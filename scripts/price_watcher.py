"""Vigilante semanal de precios y límites: abre un PR cuando cambia una página oficial.

Dos trabajos, uno por página (REQ-020 a REQ-025 de `coste-api-y-cuota`):

- `prices`: descarga la página oficial de precios, extrae la tabla «Model pricing» y la compara
  con `src/local_delegate/resources/data/prices.json`. Si cambia un precio, aparece un modelo o
  cambia la búsqueda web, abre (o actualiza) **un** PR en la rama fija `vigilante/precios` con la
  tabla nueva y `consulted` = hoy. Un modelo que desaparece **no** se borra: los transcripts
  viejos lo siguen necesitando, y el aviso sale en el log.
- `limits`: descarga el artículo de ayuda de límites de uso, extrae su texto normalizado y lo
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

ROOT = Path(__file__).resolve().parents[1]

PRICES_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
LIMITS_URL = "https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work"

PRICES_PATH = "src/local_delegate/resources/data/prices.json"
LIMITS_PATH = ".github/vigilante/limites-de-uso.txt"

BASE_BRANCH = "main"
PRICES_BRANCH = "vigilante/precios"
LIMITS_BRANCH = "vigilante/limites"
DRY_RUN_BRANCH = "vigilante/ensayo"
# Clave que añade el ensayo a `prices.json`; con `_` delante, como `_note`, no es un dato.
DRY_RUN_KEY = "_dry_run"

# Los dos workflows que contienen los checks que exige el ruleset `protect-main` (REQ-025).
CHECK_WORKFLOWS = ("ci.yml", "codeql.yml")
WAIT_CEILING_S = 45 * 60
POLL_S = 30
# `update-branch` es asíncrono: GitHub hace el merge cuando puede.
UPDATE_CEILING_S = 5 * 60
# `mergeable_state` sale `unknown` mientras GitHub lo calcula.
PR_STATE_ATTEMPTS = 10

PRICES_HEADER = "Model pricing"
MIN_ROWS = 5
# Filas que no son modelos con precio público en vigor. La página marca «Retired» e «Invite only»
# en el `aria-label` del botón que acompaña al nombre; «limited availability» lo nombra la spec.
IGNORED_MARKERS = ("retired", "limited availability", "invite only")
# Cabecera de columna de la página → campo de `prices.json`.
COLUMNS = {
    "input": "input",
    "output": "output",
    "5m writes": "w5m",
    "1h writes": "w1h",
    "hits and refreshes": "cache_read",
}
FIELDS = ("input", "w5m", "w1h", "cache_read", "output")
_WEB_SEARCH = re.compile(
    r"Web search is available on the Claude API for \$(\d+(?:\.\d+)?) per 1,000 searches"
)
# Lo que se pone a un modelo nuevo hasta que una persona lo revise; el cuerpo del PR lo pide.
NEW_PLACEHOLDER = {"family": "new", "supports_effort": True}

LIMITS_TITLE = "How do usage and length limits work?"
MIN_LIMITS_CHARS = 500

RESTART_COMMAND = "local-delegate recompute-cost --reset-calibration five_hour|seven_day"

BLOCKED_COMMENT = (
    "**El vigilante no puede dejar este PR listo para mezclar.** Los checks que exige el ruleset "
    "(`ci.yml` y `codeql.yml`, lanzados por `workflow_dispatch`) terminaron en verde, pero GitHub "
    "lo sigue marcando `blocked` (la regla `code_scanning` o "
    "`require_extra_approval_for_unattributed_changes` con commits del bot).\n\n"
    "Salida a mano (REQ-025): **cierra el PR y reábrelo**. La reapertura por una persona dispara "
    "los workflows de `pull_request` con normalidad."
)

HTTP_USER_AGENT = "local-delegate-vigilante (+https://github.com/ZahiriNatZuke/local-delegate)"
TIMEOUT_S = 60

# Iconos de la fuente de símbolos de la página: caracteres de uso privado sin significado.
_PRIVATE_USE = re.compile("[-]")


class WatcherError(Exception):
    """Algo no cuadra y el job tiene que terminar en error, no en «sin cambios»."""


class ErrorHTTP(WatcherError):
    def __init__(self, state: int, message: str) -> None:
        super().__init__(f"HTTP {state}: {message}")
        self.state = state


def _normalize(text: str) -> str:
    return " ".join(_PRIVATE_USE.sub("", text).split())


# --- Precios ----------------------------------------------------------------------------------


class _PriceTableReader(HTMLParser):
    """Lee la primera `<table>` que sigue al `<h2>` «Model pricing»: filas de celdas.

    Cada celda guarda su texto (sin `<sup>`), el de sus enlaces y los `aria-label` de lo que
    contiene, que es donde la página pone «(Retired)» o «(Invite only)». El nombre del modelo es
    el texto del enlace a su ficha: al lado va una frase de presentación que no forma parte de él.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.seen_header = False
        self.state = "buscando"  # buscando → tabla → hecho
        self.rows: list[list[dict]] = []
        self._in_h2 = False
        self._h2_text: list[str] = []
        self._row: list[dict] | None = None
        self._cell: dict | None = None
        self._in_sup = 0
        self._in_link = 0
        self._nested = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.state == "hecho":
            return
        if self.state == "buscando":
            if tag == "h2":
                self._in_h2 = True
                self._h2_text = []
            elif tag == "table" and self.seen_header:
                self.state = "tabla"
            return
        if tag == "table":
            self._nested += 1
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {"text": [], "link": [], "labels": []}
        elif tag == "sup":
            self._in_sup += 1
        elif tag == "a":
            self._in_link += 1
        label = dict(attrs).get("aria-label")
        if self._cell is not None and label:
            self._cell["labels"].append(label)

    def handle_endtag(self, tag: str) -> None:
        if self.state == "buscando":
            if tag == "h2" and self._in_h2:
                self._in_h2 = False
                if _normalize("".join(self._h2_text)) == PRICES_HEADER:
                    self.seen_header = True
            return
        if self.state != "tabla":
            return
        if tag == "table":
            if self._nested:
                self._nested -= 1
            else:
                self.state = "hecho"
        elif tag == "sup":
            self._in_sup = max(0, self._in_sup - 1)
        elif tag == "a":
            self._in_link = max(0, self._in_link - 1)
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(
                {
                    "text": _normalize("".join(self._cell["text"])),
                    "link": _normalize("".join(self._cell["link"])),
                    "labels": self._cell["labels"],
                }
            )
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._in_h2:
            self._h2_text.append(data)
        elif self.state == "tabla" and self._cell is not None and not self._in_sup:
            self._cell["text"].append(data)
            if self._in_link:
                self._cell["link"].append(data)


