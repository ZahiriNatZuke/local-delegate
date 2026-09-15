# Protocolo de medicion de modelos (F2)

Artefacto de planificacion de la fase **F2 - Catalogo de modelos** del cambio
`delegacion-precisa-y-fiable`. Cubre REQ-F2-1 a REQ-F2-6 de `spec.md`.

**Estado: escrito, sin ejecutar.** Nada de aqui se ha medido. Este documento entra al gate `plan`
**antes** de que se toque la maquina; las tareas ejecutables viven en `plan.md` (tareas 12 a 21).

**Precondiciones que puso el usuario (2026-09-12), las dos:**

1. No se arranca hasta que la otra sesion en curso libere la maquina. F2 se apodera entonces de la
   GPU y de la RAM enteras.
2. **Se avisa al usuario antes de empezar las pruebas.** La tarea 18 —montar b10909, anadir el perfil
   del driver, parar el daemon de produccion— es la primera que toca la maquina, y no se ejecuta sin
   ese aviso. Las tareas 12 a 17 son instrumentacion y no la tocan.

**Tercera version.** Dos revisiones adversariales: la primera devolvio nueve bloqueantes (mas un
decimo que aparecio al verificarlos contra el log real), y la segunda, cinco mas. Todos estan
cerrados; el registro de que cambio en cada pasada esta en la §11.

---

## 0. Por que este protocolo es tan estricto

La prueba de julio (SDD `moe-remote-routing-llamaswap-update`) descarto `gpt-oss-20b` **por fallos
del metodo, no del modelo**. Los cinco, del vault
(`projects/llms/investigacion-modelos-abiertos-2026-09.md`), y donde se cierra cada uno:

| # | Fallo de julio | Donde se cierra |
| --- | --- | --- |
| 1 | el gate de RAM medía **todo el sistema** (27-29 GiB con el modelo 100 % en GPU) | §3 (contador por proceso), CP-2 y CP-2b |
| 2 | `--n-cpu-moe 12` elegido sin barrer; con `0` daba ~121 tok/s en vez de 46 | §5.1 paso 4 (barrido obligatorio antes de medir calidad) |
| 3 | calidad sacada de **5 casos sinteticos** con puntuacion literal que penalizaba Unicode | §4 (17 casos reales congelados), §4.6, CP-3 y CP-4 |
| 4 | `reasoning_effort=low` y respuestas cortadas por `max_tokens` contadas como mala calidad | §4.6 puntos 3 y 4, §4.7 |
| 5 | los fallos a 8k y 16k eran **rechazos por contexto**, no limites del modelo | §3.5 entera: `n_ctx` fijado, presupuesto de KV y la clase `rechazo_por_contexto` |

**Regla que gobierna el resto:** ninguna medida vale si no se ha comprobado antes que el
instrumento podia dar un resultado distinto. Los controles de la §2 van **antes** de la primera
medida, no despues.

---

## 1. Entorno

### 1.1 Maquina

| Dato | Valor | Como se comprueba |
| --- | --- | --- |
| GPU | RTX 5060 Ti, 16 GB | `nvidia-smi --query-gpu=name,memory.total --format=csv` |
| Driver | 616.92 | `nvidia-smi --query-gpu=driver_version --format=csv` |
| Bus | PCIe 4.0 x8 (~16 GB/s) | `nvidia-smi -q` -> `Host Max: 4`, ancho `8x` |
| RAM | ~62 GB; ~26 GB libres tras limpiar | contador del sistema, anotado al empezar |
| Disco | 400 GB libres en `D:` (medido 2026-09-12) | los ~117 GB de la tanda caben (§5.2) |

Presupuesto de pesos: **16 GB VRAM + ~26 GB RAM ~= 40 GB**. En uso normal quedan ~2 GB de RAM
libres (99 procesos `node` y 22 `claude` de sesiones MCP abiertas): limpiar no es opcional.

### 1.2 Instalacion aparte, sin tocar lo estable

Produccion corre contra `D:\Projects\llms\llamacpp` (b9925) y su llama-swap. **No se toca.** La
medicion monta su propio par:

