"""La tanda de afinidad (`scripts/dev/tanda_afinidad.py`): el plan, la reanudación y lo que no imprime.

No llama a ningún backend: el benchmark y el techo se sustituyen por corredores falsos que escriben
filas como las de verdad. Lo que se prueba es el guion: cuántas peticiones, en qué orden, qué se salta
al reanudar, que `--seco` no toca nada y que el entorno no sale nunca por la salida.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
CORPUS_REAL = RAIZ / "benchmarks" / "afinidad-2026-10" / "cases.json"


def _cargar():
    spec = importlib.util.spec_from_file_location(
        "tanda_afinidad", RAIZ / "scripts" / "dev" / "tanda_afinidad.py"
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["tanda_afinidad"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


tanda = _cargar()

DIFF_TECHO = b"diff --git a/x b/x\n+uno\n"


def _caso(id_, tool, role, kind="calidad", rol_en_hoja=None, **extra):
    return {
        "id": id_,
        "tool": tool,
        "role": role,
        "kind": kind,
        "rol_en_hoja": rol_en_hoja,
        "system": f"sistema de {tool}",
        **extra,
    }


def _corpus_sintetico(carpeta: Path) -> Path:
    """Dos mecánicas, un commit real, una trampa y el techo: 2 + 2 + 3 peticiones por modelo."""
    (carpeta / "fuentes").mkdir(parents=True)
    (carpeta / "fuentes" / "techo.diff").write_bytes(DIFF_TECHO)
    casos = [
        _caso("m1", "local_classify", "mechanical"),
        _caso("m2", "local_extract", "mechanical"),
        _caso("c1", "local_commit_msg", "code", rol_en_hoja="real"),
        _caso("t1", "local_commit_msg", "code", rol_en_hoja="trampa"),
        _caso(
            tanda.CASO_DEL_TECHO,
            "local_commit_msg",
            "code",
            kind="techo",
            source_file="techo.diff",
            source_sha256=hashlib.sha256(DIFF_TECHO).hexdigest(),
        ),
    ]
    ruta = carpeta / "cases.json"
    ruta.write_text(json.dumps({"cases": casos}), encoding="utf-8")
    return ruta


def _fila(label, caso, run=1, **extra):
    return {
        "label": label,
        "case": caso,
        "run": run,
        "outcome": "ok",
        "descartada": False,
        **extra,
    }


def _escribir(ruta: Path, filas: list[dict]) -> None:
    """Añade filas, como el `--append` del benchmark real."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", encoding="utf-8") as destino:
        destino.write("".join(json.dumps(f) + "\n" for f in filas))


class Falso:
    """Corredores que apuntan lo que se les pide y escriben filas, sin llamar a nada."""

    def __init__(self) -> None:
        self.benchmark: list[tuple[str, list[str], Path]] = []
        self.techo: list[int] = []

    def entorno(self):
        def benchmark(modelo, ids, salida, args, variante):
            self.benchmark.append((modelo, list(ids), salida))
            _escribir(
                salida, [_fila(modelo, i, resources={"enabled": True, "pids": [1]}) for i in ids]
            )
            return 0

        def techo(run, fuente, args):
            self.techo.append(run)
            return tanda.fila_del_techo(
                run, fuente, {"texto": "feat: x", "latency_ms": 7}, Path(".")
            )

        return tanda.Entorno(
            huellas=lambda casos, args: {"m": {"t": {"prompt_sha256": "a"}}},
            benchmark=benchmark,
            techo=techo,
            variante=lambda modelo, args: {},
        )

    def reales(self, trabajo: Path) -> dict[str, list[str]]:
        """Lo que se pidió a los resultados de verdad (sin los calentamientos)."""
        return {m: ids for m, ids, salida in self.benchmark if salida.parent != trabajo}

    def calentamientos(self, trabajo: Path) -> list[tuple[str, list[str]]]:
        return [(m, ids) for m, ids, salida in self.benchmark if salida.parent == trabajo]


def _argv(tmp_path: Path, cases: Path, *extra: str) -> list[str]:
    return [
        "--cases",
        str(cases),
        "--resultados",
        str(tmp_path / "resultados"),
        "--huellas",
        str(tmp_path / "huellas.json"),
        "--ventanas",
        str(tmp_path / "ventanas.json"),
        "--trabajo",
        str(tmp_path / "trabajo"),
        "--sin-sonda",
        *extra,
    ]


