# Implementation plan: Modelo de visión por defecto: qwen36-35b-a3b-vision

## Approach

Cambio de un valor por defecto con su cola: una constante nueva para la alternativa ligera en
`config.py`, una rama más en `_probe_role_models` (sin tocar el camino de los roles de texto),
una etiqueta en `renderBackend` del panel reutilizando `.mrole` con un modificador apagado, y
documentación. Tests primero, rojos sin el cambio.

## Ordered tasks

- [x] T1 — Tests rojos: defecto, constante ligera, aviso de doctor, etiqueta del panel, docs (REQ-001, REQ-002, REQ-003, REQ-005)
  - Files or modules: tests/test_vision_default.py, tests/test_checks_role_models.py, tests/test_dashboard_states.py
  - Verification: pytest de esos ficheros falla antes del cambio
  - Depends on: none
- [x] T2 — Defecto y constante en config.py (REQ-001)
  - Files or modules: src/local_delegate/config.py
  - Verification: tests/test_vision_default.py
  - Depends on: T1
- [x] T3 — Aviso de doctor con remedio, i18n es/en (REQ-002)
  - Files or modules: src/local_delegate/checks.py, resources/i18n/{es,en}/doctor.json
  - Verification: tests/test_checks_role_models.py
  - Depends on: T1
- [x] T4 — Etiqueta «sin rol» del panel, i18n es/en, capturas claro/oscuro (REQ-003, REQ-004)
  - Files or modules: src/local_delegate/web/metrics.py, resources/i18n/{es,en}/panel.json, scripts/dev/capture_dashboard.py
  - Verification: tests/test_dashboard_states.py y capturas en evidence/
  - Depends on: T1
- [x] T5 — Documentación y CHANGELOG (REQ-005)
  - Files or modules: README.md, docs/wiki/{Configuration,Tools,Troubleshooting}.md, docs/recipes/llama-swap-{blackwell,vision}.md, resources/skills/local-delegation/SKILL{,.en}.md, CHANGELOG.md
  - Verification: tests/test_vision_default.py
  - Depends on: T2

## Test strategy

- Unit: defecto con el entorno aislado (`importlib.reload` con la variable borrada), sonda de doctor con backend simulado.
- Integration: funciones JS del panel ejecutadas con node (patrón de `test_dashboard_states.py`).
- End-to-end or manual: capturas del panel en claro y oscuro con el navegador headless.
- Security and secret scanning: `personal-security-check` antes del commit.

## Migration and compatibility

- Quien actualice con un catálogo sin `qwen36-35b-a3b-vision` debe poner
  `LOCAL_DELEGATE_MODEL_VISION=gemma4-12b`; `doctor` lo dice. Los roles de texto no cambian.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
