"""legacy_names.py — equivalencias viejo→nuevo de los datos ya escritos (D2 del SDD).

Los datos que el paquete y los hooks escribieron con nombres en español (log de uso, estado de
enfriamiento, telemetría de hooks, cachés de atribución y coste…) se leen **para siempre** en el
formato viejo, y no se reescriben en el sitio. Este módulo es la única tabla de equivalencias:
todo lector del paquete traduce por aquí, y los hooks llevan en `hook_common.py` solo las
equivalencias que leen ellos, atadas a esta por un test de igualdad.

Cada ola del frente A añade las tablas de su formato (A2 la telemetría de hooks y los nombres en
disco; A3 el log de uso; A4 el estado y los episodios de enfriamiento…).

Forma de cada formato en `FORMATS`:

- `keys`: `{clave_vieja: clave_nueva}`;
- `values`: `{clave_nueva: {valor_viejo: valor_nuevo}}`, para los valores de enumeración.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Valores de `failures.FailureClass` (`error_class`, `fallback_class` y `affinity_dropped_class`
#: del log de uso, y `clase` de los eventos de enfriamiento). `enfriamiento` no es un miembro del
#: enum: es la clase que el daemon escribe en `fallback_class` cuando salta por un modelo enfriado.
FAILURE_CLASS_VALUES: dict[str, str] = {
    "peticion": "request",
    "capacidad_o_carga": "capacity_or_load",
    "timeout_lectura": "read_timeout",
    "configuracion": "configuration",
    "modelo": "model",
    "sin_clasificar": "unclassified",
    "enfriamiento": "cooldown",
}

#: Valores de `failures.ConnectionCause` (`connection_failure` del log de uso y `cause` de `/api/*`).
CONNECTION_CAUSE_VALUES: dict[str, str] = {
    "rechazada": "refused",
    "sin_ruta": "no_route",
    "timeout_conexion": "connect_timeout",
    "credencial": "credential",
    "sin_respuesta": "no_response",
    "respuesta_invalida": "invalid_response",
    "url_invalida": "invalid_url",
    "transporte": "transport",
    "desconocida": "unknown",
}

#: El tipo de cada caso del corpus del benchmark (`kind`), tal como lo escriben `build_corpus` en
#: `benchmarks/*/cases.json` y el runner en cada fila de resultados (ola A10b-5): los corpus y los
#: resultados congelados dicen `calidad` y `techo`.
CORPUS_KIND_VALUES: dict[str, str] = {"calidad": "quality", "techo": "ceiling"}

#: La procedencia (`provenance`) y el tipo de entrada (`media_type`) de cada caso del corpus, tal
#: como los escribe `build_corpus` en `benchmarks/*/cases.json` (cierre del frente A, lote 3): los
#: corpus congelados dicen `congelado`, `generado`, `reconstruido`, `inventado`, `texto` e `imagen`.
CORPUS_PROVENANCE_VALUES: dict[str, str] = {
    "congelado": "frozen",
    "generado": "generated",
    "reconstruido": "reconstructed",
    "inventado": "made_up",
}
CORPUS_MEDIA_VALUES: dict[str, str] = {"texto": "text", "imagen": "image"}

#: El papel de un caso en la hoja de commits (`sheet_role` del corpus de afinidad) y el tipo de un par
#: de la hoja (`kind` de la clave y del juicio), y el lado de la trampa en `sides` (lote 3): lo
#: congelado dice `trampa`.
SHEET_TRAP_VALUES: dict[str, str] = {"trampa": "trap"}

#: El tipo del puntuador (`scorer.kind`) de los casos de afinidad que no se puntúan solos (lote 3).
SCORER_KIND_VALUES: dict[str, str] = {"techo": "ceiling", "hoja": "sheet"}

FORMATS: dict[str, dict[str, dict[str, Any]]] = {
    # Log de uso (`usage-*.jsonl`).
    "usage": {
        "keys": {
            "bloqueo_id": "block_id",
            "secciones": "sections",
            "fallo_conexion": "connection_failure",
        },
        "values": {
            "error_class": FAILURE_CLASS_VALUES,
            "fallback_class": FAILURE_CLASS_VALUES,
            "affinity_dropped_class": FAILURE_CLASS_VALUES,
            "connection_failure": CONNECTION_CAUSE_VALUES,
        },
    },
    # Telemetría de hooks (`LD_HOOK_TELEMETRY_LOG`). `oferta` ya no la escribe nadie: solo se lee.
    "hook_telemetry": {
        "keys": {
            "motivo": "reason",
            "bloqueo": "block",
            "camino": "route",
            "rutas": "paths",
            "oferta": "offer",
        },
        "values": {
            "reason": {
                "acotada": "bounded",
                "codigo": "code",
                "pequeno": "small",
                "backend_ausente": "backend_missing",
                "modelo_enfriado": "model_cooled",
                "prosa_grande": "large_prose",
                "no_es_volcado": "not_a_dump",
                "sin_fichero": "no_file",
                "no_es_prosa": "not_prose",
                "bloqueo_apagado": "block_off",
                "mcp_ajeno": "foreign_mcp",
            },
            "block": {
                "encendido": "on",
                "apagado_fichero": "off_file",
                "apagado_variable": "off_variable",
            },
        },
    },
    # Estado de enfriamiento (`cooldown.json`; antes `enfriamiento.json`). `hook_common` copia
    # estas claves en `COOLDOWN_STATE_KEYS` y `tests/test_hook_legacy_names.py` exige que sean iguales.
    "cooldown_state": {
        "keys": {
            "fallos": "failures",
            "espera_s": "wait_s",
            "hasta": "until",
            "reentradas": "reentries",
        },
    },
    # Registro de episodios (`cooldown-events.jsonl`; antes `enfriamiento-eventos.jsonl`).
    "cooldown_events": {
        "keys": {
            "modelo": "model",
            "evento": "event",
            "clase": "class",
            "tras_vencer": "after_expiry",
            "reentradas": "reentries",
            "espera_s": "wait_s",
        },
        "values": {
            "event": {"entra": "enter", "reentra": "reenter", "limpia": "clear"},
            "class": FAILURE_CLASS_VALUES,
        },
    },
    # Cada entrada del relleno (`attribution-AAAAMM.json`; antes `atribucion-AAAAMM.json`). La
    # clave de primer nivel `entradas`→`entries` se lee con `read_key`.
    "attribution": {
        "keys": {
            "cruce": "match",
            "banco": "bench",
            "caducidades": "expiries",
        },
        "values": {
            "match": {
                "exacto": "exact",
                "ventana": "window",
                "ventana+path": "window+path",
                "ambiguo": "ambiguous",
                "sin_cruce": "no_match",
            },
        },
    },
    # Agregados del coste (`cost-aggregates.json`; antes `coste-agregados.json`): las claves de
    # primer nivel. Lo anidado (cotejo, puntos, descartes y marcas) tiene sus propias tablas, y el
    # fichero entero se traduce con `normalize_cost_aggregates`.
    "cost_aggregates": {
        "keys": {
            "generado": "generated",
            "plazo_dias": "cleanup_days",
            "cotejo": "check",
            "n_por_mes": "n_by_month",
            "puntos": "points",
            "descartes": "discards",
            "reinicios": "resets",
            "fuentes": "sources",
        },
    },
    # El cotejo real de precios (`check`).
    "cost_aggregates_check": {
        "keys": {
            "fecha": "date",
            "version_tabla": "table_version",
            "juzgadas": "judged",
            "fuera": "outside",
            "sin_precio": "unpriced",
            "veredicto": "verdict",
        },
        "values": {"verdict": {"pasa": "pass", "falla": "fail"}},
    },
    # Cada punto de calibración de la cuota (`points[]`). Su identidad es
    # `(source, type, start, end)`, y `source` se traduce ANTES de juntar puntos viejos y nuevos.
    "cost_aggregates_point": {
        "keys": {
            "fuente": "source",
            "tipo": "type",
            "inicio": "start",
            "fin": "end",
            "marcas": "marks",
            "peticiones_sin_precio": "unpriced_requests",
        },
        "values": {"source": {"rechazo": "rejection"}},
    },
    # Sesiones y ventanas que las mediciones de adopción excluyen (`benchmarks/excluded-windows.json`;
    # antes `ventanas-excluidas.json`, que se sigue leyendo). La misma tabla vale para el primer
    # nivel y para cada entrada de `sessions[]` y `windows[]`.
    "excluded_windows": {
        "keys": {
            "sesiones": "sessions",
            "ventanas": "windows",
            "inicio": "start",
            "fin": "end",
            "motivo": "reason",
            "tanda": "batch",
        },
    },
    # Las tareas del experimento de adopción (`benchmarks/adopcion-directa/tareas.json`, congelado:
    # nadie lo reescribe). La misma tabla vale para el primer nivel y para cada tarea.
    "adoption_tasks": {
        "keys": {
            "tareas": "tasks",
            "fuente": "source",
            "comando": "command",
            "estilo": "style",
            "nombre": "name",
        },
    },
    # El `MANIFEST.json` de las copias fijas (`benchmarks/resumen-estructurado/`, congelado). La
    # misma tabla vale para el primer nivel y para cada entrada de `files`.
    "sources_manifest": {
        "keys": {"ficheros": "files", "origen": "origin"},
    },
    # Cada corrida del experimento de adopción (`results.jsonl` del banco; antes `resultados.jsonl`).
    "adoption_runs": {
        "keys": {
            "tarea": "task",
            "oferta": "offer",
            "valida": "valid",
            "correcta": "correct",
            "coste_usd": "cost_usd",
            "cobertura_titulos": "title_coverage",
            "hecho_en_respuesta": "fact_in_answer",
            "tools_locales": "local_tools",
            "intentos": "attempts",
            # Lo que `_claude_bench.analyze` vio en el transcript (antes `_banco_claude.analizar`).
            "tools_diferidas": "deferred_tools",
            "read_completo": "read_full",
            "read_franjas": "read_ranges",
            "volcado_bash": "bash_dump",
            "bloqueado": "blocked",
            "contenido_en_contexto": "content_in_context",
        },
    },
    # Cada fila de resultados de `local-delegate benchmark` y del techo de
    # `scripts/dev/affinity_batch.py` (`benchmarks/*/resultados*/*.jsonl`, congelados). Solo lo que
    # leen sus cargadores (`analyze_benchmark`, `pair_sheet`, `review_sheet` y `affinity_batch`):
    # `procedencia` y `entorno_fijado` cambian de nombre al escribir, pero nadie los lee de vuelta.
    # `zero_by` va dentro de `score`: lo traduce `normalize_benchmark_result`.
    "benchmark_results": {
        "keys": {"descartada": "discarded", "descartada_motivo": "discarded_reason"},
        "values": {
            "outcome": {"rechazo_por_contexto": "context_rejection", "truncado": "truncated"},
            "kind": CORPUS_KIND_VALUES,
        },
    },
    "benchmark_score": {
        "values": {"zero_by": {"truncado_repetido": "truncated_repeated"}},
    },
    # Cada caso del corpus (`benchmarks/*/cases.json`, congelado) tal como lo lee
    # `benchmark.load_corpus`. La señal de la pareja de referencia la compara
    # `build_corpus.check_versioned` con la que escribe hoy (ola A10b-4).
    "benchmark_corpus": {
        "keys": {"procedencia": "provenance", "origen": "origin"},
        "values": {
            "kind": CORPUS_KIND_VALUES,
            "provenance": CORPUS_PROVENANCE_VALUES,
            "media_type": CORPUS_MEDIA_VALUES,
            "reference_signal": {
                "cobertura": "coverage",
                "prohibido": "forbidden",
                "json_valido": "json_valid",
                "json_campos": "json_fields",
                "ejecucion": "execution",
                "conteos": "counts",
            },
        },
    },
    # `veredicto.json` de la evaluación de afinidad (congelado): solo lo que lee
    # `tests/test_affinity.py`. La misma tabla vale para el primer nivel y para cada celda.
    "affinity_verdict": {
        "keys": {
            "celdas": "cells",
            "alternativo": "alternative",
            "rol_comparado": "compared_role",
            "estado": "state",
            "huella": "footprint",
            "huella_rol": "role_footprint",
        },
        # El estado de cada celda (ola A10b-3): `tests/test_affinity.py` saca de él las celdas
        # aprobadas que tiene que haber en `matrix.CELLS`.
        "values": {
            "state": {"aprobada": "approved", "rechazada": "rejected", "sin base": "no_baseline"}
        },
    },
    # La huella de un modelo (`footprint.footprint`), tal como la guardan los congelados de
    # `benchmarks/afinidad-2026-10/` (`huellas.json` y `footprint`/`role_footprint` de cada celda de
    # `veredicto*.json`). La comparan `matrix.footprint_differences` y `tests/test_affinity.py`
    # (cierre del frente A, lote 1).
    "footprint": {"keys": {"ruta": "path", "tamano_bytes": "size_bytes"}},
    # El corpus de afinidad (`benchmarks/afinidad-2026-10/cases.json`, congelado; lo escribe
    # `build_corpus`) tal como lo lee `analyze_benchmark`: de cada caso, solo estas dos claves…
    "affinity_case": {
        "keys": {
            "rol_en_hoja": "sheet_role",
            "discriminante": "discriminating",
            "puntuador": "scorer",
        },
        # El tipo del caso (ola A10b-5): `analyze_benchmark` lo compara al elegir los casos de cada
        # celda; y su papel en la hoja (lote 3), con el que deja fuera las trampas.
        "values": {"kind": CORPUS_KIND_VALUES, "sheet_role": SHEET_TRAP_VALUES},
    },
    # El primer nivel del corpus de afinidad y su `selection` (ola A10b-4), tal como los lee
    # `build_corpus.check_versioned_affinity` (`normalize_affinity_corpus`).
    "affinity_corpus": {
        "keys": {
            "seleccion": "selection",
            "regla": "rule",
            "fecha_limite": "deadline",
            "paso": "step",
            "privacidad": "privacy",
            "caso_de_f2": "f2_case",
            "reales": "real",
            "trampas": "traps",
        },
    },
    # `trampas.json` de la evaluación de afinidad (congelado; ahora `traps.json`), tal como lo
    # leen `pair_sheet` (`build_commit_sheet`, `shaped_trap`) y `check_versioned_affinity`. La
    # misma tabla vale para el primer nivel, cada juego, cada trampa y su `subject_of`
    # (`normalize_affinity_traps`).
    "affinity_traps": {
        "keys": {
            "regla_de_forma": "shape_rule",
            "misma-zona": "same-zone",
            "secundario": "secondary",
            "generico": "generic",
            "juegos": "sets",
            "juego": "set",
            "trampas": "traps",
            "caso": "case",
            "tipo": "kind",
            "asunto": "subject",
            "cuerpo": "body",
            "cuerpo_origen": "source_body",
            "asunto_de": "subject_of",
            "fichero": "file",
        },
        "values": {
            "kind": {"misma-zona": "same-zone", "secundario": "secondary", "generico": "generic"}
        },
    },
    # La clave de la hoja de commits (`clave-<n>.json`, la de la hoja 1 congelada), tal como la
    # lee `pair_sheet.read_commit`: el primer nivel y cada par (`normalize_commit_key`).
    "commit_key": {
        "keys": {
            "hoja": "sheet",
            "juego": "set",
            "semilla": "seed",
            "pares": "pairs",
            "omitidos": "omitted",
            "tipo": "kind",
            "caso": "case",
            "lados": "sides",
            "trampa_tipo": "trap_kind",
        },
        "values": {
            "trap_kind": {
                "misma-zona": "same-zone",
                "secundario": "secondary",
                "generico": "generic",
            },
            "kind": SHEET_TRAP_VALUES,
        },
    },
    # Las respuestas de la hoja de commits (`respuestas-<n>.json`, las de la hoja 1 congeladas,
    # que descarga la página), tal como las lee `pair_sheet.read_commit`
    # (`normalize_commit_answers`): el primer nivel y lo contestado en cada par.
    "commit_answers": {
        "keys": {
            "hoja": "sheet",
            "parcial": "partial",
            "respuestas": "answers",
            "inventa": "made_up",
            "especifico": "specific",
            "preferencia": "preference",
        },
    },
    # Los conteos del log de uso del corpus (`conteos-log.json`, congelado; ahora
    # `log-counts.json`): el primer nivel y cada tool de `by_tool` (`normalize_log_counts`).
    "log_counts": {
        "keys": {
            "eventos": "events",
            "eventos_local": "local_events",
            "descartados_no_local": "discarded_not_local",
            "por_tool": "by_tool",
            "por_modelo": "by_model",
            "por_source": "by_source",
            "troceados": "chunked",
            "fuentes_del_repo": "repo_sources",
            "fuentes_fuera_del_repo": "sources_outside_repo",
            "chars_in_mediana": "chars_in_median",
            "modelos": "models",
        },
    },
    # …y su puntuador (`puntuador`), que lee `analyze_benchmark.score_affinity`.
    "affinity_scorer": {
        "keys": {
            "tipo": "kind",
            "aceptables": "acceptable",
            "etiquetas": "labels",
            "claves": "keys",
            "esperado": "expected",
            "titulos": "titles",
            "listas": "lists",
            "bloques": "blocks",
            "codigo": "code",
            "conteos": "counts",
            "formato": "format",
        },
        "values": {"kind": SCORER_KIND_VALUES},
    },
    # `reglas.json` de la evaluación de afinidad (congelado, escrito a mano; ahora `rules.json`).
    # La misma tabla vale para el primer nivel, `formato` y `sin_adornos`
    # (`normalize_affinity_rules`).
    "affinity_rules": {
        # Los valores de `optional_questions` (una lista) los traduce `normalize_affinity_rules`.
        "keys": {
            "max_inventa_26b": "max_made_up_26b",
            "preguntas_opcionales": "optional_questions",
            "formato": "format",
            "parada_anticipada": "early_stop",
            "primera_linea_max": "first_line_max",
            "prefijo": "prefix",
            "sin_adornos": "no_frills",
            "vallas_de_codigo": "code_fences",
            "comillas_envolventes": "wrapping_quotes",
            "encabezados_markdown": "markdown_headings",
            "frases_de_presentacion": "intro_phrases",
        },
    },
    # El juicio del usuario sobre la hoja de commits (salida de `pair_sheet.py read-commit`), que
    # lee `analyze_benchmark`: el primer nivel y cada par de `pares`
    # (`normalize_commit_judgement`).
    "commit_judgement": {
        "keys": {
            "parcial": "partial",
            "pares": "pairs",
            "juego": "set",
            "tipo": "kind",
            "preferencia": "preference",
            "lados": "sides",
            "inventa": "made_up",
            "especifico": "specific",
            "caso": "case",
        },
        "values": {"kind": SHEET_TRAP_VALUES},
    },
    # El motivo por el que CP-3 deja fuera un caso (`reason` de cada caso de `cp3.json`, que
    # escribe `analyze_benchmark cp3 --json` y relee `decide --cp3`; ola A10b-6).
    "cp3_case": {"values": {"reason": {"techo": "ceiling"}}},
    # Cada fila de `pair_sheet.py unblind --json`, que suma `analyze_benchmark decide --pairs`.
    "unblinded_pairs": {
        "keys": {"humano": "human"},
    },
    # Cada entrada de las ventanas de la tanda de afinidad (`batch-windows.json`; antes
    # `ventanas-tanda.json`, congelado).
    "batch_windows": {
        "keys": {"inicio_utc": "start_utc", "fin_utc": "end_utc", "solo": "only"},
    },
}

#: Motivos de descarte de la cuota: las claves de `discards[<tipo>]` (y los dos que añade
#: `quota.status` al leer, `expired` y `reset`). El panel los recibe ya traducidos.
COST_DISCARD_REASONS: dict[str, str] = {
    "linea_corrupta": "corrupt_line",
    "fuera_de_rango": "out_of_range",
    "delta_pequeno": "small_delta",
    "sin_uso_local": "no_local_use",
    "contaminado": "contaminated",
    "solapado": "overlapping",
    "caducado": "expired",
    "reinicio": "reset",
}

#: Marcas de un punto de cuota (REQ-033): eran prosa usada como valor de máquina. Una marca que no
#: esté aquí se copia tal cual.
COST_MARK_VALUES: dict[str, str] = {
    "cota baja": "low_bound",
    "solo comprobación": "check_only",
    "cota baja si hubo uso en otras superficies": "low_bound_if_other_surfaces",
    "reinicio": "reset",
}

#: Ficheros en disco que comparten los hooks y el daemon, como `(viejo, nuevo)` (REQ-012). Se
#: escribe solo el nuevo y se leen los dos. `hook_common.FILE_NAMES` es su copia (los hooks no
#: importan el paquete) y `tests/test_hook_legacy_names.py` exige que sean iguales.
FILE_NAMES: dict[str, tuple[str, str]] = {
    "switch_file": ("local-delegate-bloqueo-apagado", "local-delegate-block-off"),
    "block_notes": ("local-delegate-bloqueos.jsonl", "local-delegate-blocks.jsonl"),
    "call_notes_dir": ("local-delegate-llamadas", "local-delegate-calls"),
    "health_prefix": ("local-delegate-salud-", "local-delegate-health-"),
    # En `LOG_DIR`. El daemon escribe los dos mientras viva su entrada `legacy_write` de
    # `deprecations` (excepción de REQ-005); se lee el nuevo y, si no existe, el viejo.
    "cooldown_state": ("enfriamiento.json", "cooldown.json"),
}

#: El registro de episodios de enfriamiento, como `(viejo, nuevo)`. Solo lo escribe el daemon y lo
#: lee `scripts/measure_cooldown.py` (los dos ficheros, siempre): los hooks no lo copian.
COOLDOWN_EVENTS_FILE_NAMES: tuple[str, str] = (
    "enfriamiento-eventos.jsonl",
    "cooldown-events.jsonl",
)

#: Prefijo de la caché del relleno por mes (`<prefijo>AAAAMM.json`, en `LOG_DIR`), como
#: `(viejo, nuevo)`. Solo la usan el paquete (`attribution`): los hooks no la leen, así que no va en
#: `FILE_NAMES`, que tiene copia en `hook_common`. Se escribe el nuevo; el viejo siembra el nuevo una
#: sola vez y no se reescribe nunca (REQ-006).
ATTRIBUTION_FILE_PREFIXES: tuple[str, str] = ("atribucion-", "attribution-")

#: Los agregados del coste (en `LOG_DIR`), como `(viejo, nuevo)`. Solo los escribe `recompute`, y
#: solo el nuevo; el viejo siembra el nuevo una sola vez y no se reescribe nunca (REQ-006).
COST_AGGREGATES_FILE_NAMES: tuple[str, str] = ("coste-agregados.json", "cost-aggregates.json")

#: El registro del statusline (en `~/.claude`), como `(viejo, nuevo)`. Lo escribe el statusline del
#: usuario, que es código ajeno al paquete: se leen los dos si existen los dos (REQ-008).
QUOTA_STATUSLINE_FILE_NAMES: tuple[str, str] = ("cuota-statusline.jsonl", "quota-statusline.jsonl")

#: Las sesiones y ventanas que excluyen las mediciones de adopción (en `benchmarks/`), como
#: `(viejo, nuevo)`. Lo escriben `scripts/test_sessions.py` y `_claude_bench.note_window`, solo el
#: nuevo; si no existe, parten del viejo, que está congelado y no se reescribe nunca.
EXCLUDED_WINDOWS_FILE_NAMES: tuple[str, str] = ("ventanas-excluidas.json", "excluded-windows.json")

#: Ficheros de la tanda de afinidad (`benchmarks/afinidad-2026-10/`), como `(viejo, nuevo)`. Se
#: escribe solo el nuevo; si no existe, se lee el viejo, que está congelado y no se reescribe.
#: Las huellas las escribe `scripts/dev/affinity_batch.py` y las lee `analyze_benchmark`; las
#: ventanas, `affinity_batch`; el veredicto lo escribe `analyze_benchmark` y lo lee
#: `tests/test_affinity.py`.
FOOTPRINTS_FILE_NAMES: tuple[str, str] = ("huellas.json", "footprints.json")
BATCH_WINDOWS_FILE_NAMES: tuple[str, str] = ("ventanas-tanda.json", "batch-windows.json")
VERDICT_FILE_NAMES: tuple[str, str] = ("veredicto.json", "verdict.json")
#: Las reglas de la evaluación de afinidad, como `(viejo, nuevo)`: las lee `analyze_benchmark`
#: (y `pair_sheet`); el viejo, congelado, se lee si el nuevo no existe.
RULES_FILE_NAMES: tuple[str, str] = ("reglas.json", "rules.json")
#: Las trampas de la evaluación de afinidad y los conteos del log del corpus, como `(viejo, nuevo)`:
#: los escribe `build_corpus` (ola A10b-4); el viejo, congelado, se lee si el nuevo no existe.
TRAPS_FILE_NAMES: tuple[str, str] = ("trampas.json", "traps.json")
LOG_COUNTS_FILE_NAMES: tuple[str, str] = ("conteos-log.json", "log-counts.json")
#: Las preguntas de la hoja de commits que `optional_questions` puede listar, en el formato viejo.
OPTIONAL_QUESTION_VALUES: dict[str, str] = {"especifico": "specific"}

#: Valores que el panel recibe de `/api/hooks` y que su diccionario de etiquetas tiene que entender
#: también en el formato viejo (REQ-009). El servidor lo inyecta en el HTML: el JS no copia la tabla.
#: Además de los motivos persistidos, van los cubos que fabricaba el propio servidor en español.
PANEL_VALUE_ALIASES: dict[str, dict[str, str]] = {
    "hookReason": {
        **FORMATS["hook_telemetry"]["values"]["reason"],
        "avisó": "suggested",
        "aviso": "suggested",
        "sin registrar": "unrecorded",
    },
    "hookCategory": {"sin categoría": "no_category"},
    # La causa de `/api/backend` y la clase de fallo de un evento (`cause` de `acct()`).
    "connectionCause": CONNECTION_CAUSE_VALUES,
    "failureClass": FAILURE_CLASS_VALUES,
}


def new_value(table: Mapping[str, str], value: Any) -> Any:
    """`value` en el formato nuevo si es un valor viejo de `table`; si no, tal cual."""
    if isinstance(value, str):
        return table.get(value, value)
    return value


def read_key(row: Mapping[str, Any], new: str, old: str, default: Any = None) -> Any:
    """El valor de `new` en `row`, o el de `old` si la fila es del formato viejo. Gana la nueva."""
    if new in row:
        return row[new]
    if old in row:
        return row[old]
    return default


def old_keys(fmt: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Copia de `row` con las claves del formato nuevo devueltas a su nombre viejo.

    Solo para las escrituras dobles que mantiene una excepción temporal (`legacy_write`): los
    valores se copian tal cual, porque esos formatos no tienen valores de enumeración traducidos.
    """
    back = {new: old for old, new in FORMATS.get(fmt, {}).get("keys", {}).items()}
    return {back.get(key, key): value for key, value in row.items()}


