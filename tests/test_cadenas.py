"""Tarea 27 de F3: las cadenas de respaldo por rol (REQ-003, REQ-004, REQ-014).

Lo que se fija aquí es la RESOLUCIÓN de la cadena con la configuración vigente, no el salto: quién
responde cuando falla el modelo principal es de la tarea 28. Una cadena es una lista ordenada de
modelos candidatos, ya sin repetidos, sin el propio modelo principal y solo con modelos del catálogo
de texto. Si la tarea 24 dijera que el residente no cabe al lado de un modelo grande, lo que cambia
es la configuración de esa máquina o la spec, no este código.

Defectos (REQ-004), con «residente» = el modelo del grupo `persistent` de llama-swap, o el mecánico:
- código  -> residente -> largo
- largo   -> residente -> código
- mecánico -> largo
- visión  -> ninguna
"""

from __future__ import annotations

import re
from pathlib import Path

from local_delegate import cadenas, checks, config
from local_delegate import llamaswap_config as lc

MECANICO = "gemma3-4b"
LARGO = "gemma4-26b-a4b"
CODIGO = "qwen36-35b-a3b"
#: El modelo del rol `fast`, retirado en la 0.30.0. Se conserva como caso de «esto ya NO está en el
#: catálogo», que es exactamente lo que pasó a ser.
RETIRADO = "qwen35-2b"


def _config_llamaswap(tmp_path: Path, grupos: dict) -> Path:
    ruta = tmp_path / "config.yaml"
    lc.dump_config({"models": {}, "groups": grupos}, ruta)
    return ruta


# --- Defectos ---------------------------------------------------------------------------------


def test_las_cadenas_por_defecto_son_las_de_la_spec(recargar_config):
    recargar_config()
    assert cadenas.resolver("code").modelos == (MECANICO, LARGO)
    assert cadenas.resolver("long").modelos == (MECANICO, CODIGO)
    assert cadenas.resolver("mechanical").modelos == (LARGO,)


def test_vision_no_tiene_cadena(recargar_config):
    """Visión queda fuera de `ALLOWED_MODELS` a propósito: su cadena se resuelve vacía ANTES."""
    recargar_config()
    assert cadenas.resolver("vision").modelos == ()


# --- El residente -----------------------------------------------------------------------------


def test_sin_config_de_llamaswap_el_residente_es_el_mecanico(recargar_config, monkeypatch):
    recargar_config()
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    modelo, origen = cadenas.residente()
    assert modelo == MECANICO
    assert "mecánico" in origen


def test_el_residente_sale_del_grupo_persistent(recargar_config, monkeypatch, tmp_path):
    recargar_config()
    ruta = _config_llamaswap(
        tmp_path,
        {
            "swap": {"swap": True, "members": [MECANICO, CODIGO]},
            "residente": {"persistent": True, "members": [LARGO]},
        },
    )
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(ruta))
    modelo, origen = cadenas.residente()
    assert modelo == LARGO
    assert "persistent" in origen and "residente" in origen
    # Discrimina de verdad: por defecto la cadena de `code` es (MECANICO, LARGO). Con el residente
    # en LARGO, el primer salto va a él y el segundo paso («long») repite, así que se queda en uno.
    assert cadenas.resolver("code").modelos == (LARGO,), "el primer salto va al residente"


def test_con_varios_miembros_gana_el_primero_del_catalogo(recargar_config, monkeypatch, tmp_path):
    recargar_config()
    ruta = _config_llamaswap(
        tmp_path, {"resident": {"persistent": True, "members": ["no-esta", RETIRADO, MECANICO]}}
    )
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(ruta))
    # Dos miembros que no están en el catálogo —uno inventado y el del rol retirado en la 0.30.0—
    # y gana el primero que sí está: el residente nunca puede ser un modelo que no se puede pedir.
    assert cadenas.residente()[0] == MECANICO


def test_sin_pyyaml_cae_al_mecanico_y_lo_dice(recargar_config, monkeypatch, tmp_path):
    """En esta máquina residente y mecánico son el mismo modelo: sin el origen no se distingue."""
    recargar_config()
    ruta = _config_llamaswap(tmp_path, {"resident": {"persistent": True, "members": [LARGO]}})
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(ruta))
    monkeypatch.setattr(lc, "yaml", None)
    modelo, origen = cadenas.residente()
    assert modelo == MECANICO
    assert "mecánico" in origen


def test_local_status_dice_el_residente_y_su_origen(recargar_config, monkeypatch):
    recargar_config()
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    lineas = "\n".join(cadenas.describir())
    assert MECANICO in lineas and "mecánico" in lineas
    assert "code" in lineas


# --- Sobrescribir -----------------------------------------------------------------------------


def test_una_cadena_se_sobrescribe_con_roles_y_modelos(recargar_config):
    recargar_config(LOCAL_DELEGATE_FALLBACK_CODE=f"long, {MECANICO}")
    assert cadenas.resolver("code").modelos == (LARGO, MECANICO)


