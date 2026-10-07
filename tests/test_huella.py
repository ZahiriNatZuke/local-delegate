"""La huella de un modelo cargado (REQ-010) y el lector de `cmd` que usa todo el paquete.

Los `cmd` de abajo copian la FORMA de los de la config real de llama-swap de hoy (2026-10-06):
plegados en varias lineas, con rutas de Windows, `--model` en vez de `-m` y `-ncmoe` en la forma
corta. Las rutas y las claves son falsas: ningun fixture del repo lleva una clave real. Ninguno de
los `cmd` reales usa `--n-cpu-moe`, asi que la forma larga se prueba con uno sintetico: sin el, un
lector que solo conociera la forma corta pasaria toda la suite.
"""

from __future__ import annotations

import hashlib

from local_delegate import huella as huella_mod

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
CMD_LARGO = (
    "llama-server --port ${PORT} --model /modelos/x.gguf --n-cpu-moe 20 --ctx-size 4096 "
    "--cache-type-k q8_0 --cache-type-v q4_0"
)


def test_lee_la_forma_corta_de_la_config_real():
    f = huella_mod.flags_del_cmd(CMD_26B)
    assert f["n_cpu_moe"] == 12
    assert f["ctx_size"] == 38400
    assert f["modelo"] == "D:\\modelos\\gemma4-26b-a4b\\gemma-4-26B-A4B-it-UD-IQ4_XS.gguf"
    assert f["reasoning"] == "off"
    assert f["mmproj"] is None

    q = huella_mod.flags_del_cmd(CMD_QWEN36)
    assert q["n_cpu_moe"] == 20
    assert q["ctx_size"] == 16384

    doce = huella_mod.flags_del_cmd(CMD_12B)
    assert doce["mmproj"] == "D:\\modelos\\gemma4-12b\\mmproj-F16.gguf"
    assert doce["n_cpu_moe"] is None


def test_lee_la_forma_larga():
    f = huella_mod.flags_del_cmd(CMD_LARGO)
    assert f["n_cpu_moe"] == 20
    assert f["ctx_size"] == 4096
    assert f["cache_type_k"] == "q8_0"
    assert f["cache_type_v"] == "q4_0"
    assert f["modelo"] == "/modelos/x.gguf"


def test_formas_cortas_de_cache_y_ctx_y_modelo():
    f = huella_mod.flags_del_cmd(
        "llama-server -m /m/y.gguf -c 2048 -ctk f16 -ctv q8_0 -mm /m/p.gguf"
    )
    assert (f["modelo"], f["ctx_size"], f["cache_type_k"], f["cache_type_v"], f["mmproj"]) == (
        "/m/y.gguf",
        2048,
        "f16",
        "q8_0",
        "/m/p.gguf",
    )


def test_flag_con_igual_comillas_y_valor_negativo():
    f = huella_mod.flags_del_cmd(
        'llama-server --model="D:\\mis modelos\\z.gguf" --n-cpu-moe=7 --reasoning-budget -1 '
        "--reasoning-format none"
    )
    assert f["modelo"] == "D:\\mis modelos\\z.gguf"
    assert f["n_cpu_moe"] == 7
    assert f["reasoning_budget"] == "-1"
    assert f["reasoning_format"] == "none"
    assert f["reasoning"] is None


def test_un_cmd_sin_flags_da_todas_las_claves_vacias():
    f = huella_mod.flags_del_cmd("llama-server")
    assert f["n_cpu_moe"] is None and f["ctx_size"] is None and f["modelo"] is None
    assert set(huella_mod.flags_del_cmd(CMD_26B)) >= set(f)


def test_el_ultimo_valor_gana():
    assert huella_mod.flags_del_cmd("x -ncmoe 4 -ncmoe 9")["n_cpu_moe"] == 9


def _cfg(cmd: str) -> dict:
    return {"cmd": cmd, "ttl": 120}


def test_dos_huellas_que_solo_difieren_en_ncmoe_son_distintas(tmp_path):
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"x" * 10)
    base = f"llama-server --model {gguf} --ctx-size 4096 -ncmoe 12"
    h1 = huella_mod.huella(_cfg(base), "Eres un asistente.")
    h2 = huella_mod.huella(_cfg(base.replace("-ncmoe 12", "-ncmoe 16")), "Eres un asistente.")
    assert h1["ruta"] == h2["ruta"] and h1["tamano_bytes"] == h2["tamano_bytes"] == 10
    assert h1["prompt_sha256"] == h2["prompt_sha256"]
    assert h1 != h2
    assert h1["flags"]["n_cpu_moe"] == 12 and h2["flags"]["n_cpu_moe"] == 16


def test_la_huella_cambia_con_el_prompt_el_tamano_y_la_ruta(tmp_path):
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"x" * 10)
    cfg = _cfg(f"llama-server --model {gguf}")
    base = huella_mod.huella(cfg, "uno")
    assert base["prompt_sha256"] == hashlib.sha256(b"uno").hexdigest()
    assert huella_mod.huella(cfg, "dos") != base
    gguf.write_bytes(b"x" * 11)
    assert huella_mod.huella(cfg, "uno")["tamano_bytes"] == 11
    otra = tmp_path / "otro.gguf"
    otra.write_bytes(b"x" * 11)
    assert huella_mod.huella(_cfg(f"llama-server --model {otra}"), "uno")["ruta"] == str(otra)


def test_un_gguf_que_no_existe_no_rompe_la_huella(tmp_path):
    h = huella_mod.huella(_cfg(f"llama-server --model {tmp_path / 'falta.gguf'}"), "p")
    assert h["tamano_bytes"] is None
    assert huella_mod.huella({}, "p")["ruta"] is None
