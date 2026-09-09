# Research: por qué no se delega al leer, medido

Fecha: 2026-09-08. Todo lo de aquí está **ejecutado**. Lo que no se pudo medir está marcado como
hipótesis, no como causa.

## De dónde sale este cambio

De una pregunta del usuario después de una sesión larga: *«¿por qué no usas el MCP cuando toca? No
es la primera vez: el sistema funciona hasta que llega a ti, que te saltas la sugerencia»*.

La respuesta que se dio primero —«me salté el aviso»— **era falsa**, y descubrirlo es el hallazgo
principal de este research.

## Hallazgo 1: el aviso no se ignoró, nunca llegó

El hook `PreToolUse/Read` (`suggest_delegate_read.py`) **está registrado y encendido** en esta
máquina (`--enable-read-hook`, argumento `--enabled` en `settings.json`). Su umbral bajo es
**32 KB**. Los ficheros de la sesión:

| Fichero leído | Tamaño | Qué hizo el hook |
|---|---:|---|
| `spec.md` | 9,5 KB | **se calla** |
| `verification.md` | 14,2 KB | **se calla** |
| `README.md` | 16,7 KB | **se calla** |
| `CHANGELOG.md` | 128,5 KB | avisa (`strong`) |

Medido ejecutando el hook con el payload real de cada uno. **Control positivo:** un `.md` de 43 KB
**sí** avisa, y el mismo con `offset/limit` se calla, como debe — o sea, la vía de medición
discrimina y las guardas funcionan.

Los cuatro avisos que sí se vieron en la sesión eran del hook de **`UserPromptSubmit`**, que
dispara por el texto del prompt y no sabe qué fichero se va a leer. Confundirlos fue el error.

> Es el patrón que este repo ya tiene escrito: **la observación estaba bien y la causa era
> inventada**. Esta vez aplicado a la autoobservación, que es la más fácil de contaminar.

## Hallazgo 2: la franja ciega, cuantificada

Sobre las **96 lecturas** registradas en `telemetry.jsonl` desde que el log guarda la extensión
(2026-08-18; las anteriores no traen el campo y **no son comparables** — al mezclarlas parecía que
había 880 lecturas «sin extensión», que era formato viejo, no ficheros sin extensión):

| Qué decide el hook | Veces |
|---|---:|
| `acotada` (offset/limit — bien callado) | 46 |
| **`pequeno` (callado por umbral)** | **24** |
| avisa (`strong` 10 + `suggest` 7) | 17 |
| `codigo` (bien callado) | 9 |

**Las 24 que calla por tamaño son `.md`, `.json` o `.txt`. El 100 %. Ninguna es código.**
Distribución: 4 entre 4–8 KB, **17 entre 8 y 16 KB**, 3 entre 16 y 32 KB.

Bajar el umbral a **8 KB** convierte **20 de esas 24** en avisos, todas del tipo correcto. Es el
mercado que la tercera medición ya había señalado —**logs y docs, no lint**—, con el número que
faltaba.

## Hallazgo 3: el mismo umbral vive en cuatro sitios

`config.py` (para el inventario de aislamiento), el literal del hook (que **no puede importar
`config`**: es stdlib pura porque se copia al HOME), su propio docstring, y la tabla de
`docs/recipes/claude-code-hooks.md`. **Nada los ataba**, que es el defecto recurrente de este repo
—dos fuentes para el mismo dato— con una vuelta de tuerca: aquí la duplicación no se puede
eliminar, solo atar. Se ató con `test_el_umbral_del_hook_de_lectura_no_tiene_dos_valores`.

## Lo que NO está medido, y por eso no se ha construido

**Si el asistente obedece el aviso cuando llega.** No se puede saber con los datos de hoy: en los
casos observados el aviso no llegó. Cualquier afirmación sobre obediencia —a favor o en contra— es
hoy una hipótesis.

De ahí el orden que decidió el usuario: **bajar el umbral primero, dejarlo correr un par de días, y
decidir el bloqueo con la medición delante.** Construir el bloqueo ahora sería pagar su coste sin
saber si hacía falta.

## Hipótesis viva, para la próxima vuelta

**«La tarea era verificar».** Verificar exige el literal —identificadores de requisito, el texto
exacto de una aserción— y ese modo de lectura se contagia al paso *anterior*, el de orientarse, que
no lo necesitaba. Si es cierta, el aviso debería depender de **para qué** se lee y no del tamaño,
que es justo lo que un hook no puede saber. N=1 y autorreportada: sirve para diseñar el siguiente
experimento, no para concluir.

## Cómo repetir la medición dentro de unos días

```bash
# 1. ¿Delegué? (el log de uso: 0 llamadas = el aviso no bastó)
python -c "import json,pathlib;from local_delegate import config; \
  p=config.LOG_DIR/'usage-202609.jsonl'; \
  print(sum(1 for l in p.read_text(encoding='utf-8').splitlines() if l.strip()))"

# 2. ¿Cuántas veces avisó el hook ya con el umbral nuevo?
#    Contar en telemetry.jsonl los eventos category=read con band != None y ts posterior al cambio.
```

**Criterio de decisión, escrito ANTES de ver el resultado** para que no se pueda acomodar después:

| Lo que se observe en un par de días | Qué significa | Qué se hace |
|---|---|---|
| El hook avisa y **hay** delegaciones nuevas | El problema era el umbral, no la obediencia | **No se construye el bloqueo.** Se cierra el cambio. |
| El hook avisa y **no hay** delegaciones | Ahora sí está medida la desobediencia | Se construye el bloqueo, con su flag activo por defecto |
| El hook **casi no avisa** | El umbral de 8 KB tampoco alcanza, o el trabajo de estos días no leyó docs | Volver a medir la distribución antes de tocar nada |

**Aviso sobre el denominador:** un par de días de trabajo *distinto* (por ejemplo, todo código) no
refuta nada. Antes de leer el resultado hay que mirar cuántas lecturas de `.md`/`.txt`/`.log` hubo:
sin ellas, la muestra no puede distinguir.