def name_to_id(name: str) -> str:
    """«Claude Opus 4.5» → `claude-opus-4-5`; «Claude Opus 5» → `claude-opus-5` (REQ-021).

    Quita los paréntesis antes. Un nombre que no encaja en la regla es un error: mejor parar que
    inventar un id.
    """
    clean = _normalize(re.sub(r"\([^)]*\)", " ", name))
    m = re.fullmatch(r"Claude ([A-Za-z]+) (\d+)(?:\.(\d+))?", clean)
    if m is None:
        raise WatcherError(f"nombre de modelo que no encaja en la regla de ids: {name!r}")
    family, larger, smaller = m.groups()
    parts = ["claude", family.lower(), larger] + ([smaller] if smaller else [])
    return "-".join(parts)


def _read_price(text: str, model: str, column: str) -> int | float:
    clean = re.sub(r"/\s*MTok", "", text).strip()
    m = re.fullmatch(r"\$\s*(\d+(?:\.\d+)?)", clean)
    if m is None:
        raise WatcherError(f"celda de precio ilegible en {model} / {column}: {text!r}")
    value = m.group(1)
    return float(value) if "." in value else int(value)


def _ignored(name_cell: dict) -> bool:
    marks = " ".join([name_cell["text"], *name_cell["labels"]]).lower()
    return any(mark in marks for mark in IGNORED_MARKERS)


