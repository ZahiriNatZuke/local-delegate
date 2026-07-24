"""Benchmark reproducible para backends locales densos y Mixture of Experts.

El runner no arranca, descarga ni reconfigura modelos. Ejecuta un corpus sintetico contra un
endpoint OpenAI-compatible ya aislado por el operador y escribe JSONL sin prompts ni secretos.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from . import config

# El muestreo frecuente de /metrics no debe convertir el benchmark en un log de cada GET.
logging.getLogger("httpx").setLevel(logging.WARNING)

_METRIC_RE = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{[^}]*\})?\s+(?P<value>\S+)$")
_TRACKED_METRICS = {
    "llamaswap_memory_used_bytes",
    "llamaswap_gpu_memory_used_bytes",
    "llamaswap_gpu_util_percent",
    "llamaswap_gpu_power_draw_watts",
}


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    instruction: str
    facts: tuple[str, ...]
    filler: str
    target_chars: int
    max_tokens: int
    expected_terms: tuple[str, ...]
    expected_json_fields: tuple[str, ...] = ()


def load_cases(path: Path) -> list[BenchmarkCase]:
    """Carga el schema versionado del corpus y valida lo imprescindible."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("cases"), list):
        raise ValueError("corpus invalido: se esperaba schema_version=1 y cases[]")
    result: list[BenchmarkCase] = []
    seen: set[str] = set()
    for raw in data["cases"]:
        case_id = str(raw.get("id", "")).strip()
        if not case_id or case_id in seen:
            raise ValueError(f"id de caso vacio o duplicado: {case_id!r}")
        seen.add(case_id)
        result.append(
            BenchmarkCase(
                id=case_id,
                instruction=str(raw["instruction"]),
                facts=tuple(str(item) for item in raw.get("facts", [])),
                filler=str(raw.get("filler", "")),
                target_chars=max(1, int(raw.get("target_chars", 1))),
                max_tokens=max(1, int(raw.get("max_tokens", 512))),
                expected_terms=tuple(str(item) for item in raw.get("expected_terms", [])),
                expected_json_fields=tuple(
                    str(item) for item in raw.get("expected_json_fields", [])
                ),
            )
        )
    return result


def materialize_case(case: BenchmarkCase) -> str:
    """Genera entrada determinista hasta el tamaño objetivo sin datos externos."""
    core = "\n".join(case.facts)
    filler = case.filler.strip() or "Contexto neutro para medir procesamiento de prompt."
    chunks = [core] if core else []
    index = 1
    while len("\n".join(chunks)) < case.target_chars:
        chunks.append(f"Nota contextual {index}: {filler}")
        index += 1
    return "\n".join(chunks)[: case.target_chars]


def parse_prometheus_metrics(text: str) -> dict[str, float]:
    """Extrae solo gauges operativos agregando series repetidas por suma."""
    values: dict[str, float] = {}
    for line in text.splitlines():
        match = _METRIC_RE.match(line.strip())
        if not match or match.group("name") not in _TRACKED_METRICS:
            continue
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        name = match.group("name")
        values[name] = values.get(name, 0.0) + value
    return values


def score_response(case: BenchmarkCase, response: str) -> dict[str, Any]:
    """Calcula señales simples; la revisión semántica sigue siendo humana."""
    lower = response.casefold()
    matched = [term for term in case.expected_terms if term.casefold() in lower]
    score: dict[str, Any] = {
        "expected_terms": len(case.expected_terms),
        "matched_terms": len(matched),
        "term_coverage": round(len(matched) / len(case.expected_terms), 4)
        if case.expected_terms
        else None,
    }
    if case.expected_json_fields:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
        try:
            payload = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            payload = None
        score["json_valid"] = isinstance(payload, dict)
        score["json_fields_present"] = (
            sorted(field for field in case.expected_json_fields if field in payload)
            if isinstance(payload, dict)
            else []
        )
    return score


class MetricsSampler:
    """Muestrea /metrics durante la request para no confundir before/after con el pico."""

    def __init__(
        self, url: str, interval: float = 0.25, headers: dict[str, str] | None = None
    ) -> None:
        self.url = url
        self.interval = interval
        self.headers = headers or {}
        self.samples: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> MetricsSampler:
        def sample() -> None:
            while not self._stop.is_set():
                try:
                    response = httpx.get(self.url, timeout=1.0, headers=self.headers)
                    if response.is_success:
                        self.samples.append(parse_prometheus_metrics(response.text))
                except httpx.HTTPError:
                    pass
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def peaks(self) -> dict[str, float]:
        names = {name for sample in self.samples for name in sample}
        return {name: max(sample.get(name, 0.0) for sample in self.samples) for name in names}


def _root_url(base_url: str) -> str:
    clean = base_url.rstrip("/")
    return clean[:-3] if clean.endswith("/v1") else clean