# --- El plan ------------------------------------------------------------------------------------


@pytest.mark.skipif(not CORPUS_REAL.exists(), reason="el corpus de afinidad no está construido")
def test_seco_con_el_corpus_real_da_213_peticiones(tmp_path, capsys):
    rc = tanda.main(["--seco", "--resultados", str(tmp_path / "resultados")])
    salida = capsys.readouterr().out

    assert rc == 0
    assert "gemma3-4b: 33 peticiones" in salida
    assert "qwen35-2b: 33 peticiones" in salida
    assert "gemma4-26b-a4b: 72 peticiones" in salida
    assert "qwen36-35b-a3b: 72 peticiones" in salida
    assert "techo (gemma4-26b-a4b, camino de produccion): 3 peticiones" in salida
    assert "total: 213 peticiones (213 pendientes)" in salida


def test_seco_cuenta_por_modelo_y_no_escribe_nada(tmp_path, capsys):
    cases = _corpus_sintetico(tmp_path / "corpus")
    rc = tanda.main(["--seco", *_argv(tmp_path, cases)])
    salida = capsys.readouterr().out

    assert rc == 0
    # Mecánicas para los cuatro; commit (real + trampa) solo para los dos modelos de commit.
    assert "gemma3-4b: 2 peticiones" in salida
    assert "qwen35-2b: 2 peticiones" in salida
    assert "gemma4-26b-a4b: 4 peticiones" in salida
    assert "qwen36-35b-a3b: 4 peticiones" in salida
    assert "total: 15 peticiones" in salida
    assert not (tmp_path / "huellas.json").exists()
    assert not (tmp_path / "ventanas.json").exists()
    assert not (tmp_path / "resultados").exists()
    assert not (tmp_path / "trabajo").exists()


def test_solo_limita_el_plan_a_ese_modelo(tmp_path, capsys):
    cases = _corpus_sintetico(tmp_path / "corpus")
    tanda.main(["--seco", *_argv(tmp_path, cases), "--solo", "qwen36-35b-a3b"])
    salida = capsys.readouterr().out

    assert "qwen36-35b-a3b: 4 peticiones" in salida
    assert "gemma3-4b" not in salida
    assert "techo" not in salida
    assert "total: 4 peticiones" in salida


# --- La reanudación -----------------------------------------------------------------------------


def test_la_reanudacion_cuenta_lo_ya_escrito(tmp_path, capsys):
    cases = _corpus_sintetico(tmp_path / "corpus")
    resultados = tmp_path / "resultados"
    _escribir(resultados / "gemma3-4b.jsonl", [_fila("gemma3-4b", "m1")])
    _escribir(
        resultados / "techo-gemma4-26b-a4b.jsonl",
        [_fila("gemma4-26b-a4b", tanda.CASO_DEL_TECHO, run=1)],
    )

    tanda.main(["--seco", *_argv(tmp_path, cases)])
    salida = capsys.readouterr().out

    assert "gemma3-4b: 2 peticiones (1 pendientes, 1 hechas)" in salida
    assert (
        "techo (gemma4-26b-a4b, camino de produccion): 3 peticiones (2 pendientes, 1 hechas)"
        in salida
    )
    assert "total: 15 peticiones (13 pendientes)" in salida


def test_una_corrida_anulada_o_cortada_se_repite(tmp_path):
    resultados = tmp_path / "resultados"
    resultados.mkdir()
    (resultados / "m.jsonl").write_text(
        json.dumps(_fila("m", "a"))
        + "\n"
        + json.dumps(_fila("m", "b", descartada=True, outcome="error"))
        + "\n"
        + '{"label": "m", "case": "c", "run"',  # línea cortada por un apagón
        encoding="utf-8",
    )

    assert tanda.corridas_hechas(resultados) == {("m", "a", 1)}


