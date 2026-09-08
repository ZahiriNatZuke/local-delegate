"""Cuanto pesa de verdad la salida de los comandos Bash, leido de los transcripts.

Es lo que quedo de la tarea T7 del cambio `salida-grande-va-a-fichero`. El plan la penso como el
gate cuantitativo de un criterio para **reescribir** comandos; cuando la medicion mostro que el
cliente ya persiste la salida grande por su cuenta, la pregunta util paso a ser otra: **cuanta
salida entra entera al contexto hoy, y cuanta de esa la cubre `bashOutputMaxChars`**.

El corpus NO se versiona: son transcripts privados con comandos y rutas. Este script los lee de
la maquina y solo imprime agregados; lo reproducible es el procedimiento, no el dato.

    uv run python scripts/dev/medir_salidas_bash.py
"""

from __future__ import annotations

import json
import pathlib

#: Por encima de esto, Claude Code guarda la salida entera en un fichero y al modelo le manda un
#: preview de 2 KB con la ruta. Es el default de `bashOutputMaxChars`, medido con cuatro tamanos.
TECHO_POR_DEFECTO = 30_000

#: Lo que el preview le cuesta al contexto cuando la salida se persiste.
PREVIEW = 2_048

#: A partir de aqui una salida se considera cara. Sale del corpus del research.
GRANDE = 8 * 1024

FRANJAS = (
    ("menos de 1 KB", 0, 1024),
    ("1 KB - 4 KB", 1024, 4096),
    ("4 KB - 8 KB", 4096, GRANDE),
    ("8 KB - techo (entra entera)", GRANDE, TECHO_POR_DEFECTO),
    ("techo o mas (la persiste el cliente)", TECHO_POR_DEFECTO, None),
)


def tamanos() -> tuple[list[int], list[int]]:
    """(salidas no persistidas, salidas persistidas), en caracteres.

    Para una salida persistida el transcript guarda `stdout` ya cortado, asi que el tamano real
    hay que tomarlo de `persistedOutputSize`: usar el `stdout` daria el techo en todas y borraria
    justo la diferencia que se quiere medir.
    """
    raiz = pathlib.Path.home() / ".claude" / "projects"
    normales: list[int] = []
    persistidas: list[int] = []
    for archivo in raiz.rglob("*.jsonl"):
        try:
            texto = archivo.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for linea in texto.splitlines():
            # Filtro barato antes de parsear: un transcript son megas de JSON y la inmensa
            # mayoria de las lineas no son resultados de Bash.
            if '"toolUseResult"' not in linea or '"stdout"' not in linea:
                continue
            try:
                evento = json.loads(linea)
            except ValueError:
                continue
            resultado = evento.get("toolUseResult")
            if not isinstance(resultado, dict) or "stdout" not in resultado:
                continue
            real = resultado.get("persistedOutputSize")
            if real:
                persistidas.append(int(real))
            else:
                salida = resultado.get("stdout") or ""
                error = resultado.get("stderr") or ""
                normales.append(len(salida) + len(error))
    return normales, persistidas


def main() -> None:
    normales, persistidas = tamanos()
    todas = sorted(normales + persistidas)
    if not todas:
        print("No se encontro ningun resultado de Bash en los transcripts.")
        return

    print(f"Comandos Bash con resultado: {len(todas)}")
    print(f"Mediana: {todas[len(todas) // 2]} chars")
    print()
    print(f"{'franja':<38} {'casos':>6} {'% total':>8}")
    for etiqueta, desde, hasta in FRANJAS:
        casos = sum(1 for t in todas if t >= desde and (hasta is None or t < hasta))
        print(f"{etiqueta:<38} {casos:>6} {100 * casos / len(todas):>7.1f} %")

    franja = [t for t in normales if GRANDE <= t < TECHO_POR_DEFECTO]
    print()
    print("La franja que HOY entra entera al contexto (8 KB - techo):")
    print(f"  {len(franja)} casos, {sum(franja)} chars ~ {sum(franja) // 4} tokens")
    print()
    print("Lo que el cliente YA resuelve (persistido):")
    print(f"  {len(persistidas)} casos, {sum(persistidas)} chars ~ {sum(persistidas) // 4} tokens")
    if franja and persistidas:
        cubierto = sum(persistidas) / (sum(persistidas) + sum(franja))
        print(f"  o sea el {cubierto:.0%} del volumen, sin que nosotros hagamos nada")
    print()
    ahorro = (sum(franja) - PREVIEW * len(franja)) // 4
    print(f"Bajando el techo a {GRANDE}: esos {len(franja)} casos pasan a preview.")
    print(f"  ahorro bruto ~{ahorro} tokens, acumulados en TODO el historico")


if __name__ == "__main__":
    main()
