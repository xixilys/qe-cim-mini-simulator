#!/usr/bin/env python3
"""DFT/QE full-SCF hardware DSE workstream contracts.

This module keeps the DFT/QE-specific admission, release policy, evidence-gate,
and Wave 1.5 trace helpers out of the domain-neutral control-plane contracts.
The payloads are intentionally small dictionaries so Step1--Step5 lanes can
share fail-closed decisions without importing optional QE runtimes.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, Sequence


STRICT_DFT_QE_WORKLOAD_CLASSES: tuple[str, ...] = (
    "small_multi_k_scf",
    "metal_smearing_scf",
    "insulator_scf",
    "slab_vacuum_large_fft_scf",
    "gamma_only_supercell_scf",
    "projector_orthogonalization_heavy_scf",
)

STRICT_BUNDLE_REQUIRED_ASSETS: tuple[str, ...] = (
    "qe_input",
    "pseudopotential",
    "run_command",
    "reference_output_hash",
    "provenance",
    "license",
    "parser_tool_version",
    "proof_class",
)

CLAIM_BASE_EVIDENCE_GROUPS: Mapping[str, tuple[str, ...]] = {
    "golden_correctness": (
        "golden_correctness",
        "reference_correctness",
        "numerical_correctness",
        "correctness_oracle",
    ),
    "simulation": ("hls_csim", "rtl_sim", "hls_c_sim", "vcs_rtl_sim"),
    "synthesis": ("hls_csynth", "rtl_synth", "hls_c_synth", "rtl_synthesis"),
}

CLAIM_BRANCH_EVIDENCE_GROUPS: Mapping[str, tuple[str, ...]] = {
    "fpga": (
        "vivado_implementation",
        "vivado_impl",
        "vivado_route",
        "vivado_place_route",
        "fpga_implementation",
    ),
    "asic": ("dc_synth_timing_area", "dc_synth", "dc_timing", "dc_area", "asic_synthesis"),
}

UNAVAILABLE_STATUSES = {
    "unavailable",
    "tool_unavailable",
    "missing_tool",
    "not_found",
    "failed_to_launch",
}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return bool(value)
    return True


def _case_id(case: Mapping[str, Any], index: int) -> str:
    return str(case.get("case_id") or case.get("workload_case_id") or f"case-{index}")


def _asset_present(case: Mapping[str, Any], asset: str) -> bool:
    """Return whether a strict-bundle asset is present, accepting stable aliases."""

    input_hashes = _as_mapping(case.get("input_hashes"))
    provenance = _as_mapping(case.get("provenance") or case.get("baseline_run_provenance"))

    if asset == "qe_input":
        return any(
            _non_empty(case.get(key))
            for key in ("qe_input", "qe_input_path", "input_file", "input_deck")
        ) or _non_empty(input_hashes.get("qe_input") or input_hashes.get("input_deck"))
    if asset == "pseudopotential":
        return any(
            _non_empty(case.get(key))
            for key in ("pseudopotential", "pseudopotentials", "pseudopotential_hashes")
        ) or _non_empty(input_hashes.get("pseudopotential") or input_hashes.get("pseudopotentials"))
    if asset == "run_command":
        return _non_empty(case.get("run_command") or case.get("qe_command"))
    if asset == "reference_output_hash":
        return _non_empty(
            case.get("reference_output_hash")
            or case.get("reference_hash")
            or case.get("expected_output_hash")
        )
    if asset == "provenance":
        return _non_empty(provenance)
    if asset == "license":
        return _non_empty(case.get("license") or provenance.get("license"))
    if asset == "parser_tool_version":
        return _non_empty(case.get("parser_tool_version")) or (
            _non_empty(case.get("parser_version")) and _non_empty(case.get("tool_version"))
        )
    if asset == "proof_class":
        return _non_empty(case.get("proof_class") or case.get("proof_class_label"))
    return _non_empty(case.get(asset))


def validate_strict_dft_qe_bundle(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate strict Step1 DFT/QE workload-bundle admission.

    The validator fails closed: a bundle is admitted only when every required
    workload class is represented and every case carries the source assets that
    make later Step2--Step5 claims replayable.
    """

    cases = [case for case in _as_list(bundle.get("cases") or bundle.get("workloads")) if isinstance(case, Mapping)]
    class_values = set(str(item) for item in _as_list(bundle.get("workload_classes")))
    for case in cases:
        for key in ("workload_class", "stage_type", "class_id"):
            if _non_empty(case.get(key)):
                class_values.add(str(case[key]))

    missing_classes = [
        class_id for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES if class_id not in class_values
    ]
    missing_assets: List[Dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        for asset in STRICT_BUNDLE_REQUIRED_ASSETS:
            if not _asset_present(case, asset):
                missing_assets.append(
                    {
                        "case_id": _case_id(case, index),
                        "asset": asset,
                        "reason": "required strict DFT/QE bundle asset is absent",
                    }
                )

    blockers: List[Dict[str, Any]] = []
    if not _non_empty(bundle.get("bundle_id")):
        blockers.append({"id": "missing_bundle_id", "reason": "strict bundle requires bundle_id"})
    if not _non_empty(bundle.get("campaign_id")):
        blockers.append({"id": "missing_campaign_id", "reason": "strict bundle requires campaign_id"})
    if not _non_empty(bundle.get("workload_run_id")):
        blockers.append({"id": "missing_workload_run_id", "reason": "strict bundle requires workload_run_id"})
    if bundle.get("strict") is not True:
        blockers.append({"id": "strict_flag_not_true", "reason": "bundle strict flag must be true"})
    if not cases:
        blockers.append({"id": "missing_cases", "reason": "strict bundle requires at least one case"})
    if missing_classes:
        blockers.append(
            {
                "id": "missing_required_workload_classes",
                "reason": "strict DFT/QE bundle does not cover all six required classes",
                "missing_classes": missing_classes,
            }
        )
    if missing_assets:
        blockers.append(
            {
                "id": "missing_required_assets",
                "reason": "one or more workload cases are missing strict replay assets",
                "missing_assets": missing_assets,
            }
        )

    admitted = not blockers
    return {
        "schema_version": "dse.dft_scf.strict_bundle_validation.v1",
        "bundle_id": bundle.get("bundle_id"),
        "campaign_id": bundle.get("campaign_id"),
        "workload_run_id": bundle.get("workload_run_id"),
        "status": "passed" if admitted else "blocked",
        "admitted": admitted,
        "required_workload_classes": list(STRICT_DFT_QE_WORKLOAD_CLASSES),
        "present_workload_classes": sorted(class_values),
        "missing_workload_classes": missing_classes,
        "required_assets": list(STRICT_BUNDLE_REQUIRED_ASSETS),
        "missing_assets": missing_assets,
        "blockers": blockers,
        "claim_boundary": "Step1 strict workload facts only; no hardware speedup or completion claim.",
    }


def candidate_release_policy(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    """Return authoritative release/exploratory policy metadata.

    Legacy release-lane aliases are intentionally ignored for formal Pareto
    admission.  Missing policy metadata fails closed to the exploratory lane.
    """

    policy = candidate.get("release_policy")
    if isinstance(policy, Mapping):
        lane = str(policy.get("lane") or "exploratory").strip().lower()
        formal_allowed = bool(policy.get("formal_pareto_allowed", lane == "release"))
        return {
            "lane": "release" if lane == "release" and formal_allowed else "exploratory",
            "formal_pareto_allowed": lane == "release" and formal_allowed,
            "exploratory_only": not (lane == "release" and formal_allowed),
            "authority": str(policy.get("authority") or "candidate.release_policy"),
            "legacy_candidate_tier_authoritative": False,
        }
    metadata = _as_mapping(candidate.get("policy_metadata"))
    for key in ("release_policy",):
        nested = metadata.get(key)
        if isinstance(nested, Mapping):
            return candidate_release_policy({"release_policy": nested})
    template_policy = _as_mapping(metadata.get("template_policy"))
    nested = template_policy.get("release_policy")
    if isinstance(nested, Mapping):
        return candidate_release_policy({"release_policy": nested})
    if metadata.get("formal_pareto_eligible") is True:
        return {
            "lane": "release",
            "formal_pareto_allowed": True,
            "exploratory_only": False,
            "authority": "policy_metadata.formal_pareto_eligible",
            "legacy_candidate_tier_authoritative": False,
        }
    return {
        "lane": "exploratory",
        "formal_pareto_allowed": False,
        "exploratory_only": True,
        "authority": "default_fail_closed_release_policy",
        "legacy_candidate_tier_authoritative": False,
    }


def candidate_release_lane(candidate: Mapping[str, Any]) -> str:
    return str(candidate_release_policy(candidate).get("lane", "exploratory"))


def formal_pareto_candidates(candidates: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Filter candidate rows for trusted/formal Pareto reporting.

    Exploratory candidates remain visible in ``excluded_candidates`` but cannot
    enter the formal frontier even if they have attractive predicted metrics.
    """

    included: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for raw_candidate in candidates:
        candidate = dict(raw_candidate)
        release_policy = candidate_release_policy(candidate)
        release_lane = str(release_policy.get("lane", "exploratory"))
        eligibility = _as_mapping(candidate.get("claim_eligibility"))
        status = str(candidate.get("status", "")).lower()
        reasons: List[str] = []
        if release_policy.get("formal_pareto_allowed") is not True:
            reasons.append("exploratory_candidate_excluded_from_formal_pareto")
        if eligibility.get("formal_pareto") is False:
            reasons.append("candidate_claim_eligibility_disallows_formal_pareto")
        if status in {"blocked", "untrusted", "predicted_only"}:
            reasons.append(f"candidate_status_{status}_excluded")
        if reasons:
            excluded.append(
                {
                    "candidate_id": str(candidate.get("candidate_id", "unknown_candidate")),
                    "release_lane": release_lane,
                    "release_policy": release_policy,
                    "reasons": reasons,
                    "candidate": candidate,
                }
            )
            continue
        candidate["release_policy"] = release_policy
        candidate["release_lane"] = release_lane
        included.append(candidate)

    def _latency(candidate: Mapping[str, Any]) -> float:
        metrics = _as_mapping(candidate.get("metrics"))
        value = metrics.get("end_to_end_scf_time_s", metrics.get("latency_ms", float("inf")))
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("inf")

    return {
        "schema_version": "dse.dft_scf.formal_pareto_candidates.v1",
        "formal_pareto_candidates": sorted(included, key=_latency),
        "excluded_candidates": excluded,
        "policy": "release_policy.formal_pareto_allowed candidates only; exploratory candidates are visible but excluded from formal Pareto/frontier claims",
    }


def _normalize_evidence_rows(evidence: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    rows = []
    for key in ("evidence_rows", "rows", "tool_transcripts", "artifacts"):
        for row in _as_list(evidence.get(key)):
            if isinstance(row, Mapping):
                rows.append(row)
    for key, value in evidence.items():
        if isinstance(value, bool) and value:
            rows.append({"evidence_class": key, "status": "passed"})
        elif isinstance(value, Mapping):
            status = value.get("status")
            if _non_empty(status):
                rows.append({"evidence_class": key, **dict(value)})
    return rows


def _row_class(row: Mapping[str, Any]) -> str:
    return str(
        row.get("evidence_class")
        or row.get("class")
        or row.get("stage")
        or row.get("tool")
        or row.get("artifact_type")
        or ""
    ).strip().lower()


def _row_status(row: Mapping[str, Any]) -> str:
    return str(row.get("status") or row.get("tool_status") or row.get("result") or "").strip().lower()


def _row_has_vivado_route_completion(row: Mapping[str, Any]) -> bool:
    if _row_class(row) in CLAIM_BRANCH_EVIDENCE_GROUPS["fpga"]:
        return True
    for field in ("implementation_route_completed", "route_design_completed", "route_completed"):
        value = row.get(field)
        if isinstance(value, bool) and value:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "passed", "complete", "completed"}:
            return True
    return False


def adjudicate_hardware_claim_evidence(
    evidence: Mapping[str, Any],
    *,
    claim_type: str,
) -> Dict[str, Any]:
    """Fail-closed evidence gate for FPGA/ASIC candidate acceleration claims."""

    normalized_claim = str(claim_type).strip().lower()
    if normalized_claim not in {"fpga", "asic"}:
        raise ValueError("claim_type must be 'fpga' or 'asic'")

    rows = _normalize_evidence_rows(evidence)
    observed: set[str] = set()
    unavailable_rows: List[Dict[str, Any]] = []
    failed_rows: List[Dict[str, Any]] = []
    for row in rows:
        evidence_class = _row_class(row)
        status = _row_status(row)
        if not evidence_class:
            continue
        if status in UNAVAILABLE_STATUSES or row.get("tool_unavailable") is True:
            unavailable_rows.append(dict(row))
            continue
        if status in {"failed", "error", "timeout"}:
            failed_rows.append(dict(row))
            continue
        if status in {"", "passed", "pass", "ok", "succeeded", "available"}:
            observed.add(evidence_class)
            if evidence_class == "vivado_synth" and _row_has_vivado_route_completion(row):
                observed.add("vivado_implementation")

    blockers: List[Dict[str, Any]] = []
    if unavailable_rows:
        blockers.append(
            {
                "id": "tool_unavailable_blocker_not_pass",
                "reason": "unavailable or failed-to-launch tool logs are blockers, not pass evidence",
                "rows": unavailable_rows,
            }
        )
    if failed_rows:
        blockers.append(
            {
                "id": "failed_tool_log_blocker_not_pass",
                "reason": "failed tool logs are blockers, not pass evidence",
                "rows": failed_rows,
            }
        )

    def _group_present(aliases: Sequence[str]) -> bool:
        return any(alias in observed for alias in aliases)

    for group_id, aliases in CLAIM_BASE_EVIDENCE_GROUPS.items():
        if not _group_present(aliases):
            blockers.append(
                {
                    "id": f"missing_{group_id}",
                    "reason": f"candidate claim requires {group_id} evidence",
                    "accepted_aliases": list(aliases),
                }
            )

    branch_aliases = CLAIM_BRANCH_EVIDENCE_GROUPS[normalized_claim]
    if not _group_present(branch_aliases):
        blockers.append(
            {
                "id": f"missing_{normalized_claim}_branch_evidence",
                "reason": (
                    f"{normalized_claim.upper()} claim requires its branch-specific "
                    "physical evidence; FPGA claims require Vivado implementation-route "
                    "completion, not synth-only evidence"
                ),
                "accepted_aliases": list(branch_aliases),
            }
        )

    has_vivado = _group_present(CLAIM_BRANCH_EVIDENCE_GROUPS["fpga"])
    has_dc = _group_present(CLAIM_BRANCH_EVIDENCE_GROUPS["asic"])
    if normalized_claim == "fpga" and has_dc and not has_vivado:
        blockers.append(
            {
                "id": "dc_only_rejected_for_fpga_claim",
                "reason": "DC-only evidence cannot satisfy an FPGA claim; Vivado implementation-route evidence is required",
            }
        )
    if normalized_claim == "asic" and has_vivado and not has_dc:
        blockers.append(
            {
                "id": "vivado_only_rejected_for_asic_claim",
                "reason": "Vivado-only evidence cannot satisfy an ASIC claim; DC synth/timing/area evidence is required",
            }
        )

    eligible = not blockers
    return {
        "schema_version": "dse.dft_scf.hardware_claim_gate.v1",
        "claim_type": normalized_claim,
        "status": "passed" if eligible else "blocked",
        "claim_eligible": eligible,
        "observed_evidence_classes": sorted(observed),
        "blockers": blockers,
        "blocker_ids": [str(item["id"]) for item in blockers],
        "claim_boundary": (
            "Kernel acceleration claims require golden correctness, sim, synth, "
            "and claim-specific FPGA/ASIC tool evidence. FPGA evidence must "
            "include Vivado implementation-route completion; synth-only rows "
            "remain progress evidence."
        ),
    }


def _finite_nonnegative(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected finite non-negative numeric cost, got {value!r}") from exc
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"expected finite non-negative numeric cost, got {value!r}")
    return parsed


def build_full_scf_hybrid_step5_report(
    *,
    candidate_id: str,
    campaign_id: str,
    workload_run_id: str,
    trial_id: str,
    kernel_speedup: float,
    baseline_scf_time_s: float,
    accelerated_scf_time_s: float,
    host_bound_compute_cost_s: float,
    transfer_cost_s: float,
    synchronization_cost_s: float,
    queueing_cost_s: float,
    layout_cost_s: float,
    cpu_bound_costs_s: Mapping[str, float] | None = None,
    kernel_evidence_levels: Mapping[str, str] | None = None,
    candidate_claim_eligible: bool = False,
) -> Dict[str, Any]:
    """Build a Step5 full-SCF evaluated hybrid report row.

    Kernel speedup is intentionally separated from end-to-end SCF speedup so
    host-bound phases, transfer, synchronization, queueing, and layout overheads
    remain visible.
    """

    baseline = _finite_nonnegative(baseline_scf_time_s)
    accelerated = _finite_nonnegative(accelerated_scf_time_s)
    if baseline == 0.0 or accelerated == 0.0:
        raise ValueError("baseline_scf_time_s and accelerated_scf_time_s must be positive")

    host_cost = _finite_nonnegative(host_bound_compute_cost_s)
    transfer_cost = _finite_nonnegative(transfer_cost_s)
    sync_cost = _finite_nonnegative(synchronization_cost_s)
    queue_cost = _finite_nonnegative(queueing_cost_s)
    layout_cost = _finite_nonnegative(layout_cost_s)
    cpu_costs = {
        "cpu_bound_io_cost_s": _finite_nonnegative((cpu_bound_costs_s or {}).get("io", 0.0)),
        "scf_control_cost_s": _finite_nonnegative((cpu_bound_costs_s or {}).get("scf_control", 0.0)),
        "convergence_cost_s": _finite_nonnegative((cpu_bound_costs_s or {}).get("convergence", 0.0)),
        "diagonalization_cost_s": _finite_nonnegative((cpu_bound_costs_s or {}).get("diagonalization", 0.0)),
        "mixing_cost_s": _finite_nonnegative((cpu_bound_costs_s or {}).get("mixing", 0.0)),
    }
    cost_breakdown = {
        "host_bound_compute_cost_s": host_cost,
        "transfer_cost_s": transfer_cost,
        "synchronization_cost_s": sync_cost,
        "queueing_cost_s": queue_cost,
        "layout_cost_s": layout_cost,
        "synchronization_queueing_layout_cost_s": sync_cost + queue_cost + layout_cost,
        **cpu_costs,
    }
    accounted = sum(cost_breakdown.values()) - cost_breakdown["synchronization_queueing_layout_cost_s"]
    accounted += cost_breakdown["synchronization_queueing_layout_cost_s"]

    return {
        "schema_version": "dse.dft_scf.step5_full_scf_hybrid_report.v1",
        "campaign_id": campaign_id,
        "workload_run_id": workload_run_id,
        "trial_id": trial_id,
        "candidate_id": candidate_id,
        "speedups": {
            "kernel_speedup": float(kernel_speedup),
            "end_to_end_scf_evaluated_speedup": baseline / accelerated,
        },
        "cost_breakdown": cost_breakdown,
        "accounted_cost_s": accounted,
        "baseline_scf_time_s": baseline,
        "accelerated_scf_time_s": accelerated,
        "kernel_evidence_levels": dict(kernel_evidence_levels or {}),
        "candidate_claim_eligibility": {
            "trusted_full_scf_hybrid_claim": bool(candidate_claim_eligible),
            "requires_host_transfer_sync_costs": True,
        },
        "claim_boundary": "Full-SCF hybrid report; kernel speedup is not an end-to-end SCF claim by itself.",
    }


def validate_step5_full_scf_cost_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    required_cost_fields = {
        "host_bound_compute_cost_s",
        "transfer_cost_s",
        "synchronization_cost_s",
        "queueing_cost_s",
        "layout_cost_s",
        "synchronization_queueing_layout_cost_s",
        "cpu_bound_io_cost_s",
        "scf_control_cost_s",
        "convergence_cost_s",
        "diagonalization_cost_s",
        "mixing_cost_s",
    }
    cost_breakdown = _as_mapping(report.get("cost_breakdown"))
    missing = sorted(required_cost_fields - set(cost_breakdown.keys()))
    speedups = _as_mapping(report.get("speedups"))
    if "kernel_speedup" not in speedups:
        missing.append("speedups.kernel_speedup")
    if "end_to_end_scf_evaluated_speedup" not in speedups:
        missing.append("speedups.end_to_end_scf_evaluated_speedup")
    return {
        "schema_version": "dse.dft_scf.step5_cost_report_validation.v1",
        "status": "passed" if not missing else "blocked",
        "passed": not missing,
        "missing_fields": missing,
    }


def validate_artifact_scope_ids(artifact_ref: Mapping[str, Any], *, producer_stage: str) -> Dict[str, Any]:
    required = ["campaign_id"]
    if producer_stage in {"step1", "step2", "step3", "step4", "step5"}:
        required.append("workload_run_id")
    if producer_stage in {"step2", "step3", "step4", "step5"}:
        required.append("trial_id")
    missing = [field for field in required if not _non_empty(artifact_ref.get(field))]
    return {
        "schema_version": "dse.dft_scf.artifact_scope_validation.v1",
        "producer_stage": producer_stage,
        "required_ids": required,
        "missing_ids": missing,
        "passed": not missing,
        "status": "passed" if not missing else "blocked",
    }


def build_wave15_trace(
    *,
    strict_bundle: Mapping[str, Any],
    release_candidate: Mapping[str, Any],
    tool_evidence: Mapping[str, Any],
    claim_type: str = "fpga",
) -> Dict[str, Any]:
    """Build a progress-only Wave 1.5 Step1→Step5 trace payload."""

    bundle_validation = validate_strict_dft_qe_bundle(strict_bundle)
    candidate = deepcopy(dict(release_candidate))
    candidate["release_policy"] = candidate_release_policy(candidate)
    candidate["release_lane"] = candidate_release_lane(candidate)
    candidate_filter = formal_pareto_candidates([candidate])
    claim_gate = adjudicate_hardware_claim_evidence(tool_evidence, claim_type=claim_type)

    campaign_id = str(strict_bundle.get("campaign_id") or candidate.get("campaign_id") or "campaign-wave15")
    workload_run_id = str(strict_bundle.get("workload_run_id") or candidate.get("workload_run_id") or "workload-wave15")
    trial_id = str(candidate.get("trial_id") or "trial-wave15")
    step5_report = build_full_scf_hybrid_step5_report(
        candidate_id=str(candidate.get("candidate_id", "candidate-wave15")),
        campaign_id=campaign_id,
        workload_run_id=workload_run_id,
        trial_id=trial_id,
        kernel_speedup=float(_as_mapping(candidate.get("metrics")).get("kernel_speedup", 1.0)),
        baseline_scf_time_s=float(_as_mapping(candidate.get("metrics")).get("baseline_scf_time_s", 1.0)),
        accelerated_scf_time_s=float(_as_mapping(candidate.get("metrics")).get("accelerated_scf_time_s", 1.0)),
        host_bound_compute_cost_s=float(_as_mapping(candidate.get("costs")).get("host_bound_compute_cost_s", 0.0)),
        transfer_cost_s=float(_as_mapping(candidate.get("costs")).get("transfer_cost_s", 0.0)),
        synchronization_cost_s=float(_as_mapping(candidate.get("costs")).get("synchronization_cost_s", 0.0)),
        queueing_cost_s=float(_as_mapping(candidate.get("costs")).get("queueing_cost_s", 0.0)),
        layout_cost_s=float(_as_mapping(candidate.get("costs")).get("layout_cost_s", 0.0)),
        cpu_bound_costs_s=_as_mapping(candidate.get("cpu_bound_costs_s")),
        kernel_evidence_levels={str(claim_type): claim_gate["status"]},
        candidate_claim_eligible=False,
    )
    cost_validation = validate_step5_full_scf_cost_report(step5_report)

    trace_passed = (
        bool(bundle_validation["admitted"])
        and bool(candidate_filter["formal_pareto_candidates"])
        and claim_gate["status"] == "passed"
        and cost_validation["passed"]
    )
    return {
        "schema_version": "dse.dft_scf.wave15_trace.v1",
        "status": "progress_only" if trace_passed else "blocked_progress_only",
        "progress_only": True,
        "completion_claim": False,
        "mvp_claim": False,
        "campaign_id": campaign_id,
        "workload_run_id": workload_run_id,
        "trial_id": trial_id,
        "artifact_chain": [
            {
                "step": "step1",
                "artifact": "strict_workload_bundle",
                "status": bundle_validation["status"],
            },
            {
                "step": "step2",
                "artifact": "release_lane_candidate",
                "status": "passed" if candidate_filter["formal_pareto_candidates"] else "blocked",
            },
            {
                "step": "step3",
                "artifact": "tool_transcript_or_blocker",
                "status": claim_gate["status"],
                "blocker_ids": claim_gate["blocker_ids"],
            },
            {
                "step": "step4",
                "artifact": "adjudication",
                "status": "adjudicated_progress_only",
                "claim_eligible": claim_gate["claim_eligible"],
            },
            {
                "step": "step5",
                "artifact": "full_scf_hybrid_report",
                "status": cost_validation["status"],
            },
        ],
        "bundle_validation": bundle_validation,
        "candidate_filter": candidate_filter,
        "claim_gate": claim_gate,
        "step5_report": step5_report,
        "forbidden_completion_labels_absent": True,
        "claim_boundary": "Wave 1.5 is a progress-only thin trace and must not be reported as MVP, vertical-slice completion, or final closure.",
    }
