"""Vigilante semanal de precios y límites: abre un PR cuando cambia una página oficial.

Dos trabajos, uno por página (REQ-020 a REQ-025 de `coste-api-y-cuota`):

- `precios`: descarga la página oficial de precios, extrae la tabla «Model pricing» y la compara
  con `src/local_delegate/resources/datos/precios.json`. Si cambia un precio, aparece un modelo o
  cambia la búsqueda web, abre (o actualiza) **un** PR en la rama fija `vigilante/precios` con la
  tabla nueva y `consultado` = hoy. Un modelo que desaparece **no** se borra: los transcripts
  viejos lo siguen necesitando, y el aviso sale en el log.
- `limites`: descarga el artículo de ayuda de límites de uso, extrae su texto normalizado y lo
  compara con `.github/vigilante/limites-de-uso.txt`. Si cambia, el PR que actualiza ese texto
  **es** el aviso, y su cuerpo dice cómo reiniciar la calibración a mano.

Falla en voz alta (código 1), nunca como «sin cambios», si una página no responde o cambia de
forma: sin cabecera, menos de 5 filas, una celda de precio ilegible, un artículo de menos de 500
caracteres o sin su título. Un parseo vacío no puede pasar por «todo igual».

Los commits van por la **API de contenidos** de GitHub y no por `git push`: el ruleset de `main`
exige commits firmados y GitHub firma los que crea esa API en nombre del bot. Como un PR abierto
con `GITHUB_TOKEN` no dispara los workflows de `pull_request`, el propio vigilante lanza por
`workflow_dispatch` los dos que exige el ruleset (`ci.yml` y `codeql.yml`), espera a que terminen
y, si el PR sigue bloqueado con todo en verde, lo dice en un comentario (REQ-025).

Solo stdlib **por diseño**, como `check_vendor.py`: el workflow no instala nada.
"""

from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

URL_PRECIOS = "https://platform.claude.com/docs/en/about-claude/pricing"
URL_LIMITES = "https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work"

RUTA_PRECIOS = "src/local_delegate/resources/datos/precios.json"
RUTA_LIMITES = ".github/vigilante/limites-de-uso.txt"

RAMA_BASE = "main"
RAMA_PRECIOS = "vigilante/precios"
RAMA_LIMITES = "vigilante/limites"
RAMA_ENSAYO = "vigilante/ensayo"
# Clave que añade el ensayo a `precios.json`; con `_` delante, como `_nota`, no es un dato.
CLAVE_ENSAYO = "_ensayo"

# Los dos workflows que contienen los checks que exige el ruleset `protect-main` (REQ-025).
WORKFLOWS_DE_CHECKS = ("ci.yml", "codeql.yml")
TECHO_ESPERA_S = 45 * 60
SONDEO_S = 30
# `update-branch` es asíncrono: GitHub hace el merge cuando puede.
TECHO_ACTUALIZACION_S = 5 * 60
# `mergeable_state` sale `unknown` mientras GitHub lo calcula.
INTENTOS_ESTADO_PR = 10

CABECERA_PRECIOS = "Model pricing"
MIN_FILAS = 5
# Filas que no son modelos con precio público en vigor. La página marca «Retired» e «Invite only»
# en el `aria-label` del botón que acompaña al nombre; «limited availability» lo nombra la spec.
MARCAS_IGNORADAS = ("retired", "limited availability", "invite only")
# Cabecera de columna de la página → campo de `precios.json`.
COLUMNAS = {
    "input": "entrada",
    "output": "salida",
    "5m writes": "w5m",
    "1h writes": "w1h",
    "hits and refreshes": "lectura",
}
CAMPOS = ("entrada", "w5m", "w1h", "lectura", "salida")
_BUSQUEDA_WEB = re.compile(
    r"Web search is available on the Claude API for \$(\d+(?:\.\d+)?) per 1,000 searches"
)
# Lo que se pone a un modelo nuevo hasta que una persona lo revise; el cuerpo del PR lo pide.
PROVISIONAL_NUEVO = {"familia": "nueva", "admite_esfuerzo": True}

TITULO_LIMITES = "How do usage and length limits work?"
MIN_CHARS_LIMITES = 500

COMANDO_REINICIO = "local-delegate recalcular-coste --reiniciar-calibracion five_hour|seven_day"

