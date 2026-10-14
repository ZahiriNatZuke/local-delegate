"""El aviso para personas de un nombre obsoleto, en el idioma vigente (frente B, ola B1a).

Vive aparte de `deprecations` por el grafo de imports: `config` importa `deprecations` (lee las
variables con alias) e `i18n` importa `config`, así que si `deprecations` importara `i18n` habría
un ciclo `config → deprecations → i18n → config`. La tabla de nombres se queda en `deprecations`,
sin texto; la redacción, aquí.
"""

from __future__ import annotations

from . import i18n
from .deprecations import DeprecatedName, removal_version


def warning_text(entry: DeprecatedName) -> str:
    """El aviso de un nombre obsoleto: nombra el viejo, el nuevo y la versión de retirada."""
    if entry.is_retired:
        return i18n.t("cli.deprecations.retired", old=entry.old, version=entry.introduced)
    removal = removal_version(entry)
    if removal:
        when = i18n.t("cli.deprecations.removed_in", version=removal)
    else:
        when = i18n.t("cli.deprecations.removed_later")
    return i18n.t("cli.deprecations.deprecated", old=entry.old, new=entry.new, when=when)
