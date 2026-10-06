"""doctor.py — diagnóstico de la instalación completa (subcomando ``doctor``).

Complementa a la tool MCP ``local_status`` (que mira el *runtime*: backend vivo, modelos,
VRAM/RAM) chequeando la *instalación*: el andamiaje en los clientes (hooks, skill, memoria y
entradas MCP), el daemon, y qué versiones de ``llama-server`` (llama.cpp) y ``llama-swap``
tienes instaladas respecto a las que esta release ha probado (``sondas.RECOMMENDED_VERSIONS``).
Con ``--online`` consulta además la última release publicada en GitHub.

Qué se comprueba y cómo no lo decide este módulo: vive una sola vez en ``checks.CHECKS``, y
aquí solo se recorre y se imprime. Las sondas de versiones y del backend (``detect_*``,
``_compare_line``, los issues de GitHub, ``backend_probe``) viven en ``sondas``, que no importa
ni este módulo ni ``checks``: así ``checks`` las usa sin importar ``doctor`` y no hay ciclo.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import checks, config, sondas

# Encabezado de cada grupo del registro. El de `backend` se arma aparte porque su texto
# depende de --online, y es el que el usuario ya leía antes de que el doctor viera el resto.
_GROUP_HEADINGS: dict[str, str] = {
    "entorno": "Entorno (el CLI y los clientes):",
    "andamiaje": "Andamiaje (hooks, skill, memoria y entradas MCP):",
    "servicio": "Servicios:",
}


def _versions_heading(online: bool) -> str:
    if online:
        return "Versiones (instalada vs probada; consultando GitHub por la última)…"
    return "Versiones (instalada vs probada; usa --online para comparar con GitHub):"


def _print_group(group: str, results: list[tuple[checks.Check, checks.Result]]) -> None:
    for check, result in results:
        if check.group != group:
            continue
        print(f"  {checks.STATUS_LABEL[result.status]} {check.title}: {result.detail}")
        if result.fix_hint and checks.is_warning(result.status):
            # Sin caracteres fuera de cp1252: la consola de Windows revienta con una flecha
            # «→» y el diagnóstico moriría justo cuando más falta hace (algo está mal).
            print(f"         arréglalo con: {result.fix_hint}")


def run_doctor(args: argparse.Namespace) -> int:
    """Imprime el diagnóstico completo y devuelve exit code (0 sin avisos, 1 con al menos uno)."""
    config_path: Path | None = None
    if getattr(args, "config", None):
        config_path = Path(args.config)
    elif config.llamaswap_config_path():
        config_path = Path(config.llamaswap_config_path())

    home_arg = getattr(args, "home", None)
    home = Path(home_arg).expanduser() if home_arg else Path.home()
    online = bool(getattr(args, "online", False))

    # Los probes corren antes de imprimir: la cabecera necesita el resultado del backend y así
    # el estado se consulta una sola vez, no una por cada sitio donde se muestra.
    results = checks.run_all(
        checks.Context(home=home, config_path=config_path, online=online),
    )
    by_id = {check.id: result for check, result in results}

    print("local-delegate doctor — diagnóstico del andamiaje, los servicios y el backend local")
    print()

    # Entorno
    exe = config.llamaswap_exe()
    backend_status = by_id["service.backend"].status
    # `unknown` aquí es el 401/403: el backend está arriba y falta la credencial. Llamarlo
    # CAÍDO manda a arrancar algo que ya corre.
    backend_word = {
        checks.OK: "arriba",
        checks.UNKNOWN: "arriba (rechaza la credencial de este entorno)",
    }.get(backend_status, "CAÍDO")
    print(f"LLAMASWAP_EXE:    {exe or '(no seteado; se busca llama-swap en el PATH)'}")
    print(f"LLAMASWAP_CONFIG: {config_path or '(no seteado)'}")
    print(f"Backend BASE_URL: {config.BASE_URL} — {backend_word}")
    print(f"HOME:             {home}")
    print()
    print("Estados: [ OK ] a punto · [WARN] revisar · [FALT] falta · [ -- ] no se pudo comprobar")
    print()

    for group, heading in _GROUP_HEADINGS.items():
        print(heading)
        _print_group(group, results)
        print()

    print(_versions_heading(online))
    _print_group("backend", results)

    if online:
        print()
        print("Issues abiertos con señales de riesgo (revisión manual antes de canary):")
        for component in ("llama-swap", "llama-server"):
            issues = sondas.recent_relevant_issues(component)
            if not issues:
                print(
                    f"  [ -- ] {component}: ninguno detectado en los 30 actualizados más recientes"
                )
                continue
            for issue in issues:
                print(f"  [HOLD] {component} #{issue['number']}: {issue['title']} · {issue['url']}")

    warnings = sum(1 for _check, result in results if checks.is_warning(result.status))
    print()
    if warnings:
        print(f"Resultado: {warnings} aviso(s) — revisa [FALT] y [WARN] arriba.")
        return 1
    print("Resultado: todo a punto (andamiaje, servicios y versiones probadas).")
    return 0
