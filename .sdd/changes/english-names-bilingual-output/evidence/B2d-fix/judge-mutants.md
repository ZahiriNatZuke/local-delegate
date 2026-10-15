# Mutantes del juez de prosa (B2d-fix)

Aplicados de verdad sobre `scripts/judge_response_language.py` por `judge_mutants.py` (scratchpad): cada uno comprueba que el texto sustituido aparece una sola vez, que el sha256 cambia, corre `tests/test_judge_response_language.py` (sin xdist, bajo `pesado.sh`) y restaura el fichero comprobando el sha256 original. Cada mutante hace fallar SOLO el test de su regla, y el assert que salta es el de `assert_excluded` (`result.tokens == LIMIT - 1`: el elemento que la regla debía quitar aporta tokens) o, en R4, `result.tokens == LIMIT - 1` del enlace. El primer pase tenía además un mutante de la expresión de códigos con dígitos (antes en R6) que no hacía fallar nada porque R8 ya los quitaba: se quitó la expresión (ver `judge-rules.md`).

| Mutante | Cambio | Tests que fallan |
|---|---|---|
| R1 | `if PRODUCT_LINE.match(line)` → `if False` | `test_r1_product_lines_are_dropped` |
| R2 | `in headings` → `in frozenset()` | `test_r2_a_document_heading_copied_literally_is_dropped`, `test_r2_matches_after_normalization` |
| R3 en línea | sin `INLINE_CODE.sub` | `test_r3_inline_code_is_dropped` |
| R3 valla | la valla no abre | `test_r3_fenced_code_is_dropped` |
| R4 | sin `URL.sub` | `test_r4_only_the_url_goes_not_the_link_text` (la ruta se come «guide»: 18 ≠ 19) |
| R5 | sin el filtro de `/` y `\` | `test_r5_paths_are_dropped` |
| R6 | sin `KEBAB` | `test_r6_kebab_rule_names_are_dropped` |
| R7 | sin identificadores | `test_r7_identifiers_are_dropped` |
| R8 | sin dígitos | `test_r8_rule_codes_with_digits_are_dropped`, `test_r8_numbers_are_dropped` |

## Registro literal

```text
original sha256 c212c71eeecea65151cc10fd0e4a3adf4ab923f3692aa8c209841d723dc953a0

## R1
mutated sha256 bb3a43883c8273a919dfce30b5cc3ba94801101b43d54d662dcd27959a0299be (applied: 'if PRODUCT_LINE.match(line):  # R1' -> 'if False:  # R1')
result: 1 failed, 22 passed in 1.09s
failed: ['test_r1_product_lines_are_dropped']
first assert: ["AssertionError: (25, 'the summary of this log is written in plain words and it says what failed with each check for"]

## R2
mutated sha256 7e7fcad272682617bd5563c88067315fde45435995d2b7acdcc1961c9202b259 (applied: 'in headings:  # R2' -> 'in frozenset():  # R2')
result: 2 failed, 21 passed in 1.09s
failed: ['test_r2_a_document_heading_copied_literally_is_dropped', 'test_r2_matches_after_normalization']
first assert: ["AssertionError: (22, '## Configuración del sistema"]

## R3-inline
mutated sha256 de20508f5cdfcaa5f9716610aad2c88c7273c5264f368c3924f095b2f8451eda (applied: 'line = INLINE_CODE.sub(" ", line)  # R3' -> 'line = line  # R3')
result: 1 failed, 22 passed in 1.10s
failed: ['test_r3_inline_code_is_dropped']
first assert: ["AssertionError: (22, 'the summary of this log is written in plain words and it says what failed with each check for `return the value`')"]

## R3-fenced
mutated sha256 022251a3a17f5c7c5bce2122e4a73d864122db5f07d1f9ec62b4ee966b163630 (applied: 'if opening:  # R3, a fence opens' -> 'if False:  # R3, a fence opens')
result: 1 failed, 22 passed in 1.09s
failed: ['test_r3_fenced_code_is_dropped']
first assert: ["AssertionError: (24, 'the summary of this log is written in plain words and it says what failed with each check for"]

## R4
mutated sha256 5efa2444752c9304044d67ae362c6e58df7c91095a71a3043dc95b76d226b0bc (applied: 'line = URL.sub(" ", line)  # R4' -> 'line = line  # R4')
result: 1 failed, 22 passed in 1.08s
failed: ['test_r4_only_the_url_goes_not_the_link_text']
first assert: ['AssertionError: assert 18 == (20 - 1)']

## R5
mutated sha256 e5e9e32b6c2a562cf0a2b77fc9ed45317e63d71c8a10d93943fc59223403c299 (applied: 'if "/" in token or "\\\\" in token:  # R5' -> 'if False:  # R5')
result: 1 failed, 22 passed in 1.10s
failed: ['test_r5_paths_are_dropped']
first assert: ["AssertionError: (25, 'the summary of this log is written in plain words and it says what failed with each check for src/app/main C:\\\\tools\\\\bin')"]

## R6
mutated sha256 a10185e613c46f4c9e1987f72457dd6d75415945abef40c86a4c83200a4868c0 (applied: 'if KEBAB.match(bare):  # R6' -> 'if False:  # R6')
result: 1 failed, 22 passed in 1.09s
failed: ['test_r6_kebab_rule_names_are_dropped']
first assert: ["AssertionError: (22, 'the summary of this log is written in plain words and it says what failed with each check for no-unused-vars')"]

## R7
mutated sha256 8f7565f04ff2eeafb65146b3dcd68e8abfa00cbd4a2f1f6fe560c70669920c3b (applied: 'if (  # R7' -> 'if False and (  # R7')
result: 1 failed, 22 passed in 1.08s
failed: ['test_r7_identifiers_are_dropped']
first assert: ["AssertionError: (22, 'the summary of this log is written in plain words and it says what failed with each check for load_config parseArgs')"]

## R8
mutated sha256 0d2ae54b34edc8fb3381f6149f370c76aa4bc16519f9d0143145b510f9f16947 (applied: 'return not any(c.isdigit() for c in bare)  # R8' -> 'return True  # R8')
result: 2 failed, 21 passed in 1.10s
failed: ['test_r8_rule_codes_with_digits_are_dropped', 'test_r8_numbers_are_dropped']
first assert: ["AssertionError: (23, 'the summary of this log is written in plain words and it says what failed with each check for E501 I001 UP006 TS2345')"]

restored sha256 c212c71eeecea65151cc10fd0e4a3adf4ab923f3692aa8c209841d723dc953a0
```
