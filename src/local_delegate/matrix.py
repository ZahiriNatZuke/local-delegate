"""Matriz de afinidad tool × modelo alternativo (REQ-010 a REQ-013, T15).

Una celda dice que, para una tool, un modelo alternativo ya cargado responde tan bien como el
modelo de su rol (medido en la evaluación de T5/T6, `benchmarks/afinidad-2026-10/veredicto.json`).
Si el alternativo está cargado y con margen, la operación lo usa en vez de cargar el del rol.

- **Las celdas viven aquí y solo aquí** (`CELLS`): `veredicto.json` no viaja en el paquete, y un
  test compara esta tupla con sus celdas `aprobada` (REQ-043). Vaciar la tupla apaga la afinidad
  entera (el rollback de T15): sin celdas, el daemon se comporta como en T14.
- **Una celda solo vale para el modelo EXACTO que se midió** (`is_current`): la huella de la config
  vigente (GGUF, flags que cambian el modelo, `sha256` del prompt de la tool) tiene que ser la de la
  celda. Si no, la celda cuenta como «sin base» y `doctor` lo avisa.
- **Direcciones de REQ-011** como guarda (`allowed_direction`): una celda fuera de ellas no se usa
  aunque esté en la tupla.
- `choose` es **pura** (REQ-012): recibe la foto de REQ-013 ya tomada (`Observed`) y no toca la red.

Este módulo no importa `server`: el prompt de la tool y la config de llama-swap le llegan como
argumentos.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import footprint as footprint_mod

#: Tools del rol mecánico (REQ-011). `local_summarize` queda fuera de la evaluación (Non-goals).
MECHANICAL_TOOLS = frozenset(
    {"local_classify", "local_delegate", "local_extract", "local_lint_summary", "local_translate"}
)
#: La única tool de código con dirección: hacia el modelo del rol largo.
COMMIT_TOOL = "local_commit_msg"


@dataclass(frozen=True)
class Cell:
    """Una celda aprobada: (tool, alternativo, modelo del rol con el que se comparó) y su huella.

    `footprint` es la huella del ALTERNATIVO tal como la escribió la evaluación (`huella` en
    `veredicto.json`): la de `footprint.footprint` con su config y el prompt de la tool.
    """

    tool: str
    alternative: str
    compared_role: str
    footprint: Mapping[str, Any] = field(hash=False)


def _gemma_26b(prompt_sha256: str) -> dict[str, Any]:
    """La huella del 26B medida en la evaluación (la config real del 2026-10-07)."""
    return {
        "flags": {
            "cache_type_k": None,
            "cache_type_v": None,
            "ctx_size": 38400,
            "mmproj": None,
            "n_cpu_moe": 12,
            "reasoning": "off",
        },
        "prompt_sha256": prompt_sha256,
        "ruta": "D:\\Projects\\llms\\models\\gemma4-26b-a4b\\gemma-4-26B-A4B-it-UD-IQ4_XS.gguf",
        "tamano_bytes": 13597177568,
    }


def _qwen_36(prompt_sha256: str) -> dict[str, Any]:
    """La huella de Qwen3.6 medida en la evaluación (la config real del 2026-10-07)."""
    return {
        "flags": {
            "cache_type_k": None,
            "cache_type_v": None,
            "ctx_size": 16384,
            "mmproj": None,
            "n_cpu_moe": 20,
            "reasoning": "off",
        },
        "prompt_sha256": prompt_sha256,
        "ruta": "D:\\Projects\\llms\\models\\qwen36-35b-a3b\\Qwen3.6-35B-A3B-UD-IQ4_XS.gguf",
        "tamano_bytes": 17730509792,
    }


_TRANSLATE_PROMPT = "146a43ac5f5b129d7f93e76cda4a3d46ebc65395557aa1b81533cf45e10f13e5"
_LINT_PROMPT = "5202980b8aab9b7676889f5e7e7b1ba00a7c6cd38cd3111a8f9f71ca6d016838"
_DELEGATE_PROMPT = "804bdc0a8674dfef530698a753cfcd6c4546e89b5d434d647cda0321b260615b"

#: Las celdas `aprobada` del veredicto de T6 (`solo_mecanicas: false`), todas frente al rol
#: mecánico (`gemma3-4b`). Las siete `rechazada` (incluida `local_commit_msg`) no están.
CELLS: tuple[Cell, ...] = (
    Cell("local_translate", "gemma4-26b-a4b", "gemma3-4b", _gemma_26b(_TRANSLATE_PROMPT)),
    Cell("local_translate", "qwen36-35b-a3b", "gemma3-4b", _qwen_36(_TRANSLATE_PROMPT)),
    Cell("local_lint_summary", "gemma4-26b-a4b", "gemma3-4b", _gemma_26b(_LINT_PROMPT)),
    Cell("local_delegate", "gemma4-26b-a4b", "gemma3-4b", _gemma_26b(_DELEGATE_PROMPT)),
)

#: Con qué parámetros construyó cada tool sus prompts de sistema en el corpus de la evaluación
#: (`cases.json`). La huella del prompt es el `sha256` de esos prompts, distintos, ordenados y
#: unidos por un salto de línea (`scripts/dev/affinity_batch.py`, `tool_prompt`). `server` los
#: vuelve a construir con el código vigente: cambiar `_guard` o el texto de una tool cambia la
#: huella y deja la celda «sin base».
PROMPT_INPUTS: Mapping[str, tuple[Any, ...]] = {
    "local_translate": ("español", "inglés"),
    "local_lint_summary": (200,),
    "local_delegate": (
        "Solo el texto en mayúsculas, en una línea",
        "Solo la fecha con el formato AAAA-MM-DD",
        "Solo un número entero, sin texto adicional",
        "Una sola línea con los valores separados por comas, sin espacios",
        "lista Markdown con una viñeta '- ' por elemento",
    ),
}


def joined_prompt(systems: Collection[str]) -> str:
    """El prompt que entra en la huella: los distintos, ordenados y unidos por `\\n`."""
    return "\n".join(sorted(set(systems)))


def allowed_direction(cell: Cell, role_name: str | None, roles: Mapping[str, str]) -> bool:
    """REQ-011: solo estas direcciones existen; las demás celdas no se evalúan.

    - tools del rol mecánico, usadas en el rol mecánico → modelo del rol largo o de código;
    - `local_commit_msg` (rol de código) → modelo del rol largo;
    - nunca una tool de código o de largo hacia el modelo mecánico.

    `roles` es `config.modelos_por_rol()`: si una variable cambia el modelo de un rol, la celda
    medida contra el de antes ya no coincide.
    """
    mechanical = roles.get("mechanical")
    if cell.alternative == mechanical:
        return False
    if cell.tool in MECHANICAL_TOOLS:
        return (
            role_name == "mechanical"
            and cell.compared_role == mechanical
            and cell.alternative in (roles.get("long"), roles.get("code"))
        )
    if cell.tool == COMMIT_TOOL:
        return (
            role_name == "code"
            and cell.compared_role == roles.get("code")
            and cell.alternative == roles.get("long")
        )
    return False


def current_footprint(model_cfg: Mapping[str, Any], prompt: str) -> dict[str, Any]:
    """La huella vigente de un modelo de la config de llama-swap con el prompt de la tool."""
    return footprint_mod.footprint(model_cfg, prompt)


def footprint_differences(cell: Cell, current: Mapping[str, Any]) -> list[str]:
    """Qué cambió entre la huella de la celda y la vigente (vacío si coinciden)."""
    differences: list[str] = []
    for key in ("ruta", "tamano_bytes", "prompt_sha256"):
        if cell.footprint.get(key) != current.get(key):
            differences.append(key)
    old_flags = cell.footprint.get("flags") or {}
    new_flags = current.get("flags") or {}
    for key in sorted(set(old_flags) | set(new_flags)):
        if old_flags.get(key) != new_flags.get(key):
            differences.append(f"{key} {old_flags.get(key)} -> {new_flags.get(key)}")
    return differences


def is_current(cell: Cell, model_cfg: Mapping[str, Any] | None, prompt: str | None) -> bool:
    """La celda vale para la config vigente: su huella es la del modelo y el prompt de hoy.

    Sin entrada en la config o sin prompt conocido de la tool no hay con qué comparar: «sin base».
    """
    if model_cfg is None or prompt is None:
        return False
    return not footprint_differences(cell, current_footprint(model_cfg, prompt))


# --------------------------------------------------------------------------------------------
# La foto de REQ-013 y la elección de REQ-012
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Observed:
    """La foto `observado` de REQ-013, ya tomada. Lo que falta cuenta como «no se sabe».

    Todo va por el **id real** de llama-swap (el de `/running`, `/api/events` y la actividad):

    - `ready`: modelos que `/running` da `ready`; `ttl`: su TTL efectivo;
    - `in_flight`: peticiones en vuelo por modelo de `/api/events` (de cualquier cliente), o
      `None` si la consulta falló;
    - `last_end`: hora (reloj del sistema) en que terminó la última petición de cada modelo, de
      `/api/metrics/activity`;
    - `now`: `time.time()` al tomar la foto; `margin_s`: `config.AFFINITY_MARGIN_S`;
    - `clashes`: la relación de choques de la topología vigente;
    - `alias`: el id real de cada nombre con que se pregunta (los de la reserva). Cada método
      traduce su argumento con él, así que se le puede preguntar con el nombre de la reserva.
    """

    now: float
    margin_s: float
    clashes: Callable[[str, str], bool]
    ready: frozenset[str] = frozenset()
    ttl: Mapping[str, int] = field(default_factory=dict)
    in_flight: Mapping[str, int] | None = None
    last_end: Mapping[str, float] = field(default_factory=dict)
    alias: Mapping[str, str] = field(default_factory=dict)

    def real(self, model: str) -> str:
        return self.alias.get(model, model)

    def is_ready(self, model: str) -> bool:
        return self.real(model) in self.ready

    def busy(self, model: str) -> bool:
        return bool(self.in_flight and self.in_flight.get(self.real(model), 0) > 0)

    def pending_switch(self, model: str) -> bool:
        """(b) Hay en vuelo una petición para un modelo que choca con `model` y no está `ready`:
        un cambio de modelo pendiente de otro cliente."""
        if self.in_flight is None:
            return True  # sin la foto de peticiones no se sabe: no cuenta como cargado
        real = self.real(model)
        return any(
            count > 0 and other != real and other not in self.ready and self.clashes(real, other)
            for other, count in self.in_flight.items()
        )

    def needs_activity(self, model: str) -> bool:
        """La consulta de actividad solo hace falta si (a) y (b) se cumplen y (c) no se resuelve
        con lo anterior (sin petición en vuelo y con TTL distinto de 0)."""
        return (
            self.is_ready(model)
            and not self.pending_switch(model)
            and not self.busy(model)
            and self.ttl.get(self.real(model)) not in (0, None)
        )

    def ttl_left(self, model: str) -> float:
        """TTL restante: infinito con `ttl: 0` o con una petición en vuelo (el reloj de llama-swap
        está congelado); `-inf` si no se sabe."""
        real = self.real(model)
        ttl = self.ttl.get(real)
        if ttl == 0 or self.busy(model):
            return math.inf
        end = self.last_end.get(real)
        if ttl is None or end is None:
            return -math.inf
        return ttl - (self.now - end)

    def loaded_with_margin(self, model: str) -> bool:
        """REQ-013: (a) `ready`, (b) sin cambio de modelo pendiente y (c) en vuelo, TTL 0 o con
        `ttl − (ahora − fin) ≥ margen`."""
        if not self.is_ready(model) or self.pending_switch(model):
            return False
        return self.ttl_left(model) >= self.margin_s


def needs_snapshot(grantable: Collection[str], role: str, own: Collection[str]) -> bool:
    """REQ-013: la foto solo se pide si `A'` tiene alternativos fuera de `propios` y el rol no
    está en `propios`. Con el rol en uso por el propio daemon no se consulta nada."""
    if role in own:
        return False
    return any(model != role and model not in own for model in grantable)


def choose(
    grantable: Collection[str],
    role: str,
    observed: Observed | None,
    own: Collection[str],
    *,
    approved: Collection[str],
    chain_order: Sequence[str] = (),
) -> str | None:
    """REQ-012, pura. `observed` es la foto ya tomada (o `None` si no hizo falta).

    1. el rol, si está en `A'` y en `propios` o la foto lo da `ready`;
    2. si no, entre los alternativos de `A'` con celda aprobada que están en `propios` o cargados
       con margen, el primero por: con una petición en vuelo (propia o ajena); más TTL restante
       (`ttl: 0` = infinito); el orden de la cadena del rol; el id;
    3. si no, el rol. **`None`** si el rol no está en `A'` (el salto a `loaded`): no queda ningún
       miembro que cumpla REQ-012 y el paso se salta sin gastar salto (REQ-019).
    """
    if role in grantable and (role in own or (observed is not None and observed.is_ready(role))):
        return role
    candidates = [
        model
        for model in grantable
        if model != role
        and model in approved
        and (model in own or (observed is not None and observed.loaded_with_margin(model)))
    ]
    if candidates:

        def order(model: str) -> tuple[bool, float, int, str]:
            busy = model in own or (observed is not None and observed.busy(model))
            left = observed.ttl_left(model) if observed is not None else -math.inf
            chain = chain_order.index(model) if model in chain_order else len(chain_order)
            return (not busy, -left, chain, model)

        return min(candidates, key=order)
    return role if role in grantable else None
