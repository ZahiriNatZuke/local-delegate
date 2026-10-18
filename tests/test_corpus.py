"""Corpus v2 de la tanda de F2 (tarea 14 del SDD delegacion-precisa-y-fiable).

Las reglas del corpus se comprueban contra el codigo de produccion, no contra la tabla del
protocolo: se llama a la tool real con el backend interceptado y se mira que modelo elige y
cuantas llamadas hace. Cada regla tiene su control positivo —un caso que DEBE romperla— porque
una regla que no puede fallar no comprueba nada.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from local_delegate import benchmark, config, legacy_names, server

ROOT = Path(__file__).parents[1]
DESTINATION = ROOT / "benchmarks" / "catalogo-2026-09"


def _load():
    spec = importlib.util.spec_from_file_location(
        "build_corpus", ROOT / "scripts" / "build_corpus.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_corpus"] = module
    spec.loader.exec_module(module)
    return module


build = _load()


# --- Lo versionado ------------------------------------------------------------------------------


def _noticed_tools(notices: list[str], corpus: Path) -> set[str]:
    cases = json.loads((corpus / "cases.json").read_text(encoding="utf-8"))["cases"]
    tool_of = {c["id"]: c["tool"] for c in cases}
    return {tool_of[n.split(":", 1)[0]] for n in notices}


def test_versioned_corpus_still_mirrors_production():
    """Si cambia un MAX_CHARS, el enrutado o un prompt, el corpus ya no mide lo que dice. Desde la
    0.36.0 (B2b-2) la orden de idioma de REQ-028 cambia a propósito el `system` de cuatro tools: eso
    se dice como aviso (`PROMPT_BOUNDARIES`) y el resto sigue siendo error. Control: cambiar
    `_translate_system` deja una diferencia de una tool fuera de la lista y falla `== []`."""
    notices: list[str] = []
    assert build.check_versioned(DESTINATION, notices=notices) == []
    assert _noticed_tools(notices, DESTINATION) == set(build.PROMPT_BOUNDARIES["0.36.0"])
    # B2c: el commit cambia también sus topes; el resto de tools, solo el `system`. B2f: el lint
    # largo de una llamada cambia también su `user_template` (`lint-9k`), y solo esa tool.
    assert all("system" in n or "max_tokens" in n or "user_template" in n for n in notices), (
        "una frontera declarada fuera de los campos del prompt"
    )
    tool_of = {
        c["id"]: c["tool"]
        for c in json.loads((DESTINATION / "cases.json").read_text(encoding="utf-8"))["cases"]
    }
    templates = {n.split(":", 1)[0] for n in notices if "user_template" in n}
    assert templates == {"lint-9k"}  # guard: the change B2f declares is the one that is seen
    assert {tool_of[t] for t in templates} == {"local_lint_summary"}


def test_split_is_the_protocol_one():
    corpus = benchmark.load_corpus(DESTINATION / "cases.json")
    quality = Counter(c.role for c in corpus.cases if c.kind == "quality")
    assert quality == {"mechanical": 5, "long": 4, "code": 4, "vision": 2}
    assert sorted(c.role for c in corpus.cases if c.kind == "ceiling") == ["code", "long"]


def test_control_image_exists_and_is_not_the_case_one():
    corpus = benchmark.load_corpus(DESTINATION / "cases.json")
    (control,) = corpus.controls
    cases = [c for c in corpus.cases if c.id in control["para"]]
    assert len(cases) == 2
    assert all(c.raw["source_sha256"] != control["source_sha256"] for c in cases)


def test_no_user_path_reaches_the_versioned_corpus():
    for name in ("cases.json", legacy_names.LOG_COUNTS_FILE_NAMES[0]):
        text = (DESTINATION / name).read_text(encoding="utf-8")
        assert not re.search(r"[A-Za-z]:(\\\\|/)|/Users/|/home/|AppData", text), name
        assert str(Path.home()) not in text


def test_versioned_counts_add_up():
    # El error de la primera version del protocolo: una fila sumaba 152 y las demas 146.
    old_name = legacy_names.LOG_COUNTS_FILE_NAMES[0]
    counts = legacy_names.normalize_log_counts(
        json.loads((DESTINATION / old_name).read_text(encoding="utf-8"))
    )
    local = counts["local_events"]
    assert sum(t["n"] for t in counts["by_tool"].values()) == local
    assert sum(counts["by_model"].values()) == local
    assert sum(counts["by_source"].values()) == local
    assert counts["events"] == local + sum(counts["discarded_not_local"].values())


# --- El cargador ----------------------------------------------------------------------------------


def test_mismatching_hash_makes_the_load_fail(tmp_path):
    copied = tmp_path / "corpus"
    shutil.copytree(DESTINATION, copied)
    source = copied / "fuentes" / "clasificar-53.txt"
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(ValueError, match="clasificar-53: source_sha256 no cuadra"):
        benchmark.load_corpus(copied / "cases.json")


def test_the_control_hash_is_verified_too(tmp_path):
    copied = tmp_path / "corpus"
    shutil.copytree(DESTINATION, copied)
    control = copied / "fuentes" / "dashboard-bcbe39f.png"
    control.write_bytes(control.read_bytes()[:-1])
    with pytest.raises(ValueError, match="dashboard-bcbe39f: source_sha256 no cuadra"):
        benchmark.load_corpus(copied / "cases.json")


def test_a_live_path_in_source_file_is_rejected(tmp_path):
    copied = tmp_path / "corpus"
    shutil.copytree(DESTINATION, copied)
    path = copied / "cases.json"
    # La ruta viva EXISTE y su hash cuadra: solo la regla del nombre puede pararla. Sin el
    # fichero, la carga fallaria igual por «falta la fuente» y el test no probaria la regla.
    live = tmp_path / "CHANGELOG.md"
    live.write_bytes(b"## [9.9.9]\n")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cases"][0]["source_file"] = "../../CHANGELOG.md"
    data["cases"][0]["source_sha256"] = hashlib.sha256(live.read_bytes()).hexdigest()
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="nombre en fuentes/"):
        benchmark.load_corpus(path)


# --- Cada regla, con un caso que la tiene que romper ----------------------------------------------


def _case(**changes):
    base = {
        "id": "prueba",
        "tool": "local_summarize",
        "role": "mechanical",
        "kind": "quality",
        "provenance": "made_up",
        "origin": "test",
        "source": build.literal_text(""),
        "expected_terms": ("prueba",),
    }
    base.update(changes)
    return build.Case(**base)


def _errors(case, tmp_path, data: bytes, name="source.txt"):
    path = tmp_path / name
    path.write_bytes(data)
    single = None
    if case.kind == "ceiling":
        single = build.capture_case(case, path, data, no_chunking=True)
    return build.check(case, build.capture_case(case, path, data), data, single)


def test_well_formed_case_gives_no_errors(tmp_path):
    assert _errors(_case(), tmp_path, b"linea de prueba\n" * 20) == []


def test_role_rule_catches_a_file_production_sends_to_another_role(tmp_path):
    # Es el pyproject.toml entero: 7 073 bytes pasan de LONG_INPUT_CHARS y van a long.
    data = b"name = 'prueba'\n" * (config.LONG_INPUT_CHARS // 16 + 10)
    case = _case(tool="local_extract", expected_json_fields=("name",))
    errors = _errors(case, tmp_path, data, "large.toml")
    assert errors == [
        f"prueba: declarado mechanical, pero produccion eligio {config.MODEL_LONG} (long)"
    ]


def test_single_call_rule_catches_the_14k_translate(tmp_path):
    # local_translate trocea SIEMPRE a CHUNK_CHARS: 14 000 chars nunca llegan juntos al modelo.
    text = "Frase de prueba que hay que traducir entera.\n\n" * 300
    case = _case(
        tool="local_translate",
        role="long",
        arguments={"target_lang": "inglés"},
        terms_in_source=False,
    )
    errors = _errors(case, tmp_path, text.encode())
    assert len(errors) == 1 and "no cabe en una llamada, produccion hace" in errors[0]


def test_whole_input_rule_catches_a_truncation(tmp_path, monkeypatch):
    # Desde B2c ninguna tool de una llamada trunca la entrada: se reproduce el camino de antes de
    # explain_code (truncar a MAX_CHARS del rol code, una llamada) para que la regla siga probada.
    # (Con margen: el truncado añade su marca «[...contenido truncado...]» detrás.)
    monkeypatch.setattr(server, "_NO_TRUNCATE", config.max_chars_for_role("code") - 100)
    data = b"x = 1  # prueba\n" * (config.max_chars_for_role("code") // 16 + 200)
    case = _case(tool="local_explain_code", role="code")
    errors = _errors(case, tmp_path, data, "large.py")
    assert errors == ["prueba: el modelo no ve la entrada entera (truncada)"]


def test_explain_code_too_large_for_one_call_is_chunked(tmp_path):
    # B2c: lo que no cabe en el rol code ya no se trunca, se trocea; un caso de calidad así deja de
    # medir una sola llamada y la regla lo dice.
    data = b"x = 1  # prueba\n" * (config.max_chars_for_role("code") // 16 + 200)
    case = _case(tool="local_explain_code", role="code")
    errors = _errors(case, tmp_path, data, "large.py")
    assert len(errors) == 1 and errors[0].startswith("prueba: no cabe en una llamada"), errors


def test_ceiling_probe_that_fits_in_one_call_probes_nothing(tmp_path):
    case = _case(kind="ceiling", expected_terms=())
    errors = _errors(case, tmp_path, b"corto\n" * 10)
    assert errors == ["prueba: cabe en una llamada, asi que no sondea ningun techo"]


def test_expected_term_missing_from_the_source_is_rejected(tmp_path):
    case = _case(expected_terms=("prueba", "inexistente"))
    errors = _errors(case, tmp_path, b"linea de prueba\n" * 20)
    assert errors == ["prueba: el termino 'inexistente' no esta en la fuente"]


def test_id_promising_a_size_the_source_does_not_have():
    assert build._check_id_size("techo-resumen-120k", 106_092) != []
    assert build._check_id_size("techo-resumen-106k", 105_800) == []
    assert build._check_id_size("clasificar-53", 52) != []
    assert build._check_id_size("clasificar-53", 53) == []


def test_the_capture_does_not_write_to_the_usage_log_nor_call_the_backend(tmp_path, monkeypatch):
    log = tmp_path / "log"
    log.mkdir()
    monkeypatch.setattr(config, "LOG_DIR", log)
    case = _case()
    _errors(case, tmp_path, b"linea de prueba\n" * 20)
    assert list(log.iterdir()) == []


# --- Conteos del log ------------------------------------------------------------------------------


def test_count_log_drops_paths_outside_the_repo_and_non_local_events(tmp_path):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    log = tmp_path / "log"
    log.mkdir()
    events = [
        {
            "tool": "local_summarize",
            "model": "llama31-8b",
            "chars_in": 100,
            "source": "path",
            "path": str(root / "docs" / "a.md"),
        },
        {
            "tool": "local_summarize",
            "model": "gemma3-4b",
            "chars_in": 300,
            "source": "path",
            "path": str(tmp_path / "vault" / "personal-note.md"),
            "chunks": 3,
        },
        {"tool": "local_classify", "model": "gemma3-4b", "chars_in": 53, "source": "inline"},
        {"tool": "concurrency_test_resident", "model": "gemma3-4b", "chars_in": 1},
    ]
    lines = [json.dumps(e) for e in events] + ["{no es json"]
    (log / "usage-202609.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    counts = build.count_log(log, root)

    assert (counts["events"], counts["local_events"]) == (4, 3)
    assert counts["discarded_not_local"] == {"concurrency_test_resident": 1}
    assert counts["by_tool"]["local_summarize"]["n"] == 2
    assert counts["by_tool"]["local_summarize"]["chars_in_median"] == 200
    assert counts["by_model"] == {"gemma3-4b": 2, "llama31-8b": 1}
    assert counts["chunked"] == 1
    assert counts["repo_sources"] == {"docs/a.md": 1}
    assert counts["sources_outside_repo"] == 1
    dump = json.dumps(counts)
    assert "personal-note" not in dump and "vault" not in dump


# --- Parejas de referencia de CP-4 (tarea 15) -----------------------------------------------------


def _pairings():
    corpus = benchmark.load_corpus(DESTINATION / "cases.json")
    return [c for c in corpus.cases if "reference_signal" in c.raw]


def test_each_text_signal_has_its_pair():
    pairs = _pairings()
    assert sorted(c.raw["reference_signal"] for c in pairs) == sorted(build.EXPECTED_DIFFERENCES)
    assert all(c.kind == "quality" for c in pairs)


def test_each_versioned_pair_differs_only_in_its_signal_and_measures_the_same():
    # Lee el JSON versionado, no el constructor: una referencia retocada a mano tambien cae aqui.
    for case in _pairings():
        raw = case.raw
        arguments = (
            raw["expected_terms"],
            raw["forbidden_terms"],
            raw["expected_json_fields"],
            raw["execution_checks"],
            raw["expected_counts"],
        )
        ok = build.signals(raw["reference_ok"], *arguments)
        bad = build.signals(raw["reference_bad"], *arguments)
        differ = {name for name in ok if ok[name] != bad[name]}
        assert differ == build.EXPECTED_DIFFERENCES[raw["reference_signal"]], case.id
        assert len(raw["reference_ok"]) == len(raw["reference_bad"]), case.id
        assert ok["coverage"] and not ok["forbidden"], case.id


def test_pair_differing_in_two_signals_is_rejected():
    # La mala mete el termino prohibido Y pierde el esperado: separaria por cobertura, y CP-4 no
    # sabria si el puntuador acerto por la senal que se queria ejercitar.
    case = _case(
        expected_terms=("0.27.0",),
        forbidden_terms=("0.24.0",),
        reference=("forbidden", "Version 0.27.0 hoy", "Version 0.24.0 hoy"),
    )
    assert build.check_reference(case, ("0.27.0",)) == [
        (
            "prueba: la pareja de forbidden difiere en ['coverage', 'forbidden', "
            "'literal_coverage'], no en ['forbidden']"
        )
    ]


def test_pair_of_different_length_is_rejected():
    case = _case(expected_terms=("bug",), reference=("coverage", "bug", "nada"))
    assert build.check_reference(case, ("bug",)) == [
        "prueba: la pareja no tiene la misma longitud (3 y 4)"
    ]


def test_good_answer_that_is_not_good_is_rejected():
    case = _case(expected_terms=("bug",), reference=("coverage", "nada", "bug."))
    errors = build.check_reference(case, ("bug",))
    assert len(errors) == 1 and "la respuesta buena no es buena" in errors[0]


def test_nfkd_alone_does_not_remove_the_accent_and_normalisation_does():
    import unicodedata

    assert "computo" not in unicodedata.normalize("NFKD", "cómputo").casefold()
    assert build.flat("CÓMPUTO") == "computo"


def test_retouched_reference_that_is_still_valid_is_caught_by_the_watch(tmp_path):
    # El retoque deja una pareja VALIDA —misma longitud, difiere solo en cobertura—, asi que el
    # oraculo no lo ve: solo la comparacion contra el constructor puede. Un mutante que quitaba las
    # referencias de los campos vigilados sobrevivia a todo lo demas.
    copied = tmp_path / "corpus"
    shutil.copytree(DESTINATION, copied)
    path = copied / "cases.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    (case,) = [c for c in data["cases"] if c["id"] == "resumen-md-2k"]
    case["reference_ok"] = case["reference_ok"].replace("Guía", "Guia", 1)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    raw = case
    ok = build.signals(raw["reference_ok"], raw["expected_terms"], raw["forbidden_terms"], [])
    assert ok["coverage"], "el retoque tiene que dejar la pareja valida"
    assert build.check_versioned(copied) == [
        "resumen-md-2k: reference_ok ya no coincide con el constructor"
    ]


def test_rebuild_does_not_refreeze_a_source_from_the_live_file(tmp_path):
    # Paso en la tarea 16: regenerar para anadir un campo volvio a leer CHANGELOG.md y la salida de
    # ruff, y sobrescribio dos fuentes congeladas. La marca solo esta en la copia congelada: si el
    # constructor vuelve a leer CONTRIBUTING.md, desaparece.
    copied = tmp_path / "corpus"
    shutil.copytree(DESTINATION, copied)
    source = copied / "fuentes" / "resumen-md-2k.md"
    marked = source.read_bytes() + b"<!-- congelado -->\n"
    source.write_bytes(marked)

    rc = build.build(ROOT, copied, None)

    # La marca ANTES que el exit code: recongelando, la construccion puede fallar por otra regla
    # (el CHANGELOG vivo crece y cambia el tamano de su recorte), y el test caeria por eso en vez
    # de por lo que prueba. Tras una release que no cambiara el tamano, sobreviviria el defecto.
    assert source.read_bytes() == marked
    assert rc == 0
    (case,) = [
        c for c in benchmark.load_corpus(copied / "cases.json").cases if c.id == "resumen-md-2k"
    ]
    assert case.raw["source_sha256"] == hashlib.sha256(marked).hexdigest()


# --- Terminos derivados tras CP-3 (tarea 19) ------------------------------------------------------


def test_commit_terms_come_only_from_its_first_fixed_entry():
    diff = (
        " ## [Unreleased]\n"
        "+## [1.0.0]\n"
        "+\n"
        "+### Fixed\n"
        "+- Arreglo de `inflight`: `_privado` y `python -m x` no entran; `LOG_DIR/estado.json`,\n"
        "+  `/api/estado` y `snap()` si.\n"
        "+- Segunda entrada con `no_entra`.\n"
        "+### Added\n"
        "+- `tampoco`\n"
        "diff --git a/x b/x\n"
    )
    assert build._first_fix_identifiers(diff) == (
        "inflight",
        "estado.json",
        "/api/estado",
        "snap",
    )
    assert build._first_fix_identifiers("+### Added\n+- `x`\n") == ()


def test_changelog_terms_come_only_from_the_bold_headlines():
    text = (
        "## [1.0.0]\n\n### Changed\n"
        "- **Retirados `old.py` y `f()`.** El cuerpo nombra `no_entra`.\n"
        "- Entrada sin titular en negrita: `tampoco`.\n"
    )
    assert build._headline_identifiers(text) == ("old.py", "f")


_RUFF = (
    "src/a.py:1:1: CPY001 Missing copyright\n"
    "src/a.py:3:5: T201 `print` found\n"
    "src/a.py:9:5: T201 `print` found\n"
    "src/b.py:2:1: T201 `print` found\n"
    "src/b.py:4:1: COM812 Trailing comma missing\n"
    "src/c.py:1:1: CPY001 Missing copyright\n"
    "Found 6 errors.\n"
)


def test_lint_is_cut_at_whole_files_and_never_halfway():
    # a.py (3 lineas) cabe; b.py no cabe entero en el limite: no entra ni su primera linea.
    limit = len("".join(_RUFF.splitlines(keepends=True)[:4]))
    assert build.whole_files(_RUFF, limit) == "".join(_RUFF.splitlines(keepends=True)[:3])
    # Con sitio para todo, el resumen de ruff no se cuela: va en su propio bloque, al final.
    everything = build.whole_files(_RUFF, len(_RUFF) - len("Found 6 errors.\n"))
    assert "Found" not in everything and everything.count("\n") == 6


def test_valid_lint_counts_are_total_files_and_each_file():
    # T201: 3 en total, 2 archivos, 2 en a.py y 1 en b.py. CPY001: 2 en total, 2 archivos, 1 y 1.
    assert build._rule_counts(_RUFF) == {
        "T201": [1, 2, 3],
        "CPY001": [1, 2],
        "COM812": [1],
    }


def test_count_oracle_catches_the_made_up_count_of_the_second_pilot():
    counts = {"T201": [1, 2, 3]}
    assert build._counts_add_up("- src/a.py: T201 (2)\n- src/b.py: T201 (1)", counts)
    assert not build._counts_add_up("**T201 (Print):** 10 archivos (3 por archivo)", counts)
    # Nombrarla sin conteo no cuadra, y el «1.» de una lista o el 201 del codigo no cuentan.
    assert not build._counts_add_up("T201 aparece mucho", counts)
    assert build._counts_add_up("1. T201: 3", counts)
    # Cada numero es de la regla que tiene delante, y el punto de final de frase no lo anula: los
    # dos defectos de la primera version, que rompieron la pareja de referencia.
    two = {"T201": [1, 2, 3], "COM812": [1]}
    assert build._counts_add_up("a.py: T201 (2), COM812 (1). b.py: T201 3.", two)
    assert not build._counts_add_up("a.py: T201 (2), COM812 (2).", two)
    assert not build._counts_add_up("Python 3.12: T201 3.5", counts)


def test_requested_format_comes_from_the_tool_prompt():
    summary = (
        "Output EXACTO: un resumen en prosa clara. Máximo 150 palabras. Nada fuera del formato."
    )
    assert build.requested_format(summary) == {"max_words": 150, "prose": True}
    lint = "Output EXACTO: un resumen agrupado por archivo. Maximo 200 palabras."
    assert build.requested_format(lint) == {"max_words": 200}
    assert build.requested_format("Clasifica en una etiqueta.") == {}
    assert build.requested_format(None) == {}


def test_open_text_cases_are_decided_by_the_pairs():
    corpus = {c.id: c.raw for c in benchmark.load_corpus(DESTINATION / "cases.json").cases}
    opened = {
        "resumen-md-10k",
        "resumen-changelog-7k",
        "explicar-metrics-15k",
        "explicar-install-20k",
        "commit-diff-19k",
        "lint-9k",
    }
    assert {cid for cid, c in corpus.items() if c.get("automatic_scoring") is False} == opened
    assert corpus["resumen-md-10k"]["expected_format"] == {"max_words": 150, "prose": True}


def test_explain_terms_come_from_the_module_docstring_not_from_a_function():
    source = (
        '"""m.py\n\n  GET /           -> html\n  GET /api/a     -> x\n  GET /api/b     -> y\n'
        'Toca `~/.x/settings.json`, `dir/` y `--dry-run`.\n"""\n\n'
        'def f():\n    """GET /api/fuera y `otro.md`."""\n'
    )
    assert build._docstring_paths(source) == ("/api/a", "/api/b")
    assert build._docstring_files_and_flags(source) == ("settings.json", "--dry-run")


