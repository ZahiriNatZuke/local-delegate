"""Sonda de recursos por proceso del runner (tarea 13 del SDD delegacion-precisa-y-fiable).

La logica —parseo de typeperf, PID que desaparece, cambio de PID, cero muestras— se prueba con
dobles en los tres sistemas del CI. Lo que toca Windows de verdad (Toolhelp32, psapi) va marcado y
con control positivo: dos procesos de tamano distinto tienen que dar numeros distintos.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import httpx2
import pytest

from local_delegate import benchmark

RAIZ = Path(__file__).parents[1]
MIB = 1024 * 1024
NVIDIA = "0x00000000_0x0000F722"
IGPU = "0x00000000_0x00014FF6"

solo_windows = pytest.mark.skipif(
    sys.platform != "win32", reason="Toolhelp32 y psapi solo existen en Windows"
)

# Cabecera con los nombres REALES de la tarea 12 (dwm, pid 1556, y un proceso de prueba, pid
# 40160). Los valores del segundo adaptador se cambiaron de 0 a cifras distintas a proposito: con
# los ceros reales, un parseo que no filtrase por LUID daria el mismo total y el test no vería nada.
HEADER = (
    '"(PDH-CSV 4.0)",'
    f'"\\\\DESKTOP\\GPU Process Memory(pid_1556_luid_{NVIDIA}_phys_0)\\Dedicated Usage",'
    f'"\\\\DESKTOP\\GPU Process Memory(pid_1556_luid_{IGPU}_phys_0)\\Dedicated Usage",'
    f'"\\\\DESKTOP\\GPU Process Memory(pid_1556_luid_{NVIDIA}_phys_0)\\Shared Usage",'
    f'"\\\\DESKTOP\\GPU Process Memory(pid_1556_luid_{IGPU}_phys_0)\\Shared Usage",'
    f'"\\\\DESKTOP\\GPU Process Memory(pid_1556_luid_{NVIDIA}_phys_0)\\Total Committed",'
    f'"\\\\DESKTOP\\GPU Process Memory(pid_40160_luid_{NVIDIA}_phys_0)\\Dedicated Usage"'
)
ROW = (
    '"09/13/2026 21:38:45.488","9433419776.000000","202113024.000000","14647296.000000",'
    '"757760.000000","631513088.000000","11403264.000000"'
)


def test_parseo_saca_los_dos_contadores_de_la_instancia_correcta_habiendo_varias():
    columns = benchmark.parse_typeperf_header(HEADER, 1556, NVIDIA)
    assert columns == {1: "dedicated", 3: "shared"}
    reading = benchmark.parse_typeperf_sample(ROW, columns)
    assert reading == benchmark.VramReading(9433419776, 14647296)


def test_parseo_respeta_el_pid_y_el_luid_pedidos():
    otro_pid = benchmark.parse_typeperf_header(HEADER, 40160, NVIDIA)
    assert benchmark.parse_typeperf_sample(ROW, otro_pid) == benchmark.VramReading(11403264, None)
    igpu = benchmark.parse_typeperf_header(HEADER, 1556, IGPU)
    assert benchmark.parse_typeperf_sample(ROW, igpu) == benchmark.VramReading(202113024, 757760)


def test_luid_equivocado_da_cabecera_vacia_y_cero_muestras_no_la_vram_de_otro():
    columns = benchmark.parse_typeperf_header(HEADER, 1556, "0x00000000_0x0000DEAD")
    assert columns == {}
    assert benchmark.parse_typeperf_sample(ROW, columns) is None


def test_menos_uno_es_proceso_muerto_y_los_mensajes_de_consola_se_ignoran():
    columns = benchmark.parse_typeperf_header(HEADER, 1556, NVIDIA)
    gone = '"09/13/2026 21:40:13.735","-1","-1","-1","-1","-1","-1"'
    assert benchmark.parse_typeperf_sample(gone, columns) == benchmark.VramReading(
        None, None, process_gone=True
    )
    assert benchmark.parse_typeperf_header("Se est� saliendo, espere...", 1, NVIDIA) is None
    assert benchmark.parse_typeperf_sample("Los datos no son v�lidos.", columns) is None


# Salida real de la tarea 12: nvidia-smi decia 942 MiB usados.
ADAPTERS = (
    '"(PDH-CSV 4.0)",'
    f'"\\\\DESKTOP\\GPU Adapter Memory(luid_{NVIDIA}_phys_0)\\Dedicated Usage",'
    f'"\\\\DESKTOP\\GPU Adapter Memory(luid_{IGPU}_phys_0)\\Dedicated Usage",'
    '"\\\\DESKTOP\\GPU Adapter Memory(luid_0x00000000_0x0001506D_phys_0)\\Dedicated Usage"\n'
    '"09/13/2026 21:37:04.706","997896192.000000","0.000000","202113024.000000"\n'
    "Se est� saliendo, espere...\n"
)


def test_luid_de_la_nvidia_se_empareja_con_nvidia_smi():
    values = benchmark.parse_adapter_dedicated(ADAPTERS)
    assert values[NVIDIA] == 997896192
    assert benchmark.choose_gpu_luid(values, 942.0) == NVIDIA


def test_luid_no_se_adivina_si_no_hay_exactamente_un_candidato():
    values = benchmark.parse_adapter_dedicated(ADAPTERS)
    assert benchmark.choose_gpu_luid(values, 5000.0) is None
    assert benchmark.choose_gpu_luid({"a": 900 * MIB, "b": 950 * MIB}, 925.0) is None


class _FakePopen:
    def __init__(self, lines):
        self.stdout = iter(lines)
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def _stream(lines, pid=1556):
    created = {}

    def popen(command, **_kwargs):
        created["command"] = command
        created["process"] = _FakePopen(lines)
        return created["process"]

    stream = benchmark.TypeperfStream(pid, NVIDIA, popen=popen, clock=lambda: 100.0)
    stream._thread.join(timeout=2)
    return stream, created


def test_flujo_guarda_la_ultima_muestra_de_la_instancia_pedida():
    stream, created = _stream(["Nota previa", HEADER, ROW])
    assert r"\GPU Process Memory(pid_1556_*)\Dedicated Usage" in created["command"]
    assert stream.latest(max_age=2.5) == benchmark.VramReading(9433419776, 14647296)
    assert stream.process_gone is False
    stream.close()
    assert created["process"].terminated


def test_pid_que_desaparece_da_sin_muestra_y_no_una_excepcion():
    gone = '"09/13/2026 21:40:13.735","-1","-1","-1","-1","-1","-1"'
    stream, _ = _stream([HEADER, ROW, gone, gone, "Error:", "Los datos no son v�lidos."])
    assert stream.process_gone is True
    assert stream.latest(max_age=2.5) is None


class _FakeStream:
    def __init__(self, pid, luid):
        self.pid = pid
        self.luid = luid
        self.reading = benchmark.VramReading(4 * MIB, 1 * MIB)
        self.closed = False
        self.missing_instance = False

    def latest(self, max_age):
        return self.reading

    def close(self):
        self.closed = True


def _probe(find_results, memory=(300 * MIB, 900 * MIB), streams=None):
    calls = iter(find_results)
    streams = [] if streams is None else streams

    def factory(pid, luid):
        streams.append(_FakeStream(pid, luid))
        return streams[-1]

    probe = benchmark.ProcessProbe(
        "llama-server.exe",
        NVIDIA,
        find=lambda _name: next(calls),
        read_memory=lambda _pid: memory,
        stream_factory=factory,
    )
    return probe, streams


def test_sonda_lee_ram_privada_working_set_y_vram_del_pid_resuelto():
    probe, streams = _probe([[40160]])
    sample = probe.sample()
    assert sample == benchmark.ResourceSample(40160, 300 * MIB, 900 * MIB, 4 * MIB, 1 * MIB)
    assert [s.pid for s in streams] == [40160]


def test_proceso_que_desaparece_cierra_el_flujo_y_da_sin_muestra():
    probe, streams = _probe([[40160], []])
    probe.sample()
    sample = probe.sample()
    assert sample.pid is None and sample.reason == "no_process"
    assert sample.private_bytes is None
    assert streams[0].closed


def test_cambio_de_pid_relanza_el_flujo_con_el_pid_nuevo():
    probe, streams = _probe([[40160], [40160], [31776]])
    probe.sample()
    probe.sample()
    probe.sample()
    assert [s.pid for s in streams] == [40160, 31776]
    assert streams[0].closed and not streams[1].closed


def test_cabecera_sin_la_instancia_del_pid_marca_el_flujo():
    sin_instancia, _ = _stream([HEADER, ROW], pid=9999)
    assert sin_instancia.missing_instance is True
    assert sin_instancia.latest(max_age=2.5) is None
    con_instancia, _ = _stream([HEADER, ROW])
    assert con_instancia.missing_instance is False


def test_flujo_sin_la_instancia_se_relanza_con_el_mismo_pid_pero_no_en_bucle():
    # Tercer piloto de CP-3: typeperf arranco antes de que llama-server creara su contexto CUDA, la
    # cabecera salio sin su instancia y, como el PID no cambio, el 2B anulo 120 intentos.
    reloj = [0.0]
    flujos = []

    def factory(pid, luid):
        flujo = _FakeStream(pid, luid)
        flujo.missing_instance = not flujos  # solo el primero nace sin la instancia
        if flujo.missing_instance:
            flujo.reading = None
        flujos.append(flujo)
        return flujo

    probe = benchmark.ProcessProbe(
        "llama-server.exe",
        NVIDIA,
        find=lambda _name: [40160],
        read_memory=lambda _pid: (1, 2),
        stream_factory=factory,
        clock=lambda: reloj[0],
    )
    assert probe.sample().vram_dedicated_bytes is None
    reloj[0] = 1.0
    probe.sample()
    assert len(flujos) == 1  # antes de 3 s no: typeperf aun no habria dado la cabecera
    reloj[0] = 5.0
    sample = probe.sample()
    assert [f.pid for f in flujos] == [40160, 40160]
    assert flujos[0].closed and not flujos[1].closed
    assert sample.vram_dedicated_bytes == 4 * MIB


def test_sin_acceso_al_proceso_da_sin_muestra_de_ram():
    probe, _ = _probe([[1556]], memory=None)
    sample = probe.sample()
    assert sample.reason == "no_access"
    assert sample.private_bytes is None and sample.working_set_bytes is None


def test_dos_llama_server_vivos_no_miden_ninguno_y_anulan_la_corrida():
    # Protocolo §1.4: con dos vivos no hay forma fiable de saber cual es el del modelo bajo prueba.
    probe, streams = _probe([[40160, 31776], [40160, 31776]])
    with benchmark.ResourceSampler(probe, interval=60) as sampler:
        pass
    assert all(s.reason == "multiple_processes" and s.pid is None for s in sampler.samples)
    assert streams == []
    assert sampler.summary()["annul"] == "multiple_processes"


def test_sin_typeperf_no_revienta_la_tanda():
    def rota(_pid, _luid):
        raise FileNotFoundError("typeperf")

    probe = benchmark.ProcessProbe(
        "llama-server.exe",
        NVIDIA,
        find=lambda _name: [40160],
        read_memory=lambda _pid: (1, 2),
        stream_factory=rota,
    )
    sample = probe.sample()
    assert sample.private_bytes == 1 and sample.vram_dedicated_bytes is None
    assert probe.stream_error and "FileNotFoundError" in probe.stream_error


def test_corrida_instantanea_tiene_lectura_antes_y_despues():
    probe, _ = _probe([[40160], [40160]])
    with benchmark.ResourceSampler(probe, interval=60) as sampler:
        pass
    assert len(sampler.samples) == 2
    summary = sampler.summary()
    assert summary["annul"] is None
    assert summary["private_bytes_before"] == summary["private_bytes_after"] == 300 * MIB


def test_corrida_con_cero_muestras_se_marca_para_anular_y_no_se_publica_vacia():
    probe, _ = _probe([[], []])
    with benchmark.ResourceSampler(probe, interval=60) as sampler:
        pass
    summary = sampler.summary()
    assert summary["samples"] == 2 and summary["ram_samples"] == 0
    assert summary["annul"] == "zero_ram_samples"


def test_resumen_anula_por_cada_motivo():
    ok = benchmark.ResourceSample(1, 10, 20, 30, 5)
    sin_vram = benchmark.ResourceSample(1, 10, 20)
    varios = benchmark.ResourceSample(None, reason="multiple_processes")

    def annul(samples, vram_expected=True):
        return benchmark.summarize_resources(samples, enabled=True, vram_expected=vram_expected)[
            "annul"
        ]

    assert annul([ok, ok]) is None
    assert annul([ok, varios]) == "multiple_processes"
    assert annul([ok, benchmark.ResourceSample(2, 10, 20, 30, 5)]) == "process_changed"
    assert annul([sin_vram]) == "zero_vram_samples"
    assert annul([sin_vram], vram_expected=False) is None


def test_resumen_separa_shared_inicial_del_pico():
    samples = [
        benchmark.ResourceSample(1, 10 * MIB, 50 * MIB, 100 * MIB, 5 * MIB),
        benchmark.ResourceSample(1, 40 * MIB, 20 * MIB, 90 * MIB, 9 * MIB),
    ]
    summary = benchmark.summarize_resources(samples, enabled=True, vram_expected=True)
    assert summary["private_bytes_peak"] == 40 * MIB
    assert summary["working_set_bytes_peak"] == 50 * MIB
    assert summary["vram_dedicated_bytes_peak"] == 100 * MIB
    assert (summary["vram_shared_bytes_first"], summary["vram_shared_bytes_peak"]) == (
        5 * MIB,
        9 * MIB,
    )


# --- El uso: el runner escribe lo que la sonda midio ----------------------------------------------


class _NullMetrics:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def peaks(self):
        return {}


def _args(tmp_path, *extra):
    cases = RAIZ / "benchmarks" / "catalogo-2026-09" / "cases.json"
    parser = argparse.ArgumentParser()
    benchmark.add_parser(parser.add_subparsers())
    return parser.parse_args(
        [
            "benchmark",
            "--model",
            "m",
            "--label",
            "l",
            "--cases",
            str(cases),
            "--case",
            "clasificar-53",
            "--runs",
            "1",
            "--endpoint",
            "http://backend.test/v1",
            "--output",
            str(tmp_path / "out.jsonl"),
            *extra,
        ]
    )


@pytest.fixture
def backend_falso(monkeypatch):
    def handler(_request):
        return httpx2.Response(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )

    real = benchmark.httpx2.Client
    monkeypatch.setattr(
        benchmark.httpx2,
        "Client",
        lambda **kwargs: real(transport=httpx2.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(benchmark, "MetricsSampler", _NullMetrics)


def test_runner_sin_sonda_escribe_el_bloque_de_recursos_vacio(tmp_path, backend_falso):
    args = _args(tmp_path)
    assert benchmark.run_benchmark(args) == 0
    record = json.loads((tmp_path / "out.jsonl").read_text(encoding="utf-8"))
    assert record["resources"]["enabled"] is False
    assert record["resources"]["annul"] is None
    assert record["resources"]["private_bytes_peak"] is None


def test_runner_con_sonda_escribe_la_medida_y_cierra_la_sonda(tmp_path, backend_falso, monkeypatch):
    creadas = []

    class Probe:
        def __init__(self, process_name, gpu_luid):
            self.process_name = process_name
            self.gpu_luid = gpu_luid
            self.closed = False
            creadas.append(self)

        def sample(self):
            return benchmark.ResourceSample(40160, 700 * MIB, 3000 * MIB, 9000 * MIB, 8 * MIB)

        def close(self):
            self.closed = True

    monkeypatch.setattr(benchmark, "probe_supported", lambda: True)
    monkeypatch.setattr(benchmark, "ProcessProbe", Probe)
    args = _args(tmp_path, "--probe-process", "llama-server.exe", "--gpu-luid", NVIDIA)
    assert benchmark.run_benchmark(args) == 0
    record = json.loads((tmp_path / "out.jsonl").read_text(encoding="utf-8"))
    assert record["variant"]["probe_process"] == "llama-server.exe"
    assert record["variant"]["gpu_luid"] == NVIDIA
    assert record["resources"]["private_bytes_peak"] == 700 * MIB
    assert record["resources"]["vram_dedicated_bytes_peak"] == 9000 * MIB
    assert record["resources"]["pids"] == [40160]
    assert record["resources"]["annul"] is None
    assert creadas[0].process_name == "llama-server.exe" and creadas[0].closed


def test_runner_rechaza_la_sonda_fuera_de_windows_sin_escribir_nada(
    tmp_path, backend_falso, monkeypatch
):
    monkeypatch.setattr(benchmark, "probe_supported", lambda: False)
    args = _args(tmp_path, "--probe-process", "llama-server.exe")
    assert benchmark.run_benchmark(args) == 2
    assert not (tmp_path / "out.jsonl").exists()


def test_runner_pide_el_luid_si_no_lo_puede_resolver(tmp_path, backend_falso, monkeypatch):
    monkeypatch.setattr(benchmark, "probe_supported", lambda: True)
    monkeypatch.setattr(benchmark, "resolve_gpu_luid", lambda: None)
    args = _args(tmp_path, "--probe-process", "llama-server.exe")
    assert benchmark.run_benchmark(args) == 2


# --- El envoltorio de llama-bench -----------------------------------------------------------------


def _cargar_script():
    spec = importlib.util.spec_from_file_location(
        "sonda_recursos", RAIZ / "scripts" / "sonda_recursos.py"
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["sonda_recursos"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_envoltorio_escribe_la_medida_del_comando(tmp_path):
    script = _cargar_script()
    probe, _ = _probe([[40160]] * 1000)
    salida = tmp_path / "medida.json"
    rc = script.main(
        ["--process", "llama-bench.exe", "--output", str(salida), "--", sys.executable, "-c", ""],
        probe_factory=lambda _name, _luid: probe,
    )
    assert rc == 0
    medida = json.loads(salida.read_text(encoding="utf-8"))
    assert medida["exit_code"] == 0
    assert medida["resources"]["private_bytes_peak"] == 300 * MIB


def test_envoltorio_devuelve_3_si_la_medida_queda_anulada(tmp_path):
    script = _cargar_script()
    probe, _ = _probe([[]] * 1000)
    rc = script.main(
        [
            "--process",
            "x.exe",
            "--output",
            str(tmp_path / "m.json"),
            "--",
            sys.executable,
            "-c",
            "",
        ],
        probe_factory=lambda _name, _luid: probe,
    )
    assert rc == 3


# --- Windows de verdad ----------------------------------------------------------------------------

_HIJO = (
    "import mmap, os, sys\n"
    "modo, n, ruta = sys.argv[1], int(sys.argv[2]), sys.argv[3]\n"
    "vivo = None\n"
    "if modo == 'anonimo':\n"
    "    vivo = bytearray(n)\n"
    "    for i in range(0, n, 4096):\n"
    "        vivo[i] = 1\n"
    "elif modo == 'mapeado':\n"
    "    f = open(ruta, 'rb')\n"
    "    vivo = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)\n"
    "    total = sum(vivo[i] for i in range(0, n, 4096))\n"
    "print(os.getpid(), flush=True)\n"
    "sys.stdin.read()\n"
)


@solo_windows
def test_toolhelp_ve_este_proceso_por_su_nombre():
    import os

    propio = benchmark.list_processes()[os.getpid()]
    assert os.getpid() in benchmark.find_pids(propio.upper())


@solo_windows
def test_control_positivo_ram_privada_y_working_set_se_distinguen(tmp_path):
    """Tres hijos: quieto, 128 MiB anonimos y 128 MiB mapeados desde fichero y leidos.

    Lo anonimo sube los dos contadores; lo mapeado sube el working set y NO la privada. Sin el
    hijo mapeado el test no distinguiria un contador del otro —un mutante que devolvia el working
    set como privada lo paso—, y esa diferencia es justo la que decide CP-2b.
    """
    tam = 128 * MIB
    fichero = tmp_path / "mapeado.bin"
    with fichero.open("wb") as destino:
        bloque = bytes(range(256)) * (MIB // 256)
        for _ in range(tam // MIB):
            destino.write(bloque)
    hijos = []
    try:
        medidas = {}
        for modo in ("quieto", "anonimo", "mapeado"):
            hijo = subprocess.Popen(
                [sys.executable, "-c", _HIJO, modo, str(tam), str(fichero)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
            )
            hijos.append(hijo)
            assert hijo.stdout is not None
            # El PID lo dice el hijo: con el python.exe de un venv, Popen.pid es el del lanzador,
            # que no tiene la memoria (la primera pasada de la tarea 12 midio justo ese).
            pid = int(hijo.stdout.readline())
            medidas[modo] = benchmark.read_process_memory(pid)
        quieto, anonimo, mapeado = medidas["quieto"], medidas["anonimo"], medidas["mapeado"]
        assert quieto and anonimo and mapeado
        assert anonimo[0] - quieto[0] > 100 * MIB, "lo anonimo tiene que subir la privada"
        assert mapeado[1] - quieto[1] > 100 * MIB, "lo mapeado tiene que subir el working set"
        assert mapeado[0] - quieto[0] < 32 * MIB, "lo mapeado NO puede subir la privada"
    finally:
        for hijo in hijos:
            hijo.stdin.close()
            try:
                hijo.wait(timeout=10)
            except subprocess.TimeoutExpired:
                hijo.kill()


@solo_windows
def test_proceso_inexistente_da_none_y_no_una_excepcion():
    assert benchmark.read_process_memory(0x7FFFFFF0) is None
