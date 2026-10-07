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
import shutil
import sys
from pathlib import Path

from . import benchmark, doctor
from . import llamaswap_config as lc
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
# —`servicio` y `backend`— salen a la red y lanzan los binarios de llama-swap, y haber
# instalado unos hooks no es motivo para nada de eso.
_SCAFFOLD_GROUPS = ("entorno", "andamiaje")


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
        raise ValueError("--clients y --target no se combinan: usa uno de los dos")

    if target:  # semántica histórica intacta: `all` fuerza los dos, existan o no
        chosen = set(_ALL_TARGETS) if "all" in target else set(target)
        return chosen, f"por --target: {', '.join(sorted(chosen))}"

    explicit = {c for c in (clients or []) if c != "auto"}
    if explicit:
        # Pedir un cliente por su nombre es una orden, no una sugerencia: se configura aunque no
        # esté instalado (caso legítimo, p. ej. preparar el HOME antes de instalar el cliente).
        return explicit, f"por --clients: {', '.join(sorted(explicit))}"

    present = inst.present_targets(home)
    return present, "deteccion automatica (--clients auto): " + (
        ", ".join(sorted(present)) if present else "no se encontró ninguno"
    )


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


def _hay_terminal() -> bool:
    """True si se puede preguntar de verdad. Un stdin raro NO es una terminal."""
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        # stdin cerrado, redirigido o un objeto sin `isatty` usable: no hay a quién preguntar.
        return False


def _codex_mcp_puesto_a_mano(results) -> str:
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


