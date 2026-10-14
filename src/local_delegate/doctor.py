"""doctor.py — diagnóstico de la instalación completa (subcomando ``doctor``).

Complementa a la tool MCP ``local_status`` (que mira el *runtime*: backend vivo, modelos,
VRAM/RAM) chequeando la *instalación*: el andamiaje en los clientes (hooks, skill, memoria y
entradas MCP), el daemon, y qué versiones de ``llama-server`` (llama.cpp) y ``llama-swap``
tienes instaladas respecto a las que esta release ha probado (``probes.RECOMMENDED_VERSIONS``).
Con ``--online`` consulta además la última release publicada en GitHub.

Qué se comprueba y cómo no lo decide este módulo: vive una sola vez en ``checks.CHECKS``, y
aquí solo se recorre y se imprime. Las sondas de versiones y del backend (``detect_*``,
``_compare_line``, los issues de GitHub, ``backend_probe``) viven en ``probes``, que no importa
ni este módulo ni ``checks``: así ``checks`` las usa sin importar ``doctor`` y no hay ciclo.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import checks, config, i18n, probes

# Encabezado de cada grupo del registro. El de `backend` se arma aparte porque su texto
# depende de --online, y es el que el usuario ya leía antes de que el doctor viera el resto.
#: Cabeceras de grupo, por su clave del catálogo (los ids de grupo no cambian con el idioma).
_GROUP_HEADINGS: dict[str, str] = {
    "environment": "doctor.group.environment",
    "scaffold": "doctor.group.scaffold",
    "service": "doctor.group.service",
}
#: Orígenes del idioma (REQ-018) → su rótulo del catálogo común (B0a).
_LANGUAGE_SOURCES = {
    "variable": "common.language.source.variable",
    "preference": "common.language.source.preference",
    "system": "common.language.source.system",
    "fallback": "common.language.source.fallback",
}
#: Avisos de la regla del idioma (`hook_common.resolve_language`) → su texto y su marcador.
_LANGUAGE_WARNINGS = {
    "invalid_variable": ("common.language.warning.invalid_variable", "value"),
    "invalid_preference": ("common.language.warning.invalid_preference", "path"),
    "unreadable_preference": ("common.language.warning.unreadable_preference", "path"),
}


def group_heading(group: str) -> str:
    """La cabecera de un grupo de checks en el idioma vigente (la usa también `install`)."""
    return i18n.t(_GROUP_HEADINGS[group])


def status_legend() -> str:
    """La leyenda de estados, armada con los mismos rótulos que las líneas de los checks."""
    return i18n.t(
        "doctor.legend",
        ok=checks.status_label(checks.OK),
        warn=checks.status_label(checks.WARN),
        missing=checks.status_label(checks.MISSING),
        unknown=checks.status_label(checks.UNKNOWN),
    )


def language_lines() -> list[str]:
    """REQ-019 y D11: el idioma de este proceso, su origen y el `language.json`, sus avisos y,
    si lo guardado vino de la variable, cómo volver a seguir al sistema. Es cabecera y no un check:
    no cambia el total de 25 ni el código de salida."""
    current = i18n.current()
    source = i18n.t(_LANGUAGE_SOURCES[current.source])
    lines = [
        i18n.t("doctor.language.line", lang=current.lang, source=source, path=current.pref_path)
    ]
    for code, detail in current.warnings:
        if code in _LANGUAGE_WARNINGS:
            text_key, field = _LANGUAGE_WARNINGS[code]
            lines.append(
                i18n.t("doctor.language.warning", detail=i18n.t(text_key, **{field: detail}))
            )
    if current.source == "preference" and current.stored_source == "variable":
        lines.append(i18n.t("doctor.language.follow_system", path=current.pref_path))
    return lines


def _versions_heading(online: bool) -> str:
    return i18n.t("doctor.header.versions_online" if online else "doctor.header.versions_offline")


def _print_group(group: str, results: list[tuple[checks.Check, checks.Result]]) -> None:
    for check, result in results:
        if check.group != group:
            continue
        print(f"  {checks.status_label(result.status)} {check.title}: {result.detail}")
        if result.fix_hint and checks.is_warning(result.status):
            # Sin caracteres fuera de cp1252: la consola de Windows revienta con una flecha
            # «→» y el diagnóstico moriría justo cuando más falta hace (algo está mal).
            print(i18n.t("doctor.fix_with", hint=result.fix_hint))


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

    print(i18n.t("doctor.title"))
    print()

    # Entorno
    exe = config.llamaswap_exe()
    backend_status = by_id["service.backend"].status
    # `unknown` aquí es el 401/403: el backend está arriba y falta la credencial. Llamarlo
    # CAÍDO manda a arrancar algo que ya corre.
    backend_word = i18n.t(
        {
            checks.OK: "doctor.backend.up",
            checks.UNKNOWN: "doctor.backend.up_rejects_credential",
        }.get(backend_status, "doctor.backend.down")
    )
    print(f"LLAMASWAP_EXE:    {exe or i18n.t('doctor.env.llamaswap_exe_unset')}")
    print(f"LLAMASWAP_CONFIG: {config_path or i18n.t('doctor.env.unset')}")
    print(i18n.t("doctor.env.backend", url=config.BASE_URL, state=backend_word))
    print(f"HOME:             {home}")
    for line in language_lines():
        print(line)
    print()
    print(status_legend())
    print()

    for group in _GROUP_HEADINGS:
        print(group_heading(group))
        _print_group(group, results)
        print()

    print(_versions_heading(online))
    _print_group("backend", results)

    if online:
        print()
        print(i18n.t("doctor.issues.heading"))
        for component in ("llama-swap", "llama-server"):
            issues = probes.recent_relevant_issues(component)
            if not issues:
                unknown = checks.status_label(checks.UNKNOWN)
                print(i18n.t("doctor.issues.none", status=unknown, component=component))
                continue
            for issue in issues:
                print(f"  [HOLD] {component} #{issue['number']}: {issue['title']} · {issue['url']}")

    warnings = sum(1 for _check, result in results if checks.is_warning(result.status))
    print()
    if warnings:
        print(
            i18n.t(
                "doctor.summary.warnings",
                n=i18n.format_number(warnings),
                missing=checks.status_label(checks.MISSING),
                warn=checks.status_label(checks.WARN),
            )
        )
        return 1
    print(i18n.t("doctor.summary.ok"))
    return 0
