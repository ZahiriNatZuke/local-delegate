"""lint-large-logs: two realistic synthetic logs over 100 k characters (eslint stylish, tsc).

The real large logs of the set are ruff (L1) and pytest (L3) from B2e. There is no large real
eslint or tsc log on this machine, so these two are generated with a fixed seed, real rule names and
messages, a skewed (Zipf-like) number of problems per file, and the closing lines each tool prints.
Run once, BEFORE measuring; `build_set.py` freezes their sha256.

    uv run python gen_synthetic.py
"""

from __future__ import annotations

import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20261019

DIRS = [
    "src/app/cart",
    "src/app/checkout",
    "src/app/catalog",
    "src/app/auth",
    "src/app/orders",
    "src/app/admin/users",
    "src/app/admin/reports",
    "src/app/shared/ui",
    "src/app/shared/pipes",
    "src/app/core/http",
    "src/app/core/state",
    "src/app/search",
    "src/app/profile",
    "src/server/routes",
    "src/server/services",
    "src/server/db",
    "src/lib/format",
    "src/lib/money",
]
STEMS = [
    "cart.component",
    "cart.service",
    "checkout.component",
    "payment.service",
    "product-list",
    "product-card",
    "login.component",
    "auth.guard",
    "token.interceptor",
    "order-history",
    "order.store",
    "users-table",
    "report-builder",
    "button",
    "modal",
    "currency.pipe",
    "date-range.pipe",
    "api-client",
    "retry",
    "selectors",
    "effects",
    "search-box",
    "filters",
    "profile-form",
    "avatar",
    "orders.route",
    "users.route",
    "mailer",
    "pricing",
    "schema",
    "migrations",
    "format-date",
    "round",
    "index",
    "utils",
    "constants",
]

ESLINT_RULES = [
    ("@typescript-eslint/no-explicit-any", "warning", "Unexpected any. Specify a different type"),
    ("@typescript-eslint/no-unused-vars", "error", "'{v}' is defined but never used"),
    ("no-console", "warning", "Unexpected console statement"),
    ("prefer-const", "error", "'{v}' is never reassigned. Use 'const' instead"),
    ("eqeqeq", "error", "Expected '===' and instead saw '=='"),
    (
        "@typescript-eslint/explicit-function-return-type",
        "warning",
        "Missing return type on function",
    ),
    ("max-len", "warning", "This line has a length of {n}. Maximum allowed is 120"),
    ("no-shadow", "error", "'{v}' is already declared in the upper scope on line {n} column 9"),
    ("@angular-eslint/no-empty-lifecycle-method", "error", "Lifecycle methods should not be empty"),
    ("import/order", "warning", "`{m}` import should occur before import of `./{v}`"),
    ("complexity", "warning", "Method '{v}' has a complexity of {n}. Maximum allowed is 10"),
    ("no-await-in-loop", "error", "Unexpected `await` inside a loop"),
    (
        "@typescript-eslint/no-floating-promises",
        "error",
        "Promises must be awaited, end with a call to .catch, or end with a call to .then",
    ),
    ("no-param-reassign", "error", "Assignment to function parameter '{v}'"),
]
TSC_ERRORS = [
    (
        "TS2345",
        "Argument of type 'string | undefined' is not assignable to parameter of type 'string'.",
    ),
    ("TS2322", "Type 'number | null' is not assignable to type 'number'."),
    ("TS2532", "Object is possibly 'undefined'."),
    ("TS7006", "Parameter '{v}' implicitly has an 'any' type."),
    ("TS2339", "Property '{v}' does not exist on type 'Order'."),
    ("TS18048", "'{v}' is possibly 'undefined'."),
    ("TS2307", "Cannot find module '@app/{v}' or its corresponding type declarations."),
    ("TS2554", "Expected 1 arguments, but got 2."),
    (
        "TS2741",
        "Property 'id' is missing in type '{{ name: string; }}' but required in type 'Product'.",
    ),
    ("TS6133", "'{v}' is declared but its value is never read."),
    (
        "TS2564",
        "Property '{v}' has no initializer and is not definitely assigned in the constructor.",
    ),
]
NAMES = [
    "item",
    "total",
    "user",
    "order",
    "price",
    "ctx",
    "res",
    "data",
    "idx",
    "opts",
    "cb",
    "subtotal",
    "token",
    "rows",
    "query",
]
MODULES = ["rxjs", "@angular/core", "lodash-es", "date-fns", "zod"]


