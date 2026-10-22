"""Decide si un run de `ci.yml` está en verde mirando los **steps**, no el estado de los jobs.

GitHub deja a veces un job en `in_progress` para siempre **con todos sus pasos terminados en
`success`**, incluido el `Complete job` que añade el propio runner, y `completed_at: null`. Le pasó
tres veces en dos días a `test (windows-latest)` —1954 s en el PR #77, 651 s en el #86 y 10+ min en
el #88, contra los 60-125 s normales— y como el ruleset exige los checks por nombre, **el merge
queda bloqueado** hasta que alguien cancela y relanza a mano.

El cuelgue es **posterior a nuestro código**: el runner acabó en ~86 s y lo que falta es que GitHub
cierre el job. Está descartado por ejecución un proceso huérfano reteniendo handles —el fallo
clásico en Windows—, y es un problema conocido de GitHub sin solución oficial
(https://github.com/orgs/community/discussions/161434).

Como los **steps sí terminan**, este script mira los steps y da por bueno un job cuyo runner llegó
al final aunque GitHub no lo haya cerrado.

**Por qué no se resuelve con `needs` + `if: always()`**, que es el patrón habitual: `needs` espera a
que el job *termine*, que es exactamente lo que aquí no pasa. El gate corre **en paralelo** con los
demás y pregunta por la API.

**Por qué `timeout-minutes` no sustituye a este gate**, aunque `ci.yml` lo declare: sí actúa —eso
se midió y se corrigió el 2026-07-31, ver el comentario de `ci.yml`—, pero tarda **20 minutos** en
cerrar el job (15 del límite más los 5 de gracia que GitHub da al runner; 13 = 8 + 5 hasta el
2026-10-13) y lo cierra como
`cancelled`, que para este gate es un **fallo**. O sea, sin el gate el merge quedaría bloqueado
igual, solo que veinte minutos más tarde y sin log. El gate da el veredicto en segundos mirando los
pasos.

Regla de decisión por job, y el orden importa:

    conclusion success o skipped .................. OK
    conclusion cualquier otra cosa ................ FALLO, sin esperar al resto
    conclusion nula (el job sigue abierto):
        algún step concluido en algo que no sea
        success o skipped ......................... FALLO
        el ÚLTIMO step listado es `Complete job`
        y concluyó en success ..................... OK  <- el job fantasma
        resto ..................................... ESPERAR

El criterio del fantasma es **el nombre del último step**, nunca contar: está comprobado contra la
API que la numeración salta (un job de Windows lista los pasos 1-5 y luego 9-11).

`Complete job` lo nombra GitHub, no nosotros: es una dependencia externa asumida. Si lo renombraran,
el gate dejaría de reconocer al fantasma y volvería a esperar hasta agotar el plazo — o sea, degrada
al comportamiento de hoy, **nunca a un falso verde**.

Qué NO cubre: `Analyze (python)` vive en `codeql.yml`, que es otro run y no se ve desde aquí; sigue
siendo un check requerido por su cuenta.

Códigos de salida:

    0  todos los jobs esperados terminaron bien (puede haber fantasmas, se nombran)
    1  al menos un job falló, se canceló o expiró
    2  se agotó el plazo con algún job sin veredicto (incluido un job que nunca apareció)
    3  no se pudo consultar la API: red, respuesta ilegible o entorno incompleto

Uso (lo llama `ci.yml`; necesita `actions: read`, y solo lee):

    GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo GITHUB_RUN_ID=123 python scripts/ci_gate.py

Con `GITHUB_STEP_SUMMARY` en el entorno el informe se escribe **también** ahí, porque un veredicto
enterrado en el log de un job no lo lee nadie.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import NamedTuple

API = "https://api.github.com"

# El propio gate, que obviamente no se espera a sí mismo. La constante la comparte el test que ata
# esta lista a `ci.yml`, para que renombrar el job no obligue a tocar dos sitios.
GATE_NAME = "ci-gate"

# Los jobs de `ci.yml`, EXPLÍCITOS y no «los que haya en el run». Preguntar por los que aparezcan
# invita al peor fallo posible aquí: consultar antes de que se creen y pasar en verde sin haber
# comprobado nada. `tests/test_ci_gate.py` ata esta tupla a los jobs que declara `ci.yml`, por
# conjuntos iguales.
#
# `install-smoke` está DELIBERADAMENTE en la lista, y eso lo convierte en bloqueante de hecho, que
# antes no lo era. Fue una decisión tomada al diseñar el gate, no un descuido, y tiene su pero: ese
# job depende de PyPI en vivo, así que un índice degradado bloqueará PRs sin que nada esté roto.
EXPECTED_JOBS = (
    "lint",
    "test (ubuntu-latest)",
    "test (windows-latest)",
    "test (macos-latest)",
    "secrets",
    "install-smoke",
    # La suite entera con el sistema en español (REQ-043, ola B0a).
    "test-lang-es",
    # Los tests del CLI en cada Python admitido (D8, ola B1a): todas las celdas bloquean.
    "cli-python-matrix (3.11)",
    "cli-python-matrix (3.12)",
    "cli-python-matrix (3.13)",
    "cli-python-matrix (3.14)",
    "cli-python-matrix (3.15)",
    # El plugin de Claude Code contra la CLI real (SDD claude-plugin-and-mods, REQ-001): bloquea en
    # los tres sistemas, como `test`.
    "plugin (ubuntu-latest)",
    "plugin (windows-latest)",
    "plugin (macos-latest)",
)

# El plazo cubre COLA + EJECUCIÓN, que no es lo mismo que el `timeout-minutes` de un job: aquel
# corre solo sobre la ejecución. Un `install-smoke` que espere runner 5 min y ejecute 10 suma 15, y
# declararlo fallo sería cambiar un bloqueo ocasional por falsos rojos. En repo público los minutos
# no se facturan y el caso normal se resuelve en segundos.
MAX_WAIT_S = 25 * 60
INTERVAL_S = 10

API_ATTEMPTS = 5
TIMEOUT_HTTP_S = 20

STEP_FINAL = "Complete job"
GOOD_CONCLUSIONS = frozenset({"success", "skipped"})

OK = 0
JOB_FAILURE = 1
TIMEOUT_FAILURE = 2
API_FAILURE = 3

WAIT = "wait"
GOOD = "good"
BAD = "bad"

#: Cómo se imprime cada estado en el resumen del job: el texto de salida sigue en español hasta
#: el frente B.
_STATE_LABELS = {WAIT: "esperar", GOOD: "bien", BAD: "mal"}


class ApiUnavailable(Exception):
    """La API no contestó nada utilizable tras agotar los intentos."""


class Verdict(NamedTuple):
    state: str  # GOOD | BAD | WAIT
    reason: str
    phantom: bool = False


def job_verdict(job: dict) -> Verdict:
    """Decide sobre un job. Función pura: todo el criterio del gate se prueba con esto."""
    conclusion = job.get("conclusion")

    if conclusion in GOOD_CONCLUSIONS:
        return Verdict(GOOD, f"conclusion={conclusion}")
    if conclusion is not None:
        # failure, cancelled, timed_out, action_required... nada de esto habilita un merge.
        return Verdict(BAD, f"conclusion={conclusion}")

    steps = job.get("steps") or []

    # Primero los pasos malos y DESPUÉS el fantasma: cuando un step falla, GitHub cierra el job con
    # su `Complete job` en success igualmente. Al revés, esto sería un falso verde de manual.
    for step in steps:
        c = step.get("conclusion")
        if c is not None and c not in GOOD_CONCLUSIONS:
            return Verdict(BAD, f"el paso '{step.get('name')}' terminó en {c}")

    if steps and steps[-1].get("name") == STEP_FINAL and steps[-1].get("conclusion") == "success":
        return Verdict(
            GOOD,
            f"el job sigue abierto ({job.get('status')}) pero el runner llegó a "
            f"'{STEP_FINAL}': {len(steps)} pasos terminados",
            phantom=True,
        )

    done = sum(1 for s in steps if s.get("conclusion") is not None)
    return Verdict(WAIT, f"{job.get('status')}, {done}/{len(steps)} pasos concluidos")


def read_jobs(repo: str, run_id: str, token: str) -> list[dict]:
    """Devuelve los jobs del run. Lanza `ApiUnavailable` si no hay forma de leerlos.

    `filter=latest` es explícito a propósito: con `all` volverían los jobs de intentos anteriores y,
    tras un `rerun`, el gate vería el intento fallido y fallaría para siempre en ese run.
    `per_page=100` evita que un job quede fuera de la primera página y no aparezca nunca.
    """
    url = f"{API}/repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "local-delegate-ci-gate",
        },
    )

    last = ""
    for attempt in range(1, API_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_HTTP_S) as r:
                data = json.loads(r.read().decode("utf-8"))
            jobs = data.get("jobs")
            if not isinstance(jobs, list):
                raise TypeError("la respuesta no trae una lista 'jobs'")
            return jobs
        except (urllib.error.URLError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            if attempt < API_ATTEMPTS:
                time.sleep(2 * attempt)

    raise ApiUnavailable(f"tras {API_ATTEMPTS} intentos: {last}")


def evaluate(jobs: list[dict]) -> dict[str, Verdict]:
    """Da un veredicto a cada job esperado. Uno que aún no existe en el run se espera, no se
    inventa."""
    by_name = {j.get("name"): j for j in jobs}
    results: dict[str, Verdict] = {}
    for name in EXPECTED_JOBS:
        job = by_name.get(name)
        if job is None:
            results[name] = Verdict(WAIT, "todavía no aparece en el run")
        else:
            results[name] = job_verdict(job)
    return results


def _report(title: str, results: dict[str, Verdict], write: Callable[[str], None]) -> None:
    mark = {GOOD: "OK  ", BAD: "FALLO", WAIT: "..."}
    write(title)
    for name, v in results.items():
        write(f"  [{mark[v.state]:<5}] {name}: {v.reason}")

    phantoms = [n for n, v in results.items() if v.phantom]
    if phantoms:
        write("")
        write(
            "Jobs dados por buenos por sus pasos, con GitHub sin cerrarlos (el «job fantasma»): "
            + ", ".join(phantoms)
        )

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### {title}\n\n")
            for name, v in results.items():
                fh.write(f"- `{name}`: **{_STATE_LABELS[v.state]}** — {v.reason}\n")
            if phantoms:
                fh.write(f"\n> Job fantasma detectado: {', '.join(f'`{n}`' for n in phantoms)}\n")
            fh.write("\n")


def wait_for_verdict(
    repo: str,
    run_id: str,
    token: str,
    *,
    read: Callable[[str, str, str], list[dict]] = read_jobs,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    write: Callable[[str], None] = print,
) -> int:
    """Espera hasta que todos los jobs esperados tengan veredicto, y devuelve el código de salida."""
    start = clock()
    while True:
        try:
            jobs = read(repo, run_id, token)
        except ApiUnavailable as exc:
            write(f"No se pudo consultar la API de Actions: {exc}")
            write("El gate falla: sin poder leer el run, no hay nada que dar por bueno.")
            return API_FAILURE

        results = evaluate(jobs)

        if any(v.state == BAD for v in results.values()):
            _report("Un job de este run no está en verde:", results, write)
            return JOB_FAILURE

        if all(v.state == GOOD for v in results.values()):
            _report("Todos los jobs esperados terminaron sus pasos:", results, write)
            return OK

        if clock() - start >= MAX_WAIT_S:
            _report(
                f"Se agotó el plazo de {MAX_WAIT_S // 60} min con jobs sin veredicto:",
                results,
                write,
            )
            return TIMEOUT_FAILURE

        sleep(INTERVAL_S)


def main(argv: list[str] | None = None) -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    token = os.environ.get("GITHUB_TOKEN", "")

    missing = [
        n
        for n, v in (
            ("GITHUB_REPOSITORY", repo),
            ("GITHUB_RUN_ID", run_id),
            ("GITHUB_TOKEN", token),
        )
        if not v
    ]
    if missing:
        print(f"Entorno incompleto, faltan: {', '.join(missing)}", file=sys.stderr)
        return API_FAILURE

    print(f"Vigilando el run {run_id} de {repo}; jobs esperados: {', '.join(EXPECTED_JOBS)}")
    return wait_for_verdict(repo, run_id, token)


if __name__ == "__main__":
    raise SystemExit(main())