- `D:\Projects\llms\llamacpp-b10909\` — llama.cpp b10909.
- llama-swap v255 aparte, config propia `benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml`,
  **puerto distinto** del 9292, `--cache-ram 1024 -np 1`.
- `%APPDATA%\llama.cpp\config.ini`: b10909 lo lee **de forma global**, asi que tocarlo afecta
  tambien a la instalacion estable. Se **respalda** antes de vaciarlo y se **restaura** al cerrar
  (tarea 18). Su contenido de hoy esta **sin comprobar**: lo primero es mirarlo.

Cambios de b10909 que rompen los comandos heredados (PR #28334, 9 sep): desaparecen `--mmap`,
`--no-mmap`, `--mlock` y `--direct-io`, sustituidos por
`--load-mode auto|none|mmap|mlock|mmap+mlock|dio`; `--jinja` viene activo por defecto; los flags
viejos de especulacion pasan a `--spec-type` / `--spec-draft-n-max`.

**`--load-mode` se fija para toda la tanda y no es un detalle de arranque: decide si el contador de
memoria elegido mide algo.** Ver §3.1.

Por modelo: **Gemma 4 nunca con `--swa-full`** (OOM inmediato). Cache KV solo con parejas del mismo
tipo (`q8_0/q8_0` o `q4_0/q4_0`); las mezclas caen a un camino lento.

### 1.3 Perfil del driver, por ruta de ejecutable

«Prefer No Sysmem Fallback» esta activo sobre `D:\Projects\llms\llamacpp\llama-server.exe` (perfil
por programa en la NVIDIA App, activado por el usuario el 2026-09-12).

**El perfil se guarda por ruta.** El ejecutable de b10909 es otro fichero y **no hereda nada**: hay
que anadirle el suyo, o la tanda corre con el desbordamiento silencioso a RAM — el error 1 de julio,
repetido. Al cerrar, el perfil anadido se retira (tarea 18).

Ninguna activacion se puede leer: ni el panel lo confirma ni `nvidia-smi` expone la politica. **Solo
se comprueba por su efecto**, y eso es CP-1.

### 1.4 Estado limpio: comprobacion previa a cada tanda

Se anota el resultado de cada punto en la bitacora (§10). Una tanda que empiece con alguno en rojo
no cuenta.

1. Sesiones MCP cerradas; RAM libre >= 24 GB.
2. `nvidia-smi --query-compute-apps=pid,process_name --format=csv` **vacio**.
3. Daemon de produccion parado (tarea `LocalDelegateDaemon` detenida y el `pythonw` muerto).
4. **Un solo `llama-server.exe` vivo** durante la medida. Si aparece un segundo, la corrida se
   anula: no hay forma fiable de saber cual es el del modelo bajo prueba.
5. Sin navegador con aceleracion por hardware ni nada que pinte en la GPU.
6. Versiones anotadas: `llama-server --version`, version de llama-swap, `--load-mode` en uso.
7. Hora UTC de inicio anotada (§10, por la ventana de F1).

### 1.5 Convivencia con la ventana de medicion de F1

El bloqueo de lectura esta encendido desde el 2026-09-12 con ventana de 7 dias. Parar el backend de
produccion hace que el hook **no bloquee** (REQ-F1-10), y esas lecturas entrarian en la quinta
medicion como «no bloqueo por backend caido».

**Mitigacion:** cada sesion de medicion se anota en la bitacora (§10) con su intervalo UTC exacto, y
el analisis de la quinta medicion descarta los eventos que caigan dentro. El sesgo queda acotado y
escrito, no escondido.

---

## 2. Controles previos

Ninguno es opcional. Dos veces en este proyecto lo roto era la prueba, no el codigo.

### CP-1 — La politica del driver esta activa (positivo y negativo)

- **Positivo:** cargar un modelo que **no quepa** en 16 GB con `-ngl 99` (Qwen3.5-122B-A10B
  UD-IQ2_XXS, 36,6 GB). **Esperado: error de memoria en segundos.** Si carga y se arrastra, la
  politica no esta activa: se para todo y se arregla el perfil.
- **Negativo:** cargar `gemma3-4b`, que si cabe, y ver que carga normal. Sin esta mitad, un CP-1
  «pasado» podria ser solo un build roto que falla con todo.

**Falla CP-1 => no hay tanda.** Es el unico control con veto absoluto.

#### Resultado de CP-1 (tarea 18, 2026-09-14): pasa, despues de un veto real

- **El 122B no esta en disco.** Sustituto aprobado por el usuario: `qwen25-coder-14b` con KV f16 y
  contexto grande. **El primer sustituto no discriminaba**: a `-c 131072` la KV pide 24 576 MiB de
  una vez, y eso no cabe ni con desbordamiento (quedan ~7 GB de VRAM + ~15,5 GB compartidos). El que
  vale es **`-c 65536`: ~12 GiB de KV + 8,4 GB de pesos ~= 21 GB**, que no cabe en VRAM y si cabe
  con memoria compartida. Solo con ese la politica decide el resultado.
- **b10909 trae `--fit on` y `-ngl auto` por defecto**, que reducen capas hasta que quepa: sin
  `--fit off -ngl 99` CP-1 «pasaria» cargando a medias. Fijado en `llama-swap-pruebas.yaml`.
- **Control del control: la misma carga contra los dos ejecutables.** Medido con
  `\GPU Adapter Memory(luid_..._0x0000F722_phys_0)\Shared Usage` (reposo: ~140 MiB).

| Hora UTC | Perfil en la NVIDIA App | b10909 | b9925 (produccion) |
| --- | --- | --- | --- |
| 19:37 | entrada «nueva» que quedo apuntando a produccion | **cargo en 6,6 s, 6 071 MiB compartidos** | OOM a los 4,1 s |
| 19:42 | usuario borra la entrada y la anade de nuevo sobre b10909 | **OOM a los 3,9 s** (`cudaMalloc` 12 288 MiB) | cargo en 7,1 s, 6 124 MiB compartidos |

- **La NVIDIA App muestra los programas solo por nombre de fichero.** Anadir un segundo
  `llama-server.exe` no crea otra entrada: se queda la primera, y nada en el panel dice a que ruta
  apunta. Solo la medida lo delata. Consecuencia: **produccion queda sin perfil mientras dure la
  medicion**, y el rollback de la tarea 18 incluye volver a anadirlo y **medirlo** con esta misma
  prueba (b9925 debe dar OOM).
- De paso, la primera verificacion por efecto del perfil de produccion del 2026-09-12: **si actuaba**.

### CP-2 — El medidor mide el proceso

Cargar `qwen35-2b` y `qwen25-coder-14b` y leer la sonda con cada uno. **Esperado: numeros
claramente distintos, que se muevan al descargar el modelo.** Si dan lo mismo, o no cambian, la
sonda mide otra cosa.

En la misma pasada se averigua **que es `llamaswap_memory_used_bytes`** (el gauge que usa hoy
`MetricsSampler`): si resulta ser memoria del sistema, se degrada a dato de contexto y no entra en
ninguna decision. Es el candidato a repetir el error de julio.

#### Resultado de CP-1 negativo y CP-2 (tarea 18, 2026-09-14): pasan

Por el llama-swap de pruebas (puerto 9595), leyendo con `ProcessProbe` del repo y, en la misma
muestra, la RAM del sistema, `nvidia-smi` y los gauges de llama-swap. «Reposo» es tras `GET /unload`.

| Estado (UTC) | VRAM ded. proceso | VRAM compart. proceso | Privada proceso | Working set | RAM sistema | `nvidia-smi` | `llamaswap_memory_used` | `llamaswap_gpu_memory_used` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| reposo | — (`no_process`) | — | — | — | 13 038 | 852 | 13 035 | 852 |
| `gemma3-4b` (19:43) | 2 918 | 98 | 3 554 | 2 834 | 15 950 | 3 769 | 15 948 | 3 769 |
| `qwen35-2b` (19:44) | 3 092 | 96 | 4 269 | 3 331 | 16 471 | 3 943 | 16 454 | 3 943 |
| `qwen25-coder-14b` (19:44) | 8 838 | 108 | 9 555 | 8 641 | 21 791 | 9 689 | 21 805 | 9 689 |
| reposo | — (`no_process`) | — | — | — | 13 123 | 852 | 13 124 | 852 |

(MiB.)

- **CP-1 negativo pasa**: `gemma3-4b` carga (HTTP 200) sin desbordar (98 MiB compartidos, igual que
  cualquier proceso en reposo). Con la mitad positiva, **CP-1 pasa**.
- **CP-2 pasa**: la sonda da numeros distintos por modelo, del orden del GGUF, y vuelve a
  `no_process` al descargar.
- **`llamaswap_memory_used_bytes` es la RAM usada de TODO el sistema** (13 035 vs 13 038, 21 805 vs
  21 791), y `llamaswap_gpu_memory_used_bytes` es `nvidia-smi` del adaptador entero. Los dos quedan
  **degradados a dato de contexto**: ninguno entra en una decision. Confirma la pista de §3.4 (el
  `nvidia-smi.exe` hijo de llama-swap).
- **Hallazgo que CP-2b hereda: la RAM privada del proceso INCLUYE la VRAM reservada.** Con el 14B,
  9 555 MiB privados para 8 838 de VRAM: en WDDM la memoria de GPU cuenta en el commit del proceso.
  Asi que `PrivateUsage` no es «RAM del host» a secas, y lo que mide los expertos en RAM es la
  **diferencia** entre configuraciones, o `privada - VRAM dedicada`.

### CP-2b — El contador ve los expertos que viven en RAM

CP-2 compara dos modelos densos y **los dos escalarian aunque los dos subestimaran**. El caso que de
verdad decide es un MoE con `-ncmoe > 0`: si los pesos estan mapeados desde el GGUF, esa memoria no
es privada y **no aparece en `PrivateUsage`** — el error de julio invertido, con un modelo que no
cabe pareciendo que cabe.

Cargar un MoE con `-ncmoe 0` y luego con `-ncmoe 12`. **Esperado: la RAM del proceso sube en el
segundo caso en un orden parecido al tamano de los expertos descargados** (~0,38 GiB por capa,
calibrado en julio). Si no sube, el `--load-mode` elegido no sirve para medir y se cambia — o se
publican los dos contadores, el privado y el working set, diciendo cual es cual.

#### Resultado de CP-2b (tarea 18, 2026-09-14): el contador ve los expertos solo con `none`, y en diferencia

`gpt-oss-20b` MXFP4 (11,3 GB), mismo llama-swap de pruebas. MiB, lectura ~3 s tras cargar.

| Variante (UTC) | VRAM ded. | VRAM compart. | Privada | Working set | Privada − VRAM ded. | WS − VRAM ded. | RAM sistema |
| --- | --- | --- | --- | --- | --- | --- | --- |
| reposo (19:45) | — | — | — | — | — | — | 13 133 |
| `mmap`, `-ncmoe 0` (19:45) | 11 484 | 100 | 12 424 | 11 665 | 940 | 181 | 23 932 |
| `mmap`, `-ncmoe 12` (19:46) | 6 742 | 100 | 7 671 | 10 830 | **929** | **4 088** | 23 135 |
| `none`, `-ncmoe 0` (19:46) | 11 485 | 688 | 12 989 | 1 298 | 1 504 | — | 13 542 |
| `none`, `-ncmoe 12` (19:46) | 6 752 | **5 542** | 13 103 | 6 153 | **6 351** | — | 18 359 |

- `-ncmoe 12` saca **4 742 MiB** de la VRAM: ~395 MiB por capa, en linea con los ~0,38 GiB de julio.
- **H4 confirmada, y con la forma exacta del riesgo**: con `mmap`, la privada no ve los expertos
  (`privada − VRAM` se queda en ~930); solo el working set los recoge, y parcialmente (+3 907).
- **Con `none` si los ve**: `privada − VRAM` sube **+4 847**, lo mismo que la RAM del sistema
  (+4 817). `none` carga en ~4 s tras la primera lectura del GGUF: practicable.
- **El esperado de este control estaba mal escrito**: «la RAM del proceso sube». La privada
  **absoluta** apenas se mueve en ningun modo (+114 con `none`, −4 753 con `mmap`), porque en WDDM la
  privada incluye la VRAM reservada (resultado de CP-2) y lo que sale de la VRAM compensa lo que entra
  en RAM. La magnitud que decide es **`privada − VRAM dedicada`**. Leido al pie de la letra, el
  control habria fallado en los dos modos, o pasado con el que no sirve si se hubiera mirado el WS.
- **Trampa nueva**: con `none`, los expertos en RAM aparecen **tambien como VRAM compartida** del
  proceso (5 542): son buffers anclados de CUDA. Con `none`, «VRAM compartida > 0» **no** significa
  desbordamiento. Lo que impide el desbordamiento en la tanda es el perfil del driver (CP-1), no
  este contador.
- **Pendiente de decision (P-13, §10.1)**: `--load-mode` de la tanda y que magnitud se publica.

### CP-3 — El corpus discrimina

Piloto del corpus con el modelo mas debil del catalogo (`qwen35-2b`) y el mas fuerte
(`qwen25-coder-14b`), **3 corridas por caso**, no una: sin dispersion no hay con que separar una
diferencia real del ruido que la §7 misma da por existente.

**El rol `vision` no se puede pilotar asi, y hace falta decirlo:** ni `qwen35-2b` ni
`qwen25-coder-14b` son multimodales, de modo que correr con ellos los dos casos de imagen solo daria
error. Para `vision`, CP-3 es un **control de entrada en vez de un control de modelo**: el mismo
`qwen3-vl-8b` responde **los dos casos** con la imagen correcta y con una imagen equivocada.

**La imagen equivocada es `docs/assets/dashboard.png` en el commit `bcbe39f` (0.24.0)**, que se
congela en `fuentes/` junto a la actual, con su hash y `procedencia: congelado`; la produce la tarea
14 igual que las demas fuentes. Se elige esa y no una cualquiera porque es **el mismo dashboard con
otras cifras**: una imagen sin relacion la distinguiria cualquier cosa, y el control no diria nada.
Con esta, `leer-cifras-dashboard` tiene que bajar de verdad.

**Tres desenlaces, no dos, y el tercero hay que escribirlo antes de correrlo** —igual que las dos
causas de mas abajo—: `leer-cifras-dashboard` **tiene** que bajar, porque pide numeros y los numeros
cambiaron. `describir-dashboard` puede **no** bajar con toda la razon si sus `expected_terms` son
estructurales («panel», «ahorro», «tools»): es el mismo dashboard. Si pasa eso, la lectura correcta
no es «el caso no discrimina» sino **«el control de entrada no aplica a una descripcion
estructural»**, y entonces ese caso queda sin control de discriminacion y se dice — no se reescribe
para forzar que baje.

**Lo que este control demuestra, y lo que no:** si la puntuacion **no** baja con la imagen
equivocada —fuera del tercer desenlace de arriba—, el caso no discrimina nada y no sirve para
decidir el rol. Pero que **si** baje prueba
que el puntuador y el payload multimodal reaccionan a la entrada — **no** prueba que el caso pueda
separar `qwen3-vl-8b` de su candidato, que es lo que §7 necesita. El rol `vision` entra a la tanda
con esa limitacion escrita, no resuelta.

**Pasa si**, en cada rol con mas de un caso, **al menos un caso separa a los dos modelos por encima
de su banda de ruido** — y en `vision`, donde no hay dos modelos que comparar, si **los dos casos
bajan** de puntuacion con la imagen equivocada por encima de su banda. No se exige que ningun caso empate: dos modelos competentes daran cobertura
1,0 en los casos faciles, y eso es techo, no falta de discriminacion.

**Y CP-3 informa, por rol, si el AGREGADO separa, no solo si lo hace un caso.** Sin eso el control
valida una cosa y la §7 decide con otra: `mechanical` tiene cinco casos y **tres son de 42, 53 y 56
caracteres**, donde dos modelos competentes daran 1,0 los dos. Un agregado dominado por casos en
techo diluye hacia cero cualquier ventaja real del candidato y produce «nadie mejora al vigente» —
que es **la salida por defecto declarada** (§7). Un artefacto de composicion del corpus daria
entonces el mismo resultado que el hallazgo legitimo, y nada los distinguiria.

**Los casos que CP-3 marque en techo quedan fuera del agregado de su rol** (§7), y se anota cuantos
entraron. Si en un rol no entra ninguno, ese rol es **indecidible con este corpus** y eso se escribe
antes de la tanda, no despues.

**Si un rol no separa, hay dos causas posibles y el control tiene que distinguirlas:**

- *el corpus no puede*: los dos modelos dan salidas visiblemente distintas y la puntuacion no lo
  recoge -> se reescribe el caso;
- *la premisa era falsa*: las salidas son de verdad equivalentes, o el 2B es mejor en esa tarea
  (perfectamente posible en traducir o clasificar) -> **no se toca el caso**; se anota que la
  direccion supuesta no se cumple y se busca otro par de referencia.

Concluir lo primero sin mirar las salidas es exactamente el patron de este repo: observacion
correcta, causa inventada.

#### Resultado de CP-3 (tarea 19, 2026-09-14): no pasa, y casi siempre por el corpus

Sesion 2 de §10. `qwen35-2b` y `qwen25-coder-14b` con `-c 32768` (con 8192 los casos de 33-48k
darian `rechazo_por_contexto`), 3 corridas, respuestas guardadas en
`benchmarks/catalogo-2026-09/resultados/cp3-*.jsonl`. Veredicto de `analizar_benchmark.py cp3` y,
al lado, **lo que dicen las salidas**, que es lo que el control exige mirar antes de culpar al corpus.

| Rol | Programa | Lectura de las salidas |
| --- | --- | --- |
| `mechanical` | no pasa: 5 de 5 en techo | Salidas equivalentes de verdad. **Indecidible con este corpus**: ningun caso entra al agregado. |
| `code` | no pasa: banda 1,0, 0 de 4 admitidos | **El corpus no puede** en 3 de 4 (abajo). P-12 se materializo tal cual. |
| `long` | pasa: 1 de 4 admitido | Pasa por un solo caso y **en la direccion contraria** (2B 0,667, 14B 0). Un suelo y un caso sin puntuacion. |
| `vision` | pasa: los dos bajan | Solo `leer-cifras-dashboard` baja por la entrada; `describir-dashboard` es el tercer desenlace. |

Caso a caso, donde el programa y las salidas no dicen lo mismo:

- **`commit-diff-19k`, 0 los dos, con salidas muy distintas.** 2B: `feat(server): migrar estado de
  delegaciones a archivo compartido para visibilidad multi-proceso` (el arreglo, que es el cambio).
  14B: `chore: update version to 0.7.0` — **cierto** (el diff sube `pyproject.toml` a 0.7.0), pero
  se queda con lo accesorio y omite el arreglo. (La primera redaccion de este punto lo llamaba
  «inventado» sin mirar el diff: la misma causa inventada que este control pide evitar.) El unico
  termino, `inflight`, no lo nombra ninguno: la respuesta mejor puntua igual que la peor. *El
  corpus no puede*, y la premisa de direccion tampoco se cumple aqui.
- **`explicar-metrics-15k` y `explicar-install-20k`**: las dos explicaciones son razonables y los
  terminos son funciones privadas (`_log_files`, `is_simulated_home`...) que una explicacion en
  prosa rara vez nombra. El 14B da 0 / 1 / 1 en `explicar-metrics` segun si llega a listar
  helpers (el 1 viene del reintento con 1 400 tokens): esa dispersion es la que pone la banda del
  rol en 1,0. *El corpus no puede.*
- **`boilerplate-156`, techo con codigo roto en los dos**: el 2B usa `re` sin importarlo y lee
  `group(5)` de un patron con cuatro grupos; el 14B parte por espacios y no parsea `1h30m`. La
  cobertura de terminos no ve si el codigo funciona.
- **`resumen-md-10k`**: el 2B nombra `UserPromptSubmit` y `PreToolUse`; el 14B describe los ficheros
  de hooks sin nombrar los eventos. Separa, pero a favor del pequeno, y la lectura lo sostiene.
- **`resumen-changelog-43k`, 0 los dos: un suelo.** Los terminos son numeros de version y el prompt
  («resumen en prosa, 150 palabras») no los pide; ninguno los da. Simetrico al techo, y este
  protocolo no lo preveia: mide un requisito que el caso no plantea.
- **`lint-33k`, las 36 respuestas truncadas, tambien el reintento con 992 tokens.** El 2B **entra
  en bucle** (`**D102 (Docstrings):** 1 archivo.` decenas de veces); el 14B lista regla a regla y
  se queda sin tokens. Por §4.7 punto 3 truncado no puntua, asi que el caso sale «sin
  puntuacion»: **el peor fallo posible, un bucle que no termina nunca, no cuenta como 0**. Defecto
  del runner/§4.7, no del corpus.
- **`describir-dashboard`, tercer desenlace.** Con la imagen de `bcbe39f` da 0,75 (falta `computo`:
  escribe «calculo»); con la correcta, 1,0 en las validas **pero 0,75 en la corrida anulada**. La
  bajada es eleccion de palabra, no reaccion a la entrada: el caso queda **sin control de entrada**.
- **`leer-cifras-dashboard` pasa limpio**: con la imagen vieja lee `v0.24.8, 24/7 23:12` y cae por
  `forbidden_terms`; con la correcta, `29/8 05:01`.

**Defecto del runner encontrado de paso**: el comentario de `benchmark.py` dice que una corrida
anulada por la sonda «se repite», y no se repite. La primera corrida de cada modelo (arranque,
`process_changed`) se quedo con 2 corridas validas, no 3.

#### Correccion del corpus tras CP-3 (tarea 19, 2026-09-14)

Criterio, fijado **antes** de mirar que daria cada modelo: un termino esperado es algo que **la
tarea pide nombrar**, y sale de la fuente **por una regla escrita**, nunca de las salidas del
piloto. Opciones aprobadas por el usuario para `commit-diff-19k` y el changelog. Todas las reglas
tienen control positivo en `tests/test_corpus.py`.

| Caso | Antes | Ahora | Regla |
| --- | --- | --- | --- |
| `commit-diff-19k` | `inflight` | `inflight`, `inflight_snapshot`, `inflight.json`, `FileLock`, `/api/inflight` | identificadores entre backticks de la **primera entrada «Fixed» que el propio diff anade al CHANGELOG**: el cambio nombrado por su autor; fuera privados (`_x`) y comandos con espacios; de una ruta a fichero, el nombre |
| `explicar-metrics-15k` | 3 primeros `def` (privados) | las 7 rutas `GET /api/...` | lo que el **docstring del modulo** declara de si mismo: sus rutas |
| `explicar-install-20k` | 3 primeros `def` (privados) | `settings.json`, `CLAUDE.md`, `AGENTS.md`, `.bak`, `--dry-run` | idem: los ficheros y opciones que el docstring dice que toca |
| `resumen-changelog-43k` -> **`resumen-changelog-7k`** | `0.27.0`, `0.26.0`, `0.25.0` | `local_boilerplate`, `output_policy.py`, `output_stats.py`, `emit_updated_input`, `suggest_lint_summary.py`, `doctor` | **fuente nueva**: solo las secciones 0.27.0 y 0.26.0 (6 952 chars); terminos, los identificadores de los **titulares en negrita** |

- **Por que dos secciones y no una:** la 0.27.0 sola pesa 5 507 chars, bajo `LONG_INPUT_CHARS`
  (6 000), y produccion la mandaria a `mechanical`: la regla 1 de §4.4 la sacaria de `long`. Con
  tres se colaria un termino sin sentido (`ext`). Las dos secciones son byte a byte las que abrian
  la fuente congelada anterior, y `long` conserva `extraer-uvlock-48k` y `lint-33k` como casos
  grandes. Se pierde un caso de 43k de resumen: un resumen de 150 palabras de 43k no tiene un
  conjunto de terminos objetivo, y eso fue lo que el suelo mostro.
- **Mas terminos por caso** (5-7 frente a 1-3) dan granularidad a la banda: es la opcion (c) de
  P-12, aplicada a los casos que la tenian en 1. **P-12 no se da por resuelta**: se decide con la
  salida del piloto repetido.

**Lo que NO se toca, y por que:**

- **`mechanical`**: las salidas son equivalentes de verdad. Es la segunda causa de CP-3 (la premisa),
  que dice «no se toca el caso». Que quedara indecidible por techo era de §7, no del corpus, y se
  arregla en §7 (abajo).
- **`lint-33k`**: su fallo era del runner (el truncado repetido no puntuaba); arreglado abajo.

#### Runner, `boilerplate` y §7 tras CP-3 (tarea 19, 2026-09-14): decisiones del usuario

1. **Truncado repetido puntua 0.** Si tras doblar `max_tokens` sigue en `finish_reason: length`, la
   corrida puntua `quality: 0` con `zero_by: truncado_repetido`, y el analisis la cuenta. La primera
   truncada sigue sin puntuar (§4.7 punto 3). Antes salia «sin puntuacion» y caia del agregado: el
   bucle del 2B en `lint-33k` no le costaba nada.
2. **La corrida anulada se repite de verdad**, con los mismos `max_tokens`, hasta
   `MAX_ANNUL_RETRIES` = 2 veces. Cada intento lleva `retry_reason` (`anulada` o `truncado`), y el
   analisis juzga la corrida por su **ultimo intento**: descarte, estado termico y calidad. Un
   intento anulado que se repitio bien ya no descarta ni bloquea al candidato (§7 condicion 2).
3. **`boilerplate-156` se puntua ejecutando el codigo generado** (§4.7 punto 6). Cinco
   comprobaciones sacadas de la especificacion: los tres ejemplos (con tipo `int`) y dos formatos
   invalidos que deben lanzar `ValueError`. Calidad = minimo de cobertura y proporcion que pasa.
   CP-4 gana una **sexta pareja**, senal `ejecucion`: la misma funcion con `* 60` y con `* 61` en
   los minutos, validada por un oraculo que ejecuta en proceso sin compartir codigo con el arnes.
4. **§7, rol con todos los casos en techo: gana el mas rapido.** Si CP-3 dejo fuera por techo
   **todos** los casos del rol, no es indecidible sino un empate. La calidad se compara con todos
   los casos de la tanda —un candidato que ya no da 1,0 pierde por calidad— y dentro de la banda
   deciden los desempates: techo, luego velocidad. Si algun caso no separo por otra razon, el rol
   sigue indecidible. Con condiciones 2 y 3 igual que siempre.
- **`resumen-md-10k`, `describir-dashboard`, `leer-cifras-dashboard`**: sus terminos ya piden lo que
  la tarea pide; `describir` queda sin control de entrada, como se escribio.

**Siguiente: repetir el piloto de CP-3 entero** (P-9 resuelta), con el corpus y el runner nuevos,
antes de la tanda. Toca otra vez la maquina: mover el perfil del driver a b10909 y medirlo.

#### Segundo piloto de CP-3 (sesion 3, 2026-09-14): pasa en tres roles, y dos casos siguen sin poder

Sesion 3 de §10, perfil medido antes. Mismos modelos, `-c 32768`, 3 corridas, corpus y runner de la
correccion de arriba; respuestas en `resultados/cp3b-*.jsonl`, veredicto en `cp3b-texto.json` y
`cp3b-vision.json`. Piloto 23:00:36-23:10:30 UTC. Las anuladas por arranque **se repitieron** (el
arreglo funciona); `lint-33k` trunco dos veces en todas las corridas de los dos modelos.

| Rol | Programa | Lectura de las salidas |
| --- | --- | --- |
| `code` | pasa: banda 0,143, 3 de 4 admitidos, agregado 0,362 contra 0,800 | Separa de verdad en `explicar-metrics-15k` y `boilerplate-156`. `commit-diff-19k` sigue en 0 los dos. |
| `long` | pasa: banda 0, 2 de 4 admitidos, agregado 0,417 contra 0,500 | Uno separa a favor del grande (changelog) y otro a favor del pequeno (`resumen-md-10k`); `extraer-uvlock-48k` en techo, `lint-33k` en suelo. |
| `mechanical` | **no pasa**: 5 de 5 en techo | Igual que el primer piloto. Ver la contradiccion con §7 punto 4, abajo. |
| `vision` | pasa: los dos bajan | Solo `leer-cifras-dashboard` baja por la entrada; `describir-dashboard` vuelve a ser el tercer desenlace. |

Caso a caso, mirado contra la fuente:

- **`explicar-metrics-15k` separa bien (0,286 contra 1,0).** El 2B dice «tres endpoints principales» y
  nombra dos; el 14B lista las siete rutas. La correccion del corpus hizo lo que tenia que hacer.
- **`boilerplate-156` separa bien (0 contra 0,8), y ahora por ejecucion.** El 2B usa `re` sin
  importarlo y lee `group(5)` de un patron de cuatro grupos: 0 de 5. El 14B parte por espacios y
  falla solo `1h30m`: 4 de 5. La cobertura de terminos daba 1,0 a los dos.
- **`resumen-changelog-7k` separa bien (0,167 contra 1,0), y la cobertura coincide con la exactitud.**
  El 2B escribe que `local_boilerplate` «elimina la dependencia de rutas absolutas», y la fuente
  dice lo contrario (exige ruta **absoluta**, linea 6); el 14B lo da bien y nombra los modulos
  retirados.
- **`explicar-install-20k` separa a favor del pequeno (0,8 contra 0,6).** Las dos explicaciones son
  correctas; el 14B nombra `.bak` y `--dry-run` en la corrida truncada y los pierde al reintentar.
  Premisa de direccion no cumplida: **no se toca** (segunda causa de CP-3).
- **`resumen-md-10k` otra vez a favor del pequeno (0,667 contra 0).** El 2B nombra los eventos
  `UserPromptSubmit` y `PreToolUse`; el 14B nombra los ficheros `suggest_delegate_*.py`. Ninguno
  nombra `LD_HOOK_READ_BLOQUEAR` (seccion propia en la linea 44 de la fuente). Misma lectura que en el
  primer piloto: premisa falsa, **no se toca**.
- **`commit-diff-19k`: 0 los dos, con los terminos nuevos.** Salidas identicas al primer piloto: 2B
  `feat(server): migrar estado de delegaciones a archivo compartido...` (el cambio de verdad, sin
  identificadores), 14B `chore: update version to 0.7.0 in CHANGELOG, pyproject.toml, and uv.lock`
  (cierto y accesorio). **La correccion no alcanzo**: un asunto de <=72 caracteres rara vez lleva
  identificadores, y el cuerpo es opcional; ninguno lo escribe. *El corpus no puede*, y la direccion
  vuelve a favorecer al pequeno. **Pendiente del usuario** (abajo).
- **`lint-33k`: 0 los dos por `truncado_repetido`, con salidas muy distintas.** El 14B cumple
  «agrupados por archivo» literalmente, con conteos que cuadran con la fuente, y no le caben 14
  archivos y 48 reglas en 992 tokens. El 2B agrupa por regla y **se inventa los conteos**: «T201: 10
  archivos (3 por archivo)», y la fuente tiene 5 archivos y 101 ocurrencias; «CPY001: 10 archivos»,
  y son 14. Ya no entra en bucle. El puntuador no ve conteos inventados y el formato pedido (por
  archivo, 200 palabras) no cabe con esta entrada: *el corpus no puede*. **Pendiente del usuario.**
- **`leer-cifras-dashboard` pasa limpio (0,667 contra 0).** Con la imagen correcta lee `v0.27.8 /
  29/8 05:01`; con la de `bcbe39f`, `v0.24.8, 24/7 23:12` y cae por `forbidden_terms`. **Los terminos
  son correctos**: las dos imagenes dicen `v0.27.0` y `v0.24.0` en el badge (comprobado a ojo); el
  modelo lee el ultimo 0 como 8 en las dos. El 0,667 es un error real de lectura, no del corpus.
- **`describir-dashboard`, tercer desenlace otra vez.** Correcta 1,0 (la corrida 1 se anulo con 0,75 y
  al repetirse dio 1,0); control 0,75 porque escribe «calculo» donde las dos imagenes rotulan
  «computo». Eleccion de palabra: sigue **sin control de entrada**.

**Tres hallazgos que no son de un caso:**

1. **`mechanical` contradice §7 punto 4.** CP-3 exige que al menos un caso separe por rol, y el
   programa lo marca «no pasa»; §7 punto 4 (aprobado tras el primer piloto) dice que un rol todo en
   techo **no** es indecidible sino un empate que se decide por velocidad. Dos lecturas para el mismo
   dato: el criterio de CP-3 no se actualizo con la decision. Se resuelve escribiendolo, no
   repitiendo.
2. **La banda de ruido casi no mide ruido (P-12).** Con `seed` 42 y **temperatura 0** (§5.3; el runner
   la fuerza en `benchmark.py`, aunque el caso guarde la de produccion, 0,2 en casi todas) las tres corridas
   dan **la misma respuesta byte a byte** (`response_sha256` del ultimo intento): el 2B en los 13 casos
   de texto, el 14B en 8 de 13 (los otros 5 tienen dos variantes, y solo en `explicar-metrics-15k`
   cambia la puntuacion, por un truncado). `long` y `mechanical` tienen banda 0
   y la de `code` (0,143) sale de un reintento por truncado, no de variacion del modelo. Con banda 0
   cualquier diferencia «separa». **La premisa de §5.3 no se cumple**: el no determinismo de llama.cpp
   «cuando agrupa peticiones» no aparece con `-np 1`, que no agrupa. `puede_disparar` da `true` en `code` y `long`, pero por esta razon,
   no porque la granularidad del corpus alcance. P-12 cambia de forma: la pregunta ya no es solo la
   granularidad, es si las 3 corridas miden algo con semilla fija.
3. **Los dos casos que no pueden son del mismo tipo:** la puntuacion por terminos no ve si un conteo
   es verdad (`lint`) ni premia describir el cambio sin sus identificadores (`commit`). El protocolo
   ya tiene la senal que si lo veria en `boilerplate`: comprobar contra la fuente.

#### Decisiones del usuario tras el segundo piloto (2026-09-14), en el orden en que se aplicaron

Recomendadas con las salidas delante y **antes** de la tanda; aprobadas las cuatro. Ninguna mira que
modelo gana: cambian lo que se mide, no a quien favorece.

1. **(Hallazgo 1) `mechanical`: CP-3 dice lo mismo que §7 punto 4.** Un rol cuyos casos estan
   **todos** en techo pasa CP-3 como **empate en techo** (`empate_en_techo: true` en el JSON; el informe
   dice «pasa por empate en techo»), y §7 lo decide por velocidad. Si un solo caso no separa por otra
   razon, sigue sin pasar. No aplica al control de entrada: ahi 1,0 con la imagen equivocada es que
   el caso no reacciona. Test y mutante muerto en su assert.
2. **(Hallazgo 2, P-12) Temperatura de produccion y semilla por corrida.** La causa no era la
   semilla sino la **temperatura 0 forzada** por el runner (§5.3 corregida, con su premisa refutada
   escrita). Ahora cada peticion lleva la `temperature` que el corpus capturo de la tool real y
   `seed + run - 1`, la misma en los reintentos de la corrida; las dos van al registro. Dos tests y
   dos mutantes muertos en su assert.
3. **(`lint-33k`) Conteos contra la fuente y una entrada donde el formato cabe.** Senal nueva (§4.7
   punto 7) con su pareja de CP-4, y la fuente pasa a **`lint-9k`**: los 5 primeros archivos enteros
   de ruff (8 589 chars; sigue en `long` y en una llamada). Regla del recorte escrita: archivos
   enteros hasta 9 000 chars, nunca uno a medias. **Para el backlog de F3:** el prompt de
   `local_lint_summary` («agrupados por archivo, 200 palabras») no cabe con entradas grandes en
   produccion; eso se arregla en la tool, no en el benchmark.
4. **(`commit-diff-19k`) Fuera de la puntuacion automatica, a la revision a ciegas** (§4.7 punto 8).
   No se toca el prompt: el corpus copia la tool real, y exigir cuerpo mediria algo que produccion no
   hace. **Resultado de F2 ya escrito:** `qwen25-coder-14b`, el modelo de produccion de
   `local_commit_msg`, se quedo con el bump de version y omitio el arreglo en las 6 corridas de los
   dos pilotos.

**Siguiente:** repetir el piloto de CP-3 una vez con las cuatro aplicadas (la banda cambia con la
temperatura, y `lint-9k` es un caso nuevo), con el setup de medicion que sigue montado.

### CP-4 — El puntuador separa

Por cada senal de puntuacion que **se pueda ejercitar con texto** existe un caso con dos respuestas
de referencia escritas a mano (`reference_ok` y `reference_bad`): cobertura, termino prohibido,
formato JSON y normalizacion Unicode. Son **cinco casos, diez textos**, no los treinta y cuatro que
saldrian de hacerlo con todos; el control valida el puntuador, no el corpus.

**`truncado` no entra aqui, y hay que decirlo:** no es una propiedad del texto sino del
`finish_reason` que devuelve el backend (§4.7 punto 3). Ningun par de textos escritos a mano lo
dispara. Esa senal se prueba **inyectando `finish_reason: "length"`** en un test unitario del
puntuador (tarea 16), no con una referencia.

Pasa si el puntuador separa cada pareja **y lo hace por la senal correcta**: si la mala cae por
`json_valid` cuando el defecto plantado era un hecho falso, acierta por la razon equivocada y no
vale. Para poder comprobarlo, el JSONL guarda **que componente puso la calidad a 0**.

#### Resultado de la tarea 15 (2026-09-14): las cinco parejas

«Formato JSON» son **dos** senales separables —que el texto sea JSON y que traiga los campos—, y
separarlas es lo que hace que cinco casos cubran cinco senales en vez de cuatro con una repetida:

| Senal | Caso | Defecto plantado en la respuesta mala | La pareja difiere en |
| --- | --- | --- | --- |
| cobertura | `resumen-md-2k` | «pull request» cambiado por «merge commit» | cobertura (y la literal) |
| termino prohibido | `leer-cifras-dashboard` | anade la version vieja, 0.24.0 | prohibido |
| JSON valido | `extraer-toml-2k` | comillas simples: los mismos datos, JSON invalido | JSON valido (y campos, que sin JSON no existen) |
| campos JSON | `extraer-uvlock-48k` | la clave `primer_paquete` renombrada, mismo valor | campos |
| Unicode | `describir-dashboard` | «cómputo» cambiado por «cálculo» | cobertura normalizada, **no** la literal |

Cada pareja tiene **exactamente la misma longitud**. Las dos de imagen llevan respuestas de texto:
CP-4 valida el puntuador, que solo ve texto, no el modelo de vision.

Que cada pareja difiera **solo** en su senal no lo decide el puntuador de la tarea 16 —que es lo
que CP-4 va a validar—, sino un oraculo aparte en el constructor (`senales`). Si una pareja difiere
en una senal de mas, o la buena no es buena, o las longitudes no cuadran, **el corpus no se
escribe**; y `tests/test_corpus.py` repite la comprobacion sobre el JSON versionado, asi que una
referencia retocada a mano tambien cae.

Dos precisiones para la tarea 16, que esta seccion dejaba implicitas:

- **La normalizacion de §4.7 es NFKD, quitar las marcas combinantes, y `casefold`.** NFKD solo no
  basta: descompone la «ó» en «o» mas un acento suelto, y «cómputo» sigue sin casar con «computo».
- **La pareja de Unicode es la unica donde la cobertura literal NO cambia**: la buena solo acierta
  si se normaliza. Un puntuador literal puntuaria las dos igual de mal, y CP-4 lo cazaria. Para
  eso `describir-dashboard` gana el termino esperado `computo`, escrito sin acento a proposito
  frente a un panel que dice «cómputo».

---

## 3. Que se mide, y con que contador

REQ-F2-3 es explicito: **memoria del proceso, no del sistema**.

| Magnitud | Fuente | Por que esa y no otra |
| --- | --- | --- |
| RAM del proceso | `PrivateMemorySize64` de `llama-server.exe`, **y siempre tambien el working set** (P-11) | el *working set* sale inflado por el GGUF mapeado; la RAM del sistema fue el error 1 de julio. Los dos salen de la misma llamada; CP-2b decide cual se publica |
| VRAM dedicada | `\GPU Process Memory(pid_<pid>_*)\Dedicated Usage` | es por proceso; `nvidia-smi` en WDDM suele dar «Not Supported» por proceso |
| **VRAM compartida** | `\GPU Process Memory(pid_<pid>_*)\Shared Usage` | si crece, hay desbordamiento a RAM: ver §3.2 |
| Velocidad | `timings` de la respuesta + latencia del cliente | discrepan cuando llama-swap esta cargando, y esa diferencia importa |
| Tokens | `usage` | para separar razonamiento de salida util |
| Corte | `finish_reason` | `length` marca **truncado**, no mala calidad |
| Contexto | §3.5 | un rechazo por contexto es su propia clase |
| Calidad | §4.6 | automatica + revision humana; la automatica no decide sola |

Los gauges de llama-swap (`/metrics`) se siguen recogiendo como contexto y **no deciden nada** hasta
que CP-2 diga que miden.

### 3.1 `--load-mode`, y por que aparece aqui y no en «arranque»

`PrivateMemorySize64` cuenta memoria **privada**. Con los pesos mapeados desde el GGUF
(`--load-mode mmap`, que es lo que hacia el comportamiento por defecto de siempre), esas paginas son
respaldadas por fichero y **no son privadas**: los expertos de un MoE que viven en RAM del host no
apareceran en la cuenta.

**Decision: la tanda corre con `--load-mode none`** (los pesos se leen a memoria anonima), que es lo
que hace que el contador elegido vea lo que tiene que ver. El coste es un arranque mas lento, y el
arranque no se esta midiendo.

**Si `--load-mode none` resulta impracticable** (tarea 12 lo comprueba), la alternativa es publicar
los **dos** contadores —privado y working set— con una frase que diga cual es cual y por que
difieren. Lo que no se hace es publicar uno solo sabiendo que subestima.

### 3.2 Anulacion de corridas, y el caso que anula mas que una corrida

Una corrida se descarta y se repite si durante ella otro proceso aparece en
`nvidia-smi --query-compute-apps`, o si aparece un segundo `llama-server.exe`, o si llama-swap
cambia de modelo a mitad.

**`Shared Usage` creciente es otra cosa.** Si CP-1 esta en verde, el desbordamiento a RAM deberia
ser imposible: el driver tendria que dar OOM. Que crezca significa que **CP-1 ha dejado de valer**,
y entonces no se cae una corrida: se cae **todo lo medido desde el ultimo CP-1 en verde**. Se
re-verifica CP-1 y se repite ese tramo. Repetir solo la corrida produciria un numero igual de
invalido.

Las corridas descartadas **se anotan igual** en el JSONL, con `descartada` y el motivo. Un descarte
silencioso es indistinguible de un caso que no se corrio.

### 3.3 Muestreo

La sonda toma una lectura **sincrona antes y despues de cada peticion**, ademas del flujo continuo a
1 Hz para los picos. Asi una corrida corta —el caso de `clasificar-53` puede cerrarse en menos de un
segundo— nunca se queda sin ninguna medida de memoria. Una corrida con **cero muestras** se anula y
se repite; no se publica vacia.

El PID se reresuelve cuando llama-swap cambia de modelo. Un `typeperf` ya arrancado enumera las
instancias al inicio y **no vera el PID nuevo**, asi que el flujo se relanza al detectar el cambio.
La tarea 12 comprueba que eso funciona antes de que nadie escriba codigo encima.

### 3.4 Hipotesis a verificar por ejecucion

Sin comprobar en esta maquina cuando se escribieron. La tarea 12 las verifico **antes** de escribir
la sonda: **1 a 3 confirmadas con correcciones, 4 sin verificar** (resultado al final de esta
seccion; lo pendiente es P-11). En este repo
un pendiente es una hipotesis: 7 de 18 cayeron en la ultima auditoria, siempre con la observacion
correcta y la causa inventada.

1. Que los contadores `GPU Process Memory(*)` existen con ese nombre y se leen sin elevar.
2. Que `PrivateMemorySize64` sale por `ctypes` (`GetProcessMemoryInfo` ->
   `PROCESS_MEMORY_COUNTERS_EX.PrivateUsage`) sin dependencias nuevas.
3. Que `typeperf` transmite en continuo a 1 Hz y se puede relanzar al cambiar el PID (§3.3).
4. Que `--load-mode none` es practicable y hace que el contador vea los expertos (§3.1, CP-2b).

**Sin dependencias nuevas a proposito:** `ctypes` y `typeperf` son stdlib y sistema. Meter `psutil`
obligaria a una auditoria de Socket por una sonda de un solo uso.

#### Resultado de la tarea 12 (2026-09-13)

Ejecutado sin elevar (`elevado=False`, usuario `DESKTOP-LRNOJ3V\Yohan`), sin `llama-server.exe` vivo
(llama-swap en reposo), sin parar el daemon y **sin cargar nada en la GPU**: el unico uso de GPU fue
un proceso de prueba que abre un dispositivo D3D11 **sin reservar recursos** (11 MiB de
`Dedicated Usage`) durante 8-12 s. Scripts en el scratchpad de la sesion, fuera del repo.

| # | Hipotesis | Resultado |
| --- | --- | --- |
| 1 | Contadores `GPU Process Memory` con ese nombre, sin elevar | **Confirmada, con dos correcciones** |
| 2 | `PrivateUsage` por `ctypes`, sin dependencias | **Confirmada**, con control positivo y negativo |
| 3 | `typeperf` a 1 Hz por tuberia y relanzable al cambiar el PID | **Confirmada, con tres detalles de parseo** |
| 4 | `--load-mode none` practicable y que el contador vea los expertos | **NO verificada**: exige b10909 y cargar un MoE |

**H1 — confirmada, con dos correcciones.**

- **La instancia no es `pid_<pid>`: es `pid_<pid>_luid_<luid>_phys_0`**, y un mismo PID tiene una
  instancia **por adaptador** (hasta tres). Hay tres LUID en la maquina; la NVIDIA es
  `0x00000000_0x0000F722`, identificada porque su `GPU Adapter Memory\Dedicated Usage` da
  997 896 192 B = 951,7 MiB con `nvidia-smi` diciendo 942 MiB. La sonda **filtra por LUID**, o
  mezcla la VRAM de la iGPU. La ruta con comodin parcial `pid_<pid>_*` si funciona.
- **El contador por proceso no es sumable ni equivale a residencia en VRAM**: `dwm` (pid 1556)
  declara **8,79 GiB** de `Dedicated Usage` en la NVIDIA mientras el adaptador entero usa 941 MiB.
  No invalida medir `llama-server.exe` —un proceso de computo, no el compositor—, pero hace que CP-2
  **no sea opcional**: el nombre del contador no garantiza lo que mide.
- Confirmado de paso: `nvidia-smi` da `[N/A]` por proceso en WDDM, como decia la tabla de §3.

```text
> typeperf -qx "GPU Process Memory"   (169 lineas, sin elevar)
   32 Dedicated Usage | 32 Local Usage | 32 Non Local Usage | 32 Shared Usage | 32 Total Committed
  110 luid_0x00000000_0x0000F722 | 35 luid_0x00000000_0x00014FF6 | 15 luid_0x00000000_0x0001506D

