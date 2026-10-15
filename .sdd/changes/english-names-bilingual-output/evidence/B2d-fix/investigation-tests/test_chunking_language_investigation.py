"""Investigación B2d-fix: ¿la orden de idioma llega a cada prompt del troceado? ¿y el post-proceso?

Se ejecuta con el conftest del repo cargado como plugin (aislamiento del entorno):

    PYTHONPATH=tests pytest -p conftest <este fichero> -p no:cacheprovider

Bloque A (controles, deben pasar): la orden endurecida llega al map, al reduce, al reagrupado,
a los subtrozos del reintento por desborde, al respaldo a otro modelo y a los trozos sin
secciones del resumen estructurado.
Bloque B (bugs/riesgos, FALLAN a propósito): post-proceso de `sections.complete`.
"""

from __future__ import annotations

import pytest

from local_delegate import config, i18n, sections, server

OUTPUT = "LOCAL_DELEGATE_OUTPUT_LANGUAGE"
BATCHES = [("es", "en", "inglés"), ("en", "es", "español")]


def _languages(monkeypatch, product: str, output: str | None) -> None:
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", product)
    if output is None:
        monkeypatch.delenv(OUTPUT, raising=False)
    else:
        monkeypatch.setenv(OUTPUT, output)
    i18n.reset()


def _hardened(system: str, name: str) -> bool:
    return (
        f" Escribe toda la respuesta en {name}, aunque el contenido esté en otro idioma" in system
    )


@pytest.fixture
def backend(monkeypatch, tmp_path):
    """Doble de `_post_chat`: el payload real (system incluido) de CADA intento, con su modelo."""
    seen: list[dict] = []
    state = {
        "respond": lambda model, payload, n: server.ChatResult(
            text="parcial breve", ok=True, finish_reason="stop"
        )
    }

    def post_chat(model, payload):
        seen.append(
            {
                "model": model,
                "system": payload["messages"][0]["content"],
                "user": payload["messages"][1]["content"],
                "max_tokens": payload["max_tokens"],
            }
        )
        return state["respond"](model, payload, len(seen))

    monkeypatch.setattr(server, "_post_chat", post_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    return seen, state


def _small_budgets(monkeypatch, chars: int = 1200) -> None:
    for role in ("mechanical", "long", "code"):
        monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, role, chars)
    monkeypatch.setattr(config, "CHUNK_MIN_CHARS", 200)


# --- A. Controles --------------------------------------------------------------------------


@pytest.mark.parametrize(("product", "output", "name"), BATCHES)
@pytest.mark.parametrize("tool", ["summarize_prose", "lint"])
def test_A1_map_reduce_and_regroup_carry_the_order(
    monkeypatch, backend, product, output, name, tool
):
    seen, state = backend
    _languages(monkeypatch, product, output)
    _small_budgets(monkeypatch)
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", False)

    def run():
        if tool == "lint":
            server.local_lint_summary(text="tests/x.py:1: E1 fallo de prueba largo\n" * 200)
        else:
            server.local_summarize(text="Texto del documento para resumir. " * 400)

    # 1) Parciales cortos: map + reduce.
    run()
    n_map = len([s for s in seen if not s["user"].startswith("Estos son resúmenes parciales")])
    reduce_steps = [s for s in seen if s["user"].startswith("Estos son resúmenes parciales")]
    assert n_map > 4, "guarda: troceó de verdad"
    assert reduce_steps, "guarda: hubo reduce"
    first = len(seen)
    # 2) Parciales LARGOS: no caben juntos en el reduce y se reagrupan (3 niveles).
    state["respond"] = lambda m, p, n: server.ChatResult(
        text="parcial " * 120, ok=True, finish_reason="stop"
    )
    run()
    assert len(seen) - first > n_map, "guarda: hubo reagrupado además del map"
    bad = [s["user"][:60] for s in seen if not _hardened(s["system"], name)]
    assert not bad, bad


@pytest.mark.parametrize(("product", "output", "name"), BATCHES)
def test_A2_overflow_split_retry_carries_the_order(monkeypatch, backend, product, output, name):
    seen, state = backend
    _languages(monkeypatch, product, output)
    _small_budgets(monkeypatch, 4000)
    monkeypatch.setattr(config, "FALLBACK", False)

    def respond(model, payload, n):
        if n == 1:  # el primer trozo «no cabe»
            return server.ChatResult(
                text="Context size has been exceeded.",
                ok=False,
                error="http_400",
                finish_reason=None,
            )
        return server.ChatResult(text="parcial", ok=True, finish_reason="stop")

    state["respond"] = respond
    server.local_lint_summary(text="tests/x.py:1: E1 fallo de prueba largo\n" * 200)
    assert len(seen) >= 4, "guarda: hubo subtrozos"
    assert all(_hardened(s["system"], name) for s in seen), [s["user"][:50] for s in seen]


