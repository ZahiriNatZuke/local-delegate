"""cli.py — subcomandos de línea de comandos de local-delegate.

Ver docs/recipes/llama-swap-groups.md y docs/wiki/Daemon.md. El binario ``local-delegate`` SIN
argumentos sigue arrancando el servidor MCP stdio exactamente igual que siempre (ver
``entrypoint.main()``, que es quien despacha: está por encima de este módulo y de ``server``, y
por eso ``server`` ya no importa el CLI); este módulo se importa en cuanto hay **algún** argumento, y su parser es el
único sitio donde está escrito qué subcomandos existen: ``--help`` y los nombres inválidos los
responde él, no una lista aparte. Solo los comandos de configuración de llama-swap requieren el
extra ``[llamaswap]`` (``pip install "local-delegate-mcp[llamaswap]"``); ``serve`` usa
dependencias base.

El chequeo de RAM de sistema (``--ram-gb``) es OPCIONAL en ambos comandos: si no se pasa, el
comportamiento es idéntico al de antes de F7.9 (solo VRAM) — compatibilidad hacia atrás con
0.4.0. Motivo del chequeo de RAM: llama-server mapea el GGUF también en RAM (mmap) aunque el
cómputo sea 100% GPU, así que un catálogo que cabe holgado en VRAM puede igual agotar la RAM
del sistema (verificado en vivo: 8.37 GiB de archivo -> ~7.46 GB de RAM residente real).
"""

from __future__ import annotations

import argparse
import contextlib
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

from . import benchmark, doctor, i18n
from . import llamaswap_config as lc
from .i18n import t
from .version import get_version

# `agents` va al final y **no** entra por defecto: su flag es `--agents` (store_true),
# mientras que los otros cuatro se excluyen con `--no-*`. Ver el porqué en el parser.
_ALL_COMPONENTS = ("hooks", "skill", "memory", "mcp", "agents")
_ALL_TARGETS = ("claude", "codex", "opencode")
# Solo para el mensaje de «no se encontró ninguno». El de opencode se escribe con `~/.config`
# aunque `install.opencode_dir` pueda resolver otra cosa con `XDG_CONFIG_HOME`: es texto de ayuda
# y la ruta real la dice el reporte del andamiaje, que sí sale de la función.
_CLIENT_DIR = {
    "claude": "~/.claude",
    "codex": "~/.codex",
    "opencode": "~/.config/opencode",
}

# El reporte final de `install` mira SOLO estos dos grupos del registro. Los otros dos
# —`service` y `backend`— salen a la red y lanzan los binarios de llama-swap, y haber
# instalado unos hooks no es motivo para nada de eso.
_SCAFFOLD_GROUPS = ("environment", "scaffold")


def cmd_serve(args: argparse.Namespace) -> int:
    """Arranca el daemon singleton MCP HTTP + dashboard."""
    from . import daemon

    return daemon.serve(host=args.host, port=args.port, log_level=args.log_level)


def _resolve_clients(args: argparse.Namespace, home: Path) -> tuple[set[str], str]:
    """(clientes a configurar, por qué esos). Lanza ValueError si la petición es contradictoria.

    `--clients` es el flag actual y `--target` el histórico; combinarlos no tiene una lectura
    obvia (¿unión? ¿cuál gana?), así que se rechaza en vez de elegir una a espaldas del usuario.
    """
    from . import install as inst

    clients = getattr(args, "clients", None)
    target = getattr(args, "target", None)
    if clients and target:
        raise ValueError(t("cli.install.clients_and_target"))

    if target:  # semántica histórica intacta: `all` fuerza los dos, existan o no
        chosen = set(_ALL_TARGETS) if "all" in target else set(target)
        return chosen, t("cli.install.clients_by_target", clients=", ".join(sorted(chosen)))

    explicit = {c for c in (clients or []) if c != "auto"}
    if explicit:
        # Pedir un cliente por su nombre es una orden, no una sugerencia: se configura aunque no
        # esté instalado (caso legítimo, p. ej. preparar el HOME antes de instalar el cliente).
        return explicit, t("cli.install.clients_by_clients", clients=", ".join(sorted(explicit)))

    present = inst.present_targets(home)
    if present:
        return present, t("cli.install.clients_auto", clients=", ".join(sorted(present)))
    return present, t("cli.install.clients_auto_none")


def _install_options(args: argparse.Namespace, targets: set[str], skip_codex_mcp: bool = False):
    from . import install as inst

    home = Path(args.home).expanduser() if args.home else Path.home()
    components = {c for c in _ALL_COMPONENTS if getattr(args, c.replace("-", "_"))}
    return inst.Options(
        home=home,
        components=components,
        targets=targets,
        python_exe=args.python or inst.default_python(),
        enable_read_hook=getattr(args, "enable_read_hook", False),
        mcp_mode=getattr(args, "mcp_mode", "stdio"),
        base_url=getattr(args, "base_url", None),
        api_key_env=getattr(args, "api_key_env", False),
        web_token_env=getattr(args, "web_token_env", None),
        pin_version=getattr(args, "pin_version", None),
        # El HOME simulado apaga el camino por CLI, y no es una precaución teórica: `claude mcp
        # add-json --scope user` escribe SIEMPRE en el `~/.claude.json` del usuario real,
        # ignorando `--home`. Instalando duplicaba configuración; desinstalando la borraba.
        use_cli=not getattr(args, "no_client_cli", False) and not inst.is_simulated_home(home),
        skip_codex_mcp=skip_codex_mcp,
    )


def _has_terminal() -> bool:
    """True si se puede preguntar de verdad. Un stdin raro NO es una terminal."""
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        # stdin cerrado, redirigido o un objeto sin `isatty` usable: no hay a quién preguntar.
        return False


def _codex_mcp_set_by_hand(results) -> str:
    """Ruta del `config.toml` con una entrada nuestra escrita a mano, o "" si no la hay.

    El `warn` de `scaffold.mcp_codex` significa exactamente eso: la sección existe **sin** los
    marcadores gestionados, o sea la escribió el usuario. Reemplazarla sin avisar es el fallo
    contra el que existe la regla de `unknown` en todo el registro.
    """
    from . import checks

    for check, result in results:
        if check.id == "scaffold.mcp_codex" and result.status == checks.WARN:
            return result.detail
    return ""