> typeperf "\GPU Adapter Memory(*)\Dedicated Usage" -sc 1
"(PDH-CSV 4.0)","...(luid_0x00000000_0x0000F722_phys_0)\Dedicated Usage","...(luid_0x00000000_0x00014FF6_phys_0)\Dedicated Usage","...(luid_0x00000000_0x0001506D_phys_0)\Dedicated Usage"
"09/13/2026 21:37:04.706","997896192.000000","0.000000","202113024.000000"

> nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version --format=csv
NVIDIA GeForce RTX 5060 Ti, 16311 MiB, 942 MiB, 616.92
> nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
9268, ...\CrossDeviceResume.exe, [N/A]
9080, C:\Windows\explorer.exe, [N/A]
(14 procesos, todos [N/A])

> typeperf "\GPU Process Memory(pid_1556_*)\Dedicated Usage" ... "\GPU Adapter Memory(luid_..._0x0000F722_phys_0)\Dedicated Usage" -sc 2
   (pid 1556 = dwm)   Dedicated F722   Dedicated 14FF6   Shared F722   Shared 14FF6   TotalCommitted F722   TotalCommitted 14FF6   Adapter F722 Dedicated
"09/13/2026 21:38:45.488","9433419776.000000","0.000000","14647296.000000","0.000000","631513088.000000","520192.000000","986722304.000000"
```

**H2 — confirmada.** `GetProcessMemoryInfo` con `PROCESS_QUERY_LIMITED_INFORMATION` da **el mismo
numero que .NET** (`PrivateMemorySize64`) para procesos ajenos del mismo usuario, sin elevar.
`sizeof(PROCESS_MEMORY_COUNTERS_EX)` = 80. Contra `dwm` y `System` da `OpenProcess err=5` (acceso
denegado): la sonda lo trata como «sin muestra».

**Bajo que usuario corre lo que se mide, contrastado con `witr` v0.3.3** (sugerencia del usuario):
el daemon es `DESKTOP-LRNOJ3V\Yohan`, sale de la tarea programada y **pasa tambien por un
lanzador** —`pythonw.exe` 15564 -> `pythonw.exe` 15584, la misma trampa del venv de H3—, y llama-swap
es hijo suyo. El `llama-server.exe` que lance llama-swap hereda ese usuario, asi que `OpenProcess` no
deberia dar `err=5`; la tarea 18 lo confirma con el proceso vivo. Pista para CP-2, **no conclusion**:
en el momento de la consulta llama-swap tenia **un `nvidia-smi.exe` como hijo**, lo que apunta a que
`llamaswap_memory_used_bytes` sale de `nvidia-smi` y es memoria del adaptador, no del proceso.

```text
> witr --pid 16916 --tree --no-color
wininit.exe (pid 1564)
  └─ services.exe (pid 1644)
    └─ svchost.exe (pid 1092)
      └─ conhost.exe (pid 8524)
        └─ powershell.exe (pid 10052)
          └─ pythonw.exe (pid 15564)
            └─ pythonw.exe (pid 15584)
              └─ llama-swap.exe (pid 16916)
                ├─ conhost.exe (pid 18068)
                └─ nvidia-smi.exe (pid 18288)