COMENTARIO_BLOQUEADO = (
    "**El vigilante no puede dejar este PR listo para mezclar.** Los checks que exige el ruleset "
    "(`ci.yml` y `codeql.yml`, lanzados por `workflow_dispatch`) terminaron en verde, pero GitHub "
    "lo sigue marcando `blocked` (la regla `code_scanning` o "
    "`require_extra_approval_for_unattributed_changes` con commits del bot).\n\n"
    "Salida a mano (REQ-025): **cierra el PR y reábrelo**. La reapertura por una persona dispara "
    "los workflows de `pull_request` con normalidad."
)

AGENTE_HTTP = "local-delegate-vigilante (+https://github.com/ZahiriNatZuke/local-delegate)"
TIMEOUT_S = 60

# Iconos de la fuente de símbolos de la página: caracteres de uso privado sin significado.
_USO_PRIVADO = re.compile("[-]")


class ErrorDelVigilante(Exception):
    """Algo no cuadra y el job tiene que terminar en error, no en «sin cambios»."""


class ErrorHTTP(ErrorDelVigilante):
    def __init__(self, estado: int, mensaje: str) -> None:
        super().__init__(f"HTTP {estado}: {mensaje}")
        self.estado = estado


def _normalizar(texto: str) -> str:
    return " ".join(_USO_PRIVADO.sub("", texto).split())


# --- Precios ----------------------------------------------------------------------------------