def _decide_on_foreign_codex(detail: str, args: argparse.Namespace) -> bool:
    """True si hay que SALTAR la escritura de la entrada MCP de Codex."""
    if getattr(args, "force_mcp_codex", False):
        print(t("cli.install.foreign_codex.notice", detail=detail))
        print(t("cli.install.foreign_codex.forced"))
        return False
    if args.dry_run:
        print(t("cli.install.foreign_codex.notice", detail=detail))
        print(t("cli.install.foreign_codex.dry_run"))
        return False
    if not _has_terminal():
        print(t("cli.install.foreign_codex.notice", detail=detail))
        print(t("cli.install.foreign_codex.no_terminal"))
        print(t("cli.install.foreign_codex.how_to_force"))
        return True
    print(t("cli.install.foreign_codex.notice", detail=detail))
    try:
        response = input(t("cli.install.foreign_codex.question")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        response = ""
    if response in ("s", "si", "sí", "y", "yes"):
        return False
    print(t("cli.install.foreign_codex.kept"))
    return True


def _scaffold_report(home: Path, dry_run: bool) -> None:
    """Estado real tras escribir, con el mismo formato y los mismos checks que el doctor.

    Se recorre el registro **otra vez** a propósito: la primera pasada describe el sistema como
    estaba ANTES de escribir, y un reporte que use esos resultados diría lo contrario de lo que
    afirma. Es barato — estos dos grupos solo miran ficheros y el PATH.
    """
    from . import checks, doctor

    # `SKIP_PYPI` por el mismo motivo que el filtro por grupos: haber instalado unos hooks no es
    # motivo para salir a la red. La comprobación aparece igual en el reporte, como `[ -- ]`.
    results = checks.run_all(
        checks.Context(home=home, latest_release=checks.SKIP_PYPI), groups=_SCAFFOLD_GROUPS
    )
    print()
    if dry_run:
        print(t("cli.install.report.current_state"))
    else:
        print(t("cli.install.report.state_after"))
    print(t("cli.install.report.status_legend"))
    for group in _SCAFFOLD_GROUPS:
        print()
        print(doctor._GROUP_HEADINGS[group])
        doctor._print_group(group, results)


def _run_install(args: argparse.Namespace, uninstall: bool) -> int:
    from . import checks
    from . import install as inst

    home = Path(args.home).expanduser() if args.home else Path.home()
    try:
        targets, reason = _resolve_clients(args, home)
    except ValueError as exc:
        print(t("cli.error", detail=exc), file=sys.stderr)
        return 2

    print(t("cli.install.uninstalling" if uninstall else "cli.install.installing", home=home))
    print(t("cli.install.clients", reason=reason))

    if not targets:
        # Con `auto` y ningún cliente, no hay nada que hacer y casi siempre significa un --home
        # equivocado. No es un error: no se escribe nada, se dice qué se buscó y se sigue.
        print()
        joiner = f" {t('cli.and')} "
        print(t("cli.install.no_client.searched", dirs=joiner.join(_CLIENT_DIR.values())))
        print(t("cli.install.no_client.nothing_written", home=home))
        print(t("cli.install.no_client.hint"))
        _scaffold_report(home, dry_run=True)
        return 0

    # Primera pasada del registro: para saber si hay configuración del usuario que no se puede
    # pisar sin preguntar. Solo hace falta cuando de verdad vamos a escribir la entrada de Codex.
    skip_codex_mcp = False
    if not uninstall and "codex" in targets and getattr(args, "mcp", True):
        detail = _codex_mcp_set_by_hand(
            checks.run_all(checks.Context(home=home), groups=("scaffold",))
        )
        if detail:
            skip_codex_mcp = _decide_on_foreign_codex(detail, args)

    opts = _install_options(args, targets, skip_codex_mcp=skip_codex_mcp)
    if not opts.components:
        print(t("cli.install.no_component"), file=sys.stderr)
        return 2
    actions = inst.plan_uninstall(opts) if uninstall else inst.plan_install(opts)
    print(t("cli.install.components", components=", ".join(sorted(opts.components))))
    print()
    failures = inst.apply(actions, dry_run=args.dry_run)
    print()
    if args.dry_run:
        print(t("cli.install.dry_run"))
        _scaffold_report(opts.home, dry_run=True)
        return 0
    if not uninstall and not failures:
        print(t("cli.install.done"))
        _warn_if_cli_not_on_path()
        _leave_daemon_up(opts)
    # El reporte va ANTES del código de salida, y también cuando algo falló: si una acción no
    # pudo escribir, saber qué quedó a medias es justo lo que hace falta para arreglarlo.
    # Es informativo y NO cambia el exit code — tras un install correcto quedan avisos legítimos
    # (el CLI fuera del PATH con `uvx`, un cliente ausente) y devolver 1 por eso rompería
    # cualquier script de instalación.
    _scaffold_report(opts.home, dry_run=False)
    if failures:
        print(t("cli.install.failures", n=failures), file=sys.stderr)
        return 1
    return 0


def _leave_daemon_up(opts) -> None:
    """Tras instalar en modo HTTP, el daemon tiene que existir: la entrada MCP apunta a él.

    Con `stdio` no se toca nada, porque ahí quien arranca el MCP es el propio cliente vía
    `uvx`. Y con un HOME simulado tampoco: se acaba de escribir en un árbol de pruebas, y
    reiniciar el servicio real de la máquina por eso sería un efecto sorpresa.
    """
    from . import update as upd

    if opts.mcp_mode != "http":
        return
    update_opts = upd.Options(home=opts.home)
    if update_opts.simulated_home:
        print(t("cli.install.simulated_home"))
        return
    print()
    upd.restart_daemon(update_opts)


def _warn_if_cli_not_on_path() -> None:
    """Avisa si el comando que toda la documentación manda usar no existe en esta máquina.

    Pasa siempre que se instala con `uvx`, que es lo que recomienda el README: `uvx` monta un
    entorno efímero, corre el comando y lo borra. El andamiaje queda perfecto y `local-delegate
    doctor` —lo primero que dice la doc después de instalar— responde «command not found».
    Decirlo aquí es barato; que lo descubra el usuario, no.
    """
    from . import checks

    if shutil.which("local-delegate"):
        return
    print()
    print(t("cli.install.not_on_path.title"))
    print(t("cli.install.not_on_path.why"))
    print(t("cli.install.not_on_path.hint", hint=checks.CLI_HINT))


def _update_options(args: argparse.Namespace):
    from . import update as upd

    return upd.Options(
        home=Path(args.home).expanduser() if args.home else Path.home(),
        dry_run=args.dry_run,
        version=args.version,
        restart_backend=args.restart_backend,
        no_restart=args.no_restart,
    )


def cmd_update(args: argparse.Namespace) -> int:
    from . import update as upd

    return upd.run_update(_update_options(args))


def cmd_install(args: argparse.Namespace) -> int:
    return _run_install(args, uninstall=False)


def _warn_deprecated(old: str) -> None:
    """Aviso en `stderr` por un nombre viejo del CLI: nombra el nuevo y la versión de retirada."""
    from . import deprecations

    entry = deprecations.find(old)
    if entry is not None:
        print(t("cli.warning", detail=deprecations.warning_text(entry)), file=sys.stderr)


def _resolve_reset_calibration(args: argparse.Namespace) -> str | None:
    """`--reset-calibration` o su alias oculto `--reiniciar-calibracion` (REQ-001).

    Si llegan los dos con valores distintos no hay lectura obvia, así que se rechaza, como
    `--clients`/`--target`.
    """
    new = getattr(args, "reset_calibration", None)
    old = getattr(args, "legacy_reset_calibration", None)
    if old is None:
        return new
    _warn_deprecated("--reiniciar-calibracion")
    if new is not None and new != old:
        raise ValueError(t("cli.recompute_cost.reset_mismatch"))
    return old


def cmd_recompute_cost(args: argparse.Namespace) -> int:
    """`recompute-cost` (coste-api-y-cuota, REQ-070): escribe solo en el directorio de logs."""
    from . import config, recompute

    try:
        reset = _resolve_reset_calibration(args)
    except ValueError as exc:
        print(t("cli.error", detail=exc), file=sys.stderr)
        return 2
    claude_dir = Path(args.claude_dir) if args.claude_dir else Path.home() / ".claude"
    try:
        summary = recompute.run(claude_dir, config.LOG_DIR, reset=reset)
    except OSError as e:
        print(t("cli.recompute_cost.cannot_write", reason=e.strerror))
        return 1
    print(recompute.summary_text(summary))
    return 0


def cmd_recompute_cost_legacy(args: argparse.Namespace) -> int:
    """`recalcular-coste`, alias oculto de `recompute-cost`: mismo handler, con aviso."""
    _warn_deprecated("recalcular-coste")
    return cmd_recompute_cost(args)


def _count_rows_by_window(log_dir: Path, windows) -> dict[str, int]:
    """Cuántas filas del log de uso estampa cada ventana (la primera por inicio, como `cost.merge`)."""
    import json

    from . import config

    counts: dict[str, int] = {}
    # Los mismos ficheros que lee el panel: los rotados por mes y el log de nombre fijo, si existe.
    paths = sorted(log_dir.glob("usage-*.jsonl"))
    fixed = config.USAGE_LOG
    if fixed.is_file() and fixed.resolve() not in {r.resolve() for r in paths}:
        paths.append(fixed)
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            window = windows.find(row.get("ts")) if isinstance(row, dict) else None
            if window:
                counts[window] = counts.get(window, 0) + 1
    return counts


def cmd_test_window(args: argparse.Namespace) -> int:
    """`test-window` (test-windows-out-of-metrics, REQ-006 a REQ-010): marca las pruebas en vivo."""
    import json

    from . import config
    from . import test_windows as tw

    log_dir = config.LOG_DIR
    action = args.test_window_command
    try:
        if action == "start":
            w = tw.start(log_dir, args.label or "")
            print(w.id)
            return 0
        if action == "stop":
            w = tw.stop(log_dir, args.id)
            print(
                t(
                    "cli.test_window.stopped",
                    id=w.id,
                    start=tw.format_instant(w.start),
                    end=tw.format_instant(w.end),
                )
            )
            return 0
        if action == "add":
            w, created = tw.add(log_dir, args.start, args.end, args.label or "")
            if created:
                print(t("cli.test_window.added", id=w.id))
            else:
                print(t("cli.test_window.already_there", id=w.id))
            return 0
    except tw.TestWindowError as e:
        print(f"test-window: {e}", file=sys.stderr)
        return 2

    windows = tw.load(log_dir)
    rows = _count_rows_by_window(log_dir, windows)
    if args.json:
        data = {
            "file": str(tw.path_for(log_dir)),
            "error": windows.error,
            "ignored": windows.ignored,
            "windows": [{**w.to_json(), "rows": rows.get(w.id, 0)} for w in windows.windows],
        }
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if windows.error:
        print(t("cli.test_window.unreadable", path=tw.path_for(log_dir), error=windows.error))
        return 0
    if not windows.windows:
        print(t("cli.test_window.none"))
    for w in windows.windows:
        end = tw.format_instant(w.end) if w.end is not None else t("cli.test_window.open")
        label = f"  {w.label}" if w.label else ""
        print(
            t(
                "cli.test_window.row",
                id=w.id,
                start=tw.format_instant(w.start),
                end=end,
                rows=i18n.format_number(rows.get(w.id, 0)),
                label=label,
            )
        )
    if windows.ignored:
        print(t("cli.test_window.ignored", n=windows.ignored))
    return 0


def _add_test_window_parser(sub) -> None:
    tw_parser = sub.add_parser(
        "test-window",
        help=t("cli.help.test_window"),
    )
    twsub = tw_parser.add_subparsers(dest="test_window_command", required=True)
    start = twsub.add_parser("start", help=t("cli.help.test_window.start"))
    start.add_argument("--label", default="", help=t("cli.help.test_window.label"))
    stop = twsub.add_parser("stop", help=t("cli.help.test_window.stop"))
    stop.add_argument("id", nargs="?", default=None, help=t("cli.help.test_window.stop.id"))
    add = twsub.add_parser("add", help=t("cli.help.test_window.add"))
    add.add_argument("start", help=t("cli.help.test_window.add.start"))
    add.add_argument("end", help=t("cli.help.test_window.add.end"))
    add.add_argument("--label", default="", help=t("cli.help.test_window.label"))
    lst = twsub.add_parser("list", help=t("cli.help.test_window.list"))
    lst.add_argument("--json", action="store_true", help=t("cli.help.json"))
    tw_parser.set_defaults(func=cmd_test_window)


def cmd_uninstall(args: argparse.Namespace) -> int:
    return _run_install(args, uninstall=True)


def _print_breakdown(
    title: str,
    total_gb: float,
    breakdown: list[lc.GroupContribution],
    estimates: dict[str, lc.ResourceEstimate],
    budget_gb: float,
    margin_gb: float,
) -> None:
    budget = budget_gb - margin_gb
    print(f"--- {title} ---")
    print(
        t(
            "cli.budget.available",
            budget=i18n.format_number(budget_gb, 2),
            margin=i18n.format_number(margin_gb, 2),
            available=i18n.format_number(budget, 2),
        )
    )
    print()
    for gc in breakdown:
        mode = t("cli.budget.mode.swap" if gc.swap else "cli.budget.mode.together")
        print(
            t(
                "cli.budget.group",
                group=gc.group,
                mode=mode,
                gb=i18n.format_number(gc.contribution_gb, 2),
            )
        )
        for m in gc.members:
            est = estimates.get(m)
            if est is None or est.error:
                error = est.error if est else t("cli.budget.no_estimate")
                print(t("cli.budget.member_error", model=m, error=error))
            else:
                print(
                    t(
                        "cli.budget.member",
                        model=m,
                        gb=i18n.format_number(est.gb, 2),
                        method=est.method,
                        detail=est.detail,
                    )
                )
    print()
    print(t("cli.budget.worst_case", title=title, gb=i18n.format_number(total_gb, 2)))


def _estimate_all(
    groups: dict, models: dict, overrides: dict[str, float], estimator
) -> dict[str, lc.ResourceEstimate]:
    member_ids: set[str] = set()
    for g in groups.values():
        if isinstance(g, dict):
            member_ids.update(g.get("members", []))
    estimates: dict[str, lc.ResourceEstimate] = {}
    for mid in member_ids:
        entry = models.get(mid)
        if entry is None:
            estimates[mid] = lc.ResourceEstimate(
                mid, 0.0, "error", "", error=t("cli.budget.model_not_in_models", model=mid)
            )
            continue
        estimates[mid] = estimator(mid, entry, override_gb=overrides.get(mid))
    return estimates


def _ungrouped_models(groups: dict, models: dict) -> list[str]:
    """Modelos invocables que el presupuesto de groups dejaría fuera."""
    grouped: set[str] = set()
    for group in groups.values():
        if isinstance(group, dict):
            grouped.update(m for m in group.get("members", []) if isinstance(m, str))
    return sorted(set(models) - grouped)


def _reject_ungrouped(groups: dict, models: dict, allow: bool) -> bool:
    ungrouped = _ungrouped_models(groups, models)
    if not ungrouped:
        return False
    detail = t("cli.budget.ungrouped", models=", ".join(ungrouped))
    print(t("cli.warning" if allow else "cli.error", detail=detail), file=sys.stderr)
    if not allow:
        print(t("cli.budget.ungrouped_hint"), file=sys.stderr)
    return not allow


def _check_budget(
    label: str,
    groups: dict,
    models: dict,
    overrides: dict[str, float],
    estimator,
    budget_gb: float,
    margin_gb: float,
) -> tuple[bool, list[str]]:
    """Corre un chequeo de presupuesto (VRAM o RAM), imprime el desglose, y avisa el resultado.

    Devuelve (cabe, errores). 'cabe' es False también si hubo errores de estimación (no se
    puede afirmar que cabe sin poder estimar todos los miembros).
    """
    estimates = _estimate_all(groups, models, overrides, estimator)
    total_gb, breakdown = lc.worst_case_gb(groups, estimates)
    _print_breakdown(label, total_gb, breakdown, estimates, budget_gb, margin_gb)
    errored = sorted(m for m, e in estimates.items() if e.error)
    if errored:
        print()
        print(
            t("cli.budget.cannot_estimate", label=label, models=", ".join(errored)),
            file=sys.stderr,
        )
        return False, errored
    budget = budget_gb - margin_gb
    print()
    if total_gb > budget:
        print(
            t(
                "cli.budget.does_not_fit",
                label=label,
                total=i18n.format_number(total_gb, 2),
                available=i18n.format_number(budget, 2),
            )
        )
        return False, []
    print(t("cli.budget.fits", label=label, extra=i18n.format_number(budget - total_gb, 2)))
    return True, []


def cmd_check_llamaswap(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    try:
        data = lc.load_config(config_path)
    except RuntimeError as e:
        print(t("cli.error", detail=e), file=sys.stderr)
        return 2

    groups = data.get("groups")
    if not groups:
        print(t("cli.check_llamaswap.no_groups", path=config_path), file=sys.stderr)
        return 2

    models = data.get("models", {})
    if _reject_ungrouped(groups, models, args.allow_ungrouped):
        return 2
    vram_ok, vram_errors = _check_budget(
        "VRAM", groups, models, {}, lc.estimate_model_vram, args.vram_gb, args.margin_gb
    )
    if vram_errors:
        return 2

    ram_ok = True
    if args.ram_gb is not None:
        print()
        ram_ok, ram_errors = _check_budget(
            "RAM", groups, models, {}, lc.estimate_model_ram, args.ram_gb, args.ram_margin_gb
        )
        if ram_errors:
            return 2

    return 0 if (vram_ok and ram_ok) else 1


def _parse_add_model(spec: str) -> tuple[str, str, float | None]:
    if "=" not in spec:
        raise argparse.ArgumentTypeError(t("cli.init_llamaswap.bad_add_model", spec=repr(spec)))
    model_id, rest = spec.split("=", 1)
    if ":" in rest:
        path_part, vram_part = rest.rsplit(":", 1)
        try:
            return model_id, path_part, float(vram_part)
        except ValueError:
            pass  # el ':' era parte de la ruta (p. ej. 'C:\...'), no un sufijo de VRAM
    return model_id, rest, None


def cmd_init_llamaswap(args: argparse.Namespace) -> int:
    resident = [m.strip() for m in args.resident.split(",") if m.strip()]
    swap = [m.strip() for m in args.swap.split(",") if m.strip()]
    if not resident and not swap:
        print(t("cli.init_llamaswap.needs_resident_or_swap"), file=sys.stderr)
        return 2
    overlap = set(resident) & set(swap)
    if overlap:
        print(
            t("cli.init_llamaswap.overlap", models=", ".join(sorted(overlap))),
            file=sys.stderr,
        )
        return 2

    config_path = Path(args.config)
    out_path = Path(args.out) if args.out else config_path
    try:
        data = lc.load_config(config_path)
    except RuntimeError as e:
        print(t("cli.error", detail=e), file=sys.stderr)
        return 2
    models = data.setdefault("models", {})

    overrides: dict[str, float] = {}
    for spec in args.add_model or []:
        model_id, gguf_path, vram = _parse_add_model(spec)
        if model_id in models:
            print(
                t("cli.init_llamaswap.model_exists", model=model_id, path=config_path),
                file=sys.stderr,
            )
            return 2
        models[model_id] = {
            "cmd": f"{args.server_exe} --port ${{PORT}} --host 127.0.0.1 --model {gguf_path} -ngl 99"
        }
        if vram is not None:
            overrides[model_id] = vram

    missing = sorted(m for m in resident + swap if m not in models)
    if missing:
        print(t("cli.init_llamaswap.missing_models", models=", ".join(missing)), file=sys.stderr)
        return 2

    for m in resident:
        models[m]["ttl"] = args.ttl_resident
    for m in swap:
        models[m]["ttl"] = args.ttl_swap

    groups: dict[str, dict] = {}
    if resident:
        groups["resident"] = {
            "persistent": True,
            "swap": False,
            "exclusive": False,
            "members": resident,
        }
    if swap:
        groups["swap"] = {"swap": True, "exclusive": False, "members": swap}
    if _reject_ungrouped(groups, models, args.allow_ungrouped):
        print(t("cli.init_llamaswap.nothing_written"), file=sys.stderr)
        return 2
    data["groups"] = groups

    # #898: persistir las métricas de actividad de llama-swap en SQLite (si no, son in-memory y
    # se pierden al reiniciar). Habilita el panel "Rendimiento del backend" del dashboard.
    if args.store_path:
        data["store"] = {"path": args.store_path}

    vram_ok, vram_errors = _check_budget(
        "VRAM", groups, models, overrides, lc.estimate_model_vram, args.vram_gb, args.margin_gb
    )
    if vram_errors:
        print(t("cli.init_llamaswap.nothing_written"), file=sys.stderr)
        return 2

    ram_ok = True
    if args.ram_gb is not None:
        print()
        ram_ok, ram_errors = _check_budget(
            "RAM", groups, models, overrides, lc.estimate_model_ram, args.ram_gb, args.ram_margin_gb
        )
        if ram_errors:
            print(t("cli.init_llamaswap.nothing_written"), file=sys.stderr)
            return 2

    if not (vram_ok and ram_ok):
        print()
        print(t("cli.init_llamaswap.does_not_fit"))
        return 1

    if args.dry_run:
        print()
        print(t("cli.init_llamaswap.dry_run"))
        print()
        print(lc.dump_config_str(data))
        return 0

    if out_path.exists() and not args.force:
        print()
        print(
            t("cli.init_llamaswap.out_exists", path=out_path),
            file=sys.stderr,
        )
        return 2
    if out_path.exists() and args.force:
        # REQ-035: la copia lleva fecha y no pisa ninguna anterior, como la de `residency`.
        from . import residency

        backup = residency.dated_copy(out_path)
        print()
        print(f"backup: {backup}")

    lc.dump_config(data, out_path)
    print(t("cli.written", path=out_path))
    return 0


# --- llamaswap residency (T11: REQ-029 a REQ-033, REQ-038; T13: REQ-034, REQ-039) -------------
#
# Antes de escribir, la comprobación previa de REQ-034 (delegaciones propias, peticiones en vuelo
# de cualquier cliente, modelos en `/running`): por el daemon, que tiene la key; si no responde,
# directo con la key del shell; si tampoco, «no se sabe». Con `--now` se escribe igual. La vigía de
# la recarga se abre ANTES de escribir y dice cuál de las cuatro salidas hubo.


def _daemon_target() -> tuple[str, int, dict[str, str]]:
    """Host, puerto y cabecera con que el CLI pregunta al daemon: los mismos que usa `doctor`.

    Función aparte para que la suite la apunte a un puerto muerto (`conftest.real_daemon_down`).
    """
    from . import checks, config

    host, port = checks.daemon_host_port()
    return host, port, config.web_auth_headers()


def _daemon_url() -> str:
    host, port, _header = _daemon_target()
    return f"http://{host}:{port}"


def _daemon_path(answer=None) -> Path | None:
    """La config que usa el daemon, por su endpoint de REQ-039. `None` si no contesta.

    Con `answer` (lo que ya devolvió `_daemon_status`) no se vuelve a preguntar: una escritura sin
    `--config` hace UNA sola consulta del estado, que sirve para la ruta y para las negativas.
    """
    status, _why = answer if answer is not None else _daemon_status()
    if status is None or not status.config_path:
        return None
    return Path(status.config_path)


def _config_path(args: argparse.Namespace):
    """`(ruta, respuesta del daemon)`: `--config`, si no `LLAMASWAP_CONFIG`, si no la del daemon.

    La respuesta del daemon solo viene si hubo que preguntarle; la reutiliza la escritura.
    """
    from . import config

    if args.config:
        return Path(args.config), None
    from_env = config.llamaswap_config_path()
    if from_env:
        return Path(from_env).expanduser(), None
    answer = _daemon_status()
    return _daemon_path(answer), answer


def _pairs(values: list[str], option: str, kind) -> dict[str, float]:
    pair_items = {}
    for value in values:
        model, same, figure = value.partition("=")
        try:
            if not same or not model:
                raise ValueError
            pair_items[model.strip()] = kind(figure.strip().replace(",", "."))
        except ValueError:
            raise ValueError(
                t("cli.residency.bad_pair", option=option, value=repr(value))
            ) from None
    return pair_items


def _daemon_status():
    """`(estado, por qué no)` preguntando al daemon (REQ-039, punto 1), con plazo propio.

    El plazo importa: con el limitador de hilos del daemon agotado, la conexión se acepta y la
    respuesta no llega nunca, y el CLI no puede quedarse colgado esperando (T13). Y no son 2 s:
    con llama-swap caído el daemon tarda ~2,1 s en saberlo (un puerto cerrado en Windows).
    """
    import httpx2

    from . import llamaswap_api

    _host, _port, headers = _daemon_target()
    try:
        response = httpx2.get(
            f"{_daemon_url()}/api/llamaswap/status",
            headers=headers,
            timeout=llamaswap_api.CLI_TO_DAEMON,
        )
    except httpx2.TimeoutException:
        return None, t("cli.daemon.timeout")
    except httpx2.HTTPError:
        return None, t("cli.daemon.no_answer")
    if response.status_code != 200:
        return None, t("cli.daemon.status_code", code=response.status_code)
    try:
        return llamaswap_api.Status.from_json(response.json()), ""
    except (ValueError, llamaswap_api.QueryError):
        return None, t("cli.daemon.bad_status")


def _llamaswap_status(daemon_answer=None):
    """REQ-039: `(origen, estado, por qué no se sabe)`. Por el daemon; si no responde, directo
    contra llama-swap con la key del shell; si tampoco, «no se sabe». Nunca pide la key."""
    from . import config, llamaswap_api, server

    status, why = daemon_answer if daemon_answer is not None else _daemon_status()
    if status is not None:
        return "daemon", status, ""
    if not config.API_KEY:
        return "", None, t("cli.residency.no_credential", why=why)
    status = llamaswap_api.query_status(
        llamaswap_api.local_backend(), own_delegations=len(server.inflight_snapshot())
    )
    if status.llamaswap == llamaswap_api.STATE_UNKNOWN:
        return "", None, t("cli.residency.llamaswap_does_not_say", why=why, detail=status.detail)
    return "direct", status, ""


def _daemon_watch(watch_id: str):
    """Espera la salida de una vigía abierta en el daemon, preguntando cada medio segundo."""
    import time

    import httpx2

    from . import llamaswap_api

    _host, _port, headers = _daemon_target()
    deadline = time.monotonic() + llamaswap_api.WATCH_TOTAL_S + 5
    while time.monotonic() < deadline:
        try:
            response = httpx2.get(
                f"{_daemon_url()}/api/llamaswap/watch/{watch_id}",
                headers=headers,
                timeout=llamaswap_api.CLI_TO_DAEMON,
            )
            data = response.json() if response.status_code == 200 else {}
        except (httpx2.HTTPError, ValueError):
            data = {}
        outcome = data.get("outcome") if isinstance(data, dict) else None
        if outcome in llamaswap_api.OUTCOME_TEXT:
            return outcome, str(data.get("line") or "")
        time.sleep(llamaswap_api.WATCH_POLL_S)
    return llamaswap_api.UNRESOLVED, t("cli.watch.late")


def _open_watch(origin: str, why: str):
    """Abre la vigía ANTES de escribir (REQ-034). `(esperar, abandonar, por qué no)`.

    `esperar()` devuelve `(salida, línea de llama-swap)`; `abandonar()` la suelta sin esperar (no
    se llegó a escribir). Sin vigía, los dos son `None` y el tercero dice por qué.
    """
    import httpx2

    from . import llamaswap_api

    if origin == "daemon":
        _host, _port, headers = _daemon_target()
        try:
            response = httpx2.post(
                f"{_daemon_url()}/api/llamaswap/watch",
                headers=headers,
                timeout=llamaswap_api.CLI_TO_DAEMON_WATCH,
            )
            data = response.json()
        except (httpx2.HTTPError, ValueError) as e:
            return None, None, t("cli.watch.daemon_did_not_open", reason=type(e).__name__)
        watch_id = data.get("id") if isinstance(data, dict) else None
        if response.status_code != 200 or not isinstance(watch_id, str):
            error = data.get("error") if isinstance(data, dict) else None
            return (
                None,
                None,
                t("cli.watch.daemon_did_not_open", reason=error or response.status_code),
            )
        # En el daemon, una vigía abandonada acaba sola («no vigila» a los 10 s, o lo que vea).
        return (lambda: _daemon_watch(watch_id)), (lambda: None), ""
    if origin == "direct":
        watcher = llamaswap_api.Watcher(llamaswap_api.local_backend())
        try:
            watcher.open()
        except (llamaswap_api.QueryError, httpx2.HTTPError) as e:
            return None, None, t("cli.watch.could_not_open", reason=e or type(e).__name__)
        return (lambda: (watcher.wait(), watcher.line)), watcher.close, ""
    return None, None, why


def _restore_after_rejection(path: Path, previous: bytes) -> Path:
    """REQ-034, «rechazó»: vuelve a la config que sigue corriendo, por el camino de REQ-038 (valida
    la copia, copia el fichero actual y reemplaza de forma atómica). Devuelve la copia del
    rechazado, para que no se pierda."""
    from . import residency

    residency.validate_copy(previous)
    rejected_copy = residency.dated_copy(path)
    residency.atomic_replace(path, previous)
    return rejected_copy


def _report_outcome(outcome: str, line: str, path: Path, previous: bytes, status, origin) -> int:
    """El mensaje de cada una de las cuatro salidas de REQ-034 (y de «sin resolver»)."""
    from . import llamaswap_api, residency

    text = llamaswap_api.OUTCOME_TEXT[outcome]
    if outcome == llamaswap_api.RELOADED:
        print(t("cli.outcome.reloaded", outcome=text, line=line))
        return 0
    if outcome == llamaswap_api.REJECTED:
        print(t("cli.outcome.rejected", outcome=text, line=line), file=sys.stderr)
        print(t("cli.outcome.restoring"), file=sys.stderr)
        # La segunda recarga también se vigila: se abre antes de restaurar, como la primera.
        wait_again, abandon_again, why_not = _open_watch(origin, "")
        try:
            rejected_copy = _restore_after_rejection(path, previous)
        except (residency.ResidencyError, OSError) as e:
            if abandon_again is not None:
                abandon_again()
            print(t("cli.outcome.restore_failed", error=e), file=sys.stderr)
            return 1
        print(t("cli.outcome.restored", path=path, copy=rejected_copy), file=sys.stderr)
        if wait_again is None:
            print(t("cli.outcome.restored_unconfirmed", reason=why_not))
            return 1
        outcome_again, line_again = wait_again()
        print(
            t(
                "cli.outcome.restored_reload",
                outcome=llamaswap_api.OUTCOME_TEXT[outcome_again],
                line=line_again,
            ),
            file=sys.stderr,
        )
        return 1
    if outcome == llamaswap_api.NOT_WATCHING:
        message = t("cli.outcome.not_watching", outcome=text, line=line)
        if status is not None and status.autostart and not status.watch_config:
            message += t("cli.outcome.not_watching_hint")
        print(message)
        return 0
    if outcome == llamaswap_api.DOWN:
        print(t("cli.outcome.down", outcome=text, line=line))
        return 0
    print(t("cli.outcome.other", outcome=text, line=line))
    return 0


def _write_residency(
    args: argparse.Namespace, path: Path, new: bytes, original: bytes, daemon_answer=None
) -> int:
    """Escribe `new` si el fichero sigue siendo `original` (los bytes sobre los que se decidió).

    Antes, las negativas de REQ-034 (salvo `--now`) y la vigía, que se abre ANTES de comparar el
    fichero: abrirla tarda (hasta 8 s por el daemon) y comparar antes dejaría una ventana en la que
    un cambio ajeno se pisaría. Sin vigía tampoco se escribe, salvo `--now`: no se escribe a ciegas.
    T2 (d) midió que una recarga de v255 corta las peticiones en curso aunque su modelo no cambie
    (502 a los ~1,8 s): el aviso no se suaviza y la negativa se queda.
    """
    from . import llamaswap_api, residency

    origin, status, why = _llamaswap_status(daemon_answer)
    if status is None:
        reasons = [f"{residency.UNKNOWN} ({why})"]
    else:
        reasons = llamaswap_api.refusals(status)
    if reasons and not args.now:
        print(t("cli.residency.refused", reasons="; ".join(reasons)), file=sys.stderr)
        return 2
    wait, abandon, why_no_watch = _open_watch(origin, why)
    if wait is None and not args.now:
        print(t("cli.residency.cannot_watch", reason=why_no_watch), file=sys.stderr)
        return 2
    # Actualización perdida: si alguien cambió el fichero desde que se leyó, escribir pisaría su
    # cambio con una edición calculada sobre los bytes viejos. Se compara tras abrir la vigía.
    current = path.read_bytes()
    if current != original:
        if abandon is not None:
            abandon()
        print(t("cli.error", detail=residency.CHANGE_DURING_EDIT), file=sys.stderr)
        return 2
    print(t("cli.residency.about_to_reload"))
    copy = residency.dated_copy(path, current)
    residency.atomic_replace(path, new)
    print(t("cli.copy", path=copy))
    print(t("cli.written", path=path))
    if reasons:
        print(t("cli.residency.written_with_now", reasons="; ".join(reasons)))
    if wait is None:
        print(t("cli.residency.reload_unconfirmed", reason=why_no_watch))
        return 0
    print(
        t("cli.residency.waiting", seconds=i18n.format_number(llamaswap_api.WATCH_TOTAL_S)),
        flush=True,
    )
    outcome, line = wait()
    return _report_outcome(outcome, line, path, current, status, origin)


def cmd_llamaswap_residency(args: argparse.Namespace) -> int:
    from . import residency, topology

    path, daemon_answer = _config_path(args)
    if path is None:
        print(t("cli.residency.unknown_config"), file=sys.stderr)
        return 2
    try:
        ttls = {m: int(s) for m, s in _pairs(args.ttl, "--ttl", int).items()}
        model_vram = _pairs(args.vram_model, "--vram-model", float)
    except ValueError as e:
        print(t("cli.error", detail=e), file=sys.stderr)
        return 2
    if (args.pin or args.restore) and ttls:
        print(t("cli.residency.ttl_with_pin_or_restore"), file=sys.stderr)
        return 2
    try:
        if args.restore:
            copy = Path(args.restore).read_bytes()
            residency.validate_copy(copy)
            original = path.read_bytes()
            if args.dry_run:
                print(t("cli.residency.dry_run_restore", path=args.restore))
                print("\n".join(residency.hidden_diff(original, copy)))
                return 0
            return _write_residency(args, path, copy, original, daemon_answer)
        loaded_one = residency.load(path)
        snapshot = loaded_one.snapshot
        if isinstance(snapshot, topology.NoTopology):
            detail = f": {snapshot.detail}" if snapshot.detail else ""
            print(
                t("cli.residency.unreadable", reason=snapshot.reason, detail=detail),
                file=sys.stderr,
            )
            return 2
        warning = ""
        if args.none:
            changes = residency.plan_none(loaded_one.data, snapshot, ttls, args.group)
        elif args.pin:
            if args.vram_gb is None:
                print(t("cli.residency.pin_needs_vram"), file=sys.stderr)
                return 2
            changes, warning = residency.plan_pin(
                loaded_one.data, snapshot, args.pin, args.vram_gb, args.reserve_gb, model_vram
            )
        elif ttls:
            changes = residency.plan_ttl(ttls, loaded_one.data, snapshot)
        else:
            print(residency.view(snapshot, loaded_one.data).text())
            return 0
        if not changes:
            print(t("cli.residency.nothing_to_change"))
            return 0
        new, diff = residency.edit_with_diff(loaded_one.original, changes)
    except residency.ResidencyError as e:
        print(t("cli.error", detail=e), file=sys.stderr)
        return 2
    except OSError as e:
        print(t("cli.error", detail=e), file=sys.stderr)
        return 2
    if warning:
        print(t("cli.warning", detail=warning))
    if args.dry_run:
        print(t("cli.residency.dry_run"))
        print("\n".join(diff))
        return 0
    try:
        return _write_residency(args, path, new, loaded_one.original, daemon_answer)
    except (residency.ResidencyError, OSError) as e:
        print(t("cli.error", detail=e), file=sys.stderr)
        return 2


def _add_llamaswap_parser(sub) -> None:
    llamaswap = sub.add_parser(
        "llamaswap",
        help=t("cli.help.llamaswap"),
    )
    lsub = llamaswap.add_subparsers(dest="llamaswap_command", required=True)
    res = lsub.add_parser(
        "residency",
        help=t("cli.help.llamaswap.residency"),
        description=t("cli.help.llamaswap.residency._description"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    res.add_argument("--config", default=None, help=t("cli.help.llamaswap.residency.config"))
    action = res.add_mutually_exclusive_group()
    action.add_argument(
        "--none",
        action="store_true",
        help=t("cli.help.llamaswap.residency.none"),
    )
    action.add_argument(
        "--pin",
        metavar="MODEL",
        default=None,
        help=t("cli.help.llamaswap.residency.pin"),
    )
    action.add_argument(
        "--restore", metavar="BAK", default=None, help=t("cli.help.llamaswap.residency.restore")
    )
    res.add_argument(
        "--ttl",
        action="append",
        default=[],
        metavar="MODEL=SECONDS",
        help=t("cli.help.llamaswap.residency.ttl"),
    )
    res.add_argument("--group", default=None, help=t("cli.help.llamaswap.residency.group"))
    res.add_argument(
        "--vram-gb", type=float, default=None, help=t("cli.help.llamaswap.residency.vram_gb")
    )
    res.add_argument(
        "--reserve-gb",
        type=float,
        default=2.0,
        help=t("cli.help.llamaswap.residency.reserve_gb"),
    )
    res.add_argument(
        "--vram-model",
        action="append",
        default=[],
        metavar="ID=GiB",
        help=t("cli.help.llamaswap.residency.vram_model"),
    )
    res.add_argument(
        "--dry-run", action="store_true", help=t("cli.help.llamaswap.residency.dry_run")
    )
    res.add_argument(
        "--now",
        action="store_true",
        help=t("cli.help.llamaswap.residency.now"),
    )
    res.set_defaults(func=cmd_llamaswap_residency)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-delegate",
        description=t("cli.help._description"),
    )
    # `local-delegate --version` salía con código 2 y un `usage`: el parser raíz exigía subcomando
    # y no exponía la bandera, así que la única forma de saber qué versión estaba instalada era
    # preguntarle a `pip`/`uv`. En un proyecto donde dos checks del diagnóstico comparan la versión
    # instalada con la publicada, que el propio binario no supiera decir la suya era el hueco raro.
    #
    # Sale de `version.get_version()`, la misma fuente que el handshake `initialize` del MCP y que
    # `__version__`: tres canales públicos que no pueden discrepar porque solo hay un dato. Ese
    # módulo es hoja a propósito — `cli` importando `server` cerraría un ciclo, porque
    # `server.main()` importa `cli` en cuanto hay argumentos.
    parser.add_argument(
        "--version",
        action="version",
        version=f"local-delegate {get_version()}",
        help=t("cli.help.version"),
    )

    sub = parser.add_subparsers(dest="command", required=True)

    benchmark.add_parser(sub)

    check = sub.add_parser(
        "check-llamaswap",
        help=t("cli.help.check_llamaswap"),
    )
    check.add_argument("--config", required=True, help=t("cli.help.check_llamaswap.config"))
    check.add_argument(
        "--vram-gb", required=True, type=float, help=t("cli.help.llamaswap_budget.vram_gb")
    )
    check.add_argument(
        "--margin-gb",
        type=float,
        default=1.5,
        help=t("cli.help.llamaswap_budget.margin_gb"),
    )
    check.add_argument(
        "--ram-gb",
        type=float,
        default=None,
        help=t("cli.help.llamaswap_budget.ram_gb"),
    )
    check.add_argument(
        "--ram-margin-gb",
        type=float,
        default=2.0,
        help=t("cli.help.llamaswap_budget.ram_margin_gb"),
    )
    check.add_argument(
        "--allow-ungrouped",
        action="store_true",
        help=t("cli.help.check_llamaswap.allow_ungrouped"),
    )
    check.set_defaults(func=cmd_check_llamaswap)

    init = sub.add_parser(
        "init-llamaswap",
        help=t("cli.help.init_llamaswap"),
    )
    init.add_argument(
        "--config",
        required=True,
        help=t("cli.help.init_llamaswap.config"),
    )
    init.add_argument("--out", help=t("cli.help.init_llamaswap.out"))
    init.add_argument(
        "--resident",
        default="",
        help=t("cli.help.init_llamaswap.resident"),
    )
    init.add_argument("--swap", default="", help=t("cli.help.init_llamaswap.swap"))
    init.add_argument(
        "--add-model",
        action="append",
        metavar=t("cli.help.init_llamaswap.add_model_metavar"),
        help=t("cli.help.init_llamaswap.add_model"),
    )
    init.add_argument(
        "--server-exe",
        default="llama-server",
        help=t("cli.help.init_llamaswap.server_exe"),
    )
    init.add_argument(
        "--ttl-resident",
        type=int,
        default=0,
        help=t("cli.help.init_llamaswap.ttl_resident"),
    )
    init.add_argument(
        "--ttl-swap", type=int, default=300, help=t("cli.help.init_llamaswap.ttl_swap")
    )
    init.add_argument(
        "--vram-gb", required=True, type=float, help=t("cli.help.llamaswap_budget.vram_gb")
    )
    init.add_argument(
        "--margin-gb",
        type=float,
        default=1.5,
        help=t("cli.help.llamaswap_budget.margin_gb"),
    )
    init.add_argument(
        "--ram-gb",
        type=float,
        default=None,
        help=t("cli.help.llamaswap_budget.ram_gb"),
    )
    init.add_argument(
        "--ram-margin-gb",
        type=float,
        default=2.0,
        help=t("cli.help.llamaswap_budget.ram_margin_gb"),
    )
    init.add_argument(
        "--store-path",
        default=None,
        help=t("cli.help.init_llamaswap.store_path"),
    )
    init.add_argument(
        "--force",
        action="store_true",
        help=t("cli.help.init_llamaswap.force"),
    )
    init.add_argument("--dry-run", action="store_true", help=t("cli.help.init_llamaswap.dry_run"))
    init.add_argument(
        "--allow-ungrouped",
        action="store_true",
        help=t("cli.help.init_llamaswap.allow_ungrouped"),
    )
    init.set_defaults(func=cmd_init_llamaswap)

    _add_llamaswap_parser(sub)

    doc = sub.add_parser(
        "doctor",
        help=t("cli.help.doctor"),
    )
    doc.add_argument(
        "--config",
        default=None,
        help=t("cli.help.doctor.config"),
    )
    doc.add_argument(
        "--online",
        action="store_true",
        help=t("cli.help.doctor.online"),
    )
    doc.add_argument(
        "--home",
        default=None,
        help=t("cli.help.doctor.home"),
    )
    doc.set_defaults(func=doctor.run_doctor)

    serve = sub.add_parser(
        "serve",
        help=t("cli.help.serve"),
    )
    serve.add_argument("--host", default=None, help=t("cli.help.serve.host"))
    serve.add_argument("--port", type=int, default=None, help=t("cli.help.serve.port"))
    serve.add_argument(
        "--log-level",
        choices=("critical", "error", "warning", "info", "debug"),
        default="warning",
        help=t("cli.help.serve.log_level"),
    )
    serve.set_defaults(func=cmd_serve)

    recalc = sub.add_parser(
        "recompute-cost",
        help=t("cli.help.recompute_cost"),
    )
    _add_recompute_cost_args(recalc)
    recalc.set_defaults(func=cmd_recompute_cost)
    # Nombre viejo (REQ-001): sin `help`, argparse no lo lista en la ayuda; avisa al usarse.
    legacy = sub.add_parser("recalcular-coste")
    _add_recompute_cost_args(legacy)
    legacy.set_defaults(func=cmd_recompute_cost_legacy)

    _add_test_window_parser(sub)

    _add_install_parsers(sub)
    # Sin `metavar`, argparse pinta en el `usage` todos los subcomandos, ocultos incluidos.
    sub.metavar = "{" + ",".join(n for n in sub.choices if n not in _HIDDEN_COMMANDS) + "}"
    return parser


# Subcomandos que siguen funcionando pero no salen en la ayuda (alias de `deprecations`).
_HIDDEN_COMMANDS = frozenset({"recalcular-coste"})


def _add_recompute_cost_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--reset-calibration",
        choices=("five_hour", "seven_day"),
        default=None,
        help=t("cli.help.recompute_cost.reset_calibration"),
    )
    # Nombre viejo (REQ-001), oculto en la ayuda; `_resolve_reset_calibration` avisa al usarlo.
    p.add_argument(
        "--reiniciar-calibracion",
        dest="legacy_reset_calibration",
        choices=("five_hour", "seven_day"),
        default=None,
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--claude-dir",
        default=None,
        help=t("cli.help.recompute_cost.claude_dir"),
    )


def _add_common_install_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--clients",
        action="append",
        choices=("auto", "claude", "codex", "opencode"),
        default=None,
        help=t("cli.help.install_common.clients"),
    )
    p.add_argument(
        "--target",
        action="append",
        choices=("claude", "codex", "opencode", "all"),
        default=None,
        help=t("cli.help.install_common.target"),
    )
    p.add_argument("--home", default=None, help=t("cli.help.install_common.home"))
    p.add_argument("--dry-run", action="store_true", help=t("cli.help.install_common.dry_run"))
    p.add_argument(
        "--python",
        default=None,
        help=t("cli.help.install_common.python"),
    )
    p.add_argument(
        "--no-hooks", dest="hooks", action="store_false", help=t("cli.help.install_common.no_hooks")
    )
    p.add_argument(
        "--no-skill",
        dest="skill",
        action="store_false",
        help=t("cli.help.install_common.no_skill"),
    )
    p.add_argument(
        "--no-memory",
        dest="memory",
        action="store_false",
        help=t("cli.help.install_common.no_memory"),
    )
    p.add_argument(
        "--no-mcp",
        dest="mcp",
        action="store_false",
        help=t("cli.help.install_common.no_mcp"),
    )
    # El único componente que se pide, en vez de excluirse: los subagentes son ficheros del
    # usuario, no andamiaje nuestro, así que tocarlos sin que lo pida sería el mismo error que
    # el viejo `--target all` creando `~/.codex/` en máquinas sin Codex.
    p.add_argument(
        "--agents",
        dest="agents",
        action="store_true",
        help=t("cli.help.install_common.agents"),
    )
    p.add_argument(
        "--no-client-cli",
        action="store_true",
        help=t("cli.help.install_common.no_client_cli"),
    )
    p.set_defaults(hooks=True, skill=True, memory=True, mcp=True)


def _add_install_parsers(sub) -> None:
    install = sub.add_parser(
        "install",
        help=t("cli.help.install"),
        description=t("cli.help.install._description"),
    )
    _add_common_install_args(install)
    install.add_argument(
        "--enable-read-hook",
        action="store_true",
        help=t("cli.help.install.enable_read_hook"),
    )
    install.add_argument(
        "--mcp-mode",
        choices=("stdio", "http"),
        default="stdio",
        help=t("cli.help.install.mcp_mode"),
    )
    install.add_argument(
        "--base-url",
        default=None,
        help=t("cli.help.install.base_url"),
    )
    install.add_argument(
        "--api-key-env",
        action="store_true",
        help=t("cli.help.install.api_key_env"),
    )
    # Tres estados, y el de no pasar ninguno conserva la cabecera que ya tuviera cada cliente:
    # reinstalar sin el flag la borraba y dejaba al cliente en 401 contra un daemon con token.
    token = install.add_mutually_exclusive_group()
    token.add_argument(
        "--web-token-env",
        dest="web_token_env",
        action="store_const",
        const=True,
        default=None,
        help=t("cli.help.install.web_token_env"),
    )
    token.add_argument(
        "--no-web-token-env",
        dest="web_token_env",
        action="store_const",
        const=False,
        help=t("cli.help.install.no_web_token_env"),
    )
    install.add_argument(
        "--pin-version",
        default=None,
        help=t("cli.help.install.pin_version"),
    )
    install.add_argument(
        "--force-mcp-codex",
        action="store_true",
        help=t("cli.help.install.force_mcp_codex"),
    )
    install.set_defaults(func=cmd_install)

    upd = sub.add_parser(
        "update",
        help=t("cli.help.update"),
        description=t("cli.help.update._description"),
    )
    upd.add_argument("--dry-run", action="store_true", help=t("cli.help.install_common.dry_run"))
    upd.add_argument("--home", default=None, help=t("cli.help.install_common.home"))
    upd.add_argument(
        "--version",
        default=None,
        help=t("cli.help.update.version"),
    )
    upd.add_argument(
        "--restart-backend",
        action="store_true",
        help=t("cli.help.update.restart_backend"),
    )
    upd.add_argument("--no-restart", action="store_true", help=t("cli.help.update.no_restart"))
    upd.set_defaults(func=cmd_update)

    uninstall = sub.add_parser(
        "uninstall",
        help=t("cli.help.uninstall"),
    )
    _add_common_install_args(uninstall)
    uninstall.set_defaults(func=cmd_uninstall)


@contextlib.contextmanager
def _argparse_in_language() -> Iterator[None]:
    """El armazón de argparse («usage:», «options:», sus errores) en el idioma vigente (D8).

    argparse busca `_` y `ngettext` en su propio módulo cada vez que los usa, así que basta con
    cambiarlos ahí. Se devuelven a su sitio al salir, pase lo que pase: la suite corre en un
    solo proceso y, sin restaurarlos, el argparse de los scripts y de otros tests quedaría en el
    idioma del último `run()`, según el orden en que `xdist` reparta los tests.
    """
    saved = (argparse._, argparse.ngettext)
    argparse._, argparse.ngettext = i18n.argparse_gettext, i18n.argparse_ngettext
    try:
        yield
    finally:
        argparse._, argparse.ngettext = saved


def run(argv: list[str]) -> int:
    with _argparse_in_language():
        args = build_parser().parse_args(argv)
        return args.func(args)