def extract_price_table(html: str) -> dict:
    """La tabla «Model pricing» de la página: `{"web_search_per_1000", "models": {id: {...}}}`.

    Falla en voz alta (REQ-022) sin la cabecera, sin la tabla, con menos de 5 filas válidas o con
    una celda que no es un número. Ignora las filas «retired», «limited availability» e «invite
    only».
    """
    reader = _PriceTableReader()
    reader.feed(html)
    reader.close()
    if not reader.seen_header:
        raise WatcherError(f"no aparece la cabecera «{PRICES_HEADER}» en la página")
    if reader.state == "buscando":
        raise WatcherError(f"no hay tabla después de «{PRICES_HEADER}»")

    indices: dict[str, int] | None = None
    width = 0
    models: dict[str, dict] = {}
    for row in reader.rows:
        texts = [c["text"].lower() for c in row]
        if indices is None:
            if all(col in texts for col in COLUMNS):
                indices = {price_field: texts.index(col) for col, price_field in COLUMNS.items()}
                width = len(row)
            continue
        if len(row) == 1:
            continue  # separador de grupo («Additional models»)
        if len(row) != width:
            raise WatcherError(f"fila con {len(row)} celdas, se esperaban {width}: {texts}")
        if _ignored(row[0]):
            continue
        mid = name_to_id(row[0]["link"] or row[0]["text"])
        if mid in models:
            raise WatcherError(f"modelo repetido en la tabla: {mid}")
        models[mid] = {
            price_field: _read_price(row[i]["text"], mid, price_field)
            for price_field, i in indices.items()
        }
    if indices is None:
        raise WatcherError(f"la tabla no tiene las columnas esperadas: {list(COLUMNS)}")
    if len(models) < MIN_ROWS:
        raise WatcherError(f"solo {len(models)} filas de precios; se esperan {MIN_ROWS}+")

    plain_text = _normalize(html_mod.unescape(re.sub(r"<[^>]+>", " ", html)))
    m = _WEB_SEARCH.search(plain_text)
    if m is None:
        raise WatcherError("no aparece el precio de la búsqueda web")
    value = m.group(1)
    search = float(value) if "." in value else int(value)
    return {"web_search_per_1000": search, "models": models}


@dataclass
class Changes:
    """Lo que difiere entre la página y la tabla del paquete.

    `prices` son tuplas `(id, campo, viejo, nuevo)`. `vanished` no cambia la tabla: se
    avisa en el log y en el PR, pero no se borra nada.
    """

    prices: list[tuple[str, str, float, float]] = field(default_factory=list)
    new_ones: list[str] = field(default_factory=list)
    vanished: list[str] = field(default_factory=list)
    web_search: tuple[float, float] | None = None

    @property
    def has_changes(self) -> bool:
        return bool(self.prices or self.new_ones or self.web_search)


def compare(new: dict, package: dict) -> Changes:
    """Compara la tabla extraída con la del paquete, campo a campo y por valor numérico."""
    changes = Changes()
    old_ones = package["models"]
    for mid, prices in new["models"].items():
        if mid not in old_ones:
            changes.new_ones.append(mid)
            continue
        for price_field in FIELDS:
            if float(prices[price_field]) != float(old_ones[mid][price_field]):
                changes.prices.append(
                    (mid, price_field, old_ones[mid][price_field], prices[price_field])
                )
    changes.vanished = [mid for mid in old_ones if mid not in new["models"]]
    before, now = package["web_search_per_1000"], new["web_search_per_1000"]
    if float(before) != float(now):
        changes.web_search = (before, now)
    return changes


def updated_table(package: dict, new: dict, changes: Changes, today: dt.date) -> dict:
    """La tabla del paquete con los cambios aplicados y `consulted` = hoy. No borra modelos."""
    table = copy.deepcopy(package)
    for mid, price_field, _old, value in changes.prices:
        table["models"][mid][price_field] = value
    for mid in changes.new_ones:
        table["models"][mid] = {**new["models"][mid], **NEW_PLACEHOLDER}
    if changes.web_search is not None:
        table["web_search_per_1000"] = changes.web_search[1]
    table["consulted"] = today.isoformat()
    return table


_MODEL_LINE = re.compile(r'^\s*"([^"]+)": (\{.*\}),?\s*$')