def test_una_corrida_anulada_solo_por_falta_de_muestras_no_se_repite(tmp_path):
    resultados = tmp_path / "resultados"
    _escribir(
        resultados / "m.jsonl",
        [
            _fila("m", "a", descartada=True, descartada_motivo="zero_vram_samples"),
            _fila("m", "b", descartada=True, descartada_motivo="zero_ram_samples"),
            _fila("m", "c", descartada=True, descartada_motivo="multiple_processes"),
            _fila("m", "d", descartada=True, descartada_motivo="process_changed"),
        ],
    )

    assert tanda.corridas_hechas(resultados) == {("m", "a", 1), ("m", "b", 1)}


def test_el_ultimo_intento_manda_y_los_errores_se_reintentan_si_se_pide(tmp_path):
    resultados = tmp_path / "resultados"
    _escribir(
        resultados / "m.jsonl",
        [_fila("m", "a", outcome="error"), _fila("m", "b", outcome="error")]
        + [_fila("m", "b", outcome="ok")],
    )

    assert tanda.corridas_hechas(resultados) == {("m", "a", 1), ("m", "b", 1)}
    assert tanda.corridas_hechas(resultados, reintentar_errores=True) == {("m", "b", 1)}


def test_ejecutar_salta_lo_ya_escrito_y_sigue_con_lo_que_falta(tmp_path, capsys):
    cases = _corpus_sintetico(tmp_path / "corpus")
    resultados = tmp_path / "resultados"
    _escribir(resultados / "gemma3-4b.jsonl", [_fila("gemma3-4b", "m1")])
    _escribir(
        resultados / "techo-gemma4-26b-a4b.jsonl",
        [_fila("gemma4-26b-a4b", tanda.CASO_DEL_TECHO, run=1)],
    )
    falso = Falso()

    rc = tanda.main(_argv(tmp_path, cases), falso.entorno())

    trabajo = tmp_path / "trabajo"
    assert rc == 0
    reales = falso.reales(trabajo)
    # m1 ya estaba escrito para gemma3-4b: solo se pide m2. Los demás modelos, todo.
    assert reales["gemma3-4b"] == ["m2"]
    assert reales["qwen35-2b"] == ["m1", "m2"]
    assert reales["gemma4-26b-a4b"] == ["m1", "m2", "c1", "t1"]
    assert reales["qwen36-35b-a3b"] == ["m1", "m2", "c1", "t1"]
    # El techo ya tenía la corrida 1: solo la 2 y la 3.
    assert falso.techo == [2, 3]
    # Cada modelo con trabajo pendiente se calienta antes, y el calentamiento no va a resultados.
    assert [m for m, _ in falso.calentamientos(trabajo)] == [
        "gemma3-4b",
        "qwen35-2b",
        "gemma4-26b-a4b",
        "qwen36-35b-a3b",
        "gemma4-26b-a4b",
    ]
    # Una segunda vuelta no repite nada.
    falso2 = Falso()
    assert tanda.main(_argv(tmp_path, cases), falso2.entorno()) == 0
    assert falso2.benchmark == []
    assert falso2.techo == []
    capsys.readouterr()


def test_el_techo_escribe_filas_con_el_formato_de_t4(tmp_path):
    cases = _corpus_sintetico(tmp_path / "corpus")
    falso = Falso()
    tanda.main(_argv(tmp_path, cases, "--solo", "techo"), falso.entorno())

    filas = [
        json.loads(linea)
        for linea in (tmp_path / "resultados" / "techo-gemma4-26b-a4b.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [f["run"] for f in filas] == [1, 2, 3]
    assert {f["label"] for f in filas} == {"gemma4-26b-a4b"}
    assert {f["case"] for f in filas} == {tanda.CASO_DEL_TECHO}
    assert all(f["outcome"] == "ok" and f["response"] == "feat: x" for f in filas)


def test_la_fila_del_techo_no_lleva_la_carpeta_del_usuario(tmp_path, monkeypatch):
    casa = tmp_path / "Perfil-De-Alguien"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: casa))
    carpeta_log = casa / "AppData" / "Local" / "Temp" / "tanda-afinidad" / "techo-usage"
    carpeta_log.mkdir(parents=True)

    fila = tanda.fila_del_techo(
        1, Path(__file__), {"texto": "feat: x", "latency_ms": 3}, carpeta_log
    )

    assert "Perfil-De-Alguien" not in json.dumps(fila)
    assert fila["entorno_fijado"]["LOCAL_DELEGATE_LOG_DIR"] == (
        "~/AppData/Local/Temp/tanda-afinidad/techo-usage"
    )


