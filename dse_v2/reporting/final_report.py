#!/usr/bin/env python3
"""Final report and claim-validation utilities for generic DSE evidence runs.

The reporting layer is intentionally conservative: SystemC/gem5+SystemC
simulation evidence may enter trusted sections, while predicted-only,
analytical/TLM, unavailable, or blocked claims remain visible but cannot become
trusted winners.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from dse_v2.reference_workloads.dft_candidate_set_consistency import (
    validate_dft_candidate_set_consistency,
)
from dse_v2.reference_workloads.dft_architecture_winner_resolution import (
    validate_dft_architecture_winner_resolution,
)
from dse_v2.reference_workloads.dft_candidate_specific_ppa_provenance import (
    validate_dft_candidate_specific_ppa_provenance_audit,
)
from dse_v2.reference_workloads.dft_full_scf_hybrid import (
    MAJOR_SCF_ACCELERATED_KERNEL_IDS,
    REQUIRED_HOST_BOUND_PHASE_IDS,
    REQUIRED_OVERHEAD_PHASE_IDS,
)
from dse_v2.reference_workloads.dft_full_scf_numerical_closure import (
    build_full_scf_numerical_readiness_sections,
)
from dse_v2.reference_workloads.dft_full_scf_targeted_accounting import (
    summarize_full_scf_targeted_deployment_accounting,
)
from dse_v2.reference_workloads.dft_hardware_ppa_ranking import (
    validate_dft_hardware_ppa_ranking,
)
from dse_v2.reporting.complete_dse_claims import (
    build_requirement_evidence_audit_matrix,
    render_requirement_evidence_audit_markdown,
)

TRUSTED_BACKENDS = {"systemc", "gem5_systemc"}
PREDICTED_FIDELITIES = {"l1", "l2", "analytical", "tlm", "surrogate", "predicted"}
LOW_FIDELITY_ARTIFACT_KEYS = {
    "l1_evaluation_result": "l1_evaluation_result.json",
    "l1_promotion_decision": "l1_promotion_decision.json",
    "l2_evaluation_result": "l2_evaluation_result.json",
    "l2_promotion_decision": "l2_promotion_decision.json",
    "low_fidelity_summary": "low_fidelity_screening_summary.json",
}
LOW_FIDELITY_ARTIFACT_PATHS = list(LOW_FIDELITY_ARTIFACT_KEYS.values())
STEP2_SEARCH_PROVENANCE_ARTIFACT_KEYS = {
    "architecture_search_space": "architecture_search_space.json",
    "architecture_candidate_generation_report": "architecture_candidate_generation_report.json",
    "architecture_screening_report": "architecture_screening_report.json",
    "search_checkpoint": "search_checkpoint.json",
    "top_k_candidate_queue": "top_k_candidate_queue.json",
    "trial_state_ledger": "trial_state_ledger.json",
    "step3_simulation_queue": "step3_simulation_queue.json",
}
EVIDENCE_ALIASES = {
    "simulator_consistency_check.json": ["numerical_validation.json"],
}
DFT_LEDGER_ARTIFACT_NAMES = {
    "per_candidate_evidence_ledger.json",
    "release_report.json",
    "claim_validation_report.json",
    "blocker_report.json",
    "prompt_to_artifact_checklist.json",
    "eda_all_candidate_evidence.json",
}
DFT_HARDWARE_EVIDENCE_MATRIX_ARTIFACT_NAMES = {
    "dft_hardware_evidence_matrix.json",
}
DFT_FULL_SCF_HYBRID_ARTIFACT_NAMES = {
    "full_scf_accelerator_descriptor.json",
    "full_scf_runtime_schedule.json",
    "full_scf_data_residency_plan.json",
    "full_scf_correctness_report.json",
    "full_scf_ppa_summary.json",
}
QE_BASELINE_ROW_ACCOUNTING_ATTACHMENT_ARTIFACT_NAMES = {
    "qe_baseline_comparison_index.json",
    "full_scf_row_accounting.json",
}
DFT_TRIAL_LEDGER_ARTIFACT_NAMES = {
    "dft_trial_state_ledger.json",
    "dft_trial_transition_report.json",
    "dft_trial_artifact_refs.json",
    "dft_trial_state_ledger_validation.json",
}
DFT_CANDIDATE_BINDING_ARTIFACT_NAMES = {
    "dft_candidate_binding_map.json",
    "dft_candidate_binding_map_validation.json",
    "dft_candidate_binding_map_status.json",
}
DFT_HARDWARE_COMPLETION_WORKPLAN_ARTIFACT_NAMES = {
    "dft_hardware_completion_workplan.json",
    "dft_hardware_completion_workplan_validation.json",
    "dft_hardware_completion_workplan_status.json",
}
DFT_HARDWARE_CLOSURE_SHARD_ARTIFACT_NAMES = {
    "dft_hardware_closure_shards.json",
    "dft_hardware_closure_shards_validation.json",
    "dft_hardware_closure_shards_status.json",
}
DFT_HARDWARE_CLOSURE_PACKET_ARTIFACT_NAMES = {
    "dft_hardware_closure_packet_index.json",
    "dft_hardware_closure_packet_index_validation.json",
    "dft_hardware_closure_packet_index_status.json",
}
DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_ARTIFACT_NAMES = {
    "dft_hardware_closure_candidate_bundle_index.json",
    "dft_hardware_closure_candidate_bundle_index_validation.json",
    "dft_hardware_closure_candidate_bundle_status.json",
}
DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_ARTIFACT_NAMES = {
    "dft_hardware_closure_unit_provenance_index.json",
    "dft_hardware_closure_unit_provenance_validation.json",
    "dft_hardware_closure_unit_provenance_status.json",
}
DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_ARTIFACT_NAMES = {
    "dft_hardware_closure_source_flow_plan.json",
    "dft_hardware_closure_source_flow_plan_validation.json",
    "dft_hardware_closure_source_flow_plan_status.json",
}
DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_ARTIFACT_NAMES = {
    "dft_hardware_closure_raw_stage_materialization.json",
    "dft_hardware_closure_raw_stage_materialization_validation.json",
    "dft_hardware_closure_raw_stage_materialization_status.json",
}
DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_ARTIFACT_NAMES = {
    "dft_hardware_closure_raw_transcript_registration.json",
    "dft_hardware_closure_raw_transcript_registration_validation.json",
    "dft_hardware_closure_raw_transcript_registration_status.json",
}
DFT_HARDWARE_CLOSURE_EVIDENCE_INTAKE_ARTIFACT_NAMES = {
    "dft_hardware_closure_evidence_intake.json",
    "dft_hardware_closure_evidence_intake_validation.json",
    "dft_hardware_closure_evidence_intake_status.json",
}
DFT_HARDWARE_CLOSURE_ADJUDICATION_ARTIFACT_NAMES = {
    "dft_hardware_closure_adjudication.json",
    "dft_hardware_closure_adjudication_validation.json",
    "dft_hardware_closure_adjudication_status.json",
}
DFT_HARDWARE_CLOSURE_PARSED_EVIDENCE_ARTIFACT_NAMES = {
    "dft_hardware_closure_parsed_evidence_manifest.json",
    "dft_hardware_closure_parsed_evidence_manifest_validation.json",
    "dft_hardware_closure_parsed_evidence_manifest_status.json",
}
DFT_HARDWARE_CLOSURE_PARSER_RUN_ARTIFACT_NAMES = {
    "dft_hardware_closure_parser_run.json",
    "dft_hardware_closure_parser_run_validation.json",
    "dft_hardware_closure_parser_run_status.json",
}
DFT_HARDWARE_CLOSURE_GATE_ADJUDICATION_ARTIFACT_NAMES = {
    "dft_hardware_closure_gate_adjudication.json",
    "dft_hardware_closure_gate_adjudication_validation.json",
    "dft_hardware_closure_gate_adjudication_status.json",
}
DFT_HARDWARE_CLOSURE_RELEASE_GATE_ARTIFACT_NAMES = {
    "dft_hardware_closure_release_gate.json",
    "dft_hardware_closure_release_gate_validation.json",
    "dft_hardware_closure_release_gate_status.json",
}
DFT_HARDWARE_PPA_RANKING_ARTIFACT_NAMES = {
    "dft_hardware_ppa_ranking.json",
    "dft_hardware_ppa_pareto_frontier.json",
    "dft_hardware_ppa_ranking_validation.json",
    "dft_hardware_ppa_ranking_status.json",
}
DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_ARTIFACT_NAMES = {
    "dft_candidate_specific_ppa_execution.json",
    "dft_candidate_specific_ppa_execution_validation.json",
    "dft_candidate_specific_ppa_execution_status.json",
    "dft_candidate_specific_ppa_provenance_audit.json",
    "dft_candidate_specific_ppa_provenance_audit_validation.json",
    "dft_candidate_specific_ppa_provenance_audit_status.json",
    "dft_hardware_tie_breaker_execution_queue.json",
    "dft_hardware_tie_breaker_execution_queue_validation.json",
}
DFT_DEPLOYMENT_HARD_GATE_EXECUTION_QUEUE_ARTIFACT_NAMES = {
    "dft_deployment_hard_gate_execution_queue.json",
    "dft_deployment_hard_gate_execution_queue_validation.json",
    "dft_deployment_hard_gate_execution_queue_status.json",
    "dft_deployment_hard_gate_execution_queue_candidate_bundles.json",
    "dft_deployment_target_model_binding.json",
    "dft_deployment_target_model_binding_validation.json",
}
DFT_ARCHITECTURE_WINNER_RESOLUTION_ARTIFACT_NAMES = {
    "dft_architecture_winner_resolution.json",
    "dft_architecture_winner_resolution_validation.json",
    "dft_architecture_winner_resolution_status.json",
}
DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_ARTIFACT_NAMES = {
    "dft_hardware_deployment_recommendation_readiness.json",
    "dft_hardware_deployment_recommendation_readiness_validation.json",
    "dft_hardware_deployment_recommendation_readiness_status.json",
    "dft_full_scf_targeted_deployment_accounting.json",
    "dft_full_scf_targeted_deployment_accounting_validation.json",
    "dft_full_scf_targeted_deployment_accounting_status.json",
}
DFT_HARDWARE_DEPLOYMENT_DECISION_PACKET_ARTIFACT_NAMES = {
    "dft_hardware_deployment_decision_packet.json",
    "dft_hardware_deployment_decision_packet_validation.json",
    "dft_hardware_deployment_decision_packet_status.json",
}
DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_ARTIFACT_NAMES = {
    "dft_hardware_deployment_target_selection.json",
}
DFT_FULL_SCF_NUMERICAL_CLOSURE_ARTIFACT_NAMES = {
    "full_scf_end_to_end_comparison.json",
    "full_scf_end_to_end_comparison_validation.json",
    "full_scf_end_to_end_comparison_status.json",
    "full_scf_end_to_end_comparison.recheck.json",
    "full_scf_end_to_end_comparison.recheck_validation.json",
    "full_scf_end_to_end_comparison.recheck_status.json",
    "qe_accelerated_numeric_evidence_requirements.json",
    "qe_accelerated_numeric_evidence_requirements_validation.json",
    "qe_accelerated_numeric_evidence_requirements_status.json",
    "dft_scf_six_class_qe_baseline_materialization.json",
    "dft_scf_six_class_qe_baseline_materialization_validation.json",
    "dft_scf_six_class_qe_baseline_materialization_status.json",
    "full_scf_trusted_evidence_execution_queue.json",
    "full_scf_trusted_evidence_execution_queue_validation.json",
    "full_scf_trusted_evidence_execution_queue_status.json",
    "full_scf_trusted_evidence_batch_plan.json",
    "full_scf_trusted_evidence_batch_plan_validation.json",
    "full_scf_trusted_evidence_batch_plan_status.json",
    "numerical_correctness_evidence.json",
}
DFT_FULL_SCF_NUMERICAL_CLOSURE_AUX_ARTIFACT_NAMES = {
    "run_full_scf_trusted_evidence_batches.sh",
}
DFT_DEPLOYMENT_DECISION_SUPPORT_ARTIFACT_NAMES = {
    "dft_fpga_asic_deployment_summary.json",
    "dft_fpga_asic_deployment_summary_validation.json",
    "dft_fpga_asic_deployment_summary_status.json",
    "dft_deployment_target_feasibility.json",
    "dft_deployment_target_feasibility_validation.json",
    "dft_deployment_target_feasibility_status.json",
    "dft_deployment_coordination_summary.json",
    "dft_deployment_coordination_summary_validation.json",
    "dft_deployment_coordination_summary_status.json",
    "full_scf_end_to_end_comparison.json",
    "full_scf_end_to_end_comparison_validation.json",
    "full_scf_end_to_end_comparison_status.json",
    "full_scf_end_to_end_comparison.recheck.json",
    "full_scf_end_to_end_comparison.recheck_validation.json",
    "full_scf_end_to_end_comparison.recheck_status.json",
    "numerical_correctness_evidence.json",
    "dft_candidate_set_consistency.json",
    "dft_candidate_set_consistency_validation.json",
    "dft_candidate_set_consistency_status.json",
    "dft_scf_hardware_goal_completion_audit_current.json",
    "dft_scf_hardware_dse_goal_audit_current.json",
    "status.json",
    "blocker_report.json",
}
DFT_DEPLOYMENT_COMPARATOR_ARTIFACT_NAMES = {
    "dft_deployment_comparator.json",
    "dft_deployment_comparator_validation.json",
    "dft_deployment_comparator_status.json",
}
DFT_DEPLOYMENT_SELECTOR_ARTIFACT_NAMES = {
    "dft_deployment_selector.json",
    "dft_deployment_selector_validation.json",
    "dft_deployment_selector_status.json",
}
DFT_DEPLOYMENT_DECISION_SUMMARY_ARTIFACT_NAMES = {
    "dft_deployment_decision_summary.json",
    "dft_deployment_decision_summary_validation.json",
    "dft_deployment_decision_summary_status.json",
}
DFT_L4_GOAL_BINDING_ARTIFACT_NAMES = {
    "dft_l4_current_candidate_queue.json",
    "dft_l4_goal_binding.json",
    "dft_l4_goal_binding_validation.json",
    "dft_l4_goal_binding_status.json",
}
DFT_AUDIT_SEMANTIC_CLOSURE_ARTIFACT_NAMES = {
    "dft_audit_semantic_closure.json",
}
CONTROL_PLANE_VALIDATION_ARTIFACT_NAMES = {
    "campaign_evaluation_plan.json",
    "search_iteration_plan.json",
    "search_iteration_plan_validation.json",
    "campaign_search_admission_plan.json",
    "step3_admission_queue_validation.json",
}
CONTROL_PLANE_STEP3_QUEUE_ARTIFACT_NAME = "step3_simulation_queue.json"
CONTROL_PLANE_STEP3_QUEUE_DEFAULT_REFS = (
    "step2/step3_simulation_queue.json",
    "step2_input/step3_simulation_queue.json",
    "step3_simulation_queue.json",
)
CONTROL_PLANE_SCOPE_FIELDS = ("campaign_id", "workload_run_id", "trial_id")

CLAIM_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "best_architecture": {
        "description": "A final architecture winner/recommendation.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": [
            "verdict.json",
            "workload_package.json",
            "graph_lowering_report.json",
            "simulation_result.json",
            "architecture.json",
            "mapping.json",
            "phase_breakdown.csv",
        ],
        "notes": [
            "Must be backed by SystemC or gem5+SystemC evidence.",
            "Predicted-only, blocked, untrusted, or analytical/TLM claims cannot be winners.",
            "A single pilot may prove feasibility but should not overclaim a cross-candidate best architecture.",
        ],
    },
    "mapping_comparison": {
        "description": "A comparison between mappings or architecture/mapping pairs.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["workload_package.json", "graph_lowering_report.json", "simulation_result.json", "mapping.json", "phase_breakdown.csv", "mapping_simulation_samples.json"],
        "notes": ["Every compared entry must resolve to trusted evidence."],
    },
    "bottleneck": {
        "description": "A timing/resource bottleneck diagnosis.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["workload_package.json", "graph_lowering_report.json", "simulation_result.json", "phase_breakdown.csv", "resource_summary.csv"],
        "notes": ["Phase/resource tables must be cited for trusted bottleneck claims."],
    },
    "feasibility": {
        "description": "A feasibility statement for a specific design point/run.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json"],
        "notes": ["Feasibility is scoped to the cited design/run, not a global DSE winner."],
    },
    "pareto_frontier": {
        "description": "A trusted Pareto-frontier claim.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json", "claim_validation.json", "mapping_simulation_samples.json", "mapping_feedback_state.json"],
        "notes": ["Every Pareto member must be SystemC/gem5+SystemC-backed."],
    },
    "convergence": {
        "description": "A search convergence/budget claim.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json", "mapping_simulation_samples.json", "mapping_feedback_state.json", "convergence_status.json"],
        "notes": ["Budget exhaustion must be explicit when convergence is not proven."],
    },
    "debug_replay": {
        "description": "Replay/debug reproducibility claim.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["manifest.json", "artifact_manifest.json"],
        "notes": ["Replay commands and artifact locations must resolve."],
    },
    "numerical_correctness": {
        "description": "Numerical equivalence/correctness claim.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulator_consistency_check.json"],
        "notes": [
            "Timing-level shell evidence is insufficient unless explicit numerical checks are cited.",
            "The generic SystemC timing numeric reference does not prove profile-domain correctness.",
        ],
    },
    "microarchitecture_timing_consistency": {
        "description": "Internal consistency of a gem5 GenericAccel microarchitecture timing result.",
        "trusted_backends": ["gem5_systemc"],
        "required_evidence": [
            "verdict.json",
            "workload_package.json",
            "graph_lowering_report.json",
            "simulation_result.json",
            "simulator_consistency_check.json",
            "gem5_l4_proof.json",
        ],
        "notes": [
            "This is not a profile-domain numerical correctness claim.",
            "It requires the L4 descriptor/decode/microarchitecture/completion proof to pass.",
        ],
    },
        "software_visible_codesign": {
        "description": "A gem5+SystemC software-visible co-design claim for one candidate.",
        "trusted_backends": ["gem5_systemc"],
        "required_evidence": [
            "verdict.json",
            "codesign_candidate.json",
            "codesign_verdict.json",
            "l4_execution_trace.json",
            "completion_proof.json",
            "gem5_l4_proof.json",
        ],
        "notes": [
            "Requires guest descriptor submission, GenericAccel request consumption, in-gem5 microarchitecture execution, and guest-visible completion.",
            "Blocked L4 evidence is reportable as a limitation only.",
        ],
    },
    "low_fidelity_screening": {
        "description": "A Step2 L1/L2 candidate-screening signal.",
        "trusted_backends": [],
        "required_evidence": LOW_FIDELITY_ARTIFACT_PATHS,
        "notes": [
            "L1 analytical and L2 TLM screening are candidate-generation and promotion-gate signals only.",
            "They are visible in final reports but excluded from trusted ranking and winner selection.",
        ],
    },
    "unsupported_stub_limitation": {
        "description": "A limitation/blocker/untrusted-path boundary statement.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json"],
        "notes": ["Blocked or untrusted path claims are reportable limitations, never trusted winners."],
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _valid_ic_eda_transcript_ref(ref: Any) -> bool:
    if not isinstance(ref, Mapping):
        return False
    path = str(ref.get("path") or "").strip()
    digest = str(ref.get("sha256") or "").strip()
    return bool(
        path
        and digest
        and len(digest) == 64
        and all(char in "0123456789abcdef" for char in digest.lower())
        and ref.get("hash_algorithm") == "sha256"
        and ref.get("artifact_role") == "raw_command_transcript_only_not_kernel_ppa"
        and ref.get("kernel_ppa_evidence") is not True
        and ref.get("hardware_completion_eligible") is not True
        and ref.get("deliverable_complete") is not True
    )


def build_evidence_index(
    run_dir: Path,
    artifact_paths: Optional[Iterable[str]] = None,
    *,
    generated_in_current_pass: Optional[Iterable[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Return an evidence index keyed by relative artifact path."""
    run_dir = Path(run_dir)
    generated_paths = {str(path) for path in (generated_in_current_pass or [])}
    if artifact_paths is None:
        paths: List[str] = []
        artifact_manifest = _load_json(run_dir / "artifact_manifest.json")
        for entry in artifact_manifest.get("artifacts", []) or []:
            rel = entry.get("path")
            if rel:
                paths.append(str(rel))
        if not paths:
            paths = [
                "manifest.json",
                "artifact_manifest.json",
                "verdict.json",
                "design_point.json",
                "architecture.json",
                "mapping.json",
                "workload_package.json",
                "workload_graph.json",
                "graph_lowering_report.json",
                "simulation_request.json",
                "simulation_result.json",
                "simulator_consistency_check.json",
                "numerical_validation.json",
                "phase_breakdown.csv",
                "resource_summary.csv",
                "data_movement_summary.csv",
                "systemc_stdout.log",
                "systemc_stderr.log",
                "gem5_systemc_blockers.json",
            ]
    else:
        paths = [str(path) for path in artifact_paths]
    paths.extend(LOW_FIDELITY_ARTIFACT_PATHS)
    paths.extend(f"dft_ledger/{name}" for name in DFT_LEDGER_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_EVIDENCE_MATRIX_ARTIFACT_NAMES)
    paths.extend(DFT_FULL_SCF_HYBRID_ARTIFACT_NAMES)
    paths.extend(QE_BASELINE_ROW_ACCOUNTING_ATTACHMENT_ARTIFACT_NAMES)
    paths.extend(
        f"dft_full_scf_evaluated_hybrid/{name}"
        for name in DFT_FULL_SCF_HYBRID_ARTIFACT_NAMES
    )
    paths.extend(
        f"dft_full_scf_evaluated_hybrid/{name}"
        for name in QE_BASELINE_ROW_ACCOUNTING_ATTACHMENT_ARTIFACT_NAMES
    )
    paths.extend(DFT_TRIAL_LEDGER_ARTIFACT_NAMES)
    paths.extend(DFT_CANDIDATE_BINDING_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_COMPLETION_WORKPLAN_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_CLOSURE_SHARD_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_CLOSURE_PACKET_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_CLOSURE_EVIDENCE_INTAKE_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_CLOSURE_ADJUDICATION_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_CLOSURE_PARSED_EVIDENCE_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_CLOSURE_PARSER_RUN_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_CLOSURE_GATE_ADJUDICATION_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_CLOSURE_RELEASE_GATE_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_PPA_RANKING_ARTIFACT_NAMES)
    paths.extend(DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_ARTIFACT_NAMES)
    paths.extend(DFT_DEPLOYMENT_HARD_GATE_EXECUTION_QUEUE_ARTIFACT_NAMES)
    paths.extend(DFT_ARCHITECTURE_WINNER_RESOLUTION_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_DEPLOYMENT_DECISION_PACKET_ARTIFACT_NAMES)
    paths.extend(DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_ARTIFACT_NAMES)
    paths.extend(DFT_FULL_SCF_NUMERICAL_CLOSURE_ARTIFACT_NAMES)
    paths.extend(DFT_FULL_SCF_NUMERICAL_CLOSURE_AUX_ARTIFACT_NAMES)
    paths.extend(DFT_DEPLOYMENT_DECISION_SUPPORT_ARTIFACT_NAMES)
    paths.extend(DFT_DEPLOYMENT_COMPARATOR_ARTIFACT_NAMES)
    paths.extend(DFT_DEPLOYMENT_SELECTOR_ARTIFACT_NAMES)
    paths.extend(DFT_DEPLOYMENT_DECISION_SUMMARY_ARTIFACT_NAMES)
    paths.extend(DFT_L4_GOAL_BINDING_ARTIFACT_NAMES)
    paths.extend(DFT_AUDIT_SEMANTIC_CLOSURE_ARTIFACT_NAMES)
    paths.extend(CONTROL_PLANE_VALIDATION_ARTIFACT_NAMES)
    paths.extend(CONTROL_PLANE_STEP3_QUEUE_DEFAULT_REFS)

    index: Dict[str, Dict[str, Any]] = {}
    for rel in sorted(set(paths)):
        path = run_dir / rel
        entry: Dict[str, Any] = {
            "path": rel,
            "exists": path.exists(),
        }
        if path.exists() and path.is_file():
            entry.update({
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            })
        elif rel in generated_paths:
            entry.update({
                "exists": True,
                "generated_in_current_report_pass": True,
                "hash_unavailable_reason": "artifact is generated as part of the current report/evidence pass",
            })
        else:
            entry["unavailable_reason"] = "artifact not present in run directory"
        index[rel] = entry
    return index


def evidence_requirement_table() -> List[Dict[str, Any]]:
    """Machine-readable claim classes and evidence requirements."""
    rows: List[Dict[str, Any]] = []
    for claim_type, requirement in CLAIM_REQUIREMENTS.items():
        rows.append({
            "claim_type": claim_type,
            "description": requirement["description"],
            "trusted_backends": requirement["trusted_backends"],
            "required_evidence": requirement["required_evidence"],
            "notes": requirement["notes"],
        })
    return rows


def _claim_backend(claim: Mapping[str, Any]) -> str:
    return str(claim.get("backend", claim.get("source_backend", ""))).lower()


def _claim_fidelity(claim: Mapping[str, Any]) -> str:
    return str(claim.get("fidelity", claim.get("source_fidelity", ""))).lower()


def _claim_evidence_ids(claim: Mapping[str, Any]) -> List[str]:
    evidence_ids = claim.get("evidence_ids", [])
    if isinstance(evidence_ids, str):
        return [evidence_ids]
    if isinstance(evidence_ids, Sequence):
        return [str(item) for item in evidence_ids]
    return []


def _with_gem5_l4_proof_evidence(
    evidence_ids: Iterable[str],
    *,
    backend: str,
    trusted: bool,
    proof_passed: bool,
) -> List[str]:
    ids = list(dict.fromkeys(str(item) for item in evidence_ids))
    if backend == "gem5_systemc" and trusted and proof_passed and "gem5_l4_proof.json" not in ids:
        ids.append("gem5_l4_proof.json")
    return ids


def _evidence_requirement_present(
    required_id: str,
    evidence_ids: Sequence[str],
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> bool:
    candidates = [required_id] + list(EVIDENCE_ALIASES.get(required_id, []))
    return any(candidate in evidence_ids and evidence_index.get(candidate, {}).get("exists", False) for candidate in candidates)


def _verdict_allows_trust(verdict: Mapping[str, Any]) -> bool:
    return bool(verdict.get("trusted_for_final_ranking", False))


def validate_claim(
    claim: Mapping[str, Any],
    *,
    verdict: Mapping[str, Any],
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Validate a single final-report claim against evidence and status rules."""
    claim_type = str(claim.get("claim_type", "unknown"))
    backend = _claim_backend(claim)
    fidelity = _claim_fidelity(claim)
    evidence_ids = _claim_evidence_ids(claim)
    requirement = CLAIM_REQUIREMENTS.get(claim_type, {})
    required_evidence = [str(x) for x in requirement.get("required_evidence", [])]

    missing_evidence = [
        evidence_id
        for evidence_id in evidence_ids
        if not evidence_index.get(evidence_id, {}).get("exists", False)
    ]
    missing_required = [
        evidence_id
        for evidence_id in required_evidence
        if not _evidence_requirement_present(evidence_id, evidence_ids, evidence_index)
    ]

    reasons: List[str] = []
    status = str(claim.get("status", claim.get("lifecycle_state", ""))).lower()
    if status in {"blocked", "unsupported", "stub", "untrusted"}:
        reasons.append(f"claim status is {status}")
    if bool(claim.get("predicted_only", False)):
        reasons.append("claim is predicted_only")
    if fidelity in PREDICTED_FIDELITIES:
        reasons.append(f"source fidelity {fidelity} is not final-ranking evidence")
    if backend not in TRUSTED_BACKENDS:
        reasons.append(f"backend {backend or '<missing>'} is not trusted for final ranking")
    if not evidence_ids:
        reasons.append("claim has no evidence_ids")
    if missing_evidence:
        reasons.append(f"unresolved evidence ids: {', '.join(missing_evidence)}")
    if missing_required:
        reasons.append(f"required evidence ids absent or unresolved: {', '.join(missing_required)}")
    if not _verdict_allows_trust(verdict) and claim_type != "unsupported_stub_limitation":
        reasons.append("run verdict is not trusted_for_final_ranking")
    if claim_type == "convergence" and not bool(claim.get("converged", False)):
        reasons.append("convergence criterion is not satisfied; budget exhaustion or incomplete search is a limitation")
    if claim_type in {"mapping_comparison", "pareto_frontier"}:
        trusted_sample_count = int(claim.get("trusted_sample_count", 0) or 0)
        if trusted_sample_count < 2:
            reasons.append("comparative claim requires at least two trusted high-fidelity samples")
    if backend == "gem5_systemc" and claim_type != "unsupported_stub_limitation" and status not in {"blocked", "unsupported", "stub", "untrusted"}:
        if not bool(verdict.get("gem5_l4_proof_passed", False)):
            reasons.append("gem5_systemc trusted claim requires passing gem5_l4_proof.json")
        if "gem5_l4_proof.json" not in evidence_ids or not evidence_index.get("gem5_l4_proof.json", {}).get("exists", False):
            reasons.append("gem5_systemc trusted claim must directly cite gem5_l4_proof.json")

    trusted = not reasons and claim_type != "unsupported_stub_limitation"
    validation_status = "trusted" if trusted else "untrusted"
    if bool(claim.get("predicted_only", False)) or fidelity in PREDICTED_FIDELITIES:
        validation_status = "predicted_only"
    elif status in {"blocked", "unsupported", "stub", "untrusted"} or claim_type == "unsupported_stub_limitation":
        validation_status = "blocked_or_limitation"

    return {
        "claim_id": str(claim.get("claim_id", claim_type)),
        "claim_type": claim_type,
        "backend": backend,
        "source_fidelity": fidelity,
        "trusted": trusted,
        "validation_status": validation_status,
        "evidence_ids": evidence_ids,
        "missing_evidence": missing_evidence,
        "reasons": reasons,
    }


def validate_claims(
    claims: Iterable[Mapping[str, Any]],
    *,
    verdict: Mapping[str, Any],
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    validations = [validate_claim(claim, verdict=verdict, evidence_index=evidence_index) for claim in claims]
    trusted_claim_ids = [item["claim_id"] for item in validations if item["trusted"]]
    blocked_or_predicted = [
        item["claim_id"]
        for item in validations
        if item["validation_status"] in {"blocked_or_limitation", "predicted_only"}
    ]
    errors = [
        f"{item['claim_id']}: {'; '.join(item['reasons'])}"
        for item in validations
        if not item["trusted"] and item["validation_status"] not in {"blocked_or_limitation", "predicted_only"}
    ]
    return {
        "schema_version": "dse.claim_validation.v1",
        "generated_at": _now_iso(),
        "trusted_claim_ids": trusted_claim_ids,
        "blocked_or_predicted_claim_ids": blocked_or_predicted,
        "validations": validations,
        "errors": errors,
        "warnings": [],
        "passed": not errors,
    }


def _read_csv_rows(path: Path, limit: int = 1000) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows: List[Dict[str, str]] = []
        for idx, row in enumerate(reader):
            if idx >= limit:
                break
            rows.append(dict(row))
        return rows


def _default_claims(
    *,
    verdict: Mapping[str, Any],
    simulation_result: Mapping[str, Any],
    convergence_status: Optional[Mapping[str, Any]] = None,
    simulation_samples: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    backend = str(verdict.get("backend", simulation_result.get("backend", "systemc")))
    fidelity = "L4" if backend == "gem5_systemc" else "L3"
    trusted = bool(verdict.get("trusted_for_final_ranking", False))
    gem5_l4_proof_passed = bool(verdict.get("gem5_l4_proof_passed", False))
    run_id = str(verdict.get("run_id", simulation_result.get("run_id", "unknown")))

    claims: List[Dict[str, Any]] = [
        {
            "claim_id": "feasibility_current_design",
            "claim_type": "feasibility",
            "statement": "The cited design point completed the selected full workload timing-level run." if trusted else "The cited design point is not trusted for final ranking.",
            "backend": backend,
            "source_fidelity": fidelity,
            "predicted_only": False,
            "status": "simulated" if trusted else "blocked",
            "design_point_id": run_id,
            "evidence_ids": _with_gem5_l4_proof_evidence(
                ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json", "phase_breakdown.csv"],
                backend=backend,
                trusted=trusted,
                proof_passed=gem5_l4_proof_passed,
            ),
        }
    ]

    if trusted or simulation_result.get("phase_results"):
        claims.append({
            "claim_id": "phase_timing_breakdown",
            "claim_type": "bottleneck",
            "statement": "Phase timing/resource bottleneck analysis is available for the cited run.",
            "backend": backend,
            "source_fidelity": fidelity,
            "predicted_only": False,
            "status": "simulated" if trusted else "blocked",
            "design_point_id": run_id,
            "evidence_ids": _with_gem5_l4_proof_evidence(
                ["workload_package.json", "graph_lowering_report.json", "simulation_result.json", "phase_breakdown.csv", "resource_summary.csv"],
                backend=backend,
                trusted=trusted,
                proof_passed=gem5_l4_proof_passed,
            ),
        })

    numerical_validation = (
        simulation_result.get("simulator_consistency_check", {})
        if simulation_result.get("simulator_consistency_check") and isinstance(simulation_result.get("simulator_consistency_check", {}), Mapping)
        else simulation_result.get("numerical_validation", {})
        if isinstance(simulation_result.get("numerical_validation", {}), Mapping)
        else {}
    )
    if numerical_validation.get("passed") is True:
        consistency_artifact = str(numerical_validation.get("artifact") or "simulator_consistency_check.json")
        validation_scope = str(numerical_validation.get("scope", ""))
        if validation_scope == "gem5_microarchitecture_timing_internal_consistency":
            claim_id = "gem5_microarchitecture_timing_consistency"
            claim_type = "microarchitecture_timing_consistency"
            statement = (
                "gem5 GenericAccel microarchitecture timing/resource outputs passed internal "
                "coverage, ordering, and conservation checks; profile-domain correctness is outside this claim."
            )
        else:
            claim_id = "generic_systemc_numeric_reference"
            claim_type = "numerical_correctness"
            statement = (
                "Generic SystemC timing numeric outputs match the independent Python reference model "
                "within declared tolerances; profile-domain correctness is outside this claim."
            )
        claims.append({
            "claim_id": claim_id,
            "claim_type": claim_type,
            "statement": statement,
            "backend": backend,
            "source_fidelity": fidelity,
            "predicted_only": False,
            "status": "simulated" if trusted else "blocked",
            "design_point_id": run_id,
            "evidence_ids": _with_gem5_l4_proof_evidence(
                ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json", consistency_artifact],
                backend=backend,
                trusted=trusted,
                proof_passed=gem5_l4_proof_passed,
            ),
        })

    if verdict.get("gem5_systemc_blockers"):
        claims.append({
            "claim_id": "gem5_systemc_l4_blocked",
            "claim_type": "unsupported_stub_limitation",
            "statement": "gem5+SystemC full-workload binding is untrusted for this run.",
            "backend": "gem5_systemc",
            "source_fidelity": "L4",
            "predicted_only": False,
            "status": "blocked",
            "design_point_id": run_id,
            "evidence_ids": ["verdict.json", "gem5_systemc_blockers.json"],
        })

    convergence_status = convergence_status or {}
    sample_records = list((simulation_samples or {}).get("samples", []) or [])
    trusted_sample_count = sum(1 for sample in sample_records if sample.get("trusted_final_eligible"))
    if convergence_status:
        claims.append({
            "claim_id": "feedback_convergence_status",
            "claim_type": "convergence",
            "statement": (
                "The feedback loop met its configured convergence criteria."
                if convergence_status.get("converged")
                else "The feedback loop did not prove convergence; stop reason and budget status are reported as limitations."
            ),
            "backend": backend,
            "source_fidelity": fidelity,
            "predicted_only": False,
            "status": "simulated" if convergence_status.get("converged") else "blocked",
            "design_point_id": run_id,
            "converged": bool(convergence_status.get("converged", False)),
            "trusted_sample_count": trusted_sample_count,
            "evidence_ids": _with_gem5_l4_proof_evidence([
                "verdict.json",
                "workload_package.json",
                "graph_lowering_report.json",
                "simulation_result.json",
                "mapping_simulation_samples.json",
                "mapping_feedback_state.json",
                "convergence_status.json",
            ], backend=backend, trusted=bool(convergence_status.get("converged", False)), proof_passed=gem5_l4_proof_passed),
        })

    if trusted_sample_count >= 2:
        claims.append({
            "claim_id": "trusted_mapping_sample_comparison",
            "claim_type": "mapping_comparison",
            "statement": "At least two trusted high-fidelity mapping samples are available for bounded comparative ranking.",
            "backend": backend,
            "source_fidelity": fidelity,
            "predicted_only": False,
            "status": "simulated",
            "design_point_id": run_id,
            "trusted_sample_count": trusted_sample_count,
            "evidence_ids": _with_gem5_l4_proof_evidence([
                "verdict.json",
                "workload_package.json",
                "graph_lowering_report.json",
                "simulation_result.json",
                "mapping.json",
                "phase_breakdown.csv",
                "mapping_simulation_samples.json",
            ], backend=backend, trusted=True, proof_passed=gem5_l4_proof_passed),
        })

    return claims


CANDIDATE_IDENTITY_RESOLUTION_ORDER = [
    "search_policy_candidate_id",
    "mapping_candidate_id",
    "parameter_hash",
    "search_policy_parameter_hash",
    "mapping_parameter_hash",
    "candidate_id",
    "queue_candidate_id",
    "queue_entry_id",
    "mapping_id",
    "architecture_id",
    "design_point_id",
]

CANDIDATE_REF_EXPORT_FIELDS = [
    "candidate_id",
    "mapping_candidate_id",
    "parameter_hash",
    "mapping_parameter_hash",
    "search_policy_parameter_hash",
    "queue_candidate_id",
    "queue_entry_id",
    "mapping_id",
    "architecture_id",
    "design_point_id",
    "source_artifact",
]


def _compact_refs(refs: Mapping[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for key, value in refs.items():
        if value is None:
            continue
        if isinstance(value, str) and not value:
            continue
        compact[str(key)] = value
    return compact


def _load_preferred_json(run_dir: Path, rel_paths: Sequence[str]) -> Tuple[str, Dict[str, Any]]:
    for rel_path in rel_paths:
        payload = _load_json(run_dir / rel_path)
        if payload:
            return rel_path, payload
    return "", {}


def _candidate_refs_from_sample(sample: Mapping[str, Any]) -> Dict[str, Any]:
    parameters = sample.get("parameters", {}) if isinstance(sample.get("parameters", {}), Mapping) else {}
    return _compact_refs({
        "candidate_id": sample.get("candidate_id"),
        "mapping_candidate_id": sample.get("mapping_candidate_id") or parameters.get("mapping_candidate_id"),
        "parameter_hash": sample.get("parameter_hash"),
        "mapping_parameter_hash": sample.get("mapping_parameter_hash") or parameters.get("mapping_parameter_hash"),
        "search_policy_parameter_hash": sample.get("search_policy_parameter_hash"),
        "queue_entry_id": sample.get("queue_entry_id"),
        "mapping_id": sample.get("mapping_id") or parameters.get("mapping_id"),
        "architecture_id": sample.get("architecture_id") or parameters.get("architecture_id"),
        "design_point_id": sample.get("design_point_id") or parameters.get("design_point_id"),
    })


def _candidate_refs_from_handoff(
    run_dir: Path,
    *,
    design_point: Mapping[str, Any],
    architecture: Mapping[str, Any],
    mapping: Mapping[str, Any],
    simulation_request: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the canonical Step2/Step3 candidate identity for report rows."""

    selected_ref, selected_record = _load_preferred_json(run_dir, [
        "step2_input/mapping_selected_record.json",
        "step2/mapping_selected_record.json",
        "mapping_selected_record.json",
    ])
    promotion_ref, promotion = _load_preferred_json(run_dir, [
        "step2_input/mapping_promotion_decision.json",
        "step2/mapping_promotion_decision.json",
        "mapping_promotion_decision.json",
    ])
    queue_ref, queue = _load_preferred_json(run_dir, [
        "step2_input/step3_simulation_queue.json",
        "step2/step3_simulation_queue.json",
        "step3_simulation_queue.json",
    ])
    request_design_point = (
        simulation_request.get("design_point", {})
        if isinstance(simulation_request.get("design_point", {}), Mapping)
        else {}
    )
    system_architecture = (
        design_point.get("system_architecture", {})
        if isinstance(design_point.get("system_architecture", {}), Mapping)
        else {}
    )
    design_point_id = str(
        design_point.get("design_point_id")
        or request_design_point.get("design_point_id")
        or ""
    )
    architecture_id = str(
        promotion.get("architecture_id")
        or architecture.get("architecture_id")
        or request_design_point.get("architecture_id")
        or system_architecture.get("system_id")
        or ""
    )
    mapping_id = str(
        promotion.get("mapping_id")
        or selected_record.get("mapping_id")
        or mapping.get("mapping_id")
        or request_design_point.get("mapping_id")
        or ""
    )
    mapping_candidate_id = str(
        promotion.get("candidate_id")
        or selected_record.get("candidate_id")
        or mapping.get("selected_candidate_id")
        or request_design_point.get("selected_candidate_id")
        or ""
    )

    entries = queue.get("entries", []) if isinstance(queue.get("entries", []), list) else []
    queue_entry: Dict[str, Any] = {}
    candidates = [entry for entry in entries if isinstance(entry, Mapping)]
    if mapping_candidate_id:
        candidates = [
            entry for entry in candidates
            if str(entry.get("mapping_candidate_id") or "") == mapping_candidate_id
            or str(entry.get("candidate_id") or "") == mapping_candidate_id
        ]
    if design_point_id:
        design_matches = [
            entry for entry in candidates
            if str(entry.get("design_point_id") or "") == design_point_id
        ]
        if design_matches:
            candidates = design_matches
    if mapping_id:
        mapping_matches = [
            entry for entry in candidates
            if str(entry.get("mapping_id") or "") == mapping_id
        ]
        if mapping_matches:
            candidates = mapping_matches
    if architecture_id:
        architecture_matches = [
            entry for entry in candidates
            if str(entry.get("architecture_id") or "") == architecture_id
        ]
        if architecture_matches:
            candidates = architecture_matches
    scheduled = [
        entry for entry in candidates
        if str(entry.get("queue_state", "")).startswith("scheduled_for_simulation")
    ]
    if scheduled:
        queue_entry = dict(scheduled[0])
    elif candidates:
        queue_entry = dict(candidates[0])

    mapping_candidate_id = str(
        queue_entry.get("mapping_candidate_id")
        or mapping_candidate_id
        or ""
    )
    mapping_parameter_hash = str(
        queue_entry.get("mapping_parameter_hash")
        or selected_record.get("parameter_hash")
        or ""
    )
    refs = _compact_refs({
        "candidate_id": mapping_candidate_id,
        "mapping_candidate_id": mapping_candidate_id,
        "queue_candidate_id": queue_entry.get("candidate_id"),
        "queue_entry_id": queue_entry.get("queue_entry_id"),
        "parameter_hash": queue_entry.get("parameter_hash"),
        "mapping_parameter_hash": mapping_parameter_hash,
        "search_policy_parameter_hash": (
            queue_entry.get("search_policy_parameter_hash")
            or selected_record.get("search_policy_parameter_hash")
        ),
        "mapping_id": queue_entry.get("mapping_id") or mapping_id,
        "architecture_id": queue_entry.get("architecture_id") or architecture_id,
        "design_point_id": queue_entry.get("design_point_id") or design_point_id,
        "source_artifact": queue_ref or selected_ref or promotion_ref,
    })
    return refs


def _candidate_identity_payload(source: Mapping[str, Any]) -> Dict[str, Any]:
    source_refs = source.get("candidate_refs", {}) if isinstance(source.get("candidate_refs", {}), Mapping) else {}
    refs = _compact_refs({
        field: source_refs.get(field, source.get(field))
        for field in CANDIDATE_REF_EXPORT_FIELDS
    })
    payload: Dict[str, Any] = {}
    for field in (
        "candidate_id",
        "mapping_candidate_id",
        "parameter_hash",
        "mapping_parameter_hash",
        "search_policy_parameter_hash",
    ):
        if refs.get(field):
            payload[field] = refs[field]
    if refs:
        payload["candidate_refs"] = refs
        payload["candidate_id_resolution"] = [
            field for field in CANDIDATE_IDENTITY_RESOLUTION_ORDER if field in refs
        ]
    return payload


def _candidate_from_run(
    *,
    design_point: Mapping[str, Any],
    architecture: Mapping[str, Any],
    mapping: Mapping[str, Any],
    simulation_result: Mapping[str, Any],
    validation: Mapping[str, Any],
    candidate_refs: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    metrics = simulation_result.get("metrics", {}) if isinstance(simulation_result.get("metrics", {}), Mapping) else {}
    backend = str(simulation_result.get("backend", ""))
    proof = simulation_result.get("gem5_l4_proof", {}) if backend == "gem5_systemc" else {}
    proof_passed = bool(proof.get("passed", False)) if isinstance(proof, Mapping) else False
    evidence_ids = _with_gem5_l4_proof_evidence(
        ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json", "architecture.json", "mapping.json", "phase_breakdown.csv"],
        backend=backend,
        trusted=bool(validation.get("trusted", False)),
        proof_passed=proof_passed,
    )
    candidate = {
        "design_point_id": str(design_point.get("design_point_id", simulation_result.get("run_id", "unknown"))),
        "architecture_id": architecture.get("architecture_id", design_point.get("system_architecture", {}).get("system_id")),
        "mapping_id": mapping.get("mapping_id"),
        "backend": backend,
        "status": simulation_result.get("status"),
        "trusted_scope": "single-run feasibility evidence; not a comparative architecture-winner claim",
        "metrics": {
            "latency_ms": metrics.get("latency_ms"),
            "throughput_gops": metrics.get("throughput_gops"),
            "power_w": metrics.get("power_w"),
            "energy_j": metrics.get("energy_j"),
            "total_data_movement_mb": metrics.get("total_data_movement_mb"),
            "dma_time_ms": metrics.get("dma_time_ms"),
            "host_bound_compute_cost_ms": metrics.get("host_bound_compute_cost_ms", metrics.get("host_time_ms")),
            "transfer_cost_ms": metrics.get("transfer_cost_ms", metrics.get("dma_time_ms")),
            "synchronization_cost_ms": metrics.get("synchronization_cost_ms", metrics.get("sync_time_ms")),
            "queueing_cost_ms": metrics.get("queueing_cost_ms", metrics.get("queue_wait_ms")),
            "layout_cost_ms": metrics.get("layout_cost_ms", metrics.get("layout_transform_ms")),
        },
        "validation": validation,
        "evidence_ids": evidence_ids,
    }
    if candidate_refs:
        candidate.update(_candidate_identity_payload({"candidate_refs": candidate_refs}))
    return candidate


def _numeric_or_none(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _finite_nonnegative_or_none(value: Any) -> float | int | None:
    parsed = _numeric_or_none(value)
    if parsed is None:
        return None
    as_float = float(parsed)
    if not math.isfinite(as_float) or as_float < 0.0:
        return None
    return int(as_float) if as_float.is_integer() else as_float


def _first_metric(metrics: Mapping[str, Any], breakdown: Mapping[str, Any], *names: str) -> float | int | None:
    for name in names:
        value = breakdown.get(name, metrics.get(name))
        parsed = _numeric_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _full_scf_evaluated_hybrid_costs(
    simulation_result: Mapping[str, Any],
    *,
    descriptor: Optional[Mapping[str, Any]] = None,
    ppa_summary: Optional[Mapping[str, Any]] = None,
    accounting_completeness: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    metrics = simulation_result.get("metrics", {}) if isinstance(simulation_result.get("metrics", {}), Mapping) else {}
    breakdown = simulation_result.get("full_scf_cost_breakdown", simulation_result.get("scf_cost_breakdown", {}))
    breakdown = breakdown if isinstance(breakdown, Mapping) else {}
    descriptor = descriptor if isinstance(descriptor, Mapping) else {}
    ppa_summary = ppa_summary if isinstance(ppa_summary, Mapping) else {}
    descriptor_cost_model = descriptor.get("cost_model", {})
    descriptor_cost_model = descriptor_cost_model if isinstance(descriptor_cost_model, Mapping) else {}
    ppa_cost_model = ppa_summary.get("cost_model", {})
    ppa_cost_model = ppa_cost_model if isinstance(ppa_cost_model, Mapping) else {}
    cost_model = descriptor_cost_model or ppa_cost_model
    sync = _first_metric(metrics, breakdown, "synchronization_cost_ms", "sync_time_ms")
    queue = _first_metric(metrics, breakdown, "queueing_cost_ms", "queue_wait_ms")
    layout = _first_metric(metrics, breakdown, "layout_cost_ms", "layout_transform_ms")
    overhead_costs_s = cost_model.get("runtime_overhead_costs_s", {})
    overhead_costs_s = overhead_costs_s if isinstance(overhead_costs_s, Mapping) else {}
    if sync is None:
        sync = _numeric_or_none(overhead_costs_s.get("synchronization"))
        if sync is not None:
            sync = float(sync) * 1000.0
    if queue is None:
        queue = _numeric_or_none(overhead_costs_s.get("queueing"))
        if queue is not None:
            queue = float(queue) * 1000.0
    if layout is None:
        layout = _numeric_or_none(overhead_costs_s.get("layout"))
        if layout is not None:
            layout = float(layout) * 1000.0
    aggregate = _first_metric(
        metrics,
        breakdown,
        "synchronization_queueing_layout_cost_ms",
        "sync_queue_layout_cost_ms",
    )
    if aggregate is None:
        aggregate = sum(value for value in (sync, queue, layout) if value is not None)
    host_bound_cost_s = _numeric_or_none(cost_model.get("host_bound_cost_s"))
    runtime_overhead_cost_s = _numeric_or_none(cost_model.get("runtime_overhead_cost_s"))
    accelerated_kernel_cost_s = _numeric_or_none(cost_model.get("accelerated_kernel_cost_s"))
    evaluated_hybrid_scf_time_s = _numeric_or_none(cost_model.get("evaluated_hybrid_scf_time_s"))
    baseline_scf_time_s = _numeric_or_none(cost_model.get("baseline_scf_time_s"))
    descriptor_speedup = _numeric_or_none(cost_model.get("end_to_end_scf_evaluated_speedup"))
    baseline_accelerated_kernel_cost_s = _numeric_or_none(
        cost_model.get("baseline_accelerated_kernel_cost_s")
        or cost_model.get("baseline_kernel_cost_s")
    )
    if (
        baseline_accelerated_kernel_cost_s is None
        and baseline_scf_time_s is not None
        and host_bound_cost_s is not None
    ):
        residual = float(baseline_scf_time_s) - float(host_bound_cost_s)
        baseline_accelerated_kernel_cost_s = residual if residual > 0 else None
    kernel_speedup = _first_metric(metrics, breakdown, "kernel_speedup", "kernel_speedup_x")
    kernel_speedup_source = "simulation_metrics" if kernel_speedup is not None else None
    if (
        kernel_speedup is None
        and baseline_accelerated_kernel_cost_s is not None
        and accelerated_kernel_cost_s is not None
        and float(accelerated_kernel_cost_s) > 0
    ):
        kernel_speedup = float(baseline_accelerated_kernel_cost_s) / float(accelerated_kernel_cost_s)
        kernel_speedup_source = "derived_from_baseline_scf_minus_host_bound_cost"
    transfer_ms = _first_metric(metrics, breakdown, "transfer_cost_ms", "dma_time_ms")
    if transfer_ms is None:
        transfer_s = _numeric_or_none(overhead_costs_s.get("transfer"))
        if transfer_s is not None:
            transfer_ms = float(transfer_s) * 1000.0
    host_ms = _first_metric(
        metrics,
        breakdown,
        "host_bound_compute_cost_ms",
        "host_time_ms",
        "host_overhead_ms",
    )
    if host_ms is None and host_bound_cost_s is not None:
        host_ms = float(host_bound_cost_s) * 1000.0

    accounting_completeness = (
        accounting_completeness if isinstance(accounting_completeness, Mapping) else {}
    )
    payload = {
        "kernel_speedup": kernel_speedup,
        "kernel_speedup_source": kernel_speedup_source,
        "end_to_end_scf_speedup": _first_metric(
            metrics,
            breakdown,
            "end_to_end_scf_speedup",
            "full_scf_speedup",
            "scf_speedup",
        ) or descriptor_speedup,
        "host_bound_compute_cost_ms": host_ms,
        "transfer_cost_ms": transfer_ms,
        "synchronization_cost_ms": sync,
        "queueing_cost_ms": queue,
        "layout_cost_ms": layout,
        "synchronization_queueing_layout_cost_ms": aggregate,
        "accelerated_kernel_cost_s": accelerated_kernel_cost_s,
        "baseline_accelerated_kernel_cost_s": baseline_accelerated_kernel_cost_s,
        "host_bound_compute_cost_s": host_bound_cost_s,
        "runtime_overhead_cost_s": runtime_overhead_cost_s,
        "evaluated_hybrid_scf_time_s": evaluated_hybrid_scf_time_s,
        "baseline_scf_time_s": baseline_scf_time_s,
        "host_bound_phase_costs_s": cost_model.get("host_bound_phase_costs_s", {}),
        "accelerated_kernel_costs_s": cost_model.get("accelerated_kernel_costs_s", {}),
        "runtime_overhead_costs_s": cost_model.get("runtime_overhead_costs_s", {}),
        "source": (
            "full_scf_accelerator_descriptor.json"
            if descriptor_cost_model
            else "full_scf_ppa_summary.json"
            if ppa_cost_model
            else "simulation_result.json"
        ),
        "claim_boundary": (
            "Full-SCF evaluated hybrid reporting separates kernel speedup from end-to-end SCF speedup "
            "and keeps host, transfer, synchronization, queueing, and layout costs visible."
        ),
    }
    required = [
        "kernel_speedup",
        "end_to_end_scf_speedup",
        "host_bound_compute_cost_ms",
        "transfer_cost_ms",
        "synchronization_queueing_layout_cost_ms",
    ]
    payload["required_cost_fields_present"] = all(payload.get(field) is not None for field in required)
    payload["accounting_complete"] = bool(accounting_completeness.get("complete", False))
    payload["accounting_completeness_status"] = accounting_completeness.get("status")
    payload["accounting_projection_only"] = bool(accounting_completeness.get("projection_only", True))
    payload["accounting_blocker_ids"] = list(accounting_completeness.get("blocker_ids", []) or [])
    return payload


def _full_scf_accounting_bucket(
    *,
    label: str,
    blocker_prefix: str,
    required_ids: Sequence[str],
    costs_s: Any,
    scheduled_ids: Any,
) -> Dict[str, Any]:
    cost_map = costs_s if isinstance(costs_s, Mapping) else {}
    scheduled_set = {
        str(item)
        for item in (scheduled_ids if isinstance(scheduled_ids, list) else [])
        if str(item)
    }
    valid_costs: Dict[str, float | int] = {}
    invalid_ids: list[str] = []
    for item_id in required_ids:
        if item_id not in cost_map:
            continue
        parsed = _finite_nonnegative_or_none(cost_map.get(item_id))
        if parsed is None:
            invalid_ids.append(item_id)
        else:
            valid_costs[item_id] = parsed
    missing_cost_ids = [
        item_id
        for item_id in required_ids
        if item_id not in valid_costs
    ]
    missing_schedule_ids = [
        item_id
        for item_id in required_ids
        if item_id not in scheduled_set
    ]
    unexpected_cost_ids = sorted(
        str(item_id)
        for item_id in cost_map
        if str(item_id) not in set(required_ids)
    )
    blocker_ids = [
        f"{blocker_prefix}_costs_missing:{item_id}"
        for item_id in missing_cost_ids
    ]
    blocker_ids.extend(
        f"{blocker_prefix}_schedule_missing:{item_id}"
        for item_id in missing_schedule_ids
    )
    blocker_ids.extend(
        f"{blocker_prefix}_cost_invalid:{item_id}"
        for item_id in invalid_ids
    )
    return {
        "label": label,
        "required_ids": list(required_ids),
        "present_ids": [
            item_id
            for item_id in required_ids
            if item_id in valid_costs and item_id in scheduled_set
        ],
        "cost_present_ids": [
            item_id
            for item_id in required_ids
            if item_id in valid_costs
        ],
        "scheduled_ids": [
            item_id
            for item_id in required_ids
            if item_id in scheduled_set
        ],
        "missing_ids": sorted(set(missing_cost_ids) | set(missing_schedule_ids), key=list(required_ids).index),
        "missing_cost_ids": missing_cost_ids,
        "missing_schedule_ids": missing_schedule_ids,
        "invalid_cost_ids": invalid_ids,
        "unexpected_cost_ids": unexpected_cost_ids,
        "costs_s": valid_costs,
        "complete": not missing_cost_ids and not missing_schedule_ids and not invalid_ids,
        "blocker_ids": blocker_ids,
    }


def _major_kernel_matrix_completeness(hardware_matrix: Mapping[str, Any]) -> Dict[str, Any]:
    """Build a fail-closed visibility surface for the major-kernel matrix."""

    hardware_matrix = hardware_matrix if isinstance(hardware_matrix, Mapping) else {}
    expected_kernel_ids = list(MAJOR_SCF_ACCELERATED_KERNEL_IDS)
    raw_kernel_rows = hardware_matrix.get("kernel_rows")
    if not isinstance(raw_kernel_rows, list):
        raw_kernel_rows = hardware_matrix.get("rows") if isinstance(hardware_matrix.get("rows"), list) else []
    kernel_rows = [dict(row) for row in raw_kernel_rows if isinstance(row, Mapping)]

    rows_by_kernel: Dict[str, Dict[str, Any]] = {}
    duplicate_kernel_ids: list[str] = []
    unexpected_kernel_rows: list[Dict[str, Any]] = []
    for row in kernel_rows:
        kernel_id = str(row.get("kernel_id") or row.get("kernel") or "").strip()
        if not kernel_id:
            continue
        if kernel_id in rows_by_kernel:
            duplicate_kernel_ids.append(kernel_id)
            continue
        rows_by_kernel[kernel_id] = row
        if kernel_id not in expected_kernel_ids:
            unexpected_kernel_rows.append(
                {
                    "kernel_id": kernel_id,
                    "name": row.get("name"),
                    "status": row.get("status"),
                    "disposition": row.get("disposition"),
                }
            )

    missing_kernel_ids = [kernel_id for kernel_id in expected_kernel_ids if kernel_id not in rows_by_kernel]
    present_expected_row_count = len(expected_kernel_ids) - len(missing_kernel_ids)
    raw_blocker_ids = [
        str(blocker_id)
        for blocker_id in (hardware_matrix.get("blocker_ids", []) or [])
        if str(blocker_id)
    ]
    blocker_ids = list(raw_blocker_ids)
    blocker_ids.extend(f"major_kernel_matrix_row_missing:{kernel_id}" for kernel_id in missing_kernel_ids)
    blocker_ids.extend(f"major_kernel_matrix_duplicate_row:{kernel_id}" for kernel_id in duplicate_kernel_ids)
    blocker_ids.extend(
        f"major_kernel_matrix_unexpected_row:{row['kernel_id']}"
        for row in unexpected_kernel_rows
        if row.get("kernel_id")
    )
    row_coverage_complete = (
        present_expected_row_count == len(expected_kernel_ids)
        and not missing_kernel_ids
        and not duplicate_kernel_ids
        and not unexpected_kernel_rows
    )
    raw_status = str(hardware_matrix.get("status") or "not_present")
    raw_trusted = bool(hardware_matrix.get("trusted", False))
    if not hardware_matrix:
        status = "not_present"
    elif row_coverage_complete:
        status = raw_status if raw_status and raw_status != "not_present" else "passed"
    else:
        status = "blocked_partial_major_kernel_matrix"
    trusted = bool(
        row_coverage_complete
        and raw_status == "passed"
        and raw_trusted
        and not blocker_ids
    )
    hardware_completion_eligible = bool(
        row_coverage_complete
        and raw_status == "passed"
        and raw_trusted
        and bool(hardware_matrix.get("hardware_completion_eligible", False))
    )

    visible_rows: list[Dict[str, Any]] = []
    for kernel_id in expected_kernel_ids:
        row = rows_by_kernel.get(kernel_id)
        if row is None:
            visible_rows.append(
                {
                    "kernel_id": kernel_id,
                    "name": kernel_id,
                    "status": "missing",
                    "disposition": None,
                    "present": False,
                    "claim_allowed": False,
                    "trusted": False,
                    "blocker_ids": [f"major_kernel_matrix_row_missing:{kernel_id}"],
                }
            )
            continue
        row_blocker_ids = [
            str(blocker.get("id"))
            for blocker in (row.get("blockers", []) or [])
            if isinstance(blocker, Mapping) and blocker.get("id")
        ]
        visible_rows.append(
            {
                "kernel_id": kernel_id,
                "name": row.get("name"),
                "kernel_family": row.get("kernel_family"),
                "status": row.get("status"),
                "disposition": row.get("disposition"),
                "claim_allowed": bool(row.get("claim_allowed", False)),
                "trusted": bool(row.get("trusted", False)),
                "present": True,
                "blocker_ids": row_blocker_ids,
                "source": row.get("source"),
                "claim_boundary": row.get("claim_boundary"),
            }
        )

    return {
        "schema_version": "dse.final_report.major_kernel_matrix.v1",
        "present": bool(hardware_matrix),
        "status": status,
        "trusted": trusted,
        "hardware_completion_eligible": hardware_completion_eligible,
        "source": hardware_matrix.get("source"),
        "candidate_id": hardware_matrix.get("candidate_id"),
        "major_kernel_count": len(expected_kernel_ids),
        "raw_row_count": len(kernel_rows),
        "present_row_count": present_expected_row_count,
        "expected_row_count": len(expected_kernel_ids),
        "missing_kernel_ids": missing_kernel_ids,
        "duplicate_kernel_ids": duplicate_kernel_ids,
        "unexpected_kernel_rows": unexpected_kernel_rows,
        "blocker_ids": sorted(dict.fromkeys(blocker_ids)),
        "rows": visible_rows,
        "source_status": raw_status,
        "source_trusted": raw_trusted,
        "source_hardware_completion_eligible": bool(
            hardware_matrix.get("hardware_completion_eligible", False)
        ),
        "claim_boundary": hardware_matrix.get("claim_boundary"),
    }


def _qe_baseline_row_accounting_attachment_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Expose QE baseline and full-SCF row-accounting artifacts without claim upgrade."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Mapping[str, Any]] = {}
    for name in sorted(QE_BASELINE_ROW_ACCOUNTING_ATTACHMENT_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        exists = bool(entry.get("exists", False))
        artifact_refs[name] = {
            "path": rel_path,
            "exists": exists,
            "sha256": entry.get("sha256"),
            "source": "direct_step5_artifacts" if rel_path else None,
        }
        if rel_path and exists:
            payload = _load_json(run_dir / rel_path)
            if isinstance(payload, Mapping):
                loaded[name] = payload

    qe_baseline = loaded.get("qe_baseline_comparison_index.json", {})
    row_accounting = loaded.get("full_scf_row_accounting.json", {})
    present_names = [
        name for name, ref in artifact_refs.items() if bool(ref.get("exists", False))
    ]
    all_present = (
        len(present_names)
        == len(QE_BASELINE_ROW_ACCOUNTING_ATTACHMENT_ARTIFACT_NAMES)
    )
    artifact_hashes = {
        name: str(ref["sha256"])
        for name, ref in artifact_refs.items()
        if isinstance(ref, Mapping) and ref.get("sha256")
    }

    return {
        "schema_version": "dse.final_report.qe_baseline_row_accounting_attachment.v1",
        "present": bool(present_names),
        "status": (
            "attachment_present"
            if all_present
            else "partial_attachment_present"
            if present_names
            else "not_present"
        ),
        "required_artifact_names": sorted(
            QE_BASELINE_ROW_ACCOUNTING_ATTACHMENT_ARTIFACT_NAMES
        ),
        "artifacts": artifact_refs,
        "artifact_hashes": artifact_hashes,
        "hash_bound_artifact_count": len(artifact_hashes),
        "qe_baseline_comparison": {
            "present": "qe_baseline_comparison_index.json" in loaded,
            "status": qe_baseline.get("status"),
            "comparison_case_count": qe_baseline.get(
                "comparison_case_count",
                len(qe_baseline.get("comparison_rows", []) or [])
                if isinstance(qe_baseline.get("comparison_rows", []), list)
                else None,
            ),
            "deliverable_complete": bool(qe_baseline.get("deliverable_complete", False)),
        },
        "full_scf_row_accounting": {
            "present": "full_scf_row_accounting.json" in loaded,
            "status": row_accounting.get("status"),
            "passed": bool(row_accounting.get("passed", False)),
            "candidate_id": row_accounting.get("candidate_id"),
            "workload_case_id": row_accounting.get("workload_case_id"),
            "blocker_count": len(row_accounting.get("blockers", []) or [])
            if isinstance(row_accounting.get("blockers", []), list)
            else None,
            "deliverable_complete": bool(row_accounting.get("deliverable_complete", False)),
        },
        "claim_upgrade_allowed": False,
        "hardware_completion_eligible": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "QE baseline comparison and full-SCF row accounting are report attachments only. "
            "They improve row-level traceability without upgrading numerical, hardware, "
            "FPGA/ASIC, or deliverable-complete claims."
        ),
    }


def _full_scf_accounting_completeness(
    dft_full_scf_hybrid: Mapping[str, Any],
    *,
    qe_baseline_row_accounting_attachment: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a fail-closed Step5 visibility surface for full-SCF cost accounting."""

    dft_full_scf_hybrid = dft_full_scf_hybrid if isinstance(dft_full_scf_hybrid, Mapping) else {}
    present = bool(dft_full_scf_hybrid.get("present", False))
    artifacts = (
        dft_full_scf_hybrid.get("artifacts", {})
        if isinstance(dft_full_scf_hybrid.get("artifacts", {}), Mapping)
        else {}
    )
    schedule = (
        dft_full_scf_hybrid.get("schedule_summary", {})
        if isinstance(dft_full_scf_hybrid.get("schedule_summary", {}), Mapping)
        else {}
    )
    cost_model = (
        dft_full_scf_hybrid.get("cost_model", {})
        if isinstance(dft_full_scf_hybrid.get("cost_model", {}), Mapping)
        else {}
    )

    def _artifact_present(name: str) -> bool:
        ref = artifacts.get(name, {}) if isinstance(artifacts.get(name, {}), Mapping) else {}
        return bool(ref.get("exists", False))

    descriptor_present = _artifact_present("full_scf_accelerator_descriptor.json")
    runtime_schedule_present = _artifact_present("full_scf_runtime_schedule.json")
    data_residency_present = _artifact_present("full_scf_data_residency_plan.json")
    descriptor_validation_passed = bool(dft_full_scf_hybrid.get("descriptor_validation_passed", False))
    host_orchestrated = bool(schedule.get("host_orchestrated", False))

    host_bucket = _full_scf_accounting_bucket(
        label="CPU-retained/host-bound SCF stages",
        blocker_prefix="host_retained_stage",
        required_ids=REQUIRED_HOST_BOUND_PHASE_IDS,
        costs_s=cost_model.get("host_bound_phase_costs_s", {}),
        scheduled_ids=schedule.get("host_bound_phase_ids", []),
    )
    overhead_bucket = _full_scf_accounting_bucket(
        label="Transfer/synchronization/runtime overheads",
        blocker_prefix="runtime_overhead",
        required_ids=REQUIRED_OVERHEAD_PHASE_IDS,
        costs_s=cost_model.get("runtime_overhead_costs_s", {}),
        scheduled_ids=schedule.get("runtime_overhead_ids", []),
    )
    kernel_bucket = _full_scf_accounting_bucket(
        label="Major SCF kernels eligible for acceleration benefit",
        blocker_prefix="accelerated_major_kernel",
        required_ids=MAJOR_SCF_ACCELERATED_KERNEL_IDS,
        costs_s=cost_model.get("accelerated_kernel_costs_s", {}),
        scheduled_ids=schedule.get("accelerated_kernel_ids", []),
    )

    descriptor_runtime_abi = {
        "descriptor_present": descriptor_present,
        "descriptor_validation_passed": descriptor_validation_passed,
        "runtime_schedule_present": runtime_schedule_present,
        "host_orchestrated": host_orchestrated,
        "data_residency_plan_present": data_residency_present,
        "complete": (
            descriptor_present
            and descriptor_validation_passed
            and runtime_schedule_present
            and host_orchestrated
            and data_residency_present
        ),
    }

    blocker_ids: list[str] = []
    if not present:
        blocker_ids.append("full_scf_accounting_artifacts_not_present")
    elif not descriptor_present:
        blocker_ids.append("full_scf_accelerator_descriptor_missing")
    if present and descriptor_present and not descriptor_validation_passed:
        blocker_ids.append("full_scf_accelerator_descriptor_validation_not_passed")
    if present and not runtime_schedule_present:
        blocker_ids.append("full_scf_runtime_schedule_missing")
    if present and runtime_schedule_present and not host_orchestrated:
        blocker_ids.append("full_scf_runtime_schedule_not_host_orchestrated")
    if present and not data_residency_present:
        blocker_ids.append("full_scf_data_residency_plan_missing")
    blocker_ids.extend(host_bucket["blocker_ids"])
    blocker_ids.extend(overhead_bucket["blocker_ids"])
    blocker_ids.extend(kernel_bucket["blocker_ids"])
    if present and not descriptor_runtime_abi["complete"]:
        blocker_ids.append("descriptor_runtime_abi_accounting_incomplete")

    complete = (
        present
        and descriptor_runtime_abi["complete"]
        and host_bucket["complete"]
        and overhead_bucket["complete"]
        and kernel_bucket["complete"]
    )
    status = (
        "complete"
        if complete
        else "blocked_partial_accounting"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.full_scf_accounting_completeness.v1",
        "present": present,
        "status": status,
        "complete": complete,
        "projection_only": not complete,
        "descriptor_id": dft_full_scf_hybrid.get("descriptor_id"),
        "candidate_id": dft_full_scf_hybrid.get("candidate_id"),
        "prototype_boundary": dft_full_scf_hybrid.get("prototype_boundary"),
        "device_residency": dft_full_scf_hybrid.get("device_residency"),
        "host_retained_stages": host_bucket,
        "runtime_overheads": overhead_bucket,
        "accelerated_major_kernels": kernel_bucket,
        "descriptor_runtime_abi": descriptor_runtime_abi,
        "qe_baseline_row_accounting_attachment": dict(
            qe_baseline_row_accounting_attachment or {}
        ),
        "blocker_ids": sorted(dict.fromkeys(blocker_ids)),
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Full-SCF evaluated-hybrid accounting is complete only when CPU-retained "
            "stages, transfer/sync/queue/layout overheads, descriptor/runtime ABI "
            "artifacts, and all eight major-kernel cost rows are present.  Complete "
            "accounting does not by itself satisfy numerical, FPGA, ASIC, or final "
            "deployment claim gates."
        ),
    }


def _dft_full_scf_hybrid_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
    ledger_bundle: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Summarize optional DFT full-SCF evaluated-hybrid artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    artifact_source = "direct_step5_artifacts"
    for name in sorted(DFT_FULL_SCF_HYBRID_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
            "source": artifact_source if rel_path else None,
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    ledger_bundle = ledger_bundle if isinstance(ledger_bundle, Mapping) else {}
    ledger_artifact_refs = (
        ledger_bundle.get("artifact_refs", {})
        if isinstance(ledger_bundle.get("artifact_refs", {}), Mapping)
        else {}
    )
    ledger_present = bool(ledger_bundle.get("present", False))
    if not loaded and ledger_present:
        artifact_source = "dft_evidence_ledger.full_scf_hybrid_bundle"
        for name in sorted(DFT_FULL_SCF_HYBRID_ARTIFACT_NAMES):
            ref = ledger_artifact_refs.get(name, {})
            ref = ref if isinstance(ref, Mapping) else {}
            path_text = ref.get("path")
            resolved = _resolve_ledger_artifact_path(
                run_dir,
                path_text,
                bundle_dir=ledger_bundle.get("bundle_dir"),
            )
            exists = bool(resolved and resolved.exists() and resolved.is_file())
            artifact_refs[name] = {
                "path": str(path_text) if path_text else None,
                "resolved_path": str(resolved) if resolved else None,
                "exists": exists,
                "sha256": ref.get("sha256", ref.get("hash")),
                "source": artifact_source if path_text else None,
            }
            if exists and resolved is not None:
                loaded[name] = _load_json(resolved)

    descriptor = loaded.get("full_scf_accelerator_descriptor.json", {})
    runtime_schedule = loaded.get("full_scf_runtime_schedule.json", {})
    data_residency = loaded.get("full_scf_data_residency_plan.json", {})
    correctness = loaded.get("full_scf_correctness_report.json", {})
    ppa_summary = loaded.get("full_scf_ppa_summary.json", {})
    validation = descriptor.get("validation", {}) if isinstance(descriptor.get("validation", {}), Mapping) else {}
    prototype_boundary = descriptor.get("prototype_boundary") or ledger_bundle.get("prototype_boundary")
    device_residency = (
        descriptor.get("device_residency")
        or data_residency.get("device_residency")
        or ledger_bundle.get("device_residency")
    )
    accelerated_kernel_ids = [
        str(item)
        for item in runtime_schedule.get(
            "accelerated_kernel_ids",
            descriptor.get("hardware_acceleration_claim_scope", []),
        )
        or []
    ]
    host_bound_phase_ids = [
        str(item)
        for item in runtime_schedule.get(
            "host_bound_phase_ids",
            descriptor.get("host_bound_phase_scope", []),
        )
        or []
    ]
    runtime_overhead_ids = [
        str(item)
        for item in runtime_schedule.get(
            "runtime_overhead_ids",
            descriptor.get("runtime_overhead_scope", []),
        )
        or []
    ]
    host_orchestrated = bool(runtime_schedule.get("host_orchestrated", False))
    cost_model = descriptor.get("cost_model", ppa_summary.get("cost_model", {}))
    cost_model = cost_model if isinstance(cost_model, Mapping) else {}
    host_costs = (
        cost_model.get("host_bound_phase_costs_s", {})
        if isinstance(cost_model.get("host_bound_phase_costs_s", {}), Mapping)
        else {}
    )
    overhead_costs = (
        cost_model.get("runtime_overhead_costs_s", {})
        if isinstance(cost_model.get("runtime_overhead_costs_s", {}), Mapping)
        else {}
    )
    major_kernel_set = set(MAJOR_SCF_ACCELERATED_KERNEL_IDS)
    required_present = all(
        artifact_refs[name]["exists"]
        for name in DFT_FULL_SCF_HYBRID_ARTIFACT_NAMES
    )
    present = bool(loaded) or ledger_present
    artifact_hashes = {
        name: str(ref["sha256"])
        for name, ref in artifact_refs.items()
        if isinstance(ref, Mapping) and ref.get("sha256")
    }
    partition_complete = (
        bool(accelerated_kernel_ids)
        and set(accelerated_kernel_ids).issubset(major_kernel_set)
        and bool(host_bound_phase_ids)
        and all(phase_id in host_costs for phase_id in host_bound_phase_ids)
        and bool(runtime_overhead_ids)
        and all(overhead_id in overhead_costs for overhead_id in runtime_overhead_ids)
    )
    return {
        "schema_version": "dse.final_report.dft_full_scf_evaluated_hybrid.v1",
        "present": present,
        "status": (
            "artifact_bundle_present"
            if required_present and artifact_source == "direct_step5_artifacts"
            else "ledger_artifact_bundle_present"
            if required_present and artifact_source == "dft_evidence_ledger.full_scf_hybrid_bundle"
            else "partial_artifact_bundle_present"
            if present
            else "not_present"
        ),
        "source": artifact_source if present else None,
        "required_artifacts_present": required_present,
        "artifacts": artifact_refs,
        "artifact_hashes": artifact_hashes,
        "hash_bound_artifact_count": len(artifact_hashes),
        "descriptor_id": descriptor.get("descriptor_id") or ledger_bundle.get("descriptor_id"),
        "candidate_id": descriptor.get("candidate_id") or runtime_schedule.get("candidate_id") or ledger_bundle.get("candidate_id"),
        "campaign_id": descriptor.get("campaign_id") or runtime_schedule.get("campaign_id") or ledger_bundle.get("campaign_id"),
        "workload_run_id": descriptor.get("workload_run_id") or runtime_schedule.get("workload_run_id") or ledger_bundle.get("workload_run_id"),
        "trial_id": descriptor.get("trial_id") or runtime_schedule.get("trial_id") or ledger_bundle.get("trial_id"),
        "prototype_boundary": prototype_boundary,
        "device_residency": device_residency,
        "completion_claim": False,
        "partial": bool(present and not required_present),
        "projection_only": True,
        "blocked": True,
        "deliverable_complete": False,
        "descriptor_validation_passed": bool(
            validation.get("passed", ledger_bundle.get("descriptor_validation_passed", False))
        ),
        "correctness_status": correctness.get("status"),
        "numerical_correctness_claim_eligible": bool(
            correctness.get(
                "numerical_correctness_claim_eligible",
                ledger_bundle.get("numerical_correctness_claim_eligible", False),
            )
        ),
        "ppa_status": ppa_summary.get("status"),
        "ppa_claim_eligible": bool(
            ppa_summary.get("ppa_claim_eligible", ledger_bundle.get("ppa_claim_eligible", False))
        ),
        "schedule_summary": {
            "accelerated_kernel_ids": accelerated_kernel_ids,
            "host_bound_phase_ids": host_bound_phase_ids,
            "runtime_overhead_ids": runtime_overhead_ids,
            "host_orchestrated": host_orchestrated,
        },
        "host_device_partition": {
            "schema_version": "dse.final_report.dft_full_scf_host_device_partition.v1",
            "prototype_boundary": prototype_boundary,
            "device_residency": device_residency,
            "accelerated_kernel_ids": accelerated_kernel_ids,
            "cpu_retained_stage_ids": host_bound_phase_ids,
            "runtime_overhead_ids": runtime_overhead_ids,
            "host_orchestrated": host_orchestrated,
            "hardware_acceleration_claim_limited_to_major_kernels": (
                bool(accelerated_kernel_ids)
                and set(accelerated_kernel_ids).issubset(major_kernel_set)
            ),
            "cpu_retained_stages_counted_in_end_to_end_cost": (
                bool(host_bound_phase_ids)
                and all(phase_id in host_costs for phase_id in host_bound_phase_ids)
            ),
            "runtime_overheads_counted_in_end_to_end_cost": (
                bool(runtime_overhead_ids)
                and all(overhead_id in overhead_costs for overhead_id in runtime_overhead_ids)
            ),
            "partial": not partition_complete,
            "projection_only": True,
            "blocked": True,
            "trusted_final_claim": False,
            "deliverable_complete": False,
            "claim_boundary": (
                "Derived report-only host/device partition. CPU-retained stages "
                "and transfer/sync/runtime overheads are end-to-end costs, not "
                "hardware acceleration benefits."
            ),
        },
        "cost_model": dict(cost_model),
        "trusted_final_claim": False,
        "claim_boundary": (
            "DFT full-SCF evaluated-hybrid artifacts are Step5-visible accounting "
            "and schedule evidence.  They do not prove full-SCF device residency, "
            "numerical correctness, or FPGA/ASIC PPA closure unless the separate "
            "hard gates pass."
        ),
    }


def _deployment_recommendation_plan_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize proposal-only FPGA/ASIC deployment planning without upgrading claims."""

    rel_path, entry = _find_indexed_artifact(evidence_index, "deployment_recommendation_plan.json")
    payload = _load_json(run_dir / rel_path) if rel_path else {}
    queue_rel_path, queue_entry = _find_indexed_artifact(
        evidence_index,
        "dft_deployment_hard_gate_execution_queue.json",
    )
    queue_payload = _load_json(run_dir / queue_rel_path) if queue_rel_path else {}
    queue_validation_rel_path, queue_validation_entry = _find_indexed_artifact(
        evidence_index,
        "dft_deployment_hard_gate_execution_queue_validation.json",
    )
    queue_validation = _load_json(run_dir / queue_validation_rel_path) if queue_validation_rel_path else {}
    queue_status_rel_path, queue_status_entry = _find_indexed_artifact(
        evidence_index,
        "dft_deployment_hard_gate_execution_queue_status.json",
    )
    queue_status = _load_json(run_dir / queue_status_rel_path) if queue_status_rel_path else {}
    target_binding_rel_path, target_binding_entry = _find_indexed_artifact(
        evidence_index,
        "dft_deployment_target_model_binding.json",
    )
    target_binding = _load_json(run_dir / target_binding_rel_path) if target_binding_rel_path else {}
    target_binding_validation_rel_path, target_binding_validation_entry = _find_indexed_artifact(
        evidence_index,
        "dft_deployment_target_model_binding_validation.json",
    )
    target_binding_validation = (
        _load_json(run_dir / target_binding_validation_rel_path)
        if target_binding_validation_rel_path
        else {}
    )
    target_summaries = (
        payload.get("target_summaries", {})
        if isinstance(payload.get("target_summaries", {}), Mapping)
        else {}
    )
    recommendations = (
        payload.get("candidate_recommendations", [])
        if isinstance(payload.get("candidate_recommendations", []), list)
        else []
    )
    work_items = (
        payload.get("hard_gate_work_items", [])
        if isinstance(payload.get("hard_gate_work_items", []), list)
        else []
    )
    target_work_item_counts = (
        payload.get("target_work_item_counts", {})
        if isinstance(payload.get("target_work_item_counts", {}), Mapping)
        else {}
    )
    present = bool(payload)
    return {
        "schema_version": "dse.final_report.deployment_recommendation_plan.v1",
        "present": present,
        "artifact": rel_path,
        "exists": bool(entry.get("exists", False)),
        "sha256": entry.get("sha256"),
        "status": payload.get("status", "not_present"),
        "trusted_timing_sample_count": payload.get("trusted_timing_sample_count", 0),
        "candidate_recommendation_count": len(recommendations),
        "hard_gate_work_item_count": len(work_items),
        "hard_gates_pending": bool(payload.get("hard_gates_pending", bool(work_items))),
        "deployment_hard_gate_closure_status": payload.get(
            "deployment_hard_gate_closure_status",
            "hard_gates_pending" if work_items else "blocked",
        ),
        "target_work_item_counts": dict(target_work_item_counts),
        "target_summaries": dict(target_summaries),
        "forbidden_claims": list(payload.get("forbidden_claims", []) or []),
        "next_actions": list(payload.get("next_actions", []) or []),
        "hard_gate_execution_queue": {
            "present": bool(queue_payload),
            "artifact": queue_rel_path,
            "exists": bool(queue_entry.get("exists", False)),
            "sha256": queue_entry.get("sha256"),
            "status_artifact": queue_status_rel_path,
            "validation_artifact": queue_validation_rel_path,
            "queue_status": queue_payload.get("status", queue_status.get("queue_status")),
            "queue_materialization_status": queue_payload.get(
                "queue_materialization_status",
                queue_status.get("queue_materialization_status"),
            ),
            "deployment_hard_gate_closure_status": queue_payload.get(
                "deployment_hard_gate_closure_status",
                queue_status.get("deployment_hard_gate_closure_status", "not_materialized"),
            ),
            "hard_gates_pending": bool(
                queue_payload.get("hard_gates_pending", queue_status.get("hard_gates_pending", False))
            ),
            "status": queue_status.get("status"),
            "validation_status": queue_status.get("validation_status"),
            "work_item_count": queue_payload.get("work_item_count", queue_status.get("work_item_count")),
            "candidate_count": queue_payload.get("candidate_count", queue_status.get("candidate_count")),
            "major_kernel_count": queue_payload.get("major_kernel_count", queue_status.get("major_kernel_count")),
            "target_work_item_counts": dict(
                queue_payload.get("target_work_item_counts", queue_status.get("target_work_item_counts", {}))
                if isinstance(
                    queue_payload.get("target_work_item_counts", queue_status.get("target_work_item_counts", {})),
                    Mapping,
                )
                else {}
            ),
            "validation": {
                "present": bool(queue_validation),
                "valid": queue_validation.get("valid"),
                "error_count": len(queue_validation.get("errors", []) or []) if queue_validation else None,
                "exists": bool(queue_validation_entry.get("exists", False)),
                "sha256": queue_validation_entry.get("sha256"),
            },
            "status_ref": {
                "present": bool(queue_status),
                "exists": bool(queue_status_entry.get("exists", False)),
                "sha256": queue_status_entry.get("sha256"),
            },
            "target_model_binding": {
                "present": bool(target_binding),
                "artifact": target_binding_rel_path,
                "exists": bool(target_binding_entry.get("exists", False)),
                "sha256": target_binding_entry.get("sha256"),
                "validation_artifact": target_binding_validation_rel_path,
                "status": target_binding.get(
                    "status",
                    queue_status.get("target_model_binding_status"),
                ),
                "blocker_ids": list(
                    target_binding.get(
                        "blocker_ids",
                        queue_status.get("target_model_binding_blocker_ids", []),
                    )
                    or []
                ),
                "target_binding_row_count": target_binding.get("target_binding_row_count"),
                "validation": {
                    "present": bool(target_binding_validation),
                    "valid": target_binding_validation.get("valid"),
                    "error_count": len(target_binding_validation.get("errors", []) or [])
                    if target_binding_validation
                    else None,
                    "exists": bool(target_binding_validation_entry.get("exists", False)),
                    "sha256": target_binding_validation_entry.get("sha256"),
                },
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
                "claim_boundary": target_binding.get(
                    "claim_boundary",
                    "Deployment target model binding was not indexed for this Step5 run.",
                ),
            },
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": (
                queue_payload.get("claim_boundary")
                or "DFT deployment hard-gate execution queue was not indexed for this Step5 run."
            ),
        },
        "trusted_deployment_claim": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "claim_boundary": payload.get(
            "claim_boundary",
            "No deployment recommendation plan was indexed for this Step5 run.",
        ),
    }


def _phase_summary(run_dir: Path) -> Dict[str, Any]:
    rows = _read_csv_rows(run_dir / "phase_breakdown.csv")
    available = [row for row in rows if row.get("status") == "available"]
    slowest = sorted(
        available,
        key=lambda row: float(row.get("latency_ms") or 0.0),
        reverse=True,
    )[:5]
    return {
        "available_phase_count": len(available),
        "missing_phase_count": len(rows) - len(available),
        "slowest_phases": [
            {
                "phase": row.get("phase"),
                "device": row.get("device"),
                "latency_ms": float(row.get("latency_ms") or 0.0),
                "evidence_id": "phase_breakdown.csv",
            }
            for row in slowest
        ],
    }


def _artifact_exists(run_dir: Path, evidence_index: Mapping[str, Mapping[str, Any]], rel_path: str) -> bool:
    entry = evidence_index.get(rel_path)
    if entry is not None:
        return bool(entry.get("exists", False))
    return (run_dir / rel_path).exists()


def _decision_summary(payload: Mapping[str, Any], *, artifact: str, exists: bool) -> Dict[str, Any]:
    return {
        "artifact": artifact,
        "exists": exists,
        "decision": payload.get("decision"),
        "promote": bool(payload.get("promote", False)),
        "from_layer": payload.get("from_layer", payload.get("source_layer")),
        "to_layer": payload.get("to_layer", payload.get("target_layer")),
        "reason": payload.get("reason"),
        "promotion_score": payload.get("promotion_score", payload.get("score")),
        "confidence": payload.get("confidence"),
        "threshold": payload.get("threshold"),
        "low_fidelity_role": payload.get("low_fidelity_role"),
        "trusted_final_claim": bool(payload.get("trusted_final_claim", False)),
    }


def _layer_screening_summary(
    result: Mapping[str, Any],
    decision: Mapping[str, Any],
    *,
    result_artifact: str,
    decision_artifact: str,
    result_exists: bool,
    decision_exists: bool,
) -> Dict[str, Any]:
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics", {}), Mapping) else {}
    uncertainty = result.get("uncertainty", {}) if isinstance(result.get("uncertainty", {}), Mapping) else {}
    return {
        "artifact": result_artifact,
        "exists": result_exists,
        "fidelity_level_achieved": result.get("fidelity_level_achieved"),
        "status": result.get("status", "missing" if not result_exists else None),
        "design_point_id": result.get("design_point_id"),
        "family": result.get("family"),
        "candidate_id": result.get("candidate_id"),
        "feasible": result.get("feasible"),
        "confidence": result.get("confidence"),
        "promotion_score": result.get("promotion_score"),
        "mape_percent": result.get("mape_percent"),
        "metrics": dict(metrics),
        "uncertainty": dict(uncertainty),
        "provenance": result.get("provenance", {}),
        "candidate_generation_only": bool(result.get("candidate_generation_only", result_exists)),
        "low_fidelity_role": result.get("low_fidelity_role"),
        "trusted_final_claim": bool(result.get("trusted_final_claim", False)),
        "promotion_decision": _decision_summary(decision, artifact=decision_artifact, exists=decision_exists),
    }


def _low_fidelity_screening_section(
    run_dir: Path,
    *,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    loaded = {
        key: _load_json(run_dir / filename)
        for key, filename in LOW_FIDELITY_ARTIFACT_KEYS.items()
    }
    exists = {
        key: _artifact_exists(run_dir, evidence_index, filename)
        for key, filename in LOW_FIDELITY_ARTIFACT_KEYS.items()
    }
    present = any(exists.values())
    missing_artifacts = [
        filename
        for key, filename in LOW_FIDELITY_ARTIFACT_KEYS.items()
        if not exists[key]
    ]
    summary = loaded["low_fidelity_summary"]
    status = str(summary.get("status") or ("incomplete" if present and missing_artifacts else "available" if present else "unavailable"))
    l1 = _layer_screening_summary(
        loaded["l1_evaluation_result"],
        loaded["l1_promotion_decision"],
        result_artifact=LOW_FIDELITY_ARTIFACT_KEYS["l1_evaluation_result"],
        decision_artifact=LOW_FIDELITY_ARTIFACT_KEYS["l1_promotion_decision"],
        result_exists=exists["l1_evaluation_result"],
        decision_exists=exists["l1_promotion_decision"],
    )
    l2 = _layer_screening_summary(
        loaded["l2_evaluation_result"],
        loaded["l2_promotion_decision"],
        result_artifact=LOW_FIDELITY_ARTIFACT_KEYS["l2_evaluation_result"],
        decision_artifact=LOW_FIDELITY_ARTIFACT_KEYS["l2_promotion_decision"],
        result_exists=exists["l2_evaluation_result"],
        decision_exists=exists["l2_promotion_decision"],
    )
    return {
        "schema_version": "dse.final_report.low_fidelity_screening.v1",
        "present": present,
        "status": status,
        "summary_artifact": LOW_FIDELITY_ARTIFACT_KEYS["low_fidelity_summary"],
        "summary_exists": exists["low_fidelity_summary"],
        "passed": bool(summary.get("passed", False)),
        "required_for_step3": bool(summary.get("required_for_step3", present)),
        "artifact_refs": (
            dict(summary.get("artifact_refs", LOW_FIDELITY_ARTIFACT_KEYS))
            if isinstance(summary.get("artifact_refs", {}), Mapping)
            else dict(LOW_FIDELITY_ARTIFACT_KEYS)
        ),
        "required_artifacts": (
            list(summary.get("required_artifacts", LOW_FIDELITY_ARTIFACT_PATHS))
            if isinstance(summary.get("required_artifacts", []), list)
            else list(LOW_FIDELITY_ARTIFACT_PATHS)
        ),
        "missing_artifacts": missing_artifacts,
        "loaded_artifacts": [filename for key, filename in LOW_FIDELITY_ARTIFACT_KEYS.items() if exists[key]],
        "candidate_id": summary.get("candidate_id") or l1.get("candidate_id") or l2.get("candidate_id"),
        "mapping_id": summary.get("mapping_id"),
        "policy": summary.get("policy", {}),
        "promotion_scores": summary.get("promotion_scores", {}),
        "thresholds": summary.get("thresholds", {}),
        "confidence": summary.get("confidence", {}),
        "blockers": list(summary.get("blockers", []) or []),
        "l1": l1,
        "l2": l2,
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
        "trusted_final_eligible": False,
        "excluded_from_trusted_ranking": True,
        "notes": [
            "L1/L2 screening is reported for Step2 transparency and Step3 gate traceability only.",
            "Trusted ranking and selected winners require SystemC or gem5+SystemC evidence.",
        ],
    }


def _low_fidelity_claims(low_fidelity: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if not low_fidelity.get("present"):
        return []
    summary_artifact = str(low_fidelity.get("summary_artifact", LOW_FIDELITY_ARTIFACT_KEYS["low_fidelity_summary"]))
    claims: List[Dict[str, Any]] = []
    for layer_key, backend, source_fidelity, statement in [
        (
            "l1",
            "analytical",
            "L1",
            "L1 analytical screening is available as a Step2 candidate-generation signal only.",
        ),
        (
            "l2",
            "tlm",
            "L2",
            "L2 TLM screening is available as a Step2 candidate-generation signal only.",
        ),
    ]:
        layer = low_fidelity.get(layer_key, {}) if isinstance(low_fidelity.get(layer_key, {}), Mapping) else {}
        if not layer.get("exists"):
            continue
        evidence_ids = list(LOW_FIDELITY_ARTIFACT_PATHS)
        if not low_fidelity.get("summary_exists") and summary_artifact in evidence_ids:
            evidence_ids.remove(summary_artifact)
        claims.append({
            "claim_id": f"{layer_key}_screening_candidate_signal",
            "claim_type": "low_fidelity_screening",
            "statement": statement,
            "backend": backend,
            "source_fidelity": source_fidelity,
            "predicted_only": True,
            "status": layer.get("status", "available"),
            "design_point_id": layer.get("design_point_id"),
            "candidate_id": layer.get("candidate_id", low_fidelity.get("candidate_id")),
            "low_fidelity_role": "candidate_generator_only",
            "trusted_final_claim": False,
            "evidence_ids": evidence_ids,
        })
    return claims


def _find_indexed_artifact(
    evidence_index: Mapping[str, Mapping[str, Any]],
    artifact_name: str,
) -> tuple[str | None, Mapping[str, Any]]:
    direct = evidence_index.get(artifact_name)
    if direct and direct.get("exists"):
        return artifact_name, direct
    for rel_path, entry in evidence_index.items():
        if Path(rel_path).name == artifact_name and entry.get("exists"):
            return rel_path, entry
    return None, {}


def _resolve_run_or_artifact_relative_path(
    ref_path: Any,
    *,
    run_dir: Path,
    artifact_path: Optional[Path] = None,
) -> Optional[Path]:
    if not ref_path:
        return None
    path = Path(str(ref_path))
    if path.is_absolute():
        return path
    candidates: List[Path] = [run_dir / path]
    if artifact_path is not None:
        candidates.append(Path(artifact_path).parent / path)
    candidates.append(path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _normalize_run_local_ref(value: str) -> tuple[str | None, str | None]:
    candidate = PurePosixPath(str(value))
    if candidate.is_absolute():
        return None, "absolute paths are not run-local evidence references"
    if ".." in candidate.parts:
        return None, "parent-directory traversal is not allowed in evidence references"
    normalized = str(candidate)
    if normalized in {".", ""}:
        return None, "empty queue reference is not a run-local evidence reference"
    return normalized, None


def _search_admission_queue_ref_resolution(
    loaded: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return ordered run-local Step3 queue refs plus rejected handoff refs."""

    candidate_rows: List[Dict[str, Any]] = []
    for artifact_name in [
        "campaign_search_admission_plan.json",
        "campaign_evaluation_plan.json",
        "search_iteration_plan.json",
    ]:
        payload = loaded.get(artifact_name, {})
        if not isinstance(payload, Mapping):
            continue
        for field in [
            "step3_simulation_queue_ref",
            "next_step3_admission_queue_ref",
            "step3_admission_queue",
        ]:
            value = payload.get(field)
            if isinstance(value, str) and value:
                candidate_rows.append({
                    "artifact": artifact_name,
                    "field": field,
                    "ref": value,
                    "explicit": True,
                })
    candidate_rows.extend(
        {
            "artifact": "default",
            "field": "step3_simulation_queue_ref",
            "ref": value,
            "explicit": False,
        }
        for value in CONTROL_PLANE_STEP3_QUEUE_DEFAULT_REFS
    )
    ordered: List[str] = []
    explicit_refs: List[str] = []
    invalid_refs: List[Dict[str, Any]] = []
    seen: set[str] = set()
    explicit_ref_count = 0
    for row in candidate_rows:
        if row.get("explicit"):
            explicit_ref_count += 1
        normalized, reason = _normalize_run_local_ref(str(row.get("ref") or ""))
        if normalized is None:
            if row.get("explicit"):
                invalid_refs.append({
                    "artifact": row.get("artifact"),
                    "field": row.get("field"),
                    "ref": row.get("ref"),
                    "reason": reason,
                })
            continue
        if normalized not in seen:
            ordered.append(normalized)
            seen.add(normalized)
        if row.get("explicit") and normalized not in explicit_refs:
            explicit_refs.append(normalized)
    return {
        "refs": ordered,
        "explicit_refs": explicit_refs,
        "explicit_ref_count": explicit_ref_count,
        "invalid_refs": invalid_refs,
    }


def _search_admission_queue_ref_candidates(
    loaded: Mapping[str, Mapping[str, Any]],
) -> List[str]:
    """Return ordered run-relative refs that may name the Step3 admission queue."""

    return list(_search_admission_queue_ref_resolution(loaded).get("refs", []))


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _find_step3_queue_artifact(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
    loaded: Mapping[str, Mapping[str, Any]],
) -> tuple[str | None, Mapping[str, Any], Mapping[str, Any]]:
    """Resolve the actual Step3 queue, preferring refs over basename matches."""

    ref_resolution = _search_admission_queue_ref_resolution(loaded)
    explicit_refs = list(ref_resolution.get("explicit_refs", []) or [])
    refs_to_search = (
        explicit_refs
        if ref_resolution.get("explicit_ref_count", 0)
        else list(ref_resolution.get("refs", []) or [])
    )
    for rel_path in refs_to_search:
        entry = evidence_index.get(rel_path, {})
        if entry.get("exists"):
            path = run_dir / rel_path
            if _path_is_under(path, run_dir):
                return rel_path, entry, ref_resolution
        path = run_dir / rel_path
        if path.exists() and path.is_file() and _path_is_under(path, run_dir):
            return rel_path, {
                "path": rel_path,
                "exists": True,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }, ref_resolution
    if ref_resolution.get("explicit_ref_count", 0):
        missing_ref = explicit_refs[0] if explicit_refs else None
        return missing_ref, {
            "path": missing_ref,
            "exists": False,
            "unavailable_reason": "referenced Step3 simulation queue artifact not present in run directory",
        }, ref_resolution
    candidates = list(ref_resolution.get("refs", []) or [])
    if candidates:
        missing_ref = candidates[0]
        return missing_ref, {
            "path": missing_ref,
            "exists": False,
            "unavailable_reason": "canonical Step3 simulation queue artifact not present in run directory",
        }, ref_resolution
    return None, {}, ref_resolution


def _recompute_step3_queue_validation(
    loaded: Mapping[str, Mapping[str, Any]],
    queue_rel_path: str | None,
) -> Dict[str, Any]:
    """Re-run the Step3 admission queue validator from current artifacts."""

    queue = loaded.get(CONTROL_PLANE_STEP3_QUEUE_ARTIFACT_NAME, {})
    if not queue:
        return {}
    try:
        from dse_v2.dse.step3_admission_queue_validation import (
            validate_step3_admission_queue,
        )

        campaign_evaluation_plan = loaded.get("campaign_evaluation_plan.json", {})
        search_iteration_plan = loaded.get("search_iteration_plan.json", {})
        campaign_search_admission_plan = loaded.get("campaign_search_admission_plan.json", {})
        refs: Dict[str, str] = {}
        if queue_rel_path:
            refs["step3_simulation_queue"] = queue_rel_path
        for payload in [
            campaign_evaluation_plan,
            campaign_search_admission_plan,
            search_iteration_plan,
        ]:
            if not isinstance(payload, Mapping):
                continue
            top_k_ref = payload.get("top_k_candidate_queue_ref")
            if isinstance(top_k_ref, str) and top_k_ref:
                refs.setdefault("top_k_candidate_queue", top_k_ref)
        validation = validate_step3_admission_queue(
            step3_simulation_queue=queue,
            campaign_evaluation_plan=(
                campaign_evaluation_plan
                if isinstance(campaign_evaluation_plan, Mapping) and campaign_evaluation_plan
                else None
            ),
            search_iteration_plan=(
                search_iteration_plan
                if isinstance(search_iteration_plan, Mapping) and search_iteration_plan
                else None
            ),
            campaign_search_admission_plan=(
                campaign_search_admission_plan
                if isinstance(campaign_search_admission_plan, Mapping) and campaign_search_admission_plan
                else None
            ),
            refs=refs,
        )
        return validation if isinstance(validation, dict) else {}
    except Exception as exc:  # pragma: no cover - defensive fail-closed guard.
        return {
            "schema_version": "dse.step3.admission_queue_validation.v1",
            "status": "failed",
            "valid": False,
            "error_count": 1,
            "errors": [
                {
                    "field": "step3_admission_queue_recomputed_validation.exception",
                    "message": "Step5 could not recompute Step3 admission queue validation",
                    "exception": type(exc).__name__,
                    "detail": str(exc),
                }
            ],
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "claim_boundary": (
                "Step5 treats recomputation failures as failed search/admission "
                "validation rather than trusting stale sidecars."
            ),
        }


def _recompute_search_iteration_plan_validation(
    loaded: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Re-run the Step2 search-iteration validator from the current plan."""

    search_iteration_plan = loaded.get("search_iteration_plan.json", {})
    if not search_iteration_plan:
        return {}
    try:
        from dse_v2.mapping.search_plan_validation import (
            validate_search_iteration_plan,
        )

        validation = validate_search_iteration_plan(search_iteration_plan)
        return validation if isinstance(validation, dict) else {}
    except Exception as exc:  # pragma: no cover - defensive fail-closed guard.
        return {
            "schema_version": "dse.step2.search_iteration_plan_validation.v1",
            "status": "failed",
            "valid": False,
            "error_count": 1,
            "errors": [
                {
                    "field": "search_iteration_plan_recomputed_validation.exception",
                    "message": "Step5 could not recompute search iteration plan validation",
                    "exception": type(exc).__name__,
                    "detail": str(exc),
                }
            ],
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": (
                "Step5 treats search-plan recomputation failures as failed "
                "search/admission validation rather than trusting stale sidecars."
            ),
        }


def _control_plane_scope_consensus(
    loaded: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Recompute Campaign/Trial scope consensus from present handoff artifacts."""

    source_artifacts = {
        "campaign_evaluation_plan": "campaign_evaluation_plan.json",
        "search_iteration_plan": "search_iteration_plan.json",
        "campaign_search_admission_plan": "campaign_search_admission_plan.json",
        "step3_simulation_queue": CONTROL_PLANE_STEP3_QUEUE_ARTIFACT_NAME,
    }
    observed: Dict[str, Dict[str, List[str]]] = {
        field: {}
        for field in CONTROL_PLANE_SCOPE_FIELDS
    }
    for source, artifact_name in source_artifacts.items():
        payload = loaded.get(artifact_name, {})
        if not payload:
            continue
        for field in CONTROL_PLANE_SCOPE_FIELDS:
            value = str(payload.get(field) or "")
            if value:
                observed[field].setdefault(value, []).append(source)

    conflicts: List[Dict[str, Any]] = []
    for field, values_by_source in observed.items():
        if len(values_by_source) <= 1:
            continue
        conflicts.append({
            "field": field,
            "observed_values": sorted(values_by_source),
            "sources_by_value": {
                value: sorted(sources)
                for value, sources in sorted(values_by_source.items())
            },
        })

    return {
        "schema_version": "dse.final_report.search_admission_scope_consensus.v1",
        "status": "passed" if not conflicts else "failed",
        "valid": not conflicts,
        "scope_fields": list(CONTROL_PLANE_SCOPE_FIELDS),
        "observed": {
            field: {
                value: sorted(sources)
                for value, sources in sorted(values_by_source.items())
            }
            for field, values_by_source in observed.items()
        },
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "claim_boundary": (
            "Step5 recomputes Campaign/Trial scope from present control-plane "
            "handoff artifacts and does not trust stale passed validation "
            "sidecars when the source artifacts disagree."
        ),
    }


def _search_admission_validation_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize Step2/Step3/Campaign search-admission control artifacts.

    These artifacts are orchestration/admission evidence, not performance
    evidence.  Step5 must show them and fail closed when they are present but
    invalid so a final report cannot imply a trusted campaign/search handoff
    while the control plane rejected admission.
    """

    run_dir = Path(run_dir)
    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(CONTROL_PLANE_VALIDATION_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        if not rel_path and (run_dir / name).exists():
            rel_path = name
            path = run_dir / name
            entry = {
                "path": name,
                "exists": True,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    queue_rel_path, queue_entry, queue_ref_resolution = _find_step3_queue_artifact(
        run_dir,
        evidence_index,
        loaded,
    )
    artifact_refs[CONTROL_PLANE_STEP3_QUEUE_ARTIFACT_NAME] = {
        "path": queue_rel_path,
        "exists": bool(queue_entry.get("exists", False)),
        "sha256": queue_entry.get("sha256"),
    }
    if queue_rel_path and queue_entry.get("exists"):
        loaded[CONTROL_PLANE_STEP3_QUEUE_ARTIFACT_NAME] = _load_json(run_dir / queue_rel_path)

    present = bool(loaded)
    core_artifacts = {
        "search_iteration_plan.json",
        "search_iteration_plan_validation.json",
        "step3_admission_queue_validation.json",
        "campaign_search_admission_plan.json",
    }
    core_present = any(artifact_refs[name]["exists"] for name in core_artifacts)
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    def add_error(field: str, message: str, *, actual: Any = None) -> None:
        error: Dict[str, Any] = {"field": field, "message": message}
        if actual is not None:
            error["actual"] = actual
        errors.append(error)

    def add_warning(field: str, message: str, *, actual: Any = None) -> None:
        warning: Dict[str, Any] = {"field": field, "message": message}
        if actual is not None:
            warning["actual"] = actual
        warnings.append(warning)

    if core_present:
        for name in sorted(core_artifacts):
            if not artifact_refs[name]["exists"]:
                add_error(
                    name,
                    "search/admission control-plane context requires this artifact before Step5 can trust the handoff",
                )
    scope_consensus = _control_plane_scope_consensus(loaded)
    for conflict in scope_consensus.get("conflicts", []) or []:
        if isinstance(conflict, Mapping):
            field = str(conflict.get("field") or "unknown")
            add_error(
                f"campaign_scope.{field}",
                "Campaign scope field must agree across present Step5 control-plane artifacts",
                actual={
                    "observed_values": conflict.get("observed_values", []),
                    "sources_by_value": conflict.get("sources_by_value", {}),
                },
            )
    for invalid_ref in queue_ref_resolution.get("invalid_refs", []) or []:
        if isinstance(invalid_ref, Mapping):
            add_error(
                "step3_simulation_queue_ref.invalid_run_local_path",
                "Step3 simulation queue refs must be run-local relative paths without parent traversal",
                actual=invalid_ref,
            )
    if core_present and not artifact_refs[CONTROL_PLANE_STEP3_QUEUE_ARTIFACT_NAME]["exists"]:
        queue_ref_sources = _search_admission_queue_ref_candidates(loaded)
        if queue_ref_sources:
            add_error(
                CONTROL_PLANE_STEP3_QUEUE_ARTIFACT_NAME,
                "Step5 must inspect the current Step3 simulation queue before trusting search/admission sidecars",
                actual={"expected_refs": queue_ref_sources},
            )
    recomputed_queue_validation = _recompute_step3_queue_validation(
        loaded,
        queue_rel_path,
    )
    if recomputed_queue_validation and recomputed_queue_validation.get("valid") is not True:
        add_error(
            "step3_admission_queue_recomputed_validation.valid",
            "Step5 recomputed Step3 admission queue validation from current artifacts and it did not pass",
            actual={
                "valid": recomputed_queue_validation.get("valid"),
                "status": recomputed_queue_validation.get("status"),
                "error_count": recomputed_queue_validation.get("error_count"),
            },
        )
    recomputed_search_validation = _recompute_search_iteration_plan_validation(loaded)
    if recomputed_search_validation and recomputed_search_validation.get("valid") is not True:
        add_error(
            "search_iteration_plan_recomputed_validation.valid",
            "Step5 recomputed search iteration plan validation from the current artifact and it did not pass",
            actual={
                "valid": recomputed_search_validation.get("valid"),
                "status": recomputed_search_validation.get("status"),
                "error_count": recomputed_search_validation.get("error_count"),
            },
        )

    search_validation_present = artifact_refs["search_iteration_plan_validation.json"]["exists"]
    search_validation = loaded.get("search_iteration_plan_validation.json", {})
    search_status = search_validation.get("status")
    search_valid = search_validation.get("valid")
    if search_validation_present:
        if search_valid is not True:
            add_error(
                "search_iteration_plan_validation.valid",
                "search iteration plan validation must pass before Step5 can trust search/admission claims",
                actual=search_valid,
            )
        if str(search_status).lower() == "failed":
            add_error(
                "search_iteration_plan_validation.status",
                "search iteration plan validation status is failed",
                actual=search_status,
            )
        if search_validation.get("trusted_final_claim") is True:
            add_error(
                "search_iteration_plan_validation.trusted_final_claim",
                "validation artifacts cannot claim final trust",
                actual=True,
            )
    step3_queue_validation_present = artifact_refs["step3_admission_queue_validation.json"]["exists"]
    step3_queue_validation = loaded.get("step3_admission_queue_validation.json", {})
    step3_status = step3_queue_validation.get("status")
    step3_valid = step3_queue_validation.get("valid")
    if step3_queue_validation_present:
        if step3_valid is not True:
            add_error(
                "step3_admission_queue_validation.valid",
                "Step3 admission queue validation must pass before Step5 can trust search/admission claims",
                actual=step3_valid,
            )
        if str(step3_status).lower() == "failed":
            add_error(
                "step3_admission_queue_validation.status",
                "Step3 admission queue validation status is failed",
                actual=step3_status,
            )
        if step3_queue_validation.get("trusted_final_claim") is True:
            add_error(
                "step3_admission_queue_validation.trusted_final_claim",
                "validation artifacts cannot claim final trust",
                actual=True,
            )
        sidecar_scope = (
            step3_queue_validation.get("campaign_scope_validation", {})
            if isinstance(step3_queue_validation.get("campaign_scope_validation", {}), Mapping)
            else {}
        )
        if sidecar_scope:
            if sidecar_scope.get("valid") is not True:
                add_error(
                    "step3_admission_queue_validation.campaign_scope_validation.valid",
                    "Step3 admission validation campaign scope summary must pass",
                    actual=sidecar_scope.get("valid"),
                )
        elif core_present:
            if recomputed_queue_validation and recomputed_queue_validation.get("valid") is True:
                add_warning(
                    "step3_admission_queue_validation.campaign_scope_validation",
                    (
                        "Older Step3 admission validation sidecar is missing "
                        "campaign_scope_validation; Step5 used freshly "
                        "recomputed current-artifact validation instead."
                    ),
                )
            else:
                add_error(
                    "step3_admission_queue_validation.campaign_scope_validation",
                    "Step3 admission validation must include campaign_scope_validation when search/admission artifacts are present",
                )

    campaign_plan = loaded.get("campaign_search_admission_plan.json", {})
    campaign_status = campaign_plan.get("status")
    campaign_admission_status = campaign_plan.get("admission_status")
    execution_allowed = campaign_plan.get("execution_allowed")
    trusted_final_claim = campaign_plan.get("trusted_final_claim")
    release_completion_eligible = campaign_plan.get("release_completion_eligible")
    hidden_evidence_fanout_allowed = campaign_plan.get("hidden_evidence_fanout_allowed")
    broad_evidence_run = campaign_plan.get("broad_evidence_run")
    top_k_queue_provenance_only = campaign_plan.get("top_k_queue_provenance_only")
    if campaign_plan:
        if str(campaign_status).lower() in {
            "blocked",
            "failed",
            "invalid",
            "partial_blocked_not_complete",
            "untrusted",
        }:
            add_error(
                "campaign_search_admission_plan.status",
                "campaign search admission plan is blocked or incomplete",
                actual=campaign_status,
            )
        if execution_allowed is True:
            add_error(
                "campaign_search_admission_plan.execution_allowed",
                "campaign search admission plans cannot directly authorize Step3 execution",
                actual=True,
            )
        if trusted_final_claim is True:
            add_error(
                "campaign_search_admission_plan.trusted_final_claim",
                "campaign search admission plans cannot upgrade final trust",
                actual=True,
            )
        if release_completion_eligible is True:
            add_error(
                "campaign_search_admission_plan.release_completion_eligible",
                "campaign search admission plans cannot mark release completion eligibility",
                actual=True,
            )
        if hidden_evidence_fanout_allowed is True:
            add_error(
                "campaign_search_admission_plan.hidden_evidence_fanout_allowed",
                "campaign search admission plans cannot authorize hidden evidence fanout",
                actual=True,
            )
        if broad_evidence_run is True:
            add_error(
                "campaign_search_admission_plan.broad_evidence_run",
                "campaign search admission plans cannot mark broad evidence execution",
                actual=True,
            )
        if top_k_queue_provenance_only is False:
            add_error(
                "campaign_search_admission_plan.top_k_queue_provenance_only",
                "campaign search admission plans must remain top-k provenance only when the field is present",
                actual=False,
            )

    campaign_evaluation_plan = loaded.get("campaign_evaluation_plan.json", {})
    if campaign_evaluation_plan:
        if campaign_evaluation_plan.get("trusted_final_claim") is True:
            add_error(
                "campaign_evaluation_plan.trusted_final_claim",
                "campaign evaluation plans cannot upgrade final trust",
                actual=True,
            )
        if campaign_evaluation_plan.get("release_completion_eligible") is True:
            add_error(
                "campaign_evaluation_plan.release_completion_eligible",
                "campaign evaluation plans cannot mark release completion eligibility",
                actual=True,
            )

    return {
        "schema_version": "dse.final_report.search_admission_validation.v1",
        "present": present,
        "status": "failed" if errors else "passed" if present else "not_present",
        "valid": False if errors else True,
        "artifact_refs": artifact_refs,
        "scope_consensus": scope_consensus,
        "search_iteration_plan_recomputed_validation": recomputed_search_validation,
        "step3_admission_queue_recomputed_validation": recomputed_queue_validation,
        "campaign_id": (
            campaign_plan.get("campaign_id")
            or campaign_evaluation_plan.get("campaign_id")
            or None
        ),
        "workload_run_id": (
            campaign_plan.get("workload_run_id")
            or campaign_evaluation_plan.get("workload_run_id")
            or None
        ),
        "trial_id": (
            campaign_plan.get("trial_id")
            or campaign_evaluation_plan.get("trial_id")
            or None
        ),
        "search_iteration_plan_validation_status": search_status,
        "search_iteration_plan_validation_valid": search_valid,
        "search_iteration_plan_validation_error_count": search_validation.get("error_count"),
        "step3_admission_queue_validation_status": step3_status,
        "step3_admission_queue_validation_valid": step3_valid,
        "step3_admission_queue_validation_error_count": step3_queue_validation.get("error_count"),
        "campaign_search_admission_plan_status": campaign_status,
        "campaign_admission_status": campaign_admission_status,
        "execution_allowed": execution_allowed,
        "trusted_final_claim": trusted_final_claim,
        "release_completion_eligible": release_completion_eligible,
        "hidden_evidence_fanout_allowed": hidden_evidence_fanout_allowed,
        "broad_evidence_run": broad_evidence_run,
        "top_k_queue_provenance_only": top_k_queue_provenance_only,
        "error_count": len(errors),
        "errors": errors,
        "warning_count": len(warnings),
        "warnings": warnings,
        "resume_next_actions": list(campaign_plan.get("resume_next_actions", []) or []),
        "claim_boundary": (
            "Step5 reports search/admission validation as control-plane evidence only. "
            "Invalid search-iteration validation, invalid Step3 admission-queue "
            "validation, or blocked campaign admission prevents trusted final "
            "search/admission claims."
        ),
    }


def _step2_search_provenance_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Expose Step2 search/admission artifacts in Step5 without upgrading claims."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    payloads: Dict[str, Dict[str, Any]] = {}
    for key, artifact_name in STEP2_SEARCH_PROVENANCE_ARTIFACT_KEYS.items():
        rel_path, entry = _find_indexed_artifact(evidence_index, artifact_name)
        payload = _load_json(run_dir / rel_path) if rel_path else {}
        artifact_refs[key] = {
            "artifact": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
            "schema_version": payload.get("schema_version"),
        }
        payloads[key] = payload

    search_space = payloads["architecture_search_space"]
    generation = payloads["architecture_candidate_generation_report"]
    screening = payloads["architecture_screening_report"]
    checkpoint = payloads["search_checkpoint"]
    top_k = payloads["top_k_candidate_queue"]
    trial_ledger = payloads["trial_state_ledger"]
    step3_queue = payloads["step3_simulation_queue"]
    required_keys = (
        "architecture_search_space",
        "architecture_candidate_generation_report",
        "architecture_screening_report",
        "step3_simulation_queue",
    )
    present = any(ref["exists"] for ref in artifact_refs.values())
    required_present = all(artifact_refs[key]["exists"] for key in required_keys)
    return {
        "schema_version": "dse.final_report.step2_search_provenance.v1",
        "present": present,
        "status": (
            "step2_search_provenance_indexed"
            if required_present
            else "partial_step2_search_provenance_indexed"
            if present
            else "not_present"
        ),
        "required_artifacts_present": required_present,
        "artifact_count": sum(1 for ref in artifact_refs.values() if ref["exists"]),
        "artifacts": artifact_refs,
        "search_space": {
            "artifact": artifact_refs["architecture_search_space"]["artifact"],
            "search_space_hash": search_space.get("search_space_hash")
            or generation.get("search_space_hash")
            or checkpoint.get("search_space_hash")
            or trial_ledger.get("search_space_hash"),
            "freeze_gate_status": (
                search_space.get("freeze_gate_verdict", {})
                if isinstance(search_space.get("freeze_gate_verdict", {}), Mapping)
                else {}
            ).get("status"),
            "search_policy_name": search_space.get("search_policy_name")
            or generation.get("search_policy_name")
            or screening.get("search_policy_name")
            or checkpoint.get("search_policy_name"),
            "search_policy_problem_id": search_space.get("search_policy_problem_id")
            or generation.get("search_policy_problem_id")
            or screening.get("search_policy_problem_id")
            or checkpoint.get("search_policy_problem_id"),
            "search_policy_proposed_count": search_space.get("search_policy_proposed_count")
            or generation.get("search_policy_proposed_count")
            or screening.get("search_policy_proposed_count")
            or checkpoint.get("search_policy_proposed_count"),
            "search_policy_budget": search_space.get("search_policy_budget")
            or generation.get("search_policy_budget")
            or top_k.get("search_policy_budget"),
        },
        "candidate_generation": {
            "artifact": artifact_refs["architecture_candidate_generation_report"]["artifact"],
            "architecture_candidate_count": generation.get("architecture_candidate_count"),
            "mapping_candidate_count": generation.get("mapping_candidate_count"),
            "search_policy_candidate_count": generation.get("search_policy_candidate_count"),
            "top_k_candidate_count": generation.get("top_k_candidate_count"),
            "all_generated_candidates_have_parameter_hash": generation.get(
                "all_generated_candidates_have_parameter_hash"
            ),
            "search_policy_provenance_only": bool(generation.get("search_policy_provenance_only", False)),
        },
        "screening": {
            "artifact": artifact_refs["architecture_screening_report"]["artifact"],
            "screened_candidate_count": screening.get("screened_candidate_count"),
            "promoted_candidate_count": screening.get("promoted_candidate_count"),
            "step3_queue_entry_count": screening.get("step3_queue_entry_count"),
            "top_k_provenance_entry_count": screening.get("top_k_provenance_entry_count"),
            "top_k_queue_provenance_only": bool(screening.get("top_k_queue_provenance_only", False)),
            "trusted_final_claim": False,
        },
        "admission_queue": {
            "artifact": artifact_refs["step3_simulation_queue"]["artifact"],
            "queue_mode": step3_queue.get("queue_mode"),
            "entry_count": step3_queue.get("entry_count"),
            "admitted_candidate_count": step3_queue.get("admitted_candidate_count"),
            "non_admitted_candidate_count": step3_queue.get("non_admitted_candidate_count"),
            "trusted_final_claim": False,
            "release_completion_eligible": False,
        },
        "top_k_queue": {
            "artifact": artifact_refs["top_k_candidate_queue"]["artifact"],
            "queue_mode": top_k.get("queue_mode"),
            "entry_count": top_k.get("entry_count"),
            "provenance_only": bool(top_k.get("provenance_only", True)),
            "execution_order_suggestion_only": bool(top_k.get("execution_order_suggestion_only", True)),
            "trusted_final_claim": False,
        },
        "trial_state_ledger": {
            "artifact": artifact_refs["trial_state_ledger"]["artifact"],
            "candidate_count": trial_ledger.get("candidate_count"),
            "promoted_candidate_count": trial_ledger.get("promoted_candidate_count"),
            "queued_entry_count": trial_ledger.get("queued_entry_count"),
            "state_counts": trial_ledger.get("state_counts", {}),
            "trusted_final_claim": False,
        },
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "claim_boundary": (
            "Step2 search/admission provenance explains how candidates entered the "
            "Step3 queue. It is replay and audit evidence only; it does not prove "
            "Step3 measurements, Step4 claims, global convergence, FPGA/ASIC PPA, "
            "or deliverable completion."
        ),
    }


def _resolve_ledger_artifact_path(
    run_dir: Path,
    path_text: Any,
    *,
    bundle_dir: Any = None,
) -> Path | None:
    """Resolve artifact refs emitted by an optional ledger-attached bundle.

    Ledger refs are often absolute paths because the bundle may live outside the
    Step5 run directory.  Some future ledgers may store paths relative to the
    Step5 directory or relative to their recorded bundle directory, so keep the
    resolver permissive while the claim logic remains fail-closed on existence.
    """

    if not path_text:
        return None
    raw = Path(str(path_text))
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(run_dir / raw)
        # Historical ledger builders may record paths relative to the current
        # repository/process working directory rather than the Step5 run dir.
        candidates.append(raw)
        bundle_raw = Path(str(bundle_dir)) if bundle_dir else None
        if bundle_raw:
            bundle_base = bundle_raw if bundle_raw.is_absolute() else run_dir / bundle_raw
            candidates.append(bundle_base / raw)
            if raw.name:
                candidates.append(bundle_base / raw.name)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0] if candidates else None


def _dft_evidence_ledger_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional DFT ledger artifacts for Step5 without upgrading claims."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_LEDGER_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    ledger = loaded.get("per_candidate_evidence_ledger.json", {})
    ledger_present = bool(ledger)
    release_report = loaded.get("release_report.json", {})
    eda = loaded.get("eda_all_candidate_evidence.json", {})
    matrix_rel_path, matrix_entry = _find_indexed_artifact(
        evidence_index,
        "dft_hardware_evidence_matrix.json",
    )
    artifact_refs["dft_hardware_evidence_matrix.json"] = {
        "path": matrix_rel_path,
        "exists": bool(matrix_entry.get("exists", False)),
        "sha256": matrix_entry.get("sha256"),
    }
    hardware_matrix = _load_json(run_dir / matrix_rel_path) if matrix_rel_path else {}
    ledger_matrix_ref = (
        eda.get("dft_hardware_evidence_matrix")
        if isinstance(eda.get("dft_hardware_evidence_matrix"), Mapping)
        else {}
    )
    matrix_path = matrix_rel_path
    matrix_resolved_path: Path | None = run_dir / matrix_rel_path if matrix_rel_path else None
    matrix_exists = bool(matrix_entry.get("exists", False))
    matrix_sha = matrix_entry.get("sha256")
    matrix_source = "direct_step5_artifact" if matrix_rel_path else None
    if not hardware_matrix and ledger_matrix_ref:
        eda_artifact_path = artifact_refs.get("eda_all_candidate_evidence.json", {}).get("path")
        eda_bundle_dir = None
        if eda_artifact_path:
            eda_bundle_parent = PurePosixPath(str(eda_artifact_path)).parent
            eda_bundle_dir = str(eda_bundle_parent) if str(eda_bundle_parent) != "." else None
        ledger_matrix_path = _resolve_ledger_artifact_path(
            run_dir,
            ledger_matrix_ref.get("path"),
            bundle_dir=eda_bundle_dir,
        )
        if ledger_matrix_path and ledger_matrix_path.exists() and ledger_matrix_path.is_file():
            try:
                hardware_matrix = _load_json(ledger_matrix_path)
            except (OSError, json.JSONDecodeError):
                hardware_matrix = {}
        if hardware_matrix:
            matrix_path = str(ledger_matrix_ref.get("path") or ledger_matrix_path)
            matrix_resolved_path = ledger_matrix_path
            matrix_exists = True
            matrix_sha = ledger_matrix_ref.get("sha256", ledger_matrix_ref.get("hash"))
            matrix_source = "eda_all_candidate_evidence.dft_hardware_evidence_matrix"
    hardware_matrix_present = bool(hardware_matrix)
    major_kernel_matrix = _major_kernel_matrix_completeness(hardware_matrix)
    release_claim_gate = (
        ledger.get("release_claim_gate")
        if isinstance(ledger.get("release_claim_gate"), Mapping)
        else release_report.get("release_claim_gate")
        if isinstance(release_report.get("release_claim_gate"), Mapping)
        else {}
    )
    evaluation_policy_routing_summary = (
        ledger.get("evaluation_policy_routing_summary")
        if isinstance(ledger.get("evaluation_policy_routing_summary"), Mapping)
        else release_report.get("evaluation_policy_routing_summary")
        if isinstance(release_report.get("evaluation_policy_routing_summary"), Mapping)
        else release_claim_gate.get("evaluation_policy_routing_summary")
        if isinstance(release_claim_gate.get("evaluation_policy_routing_summary"), Mapping)
        else {}
    )
    full_scf_hybrid_bundle = (
        ledger.get("full_scf_hybrid_bundle")
        if isinstance(ledger.get("full_scf_hybrid_bundle"), Mapping)
        else release_report.get("full_scf_hybrid_bundle")
        if isinstance(release_report.get("full_scf_hybrid_bundle"), Mapping)
        else {}
    )
    deliverable_complete = bool(
        release_claim_gate.get(
            "deliverable_complete",
            release_report.get("deliverable_complete", False),
        )
    )
    ic_eda_availability_ref = (
        eda.get("ic_eda_tool_availability")
        if isinstance(eda.get("ic_eda_tool_availability"), Mapping)
        else {}
    )
    ic_eda_availability_path = _resolve_ledger_artifact_path(
        run_dir,
        ic_eda_availability_ref.get("path"),
    )
    ic_eda_availability = (
        _load_json(ic_eda_availability_path)
        if ic_eda_availability_path and ic_eda_availability_path.exists()
        else {}
    )
    ic_eda_attempts_ref = (
        eda.get("ic_eda_tool_attempts")
        if isinstance(eda.get("ic_eda_tool_attempts"), Mapping)
        else {}
    )
    ic_eda_attempts_path = _resolve_ledger_artifact_path(
        run_dir,
        ic_eda_attempts_ref.get("path"),
    )
    ic_eda_attempts = (
        _load_json(ic_eda_attempts_path)
        if ic_eda_attempts_path and ic_eda_attempts_path.exists()
        else {}
    )
    raw_availability_completion_claim = ic_eda_availability.get("completion_claim")
    raw_ic_eda_attempts = (
        ic_eda_attempts if isinstance(ic_eda_attempts, list) else []
    )
    raw_ic_eda_availability_attempts = (
        ic_eda_availability.get("raw_attempts", [])
        if isinstance(ic_eda_availability.get("raw_attempts", []), list)
        else []
    )
    ic_eda_first_verification = None
    first_verification_source = ic_eda_attempts_ref.get("path") if ic_eda_attempts_ref else None
    if raw_ic_eda_attempts:
        first = raw_ic_eda_attempts[0]
        ic_eda_first_verification = dict(first) if isinstance(first, Mapping) else {"value": first}
    elif raw_ic_eda_availability_attempts:
        first = raw_ic_eda_availability_attempts[0]
        if not first_verification_source:
            first_verification_source = "ic_eda_tool_availability.json.raw_attempts"
        ic_eda_first_verification = dict(first) if isinstance(first, Mapping) else {"value": first}
    availability_payload_claim_boundary_valid = bool(
        ic_eda_availability
        and raw_availability_completion_claim == "availability_only_not_kernel_ppa"
        and ic_eda_availability.get("kernel_ppa_evidence") is not True
        and ic_eda_availability.get("hardware_completion_eligible") is not True
        and ic_eda_availability.get("deliverable_complete") is not True
    )
    raw_transcript_refs = (
        ic_eda_availability.get("raw_command_transcript_refs", []) or []
        if isinstance(ic_eda_availability.get("raw_command_transcript_refs", []), list)
        else []
    )
    valid_transcript_refs = [
        dict(ref) for ref in raw_transcript_refs if _valid_ic_eda_transcript_ref(ref)
    ]
    matrix_ref = (
        {
            "path": matrix_path,
            "resolved_path": str(matrix_resolved_path) if matrix_resolved_path else None,
            "exists": matrix_exists,
            "sha256": matrix_sha,
            "source": matrix_source,
            "status": hardware_matrix.get("status"),
            "trusted": bool(hardware_matrix.get("trusted", False)),
            "hardware_completion_eligible": bool(
                hardware_matrix.get("hardware_completion_eligible", False)
            ),
            "matrix_source": hardware_matrix.get("source"),
            "candidate_count": hardware_matrix.get("candidate_count"),
            "unit_count": hardware_matrix.get("unit_count"),
            "claim_boundary": hardware_matrix.get("claim_boundary"),
        }
        if hardware_matrix
        else ledger_matrix_ref
    )
    matrix_status = major_kernel_matrix["status"]
    matrix_trusted = bool(major_kernel_matrix["trusted"])
    eda_summary = {
        "artifact": artifact_refs.get("eda_all_candidate_evidence.json", {}),
        "status": eda.get("status"),
        "tool_availability_status": eda.get("tool_availability_status"),
        "major_kernel_matrix_status": matrix_status,
        "major_kernel_matrix_trusted": matrix_trusted,
        "attached_hardware_evidence_structurally_ready": bool(
            eda.get("attached_hardware_evidence_structurally_ready", False)
            or major_kernel_matrix["trusted"]
        ),
        "hardware_release_gate_eligible": bool(
            eda.get("hardware_release_gate_eligible", False)
            or release_claim_gate.get("hardware_release_gate_eligible", False)
            or (
                hardware_matrix.get("trusted", False)
                and hardware_matrix.get("hardware_completion_eligible", False)
                and hardware_matrix.get("source") == "dft_hardware_closure_release_gate"
            )
        ),
        "ledger_candidate_claims_eligible": release_claim_gate.get("ledger_candidate_claims_eligible"),
        "candidate_claim_requirement_satisfied": release_claim_gate.get(
            "candidate_claim_requirement_satisfied"
        ),
        "candidate_claim_requirement_source": release_claim_gate.get("candidate_claim_requirement_source"),
        "hardware_completion_eligible": bool(
            major_kernel_matrix["hardware_completion_eligible"]
            or (
                eda.get("hardware_completion_eligible", False)
                and major_kernel_matrix["trusted"]
            )
        ),
        "ic_eda_tool_availability": eda.get("ic_eda_tool_availability"),
        "ic_eda_tool_availability_resolved_path": (
            str(ic_eda_availability_path) if ic_eda_availability_path else None
        ),
        "ic_eda_tool_availability_payload_status": ic_eda_availability.get("status"),
        "ic_eda_tool_availability_all_required_tools_available": ic_eda_availability.get(
            "all_required_tools_available"
        ),
        "ic_eda_tool_availability_required_tools": ic_eda_availability.get("required_tools", []),
        "ic_eda_tool_availability_file_list": {
            "availability": (
                {
                    "path": ic_eda_availability_ref.get("path"),
                    "exists": bool(
                        ic_eda_availability_path and ic_eda_availability_path.exists()
                    ),
                    "sha256": ic_eda_availability_ref.get("sha256"),
                }
                if ic_eda_availability_ref
                else None
            ),
            "attempts": (
                {
                    "path": ic_eda_attempts_ref.get("path"),
                    "exists": bool(ic_eda_attempts_path and ic_eda_attempts_path.exists()),
                    "sha256": ic_eda_attempts_ref.get("sha256"),
                }
                if ic_eda_attempts_ref
                else None
            ),
        },
        "ic_eda_tool_availability_tool_count": len(ic_eda_availability.get("tool_rows", []) or [])
        if isinstance(ic_eda_availability.get("tool_rows", []), list)
        else 0,
        "ic_eda_tool_availability_raw_attempt_count": len(ic_eda_availability.get("raw_attempts", []) or [])
        if isinstance(ic_eda_availability.get("raw_attempts", []), list)
        else 0,
        "ic_eda_tool_availability_first_verification": ic_eda_first_verification,
        "ic_eda_tool_availability_first_verification_source": first_verification_source,
        "ic_eda_tool_availability_raw_transcript_refs": valid_transcript_refs,
        "ic_eda_tool_availability_raw_transcript_ref_count": len(valid_transcript_refs),
        "ic_eda_tool_availability_transcript_ref_malformed_count": (
            len(raw_transcript_refs) - len(valid_transcript_refs)
        ),
        "ic_eda_tool_availability_artifact_role": ic_eda_availability.get("artifact_role"),
        "ic_eda_tool_availability_raw_completion_claim": raw_availability_completion_claim,
        "ic_eda_tool_availability_completion_claim": (
            "availability_only_not_kernel_ppa" if ic_eda_availability else None
        ),
        "ic_eda_tool_availability_payload_claim_boundary_valid": (
            availability_payload_claim_boundary_valid
        ),
        "ic_eda_tool_availability_payload_claim_upgrade_detected": bool(
            ic_eda_availability and not availability_payload_claim_boundary_valid
        ),
        "ic_eda_tool_availability_kernel_ppa_evidence": False,
        "ic_eda_tool_availability_hardware_completion_eligible": False,
        "ic_eda_tool_availability_deliverable_complete": False,
        "dft_hardware_evidence_matrix": matrix_ref,
        "major_kernel_matrix": major_kernel_matrix,
        "claim_boundary": (
            (eda.get("hardware_evidence_attachment_policy", {}) or {}).get("claim_boundary")
            if isinstance(eda.get("hardware_evidence_attachment_policy", {}), Mapping)
            else eda.get("claim_boundary") or hardware_matrix.get("claim_boundary")
        ),
    }
    present = ledger_present
    return {
        "schema_version": "dse.final_report.dft_evidence_ledger.v1",
        "present": present,
        "ledger_present": ledger_present,
        "hardware_matrix_present": hardware_matrix_present,
        "status": (
            "audit_artifacts_present"
            if ledger_present
            else "hardware_matrix_only"
            if hardware_matrix_present
            else "not_present"
        ),
        "artifacts": artifact_refs,
        "release_id": ledger.get("release_id", release_report.get("release_id")),
        "legal_candidate_count": ledger.get(
            "legal_candidate_count",
            release_report.get("legal_candidate_count"),
        ),
        "release_claim_gate": release_claim_gate,
        "evaluation_policy_routing_summary": evaluation_policy_routing_summary,
        "full_scf_hybrid_bundle": full_scf_hybrid_bundle,
        "deliverable_complete": deliverable_complete,
        "eda_summary": eda_summary,
        "major_kernel_matrix": major_kernel_matrix,
        "trusted_final_claim": False,
        "completion_claim": "blocked" if present else "not_applicable",
        "claim_boundary": (
            "DFT ledger artifacts are cited as Step5 audit/reporting evidence only. "
            "They do not upgrade Step4 trust, do not prove full-SCF completion, "
            "and do not create FPGA/ASIC PPA claims unless the per-kernel and "
            "per-candidate hard evidence gates pass."
        ),
    }


def _dft_trial_state_ledger_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional DFT trial-state ledger artifacts without claim upgrade."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_TRIAL_LEDGER_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    ledger = loaded.get("dft_trial_state_ledger.json", {})
    transition_report = loaded.get("dft_trial_transition_report.json", {})
    artifact_refs_report = loaded.get("dft_trial_artifact_refs.json", {})
    validation = loaded.get("dft_trial_state_ledger_validation.json", {})
    present = bool(ledger)
    blocked_trial_count = int(ledger.get("blocked_trial_count", 0) or 0) if ledger else 0
    rejected_trial_count = int(ledger.get("rejected_trial_count", 0) or 0) if ledger else 0
    reported_deliverable_complete = bool(ledger.get("deliverable_complete", False))
    reported_completion_eligible = bool(ledger.get("completion_eligible", False))
    validation_valid = validation.get("valid")
    deliverable_complete = False
    completion_eligible = False
    status = (
        "fail_closed_trial_ledger_present"
        if present
        and validation_valid is True
        and not reported_deliverable_complete
        and not reported_completion_eligible
        else "invalid_trial_ledger_claim_upgrade"
        if present
        and validation_valid is True
        and (reported_deliverable_complete or reported_completion_eligible)
        else "invalid_trial_ledger"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_trial_state_ledger.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "campaign_id": ledger.get("campaign_id"),
        "workload_run_id": ledger.get("workload_run_id"),
        "candidate_count": ledger.get("candidate_count"),
        "release_trial_count": ledger.get("release_trial_count"),
        "exploratory_trial_count": ledger.get("exploratory_trial_count"),
        "blocked_trial_count": blocked_trial_count,
        "rejected_trial_count": rejected_trial_count,
        "selected_trial_count": ledger.get("selected_trial_count"),
        "reported_completion_eligible": reported_completion_eligible,
        "reported_deliverable_complete": reported_deliverable_complete,
        "completion_eligible": completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
            "warning_count": len(validation.get("warnings", []) or []) if validation else None,
        },
        "transition_report": {
            "present": bool(transition_report),
            "status": transition_report.get("status"),
            "trial_count": transition_report.get("trial_count"),
            "transition_row_count": len(transition_report.get("transition_rows", []) or [])
            if isinstance(transition_report.get("transition_rows", []), list)
            else None,
        },
        "artifact_refs_report": {
            "present": bool(artifact_refs_report),
            "status": artifact_refs_report.get("status"),
            "campaign_artifact_ref_count": len(artifact_refs_report.get("campaign_artifact_refs", []) or [])
            if isinstance(artifact_refs_report.get("campaign_artifact_refs", []), list)
            else None,
            "trial_artifact_ref_count": len(artifact_refs_report.get("trial_artifact_refs", []) or [])
            if isinstance(artifact_refs_report.get("trial_artifact_refs", []), list)
            else None,
            "registry": artifact_refs_report.get("registry", {}),
        },
        "blocked_reasons": list(ledger.get("blocked_reasons", []) or []) if isinstance(ledger.get("blocked_reasons", []), list) else [],
        "next_actions": list(ledger.get("next_actions", []) or []) if isinstance(ledger.get("next_actions", []), list) else [],
        "trusted_final_claim": False,
        "completion_claim": (
            "blocked" if present and not deliverable_complete else "deliverable_complete" if deliverable_complete else "not_applicable"
        ),
        "claim_boundary": (
            "DFT trial-state ledger artifacts are Campaign/WorkloadRun/Trial "
            "orchestration and audit evidence only. They prove ID propagation, "
            "legal transitions, artifact refs, and blockers, but do not upgrade "
            "Step4 trust, numerical correctness, FPGA/ASIC PPA, trusted Pareto, "
            "or deliverable completion."
        ),
    }


def _dft_candidate_binding_map_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional DFT candidate-binding artifacts without claim upgrade."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_CANDIDATE_BINDING_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    binding_map = loaded.get("dft_candidate_binding_map.json", {})
    validation = loaded.get("dft_candidate_binding_map_validation.json", {})
    present = bool(binding_map)
    reported_deliverable_complete = bool(binding_map.get("deliverable_complete", False))
    reported_completion_eligible = bool(binding_map.get("completion_eligible", False))
    validation_valid = validation.get("valid")
    deliverable_complete = False
    completion_eligible = False
    status = (
        "fail_closed_candidate_binding_map_present"
        if present and validation_valid is True and not reported_deliverable_complete and not reported_completion_eligible
        else "invalid_candidate_binding_map"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_candidate_binding_map.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "workload_suite_id": binding_map.get("workload_suite_id"),
        "release_id": binding_map.get("release_id"),
        "search_candidate_count": binding_map.get("search_candidate_count"),
        "legal_release_candidate_count": binding_map.get("legal_release_candidate_count"),
        "bound_candidate_count": binding_map.get("bound_candidate_count"),
        "unmatched_candidate_count": binding_map.get("unmatched_candidate_count"),
        "unique_release_candidate_count": binding_map.get("unique_release_candidate_count"),
        "duplicate_release_candidate_ids": list(binding_map.get("duplicate_release_candidate_ids", []) or [])
        if isinstance(binding_map.get("duplicate_release_candidate_ids", []), list)
        else [],
        "reported_completion_eligible": reported_completion_eligible,
        "reported_deliverable_complete": reported_deliverable_complete,
        "completion_eligible": completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "blocked" if present and not deliverable_complete else "deliverable_complete" if deliverable_complete else "not_applicable"
        ),
        "claim_boundary": (
            binding_map.get("claim_boundary")
            or "DFT candidate binding maps are heuristic ID-provenance metadata only; they cannot upgrade numerical correctness, trusted Pareto, FPGA/ASIC PPA, or deliverable completion."
        ),
    }


def _dft_hardware_completion_workplan_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional DFT hardware-completion workplan artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_COMPLETION_WORKPLAN_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    workplan = loaded.get("dft_hardware_completion_workplan.json", {})
    validation = loaded.get("dft_hardware_completion_workplan_validation.json", {})
    present = bool(workplan)
    hardware_completion_eligible = bool(workplan.get("hardware_completion_eligible", False))
    deliverable_complete = bool(workplan.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    status = (
        "fail_closed_hardware_completion_workplan_present"
        if present and validation_valid is True and not hardware_completion_eligible and not deliverable_complete
        else "invalid_hardware_completion_workplan"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_completion_workplan.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": workplan.get("release_id"),
        "candidate_count": workplan.get("candidate_count"),
        "major_kernel_count": workplan.get("major_kernel_count"),
        "required_stage_ids": list(workplan.get("required_stage_ids", []) or [])
        if isinstance(workplan.get("required_stage_ids", []), list)
        else [],
        "required_work_item_count": workplan.get("required_work_item_count"),
        "blocked_work_item_count": workplan.get("blocked_work_item_count"),
        "candidate_specific_evidence_present_count": workplan.get("candidate_specific_evidence_present_count"),
        "shared_microkernel_smoke_stage_present_count": workplan.get("shared_microkernel_smoke_stage_present_count"),
        "blocker_ids": list(workplan.get("blocker_ids", []) or []) if isinstance(workplan.get("blocker_ids", []), list) else [],
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "blocked" if present and not deliverable_complete else "deliverable_complete" if deliverable_complete else "not_applicable"
        ),
        "claim_boundary": (
            workplan.get("claim_boundary")
            or "DFT hardware completion workplans are execution scheduling evidence only; they cannot upgrade numerical correctness, trusted Pareto, FPGA/ASIC PPA, or deliverable completion."
        ),
    }


def _dft_hardware_closure_shards_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional DFT hardware closure shard queue artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_CLOSURE_SHARD_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    shards = loaded.get("dft_hardware_closure_shards.json", {})
    validation = loaded.get("dft_hardware_closure_shards_validation.json", {})
    present = bool(shards)
    hardware_completion_eligible = bool(shards.get("hardware_completion_eligible", False))
    deliverable_complete = bool(shards.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    status = (
        "fail_closed_hardware_closure_shards_present"
        if present and validation_valid is True and not hardware_completion_eligible and not deliverable_complete
        else "invalid_hardware_closure_shards"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_shards.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": shards.get("release_id"),
        "candidate_count": shards.get("candidate_count"),
        "major_kernel_count": shards.get("major_kernel_count"),
        "unit_count": shards.get("unit_count"),
        "shard_count": shards.get("shard_count"),
        "max_units_per_shard": shards.get("max_units_per_shard"),
        "work_item_count": shards.get("work_item_count"),
        "blocked_work_item_count": shards.get("blocked_work_item_count"),
        "candidate_specific_bundle_count": shards.get("candidate_specific_bundle_count"),
        "candidate_specific_evidence_present_count": shards.get("candidate_specific_evidence_present_count"),
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "blocked" if present and not deliverable_complete else "deliverable_complete" if deliverable_complete else "not_applicable"
        ),
        "claim_boundary": (
            shards.get("claim_boundary")
            or "DFT hardware closure shards are parallel queue metadata only; they cannot upgrade numerical correctness, trusted Pareto, FPGA/ASIC PPA, or deliverable completion."
        ),
    }


def _dft_hardware_closure_packets_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional DFT per-shard closure packet/runbook artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_CLOSURE_PACKET_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    packets = loaded.get("dft_hardware_closure_packet_index.json", {})
    validation = loaded.get("dft_hardware_closure_packet_index_validation.json", {})
    present = bool(packets)
    hardware_completion_eligible = bool(packets.get("hardware_completion_eligible", False))
    deliverable_complete = bool(packets.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    packet_summaries = packets.get("packets", []) if isinstance(packets.get("packets", []), list) else []
    command_template_ids = sorted({
        str(template_id)
        for packet in packet_summaries
        if isinstance(packet, Mapping)
        for template_id in (packet.get("command_template_ids", []) or [])
    })
    packet_artifact_refs = [
        {
            "packet_id": packet.get("packet_id"),
            "shard_id": packet.get("shard_id"),
            "packet_json": packet.get("packet_json"),
            "runbook_md": packet.get("runbook_md"),
        }
        for packet in packet_summaries
        if isinstance(packet, Mapping)
    ]
    status = (
        "fail_closed_hardware_closure_packets_present"
        if present and validation_valid is True and not hardware_completion_eligible and not deliverable_complete
        else "invalid_hardware_closure_packets"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_packets.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": packets.get("release_id"),
        "candidate_count": packets.get("candidate_count"),
        "major_kernel_count": packets.get("major_kernel_count"),
        "shard_count": packets.get("shard_count"),
        "packet_count": packets.get("packet_count"),
        "unit_count": packets.get("unit_count"),
        "work_item_count": packets.get("work_item_count"),
        "blocked_work_item_count": packets.get("blocked_work_item_count"),
        "expected_evidence_file_count": packets.get("expected_evidence_file_count"),
        "command_template_ids": command_template_ids,
        "packet_artifact_refs": packet_artifact_refs,
        "candidate_specific_bundle_count": packets.get("candidate_specific_bundle_count"),
        "candidate_specific_evidence_present_count": packets.get("candidate_specific_evidence_present_count"),
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "invalid_claim_upgrade" if present and deliverable_complete else "blocked" if present else "not_applicable"
        ),
        "claim_boundary": (
            packets.get("claim_boundary")
            or "DFT hardware closure packets and runbooks are execution instructions only; they cannot upgrade numerical correctness, trusted Pareto, FPGA/ASIC PPA, or deliverable completion."
        ),
    }


def _dft_hardware_closure_candidate_bundles_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional per-candidate closure bundle-template artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_CLOSURE_CANDIDATE_BUNDLE_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    bundles = loaded.get("dft_hardware_closure_candidate_bundle_index.json", {})
    validation = loaded.get("dft_hardware_closure_candidate_bundle_index_validation.json", {})
    status_artifact = loaded.get("dft_hardware_closure_candidate_bundle_status.json", {})
    present = bool(bundles)
    hardware_completion_eligible = bool(bundles.get("hardware_completion_eligible", False))
    deliverable_complete = bool(bundles.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    bundle_rows = bundles.get("bundles", []) if isinstance(bundles.get("bundles", []), list) else []
    status = (
        "fail_closed_candidate_bundle_templates_present"
        if present
        and validation_valid is True
        and not hardware_completion_eligible
        and not deliverable_complete
        and int(bundles.get("raw_evidence_file_count", 0) or 0) == 0
        else "invalid_candidate_bundle_templates"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_candidate_bundles.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": bundles.get("release_id"),
        "candidate_count": bundles.get("candidate_count"),
        "major_kernel_count": bundles.get("major_kernel_count"),
        "bundle_count": bundles.get("bundle_count"),
        "expected_evidence_file_count": bundles.get("expected_evidence_file_count"),
        "raw_evidence_file_count": bundles.get("raw_evidence_file_count"),
        "bundle_template_only": present and int(bundles.get("raw_evidence_file_count", 0) or 0) == 0,
        "bundle_status": status_artifact.get("status"),
        "bundle_refs": [
            {
                "unit_id": row.get("unit_id"),
                "candidate_id": row.get("candidate_id"),
                "kernel_id": row.get("kernel_id"),
                "candidate_bundle": row.get("candidate_bundle"),
                "expected_evidence_file_count": row.get("expected_evidence_file_count"),
                "raw_evidence_file_count": row.get("raw_evidence_file_count"),
                "status": row.get("status"),
            }
            for row in bundle_rows[:20]
            if isinstance(row, Mapping)
        ],
        "bundle_ref_count": len(bundle_rows),
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "invalid_claim_upgrade" if present and deliverable_complete else "blocked" if present else "not_applicable"
        ),
        "claim_boundary": (
            bundles.get("claim_boundary")
            or "DFT hardware closure candidate bundles are execution metadata and expected-file contracts only; they do not contain raw VCS/HLS, Vivado, DC, timing, area, PPA, or completion evidence."
        ),
    }


def _dft_hardware_closure_unit_provenance_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional candidate/kernel-scoped unit provenance staging."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_CLOSURE_UNIT_PROVENANCE_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    provenance = loaded.get("dft_hardware_closure_unit_provenance_index.json", {})
    validation = loaded.get("dft_hardware_closure_unit_provenance_validation.json", {})
    status_artifact = loaded.get("dft_hardware_closure_unit_provenance_status.json", {})
    present = bool(provenance)
    hardware_completion_eligible = bool(provenance.get("hardware_completion_eligible", False))
    deliverable_complete = bool(provenance.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    raw_stage_count = int(provenance.get("raw_stage_evidence_file_count", 0) or 0)
    unit_rows = provenance.get("units", []) if isinstance(provenance.get("units", []), list) else []
    status = (
        "fail_closed_hardware_closure_unit_provenance_present"
        if present
        and validation_valid is True
        and raw_stage_count == 0
        and not hardware_completion_eligible
        and not deliverable_complete
        else "invalid_hardware_closure_unit_provenance"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_unit_provenance.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": provenance.get("release_id"),
        "candidate_count": provenance.get("candidate_count"),
        "major_kernel_count": provenance.get("major_kernel_count"),
        "staged_unit_count": provenance.get("staged_unit_count"),
        "global_provenance_file_count": provenance.get("global_provenance_file_count"),
        "raw_stage_evidence_file_count": provenance.get("raw_stage_evidence_file_count"),
        "error_count": provenance.get("error_count"),
        "unit_provenance_status": status_artifact.get("status"),
        "unit_refs": [
            {
                "unit_id": row.get("unit_id"),
                "candidate_id": row.get("candidate_id"),
                "kernel_id": row.get("kernel_id"),
                "global_provenance_file_count": row.get("global_provenance_file_count"),
                "raw_stage_evidence_file_count": row.get("raw_stage_evidence_file_count"),
                "status": row.get("status"),
            }
            for row in unit_rows[:20]
            if isinstance(row, Mapping)
        ],
        "unit_ref_count": len(unit_rows),
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "invalid_claim_upgrade" if present and deliverable_complete else "blocked" if present else "not_applicable"
        ),
        "claim_boundary": (
            provenance.get("claim_boundary")
            or "DFT hardware closure unit provenance is candidate/kernel metadata staging only; it contains no raw VCS/HLS, Vivado, DC, timing, area, PPA, Pareto, or deliverable-completion evidence."
        ),
    }


def _dft_hardware_closure_artifact_chain_section(
    run_dir: Path,
    dft_hardware_completion_workplan: Mapping[str, Any],
    dft_hardware_closure_shards: Mapping[str, Any],
    dft_hardware_closure_packets: Mapping[str, Any],
    dft_hardware_closure_candidate_bundles: Mapping[str, Any],
    dft_hardware_closure_unit_provenance: Mapping[str, Any],
) -> Dict[str, Any]:
    """Summarize the machine-linkable Step5 artifact chain."""

    def _section_ref(section: Mapping[str, Any], artifact_name: str) -> Dict[str, Any]:
        artifacts = section.get("artifacts", {})
        ref = artifacts.get(artifact_name, {}) if isinstance(artifacts, Mapping) else {}
        return {
            "path": ref.get("path"),
            "exists": bool(ref.get("exists", False)),
            "sha256": ref.get("sha256"),
        }

    def _load_source_artifacts(ref: Mapping[str, Any]) -> Dict[str, Any]:
        path = ref.get("path")
        if not path:
            return {}
        payload = _load_json(run_dir / str(path))
        source_artifacts = payload.get("source_artifacts", {})
        if not isinstance(source_artifacts, Mapping):
            return {}
        return {
            str(name): {
                "path": item.get("path"),
                "exists": bool(item.get("exists", False)),
                "sha256": item.get("sha256"),
            }
            for name, item in source_artifacts.items()
            if isinstance(item, Mapping)
        }

    def _first_unit_bundle_source_ref(section: Mapping[str, Any]) -> Dict[str, Any]:
        unit_rows = section.get("unit_refs", [])
        if not isinstance(unit_rows, list):
            return {}
        index_ref = {}
        artifacts = section.get("artifacts", {})
        if isinstance(artifacts, Mapping):
            index_ref = artifacts.get("dft_hardware_closure_unit_provenance_index.json", {}) or {}
        index_path = index_ref.get("path")
        if not index_path:
            return {}
        payload = _load_json(run_dir / str(index_path))
        units = payload.get("units", [])
        if not isinstance(units, list):
            return {}
        for unit in units:
            if not isinstance(unit, Mapping):
                continue
            provenance_files = unit.get("provenance_files", {})
            if not isinstance(provenance_files, Mapping):
                continue
            source_bundle = provenance_files.get("source_bundle_manifest.json", {})
            if not isinstance(source_bundle, Mapping) or not source_bundle.get("path"):
                continue
            source_bundle_payload = _load_json(run_dir / str(source_bundle.get("path")))
            source_refs = source_bundle_payload.get("source_refs", [])
            if not isinstance(source_refs, list):
                continue
            for source_ref in source_refs:
                if not isinstance(source_ref, Mapping):
                    continue
                if str(source_ref.get("role", "")) == "candidate_bundle_template":
                    return {
                        "path": source_ref.get("path"),
                        "exists": bool(source_ref.get("exists", False)),
                        "sha256": source_ref.get("sha256"),
                    }
        return {}

    stages = [
        (
            "workplan",
            "dft_hardware_completion_workplan",
            "dft_hardware_completion_workplan.json",
            dft_hardware_completion_workplan,
            "shard_queue",
        ),
        (
            "shard_queue",
            "dft_hardware_closure_shards",
            "dft_hardware_closure_shards.json",
            dft_hardware_closure_shards,
            "packet_index",
        ),
        (
            "packet_index",
            "dft_hardware_closure_packets",
            "dft_hardware_closure_packet_index.json",
            dft_hardware_closure_packets,
            "candidate_bundle_templates",
        ),
        (
            "candidate_bundle_templates",
            "dft_hardware_closure_candidate_bundles",
            "dft_hardware_closure_candidate_bundle_index.json",
            dft_hardware_closure_candidate_bundles,
            "unit_provenance",
        ),
        (
            "unit_provenance",
            "dft_hardware_closure_unit_provenance",
            "dft_hardware_closure_unit_provenance_index.json",
            dft_hardware_closure_unit_provenance,
            None,
        ),
    ]

    chain_rows: list[Dict[str, Any]] = []
    for stage_id, report_key, artifact_name, section, next_stage_id in stages:
        artifact_ref = _section_ref(section, artifact_name)
        row = {
            "stage_id": stage_id,
            "report_key": report_key,
            "artifact_name": artifact_name,
            "artifact_ref": artifact_ref,
            "present": bool(section.get("present", False)),
            "status": section.get("status"),
            "validation_valid": (
                section.get("validation", {}).get("valid")
                if isinstance(section.get("validation", {}), Mapping)
                else None
            ),
            "source_artifacts": _load_source_artifacts(artifact_ref),
            "next_stage_id": next_stage_id,
        }
        if stage_id == "packet_index":
            row["packet_refs"] = list(section.get("packet_artifact_refs", []) or [])
        if stage_id == "candidate_bundle_templates":
            row["bundle_refs"] = list(section.get("bundle_refs", []) or [])
        if stage_id == "unit_provenance":
            row["unit_refs"] = list(section.get("unit_refs", []) or [])
            row["bundle_template_ref"] = _first_unit_bundle_source_ref(section)
        chain_rows.append(row)

    chain_present = all(row["present"] for row in chain_rows)
    chain_linked = chain_present and all(row["artifact_ref"].get("path") for row in chain_rows)
    validation_valid = all(
        row["validation_valid"] is True
        for row in chain_rows
        if row["validation_valid"] is not None
    )
    status = (
        "fail_closed_linked_artifact_chain_present"
        if chain_linked and validation_valid
        else "partial_linked_artifact_chain_present"
        if chain_present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_artifact_chain.v1",
        "present": chain_present,
        "status": status,
        "chain_linked": chain_linked,
        "validation_valid": validation_valid,
        "stages": chain_rows,
        "stage_order": [row["stage_id"] for row in chain_rows],
        "claim_boundary": (
            "The Step5 artifact chain is report-visible provenance only. It can link "
            "workplan, shard queue, packet index, candidate-bundle templates, and "
            "unit provenance, but it cannot upgrade numerical correctness, PPA, "
            "trusted Pareto, or deliverable completion."
        ),
    }


def _dft_hardware_closure_source_flow_plan_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional candidate/kernel source-flow planning artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_CLOSURE_SOURCE_FLOW_PLAN_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    plan = loaded.get("dft_hardware_closure_source_flow_plan.json", {})
    validation = loaded.get("dft_hardware_closure_source_flow_plan_validation.json", {})
    status_artifact = loaded.get("dft_hardware_closure_source_flow_plan_status.json", {})
    present = bool(plan)
    hardware_completion_eligible = bool(plan.get("hardware_completion_eligible", False))
    deliverable_complete = bool(plan.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    passed_stage_count = int(plan.get("passed_stage_count", 0) or 0)
    adjudication_result = plan.get("adjudication_result")
    unit_rows = plan.get("units", []) if isinstance(plan.get("units", []), list) else []
    source_artifacts = (
        plan.get("source_artifacts", {})
        if isinstance(plan.get("source_artifacts", {}), Mapping)
        else {}
    )
    source_flow_map_ref = (
        source_artifacts.get("source_flow_map", {})
        if isinstance(source_artifacts.get("source_flow_map", {}), Mapping)
        else {}
    )
    source_flow_errors = [
        dict(item)
        for item in (plan.get("errors", []) or [])[:20]
        if isinstance(item, Mapping)
    ]
    source_flow_blocker_counts: Dict[str, int] = {}
    materialization_eligible_unit_count = 0
    for row in unit_rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("materialization_eligible") is True and row.get("source_flow_present") is True:
            materialization_eligible_unit_count += 1
        for blocker_id in row.get("blocker_ids", []) or []:
            key = str(blocker_id)
            source_flow_blocker_counts[key] = source_flow_blocker_counts.get(key, 0) + 1
    status = (
        "fail_closed_hardware_closure_source_flow_plan_present"
        if present
        and validation_valid is True
        and adjudication_result == "not_adjudicated_by_source_flow_plan"
        and passed_stage_count == 0
        and not hardware_completion_eligible
        and not deliverable_complete
        else "invalid_hardware_closure_source_flow_plan"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_source_flow_plan.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": plan.get("release_id"),
        "candidate_count": plan.get("candidate_count"),
        "major_kernel_count": plan.get("major_kernel_count"),
        "unit_count": plan.get("unit_count"),
        "planned_unit_count": plan.get("planned_unit_count"),
        "materialization_eligible_unit_count": materialization_eligible_unit_count,
        "source_flow_present_count": plan.get("source_flow_present_count"),
        "source_flow_missing_count": plan.get("source_flow_missing_count"),
        "blocked_unit_count": plan.get("blocked_unit_count"),
        "source_flow_map": {
            "path": source_flow_map_ref.get("path"),
            "exists": source_flow_map_ref.get("exists"),
            "sha256": source_flow_map_ref.get("sha256"),
        },
        "error_count": plan.get("error_count"),
        "errors": source_flow_errors,
        "blocker_id_counts": dict(sorted(source_flow_blocker_counts.items())),
        "blocked_wrong_candidate_reuse_count": plan.get("blocked_wrong_candidate_reuse_count"),
        "blocked_wrong_kernel_reuse_count": plan.get("blocked_wrong_kernel_reuse_count"),
        "blocked_reused_source_flow_count": plan.get("blocked_reused_source_flow_count"),
        "blocked_invalid_manifest_count": plan.get("blocked_invalid_manifest_count"),
        "provenance_mismatch_count": plan.get("provenance_mismatch_count"),
        "adjudication_result": adjudication_result,
        "passed_stage_count": passed_stage_count,
        "source_flow_plan_status": status_artifact.get("status"),
        "unit_refs": [
            {
                "unit_id": row.get("unit_id"),
                "candidate_id": row.get("candidate_id"),
                "kernel_id": row.get("kernel_id"),
                "status": row.get("status"),
                "source_flow_present": row.get("source_flow_present"),
                "materialization_eligible": row.get("materialization_eligible"),
                "source_flow_dir": row.get("source_flow_dir"),
                "blocker_ids": row.get("blocker_ids", []),
            }
            for row in unit_rows[:20]
            if isinstance(row, Mapping)
        ],
        "unit_ref_count": len(unit_rows),
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "invalid_claim_upgrade" if present and deliverable_complete else "blocked" if present else "not_applicable"
        ),
        "claim_boundary": (
            plan.get("claim_boundary")
            or "DFT hardware closure source-flow planning binds source-flow directories to exact candidate/kernel units only; it does not copy raw evidence, parse results, adjudicate hard gates, or upgrade PPA/Pareto/completion claims."
        ),
    }


def _dft_hardware_closure_raw_transcript_registration_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional raw-transcript registration artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_CLOSURE_RAW_TRANSCRIPT_REGISTRATION_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    registration = loaded.get("dft_hardware_closure_raw_transcript_registration.json", {})
    validation = loaded.get("dft_hardware_closure_raw_transcript_registration_validation.json", {})
    status_artifact = loaded.get("dft_hardware_closure_raw_transcript_registration_status.json", {})
    present = bool(registration)
    hardware_completion_eligible = bool(registration.get("hardware_completion_eligible", False))
    deliverable_complete = bool(registration.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    passed_stage_count = int(registration.get("passed_stage_count", 0) or 0)
    adjudication_result = registration.get("adjudication_result")
    unit_rows = registration.get("units", []) if isinstance(registration.get("units", []), list) else []
    status = (
        "fail_closed_hardware_closure_raw_transcript_registration_present"
        if present
        and validation_valid is True
        and adjudication_result == "not_adjudicated_by_raw_transcript_registration"
        and passed_stage_count == 0
        and not hardware_completion_eligible
        and not deliverable_complete
        else "invalid_hardware_closure_raw_transcript_registration"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_raw_transcript_registration.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": registration.get("release_id"),
        "candidate_count": registration.get("candidate_count"),
        "major_kernel_count": registration.get("major_kernel_count"),
        "unit_count": registration.get("unit_count"),
        "registered_unit_count": registration.get("registered_unit_count"),
        "blocked_unit_count": registration.get("blocked_unit_count"),
        "registered_raw_stage_evidence_file_count": registration.get(
            "registered_raw_stage_evidence_file_count"
        ),
        "present_raw_stage_evidence_file_count": registration.get("present_raw_stage_evidence_file_count"),
        "missing_raw_stage_evidence_file_count": registration.get("missing_raw_stage_evidence_file_count"),
        "invalid_raw_stage_evidence_file_count": registration.get("invalid_raw_stage_evidence_file_count"),
        "adjudication_result": adjudication_result,
        "passed_stage_count": passed_stage_count,
        "registration_status": status_artifact.get("status"),
        "unit_refs": [
            {
                "unit_id": row.get("unit_id"),
                "candidate_id": row.get("candidate_id"),
                "kernel_id": row.get("kernel_id"),
                "status": row.get("status"),
                "registered_raw_stage_evidence_file_count": row.get(
                    "registered_raw_stage_evidence_file_count"
                ),
                "present_raw_stage_evidence_file_count": row.get("present_raw_stage_evidence_file_count"),
                "missing_raw_stage_evidence_file_count": row.get("missing_raw_stage_evidence_file_count"),
                "invalid_raw_stage_evidence_file_count": row.get("invalid_raw_stage_evidence_file_count"),
            }
            for row in unit_rows[:20]
            if isinstance(row, Mapping)
        ],
        "unit_ref_count": len(unit_rows),
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "invalid_claim_upgrade" if present and deliverable_complete else "blocked" if present else "not_applicable"
        ),
        "claim_boundary": (
            registration.get("claim_boundary")
            or "DFT hardware closure raw transcript registration records SHA-256 refs for already-present candidate-specific raw files only; it cannot create evidence, parse results, pass hard gates, or upgrade PPA/Pareto/completion claims."
        ),
    }


def _dft_hardware_closure_raw_stage_materialization_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional raw-stage materialization artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    materialization = loaded.get("dft_hardware_closure_raw_stage_materialization.json", {})
    validation = loaded.get("dft_hardware_closure_raw_stage_materialization_validation.json", {})
    status_artifact = loaded.get("dft_hardware_closure_raw_stage_materialization_status.json", {})
    present = bool(materialization)
    hardware_completion_eligible = bool(materialization.get("hardware_completion_eligible", False))
    deliverable_complete = bool(materialization.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    passed_stage_count = int(materialization.get("passed_stage_count", 0) or 0)
    adjudication_result = materialization.get("adjudication_result")
    unit_rows = materialization.get("units", []) if isinstance(materialization.get("units", []), list) else []
    materialization_blocker_ids = sorted(
        {
            str(item.get("blocker_id"))
            for row in unit_rows
            if isinstance(row, Mapping)
            for item in row.get("missing_required_raw_stage_files", []) or []
            if isinstance(item, Mapping) and item.get("blocker_id")
        }
    )
    status = (
        "fail_closed_hardware_closure_raw_stage_materialization_present"
        if present
        and validation_valid is True
        and adjudication_result == "not_adjudicated_by_raw_stage_materialization"
        and passed_stage_count == 0
        and not hardware_completion_eligible
        and not deliverable_complete
        else "invalid_hardware_closure_raw_stage_materialization"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_raw_stage_materialization.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": materialization.get("release_id"),
        "candidate_count": materialization.get("candidate_count"),
        "major_kernel_count": materialization.get("major_kernel_count"),
        "unit_count": materialization.get("unit_count"),
        "materialized_unit_count": materialization.get("materialized_unit_count"),
        "materialized_file_count": materialization.get("materialized_file_count"),
        "missing_required_raw_stage_file_count": materialization.get("missing_required_raw_stage_file_count"),
        "materialization_blocker_ids": materialization_blocker_ids,
        "blocked_unit_count": materialization.get("blocked_unit_count"),
        "adjudication_result": adjudication_result,
        "passed_stage_count": passed_stage_count,
        "materialization_status": status_artifact.get("status"),
        "unit_refs": [
            {
                "unit_id": row.get("unit_id"),
                "candidate_id": row.get("candidate_id"),
                "kernel_id": row.get("kernel_id"),
                "status": row.get("status"),
                "source_flow_dir": row.get("source_flow_dir"),
                "materialized_file_count": row.get("materialized_file_count"),
                "missing_required_raw_stage_file_count": row.get("missing_required_raw_stage_file_count"),
                "blocker_count": row.get("blocker_count"),
                "missing_required_raw_stage_files": [
                    {
                        "stage_id": item.get("stage_id"),
                        "path": item.get("path"),
                        "blocker_id": item.get("blocker_id"),
                    }
                    for item in (row.get("missing_required_raw_stage_files", []) or [])[:5]
                    if isinstance(item, Mapping)
                ],
            }
            for row in unit_rows[:20]
            if isinstance(row, Mapping)
        ],
        "unit_ref_count": len(unit_rows),
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "invalid_claim_upgrade" if present and deliverable_complete else "blocked" if present else "not_applicable"
        ),
        "claim_boundary": (
            materialization.get("claim_boundary")
            or "DFT hardware closure raw-stage materialization copies or wraps existing kernel-flow outputs into packet-expected filenames only; registration, parser, gate adjudication, release completion, and PPA claims remain separate."
        ),
    }


def _dft_hardware_closure_evidence_intake_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional DFT closure evidence intake artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_CLOSURE_EVIDENCE_INTAKE_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    intake = loaded.get("dft_hardware_closure_evidence_intake.json", {})
    validation = loaded.get("dft_hardware_closure_evidence_intake_validation.json", {})
    present = bool(intake)
    hardware_completion_eligible = bool(intake.get("hardware_completion_eligible", False))
    deliverable_complete = bool(intake.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    status = (
        "fail_closed_hardware_closure_evidence_intake_present"
        if present and validation_valid is True and not hardware_completion_eligible and not deliverable_complete
        else "invalid_hardware_closure_evidence_intake"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_evidence_intake.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": intake.get("release_id"),
        "candidate_count": intake.get("candidate_count"),
        "major_kernel_count": intake.get("major_kernel_count"),
        "packet_count": intake.get("packet_count"),
        "unit_count": intake.get("unit_count"),
        "expected_evidence_file_count": intake.get("expected_evidence_file_count"),
        "present_evidence_file_count": intake.get("present_evidence_file_count"),
        "missing_evidence_file_count": intake.get("missing_evidence_file_count"),
        "candidate_bundle_count": intake.get("candidate_bundle_count"),
        "adjudication_status": intake.get("adjudication_status"),
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "blocked" if present and not deliverable_complete else "deliverable_complete" if deliverable_complete else "not_applicable"
        ),
        "claim_boundary": (
            intake.get("claim_boundary")
            or "DFT hardware closure evidence intake checks file presence only; it cannot upgrade numerical correctness, trusted Pareto, FPGA/ASIC PPA, or deliverable completion."
        ),
    }


def _dft_hardware_closure_adjudication_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional DFT hardware closure adjudication artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_CLOSURE_ADJUDICATION_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    adjudication = loaded.get("dft_hardware_closure_adjudication.json", {})
    validation = loaded.get("dft_hardware_closure_adjudication_validation.json", {})
    present = bool(adjudication)
    hardware_completion_eligible = bool(adjudication.get("hardware_completion_eligible", False))
    deliverable_complete = bool(adjudication.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    status = (
        "fail_closed_hardware_closure_adjudication_present"
        if present and validation_valid is True and not hardware_completion_eligible and not deliverable_complete
        else "invalid_hardware_closure_adjudication"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_adjudication.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": adjudication.get("release_id"),
        "candidate_count": adjudication.get("candidate_count"),
        "major_kernel_count": adjudication.get("major_kernel_count"),
        "packet_count": adjudication.get("packet_count"),
        "unit_count": adjudication.get("unit_count"),
        "stage_count": adjudication.get("stage_count"),
        "passed_stage_count": adjudication.get("passed_stage_count"),
        "blocked_stage_count": adjudication.get("blocked_stage_count"),
        "files_present_unadjudicated_stage_count": adjudication.get("files_present_unadjudicated_stage_count"),
        "expected_evidence_file_count": adjudication.get("expected_evidence_file_count"),
        "present_evidence_file_count": adjudication.get("present_evidence_file_count"),
        "missing_evidence_file_count": adjudication.get("missing_evidence_file_count"),
        "candidate_bundle_count": adjudication.get("candidate_bundle_count"),
        "adjudication_result": adjudication.get("adjudication_result"),
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "invalid_claim_upgrade" if present and deliverable_complete else "blocked" if present else "not_applicable"
        ),
        "claim_boundary": (
            adjudication.get("claim_boundary")
            or "DFT hardware closure adjudication is a fail-closed stage ledger; it cannot upgrade numerical correctness, trusted Pareto, FPGA/ASIC PPA, or deliverable completion without parsed candidate-specific evidence."
        ),
    }


def _dft_hardware_closure_parsed_evidence_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional DFT closure parsed-evidence manifest artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_CLOSURE_PARSED_EVIDENCE_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    manifest = loaded.get("dft_hardware_closure_parsed_evidence_manifest.json", {})
    validation = loaded.get("dft_hardware_closure_parsed_evidence_manifest_validation.json", {})
    present = bool(manifest)
    hardware_completion_eligible = bool(manifest.get("hardware_completion_eligible", False))
    deliverable_complete = bool(manifest.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    status = (
        "fail_closed_hardware_closure_parsed_evidence_present"
        if present and validation_valid is True and not hardware_completion_eligible and not deliverable_complete
        else "invalid_hardware_closure_parsed_evidence"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_parsed_evidence.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": manifest.get("release_id"),
        "candidate_count": manifest.get("candidate_count"),
        "major_kernel_count": manifest.get("major_kernel_count"),
        "packet_count": manifest.get("packet_count"),
        "unit_count": manifest.get("unit_count"),
        "stage_count": manifest.get("stage_count"),
        "expected_parsed_result_count": manifest.get("expected_parsed_result_count"),
        "present_parsed_result_count": manifest.get("present_parsed_result_count"),
        "missing_parsed_result_count": manifest.get("missing_parsed_result_count"),
        "valid_parsed_result_count": manifest.get("valid_parsed_result_count"),
        "invalid_parsed_result_count": manifest.get("invalid_parsed_result_count"),
        "parsed_verdict_counts": manifest.get("parsed_verdict_counts"),
        "adjudication_result": manifest.get("adjudication_result"),
        "passed_stage_count": manifest.get("passed_stage_count"),
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "invalid_claim_upgrade" if present and deliverable_complete else "blocked" if present else "not_applicable"
        ),
        "claim_boundary": (
            manifest.get("claim_boundary")
            or "DFT hardware closure parsed-evidence manifests are parser/readiness evidence only; they cannot upgrade hard-gate, PPA, Pareto, or deliverable claims."
        ),
    }


def _dft_hardware_closure_parser_run_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional DFT closure parser-run artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_CLOSURE_PARSER_RUN_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    parser_run = loaded.get("dft_hardware_closure_parser_run.json", {})
    validation = loaded.get("dft_hardware_closure_parser_run_validation.json", {})
    present = bool(parser_run)
    hardware_completion_eligible = bool(parser_run.get("hardware_completion_eligible", False))
    deliverable_complete = bool(parser_run.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    parser_rows = parser_run.get("parser_rows", []) if isinstance(parser_run.get("parser_rows", []), list) else []
    parser_stage_blocker_ids = sorted(
        {
            str(blocker_id)
            for row in parser_rows
            if isinstance(row, Mapping)
            for blocker_id in row.get("stage_blocker_ids", []) or []
            if blocker_id
        }
    )
    parser_status_counts: Dict[str, int] = {}
    dc_target_library_discovery_counts: Dict[str, int] = {}
    dc_target_libraries: set[str] = set()
    for row in parser_rows:
        if not isinstance(row, Mapping):
            continue
        row_status = str(row.get("status", "unknown") or "unknown")
        parser_status_counts[row_status] = parser_status_counts.get(row_status, 0) + 1
        if str(row.get("stage_id", "")) != "dc_asic_synth_timing_area":
            continue
        parsed_ref = row.get("parsed_result", {}) if isinstance(row.get("parsed_result", {}), Mapping) else {}
        parsed_path_text = str(parsed_ref.get("path", ""))
        if not parsed_path_text:
            continue
        parsed_path = run_dir / parsed_path_text
        if not parsed_path.exists():
            parsed_path = run_dir / "parsed_hard_gate_results" / parsed_path_text
        parsed_payload = _load_json(parsed_path)
        metrics = parsed_payload.get("metrics", {}) if isinstance(parsed_payload.get("metrics", {}), Mapping) else {}
        discovery = str(metrics.get("dc_target_library_discovery", "") or "")
        if discovery:
            dc_target_library_discovery_counts[discovery] = dc_target_library_discovery_counts.get(discovery, 0) + 1
        for library in metrics.get("dc_target_libraries", []) or []:
            if library:
                dc_target_libraries.add(str(library))
    status = (
        "fail_closed_hardware_closure_parser_run_present"
        if present and validation_valid is True and not hardware_completion_eligible and not deliverable_complete
        else "invalid_hardware_closure_parser_run"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_parser_run.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": parser_run.get("release_id"),
        "candidate_count": parser_run.get("candidate_count"),
        "major_kernel_count": parser_run.get("major_kernel_count"),
        "packet_count": parser_run.get("packet_count"),
        "unit_count": parser_run.get("unit_count"),
        "stage_count": parser_run.get("stage_count"),
        "parsed_result_written_count": parser_run.get("parsed_result_written_count"),
        "blocked_stage_count": parser_run.get("blocked_stage_count"),
        "verdict_counts": parser_run.get("verdict_counts"),
        "parser_status_counts": parser_status_counts,
        "stage_blocker_ids": parser_stage_blocker_ids,
        "dc_target_library_discovery_counts": dc_target_library_discovery_counts,
        "dc_target_libraries": sorted(dc_target_libraries),
        "adjudication_result": parser_run.get("adjudication_result"),
        "passed_stage_count": parser_run.get("passed_stage_count"),
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "invalid_claim_upgrade" if present and deliverable_complete else "blocked" if present else "not_applicable"
        ),
        "claim_boundary": (
            parser_run.get("claim_boundary")
            or "DFT hardware closure parser runs produce parser outputs from existing raw evidence only; they cannot adjudicate hard gates or upgrade completion claims."
        ),
    }


def _dft_hardware_closure_gate_adjudication_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional DFT hard-gate adjudication artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_CLOSURE_GATE_ADJUDICATION_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    gate_adjudication = loaded.get("dft_hardware_closure_gate_adjudication.json", {})
    validation = loaded.get("dft_hardware_closure_gate_adjudication_validation.json", {})
    present = bool(gate_adjudication)
    hardware_completion_eligible = bool(gate_adjudication.get("hardware_completion_eligible", False))
    deliverable_complete = bool(gate_adjudication.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    status = (
        "fail_closed_hardware_closure_gate_adjudication_present"
        if present and validation_valid is True and not hardware_completion_eligible and not deliverable_complete
        else "invalid_hardware_closure_gate_adjudication"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_gate_adjudication.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": gate_adjudication.get("release_id"),
        "candidate_count": gate_adjudication.get("candidate_count"),
        "major_kernel_count": gate_adjudication.get("major_kernel_count"),
        "packet_count": gate_adjudication.get("packet_count"),
        "unit_count": gate_adjudication.get("unit_count"),
        "stage_count": gate_adjudication.get("stage_count"),
        "stage_gate_passed_count": gate_adjudication.get("stage_gate_passed_count"),
        "blocked_stage_count": gate_adjudication.get("blocked_stage_count"),
        "failed_stage_count": gate_adjudication.get("failed_stage_count"),
        "unit_gate_passed_count": gate_adjudication.get("unit_gate_passed_count"),
        "blocked_unit_count": gate_adjudication.get("blocked_unit_count"),
        "failed_unit_count": gate_adjudication.get("failed_unit_count"),
        "candidate_kernel_axis_unbound_stage_count": gate_adjudication.get(
            "candidate_kernel_axis_unbound_stage_count"
        ),
        "parsed_stage_result_ref_count": gate_adjudication.get("parsed_stage_result_ref_count"),
        "parsed_stage_result_refs": gate_adjudication.get("parsed_stage_result_refs", []),
        "adjudication_result": gate_adjudication.get("adjudication_result"),
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
            "candidate_kernel_axis_unbound_stage_count": validation.get(
                "candidate_kernel_axis_unbound_stage_count"
            ),
            "parsed_stage_result_ref_count": validation.get("parsed_stage_result_ref_count"),
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "invalid_claim_upgrade" if present and deliverable_complete else "blocked" if present else "not_applicable"
        ),
        "claim_boundary": (
            gate_adjudication.get("claim_boundary")
            or "DFT hardware closure gate adjudication records per-stage verdicts only; it cannot upgrade release completion, trusted Pareto, FPGA PPA, or ASIC PPA claims by itself."
        ),
    }


def _dft_hardware_closure_release_gate_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional DFT hardware closure release-gate artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_CLOSURE_RELEASE_GATE_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    release_gate = loaded.get("dft_hardware_closure_release_gate.json", {})
    validation = loaded.get("dft_hardware_closure_release_gate_validation.json", {})
    present = bool(release_gate)
    hardware_completion_eligible = bool(release_gate.get("hardware_completion_eligible", False))
    deliverable_complete = bool(release_gate.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    status = (
        "fail_closed_hardware_closure_release_gate_present"
        if present and validation_valid is True and not deliverable_complete
        else "invalid_hardware_closure_release_gate"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_closure_release_gate.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "release_id": release_gate.get("release_id"),
        "candidate_count": release_gate.get("candidate_count"),
        "major_kernel_count": release_gate.get("major_kernel_count"),
        "packet_count": release_gate.get("packet_count"),
        "unit_count": release_gate.get("unit_count"),
        "stage_count": release_gate.get("stage_count"),
        "stage_gate_passed_count": release_gate.get("stage_gate_passed_count"),
        "blocked_stage_count": release_gate.get("blocked_stage_count"),
        "failed_stage_count": release_gate.get("failed_stage_count"),
        "expected_unit_count": release_gate.get("expected_unit_count"),
        "actual_unit_count": release_gate.get("actual_unit_count"),
        "duplicate_unit_count": release_gate.get("duplicate_unit_count"),
        "candidate_count_complete": release_gate.get("candidate_count_complete"),
        "unit_count_complete": release_gate.get("unit_count_complete"),
        "per_candidate_kernel_coverage_complete": release_gate.get("per_candidate_kernel_coverage_complete"),
        "unit_gate_passed_count": release_gate.get("unit_gate_passed_count"),
        "blocked_unit_count": release_gate.get("blocked_unit_count"),
        "failed_unit_count": release_gate.get("failed_unit_count"),
        "candidate_gate_passed_count": release_gate.get("candidate_gate_passed_count"),
        "blocked_candidate_count": release_gate.get("blocked_candidate_count"),
        "failed_candidate_count": release_gate.get("failed_candidate_count"),
        "release_gate_result": release_gate.get("release_gate_result"),
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": deliverable_complete,
        "evaluation_policy_routing_summary": release_gate.get("evaluation_policy_routing_summary", {}),
        "routing_blocker_count": release_gate.get("routing_blocker_count", 0),
        "routing_blocked_candidate_ids": release_gate.get("routing_blocked_candidate_ids", []),
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "completion_claim": (
            "invalid_claim_upgrade" if present and deliverable_complete else "blocked" if present else "not_applicable"
        ),
        "claim_boundary": (
            release_gate.get("claim_boundary")
            or "DFT hardware closure release gates roll up candidate/kernel gates but cannot directly mark deliverable completion."
        ),
    }


def _dft_hardware_ppa_ranking_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional DFT hardware PPA ranking artifacts.

    This section is scoped to candidate-stamped major-kernel hardware PPA.  It
    deliberately does not upgrade full-workload Step4 trust or mark deliverable
    completion.
    """

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_PPA_RANKING_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    ranking = loaded.get("dft_hardware_ppa_ranking.json", {})
    validation = loaded.get("dft_hardware_ppa_ranking_validation.json", {})
    status_artifact = loaded.get("dft_hardware_ppa_ranking_status.json", {})
    pareto = loaded.get("dft_hardware_ppa_pareto_frontier.json", {})
    present = bool(ranking)
    recomputed_validation = validate_dft_hardware_ppa_ranking(ranking) if present else {}
    companion_validation_valid = validation.get("valid")
    recomputed_validation_valid = recomputed_validation.get("valid")
    validation_valid = companion_validation_valid is True and recomputed_validation_valid is True
    ranking_entries = (
        ranking.get("fpga_ranking", [])
        if isinstance(ranking.get("fpga_ranking", []), list)
        else []
    )
    asic_entries = (
        ranking.get("asic_ranking", [])
        if isinstance(ranking.get("asic_ranking", []), list)
        else []
    )
    candidate_rows = (
        ranking.get("candidate_rows", [])
        if isinstance(ranking.get("candidate_rows", []), list)
        else []
    )
    fpga_model_binding_rows = []
    asic_model_binding_rows = []
    for row in candidate_rows:
        if not isinstance(row, Mapping):
            continue
        binding = row.get("fpga_target_model_binding", {})
        if not isinstance(binding, Mapping) or binding.get("status") in (None, "not_fpga_candidate"):
            pass
        else:
            fpga_model_binding_rows.append(
                {
                    "candidate_id": row.get("candidate_id"),
                    "ranking_eligible": row.get("ranking_eligible"),
                    "binding_status": binding.get("status"),
                    "blocker_id": binding.get("blocker_id"),
                    "observed_vivado_devices": binding.get(
                        "observed_vivado_devices",
                        row.get("fpga_vivado_devices", []),
                    ),
                    "expected_vivado_parts": binding.get("expected_vivado_parts", []),
                }
            )
        binding = row.get("asic_target_model_binding", {})
        if not isinstance(binding, Mapping) or binding.get("status") in (None, "not_asic_candidate"):
            continue
        asic_model_binding_rows.append(
            {
                "candidate_id": row.get("candidate_id"),
                "ranking_eligible": row.get("ranking_eligible"),
                "binding_status": binding.get("status"),
                "blocker_id": binding.get("blocker_id"),
                "observed_dc_target_libraries": binding.get(
                    "observed_dc_target_libraries",
                    row.get("asic_dc_target_libraries", []),
                ),
                "expected_dc_target_libraries": binding.get("expected_dc_target_libraries", []),
            }
        )
    pareto_entries = (
        pareto.get("pareto_alternatives", [])
        if isinstance(pareto.get("pareto_alternatives", []), list)
        else []
    )
    source_artifacts = ranking.get("source_artifacts", {}) if isinstance(ranking.get("source_artifacts", {}), Mapping) else {}
    candidate_universe_ref = (
        source_artifacts.get("candidate_universe_manifest", {})
        if isinstance(source_artifacts.get("candidate_universe_manifest", {}), Mapping)
        else {}
    )
    source_refs_valid = not (candidate_universe_ref and candidate_universe_ref.get("exists") is not True)
    if not source_refs_valid:
        recomputed_validation = dict(recomputed_validation)
        errors = list(recomputed_validation.get("errors", []) or [])
        if "ranking_candidates_require_candidate_universe_manifest" not in errors:
            errors.append("ranking_candidates_require_candidate_universe_manifest")
        recomputed_validation["errors"] = errors
        recomputed_validation["valid"] = False
        recomputed_validation_valid = False
    validation_valid = bool(validation_valid and source_refs_valid)
    trusted_hardware_scope = (
        present
        and validation_valid is True
        and ranking.get("hardware_completion_eligible") is True
        and (bool(ranking_entries) or bool(asic_entries))
    )
    return {
        "schema_version": "dse.final_report.dft_hardware_ppa_ranking.v1",
        "present": present,
        "status": (
            "hardware_ppa_ranking_present"
            if trusted_hardware_scope
            else "invalid_hardware_ppa_ranking"
            if present
            else "not_present"
        ),
        "artifacts": artifact_refs,
        "release_id": ranking.get("release_id"),
        "candidate_count": ranking.get("candidate_count"),
        "major_kernel_count": ranking.get("major_kernel_count"),
        "ranking_eligible_candidate_count": ranking.get("ranking_eligible_candidate_count"),
        "blocked_candidate_count": ranking.get("blocked_candidate_count"),
        "hardware_completion_eligible": bool(ranking.get("hardware_completion_eligible", False)),
        "deliverable_complete": False,
        "winner_selection_status": ranking.get("winner_selection_status"),
        "all_candidates_metric_tied": bool(ranking.get("all_candidates_metric_tied", False)),
        "metric_signature_count": ranking.get("metric_signature_count"),
        "fpga_top_candidate_ids": [
            str(row.get("candidate_id"))
            for row in ranking_entries
            if isinstance(row, Mapping) and row.get("rank") == 1 and row.get("candidate_id")
        ],
        "asic_top_candidate_ids": [
            str(row.get("candidate_id"))
            for row in asic_entries
            if isinstance(row, Mapping) and row.get("rank") == 1 and row.get("candidate_id")
        ],
        "pareto_candidate_count": pareto.get("pareto_candidate_count"),
        "pareto_alternatives": pareto_entries,
        "fpga_ranking": ranking_entries,
        "asic_ranking": asic_entries,
        "fpga_target_model_binding_rows": fpga_model_binding_rows,
        "asic_target_model_binding_rows": asic_model_binding_rows,
        "ranking_policy": ranking.get("ranking_policy", {}),
        "status_artifact": status_artifact,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "companion_valid": companion_validation_valid,
            "companion_errors": validation.get("errors", []) if validation else [],
            "companion_error_count": len(validation.get("errors", []) or []) if validation else None,
            "recomputed_valid": recomputed_validation_valid,
            "recomputed_errors": recomputed_validation.get("errors", [])
            if recomputed_validation
            else [],
            "recomputed_error_count": len(recomputed_validation.get("errors", []) or [])
            if recomputed_validation
            else None,
            "error_count": (
                len(validation.get("errors", []) or [])
                + len(recomputed_validation.get("errors", []) or [])
                if validation or recomputed_validation
                else None
            ),
        },
        "trusted_final_claim": False,
        "trusted_hardware_ppa_scope": bool(trusted_hardware_scope),
        "completion_claim": "blocked",
        "claim_boundary": (
            ranking.get("claim_boundary")
            or "DFT hardware PPA ranking is hardware-only evidence and cannot mark full deliverable completion."
        ),
    }


def _dft_hardware_ppa_trusted_entries(section: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Convert hardware PPA ranking rows into scoped Step5 ranking entries."""

    if not section.get("trusted_hardware_ppa_scope"):
        return []
    entries: List[Dict[str, Any]] = []
    for row in list(section.get("fpga_ranking", []) or []) + list(section.get("asic_ranking", []) or []):
        if not isinstance(row, Mapping):
            continue
        entries.append(
            {
                "design_point_id": str(row.get("candidate_id")),
                "candidate_id": str(row.get("candidate_id")),
                "design_candidate_id": row.get("design_candidate_id"),
                "backend": "vivado_dc_candidate_hard_gate",
                "status": "hardware_ppa_ranked",
                "trusted_scope": (
                    "candidate-stamped major-kernel hardware PPA only; not a "
                    "generic Step4 full-workload ranking and not deliverable completion"
                ),
                "rank": row.get("rank"),
                "winner_selection_status": section.get("winner_selection_status"),
                "metrics": {
                    "fpga_total_slice_luts": row.get("fpga_total_slice_luts"),
                    "fpga_total_dsps": row.get("fpga_total_dsps"),
                    "fpga_total_block_ram_tiles": row.get("fpga_total_block_ram_tiles"),
                    "fpga_total_bonded_iob": row.get("fpga_total_bonded_iob"),
                    "asic_total_cell_area": row.get("asic_total_cell_area"),
                    "asic_min_slack_ns": row.get("asic_min_slack_ns"),
                    "kernel_count": row.get("kernel_count"),
                },
                "validation": {
                    "trusted": True,
                    "validation_status": "trusted_hardware_ppa_scope_only",
                    "not_full_dse_winner": True,
                    "deliverable_complete": False,
                },
                "evidence_ids": [
                    "dft_hardware_ppa_ranking.json",
                    "dft_hardware_ppa_pareto_frontier.json",
                    "dft_hardware_ppa_ranking_validation.json",
                    "dft_hardware_closure_release_gate.json",
                    "dft_hardware_closure_gate_adjudication.json",
                    "dft_hardware_closure_parser_run.json",
                ],
            }
        )
    return entries


def _dft_candidate_specific_ppa_provenance_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize candidate-specific PPA provenance and fresh execution queue."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    audit = loaded.get("dft_candidate_specific_ppa_provenance_audit.json", {})
    validation = loaded.get("dft_candidate_specific_ppa_provenance_audit_validation.json", {})
    status_artifact = loaded.get("dft_candidate_specific_ppa_provenance_audit_status.json", {})
    queue = loaded.get("dft_hardware_tie_breaker_execution_queue.json", {})
    queue_validation = loaded.get("dft_hardware_tie_breaker_execution_queue_validation.json", {})
    execution = loaded.get("dft_candidate_specific_ppa_execution.json", {})
    execution_validation = loaded.get("dft_candidate_specific_ppa_execution_validation.json", {})
    execution_status = loaded.get("dft_candidate_specific_ppa_execution_status.json", {})
    present = bool(audit)
    recomputed_validation = (
        validate_dft_candidate_specific_ppa_provenance_audit(audit)
        if present
        else {}
    )
    companion_validation_valid = validation.get("valid")
    recomputed_validation_valid = recomputed_validation.get("valid")
    validation_valid = companion_validation_valid is True and recomputed_validation_valid is True
    source_winner_provenance_eligible = bool(audit.get("winner_provenance_eligible", False))
    winner_provenance_eligible = source_winner_provenance_eligible and validation_valid is True
    return {
        "schema_version": "dse.final_report.dft_candidate_specific_ppa_provenance.v1",
        "present": present,
        "status": (
            "invalid_candidate_specific_ppa_provenance_validation"
            if present and validation_valid is not True
            else audit.get("status")
            if present
            else "not_present"
        ),
        "artifacts": artifact_refs,
        "candidate_count": audit.get("candidate_count"),
        "major_kernel_count": audit.get("major_kernel_count"),
        "unit_count": audit.get("unit_count"),
        "stage_count": audit.get("stage_count"),
        "trusted_unit_count": audit.get("trusted_unit_count"),
        "blocked_unit_count": audit.get("blocked_unit_count"),
        "trusted_stage_count": audit.get("trusted_stage_count"),
        "blocked_stage_count": audit.get("blocked_stage_count"),
        "blocker_count": audit.get("blocker_count"),
        "blocker_id_counts": audit.get("blocker_id_counts", {}),
        "source_winner_provenance_eligible": source_winner_provenance_eligible,
        "winner_provenance_eligible": winner_provenance_eligible,
        "tied_candidate_ids_requiring_fresh_ppa": audit.get("tied_candidate_ids_requiring_fresh_ppa", []),
        "tie_breaker_queue_present": bool(queue),
        "tie_breaker_work_item_count": queue.get("work_item_count"),
        "tie_breaker_queue_status": queue.get("status"),
        "fresh_execution_present": bool(execution),
        "fresh_execution_status": execution.get("status"),
        "fresh_execution_selected_unit_count": execution.get("selected_unit_count"),
        "fresh_execution_executed_unit_count": execution.get("executed_unit_count"),
        "fresh_execution_blocked_unit_count": execution.get("blocked_unit_count"),
        "fresh_execution_materialized_raw_file_count": execution.get("materialized_raw_file_count"),
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "companion_valid": companion_validation_valid,
            "companion_errors": validation.get("errors", []) if validation else [],
            "companion_error_count": len(validation.get("errors", []) or []) if validation else None,
            "recomputed_valid": recomputed_validation_valid,
            "recomputed_errors": recomputed_validation.get("errors", [])
            if recomputed_validation
            else [],
            "recomputed_error_count": len(recomputed_validation.get("errors", []) or [])
            if recomputed_validation
            else None,
            "error_count": (
                len(validation.get("errors", []) or [])
                + len(recomputed_validation.get("errors", []) or [])
                if validation or recomputed_validation
                else None
            ),
        },
        "queue_validation": {
            "present": bool(queue_validation),
            "valid": queue_validation.get("valid"),
            "error_count": len(queue_validation.get("errors", []) or []) if queue_validation else None,
        },
        "fresh_execution_validation": {
            "present": bool(execution_validation),
            "valid": execution_validation.get("valid"),
            "error_count": len(execution_validation.get("errors", []) or []) if execution_validation else None,
        },
        "fresh_execution_status_artifact": execution_status,
        "status_artifact": status_artifact,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "trusted_final_claim": False,
        "completion_claim": (
            "winner_provenance_ready_pending_unique_ppa_and_release_claim"
            if winner_provenance_eligible
            else "blocked"
            if present
            else "not_applicable"
        ),
        "claim_boundary": (
            audit.get("claim_boundary")
            or "Candidate-specific PPA provenance blocks winner proof when raw files lack fresh command/tool provenance."
        ),
    }


def _dft_architecture_winner_resolution_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize fail-closed FPGA/ASIC winner-resolution artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_ARCHITECTURE_WINNER_RESOLUTION_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    resolution = loaded.get("dft_architecture_winner_resolution.json", {})
    validation = loaded.get("dft_architecture_winner_resolution_validation.json", {})
    status_artifact = loaded.get("dft_architecture_winner_resolution_status.json", {})
    present = bool(resolution)
    deployments = resolution.get("deployments", {}) if isinstance(resolution.get("deployments", {}), Mapping) else {}
    fpga = deployments.get("fpga", {}) if isinstance(deployments.get("fpga", {}), Mapping) else {}
    asic = deployments.get("asic", {}) if isinstance(deployments.get("asic", {}), Mapping) else {}
    recomputed_validation = (
        validate_dft_architecture_winner_resolution(resolution)
        if present
        else {}
    )
    companion_validation_valid = validation.get("valid")
    recomputed_validation_valid = recomputed_validation.get("valid")
    validation_valid = companion_validation_valid is True and recomputed_validation_valid is True
    status_passed = (
        status_artifact.get("status") == "passed"
        if status_artifact
        else validation_valid is True
    )
    source_hardware_winner_resolution_eligible = bool(
        resolution.get("hardware_winner_resolution_eligible", False)
    )
    hardware_winner_resolution_eligible = (
        source_hardware_winner_resolution_eligible
        and validation_valid is True
        and status_passed
    )
    return {
        "schema_version": "dse.final_report.dft_architecture_winner_resolution.v1",
        "present": present,
        "status": (
            "invalid_hardware_winner_resolution_validation"
            if present and validation_valid is not True
            else "invalid_hardware_winner_resolution_status"
            if present and not status_passed
            else resolution.get("status")
            if present
            else "not_present"
        ),
        "source_status": resolution.get("status"),
        "artifacts": artifact_refs,
        "release_id": resolution.get("release_id"),
        "candidate_count": resolution.get("candidate_count"),
        "ranking_eligible_candidate_count": resolution.get("ranking_eligible_candidate_count"),
        "hardware_completion_eligible": bool(resolution.get("hardware_completion_eligible", False)),
        "ppa_winner_selection_status": resolution.get("ppa_winner_selection_status"),
        "all_candidates_metric_tied": bool(resolution.get("all_candidates_metric_tied", False)),
        "metric_signature_count": resolution.get("metric_signature_count"),
        "source_hardware_winner_resolution_eligible": source_hardware_winner_resolution_eligible,
        "hardware_winner_resolution_eligible": hardware_winner_resolution_eligible,
        "trusted_best_architecture_claim_eligible": False,
        "deliverable_complete": False,
        "fpga_status": fpga.get("status"),
        "asic_status": asic.get("status"),
        "fpga_top_rank_candidate_count": fpga.get("top_rank_candidate_count"),
        "asic_top_rank_candidate_count": asic.get("top_rank_candidate_count"),
        "fpga_top_candidate_ids": fpga.get("top_rank_candidate_ids", []),
        "asic_top_candidate_ids": asic.get("top_rank_candidate_ids", []),
        "fpga_best_architecture": resolution.get("fpga_best_architecture"),
        "asic_best_architecture": resolution.get("asic_best_architecture"),
        "full_scf_tie_breaker": resolution.get("full_scf_tie_breaker", {}),
        "blocker_count": resolution.get("blocker_count"),
        "blockers": resolution.get("blockers", []),
        "required_next_evidence": {
            "fpga": fpga.get("required_next_evidence", []),
            "asic": asic.get("required_next_evidence", []),
        },
        "status_artifact": status_artifact,
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "companion_valid": companion_validation_valid,
            "companion_errors": validation.get("errors", []) if validation else [],
            "companion_error_count": len(validation.get("errors", []) or []) if validation else None,
            "recomputed_valid": recomputed_validation_valid,
            "recomputed_errors": recomputed_validation.get("errors", [])
            if recomputed_validation
            else [],
            "recomputed_error_count": len(recomputed_validation.get("errors", []) or [])
            if recomputed_validation
            else None,
            "error_count": (
                len(validation.get("errors", []) or [])
                + len(recomputed_validation.get("errors", []) or [])
                if validation or recomputed_validation
                else None
            ),
        },
        "status_validation": {
            "present": bool(status_artifact),
            "status": status_artifact.get("status"),
            "passed": status_passed,
        },
        "trusted_final_claim": False,
        "completion_claim": resolution.get("completion_claim", "blocked" if present else "not_applicable"),
        "claim_boundary": (
            resolution.get("claim_boundary")
            or "Winner resolution is fail-closed and cannot mark final deliverable completion."
        ),
    }


def _dft_hardware_deployment_recommendation_readiness_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize fail-closed FPGA/ASIC deployment recommendation readiness."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(
        DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_ARTIFACT_NAMES
        | DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_ARTIFACT_NAMES
        | DFT_FULL_SCF_NUMERICAL_CLOSURE_ARTIFACT_NAMES
        | DFT_FULL_SCF_NUMERICAL_CLOSURE_AUX_ARTIFACT_NAMES
    ):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path and name.endswith(".json"):
            loaded[name] = _load_json(run_dir / rel_path)

    readiness = loaded.get("dft_hardware_deployment_recommendation_readiness.json", {})
    validation = loaded.get("dft_hardware_deployment_recommendation_readiness_validation.json", {})
    status_artifact = loaded.get("dft_hardware_deployment_recommendation_readiness_status.json", {})
    target_selection_artifact = loaded.get("dft_hardware_deployment_target_selection.json", {})
    full_scf_artifact_name = (
        "full_scf_end_to_end_comparison.json"
        if loaded.get("full_scf_end_to_end_comparison.json")
        else "full_scf_end_to_end_comparison.recheck.json"
        if loaded.get("full_scf_end_to_end_comparison.recheck.json")
        else None
    )
    full_scf_validation_artifact_name = (
        "full_scf_end_to_end_comparison_validation.json"
        if full_scf_artifact_name == "full_scf_end_to_end_comparison.json"
        else "full_scf_end_to_end_comparison.recheck_validation.json"
        if full_scf_artifact_name == "full_scf_end_to_end_comparison.recheck.json"
        else None
    )
    full_scf_status_artifact_name = (
        "full_scf_end_to_end_comparison_status.json"
        if full_scf_artifact_name == "full_scf_end_to_end_comparison.json"
        else "full_scf_end_to_end_comparison.recheck_status.json"
        if full_scf_artifact_name == "full_scf_end_to_end_comparison.recheck.json"
        else None
    )
    full_scf = loaded.get(full_scf_artifact_name or "", {})
    full_scf_validation = loaded.get(full_scf_validation_artifact_name or "", {})
    full_scf_status_artifact_payload = loaded.get(full_scf_status_artifact_name or "", {})
    full_scf_artifact = (
        artifact_refs.get(full_scf_artifact_name or "", {}).get("path")
        if full_scf_artifact_name
        else None
    )
    full_scf_sections = build_full_scf_numerical_readiness_sections(
        full_scf,
        validation=full_scf_validation,
        status_artifact=full_scf_status_artifact_payload,
        artifact=full_scf_artifact,
        validation_artifact=(
            artifact_refs.get(full_scf_validation_artifact_name or "", {}).get("path")
            if full_scf_validation_artifact_name
            else None
        ),
        status_artifact_path=(
            artifact_refs.get(full_scf_status_artifact_name or "", {}).get("path")
            if full_scf_status_artifact_name
            else None
        ),
    )
    full_scf_workplan = full_scf_sections["full_scf_numerical_closure_workplan"]
    full_scf_qe_requirements = loaded.get("qe_accelerated_numeric_evidence_requirements.json", {})
    full_scf_qe_requirements_validation = loaded.get(
        "qe_accelerated_numeric_evidence_requirements_validation.json",
        {},
    )
    full_scf_qe_requirements_status = loaded.get(
        "qe_accelerated_numeric_evidence_requirements_status.json",
        {},
    )
    full_scf_qe_baseline_materialization = loaded.get(
        "dft_scf_six_class_qe_baseline_materialization.json",
        {},
    )
    full_scf_qe_baseline_materialization_validation = loaded.get(
        "dft_scf_six_class_qe_baseline_materialization_validation.json",
        {},
    )
    full_scf_qe_baseline_materialization_status = loaded.get(
        "dft_scf_six_class_qe_baseline_materialization_status.json",
        {},
    )
    full_scf_execution_queue = loaded.get("full_scf_trusted_evidence_execution_queue.json", {})
    full_scf_execution_queue_validation = loaded.get(
        "full_scf_trusted_evidence_execution_queue_validation.json",
        {},
    )
    full_scf_execution_queue_status = loaded.get(
        "full_scf_trusted_evidence_execution_queue_status.json",
        {},
    )
    full_scf_batch_plan = loaded.get("full_scf_trusted_evidence_batch_plan.json", {})
    full_scf_batch_plan_validation = loaded.get(
        "full_scf_trusted_evidence_batch_plan_validation.json",
        {},
    )
    full_scf_batch_plan_status = loaded.get(
        "full_scf_trusted_evidence_batch_plan_status.json",
        {},
    )
    targeted_accounting_artifact = loaded.get(
        "dft_full_scf_targeted_deployment_accounting.json",
        {},
    )
    targeted_accounting_validation = loaded.get(
        "dft_full_scf_targeted_deployment_accounting_validation.json",
        {},
    )
    targeted_accounting_status = loaded.get(
        "dft_full_scf_targeted_deployment_accounting_status.json",
        {},
    )
    present = bool(readiness)
    deployments = readiness.get("deployments", {}) if isinstance(readiness.get("deployments", {}), Mapping) else {}
    fpga = deployments.get("fpga", {}) if isinstance(deployments.get("fpga", {}), Mapping) else {}
    asic = deployments.get("asic", {}) if isinstance(deployments.get("asic", {}), Mapping) else {}
    fpga_target_selection = (
        fpga.get("target_selection", {})
        if isinstance(fpga.get("target_selection", {}), Mapping)
        else {}
    )
    asic_target_selection = (
        asic.get("target_selection", {})
        if isinstance(asic.get("target_selection", {}), Mapping)
        else {}
    )
    deployment_target_selection_trust_gates = (
        readiness.get("deployment_target_selection_trust_gates", {})
        if isinstance(readiness.get("deployment_target_selection_trust_gates", {}), Mapping)
        else {}
    )
    target_selection_trust_gate_rows = (
        deployment_target_selection_trust_gates.get("gates", {})
        if isinstance(deployment_target_selection_trust_gates.get("gates", {}), Mapping)
        else {}
    )
    target_selection_trusted_gate_count = sum(
        1
        for gate in target_selection_trust_gate_rows.values()
        if isinstance(gate, Mapping) and gate.get("trusted") is True
    )
    target_selection_blocked_gate_count = sum(
        1
        for gate in target_selection_trust_gate_rows.values()
        if isinstance(gate, Mapping) and gate.get("blockers")
    )
    target_selection_trust_gate_summary = {
        "present": bool(deployment_target_selection_trust_gates.get("present", False)),
        "all_trusted": bool(deployment_target_selection_trust_gates.get("all_trusted", False)),
        "trusted_gate_count": target_selection_trusted_gate_count,
        "gate_count": len(target_selection_trust_gate_rows),
        "blocked_gate_count": target_selection_blocked_gate_count,
    }
    target_selection_input_trust_gates = {
        "fpga": dict(fpga_target_selection.get("input_trust_gate", {}))
        if isinstance(fpga_target_selection.get("input_trust_gate", {}), Mapping)
        else {},
        "asic": dict(asic_target_selection.get("input_trust_gate", {}))
        if isinstance(asic_target_selection.get("input_trust_gate", {}), Mapping)
        else {},
    }
    readiness_targeted_accounting = (
        readiness.get("full_scf_targeted_deployment_accounting", {})
        if isinstance(readiness.get("full_scf_targeted_deployment_accounting", {}), Mapping)
        else {}
    )
    direct_targeted_accounting = summarize_full_scf_targeted_deployment_accounting(
        targeted_accounting_artifact,
        validation=targeted_accounting_validation,
    )
    targeted_accounting = (
        readiness_targeted_accounting
        if readiness_targeted_accounting
        else direct_targeted_accounting
    )
    targeted_accounting_deployments = (
        targeted_accounting.get("deployments", {})
        if isinstance(targeted_accounting.get("deployments", {}), Mapping)
        else {}
    )
    source_artifacts = (
        readiness.get("source_artifacts", {})
        if isinstance(readiness.get("source_artifacts", {}), Mapping)
        else {}
    )
    required_next_evidence = (
        readiness.get("required_next_evidence", {})
        if isinstance(readiness.get("required_next_evidence", {}), Mapping)
        else {}
    )
    final_next_evidence = (
        readiness.get("final_recommendation_required_next_evidence", {})
        if isinstance(readiness.get("final_recommendation_required_next_evidence", {}), Mapping)
        else {}
    )
    next_counts = (
        readiness.get("next_runnable_work_item_counts", {})
        if isinstance(readiness.get("next_runnable_work_item_counts", {}), Mapping)
        else {}
    )
    fpga_next_counts = next_counts.get("fpga", {}) if isinstance(next_counts.get("fpga", {}), Mapping) else {}
    asic_next_counts = next_counts.get("asic", {}) if isinstance(next_counts.get("asic", {}), Mapping) else {}
    deployment_summary: Dict[str, Dict[str, Any]] = {}
    for deployment, row in (("fpga", fpga), ("asic", asic)):
        next_counts_for_deployment = (
            next_counts.get(deployment, {})
            if isinstance(next_counts.get(deployment, {}), Mapping)
            else {}
        )
        row_target_selection = (
            row.get("target_selection", {})
            if isinstance(row.get("target_selection", {}), Mapping)
            else {}
        )
        row_input_trust_gate = (
            row_target_selection.get("input_trust_gate", {})
            if isinstance(row_target_selection.get("input_trust_gate", {}), Mapping)
            else {}
        )
        deployment_summary[deployment] = {
            "deployment": deployment,
            "status": row.get("status"),
            "can_name_hardware_ppa_winner": bool(row.get("can_name_hardware_ppa_winner", False)),
            "can_name_final_recommendation": False,
            "can_name_targeted_deployment_recommendation": False,
            "resolved_by_winner_resolution": bool(row.get("resolved_by_winner_resolution", False)),
            "hardware_winner_resolution_eligible": bool(row.get("hardware_winner_resolution_eligible", False)),
            "blocker_count": len(row.get("blockers", []) or []),
            "blockers": list(row.get("blockers", []) or []),
            "required_next_evidence": list(row.get("required_next_evidence", []) or []),
            "final_recommendation_required_next_evidence": list(
                row.get("final_recommendation_required_next_evidence", []) or []
            ),
            "next_runnable_work_item_counts": dict(next_counts_for_deployment),
            "target_selection": row_target_selection,
            "target_selection_input_trust_gate": dict(row_input_trust_gate),
            "tool_readiness": row.get("tool_readiness", {}),
        }
    raw_can_name_targeted = bool(readiness.get("can_name_targeted_deployment_recommendation", False))
    raw_can_name_final = bool(readiness.get("can_name_final_recommendation", False))
    raw_deliverable_complete = bool(readiness.get("deliverable_complete", False))
    safety_findings: list[str] = []
    if raw_can_name_targeted:
        safety_findings.append("readiness_attempted_targeted_deployment_recommendation_upgrade")
    if raw_can_name_final:
        safety_findings.append("readiness_attempted_final_recommendation_upgrade")
    if raw_deliverable_complete:
        safety_findings.append("readiness_attempted_deliverable_complete_upgrade")
    readiness_upgrade_detected = bool(safety_findings)
    validation_valid = validation.get("valid")
    report_validation_valid = False if readiness_upgrade_detected else validation_valid
    return {
        "schema_version": "dse.final_report.dft_hardware_deployment_recommendation_readiness.v1",
        "present": present,
        "status": readiness.get("status") if present else "not_present",
        "artifacts": artifact_refs,
        "deployments": deployment_summary,
        "release_id": readiness.get("release_id"),
        "candidate_count": readiness.get("candidate_count"),
        "ranking_eligible_candidate_count": readiness.get("ranking_eligible_candidate_count"),
        "hardware_completion_eligible": bool(readiness.get("hardware_completion_eligible", False)),
        "hardware_winner_resolution_eligible": bool(readiness.get("hardware_winner_resolution_eligible", False)),
        "fpga_status": fpga.get("status"),
        "asic_status": asic.get("status"),
        "fpga_can_name_winner": bool(readiness.get("fpga_can_name_winner", False)),
        "asic_can_name_winner": bool(readiness.get("asic_can_name_winner", False)),
        "can_name_hardware_ppa_winners": bool(readiness.get("can_name_hardware_ppa_winners", False)),
        "deployment_target_selection_ready": bool(
            readiness.get("deployment_target_selection_ready", False)
        ),
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "raw_readiness_flags": {
            "can_name_targeted_deployment_recommendation": raw_can_name_targeted,
            "can_name_final_recommendation": raw_can_name_final,
            "deliverable_complete": raw_deliverable_complete,
        },
        "targeted_recommendation_upgrade_detected": raw_can_name_targeted,
        "final_recommendation_upgrade_detected": raw_can_name_final,
        "deliverable_upgrade_detected": raw_deliverable_complete,
        "readiness_upgrade_detected": readiness_upgrade_detected,
        "safety_findings": safety_findings,
        "deployment_target_selection_artifact": artifact_refs.get(
            "dft_hardware_deployment_target_selection.json",
            {},
        ),
        "deployment_target_selection_source": dict(
            source_artifacts.get("deployment_target_selection", {})
            if isinstance(source_artifacts.get("deployment_target_selection", {}), Mapping)
            else {}
        ),
        "deployment_target_selection_status": (
            target_selection_artifact.get("status")
            or fpga_target_selection.get("status")
            or asic_target_selection.get("status")
        ),
        "deployment_target_selection_trust_gates": dict(deployment_target_selection_trust_gates),
        "deployment_target_selection_trust_gate_summary": target_selection_trust_gate_summary,
        "target_selection_input_trust_gates": target_selection_input_trust_gates,
        "fpga_target_selection": fpga_target_selection,
        "asic_target_selection": asic_target_selection,
        "required_next_evidence": {
            "fpga": required_next_evidence.get("fpga", []),
            "asic": required_next_evidence.get("asic", []),
        },
        "required_next_evidence_counts": {
            "fpga": len(required_next_evidence.get("fpga", []) or []),
            "asic": len(required_next_evidence.get("asic", []) or []),
        },
        "final_recommendation_required_next_evidence": {
            "fpga": final_next_evidence.get("fpga", []),
            "asic": final_next_evidence.get("asic", []),
        },
        "final_recommendation_required_next_evidence_counts": {
            "fpga": len(final_next_evidence.get("fpga", []) or []),
            "asic": len(final_next_evidence.get("asic", []) or []),
        },
        "next_runnable_work_item_counts": {
            "fpga": fpga_next_counts,
            "asic": asic_next_counts,
        },
        "full_scf_numerical_gate": full_scf_sections["full_scf_numerical_gate"],
        "full_scf_numerical_closure_workplan": full_scf_workplan,
        "full_scf_qe_accelerated_numeric_requirements": {
            "present": bool(full_scf_qe_requirements),
            "artifact": artifact_refs.get("qe_accelerated_numeric_evidence_requirements.json", {}),
            "validation_artifact": artifact_refs.get(
                "qe_accelerated_numeric_evidence_requirements_validation.json",
                {},
            ),
            "status_artifact": artifact_refs.get(
                "qe_accelerated_numeric_evidence_requirements_status.json",
                {},
            ),
            "status": full_scf_qe_requirements.get("status"),
            "requirements_status": full_scf_qe_requirements_status.get("requirements_status"),
            "validation_valid": full_scf_qe_requirements_validation.get("valid"),
            "row_count": full_scf_qe_requirements.get("row_count"),
            "ready_row_count": full_scf_qe_requirements.get("ready_row_count"),
            "blocked_row_count": full_scf_qe_requirements.get("blocked_row_count"),
            "candidate_count": full_scf_qe_requirements.get("candidate_count"),
            "strict_scf_class_count": full_scf_qe_requirements.get("strict_scf_class_count"),
            "source_blocker_ids": full_scf_qe_requirements.get("source_blocker_ids", []),
            "blocker_id_counts": full_scf_qe_requirements.get("blocker_id_counts", {}),
            "trusted_final_claim": False,
            "hardware_completion_eligible": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": full_scf_qe_requirements.get(
                "claim_boundary",
                "Full-SCF QE accelerated numeric requirements are producer inputs only.",
            ),
        },
        "full_scf_qe_baseline_materialization": {
            "present": bool(full_scf_qe_baseline_materialization),
            "artifact": artifact_refs.get(
                "dft_scf_six_class_qe_baseline_materialization.json",
                {},
            ),
            "validation_artifact": artifact_refs.get(
                "dft_scf_six_class_qe_baseline_materialization_validation.json",
                {},
            ),
            "status_artifact": artifact_refs.get(
                "dft_scf_six_class_qe_baseline_materialization_status.json",
                {},
            ),
            "status": full_scf_qe_baseline_materialization.get("status"),
            "materialization_status": full_scf_qe_baseline_materialization_status.get("status"),
            "validation_valid": full_scf_qe_baseline_materialization_validation.get("valid"),
            "case_count": full_scf_qe_baseline_materialization.get("case_count"),
            "passed_case_count": full_scf_qe_baseline_materialization.get("passed_case_count"),
            "blocked_case_count": full_scf_qe_baseline_materialization.get("blocked_case_count"),
            "strict_scf_class_ids": full_scf_qe_baseline_materialization.get(
                "strict_scf_class_ids",
                [],
            ),
            "blocker_id_counts": full_scf_qe_baseline_materialization.get(
                "blocker_id_counts",
                {},
            ),
            "trusted_final_claim": False,
            "hardware_completion_eligible": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": full_scf_qe_baseline_materialization.get(
                "claim_boundary",
                "Strict six-class QE baseline materialization is a pure-software baseline readiness input only.",
            ),
        },
        "full_scf_targeted_deployment_accounting": {
            "present": bool(targeted_accounting_artifact),
            "artifact": artifact_refs.get("dft_full_scf_targeted_deployment_accounting.json", {}),
            "validation_artifact": artifact_refs.get(
                "dft_full_scf_targeted_deployment_accounting_validation.json",
                {},
            ),
            "status_artifact": artifact_refs.get(
                "dft_full_scf_targeted_deployment_accounting_status.json",
                {},
            ),
            "status": (
                targeted_accounting.get("status")
                or targeted_accounting_artifact.get("status")
            ),
            "artifact_status": targeted_accounting_status.get("status"),
            "validation_valid": (
                targeted_accounting.get("validation_valid")
                if "validation_valid" in targeted_accounting
                else targeted_accounting_validation.get("valid")
            ),
            "targeted_accounting_ready": bool(
                targeted_accounting.get("targeted_accounting_ready", False)
            ),
            "projection_only": bool(targeted_accounting.get("projection_only", True)),
            "full_scf_numerical_gate_passed": bool(
                targeted_accounting.get("full_scf_numerical_gate_passed", False)
            ),
            "blocker_ids": list(targeted_accounting.get("blocker_ids", []) or []),
            "final_claim_blockers": list(
                targeted_accounting_artifact.get("final_claim_blockers", []) or []
            ),
            "fpga": targeted_accounting_deployments.get("fpga", {}),
            "asic": targeted_accounting_deployments.get("asic", {}),
            "trusted_final_claim": False,
            "hardware_completion_eligible": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": targeted_accounting.get(
                "claim_boundary",
                "Target-tied full-SCF accounting is planning/accounting evidence only.",
            ),
        },
        "full_scf_trusted_evidence_execution_queue": {
            "present": bool(full_scf_execution_queue),
            "artifact": artifact_refs.get("full_scf_trusted_evidence_execution_queue.json", {}),
            "validation_artifact": artifact_refs.get(
                "full_scf_trusted_evidence_execution_queue_validation.json",
                {},
            ),
            "status_artifact": artifact_refs.get(
                "full_scf_trusted_evidence_execution_queue_status.json",
                {},
            ),
            "status": full_scf_execution_queue.get("status"),
            "queue_status": full_scf_execution_queue_status.get("queue_status"),
            "validation_valid": full_scf_execution_queue_validation.get("valid"),
            "execution_required": bool(full_scf_execution_queue.get("execution_required", False)),
            "work_item_count": full_scf_execution_queue.get("work_item_count"),
            "candidate_count": full_scf_execution_queue.get("candidate_count"),
            "strict_scf_class_count": full_scf_execution_queue.get("strict_scf_class_count"),
            "winner_prioritization_trusted": bool(
                full_scf_execution_queue.get("winner_prioritization_trusted", False)
            ),
            "source_blocker_id_counts": full_scf_execution_queue.get("source_blocker_id_counts", {}),
            "trusted_final_claim": False,
            "hardware_completion_eligible": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": full_scf_execution_queue.get(
                "claim_boundary",
                "Full-SCF trusted evidence execution queue is scheduling metadata only.",
            ),
        },
        "full_scf_trusted_evidence_batch_plan": {
            "present": bool(full_scf_batch_plan),
            "artifact": artifact_refs.get("full_scf_trusted_evidence_batch_plan.json", {}),
            "validation_artifact": artifact_refs.get(
                "full_scf_trusted_evidence_batch_plan_validation.json",
                {},
            ),
            "status_artifact": artifact_refs.get(
                "full_scf_trusted_evidence_batch_plan_status.json",
                {},
            ),
            "shell_script_artifact": artifact_refs.get(
                "run_full_scf_trusted_evidence_batches.sh",
                {},
            ),
            "status": full_scf_batch_plan.get("status"),
            "plan_status": full_scf_batch_plan_status.get("plan_status"),
            "validation_valid": full_scf_batch_plan_validation.get("valid"),
            "planned_work_item_count": full_scf_batch_plan.get("planned_work_item_count"),
            "ready_to_execute_work_item_count": full_scf_batch_plan.get(
                "ready_to_execute_work_item_count"
            ),
            "blocked_work_item_count": full_scf_batch_plan.get("blocked_work_item_count"),
            "shard_count": full_scf_batch_plan.get("shard_count"),
            "priority_buckets": full_scf_batch_plan.get("priority_buckets", []),
            "blocker_id_counts": full_scf_batch_plan.get("blocker_id_counts", {}),
            "trusted_final_claim": False,
            "hardware_completion_eligible": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": full_scf_batch_plan.get(
                "claim_boundary",
                "Full-SCF trusted evidence batch plan is replay metadata only.",
            ),
        },
        "release_completion_gates": full_scf_sections["release_completion_gates"],
        "fpga_tool_readiness": fpga.get("tool_readiness", {}),
        "asic_tool_readiness": asic.get("tool_readiness", {}),
        "forbidden_shortcuts": readiness.get("forbidden_shortcuts", []),
        "status_artifact": status_artifact,
        "validation": {
            "present": bool(validation),
            "valid": report_validation_valid,
            "artifact_valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
            "report_safety_error_count": len(safety_findings),
        },
        "completion_claim": readiness.get("completion_claim", "blocked" if present else "not_applicable"),
        "claim_boundary": (
            readiness.get("claim_boundary")
            or "DFT deployment readiness is an evidence-planning summary only and cannot name final winners."
        ),
    }



def _dft_hardware_deployment_decision_packet_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize the fail-closed deployment decision packet."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_HARDWARE_DEPLOYMENT_DECISION_PACKET_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    packet = loaded.get("dft_hardware_deployment_decision_packet.json", {})
    validation = loaded.get("dft_hardware_deployment_decision_packet_validation.json", {})
    status_artifact = loaded.get("dft_hardware_deployment_decision_packet_status.json", {})
    present = bool(packet)
    deployments = packet.get("deployments", {}) if isinstance(packet.get("deployments", {}), Mapping) else {}
    fpga = deployments.get("fpga", {}) if isinstance(deployments.get("fpga", {}), Mapping) else {}
    asic = deployments.get("asic", {}) if isinstance(deployments.get("asic", {}), Mapping) else {}
    raw_targeted = bool(packet.get("can_name_targeted_deployment_recommendation", False))
    raw_final = bool(packet.get("can_name_final_recommendation", False))
    raw_trusted_final = bool(packet.get("trusted_final_claim", False))
    raw_deliverable = bool(packet.get("deliverable_complete", False))
    safety_findings: list[str] = []
    if raw_targeted:
        safety_findings.append("decision_packet_attempted_targeted_recommendation_upgrade")
    if raw_final:
        safety_findings.append("decision_packet_attempted_final_recommendation_upgrade")
    if raw_trusted_final:
        safety_findings.append("decision_packet_attempted_trusted_final_claim_upgrade")
    if raw_deliverable:
        safety_findings.append("decision_packet_attempted_deliverable_complete_upgrade")
    validation_valid = validation.get("valid")
    report_validation_valid = False if safety_findings else validation_valid
    return {
        "schema_version": "dse.final_report.dft_hardware_deployment_decision_packet.v1",
        "present": present,
        "status": packet.get("status") if present else "not_present",
        "artifacts": artifact_refs,
        "release_id": packet.get("release_id"),
        "candidate_count": packet.get("candidate_count"),
        "ranking_eligible_candidate_count": packet.get("ranking_eligible_candidate_count"),
        "planning_packet_ready": bool(packet.get("planning_packet_ready", False)),
        "can_name_scoped_hardware_ppa_winners": bool(
            packet.get("can_name_scoped_hardware_ppa_winners", False)
        ),
        "can_name_hardware_ppa_winners": bool(packet.get("can_name_hardware_ppa_winners", False)),
        "deployment_target_selection_ready": bool(
            packet.get("deployment_target_selection_ready", False)
        ),
        "full_scf_numerical_gate_passed": bool(packet.get("full_scf_numerical_gate_passed", False)),
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "raw_decision_packet_flags": {
            "can_name_targeted_deployment_recommendation": raw_targeted,
            "can_name_final_recommendation": raw_final,
            "trusted_final_claim": raw_trusted_final,
            "deliverable_complete": raw_deliverable,
        },
        "safety_findings": safety_findings,
        "fpga_planning_status": fpga.get("status"),
        "asic_planning_status": asic.get("status"),
        "fpga_scoped_hardware_ppa_winner": fpga.get("scoped_hardware_ppa_winner"),
        "asic_scoped_hardware_ppa_winner": asic.get("scoped_hardware_ppa_winner"),
        "fpga_selected_target": fpga.get("selected_target", {}),
        "asic_selected_target": asic.get("selected_target", {}),
        "fpga_hardware_ppa_metrics": fpga.get("hardware_ppa_metrics", {}),
        "asic_hardware_ppa_metrics": asic.get("hardware_ppa_metrics", {}),
        "full_scf_numerical_gate": packet.get("full_scf_numerical_gate", {}),
        "full_scf_numerical_closure_workplan": packet.get("full_scf_numerical_closure_workplan", {}),
        "release_completion_gates": packet.get("release_completion_gates", {}),
        "final_claim_blockers": packet.get("final_claim_blockers", []),
        "required_next_evidence": packet.get("required_next_evidence", {}),
        "final_recommendation_required_next_evidence": packet.get(
            "final_recommendation_required_next_evidence",
            {},
        ),
        "forbidden_shortcuts": packet.get("forbidden_shortcuts", []),
        "status_artifact": status_artifact,
        "validation": {
            "present": bool(validation),
            "valid": report_validation_valid,
            "artifact_valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
            "report_safety_error_count": len(safety_findings),
        },
        "completion_claim": packet.get("completion_claim", "blocked" if present else "not_applicable"),
        "claim_boundary": (
            packet.get("claim_boundary")
            or "Deployment decision packet may name scoped hardware-PPA planning winners only; it cannot mark final deployment completion."
        ),
    }



def _dft_deployment_comparator_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional FPGA/ASIC deployment comparator artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_DEPLOYMENT_COMPARATOR_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    comparator = loaded.get("dft_deployment_comparator.json", {})
    validation = loaded.get("dft_deployment_comparator_validation.json", {})
    status_artifact = loaded.get("dft_deployment_comparator_status.json", {})
    present = bool(comparator)
    fpga = (
        comparator.get("fpga_recommendation", {})
        if isinstance(comparator.get("fpga_recommendation", {}), Mapping)
        else {}
    )
    asic = (
        comparator.get("asic_recommendation", {})
        if isinstance(comparator.get("asic_recommendation", {}), Mapping)
        else {}
    )
    cross_target = (
        comparator.get("cross_target_recommendation", {})
        if isinstance(comparator.get("cross_target_recommendation", {}), Mapping)
        else {}
    )
    target_recommendation_available_count = comparator.get("target_recommendation_available_count")
    if target_recommendation_available_count is None:
        target_recommendation_available_count = sum(
            1
            for item in (fpga, asic)
            if item.get("recommendation_kind") in {"unique_candidate", "best_physical_tie_set"}
        )
    cross_target_comparison_eligible = comparator.get("cross_target_comparison_eligible")
    if cross_target_comparison_eligible is None:
        cross_target_comparison_eligible = target_recommendation_available_count == 2
    deployment_completion_eligible = bool(cross_target_comparison_eligible)
    return {
        "schema_version": "dse.final_report.dft_deployment_comparator.v1",
        "present": present,
        "status": comparator.get("status") if present else "not_present",
        "artifacts": artifact_refs,
        "release_id": comparator.get("release_id"),
        "candidate_count": comparator.get("candidate_count"),
        "ranking_eligible_candidate_count": comparator.get("ranking_eligible_candidate_count"),
        "hardware_completion_eligible": bool(comparator.get("hardware_completion_eligible", False)),
        "candidate_specific_ppa_provenance_eligible": bool(
            comparator.get("candidate_specific_ppa_provenance_eligible", False)
        ),
        "target_recommendation_available_count": target_recommendation_available_count,
        "cross_target_comparison_eligible": bool(cross_target_comparison_eligible),
        "hardware_completion_eligible_for_deployment_comparison": bool(deployment_completion_eligible),
        "deployment_comparison_status": comparator.get("deployment_comparison_status"),
        "winner_resolution_status": comparator.get("winner_resolution_status"),
        "fpga_recommendation_status": fpga.get("status"),
        "fpga_recommendation_kind": fpga.get("recommendation_kind"),
        "fpga_top_candidate_count": fpga.get("top_candidate_count"),
        "fpga_top_candidate_ids": fpga.get("top_candidate_ids", []),
        "fpga_unique_winner": fpga.get("unique_winner"),
        "asic_recommendation_status": asic.get("status"),
        "asic_recommendation_kind": asic.get("recommendation_kind"),
        "asic_top_candidate_count": asic.get("top_candidate_count"),
        "asic_top_candidate_ids": asic.get("top_candidate_ids", []),
        "asic_unique_winner": asic.get("unique_winner"),
        "cross_target_recommendation_status": cross_target.get("status"),
        "single_cross_target_winner": cross_target.get("single_cross_target_winner"),
        "objective_required": cross_target.get("objective_required"),
        "non_physical_tie_breakers_used": bool(comparator.get("non_physical_tie_breakers_used", False)),
        "forbidden_tie_breakers": comparator.get("forbidden_tie_breakers", []),
        "target_recommendations": comparator.get("target_recommendations", {}),
        "status_artifact": status_artifact,
        "validation": {
            "present": bool(validation),
            "valid": validation.get("valid"),
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "completion_claim": "hardware_ppa_deployment_comparison_only" if present else "not_applicable",
        "claim_boundary": (
            comparator.get("claim_boundary")
            or "Deployment comparator is hardware-PPA recommendation-set evidence only."
        ),
    }


def _dft_deployment_selector_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional explicit-objective deployment selector artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_DEPLOYMENT_SELECTOR_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    selector = loaded.get("dft_deployment_selector.json", {})
    validation = loaded.get("dft_deployment_selector_validation.json", {})
    status_artifact = loaded.get("dft_deployment_selector_status.json", {})
    present = bool(selector)
    objective = (
        selector.get("objective", {})
        if isinstance(selector.get("objective", {}), Mapping)
        else {}
    )
    target_selection = (
        selector.get("target_selection", {})
        if isinstance(selector.get("target_selection", {}), Mapping)
        else {}
    )
    candidate_selection = (
        selector.get("candidate_selection", {})
        if isinstance(selector.get("candidate_selection", {}), Mapping)
        else {}
    )
    return {
        "schema_version": "dse.final_report.dft_deployment_selector.v1",
        "present": present,
        "status": selector.get("status") if present else "not_present",
        "selection_status": selector.get("selection_status"),
        "artifacts": artifact_refs,
        "objective_present": bool(selector.get("objective_present", False)),
        "objective_id": objective.get("objective_id"),
        "objective_deployment_target": objective.get("deployment_target"),
        "selected_deployment_target": selector.get("selected_deployment_target"),
        "selected_candidate_id": selector.get("selected_candidate_id"),
        "selected_candidate": selector.get("selected_candidate"),
        "target_selection_status": target_selection.get("status"),
        "candidate_selection_status": candidate_selection.get("status"),
        "candidate_selection_tie_candidate_ids": candidate_selection.get("tie_candidate_ids", []),
        "blocker_count": len(selector.get("blockers", []) or []) if present else None,
        "blockers": selector.get("blockers", []) if present else [],
        "non_physical_tie_breakers_used": bool(selector.get("non_physical_tie_breakers_used", False)),
        "forbidden_tie_breakers": selector.get("forbidden_tie_breakers", []),
        "status_artifact": status_artifact,
        "validation": {
            "present": bool(validation),
            "valid": validation.get("valid"),
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "completion_claim": "explicit_objective_deployment_selection_only" if present else "not_applicable",
        "claim_boundary": (
            selector.get("claim_boundary")
            or "Deployment selector can choose only with explicit objective evidence."
        ),
    }


def _dft_deployment_decision_summary_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional FPGA-vs-ASIC deployment decision-summary artifacts."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_DEPLOYMENT_DECISION_SUMMARY_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    summary = loaded.get("dft_deployment_decision_summary.json", {})
    validation = loaded.get("dft_deployment_decision_summary_validation.json", {})
    status_artifact = loaded.get("dft_deployment_decision_summary_status.json", {})
    present = bool(summary)
    best = (
        summary.get("best_current_deployment_recommendation", {})
        if isinstance(summary.get("best_current_deployment_recommendation", {}), Mapping)
        else {}
    )
    fpga = (
        summary.get("fpga_deployment_assessment", {})
        if isinstance(summary.get("fpga_deployment_assessment", {}), Mapping)
        else {}
    )
    asic = (
        summary.get("asic_deployment_assessment", {})
        if isinstance(summary.get("asic_deployment_assessment", {}), Mapping)
        else {}
    )
    return {
        "schema_version": "dse.final_report.dft_deployment_decision_summary.v1",
        "present": present,
        "status": summary.get("status") if present else "not_present",
        "artifacts": artifact_refs,
        "best_recommendation_status": best.get("status"),
        "recommended_target": best.get("recommended_target"),
        "recommended_candidate_id": best.get("recommended_candidate_id"),
        "selected_deployment_target": summary.get("selected_deployment_target"),
        "selected_candidate_id": summary.get("selected_candidate_id"),
        "objective_id": best.get("objective_id"),
        "fpga_target_model_binding_status": fpga.get("target_model_binding_status"),
        "fpga_selected_model_id": fpga.get("selected_model_id"),
        "fpga_blocker_ids": fpga.get("blocker_ids", []),
        "asic_target_model_binding_status": asic.get("target_model_binding_status"),
        "asic_selected_model_id": asic.get("selected_model_id"),
        "asic_blocker_ids": asic.get("blocker_ids", []),
        "status_artifact": status_artifact,
        "validation": {
            "present": bool(validation),
            "valid": validation.get("valid"),
            "error_count": len(validation.get("errors", []) or []) if validation else None,
        },
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "completion_claim": "explicit_objective_deployment_decision_summary_only" if present else "not_applicable",
        "claim_boundary": (
            summary.get("claim_boundary")
            or "Deployment decision summary rolls up comparator/selector/binding evidence without upgrading claims."
        ),
    }


def _deployment_recommendations_from_winner_resolution(
    winner_resolution: Mapping[str, Any],
    *,
    deployment_readiness: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Expose deployment-specific hardware-PPA recommendations without winner upgrade."""

    recommendations: Dict[str, Dict[str, Any]] = {}
    eligible = bool(winner_resolution.get("hardware_winner_resolution_eligible", False))
    readiness = deployment_readiness if isinstance(deployment_readiness, Mapping) else {}
    readiness_present = bool(readiness.get("present", False))
    readiness_deployments = (
        readiness.get("deployments", {})
        if isinstance(readiness.get("deployments", {}), Mapping)
        else {}
    )
    for deployment in ("fpga", "asic"):
        winner = winner_resolution.get(f"{deployment}_best_architecture")
        if eligible and isinstance(winner, Mapping) and winner.get("candidate_id"):
            readiness_row = (
                readiness_deployments.get(deployment, {})
                if isinstance(readiness_deployments.get(deployment, {}), Mapping)
                else {}
            )
            readiness_can_name = (
                readiness_row.get("can_name_hardware_ppa_winner") is True
                if readiness_present
                else None
            )
            target_evidence = (
                winner.get("deployment_target_evidence", {})
                if isinstance(winner.get("deployment_target_evidence", {}), Mapping)
                else {}
            )
            selected_target = _first_present(
                target_evidence.get("selected_target"),
                target_evidence.get("selected_device"),
                target_evidence.get("selected_part"),
                target_evidence.get("selected_target_library"),
            )
            deployment_target_summary = {
                "status": target_evidence.get("status"),
                "selected_target": selected_target,
                "observed_kernel_count": target_evidence.get("observed_kernel_count"),
                "expected_kernel_count": target_evidence.get("expected_kernel_count"),
                "targeted_kernel_count": target_evidence.get("targeted_kernel_count"),
                "all_major_kernel_consistency": target_evidence.get(
                    "all_major_kernel_consistency"
                ),
                "blocker_count": target_evidence.get("blocker_count"),
                "blockers": list(target_evidence.get("blockers", []) or [])[:10],
                "claim_boundary": target_evidence.get("claim_boundary"),
            }
            evidence_ids = [
                str(item)
                for item in winner.get("evidence_ids", []) or []
                if str(item)
            ]
            if "dft_architecture_winner_resolution.json" not in evidence_ids:
                evidence_ids.append("dft_architecture_winner_resolution.json")
            if readiness_present and "dft_hardware_deployment_recommendation_readiness.json" not in evidence_ids:
                evidence_ids.append("dft_hardware_deployment_recommendation_readiness.json")
            if readiness_present and readiness_can_name is not True:
                recommendations[deployment] = {
                    "deployment": deployment,
                    "status": "blocked_by_deployment_recommendation_readiness",
                    "candidate_id": None,
                    "blocked_candidate_id_hint": str(winner.get("candidate_id")),
                    "design_candidate_id": winner.get("design_candidate_id"),
                    "readiness_checked": True,
                    "readiness_status": readiness_row.get("status"),
                    "readiness_can_name_hardware_ppa_winner": False,
                    "required_next_evidence": list(readiness_row.get("required_next_evidence", []) or []),
                    "final_recommendation_required_next_evidence": list(
                        readiness_row.get("final_recommendation_required_next_evidence", []) or []
                    ),
                    "evidence_ids": evidence_ids,
                    "recommendation_scope": (
                        "deployment-specific hardware-PPA recommendation blocked "
                        "until readiness validates hard-gate, tool, and target evidence"
                    ),
                    "trusted_winner": False,
                    "trusted_final_claim": False,
                    "deliverable_complete": False,
                    "claim_boundary": readiness.get("claim_boundary")
                    or "Deployment readiness blocks hardware-PPA recommendation naming.",
                }
                continue
            recommendations[deployment] = {
                "deployment": deployment,
                "status": "resolved_hardware_ppa_deployment_recommendation",
                "candidate_id": str(winner.get("candidate_id")),
                "design_candidate_id": winner.get("design_candidate_id"),
                "rank": winner.get("rank"),
                "metrics": dict(winner.get("metrics", {}) if isinstance(winner.get("metrics", {}), Mapping) else {}),
                "deployment_target_evidence": deployment_target_summary,
                "selected_device": (
                    _first_present(target_evidence.get("selected_device"), selected_target)
                    if deployment == "fpga"
                    else None
                ),
                "selected_part": (
                    _first_present(target_evidence.get("selected_part"), selected_target)
                    if deployment == "fpga"
                    else None
                ),
                "selected_package": (
                    target_evidence.get("selected_package")
                    if deployment == "fpga"
                    else None
                ),
                "selected_target_library": (
                    _first_present(
                        target_evidence.get("selected_target_library"),
                        selected_target,
                    )
                    if deployment == "asic"
                    else None
                ),
                "evidence_ids": evidence_ids,
                "readiness_checked": readiness_present,
                "readiness_status": readiness_row.get("status") if readiness_present else None,
                "readiness_can_name_hardware_ppa_winner": readiness_can_name,
                "recommendation_scope": (
                    "deployment-specific candidate-stamped major-kernel hardware PPA; "
                    "not a full-SCF trusted winner or deliverable-complete claim"
                ),
                "trusted_winner": False,
                "trusted_final_claim": False,
                "deliverable_complete": False,
                "claim_boundary": winner.get("claim_boundary")
                or winner_resolution.get("claim_boundary")
                or "Deployment recommendation is hardware-PPA scoped only.",
            }
            continue

        recommendations[deployment] = {
            "deployment": deployment,
            "status": "blocked_no_resolved_hardware_ppa_deployment_recommendation",
            "candidate_id": None,
            "readiness_checked": readiness_present,
            "readiness_status": (
                readiness_deployments.get(deployment, {}).get("status")
                if isinstance(readiness_deployments.get(deployment, {}), Mapping)
                else None
            ),
            "readiness_can_name_hardware_ppa_winner": (
                readiness_deployments.get(deployment, {}).get("can_name_hardware_ppa_winner")
                if isinstance(readiness_deployments.get(deployment, {}), Mapping)
                else None
            ),
            "required_next_evidence": (
                winner_resolution.get("required_next_evidence", {}).get(deployment, [])
                if isinstance(winner_resolution.get("required_next_evidence", {}), Mapping)
                else []
            ),
            "recommendation_scope": (
                "deployment-specific hardware-PPA recommendation blocked until "
                "winner resolution is eligible"
            ),
            "trusted_winner": False,
            "trusted_final_claim": False,
            "deliverable_complete": False,
            "claim_boundary": winner_resolution.get("claim_boundary")
            or "Deployment recommendation is blocked by winner-resolution gates.",
        }

    resolved_count = sum(
        1
        for recommendation in recommendations.values()
        if recommendation.get("status") == "resolved_hardware_ppa_deployment_recommendation"
    )
    readiness_blocked_count = sum(
        1
        for recommendation in recommendations.values()
        if recommendation.get("status") == "blocked_by_deployment_recommendation_readiness"
    )
    return {
        "schema_version": "dse.final_report.deployment_recommendations.v1",
        "present": bool(winner_resolution.get("present", False)),
        "status": (
            "hardware_ppa_deployment_recommendations_available"
            if resolved_count == 2
            else "blocked_by_deployment_recommendation_readiness"
            if readiness_blocked_count
            else "partial_hardware_ppa_deployment_recommendations_available"
            if resolved_count
            else "blocked_no_hardware_ppa_deployment_recommendations"
        ),
        "recommendation_scope": "fpga_asic_hardware_ppa_only_not_full_scf_winner",
        "hardware_winner_resolution_eligible": eligible,
        "deployment_readiness_present": readiness_present,
        "deployment_readiness_status": readiness.get("status") if readiness_present else None,
        "deployment_readiness_can_name_hardware_ppa_winners": (
            readiness.get("can_name_hardware_ppa_winners") if readiness_present else None
        ),
        "resolved_recommendation_count": resolved_count,
        "readiness_blocked_recommendation_count": readiness_blocked_count,
        "recommendations": recommendations,
        "trusted_winner": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "source_artifacts": [
            "dft_architecture_winner_resolution.json",
            "dft_hardware_ppa_ranking.json",
            "dft_candidate_specific_ppa_provenance_audit.json",
        ],
        "claim_boundary": (
            "Deployment recommendations expose resolved FPGA/ASIC hardware-PPA "
            "choices for planning. They do not select a full-SCF trusted winner "
            "or mark deliverable completion."
        ),
    }


def _target_scoped_recommendation_sections(
    deployment_recommendations: Mapping[str, Any],
    *,
    ppa_ranking: Mapping[str, Any] | None = None,
) -> Dict[str, Dict[str, Any]]:
    """Build separate fail-closed FPGA/ASIC best/Pareto report sections."""

    ppa_ranking = ppa_ranking if isinstance(ppa_ranking, Mapping) else {}
    recommendations = (
        deployment_recommendations.get("recommendations", {})
        if isinstance(deployment_recommendations.get("recommendations", {}), Mapping)
        else {}
    )
    sections: Dict[str, Dict[str, Any]] = {}
    for target in ("fpga", "asic"):
        recommendation = (
            recommendations.get(target, {})
            if isinstance(recommendations.get(target, {}), Mapping)
            else {}
        )
        status = str(
            recommendation.get("status")
            or "blocked_no_target_scoped_recommendation"
        )
        ranking_rows = (
            ppa_ranking.get(f"{target}_ranking", [])
            if isinstance(ppa_ranking.get(f"{target}_ranking", []), list)
            else []
        )
        pareto_candidate_ids = [
            str(row.get("candidate_id"))
            for row in ranking_rows
            if isinstance(row, Mapping) and str(row.get("candidate_id") or "")
        ]
        blockers = list(recommendation.get("required_next_evidence", []) or [])
        blockers.extend(list(recommendation.get("final_recommendation_required_next_evidence", []) or []))
        if status != "resolved_hardware_ppa_deployment_recommendation":
            blockers.append(status)
        target_evidence = (
            recommendation.get("deployment_target_evidence", {})
            if isinstance(recommendation.get("deployment_target_evidence", {}), Mapping)
            else {}
        )
        sections[target] = {
            "schema_version": "dse.final_report.target_scoped_recommendation_section.v1",
            "target": target,
            "recommendation_kind": "best_or_pareto",
            "status": status,
            "candidate_id": recommendation.get("candidate_id"),
            "design_candidate_id": recommendation.get("design_candidate_id"),
            "deployment_boundary": "full_scf_evaluated_hybrid",
            "best": {
                "candidate_id": recommendation.get("candidate_id"),
                "design_candidate_id": recommendation.get("design_candidate_id"),
                "status": status,
                "metrics": dict(
                    recommendation.get("metrics", {})
                    if isinstance(recommendation.get("metrics", {}), Mapping)
                    else {}
                ),
            },
            "pareto": {
                "candidate_ids": pareto_candidate_ids,
                "candidate_count": len(pareto_candidate_ids),
                "ranking_artifact": "dft_hardware_ppa_ranking.json"
                if ppa_ranking.get("present")
                else None,
            },
            "architecture_modules": [],
            "mapping_layout": {},
            "runtime_co_schedule": {},
            "expected_metrics": dict(
                recommendation.get("metrics", {})
                if isinstance(recommendation.get("metrics", {}), Mapping)
                else {}
            ),
            "comparison_rationale": recommendation.get("recommendation_scope")
            or deployment_recommendations.get("recommendation_scope"),
            "evidence_level": (
                "target_scoped_hardware_ppa"
                if status == "resolved_hardware_ppa_deployment_recommendation"
                else "blocked"
            ),
            "deployment_target_evidence": dict(target_evidence),
            "evidence_ids": list(recommendation.get("evidence_ids", []) or []),
            "blockers": sorted({str(blocker) for blocker in blockers if str(blocker)}),
            "trusted_winner": False,
            "trusted_final_claim": False,
            "deliverable_complete": False,
            "claim_boundary": recommendation.get("claim_boundary")
            or (
                "Target-scoped recommendation section is hardware-PPA scoped "
                "and cannot mark a full-SCF trusted winner or deliverable completion."
            ),
        }
    return sections


def _deployment_recommendation_plan_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize proposal-only FPGA/ASIC deployment planning without upgrading claims."""

    rel_path, entry = _find_indexed_artifact(evidence_index, "deployment_recommendation_plan.json")
    payload = _load_json(run_dir / rel_path) if rel_path else {}
    queue_rel_path, queue_entry = _find_indexed_artifact(
        evidence_index,
        "dft_deployment_hard_gate_execution_queue.json",
    )
    queue_payload = _load_json(run_dir / queue_rel_path) if queue_rel_path else {}
    queue_validation_rel_path, queue_validation_entry = _find_indexed_artifact(
        evidence_index,
        "dft_deployment_hard_gate_execution_queue_validation.json",
    )
    queue_validation = _load_json(run_dir / queue_validation_rel_path) if queue_validation_rel_path else {}
    queue_status_rel_path, queue_status_entry = _find_indexed_artifact(
        evidence_index,
        "dft_deployment_hard_gate_execution_queue_status.json",
    )
    queue_status = _load_json(run_dir / queue_status_rel_path) if queue_status_rel_path else {}
    target_summaries = (
        payload.get("target_summaries", {})
        if isinstance(payload.get("target_summaries", {}), Mapping)
        else {}
    )
    recommendations = (
        payload.get("candidate_recommendations", [])
        if isinstance(payload.get("candidate_recommendations", []), list)
        else []
    )
    work_items = (
        payload.get("hard_gate_work_items", [])
        if isinstance(payload.get("hard_gate_work_items", []), list)
        else []
    )
    target_work_item_counts = (
        payload.get("target_work_item_counts", {})
        if isinstance(payload.get("target_work_item_counts", {}), Mapping)
        else {}
    )
    present = bool(payload)
    return {
        "schema_version": "dse.final_report.deployment_recommendation_plan.v1",
        "present": present,
        "artifact": rel_path,
        "exists": bool(entry.get("exists", False)),
        "sha256": entry.get("sha256"),
        "status": payload.get("status", "not_present"),
        "trusted_timing_sample_count": payload.get("trusted_timing_sample_count", 0),
        "candidate_recommendation_count": len(recommendations),
        "hard_gate_work_item_count": len(work_items),
        "hard_gates_pending": bool(payload.get("hard_gates_pending", bool(work_items))),
        "deployment_hard_gate_closure_status": payload.get(
            "deployment_hard_gate_closure_status",
            "hard_gates_pending" if work_items else "blocked",
        ),
        "target_work_item_counts": dict(target_work_item_counts),
        "target_summaries": dict(target_summaries),
        "forbidden_claims": list(payload.get("forbidden_claims", []) or []),
        "next_actions": list(payload.get("next_actions", []) or []),
        "hard_gate_execution_queue": {
            "present": bool(queue_payload),
            "artifact": queue_rel_path,
            "exists": bool(queue_entry.get("exists", False)),
            "sha256": queue_entry.get("sha256"),
            "status_artifact": queue_status_rel_path,
            "validation_artifact": queue_validation_rel_path,
            "queue_status": queue_payload.get("status", queue_status.get("queue_status")),
            "queue_materialization_status": queue_payload.get(
                "queue_materialization_status",
                queue_status.get("queue_materialization_status"),
            ),
            "deployment_hard_gate_closure_status": queue_payload.get(
                "deployment_hard_gate_closure_status",
                queue_status.get("deployment_hard_gate_closure_status", "not_materialized"),
            ),
            "hard_gates_pending": bool(
                queue_payload.get("hard_gates_pending", queue_status.get("hard_gates_pending", False))
            ),
            "status": queue_status.get("status"),
            "validation_status": queue_status.get("validation_status"),
            "work_item_count": queue_payload.get("work_item_count", queue_status.get("work_item_count")),
            "candidate_count": queue_payload.get("candidate_count", queue_status.get("candidate_count")),
            "major_kernel_count": queue_payload.get("major_kernel_count", queue_status.get("major_kernel_count")),
            "target_work_item_counts": dict(
                queue_payload.get("target_work_item_counts", queue_status.get("target_work_item_counts", {}))
                if isinstance(
                    queue_payload.get("target_work_item_counts", queue_status.get("target_work_item_counts", {})),
                    Mapping,
                )
                else {}
            ),
            "validation": {
                "present": bool(queue_validation),
                "valid": queue_validation.get("valid"),
                "error_count": len(queue_validation.get("errors", []) or []) if queue_validation else None,
                "exists": bool(queue_validation_entry.get("exists", False)),
                "sha256": queue_validation_entry.get("sha256"),
            },
            "status_ref": {
                "present": bool(queue_status),
                "exists": bool(queue_status_entry.get("exists", False)),
                "sha256": queue_status_entry.get("sha256"),
            },
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": (
                queue_payload.get("claim_boundary")
                or "DFT deployment hard-gate execution queue was not indexed for this Step5 run."
            ),
        },
        "trusted_deployment_claim": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "claim_boundary": payload.get(
            "claim_boundary",
            "No deployment recommendation plan was indexed for this Step5 run.",
        ),
    }


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _top_counted_items(payload: Any, *, limit: int = 8) -> List[Dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    rows: List[Dict[str, Any]] = []
    for key, value in payload.items():
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        rows.append({"id": str(key), "count": count})
    return sorted(rows, key=lambda item: (-item["count"], item["id"]))[:limit]


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item)]


def _unique_string_list(value: Any) -> List[str]:
    return sorted(set(_string_list(value)))


def _candidate_ids_from_rows(payload: Mapping[str, Any], *row_keys: str) -> List[str]:
    candidate_ids: set[str] = set()
    for row_key in row_keys:
        rows = payload.get(row_key, [])
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            candidate_id = row.get("candidate_id")
            if candidate_id:
                candidate_ids.add(str(candidate_id))
    return sorted(candidate_ids)


def _full_scf_candidate_ids(full_scf: Mapping[str, Any]) -> List[str]:
    candidate_ids = set(_string_list(full_scf.get("candidate_ids", [])))
    candidate_ids.update(
        _candidate_ids_from_rows(full_scf, "candidate_records", "row_records")
    )
    return sorted(candidate_ids)


def _deployment_candidate_alignment(
    deployment_rows: Mapping[str, Mapping[str, Any]],
    *,
    candidate_set_ids: Sequence[str],
    candidate_set_trusted: bool,
    full_scf_ids: Sequence[str],
    full_scf_present: bool,
) -> Dict[str, Any]:
    """Check deployment recommendations remain inside current release/full-SCF sets."""

    candidate_set = {str(candidate_id) for candidate_id in candidate_set_ids}
    full_scf_set = {str(candidate_id) for candidate_id in full_scf_ids}
    recommendation_candidate_ids = {
        deployment: str(row.get("candidate_id"))
        for deployment, row in deployment_rows.items()
        if isinstance(row, Mapping) and row.get("candidate_id")
    }
    blockers: List[Dict[str, Any]] = []
    per_deployment: Dict[str, Dict[str, Any]] = {}
    missing_from_candidate_set: Dict[str, List[str]] = {}
    missing_from_full_scf: Dict[str, List[str]] = {}

    for deployment, row in deployment_rows.items():
        candidate_id = (
            str(row.get("candidate_id"))
            if isinstance(row, Mapping) and row.get("candidate_id")
            else None
        )
        row_blockers: List[Dict[str, Any]] = []
        if not candidate_id:
            candidate_set_membership = "no_recommendation_candidate"
            full_scf_membership = "no_recommendation_candidate"
        else:
            if candidate_set_trusted:
                candidate_set_membership = (
                    "present" if candidate_id in candidate_set else "missing"
                )
                if candidate_id not in candidate_set:
                    missing_from_candidate_set[deployment] = [candidate_id]
                    row_blockers.append({
                        "blocker_id": "deployment_candidate_not_in_release_candidate_set",
                        "deployment": deployment,
                        "candidate_id": candidate_id,
                        "reason": (
                            "Deployment recommendation candidate must be present "
                            "in the reconciled release/binding/trial candidate set."
                        ),
                    })
            else:
                candidate_set_membership = "not_checked_candidate_set_gate_untrusted"
                row_blockers.append({
                    "blocker_id": "deployment_candidate_set_gate_not_trusted",
                    "deployment": deployment,
                    "candidate_id": candidate_id,
                    "reason": (
                        "Deployment recommendation alignment cannot be trusted "
                        "until the candidate-set consistency gate passes validation."
                    ),
                })

            if full_scf_present and full_scf_set:
                full_scf_membership = (
                    "present" if candidate_id in full_scf_set else "missing"
                )
                if candidate_id not in full_scf_set:
                    missing_from_full_scf[deployment] = [candidate_id]
                    row_blockers.append({
                        "blocker_id": "deployment_candidate_not_in_full_scf_candidate_set",
                        "deployment": deployment,
                        "candidate_id": candidate_id,
                        "reason": (
                            "Deployment recommendation candidate must be covered "
                            "by the full-SCF end-to-end comparison candidate set."
                        ),
                    })
            else:
                full_scf_membership = "not_checked_missing_full_scf_candidate_ids"
                row_blockers.append({
                    "blocker_id": "full_scf_candidate_set_missing",
                    "deployment": deployment,
                    "candidate_id": candidate_id,
                    "reason": (
                        "Full-SCF comparison must expose candidate_ids before "
                        "deployment recommendation alignment can be trusted."
                    ),
                })

        per_deployment[deployment] = {
            "candidate_id": candidate_id,
            "candidate_set_membership": candidate_set_membership,
            "full_scf_candidate_membership": full_scf_membership,
            "evidence_alignment_ready": bool(
                candidate_id
                and candidate_set_membership == "present"
                and full_scf_membership == "present"
            ),
            "blockers": row_blockers,
        }
        blockers.extend(row_blockers)

    if not recommendation_candidate_ids:
        status = "deployment_candidate_alignment_not_checked_no_recommendations"
    elif not blockers:
        status = "deployment_candidate_alignment_passed"
    elif any(
        blocker.get("blocker_id")
        in {
            "deployment_candidate_not_in_release_candidate_set",
            "deployment_candidate_not_in_full_scf_candidate_set",
        }
        for blocker in blockers
    ):
        status = "deployment_candidate_alignment_mismatch"
    elif any(
        blocker.get("blocker_id") == "deployment_candidate_set_gate_not_trusted"
        for blocker in blockers
    ):
        status = "deployment_candidate_alignment_blocked_candidate_set_gate"
    elif any(
        blocker.get("blocker_id") == "full_scf_candidate_set_missing"
        for blocker in blockers
    ):
        status = "deployment_candidate_alignment_blocked_missing_full_scf_candidate_ids"
    else:
        status = "deployment_candidate_alignment_blocked"

    return {
        "status": status,
        "checked": bool(recommendation_candidate_ids),
        "passed": status == "deployment_candidate_alignment_passed",
        "recommendation_candidate_ids": recommendation_candidate_ids,
        "candidate_set_candidate_count": len(candidate_set),
        "full_scf_candidate_count": len(full_scf_set),
        "missing_from_candidate_set": missing_from_candidate_set,
        "missing_from_full_scf": missing_from_full_scf,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "per_deployment": per_deployment,
    }


def _deployment_source_consensus(
    source_rows: Mapping[str, Mapping[str, Mapping[str, Any]]],
    *,
    recommendation_bearing_deployments: Iterable[str] = (),
) -> Dict[str, Any]:
    """Check that deployment recommendation sources do not disagree on identity."""

    recommendation_deployments = {
        str(deployment)
        for deployment in recommendation_bearing_deployments
        if str(deployment)
    }
    per_deployment: Dict[str, Dict[str, Any]] = {}
    blockers: List[Dict[str, Any]] = []
    for deployment, sources in source_rows.items():
        recommendation_bearing = deployment in recommendation_deployments
        candidate_by_source = {
            source: str(row.get("candidate_id"))
            for source, row in sources.items()
            if isinstance(row, Mapping) and row.get("candidate_id")
        }
        design_by_source = {
            source: str(row.get("design_candidate_id"))
            for source, row in sources.items()
            if isinstance(row, Mapping) and row.get("design_candidate_id")
        }
        candidate_values = sorted(set(candidate_by_source.values()))
        design_values = sorted(set(design_by_source.values()))
        row_blockers: List[Dict[str, Any]] = []
        if len(candidate_values) > 1:
            row_blockers.append({
                "blocker_id": "deployment_candidate_source_mismatch",
                "deployment": deployment,
                "candidate_id_by_source": candidate_by_source,
                "reason": (
                    "Deployment recommendation sources disagree on candidate_id; "
                    "Step5 must not silently prefer one source."
                ),
            })
        if len(design_values) > 1:
            row_blockers.append({
                "blocker_id": "deployment_design_source_mismatch",
                "deployment": deployment,
                "design_candidate_id_by_source": design_by_source,
                "reason": (
                    "Deployment recommendation sources disagree on design_candidate_id; "
                    "Step5 must not silently prefer one source."
                ),
            })
        if row_blockers:
            status = "deployment_source_consensus_mismatch"
        elif not recommendation_bearing:
            status = "deployment_source_consensus_not_checked_no_recommendation"
        elif len(candidate_by_source) >= 2 and len(design_by_source) >= 2:
            status = "deployment_source_consensus_passed"
        elif len(candidate_by_source) == 1:
            status = "deployment_source_consensus_not_checked_insufficient_sources"
            row_blockers.append({
                "blocker_id": "deployment_source_consensus_insufficient_sources",
                "deployment": deployment,
                "candidate_id_by_source": candidate_by_source,
                "reason": (
                    "Recommendation-bearing deployments need at least two "
                    "independent candidate identity sources before Step5 can "
                    "treat source consensus as passed."
                ),
            })
        elif candidate_by_source:
            status = "deployment_source_consensus_not_checked_insufficient_design_sources"
            row_blockers.append({
                "blocker_id": "deployment_source_consensus_insufficient_design_sources",
                "deployment": deployment,
                "design_candidate_id_by_source": design_by_source,
                "reason": (
                    "Recommendation-bearing deployments need at least two "
                    "independent design_candidate_id sources before Step5 can "
                    "treat source consensus as passed."
                ),
            })
        else:
            status = "deployment_source_consensus_not_checked_no_candidate"
            row_blockers.append({
                "blocker_id": "deployment_source_consensus_missing_candidate_sources",
                "deployment": deployment,
                "reason": (
                    "A recommendation-bearing deployment had no candidate "
                    "identity source rows available for consensus."
                ),
            })
        per_deployment[deployment] = {
            "status": status,
            "passed": status == "deployment_source_consensus_passed",
            "recommendation_bearing": recommendation_bearing,
            "source_count": len(candidate_by_source),
            "design_source_count": len(design_by_source),
            "candidate_id_by_source": candidate_by_source,
            "design_candidate_id_by_source": design_by_source,
            "consensus_candidate_id": candidate_values[0] if len(candidate_values) == 1 else None,
            "consensus_design_candidate_id": design_values[0] if len(design_values) == 1 else None,
            "blockers": row_blockers,
        }
        blockers.extend(row_blockers)

    recommendation_rows = [
        row
        for deployment, row in per_deployment.items()
        if deployment in recommendation_deployments
    ]
    mismatch_blockers = [
        blocker
        for blocker in blockers
        if blocker.get("blocker_id")
        in {
            "deployment_candidate_source_mismatch",
            "deployment_design_source_mismatch",
        }
    ]
    if not recommendation_deployments:
        status = "deployment_source_consensus_not_checked_no_candidates"
    elif mismatch_blockers:
        status = "deployment_source_consensus_mismatch"
    elif recommendation_rows and all(
        row.get("status") == "deployment_source_consensus_passed"
        for row in recommendation_rows
    ):
        status = "deployment_source_consensus_passed"
    elif any(
        row.get("status") == "deployment_source_consensus_not_checked_insufficient_sources"
        for row in recommendation_rows
    ):
        status = "deployment_source_consensus_not_checked_insufficient_sources"
    elif any(
        row.get("status")
        == "deployment_source_consensus_not_checked_insufficient_design_sources"
        for row in recommendation_rows
    ):
        status = "deployment_source_consensus_not_checked_insufficient_design_sources"
    else:
        status = "deployment_source_consensus_not_checked_no_candidate_sources"

    return {
        "status": status,
        "checked": bool(recommendation_deployments),
        "passed": status == "deployment_source_consensus_passed",
        "recommendation_bearing_deployments": sorted(recommendation_deployments),
        "recommendation_bearing_deployment_count": len(recommendation_deployments),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "per_deployment": per_deployment,
    }


def _normalize_fpga_target_token(value: Any) -> str:
    token = str(value or "").strip().upper()
    if token.startswith("XC"):
        token = token[2:]
    return token


def _fpga_device_part_compatible(device: Any, part: Any) -> bool:
    device_token = _normalize_fpga_target_token(device)
    part_token = _normalize_fpga_target_token(part)
    if not device_token or not part_token:
        return True
    return (
        device_token == part_token
        or device_token.startswith(part_token)
        or part_token.startswith(device_token)
    )


def _deployment_target_consensus(
    target_rows: Mapping[str, Mapping[str, Mapping[str, Any]]],
    *,
    recommendation_bearing_deployments: Iterable[str] = (),
) -> Dict[str, Any]:
    """Check that deployment target identity fields are self-consistent."""

    recommendation_deployments = {
        str(deployment)
        for deployment in recommendation_bearing_deployments
        if str(deployment)
    }
    per_deployment: Dict[str, Dict[str, Any]] = {}
    blockers: List[Dict[str, Any]] = []
    for deployment, sources in target_rows.items():
        recommendation_bearing = deployment in recommendation_deployments
        row_blockers: List[Dict[str, Any]] = []
        device_by_source = {
            source: str(row.get("selected_device"))
            for source, row in sources.items()
            if isinstance(row, Mapping) and row.get("selected_device")
        }
        part_by_source = {
            source: str(row.get("selected_part"))
            for source, row in sources.items()
            if isinstance(row, Mapping) and row.get("selected_part")
        }
        package_by_source = {
            source: str(row.get("selected_package"))
            for source, row in sources.items()
            if isinstance(row, Mapping) and row.get("selected_package")
        }
        target_library_by_source = {
            source: str(row.get("selected_target_library"))
            for source, row in sources.items()
            if isinstance(row, Mapping) and row.get("selected_target_library")
        }
        target_identity_source_counts = {
            "selected_device": len(device_by_source),
            "selected_part": len(part_by_source),
            "selected_package": len(package_by_source),
            "selected_target_library": len(target_library_by_source),
        }
        critical_identity_fields = (
            ("selected_device", "selected_part", "selected_package")
            if deployment == "fpga"
            else ("selected_target_library",)
        )
        overlapping_target_identity_fields = [
            field
            for field in critical_identity_fields
            if target_identity_source_counts.get(field, 0) >= 2
        ]
        passing_target_identity_fields = (
            [
                field
                for field in overlapping_target_identity_fields
                if field in {"selected_device", "selected_part"}
            ]
            if deployment == "fpga"
            else list(overlapping_target_identity_fields)
        )

        if deployment == "fpga":
            normalized_devices = sorted({
                _normalize_fpga_target_token(value)
                for value in device_by_source.values()
                if _normalize_fpga_target_token(value)
            })
            normalized_parts = sorted({
                _normalize_fpga_target_token(value)
                for value in part_by_source.values()
                if _normalize_fpga_target_token(value)
            })
            if len(normalized_devices) > 1:
                row_blockers.append({
                    "blocker_id": "fpga_selected_device_source_mismatch",
                    "deployment": deployment,
                    "selected_device_by_source": device_by_source,
                    "normalized_devices": normalized_devices,
                    "reason": (
                        "FPGA target sources disagree on selected_device; "
                        "Step5 must not silently combine incompatible device identities."
                    ),
                })
            if len(normalized_parts) > 1:
                row_blockers.append({
                    "blocker_id": "fpga_selected_part_source_mismatch",
                    "deployment": deployment,
                    "selected_part_by_source": part_by_source,
                    "normalized_parts": normalized_parts,
                    "reason": (
                        "FPGA target sources disagree on selected_part; "
                        "the selected FPGA model/package must be reconciled."
                    ),
                })
            for source, row in sources.items():
                if not isinstance(row, Mapping):
                    continue
                device = row.get("selected_device")
                part = row.get("selected_part")
                if device and part and not _fpga_device_part_compatible(device, part):
                    row_blockers.append({
                        "blocker_id": "fpga_selected_device_part_inconsistent",
                        "deployment": deployment,
                        "source": source,
                        "selected_device": str(device),
                        "selected_part": str(part),
                        "reason": (
                            "A single FPGA target source reports selected_device "
                            "and selected_part that do not describe the same model."
                        ),
                    })
        elif deployment == "asic":
            libraries = sorted(set(target_library_by_source.values()))
            if len(libraries) > 1:
                row_blockers.append({
                    "blocker_id": "asic_target_library_source_mismatch",
                    "deployment": deployment,
                    "selected_target_library_by_source": target_library_by_source,
                    "reason": (
                        "ASIC target sources disagree on selected target library; "
                        "Step5 must not silently combine incompatible ASIC targets."
                    ),
                })

        if row_blockers:
            status = "deployment_target_consensus_mismatch"
        elif not recommendation_bearing:
            status = "deployment_target_consensus_not_checked_no_recommendation"
        elif passing_target_identity_fields:
            status = "deployment_target_consensus_passed"
        elif len(sources) == 1:
            status = "deployment_target_consensus_not_checked_insufficient_sources"
            row_blockers.append({
                "blocker_id": "deployment_target_consensus_insufficient_sources",
                "deployment": deployment,
                "target_sources": sorted(str(source) for source in sources),
                "reason": (
                    "Recommendation-bearing deployments need at least two "
                    "independent target identity sources before Step5 can treat "
                    "target consensus as passed."
                ),
            })
        elif sources:
            status = "deployment_target_consensus_not_checked_sparse_target_identity"
            row_blockers.append({
                "blocker_id": "deployment_target_consensus_sparse_target_identity",
                "deployment": deployment,
                "target_sources": sorted(str(source) for source in sources),
                "target_identity_source_counts": target_identity_source_counts,
                "reason": (
                    "Recommendation-bearing deployments need at least two "
                    "independent sources for the same selected target identity "
                    "field before Step5 can treat target consensus as passed."
                ),
            })
        else:
            status = "deployment_target_consensus_not_checked_no_target"
            row_blockers.append({
                "blocker_id": "deployment_target_consensus_missing_target_sources",
                "deployment": deployment,
                "reason": (
                    "A recommendation-bearing deployment had no selected target "
                    "source rows available for consensus."
                ),
            })
        per_deployment[deployment] = {
            "status": status,
            "passed": status == "deployment_target_consensus_passed",
            "recommendation_bearing": recommendation_bearing,
            "source_count": len(sources),
            "selected_device_by_source": device_by_source,
            "selected_part_by_source": part_by_source,
            "selected_package_by_source": package_by_source,
            "selected_target_library_by_source": target_library_by_source,
            "target_identity_source_counts": target_identity_source_counts,
            "overlapping_target_identity_fields": overlapping_target_identity_fields,
            "passing_target_identity_fields": passing_target_identity_fields,
            "blockers": row_blockers,
        }
        blockers.extend(row_blockers)

    recommendation_rows = [
        row
        for deployment, row in per_deployment.items()
        if deployment in recommendation_deployments
    ]
    mismatch_blockers = [
        blocker
        for blocker in blockers
        if blocker.get("blocker_id")
        in {
            "fpga_selected_device_source_mismatch",
            "fpga_selected_part_source_mismatch",
            "fpga_selected_device_part_inconsistent",
            "asic_target_library_source_mismatch",
        }
    ]
    if not recommendation_deployments:
        status = "deployment_target_consensus_not_checked_no_targets"
    elif mismatch_blockers:
        status = "deployment_target_consensus_mismatch"
    elif recommendation_rows and all(
        row.get("status") == "deployment_target_consensus_passed"
        for row in recommendation_rows
    ):
        status = "deployment_target_consensus_passed"
    elif any(
        row.get("status") == "deployment_target_consensus_not_checked_insufficient_sources"
        for row in recommendation_rows
    ):
        status = "deployment_target_consensus_not_checked_insufficient_sources"
    elif any(
        row.get("status")
        == "deployment_target_consensus_not_checked_sparse_target_identity"
        for row in recommendation_rows
    ):
        status = "deployment_target_consensus_not_checked_sparse_target_identity"
    else:
        status = "deployment_target_consensus_not_checked_no_target_sources"

    return {
        "status": status,
        "checked": bool(recommendation_deployments),
        "passed": status == "deployment_target_consensus_passed",
        "recommendation_bearing_deployments": sorted(recommendation_deployments),
        "recommendation_bearing_deployment_count": len(recommendation_deployments),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "per_deployment": per_deployment,
    }


def _deployment_target_reconciliation_workplan(
    deployment_rows: Mapping[str, Mapping[str, Any]],
    deployment_target_consensus: Mapping[str, Any],
) -> Dict[str, Any]:
    """Turn target-consensus blockers into explicit follow-up work items."""

    per_deployment = (
        deployment_target_consensus.get("per_deployment", {})
        if isinstance(deployment_target_consensus.get("per_deployment", {}), Mapping)
        else {}
    )
    work_items: List[Dict[str, Any]] = []
    for deployment, consensus_row in per_deployment.items():
        if not isinstance(consensus_row, Mapping):
            continue
        if consensus_row.get("recommendation_bearing") is not True:
            continue
        if consensus_row.get("passed") is True:
            continue
        recommendation = (
            deployment_rows.get(deployment, {})
            if isinstance(deployment_rows.get(deployment, {}), Mapping)
            else {}
        )
        candidate_id = recommendation.get("candidate_id")
        blocker_ids = [
            str(blocker.get("blocker_id"))
            for blocker in consensus_row.get("blockers", []) or []
            if isinstance(blocker, Mapping) and blocker.get("blocker_id")
        ]
        if deployment == "fpga":
            required_action = (
                "Select one FPGA target identity, then regenerate or attach "
                "candidate-specific Vivado synthesis/implementation evidence "
                "for every major claimed kernel on that target; alternatively "
                "correct the target-feasibility/coordination hints to match the "
                "already attached per-kernel Vivado evidence."
            )
            required_gate_sequence = [
                "golden_correctness",
                "hls_csim_or_rtl_sim",
                "hls_csynth_or_rtl_synth",
                "vivado_synthesis",
                "vivado_implementation",
            ]
        else:
            required_action = (
                "Select one ASIC target-library identity, then regenerate or "
                "attach candidate-specific DC synthesis/timing/area evidence "
                "for every major claimed kernel on that library; alternatively "
                "correct coordination hints to match the attached DC evidence."
            )
            required_gate_sequence = [
                "golden_correctness",
                "hls_csim_or_rtl_sim",
                "hls_csynth_or_rtl_synth",
                "dc_synthesis",
                "dc_timing_area",
            ]
        work_items.append({
            "work_item_id": f"deployment-target-reconcile::{deployment}::{candidate_id or 'unbound'}",
            "deployment": deployment,
            "candidate_id": candidate_id,
            "design_candidate_id": recommendation.get("design_candidate_id"),
            "status": "blocked_pending_target_reconciliation",
            "target_consensus_status": consensus_row.get("status"),
            "blocker_ids": blocker_ids,
            "blockers": list(consensus_row.get("blockers", []) or [])[:10],
            "selected_device_by_source": consensus_row.get("selected_device_by_source", {}),
            "selected_part_by_source": consensus_row.get("selected_part_by_source", {}),
            "selected_package_by_source": consensus_row.get("selected_package_by_source", {}),
            "selected_target_library_by_source": consensus_row.get(
                "selected_target_library_by_source",
                {},
            ),
            "target_identity_source_counts": consensus_row.get(
                "target_identity_source_counts",
                {},
            ),
            "required_action": required_action,
            "required_gate_sequence": required_gate_sequence,
            "expected_kernel_count": recommendation.get("expected_kernel_count"),
            "targeted_kernel_count": recommendation.get("targeted_kernel_count"),
            "not_a_step3_queue_entry": True,
            "provenance_only": True,
            "execution_allowed": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": (
                "Target reconciliation work items are coordination/runbook "
                "records only. They do not execute tools, prove PPA, or upgrade "
                "FPGA/ASIC/full-SCF claims."
            ),
        })

    status = (
        "target_reconciliation_required"
        if work_items
        else "target_reconciliation_not_required"
    )
    return {
        "schema_version": "dse.final_report.dft_deployment_target_reconciliation_workplan.v1",
        "status": status,
        "required": bool(work_items),
        "work_item_count": len(work_items),
        "work_items": work_items,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "This workplan translates target-consensus blockers into manual or "
            "parallel closure tasks. It is not hardware evidence and cannot "
            "select a final deployment target by itself."
        ),
    }


def _dft_deployment_decision_support_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
    *,
    deployment_recommendations: Mapping[str, Any],
) -> Dict[str, Any]:
    """Summarize optional FPGA/ASIC coordination artifacts fail-closed."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_DEPLOYMENT_DECISION_SUPPORT_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    deployment_summary = loaded.get("dft_fpga_asic_deployment_summary.json", {})
    deployment_validation = loaded.get("dft_fpga_asic_deployment_summary_validation.json", {})
    target_feasibility = loaded.get("dft_deployment_target_feasibility.json", {})
    target_validation = loaded.get("dft_deployment_target_feasibility_validation.json", {})
    coordination = loaded.get("dft_deployment_coordination_summary.json", {})
    coordination_validation = loaded.get("dft_deployment_coordination_summary_validation.json", {})
    deployment_summary_validation_valid = (
        deployment_validation.get("valid") is True if deployment_summary else None
    )
    target_feasibility_validation_valid = (
        target_validation.get("valid") is True if target_feasibility else None
    )
    coordination_validation_valid = (
        coordination_validation.get("valid") is True if coordination else None
    )
    deployment_sidecar_validation_blockers: list[Dict[str, Any]] = []
    for label, artifact_name, payload, validation, valid in (
        (
            "deployment_summary",
            "dft_fpga_asic_deployment_summary.json",
            deployment_summary,
            deployment_validation,
            deployment_summary_validation_valid,
        ),
        (
            "target_feasibility",
            "dft_deployment_target_feasibility.json",
            target_feasibility,
            target_validation,
            target_feasibility_validation_valid,
        ),
        (
            "coordination",
            "dft_deployment_coordination_summary.json",
            coordination,
            coordination_validation,
            coordination_validation_valid,
        ),
    ):
        if payload and valid is not True:
            deployment_sidecar_validation_blockers.append(
                {
                    "blocker_id": f"deployment_{label}_validation_not_valid",
                    "artifact": artifact_name,
                    "validation_valid": valid,
                    "validation_errors": list(validation.get("errors", []) or []),
                }
            )
    deployment_sidecar_validation_passed = not deployment_sidecar_validation_blockers
    full_scf_artifact_name = (
        "full_scf_end_to_end_comparison.json"
        if loaded.get("full_scf_end_to_end_comparison.json")
        else "full_scf_end_to_end_comparison.recheck.json"
        if loaded.get("full_scf_end_to_end_comparison.recheck.json")
        else None
    )
    full_scf_validation_artifact_name = (
        "full_scf_end_to_end_comparison_validation.json"
        if full_scf_artifact_name == "full_scf_end_to_end_comparison.json"
        else "full_scf_end_to_end_comparison.recheck_validation.json"
        if full_scf_artifact_name == "full_scf_end_to_end_comparison.recheck.json"
        else None
    )
    full_scf_status_artifact_name = (
        "full_scf_end_to_end_comparison_status.json"
        if full_scf_artifact_name == "full_scf_end_to_end_comparison.json"
        else "full_scf_end_to_end_comparison.recheck_status.json"
        if full_scf_artifact_name == "full_scf_end_to_end_comparison.recheck.json"
        else None
    )
    full_scf = loaded.get(full_scf_artifact_name or "", {})
    full_scf_validation = loaded.get(full_scf_validation_artifact_name or "", {})
    full_scf_status_artifact_payload = loaded.get(full_scf_status_artifact_name or "", {})
    full_scf_artifact = (
        artifact_refs.get(full_scf_artifact_name or "", {}).get("path")
        if full_scf_artifact_name
        else None
    )
    full_scf_sections = build_full_scf_numerical_readiness_sections(
        full_scf,
        validation=full_scf_validation,
        status_artifact=full_scf_status_artifact_payload,
        artifact=full_scf_artifact,
        validation_artifact=(
            artifact_refs.get(full_scf_validation_artifact_name or "", {}).get("path")
            if full_scf_validation_artifact_name
            else None
        ),
        status_artifact_path=(
            artifact_refs.get(full_scf_status_artifact_name or "", {}).get("path")
            if full_scf_status_artifact_name
            else None
        ),
    )
    numerical_evidence = loaded.get("numerical_correctness_evidence.json", {})
    candidate_set_consistency = loaded.get("dft_candidate_set_consistency.json", {})
    candidate_set_consistency_validation = loaded.get("dft_candidate_set_consistency_validation.json", {})
    goal_audit = loaded.get("dft_scf_hardware_goal_completion_audit_current.json", {})
    dse_goal_audit = loaded.get("dft_scf_hardware_dse_goal_audit_current.json", {})
    run_status = loaded.get("status.json", {})
    blocker_report = loaded.get("blocker_report.json", {})
    blocker_report_source_producer_artifact_refs = (
        dict(blocker_report.get("source_producer_artifact_refs", {}))
        if isinstance(blocker_report.get("source_producer_artifact_refs", {}), Mapping)
        else {}
    )
    def _append_lane_unique(
        lane_summary: Dict[str, Any],
        field: str,
        value: Any,
    ) -> None:
        text = str(value or "")
        if not text:
            return
        values = lane_summary.setdefault(field, [])
        if text not in values:
            values.append(text)

    def _merge_lane_counter_map(
        lane_summary: Dict[str, Any],
        field: str,
        value: Any,
    ) -> None:
        if not isinstance(value, Mapping):
            return
        counts = lane_summary.setdefault(field, {})
        for key, count in value.items():
            key_text = str(key)
            counts[key_text] = int(counts.get(key_text, 0) or 0) + int(count or 0)

    blocker_report_source_lane_summary: Dict[str, Dict[str, Any]] = {}
    for artifact_name, artifact_ref in blocker_report_source_producer_artifact_refs.items():
        if not isinstance(artifact_ref, Mapping):
            continue
        source_lane = str(artifact_ref.get("source_lane") or "unknown")
        lane_summary = blocker_report_source_lane_summary.setdefault(
            source_lane,
            {
                "artifact_count": 0,
                "artifact_names": [],
                "statuses": [],
                "claimable_count": 0,
                "deliverable_complete_count": 0,
                "claim_upgrade_allowed_count": 0,
            },
        )
        lane_summary["artifact_count"] += 1
        lane_summary["artifact_names"].append(str(artifact_name))
        status = str(artifact_ref.get("status") or "")
        if status and status not in lane_summary["statuses"]:
            lane_summary["statuses"].append(status)
        if bool(artifact_ref.get("claimable", False)):
            lane_summary["claimable_count"] += 1
        if bool(artifact_ref.get("deliverable_complete", False)):
            lane_summary["deliverable_complete_count"] += 1
        if "claim_upgrade_allowed_count" in artifact_ref:
            lane_summary["claim_upgrade_allowed_count"] += int(
                artifact_ref.get("claim_upgrade_allowed_count", 0) or 0
            )
        release_status = artifact_ref.get(
            "release_candidate_identity_provenance_status"
        )
        if release_status is not None:
            status_items = lane_summary.setdefault(
                "release_candidate_identity_provenance_statuses", []
            )
            release_status_text = str(release_status)
            if release_status_text and release_status_text not in status_items:
                status_items.append(release_status_text)
            blocker_items = lane_summary.setdefault(
                "release_candidate_identity_provenance_blocker_ids", []
            )
            for blocker_id in artifact_ref.get(
                "release_candidate_identity_provenance_blocker_ids", []
            ) or []:
                blocker_text = str(blocker_id)
                if blocker_text and blocker_text not in blocker_items:
                    blocker_items.append(blocker_text)
            lane_summary.setdefault(
                "release_candidate_identity_provenance_trusted_count", 0
            )
            lane_summary.setdefault(
                "release_candidate_identity_provenance_canonical_bundle_bound_count",
                0,
            )
            if bool(
                artifact_ref.get(
                    "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity",
                    False,
                )
            ):
                lane_summary[
                    "release_candidate_identity_provenance_trusted_count"
                ] += 1
            if bool(
                artifact_ref.get(
                    "release_candidate_identity_provenance_canonical_bundle_bound",
                    False,
                )
            ):
                lane_summary[
                    "release_candidate_identity_provenance_canonical_bundle_bound_count"
                ] += 1
        stable_blocker_counts = artifact_ref.get("stable_blocker_reason_counts")
        if isinstance(stable_blocker_counts, Mapping):
            row_counts = lane_summary.setdefault("stable_blocker_reason_counts", {})
            for reason, count in stable_blocker_counts.items():
                reason_key = str(reason)
                row_counts[reason_key] = int(row_counts.get(reason_key, 0) or 0) + int(
                    count or 0
                )
        runtime_provenance = artifact_ref.get("runtime_scheduling_provenance")
        if isinstance(runtime_provenance, Mapping):
            _append_lane_unique(
                lane_summary,
                "runtime_schedule_ids",
                runtime_provenance.get("runtime_schedule_id"),
            )
            _append_lane_unique(
                lane_summary,
                "co_scheduling_policy_ids",
                runtime_provenance.get("co_scheduling_policy_id"),
            )
            _append_lane_unique(
                lane_summary,
                "queue_policies",
                runtime_provenance.get("queue_policy"),
            )
        artifact_provenance = artifact_ref.get("artifact_provenance")
        if isinstance(artifact_provenance, Mapping):
            lane_summary["artifact_provenance_ref_count"] = int(
                lane_summary.get("artifact_provenance_ref_count", 0) or 0
            ) + 1
            _append_lane_unique(
                lane_summary,
                "artifact_provenance_release_subset_hashes",
                artifact_provenance.get("release_subset_hash"),
            )
            _append_lane_unique(
                lane_summary,
                "artifact_provenance_candidate_workflow_deployment_target_matrix_hashes",
                artifact_provenance.get(
                    "candidate_workflow_deployment_target_matrix_hash"
                )
                or artifact_provenance.get("matrix_hash"),
            )
        for count_field in (
            "replayable_tool_transcript_ref_count",
            "availability_probe_only_row_count",
            "candidate_kernel_axis_unbound_row_count",
            "candidate_kernel_axis_bound_row_count",
            "candidate_kernel_target_axis_count",
            "unknown_target_platform_kind_row_count",
            "parsed_stage_result_ref_count",
            "blocker_count",
        ):
            if count_field not in artifact_ref:
                continue
            if count_field == "blocker_count" and artifact_name == "blocker_report.json":
                continue
            lane_summary[count_field] = int(
                lane_summary.get(count_field, 0) or 0
            ) + int(artifact_ref.get(count_field, 0) or 0)
        for map_field in (
            "candidate_kernel_target_axis_counts_by_target",
            "row_counts_by_candidate_kernel_target_axis",
            "row_counts_by_target_platform_kind",
            "blocker_id_counts",
        ):
            _merge_lane_counter_map(
                lane_summary,
                map_field,
                artifact_ref.get(map_field),
            )
    for lane_summary in blocker_report_source_lane_summary.values():
        lane_summary["artifact_names"] = sorted(lane_summary["artifact_names"])
        lane_summary["statuses"] = sorted(lane_summary["statuses"])
        for list_field in (
            "runtime_schedule_ids",
            "co_scheduling_policy_ids",
            "queue_policies",
            "artifact_provenance_release_subset_hashes",
            "artifact_provenance_candidate_workflow_deployment_target_matrix_hashes",
        ):
            if list_field in lane_summary:
                lane_summary[list_field] = sorted(lane_summary[list_field])
        if "release_candidate_identity_provenance_statuses" in lane_summary:
            lane_summary["release_candidate_identity_provenance_statuses"] = sorted(
                lane_summary["release_candidate_identity_provenance_statuses"]
            )
        if "release_candidate_identity_provenance_blocker_ids" in lane_summary:
            lane_summary["release_candidate_identity_provenance_blocker_ids"] = sorted(
                lane_summary["release_candidate_identity_provenance_blocker_ids"]
            )
        if "stable_blocker_reason_counts" in lane_summary:
            lane_summary["stable_blocker_reason_counts"] = dict(
                sorted(lane_summary["stable_blocker_reason_counts"].items())
            )
        for map_field in (
            "candidate_kernel_target_axis_counts_by_target",
            "row_counts_by_candidate_kernel_target_axis",
            "row_counts_by_target_platform_kind",
            "blocker_id_counts",
        ):
            if map_field in lane_summary:
                lane_summary[map_field] = dict(sorted(lane_summary[map_field].items()))
    blocker_report_source_producer_artifact_rationale = str(
        blocker_report.get("source_producer_artifact_rationale") or ""
    )

    recommendations = (
        deployment_recommendations.get("recommendations", {})
        if isinstance(deployment_recommendations.get("recommendations", {}), Mapping)
        else {}
    )
    coordination_recommendations = (
        coordination.get("deployment_recommendations", {})
        if isinstance(coordination.get("deployment_recommendations", {}), Mapping)
        else {}
    )
    fpga_target = (
        target_feasibility.get("fpga_target_feasibility", {})
        if isinstance(target_feasibility.get("fpga_target_feasibility", {}), Mapping)
        else {}
    )
    asic_target = (
        target_feasibility.get("asic_target_binding", {})
        if isinstance(target_feasibility.get("asic_target_binding", {}), Mapping)
        else {}
    )

    deployment_rows: Dict[str, Dict[str, Any]] = {}
    deployment_source_rows: Dict[str, Dict[str, Dict[str, Any]]] = {}
    deployment_target_rows: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for deployment in ("fpga", "asic"):
        summary_row = (
            deployment_summary.get(deployment, {})
            if isinstance(deployment_summary.get(deployment, {}), Mapping)
            else {}
        )
        coordination_row = (
            coordination_recommendations.get(deployment, {})
            if isinstance(coordination_recommendations.get(deployment, {}), Mapping)
            else {}
        )
        recommendation_row = (
            recommendations.get(deployment, {})
            if isinstance(recommendations.get(deployment, {}), Mapping)
            else {}
        )
        target_row = fpga_target if deployment == "fpga" else asic_target
        source_rows: Dict[str, Dict[str, Any]] = {}
        if recommendation_row.get("candidate_id"):
            source_rows["winner_resolution"] = {
                "candidate_id": recommendation_row.get("candidate_id"),
                "design_candidate_id": recommendation_row.get("design_candidate_id"),
            }
        if summary_row.get("best_candidate_id"):
            source_rows["deployment_summary"] = {
                "candidate_id": summary_row.get("best_candidate_id"),
                "design_candidate_id": summary_row.get("best_design_candidate_id"),
            }
        if coordination_row.get("best_candidate_id"):
            source_rows["coordination_summary"] = {
                "candidate_id": coordination_row.get("best_candidate_id"),
                "design_candidate_id": coordination_row.get("best_design_candidate_id"),
            }
        if isinstance(target_row, Mapping) and target_row.get("candidate_id"):
            source_rows["target_feasibility"] = {
                "candidate_id": target_row.get("candidate_id"),
                "design_candidate_id": target_row.get("design_candidate_id"),
            }
        deployment_source_rows[deployment] = source_rows
        target_source_rows: Dict[str, Dict[str, Any]] = {}
        if deployment == "fpga" and (
            recommendation_row.get("selected_device")
            or recommendation_row.get("selected_part")
            or recommendation_row.get("selected_package")
        ):
            target_source_rows["winner_resolution"] = {
                "selected_device": recommendation_row.get("selected_device"),
                "selected_part": recommendation_row.get("selected_part"),
                "selected_package": recommendation_row.get("selected_package"),
            }
        if deployment == "asic" and recommendation_row.get("selected_target_library"):
            target_source_rows["winner_resolution"] = {
                "selected_target_library": recommendation_row.get(
                    "selected_target_library"
                ),
            }
        if summary_row.get("selected_device") or summary_row.get("selected_part"):
            target_source_rows["deployment_summary"] = {
                "selected_device": summary_row.get("selected_device"),
                "selected_part": summary_row.get("selected_part"),
                "selected_package": summary_row.get("selected_package"),
            }
        if (
            coordination_row.get("selected_device")
            or coordination_row.get("fpga_selected_part")
            or coordination_row.get("fpga_selected_package")
        ):
            target_source_rows["coordination_summary"] = {
                "selected_device": (
                    coordination_row.get("selected_device")
                    if deployment == "fpga"
                    else None
                ),
                "selected_part": coordination_row.get("fpga_selected_part"),
                "selected_package": coordination_row.get("fpga_selected_package"),
                "selected_target_library": (
                    coordination_row.get("selected_device")
                    if deployment == "asic"
                    else None
                ),
            }
        if deployment == "fpga" and isinstance(target_row, Mapping) and (
            target_row.get("selected_device")
            or target_row.get("selected_part")
            or target_row.get("selected_package")
        ):
            target_source_rows["target_feasibility"] = {
                "selected_device": target_row.get("selected_device"),
                "selected_part": target_row.get("selected_part"),
                "selected_package": target_row.get("selected_package"),
                "selected_target_id": target_row.get("selected_target_id"),
            }
        if deployment == "asic" and isinstance(target_row, Mapping) and target_row.get("selected_target_library"):
            target_source_rows["target_feasibility"] = {
                "selected_target_library": target_row.get("selected_target_library"),
            }
        deployment_target_rows[deployment] = target_source_rows
        metrics_payload = _first_present(
            coordination_row.get("metrics"),
            summary_row.get("metrics"),
            recommendation_row.get("metrics"),
        )
        equivalent_ids_payload = _first_present(
            coordination_row.get("equivalent_top_candidate_ids"),
            summary_row.get("equivalent_top_candidate_ids"),
        )
        deployment_rows[deployment] = {
            "deployment": deployment,
            "status": _first_present(
                coordination_row.get("status"),
                summary_row.get("status"),
                recommendation_row.get("status"),
            ),
            "candidate_id": _first_present(
                coordination_row.get("best_candidate_id"),
                summary_row.get("best_candidate_id"),
                recommendation_row.get("candidate_id"),
            ),
            "design_candidate_id": _first_present(
                coordination_row.get("best_design_candidate_id"),
                summary_row.get("best_design_candidate_id"),
                recommendation_row.get("design_candidate_id"),
            ),
            "selected_device": _first_present(
                coordination_row.get("selected_device"),
                recommendation_row.get("selected_device"),
                target_row.get("selected_device"),
                target_row.get("selected_target_library"),
                recommendation_row.get("selected_target_library"),
            ),
            "selected_part": _first_present(
                coordination_row.get("fpga_selected_part"),
                recommendation_row.get("selected_part"),
                target_row.get("selected_part"),
            ),
            "selected_package": _first_present(
                coordination_row.get("fpga_selected_package"),
                recommendation_row.get("selected_package"),
                target_row.get("selected_package"),
            ),
            "target_feasibility_status": _first_present(
                coordination_row.get("target_feasibility_status"),
                target_row.get("status"),
            ),
            "metrics": dict(metrics_payload) if isinstance(metrics_payload, Mapping) else {},
            "equivalent_top_candidate_ids": (
                list(equivalent_ids_payload)
                if isinstance(equivalent_ids_payload, Sequence)
                and not isinstance(equivalent_ids_payload, (str, bytes))
                else []
            ),
            "targeted_kernel_count": coordination_row.get("targeted_kernel_count"),
            "expected_kernel_count": coordination_row.get("expected_kernel_count"),
            "blocker_count": int(coordination_row.get("blocker_count", 0) or 0),
            "blockers": list(coordination_row.get("blockers", []) or [])[:10],
            "trusted_winner": False,
            "trusted_final_claim": False,
            "deliverable_complete": False,
        }

    recommendation_bearing_deployments = sorted(
        deployment
        for deployment, row in deployment_rows.items()
        if row.get("candidate_id")
    )
    deployment_source_consensus = _deployment_source_consensus(
        deployment_source_rows,
        recommendation_bearing_deployments=recommendation_bearing_deployments,
    )
    deployment_target_consensus = _deployment_target_consensus(
        deployment_target_rows,
        recommendation_bearing_deployments=recommendation_bearing_deployments,
    )
    target_reconciliation_workplan = _deployment_target_reconciliation_workplan(
        deployment_rows,
        deployment_target_consensus,
    )

    selected_full_scf_ref = (
        "full_scf_end_to_end_comparison.json"
        if loaded.get("full_scf_end_to_end_comparison.json")
        else "full_scf_end_to_end_comparison.recheck.json"
        if loaded.get("full_scf_end_to_end_comparison.recheck.json")
        else None
    )
    strict_classes = full_scf.get("strict_scf_class_ids", [])
    if not isinstance(strict_classes, list):
        strict_classes = []
    full_scf_candidate_ids = _full_scf_candidate_ids(full_scf)
    full_scf_gate = dict(full_scf_sections["full_scf_numerical_gate"])
    full_scf_gate.update({
        "candidate_count": full_scf.get("candidate_count"),
        "strict_scf_class_count": len(strict_classes),
        "strict_scf_class_ids": strict_classes,
        "candidate_id_count": len(full_scf_candidate_ids),
        "blocked_candidate_count": full_scf.get("blocked_candidate_count"),
        "blocked_row_record_count": full_scf.get(
            "blocked_row_record_count",
            full_scf.get("blocked_row_count"),
        ),
        "blocker_count": full_scf.get("blocker_count"),
        "blockers": list(full_scf.get("blockers", []) or [])[:10],
        "top_blocker_categories": _top_counted_items(
            full_scf.get("candidate_blocker_category_histogram", {})
        ),
        "trusted_accelerated_numeric_source": bool(
            full_scf.get("trusted_accelerated_numeric_source", False)
        ),
        "claim_boundary": (
            full_scf.get("claim_boundary")
            or "Full-SCF numerical gate must pass trusted host+accelerator end-to-end rows before final claims."
        ),
    })
    full_scf_passed = bool(full_scf_gate.get("passed", False))

    active_goal_audit = dse_goal_audit or goal_audit
    hardware_blockers = [
        dict(item)
        for item in active_goal_audit.get("hardware_eligibility_blockers", []) or []
        if isinstance(item, Mapping)
    ]
    if candidate_set_consistency:
        candidate_set_fresh_validation = validate_dft_candidate_set_consistency(
            candidate_set_consistency
        )
        recomputed_candidate_sets = (
            candidate_set_fresh_validation.get("recomputed", {})
            if isinstance(candidate_set_fresh_validation.get("recomputed", {}), Mapping)
            else {}
        )
        source_only = (
            recomputed_candidate_sets.get("source_only_candidate_ids", {})
            if isinstance(
                recomputed_candidate_sets.get("source_only_candidate_ids", {}),
                Mapping,
            )
            else {}
        )
        source_missing = (
            recomputed_candidate_sets.get("source_missing_candidate_ids", {})
            if isinstance(
                recomputed_candidate_sets.get("source_missing_candidate_ids", {}),
                Mapping,
            )
            else {}
        )
        release_gate_only_candidate_ids = _string_list(source_only.get("release_gate", []))
        binding_only_candidate_ids = _string_list(source_only.get("binding_map", []))
        trial_ledger_only_candidate_ids = _string_list(source_only.get("trial_ledger", []))
        release_gate_missing_candidate_ids = _string_list(source_missing.get("release_gate", []))
        binding_map_missing_candidate_ids = _string_list(source_missing.get("binding_map", []))
        trial_ledger_missing_candidate_ids = _string_list(source_missing.get("trial_ledger", []))
        candidate_set_status = str(
            recomputed_candidate_sets.get("candidate_set_consistency_status")
            or (
                "candidate_sets_match"
                if recomputed_candidate_sets.get("status") == "passed"
                else "candidate_set_mismatch"
            )
        )
        candidate_set_consistency_source = "dft_candidate_set_consistency.json"
        candidate_set_consistency_checked = True
        candidate_set_missing_sources = _string_list(
            recomputed_candidate_sets.get("missing_sources", [])
        )
        candidate_set_empty_sources = _string_list(
            recomputed_candidate_sets.get("empty_sources", [])
        )
        candidate_set_artifact_status = recomputed_candidate_sets.get("status")
        sidecar_validation_valid = (
            candidate_set_consistency_validation.get("valid")
            if candidate_set_consistency_validation
            else None
        )
        fresh_validation_valid = candidate_set_fresh_validation.get("valid") is True
        candidate_set_validation_valid = bool(
            fresh_validation_valid and sidecar_validation_valid is not False
        )
        candidate_set_blockers = [
            dict(item)
            for item in recomputed_candidate_sets.get("blockers", []) or []
            if isinstance(item, Mapping)
        ]
        if candidate_set_validation_valid is not True:
            candidate_set_status = "candidate_sets_not_checked_validation_invalid"
            candidate_set_blockers.append({
                "blocker_id": "candidate_set_consistency_validation_not_passed",
                "validation_valid": candidate_set_validation_valid,
                "fresh_validation_valid": fresh_validation_valid,
                "sidecar_validation_valid": sidecar_validation_valid,
                "fresh_validation_error_count": len(
                    candidate_set_fresh_validation.get("errors", []) or []
                ),
                "fresh_validation_errors": list(
                    candidate_set_fresh_validation.get("errors", []) or []
                )[:5],
                "reason": (
                    "Explicit DFT candidate-set consistency artifacts must pass "
                    "fresh recomputation from candidate_sets and any validation "
                    "sidecar before Step5 can trust the candidate-set comparison."
                ),
            })
        candidate_set_ids = _unique_string_list(
            recomputed_candidate_sets.get("union_candidate_ids", [])
        )
    else:
        release_gate_only_candidate_ids = sorted({
            str(candidate_id)
            for blocker in hardware_blockers
            for candidate_id in blocker.get("release_gate_only_candidate_ids", []) or []
        })
        binding_only_candidate_ids = sorted({
            str(candidate_id)
            for blocker in hardware_blockers
            for candidate_id in blocker.get("binding_map_only_candidate_ids", []) or []
        })
        trial_ledger_only_candidate_ids = sorted({
            str(candidate_id)
            for blocker in hardware_blockers
            for candidate_id in blocker.get("trial_ledger_only_candidate_ids", []) or []
        })
        release_gate_missing_candidate_ids: List[str] = []
        binding_map_missing_candidate_ids: List[str] = []
        trial_ledger_missing_candidate_ids: List[str] = []
        candidate_set_status = (
            "candidate_set_mismatch"
            if release_gate_only_candidate_ids
            or binding_only_candidate_ids
            or trial_ledger_only_candidate_ids
            else "candidate_sets_match_or_not_checked"
        )
        candidate_set_consistency_source = "goal_audit_hardware_eligibility_blockers"
        candidate_set_consistency_checked = bool(
            release_gate_only_candidate_ids
            or binding_only_candidate_ids
            or trial_ledger_only_candidate_ids
        )
        candidate_set_missing_sources = []
        candidate_set_empty_sources = []
        candidate_set_artifact_status = None
        candidate_set_validation_valid = None
        candidate_set_blockers = []
        candidate_set_ids = []

    candidate_set_trusted = (
        candidate_set_status == "candidate_sets_match"
        and candidate_set_validation_valid is True
        and bool(candidate_set_ids)
    )
    deployment_candidate_alignment = _deployment_candidate_alignment(
        deployment_rows,
        candidate_set_ids=candidate_set_ids,
        candidate_set_trusted=candidate_set_trusted,
        full_scf_ids=full_scf_candidate_ids,
        full_scf_present=bool(full_scf),
    )
    for deployment, alignment_row in deployment_candidate_alignment["per_deployment"].items():
        if deployment in deployment_rows:
            deployment_rows[deployment]["candidate_set_membership"] = alignment_row[
                "candidate_set_membership"
            ]
            deployment_rows[deployment]["full_scf_candidate_membership"] = alignment_row[
                "full_scf_candidate_membership"
            ]
            deployment_rows[deployment]["evidence_alignment_ready"] = alignment_row[
                "evidence_alignment_ready"
            ]
            deployment_rows[deployment]["evidence_alignment_blockers"] = alignment_row[
                "blockers"
            ][:10]
    for deployment, consensus_row in deployment_source_consensus["per_deployment"].items():
        if deployment in deployment_rows:
            deployment_rows[deployment]["source_consensus_status"] = consensus_row["status"]
            deployment_rows[deployment]["source_consensus_passed"] = consensus_row["passed"]
            deployment_rows[deployment]["candidate_id_by_source"] = consensus_row[
                "candidate_id_by_source"
            ]
            deployment_rows[deployment]["design_candidate_id_by_source"] = consensus_row[
                "design_candidate_id_by_source"
            ]
            deployment_rows[deployment]["source_consensus_blockers"] = consensus_row[
                "blockers"
            ][:10]
    for deployment, target_consensus_row in deployment_target_consensus["per_deployment"].items():
        if deployment in deployment_rows:
            deployment_rows[deployment]["target_consensus_status"] = target_consensus_row["status"]
            deployment_rows[deployment]["target_consensus_passed"] = target_consensus_row["passed"]
            deployment_rows[deployment]["selected_device_by_source"] = target_consensus_row[
                "selected_device_by_source"
            ]
            deployment_rows[deployment]["selected_part_by_source"] = target_consensus_row[
                "selected_part_by_source"
            ]
            deployment_rows[deployment]["selected_package_by_source"] = target_consensus_row[
                "selected_package_by_source"
            ]
            deployment_rows[deployment]["selected_target_library_by_source"] = target_consensus_row[
                "selected_target_library_by_source"
            ]
            deployment_rows[deployment]["target_consensus_blockers"] = target_consensus_row[
                "blockers"
            ][:10]
            deployment_rows[deployment]["overlapping_target_identity_fields"] = target_consensus_row[
                "overlapping_target_identity_fields"
            ]
            deployment_rows[deployment]["passing_target_identity_fields"] = target_consensus_row[
                "passing_target_identity_fields"
            ]

    completion_blockers = [
        dict(item)
        for item in active_goal_audit.get("deliverable_completion_blockers", []) or []
        if isinstance(item, Mapping)
    ]
    coordination_blockers = [
        dict(item)
        for item in coordination.get("coordination_blockers", []) or []
        if isinstance(item, Mapping)
    ]
    release_completion_gates = {
        "status_claim": run_status.get("claim_status"),
        "blocker_report_status": blocker_report.get("status"),
        "blocker_report_blocked_fields": list(blocker_report.get("blocked_fields", []) or []),
        "blocker_report_source_producer_artifact_ref_count": len(
            blocker_report_source_producer_artifact_refs
        ),
        "blocker_report_source_lanes": sorted(blocker_report_source_lane_summary),
        "full_scf_numerical_passed": full_scf_passed,
        "full_scf_numerical_comparison_artifact_passed": bool(
            full_scf_gate.get("comparison_artifact_passed", False)
        ),
        "full_scf_numerical_validation_passed": bool(
            full_scf_gate.get("validation_passed", False)
        ),
        "full_scf_numerical_status_artifact_passed": bool(
            full_scf_gate.get("status_artifact_passed", False)
        ),
        "numerical_correctness_status": numerical_evidence.get("status"),
        "goal_audit_status": goal_audit.get("status"),
        "dse_goal_audit_status": dse_goal_audit.get("status"),
        "completion_decision": active_goal_audit.get("completion_decision"),
        "horizon_reached": bool(active_goal_audit.get("horizon_reached", False)),
        "candidate_set_consistency_status": candidate_set_status,
        "candidate_set_consistency_source": candidate_set_consistency_source,
        "candidate_set_consistency_checked": candidate_set_consistency_checked,
        "candidate_set_consistency_artifact_status": candidate_set_artifact_status,
        "candidate_set_consistency_validation_valid": candidate_set_validation_valid,
        "candidate_set_missing_sources": candidate_set_missing_sources,
        "candidate_set_empty_sources": candidate_set_empty_sources,
        "deployment_source_consensus_status": deployment_source_consensus["status"],
        "deployment_source_consensus_checked": deployment_source_consensus["checked"],
        "deployment_source_consensus_passed": deployment_source_consensus["passed"],
        "deployment_source_consensus_recommendation_bearing_deployments": deployment_source_consensus[
            "recommendation_bearing_deployments"
        ],
        "deployment_source_consensus_blockers": deployment_source_consensus["blockers"][:10],
        "deployment_target_consensus_status": deployment_target_consensus["status"],
        "deployment_target_consensus_checked": deployment_target_consensus["checked"],
        "deployment_target_consensus_passed": deployment_target_consensus["passed"],
        "deployment_target_consensus_recommendation_bearing_deployments": deployment_target_consensus[
            "recommendation_bearing_deployments"
        ],
        "deployment_target_consensus_blockers": deployment_target_consensus["blockers"][:10],
        "deployment_target_reconciliation_required": target_reconciliation_workplan[
            "required"
        ],
        "deployment_target_reconciliation_work_item_count": target_reconciliation_workplan[
            "work_item_count"
        ],
        "deployment_candidate_alignment_status": deployment_candidate_alignment["status"],
        "deployment_candidate_alignment_checked": deployment_candidate_alignment["checked"],
        "deployment_candidate_alignment_passed": deployment_candidate_alignment["passed"],
        "deployment_recommendation_candidate_ids": deployment_candidate_alignment[
            "recommendation_candidate_ids"
        ],
        "deployment_candidate_ids_missing_from_candidate_set": deployment_candidate_alignment[
            "missing_from_candidate_set"
        ],
        "deployment_candidate_ids_missing_from_full_scf": deployment_candidate_alignment[
            "missing_from_full_scf"
        ],
        "deployment_candidate_alignment_blockers": deployment_candidate_alignment["blockers"][:10],
        "deployment_summary_validation_valid": deployment_summary_validation_valid,
        "target_feasibility_validation_valid": target_feasibility_validation_valid,
        "coordination_validation_valid": coordination_validation_valid,
        "deployment_sidecar_validation_passed": deployment_sidecar_validation_passed,
        "deployment_sidecar_validation_blockers": deployment_sidecar_validation_blockers[:10],
        "full_scf_candidate_id_count": len(full_scf_candidate_ids),
        "candidate_set_candidate_id_count": len(candidate_set_ids),
        "release_gate_only_candidate_ids": release_gate_only_candidate_ids,
        "binding_map_only_candidate_ids": binding_only_candidate_ids,
        "trial_ledger_only_candidate_ids": trial_ledger_only_candidate_ids,
        "release_gate_missing_candidate_ids": release_gate_missing_candidate_ids,
        "binding_map_missing_candidate_ids": binding_map_missing_candidate_ids,
        "trial_ledger_missing_candidate_ids": trial_ledger_missing_candidate_ids,
        "candidate_set_blockers": candidate_set_blockers[:10],
        "deliverable_completion_blocker_count": len(completion_blockers),
        "hardware_eligibility_blocker_count": len(hardware_blockers),
        "coordination_blocker_count": len(coordination_blockers),
        "release_completion_eligible": bool(coordination.get("release_completion_eligible", False)),
        "trusted_final_claim": False,
        "deliverable_complete": False,
    }
    decision_support_gates_passed = bool(
        candidate_set_trusted
        and deployment_candidate_alignment["passed"]
        and deployment_source_consensus["passed"]
        and deployment_target_consensus["passed"]
        and deployment_sidecar_validation_passed
    )
    release_completion_gates["decision_support_eligibility_gates_passed"] = (
        decision_support_gates_passed
    )

    present = bool(
        deployment_summary
        or target_feasibility
        or coordination
        or full_scf
        or numerical_evidence
        or candidate_set_consistency
        or goal_audit
        or dse_goal_audit
        or run_status
        or blocker_report
    )
    source_artifacts = [
        name
        for name, ref in artifact_refs.items()
        if ref.get("exists")
    ]
    return {
        "schema_version": "dse.final_report.dft_deployment_decision_support.v1",
        "present": present,
        "status": (
            "invalid_deployment_decision_support_validation"
            if present and not deployment_sidecar_validation_passed
            else _first_present(
                coordination.get("status"),
                deployment_summary.get("status"),
                target_feasibility.get("status"),
                "not_present",
            )
        ),
        "source_artifacts": source_artifacts,
        "artifacts": artifact_refs,
        "deployment_summary_status": deployment_summary.get("status"),
        "deployment_summary_validation_valid": deployment_summary_validation_valid,
        "target_feasibility_status": target_feasibility.get("status"),
        "target_feasibility_validation_valid": target_feasibility_validation_valid,
        "coordination_status": coordination.get("status"),
        "coordination_validation_valid": coordination_validation_valid,
        "deployment_sidecar_validation_passed": deployment_sidecar_validation_passed,
        "deployment_sidecar_validation_blockers": deployment_sidecar_validation_blockers[:10],
        "blocker_report_source_producer_artifact_refs": blocker_report_source_producer_artifact_refs,
        "blocker_report_source_producer_artifact_ref_count": len(
            blocker_report_source_producer_artifact_refs
        ),
        "blocker_report_source_lane_summary": blocker_report_source_lane_summary,
        "blocker_report_source_lanes": sorted(blocker_report_source_lane_summary),
        "blocker_report_source_producer_artifact_rationale": (
            blocker_report_source_producer_artifact_rationale
            or (
                "No blocker-report source producer refs were provided. When present, "
                "they are final-report traceability inputs only and cannot upgrade claims."
            )
        ),
        "current_best_available": bool(coordination.get("current_best_available", False))
        and coordination_validation_valid is True,
        "target_feasibility_ready": bool(target_feasibility.get("target_feasibility_ready", False))
        and target_feasibility_validation_valid is True,
        "best_deployment_claim_eligible": decision_support_gates_passed,
        "hardware_completion_eligible": False,
        "recommendations": deployment_rows,
        "target_reconciliation_workplan": target_reconciliation_workplan,
        "full_scf_numerical_gate": full_scf_gate,
        "release_completion_gates": release_completion_gates,
        "goal_audit_summary": (
            active_goal_audit.get("summary", {})
            if isinstance(active_goal_audit.get("summary", {}), Mapping)
            else {}
        ),
        "deliverable_completion_blockers": completion_blockers[:10],
        "hardware_eligibility_blockers": hardware_blockers[:10],
        "coordination_blockers": coordination_blockers[:10],
        "recommended_next_actions": list(coordination.get("recommended_next_actions", []) or [])[:10],
        "trusted_winner": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Deployment decision support packages current FPGA/ASIC scoped PPA "
            "winners, target feasibility, full-SCF numerical gates, and goal-audit "
            "blockers for coordination only. It never upgrades to a full-SCF "
            "trusted winner or deliverable-complete claim."
        ),
    }


def _dft_l4_goal_binding_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize optional L4/gem5 binding artifacts without upgrading claims."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_L4_GOAL_BINDING_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    binding = loaded.get("dft_l4_goal_binding.json", {})
    validation = loaded.get("dft_l4_goal_binding_validation.json", {})
    status_artifact = loaded.get("dft_l4_goal_binding_status.json", {})
    queue_artifact = loaded.get("dft_l4_current_candidate_queue.json", {})
    if not queue_artifact and isinstance(binding.get("current_candidate_l4_queue", {}), Mapping):
        queue_artifact = binding.get("current_candidate_l4_queue", {})
    present = bool(binding)
    current = binding.get("current_goal_binding", {}) if isinstance(binding.get("current_goal_binding", {}), Mapping) else {}
    l4_matrix = binding.get("l4_matrix", {}) if isinstance(binding.get("l4_matrix", {}), Mapping) else {}
    accelerated_qe_summary = (
        binding.get("accelerated_qe_blocker_summary", {})
        if isinstance(binding.get("accelerated_qe_blocker_summary", {}), Mapping)
        else {}
    )
    row_level_proofs = (
        binding.get("row_level_proofs", {})
        if isinstance(binding.get("row_level_proofs", {}), Mapping)
        else {}
    )
    queue_ready = queue_artifact.get("ready")
    if queue_ready is None:
        queue_ready = bool(queue_artifact.get("row_count")) and int(queue_artifact.get("blocked_row_count", 0) or 0) == 0
    queue_current_readiness = (
        queue_artifact.get("current_candidate_readiness", {})
        if isinstance(queue_artifact.get("current_candidate_readiness", {}), Mapping)
        else {}
    )
    if not queue_current_readiness:
        queue_current_readiness = {
            "status": queue_artifact.get("status"),
            "ready": queue_ready,
            "candidate_count": queue_artifact.get("candidate_count"),
            "workload_class_count": queue_artifact.get("workload_class_count"),
            "row_count": queue_artifact.get("row_count"),
            "passed_row_count": queue_artifact.get("passed_row_count"),
            "blocked_row_count": queue_artifact.get("blocked_row_count"),
            "blocked_row_ids": [],
        }
    queue_blocked_rows = (
        queue_artifact.get("blocked_rows", [])
        if isinstance(queue_artifact.get("blocked_rows", []), list)
        else []
    )
    if not queue_blocked_rows and isinstance(queue_artifact.get("rows", []), list):
        queue_blocked_rows = [
            dict(row)
            for row in queue_artifact.get("rows", [])
            if isinstance(row, Mapping) and row.get("status") != "passed"
        ]
    final_closure_eligible = bool(binding.get("final_closure_eligible", False))
    deliverable_complete = bool(binding.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    validation_errors = list(validation.get("errors", []) or []) if validation else []
    invalid_contract_errors = {
        "schema_version_mismatch",
        "binding_artifact_must_not_mark_deliverable_complete",
    }
    status = (
        "fail_closed_l4_goal_binding_present"
        if present and validation_valid is True and not deliverable_complete
        else "fail_closed_l4_goal_binding_blocked"
        if (
            present
            and validation
            and not deliverable_complete
            and not invalid_contract_errors.intersection(str(error) for error in validation_errors)
        )
        else "invalid_l4_goal_binding"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_l4_goal_binding.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "binding_status": binding.get("status"),
        "l4_root": binding.get("l4_root"),
        "step5_run": binding.get("step5_run"),
        "l4_software_visible_proof_present": bool(binding.get("l4_software_visible_proof_present", False)),
        "final_closure_eligible": final_closure_eligible,
        "deliverable_complete": deliverable_complete,
        "l4_matrix": {
            "coverage_status": l4_matrix.get("coverage_status"),
            "row_count": l4_matrix.get("row_count"),
            "expected_row_count": l4_matrix.get("expected_row_count"),
            "blocked_row_count": l4_matrix.get("blocked_row_count"),
            "candidate_count": l4_matrix.get("candidate_count"),
            "workload_case_count": l4_matrix.get("workload_case_count"),
            "matrix_hash": l4_matrix.get("matrix_hash"),
        },
        "row_level_proofs": {
            "expected_gem5_l4_proof_count": row_level_proofs.get("expected_gem5_l4_proof_count"),
            "present_gem5_l4_proof_count": row_level_proofs.get("present_gem5_l4_proof_count"),
        },
        "current_candidate_l4_queue": {
            "schema_version": queue_artifact.get("schema_version"),
            "status": queue_artifact.get("status"),
            "ready": queue_ready,
            "candidate_count": queue_artifact.get("candidate_count"),
            "workload_class_count": queue_artifact.get("workload_class_count"),
            "row_count": queue_artifact.get("row_count"),
            "passed_row_count": queue_artifact.get("passed_row_count"),
            "blocked_row_count": queue_artifact.get("blocked_row_count"),
            "current_candidate_readiness": queue_current_readiness,
            "blocked_rows": queue_blocked_rows,
            "claim_flags": (
                queue_artifact.get("claim_flags", {})
                if isinstance(queue_artifact.get("claim_flags", {}), Mapping)
                else {}
            ),
            "claim_boundary": queue_artifact.get("claim_boundary"),
        },
        "accelerated_qe_blocker_summary": accelerated_qe_summary,
        "current_goal_binding": {
            "candidate_mapping_policy": current.get("candidate_mapping_policy"),
            "workload_mapping_policy": current.get("workload_mapping_policy"),
            "step5_candidate_count": current.get("step5_candidate_count"),
            "candidate_crosswalk_count": current.get("candidate_crosswalk_count"),
            "candidate_structured_crosswalk_count": current.get("candidate_structured_crosswalk_count"),
            "candidate_identity_binding_explicit": bool(current.get("candidate_identity_binding_explicit", False)),
            "candidate_keys_exact": bool(current.get("candidate_keys_exact", False)),
            "mapped_l4_candidates_unique": bool(current.get("mapped_l4_candidates_unique", False)),
            "workload_crosswalk_count": current.get("workload_crosswalk_count"),
            "workload_structured_crosswalk_count": current.get("workload_structured_crosswalk_count"),
            "workload_identity_binding_explicit": bool(current.get("workload_identity_binding_explicit", False)),
            "workload_keys_exact": bool(current.get("workload_keys_exact", False)),
            "current_goal_l4_bound": bool(current.get("current_goal_l4_bound", False)),
        },
        "validation": {
            "present": bool(validation),
            "valid": validation_valid,
            "error_count": len(validation.get("errors", []) or []) if validation else None,
            "errors": validation_errors,
            "warning_count": len(validation.get("warnings", []) or []) if validation else None,
            "warnings": validation.get("warnings", []) if validation else [],
        },
        "blockers": list(binding.get("blockers", []) or []) if isinstance(binding.get("blockers", []), list) else [],
        "status_artifact": {
            "status": status_artifact.get("status"),
            "binding_status": status_artifact.get("binding_status"),
            "accelerated_qe_blocker_status": status_artifact.get("accelerated_qe_blocker_status"),
            "accelerated_qe_required_row_count": status_artifact.get(
                "accelerated_qe_required_row_count"
            ),
            "accelerated_qe_index_row_count": status_artifact.get("accelerated_qe_index_row_count"),
        },
        "trusted_final_claim": False,
        "completion_claim": "blocked" if present and not final_closure_eligible else "l4_bound" if final_closure_eligible else "not_applicable",
        "claim_boundary": (
            binding.get("claim_boundary")
            or "L4/gem5 binding is software-visible proof only and does not upgrade FPGA/ASIC or full-SCF completion claims."
        ),
    }




def _dft_audit_semantic_closure_section(
    run_dir: Path,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize the semantic audit-closure artifact without upgrading claims."""

    artifact_refs: Dict[str, Dict[str, Any]] = {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for name in sorted(DFT_AUDIT_SEMANTIC_CLOSURE_ARTIFACT_NAMES):
        rel_path, entry = _find_indexed_artifact(evidence_index, name)
        artifact_refs[name] = {
            "path": rel_path,
            "exists": bool(entry.get("exists", False)),
            "sha256": entry.get("sha256"),
        }
        if rel_path:
            loaded[name] = _load_json(run_dir / rel_path)

    closure = loaded.get("dft_audit_semantic_closure.json", {})
    present = bool(closure)
    checks = [dict(item) for item in closure.get("checks", []) or [] if isinstance(item, Mapping)]
    source_artifacts = (
        closure.get("source_artifacts", {})
        if isinstance(closure.get("source_artifacts", {}), Mapping)
        else {}
    )
    required_source_count = 0
    hashed_required_source_count = 0
    missing_required_sources: List[str] = []
    source_hash_errors: List[str] = []
    closure_artifact_path: Optional[Path] = None
    closure_ref = artifact_refs.get("dft_audit_semantic_closure.json", {})
    if closure_ref.get("path"):
        closure_artifact_path = run_dir / str(closure_ref.get("path"))
    for label, ref_any in source_artifacts.items():
        ref = ref_any if isinstance(ref_any, Mapping) else {}
        if ref.get("required") is True:
            required_source_count += 1
            if ref.get("exists") is not True:
                missing_required_sources.append(str(label))
                source_hash_errors.append(f"{label}:required_source_missing")
            if ref.get("sha256"):
                hashed_required_source_count += 1
            else:
                source_hash_errors.append(f"{label}:missing_sha256")
        if not ref.get("sha256") or ref.get("exists") is not True:
            continue
        resolved = _resolve_run_or_artifact_relative_path(
            ref.get("path"),
            run_dir=run_dir,
            artifact_path=closure_artifact_path,
        )
        if resolved is None or not resolved.exists() or not resolved.is_file():
            source_hash_errors.append(f"{label}:referenced_source_missing")
            continue
        if _sha256(resolved) != ref.get("sha256"):
            source_hash_errors.append(f"{label}:source_hash_mismatch")
    source_hash_backed = bool(
        closure.get("source_hash_backed") is True
        and required_source_count > 0
        and hashed_required_source_count == required_source_count
        and not missing_required_sources
        and not source_hash_errors
    )
    failed_checks = [str(item.get("check_id")) for item in checks if item.get("passed") is not True]
    required_check_ids = {
        "phase_hotspot_identity",
        "evaluation_policy_legality",
        "candidate_tier_absence",
        "coverage_vector_derivation",
        "reference_hash_admission",
    }
    present_check_ids = {str(item.get("check_id")) for item in checks if item.get("check_id")}
    missing_checks = sorted(required_check_ids - present_check_ids)
    overall_passed = bool(closure.get("overall_passed") is True)
    valid = bool(
        present
        and closure.get("schema_version") == "dse.dft_scf.semantic_audit_closure.v1"
        and overall_passed
        and source_hash_backed
        and not failed_checks
        and not missing_checks
    )
    status = (
        "semantic_audit_closure_passed"
        if valid
        else "semantic_audit_closure_blocked"
        if present
        else "not_present"
    )
    return {
        "schema_version": "dse.final_report.dft_audit_semantic_closure.v1",
        "present": present,
        "status": status,
        "artifacts": artifact_refs,
        "source_schema_version": closure.get("schema_version"),
        "overall_passed": overall_passed,
        "source_hash_backed": source_hash_backed,
        "required_source_count": required_source_count,
        "hashed_required_source_count": hashed_required_source_count,
        "missing_required_sources": missing_required_sources,
        "source_hash_errors": source_hash_errors,
        "check_count": len(checks),
        "failed_checks": failed_checks,
        "missing_checks": missing_checks,
        "checks": [
            {
                "check_id": item.get("check_id"),
                "passed": item.get("passed"),
                "blockers": item.get("blockers", []),
            }
            for item in checks
        ],
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": (
            closure.get("claim_boundary")
            or "Semantic audit closure can close the five audit findings only; it is not hardware release or final DFT/QE hardware-DSE completion evidence."
        ),
    }

def generate_final_report(
    run_dir: Path,
    *,
    claims: Optional[Iterable[Mapping[str, Any]]] = None,
    artifact_paths: Optional[Iterable[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build final report, claim validation, and evidence requirements payloads."""
    run_dir = Path(run_dir)
    manifest = _load_json(run_dir / "manifest.json")
    verdict = _load_json(run_dir / "verdict.json")
    design_point = _load_json(run_dir / "design_point.json")
    architecture = _load_json(run_dir / "architecture.json")
    mapping = _load_json(run_dir / "mapping.json")
    workload_package = _load_json(run_dir / "workload_package.json")
    workload_graph = _load_json(run_dir / "workload_graph.json")
    graph_lowering = _load_json(run_dir / "graph_lowering_report.json")
    simulation_request = _load_json(run_dir / "simulation_request.json")
    simulation_result = _load_json(run_dir / "simulation_result.json")
    simulator_consistency_check = _load_json(run_dir / "simulator_consistency_check.json")
    numerical_validation = simulator_consistency_check or _load_json(run_dir / "numerical_validation.json")
    blockers = _load_json(run_dir / "gem5_systemc_blockers.json")
    codesign_candidate = _load_json(run_dir / "codesign_candidate.json")
    codesign_verdict = _load_json(run_dir / "codesign_verdict.json")
    simulation_samples = _load_json(run_dir / "mapping_simulation_samples.json")
    feedback_state = _load_json(run_dir / "mapping_feedback_state.json")
    convergence_status = _load_json(run_dir / "convergence_status.json")
    step3_queue_execution_status = _load_json(run_dir / "step3_queue_execution_status.json")
    step4_queue_adjudication_status = _load_json(run_dir / "step4_queue_adjudication_status.json")
    step3_queue_aggregation = {
        "present": bool(step3_queue_execution_status or step4_queue_adjudication_status),
        "step3_queue_execution_status": "step3_queue_execution_status.json" if step3_queue_execution_status else None,
        "step4_queue_adjudication_status": "step4_queue_adjudication_status.json" if step4_queue_adjudication_status else None,
        "queue_mode": step4_queue_adjudication_status.get("queue_mode", step3_queue_execution_status.get("queue_mode")),
        "planned_entry_count": step4_queue_adjudication_status.get("planned_entry_count", step3_queue_execution_status.get("planned_entry_count")),
        "executed_entry_count": step4_queue_adjudication_status.get("executed_entry_count", step3_queue_execution_status.get("executed_entry_count")),
        "adjudicated_entry_count": step4_queue_adjudication_status.get("adjudicated_entry_count"),
        "trusted_entry_count": step4_queue_adjudication_status.get("trusted_entry_count"),
        "blocked_entry_count": step4_queue_adjudication_status.get("blocked_entry_count"),
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "claim_boundary": (
            "Step3 queue aggregation is bounded campaign evidence. It cannot by itself "
            "establish global convergence, FPGA/ASIC winners, or deliverable completion."
        ),
    }
    workflow_payload = simulation_result.get("workflow", workload_package.get("workflow", graph_lowering.get("workflow", {})))
    if not isinstance(workflow_payload, Mapping):
        workflow_payload = {}
    profile_domain_validation = simulation_result.get("domain_validation")
    if not isinstance(profile_domain_validation, Mapping):
        profile_domain_validation = simulation_result.get("profile_domain_validation", verdict.get("domain_validation", {}))
    if not isinstance(profile_domain_validation, Mapping):
        profile_domain_validation = {}
    unavailable_metrics = simulation_result.get("unavailable_metrics", [])
    if not isinstance(unavailable_metrics, list):
        unavailable_metrics = []
    generated_report_paths = {
        "artifact_manifest.json",
        "evidence_requirements.json",
        "claim_validation.json",
        "final_report.json",
        "final_report.md",
    }
    evidence_index = build_evidence_index(
        run_dir,
        artifact_paths=artifact_paths,
        generated_in_current_pass=generated_report_paths,
    )
    step2_search_provenance = _step2_search_provenance_section(
        run_dir,
        evidence_index=evidence_index,
    )
    low_fidelity_screening = _low_fidelity_screening_section(
        run_dir,
        evidence_index=evidence_index,
    )
    search_admission_validation = _search_admission_validation_section(
        run_dir,
        evidence_index,
    )
    dft_evidence_ledger = _dft_evidence_ledger_section(
        run_dir,
        evidence_index,
    )
    dft_trial_state_ledger = _dft_trial_state_ledger_section(
        run_dir,
        evidence_index,
    )
    dft_candidate_binding_map = _dft_candidate_binding_map_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_completion_workplan = _dft_hardware_completion_workplan_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_closure_shards = _dft_hardware_closure_shards_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_closure_packets = _dft_hardware_closure_packets_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_closure_candidate_bundles = _dft_hardware_closure_candidate_bundles_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_closure_unit_provenance = _dft_hardware_closure_unit_provenance_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_closure_artifact_chain = _dft_hardware_closure_artifact_chain_section(
        run_dir,
        dft_hardware_completion_workplan,
        dft_hardware_closure_shards,
        dft_hardware_closure_packets,
        dft_hardware_closure_candidate_bundles,
        dft_hardware_closure_unit_provenance,
    )
    dft_hardware_closure_source_flow_plan = _dft_hardware_closure_source_flow_plan_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_closure_raw_stage_materialization = _dft_hardware_closure_raw_stage_materialization_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_closure_raw_transcript_registration = _dft_hardware_closure_raw_transcript_registration_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_closure_evidence_intake = _dft_hardware_closure_evidence_intake_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_closure_adjudication = _dft_hardware_closure_adjudication_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_closure_parsed_evidence = _dft_hardware_closure_parsed_evidence_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_closure_parser_run = _dft_hardware_closure_parser_run_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_closure_gate_adjudication = _dft_hardware_closure_gate_adjudication_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_closure_release_gate = _dft_hardware_closure_release_gate_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_ppa_ranking = _dft_hardware_ppa_ranking_section(
        run_dir,
        evidence_index,
    )
    dft_candidate_specific_ppa_provenance = _dft_candidate_specific_ppa_provenance_section(
        run_dir,
        evidence_index,
    )
    dft_architecture_winner_resolution = _dft_architecture_winner_resolution_section(
        run_dir,
        evidence_index,
    )
    dft_hardware_deployment_recommendation_readiness = (
        _dft_hardware_deployment_recommendation_readiness_section(
            run_dir,
            evidence_index,
        )
    )
    dft_hardware_deployment_decision_packet = (
        _dft_hardware_deployment_decision_packet_section(
            run_dir,
            evidence_index,
        )
    )
    deployment_recommendations = _deployment_recommendations_from_winner_resolution(
        dft_architecture_winner_resolution,
        deployment_readiness=dft_hardware_deployment_recommendation_readiness,
    )
    dft_deployment_decision_support = _dft_deployment_decision_support_section(
        run_dir,
        evidence_index,
        deployment_recommendations=deployment_recommendations,
    )
    deployment_recommendation_plan = _deployment_recommendation_plan_section(
        run_dir,
        evidence_index,
    )
    dft_deployment_comparator = _dft_deployment_comparator_section(
        run_dir,
        evidence_index,
    )
    dft_deployment_selector = _dft_deployment_selector_section(
        run_dir,
        evidence_index,
    )
    dft_deployment_decision_summary = _dft_deployment_decision_summary_section(
        run_dir,
        evidence_index,
    )
    dft_l4_goal_binding = _dft_l4_goal_binding_section(
        run_dir,
        evidence_index,
    )
    dft_audit_semantic_closure = _dft_audit_semantic_closure_section(
        run_dir,
        evidence_index,
    )
    if step3_queue_aggregation.get("present"):
        dft_step5_root_artifact_refs = {
            "dft_evidence_ledger": (
                dft_evidence_ledger.get("artifacts", {})
                .get("per_candidate_evidence_ledger.json", {})
                .get("path")
            ),
            "dft_candidate_binding_map": (
                dft_candidate_binding_map.get("artifacts", {})
                .get("dft_candidate_binding_map.json", {})
                .get("path")
            ),
            "dft_trial_state_ledger": (
                dft_trial_state_ledger.get("artifacts", {})
                .get("dft_trial_state_ledger.json", {})
                .get("path")
            ),
            "dft_deployment_decision_summary": (
                dft_deployment_decision_summary.get("artifacts", {})
                .get("dft_deployment_decision_summary.json", {})
                .get("path")
            ),
            "dft_l4_goal_binding": (
                dft_l4_goal_binding.get("artifacts", {})
                .get("dft_l4_goal_binding.json", {})
                .get("path")
            ),
            "dft_audit_semantic_closure": (
                dft_audit_semantic_closure.get("artifacts", {})
                .get("dft_audit_semantic_closure.json", {})
                .get("path")
            ),
        }
        dft_step5_root_artifact_refs = {
            key: value for key, value in dft_step5_root_artifact_refs.items() if value
        }
        if any(dft_step5_root_artifact_refs.values()):
            step3_queue_aggregation["dft_step5_root_artifact_refs"] = dft_step5_root_artifact_refs
    dft_full_scf_hybrid = _dft_full_scf_hybrid_section(
        run_dir,
        evidence_index,
        ledger_bundle=dft_evidence_ledger.get("full_scf_hybrid_bundle", {}),
    )
    qe_baseline_row_accounting_attachment = _qe_baseline_row_accounting_attachment_section(
        run_dir,
        evidence_index,
    )
    full_scf_accounting_completeness = _full_scf_accounting_completeness(
        dft_full_scf_hybrid,
        qe_baseline_row_accounting_attachment=qe_baseline_row_accounting_attachment,
    )
    dft_full_scf_hybrid = {
        **dft_full_scf_hybrid,
        "accounting_completeness": full_scf_accounting_completeness,
    }

    claim_list = list(claims) if claims is not None else _default_claims(
        verdict=verdict,
        simulation_result=simulation_result,
        convergence_status=convergence_status,
        simulation_samples=simulation_samples,
    )
    if claims is None:
        claim_list.extend(_low_fidelity_claims(low_fidelity_screening))
    if claims is None and codesign_verdict:
        codesign_trusted = bool(codesign_verdict.get("trusted_for_codesign_ranking", False))
        claim_list.append({
            "claim_id": "software_visible_codesign_current_candidate",
            "claim_type": "software_visible_codesign",
            "statement": (
                "The cited co-design candidate closed the software-visible descriptor/request/microarchitecture/completion path."
                if codesign_trusted
                else "The cited co-design candidate did not close the L4 software-visible proof path."
            ),
            "backend": "gem5_systemc",
            "source_fidelity": "L4",
            "predicted_only": False,
            "status": "simulated" if codesign_trusted else "blocked",
            "design_point_id": codesign_candidate.get("design_point_id", verdict.get("run_id")),
            "codesign_candidate_id": codesign_candidate.get("codesign_candidate_id"),
            "evidence_ids": [
                "verdict.json",
                "codesign_candidate.json",
                "codesign_verdict.json",
                "l4_execution_trace.json",
                "completion_proof.json",
                "gem5_l4_proof.json",
            ],
        })
    claim_validation = validate_claims(claim_list, verdict=verdict, evidence_index=evidence_index)
    validation_by_id = {item["claim_id"]: item for item in claim_validation["validations"]}

    trusted_validation = validation_by_id.get("feasibility_current_design", {})
    run_candidate_refs = _candidate_refs_from_handoff(
        run_dir,
        design_point=design_point,
        architecture=architecture,
        mapping=mapping,
        simulation_request=simulation_request,
    )
    candidate = _candidate_from_run(
        design_point=design_point,
        architecture=architecture,
        mapping=mapping,
        simulation_result=simulation_result,
        validation=trusted_validation,
        candidate_refs=run_candidate_refs,
    )

    sample_records = list(simulation_samples.get("samples", []) or [])
    trusted_sample_records = [sample for sample in sample_records if sample.get("trusted_final_eligible")]
    if len(trusted_sample_records) > 1:
        trusted_ranking = []
        for sample in sorted(
            trusted_sample_records,
            key=lambda item: float((item.get("metrics", {}) or {}).get("latency_ms") or float("inf")),
        ):
            ranking_entry = {
                "design_point_id": str(sample.get("design_point_id") or sample.get("candidate_id")),
                "architecture_id": sample.get("architecture_id")
                or architecture.get("architecture_id", design_point.get("system_architecture", {}).get("system_id")),
                "mapping_id": sample.get("mapping_id") or mapping.get("mapping_id"),
                "candidate_id": sample.get("candidate_id"),
                "queue_entry_id": sample.get("queue_entry_id"),
                "mapping_candidate_id": sample.get("mapping_candidate_id"),
                "backend": sample.get("backend"),
                "status": sample.get("status"),
                "trusted_scope": "bounded multi-candidate high-fidelity ranking; not global convergence unless convergence_status proves it",
                "metrics": sample.get("metrics", {}),
                "validation": {"trusted": True, "validation_status": "trusted"},
                "evidence_ids": list(sample.get("evidence_ids", []) or []),
            }
            ranking_entry.update(_candidate_identity_payload({
                "candidate_refs": _candidate_refs_from_sample(sample),
            }))
            trusted_ranking.append(ranking_entry)
    else:
        trusted_ranking = [candidate] if trusted_validation.get("trusted") else []
    hardware_ppa_ranking_entries = _dft_hardware_ppa_trusted_entries(dft_hardware_ppa_ranking)
    hardware_ppa_only_trusted_ranking = bool(not trusted_ranking and hardware_ppa_ranking_entries)
    if hardware_ppa_only_trusted_ranking:
        trusted_ranking = hardware_ppa_ranking_entries
    predicted_only_candidates = [
        {"claim": dict(claim), "validation": validation_by_id.get(str(claim.get("claim_id", claim.get("claim_type", "unknown"))), {})}
        for claim in claim_list
        if bool(claim.get("predicted_only", False)) or _claim_fidelity(claim) in PREDICTED_FIDELITIES
    ]
    blocked_or_untrusted = [
        {"claim": dict(claim), "validation": validation_by_id.get(str(claim.get("claim_id", claim.get("claim_type", "unknown"))), {})}
        for claim in claim_list
        if str(claim.get("status", claim.get("lifecycle_state", ""))).lower() in {"blocked", "unsupported", "stub", "untrusted"}
        or str(claim.get("claim_type")) == "unsupported_stub_limitation"
    ]
    deployment_full_scf_workplan = (
        dft_hardware_deployment_recommendation_readiness.get(
            "full_scf_numerical_closure_workplan", {}
        )
        if isinstance(
            dft_hardware_deployment_recommendation_readiness.get(
                "full_scf_numerical_closure_workplan", {}
            ),
            Mapping,
        )
        else {}
    )

    selected_recommendation: Dict[str, Any]
    if len(trusted_sample_records) > 1:
        selected_recommendation = {
            "status": "not_selected",
            "selection_status": "trusted_comparative_ranking_available_but_not_converged"
            if not convergence_status.get("converged")
            else "trusted_converged_recommendation_available",
            "trusted_winner": bool(convergence_status.get("converged", False)),
            "design_point_id": trusted_ranking[0]["design_point_id"],
            "rationale": (
                "Multiple trusted high-fidelity samples are ranked by latency. "
                "The recommendation remains non-global unless convergence_status.json proves configured convergence."
            ),
            "evidence_ids": _with_gem5_l4_proof_evidence(
                _claim_evidence_ids(trusted_ranking[0]) + ["mapping_simulation_samples.json", "convergence_status.json"],
                backend=str(trusted_ranking[0].get("backend", "")),
                trusted=True,
                proof_passed=bool(verdict.get("gem5_l4_proof_passed", False)),
            ),
        }
    elif hardware_ppa_only_trusted_ranking:
        winner_resolution_status = dft_architecture_winner_resolution.get("status")
        deployment_recommendation_status = deployment_recommendations.get("status")
        hardware_winner_resolution_eligible = (
            dft_architecture_winner_resolution.get("hardware_winner_resolution_eligible")
            is True
        )
        deployment_recommendations_available = (
            deployment_recommendations.get("status")
            == "hardware_ppa_deployment_recommendations_available"
        )
        selected_recommendation = {
            "status": "not_selected",
            "selection_status": (
                "hardware_ppa_deployment_recommendations_available_no_full_scf_winner"
                if deployment_recommendations_available
                else "hardware_ppa_ranking_available_no_full_dse_winner"
            ),
            "trusted_winner": False,
            "design_point_id": trusted_ranking[0]["design_point_id"],
            "fpga_best_architecture": (
                dft_architecture_winner_resolution.get("fpga_best_architecture")
                if hardware_winner_resolution_eligible
                else None
            ),
            "asic_best_architecture": (
                dft_architecture_winner_resolution.get("asic_best_architecture")
                if hardware_winner_resolution_eligible
                else None
            ),
            "rationale": (
                "Candidate-stamped FPGA/ASIC hardware-PPA deployment recommendations "
                "are available for planning, but they remain outside the full-SCF "
                "trusted winner and deliverable-complete claims."
                if deployment_recommendations_available
                else (
                    "Candidate-stamped major-kernel FPGA/DC PPA ranking is available, "
                    "but all tied or scoped hardware-only entries remain outside the "
                    "full-SCF deliverable winner claim until a separate system-level "
                    "tie-breaker and release claim gate close."
                )
            ),
            "winner_resolution_status": winner_resolution_status,
            "deployment_recommendation_status": deployment_recommendation_status,
            "deployment_recommendations": deployment_recommendations.get("recommendations", {}),
            "required_next_evidence": dft_architecture_winner_resolution.get(
                "required_next_evidence",
                {},
            ),
            "blocked_hardware_winner_summary": dft_architecture_winner_resolution.get(
                "blocked_recommendation_summary",
                {},
            ),
            "deployment_recommendation_readiness": {
                "present": dft_hardware_deployment_recommendation_readiness.get("present"),
                "status": dft_hardware_deployment_recommendation_readiness.get("status"),
                "fpga_can_name_winner": dft_hardware_deployment_recommendation_readiness.get("fpga_can_name_winner"),
                "asic_can_name_winner": dft_hardware_deployment_recommendation_readiness.get("asic_can_name_winner"),
                "deployment_target_selection_ready": dft_hardware_deployment_recommendation_readiness.get(
                    "deployment_target_selection_ready"
                ),
                "can_name_targeted_deployment_recommendation": dft_hardware_deployment_recommendation_readiness.get(
                    "can_name_targeted_deployment_recommendation"
                ),
                "can_name_final_recommendation": False,
                "final_recommendation_required_next_evidence_counts": (
                    dft_hardware_deployment_recommendation_readiness.get(
                        "final_recommendation_required_next_evidence_counts",
                        {},
                    )
                ),
                "full_scf_numerical_gate": dft_hardware_deployment_recommendation_readiness.get(
                    "full_scf_numerical_gate", {}
                ),
                "full_scf_numerical_closure_required": deployment_full_scf_workplan.get("required"),
                "full_scf_numerical_closure_work_item_count": deployment_full_scf_workplan.get(
                    "work_item_count"
                ),
            },
            "deployment_decision_packet": {
                "present": dft_hardware_deployment_decision_packet.get("present"),
                "status": dft_hardware_deployment_decision_packet.get("status"),
                "planning_packet_ready": dft_hardware_deployment_decision_packet.get(
                    "planning_packet_ready"
                ),
                "can_name_scoped_hardware_ppa_winners": (
                    dft_hardware_deployment_decision_packet.get(
                        "can_name_scoped_hardware_ppa_winners"
                    )
                ),
                "deployment_target_selection_ready": (
                    dft_hardware_deployment_decision_packet.get(
                        "deployment_target_selection_ready"
                    )
                ),
                "full_scf_numerical_gate_passed": (
                    dft_hardware_deployment_decision_packet.get(
                        "full_scf_numerical_gate_passed"
                    )
                ),
                "can_name_targeted_deployment_recommendation": False,
                "can_name_final_recommendation": False,
            },
            "evidence_ids": trusted_ranking[0]["evidence_ids"]
            + (
                ["dft_candidate_specific_ppa_provenance_audit.json"]
                if dft_candidate_specific_ppa_provenance.get("present")
                else []
            )
            + (
                ["dft_architecture_winner_resolution.json"]
                if dft_architecture_winner_resolution.get("present")
                else []
            )
            + (
                ["dft_hardware_deployment_recommendation_readiness.json"]
                if dft_hardware_deployment_recommendation_readiness.get("present")
                else []
            )
            + (
                ["dft_hardware_deployment_decision_packet.json"]
                if dft_hardware_deployment_decision_packet.get("present")
                else []
            ),
        }
    elif trusted_ranking:
        selected_recommendation = {
            "status": "not_selected",
            "selection_status": "trusted_feasibility_candidate_not_cross_candidate_winner",
            "trusted_winner": False,
            "design_point_id": candidate["design_point_id"],
            "rationale": (
                "This run is SystemC/gem5+SystemC-backed and feasible for the cited design point. "
                "It is not promoted to a global best-architecture winner without comparable trusted candidates."
            ),
            "evidence_ids": candidate["evidence_ids"],
        }
    else:
        selected_recommendation = {
            "status": "not_selected",
            "selection_status": "no_trusted_recommendation",
            "trusted_winner": False,
            "rationale": "No candidate passed trusted claim validation; predicted-only or blocked entries are excluded from trusted winners.",
            "evidence_ids": ["verdict.json", "claim_validation.json"],
        }
    if trusted_ranking:
        selected_recommendation.update(_candidate_identity_payload(trusted_ranking[0]))
    if search_admission_validation.get("present") and search_admission_validation.get("valid") is not True:
        selected_recommendation = dict(selected_recommendation)
        selected_recommendation.update({
            "status": "not_selected",
            "selection_status": "blocked_search_admission_validation",
            "trusted_winner": False,
            "control_plane_validation_status": search_admission_validation.get("status"),
            "search_admission_validation": "search_admission_validation",
            "rationale": (
                str(selected_recommendation.get("rationale") or "")
                + " Search/admission validation is blocked, so Step5 cannot promote this report "
                "to a trusted campaign/search winner."
            ).strip(),
            "evidence_ids": sorted(set(
                list(selected_recommendation.get("evidence_ids", []) or [])
                + [
                    ref["path"]
                    for ref in search_admission_validation.get("artifact_refs", {}).values()
                    if isinstance(ref, Mapping) and ref.get("exists") and ref.get("path")
                ]
            )),
        })

    limitations = list(verdict.get("evidence_gaps", []) or [])
    if search_admission_validation.get("present") and search_admission_validation.get("valid") is not True:
        limitations.append(
            "Search/admission validation failed; Step5 final claims remain fail-closed until "
            "search_iteration_plan_validation.json, step3_admission_queue_validation.json, "
            "and campaign_search_admission_plan.json pass together."
        )
    if blockers.get("blockers"):
        limitations.append("gem5+SystemC L4 binding is untrusted for this run.")
    if codesign_verdict and not codesign_verdict.get("trusted_for_codesign_ranking", False):
        limitations.append("Software-visible co-design claim is blocked until codesign_verdict.json and gem5_l4_proof.json pass.")
    if not trusted_ranking:
        limitations.append("No trusted final ranking is available from the cited evidence.")
    elif hardware_ppa_only_trusted_ranking:
        limitations.append(
            "No generic full-workload trusted final ranking is available; "
            "trusted_ranking entries are scoped to candidate-stamped major-kernel "
            "hardware PPA and cannot select a full-SCF DSE winner."
        )
    if (
        dft_architecture_winner_resolution.get("present")
        and dft_architecture_winner_resolution.get("hardware_winner_resolution_eligible") is not True
    ):
        limitations.append(
            "FPGA/ASIC architecture winner resolution is blocked; tied or insufficient "
            "candidate-stamped hardware PPA cannot be converted into a best-architecture claim."
        )
    if (
        dft_architecture_winner_resolution.get("present")
        and dft_architecture_winner_resolution.get("validation", {}).get("valid") is not True
    ):
        limitations.append(
            "FPGA/ASIC architecture winner resolution validation failed; Step5 "
            "blocks deployment recommendations from stale or invalid winner-resolution artifacts."
        )
    if (
        dft_architecture_winner_resolution.get("present")
        and dft_architecture_winner_resolution.get("status_validation", {}).get("passed") is not True
    ):
        limitations.append(
            "FPGA/ASIC architecture winner resolution status sidecar did not pass; "
            "deployment recommendations remain blocked until the winner-resolution sidecars are rebuilt."
        )
    if (
        deployment_recommendations.get("status")
        == "hardware_ppa_deployment_recommendations_available"
    ):
        limitations.append(
            "Deployment-specific FPGA/ASIC hardware-PPA recommendations are "
            "available for planning only; selected_recommendation.trusted_winner "
            "and deliverable_complete remain false until full-SCF release gates close."
        )
    if dft_deployment_decision_support.get("present"):
        release_gates = dft_deployment_decision_support.get("release_completion_gates", {})
        if isinstance(release_gates, Mapping):
            if release_gates.get("deployment_sidecar_validation_passed") is not True:
                limitations.append(
                    "Deployment decision-support sidecar validation did not pass; "
                    "FPGA/ASIC current-best and target-feasibility readiness remain fail-closed."
                )
            if release_gates.get("full_scf_numerical_passed") is not True:
                limitations.append(
                    "Full-SCF host+accelerator numerical gate is not passed; "
                    "FPGA/ASIC deployment recommendations remain decision-support only."
                )
            if release_gates.get("candidate_set_consistency_status") in {
                "candidate_set_mismatch",
                "candidate_sets_not_checked_missing_sources",
                "candidate_sets_empty",
            }:
                limitations.append(
                    "Release-gate candidate IDs do not exactly match current binding/trial-ledger admission."
                )
            if (
                release_gates.get("candidate_set_consistency_checked") is True
                and release_gates.get("candidate_set_consistency_validation_valid") is not True
            ):
                limitations.append(
                    "Candidate-set consistency artifact validation did not pass; "
                    "release candidate-set comparison remains fail-closed."
                )
            if release_gates.get("deployment_candidate_alignment_status") not in {
                "deployment_candidate_alignment_passed",
                "deployment_candidate_alignment_not_checked_no_recommendations",
                None,
            }:
                limitations.append(
                    "Deployment recommendation candidate IDs are not fully aligned "
                    "with trusted candidate-set and full-SCF comparison coverage."
                )
            source_consensus_status = release_gates.get("deployment_source_consensus_status")
            if source_consensus_status not in {
                "deployment_source_consensus_passed",
                "deployment_source_consensus_not_checked_no_candidates",
                None,
            }:
                limitations.append(
                    "Deployment recommendation source artifacts disagree on "
                    "candidate/design identity or have insufficient independent "
                    "sources; Step5 recommendations remain fail-closed until "
                    "the sources are reconciled."
                )
            target_consensus_status = release_gates.get("deployment_target_consensus_status")
            if target_consensus_status not in {
                "deployment_target_consensus_passed",
                "deployment_target_consensus_not_checked_no_targets",
                None,
            }:
                limitations.append(
                    "Deployment target selection artifacts disagree on FPGA/ASIC "
                    "target identity or have insufficient independent sources; "
                    "selected device/part/library must be reconciled before "
                    "deployment recommendations are evidence-backed."
                )
    if convergence_status:
        limitations.extend(str(item) for item in convergence_status.get("limitations", []) or [])
        if convergence_status.get("stop_reason") == "budget_exhausted" and not convergence_status.get("converged"):
            limitations.append("Feedback loop stopped by budget exhaustion; this is not proof of global convergence.")
    importer_payload = workload_package.get("importer", {}) if isinstance(workload_package.get("importer", {}), Mapping) else {}
    if workload_package and importer_payload.get("claim_boundary") not in {"full_workload", "full", "end_to_end"}:
        limitations.append("WorkloadPackage claim boundary is reduced/diagnostic; trusted final claims are not allowed for this run.")
    if graph_lowering and not graph_lowering.get("full_workload_eligible", False):
        limitations.append("Graph lowering report is not full-workload eligible; final trusted claims are blocked for this run.")
    if step2_search_provenance.get("present"):
        limitations.append(
            "Step2 search/admission provenance is replay and audit evidence only; "
            "it does not prove Step3 measurements, global convergence, FPGA/ASIC PPA, or deliverable completion."
        )
    if low_fidelity_screening.get("present"):
        limitations.append("Step2 L1/L2 screening is low-fidelity candidate-generation evidence only; it is excluded from trusted final ranking.")
    if step3_queue_aggregation.get("present"):
        limitations.append(
            "Step3 queue aggregation is bounded per-candidate timing evidence only; "
            "it does not prove global search convergence, FPGA/ASIC PPA, or deliverable completion."
        )
    if deployment_recommendation_plan.get("present"):
        limitations.append(
            "Deployment recommendation planning is proposal-only hard-gate scheduling; "
            "it does not prove FPGA/ASIC winners, PPA closure, or deliverable completion."
        )
    if dft_hardware_deployment_recommendation_readiness.get("present"):
        if dft_hardware_deployment_recommendation_readiness.get("can_name_hardware_ppa_winners") is not True:
            limitations.append(
                "Hardware deployment recommendation readiness is blocked; final_report "
                "must surface required next evidence instead of naming FPGA/ASIC "
                "hardware-PPA deployment recommendations."
            )
        if dft_hardware_deployment_recommendation_readiness.get("deployment_target_selection_ready") is not True:
            limitations.append(
                "Deployment target selection readiness is not closed; final FPGA/ASIC "
                "deployment recommendations remain blocked even when hardware-PPA "
                "winner resolution exists."
            )
        readiness_full_scf_workplan = (
            dft_hardware_deployment_recommendation_readiness.get(
                "full_scf_numerical_closure_workplan", {}
            )
            if isinstance(
                dft_hardware_deployment_recommendation_readiness.get(
                    "full_scf_numerical_closure_workplan", {}
                ),
                Mapping,
            )
            else {}
        )
        if readiness_full_scf_workplan.get("required") is True:
            limitations.append(
                "Full-SCF numerical closure workplan is provenance-only; "
                "it schedules missing trusted host+accelerator evidence and "
                "does not upgrade deployment, hardware-completion, release, "
                "or deliverable claims."
            )
    if dft_evidence_ledger.get("present"):
        limitations.append(
            "DFT evidence ledger artifacts are audit/reporting evidence only; "
            "they do not prove full-SCF completion or FPGA/ASIC PPA claims."
        )
        dft_eda_summary = (
            dft_evidence_ledger.get("eda_summary", {})
            if isinstance(dft_evidence_ledger.get("eda_summary", {}), Mapping)
            else {}
        )
        if dft_eda_summary.get("ic_eda_tool_availability_completion_claim"):
            limitations.append(
                "IC/EDA tool availability is cited only as reachability/planning evidence; "
                "it is not candidate-specific kernel PPA, timing, area, or implementation evidence."
            )
    if dft_trial_state_ledger.get("present"):
        limitations.append(
            "DFT trial-state ledger artifacts prove ID propagation and state/audit continuity only; "
            "they do not prove numerical correctness, trusted Pareto, or FPGA/ASIC PPA closure."
        )
    if dft_candidate_binding_map.get("present"):
        limitations.append(
            "DFT candidate binding maps relate hierarchical search IDs to frozen release IDs only; "
            "they are heuristic provenance and do not prove numerical correctness, trusted Pareto, or FPGA/ASIC PPA closure."
        )
    if dft_hardware_completion_workplan.get("present"):
        limitations.append(
            "DFT hardware completion workplans enumerate candidate-specific kernel closure work only; "
            "they do not prove candidate-specific numerical correctness, trusted Pareto, or FPGA/ASIC PPA closure."
        )
    if dft_hardware_closure_shards.get("present"):
        limitations.append(
            "DFT hardware closure shards are parallel queue metadata only; "
            "they do not attach candidate-specific RTL/HLS bundles or prove Vivado/DC closure."
        )
    if dft_hardware_closure_packets.get("present"):
        limitations.append(
            "DFT hardware closure packets and runbooks are execution instructions only; "
            "they do not attach candidate-specific evidence or upgrade hardware completion claims."
        )
    if dft_hardware_closure_candidate_bundles.get("present"):
        limitations.append(
            "DFT hardware closure candidate bundles are template contracts for expected source/evidence placement only; "
            "they do not contain raw tool results or upgrade correctness, PPA, trusted ranking, or completion claims."
        )
    if dft_hardware_closure_unit_provenance.get("present"):
        limitations.append(
            "DFT hardware closure unit provenance stages candidate/kernel source/tool/command/transcript metadata only; "
            "it does not contain raw tool results or upgrade correctness, PPA, trusted ranking, or completion claims."
        )
    if dft_hardware_closure_source_flow_plan.get("present"):
        limitations.append(
            "DFT hardware closure source-flow plans bind candidate/kernel units to validated source-flow directories "
            "before materialization only; they do not copy evidence, adjudicate hard gates, or upgrade PPA/completion claims."
        )
    if dft_hardware_closure_raw_stage_materialization.get("present"):
        limitations.append(
            "DFT hardware closure raw-stage materialization copies or wraps existing kernel-flow outputs into "
            "candidate-specific packet filenames only; registration, parsing, gate adjudication, and PPA/completion "
            "claims remain separate."
        )
    if dft_hardware_closure_raw_transcript_registration.get("present"):
        limitations.append(
            "DFT hardware closure raw transcript registration records SHA-256 refs for already-present "
            "candidate-specific raw files only; it does not create evidence, parse results, adjudicate hard gates, "
            "or upgrade completion claims."
        )
    if dft_hardware_closure_evidence_intake.get("present"):
        limitations.append(
            "DFT hardware closure evidence intake checks file presence only; "
            "it does not adjudicate correctness, Vivado/DC PPA, or deliverable completion."
        )
    if dft_hardware_closure_adjudication.get("present"):
        limitations.append(
            "DFT hardware closure adjudication is a fail-closed stage ledger only; "
            "it does not pass hard gates without parsed candidate-specific evidence."
        )
    if dft_hardware_closure_parsed_evidence.get("present"):
        limitations.append(
            "DFT hardware closure parsed-evidence manifests are parser/readiness evidence only; "
            "they do not adjudicate hard gates or upgrade completion claims."
        )
    if dft_hardware_closure_parser_run.get("present"):
        limitations.append(
            "DFT hardware closure parser runs consume already-present candidate-specific raw files only; "
            "they write parser outputs but do not adjudicate hard gates or upgrade completion claims."
        )
    if dft_hardware_closure_gate_adjudication.get("present"):
        limitations.append(
            "DFT hardware closure gate adjudication records per-stage hard-gate verdicts only; "
            "it does not by itself upgrade release completion, trusted Pareto, FPGA PPA, or ASIC PPA claims."
        )
    if dft_hardware_closure_release_gate.get("present"):
        limitations.append(
            "DFT hardware closure release gates roll up candidate/kernel gate status only; "
            "they cannot directly mark deliverable completion or trusted Pareto winners."
        )
    if dft_hardware_ppa_ranking.get("present"):
        limitations.append(
            "DFT hardware PPA ranking compares candidate-stamped major-kernel PPA only; "
            "it cannot mark full-SCF deliverable completion or choose a single end-to-end winner "
            "while system-level tie-breakers/release gates remain open."
        )
    if dft_candidate_specific_ppa_provenance.get("present"):
        limitations.append(
            "Candidate-specific PPA provenance audit must be trusted before parsed hard-gate "
            "files can support FPGA/ASIC best-architecture proof; copied/wrapped source-flow "
            "or metadata-only evidence remains blocked and queued for fresh tool execution."
        )
    if dft_l4_goal_binding.get("present"):
        limitations.append(
            "DFT L4/gem5 goal binding cites software-visible GenericAccel evidence only; "
            "it does not prove wave36 candidate identity, six-SCF workload closure, FPGA/ASIC PPA, "
            "or full deliverable completion unless explicit current-goal crosswalks pass."
        )
    if dft_audit_semantic_closure.get("present"):
        limitations.append(
            "DFT semantic audit closure is source-hash-backed audit evidence for five HIGH semantic findings only; "
            "it does not prove hardware release eligibility, trusted Pareto winners, FPGA/ASIC PPA, or final deliverable completion."
        )
    if dft_full_scf_hybrid.get("present"):
        limitations.append(
            "DFT full-SCF evaluated-hybrid artifacts expose schedule/cost accounting only; "
            "they do not prove full-SCF device residency, numerical correctness, or FPGA/ASIC PPA closure."
        )
    workload_family = manifest.get("workload_family", workload_package.get("workload_family"))
    if numerical_validation.get("passed"):
        limitations.append(
            "Timing-level numeric outputs are reference-validated for this generic SystemC run, "
            "but this does not prove profile-specific domain correctness or board/ASIC results."
        )
    else:
        limitations.append("Timing-level workload evidence does not by itself prove profile-specific domain correctness or board/ASIC results.")
    if profile_domain_validation:
        limitations.append(str(profile_domain_validation.get("boundary", "Profile/importer-domain correctness is unclaimed without profile/importer validation evidence.")))

    target_scoped_recommendation_sections = _target_scoped_recommendation_sections(
        deployment_recommendations,
        ppa_ranking=dft_hardware_ppa_ranking,
    )

    report = {
        "schema_version": "dse.final_report.v1",
        "generated_at": _now_iso(),
        "run_metadata": {
            "run_id": manifest.get("run_id", verdict.get("run_id", simulation_result.get("run_id"))),
            "backend": manifest.get("backend", verdict.get("backend", simulation_result.get("backend"))),
            "evidence_mode": manifest.get("evidence_mode", verdict.get("evidence_mode")),
            "trusted_for_final_ranking": bool(verdict.get("trusted_for_final_ranking", False)),
            "manifest": "manifest.json",
            "verdict": "verdict.json",
        },
        "workload": {
            "workload_id": manifest.get("workload", workload_package.get("workload_id", workload_graph.get("graph_id"))),
            "workload_family": workload_family,
            "profile_id": (workload_package.get("profile", {}) or {}).get("profile_id", verdict.get("workload_package", {}).get("profile_id")),
            "profile_version": (workload_package.get("profile", {}) or {}).get("profile_version", verdict.get("workload_package", {}).get("profile_version")),
            "importer_id": importer_payload.get("importer_id", manifest.get("workload_importer")),
            "importer_version": importer_payload.get("importer_version"),
            "claim_boundary": importer_payload.get("claim_boundary"),
            "source": workload_package.get("source", {}),
            "profile": workflow_payload,
            "workflow": workflow_payload,
            "graph_id": workload_graph.get("graph_id"),
            "graph_lowering": {
                "artifact": "graph_lowering_report.json",
                "status": graph_lowering.get("status"),
                "full_workload_eligible": graph_lowering.get("full_workload_eligible"),
                "unsupported_constructs": graph_lowering.get("unsupported_constructs", []),
            },
            "required_coverage": simulation_result.get("required_coverage", simulation_result.get("profile_required_coverage", [])),
            "profile_required_coverage": simulation_result.get("profile_required_coverage", simulation_result.get("required_coverage", [])),
            "missing_required_coverage": simulation_result.get("missing_required_coverage", []),
            "domain_validation": simulation_result.get("domain_validation", profile_domain_validation),
            "profile_domain_validation": simulation_result.get("profile_domain_validation", profile_domain_validation),
            "unavailable_metrics": unavailable_metrics,
            "phase_summary": _phase_summary(run_dir),
        },
        "architecture_catalog_scope": {
            "architecture_id": architecture.get("architecture_id"),
            "architecture_family": architecture.get("architecture_family"),
            "status": architecture.get("status"),
            "trusted_final_eligible": architecture.get("trusted_final_eligible", False),
            "scope": architecture.get("architecture_scope"),
        },
        "search_configuration": {
            "mapping_policy": mapping.get("mapping_policy"),
            "search_status": mapping.get("search_status"),
            "scheduling_policy": design_point.get("scheduling_policy"),
            "config": design_point.get("config", {}),
        },
        "search_admission_validation": search_admission_validation,
        "step2_search_provenance": step2_search_provenance,
        "feedback_loop": {
            "simulation_samples_artifact": "mapping_simulation_samples.json",
            "feedback_state_artifact": "mapping_feedback_state.json",
            "convergence_status_artifact": "convergence_status.json",
            "sample_count": len(sample_records),
            "trusted_sample_count": len(trusted_sample_records),
            "feedback_state_summary": {
                "screened_count": feedback_state.get("screened_count"),
                "promoted_count": feedback_state.get("promoted_count"),
                "simulation_budget": feedback_state.get("simulation_budget", {}),
                "ranking_update": feedback_state.get("ranking_update", {}),
            },
            "convergence": convergence_status,
        },
        "step3_queue_aggregation": step3_queue_aggregation,
        "deployment_recommendation_plan": deployment_recommendation_plan,
        "dft_hardware_deployment_recommendation_readiness": dft_hardware_deployment_recommendation_readiness,
        "low_fidelity_screening": low_fidelity_screening,
        "dft_evidence_ledger": dft_evidence_ledger,
        "major_kernel_matrix": dft_evidence_ledger.get("major_kernel_matrix", {}),
        "dft_trial_state_ledger": dft_trial_state_ledger,
        "dft_candidate_binding_map": dft_candidate_binding_map,
        "dft_hardware_completion_workplan": dft_hardware_completion_workplan,
        "dft_hardware_closure_shards": dft_hardware_closure_shards,
        "dft_hardware_closure_packets": dft_hardware_closure_packets,
        "dft_hardware_closure_candidate_bundles": dft_hardware_closure_candidate_bundles,
        "dft_hardware_closure_unit_provenance": dft_hardware_closure_unit_provenance,
        "dft_hardware_closure_artifact_chain": dft_hardware_closure_artifact_chain,
        "dft_hardware_closure_source_flow_plan": dft_hardware_closure_source_flow_plan,
        "dft_hardware_closure_raw_stage_materialization": dft_hardware_closure_raw_stage_materialization,
        "dft_hardware_closure_raw_transcript_registration": dft_hardware_closure_raw_transcript_registration,
        "dft_hardware_closure_evidence_intake": dft_hardware_closure_evidence_intake,
        "dft_hardware_closure_adjudication": dft_hardware_closure_adjudication,
        "dft_hardware_closure_parsed_evidence": dft_hardware_closure_parsed_evidence,
        "dft_hardware_closure_parser_run": dft_hardware_closure_parser_run,
        "dft_hardware_closure_gate_adjudication": dft_hardware_closure_gate_adjudication,
        "dft_hardware_closure_release_gate": dft_hardware_closure_release_gate,
        "dft_hardware_ppa_ranking": dft_hardware_ppa_ranking,
        "dft_candidate_specific_ppa_provenance": dft_candidate_specific_ppa_provenance,
        "dft_architecture_winner_resolution": dft_architecture_winner_resolution,
        "deployment_recommendations": deployment_recommendations,
        "target_scoped_recommendation_sections": target_scoped_recommendation_sections,
        "dft_deployment_decision_support": dft_deployment_decision_support,
        "dft_hardware_deployment_decision_packet": dft_hardware_deployment_decision_packet,
        "dft_deployment_comparator": dft_deployment_comparator,
        "dft_deployment_selector": dft_deployment_selector,
        "dft_deployment_decision_summary": dft_deployment_decision_summary,
        "dft_l4_goal_binding": dft_l4_goal_binding,
        "dft_audit_semantic_closure": dft_audit_semantic_closure,
        "dft_full_scf_evaluated_hybrid": dft_full_scf_hybrid,
        "qe_baseline_row_accounting_attachment": qe_baseline_row_accounting_attachment,
        "full_scf_accounting_completeness": full_scf_accounting_completeness,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "codesign": {
            "candidate_artifact": "codesign_candidate.json" if codesign_candidate else None,
            "verdict_artifact": "codesign_verdict.json" if codesign_verdict else None,
            "codesign_candidate_id": codesign_candidate.get("codesign_candidate_id"),
            "l4_required": bool(
                (codesign_candidate.get("promotion_policy", {}) or {}).get("l4_required", False)
                if isinstance(codesign_candidate.get("promotion_policy", {}), Mapping)
                else False
            ),
            "trusted_for_codesign_ranking": bool(codesign_verdict.get("trusted_for_codesign_ranking", False)),
            "status": codesign_verdict.get("status", "not_run" if codesign_candidate else "unavailable"),
            "evidence_ids": codesign_verdict.get("evidence_ids", []),
        },
        "numerical_validation": {
            "artifact": "simulator_consistency_check.json" if simulator_consistency_check else "numerical_validation.json",
            "status": numerical_validation.get("status"),
            "passed": bool(numerical_validation.get("passed", False)),
            "scope": numerical_validation.get("scope"),
            "summary": numerical_validation.get("summary", {}),
            "domain_correctness_boundary": numerical_validation.get("domain_correctness_boundary"),
        },
        "full_scf_evaluated_hybrid_costs": _full_scf_evaluated_hybrid_costs(
            simulation_result,
            descriptor=dft_full_scf_hybrid.get("cost_model") and {
                "cost_model": dft_full_scf_hybrid.get("cost_model"),
            },
            ppa_summary=_load_json(run_dir / str(dft_full_scf_hybrid.get("artifacts", {}).get("full_scf_ppa_summary.json", {}).get("path")))
            if dft_full_scf_hybrid.get("present")
            and dft_full_scf_hybrid.get("artifacts", {}).get("full_scf_ppa_summary.json", {}).get("path")
            else None,
            accounting_completeness=full_scf_accounting_completeness,
        ),
        "trusted_ranking": trusted_ranking,
        "predicted_only_candidates": predicted_only_candidates,
        "blocked_or_untrusted": blocked_or_untrusted,
        "pareto_alternatives": (
            dft_hardware_ppa_ranking.get("pareto_alternatives", [])
            if hardware_ppa_only_trusted_ranking
            else []
        ),
        "selected_recommendation": selected_recommendation,
        "claims": claim_list,
        "claim_validation": claim_validation,
        "evidence_requirements": evidence_requirement_table(),
        "evidence_index": evidence_index,
        "limitations": limitations,
        "replay_instructions": {
            "python_replay_command": manifest.get("replay_metadata", {}).get("python_replay_command", manifest.get("cli_command", [])),
            "simulator_replay_command": manifest.get("replay_metadata", {}).get("simulator_replay_command", manifest.get("simulator_command", [])),
            "run_directory": str(run_dir),
            "required_artifact_index": "artifact_manifest.json",
        },
    }

    requirements_payload = {
        "schema_version": "dse.evidence_requirements.v1",
        "generated_at": _now_iso(),
        "requirements": evidence_requirement_table(),
        "trusted_backend_policy": sorted(TRUSTED_BACKENDS),
        "predicted_fidelity_policy": sorted(PREDICTED_FIDELITIES),
    }
    return report, claim_validation, requirements_payload


def render_markdown_report(report: Mapping[str, Any]) -> str:
    """Render a concise audit-friendly Markdown report."""
    run = report.get("run_metadata", {})
    selected = report.get("selected_recommendation", {})
    workload = report.get("workload", {}) if isinstance(report.get("workload", {}), Mapping) else {}
    domain_validation = workload.get("profile_domain_validation", workload.get("domain_validation", {}))
    domain_validation = domain_validation if isinstance(domain_validation, Mapping) else {}
    lines = [
        "# Generic DSE Final Report",
        "",
        "## Executive Summary",
        f"- Run id: `{run.get('run_id')}`",
        f"- Backend: `{run.get('backend')}`",
        f"- Workload family: `{workload.get('workload_family')}`",
        f"- Profile: `{workload.get('profile_id')}` `{workload.get('profile_version')}`",
        f"- Importer: `{workload.get('importer_id')}` `{workload.get('importer_version')}`",
        f"- Trusted for final ranking: `{run.get('trusted_for_final_ranking')}`",
        f"- Recommendation status: `{selected.get('selection_status')}`",
        f"- Trusted winner: `{selected.get('trusted_winner')}`",
        f"- Profile/importer-domain validation: `{domain_validation.get('status')}`",
        "",
        "## Trusted Ranking",
    ]
    trusted = report.get("trusted_ranking", []) or []
    if trusted:
        for idx, candidate in enumerate(trusted, start=1):
            metrics = candidate.get("metrics", {})
            lines.append(
                f"{idx}. `{candidate.get('design_point_id')}` — latency `{metrics.get('latency_ms')}` ms, "
                f"energy `{metrics.get('energy_j')}` J, evidence `{', '.join(candidate.get('evidence_ids', []))}`"
            )
    else:
        lines.append("- No trusted ranking entries; predicted-only and blocked candidates are excluded from winners.")

    lines.extend(["", "## Predicted-only / Blocked / Untrusted", ""])
    blocked = report.get("blocked_or_untrusted", []) or []
    predicted = report.get("predicted_only_candidates", []) or []
    if not blocked and not predicted:
        lines.append("- None recorded.")
    for item in predicted:
        claim = item.get("claim", {})
        lines.append(f"- Predicted-only: `{claim.get('claim_id', claim.get('claim_type'))}`")
    for item in blocked:
        claim = item.get("claim", {})
        lines.append(f"- Blocked/untrusted: `{claim.get('claim_id', claim.get('claim_type'))}` — {claim.get('statement', '')}")

    low_fidelity = report.get("low_fidelity_screening", {})
    low_fidelity = low_fidelity if isinstance(low_fidelity, Mapping) else {}
    l1 = low_fidelity.get("l1", {}) if isinstance(low_fidelity.get("l1", {}), Mapping) else {}
    l2 = low_fidelity.get("l2", {}) if isinstance(low_fidelity.get("l2", {}), Mapping) else {}
    lines.extend([
        "",
        "## Low-Fidelity Screening",
        f"- Present: `{low_fidelity.get('present')}`",
        f"- Status: `{low_fidelity.get('status')}`",
        f"- Passed Step3 gate: `{low_fidelity.get('passed')}`",
        f"- Role: `{low_fidelity.get('low_fidelity_role')}`",
        f"- Excluded from trusted ranking: `{low_fidelity.get('excluded_from_trusted_ranking')}`",
    ])
    if low_fidelity.get("present"):
        lines.extend([
            f"- L1: `{l1.get('status')}` confidence `{l1.get('confidence')}` score `{l1.get('promotion_score')}`",
            f"- L2: `{l2.get('status')}` confidence `{l2.get('confidence')}` score `{l2.get('promotion_score')}`",
            f"- Missing artifacts: `{', '.join(low_fidelity.get('missing_artifacts', []) or []) or 'none'}`",
        ])
    else:
        lines.append("- No L1/L2 screening artifacts found in this run directory.")

    search_admission = report.get("search_admission_validation", {})
    search_admission = search_admission if isinstance(search_admission, Mapping) else {}
    lines.extend([
        "",
        "## Search / Admission Validation",
        f"- Present: `{search_admission.get('present')}`",
        f"- Status: `{search_admission.get('status')}`",
        f"- Valid: `{search_admission.get('valid')}`",
        f"- Search-iteration validation: `{search_admission.get('search_iteration_plan_validation_status')}` / `{search_admission.get('search_iteration_plan_validation_valid')}`",
        f"- Step3 admission-queue validation: `{search_admission.get('step3_admission_queue_validation_status')}` / `{search_admission.get('step3_admission_queue_validation_valid')}`",
        f"- Campaign admission: `{search_admission.get('campaign_search_admission_plan_status')}` / `{search_admission.get('campaign_admission_status')}`",
        f"- Execution allowed by campaign plan: `{search_admission.get('execution_allowed')}`",
        "- Boundary: search/admission artifacts are control-plane handoff evidence only; failed validation blocks trusted final search/admission claims.",
    ])
    search_admission_errors: List[object] = []
    raw_search_admission_errors = search_admission.get("errors")
    if isinstance(raw_search_admission_errors, list):
        search_admission_errors = raw_search_admission_errors
    for error in search_admission_errors[:5]:
        if isinstance(error, Mapping):
            lines.append(f"- Error: `{error.get('field')}` — {error.get('message')}")

    dft_ledger = report.get("dft_evidence_ledger", {})
    dft_ledger = dft_ledger if isinstance(dft_ledger, Mapping) else {}
    eda_summary = dft_ledger.get("eda_summary", {}) if isinstance(dft_ledger.get("eda_summary", {}), Mapping) else {}
    major_kernel_matrix = (
        dft_ledger.get("major_kernel_matrix", {})
        if isinstance(dft_ledger.get("major_kernel_matrix", {}), Mapping)
        else {}
    )
    ledger_full_scf = (
        dft_ledger.get("full_scf_hybrid_bundle", {})
        if isinstance(dft_ledger.get("full_scf_hybrid_bundle", {}), Mapping)
        else {}
    )
    ic_eda_file_list = (
        eda_summary.get("ic_eda_tool_availability_file_list", {})
        if isinstance(eda_summary.get("ic_eda_tool_availability_file_list", {}), Mapping)
        else {}
    )
    ic_eda_availability_file = (
        ic_eda_file_list.get("availability", {})
        if isinstance(ic_eda_file_list.get("availability", {}), Mapping)
        else {}
    )
    ic_eda_attempts_file = (
        ic_eda_file_list.get("attempts", {})
        if isinstance(ic_eda_file_list.get("attempts", {}), Mapping)
        else {}
    )
    ic_eda_transcript_refs = [
        ref
        for ref in (eda_summary.get("ic_eda_tool_availability_raw_transcript_refs") or [])
        if isinstance(ref, Mapping)
    ]
    lines.extend([
        "",
        "## DFT Evidence Ledger",
        f"- Present: `{dft_ledger.get('present')}`",
        f"- Deliverable complete: `{dft_ledger.get('deliverable_complete')}`",
        f"- EDA status: `{eda_summary.get('status')}`",
        f"- IC/EDA availability status: `{eda_summary.get('tool_availability_status')}`",
        f"- IC/EDA availability payload status: `{eda_summary.get('ic_eda_tool_availability_payload_status')}`",
        f"- IC/EDA availability completion claim: `{eda_summary.get('ic_eda_tool_availability_completion_claim')}`",
        f"- IC/EDA availability file list: availability `{ic_eda_availability_file.get('path')}`, attempts `{ic_eda_attempts_file.get('path')}`",
        f"- IC/EDA first verification source: `{eda_summary.get('ic_eda_tool_availability_first_verification_source')}`",
        f"- IC/EDA availability kernel PPA evidence: `{eda_summary.get('ic_eda_tool_availability_kernel_ppa_evidence')}`",
        f"- IC/EDA availability raw attempts: `{eda_summary.get('ic_eda_tool_availability_raw_attempt_count')}`",
        f"- IC/EDA availability raw transcript refs: `{eda_summary.get('ic_eda_tool_availability_raw_transcript_ref_count')}`",
        f"- IC/EDA availability malformed transcript refs: `{eda_summary.get('ic_eda_tool_availability_transcript_ref_malformed_count')}`",
        f"- Major-kernel matrix status: `{eda_summary.get('major_kernel_matrix_status')}`",
        f"- Major-kernel matrix trusted: `{eda_summary.get('major_kernel_matrix_trusted')}`",
        f"- Major-kernel matrix rows: `{major_kernel_matrix.get('present_row_count')}` / `{major_kernel_matrix.get('expected_row_count')}`",
        f"- Major-kernel matrix missing rows: `{', '.join(str(item) for item in (major_kernel_matrix.get('missing_kernel_ids', []) or [])) or 'none'}`",
        f"- Major-kernel matrix blockers: `{', '.join(str(item) for item in (major_kernel_matrix.get('blocker_ids', []) or [])) or 'none'}`",
        f"- Hardware completion eligible: `{eda_summary.get('hardware_completion_eligible')}`",
        f"- Full-SCF hybrid bundle status: `{ledger_full_scf.get('status')}`",
        f"- Full-SCF hybrid bundle completion claim: `{ledger_full_scf.get('completion_claim')}`",
        "- Boundary: this citation does not upgrade Step4/Step5 trust, does not prove full-SCF completion, and does not create FPGA/ASIC PPA claims.",
    ])
    major_kernel_rows = major_kernel_matrix.get("rows", []) if isinstance(major_kernel_matrix.get("rows", []), list) else []
    if major_kernel_rows:
        lines.append("- Major-kernel matrix rows:")
        for row in major_kernel_rows:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                f"  - `{row.get('kernel_id')}`: status `{row.get('status')}`, disposition `{row.get('disposition')}`, present `{row.get('present')}`, trusted `{row.get('trusted')}`, blockers `{', '.join(str(item) for item in (row.get('blocker_ids', []) or [])) or 'none'}`"
            )
    if ic_eda_transcript_refs:
        lines.append("- IC/EDA availability transcript refs:")
        for ref in ic_eda_transcript_refs[:10]:
            path = str(ref.get("path") or "")
            digest = str(ref.get("sha256") or "")
            role = str(ref.get("artifact_role") or "raw_command_transcript_only_not_kernel_ppa")
            lines.append(
                f"  - `{path}` sha256 `{digest}` role `{role}`; availability-only, not kernel PPA."
            )
        if len(ic_eda_transcript_refs) > 10:
            lines.append(f"  - ... `{len(ic_eda_transcript_refs) - 10}` additional transcript refs omitted")
    if not dft_ledger.get("present"):
        lines.append("- No DFT evidence ledger artifacts were indexed for this Step5 run.")

    dft_trial_ledger = report.get("dft_trial_state_ledger", {})
    dft_trial_ledger = dft_trial_ledger if isinstance(dft_trial_ledger, Mapping) else {}
    validation = (
        dft_trial_ledger.get("validation", {})
        if isinstance(dft_trial_ledger.get("validation", {}), Mapping)
        else {}
    )
    transition_report = (
        dft_trial_ledger.get("transition_report", {})
        if isinstance(dft_trial_ledger.get("transition_report", {}), Mapping)
        else {}
    )
    artifact_refs_report = (
        dft_trial_ledger.get("artifact_refs_report", {})
        if isinstance(dft_trial_ledger.get("artifact_refs_report", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Trial State Ledger",
        f"- Present: `{dft_trial_ledger.get('present')}`",
        f"- Status: `{dft_trial_ledger.get('status')}`",
        f"- Campaign/workload: `{dft_trial_ledger.get('campaign_id')}` / `{dft_trial_ledger.get('workload_run_id')}`",
        f"- Candidate count: `{dft_trial_ledger.get('candidate_count')}`",
        f"- Blocked/rejected/selected trials: `{dft_trial_ledger.get('blocked_trial_count')}` / `{dft_trial_ledger.get('rejected_trial_count')}` / `{dft_trial_ledger.get('selected_trial_count')}`",
        f"- Validation valid: `{validation.get('valid')}`",
        f"- Transition report rows: `{transition_report.get('transition_row_count')}`",
        f"- Artifact refs campaign/trial: `{artifact_refs_report.get('campaign_artifact_ref_count')}` / `{artifact_refs_report.get('trial_artifact_ref_count')}`",
        f"- Completion eligible: `{dft_trial_ledger.get('completion_eligible')}`",
        f"- Deliverable complete: `{dft_trial_ledger.get('deliverable_complete')}`",
        "- Boundary: trial state is orchestration/audit provenance only; it cannot upgrade Step4 trust, numerical correctness, trusted Pareto, or FPGA/ASIC PPA claims.",
    ])
    if not dft_trial_ledger.get("present"):
        lines.append("- No DFT trial-state ledger was indexed for this Step5 run.")

    dft_binding = report.get("dft_candidate_binding_map", {})
    dft_binding = dft_binding if isinstance(dft_binding, Mapping) else {}
    binding_validation = (
        dft_binding.get("validation", {})
        if isinstance(dft_binding.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Candidate Binding Map",
        f"- Present: `{dft_binding.get('present')}`",
        f"- Status: `{dft_binding.get('status')}`",
        f"- Workload/release: `{dft_binding.get('workload_suite_id')}` / `{dft_binding.get('release_id')}`",
        f"- Search/bound/unmatched candidates: `{dft_binding.get('search_candidate_count')}` / `{dft_binding.get('bound_candidate_count')}` / `{dft_binding.get('unmatched_candidate_count')}`",
        f"- Unique release candidates: `{dft_binding.get('unique_release_candidate_count')}`",
        f"- Duplicate release IDs: `{', '.join(str(item) for item in (dft_binding.get('duplicate_release_candidate_ids', []) or [])) or 'none'}`",
        f"- Validation valid: `{binding_validation.get('valid')}`",
        f"- Completion eligible: `{dft_binding.get('completion_eligible')}`",
        f"- Deliverable complete: `{dft_binding.get('deliverable_complete')}`",
        "- Boundary: binding maps are heuristic ID provenance only; they cannot upgrade Step4 trust, numerical correctness, trusted Pareto, or FPGA/ASIC PPA claims.",
    ])
    if not dft_binding.get("present"):
        lines.append("- No DFT candidate binding map was indexed for this Step5 run.")

    dft_workplan = report.get("dft_hardware_completion_workplan", {})
    dft_workplan = dft_workplan if isinstance(dft_workplan, Mapping) else {}
    workplan_validation = (
        dft_workplan.get("validation", {})
        if isinstance(dft_workplan.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Completion Workplan",
        f"- Present: `{dft_workplan.get('present')}`",
        f"- Status: `{dft_workplan.get('status')}`",
        f"- Release/candidates/kernels: `{dft_workplan.get('release_id')}` / `{dft_workplan.get('candidate_count')}` / `{dft_workplan.get('major_kernel_count')}`",
        f"- Required/blocked work items: `{dft_workplan.get('required_work_item_count')}` / `{dft_workplan.get('blocked_work_item_count')}`",
        f"- Candidate-specific evidence rows present: `{dft_workplan.get('candidate_specific_evidence_present_count')}`",
        f"- Shared smoke stages observed: `{dft_workplan.get('shared_microkernel_smoke_stage_present_count')}`",
        f"- Validation valid: `{workplan_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_workplan.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_workplan.get('deliverable_complete')}`",
        "- Boundary: workplans schedule candidate-specific Vivado/DC/kernel closure work; they cannot upgrade Step4 trust, numerical correctness, trusted Pareto, or FPGA/ASIC PPA claims.",
    ])
    if not dft_workplan.get("present"):
        lines.append("- No DFT hardware completion workplan was indexed for this Step5 run.")

    dft_shards = report.get("dft_hardware_closure_shards", {})
    dft_shards = dft_shards if isinstance(dft_shards, Mapping) else {}
    shard_validation = (
        dft_shards.get("validation", {})
        if isinstance(dft_shards.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Closure Shards",
        f"- Present: `{dft_shards.get('present')}`",
        f"- Status: `{dft_shards.get('status')}`",
        f"- Release/candidates/kernels: `{dft_shards.get('release_id')}` / `{dft_shards.get('candidate_count')}` / `{dft_shards.get('major_kernel_count')}`",
        f"- Units/shards: `{dft_shards.get('unit_count')}` / `{dft_shards.get('shard_count')}`",
        f"- Work items blocked: `{dft_shards.get('blocked_work_item_count')}` / `{dft_shards.get('work_item_count')}`",
        f"- Candidate-specific bundles/evidence: `{dft_shards.get('candidate_specific_bundle_count')}` / `{dft_shards.get('candidate_specific_evidence_present_count')}`",
        f"- Validation valid: `{shard_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_shards.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_shards.get('deliverable_complete')}`",
        "- Boundary: shard queues assign closure work; they cannot upgrade Step4 trust, numerical correctness, trusted Pareto, or FPGA/ASIC PPA claims.",
    ])
    if not dft_shards.get("present"):
        lines.append("- No DFT hardware closure shard queue was indexed for this Step5 run.")

    dft_packets = report.get("dft_hardware_closure_packets", {})
    dft_packets = dft_packets if isinstance(dft_packets, Mapping) else {}
    packet_validation = (
        dft_packets.get("validation", {})
        if isinstance(dft_packets.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Closure Packets",
        f"- Present: `{dft_packets.get('present')}`",
        f"- Status: `{dft_packets.get('status')}`",
        f"- Release/candidates/kernels: `{dft_packets.get('release_id')}` / `{dft_packets.get('candidate_count')}` / `{dft_packets.get('major_kernel_count')}`",
        f"- Shards/packets/units: `{dft_packets.get('shard_count')}` / `{dft_packets.get('packet_count')}` / `{dft_packets.get('unit_count')}`",
        f"- Work items blocked: `{dft_packets.get('blocked_work_item_count')}` / `{dft_packets.get('work_item_count')}`",
        f"- Expected candidate-specific evidence files: `{dft_packets.get('expected_evidence_file_count')}`",
        f"- Command templates: `{', '.join(str(item) for item in (dft_packets.get('command_template_ids', []) or [])) or 'none'}`",
        f"- Packet/runbook refs: `{len(dft_packets.get('packet_artifact_refs', []) or [])}`",
        f"- Candidate-specific bundles/evidence: `{dft_packets.get('candidate_specific_bundle_count')}` / `{dft_packets.get('candidate_specific_evidence_present_count')}`",
        f"- Validation valid: `{packet_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_packets.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_packets.get('deliverable_complete')}`",
        "- Boundary: closure packets/runbooks give exact execution instructions and expected filenames; they cannot upgrade Step4 trust, numerical correctness, trusted Pareto, or FPGA/ASIC PPA claims.",
    ])
    if not dft_packets.get("present"):
        lines.append("- No DFT hardware closure packet index was indexed for this Step5 run.")

    dft_bundles = report.get("dft_hardware_closure_candidate_bundles", {})
    dft_bundles = dft_bundles if isinstance(dft_bundles, Mapping) else {}
    bundle_validation = (
        dft_bundles.get("validation", {})
        if isinstance(dft_bundles.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Closure Candidate Bundles",
        f"- Present: `{dft_bundles.get('present')}`",
        f"- Status: `{dft_bundles.get('status')}`",
        f"- Release/candidates/kernels: `{dft_bundles.get('release_id')}` / `{dft_bundles.get('candidate_count')}` / `{dft_bundles.get('major_kernel_count')}`",
        f"- Bundle refs/templates: `{dft_bundles.get('bundle_ref_count')}` / `{dft_bundles.get('bundle_count')}`",
        f"- Expected/raw evidence files: `{dft_bundles.get('expected_evidence_file_count')}` / `{dft_bundles.get('raw_evidence_file_count')}`",
        f"- Bundle template only: `{dft_bundles.get('bundle_template_only')}`",
        f"- Validation valid: `{bundle_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_bundles.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_bundles.get('deliverable_complete')}`",
        "- Boundary: candidate bundles are expected-file/source placement contracts only; they cannot adjudicate or upgrade golden, RTL/HLS, Vivado, DC, PPA, trusted Pareto, or completion claims.",
    ])
    if not dft_bundles.get("present"):
        lines.append("- No DFT hardware closure candidate-bundle index was indexed for this Step5 run.")

    dft_unit_provenance = report.get("dft_hardware_closure_unit_provenance", {})
    dft_unit_provenance = dft_unit_provenance if isinstance(dft_unit_provenance, Mapping) else {}
    unit_provenance_validation = (
        dft_unit_provenance.get("validation", {})
        if isinstance(dft_unit_provenance.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Closure Unit Provenance",
        f"- Present: `{dft_unit_provenance.get('present')}`",
        f"- Status: `{dft_unit_provenance.get('status')}`",
        f"- Release/candidates/kernels: `{dft_unit_provenance.get('release_id')}` / `{dft_unit_provenance.get('candidate_count')}` / `{dft_unit_provenance.get('major_kernel_count')}`",
        f"- Staged units: `{dft_unit_provenance.get('staged_unit_count')}`",
        f"- Provenance/raw stage files: `{dft_unit_provenance.get('global_provenance_file_count')}` / `{dft_unit_provenance.get('raw_stage_evidence_file_count')}`",
        f"- Unit refs indexed: `{dft_unit_provenance.get('unit_ref_count')}`",
        f"- Validation valid: `{unit_provenance_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_unit_provenance.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_unit_provenance.get('deliverable_complete')}`",
        "- Boundary: unit provenance stages candidate/kernel metadata only; it contains no raw VCS/HLS/Vivado/DC logs, parsed results, PPA, trusted Pareto, or completion evidence.",
    ])
    if not dft_unit_provenance.get("present"):
        lines.append("- No DFT hardware closure unit-provenance index was indexed for this Step5 run.")

    dft_artifact_chain = report.get("dft_hardware_closure_artifact_chain", {})
    dft_artifact_chain = dft_artifact_chain if isinstance(dft_artifact_chain, Mapping) else {}
    lines.extend([
        "",
        "## DFT Hardware Closure Artifact Chain",
        f"- Present: `{dft_artifact_chain.get('present')}`",
        f"- Status: `{dft_artifact_chain.get('status')}`",
        f"- Chain linked: `{dft_artifact_chain.get('chain_linked')}`",
        f"- Stage order: `{', '.join(str(item) for item in (dft_artifact_chain.get('stage_order', []) or [])) or 'none'}`",
        f"- Validation valid: `{dft_artifact_chain.get('validation_valid')}`",
        "- Boundary: the artifact chain reports linked provenance only; it cannot upgrade Step4 trust, numerical correctness, trusted Pareto, or completion claims.",
    ])
    if not dft_artifact_chain.get("present"):
        lines.append("- No DFT hardware closure artifact chain was indexed for this Step5 run.")

    dft_source_flow_plan = report.get("dft_hardware_closure_source_flow_plan", {})
    dft_source_flow_plan = dft_source_flow_plan if isinstance(dft_source_flow_plan, Mapping) else {}
    source_flow_plan_validation = (
        dft_source_flow_plan.get("validation", {})
        if isinstance(dft_source_flow_plan.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Closure Source Flow Plan",
        f"- Present: `{dft_source_flow_plan.get('present')}`",
        f"- Status: `{dft_source_flow_plan.get('status')}`",
        f"- Release/candidates/kernels: `{dft_source_flow_plan.get('release_id')}` / `{dft_source_flow_plan.get('candidate_count')}` / `{dft_source_flow_plan.get('major_kernel_count')}`",
        f"- Planned units: `{dft_source_flow_plan.get('planned_unit_count')}`",
        f"- Materialization-eligible units: `{dft_source_flow_plan.get('materialization_eligible_unit_count')}`",
        f"- Source-flow present/missing/blocked units: `{dft_source_flow_plan.get('source_flow_present_count')}` / `{dft_source_flow_plan.get('source_flow_missing_count')}` / `{dft_source_flow_plan.get('blocked_unit_count')}`",
        f"- Source-flow map: `{(dft_source_flow_plan.get('source_flow_map') or {}).get('path')}` (exists: `{(dft_source_flow_plan.get('source_flow_map') or {}).get('exists')}`)",
        f"- Source-flow plan errors: `{dft_source_flow_plan.get('error_count')}`",
        f"- Source-flow blocker ids: `{dft_source_flow_plan.get('blocker_id_counts')}`",
        f"- Wrong-candidate/wrong-kernel/reused-source blockers: `{dft_source_flow_plan.get('blocked_wrong_candidate_reuse_count')}` / `{dft_source_flow_plan.get('blocked_wrong_kernel_reuse_count')}` / `{dft_source_flow_plan.get('blocked_reused_source_flow_count')}`",
        f"- Invalid manifest/provenance mismatch counts: `{dft_source_flow_plan.get('blocked_invalid_manifest_count')}` / `{dft_source_flow_plan.get('provenance_mismatch_count')}`",
        f"- Adjudication result: `{dft_source_flow_plan.get('adjudication_result')}`",
        f"- Passed stage count: `{dft_source_flow_plan.get('passed_stage_count')}`",
        f"- Validation valid: `{source_flow_plan_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_source_flow_plan.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_source_flow_plan.get('deliverable_complete')}`",
        "- Boundary: source-flow planning validates candidate/kernel provenance before materialization only; it does not copy raw files, parse results, adjudicate gates, certify PPA, or complete the release.",
    ])
    if not dft_source_flow_plan.get("present"):
        lines.append("- No DFT hardware closure source-flow plan artifact was indexed for this Step5 run.")

    dft_raw_materialization = report.get("dft_hardware_closure_raw_stage_materialization", {})
    dft_raw_materialization = dft_raw_materialization if isinstance(dft_raw_materialization, Mapping) else {}
    raw_materialization_validation = (
        dft_raw_materialization.get("validation", {})
        if isinstance(dft_raw_materialization.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Closure Raw Stage Materialization",
        f"- Present: `{dft_raw_materialization.get('present')}`",
        f"- Status: `{dft_raw_materialization.get('status')}`",
        f"- Release/candidates/kernels: `{dft_raw_materialization.get('release_id')}` / `{dft_raw_materialization.get('candidate_count')}` / `{dft_raw_materialization.get('major_kernel_count')}`",
        f"- Units materialized/total/blocked: `{dft_raw_materialization.get('materialized_unit_count')}` / `{dft_raw_materialization.get('unit_count')}` / `{dft_raw_materialization.get('blocked_unit_count')}`",
        f"- Materialized raw files: `{dft_raw_materialization.get('materialized_file_count')}`",
        f"- Missing required raw-stage files: `{dft_raw_materialization.get('missing_required_raw_stage_file_count')}`",
        f"- Materialization blocker ids: `{dft_raw_materialization.get('materialization_blocker_ids')}`",
        f"- Adjudication result: `{dft_raw_materialization.get('adjudication_result')}`",
        f"- Passed stage count: `{dft_raw_materialization.get('passed_stage_count')}`",
        f"- Validation valid: `{raw_materialization_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_raw_materialization.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_raw_materialization.get('deliverable_complete')}`",
        "- Boundary: raw-stage materialization copies/wraps existing source-flow outputs only; registration, parser, adjudication, release completion, and PPA claims remain separate.",
    ])
    if not dft_raw_materialization.get("present"):
        lines.append("- No DFT hardware closure raw-stage materialization artifact was indexed for this Step5 run.")

    dft_raw_registration = report.get("dft_hardware_closure_raw_transcript_registration", {})
    dft_raw_registration = dft_raw_registration if isinstance(dft_raw_registration, Mapping) else {}
    raw_registration_validation = (
        dft_raw_registration.get("validation", {})
        if isinstance(dft_raw_registration.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Closure Raw Transcript Registration",
        f"- Present: `{dft_raw_registration.get('present')}`",
        f"- Status: `{dft_raw_registration.get('status')}`",
        f"- Release/candidates/kernels: `{dft_raw_registration.get('release_id')}` / `{dft_raw_registration.get('candidate_count')}` / `{dft_raw_registration.get('major_kernel_count')}`",
        f"- Units registered/total/blocked: `{dft_raw_registration.get('registered_unit_count')}` / `{dft_raw_registration.get('unit_count')}` / `{dft_raw_registration.get('blocked_unit_count')}`",
        f"- Raw refs registered/present/missing/invalid: `{dft_raw_registration.get('registered_raw_stage_evidence_file_count')}` / `{dft_raw_registration.get('present_raw_stage_evidence_file_count')}` / `{dft_raw_registration.get('missing_raw_stage_evidence_file_count')}` / `{dft_raw_registration.get('invalid_raw_stage_evidence_file_count')}`",
        f"- Adjudication result: `{dft_raw_registration.get('adjudication_result')}`",
        f"- Passed stage count: `{dft_raw_registration.get('passed_stage_count')}`",
        f"- Validation valid: `{raw_registration_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_raw_registration.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_raw_registration.get('deliverable_complete')}`",
        "- Boundary: raw-transcript registration hashes and indexes already-present candidate-specific raw files only; parser and hard-gate adjudication remain separate.",
    ])
    if not dft_raw_registration.get("present"):
        lines.append("- No DFT hardware closure raw-transcript registration artifact was indexed for this Step5 run.")

    dft_intake = report.get("dft_hardware_closure_evidence_intake", {})
    dft_intake = dft_intake if isinstance(dft_intake, Mapping) else {}
    intake_validation = (
        dft_intake.get("validation", {})
        if isinstance(dft_intake.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Closure Evidence Intake",
        f"- Present: `{dft_intake.get('present')}`",
        f"- Status: `{dft_intake.get('status')}`",
        f"- Release/candidates/kernels: `{dft_intake.get('release_id')}` / `{dft_intake.get('candidate_count')}` / `{dft_intake.get('major_kernel_count')}`",
        f"- Packets/units: `{dft_intake.get('packet_count')}` / `{dft_intake.get('unit_count')}`",
        f"- Evidence files present/missing/expected: `{dft_intake.get('present_evidence_file_count')}` / `{dft_intake.get('missing_evidence_file_count')}` / `{dft_intake.get('expected_evidence_file_count')}`",
        f"- Candidate bundles present: `{dft_intake.get('candidate_bundle_count')}`",
        f"- Adjudication status: `{dft_intake.get('adjudication_status')}`",
        f"- Validation valid: `{intake_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_intake.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_intake.get('deliverable_complete')}`",
        "- Boundary: evidence intake checks candidate-specific file presence only; it cannot adjudicate or upgrade correctness, FPGA/ASIC PPA, trusted Pareto, or completion claims.",
    ])
    if not dft_intake.get("present"):
        lines.append("- No DFT hardware closure evidence intake was indexed for this Step5 run.")

    dft_adjudication = report.get("dft_hardware_closure_adjudication", {})
    dft_adjudication = dft_adjudication if isinstance(dft_adjudication, Mapping) else {}
    adjudication_validation = (
        dft_adjudication.get("validation", {})
        if isinstance(dft_adjudication.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Closure Adjudication",
        f"- Present: `{dft_adjudication.get('present')}`",
        f"- Status: `{dft_adjudication.get('status')}`",
        f"- Release/candidates/kernels: `{dft_adjudication.get('release_id')}` / `{dft_adjudication.get('candidate_count')}` / `{dft_adjudication.get('major_kernel_count')}`",
        f"- Packets/units/stages: `{dft_adjudication.get('packet_count')}` / `{dft_adjudication.get('unit_count')}` / `{dft_adjudication.get('stage_count')}`",
        f"- Stages passed/blocked/files-present-unadjudicated: `{dft_adjudication.get('passed_stage_count')}` / `{dft_adjudication.get('blocked_stage_count')}` / `{dft_adjudication.get('files_present_unadjudicated_stage_count')}`",
        f"- Evidence files present/missing/expected: `{dft_adjudication.get('present_evidence_file_count')}` / `{dft_adjudication.get('missing_evidence_file_count')}` / `{dft_adjudication.get('expected_evidence_file_count')}`",
        f"- Candidate bundles present: `{dft_adjudication.get('candidate_bundle_count')}`",
        f"- Adjudication result: `{dft_adjudication.get('adjudication_result')}`",
        f"- Validation valid: `{adjudication_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_adjudication.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_adjudication.get('deliverable_complete')}`",
        "- Boundary: closure adjudication is a fail-closed stage ledger; it cannot pass golden/sim/synth/Vivado/DC gates without parsed candidate-specific evidence.",
    ])
    if not dft_adjudication.get("present"):
        lines.append("- No DFT hardware closure adjudication ledger was indexed for this Step5 run.")

    dft_parsed = report.get("dft_hardware_closure_parsed_evidence", {})
    dft_parsed = dft_parsed if isinstance(dft_parsed, Mapping) else {}
    parsed_validation = (
        dft_parsed.get("validation", {})
        if isinstance(dft_parsed.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Closure Parsed Evidence",
        f"- Present: `{dft_parsed.get('present')}`",
        f"- Status: `{dft_parsed.get('status')}`",
        f"- Release/candidates/kernels: `{dft_parsed.get('release_id')}` / `{dft_parsed.get('candidate_count')}` / `{dft_parsed.get('major_kernel_count')}`",
        f"- Packets/units/stages: `{dft_parsed.get('packet_count')}` / `{dft_parsed.get('unit_count')}` / `{dft_parsed.get('stage_count')}`",
        f"- Parsed results present/missing/expected: `{dft_parsed.get('present_parsed_result_count')}` / `{dft_parsed.get('missing_parsed_result_count')}` / `{dft_parsed.get('expected_parsed_result_count')}`",
        f"- Parsed results valid/invalid: `{dft_parsed.get('valid_parsed_result_count')}` / `{dft_parsed.get('invalid_parsed_result_count')}`",
        f"- Parsed verdict counts: `{dft_parsed.get('parsed_verdict_counts')}`",
        f"- Adjudication result: `{dft_parsed.get('adjudication_result')}`",
        f"- Passed stage count: `{dft_parsed.get('passed_stage_count')}`",
        f"- Validation valid: `{parsed_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_parsed.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_parsed.get('deliverable_complete')}`",
        "- Boundary: parsed evidence manifests validate parser outputs only; a separate adjudicator must still decide golden/sim/synth/Vivado/DC gates.",
    ])
    if not dft_parsed.get("present"):
        lines.append("- No DFT hardware closure parsed-evidence manifest was indexed for this Step5 run.")

    dft_parser_run = report.get("dft_hardware_closure_parser_run", {})
    dft_parser_run = dft_parser_run if isinstance(dft_parser_run, Mapping) else {}
    parser_run_validation = (
        dft_parser_run.get("validation", {})
        if isinstance(dft_parser_run.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Closure Parser Run",
        f"- Present: `{dft_parser_run.get('present')}`",
        f"- Status: `{dft_parser_run.get('status')}`",
        f"- Release/candidates/kernels: `{dft_parser_run.get('release_id')}` / `{dft_parser_run.get('candidate_count')}` / `{dft_parser_run.get('major_kernel_count')}`",
        f"- Packets/units/stages: `{dft_parser_run.get('packet_count')}` / `{dft_parser_run.get('unit_count')}` / `{dft_parser_run.get('stage_count')}`",
        f"- Parsed results written: `{dft_parser_run.get('parsed_result_written_count')}`",
        f"- Blocked stage count: `{dft_parser_run.get('blocked_stage_count')}`",
        f"- Parsed verdict counts: `{dft_parser_run.get('verdict_counts')}`",
        f"- Parser status counts: `{dft_parser_run.get('parser_status_counts')}`",
        f"- Stage blocker ids: `{dft_parser_run.get('stage_blocker_ids')}`",
        f"- DC target-library discovery counts: `{dft_parser_run.get('dc_target_library_discovery_counts')}`",
        f"- DC target libraries: `{dft_parser_run.get('dc_target_libraries')}`",
        f"- Adjudication result: `{dft_parser_run.get('adjudication_result')}`",
        f"- Passed stage count: `{dft_parser_run.get('passed_stage_count')}`",
        f"- Validation valid: `{parser_run_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_parser_run.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_parser_run.get('deliverable_complete')}`",
        "- Boundary: parser runs materialize parser-output files only from existing candidate-specific raw evidence; a separate adjudicator must still decide every golden/sim/synth/Vivado/DC gate.",
    ])
    if not dft_parser_run.get("present"):
        lines.append("- No DFT hardware closure parser-run artifact was indexed for this Step5 run.")

    dft_gate_adj = report.get("dft_hardware_closure_gate_adjudication", {})
    dft_gate_adj = dft_gate_adj if isinstance(dft_gate_adj, Mapping) else {}
    gate_adj_validation = (
        dft_gate_adj.get("validation", {})
        if isinstance(dft_gate_adj.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Closure Gate Adjudication",
        f"- Present: `{dft_gate_adj.get('present')}`",
        f"- Status: `{dft_gate_adj.get('status')}`",
        f"- Release/candidates/kernels: `{dft_gate_adj.get('release_id')}` / `{dft_gate_adj.get('candidate_count')}` / `{dft_gate_adj.get('major_kernel_count')}`",
        f"- Packets/units/stages: `{dft_gate_adj.get('packet_count')}` / `{dft_gate_adj.get('unit_count')}` / `{dft_gate_adj.get('stage_count')}`",
        f"- Stage gates passed/blocked/failed: `{dft_gate_adj.get('stage_gate_passed_count')}` / `{dft_gate_adj.get('blocked_stage_count')}` / `{dft_gate_adj.get('failed_stage_count')}`",
        f"- Unit gates passed/blocked/failed: `{dft_gate_adj.get('unit_gate_passed_count')}` / `{dft_gate_adj.get('blocked_unit_count')}` / `{dft_gate_adj.get('failed_unit_count')}`",
        f"- Adjudication result: `{dft_gate_adj.get('adjudication_result')}`",
        f"- Validation valid: `{gate_adj_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_gate_adj.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_gate_adj.get('deliverable_complete')}`",
        "- Boundary: gate adjudication may record per-stage parsed-evidence verdicts, but release completion/trusted Pareto/FPGA/ASIC PPA require later all-unit claim closure.",
    ])
    if not dft_gate_adj.get("present"):
        lines.append("- No DFT hardware closure gate-adjudication artifact was indexed for this Step5 run.")

    dft_release_gate = report.get("dft_hardware_closure_release_gate", {})
    dft_release_gate = dft_release_gate if isinstance(dft_release_gate, Mapping) else {}
    release_gate_validation = (
        dft_release_gate.get("validation", {})
        if isinstance(dft_release_gate.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Closure Release Gate",
        f"- Present: `{dft_release_gate.get('present')}`",
        f"- Status: `{dft_release_gate.get('status')}`",
        f"- Release/candidates/kernels: `{dft_release_gate.get('release_id')}` / `{dft_release_gate.get('candidate_count')}` / `{dft_release_gate.get('major_kernel_count')}`",
        f"- Units/stages: `{dft_release_gate.get('unit_count')}` / `{dft_release_gate.get('stage_count')}`",
        f"- Stage gates passed/blocked/failed: `{dft_release_gate.get('stage_gate_passed_count')}` / `{dft_release_gate.get('blocked_stage_count')}` / `{dft_release_gate.get('failed_stage_count')}`",
        f"- Unit gates passed/blocked/failed: `{dft_release_gate.get('unit_gate_passed_count')}` / `{dft_release_gate.get('blocked_unit_count')}` / `{dft_release_gate.get('failed_unit_count')}`",
        f"- Candidate gates passed/blocked/failed: `{dft_release_gate.get('candidate_gate_passed_count')}` / `{dft_release_gate.get('blocked_candidate_count')}` / `{dft_release_gate.get('failed_candidate_count')}`",
        f"- Release gate result: `{dft_release_gate.get('release_gate_result')}`",
        f"- Validation valid: `{release_gate_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_release_gate.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_release_gate.get('deliverable_complete')}`",
        "- Boundary: release-gate rollup can make hardware completion eligibility auditable after all unit gates pass, but final deliverable completion remains a separate goal/release claim.",
    ])
    if not dft_release_gate.get("present"):
        lines.append("- No DFT hardware closure release-gate artifact was indexed for this Step5 run.")

    dft_ppa = report.get("dft_hardware_ppa_ranking", {})
    dft_ppa = dft_ppa if isinstance(dft_ppa, Mapping) else {}
    ppa_validation = (
        dft_ppa.get("validation", {})
        if isinstance(dft_ppa.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware PPA Ranking",
        f"- Present: `{dft_ppa.get('present')}`",
        f"- Status: `{dft_ppa.get('status')}`",
        f"- Release/candidates/kernels: `{dft_ppa.get('release_id')}` / `{dft_ppa.get('candidate_count')}` / `{dft_ppa.get('major_kernel_count')}`",
        f"- Ranking-eligible candidates: `{dft_ppa.get('ranking_eligible_candidate_count')}`",
        f"- Pareto candidates: `{dft_ppa.get('pareto_candidate_count')}`",
        f"- Winner selection status: `{dft_ppa.get('winner_selection_status')}`",
        f"- All candidates metric-tied: `{dft_ppa.get('all_candidates_metric_tied')}`",
        f"- FPGA top candidate ids: `{', '.join(dft_ppa.get('fpga_top_candidate_ids', []) or []) or 'none'}`",
        f"- ASIC top candidate ids: `{', '.join(dft_ppa.get('asic_top_candidate_ids', []) or []) or 'none'}`",
        f"- FPGA target-model binding rows: `{len(dft_ppa.get('fpga_target_model_binding_rows', []) or [])}`",
        f"- ASIC target-model binding rows: `{len(dft_ppa.get('asic_target_model_binding_rows', []) or [])}`",
        f"- Validation valid: `{ppa_validation.get('valid')}`",
        f"- Hardware completion eligible: `{dft_ppa.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{dft_ppa.get('deliverable_complete')}`",
        "- Boundary: hardware PPA ranking is candidate-stamped major-kernel evidence only; it is not a full-SCF deliverable-completion or single-winner claim.",
    ])
    if not dft_ppa.get("present"):
        lines.append("- No DFT hardware PPA ranking artifact was indexed for this Step5 run.")

    dft_ppa_prov = report.get("dft_candidate_specific_ppa_provenance", {})
    dft_ppa_prov = dft_ppa_prov if isinstance(dft_ppa_prov, Mapping) else {}
    ppa_prov_validation = (
        dft_ppa_prov.get("validation", {})
        if isinstance(dft_ppa_prov.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Candidate-Specific PPA Provenance",
        f"- Present: `{dft_ppa_prov.get('present')}`",
        f"- Status: `{dft_ppa_prov.get('status')}`",
        f"- Winner provenance eligible: `{dft_ppa_prov.get('winner_provenance_eligible')}`",
        f"- Units trusted/blocked: `{dft_ppa_prov.get('trusted_unit_count')}` / `{dft_ppa_prov.get('blocked_unit_count')}`",
        f"- Stages trusted/blocked: `{dft_ppa_prov.get('trusted_stage_count')}` / `{dft_ppa_prov.get('blocked_stage_count')}`",
        f"- Blocker count: `{dft_ppa_prov.get('blocker_count')}`",
        f"- Tie-breaker queue items: `{dft_ppa_prov.get('tie_breaker_work_item_count')}`",
        f"- Fresh execution present/status: `{dft_ppa_prov.get('fresh_execution_present')}` / `{dft_ppa_prov.get('fresh_execution_status')}`",
        f"- Fresh execution units selected/executed/blocked: `{dft_ppa_prov.get('fresh_execution_selected_unit_count')}` / `{dft_ppa_prov.get('fresh_execution_executed_unit_count')}` / `{dft_ppa_prov.get('fresh_execution_blocked_unit_count')}`",
        f"- Fresh execution raw files materialized: `{dft_ppa_prov.get('fresh_execution_materialized_raw_file_count')}`",
        f"- Validation valid: `{ppa_prov_validation.get('valid')}`",
        "- Boundary: fresh command/tool provenance is required before parsed PPA files can support best FPGA/ASIC architecture proof; this section does not run tools or mark completion.",
    ])
    if not dft_ppa_prov.get("present"):
        lines.append("- No DFT candidate-specific PPA provenance audit was indexed for this Step5 run.")

    dft_winner = report.get("dft_architecture_winner_resolution", {})
    dft_winner = dft_winner if isinstance(dft_winner, Mapping) else {}
    winner_validation = (
        dft_winner.get("validation", {})
        if isinstance(dft_winner.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Architecture Winner Resolution",
        f"- Present: `{dft_winner.get('present')}`",
        f"- Status: `{dft_winner.get('status')}`",
        f"- Hardware winner resolution eligible: `{dft_winner.get('hardware_winner_resolution_eligible')}`",
        f"- FPGA status/top-count: `{dft_winner.get('fpga_status')}` / `{dft_winner.get('fpga_top_rank_candidate_count')}`",
        f"- ASIC status/top-count: `{dft_winner.get('asic_status')}` / `{dft_winner.get('asic_top_rank_candidate_count')}`",
        f"- All candidates metric-tied: `{dft_winner.get('all_candidates_metric_tied')}`",
        f"- Validation valid: `{winner_validation.get('valid')}`",
        f"- Deliverable complete: `{dft_winner.get('deliverable_complete')}`",
        "- Boundary: candidate-id tie order, Step2 design score, shared route-probe evidence, or a single-candidate full-SCF bundle cannot become a best FPGA/ASIC architecture proof.",
    ])
    if not dft_winner.get("present"):
        lines.append("- No DFT architecture winner-resolution artifact was indexed for this Step5 run.")

    readiness = report.get("dft_hardware_deployment_recommendation_readiness", {})
    readiness = readiness if isinstance(readiness, Mapping) else {}
    readiness_validation = (
        readiness.get("validation", {})
        if isinstance(readiness.get("validation", {}), Mapping)
        else {}
    )
    readiness_deployments = (
        readiness.get("deployments", {})
        if isinstance(readiness.get("deployments", {}), Mapping)
        else {}
    )
    readiness_fpga = (
        readiness_deployments.get("fpga", {})
        if isinstance(readiness_deployments.get("fpga", {}), Mapping)
        else {}
    )
    readiness_asic = (
        readiness_deployments.get("asic", {})
        if isinstance(readiness_deployments.get("asic", {}), Mapping)
        else {}
    )
    readiness_next_counts = (
        readiness.get("required_next_evidence_counts", {})
        if isinstance(readiness.get("required_next_evidence_counts", {}), Mapping)
        else {}
    )
    readiness_final_next_counts = (
        readiness.get("final_recommendation_required_next_evidence_counts", {})
        if isinstance(readiness.get("final_recommendation_required_next_evidence_counts", {}), Mapping)
        else {}
    )
    readiness_fpga_target_selection = (
        readiness.get("fpga_target_selection", {})
        if isinstance(readiness.get("fpga_target_selection", {}), Mapping)
        else {}
    )
    readiness_asic_target_selection = (
        readiness.get("asic_target_selection", {})
        if isinstance(readiness.get("asic_target_selection", {}), Mapping)
        else {}
    )
    readiness_fpga_selected_target = (
        readiness_fpga_target_selection.get("selected_target", {})
        if isinstance(readiness_fpga_target_selection.get("selected_target", {}), Mapping)
        else {}
    )
    readiness_asic_selected_target = (
        readiness_asic_target_selection.get("selected_target", {})
        if isinstance(readiness_asic_target_selection.get("selected_target", {}), Mapping)
        else {}
    )
    readiness_target_trust_gate_summary = (
        readiness.get("deployment_target_selection_trust_gate_summary", {})
        if isinstance(readiness.get("deployment_target_selection_trust_gate_summary", {}), Mapping)
        else {}
    )
    readiness_input_trust_gates = (
        readiness.get("target_selection_input_trust_gates", {})
        if isinstance(readiness.get("target_selection_input_trust_gates", {}), Mapping)
        else {}
    )
    readiness_fpga_input_trust_gate = (
        readiness_input_trust_gates.get("fpga", {})
        if isinstance(readiness_input_trust_gates.get("fpga", {}), Mapping)
        else {}
    )
    readiness_asic_input_trust_gate = (
        readiness_input_trust_gates.get("asic", {})
        if isinstance(readiness_input_trust_gates.get("asic", {}), Mapping)
        else {}
    )
    readiness_full_scf_gate = (
        readiness.get("full_scf_numerical_gate", {})
        if isinstance(readiness.get("full_scf_numerical_gate", {}), Mapping)
        else {}
    )
    readiness_full_scf_workplan = (
        readiness.get("full_scf_numerical_closure_workplan", {})
        if isinstance(readiness.get("full_scf_numerical_closure_workplan", {}), Mapping)
        else {}
    )
    readiness_full_scf_qe_requirements = (
        readiness.get("full_scf_qe_accelerated_numeric_requirements", {})
        if isinstance(readiness.get("full_scf_qe_accelerated_numeric_requirements", {}), Mapping)
        else {}
    )
    readiness_full_scf_qe_baselines = (
        readiness.get("full_scf_qe_baseline_materialization", {})
        if isinstance(readiness.get("full_scf_qe_baseline_materialization", {}), Mapping)
        else {}
    )
    readiness_full_scf_targeted_accounting = (
        readiness.get("full_scf_targeted_deployment_accounting", {})
        if isinstance(readiness.get("full_scf_targeted_deployment_accounting", {}), Mapping)
        else {}
    )
    readiness_full_scf_targeted_fpga = (
        readiness_full_scf_targeted_accounting.get("fpga", {})
        if isinstance(readiness_full_scf_targeted_accounting.get("fpga", {}), Mapping)
        else {}
    )
    readiness_full_scf_targeted_asic = (
        readiness_full_scf_targeted_accounting.get("asic", {})
        if isinstance(readiness_full_scf_targeted_accounting.get("asic", {}), Mapping)
        else {}
    )
    readiness_full_scf_batch_plan = (
        readiness.get("full_scf_trusted_evidence_batch_plan", {})
        if isinstance(readiness.get("full_scf_trusted_evidence_batch_plan", {}), Mapping)
        else {}
    )
    dft_deployment = report.get("dft_deployment_comparator", {})
    dft_deployment = dft_deployment if isinstance(dft_deployment, Mapping) else {}
    deployment_validation = (
        dft_deployment.get("validation", {})
        if isinstance(dft_deployment.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Deployment Recommendation Readiness",
        f"- Present: `{readiness.get('present')}`",
        f"- Status: `{readiness.get('status')}`",
        f"- Validation valid: `{readiness_validation.get('valid')}`",
        f"- Can name hardware-PPA winners: `{readiness.get('can_name_hardware_ppa_winners')}`",
        f"- Deployment target selection ready: `{readiness.get('deployment_target_selection_ready')}`",
        f"- FPGA readiness/status/blockers: `{readiness_fpga.get('can_name_hardware_ppa_winner')}` / `{readiness_fpga.get('status')}` / `{readiness_fpga.get('blocker_count')}`",
        f"- ASIC readiness/status/blockers: `{readiness_asic.get('can_name_hardware_ppa_winner')}` / `{readiness_asic.get('status')}` / `{readiness_asic.get('blocker_count')}`",
        f"- Can name targeted deployment recommendation: `{readiness.get('can_name_targeted_deployment_recommendation')}`",
        f"- Can name final recommendation: `{readiness.get('can_name_final_recommendation')}`",
        f"- Required next-evidence items (FPGA/ASIC): `{readiness_next_counts.get('fpga')}` / `{readiness_next_counts.get('asic')}`",
        f"- Final-recommendation next-evidence items (FPGA/ASIC): `{readiness_final_next_counts.get('fpga')}` / `{readiness_final_next_counts.get('asic')}`",
        f"- FPGA target selection: status `{readiness_fpga_target_selection.get('status')}`, target `{readiness_fpga_selected_target.get('target_device_id')}`, part `{readiness_fpga_selected_target.get('part')}`, vendor `{readiness_fpga_selected_target.get('vendor')}`, source refs `{readiness_fpga_target_selection.get('source_ref_count')}`, blockers `{len(readiness_fpga_target_selection.get('blockers', []) or [])}`",
        f"- ASIC target selection: status `{readiness_asic_target_selection.get('status')}`, library `{readiness_asic_selected_target.get('target_library_id')}`, process `{readiness_asic_selected_target.get('process_node')}`, PVT `{readiness_asic_selected_target.get('pvt_corner')}`, source refs `{readiness_asic_target_selection.get('source_ref_count')}`, blockers `{len(readiness_asic_target_selection.get('blockers', []) or [])}`",
        f"- Target trust gates: present `{readiness_target_trust_gate_summary.get('present')}`, all trusted `{readiness_target_trust_gate_summary.get('all_trusted')}`, trusted gates `{readiness_target_trust_gate_summary.get('trusted_gate_count')}/{readiness_target_trust_gate_summary.get('gate_count')}`, blocked gates `{readiness_target_trust_gate_summary.get('blocked_gate_count')}`",
        f"- FPGA input trust gate: class `{readiness_fpga_input_trust_gate.get('trust_class')}`, trusted `{readiness_fpga_input_trust_gate.get('trusted')}`, blockers `{len(readiness_fpga_input_trust_gate.get('blockers', []) or [])}`",
        f"- ASIC input trust gate: class `{readiness_asic_input_trust_gate.get('trust_class')}`, trusted `{readiness_asic_input_trust_gate.get('trusted')}`, blockers `{len(readiness_asic_input_trust_gate.get('blockers', []) or [])}`",
        f"- Full-SCF numerical gate: present `{readiness_full_scf_gate.get('present')}`, status `{readiness_full_scf_gate.get('status')}`, passed `{readiness_full_scf_gate.get('passed')}`, blocked rows `{readiness_full_scf_gate.get('blocked_row_record_count')}`",
        f"- Full-SCF numerical closure workplan: required `{readiness_full_scf_workplan.get('required')}`, work items `{readiness_full_scf_workplan.get('work_item_count')}`, class rows `{readiness_full_scf_workplan.get('class_row_work_item_count')}`",
        f"- Full-SCF targeted deployment accounting: present `{readiness_full_scf_targeted_accounting.get('present')}`, status `{readiness_full_scf_targeted_accounting.get('status')}`, ready `{readiness_full_scf_targeted_accounting.get('targeted_accounting_ready')}`, full-SCF gate passed `{readiness_full_scf_targeted_accounting.get('full_scf_numerical_gate_passed')}`",
        f"- Full-SCF targeted accounting visibility (FPGA/ASIC): host-retained `{readiness_full_scf_targeted_fpga.get('host_bound_costs_included')}` / `{readiness_full_scf_targeted_asic.get('host_bound_costs_included')}`, runtime-overhead `{readiness_full_scf_targeted_fpga.get('runtime_overheads_included')}` / `{readiness_full_scf_targeted_asic.get('runtime_overheads_included')}`, accelerated-kernel `{readiness_full_scf_targeted_fpga.get('accelerated_kernel_costs_included')}` / `{readiness_full_scf_targeted_asic.get('accelerated_kernel_costs_included')}`",
        f"- Full-SCF QE baseline materialization: present `{readiness_full_scf_qe_baselines.get('present')}`, status `{readiness_full_scf_qe_baselines.get('status')}`, cases `{readiness_full_scf_qe_baselines.get('case_count')}`, passed `{readiness_full_scf_qe_baselines.get('passed_case_count')}`, blocked `{readiness_full_scf_qe_baselines.get('blocked_case_count')}`",
        f"- Full-SCF QE accelerated numeric requirements: present `{readiness_full_scf_qe_requirements.get('present')}`, status `{readiness_full_scf_qe_requirements.get('status')}`, rows `{readiness_full_scf_qe_requirements.get('row_count')}`, ready `{readiness_full_scf_qe_requirements.get('ready_row_count')}`, blocked `{readiness_full_scf_qe_requirements.get('blocked_row_count')}`",
        f"- Full-SCF trusted evidence batch plan: present `{readiness_full_scf_batch_plan.get('present')}`, status `{readiness_full_scf_batch_plan.get('status')}`, planned `{readiness_full_scf_batch_plan.get('planned_work_item_count')}`, ready `{readiness_full_scf_batch_plan.get('ready_to_execute_work_item_count')}`, blocked `{readiness_full_scf_batch_plan.get('blocked_work_item_count')}`, shards `{readiness_full_scf_batch_plan.get('shard_count')}`",
        f"- Readiness upgrade detected: `{readiness.get('readiness_upgrade_detected')}`",
        f"- Deliverable complete: `{readiness.get('deliverable_complete')}`",
        "- Boundary: readiness can unblock scoped hardware-PPA winner naming and aggregate target/accounting planning context only; it never names final deployment recommendations or upgrades final full-SCF deployment claims.",
    ])
    readiness_safety_findings = readiness.get("safety_findings", [])
    if readiness_safety_findings:
        lines.append(
            "- Safety findings: `"
            + ", ".join(str(item) for item in readiness_safety_findings)
            + "`"
        )
    if not readiness.get("present"):
        lines.append("- No DFT deployment recommendation readiness artifact was indexed for this Step5 run.")

    deployment_recs = report.get("deployment_recommendations", {})
    deployment_recs = deployment_recs if isinstance(deployment_recs, Mapping) else {}
    deployment_rec_items = (
        deployment_recs.get("recommendations", {})
        if isinstance(deployment_recs.get("recommendations", {}), Mapping)
        else {}
    )
    fpga_deployment_rec = (
        deployment_rec_items.get("fpga", {})
        if isinstance(deployment_rec_items.get("fpga", {}), Mapping)
        else {}
    )
    asic_deployment_rec = (
        deployment_rec_items.get("asic", {})
        if isinstance(deployment_rec_items.get("asic", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Deployment Comparator",
        f"- Present: `{dft_deployment.get('present')}`",
        f"- Status: `{dft_deployment.get('status')}`",
        f"- Deployment comparison status: `{dft_deployment.get('deployment_comparison_status')}`",
        f"- FPGA status/kind/top-count: `{dft_deployment.get('fpga_recommendation_status')}` / `{dft_deployment.get('fpga_recommendation_kind')}` / `{dft_deployment.get('fpga_top_candidate_count')}`",
        f"- FPGA top candidate ids: `{', '.join(dft_deployment.get('fpga_top_candidate_ids', []) or []) or 'none'}`",
        f"- ASIC status/kind/top-count: `{dft_deployment.get('asic_recommendation_status')}` / `{dft_deployment.get('asic_recommendation_kind')}` / `{dft_deployment.get('asic_top_candidate_count')}`",
        f"- ASIC top candidate ids: `{', '.join(dft_deployment.get('asic_top_candidate_ids', []) or []) or 'none'}`",
        f"- Target recommendation count: `{dft_deployment.get('target_recommendation_available_count')}`",
        f"- Cross-target comparison eligible: `{dft_deployment.get('cross_target_comparison_eligible')}`",
        f"- Hardware-completion eligible for deployment comparison: `{dft_deployment.get('hardware_completion_eligible_for_deployment_comparison')}`",
        f"- Cross-target status: `{dft_deployment.get('cross_target_recommendation_status')}`",
        f"- Non-physical tie-breakers used: `{dft_deployment.get('non_physical_tie_breakers_used')}`",
        f"- Validation valid: `{deployment_validation.get('valid')}`",
        f"- Deliverable complete: `{dft_deployment.get('deliverable_complete')}`",
        "- Boundary: this comparator can report a best FPGA tie set and a unique ASIC physical winner, but it cannot collapse physical ties or choose one FPGA-vs-ASIC winner without a user objective.",
    ])
    if not dft_deployment.get("present"):
        lines.append("- No DFT deployment-comparator artifact was indexed for this Step5 run.")

    dft_selector = report.get("dft_deployment_selector", {})
    dft_selector = dft_selector if isinstance(dft_selector, Mapping) else {}
    selector_validation = (
        dft_selector.get("validation", {})
        if isinstance(dft_selector.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## FPGA/ASIC Deployment Recommendations",
        f"- Status: `{deployment_recs.get('status')}`",
        f"- Scope: `{deployment_recs.get('recommendation_scope')}`",
        f"- FPGA candidate/status: `{fpga_deployment_rec.get('candidate_id')}` / `{fpga_deployment_rec.get('status')}`",
        f"- ASIC candidate/status: `{asic_deployment_rec.get('candidate_id')}` / `{asic_deployment_rec.get('status')}`",
        f"- Readiness checked/status: `{deployment_recs.get('deployment_readiness_present')}` / `{deployment_recs.get('deployment_readiness_status')}`",
        f"- Trusted winner: `{deployment_recs.get('trusted_winner')}`",
        f"- Deliverable complete: `{deployment_recs.get('deliverable_complete')}`",
        "- Boundary: these are deployment-specific hardware-PPA planning recommendations only, not full-SCF trusted winners.",
    ])
    target_sections = (
        report.get("target_scoped_recommendation_sections", {})
        if isinstance(report.get("target_scoped_recommendation_sections", {}), Mapping)
        else {}
    )
    for target, title in (
        ("fpga", "FPGA Best/Pareto Recommendation"),
        ("asic", "ASIC Best/Pareto Recommendation"),
    ):
        section = (
            target_sections.get(target, {})
            if isinstance(target_sections.get(target, {}), Mapping)
            else {}
        )
        best = section.get("best", {}) if isinstance(section.get("best", {}), Mapping) else {}
        pareto = section.get("pareto", {}) if isinstance(section.get("pareto", {}), Mapping) else {}
        lines.extend([
            "",
            f"## {title}",
            f"- Status: `{section.get('status')}`",
            f"- Candidate/design: `{section.get('candidate_id')}` / `{section.get('design_candidate_id')}`",
            f"- Best candidate: `{best.get('candidate_id')}`",
            f"- Pareto candidates: `{', '.join(str(item) for item in (pareto.get('candidate_ids', []) or [])) or 'none'}`",
            f"- Evidence level: `{section.get('evidence_level')}`",
            f"- Blockers: `{', '.join(str(item) for item in (section.get('blockers', []) or [])) or 'none'}`",
            f"- Trusted final claim: `{section.get('trusted_final_claim')}`",
            f"- Deliverable complete: `{section.get('deliverable_complete')}`",
            f"- Boundary: {section.get('claim_boundary')}",
        ])

    dft_deployment_support = report.get("dft_deployment_decision_support", {})
    dft_deployment_support = dft_deployment_support if isinstance(dft_deployment_support, Mapping) else {}
    support_recs = (
        dft_deployment_support.get("recommendations", {})
        if isinstance(dft_deployment_support.get("recommendations", {}), Mapping)
        else {}
    )
    support_fpga = support_recs.get("fpga", {}) if isinstance(support_recs.get("fpga", {}), Mapping) else {}
    support_asic = support_recs.get("asic", {}) if isinstance(support_recs.get("asic", {}), Mapping) else {}
    release_gates = (
        dft_deployment_support.get("release_completion_gates", {})
        if isinstance(dft_deployment_support.get("release_completion_gates", {}), Mapping)
        else {}
    )
    full_scf_gate = (
        dft_deployment_support.get("full_scf_numerical_gate", {})
        if isinstance(dft_deployment_support.get("full_scf_numerical_gate", {}), Mapping)
        else {}
    )
    blocker_report_source_lane_summary = (
        dft_deployment_support.get("blocker_report_source_lane_summary", {})
        if isinstance(
            dft_deployment_support.get("blocker_report_source_lane_summary", {}),
            Mapping,
        )
        else {}
    )
    blocker_report_source_lane_items = [
        f"{lane}:{blocker_report_source_lane_summary.get(lane, {}).get('artifact_count', 0)}"
        for lane in dft_deployment_support.get("blocker_report_source_lanes", []) or []
    ]
    blocker_report_source_lane_display = (
        ", ".join(blocker_report_source_lane_items)
        if blocker_report_source_lane_items
        else "none"
    )
    release_provenance_items = []
    release_runtime_items = []
    candidate_kernel_axis_items = []
    for lane in dft_deployment_support.get("blocker_report_source_lanes", []) or []:
        lane_summary = blocker_report_source_lane_summary.get(lane, {})
        if not isinstance(lane_summary, Mapping):
            continue
        release_statuses = lane_summary.get(
            "release_candidate_identity_provenance_statuses", []
        )
        if release_statuses:
            release_provenance_items.append(
                f"{lane}:{'+'.join(str(item) for item in release_statuses)}"
            )
        runtime_ids = lane_summary.get("runtime_schedule_ids", [])
        co_schedule_ids = lane_summary.get("co_scheduling_policy_ids", [])
        queue_policies = lane_summary.get("queue_policies", [])
        if runtime_ids or co_schedule_ids or queue_policies:
            release_runtime_items.append(
                f"{lane}:runtime={'+'.join(str(item) for item in runtime_ids) or 'none'}, "
                f"co_schedule={'+'.join(str(item) for item in co_schedule_ids) or 'none'}, "
                f"queue={'+'.join(str(item) for item in queue_policies) or 'none'}, "
                f"release_hashes={len(lane_summary.get('artifact_provenance_release_subset_hashes', []) or [])}, "
                f"matrix_hashes={len(lane_summary.get('artifact_provenance_candidate_workflow_deployment_target_matrix_hashes', []) or [])}"
            )
        if (
            "candidate_kernel_axis_unbound_row_count" in lane_summary
            or "parsed_stage_result_ref_count" in lane_summary
        ):
            candidate_kernel_axis_items.append(
                f"{lane}:unbound={lane_summary.get('candidate_kernel_axis_unbound_row_count', 0)}, "
                f"parsed_refs={lane_summary.get('parsed_stage_result_ref_count', 0)}"
            )
    release_provenance_display = (
        ", ".join(release_provenance_items) if release_provenance_items else "none"
    )
    release_runtime_display = (
        ", ".join(release_runtime_items) if release_runtime_items else "none"
    )
    candidate_kernel_axis_display = (
        ", ".join(candidate_kernel_axis_items)
        if candidate_kernel_axis_items
        else "none"
    )
    target_counter_items = []
    for lane in dft_deployment_support.get("blocker_report_source_lanes", []) or []:
        lane_summary = blocker_report_source_lane_summary.get(lane, {})
        if not isinstance(lane_summary, Mapping):
            continue
        has_target_counter = any(
            key in lane_summary
            for key in (
                "candidate_kernel_axis_bound_row_count",
                "candidate_kernel_axis_unbound_row_count",
                "parsed_stage_result_ref_count",
                "replayable_tool_transcript_ref_count",
                "availability_probe_only_row_count",
                "candidate_kernel_target_axis_count",
                "candidate_kernel_target_axis_counts_by_target",
                "row_counts_by_target_platform_kind",
                "unknown_target_platform_kind_row_count",
                "stable_blocker_reason_counts",
                "blocker_count",
                "blocker_id_counts",
            )
        )
        if not has_target_counter:
            continue
        target_counts = lane_summary.get("candidate_kernel_target_axis_counts_by_target", {})
        target_counts_display = "none"
        if isinstance(target_counts, Mapping) and target_counts:
            target_counts_display = "+".join(
                f"{target}:{target_counts[target]}" for target in sorted(target_counts)
            )
        blocker_counts = lane_summary.get("stable_blocker_reason_counts", {})
        blocker_display = "none"
        if isinstance(blocker_counts, Mapping) and blocker_counts:
            blocker_display = "+".join(
                f"{reason}:{blocker_counts[reason]}"
                for reason in sorted(blocker_counts)
            )
        blocker_id_counts = lane_summary.get("blocker_id_counts", {})
        blocker_id_display = "none"
        if isinstance(blocker_id_counts, Mapping) and blocker_id_counts:
            blocker_id_display = "+".join(
                f"{blocker_id}:{blocker_id_counts[blocker_id]}"
                for blocker_id in sorted(blocker_id_counts)
            )
        target_counter_items.append(
            f"{lane}:axis={lane_summary.get('candidate_kernel_target_axis_count', 0)}, "
            f"targets={target_counts_display}, "
            f"bound={lane_summary.get('candidate_kernel_axis_bound_row_count', 0)}, "
            f"unbound={lane_summary.get('candidate_kernel_axis_unbound_row_count', 0)}, "
            f"parsed_refs={lane_summary.get('parsed_stage_result_ref_count', 0)}, "
            f"replayable_transcripts={lane_summary.get('replayable_tool_transcript_ref_count', 0)}, "
            f"availability_probe_only={lane_summary.get('availability_probe_only_row_count', 0)}, "
            f"unknown_target={lane_summary.get('unknown_target_platform_kind_row_count', 0)}, "
            f"blocker_count={lane_summary.get('blocker_count', 0)}, "
            f"blockers={blocker_display}, "
            f"blocker_ids={blocker_id_display}"
        )
    target_counter_display = (
        ", ".join(target_counter_items) if target_counter_items else "none"
    )
    lines.extend([
        "",
        "## DFT Deployment Selector",
        f"- Present: `{dft_selector.get('present')}`",
        f"- Status: `{dft_selector.get('status')}`",
        f"- Objective present: `{dft_selector.get('objective_present')}`",
        f"- Objective id/target: `{dft_selector.get('objective_id')}` / `{dft_selector.get('objective_deployment_target')}`",
        f"- Selected target: `{dft_selector.get('selected_deployment_target')}`",
        f"- Selected candidate id: `{dft_selector.get('selected_candidate_id')}`",
        f"- Target selection status: `{dft_selector.get('target_selection_status')}`",
        f"- Candidate selection status: `{dft_selector.get('candidate_selection_status')}`",
        f"- Non-physical tie-breakers used: `{dft_selector.get('non_physical_tie_breakers_used')}`",
        f"- Validation valid: `{selector_validation.get('valid')}`",
        f"- Deliverable complete: `{dft_selector.get('deliverable_complete')}`",
        "- Boundary: this selector is fail-closed without an explicit objective and cannot use candidate ids, Step2 scores, labels, or sidecars to break physical ties.",
    ])
    if not dft_selector.get("present"):
        lines.append("- No DFT deployment-selector artifact was indexed for this Step5 run.")

    dft_decision = report.get("dft_deployment_decision_summary", {})
    dft_decision = dft_decision if isinstance(dft_decision, Mapping) else {}
    decision_validation = (
        dft_decision.get("validation", {})
        if isinstance(dft_decision.get("validation", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Deployment Decision Support",
        f"- Present: `{dft_deployment_support.get('present')}`",
        f"- Status: `{dft_deployment_support.get('status')}`",
        f"- Current best available: `{dft_deployment_support.get('current_best_available')}`",
        f"- Target feasibility ready: `{dft_deployment_support.get('target_feasibility_ready')}`",
        f"- FPGA target: `{support_fpga.get('candidate_id')}` / `{support_fpga.get('selected_device')}` / `{support_fpga.get('selected_part')}`",
        f"- ASIC target: `{support_asic.get('candidate_id')}` / `{support_asic.get('selected_device')}`",
        f"- Full-SCF numerical gate: `{full_scf_gate.get('status')}` / passed `{full_scf_gate.get('passed')}`",
        f"- Candidate-set gate: `{release_gates.get('candidate_set_consistency_status')}`",
        f"- Deployment source consensus: `{release_gates.get('deployment_source_consensus_status')}`",
        f"- Deployment target consensus: `{release_gates.get('deployment_target_consensus_status')}`",
        f"- Deployment candidate alignment: `{release_gates.get('deployment_candidate_alignment_status')}`",
        f"- Blocker producer refs: `{dft_deployment_support.get('blocker_report_source_producer_artifact_ref_count')}`",
        f"- Blocker producer lanes: `{blocker_report_source_lane_display}`",
        f"- Release provenance: `{release_provenance_display}`",
        f"- Release runtime/co-scheduling: `{release_runtime_display}`",
        f"- Candidate/kernel axis gaps: `{candidate_kernel_axis_display}`",
        f"- Target ledger counters: `{target_counter_display}`",
        f"- Release claim status: `{release_gates.get('status_claim')}`",
        f"- Trusted winner: `{dft_deployment_support.get('trusted_winner')}`",
        f"- Deliverable complete: `{dft_deployment_support.get('deliverable_complete')}`",
        "- Boundary: decision support coordinates current PPA winners, targets, numerical gates, and blockers; it never upgrades final claims.",
    ])
    if not dft_deployment_support.get("present"):
        lines.append("- No DFT deployment decision-support artifacts were indexed for this Step5 run.")

    decision_packet = report.get("dft_hardware_deployment_decision_packet", {})
    decision_packet = decision_packet if isinstance(decision_packet, Mapping) else {}
    packet_validation = (
        decision_packet.get("validation", {})
        if isinstance(decision_packet.get("validation", {}), Mapping)
        else {}
    )
    packet_fpga_target = (
        decision_packet.get("fpga_selected_target", {})
        if isinstance(decision_packet.get("fpga_selected_target", {}), Mapping)
        else {}
    )
    packet_asic_target = (
        decision_packet.get("asic_selected_target", {})
        if isinstance(decision_packet.get("asic_selected_target", {}), Mapping)
        else {}
    )
    packet_full_scf_gate = (
        decision_packet.get("full_scf_numerical_gate", {})
        if isinstance(decision_packet.get("full_scf_numerical_gate", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Hardware Deployment Decision Packet",
        f"- Present: `{decision_packet.get('present')}`",
        f"- Status: `{decision_packet.get('status')}`",
        f"- Planning packet ready: `{decision_packet.get('planning_packet_ready')}`",
        f"- Can name scoped hardware-PPA winners: `{decision_packet.get('can_name_scoped_hardware_ppa_winners')}`",
        f"- Deployment target selection ready: `{decision_packet.get('deployment_target_selection_ready')}`",
        f"- Full-SCF numerical gate passed: `{decision_packet.get('full_scf_numerical_gate_passed')}`",
        f"- FPGA target: `{packet_fpga_target.get('target_device_id')}` / `{packet_fpga_target.get('part')}`",
        f"- ASIC target: `{packet_asic_target.get('target_library_id')}` / `{packet_asic_target.get('process_node')}`",
        f"- Full-SCF gate: `{packet_full_scf_gate.get('status')}` / passed `{packet_full_scf_gate.get('passed')}`",
        f"- Validation valid: `{packet_validation.get('valid')}`",
        f"- Deliverable complete: `{decision_packet.get('deliverable_complete')}`",
        "- Boundary: decision packets are planning packets only; targeted/final deployment claims stay false until full-SCF and target-specific hard gates pass.",
    ])
    packet_safety_findings = decision_packet.get("safety_findings", [])
    if packet_safety_findings:
        lines.append(
            "- Safety findings: `"
            + ", ".join(str(item) for item in packet_safety_findings)
            + "`"
        )
    if not decision_packet.get("present"):
        lines.append("- No DFT deployment decision-packet artifact was indexed for this Step5 run.")
    lines.extend([
        "",
        "## DFT Deployment Decision Summary",
        f"- Present: `{dft_decision.get('present')}`",
        f"- Status: `{dft_decision.get('status')}`",
        f"- Best recommendation status: `{dft_decision.get('best_recommendation_status')}`",
        f"- Recommended target/candidate: `{dft_decision.get('recommended_target')}` / `{dft_decision.get('recommended_candidate_id')}`",
        f"- Objective id: `{dft_decision.get('objective_id')}`",
        f"- FPGA model/binding/blockers: `{dft_decision.get('fpga_selected_model_id')}` / `{dft_decision.get('fpga_target_model_binding_status')}` / `{', '.join(dft_decision.get('fpga_blocker_ids', []) or []) or 'none'}`",
        f"- ASIC model/binding/blockers: `{dft_decision.get('asic_selected_model_id')}` / `{dft_decision.get('asic_target_model_binding_status')}` / `{', '.join(dft_decision.get('asic_blocker_ids', []) or []) or 'none'}`",
        f"- Validation valid: `{decision_validation.get('valid')}`",
        f"- Deliverable complete: `{dft_decision.get('deliverable_complete')}`",
        "- Boundary: this summary rolls up selector/comparator/target-binding evidence into a current deployment recommendation without upgrading FPGA, ASIC, PPA, or full-SCF completion claims.",
    ])
    if not dft_decision.get("present"):
        lines.append("- No DFT deployment decision-summary artifact was indexed for this Step5 run.")

    dft_semantic = report.get("dft_audit_semantic_closure", {})
    dft_semantic = dft_semantic if isinstance(dft_semantic, Mapping) else {}
    lines.extend([
        "",
        "## DFT Semantic Audit Closure",
        f"- Present: `{dft_semantic.get('present')}`",
        f"- Status: `{dft_semantic.get('status')}`",
        f"- Overall passed: `{dft_semantic.get('overall_passed')}`",
        f"- Source-hash backed: `{dft_semantic.get('source_hash_backed')}`",
        f"- Required sources hashed: `{dft_semantic.get('hashed_required_source_count')}` / `{dft_semantic.get('required_source_count')}`",
        f"- Failed checks: `{', '.join(str(item) for item in (dft_semantic.get('failed_checks', []) or [])) or 'none'}`",
        f"- Missing checks: `{', '.join(str(item) for item in (dft_semantic.get('missing_checks', []) or [])) or 'none'}`",
        "- Boundary: semantic closure is audit-hardening evidence only; it does not prove hardware release, PPA, trusted Pareto, or final DFT/QE deliverable completion.",
    ])
    if not dft_semantic.get("present"):
        lines.append("- No DFT semantic audit-closure artifact was indexed for this Step5 run.")

    dft_hybrid = report.get("dft_full_scf_evaluated_hybrid", {})
    dft_hybrid = dft_hybrid if isinstance(dft_hybrid, Mapping) else {}
    full_scf_accounting = report.get("full_scf_accounting_completeness", {})
    full_scf_accounting = (
        full_scf_accounting
        if isinstance(full_scf_accounting, Mapping)
        else {}
    )
    accounting_attachment = (
        report.get("qe_baseline_row_accounting_attachment", {})
        if isinstance(report.get("qe_baseline_row_accounting_attachment", {}), Mapping)
        else {}
    )
    attachment_artifacts = (
        accounting_attachment.get("artifacts", {})
        if isinstance(accounting_attachment.get("artifacts", {}), Mapping)
        else {}
    )
    hybrid_schedule = (
        dft_hybrid.get("schedule_summary", {})
        if isinstance(dft_hybrid.get("schedule_summary", {}), Mapping)
        else {}
    )
    accounting_host = (
        full_scf_accounting.get("host_retained_stages", {})
        if isinstance(full_scf_accounting.get("host_retained_stages", {}), Mapping)
        else {}
    )
    accounting_overheads = (
        full_scf_accounting.get("runtime_overheads", {})
        if isinstance(full_scf_accounting.get("runtime_overheads", {}), Mapping)
        else {}
    )
    accounting_kernels = (
        full_scf_accounting.get("accelerated_major_kernels", {})
        if isinstance(full_scf_accounting.get("accelerated_major_kernels", {}), Mapping)
        else {}
    )
    accounting_abi = (
        full_scf_accounting.get("descriptor_runtime_abi", {})
        if isinstance(full_scf_accounting.get("descriptor_runtime_abi", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Full-SCF Evaluated Hybrid",
        f"- Present: `{dft_hybrid.get('present')}`",
        f"- Required artifact bundle present: `{dft_hybrid.get('required_artifacts_present')}`",
        f"- Prototype boundary: `{dft_hybrid.get('prototype_boundary')}`",
        f"- Device residency: `{dft_hybrid.get('device_residency')}`",
        f"- Descriptor validation passed: `{dft_hybrid.get('descriptor_validation_passed')}`",
        f"- Numerical correctness claim eligible: `{dft_hybrid.get('numerical_correctness_claim_eligible')}`",
        f"- PPA claim eligible: `{dft_hybrid.get('ppa_claim_eligible')}`",
        f"- Accelerated kernels: `{', '.join(str(item) for item in (hybrid_schedule.get('accelerated_kernel_ids', []) or []))}`",
        f"- Host-bound phases: `{', '.join(str(item) for item in (hybrid_schedule.get('host_bound_phase_ids', []) or []))}`",
        f"- Full-SCF accounting completeness: status `{full_scf_accounting.get('status')}`, complete `{full_scf_accounting.get('complete')}`, projection-only `{full_scf_accounting.get('projection_only')}`, blockers `{len(full_scf_accounting.get('blocker_ids', []) or [])}`",
        f"- CPU-retained stage accounting: present `{len(accounting_host.get('present_ids', []) or [])}` / `{len(accounting_host.get('required_ids', []) or [])}`, missing `{', '.join(str(item) for item in (accounting_host.get('missing_ids', []) or [])) or 'none'}`",
        f"- Transfer/sync/runtime overhead accounting: present `{len(accounting_overheads.get('present_ids', []) or [])}` / `{len(accounting_overheads.get('required_ids', []) or [])}`, missing `{', '.join(str(item) for item in (accounting_overheads.get('missing_ids', []) or [])) or 'none'}`",
        f"- Major-kernel accelerated cost accounting: present `{len(accounting_kernels.get('present_ids', []) or [])}` / `{len(accounting_kernels.get('required_ids', []) or [])}`, missing `{', '.join(str(item) for item in (accounting_kernels.get('missing_ids', []) or [])) or 'none'}`",
        f"- Descriptor/runtime ABI accounting: descriptor `{accounting_abi.get('descriptor_present')}`, validation `{accounting_abi.get('descriptor_validation_passed')}`, runtime schedule `{accounting_abi.get('runtime_schedule_present')}`, host-orchestrated `{accounting_abi.get('host_orchestrated')}`, data residency `{accounting_abi.get('data_residency_plan_present')}`",
        "- Boundary: evaluated-hybrid artifacts expose schedule/cost accounting only; they do not prove device residency, numerical correctness, or FPGA/ASIC PPA closure.",
    ])
    if not dft_hybrid.get("present"):
        lines.append("- No full-SCF evaluated-hybrid artifact bundle was indexed for this Step5 run.")
    lines.extend([
        "",
        "## QE Baseline / Full-SCF Row Accounting Attachment",
        f"- Present: `{accounting_attachment.get('present')}`",
        f"- Status: `{accounting_attachment.get('status')}`",
        f"- QE baseline comparison artifact: `{(attachment_artifacts.get('qe_baseline_comparison_index.json', {}) or {}).get('path')}`",
        f"- Full-SCF row accounting artifact: `{(attachment_artifacts.get('full_scf_row_accounting.json', {}) or {}).get('path')}`",
        f"- Claim upgrade allowed: `{accounting_attachment.get('claim_upgrade_allowed')}`",
        f"- Hardware completion eligible: `{accounting_attachment.get('hardware_completion_eligible')}`",
        f"- Deliverable complete: `{accounting_attachment.get('deliverable_complete')}`",
        "- Boundary: the attachment is row-accounting visibility only; it does not upgrade numerical, hardware, FPGA/ASIC, or final deployment claims.",
    ])
    if not accounting_attachment.get("present"):
        lines.append("- No QE baseline / full-SCF row-accounting attachment was indexed for this Step5 run.")

    step2_provenance = report.get("step2_search_provenance", {})
    step2_provenance = step2_provenance if isinstance(step2_provenance, Mapping) else {}
    if step2_provenance.get("present"):
        search_space = (
            step2_provenance.get("search_space", {})
            if isinstance(step2_provenance.get("search_space", {}), Mapping)
            else {}
        )
        generation = (
            step2_provenance.get("candidate_generation", {})
            if isinstance(step2_provenance.get("candidate_generation", {}), Mapping)
            else {}
        )
        screening = (
            step2_provenance.get("screening", {})
            if isinstance(step2_provenance.get("screening", {}), Mapping)
            else {}
        )
        admission = (
            step2_provenance.get("admission_queue", {})
            if isinstance(step2_provenance.get("admission_queue", {}), Mapping)
            else {}
        )
        lines.extend([
            "",
            "## Step2 Search Provenance",
            f"- Status: `{step2_provenance.get('status')}`",
            f"- Search policy: `{search_space.get('search_policy_name')}`; search-space hash: `{search_space.get('search_space_hash')}`",
            f"- Generated architecture/mapping candidates: `{generation.get('architecture_candidate_count')}` / `{generation.get('mapping_candidate_count')}`",
            f"- Screened/promoted candidates: `{screening.get('screened_candidate_count')}` / `{screening.get('promoted_candidate_count')}`",
            f"- Step3 admission queue: `{admission.get('queue_mode')}` with `{admission.get('entry_count')}` entries",
            "- Boundary: Step2 provenance explains replayable queue admission only; it is not Step3 measurement, convergence, FPGA/ASIC PPA, or deliverable completion proof.",
        ])

    feedback = report.get("feedback_loop", {}) or {}
    convergence = feedback.get("convergence", {}) or {}
    lines.extend([
        "",
        "## Feedback / Convergence",
        f"- Sample count: `{feedback.get('sample_count')}`",
        f"- Trusted sample count: `{feedback.get('trusted_sample_count')}`",
        f"- Converged: `{convergence.get('converged')}`",
        f"- Stop reason: `{convergence.get('stop_reason')}`",
        f"- Budget: `{convergence.get('simulation_budget')}`",
    ])

    queue_aggregation = report.get("step3_queue_aggregation", {})
    queue_aggregation = queue_aggregation if isinstance(queue_aggregation, Mapping) else {}
    if queue_aggregation.get("present"):
        lines.extend([
            "",
            "## Step3 Queue Aggregation",
            f"- Queue mode: `{queue_aggregation.get('queue_mode')}`",
            f"- Planned/executed/adjudicated: `{queue_aggregation.get('planned_entry_count')}` / `{queue_aggregation.get('executed_entry_count')}` / `{queue_aggregation.get('adjudicated_entry_count')}`",
            f"- Trusted/blocked entries: `{queue_aggregation.get('trusted_entry_count')}` / `{queue_aggregation.get('blocked_entry_count')}`",
            "- Boundary: queue aggregation is bounded campaign evidence, not FPGA/ASIC winner or deliverable-completion proof.",
        ])

    deployment_plan = report.get("deployment_recommendation_plan", {})
    deployment_plan = deployment_plan if isinstance(deployment_plan, Mapping) else {}
    if deployment_plan.get("present"):
        target_summaries = (
            deployment_plan.get("target_summaries", {})
            if isinstance(deployment_plan.get("target_summaries", {}), Mapping)
            else {}
        )
        hard_gate_queue = (
            deployment_plan.get("hard_gate_execution_queue", {})
            if isinstance(deployment_plan.get("hard_gate_execution_queue", {}), Mapping)
            else {}
        )
        hard_gate_queue_validation = (
            hard_gate_queue.get("validation", {})
            if isinstance(hard_gate_queue.get("validation", {}), Mapping)
            else {}
        )
        lines.extend([
            "",
            "## Deployment Recommendation Plan",
            f"- Status: `{deployment_plan.get('status')}`",
            f"- Trusted timing samples: `{deployment_plan.get('trusted_timing_sample_count')}`",
            f"- Candidate recommendations: `{deployment_plan.get('candidate_recommendation_count')}`",
            f"- Candidate-specific hard-gate work items: `{deployment_plan.get('hard_gate_work_item_count')}`",
            f"- FPGA target: `{(target_summaries.get('fpga', {}) or {}).get('admission_status')}`; trusted deployment claim=`{deployment_plan.get('trusted_deployment_claim')}`",
            f"- ASIC target: `{(target_summaries.get('asic', {}) or {}).get('admission_status')}`; release completion eligible=`{deployment_plan.get('release_completion_eligible')}`",
            f"- DFT hard-gate execution queue: present=`{hard_gate_queue.get('present')}`; status=`{hard_gate_queue.get('queue_status')}`; work items=`{hard_gate_queue.get('work_item_count')}`; validation valid=`{hard_gate_queue_validation.get('valid')}`",
            "- Boundary: proposal-only hard-gate worklist; not FPGA/ASIC PPA proof, winner selection, or deliverable completion.",
        ])

    requirement_matrix = report.get("requirement_evidence_matrix", {})
    requirement_matrix = requirement_matrix if isinstance(requirement_matrix, Mapping) else {}
    if requirement_matrix:
        lines.extend([
            "",
            "## Requirement-Evidence Matrix",
            "- Artifact: `requirement_evidence_matrix.json` / `requirement_evidence_matrix.md`",
            f"- Source goal: `{requirement_matrix.get('source_goal')}`",
            f"- Claimability: `{requirement_matrix.get('claimability')}`",
            f"- Requirements: `{requirement_matrix.get('requirement_count')}`",
            f"- Blocked requirements: `{requirement_matrix.get('blocked_requirement_count')}`",
            f"- Deliverable complete allowed: `{requirement_matrix.get('deliverable_complete_allowed')}`",
            f"- Trusted final claim: `{requirement_matrix.get('trusted_final_claim')}`",
            "- Boundary: requirement rows are fail-closed; missing, projected, stale, wrong-target, or tool-unavailable evidence remains non-claimable.",
        ])

    lines.extend(["", "## Claim Validation", ""])
    for validation in report.get("claim_validation", {}).get("validations", []) or []:
        reason = "; ".join(validation.get("reasons", [])) or "ok"
        lines.append(
            f"- `{validation.get('claim_id')}`: `{validation.get('validation_status')}`, "
            f"trusted=`{validation.get('trusted')}` ({reason})"
        )

    lines.extend(["", "## Limitations", ""])
    for limitation in report.get("limitations", []) or []:
        lines.append(f"- {limitation}")

    replay = report.get("replay_instructions", {})
    lines.extend([
        "",
        "## Replay Instructions",
        f"- Python command: `{replay.get('python_replay_command')}`",
        f"- Simulator command: `{replay.get('simulator_replay_command')}`",
        f"- Run directory: `{replay.get('run_directory')}`",
        f"- Artifact index: `{replay.get('required_artifact_index')}`",
        "",
    ])
    return "\n".join(lines)


def write_final_report_artifacts(
    run_dir: Path,
    *,
    claims: Optional[Iterable[Mapping[str, Any]]] = None,
    artifact_paths: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """Compatibility wrapper for Step4 claim validation plus Step5 reports.

    New staged flows should call ``write_step4_claim_validation_artifacts`` from
    evidence adjudication and ``write_step5_report_artifacts`` from reporting.
    This wrapper remains for older full-flow callers that still expect one API.
    """
    step4_paths = write_step4_claim_validation_artifacts(
        run_dir,
        claims=claims,
        artifact_paths=artifact_paths,
    )
    step5_paths = write_step5_report_artifacts(
        run_dir,
        claims=claims,
        artifact_paths=artifact_paths,
    )
    return {**step4_paths, **step5_paths}


def write_step4_claim_validation_artifacts(
    run_dir: Path,
    *,
    claims: Optional[Iterable[Mapping[str, Any]]] = None,
    artifact_paths: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """Generate Step4-owned evidence requirements and claim validation."""
    run_dir = Path(run_dir)
    _report, claim_validation, requirements = generate_final_report(
        run_dir,
        claims=claims,
        artifact_paths=artifact_paths,
    )
    _write_json(run_dir / "evidence_requirements.json", requirements)
    _write_json(run_dir / "claim_validation.json", claim_validation)
    return {
        "evidence_requirements": "evidence_requirements.json",
        "claim_validation": "claim_validation.json",
    }


def _report_artifact_ref(
    report: Mapping[str, Any],
    section_key: str,
    artifact_name: str,
    *,
    run_dir: Path,
) -> str | None:
    """Return the actual indexed artifact path, including caller-supplied parent refs."""

    section = report.get(section_key, {})
    artifacts = section.get("artifacts", {}) if isinstance(section, Mapping) else {}
    artifact_ref = artifacts.get(artifact_name, {}) if isinstance(artifacts, Mapping) else {}
    if isinstance(artifact_ref, Mapping) and artifact_ref.get("exists") and artifact_ref.get("path"):
        return str(artifact_ref["path"])
    return artifact_name if (run_dir / artifact_name).exists() else None


_STEP5_REQUIREMENT_REF_PAYLOAD_FIELDS = (
    "status",
    "evidence_status",
    "complete",
    "completion_complete",
    "deliverable_complete",
    "valid",
    "validation_valid",
    "projection_only",
    "smoke_only",
    "stale",
    "forged",
    "exists",
    "availability_only_not_kernel_ppa",
    "kernel_ppa_evidence",
    "hardware_completion_eligible",
    "raw_command_transcript_ref_count",
    "release_candidate_identity_provenance_status",
    "release_candidate_identity_provenance_blocker_ids",
    "release_candidate_identity_provenance_package_exists",
    "release_candidate_identity_provenance_package_status",
    "release_candidate_identity_provenance_canonical_bundle_bound",
    "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity",
    "release_candidate_identity_provenance_claim_boundary",
    "claim_upgrade_allowed_count",
    "availability_probe_only_row_count",
    "replayable_tool_transcript_ref_count",
    "candidate_kernel_axis_unbound_row_count",
    "candidate_kernel_axis_bound_row_count",
    "candidate_kernel_axis_unbound_stage_count",
    "parsed_stage_result_ref_count",
    "candidate_kernel_target_axis_count",
    "candidate_kernel_target_axis_counts_by_target",
    "row_counts_by_candidate_kernel_target_axis",
    "row_counts_by_target_platform_kind",
    "blocker_id_counts",
)


def _step5_file_artifact_ref(path: Path, *, base_dir: Path) -> Dict[str, Any]:
    ref: Dict[str, Any] = {
        "path": path.relative_to(base_dir).as_posix(),
        "sha256": _sha256(path),
        "hash_algorithm": "sha256",
    }
    payload = _load_json(path) if path.suffix == ".json" else {}
    if isinstance(payload, Mapping):
        for key in _STEP5_REQUIREMENT_REF_PAYLOAD_FIELDS:
            if key in payload:
                ref[key] = payload[key]
    return ref


def _merge_step5_artifact_ref_map(
    artifact_refs: Dict[str, Any],
    candidate_refs: Any,
    *,
    override: bool = False,
) -> None:
    if not isinstance(candidate_refs, Mapping):
        return
    for raw_name, raw_ref in candidate_refs.items():
        if not isinstance(raw_ref, Mapping):
            continue
        name = str(raw_name)
        ref = {str(key): value for key, value in raw_ref.items()}
        ref.setdefault("path", str(ref.get("path") or name))
        if override or name not in artifact_refs:
            artifact_refs[name] = ref


def _step5_source_producer_artifact_refs(
    run_dir: Path,
    report: Mapping[str, Any],
) -> Dict[str, Any]:
    refs: Dict[str, Any] = {}
    support = report.get("dft_deployment_decision_support", {})
    if isinstance(support, Mapping):
        _merge_step5_artifact_ref_map(
            refs,
            support.get("blocker_report_source_producer_artifact_refs"),
            override=True,
        )
    for artifact_name in (
        "blocker_report.json",
        "reporting_artifact_manifest.json",
        "coverage_claim_report.json",
        "complete_dse_release_artifact_package.json",
    ):
        payload = _load_json(run_dir / artifact_name)
        _merge_step5_artifact_ref_map(
            refs,
            payload.get("source_producer_artifact_refs"),
            override=True,
        )
    return refs


def _step5_requirement_artifact_refs(
    run_dir: Path,
    report: Mapping[str, Any],
    *,
    source_producer_artifact_refs: Mapping[str, Any],
) -> Dict[str, Any]:
    artifact_refs: Dict[str, Any] = {}
    for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        artifact_refs[path.relative_to(run_dir).as_posix()] = _step5_file_artifact_ref(
            path,
            base_dir=run_dir,
        )

    for value in report.values():
        if isinstance(value, Mapping):
            _merge_step5_artifact_ref_map(
                artifact_refs,
                value.get("artifacts"),
                override=False,
            )
    for artifact_name in (
        "reporting_artifact_manifest.json",
        "coverage_claim_report.json",
        "complete_dse_release_artifact_package.json",
        "complete_dse_release_artifact_hash_manifest.json",
    ):
        payload = _load_json(run_dir / artifact_name)
        _merge_step5_artifact_ref_map(artifact_refs, payload.get("artifacts"), override=False)
        _merge_step5_artifact_ref_map(
            artifact_refs,
            payload.get("required_artifacts"),
            override=False,
        )

    _merge_step5_artifact_ref_map(
        artifact_refs,
        source_producer_artifact_refs,
        override=True,
    )
    return artifact_refs


def _step5_source_artifact_binding_conflicts(run_dir: Path) -> List[Dict[str, Any]]:
    """Return source-artifact run/backend mismatches that Step5 must fail closed on."""

    def _artifact(name: str) -> Mapping[str, Any]:
        payload = _load_json(run_dir / name)
        return payload if isinstance(payload, Mapping) else {}

    def _backend(payload: Mapping[str, Any], artifact: str) -> str:
        if artifact == "simulation_request.json":
            translation = (
                payload.get("candidate_translation", {})
                if isinstance(payload.get("candidate_translation", {}), Mapping)
                else {}
            )
            simulation_config = (
                translation.get("simulation_config", {})
                if isinstance(translation.get("simulation_config", {}), Mapping)
                else {}
            )
            value = (
                translation.get("backend_mode")
                or simulation_config.get("backend")
                or payload.get("mode")
            )
        else:
            value = payload.get("backend")
        normalized = str(value or "")
        if normalized == "standalone_systemc":
            return "systemc"
        if normalized == "gem5_cosim":
            return "gem5_systemc"
        return normalized

    artifacts = {
        name: _artifact(name)
        for name in (
            "verdict.json",
            "simulation_result.json",
            "simulation_result.raw.json",
            "manifest.json",
            "provenance.json",
            "simulation_request.json",
            "step3_status.json",
        )
        if (run_dir / name).exists()
    }
    conflicts: List[Dict[str, Any]] = []
    for field in ("run_id", "backend"):
        values: Dict[str, List[str]] = {}
        for artifact, payload in artifacts.items():
            if field == "backend" and artifact == "simulation_request.json":
                # A Step4/Step5 source bundle may wrap a lower-level generic
                # SystemC request inside a gem5_systemc evidence path.  The
                # authoritative backend claim is carried by verdict/manifest/
                # result/status; request.backend is still checked during
                # Step4 replay binding when applicable.
                continue
            raw_value = _backend(payload, artifact) if field == "backend" else str(payload.get(field) or "")
            if raw_value:
                values.setdefault(raw_value, []).append(artifact)
        if len(values) > 1:
            conflicts.append({
                "field": field,
                "observed_values": sorted(values),
                "sources_by_value": {
                    value: sorted(sources)
                    for value, sources in sorted(values.items())
                },
            })
    return conflicts


def write_step5_report_artifacts(
    run_dir: Path,
    *,
    claims: Optional[Iterable[Mapping[str, Any]]] = None,
    artifact_paths: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """Generate Step5-owned final report, ranking, and summary artifacts."""
    run_dir = Path(run_dir)
    missing_step4 = [
        artifact
        for artifact in ("verdict.json", "claim_validation.json", "evidence_requirements.json")
        if not (run_dir / artifact).exists()
    ]
    if missing_step4:
        raise ValueError(
            "Step5 report generation requires Step4 adjudication artifacts before final report writing: "
            + ", ".join(missing_step4)
        )
    source_claim_validation = _load_json(run_dir / "claim_validation.json")
    if not source_claim_validation:
        raise ValueError("Step5 report generation requires a non-empty Step4 claim_validation.json")
    source_binding_conflicts = _step5_source_artifact_binding_conflicts(run_dir)
    if source_binding_conflicts:
        raise ValueError(
            "Step5 report generation requires source artifacts to bind to one run/backend "
            f"before final report writing: {source_binding_conflicts}"
        )
    report, _claim_validation, _requirements = generate_final_report(
        run_dir,
        claims=claims,
        artifact_paths=artifact_paths,
    )
    source_step4_passed = bool(source_claim_validation.get("passed", False))
    report.setdefault("run_metadata", {})["source_step4_claim_validation"] = "claim_validation.json"
    report.setdefault("run_metadata", {})["source_step4_claim_validation_passed"] = source_step4_passed
    report.setdefault("run_metadata", {})["step5_trust_boundary"] = (
        "Step5 presents Step4 evidence and may report blocked claims; it does not upgrade unpassed Step4 claim validation."
    )
    if not source_step4_passed:
        claim_validation = dict(report.get("claim_validation", {}))
        errors = list(claim_validation.get("errors", []) or [])
        source_reason = str(
            source_claim_validation.get("fail_closed_reason")
            or source_claim_validation.get("reason")
            or "source_step4_claim_validation_failed"
        )
        error = f"source_step4_claim_validation: {source_reason}"
        if error not in errors:
            errors.append(error)
        claim_validation.update(
            {
                "passed": False,
                "source_step4_claim_validation": "claim_validation.json",
                "source_step4_claim_validation_passed": False,
                "fail_closed_reason": (
                    "Step5 final_report.json cannot upgrade an unpassed source "
                    "Step4 claim_validation.json."
                ),
                "errors": errors,
            }
        )
        report["claim_validation"] = claim_validation
    search_admission_validation = (
        report.get("search_admission_validation", {})
        if isinstance(report.get("search_admission_validation", {}), Mapping)
        else {}
    )
    if (
        search_admission_validation.get("present")
        and search_admission_validation.get("valid") is not True
    ):
        claim_validation = dict(report.get("claim_validation", {}))
        errors = list(claim_validation.get("errors", []) or [])
        error = (
            "search_admission_validation: Step5 final_report.json cannot "
            "upgrade failed search/admission validation artifacts."
        )
        if error not in errors:
            errors.append(error)
        claim_validation.update({
            "passed": False,
            "search_admission_validation": "search_admission_validation",
            "search_admission_validation_passed": False,
            "fail_closed_reason": (
                "Step5 final_report.json cannot upgrade failed "
                "search/admission validation artifacts."
            ),
            "errors": errors,
        })
        report["claim_validation"] = claim_validation
    source_producer_refs = _step5_source_producer_artifact_refs(run_dir, report)
    requirement_artifact_refs = _step5_requirement_artifact_refs(
        run_dir,
        report,
        source_producer_artifact_refs=source_producer_refs,
    )
    requirement_audit = build_requirement_evidence_audit_matrix(
        artifact_refs=requirement_artifact_refs,
        recommendation_report=report,
        source_producer_artifact_refs=source_producer_refs,
        status="blocked",
    )
    _write_json(run_dir / "requirement_evidence_matrix.json", requirement_audit)
    _write_text(
        run_dir / "requirement_evidence_matrix.md",
        render_requirement_evidence_audit_markdown(requirement_audit),
    )
    report["requirement_evidence_matrix"] = requirement_audit
    claim_validation = dict(report.get("claim_validation", {}))
    claim_validation["requirement_evidence_matrix"] = {
        "path": "requirement_evidence_matrix.json",
        "markdown_path": "requirement_evidence_matrix.md",
        "schema_version": requirement_audit.get("schema_version"),
        "source_goal": requirement_audit.get("source_goal"),
        "claimability": requirement_audit.get("claimability"),
        "requirement_count": requirement_audit.get("requirement_count"),
        "blocked_requirement_count": requirement_audit.get("blocked_requirement_count"),
        "deliverable_complete_allowed": bool(
            requirement_audit.get("deliverable_complete_allowed", False)
        ),
        "trusted_final_claim": bool(requirement_audit.get("trusted_final_claim", False)),
    }
    claim_validation["deliverable_complete_allowed"] = bool(
        claim_validation.get("passed", False)
        and requirement_audit.get("deliverable_complete_allowed", False)
    )
    claim_validation["trusted_final_claim"] = bool(
        claim_validation.get("deliverable_complete_allowed", False)
        and requirement_audit.get("trusted_final_claim", False)
    )
    report["claim_validation"] = claim_validation
    report["trusted_final_claim"] = False
    report["deliverable_complete"] = False
    _write_json(run_dir / "final_report.json", report)
    _write_text(run_dir / "final_report.md", render_markdown_report(report))
    campaign_summary = {
        "schema_version": "dse.step5.campaign_summary.v1",
        "generated_at": _now_iso(),
        "run_metadata": report.get("run_metadata", {}),
        "selected_recommendation": report.get("selected_recommendation", {}),
        "search_admission_validation_summary": report.get("search_admission_validation", {}),
        "trusted_ranking_count": len(report.get("trusted_ranking", []) or []),
        "limitations": report.get("limitations", []),
        "step2_search_provenance_summary": report.get("step2_search_provenance", {}),
        "deployment_recommendation_plan_summary": report.get("deployment_recommendation_plan", {}),
        "dft_evidence_ledger_summary": report.get("dft_evidence_ledger", {}),
        "dft_trial_state_ledger_summary": report.get("dft_trial_state_ledger", {}),
        "dft_candidate_binding_map_summary": report.get("dft_candidate_binding_map", {}),
        "dft_hardware_completion_workplan_summary": report.get("dft_hardware_completion_workplan", {}),
        "dft_hardware_closure_shards_summary": report.get("dft_hardware_closure_shards", {}),
        "dft_hardware_closure_packets_summary": report.get("dft_hardware_closure_packets", {}),
        "dft_hardware_closure_candidate_bundles_summary": report.get("dft_hardware_closure_candidate_bundles", {}),
        "dft_hardware_closure_unit_provenance_summary": report.get("dft_hardware_closure_unit_provenance", {}),
        "dft_hardware_closure_artifact_chain_summary": report.get("dft_hardware_closure_artifact_chain", {}),
        "dft_hardware_closure_source_flow_plan_summary": report.get("dft_hardware_closure_source_flow_plan", {}),
        "dft_hardware_closure_raw_stage_materialization_summary": report.get(
            "dft_hardware_closure_raw_stage_materialization", {}
        ),
        "dft_hardware_closure_raw_transcript_registration_summary": report.get(
            "dft_hardware_closure_raw_transcript_registration", {}
        ),
        "dft_hardware_closure_evidence_intake_summary": report.get("dft_hardware_closure_evidence_intake", {}),
        "dft_hardware_closure_adjudication_summary": report.get("dft_hardware_closure_adjudication", {}),
        "dft_hardware_closure_parsed_evidence_summary": report.get("dft_hardware_closure_parsed_evidence", {}),
        "dft_hardware_closure_parser_run_summary": report.get("dft_hardware_closure_parser_run", {}),
        "dft_hardware_closure_gate_adjudication_summary": report.get("dft_hardware_closure_gate_adjudication", {}),
        "dft_hardware_closure_release_gate_summary": report.get("dft_hardware_closure_release_gate", {}),
        "dft_hardware_ppa_ranking_summary": report.get("dft_hardware_ppa_ranking", {}),
        "dft_candidate_specific_ppa_provenance_summary": report.get("dft_candidate_specific_ppa_provenance", {}),
        "dft_architecture_winner_resolution_summary": report.get("dft_architecture_winner_resolution", {}),
        "dft_hardware_deployment_recommendation_readiness_summary": report.get(
            "dft_hardware_deployment_recommendation_readiness",
            {},
        ),
        "dft_deployment_decision_support_summary": report.get("dft_deployment_decision_support", {}),
        "dft_hardware_deployment_decision_packet_summary": report.get(
            "dft_hardware_deployment_decision_packet", {}
        ),
        "dft_deployment_comparator_summary": report.get("dft_deployment_comparator", {}),
        "dft_deployment_selector_summary": report.get("dft_deployment_selector", {}),
        "dft_deployment_decision_summary_summary": report.get("dft_deployment_decision_summary", {}),
        "target_scoped_recommendation_sections_summary": report.get(
            "target_scoped_recommendation_sections", {}
        ),
        "dft_l4_goal_binding_summary": report.get("dft_l4_goal_binding", {}),
        "dft_audit_semantic_closure_summary": report.get("dft_audit_semantic_closure", {}),
        "dft_full_scf_evaluated_hybrid_summary": report.get("dft_full_scf_evaluated_hybrid", {}),
        "qe_baseline_row_accounting_attachment_summary": report.get(
            "qe_baseline_row_accounting_attachment", {}
        ),
        "full_scf_accounting_completeness_summary": report.get("full_scf_accounting_completeness", {}),
        "requirement_evidence_matrix_summary": {
            "path": "requirement_evidence_matrix.json",
            "claimability": requirement_audit.get("claimability"),
            "requirement_count": requirement_audit.get("requirement_count"),
            "blocked_requirement_count": requirement_audit.get("blocked_requirement_count"),
            "deliverable_complete_allowed": requirement_audit.get("deliverable_complete_allowed"),
            "trusted_final_claim": requirement_audit.get("trusted_final_claim"),
        },
        "source_step4_artifacts": ["verdict.json", "claim_validation.json", "evidence_requirements.json"],
    }
    deployment_recommendations = (
        report.get("deployment_recommendations", {})
        if isinstance(report.get("deployment_recommendations", {}), Mapping)
        else {}
    )
    dft_deployment_decision_support = (
        report.get("dft_deployment_decision_support", {})
        if isinstance(report.get("dft_deployment_decision_support", {}), Mapping)
        else {}
    )
    campaign_summary["deployment_recommendations_summary"] = deployment_recommendations
    _write_json(run_dir / "campaign_summary.json", campaign_summary)
    selected_status = str((report.get("selected_recommendation", {}) or {}).get("selection_status") or "")
    hardware_ppa_sidecar_scope = selected_status in {
        "hardware_ppa_ranking_available_no_full_dse_winner",
        "hardware_ppa_deployment_recommendations_available_no_full_scf_winner",
    }
    _write_json(run_dir / "deployment_recommendations.json", {
        "schema_version": "dse.step5.deployment_recommendations.v1",
        "generated_at": _now_iso(),
        "source_step4_artifacts": ["verdict.json", "claim_validation.json", "evidence_requirements.json"],
        "source_step5_artifacts": ["final_report.json"],
        "source_hardware_artifacts": [
            "dft_architecture_winner_resolution.json"
            if (run_dir / "dft_architecture_winner_resolution.json").exists()
            else None,
            "dft_hardware_ppa_ranking.json"
            if (run_dir / "dft_hardware_ppa_ranking.json").exists()
            else None,
            "dft_candidate_specific_ppa_provenance_audit.json"
            if (run_dir / "dft_candidate_specific_ppa_provenance_audit.json").exists()
            else None,
            "dft_fpga_asic_deployment_summary.json"
            if (run_dir / "dft_fpga_asic_deployment_summary.json").exists()
            else None,
            "dft_deployment_target_feasibility.json"
            if (run_dir / "dft_deployment_target_feasibility.json").exists()
            else None,
            "dft_deployment_coordination_summary.json"
            if (run_dir / "dft_deployment_coordination_summary.json").exists()
            else None,
            "dft_candidate_set_consistency.json"
            if (run_dir / "dft_candidate_set_consistency.json").exists()
            else None,
            "dft_hardware_deployment_recommendation_readiness.json"
            if (run_dir / "dft_hardware_deployment_recommendation_readiness.json").exists()
            else None,
            "dft_hardware_deployment_decision_packet.json"
            if (run_dir / "dft_hardware_deployment_decision_packet.json").exists()
            else None,
        ],
        "selected_recommendation_status": selected_status,
        "status": deployment_recommendations.get("status", "blocked_no_hardware_ppa_deployment_recommendations"),
        "recommendation_scope": deployment_recommendations.get(
            "recommendation_scope",
            "fpga_asic_hardware_ppa_only_not_full_scf_winner",
        ),
        "hardware_winner_resolution_eligible": bool(
            deployment_recommendations.get("hardware_winner_resolution_eligible", False)
        ),
        "resolved_recommendation_count": int(
            deployment_recommendations.get("resolved_recommendation_count", 0) or 0
        ),
        "recommendations": deployment_recommendations.get("recommendations", {}),
        "target_scoped_recommendation_sections": report.get(
            "target_scoped_recommendation_sections",
            {},
        ),
        "deployment_readiness": report.get(
            "dft_hardware_deployment_recommendation_readiness",
            {},
        ),
        "deployment_decision_packet": report.get(
            "dft_hardware_deployment_decision_packet",
            {},
        ),
        "decision_support": {
            "status": dft_deployment_decision_support.get("status"),
            "present": bool(dft_deployment_decision_support.get("present", False)),
            "current_best_available": bool(
                dft_deployment_decision_support.get("current_best_available", False)
            ),
            "target_feasibility_ready": bool(
                dft_deployment_decision_support.get("target_feasibility_ready", False)
            ),
            "recommendations": dft_deployment_decision_support.get("recommendations", {}),
            "full_scf_numerical_gate": dft_deployment_decision_support.get(
                "full_scf_numerical_gate",
                {},
            ),
            "release_completion_gates": dft_deployment_decision_support.get(
                "release_completion_gates",
                {},
            ),
            "target_reconciliation_workplan": dft_deployment_decision_support.get(
                "target_reconciliation_workplan",
                {},
            ),
            "coordination_blockers": dft_deployment_decision_support.get(
                "coordination_blockers",
                [],
            ),
            "hardware_eligibility_blockers": dft_deployment_decision_support.get(
                "hardware_eligibility_blockers",
                [],
            ),
            "blocker_report_source_producer_artifact_refs": dft_deployment_decision_support.get(
                "blocker_report_source_producer_artifact_refs",
                {},
            ),
            "blocker_report_source_producer_artifact_ref_count": dft_deployment_decision_support.get(
                "blocker_report_source_producer_artifact_ref_count",
                0,
            ),
            "blocker_report_source_lane_summary": dft_deployment_decision_support.get(
                "blocker_report_source_lane_summary",
                {},
            ),
            "blocker_report_source_lanes": dft_deployment_decision_support.get(
                "blocker_report_source_lanes",
                [],
            ),
            "blocker_report_source_producer_artifact_rationale": dft_deployment_decision_support.get(
                "blocker_report_source_producer_artifact_rationale",
                "",
            ),
        },
        "trusted_winner": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Step5 deployment recommendations are coordination/planning artifacts. "
            "They are hardware-PPA scoped and cannot mark a full-SCF trusted winner "
            "or deliverable completion."
        ),
    })
    _write_json(run_dir / "trusted_ranking.json", {
        "schema_version": "dse.step5.trusted_ranking.v1",
        "generated_at": _now_iso(),
        "source_step4_artifacts": ["verdict.json", "claim_validation.json"],
        "ranking_scope": (
            "hardware_ppa_only"
            if hardware_ppa_sidecar_scope
            else "generic_step5"
        ),
        "dft_hardware_ppa_ranking": "dft_hardware_ppa_ranking.json"
        if (run_dir / "dft_hardware_ppa_ranking.json").exists()
        else None,
        "dft_architecture_winner_resolution": "dft_architecture_winner_resolution.json"
        if (run_dir / "dft_architecture_winner_resolution.json").exists()
        else None,
        "dft_candidate_specific_ppa_provenance_audit": "dft_candidate_specific_ppa_provenance_audit.json"
        if (run_dir / "dft_candidate_specific_ppa_provenance_audit.json").exists()
        else None,
        "dft_hardware_deployment_target_selection": "dft_hardware_deployment_target_selection.json"
        if (run_dir / "dft_hardware_deployment_target_selection.json").exists()
        else None,
        "deployment_recommendations": deployment_recommendations,
        "dft_hardware_ppa_ranking": _report_artifact_ref(
            report, "dft_hardware_ppa_ranking", "dft_hardware_ppa_ranking.json", run_dir=run_dir
        ),
        "dft_architecture_winner_resolution": _report_artifact_ref(
            report,
            "dft_architecture_winner_resolution",
            "dft_architecture_winner_resolution.json",
            run_dir=run_dir,
        ),
        "dft_deployment_comparator": _report_artifact_ref(
            report, "dft_deployment_comparator", "dft_deployment_comparator.json", run_dir=run_dir
        ),
        "dft_deployment_selector": _report_artifact_ref(
            report, "dft_deployment_selector", "dft_deployment_selector.json", run_dir=run_dir
        ),
        "dft_deployment_decision_summary": _report_artifact_ref(
            report,
            "dft_deployment_decision_summary",
            "dft_deployment_decision_summary.json",
            run_dir=run_dir,
        ),
        "dft_evidence_ledger": _report_artifact_ref(
            report,
            "dft_evidence_ledger",
            "per_candidate_evidence_ledger.json",
            run_dir=run_dir,
        ),
        "dft_trial_state_ledger": _report_artifact_ref(
            report, "dft_trial_state_ledger", "dft_trial_state_ledger.json", run_dir=run_dir
        ),
        "dft_trial_transition_report": _report_artifact_ref(
            report, "dft_trial_state_ledger", "dft_trial_transition_report.json", run_dir=run_dir
        ),
        "dft_trial_artifact_refs": _report_artifact_ref(
            report, "dft_trial_state_ledger", "dft_trial_artifact_refs.json", run_dir=run_dir
        ),
        "dft_candidate_binding_map": _report_artifact_ref(
            report, "dft_candidate_binding_map", "dft_candidate_binding_map.json", run_dir=run_dir
        ),
        "dft_l4_goal_binding": _report_artifact_ref(
            report, "dft_l4_goal_binding", "dft_l4_goal_binding.json", run_dir=run_dir
        ),
        "dft_l4_current_candidate_queue": _report_artifact_ref(
            report, "dft_l4_goal_binding", "dft_l4_current_candidate_queue.json", run_dir=run_dir
        ),
        "dft_audit_semantic_closure": _report_artifact_ref(
            report, "dft_audit_semantic_closure", "dft_audit_semantic_closure.json", run_dir=run_dir
        ),
        "dft_candidate_specific_ppa_provenance_audit": _report_artifact_ref(
            report,
            "dft_candidate_specific_ppa_provenance",
            "dft_candidate_specific_ppa_provenance_audit.json",
            run_dir=run_dir,
        ),
        "trusted_ranking": report.get("trusted_ranking", []),
    })
    _write_json(run_dir / "pareto_frontier.json", {
        "schema_version": "dse.step5.pareto_frontier.v1",
        "generated_at": _now_iso(),
        "source_step4_artifacts": ["verdict.json", "claim_validation.json"],
        "frontier_scope": (
            "hardware_ppa_only"
            if hardware_ppa_sidecar_scope
            else "generic_step5"
        ),
        "dft_hardware_ppa_pareto_frontier": _report_artifact_ref(
            report, "dft_hardware_ppa_ranking", "dft_hardware_ppa_pareto_frontier.json", run_dir=run_dir
        ),
        "dft_deployment_decision_summary": _report_artifact_ref(
            report,
            "dft_deployment_decision_summary",
            "dft_deployment_decision_summary.json",
            run_dir=run_dir,
        ),
        "dft_evidence_ledger": _report_artifact_ref(
            report,
            "dft_evidence_ledger",
            "per_candidate_evidence_ledger.json",
            run_dir=run_dir,
        ),
        "dft_trial_state_ledger": _report_artifact_ref(
            report, "dft_trial_state_ledger", "dft_trial_state_ledger.json", run_dir=run_dir
        ),
        "dft_candidate_binding_map": _report_artifact_ref(
            report, "dft_candidate_binding_map", "dft_candidate_binding_map.json", run_dir=run_dir
        ),
        "dft_l4_goal_binding": _report_artifact_ref(
            report, "dft_l4_goal_binding", "dft_l4_goal_binding.json", run_dir=run_dir
        ),
        "dft_l4_current_candidate_queue": _report_artifact_ref(
            report, "dft_l4_goal_binding", "dft_l4_current_candidate_queue.json", run_dir=run_dir
        ),
        "dft_audit_semantic_closure": _report_artifact_ref(
            report, "dft_audit_semantic_closure", "dft_audit_semantic_closure.json", run_dir=run_dir
        ),
        "pareto_alternatives": report.get("pareto_alternatives", []),
    })
    return {
        "final_report_json": "final_report.json",
        "final_report_markdown": "final_report.md",
        "campaign_summary": "campaign_summary.json",
        "trusted_ranking": "trusted_ranking.json",
        "pareto_frontier": "pareto_frontier.json",
        "deployment_recommendations": "deployment_recommendations.json",
        "requirement_evidence_matrix": "requirement_evidence_matrix.json",
        "requirement_evidence_matrix_markdown": "requirement_evidence_matrix.md",
    }


def validate_report_claims(report: Mapping[str, Any], run_dir: Path) -> Dict[str, Any]:
    """Compatibility validator for report-shaped claim payloads.

    The newer report path validates explicit claim lists with ``validate_claims``.
    Some tests and downstream scripts still pass a complete report object and
    expect a compact ``errors``/``warnings`` contract.  Keep this wrapper
    conservative so predicted-only or low-fidelity winners remain rejected even
    when a caller has not built a full evidence index.
    """
    run_dir = Path(run_dir)
    errors: List[str] = []
    warnings: List[str] = []
    claims = report.get("claims", []) or []
    if not isinstance(claims, list):
        errors.append("claims must be a list")
        claims = []

    trusted_claim_count = 0
    winner_claim_types = {"best_architecture", "selected_recommendation", "pareto_frontier"}
    for idx, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            errors.append(f"claim[{idx}] is not an object")
            continue
        claim_id = str(claim.get("claim_id", f"claim[{idx}]"))
        claim_type = str(claim.get("claim_type", ""))
        predicted_only = bool(claim.get("predicted_only", False))
        blocked = bool(claim.get("blocked", False)) or str(claim.get("status", "")).lower() == "blocked"
        trusted = bool(claim.get("trusted", False))
        backend = _claim_backend(claim)
        fidelity = _claim_fidelity(claim)
        evidence_ids = _claim_evidence_ids(claim)

        if predicted_only and claim_type in winner_claim_types:
            errors.append(f"{claim_id}: predicted-only candidate cannot be a winner/Pareto claim")
        if trusted:
            trusted_claim_count += 1
            package = report.get("workload", {}) if isinstance(report.get("workload", {}), Mapping) else {}
            if package.get("claim_boundary") and package.get("claim_boundary") not in {"full_workload", "full", "end_to_end"}:
                errors.append(f"{claim_id}: trusted claim cannot use reduced/diagnostic workload boundary {package.get('claim_boundary')}")
            lowering = package.get("graph_lowering", {}) if isinstance(package.get("graph_lowering", {}), Mapping) else {}
            if lowering and lowering.get("full_workload_eligible") is False:
                errors.append(f"{claim_id}: trusted claim requires full-workload eligible graph lowering")
            if predicted_only:
                errors.append(f"{claim_id}: trusted claim cannot be predicted_only")
            if blocked:
                errors.append(f"{claim_id}: trusted claim cannot be blocked")
            if backend not in TRUSTED_BACKENDS:
                errors.append(f"{claim_id}: trusted claim backend must be SystemC or gem5+SystemC")
            if fidelity in PREDICTED_FIDELITIES:
                errors.append(f"{claim_id}: trusted claim cannot use low-fidelity source")
            if not evidence_ids:
                errors.append(f"{claim_id}: trusted claim must list evidence_ids")
        for evidence_id in evidence_ids:
            rel = Path(str(evidence_id))
            if rel.is_absolute() or ".." in rel.parts:
                errors.append(f"{claim_id}: evidence id must be a run-local relative path: {evidence_id}")
            elif not (run_dir / rel).exists():
                errors.append(f"{claim_id}: evidence id does not resolve to a file: {evidence_id}")

    selected = report.get("selected_recommendation", {}) or {}
    if isinstance(selected, Mapping) and selected.get("status") == "selected":
        evidence_ids = _claim_evidence_ids(selected)
        if selected.get("predicted_only"):
            errors.append("selected_recommendation: predicted-only candidate cannot be selected")
        if selected.get("backend") not in TRUSTED_BACKENDS:
            errors.append("selected_recommendation: backend must be SystemC or gem5+SystemC")
        if not evidence_ids:
            errors.append("selected_recommendation: selected design requires evidence_ids")
        for evidence_id in evidence_ids:
            rel = Path(str(evidence_id))
            if rel.is_absolute() or ".." in rel.parts:
                errors.append(f"selected_recommendation: evidence id must be a run-local relative path: {evidence_id}")
            elif not (run_dir / rel).exists():
                errors.append(f"selected_recommendation: evidence id does not resolve: {evidence_id}")
    else:
        warnings.append("No comparative selected recommendation emitted; report is single-run evidence only.")

    search_admission = report.get("search_admission_validation", {})
    if isinstance(search_admission, Mapping) and search_admission.get("present"):
        if search_admission.get("valid") is not True:
            errors.append("search_admission_validation: failed control-plane validation blocks trusted final search/admission claims")
        if search_admission.get("execution_allowed") is True:
            errors.append("search_admission_validation: campaign plan must not directly allow execution")
        if search_admission.get("trusted_final_claim") is True:
            errors.append("search_admission_validation: must not set trusted_final_claim true")
        if search_admission.get("release_completion_eligible") is True:
            errors.append("search_admission_validation: must not set release_completion_eligible true")
        if search_admission.get("hidden_evidence_fanout_allowed") is True:
            errors.append("search_admission_validation: must not set hidden_evidence_fanout_allowed true")
        if search_admission.get("broad_evidence_run") is True:
            errors.append("search_admission_validation: must not set broad_evidence_run true")
        if search_admission.get("top_k_queue_provenance_only") is False:
            errors.append("search_admission_validation: must not set top_k_queue_provenance_only false")
        scope_consensus = search_admission.get("scope_consensus", {})
        if isinstance(scope_consensus, Mapping) and scope_consensus.get("valid") is not True:
            errors.append("search_admission_validation: Campaign/Trial scope consensus must pass")
        recomputed_queue_validation = search_admission.get("step3_admission_queue_recomputed_validation", {})
        if (
            isinstance(recomputed_queue_validation, Mapping)
            and recomputed_queue_validation
            and recomputed_queue_validation.get("valid") is not True
        ):
            errors.append("search_admission_validation: recomputed Step3 admission queue validation must pass")

    deployment_recommendations = report.get("deployment_recommendations", {})
    if isinstance(deployment_recommendations, Mapping):
        if deployment_recommendations.get("trusted_winner") is True:
            errors.append("deployment_recommendations: must not set trusted_winner true")
        if deployment_recommendations.get("trusted_final_claim") is True:
            errors.append("deployment_recommendations: must not set trusted_final_claim true")
        if deployment_recommendations.get("deliverable_complete") is True:
            errors.append("deployment_recommendations: must not set deliverable_complete true")
        recommendations = deployment_recommendations.get("recommendations", {})
        if isinstance(recommendations, Mapping):
            for deployment, recommendation in recommendations.items():
                if not isinstance(recommendation, Mapping):
                    continue
                prefix = f"deployment_recommendations.{deployment}"
                if recommendation.get("trusted_winner") is True:
                    errors.append(f"{prefix}: must not set trusted_winner true")
                if recommendation.get("trusted_final_claim") is True:
                    errors.append(f"{prefix}: must not set trusted_final_claim true")
                if recommendation.get("deliverable_complete") is True:
                    errors.append(f"{prefix}: must not set deliverable_complete true")

    target_sections = report.get("target_scoped_recommendation_sections", {})
    if isinstance(target_sections, Mapping):
        for target, section in target_sections.items():
            if not isinstance(section, Mapping):
                continue
            prefix = f"target_scoped_recommendation_sections.{target}"
            if section.get("trusted_winner") is True:
                errors.append(f"{prefix}: must not set trusted_winner true")
            if section.get("trusted_final_claim") is True:
                errors.append(f"{prefix}: must not set trusted_final_claim true")
            if section.get("deliverable_complete") is True:
                errors.append(f"{prefix}: must not set deliverable_complete true")

    dft_deployment_support = report.get("dft_deployment_decision_support", {})
    if isinstance(dft_deployment_support, Mapping):
        if dft_deployment_support.get("trusted_winner") is True:
            errors.append("dft_deployment_decision_support: must not set trusted_winner true")
        if dft_deployment_support.get("trusted_final_claim") is True:
            errors.append("dft_deployment_decision_support: must not set trusted_final_claim true")
        if dft_deployment_support.get("deliverable_complete") is True:
            errors.append("dft_deployment_decision_support: must not set deliverable_complete true")
        support_recommendations = dft_deployment_support.get("recommendations", {})
        if isinstance(support_recommendations, Mapping):
            for deployment, recommendation in support_recommendations.items():
                if not isinstance(recommendation, Mapping):
                    continue
                prefix = f"dft_deployment_decision_support.{deployment}"
                if recommendation.get("trusted_winner") is True:
                    errors.append(f"{prefix}: must not set trusted_winner true")
                if recommendation.get("trusted_final_claim") is True:
                    errors.append(f"{prefix}: must not set trusted_final_claim true")
                if recommendation.get("deliverable_complete") is True:
                    errors.append(f"{prefix}: must not set deliverable_complete true")
        for workplan_key in ("target_reconciliation_workplan",):
            workplan = dft_deployment_support.get(workplan_key, {})
            if not isinstance(workplan, Mapping):
                continue
            prefix = f"dft_deployment_decision_support.{workplan_key}"
            forbidden_true_fields = {
                "execution_allowed",
                "trusted_winner",
                "trusted_final_claim",
                "numerical_correctness_claim_eligible",
                "hardware_completion_eligible",
                "release_completion_eligible",
                "deliverable_complete",
            }
            for field in sorted(forbidden_true_fields):
                if bool(workplan.get(field, False)):
                    errors.append(f"{prefix}: must not set {field} true")
            for idx, item in enumerate(workplan.get("work_items", []) or []):
                if not isinstance(item, Mapping):
                    errors.append(f"{prefix}.work_items[{idx}] is not an object")
                    continue
                for field in sorted(forbidden_true_fields):
                    if bool(item.get(field, False)):
                        errors.append(f"{prefix}.work_items[{idx}]: must not set {field} true")

    dft_deployment_readiness = report.get("dft_hardware_deployment_recommendation_readiness", {})
    if isinstance(dft_deployment_readiness, Mapping):
        if dft_deployment_readiness.get("trusted_final_claim") is True:
            errors.append("dft_hardware_deployment_recommendation_readiness: must not set trusted_final_claim true")
        if dft_deployment_readiness.get("deliverable_complete") is True:
            errors.append("dft_hardware_deployment_recommendation_readiness: must not set deliverable_complete true")
        if dft_deployment_readiness.get("can_name_final_recommendation") is True:
            errors.append(
                "dft_hardware_deployment_recommendation_readiness: must not set can_name_final_recommendation true"
            )
        if dft_deployment_readiness.get("can_name_targeted_deployment_recommendation") is True:
            errors.append(
                "dft_hardware_deployment_recommendation_readiness: must not set can_name_targeted_deployment_recommendation true"
            )
        forbidden_report_true_fields = {
            "trusted_final_claim",
            "deliverable_complete",
            "release_completion_eligible",
            "hardware_completion_eligible",
            "numerical_correctness_claim_eligible",
        }
        for section_name in ("full_scf_numerical_gate", "release_completion_gates"):
            section = dft_deployment_readiness.get(section_name, {})
            if isinstance(section, Mapping):
                for field in sorted(forbidden_report_true_fields):
                    if bool(section.get(field, False)):
                        errors.append(
                            "dft_hardware_deployment_recommendation_readiness."
                            f"{section_name}: must not set {field} true"
                        )
        gate = dft_deployment_readiness.get("full_scf_numerical_gate", {})
        if isinstance(gate, Mapping) and bool(gate.get("passed", False)):
            if gate.get("comparison_artifact_passed") is not True:
                errors.append(
                    "dft_hardware_deployment_recommendation_readiness."
                    "full_scf_numerical_gate: passed requires comparison_artifact_passed true"
                )
            if gate.get("validation_passed") is not True:
                errors.append(
                    "dft_hardware_deployment_recommendation_readiness."
                    "full_scf_numerical_gate: passed requires validation_passed true"
                )
            if gate.get("status_artifact_passed") is not True:
                errors.append(
                    "dft_hardware_deployment_recommendation_readiness."
                    "full_scf_numerical_gate: passed requires status_artifact_passed true"
                )
        release_gates = dft_deployment_readiness.get("release_completion_gates", {})
        if isinstance(release_gates, Mapping):
            gate_passed = bool(gate.get("passed", False)) if isinstance(gate, Mapping) else False
            if release_gates.get("full_scf_numerical_passed") is True and not gate_passed:
                errors.append(
                    "dft_hardware_deployment_recommendation_readiness."
                    "release_completion_gates: full_scf_numerical_passed requires full_scf_numerical_gate.passed true"
                )
            workplan_for_gate = dft_deployment_readiness.get("full_scf_numerical_closure_workplan", {})
            if isinstance(workplan_for_gate, Mapping):
                workplan_required = bool(workplan_for_gate.get("required", False))
                if release_gates.get("full_scf_numerical_closure_required") is False and workplan_required:
                    errors.append(
                        "dft_hardware_deployment_recommendation_readiness."
                        "release_completion_gates: full_scf_numerical_closure_required false conflicts with required workplan"
                    )
        workplan = dft_deployment_readiness.get("full_scf_numerical_closure_workplan", {})
        if isinstance(workplan, Mapping):
            forbidden_true_fields = {
                "execution_allowed",
                "trusted_accelerated_numeric_source",
                "trusted_winner",
                "trusted_final_claim",
                "numerical_correctness_claim_eligible",
                "hardware_completion_eligible",
                "release_completion_eligible",
                "deliverable_complete",
            }
            for field in sorted(forbidden_true_fields):
                if bool(workplan.get(field, False)):
                    errors.append(
                        "dft_hardware_deployment_recommendation_readiness."
                        f"full_scf_numerical_closure_workplan: must not set {field} true"
                    )
            for idx, item in enumerate(workplan.get("work_items", []) or []):
                if not isinstance(item, Mapping):
                    errors.append(
                        "dft_hardware_deployment_recommendation_readiness."
                        f"full_scf_numerical_closure_workplan.work_items[{idx}] is not an object"
                    )
                    continue
                for field in sorted(forbidden_true_fields):
                    if bool(item.get(field, False)):
                        errors.append(
                            "dft_hardware_deployment_recommendation_readiness."
                            "full_scf_numerical_closure_workplan."
                            f"work_items[{idx}]: must not set {field} true"
                        )
        for section_name in (
            "full_scf_qe_accelerated_numeric_requirements",
            "full_scf_qe_baseline_materialization",
            "full_scf_trusted_evidence_execution_queue",
            "full_scf_trusted_evidence_batch_plan",
        ):
            section = dft_deployment_readiness.get(section_name, {})
            if isinstance(section, Mapping):
                for field in (
                    "trusted_final_claim",
                    "hardware_completion_eligible",
                    "release_completion_eligible",
                    "deliverable_complete",
                ):
                    if bool(section.get(field, False)):
                        errors.append(
                            "dft_hardware_deployment_recommendation_readiness."
                            f"{section_name}: must not set {field} true"
                        )

    dft_decision_packet = report.get("dft_hardware_deployment_decision_packet", {})
    if isinstance(dft_decision_packet, Mapping):
        if dft_decision_packet.get("can_name_targeted_deployment_recommendation") is True:
            errors.append(
                "dft_hardware_deployment_decision_packet: must not set can_name_targeted_deployment_recommendation true"
            )
        if dft_decision_packet.get("can_name_final_recommendation") is True:
            errors.append("dft_hardware_deployment_decision_packet: must not set can_name_final_recommendation true")
        if dft_decision_packet.get("trusted_final_claim") is True:
            errors.append("dft_hardware_deployment_decision_packet: must not set trusted_final_claim true")
        if dft_decision_packet.get("deliverable_complete") is True:
            errors.append("dft_hardware_deployment_decision_packet: must not set deliverable_complete true")
        packet_gate = dft_decision_packet.get("full_scf_numerical_gate", {})
        if (
            dft_decision_packet.get("full_scf_numerical_gate_passed") is True
            and isinstance(packet_gate, Mapping)
            and packet_gate.get("passed") is not True
        ):
            errors.append(
                "dft_hardware_deployment_decision_packet: full_scf_numerical_gate_passed requires full_scf_numerical_gate.passed true"
            )

    full_scf_accounting = report.get("full_scf_accounting_completeness", {})
    if isinstance(full_scf_accounting, Mapping):
        for field in ("trusted_final_claim", "deliverable_complete"):
            if bool(full_scf_accounting.get(field, False)):
                errors.append(
                    f"full_scf_accounting_completeness: must not set {field} true"
                )
        status = full_scf_accounting.get("status")
        complete = bool(full_scf_accounting.get("complete", False))
        projection_only = bool(full_scf_accounting.get("projection_only", False))
        blockers = full_scf_accounting.get("blocker_ids", [])
        blockers = blockers if isinstance(blockers, list) else []
        if complete and status != "complete":
            errors.append(
                "full_scf_accounting_completeness: complete true requires status complete"
            )
        if status == "complete" and blockers:
            errors.append(
                "full_scf_accounting_completeness: status complete requires no blockers"
            )
        if status != "complete" and not projection_only:
            errors.append(
                "full_scf_accounting_completeness: incomplete accounting must remain projection_only true"
            )
        if status == "complete":
            for section_name in (
                "host_retained_stages",
                "runtime_overheads",
                "accelerated_major_kernels",
            ):
                section = full_scf_accounting.get(section_name, {})
                if isinstance(section, Mapping) and section.get("missing_ids"):
                    errors.append(
                        "full_scf_accounting_completeness: "
                        f"{section_name} status complete conflicts with missing_ids"
                    )
            abi = full_scf_accounting.get("descriptor_runtime_abi", {})
            if isinstance(abi, Mapping) and not bool(abi.get("complete", False)):
                errors.append(
                    "full_scf_accounting_completeness: status complete requires descriptor_runtime_abi.complete true"
                )
        attachment = full_scf_accounting.get("qe_baseline_row_accounting_attachment", {})
        if isinstance(attachment, Mapping):
            for field in (
                "claim_upgrade_allowed",
                "hardware_completion_eligible",
                "trusted_final_claim",
                "deliverable_complete",
            ):
                if bool(attachment.get(field, False)):
                    errors.append(
                        "full_scf_accounting_completeness."
                        f"qe_baseline_row_accounting_attachment: must not set {field} true"
                    )

    attachment = report.get("qe_baseline_row_accounting_attachment", {})
    if isinstance(attachment, Mapping):
        for field in (
            "claim_upgrade_allowed",
            "hardware_completion_eligible",
            "trusted_final_claim",
            "deliverable_complete",
        ):
            if bool(attachment.get(field, False)):
                errors.append(
                    f"qe_baseline_row_accounting_attachment: must not set {field} true"
                )

    major_kernel_matrix = report.get("major_kernel_matrix", {})
    if isinstance(major_kernel_matrix, Mapping):
        status = str(major_kernel_matrix.get("status") or "")
        trusted = bool(major_kernel_matrix.get("trusted", False))
        missing_kernel_ids = major_kernel_matrix.get("missing_kernel_ids", [])
        missing_kernel_ids = missing_kernel_ids if isinstance(missing_kernel_ids, list) else []
        rows = major_kernel_matrix.get("rows", [])
        rows = rows if isinstance(rows, list) else []
        present_row_count = major_kernel_matrix.get("present_row_count")
        expected_row_count = major_kernel_matrix.get("expected_row_count")
        if status == "passed" and missing_kernel_ids:
            errors.append("major_kernel_matrix: status passed requires no missing_kernel_ids")
        if trusted and missing_kernel_ids:
            errors.append("major_kernel_matrix: trusted true requires no missing_kernel_ids")
        if status == "passed" and present_row_count is not None and expected_row_count is not None:
            if int(present_row_count) != int(expected_row_count):
                errors.append("major_kernel_matrix: status passed requires present_row_count == expected_row_count")
        if status == "passed" and not rows:
            errors.append("major_kernel_matrix: status passed requires visible rows")
        if status == "passed":
            expected_ids = list(MAJOR_SCF_ACCELERATED_KERNEL_IDS)
            observed_ids = [
                str(row.get("kernel_id"))
                for row in rows
                if isinstance(row, Mapping) and row.get("kernel_id")
            ]
            if len(observed_ids) != len(expected_ids) or set(observed_ids) != set(expected_ids):
                errors.append("major_kernel_matrix: status passed requires all eight major-kernel rows")

    return {
        "schema_version": "dse.claim_validation.compat.v1",
        "generated_at": _now_iso(),
        "passed": not errors,
        "trusted_claim_count": trusted_claim_count,
        "errors": errors,
        "warnings": warnings,
    }


def generate_final_report_artifacts(
    run_dir: Path,
    *,
    claims: Optional[Iterable[Mapping[str, Any]]] = None,
    artifact_paths: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Compatibility wrapper that writes report artifacts and returns summary keys."""
    paths = write_final_report_artifacts(run_dir, claims=claims, artifact_paths=artifact_paths)
    validation = _load_json(Path(run_dir) / "claim_validation.json")
    return {
        **paths,
        "report_path": str(Path(run_dir) / paths["final_report_json"]),
        "markdown_path": str(Path(run_dir) / paths["final_report_markdown"]),
        "validation_path": str(Path(run_dir) / paths["claim_validation"]),
        "validation_passed": bool(validation.get("passed", False)),
        "trusted_claim_count": len(validation.get("trusted_claim_ids", []) or []),
    }
