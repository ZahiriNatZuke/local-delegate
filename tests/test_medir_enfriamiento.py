"""El script que aplica el criterio de P-4.

Se prueba por la misma razon que `medir_adopcion.py`: es quien va a dar el resultado, y un script
que cuenta mal parece una medida. Cada regla tiene su caso y su control en el borde, porque un
umbral mal escrito (`>` por `>=`) cambia el resultado sin que nada falle.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from local_delegate import config

RAIZ = Path(__file__).parents[1]


def _cargar():
    spec = importlib.util.spec_from_file_location(
        "medir_enfriamiento", RAIZ / "scripts" / "medir_enfriamiento.py"
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["medir_enfriamiento"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


medir_enfriamiento = _cargar()


def _ts(dia: int, hora: int = 10) -> str:
    return f"2026-09-{dia:02d}T{hora:02d}:00:00+00:00"


class Logs:
    def __init__(self, directorio: Path) -> None:
        self.directorio = directorio
        self.usos: list[dict] = []
        #: Filas para `enfriamiento-eventos.jsonl` (el registro viejo, hasta la 0.34.0) y para
        #: `cooldown-events.jsonl` (el nuevo). El script lee los dos, siempre (REQ-007).
        self.registro: list[dict] = []
        self.registro_nuevo: list[dict] = []

    def fallos(self, cuantos: int, dia: int = 20, clase: str = "modelo") -> None:
        self.usos += [
            {"ts": _ts(dia), "tool": "local_summarize", "error": "http_500", "error_class": clase}
            for _ in range(cuantos)
        ]

    def desviadas(self, cuantas: int, dia: int = 20) -> None:
        self.usos += [
            {"ts": _ts(dia), "tool": "local_summarize", "fallback_class": "enfriamiento"}
            for _ in range(cuantas)
        ]

    def episodio(
        self,
        dia: int,
        modelo: str = "m",
        clase: str = "modelo",
        esperas_reentrada: tuple[float, ...] = (),
        final: str | None = "recuperado",
    ) -> None:
        hora = 10
        self.registro.append(
            {
                "ts": _ts(dia, hora),
                "modelo": modelo,
                "evento": "entra",
                "clase": clase,
                "reentradas": 1,
                "espera_s": 120.0,
            }
        )
        for numero, espera in enumerate(esperas_reentrada, start=2):
            hora += 1
            self.registro.append(
                {
                    "ts": _ts(dia, hora),
                    "modelo": modelo,
                    "evento": "reentra",
                    "clase": clase,
                    "reentradas": numero,
                    "espera_s": espera,
                }
            )
        if final is not None:
            self.registro.append(
                {
                    "ts": _ts(dia, hora + 1),
                    "modelo": modelo,
                    "evento": "limpia",
                    "reentradas": 1 + len(esperas_reentrada),
                    "espera_s": 120.0,
                    "tras_vencer": final == "recuperado",
                }
            )

    def medir(self, **opciones) -> dict:
        self.directorio.mkdir(parents=True, exist_ok=True)
        (self.directorio / "usage-202609.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in self.usos), encoding="utf-8"
        )
        (self.directorio / "enfriamiento-eventos.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in self.registro), encoding="utf-8"
        )
        (self.directorio / "cooldown-events.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in self.registro_nuevo), encoding="utf-8"
        )
        return medir_enfriamiento.medir(opciones.pop("desde", "2026-09-16"), **opciones)


@pytest.fixture
def logs(tmp_path, monkeypatch) -> Logs:
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    return Logs(tmp_path / "logs")


def _cinco_episodios(logs: Logs, reentran: int = 2, **opciones) -> None:
    for dia in range(20, 25):
        esperas = (240.0,) if dia - 20 < reentran else ()
        logs.episodio(dia, modelo=f"m{dia}", esperas_reentrada=esperas, **opciones)


# --- Los tres resultados ------------------------------------------------------------------------


def test_sin_episodios_no_es_un_exito_es_no_concluyente(logs):
    """Una ventana sin enfriamientos no mide nada, y el script no puede leerla como «se quedan»."""
    medida = logs.medir()
    assert medida["episodios"] == 0
    assert medida["resultado"] == "no concluyente"


def test_cuatro_episodios_son_no_concluyente_y_cinco_no(logs):
    logs.fallos(10)
    for dia in range(20, 24):
        logs.episodio(dia, modelo=f"m{dia}")
    assert logs.medir()["resultado"] == "no concluyente"
    logs.episodio(24, modelo="m24")
    assert logs.medir()["resultado"] == "se quedan", "con el minimo exacto ya se concluye"


def test_nueve_fallos_son_no_concluyente_aunque_haya_episodios(logs):
    _cinco_episodios(logs)
    logs.fallos(9)
    assert logs.medir()["resultado"] == "no concluyente"
    logs.fallos(1)
    assert logs.medir()["resultado"] == "se quedan"


def test_los_fallos_que_cuentan_son_los_de_la_tabla_y_nada_mas(logs):
    logs.fallos(2, clase="modelo")
    logs.fallos(3, clase="timeout_lectura")
    logs.fallos(4, clase="capacidad_o_carga")
    logs.fallos(5, clase="peticion")
    logs.usos.append({"ts": _ts(20), "tool": "local_summarize", "fallback_class": "modelo"})
    logs.usos.append({"ts": _ts(20), "tool": "local_summarize", "error": "cooldown"})
    medida = logs.medir()
    assert medida["fallos_que_cuentan"] == 2 + 3 + 1
    assert medida["fallos_al_momento"] == 1
    assert medida["operaciones_desviadas"] == 1


# --- Las reglas, cada una con su borde -----------------------------------------------------------


def test_regla_1_el_modelo_seguia_roto(logs):
    logs.fallos(10)
    _cinco_episodios(logs, reentran=4)
    medida = logs.medir()
    assert medida["R"] == pytest.approx(0.8)
    assert (medida["resultado"], medida["regla"]) == ("cambiar", 1)


def test_regla_1_no_salta_con_r_en_60(logs):
    logs.fallos(10)
    _cinco_episodios(logs, reentran=3)
    medida = logs.medir()
    assert medida["R"] == pytest.approx(0.6)
    assert medida["resultado"] == "se quedan"


def test_regla_2_la_abren_los_timeouts(logs):
    logs.fallos(10)
    for dia in range(20, 25):
        clase = "timeout_lectura" if dia < 23 else "modelo"
        esperas = (240.0,) if dia < 22 else ()
        logs.episodio(dia, modelo=f"m{dia}", clase=clase, esperas_reentrada=esperas)
    medida = logs.medir()
    assert medida["episodios_por_timeout"] == 3
    assert (medida["resultado"], medida["regla"]) == ("cambiar", 2)


def test_regla_2_salta_con_la_mitad_exacta(logs):
    """El borde de «la mitad o mas» solo existe con un numero par de episodios: con cinco, `>=` y
    `>` dan lo mismo y el mutante que los cambia sobrevivio."""
    logs.fallos(10)
    for dia in range(20, 26):
        clase = "timeout_lectura" if dia < 23 else "modelo"
        esperas = (240.0,) if dia < 22 else ()
        logs.episodio(dia, modelo=f"m{dia}", clase=clase, esperas_reentrada=esperas)
    medida = logs.medir()
    assert (medida["episodios"], medida["episodios_por_timeout"]) == (6, 3)
    assert medida["R"] == pytest.approx(2 / 6, abs=1e-3), "R fuera de las reglas 1 y 3"
    assert (medida["resultado"], medida["regla"]) == ("cambiar", 2)


def test_regla_2_no_salta_con_dos_de_cinco(logs):
    logs.fallos(10)
    for dia in range(20, 25):
        clase = "timeout_lectura" if dia < 22 else "modelo"
        esperas = (240.0,) if dia < 22 else ()
        logs.episodio(dia, modelo=f"m{dia}", clase=clase, esperas_reentrada=esperas)
    assert logs.medir()["resultado"] == "se quedan"


def test_regla_3_enfria_de_mas(logs):
    logs.fallos(10)
    _cinco_episodios(logs, reentran=0)
    logs.desviadas(15)
    medida = logs.medir()
    assert medida["R"] == 0
    assert (medida["resultado"], medida["regla"]) == ("cambiar", 3)


def test_regla_3_no_salta_con_menos_de_tres_desviadas_de_media(logs):
    logs.fallos(10)
    _cinco_episodios(logs, reentran=0)
    logs.desviadas(14)
    assert logs.medir()["resultado"] == "se quedan"


def test_regla_4_llega_a_tmax_y_vuelve_a_reentrar(logs):
    logs.fallos(10)
    logs.episodio(20, modelo="roto", esperas_reentrada=(240.0, 480.0, 900.0, 900.0))
    for dia in range(21, 25):
        logs.episodio(dia, modelo=f"m{dia}")
    medida = logs.medir()
    assert medida["episodios_que_reentran_en_tmax"] == 1
    assert (medida["resultado"], medida["regla"]) == ("cambiar", 4)


def test_regla_4_no_salta_si_llega_a_tmax_y_se_recupera(logs):
    logs.fallos(10)
    logs.episodio(20, modelo="roto", esperas_reentrada=(240.0, 480.0, 900.0))
    for dia in range(21, 25):
        logs.episodio(dia, modelo=f"m{dia}")
    assert logs.medir()["resultado"] == "se quedan"


def test_se_aplica_solo_la_primera_regla_y_las_demas_se_anotan(logs):
    logs.fallos(10)
    logs.episodio(
        20, modelo="roto", clase="timeout_lectura", esperas_reentrada=(240.0, 900.0, 900.0)
    )
    for dia in range(21, 25):
        logs.episodio(dia, modelo=f"m{dia}", clase="timeout_lectura", esperas_reentrada=(240.0,))
    medida = logs.medir()
    assert medida["regla"] == 1
    assert medida["anotadas"] == [2, 4]


# --- Que entra en la ventana y en R ------------------------------------------------------------


def test_r_ignora_los_episodios_sin_desenlace_conocido(logs):
    """Abiertos, o limpiados por un exito con `model` explicito antes de vencer: no se sabe si el
    modelo se habria recuperado, asi que no pueden contar ni a favor ni en contra."""
    logs.episodio(20, modelo="a", esperas_reentrada=(240.0,))
    logs.episodio(21, modelo="b")
    logs.episodio(22, modelo="c", final=None)
    logs.episodio(23, modelo="d", final="exito_explicito")
    medida = logs.medir()
    assert medida["episodios"] == 4
    assert medida["episodios_con_desenlace"] == 2
    assert medida["R"] == pytest.approx(0.5)


def test_el_tramo_excluido_saca_sus_episodios_y_sus_fallos(logs):
    logs.fallos(10, dia=21)
    logs.fallos(10, dia=25)
    _cinco_episodios(logs)
    completa = logs.medir()
    assert completa["resultado"] == "se quedan"
    tramo = ("2026-09-21T00:00", "2026-09-22T00:00")
    recortada = logs.medir(excluidos=[tramo])
    assert recortada["episodios"] == 4
    assert recortada["fallos_que_cuentan"] == 10
    assert recortada["resultado"] == "no concluyente"


def test_lo_anterior_a_la_ventana_no_cuenta(logs):
    logs.fallos(10, dia=10)
    for dia in (10, 11, 12, 13, 14):
        logs.episodio(dia, modelo=f"m{dia}")
    medida = logs.medir()
    assert (medida["episodios"], medida["fallos_que_cuentan"]) == (0, 0)


def test_una_reentrada_sin_su_entrada_se_ignora(logs):
    logs.registro.append(
        {
            "ts": _ts(20),
            "modelo": "m",
            "evento": "reentra",
            "clase": "modelo",
            "reentradas": 2,
            "espera_s": 240.0,
        }
    )
    assert logs.medir()["episodios"] == 0


def test_el_aviso_fuera_de_p4_salta_por_encima_del_5_pct(logs):
    logs.usos += [{"ts": _ts(20), "tool": "local_summarize"} for _ in range(18)]
    logs.usos += [{"ts": _ts(20), "tool": "local_summarize", "error": "cooldown"} for _ in range(2)]
    assert logs.medir()["fuera_de_p4_fallos_al_momento_sobre_5_pct"] is True
    logs.usos += [{"ts": _ts(20), "tool": "local_summarize"} for _ in range(20)]
    assert logs.medir()["fuera_de_p4_fallos_al_momento_sobre_5_pct"] is False


def test_lee_el_registro_que_escribe_el_modulo(logs):
    """Ida y vuelta: los eventos que escribe `CooldownState` son los que este script agrupa. Sin esto, los
    tests de arriba prueban el script contra un formato que yo mismo escribi a mano."""
    from local_delegate import cooldown

    ahora = [1_789_900_000.0]  # 2026-09-20
    estado = cooldown.CooldownState(
        logs.directorio / "cooldown.json",
        failures=3,
        wait_s=120.0,
        max_wait_s=900.0,
        clock=lambda: ahora[0],
    )
    for _ in range(3):
        estado.record_failure("m", "timeout_lectura")
    ahora[0] += 121
    estado.record_failure("m", "modelo")
    ahora[0] += 241
    estado.record_success("m")
    registro = (logs.directorio / cooldown.EVENTS_FILE).read_text(encoding="utf-8")
    logs.registro_nuevo = [json.loads(linea) for linea in registro.splitlines()]
    assert {e["event"] for e in logs.registro_nuevo} == {"enter", "reenter", "clear"}
    medida = logs.medir()
    assert medida["episodios"] == 1
    assert medida["episodios_que_reentraron"] == 1
    assert medida["episodios_por_timeout"] == 1


# --- Arranque y ventanas de prueba (test-windows-out-of-metrics, REQ-020) ------------------------


def _sin_metadatos(medida: dict) -> dict:
    """Lo que decide P-4, sin lo que solo describe como se filtro."""
    fuera = {"excluidos", "include_tests", "excluded_manual", "excluded_tests", "test_windows"}
    return {k: v for k, v in medida.items() if k not in fuera}


def test_main_de_verdad_sale_con_cero(tmp_path, monkeypatch, capsys):
    """El `main()` reventaba siempre con `AttributeError: ... 'exclude'` (evidencias/T0.md).
    Control: volver a poner `args.exclude` → este test falla."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["medir_enfriamiento.py", "--desde", "2030-01-01"])
    assert medir_enfriamiento.main() == 0
    assert "RESULTADO: no concluyente" in capsys.readouterr().out
    monkeypatch.setattr(
        sys,
        "argv",
        ["medir_enfriamiento.py", "--json", "--excluir", "2026-09-15T19:31:14,2026-09-15T19:35:14"],
    )
    assert medir_enfriamiento.main() == 0
    datos = json.loads(capsys.readouterr().out)
    assert set(datos["excluded_tests"]) == {"usage_rows", "episodes"}
    assert datos["test_windows"] == []


