# Verification: doctor: cada rol tiene su modelo servido

## Environment

- Revision: branch `fix/doctor-role-models-served` on `main` `332f0e36`
- Relevant runtime and tool versions: Python 3.11 (`.venv` of the main checkout, `PYTHONPATH=src`), Windows 11

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_all_roles_served_is_ok`, `test_a_text_role_missing_is_warn_with_id_and_variable` (3 roles), `test_two_missing_names_both_variables`, `test_an_empty_list_warns_for_every_text_role` | pass | mutant `if True` instead of `model in served`: 6 tests fail |
| REQ-002 | `test_only_vision_missing_is_ok_with_a_note`, `test_a_text_role_and_vision_missing_warn_without_the_vision_variable`, `test_a_role_without_a_model_is_skipped` | pass | same mutant makes the vision test fail |
| REQ-003 | `test_the_ids_come_from_the_daemon`, `test_the_roles_are_the_daemons_when_it_sends_them`, `test_an_older_daemon_without_roles_uses_this_console_and_says_so`, `test_the_daemon_endpoint_sends_its_role_models`, `test_the_direct_probe_reads_the_ids_of_a_cloud_backend`, `test_an_id_without_tag_counts_as_its_latest_tag`, `test_an_alias_listed_by_models_counts`, `test_backend_down_or_no_list_is_unknown` | pass | mutant ignoring the daemon roles: 1 role test fails |
| REQ-004 | `test_one_doctor_run_probes_the_backend_once` | pass | mutant without memo: the test fails (2 calls) |
| REQ-005 | `tests/test_wiki.py`, `tests/test_checks.py` (ids and counts), `tests/test_doctor.py`, `tests/test_doctor_english.py`, `tests/test_metrics.py`, `tests/test_connection_cause.py` | pass | full suite below |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest -n 2 (full suite, with the lock) | yes | pass | 7290 passed, 30 skipped, 2 failed, both fixed and rerun green (field pin of BackendView and a test name the lexicon did not know) |
| ruff check src tests | yes | pass | no findings |
| ruff format --check src tests | yes | pass | already formatted |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Not run against the real daemon and backend: the main session restarts the daemon with this version and runs `doctor` (live check).
- Providers that list ids with a prefix (`models/<id>`) or do not list what they accept (Azure deployments) would give a warn; not verified, recorded.
- llama-swap aliases not listed (`includeAliasesInList` off) give a warn; the hint says so.
