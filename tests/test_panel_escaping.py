"""El panel no pinta sin escapar lo que viene del daemon (revisión de seguridad 2026-10-23).

Hasta la 0.41.1 la tabla de actividad, «En curso», la última delegación y las tools metían en
`innerHTML` campos del log (`tool`, `model`, `source`, `ts`, `model_requested`…) tal cual. Con la
línea que `record-read` dejaba escribir en cualquier `.jsonl`, eso era un XSS al abrir el panel, en el
mismo origen que `/mcp`. Este módulo guarda las dos defensas:

- **el escape**: lo cuenta un programa, no la vista. Se recorren TODAS las interpolaciones
  `${…}` de las plantillas del script del panel, y cualquiera que lea un campo de un registro del
  servidor (`e.tool`, `it.model`, `t.name`…) tiene que pasar por `escHooks` o por un formateador de
  números. Una plantilla nueva que pinte un campo crudo rompe este test;
- **la CSP**: `GET /` lleva `Content-Security-Policy` con `script-src` por hash, y los hashes son los
  de los `<script>` que de verdad sirve (si no, el propio panel no correría).

La prueba en un navegador real (Playwright) está en `test_panel_xss_ui.py`.
"""

from __future__ import annotations

import base64
import hashlib
import re

from fastapi.testclient import TestClient

from local_delegate.web import metrics

#: Las variables con las que el script recorre lo que devuelve el servidor (`/api/events`,
#: `/api/inflight`, `/api/status`, `/api/stats`, `/api/system`, `/api/hooks`).
RECORD = r"\b(?:e|ev|it|t|p|bp|c|g|m|r|j|s|im|q|pr|gen|u)\.[A-Za-z_]\w*"
#: Lo que deja un campo inofensivo en el HTML: el escape, o una cifra formateada.
SAFE_CALL = re.compile(r"^(?:escHooks|F\.format|F1\.format|f1|fmtMB|fmtNum|Math\.min)\(")
#: Un ternario cuyas dos ramas son literales: el campo solo decide cuál.
LITERAL_TERNARY = re.compile(r"^[^?]+\?\s*('[^']*'|\"[^\"]*\")\s*:\s*('[^']*'|\"[^\"]*\")$")


def _inline(page: str) -> list[str]:
    """Los `<script>` en línea, cortando por las etiquetas exactas que escribe la plantilla del panel
    (sin expresiones regulares: el HTML es el nuestro, no uno ajeno que filtrar)."""
    return [chunk.split("</script>", 1)[0] for chunk in page.split("<script>")[1:]]


def _main_script() -> str:
    return _inline(metrics.HTML)[-1]


def _template_slots(js: str) -> list[str]:
    """Cada `${…}` del script, con las llaves balanceadas."""
    found, i = [], 0
    while (i := js.find("${", i)) >= 0:
        depth, j = 0, i + 2
        while True:
            if js[j] == "{":
                depth += 1
            elif js[j] == "}":
                if depth == 0:
                    break
                depth -= 1
            j += 1
        found.append(js[i + 2 : j].strip())
        i = j
    return found


def _closes_at_end(expr: str) -> bool:
    """`escHooks(…)` entero, no `escHooks(a) + b`: el paréntesis del principio cierra al final."""
    depth = 0
    for k, ch in enumerate(expr):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return k == len(expr) - 1
    return False


def _ternary(expr: str) -> tuple[str, str] | None:
    """Las dos ramas de `cond ? a : b` al nivel de arriba (fuera de comillas y paréntesis)."""
    depth, quote, question = 0, None, None
    for k, ch in enumerate(expr):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and ch == "?" and question is None:
            question = k
        elif depth == 0 and ch == ":" and question is not None:
            return expr[question + 1 : k].strip(), expr[k + 1 :].strip()
    return None


def _unsafe(expr: str) -> bool:
    if not re.search(RECORD, expr):
        return False
    if SAFE_CALL.match(expr) and _closes_at_end(expr):
        return False
    if LITERAL_TERNARY.match(expr):
        return False
    # `cond ? a : b`: el campo de la condición no llega al HTML; cuentan las ramas.
    branches = _ternary(expr)
    return branches is None or any(_unsafe(b) for b in branches)


def test_the_guard_sees_the_templates():
    """Guarda: el recorrido encuentra las plantillas, y las del ejemplo del informe están dentro."""
    found = _template_slots(_main_script())
    assert len(found) > 100, len(found)
    assert "escHooks(e.tool)" in found
    assert "escHooks(it.model)" in found


def test_the_guard_flags_a_raw_field():
    """Control positivo: las formas que tenía la 0.41.1 se marcan; las seguras, no."""
    for raw in (
        "e.tool",
        "ev.tool||'?'",
        "it.backend",
        "t.name",
        "escHooks(e.tool) + e.model",
        "e.ok ? e.model : '?'",
        "T('backend.chunk', {n: it.chunk||1, total: it.chunks})",
    ):
        assert _unsafe(raw), raw
    for safe in (
        "escHooks(e.tool)",
        "F.format(e.chars_in||0)",
        "e.ok===false?'err':'ok'",
        "p.vram_mb!=null?fmtMB(p.vram_mb):'-'",
        "chunk",
    ):
        assert not _unsafe(safe), safe


def test_every_record_field_in_a_template_is_escaped():
    raw = [expr for expr in _template_slots(_main_script()) if _unsafe(expr)]
    assert raw == [], f"campos del servidor sin escapar en el panel: {raw}"


def test_the_panel_is_served_with_a_policy_that_lets_its_own_scripts_run():
    response = TestClient(metrics.app, client=("127.0.0.1", 50000)).get("/")
    assert response.status_code == 200
    policy = response.headers.get("content-security-policy", "")
    rules = {part.split()[0]: part.split()[1:] for part in policy.split(";") if part.strip()}
    script_src = rules.get("script-src", [])
    assert "'self'" in script_src
    assert "'unsafe-inline'" not in script_src
    assert "'unsafe-eval'" not in script_src
    assert rules.get("object-src") == ["'none'"]
    assert rules.get("connect-src") == ["'self'"]
    inline = _inline(response.text)
    assert inline == metrics.inline_scripts(response.text)
    assert len(inline) == 2, len(inline)  # el del tema en <head> y el del panel
    for body in inline:
        digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
        assert f"'sha256-{digest}'" in script_src
    # Solo esos: un hash de más sería un script que nadie sirve.
    assert len([x for x in script_src if x.startswith("'sha256-")]) == len(inline)