def test_una_cadena_vacia_desactiva_el_respaldo_de_ese_rol(recargar_config):
    recargar_config(LOCAL_DELEGATE_FALLBACK_LONG="")
    assert cadenas.resolver("long").modelos == ()
    assert cadenas.resolver("code").modelos == (MECANICO, LARGO), "los demás roles no cambian"


def test_none_tambien_desactiva_porque_windows_no_guarda_variables_vacias(recargar_config):
    """En Windows fijar una variable a "" la BORRA: en el daemon real la cadena vacía no existe.

    `monkeypatch.setenv` sí guarda "" en el diccionario de Python, así que el test de arriba pasa
    igual y no lo habría destapado. `none` es la forma que funciona en las tres plataformas.
    """
    recargar_config(LOCAL_DELEGATE_FALLBACK_LONG="none")
    assert cadenas.resolver("long").modelos == ()
    assert cadenas.resolver("long").ignorados == ()


def test_un_modelo_desconocido_se_ignora_y_se_informa(recargar_config):
    recargar_config(LOCAL_DELEGATE_FALLBACK_CODE="long,modelo-que-no-existe")
    cadena = cadenas.resolver("code")
    assert cadena.modelos == (LARGO,)
    assert cadena.ignorados == ("modelo-que-no-existe",)


def test_los_repetidos_y_el_propio_modelo_se_quitan(recargar_config):
    """Largo y código consolidados en uno: ese modelo no se reintenta contra sí mismo."""
    recargar_config(LOCAL_DELEGATE_MODEL_CODE=LARGO)
    assert cadenas.resolver("long").modelos == (MECANICO,)
    assert cadenas.resolver("code").modelos == (MECANICO,)
    # Y los repetidos dentro de una misma cadena se quitan: «long,code,long» con los dos roles
    # consolidados en un modelo es tres veces el mismo candidato.
    recargar_config(
        LOCAL_DELEGATE_MODEL_CODE=LARGO, LOCAL_DELEGATE_FALLBACK_MECHANICAL="long,code,long"
    )
    assert cadenas.resolver("mechanical").modelos == (LARGO,)


# --- Variables (REQ-014) ----------------------------------------------------------------------


def test_el_respaldo_viene_encendido_con_dos_saltos(recargar_config):
    recargar_config()
    assert config.FALLBACK is True
    assert config.FALLBACK_MAX_HOPS == 2


def test_las_variables_nuevas_estan_en_el_inventario(recargar_config):
    recargar_config()
    for nombre in (
        "LOCAL_DELEGATE_FALLBACK",
        "LOCAL_DELEGATE_FALLBACK_MAX_HOPS",
        "LOCAL_DELEGATE_FALLBACK_MECHANICAL",
        "LOCAL_DELEGATE_FALLBACK_LONG",
        "LOCAL_DELEGATE_FALLBACK_CODE",
        "LOCAL_DELEGATE_FALLBACK_FAST",
        "LLAMASWAP_CONFIG",
        "LLAMASWAP_EXE",
        "LLAMASWAP_LISTEN",
        "LLAMASWAP_WATCH_CONFIG",
    ):
        assert nombre in config.VARIABLES_DE_ENTORNO, nombre


def test_nadie_fuera_de_config_lee_llamaswap_del_entorno():
    """Tres sitios leían `LLAMASWAP_CONFIG` con `os.environ` directo: dos fuentes para un dato.

    El guardián de `test_aislamiento_entorno.py` solo mira `config.py`, así que por ahí la suite
    volvía a heredar el entorno de la máquina.
    """
    paquete = Path(config.__file__).parent
    lectura_directa = re.compile(r"os\.environ[^\n]*LLAMASWAP_")
    culpables = [
        f"{ruta.name}:{numero}"
        for ruta in paquete.rglob("*.py")
        if ruta.name != "config.py"
        for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1)
        if lectura_directa.search(linea)
    ]
    assert culpables == []


# --- doctor -----------------------------------------------------------------------------------


def test_doctor_avisa_de_un_modelo_desconocido_en_una_cadena(recargar_config, tmp_path):
    recargar_config(LOCAL_DELEGATE_FALLBACK_CODE="long,modelo-que-no-existe")
    resultado = checks._probe_fallback(checks.Context(home=tmp_path))
    assert resultado.status == checks.WARN
    assert "modelo-que-no-existe" in resultado.detail
    assert "LOCAL_DELEGATE_FALLBACK_CODE" in resultado.detail


def test_doctor_no_avisa_con_las_cadenas_por_defecto(recargar_config, tmp_path):
    recargar_config()
    resultado = checks._probe_fallback(checks.Context(home=tmp_path))
    assert resultado.status == checks.OK


# El bloque «`fast` es inalcanzable desde las tools» se retiró con el rol (0.30.0): comprobaba que
# ninguna tool enrutaba a él, que era el argumento para quitarlo. Lo que queda por proteger —que su
# modelo ya no se pueda pedir a mano— vive en `test_rol_fast_retirado.py`.