# =====================================================================================================
# Corpus de afinidad (REQ-040): la regla de seleccion de commits, las trampas y el corpus construido.
# La regla se prueba sobre repos git sinteticos en `tmp_path`: un test que leyera el historial real
# fallaria en un checkout superficial del CI.
# =====================================================================================================

CUTOFF = "2026-10-06"
SYNTHETIC_STEPS = ((None, 300, 1200),)


def _git_repo(
    repo: Path, *args: str, date: str | None = None, author: str = "Ana <ana@example.org>"
):
    env = {
        **os.environ,
        "GIT_COMMITTER_NAME": "Ana",
        "GIT_COMMITTER_EMAIL": "ana@example.org",
        "GIT_AUTHOR_NAME": author.split(" <")[0],
        "GIT_AUTHOR_EMAIL": author.split("<")[1].rstrip(">"),
    }
    if date:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = f"{date}T12:00:00+00:00"
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )


def _new_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_repo(repo, "init", "-q", "-b", "main")
    return repo


def _confirm(
    repo, subject, file, size=400, date="2026-09-01", author="Ana <ana@example.org>", body=""
):
    """Un commit que deja en `file` una linea de `size` caracteres, propia de este commit."""
    line = (subject + " " + "x" * size)[:size]
    (repo / file).write_text(line + "\n", encoding="utf-8", newline="\n")
    _git_repo(repo, "add", "-A")
    message = subject + (f"\n\n{body}" if body else "")
    _git_repo(repo, "commit", "-q", "-m", message, date=date, author=author)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _rule_repo(tmp_path):
    """Los elegibles `ok-NN`, mezclados con todo lo que la regla excluye entre los mas recientes."""
    repo = _new_repo(tmp_path)
    day = iter(range(1, 28))

    def date():
        return f"2026-09-{next(day):02d}"

    for i in range(1, 11):
        _confirm(repo, f"feat: ok-{i:02d}", f"f{i}.txt", date=date())
    excluded = [
        ("ok-11", {}),
        ("chore(release): 1.1", {}),
        ("ok-12", {}),
        ("chore(deps): sube una libreria", {}),
        ("chore: release v1.0", {}),
        ("ok-13", {}),
        ("fix: subir otra libreria", {"author": "dependabot[bot] <bot@example.org>"}),
        ("fix: diff chico", {"size": 20}),
        ("ok-14", {}),
        ("fix: diff enorme", {"size": 3000}),
    ]
    for n, (subject, kw) in enumerate(excluded):
        if subject.startswith("ok-"):
            subject = f"feat: {subject}"
        _confirm(repo, subject, f"g{n}.txt", date=date(), **kw)
    # Un merge sin conflicto y un commit posterior a la fecha de corte.
    _git_repo(repo, "checkout", "-q", "-b", "rama")
    _confirm(repo, "fix: diff chico de la rama", "branch.txt", size=20, date=date())
    _git_repo(repo, "checkout", "-q", "main")
    _git_repo(repo, "merge", "-q", "--no-ff", "rama", "-m", "Merge rama", date=date())
    _confirm(repo, "feat: tardio", "late.txt", date="2026-10-07")
    return repo