> witr --pid 15584 --no-color
Process     : pythonw.exe (pid 15584)
User        : DESKTOP-LRNOJ3V\Yohan
Command     : "C:\Users\Yohan\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none\pythonw.exe" -m local_delegate serve --log-level warning
Sockets     : 127.0.0.1:9393 (TCP | LISTENING)
> witr --port 9292 --no-color
[2] llama-swap.exe (pid 16916)
    D:\Projects\llms\llama-swap\llama-swap.exe --config D:\Projects\llms\llama-swap\config.yaml -watch-config --listen 127.0.0.1:9292
> witr --pid 1556 --no-color
Process     : dwm.exe (pid 1556)
Why It Exists :
  winlogon.exe (pid 1672) → dwm.exe (pid 1556)
Source      : unknown        (sin campo User: tampoco witr puede abrirlo)
```

El control es el mecanismo del que depende H4, y **se cumple**: 256 MiB anonimos suben
`PrivateUsage` +256,5 MiB; 256 MiB mapeados desde fichero y leidos lo dejan en **+0,5** mientras el
working set sube +256,0. O sea, el riesgo de §3.1 es real: con los pesos mapeados, `PrivateUsage`
**no ve** los expertos.

```text
sizeof(PROCESS_MEMORY_COUNTERS_EX)=80 python=3.11.15
pid 16916 (ajeno, sin elevar)      PrivateUsage=     56.3 MiB  WorkingSet=     14.6 MiB  PagefileUsage=     56.3 MiB
pid 15584 (ajeno, sin elevar)      PrivateUsage=     92.8 MiB  WorkingSet=     50.0 MiB  PagefileUsage=     92.8 MiB
pid 1556: OpenProcess err=5
pid 4: OpenProcess err=5
propio, base                       PrivateUsage=      6.3 MiB  WorkingSet=     13.1 MiB  PagefileUsage=      6.3 MiB
propio, +256 MiB anonimos          PrivateUsage=    262.8 MiB  WorkingSet=    269.1 MiB  PagefileUsage=    262.8 MiB
propio, anonimos liberados         PrivateUsage=      6.3 MiB  WorkingSet=     13.1 MiB  PagefileUsage=      6.3 MiB
propio, antes de mapear            PrivateUsage=      7.3 MiB  WorkingSet=     14.2 MiB  PagefileUsage=      7.3 MiB
propio, 256 MiB mapeados y leidos  PrivateUsage=      7.8 MiB  WorkingSet=    270.2 MiB  PagefileUsage=      7.8 MiB
delta PrivateUsage anonimo = +256.5 MiB (esperado ~+256)
delta PrivateUsage mapeado = +0.5 MiB (esperado ~0)
delta WorkingSet  mapeado = +256.0 MiB (esperado ~+256)
--- referencia .NET (Get-Process) ---
 1556 dwm                          418.90           141.10
16916 llama-swap                    56.30            14.60
15584 pythonw                       92.80            50.00
```

**H3 — confirmada, con tres detalles que la sonda tiene que conocer.** Por tuberia llega **una
linea por segundo** (hora de llegada, no la marca del CSV), y relanzar con el PID nuevo lee a los
~1,4 s. Lo que no se sabia:

1. **Cuando el proceso muere, `typeperf` no se cierra ni deja el campo vacio: emite `"-1"`** cada
   segundo hasta agotar `-sc`, y entonces sale con rc `3221228486` (`0xC0000BC6`, «Los datos no son
   validos»). `-1` es la senal de «el PID ya no existe» -> «sin muestra» y reresolver.
2. **Una ruta con un PID sin instancia sale al instante** con rc `4026531842` y un mensaje
   **enganoso** que culpa a los permisos («debe pertenecer al grupo Usuarios del registro de
   rendimiento...»). No es un problema de permisos: la sonda no debe leer ese texto, sino el rc.
3. **Arrancar `typeperf` cuesta ~1,4-2,8 s hasta la cabecera.** La «lectura sincrona antes y
   despues de cada peticion» de §3.3 **no puede salir de un `typeperf` nuevo**: sale de la ultima
   muestra del flujo continuo (VRAM) y de `ctypes` (RAM, instantaneo). Si eso no basta para las
   corridas de menos de un segundo, la alternativa sin dependencias es PDH por `ctypes`
   (`pdh.dll`); lo decide la tarea 13.

Y un comodin `(*)` arrancado **antes** de que exista el proceso no lo ve nunca (cabecera fija), como
decia §3.3. Detalles menores: los mensajes salen en la pagina de codigos de consola (`Se est�
saliendo`), asi que se parsean solo las lineas que empiezan por `"`.

Trampa de la propia prueba, que la tarea 13 hereda: **el `python.exe` de un venv en Windows es un
lanzador**, y `Popen.pid` es el suyo, no el del interprete. La primera pasada midio el PID
equivocado y dio exactamente el error de permisos del punto 2. La sonda resuelve el PID por nombre
de proceso (`llama-server.exe`), nunca por el `Popen` de quien lo lanzo.

```text
=== A: ruta con PID concreto, el proceso muere a mitad ===
[  0.30s] gpuproc: pid=40160 hr=0x00000000 nivel=0xB000 (Popen.pid=33504)
[  3.14s] A "(PDH-CSV 4.0)","\\DESKTOP-LRNOJ3V\GPU Process Memory(pid_40160_luid_0x00000000_0x0000F722_phys_0)\Dedicated Usage","\\DESKTOP-LRNOJ3V\GPU Process Memory(pid_40160_luid_0x00000000_0x0000F722_phys_0)\Shared Usage"
[  4.14s] A "09/13/2026 21:40:07.729","11403264.000000","757760.000000"
[  5.14s] A "09/13/2026 21:40:08.731","11403264.000000","757760.000000"
[  6.14s] A "09/13/2026 21:40:09.731","11403264.000000","757760.000000"
[  7.14s] A "09/13/2026 21:40:10.732","11403264.000000","757760.000000"
[  8.14s] A "09/13/2026 21:40:11.733","11403264.000000","757760.000000"
[  9.16s] A "09/13/2026 21:40:12.733","11403264.000000","757760.000000"
[ 10.16s] A "09/13/2026 21:40:13.735","-1","-1"
[ 11.17s] A "09/13/2026 21:40:14.747","-1","-1"
(... "-1" cada segundo ...)
[ 16.19s] A "09/13/2026 21:40:20.779","-1","-1"
[ 16.19s] A Error:
[ 16.19s] A Los datos no son v�lidos.
[ 16.19s] A fin, rc=3221228486
=== B: comodin arrancado ANTES de que exista el proceso ===
[ 18.48s] gpuproc: pid=31776 hr=0x00000000 nivel=0xB000 (Popen.pid=4280)
[ 18.48s] B cabecera: 30 columnas, contiene pid_31776_ = False
[ 18.56s] B muestra (30 comas)
[ 19.56s] B muestra (30 comas)
[ 20.56s] B muestra (30 comas)
[ 21.58s] B muestra (30 comas)
[ 22.59s] B muestra (30 comas)
[ 22.59s] B fin, rc=0
=== C: relanzado con el PID nuevo ===
[ 23.95s] C "(PDH-CSV 4.0)","\\DESKTOP-LRNOJ3V\GPU Process Memory(pid_31776_luid_0x00000000_0x0000F722_phys_0)\Dedicated Usage"
[ 24.95s] C "09/13/2026 21:40:28.533","11403264.000000"
[ 25.97s] C "09/13/2026 21:40:29.536","11403264.000000"
[ 25.97s] C fin, rc=0

--- primera pasada, con Popen.pid (el del lanzador del venv) ---
[  2.16s] A Error: contadores no v lidos.
[  2.16s] A   Para usar typeperf, debe pertenecer al grupo Usuarios del
[  2.16s] A   registro de rendimiento local o el comando debe ejecutarse desde una
[  2.16s] A   ventana de comandos con permisos elevados.
[  2.16s] A fin, rc=4026531842
```

**H4 — NO verificada, y no se puede sin tocar la maquina.** Lo que si quedo establecido:

- **b10909 no esta en disco** (`Test-Path D:\Projects\llms\llamacpp-b10909` -> `False`).
- **b9925 no tiene `--load-mode`**: su ayuda (650 lineas) trae `--mlock`, `--mmap, --no-mmap`
  («default: enabled») y `-dio, --direct-io`, coherente con que el PR #28334 los sustituya.
- **El mecanismo esta confirmado por H2** a escala pequena: lo mapeado no es privado.

Lo que falta es exactamente lo que decide: que `--load-mode none` **exista y se comporte asi** en
b10909, que sea **practicable** (tiempo de carga y RAM con ~26 GB libres), y CP-2b: un MoE con
`-ncmoe 0` contra `-ncmoe 12` **subiendo** `PrivateUsage`. Las tres cosas exigen montar b10909 y
cargar un MoE en la GPU, que es la tarea 18 y su aviso previo. Queda como P-11 (§10.1).

```text
> Test-Path D:\Projects\llms\llamacpp-b10909
False
> D:\Projects\llms\llamacpp\llama-server.exe --version
version: 9925 (ed8c26150)
built with Clang 20.1.8 for Windows x86_64
> llama-server.exe --help | Select-String mmap,mlock,load-mode,cpu-moe,direct-io   (650 lineas)
--mlock                                 force system to keep model in RAM rather than swapping or compressing
--mmap, --no-mmap                       whether to memory-map model. (if mmap disabled, slower load but may
                                        reduce pageouts if not using mlock) (default: enabled)
-dio,  --direct-io, -ndio, --no-direct-io
-cmoe, --cpu-moe                        keep all Mixture of Experts (MoE) weights in the CPU
-ncmoe, --n-cpu-moe N                   keep the Mixture of Experts (MoE) weights of the first N layers in the
```
### 3.5 Contexto: `n_ctx`, presupuesto de KV y `rechazo_por_contexto`

Este es el fallo 5 de julio, que la primera version de este protocolo no cerraba.

- **`n_ctx` se fija por modelo, se anota en el registro de §5.2 y se repite igual en las tres
  corridas.** Un modelo medido a 8k y otro a 32k no son comparables.
- **El KV entra en el presupuesto de VRAM.** Se calcula antes de cargar y se anota junto al tamano de
  los pesos; un modelo que quepa en pesos y no en pesos+KV es un modelo que no cabe. gpt-oss usa SWA
  y 32k le cuestan ~0,75 GiB; los densos, mucho mas.
- **El barrido de `llama-bench` llega hasta la profundidad del caso mayor de *su rol***, no hasta un
  32768 fijo. Elegir el punto de operacion con profundidades que no alcanzan al corpus es garantizar
  que el ganador del barrido reviente en la medida.
- **`n_ctx` se fija en tokens medidos del caso mayor del rol, no estimados desde los chars.** La
  densidad varia mas del doble segun el contenido: 48 000 chars de `uv.lock` no son los mismos tokens
  que 48 000 de Markdown, y este repo ya tiene documentada esa trampa. Un `n_ctx` estimado en chars
  convierte el caso mayor en `rechazo_por_contexto` y §6 tumba el rol entero por un error de unidades.
- **Si vigente y candidato no pueden compartir `n_ctx`** —el candidato tiene un techo menor—, se mide
  a los dos con el menor de los dos y se escribe. Lo que no vale es compararlos a contextos distintos.
- **`rechazo_por_contexto` es una clase de resultado propia**, distinta de `descartada` y distinta de
  mala calidad: el modelo devolvio un error por exceso de contexto. En julio estos se contaron como
  fallos del modelo y descartaron uno bueno. En la hoja de resultados van en su columna.

---

## 4. Corpus de tareas reales

REQ-F2-2 pide tareas **reales**, mas que los cinco casos sinteticos de julio, con razonamiento
fijado y `max_tokens` holgado.

### 4.1 De donde salen

Del log de uso del propio MCP: `%LOCALAPPDATA%\local-delegate\usage-*.jsonl`. Guarda `tool`,
`model`, `source`, `chars_in`, `chars_out`, `latency_ms`, `finish_reason`, `chunks` y **`path`**.

Medido el 2026-09-12 sobre los tres meses de log: **152 eventos, de los cuales 146 son tools
`local_*`** (los otros 6 son pruebas de concurrencia). Todos los numeros de esta seccion estan sobre
**los 146**, y los emite el programa en la tarea 14 — no se copian a mano. La primera version de
este documento mezclo los dos denominadores en una fila y de ahi salio una decision equivocada; ver
§11.

### 4.2 Distribucion observada (sobre 146)

