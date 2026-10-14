"""Cuanto pesa de verdad la salida de los comandos Bash, leido de los transcripts.

Es lo que quedo de la tarea T7 del cambio `salida-grande-va-a-fichero`. El plan la penso como el
gate cuantitativo de un criterio para **reescribir** comandos; cuando la medicion mostro que el
cliente ya persiste la salida grande por su cuenta, la pregunta util paso a ser otra: **cuanta
salida entra entera al contexto hoy, y cuanta de esa la cubre `bashOutputMaxChars`**.

El corpus NO se versiona: son transcripts privados con comandos y rutas. Este script los lee de
la maquina y solo imprime agregados; lo reproducible es el procedimiento, no el dato.

    uv run python scripts/dev/measure_bash_outputs.py
"""

from __future__ import annotations

import json
import pathlib

#: Por encima de esto, Claude Code guarda la salida entera en un fichero y al modelo le manda un
#: preview de 2 KB con la ruta. Es el default de `bashOutputMaxChars`, medido con cuatro tamanos.
DEFAULT_CEILING = 30_000

#: Lo que el preview le cuesta al contexto cuando la salida se persiste.
PREVIEW = 2_048

#: A partir de aqui una salida se considera cara. Sale del corpus del research.
LARGE = 8 * 1024

BANDS = (
    ("menos de 1 KB", 0, 1024),
    ("1 KB - 4 KB", 1024, 4096),
    ("4 KB - 8 KB", 4096, LARGE),
    ("8 KB - techo (entra entera)", LARGE, DEFAULT_CEILING),
    ("techo o mas (la persiste el cliente)", DEFAULT_CEILING, None),
)


def sizes() -> tuple[list[int], list[int]]:
    """(salidas no persistidas, salidas persistidas), en caracteres.

    Para una salida persistida el transcript guarda `stdout` ya cortado, asi que el tamano real
    hay que tomarlo de `persistedOutputSize`: usar el `stdout` daria el techo en todas y borraria
    justo la diferencia que se quiere medir.
    """
    root = pathlib.Path.home() / ".claude" / "projects"
    normal: list[int] = []
    persisted: list[int] = []
    for file in root.rglob("*.jsonl"):
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            # Filtro barato antes de parsear: un transcript son megas de JSON y la inmensa
            # mayoria de las lineas no son resultados de Bash.
            if '"toolUseResult"' not in line or '"stdout"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            result = event.get("toolUseResult")
            if not isinstance(result, dict) or "stdout" not in result:
                continue
            real = result.get("persistedOutputSize")
            if real:
                persisted.append(int(real))
            else:
                output = result.get("stdout") or ""
                error = result.get("stderr") or ""
                normal.append(len(output) + len(error))
    return normal, persisted


def main() -> None:
    normal, persisted = sizes()
    all_rows = sorted(normal + persisted)
    if not all_rows:
        print("No se encontro ningun resultado de Bash en los transcripts.")
        return

    print(f"Comandos Bash con resultado: {len(all_rows)}")
    print(f"Mediana: {all_rows[len(all_rows) // 2]} chars")
    print()
    print(f"{'franja':<38} {'casos':>6} {'% total':>8}")
    for label, since, until in BANDS:
        cases = sum(1 for t in all_rows if t >= since and (until is None or t < until))
        print(f"{label:<38} {cases:>6} {100 * cases / len(all_rows):>7.1f} %")

    band = [t for t in normal if LARGE <= t < DEFAULT_CEILING]
    print()
    print("La franja que HOY entra entera al contexto (8 KB - techo):")
    print(f"  {len(band)} casos, {sum(band)} chars ~ {sum(band) // 4} tokens")
    print()
    print("Lo que el cliente YA resuelve (persistido):")
    print(f"  {len(persisted)} casos, {sum(persisted)} chars ~ {sum(persisted) // 4} tokens")
    if band and persisted:
        covered = sum(persisted) / (sum(persisted) + sum(band))
        print(f"  o sea el {covered:.0%} del volumen, sin que nosotros hagamos nada")
    print()
    savings = (sum(band) - PREVIEW * len(band)) // 4
    print(f"Bajando el techo a {LARGE}: esos {len(band)} casos pasan a preview.")
    print(f"  ahorro bruto ~{savings} tokens, acumulados en TODO el historico")


if __name__ == "__main__":
    main()
