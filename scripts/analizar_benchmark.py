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
  tanda, la huella de cada celda (`huellas.json`), `reglas.json` y el juicio del usuario, y escribe
  `veredicto.json` y la tabla de `verification.md`. No importa `local_delegate`.

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
    python scripts/analizar_benchmark.py cp3 --cases benchmarks/catalogo-2026-09/cases.json \\
        --pequeno qwen35-2b --grande qwen25-coder-14b --json cp3.json resultados/cp3-*.jsonl
    python scripts/analizar_benchmark.py decidir --cases benchmarks/catalogo-2026-09/cases.json \\
        --cp3 cp3.json --par long llama31-8b gemma4-26b-a4b resultados/*.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
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
ROLES_SIN_AGREGADO = frozenset({"vision", "fast"})
MIN_CASOS_DECIDIBLE = 2
LATENCIA_MAXIMA = 1.5
# El runner redondea la cobertura a 4 decimales: 0,3334 contra una banda de 0,3333 no es mejora, es
# redondeo. Menor que el paso real mas fino del corpus (1/6 por caso, 1/24 en un agregado de 4).
TOLERANCIA = 1e-3
# Comparacion por pares (P-15): prueba de signos de una cola sobre los pares con eleccion.
ALFA_PARES = 0.05
# Aceptadas: el backend recibio la entrada entera, aunque luego no puntue.
_ACEPTADAS = frozenset({"ok", "truncado", "configuracion"})


# --- Lectura ------------------------------------------------------------------------------------


def leer_jsonl(rutas: list[Path]) -> list[dict[str, Any]]:
    registros: list[dict[str, Any]] = []
    for ruta in rutas:
        for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
            if not linea.strip():
                continue
            registro = json.loads(linea)
            if registro.get("schema_version") != 2:
                raise ValueError(f"{ruta}:{numero}: se esperaba schema_version 2")
            registros.append(registro)
    return registros


def leer_corpus(ruta: Path) -> dict[str, dict[str, Any]]:
    """Solo ids, rol y tipo: el analisis no toca las fuentes, las verifica el runner."""
    data = json.loads(ruta.read_text(encoding="utf-8"))
    if data.get("schema_version") != 2:
        raise ValueError(f"{ruta}: se esperaba un corpus schema_version 2")
    return {c["id"]: c for c in data["cases"]}


@dataclass(frozen=True)
class Selector:
    label: str
    variante: str | None

    @classmethod
    def parse(cls, texto: str) -> Selector:
        label, _, variante = texto.partition("@")
        return cls(label, variante or None)

    def __str__(self) -> str:
        return f"{self.label}@{self.variante}" if self.variante else self.label

    def acepta(self, registro: dict[str, Any]) -> bool:
        return (
            registro.get("label") == self.label and registro.get("input_variant") == self.variante
        )


# --- Corridas y casos ---------------------------------------------------------------------------


@dataclass
class Corrida:
    """Una corrida con sus intentos: un `truncado` repetido con mas tokens es UNA corrida, no dos."""

    intentos: list[dict[str, Any]]

    @property
    def final(self) -> dict[str, Any]:
        return self.intentos[-1]

    @property
    def outcome(self) -> str:
        return str(self.final.get("outcome"))

    # Todo se juzga por el ULTIMO intento: desde la tarea 19 el runner repite la anulada, y un
    # intento anulado que se repitio bien no puede seguir descartando ni bloqueando la corrida.
    @property
    def descartada(self) -> bool:
        return bool(self.final.get("descartada"))

    @property
    def motivo_descarte(self) -> str | None:
        return self.final.get("descartada_motivo") if self.descartada else None

    @property
    def fria(self) -> bool:
        return self.final.get("thermal_state") == "cold"

    @property
    def calidad(self) -> float | None:
        if self.descartada:
            return None
        score = self.final.get("score") or {}
        # Truncada otra vez tras doblar los tokens: puntua 0 (§4.7 punto 3), no «sin puntuacion».
        if self.outcome == "ok" or (
            self.outcome == "truncado" and score.get("zero_by") == "truncado_repetido"
        ):
            return score.get("quality")
        return None

    @property
    def latencia(self) -> float | None:
        """Solo de corridas validas y calientes: la fria lleva dentro la carga del modelo."""
        if self.descartada or self.outcome != "ok" or self.fria:
            return None
        return self.final.get("latency_ms")


def _mediana_y_dispersion(valores: list[float]) -> tuple[float | None, float | None]:
    if not valores:
        return None, None
    return statistics.median(valores), max(valores) - min(valores)


@dataclass
class Caso:
    id: str
    role: str
    kind: str
    corridas: list[Corrida] = field(default_factory=list)

    @property
    def calidades(self) -> list[float]:
        return [c.calidad for c in self.corridas if c.calidad is not None]

    @property
    def mediana(self) -> float | None:
        return _mediana_y_dispersion(self.calidades)[0]

    @property
    def dispersion(self) -> float | None:
        return _mediana_y_dispersion(self.calidades)[1]

    @property
    def latencias(self) -> list[float]:
        return [c.latencia for c in self.corridas if c.latencia is not None]

    @property
    def latencia_mediana(self) -> float | None:
        return _mediana_y_dispersion(self.latencias)[0]

    @property
    def latencia_dispersion(self) -> float | None:
        return _mediana_y_dispersion(self.latencias)[1]

    @property
    def aceptada(self) -> bool | None:
        """Si el modelo acepto la entrada en todas sus corridas validas; None sin corridas validas."""
        validas = [c for c in self.corridas if not c.descartada]
        if not validas:
            return None
        return all(c.outcome in _ACEPTADAS for c in validas)


@dataclass
class Config:
    selector: Selector
    registros: list[dict[str, Any]]
    casos: dict[str, Caso]


def cargar_config(registros: list[dict[str, Any]], selector: Selector) -> Config:
    propios = [r for r in registros if selector.acepta(r)]
    if not propios:
        raise ValueError(f"no hay corridas de {selector}")
    casos: dict[str, Caso] = {}
    # Estable: el orden del fichero desempata dos registros con el mismo ts.
    for registro in sorted(propios, key=lambda r: str(r.get("ts", ""))):
        caso = casos.setdefault(
            registro["case"], Caso(registro["case"], registro["role"], registro["kind"])
        )
        if int(registro.get("attempt", 1)) == 1:
            caso.corridas.append(Corrida([registro]))
        elif caso.corridas:
            caso.corridas[-1].intentos.append(registro)
        else:
            raise ValueError(f"{selector}: {registro['case']} tiene un intento >1 sin el primero")
    return Config(selector, propios, casos)


def _casos_del_rol(corpus: dict[str, dict[str, Any]], rol: str, kind: str) -> list[str]:
    # Un caso con `automatic_scoring: false` no entra en ninguna cuenta de la regla: lo juzga solo la
    # revision a ciegas (§4.8). Es `commit-diff-19k` desde el segundo piloto de CP-3.
    return [
        cid
        for cid, c in corpus.items()
        if c["role"] == rol and c["kind"] == kind and c.get("automatic_scoring") is not False
    ]


def _solo_revision(corpus: dict[str, dict[str, Any]], rol: str) -> list[str]:
    return [
        cid
        for cid, c in corpus.items()
        if c["role"] == rol and c["kind"] == "calidad" and c.get("automatic_scoring") is False
    ]


def _caso(config: Config, case_id: str, corpus: dict[str, dict[str, Any]]) -> Caso:
    """Un caso que no corrio existe igual, vacio: asi cuenta como «sin puntuacion valida»."""
    meta = corpus[case_id]
    return config.casos.get(case_id) or Caso(case_id, meta["role"], meta["kind"])


def banda_del_caso(
    configs: list[Config], case_id: str, corpus: dict[str, dict[str, Any]]
) -> float | None:
    """La mayor dispersion de ESE caso entre las configuraciones que se comparan.

    Tercer piloto de CP-3 (decision del usuario): con la temperatura de produccion, la banda del ROL
    —la mayor dispersion de todos sus casos— la fijaba el caso mas inestable y ningun otro podia
    separar. `boilerplate-156` daba 0/0/0 contra 1/1/0,8 y quedaba dentro de una banda de 1,0 que
    ponia `explicar-metrics-15k`. Cada caso se mide contra su propio ruido.
    """
    dispersiones = [
        d for cfg in configs if (d := _caso(cfg, case_id, corpus).dispersion) is not None
    ]
    return max(dispersiones) if dispersiones else None


def banda_del_agregado(
    configs: list[Config], casos: list[str], corpus: dict[str, dict[str, Any]]
) -> float | None:
    """La media de las bandas de los casos que forman el agregado.

    El agregado es la media de sus medianas, y su ruido es del orden del ruido medio de sus casos.
    La media y no la maxima, para que un caso inestable no vete al resto; y no la media dividida
    por la raiz de N, que supondria independencia entre casos corridos por el mismo modelo.
    CP-3 y §7 usan la misma: si no, el control validaria una magnitud y la regla decidiria con otra.
    """
    return _media([banda_del_caso(configs, cid, corpus) for cid in casos]) if casos else None


def _media(valores: list[float | None]) -> float | None:
    presentes = [v for v in valores if v is not None]
    if not presentes or len(presentes) != len(valores):
        return None
    return statistics.fmean(presentes)


def puede_disparar(banda: float | None, calidad_vigente: float | None) -> bool | None:
    """Si un candidato PERFECTO (calidad 1,0) superaria la banda. Si no, la regla no puede elegir.

    Con la granularidad real —un caso de un solo termino da 0 o 1— basta que ese caso cambie una
    vez en tres corridas para que la banda valga 1,0 y ningun candidato pueda ganar jamas. Eso da
    «no se cambia», la salida por defecto, y seria indistinguible del hallazgo legitimo.
    """
    if banda is None or calidad_vigente is None:
        return None
    return 1.0 - calidad_vigente > banda + TOLERANCIA


# --- Comparacion por pares (P-15) -------------------------------------------------------------


def _cola_binomial(exitos: int, n: int) -> float:
    """P(X >= exitos) con X ~ Binomial(n, 1/2): la probabilidad de tantas elecciones por azar."""
    return sum(math.comb(n, i) for i in range(exitos, n + 1)) / 2**n


def veredicto_pares(candidato: int, vigente: int, empates: int = 0) -> str | None:
    """Prueba de signos sobre los pares con eleccion; los empates no cuentan.

    «mejor» si el candidato fue elegido tantas veces que por azar pasaria con probabilidad
    <= ALFA_PARES; «peor» si eso le pasa al vigente; si no, «empate». Con 20 pares sin empates hace
    falta 15 a 5. Sin ningun par juzgado no hay veredicto.
    """
    n = candidato + vigente
    if n == 0:
        return "empate" if empates else None
    if _cola_binomial(candidato, n) <= ALFA_PARES:
        return "mejor"
    if _cola_binomial(vigente, n) <= ALFA_PARES:
        return "peor"
    return "empate"


def pares_del_rol(
    pares: dict[str, Any] | None,
    corpus: dict[str, dict[str, Any]],
    rol: str,
    vigente: str,
    candidato: str,
) -> dict[str, Any] | None:
    """Suma las elecciones de `hoja_pares.py destapar --json` en los casos por pares del rol."""
    if pares is None:
        return None
    casos = [cid for cid in _solo_revision(corpus, rol) if cid in pares]
    if not casos:
        return None
    cuenta = {
        quien: sum(int(pares[cid]["humano"].get(etiqueta, 0)) for cid in casos)
        for quien, etiqueta in (
            ("candidato", candidato),
            ("vigente", vigente),
            ("empates", "empate"),
        )
    }
    return {
        "casos": casos,
        **cuenta,
        "veredicto": veredicto_pares(cuenta["candidato"], cuenta["vigente"], cuenta["empates"]),
    }


# --- CP-3 ---------------------------------------------------------------------------------------


def analizar_cp3(
    registros: list[dict[str, Any]],
    corpus: dict[str, dict[str, Any]],
    pequeno: Selector,
    grande: Selector,
) -> dict[str, Any]:
    cfg_p, cfg_g = cargar_config(registros, pequeno), cargar_config(registros, grande)
    control_de_entrada = pequeno.label == grande.label and pequeno.variante != grande.variante
    roles = sorted({c.role for cfg in (cfg_p, cfg_g) for c in cfg.casos.values()})
    salida: dict[str, Any] = {
        "pequeno": str(pequeno),
        "grande": str(grande),
        "control_de_entrada": control_de_entrada,
        "roles": {},
    }
    for rol in roles:
        ids = _casos_del_rol(corpus, rol, "calidad")
        casos: dict[str, Any] = {}
        for cid in ids:
            m_p, m_g = _caso(cfg_p, cid, corpus).mediana, _caso(cfg_g, cid, corpus).mediana
            banda_caso = banda_del_caso([cfg_p, cfg_g], cid, corpus)
            if m_p is None or m_g is None:
                casos[cid] = {
                    "pequeno": m_p,
                    "grande": m_g,
                    "banda": banda_caso,
                    "separa": False,
                    "motivo": "sin puntuacion",
                }
                continue
            diferencia = m_g - m_p
            # En el control de entrada la direccion importa: la imagen correcta tiene que ganar.
            separa = (diferencia if control_de_entrada else abs(diferencia)) > (
                banda_caso or 0.0
            ) + TOLERANCIA
            en_techo = m_p == 1.0 and m_g == 1.0
            motivo = None if separa else ("techo" if en_techo else "no separa")
            casos[cid] = {
                "pequeno": m_p,
                "grande": m_g,
                "diferencia": round(diferencia, 4),
                "banda": banda_caso,
                "separa": separa,
                "direccion": "grande" if diferencia > 0 else "pequeno" if diferencia < 0 else None,
                "motivo": motivo,
            }
        admitidos = [cid for cid, c in casos.items() if c["separa"]]
        # §7 punto 4: si TODOS los casos del rol estan en techo, los dos modelos empatan en 1,0 y el
        # rol se decide por velocidad; no es un corpus que no discrimina. En el control de entrada
        # no aplica: que la imagen equivocada tambien de 1,0 es justo que el caso no reacciona.
        empate_en_techo = (
            not control_de_entrada
            and bool(ids)
            and not admitidos
            and all(c["motivo"] == "techo" for c in casos.values())
        )
        if control_de_entrada:
            pasa = bool(ids) and len(admitidos) == len(ids)
        else:
            pasa = len(ids) <= 1 or bool(admitidos) or empate_en_techo
        banda = banda_del_agregado([cfg_p, cfg_g], admitidos, corpus)
        agregado_p = _media([casos[c]["pequeno"] for c in admitidos]) if admitidos else None
        agregado_g = _media([casos[c]["grande"] for c in admitidos]) if admitidos else None
        agregado_separa = (
            abs(agregado_g - agregado_p) > (banda or 0.0) + TOLERANCIA
            if agregado_p is not None and agregado_g is not None
            else False
        )
        peor = (
            min(agregado_p, agregado_g)
            if agregado_p is not None and agregado_g is not None
            else None
        )
        salida["roles"][rol] = {
            "banda": banda,
            "casos": casos,
            "casos_admitidos": admitidos,
            "pasa": pasa,
            "empate_en_techo": empate_en_techo,
            "agregado": {"pequeno": agregado_p, "grande": agregado_g, "separa": agregado_separa},
            "puede_disparar": puede_disparar(banda, peor),
            "sin_agregado": rol in ROLES_SIN_AGREGADO,
            "solo_revision": _solo_revision(corpus, rol),
        }
    return salida


# --- §6: tanda no concluyente -------------------------------------------------------------------


def validar_tanda(
    vigente: Config,
    candidato: Config,
    rol: str,
    corpus: dict[str, dict[str, Any]],
    umbral_shared_bytes: int,
) -> list[str]:
    """Motivos por los que el rol NO se puede interpretar. Vacio = concluyente."""
    motivos: list[str] = []
    configs = (vigente, candidato)
    corridas = [
        c
        for cfg in configs
        for caso in cfg.casos.values()
        if caso.role == rol
        for c in caso.corridas
    ]
    descartadas = [c for c in corridas if c.descartada]
    if corridas and len(descartadas) * 3 > len(corridas):
        motivos.append(
            f"{len(descartadas)} de {len(corridas)} corridas descartadas (mas de una de cada tres)"
        )
    for cfg in configs:
        for cid in _casos_del_rol(corpus, rol, "calidad"):
            if not _caso(cfg, cid, corpus).calidades:
                motivos.append(f"{cfg.selector}: {cid} sin ninguna puntuacion valida")
    registros = [r for cfg in configs for r in cfg.registros if r.get("role") == rol]
    # Por tipo de caso (§3.5, decision del usuario 2026-09-14): la calidad corre con el n_ctx del caso
    # mayor y los sondeos de techo en otra config con mas contexto, o medirian la ventana y no el
    # modelo. Lo que no vale es que vigente y candidato difieran DENTRO de un mismo tipo.
    for kind in sorted({r.get("kind") for r in registros}, key=str):
        del_tipo = [r for r in registros if r.get("kind") == kind]
        for clave, nombre in (("context_size", "n_ctx"), ("load_mode", "--load-mode")):
            valores = {(r.get("variant") or {}).get(clave) for r in del_tipo}
            if None in valores:
                # Sin declararlo no se puede comprobar, y un control que no puede fallar no es control.
                motivos.append(f"{nombre} sin declarar en alguna corrida de {kind}")
            elif len(valores) > 1:
                motivos.append(
                    f"{nombre} distinto entre corridas de {kind}: {sorted(map(str, valores))}"
                )
    for cfg in configs:
        propios = [r for r in cfg.registros if r.get("role") == rol]
        primeras = [
            (r.get("resources") or {}).get("vram_shared_bytes_first")
            for r in propios
            if (r.get("resources") or {}).get("vram_shared_bytes_first") is not None
        ]
        if not primeras:
            continue
        base = min(primeras)
        for r in propios:
            pico = (r.get("resources") or {}).get("vram_shared_bytes_peak")
            if pico is not None and pico - base > umbral_shared_bytes:
                # §3.2: no se cae la corrida, se cae CP-1 y todo el tramo desde el ultimo CP-1 verde.
                motivos.append(
                    f"{cfg.selector}: Shared Usage crecio {pico - base} bytes en {r['case']} "
                    f"run={r.get('run')}: CP-1 dejo de valer, repetir el tramo"
                )
                break
    return motivos


# --- §7: regla de decision ----------------------------------------------------------------------


def _latencia_del_rol(
    configs: list[Config], ids: list[str], corpus
) -> tuple[list[float | None], float | None]:
    medias = [_media([_caso(cfg, cid, corpus).latencia_mediana for cid in ids]) for cfg in configs]
    dispersiones = [
        d
        for cfg in configs
        for cid in ids
        if (d := _caso(cfg, cid, corpus).latencia_dispersion) is not None
    ]
    return medias, (max(dispersiones) if dispersiones else None)


def techo_aceptado(config: Config, rol: str, corpus: dict[str, dict[str, Any]]) -> int | None:
    """Mayor entrada aceptada en un caso del rol. None si falta un sondeo de techo del corpus."""
    for cid in _casos_del_rol(corpus, rol, "techo"):
        if _caso(config, cid, corpus).aceptada is None:
            return None
    aceptados = [
        int(caso.corridas[0].final.get("input_bytes") or 0)
        for caso in config.casos.values()
        if caso.role == rol and caso.corridas and caso.aceptada
    ]
    return max(aceptados, default=0)


def decidir_rol(
    rol: str,
    vigente: Config,
    candidato: Config,
    corpus: dict[str, dict[str, Any]],
    cp3: dict[str, Any] | None,
    umbral_shared_bytes: int = 0,
    pares: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ids = _casos_del_rol(corpus, rol, "calidad")
    resultado: dict[str, Any] = {
        "rol": rol,
        "vigente": str(vigente.selector),
        "candidato": str(candidato.selector),
        "motivos": [],
    }
    no_concluyente = validar_tanda(vigente, candidato, rol, corpus, umbral_shared_bytes)
    if no_concluyente:
        # §6: una tanda no concluyente no se interpreta; se repite el rol.
        return {**resultado, "veredicto": "no_concluyente", "motivos": no_concluyente}
    if rol in ROLES_SIN_AGREGADO:
        return {
            **resultado,
            "veredicto": "sin_agregado",
            "motivos": [
                f"{rol} no presenta agregado (§7): decide la tabla caso a caso y la revision"
            ],
        }
    if cp3 is None:
        raise ValueError(f"{rol}: falta el resultado de CP-3; sin el no hay casos admitidos")

    admitidos = [cid for cid in cp3.get("casos_admitidos", []) if cid in ids]
    descartes = {
        cid: (cp3.get("casos", {}).get(cid) or {}).get("motivo") or "sin dato de CP-3"
        for cid in ids
        if cid not in admitidos
    }
    resultado["casos_admitidos"] = admitidos
    resultado["casos_descartados"] = descartes
    # Si CP-3 dejo TODOS los casos fuera por techo, los modelos del piloto empataban en 1,0: no hay
    # nada que separe por calidad, y eso no es un rol indecidible sino un empate. Decision del
    # usuario (tarea 19): «al mismo resultado, nos quedamos con el mas rapido». La calidad se
    # compara igual con todos los casos de ESTA tanda —un candidato que ya no da 1,0 pierde por
    # calidad—, y dentro de la banda deciden los desempates de siempre: techo, luego velocidad.
    todos_en_techo = bool(ids) and not admitidos and all(m == "techo" for m in descartes.values())
    resultado["todos_en_techo"] = todos_en_techo
    casos_calidad = admitidos or (ids if todos_en_techo else [])
    # P-15: los casos de texto abierto los decide la comparacion por pares a ciegas, no la formula.
    casos_pares = _solo_revision(corpus, rol)
    pares_rol = pares_del_rol(pares, corpus, rol, str(vigente.selector), str(candidato.selector))
    resultado["pares"] = pares_rol
    if not casos_calidad and (pares_rol is None or pares_rol["veredicto"] is None):
        return {
            **resultado,
            "veredicto": "indecidible",
            "motivos": ["ningun caso de CP-3 separa: el rol es indecidible con este corpus"],
        }

    # Latencia de TODOS los casos de calidad: los de pares tambien corren y tardan.
    # Condicion 3 sobre los casos con latencia medida en LOS DOS (decision del usuario, tarea 20): el
    # vigente de long se corto en todas las corridas de lint-9k y la media del rol salia vacia, asi que
    # su fallo vetaba al candidato. Que un modelo no termine un caso ya lo castigan calidad y pares.
    casos_lat = ids + casos_pares
    con_latencia = [
        cid
        for cid in casos_lat
        if all(_caso(cfg, cid, corpus).latencia_mediana is not None for cfg in (vigente, candidato))
    ]
    (lat_v, lat_c), banda_lat = _latencia_del_rol([vigente, candidato], con_latencia, corpus)
    hay_techo = bool(_casos_del_rol(corpus, rol, "techo"))
    techo_v, techo_c = techo_aceptado(vigente, rol, corpus), techo_aceptado(candidato, rol, corpus)
    resultado.update(
        {
            "debilmente_decidible": len(casos_calidad) < MIN_CASOS_DECIDIBLE and pares_rol is None,
            "latencia_ms": {
                "vigente": lat_v,
                "candidato": lat_c,
                "banda": banda_lat,
                "fuera": [cid for cid in casos_lat if cid not in con_latencia],
            },
            "techo_bytes": {"vigente": techo_v, "candidato": techo_c} if hay_techo else None,
        }
    )
    automatico: str | None = None
    if casos_calidad:
        banda = banda_del_agregado([vigente, candidato], casos_calidad, corpus) or 0.0
        q_v = _media([_caso(vigente, cid, corpus).mediana for cid in casos_calidad])
        q_c = _media([_caso(candidato, cid, corpus).mediana for cid in casos_calidad])
        assert q_v is not None and q_c is not None  # §6 ya exige puntuacion valida en cada caso
        diferencia = q_c - q_v
        resultado.update(
            {
                "calidad": {"vigente": q_v, "candidato": q_c, "diferencia": round(diferencia, 4)},
                "banda": banda,
                "puede_disparar": puede_disparar(banda, q_v),
            }
        )
        if diferencia > banda + TOLERANCIA:
            automatico = "mejor"
        elif diferencia < -banda - TOLERANCIA:
            automatico = "peor"
        else:
            automatico = "empate"

    # Quien gana por calidad: si alguna fuente dice «peor», pierde; si ninguna lo dice y alguna dice
    # «mejor», gana. Si no, la precedencia de desempates de siempre.
    fuentes = [f for f in (automatico, pares_rol and pares_rol["veredicto"]) if f]
    gana: bool
    if "peor" in fuentes:
        gana, criterio = False, "calidad"
    elif "mejor" in fuentes:
        gana, criterio = True, "calidad"
    elif hay_techo and (techo_v is None or techo_c is None):
        gana, criterio = False, "techo sin medir"
    elif hay_techo and techo_c != techo_v:
        gana, criterio = bool(techo_c > techo_v), "techo"  # type: ignore[operator]
    elif lat_v is not None and lat_c is not None and abs(lat_c - lat_v) > (banda_lat or 0.0):
        gana, criterio = lat_c < lat_v, "velocidad"
    else:
        gana, criterio = False, "empate"
    resultado["criterio"] = criterio

    bloqueos: list[str] = []
    if gana:
        # Condicion 2: ninguna corrida anulada, con error (OOM incluido) ni rechazo en calidad.
        for caso in candidato.casos.values():
            if caso.role != rol:
                continue
            for corrida in caso.corridas:
                if corrida.descartada:
                    bloqueos.append(f"{caso.id}: corrida anulada ({corrida.motivo_descarte})")
                elif corrida.outcome == "error":
                    bloqueos.append(f"{caso.id}: error ({corrida.final.get('error')})")
                elif corrida.outcome == "rechazo_por_contexto" and caso.kind == "calidad":
                    bloqueos.append(f"{caso.id}: rechazo_por_contexto en un caso de calidad")
        # Condicion 3: la latencia no empeora mas de un 50 %.
        if lat_v is None or lat_c is None:
            bloqueos.append("latencia sin medir")
        elif lat_c > LATENCIA_MAXIMA * lat_v:
            bloqueos.append(
                f"latencia {lat_c / lat_v:.2f}x la del vigente (maximo {LATENCIA_MAXIMA}x)"
            )
        # Un rol con casos por pares no se cambia sin su comparacion: la formula no los ve.
        if casos_pares and pares_rol is None:
            bloqueos.append(
                "falta la comparacion por pares de " + ", ".join(casos_pares) + " (P-15)"
            )
        # El sondeo de techo entra en la decision, no solo en la hoja.
        if hay_techo and (techo_v is None or techo_c is None):
            bloqueos.append("falta el sondeo de techo")
        elif hay_techo and techo_c < techo_v:  # type: ignore[operator]
            bloqueos.append("el candidato no aguanta el sondeo de techo que el vigente si")
    resultado["motivos"] = bloqueos
    if gana and not bloqueos:
        resultado["veredicto"] = "sustituye"
    else:
        resultado["veredicto"] = "no_sustituye"
        if not gana:
            resultado["motivos"] = ["nadie mejora al vigente: el rol no se cambia (REQ-F2-6)"]
    return resultado


# --- Informe ------------------------------------------------------------------------------------


def _fmt(valor: Any, decimales: int = 3) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, float):
        return f"{valor:.{decimales}f}"
    return str(valor)


def _pico(config: Config, rol: str, ruta: tuple[str, ...]) -> Any:
    valores = []
    for r in config.registros:
        # Solo calidad: el sondeo de techo corre con mas contexto y su KV inflaria la memoria de la
        # config que se decide (§3.5).
        if r.get("role") != rol or r.get("kind") != "calidad":
            continue
        valor: Any = r
        for clave in ruta:
            valor = (valor or {}).get(clave)
        if valor is not None:
            valores.append(valor)
    return max(valores, default=None)


# Presupuesto de uso diario (protocolo §1.1, P-14): 16 GB de VRAM y 32 GB de RAM menos una reserva
# fija de 2 y 8 GB para el resto de la PC. Solo informativo: la regla de §7 no descarta por esto.
USO_DIARIO_VRAM_BYTES = 14 * 1024**3
USO_DIARIO_RAM_BYTES = 24 * 1024**3


def _cabe_uso_diario(vram_bytes: float | None, host_bytes: float | None) -> str:
    if vram_bytes is None or host_bytes is None:
        return "—"
    return (
        "si" if vram_bytes <= USO_DIARIO_VRAM_BYTES and host_bytes <= USO_DIARIO_RAM_BYTES else "no"
    )


def informe_decision(
    decisiones: list[dict[str, Any]], configs: dict[str, Config], corpus: dict[str, dict[str, Any]]
) -> str:
    lineas = ["# Regla de decision de F2 (§6 y §7)", ""]
    lineas += [
        "## Tabla 1: por rol",
        "",
        (
            "| Rol | Vigente | Candidato | Calidad v / c | Banda | Latencia ms v / c | "
            "RAM host pico c | RAM privada pico c | Working set pico c | VRAM dedicada pico c | "
            "Shared pico c | Cabe uso diario c | Descartadas | Rechazos | Veredicto | Criterio |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for d in decisiones:
        cand = configs[d["candidato"]]
        corridas = [
            c for caso in cand.casos.values() if caso.role == d["rol"] for c in caso.corridas
        ]
        calidad = d.get("calidad") or {}
        latencia = d.get("latencia_ms") or {}
        host = _pico(cand, d["rol"], ("resources", "host_private_bytes_peak"))
        vram = _pico(cand, d["rol"], ("resources", "vram_dedicated_bytes_peak"))
        lineas.append(
            f"| {d['rol']} | {d['vigente']} | {d['candidato']} | "
            f"{_fmt(calidad.get('vigente'))} / {_fmt(calidad.get('candidato'))} | {_fmt(d.get('banda'))} | "
            f"{_fmt(latencia.get('vigente'), 0)} / {_fmt(latencia.get('candidato'), 0)} | "
            f"{_fmt(host)} | "
            f"{_fmt(_pico(cand, d['rol'], ('resources', 'private_bytes_peak')))} | "
            f"{_fmt(_pico(cand, d['rol'], ('resources', 'working_set_bytes_peak')))} | "
            f"{_fmt(vram)} | "
            f"{_fmt(_pico(cand, d['rol'], ('resources', 'vram_shared_bytes_peak')))} | "
            f"{_cabe_uso_diario(vram, host)} | "
            f"{sum(c.descartada for c in corridas)} | "
            f"{sum(c.outcome == 'rechazo_por_contexto' for c in corridas)} | "
            f"**{d['veredicto']}** | {d.get('criterio', '—')} |"
        )
    lineas.append("")
    for d in decisiones:
        lineas.append(f"### {d['rol']}: {d['veredicto']}")
        lineas.append("")
        for motivo in d.get("motivos") or []:
            lineas.append(f"- {motivo}")
        if "casos_admitidos" in d:
            lineas.append(
                f"- casos en el agregado: {len(d['casos_admitidos'])} ({', '.join(d['casos_admitidos']) or 'ninguno'})"
            )
            for cid, motivo in (d.get("casos_descartados") or {}).items():
                lineas.append(f"- fuera del agregado: {cid} ({motivo})")
        if pares_rol := d.get("pares"):
            lineas.append(
                f"- comparacion por pares ({', '.join(pares_rol['casos'])}): candidato "
                f"{pares_rol['candidato']}, vigente {pares_rol['vigente']}, empates "
                f"{pares_rol['empates']} -> **{pares_rol['veredicto']}**"
            )
        if d.get("debilmente_decidible"):
            lineas.append("- **debilmente decidible**: menos de dos casos en el agregado")
        if d.get("puede_disparar") is False:
            lineas.append(
                "- **la regla no puede disparar**: ni un candidato con calidad 1,0 superaria la banda; "
                "«no se cambia» aqui no distingue nada"
            )
        lineas.append("")

    lineas += [
        "## Tabla 2: caso a caso",
        "",
        "| Rol | Caso | Modelo | Corridas (calidad, outcome) | Mediana | Dispersion | Latencia mediana |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for d in decisiones:
        for nombre in (d["vigente"], d["candidato"]):
            cfg = configs[nombre]
            for cid, meta in corpus.items():
                if meta["role"] != d["rol"]:
                    continue
                caso = _caso(cfg, cid, corpus)
                corridas = (
                    ", ".join(
                        f"{_fmt(c.calidad, 2)} {c.outcome}"
                        + (" descartada" if c.descartada else "")
                        + (" fria" if c.fria else "")
                        for c in caso.corridas
                    )
                    or "sin corridas"
                )
                lineas.append(
                    f"| {d['rol']} | {cid} | {nombre} | {corridas} | {_fmt(caso.mediana)} | "
                    f"{_fmt(caso.dispersion)} | {_fmt(caso.latencia_mediana, 0)} |"
                )
    lineas.append("")

    lineas += [
        "## Tabla 3: entorno",
        "",
        "| Modelo | n_ctx | --load-mode | -ncmoe | llama-server | llama-swap | Anuladas (motivo) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for nombre, cfg in configs.items():
        variantes = {json.dumps(r.get("variant") or {}, sort_keys=True) for r in cfg.registros}
        for variante in sorted(variantes):
            v = json.loads(variante)
            anuladas = sorted(
                {
                    f"{r['case']} run={r.get('run')} ({r.get('descartada_motivo')})"
                    for r in cfg.registros
                    if r.get("descartada")
                }
            )
            lineas.append(
                f"| {nombre} | {_fmt(v.get('context_size'))} | {_fmt(v.get('load_mode'))} | {_fmt(v.get('n_cpu_moe'))} | "
                f"{_fmt(v.get('llama_server_version'))} | {_fmt(v.get('llama_swap_version'))} | {'; '.join(anuladas) or '—'} |"
            )
    concluyente = all(d["veredicto"] != "no_concluyente" for d in decisiones)
    lineas += ["", f"Tanda concluyente segun §6: **{'si' if concluyente else 'no'}**.", ""]

    lineas += [
        "## Tabla 4: techo",
        "",
        "| Rol | Modelo | Mayor entrada aceptada (bytes) |",
        "| --- | --- | --- |",
    ]
    for d in decisiones:
        for nombre in (d["vigente"], d["candidato"]):
            lineas.append(
                f"| {d['rol']} | {nombre} | {_fmt(techo_aceptado(configs[nombre], d['rol'], corpus))} |"
            )
    lineas.append("")
    return "\n".join(lineas)


def informe_cp3(resultado: dict[str, Any]) -> str:
    lineas = [f"# CP-3: {resultado['pequeno']} contra {resultado['grande']}", ""]
    if resultado["control_de_entrada"]:
        lineas += [
            "Control de entrada: pasa si todos los casos bajan con la entrada de control.",
            "",
        ]
    for rol, datos in resultado["roles"].items():
        agregado = datos["agregado"]
        estado = "pasa" if datos["pasa"] else "NO pasa"
        if datos.get("empate_en_techo"):
            estado = "pasa por empate en techo (decide la velocidad, §7 punto 4)"
        lineas += [
            f"## {rol}: {estado}",
            "",
            f"- banda del agregado (media de las bandas por caso): {_fmt(datos['banda'])}",
            f"- casos en el agregado: {len(datos['casos_admitidos'])} de {len(datos['casos'])}",
            (
                f"- el agregado separa: {'si' if agregado['separa'] else 'no'} "
                f"({_fmt(agregado['pequeno'])} contra {_fmt(agregado['grande'])})"
            ),
        ]
        if datos["puede_disparar"] is False:
            lineas.append("- **la regla de §7 no puede disparar con esta banda**")
        if datos.get("solo_revision"):
            lineas.append(
                "- sin puntuacion automatica, lo decide la comparacion por pares a ciegas: "
                + ", ".join(datos["solo_revision"])
            )
        lineas += [
            "",
            "| Caso | Pequeno | Grande | Diferencia | Banda | Separa | Motivo |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for cid, caso in datos["casos"].items():
            lineas.append(
                f"| {cid} | {_fmt(caso['pequeno'])} | {_fmt(caso['grande'])} | "
                f"{_fmt(caso.get('diferencia'))} | {_fmt(caso.get('banda'))} | "
                f"{'si' if caso['separa'] else 'no'} | {caso['motivo'] or '—'} |"
            )
        lineas.append("")
    return "\n".join(lineas)


# --- Afinidad: puntuadores, criterios y veredicto (REQ-040 a REQ-043) ----------------------------
#
# Todo el criterio de la evaluacion que aprueba las celdas esta escrito aqui, en codigo, y se prueba
# con datos sinteticos antes de que exista un solo resultado real. Este modulo NO importa el paquete
# `local_delegate`: la tarea que recoge el juicio del usuario corre mientras otras tareas editan
# `server.py`, y importar el paquete lo cargaria a medio escribir. La huella de cada celda se COPIA
# de `huellas.json` (la calcula la tanda).

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
    actual: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if fence is not None:
            closing = line.strip()
            if closing and set(closing) == {fence[0]} and len(closing) >= len(fence):
                blocks.append("\n".join(actual))
                fence, actual = None, []
            else:
                actual.append(line)
            continue
        if m := _FENCE_OPEN.match(line):
            fence = m.group(1)
            continue
        titles += bool(_TITLE.match(line))
        item_lists += bool(_ITEM.match(line))
    if fence is not None:  # valla sin cerrar: cuenta como bloque (el modelo se quedo a medias)
        blocks.append("\n".join(actual))
    return {"titulos": titles, "listas": item_lists, "bloques": len(blocks), "codigo": blocks}


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
    """`{"calidad": 0..1, "formato": bool}` de una respuesta, con el puntuador DEL caso.

    El puntuador sale de `cases.json` (`puntuador`), con lo esperado calculado por el constructor del
    corpus a partir de la fuente, no de lo que respondio un modelo. `formato` es lo que la tool
    prometio (una etiqueta, un objeto JSON con esas claves, la estructura Markdown, un limite de
    palabras, un formato exacto); `calidad` es si ademas es correcto.
    """
    spec = case.get("puntuador") or {}
    kind = spec.get("tipo")
    if kind == "classify":
        response = text.strip()
        return {
            "calidad": 1.0 if response in spec["aceptables"] else 0.0,
            "formato": response in spec["etiquetas"],
        }
    if kind == "extract":
        try:
            obj = json.loads(_strip_fences(text))
        except ValueError:
            obj = None
        if not isinstance(obj, dict) or set(obj) != set(spec["claves"]):
            return {"calidad": 0.0, "formato": False}
        good = sum(_json_equal(obj[c], spec["esperado"][c]) for c in spec["claves"])
        return {"calidad": good / len(spec["claves"]), "formato": True}
    if kind == "translate":
        est = markdown_structure(text)
        structure = [
            est["titulos"] == spec["titulos"],
            est["listas"] == spec["listas"],
            est["bloques"] == spec["bloques"],
        ]
        inside = set(est["codigo"])
        tests_run = structure + [block in inside for block in spec["codigo"]]
        return {"calidad": sum(tests_run) / len(tests_run), "formato": all(structure)}
    if kind == "lint":
        bad_ones = rules_with_wrong_count(text, spec["conteos"])
        words = len(re.findall(r"\w+", text))
        return {
            "calidad": (len(spec["conteos"]) - len(bad_ones)) / len(spec["conteos"]),
            "formato": bool(text.strip()) and words <= spec["max_words"],
        }
    if kind == "delegate":
        response = text.strip()
        return {
            "calidad": 1.0 if response == spec["esperado"] else 0.0,
            "formato": re.fullmatch(spec["formato"], response) is not None,
        }
    if kind == "f2":
        # Los cinco casos de regresion de F2 conservan su puntuacion de entonces, la del runner.
        scoring = (record or {}).get("score") or {}
        quality = scoring.get("quality")
        fmt = scoring.get("format_ok")
        return {
            "calidad": float(quality) if quality is not None else 0.0,
            "formato": True if fmt is None else bool(fmt),
        }
    raise ValueError(f"{case.get('id')}: puntuador {kind!r} desconocido")


# --- Reglas, huellas y resultados -----------------------------------------------------------------

POSSIBLE_OPTIONAL_QUESTIONS = frozenset({"principal", "especifico"})


def read_affinity_rules(path: Path) -> dict[str, Any]:
    """`reglas.json`, validado. Una regla invalida lo rechaza entero: no hay valores por defecto."""
    rules = json.loads(path.read_text(encoding="utf-8"))
    maximum = rules.get("max_inventa_26b")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
        raise SystemExit("reglas.json: max_inventa_26b tiene que ser un entero >= 0")
    optional_ones = rules.get("preguntas_opcionales")
    if not isinstance(optional_ones, list) or not set(optional_ones) <= POSSIBLE_OPTIONAL_QUESTIONS:
        raise SystemExit(
            "reglas.json: preguntas_opcionales solo admite 'principal' y 'especifico'; "
            "'inventa' y la preferencia no pueden ser opcionales"
        )
    if not isinstance(rules.get("formato"), dict):
        raise SystemExit("reglas.json: falta la regla de formato")
    if not isinstance(rules.get("parada_anticipada"), bool):
        raise SystemExit("reglas.json: parada_anticipada tiene que ser true o false")
    return rules


def message_format(message: str, rule: dict[str, Any]) -> bool:
    """«Formato» de un mensaje de commit, calculado por el programa con la regla de `reglas.json`.

    Primera linea de 72 caracteres como maximo, prefijo convencional y sin adornos: ni vallas de
    codigo, ni comillas que envuelvan el mensaje, ni encabezados Markdown, ni frases de
    presentacion. Se publica; no decide ninguna celda.
    """
    text = message.strip("\n")
    if not text.strip():
        return False
    first_one = text.split("\n", 1)[0]
    if len(first_one) > int(rule["primera_linea_max"]):
        return False
    if re.match(rule["prefijo"], first_one) is None:
        return False
    decorations = rule["sin_adornos"]
    lines = text.split("\n")
    if decorations.get("vallas_de_codigo") and any(
        line.strip().startswith(("```", "~~~")) for line in lines
    ):
        return False
    bare = text.strip()
    if (
        decorations.get("comillas_envolventes")
        and len(bare) > 1
        and bare[0] in "\"'`“«‘"
        and bare[-1] in "\"'`”»’"
    ):
        return False
    if decorations.get("encabezados_markdown") and any(re.match(r"^#{1,6}\s", x) for x in lines):
        return False
    return not any(
        re.match(patron, first_one, re.IGNORECASE)
        for patron in decorations.get("frases_de_presentacion", [])
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
    return bool(attempt.get("descartada")) and (
        attempt.get("descartada_motivo") not in RESOURCE_ONLY_REASONS
    )


def _falla(attempt: dict[str, Any]) -> bool:
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
        point = {"calidad": 0.0, "formato": False}
    hot = ok and final.get("thermal_state") != "cold"
    return Result(
        label=label,
        case=case["id"],
        ok=ok,
        fails=any(_falla(i) for i in attempts),
        quality=float(point["calidad"]),
        fmt=bool(point["formato"]),
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
    for ts, model_id, enters, sale, pps, tps, duration, state, error in rows:
        start_ts = ts - duration / 1000
        prior = last.get(model_id)
        if (
            model_id == model
            and prior is not None
            and start_ts - prior >= gap_s
            and state == 200
            and not error
            and sale > 0
        ):
            inference = (enters / pps if pps else 0.0) + (sale / tps if tps else 0.0)
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

    El orden de los desenlaces es fijo: si falla el criterio 1 la celda queda `sin base`, falle lo
    que falle ademas; si el 1 se cumple y falla cualquier otro, `rechazada`; si todos, `aprobada`.
    Los casos de regresion (no discriminantes) cuentan en los criterios 2 a 6 pero no en el 1.
    """
    discriminating = [c for c in cases if c.get("discriminante")]
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
        if ok["calidad"] != 1.0 or not ok["formato"] or bad["calidad"] >= 1.0:
            bad_references.append(c["id"])
    scores_below_one = [
        c["id"]
        for c in discriminating
        if res[(role, c["id"])].quality < 1.0 or res[(weak, c["id"])].quality < 1.0
    ]
    discriminates = {
        "ok": not bad_references and bool(scores_below_one),
        "referencias_malas": bad_references,
        "casos_donde_el_rol_o_el_debil_fallan": scores_below_one,
    }

    # 2. Calidad: en cada caso, M >= el rol.
    worst = [
        c["id"]
        for c in cases
        if res[(alternative, c["id"])].quality < res[(role, c["id"])].quality - _EPS
    ]
    quality = {"ok": not worst, "casos_peores": worst}

    # 3. Formato: donde el rol da formato correcto, M tambien.
    unformatted = [
        c["id"] for c in cases if res[(role, c["id"])].fmt and not res[(alternative, c["id"])].fmt
    ]
    fmt = {"ok": not unformatted, "casos_sin_formato": unformatted}

    # 4. Verbosidad: la mediana de chars(M)/chars(rol) <= 1,5.
    ratios = [
        res[(alternative, c["id"])].chars / res[(role, c["id"])].chars
        for c in cases
        if res[(role, c["id"])].chars > 0
    ]
    ratio_median = _median(ratios)
    verbosity = {
        "ok": ratio_median is not None and ratio_median <= MAX_VERBOSITY,
        "mediana": ratio_median,
        "maximo": MAX_VERBOSITY,
    }

    # 5. Fiabilidad: ningun caso donde M falla y el rol no.
    failures = [
        c["id"]
        for c in cases
        if res[(alternative, c["id"])].fails and not res[(role, c["id"])].fails
    ]
    reliability = {"ok": not failures, "casos_que_fallan_solo_en_el_alternativo": failures}

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
        "mediana_alternativo_ms": lat_m,
        "mediana_rol_ms": lat_r,
        "carga_en_frio_rol_s": role_cold_s,
        "nota": None if role_cold_s is not None else "sin filas en frio en metrics.db: se usa 0 s",
    }

    criteria = {
        "discrimina": discriminates,
        "calidad": quality,
        "formato": fmt,
        "verbosidad": verbosity,
        "fiabilidad": reliability,
        "latencia": latency,
    }
    if not discriminates["ok"]:
        state = "sin base"
    elif all(v["ok"] for v in criteria.values()):
        state = "aprobada"
    else:
        state = "rechazada"
    return {
        "tool": tool,
        "alternativo": alternative,
        "rol_comparado": role,
        "estado": state,
        "criterios": criteria,
        "casos": len(cases),
    }


# --- Celda de commit (REQ-043, criterios 0 a 3) -----------------------------------------------------


_PUBLISHED_ROW = {"mensajes": 0, "inventa": 0, "formato": 0, "principal_si": 0, "especifico_si": 0}


def _preferred(pair: dict[str, Any]) -> str:
    """Quien gano el par: el nombre del lado elegido, o `empate`."""
    choice = pair.get("preferencia")
    if choice is None:
        raise NoData(f"el par {pair.get('caso')} no tiene preferencia")
    return "empate" if choice == "=" else str(pair["lados"][choice])


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
    `max_inventa_26b` de los 30 mensajes del 26B. 2: `c >= v`. 3: el techo termina 3 de 3 y ningun
    caso falla en el 26B si no falla en el modelo de codigo. Si falla el 0, `sin base`; si el 0 se
    cumple y falla el 1, el 2 o el 3, `rechazada`.
    """
    if judgement.get("parcial"):
        raise NoData("el juicio es parcial: el veredicto necesita la hoja entera")
    pair_items = judgement["pares"]
    traps = [p for p in pair_items.values() if p["tipo"] == "trampa"]
    real = [p for p in pair_items.values() if p["tipo"] == "real"]
    if len(traps) != TRAPS_PER_SHEET:
        raise NoData(f"la hoja tiene {len(traps)} pares trampa y se esperaban {TRAPS_PER_SHEET}")
    worst = 0
    for p in traps:
        winner = _preferred(p)
        worst += winner not in ("empate", "trampa")
    sheet = {
        "ok": worst >= MIN_TRAPS,
        "trampas_marcadas_como_peores": worst,
        "de": len(traps),
    }

    invents_if = 0
    n = 0
    published: dict[str, dict[str, int]] = {}
    for p in real:
        for side, model in p["lados"].items():
            row = published.setdefault(model, dict(_PUBLISHED_ROW))
            row["mensajes"] += 1
            row["inventa"] += p["inventa"][side] == "s"
            row["principal_si"] += (p.get("principal") or {}).get(side) == "s"
            row["especifico_si"] += (p.get("especifico") or {}).get(side) == "s"
        if p["lados"]["A"] == alternative or p["lados"]["B"] == alternative:
            side = "A" if p["lados"]["A"] == alternative else "B"
            n += 1
            invents_if += p["inventa"][side] == "s"
    invents = {
        "ok": invents_if <= int(rules["max_inventa_26b"]),
        "n": n,
        "si": invents_if,
        "max": int(rules["max_inventa_26b"]),
    }

    c = sum(_preferred(p) == alternative for p in real)
    v = sum(_preferred(p) == role for p in real)
    preference = {"ok": c >= v, "c": c, "v": v, "empates": len(real) - c - v}

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
            row["formato"] += result.ok and message_format(result.text, rules["formato"])
    behaviour = {
        "ok": ceiling_ok and not only_in_alternative,
        "techo_3_de_3": ceiling_ok,
        "casos_que_fallan_solo_en_el_alternativo": only_in_alternative,
    }

    criteria = {
        "hoja_valida": sheet,
        "inventa": invents,
        "preferencia": preference,
        "funcionamiento": behaviour,
    }
    report = None
    if not sheet["ok"]:
        state = "sin base"
        report = (
            "repetir hoja"
            if int(judgement.get("juego") or 1) < 3
            else "la tercera hoja tampoco vale: sin base"
        )
    elif invents["ok"] and preference["ok"] and behaviour["ok"]:
        state = "aprobada"
    else:
        state = "rechazada"
    return {
        "tool": TOOL_COMMIT,
        "alternativo": alternative,
        "rol_comparado": role,
        "estado": state,
        "criterios": criteria,
        "informe": report,
        "publicados": published,
        "casos": len(real),
    }


# --- Veredicto -------------------------------------------------------------------------------------


def _footprint(footprints: dict[str, Any], model: str, tool: str) -> dict[str, Any]:
    try:
        return dict(footprints[model][tool])
    except (KeyError, TypeError) as exc:
        raise NoData(f"huellas.json no trae la huella de {model} para {tool}") from exc


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
    """Aplica los criterios literalmente y devuelve el contenido de `veredicto.json`.

    No hay ningun parametro que fuerce un estado: la unica forma de cambiar un estado es cambiar los
    datos.
    """
    models = production_config["models"]
    mechanical_role, long, code = models["mechanical"], models["long"], models["code"]
    cases = [
        c
        for c in corpus.values()
        if c.get("kind") == "calidad" and c.get("rol_en_hoja") != "trampa"
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
            cell["huella"] = _footprint(footprints, alternative, tool)
            cell["huella_rol"] = _footprint(footprints, mechanical_role, tool)
            cells.append(cell)
    if not mechanical_only:
        if judgement is None:
            raise NoData(
                "falta el juicio del usuario (`leer-commit --salida`) para la celda de commit"
            )
        real = [c for c in cases if c["tool"] == TOOL_COMMIT and c.get("rol_en_hoja") == "real"]
        ceiling = [c for c in corpus.values() if c["id"] == CEILING_CASE_ID]
        cell = evaluate_commit_cell(long, code, judgement, rules, real, runs, ceiling)
        cell["huella"] = _footprint(footprints, long, TOOL_COMMIT)
        cell["huella_rol"] = _footprint(footprints, code, TOOL_COMMIT)
        cells.append(cell)
    return {
        "schema_version": 1,
        "solo_mecanicas": mechanical_only,
        "reglas": rules,
        "celdas": cells,
    }


def verdict_table(verdict: dict[str, Any]) -> str:
    """La tabla Markdown que se pega en `verification.md`."""
    lines = [
        "| Tool | Alternativo | Comparado con | Estado | Criterios que no se cumplen |",
        "| --- | --- | --- | --- | --- |",
    ]
    for cell in verdict["celdas"]:
        fails = [name for name, c in cell["criterios"].items() if not c["ok"]]
        extra = f" ({cell['informe']})" if cell.get("informe") else ""
        lines.append(
            f"| {cell['tool']} | {cell['alternativo']} | {cell['rol_comparado']} | "
            f"{cell['estado']}{extra} | {', '.join(fails) or '—'} |"
        )
    commit = next((c for c in verdict["celdas"] if c["tool"] == TOOL_COMMIT), None)
    if commit:
        lines += ["", "Celda de commit, lo que se publica y no decide:", ""]
        lines += [
            "| Modelo | Mensajes | inventa = si | Formato (calculado) | Lo principal = si | Especifico = si |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for model, row in sorted(commit["publicados"].items()):
            lines.append(
                f"| {model} | {row['mensajes']} | {row['inventa']} | {row['formato']} | "
                f"{row['principal_si']} | {row['especifico_si']} |"
            )
    return "\n".join(lines) + "\n"


def run_verdict(args: argparse.Namespace) -> int:
    cases_path: Path = args.cases
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 2:
        raise ValueError(f"{cases_path}: se esperaba un corpus schema_version 2")
    corpus = {c["id"]: c for c in data["cases"]}
    rules = read_affinity_rules(args.rules)
    footprints = json.loads(args.footprints.read_text(encoding="utf-8"))
    runs = group_runs(leer_jsonl(args.jsonl))
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
    verdict["reglas_sha256"] = hashlib.sha256(args.rules.read_bytes()).hexdigest()
    verdict["cases_sha256"] = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    output = args.salida or cases_path.parent / (
        "veredicto-mecanicas.json" if args.mechanical_only else "veredicto.json"
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
        help="aplica los criterios de aceptacion de las celdas (REQ-043) y escribe veredicto.json",
    )
    base = Path(__file__).resolve().parents[1] / "benchmarks" / "afinidad-2026-10"
    p.add_argument("--cases", type=Path, default=base / "cases.json")
    p.add_argument("--rules", type=Path, default=base / "reglas.json")
    p.add_argument("--footprints", type=Path, default=base / "huellas.json")
    p.add_argument(
        "--judgement", type=Path, default=None, help="salida de `hoja_pares.py leer-commit`"
    )
    p.add_argument("--metrics-db", type=Path, default=None, help="una COPIA de metrics.db")
    p.add_argument("--mechanical-only", action="store_true", help="sin la celda de commit")
    p.add_argument("--salida", type=Path, default=None, help="veredicto.json")
    p.add_argument("--table", type=Path, default=None, help="tabla Markdown para verification.md")
    p.add_argument("jsonl", nargs="+", type=Path, help="resultados de la tanda")


# --- CLI ----------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    sub = parser.add_subparsers(dest="modo", required=True)
    _verdict_parser(sub)
    for nombre in ("cp3", "decidir"):
        p = sub.add_parser(nombre)
        p.add_argument("--cases", type=Path, required=True, help="cases.json del corpus v2")
        p.add_argument(
            "--json", type=Path, default=None, help="escribe tambien el resultado en JSON"
        )
        p.add_argument(
            "--salida", type=Path, default=None, help="escribe el informe aqui en vez de stdout"
        )
        p.add_argument("jsonl", nargs="+", type=Path)
    cp3 = sub.choices["cp3"]
    cp3.add_argument("--pequeno", required=True, help="label, o label@control")
    cp3.add_argument("--grande", required=True, help="label, o label@control")
    decidir = sub.choices["decidir"]
    decidir.add_argument(
        "--cp3", type=Path, action="append", default=[], help="JSON de `cp3` (repetible)"
    )
    decidir.add_argument(
        "--par", nargs=3, action="append", required=True, metavar=("ROL", "VIGENTE", "CANDIDATO")
    )
    decidir.add_argument(
        "--pares",
        type=Path,
        action="append",
        default=[],
        help="JSON de `hoja_pares.py destapar --json` (repetible, uno por comparacion)",
    )
    decidir.add_argument(
        "--umbral-shared-mib",
        type=float,
        default=0.0,
        help="crecimiento de Shared Usage tolerado antes de dar CP-1 por caido (sin calibrar: tarea 18)",
    )
    args = parser.parse_args(argv)

    if args.modo == "affinity-verdict":
        try:
            return run_verdict(args)
        except (OSError, ValueError, KeyError) as exc:  # `NoData` es un `ValueError`
            print(f"error: {exc}", file=sys.stderr)
            return 2

    try:
        corpus = leer_corpus(args.cases)
        registros = leer_jsonl(args.jsonl)
        if args.modo == "cp3":
            resultado: Any = analizar_cp3(
                registros, corpus, Selector.parse(args.pequeno), Selector.parse(args.grande)
            )
            texto = informe_cp3(resultado)
        else:
            cp3_por_rol: dict[str, Any] = {}
            for ruta in args.cp3:
                cp3_por_rol.update(json.loads(ruta.read_text(encoding="utf-8"))["roles"])
            pares: dict[str, Any] | None = None
            for ruta in args.pares:
                pares = pares or {}
                for cid, fila in json.loads(ruta.read_text(encoding="utf-8")).items():
                    previo = pares.setdefault(cid, {"humano": {}})["humano"]
                    for quien, n in fila["humano"].items():
                        previo[quien] = previo.get(quien, 0) + int(n)
            configs: dict[str, Config] = {}
            decisiones = []
            for rol, vigente, candidato in args.par:
                par = []
                for nombre in (vigente, candidato):
                    selector = Selector.parse(nombre)
                    configs.setdefault(str(selector), cargar_config(registros, selector))
                    par.append(configs[str(selector)])
                decisiones.append(
                    decidir_rol(
                        rol,
                        par[0],
                        par[1],
                        corpus,
                        cp3_por_rol.get(rol),
                        round(args.umbral_shared_mib * 1024 * 1024),
                        pares,
                    )
                )
            resultado = {"decisiones": decisiones}
            texto = informe_decision(decisiones, configs, corpus)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        args.json.write_text(
            json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.salida:
        args.salida.write_text(texto, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