def _decide_sobre_el_codex_ajeno(detalle: str, args: argparse.Namespace) -> bool:
    """True si hay que SALTAR la escritura de la entrada MCP de Codex."""
    if getattr(args, "force_mcp_codex", False):
        print(f"Aviso: {detalle}")
        print("       --force-mcp-codex: se reemplaza (queda una copia .bak al lado).")
        return False
    if args.dry_run:
        print(f"Aviso: {detalle}")
        print("       En una ejecución real se pediría confirmación antes de reemplazarla.")
        return False
    if not _hay_terminal():
        print(f"Aviso: {detalle}")
        print("       Sin terminal para preguntar: se conserva tal cual y no se toca.")
        print("       Para reemplazarla sin preguntar: --force-mcp-codex")
        return True
    print(f"Aviso: {detalle}")
    try:
        respuesta = input("       ¿Reemplazarla por la entrada gestionada? [s/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        respuesta = ""
    if respuesta in ("s", "si", "sí", "y", "yes"):
        return False
    print("       Se conserva la entrada del usuario; el resto sí se instala.")
    return True


def _reporte_del_andamiaje(home: Path, dry_run: bool) -> None:
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
        print("Estado ACTUAL del andamiaje (no se escribió nada):")
    else:
        print("Estado del andamiaje después de escribir:")
    print("Estados: [ OK ] a punto · [WARN] revisar · [FALT] falta · [ -- ] no se pudo comprobar")
    for group in _SCAFFOLD_GROUPS:
        print()
        print(doctor._GROUP_HEADINGS[group])
        doctor._print_group(group, results)


def _run_install(args: argparse.Namespace, uninstall: bool) -> int:
    from . import checks
    from . import install as inst

    home = Path(args.home).expanduser() if args.home else Path.home()
    try:
        targets, motivo = _resolve_clients(args, home)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    verb = "Desinstalando" if uninstall else "Instalando"
    print(f"{verb} local-delegate en {home}")
    print(f"clientes: {motivo}")

    if not targets:
        # Con `auto` y ningún cliente, no hay nada que hacer y casi siempre significa un --home
        # equivocado. No es un error: no se escribe nada, se dice qué se buscó y se sigue.
        print()
        print("No se encontró ningún cliente: se buscaron " + " y ".join(_CLIENT_DIR.values()))
        print(f"bajo {home}. No se escribió nada.")
        print("Si querías configurarlo igual:  --clients claude   (o codex, u opencode)")
        _reporte_del_andamiaje(home, dry_run=True)
        return 0

    # Primera pasada del registro: para saber si hay configuración del usuario que no se puede
    # pisar sin preguntar. Solo hace falta cuando de verdad vamos a escribir la entrada de Codex.
    skip_codex_mcp = False
    if not uninstall and "codex" in targets and getattr(args, "mcp", True):
        detalle = _codex_mcp_puesto_a_mano(
            checks.run_all(checks.Context(home=home), groups=("andamiaje",))
        )
        if detalle:
            skip_codex_mcp = _decide_sobre_el_codex_ajeno(detalle, args)

    opts = _install_options(args, targets, skip_codex_mcp=skip_codex_mcp)
    if not opts.components:
        print("error: no queda ningún componente que instalar (todo desactivado)", file=sys.stderr)
        return 2
    actions = inst.plan_uninstall(opts) if uninstall else inst.plan_install(opts)
    print(f"componentes: {', '.join(sorted(opts.components))}")
    print()
    failures = inst.apply(actions, dry_run=args.dry_run)
    print()
    if args.dry_run:
        print("--dry-run: no se escribió nada.")
        _reporte_del_andamiaje(opts.home, dry_run=True)
        return 0
    if not uninstall and not failures:
        print("Listo. Reinicia el cliente (Claude Code / Codex / opencode) para tomar los cambios.")
        _avisa_si_el_cli_no_esta_en_el_path()
        _deja_el_daemon_arriba(opts)
    # El reporte va ANTES del código de salida, y también cuando algo falló: si una acción no
    # pudo escribir, saber qué quedó a medias es justo lo que hace falta para arreglarlo.
    # Es informativo y NO cambia el exit code — tras un install correcto quedan avisos legítimos
    # (el CLI fuera del PATH con `uvx`, un cliente ausente) y devolver 1 por eso rompería
    # cualquier script de instalación.
    _reporte_del_andamiaje(opts.home, dry_run=False)
    if failures:
        print(f"{failures} acción(es) fallaron.", file=sys.stderr)
        return 1
    return 0


def _deja_el_daemon_arriba(opts) -> None:
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
        print("HOME simulado: no se toca el daemon de la máquina.")
        return
    print()
    upd.restart_daemon(update_opts)


def _avisa_si_el_cli_no_esta_en_el_path() -> None:
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
    print("Aviso: el comando `local-delegate` no quedó en el PATH.")
    print("       Pasa cuando se instala con `uvx`, que borra su entorno al terminar.")
    print(f"       Para tenerlo siempre disponible:  {checks.CLI_HINT}")


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


def cmd_recalcular_coste(args: argparse.Namespace) -> int:
    """`recalcular-coste` (coste-api-y-cuota, REQ-070): escribe solo en el directorio de logs."""
    from . import config, recalcular

    claude_dir = Path(args.claude_dir) if args.claude_dir else Path.home() / ".claude"
    try:
        resumen = recalcular.ejecutar(
            claude_dir, config.LOG_DIR, reiniciar=args.reiniciar_calibracion
        )
    except OSError as e:
        print(f"recalcular-coste: no se pudo escribir en el directorio de logs ({e.strerror}).")
        return 1
    print(recalcular.texto_del_resumen(resumen))
    return 0


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
        f"Presupuesto: {budget_gb:.2f} GiB - margen {margin_gb:.2f} GiB = {budget:.2f} GiB disponibles"
    )
    print()
    for gc in breakdown:
        mode = "swap (1 a la vez)" if gc.swap else "todos juntos"
        print(f"grupo '{gc.group}' [{mode}] -> {gc.contribution_gb:.2f} GiB")
        for m in gc.members:
            est = estimates.get(m)
            if est is None or est.error:
                print(f"    {m}: ERROR ({est.error if est else 'sin estimación'})")
            else:
                print(f"    {m}: {est.gb:.2f} GiB [{est.method}] — {est.detail}")
    print()
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
        print()
        print(f"error: no se pudo estimar {label} de: {', '.join(errored)}", file=sys.stderr)
        return False, errored
    budget = budget_gb - margin_gb
    print()
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
        print()
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
        print()
        ram_ok, ram_errors = _check_budget(
            "RAM", groups, models, overrides, lc.estimate_model_ram, args.ram_gb, args.ram_margin_gb
        )
        if ram_errors:
            print("(nada se escribió)", file=sys.stderr)
            return 2

    if not (vram_ok and ram_ok):
        print()
        print("no cabe — no se escribió nada")
        return 1

    if args.dry_run:
        print()
        print("--dry-run: no se escribió nada. YAML resultante:")
        print()
        print(lc.dump_config_str(data))
        return 0

    if out_path.exists() and not args.force:
        print()
        print(
            f"error: {out_path} ya existe — usa --force para sobreescribir (se guarda un .bak)",
            file=sys.stderr,
        )
        return 2
    if out_path.exists() and args.force:
        # REQ-035: la copia lleva fecha y no pisa ninguna anterior, como la de `residencia`.
        from . import residencia

        backup = residencia.copia_con_fecha(out_path)
        print()
        print(f"backup: {backup}")

    lc.dump_config(data, out_path)
    print(f"escrito: {out_path}")
    return 0