def test_p4_se_puede_volver_a_medir_con_la_ventana_del_fichero(logs):
    """El escenario del spec. Control: mutante «se ignora el fichero» → las dos medidas difieren."""
    from local_delegate import test_windows

    logs.fallos(10, dia=21)
    logs.fallos(10, dia=25)
    _cinco_episodios(logs)
    tramo = ("2026-09-21T00:00:00Z", "2026-09-21T23:59:59Z")
    completa = logs.medir()
    a_mano = logs.medir(excluidos=[tramo], include_tests=True)
    assert _sin_metadatos(completa) != _sin_metadatos(a_mano), "guarda: el tramo quita algo"
    test_windows.add(logs.directorio, *tramo, "P-4 fallo provocado")
    con_fichero = logs.medir()
    assert _sin_metadatos(con_fichero) == _sin_metadatos(a_mano)
    assert con_fichero["excluded_tests"] == {"usage_rows": 10, "episodes": 1}
    assert [w["removed"] for w in con_fichero["test_windows"]] == [11]


def test_include_tests_no_quita_los_tramos_de_excluir(logs):
    from local_delegate import test_windows

    logs.fallos(3, dia=21)
    logs.fallos(4, dia=22)
    test_windows.add(logs.directorio, "2026-09-22T00:00:00Z", "2026-09-22T23:59:59Z")
    m = logs.medir(excluidos=[("2026-09-21T00:00:00Z", "2026-09-21T23:59:59Z")], include_tests=True)
    assert m["excluded_manual"]["usage_rows"] == 3
    assert m["excluded_tests"]["usage_rows"] == 0
    assert m["fallos_que_cuentan"] == 4


