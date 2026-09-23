"""Banco de pruebas con `claude -p` (SDD subagente-lector-local, spec v2).

Lo comparten el control instalado (tarea 4) y el experimento de adopción (tarea 5). Todo lo que
aquí parece exceso de cuidado salió de una revisión adversarial que encontró la forma de que el
experimento midiera el entorno en vez del producto (`review.md`):

- **Entorno por `--settings`, no por variables del proceso.** El bloque `env` del
  `settings.json` del usuario pisaría a las del proceso; `--settings` tiene más precedencia. Y el
  control de precedencia al inicio de cada tanda lo comprueba en vez de suponerlo.
- **El interruptor global de apagado nunca se toca**: afecta a las sesiones del usuario y dispara
  el criterio de retirada del bloqueo. Se aísla con `LD_HOOK_READ_INTERRUPTOR` a una ruta que no
  existe.
- **Telemetría propia de cada corrida**, para atribuir cada evento a su corrida sin cruces.
- **La evidencia sale del transcript**, nunca de lo que el modelo diga que hizo.

El formato del transcript es interno de Claude Code y cambia entre versiones: si falta algo que
se espera, se lanza `FormatoDesconocido` en vez de devolver ceros.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PROYECTOS = Path.home() / ".claude" / "projects"
TOOL_PRINCIPAL = "mcp__local-delegate__local_summarize"
PREFIJO_LOCAL = "mcp__local-delegate__local_"
#: Resultado de Bash por encima del cual contar como «volcado» si el comando nombra el fichero.
UMBRAL_VOLCADO = 2048
#: Marcas del texto de los bloqueos de nuestros hooks (Read y Shell).
MARCAS_DE_BLOQUEO = ("y es prosa", "de prosa al contexto")


class FormatoDesconocido(RuntimeError):
    """El transcript o la salida de `claude -p` no tienen la forma que se espera."""


@dataclass
class Corrida:
    session_id: str
    resultado: str
    coste_usd: float
    inicio: str
    fin: str
    error: str = ""
    model_usage: dict = field(default_factory=dict)


def ahora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def dir_de_proyecto(cwd: Path) -> Path:
    """Dónde guarda Claude Code los transcripts de una sesión lanzada en `cwd`."""
    return PROYECTOS / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def escribir_settings(destino: Path, env: dict[str, str]) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({"env": env}, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino


def env_de_tanda(telemetria: Path, interruptor: Path, *, hooks: bool = True) -> dict[str, str]:
    return {
        "LD_HOOK_TELEMETRY_LOG": str(telemetria),
        "LD_HOOK_READ_BLOQUEAR": "1",
        "LD_HOOK_READ_INTERRUPTOR": str(interruptor),
        "LD_HOOK_ENABLED": "1" if hooks else "0",
    }


def correr(
    prompt: str,
    cwd: Path,
    settings: Path,
    *,
    modelo: str = "opus",
    max_turns: int = 12,
    timeout_s: int = 900,
) -> Corrida:
    """Una sesión nueva de `claude -p`. No reintenta: eso lo decide quien llama."""
    inicio = ahora()
    argv = [
        "claude",
        "-p",
        "--model",
        modelo,
        "--settings",
        str(settings),
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        str(max_turns),
        prompt,
    ]
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Corrida("", "", 0.0, inicio, ahora(), error="timeout")
    final = None
    for linea in proc.stdout.splitlines():
        try:
            evento = json.loads(linea)
        except json.JSONDecodeError:
            continue
        if evento.get("type") == "result":
            final = evento
    if final is None:
        return Corrida("", "", 0.0, inicio, ahora(), error=f"sin resultado: {proc.stderr[-300:]}")
    return Corrida(
        session_id=str(final.get("session_id") or ""),
        resultado=str(final.get("result") or ""),
        coste_usd=float(final.get("total_cost_usd") or 0.0),
        inicio=inicio,
        fin=ahora(),
        error="api" if final.get("is_error") else "",
        model_usage=final.get("modelUsage") or {},
    )


def leer_transcript(cwd: Path, session_id: str, *, espera_s: float = 5.0) -> list[dict]:
    ruta = dir_de_proyecto(cwd) / f"{session_id}.jsonl"
    limite = time.monotonic() + espera_s
    while not ruta.is_file() and time.monotonic() < limite:
        time.sleep(0.2)
    if not ruta.is_file():
        raise FormatoDesconocido(f"no aparece el transcript de la sesión {session_id}")
    return [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines() if linea]


def _misma_ruta(a: str, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(str(b)))
    except (TypeError, ValueError):
        return False


def _texto(contenido) -> str:
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        return "".join(str(c.get("text", "")) for c in contenido if isinstance(c, dict))
    return ""


def analizar(eventos: list[dict], fichero: Path) -> dict:
    """Qué hizo el hilo principal con `fichero`, leído del transcript (nunca del informe)."""
    diferidas = None
    usos: dict[str, dict] = {}
    resultados: dict[str, dict] = {}
    for evento in eventos:
        if evento.get("isSidechain"):
            continue
        adjunto = evento.get("attachment")
        if isinstance(adjunto, dict) and adjunto.get("type") == "deferred_tools_delta":
            # Es un DELTA: llegan varios y cada uno añade o quita nombres. Quedarse con el último
            # daba «no diferidas» en el control instalado (tarea 4) con las tools ahí.
            diferidas = (diferidas or set()) | set(adjunto.get("addedNames") or [])
            diferidas -= set(adjunto.get("removedNames") or [])
        contenido = (evento.get("message") or {}).get("content")
        for bloque in contenido if isinstance(contenido, list) else []:
            if bloque.get("type") == "tool_use":
                usos[bloque["id"]] = bloque
            elif bloque.get("type") == "tool_result":
                resultados[bloque.get("tool_use_id", "")] = bloque
    if diferidas is None:
        raise FormatoDesconocido("el transcript no trae `deferred_tools_delta`")

    salida = {
        "tools_diferidas": TOOL_PRINCIPAL in diferidas,
        "read_completo": False,
        "read_franjas": 0,
        "volcado_bash": False,
        "local_con_path": [],
        "toolsearch": False,
        "bloqueado": False,
    }
    for uid, uso in usos.items():
        nombre, entrada = uso.get("name", ""), uso.get("input") or {}
        resultado = resultados.get(uid) or {}
        texto_resultado = _texto(resultado.get("content"))
        if resultado.get("is_error") and any(m in texto_resultado for m in MARCAS_DE_BLOQUEO):
            salida["bloqueado"] = True
            continue  # una lectura denegada no metió nada en el contexto
        if nombre == "ToolSearch":
            salida["toolsearch"] = True
        elif nombre == "Read" and _misma_ruta(str(entrada.get("file_path", "")), fichero):
            if entrada.get("offset") is not None or entrada.get("limit") is not None:
                salida["read_franjas"] += 1
            else:
                salida["read_completo"] = True
        elif nombre in ("Bash", "PowerShell"):
            comando = str(entrada.get("command", ""))
            if fichero.name in comando and len(texto_resultado) > UMBRAL_VOLCADO:
                salida["volcado_bash"] = True
        elif (
            nombre.startswith(PREFIJO_LOCAL)
            and _misma_ruta(str(entrada.get("path", "")), fichero)
            and not resultado.get("is_error")
        ):
            salida["local_con_path"].append(nombre)
    salida["contenido_en_contexto"] = (
        salida["read_completo"] or salida["read_franjas"] > 0 or salida["volcado_bash"]
    )
    return salida


def eventos_de_telemetria(ruta: Path) -> list[dict]:
    if not ruta.is_file():
        return []
    return [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines() if linea]


def corrida_valida(telemetria: list[dict], session_id: str) -> bool:
    """El hook de prompt deja un evento en TODO prompt: si no está, con el bloqueo encendido, la
    corrida no corrió con los hooks que se querían medir."""
    return any(
        e.get("event") == "UserPromptSubmit"
        and e.get("session_id") == session_id
        and e.get("bloqueo") == "encendido"
        for e in telemetria
    )


def anotar_ventana(destino: Path, tanda: str, corridas: list[Corrida]) -> None:
    """Ventana de la tanda (+10 min: los modelos quedan calientes) y sus sesiones, para excluirlas."""
    datos = {"sesiones": [], "ventanas": []}
    if destino.is_file():
        datos = json.loads(destino.read_text(encoding="utf-8"))
    validas = [c for c in corridas if c.inicio]
    if not validas:
        return
    fin = datetime.fromisoformat(max(c.fin for c in validas)).timestamp() + 600
    datos.setdefault("ventanas", []).append(
        {
            "tanda": tanda,
            "inicio": min(c.inicio for c in validas),
            "fin": datetime.fromtimestamp(fin, UTC).isoformat(timespec="seconds"),
        }
    )
    conocidas = {s["session_id"] for s in datos.setdefault("sesiones", [])}
    for c in validas:
        if c.session_id and c.session_id not in conocidas:
            datos["sesiones"].append(
                {"session_id": c.session_id, "inicio": c.inicio, "fin": c.fin, "motivo": tanda}
            )
    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def confirmar(corridas: int, coste_por_corrida: float, *, si: bool) -> bool:
    print(
        f"Se van a lanzar {corridas} corridas de `claude -p` (~{coste_por_corrida:.2f} USD de "
        f"lista cada una, ~{corridas * coste_por_corrida:.0f} USD en total) contra tu cuota."
    )
    if si:
        return True
    try:
        return input("¿Seguir? [s/N]: ").strip().lower() in {"s", "si", "sí", "y", "yes"}
    except EOFError:
        return False


def control_de_precedencia(banco: Path, fichero_prosa: Path, interruptor: Path) -> bool:
    """Con `LD_HOOK_ENABLED=0` por `--settings`, el `Read` completo de prosa grande NO se deniega.

    Si se deniega, el `env` del usuario manda sobre `--settings` y nada de lo que sigue mediría la
    variante que dice: la tanda aborta, no reintenta.
    """
    settings = escribir_settings(
        banco / "settings-precedencia.json",
        env_de_tanda(banco / "telemetria-precedencia.jsonl", interruptor, hooks=False),
    )
    corrida = correr(
        f"Lee entero el fichero {fichero_prosa} con la tool Read (sin offset ni limit) y dime "
        "solo su primera línea.",
        banco,
        settings,
        max_turns=4,
    )
    if corrida.error or not corrida.session_id:
        return False
    visto = analizar(leer_transcript(banco, corrida.session_id), fichero_prosa)
    return visto["read_completo"] and not visto["bloqueado"]