class _LectorTablaPrecios(HTMLParser):
    """Lee la primera `<table>` que sigue al `<h2>` «Model pricing»: filas de celdas.

    Cada celda guarda su texto (sin `<sup>`), el de sus enlaces y los `aria-label` de lo que
    contiene, que es donde la página pone «(Retired)» o «(Invite only)». El nombre del modelo es
    el texto del enlace a su ficha: al lado va una frase de presentación que no forma parte de él.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cabecera_vista = False
        self.estado = "buscando"  # buscando → tabla → hecho
        self.filas: list[list[dict]] = []
        self._en_h2 = False
        self._texto_h2: list[str] = []
        self._fila: list[dict] | None = None
        self._celda: dict | None = None
        self._en_sup = 0
        self._en_enlace = 0
        self._anidadas = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.estado == "hecho":
            return
        if self.estado == "buscando":
            if tag == "h2":
                self._en_h2 = True
                self._texto_h2 = []
            elif tag == "table" and self.cabecera_vista:
                self.estado = "tabla"
            return
        if tag == "table":
            self._anidadas += 1
        elif tag == "tr":
            self._fila = []
        elif tag in ("td", "th") and self._fila is not None:
            self._celda = {"texto": [], "enlace": [], "etiquetas": []}
        elif tag == "sup":
            self._en_sup += 1
        elif tag == "a":
            self._en_enlace += 1
        etiqueta = dict(attrs).get("aria-label")
        if self._celda is not None and etiqueta:
            self._celda["etiquetas"].append(etiqueta)

    def handle_endtag(self, tag: str) -> None:
        if self.estado == "buscando":
            if tag == "h2" and self._en_h2:
                self._en_h2 = False
                if _normalizar("".join(self._texto_h2)) == CABECERA_PRECIOS:
                    self.cabecera_vista = True
            return
        if self.estado != "tabla":
            return
        if tag == "table":
            if self._anidadas:
                self._anidadas -= 1
            else:
                self.estado = "hecho"
        elif tag == "sup":
            self._en_sup = max(0, self._en_sup - 1)
        elif tag == "a":
            self._en_enlace = max(0, self._en_enlace - 1)
        elif tag in ("td", "th") and self._celda is not None and self._fila is not None:
            self._fila.append(
                {
                    "texto": _normalizar("".join(self._celda["texto"])),
                    "enlace": _normalizar("".join(self._celda["enlace"])),
                    "etiquetas": self._celda["etiquetas"],
                }
            )
            self._celda = None
        elif tag == "tr" and self._fila is not None:
            self.filas.append(self._fila)
            self._fila = None

    def handle_data(self, data: str) -> None:
        if self._en_h2:
            self._texto_h2.append(data)
        elif self.estado == "tabla" and self._celda is not None and not self._en_sup:
            self._celda["texto"].append(data)
            if self._en_enlace:
                self._celda["enlace"].append(data)


def nombre_a_id(nombre: str) -> str:
    """«Claude Opus 4.5» → `claude-opus-4-5`; «Claude Opus 5» → `claude-opus-5` (REQ-021).

    Quita los paréntesis antes. Un nombre que no encaja en la regla es un error: mejor parar que
    inventar un id.
    """
    limpio = _normalizar(re.sub(r"\([^)]*\)", " ", nombre))
    m = re.fullmatch(r"Claude ([A-Za-z]+) (\d+)(?:\.(\d+))?", limpio)
    if m is None:
        raise ErrorDelVigilante(f"nombre de modelo que no encaja en la regla de ids: {nombre!r}")
    familia, mayor, menor = m.groups()
    partes = ["claude", familia.lower(), mayor] + ([menor] if menor else [])
    return "-".join(partes)


def _leer_precio(texto: str, modelo: str, columna: str) -> int | float:
    limpio = re.sub(r"/\s*MTok", "", texto).strip()
    m = re.fullmatch(r"\$\s*(\d+(?:\.\d+)?)", limpio)
    if m is None:
        raise ErrorDelVigilante(f"celda de precio ilegible en {modelo} / {columna}: {texto!r}")
    valor = m.group(1)
    return float(valor) if "." in valor else int(valor)


def _ignorada(celda_nombre: dict) -> bool:
    marcas = " ".join([celda_nombre["texto"], *celda_nombre["etiquetas"]]).lower()
    return any(marca in marcas for marca in MARCAS_IGNORADAS)


def extraer_tabla_precios(html: str) -> dict:
    """La tabla «Model pricing» de la página: `{"busqueda_web_por_1000", "modelos": {id: {...}}}`.

    Falla en voz alta (REQ-022) sin la cabecera, sin la tabla, con menos de 5 filas válidas o con
    una celda que no es un número. Ignora las filas «retired», «limited availability» e «invite
    only».
    """
    lector = _LectorTablaPrecios()
    lector.feed(html)
    lector.close()
    if not lector.cabecera_vista:
        raise ErrorDelVigilante(f"no aparece la cabecera «{CABECERA_PRECIOS}» en la página")
    if lector.estado == "buscando":
        raise ErrorDelVigilante(f"no hay tabla después de «{CABECERA_PRECIOS}»")

    indices: dict[str, int] | None = None
    ancho = 0
    modelos: dict[str, dict] = {}
    for fila in lector.filas:
        textos = [c["texto"].lower() for c in fila]
        if indices is None:
            if all(col in textos for col in COLUMNAS):
                indices = {campo: textos.index(col) for col, campo in COLUMNAS.items()}
                ancho = len(fila)
            continue
        if len(fila) == 1:
            continue  # separador de grupo («Additional models»)
        if len(fila) != ancho:
            raise ErrorDelVigilante(f"fila con {len(fila)} celdas, se esperaban {ancho}: {textos}")
        if _ignorada(fila[0]):
            continue
        mid = nombre_a_id(fila[0]["enlace"] or fila[0]["texto"])
        if mid in modelos:
            raise ErrorDelVigilante(f"modelo repetido en la tabla: {mid}")
        modelos[mid] = {
            campo: _leer_precio(fila[i]["texto"], mid, campo) for campo, i in indices.items()
        }
    if indices is None:
        raise ErrorDelVigilante(f"la tabla no tiene las columnas esperadas: {list(COLUMNAS)}")
    if len(modelos) < MIN_FILAS:
        raise ErrorDelVigilante(f"solo {len(modelos)} filas de precios; se esperan {MIN_FILAS}+")

    texto_plano = _normalizar(html_mod.unescape(re.sub(r"<[^>]+>", " ", html)))
    m = _BUSQUEDA_WEB.search(texto_plano)
    if m is None:
        raise ErrorDelVigilante("no aparece el precio de la búsqueda web")
    valor = m.group(1)
    busqueda = float(valor) if "." in valor else int(valor)
    return {"busqueda_web_por_1000": busqueda, "modelos": modelos}


@dataclass
class Cambios:
    """Lo que difiere entre la página y la tabla del paquete.

    `precios` son tuplas `(id, campo, viejo, nuevo)`. `desaparecidos` no cambia la tabla: se
    avisa en el log y en el PR, pero no se borra nada.
    """

    precios: list[tuple[str, str, float, float]] = field(default_factory=list)
    nuevos: list[str] = field(default_factory=list)
    desaparecidos: list[str] = field(default_factory=list)
    busqueda_web: tuple[float, float] | None = None

    @property
    def hay_cambios(self) -> bool:
        return bool(self.precios or self.nuevos or self.busqueda_web)


def comparar(nueva: dict, paquete: dict) -> Cambios:
    """Compara la tabla extraída con la del paquete, campo a campo y por valor numérico."""
    cambios = Cambios()
    viejos = paquete["modelos"]
    for mid, precios in nueva["modelos"].items():
        if mid not in viejos:
            cambios.nuevos.append(mid)
            continue
        for campo in CAMPOS:
            if float(precios[campo]) != float(viejos[mid][campo]):
                cambios.precios.append((mid, campo, viejos[mid][campo], precios[campo]))
    cambios.desaparecidos = [mid for mid in viejos if mid not in nueva["modelos"]]
    antes, ahora = paquete["busqueda_web_por_1000"], nueva["busqueda_web_por_1000"]
    if float(antes) != float(ahora):
        cambios.busqueda_web = (antes, ahora)
    return cambios


def tabla_actualizada(paquete: dict, nueva: dict, cambios: Cambios, hoy: dt.date) -> dict:
    """La tabla del paquete con los cambios aplicados y `consultado` = hoy. No borra modelos."""
    tabla = copy.deepcopy(paquete)
    for mid, campo, _viejo, valor in cambios.precios:
        tabla["modelos"][mid][campo] = valor
    for mid in cambios.nuevos:
        tabla["modelos"][mid] = {**nueva["modelos"][mid], **PROVISIONAL_NUEVO}
    if cambios.busqueda_web is not None:
        tabla["busqueda_web_por_1000"] = cambios.busqueda_web[1]
    tabla["consultado"] = hoy.isoformat()
    return tabla


_LINEA_MODELO = re.compile(r'^\s*"([^"]+)": (\{.*\}),?\s*$')


def serializar_precios(tabla: dict, original: str) -> str:
    """`precios.json` con el formato del repo: una línea por modelo.

    Las líneas de los modelos que no cambian se copian **tal cual** del original (con su `0.20`),
    para que el diff del PR enseñe solo lo que cambió.
    """
    lineas_originales: dict[str, str] = {}
    datos_originales = json.loads(original).get("modelos", {})
    for linea in original.splitlines():
        m = _LINEA_MODELO.match(linea)
        if m and m.group(1) in datos_originales:
            lineas_originales[m.group(1)] = m.group(2)

    def _valor(v: object) -> str:
        return json.dumps(v, ensure_ascii=False)

    salida = ["{"]
    claves = list(tabla)
    for k in claves:
        coma = "," if k != claves[-1] else ""
        if k != "modelos":
            salida.append(f"  {_valor(k)}: {_valor(tabla[k])}{coma}")
            continue
        salida.append('  "modelos": {')
        ids = list(tabla["modelos"])
        for mid in ids:
            entrada = tabla["modelos"][mid]
            if mid in lineas_originales and datos_originales.get(mid) == entrada:
                cuerpo = lineas_originales[mid]
            else:
                cuerpo = json.dumps(entrada, ensure_ascii=False, separators=(", ", ": "))
            salida.append(f"    {_valor(mid)}: {cuerpo}{',' if mid != ids[-1] else ''}")
        salida.append(f"  }}{coma}")
    salida.append("}")
    return "\n".join(salida) + "\n"


def cuerpo_pr_precios(cambios: Cambios, *, ensayo: bool = False) -> str:
    lineas = []
    if ensayo:
        lineas += [
            (
                "> **[ensayo]** PR de prueba del vigilante (T11 de `coste-api-y-cuota`): solo "
                "añade la marca `_ensayo` a la tabla. **No mezclar**: se cierra sin mezclar y se "
                "borra la rama."
            ),
            "",
        ]
    lineas += [
        (
            f"La página oficial de precios ({URL_PRECIOS}) ya no coincide con "
            f"`{RUTA_PRECIOS}`. Este PR lo abre el vigilante semanal."
        ),
        "",
    ]
    if cambios.precios:
        lineas += ["### Precios que cambian (USD/MTok)", "", "| Modelo | Campo | Antes | Ahora |"]
        lineas.append("|---|---|---:|---:|")
        lineas += [f"| `{m}` | {c} | {a} | {n} |" for m, c, a, n in cambios.precios]
        lineas.append("")
    if cambios.busqueda_web is not None:
        antes, ahora = cambios.busqueda_web
        lineas += [f"### Búsqueda web: de ${antes} a ${ahora} por cada 1000 búsquedas", ""]
    if cambios.nuevos:
        lineas += ["### Modelos nuevos: revísalos a mano", ""]
        lineas += [f"- `{m}`" for m in cambios.nuevos]
        lineas += [
            "",
            (
                "El id se deduce del nombre comercial (la página no trae ids): compáralo con "
                "«Models overview» y «Model IDs and versioning». `familia` y `admite_esfuerzo` "
                f"van provisionales ({PROVISIONAL_NUEVO['familia']} / "
                f"{str(PROVISIONAL_NUEVO['admite_esfuerzo']).lower()}): corrígelos antes de "
                "mezclar."
            ),
            "",
        ]
    if cambios.desaparecidos:
        lineas += ["### Modelos que ya no salen en la página (siguen en la tabla)", ""]
        lineas += [f"- `{m}`" for m in cambios.desaparecidos]
        lineas += [
            "",
            "No se borran: los transcripts viejos los siguen necesitando para valorar el coste.",
            "",
        ]
    lineas += [
        (
            "Los checks del ruleset (`ci.yml` y `codeql.yml`) los lanza el propio vigilante por "
            "`workflow_dispatch`; los commits van por la API de contenidos, que los firma."
        ),
    ]
    return "\n".join(lineas) + "\n"


# --- Límites ----------------------------------------------------------------------------------

_BLOQUES = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "tr", "br", "ul", "ol", "table"}


class _LectorArticulo(HTMLParser):
    """El título (`<h1>`) y el texto del primer `<article>`, con un salto por bloque."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titulo: str | None = None
        self.trozos: list[str] = []
        self._en_h1 = False
        self._h1: list[str] = []
        self._profundidad = 0  # dentro del <article>
        self._terminado = False
        self._ignorar = 0  # <script>/<style>

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._ignorar += 1
        elif tag == "h1" and self.titulo is None:
            self._en_h1 = True
        elif tag == "article" and not self._terminado:
            self._profundidad += 1
        if self._profundidad and tag in _BLOQUES:
            self.trozos.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._ignorar = max(0, self._ignorar - 1)
        elif tag == "h1" and self._en_h1:
            self._en_h1 = False
            self.titulo = _normalizar("".join(self._h1))
        elif tag == "article" and self._profundidad:
            self._profundidad -= 1
            if not self._profundidad:
                self._terminado = True
        if self._profundidad and tag in _BLOQUES:
            self.trozos.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignorar:
            return
        if self._en_h1:
            self._h1.append(data)
        if self._profundidad:
            self.trozos.append(data)