| Tool | n | chars_in mediana | min | max | modelo que produccion eligio |
| --- | --- | --- | --- | --- | --- |
| `local_summarize` | 62 | 12 884 | 10 | 197 949 | llama31-8b 42, gemma3-4b 20 |
| `local_commit_msg` | 20 | 19 390 | 143 | 164 585 | qwen25-coder-14b 20 |
| `local_extract` | 19 | 2 132 | 4 | 48 027 | gemma3-4b 14, llama31-8b 5 |
| `local_boilerplate` | 8 | 156 | 32 | 1 024 | qwen25-coder-14b 8 |
| `local_explain_code` | 8 | 16 724 | 33 | 20 027 | qwen25-coder-14b 8 |
| `local_delegate` | 7 | 56 | 4 | 2 000 | gemma3-4b 5, **qwen35-2b 2** |
| `local_classify` | 7 | 53 | 24 | 243 | gemma3-4b 7 |
| `local_translate` | 7 | 42 | 22 | 14 222 | gemma3-4b 5, llama31-8b 2 |
| `local_lint_summary` | 4 | 406 | 81 | 33 423 | gemma3-4b 3, llama31-8b 1 |
| `local_describe_image` | 4 | 546 280 | 53 569 | 587 780 | qwen3-vl-8b 4 |

Por modelo, sobre los mismos 146: `gemma3-4b` 54, `llama31-8b` 50, `qwen25-coder-14b` 36,
`qwen3-vl-8b` 4, **`qwen35-2b` 2**.

### 4.3 El hallazgo que reordena el corpus: produccion trocea

**18 de las 146 delegaciones reales se trocearon** (`chunks` > 1). El diff de 164 585 chars no fue
una llamada: fue **12 en una ocasion y 17 en otra**. Un resumen de 95 016 chars fueron 4.

Consecuencia directa, y es la que mas cambia el corpus: **un caso de 120 000 o 160 000 chars no mide
el modelo, mide el troceador.** El modelo nunca ve esa entrada entera. Medir ahi habria respondido a
una pregunta que no es la de F2.

**Que tool trocea y cuando, leido del codigo y no supuesto** (`server.py`, `config.py`):

| Tool | Camino | Trocea cuando |
| --- | --- | --- |
| `local_summarize`, `local_lint_summary` | `_chat_map_reduce` o `_chat` | `len(contenido) > MAX_CHARS` del modelo del rol |
| `local_commit_msg` | idem, con `MODEL_CODE` | `len(contenido) > 20 000` |
| `local_translate` | `_chat_chunked` | **siempre**, en trozos de `CHUNK_CHARS` = 3 500 |
| `local_delegate` | `_chat_chunked` si `chunk=on`, o `auto` y mayor | `len(entrada) > 3 500` |
| `local_extract`, `local_classify`, `local_boilerplate`, `local_explain_code`, `local_describe_image` | `_chat` | nunca: `_read_input` trunca a `MAX_CHARS` |

Esta tabla no es documentacion: es el criterio con el que se dimensiona **cada** caso, y la tarea 14
la comprueba por programa. Sin ella, la primera version del corpus metio un `traducir-14k` como caso
de una sola llamada cuando `local_translate` trocea **siempre**: el modelo nunca habria visto mas de
3 500 caracteres de una vez.

Asi que el corpus se parte en dos, con proposito distinto:

- **Casos de calidad (15):** dimensionados para caber en **una sola llamada** con el `n_ctx` fijado
  en §5.2. Miden al modelo.
- **Sondeos de techo (2):** las entradas reales grandes, que **no puntuan calidad**. Miden cual es
  la mayor llamada unica que cada modelo acepta, y su resultado natural es `rechazo_por_contexto`
  (§3.5). De ahi sale si los topes de `MAX_CHARS` en `config.py` se pueden subir, que es una
  pregunta de F3, no de F2.

### 4.4 Los 17 casos: 15 de calidad y 2 sondeos de techo

Dos reglas gobiernan la tabla, y las dos se comprueban por programa en la tarea 14:

1. **El rol de cada caso es el que produccion eligio de verdad** (columna de §4.2), no el que yo
   supondria.
2. **Cada caso de calidad cabe en una sola llamada** segun la tabla de troceado de §4.3, con el
   `MAX_CHARS` real de su modelo (`config.py`: mechanical 20 000, long 48 000, code 20 000).

Todas las fuentes se **congelan** en `benchmarks/catalogo-2026-09/fuentes/`; los casos no apuntan a
ficheros vivos del repo (§4.5).

**Rol `mechanical`** (gemma3-4b hoy; una llamada hasta 20 000 chars)

| id | tool | fuente | ~chars | por que |
| --- | --- | --- | --- | --- |
| `resumen-md-2k` | summarize | `CONTRIBUTING.md` | 2 010 | fichero real, delegado 3 veces |
| `extraer-json-2k` | extract | `pyproject.toml` | ~2 100 | la mediana real de extract |
| `clasificar-53` | classify | reconstruido | 53 | la mediana real de classify |
| `traducir-42` | translate | reconstruido | 42 | la mediana real de translate, y **cabe en un trozo** de 3 500 |
| `delegar-56` | delegate | reconstruido | 56 | la mediana real de delegate |

**Rol `long`** (llama31-8b hoy; una llamada hasta 48 000 chars)

| id | tool | fuente | ~chars | por que |
| --- | --- | --- | --- | --- |
| `resumen-md-13k` | summarize | `docs/recipes/claude-code-hooks.md` | ~13 000 | la mediana real de summarize |
| `resumen-changelog-45k` | summarize | copia de `CHANGELOG.md`, recortada | ~45 000 | cerca del tope de una llamada |
| `extraer-uvlock-48k` | extract | `uv.lock` **recortado a lo que el modelo ve** | 48 000 | el maximo real fue 48 027 y `_read_input` lo trunca en `max_chars_for(long)` = 48 000: se congela lo truncado |
| `lint-33k` (**`lint-9k`** desde el segundo piloto de CP-3, §2) | lint_summary | salida de `pytest` congelada (ruff: punto 4 abajo) | 33 423 (8 589) | el maximo real de lint_summary, y cabe en una llamada. **Sustituido**: con 14 archivos el formato pedido no cabia; ahora 5 archivos enteros y conteos comprobados contra la fuente |

**Rol `code`** (qwen25-coder-14b hoy; una llamada hasta 20 000 chars)

| id | tool | fuente | ~chars | por que |
| --- | --- | --- | --- | --- |
| `commit-diff-19k` | commit_msg | diff de un commit real | ~19 000 | la mediana real de commit_msg |
| `explicar-metrics-17k` | explain_code | fragmento de `web/metrics.py` | ~17 000 | la mediana real; fichero delegado 3 veces |
| `explicar-install-20k` | explain_code | fragmento de `install.py` | ~20 000 | el maximo real de explain_code |
| `boilerplate-156` | boilerplate | reconstruido | 156 | la mediana real |

**Rol `vision`** (qwen3-vl-8b hoy)

| id | tool | fuente | por que |
| --- | --- | --- | --- |
| `describir-dashboard` | describe_image | `docs/assets/dashboard.png` | **el unico evento real recuperable**, delegado 3 veces |
| `leer-cifras-dashboard` | describe_image | la misma imagen, otra pregunta | la tarea cambia aunque la imagen no; **inventado**, y asi se marca |

**Limitacion declarada:** de los 4 eventos reales de vision, 3 son el mismo `dashboard.png` y el
cuarto es un recorte de pantalla en una carpeta temporal que **ya no existe**. El rol se decide con
**dos casos sobre una sola imagen**, y uno de los dos es inventado. Si eso no alcanza para superar la
banda de ruido, la salida correcta es dejar el rol como esta y escribirlo (REQ-F2-6).

**Rol `fast`: cero casos, y es un resultado**

`qwen35-2b` tiene **2 usos reales en tres meses** y **ninguna tool lo elige**: aparece solo en
`local_delegate`, y ahi produccion escogio `gemma3-4b` 5 de 7 veces. Por la regla 1 de arriba,
`delegar-56` pertenece a `mechanical`, no a `fast`. Forzar un caso para `fast` seria inventarle una
carga que no tiene.

Asi que el rol `fast` **no se mide, no se cambia, y su candidato no se descarga**.

**Lo que cumple esto es REQ-F2-4, no REQ-F2-6.** REQ-F2-4 pide que cada rol quede asignado «con
criterio explicito y con el dato que lo sostiene»; no pide medirlo. Aqui la asignacion es
`qwen35-2b` sin cambio, el criterio es que no tiene carga real, y el dato es verificable: 2 usos en
tres meses y `MODEL_FAST` sin un solo consumidor en `server.py` fuera de la lista que imprime
`local_status`. REQ-F2-6 dice otra cosa —«ningun candidato **supera al vigente** con margen fuera del
ruido»—, y eso presupone un rol **que si se midio**. Citarlo aqui seria la conclusion correcta con
la justificacion inventada, que es el defecto que este repo tiene documentado.

**Desviacion que el gate aprueba explicitamente:** los escenarios de la spec no contemplan «un rol
sin carga real», asi que esta salida no se hereda por prosa. Y la pregunta que F2 deja abierta —si el
rol `fast` debe existir— es **alcance de backlog, fuera del entregable de F2**.

**Sondeos de techo (no puntuan calidad)**

| id | tool | rol | fuente | ~chars | que mide |
| --- | --- | --- | --- | --- | --- |
| `techo-resumen-120k` | summarize | long | `src/local_delegate/server.py` | ~120 000 | la mayor llamada unica que acepta; en produccion son 4+ llamadas |
| `techo-commit-160k` | commit_msg | code | diff reconstruido del historial | ~164 000 | idem; en produccion fueron 12 y 17 llamadas |

**Los sondeos los corren solo los modelos de `long` y `code`**, que son los dos roles cuyas tools
trocean de verdad en el log (14 eventos de summarize y 10 de commit_msg). El candidato de
`mechanical` o de `vision` no recibe un diff de 164 000 chars: no responderia a ninguna pregunta.

**Por que se quedan en F2 y no en F3:** un candidato que no aguante la mayor llamada unica de su rol
es peor para ese rol, y eso es criterio de REQ-F2-4. Que ademas digan si los topes de `MAX_CHARS` se
pueden subir es una consecuencia util que F3 aprovechara, no la razon de medirlos. Cuestan 24
corridas de las ~214 (§5.2) y usan la misma maquina limpia, que no volvera a existir.

**Reparto: mechanical 5, long 4, code 4, vision 2, fast 0 = 15 casos de calidad**, mas 2 sondeos.
Un rol con dos casos no tiene banda de ruido propia digna de ese nombre; esta escrito aqui para que
la §7 no finja un agregado donde no lo hay.

**Que modelo corre que casos:** cada modelo corre **los casos de su rol**, y ademas los dos sondeos
si es de `long` o de `code`. Ni el candidato de `mechanical` gasta corridas en un diff enorme, ni el
de `code` en clasificar 53 caracteres.

#### Resultado de la tarea 14 (2026-09-14): lo que cambio al construirlo

El corpus lo construye `scripts/construir_corpus.py` llamando a **la tool real** de `server.py` con
el backend interceptado, y guarda el modelo que eligio produccion, cuantas llamadas hizo y el prompt
exacto. Las reglas de arriba se comprobaron asi, no leyendo esta tabla, y **cuatro cosas de esta
seccion no aguantaron**:

1. **Seis ids prometian un tamano que la fuente no tiene.** Es el mismo defecto del
   `techo-resumen-120k` —`server.py` tiene 102 987 chars, no 120 000—, repetido en cinco casos mas.
   Se renombran al tamano real y el constructor comprueba desde ahora que el numero del id cuadra
   con la fuente:

   | Antes | Ahora | Por que |
   | --- | --- | --- |
   | `extraer-json-2k` | `extraer-toml-2k` | `pyproject.toml` entero son 7 073 bytes: produccion lo manda a `long`, no a `mechanical`. Se recorta a 2 100 chars en linea entera |
   | `resumen-md-13k` | `resumen-md-10k` | la fuente tiene 10 331 chars |
   | `resumen-changelog-45k` | `resumen-changelog-43k` | recortado antes de una seccion de version: 43 293 |
   | `explicar-metrics-17k` | `explicar-metrics-15k` | recortado antes de un bloque de nivel superior: 15 400 |
   | `techo-resumen-120k` | `techo-resumen-103k` | `server.py` entero; en produccion, 5 llamadas |
   | `techo-commit-160k` | `techo-commit-156k` | `git show d7c3dcc`; en produccion, 13 llamadas |

2. **La imagen de control no tenia «otras cifras».** Las seis cifras grandes del panel
   (1.847.125, 390, 123.478, 1.898.456, 5048 ms, 2,3 %) son **identicas** en `dashboard.png` actual
   y en la de `bcbe39f`: son datos de demostracion fijos. Un `leer-cifras-dashboard` que preguntara
   por ellas daria lo mismo con la imagen correcta que con la equivocada, o sea un control de CP-3
   que no puede fallar. Lo que si cambia es la version (0.27.0 frente a 0.24.0) y la primera fila de
   «Actividad reciente» (29/8 05:01 frente a 24/7 23:12): el caso pregunta por eso, y lo de la
   imagen vieja va como `forbidden_terms`. `describir-dashboard` tiene terminos estructurales, asi
   que su desenlace esperado con la imagen equivocada es el tercero de CP-3.

3. **`instruction` no existe: son `system` y `user_template`**, capturados de la tool con el
   contenido sustituido por `{CONTENIDO}`, mas `max_tokens`, `temperature` y `response_format` de
   produccion. «El prompt real de esa tool» (§4.6) solo es real si sale de la tool. Por la misma
   razon, `max_tokens` es **el de produccion** y no «2x la salida esperada»: si trunca, §4.7 punto 3
   ya lo marca `truncado` y lo repite con mas.

4. **`lint-33k` sale de `ruff check --select ALL`, no de `pytest`.** Una suite en verde da una
   salida corta y con tiempos que cambian en cada corrida; ruff da hallazgos deterministas para un
   commit. Sigue siendo `generado`, con el comando registrado en `origen`.

Y dos decisiones de sitio: el cargador del corpus v2 (`load_corpus`, que falla si un hash no cuadra)
va **ya** en `benchmark.py` y la tarea 16 lo conecta al runner, en vez de escribir otro en el
script; y los fragmentos de codigo se congelan como `.py.txt`, porque estan cortados a mitad y ruff
los rechazaria.

### 4.5 Fuentes congeladas, y lo que no se pudo recuperar

Cada fuente se copia a `benchmarks/catalogo-2026-09/fuentes/` y se hashea **la copia**. Dos razones:

1. Los casos apuntaban a ficheros que **el propio plan edita**: `CHANGELOG.md` cambia en cada release
   y `docs/wiki/Backend-versions.md` lo toca la tarea 16. Un `source_sha256` contra una ruta viva se
   invalida solo.
2. Dos fuentes reales **ya no existen**: el `diff-grande.txt` del scratchpad de una sesion antigua y
   el recorte de pantalla de vision. Se reconstruyen equivalentes desde el historial del repo y se
   marcan como reconstruidas.

**Lo que no se puede recuperar, y se dice:** 50 de los 146 eventos son `source=inline`, y de esos el
log guarda el tamano pero **no el contenido**. (Esta linea decia 56: es la cifra sobre los 152, con
las 6 pruebas de concurrencia dentro. El mismo cruce de denominadores que §11 da por corregido,
repetido aqui; lo conto el constructor de la tarea 14, no una relectura.)

El campo `procedencia` distingue cuatro cosas, porque meterlas todas en «reconstruido» seria
esconder la diferencia que importa:

| Valor | Que significa | Casos |
| --- | --- | --- |
| `congelado` | copia literal del fichero que se delego de verdad | los 8 que salen de ficheros del repo |
| `generado` | salida de una herramienta, regenerada con el mismo comando | `lint-9k` (ruff; era `lint-33k`) |
| `reconstruido` | evento real cuyo contenido era `inline`: se recrea con su forma y tamano | `clasificar-53`, `traducir-42`, `delegar-56`, `boilerplate-156`, `techo-commit-160k` |
| `inventado` | **no corresponde a ningun evento real** | `leer-cifras-dashboard` |

Ninguna conclusion se apoya en un caso que no sea `congelado` sin decirlo, y la unica de las cuatro
categorias que no deberia sostener sola una decision de rol es `inventado` — que es justo el problema
declarado de `vision` en §4.4.

**Privacidad:** el log guarda rutas de ficheros ajenos al repo (el vault de Obsidian, otros
proyectos). El constructor **descarta toda fuente fuera del repo** y el corpus versionado no lleva
ninguna ruta del usuario. Los conteos agregados si, porque no identifican nada.

### 4.6 Esquema del corpus (v2)

El corpus de julio (`benchmarks/moe/cases.json`, `schema_version: 1`) **fabrica** la entrada:
`materialize_case()` repite un `filler` hasta `target_chars`. Para tareas reales no sirve.

`schema_version: 2`, en `benchmarks/catalogo-2026-09/cases.json`:

