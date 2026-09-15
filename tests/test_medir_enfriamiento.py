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
        self.registro: list[dict] = []

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
        return medir_enfriamiento.medir(opciones.pop("desde", "2026-09-16"), **opciones)


@pytest.fixture
def logs(tmp_path, monkeypatch) -> Logs:
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path / "logs"))
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
    """Ida y vuelta: los eventos que escribe `Estado` son los que este script agrupa. Sin esto, los
    tests de arriba prueban el script contra un formato que yo mismo escribi a mano."""
    from local_delegate import enfriamiento

    ahora = [1_789_900_000.0]  # 2026-09-20
    estado = enfriamiento.Estado(
        logs.directorio / "enfriamiento.json",
        fallos=3,
        espera_s=120.0,
        espera_max_s=900.0,
        reloj=lambda: ahora[0],
    )
    for _ in range(3):
        estado.registrar_fallo("m", "timeout_lectura")
    ahora[0] += 121
    estado.registrar_fallo("m", "modelo")
    ahora[0] += 241
    estado.registrar_exito("m")
    registro = (logs.directorio / enfriamiento.FICHERO_EVENTOS).read_text(encoding="utf-8")
    logs.registro = [json.loads(linea) for linea in registro.splitlines()]
    medida = logs.medir()
    assert medida["episodios"] == 1
    assert medida["episodios_que_reentraron"] == 1
    assert medida["episodios_por_timeout"] == 1
