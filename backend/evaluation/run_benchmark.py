from __future__ import annotations

import json
import math
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.querying.duckdb_engine import DuckDbEngine
from app.security.access_control import AccessController
from app.services.askdata_service import AskDataService


EVALUATION_DIR = Path(__file__).resolve().parent
CASES_PATH = EVALUATION_DIR / "cases.json"
RESULTS_DIR = EVALUATION_DIR / "results"


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[rank], 3)


def canonical_value(value: Any) -> tuple[str, Any]:
    if value is None:
        return ("null", None)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float, Decimal)):
        return ("number", round(float(value), 6))
    return ("text", str(value))


def canonical_rows(rows: list[dict[str, Any]]) -> Counter[tuple[tuple[str, Any], ...]]:
    # SQL aliases are presentation details; compare each row's ordered values and
    # treat row order as irrelevant because not every question requests ordering.
    return Counter(tuple(canonical_value(value) for value in row.values()) for row in rows)


def results_equal(actual: list[dict[str, Any]], expected: list[dict[str, Any]]) -> bool:
    if len(actual) != len(expected):
        return False
    if actual and expected and len(actual[0]) != len(expected[0]):
        return False
    return canonical_rows(actual) == canonical_rows(expected)


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def main() -> None:
    suite = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    service = AskDataService()
    engine = DuckDbEngine()
    scope = AccessController().resolve("demo_analyst")
    records: list[dict[str, Any]] = []

    all_cases = [
        *(dict(case, expected="completed") for case in suite["clear_cases"]),
        *(dict(case, expected="waiting_clarification") for case in suite["ambiguous_cases"]),
    ]
    print(f"locked_suite={suite['version']} cases={len(all_cases)}", flush=True)

    for index, case in enumerate(all_cases, 1):
        started = time.perf_counter()
        error = None
        result = None
        try:
            result = service.submit(
                case["query"],
                session_id=f"eval-{suite['version']}-{case['id']}",
                user_id="demo_analyst",
            )
        except Exception as exc:  # preserve unexpected failures in the result file
            error = f"{type(exc).__name__}: {exc}"
        elapsed = round(time.perf_counter() - started, 3)

        record: dict[str, Any] = {
            "id": case["id"],
            "query": case["query"],
            "expected_status": case["expected"],
            "elapsed_seconds": elapsed,
            "exception": error,
        }
        if result is not None:
            retrieval = result.retrieval or {}
            hit_ids = [str(hit.get("doc_id")) for hit in retrieval.get("hits", [])]
            record.update({
                "actual_status": result.status,
                "route": result.route,
                "sql": result.sql,
                "analysis": result.analysis,
                "clarification": result.clarification.model_dump() if result.clarification else None,
                "retrieved_doc_ids": hit_ids,
                "stage_timings_ms": result.stage_timings_ms,
                "execution_log": result.execution_log,
            })
            if case["expected"] == "completed":
                required = set(case["required_fields"])
                hits = set(hit_ids)
                record["required_fields"] = sorted(required)
                record["recalled_required_fields"] = sorted(required & hits)
                record["field_recall"] = ratio(len(required & hits), len(required))
                record["complete_schema_recall"] = required <= hits
                gold = engine.execute("askdata_mock", case["gold_sql"], scope)
                record["gold_sql"] = case["gold_sql"]
                record["gold_execution_success"] = gold.success
                record["gold_rows"] = gold.rows
                record["actual_rows"] = result.rows
                record["result_match"] = bool(
                    result.status == "completed"
                    and gold.success
                    and results_equal(result.rows, gold.rows)
                )
        records.append(record)
        print(
            f"[{index:02d}/{len(all_cases)}] {case['id']} "
            f"status={record.get('actual_status', 'exception')} "
            f"match={record.get('result_match', '-')} time={elapsed}s",
            flush=True,
        )

    clear = [record for record in records if record["expected_status"] == "completed"]
    ambiguous = [record for record in records if record["expected_status"] == "waiting_clarification"]
    triggered = [record for record in records if record.get("actual_status") == "waiting_clarification"]
    required_total = sum(len(record.get("required_fields", [])) for record in clear)
    recalled_total = sum(len(record.get("recalled_required_fields", [])) for record in clear)
    true_clarifications = sum(record.get("actual_status") == "waiting_clarification" for record in ambiguous)
    completed = sum(record.get("actual_status") == "completed" for record in clear)
    matched = sum(record.get("result_match") is True for record in clear)
    latencies = [float(record["elapsed_seconds"]) for record in records]
    summary = {
        "suite_version": suite["version"],
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_calls": "real configured remote models",
        "clear_case_count": len(clear),
        "ambiguous_case_count": len(ambiguous),
        "schema_field_recall": ratio(recalled_total, required_total),
        "complete_schema_recall_rate": ratio(
            sum(record.get("complete_schema_recall") is True for record in clear), len(clear)
        ),
        "sql_execution_success_rate": ratio(completed, len(clear)),
        "result_match_rate": ratio(matched, len(clear)),
        "clarification_recall": ratio(true_clarifications, len(ambiguous)),
        "clarification_precision": ratio(true_clarifications, len(triggered)),
        "false_clarifications_on_clear_cases": sum(
            record.get("actual_status") == "waiting_clarification" for record in clear
        ),
        "latency_seconds": {
            "mean": round(statistics.mean(latencies), 3),
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "min": round(min(latencies), 3),
            "max": round(max(latencies), 3),
        },
    }
    payload = {"summary": summary, "records": records}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = RESULTS_DIR / f"benchmark-{suite['version']}-{timestamp}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_path = RESULTS_DIR / "latest.json"
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f"result_file={output_path}", flush=True)


if __name__ == "__main__":
    main()
