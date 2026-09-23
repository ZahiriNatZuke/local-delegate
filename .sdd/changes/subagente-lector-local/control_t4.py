"""Control instalado (tarea 4): precedencia + una corrida por variante, con evidencia por transcript.

Archivado. En T4 corrió con la API del banco CON `oferta`; al retirar V1/V2 tras el piloto de T5
se adaptó a la actual, sin ella. Hoy las tres «ofertas» son solo etiquetas: los hooks son los
mismos en las tres corridas.
"""

import json
import random
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))
import _banco_claude as banco
import experimento_adopcion as exp

B = Path(tempfile.gettempdir()) / "banco-control-t4"
B.mkdir(parents=True, exist_ok=True)
interruptor = B / "interruptor-que-no-existe"
muestra = B / "precedencia.md"
muestra.write_text((REPO / "README.md").read_text(encoding="utf-8"), encoding="utf-8")

print("precedencia:", banco.control_de_precedencia(B, muestra, interruptor), flush=True)

rng = random.Random(4)
corridas = []
for oferta in ("v0", "v1", "v2"):
    d = B / f"control-{oferta}"
    d.mkdir(exist_ok=True)
    texto, conector, valor = exp.plantar(
        (REPO / "docs/wiki/Daemon.md").read_text(encoding="utf-8"), "md", rng
    )
    fichero = d / "manual-daemon.md"
    fichero.write_text(texto, encoding="utf-8")
    tele = d / "telemetria.jsonl"
    tele.unlink(missing_ok=True)
    settings = banco.escribir_settings(d / "settings.json", banco.env_de_tanda(tele, interruptor))
    c = banco.correr(exp.pregunta(fichero, "md"), B, settings)
    corridas.append(c)
    visto = banco.analizar(banco.leer_transcript(B, c.session_id), fichero) if c.session_id else {}
    eventos = banco.eventos_de_telemetria(tele)
    print(
        json.dumps(
            {
                "oferta": oferta,
                "error": c.error,
                "valida": banco.corrida_valida(eventos, c.session_id),
                "hecho_ok": valor in c.resultado,
                "coste": round(c.coste_usd, 3),
                "eventos": [
                    (
                        e.get("event"),
                        e.get("oferta"),
                        e.get("motivo"),
                        e.get("category"),
                        e.get("disparo"),
                    )
                    for e in eventos
                ],
                **visto,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
banco.anotar_ventana(REPO / "benchmarks" / "ventanas-excluidas.json", "control-t4", corridas)