def run_benchmark(args: argparse.Namespace) -> int:
    cases = load_cases(Path(args.cases))
    selected = set(args.case or [])
    if selected:
        unknown = selected - {case.id for case in cases}
        if unknown:
            raise ValueError(f"casos desconocidos: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case.id in selected]

    output = Path(args.output)
    if output.exists() and not args.append:
        print(f"error: {output} ya existe; usa --append o elige otra ruta")
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)

    base_url = (args.endpoint or config.BASE_URL).rstrip("/")
    metrics_url = f"{_root_url(base_url)}/metrics"
    headers = {"Content-Type": "application/json"}
    api_key = args.api_key or config.API_KEY
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    failures = 0
    with (
        httpx.Client(timeout=args.timeout, headers=headers) as client,
        output.open("a", encoding="utf-8") as sink,
    ):
        for case in cases:
            content = materialize_case(case)
            prompt_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            for run in range(1, args.runs + 1):
                payload = {
                    "model": args.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Cumple el formato pedido y no inventes datos.",
                        },
                        {
                            "role": "user",
                            "content": f"{case.instruction}\n\nCONTENIDO:\n{content}",
                        },
                    ],
                    "temperature": 0.0,
                    "seed": args.seed,
                    "max_tokens": case.max_tokens,
                }
                if args.reasoning_effort:
                    payload["chat_template_kwargs"] = {"reasoning_effort": args.reasoning_effort}
                started = time.perf_counter()
                response_text = ""
                error: str | None = None
                usage: dict[str, Any] = {}
                timings: dict[str, Any] = {}
                finish_reason: str | None = None
                with MetricsSampler(metrics_url, args.sample_interval, headers) as sampler:
                    try:
                        response = client.post(f"{base_url}/chat/completions", json=payload)
                        response.raise_for_status()
                        data = response.json()
                        choice = data["choices"][0]
                        response_text = str(choice["message"]["content"])
                        finish_reason = choice.get("finish_reason")
                        usage = data.get("usage") or {}
                        timings = data.get("timings") or {}
                    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                        error = f"{type(exc).__name__}: {exc}"
                        if isinstance(exc, httpx.HTTPStatusError):
                            detail = exc.response.text.strip().replace("\n", " ")[:500]
                            if detail:
                                error = f"{error} · backend={detail}"
                        failures += 1
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                record: dict[str, Any] = {
                    "schema_version": 1,
                    "ts": datetime.now(UTC).isoformat(),
                    "label": args.label,
                    "model": args.model,
                    "variant": {
                        "quantization": args.quantization,
                        "context_size": args.context_size,
                        "n_cpu_moe": args.n_cpu_moe,
                        "llama_swap_version": args.llama_swap_version,
                        "llama_server_version": args.llama_server_version,
                        "reasoning_effort": args.reasoning_effort,
                    },
                    "case": case.id,
                    "run": run,
                    "thermal_state": "cold" if run == 1 else "hot",
                    "seed": args.seed,
                    "input_chars": len(content),
                    "input_sha256": prompt_hash,
                    "latency_ms": elapsed_ms,
                    "ok": error is None,
                    "error": error,
                    "finish_reason": finish_reason,
                    "usage": usage,
                    "timings": timings,
                    "metrics_peak": sampler.peaks(),
                    "score": score_response(case, response_text) if not error else None,
                    "response_chars": len(response_text),
                    "response_sha256": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
                }
                if args.save_responses:
                    record["response"] = response_text
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                sink.flush()
                state = "OK" if error is None else "ERROR"
                print(f"[{state}] {case.id} run={run} latency={elapsed_ms}ms")
    return 1 if failures else 0


def add_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "benchmark",
        help="Ejecuta un corpus sintetico contra un backend canary y escribe resultados JSONL.",
    )
    parser.add_argument("--model", required=True, help="id expuesto por el backend canary")
    parser.add_argument(
        "--label", required=True, help="etiqueta de config, p. ej. gptoss-ncmoe12-c8k"
    )
    parser.add_argument("--cases", required=True, help="archivo JSON del corpus versionado")
    parser.add_argument("--case", action="append", help="id de caso a ejecutar (repetible)")
    parser.add_argument("--runs", type=int, default=3, help="corridas por caso (default 3)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--quantization", default=None)
    parser.add_argument("--context-size", type=int, default=None)
    parser.add_argument("--n-cpu-moe", type=int, default=None)
    parser.add_argument("--llama-swap-version", default=None)
    parser.add_argument("--llama-server-version", default=None)
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high"),
        default=None,
        help="chat_template_kwargs para modelos razonadores como gpt-oss",
    )
    parser.add_argument(
        "--endpoint", default=None, help="BASE_URL /v1; default LOCAL_DELEGATE_BASE_URL"
    )
    parser.add_argument("--api-key", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--sample-interval", type=float, default=0.25)
    parser.add_argument("--output", required=True, help="JSONL de salida")
    parser.add_argument("--append", action="store_true")
    parser.add_argument(
        "--save-responses",
        action="store_true",
        help="guarda respuestas completas; el corpus incluido es sintetico",
    )
    parser.set_defaults(func=run_benchmark)
