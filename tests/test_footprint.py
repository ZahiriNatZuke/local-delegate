"""La huella de un modelo cargado (REQ-010) y el lector de `cmd` que usa todo el paquete.

Los `cmd` de abajo copian la FORMA de los de la config real de llama-swap de hoy (2026-10-06):
plegados en varias lineas, con rutas de Windows, `--model` en vez de `-m` y `-ncmoe` en la forma
corta. Las rutas y las claves son falsas: ningun fixture del repo lleva una clave real. Ninguno de
los `cmd` reales usa `--n-cpu-moe`, asi que la forma larga se prueba con uno sintetico: sin el, un
lector que solo conociera la forma corta pasaria toda la suite.
"""

from __future__ import annotations

import hashlib

from local_delegate import footprint as footprint_mod

CMD_26B = (
    "D:\\llama\\llama-server.exe --port ${PORT} --host 127.0.0.1\n"
    "      --model D:\\modelos\\gemma4-26b-a4b\\gemma-4-26B-A4B-it-UD-IQ4_XS.gguf\n"
    "      --fit off -ngl 99 -ncmoe 12 --ctx-size 38400 --jinja --reasoning off\n"
    "      --load-mode mmap --cache-ram 1024 -np 1 --api-key clave-falsa-1\n\n"
)
CMD_QWEN36 = (
    "D:\\llama\\llama-server.exe --port ${PORT} --host 127.0.0.1\n"
    "      --model D:\\modelos\\qwen36-35b-a3b\\Qwen3.6-35B-A3B-UD-IQ4_XS.gguf\n"
    "      --fit off -ngl 99 -ncmoe 20 --ctx-size 16384 --jinja --reasoning off\n"
    "      --load-mode mmap --cache-ram 1024 -np 1\n\n"
)
CMD_12B = (
    "D:\\llama\\llama-server.exe --port ${PORT} --host 127.0.0.1\n"
    "      --model D:\\modelos\\gemma4-12b\\gemma-4-12b-it-Q4_K_M.gguf\n"
    "      --mmproj D:\\modelos\\gemma4-12b\\mmproj-F16.gguf\n"
    "      --fit off -ngl 99 --ctx-size 8192 --batch-size 2048 --ubatch-size 2048 --jinja\n"
    "      --reasoning off --load-mode mmap --cache-ram 1024 -np 1\n\n"
)
LONG_CMD = (
    "llama-server --port ${PORT} --model /modelos/x.gguf --n-cpu-moe 20 --ctx-size 4096 "
    "--cache-type-k q8_0 --cache-type-v q4_0"
)


def test_reads_short_form_of_real_config():
    f = footprint_mod.cmd_flags(CMD_26B)
    assert f["n_cpu_moe"] == 12
    assert f["ctx_size"] == 38400
    assert f["modelo"] == "D:\\modelos\\gemma4-26b-a4b\\gemma-4-26B-A4B-it-UD-IQ4_XS.gguf"
    assert f["reasoning"] == "off"
    assert f["mmproj"] is None

    q = footprint_mod.cmd_flags(CMD_QWEN36)
    assert q["n_cpu_moe"] == 20
    assert q["ctx_size"] == 16384

    twelve = footprint_mod.cmd_flags(CMD_12B)
    assert twelve["mmproj"] == "D:\\modelos\\gemma4-12b\\mmproj-F16.gguf"
    assert twelve["n_cpu_moe"] is None


def test_reads_long_form():
    f = footprint_mod.cmd_flags(LONG_CMD)
    assert f["n_cpu_moe"] == 20
    assert f["ctx_size"] == 4096
    assert f["cache_type_k"] == "q8_0"
    assert f["cache_type_v"] == "q4_0"
    assert f["modelo"] == "/modelos/x.gguf"


def test_short_forms_of_cache_ctx_and_model():
    f = footprint_mod.cmd_flags(
        "llama-server -m /m/y.gguf -c 2048 -ctk f16 -ctv q8_0 -mm /m/p.gguf"
    )
    assert (f["modelo"], f["ctx_size"], f["cache_type_k"], f["cache_type_v"], f["mmproj"]) == (
        "/m/y.gguf",
        2048,
        "f16",
        "q8_0",
        "/m/p.gguf",
    )


def test_flag_with_equals_quotes_and_negative_value():
    f = footprint_mod.cmd_flags(
        'llama-server --model="D:\\mis modelos\\z.gguf" --n-cpu-moe=7 --reasoning-budget -1 '
        "--reasoning-format none"
    )
    assert f["modelo"] == "D:\\mis modelos\\z.gguf"
    assert f["n_cpu_moe"] == 7
    assert f["reasoning_budget"] == "-1"
    assert f["reasoning_format"] == "none"
    assert f["reasoning"] is None


def test_cmd_without_flags_gives_all_empty_keys():
    f = footprint_mod.cmd_flags("llama-server")
    assert f["n_cpu_moe"] is None and f["ctx_size"] is None and f["modelo"] is None
    assert set(footprint_mod.cmd_flags(CMD_26B)) >= set(f)


def test_last_value_wins():
    assert footprint_mod.cmd_flags("x -ncmoe 4 -ncmoe 9")["n_cpu_moe"] == 9


def _cfg(cmd: str) -> dict:
    return {"cmd": cmd, "ttl": 120}


def test_two_footprints_differing_only_in_ncmoe_are_distinct(tmp_path):
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"x" * 10)
    base = f"llama-server --model {gguf} --ctx-size 4096 -ncmoe 12"
    h1 = footprint_mod.footprint(_cfg(base), "Eres un asistente.")
    h2 = footprint_mod.footprint(_cfg(base.replace("-ncmoe 12", "-ncmoe 16")), "Eres un asistente.")
    assert h1["ruta"] == h2["ruta"] and h1["tamano_bytes"] == h2["tamano_bytes"] == 10
    assert h1["prompt_sha256"] == h2["prompt_sha256"]
    assert h1 != h2
    assert h1["flags"]["n_cpu_moe"] == 12 and h2["flags"]["n_cpu_moe"] == 16


def test_footprint_changes_with_prompt_size_and_path(tmp_path):
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"x" * 10)
    cfg = _cfg(f"llama-server --model {gguf}")
    base = footprint_mod.footprint(cfg, "uno")
    assert base["prompt_sha256"] == hashlib.sha256(b"uno").hexdigest()
    assert footprint_mod.footprint(cfg, "dos") != base
    gguf.write_bytes(b"x" * 11)
    assert footprint_mod.footprint(cfg, "uno")["tamano_bytes"] == 11
    another = tmp_path / "otro.gguf"
    another.write_bytes(b"x" * 11)
    assert footprint_mod.footprint(_cfg(f"llama-server --model {another}"), "uno")["ruta"] == str(
        another
    )


def test_missing_gguf_does_not_break_footprint(tmp_path):
    h = footprint_mod.footprint(_cfg(f"llama-server --model {tmp_path / 'falta.gguf'}"), "p")
    assert h["tamano_bytes"] is None
    assert footprint_mod.footprint({}, "p")["ruta"] is None
