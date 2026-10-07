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

- `veredicto-afinidad`: la evaluacion que aprueba las celdas de afinidad (REQ-040 a REQ-043 del SDD
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
TOOLS_CON_CELDA = (
    "local_classify",
    "local_extract",
    "local_translate",
    "local_lint_summary",
    "local_delegate",
)
TOOL_COMMIT = "local_commit_msg"
CONTROL_DEBIL = "qwen35-2b"  # control debil de la tanda (REQ-041), solo en las mecanicas
CASO_TECHO = "techo-commit-156k"
CORRIDAS_DEL_TECHO = 3
VERBOSIDAD_MAXIMA = 1.5  # criterio 4
TRAMPAS_POR_HOJA = 3
TRAMPAS_MINIMAS = 2  # criterio 0: la hoja vale si el usuario marca peor la trampa en 2 de las 3
HUECO_FRIO_S = 300  # una fila es «en frio» si el modelo llevaba >= 300 s sin peticiones (TTL max.)
_EPS = 1e-9


class SinDatos(ValueError):
    """Falta un dato que el criterio necesita. Nunca se sustituye por un valor: sin dato no hay
    veredicto, porque una celda aprobada con un hueco seria una celda aprobada a ciegas."""


# --- Puntuadores de las tools mecanicas -----------------------------------------------------------


def _quitar_vallas(texto: str) -> str:
    """Lo mismo que `_strip_fences` de la tool: la salida que ve quien llama ya va sin vallas."""
    s = texto.strip()
    if s.startswith("```"):
        lineas = s.splitlines()[1:]
        if lineas and lineas[-1].strip().startswith("```"):
            lineas = lineas[:-1]
        s = "\n".join(lineas).strip()
    return s


def _igual_json(a: Any, b: Any) -> bool:
    """Igualdad estricta de valores JSON: `True` no es 1, `"502"` no es 502, `0` no es `null`."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


_TITULO = re.compile(r"^#{1,6}\s+\S")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_VALLA_ABRE = re.compile(r"^\s*(`{3,}|~{3,})")


def estructura_markdown(texto: str) -> dict[str, Any]:
    """Titulos, elementos de lista y bloques de codigo de un Markdown, y el codigo de cada bloque.

    Lo de dentro de una valla no cuenta como titulo ni como lista: un `# comentario` de Python no es
    un encabezado.
    """
    titulos = listas = 0
    bloques: list[str] = []
    valla: str | None = None
    actual: list[str] = []
    for linea in texto.replace("\r\n", "\n").split("\n"):
        if valla is not None:
            cierre = linea.strip()
            if cierre and set(cierre) == {valla[0]} and len(cierre) >= len(valla):
                bloques.append("\n".join(actual))
                valla, actual = None, []
            else:
                actual.append(linea)
            continue
        if m := _VALLA_ABRE.match(linea):
            valla = m.group(1)
            continue
        titulos += bool(_TITULO.match(linea))
        listas += bool(_ITEM.match(linea))
    if valla is not None:  # valla sin cerrar: cuenta como bloque (el modelo se quedo a medias)
        bloques.append("\n".join(actual))
    return {"titulos": titulos, "listas": listas, "bloques": len(bloques), "codigo": bloques}


_CODIGO_DE_REGLA = re.compile(r"(?<![A-Za-z0-9])[A-Z]+[0-9]+(?![A-Za-z0-9])")
_ENTERO_SUELTO = re.compile(r"(?<![\w.])\d+(?!\w|\.\d)")


def reglas_con_conteo_incorrecto(texto: str, conteos: dict[str, list[int]]) -> list[str]:
    """Las reglas de `conteos` cuyo numero NO cuadra con la fuente.

    Cada entero pertenece a la regla que tiene delante en su linea, hasta la siguiente regla. Cuadra
    si la regla tiene al menos un entero y todos estan entre los validos (el total, los archivos que
    la tienen o lo que suma en alguno). Una regla nombrada sin conteo no cuadra. Es la misma
    lectura que `check_counts` de `benchmark.py`, copiada porque este modulo no importa el paquete.
    """
    numeros: dict[str, list[int]] = {regla: [] for regla in conteos}
    for linea in texto.splitlines():
        codigos = list(_CODIGO_DE_REGLA.finditer(linea))
        for i, codigo in enumerate(codigos):
            if codigo.group() not in numeros:
                continue
            fin = codigos[i + 1].start() if i + 1 < len(codigos) else len(linea)
            numeros[codigo.group()] += [
                int(n) for n in _ENTERO_SUELTO.findall(linea[codigo.end() : fin])
            ]
    return [
        regla
        for regla, validos in conteos.items()
        if not numeros[regla] or not set(numeros[regla]) <= set(validos)
    ]


def puntuar_afinidad(
    caso: dict[str, Any], texto: str, registro: dict[str, Any] | None = None
) -> dict[str, Any]:
    """`{"calidad": 0..1, "formato": bool}` de una respuesta, con el puntuador DEL caso.

    El puntuador sale de `cases.json` (`puntuador`), con lo esperado calculado por el constructor del
    corpus a partir de la fuente, no de lo que respondio un modelo. `formato` es lo que la tool
    prometio (una etiqueta, un objeto JSON con esas claves, la estructura Markdown, un limite de
    palabras, un formato exacto); `calidad` es si ademas es correcto.
    """
    spec = caso.get("puntuador") or {}
    tipo = spec.get("tipo")
    if tipo == "classify":
        respuesta = texto.strip()
        return {
            "calidad": 1.0 if respuesta in spec["aceptables"] else 0.0,
            "formato": respuesta in spec["etiquetas"],
        }
    if tipo == "extract":
        try:
            objeto = json.loads(_quitar_vallas(texto))
        except ValueError:
            objeto = None
        if not isinstance(objeto, dict) or set(objeto) != set(spec["claves"]):
            return {"calidad": 0.0, "formato": False}
        bien = sum(_igual_json(objeto[c], spec["esperado"][c]) for c in spec["claves"])
        return {"calidad": bien / len(spec["claves"]), "formato": True}
    if tipo == "translate":
        est = estructura_markdown(texto)
        estructura = [
            est["titulos"] == spec["titulos"],
            est["listas"] == spec["listas"],
            est["bloques"] == spec["bloques"],
        ]
        dentro = set(est["codigo"])
        pruebas = estructura + [bloque in dentro for bloque in spec["codigo"]]
        return {"calidad": sum(pruebas) / len(pruebas), "formato": all(estructura)}
    if tipo == "lint":
        malas = reglas_con_conteo_incorrecto(texto, spec["conteos"])
        palabras = len(re.findall(r"\w+", texto))
        return {
            "calidad": (len(spec["conteos"]) - len(malas)) / len(spec["conteos"]),
            "formato": bool(texto.strip()) and palabras <= spec["max_words"],
        }
    if tipo == "delegate":
        respuesta = texto.strip()
        return {
            "calidad": 1.0 if respuesta == spec["esperado"] else 0.0,
            "formato": re.fullmatch(spec["formato"], respuesta) is not None,
        }
    if tipo == "f2":
        # Los cinco casos de regresion de F2 conservan su puntuacion de entonces, la del runner.
        puntuacion = (registro or {}).get("score") or {}
        calidad = puntuacion.get("quality")
        formato = puntuacion.get("format_ok")
        return {
            "calidad": float(calidad) if calidad is not None else 0.0,
            "formato": True if formato is None else bool(formato),
        }
    raise ValueError(f"{caso.get('id')}: puntuador {tipo!r} desconocido")


# --- Reglas, huellas y resultados -----------------------------------------------------------------

PREGUNTAS_OPCIONALES_POSIBLES = frozenset({"principal", "especifico"})


def leer_reglas_afinidad(ruta: Path) -> dict[str, Any]:
    """`reglas.json`, validado. Una regla invalida lo rechaza entero: no hay valores por defecto."""
    reglas = json.loads(ruta.read_text(encoding="utf-8"))
    maximo = reglas.get("max_inventa_26b")
    if not isinstance(maximo, int) or isinstance(maximo, bool) or maximo < 0:
        raise SystemExit("reglas.json: max_inventa_26b tiene que ser un entero >= 0")
    opcionales = reglas.get("preguntas_opcionales")
    if not isinstance(opcionales, list) or not set(opcionales) <= PREGUNTAS_OPCIONALES_POSIBLES:
        raise SystemExit(
            "reglas.json: preguntas_opcionales solo admite 'principal' y 'especifico'; "
            "'inventa' y la preferencia no pueden ser opcionales"
        )
    if not isinstance(reglas.get("formato"), dict):
        raise SystemExit("reglas.json: falta la regla de formato")
    if not isinstance(reglas.get("parada_anticipada"), bool):
        raise SystemExit("reglas.json: parada_anticipada tiene que ser true o false")
    return reglas


def formato_de_mensaje(mensaje: str, regla: dict[str, Any]) -> bool:
    """«Formato» de un mensaje de commit, calculado por el programa con la regla de `reglas.json`.

    Primera linea de 72 caracteres como maximo, prefijo convencional y sin adornos: ni vallas de
    codigo, ni comillas que envuelvan el mensaje, ni encabezados Markdown, ni frases de
    presentacion. Se publica; no decide ninguna celda.
    """
    texto = mensaje.strip("\n")
    if not texto.strip():
        return False
    primera = texto.split("\n", 1)[0]
    if len(primera) > int(regla["primera_linea_max"]):
        return False
    if re.match(regla["prefijo"], primera) is None:
        return False
    adornos = regla["sin_adornos"]
    lineas = texto.split("\n")
    if adornos.get("vallas_de_codigo") and any(
        linea.strip().startswith(("```", "~~~")) for linea in lineas
    ):
        return False
    pelado = texto.strip()
    if (
        adornos.get("comillas_envolventes")
        and len(pelado) > 1
        and pelado[0] in "\"'`“«‘"
        and pelado[-1] in "\"'`”»’"
    ):
        return False
    if adornos.get("encabezados_markdown") and any(re.match(r"^#{1,6}\s", x) for x in lineas):
        return False
    return not any(
        re.match(patron, primera, re.IGNORECASE)
        for patron in adornos.get("frases_de_presentacion", [])
    )


@dataclass
class Resultado:
    """Lo que un modelo hizo en un caso, ya reducido a lo que miran los criterios."""

    label: str
    caso: str
    ok: bool  # la corrida termino bien (ultimo intento)
    falla: bool  # algun intento no anulado dio error, timeout, rechazo o `length`
    calidad: float
    formato: bool
    chars: int
    latencia_ms: float | None
    texto: str


Corridas = dict[tuple[str, str, int], list[dict[str, Any]]]


def agrupar_corridas(registros: list[dict[str, Any]]) -> Corridas:
    """`(label, caso, corrida) -> intentos` en el orden del fichero: el ultimo intento manda."""
    corridas: Corridas = {}
    for r in registros:
        if r.get("input_variant") is not None:
            continue
        corridas.setdefault((str(r["label"]), str(r["case"]), int(r["run"])), []).append(r)
    return corridas


# Motivos de anulación de la sonda que solo dejan la fila sin medida de recursos (RAM o VRAM): la
# respuesta es válida y este veredicto no juzga recursos, así que la fila cuenta. Pasa con peticiones
# de menos de 100 ms, que terminan antes de que la sonda muestree. Un proceso que cambió o varios
# procesos sí invalidan la corrida y se siguen descartando. Solo afecta al veredicto de afinidad.
MOTIVOS_SOLO_DE_RECURSOS = frozenset({"zero_vram_samples", "zero_ram_samples"})


def _anulada(intento: dict[str, Any]) -> bool:
    """La fila no vale para el veredicto de afinidad (ver `MOTIVOS_SOLO_DE_RECURSOS`)."""
    return bool(intento.get("descartada")) and (
        intento.get("descartada_motivo") not in MOTIVOS_SOLO_DE_RECURSOS
    )


def _falla(intento: dict[str, Any]) -> bool:
    return not _anulada(intento) and intento.get("outcome") != "ok"


def resultado_de(
    corridas: Corridas, label: str, caso: dict[str, Any], run: int = 1, *, puntuar: bool = True
) -> Resultado:
    intentos = corridas.get((label, caso["id"], run))
    if not intentos:
        raise SinDatos(f"falta la corrida {run} de {label} en {caso['id']}")
    final = intentos[-1]
    if _anulada(final):
        raise SinDatos(f"{label}:{caso['id']} corrida {run}: anulada y sin repetir")
    ok = final.get("outcome") == "ok"
    texto = str(final.get("response") or "")
    if ok and "response" not in final:
        raise SinDatos(f"{label}:{caso['id']}: sin respuesta guardada (falta --save-responses)")
    if ok and puntuar:
        punto = puntuar_afinidad(caso, texto, final)
    else:
        # Un caso que no termino puntua 0: una respuesta que no existe no puede ser mejor que otra.
        punto = {"calidad": 0.0, "formato": False}
    caliente = ok and final.get("thermal_state") != "cold"
    return Resultado(
        label=label,
        caso=caso["id"],
        ok=ok,
        falla=any(_falla(i) for i in intentos),
        calidad=float(punto["calidad"]),
        formato=bool(punto["formato"]),
        chars=int(final.get("response_chars") or len(texto)),
        latencia_ms=float(final["latency_ms"]) if caliente and "latency_ms" in final else None,
        texto=texto,
    )


def carga_en_frio_mediana(db: Path, modelo: str, hueco_s: int = HUECO_FRIO_S) -> float | None:
    """Mediana (s) de lo que tarda una peticion en frio en `modelo`, de una COPIA de `metrics.db`.

    Una fila es «en frio» si el modelo llevaba al menos `hueco_s` sin peticiones (venció su TTL) y
    termino bien. Su carga es lo que sobra de la duracion al quitarle la inferencia: `duration_ms`
    incluye la cola y la carga del modelo (`ts_created` es el momento en que termina).
    """
    conexion = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        filas = conexion.execute(
            "SELECT ts_created, model_id, input_tokens, output_tokens, prompt_per_second, "
            "tokens_per_second, duration_ms, resp_status_code, error_msg "
            "FROM activity ORDER BY ts_created, id"
        ).fetchall()
    finally:
        conexion.close()
    ultimo: dict[str, float] = {}
    esperas: list[float] = []
    for ts, modelo_id, entra, sale, pps, tps, duracion, estado, error in filas:
        inicio = ts - duracion / 1000
        previo = ultimo.get(modelo_id)
        if (
            modelo_id == modelo
            and previo is not None
            and inicio - previo >= hueco_s
            and estado == 200
            and not error
            and sale > 0
        ):
            inferencia = (entra / pps if pps else 0.0) + (sale / tps if tps else 0.0)
            esperas.append(max(0.0, duracion / 1000 - inferencia))
        ultimo[modelo_id] = ts
    return statistics.median(esperas) if esperas else None


# --- Celda mecanica (REQ-043, criterios 1 a 6) ------------------------------------------------------


def _mediana(valores: list[float]) -> float | None:
    return statistics.median(valores) if valores else None


def evaluar_celda_mecanica(
    tool: str,
    alternativo: str,
    rol: str,
    casos: list[dict[str, Any]],
    corridas: Corridas,
    frio_rol_s: float | None,
    debil: str = CONTROL_DEBIL,
) -> dict[str, Any]:
    """Estado y criterios de una celda mecanica `tool -> alternativo`, comparada con `rol`.

    El orden de los desenlaces es fijo: si falla el criterio 1 la celda queda `sin base`, falle lo
    que falle ademas; si el 1 se cumple y falla cualquier otro, `rechazada`; si todos, `aprobada`.
    Los casos de regresion (no discriminantes) cuentan en los criterios 2 a 6 pero no en el 1.
    """
    discriminantes = [c for c in casos if c.get("discriminante")]
    if not discriminantes:
        raise SinDatos(f"{tool}: el corpus no trae casos discriminantes")
    res = {
        (label, c["id"]): resultado_de(corridas, label, c)
        for label in (alternativo, rol, debil)
        for c in casos
    }

    # 1. El corpus discrimina: las referencias separan y alguien saca menos de 1.
    malas_referencias = []
    for c in discriminantes:
        ok = puntuar_afinidad(c, c["reference_ok"])
        malo = puntuar_afinidad(c, c["reference_bad"])
        if ok["calidad"] != 1.0 or not ok["formato"] or malo["calidad"] >= 1.0:
            malas_referencias.append(c["id"])
    saca_menos_de_uno = [
        c["id"]
        for c in discriminantes
        if res[(rol, c["id"])].calidad < 1.0 or res[(debil, c["id"])].calidad < 1.0
    ]
    discrimina = {
        "ok": not malas_referencias and bool(saca_menos_de_uno),
        "referencias_malas": malas_referencias,
        "casos_donde_el_rol_o_el_debil_fallan": saca_menos_de_uno,
    }

    # 2. Calidad: en cada caso, M >= el rol.
    peores = [
        c["id"]
        for c in casos
        if res[(alternativo, c["id"])].calidad < res[(rol, c["id"])].calidad - _EPS
    ]
    calidad = {"ok": not peores, "casos_peores": peores}

    # 3. Formato: donde el rol da formato correcto, M tambien.
    sin_formato = [
        c["id"]
        for c in casos
        if res[(rol, c["id"])].formato and not res[(alternativo, c["id"])].formato
    ]
    formato = {"ok": not sin_formato, "casos_sin_formato": sin_formato}

    # 4. Verbosidad: la mediana de chars(M)/chars(rol) <= 1,5.
    razones = [
        res[(alternativo, c["id"])].chars / res[(rol, c["id"])].chars
        for c in casos
        if res[(rol, c["id"])].chars > 0
    ]
    mediana_razon = _mediana(razones)
    verbosidad = {
        "ok": mediana_razon is not None and mediana_razon <= VERBOSIDAD_MAXIMA,
        "mediana": mediana_razon,
        "maximo": VERBOSIDAD_MAXIMA,
    }

    # 5. Fiabilidad: ningun caso donde M falla y el rol no.
    fallos = [
        c["id"]
        for c in casos
        if res[(alternativo, c["id"])].falla and not res[(rol, c["id"])].falla
    ]
    fiabilidad = {"ok": not fallos, "casos_que_fallan_solo_en_el_alternativo": fallos}

    # 6. Latencia: mediana en caliente de M <= la del rol mas su carga en frio mediana.
    lat_m = _mediana(
        [
            r.latencia_ms
            for (lab, _), r in res.items()
            if lab == alternativo and r.latencia_ms is not None
        ]
    )
    lat_r = _mediana(
        [r.latencia_ms for (lab, _), r in res.items() if lab == rol and r.latencia_ms is not None]
    )
    frio = frio_rol_s if frio_rol_s is not None else 0.0
    latencia = {
        "ok": lat_m is not None and lat_r is not None and lat_m <= lat_r + frio * 1000,
        "mediana_alternativo_ms": lat_m,
        "mediana_rol_ms": lat_r,
        "carga_en_frio_rol_s": frio_rol_s,
        "nota": None if frio_rol_s is not None else "sin filas en frio en metrics.db: se usa 0 s",
    }

    criterios = {
        "discrimina": discrimina,
        "calidad": calidad,
        "formato": formato,
        "verbosidad": verbosidad,
        "fiabilidad": fiabilidad,
        "latencia": latencia,
    }
    if not discrimina["ok"]:
        estado = "sin base"
    elif all(v["ok"] for v in criterios.values()):
        estado = "aprobada"
    else:
        estado = "rechazada"
    return {
        "tool": tool,
        "alternativo": alternativo,
        "rol_comparado": rol,
        "estado": estado,
        "criterios": criterios,
        "casos": len(casos),
    }


# --- Celda de commit (REQ-043, criterios 0 a 3) -----------------------------------------------------


_FILA_PUBLICADA = {"mensajes": 0, "inventa": 0, "formato": 0, "principal_si": 0, "especifico_si": 0}


def _preferido(par: dict[str, Any]) -> str:
    """Quien gano el par: el nombre del lado elegido, o `empate`."""
    eleccion = par.get("preferencia")
    if eleccion is None:
        raise SinDatos(f"el par {par.get('caso')} no tiene preferencia")
    return "empate" if eleccion == "=" else str(par["lados"][eleccion])


def evaluar_celda_commit(
    alternativo: str,
    rol: str,
    juicio: dict[str, Any],
    reglas: dict[str, Any],
    casos_reales: list[dict[str, Any]],
    corridas: Corridas,
    techo: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """`local_commit_msg -> alternativo` con la regla del usuario, fijada antes de ver datos.

    0 (hoja valida): el usuario marca peor la trampa en 2 de las 3. 1: «inventa = si» en no mas de
    `max_inventa_26b` de los 30 mensajes del 26B. 2: `c >= v`. 3: el techo termina 3 de 3 y ningun
    caso falla en el 26B si no falla en el modelo de codigo. Si falla el 0, `sin base`; si el 0 se
    cumple y falla el 1, el 2 o el 3, `rechazada`.
    """
    if juicio.get("parcial"):
        raise SinDatos("el juicio es parcial: el veredicto necesita la hoja entera")
    pares = juicio["pares"]
    trampas = [p for p in pares.values() if p["tipo"] == "trampa"]
    reales = [p for p in pares.values() if p["tipo"] == "real"]
    if len(trampas) != TRAMPAS_POR_HOJA:
        raise SinDatos(
            f"la hoja tiene {len(trampas)} pares trampa y se esperaban {TRAMPAS_POR_HOJA}"
        )
    peores = 0
    for p in trampas:
        ganador = _preferido(p)
        peores += ganador not in ("empate", "trampa")
    hoja = {
        "ok": peores >= TRAMPAS_MINIMAS,
        "trampas_marcadas_como_peores": peores,
        "de": len(trampas),
    }

    inventa_si = 0
    n = 0
    publicados: dict[str, dict[str, int]] = {}
    for p in reales:
        for lado, modelo in p["lados"].items():
            fila = publicados.setdefault(modelo, dict(_FILA_PUBLICADA))
            fila["mensajes"] += 1
            fila["inventa"] += p["inventa"][lado] == "s"
            fila["principal_si"] += (p.get("principal") or {}).get(lado) == "s"
            fila["especifico_si"] += (p.get("especifico") or {}).get(lado) == "s"
        if p["lados"]["A"] == alternativo or p["lados"]["B"] == alternativo:
            lado = "A" if p["lados"]["A"] == alternativo else "B"
            n += 1
            inventa_si += p["inventa"][lado] == "s"
    inventa = {
        "ok": inventa_si <= int(reglas["max_inventa_26b"]),
        "n": n,
        "si": inventa_si,
        "max": int(reglas["max_inventa_26b"]),
    }

    c = sum(_preferido(p) == alternativo for p in reales)
    v = sum(_preferido(p) == rol for p in reales)
    preferencia = {"ok": c >= v, "c": c, "v": v, "empates": len(reales) - c - v}

    # 3a: el techo por el camino de produccion, 3 de 3 sin error con el 26B.
    corridas_techo = []
    for run in range(1, CORRIDAS_DEL_TECHO + 1):
        if techo:
            corridas_techo.append(resultado_de(corridas, alternativo, techo[0], run, puntuar=False))
    techo_ok = (
        bool(techo)
        and len(corridas_techo) == CORRIDAS_DEL_TECHO
        and not any(r.falla for r in corridas_techo)
    )
    # 3b: ningun caso falla en el alternativo si no falla en el modelo de codigo.
    solo_en_el_alternativo = []
    for caso in casos_reales:
        a = resultado_de(corridas, alternativo, caso, puntuar=False)
        r = resultado_de(corridas, rol, caso, puntuar=False)
        if a.falla and not r.falla:
            solo_en_el_alternativo.append(caso["id"])
        # «Formato» lo calcula el programa sobre el mensaje tal como lo devolvio la tool.
        for resultado in (a, r):
            fila = publicados.setdefault(resultado.label, dict(_FILA_PUBLICADA))
            fila["formato"] += resultado.ok and formato_de_mensaje(
                resultado.texto, reglas["formato"]
            )
    funcionamiento = {
        "ok": techo_ok and not solo_en_el_alternativo,
        "techo_3_de_3": techo_ok,
        "casos_que_fallan_solo_en_el_alternativo": solo_en_el_alternativo,
    }

    criterios = {
        "hoja_valida": hoja,
        "inventa": inventa,
        "preferencia": preferencia,
        "funcionamiento": funcionamiento,
    }
    informe = None
    if not hoja["ok"]:
        estado = "sin base"
        informe = (
            "repetir hoja"
            if int(juicio.get("juego") or 1) < 3
            else "la tercera hoja tampoco vale: sin base"
        )
    elif inventa["ok"] and preferencia["ok"] and funcionamiento["ok"]:
        estado = "aprobada"
    else:
        estado = "rechazada"
    return {
        "tool": TOOL_COMMIT,
        "alternativo": alternativo,
        "rol_comparado": rol,
        "estado": estado,
        "criterios": criterios,
        "informe": informe,
        "publicados": publicados,
        "casos": len(reales),
    }


# --- Veredicto -------------------------------------------------------------------------------------


def _huella(huellas: dict[str, Any], modelo: str, tool: str) -> dict[str, Any]:
    try:
        return dict(huellas[modelo][tool])
    except (KeyError, TypeError) as exc:
        raise SinDatos(f"huellas.json no trae la huella de {modelo} para {tool}") from exc


def calcular_veredicto(
    corpus: dict[str, dict[str, Any]],
    production_config: dict[str, Any],
    corridas: Corridas,
    huellas: dict[str, Any],
    frio_rol_s: float | None,
    reglas: dict[str, Any],
    juicio: dict[str, Any] | None,
    *,
    solo_mecanicas: bool = False,
) -> dict[str, Any]:
    """Aplica los criterios literalmente y devuelve el contenido de `veredicto.json`.

    No hay ningun parametro que fuerce un estado: la unica forma de cambiar un estado es cambiar los
    datos.
    """
    modelos = production_config["models"]
    rol_mecanico, largo, codigo = modelos["mechanical"], modelos["long"], modelos["code"]
    casos = [
        c
        for c in corpus.values()
        if c.get("kind") == "calidad" and c.get("rol_en_hoja") != "trampa"
    ]
    celdas: list[dict[str, Any]] = []
    for tool in TOOLS_CON_CELDA:
        del_tool = [c for c in casos if c["tool"] == tool]
        if not del_tool:
            continue
        for alternativo in (largo, codigo):
            celda = evaluar_celda_mecanica(
                tool, alternativo, rol_mecanico, del_tool, corridas, frio_rol_s
            )
            celda["huella"] = _huella(huellas, alternativo, tool)
            celda["huella_rol"] = _huella(huellas, rol_mecanico, tool)
            celdas.append(celda)
    if not solo_mecanicas:
        if juicio is None:
            raise SinDatos(
                "falta el juicio del usuario (`leer-commit --salida`) para la celda de commit"
            )
        reales = [c for c in casos if c["tool"] == TOOL_COMMIT and c.get("rol_en_hoja") == "real"]
        techo = [c for c in corpus.values() if c["id"] == CASO_TECHO]
        celda = evaluar_celda_commit(largo, codigo, juicio, reglas, reales, corridas, techo)
        celda["huella"] = _huella(huellas, largo, TOOL_COMMIT)
        celda["huella_rol"] = _huella(huellas, codigo, TOOL_COMMIT)
        celdas.append(celda)
    return {
        "schema_version": 1,
        "solo_mecanicas": solo_mecanicas,
        "reglas": reglas,
        "celdas": celdas,
    }


def tabla_del_veredicto(veredicto: dict[str, Any]) -> str:
    """La tabla Markdown que se pega en `verification.md`."""
    lineas = [
        "| Tool | Alternativo | Comparado con | Estado | Criterios que no se cumplen |",
        "| --- | --- | --- | --- | --- |",
    ]
    for celda in veredicto["celdas"]:
        falla = [nombre for nombre, c in celda["criterios"].items() if not c["ok"]]
        extra = f" ({celda['informe']})" if celda.get("informe") else ""
        lineas.append(
            f"| {celda['tool']} | {celda['alternativo']} | {celda['rol_comparado']} | "
            f"{celda['estado']}{extra} | {', '.join(falla) or '—'} |"
        )
    commit = next((c for c in veredicto["celdas"] if c["tool"] == TOOL_COMMIT), None)
    if commit:
        lineas += ["", "Celda de commit, lo que se publica y no decide:", ""]
        lineas += [
            "| Modelo | Mensajes | inventa = si | Formato (calculado) | Lo principal = si | Especifico = si |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for modelo, fila in sorted(commit["publicados"].items()):
            lineas.append(
                f"| {modelo} | {fila['mensajes']} | {fila['inventa']} | {fila['formato']} | "
                f"{fila['principal_si']} | {fila['especifico_si']} |"
            )
    return "\n".join(lineas) + "\n"


def ejecutar_veredicto(args: argparse.Namespace) -> int:
    ruta_cases: Path = args.cases
    datos = json.loads(ruta_cases.read_text(encoding="utf-8"))
    if datos.get("schema_version") != 2:
        raise ValueError(f"{ruta_cases}: se esperaba un corpus schema_version 2")
    corpus = {c["id"]: c for c in datos["cases"]}
    reglas = leer_reglas_afinidad(args.reglas)
    huellas = json.loads(args.huellas.read_text(encoding="utf-8"))
    corridas = agrupar_corridas(leer_jsonl(args.jsonl))
    juicio = json.loads(args.juicio.read_text(encoding="utf-8")) if args.juicio else None
    rol_mecanico = datos["production_config"]["models"]["mechanical"]
    if args.metrics_db is None:
        raise SinDatos("falta --metrics-db (una COPIA de metrics.db) para el criterio 6")
    frio = carga_en_frio_mediana(args.metrics_db, rol_mecanico)
    veredicto = calcular_veredicto(
        corpus,
        datos["production_config"],
        corridas,
        huellas,
        frio,
        reglas,
        juicio,
        solo_mecanicas=args.solo_mecanicas,
    )
    veredicto["reglas_sha256"] = hashlib.sha256(args.reglas.read_bytes()).hexdigest()
    veredicto["cases_sha256"] = hashlib.sha256(ruta_cases.read_bytes()).hexdigest()
    salida = args.salida or ruta_cases.parent / (
        "veredicto-mecanicas.json" if args.solo_mecanicas else "veredicto.json"
    )
    salida.write_text(json.dumps(veredicto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tabla = tabla_del_veredicto(veredicto)
    if args.tabla:
        args.tabla.write_text(tabla, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(tabla)
    return 0


def _parser_veredicto(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "veredicto-afinidad",
        help="aplica los criterios de aceptacion de las celdas (REQ-043) y escribe veredicto.json",
    )
    base = Path(__file__).resolve().parents[1] / "benchmarks" / "afinidad-2026-10"
    p.add_argument("--cases", type=Path, default=base / "cases.json")
    p.add_argument("--reglas", type=Path, default=base / "reglas.json")
    p.add_argument("--huellas", type=Path, default=base / "huellas.json")
    p.add_argument(
        "--juicio", type=Path, default=None, help="salida de `hoja_pares.py leer-commit`"
    )
    p.add_argument("--metrics-db", type=Path, default=None, help="una COPIA de metrics.db")
    p.add_argument("--solo-mecanicas", action="store_true", help="sin la celda de commit")
    p.add_argument("--salida", type=Path, default=None, help="veredicto.json")
    p.add_argument("--tabla", type=Path, default=None, help="tabla Markdown para verification.md")
    p.add_argument("jsonl", nargs="+", type=Path, help="resultados de la tanda")


# --- CLI ----------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    sub = parser.add_subparsers(dest="modo", required=True)
    _parser_veredicto(sub)
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

    if args.modo == "veredicto-afinidad":
        try:
            return ejecutar_veredicto(args)
        except (OSError, ValueError, KeyError) as exc:  # `SinDatos` es un `ValueError`
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