# --- llamaswap residency (T11: REQ-029 a REQ-033, REQ-038; T13: REQ-034, REQ-039) -------------
#
# Antes de escribir, la comprobación previa de REQ-034 (delegaciones propias, peticiones en vuelo
# de cualquier cliente, modelos en `/running`): por el daemon, que tiene la key; si no responde,
# directo con la key del shell; si tampoco, «no se sabe». Con `--now` se escribe igual. La vigía de
# la recarga se abre ANTES de escribir y dice cuál de las cuatro salidas hubo.

_AYUDA_RESIDENCIA = """\
Sin opciones, muestra la residencia de la config de llama-swap: cada modelo con su grupo, el TTL
efectivo y el veredicto («sin residente (recomendado)» o «residente: X»). No imprime claves ni
`cmd`.

TTL efectivo: en llama-swap (load.go) un `ttl` ausente o -1 vale `globalTTL`, que por defecto es 0.
Así que SIN `globalTTL` NI `ttl` TODOS LOS MODELOS TIENEN TTL EFECTIVO 0: no se descargan nunca por
TTL y salen como residentes. Para dejarlos sin residente, `--none` pide entonces `--ttl` para
todos.

La config sale de --config; si no, de LLAMASWAP_CONFIG; si no, de la que usa el daemon. Si nada de
eso responde, «no se sabe» y no se abre ningún fichero.

Escribir hace que llama-swap (con -watch-config) recargue en unos 2 s, DESCARGUE TODOS LOS MODELOS
y CORTE LAS PETICIONES EN CURSO (de cualquier cliente). Por eso no se escribe si hay delegaciones
de local-delegate en curso, peticiones en vuelo en llama-swap o modelos cargados, ni si no se puede
saber (sin daemon y sin la credencial de llama-swap en el shell): --now escribe igual.

Antes deja una copia <config>.<AAAAMMDD-HHMMSS>.bak y reemplaza el fichero de forma atómica.
Después dice qué hizo llama-swap: recargó; rechazó (y se restaura la copia, para que el fichero
coincida con lo que corre); no vigila el fichero (se aplicará en el próximo arranque); o caído.
"""


def _destino_del_daemon() -> tuple[str, int, dict[str, str]]:
    """Host, puerto y cabecera con que el CLI pregunta al daemon: los mismos que usa `doctor`.

    Función aparte para que la suite la apunte a un puerto muerto (`conftest.daemon_real_cortado`).
    """
    from . import checks, config

    host, puerto = checks.daemon_host_port()
    return host, puerto, config.web_auth_headers()


def _url_del_daemon() -> str:
    host, puerto, _cabecera = _destino_del_daemon()
    return f"http://{host}:{puerto}"


def _ruta_del_daemon(answer=None) -> Path | None:
    """La config que usa el daemon, por su endpoint de REQ-039. `None` si no contesta.

    Con `answer` (lo que ya devolvió `_daemon_status`) no se vuelve a preguntar: una escritura sin
    `--config` hace UNA sola consulta del estado, que sirve para la ruta y para las negativas.
    """
    status, _why = answer if answer is not None else _daemon_status()
    if status is None or not status.config_path:
        return None
    return Path(status.config_path)


def _ruta_de_la_config(args: argparse.Namespace):
    """`(ruta, respuesta del daemon)`: `--config`, si no `LLAMASWAP_CONFIG`, si no la del daemon.

    La respuesta del daemon solo viene si hubo que preguntarle; la reutiliza la escritura.
    """
    from . import config

    if args.config:
        return Path(args.config), None
    desde_el_entorno = config.llamaswap_config_path()
    if desde_el_entorno:
        return Path(desde_el_entorno).expanduser(), None
    answer = _daemon_status()
    return _ruta_del_daemon(answer), answer


def _pares(valores: list[str], opcion: str, tipo) -> dict[str, float]:
    pares = {}
    for valor in valores:
        modelo, igual, cifra = valor.partition("=")
        try:
            if not igual or not modelo:
                raise ValueError
            pares[modelo.strip()] = tipo(cifra.strip().replace(",", "."))
        except ValueError:
            raise ValueError(f"{opcion} {valor!r}: el formato es MODEL=VALUE") from None
    return pares