def test_un_techo_que_devuelve_error_no_es_ok():
    fila = tanda.fila_del_techo(
        1, Path(__file__), {"texto": "[local-delegate error] se cayó", "latency_ms": 3}, Path(".")
    )
    assert fila["outcome"] == "error"
    assert fila["ok"] is False


# --- Huellas, ventana y lo que no se imprime -----------------------------------------------------


def test_huellas_distintas_paran_la_tanda_sin_pisar_las_anteriores(tmp_path, capsys):
    cases = _corpus_sintetico(tmp_path / "corpus")
    (tmp_path / "huellas.json").write_text(json.dumps({"viejas": 1}), encoding="utf-8")
    falso = Falso()

    rc = tanda.main(_argv(tmp_path, cases), falso.entorno())

    assert rc == 4
    assert falso.benchmark == []
    assert json.loads((tmp_path / "huellas.json").read_text(encoding="utf-8")) == {"viejas": 1}
    assert "--rehacer-huellas" in capsys.readouterr().out


def test_la_ventana_se_apunta_al_empezar_y_al_terminar(tmp_path, capsys):
    cases = _corpus_sintetico(tmp_path / "corpus")
    tanda.main(_argv(tmp_path, cases), Falso().entorno())
    salida = capsys.readouterr().out

    assert "VENTANA inicio_utc=" in salida
    assert "VENTANA fin_utc=" in salida
    ventanas = json.loads((tmp_path / "ventanas.json").read_text(encoding="utf-8"))
    assert len(ventanas) == 1
    assert ventanas[0]["inicio_utc"] and ventanas[0]["fin_utc"]


def test_el_entorno_no_sale_por_la_salida_ni_por_argv(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCAL_DELEGATE_API_KEY", "clave-de-prueba-que-no-debe-salir")
    cases = _corpus_sintetico(tmp_path / "corpus")
    falso = Falso()
    tanda.main(_argv(tmp_path, cases), falso.entorno())
    tanda.main(["--seco", *_argv(tmp_path, cases)])
    salida = capsys.readouterr()

    assert "clave-de-prueba" not in salida.out + salida.err

    args = tanda.parse_args(_argv(tmp_path, cases))
    argv = tanda.argv_del_benchmark("gemma3-4b", ["m1"], tmp_path / "o.jsonl", args, {})
    assert "--api-key" not in argv
    assert "clave-de-prueba" not in " ".join(argv)


def test_el_calentamiento_que_la_sonda_no_ve_para_la_tanda(tmp_path):
    salida = tmp_path / "calentamiento.jsonl"
    _escribir(salida, [_fila("m", "a", resources={"enabled": True, "pids": []})])
    assert "no vio ningun proceso" in tanda.comprobar_calentamiento(salida, con_sonda=True)
    assert tanda.comprobar_calentamiento(salida, con_sonda=False) is None

    salida.unlink()
    _escribir(salida, [_fila("m", "a", resources={"enabled": True, "pids": [7]})])
    assert tanda.comprobar_calentamiento(salida, con_sonda=True) is None


def test_el_argv_del_benchmark_lleva_los_flags_de_produccion(tmp_path):
    args = tanda.parse_args(["--semilla", "9", "--endpoint", "http://x/v1"])
    argv = tanda.argv_del_benchmark(
        "gemma4-26b-a4b",
        ["c1", "t1"],
        tmp_path / "o.jsonl",
        args,
        {"ctx_size": 38400, "n_cpu_moe": 12, "load_mode": "mmap"},
    )

    def valor(flag: str) -> str:
        return argv[argv.index(flag) + 1]

    assert valor("--model") == valor("--label") == "gemma4-26b-a4b"
    assert valor("--cases") == str(args.cases)
    assert valor("--runs") == "1"
    assert valor("--seed") == "9"
    assert valor("--endpoint") == "http://x/v1"
    assert valor("--probe-process") == "llama-server.exe"
    assert valor("--context-size") == "38400"
    assert valor("--n-cpu-moe") == "12"
    assert valor("--load-mode") == "mmap"
    assert "--save-responses" in argv
    assert argv.count("--case") == 2