def _subjects(commits):
    return [c.subject for c in commits]


def test_rule_picks_expected_in_order_and_next_as_trap(tmp_path):
    repo = _rule_repo(tmp_path)
    sel = build.select_commits(
        repo, before=CUTOFF, exclude=(), n_real=3, n_traps=2, steps=SYNTHETIC_STEPS
    )
    chosen_set = _subjects(sel.real) + _subjects(sel.traps)
    # `chore(release): 1.1` SI es candidato: la regla excluye el texto exacto `chore: release`.
    assert chosen_set == [
        "feat: ok-14",
        "feat: ok-13",
        "feat: ok-12",
        "chore(release): 1.1",
        "feat: ok-11",
    ]
    assert _subjects(sel.real) == ["feat: ok-14", "feat: ok-13", "feat: ok-12"]
    assert _subjects(sel.traps) == ["chore(release): 1.1", "feat: ok-11"]
    # Todo lo que la regla excluye, de verdad estaba en el historial (control positivo).
    all_items = _subjects(build._commits_of(repo, "main", None))
    for excluded in (
        "chore: release v1.0",
        "fix: subir otra libreria",
        "feat: tardio",
    ):
        assert excluded in all_items


def test_no_trap_matches_real_case(tmp_path):
    repo = _rule_repo(tmp_path)
    sel = build.select_commits(
        repo, before=CUTOFF, exclude=(), n_real=3, n_traps=2, steps=SYNTHETIC_STEPS
    )
    real = {c.hash for c in sel.real}
    traps = {c.hash for c in sel.traps}
    assert len(traps) == 2
    assert not real & traps
    real_diffs = {build._normalized_diff(repo, h) for h in real}
    assert not real_diffs & {build._normalized_diff(repo, h) for h in traps}


