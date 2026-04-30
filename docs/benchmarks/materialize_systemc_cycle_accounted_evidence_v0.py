#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import gmtime, strftime
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "systemc_cycle_accounted_evidence_v0"
MATRIX_SCHEMA_VERSION = "systemc_cycle_accounted_evidence_matrix_v0"
EVIDENCE_TIER_LABEL = "systemc-cycle-accounted"
DEFAULT_MATRIX_NAME = "systemc_cycle_accounted_evidence_matrix_v0.json"
DEFAULT_NON_CLAIMS = [
    "systemc_cycle_accounting_only",
    "not_rtl_cycle_accurate",
    "not_board_or_asic_measured",
    "not_physical_timing_signoff",
    "not_cpu_gpu_superiority_evidence",
    "not_final_best_architecture_claim",
]
CLUSTER_STAGE_NAMES = {
    "cluster_a": "operator_sweep_projector_backproject",
    "cluster_b": "reduction_build",
    "cluster_c": "solver_diagonalization",
    "cluster_d": "refresh_residual_writeback",
}
CLUSTER_STAGE_DESCRIPTIONS = {
    "cluster_a": "Cluster A operator/projector/backproject SystemC-accounted work.",
    "cluster_b": "Cluster B reduced build and collective reduction SystemC-accounted work.",
    "cluster_c": "Cluster C solver/diagonalization SystemC-accounted work.",
    "cluster_d": "Cluster D refresh/residual/writeback SystemC-accounted work.",
}


class CycleEvidenceInputError(ValueError):
    pass


