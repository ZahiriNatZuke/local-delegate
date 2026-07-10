"""cli.py — subcomandos opt-in de línea de comandos: check-llamaswap / init-llamaswap.

Ver docs/recipes/llama-swap-groups.md. El binario ``local-delegate`` SIN argumentos sigue
arrancando el servidor MCP stdio exactamente igual que siempre (ver server.main()); este
módulo solo se importa cuando el usuario invoca explícitamente uno de estos subcomandos.
Requieren el extra ``[llamaswap]`` (``pip install "local-delegate-mcp[llamaswap]"``).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import llamaswap_config as lc

KNOWN_COMMANDS = {"check-llamaswap", "init-llamaswap"}


def _print_breakdown(
    total_gb: float,
    breakdown: list[lc.GroupContribution],
    estimates: dict[str, lc.VramEstimate],
    vram_gb: float,
    margin_gb: float,
) -> None:
    budget = vram_gb - margin_gb
    print(f"Presupuesto: {vram_gb:.2f} GiB - margen {margin_gb:.2f} GiB = {budget:.2f} GiB disponibles")
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
    print(f"Total peor caso: {total_gb:.2f} GiB")


def _estimate_all(
    groups: dict, models: dict, overrides: dict[str, float]
) -> dict[str, lc.VramEstimate]:
    member_ids: set[str] = set()
    for g in groups.values():
        if isinstance(g, dict):
            member_ids.update(g.get("members", []))
    estimates: dict[str, lc.VramEstimate] = {}
    for mid in member_ids:
        entry = models.get(mid)
        if entry is None:
            estimates[mid] = lc.VramEstimate(
                mid, 0.0, "error", "", error=f"modelo '{mid}' no está en 'models:'"
            )
            continue
        estimates[mid] = lc.estimate_model_vram(mid, entry, override_gb=overrides.get(mid))
    return estimates


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
    estimates = _estimate_all(groups, models, overrides={})
    total_gb, breakdown = lc.worst_case_vram_gb(groups, estimates)
    _print_breakdown(total_gb, breakdown, estimates, args.vram_gb, args.margin_gb)

    errored = sorted(m for m, e in estimates.items() if e.error)
    if errored:
        print("")
        print(f"error: no se pudo estimar VRAM de: {', '.join(errored)}", file=sys.stderr)
        return 2

    budget = args.vram_gb - args.margin_gb
    print("")
    if total_gb > budget:
        print(f"NO CABE: {total_gb:.2f} GiB > {budget:.2f} GiB disponibles")
        return 1
    print(f"OK: cabe con {budget - total_gb:.2f} GiB de margen extra")
    return 0


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
        print(f"error: modelo(s) no encontrados en 'models:': {', '.join(missing)}", file=sys.stderr)
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
    data["groups"] = groups

    estimates = _estimate_all(groups, models, overrides)
    total_gb, breakdown = lc.worst_case_vram_gb(groups, estimates)
    _print_breakdown(total_gb, breakdown, estimates, args.vram_gb, args.margin_gb)

    errored = sorted(m for m, e in estimates.items() if e.error)
    if errored:
        print("")
        print(
            f"error: no se pudo estimar VRAM de: {', '.join(errored)} — no se escribió nada",
            file=sys.stderr,
        )
        return 2

    budget = args.vram_gb - args.margin_gb
    if total_gb > budget:
        print("")
        print(f"NO CABE: {total_gb:.2f} GiB > {budget:.2f} GiB disponibles — no se escribió nada")
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
    print("")
    print(f"OK: cabe con {budget - total_gb:.2f} GiB de margen extra")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-delegate",
        description="CLIs opcionales de local-delegate para groups de llama-swap (extra [llamaswap]).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser(
        "check-llamaswap",
        help="Valida el presupuesto de VRAM de los groups de un config.yaml de llama-swap.",
    )
    check.add_argument("--config", required=True, help="ruta al config.yaml de llama-swap")
    check.add_argument("--vram-gb", required=True, type=float, help="VRAM total de la GPU en GiB")
    check.add_argument(
        "--margin-gb", type=float, default=1.5, help="margen reservado al sistema (default 1.5)"
    )
    check.set_defaults(func=cmd_check_llamaswap)

    init = sub.add_parser(
        "init-llamaswap",
        help="Genera/actualiza groups en un config.yaml de llama-swap con guardrail de VRAM.",
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
        "--margin-gb", type=float, default=1.5, help="margen reservado al sistema (default 1.5)"
    )
    init.add_argument(
        "--force", action="store_true", help="sobreescribe --out si ya existe (deja un .bak)"
    )
    init.add_argument(
        "--dry-run", action="store_true", help="imprime el YAML resultante, no escribe nada"
    )
    init.set_defaults(func=cmd_init_llamaswap)

    return parser


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