def _daemon_status():
    """`(estado, por qué no)` preguntando al daemon (REQ-039, punto 1), con plazo propio.

    El plazo importa: con el limitador de hilos del daemon agotado, la conexión se acepta y la
    respuesta no llega nunca, y el CLI no puede quedarse colgado esperando (T13). Y no son 2 s:
    con llama-swap caído el daemon tarda ~2,1 s en saberlo (un puerto cerrado en Windows).
    """
    import httpx2

    from . import llamaswap_api

    _host, _port, headers = _destino_del_daemon()
    try:
        response = httpx2.get(
            f"{_url_del_daemon()}/api/llamaswap/status",
            headers=headers,
            timeout=llamaswap_api.CLI_TO_DAEMON,
        )
    except httpx2.TimeoutException:
        return None, "el daemon no contestó a tiempo"
    except httpx2.HTTPError:
        return None, "el daemon no responde"
    if response.status_code != 200:
        return None, f"el daemon respondió {response.status_code}"
    try:
        return llamaswap_api.Status.from_json(response.json()), ""
    except (ValueError, llamaswap_api.QueryError):
        return None, "el daemon devolvió un estado que no se entiende"


def _llamaswap_status(daemon_answer=None):
    """REQ-039: `(origen, estado, por qué no se sabe)`. Por el daemon; si no responde, directo
    contra llama-swap con la key del shell; si tampoco, «no se sabe». Nunca pide la key."""
    from . import config, llamaswap_api, server

    status, why = daemon_answer if daemon_answer is not None else _daemon_status()
    if status is not None:
        return "daemon", status, ""
    if not config.API_KEY:
        return "", None, f"{why}, y este shell no tiene la credencial de llama-swap"
    status = llamaswap_api.query_status(
        llamaswap_api.local_backend(), own_delegations=len(server.inflight_snapshot())
    )
    if status.llamaswap == llamaswap_api.STATE_UNKNOWN:
        return "", None, f"{why}, y llama-swap no lo dice: {status.detail}"
    return "direct", status, ""


