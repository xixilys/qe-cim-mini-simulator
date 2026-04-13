#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = ROOT / "docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare a candidate result JSON against a QE gold baseline JSON under "
            "the frozen QE numerical tolerance schema."
        )
    )
    parser.add_argument("--baseline", type=Path, required=True, help="Baseline JSON path.")
    parser.add_argument("--candidate", type=Path, required=True, help="Candidate JSON path.")
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help=f"Tolerance schema JSON path (default: {DEFAULT_SCHEMA}).",
    )
    parser.add_argument(
        "--case-id",
        default=None,
        help="Optional case_id selector when the input JSON is a list or a dict with a top-level 'cases' list.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the machine-readable comparison report JSON.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def select_case(payload: Any, case_id: str | None) -> Any:
    if case_id is None:
        return payload
    candidates: list[dict[str, Any]] = []
    if isinstance(payload, list):
        candidates = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        candidates = [item for item in payload["cases"] if isinstance(item, dict)]
    else:
        return payload

    for item in candidates:
        if item.get("case_id") == case_id:
            return item
    raise KeyError(f"case_id '{case_id}' not found in payload")


def get_by_path(payload: Any, dotted_path: str) -> tuple[bool, Any]:
    current = payload
    for part in dotted_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                return False, None
            if index < 0 or index >= len(current):
                return False, None
            current = current[index]
            continue
        return False, None
    return True, current


def normalize_float(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("bool is not a float")
    if isinstance(value, (int, float)):
        out = float(value)
    elif isinstance(value, str):
        out = float(value.strip().replace("D", "E").replace("d", "e"))
    else:
        raise ValueError(f"cannot coerce {type(value).__name__} to float")
    if not math.isfinite(out):
        raise ValueError("float is not finite")
    return out


def normalize_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("bool is not an int")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return int(value.strip())
    raise ValueError(f"cannot coerce {type(value).__name__} to int")


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "y", "1", "converged", "pass"}:
            return True
        if lowered in {"false", "no", "n", "0", "not_converged", "fail"}:
            return False
    raise ValueError(f"cannot coerce {value!r} to bool")


def normalize_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    return str(value)


def coerce_value(kind: str, value: Any) -> Any:
    if kind == "float":
        return normalize_float(value)
    if kind == "int":
        return normalize_int(value)
    if kind == "bool":
        return normalize_bool(value)
    if kind == "string":
        return normalize_string(value)
    raise ValueError(f"unsupported field kind: {kind}")


def discover_stdout_path(payload: Any, schema: dict[str, Any]) -> Path | None:
    stdout_cfg = schema.get("stdout_fallback", {})
    if not stdout_cfg.get("enabled", False):
        return None
    for path in stdout_cfg.get("stdout_path_candidates", []):
        found, value = get_by_path(payload, path)
        if found and value:
            stdout_path = Path(str(value))
            if stdout_path.exists():
                return stdout_path
    return None


def parse_qe_stdout(stdout_path: Path, schema: dict[str, Any]) -> dict[str, Any]:
    regex_map = schema.get("stdout_fallback", {}).get("regex", {})
    total_energy_re = re.compile(regex_map["total_energy_ry"])
    scf_acc_re = re.compile(regex_map["estimated_scf_accuracy_ry"])
    converged_re = re.compile(regex_map["converged_iterations"])
    iter_re = re.compile(regex_map["iteration_number"])

    total_energy: float | None = None
    scf_acc: float | None = None
    converged = False
    converged_iterations: int | None = None
    last_iteration_number: int | None = None

    for line in stdout_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = total_energy_re.match(line)
        if match:
            total_energy = normalize_float(match.group("value"))
            continue
        match = scf_acc_re.match(line)
        if match:
            scf_acc = normalize_float(match.group("value"))
            continue
        match = converged_re.search(line)
        if match:
            converged = True
            converged_iterations = normalize_int(match.group("value"))
            continue
        match = iter_re.match(line)
        if match:
            last_iteration_number = normalize_int(match.group("value"))

    result: dict[str, Any] = {}
    if total_energy is not None:
        result["final_total_energy_ry"] = total_energy
    if scf_acc is not None:
        result["final_estimated_scf_accuracy_ry"] = scf_acc
    result["final_converged"] = converged
    result["final_residual_threshold_reached"] = converged
    if converged_iterations is not None:
        result["scf_iterations"] = converged_iterations
    elif last_iteration_number is not None:
        result["scf_iterations"] = last_iteration_number
    return result


def resolve_direct_value(
    payload: Any,
    field_spec: dict[str, Any],
    side_key: str,
) -> tuple[bool, Any, str | None, str | None]:
    paths = field_spec.get(side_key, [])
    for dotted_path in paths:
        found, raw_value = get_by_path(payload, dotted_path)
        if not found:
            continue
        try:
            value = coerce_value(field_spec["kind"], raw_value)
        except ValueError as exc:
            return False, None, dotted_path, str(exc)
        return True, value, dotted_path, None
    return False, None, None, None


def resolve_fields(payload: Any, schema: dict[str, Any], side: str) -> tuple[dict[str, Any], dict[str, Any]]:
    side_key = "baseline_paths" if side == "baseline" else "candidate_paths"
    stdout_path = discover_stdout_path(payload, schema)
    stdout_values = parse_qe_stdout(stdout_path, schema) if stdout_path is not None else {}

    normalized: dict[str, Any] = {}
    details: dict[str, Any] = {}

    for field_spec in schema["fields"]:
        name = field_spec["name"]
        found, value, source_path, error = resolve_direct_value(payload, field_spec, side_key)
        source = "json_path"
        note = None

        if error is not None:
            details[name] = {
                "found": False,
                "value": None,
                "source": source,
                "source_path": source_path,
                "note": error,
            }
            continue

        if not found and name in stdout_values:
            try:
                value = coerce_value(field_spec["kind"], stdout_values[name])
                found = True
                source = "stdout_fallback"
                source_path = str(stdout_path) if stdout_path is not None else None
            except ValueError as exc:
                note = str(exc)

        if not found:
            fallback_name = field_spec.get("fallback_from_field")
            if fallback_name and fallback_name in normalized:
                value = normalized[fallback_name]
                found = True
                source = "field_fallback"
                source_path = fallback_name
                note = field_spec.get("fallback_label")

        if found:
            normalized[name] = value
        details[name] = {
            "found": found,
            "value": value if found else None,
            "source": source,
            "source_path": source_path,
            "note": note,
        }

    return normalized, details


def compare_field(field_spec: dict[str, Any], baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    name = field_spec["name"]
    report_only = bool(field_spec.get("report_only", False))
    required = bool(field_spec.get("required", False))
    baseline_found = baseline[name]["found"]
    candidate_found = candidate[name]["found"]

    result = {
        "name": name,
        "required": required,
        "report_only": report_only,
        "comparison": field_spec["comparison"],
        "baseline": baseline[name],
        "candidate": candidate[name],
        "status": "pass",
        "message": "",
    }

    if not baseline_found or not candidate_found:
        if required:
            result["status"] = "fail"
            result["message"] = "missing required field"
        else:
            result["status"] = "missing"
            result["message"] = "optional/report-only field missing"
        return result

    b = baseline[name]["value"]
    c = candidate[name]["value"]
    comparison = field_spec["comparison"]

    if comparison in {"exact", "exact_if_both_present"}:
        passed = b == c
        result["status"] = "pass" if passed else "fail"
        result["message"] = "exact match" if passed else f"mismatch: baseline={b!r}, candidate={c!r}"
        return result

    if comparison == "abs_or_rel":
        abs_tol = normalize_float(field_spec["abs_tol"])
        rel_tol = normalize_float(field_spec["rel_tol"])
        scale_floor = normalize_float(field_spec.get("scale_floor", 1.0))
        abs_err = abs(c - b)
        rel_err = abs_err / max(abs(b), scale_floor)
        threshold = max(abs_tol, rel_tol * max(abs(b), scale_floor))
        passed = abs_err <= threshold
        result.update(
            {
                "abs_tol": abs_tol,
                "rel_tol": rel_tol,
                "scale_floor": scale_floor,
                "abs_err": abs_err,
                "rel_err": rel_err,
                "effective_tol": threshold,
                "status": "pass" if passed else "fail",
                "message": (
                    f"abs_err={abs_err:.3e}, rel_err={rel_err:.3e}, effective_tol={threshold:.3e}"
                ),
            }
        )
        return result

    raise ValueError(f"unsupported comparison mode: {comparison}")


def build_report(
    baseline_file: Path,
    candidate_file: Path,
    schema_file: Path,
    case_id: str | None,
    schema: dict[str, Any],
    baseline_details: dict[str, Any],
    candidate_details: dict[str, Any],
) -> dict[str, Any]:
    field_results = [
        compare_field(field_spec, baseline_details, candidate_details)
        for field_spec in schema["fields"]
    ]

    required_results = [item for item in field_results if item["required"]]
    overall_pass = all(item["status"] == "pass" for item in required_results)

    report = {
        "schema_name": schema.get("schema_name"),
        "schema_version": schema.get("schema_version"),
        "baseline_file": str(baseline_file),
        "candidate_file": str(candidate_file),
        "case_id": case_id,
        "overall_pass": overall_pass,
        "pass_rule": schema.get("pass_rule"),
        "field_results": field_results,
        "summary": {
            "required_fields": len(required_results),
            "required_passed": sum(1 for item in required_results if item["status"] == "pass"),
            "required_failed": sum(1 for item in required_results if item["status"] == "fail"),
            "report_only_missing": sum(
                1 for item in field_results if item["report_only"] and item["status"] == "missing"
            ),
        },
        "schema_file": str(schema_file),
    }
    return report


def print_summary(report: dict[str, Any]) -> None:
    print(
        f"QE gold correctness: {'PASS' if report['overall_pass'] else 'FAIL'}"
    )
    if report.get("case_id"):
        print(f"case_id: {report['case_id']}")
    for item in report["field_results"]:
        status = item["status"].upper()
        print(f"- {item['name']}: {status} | {item['message']}")


def main() -> int:
    args = parse_args()
    schema = load_json(args.schema)
    baseline_payload = select_case(load_json(args.baseline), args.case_id)
    candidate_payload = select_case(load_json(args.candidate), args.case_id)

    baseline_normalized, baseline_details = resolve_fields(baseline_payload, schema, "baseline")
    candidate_normalized, candidate_details = resolve_fields(candidate_payload, schema, "candidate")

    report = build_report(
        args.baseline,
        args.candidate,
        args.schema,
        args.case_id or baseline_normalized.get("case_id") or candidate_normalized.get("case_id"),
        schema,
        baseline_details,
        candidate_details,
    )
    print_summary(report)

    if args.output is not None:
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote report: {args.output}")

    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
