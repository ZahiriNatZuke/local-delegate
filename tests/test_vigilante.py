"""Pruebas de `scripts/vigilante_precios.py`, el vigilante semanal de precios y límites.

Sin red (REQ-024): las dos páginas oficiales están guardadas en `tests/fixtures/vigilante/` y lo
que se espera de ellas va **congelado en este fichero**, no leído de la tabla del paquete. Así el
PR del vigilante, que cambia la tabla del paquete, no rompe estas pruebas.

El flujo de GitHub se prueba con un cliente `api` falso que registra cada llamada: lo que importa
es que el commit vaya por la API de contenidos (que lo firma), que se lancen los dos workflows del
ruleset y que el PR existente se actualice en vez de abrir otro.
"""

from __future__ import annotations

import ast
import base64
import datetime as dt
import functools
import importlib.util
import json
import secrets
import sys
import uuid
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).parents[1]
SCRIPT = RAIZ / "scripts" / "vigilante_precios.py"
FIXTURES = Path(__file__).parent / "fixtures" / "vigilante"
WORKFLOWS = RAIZ / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "vigilante-precios.yml"

# Mismo criterio que en `test_ci_gate.py`: `scripts/` no viaja en el sdist.
if not SCRIPT.is_file():
    pytest.skip("scripts/ no está en el árbol (sdist)", allow_module_level=True)


