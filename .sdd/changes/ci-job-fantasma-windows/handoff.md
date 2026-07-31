# Handoff: el job de Windows puede colgarse y bloquear un merge sin límite

## Estado actual

- SDD status: `closed`
- Último gate completado: `memory`
- Revisión: PR **#87**.

## Qué cambió

`ci.yml` declara `timeout-minutes` en sus cuatro jobs y `concurrency` para cancelar el run
anterior de una rama de trabajo. El peor caso de un cuelgue pasa de **6 horas** (el default de
GitHub, que regía porque no había nada declarado) a **8 minutos y un `gh run rerun`**.

## Lo que hay que saber si vuelve a pasar

**No es nuestro código.** La API del job colgado devuelve los ocho pasos en `success` —incluido
`Complete job`— con `completed_at: null`: el runner acaba en ~86 s y lo que falta es que GitHub
cierre el job. Pasó dos veces en dos días (PRs #77 y #86) con GitHub Status en verde.

**Se descartó por ejecución** la causa que uno sospecha primero en Windows: un proceso hijo
huérfano reteniendo los handles del job. La suite corrida en Windows no deja ni un proceso nuevo,
y lo único que lanza procesos desacoplados (`update._spawn_detached`) va doblado en los tests.

**Cómo diagnosticarlo sin repetir el trabajo:** mirar los *steps*, no el reloj.

```bash
gh api repos/ZahiriNatZuke/local-delegate/actions/jobs/<job-id> \
  --jq '{status, completed_at, pasos: [.steps[] | {name, conclusion}]}'
```

Y luego `gh run cancel <run-id>` + `gh run rerun <run-id>`. **El estado va con retraso en las dos
direcciones:** la cancelación tarda en verse, y `gh run rerun --job` responde «cannot be rerun»
mientras el job siga `in_progress`.

## Decisiones que no se deducen del código

1. **Se acota el daño, no se cura la causa.** No es curable desde el repo.
2. **`main` queda fuera de `cancel-in-progress`:** allí el run es el registro de que ese estado
   pasó el CI.
3. **Sin reintento automático**, a propósito: escondería el problema en vez de acotarlo, y aquí
   interesa que se vea.
4. **Los valores salen de datos, no de intuición.** La primera versión ponía 15 min en `test`
   mirando el cuelgue; se bajó a 8 al comprobar que el peor caso real es 1 m 23 s y que el reloj
   del `timeout` corre sobre la **ejecución**, no sobre la espera en cola. Si algún día hay que
   subirlo, que sea con el dato nuevo delante.

## Siguiente acción

Ninguna. Si el cuelgue se repite, ahora falla solo en 8 minutos.

## Memoria

- Nota canónica: pendiente de escribir con la jornada del 2026-07-31.
- Sin secretos ni datos personales.
