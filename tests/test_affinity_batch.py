"""La tanda de afinidad (`scripts/dev/affinity_batch.py`): el plan, la reanudación y lo que no imprime.

No llama a ningún backend: el benchmark y el techo se sustituyen por corredores falsos que escriben
filas como las de verdad. Lo que se prueba es el guion: cuántas peticiones, en qué orden, qué se salta
al reanudar, que `--dry` no toca nada y que el entorno no sale nunca por la salida.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
CORPUS_REAL = ROOT / "benchmarks" / "afinidad-2026-10" / "cases.json"


def _load():
    spec = importlib.util.spec_from_file_location(
        "affinity_batch", ROOT / "scripts" / "dev" / "affinity_batch.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["affinity_batch"] = module
    spec.loader.exec_module(module)
    return module


batch = _load()

CEILING_DIFF = b"diff --git a/x b/x\n+uno\n"


def _case(id_, tool, role, kind="calidad", role_in_sheet=None, **extra):
    return {
        "id": id_,
        "tool": tool,
        "role": role,
        "kind": kind,
        "rol_en_hoja": role_in_sheet,
        "system": f"sistema de {tool}",
        **extra,
    }


def _synthetic_corpus(folder: Path) -> Path:
    """Dos mecánicas, un commit real, una trampa y el techo: 2 + 2 + 3 peticiones por modelo."""
    (folder / "fuentes").mkdir(parents=True)
    (folder / "fuentes" / "techo.diff").write_bytes(CEILING_DIFF)
    cases = [
        _case("m1", "local_classify", "mechanical"),
        _case("m2", "local_extract", "mechanical"),
        _case("c1", "local_commit_msg", "code", role_in_sheet="real"),
        _case("t1", "local_commit_msg", "code", role_in_sheet="trampa"),
        _case(
            batch.CEILING_CASE,
            "local_commit_msg",
            "code",
            kind="techo",
            source_file="techo.diff",
            source_sha256=hashlib.sha256(CEILING_DIFF).hexdigest(),
        ),
    ]
    path = folder / "cases.json"
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    return path


def _row(label, case, run=1, **extra):
    return {
        "label": label,
        "case": case,
        "run": run,
        "outcome": "ok",
        "descartada": False,
        **extra,
    }


def _write(path: Path, rows: list[dict]) -> None:
    """Añade filas, como el `--append` del benchmark real."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as target:
        target.write("".join(json.dumps(f) + "\n" for f in rows))


class Fake:
    """Corredores que apuntan lo que se les pide y escriben filas, sin llamar a nada."""

    def __init__(self) -> None:
        self.benchmark: list[tuple[str, list[str], Path]] = []
        self.ceiling: list[int] = []

    def env(self):
        def benchmark(model, ids, output, args, variant):
            self.benchmark.append((model, list(ids), output))
            _write(output, [_row(model, i, resources={"enabled": True, "pids": [1]}) for i in ids])
            return 0

        def ceiling(run, source, args):
            self.ceiling.append(run)
            return batch.ceiling_row(run, source, {"texto": "feat: x", "latency_ms": 7}, Path("."))

        return batch.Environment(
            footprints=lambda cases, args: {"m": {"t": {"prompt_sha256": "a"}}},
            benchmark=benchmark,
            ceiling=ceiling,
            variant=lambda model, args: {},
        )

    def real(self, work: Path) -> dict[str, list[str]]:
        """Lo que se pidió a los resultados de verdad (sin los calentamientos)."""
        return {m: ids for m, ids, output in self.benchmark if output.parent != work}

    def warmups(self, work: Path) -> list[tuple[str, list[str]]]:
        return [(m, ids) for m, ids, output in self.benchmark if output.parent == work]


