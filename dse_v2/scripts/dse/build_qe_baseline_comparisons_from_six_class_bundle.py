#!/usr/bin/env python3
"""Build pure-software QE baseline-comparison rows from an admitted six-SCF bundle.

The six-class reference bundle builder already runs real ``pw.x`` and records
final reference-output hashes.  The accelerated numeric evidence collector,
however, consumes row-local ``baseline_comparison.json`` files.  This adapter
bridges those two evidence surfaces without relaxing either gate: a baseline
comparison is admitted only when the bundle case has a final local QE reference
output, the output file exists, its hash matches the manifest, and QE reported
``JOB DONE`` plus SCF convergence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.dft_scf_workstreams import STRICT_DFT_QE_WORKLOAD_CLASSES  # noqa: E402
from dse_v2.reference_workloads.qe_accelerated_evidence import parse_qe_stdout_metrics  # noqa: E402


BASELINE_COMPARISON_SCHEMA = "dse.qe_pure_software_baseline_result.v1"
INDEX_SCHEMA = "dse.qe_pure_software_baseline_from_six_class_bundle_index.v1"
MATERIALIZATION_SCHEMA = "dse.dft_scf.six_class_qe_baseline_materialization.v1"
MATERIALIZATION_VALIDATION_SCHEMA = "dse.dft_scf.six_class_qe_baseline_materialization_validation.v1"
MATERIALIZATION_STATUS_SCHEMA = "dse.dft_scf.six_class_qe_baseline_materialization_status.v1"
MANIFEST_NAME = "dft_scf_six_class_bundle_manifest.json"
INDEX_NAME = "qe_baseline_comparison_index.json"
MATERIALIZATION_NAME = "dft_scf_six_class_qe_baseline_materialization.json"
MATERIALIZATION_VALIDATION_NAME = "dft_scf_six_class_qe_baseline_materialization_validation.json"
MATERIALIZATION_STATUS_NAME = "dft_scf_six_class_qe_baseline_materialization_status.json"
FALSE_CLAIM_FLAGS = {
    "hardware_acceleration": False,
    "hardware_acceleration_evidence": False,
    "fpga_ppa": False,
    "fpga_ppa_evidence": False,
    "asic_ppa": False,
    "asic_ppa_evidence": False,
    "l4_value": False,
    "l4_value_evidence": False,
    "trusted_final_claim": False,
    "hardware_completion": False,
    "hardware_completion_eligible": False,
    "release_completion": False,
    "release_completion_eligible": False,
    "deliverable_complete": False,
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalize_class_id(value: Any) -> str:
    text = str(value or "").strip()
    return text[: -len("_case")] if text.endswith("_case") else text


def _case_id(case: Mapping[str, Any], class_id: str) -> str:
    return str(case.get("case_id") or case.get("workload_case_id") or f"{class_id}_case")


def _reference_output_path(bundle_dir: Path, reference_output: Mapping[str, Any]) -> Path | None:
    raw_path = reference_output.get("path")
    if not raw_path:
        return None
    path = Path(str(raw_path))
    return path if path.is_absolute() else bundle_dir / path


def _qe_job_done_marker_present(output_text: str) -> bool:
    return "JOB DONE" in (output_text or "").upper()


def _qe_scf_converged_marker_present(output_text: str) -> bool:
    return "CONVERGENCE HAS BEEN ACHIEVED" in (output_text or "").upper()


def _build_case_baseline(
    *,
    bundle_dir: Path,
    case: Mapping[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    class_id = _normalize_class_id(case.get("class_id") or case.get("workload_class") or case.get("case_id"))
    case_id = _case_id(case, class_id)
    reference_output = case.get("reference_output", {})
    reference_output_map = reference_output if isinstance(reference_output, Mapping) else {}
    output_path = _reference_output_path(bundle_dir, reference_output_map)
    blockers: list[str] = []

    if class_id not in STRICT_DFT_QE_WORKLOAD_CLASSES:
        blockers.append(f"strict_scf_class_id_not_in_required_suite:{class_id or 'missing'}")
    if reference_output_map.get("hash_final") is not True:
        blockers.append("reference_output_hash_not_final")
    if reference_output_map.get("job_done") is not True:
        blockers.append("reference_output_job_done_not_true")
    if reference_output_map.get("scf_converged") is not True:
        blockers.append("reference_output_scf_converged_not_true")
    if not output_path or not output_path.exists():
        blockers.append(f"reference_output_missing:{output_path}")
        output_text = ""
        output_sha256 = None
    else:
        output_text = output_path.read_text(encoding="utf-8", errors="replace")
        output_sha256 = _sha256_file(output_path)
        expected_sha256 = reference_output_map.get("sha256")
        if expected_sha256 and output_sha256 != expected_sha256:
            blockers.append("reference_output_sha256_mismatch")
        job_done_marker = _qe_job_done_marker_present(output_text)
        scf_converged_marker = _qe_scf_converged_marker_present(output_text)
        if reference_output_map.get("job_done") is True and not job_done_marker:
            blockers.append("reference_output_job_done_marker_missing")
        if reference_output_map.get("job_done") is not True and job_done_marker:
            blockers.append("reference_output_job_done_manifest_disagrees_with_marker")
        if reference_output_map.get("scf_converged") is True and not scf_converged_marker:
            blockers.append("reference_output_scf_converged_marker_missing")
        if reference_output_map.get("scf_converged") is not True and scf_converged_marker:
            blockers.append("reference_output_scf_converged_manifest_disagrees_with_marker")

    metrics = parse_qe_stdout_metrics(output_text)
    if "total_energy_ry" not in metrics:
        blockers.append("baseline_metric_missing:total_energy_ry")

    passed = not blockers
    command = [str(item) for item in reference_output_map.get("command", []) or []]
    baseline = {
        "schema_version": BASELINE_COMPARISON_SCHEMA,
        "case_id": case_id,
        "class_id": class_id,
        "status": "passed" if passed else "blocked",
        "baseline_status": "real_qe_baseline" if passed else "qe_reference_bundle_baseline_not_admitted",
        "pure_software_qe_baseline": passed,
        "qe_command": command,
        "reference_bundle_dir": str(bundle_dir),
        "reference_output_path": str(output_path) if output_path else None,
        "reference_output_hash": output_sha256,
        "reference_output_manifest_entry": dict(reference_output_map),
        "steps": [
            {
                "step_id": "stage_00_scf",
                "program": command[0] if command else "pw.x",
                "command": command,
                "status": "passed" if passed else "blocked",
                "returncode": 0 if passed else reference_output_map.get("returncode"),
                "stdout_path": str(output_path) if output_path else None,
                "stderr_path": None,
                "metrics": metrics,
                "blockers": sorted(dict.fromkeys(blockers)),
            }
        ],
        "returncode": 0 if passed else reference_output_map.get("returncode"),
        "timeout": False,
        "elapsed_seconds": None,
        "performance_metrics": {
            "terminal_step_metrics": metrics,
            "total_elapsed_seconds": None,
        },
        "stdout_path": str(output_path) if output_path else None,
        "stderr_path": None,
        "blockers": sorted(dict.fromkeys(blockers)),
        "claim_boundary": (
            "This is a pure-software QE baseline-comparison view of an already admitted "
            "six-SCF reference-bundle output. It does not prove accelerated correctness, "
            "kernel replacement, PPA, or DSE completion."
        ),
    }
    out_path = out_dir / case_id / "baseline_comparison.json"
    _write_json(out_path, baseline)
    return {
        "case_id": case_id,
        "class_id": class_id,
        "status": baseline["status"],
        "pure_software_qe_baseline": passed,
        "baseline_comparison": str(out_path),
        "reference_output_path": str(output_path) if output_path else None,
        "blockers": baseline["blockers"],
    }


def _count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _resolve_record_path(raw_path: Any, *, index_path: Path) -> Path | None:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    return path if path.is_absolute() else index_path.parent / path


def _row_blockers(value: Any) -> list[str]:
    return [str(item) for item in value or []]


def _baseline_row_consistency_errors(
    *,
    index_path: Path,
    record: Mapping[str, Any],
    case_id: str,
    class_id: str,
) -> list[str]:
    errors: list[str] = []
    row_path = _resolve_record_path(record.get("baseline_comparison"), index_path=index_path)
    if row_path is None:
        return [f"baseline_comparison_path_missing:{case_id}"]
    if not row_path.exists() or not row_path.is_file():
        return [f"baseline_comparison_missing:{case_id}:{row_path}"]
    try:
        row = _load_json(row_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"baseline_comparison_unreadable:{case_id}:{type(exc).__name__}"]
    comparisons = {
        "case_id": str(row.get("case_id") or ""),
        "class_id": _normalize_class_id(row.get("class_id")),
        "status": str(row.get("status") or ""),
        "pure_software_qe_baseline": row.get("pure_software_qe_baseline") is True,
        "blockers": _row_blockers(row.get("blockers")),
    }
    expected = {
        "case_id": case_id,
        "class_id": class_id,
        "status": str(record.get("status") or ""),
        "pure_software_qe_baseline": record.get("pure_software_qe_baseline") is True,
        "blockers": _row_blockers(record.get("blockers")),
    }
    for key, expected_value in expected.items():
        if comparisons[key] != expected_value:
            errors.append(f"baseline_comparison_mismatch:{case_id}:{key}")
    return errors


def _materialization_errors(
    index: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    index_path: Path,
) -> list[str]:
    errors: list[str] = []
    expected_class_ids = list(STRICT_DFT_QE_WORKLOAD_CLASSES)
    observed_class_ids = [_normalize_class_id(record.get("class_id")) for record in records]
    observed_counts = _count_values(observed_class_ids)

    if index.get("schema_version") != INDEX_SCHEMA:
        errors.append("index_schema_version_mismatch")
    if index.get("status") != "passed":
        errors.append("index_status_not_passed")
    if index.get("passed") is not True:
        errors.append("index_passed_not_true")
    if int(index.get("case_count", -1) or -1) != len(records):
        errors.append(f"case_count_mismatch:{index.get('case_count')}:{len(records)}")
    passed_records = [record for record in records if record.get("status") == "passed"]
    if int(index.get("passed_case_count", -1) or -1) != len(passed_records):
        errors.append(f"passed_case_count_mismatch:{index.get('passed_case_count')}:{len(passed_records)}")

    for class_id in expected_class_ids:
        if observed_counts.get(class_id, 0) == 0:
            errors.append(f"missing_strict_scf_class_id:{class_id}")
        if observed_counts.get(class_id, 0) > 1:
            errors.append(f"duplicate_strict_scf_class_id:{class_id}")
    for class_id in sorted(class_id for class_id in observed_counts if class_id not in expected_class_ids):
        errors.append(f"unexpected_strict_scf_class_id:{class_id or 'missing'}")

    for missing_class_id in index.get("missing_strict_scf_class_ids", []) or []:
        errors.append(f"source_index_missing_strict_scf_class_id:{missing_class_id}")
    for blocker in index.get("blockers", []) or []:
        errors.append(f"source_index_blocker:{blocker}")
    for flag in FALSE_CLAIM_FLAGS:
        if index.get(flag) is True:
            errors.append(f"source_index_attempted_claim_upgrade:{flag}")

    for record in records:
        class_id = _normalize_class_id(record.get("class_id"))
        case_id = str(record.get("case_id") or f"{class_id}_case")
        if record.get("status") != "passed":
            errors.append(f"record_not_passed:{case_id}")
        if record.get("pure_software_qe_baseline") is not True:
            errors.append(f"record_not_pure_software_qe_baseline:{case_id}")
        for blocker in record.get("blockers", []) or []:
            errors.append(f"record_blocker:{case_id}:{blocker}")
        for flag in FALSE_CLAIM_FLAGS:
            if record.get(flag) is True:
                errors.append(f"record_attempted_claim_upgrade:{case_id}:{flag}")
        errors.extend(
            _baseline_row_consistency_errors(
                index_path=index_path,
                record=record,
                case_id=case_id,
                class_id=class_id,
            )
        )

    return sorted(dict.fromkeys(errors))


def materialize_qe_baseline_triplet_from_index(index_path: Path) -> dict[str, Any]:
    index_path = Path(index_path)
    out_dir = index_path.parent
    index = _load_json(index_path)
    raw_records = index.get("records", []) or []
    records = [record for record in raw_records if isinstance(record, Mapping)]
    errors = _materialization_errors(index, records, index_path=index_path)
    valid = not errors
    passed_records = [record for record in records if record.get("status") == "passed"]
    blocked_records = [record for record in records if record.get("status") != "passed"]
    blocker_id_counts = _count_values(
        str(blocker)
        for record in records
        for blocker in (record.get("blockers", []) or [])
    )
    class_records = [
        {
            "case_id": str(record.get("case_id") or ""),
            "class_id": _normalize_class_id(record.get("class_id")),
            "status": str(record.get("status") or "unknown"),
            "pure_software_qe_baseline": record.get("pure_software_qe_baseline") is True,
            "baseline_comparison": record.get("baseline_comparison"),
            "reference_output_path": record.get("reference_output_path"),
            "blockers": list(record.get("blockers", []) or []),
        }
        for record in records
    ]
    materialization_path = out_dir / MATERIALIZATION_NAME
    validation_path = out_dir / MATERIALIZATION_VALIDATION_NAME
    status_path = out_dir / MATERIALIZATION_STATUS_NAME
    materialization = {
        "schema_version": MATERIALIZATION_SCHEMA,
        "status": "passed" if valid else "blocked",
        "source_index": str(index_path),
        "source_index_sha256": _sha256_file(index_path),
        "case_count": len(records),
        "passed_case_count": len(passed_records) if valid else 0,
        "blocked_case_count": len(blocked_records) if valid else len(records),
        "strict_scf_class_ids": list(STRICT_DFT_QE_WORKLOAD_CLASSES),
        "materialized_class_ids": [_normalize_class_id(record.get("class_id")) for record in records],
        "records": class_records,
        "blocker_id_counts": blocker_id_counts,
        "validation_errors": errors,
        "evidence_classification": "pure_software_qe_baseline_value_evidence",
        "pure_software_qe_baseline": valid,
        "pure_software_qe_baseline_only": valid,
        **FALSE_CLAIM_FLAGS,
        "claim_boundary": (
            "This artifact materializes strict six-class QE baseline rows as pure-software "
            "baseline/value evidence only. It does not prove hardware acceleration, FPGA PPA, "
            "ASIC PPA, L4 value, trusted final claims, hardware completion, release completion, "
            "or deliverable completion."
        ),
    }
    validation = {
        "schema_version": MATERIALIZATION_VALIDATION_SCHEMA,
        "valid": valid,
        "status": "passed" if valid else "blocked",
        "source_index": str(index_path),
        "materialization_artifact": str(materialization_path),
        "errors": errors,
        "claim_flags": dict(FALSE_CLAIM_FLAGS),
        "claim_boundary": materialization["claim_boundary"],
    }
    status = {
        "schema_version": MATERIALIZATION_STATUS_SCHEMA,
        "status": "passed" if valid else "blocked",
        "source_index": str(index_path),
        "materialization_artifact": str(materialization_path),
        "validation_artifact": str(validation_path),
        "valid": valid,
        "errors": errors,
        "case_count": materialization["case_count"],
        "passed_case_count": materialization["passed_case_count"],
        "blocked_case_count": materialization["blocked_case_count"],
        "claim_flags": dict(FALSE_CLAIM_FLAGS),
        **FALSE_CLAIM_FLAGS,
        "claim_boundary": materialization["claim_boundary"],
    }
    _write_json(materialization_path, materialization)
    _write_json(validation_path, validation)
    _write_json(status_path, status)
    return materialization


def build_baseline_comparisons_from_six_class_bundle(bundle_dir: Path, out_dir: Path) -> dict[str, Any]:
    bundle_dir = Path(bundle_dir)
    out_dir = Path(out_dir)
    manifest = _load_json(bundle_dir / MANIFEST_NAME)
    cases = [case for case in manifest.get("cases", []) or [] if isinstance(case, Mapping)]
    records = [_build_case_baseline(bundle_dir=bundle_dir, case=case, out_dir=out_dir) for case in cases]
    class_ids = {str(record.get("class_id")) for record in records}
    missing_class_ids = [class_id for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES if class_id not in class_ids]
    blocker_set = set()
    for record in records:
        blocker_set.update(str(blocker) for blocker in record.get("blockers", []) or [])
    for class_id in missing_class_ids:
        blocker_set.add(f"strict_scf_class_missing:{class_id}")
    passed_records = [record for record in records if record.get("status") == "passed"]
    status = "passed" if len(passed_records) == len(STRICT_DFT_QE_WORKLOAD_CLASSES) and not blocker_set else "blocked"
    index = {
        "schema_version": INDEX_SCHEMA,
        "status": status,
        "passed": status == "passed",
        "bundle_dir": str(bundle_dir),
        "out_dir": str(out_dir),
        "case_count": len(records),
        "passed_case_count": len(passed_records),
        "strict_scf_class_ids": list(STRICT_DFT_QE_WORKLOAD_CLASSES),
        "missing_strict_scf_class_ids": missing_class_ids,
        "records": records,
        "blockers": sorted(blocker_set),
        "claim_boundary": (
            "These rows are baseline-comparison inputs for accelerated evidence collection only. "
            "They cannot substitute for trusted accelerated rows or final hardware DSE evidence."
        ),
    }
    _write_json(out_dir / INDEX_NAME, index)
    materialize_qe_baseline_triplet_from_index(out_dir / INDEX_NAME)
    return index


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--index-path", type=Path)
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args(argv)
    if args.index_path:
        materialization = materialize_qe_baseline_triplet_from_index(args.index_path)
        print(json.dumps(materialization, indent=2, sort_keys=True))
        return 2 if args.fail_on_blocked and materialization["status"] != "passed" else 0
    if not args.bundle_dir or not args.out_dir:
        parser.error("either --index-path or both --bundle-dir and --out-dir are required")
    index = build_baseline_comparisons_from_six_class_bundle(args.bundle_dir, args.out_dir)
    print(json.dumps(index, indent=2, sort_keys=True))
    return 2 if args.fail_on_blocked and not index["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
