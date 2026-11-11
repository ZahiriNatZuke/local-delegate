# Verification: llama-swap: un solo lector del cmd

## Environment

- Revision: branch `fix/llamaswap-cmd-single-parser` on `main` `332f0e36`
- Relevant runtime and tool versions: Python 3.11.15 (`.venv` of the main checkout, `PYTHONPATH=src`), Windows 11

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_ctx_size_every_shape_of_the_flag`, `test_ctx_size_variable_or_no_value_stays_estimate`, `test_ctx_size_the_last_form_wins`, `test_ctx_size_only_plain_digits_count` | pass | on 332f0e36 `--ctx-size=32768`, `-c=32768` and `-c "32768"` gave (8192, True); after review, last-form and plain-digit cases fail without the footprint change (4 of 5) |
| REQ-002 | `test_parse_model_gguf_path_quotes_and_equals`, `test_estimate_model_vram_finds_a_quoted_path_with_spaces` | pass | on 332f0e36 the path came cut or with its quotes; the VRAM estimate said file not found |
| REQ-003 | `test_parse_cmd_flags_matches_footprint` and the existing parser tests unchanged | pass | 3 of 4 cases failed on 332f0e36; repro r3 now gives the same values in both readers |
| REQ-004 | `test_doctor_context_estimated_warning`, `test_status_context_estimated` (existing) | pass | the `context_estimated` warning exists; it shows when the role has reasoning with a budget |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| test | pytest -n 2 full suite | pass | see Deviations for the counts |
| lint | ruff check and ruff format --check on the touched files | pass | All checks passed |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- First full run: 1 failed (lexicon: new words `agrees`, `cmds`, `macro` in test names), 7285 passed; renamed. Second full run result recorded in the quality gate evidence.
- An apostrophe inside an unquoted path (`D:/O'Brien/x.gguf`) now opens a quote; llama-swap splits the `cmd` the same shell-like way, so it is accepted and not tested.
- No test drives `_reasoning_fits` end to end with `--ctx-size=32768`; it reads `model_context_size`, which is tested.
