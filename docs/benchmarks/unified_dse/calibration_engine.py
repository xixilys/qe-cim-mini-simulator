from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from .interfaces import DESIGN_POINT_IDENTITY_KEYS, WORKLOAD_IDENTITY_KEYS


IDENTITY_KEYS = WORKLOAD_IDENTITY_KEYS + DESIGN_POINT_IDENTITY_KEYS


def apply_calibration_feedback(row: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
    for key in IDENTITY_KEYS:
        if key in feedback:
            raise ValueError(f"calibration feedback cannot update identity key: {key}")

    updated = deepcopy(row)
    feedback_copy: Mapping[str, Any] = deepcopy(feedback)
    if "source_kind" in feedback_copy and updated.get("source_kind") != "fast_model_screening":
        updated["source_kind"] = feedback_copy["source_kind"]
    updated["calibration"] = dict(feedback_copy)
    metrics = updated.get("metrics", {})
    residual = feedback_copy.get("calibration_residual_summary", {})
    if isinstance(metrics, Mapping) and isinstance(residual, Mapping):
        alpha_family = _float_or_default(feedback_copy.get("alpha_family"), 1.0)
        beta_workload = _float_or_default(feedback_copy.get("beta_workload"), 1.0)
        gamma_transfer = _float_or_default(feedback_copy.get("gamma_transfer"), 0.0)
        calibrated_metrics = corrected_metrics(metrics, alpha_family, beta_workload, gamma_transfer)
        updated["calibrated_metrics"] = calibrated_metrics
        updated["calibration_metadata"] = {
            "schema_version": "calibration_metadata_v0",
            "calibration_data_count": int(residual.get("sample_count") or 0),
            "error_before": residual.get("error_before", residual.get("max_relative_error")),
            "error_after": residual.get("error_after", residual.get("max_relative_error")),
            "validity_scope": feedback_copy.get("validity_scope", "stage_a_feedback_scope"),
            "confidence": feedback_copy.get("confidence", "low"),
            "alpha_family": alpha_family,
            "beta_workload": beta_workload,
            "gamma_transfer": gamma_transfer,
        }
    return updated


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def corrected_metrics(
    metrics: Mapping[str, Any],
    alpha_family: float,
    beta_workload: float,
    gamma_transfer: float,
) -> dict[str, Any]:
    calibrated_metrics = deepcopy(dict(metrics))
    if "time_to_convergence_s" in calibrated_metrics:
        calibrated_metrics["time_to_convergence_s"] = (
            _float_or_default(calibrated_metrics["time_to_convergence_s"], 0.0)
            * alpha_family
            * beta_workload
            + gamma_transfer
        )
    if "latency_s" in calibrated_metrics:
        calibrated_metrics["latency_s"] = (
            _float_or_default(calibrated_metrics["latency_s"], 0.0)
            * alpha_family
            * beta_workload
            + gamma_transfer
        )
    calibrated_metrics["calibration_formula"] = (
        "corrected_latency = fast_latency * alpha_family * beta_workload + gamma_transfer"
    )
    return calibrated_metrics


def fit_residual_calibration(
    rows: Sequence[Mapping[str, Any]],
    evidence_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    fast_by_candidate = {}
    for row in rows:
        candidate_id = _candidate_id(row)
        metrics = row.get("metrics", {})
        if candidate_id and isinstance(metrics, Mapping):
            fast_by_candidate[candidate_id] = metrics

    ratios = []
    abs_errors_before = []
    for evidence in evidence_rows:
        candidate_id = str(evidence.get("candidate_id"))
        fast_metrics = fast_by_candidate.get(candidate_id, {})
        evidence_metrics = evidence.get("metrics", {})
        if not isinstance(evidence_metrics, Mapping):
            continue
        fast_latency = _latency(fast_metrics)
        measured_latency = _latency(evidence_metrics)
        if fast_latency is None or measured_latency is None or fast_latency <= 0:
            continue
        ratios.append(measured_latency / fast_latency)
        abs_errors_before.append(abs(measured_latency - fast_latency) / max(1e-30, measured_latency))

    alpha = sum(ratios) / len(ratios) if ratios else 1.0
    errors_after = []
    for evidence in evidence_rows:
        candidate_id = str(evidence.get("candidate_id"))
        fast_metrics = fast_by_candidate.get(candidate_id, {})
        evidence_metrics = evidence.get("metrics", {})
        if not isinstance(evidence_metrics, Mapping):
            continue
        fast_latency = _latency(fast_metrics)
        measured_latency = _latency(evidence_metrics)
        if fast_latency is None or measured_latency is None:
            continue
        corrected = fast_latency * alpha
        errors_after.append(abs(measured_latency - corrected) / max(1e-30, measured_latency))

    return {
        "schema_version": "calibration_metadata_v0",
        "calibration_model_schema_version": "calibration_model_v0",
        "formula": "corrected_latency = fast_latency * alpha_family * beta_workload + gamma_transfer",
        "calibration_data_count": len(ratios),
        "error_before": max(abs_errors_before) if abs_errors_before else None,
        "error_after": max(errors_after) if errors_after else None,
        "validity_scope": "family_workload_stage_a_scope",
        "confidence": "medium" if len(ratios) >= 3 else "low",
        "alpha_family": alpha,
        "beta_workload": 1.0,
        "gamma_transfer": 0.0,
        "training_evidence_refs": [
            evidence.get("artifact_refs", {})
            for evidence in evidence_rows
            if isinstance(evidence.get("artifact_refs", {}), Mapping)
        ],
        "grouping": {
            "family": "pooled" if len(ratios) < 3 else "family_workload",
            "workload": "pooled" if len(ratios) < 3 else "workload_domain",
            "backend_fidelity": sorted(
                {
                    str(evidence.get("fidelity"))
                    for evidence in evidence_rows
                    if evidence.get("fidelity")
                }
            ),
        },
    }


def fit_calibration_model(
    rows: Sequence[Mapping[str, Any]],
    evidence_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    metadata = fit_residual_calibration(rows, evidence_rows)
    return {
        "schema_version": "calibration_model_v0",
        "metadata": dict(metadata),
        "formula": metadata["formula"],
        "parameters": {
            "alpha_family": metadata["alpha_family"],
            "beta_workload": metadata["beta_workload"],
            "gamma_transfer": metadata["gamma_transfer"],
        },
        "validity_scope": metadata["validity_scope"],
        "confidence": metadata["confidence"],
        "claim_ceiling": "fast_model_calibrated_screening_only",
        "non_claims": [
            "not_final_performance_truth",
            "not_board_measured",
            "not_qe_correctness_evidence",
        ],
    }


def apply_calibration_metadata_to_rows(
    rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
) -> list[dict[str, Any]]:
    alpha = _float_or_default(metadata.get("alpha_family"), 1.0)
    beta = _float_or_default(metadata.get("beta_workload"), 1.0)
    gamma = _float_or_default(metadata.get("gamma_transfer"), 0.0)
    updated = []
    for row in rows:
        copied = deepcopy(dict(row))
        metrics = copied.get("metrics", {})
        if isinstance(metrics, Mapping):
            copied["calibrated_metrics"] = corrected_metrics(metrics, alpha, beta, gamma)
            copied["calibration_metadata"] = dict(metadata)
            if copied.get("source_kind") == "fast_model_screening":
                copied["ranking_claim_ceiling"] = "fast_model_calibrated_screening"
        updated.append(copied)
    return updated


def _latency(metrics: Mapping[str, Any]) -> float | None:
    for key in ("time_to_convergence_s", "latency_s", "time_proxy_s"):
        if key not in metrics:
            continue
        try:
            return float(metrics[key])
        except (TypeError, ValueError):
            return None
    return None


def _candidate_id(row: Mapping[str, Any]) -> str | None:
    for key in ("systemc_feedback_contract", "candidate_descriptor", "evidence_ir"):
        value = row.get(key)
        if isinstance(value, Mapping) and value.get("candidate_id"):
            return str(value["candidate_id"])
    if row.get("candidate_id"):
        return str(row["candidate_id"])
    return None
