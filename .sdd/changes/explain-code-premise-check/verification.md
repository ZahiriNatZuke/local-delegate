# Verification: explain_code: flag answers that confirm an unanchored premise of the question

## Environment

- Revision: branch fix/explain-code-premise-check from origin/main 6eea8660
- Relevant runtime and tool versions: Python of the repo .venv, PYTHONPATH=src (worktree), ruff of the repo

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | tests/test_explain_code_premise.py::test_the_tool_warns_on_the_issue_case, ::test_cognates_with_a_soft_c_are_held_by_the_file, ::test_a_truncated_answer_does_not_judge_its_last_line | pass | warning names «retención»; mutant «no premise branch» fails it; mutant «no ci→ti variant» makes the 4 cognate cases warn; mutant «server does not pass truncated» fails the truncated test |
| REQ-002 | tests/test_explain_code_premise.py::test_the_issue_case_warns_and_the_correct_answer_does_not | pass | mutant «no negation check» makes the 8 correct backup answers warn; mutant «nothing anchors» fails the anchored case |
| REQ-003 | tests/test_explain_code_premise.py::test_correct_answers_do_not_warn | pass | 0/26 of the #507 review set, 0/20 correct answers of the new set; mutant «every word counts» warns on 5 of 6 unanchored correct answers |
| REQ-004 | tests/test_explain_code_premise.py::test_without_path_nothing_is_added | pass | inline output byte for byte; English warning test passes |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest (full, -n 2, under pesado.sh) | yes | pass after lexicon fix | 6268 passed, 29 skipped, 1 failed (test_detect_spanish_names: new English words unclassified), fixed by classifying them in scripts/data/spanish_lexicon.json; that file then 46 passed |
| ruff check src tests / ruff format --check | yes | pass | All checks passed |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Known miss: an assertion whose sentence names a real identifier is taken as anchored.
- Cognates whose first 5 letters differ (autenticación/authentication, sesión/session) can warn on a correct unanchored answer; the meta stoplist covers the asking ones (opción, sección, versión...).
- No prompt change; the live check with the real backend is left to the main session.