| Campo | Para que |
| --- | --- |
| `id`, `tool`, `role` | identificacion y a que rol pertenece (`fast`/`mechanical`/`long`/`code`/`vision`) |
| `kind` | `calidad` o `techo`; los de techo no puntuan calidad |
| `instruction` | el prompt real de esa tool |
| `source_file` | nombre del fichero **dentro de `fuentes/`**, nunca una ruta viva |
| `source_sha256`, `source_chars` | reproducibilidad; si el hash no cuadra, el runner **falla** |
| `procedencia` | `congelado`, `generado`, `reconstruido` o `inventado` (§4.5) |
| `media_type` | `texto` o `imagen`; decide si el payload lleva `image_url` |
| `max_tokens` | 2x la salida esperada |
| `reasoning_effort` | override opcional del valor por modelo (§4.7) |
| `expected_terms`, `forbidden_terms`, `expected_json_fields` | puntuacion |
| `reference_ok`, `reference_bad` | solo en los cinco casos de CP-4 |

**Decision: el runner deja de aceptar `schema_version: 1`.** Ningun REQ-F2 pide repetir la prueba de
julio, el fichero de julio se conserva igual, y mantener dos esquemas vivos es superficie y tests que
F2 no necesita. Si algun dia hiciera falta, el cargador viejo esta en el historial de git.

### 4.7 Puntuacion: que cambia respecto a julio

`score_response()` hace hoy `casefold()` y busca el termino literal. Los cambios:

1. **Normalizacion Unicode** (NFKD + `casefold`) antes de comparar. En julio la puntuacion literal
   penalizo el Unicode: un resumen en espanol correcto perdia puntos por los acentos.
2. **Terminos prohibidos**: si aparece uno, la calidad de esa corrida es 0 aunque acierte lo demas.
   Es el unico detector barato de alucinacion, y hace falta.
3. **`finish_reason == "length"` marca `truncado`** y la corrida **no puntua como mala**: se repite
   con `max_tokens` mayor. **Tarea 19:** si vuelve a truncar con el doble, puntua 0
   (`truncado_repetido`); ver «Runner, `boilerplate` y §7 tras CP-3» en §2.
4. **Razonamiento aparte**: los tokens de `reasoning_content` se cuentan por separado. Un modelo que
   gaste el presupuesto pensando y devuelva `content` vacio es un fallo de **configuracion** — la
   clase ya existe en `fallos.py` desde F0.
5. **El JSONL guarda que componente puso la calidad a 0.** Sin eso CP-4 no se puede evaluar: no habria
   forma de saber si el puntuador acerto por la razon correcta.
6. **Tarea 19: el codigo generado se ejecuta** en los casos con `execution_checks`. Pasa por el
   mismo `_strip_fences` que `local_boilerplate` antes de escribir a disco, y corre en otro proceso
   con `python -I`, carpeta temporal, entorno vacio, sin stdin y `EXEC_TIMEOUT_S` = 10 s. No es un
   sandbox del sistema: correr codigo de un modelo en local lo aprobo el usuario. El JSONL guarda
   `execution_ratio` y `execution_passed`; si la proporcion es 0, `zero_by: execution`.
7. **Segundo piloto de CP-3: los conteos de lint se comprueban contra la fuente** en los casos con
   `expected_counts` (hoy `lint-9k`). Regla escrita, en el constructor: para cada regla que el caso
   pide nombrar (las tres mas frecuentes), los numeros validos son **el total, cuantos archivos la
   tienen y lo que suma en cada archivo**, sacados de las lineas de ruff. El puntuador asigna cada
   entero suelto (ni pegado a letras ni parte de un decimal) a **la regla que tiene delante en su
   linea, hasta la siguiente regla**; la regla cuadra si tiene al menos uno y todos son validos.
   Calidad = minimo con la cobertura; `zero_by: counts`. **Limite escrito:** los numeros pequenos
   (1, 2) suelen ser validos para cualquier regla, asi que la senal caza el conteo grande inventado
   («T201: 10 archivos», con 5) y no el pequeno; y un conteo escrito **delante** de la regla o en
   otra linea no se ve. CP-4 gana una **septima pareja**, senal
   `conteos`, con un oraculo que recorre los digitos a mano, sin las expresiones del puntuador.
8. **Segundo piloto de CP-3: un caso puede quedar sin puntuacion automatica**
   (`automatic_scoring: false`: `commit-diff-19k` desde el segundo piloto, `lint-9k` desde el tercero). El runner lo sigue puntuando y guardando
   —el dato no se pierde—, pero `analizar_benchmark.py` lo saca de la banda, del agregado y de §6 y
   §7, y el informe de CP-3 lo lista como «solo revision a ciegas». Lo juzga §4.8.

**`reasoning_effort` se fija por modelo y se puede sobreescribir por caso.** Hace falta lo segundo:
Qwen3.8-27B es muy verboso y para resumir hay que apagarle el razonamiento, pero el mismo modelo
corre casos de codigo en la misma tanda, y con un solo valor por invocacion se mediria mal uno de
los dos. Precedencia: caso > modelo. **El CLI de hoy solo acepta `low|medium|high`: la tarea 16
anade «apagado»**, porque «apagado» es justo lo que el registro de §5.2 necesita y no existe. El
fallo 4 de julio fue exactamente medir con `low` creyendo que era neutro.

#### Resultado de la tarea 16 (2026-09-14): el runner, y lo que esta seccion no fijaba

**La calidad.** `score_output` normaliza (NFKD, sin marcas combinantes, `casefold`); un termino
prohibido la pone a 0 (`zero_by: forbidden_terms`); un JSON invalido tambien (`zero_by:
json_valid`); si no, es el **minimo** entre la cobertura y la proporcion de campos JSON presentes,
y si ese minimo es 0 se anota que componente fue. El minimo y no la media: un extractor que acierta
los terminos y se deja la mitad de las claves no hizo la mitad del trabajo bien.

**Los desenlaces de una corrida**, cada uno en su columna:

| `outcome` | Cuando | Puntua |
| --- | --- | --- |
| `ok` | respuesta completa | si |
| `truncado` | `finish_reason: length`; se repite **una vez** con el doble de `max_tokens`, y las dos quedan en el JSONL | no |
| `rechazo_por_contexto` | 400 con `exceed_context_size_error` en el cuerpo | no |
| `configuracion` | `length`, `content` vacio y `reasoning_content` con texto: la clase de `fallos.py` | no |
| `error` | todo lo demas | no |

`descartada` va aparte: la pone la sonda (§3.2), no el backend.

**Lo que se verifico y lo que no:** la cadena `exceed_context_size_error` y las de `enable_thinking`
y `chat_template_kwargs` estan en `llama-server-impl.dll` de **b9925**, buscadas en el binario. Que
b10909 conteste asi un desborde real, y que un modelo razonador respete `enable_thinking: false`,
**no** esta comprobado: lo confirman los sondeos de techo y la primera corrida con Qwen3.8 (tarea
19). Para poder reclasificar sin repetir, el runner guarda `error_body` y `reasoning_chars`.

**«Apagado» es `--reasoning-effort off`**, y viaja como `chat_template_kwargs: {enable_thinking:
false}`; `low|medium|high` siguen yendo como `reasoning_effort`, que es variable de la plantilla de
gpt-oss. Precedencia caso > modelo, con `reasoning_effort_source` en el registro.

**La temperatura es la de produccion** (0,2 en 13 casos, 0,1 en `boilerplate-156`, 0 en
`extraer-toml-2k`, `clasificar-53` y `extraer-uvlock-48k`), que el corpus guarda de la tool real.
**Cambiado tras el segundo piloto de CP-3 (P-12, decision del usuario, 2026-09-14)**: la primera
version fijaba 0 «para medir», y con `-np 1` eso daba corridas identicas byte a byte (§5.3).

**CP-4 ya es un test** (`tests/test_benchmark.py`): puntua las cinco parejas del corpus y exige que
cada una se separe **por su componente**. Corre en cada commit; la tarea 19 no tiene que ejecutarlo,
solo leer que esta en verde. Y otro test comprueba que un puntuador literal **no** separaria la
pareja de Unicode, que es la que delataria perder la normalizacion.

**Los sondeos de techo no tenian prompt.** En produccion son 5 y 13 llamadas, asi que el constructor
no guardaba ninguno. Ahora captura aparte la ruta de **una** llamada de la misma tool (forzando
`max_chars_for`), y `production.calls` sigue diciendo las llamadas reales.

**Y un defecto del constructor que salio aqui:** regenerar el corpus **recongelaba las fuentes desde
los ficheros vivos**. Al anadir el prompt de los sondeos leyo un `CHANGELOG.md` que ya traia la
entrada nueva y paso ruff por un `src/` modificado, y sobrescribio `resumen-changelog-43k` y
`lint-33k` —la invalidacion que §4.5 queria evitar al congelar—. Se restauraron desde git, y ahora
una fuente ya congelada se reutiliza; recongelar exige `--refrescar-fuentes`.

### 4.8 Revision humana, a ciegas

La puntuacion automatica no decide sola (REQ-F2-2). Al cerrar la tanda, un script genera una hoja
con las respuestas guardadas, **barajadas y con la etiqueta del modelo oculta**. El usuario puntua
0/1/2 sin saber de quien es cada una. Luego se destapan.

Que sea a ciegas no es ceremonia: la revision es el unico juez que ve lo que el puntuador automatico
no, y si sabe que modelo mira, puntua la expectativa.

---

## 5. Procedimiento

### 5.1 Orden, y por que ese

1. **CP-1, CP-2 y CP-2b.** CP-1 tiene veto.
2. **Fijar `n_ctx` y el presupuesto de KV por modelo** (§3.5), antes de cargar nada en serio.
3. **CP-3 y CP-4** con el corpus ya congelado. Van **antes** de la linea base: si CP-3 obliga a
   reescribir un caso (P-9), una linea base medida antes queda inservible para ese caso y habria que
   repetirla.
4. **Linea base del catalogo vigente** (REQ-F2-6), en la misma tanda y **sobre b10909**, no sobre la
   b9925 de produccion: comparar sobre motores distintos no es comparar. Si el motor nuevo cambia
   los numeros del vigente, es un hallazgo propio y se escribe aparte.
5. **Barrido del punto de operacion** de cada candidato, *antes* de medir su calidad: `llama-bench`
   con profundidades **hasta la del caso mayor de su rol**, y en los MoE un barrido de `-ncmoe`
   (0, 4, 8, 12, 16). Se fija el punto mas rapido que **quepa** con `Shared Usage` plano. Julio fijo
   `-ncmoe 12` sin barrer y perdio un 60 % de velocidad.
6. **Tanda de calidad y memoria**: cada modelo con los casos de su rol, 3 corridas.
7. **Sondeos de techo**, que dan `rechazo_por_contexto` o el tamano maximo aceptado.
8. **Agregacion y regla de decision** (§7), la corre el programa.
9. **Revision humana a ciegas** (§4.8).
10. **Asignacion de roles** con su criterio escrito (REQ-F2-4) y la entrada a F3 (REQ-F2-5).

### 5.2 Registro de modelos de la tanda

Se completa antes de empezar; ninguna fila puede quedar con huecos. `n_ctx`, KV y `--load-mode` se
anotan aqui porque son parte de la identidad de la medida, no del arranque.

| Rol | Vigente (linea base) | Candidato | Alternativa si el candidato cae | `reasoning_effort` por defecto | Notas |
| --- | --- | --- | --- | --- | --- |
| `fast` | `qwen35-2b` | **no se mide** | — | — | cero casos y cero carga real: §4.4. El rol no se cambia y el candidato no se descarga |
| `mechanical` | `gemma3-4b` (residente) | Gemma 4 E4B (Q4_K_M, 5 GB) | LFM2.5-8B-A1B | — | **nunca `--swa-full`** |
| `long` | `llama31-8b` | Gemma 4 26B-A4B UD-IQ4_XS (13,4 GB) | gpt-oss-20b, Granite 4.2 8B | gpt-oss: fijar y anotar | MoE: barrer `-ncmoe` |
| `code` | `qwen25-coder-14b` | Qwen3.6-35B-A3B IQ4_XS | Qwen3.8-27B (+MTP), North-Mini-Code | Qwen3.8: **apagado** al resumir | MoE: barrer `-ncmoe` |
| `vision` | `qwen3-vl-8b` | Gemma 4 12B | Gemma 4 26B-A4B | — | 2 casos sobre 1 imagen: ver §4.4 |

Columnas que se rellenan al fijar el entorno: `n_ctx`, VRAM de pesos, VRAM de KV, `-ncmoe` elegido,
`--load-mode`.

Descarga: los **~85 GB** de la lista corta del vault menos los ~5 GB de los candidatos de `fast`, que salen de la tanda, mas los **36,6 GB** del modelo que no cabe de CP-1: **~117 GB** en total, dentro de los 400 GB libres. La cifra se contrasta al descargar; no se deriva de nada mas. `gpt-oss-20b` ya esta. **Qwen3.5-122B-A10B UD-IQ2_XXS
(36,6 GB) no es candidato**: entra solo como el modelo que no cabe de CP-1.

**Alcance y presupuesto de corridas.** `fast` sale de la tanda (§4.4), asi que son **8 modelos**:
vigente y candidato de `mechanical`, `long`, `code` y `vision`. Las alternativas solo se miden si su
candidato cae por CP-1, por OOM o por `rechazo_por_contexto` en su propio rol.

| Bloque | Cuenta | Corridas |
| --- | --- | --- |
| CP-3, texto | 13 casos x 2 modelos x 5 | 130 |
| CP-3, `vision` | 2 casos x 2 entradas x 5, con un solo modelo | 20 |
| CP-1, CP-2, CP-2b | cargas y descargas, sin corpus | ~10 |
| Tanda de calidad | (5+4+4+2) casos x 2 modelos cada rol x 5 | 150 |
| Sondeos de techo | 2 casos x 4 modelos (`long` y `code`) x 5 | 40 |
| **Total de peticiones al backend** | | **~350** (era ~214 con 3 corridas) |

Aparte van los barridos de `llama-bench`, que no pasan por el runner, y las descargas (~117 GB,
desglosadas arriba). CP-4 no gasta corridas: es un test del puntuador.

**La duracion estimada en horas se escribe en la bitacora antes de empezar y se contrasta al
cerrar.** No es burocracia: la maquina queda bloqueada mientras tanto y la ventana de F1 corre en
paralelo (§1.5), asi que el coste de equivocarse en la estimacion lo paga otra medicion.

### 5.3 Repeticiones y estado termico

**5 corridas** por (modelo, caso) —3 hasta el tercer piloto de CP-3: con ruido real, una corrida mala
movia la mediana de 3 y ponia la dispersion en su maximo—, con **la temperatura de produccion del caso
y una semilla distinta por corrida** (`seed + run - 1`, la misma en los reintentos de esa corrida; las dos van al registro). Asi
la banda de ruido mide la variacion que produccion tiene de verdad y la medida sigue siendo
reproducible.

*Primera version, refutada por el segundo piloto de CP-3:* «`temperature 0` y `seed` fijo no bastan:
llama.cpp no es determinista bit a bit cuando agrupa peticiones». Con `-np 1` no agrupa, y las tres
corridas salieron identicas byte a byte (§2, segundo piloto). Los tres casos con temperatura 0 en
produccion siguen dando banda 0, y eso es fiel a produccion, no un defecto.

**`thermal_state` esta mal calculado hoy** y alimenta la banda de ruido: `benchmark.py:269` lo pone
como `"cold" if run == 1 else "hot"`, asi que marca como fria la primera corrida **de cada caso**
cuando el modelo lleva rato cargado. Solo es fria la primera peticion despues de cargar el modelo.
La tarea 16 lo corrige marcando como fria **solo la primera peticion tras un cambio de PID de
`llama-server.exe`**, que es la senal de carga que la sonda ya sigue (§3.3) y la unica disponible sin
preguntarle a llama-swap. Si no se corrige, la banda de ruido se infla con un valor mal etiquetado y
la regla de decision se vuelve imposible de superar por un artefacto.

---

## 6. Criterio de tanda no concluyente

Antes de agregar nada, la tanda tiene que ser valida. **No lo es si** para un rol:

- mas de una de cada tres corridas quedo `descartada`, o
- algun caso quedo sin ninguna puntuacion valida en las tres corridas, o
- el vigente y el candidato no corrieron con el **mismo** `n_ctx` y `--load-mode` —cuando el
  candidato tiene un techo menor, los dos se miden al menor y se escribe, que no es lo mismo que
  compararlos a contextos distintos—, o
- CP-1 se cayo a mitad y el tramo afectado no se repitio (§3.2).

Una tanda no concluyente **no se interpreta**: se repite ese rol. Publicar un ganador salido de
cuatro corridas validas de nueve es peor que no publicar ninguno.

---

## 7. Agregacion y regla de decision

