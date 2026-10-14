"""Tests del banco y del experimento de adopción (SDD subagente-lector-local, spec v2, tarea 5).

Solo las partes puras: reglas del veredicto, plan de corridas, hecho plantado y lectura del
transcript. Lo que lanza `claude -p` se prueba corriendo (tareas 4 y 5), no aquí.
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bench = _load("_claude_bench")
exp = _load("adoption_experiment")


# --- Veredicto ------------------------------------------------------------------------------------


def _rows(correct_ones: dict[tuple[str, str], int], r: int = 3, cost: dict | None = None):
    cost = cost or {}
    rows = []
    for (task, offer), n in correct_ones.items():
        for i in range(r):
            rows.append(
                {
                    "task": task,
                    "offer": offer,
                    "valid": True,
                    "correct": i < n,
                    "cost_usd": cost.get(offer, 0.4),
                }
            )
    return rows


def _table(v0: list[int], v1: list[int], v2: list[int]) -> dict:
    return {
        (f"t{i}", offer): n
        for offer, values in (("v0", v0), ("v1", v1), ("v2", v2))
        for i, n in enumerate(values)
    }


def test_the_one_beating_v0_in_more_tasks_wins():
    table = _table([0] * 8, [1, 1, 1, 0, 0, 0, 0, 0], [2, 2, 2, 2, 0, 0, 0, 0])
    assert exp.verdict(_rows(table))["chosen"] == "v2"


def test_without_three_tasks_nobody_wins():
    # Control: con 2 de 8 no llega al mínimo, aunque supere a V0 por mucho.
    table = _table([0] * 8, [3, 3, 0, 0, 0, 0, 0, 0], [0] * 8)
    assert exp.verdict(_rows(table))["chosen"] is None


def test_task_tie_is_decided_by_cost():
    table = _table([0] * 8, [1, 1, 1, 0, 0, 0, 0, 0], [1, 1, 1, 0, 0, 0, 0, 0])
    rows = _rows(table, cost={"v0": 0.4, "v1": 0.5, "v2": 0.3})
    assert exp.verdict(rows)["chosen"] == "v2"


def test_task_and_cost_tie_the_simplest_wins():
    table = _table([0] * 8, [1, 1, 1, 0, 0, 0, 0, 0], [1, 1, 1, 0, 0, 0, 0, 0])
    assert exp.verdict(_rows(table))["chosen"] == "v1"


def test_matching_v0_is_not_beating_it():
    table = _table([2] * 8, [2] * 8, [2] * 8)
    result = exp.verdict(_rows(table))
    assert result["chosen"] is None
    assert result["beats_v0_in"] == {"v1": [], "v2": []}


def test_invalid_runs_do_not_count():
    table = _table([0] * 8, [1, 1, 1, 0, 0, 0, 0, 0], [0] * 8)
    rows = _rows(table)
    for f in rows:
        if f["offer"] == "v1":
            f["valid"] = False
    assert exp.verdict(rows)["chosen"] is None


# --- Plan de corridas y hecho plantado --------------------------------------------------------


def test_the_plan_covers_everything_once_and_is_reproducible():
    plan = exp.run_plan(["a", "b"], 3, seed=7)
    assert len(plan) == len(set(plan)) == 2 * 3 * 3
    assert plan == exp.run_plan(["a", "b"], 3, seed=7)
    assert plan != exp.run_plan(["a", "b"], 3, seed=8)  # intercalado de verdad


@pytest.mark.parametrize("style", ["md", "log"])
def test_the_planted_fact_appears_once_and_near_the_middle(style):
    base = "".join(f"linea {i}\n" for i in range(400))
    text, connector, value = exp.plant(base, style, random.Random(1))
    assert text.count(value) == 1 and connector in text
    position = text.index(value) / len(text)
    assert 0.3 < position < 0.7


def test_the_question_mentions_neither_delegating_nor_the_planted_fact():
    # Sin el dato ni su conector: si la pregunta los nombra, `Grep` la resuelve sin leer (tarea 4).
    for style in ("md", "log"):
        text = exp.question(Path("C:/x/informe.md"), style).lower()
        for word in ("deleg", "local_", "tool", "umbral", "reintent", *exp.CONNECTORS):
            assert word not in text, (style, word)


def test_the_pilot_question_names_neither_sections_nor_delegating():
    # Si nombrase las secciones, `Grep '^## '` sacaría los títulos sin leer ni delegar.
    text = exp.pilot_question(Path("C:/x/informe.md")).lower()
    for word in ("deleg", "local_", "tool", "secci", "título", "titulo", "##", "cifra"):
        assert word not in text, word


def test_coverage_counts_normalised_titles():
    doc = "# T\n## Por qué existe\nx\n## Opciones: `--agents`\ny\n### Sub\n## Arranque\n"
    headings = exp.section_titles(doc)
    assert headings == ["Por qué existe", "Opciones: `--agents`", "Arranque"]
    response = "- **Por qué existe**: ...\n- Opciones --agents: ...\n"
    assert exp.title_coverage(response, headings) == pytest.approx(2 / 3)
    assert exp.title_coverage(response + "Arranque", headings) == 1.0
    assert exp.title_coverage("", headings) == 0.0
    assert exp.title_coverage("algo", []) == 0.0


def test_the_pilot_tasks_exist_and_have_sections():
    tasks = {t["id"]: t for t in exp.load_tasks()}
    for tid in exp.PILOT_TASKS:
        text = (exp.ROOT / tasks[tid]["source"]["repo"]).read_text(encoding="utf-8")
        assert len(exp.section_titles(text)) >= 5, tid


# --- Lectura del transcript -------------------------------------------------------------------


def _usage(uid: str, name: str, entry: dict) -> dict:
    return {"message": {"content": [{"type": "tool_use", "id": uid, "name": name, "input": entry}]}}


def _res(uid: str, text: str, error: bool = False) -> dict:
    block = {"type": "tool_result", "tool_use_id": uid, "content": text, "is_error": error}
    return {"message": {"content": [block]}}


def _deferred(with_ours: bool = True) -> dict:
    names = ["CronCreate"] + ([bench.TOOL_PRINCIPAL] if with_ours else [])
    return {"attachment": {"type": "deferred_tools_delta", "addedNames": names}}


def test_delegating_with_path_does_not_put_in_the_content(tmp_path):
    f = tmp_path / "doc.md"
    events = [
        _deferred(),
        _usage("1", "ToolSearch", {"query": f"select:{bench.TOOL_PRINCIPAL}"}),
        _res("1", "ok"),
        _usage("2", bench.TOOL_PRINCIPAL, {"path": str(f)}),
        _res("2", "resumen"),
    ]
    seen = bench.analyze(events, f)
    assert seen["local_with_path"] == [bench.TOOL_PRINCIPAL]
    assert seen["toolsearch"] and not seen["content_in_context"]


def test_a_denied_read_does_not_count_as_read(tmp_path):
    f = tmp_path / "doc.md"
    events = [
        _deferred(),
        _usage("1", "Read", {"file_path": str(f)}),
        _res("1", "40 KB y es prosa", True),
    ]
    seen = bench.analyze(events, f)
    assert seen["blocked"] and not seen["read_full"]


@pytest.mark.parametrize(
    ("usage", "result", "key"),
    [
        (("Read", {"file_path": "{f}"}), "texto", "read_full"),
        (("Read", {"file_path": "{f}", "offset": 10, "limit": 50}), "trozo", "read_ranges"),
        (("Bash", {"command": "cat doc.md"}), "x" * 3000, "bash_dump"),
    ],
)
def test_the_three_ways_of_putting_in_the_content(tmp_path, usage, result, key):
    f = tmp_path / "doc.md"
    name, entry = usage
    entry = {k: (str(f) if v == "{f}" else v) for k, v in entry.items()}
    seen = bench.analyze([_deferred(), _usage("1", name, entry), _res("1", result)], f)
    assert seen[key]
    assert seen["content_in_context"]


def test_a_short_bash_naming_the_file_is_not_a_dump(tmp_path):
    f = tmp_path / "doc.md"
    events = [
        _deferred(),
        _usage("1", "Bash", {"command": "wc -c doc.md"}),
        _res("1", "40000 doc.md"),
    ]
    assert not bench.analyze(events, f)["content_in_context"]


def test_the_subagent_part_does_not_count_as_main_thread(tmp_path):
    f = tmp_path / "doc.md"
    read = {**_usage("1", "Read", {"file_path": str(f)}), "isSidechain": True}
    assert not bench.analyze([_deferred(), read, _res("1", "t")], f)["read_full"]


def test_without_the_deferred_list_the_format_is_unknown(tmp_path):
    with pytest.raises(bench.UnknownFormat):
        bench.analyze([_usage("1", "Read", {"file_path": "x"})], tmp_path / "x")


def test_the_run_is_only_valid_with_its_prompt_event():
    good = {"event": "UserPromptSubmit", "session_id": "s1", "bloqueo": "encendido"}
    assert bench.valid_run([good], "s1")
    assert not bench.valid_run([good], "s2")  # otra sesión
    assert not bench.valid_run([{**good, "bloqueo": "apagado_fichero"}], "s1")
    assert not bench.valid_run([{**good, "event": "PreToolUse"}], "s1")
    assert not bench.valid_run([], "s1")


def test_project_dir_follows_the_claude_code_convention():
    path = bench.project_dir(Path(r"C:\Users\ana\AppData\Local\Temp\banco-lector"))
    assert path.name == "C--Users-ana-AppData-Local-Temp-banco-lector"


def test_the_deferred_ones_accumulate_delta_by_delta(tmp_path):
    """Medido en el control instalado: el primer delta traía las nuestras y el último, otras 5."""
    f = tmp_path / "doc.md"
    first = {"attachment": {"type": "deferred_tools_delta", "addedNames": [bench.TOOL_PRINCIPAL]}}
    last = {"attachment": {"type": "deferred_tools_delta", "addedNames": ["CronList"]}}
    assert bench.analyze([first, last], f)["deferred_tools"]
    removes = {
        "attachment": {"type": "deferred_tools_delta", "removedNames": [bench.TOOL_PRINCIPAL]}
    }
    assert not bench.analyze([first, last, removes], f)["deferred_tools"]


# --- Etapa 2 del SDD resumen-por-secciones --------------------------------------------------------


def _row(task: str, correct: bool, in_context: bool) -> dict:
    return {
        "task": task,
        "offer": "v0",
        "valid": True,
        "correct": correct,
        "content_in_context": in_context,
    }


@pytest.mark.parametrize(
    ("correct_ones", "decision"),
    [
        (6, "se queda"),
        (9, "se queda"),
        (5, "no concluyente"),
        (4, "no concluyente"),
        (3, "se retira"),
    ],
)
def test_summary_report_decides_only_by_correct_ones(correct_ones, decision):
    rows = [
        _row(t, i * 3 + r < correct_ones, i * 3 + r >= correct_ones)
        for i, t in enumerate(("readme", "wiki-daemon", "wiki-instalacion"))
        for r in range(3)
    ]
    report = exp.summary_report(rows)
    assert report["correct_ones"] == correct_ones
    assert report["content_in_context"] == 9 - correct_ones
    assert report["decision"] == decision
    assert sum(t["runs"] for t in report["per_task"].values()) == 9


def test_summary_report_does_not_decide_with_another_number_of_runs():
    rows = [_row("readme", True, False)] * 8 + [{**_row("readme", True, False), "valid": False}]
    assert exp.summary_report(rows)["decision"].startswith("sin decisión")


def test_plan_with_a_single_variant():
    plan = exp.run_plan(["a", "b", "c"], 3, 7, ("v0",))
    assert len(plan) == 9 and {v for _t, v, _r in plan} == {"v0"}


def test_the_fixed_sources_replace_the_live_file(tmp_path):
    sources = tmp_path / "fuentes"
    sources.mkdir()
    (sources / "readme.md").write_text("COPIA FIJA", encoding="utf-8")
    manifest = {"ficheros": {"readme.md": {"origen": "README.md"}}}
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    task = {"id": "readme", "source": {"repo": "README.md"}}
    assert exp.source_text(task, tmp_path / "cache", sources) == "COPIA FIJA"
    assert exp.source_text(task, tmp_path / "cache") != "COPIA FIJA"


# --- Ventanas excluidas: fichero nuevo y viejo (decisión 7 de A10a-4/5) ---------------------------


def test_the_excluded_windows_are_read_from_either_file_and_written_in_the_new_one(tmp_path):
    """Lo que escribe el banco al cerrar una tanda: parte del fichero nuevo o, si no existe, del de
    antes (claves en español, como el congelado de `benchmarks/`), y escribe solo el nuevo."""
    new_name, old_name = exp.WINDOWS.name, "ventanas-excluidas.json"
    assert new_name == "excluded-windows.json"
    run = bench.Run("s2", "", 0.0, "2026-10-13T10:00:00+00:00", "2026-10-13T10:05:00+00:00")
    old = {
        "sesiones": [{"session_id": "s1", "inicio": "a", "fin": "b", "motivo": "prueba"}],
        "ventanas": [{"tanda": "t0", "inicio": "a", "fin": "b"}],
    }
    # Solo el viejo: se lee, se traduce y el resultado va al nuevo; el viejo queda intacto.
    (tmp_path / old_name).write_text(json.dumps(old), encoding="utf-8")
    bench.note_window(tmp_path / new_name, "t1", [run])
    data = json.loads((tmp_path / new_name).read_text(encoding="utf-8"))
    assert [s["session_id"] for s in data["sessions"]] == ["s1", "s2"]
    assert data["sessions"][0] == {"session_id": "s1", "start": "a", "end": "b", "reason": "prueba"}
    assert [w["batch"] for w in data["windows"]] == ["t0", "t1"]
    assert "sesiones" not in data and "ventanas" not in data
    assert json.loads((tmp_path / old_name).read_text(encoding="utf-8")) == old
    # Con el nuevo ya escrito, manda el nuevo: la tanda siguiente se suma a lo que hay en él.
    bench.note_window(tmp_path / new_name, "t2", [run])
    data = json.loads((tmp_path / new_name).read_text(encoding="utf-8"))
    assert [w["batch"] for w in data["windows"]] == ["t0", "t1", "t2"]
    assert [s["session_id"] for s in data["sessions"]] == ["s1", "s2"]
