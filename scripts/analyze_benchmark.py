#!/usr/bin/env python3
"""Agrega el JSONL de `local-delegate benchmark` y aplica por programa §6 y §7 de protocolo-f2.md.

La cuenta la hace el programa: contar a ojo en este repo ya fallo una vez, catorce contra treinta
y cuatro. Dos modos, en el orden en que se usan:

- `cp3`: el piloto de CP-3. Por rol dice que casos separan a dos configuraciones por encima de la
  banda de ruido, cuales estan en techo, si separa el AGREGADO y si la regla de §7 podria disparar
  alguna vez con esa banda. Su `--json` es el insumo de `decidir`, que no tiene otro modo de saber
  que casos entran en el agregado.
- `decidir`: vigente contra candidato por rol. Primero el criterio de tanda no concluyente (§6);
  despues las condiciones y los desempates de §7. «No se cambia» es un resultado, no un error: el
  exit code es 0.

- `affinity-verdict`: la evaluacion que aprueba las celdas de afinidad (REQ-040 a REQ-043 del SDD
  `daemon-reparte-el-backend`). Aplica los criterios escritos en el SDD sobre los resultados de la
  tanda, la huella de cada celda (`footprints.json`), `rules.json` y el juicio del usuario, y escribe
  `verdict.json` y la tabla de `verification.md`. No importa `local_delegate`.

Una configuracion se nombra por su `--label` del runner; `label@control` selecciona las corridas
hechas con `--input-control` (el control de entrada de `vision` en CP-3).

Lecturas del protocolo que el texto no fijaba del todo, y que este programa decide asi:

- **Empate** es toda diferencia de calidad dentro de la banda, con cualquier signo: dentro de la
  banda la diferencia es ruido. Lo resuelve la precedencia (techo, luego velocidad, luego no se
  cambia). Ganar por un desempate exige igualmente las condiciones 2 y 3 de §7.
- **Banda de ruido**: por caso, la mayor dispersion de ese caso en los dos modelos; la del
  agregado, la media de las bandas de sus casos. Hasta el tercer piloto de CP-3 era la mayor
  dispersion de todo el rol, y con ruido real un solo caso inestable impedia separar a los demas.
- **OOM**: el JSONL no tiene una clase propia; cualquier `error` del candidato bloquea la
  sustitucion y se lista con su texto. Inventar una cadena de OOM daria un control que no ve el
  resto de caidas.
- **Corrida fria**: fuera de la latencia (incluye la carga del modelo), dentro de la calidad.
- **Techo**: la mayor `input_bytes` que el modelo acepto en todas sus corridas validas de un caso
  del rol. Si el rol tiene sondeo de techo en el corpus y falta en alguno de los dos, no se decide
  por techo ni se sustituye.

Uso:
    python scripts/analyze_benchmark.py cp3 --cases benchmarks/catalogo-2026-09/cases.json \\
        --small qwen35-2b --large qwen25-coder-14b --json cp3.json resultados/cp3-*.jsonl
    python scripts/analyze_benchmark.py decide --cases benchmarks/catalogo-2026-09/cases.json \\
        --cp3 cp3.json --pair long llama31-8b gemma4-26b-a4b resultados/*.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sqlite3
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# vision tiene dos casos sobre una imagen y fast sale de la tanda: ninguno presenta agregado (§7).
ROLES_WITHOUT_AGGREGATE = frozenset({"vision", "fast"})
MIN_DECIDABLE_CASES = 2
MAX_LATENCY = 1.5
# El runner redondea la cobertura a 4 decimales: 0,3334 contra una banda de 0,3333 no es mejora, es
# redondeo. Menor que el paso real mas fino del corpus (1/6 por caso, 1/24 en un agregado de 4).
TOLERANCE = 1e-3
# Comparacion por pares (P-15): prueba de signos de una cola sobre los pares con eleccion.
PAIRS_ALPHA = 0.05
# Aceptadas: el backend recibio la entrada entera, aunque luego no puntue.
_ACCEPTED = frozenset({"ok", "truncado", "configuracion", "configuration"})


def _load_legacy_names() -> Any:
    """`src/local_delegate/legacy_names.py`, cargado por ruta: solo usa la biblioteca estandar, y
    asi este programa lee las filas viejas con la misma tabla que el paquete sin importarlo."""
    path = Path(__file__).resolve().parents[1] / "src" / "local_delegate" / "legacy_names.py"
    spec = importlib.util.spec_from_file_location("_legacy_names", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEGACY_NAMES = _load_legacy_names()


# --- Lectura ------------------------------------------------------------------------------------


def read_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            record = LEGACY_NAMES.normalize_benchmark_result(json.loads(line))
            if record.get("schema_version") != 2:
                raise ValueError(f"{path}:{number}: se esperaba schema_version 2")
            records.append(record)
    return records


def read_corpus(path: Path) -> dict[str, dict[str, Any]]:
    """Solo ids, rol y tipo: el analisis no toca las fuentes, las verifica el runner. Un corpus
    congelado en el formato viejo (`kind` `calidad`/`techo`) se lee traducido."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 2:
        raise ValueError(f"{path}: se esperaba un corpus schema_version 2")
    cases = [LEGACY_NAMES.normalize("benchmark_corpus", c) for c in data["cases"]]
    return {c["id"]: c for c in cases}


@dataclass(frozen=True)
class Selector:
    label: str
    variant: str | None

    @classmethod
    def parse(cls, text: str) -> Selector:
        label, _, variant = text.partition("@")
        return cls(label, variant or None)

    def __str__(self) -> str:
        return f"{self.label}@{self.variant}" if self.variant else self.label

    def accepts(self, record: dict[str, Any]) -> bool:
        return record.get("label") == self.label and record.get("input_variant") == self.variant


# --- Corridas y casos ---------------------------------------------------------------------------


@dataclass
class Run:
    """Una corrida con sus intentos: un `truncado` repetido con mas tokens es UNA corrida, no dos."""

    attempts: list[dict[str, Any]]

    @property
    def final(self) -> dict[str, Any]:
        return self.attempts[-1]

    @property
    def outcome(self) -> str:
        return str(self.final.get("outcome"))

    # Todo se juzga por el ULTIMO intento: desde la tarea 19 el runner repite la anulada, y un
    # intento anulado que se repitio bien no puede seguir descartando ni bloqueando la corrida.
    @property
    def discarded(self) -> bool:
        return bool(self.final.get("discarded"))

    @property
    def discard_reason(self) -> str | None:
        return self.final.get("discarded_reason") if self.discarded else None

    @property
    def cold(self) -> bool:
        return self.final.get("thermal_state") == "cold"

    @property
    def quality(self) -> float | None:
        if self.discarded:
            return None
        score = self.final.get("score") or {}
        # Truncada otra vez tras doblar los tokens: puntua 0 (§4.7 punto 3), no «sin puntuacion».
        if self.outcome == "ok" or (
            self.outcome == "truncado" and score.get("zero_by") == "truncated_repeated"
        ):
            return score.get("quality")
        return None

    @property
    def latency(self) -> float | None:
        """Solo de corridas validas y calientes: la fria lleva dentro la carga del modelo."""
        if self.discarded or self.outcome != "ok" or self.cold:
            return None
        return self.final.get("latency_ms")