def normalize(fmt: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Copia de `row` con claves y valores de enumeración traducidos al formato nuevo.

    Una fila ya nueva sale igual; una clave que no está en la tabla se conserva tal cual. Si la
    fila trae la clave vieja y la nueva a la vez, gana la nueva.
    """
    table = FORMATS.get(fmt, {})
    keys: Mapping[str, str] = table.get("keys", {})
    values: Mapping[str, Mapping[str, str]] = table.get("values", {})
    out: dict[str, Any] = {}
    for key, value in row.items():
        new_key = keys.get(key, key)
        if new_key != key and new_key in row:
            continue  # la clave nueva también está: manda ella
        out[new_key] = value
    for key, mapping in values.items():
        value = out.get(key)
        if isinstance(value, str) and value in mapping:
            out[key] = mapping[value]
    return out


def normalize_excluded_windows(data: Mapping[str, Any]) -> dict[str, Any]:
    """El fichero de ventanas excluidas en el formato nuevo: el primer nivel y cada entrada de
    `sessions[]` y `windows[]`. Un fichero ya nuevo sale igual."""
    out = normalize("excluded_windows", data)
    for key in ("sessions", "windows"):
        if isinstance(out.get(key), list):
            out[key] = [
                normalize("excluded_windows", e) if isinstance(e, Mapping) else e for e in out[key]
            ]
    return out


def normalize_cost_point(point: Any) -> Any:
    """Un punto de cuota en el formato nuevo, con `source` y las marcas ya traducidas.

    Lo que no es un dict se devuelve tal cual: `quota.split_malformed` lo cuenta como roto.
    """
    if not isinstance(point, Mapping):
        return point
    out = normalize("cost_aggregates_point", point)
    marks = out.get("marks")
    if isinstance(marks, list):
        out["marks"] = [new_value(COST_MARK_VALUES, m) for m in marks]
    return out


def normalize_cost_aggregates(data: Mapping[str, Any]) -> dict[str, Any]:
    """`coste-agregados.json` entero en el formato de `cost-aggregates.json`.

    Traduce las claves de primer nivel, las del cotejo y su veredicto, las de cada punto (con
    `source` y las marcas, para que un punto viejo y su gemelo nuevo tengan la misma identidad) y
    los motivos de descarte. Un fichero ya nuevo sale igual.
    """
    out = normalize("cost_aggregates", data)
    check = out.get("check")
    if isinstance(check, Mapping):
        out["check"] = normalize("cost_aggregates_check", check)
    points = out.get("points")
    if isinstance(points, list):
        out["points"] = [normalize_cost_point(p) for p in points]
    discards = out.get("discards")
    if isinstance(discards, Mapping):
        out["discards"] = {
            kind: (
                {COST_DISCARD_REASONS.get(r, r): n for r, n in by_reason.items()}
                if isinstance(by_reason, Mapping)
                else by_reason
            )
            for kind, by_reason in discards.items()
        }
    return out


def normalize_benchmark_result(row: Mapping[str, Any]) -> dict[str, Any]:
    """Una fila de resultados del benchmark en el formato nuevo, con el `zero_by` de su `score`
    ya traducido. Una fila ya nueva sale igual."""
    out = normalize("benchmark_results", row)
    score = out.get("score")
    if isinstance(score, Mapping):
        out["score"] = normalize("benchmark_score", score)
    return out


def normalize_affinity_verdict(data: Mapping[str, Any]) -> dict[str, Any]:
    """`veredicto.json` en el formato nuevo: el primer nivel y cada entrada de `cells`. Un fichero
    ya nuevo sale igual."""
    out = normalize("affinity_verdict", data)
    if isinstance(out.get("cells"), list):
        out["cells"] = [
            _normalize_verdict_cell(c) if isinstance(c, Mapping) else c for c in out["cells"]
        ]
    return out


def _normalize_verdict_cell(cell: Mapping[str, Any]) -> dict[str, Any]:
    out = normalize("affinity_verdict", cell)
    for key in ("footprint", "role_footprint"):
        if key in out:
            out[key] = normalize_footprint(out[key])
    return out


def normalize_footprint(footprint: Any) -> Any:
    """Una huella (`footprint.footprint`) con las claves nuevas (`path`, `size_bytes`); la de un
    congelado viejo (`ruta`, `tamano_bytes`) sale traducida y una que no es un mapa, tal cual."""
    if isinstance(footprint, Mapping):
        return normalize("footprint", footprint)
    return footprint


def normalize_affinity_rules(data: Mapping[str, Any]) -> dict[str, Any]:
    """Las reglas de afinidad en el formato nuevo: el primer nivel, `format` y `no_frills`. Unas
    reglas ya nuevas salen igual."""
    out = normalize("affinity_rules", data)
    questions = out.get("optional_questions")
    if isinstance(questions, list):
        out["optional_questions"] = [new_value(OPTIONAL_QUESTION_VALUES, q) for q in questions]
    fmt = out.get("format")
    if isinstance(fmt, Mapping):
        fmt = normalize("affinity_rules", fmt)
        if isinstance(fmt.get("no_frills"), Mapping):
            fmt["no_frills"] = normalize("affinity_rules", fmt["no_frills"])
        out["format"] = fmt
    return out


def normalize_commit_judgement(data: Mapping[str, Any]) -> dict[str, Any]:
    """El juicio de la hoja de commits en el formato nuevo: el primer nivel y cada par de `pairs`.
    Un juicio ya nuevo sale igual."""
    out = normalize("commit_judgement", data)
    if isinstance(out.get("pairs"), Mapping):
        out["pairs"] = {
            k: _normalize_pair_sides(normalize("commit_judgement", p))
            if isinstance(p, Mapping)
            else p
            for k, p in out["pairs"].items()
        }
    return out


def _normalize_pair_sides(pair: dict[str, Any]) -> dict[str, Any]:
    """El lado de la trampa de un par (`sides`, `{"A": "trampa", "B": <modelo>}` en lo congelado)
    con el valor nuevo. Los lados de un modelo se copian tal cual."""
    sides = pair.get("sides")
    if isinstance(sides, Mapping):
        pair["sides"] = {side: new_value(SHEET_TRAP_VALUES, who) for side, who in sides.items()}
    return pair


def normalize_affinity_corpus(data: Mapping[str, Any]) -> dict[str, Any]:
    """El corpus de afinidad en el formato nuevo: el primer nivel, `selection` y cada caso
    (`benchmark_corpus` y `affinity_case`). Un corpus ya nuevo sale igual."""
    out = normalize("affinity_corpus", data)
    if isinstance(out.get("selection"), Mapping):
        out["selection"] = normalize("affinity_corpus", out["selection"])
    if isinstance(out.get("cases"), list):
        out["cases"] = [
            _normalize_affinity_case(c) if isinstance(c, Mapping) else c for c in out["cases"]
        ]
    return out


def _normalize_affinity_case(case: Mapping[str, Any]) -> dict[str, Any]:
    out = normalize("affinity_case", normalize("benchmark_corpus", case))
    if isinstance(out.get("scorer"), Mapping):
        out["scorer"] = normalize("affinity_scorer", out["scorer"])
    return out


def normalize_affinity_trap(trap: Mapping[str, Any]) -> dict[str, Any]:
    """Una trampa en el formato nuevo, con su `subject_of`. Una ya nueva sale igual."""
    out = normalize("affinity_traps", trap)
    if isinstance(out.get("subject_of"), Mapping):
        out["subject_of"] = normalize("affinity_traps", out["subject_of"])
    return out


def normalize_affinity_traps(data: Mapping[str, Any]) -> dict[str, Any]:
    """`trampas.json` en el formato nuevo: el primer nivel, cada juego y cada trampa. Uno ya
    nuevo sale igual."""
    out = normalize("affinity_traps", data)
    if isinstance(out.get("sets"), list):
        sets = []
        for item in out["sets"]:
            if isinstance(item, Mapping):
                item = normalize("affinity_traps", item)
                if isinstance(item.get("traps"), list):
                    item["traps"] = [
                        normalize_affinity_trap(t) if isinstance(t, Mapping) else t
                        for t in item["traps"]
                    ]
            sets.append(item)
        out["sets"] = sets
    return out


def normalize_commit_key(data: Mapping[str, Any]) -> dict[str, Any]:
    """La clave de la hoja de commits en el formato nuevo: el primer nivel y cada par de `pairs`.
    Una clave ya nueva sale igual."""
    out = normalize("commit_key", data)
    if isinstance(out.get("pairs"), Mapping):
        out["pairs"] = {
            k: _normalize_pair_sides(normalize("commit_key", p)) if isinstance(p, Mapping) else p
            for k, p in out["pairs"].items()
        }
    return out


def normalize_commit_answers(data: Mapping[str, Any]) -> dict[str, Any]:
    """Las respuestas de la hoja de commits en el formato nuevo: el primer nivel y lo contestado en
    cada par de `answers`. Unas ya nuevas salen igual."""
    out = normalize("commit_answers", data)
    if isinstance(out.get("answers"), Mapping):
        out["answers"] = {
            k: normalize("commit_answers", a) if isinstance(a, Mapping) else a
            for k, a in out["answers"].items()
        }
    return out


def normalize_log_counts(data: Mapping[str, Any]) -> dict[str, Any]:
    """Los conteos del log del corpus en el formato nuevo: el primer nivel y cada tool de
    `by_tool`. Unos ya nuevos salen igual."""
    out = normalize("log_counts", data)
    if isinstance(out.get("by_tool"), Mapping):
        out["by_tool"] = {
            k: normalize("log_counts", t) if isinstance(t, Mapping) else t
            for k, t in out["by_tool"].items()
        }
    return out