def test_rule_widens_if_window_lacks_commits(tmp_path):
    repo = _rule_repo(tmp_path)
    # Una ventana de 3 commits no da 5: el segundo paso mira todo el historial.
    steps = ((3, 300, 700), (None, 300, 700))
    sel = build.select_commits(repo, before=CUTOFF, exclude=(), n_real=3, n_traps=2, steps=steps)
    assert sel.step == 1
    assert len(sel.real) == 3 and len(sel.traps) == 2
    with pytest.raises(ValueError, match="no da 40 commits"):
        build.select_commits(repo, before=CUTOFF, exclude=(), n_real=30, n_traps=10, steps=steps)


def test_case_already_in_f2_and_private_diffs_not_chosen(tmp_path):
    repo = _new_repo(tmp_path)
    for i in range(1, 6):
        _confirm(repo, f"feat: ok-{i}", f"f{i}.txt", date=f"2026-09-{i:02d}")
    private_item = repo / "p.txt"
    private_item.write_text(
        "ruta C:\\Users\\Persona\\secreto " + "x" * 400 + "\n", encoding="utf-8"
    )
    _git_repo(repo, "add", "-A")
    _git_repo(repo, "commit", "-q", "-m", "feat: con ruta privada", date="2026-09-10")
    sel = build.select_commits(
        repo, before=CUTOFF, n_real=2, n_traps=1, steps=SYNTHETIC_STEPS, exclude=()
    )
    assert _subjects(sel.real)[0] == "feat: con ruta privada"
    sel = build.select_commits(
        repo,
        before=CUTOFF,
        n_real=2,
        n_traps=1,
        steps=SYNTHETIC_STEPS,
        exclude=(),
        discard_if=lambda text: bool(build.private_data(text)),
    )
    assert "feat: con ruta privada" not in _subjects(sel.real + sel.traps)
    first = sel.real[0]
    sel = build.select_commits(
        repo,
        before=CUTOFF,
        n_real=2,
        n_traps=1,
        steps=SYNTHETIC_STEPS,
        exclude=(first.hash[:7],),
        discard_if=lambda text: bool(build.private_data(text)),
    )
    assert first.hash not in {c.hash for c in sel.real + sel.traps}


