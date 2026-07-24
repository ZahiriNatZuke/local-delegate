"""Tests del runner canary denso/MoE; no requieren backend real."""

from __future__ import annotations

import json

import pytest

from local_delegate import benchmark


def test_load_and_materialize_cases_reaches_target_without_private_input(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cases": [
                    {
                        "id": "one",
                        "instruction": "resume",
                        "facts": ["hecho ZX-41"],
                        "filler": "relleno",
                        "target_chars": 200,
                        "expected_terms": ["ZX-41"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    case = benchmark.load_cases(path)[0]
    content = benchmark.materialize_case(case)
    assert len(content) == 200
    assert "ZX-41" in content


def test_load_cases_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "cases.json"
    case = {"id": "same", "instruction": "x", "target_chars": 1}
    path.write_text(json.dumps({"schema_version": 1, "cases": [case, case]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicado"):
        benchmark.load_cases(path)


def test_parse_prometheus_metrics_aggregates_gpu_series_and_ignores_noise():
    text = """
# HELP ignored comment
llamaswap_memory_used_bytes 100
llamaswap_gpu_memory_used_bytes{id="0"} 40
llamaswap_gpu_memory_used_bytes{id="1"} 60
unrelated_metric 999
"""
    assert benchmark.parse_prometheus_metrics(text) == {
        "llamaswap_memory_used_bytes": 100.0,
        "llamaswap_gpu_memory_used_bytes": 100.0,
    }


def test_score_response_checks_terms_and_json_fields():
    case = benchmark.BenchmarkCase(
        id="extract",
        instruction="json",
        facts=(),
        filler="x",
        target_chars=1,
        max_tokens=10,
        expected_terms=("Aurora", "Camila"),
        expected_json_fields=("project", "owner"),
    )
    score = benchmark.score_response(case, '{"project":"Aurora","owner":"Camila"}')
    assert score["term_coverage"] == 1.0
    assert score["json_valid"] is True
    assert score["json_fields_present"] == ["owner", "project"]
