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

from . import backend_params, checks, config, i18n, probes

# Encabezado de cada grupo del registro. El de `backend` se arma aparte porque su texto
# depende de --online, y es el que el usuario ya leía antes de que el doctor viera el resto.
#: Cabeceras de grupo, por su clave del catálogo (los ids de grupo no cambian con el idioma).
_GROUP_HEADINGS: dict[str, str] = {
    "environment": "doctor.group.environment",
    "scaffold": "doctor.group.scaffold",
    "service": "doctor.group.service",
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
    no cambia el total de 25 ni el código de salida. Los datos salen de `i18n.language_report`, el
    mismo que usa `local_status` (B2a)."""
    report = i18n.language_report()
    lines = [
        i18n.t("doctor.language.line", lang=report.lang, source=report.source, path=report.path)
    ]
    lines.extend(i18n.t("doctor.language.warning", detail=detail) for detail in report.warnings)
    if report.follow_system:
        lines.append(i18n.t("doctor.language.follow_system", path=report.path))
    # REQ-028 (issue #260): el idioma de respuesta del modelo, con la misma regla que las tools.
    value, source, warning = i18n.response_language_lines()
    lines.append(i18n.t("doctor.language.response_line", value=value, source=source))
    if warning:
        lines.append(i18n.t("doctor.language.warning", detail=warning))
    return lines


def backend_params_lines() -> list[str]:
    """REQ-016/023 (SDD backend-extra-params, T9): the per-role backend parameters, as header lines.

    Not a check: it changes neither the 26 checks nor the exit code. It reads the file of this
    machine and `LOCAL_DELEGATE_BACKEND_PARAMS` of **this** shell, which may not be the daemon's,
    and says so. It repeats the warnings of `backend_params.report()` (context ones included).
    Values come only from accepted entries; a dropped entry shows its role, key and code, never its
    value. Without parameters, warnings or the variable, no line at all.
    """
    rows = [row for row in backend_params.report() if row.values or row.warnings]
    in_shell = config.backend_params_override().raw is not None
    if not rows and not in_shell:
        return []
    lines = [i18n.t("doctor.backend_params.line", path=backend_params.path())]
    if in_shell:
        lines.append(i18n.t("doctor.backend_params.env_in_shell"))
    for row in rows:
        if row.values:
            from_env = i18n.t("doctor.backend_params.from_env")
            params = ", ".join(
                f"{key}={backend_params.format_param_value(value)}"
                + (f" {from_env}" if row.source.get(key) == backend_params.SOURCE_ENV else "")
                for key, value in row.values.items()
            )
            lines.append(i18n.t("doctor.backend_params.role", role=row.role, params=params))
        lines.extend(
            i18n.t("doctor.backend_params.warning", detail=backend_params.warning_text(warning))
            for warning in row.warnings
        )
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
    for line in backend_params_lines():
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