def _median_and_spread(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    return statistics.median(values), max(values) - min(values)


@dataclass
class Case:
    id: str
    role: str
    kind: str
    runs: list[Run] = field(default_factory=list)

    @property
    def qualities(self) -> list[float]:
        return [c.quality for c in self.runs if c.quality is not None]

    @property
    def median(self) -> float | None:
        return _median_and_spread(self.qualities)[0]

    @property
    def dispersion(self) -> float | None:
        return _median_and_spread(self.qualities)[1]

    @property
    def latencies(self) -> list[float]:
        return [c.latency for c in self.runs if c.latency is not None]

    @property
    def latency_median(self) -> float | None:
        return _median_and_spread(self.latencies)[0]

    @property
    def latency_spread(self) -> float | None:
        return _median_and_spread(self.latencies)[1]

    @property
    def accepted(self) -> bool | None:
        """Si el modelo acepto la entrada en todas sus corridas validas; None sin corridas validas."""
        valid_ones = [c for c in self.runs if not c.discarded]
        if not valid_ones:
            return None
        return all(c.outcome in _ACCEPTED for c in valid_ones)


@dataclass
class Config:
    selector: Selector
    records: list[dict[str, Any]]
    cases: dict[str, Case]


def load_config(records: list[dict[str, Any]], selector: Selector) -> Config:
    own = [r for r in records if selector.accepts(r)]
    if not own:
        raise ValueError(f"no hay corridas de {selector}")
    cases: dict[str, Case] = {}
    # Estable: el orden del fichero desempata dos registros con el mismo ts.
    for record in sorted(own, key=lambda r: str(r.get("ts", ""))):
        case = cases.setdefault(
            record["case"], Case(record["case"], record["role"], record["kind"])
        )
        if int(record.get("attempt", 1)) == 1:
            case.runs.append(Run([record]))
        elif case.runs:
            case.runs[-1].attempts.append(record)
        else:
            raise ValueError(f"{selector}: {record['case']} tiene un intento >1 sin el primero")
    return Config(selector, own, cases)


def _role_cases(corpus: dict[str, dict[str, Any]], role: str, kind: str) -> list[str]:
    # Un caso con `automatic_scoring: false` no entra en ninguna cuenta de la regla: lo juzga solo la
    # revision a ciegas (§4.8). Es `commit-diff-19k` desde el segundo piloto de CP-3.
    return [
        cid
        for cid, c in corpus.items()
        if c["role"] == role and c["kind"] == kind and c.get("automatic_scoring") is not False
    ]


#: Cómo nombran los mensajes cada tipo de caso (`kind`): el texto de salida sigue en español hasta
#: el frente B.
_KIND_LABELS = {"quality": "calidad", "ceiling": "techo"}


def _kind_label(kind: Any) -> str:
    return _KIND_LABELS.get(kind, str(kind))


def _review_only(corpus: dict[str, dict[str, Any]], role: str) -> list[str]:
    return [
        cid
        for cid, c in corpus.items()
        if c["role"] == role and c["kind"] == "quality" and c.get("automatic_scoring") is False
    ]


def _case(config: Config, case_id: str, corpus: dict[str, dict[str, Any]]) -> Case:
    """Un caso que no corrio existe igual, vacio: asi cuenta como «sin puntuacion valida»."""
    meta = corpus[case_id]
    return config.cases.get(case_id) or Case(case_id, meta["role"], meta["kind"])


def band_for_case(
    configs: list[Config], case_id: str, corpus: dict[str, dict[str, Any]]
) -> float | None:
    """La mayor dispersion de ESE caso entre las configuraciones que se comparan.

    Tercer piloto de CP-3 (decision del usuario): con la temperatura de produccion, la banda del ROL
    —la mayor dispersion de todos sus casos— la fijaba el caso mas inestable y ningun otro podia
    separar. `boilerplate-156` daba 0/0/0 contra 1/1/0,8 y quedaba dentro de una banda de 1,0 que
    ponia `explicar-metrics-15k`. Cada caso se mide contra su propio ruido.
    """
    spreads = [d for cfg in configs if (d := _case(cfg, case_id, corpus).dispersion) is not None]
    return max(spreads) if spreads else None


def aggregate_band(
    configs: list[Config], cases: list[str], corpus: dict[str, dict[str, Any]]
) -> float | None:
    """La media de las bandas de los casos que forman el agregado.

    El agregado es la media de sus medianas, y su ruido es del orden del ruido medio de sus casos.
    La media y no la maxima, para que un caso inestable no vete al resto; y no la media dividida
    por la raiz de N, que supondria independencia entre casos corridos por el mismo modelo.
    CP-3 y §7 usan la misma: si no, el control validaria una magnitud y la regla decidiria con otra.
    """
    return _media([band_for_case(configs, cid, corpus) for cid in cases]) if cases else None


def _media(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    if not present or len(present) != len(values):
        return None
    return statistics.fmean(present)


def can_fire(band: float | None, incumbent_quality: float | None) -> bool | None:
    """Si un candidato PERFECTO (calidad 1,0) superaria la banda. Si no, la regla no puede elegir.

    Con la granularidad real —un caso de un solo termino da 0 o 1— basta que ese caso cambie una
    vez en tres corridas para que la banda valga 1,0 y ningun candidato pueda ganar jamas. Eso da
    «no se cambia», la salida por defecto, y seria indistinguible del hallazgo legitimo.
    """
    if band is None or incumbent_quality is None:
        return None
    return 1.0 - incumbent_quality > band + TOLERANCE


# --- Comparacion por pares (P-15) -------------------------------------------------------------


def _binomial_tail(successes: int, n: int) -> float:
    """P(X >= exitos) con X ~ Binomial(n, 1/2): la probabilidad de tantas elecciones por azar."""
    return sum(math.comb(n, i) for i in range(successes, n + 1)) / 2**n


def pairs_verdict(candidate: int, incumbent: int, ties: int = 0) -> str | None:
    """Prueba de signos sobre los pares con eleccion; los empates no cuentan.

    «mejor» si el candidato fue elegido tantas veces que por azar pasaria con probabilidad
    <= PAIRS_ALPHA; «peor» si eso le pasa al vigente; si no, «empate». Con 20 pares sin empates hace
    falta 15 a 5. Sin ningun par juzgado no hay veredicto.
    """
    n = candidate + incumbent
    if n == 0:
        return "empate" if ties else None
    if _binomial_tail(candidate, n) <= PAIRS_ALPHA:
        return "mejor"
    if _binomial_tail(incumbent, n) <= PAIRS_ALPHA:
        return "peor"
    return "empate"


def pairs_for_role(
    pairs: dict[str, Any] | None,
    corpus: dict[str, dict[str, Any]],
    role: str,
    incumbent: str,
    candidate: str,
) -> dict[str, Any] | None:
    """Suma las elecciones de `pair_sheet.py unblind --json` en los casos por pares del rol."""
    if pairs is None:
        return None
    cases = [cid for cid in _review_only(corpus, role) if cid in pairs]
    if not cases:
        return None
    count = {
        who: sum(int(pairs[cid]["human"].get(label, 0)) for cid in cases)
        for who, label in (
            ("candidate", candidate),
            ("incumbent", incumbent),
            ("ties", "empate"),
        )
    }
    return {
        "cases": cases,
        **count,
        "verdict": pairs_verdict(count["candidate"], count["incumbent"], count["ties"]),
    }


# --- CP-3 ---------------------------------------------------------------------------------------


def analyze_cp3(
    records: list[dict[str, Any]],
    corpus: dict[str, dict[str, Any]],
    small: Selector,
    large: Selector,
) -> dict[str, Any]:
    cfg_p, cfg_g = load_config(records, small), load_config(records, large)
    entry_control = small.label == large.label and small.variant != large.variant
    roles = sorted({c.role for cfg in (cfg_p, cfg_g) for c in cfg.cases.values()})
    output: dict[str, Any] = {
        "small": str(small),
        "large": str(large),
        "entry_control": entry_control,
        "roles": {},
    }
    for role in roles:
        ids = _role_cases(corpus, role, "quality")
        cases: dict[str, Any] = {}
        for cid in ids:
            m_p, m_g = _case(cfg_p, cid, corpus).median, _case(cfg_g, cid, corpus).median
            case_band = band_for_case([cfg_p, cfg_g], cid, corpus)
            if m_p is None or m_g is None:
                cases[cid] = {
                    "small": m_p,
                    "large": m_g,
                    "band": case_band,
                    "separates": False,
                    "reason": "sin puntuacion",
                }
                continue
            difference = m_g - m_p
            # En el control de entrada la direccion importa: la imagen correcta tiene que ganar.
            separates = (difference if entry_control else abs(difference)) > (
                case_band or 0.0
            ) + TOLERANCE
            at_ceiling = m_p == 1.0 and m_g == 1.0
            reason = None if separates else (CP3_CEILING if at_ceiling else "no separa")
            cases[cid] = {
                "small": m_p,
                "large": m_g,
                "difference": round(difference, 4),
                "band": case_band,
                "separates": separates,
                "direction": "large" if difference > 0 else "small" if difference < 0 else None,
                "reason": reason,
            }
        admitted = [cid for cid, c in cases.items() if c["separates"]]
        # §7 punto 4: si TODOS los casos del rol estan en techo, los dos modelos empatan en 1,0 y el
        # rol se decide por velocidad; no es un corpus que no discrimina. En el control de entrada
        # no aplica: que la imagen equivocada tambien de 1,0 es justo que el caso no reacciona.
        tie_at_ceiling = (
            not entry_control
            and bool(ids)
            and not admitted
            and all(c["reason"] == CP3_CEILING for c in cases.values())
        )
        if entry_control:
            passes = bool(ids) and len(admitted) == len(ids)
        else:
            passes = len(ids) <= 1 or bool(admitted) or tie_at_ceiling
        band = aggregate_band([cfg_p, cfg_g], admitted, corpus)
        aggregate_s = _media([cases[c]["small"] for c in admitted]) if admitted else None
        aggregate_l = _media([cases[c]["large"] for c in admitted]) if admitted else None
        aggregate_separates = (
            abs(aggregate_l - aggregate_s) > (band or 0.0) + TOLERANCE
            if aggregate_s is not None and aggregate_l is not None
            else False
        )
        worse = (
            min(aggregate_s, aggregate_l)
            if aggregate_s is not None and aggregate_l is not None
            else None
        )
        output["roles"][role] = {
            "band": band,
            "cases": cases,
            "admitted_cases": admitted,
            "passes": passes,
            "tie_at_ceiling": tie_at_ceiling,
            "aggregate": {
                "small": aggregate_s,
                "large": aggregate_l,
                "separates": aggregate_separates,
            },
            "can_fire": can_fire(band, worse),
            "no_aggregate": role in ROLES_WITHOUT_AGGREGATE,
            "review_only": _review_only(corpus, role),
        }
    return output


# --- §6: tanda no concluyente -------------------------------------------------------------------


def validate_batch(
    incumbent: Config,
    candidate: Config,
    role: str,
    corpus: dict[str, dict[str, Any]],
    shared_threshold_bytes: int,
) -> list[str]:
    """Motivos por los que el rol NO se puede interpretar. Vacio = concluyente."""
    reasons: list[str] = []
    configs = (incumbent, candidate)
    runs = [
        c for cfg in configs for case in cfg.cases.values() if case.role == role for c in case.runs
    ]
    discarded_ones = [c for c in runs if c.discarded]
    if runs and len(discarded_ones) * 3 > len(runs):
        reasons.append(
            f"{len(discarded_ones)} de {len(runs)} corridas descartadas (mas de una de cada tres)"
        )
    for cfg in configs:
        for cid in _role_cases(corpus, role, "quality"):
            if not _case(cfg, cid, corpus).qualities:
                reasons.append(f"{cfg.selector}: {cid} sin ninguna puntuacion valida")
    records = [r for cfg in configs for r in cfg.records if r.get("role") == role]
    # Por tipo de caso (§3.5, decision del usuario 2026-09-14): la calidad corre con el n_ctx del caso
    # mayor y los sondeos de techo en otra config con mas contexto, o medirian la ventana y no el
    # modelo. Lo que no vale es que vigente y candidato difieran DENTRO de un mismo tipo.
    for kind in sorted({r.get("kind") for r in records}, key=_kind_label):
        of_type = [r for r in records if r.get("kind") == kind]
        label = _kind_label(kind)
        for key, name in (("context_size", "n_ctx"), ("load_mode", "--load-mode")):
            values = {(r.get("variant") or {}).get(key) for r in of_type}
            if None in values:
                # Sin declararlo no se puede comprobar, y un control que no puede fallar no es control.
                reasons.append(f"{name} sin declarar en alguna corrida de {label}")
            elif len(values) > 1:
                reasons.append(
                    f"{name} distinto entre corridas de {label}: {sorted(map(str, values))}"
                )
    for cfg in configs:
        own = [r for r in cfg.records if r.get("role") == role]
        first_ones = [
            (r.get("resources") or {}).get("vram_shared_bytes_first")
            for r in own
            if (r.get("resources") or {}).get("vram_shared_bytes_first") is not None
        ]
        if not first_ones:
            continue
        base = min(first_ones)
        for r in own:
            peak = (r.get("resources") or {}).get("vram_shared_bytes_peak")
            if peak is not None and peak - base > shared_threshold_bytes:
                # §3.2: no se cae la corrida, se cae CP-1 y todo el tramo desde el ultimo CP-1 verde.
                reasons.append(
                    f"{cfg.selector}: Shared Usage crecio {peak - base} bytes en {r['case']} "
                    f"run={r.get('run')}: CP-1 dejo de valer, repetir el tramo"
                )
                break
    return reasons


# --- §7: regla de decision ----------------------------------------------------------------------


def _role_latency(
    configs: list[Config], ids: list[str], corpus
) -> tuple[list[float | None], float | None]:
    means = [_media([_case(cfg, cid, corpus).latency_median for cid in ids]) for cfg in configs]
    spreads = [
        d
        for cfg in configs
        for cid in ids
        if (d := _case(cfg, cid, corpus).latency_spread) is not None
    ]
    return means, (max(spreads) if spreads else None)


def accepted_ceiling(config: Config, role: str, corpus: dict[str, dict[str, Any]]) -> int | None:
    """Mayor entrada aceptada en un caso del rol. None si falta un sondeo de techo del corpus."""
    for cid in _role_cases(corpus, role, "ceiling"):
        if _case(config, cid, corpus).accepted is None:
            return None
    accepted = [
        int(case.runs[0].final.get("input_bytes") or 0)
        for case in config.cases.values()
        if case.role == role and case.runs and case.accepted
    ]
    return max(accepted, default=0)


def decide_role(
    role: str,
    incumbent: Config,
    candidate: Config,
    corpus: dict[str, dict[str, Any]],
    cp3: dict[str, Any] | None,
    shared_threshold_bytes: int = 0,
    pairs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ids = _role_cases(corpus, role, "quality")
    result: dict[str, Any] = {
        "role": role,
        "incumbent": str(incumbent.selector),
        "candidate": str(candidate.selector),
        "reasons": [],
    }
    inconclusive = validate_batch(incumbent, candidate, role, corpus, shared_threshold_bytes)
    if inconclusive:
        # §6: una tanda no concluyente no se interpreta; se repite el rol.
        return {**result, "verdict": "inconclusive", "reasons": inconclusive}
    if role in ROLES_WITHOUT_AGGREGATE:
        return {
            **result,
            "verdict": "no_aggregate",
            "reasons": [
                f"{role} no presenta agregado (§7): decide la tabla caso a caso y la revision"
            ],
        }
    if cp3 is None:
        raise ValueError(f"{role}: falta el resultado de CP-3; sin el no hay casos admitidos")

    admitted = [cid for cid in cp3.get("admitted_cases", []) if cid in ids]
    discards = {
        cid: (cp3.get("cases", {}).get(cid) or {}).get("reason") or "sin dato de CP-3"
        for cid in ids
        if cid not in admitted
    }
    result["admitted_cases"] = admitted
    result["discarded_cases"] = discards
    # Si CP-3 dejo TODOS los casos fuera por techo, los modelos del piloto empataban en 1,0: no hay
    # nada que separe por calidad, y eso no es un rol indecidible sino un empate. Decision del
    # usuario (tarea 19): «al mismo resultado, nos quedamos con el mas rapido». La calidad se
    # compara igual con todos los casos de ESTA tanda —un candidato que ya no da 1,0 pierde por
    # calidad—, y dentro de la banda deciden los desempates de siempre: techo, luego velocidad.
    all_at_ceiling = bool(ids) and not admitted and all(m == CP3_CEILING for m in discards.values())
    result["all_at_ceiling"] = all_at_ceiling
    quality_cases = admitted or (ids if all_at_ceiling else [])
    # P-15: los casos de texto abierto los decide la comparacion por pares a ciegas, no la formula.
    pair_cases = _review_only(corpus, role)
    role_pairs = pairs_for_role(
        pairs, corpus, role, str(incumbent.selector), str(candidate.selector)
    )
    result["pairs"] = role_pairs
    if not quality_cases and (role_pairs is None or role_pairs["verdict"] is None):
        return {
            **result,
            "verdict": "undecidable",
            "reasons": ["ningun caso de CP-3 separa: el rol es indecidible con este corpus"],
        }

    # Latencia de TODOS los casos de calidad: los de pares tambien corren y tardan.
    # Condicion 3 sobre los casos con latencia medida en LOS DOS (decision del usuario, tarea 20): el
    # vigente de long se corto en todas las corridas de lint-9k y la media del rol salia vacia, asi que
    # su fallo vetaba al candidato. Que un modelo no termine un caso ya lo castigan calidad y pares.
    lat_cases = ids + pair_cases
    with_latency = [
        cid
        for cid in lat_cases
        if all(_case(cfg, cid, corpus).latency_median is not None for cfg in (incumbent, candidate))
    ]
    (lat_v, lat_c), lat_band = _role_latency([incumbent, candidate], with_latency, corpus)
    has_ceiling = bool(_role_cases(corpus, role, "ceiling"))
    ceiling_i, ceiling_c = (
        accepted_ceiling(incumbent, role, corpus),
        accepted_ceiling(candidate, role, corpus),
    )
    result.update(
        {
            "weakly_decidable": len(quality_cases) < MIN_DECIDABLE_CASES and role_pairs is None,
            "latency_ms": {
                "incumbent": lat_v,
                "candidate": lat_c,
                "band": lat_band,
                "outside": [cid for cid in lat_cases if cid not in with_latency],
            },
            "ceiling_bytes": {"incumbent": ceiling_i, "candidate": ceiling_c}
            if has_ceiling
            else None,
        }
    )
    automatic: str | None = None
    if quality_cases:
        band = aggregate_band([incumbent, candidate], quality_cases, corpus) or 0.0
        q_v = _media([_case(incumbent, cid, corpus).median for cid in quality_cases])
        q_c = _media([_case(candidate, cid, corpus).median for cid in quality_cases])
        assert q_v is not None and q_c is not None  # §6 ya exige puntuacion valida en cada caso
        difference = q_c - q_v
        result.update(
            {
                "quality": {"incumbent": q_v, "candidate": q_c, "difference": round(difference, 4)},
                "band": band,
                "can_fire": can_fire(band, q_v),
            }
        )
        if difference > band + TOLERANCE:
            automatic = "mejor"
        elif difference < -band - TOLERANCE:
            automatic = "peor"
        else:
            automatic = "empate"

    # Quien gana por calidad: si alguna fuente dice «peor», pierde; si ninguna lo dice y alguna dice
    # «mejor», gana. Si no, la precedencia de desempates de siempre.
    sources = [f for f in (automatic, role_pairs and role_pairs["verdict"]) if f]
    wins: bool
    if "peor" in sources:
        wins, criterion = False, "calidad"
    elif "mejor" in sources:
        wins, criterion = True, "calidad"
    elif has_ceiling and (ceiling_i is None or ceiling_c is None):
        wins, criterion = False, "techo sin medir"
    elif has_ceiling and ceiling_c != ceiling_i:
        wins, criterion = bool(ceiling_c > ceiling_i), "techo"  # type: ignore[operator]
    elif lat_v is not None and lat_c is not None and abs(lat_c - lat_v) > (lat_band or 0.0):
        wins, criterion = lat_c < lat_v, "velocidad"
    else:
        wins, criterion = False, "empate"
    result["criterion"] = criterion

    blocks: list[str] = []
    if wins:
        # Condicion 2: ninguna corrida anulada, con error (OOM incluido) ni rechazo en calidad.
        for case in candidate.cases.values():
            if case.role != role:
                continue
            for run in case.runs:
                if run.discarded:
                    blocks.append(f"{case.id}: corrida anulada ({run.discard_reason})")
                elif run.outcome == "error":
                    blocks.append(f"{case.id}: error ({run.final.get('error')})")
                elif run.outcome == "context_rejection" and case.kind == "quality":
                    blocks.append(f"{case.id}: context_rejection en un caso de calidad")
        # Condicion 3: la latencia no empeora mas de un 50 %.
        if lat_v is None or lat_c is None:
            blocks.append("latencia sin medir")
        elif lat_c > MAX_LATENCY * lat_v:
            blocks.append(f"latencia {lat_c / lat_v:.2f}x la del vigente (maximo {MAX_LATENCY}x)")
        # Un rol con casos por pares no se cambia sin su comparacion: la formula no los ve.
        if pair_cases and role_pairs is None:
            blocks.append("falta la comparacion por pares de " + ", ".join(pair_cases) + " (P-15)")
        # El sondeo de techo entra en la decision, no solo en la hoja.
        if has_ceiling and (ceiling_i is None or ceiling_c is None):
            blocks.append("falta el sondeo de techo")
        elif has_ceiling and ceiling_c < ceiling_i:  # type: ignore[operator]
            blocks.append("el candidato no aguanta el sondeo de techo que el vigente si")
    result["reasons"] = blocks
    if wins and not blocks:
        result["verdict"] = "replace"
    else:
        result["verdict"] = "no_replace"
        if not wins:
            result["reasons"] = ["nadie mejora al vigente: el rol no se cambia (REQ-F2-6)"]
    return result


# --- Informe ------------------------------------------------------------------------------------


def _fmt(value: Any, decimals: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def _peak(config: Config, role: str, path: tuple[str, ...]) -> Any:
    values = []
    for r in config.records:
        # Solo calidad: el sondeo de techo corre con mas contexto y su KV inflaria la memoria de la
        # config que se decide (§3.5).
        if r.get("role") != role or r.get("kind") != "quality":
            continue
        value: Any = r
        for key in path:
            value = (value or {}).get(key)
        if value is not None:
            values.append(value)
    return max(values, default=None)


# Presupuesto de uso diario (protocolo §1.1, P-14): 16 GB de VRAM y 32 GB de RAM menos una reserva
# fija de 2 y 8 GB para el resto de la PC. Solo informativo: la regla de §7 no descarta por esto.
DAILY_USE_VRAM_BYTES = 14 * 1024**3
DAILY_USE_RAM_BYTES = 24 * 1024**3


def _fits_daily_use(vram_bytes: float | None, host_bytes: float | None) -> str:
    if vram_bytes is None or host_bytes is None:
        return "—"
    return (
        "si" if vram_bytes <= DAILY_USE_VRAM_BYTES and host_bytes <= DAILY_USE_RAM_BYTES else "no"
    )


def decision_report(
    decisions: list[dict[str, Any]], configs: dict[str, Config], corpus: dict[str, dict[str, Any]]
) -> str:
    lines = ["# Regla de decision de F2 (§6 y §7)", ""]
    lines += [
        "## Tabla 1: por rol",
        "",
        (
            "| Rol | Vigente | Candidato | Calidad v / c | Banda | Latencia ms v / c | "
            "RAM host pico c | RAM privada pico c | Working set pico c | VRAM dedicada pico c | "
            "Shared pico c | Cabe uso diario c | Descartadas | Rechazos | Veredicto | Criterio |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for d in decisions:
        cand = configs[d["candidate"]]
        runs = [c for case in cand.cases.values() if case.role == d["role"] for c in case.runs]
        quality = d.get("quality") or {}
        latency = d.get("latency_ms") or {}
        host = _peak(cand, d["role"], ("resources", "host_private_bytes_peak"))
        vram = _peak(cand, d["role"], ("resources", "vram_dedicated_bytes_peak"))
        lines.append(
            f"| {d['role']} | {d['incumbent']} | {d['candidate']} | "
            f"{_fmt(quality.get('incumbent'))} / {_fmt(quality.get('candidate'))} | {_fmt(d.get('band'))} | "
            f"{_fmt(latency.get('incumbent'), 0)} / {_fmt(latency.get('candidate'), 0)} | "
            f"{_fmt(host)} | "
            f"{_fmt(_peak(cand, d['role'], ('resources', 'private_bytes_peak')))} | "
            f"{_fmt(_peak(cand, d['role'], ('resources', 'working_set_bytes_peak')))} | "
            f"{_fmt(vram)} | "
            f"{_fmt(_peak(cand, d['role'], ('resources', 'vram_shared_bytes_peak')))} | "
            f"{_fits_daily_use(vram, host)} | "
            f"{sum(c.discarded for c in runs)} | "
            f"{sum(c.outcome == 'context_rejection' for c in runs)} | "
            f"**{d['verdict']}** | {d.get('criterion', '—')} |"
        )
    lines.append("")
    for d in decisions:
        lines.append(f"### {d['role']}: {d['verdict']}")
        lines.append("")
        for reason in d.get("reasons") or []:
            lines.append(f"- {reason}")
        if "admitted_cases" in d:
            lines.append(
                f"- casos en el agregado: {len(d['admitted_cases'])} ({', '.join(d['admitted_cases']) or 'ninguno'})"
            )
            for cid, reason in (d.get("discarded_cases") or {}).items():
                lines.append(f"- fuera del agregado: {cid} ({_cp3_reason_label(reason)})")
        if role_pairs := d.get("pairs"):
            lines.append(
                f"- comparacion por pares ({', '.join(role_pairs['cases'])}): candidato "
                f"{role_pairs['candidate']}, vigente {role_pairs['incumbent']}, empates "
                f"{role_pairs['ties']} -> **{role_pairs['verdict']}**"
            )
        if d.get("weakly_decidable"):
            lines.append("- **debilmente decidible**: menos de dos casos en el agregado")
        if d.get("can_fire") is False:
            lines.append(
                "- **la regla no puede disparar**: ni un candidato con calidad 1,0 superaria la banda; "
                "«no se cambia» aqui no distingue nada"
            )
        lines.append("")

    lines += [
        "## Tabla 2: caso a caso",
        "",
        "| Rol | Caso | Modelo | Corridas (calidad, outcome) | Mediana | Dispersion | Latencia mediana |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for d in decisions:
        for name in (d["incumbent"], d["candidate"]):
            cfg = configs[name]
            for cid, meta in corpus.items():
                if meta["role"] != d["role"]:
                    continue
                case = _case(cfg, cid, corpus)
                runs = (
                    ", ".join(
                        f"{_fmt(c.quality, 2)} {c.outcome}"
                        + (" descartada" if c.discarded else "")
                        + (" fria" if c.cold else "")
                        for c in case.runs
                    )
                    or "sin corridas"
                )
                lines.append(
                    f"| {d['role']} | {cid} | {name} | {runs} | {_fmt(case.median)} | "
                    f"{_fmt(case.dispersion)} | {_fmt(case.latency_median, 0)} |"
                )
    lines.append("")

    lines += [
        "## Tabla 3: entorno",
        "",
        "| Modelo | n_ctx | --load-mode | -ncmoe | llama-server | llama-swap | Anuladas (motivo) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, cfg in configs.items():
        variants = {json.dumps(r.get("variant") or {}, sort_keys=True) for r in cfg.records}
        for variant in sorted(variants):
            v = json.loads(variant)
            voided = sorted(
                {
                    f"{r['case']} run={r.get('run')} ({r.get('discarded_reason')})"
                    for r in cfg.records
                    if r.get("discarded")
                }
            )
            lines.append(
                f"| {name} | {_fmt(v.get('context_size'))} | {_fmt(v.get('load_mode'))} | {_fmt(v.get('n_cpu_moe'))} | "
                f"{_fmt(v.get('llama_server_version'))} | {_fmt(v.get('llama_swap_version'))} | {'; '.join(voided) or '—'} |"
            )
    conclusive = all(d["verdict"] != "inconclusive" for d in decisions)
    lines += ["", f"Tanda concluyente segun §6: **{'si' if conclusive else 'no'}**.", ""]

    lines += [
        "## Tabla 4: techo",
        "",
        "| Rol | Modelo | Mayor entrada aceptada (bytes) |",
        "| --- | --- | --- |",
    ]
    for d in decisions:
        for name in (d["incumbent"], d["candidate"]):
            lines.append(
                f"| {d['role']} | {name} | {_fmt(accepted_ceiling(configs[name], d['role'], corpus))} |"
            )
    lines.append("")
    return "\n".join(lines)


#: El motivo de CP-3 para un caso en techo, tal como se guarda en `cp3.json` (antes `techo`; el
#: viejo se lee traducido, `legacy_names`). Los mensajes lo siguen llamando «techo» (frente B).
CP3_CEILING = "ceiling"
_CP3_REASON_LABELS = {CP3_CEILING: "techo"}


def _cp3_reason_label(reason: Any) -> Any:
    return _CP3_REASON_LABELS.get(reason, reason)


def read_cp3(paths: list[Path]) -> dict[str, Any]:
    """Los roles de varios `cp3.json` (`analyze_benchmark cp3 --json`), con el motivo de cada caso
    en el formato nuevo: un `cp3.json` de antes dice `techo`."""
    per_role: dict[str, Any] = {}
    for path in paths:
        for role, data in json.loads(path.read_text(encoding="utf-8"))["roles"].items():
            cases = data.get("cases")
            if isinstance(cases, dict):
                data = {
                    **data,
                    "cases": {
                        cid: LEGACY_NAMES.normalize("cp3_case", c) if isinstance(c, dict) else c
                        for cid, c in cases.items()
                    },
                }
            per_role[role] = data
    return per_role


def cp3_report(result: dict[str, Any]) -> str:
    lines = [f"# CP-3: {result['small']} contra {result['large']}", ""]
    if result["entry_control"]:
        lines += [
            "Control de entrada: pasa si todos los casos bajan con la entrada de control.",
            "",
        ]
    for role, data in result["roles"].items():
        aggregate = data["aggregate"]
        state = "pasa" if data["passes"] else "NO pasa"
        if data.get("tie_at_ceiling"):
            state = "pasa por empate en techo (decide la velocidad, §7 punto 4)"
        lines += [
            f"## {role}: {state}",
            "",
            f"- banda del agregado (media de las bandas por caso): {_fmt(data['band'])}",
            f"- casos en el agregado: {len(data['admitted_cases'])} de {len(data['cases'])}",
            (
                f"- el agregado separa: {'si' if aggregate['separates'] else 'no'} "
                f"({_fmt(aggregate['small'])} contra {_fmt(aggregate['large'])})"
            ),
        ]
        if data["can_fire"] is False:
            lines.append("- **la regla de §7 no puede disparar con esta banda**")
        if data.get("review_only"):
            lines.append(
                "- sin puntuacion automatica, lo decide la comparacion por pares a ciegas: "
                + ", ".join(data["review_only"])
            )
        lines += [
            "",
            "| Caso | Pequeno | Grande | Diferencia | Banda | Separa | Motivo |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for cid, case in data["cases"].items():
            lines.append(
                f"| {cid} | {_fmt(case['small'])} | {_fmt(case['large'])} | "
                f"{_fmt(case.get('difference'))} | {_fmt(case.get('band'))} | "
                f"{'si' if case['separates'] else 'no'} | {_cp3_reason_label(case['reason']) or '—'} |"
            )
        lines.append("")
    return "\n".join(lines)


# --- Afinidad: puntuadores, criterios y veredicto (REQ-040 a REQ-043) ----------------------------
#
# Todo el criterio de la evaluacion que aprueba las celdas esta escrito aqui, en codigo, y se prueba
# con datos sinteticos antes de que exista un solo resultado real. Este modulo NO importa el paquete
# `local_delegate`: la tarea que recoge el juicio del usuario corre mientras otras tareas editan
# `server.py`, y importar el paquete lo cargaria a medio escribir. La huella de cada celda se COPIA
# de `footprints.json` (la calcula la tanda).

# Las cinco tools con celda mecanica. `local_summarize` esta fuera (REQ-011): sus casos de regresion
# se publican pero no deciden ninguna celda.
TOOLS_WITH_CELL = (
    "local_classify",
    "local_extract",
    "local_translate",
    "local_lint_summary",
    "local_delegate",
)
TOOL_COMMIT = "local_commit_msg"
WEAK_CONTROL = "qwen35-2b"  # control debil de la tanda (REQ-041), solo en las mecanicas
CEILING_CASE_ID = "techo-commit-156k"
CEILING_RUNS = 3
MAX_VERBOSITY = 1.5  # criterio 4
TRAPS_PER_SHEET = 3
MIN_TRAPS = 2  # criterio 0: la hoja vale si el usuario marca peor la trampa en 2 de las 3
COLD_GAP_S = 300  # una fila es «en frio» si el modelo llevaba >= 300 s sin peticiones (TTL max.)
_EPS = 1e-9


class NoData(ValueError):
    """Falta un dato que el criterio necesita. Nunca se sustituye por un valor: sin dato no hay
    veredicto, porque una celda aprobada con un hueco seria una celda aprobada a ciegas."""


# --- Puntuadores de las tools mecanicas -----------------------------------------------------------


def _strip_fences(text: str) -> str:
    """Lo mismo que `_strip_fences` de la tool: la salida que ve quien llama ya va sin vallas."""
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


def _json_equal(a: Any, b: Any) -> bool:
    """Igualdad estricta de valores JSON: `True` no es 1, `"502"` no es 502, `0` no es `null`."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


_TITLE = re.compile(r"^#{1,6}\s+\S")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})")


def markdown_structure(text: str) -> dict[str, Any]:
    """Titulos, elementos de lista y bloques de codigo de un Markdown, y el codigo de cada bloque.

    Lo de dentro de una valla no cuenta como titulo ni como lista: un `# comentario` de Python no es
    un encabezado.
    """
    titles = item_lists = 0
    blocks: list[str] = []
    fence: str | None = None
    current: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if fence is not None:
            closing = line.strip()
            if closing and set(closing) == {fence[0]} and len(closing) >= len(fence):
                blocks.append("\n".join(current))
                fence, current = None, []
            else:
                current.append(line)
            continue
        if m := _FENCE_OPEN.match(line):
            fence = m.group(1)
            continue
        titles += bool(_TITLE.match(line))
        item_lists += bool(_ITEM.match(line))
    if fence is not None:  # valla sin cerrar: cuenta como bloque (el modelo se quedo a medias)
        blocks.append("\n".join(current))
    return {"titles": titles, "lists": item_lists, "blocks": len(blocks), "code": blocks}


_RULE_CODE = re.compile(r"(?<![A-Za-z0-9])[A-Z]+[0-9]+(?![A-Za-z0-9])")
_BARE_INTEGER = re.compile(r"(?<![\w.])\d+(?!\w|\.\d)")


def rules_with_wrong_count(text: str, counts: dict[str, list[int]]) -> list[str]:
    """Las reglas de `conteos` cuyo numero NO cuadra con la fuente.

    Cada entero pertenece a la regla que tiene delante en su linea, hasta la siguiente regla. Cuadra
    si la regla tiene al menos un entero y todos estan entre los validos (el total, los archivos que
    la tienen o lo que suma en alguno). Una regla nombrada sin conteo no cuadra. Es la misma
    lectura que `check_counts` de `benchmark.py`, copiada porque este modulo no importa el paquete.
    """
    numbers: dict[str, list[int]] = {rule: [] for rule in counts}
    for line in text.splitlines():
        codes = list(_RULE_CODE.finditer(line))
        for i, code in enumerate(codes):
            if code.group() not in numbers:
                continue
            end = codes[i + 1].start() if i + 1 < len(codes) else len(line)
            numbers[code.group()] += [int(n) for n in _BARE_INTEGER.findall(line[code.end() : end])]
    return [
        rule
        for rule, valid in counts.items()
        if not numbers[rule] or not set(numbers[rule]) <= set(valid)
    ]


def score_affinity(
    case: dict[str, Any], text: str, record: dict[str, Any] | None = None
) -> dict[str, Any]:
    """`{"quality": 0..1, "format": bool}` de una respuesta, con el puntuador DEL caso.

    El puntuador sale de `cases.json` (`scorer`), con lo esperado calculado por el constructor del
    corpus a partir de la fuente, no de lo que respondio un modelo. `format` es lo que la tool
    prometio (una etiqueta, un objeto JSON con esas claves, la estructura Markdown, un limite de
    palabras, un formato exacto); `quality` es si ademas es correcto.
    """
    case = LEGACY_NAMES.normalize("affinity_case", case)
    spec = LEGACY_NAMES.normalize("affinity_scorer", case.get("scorer") or {})
    kind = spec.get("kind")
    if kind == "classify":
        response = text.strip()
        return {
            "quality": 1.0 if response in spec["acceptable"] else 0.0,
            "format": response in spec["labels"],
        }
    if kind == "extract":
        try:
            obj = json.loads(_strip_fences(text))
        except ValueError:
            obj = None
        if not isinstance(obj, dict) or set(obj) != set(spec["keys"]):
            return {"quality": 0.0, "format": False}
        good = sum(_json_equal(obj[c], spec["expected"][c]) for c in spec["keys"])
        return {"quality": good / len(spec["keys"]), "format": True}
    if kind == "translate":
        est = markdown_structure(text)
        structure = [
            est["titles"] == spec["titles"],
            est["lists"] == spec["lists"],
            est["blocks"] == spec["blocks"],
        ]
        inside = set(est["code"])
        tests_run = structure + [block in inside for block in spec["code"]]
        return {"quality": sum(tests_run) / len(tests_run), "format": all(structure)}
    if kind == "lint":
        bad_ones = rules_with_wrong_count(text, spec["counts"])
        words = len(re.findall(r"\w+", text))
        return {
            "quality": (len(spec["counts"]) - len(bad_ones)) / len(spec["counts"]),
            "format": bool(text.strip()) and words <= spec["max_words"],
        }
    if kind == "delegate":
        response = text.strip()
        return {
            "quality": 1.0 if response == spec["expected"] else 0.0,
            "format": re.fullmatch(spec["format"], response) is not None,
        }
    if kind == "f2":
        # Los cinco casos de regresion de F2 conservan su puntuacion de entonces, la del runner.
        scoring = (record or {}).get("score") or {}
        quality = scoring.get("quality")
        fmt = scoring.get("format_ok")
        return {
            "quality": float(quality) if quality is not None else 0.0,
            "format": True if fmt is None else bool(fmt),
        }
    raise ValueError(f"{case.get('id')}: puntuador {kind!r} desconocido")


# --- Reglas, huellas y resultados -----------------------------------------------------------------

POSSIBLE_OPTIONAL_QUESTIONS = frozenset({"principal", "specific"})


def read_affinity_rules(path: Path) -> dict[str, Any]:
    """`rules.json` (o el `reglas.json` congelado), validado. Una regla invalida lo rechaza entero: no
    hay valores por defecto."""
    rules = LEGACY_NAMES.normalize_affinity_rules(json.loads(path.read_text(encoding="utf-8")))
    maximum = rules.get("max_made_up_26b")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
        raise SystemExit(f"{path.name}: max_made_up_26b tiene que ser un entero >= 0")
    optional_ones = rules.get("optional_questions")
    if not isinstance(optional_ones, list) or not set(optional_ones) <= POSSIBLE_OPTIONAL_QUESTIONS:
        raise SystemExit(
            f"{path.name}: optional_questions solo admite 'principal' y 'specific'; "
            "'inventa' y la preferencia no pueden ser opcionales"
        )
    if not isinstance(rules.get("format"), dict):
        raise SystemExit(f"{path.name}: falta la regla de formato")
    if not isinstance(rules.get("early_stop"), bool):
        raise SystemExit(f"{path.name}: early_stop tiene que ser true o false")
    return rules


def message_format(message: str, rule: dict[str, Any]) -> bool:
    """«Formato» de un mensaje de commit, calculado por el programa con la regla de `rules.json`.

    Primera linea de 72 caracteres como maximo, prefijo convencional y sin adornos: ni vallas de
    codigo, ni comillas que envuelvan el mensaje, ni encabezados Markdown, ni frases de
    presentacion. Se publica; no decide ninguna celda.
    """
    text = message.strip("\n")
    if not text.strip():
        return False
    first_one = text.split("\n", 1)[0]
    if len(first_one) > int(rule["first_line_max"]):
        return False
    if re.match(rule["prefix"], first_one) is None:
        return False
    decorations = rule["no_frills"]
    lines = text.split("\n")
    if decorations.get("code_fences") and any(
        line.strip().startswith(("```", "~~~")) for line in lines
    ):
        return False
    bare = text.strip()
    if (
        decorations.get("wrapping_quotes")
        and len(bare) > 1
        and bare[0] in "\"'`“«‘"
        and bare[-1] in "\"'`”»’"
    ):
        return False
    if decorations.get("markdown_headings") and any(re.match(r"^#{1,6}\s", x) for x in lines):
        return False
    return not any(
        re.match(pattern, first_one, re.IGNORECASE)
        for pattern in decorations.get("intro_phrases", [])
    )


@dataclass
class Result:
    """Lo que un modelo hizo en un caso, ya reducido a lo que miran los criterios."""

    label: str
    case: str
    ok: bool  # la corrida termino bien (ultimo intento)
    fails: bool  # algun intento no anulado dio error, timeout, rechazo o `length`
    quality: float
    fmt: bool
    chars: int
    latency_ms: float | None
    text: str


Runs = dict[tuple[str, str, int], list[dict[str, Any]]]


def group_runs(records: list[dict[str, Any]]) -> Runs:
    """`(label, caso, corrida) -> intentos` en el orden del fichero: el ultimo intento manda."""
    runs: Runs = {}
    for r in records:
        if r.get("input_variant") is not None:
            continue
        runs.setdefault((str(r["label"]), str(r["case"]), int(r["run"])), []).append(r)
    return runs


# Motivos de anulación de la sonda que solo dejan la fila sin medida de recursos (RAM o VRAM): la
# respuesta es válida y este veredicto no juzga recursos, así que la fila cuenta. Pasa con peticiones
# de menos de 100 ms, que terminan antes de que la sonda muestree. Un proceso que cambió o varios
# procesos sí invalidan la corrida y se siguen descartando. Solo afecta al veredicto de afinidad.
RESOURCE_ONLY_REASONS = frozenset({"zero_vram_samples", "zero_ram_samples"})


def _cancelled(attempt: dict[str, Any]) -> bool:
    """La fila no vale para el veredicto de afinidad (ver `RESOURCE_ONLY_REASONS`)."""
    return bool(attempt.get("discarded")) and (
        attempt.get("discarded_reason") not in RESOURCE_ONLY_REASONS
    )


def _fails(attempt: dict[str, Any]) -> bool:
    return not _cancelled(attempt) and attempt.get("outcome") != "ok"


def result_of(
    runs: Runs, label: str, case: dict[str, Any], run: int = 1, *, score_fn: bool = True
) -> Result:
    attempts = runs.get((label, case["id"], run))
    if not attempts:
        raise NoData(f"falta la corrida {run} de {label} en {case['id']}")
    final = attempts[-1]
    if _cancelled(final):
        raise NoData(f"{label}:{case['id']} corrida {run}: anulada y sin repetir")
    ok = final.get("outcome") == "ok"
    text = str(final.get("response") or "")
    if ok and "response" not in final:
        raise NoData(f"{label}:{case['id']}: sin respuesta guardada (falta --save-responses)")
    if ok and score_fn:
        point = score_affinity(case, text, final)
    else:
        # Un caso que no termino puntua 0: una respuesta que no existe no puede ser mejor que otra.
        point = {"quality": 0.0, "format": False}
    hot = ok and final.get("thermal_state") != "cold"
    return Result(
        label=label,
        case=case["id"],
        ok=ok,
        fails=any(_fails(i) for i in attempts),
        quality=float(point["quality"]),
        fmt=bool(point["format"]),
        chars=int(final.get("response_chars") or len(text)),
        latency_ms=float(final["latency_ms"]) if hot and "latency_ms" in final else None,
        text=text,
    )


def median_cold_load(db: Path, model: str, gap_s: int = COLD_GAP_S) -> float | None:
    """Mediana (s) de lo que tarda una peticion en frio en `modelo`, de una COPIA de `metrics.db`.

    Una fila es «en frio» si el modelo llevaba al menos `gap_s` sin peticiones (venció su TTL) y
    termino bien. Su carga es lo que sobra de la duracion al quitarle la inferencia: `duration_ms`
    incluye la cola y la carga del modelo (`ts_created` es el momento en que termina).
    """
    connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT ts_created, model_id, input_tokens, output_tokens, prompt_per_second, "
            "tokens_per_second, duration_ms, resp_status_code, error_msg "
            "FROM activity ORDER BY ts_created, id"
        ).fetchall()
    finally:
        connection.close()
    last: dict[str, float] = {}
    waits: list[float] = []
    for ts, model_id, enters, outcome, pps, tps, duration, state, error in rows:
        start_ts = ts - duration / 1000
        prior = last.get(model_id)
        if (
            model_id == model
            and prior is not None
            and start_ts - prior >= gap_s
            and state == 200
            and not error
            and outcome > 0
        ):
            inference = (enters / pps if pps else 0.0) + (outcome / tps if tps else 0.0)
            waits.append(max(0.0, duration / 1000 - inference))
        last[model_id] = ts
    return statistics.median(waits) if waits else None


# --- Celda mecanica (REQ-043, criterios 1 a 6) ------------------------------------------------------


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def evaluate_mechanical_cell(
    tool: str,
    alternative: str,
    role: str,
    cases: list[dict[str, Any]],
    runs: Runs,
    role_cold_s: float | None,
    weak: str = WEAK_CONTROL,
) -> dict[str, Any]:
    """Estado y criterios de una celda mecanica `tool -> alternativo`, comparada con `rol`.

    El orden de los desenlaces es fijo: si falla el criterio 1 la celda queda `no_baseline`, falle lo
    que falle ademas; si el 1 se cumple y falla cualquier otro, `rejected`; si todos, `approved`.
    Los casos de regresion (no discriminantes) cuentan en los criterios 2 a 6 pero no en el 1.
    """
    cases = [LEGACY_NAMES.normalize("affinity_case", c) for c in cases]
    discriminating = [c for c in cases if c.get("discriminating")]
    if not discriminating:
        raise NoData(f"{tool}: el corpus no trae casos discriminantes")
    res = {
        (label, c["id"]): result_of(runs, label, c)
        for label in (alternative, role, weak)
        for c in cases
    }

    # 1. El corpus discrimina: las referencias separan y alguien saca menos de 1.
    bad_references = []
    for c in discriminating:
        ok = score_affinity(c, c["reference_ok"])
        bad = score_affinity(c, c["reference_bad"])
        if ok["quality"] != 1.0 or not ok["format"] or bad["quality"] >= 1.0:
            bad_references.append(c["id"])
    scores_below_one = [
        c["id"]
        for c in discriminating
        if res[(role, c["id"])].quality < 1.0 or res[(weak, c["id"])].quality < 1.0
    ]
    discriminates = {
        "ok": not bad_references and bool(scores_below_one),
        "bad_references": bad_references,
        "cases_where_role_or_weak_fail": scores_below_one,
    }

    # 2. Calidad: en cada caso, M >= el rol.
    worst = [
        c["id"]
        for c in cases
        if res[(alternative, c["id"])].quality < res[(role, c["id"])].quality - _EPS
    ]
    quality = {"ok": not worst, "worse_cases": worst}

    # 3. Formato: donde el rol da formato correcto, M tambien.
    unformatted = [
        c["id"] for c in cases if res[(role, c["id"])].fmt and not res[(alternative, c["id"])].fmt
    ]
    fmt = {"ok": not unformatted, "cases_without_format": unformatted}

    # 4. Verbosidad: la mediana de chars(M)/chars(rol) <= 1,5.
    ratios = [
        res[(alternative, c["id"])].chars / res[(role, c["id"])].chars
        for c in cases
        if res[(role, c["id"])].chars > 0
    ]
    ratio_median = _median(ratios)
    verbosity = {
        "ok": ratio_median is not None and ratio_median <= MAX_VERBOSITY,
        "median": ratio_median,
        "max": MAX_VERBOSITY,
    }

    # 5. Fiabilidad: ningun caso donde M falla y el rol no.
    failures = [
        c["id"]
        for c in cases
        if res[(alternative, c["id"])].fails and not res[(role, c["id"])].fails
    ]
    reliability = {"ok": not failures, "cases_failing_only_in_alternative": failures}

    # 6. Latencia: mediana en caliente de M <= la del rol mas su carga en frio mediana.
    lat_m = _median(
        [
            r.latency_ms
            for (lab, _), r in res.items()
            if lab == alternative and r.latency_ms is not None
        ]
    )
    lat_r = _median(
        [r.latency_ms for (lab, _), r in res.items() if lab == role and r.latency_ms is not None]
    )
    cold = role_cold_s if role_cold_s is not None else 0.0
    latency = {
        "ok": lat_m is not None and lat_r is not None and lat_m <= lat_r + cold * 1000,
        "alternative_median_ms": lat_m,
        "role_median_ms": lat_r,
        "cold_load_role_s": role_cold_s,
        "note": None if role_cold_s is not None else "sin filas en frio en metrics.db: se usa 0 s",
    }

    criteria = {
        "discriminates": discriminates,
        "quality": quality,
        "format": fmt,
        "verbosity": verbosity,
        "reliability": reliability,
        "latency": latency,
    }
    if not discriminates["ok"]:
        state = "no_baseline"
    elif all(v["ok"] for v in criteria.values()):
        state = "approved"
    else:
        state = "rejected"
    return {
        "tool": tool,
        "alternative": alternative,
        "compared_role": role,
        "state": state,
        "criteria": criteria,
        "cases": len(cases),
    }


# --- Celda de commit (REQ-043, criterios 0 a 3) -----------------------------------------------------


_PUBLISHED_ROW = {"messages": 0, "made_up": 0, "format": 0, "main_yes": 0, "specific_yes": 0}


def _preferred(pair: dict[str, Any]) -> str:
    """Quien gano el par: el nombre del lado elegido, o `empate`."""
    choice = pair.get("preference")
    if choice is None:
        raise NoData(f"el par {pair.get('case')} no tiene preferencia")
    return "empate" if choice == "=" else str(pair["sides"][choice])


def evaluate_commit_cell(
    alternative: str,
    role: str,
    judgement: dict[str, Any],
    rules: dict[str, Any],
    real_cases: list[dict[str, Any]],
    runs: Runs,
    ceiling: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """`local_commit_msg -> alternativo` con la regla del usuario, fijada antes de ver datos.

    0 (hoja valida): el usuario marca peor la trampa en 2 de las 3. 1: «inventa = si» en no mas de
    `max_made_up_26b` de los 30 mensajes del 26B. 2: `c >= v`. 3: el techo termina 3 de 3 y ningun
    caso falla en el 26B si no falla en el modelo de codigo. Si falla el 0, `no_baseline`; si el 0 se
    cumple y falla el 1, el 2 o el 3, `rejected`.
    """
    judgement = LEGACY_NAMES.normalize_commit_judgement(judgement)
    rules = LEGACY_NAMES.normalize_affinity_rules(rules)
    if judgement.get("partial"):
        raise NoData("el juicio es parcial: el veredicto necesita la hoja entera")
    pair_items = judgement["pairs"]
    traps = [p for p in pair_items.values() if p["kind"] == "trampa"]
    real = [p for p in pair_items.values() if p["kind"] == "real"]
    if len(traps) != TRAPS_PER_SHEET:
        raise NoData(f"la hoja tiene {len(traps)} pares trampa y se esperaban {TRAPS_PER_SHEET}")
    worst = 0
    for p in traps:
        winner = _preferred(p)
        worst += winner not in ("empate", "trampa")
    sheet = {
        "ok": worst >= MIN_TRAPS,
        "traps_flagged_as_worse": worst,
        "de": len(traps),
    }

    invents_if = 0
    n = 0
    published: dict[str, dict[str, int]] = {}
    for p in real:
        for side, model in p["sides"].items():
            row = published.setdefault(model, dict(_PUBLISHED_ROW))
            row["messages"] += 1
            row["made_up"] += p["made_up"][side] == "s"
            row["main_yes"] += (p.get("principal") or {}).get(side) == "s"
            row["specific_yes"] += (p.get("specific") or {}).get(side) == "s"
        if p["sides"]["A"] == alternative or p["sides"]["B"] == alternative:
            side = "A" if p["sides"]["A"] == alternative else "B"
            n += 1
            invents_if += p["made_up"][side] == "s"
    invents = {
        "ok": invents_if <= int(rules["max_made_up_26b"]),
        "n": n,
        "yes": invents_if,
        "max": int(rules["max_made_up_26b"]),
    }

    c = sum(_preferred(p) == alternative for p in real)
    v = sum(_preferred(p) == role for p in real)
    preference = {"ok": c >= v, "c": c, "v": v, "ties": len(real) - c - v}

    # 3a: el techo por el camino de produccion, 3 de 3 sin error con el 26B.
    ceiling_runs = []
    for run in range(1, CEILING_RUNS + 1):
        if ceiling:
            ceiling_runs.append(result_of(runs, alternative, ceiling[0], run, score_fn=False))
    ceiling_ok = (
        bool(ceiling)
        and len(ceiling_runs) == CEILING_RUNS
        and not any(r.fails for r in ceiling_runs)
    )
    # 3b: ningun caso falla en el alternativo si no falla en el modelo de codigo.
    only_in_alternative = []
    for case in real_cases:
        a = result_of(runs, alternative, case, score_fn=False)
        r = result_of(runs, role, case, score_fn=False)
        if a.fails and not r.fails:
            only_in_alternative.append(case["id"])
        # «Formato» lo calcula el programa sobre el mensaje tal como lo devolvio la tool.
        for result in (a, r):
            row = published.setdefault(result.label, dict(_PUBLISHED_ROW))
            row["format"] += result.ok and message_format(result.text, rules["format"])
    behaviour = {
        "ok": ceiling_ok and not only_in_alternative,
        "ceiling_3_of_3": ceiling_ok,
        "cases_failing_only_in_alternative": only_in_alternative,
    }

    criteria = {
        "valid_sheet": sheet,
        "made_up": invents,
        "preference": preference,
        "behaviour": behaviour,
    }
    report = None
    if not sheet["ok"]:
        state = "no_baseline"
        report = (
            "repetir hoja"
            if int(judgement.get("set") or 1) < 3
            else "la tercera hoja tampoco vale: sin base"
        )
    elif invents["ok"] and preference["ok"] and behaviour["ok"]:
        state = "approved"
    else:
        state = "rejected"
    return {
        "tool": TOOL_COMMIT,
        "alternative": alternative,
        "compared_role": role,
        "state": state,
        "criteria": criteria,
        "report": report,
        "published": published,
        "cases": len(real),
    }


# --- Veredicto -------------------------------------------------------------------------------------


def _frozen_fallback(path: Path, names: tuple[str, str]) -> Path:
    """`path` y, si es el nombre nuevo y no existe, el viejo de al lado (la tanda congelada, de
    antes del renombrado). Otro nombre se lee tal cual."""
    old_name, new_name = names
    if path.name == new_name and not path.exists():
        return path.with_name(old_name)
    return path


def footprints_file(path: Path) -> Path:
    """Las huellas que se leen: `footprints.json` o, si no existe, la `huellas.json` congelada."""
    return _frozen_fallback(path, LEGACY_NAMES.FOOTPRINTS_FILE_NAMES)


def rules_file(path: Path) -> Path:
    """Las reglas que se leen: `rules.json` o, si no existe, el `reglas.json` congelado."""
    return _frozen_fallback(path, LEGACY_NAMES.RULES_FILE_NAMES)


def _footprint(footprints: dict[str, Any], model: str, tool: str) -> dict[str, Any]:
    try:
        # `huellas.json` congelado trae `ruta`/`tamano_bytes`: el veredicto sale con las nuevas.
        return dict(LEGACY_NAMES.normalize_footprint(dict(footprints[model][tool])))
    except (KeyError, TypeError) as exc:
        raise NoData(f"footprints.json no trae la huella de {model} para {tool}") from exc


def compute_verdict(
    corpus: dict[str, dict[str, Any]],
    production_config: dict[str, Any],
    runs: Runs,
    footprints: dict[str, Any],
    role_cold_s: float | None,
    rules: dict[str, Any],
    judgement: dict[str, Any] | None,
    *,
    mechanical_only: bool = False,
) -> dict[str, Any]:
    """Aplica los criterios literalmente y devuelve el contenido de `verdict.json`.

    No hay ningun parametro que fuerce un estado: la unica forma de cambiar un estado es cambiar los
    datos.
    """
    corpus = {k: LEGACY_NAMES.normalize("affinity_case", c) for k, c in corpus.items()}
    models = production_config["models"]
    mechanical_role, long, code = models["mechanical"], models["long"], models["code"]
    cases = [
        c for c in corpus.values() if c.get("kind") == "quality" and c.get("sheet_role") != "trampa"
    ]
    cells: list[dict[str, Any]] = []
    for tool in TOOLS_WITH_CELL:
        tool_name = [c for c in cases if c["tool"] == tool]
        if not tool_name:
            continue
        for alternative in (long, code):
            cell = evaluate_mechanical_cell(
                tool, alternative, mechanical_role, tool_name, runs, role_cold_s
            )
            cell["footprint"] = _footprint(footprints, alternative, tool)
            cell["role_footprint"] = _footprint(footprints, mechanical_role, tool)
            cells.append(cell)
    if not mechanical_only:
        if judgement is None:
            raise NoData(
                "falta el juicio del usuario (`read-commit --output`) para la celda de commit"
            )
        real = [c for c in cases if c["tool"] == TOOL_COMMIT and c.get("sheet_role") == "real"]
        ceiling = [c for c in corpus.values() if c["id"] == CEILING_CASE_ID]
        cell = evaluate_commit_cell(long, code, judgement, rules, real, runs, ceiling)
        cell["footprint"] = _footprint(footprints, long, TOOL_COMMIT)
        cell["role_footprint"] = _footprint(footprints, code, TOOL_COMMIT)
        cells.append(cell)
    return {
        "schema_version": 1,
        "mechanical_only": mechanical_only,
        "rules": rules,
        "cells": cells,
    }


#: Como se lee el estado de una celda en la tabla: el `verdict.json` guarda el valor en ingles
#: (`state`), la tabla es para leerla una persona y sigue en espanol (frente B).
_STATE_LABELS = {"approved": "aprobada", "rejected": "rechazada", "no_baseline": "sin base"}


def verdict_table(verdict: dict[str, Any]) -> str:
    """La tabla Markdown que se pega en `verification.md`."""
    lines = [
        "| Tool | Alternativo | Comparado con | Estado | Criterios que no se cumplen |",
        "| --- | --- | --- | --- | --- |",
    ]
    for cell in verdict["cells"]:
        fails = [name for name, c in cell["criteria"].items() if not c["ok"]]
        extra = f" ({cell['report']})" if cell.get("report") else ""
        lines.append(
            f"| {cell['tool']} | {cell['alternative']} | {cell['compared_role']} | "
            f"{_STATE_LABELS.get(cell['state'], cell['state'])}{extra} | {', '.join(fails) or '—'} |"
        )
    commit = next((c for c in verdict["cells"] if c["tool"] == TOOL_COMMIT), None)
    if commit:
        lines += ["", "Celda de commit, lo que se publica y no decide:", ""]
        lines += [
            "| Modelo | Mensajes | inventa = si | Formato (calculado) | Lo principal = si | Especifico = si |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for model, row in sorted(commit["published"].items()):
            lines.append(
                f"| {model} | {row['messages']} | {row['made_up']} | {row['format']} | "
                f"{row['main_yes']} | {row['specific_yes']} |"
            )
    return "\n".join(lines) + "\n"


def run_verdict(args: argparse.Namespace) -> int:
    cases_path: Path = args.cases
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 2:
        raise ValueError(f"{cases_path}: se esperaba un corpus schema_version 2")
    corpus = {c["id"]: c for c in data["cases"]}
    rules_path = rules_file(args.rules)
    rules = read_affinity_rules(rules_path)
    footprints = json.loads(footprints_file(args.footprints).read_text(encoding="utf-8"))
    runs = group_runs(read_jsonl(args.jsonl))
    judgement = json.loads(args.judgement.read_text(encoding="utf-8")) if args.judgement else None
    mechanical_role = data["production_config"]["models"]["mechanical"]
    if args.metrics_db is None:
        raise NoData("falta --metrics-db (una COPIA de metrics.db) para el criterio 6")
    cold = median_cold_load(args.metrics_db, mechanical_role)
    verdict = compute_verdict(
        corpus,
        data["production_config"],
        runs,
        footprints,
        cold,
        rules,
        judgement,
        mechanical_only=args.mechanical_only,
    )
    verdict["rules_sha256"] = hashlib.sha256(rules_path.read_bytes()).hexdigest()
    verdict["cases_sha256"] = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    output = args.output or cases_path.parent / (
        "verdict-mechanical.json" if args.mechanical_only else LEGACY_NAMES.VERDICT_FILE_NAMES[1]
    )
    output.write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    table = verdict_table(verdict)
    if args.table:
        args.table.write_text(table, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(table)
    return 0


def _verdict_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "affinity-verdict",
        help="aplica los criterios de aceptacion de las celdas (REQ-043) y escribe verdict.json",
    )
    base = Path(__file__).resolve().parents[1] / "benchmarks" / "afinidad-2026-10"
    p.add_argument("--cases", type=Path, default=base / "cases.json")
    p.add_argument("--rules", type=Path, default=base / LEGACY_NAMES.RULES_FILE_NAMES[1])
    p.add_argument("--footprints", type=Path, default=base / LEGACY_NAMES.FOOTPRINTS_FILE_NAMES[1])
    p.add_argument(
        "--judgement", type=Path, default=None, help="salida de `pair_sheet.py read-commit`"
    )
    p.add_argument("--metrics-db", type=Path, default=None, help="una COPIA de metrics.db")
    p.add_argument("--mechanical-only", action="store_true", help="sin la celda de commit")
    p.add_argument("--output", type=Path, default=None, help="verdict.json")
    p.add_argument("--table", type=Path, default=None, help="tabla Markdown para verification.md")
    p.add_argument("jsonl", nargs="+", type=Path, help="resultados de la tanda")


# --- CLI ----------------------------------------------------------------------------------------


def merge_unblinded_pairs(paths: list[Path]) -> dict[str, Any] | None:
    """Suma por caso las elecciones de varios `pair_sheet.py unblind --json`; `None` sin ninguno.
    Lee las filas en los dos formatos (`humano` antes del renombrado, `human` despues)."""
    pairs: dict[str, Any] | None = None
    for path in paths:
        pairs = pairs or {}
        for cid, raw in json.loads(path.read_text(encoding="utf-8")).items():
            row = LEGACY_NAMES.normalize("unblinded_pairs", raw)
            previous = pairs.setdefault(cid, {"human": {}})["human"]
            for who, n in row["human"].items():
                previous[who] = previous.get(who, 0) + int(n)
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    _verdict_parser(sub)
    for name in ("cp3", "decide"):
        p = sub.add_parser(name)
        p.add_argument("--cases", type=Path, required=True, help="cases.json del corpus v2")
        p.add_argument(
            "--json", type=Path, default=None, help="escribe tambien el resultado en JSON"
        )
        p.add_argument(
            "--output", type=Path, default=None, help="escribe el informe aqui en vez de stdout"
        )
        p.add_argument("jsonl", nargs="+", type=Path)
    cp3 = sub.choices["cp3"]
    cp3.add_argument("--small", required=True, help="label, o label@control")
    cp3.add_argument("--large", required=True, help="label, o label@control")
    decide = sub.choices["decide"]
    decide.add_argument(
        "--cp3", type=Path, action="append", default=[], help="JSON de `cp3` (repetible)"
    )
    decide.add_argument(
        "--pair",
        nargs=3,
        action="append",
        required=True,
        metavar=("ROLE", "INCUMBENT", "CANDIDATE"),
    )
    decide.add_argument(
        "--pairs",
        type=Path,
        action="append",
        default=[],
        help="JSON de `pair_sheet.py unblind --json` (repetible, uno por comparacion)",
    )
    decide.add_argument(
        "--shared-mib-threshold",
        type=float,
        default=0.0,
        help="crecimiento de Shared Usage tolerado antes de dar CP-1 por caido (sin calibrar: tarea 18)",
    )
    args = parser.parse_args(argv)

    if args.mode == "affinity-verdict":
        try:
            return run_verdict(args)
        except (OSError, ValueError, KeyError) as exc:  # `NoData` es un `ValueError`
            print(f"error: {exc}", file=sys.stderr)
            return 2

    try:
        corpus = read_corpus(args.cases)
        records = read_jsonl(args.jsonl)
        if args.mode == "cp3":
            result: Any = analyze_cp3(
                records, corpus, Selector.parse(args.small), Selector.parse(args.large)
            )
            text = cp3_report(result)
        else:
            cp3_per_role = read_cp3(args.cp3)
            pairs = merge_unblinded_pairs(args.pairs)
            configs: dict[str, Config] = {}
            decisions = []
            for role, incumbent, candidate in args.pair:
                pair = []
                for name in (incumbent, candidate):
                    selector = Selector.parse(name)
                    configs.setdefault(str(selector), load_config(records, selector))
                    pair.append(configs[str(selector)])
                decisions.append(
                    decide_role(
                        role,
                        pair[0],
                        pair[1],
                        corpus,
                        cp3_per_role.get(role),
                        round(args.shared_mib_threshold * 1024 * 1024),
                        pairs,
                    )
                )
            result = {"decisions": decisions}
            text = decision_report(decisions, configs, corpus)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        args.json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