@functools.cache
def _v():
    """El script, cargado a demanda: el test de «solo stdlib» no debe depender de que cargue."""
    spec = importlib.util.spec_from_file_location("vigilante_precios", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["vigilante_precios"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


# --- Lo esperado, congelado ---------------------------------------------------------------------

# La tabla que da `precios.html` tal como se guardó el 2026-10-06. Trece modelos: fuera los cuatro
# «Retired» (Opus 4.1, Opus 4, Sonnet 4, Haiku 3.5) y los dos «Invite only» (Mythos 5.1 y 5).
_P = ("entrada", "salida", "w5m", "w1h", "lectura")
ESPERADA = {
    "busqueda_web_por_1000": 10,
    "modelos": {
        mid: dict(zip(_P, valores, strict=True))
        for mid, valores in {
            "claude-fable-5-1": (10, 50, 12.5, 20, 0.25),
            "claude-opus-5-5": (4, 20, 5, 8, 0.20),
            "claude-sonnet-5-5": (2, 10, 2.5, 4, 0.20),
            "claude-haiku-4-5": (1, 5, 1.25, 2, 0.10),
            "claude-fable-5": (10, 50, 12.5, 20, 1),
            "claude-opus-5": (5, 25, 6.25, 10, 0.50),
            "claude-opus-4-8": (5, 25, 6.25, 10, 0.50),
            "claude-opus-4-7": (5, 25, 6.25, 10, 0.50),
            "claude-opus-4-6": (5, 25, 6.25, 10, 0.50),
            "claude-opus-4-5": (5, 25, 6.25, 10, 0.50),
            "claude-sonnet-5": (2, 10, 2.5, 4, 0.20),
            "claude-sonnet-4-6": (3, 15, 3.75, 6, 0.30),
            "claude-sonnet-4-5": (3, 15, 3.75, 6, 0.30),
        }.items()
    },
}

# Una tabla «del paquete» congelada, con la forma de `precios.json`, igual a la página guardada.
PAQUETE = {
    "fuente": "https://platform.claude.com/docs/en/about-claude/pricing",
    "consultado": "2026-10-06",
    "busqueda_web_por_1000": 10,
    "modelos": {
        mid: {**precios, "familia": "nueva", "admite_esfuerzo": True}
        for mid, precios in ESPERADA["modelos"].items()
    },
}

HOY = dt.date(2026, 10, 12)
NUEVO = 0.30


def _pagina_precios() -> str:
    return (FIXTURES / "precios.html").read_text(encoding="utf-8")


def _pagina_limites() -> str:
    return (FIXTURES / "limites.html").read_text(encoding="utf-8")


def _tabla_html(html: str) -> tuple[int, int]:
    inicio = html.index("<table", html.index('<h2 id="model-pricing"'))
    return inicio, html.index("</table>", inicio)


def _fila(html: str, nombre: str) -> tuple[int, int]:
    """Inicio y fin (exclusivo) del `<tr>` de la tabla de precios cuyo enlace es `nombre`."""
    inicio, fin = _tabla_html(html)
    pos = html.index(f"{nombre}</a>", inicio, fin)
    desde = html.rindex("<tr", inicio, pos)
    hasta = html.index("</tr>", pos) + len("</tr>")
    return desde, hasta


def _cambiar_en_fila(html: str, nombre: str, viejo: str, nuevo: str) -> str:
    desde, hasta = _fila(html, nombre)
    fila = html[desde:hasta]
    assert viejo in fila, f"{viejo!r} no está en la fila de {nombre}: la copia guardada cambió"
    return html[:desde] + fila.replace(viejo, nuevo, 1) + html[hasta:]


# --- Precios: la extracción ---------------------------------------------------------------------


def test_la_pagina_intacta_da_la_tabla_congelada():
    tabla = _v().extraer_tabla_precios(_pagina_precios())
    assert tabla == ESPERADA


def test_la_copia_guardada_tiene_filas_que_ignorar():
    """Guarda del test anterior: sin filas «Retired» no probaría que se ignoran."""
    html = _pagina_precios()
    inicio, fin = _tabla_html(html)
    assert 'aria-label="Claude Opus 4.1 (Retired)"' in html[inicio:fin]
    assert 'aria-label="Claude Mythos 5.1 (Invite only)"' in html[inicio:fin]


def test_una_nota_al_pie_en_el_nombre_no_cambia_el_id():
    html = _cambiar_en_fila(
        _pagina_precios(),
        "Claude Opus 5.5",
        "Claude Opus 5.5</a>",
        "Claude Opus 5.5<sup>1</sup></a>",
    )
    assert "claude-opus-5-5" in _v().extraer_tabla_precios(html)["modelos"]


@pytest.mark.parametrize(
    ("nombre", "esperado"),
    [
        ("Claude Opus 4.5", "claude-opus-4-5"),
        ("Claude Opus 5", "claude-opus-5"),
        ("Claude Fable 5.1 (new)", "claude-fable-5-1"),
    ],
)
def test_nombre_a_id(nombre, esperado):
    assert _v().nombre_a_id(nombre) == esperado


def test_un_nombre_fuera_de_la_regla_falla():
    with pytest.raises(_v().ErrorDelVigilante):
        _v().nombre_a_id("Opus Ultra")


def test_un_precio_cambiado_da_ese_diff():
    v = _v()
    html = _cambiar_en_fila(_pagina_precios(), "Claude Opus 5.5", "$0.20", f"${NUEVO:.2f}")
    cambios = v.comparar(v.extraer_tabla_precios(html), PAQUETE)
    assert cambios.precios == [("claude-opus-5-5", "lectura", 0.20, NUEVO)]
    assert cambios.nuevos == [] and cambios.desaparecidos == []
    assert cambios.hay_cambios


def test_la_pagina_intacta_no_da_cambios():
    v = _v()
    cambios = v.comparar(v.extraer_tabla_precios(_pagina_precios()), PAQUETE)
    assert not cambios.hay_cambios
    assert cambios.precios == [] and cambios.desaparecidos == []


def _con_modelo_nuevo(html: str) -> str:
    desde, hasta = _fila(html, "Claude Opus 5.5")
    copia = html[desde:hasta].replace("Claude Opus 5.5</a>", "Claude Nuevo 9</a>")
    return html[:hasta] + copia + html[hasta:]


def test_un_modelo_nuevo_sale_listado_en_el_pr():
    v = _v()
    cambios = v.comparar(v.extraer_tabla_precios(_con_modelo_nuevo(_pagina_precios())), PAQUETE)
    assert cambios.nuevos == ["claude-nuevo-9"]
    cuerpo = v.cuerpo_pr_precios(cambios)
    assert "claude-nuevo-9" in cuerpo
    tabla = v.tabla_actualizada(
        PAQUETE, v.extraer_tabla_precios(_con_modelo_nuevo(_pagina_precios())), cambios, HOY
    )
    assert tabla["modelos"]["claude-nuevo-9"]["entrada"] == 4
    assert tabla["consultado"] == HOY.isoformat()


def test_un_modelo_que_desaparece_no_se_borra():
    v = _v()
    html = _pagina_precios()
    desde, hasta = _fila(html, "Claude Opus 4.5")
    html = html[:desde] + html[hasta:]
    html = _cambiar_en_fila(html, "Claude Opus 5.5", "$0.20", f"${NUEVO:.2f}")
    nueva = v.extraer_tabla_precios(html)
    assert "claude-opus-4-5" not in nueva["modelos"]  # guarda: de verdad desapareció
    cambios = v.comparar(nueva, PAQUETE)
    assert cambios.desaparecidos == ["claude-opus-4-5"]
    resultado = v.tabla_actualizada(PAQUETE, nueva, cambios, HOY)
    assert "claude-opus-4-5" in resultado["modelos"]
    assert resultado["modelos"]["claude-opus-5-5"]["lectura"] == NUEVO
    assert "claude-opus-4-5" in v.cuerpo_pr_precios(cambios)


def test_sin_cabecera_falla():
    v = _v()
    html = _pagina_precios().replace(
        '<h2 id="model-pricing" class="group">Model pricing',
        '<h2 id="model-pricing" class="group">Model prices',
    )
    with pytest.raises(v.ErrorDelVigilante, match="cabecera"):
        v.extraer_tabla_precios(html)


def test_menos_de_5_filas_falla():
    v = _v()
    html = _pagina_precios()
    inicio, fin = _tabla_html(html)
    grupo = html.index("<tbody id=", inicio, fin)
    cierre = html.index("</tbody>", grupo) + len("</tbody>")
    recortada = html[:grupo] + html[cierre:]  # quedan las cuatro filas destacadas
    with pytest.raises(v.ErrorDelVigilante, match="filas"):
        v.extraer_tabla_precios(recortada)


def test_una_celda_que_no_es_numero_falla():
    v = _v()
    html = _cambiar_en_fila(_pagina_precios(), "Claude Opus 5.5", "$4<!--", "Consultar<!--")
    with pytest.raises(v.ErrorDelVigilante, match="ilegible"):
        v.extraer_tabla_precios(html)


def test_serializar_conserva_el_formato_del_paquete():
    """El PR solo debe enseñar lo que cambia: el `0.20` del fichero no se reescribe como `0.2`."""
    v = _v()
    original = (RAIZ / v.RUTA_PRECIOS).read_text(encoding="utf-8")
    tabla = json.loads(original)
    assert v.serializar_precios(tabla, original) == original
    primero = next(iter(tabla["modelos"]))
    tabla["modelos"][primero]["salida"] = 999
    tabla["consultado"] = HOY.isoformat()
    distintas = [
        (a, b)
        for a, b in zip(
            original.splitlines(), v.serializar_precios(tabla, original).splitlines(), strict=True
        )
        if a != b
    ]
    assert len(distintas) == 2
    assert HOY.isoformat() in distintas[0][1] and "999" in distintas[1][1]


# --- Límites ------------------------------------------------------------------------------------


def _limites_esperado() -> str:
    return (FIXTURES / "limites-esperado.txt").read_text(encoding="utf-8")


def test_limites_intacta_da_el_texto_esperado():
    assert _v().extraer_texto_limites(_pagina_limites()) == _limites_esperado()


def test_limites_con_un_parrafo_cambiado_da_diff():
    v = _v()
    viejo = "Think of this as your"
    html = _pagina_limites()
    assert viejo in html
    texto = v.extraer_texto_limites(html.replace(viejo, "Picture this as your", 1))
    distintas = [
        b
        for a, b in zip(_limites_esperado().splitlines(), texto.splitlines(), strict=True)
        if a != b
    ]
    assert len(distintas) == 1 and "Picture this as your" in distintas[0]


def test_limites_vaciada_falla():
    v = _v()
    html = _pagina_limites()
    inicio = html.index(">", html.index("<article")) + 1
    fin = html.index("</article>")
    vaciada = html[:inicio] + "<p>Pronto volvemos.</p>" + html[fin:]
    with pytest.raises(v.ErrorDelVigilante, match="caracteres"):
        v.extraer_texto_limites(vaciada)


def test_limites_sin_titulo_falla():
    v = _v()
    h1 = f">{v.TITULO_LIMITES}</h1>"
    assert h1 in _pagina_limites()
    html = _pagina_limites().replace(h1, ">Otra cosa</h1>")
    with pytest.raises(v.ErrorDelVigilante, match="título"):
        v.extraer_texto_limites(html)


def test_el_pr_de_limites_dice_como_reiniciar():
    cuerpo = _v().cuerpo_pr_limites()
    assert "recalcular-coste --reiniciar-calibracion" in cuerpo


# --- El flujo de GitHub, con un cliente falso ---------------------------------------------------

REPO = "o/r"
RUTA_CONTENIDOS_PRECIOS = f"/repos/{REPO}/contents/src/local_delegate/resources/datos/precios.json"


class FalsoGitHub:
    """La REST de GitHub en memoria: lo justo para el flujo del vigilante."""

    def __init__(
        self, reloj, *, pr_abierto=False, behind_by=0, estado="clean", conclusion="success"
    ):
        self.reloj = reloj
        self.llamadas: list[tuple[str, str]] = []
        self.cuerpos: list[object] = []
        self.pr = {"number": 7} if pr_abierto else None
        self.rama_existe = pr_abierto
        self.behind_by = behind_by
        self.estado = estado
        self.conclusion = conclusion
        self.head = "sha-1"
        self.runs: list[dict] = []
        self.ficheros: dict[str, str] = {}

    def __call__(self, metodo, ruta, cuerpo=None):
        v = _v()
        self.llamadas.append((metodo, ruta))
        self.cuerpos.append(cuerpo)
        b = f"/repos/{REPO}"
        camino, _, consulta = ruta.partition("?")
        if metodo == "GET" and camino == f"{b}/git/ref/heads/main":
            return {"object": {"sha": "sha-main"}}
        if metodo == "GET" and camino.startswith(f"{b}/git/ref/heads/"):
            if self.rama_existe:
                return {"object": {"sha": self.head}}
            raise v.ErrorHTTP(404, "Not Found")
        if metodo == "POST" and camino == f"{b}/git/refs":
            self.rama_existe = True
            return {}
        if metodo == "PATCH" and camino.startswith(f"{b}/git/refs/heads/"):
            return {}
        if metodo == "GET" and camino == f"{b}/pulls":
            return [self.pr] if self.pr else []
        if metodo == "GET" and camino.startswith(f"{b}/contents/"):
            texto = self.ficheros[camino.removeprefix(f"{b}/contents/")]
            return {"sha": "blob-1", "content": base64.b64encode(texto.encode()).decode()}
        if metodo == "PUT" and camino.startswith(f"{b}/contents/"):
            self.head = "sha-2"
            return {}
        if metodo == "POST" and camino == f"{b}/pulls":
            self.pr = {"number": 7}
            return dict(self.pr)
        if metodo == "PATCH" and camino == f"{b}/pulls/7":
            return {}
        if metodo == "GET" and camino.startswith(f"{b}/compare/"):
            return {"behind_by": self.behind_by}
        if metodo == "PUT" and camino == f"{b}/pulls/7/update-branch":
            self.behind_by = 0
            self.head = "sha-actualizado"
            return {}
        if metodo == "GET" and camino == f"{b}/pulls/7":
            return {"number": 7, "head": {"sha": self.head}, "mergeable_state": self.estado}
        if metodo == "POST" and camino.endswith("/dispatches"):
            wf = camino.split("/")[-2]
            self.runs.insert(
                0,
                {
                    "path": f".github/workflows/{wf}",
                    "created_at": v._iso(self.reloj()),
                    "status": "completed",
                    "conclusion": self.conclusion,
                    "head_sha": self.head,
                },
            )
            return None
        if metodo == "GET" and camino == f"{b}/actions/runs":
            sha = dict(p.split("=", 1) for p in consulta.split("&"))["head_sha"]
            return {"workflow_runs": [r for r in self.runs if r["head_sha"] == sha]}
        if metodo == "POST" and camino == f"{b}/issues/7/comments":
            return {}
        raise AssertionError(f"llamada inesperada: {metodo} {ruta}")

    def despachados(self) -> set[str]:
        return {r.split("/")[-2] for m, r in self.llamadas if r.endswith("/dispatches")}


@pytest.fixture
def raiz(tmp_path):
    """Un repo de mentira con la tabla congelada: el test no depende de la del paquete."""
    v = _v()
    ruta = tmp_path / v.RUTA_PRECIOS
    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps(PAQUETE, indent=2) + "\n", encoding="utf-8")
    limites = tmp_path / v.RUTA_LIMITES
    limites.parent.mkdir(parents=True)
    limites.write_text(_limites_esperado(), encoding="utf-8")
    return tmp_path


def _correr(raiz, trabajo, pagina, **opciones):
    v = _v()
    t = [1_790_000_000.0]
    falso = FalsoGitHub(lambda: t[0], **opciones)
    falso.ficheros = {
        v.RUTA_PRECIOS: (raiz / v.RUTA_PRECIOS).read_text(encoding="utf-8"),
        v.RUTA_LIMITES: (raiz / v.RUTA_LIMITES).read_text(encoding="utf-8"),
    }

    def dormir(segundos):
        t[0] += segundos

    codigo = v.main(
        [trabajo],
        api=falso,
        bajar=lambda _url: pagina,
        hoy=HOY,
        dormir=dormir,
        reloj=lambda: t[0],
        raiz=raiz,
        entorno={"GITHUB_REPOSITORY": REPO},
    )
    return codigo, falso


def _pagina_alterada() -> str:
    return _cambiar_en_fila(_pagina_precios(), "Claude Opus 5.5", "$0.20", f"${NUEVO:.2f}")


def test_el_pr_se_hace_por_la_api_y_lanza_los_dos_checks(raiz):
    codigo, falso = _correr(raiz, "precios", _pagina_alterada())
    assert codigo == 0
    assert ("PUT", RUTA_CONTENIDOS_PRECIOS) in falso.llamadas
    assert ("POST", f"/repos/{REPO}/pulls") in falso.llamadas
    assert {"ci.yml", "codeql.yml"} <= falso.despachados()
    # El commit lleva la tabla nueva con la fecha de hoy.
    cuerpo = falso.cuerpos[falso.llamadas.index(("PUT", RUTA_CONTENIDOS_PRECIOS))]
    escrita = json.loads(base64.b64decode(cuerpo["content"]))
    assert cuerpo["branch"] == "vigilante/precios"
    assert escrita["modelos"]["claude-opus-5-5"]["lectura"] == NUEVO
    assert escrita["consultado"] == HOY.isoformat()
    # Con el PR en `clean`, no hay comentario.
    assert not any(r.endswith("/comments") for _m, r in falso.llamadas)


def test_sin_cambios_no_toca_github(raiz):
    codigo, falso = _correr(raiz, "precios", _pagina_precios())
    assert codigo == 0
    assert falso.llamadas == []


def test_si_ya_hay_pr_lo_actualiza(raiz):
    codigo, falso = _correr(raiz, "precios", _pagina_alterada(), pr_abierto=True)
    assert codigo == 0
    assert not any(m == "POST" and r.endswith("/pulls") for m, r in falso.llamadas)
    assert ("PATCH", f"/repos/{REPO}/pulls/7") in falso.llamadas
    assert ("PUT", RUTA_CONTENIDOS_PRECIOS) in falso.llamadas


def test_si_main_avanzo_actualiza_la_rama_y_relanza(raiz):
    codigo, falso = _correr(raiz, "precios", _pagina_alterada(), pr_abierto=True, behind_by=3)
    assert codigo == 0
    actualizar = ("PUT", f"/repos/{REPO}/pulls/7/update-branch")
    assert actualizar in falso.llamadas
    primer_despacho = next(
        i for i, (_m, r) in enumerate(falso.llamadas) if r.endswith("/dispatches")
    )
    assert falso.llamadas.index(actualizar) < primer_despacho
    # Los checks se esperan sobre el head que dejó la actualización, no sobre el viejo.
    assert any("head_sha=sha-actualizado" in r for _m, r in falso.llamadas)


def test_si_queda_blocked_lo_dice_en_el_pr(raiz):
    codigo, falso = _correr(raiz, "precios", _pagina_alterada(), estado="blocked")
    assert codigo == 0
    assert any(r.endswith("/comments") for _m, r in falso.llamadas)
    comentario = falso.cuerpos[
        next(i for i, (_m, r) in enumerate(falso.llamadas) if r.endswith("/comments"))
    ]
    assert "reábrelo" in comentario["body"]


def test_checks_en_rojo_terminan_en_error(raiz):
    codigo, falso = _correr(raiz, "precios", _pagina_alterada(), conclusion="failure")
    assert codigo == 1
    assert {"ci.yml", "codeql.yml"} <= falso.despachados()


def test_una_pagina_rota_termina_en_error_y_no_en_sin_cambios(raiz):
    rota = _pagina_precios().replace(">Model pricing<", ">Pricing<")
    codigo, falso = _correr(raiz, "precios", rota)
    assert codigo == 1
    assert falso.llamadas == []


def test_el_ensayo_fuerza_un_diff_inocuo_en_su_rama(raiz):
    v = _v()
    t = [1_790_000_000.0]
    falso = FalsoGitHub(lambda: t[0])
    falso.ficheros = {v.RUTA_PRECIOS: (raiz / v.RUTA_PRECIOS).read_text(encoding="utf-8")}
    codigo = v.main(
        ["precios"],
        api=falso,
        bajar=lambda _url: _pagina_precios(),
        hoy=HOY,
        dormir=lambda s: t.__setitem__(0, t[0] + s),
        reloj=lambda: t[0],
        raiz=raiz,
        entorno={"GITHUB_REPOSITORY": REPO, "VIGILANTE_ENSAYO": "true"},
    )
    assert codigo == 0
    pr = falso.cuerpos[falso.llamadas.index(("POST", f"/repos/{REPO}/pulls"))]
    assert pr["head"] == "vigilante/ensayo" and pr["title"].startswith("[ensayo]")
    cuerpo = falso.cuerpos[falso.llamadas.index(("PUT", RUTA_CONTENIDOS_PRECIOS))]
    escrita = json.loads(base64.b64decode(cuerpo["content"]))
    assert escrita == {**PAQUETE, "consultado": HOY.isoformat()}


def test_limites_cambiados_abren_su_pr(raiz):
    v = _v()
    html = _pagina_limites().replace("Think of this as your", "Picture this as your", 1)
    codigo, falso = _correr(raiz, "limites", html)
    assert codigo == 0
    ruta = f"/repos/{REPO}/contents/{v.RUTA_LIMITES}"
    assert ("PUT", ruta) in falso.llamadas
    pr = falso.cuerpos[falso.llamadas.index(("POST", f"/repos/{REPO}/pulls"))]
    assert pr["head"] == "vigilante/limites"
    assert "recalcular-coste --reiniciar-calibracion" in pr["body"]


def test_limites_iguales_no_tocan_github(raiz):
    codigo, falso = _correr(raiz, "limites", _pagina_limites())
    assert codigo == 0
    assert falso.llamadas == []


# --- Workflows y script -------------------------------------------------------------------------


def _yaml(ruta: Path) -> dict:
    return yaml.safe_load(ruta.read_text(encoding="utf-8"))


def _on(datos: dict) -> dict:
    # PyYAML lee la clave `on:` como el booleano True (YAML 1.1).
    return datos.get("on", datos.get(True))


def test_el_workflow_tiene_lo_justo():
    assert WORKFLOW.is_file()
    datos = _yaml(WORKFLOW)
    on = _on(datos)
    assert on["schedule"] and on["schedule"][0]["cron"]
    assert on["workflow_dispatch"]["inputs"]["ensayo"]["type"] == "boolean"
    assert set(on) == {"schedule", "workflow_dispatch"}
    assert datos["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "actions": "write",
    }
    assert set(datos["jobs"]) == {"precios", "limites"}
    for nombre, job in datos["jobs"].items():
        assert "permissions" not in job, nombre
        assert job["timeout-minutes"] == 60, nombre
        ejecuta = [paso["run"] for paso in job["steps"] if "run" in paso]
        assert ejecuta == [f"python3 scripts/vigilante_precios.py {nombre}"]
        checkout = [p for p in job["steps"] if p.get("uses", "").startswith("actions/checkout")]
        assert checkout and checkout[0]["with"]["persist-credentials"] is False


@pytest.mark.parametrize("fichero", ["ci.yml", "codeql.yml"])
def test_ci_y_codeql_aceptan_workflow_dispatch(fichero):
    datos = _yaml(WORKFLOWS / fichero)
    assert "workflow_dispatch" in _on(datos)
    assert datos["permissions"] == {"contents": "read"}


def _imports_ajenos(fuente: str) -> list[str]:
    modulos = set()
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, ast.Import):
            modulos.update(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            modulos.add(nodo.module.split(".")[0])
    return sorted(m for m in modulos if m not in sys.stdlib_module_names)


def test_el_script_es_solo_stdlib():
    ajenos = _imports_ajenos(SCRIPT.read_text(encoding="utf-8"))
    assert ajenos == []


# --- Privacidad de las copias (arreglo tras T10) -------------------------------------------------


def _limpiador():
    ruta = RAIZ / "scripts" / "limpiar_fixtures_vigilante.py"
    spec = importlib.util.spec_from_file_location("limpiar_fixtures_vigilante", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_las_copias_no_guardan_datos_de_la_visita():
    """Las páginas guardadas no llevan el id anónimo, el de sesión, el país de la IP ni el `nonce`
    de quien las bajó: las limpia `scripts/limpiar_fixtures_vigilante.py`."""
    limpiador = _limpiador()
    for nombre in ("precios.html", "limites.html"):
        assert limpiador.restos((FIXTURES / nombre).read_text(encoding="utf-8")) == [], nombre


# Valores SINTÉTICOS para el control positivo: se generan en cada ejecución, así que el repo no
# guarda ningún valor de una visita real (ni siquiera como control).
def _sinteticos() -> dict[str, str]:
    return {
        "anonimo": str(uuid.uuid4()),
        "estable": str(uuid.uuid4()),
        "sesion": str(uuid.uuid4()),
        "sesion2": str(uuid.uuid4()),
        "nonce": secrets.token_urlsafe(16),
        "nonce2": secrets.token_urlsafe(16),
        "pais": "QM",  # ISO 3166 de uso privado, distinto del neutro «ZZ»
        "pais2": "XA",
        "pais3": "QN",
    }


def _siembra(v: dict[str, str]) -> list[tuple[str, str]]:
    """(fragmento, valor que el guardián debe ver) en todas las formas que admite el limpiador:
    comillas dobles o simples, con o sin espacios, atributo, JSON y JSON escapado."""
    return [
        (f'"user":{{"anonymousId":"{v["anonimo"]}"}}', v["anonimo"]),
        (f"{{'stableId' : '{v['estable']}'}}", v["estable"]),
        (f'_sift.push([\\"_setSessionId\\", \\"{v["sesion"]}\\"])', v["sesion"]),
        (f'\\\\\\"sessionId\\\\\\":\\\\\\"{v["sesion2"]}\\\\\\"', v["sesion2"]),
        (f'<script nonce="{v["nonce"]}">', v["nonce"]),
        (f"<link nonce = '{v['nonce2']}'>", v["nonce2"]),
        (f'<div data-consent-ip-country="{v["pais"]}">', v["pais"]),
        (f'\\"ipCountry\\":\\"{v["pais2"]}\\"', v["pais2"]),
        (f"{{'ip_country': '{v['pais3']}'}}", v["pais3"]),
    ]


def test_el_guardian_detecta_datos_sinteticos_sembrados_en_una_copia(tmp_path):
    """Control positivo del guardián: siembra valores sintéticos en una copia temporal de cada
    página y comprueba que `restos()` los ve TODOS y que `limpiar()` (vía `main`) los quita sin
    tocar nada más."""
    limpiador = _limpiador()
    for nombre in ("precios.html", "limites.html"):
        v = _sinteticos()
        siembra = _siembra(v)
        original = (FIXTURES / nombre).read_bytes().decode("utf-8")
        mitad = len(original) // 2
        sucia = original[:mitad] + " ".join(f for f, _ in siembra) + original[mitad:]
        copia = tmp_path / nombre
        copia.write_bytes(sucia.encode("utf-8"))

        assert sorted(limpiador.restos(sucia)) == sorted(valor for _, valor in siembra), nombre

        assert limpiador.main([str(copia)]) == 0
        limpia = copia.read_bytes().decode("utf-8")
        assert limpiador.restos(limpia) == [], nombre
        assert not any(valor in limpia for _, valor in siembra if len(valor) > 2), nombre
        # Solo cambia lo sembrado: fuera de la siembra, la página queda byte a byte igual.
        assert limpia.startswith(original[:mitad]) and limpia.endswith(original[mitad:]), nombre


def test_el_guardian_no_depende_de_valores_concretos():
    """El guardián busca formas, no valores: un valor de visita cualquiera, en cualquier clave
    vigilada, sale; el valor neutro, no."""
    limpiador = _limpiador()
    assert limpiador.restos(f'"anonymousId":"{limpiador.UUID_NEUTRO}"') == []
    assert limpiador.restos(f'"ipCountry":"{limpiador.PAIS_NEUTRO}"') == []
    assert limpiador.restos(f'nonce="{limpiador.NONCE_NEUTRO}"') == []
    for _ in range(3):
        otro = str(uuid.uuid4())
        assert limpiador.restos(f'"anonymousId":"{otro}"') == [otro]
