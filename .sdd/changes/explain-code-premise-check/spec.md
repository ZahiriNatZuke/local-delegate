# Specification: explain_code: flag answers that confirm an unanchored premise of the question

## Summary

`local_explain_code` with `path` and `question` warns when the answer asserts a premise of the
question that the file does not support, and stays silent when the answer denies it.

## Requirements

- **REQ-001** — With `path` and a question, an answer that asserts a nominalization of the
  question (retención, rotation, caducidad…) that the file does not hold (first 5 letters, folded),
  in a sentence with no negation and no anchor, ends with a `mcp.explain.premise_unsupported`
  warning naming the word; the prose is not rewritten.
  - Request: "si la respuesta **afirma** algo y no cita ninguna línea que lo respalde (o cita líneas que no lo contienen), avisar"
  - Verify: test tests/test_explain_code_premise.py::test_the_tool_warns_on_the_issue_case
- **REQ-002** — An answer that negates the premise, or whose sentence stands on the code (a cited
  line verified by `line_check.check`, or a code identifier present in the file), gets no warning.
  - Request: "un test que pase con la respuesta correcta «no hay retención; nunca borra» y avise con la inventada"
  - Verify: test tests/test_explain_code_premise.py::test_the_issue_case_warns_and_the_correct_answer_does_not
- **REQ-003** — False warnings stay rare: 0 on the 26 correct answers of the #507 review set and 0
  on the correct answers of the new set (including Spanish answers about English code with no
  anchor); plain words that are not nominalizations never count.
  - Request: "Cuidado con los falsos positivos: una guarda que avisa siempre no sirve"
  - Verify: test tests/test_explain_code_premise.py::test_correct_answers_do_not_warn
- **REQ-004** — Without `path` or without a question the output is unchanged; the warning exists in
  Spanish and English.
  - Request: "derived: the #460 contract (inline code and no question stay byte for byte)"
  - Verify: test tests/test_explain_code_premise.py::test_without_path_nothing_is_added

## Acceptance scenarios

### Scenario: the issue case

- **Given** the backup module and «¿cómo gestiona los backups y su retención?»
- **When** the model answers «El módulo aplica una retención implícita…»
- **Then** the result ends with the warning naming «retención»

### Scenario: the correct answer

- **Given** the same file and question
- **When** the model answers «No hay retención: el módulo nunca borra backups…»
- **Then** no warning is added

## Edge cases and failure behavior

- Fenced code in the answer is not prose. A file that mentions the word (comment, string) holds it.
- Known miss: «`createBackup()` aplica una retención implícita» is anchored by the identifier.

## Non-functional requirements

- Linear regexes only; the check runs once per answer over the whole file.

## Non-goals

- Judging the prose with a model; changing prompts.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