La cuenta la hace el programa. Contar a ojo en este repo ya fallo una vez: 14 contra 34.

**Por caso y modelo:** mediana de las 3 corridas y **dispersion** = max - min.

**Calidad de una corrida**, en [0, 1]:

- `0` si aparece cualquier termino prohibido (compuerta dura), y se anota **cual** componente la
  puso a 0;
- si no, `cobertura` = terminos esperados encontrados / esperados, con normalizacion Unicode;
- si el caso pide JSON, invalido o con campos faltantes multiplica por 0,5;
- las corridas `truncado` no puntuan: se repiten con mas `max_tokens`;
- las `rechazo_por_contexto` no puntuan calidad: van a su columna (§3.5).

**Por rol:** media de las medianas **de los casos que CP-3 mostro capaces de separar**, y ademas la
tabla caso a caso completa. Los casos en techo no se promedian: no aportan informacion y diluyen la
diferencia. Se anota **cuantos casos entraron** en cada agregado **y por que se descarto cada uno de
los demas**; si no entro ninguno, el rol es indecidible con este corpus y se dice.

**Sesgo declarado del filtro:** CP-3 calibra con `qwen35-2b` contra `qwen25-coder-14b`, que no es el
par que se decide. Un caso de `long` que no separe *ese* par puede separar perfectamente
`llama31-8b` de Gemma 4 26B-A4B, y aun asi quedaria fuera. El sesgo empuja hacia «no se cambia», que
es la salida conservadora, pero no es gratis: `long` y `code` tienen 4 casos, y si entran menos de
**dos**, el rol se declara **debilmente decidible** y el veredicto lo dice junto al numero. La media sola, sin la tabla, esconderia un modelo bueno en
tres casos y catastrofico en uno. `vision` tiene 2 casos y `fast` esta fuera de la tanda: en ninguno
de los dos se presenta un agregado.

**Banda de ruido de un caso** = la mayor dispersion de ese caso en los dos modelos comparados.
**Banda del agregado** = la media de las bandas de los casos que lo forman. CP-3 separa cada caso
contra su propia banda, y §7 compara el agregado contra la del agregado: la misma magnitud en el
control y en la regla.

*Primera version, cambiada tras el tercer piloto de CP-3 (decision del usuario, 2026-09-15):* «la
mayor dispersion por caso observada en ese rol». Con la temperatura de produccion, esa banda la
ponia el caso mas inestable del rol (1,0 en `code`, por `explicar-metrics-15k`), y ningun otro podia
separar: `boilerplate-156` daba 0/0/0 contra 1/1/0,8 y quedaba dentro. Una banda que un solo caso
fija para todos no es conservadora, es un veto.

**Regla (REQ-F2-6):** un candidato sustituye al vigente **solo si** las tres:

1. `calidad(candidato) - calidad(vigente) > banda del agregado`;
2. ninguna corrida suya quedo anulada, ni dio OOM, ni `rechazo_por_contexto` en un caso de calidad;
3. su latencia mediana no empeora mas de un 50 % respecto al vigente: un modelo mejor que tarde el
   triple no sirve para lo que se delega.

**Los sondeos de techo entran en la decision, no solo en la hoja.** Si el candidato de `long` o de
`code` da `rechazo_por_contexto` en el sondeo de su rol y el vigente no, el candidato es peor para
ese rol. Sin esta regla, las 24 corridas de los sondeos no cerrarian ningun criterio y su
justificacion seria retorica.

**Precedencia de los desempates, cuando la calidad cae dentro de la banda** — el programa la aplica
en este orden y sin ambiguedad, porque una regla que no se puede ejecutar no es una regla:

1. **Techo primero.** El que aguante la mayor llamada unica de su rol gana. Un modelo que no puede
   con la entrada real mas grande del rol es peor ahi aunque sea mas rapido: la velocidad no sirve de
   nada en una peticion que se rechaza.
2. **Velocidad despues.** Si los dos aguantan igual, decide la latencia mediana.
3. Si tambien empatan en latencia dentro de su dispersion, **no se cambia el rol**, que es la salida
   por defecto (REQ-F2-6).

**Empate dentro de la banda:** lo resuelve la precedencia de arriba —techo, luego velocidad—, no la velocidad sola, y queda escrito cual de los dos criterios decidio.

**Nadie mejora al vigente:** el rol **no se cambia**, y eso se escribe como resultado, no como
fracaso de la medicion. Es lo que dice REQ-F2-6 literalmente.

**Si el corpus no distingue** en un rol, CP-3 ya lo habra dicho antes de la tanda —por caso y por
agregado, y con la causa separada—, incluido `vision`, que se pilota con el control de entrada de
§CP-3 porque ningun modelo de texto puede correr sus casos.

#### Resultado de la tarea 17 (2026-09-14): la regla ya la aplica un programa

`scripts/analizar_benchmark.py` tiene dos modos. **`cp3`** dice por rol que casos separan por encima
de la banda, cuales estan en techo, si separa el agregado y si la regla podria disparar; su `--json`
es el insumo de **`decidir`**, que aplica §6 y despues §7. `scripts/hoja_revision.py` genera la hoja
de §4.8 barajada y con el modelo oculto, y la destapa contra una clave aparte.

**Lo que el JSONL no traia.** §6 compara `--load-mode` entre vigente y candidato, y el runner no lo
guardaba. Ahora `local-delegate benchmark --load-mode` lo anota en `variant` (toca `benchmark.py`,
su test, la wiki y el CHANGELOG, fuera de los ficheros de la tarea). Y un `n_ctx` o un
`--load-mode` **sin declarar** da no concluyente: con `None` en los dos lados la comparacion pasaria
sin comprobar nada.

**Lecturas que esta seccion no fijaba, y como las decide el programa:**

- **Empate** es toda diferencia de calidad dentro de la banda, con cualquier signo. La regla dice
  «sustituye solo si las tres» y a la vez da desempates «cuando la calidad cae dentro de la banda»:
  las dos cosas solo casan si dentro de la banda la condicion 1 la sustituye la precedencia. Ganar
  por techo o por velocidad exige igualmente las condiciones 2 y 3.
- **Banda**: ~~la mayor dispersion de **todos** los casos de calidad del rol, no solo de los que
  admite CP-3~~. Desde el tercer piloto de CP-3, por caso y media en el agregado (arriba).
- **OOM**: no hay clase propia en el JSONL; **cualquier** `error` del candidato bloquea y se lista
  con su texto. Buscar una cadena de OOM inventada daria un control ciego al resto de caidas.
- **Corrida fria**: fuera de la latencia (lleva dentro la carga), dentro de la calidad.
- **Techo**: la mayor `input_bytes` aceptada en todas las corridas validas de un caso del rol. Si el
  rol tiene sondeo y falta en alguno de los dos, ni se decide por techo ni se sustituye. Y el sondeo
  perdido **veta** tambien una victoria por calidad («entra en la decision, no solo en la hoja»).
- **Tolerancia de 0,001** en todas las comparaciones con la banda: el runner redondea la cobertura a
  4 decimales, y 0,3334 contra una banda de 0,3333 no es mejora. Es menor que el paso real mas fino
  (1/24 en un agregado de cuatro casos de seis terminos).
- **`Shared Usage`**: crece si el pico de una corrida supera la menor primera lectura del modelo en
  el rol. El umbral por defecto es 0 y **esta sin calibrar**: lo fija la tarea 18 al ver CP-1.

**El hallazgo: con la granularidad real, en `code` la regla puede no disparar nunca.** El corpus
tiene casos de muy pocos terminos (`commit-diff-19k` tiene **uno**: calidad 0 o 1;
`extraer-uvlock-48k`, dos). Con la banda definida como la mayor dispersion, basta que
`commit-diff-19k` cambie **una vez en tres corridas** para que la banda de `code` valga 1,0, y
entonces ni un candidato perfecto la supera: «no se cambia», la salida por defecto, por un artefacto
del corpus. Y en general un candidato **un termino** mejor, con un paso de dispersion en el vigente,
no gana nunca: la media de 1/N por caso no supera el mayor 1/N. Dos terminos si (`long`, banda 0,5).
Los dos casos estan en `tests/test_analisis_benchmark.py`, puntuando textos con el puntuador real
sobre los casos reales. **El programa no lo esconde**: `cp3` y `decidir` informan `puede_disparar`,
y el informe dice «la regla no puede disparar» cuando pasa. Si pasa de verdad lo dice la salida real
de CP-3 (tarea 19); que hacer si pasa es la P-12.

**Verificacion:** 36 tests nuevos (35 del analisis y 1 del runner; la suite pasa de 1024 a 1060);
**23 mutantes, 23 muertos**, cada uno por el test que le toca. Uno
quedo vivo en la primera pasada —quitar la tolerancia no rompia nada— porque el test del redondeo
promediaba cuatro casos y diluia la diferencia a 0,25, lejos de la banda: el caso de prueba no podia
distinguir. Se reescribio con un solo caso en el agregado.

---

## 8. Scripts: que se toca y que se crea

| Pieza | Donde | Por que ahi |
| --- | --- | --- |
| Sonda de recursos por proceso | **dentro de** `src/local_delegate/benchmark.py` | el runner la necesita durante la peticion; un modulo nuevo en el paquete seria superficie publicada nueva —con sus tres sitios de documentacion— por una sonda Windows-only de un solo uso |
| Envoltorio para medir fuera del runner | `scripts/sonda_recursos.py` (nuevo) | importa del paquete; lo usa `llama-bench`, que no pasa por el runner |
| Runner: corpus v2, puntuacion, multimodal | `src/local_delegate/benchmark.py` | ya existe, ya esta en el CLI y ya esta documentado en `docs/wiki/Backend-versions.md` |
| Congelado y construccion del corpus | `scripts/construir_corpus.py` (nuevo) | lo corre el repo, no el usuario final; el wheel no empaqueta `scripts/` |
| Agregacion y regla de decision | `scripts/analizar_benchmark.py` (nuevo) | analisis de un solo uso de este SDD |
| Hoja de revision a ciegas | `scripts/hoja_revision.py` (nuevo) | idem |
| Config de llama-swap de pruebas | `benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml` | separada de la estable a proposito |
| Corpus y fuentes congeladas | `benchmarks/catalogo-2026-09/` | versionado, al lado del de julio, que se conserva |

**El runner tiene que aprender a mandar imagenes.** Hoy el payload es texto puro
(`benchmark.py:214-227`: un unico mensaje `user` con `instruction + CONTENIDO`). Sin una parte
`image_url`, **el rol `vision` de REQ-F2-4 no se puede medir en absoluto**. Va en la tarea 16, con su
propia verificacion.

**El corpus de julio queda como material de archivo.** Al retirar `schema_version: 1` (§4.6), el
fichero `benchmarks/moe/cases.json` sigue en el repo pero **su propia CLI ya no lo puede cargar**. Se
conserva a proposito, con una nota en su `README.md` que lo diga: es la unica forma de saber que se
midio en julio, y borrarlo haria irreproducible aquella conclusion.

**Pruebas Windows-only:** la sonda usa `ctypes` y `typeperf`, que no existen en Ubuntu ni macOS, y el
CI corre en los tres. Sus tests llevan marca de plataforma declarada. Este repo ya tiene el
antecedente de un test que fallo **solo en macOS**.

**Obligacion de release:** `benchmark.py` es superficie publicada. Una release toca **tres** sitios:
`CHANGELOG.md`, `README.md` y `docs/wiki/`. La wiki se pudrio cuatro releases seguidas por saltarse
esto, y `Backend-versions.md` es justo la pagina del runner.

---

## 9. Hoja de resultados

El JSONL crudo se conserva entero (`benchmarks/catalogo-2026-09/resultados/*.jsonl`), y de el sale
una hoja generada, nunca escrita a mano:

- **Tabla 1, por rol:** vigente y candidato, con calidad mediana, dispersion, banda de ruido,
  latencia mediana, tok/s, RAM del proceso pico, VRAM dedicada pico, `Shared Usage` pico, corridas
  `descartada` y `rechazo_por_contexto`, y el veredicto de la regla de §7.
- **Tabla 2, caso a caso:** las tres corridas a la vista.
- **Tabla 3, entorno:** versiones, `n_ctx`, `--load-mode`, `-ncmoe` elegido, fecha, estado de CP-1 a
  CP-4, corridas anuladas con su motivo, y si la tanda fue concluyente segun §6.
- **Tabla 4, techo:** la mayor llamada unica que acepto cada modelo.
- **Parrafo por rol** con el criterio de REQ-F2-4: que dato sostiene la eleccion, y si un modelo
  cubre varios roles.

Las cuatro tablas van a `verification.md` cuando la tanda cierre.

---

## 10. Bitacora de sesiones de medicion

Sirve para reproducir la tanda y para descontar estos intervalos de la quinta medicion de adopcion
(§1.5).

| # | Inicio UTC | Fin UTC | Duracion estimada / real | Que se midio | llama.cpp | llama-swap | `--load-mode` | CP-1..CP-4 | Anuladas |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-09-14 19:24 | 2026-09-14 19:51 | ~60 min / 27 min | Tarea 18: entorno, CP-1, CP-2, CP-2b (sin tanda) | b10909 (`a2878d30d`, CUDA 13.3) | v255 (`7761aa1`), puerto 9595 | `mmap` y `none` (CP-2b los compara) | CP-1 pasa (tras un veto: perfil en la ruta equivocada), CP-2 pasa, CP-2b ve expertos solo con `none` y en diferencia (P-13) | ninguna |
| 2 | 2026-09-14 20:09 | 2026-09-14 20:58 | ~75 min / 49 min (CP-3 en si: 20:14-20:24) | Tarea 19: perfil del driver movido a b10909 y medido, CP-3 (`qwen35-2b` vs `qwen25-coder-14b`, 3 corridas, `-c 32768`) y control de entrada de `vision` (`qwen3-vl-8b`) | b10909 (`a2878d30d`, CUDA 13.3) | v255 (`7761aa1`), puerto 9595 | `mmap` (CP-3 no decide RAM; P-13 sigue abierta) | CP-3 **no pasa** (`code` y `mechanical`; `long` y `vision` pasan solo en el programa, ver resultado de CP-3); CP-4 pasa (test) | 2 por `process_changed` (primera corrida de cada modelo), **no repetidas** |
| 3 | 2026-09-14 22:58 | **abierta**: el setup de medicion (perfil en b10909, daemon parado) se mantiene hasta la tanda por decision del usuario; descontar todo el intervalo de la quinta medicion de adopcion (§1.5) | ~90 min / segundo piloto 23:00:36-23:10:30; tercer piloto (las cuatro decisiones, commit `a3bd148`) en la misma sesion, sin tocar el setup | Tarea 19, segundo piloto de CP-3 entero (P-9) con el corpus y el runner corregidos: perfil del driver medido en b10909, texto con `qwen35-2b` y `qwen25-coder-14b` (3 corridas), control de entrada de `vision` con `qwen3-vl-8b` | b10909 (`a2878d30d`, CUDA 13.3) | v255 (`7761aa1`), puerto 9595 | `mmap` | — | — |

Desviaciones de §1.4 en la sesion 1, que la tanda tiene que resolver antes de empezar:

- **RAM libre 17,9 GB, no >= 24**: la maquina tiene **32 GB**, no ~62 como dice §1.1
  (`Win32_PhysicalMemory`: 2 x 16 GB). El presupuesto de pesos de §1.1 esta mal y hay que rehacerlo.
- **`nvidia-smi --query-compute-apps` nunca sale vacio en WDDM**: lista explorer, WebView2,
  PowerToys... El punto 2 se reescribe como «ningun proceso de computo ajeno» (sin `llama-server`
  ni otro cargador vivo).
- **Produccion sin perfil del driver entre ~19:40 y 19:50 UTC** (con el daemon parado, sin uso). Al
  cerrar se devolvio a `D:\Projects\llms\llamacpp\llama-server.exe` y **se midio**: b10909 carga
  desbordando 6 056 MiB, y b9925 **no carga** (tres intentos, 19:50-19:52, sale a los 5-6 s con
  `0xC0000005` al crear el contexto). Esta vez el log **no** trae la linea `cudaMalloc failed`
  —el proceso muere antes de escribirla—, asi que la prueba es por contraste: a las 19:42, sin
  perfil, **el mismo binario con los mismos argumentos cargo**, y lo unico que cambio despues fue el
  perfil. Daemon arrancado a las 19:51; `local_status` lo da arriba, sin modelos cargados.
