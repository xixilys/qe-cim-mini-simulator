#!/usr/bin/env python3
"""Build audited QE accelerated/offloaded numeric evidence rows.

This module is intentionally only a collector/comparator.  It does not run QE,
does not synthesize accelerated outputs, and does not upgrade fixture or
baseline-copy data into trusted correctness.  A trusted row needs an explicit
offload provenance artifact plus numeric kernel and SCF/physical deltas.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


QE_ACCELERATED_NUMERIC_EVIDENCE_SCHEMA = "dse.qe_accelerated_numeric_evidence.v1"
TRUSTED_QE_ACCELERATED_NUMERIC_SOURCES = {
    "qe_offload_runtime",
    "gem5_generic_accel_qe_extension",
    "accelerated_qe_runtime",
}
UNTRUSTED_QE_ACCELERATED_NUMERIC_SOURCES = {
    "fixture",
    "fixture_reference",
    "l3_fixture_sidecar",
    "baseline_copy",
    "pure_software_qe_baseline",
    "timing_only",
}
REQUIRED_QE_ACCELERATED_PHYSICAL_FIELDS = (
    "total_energy_error_ry",
    "density_residual",
    "eigenvalue_summary_error_ry",
)
REQUIRED_FULL_HPSI_KERNEL_SCOPES = {
    "full_h_psi",
    "full_qe_hpsi",
    "full_kernel_h_psi",
}
FULL_KERNEL_SCOPE_PREFIXES = ("full_", "full-qe", "full_kernel_")
_UNTRUSTED_PROVENANCE_MARKERS = {
    "fixture",
    "fixture_reference",
    "baseline",
    "baseline_copy",
    "pure_software",
    "pure_software_qe_baseline",
    "timing_only",
    "l3_fixture_sidecar",
}

_QE_TOTAL_ENERGY_RE = re.compile(r"!\s*total energy\s*=\s*([-+0-9.Ee]+)\s+Ry")
_QE_HOMO_LUMO_RE = re.compile(
    r"highest occupied,\s*lowest unoccupied level\s*\(ev\):\s*([-+0-9.Ee]+)\s+([-+0-9.Ee]+)",
    re.IGNORECASE,
)
_QE_TOTAL_FORCE_RE = re.compile(r"Total force\s*=\s*([-+0-9.Ee]+)", re.IGNORECASE)
_QE_TOTAL_STRESS_PRESSURE_RE = re.compile(
    r"total\s+stress\s+\(Ry/bohr\*\*3\)[^\n]*P=\s*([-+0-9.Ee]+)",
    re.IGNORECASE,
)


_HPSI_SIDECAR_COUNTER_FIELDS = (
    "sidecar_observed_hpsi_calls",
    "sidecar_attempted_hpsi_calls",
    "sidecar_consumed_hpsi_calls",
    "sidecar_failed_hpsi_calls",
)
_HPSI_SIDECAR_SOURCE_HINTS = (
    "qe_hpsi",
    "hpsi",
    "h_psi",
    "native_payload",
    "component_sidecar",
    "systemc_native_payload",
)


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        numeric = float(value)
        if not numeric.is_integer():
            return None
        return int(numeric)
    except (TypeError, ValueError):
        return None


def _requires_hpsi_sidecar_consumption_counters(item: Mapping[str, Any]) -> bool:
    kernel_id = str(item.get("kernel_id") or item.get("target_kernel") or item.get("kernel") or "").lower()
    text = " ".join(
        str(item.get(key) or "")
        for key in (
            "producer",
            "accelerated_runtime",
            "offload_target",
            "source",
            "source_kind",
            "trusted_payload_kind",
            "claim_boundary",
        )
    ).lower()
    if kernel_id not in {"", "h_psi", "hpsi"} and "hpsi" not in text and "h_psi" not in text:
        return False
    return any(hint in text for hint in _HPSI_SIDECAR_SOURCE_HINTS)


def _validate_hpsi_sidecar_consumption_counters(
    item: Mapping[str, Any],
    *,
    blocker_prefix: str,
) -> list[str]:
    blockers: list[str] = []
    if not _requires_hpsi_sidecar_consumption_counters(item):
        return blockers
    values = {field: _int_or_none(item.get(field)) for field in _HPSI_SIDECAR_COUNTER_FIELDS}
    for field, value in values.items():
        if value is None:
            blockers.append(f"{blocker_prefix}_missing_{field}")
    observed = values["sidecar_observed_hpsi_calls"]
    attempted = values["sidecar_attempted_hpsi_calls"]
    consumed = values["sidecar_consumed_hpsi_calls"]
    failed = values["sidecar_failed_hpsi_calls"]
    if observed is not None:
        if observed <= 0:
            blockers.append(f"{blocker_prefix}_sidecar_observed_hpsi_calls_not_positive:{observed}")
        if attempted is not None and attempted != observed:
            blockers.append(f"{blocker_prefix}_sidecar_attempted_hpsi_calls_mismatch:{attempted}!={observed}")
        if consumed is not None and consumed != observed:
            blockers.append(f"{blocker_prefix}_sidecar_consumed_hpsi_calls_mismatch:{consumed}!={observed}")
    if failed is not None and failed != 0:
        blockers.append(f"{blocker_prefix}_sidecar_failed_hpsi_calls:{failed}")
    if item.get("all_observed_hpsi_calls_sidecar_consumed") is not True:
        blockers.append(f"{blocker_prefix}_missing_all_observed_hpsi_calls_sidecar_consumed_true")
    if item.get("single_hpsi_call_smoke_only") is not False:
        blockers.append(f"{blocker_prefix}_missing_single_hpsi_call_smoke_only_false")
    return blockers


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_qe_stdout_metrics(stdout: str) -> Dict[str, float]:
    """Extract stable scalar metrics from a QE stdout log."""
    metrics: Dict[str, float] = {}
    energy_matches = _QE_TOTAL_ENERGY_RE.findall(stdout or "")
    if energy_matches:
        metrics["total_energy_ry"] = float(energy_matches[-1])
    homo_lumo = _QE_HOMO_LUMO_RE.search(stdout or "")
    if homo_lumo:
        metrics["highest_occupied_ev"] = float(homo_lumo.group(1))
        metrics["lowest_unoccupied_ev"] = float(homo_lumo.group(2))
    force_matches = _QE_TOTAL_FORCE_RE.findall(stdout or "")
    if force_matches:
        metrics["total_force_ry_bohr"] = float(force_matches[-1])
    pressure_matches = _QE_TOTAL_STRESS_PRESSURE_RE.findall(stdout or "")
    if pressure_matches:
        metrics["pressure_kbar"] = float(pressure_matches[-1])
    return metrics


def _baseline_terminal_metrics(baseline_comparison: Mapping[str, Any]) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    perf = baseline_comparison.get("performance_metrics", {})
    if isinstance(perf, Mapping) and isinstance(perf.get("terminal_step_metrics"), Mapping):
        metrics.update(dict(perf["terminal_step_metrics"]))
    steps = baseline_comparison.get("steps", [])
    if isinstance(steps, list):
        # Multi-stage QE flows such as scf->nscf or scf->bands may emit SCF
        # energy/eigen summaries in prerequisite steps while the terminal tool
        # emits only band/DOS artifacts.  Preserve terminal metrics, but fill
        # missing scalar oracles from the latest prior step that reported them.
        for step in reversed(steps):
            if isinstance(step, Mapping) and isinstance(step.get("metrics"), Mapping):
                for key, value in step["metrics"].items():
                    metrics.setdefault(str(key), value)
    return metrics


def _load_kernel_evidence(path: Path | None) -> tuple[list[Dict[str, Any]], list[str]]:
    if path is None:
        return [], ["missing_kernel_evidence_json"]
    if not path.exists():
        return [], [f"kernel_evidence_json_missing:{path}"]
    payload = _read_json(path)
    rows = payload.get("kernel_evidence", payload) if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        return [], [f"kernel_evidence_json_not_list:{path}"]
    evidence = [dict(item) for item in rows if isinstance(item, Mapping)]
    blockers: list[str] = []
    if not evidence:
        blockers.append("missing_accelerated_qe_kernel_numeric_outputs")
    for index, item in enumerate(evidence):
        if _float_or_none(item.get("absolute_error")) is None or _float_or_none(item.get("relative_error")) is None:
            blockers.append(f"kernel_evidence_missing_error_metric:{index}")
    return evidence, blockers


def _marker_is_untrusted(value: Any) -> bool:
    if value is None:
        return False
    normalized = str(value).strip().lower()
    if not normalized:
        return False
    return normalized in _UNTRUSTED_PROVENANCE_MARKERS


def validate_offload_provenance(provenance: Mapping[str, Any] | None, source_kind: str) -> list[str]:
    """Return anti-downgrade blockers for an accelerated/offload provenance map."""
    blockers: list[str] = []
    if source_kind in TRUSTED_QE_ACCELERATED_NUMERIC_SOURCES and not provenance:
        blockers.append("missing_offload_provenance_for_trusted_source")
        return blockers
    if not provenance:
        return blockers
    for field in ("producer", "accelerated_runtime", "offload_target"):
        if not provenance.get(field):
            blockers.append(f"offload_provenance_missing_{field}")
        elif _marker_is_untrusted(provenance.get(field)):
            blockers.append(f"offload_provenance_untrusted_{field}:{provenance.get(field)}")
    if provenance.get("baseline_copy") is True:
        blockers.append("offload_provenance_marks_baseline_copy")
    if provenance.get("timing_only") is True:
        blockers.append("offload_provenance_marks_timing_only")
    if provenance.get("fixture") is True:
        blockers.append("offload_provenance_marks_fixture")
    if provenance.get("pure_software_qe_baseline") is True:
        blockers.append("offload_provenance_marks_pure_software_qe_baseline")
    if provenance.get("host_stage_reference_assisted") is True:
        blockers.append("offload_provenance_marks_host_stage_reference_assisted")
    if provenance.get("component_model_reference_replay_only") is True:
        blockers.append("offload_provenance_marks_component_model_reference_replay_only")
    if provenance.get("software_component_model_not_l4") is True:
        blockers.append("offload_provenance_marks_software_component_model_not_l4")
    if provenance.get("single_hpsi_call_smoke_only") is True:
        blockers.append("offload_provenance_marks_single_hpsi_call_smoke_only")
    if provenance.get("all_observed_hpsi_calls_sidecar_consumed") is False:
        blockers.append("offload_provenance_not_all_observed_hpsi_calls_sidecar_consumed")
    if _float_or_none(provenance.get("sidecar_failed_hpsi_calls")) not in {None, 0.0}:
        blockers.append(f"offload_provenance_sidecar_failed_hpsi_calls:{provenance.get('sidecar_failed_hpsi_calls')}")
    blockers.extend(
        _validate_hpsi_sidecar_consumption_counters(
            provenance,
            blocker_prefix="offload_provenance",
        )
    )
    if source_kind in TRUSTED_QE_ACCELERATED_NUMERIC_SOURCES:
        target_kernel = str(
            provenance.get("target_kernel")
            or provenance.get("kernel_id")
            or ""
        ).strip().lower()
        full_kernel_recomputed = provenance.get("full_kernel_recomputed") is True
        full_hpsi_recomputed = provenance.get("full_h_psi_recomputed") is True
        if target_kernel in {"", "h_psi"} and not (
            full_hpsi_recomputed or full_kernel_recomputed
        ):
            blockers.append("offload_provenance_missing_full_h_psi_recomputed_true")
        elif target_kernel and target_kernel != "h_psi" and not full_kernel_recomputed:
            blockers.append(
                f"offload_provenance_missing_full_kernel_recomputed_true:{target_kernel}"
            )
        if provenance.get("qe_mainflow_integrated") is not True:
            blockers.append("offload_provenance_missing_qe_mainflow_integrated_true")
        if provenance.get("accelerated_results_consumed_by_qe") is not True:
            blockers.append("offload_provenance_missing_accelerated_results_consumed_by_qe_true")
        l4_proof = provenance.get("l4_execution_proof")
        if not isinstance(l4_proof, Mapping):
            blockers.append("offload_provenance_missing_l4_execution_proof")
        else:
            if l4_proof.get("passed") is not True:
                blockers.append("offload_provenance_l4_execution_proof_not_passed")
            transport = str(l4_proof.get("transport_harness") or "")
            if not transport:
                blockers.append("offload_provenance_l4_execution_proof_missing_transport_harness")
    if provenance.get("boundary_norm_probe_only") is True:
        blockers.append("offload_provenance_marks_boundary_norm_probe_only")
    return blockers


def _kernel_text(item: Mapping[str, Any]) -> str:
    return str(item.get("kernel_id") or item.get("kernel") or "").strip().lower()


def _kernel_scope_text(item: Mapping[str, Any]) -> str:
    return str(item.get("kernel_scope") or item.get("scope") or "").strip().lower()


def _is_full_kernel_evidence(item: Mapping[str, Any]) -> bool:
    kernel_id = _kernel_text(item)
    kernel_scope = _kernel_scope_text(item)
    if item.get("full_kernel_recomputed") is not True:
        return False
    if item.get("boundary_norm_probe_only") is True:
        return False
    if kernel_id == "h_psi" and kernel_scope in REQUIRED_FULL_HPSI_KERNEL_SCOPES:
        return True
    return kernel_scope.startswith(FULL_KERNEL_SCOPE_PREFIXES) or kernel_scope == (
        "full_" + kernel_id
    )


def validate_kernel_numeric_evidence(kernel_evidence: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return blockers for missing/untrusted accelerated kernel numeric evidence."""
    blockers: list[str] = []
    if not kernel_evidence:
        blockers.append("missing_accelerated_qe_kernel_numeric_outputs")
        return blockers
    full_kernel_indices = {
        index
        for index, item in enumerate(kernel_evidence)
        if _is_full_kernel_evidence(item)
    }
    full_hpsi_indices = {
        index
        for index, item in enumerate(kernel_evidence)
        if _kernel_text(item) == "h_psi"
        and index in full_kernel_indices
    }
    full_hpsi_seen = bool(full_hpsi_indices)
    hpsi_evidence_seen = any(_kernel_text(item) == "h_psi" for item in kernel_evidence)
    for index, item in enumerate(kernel_evidence):
        if _float_or_none(item.get("absolute_error")) is None or _float_or_none(item.get("relative_error")) is None:
            blockers.append(f"kernel_evidence_missing_error_metric:{index}")
        source = str(item.get("source") or item.get("source_kind") or "").strip().lower()
        if source in UNTRUSTED_QE_ACCELERATED_NUMERIC_SOURCES:
            blockers.append(f"kernel_evidence_untrusted_source:{index}:{source}")
        if item.get("baseline_copy") is True:
            blockers.append(f"kernel_evidence_marks_baseline_copy:{index}")
        if item.get("timing_only") is True:
            blockers.append(f"kernel_evidence_marks_timing_only:{index}")
        if item.get("host_stage_reference_assisted") is True:
            blockers.append(f"kernel_evidence_marks_host_stage_reference_assisted:{index}")
        if item.get("component_model_reference_replay_only") is True:
            blockers.append(f"kernel_evidence_marks_component_model_reference_replay_only:{index}")
        if item.get("software_component_model_not_l4") is True:
            blockers.append(f"kernel_evidence_marks_software_component_model_not_l4:{index}")
        if item.get("single_hpsi_call_smoke_only") is True:
            blockers.append(f"kernel_evidence_marks_single_hpsi_call_smoke_only:{index}")
        if item.get("all_observed_hpsi_calls_sidecar_consumed") is False:
            blockers.append(f"kernel_evidence_not_all_observed_hpsi_calls_sidecar_consumed:{index}")
        if _float_or_none(item.get("sidecar_failed_hpsi_calls")) not in {None, 0.0}:
            blockers.append(f"kernel_evidence_sidecar_failed_hpsi_calls:{index}:{item.get('sidecar_failed_hpsi_calls')}")
        blockers.extend(
            _validate_hpsi_sidecar_consumption_counters(
                item,
                blocker_prefix=f"kernel_evidence:{index}",
            )
        )
        kernel_id = _kernel_text(item)
        kernel_scope = _kernel_scope_text(item)
        if kernel_id == "h_psi":
            if not full_hpsi_seen and item.get("boundary_norm_probe_only") is True:
                blockers.append(f"kernel_evidence_boundary_norm_probe_only:{index}")
            if index not in full_hpsi_indices and not full_hpsi_seen:
                blockers.append(f"kernel_evidence_not_full_h_psi:{index}:{kernel_scope or 'missing_scope'}")
        elif index not in full_kernel_indices:
            blockers.append(
                f"kernel_evidence_not_full_kernel:{index}:{kernel_id or 'missing_kernel'}:{kernel_scope or 'missing_scope'}"
            )
    if not full_kernel_indices:
        blockers.append("missing_required_full_kernel_evidence")
    if hpsi_evidence_seen and not full_hpsi_seen:
        blockers.append("missing_required_full_h_psi_kernel_evidence")
    return blockers