def serialize_prices(table: dict, original: str) -> str:
    """`prices.json` con el formato del repo: una línea por modelo.

    Las líneas de los modelos que no cambian se copian **tal cual** del original (con su `0.20`),
    para que el diff del PR enseñe solo lo que cambió.
    """
    original_lines: dict[str, str] = {}
    original_data = json.loads(original).get("models", {})
    for line in original.splitlines():
        m = _MODEL_LINE.match(line)
        if m and m.group(1) in original_data:
            original_lines[m.group(1)] = m.group(2)

    def _value(v: object) -> str:
        return json.dumps(v, ensure_ascii=False)

    output = ["{"]
    keys = list(table)
    for k in keys:
        comma = "," if k != keys[-1] else ""
        if k != "models":
            output.append(f"  {_value(k)}: {_value(table[k])}{comma}")
            continue
        output.append('  "models": {')
        ids = list(table["models"])
        for mid in ids:
            entry = table["models"][mid]
            if mid in original_lines and original_data.get(mid) == entry:
                body = original_lines[mid]
            else:
                body = json.dumps(entry, ensure_ascii=False, separators=(", ", ": "))
            output.append(f"    {_value(mid)}: {body}{',' if mid != ids[-1] else ''}")
        output.append(f"  }}{comma}")
    output.append("}")
    return "\n".join(output) + "\n"


def prices_pr_body(changes: Changes, *, dry_run: bool = False) -> str:
    lines = []
    if dry_run:
        lines += [
            (
                "> **[ensayo]** PR de prueba del vigilante (T11 de `coste-api-y-cuota`): solo "
                "añade la marca `_dry_run` a la tabla. **No mezclar**: se cierra sin mezclar y se "
                "borra la rama."
            ),
            "",
        ]
    lines += [
        (
            f"La página oficial de precios ({PRICES_URL}) ya no coincide con "
            f"`{PRICES_PATH}`. Este PR lo abre el vigilante semanal."
        ),
        "",
    ]
    if changes.prices:
        lines += ["### Precios que cambian (USD/MTok)", "", "| Modelo | Campo | Antes | Ahora |"]
        lines.append("|---|---|---:|---:|")
        lines += [f"| `{m}` | {c} | {a} | {n} |" for m, c, a, n in changes.prices]
        lines.append("")
    if changes.web_search is not None:
        before, now = changes.web_search
        lines += [f"### Búsqueda web: de ${before} a ${now} por cada 1000 búsquedas", ""]
    if changes.new_ones:
        lines += ["### Modelos nuevos: revísalos a mano", ""]
        lines += [f"- `{m}`" for m in changes.new_ones]
        lines += [
            "",
            (
                "El id se deduce del nombre comercial (la página no trae ids): compáralo con "
                "«Models overview» y «Model IDs and versioning». `family` y `supports_effort` "
                f"van provisionales ({NEW_PLACEHOLDER['family']} / "
                f"{str(NEW_PLACEHOLDER['supports_effort']).lower()}): corrígelos antes de "
                "mezclar."
            ),
            "",
        ]
    if changes.vanished:
        lines += ["### Modelos que ya no salen en la página (siguen en la tabla)", ""]
        lines += [f"- `{m}`" for m in changes.vanished]
        lines += [
            "",
            "No se borran: los transcripts viejos los siguen necesitando para valorar el coste.",
            "",
        ]
    lines += [
        (
            "Los checks del ruleset (`ci.yml` y `codeql.yml`) los lanza el propio vigilante por "
            "`workflow_dispatch`; los commits van por la API de contenidos, que los firma."
        ),
    ]
    return "\n".join(lines) + "\n"


# --- Límites ----------------------------------------------------------------------------------

_BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "tr", "br", "ul", "ol", "table"}