# --- La trampa «de la misma zona» --------------------------------------------------------------------


def _zone_repo(tmp_path):
    repo = _new_repo(tmp_path)
    long = "docs: " + "un asunto demasiado largo para una linea de commit " * 2  # > 72
    assert len(long) > 72
    _confirm(repo, long.strip(), "large.txt", size=80, date="2026-08-01")
    _confirm(
        repo,
        "fix: asunto del segundo fichero (#12)",
        "small.txt",
        size=80,
        date="2026-08-02",
        body="Primera linea del cuerpo.\n* feat: el asunto repetido por el squash\nSegunda linea.\n\n"
        "Co-Authored-By: Alguien <a@example.org>\nClaude-Session: https://claude.ai/code/session_ABCDEFGHIJ",
    )
    # El commit del caso trampa: toca `grande.txt` mucho y `chico.txt` poco.
    path = repo / "large.txt"
    path.write_text(
        path.read_text(encoding="utf-8") + "linea nueva\n" * 40, encoding="utf-8", newline="\n"
    )
    (repo / "small.txt").write_text("otro\n", encoding="utf-8", newline="\n")
    _git_repo(repo, "add", "-A")
    _git_repo(repo, "commit", "-q", "-m", "feat: el cambio del caso", date="2026-09-01")
    return repo


def test_same_zone_trap_subject_at_most_72_chars(tmp_path):
    repo = _zone_repo(tmp_path)
    case = next(
        c for c in build._commits_of(repo, "main", None) if c.subject == "feat: el cambio del caso"
    )
    # `grande.txt` es el fichero mas cambiado: su unico otro commit tiene un asunto de mas de 72.
    assert build._numstat(repo, case.hash)[0][1] == "large.txt"
    zone = build.same_zone_subject(repo, case, {case.hash}, before=CUTOFF)
    assert zone is not None
    assert len(zone["subject"]) <= 72
    # Pasa al siguiente fichero mas cambiado, y le quita el « (#12)» del squash.
    assert (zone["file"], zone["subject"]) == ("small.txt", "fix: asunto del segundo fichero")
    # El cuerpo real, sin firmas, sin enlaces de sesion y sin el asunto repetido.
    assert zone["real_body"] == ["Primera linea del cuerpo.", "Segunda linea."]
    # Sin ningun candidato, no inventa ninguno.
    assert build.same_zone_subject(repo, case, {case.hash}, before=CUTOFF, max_subject=5) is None


def test_build_traps_gives_three_per_set_with_three_kinds(tmp_path, monkeypatch):
    repo = _new_repo(tmp_path)
    for z in range(3):  # el commit de cada zona, de asunto corto y fuera de la seleccion
        _confirm(repo, f"docs: zona {z}", f"z{z}.txt", size=30, date="2026-08-01")
    for i in range(1, 12):
        file = f"z{(i - 1) % 3}.txt"
        _confirm(repo, f"feat: ok-{i:02d}", file, size=400, date=f"2026-09-{i:02d}")
    sel = build.select_commits(
        repo, before=CUTOFF, exclude=(), n_real=2, n_traps=9, steps=SYNTHETIC_STEPS
    )
    assert len(sel.traps) == 9
    written = {
        c.short: {
            "subject": f"chore: redactada {c.short}",
            "body": [f"linea {n}" for n in range(5)],
        }
        for k, c in enumerate(sel.traps)
        if k % 3 != 0
    }
    reserves = {
        c.short: [f"reserva {n}" for n in range(5)] for k, c in enumerate(sel.traps) if k % 3 == 0
    }
    monkeypatch.setattr(build, "WRITTEN_TRAPS", written)
    monkeypatch.setattr(build, "SAME_ZONE_RESERVES", reserves)
    traps = build.build_traps(repo, sel, before=CUTOFF)
    assert [j["set"] for j in traps["sets"]] == [1, 2, 3]
    all_items = []
    for case_set_item in traps["sets"]:
        assert [t["kind"] for t in case_set_item["traps"]] == [
            "same-zone",
            "secondary",
            "generic",
        ]
        for t in case_set_item["traps"]:
            assert len(t["subject"]) <= 72 and 1 <= len(t["body"]) <= 5
            all_items.append(t["case"])
    assert len(set(all_items)) == 9
    assert set(all_items) == {f"commit-trampa-{c.short}" for c in sel.traps}
    # La de la misma zona es el asunto REAL de otro commit del mismo fichero, fuera de la seleccion.
    first_one = traps["sets"][0]["traps"][0]
    assert first_one["subject"].startswith("docs: zona ")
    assert first_one["subject_of"]["hash"] not in {c.hash for c in sel.real + sel.traps}
    assert first_one["source_body"] != "real-rewritten"
    # Con el cuerpo reescrito a mano, ese cuerpo manda sobre las lineas reales (partidas a 80 columnas).
    monkeypatch.setattr(build, "SAME_ZONE_BODIES", {sel.traps[0].short: ["Una frase entera."]})
    rewritten = build.build_traps(repo, sel, before=CUTOFF)["sets"][0]["traps"][0]
    assert rewritten["body"] == ["Una frase entera."]
    assert rewritten["source_body"] == "real-rewritten"
    # Si falta la trampa redactada de un caso, no se inventa: se para.
    monkeypatch.setattr(build, "WRITTEN_TRAPS", {})
    with pytest.raises(ValueError, match="falta la trampa redactada"):
        build.build_traps(repo, sel, before=CUTOFF)