def test_excluir_compara_instantes_y_no_cadenas(logs):
    """Con cadenas, `...01:20:05+00:00` < `...01:20:05.255Z` (el `+` ordena antes que el `.`) y la
    fila se colaba. Control: mutante que compara cadenas → este test falla."""
    logs.usos.append(
        {"ts": "2026-09-20T01:20:05+00:00", "tool": "local_summarize", "error_class": "modelo"}
    )
    m = logs.medir(excluidos=[("2026-09-20T01:20:05.255Z", "2026-09-20T01:22:31.544Z")])
    assert m["excluded_manual"]["usage_rows"] == 1
    assert m["fallos_que_cuentan"] == 0


# --- Formato viejo, nuevo y mezclado (REQ-007, ola A3) --------------------------------------------

_VIEJA_A_NUEVA = {
    "modelo": "model",
    "timeout_lectura": "read_timeout",
    "capacidad_o_carga": "capacity_or_load",
    "peticion": "request",
    "enfriamiento": "cooldown",
}


def _escenario(logs: Logs, formato: str) -> dict:
    """El mismo tramo de P-4 escrito con las clases viejas, las nuevas o mitad y mitad."""

    def clase(vieja: str, i: int) -> str:
        if formato == "viejo" or (formato == "mezclado" and i % 2 == 0):
            return vieja
        return _VIEJA_A_NUEVA[vieja]

    for i, vieja in enumerate(["modelo"] * 4 + ["timeout_lectura"] * 4 + ["capacidad_o_carga"] * 3):
        logs.fallos(1, clase=clase(vieja, i))
    for i in range(4):
        logs.usos.append(
            {"ts": _ts(20), "tool": "local_summarize", "fallback_class": clase("enfriamiento", i)}
        )
        logs.usos.append(
            {"ts": _ts(21), "tool": "local_summarize", "fallback_class": clase("modelo", i)}
        )
    for dia in range(20, 26):
        vieja = "timeout_lectura" if dia < 23 else "modelo"
        esperas = (240.0,) if dia < 22 else ()
        logs.episodio(dia, modelo=f"m{dia}", clase=clase(vieja, dia), esperas_reentrada=esperas)
    return logs.medir()


