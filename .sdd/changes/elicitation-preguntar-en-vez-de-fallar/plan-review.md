# Revisión adversarial del plan

Contra `plan.md` y `spec.md`, buscando por dónde rompe. **Cinco hallazgos, cuatro bloqueantes.**

## B-1 (bloqueante) — el plazo, tal como está descrito, no corta nada

El plan dice «`preguntar(...)` con plazo». Pero lo medido es que **la corrutina del cliente no
vuelve nunca**, y la llamada se hace con `anyio.from_thread.run(ctx.elicit, ...)` **desde un hilo
del threadpool**. Envolver eso en un `anyio.move_on_after` del lado del hilo **no funciona**: el
scope de cancelación de anyio pertenece al event loop, no al hilo que llama.

**Cómo falla:** se implementa el plazo, el test con cliente mudo pasa porque el test corta desde
fuera, y en producción la tool sigue colgada. El defecto sobrevive **con test verde**.

**Corrección exigida:** el plazo tiene que aplicarse **dentro del loop**, envolviendo la corrutina
antes de pasarla al hilo — es decir, `from_thread.run` de un *wrapper* async que ya lleva su
`move_on_after` dentro, no un `move_on_after` alrededor de `from_thread.run`. Y el test debe
comprobar que la tool **vuelve sola**, midiendo que tarda menos que el plazo, sin cortar desde
fuera. Un test que corta desde fuera no distingue las dos implementaciones.

**Medido, y sale peor de lo que decía el hallazgo** (`probe_timeout2.py`):

```
A) move_on_after alrededor de from_thread.run:
   A REVENTO con NoEventLoopError tras 0.0s
B) plazo dentro de la corrutina:
   B volvio tras 2.0s con None
```

La forma ingenua no es que no corte: **ni siquiera se puede escribir**. `anyio.move_on_after`
consulta el event loop actual y desde el hilo del threadpool no hay ninguno, así que lanza
`NoEventLoopError` al instante. Peligro añadido: como revienta rápido y el `except` de REQ-007 se lo
tragaría, el síntoma sería «nunca se pregunta» — un fallo silencioso, no un error visible.

## B-2 (bloqueante) — el caso 2 cambia el contrato de las tools, y la spec no lo dice

REQ-003 dice que un `model` inválido pasa a ofrecer los válidos y «la operación continúa» con el
elegido. Hoy ese camino devuelve **una cadena de error** y **no gasta backend**. Con el cambio, una
llamada con un parámetro equivocado puede **acabar ejecutando inferencia** — gasta GPU y tiempo — y
devolver un resultado en vez de un error.

Eso es un cambio de comportamiento de la tool, no una mejora de mensaje. Para un cliente automático
que llama con un modelo mal escrito, hoy recibe un error inmediato; mañana espera 30 s y luego
consume el backend.

**Corrección exigida:** dejarlo escrito en la spec como consecuencia aceptada **y** acotarlo: si el
mecanismo está apagado, o el cliente no puede responder, o se agota el plazo, el comportamiento es
**idéntico** al de hoy — error inmediato, sin backend. Eso ya está en REQ-006/007/008, pero la
interacción con REQ-003 hay que nombrarla, porque es donde el usuario notará la diferencia.

## B-3 (bloqueante) — `style` no pertenece a este change

El plan mete `style` (`server.py:1438`, de `local_commit_msg`) en el caso 2 junto a `model` y
`chunk`. Pero **`style` no aparece en la spec**: REQ-003 lo nombra, sí, pero el escenario de
aceptación solo cubre el modelo. Peor: `style` tiene **dos** valores (`conventional`, `plain`) y un
default sensato, así que preguntar aporta muchísimo menos que en `model`, donde la lista sale de la
configuración del usuario y es imposible de adivinar.

**Corrección exigida:** o se le escribe su escenario, o sale del alcance. **Recomendación: sacarlo**,
junto con `chunk` — mismo argumento, tres valores fijos y documentados. El caso que de verdad
justifica preguntar es `model`, porque la lista **depende de la instalación**. Menos superficie y el
valor se conserva entero.

## B-4 (bloqueante) — dos middlewares y ningún orden declarado

El plan añade un segundo middleware junto al de `clients.py`, y el SDK documenta que se listan
**«outermost-first»**. El plan no dice en qué orden van ni por qué da igual.

Aquí sí importa: si el de preguntas va por fuera, el `ContextVar` está puesto antes de que el
observador corra; si va por dentro, no. Hoy ninguno depende del otro, pero el orden es una decisión
que hay que fijar **ahora** para que nadie lo cambie después creyendo que es arbitrario.

**Corrección exigida:** fijar el orden con un comentario que diga que los dos son independientes y
que el criterio es «observar primero, habilitar después».

## O-5 (no bloqueante) — el default activado merece más que media frase

El plan justifica `LOCAL_DELEGATE_ASK` activado por defecto con «preguntar es más seguro que
fallar». Es razonable, pero conviene decir lo que implica: **un cliente que declare `elicitation` y
no atienda las preguntas verá cada fallo de backend tardar 30 s de más**. Es el peor caso y hay que
nombrarlo, no descubrirlo.

## Lo que está bien y no hay que tocar

- Las cuatro decisiones del `Approach` están **medidas**, no supuestas, y cada una tiene su sonda.
- El `ContextVar` evita tocar 15 firmas y hace que REQ-009 se cumpla por construcción en vez de por
  cuidado.
- Que `preguntar()` devuelva `None` para todos los caminos malos —no se puede, no contestan, dicen
  que no, revienta— deja los puntos de uso con una sola rama y sin forma de olvidarse de un caso.
