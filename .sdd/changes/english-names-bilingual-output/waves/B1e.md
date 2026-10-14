# Ola B1e: control independiente del detector de idioma

## Selección y congelación

**Quién y cómo:** la eligió el agente de B1e el 2026-10-14, con un script del scratchpad
(`select_b1e.py`, sha256 `d9602e5281075b1f1d91cdaef1a76e05714e6dba4ad123a7c66072920a1fbe25`), sobre
el commit base `58ff9c6f473f0d21d118e9cb6991c039e1733803`. No abrió
`scripts/data/function_words.json` ni corrió el detector sobre ningún candidato. Ninguna frase se
eligió, cambió ni descartó a mano.

**Fichero congelado:** `tests/data/detect_language_control_b1.json` (LF), sha256
`c6e2b6b195408dad323eb4e3cdf09b44ee1576e347fd40f1be06d65a275c0812`. Formato del de B0b (`_about`,
`es`, `en` con `source` y `text`) más `key` (catálogos) o `line` (wiki, línea donde empieza el
párrafo o el elemento de lista), `sha256`, `_base_commit`, `_rule` y `_stats`.

### Regla aplicada (`B1-proposal.md` §5)

- **Español (60):** 30 valores de `es/cli.json` + `es/doctor.json` y 30 frases de `docs/wiki/*.md`
  (12 páginas).
- **Inglés (60):** valores de `en/cli.json` + `en/doctor.json` cuyas claves no están entre las 30
  españolas elegidas.
- **Limpieza:** enlaces Markdown a su texto (se quita la URL o la ruta), spans entre comillas
  invertidas, marcadores (`{x}`, `%(x)s`, `%s`), URL y rutas; espacios colapsados.
- **Wiki:** solo párrafos y elementos de lista sin su marcador; fuera encabezados, tablas, bloques
  de código, citas y HTML. Se limpia el bloque y luego se parte por `(?<=[.!?])\s+`.
- **Elegible:** de 8 a 40 palabras separadas por espacios y al menos 8 tokens `[a-záéíóúüñ]+`.
- **Sin duplicados** (minúsculas) y **sin las 40 frases de B0b**.
- **Selección:** orden por `sha256("<source>\n<text>")` dentro de cada fuente; se toman las N
  primeras.

### Lecturas que la regla no fijaba (decididas antes de correr nada)

1. `<source>` en el hash es la ruta del fichero desde la raíz del repo, igual que el campo
   `source` del control de B0b (`src/local_delegate/resources/i18n/es/cli.json`,
   `docs/wiki/Tools.md`).
2. `es/cli.json` + `es/doctor.json` forman **una** fuente (los 30 salen del conjunto unido);
   igual en inglés.
3. «Ruta» es todo trozo sin espacios que lleve `/` o `\` (se lleva también cosas como «y/o»).
4. Las citas (`>`) no cuentan como párrafo; las líneas que empiezan por `<` tampoco (HTML).
5. Los valores de catálogo no se parten en frases (la regla solo parte la wiki).
6. Ante un duplicado se queda el primero en orden de sha256.
7. Las frases de B0b se buscaron en las dos formas: texto igual y, en la wiki (donde B0b quitó
   los backticks pero conservó su contenido), frase cuyos tokens están todos dentro de una de B0b.
   Se encontraron las 20 españolas y salieron las 20.

Si la sesión principal no comparte alguna, el script se vuelve a correr con la otra lectura
**antes** del commit de congelación.

### Recuentos

| Fuente | Valores o frases | Elegibles | Únicos | Tomadas |
| --- | ---: | ---: | ---: | ---: |
| `es/cli.json` + `es/doctor.json` | 883 valores | 296 | 295 | 30 (20 de `cli`, 10 de `doctor`) |
| `docs/wiki/*.md` | 1 165 frases | 883 (tras quitar 20 de B0b) | 883 | 30 (10 páginas) |
| `en/cli.json` + `en/doctor.json` | 883 valores (menos las 30 claves) | 265 | 262 | 60 (46 de `cli`, 14 de `doctor`) |

Wiki por página: Savings-and-metrics 7, Tools 5, Daemon 5, Troubleshooting 3, Configuration 2,
Remote-backend 2, Architecture 2, Repo-hardening 2, Backend-versions 1, Integration-install 1.

### Comprobaciones hechas sin el detector

- Las 120 frases tienen entre 8 y 36 palabras y al menos 8 tokens; el `sha256` de cada una
  coincide con `sha256("<source>\n<text>")`.
- Ninguna clave inglesa está entre las 30 españolas; ningún texto se repite entre idiomas ni
  coincide con el control de B0b.
- Ningún valor elegido es igual en `es` y en `en` (no hay textos sin traducir haciéndose pasar
  por un idioma).
- La limpieza deja restos visibles en algunas frases (p. ej. `** ** — preguntar al usuario…`,
  `d; candidata a canary…`); se dejan tal cual, como manda la regla.

El commit de congelación (`B1e-freeze-commit-msg.txt`) tiene que entrar antes de cualquier corrida
del detector sobre este fichero.