# --- Datos privados -----------------------------------------------------------------------------------


def test_private_data_detects_private_and_lets_harmless_pass():
    private_items = build.private_data(
        "ruta C:\\Users\\Persona\\x.py y /home/persona/y, ip 100.64.1.2, sesion session_ABCDEFGH12, "
        "correo persona@gmail.com"
    )
    assert len(private_items) == 5, private_items
    harmless = (
        "C:\\Users\\...\\hook.py, /Users/<usuario>/x, 127.0.0.1, 0.0.0.0, 203.0.113.7, version 0.28.0, "
        "marta@example.org, +@pytest.fixture y opencode-ai@1.18.11"
    )
    assert build.private_data(harmless) == []


# --- El corpus construido -----------------------------------------------------------------------------


def _built_corpus():
    path = os.environ.get("LD_AFFINITY_CORPUS") or str(ROOT / "benchmarks" / "afinidad-2026-10")
    cases = Path(path) / "cases.json"
    if not cases.is_file():
        pytest.skip(f"el corpus de afinidad aun no esta construido en {path}")
    return Path(path), cases


def _traps_file(folder):
    """`traps.json` si el constructor ya lo escribio; si no, el `trampas.json` congelado."""
    old_name, new_name = legacy_names.TRAPS_FILE_NAMES
    return folder / new_name if (folder / new_name).exists() else folder / old_name


@pytest.fixture
def affinity():
    folder, cases = _built_corpus()
    corpus = benchmark.load_corpus(cases)  # verifica el sha256 de cada fuente
    # Normalizado, como lo leen `build_corpus` y `analyze_benchmark`: el congelado sigue en el
    # formato viejo (lo prueba `test_frozen_affinity_corpus_is_read_with_the_new_keys`).
    data = legacy_names.normalize_affinity_corpus(json.loads(cases.read_text(encoding="utf-8")))
    return folder, data, corpus


def test_affinity_corpus_has_spec_size(affinity):
    _, data, corpus = affinity
    cases = data["cases"]

    def tally(tool, **filter_fn):
        return sum(
            1
            for c in cases
            if c["tool"] == tool and all(c.get(k) == v for k, v in filter_fn.items())
        )

    new_items = {"discriminating": True, "sheet_role": None}
    assert tally("local_classify", **new_items) == 8
    assert tally("local_extract", **new_items) == 8
    assert tally("local_translate", **new_items) == 4
    assert tally("local_lint_summary", **new_items) == 4
    assert tally("local_delegate", **new_items) == 4
    assert tally("local_commit_msg", sheet_role="real") == 30
    assert tally("local_commit_msg", sheet_role="trap") == 9
    regression = [
        c["id"]
        for c in cases
        if c["discriminating"] is False and c["kind"] == "quality" and c["sheet_role"] is None
    ]
    assert sorted(regression) == sorted(build.F2_REGRESSION)
    assert [c["id"] for c in cases if c["kind"] == "ceiling"] == [build.F2_CEILING_CASE]
    assert len(corpus.cases) == len(cases) == 73
    assert build.F2_REAL_CASE in {c["id"] for c in cases if c.get("sheet_role") == "real"}


def test_each_mechanical_case_discriminates_with_its_scorer(affinity):
    # El criterio 1, en su parte del corpus: la referencia buena puntua 1 y la mala, menos de 1. Si
    # falla, el caso esta mal construido: se corrige el caso, no el puntuador.
    _, data, _ = affinity
    analyze = build.analyzer()
    mechanical_ones = [
        c for c in data["cases"] if c["discriminating"] and c["tool"] != "local_commit_msg"
    ]
    assert len(mechanical_ones) == 28
    for case in mechanical_ones:
        ok = analyze.score_affinity(case, case["reference_ok"])
        bad = analyze.score_affinity(case, case["reference_bad"])
        assert ok == {"quality": 1.0, "format": True}, case["id"]
        assert bad["quality"] < 1.0, case["id"]


def test_corpus_declares_what_spec_requires(affinity):
    _, data, _ = affinity
    by_id = {c["id"]: c for c in data["cases"]}
    classify_fn = [
        c for c in data["cases"] if c["tool"] == "local_classify" and c["discriminating"]
    ]
    assert all(len(c["scorer"]["labels"]) >= 4 for c in classify_fn)
    assert all(set(c["scorer"]["acceptable"]) <= set(c["scorer"]["labels"]) for c in classify_fn)
    assert "clasifica-bug-con-etiquetas-en-ingles" in by_id  # etiquetas en ingles, texto en español
    extract_fn = [
        c["scorer"]["expected"]
        for c in by_id.values()
        if c["tool"] == "local_extract" and c["discriminating"]
    ]
    assert any(None in e.values() for e in extract_fn)  # un campo ausente que sale null
    assert any(isinstance(v, (int, float)) for e in extract_fn for v in e.values())  # numeros
    for case in data["cases"]:
        assert case["provenance"] and case["origin"]
        if case["kind"] == "quality":
            assert case["system"] and case["user_template"] and case["max_tokens"]
            assert case["production"]["calls"] == 1, case["id"]
        if case["discriminating"]:
            assert case["reference_ok"] and case["reference_bad"], case["id"]
    # Cada caso pide lo que la tool de produccion pide: el rol sale de la captura, no de una tabla.
    assert {c["role"] for c in data["cases"] if c["tool"] == "local_commit_msg"} == {"code"}
    assert {c["role"] for c in data["cases"] if c["tool"] == "local_classify"} == {"mechanical"}