def load_json_object(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CycleEvidenceInputError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def sha256_json(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def artifact_hash(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve(strict=False)
    if not resolved.exists():
        raise CycleEvidenceInputError(f"artifact does not exist: {path}")
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    if parsed < 0.0:
        return None
    return parsed


def _positive_number(value: Any) -> float | None:
    parsed = _number_or_none(value)
    if parsed is None or parsed <= 0.0:
        return None
    return parsed


def _cycle_value(value: float | int) -> int | float:
    if float(value).is_integer():
        return int(value)
    return value


def _path_from_ref(value: Any, *, base: Path | None = None) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_absolute() and base is not None:
        path = base / path
    return path.expanduser().resolve(strict=False)


def parse_key_path(items: Sequence[str], option_name: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for raw in items:
        if "=" not in raw:
            raise CycleEvidenceInputError(f"{option_name} must use key=path form: {raw}")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise CycleEvidenceInputError(f"{option_name} key must be non-empty")
        if key in result:
            raise CycleEvidenceInputError(f"{option_name} specified more than once for key={key}")
        result[key] = Path(value.strip())
    return result


def _assert_same_if_present(name: str, explicit: str | None, discovered: str | None) -> None:
    if explicit and discovered and explicit != discovered:
        raise CycleEvidenceInputError(
            f"{name} mismatch: explicit {explicit!r} does not match discovered {discovered!r}"
        )


def _source_row_context(row: Mapping[str, Any] | None, row_base: Path | None) -> dict[str, Any]:
    if row is None:
        return {}
    workload = _mapping(row.get("workload"))
    artifacts = _mapping(row.get("artifacts"))
    projection = _mapping(row.get("projection"))
    return {
        "candidate_id": _string_or_none(row.get("candidate_id")) or _string_or_none(row.get("result_id")),
        "workload_id": _string_or_none(row.get("workload_id")) or _string_or_none(workload.get("workload_id")),
        "case_id": _string_or_none(row.get("case_id")) or _string_or_none(workload.get("case_id")),
        "architecture_template_id": _string_or_none(row.get("architecture_template_id")),
        "template_artifact_sha256": _string_or_none(row.get("template_artifact_sha256")),
        "systemc_config_ref": _path_from_ref(row.get("projected_config_path"), base=row_base),
        "systemc_candidate_result_ref": _path_from_ref(artifacts.get("metrics_path"), base=row_base),
        "model_support_status": _string_or_none(row.get("support_status"))
        or _string_or_none(projection.get("support_status")),
        "support_evidence": dict(_mapping(row.get("support_evidence"))),
    }


def _config_context(config: Mapping[str, Any] | None) -> dict[str, Any]:
    if config is None:
        return {}
    metadata = _mapping(config.get("projection_metadata"))
    return {
        "candidate_id": _string_or_none(metadata.get("candidate_id")),
        "architecture_template_id": _string_or_none(metadata.get("source_template_id")),
        "template_artifact_sha256": _string_or_none(metadata.get("source_template_sha256")),
        "model_support_status": _string_or_none(metadata.get("support_status")),
        "support_evidence": dict(_mapping(metadata.get("support_evidence"))),
        "design_space_spec_id": _string_or_none(metadata.get("design_space_spec_id")),
        "design_space_spec_sha256": _string_or_none(metadata.get("design_space_spec_sha256")),
    }


def resolve_identity(
    *,
    candidate: Mapping[str, Any],
    candidate_result_path: Path,
    explicit_candidate_id: str | None,
    explicit_workload_id: str | None,
    explicit_architecture_template_id: str | None,
    source_row: Mapping[str, Any] | None,
    source_row_base: Path | None,
    systemc_config: Mapping[str, Any] | None,
) -> dict[str, Any]:
    row_context = _source_row_context(source_row, source_row_base)
    config_context = _config_context(systemc_config)
    run_config = _mapping(candidate.get("run_config"))

    discovered_candidate_id = _string_or_none(candidate.get("candidate_id"))
    for source_name, candidate_id in (
        ("source row", row_context.get("candidate_id")),
        ("systemc config", config_context.get("candidate_id")),
    ):
        try:
            _assert_same_if_present("candidate_id", discovered_candidate_id, candidate_id)
        except CycleEvidenceInputError as exc:
            raise CycleEvidenceInputError(f"{source_name} {exc}") from exc
    _assert_same_if_present("candidate_id", row_context.get("candidate_id"), config_context.get("candidate_id"))
    _assert_same_if_present("candidate_id", explicit_candidate_id, discovered_candidate_id)
    _assert_same_if_present("candidate_id", explicit_candidate_id, row_context.get("candidate_id"))
    _assert_same_if_present("candidate_id", explicit_candidate_id, config_context.get("candidate_id"))

    candidate_id = (
        explicit_candidate_id
        or discovered_candidate_id
        or row_context.get("candidate_id")
        or config_context.get("candidate_id")
        or candidate_result_path.stem
    )
    workload_id = (
        explicit_workload_id
        or _string_or_none(candidate.get("workload_id"))
        or row_context.get("workload_id")
        or _string_or_none(run_config.get("workload_id"))
        or _string_or_none(candidate.get("case_id"))
        or _string_or_none(run_config.get("case_id"))
    )
    if not workload_id:
        raise CycleEvidenceInputError("workload_id is required; pass --workload-id or a source row/config carrying it")
    architecture_template_id = (
        explicit_architecture_template_id
        or row_context.get("architecture_template_id")
        or config_context.get("architecture_template_id")
        or _string_or_none(candidate.get("architecture_template_id"))
        or _string_or_none(candidate.get("architecture_family"))
    )

    model_support_status = (
        config_context.get("model_support_status")
        or row_context.get("model_support_status")
        or _string_or_none(candidate.get("model_support_status"))
        or "systemc_result_available"
    )
    support_evidence = {}
    support_evidence.update(dict(row_context.get("support_evidence") or {}))
    support_evidence.update(dict(config_context.get("support_evidence") or {}))
    return {
        "candidate_id": str(candidate_id),
        "workload_id": str(workload_id),
        "case_id": (
            _string_or_none(candidate.get("case_id"))
            or row_context.get("case_id")
            or _string_or_none(run_config.get("case_id"))
            or str(workload_id)
        ),
        "architecture_template_id": architecture_template_id,
        "template_artifact_sha256": (
            row_context.get("template_artifact_sha256")
            or config_context.get("template_artifact_sha256")
        ),
        "model_support_status": model_support_status,
        "support_evidence": support_evidence,
        "design_space_spec_id": config_context.get("design_space_spec_id"),
        "design_space_spec_sha256": config_context.get("design_space_spec_sha256"),
    }


def _component_cycles(cluster_metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cluster_id in sorted(cluster_metrics):
        item = cluster_metrics[cluster_id]
        if not isinstance(item, Mapping):
            continue
        accounted_cycles = _positive_number(item.get("accounted_ref_cycles"))
        if accounted_cycles is None:
            continue
        stage_name = CLUSTER_STAGE_NAMES.get(str(cluster_id), str(cluster_id))
        rows.append(
            {
                "component_id": str(item.get("dominant_resource") or item.get("cluster_name") or cluster_id),
                "component_name": str(item.get("cluster_name") or cluster_id),
                "stage_id": str(cluster_id),
                "stage_name": stage_name,
                "cycles": _cycle_value(accounted_cycles),
                "invocations": item.get("invocations"),
                "backpressure_cycles": _cycle_value(_number_or_none(item.get("backpressure_ref_cycles")) or 0.0),
                "data_movement_kib": item.get("data_movement_kib"),
                "dominant_resource": item.get("dominant_resource"),
                "detail": item.get("detail"),
                "source": "systemc_cluster_metrics.accounted_ref_cycles",
            }
        )
    return rows


def _metric_cycle(metrics: Mapping[str, Any], field: str) -> float | None:
    return _positive_number(metrics.get(field))


def _cluster_cycle_total(component_rows: Sequence[Mapping[str, Any]]) -> float:
    total = 0.0
    for row in component_rows:
        cycles = _number_or_none(row.get("cycles"))
        if cycles is not None:
            total += cycles
    return total


def build_cycle_accounting(candidate: Mapping[str, Any]) -> dict[str, Any]:
    run_summary = _mapping(candidate.get("run_summary"))
    metrics = _mapping(candidate.get("metrics"))
    cluster_metrics = _mapping(candidate.get("cluster_metrics"))
    component_rows = _component_cycles(cluster_metrics)
    cluster_total = _cluster_cycle_total(component_rows)
    device_busy_cycles = _metric_cycle(metrics, "device_busy_ref_cycles") or (cluster_total or None)
    dma_cycles = _metric_cycle(metrics, "dma_ref_cycles")
    host_assist_cycles = _metric_cycle(metrics, "host_assist_ref_cycles")
    run_summary_total = _positive_number(run_summary.get("total_ref_cycles"))

    component_metric_total = sum(
        value for value in (device_busy_cycles, dma_cycles, host_assist_cycles) if value is not None
    )
    total_cycles = run_summary_total or (component_metric_total if component_metric_total > 0.0 else cluster_total)
    if total_cycles <= 0.0:
        raise CycleEvidenceInputError("SystemC candidate result does not contain positive cycle evidence")

    stage_rows: list[dict[str, Any]] = []
    for component in component_rows:
        cluster_id = str(component["stage_id"])
        cycles = _number_or_none(component.get("cycles"))
        if cycles is None:
            continue
        stage_rows.append(
            {
                "stage_id": cluster_id,
                "stage_name": component["stage_name"],
                "cycles": _cycle_value(cycles),
                "cycle_role": "systemc_accounted_datapath",
                "included_in_total": True,
                "description": CLUSTER_STAGE_DESCRIPTIONS.get(cluster_id, "SystemC-accounted cluster work."),
                "source": "systemc_cluster_metrics.accounted_ref_cycles",
            }
        )
    if dma_cycles is not None:
        stage_rows.append(
            {
                "stage_id": "dma_transfer",
                "stage_name": "memory_dma_transfer",
                "cycles": _cycle_value(dma_cycles),
                "cycle_role": "systemc_accounted_memory_dma",
                "included_in_total": True,
                "description": "SystemC-accounted memory/DMA movement cycles from metrics.dma_ref_cycles.",
                "source": "systemc_metrics.dma_ref_cycles",
            }
        )
    if host_assist_cycles is not None:
        stage_rows.append(
            {
                "stage_id": "host_assist_control",
                "stage_name": "host_assist_queue_control",
                "cycles": _cycle_value(host_assist_cycles),
                "cycle_role": "systemc_accounted_host_control",
                "included_in_total": True,
                "description": "SystemC-accounted host assist, queue, and control cycles.",
                "source": "systemc_metrics.host_assist_ref_cycles",
            }
        )

    included_total = sum(float(row["cycles"]) for row in stage_rows if row.get("included_in_total") is True)
    residual_cycles = total_cycles - included_total
    if residual_cycles > 0.0:
        stage_rows.append(
            {
                "stage_id": "unattributed_control_or_scheduler_residual",
                "stage_name": "unattributed_control_or_scheduler_residual",
                "cycles": _cycle_value(residual_cycles),
                "cycle_role": "systemc_accounted_residual",
                "included_in_total": True,
                "description": "Residual cycles needed to reconcile per-stage table to run_summary.total_ref_cycles.",
                "source": "systemc_run_summary.total_ref_cycles_minus_accounted_stage_cycles",
            }
        )

    backpressure_cycles = _number_or_none(run_summary.get("total_backpressure_ref_cycles"))
    if backpressure_cycles is None:
        backpressure_cycles = sum(
            _number_or_none(row.get("backpressure_cycles")) or 0.0 for row in component_rows
        )
    if backpressure_cycles > 0.0:
        stage_rows.append(
            {
                "stage_id": "backpressure_diagnostic",
                "stage_name": "backpressure_diagnostic",
                "cycles": _cycle_value(backpressure_cycles),
                "cycle_role": "diagnostic_overlap_not_summed",
                "included_in_total": False,
                "description": "Backpressure diagnostic cycles; reported separately to avoid double-counting.",
                "source": "systemc_run_summary_or_cluster_metrics.backpressure_ref_cycles",
            }
        )

    if not stage_rows or not component_rows:
        raise CycleEvidenceInputError("SystemC candidate result must contain per-stage and per-component cycle rows")

    included_total = sum(float(row["cycles"]) for row in stage_rows if row.get("included_in_total") is True)
    return {
        "cycle_source": "systemc_run_summary_and_cluster_metrics",
        "total_cycles": _cycle_value(total_cycles),
        "included_stage_cycle_total": _cycle_value(included_total),
        "per_stage_cycle_table": stage_rows,
        "per_component_cycle_table": component_rows,
        "diagnostic_cycle_fields": {
            "run_summary_total_ref_cycles": _cycle_value(run_summary_total) if run_summary_total is not None else None,
            "metrics_device_busy_ref_cycles": _cycle_value(device_busy_cycles) if device_busy_cycles is not None else None,
            "metrics_dma_ref_cycles": _cycle_value(dma_cycles) if dma_cycles is not None else None,
            "metrics_host_assist_ref_cycles": _cycle_value(host_assist_cycles) if host_assist_cycles is not None else None,
            "cluster_accounted_ref_cycles_total": _cycle_value(cluster_total),
            "backpressure_ref_cycles": _cycle_value(backpressure_cycles),
        },
    }


def build_calibration_refs(refs: Mapping[str, Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ref_id, path in sorted(refs.items()):
        rows.append(
            {
                "ref_id": ref_id,
                **artifact_hash(path),
            }
        )
    return rows


def materialize_systemc_cycle_evidence(
    *,
    systemc_candidate_result: Path,
    candidate_id: str | None = None,
    workload_id: str | None = None,
    architecture_template_id: str | None = None,
    architecture_template_ref: Path | None = None,
    systemc_config_ref: Path | None = None,
    source_row_ref: Path | None = None,
    calibration_refs: Mapping[str, Path] | None = None,
    output_ref: Path | None = None,
) -> dict[str, Any]:
    candidate_result_path = systemc_candidate_result.expanduser().resolve(strict=False)
    candidate = load_json_object(candidate_result_path)
    if candidate.get("schema_version") not in (None, "systemc_architecture_candidate_result_v0"):
        raise CycleEvidenceInputError("unsupported SystemC candidate result schema_version")

    row_base: Path | None = None
    source_row: Mapping[str, Any] | None = None
    if source_row_ref is not None:
        row_path = source_row_ref.expanduser().resolve(strict=False)
        source_row = load_json_object(row_path)
        row_base = row_path.parent
    row_context = _source_row_context(source_row, row_base)
    if systemc_config_ref is None:
        systemc_config_ref = row_context.get("systemc_config_ref")

    systemc_config: Mapping[str, Any] | None = None
    if systemc_config_ref is not None:
        systemc_config = load_json_object(systemc_config_ref)

    identity = resolve_identity(
        candidate=candidate,
        candidate_result_path=candidate_result_path,
        explicit_candidate_id=candidate_id,
        explicit_workload_id=workload_id,
        explicit_architecture_template_id=architecture_template_id,
        source_row=source_row,
        source_row_base=row_base,
        systemc_config=systemc_config,
    )
    cycle_accounting = build_cycle_accounting(candidate)
    calibration_rows = build_calibration_refs(calibration_refs or {})
    artifact_hashes = {
        "systemc_candidate_result": artifact_hash(candidate_result_path),
        "architecture_template": artifact_hash(architecture_template_ref) if architecture_template_ref else None,
        "systemc_config": artifact_hash(systemc_config_ref) if systemc_config_ref else None,
        "source_row": artifact_hash(source_row_ref) if source_row_ref else None,
        "calibration_refs": {row["ref_id"]: row["sha256"] for row in calibration_rows},
    }
    template_config_hash = sha256_json(
        {
            "candidate_id": identity["candidate_id"],
            "workload_id": identity["workload_id"],
            "architecture_template_id": identity.get("architecture_template_id"),
            "template_artifact_sha256": identity.get("template_artifact_sha256"),
            "architecture_template_ref_sha256": (
                artifact_hashes["architecture_template"]["sha256"]
                if artifact_hashes["architecture_template"]
                else None
            ),
            "systemc_config_ref_sha256": (
                artifact_hashes["systemc_config"]["sha256"] if artifact_hashes["systemc_config"] else None
            ),
            "design_space_spec_sha256": identity.get("design_space_spec_sha256"),
        }
    )
    generated_at = strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "evidence_tier_label": EVIDENCE_TIER_LABEL,
        "claim_label": EVIDENCE_TIER_LABEL,
        "candidate_id": identity["candidate_id"],
        "workload_id": identity["workload_id"],
        "case_id": identity["case_id"],
        "architecture_template_id": identity.get("architecture_template_id"),
        "template_config_hash": template_config_hash,
        "template_artifact_sha256": identity.get("template_artifact_sha256"),
        "cycle_accounting": cycle_accounting,
        "model_support_status": {
            "status": identity["model_support_status"],
            "source": "systemc_config_projection_metadata_or_source_row",
            "support_evidence": identity["support_evidence"],
        },
        "calibration_refs": calibration_rows,
        "artifact_hashes": artifact_hashes,
        "artifact_refs": {
            "systemc_candidate_result": str(candidate_result_path),
            "architecture_template": str(architecture_template_ref.expanduser().resolve(strict=False))
            if architecture_template_ref
            else None,
            "systemc_config": str(systemc_config_ref.expanduser().resolve(strict=False))
            if systemc_config_ref
            else None,
            "source_row": str(source_row_ref.expanduser().resolve(strict=False)) if source_row_ref else None,
        },
        "final_best_eligible": False,
        "final_best_claim": False,
        "claim_ceiling": "systemc_cycle_accounted_not_final_best",
        "claim_boundary": {
            "may_promote_to_final_best_by_itself": False,
            "requires_exact_same_candidate_stage_c_strict_b4_stage_d": True,
            "cycle_accuracy_claim": False,
            "rtl_or_physical_timing_claim": False,
            "board_or_asic_measurement_claim": False,
        },
        "non_claims": list(DEFAULT_NON_CLAIMS),
        "non_claim_summary": (
            "This artifact is SystemC cycle-accounted evidence for the named candidate/workload only; "
            "it is not an RTL, board, ASIC, physical-timing, GPU-superiority, or final-best claim."
        ),
    }
    if output_ref is not None:
        payload["report_ref"] = str(output_ref)
    validate_cycle_evidence(payload)
    return payload


def validate_cycle_evidence(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CycleEvidenceInputError("invalid schema_version")
    if payload.get("evidence_tier_label") != EVIDENCE_TIER_LABEL:
        raise CycleEvidenceInputError("SystemC evidence must use systemc-cycle-accounted label")
    if payload.get("final_best_eligible") is not False or payload.get("final_best_claim") is not False:
        raise CycleEvidenceInputError("SystemC cycle evidence must not claim final-best eligibility by itself")
    for field in ("candidate_id", "workload_id", "template_config_hash"):
        if not payload.get(field):
            raise CycleEvidenceInputError(f"missing required field: {field}")
    accounting = _mapping(payload.get("cycle_accounting"))
    if _positive_number(accounting.get("total_cycles")) is None:
        raise CycleEvidenceInputError("cycle_accounting.total_cycles must be positive")
    if not _list(accounting.get("per_stage_cycle_table")):
        raise CycleEvidenceInputError("missing per_stage_cycle_table")
    if not _list(accounting.get("per_component_cycle_table")):
        raise CycleEvidenceInputError("missing per_component_cycle_table")
    non_claims = {str(item) for item in _list(payload.get("non_claims"))}
    for required in ("systemc_cycle_accounting_only", "not_rtl_cycle_accurate", "not_final_best_architecture_claim"):
        if required not in non_claims:
            raise CycleEvidenceInputError(f"missing non-claim: {required}")
    claim_boundary = _mapping(payload.get("claim_boundary"))
    if claim_boundary.get("cycle_accuracy_claim") is not False:
        raise CycleEvidenceInputError("cycle_accuracy_claim must be false")


def materialize_many_from_map(
    *,
    candidate_map: Path,
    output_dir: Path,
    matrix_name: str = DEFAULT_MATRIX_NAME,
) -> dict[str, Any]:
    payload = load_json_object(candidate_map)
    entries_raw = payload.get("candidates") or payload.get("rows") or payload.get("evidence")
    if not isinstance(entries_raw, list):
        raise CycleEvidenceInputError("candidate map must contain a candidates, rows, or evidence list")
    reports_dir = output_dir / "systemc_cycle_accounted_evidence"
    rows: list[dict[str, Any]] = []
    for index, entry_raw in enumerate(entries_raw):
        if not isinstance(entry_raw, Mapping):
            raise CycleEvidenceInputError(f"candidate map entry {index} must be an object")
        entry = dict(entry_raw)
        candidate_result = _path_from_ref(
            entry.get("systemc_candidate_result")
            or entry.get("systemc_result")
            or _mapping(entry.get("artifact_refs")).get("systemc_candidate_result")
            or _mapping(entry.get("artifacts")).get("metrics_path"),
            base=candidate_map.parent,
        )
        if candidate_result is None:
            raise CycleEvidenceInputError(f"candidate map entry {index} missing systemc_candidate_result")
        template_ref = _path_from_ref(entry.get("architecture_template_ref"), base=candidate_map.parent)
        config_ref = _path_from_ref(
            entry.get("systemc_config_ref") or entry.get("projected_config_path"),
            base=candidate_map.parent,
        )
        candidate_id = _string_or_none(entry.get("candidate_id")) or candidate_result.stem
        output = reports_dir / f"{sanitize_id_part(candidate_id)}.systemc_cycle_accounted_evidence_v0.json"
        report = materialize_systemc_cycle_evidence(
            systemc_candidate_result=candidate_result,
            candidate_id=candidate_id,
            workload_id=_string_or_none(entry.get("workload_id")),
            architecture_template_id=_string_or_none(entry.get("architecture_template_id")),
            architecture_template_ref=template_ref,
            systemc_config_ref=config_ref,
            calibration_refs={},
            output_ref=output,
        )
        write_json(output, report)
        rows.append(
            {
                "candidate_id": report["candidate_id"],
                "workload_id": report["workload_id"],
                "evidence_tier_label": report["evidence_tier_label"],
                "total_cycles": report["cycle_accounting"]["total_cycles"],
                "model_support_status": report["model_support_status"]["status"],
                "report_path": str(output),
                "report_sha256": sha256_file(output),
            }
        )
    matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "generated_at_utc": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
        "source_candidate_map": str(candidate_map),
        "reports_dir": str(reports_dir),
        "row_count": len(rows),
        "tier_counts": {EVIDENCE_TIER_LABEL: len(rows)},
        "rows": rows,
        "non_claims": list(DEFAULT_NON_CLAIMS),
    }
    write_json(output_dir / matrix_name, matrix)
    return matrix


def sanitize_id_part(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value.strip())
    return cleaned.strip("_") or "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize SystemC cycle-accounted evidence for an exact DSE candidate/workload."
    )
    parser.add_argument("--systemc-candidate-result", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--candidate-id")
    parser.add_argument("--workload-id")
    parser.add_argument("--architecture-template-id")
    parser.add_argument("--architecture-template-ref", type=Path)
    parser.add_argument("--systemc-config-ref", type=Path)
    parser.add_argument("--source-row-ref", type=Path)
    parser.add_argument("--calibration-ref", action="append", default=[], metavar="ref_id=path")
    parser.add_argument("--candidate-map", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--matrix-name", default=DEFAULT_MATRIX_NAME)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.candidate_map is not None:
            if args.output_dir is None:
                raise CycleEvidenceInputError("--output-dir is required with --candidate-map")
            materialize_many_from_map(
                candidate_map=args.candidate_map,
                output_dir=args.output_dir,
                matrix_name=args.matrix_name,
            )
            return 0
        if args.systemc_candidate_result is None:
            raise CycleEvidenceInputError("--systemc-candidate-result is required without --candidate-map")
        if args.output is None:
            raise CycleEvidenceInputError("--output is required without --candidate-map")
        calibration_refs = parse_key_path(args.calibration_ref, "--calibration-ref")
        payload = materialize_systemc_cycle_evidence(
            systemc_candidate_result=args.systemc_candidate_result,
            candidate_id=args.candidate_id,
            workload_id=args.workload_id,
            architecture_template_id=args.architecture_template_id,
            architecture_template_ref=args.architecture_template_ref,
            systemc_config_ref=args.systemc_config_ref,
            source_row_ref=args.source_row_ref,
            calibration_refs=calibration_refs,
            output_ref=args.output,
        )
    except CycleEvidenceInputError as exc:
        parser.error(str(exc))
    write_json(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
