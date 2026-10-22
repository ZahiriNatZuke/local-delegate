# Evidencia — Credenciales desde el Llavero de macOS (macos-keychain, issue #409)

Rama `feat/plugin-macos-keychain`, worktree `D:/Projects/ld-wt-macos-keychain`, base `main` en
`fa4eeeb` (incluye #408, #410 y #411). Máquina: Windows 11; no hay Mac, así que `security` y
`sys.platform` son simulados en toda la suite. El Llavero real no se toca nunca: `conftest.py`
apunta `token_source.SECURITY_COMMAND` a una ruta inexistente en cada test, también en el runner
`macos-latest`.

## Qué cambia

- `keychain.py` (hoja nueva, sin imports del paquete) y `token_source.py`: orden común «entorno
  del proceso → Llavero» (`keychain.credential`; `token_source.resolve`, `api_key`,
  `daemon_token` delegan en ella); Llavero con `/usr/bin/security find-generic-password -a <usuario> -s <servicio>
  -w`, tope 3 s, una consulta por proceso (también el «no hay»), diferida, sin registrar el valor.
  Servicios `local-delegate-remote` y `local-delegate-web-token`. En Windows el puente sigue con
  «registro → entorno» (`web_token`); Linux sin cambio. Docstring de la decisión 11 corregido.
- Una referencia `${VAR}`, `${VAR:-…}` o `{env:VAR}` sin expandir **no cuenta como clave**:
  Claude Code pasa `${LOCAL_DELEGATE_API_KEY}` tal cual si no tiene la variable (review-spec §13),
  que es justo la entrada que escribe `install --api-key-env`. Sin esto el Llavero nunca se
  habría consultado en el caso del issue.
- Consumidores: `config.auth_headers`, `config.web_auth_headers`, `daemon.build_app`
  (`auth.protect`), `web/metrics._require_web_token`, `cli` (residencia) y `benchmark`.
- `doctor` (`service.credential`): en macOS dice la fuente (Llavero, entorno + Llavero) y da WARN
  si la clave solo está en el entorno del shell, con
  `security add-generic-password -U -a "$USER" -s local-delegate-remote -w`. Sin clave en macOS, el
  arreglo propuesto es el Llavero (el daemon tampoco la tiene).
- Mod (`mod/common.js`): `token($)` cae al Llavero con `$.process.run` (tope 3000 ms, una vez por
  carga) si `$.env.get` no trae el token y el entorno es de macOS (`HOME=/Users/<cuenta>` y sin
  `USERPROFILE`; el mod no tiene sustantivo de plataforma y no se amplía la lista de variables).
- Docs: `Remote-backend.md` (sección nueva «Credenciales en el Llavero»), `Daemon.md`,
  `Configuration.md`, `Troubleshooting.md`. CHANGELOG en bloque propio.

## Tests primero (rojo antes del cambio)

Sobre el código de `main`, los tests nuevos de Python fallaban por `AttributeError` (no existía
ninguna lectura del Llavero: `token_source.subprocess`, `api_key`, `resolve`…) y los del mod por
assert (`Expected: "tok-…" / Received: null`; 2 fail de 39). Para comprobar que cada test falla por
la razón que dice, se aplicaron mutantes sobre la implementación y se miró qué assert disparaba:

| Mutante | Test que cae | Assert |
| --- | --- | --- |
| `resolve` no consulta el Llavero | `test_keychain_supplies_the_api_key_when_the_variable_is_missing` | `'' == 'kc-secret-…'` |
| sin caché por proceso | `test_a_failed_or_empty_lookup_is_no_credential[missing]` | `2 == 1` llamadas |
| sin la guarda de plataforma | `test_outside_macos_security_is_never_called[linux]` | «security must not run outside macOS» |
| sin `timeout=` | `…supplies_the_api_key…` y `test_a_hanging_security_is_cut_by_the_time_limit` | `None == 3.0`; 60 s `< 10` |
| sin descartar `${VAR}` sin expandir | `test_an_unexpanded_reference_is_not_a_key` (×3) | fuente `environment` ≠ `keychain` |
| `keychain.py` importa el paquete (`from . import config`) | `test_keychain_is_a_leaf_without_package_imports` | `assert not <re.Match … 'from .'>` |
| `doctor` como antes (sin rama macOS) | `test_credential_on_macos_warns_when_the_key_is_only_in_the_shell` | `'ok' == 'warn'` |

## Ciclo de imports (CodeQL #172 y #173)

La primera versión resolvía en `config.auth_headers`/`web_auth_headers` con un
`from . import token_source` diferido, y `token_source` importa `config`: CodeQL lo marcó como
«Cyclic import». Se rompió de verdad: la consulta al Llavero, la caché, el tope y la detección de
`${VAR}` sin expandir viven en `keychain.py`, que no importa nada del paquete; `config` resuelve con
`keychain.credential(API_KEY, keychain.API_KEY_SERVICE)` y `token_source` delega en lo mismo. Un
test nuevo exige que `keychain.py` siga siendo hoja. Los mutantes de la tabla se repitieron sobre
`keychain.py` y cada uno cae por el mismo assert que antes.

## Suite

- `pesado.sh uv run pytest -n 2`: 4418 passed, 28 skipped, 2 failed. Los dos fallos: el
  guardián de nombres en español (cuatro palabras inglesas nuevas sin clasificar → añadidas a
  `scripts/data/spanish_lexicon.json`, 46 passed después) y
  `test_install_over_a_034_retires_anotar_llamada_and_registers_record_call`, que pasa solo y en
  la segunda corrida completa (intermitente, no toca nada de este lote).
- `ruff check .` y `ruff format --check .`: limpios.
- `claude plugin test` (2.1.308, `CLAUDE_CONFIG_DIR` del scratchpad, tras `build_mod.py`):
  39 pass, 0 fail. `claude plugin validate --strict --json`: `success: true`.

## Verificación en vivo (la hace el usuario en la Mac)

Ver el cuerpo del PR: pasos copiables con `env -i` + MCP stdio + `local_status`, sin pegar
secretos.

## Llamadas `local_*`

- `local_lint_summary(path=suite.txt)`: resumen de la corrida completa de pytest.
- `local_commit_msg(path=diff)`: borrador del mensaje de commit (revisado y reescrito).
- `local_lint_summary(path=suite3.txt)`: corrida completa tras romper el ciclo.