def _daemon_watch(watch_id: str):
    """Espera la salida de una vigía abierta en el daemon, preguntando cada medio segundo."""
    import time

    import httpx2

    from . import llamaswap_api

    _host, _port, headers = _destino_del_daemon()
    deadline = time.monotonic() + llamaswap_api.WATCH_TOTAL_S + 5
    while time.monotonic() < deadline:
        try:
            response = httpx2.get(
                f"{_url_del_daemon()}/api/llamaswap/watch/{watch_id}",
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
    return llamaswap_api.UNRESOLVED, "el daemon no dio la salida de la vigía a tiempo"


def _open_watch(origin: str, why: str):
    """Abre la vigía ANTES de escribir (REQ-034). `(esperar, abandonar, por qué no)`.

    `esperar()` devuelve `(salida, línea de llama-swap)`; `abandonar()` la suelta sin esperar (no
    se llegó a escribir). Sin vigía, los dos son `None` y el tercero dice por qué.
    """
    import httpx2

    from . import llamaswap_api

    if origin == "daemon":
        _host, _port, headers = _destino_del_daemon()
        try:
            response = httpx2.post(
                f"{_url_del_daemon()}/api/llamaswap/watch",
                headers=headers,
                timeout=llamaswap_api.CLI_TO_DAEMON_WATCH,
            )
            data = response.json()
        except (httpx2.HTTPError, ValueError) as e:
            return None, None, f"el daemon no abrió la vigía: {type(e).__name__}"
        watch_id = data.get("id") if isinstance(data, dict) else None
        if response.status_code != 200 or not isinstance(watch_id, str):
            error = data.get("error") if isinstance(data, dict) else None
            return None, None, f"el daemon no abrió la vigía: {error or response.status_code}"
        # En el daemon, una vigía abandonada acaba sola («no vigila» a los 10 s, o lo que vea).
        return (lambda: _daemon_watch(watch_id)), (lambda: None), ""
    if origin == "direct":
        watcher = llamaswap_api.Watcher(llamaswap_api.local_backend())
        try:
            watcher.open()
        except (llamaswap_api.QueryError, httpx2.HTTPError) as e:
            return None, None, f"no se pudo abrir la vigía: {e or type(e).__name__}"
        return (lambda: (watcher.wait(), watcher.line)), watcher.close, ""
    return None, None, why


def _restore_after_rejection(path: Path, previous: bytes) -> Path:
    """REQ-034, «rechazó»: vuelve a la config que sigue corriendo, por el camino de REQ-038 (valida
    la copia, copia el fichero actual y reemplaza de forma atómica). Devuelve la copia del
    rechazado, para que no se pierda."""
    from . import residencia

    residencia.validar_copia(previous)
    rejected_copy = residencia.copia_con_fecha(path)
    residencia.reemplazar_atomico(path, previous)
    return rejected_copy


def _report_outcome(outcome: str, line: str, path: Path, previous: bytes, status, origin) -> int:
    """El mensaje de cada una de las cuatro salidas de REQ-034 (y de «sin resolver»)."""
    from . import llamaswap_api, residencia

    text = llamaswap_api.OUTCOME_TEXT[outcome]
    if outcome == llamaswap_api.RELOADED:
        print(f"llama-swap {text} la config ({line})")
        return 0
    if outcome == llamaswap_api.REJECTED:
        print(
            f"error: llama-swap {text} la config y sigue con la anterior. Su error: {line}",
            file=sys.stderr,
        )
        print(
            "aviso: se restaura la config que corre llama-swap; al restaurar, llama-swap vuelve a "
            "recargar y corta las peticiones en curso",
            file=sys.stderr,
        )
        # La segunda recarga también se vigila: se abre antes de restaurar, como la primera.
        wait_again, abandon_again, why_not = _open_watch(origin, "")
        try:
            rejected_copy = _restore_after_rejection(path, previous)
        except (residencia.ErrorResidencia, OSError) as e:
            if abandon_again is not None:
                abandon_again()
            print(f"error: no se pudo restaurar la copia: {e}", file=sys.stderr)
            return 1
        print(
            f"restaurada la config que corre llama-swap en {path}; la rechazada quedó en "
            f"{rejected_copy}",
            file=sys.stderr,
        )
        if wait_again is None:
            print(f"aviso: no se puede confirmar la recarga de la restaurada ({why_not})")
            return 1
        outcome_again, line_again = wait_again()
        print(
            f"recarga de la config restaurada: {llamaswap_api.OUTCOME_TEXT[outcome_again]} "
            f"({line_again})",
            file=sys.stderr,
        )
        return 1
    if outcome == llamaswap_api.NOT_WATCHING:
        message = (
            f"llama-swap {text} ({line}): el cambio se aplicará en el próximo arranque de "
            "llama-swap"
        )
        if status is not None and status.autostart and not status.watch_config:
            message += (
                "; si llama-swap lo arrancó el daemon, le falta -watch-config "
                "(LLAMASWAP_WATCH_CONFIG=1 en el lanzador del daemon)"
            )
        print(message)
        return 0
    if outcome == llamaswap_api.DOWN:
        print(
            f"llama-swap {text}: no responde ({line}); el cambio se aplicará en el próximo arranque"
        )
        return 0
    print(f"aviso: recarga {text}: {line}")
    return 0


def _escribir_residencia(
    args: argparse.Namespace, ruta: Path, nuevo: bytes, original: bytes, daemon_answer=None
) -> int:
    """Escribe `nuevo` si el fichero sigue siendo `original` (los bytes sobre los que se decidió).

    Antes, las negativas de REQ-034 (salvo `--now`) y la vigía, que se abre ANTES de comparar el
    fichero: abrirla tarda (hasta 8 s por el daemon) y comparar antes dejaría una ventana en la que
    un cambio ajeno se pisaría. Sin vigía tampoco se escribe, salvo `--now`: no se escribe a ciegas.
    T2 (d) midió que una recarga de v255 corta las peticiones en curso aunque su modelo no cambie
    (502 a los ~1,8 s): el aviso no se suaviza y la negativa se queda.
    """
    from . import llamaswap_api, residencia

    origin, status, why = _llamaswap_status(daemon_answer)
    if status is None:
        reasons = [f"{residencia.NO_SE_SABE} ({why})"]
    else:
        reasons = llamaswap_api.refusals(status)
    if reasons and not args.now:
        print(
            f"error: {'; '.join(reasons)}: no se escribe. llama-swap recargaría la config, "
            "descargaría todos los modelos y cortaría las peticiones en curso. Con --now se "
            "escribe igual.",
            file=sys.stderr,
        )
        return 2
    wait, abandon, why_no_watch = _open_watch(origin, why)
    if wait is None and not args.now:
        print(
            f"error: no se puede vigilar la recarga ({why_no_watch}): no se escribe a ciegas. "
            "Con --now se escribe igual.",
            file=sys.stderr,
        )
        return 2
    # Actualización perdida: si alguien cambió el fichero desde que se leyó, escribir pisaría su
    # cambio con una edición calculada sobre los bytes viejos. Se compara tras abrir la vigía.
    current = ruta.read_bytes()
    if current != original:
        if abandon is not None:
            abandon()
        print(f"error: {residencia.CAMBIO_DURANTE_LA_EDICION}", file=sys.stderr)
        return 2
    print(
        "aviso: llama-swap recargará la config en unos 2 s, descargará todos los modelos y cortará "
        "las peticiones en curso"
    )
    copy = residencia.copia_con_fecha(ruta, current)
    residencia.reemplazar_atomico(ruta, nuevo)
    print(f"copia: {copy}")
    print(f"escrito: {ruta}")
    if reasons:
        print(f"aviso: escrito con --now: {'; '.join(reasons)}")
    if wait is None:
        print(f"aviso: no se puede confirmar la recarga ({why_no_watch})")
        return 0
    print(f"esperando a llama-swap (hasta {llamaswap_api.WATCH_TOTAL_S:g} s)...", flush=True)
    outcome, line = wait()
    return _report_outcome(outcome, line, ruta, current, status, origin)


def cmd_llamaswap_residencia(args: argparse.Namespace) -> int:
    from . import residencia, topologia

    ruta, daemon_answer = _ruta_de_la_config(args)
    if ruta is None:
        print(
            "no se sabe qué config usa llama-swap: no hay --config, LLAMASWAP_CONFIG está vacía y "
            "el daemon no responde. Pasa --config PATH.",
            file=sys.stderr,
        )
        return 2
    try:
        ttls = {m: int(s) for m, s in _pares(args.ttl, "--ttl", int).items()}
        vram_modelo = _pares(args.vram_model, "--vram-model", float)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if (args.pin or args.restore) and ttls:
        print("error: --ttl no se combina con --pin ni con --restore", file=sys.stderr)
        return 2
    try:
        if args.restore:
            copia = Path(args.restore).read_bytes()
            residencia.validar_copia(copia)
            original = ruta.read_bytes()
            if args.dry_run:
                print(
                    f"--dry-run: no se escribe nada. Líneas que cambiarían al restaurar {args.restore}:"
                )
                print("\n".join(residencia.diff_oculto(original, copia)))
                return 0
            return _escribir_residencia(args, ruta, copia, original, daemon_answer)
        cargada = residencia.cargar(ruta)
        foto = cargada.foto
        if isinstance(foto, topologia.SinTopologia):
            detalle = f": {foto.detalle}" if foto.detalle else ""
            print(
                f"error: no se puede leer la residencia ({foto.motivo}{detalle})", file=sys.stderr
            )
            return 2
        aviso = ""
        if args.none:
            cambios = residencia.plan_ninguno(cargada.datos, foto, ttls, args.group)
        elif args.pin:
            if args.vram_gb is None:
                print("error: --pin necesita --vram-gb (la VRAM de la GPU)", file=sys.stderr)
                return 2
            cambios, aviso = residencia.plan_fijar(
                cargada.datos, foto, args.pin, args.vram_gb, args.reserve_gb, vram_modelo
            )
        elif ttls:
            cambios = residencia.plan_ttl(ttls, cargada.datos, foto)
        else:
            print(residencia.vista(foto, cargada.datos).texto())
            return 0
        if not cambios:
            print("nada que cambiar")
            return 0
        nuevo, diff = residencia.editar_con_diff(cargada.original, cambios)
    except residencia.ErrorResidencia as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if aviso:
        print(f"aviso: {aviso}")
    if args.dry_run:
        print("--dry-run: no se escribe nada. Líneas que cambiarían:")
        print("\n".join(diff))
        return 0
    try:
        return _escribir_residencia(args, ruta, nuevo, cargada.original, daemon_answer)
    except (residencia.ErrorResidencia, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def _add_llamaswap_parser(sub) -> None:
    llamaswap = sub.add_parser(
        "llamaswap",
        help="Residencia y TTL de los modelos de llama-swap (pide el extra [llamaswap]).",
    )
    lsub = llamaswap.add_subparsers(dest="llamaswap_command", required=True)
    res = lsub.add_parser(
        "residency",
        help="Muestra o cambia qué modelo se queda cargado y los TTL.",
        description=_AYUDA_RESIDENCIA,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    res.add_argument("--config", default=None, help="config.yaml de llama-swap")
    accion = res.add_mutually_exclusive_group()
    accion.add_argument(
        "--none",
        action="store_true",
        help="deja la config sin residente: mueve los grupos persistent al grupo swap y pone --ttl "
        "a los modelos con TTL efectivo 0",
    )
    accion.add_argument(
        "--pin",
        metavar="MODEL",
        default=None,
        help="residencia OPT-IN: el modelo pasa a un grupo persistent (swap y exclusive false) con "
        "ttl 0 y retiene VRAM de forma permanente; se niega si no cabe",
    )
    accion.add_argument(
        "--restore", metavar="BAK", default=None, help="vuelve a una copia .bak, byte a byte"
    )
    res.add_argument(
        "--ttl",
        action="append",
        default=[],
        metavar="MODEL=SECONDS",
        help="cambia el TTL (entero >= 1; el 0 es --pin; -1 solo con globalTTL > 0); repetible",
    )
    res.add_argument("--group", default=None, help="grupo destino de --none")
    res.add_argument("--vram-gb", type=float, default=None, help="VRAM de la GPU en GiB (--pin)")
    res.add_argument(
        "--reserve-gb",
        type=float,
        default=2.0,
        help="VRAM que se deja al resto de la PC (default 2)",
    )
    res.add_argument(
        "--vram-model",
        action="append",
        default=[],
        metavar="ID=GiB",
        help="VRAM medida de un modelo (repetible); sin ella, --pin se niega",
    )
    res.add_argument(
        "--dry-run", action="store_true", help="imprime solo las líneas que cambiarían"
    )
    res.add_argument(
        "--now",
        action="store_true",
        help="escribe aunque no se sepa si hay delegaciones en curso",
    )
    res.set_defaults(func=cmd_llamaswap_residencia)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-delegate",
        description=(
            "Instala, diagnostica y sirve local-delegate. Sin subcomando, este binario arranca "
            "el servidor MCP stdio, que es como lo lanzan Claude Code, Codex y opencode. "
            "`check-llamaswap` e `init-llamaswap` piden el extra [llamaswap]."
        ),
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
        help="imprime la versión instalada y termina",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    benchmark.add_parser(sub)

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
        "--resident",
        default="",
        help="residencia OPT-IN: ids de modelos (coma-separados) que se quedan cargados para "
        "siempre en un grupo persistente y retienen VRAM; por defecto no hay residente",
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
        "--ttl-resident",
        type=int,
        default=0,
        help="ttl (segundos) para modelos de --resident (default 0: con `persistent` y un TTL "
        "mayor que 0 el modelo se descarga igual y no hay residencia de verdad)",
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
        "--force",
        action="store_true",
        help="sobreescribe --out si ya existe (deja una copia <out>.<AAAAMMDD-HHMMSS>.bak)",
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

    _add_llamaswap_parser(sub)

    doc = sub.add_parser(
        "doctor",
        help="Diagnostica el andamiaje (hooks, skill, memoria, MCP), el daemon y el backend.",
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
    doc.add_argument(
        "--home",
        default=None,
        help="HOME alternativo para diagnosticar (default: el del usuario); solo se lee",
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

    recalc = sub.add_parser(
        "recalcular-coste",
        help=(
            "Lee los transcripts de Claude Code y deja en el directorio de logs el relleno de "
            "atribución, los agregados de N, el cotejo de precios y los puntos de cuota."
        ),
    )
    recalc.add_argument(
        "--reiniciar-calibracion",
        choices=("five_hour", "seven_day"),
        default=None,
        help="los puntos de cuota de ese tipo anteriores a hoy dejan de contar",
    )
    recalc.add_argument(
        "--claude-dir",
        default=None,
        help="directorio de Claude Code (default: ~/.claude); solo se lee",
    )
    recalc.set_defaults(func=cmd_recalcular_coste)

    _add_install_parsers(sub)
    return parser


def _add_common_install_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--clients",
        action="append",
        choices=("auto", "claude", "codex", "opencode"),
        default=None,
        help="cliente a configurar (repetible; default: auto = los que estén instalados)",
    )
    p.add_argument(
        "--target",
        action="append",
        choices=("claude", "codex", "opencode", "all"),
        default=None,
        help="histórico, equivale a --clients; `all` fuerza los tres aunque no estén instalados",
    )
    p.add_argument("--home", default=None, help="HOME alternativo (para pruebas)")
    p.add_argument("--dry-run", action="store_true", help="describe los cambios sin escribir")
    p.add_argument(
        "--python",
        default=None,
        help="intérprete con el que se ejecutan los hooks (default: python3 / python en Windows)",
    )
    p.add_argument(
        "--no-hooks", dest="hooks", action="store_false", help="no instalar los hooks consultivos"
    )
    p.add_argument(
        "--no-skill",
        dest="skill",
        action="store_false",
        help="no instalar la skill delegacion-local",
    )
    p.add_argument(
        "--no-memory",
        dest="memory",
        action="store_false",
        help="no tocar CLAUDE.md / AGENTS.md globales",
    )
    p.add_argument(
        "--no-mcp",
        dest="mcp",
        action="store_false",
        help="no registrar el servidor MCP en la config del cliente",
    )
    # El único componente que se pide, en vez de excluirse: los subagentes son ficheros del
    # usuario, no andamiaje nuestro, así que tocarlos sin que lo pida sería el mismo error que
    # el viejo `--target all` creando `~/.codex/` en máquinas sin Codex.
    p.add_argument(
        "--agents",
        dest="agents",
        action="store_true",
        help="actualiza ~/.claude/agents que ya declaren tools local_* (opt-in)",
    )
    p.add_argument(
        "--no-client-cli",
        action="store_true",
        help="no usar el binario `claude`; edita ~/.claude.json directamente",
    )
    p.set_defaults(hooks=True, skill=True, memory=True, mcp=True)


def _add_install_parsers(sub) -> None:
    install = sub.add_parser(
        "install",
        help="Instala hooks, skill, memoria y la entrada MCP en Claude Code / Codex / opencode.",
        description=(
            "Instala la integración completa en el HOME del usuario: hooks consultivos, la "
            "skill delegacion-local, un bloque gestionado en CLAUDE.md/AGENTS.md y la entrada "
            "del servidor MCP. Es idempotente (bloques con marcadores, backups .bak) y se "
            "revierte con `local-delegate uninstall`."
        ),
    )
    _add_common_install_args(install)
    install.add_argument(
        "--enable-read-hook",
        action="store_true",
        help="registra y ENCIENDE el hook experimental PreToolUse/Read (apagado por defecto)",
    )
    install.add_argument(
        "--mcp-mode",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio (uvx, default) o http (daemon compartido en /mcp)",
    )
    install.add_argument(
        "--base-url",
        default=None,
        help="LOCAL_DELEGATE_BASE_URL de la entrada MCP (p. ej. el backend remoto de otra máquina)",
    )
    install.add_argument(
        "--api-key-env",
        action="store_true",
        help="reenvía LOCAL_DELEGATE_API_KEY desde el entorno (nunca escribe el secreto)",
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
        help=(
            "con --mcp-mode http, autentica contra el daemon referenciando "
            "LOCAL_DELEGATE_WEB_TOKEN del entorno (nunca escribe el secreto). Sin este flag ni "
            "--no-web-token-env, se conserva la cabecera que ya tuviera la entrada"
        ),
    )
    token.add_argument(
        "--no-web-token-env",
        dest="web_token_env",
        action="store_const",
        const=False,
        help="quita la cabecera de autorización de la entrada MCP aunque ya la tuviera",
    )
    install.add_argument(
        "--pin-version",
        default=None,
        help="fija la versión del paquete en la entrada MCP (p. ej. 0.11.0)",
    )
    install.add_argument(
        "--force-mcp-codex",
        action="store_true",
        help="reemplaza sin preguntar una entrada de Codex escrita a mano (deja .bak)",
    )
    install.set_defaults(func=cmd_install)

    upd = sub.add_parser(
        "update",
        help="Actualiza el pin, completa lo que falte del andamiaje y deja el daemon arriba.",
        description=(
            "Revisa el estado real de la máquina con las mismas comprobaciones que `doctor`, "
            "actualiza el pin de versión donde exista, completa la configuración que falte y "
            "termina dejando el daemon arriba: lo reinicia si corría, lo levanta si no. El "
            "backend de inferencia no se toca salvo que se pida con --restart-backend."
        ),
    )
    upd.add_argument("--dry-run", action="store_true", help="describe los cambios sin escribir")
    upd.add_argument("--home", default=None, help="HOME alternativo (para pruebas)")
    upd.add_argument(
        "--version",
        default=None,
        help="versión a fijar en el pin (default: la última publicada en PyPI)",
    )
    upd.add_argument(
        "--restart-backend",
        action="store_true",
        help="reinicia también llama-swap (por defecto NO se toca: descarga los modelos de VRAM)",
    )
    upd.add_argument(
        "--no-restart", action="store_true", help="no toca el daemon; solo repara e informa"
    )
    upd.set_defaults(func=cmd_update)

    uninstall = sub.add_parser(
        "uninstall",
        help="Revierte lo que instaló `local-delegate install` (solo lo suyo).",
    )
    _add_common_install_args(uninstall)
    uninstall.set_defaults(func=cmd_uninstall)


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