- **Sesion 2, perfil movido a b10909 y medido antes de medir** (misma prueba que CP-1: 14B, `-c 65536`,
  KV f16, `--fit off -ngl 99`; `Shared Usage` en reposo 129 MiB). Daemon parado a las 20:09 UTC.

  | Hora UTC | b10909 (con perfil) | b9925 (produccion, sin perfil) |
  | --- | --- | --- |
  | 20:14 | **OOM a los 6,1 s** (`cudaMalloc` 12 288 MiB, sale con 1) | **cargo en 10,6 s, 6 053 MiB compartidos** |

  Produccion queda sin perfil mientras dure la sesion 2, con el daemon parado. **Al cerrar** el
  usuario lo devolvio a `D:\Projects\llms\llamacpp\llama-server.exe` y se midio: a las 20:57 b9925
  **no carga** (sale a los 4,6 s con `0xC0000005`, sin linea `cudaMalloc`, igual que al cerrar la
  sesion 1) y b10909 carga en 12,1 s desbordando 5 958 MiB. El perfil vuelve a actuar sobre produccion.
- **Sesion 3, perfil medido antes de medir.** El usuario lo movio a b10909 al cerrar la sesion 2
  (~22:56 UTC) **con el daemon de produccion arriba**: produccion corrio sin perfil hasta que se paro
  el daemon (`LocalDelegateDaemon`, sus dos `pythonw` y su llama-swap) a las 22:58:35. Misma prueba
  que en la sesion 2 (`Shared Usage` en reposo 81 MiB):

  | Hora UTC | b10909 (con perfil) | b9925 (produccion, sin perfil) |
  | --- | --- | --- |
  | 22:58 | **OOM a los 6,1 s** (`cudaMalloc` 12 288 MiB, sale con 1) | **cargo en 13,6 s, 6 114 MiB compartidos** |

- `%APPDATA%\llama.cpp\config.ini` **no existe** (comprobado al empezar y al cerrar): nada que
  respaldar ni restaurar.
- b10909 (`D:\Projects\llms\llamacpp-b10909`), llama-swap v255 (`D:\Projects\llms\llama-swap-v255`) y
  `llama-swap-pruebas.yaml` **se quedan en disco** para la tarea 19; el perfil **no**: la tarea 19
  tiene que moverlo a b10909 y volver a medirlo, porque la NVIDIA App solo admite una entrada por
  nombre de fichero.

---

## 10.1 Preguntas abiertas

- **P-8 — resuelta (2026-09-12).** Choque con la ventana de F1: se espera a que la sesion en curso
  libere la maquina y entonces F2 toma la GPU y la RAM enteras. La bitacora de §10 queda como
  mitigacion del sesgo.
- **P-9 — resuelta (2026-09-14, aprobada por el usuario): se repite el piloto entero**, porque la
  tarea 19 cambio cuatro de los trece casos de texto, el puntuador de `boilerplate` y el runner, y
  el 14B mostro dispersion en un caso que no se toco. Pregunta original: si CP-3 obliga a reescribir algun caso, ¿se repite el piloto entero o solo el
  caso tocado? Propuesta: solo el tocado, mas una corrida de los demas para comprobar que el corpus
  nuevo no movio la linea base. Se decide con el dato delante, no antes — pero **no se decide sobre
  la marcha sin escribirlo**, que es como se cuela un corpus ajustado al resultado que se queria.
- **P-10 — resuelta, y dejo de ser una pregunta.** «¿Alcanza la evidencia para decidir el rol
  `fast`?» se contesto sola al corregir la aritmetica: 2 usos reales, ninguna tool lo elige, cero
  casos en el corpus. Ya no es una incognita de la medicion sino un resultado de F2 (§4.4).
- **P-11 — resuelta (2026-09-13), aprobada por el usuario.** H4 de §3.4 no se pudo verificar en la
  tarea 12: exige b10909 y cargar un MoE, y la tarea 12 no toca la maquina. El plan pedia que, si el
  contador no ve los expertos, «el metodo se cambia aqui, no despues de escribir la sonda encima».
  Resolucion: **la sonda de la tarea 13 guarda siempre los dos contadores**, `PrivateUsage` y
  `WorkingSetSize`, que salen de la **misma** llamada a `GetProcessMemoryInfo` sin coste extra. Asi
  el resultado de CP-2b solo decide **cual se publica** (§3.1 ya preve publicar los dos si `none` no
  sirve), no el codigo. **El orden no cambia**: la primera redaccion de esta pregunta proponia mover
  CP-2b, y era innecesario —§5.1 paso 1 y la tarea 18 ya lo ponen tras CP-1 y CP-2 y antes de
  cualquier medida— y adelantarlo a CP-2 seria peor, porque CP-2 es el que valida que la sonda mide
  el proceso.
- **P-12 — resuelta (2026-09-14, decision del usuario tras el segundo piloto de CP-3).** La banda no
  medía ruido porque el runner forzaba temperatura 0 y con `-np 1` las corridas salian identicas.
  Ahora van la temperatura de produccion y una semilla por corrida (§5.3), y las opciones (b) y (c)
  quedan descartadas: con ruido real la banda deja de ser 0, y el tercer piloto dira si
  `puede_disparar` sigue en `true`. Texto original: La tarea 17 mostro que, con la banda como «la mayor dispersion
  del rol» y casos de uno o dos terminos, la regla de §7 **puede no disparar nunca** en `code`
  (`commit-diff-19k`, un termino: si cambia en una de tres corridas, la banda vale 1,0). ¿Que se
  hace si la salida real de CP-3 da `puede_disparar: false` en un rol? Opciones: (a) aceptarlo y
  escribir el rol como indecidible con este corpus; (b) cambiar la banda, p. ej. por caso en vez de
  la maxima del rol; (c) dar mas terminos a los casos de uno o dos. La (c) toca el corpus y la (b) la
  regla: **las dos se deciden con la salida de CP-3 delante y antes de la tanda**, nunca despues de
  ver quien gana, que es como se ajusta una regla al resultado que se queria.
- **P-13 — abierta (2026-09-14).** CP-2b (tarea 18) mostro que con `--load-mode mmap` ningun
  contador privado ve los expertos en RAM, y que con `none` los ve solo como **`privada − VRAM
  dedicada`**, porque en WDDM la privada incluye la VRAM reservada. Hay que decidir, antes de la
  tanda: (a) `--load-mode` de la tanda — la evidencia apunta a `none`; (b) que magnitud se publica
  como «RAM del proceso» — `privada − VRAM dedicada`, con privada y working set al lado; (c) si esa
  resta la hace `analizar_benchmark.py` (codigo nuevo, con su test) o solo la hoja de resultados.
  Y un aviso para §3.2: con `none` la **VRAM compartida** del proceso sube por los buffers anclados
  de CUDA, asi que no sirve como senal de desbordamiento; esa senal es el OOM que da el perfil.
- **P-14 — abierta (2026-09-14, planteada por el usuario).** En el uso real el MCP **no tendra la
  maquina entera**: convive con el navegador, video, IDE y lo que el usuario este haciendo. El estado
  limpio de §1.4 sigue valiendo para **comparar** modelos entre si (quita ruido), pero **no** para
  **dimensionar** la configuracion que se elige: una config que cabe justa con la GPU vacia, con el
  perfil «Prefer No Sysmem Fallback» activo, **da OOM al cargar** cuando el escritorio ocupa VRAM, en
  vez de ir mas lenta. Hay que decidir antes de la tanda: (a) cuanta VRAM y RAM se reservan para el
  resto de la maquina — medirlo con una muestra de uso normal (VRAM dedicada ocupada fuera de
  `llama-server` durante sesiones de trabajo reales), no suponerlo; (b) si la regla de §7 descarta
  las configs que no caben dentro de ese presupuesto, aunque ganen con la maquina libre; (c) si los
  finalistas se repiten una vez con carga de escritorio tipica (p. ej. video en el navegador) para
  ver que cargan y cuanto pierden. CP-3 no depende de esto: mide si el corpus separa, no cuanto cabe.

---

## 11. Que cambio en la segunda version

Revision adversarial de la primera version (2026-09-12): nueve bloqueantes, seis huecos de
verificacion, ocho riesgos y dos sobre-alcances. Todos resueltos. Los que cambiaron el diseno, no
solo la redaccion:

- **El troceado (hallazgo propio al verificar).** 18 de 146 delegaciones reales se trocean, y el
  caso de 164 000 chars fueron 12 y 17 llamadas. Los casos grandes median el troceador. El corpus se
  parte en casos de calidad de una sola llamada y sondeos de techo (§4.3).
- **El fallo 5 de julio no estaba cerrado** pese a que el documento afirmaba que si: no habia `n_ctx`
  fijado, ni presupuesto de KV, ni clase `rechazo_por_contexto`, y el barrido no llegaba a la
  profundidad del corpus. Ahora es la §3.5.
- **El corpus se invalidaba solo**: apuntaba a `CHANGELOG.md` y a `docs/wiki/Backend-versions.md`,
  ficheros que el propio plan edita, con un gate de hash. Ahora las fuentes se congelan (§4.5).
- **`PrivateMemorySize64` podia subestimar** justo lo que hay que decidir: con los pesos mapeados,
  los expertos en RAM no son memoria privada. De ahi `--load-mode none` y CP-2b (§3.1).
- **El rol `vision` no se podia medir**: el runner no sabe mandar imagenes (§8).
- **«Apagar el razonamiento» no era expresable**: el CLI solo acepta `low|medium|high`, y el ajuste
  tenia que poder ser por caso, no solo por modelo (§4.7).
- **La regla de anulacion era incoherente con CP-1**: si `Shared Usage` crece, lo que se cae es CP-1
  y todo el tramo, no una corrida (§3.2).
- **CP-3 corria con n=1** y exigia «ningun empate exacto», un criterio que obligaba a reescribir
  casos por una razon inventada; y no distinguia «el corpus no puede» de «la premisa era falsa».
- **CP-4 consumia 32 respuestas de referencia que nadie producia**: ahora son 12, con dueno, elegidas
  para cubrir cada senal (§CP-4, tarea 15).
- **Un error de aritmetica sostenia una decision**: la fila «por modelo» sumaba 152 y las otras 146.
  Corregido, `qwen35-2b` tiene **2** usos reales, no 5 — lo que convierte la debilidad del rol `fast`
  en un hallazgo sobre el rol, no en un margen de error (§4.4).

### Tercera version

La segunda paso otra revision adversarial: los nueve bloqueantes originales quedaron cerrados y
aparecieron cinco nuevos, todos en §4.3-§4.4. Lo que cambio:

- **La regla del troceado no se habia aplicado a sus propios casos.** `traducir-14k` entro como caso
  de una sola llamada cuando `local_translate` trocea **siempre** a 3 500 chars
  (`server.py:2043`, `config.py:230`): el modelo nunca habria visto esa entrada entera. De ahi sale
  la tabla de troceado de §4.3, leida del codigo, y la regla 2 de §4.4 que la tarea 14 comprueba por
  programa. `traducir-14k` se sustituye por `traducir-42`, la mediana real, que si cabe en un trozo.
- **El rol `fast` se queda con cero casos, y eso es el resultado.** `delegar-56` violaba la regla de
  asignacion por rol: produccion escogio `gemma3-4b` 5 de 7 veces para `local_delegate`, asi que el
  caso es de `mechanical`. Sin el, `fast` no tiene ninguno — que es coherente con no tener carga
  real. Su candidato sale de la tanda.
- **Los sondeos de techo los corren solo `long` y `code`.** El texto anterior decia a la vez que los
  corren todos los modelos y que el candidato de `fast` no recibe el diff de 164 000 chars, que era
  justo uno de los sondeos.
- **La verificacion del corpus era irrealizable**: pedia que la distribucion del corpus reprodujera
  la del log, cuando el reparto es por rol a proposito y ninguna tolerancia estaba declarada. Se
  sustituye por dos comprobaciones que si pueden fallar: el rol de cada caso contra el enrutado real,
  y que cada caso de calidad cabe en una llamada.
- **CP-4 no podia cubrir `truncado` con textos**: no es una propiedad del texto sino del
  `finish_reason`. Pasa a probarse inyectandolo en un test del puntuador, y CP-4 baja a cinco casos y
  diez referencias.
- Y lo no bloqueante: `extraer-uvlock` se recorta a lo que el modelo ve de verdad (48 000 exactos,
  que es donde `_read_input` trunca, no los 48 027 que entraron a la tool); `procedencia` gana `generado` e `inventado`; vuelven las preguntas abiertas; el `n_ctx` se
  fija en **tokens medidos** y no en chars; el presupuesto de corridas tiene cifra (~214); y el
  corpus de julio queda declarado como material de archivo que la CLI ya no carga.

---

### Cuarta version

La tercera paso una tercera revision adversarial: los catorce bloqueantes anteriores siguieron
cerrados y aparecieron dos nuevos, los dos de la misma clase que este protocolo dice combatir — un
control que no puede dar un resultado distinto.

- **CP-3 no podia validar `vision`**: sus dos casos son de imagen y el piloto los corria con dos
  modelos de solo texto, asi que esas corridas solo podian dar error, mientras §7 afirmaba que CP-3
  ya habria hablado. `vision` pasa a pilotarse con un **control de entrada**: la misma imagen
  correcta contra otra distinta, con el mismo modelo.
- **CP-3 validaba por caso y §7 decidia por agregado.** Con tres de los cinco casos de `mechanical`
  en 42-56 caracteres, el agregado podia ser incapaz de separar y el resultado habria sido
  indistinguible del legitimo «nadie mejora al vigente», que es la salida por defecto. Ahora CP-3
  informa tambien por agregado, los casos en techo **quedan fuera** del promedio del rol, y se anota
  cuantos entraron.
- **La cita estaba mal**: la salida del rol `fast` cumple **REQ-F2-4** (criterio explicito con el
  dato que lo sostiene), no REQ-F2-6, que presupone un rol medido. La conclusion era correcta y la
  justificacion inventada — el defecto documentado de este repo. Corregido, y la desviacion queda
  para que el gate la apruebe explicitamente.
- **Los sondeos de techo entran ahora en la regla de §7** como desempate; antes solo iban a la hoja,
  y sus 24 corridas no cerraban ningun criterio.
- Y las cifras que no cuadraban, que en un documento cuya tesis es «que lo cuente el programa» son
  justo las que no debian quedar: 204 contra 214, seis contra cinco referencias de CP-4, `fast` con
  «1 caso» cuando tiene cero, `procedencia` con dos valores en el plan, 47 000 contra los 48 000
  donde trunca `_read_input`, el orden de §5.1 (CP-3 va antes de la linea base) y la descarga, que
  ahora se declara en vez de derivarse mal.

### Quinta version

Cuarta revision adversarial: A y B cerrados con mecanismo, y tres ediciones cortas que faltaban.

- **La imagen de control no tenia dueno** — el mismo defecto que ya se corrigio con las referencias
  de CP-4, reaparecido en el control nuevo. Ahora es `dashboard.png` en el commit `bcbe39f` (0.24.0):
  **el mismo dashboard con otras cifras**, que es un control mucho mas duro que una imagen sin
  relacion, y lo congela la tarea 14 como cualquier otra fuente.
- **Faltaba decir lo que el control NO demuestra**: que la puntuacion baje con la imagen equivocada
  prueba que el payload y el puntuador reaccionan, no que el caso separe dos modelos. `vision` entra
  con esa limitacion escrita.
- **§7 tenia dos desempates para la misma situacion y ninguna precedencia**, o sea una regla que el
  programa de la tarea 17 no podia implementar. Orden fijado: techo, luego velocidad, y si empatan,
  no se cambia el rol.
- La fila de CP-3 del presupuesto describia una formula falsa (15 x 2 x 3): los casos de imagen no se
  corren con los dos modelos de texto. Partida en dos filas, 78 + 12; el total sigue en ~214.
- Declarado el **sesgo del filtro de §7**: CP-3 calibra con un par que no es el que se decide, asi que
  un rol donde entren menos de dos casos al agregado se marca **debilmente decidible**.

---

## Trazabilidad

| Requisito | Donde se cumple | Evidencia que lo cierra |
| --- | --- | --- |
| REQ-F2-1 | §1.2-1.4, CP-1, §3.1, §3.2, §3.5, §5.3, §6 | bitacora con versiones, `n_ctx` y `--load-mode`; 3 corridas y mediana; anuladas anotadas; criterio de no concluyente |
| REQ-F2-2 | §4 entera | 17 casos trazados al log real, fuentes congeladas con hash, procedencia declarada, revision a ciegas |
| REQ-F2-3 | §3, §3.1, §3.3, CP-2, CP-2b | la medida cruda por corrida: `PrivateMemorySize64`, `Dedicated Usage`, `Shared Usage`, con el control de que ve los expertos |
| REQ-F2-4 | §5.2, §9 | tabla de roles con el dato que sostiene cada eleccion; `fast` y `vision` con su limitacion escrita |
| REQ-F2-5 | §5.1 paso 10 | los roles resultantes son la entrada de F3; F3 no se planifica antes |
| REQ-F2-6 | §5.1 paso 3, §7 | linea base en la misma tanda y el mismo motor; banda de ruido; «nadie mejora» se escribe como resultado |