def build_qe_accelerated_numeric_evidence(
    *,
    candidate_id: str,
    workload_case_id: str,
    baseline_comparison: Mapping[str, Any],
    accelerated_stdout: str,
    source_kind: str,
    kernel_evidence: Sequence[Mapping[str, Any]],
    provenance: Mapping[str, Any] | None = None,
    density_residual: float | None = None,
    force_error_ry_bohr: float | None = None,
    stress_error_kbar: float | None = None,
    accelerated_reference: Mapping[str, Any] | None = None,
    baseline_reference: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Compare baseline and accelerated QE outputs into one evidence row."""
    normalized_source = source_kind.strip().lower()
    blockers: list[str] = []
    if normalized_source in UNTRUSTED_QE_ACCELERATED_NUMERIC_SOURCES:
        blockers.append(f"untrusted_accelerated_numeric_source:{normalized_source}")
    elif normalized_source not in TRUSTED_QE_ACCELERATED_NUMERIC_SOURCES:
        blockers.append(f"unrecognized_accelerated_numeric_source:{normalized_source or 'missing'}")
    blockers.extend(validate_offload_provenance(provenance, normalized_source))

    baseline_metrics = _baseline_terminal_metrics(baseline_comparison)
    accelerated_metrics = parse_qe_stdout_metrics(accelerated_stdout)
    physical_evidence: Dict[str, float] = {}

    baseline_energy = _float_or_none(baseline_metrics.get("total_energy_ry"))
    accelerated_energy = _float_or_none(accelerated_metrics.get("total_energy_ry"))
    if baseline_energy is not None and accelerated_energy is not None:
        physical_evidence["total_energy_error_ry"] = abs(accelerated_energy - baseline_energy)
    else:
        blockers.append("missing_total_energy_for_scf_physical_evidence")

    eigen_errors: list[float] = []
    for field in ("highest_occupied_ev", "lowest_unoccupied_ev"):
        base = _float_or_none(baseline_metrics.get(field))
        accel = _float_or_none(accelerated_metrics.get(field))
        if base is not None and accel is not None:
            eigen_errors.append(abs(accel - base) / 13.605693122994)
    if eigen_errors:
        physical_evidence["eigenvalue_summary_error_ry"] = max(eigen_errors)
    else:
        blockers.append("missing_eigenvalue_summary_for_scf_physical_evidence")

    if density_residual is not None:
        physical_evidence["density_residual"] = float(density_residual)
    else:
        blockers.append("missing_density_residual_for_scf_physical_evidence")
    if force_error_ry_bohr is None:
        baseline_force = _float_or_none(baseline_metrics.get("total_force_ry_bohr"))
        accelerated_force = _float_or_none(accelerated_metrics.get("total_force_ry_bohr"))
        if baseline_force is not None and accelerated_force is not None:
            force_error_ry_bohr = abs(accelerated_force - baseline_force)
    if stress_error_kbar is None:
        baseline_pressure = _float_or_none(baseline_metrics.get("pressure_kbar"))
        accelerated_pressure = _float_or_none(accelerated_metrics.get("pressure_kbar"))
        if baseline_pressure is not None and accelerated_pressure is not None:
            stress_error_kbar = abs(accelerated_pressure - baseline_pressure)
    if force_error_ry_bohr is not None:
        physical_evidence["force_error_ry_bohr"] = float(force_error_ry_bohr)
    if stress_error_kbar is not None:
        physical_evidence["stress_error_kbar"] = float(stress_error_kbar)

    kernel_rows = [dict(item) for item in kernel_evidence if isinstance(item, Mapping)]
    blockers.extend(validate_kernel_numeric_evidence(kernel_rows))

    trusted = normalized_source in TRUSTED_QE_ACCELERATED_NUMERIC_SOURCES and not blockers
    return {
        "schema_version": QE_ACCELERATED_NUMERIC_EVIDENCE_SCHEMA,
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "source_kind": source_kind,
        "accelerated_output_status": "passed" if trusted else "blocked",
        "trusted_accelerated_numeric_source": trusted,
        "baseline_reference": dict(baseline_reference or {}),
        "accelerated_reference": dict(accelerated_reference or {}),
        "offload_provenance": dict(provenance or {}),
        "kernel_evidence": kernel_rows,
        "physical_evidence": physical_evidence,
        "blockers": sorted(dict.fromkeys(blockers)),
        "claim_boundary": (
            "Generated by an evidence collector only; trusted correctness still requires the matrix runner "
            "to re-check source kind and kernel/SCF deltas against frozen tolerances."
        ),
    }


def build_evidence_from_files(
    *,
    candidate_id: str,
    workload_case_id: str,
    baseline_comparison_path: Path,
    accelerated_stdout_path: Path,
    source_kind: str,
    kernel_evidence_path: Path | None,
    offload_provenance_path: Path | None,
    density_residual: float | None = None,
    force_error_ry_bohr: float | None = None,
    stress_error_kbar: float | None = None,
) -> Dict[str, Any]:
    baseline = _read_json(baseline_comparison_path)
    accelerated_stdout = accelerated_stdout_path.read_text(encoding="utf-8")
    kernel_evidence, kernel_blockers = _load_kernel_evidence(kernel_evidence_path)
    provenance = _read_json(offload_provenance_path) if offload_provenance_path and offload_provenance_path.exists() else None
    provenance_map = provenance if isinstance(provenance, Mapping) else {}
    provenance_physical = provenance_map.get("physical_evidence", {})
    provenance_physical_map = provenance_physical if isinstance(provenance_physical, Mapping) else {}
    if density_residual is None:
        density_residual = _float_or_none(provenance_map.get("density_residual") or provenance_physical_map.get("density_residual"))
    if force_error_ry_bohr is None:
        force_error_ry_bohr = _float_or_none(
            provenance_map.get("force_error_ry_bohr") or provenance_physical_map.get("force_error_ry_bohr")
        )
    if stress_error_kbar is None:
        stress_error_kbar = _float_or_none(provenance_map.get("stress_error_kbar") or provenance_physical_map.get("stress_error_kbar"))
    evidence = build_qe_accelerated_numeric_evidence(
        candidate_id=candidate_id,
        workload_case_id=workload_case_id,
        baseline_comparison=baseline,
        accelerated_stdout=accelerated_stdout,
        source_kind=source_kind,
        kernel_evidence=kernel_evidence,
        provenance=provenance_map,
        density_residual=density_residual,
        force_error_ry_bohr=force_error_ry_bohr,
        stress_error_kbar=stress_error_kbar,
        baseline_reference={"path": str(baseline_comparison_path)},
        accelerated_reference={
            "stdout_path": str(accelerated_stdout_path),
            "kernel_evidence_path": str(kernel_evidence_path) if kernel_evidence_path else None,
            "offload_provenance_path": str(offload_provenance_path) if offload_provenance_path else None,
        },
    )
    if kernel_blockers:
        evidence["blockers"] = sorted(dict.fromkeys([*evidence.get("blockers", []), *kernel_blockers]))
        evidence["trusted_accelerated_numeric_source"] = False
        evidence["accelerated_output_status"] = "blocked"
    return evidence


__all__ = [
    "QE_ACCELERATED_NUMERIC_EVIDENCE_SCHEMA",
    "TRUSTED_QE_ACCELERATED_NUMERIC_SOURCES",
    "UNTRUSTED_QE_ACCELERATED_NUMERIC_SOURCES",
    "REQUIRED_QE_ACCELERATED_PHYSICAL_FIELDS",
    "REQUIRED_FULL_HPSI_KERNEL_SCOPES",
    "build_evidence_from_files",
    "build_qe_accelerated_numeric_evidence",
    "parse_qe_stdout_metrics",
    "validate_kernel_numeric_evidence",
    "validate_offload_provenance",
]
