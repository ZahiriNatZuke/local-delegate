import importlib.util

spec = importlib.util.spec_from_file_location("s", "scripts/score_lint_fidelity.py")
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)
cases = [
    (
        "underscore",
        r"El fichero `scripts/build\_corpus.py` falla.",
        "scripts/build_corpus.py: error X\n",
    ),
    (
        "underscore-control",
        "El fichero `scripts/build_corpus.py` falla.",
        "scripts/build_corpus.py: error X\n",
    ),
    (
        "tsc-pos",
        "Error en la posición 52 de `login.page.ts`.",
        "src/login.page.ts(52,24): error TS2322: bad\n",
    ),
    ("v255", "llama-swap va en la versión 255.", "llama-swap: v255\n"),
    ("nine", "nine instances of T201.", "a.py:3:9: T201 print found\n"),
]
for name, ans, log in cases:
    r = s.count_inventions(ans, log)
    print(name, {k: v for k, v in r.items() if v})