def test_traps_match_no_real_case_and_do_not_repeat(affinity):
    folder, data, _ = affinity
    real = [c for c in data["cases"] if c.get("sheet_role") == "real"]
    traps = [c for c in data["cases"] if c.get("sheet_role") == "trap"]
    assert not {c["commit"] for c in real} & {c["commit"] for c in traps}
    assert not {c["source_sha256"] for c in real} & {c["source_sha256"] for c in traps}
    assert len({c["source_sha256"] for c in real + traps}) == 39
    traps_json = legacy_names.normalize_affinity_traps(
        json.loads(_traps_file(folder).read_text(encoding="utf-8"))
    )
    ids = []
    for case_set_item in traps_json["sets"]:
        assert [t["kind"] for t in case_set_item["traps"]] == [
            "same-zone",
            "secondary",
            "generic",
        ]
        for t in case_set_item["traps"]:
            assert len(t["subject"]) <= 72 and 1 <= len(t["body"]) <= 5
            assert build._CONVENTIONAL_PREFIX.match(t["subject"]), t["subject"]
            ids.append(t["case"])
    assert sorted(ids) == sorted(c["id"] for c in traps)
    # Cada commit sale de la regla; la lista esta en cases.json.
    sel = data["selection"]
    assert [x["hash"] for x in sel["real"]] == [
        c["commit"] for c in real if c["id"] != build.F2_REAL_CASE
    ]


def test_nothing_private_goes_to_repo(affinity):
    folder, _, _ = affinity
    for file in [
        folder / "cases.json",
        _traps_file(folder),
        *sorted((folder / "fuentes").iterdir()),
    ]:
        if file.suffix in (".png",):
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        assert build.private_data(text) == [], file.name


# --- El idioma del mensaje de commit es el del corpus, no el del entorno (REQ-044) ----------------
# Los casos de commit llevan el prompt de produccion, que incluye la orden de idioma de
# `LOCAL_DELEGATE_COMMIT_LANGUAGE`. Cada corpus se congelo con un idioma (`AFFINITY_COMMIT_LANGUAGE`,
# `F2_COMMIT_LANGUAGE`) y la captura lo FIJA: antes conservaba la variable de quien la corria, y
# `affinity --check` daba ok solo con `=es` puesta (40 diferencias sin ella). Los tests ponen la
# variable a mano porque la suite corre sin ella (conftest): sin esto el agujero no se veria nunca.
_SMALL_DIFF = "diff --git a/uno.py b/uno.py\n--- a/uno.py\n+++ b/uno.py\n@@ -1 +1 @@\n-a\n+b\n"
_ASKS_SPANISH = "(primera línea y cuerpo) en español."
_ASKS_DIFF_LANGUAGE = "en el idioma predominante de los textos del diff"
_ENVIRONMENT_LANGUAGES = pytest.mark.parametrize("environment_language", [None, "es", "en"])


def _captured_commit_system(tmp_path, commit_language: str) -> str:
    from local_delegate import server

    path = tmp_path / "small.diff"
    path.write_text(_SMALL_DIFF, encoding="utf-8")
    with build.intercepted_production(commit_language) as calls:
        server.local_commit_msg(path=str(path))
    assert len(calls) == 1
    return calls[0].system