def _argv(tmp_path: Path, cases: Path, *extra: str) -> list[str]:
    return [
        "--cases",
        str(cases),
        "--results",
        str(tmp_path / "resultados"),
        "--footprints",
        str(tmp_path / "huellas.json"),
        "--windows",
        str(tmp_path / "ventanas.json"),
        "--work-dir",
        str(tmp_path / "trabajo"),
        "--no-probe",
        *extra,
    ]


# --- El plan ------------------------------------------------------------------------------------


@pytest.mark.skipif(not CORPUS_REAL.exists(), reason="el corpus de afinidad no está construido")
def test_dry_with_real_corpus_gives_213_requests(tmp_path, capsys):
    rc = batch.main(["--dry", "--results", str(tmp_path / "resultados")])
    output = capsys.readouterr().out

    assert rc == 0
    assert "gemma3-4b: 33 peticiones" in output
    assert "qwen35-2b: 33 peticiones" in output
    assert "gemma4-26b-a4b: 72 peticiones" in output
    assert "qwen36-35b-a3b: 72 peticiones" in output
    assert "techo (gemma4-26b-a4b, camino de produccion): 3 peticiones" in output
    assert "total: 213 peticiones (213 pendientes)" in output


def test_dry_counts_by_model_and_writes_nothing(tmp_path, capsys):
    cases = _synthetic_corpus(tmp_path / "corpus")
    rc = batch.main(["--dry", *_argv(tmp_path, cases)])
    output = capsys.readouterr().out

    assert rc == 0
    # Mecánicas para los cuatro; commit (real + trampa) solo para los dos modelos de commit.
    assert "gemma3-4b: 2 peticiones" in output
    assert "qwen35-2b: 2 peticiones" in output
    assert "gemma4-26b-a4b: 4 peticiones" in output
    assert "qwen36-35b-a3b: 4 peticiones" in output
    assert "total: 15 peticiones" in output
    assert not (tmp_path / "huellas.json").exists()
    assert not (tmp_path / "ventanas.json").exists()
    assert not (tmp_path / "resultados").exists()
    assert not (tmp_path / "trabajo").exists()


def test_only_limits_plan_to_that_model(tmp_path, capsys):
    cases = _synthetic_corpus(tmp_path / "corpus")
    batch.main(["--dry", *_argv(tmp_path, cases), "--only", "qwen36-35b-a3b"])
    output = capsys.readouterr().out

    assert "qwen36-35b-a3b: 4 peticiones" in output
    assert "gemma3-4b" not in output
    assert "techo" not in output
    assert "total: 4 peticiones" in output


# --- La reanudación -----------------------------------------------------------------------------


def test_resume_counts_already_written(tmp_path, capsys):
    cases = _synthetic_corpus(tmp_path / "corpus")
    results = tmp_path / "resultados"
    _write(results / "gemma3-4b.jsonl", [_row("gemma3-4b", "m1")])
    _write(
        results / "techo-gemma4-26b-a4b.jsonl",
        [_row("gemma4-26b-a4b", batch.CEILING_CASE, run=1)],
    )

    batch.main(["--dry", *_argv(tmp_path, cases)])
    output = capsys.readouterr().out

    assert "gemma3-4b: 2 peticiones (1 pendientes, 1 hechas)" in output
    assert (
        "techo (gemma4-26b-a4b, camino de produccion): 3 peticiones (2 pendientes, 1 hechas)"
        in output
    )
    assert "total: 15 peticiones (13 pendientes)" in output


def test_cancelled_or_cut_run_is_repeated(tmp_path):
    results = tmp_path / "resultados"
    results.mkdir()
    (results / "m.jsonl").write_text(
        json.dumps(_row("m", "a"))
        + "\n"
        + json.dumps(_row("m", "b", descartada=True, outcome="error"))
        + "\n"
        + '{"label": "m", "case": "c", "run"',  # línea cortada por un apagón
        encoding="utf-8",
    )

    assert batch.done_runs(results) == {("m", "a", 1)}


