"""Tests de F7: estimador de VRAM + parser GGUF + CLIs check-llamaswap/init-llamaswap.

No requiere llama-swap real. Los GGUF son sintéticos: el header de metadatos se escribe de
verdad (unos cientos de bytes, válido para read_gguf_arch_info), pero el tamaño "de pesos"
que ve estimate_model_vram se simula mockeando Path.stat() para esa ruta puntual — así se
puede probar con modelos de varios GiB sin escribir un solo byte de más a disco real (un
primer intento con archivos dispersos vía seek()+write() resultó NO ser sparse en este
filesystem y llegó a llenar el disco del usuario; de ahí este enfoque).
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from local_delegate import cli
from local_delegate import llamaswap_config as lc

GIB = 1024**3


def _write_fake_gguf(
    path: Path,
    *,
    arch: str = "testarch",
    n_layer: int = 4,
    head_count: int = 4,
    head_count_kv: int = 2,
    embedding_length: int = 64,
) -> None:
    """Escribe un GGUF sintético mínimo pero binariamente válido para read_gguf_arch_info."""
    kv: list[tuple[str, int, object]] = [
        ("general.architecture", 8, arch),
        (f"{arch}.block_count", 4, n_layer),
        (f"{arch}.attention.head_count", 4, head_count),
        (f"{arch}.attention.head_count_kv", 4, head_count_kv),
        (f"{arch}.embedding_length", 4, embedding_length),
    ]
    buf = bytearray()
    buf += b"GGUF"
    buf += struct.pack("<I", 3)  # version
    buf += struct.pack("<Q", 0)  # tensor_count
    buf += struct.pack("<Q", len(kv))  # metadata_kv_count
    for key, vtype, value in kv:
        key_bytes = key.encode("utf-8")
        buf += struct.pack("<Q", len(key_bytes)) + key_bytes
        buf += struct.pack("<I", vtype)
        if vtype == 8:
            val_bytes = value.encode("utf-8")
            buf += struct.pack("<Q", len(val_bytes)) + val_bytes
        elif vtype == 4:
            buf += struct.pack("<I", value)
        else:  # pragma: no cover - no se usa en estos tests
            raise ValueError("tipo GGUF no soportado por el helper de test")
    path.write_bytes(bytes(buf))


def _mock_file_size(monkeypatch, path: Path, size_bytes: int) -> None:
    """Hace que path.stat().st_size reporte size_bytes SIN escribir nada a disco.

    Solo intercepta la ruta exacta indicada; cualquier otra ruta (incluidos los archivos
    reales que pytest/tmp_path manejan por su cuenta) sigue viendo el stat() real.
    """
    real_stat = Path.stat
    # OJO: NO usar Path.resolve() aquí para comparar — en Windows resolve() internamente
    # llama a .stat() para resolver symlinks/junctions, lo que reentra en este mismo mock
    # y produce recursión infinita. os.path.abspath es puro manejo de strings, sin I/O.
    target = os.path.normcase(os.path.abspath(str(path)))

    def fake_stat(self, *args, **kwargs):
        result = real_stat(self, *args, **kwargs)
        if os.path.normcase(os.path.abspath(str(self))) == target:
            seq = (
                result.st_mode,
                result.st_ino,
                result.st_dev,
                result.st_nlink,
                result.st_uid,
                result.st_gid,
                size_bytes,
                result.st_atime,
                result.st_mtime,
                result.st_ctime,
            )
            return os.stat_result(seq)
        return result

    monkeypatch.setattr(Path, "stat", fake_stat)


def _write_fake_gguf_with_size(monkeypatch, path: Path, size_bytes: int, **kwargs) -> None:
    """Combina _write_fake_gguf (header real) + _mock_file_size (tamaño simulado)."""
    _write_fake_gguf(path, **kwargs)
    _mock_file_size(monkeypatch, path, size_bytes)


# --- import guard (sin pyyaml) ------------------------------------------------------------


def test_load_config_without_yaml_raises_with_extra_hint(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "yaml", None)
    with pytest.raises(RuntimeError, match=r'pip install "local-delegate-mcp\[llamaswap\]"'):
        lc.load_config(tmp_path / "config.yaml")


def test_dump_config_without_yaml_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "yaml", None)
    with pytest.raises(RuntimeError, match=r"local-delegate-mcp\[llamaswap\]"):
        lc.dump_config({"models": {}}, tmp_path / "out.yaml")


# --- parse_model_gguf_path / _parse_cmd_flags ----------------------------------------------


def test_parse_model_gguf_path_long_flag():
    cmd = "llama-server --port 1 --model /models/foo.gguf -ngl 99"
    assert lc.parse_model_gguf_path(cmd) == Path("/models/foo.gguf")


def test_parse_model_gguf_path_short_flag():
    cmd = "llama-server --port 1 -m /models/foo.gguf -ngl 99"
    assert lc.parse_model_gguf_path(cmd) == Path("/models/foo.gguf")


def test_parse_model_gguf_path_missing_returns_none():
    cmd = "docker run --name x ghcr.io/ggml-org/llama.cpp:server"
    assert lc.parse_model_gguf_path(cmd) is None


def test_parse_cmd_flags_ctx_and_cache_types():
    cmd = (
        "llama-server --port 1 --model /m.gguf -ngl 99 --ctx-size 8192 "
        "--cache-type-k q4_0 --cache-type-v q4_0 --jinja"
    )
    flags = lc._parse_cmd_flags(cmd)
    assert flags["ctx_size"] == "8192"
    assert flags["cache_type_k"] == "q4_0"
    assert flags["cache_type_v"] == "q4_0"


# --- read_gguf_arch_info ---------------------------------------------------------------


def test_read_gguf_arch_info_valid(tmp_path):
    p = tmp_path / "fake.gguf"
    _write_fake_gguf(p, n_layer=32, head_count=32, head_count_kv=8, embedding_length=4096)
    info = lc.read_gguf_arch_info(p)
    assert info == {"n_layer": 32, "n_head_kv": 8, "head_dim": 128}


def test_read_gguf_arch_info_invalid_magic(tmp_path):
    p = tmp_path / "notgguf.bin"
    p.write_bytes(b"NOPE" + b"\0" * 32)
    assert lc.read_gguf_arch_info(p) is None


def test_read_gguf_arch_info_missing_file(tmp_path):
    assert lc.read_gguf_arch_info(tmp_path / "missing.gguf") is None


# --- estimate_model_vram -----------------------------------------------------------------


def test_estimate_model_vram_flat_fallback_without_ctx(monkeypatch, tmp_path):
    p = tmp_path / "m.gguf"
    _write_fake_gguf_with_size(monkeypatch, p, 2 * GIB)
    entry = {"cmd": f"llama-server --port 1 --model {p} -ngl 99"}  # sin --ctx-size
    est = lc.estimate_model_vram("m", entry)
    assert est.method == "flat-fallback"
    assert est.gb == pytest.approx(2.0 * 1.2, rel=1e-3)


def test_estimate_model_vram_gguf_metadata_matches_hand_calc(monkeypatch, tmp_path):
    p = tmp_path / "m.gguf"
    # pesos = 4 GiB exactos; arquitectura conocida; ctx explícito -> debe usar la vía fina.
    _write_fake_gguf_with_size(
        monkeypatch,
        p,
        4 * GIB,
        n_layer=32,
        head_count=32,
        head_count_kv=8,
        embedding_length=4096,
    )
    entry = {"cmd": f"llama-server --port 1 --model {p} -ngl 99 --ctx-size 16384"}
    est = lc.estimate_model_vram("m", entry)
    assert est.method == "gguf-metadata"
    # head_dim=128, kv cache fp16/fp16 (default): 2*32*8*128*16384*2 bytes = 2 GiB
    expected_kv_gb = (2 * 32 * 8 * 128 * 16384 * 2) / GIB
    expected = 4.0 * 1.05 + expected_kv_gb
    assert est.gb == pytest.approx(expected, rel=1e-6)


def test_estimate_model_vram_quantized_cache_smaller_than_fp16(monkeypatch, tmp_path):
    p = tmp_path / "m.gguf"
    _write_fake_gguf_with_size(
        monkeypatch,
        p,
        8 * GIB,
        n_layer=48,
        head_count=40,
        head_count_kv=8,
        embedding_length=5120,
    )
    fp16_entry = {"cmd": f"llama-server --port 1 --model {p} -ngl 99 --ctx-size 8192"}
    q4_entry = {
        "cmd": (
            f"llama-server --port 1 --model {p} -ngl 99 --ctx-size 8192 "
            "--cache-type-k q4_0 --cache-type-v q4_0"
        )
    }
    est_fp16 = lc.estimate_model_vram("m", fp16_entry)
    est_q4 = lc.estimate_model_vram("m", q4_entry)
    assert est_q4.gb < est_fp16.gb


def test_estimate_model_vram_override():
    est = lc.estimate_model_vram("m", {"cmd": ""}, override_gb=3.5)
    assert est.method == "override"
    assert est.gb == 3.5


def test_estimate_model_vram_missing_model_flag():
    est = lc.estimate_model_vram("m", {"cmd": "docker run x"})
    assert est.method == "error"
    assert "no se encontró" in est.error


def test_estimate_model_vram_file_not_found(tmp_path):
    entry = {"cmd": f"llama-server --model {tmp_path / 'nope.gguf'} --ctx-size 4096"}
    est = lc.estimate_model_vram("m", entry)
    assert est.method == "error"
    assert "no encontrado" in est.error


# --- estimate_model_ram (F7.9) ------------------------------------------------------------


def test_estimate_model_ram_weights_only(monkeypatch, tmp_path):
    p = tmp_path / "m.gguf"
    _write_fake_gguf_with_size(monkeypatch, p, 8 * GIB, n_layer=48, embedding_length=5120)
    # con --ctx-size (que sí afectaría la vía fina de VRAM), la RAM sigue siendo solo pesos
    entry = {"cmd": f"llama-server --port 1 --model {p} -ngl 99 --ctx-size 16384"}
    est = lc.estimate_model_ram("m", entry)
    assert est.method == "weights-only"
    assert est.gb == pytest.approx(8.0, rel=1e-6)


def test_estimate_model_ram_override():
    est = lc.estimate_model_ram("m", {"cmd": ""}, override_gb=4.0)
    assert est.method == "override"
    assert est.gb == 4.0


def test_estimate_model_ram_missing_model_flag():
    est = lc.estimate_model_ram("m", {"cmd": "docker run x"})
    assert est.method == "error"


def test_estimate_model_ram_file_not_found(tmp_path):
    entry = {"cmd": f"llama-server --model {tmp_path / 'nope.gguf'}"}
    est = lc.estimate_model_ram("m", entry)
    assert est.method == "error"
    assert "no encontrado" in est.error


# --- worst_case_vram_gb ------------------------------------------------------------------


def _est(gb: float) -> lc.VramEstimate:
    return lc.VramEstimate("x", gb, "override", "")


def test_worst_case_vram_swap_group_takes_max():
    groups = {"swap": {"swap": True, "members": ["a", "b"]}}
    estimates = {"a": _est(3.0), "b": _est(7.0)}
    total, breakdown = lc.worst_case_vram_gb(groups, estimates)
    assert total == pytest.approx(7.0)
    assert breakdown[0].contribution_gb == pytest.approx(7.0)


def test_worst_case_vram_no_swap_group_sums():
    groups = {"together": {"swap": False, "members": ["a", "b"]}}
    estimates = {"a": _est(3.0), "b": _est(7.0)}
    total, _ = lc.worst_case_vram_gb(groups, estimates)
    assert total == pytest.approx(10.0)


def test_worst_case_vram_multiple_groups_sum_of_contributions():
    groups = {
        "resident": {"swap": False, "persistent": True, "members": ["r"]},
        "swap": {"swap": True, "members": ["a", "b"]},
    }
    estimates = {"r": _est(3.0), "a": _est(5.0), "b": _est(9.0)}
    total, _ = lc.worst_case_vram_gb(groups, estimates)
    assert total == pytest.approx(3.0 + 9.0)


# --- CLI check-llamaswap: 3 escenarios (cabe / no cabe / justo en el margen) --------------


def _write_config_with_models(monkeypatch, tmp_path, model_sizes_gib: dict, groups: dict) -> Path:
    """Config YAML real (no fixture estática) con GGUF sintéticos de tamaño simulado.

    Se genera por test en vez de vivir en tests/fixtures/ porque las rutas del 'cmd' de cada
    modelo deben apuntar a archivos que existen de verdad (estimate_model_vram valida
    is_file()); una ruta absoluta fija no sería portable entre máquinas/CI. El tamaño "de
    pesos" se simula con _mock_file_size, nunca se escriben GiB reales a disco.
    """
    models = {}
    for mid, size_gib in model_sizes_gib.items():
        gguf = tmp_path / f"{mid}.gguf"
        _write_fake_gguf_with_size(monkeypatch, gguf, int(size_gib * GIB))
        models[mid] = {"cmd": f"llama-server --port 1 --model {gguf} -ngl 99"}  # sin ctx -> flat
    config_path = tmp_path / "config.yaml"
    lc.dump_config({"models": models, "groups": groups}, config_path)
    return config_path


def test_check_llamaswap_cabe(monkeypatch, tmp_path, capsys):
    groups = {
        "resident": {"swap": False, "persistent": True, "members": ["r"]},
        "swap": {"swap": True, "members": ["a", "b"]},
    }
    # con factor plano x1.2: r=3*1.2=3.6, max(a=2*1.2=2.4, b=4*1.2=4.8)=4.8 -> total=8.4
    config_path = _write_config_with_models(monkeypatch, tmp_path, {"r": 3, "a": 2, "b": 4}, groups)
    rc = cli.run(["check-llamaswap", "--config", str(config_path), "--vram-gb", "16"])
    assert rc == 0
    assert "OK: cabe" in capsys.readouterr().out


def test_check_llamaswap_no_cabe(monkeypatch, tmp_path, capsys):
    groups = {"swap": {"swap": True, "members": ["a", "b"]}}
    # max(6, 14)*1.2 = 16.8 GiB > 16 - 1.5 = 14.5 -> no cabe.
    config_path = _write_config_with_models(monkeypatch, tmp_path, {"a": 6, "b": 14}, groups)
    rc = cli.run(["check-llamaswap", "--config", str(config_path), "--vram-gb", "16"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "NO CABE" in out


def test_check_llamaswap_justo_en_el_margen(monkeypatch, tmp_path):
    # 1 modelo de 10 GiB reales -> estimado 12.0 GiB (x1.2). budget = 13.5 - 1.5 = 12.0 exacto.
    groups = {"swap": {"swap": True, "members": ["a"]}}
    config_path = _write_config_with_models(monkeypatch, tmp_path, {"a": 10}, groups)
    rc = cli.run(
        ["check-llamaswap", "--config", str(config_path), "--vram-gb", "13.5", "--margin-gb", "1.5"]
    )
    assert rc == 0  # total == budget -> no es "> budget", así que cabe (borde inclusivo)


def test_check_llamaswap_no_groups_errors(tmp_path):
    config_path = tmp_path / "config.yaml"
    lc.dump_config({"models": {}}, config_path)
    rc = cli.run(["check-llamaswap", "--config", str(config_path), "--vram-gb", "16"])
    assert rc == 2


def test_check_llamaswap_missing_model_file_errors(tmp_path):
    groups = {"swap": {"swap": True, "members": ["ghost"]}}
    config_path = tmp_path / "config.yaml"
    lc.dump_config(
        {
            "models": {"ghost": {"cmd": f"llama-server --model {tmp_path / 'nope.gguf'}"}},
            "groups": groups,
        },
        config_path,
    )
    rc = cli.run(["check-llamaswap", "--config", str(config_path), "--vram-gb", "16"])
    assert rc == 2


# --- CLI init-llamaswap --------------------------------------------------------------------


def _base_config(monkeypatch, tmp_path) -> tuple[Path, dict]:
    gguf_r = tmp_path / "r.gguf"
    gguf_a = tmp_path / "a.gguf"
    _write_fake_gguf_with_size(monkeypatch, gguf_r, int(3 * GIB))
    _write_fake_gguf_with_size(monkeypatch, gguf_a, int(5 * GIB))
    models = {
        "gemma3-4b": {"cmd": f"llama-server --port 1 --model {gguf_r} -ngl 99"},
        "llama31-8b": {"cmd": f"llama-server --port 1 --model {gguf_a} -ngl 99"},
    }
    config_path = tmp_path / "config.yaml"
    lc.dump_config({"models": models}, config_path)
    return config_path, models


def test_init_llamaswap_writes_groups_and_ttl(monkeypatch, tmp_path):
    config_path, _ = _base_config(monkeypatch, tmp_path)
    rc = cli.run(
        [
            "init-llamaswap",
            "--config",
            str(config_path),
            "--resident",
            "gemma3-4b",
            "--swap",
            "llama31-8b",
            "--vram-gb",
            "16",
            "--force",
        ]
    )
    assert rc == 0
    data = lc.load_config(config_path)
    assert data["groups"]["resident"]["members"] == ["gemma3-4b"]
    assert data["groups"]["resident"]["persistent"] is True
    assert data["groups"]["swap"]["members"] == ["llama31-8b"]
    assert data["models"]["gemma3-4b"]["ttl"] == 600
    assert data["models"]["llama31-8b"]["ttl"] == 300


def test_init_llamaswap_refuses_overwrite_without_force(monkeypatch, tmp_path):
    config_path, _ = _base_config(monkeypatch, tmp_path)
    rc = cli.run(
        [
            "init-llamaswap",
            "--config",
            str(config_path),
            "--resident",
            "gemma3-4b",
            "--swap",
            "llama31-8b",
            "--vram-gb",
            "16",
        ]
    )
    assert rc == 2
    assert not (tmp_path / "config.yaml.bak").exists()


def test_init_llamaswap_force_creates_backup(monkeypatch, tmp_path):
    config_path, _ = _base_config(monkeypatch, tmp_path)
    original = config_path.read_text(encoding="utf-8")
    rc = cli.run(
        [
            "init-llamaswap",
            "--config",
            str(config_path),
            "--resident",
            "gemma3-4b",
            "--swap",
            "llama31-8b",
            "--vram-gb",
            "16",
            "--force",
        ]
    )
    assert rc == 0
    backup = config_path.with_suffix(config_path.suffix + ".bak")
    assert backup.read_text(encoding="utf-8") == original


def test_init_llamaswap_idempotent(monkeypatch, tmp_path):
    config_path, _ = _base_config(monkeypatch, tmp_path)
    argv = [
        "init-llamaswap",
        "--config",
        str(config_path),
        "--resident",
        "gemma3-4b",
        "--swap",
        "llama31-8b",
        "--vram-gb",
        "16",
        "--force",
    ]
    assert cli.run(argv) == 0
    first = config_path.read_text(encoding="utf-8")
    assert cli.run(argv) == 0
    second = config_path.read_text(encoding="utf-8")
    assert first == second


def test_init_llamaswap_dry_run_writes_nothing(monkeypatch, tmp_path):
    config_path, _ = _base_config(monkeypatch, tmp_path)
    before = config_path.read_text(encoding="utf-8")
    rc = cli.run(
        [
            "init-llamaswap",
            "--config",
            str(config_path),
            "--resident",
            "gemma3-4b",
            "--swap",
            "llama31-8b",
            "--vram-gb",
            "16",
            "--dry-run",
        ]
    )
    assert rc == 0
    assert config_path.read_text(encoding="utf-8") == before
    assert not (config_path.with_suffix(config_path.suffix + ".bak")).exists()


def test_init_llamaswap_add_model_creates_minimal_entry(monkeypatch, tmp_path):
    config_path, _ = _base_config(monkeypatch, tmp_path)
    new_gguf = tmp_path / "new.gguf"
    _write_fake_gguf_with_size(monkeypatch, new_gguf, int(2 * GIB))
    rc = cli.run(
        [
            "init-llamaswap",
            "--config",
            str(config_path),
            "--add-model",
            f"newmodel={new_gguf}",
            "--resident",
            "gemma3-4b",
            "--swap",
            "llama31-8b,newmodel",
            "--vram-gb",
            "16",
            "--force",
        ]
    )
    assert rc == 0
    data = lc.load_config(config_path)
    assert "newmodel" in data["models"]
    assert str(new_gguf) in data["models"]["newmodel"]["cmd"]


def test_init_llamaswap_vram_check_failure_writes_nothing(monkeypatch, tmp_path):
    config_path, _ = _base_config(monkeypatch, tmp_path)  # r=3GiB, a=5GiB
    original = config_path.read_text(encoding="utf-8")
    rc = cli.run(
        [
            "init-llamaswap",
            "--config",
            str(config_path),
            "--resident",
            "gemma3-4b",
            "--swap",
            "llama31-8b",
            "--vram-gb",
            "1",  # presupuesto absurdamente bajo -> debe fallar
            "--force",
        ]
    )
    assert rc == 1
    assert config_path.read_text(encoding="utf-8") == original
    assert not (config_path.with_suffix(config_path.suffix + ".bak")).exists()


def test_init_llamaswap_missing_model_id_errors(monkeypatch, tmp_path):
    config_path, _ = _base_config(monkeypatch, tmp_path)
    rc = cli.run(
        [
            "init-llamaswap",
            "--config",
            str(config_path),
            "--resident",
            "no-existe",
            "--vram-gb",
            "16",
        ]
    )
    assert rc == 2


def test_init_llamaswap_requires_resident_or_swap(monkeypatch, tmp_path):
    config_path, _ = _base_config(monkeypatch, tmp_path)
    rc = cli.run(["init-llamaswap", "--config", str(config_path), "--vram-gb", "16"])
    assert rc == 2


# --- guardrail de RAM (F7.9): --ram-gb en check-llamaswap / init-llamaswap ----------------


def test_check_llamaswap_ram_gb_not_passed_skips_ram_check(monkeypatch, tmp_path, capsys):
    # r=3GiB, a=5GiB -> RAM real (pesos) sería 3+5=8GiB si se sumaran (grupo swap real toma max
    # de VRAM, pero r+a como RAM del sistema en un budget bajo debería fallar SI se chequeara).
    groups = {"swap": {"swap": True, "members": ["a"]}}
    config_path = _write_config_with_models(monkeypatch, tmp_path, {"a": 10}, groups)
    rc = cli.run(["check-llamaswap", "--config", str(config_path), "--vram-gb", "16"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "--- RAM ---" not in out  # sin --ram-gb no se imprime ninguna sección de RAM


def test_check_llamaswap_ram_gb_fails_even_if_vram_ok(monkeypatch, tmp_path, capsys):
    groups = {"swap": {"swap": True, "members": ["a"]}}
    config_path = _write_config_with_models(monkeypatch, tmp_path, {"a": 4}, groups)
    # VRAM: 4*1.2=4.8 GiB, cabe holgado en 16 GiB. RAM (solo pesos, sin factor): 4 GiB, budget
    # de RAM absurdamente bajo -> debe fallar el chequeo de RAM aunque VRAM esté OK.
    rc = cli.run(
        [
            "check-llamaswap",
            "--config",
            str(config_path),
            "--vram-gb",
            "16",
            "--ram-gb",
            "1",
            "--ram-margin-gb",
            "0",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "VRAM OK" in out
    assert "RAM NO CABE" in out


def test_check_llamaswap_ram_gb_ok(monkeypatch, tmp_path, capsys):
    groups = {"swap": {"swap": True, "members": ["a"]}}
    config_path = _write_config_with_models(monkeypatch, tmp_path, {"a": 2}, groups)
    rc = cli.run(
        [
            "check-llamaswap",
            "--config",
            str(config_path),
            "--vram-gb",
            "16",
            "--ram-gb",
            "16",
            "--ram-margin-gb",
            "2",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "VRAM OK" in out
    assert "RAM OK" in out


def test_init_llamaswap_ram_check_failure_writes_nothing(monkeypatch, tmp_path):
    config_path, _ = _base_config(monkeypatch, tmp_path)  # r=3GiB, a=5GiB (pesos)
    original = config_path.read_text(encoding="utf-8")
    rc = cli.run(
        [
            "init-llamaswap",
            "--config",
            str(config_path),
            "--resident",
            "gemma3-4b",
            "--swap",
            "llama31-8b",
            "--vram-gb",
            "16",  # VRAM sobra
            "--ram-gb",
            "1",
            "--ram-margin-gb",
            "0",  # RAM absurdamente baja -> falla
            "--force",
        ]
    )
    assert rc == 1
    assert config_path.read_text(encoding="utf-8") == original
    assert not (config_path.with_suffix(config_path.suffix + ".bak")).exists()


def test_init_llamaswap_ram_gb_ok_writes_groups(monkeypatch, tmp_path):
    config_path, _ = _base_config(monkeypatch, tmp_path)
    rc = cli.run(
        [
            "init-llamaswap",
            "--config",
            str(config_path),
            "--resident",
            "gemma3-4b",
            "--swap",
            "llama31-8b",
            "--vram-gb",
            "16",
            "--ram-gb",
            "32",
            "--ram-margin-gb",
            "2",
            "--force",
        ]
    )
    assert rc == 0
    data = lc.load_config(config_path)
    assert "groups" in data