class _ArticleReader(HTMLParser):
    """El título (`<h1>`) y el texto del primer `<article>`, con un salto por bloque."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.chunks: list[str] = []
        self._in_h1 = False
        self._h1: list[str] = []
        self._depth = 0  # dentro del <article>
        self._finished = False
        self._ignore = 0  # <script>/<style>

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._ignore += 1
        elif tag == "h1" and self.title is None:
            self._in_h1 = True
        elif tag == "article" and not self._finished:
            self._depth += 1
        if self._depth and tag in _BLOCKS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._ignore = max(0, self._ignore - 1)
        elif tag == "h1" and self._in_h1:
            self._in_h1 = False
            self.title = _normalize("".join(self._h1))
        elif tag == "article" and self._depth:
            self._depth -= 1
            if not self._depth:
                self._finished = True
        if self._depth and tag in _BLOCKS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignore:
            return
        if self._in_h1:
            self._h1.append(data)
        if self._depth:
            self.chunks.append(data)


def extract_limits_text(html: str) -> str:
    """El artículo de límites como texto: título, línea en blanco y un párrafo por línea.

    Sin HTML y con los espacios colapsados (REQ-023). Falla en voz alta sin el título o con menos
    de 500 caracteres de artículo.
    """
    reader = _ArticleReader()
    reader.feed(html)
    reader.close()
    if reader.title != LIMITS_TITLE:
        raise WatcherError(f"no aparece el título «{LIMITS_TITLE}» (h1 leído: {reader.title!r})")
    paragraphs = [_normalize(p) for p in "".join(reader.chunks).split("\n")]
    body = "\n".join(p for p in paragraphs if p)
    if len(body) < MIN_LIMITS_CHARS:
        raise WatcherError(
            f"el artículo de límites tiene {len(body)} caracteres; se esperan {MIN_LIMITS_CHARS}+"
        )
    return f"{LIMITS_TITLE}\n\n{body}\n"


def limits_pr_body() -> str:
    return (
        f"Ha cambiado el artículo de límites de uso ({LIMITS_URL}). El diff de "
        f"`{LIMITS_PATH}` **es** el aviso: léelo y decide si los límites de cuota cambiaron.\n\n"
        "Si cambiaron, la calibración de la cuota hecha con los límites viejos deja de valer. "
        "Reiníciala a mano en cada máquina, para el tipo de ventana afectado (REQ-057):\n\n"
        f"```\n{RESTART_COMMAND}\n```\n\n"
        "Mezcla el PR para que el vigilante compare la semana que viene contra este texto. Los "
        "checks del ruleset los lanza el propio vigilante por `workflow_dispatch`.\n"
    )


# --- GitHub -----------------------------------------------------------------------------------

Api = Callable[..., object]


def github_client(token: str, base: str = "https://api.github.com") -> Api:
    """`api(metodo, ruta, cuerpo=None)` sobre la REST de GitHub. Un error HTTP lanza `ErrorHTTP`."""

    def api(method: str, path: str, body: dict | None = None) -> object:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            base + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": HTTP_USER_AGENT,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:500].decode("utf-8", errors="replace")
            raise ErrorHTTP(exc.code, f"{method} {path}: {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise WatcherError(f"{method} {path}: sin respuesta de GitHub ({exc})") from exc
        return json.loads(raw) if raw else None

    return api


def download(url: str, attempts: int = 2) -> str:
    """El HTML de la página. Si no responde tras `attempts`, error (REQ-022)."""
    last: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": HTTP_USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except (urllib.error.URLError, OSError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(10)
    raise WatcherError(f"la página {url} no responde: {last}")


def _iso(seconds: float) -> str:
    return dt.datetime.fromtimestamp(seconds, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Context:
    api: Api
    repo: str
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.time

    @property
    def r(self) -> str:
        return f"/repos/{self.repo}"


def _prepare_branch(ctx: Context, branch: str, sha_base: str) -> None:
    """La rama, recién salida de `main`. Si quedó de un PR ya cerrado, se reinicia."""
    try:
        ctx.api("GET", f"{ctx.r}/git/ref/heads/{branch}")
    except ErrorHTTP as exc:
        if exc.state != 404:
            raise
        ctx.api("POST", f"{ctx.r}/git/refs", {"ref": f"refs/heads/{branch}", "sha": sha_base})
        return
    ctx.api("PATCH", f"{ctx.r}/git/refs/heads/{branch}", {"sha": sha_base, "force": True})


def _write(ctx: Context, branch: str, path: str, content: str, message: str) -> bool:
    """Un commit por la API de contenidos (firmado por GitHub). `False` si ya estaba igual."""
    sha = None
    try:
        current = ctx.api("GET", f"{ctx.r}/contents/{path}?ref={urllib.parse.quote(branch)}")
    except ErrorHTTP as exc:
        if exc.state != 404:
            raise
    else:
        sha = current["sha"]
        if base64.b64decode(current.get("content", "")).decode("utf-8") == content:
            return False
    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha is not None:
        body["sha"] = sha
    ctx.api("PUT", f"{ctx.r}/contents/{path}", body)
    return True


def _update_if_behind(ctx: Context, branch: str, number: int) -> None:
    """Si `main` avanzó, «update branch» (el commit lo hace GitHub) y espera al head nuevo."""
    comparison = ctx.api("GET", f"{ctx.r}/compare/{BASE_BRANCH}...{branch}")
    if not comparison.get("behind_by"):
        return
    before = ctx.api("GET", f"{ctx.r}/pulls/{number}")["head"]["sha"]
    ctx.api("PUT", f"{ctx.r}/pulls/{number}/update-branch", {"expected_head_sha": before})
    limit = ctx.clock() + UPDATE_CEILING_S
    while ctx.api("GET", f"{ctx.r}/pulls/{number}")["head"]["sha"] == before:
        if ctx.clock() >= limit:
            raise WatcherError(f"la rama {branch} no se actualizó con {BASE_BRANCH} a tiempo")
        ctx.sleep(POLL_S)


def _launch_and_wait_checks(ctx: Context, branch: str, sha: str) -> None:
    """Lanza `ci.yml` y `codeql.yml` sobre la rama y espera a que terminen en verde."""
    start = ctx.clock()
    for wf in CHECK_WORKFLOWS:
        ctx.api("POST", f"{ctx.r}/actions/workflows/{wf}/dispatches", {"ref": branch})
    # Margen para relojes desfasados; descarta runs de semanas anteriores sobre el mismo sha.
    since = _iso(start - 120)
    limit = start + WAIT_CEILING_S
    while True:
        runs = ctx.api(
            "GET", f"{ctx.r}/actions/runs?head_sha={sha}&event=workflow_dispatch&per_page=50"
        )["workflow_runs"]
        latest: dict[str, dict] = {}
        for run in runs:  # la API los da del más nuevo al más viejo
            wf = run.get("path", "").split("@")[0].rsplit("/", 1)[-1]
            if wf in CHECK_WORKFLOWS and run.get("created_at", "") >= since:
                latest.setdefault(wf, run)
        finished = [r for r in latest.values() if r.get("status") == "completed"]
        if len(finished) == len(CHECK_WORKFLOWS):
            break
        if ctx.clock() >= limit:
            raise WatcherError(
                f"los checks no terminaron en {WAIT_CEILING_S // 60} min: {sorted(latest)}"
            )
        ctx.sleep(POLL_S)
    red = {wf: r.get("conclusion") for wf, r in latest.items() if r["conclusion"] != "success"}
    if red:
        raise WatcherError(f"checks del PR sin éxito: {red}")


def _warn_if_blocked(ctx: Context, number: int) -> str | None:
    state = None
    for attempt in range(PR_STATE_ATTEMPTS):
        state = ctx.api("GET", f"{ctx.r}/pulls/{number}").get("mergeable_state")
        if state != "unknown":
            break
        if attempt + 1 < PR_STATE_ATTEMPTS:
            ctx.sleep(POLL_S)
    if state == "blocked":
        ctx.api("POST", f"{ctx.r}/issues/{number}/comments", {"body": BLOCKED_COMMENT})
    return state


def propose(
    ctx: Context, branch: str, files: dict[str, str], title: str, body: str, message: str
) -> int | None:
    """Abre o actualiza el PR de `branch` con `files` y deja lanzados y vistos sus checks."""
    sha_main = ctx.api("GET", f"{ctx.r}/git/ref/heads/{BASE_BRANCH}")["object"]["sha"]
    owner = ctx.repo.split("/")[0]
    head = urllib.parse.quote(f"{owner}:{branch}")
    opened = ctx.api("GET", f"{ctx.r}/pulls?state=open&head={head}&base={BASE_BRANCH}")
    pr = opened[0] if opened else None
    if pr is None:
        _prepare_branch(ctx, branch, sha_main)
    written = [path for path, text in files.items() if _write(ctx, branch, path, text, message)]
    if pr is None:
        if not written:
            print(f"La rama {branch} ya coincide con {BASE_BRANCH}: no hay PR que abrir.")
            return None
        pr = ctx.api(
            "POST",
            f"{ctx.r}/pulls",
            {"title": title, "head": branch, "base": BASE_BRANCH, "body": body},
        )
        print(f"PR abierto: #{pr['number']}")
    else:
        ctx.api("PATCH", f"{ctx.r}/pulls/{pr['number']}", {"title": title, "body": body})
        print(f"PR actualizado: #{pr['number']}")
    number = pr["number"]
    _update_if_behind(ctx, branch, number)
    sha = ctx.api("GET", f"{ctx.r}/pulls/{number}")["head"]["sha"]
    _launch_and_wait_checks(ctx, branch, sha)
    state = _warn_if_blocked(ctx, number)
    print(f"Checks en verde; estado del PR: {state}")
    return number


# --- Trabajos ---------------------------------------------------------------------------------


def dry_run_mark(id_run: str) -> str:
    """El valor de `_dry_run`: distinto en cada run, para que el ensayo siempre tenga diff."""
    return f"PR de prueba del vigilante (run {id_run or 'local'}): no mezclar"


def prices_job(
    ctx: Context,
    html: str,
    root: Path,
    today: dt.date,
    *,
    dry_run: bool = False,
    id_run: str = "",
) -> int | None:
    new = extract_price_table(html)
    original = (root / PRICES_PATH).read_text(encoding="utf-8")
    package = json.loads(original)
    changes = compare(new, package)
    for mid in changes.vanished:
        print(f"AVISO: {mid} ya no sale en la página; se queda en la tabla.")
    if dry_run:
        # Un diff inocuo y forzado para probar el circuito entero en GitHub (T11). No toca
        # `consulted` (REQ-010: fecha del último cambio real), que el día en que se mezcló la
        # tabla ya vale hoy y no daría diff: añade una marca `_dry_run` con el id del run, que
        # cambia en cada ejecución y que la carga de la tabla ignora como ignora `_nota`.
        # La marca va primera y la del paquete, si la trae (una rama de ensayo anterior), se
        # descarta: la nueva tiene que ganar siempre o no habría diff.
        rest = {k: v for k, v in copy.deepcopy(package).items() if k != DRY_RUN_KEY}
        table = {DRY_RUN_KEY: dry_run_mark(id_run), **rest}
        branch, title = DRY_RUN_BRANCH, "[ensayo] Vigilante de precios: prueba del circuito"
    elif not changes.has_changes:
        print("Precios: sin cambios.")
        return None
    else:
        table = updated_table(package, new, changes, today)
        branch, title = PRICES_BRANCH, "Vigilante de precios: la página oficial ha cambiado"
    content = serialize_prices(table, original)
    if content == original:
        raise WatcherError("la tabla propuesta es idéntica a la del paquete: no hay diff")
    return propose(
        ctx,
        branch,
        {PRICES_PATH: content},
        title,
        prices_pr_body(changes, dry_run=dry_run),
        f"chore(precios): tabla según la página oficial del {today.isoformat()}",
    )


def limits_job(ctx: Context, html: str, root: Path) -> int | None:
    text = extract_limits_text(html)
    saved_path = root / LIMITS_PATH
    saved = saved_path.read_text(encoding="utf-8") if saved_path.is_file() else ""
    if text == saved:
        print("Límites: sin cambios.")
        return None
    return propose(
        ctx,
        LIMITS_BRANCH,
        {LIMITS_PATH: text},
        "Vigilante de límites: el artículo de límites de uso ha cambiado",
        limits_pr_body(),
        "chore(limites): texto del artículo de límites de uso",
    )


def main(
    argv: list[str] | None = None,
    *,
    api: Api | None = None,
    lower: Callable[[str], str] = download,
    today: dt.date | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
    root: Path = ROOT,
    env: dict[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("job", choices=("prices", "limits"))
    args = parser.parse_args(argv)
    env = dict(os.environ) if env is None else env
    dry_run = env.get("WATCHER_DRY_RUN", "").strip().lower() == "true"
    today = today or dt.datetime.now(dt.UTC).date()
    try:
        repo = env.get("GITHUB_REPOSITORY", "")
        if "/" not in repo:
            raise WatcherError("falta GITHUB_REPOSITORY (dueño/repo)")
        if api is None:
            token = env.get("GITHUB_TOKEN", "")
            if not token:
                raise WatcherError("falta GITHUB_TOKEN")
            api = github_client(token)
        ctx = Context(api=api, repo=repo, sleep=sleep, clock=clock)
        if args.job == "prices":
            prices_job(
                ctx,
                lower(PRICES_URL),
                root,
                today,
                dry_run=dry_run,
                id_run=env.get("GITHUB_RUN_ID", "").strip(),
            )
        else:
            limits_job(ctx, lower(LIMITS_URL), root)
    except WatcherError as exc:
        print(f"FALLO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
