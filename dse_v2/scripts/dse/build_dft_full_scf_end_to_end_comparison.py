#!/usr/bin/env python3
"""Build strict full-SCF host+accelerator numerical comparison evidence.

This is the producer for the numerical gate consumed by
``build_dft_numerical_correctness_evidence.py --full-scf-comparison-evidence``.
It is intentionally fail-closed: historical h_psi-only, timing-only,
baseline-copy, fixture, or partial-suite evidence is recorded as progress but
cannot pass the full-SCF numerical comparison gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS  # noqa: E402
from dse_v2.codesign.dft_scf_workstreams import STRICT_DFT_QE_WORKLOAD_CLASSES  # noqa: E402
from dse_v2.reference_workloads.dft_full_scf_hybrid import (  # noqa: E402
    REQUIRED_HOST_BOUND_PHASE_IDS,
    REQUIRED_OVERHEAD_PHASE_IDS,
)
from dse_v2.reference_workloads.dft_full_scf_accounting import (  # noqa: E402
    TRUSTED_RUNTIME_TRACE_SOURCES,
    UNTRUSTED_RUNTIME_TRACE_SOURCES,
)


DEFAULT_ROW_FILENAMES = (
    "full_scf_end_to_end_numerical_evidence.json",
    "full_scf_numerical_comparison.json",
    "qe_full_scf_numerical_evidence.json",
    "qe_accelerated_numeric_evidence.json",
    "qe_correctness_for_l4_closure.json",
)

PHYSICAL_TOLERANCES = {
    "total_energy_error_ry": 1.0e-6,
    "density_residual": 1.0e-7,
    "force_error_ry_bohr": 1.0e-5,
    "stress_error_kbar": 1.0e-3,
    "eigenvalue_summary_error_ry": 1.0e-5,
}
EXECUTION_PROOF_FIELDS = (
    "runtime_execution_proof",
    "l4_execution_proof",
    "hardware_counter_proof",
    "tool_execution_proof",
)
FORBIDDEN_PROOF_FLAGS = (
    "fixture",
    "baseline_copy",
    "timing_only",
    "synthetic",
    "model_estimate",
    "component_model_reference_replay_only",
    "software_component_model_not_l4",
    "single_hpsi_call_smoke_only",
    "proxy_runtime_smoke_only",
    "proxy_runtime_only",
    "qe_callsite_gated_proxy_only",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_ref(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": str(path)}
    if path.exists():
        payload.update({"exists": True, "hash": _sha256_file(path), "hash_algorithm": "sha256"})
    else:
        payload.update({"exists": False})
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _comparison_output_path(out_target: Path) -> Path:
    """Resolve ``--out`` as either a directory or explicit JSON artifact path.

    Most runbooks pass a directory and expect ``full_scf_end_to_end_comparison.json``
    inside it.  Some long-running repair loops pass the JSON filename directly;
    accepting that form avoids accidentally creating
    ``.../full_scf_end_to_end_comparison.json/full_scf_end_to_end_comparison.json``.
    """

    out_target = Path(out_target)
    if out_target.exists() and out_target.is_file():
        return out_target
    if out_target.suffix.lower() == ".json":
        return out_target
    return out_target / "full_scf_end_to_end_comparison.json"


def _comparison_companion_paths(output_path: Path) -> tuple[Path, Path]:
    stem = output_path.stem
    return (
        output_path.with_name(f"{stem}_validation.json"),
        output_path.with_name(f"{stem}_status.json"),
    )


def _load_legal_candidate_ids(release_artifact_dir: Path) -> list[str]:
    manifest_path = release_artifact_dir / "candidate_universe_manifest.json"
    if not manifest_path.exists():
        manifest_path = release_artifact_dir / "release_subset_manifest.json"
    manifest = _load_json(manifest_path)
    legal_ids = [str(item) for item in manifest.get("legal_candidate_ids", []) or []]
    if legal_ids:
        return legal_ids
    return [
        str(candidate["candidate_id"])
        for candidate in manifest.get("candidates", []) or []
        if isinstance(candidate, Mapping) and candidate.get("legal") is True and candidate.get("candidate_id")
    ]


def _candidate_id_from_path(path: Path) -> str | None:
    for part in reversed(path.parts):
        if part.startswith(("cand_", "cdse_")):
            return part
    return None


def _normalize_strict_class_id(value: Any) -> str | None:
    if value is None:
        return None
    class_id = str(value)
    strict = set(STRICT_DFT_QE_WORKLOAD_CLASSES)
    if class_id in strict:
        return class_id
    if class_id.endswith("_case"):
        without_case = class_id[: -len("_case")]
        if without_case in strict:
            return without_case
    return class_id


def _class_id_from_path(path: Path) -> str | None:
    strict = set(STRICT_DFT_QE_WORKLOAD_CLASSES)
    for part in reversed(path.parts):
        normalized = _normalize_strict_class_id(part)
        if normalized in strict:
            return normalized
    return None


def _row_identity(path: Path, payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    candidate_id = (
        payload.get("candidate_id")
        or payload.get("design_candidate_id")
        or payload.get("cdse_candidate_id")
        or _candidate_id_from_path(path)
    )
    class_id = (
        payload.get("class_id")
        or payload.get("workload_class_id")
        or payload.get("workload_case_id")
        or payload.get("case_id")
        or _class_id_from_path(path)
    )
    return (
        str(candidate_id) if candidate_id else None,
        _normalize_strict_class_id(class_id),
    )


def _collect_row_paths(row_evidence_root: Path) -> list[Path]:
    paths_by_row_dir: dict[Path, Path] = {}
    for filename in DEFAULT_ROW_FILENAMES:
        for path in row_evidence_root.rglob(filename):
            paths_by_row_dir.setdefault(path.parent, path)
    return sorted(paths_by_row_dir.values())


def _kernel_ids(payload: Mapping[str, Any]) -> list[str]:
    direct = (
        payload.get("covered_accelerated_kernel_ids")
        or payload.get("accelerated_kernel_ids")
        or payload.get("major_kernel_ids")
        or payload.get("required_kernel_ids")
    )
    if isinstance(direct, list):
        return [str(item) for item in direct]
    kernel_evidence = payload.get("kernel_evidence")
    if isinstance(kernel_evidence, list):
        return [
            str(item.get("kernel_id"))
            for item in kernel_evidence
            if isinstance(item, Mapping) and item.get("kernel_id")
        ]
    kernel_gate = payload.get("kernel_gate")
    if isinstance(kernel_gate, Mapping):
        checks = kernel_gate.get("checks")
        if isinstance(checks, list):
            return [
                str(item.get("kernel_id"))
                for item in checks
                if isinstance(item, Mapping) and item.get("kernel_id")
            ]
    return []


def _boolish(payload: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    return value is True


def _row_measurement_source(payload: Mapping[str, Any]) -> str:
    return str(
        payload.get("accounting_source")
        or payload.get("runtime_trace_source")
        or payload.get("measurement_source")
        or payload.get("source_kind")
        or payload.get("source")
        or ""
    ).strip().lower()


def _proof_passed(payload: Mapping[str, Any]) -> bool:
    for key in EXECUTION_PROOF_FIELDS:
        proof = payload.get(key)
        if isinstance(proof, Mapping) and proof.get("passed") is True:
            return True
    return False


def _execution_proof_blockers(payload: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    passed_proof_seen = False
    for proof_key in EXECUTION_PROOF_FIELDS:
        proof = payload.get(proof_key)
        if not isinstance(proof, Mapping) or proof.get("passed") is not True:
            continue
        passed_proof_seen = True
        for flag in FORBIDDEN_PROOF_FLAGS:
            if proof.get(flag) is True:
                blockers.append(f"row_{proof_key}_{flag}_forbidden")
    if not passed_proof_seen:
        blockers.append("row_missing_passed_execution_proof")
    return sorted(dict.fromkeys(blockers))


def _metric_checks(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []

    explicit_checks = payload.get("metric_checks")
    if isinstance(explicit_checks, list) and explicit_checks:
        for index, check in enumerate(explicit_checks):
            if not isinstance(check, Mapping):
                blockers.append(f"metric_check_not_mapping::{index}")
                continue
            status = str(check.get("status") or "")
            passed = check.get("passed") is True or status == "passed"
            checks.append(dict(check))
            if not passed:
                blockers.append(f"metric_check_not_passed::{check.get('metric', index)}")
        return checks, blockers

    scf_gate = payload.get("scf_physical_gate")
    if isinstance(scf_gate, Mapping) and isinstance(scf_gate.get("checks"), list):
        for index, check in enumerate(scf_gate.get("checks") or []):
            if not isinstance(check, Mapping):
                blockers.append(f"scf_physical_check_not_mapping::{index}")
                continue
            metric = str(check.get("metric") or index)
            status = str(check.get("status") or "")
            passed = check.get("passed") is True or status == "passed"
            checks.append(dict(check))
            if not passed:
                blockers.append(f"scf_physical_check_not_passed::{metric}")
        if checks:
            return checks, blockers

    physical = payload.get("physical_evidence")
    if not isinstance(physical, Mapping):
        blockers.append("physical_evidence_missing")
        return checks, blockers

    required_metrics = ("total_energy_error_ry", "density_residual")
    for metric in required_metrics:
        if metric not in physical:
            blockers.append(f"required_physical_metric_missing::{metric}")
    for metric, tolerance in PHYSICAL_TOLERANCES.items():
        if metric not in physical:
            continue
        try:
            value = abs(float(physical[metric]))
        except (TypeError, ValueError):
            blockers.append(f"physical_metric_not_numeric::{metric}")
            continue
        passed = value <= tolerance
        checks.append(
            {
                "metric": metric,
                "value": value,
                "tolerance": tolerance,
                "status": "passed" if passed else "failed",
                "passed": passed,
            }
        )
        if not passed:
            blockers.append(f"physical_metric_out_of_tolerance::{metric}")
    return checks, blockers


def _cost_map(payload: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _validate_cost_map(
    costs: Mapping[str, Any],
    *,
    required_ids: tuple[str, ...],
    blocker_prefix: str,
) -> list[str]:
    blockers: list[str] = []
    if not costs:
        return [f"{blocker_prefix}_missing"]
    for cost_id in required_ids:
        if cost_id not in costs:
            blockers.append(f"{blocker_prefix}_missing::{cost_id}")
            continue
        try:
            value = float(costs[cost_id])
        except (TypeError, ValueError):
            blockers.append(f"{blocker_prefix}_not_numeric::{cost_id}")
            continue
        if value < 0.0:
            blockers.append(f"{blocker_prefix}_negative::{cost_id}")
    return blockers


def _row_blocker_category(blocker: str) -> str:
    """Group strict-row blockers into workstream-sized diagnostic buckets."""

    text = str(blocker)
    if "accelerated_kernel_costs_s" in text or "major_accelerated_kernels" in text:
        return "major_kernel_runtime_coverage"
    if "host_bound_costs_s" in text or "host_bound_costs_included" in text:
        return "host_bound_cost_accounting"
    if "runtime_overhead_costs_s" in text:
        return "runtime_overhead_accounting"
    if "execution_proof" in text or "proof" in text:
        return "execution_proof"
    if "physical" in text or "metric" in text or "density_residual" in text or "total_energy" in text:
        return "physical_metrics"
    if "trusted_accelerated_numeric_source" in text or "runtime_source" in text or "comparison_scope" in text:
        return "row_scope_and_source"
    if "strict_scf" in text or "candidate_id" in text:
        return "suite_identity_coverage"
    if "fixture" in text or "baseline_copy" in text or "timing_only" in text:
        return "forbidden_shortcut"
    return "other"


def _strip_candidate_class_prefix(blocker: str) -> str:
    """Return the row-local blocker suffix from ``class_id::blocker`` strings."""

    parts = str(blocker).split("::")
    if parts and parts[0] in STRICT_DFT_QE_WORKLOAD_CLASSES:
        return "::".join(parts[1:]) if len(parts) > 1 else str(blocker)
    return str(blocker)


def _evaluate_row(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    candidate_id, class_id = _row_identity(path, payload)
    blockers: list[str] = []
    if not candidate_id:
        blockers.append("candidate_id_missing")
    if not class_id:
        blockers.append("strict_scf_class_id_missing")
    elif class_id not in STRICT_DFT_QE_WORKLOAD_CLASSES:
        blockers.append("strict_scf_class_id_not_in_required_suite")

    kernels = _kernel_ids(payload)
    missing_kernels = [kernel_id for kernel_id in MAJOR_SCF_KERNEL_IDS if kernel_id not in kernels]
    if missing_kernels:
        blockers.append("major_accelerated_kernels_not_all_covered")

    status = str(payload.get("status") or payload.get("requested_claim_status") or "")
    if status != "passed" and payload.get("passed") is not True:
        blockers.append("row_status_not_passed")
    if payload.get("comparison_scope") != "full_scf_host_accelerator_end_to_end":
        blockers.append("comparison_scope_not_full_scf_host_accelerator_end_to_end")
    for key in (
        "trusted_accelerated_numeric_source",
        "host_accelerator_end_to_end",
        "full_scf_schedule_consumed",
        "host_bound_costs_included",
    ):
        if not _boolish(payload, key):
            blockers.append(f"{key}_not_true")
    measurement_source = _row_measurement_source(payload)
    if measurement_source in UNTRUSTED_RUNTIME_TRACE_SOURCES or measurement_source not in TRUSTED_RUNTIME_TRACE_SOURCES:
        blockers.append(f"row_untrusted_runtime_source:{measurement_source or 'missing'}")
    blockers.extend(_execution_proof_blockers(payload))
    for key in ("fixture", "baseline_copy", "timing_only"):
        if payload.get(key) is True:
            blockers.append(f"{key}_forbidden")
    accelerated_kernel_costs_s = _cost_map(payload, "accelerated_kernel_costs_s", "accelerated_costs_s")
    host_bound_costs_s = _cost_map(payload, "host_bound_costs_s", "host_bound_stage_costs_s")
    runtime_overhead_costs_s = _cost_map(payload, "runtime_overhead_costs_s", "overhead_costs_s")
    blockers.extend(
        _validate_cost_map(
            accelerated_kernel_costs_s,
            required_ids=MAJOR_SCF_KERNEL_IDS,
            blocker_prefix="accelerated_kernel_costs_s",
        )
    )
    blockers.extend(
        _validate_cost_map(
            host_bound_costs_s,
            required_ids=REQUIRED_HOST_BOUND_PHASE_IDS,
            blocker_prefix="host_bound_costs_s",
        )
    )
    blockers.extend(
        _validate_cost_map(
            runtime_overhead_costs_s,
            required_ids=REQUIRED_OVERHEAD_PHASE_IDS,
            blocker_prefix="runtime_overhead_costs_s",
        )
    )

    metric_checks, metric_blockers = _metric_checks(payload)
    blockers.extend(metric_blockers)

    row_passed = not blockers
    return {
        "candidate_id": candidate_id,
        "class_id": class_id,
        "status": "passed" if row_passed else "blocked_temporary",
        "passed": row_passed,
        "artifact_ref": _artifact_ref(path),
        "comparison_scope": payload.get("comparison_scope"),
        "trusted_accelerated_numeric_source": bool(payload.get("trusted_accelerated_numeric_source", False)),
        "host_accelerator_end_to_end": bool(payload.get("host_accelerator_end_to_end", False)),
        "full_scf_schedule_consumed": bool(payload.get("full_scf_schedule_consumed", False)),
        "host_bound_costs_included": bool(payload.get("host_bound_costs_included", False)),
        "accelerated_kernel_costs_s": accelerated_kernel_costs_s,
        "host_bound_costs_s": host_bound_costs_s,
        "runtime_overhead_costs_s": runtime_overhead_costs_s,
        "measurement_source": measurement_source,
        "execution_proof_present": _proof_passed(payload),
        "covered_accelerated_kernel_ids": kernels,
        "missing_accelerated_kernel_ids": missing_kernels,
        "metric_checks": metric_checks,
        "blockers": sorted(dict.fromkeys(blockers)),
        "claim_boundary": (
            "A row passes only when it is trusted full-SCF host+accelerator "
            "end-to-end numerical evidence, covers every claimed major kernel, "
            "includes host-bound/overhead costs, has physical metrics within "
            "tolerance, and carries trusted runtime/accounting source plus a "
            "passed execution proof."
        ),
    }


def _count_mismatch_errors(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    row_records = payload.get("row_records", [])
    candidate_records = payload.get("candidate_records", [])
    if not isinstance(row_records, list):
        errors.append("row_records_not_list")
        row_records = []
    if not isinstance(candidate_records, list):
        errors.append("candidate_records_not_list")
        candidate_records = []
    expected_pairs = {
        (str(candidate_id), str(class_id))
        for candidate_id in payload.get("candidate_ids", []) or []
        for class_id in payload.get("strict_scf_class_ids", []) or []
    }
    observed_pairs = {
        (str(row.get("candidate_id")), str(row.get("class_id")))
        for row in row_records
        if isinstance(row, Mapping) and row.get("candidate_id") and row.get("class_id")
    }
    if expected_pairs and observed_pairs != expected_pairs:
        errors.append("candidate_class_cartesian_coverage_mismatch")
    count_expectations = {
        "candidate_count": len(candidate_records),
        "passed_candidate_count": sum(
            1 for record in candidate_records if isinstance(record, Mapping) and record.get("status") == "passed"
        ),
        "blocked_candidate_count": sum(
            1 for record in candidate_records if not (isinstance(record, Mapping) and record.get("status") == "passed")
        ),
        "row_record_count": len(row_records),
        "passed_row_record_count": sum(
            1 for record in row_records if isinstance(record, Mapping) and record.get("status") == "passed"
        ),
        "blocked_row_record_count": sum(
            1 for record in row_records if not (isinstance(record, Mapping) and record.get("status") == "passed")
        ),
    }
    for key, expected in count_expectations.items():
        if payload.get(key) != expected:
            errors.append(f"{key}_mismatch")
    if payload.get("blocker_count") != len(set(payload.get("blockers", []) or [])):
        errors.append("blocker_count_mismatch")
    return errors


def _comparison_validation_payload(output_path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    errors = list(payload.get("blockers", []) or [])
    errors.extend(_count_mismatch_errors(payload))
    if payload.get("passed") is not True:
        errors.append("full_scf_comparison_not_passed")
    if payload.get("status") != "passed":
        errors.append(f"full_scf_comparison_status:{payload.get('status') or 'missing'}")
    if payload.get("trusted_accelerated_numeric_source") is not True:
        errors.append("trusted_accelerated_numeric_source_not_true")
    if payload.get("host_bound_costs_included") is not True:
        errors.append("host_bound_costs_included_not_true")
    errors = sorted(dict.fromkeys(str(error) for error in errors))
    valid = not errors
    return {
        "schema_version": "dse.dft.numerical.full_scf_end_to_end_comparison_validation.v1",
        "status": "passed" if valid else "blocked_temporary",
        "passed": valid,
        "valid": valid,
        "errors": errors,
        "error_count": len(errors),
        "candidate_count": payload.get("candidate_count"),
        "passed_candidate_count": payload.get("passed_candidate_count"),
        "blocked_candidate_count": payload.get("blocked_candidate_count"),
        "row_record_count": payload.get("row_record_count"),
        "passed_row_record_count": payload.get("passed_row_record_count"),
        "blocked_row_record_count": payload.get("blocked_row_record_count"),
        "blocker_count": payload.get("blocker_count"),
        "comparison_artifact": _artifact_ref(output_path),
        "claim_boundary": (
            "This companion validates only the full-SCF comparison artifact's "
            "own pass/block status and accounting shape. It is not independent "
            "numerical evidence and cannot claim deliverable completion."
        ),
    }


def _comparison_status_payload(payload: Mapping[str, Any], validation: Mapping[str, Any]) -> dict[str, Any]:
    comparison_passed = payload.get("passed") is True and validation.get("valid") is True
    return {
        "schema_version": "dse.dft.numerical.full_scf_end_to_end_comparison_status.v1",
        "status": "comparison_passed" if comparison_passed else "comparison_blocked",
        "comparison_status": payload.get("status", "missing"),
        "comparison_passed": comparison_passed,
        "validation_status": validation.get("status", "missing"),
        "validation_passed": validation.get("valid") is True,
        "candidate_count": payload.get("candidate_count"),
        "passed_candidate_count": payload.get("passed_candidate_count"),
        "blocked_candidate_count": payload.get("blocked_candidate_count"),
        "row_record_count": payload.get("row_record_count"),
        "passed_row_record_count": payload.get("passed_row_record_count"),
        "blocked_row_record_count": payload.get("blocked_row_record_count"),
        "blockers": list(payload.get("blockers", []) or []),
        "validation_errors": list(validation.get("errors", []) or []),
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "hardware_completion_eligible": False,
        "release_completion_eligible": False,
        "numerical_correctness_claim_eligible": False,
        "claim_boundary": (
            "This status companion makes the comparison pass/block state "
            "explicit for report gates. It never upgrades blocked or partial "
            "full-SCF evidence into a release or deliverable claim."
        ),
    }


def build_full_scf_end_to_end_comparison(
    out_target: Path,
    *,
    release_artifact_dir: Path,
    row_evidence_root: Path,
    overlay_row_evidence_roots: list[Path] | None = None,
) -> dict[str, Any]:
    output_path = _comparison_output_path(out_target)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    legal_candidate_ids = _load_legal_candidate_ids(release_artifact_dir)
    selected_row_records: list[dict[str, Any]] = []
    unidentified_row_records: list[dict[str, Any]] = []
    row_by_candidate_class: dict[tuple[str, str], dict[str, Any]] = {}
    duplicate_rows: list[str] = []
    superseded_rows: list[dict[str, Any]] = []
    root_specs = [("base", row_evidence_root), *[("overlay", root) for root in overlay_row_evidence_roots or []]]

    for root_role, root in root_specs:
        for path in _collect_row_paths(root):
            try:
                payload = _load_json(path)
            except Exception as exc:  # pragma: no cover - defensive artifact capture
                row = {
                    "candidate_id": _candidate_id_from_path(path),
                    "class_id": _class_id_from_path(path),
                    "status": "blocked_temporary",
                    "passed": False,
                    "artifact_ref": _artifact_ref(path),
                    "blockers": [f"row_json_unreadable::{type(exc).__name__}: {exc}"],
                }
            else:
                row = _evaluate_row(path, payload)
            row["row_evidence_root"] = str(root)
            row["row_evidence_root_role"] = root_role
            candidate_id = row.get("candidate_id")
            class_id = row.get("class_id")
            if not (candidate_id and class_id):
                unidentified_row_records.append(row)
                continue
            key = (str(candidate_id), str(class_id))
            previous = row_by_candidate_class.get(key)
            if previous is None:
                row_by_candidate_class[key] = row
                continue
            if root_role == "overlay":
                superseded_rows.append(
                    {
                        "candidate_id": str(candidate_id),
                        "class_id": str(class_id),
                        "selected_artifact": row.get("artifact_ref"),
                        "superseded_artifact": previous.get("artifact_ref"),
                        "overlay_row_evidence_root": str(root),
                        "claim_boundary": (
                            "Overlay rows replace older candidate/class evidence for replay coordination only. "
                            "The selected row is still evaluated by the same strict full-SCF gates."
                        ),
                    }
                )
                row_by_candidate_class[key] = row
            else:
                duplicate_rows.append(f"{candidate_id}::{class_id}")
                if row["status"] == "passed" and previous["status"] != "passed":
                    row_by_candidate_class[key] = row

    selected_row_records = [*unidentified_row_records, *row_by_candidate_class.values()]
    row_records = selected_row_records

    candidate_records: list[dict[str, Any]] = []
    passed_candidate_ids: list[str] = []
    for candidate_id in legal_candidate_ids:
        class_rows = [
            row_by_candidate_class.get((candidate_id, class_id))
            for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES
        ]
        missing_class_ids = [
            class_id
            for class_id, row in zip(STRICT_DFT_QE_WORKLOAD_CLASSES, class_rows)
            if row is None
        ]
        passed_class_ids = [
            class_id
            for class_id, row in zip(STRICT_DFT_QE_WORKLOAD_CLASSES, class_rows)
            if isinstance(row, Mapping) and row.get("status") == "passed"
        ]
        row_blockers = [
            f"{row.get('class_id')}::{blocker}"
            for row in class_rows
            if isinstance(row, Mapping)
            for blocker in row.get("blockers", []) or []
        ]
        blockers = list(row_blockers)
        if missing_class_ids:
            blockers.append("strict_six_scf_classes_not_all_covered")
        if len(passed_class_ids) != len(STRICT_DFT_QE_WORKLOAD_CLASSES):
            blockers.append("not_all_strict_scf_rows_passed")
        status = "passed" if not blockers else "blocked_temporary"
        if status == "passed":
            passed_candidate_ids.append(candidate_id)
        candidate_records.append(
            {
                "candidate_id": candidate_id,
                "status": status,
                "passed": status == "passed",
                "comparison_scope": "full_scf_host_accelerator_end_to_end",
                "trusted_accelerated_numeric_source": status == "passed",
                "host_accelerator_end_to_end": status == "passed",
                "strict_scf_class_ids": passed_class_ids,
                "missing_strict_scf_class_ids": missing_class_ids,
                "covered_accelerated_kernel_ids": list(MAJOR_SCF_KERNEL_IDS) if status == "passed" else [],
                "missing_accelerated_kernel_ids": [] if status == "passed" else list(MAJOR_SCF_KERNEL_IDS),
                "row_artifacts": [
                    row.get("artifact_ref")
                    for row in class_rows
                    if isinstance(row, Mapping) and isinstance(row.get("artifact_ref"), Mapping)
                ],
                "blockers": sorted(dict.fromkeys(blockers)),
            }
        )

    extra_candidate_ids = sorted(
        {
            str(row.get("candidate_id"))
            for row in row_records
            if row.get("candidate_id") and str(row.get("candidate_id")) not in set(legal_candidate_ids)
        }
    )
    top_blockers: list[str] = []
    if not legal_candidate_ids:
        top_blockers.append("legal_candidate_universe_missing")
    if duplicate_rows:
        top_blockers.append("duplicate_candidate_class_rows_present")
    if extra_candidate_ids:
        top_blockers.append("extra_candidate_rows_present")
    if len(passed_candidate_ids) != len(legal_candidate_ids):
        top_blockers.append("not_all_legal_candidates_passed_full_scf_comparison")

    row_blocker_histogram: Counter[str] = Counter()
    for row in row_records:
        row_blocker_histogram.update(str(blocker) for blocker in row.get("blockers", []) or [])
    candidate_blocker_histogram: Counter[str] = Counter()
    for candidate_record in candidate_records:
        candidate_blocker_histogram.update(
            str(blocker) for blocker in candidate_record.get("blockers", []) or []
        )
    row_blocker_category_histogram: Counter[str] = Counter()
    for blocker, count in row_blocker_histogram.items():
        row_blocker_category_histogram[_row_blocker_category(blocker)] += count
    candidate_blocker_category_histogram: Counter[str] = Counter()
    for blocker, count in candidate_blocker_histogram.items():
        candidate_blocker_category_histogram[_row_blocker_category(_strip_candidate_class_prefix(blocker))] += count
    missing_strict_class_histogram: Counter[str] = Counter()
    observed_missing_kernel_histogram: Counter[str] = Counter()
    accelerated_kernel_cost_gap_histogram: Counter[str] = Counter()
    host_bound_cost_gap_histogram: Counter[str] = Counter()
    runtime_overhead_cost_gap_histogram: Counter[str] = Counter()
    physical_metric_gap_histogram: Counter[str] = Counter()
    for candidate_record in candidate_records:
        missing_strict_class_histogram.update(
            str(class_id) for class_id in candidate_record.get("missing_strict_scf_class_ids", []) or []
        )
    for row in row_records:
        observed_missing_kernel_histogram.update(
            str(kernel_id) for kernel_id in row.get("missing_accelerated_kernel_ids", []) or []
        )
        for blocker in row.get("blockers", []) or []:
            blocker_text = str(blocker)
            if blocker_text.startswith("accelerated_kernel_costs_s_missing::"):
                accelerated_kernel_cost_gap_histogram[blocker_text.split("::", 1)[1]] += 1
            elif blocker_text.startswith("host_bound_costs_s_missing::"):
                host_bound_cost_gap_histogram[blocker_text.split("::", 1)[1]] += 1
            elif blocker_text.startswith("runtime_overhead_costs_s_missing::"):
                runtime_overhead_cost_gap_histogram[blocker_text.split("::", 1)[1]] += 1
            elif blocker_text.startswith("required_physical_metric_missing::"):
                physical_metric_gap_histogram[blocker_text.split("::", 1)[1]] += 1
            elif blocker_text.startswith("physical_metric_out_of_tolerance::"):
                physical_metric_gap_histogram[blocker_text.split("::", 1)[1]] += 1
    required_candidate_class_row_count = len(legal_candidate_ids) * len(STRICT_DFT_QE_WORKLOAD_CLASSES)
    passed_row_record_count = sum(1 for row in row_records if row.get("status") == "passed")
    blocked_row_record_count = sum(1 for row in row_records if row.get("status") != "passed")
    missing_candidate_class_row_count = max(required_candidate_class_row_count - len(row_by_candidate_class), 0)

    passed = not top_blockers and len(passed_candidate_ids) == len(legal_candidate_ids)
    payload = {
        "schema_version": "dse.dft.numerical.full_scf_end_to_end_comparison.v1",
        "status": "passed" if passed else "blocked_temporary",
        "passed": passed,
        "comparison_scope": "full_scf_host_accelerator_end_to_end",
        "trusted_accelerated_numeric_source": passed,
        "host_accelerator_end_to_end": passed,
        "full_scf_schedule_consumed": passed,
        "host_bound_costs_included": passed,
        "fixture": False,
        "baseline_copy": False,
        "timing_only": False,
        "release_artifact_dir": str(release_artifact_dir),
        "row_evidence_root": str(row_evidence_root),
        "overlay_row_evidence_roots": [str(root) for root in overlay_row_evidence_roots or []],
        "strict_scf_class_ids": list(STRICT_DFT_QE_WORKLOAD_CLASSES),
        "covered_accelerated_kernel_ids": list(MAJOR_SCF_KERNEL_IDS) if passed else [],
        "candidate_ids": legal_candidate_ids,
        "candidate_count": len(legal_candidate_ids),
        "passed_candidate_count": len(passed_candidate_ids),
        "blocked_candidate_count": len(legal_candidate_ids) - len(passed_candidate_ids),
        "required_candidate_class_row_count": required_candidate_class_row_count,
        "missing_candidate_class_row_count": missing_candidate_class_row_count,
        "extra_candidate_ids": extra_candidate_ids,
        "duplicate_candidate_class_rows": sorted(dict.fromkeys(duplicate_rows)),
        "superseded_candidate_class_rows": superseded_rows,
        "candidate_records": candidate_records,
        "row_record_count": len(row_records),
        "passed_row_record_count": passed_row_record_count,
        "blocked_row_record_count": blocked_row_record_count,
        "row_records": row_records,
        "blockers": sorted(dict.fromkeys(top_blockers)),
        "blocker_count": len(set(top_blockers)),
        "row_blocker_histogram": dict(sorted(row_blocker_histogram.items())),
        "candidate_blocker_histogram": dict(sorted(candidate_blocker_histogram.items())),
        "row_blocker_category_histogram": dict(sorted(row_blocker_category_histogram.items())),
        "candidate_blocker_category_histogram": dict(sorted(candidate_blocker_category_histogram.items())),
        "evidence_gap_summary": {
            "status": "passed" if passed else "blocked_temporary",
            "legal_candidate_count": len(legal_candidate_ids),
            "passed_candidate_count": len(passed_candidate_ids),
            "blocked_candidate_count": len(legal_candidate_ids) - len(passed_candidate_ids),
            "required_candidate_class_row_count": required_candidate_class_row_count,
            "observed_candidate_class_row_count": len(row_by_candidate_class),
            "missing_candidate_class_row_count": missing_candidate_class_row_count,
            "passed_row_record_count": passed_row_record_count,
            "blocked_row_record_count": blocked_row_record_count,
            "missing_strict_class_histogram": dict(sorted(missing_strict_class_histogram.items())),
            "observed_missing_kernel_histogram": dict(sorted(observed_missing_kernel_histogram.items())),
            "accelerated_kernel_cost_gap_histogram": dict(sorted(accelerated_kernel_cost_gap_histogram.items())),
            "host_bound_cost_gap_histogram": dict(sorted(host_bound_cost_gap_histogram.items())),
            "runtime_overhead_cost_gap_histogram": dict(sorted(runtime_overhead_cost_gap_histogram.items())),
            "physical_metric_gap_histogram": dict(sorted(physical_metric_gap_histogram.items())),
            "row_blocker_category_histogram": dict(sorted(row_blocker_category_histogram.items())),
            "candidate_blocker_category_histogram": dict(sorted(candidate_blocker_category_histogram.items())),
            "top_row_blockers": [
                {"blocker": blocker, "count": count}
                for blocker, count in row_blocker_histogram.most_common(12)
            ],
            "top_candidate_blockers": [
                {"blocker": blocker, "count": count}
                for blocker, count in candidate_blocker_histogram.most_common(12)
            ],
            "top_row_blocker_categories": [
                {"category": category, "count": count}
                for category, count in row_blocker_category_histogram.most_common(12)
            ],
            "top_candidate_blocker_categories": [
                {"category": category, "count": count}
                for category, count in candidate_blocker_category_histogram.most_common(12)
            ],
            "required_next_evidence": (
                "trusted full-SCF host+accelerator numerical rows for every legal candidate and all six "
                "strict SCF workload classes"
                if not passed
                else "none"
            ),
        },
        "claim_boundary": (
            "This artifact is eligible for the DFT numerical gate only when it is "
            "passed=true. It requires every legal candidate across all six strict "
            "SCF workload classes to have trusted host+accelerator full-SCF "
            "comparison rows covering every major claimed accelerated kernel. "
            "Partial h_psi/L4/timing evidence is preserved as blocked evidence only."
        ),
    }
    _write_json(output_path, payload)
    validation_path, status_path = _comparison_companion_paths(output_path)
    validation = _comparison_validation_payload(output_path, payload)
    _write_json(validation_path, validation)
    _write_json(status_path, _comparison_status_payload(payload, validation))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help=(
            "Output directory, or an explicit .json artifact path. Directory "
            "form writes full_scf_end_to_end_comparison.json inside it."
        ),
    )
    parser.add_argument(
        "--release-artifact-dir",
        type=Path,
        required=True,
        help="Directory containing candidate_universe_manifest.json or current-goal release_subset_manifest.json.",
    )
    parser.add_argument(
        "--row-evidence-root",
        type=Path,
        required=True,
        help=(
            "Root containing per-candidate/per-strict-SCF numerical row evidence. "
            "Known filenames include full_scf_end_to_end_numerical_evidence.json "
            "and qe_accelerated_numeric_evidence.json; pass/fail remains schema-gated."
        ),
    )
    parser.add_argument(
        "--overlay-row-evidence-root",
        type=Path,
        action="append",
        default=[],
        help=(
            "Optional newer row root to overlay on top of --row-evidence-root by "
            "candidate_id/class_id. This is for repair/replay coordination when "
            "a small set of rows has been regenerated separately; overlay rows "
            "are still evaluated by the same strict gates and cannot bypass "
            "blocked evidence."
        ),
    )
    args = parser.parse_args(argv)
    output_path = _comparison_output_path(args.out)
    payload = build_full_scf_end_to_end_comparison(
        args.out,
        release_artifact_dir=args.release_artifact_dir,
        row_evidence_root=args.row_evidence_root,
        overlay_row_evidence_roots=args.overlay_row_evidence_root,
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "artifact": str(output_path),
                "candidate_count": payload["candidate_count"],
                "passed_candidate_count": payload["passed_candidate_count"],
                "row_record_count": payload["row_record_count"],
                "blockers": payload["blockers"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