def _files(rng: random.Random, count: int, ext_choices: tuple[str, ...]) -> list[str]:
    files: set[str] = set()
    while len(files) < count:
        files.add(f"{rng.choice(DIRS)}/{rng.choice(STEMS)}{rng.choice(ext_choices)}")
    out = sorted(files)
    rng.shuffle(out)
    return out


def _weights(n: int) -> list[float]:
    return [1.0 / (i + 1) ** 0.9 for i in range(n)]


def _fill(template: str, rng: random.Random) -> str:
    return template.format(v=rng.choice(NAMES), n=rng.randint(11, 190), m=rng.choice(MODULES))


def eslint(rng: random.Random, target_chars: int) -> str:
    files = _files(rng, 130, (".ts", ".ts", ".tsx", ".js"))
    rule_w = _weights(len(ESLINT_RULES))
    per_file: dict[str, list[tuple[int, int, str, str, str]]] = {f: [] for f in files}
    file_w = _weights(len(files))
    size = 0
    while size < target_chars:
        f = rng.choices(files, file_w)[0]
        rule, sev, msg = rng.choices(ESLINT_RULES, rule_w)[0]
        line = rng.randint(1, 400)
        col = rng.randint(1, 60)
        per_file[f].append((line, col, sev, _fill(msg, rng), rule))
        size += 70 + len(msg)
    root = "/home/runner/work/shop-web/shop-web/"
    out = ["> shop-web@3.4.0 lint", "> eslint . --ext .ts,.tsx,.js", ""]
    errors = warnings = 0
    for f in files:
        items = sorted(per_file[f])
        if not items:
            continue
        out.append(root + f)
        for line, col, sev, msg, rule in items:
            out.append(f"  {f'{line}:{col}':<8} {sev:<8} {msg}  {rule}")
            errors += sev == "error"
            warnings += sev == "warning"
        out.append("")
    total = errors + warnings
    out.append(f"✖ {total} problems ({errors} errors, {warnings} warnings)")
    out.append(
        f"  {errors // 9} errors and 0 warnings potentially fixable with the `--fix` option."
    )
    out.append("")
    return "\n".join(out)


def tsc(rng: random.Random, target_chars: int) -> str:
    files = _files(rng, 95, (".ts", ".ts", ".tsx"))
    file_w = _weights(len(files))
    err_w = _weights(len(TSC_ERRORS))
    found: list[tuple[str, int, int, str, str]] = []
    size = 0
    while size < target_chars:
        f = rng.choices(files, file_w)[0]
        code, msg = rng.choices(TSC_ERRORS, err_w)[0]
        found.append((f, rng.randint(1, 500), rng.randint(1, 80), code, _fill(msg, rng)))
        size += len(f) + len(msg) + 30
    found.sort()
    out = ["> shop-web@3.4.0 typecheck", "> tsc --noEmit -p tsconfig.json", ""]
    out += [f"{f}({line},{col}): error {code}: {msg}" for f, line, col, code, msg in found]
    named = len({f for f, *_ in found})
    out += ["", f"Found {len(found)} errors in {named} files.", ""]
    return "\n".join(out)


def main() -> int:
    rng = random.Random(SEED)
    targets = {"N1-eslint-stylish.txt": eslint(rng, 160_000), "N2-tsc.txt": tsc(rng, 120_000)}
    for name, text in targets.items():
        (HERE / "docs" / name).write_text(text, encoding="utf-8", newline="\n")
        print(name, len(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
