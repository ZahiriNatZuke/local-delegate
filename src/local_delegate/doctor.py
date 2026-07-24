"""doctor.py — diagnóstico de instalación/entorno del backend local (subcomando ``doctor``).

Complementa a la tool MCP ``local_status`` (que mira el *runtime*: backend vivo, modelos,
VRAM/RAM) chequeando la *instalación*: qué versiones de ``llama-server`` (llama.cpp) y
``llama-swap`` tienes instaladas, y si conviene actualizarlas respecto a las versiones que
esta release ha probado (``RECOMMENDED_VERSIONS``). Con ``--online`` consulta además la última
release publicada en GitHub.

Todo es best-effort y de solo lectura: cualquier binario ausente, salida inesperada o fallo de
red degrada a un aviso y nunca lanza. No requiere el extra ``[llamaswap]``: la ruta de
``llama-server`` se saca del ``config.yaml`` con una lectura de texto (sin pyyaml).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import autostart, config

# --- Fuente de verdad de versiones probadas ----------------------------------------------
# Versiones del backend verificadas en vivo con esta release de local-delegate. La doc
# (docs/wiki/Backend-versions.md) las referencia desde aquí para no divergir.
RECOMMENDED_VERSIONS: dict[str, str] = {
    # llama.cpp, probado 2026-07-11 en RTX 5060 (Blackwell/sm_120) con runtime CUDA 13.3.
    "llama-server": "b9925",
    "llama-swap": "v238",
}

# Repos de GitHub para el chequeo opcional --online.
_GITHUB_REPOS: dict[str, str] = {
    "llama-server": "ggml-org/llama.cpp",
    "llama-swap": "mostlygeek/llama-swap",
}
_RISK_TERMS = re.compile(
    r"\b(deadlock|hang|freeze|crash|regression|oom|cuda|windows|ttl|unload|corrupt|security)\b",
    re.IGNORECASE,
)

# Una rolling release nueva no se promueve directamente. Primero debe acumular este tiempo sin
# una regresión relevante y después pasar el canary local.
MIN_RELEASE_SOAK_DAYS = 7

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _vnum(version: str | None) -> int | None:
    """Extrae el número de una versión ('v238' -> 238, 'b9925' -> 9925). None si no hay."""
    if not version:
        return None
    m = re.search(r"(\d+)", version)
    return int(m.group(1)) if m else None


def _run_version(exe: str) -> str | None:
    """Corre ``<exe> --version`` y devuelve stdout+stderr. None si el binario no está o falla."""
    try:
        out = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (out.stdout or "") + (out.stderr or "")


def detect_llamaswap_version() -> str | None:
    """Versión instalada de llama-swap ('v238'), vía LLAMASWAP_EXE o el PATH. None si no se pudo."""
    exe = autostart._find_exe()
    if not exe:
        return None
    text = _run_version(exe)
    if not text:
        return None
    m = re.search(r"\bv(\d+)\b", text)
    return f"v{m.group(1)}" if m else None


def _llamaserver_exe_from_config(config_path: Path) -> str | None:
    """Ruta del binario de llama-server sacada del primer ``cmd`` del config.yaml (lectura de texto).

    No usa pyyaml a propósito: así el doctor funciona sin el extra [llamaswap]. Robusto con rutas
    Windows ('D:\\...\\llama-server.exe') y POSIX ('/usr/bin/llama-server').
    """
    try:
        raw = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"""[^\s'"]*llama-server(?:\.exe)?""", raw)
    return m.group(0) if m else None


def detect_llamaserver_version(config_path: Path | None) -> tuple[str | None, str | None]:
    """Versión instalada de llama-server ('b9925') a partir del config.yaml.

    Devuelve (version, motivo_fallo). Si version es None, motivo_fallo explica por qué (sin
    config, sin ruta en el cmd, binario ausente…) para que el doctor lo muestre.
    """
    if not config_path:
        return None, "no hay --config ni LLAMASWAP_CONFIG (no se puede localizar llama-server)"
    if not config_path.is_file():
        return None, f"config no encontrado: {config_path}"
    exe = _llamaserver_exe_from_config(config_path)
    if not exe:
        return None, "no se encontró la ruta de llama-server en los 'cmd' del config"
    text = _run_version(exe)
    if not text:
        return None, f"no se pudo ejecutar {exe} --version"
    m = re.search(r"version:\s*(\d+)", text)
    if not m:
        return None, f"salida de --version inesperada de {exe}"
    return f"b{m.group(1)}", None


def latest_github_info(component: str) -> dict[str, str] | None:
    """Metadatos de la última release de GitHub. Best-effort y sin autenticación requerida."""
    repo = _GITHUB_REPOS.get(component)
    if not repo:
        return None
    try:
        import httpx

        with httpx.Client(timeout=5.0) as c:
            r = c.get(f"https://api.github.com/repos/{repo}/releases/latest")
            r.raise_for_status()
            data = r.json()
            tag = data.get("tag_name")
            if not isinstance(tag, str):
                return None
            return {
                "tag": tag,
                "published_at": str(data.get("published_at") or ""),
                "url": str(data.get("html_url") or ""),
            }
    except Exception:
        return None


def latest_github(component: str) -> str | None:
    """Último tag publicado; wrapper conservado para consumidores anteriores."""
    info = latest_github_info(component)
    return info["tag"] if info else None


def _select_relevant_issues(items: list[dict], limit: int = 3) -> list[dict[str, str | int]]:
    """Filtra issues recientes por señales de riesgo; excluye pull requests."""
    result: list[dict[str, str | int]] = []
    for item in items:
        if "pull_request" in item:
            continue
        title = str(item.get("title") or "")
        # El cuerpo de issues de feature suele mencionar plataformas o fallos hipotéticos y genera
        # demasiados falsos positivos. El título es una señal deliberadamente conservadora.
        if not _RISK_TERMS.search(title):
            continue
        result.append(
            {
                "number": int(item.get("number") or 0),
                "title": title,
                "url": str(item.get("html_url") or ""),
            }
        )
        if len(result) >= limit:
            break
    return result


def recent_relevant_issues(component: str) -> list[dict[str, str | int]]:
    """Issues abiertos y recientes que ameritan revisión antes de un canary. Best-effort."""
    repo = _GITHUB_REPOS.get(component)
    if not repo:
        return []
    try:
        import httpx

        with httpx.Client(timeout=5.0) as client:
            response = client.get(
                f"https://api.github.com/repos/{repo}/issues",
                params={"state": "open", "sort": "updated", "direction": "desc", "per_page": 30},
            )
            response.raise_for_status()
            data = response.json()
            return _select_relevant_issues(data if isinstance(data, list) else [])
    except Exception:
        return []


def _release_age_days(published_at: str, now: datetime | None = None) -> int | None:
    """Edad completa de una release ISO-8601; None ante una fecha ausente o inválida."""
    if not published_at:
        return None
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    current = now or datetime.now(UTC)
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    return max(0, (current - published).days)


def _compare_line(component: str, installed: str | None, online: bool) -> tuple[str, bool]:
    """Arma la línea de estado de un componente y si cuenta como warning.

    Devuelve (línea, es_warning). WARN si la instalada es más vieja que la probada.
    """
    recommended = RECOMMENDED_VERSIONS[component]
    inst_n, rec_n = _vnum(installed), _vnum(recommended)
    release = latest_github_info(component) if online else None
    latest = release["tag"] if release else None
    lat_n = _vnum(latest)

    extra = ""
    if latest:
        if lat_n is not None and rec_n is not None and lat_n > rec_n:
            age = _release_age_days(release.get("published_at", "")) if release else None
            if age is None:
                gate = "edad desconocida; revisar antes del canary"
            elif age < MIN_RELEASE_SOAK_DAYS:
                gate = f"HOLD: {age}d de {MIN_RELEASE_SOAK_DAYS}d mínimos"
            else:
                gate = f"{age}d; candidata a canary, no a promoción directa"
            extra = f" · última en GitHub: {latest} (más nueva; {gate})"
        else:
            extra = f" · última en GitHub: {latest}"

    if installed is None:
        return f"[ -- ] {component}: no detectado (probada: {recommended}){extra}", False
    if inst_n is not None and rec_n is not None and inst_n < rec_n:
        return (
            f"[WARN] {component}: {installed} instalada < {recommended} probada — "
            f"considera actualizar{extra}",
            True,
        )
    if inst_n is not None and rec_n is not None and inst_n > rec_n:
        return (
            f"[ OK ] {component}: {installed} (más nueva que la probada {recommended}){extra}",
            False,
        )
    return f"[ OK ] {component}: {installed} (= probada){extra}", False


def _backend_up() -> bool:
    """True si el endpoint OpenAI-compatible responde a /models (best-effort)."""
    try:
        import httpx

        with httpx.Client(timeout=2.0) as c:
            return c.get(f"{config.BASE_URL}/models", headers=config.auth_headers()).is_success
    except Exception:
        return False


def run_doctor(args: argparse.Namespace) -> int:
    """Imprime el diagnóstico de instalación y devuelve exit code (0 OK, 1 hay warnings)."""
    config_path: Path | None = None
    if getattr(args, "config", None):
        config_path = Path(args.config)
    elif os.environ.get("LLAMASWAP_CONFIG"):
        config_path = Path(os.environ["LLAMASWAP_CONFIG"])

    warnings = False
    print("local-delegate doctor — diagnóstico de instalación del backend local")
    print("")

    # Entorno
    exe = os.environ.get("LLAMASWAP_EXE", "")
    print(f"LLAMASWAP_EXE:    {exe or '(no seteado; se busca llama-swap en el PATH)'}")
    print(f"LLAMASWAP_CONFIG: {config_path or '(no seteado)'}")
    print(f"Backend BASE_URL: {config.BASE_URL} — {'arriba' if _backend_up() else 'CAÍDO'}")
    print("")

    # Versiones
    if args.online:
        print("Versiones (instalada vs probada; consultando GitHub por la última)…")
    else:
        print("Versiones (instalada vs probada; usa --online para comparar con GitHub):")

    ls_installed = detect_llamaswap_version()
    line, warn = _compare_line("llama-swap", ls_installed, args.online)
    print(f"  {line}")
    warnings = warnings or warn

    lsrv_installed, reason = detect_llamaserver_version(config_path)
    if lsrv_installed is None and reason:
        recommended = RECOMMENDED_VERSIONS["llama-server"]
        print(f"  [ -- ] llama-server: no detectado (probada: {recommended}) — {reason}")
    else:
        line, warn = _compare_line("llama-server", lsrv_installed, args.online)
        print(f"  {line}")
        warnings = warnings or warn

    if args.online:
        print("")
        print("Issues abiertos con señales de riesgo (revisión manual antes de canary):")
        for component in ("llama-swap", "llama-server"):
            issues = recent_relevant_issues(component)
            if not issues:
                print(
                    f"  [ -- ] {component}: ninguno detectado en los 30 actualizados más recientes"
                )
                continue
            for issue in issues:
                print(f"  [HOLD] {component} #{issue['number']}: {issue['title']} · {issue['url']}")

    print("")
    if warnings:
        print("Resultado: hay actualizaciones sugeridas (ver [WARN] arriba).")
        return 1
    print("Resultado: todo al día respecto a las versiones probadas.")
    return 0