def _set_environment_language(monkeypatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv(build.COMMIT_LANGUAGE_VARIABLE, raising=False)
    else:
        monkeypatch.setenv(build.COMMIT_LANGUAGE_VARIABLE, value)


def test_frozen_commit_languages_match_the_frozen_cases():
    """Las constantes dicen con que idioma se congelo cada corpus; aqui se mira en lo congelado."""
    affinity = json.loads((build.AFFINITY_TARGET / "cases.json").read_text(encoding="utf-8"))
    f2 = json.loads((DESTINATION / "cases.json").read_text(encoding="utf-8"))
    affinity_commits = [c for c in affinity["cases"] if c["tool"] == "local_commit_msg"]
    f2_commits = [c for c in f2["cases"] if c["tool"] == "local_commit_msg"]
    assert len(affinity_commits) == 40 and len(f2_commits) == 2  # que haya algo que comprobar
    assert build.AFFINITY_COMMIT_LANGUAGE == "es"
    assert all(c["system"].endswith(_ASKS_SPANISH) for c in affinity_commits)
    # B2b-2: vacío ya es el idioma vigente; la regla del diff, con la que se congeló F2, es `diff`.
    assert build.F2_COMMIT_LANGUAGE == "diff"
    assert all(_ASKS_DIFF_LANGUAGE in c["system"] for c in f2_commits)


@_ENVIRONMENT_LANGUAGES
def test_affinity_capture_ignores_the_environment_language(
    tmp_path, monkeypatch, environment_language
):
    """Mutante: que `intercepted_production` vuelva a dejar la variable del usuario. Con `None` o
    `en`, el prompt sale con otra orden y falla el assert de `en español.`"""
    _set_environment_language(monkeypatch, environment_language)
    system = _captured_commit_system(tmp_path, build.AFFINITY_COMMIT_LANGUAGE)
    assert system.endswith(_ASKS_SPANISH)
    # Y la deja como estaba.
    assert os.environ.get(build.COMMIT_LANGUAGE_VARIABLE) == environment_language


@_ENVIRONMENT_LANGUAGES
def test_f2_capture_ignores_the_environment_language(tmp_path, monkeypatch, environment_language):
    """El corpus F2 se congelo sin variable: con `es` en el entorno, su `--check` daba 2
    diferencias. Control del anterior: el mismo mecanismo con el otro idioma."""
    _set_environment_language(monkeypatch, environment_language)
    system = _captured_commit_system(tmp_path, build.F2_COMMIT_LANGUAGE)
    assert _ASKS_DIFF_LANGUAGE in system
    assert os.environ.get(build.COMMIT_LANGUAGE_VARIABLE) == environment_language


def _full_history() -> bool:
    """`select_commits` lee `main` entero; el checkout superficial del CI no lo tiene."""

    def git(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
        return done.stdout.strip() if done.returncode == 0 else ""

    return (
        bool(git("rev-parse", "--verify", "main"))
        and git("rev-parse", "--is-shallow-repository") == "false"
    )


@pytest.mark.skipif(not _full_history(), reason="sin el historial de `main` (checkout superficial)")
@pytest.mark.parametrize("environment_language", [None, "en"])
def test_affinity_check_is_ok_with_any_environment_language(monkeypatch, environment_language):
    """La comprobacion entera, como la corre `affinity --check`, sin la variable y con otra."""
    _set_environment_language(monkeypatch, environment_language)
    notices: list[str] = []
    assert build.check_versioned_affinity(build.AFFINITY_TARGET, notices=notices) == []
    # B2b-2: lint ×4 y summarize ×1 cambian a propósito (REQ-028). B2c: los 40 commits también
    # (cuerpo obligatorio y topes nuevos).
    assert _noticed_tools(notices, build.AFFINITY_TARGET) == {
        "local_lint_summary",
        "local_summarize",
        "local_commit_msg",
    }


# --- Lectura dual de lo congelado del corpus (ola A10b-4) -------------------------------------------

AFFINITY = ROOT / "benchmarks" / "afinidad-2026-10"


def test_frozen_reference_signals_are_read_in_english():
    raw = json.loads((DESTINATION / "cases.json").read_text(encoding="utf-8"))
    old = {c["reference_signal"] for c in raw["cases"] if "reference_signal" in c}
    # Control: el congelado sigue con las senales de antes.
    assert {"cobertura", "prohibido", "json_valido", "json_campos", "ejecucion", "conteos"} <= old
    assert {c.raw["reference_signal"] for c in _pairings()} == set(build.EXPECTED_DIFFERENCES)


def test_frozen_log_counts_are_read_with_the_new_keys():
    old_name, new_name = legacy_names.LOG_COUNTS_FILE_NAMES
    assert not (DESTINATION / new_name).exists()
    raw = json.loads((DESTINATION / old_name).read_text(encoding="utf-8"))
    assert "eventos_local" in raw
    counts = legacy_names.normalize_log_counts(raw)
    local = counts["local_events"]
    assert local and sum(t["n"] for t in counts["by_tool"].values()) == local
    assert sum(counts["by_model"].values()) == sum(counts["by_source"].values()) == local
    assert all({"chars_in_median", "models"} <= set(t) for t in counts["by_tool"].values())
    assert legacy_names.normalize_log_counts(counts) == counts


def test_frozen_affinity_corpus_is_read_with_the_new_keys():
    raw = json.loads((AFFINITY / "cases.json").read_text(encoding="utf-8"))
    assert "seleccion" in raw and any("puntuador" in c for c in raw["cases"])
    corpus = legacy_names.normalize_affinity_corpus(raw)
    assert set(corpus["selection"]) >= {"rule", "deadline", "step", "privacy", "f2_case", "real"}
    # El valor de `--privacy` y la clave de la fecha de cada commit salen en inglés (lote 5).
    assert raw["seleccion"]["privacidad"] != corpus["selection"]["privacy"]  # sí es viejo
    assert corpus["selection"]["traps"] and corpus["selection"]["privacy"] == "exclude"
    for key, old_key in (("real", "reales"), ("traps", "trampas")):
        assert all("date" not in c for c in raw["seleccion"][old_key])  # sí es viejo
        assert all(set(c) == {"hash", "date", "chars"} for c in corpus["selection"][key]), key
    for case in corpus["cases"]:
        assert "scorer" in case and "puntuador" not in case, case["id"]
        assert {"provenance", "origin"} <= set(case) and "procedencia" not in case, case["id"]
        assert "kind" in case["scorer"] and "tipo" not in case["scorer"], case["id"]
    assert legacy_names.normalize_affinity_corpus(corpus) == corpus


def test_frozen_trap_body_origins_are_read_in_english():
    """`source_body` de cada trampa congelada: el valor viejo, leído con el que escribe hoy
    `build_traps` (cierre del frente A, lote 5)."""
    raw = json.loads((AFFINITY / legacy_names.TRAPS_FILE_NAMES[0]).read_text(encoding="utf-8"))
    old = [t["cuerpo_origen"] for s in raw["juegos"] for t in s["trampas"]]
    traps = legacy_names.normalize_affinity_traps(raw)
    new = [t["source_body"] for s in traps["sets"] for t in s["traps"]]
    assert len(new) == len(old) == 9
    assert not set(old) & {"written", "real+written", "real-rewritten"}  # sí es viejo
    assert sorted(new) == ["real-rewritten"] * 3 + ["written"] * 6


# --- Valores del corpus en inglés y su lectura dual (cierre del frente A, lote 3) -------------------

# Escritas a mano: si salieran de `legacy_names`, una tabla vacía daría un formato «viejo» igual al
# nuevo y el test no distinguiría nada.
_OLD_PROVENANCES = {
    "congelado": "frozen",
    "generado": "generated",
    "reconstruido": "reconstructed",
    "inventado": "made_up",
}
_OLD_MEDIA = {"texto": "text", "imagen": "image"}
_OLD_SHEET_ROLES = {"trampa": "trap", "real": "real", None: None}
_OLD_SCORER_KINDS = {"techo": "ceiling", "hoja": "sheet"}


@pytest.mark.parametrize("corpus", ["catalogo-2026-09", "afinidad-2026-10"])
def test_frozen_corpus_values_are_read_in_english(corpus):
    """Los corpus congelados dicen `congelado`, `texto`, `trampa`, `techo`…; `load_corpus` y
    `normalize_affinity_corpus` los dan en inglés."""
    raw = json.loads((ROOT / "benchmarks" / corpus / "cases.json").read_text(encoding="utf-8"))
    cases = raw["cases"]
    # Control: lo congelado sigue con los valores de antes; si no, el test no probaría nada.
    assert {c["procedencia"] for c in cases} == set(_OLD_PROVENANCES)
    assert {c["media_type"] for c in cases} <= set(_OLD_MEDIA)
    expected_provenance = [_OLD_PROVENANCES[c["procedencia"]] for c in cases]
    expected_media = [_OLD_MEDIA[c["media_type"]] for c in cases]
    normalized = legacy_names.normalize_affinity_corpus(raw)["cases"]
    assert [c["provenance"] for c in normalized] == expected_provenance
    assert [c["media_type"] for c in normalized] == expected_media
    if corpus == "catalogo-2026-09":
        assert "imagen" in {c["media_type"] for c in cases}
        loaded = benchmark.load_corpus(ROOT / "benchmarks" / corpus / "cases.json").cases
        assert [c.provenance for c in loaded] == expected_provenance
        assert [c.media_type for c in loaded] == expected_media
        return
    assert "trampa" in {c.get("rol_en_hoja") for c in cases}
    assert {"techo", "hoja"} <= {c["puntuador"]["tipo"] for c in cases}
    assert [c["sheet_role"] for c in normalized] == [
        _OLD_SHEET_ROLES[c.get("rol_en_hoja")] for c in cases
    ]
    assert [c["scorer"]["kind"] for c in normalized] == [
        _OLD_SCORER_KINDS.get(c["puntuador"]["tipo"], c["puntuador"]["tipo"]) for c in cases
    ]
    # Un caso ya nuevo sale igual.
    new = {"provenance": "frozen", "media_type": "text", "sheet_role": "trap"}
    assert (
        legacy_names.normalize("affinity_case", legacy_names.normalize("benchmark_corpus", new))
        == new
    )
