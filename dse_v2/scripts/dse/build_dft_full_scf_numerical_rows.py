#!/usr/bin/env python3
"""Materialize strict DFT full-SCF numerical comparison rows.

This adapter upgrades *only already-trusted* QE accelerated numeric evidence
into the row schema consumed by ``build_dft_full_scf_end_to_end_comparison.py``.
It is fail-closed: a trusted kernel/SCF numeric row is still insufficient unless
an explicit full-SCF accounting artifact declares host+accelerator end-to-end
scope, schedule consumption, host-bound cost inclusion, and all-major-kernel
coverage.  Missing inputs are preserved as blocked row artifacts rather than
being fabricated from L4 transport or descriptor-only evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS  # noqa: E402
from dse_v2.codesign.dft_scf_workstreams import STRICT_DFT_QE_WORKLOAD_CLASSES  # noqa: E402
from dse_v2.reference_workloads.dft_full_scf_accounting import (  # noqa: E402
    materialize_full_scf_row_accounting_from_trace,
    validate_full_scf_row_accounting_payload,
)
from dse_v2.reference_workloads.dft_full_scf_hybrid import (  # noqa: E402
    REQUIRED_HOST_BOUND_PHASE_IDS,
    REQUIRED_OVERHEAD_PHASE_IDS,
)

SOURCE_ROW_FILENAMES = ("qe_accelerated_numeric_evidence.json",)
ACCOUNTING_FILENAMES = (
    "full_scf_row_accounting.json",
    "full_scf_host_accelerator_accounting.json",
)
RUNTIME_TRACE_FILENAMES = (
    "full_scf_runtime_trace.json",
)
PHYSICAL_TOLERANCES = {
    "total_energy_error_ry": 1.0e-6,
    "density_residual": 1.0e-7,
    "force_error_ry_bohr": 1.0e-5,
    "stress_error_kbar": 1.0e-3,
    "eigenvalue_summary_error_ry": 1.0e-5,
}
REQUIRED_PHYSICAL_METRICS = ("total_energy_error_ry", "density_residual")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_ref(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"exists": False, "path": None}
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
    return (str(candidate_id) if candidate_id else None, _normalize_strict_class_id(class_id))


def _collect_source_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for filename in SOURCE_ROW_FILENAMES:
        paths.extend(root.rglob(filename))
    return sorted(dict.fromkeys(paths))


def _source_path_refs(paths: Sequence[Path]) -> list[dict[str, Any]]:
    return [_artifact_ref(path) for path in sorted(paths, key=lambda item: str(item))]


def _duplicate_source_row(
    candidate_id: str,
    class_id: str,
    source_paths: Sequence[Path],
) -> dict[str, Any]:
    duplicate_paths = [str(path) for path in sorted(source_paths, key=lambda item: str(item))]
    return {
        "schema_version": "dse.dft.numerical.full_scf_row_evidence.v1",
        "candidate_id": candidate_id,
        "class_id": class_id,
        "workload_case_id": class_id,
        "status": "blocked_temporary",
        "passed": False,
        "comparison_scope": None,
        "trusted_accelerated_numeric_source": False,
        "source_qe_accelerated_numeric_evidence": {"exists": False, "path": None},
        "source_full_scf_row_accounting": {"exists": False, "path": None},
        "source_full_scf_runtime_trace": {"exists": False, "path": None},
        "duplicate_source_row_count": len(duplicate_paths),
        "duplicate_source_rows": duplicate_paths,
        "duplicate_source_qe_accelerated_numeric_row_paths": duplicate_paths,
        "duplicate_source_qe_accelerated_numeric_rows": _source_path_refs(source_paths),
        "blockers": ["duplicate_source_qe_accelerated_numeric_rows"],
        "claim_boundary": (
            "Multiple QE accelerated numeric source rows normalized to the same candidate/workload identity. "
            "The strict full-SCF row is fail-closed until the source-root layout is canonicalized and exactly "
            "one trusted source row is provided for this candidate/workload pair."
        ),
    }


def _accelerated_reference_path(source: Mapping[str, Any], key: str) -> Path | None:
    refs = source.get("accelerated_reference")
    if not isinstance(refs, Mapping):
        return None
    value = refs.get(key)
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else REPO_ROOT / path


def _find_accounting_path(
    source_path: Path,
    source: Mapping[str, Any],
    accounting_root: Path | None,
    candidate_id: str | None,
    class_id: str | None,
) -> Path | None:
    candidates: list[Path] = []
    referenced = _accelerated_reference_path(source, "full_scf_row_accounting_json")
    if referenced is not None:
        candidates.append(referenced)
    for filename in ACCOUNTING_FILENAMES:
        candidates.append(source_path.parent / filename)
    if accounting_root is not None and candidate_id and class_id:
        for class_dir in (class_id, f"{class_id}_case"):
            for filename in ACCOUNTING_FILENAMES:
                candidates.append(accounting_root / candidate_id / class_dir / filename)
    for path in candidates:
        if path.exists():
            return path
    return None


def _find_runtime_trace_path(
    source_path: Path,
    source: Mapping[str, Any],
    accounting_root: Path | None,
    candidate_id: str | None,
    class_id: str | None,
) -> Path | None:
    candidates: list[Path] = []
    referenced = _accelerated_reference_path(source, "full_scf_runtime_trace_json")
    if referenced is not None:
        candidates.append(referenced)
    for filename in RUNTIME_TRACE_FILENAMES:
        candidates.append(source_path.parent / filename)
    if accounting_root is not None and candidate_id and class_id:
        for class_dir in (class_id, f"{class_id}_case"):
            for filename in RUNTIME_TRACE_FILENAMES:
                candidates.append(accounting_root / candidate_id / class_dir / filename)
    for path in candidates:
        if path.exists():
            return path
    return None


def _list_from_payload(*values: Any) -> list[str]:
    for value in values:
        if isinstance(value, list):
            return [str(item) for item in value]
    return []


def _kernel_ids(source: Mapping[str, Any], accounting: Mapping[str, Any]) -> list[str]:
    direct = _list_from_payload(
        accounting.get("covered_accelerated_kernel_ids"),
        accounting.get("accelerated_kernel_ids"),
        accounting.get("major_kernel_ids"),
        source.get("covered_accelerated_kernel_ids"),
        source.get("accelerated_kernel_ids"),
        source.get("major_kernel_ids"),
        source.get("required_kernel_ids"),
    )
    if direct:
        return direct
    kernel_evidence = source.get("kernel_evidence")
    if isinstance(kernel_evidence, list):
        return [
            str(item.get("kernel_id"))
            for item in kernel_evidence
            if isinstance(item, Mapping) and item.get("kernel_id")
        ]
    return []


def _kernel_consumption_flag(source: Mapping[str, Any], row: Mapping[str, Any], key: str) -> bool:
    if row.get(key) is True:
        return True
    provenance = source.get("offload_provenance")
    return isinstance(provenance, Mapping) and provenance.get(key) is True


def _kernel_consumption_blockers(source: Mapping[str, Any]) -> list[str]:
    """Return blockers for missing per-major-kernel QE consumption evidence.

    Strict full-SCF rows cannot pass from offline kernel comparisons alone.
    Every major kernel claimed accelerated must have a row-local kernel evidence
    record proving full recomputation, QE mainflow integration, and that the
    accelerated result was consumed by QE.
    """

    kernel_evidence = source.get("kernel_evidence")
    if not isinstance(kernel_evidence, list) or not kernel_evidence:
        return ["kernel_consumption_evidence_missing_all_major_kernel_rows"]
    full_rows_by_kernel: dict[str, list[Mapping[str, Any]]] = {}
    for item in kernel_evidence:
        if not isinstance(item, Mapping):
            continue
        kernel_id = str(item.get("kernel_id") or item.get("target_kernel") or "").strip()
        if not kernel_id:
            continue
        if item.get("full_kernel_recomputed") is True and item.get("boundary_norm_probe_only") is not True:
            full_rows_by_kernel.setdefault(kernel_id, []).append(item)

    blockers: list[str] = []
    for kernel_id in MAJOR_SCF_KERNEL_IDS:
        rows = full_rows_by_kernel.get(kernel_id, [])
        if not rows:
            blockers.append(f"kernel_consumption_evidence_missing::{kernel_id}")
            continue
        if not any(_kernel_consumption_flag(source, row, "qe_mainflow_integrated") for row in rows):
            blockers.append(f"kernel_consumption_evidence_qe_mainflow_integrated_not_true::{kernel_id}")
        if not any(_kernel_consumption_flag(source, row, "accelerated_results_consumed_by_qe") for row in rows):
            blockers.append(f"kernel_consumption_evidence_accelerated_results_consumed_by_qe_not_true::{kernel_id}")
        for metric in ("absolute_error", "relative_error"):
            if not any(row.get(metric) is not None for row in rows):
                blockers.append(f"kernel_consumption_evidence_missing_{metric}::{kernel_id}")
    return blockers


def _physical_evidence(source: Mapping[str, Any], accounting: Mapping[str, Any]) -> dict[str, Any]:
    physical: dict[str, Any] = {}
    for payload in (source.get("physical_evidence"), accounting.get("physical_evidence")):
        if isinstance(payload, Mapping):
            physical.update(dict(payload))
    return physical


def _metric_checks(physical: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    for metric in REQUIRED_PHYSICAL_METRICS:
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
    required_ids: Sequence[str],
    blocker_prefix: str,
) -> list[str]:
    blockers: list[str] = []
    if not isinstance(costs, Mapping) or not costs:
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


def _boolish_true(payload: Mapping[str, Any], key: str) -> bool:
    return payload.get(key) is True


def _accounting_source(source: Mapping[str, Any], accounting: Mapping[str, Any]) -> Any:
    return (
        accounting.get("runtime_trace_source")
        or accounting.get("accounting_source")
        or accounting.get("measurement_source")
        or accounting.get("source_kind")
        or source.get("runtime_trace_source")
        or source.get("source_kind")
    )


def _proof_payload(source: Mapping[str, Any], accounting: Mapping[str, Any], key: str) -> dict[str, Any] | None:
    for payload in (accounting.get(key), source.get(key)):
        if isinstance(payload, Mapping):
            return dict(payload)
    return None


def _build_strict_row(
    source_path: Path,
    source: Mapping[str, Any],
    accounting_path: Path | None,
    accounting: Mapping[str, Any],
    *,
    runtime_trace_path: Path | None = None,
    runtime_trace_materialized: bool = False,
) -> dict[str, Any]:
    candidate_id, class_id = _row_identity(source_path, source)
    blockers: list[str] = []
    if not candidate_id:
        blockers.append("candidate_id_missing")
    if not class_id:
        blockers.append("strict_scf_class_id_missing")
    elif class_id not in STRICT_DFT_QE_WORKLOAD_CLASSES:
        blockers.append("strict_scf_class_id_not_in_required_suite")

    if source.get("schema_version") != "dse.qe_accelerated_numeric_evidence.v1":
        blockers.append("source_qe_accelerated_numeric_schema_mismatch")
    if source.get("trusted_accelerated_numeric_source") is not True:
        blockers.append("source_trusted_accelerated_numeric_source_not_true")
    if source.get("accelerated_output_status") != "passed" and source.get("status") != "passed" and source.get("passed") is not True:
        blockers.append("source_accelerated_output_status_not_passed")
    for source_blocker in source.get("blockers", []) or []:
        blockers.append(f"source_blocker::{source_blocker}")

    if accounting_path is None:
        blockers.append("full_scf_row_accounting_missing")
    else:
        blockers.extend(
            validate_full_scf_row_accounting_payload(
                accounting,
                candidate_id=candidate_id,
                workload_case_id=class_id,
            )
        )
        if accounting.get("schema_version") not in {
            "dse.dft.numerical.full_scf_row_accounting.v1",
            "dse.dft_scf.full_scf_row_accounting.v1",
        }:
            blockers.append("full_scf_row_accounting_schema_mismatch")
        if accounting.get("status") not in {"passed", "complete"} and accounting.get("passed") is not True:
            blockers.append("full_scf_row_accounting_status_not_passed")

    comparison_scope = accounting.get("comparison_scope") or source.get("comparison_scope")
    if comparison_scope != "full_scf_host_accelerator_end_to_end":
        blockers.append("comparison_scope_not_full_scf_host_accelerator_end_to_end")
    for key in (
        "host_accelerator_end_to_end",
        "full_scf_schedule_consumed",
        "host_bound_costs_included",
    ):
        if not (_boolish_true(accounting, key) or _boolish_true(source, key)):
            blockers.append(f"{key}_not_true")
    for key in ("fixture", "baseline_copy", "timing_only"):
        if source.get(key) is True or accounting.get(key) is True:
            blockers.append(f"{key}_forbidden")
    accelerated_kernel_costs_s = _cost_map(accounting, "accelerated_kernel_costs_s", "accelerated_costs_s")
    host_bound_costs_s = _cost_map(accounting, "host_bound_costs_s", "host_bound_stage_costs_s")
    runtime_overhead_costs_s = _cost_map(accounting, "runtime_overhead_costs_s", "overhead_costs_s")
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

    kernels = _kernel_ids(source, accounting)
    missing_kernels = [kernel_id for kernel_id in MAJOR_SCF_KERNEL_IDS if kernel_id not in kernels]
    if missing_kernels:
        blockers.append("major_accelerated_kernels_not_all_covered")
    blockers.extend(_kernel_consumption_blockers(source))

    physical = _physical_evidence(source, accounting)
    metric_checks, metric_blockers = _metric_checks(physical)
    blockers.extend(metric_blockers)

    passed = not blockers
    return {
        "schema_version": "dse.dft.numerical.full_scf_row_evidence.v1",
        "candidate_id": candidate_id,
        "class_id": class_id,
        "workload_case_id": class_id,
        "status": "passed" if passed else "blocked_temporary",
        "passed": passed,
        "comparison_scope": "full_scf_host_accelerator_end_to_end" if comparison_scope == "full_scf_host_accelerator_end_to_end" else comparison_scope,
        "trusted_accelerated_numeric_source": passed,
        "host_accelerator_end_to_end": _boolish_true(accounting, "host_accelerator_end_to_end") or _boolish_true(source, "host_accelerator_end_to_end"),
        "full_scf_schedule_consumed": _boolish_true(accounting, "full_scf_schedule_consumed") or _boolish_true(source, "full_scf_schedule_consumed"),
        "host_bound_costs_included": _boolish_true(accounting, "host_bound_costs_included") or _boolish_true(source, "host_bound_costs_included"),
        "accelerated_kernel_costs_s": accelerated_kernel_costs_s,
        "host_bound_costs_s": host_bound_costs_s,
        "runtime_overhead_costs_s": runtime_overhead_costs_s,
        "accounting_source": _accounting_source(source, accounting),
        "runtime_execution_proof": _proof_payload(source, accounting, "runtime_execution_proof"),
        "l4_execution_proof": _proof_payload(source, accounting, "l4_execution_proof"),
        "hardware_counter_proof": _proof_payload(source, accounting, "hardware_counter_proof"),
        "tool_execution_proof": _proof_payload(source, accounting, "tool_execution_proof"),
        "fixture": bool(source.get("fixture") is True or accounting.get("fixture") is True),
        "baseline_copy": bool(source.get("baseline_copy") is True or accounting.get("baseline_copy") is True),
        "timing_only": bool(source.get("timing_only") is True or accounting.get("timing_only") is True),
        "covered_accelerated_kernel_ids": kernels,
        "missing_accelerated_kernel_ids": missing_kernels,
        "physical_evidence": physical,
        "metric_checks": metric_checks,
        "source_qe_accelerated_numeric_evidence": _artifact_ref(source_path),
        "source_full_scf_row_accounting": _artifact_ref(accounting_path),
        "source_full_scf_runtime_trace": _artifact_ref(runtime_trace_path),
        "runtime_trace_materialized_to_accounting": bool(runtime_trace_materialized),
        "blockers": sorted(dict.fromkeys(blockers)),
        "claim_boundary": (
            "This strict row is produced only from trusted QE accelerated numeric evidence plus explicit "
            "full-SCF host+accelerator accounting. It cannot be inferred from descriptor-only, L4 transport, "
            "fixture, timing-only, or baseline-copy evidence."
        ),
    }


def build_full_scf_numerical_rows(source_row_root: Path, out_root: Path, *, accounting_root: Path | None = None) -> dict[str, Any]:
    out_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    passed_count = 0
    blocked_count = 0
    duplicate_source_row_count = 0
    duplicate_source_identity_count = 0
    blocker_histogram: Counter[str] = Counter()
    source_paths = _collect_source_paths(source_row_root)
    identity_to_source_paths: dict[tuple[str, str], list[Path]] = {}
    for source_path in source_paths:
        try:
            source = _load_json(source_path)
        except Exception:
            continue
        candidate_id, class_id = _row_identity(source_path, source)
        if candidate_id and class_id:
            identity_to_source_paths.setdefault((str(candidate_id), str(class_id)), []).append(source_path)
    duplicate_identity_to_paths = {
        identity: paths
        for identity, paths in identity_to_source_paths.items()
        if len(paths) > 1
    }
    duplicate_source_paths = {
        source_path for paths in duplicate_identity_to_paths.values() for source_path in paths
    }
    duplicate_source_row_count = sum(len(paths) for paths in duplicate_identity_to_paths.values())
    duplicate_source_identity_count = len(duplicate_identity_to_paths)

    for (candidate_id, class_id), duplicate_paths in sorted(duplicate_identity_to_paths.items()):
        row = _duplicate_source_row(candidate_id, class_id, duplicate_paths)
        out_path = out_root / candidate_id / class_id / "full_scf_end_to_end_numerical_evidence.json"
        _write_json(out_path, row)
        record = {
            "candidate_id": row.get("candidate_id"),
            "class_id": row.get("class_id"),
            "status": row.get("status"),
            "passed": False,
            "source": None,
            "out": str(out_path),
            "blockers": row.get("blockers", []),
            "duplicate_source_rows": row.get("duplicate_source_rows", []),
            "duplicate_source_row_count": row.get("duplicate_source_row_count", 0),
        }
        records.append(record)
        blocked_count += 1
        blocker_histogram.update(str(blocker) for blocker in row.get("blockers", []))

    for source_path in source_paths:
        if source_path in duplicate_source_paths:
            continue
        try:
            source = _load_json(source_path)
        except Exception as exc:  # pragma: no cover - defensive artifact preservation
            candidate_id = _candidate_id_from_path(source_path)
            class_id = _class_id_from_path(source_path)
            row = {
                "schema_version": "dse.dft.numerical.full_scf_row_evidence.v1",
                "candidate_id": candidate_id,
                "class_id": class_id,
                "status": "blocked_temporary",
                "passed": False,
                "source_qe_accelerated_numeric_evidence": _artifact_ref(source_path),
                "source_full_scf_row_accounting": {"exists": False, "path": None},
                "blockers": [f"source_row_json_unreadable::{type(exc).__name__}: {exc}"],
                "claim_boundary": "Unreadable source rows are preserved as blocked strict full-SCF evidence.",
            }
        else:
            candidate_id, class_id = _row_identity(source_path, source)
            accounting_path = _find_accounting_path(source_path, source, accounting_root, candidate_id, class_id)
            runtime_trace_path = _find_runtime_trace_path(source_path, source, accounting_root, candidate_id, class_id)
            runtime_trace_materialized = False
            if accounting_path is None and runtime_trace_path is not None and candidate_id and class_id:
                accounting_path = out_root / str(candidate_id) / str(class_id) / "full_scf_row_accounting.json"
                materialize_full_scf_row_accounting_from_trace(
                    trace_path=runtime_trace_path,
                    output_path=accounting_path,
                    candidate_id=str(candidate_id),
                    workload_case_id=str(class_id),
                )
                runtime_trace_materialized = True
            accounting = _load_json(accounting_path) if accounting_path is not None else {}
            row = _build_strict_row(
                source_path,
                source,
                accounting_path,
                accounting,
                runtime_trace_path=runtime_trace_path,
                runtime_trace_materialized=runtime_trace_materialized,
            )
        candidate_id = str(row.get("candidate_id") or "candidate_unknown")
        class_id = str(row.get("class_id") or "class_unknown")
        out_path = out_root / candidate_id / class_id / "full_scf_end_to_end_numerical_evidence.json"
        _write_json(out_path, row)
        record = {
            "candidate_id": row.get("candidate_id"),
            "class_id": row.get("class_id"),
            "status": row.get("status"),
            "passed": row.get("passed") is True,
            "source": str(source_path),
            "out": str(out_path),
            "blockers": row.get("blockers", []),
        }
        records.append(record)
        if row.get("passed") is True:
            passed_count += 1
        else:
            blocked_count += 1
            row_blockers = row.get("blockers", [])
            if isinstance(row_blockers, list):
                blocker_histogram.update(str(blocker) for blocker in row_blockers)

    status = "passed" if records and blocked_count == 0 else "blocked_temporary"
    index = {
        "schema_version": "dse.dft.numerical.full_scf_row_materialization_index.v1",
        "status": status,
        "passed": status == "passed",
        "source_row_root": str(source_row_root),
        "accounting_root": str(accounting_root) if accounting_root is not None else None,
        "out_root": str(out_root),
        "row_count": len(records),
        "passed_row_count": passed_count,
        "blocked_row_count": blocked_count,
        "duplicate_source_row_count": duplicate_source_row_count,
        "duplicate_source_identity_count": duplicate_source_identity_count,
        "blocker_histogram": dict(sorted(blocker_histogram.items())),
        "missing_full_scf_accounting_row_count": blocker_histogram.get("full_scf_row_accounting_missing", 0),
        "missing_trusted_accelerated_numeric_source_row_count": blocker_histogram.get(
            "source_trusted_accelerated_numeric_source_not_true",
            0,
        ),
        "records": records,
        "evidence_gap_summary": {
            "status": "passed" if status == "passed" else "blocked_temporary",
            "row_count": len(records),
            "passed_row_count": passed_count,
            "blocked_row_count": blocked_count,
            "duplicate_source_row_count": duplicate_source_row_count,
            "duplicate_source_identity_count": duplicate_source_identity_count,
            "missing_full_scf_accounting_row_count": blocker_histogram.get("full_scf_row_accounting_missing", 0),
            "missing_trusted_accelerated_numeric_source_row_count": blocker_histogram.get(
                "source_trusted_accelerated_numeric_source_not_true",
                0,
            ),
            "top_blockers": [
                {"blocker": blocker, "count": count}
                for blocker, count in blocker_histogram.most_common(12)
            ],
            "required_next_evidence": (
                "trusted QE/offload full-SCF runtime rows plus full_scf_row_accounting.json for each "
                "candidate/workload row"
                if status != "passed"
                else "none"
            ),
        },
        "claim_boundary": (
            "This index only records strict row materialization. Full numerical closure still requires "
            "build_dft_full_scf_end_to_end_comparison.py to pass across every legal candidate and all six SCF classes."
        ),
    }
    _write_json(out_root / "full_scf_numerical_row_materialization_index.json", index)
    return index


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-row-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--accounting-root", type=Path, default=None)
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args(argv)
    index = build_full_scf_numerical_rows(
        args.source_row_root,
        args.out_root,
        accounting_root=args.accounting_root,
    )
    print(json.dumps(index, indent=2, sort_keys=True))
    return 2 if args.fail_on_blocked and index["blocked_row_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