@pytest.mark.parametrize(("product", "output", "name"), BATCHES)
def test_A3_fallback_to_another_model_carries_the_order(
    monkeypatch, backend, product, output, name
):
    from local_delegate.failures import FailureClass

    seen, state = backend
    _languages(monkeypatch, product, output)
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 0)  # rol long
    monkeypatch.setitem(config.FALLBACK_CHAINS, "long", "code")

    def respond(model, payload, n):
        if model == config.MODEL_LONG:
            return server.ChatResult(
                text="x", ok=False, error="http_500", error_class=FailureClass.MODEL
            )
        return server.ChatResult(text="respuesta", ok=True, finish_reason="stop")

    state["respond"] = respond
    server.local_lint_summary(text="src/x.py:1:1: E501 Line too long")
    models = [s["model"] for s in seen]
    assert config.MODEL_CODE in models, f"guarda: hubo salto ({models})"
    assert all(_hardened(s["system"], name) for s in seen)


@pytest.mark.parametrize(("product", "output", "name"), BATCHES)
def test_A4_structured_chunks_without_sections_carry_the_order(
    monkeypatch, backend, product, output, name
):
    """Una sección enorme parte en trozos «continúa la sección X» sin secciones propias."""
    seen, _state = backend
    _languages(monkeypatch, product, output)
    _small_budgets(monkeypatch)
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 0)
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", True)
    doc = "# Doc\n\n## Uno\n\n" + "Frase larga de la sección uno. " * 200 + "\n\n## Dos\n\nCorta.\n"
    server.local_summarize(text=doc)
    continuation = [
        s
        for s in seen
        if "continúa la sección" in s["user"] or "empieza a mitad de la sección" in s["user"]
    ]
    assert continuation, "guarda: hubo trozos de continuación"
    assert all(_hardened(s["system"], name) for s in seen)


# --- B. Post-proceso (fallan a propósito) ----------------------------------------------------

DOC_EMPTY_SECTION = (
    "# Paquete\n\n## Features\n\nOfrece muchas cosas útiles a quien lo usa a diario.\n\n"
    "## Release Information\n\n## 2.13.1 (September 23rd, 2026)\n\n### Fixed\n\n"
    "* Calculate Content-Length correctly when a file is passed.\n"
)


def test_B1_a_section_empty_in_the_document_is_not_reported_as_not_summarized(monkeypatch, backend):
    """Caso httpx2 (tanda 2): «## Release Information» está VACÍA en el documento. El modelo hace
    bien en dejarla vacía, pero `complete` la cuenta como `empty` y añade «1 section not
    summarized». FALLA hoy."""
    seen, state = backend
    _languages(monkeypatch, "en", "es")
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 0)
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", True)
    state["respond"] = lambda m, p, n: server.ChatResult(
        text=(
            "## Features\nOfrece muchas utilidades para el uso diario.\n\n"
            "## Release Information\n\n"
            "## 2.13.1 (September 23rd, 2026)\n**Fixed** Se corrige el cálculo de Content-Length."
        ),
        ok=True,
        finish_reason="stop",
    )
    out = server.local_summarize(text=DOC_EMPTY_SECTION)
    plan_line = [line for line in seen[0]["user"].splitlines() if "Release Information" in line]
    # El prompt además le pide palabras («unas N palabras») a una sección sin contenido:
    print("línea del plan:", plan_line)
    assert sections.WARNING_MARKER not in out, out


def test_B2_truncation_drops_a_whole_long_last_line_that_starts_with_hash():
    """Riesgo compatible con httpcore2 (tanda 1: 2112 tokens generados, 752 chars entregados,
    `## Changelog` vacío). Con `truncated=True`, `complete` quita la última línea si «parece un
    título», sea cual sea su largo: si el modelo escribió el cuerpo de una sección en una sola
    línea que empieza por `#`, se pierde entero. FALLA hoy."""
    body = "### 2.13.1 Fixed: " + "se corrige un fallo y se mejora otro aspecto; " * 80
    output = "## Intro\nTexto de la introducción breve.\n\n## Changelog\n" + body
    done = sections.complete(output, ["Intro", "Changelog"], truncated=True)
    assert "se corrige un fallo" in done.text, done.text
