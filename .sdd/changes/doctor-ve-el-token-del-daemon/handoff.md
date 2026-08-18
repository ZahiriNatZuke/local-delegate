# Handoff

## Qué se cerró

`doctor` ya ve la combinación que hoy daba «todo a punto» con las once tools en 401: entrada MCP
en modo HTTP, daemon que exige token, y nada con qué autenticarse.

Mergeado en **PR #152** (`0a03477`), con el CI en verde.

## Decisiones que sobreviven

- **El check nuevo NO sustituye a `service.credential`, lo acompaña.** Aquel mira la puerta del
  backend (¿tiene el proceso MCP la API key?) y este la del daemon (¿puede el cliente entrar al
  puerto?). Se cierran por separado: el día de la avería la del backend estaba bien.
- **Vive en `servicio` y no en `andamiaje`**, porque pregunta al puerto y ese grupo no sale a la
  red por contrato — es lo que permite a `install` correr su reporte sin tocar nada externo.
- **Los dos avisos tienen fuerza distinta a propósito.** «No hay cabecera» es una avería segura;
  «la variable está vacía en el entorno de `doctor`» es una sospecha con testigo, porque el
  cliente puede haberse lanzado desde otra consola. Redactarlos igual haría de la segunda una
  certeza falsa.
- **Las entradas `stdio` no cuentan aquí.** No hablan con el puerto, y de su problema ya avisa
  `service.credential`; contarlas sería falso positivo y aviso duplicado.
- **Tres clientes, tres vocabularios** (`headers.Authorization`, `bearer_token_env_var`,
  `{env:VAR}`). El probe los traduce a uno solo en un punto, en vez de comparar tres formatos en
  el sitio de la decisión.

## Qué queda abierto

- **`install` sigue borrando la cabecera al reinstalar sin `--web-token-env`.** Fuera de alcance
  a propósito: es otro fichero y otra decisión (¿conservar lo que había? ¿avisar?). Ahora al menos
  `doctor` lo dice al momento siguiente.
- **Claude Desktop sigue fuera del registro de clientes**, así que este check tampoco lo mira. Es
  el punto de backlog abierto desde el 2026-08-06.
- El check depende de que `doctor` corra en un entorno parecido al del cliente. Ese límite está
  escrito en el docstring y es la razón de que el segundo aviso sea sospecha y no veredicto.

## Nota de operación

En esta máquina, `install` necesita **dos** flags y no uno:

    local-delegate install --mcp-mode http --web-token-env --enable-read-hook --agents
