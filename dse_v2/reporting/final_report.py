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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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
DFT_FULL_SCF_HYBRID_ARTIFACT_NAMES = {
    "full_scf_accelerator_descriptor.json",
    "full_scf_runtime_schedule.json",
    "full_scf_data_residency_plan.json",
    "full_scf_correctness_report.json",
    "full_scf_ppa_summary.json",
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
DFT_L4_GOAL_BINDING_ARTIFACT_NAMES = {
    "dft_l4_goal_binding.json",
    "dft_l4_goal_binding_validation.json",
    "dft_l4_goal_binding_status.json",
}
DFT_AUDIT_SEMANTIC_CLOSURE_ARTIFACT_NAMES = {
    "dft_audit_semantic_closure.json",
}

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
    paths.extend(DFT_FULL_SCF_HYBRID_ARTIFACT_NAMES)
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
    paths.extend(DFT_L4_GOAL_BINDING_ARTIFACT_NAMES)
    paths.extend(DFT_AUDIT_SEMANTIC_CLOSURE_ARTIFACT_NAMES)

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


def _candidate_from_run(
    *,
    design_point: Mapping[str, Any],
    architecture: Mapping[str, Any],
    mapping: Mapping[str, Any],
    simulation_result: Mapping[str, Any],
    validation: Mapping[str, Any],
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
    return {
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
    return payload


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
    required_present = all(
        artifact_refs[name]["exists"]
        for name in DFT_FULL_SCF_HYBRID_ARTIFACT_NAMES
    )
    present = bool(loaded) or ledger_present
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
        "descriptor_id": descriptor.get("descriptor_id") or ledger_bundle.get("descriptor_id"),
        "candidate_id": descriptor.get("candidate_id") or runtime_schedule.get("candidate_id") or ledger_bundle.get("candidate_id"),
        "campaign_id": descriptor.get("campaign_id") or runtime_schedule.get("campaign_id") or ledger_bundle.get("campaign_id"),
        "workload_run_id": descriptor.get("workload_run_id") or runtime_schedule.get("workload_run_id") or ledger_bundle.get("workload_run_id"),
        "trial_id": descriptor.get("trial_id") or runtime_schedule.get("trial_id") or ledger_bundle.get("trial_id"),
        "prototype_boundary": descriptor.get("prototype_boundary") or ledger_bundle.get("prototype_boundary"),
        "device_residency": descriptor.get("device_residency") or data_residency.get("device_residency") or ledger_bundle.get("device_residency"),
        "completion_claim": False,
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
            "accelerated_kernel_ids": runtime_schedule.get(
                "accelerated_kernel_ids",
                descriptor.get("hardware_acceleration_claim_scope", []),
            ),
            "host_bound_phase_ids": runtime_schedule.get(
                "host_bound_phase_ids",
                descriptor.get("host_bound_phase_scope", []),
            ),
            "runtime_overhead_ids": runtime_schedule.get(
                "runtime_overhead_ids",
                descriptor.get("runtime_overhead_scope", []),
            ),
            "host_orchestrated": bool(runtime_schedule.get("host_orchestrated", False)),
        },
        "cost_model": descriptor.get("cost_model", ppa_summary.get("cost_model", {})),
        "trusted_final_claim": False,
        "claim_boundary": (
            "DFT full-SCF evaluated-hybrid artifacts are Step5-visible accounting "
            "and schedule evidence.  They do not prove full-SCF device residency, "
            "numerical correctness, or FPGA/ASIC PPA closure unless the separate "
            "hard gates pass."
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

    present = bool(loaded)
    ledger = loaded.get("per_candidate_evidence_ledger.json", {})
    release_report = loaded.get("release_report.json", {})
    eda = loaded.get("eda_all_candidate_evidence.json", {})
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
    raw_availability_completion_claim = ic_eda_availability.get("completion_claim")
    availability_payload_claim_boundary_valid = bool(
        ic_eda_availability
        and raw_availability_completion_claim == "availability_only_not_kernel_ppa"
        and ic_eda_availability.get("kernel_ppa_evidence") is not True
        and ic_eda_availability.get("hardware_completion_eligible") is not True
        and ic_eda_availability.get("deliverable_complete") is not True
    )
    eda_summary = {
        "artifact": artifact_refs.get("eda_all_candidate_evidence.json", {}),
        "status": eda.get("status"),
        "tool_availability_status": eda.get("tool_availability_status"),
        "major_kernel_matrix_status": eda.get("major_kernel_matrix_status"),
        "major_kernel_matrix_trusted": bool(eda.get("major_kernel_matrix_trusted", False)),
        "attached_hardware_evidence_structurally_ready": bool(
            eda.get("attached_hardware_evidence_structurally_ready", False)
        ),
        "hardware_completion_eligible": bool(eda.get("hardware_completion_eligible", False)),
        "ic_eda_tool_availability": eda.get("ic_eda_tool_availability"),
        "ic_eda_tool_availability_resolved_path": (
            str(ic_eda_availability_path) if ic_eda_availability_path else None
        ),
        "ic_eda_tool_availability_payload_status": ic_eda_availability.get("status"),
        "ic_eda_tool_availability_all_required_tools_available": ic_eda_availability.get(
            "all_required_tools_available"
        ),
        "ic_eda_tool_availability_required_tools": ic_eda_availability.get("required_tools", []),
        "ic_eda_tool_availability_tool_count": len(ic_eda_availability.get("tool_rows", []) or [])
        if isinstance(ic_eda_availability.get("tool_rows", []), list)
        else 0,
        "ic_eda_tool_availability_raw_attempt_count": len(ic_eda_availability.get("raw_attempts", []) or [])
        if isinstance(ic_eda_availability.get("raw_attempts", []), list)
        else 0,
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
        "dft_hardware_evidence_matrix": eda.get("dft_hardware_evidence_matrix"),
        "claim_boundary": (
            (eda.get("hardware_evidence_attachment_policy", {}) or {}).get("claim_boundary")
            if isinstance(eda.get("hardware_evidence_attachment_policy", {}), Mapping)
            else eda.get("claim_boundary")
        ),
    }
    return {
        "schema_version": "dse.final_report.dft_evidence_ledger.v1",
        "present": present,
        "status": (
            "audit_artifacts_present"
            if present
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
    validation = loaded.get("dft_trial_state_ledger_validation.json", {})
    present = bool(ledger)
    blocked_trial_count = int(ledger.get("blocked_trial_count", 0) or 0) if ledger else 0
    rejected_trial_count = int(ledger.get("rejected_trial_count", 0) or 0) if ledger else 0
    deliverable_complete = bool(ledger.get("deliverable_complete", False))
    completion_eligible = bool(ledger.get("completion_eligible", False))
    status = (
        "fail_closed_trial_ledger_present"
        if present and validation.get("valid", True) is True
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
        "completion_eligible": completion_eligible,
        "deliverable_complete": deliverable_complete,
        "validation": {
            "present": bool(validation),
            "valid": validation.get("valid"),
            "error_count": len(validation.get("errors", []) or []) if validation else None,
            "warning_count": len(validation.get("warnings", []) or []) if validation else None,
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
    deliverable_complete = bool(binding_map.get("deliverable_complete", False))
    completion_eligible = bool(binding_map.get("completion_eligible", False))
    validation_valid = validation.get("valid")
    status = (
        "fail_closed_candidate_binding_map_present"
        if present and validation_valid is True and not deliverable_complete and not completion_eligible
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
        "adjudication_result": gate_adjudication.get("adjudication_result"),
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
    present = bool(binding)
    current = binding.get("current_goal_binding", {}) if isinstance(binding.get("current_goal_binding", {}), Mapping) else {}
    l4_matrix = binding.get("l4_matrix", {}) if isinstance(binding.get("l4_matrix", {}), Mapping) else {}
    row_level_proofs = (
        binding.get("row_level_proofs", {})
        if isinstance(binding.get("row_level_proofs", {}), Mapping)
        else {}
    )
    final_closure_eligible = bool(binding.get("final_closure_eligible", False))
    deliverable_complete = bool(binding.get("deliverable_complete", False))
    validation_valid = validation.get("valid")
    status = (
        "fail_closed_l4_goal_binding_present"
        if present and validation_valid is True and not deliverable_complete
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
            "warning_count": len(validation.get("warnings", []) or []) if validation else None,
            "warnings": validation.get("warnings", []) if validation else [],
        },
        "blockers": list(binding.get("blockers", []) or []) if isinstance(binding.get("blockers", []), list) else [],
        "status_artifact": {
            "status": status_artifact.get("status"),
            "binding_status": status_artifact.get("binding_status"),
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
    for label, ref_any in source_artifacts.items():
        ref = ref_any if isinstance(ref_any, Mapping) else {}
        if ref.get("required") is True:
            required_source_count += 1
            if ref.get("exists") is not True:
                missing_required_sources.append(str(label))
            if ref.get("sha256"):
                hashed_required_source_count += 1
    source_hash_backed = bool(
        closure.get("source_hash_backed") is True
        and required_source_count > 0
        and hashed_required_source_count == required_source_count
        and not missing_required_sources
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
    simulation_result = _load_json(run_dir / "simulation_result.json")
    simulator_consistency_check = _load_json(run_dir / "simulator_consistency_check.json")
    numerical_validation = simulator_consistency_check or _load_json(run_dir / "numerical_validation.json")
    blockers = _load_json(run_dir / "gem5_systemc_blockers.json")
    codesign_candidate = _load_json(run_dir / "codesign_candidate.json")
    codesign_verdict = _load_json(run_dir / "codesign_verdict.json")
    simulation_samples = _load_json(run_dir / "mapping_simulation_samples.json")
    feedback_state = _load_json(run_dir / "mapping_feedback_state.json")
    convergence_status = _load_json(run_dir / "convergence_status.json")
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
    low_fidelity_screening = _low_fidelity_screening_section(
        run_dir,
        evidence_index=evidence_index,
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
    dft_l4_goal_binding = _dft_l4_goal_binding_section(
        run_dir,
        evidence_index,
    )
    dft_audit_semantic_closure = _dft_audit_semantic_closure_section(
        run_dir,
        evidence_index,
    )
    dft_full_scf_hybrid = _dft_full_scf_hybrid_section(
        run_dir,
        evidence_index,
        ledger_bundle=dft_evidence_ledger.get("full_scf_hybrid_bundle", {}),
    )

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
    candidate = _candidate_from_run(
        design_point=design_point,
        architecture=architecture,
        mapping=mapping,
        simulation_result=simulation_result,
        validation=trusted_validation,
    )

    sample_records = list(simulation_samples.get("samples", []) or [])
    trusted_sample_records = [sample for sample in sample_records if sample.get("trusted_final_eligible")]
    if len(trusted_sample_records) > 1:
        trusted_ranking = [
            {
                "design_point_id": str(sample.get("candidate_id")),
                "architecture_id": architecture.get("architecture_id", design_point.get("system_architecture", {}).get("system_id")),
                "mapping_id": mapping.get("mapping_id"),
                "backend": sample.get("backend"),
                "status": sample.get("status"),
                "trusted_scope": "bounded multi-candidate high-fidelity ranking; not global convergence unless convergence_status proves it",
                "metrics": sample.get("metrics", {}),
                "validation": {"trusted": True, "validation_status": "trusted"},
                "evidence_ids": list(sample.get("evidence_ids", []) or []),
            }
            for sample in sorted(
                trusted_sample_records,
                key=lambda item: float((item.get("metrics", {}) or {}).get("latency_ms") or float("inf")),
            )
        ]
    else:
        trusted_ranking = [candidate] if trusted_validation.get("trusted") else []
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

    limitations = list(verdict.get("evidence_gaps", []) or [])
    if blockers.get("blockers"):
        limitations.append("gem5+SystemC L4 binding is untrusted for this run.")
    if codesign_verdict and not codesign_verdict.get("trusted_for_codesign_ranking", False):
        limitations.append("Software-visible co-design claim is blocked until codesign_verdict.json and gem5_l4_proof.json pass.")
    if not trusted_ranking:
        limitations.append("No trusted final ranking is available from the cited evidence.")
    if convergence_status:
        limitations.extend(str(item) for item in convergence_status.get("limitations", []) or [])
        if convergence_status.get("stop_reason") == "budget_exhausted" and not convergence_status.get("converged"):
            limitations.append("Feedback loop stopped by budget exhaustion; this is not proof of global convergence.")
    importer_payload = workload_package.get("importer", {}) if isinstance(workload_package.get("importer", {}), Mapping) else {}
    if workload_package and importer_payload.get("claim_boundary") not in {"full_workload", "full", "end_to_end"}:
        limitations.append("WorkloadPackage claim boundary is reduced/diagnostic; trusted final claims are not allowed for this run.")
    if graph_lowering and not graph_lowering.get("full_workload_eligible", False):
        limitations.append("Graph lowering report is not full-workload eligible; final trusted claims are blocked for this run.")
    if low_fidelity_screening.get("present"):
        limitations.append("Step2 L1/L2 screening is low-fidelity candidate-generation evidence only; it is excluded from trusted final ranking.")
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
        "low_fidelity_screening": low_fidelity_screening,
        "dft_evidence_ledger": dft_evidence_ledger,
        "dft_trial_state_ledger": dft_trial_state_ledger,
        "dft_candidate_binding_map": dft_candidate_binding_map,
        "dft_hardware_completion_workplan": dft_hardware_completion_workplan,
        "dft_hardware_closure_shards": dft_hardware_closure_shards,
        "dft_hardware_closure_packets": dft_hardware_closure_packets,
        "dft_hardware_closure_candidate_bundles": dft_hardware_closure_candidate_bundles,
        "dft_hardware_closure_unit_provenance": dft_hardware_closure_unit_provenance,
        "dft_hardware_closure_source_flow_plan": dft_hardware_closure_source_flow_plan,
        "dft_hardware_closure_raw_stage_materialization": dft_hardware_closure_raw_stage_materialization,
        "dft_hardware_closure_raw_transcript_registration": dft_hardware_closure_raw_transcript_registration,
        "dft_hardware_closure_evidence_intake": dft_hardware_closure_evidence_intake,
        "dft_hardware_closure_adjudication": dft_hardware_closure_adjudication,
        "dft_hardware_closure_parsed_evidence": dft_hardware_closure_parsed_evidence,
        "dft_hardware_closure_parser_run": dft_hardware_closure_parser_run,
        "dft_hardware_closure_gate_adjudication": dft_hardware_closure_gate_adjudication,
        "dft_hardware_closure_release_gate": dft_hardware_closure_release_gate,
        "dft_l4_goal_binding": dft_l4_goal_binding,
        "dft_audit_semantic_closure": dft_audit_semantic_closure,
        "dft_full_scf_evaluated_hybrid": dft_full_scf_hybrid,
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
        ),
        "trusted_ranking": trusted_ranking,
        "predicted_only_candidates": predicted_only_candidates,
        "blocked_or_untrusted": blocked_or_untrusted,
        "pareto_alternatives": [],
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

    dft_ledger = report.get("dft_evidence_ledger", {})
    dft_ledger = dft_ledger if isinstance(dft_ledger, Mapping) else {}
    eda_summary = dft_ledger.get("eda_summary", {}) if isinstance(dft_ledger.get("eda_summary", {}), Mapping) else {}
    ledger_full_scf = (
        dft_ledger.get("full_scf_hybrid_bundle", {})
        if isinstance(dft_ledger.get("full_scf_hybrid_bundle", {}), Mapping)
        else {}
    )
    lines.extend([
        "",
        "## DFT Evidence Ledger",
        f"- Present: `{dft_ledger.get('present')}`",
        f"- Deliverable complete: `{dft_ledger.get('deliverable_complete')}`",
        f"- EDA status: `{eda_summary.get('status')}`",
        f"- IC/EDA availability status: `{eda_summary.get('tool_availability_status')}`",
        f"- IC/EDA availability payload status: `{eda_summary.get('ic_eda_tool_availability_payload_status')}`",
        f"- IC/EDA availability completion claim: `{eda_summary.get('ic_eda_tool_availability_completion_claim')}`",
        f"- IC/EDA availability kernel PPA evidence: `{eda_summary.get('ic_eda_tool_availability_kernel_ppa_evidence')}`",
        f"- IC/EDA availability raw attempts: `{eda_summary.get('ic_eda_tool_availability_raw_attempt_count')}`",
        f"- Major-kernel matrix status: `{eda_summary.get('major_kernel_matrix_status')}`",
        f"- Major-kernel matrix trusted: `{eda_summary.get('major_kernel_matrix_trusted')}`",
        f"- Hardware completion eligible: `{eda_summary.get('hardware_completion_eligible')}`",
        f"- Full-SCF hybrid bundle status: `{ledger_full_scf.get('status')}`",
        f"- Full-SCF hybrid bundle completion claim: `{ledger_full_scf.get('completion_claim')}`",
        "- Boundary: this citation does not upgrade Step4/Step5 trust, does not prove full-SCF completion, and does not create FPGA/ASIC PPA claims.",
    ])
    if not dft_ledger.get("present"):
        lines.append("- No DFT evidence ledger artifacts were indexed for this Step5 run.")

    dft_trial_ledger = report.get("dft_trial_state_ledger", {})
    dft_trial_ledger = dft_trial_ledger if isinstance(dft_trial_ledger, Mapping) else {}
    validation = (
        dft_trial_ledger.get("validation", {})
        if isinstance(dft_trial_ledger.get("validation", {}), Mapping)
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
    hybrid_schedule = (
        dft_hybrid.get("schedule_summary", {})
        if isinstance(dft_hybrid.get("schedule_summary", {}), Mapping)
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
        "- Boundary: evaluated-hybrid artifacts expose schedule/cost accounting only; they do not prove device residency, numerical correctness, or FPGA/ASIC PPA closure.",
    ])
    if not dft_hybrid.get("present"):
        lines.append("- No full-SCF evaluated-hybrid artifact bundle was indexed for this Step5 run.")

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
    _write_json(run_dir / "final_report.json", report)
    _write_text(run_dir / "final_report.md", render_markdown_report(report))
    campaign_summary = {
        "schema_version": "dse.step5.campaign_summary.v1",
        "generated_at": _now_iso(),
        "run_metadata": report.get("run_metadata", {}),
        "selected_recommendation": report.get("selected_recommendation", {}),
        "trusted_ranking_count": len(report.get("trusted_ranking", []) or []),
        "limitations": report.get("limitations", []),
        "dft_evidence_ledger_summary": report.get("dft_evidence_ledger", {}),
        "dft_trial_state_ledger_summary": report.get("dft_trial_state_ledger", {}),
        "dft_candidate_binding_map_summary": report.get("dft_candidate_binding_map", {}),
        "dft_hardware_completion_workplan_summary": report.get("dft_hardware_completion_workplan", {}),
        "dft_hardware_closure_shards_summary": report.get("dft_hardware_closure_shards", {}),
        "dft_hardware_closure_packets_summary": report.get("dft_hardware_closure_packets", {}),
        "dft_hardware_closure_candidate_bundles_summary": report.get("dft_hardware_closure_candidate_bundles", {}),
        "dft_hardware_closure_unit_provenance_summary": report.get("dft_hardware_closure_unit_provenance", {}),
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
        "dft_l4_goal_binding_summary": report.get("dft_l4_goal_binding", {}),
        "dft_audit_semantic_closure_summary": report.get("dft_audit_semantic_closure", {}),
        "dft_full_scf_evaluated_hybrid_summary": report.get("dft_full_scf_evaluated_hybrid", {}),
        "source_step4_artifacts": ["verdict.json", "claim_validation.json", "evidence_requirements.json"],
    }
    _write_json(run_dir / "campaign_summary.json", campaign_summary)
    _write_json(run_dir / "trusted_ranking.json", {
        "schema_version": "dse.step5.trusted_ranking.v1",
        "generated_at": _now_iso(),
        "source_step4_artifacts": ["verdict.json", "claim_validation.json"],
        "trusted_ranking": report.get("trusted_ranking", []),
    })
    _write_json(run_dir / "pareto_frontier.json", {
        "schema_version": "dse.step5.pareto_frontier.v1",
        "generated_at": _now_iso(),
        "source_step4_artifacts": ["verdict.json", "claim_validation.json"],
        "pareto_alternatives": report.get("pareto_alternatives", []),
    })
    return {
        "final_report_json": "final_report.json",
        "final_report_markdown": "final_report.md",
        "campaign_summary": "campaign_summary.json",
        "trusted_ranking": "trusted_ranking.json",
        "pareto_frontier": "pareto_frontier.json",
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