def extraer_texto_limites(html: str) -> str:
    """El artículo de límites como texto: título, línea en blanco y un párrafo por línea.

    Sin HTML y con los espacios colapsados (REQ-023). Falla en voz alta sin el título o con menos
    de 500 caracteres de artículo.
    """
    lector = _LectorArticulo()
    lector.feed(html)
    lector.close()
    if lector.titulo != TITULO_LIMITES:
        raise ErrorDelVigilante(
            f"no aparece el título «{TITULO_LIMITES}» (h1 leído: {lector.titulo!r})"
        )
    parrafos = [_normalizar(p) for p in "".join(lector.trozos).split("\n")]
    cuerpo = "\n".join(p for p in parrafos if p)
    if len(cuerpo) < MIN_CHARS_LIMITES:
        raise ErrorDelVigilante(
            f"el artículo de límites tiene {len(cuerpo)} caracteres; se esperan "
            f"{MIN_CHARS_LIMITES}+"
        )
    return f"{TITULO_LIMITES}\n\n{cuerpo}\n"


def cuerpo_pr_limites() -> str:
    return (
        f"Ha cambiado el artículo de límites de uso ({URL_LIMITES}). El diff de "
        f"`{RUTA_LIMITES}` **es** el aviso: léelo y decide si los límites de cuota cambiaron.\n\n"
        "Si cambiaron, la calibración de la cuota hecha con los límites viejos deja de valer. "
        "Reiníciala a mano en cada máquina, para el tipo de ventana afectado (REQ-057):\n\n"
        f"```\n{COMANDO_REINICIO}\n```\n\n"
        "Mezcla el PR para que el vigilante compare la semana que viene contra este texto. Los "
        "checks del ruleset los lanza el propio vigilante por `workflow_dispatch`.\n"
    )