def test_el_informe_es_el_mismo_con_clases_viejas_nuevas_y_mezcladas(tmp_path, monkeypatch):
    medidas = {}
    for formato in ("viejo", "nuevo", "mezclado"):
        directorio = tmp_path / formato
        monkeypatch.setattr(config, "LOG_DIR", directorio)
        medidas[formato] = _escenario(Logs(directorio), formato)
        medidas[formato].pop("excluidos", None)
    # Guarda: el escenario llega a contar algo en cada medida que depende de la clase.
    assert medidas["viejo"]["fallos_que_cuentan"] == 12
    assert medidas["viejo"]["episodios_por_timeout"] == 3
    assert medidas["viejo"]["operaciones_desviadas"] == 4
    assert medidas["nuevo"] == medidas["viejo"]
    assert medidas["mezclado"] == medidas["viejo"]


# --- Registro de episodios viejo, nuevo y mezclado (REQ-007, ola A4) ------------------------------
#
# Desde la A4 el daemon escribe `cooldown-events.jsonl` con claves y valores en inglés; lo escrito
# antes sigue en `enfriamiento-eventos.jsonl`. La traducción de la fila se escribe aquí a mano, no
# con `legacy_names`: si no, el test compararía la tabla consigo misma.

_CLAVE_NUEVA = {
    "modelo": "model",
    "evento": "event",
    "clase": "class",
    "reentradas": "reentries",
    "espera_s": "wait_s",
    "tras_vencer": "after_expiry",
}
_EVENTO_NUEVO = {"entra": "enter", "reentra": "reenter", "limpia": "clear"}