def test_run_cancelled_only_for_lack_of_samples_not_repeated(tmp_path):
    results = tmp_path / "resultados"
    _write(
        results / "m.jsonl",
        [
            _row("m", "a", descartada=True, descartada_motivo="zero_vram_samples"),
            _row("m", "b", descartada=True, descartada_motivo="zero_ram_samples"),
            _row("m", "c", descartada=True, descartada_motivo="multiple_processes"),
            _row("m", "d", descartada=True, descartada_motivo="process_changed"),
        ],
    )

    assert batch.done_runs(results) == {("m", "a", 1), ("m", "b", 1)}


def test_last_attempt_wins_and_errors_retried_on_request(tmp_path):
    results = tmp_path / "resultados"
    _write(
        results / "m.jsonl",
        [_row("m", "a", outcome="error"), _row("m", "b", outcome="error")]
        + [_row("m", "b", outcome="ok")],
    )

    assert batch.done_runs(results) == {("m", "a", 1), ("m", "b", 1)}
    assert batch.done_runs(results, retry_errors=True) == {("m", "b", 1)}


def test_run_skips_already_written_and_continues(tmp_path, capsys):
    cases = _synthetic_corpus(tmp_path / "corpus")
    results = tmp_path / "resultados"
    _write(results / "gemma3-4b.jsonl", [_row("gemma3-4b", "m1")])
    _write(
        results / "techo-gemma4-26b-a4b.jsonl",
        [_row("gemma4-26b-a4b", batch.CEILING_CASE, run=1)],
    )
    fake = Fake()

    rc = batch.main(_argv(tmp_path, cases), fake.env())

    work = tmp_path / "trabajo"
    assert rc == 0
    real = fake.real(work)
    # m1 ya estaba escrito para gemma3-4b: solo se pide m2. Los demás modelos, todo.
    assert real["gemma3-4b"] == ["m2"]
    assert real["qwen35-2b"] == ["m1", "m2"]
    assert real["gemma4-26b-a4b"] == ["m1", "m2", "c1", "t1"]
    assert real["qwen36-35b-a3b"] == ["m1", "m2", "c1", "t1"]
    # El techo ya tenía la corrida 1: solo la 2 y la 3.
    assert fake.ceiling == [2, 3]
    # Cada modelo con trabajo pendiente se calienta antes, y el calentamiento no va a resultados.
    assert [m for m, _ in fake.warmups(work)] == [
        "gemma3-4b",
        "qwen35-2b",
        "gemma4-26b-a4b",
        "qwen36-35b-a3b",
        "gemma4-26b-a4b",
    ]
    # Una segunda vuelta no repite nada.
    fake2 = Fake()
    assert batch.main(_argv(tmp_path, cases), fake2.env()) == 0
    assert fake2.benchmark == []
    assert fake2.ceiling == []
    capsys.readouterr()


