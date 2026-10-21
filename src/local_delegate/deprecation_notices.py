"""El aviso para personas de un nombre obsoleto, en el idioma vigente (frente B, ola B1a).

Vive aparte de `deprecations` por el grafo de imports: `config` importa `deprecations` (lee las
variables con alias) e `i18n` importa `config`, así que si `deprecations` importara `i18n` habría
un ciclo `config → deprecations → i18n → config`. La tabla de nombres se queda en `deprecations`,
sin texto; la redacción, aquí.
"""

from __future__ import annotations

from . import i18n
from .deprecations import UNRELEASED, DeprecatedName, removal_version


def warning_text(entry: DeprecatedName) -> str:
    """El aviso de un nombre obsoleto: nombra el viejo, el nuevo y la versión de retirada.

    Un retirado con sucesor aún sin publicar (`UNRELEASED`) usa su propia clave, sin versión, para
    no imprimir nunca «UNRELEASED» (el mismo motivo que `cli.deprecations.removed_later`).
    """
    if entry.is_retired:
        if entry.new is None:
            return i18n.t("cli.deprecations.retired", old=entry.old, version=entry.introduced)
        if entry.introduced == UNRELEASED:
            return i18n.t(
                "cli.deprecations.retired_renamed_unreleased", old=entry.old, new=entry.new
            )
        return i18n.t(
            "cli.deprecations.retired_renamed",
            old=entry.old,
            new=entry.new,
            version=entry.introduced,
        )
    removal = removal_version(entry)
    if removal:
        when = i18n.t("cli.deprecations.removed_in", version=removal)
    else:
        when = i18n.t("cli.deprecations.removed_later")
    return i18n.t("cli.deprecations.deprecated", old=entry.old, new=entry.new, when=when)