# --- GitHub -----------------------------------------------------------------------------------

Api = Callable[..., object]


def cliente_github(token: str, base: str = "https://api.github.com") -> Api:
    """`api(metodo, ruta, cuerpo=None)` sobre la REST de GitHub. Un error HTTP lanza `ErrorHTTP`."""

    def api(metodo: str, ruta: str, cuerpo: dict | None = None) -> object:
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
        peticion = urllib.request.Request(
            base + ruta,
            data=datos,
            method=metodo,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": AGENTE_HTTP,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(peticion, timeout=TIMEOUT_S) as respuesta:
                crudo = respuesta.read()
        except urllib.error.HTTPError as exc:
            detalle = exc.read()[:500].decode("utf-8", errors="replace")
            raise ErrorHTTP(exc.code, f"{metodo} {ruta}: {detalle}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ErrorDelVigilante(f"{metodo} {ruta}: sin respuesta de GitHub ({exc})") from exc
        return json.loads(crudo) if crudo else None

    return api


def descargar(url: str, intentos: int = 2) -> str:
    """El HTML de la página. Si no responde tras `intentos`, error (REQ-022)."""
    ultimo: Exception | None = None
    for intento in range(intentos):
        peticion = urllib.request.Request(url, headers={"User-Agent": AGENTE_HTTP})
        try:
            with urllib.request.urlopen(peticion, timeout=TIMEOUT_S) as respuesta:
                juego = respuesta.headers.get_content_charset() or "utf-8"
                return respuesta.read().decode(juego, errors="replace")
        except (urllib.error.URLError, OSError) as exc:
            ultimo = exc
            if intento + 1 < intentos:
                time.sleep(10)
    raise ErrorDelVigilante(f"la página {url} no responde: {ultimo}")


def _iso(segundos: float) -> str:
    return dt.datetime.fromtimestamp(segundos, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Contexto:
    api: Api
    repo: str
    dormir: Callable[[float], None] = time.sleep
    reloj: Callable[[], float] = time.time

    @property
    def r(self) -> str:
        return f"/repos/{self.repo}"


def _preparar_rama(ctx: Contexto, rama: str, sha_base: str) -> None:
    """La rama, recién salida de `main`. Si quedó de un PR ya cerrado, se reinicia."""
    try:
        ctx.api("GET", f"{ctx.r}/git/ref/heads/{rama}")
    except ErrorHTTP as exc:
        if exc.estado != 404:
            raise
        ctx.api("POST", f"{ctx.r}/git/refs", {"ref": f"refs/heads/{rama}", "sha": sha_base})
        return
    ctx.api("PATCH", f"{ctx.r}/git/refs/heads/{rama}", {"sha": sha_base, "force": True})


def _escribir(ctx: Contexto, rama: str, ruta: str, contenido: str, mensaje: str) -> bool:
    """Un commit por la API de contenidos (firmado por GitHub). `False` si ya estaba igual."""
    sha = None
    try:
        actual = ctx.api("GET", f"{ctx.r}/contents/{ruta}?ref={urllib.parse.quote(rama)}")
    except ErrorHTTP as exc:
        if exc.estado != 404:
            raise
    else:
        sha = actual["sha"]
        if base64.b64decode(actual.get("content", "")).decode("utf-8") == contenido:
            return False
    cuerpo = {
        "message": mensaje,
        "content": base64.b64encode(contenido.encode("utf-8")).decode("ascii"),
        "branch": rama,
    }
    if sha is not None:
        cuerpo["sha"] = sha
    ctx.api("PUT", f"{ctx.r}/contents/{ruta}", cuerpo)
    return True


def _actualizar_si_va_detras(ctx: Contexto, rama: str, numero: int) -> None:
    """Si `main` avanzó, «update branch» (el commit lo hace GitHub) y espera al head nuevo."""
    comparacion = ctx.api("GET", f"{ctx.r}/compare/{RAMA_BASE}...{rama}")
    if not comparacion.get("behind_by"):
        return
    antes = ctx.api("GET", f"{ctx.r}/pulls/{numero}")["head"]["sha"]
    ctx.api("PUT", f"{ctx.r}/pulls/{numero}/update-branch", {"expected_head_sha": antes})
    limite = ctx.reloj() + TECHO_ACTUALIZACION_S
    while ctx.api("GET", f"{ctx.r}/pulls/{numero}")["head"]["sha"] == antes:
        if ctx.reloj() >= limite:
            raise ErrorDelVigilante(f"la rama {rama} no se actualizó con {RAMA_BASE} a tiempo")
        ctx.dormir(SONDEO_S)


def _lanzar_y_esperar_checks(ctx: Contexto, rama: str, sha: str) -> None:
    """Lanza `ci.yml` y `codeql.yml` sobre la rama y espera a que terminen en verde."""
    inicio = ctx.reloj()
    for wf in WORKFLOWS_DE_CHECKS:
        ctx.api("POST", f"{ctx.r}/actions/workflows/{wf}/dispatches", {"ref": rama})
    # Margen para relojes desfasados; descarta runs de semanas anteriores sobre el mismo sha.
    desde = _iso(inicio - 120)
    limite = inicio + TECHO_ESPERA_S
    while True:
        runs = ctx.api(
            "GET", f"{ctx.r}/actions/runs?head_sha={sha}&event=workflow_dispatch&per_page=50"
        )["workflow_runs"]
        ultimos: dict[str, dict] = {}
        for run in runs:  # la API los da del más nuevo al más viejo
            wf = run.get("path", "").split("@")[0].rsplit("/", 1)[-1]
            if wf in WORKFLOWS_DE_CHECKS and run.get("created_at", "") >= desde:
                ultimos.setdefault(wf, run)
        terminados = [r for r in ultimos.values() if r.get("status") == "completed"]
        if len(terminados) == len(WORKFLOWS_DE_CHECKS):
            break
        if ctx.reloj() >= limite:
            raise ErrorDelVigilante(
                f"los checks no terminaron en {TECHO_ESPERA_S // 60} min: {sorted(ultimos)}"
            )
        ctx.dormir(SONDEO_S)
    rojos = {wf: r.get("conclusion") for wf, r in ultimos.items() if r["conclusion"] != "success"}
    if rojos:
        raise ErrorDelVigilante(f"checks del PR sin éxito: {rojos}")


def _avisar_si_bloqueado(ctx: Contexto, numero: int) -> str | None:
    estado = None
    for intento in range(INTENTOS_ESTADO_PR):
        estado = ctx.api("GET", f"{ctx.r}/pulls/{numero}").get("mergeable_state")
        if estado != "unknown":
            break
        if intento + 1 < INTENTOS_ESTADO_PR:
            ctx.dormir(SONDEO_S)
    if estado == "blocked":
        ctx.api("POST", f"{ctx.r}/issues/{numero}/comments", {"body": COMENTARIO_BLOQUEADO})
    return estado


def proponer(
    ctx: Contexto, rama: str, ficheros: dict[str, str], titulo: str, cuerpo: str, mensaje: str
) -> int | None:
    """Abre o actualiza el PR de `rama` con `ficheros` y deja lanzados y vistos sus checks."""
    sha_main = ctx.api("GET", f"{ctx.r}/git/ref/heads/{RAMA_BASE}")["object"]["sha"]
    dueno = ctx.repo.split("/")[0]
    cabeza = urllib.parse.quote(f"{dueno}:{rama}")
    abiertos = ctx.api("GET", f"{ctx.r}/pulls?state=open&head={cabeza}&base={RAMA_BASE}")
    pr = abiertos[0] if abiertos else None
    if pr is None:
        _preparar_rama(ctx, rama, sha_main)
    escritos = [
        ruta for ruta, texto in ficheros.items() if _escribir(ctx, rama, ruta, texto, mensaje)
    ]
    if pr is None:
        if not escritos:
            print(f"La rama {rama} ya coincide con {RAMA_BASE}: no hay PR que abrir.")
            return None
        pr = ctx.api(
            "POST",
            f"{ctx.r}/pulls",
            {"title": titulo, "head": rama, "base": RAMA_BASE, "body": cuerpo},
        )
        print(f"PR abierto: #{pr['number']}")
    else:
        ctx.api("PATCH", f"{ctx.r}/pulls/{pr['number']}", {"title": titulo, "body": cuerpo})
        print(f"PR actualizado: #{pr['number']}")
    numero = pr["number"]
    _actualizar_si_va_detras(ctx, rama, numero)
    sha = ctx.api("GET", f"{ctx.r}/pulls/{numero}")["head"]["sha"]
    _lanzar_y_esperar_checks(ctx, rama, sha)
    estado = _avisar_si_bloqueado(ctx, numero)
    print(f"Checks en verde; estado del PR: {estado}")
    return numero


# --- Trabajos ---------------------------------------------------------------------------------


def marca_de_ensayo(id_run: str) -> str:
    """El valor de `_ensayo`: distinto en cada run, para que el ensayo siempre tenga diff."""
    return f"PR de prueba del vigilante (run {id_run or 'local'}): no mezclar"


def trabajo_precios(
    ctx: Contexto,
    html: str,
    raiz: Path,
    hoy: dt.date,
    *,
    ensayo: bool = False,
    id_run: str = "",
) -> int | None:
    nueva = extraer_tabla_precios(html)
    original = (raiz / RUTA_PRECIOS).read_text(encoding="utf-8")
    paquete = json.loads(original)
    cambios = comparar(nueva, paquete)
    for mid in cambios.desaparecidos:
        print(f"AVISO: {mid} ya no sale en la página; se queda en la tabla.")
    if ensayo:
        # Un diff inocuo y forzado para probar el circuito entero en GitHub (T11). No toca
        # `consultado` (REQ-010: fecha del último cambio real), que el día en que se mezcló la
        # tabla ya vale hoy y no daría diff: añade una marca `_ensayo` con el id del run, que
        # cambia en cada ejecución y que la carga de la tabla ignora como ignora `_nota`.
        tabla = {CLAVE_ENSAYO: marca_de_ensayo(id_run), **copy.deepcopy(paquete)}
        rama, titulo = RAMA_ENSAYO, "[ensayo] Vigilante de precios: prueba del circuito"
    elif not cambios.hay_cambios:
        print("Precios: sin cambios.")
        return None
    else:
        tabla = tabla_actualizada(paquete, nueva, cambios, hoy)
        rama, titulo = RAMA_PRECIOS, "Vigilante de precios: la página oficial ha cambiado"
    contenido = serializar_precios(tabla, original)
    if contenido == original:
        raise ErrorDelVigilante("la tabla propuesta es idéntica a la del paquete: no hay diff")
    return proponer(
        ctx,
        rama,
        {RUTA_PRECIOS: contenido},
        titulo,
        cuerpo_pr_precios(cambios, ensayo=ensayo),
        f"chore(precios): tabla según la página oficial del {hoy.isoformat()}",
    )


def trabajo_limites(ctx: Contexto, html: str, raiz: Path) -> int | None:
    texto = extraer_texto_limites(html)
    guardado_ruta = raiz / RUTA_LIMITES
    guardado = guardado_ruta.read_text(encoding="utf-8") if guardado_ruta.is_file() else ""
    if texto == guardado:
        print("Límites: sin cambios.")
        return None
    return proponer(
        ctx,
        RAMA_LIMITES,
        {RUTA_LIMITES: texto},
        "Vigilante de límites: el artículo de límites de uso ha cambiado",
        cuerpo_pr_limites(),
        "chore(limites): texto del artículo de límites de uso",
    )


def main(
    argv: list[str] | None = None,
    *,
    api: Api | None = None,
    bajar: Callable[[str], str] = descargar,
    hoy: dt.date | None = None,
    dormir: Callable[[float], None] = time.sleep,
    reloj: Callable[[], float] = time.time,
    raiz: Path = RAIZ,
    entorno: dict[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("trabajo", choices=("precios", "limites"))
    args = parser.parse_args(argv)
    entorno = dict(os.environ) if entorno is None else entorno
    ensayo = entorno.get("VIGILANTE_ENSAYO", "").strip().lower() == "true"
    hoy = hoy or dt.datetime.now(dt.UTC).date()
    try:
        repo = entorno.get("GITHUB_REPOSITORY", "")
        if "/" not in repo:
            raise ErrorDelVigilante("falta GITHUB_REPOSITORY (dueño/repo)")
        if api is None:
            token = entorno.get("GITHUB_TOKEN", "")
            if not token:
                raise ErrorDelVigilante("falta GITHUB_TOKEN")
            api = cliente_github(token)
        ctx = Contexto(api=api, repo=repo, dormir=dormir, reloj=reloj)
        if args.trabajo == "precios":
            trabajo_precios(
                ctx,
                bajar(URL_PRECIOS),
                raiz,
                hoy,
                ensayo=ensayo,
                id_run=entorno.get("GITHUB_RUN_ID", "").strip(),
            )
        else:
            trabajo_limites(ctx, bajar(URL_LIMITES), raiz)
    except ErrorDelVigilante as exc:
        print(f"FALLO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