def test_ceiling_writes_rows_in_t4_format(tmp_path):
    cases = _synthetic_corpus(tmp_path / "corpus")
    fake = Fake()
    batch.main(_argv(tmp_path, cases, "--only", "techo"), fake.env())

    rows = [
        json.loads(line)
        for line in (tmp_path / "resultados" / "techo-gemma4-26b-a4b.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [f["run"] for f in rows] == [1, 2, 3]
    assert {f["label"] for f in rows} == {"gemma4-26b-a4b"}
    assert {f["case"] for f in rows} == {batch.CEILING_CASE}
    assert all(f["outcome"] == "ok" and f["response"] == "feat: x" for f in rows)


def test_ceiling_row_lacks_user_folder(tmp_path, monkeypatch):
    home = tmp_path / "Perfil-De-Alguien"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    log_dir = home / "AppData" / "Local" / "Temp" / "tanda-afinidad" / "techo-usage"
    log_dir.mkdir(parents=True)

    row = batch.ceiling_row(1, Path(__file__), {"texto": "feat: x", "latency_ms": 3}, log_dir)

    assert "Perfil-De-Alguien" not in json.dumps(row)
    assert row["entorno_fijado"]["LOCAL_DELEGATE_LOG_DIR"] == (
        "~/AppData/Local/Temp/tanda-afinidad/techo-usage"
    )


def test_ceiling_returning_error_is_not_ok():
    row = batch.ceiling_row(
        1, Path(__file__), {"texto": "[local-delegate error] se cayó", "latency_ms": 3}, Path(".")
    )
    assert row["outcome"] == "error"
    assert row["ok"] is False


# --- Huellas, ventana y lo que no se imprime -----------------------------------------------------


def test_different_footprints_stop_batch_without_overwriting_previous(tmp_path, capsys):
    cases = _synthetic_corpus(tmp_path / "corpus")
    (tmp_path / "huellas.json").write_text(json.dumps({"viejas": 1}), encoding="utf-8")
    fake = Fake()

    rc = batch.main(_argv(tmp_path, cases), fake.env())

    assert rc == 4
    assert fake.benchmark == []
    assert json.loads((tmp_path / "huellas.json").read_text(encoding="utf-8")) == {"viejas": 1}
    assert "--redo-footprints" in capsys.readouterr().out


def test_window_recorded_at_start_and_end(tmp_path, capsys):
    cases = _synthetic_corpus(tmp_path / "corpus")
    batch.main(_argv(tmp_path, cases), Fake().env())
    output = capsys.readouterr().out

    assert "VENTANA inicio_utc=" in output
    assert "VENTANA fin_utc=" in output
    windows = json.loads((tmp_path / "ventanas.json").read_text(encoding="utf-8"))
    assert len(windows) == 1
    assert windows[0]["inicio_utc"] and windows[0]["fin_utc"]


def test_env_not_leaked_in_output_or_argv(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCAL_DELEGATE_API_KEY", "clave-de-prueba-que-no-debe-salir")
    cases = _synthetic_corpus(tmp_path / "corpus")
    fake = Fake()
    batch.main(_argv(tmp_path, cases), fake.env())
    batch.main(["--dry", *_argv(tmp_path, cases)])
    output = capsys.readouterr()

    assert "clave-de-prueba" not in output.out + output.err

    args = batch.parse_args(_argv(tmp_path, cases))
    argv = batch.benchmark_argv("gemma3-4b", ["m1"], tmp_path / "o.jsonl", args, {})
    assert "--api-key" not in argv
    assert "clave-de-prueba" not in " ".join(argv)


def test_warmup_unseen_by_probe_stops_batch(tmp_path):
    output = tmp_path / "calentamiento.jsonl"
    _write(output, [_row("m", "a", resources={"enabled": True, "pids": []})])
    assert "no vio ningun proceso" in batch.check_warmup(output, with_probe=True)
    assert batch.check_warmup(output, with_probe=False) is None

    output.unlink()
    _write(output, [_row("m", "a", resources={"enabled": True, "pids": [7]})])
    assert batch.check_warmup(output, with_probe=True) is None


def test_benchmark_argv_carries_production_flags(tmp_path):
    args = batch.parse_args(["--seed", "9", "--endpoint", "http://x/v1"])
    argv = batch.benchmark_argv(
        "gemma4-26b-a4b",
        ["c1", "t1"],
        tmp_path / "o.jsonl",
        args,
        {"ctx_size": 38400, "n_cpu_moe": 12, "load_mode": "mmap"},
    )

    def value(flag: str) -> str:
        return argv[argv.index(flag) + 1]

    assert value("--model") == value("--label") == "gemma4-26b-a4b"
    assert value("--cases") == str(args.cases)
    assert value("--runs") == "1"
    assert value("--seed") == "9"
    assert value("--endpoint") == "http://x/v1"
    assert value("--probe-process") == "llama-server.exe"
    assert value("--context-size") == "38400"
    assert value("--n-cpu-moe") == "12"
    assert value("--load-mode") == "mmap"
    assert "--save-responses" in argv
    assert argv.count("--case") == 2
