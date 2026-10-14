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

ROOT = Path(__file__).parents[1]
MIB = 1024 * 1024
NVIDIA = "0x00000000_0x0000F722"
IGPU = "0x00000000_0x00014FF6"

windows_only = pytest.mark.skipif(
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


def test_parsing_takes_both_counters_from_the_right_instance_among_several():
    columns = benchmark.parse_typeperf_header(HEADER, 1556, NVIDIA)
    assert columns == {1: "dedicated", 3: "shared"}
    reading = benchmark.parse_typeperf_sample(ROW, columns)
    assert reading == benchmark.VramReading(9433419776, 14647296)


def test_parsing_respects_the_requested_pid_and_luid():
    other_pid = benchmark.parse_typeperf_header(HEADER, 40160, NVIDIA)
    assert benchmark.parse_typeperf_sample(ROW, other_pid) == benchmark.VramReading(11403264, None)
    igpu = benchmark.parse_typeperf_header(HEADER, 1556, IGPU)
    assert benchmark.parse_typeperf_sample(ROW, igpu) == benchmark.VramReading(202113024, 757760)


def test_wrong_luid_gives_empty_header_and_zero_samples_not_another_ones_vram():
    columns = benchmark.parse_typeperf_header(HEADER, 1556, "0x00000000_0x0000DEAD")
    assert columns == {}
    assert benchmark.parse_typeperf_sample(ROW, columns) is None


def test_minus_one_is_a_dead_process_and_console_messages_are_ignored():
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


def test_nvidia_luid_is_paired_with_nvidia_smi():
    values = benchmark.parse_adapter_dedicated(ADAPTERS)
    assert values[NVIDIA] == 997896192
    assert benchmark.choose_gpu_luid(values, 942.0) == NVIDIA


def test_luid_is_not_guessed_unless_there_is_exactly_one_candidate():
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


def test_stream_keeps_the_last_sample_of_the_requested_instance():
    stream, created = _stream(["Nota previa", HEADER, ROW])
    assert r"\GPU Process Memory(pid_1556_*)\Dedicated Usage" in created["command"]
    assert stream.latest(max_age=2.5) == benchmark.VramReading(9433419776, 14647296)
    assert stream.process_gone is False
    stream.close()
    assert created["process"].terminated


def test_vanishing_pid_gives_no_sample_and_not_an_exception():
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


def test_probe_reads_private_ram_working_set_and_vram_of_the_resolved_pid():
    probe, streams = _probe([[40160]])
    sample = probe.sample()
    assert sample == benchmark.ResourceSample(40160, 300 * MIB, 900 * MIB, 4 * MIB, 1 * MIB)
    assert [s.pid for s in streams] == [40160]


def test_vanishing_process_closes_the_stream_and_gives_no_sample():
    probe, streams = _probe([[40160], []])
    probe.sample()
    sample = probe.sample()
    assert sample.pid is None and sample.reason == "no_process"
    assert sample.private_bytes is None
    assert streams[0].closed


def test_pid_change_relaunches_the_stream_with_the_new_pid():
    probe, streams = _probe([[40160], [40160], [31776]])
    probe.sample()
    probe.sample()
    probe.sample()
    assert [s.pid for s in streams] == [40160, 31776]
    assert streams[0].closed and not streams[1].closed


def test_header_without_the_pid_instance_marks_the_stream():
    without_instance, _ = _stream([HEADER, ROW], pid=9999)
    assert without_instance.missing_instance is True
    assert without_instance.latest(max_age=2.5) is None
    with_instance, _ = _stream([HEADER, ROW])
    assert with_instance.missing_instance is False


def test_stream_without_the_instance_relaunches_with_the_same_pid_but_not_in_a_loop():
    # Tercer piloto de CP-3: typeperf arranco antes de que llama-server creara su contexto CUDA, la
    # cabecera salio sin su instancia y, como el PID no cambio, el 2B anulo 120 intentos.
    clock = [0.0]
    streams = []

    def factory(pid, luid):
        stream = _FakeStream(pid, luid)
        stream.missing_instance = not streams  # solo el primero nace sin la instancia
        if stream.missing_instance:
            stream.reading = None
        streams.append(stream)
        return stream

    probe = benchmark.ProcessProbe(
        "llama-server.exe",
        NVIDIA,
        find=lambda _name: [40160],
        read_memory=lambda _pid: (1, 2),
        stream_factory=factory,
        clock=lambda: clock[0],
    )
    assert probe.sample().vram_dedicated_bytes is None
    clock[0] = 1.0
    probe.sample()
    assert len(streams) == 1  # antes de 3 s no: typeperf aun no habria dado la cabecera
    clock[0] = 5.0
    sample = probe.sample()
    assert [f.pid for f in streams] == [40160, 40160]
    assert streams[0].closed and not streams[1].closed
    assert sample.vram_dedicated_bytes == 4 * MIB


def test_without_process_access_gives_no_ram_sample():
    probe, _ = _probe([[1556]], memory=None)
    sample = probe.sample()
    assert sample.reason == "no_access"
    assert sample.private_bytes is None and sample.working_set_bytes is None


def test_two_live_llama_servers_measure_neither_and_annul_the_run():
    # Protocolo §1.4: con dos vivos no hay forma fiable de saber cual es el del modelo bajo prueba.
    probe, streams = _probe([[40160, 31776], [40160, 31776]])
    with benchmark.ResourceSampler(probe, interval=60) as sampler:
        pass
    assert all(s.reason == "multiple_processes" and s.pid is None for s in sampler.samples)
    assert streams == []
    assert sampler.summary()["annul"] == "multiple_processes"


def test_without_typeperf_the_batch_does_not_blow_up():
    def broken(_pid, _luid):
        raise FileNotFoundError("typeperf")

    probe = benchmark.ProcessProbe(
        "llama-server.exe",
        NVIDIA,
        find=lambda _name: [40160],
        read_memory=lambda _pid: (1, 2),
        stream_factory=broken,
    )
    sample = probe.sample()
    assert sample.private_bytes == 1 and sample.vram_dedicated_bytes is None
    assert probe.stream_error and "FileNotFoundError" in probe.stream_error


def test_instant_run_has_a_reading_before_and_after():
    probe, _ = _probe([[40160], [40160]])
    with benchmark.ResourceSampler(probe, interval=60) as sampler:
        pass
    assert len(sampler.samples) == 2
    summary = sampler.summary()
    assert summary["annul"] is None
    assert summary["private_bytes_before"] == summary["private_bytes_after"] == 300 * MIB


def test_run_with_zero_samples_is_marked_to_annul_and_not_published_empty():
    probe, _ = _probe([[], []])
    with benchmark.ResourceSampler(probe, interval=60) as sampler:
        pass
    summary = sampler.summary()
    assert summary["samples"] == 2 and summary["ram_samples"] == 0
    assert summary["annul"] == "zero_ram_samples"


def test_summary_annuls_for_each_reason():
    ok = benchmark.ResourceSample(1, 10, 20, 30, 5)
    without_vram = benchmark.ResourceSample(1, 10, 20)
    multiple = benchmark.ResourceSample(None, reason="multiple_processes")

    def annul(samples, vram_expected=True):
        return benchmark.summarize_resources(samples, enabled=True, vram_expected=vram_expected)[
            "annul"
        ]

    assert annul([ok, ok]) is None
    assert annul([ok, multiple]) == "multiple_processes"
    assert annul([ok, benchmark.ResourceSample(2, 10, 20, 30, 5)]) == "process_changed"
    assert annul([without_vram]) == "zero_vram_samples"
    assert annul([without_vram], vram_expected=False) is None


def test_summary_separates_initial_shared_from_the_peak():
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


def test_summary_host_ram_is_the_peak_of_the_per_sample_difference():
    # Forma de CP-2b: al descargar expertos la privada casi no se mueve y la VRAM baja. El pico de la
    # resta (7 GiB) no es la resta de los picos (13 - 11 = 2), y la muestra sin VRAM no cuenta como
    # VRAM cero (daria 9 GiB).
    gib = 1024 * MIB
    samples = [
        benchmark.ResourceSample(1, 12 * gib, 11 * gib, 11 * gib, 0),
        benchmark.ResourceSample(1, 13 * gib, 6 * gib, 6 * gib, 5 * gib),
        benchmark.ResourceSample(1, 9 * gib, 9 * gib),
    ]
    summary = benchmark.summarize_resources(samples, enabled=True, vram_expected=True)
    assert summary["host_private_bytes_peak"] == 7 * gib
    ram_only = benchmark.summarize_resources(samples[2:], enabled=True, vram_expected=False)
    assert ram_only["host_private_bytes_peak"] is None


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
    cases = ROOT / "benchmarks" / "catalogo-2026-09" / "cases.json"
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
def fake_backend(monkeypatch):
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


def test_runner_without_probe_writes_an_empty_resources_block(tmp_path, fake_backend):
    args = _args(tmp_path)
    assert benchmark.run_benchmark(args) == 0
    record = json.loads((tmp_path / "out.jsonl").read_text(encoding="utf-8"))
    assert record["resources"]["enabled"] is False
    assert record["resources"]["annul"] is None
    assert record["resources"]["private_bytes_peak"] is None


def test_runner_with_probe_writes_the_measurement_and_closes_the_probe(
    tmp_path, fake_backend, monkeypatch
):
    created = []

    class Probe:
        def __init__(self, process_name, gpu_luid):
            self.process_name = process_name
            self.gpu_luid = gpu_luid
            self.closed = False
            created.append(self)

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
    assert created[0].process_name == "llama-server.exe" and created[0].closed


def test_runner_rejects_the_probe_outside_windows_without_writing_anything(
    tmp_path, fake_backend, monkeypatch
):
    monkeypatch.setattr(benchmark, "probe_supported", lambda: False)
    args = _args(tmp_path, "--probe-process", "llama-server.exe")
    assert benchmark.run_benchmark(args) == 2
    assert not (tmp_path / "out.jsonl").exists()


def test_runner_asks_for_the_luid_if_it_cannot_resolve_it(tmp_path, fake_backend, monkeypatch):
    monkeypatch.setattr(benchmark, "probe_supported", lambda: True)
    monkeypatch.setattr(benchmark, "resolve_gpu_luid", lambda: None)
    args = _args(tmp_path, "--probe-process", "llama-server.exe")
    assert benchmark.run_benchmark(args) == 2


# --- El envoltorio de llama-bench -----------------------------------------------------------------


def _load_probe_script():
    spec = importlib.util.spec_from_file_location(
        "resource_probe", ROOT / "scripts" / "resource_probe.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["resource_probe"] = module
    spec.loader.exec_module(module)
    return module


def test_wrapper_writes_the_command_measurement(tmp_path):
    script = _load_probe_script()
    probe, _ = _probe([[40160]] * 1000)
    output = tmp_path / "measurement.json"
    rc = script.main(
        ["--process", "llama-bench.exe", "--output", str(output), "--", sys.executable, "-c", ""],
        probe_factory=lambda _name, _luid: probe,
    )
    assert rc == 0
    measurement = json.loads(output.read_text(encoding="utf-8"))
    assert measurement["exit_code"] == 0
    assert measurement["resources"]["private_bytes_peak"] == 300 * MIB


def test_wrapper_returns_3_if_the_measurement_is_annulled(tmp_path):
    script = _load_probe_script()
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

_CHILD = (
    "import mmap, os, sys\n"
    "mode, n, path = sys.argv[1], int(sys.argv[2]), sys.argv[3]\n"
    "held = None\n"
    "if mode == 'anonymous':\n"
    "    held = bytearray(n)\n"
    "    for i in range(0, n, 4096):\n"
    "        held[i] = 1\n"
    "elif mode == 'mapped':\n"
    "    f = open(path, 'rb')\n"
    "    held = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)\n"
    "    total = sum(held[i] for i in range(0, n, 4096))\n"
    "print(os.getpid(), flush=True)\n"
    "sys.stdin.read()\n"
)


@windows_only
def test_toolhelp_sees_this_process_by_its_name():
    import os

    own = benchmark.list_processes()[os.getpid()]
    assert os.getpid() in benchmark.find_pids(own.upper())


@windows_only
def test_positive_control_private_ram_and_working_set_are_told_apart(tmp_path):
    """Tres hijos: quieto, 128 MiB anonimos y 128 MiB mapeados desde fichero y leidos.

    Lo anonimo sube los dos contadores; lo mapeado sube el working set y NO la privada. Sin el
    hijo mapeado el test no distinguiria un contador del otro —un mutante que devolvia el working
    set como privada lo paso—, y esa diferencia es justo la que decide CP-2b.
    """
    size = 128 * MIB
    file = tmp_path / "mapped.bin"
    with file.open("wb") as dest:
        block = bytes(range(256)) * (MIB // 256)
        for _ in range(size // MIB):
            dest.write(block)
    children = []
    try:
        measurements = {}
        for mode in ("still", "anonymous", "mapped"):
            child = subprocess.Popen(
                [sys.executable, "-c", _CHILD, mode, str(size), str(file)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
            )
            children.append(child)
            assert child.stdout is not None
            # El PID lo dice el hijo: con el python.exe de un venv, Popen.pid es el del lanzador,
            # que no tiene la memoria (la primera pasada de la tarea 12 midio justo ese).
            pid = int(child.stdout.readline())
            measurements[mode] = benchmark.read_process_memory(pid)
        idle, anonymous, mapped = (
            measurements["still"],
            measurements["anonymous"],
            measurements["mapped"],
        )
        assert idle and anonymous and mapped
        assert anonymous[0] - idle[0] > 100 * MIB, "lo anonimo tiene que subir la privada"
        assert mapped[1] - idle[1] > 100 * MIB, "lo mapeado tiene que subir el working set"
        assert mapped[0] - idle[0] < 32 * MIB, "lo mapeado NO puede subir la privada"
    finally:
        for child in children:
            child.stdin.close()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()


@windows_only
def test_nonexistent_process_gives_none_and_not_an_exception():
    assert benchmark.read_process_memory(0x7FFFFFF0) is None
