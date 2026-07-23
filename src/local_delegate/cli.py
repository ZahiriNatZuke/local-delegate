"""cli.py — subcomandos de línea de comandos de local-delegate.

Ver docs/recipes/llama-swap-groups.md y docs/wiki/Daemon.md. El binario ``local-delegate`` SIN
argumentos sigue arrancando el servidor MCP stdio exactamente igual que siempre (ver
server.main()); este módulo solo se importa cuando el usuario invoca explícitamente un
subcomando. Solo los comandos de configuración de llama-swap requieren el extra ``[llamaswap]``
(``pip install "local-delegate-mcp[llamaswap]"``); ``serve`` usa dependencias base.

El chequeo de RAM de sistema (``--ram-gb``) es OPCIONAL en ambos comandos: si no se pasa, el
comportamiento es idéntico al de antes de F7.9 (solo VRAM) — compatibilidad hacia atrás con
0.4.0. Motivo del chequeo de RAM: llama-server mapea el GGUF también en RAM (mmap) aunque el
cómputo sea 100% GPU, así que un catálogo que cabe holgado en VRAM puede igual agotar la RAM
del sistema (verificado en vivo: 8.37 GiB de archivo -> ~7.46 GB de RAM residente real).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import doctor
from . import llamaswap_config as lc

KNOWN_COMMANDS = {"check-llamaswap", "init-llamaswap", "doctor", "serve"}


def cmd_serve(args: argparse.Namespace) -> int:
    """Arranca el daemon singleton MCP HTTP + dashboard."""
    from . import daemon

    return daemon.serve(host=args.host, port=args.port, log_level=args.log_level)


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
        f"Presupuesto: {budget_gb:.2f} GiB - margen {margin_gb:.2f} GiB = {budget:.2f} GiB disponibles"
    )
    print("")
    for gc in breakdown:
        mode = "swap (1 a la vez)" if gc.swap else "todos juntos"
        print(f"grupo '{gc.group}' [{mode}] -> {gc.contribution_gb:.2f} GiB")
        for m in gc.members:
            est = estimates.get(m)
            if est is None or est.error:
                print(f"    {m}: ERROR ({est.error if est else 'sin estimación'})")
            else:
                print(f"    {m}: {est.gb:.2f} GiB [{est.method}] — {est.detail}")
    print("")
    print(f"Total peor caso ({title}): {total_gb:.2f} GiB")


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
                mid, 0.0, "error", "", error=f"modelo '{mid}' no está en 'models:'"
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
    level = "aviso" if allow else "error"
    print(
        f"{level}: modelo(s) fuera de todos los groups: {', '.join(ungrouped)}",
        file=sys.stderr,
    )
    if not allow:
        print(
            "el presupuesto quedaría incompleto; agrúpalos o usa --allow-ungrouped "
            "si es deliberado",
            file=sys.stderr,
        )
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
        print("")
        print(f"error: no se pudo estimar {label} de: {', '.join(errored)}", file=sys.stderr)
        return False, errored
    budget = budget_gb - margin_gb
    print("")
    if total_gb > budget:
        print(f"{label} NO CABE: {total_gb:.2f} GiB > {budget:.2f} GiB disponibles")
        return False, []
    print(f"{label} OK: cabe con {budget - total_gb:.2f} GiB de margen extra")
    return True, []


def cmd_check_llamaswap(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    try:
        data = lc.load_config(config_path)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    groups = data.get("groups")
    if not groups:
        print(f"error: no hay 'groups:' en {config_path}, nada que validar", file=sys.stderr)
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
        print("")
        ram_ok, ram_errors = _check_budget(
            "RAM", groups, models, {}, lc.estimate_model_ram, args.ram_gb, args.ram_margin_gb
        )
        if ram_errors:
            return 2

    return 0 if (vram_ok and ram_ok) else 1


def _parse_add_model(spec: str) -> tuple[str, str, float | None]:
    if "=" not in spec:
        raise argparse.ArgumentTypeError(
            f"formato inválido para --add-model: {spec!r} (esperado ID=RUTA[:VRAM_GB])"
        )
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
        print("error: hace falta al menos --resident o --swap", file=sys.stderr)
        return 2
    overlap = set(resident) & set(swap)
    if overlap:
        print(
            f"error: modelo(s) en --resident Y --swap a la vez: {', '.join(sorted(overlap))}",
            file=sys.stderr,
        )
        return 2

    config_path = Path(args.config)
    out_path = Path(args.out) if args.out else config_path
    try:
        data = lc.load_config(config_path)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    models = data.setdefault("models", {})

    overrides: dict[str, float] = {}
    for spec in args.add_model or []:
        model_id, gguf_path, vram = _parse_add_model(spec)
        if model_id in models:
            print(
                f"error: --add-model '{model_id}' ya existe en 'models:' de {config_path}",
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
        print(
            f"error: modelo(s) no encontrados en 'models:': {', '.join(missing)}", file=sys.stderr
        )
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
        print("(nada se escribió)", file=sys.stderr)
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
        print("(nada se escribió)", file=sys.stderr)
        return 2

    ram_ok = True
    if args.ram_gb is not None:
        print("")
        ram_ok, ram_errors = _check_budget(
            "RAM", groups, models, overrides, lc.estimate_model_ram, args.ram_gb, args.ram_margin_gb
        )
        if ram_errors:
            print("(nada se escribió)", file=sys.stderr)
            return 2

    if not (vram_ok and ram_ok):
        print("")
        print("no cabe — no se escribió nada")
        return 1

    if args.dry_run:
        print("")
        print("--dry-run: no se escribió nada. YAML resultante:")
        print("")
        print(lc.dump_config_str(data))
        return 0

    if out_path.exists() and not args.force:
        print("")
        print(
            f"error: {out_path} ya existe — usa --force para sobreescribir (se guarda un .bak)",
            file=sys.stderr,
        )
        return 2
    if out_path.exists() and args.force:
        backup = out_path.with_suffix(out_path.suffix + ".bak")
        shutil.copy2(out_path, backup)
        print("")
        print(f"backup: {backup}")

    lc.dump_config(data, out_path)
    print(f"escrito: {out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-delegate",
        description="CLIs opcionales de local-delegate para groups de llama-swap (extra [llamaswap]).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser(
        "check-llamaswap",
        help="Valida el presupuesto de VRAM (y opcionalmente RAM) de los groups de un config.yaml.",
    )
    check.add_argument("--config", required=True, help="ruta al config.yaml de llama-swap")
    check.add_argument("--vram-gb", required=True, type=float, help="VRAM total de la GPU en GiB")
    check.add_argument(
        "--margin-gb",
        type=float,
        default=1.5,
        help="margen de VRAM reservado al sistema (default 1.5)",
    )
    check.add_argument(
        "--ram-gb",
        type=float,
        default=None,
        help="si se pasa, también valida la RAM DE SISTEMA total (GiB) — opcional, off por default",
    )
    check.add_argument(
        "--ram-margin-gb",
        type=float,
        default=2.0,
        help="margen de RAM reservado al SO/otras apps (default 2.0, solo aplica con --ram-gb)",
    )
    check.add_argument(
        "--allow-ungrouped",
        action="store_true",
        help="permite modelos fuera de groups (se excluyen deliberadamente del presupuesto)",
    )
    check.set_defaults(func=cmd_check_llamaswap)

    init = sub.add_parser(
        "init-llamaswap",
        help="Genera/actualiza groups en un config.yaml de llama-swap con guardrail de VRAM/RAM.",
    )
    init.add_argument(
        "--config",
        required=True,
        help="config.yaml existente a aumentar (si no existe, se parte de uno vacío)",
    )
    init.add_argument("--out", help="ruta de salida (default: el mismo --config)")
    init.add_argument(
        "--resident", default="", help="ids de modelos (coma-separados) para el grupo persistente"
    )
    init.add_argument(
        "--swap", default="", help="ids de modelos (coma-separados) para el grupo swap (1 a la vez)"
    )
    init.add_argument(
        "--add-model",
        action="append",
        metavar="ID=RUTA[:VRAM_GB]",
        help="define una entrada mínima de modelo si ID no existe ya en --config (repetible)",
    )
    init.add_argument(
        "--server-exe",
        default="llama-server",
        help="ejecutable usado en el cmd generado para --add-model (default: llama-server)",
    )
    init.add_argument(
        "--ttl-resident", type=int, default=600, help="ttl (segundos) para modelos de --resident"
    )
    init.add_argument(
        "--ttl-swap", type=int, default=300, help="ttl (segundos) para modelos de --swap"
    )
    init.add_argument("--vram-gb", required=True, type=float, help="VRAM total de la GPU en GiB")
    init.add_argument(
        "--margin-gb",
        type=float,
        default=1.5,
        help="margen de VRAM reservado al sistema (default 1.5)",
    )
    init.add_argument(
        "--ram-gb",
        type=float,
        default=None,
        help="si se pasa, también valida la RAM DE SISTEMA total (GiB) — opcional, off por default",
    )
    init.add_argument(
        "--ram-margin-gb",
        type=float,
        default=2.0,
        help="margen de RAM reservado al SO/otras apps (default 2.0, solo aplica con --ram-gb)",
    )
    init.add_argument(
        "--store-path",
        default=None,
        help="ruta de la BD SQLite de métricas de llama-swap (#898); persiste stats entre reinicios",
    )
    init.add_argument(
        "--force", action="store_true", help="sobreescribe --out si ya existe (deja un .bak)"
    )
    init.add_argument(
        "--dry-run", action="store_true", help="imprime el YAML resultante, no escribe nada"
    )
    init.add_argument(
        "--allow-ungrouped",
        action="store_true",
        help="permite conservar modelos fuera de los groups generados",
    )
    init.set_defaults(func=cmd_init_llamaswap)

    doc = sub.add_parser(
        "doctor",
        help="Diagnostica la instalación del backend: versiones de llama-server/llama-swap vs probadas.",
    )
    doc.add_argument(
        "--config",
        default=None,
        help="config.yaml de llama-swap (para localizar llama-server; default: LLAMASWAP_CONFIG)",
    )
    doc.add_argument(
        "--online",
        action="store_true",
        help="consulta GitHub por la última release publicada de cada componente",
    )
    doc.set_defaults(func=doctor.run_doctor)

    serve = sub.add_parser(
        "serve",
        help="Sirve MCP Streamable HTTP (/mcp) y dashboard (/) como daemon singleton.",
    )
    serve.add_argument(
        "--host", default=None, help="host de escucha (default: web host / 127.0.0.1)"
    )
    serve.add_argument(
        "--port", type=int, default=None, help="puerto único MCP+web (default: 9393)"
    )
    serve.add_argument(
        "--log-level",
        choices=("critical", "error", "warning", "info", "debug"),
        default="warning",
        help="nivel de log de uvicorn (default: warning)",
    )
    serve.set_defaults(func=cmd_serve)

    return parser


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
