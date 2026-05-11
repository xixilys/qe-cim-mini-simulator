#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import compare_qe_gold_correctness as compare


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = ROOT / "docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize QE baseline metadata/stdout inputs into the canonical JSON "
            "shape consumed by the QE gold correctness lane."
        )
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=None,
        help="Optional QE metadata.json path.",
    )
    parser.add_argument(
        "--stdout",
        type=Path,
        default=None,
        help="Optional QE stdout.out path. Overrides metadata-derived stdout path when given.",
    )
    parser.add_argument(
        "--case-id",
        default=None,
        help="Optional explicit case_id override.",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help=f"Tolerance schema JSON path (default: {DEFAULT_SCHEMA}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output JSON path. Defaults to stdout.",
    )
    return parser.parse_args()


def resolve_payload(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if args.metadata is None and args.stdout is None:
        raise ValueError("at least one of --metadata or --stdout is required")

    metadata_payload: dict[str, Any] | None = None
    payload: dict[str, Any] = {}
    if args.metadata is not None:
        metadata_payload = compare.load_json(args.metadata)
        if not isinstance(metadata_payload, dict):
            raise ValueError("metadata payload must be a JSON object")
        payload.update(metadata_payload)

    if args.stdout is not None:
        payload["stdout_file"] = str(args.stdout)
    if args.case_id is not None:
        payload["case_id"] = args.case_id
    return payload, metadata_payload


def canonical_case_id(payload: dict[str, Any], normalized: dict[str, Any]) -> str:
    case_id = normalized.get("case_id") or payload.get("case_id")
    if case_id:
        return str(case_id)
    stdout_file = payload.get("stdout_file")
    if stdout_file:
        return Path(str(stdout_file)).resolve().parent.name
    return "qe_gold_case"


def build_output_payload(
    args: argparse.Namespace,
    payload: dict[str, Any],
    metadata_payload: dict[str, Any] | None,
    schema: dict[str, Any],
) -> dict[str, Any]:
    normalized, details = compare.resolve_fields(payload, schema, "baseline")
    stdout_path = compare.discover_stdout_path(payload, schema)
    stdout_values = compare.parse_qe_stdout(stdout_path, schema) if stdout_path is not None else {}

    missing_required = []
    for field_spec in schema["fields"]:
        if not field_spec.get("required", False):
            continue
        name = field_spec["name"]
        if not details[name]["found"]:
            missing_required.append(name)
    if missing_required:
        raise ValueError(
            "missing required canonical QE gold fields: " + ", ".join(missing_required)
        )

    final = {
        "total_energy_ry": normalized["final_total_energy_ry"],
        "residual_threshold_reached": normalized["final_residual_threshold_reached"],
        "converged": normalized["final_converged"],
    }
    if "scf_iterations" in normalized:
        final["scf_iterations"] = normalized["scf_iterations"]
    if "final_estimated_scf_accuracy_ry" in stdout_values:
        final["estimated_scf_accuracy_ry"] = stdout_values["final_estimated_scf_accuracy_ry"]

    field_sources = {}
    for name, info in details.items():
        field_sources[name] = {
            "found": info["found"],
            "source": info["source"],
            "source_path": info["source_path"],
            "note": info["note"],
        }

    metadata = {
        "source_kind": "qe_gold_baseline",
        "metadata_file": None if args.metadata is None else str(args.metadata.resolve()),
        "stdout_file": None if stdout_path is None else str(stdout_path.resolve()),
        "normalizer_script": str(Path(__file__).resolve()),
        "tolerance_schema": str(args.schema.resolve()),
        "field_sources": field_sources,
    }
    if metadata_payload is not None:
        if "exit_code" in metadata_payload:
            metadata["qe_exit_code"] = metadata_payload["exit_code"]
        if "duration_sec" in metadata_payload:
            metadata["qe_duration_sec"] = metadata_payload["duration_sec"]
        if "input_file" in metadata_payload:
            metadata["input_file"] = metadata_payload["input_file"]
        if "pw_bin" in metadata_payload:
            metadata["pw_bin"] = metadata_payload["pw_bin"]

    return {
        "schema_version": "qe_gold_canonical_result_v0",
        "case_id": canonical_case_id(payload, normalized),
        "final": final,
        "metadata": metadata,
    }


def main() -> int:
    args = parse_args()
    try:
        payload, metadata_payload = resolve_payload(args)
        schema = compare.load_json(args.schema)
        output_payload = build_output_payload(args, payload, metadata_payload, schema)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    encoded = json.dumps(output_payload, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(f"[ok] wrote canonical QE gold JSON: {args.output}")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