def _fila_nueva(fila: dict) -> dict:
    nueva = {_CLAVE_NUEVA.get(k, k): v for k, v in fila.items()}
    nueva["event"] = _EVENTO_NUEVO[nueva["event"]]
    if "class" in nueva:
        nueva["class"] = _VIEJA_A_NUEVA[nueva["class"]]
    return nueva


def _episodios_de_p4(logs: Logs) -> list[dict]:
    """Seis episodios en formato viejo: tres por timeout, dos que reentran, uno sin desenlace."""
    logs.fallos(10)
    for dia in range(20, 26):
        clase = "timeout_lectura" if dia < 23 else "modelo"
        esperas = (240.0, 900.0, 900.0) if dia < 22 else ()
        final = None if dia == 25 else ("recuperado" if dia % 2 else "exito_explicito")
        logs.episodio(dia, modelo=f"m{dia}", clase=clase, esperas_reentrada=esperas, final=final)
    filas, logs.registro = logs.registro, []
    return filas


@pytest.mark.parametrize(
    "formato", ["nuevo", "mezclado_en_dos_ficheros", "mezclado_en_el_fichero_nuevo"]
)
def test_el_informe_es_el_mismo_con_el_registro_viejo_nuevo_y_mezclado(
    tmp_path, monkeypatch, formato
):
    def medida(nombre: str, reparto) -> dict:
        directorio = tmp_path / nombre
        monkeypatch.setattr(config, "LOG_DIR", directorio)
        logs = Logs(directorio)
        for i, fila in enumerate(_episodios_de_p4(logs)):
            destino, fila = reparto(i, fila)
            (logs.registro if destino == "viejo" else logs.registro_nuevo).append(fila)
        return logs.medir()

    viejo = medida("viejo", lambda i, fila: ("viejo", fila))
    # Guarda: el escenario cuenta algo en cada medida que depende del registro de episodios.
    assert viejo["episodios"] == 6
    assert viejo["episodios_por_timeout"] == 3
    assert viejo["episodios_que_reentraron"] == 2
    assert viejo["episodios_que_reentran_en_tmax"] == 2
    assert viejo["episodios_con_desenlace"] == 3
    repartos = {
        "nuevo": lambda i, fila: ("nuevo", _fila_nueva(fila)),
        "mezclado_en_dos_ficheros": lambda i, fila: (
            ("viejo", fila) if i % 2 else ("nuevo", _fila_nueva(fila))
        ),
        "mezclado_en_el_fichero_nuevo": lambda i, fila: (
            "nuevo",
            fila if i % 2 else _fila_nueva(fila),
        ),
    }
    assert medida(formato, repartos[formato]) == viejo
