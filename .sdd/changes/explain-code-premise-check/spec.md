# Specification: explain_code: flag answers that confirm an unanchored premise of the question

## Summary

`local_explain_code` with `path` and `question` warns when the answer asserts a premise of the
question that the file does not support, and stays silent when the answer denies it.

## Requirements

- **REQ-001** — With `path` and a question, an answer that asserts a nominalization of the
  question (retención, rotation, caducidad…) that the file does not hold (first 5 letters, folded),
  nor as its English cognate (a Spanish `c` before `i` written `t`: rotación → `rotat`, and the first
  4 letters of that form at a word start: inicialización → `init` of `__init__`), in a sentence with
  no negation and no anchor, ends with a `mcp.explain.premise_unsupported` warning naming the word;
  the prose is not rewritten. With a truncated answer its last line is not judged, as in `check`.
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

- **REQ-005** — The denial is judged per word (#553): if any sentence of the answer that names the
  word (as written or as its English cognate) denies it, the word does not warn in any sentence;
  «no solo», «sin embargo», «not only» do not deny. The warning text has a space after its colon.
  - Request: "si **alguna** frase de la respuesta niega el término (o su cognado) [...] ese término no avisa en ninguna frase"
  - Verify: test tests/test_explain_code_premise.py::test_a_word_denied_in_one_sentence_does_not_warn_in_another

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
- Inherent limit (not fixed with lists): a concept present under another name gives a false
  warning on a correct unanchored answer: «concurrencia» with `sync.Mutex`, paginación with
  `offset`/`limit`, autenticación with `login`; also cognates that differ in other letters
  (sesión/session). -dad/-ty (caducidad/expiry) cannot be fixed with a prefix. To be measured live.
- Cognates with a soft `c` (rotación/TimedRotatingFileHandler, inicialización/`__init__`,
  duración/duration, creación/create) are held by the file and do not warn.

- Known miss of REQ-005: a negation in a sentence that names the word is taken as denying it,
  without parsing what it denies («La retención es implícita, ya que no se borra nada» does not
  warn). Limiting negations («no solo», «not only») and connectors («sin embargo») are excluded.

## Non-functional requirements

- Linear regexes only; the check runs once per answer over the whole file.

## Non-goals

- Judging the prose with a model; changing prompts.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
