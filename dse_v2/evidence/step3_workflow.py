#!/usr/bin/env python3
"""Step3 simulation workflow consuming Step2 handoff artifacts.

Step3 is the boundary after architecture/mapping promotion.  It reloads the
persisted Step2 artifacts from disk, refuses unpromoted or diagnostic handoffs,
runs the selected SystemC simulation, and emits only Step3 execution artifacts.
Step4 adjudication and Step5 reporting are explicit downstream APIs.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from dse_v2.backends.gem5_systemc_adapter import Gem5SystemCClosureAdapter
from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend
from dse_v2.codesign import (
    CODESIGN_L4_EVIDENCE_ARTIFACTS,
    CODESIGN_STEP2_ARTIFACTS,
    validate_codesign_artifacts,
)
from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.core.workload.package import WorkloadPackage
from dse_v2.core.workload.workflows import DIAGNOSTIC_CLAIM_BOUNDARIES
from dse_v2.evidence.full_flow import write_full_flow_evidence
from dse_v2.mapping.step2_workflow import (
    STEP2_CANDIDATE_QUEUE_ARTIFACTS,
    STEP2_LOW_FIDELITY_ARTIFACTS,
    STEP2_LOW_FIDELITY_ARTIFACT_KEYS,
    design_point_from_dict,
    validate_step2_artifacts,
)

STEP2_INPUT_ARTIFACTS = [
    "step2_status.json",
    "step2_artifact_validation.json",
    "workload_package.json",
    "workload_graph.json",
    "graph_lowering_report.json",
    "executable_graph.json",
    "architecture_catalog.json",
    "architecture.json",
    "design_point.json",
    "mapping.json",
    "mapping_promotion_decision.json",
    "mapping_legality_matrix.json",
    "mapping_seed_set.json",
    "mapping_candidate_records.json",
    "mapping_selected_record.json",
    "mapping_simulation_samples.json",
    "mapping_feedback_state.json",
    "convergence_status.json",
] + STEP2_LOW_FIDELITY_ARTIFACTS + CODESIGN_STEP2_ARTIFACTS + STEP2_CANDIDATE_QUEUE_ARTIFACTS + ["domain_policy_hints.json"]

STEP2_OPTIONAL_INPUT_ARTIFACTS = set(STEP2_CANDIDATE_QUEUE_ARTIFACTS + ["domain_policy_hints.json"])

STEP3_EVIDENCE_ARTIFACTS = [
    "simulation_request.json",
    "simulation_result.json",
    "simulation_result.raw.json",
    "systemc_stdout.log",
    "systemc_stderr.log",
    "phase_breakdown.csv",
    "resource_summary.csv",
    "data_movement_summary.csv",
] + [
    artifact for artifact in CODESIGN_L4_EVIDENCE_ARTIFACTS if artifact != "codesign_verdict.json"
] + [
    "generic_accel_command_descriptor.json",
    "gem5.log",
]


@dataclass
class Step3WorkflowResult:
    """Summary of a Step3 simulation/evidence attempt."""

    status: str
    trusted_for_final_ranking: bool
    run_dir: Path
    step2_dir: Path
    artifacts: Dict[str, Any] = field(default_factory=dict)
    artifact_paths: Dict[str, str] = field(default_factory=dict)
    reasons: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "trusted_for_final_ranking": self.trusted_for_final_ranking,
            "run_dir": str(self.run_dir),
            "step2_dir": str(self.step2_dir),
            "artifact_paths": dict(self.artifact_paths),
            "reasons": list(self.reasons),
        }


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _reason(reason_id: str, detail: str, **extra: Any) -> Dict[str, Any]:
    payload = {"reason_id": reason_id, "detail": detail}
    payload.update(extra)
    return payload


def _copy_step2_inputs(step2_dir: Path, run_dir: Path) -> List[str]:
    copied: List[str] = []
    target_root = run_dir / "step2_input"
    target_root.mkdir(parents=True, exist_ok=True)
    for artifact in STEP2_INPUT_ARTIFACTS:
        source = step2_dir / artifact
        if not source.exists():
            continue
        target = target_root / artifact
        shutil.copy2(source, target)
        copied.append(str(Path("step2_input") / artifact))
    return copied


def _load_step2_handoff(step2_dir: Path) -> Dict[str, Any]:
    return {
        "step2_status": _load_json(step2_dir / "step2_status.json"),
        "step2_artifact_validation": _load_json(step2_dir / "step2_artifact_validation.json"),
        "workload_package": _load_json(step2_dir / "workload_package.json"),
        "workload_graph": _load_json(step2_dir / "workload_graph.json"),
        "graph_lowering_report": _load_json(step2_dir / "graph_lowering_report.json"),
        "executable_graph": _load_json(step2_dir / "executable_graph.json"),
        "architecture": _load_json(step2_dir / "architecture.json"),
        "design_point": _load_json(step2_dir / "design_point.json"),
        "mapping_promotion_decision": _load_json(step2_dir / "mapping_promotion_decision.json"),
        "mapping_selected_record": _load_json(step2_dir / "mapping_selected_record.json"),
        "mapping_feedback_state": _load_json(step2_dir / "mapping_feedback_state.json"),
        "convergence_status": _load_json(step2_dir / "convergence_status.json"),
        "domain_policy_hints": _load_json(step2_dir / "domain_policy_hints.json"),
        "architecture_candidate_set": _load_json(step2_dir / "architecture_candidate_set.json"),
        "trial_state_ledger": _load_json(step2_dir / "trial_state_ledger.json"),
        "step3_simulation_queue": _load_json(step2_dir / "step3_simulation_queue.json"),
        "l1_evaluation_result": _load_json(step2_dir / "l1_evaluation_result.json"),
        "l1_promotion_decision": _load_json(step2_dir / "l1_promotion_decision.json"),
        "l2_evaluation_result": _load_json(step2_dir / "l2_evaluation_result.json"),
        "l2_promotion_decision": _load_json(step2_dir / "l2_promotion_decision.json"),
        "low_fidelity_summary": _load_json(step2_dir / "low_fidelity_screening_summary.json"),
        "codesign_candidate": _load_json(step2_dir / "codesign_candidate.json"),
        "software_stack_config": _load_json(step2_dir / "software_stack_config.json"),
        "compiler_lowering": _load_json(step2_dir / "compiler_lowering.json"),
        "runtime_schedule": _load_json(step2_dir / "runtime_schedule.json"),
        "descriptor_protocol": _load_json(step2_dir / "descriptor_protocol.json"),
        "memory_policy": _load_json(step2_dir / "memory_policy.json"),
        "codesign_artifact_validation": _load_json(step2_dir / "codesign_artifact_validation.json"),
    }


def _low_fidelity_handoff_reasons(step2_dir: Path, handoff: Mapping[str, Any], promotion: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if not promotion.get("promoted_for_simulation", False):
        return []

    low_section = promotion.get("low_fidelity_screening", {}) if isinstance(promotion.get("low_fidelity_screening", {}), Mapping) else {}
    required_artifacts = [
        str(artifact)
        for artifact in low_section.get("required_artifacts", STEP2_LOW_FIDELITY_ARTIFACTS)
    ]
    reasons: List[Dict[str, Any]] = []
    missing = [artifact for artifact in required_artifacts if not (step2_dir / artifact).exists()]
    if missing:
        reasons.append(_reason(
            "missing_low_fidelity_artifacts",
            "promoted Step2 handoff is missing required L1/L2 screening artifacts",
            missing_artifacts=missing,
        ))

    summary = handoff.get("low_fidelity_summary", {}) if isinstance(handoff.get("low_fidelity_summary", {}), Mapping) else {}
    if not summary:
        reasons.append(_reason(
            "missing_low_fidelity_summary",
            "promoted Step2 handoff requires low_fidelity_screening_summary.json",
        ))
    elif not summary.get("passed", False):
        reasons.append(_reason(
            "low_fidelity_screening_failed",
            "Step2 low-fidelity screening summary did not pass the pre-Step3 gate",
            blockers=list(summary.get("blockers", []) or []),
        ))

    for key in STEP2_LOW_FIDELITY_ARTIFACT_KEYS:
        payload = handoff.get(key, {}) if isinstance(handoff.get(key, {}), Mapping) else {}
        if not payload:
            continue
        if payload.get("trusted_final_claim"):
            reasons.append(_reason(
                "invalid_low_fidelity_trusted_final_claim",
                "L1/L2 Step2 handoff artifact cannot claim trusted final results",
                artifact_key=key,
            ))
        if payload.get("low_fidelity_role") != "candidate_generator_only":
            reasons.append(_reason(
                "invalid_low_fidelity_role",
                "L1/L2 Step2 handoff artifact must remain candidate-generation evidence only",
                artifact_key=key,
                low_fidelity_role=payload.get("low_fidelity_role"),
            ))
    return reasons


def _step3_queue_handoff_reasons(handoff: Mapping[str, Any], promotion: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Validate Step2's explicit queue contract before Step3 execution."""

    queue = handoff.get("step3_simulation_queue", {}) if isinstance(handoff.get("step3_simulation_queue", {}), Mapping) else {}
    entries = [entry for entry in queue.get("entries", []) or [] if isinstance(entry, Mapping)]
    selected = handoff.get("mapping_selected_record", {}) if isinstance(handoff.get("mapping_selected_record", {}), Mapping) else {}
    design_point = handoff.get("design_point", {}) if isinstance(handoff.get("design_point", {}), Mapping) else {}
    architecture = handoff.get("architecture", {}) if isinstance(handoff.get("architecture", {}), Mapping) else {}
    promoted = bool(promotion.get("promoted_for_simulation", False))
    reasons: List[Dict[str, Any]] = []
    if queue.get("trusted_final_claim"):
        reasons.append(_reason("invalid_step3_queue_trusted_final_claim", "Step2 queue cannot claim trusted final results"))
    if not promoted:
        scheduled = [
            entry
            for entry in entries
            if str(entry.get("queue_state", "")).startswith("scheduled_for_simulation")
        ]
        if scheduled:
            reasons.append(_reason(
                "step3_queue_schedules_unpromoted_candidate",
                "Step3 queue cannot schedule entries when mapping_promotion_decision.promoted_for_simulation is false",
                scheduled_count=len(scheduled),
            ))
        return reasons

    expected_design_point_id = str(design_point.get("design_point_id") or "")
    expected_mapping_id = str(promotion.get("mapping_id") or design_point.get("config", {}).get("mapping_id") or "")
    expected_architecture_id = str(promotion.get("architecture_id") or architecture.get("architecture_id") or "")
    expected_mapping_candidate_id = str(promotion.get("candidate_id") or selected.get("candidate_id") or "")
    matching_entries = [
        entry
        for entry in entries
        if str(entry.get("design_point_id") or "") == expected_design_point_id
        and str(entry.get("mapping_id") or "") == expected_mapping_id
        and str(entry.get("architecture_id") or "") == expected_architecture_id
        and str(entry.get("mapping_candidate_id") or "") == expected_mapping_candidate_id
    ]
    if not matching_entries:
        reasons.append(_reason(
            "missing_matching_step3_queue_entry",
            "Promoted Step2 handoff requires a Step3 queue entry matching design_point_id, mapping_id, architecture_id, and mapping candidate.",
            expected_design_point_id=expected_design_point_id,
            expected_mapping_id=expected_mapping_id,
            expected_architecture_id=expected_architecture_id,
            expected_mapping_candidate_id=expected_mapping_candidate_id,
        ))
        return reasons
    scheduled_entries = [
        entry
        for entry in matching_entries
        if str(entry.get("queue_state", "")).startswith("scheduled_for_simulation")
    ]
    if not scheduled_entries:
        reasons.append(_reason(
            "step3_queue_entry_not_scheduled",
            "Matching Step3 queue entry is not scheduled for simulation.",
            queue_states=[str(entry.get("queue_state", "")) for entry in matching_entries],
        ))
    for entry in matching_entries:
        if entry.get("trusted_final_claim"):
            reasons.append(_reason(
                "invalid_step3_queue_entry_trusted_final_claim",
                "Step3 queue entries cannot claim trusted final results",
                queue_entry_id=entry.get("queue_entry_id"),
            ))
    return reasons


def validate_step2_handoff_for_step3(step2_dir: Path) -> Dict[str, Any]:
    """Return whether a persisted Step2 handoff may enter Step3 simulation."""
    step2_dir = Path(step2_dir)
    handoff = _load_step2_handoff(step2_dir)
    reasons: List[Dict[str, Any]] = []

    promotion = handoff["mapping_promotion_decision"]
    co_design = promotion.get("co_design", {}) if isinstance(promotion.get("co_design", {}), Mapping) else {}
    low_fidelity_section = promotion.get("low_fidelity_screening", {}) if isinstance(promotion.get("low_fidelity_screening", {}), Mapping) else {}
    low_fidelity_required = bool(promotion.get("promoted_for_simulation", False) or low_fidelity_section.get("required_for_step3", False))
    codesign_present = any((step2_dir / artifact).exists() for artifact in CODESIGN_STEP2_ARTIFACTS)
    required_input_artifacts = [
        artifact
        for artifact in STEP2_INPUT_ARTIFACTS
        if artifact != "step2_artifact_validation.json"
        and artifact not in STEP2_OPTIONAL_INPUT_ARTIFACTS
        and (artifact not in STEP2_LOW_FIDELITY_ARTIFACTS or low_fidelity_required)
        and (artifact not in CODESIGN_STEP2_ARTIFACTS or co_design.get("l4_required") or codesign_present)
    ]
    missing = [artifact for artifact in required_input_artifacts if not (step2_dir / artifact).exists()]
    if missing:
        reasons.append(_reason("missing_step2_artifacts", "required Step2 artifacts are absent", missing_artifacts=missing))

    if not handoff["workload_package"]:
        reasons.append(_reason("missing_workload_package", "workload_package.json is required for Step3"))
    if not handoff["executable_graph"]:
        reasons.append(_reason("missing_executable_graph", "executable_graph.json is required for Step3 simulation"))
    if not handoff["design_point"]:
        reasons.append(_reason("missing_design_point", "design_point.json is required for Step3 simulation"))

    if not promotion.get("promoted_for_simulation", False):
        reasons.append(_reason(
            "step2_not_promoted_for_simulation",
            "Step2 promotion decision did not allow this candidate to enter Step3 simulation",
            promotion_reasons=promotion.get("reasons", []),
        ))
    if promotion.get("trusted_final_claim"):
        reasons.append(_reason("invalid_step2_trusted_final_claim", "Step2 promotion cannot claim trusted final results"))
    reasons.extend(_low_fidelity_handoff_reasons(step2_dir, handoff, promotion))
    reasons.extend(_step3_queue_handoff_reasons(handoff, promotion))

    package_payload = handoff["workload_package"]
    importer = package_payload.get("importer", {}) if isinstance(package_payload.get("importer", {}), Mapping) else {}
    claim_boundary = str(importer.get("claim_boundary", "full_workload"))
    if claim_boundary in DIAGNOSTIC_CLAIM_BOUNDARIES:
        reasons.append(_reason(
            "diagnostic_claim_boundary",
            "diagnostic, smoke, synthetic, trace-only, or reduced workload cannot enter trusted Step3 simulation",
            claim_boundary=claim_boundary,
        ))

    lowering = handoff["graph_lowering_report"]
    if lowering.get("status") != "lowered" or not lowering.get("full_workload_eligible", False):
        reasons.append(_reason(
            "unsupported_or_reduced_lowering",
            "graph lowering is not full-workload eligible for Step3 trusted evidence",
            lowering_status=lowering.get("status"),
            full_workload_eligible=lowering.get("full_workload_eligible", False),
            unsupported_constructs=lowering.get("unsupported_constructs", []),
        ))

    selected = handoff["mapping_selected_record"]
    if selected.get("violations"):
        reasons.append(_reason("illegal_selected_mapping", "selected mapping has legality violations", violations=selected.get("violations", [])))

    dynamic_validation = validate_step2_artifacts({
        "architecture": handoff["architecture"],
        "design_point": handoff["design_point"],
        "workload_graph": handoff["workload_graph"],
        "executable_graph": handoff["executable_graph"],
        "selected_record": selected,
        "promotion_decision": promotion,
        "architecture_candidate_set": handoff["architecture_candidate_set"],
        "trial_state_ledger": handoff["trial_state_ledger"],
        "step3_simulation_queue": handoff["step3_simulation_queue"],
        "feedback_state": handoff["mapping_feedback_state"],
        "l1_evaluation_result": handoff["l1_evaluation_result"],
        "l1_promotion_decision": handoff["l1_promotion_decision"],
        "l2_evaluation_result": handoff["l2_evaluation_result"],
        "l2_promotion_decision": handoff["l2_promotion_decision"],
        "low_fidelity_summary": handoff["low_fidelity_summary"],
        "system_architecture": (handoff["design_point"].get("system_architecture", {}) if isinstance(handoff["design_point"], Mapping) else {}),
    })
    if not dynamic_validation.get("valid", False):
        reasons.append(_reason(
            "step2_artifact_validation_failed",
            "Step2 artifact references do not validate immediately before Step3",
            validation=dynamic_validation,
        ))

    codesign_candidate = handoff.get("codesign_candidate", {})
    if codesign_candidate:
        codesign_validation = validate_codesign_artifacts({
            "codesign_candidate": codesign_candidate,
            "software_stack_config": handoff.get("software_stack_config", {}),
            "compiler_lowering": handoff.get("compiler_lowering", {}),
            "runtime_schedule": handoff.get("runtime_schedule", {}),
            "descriptor_protocol": handoff.get("descriptor_protocol", {}),
            "memory_policy": handoff.get("memory_policy", {}),
        })
        if not codesign_validation.get("valid", False):
            reasons.append(_reason(
                "codesign_artifact_validation_failed",
                "Co-design candidate artifacts are not replayable for Step3",
                validation=codesign_validation,
            ))
    else:
        if co_design.get("l4_required"):
            reasons.append(_reason(
                "missing_codesign_candidate",
                "Step2 promotion requires L4 co-design proof but codesign_candidate.json is missing",
            ))

    return {
        "schema_version": "dse.step3.step2_handoff_validation.v1",
        "valid": not reasons,
        "reasons": reasons,
        "handoff": handoff,
        "dynamic_step2_artifact_validation": dynamic_validation,
    }


def _write_blocked_status(
    *,
    run_dir: Path,
    step2_dir: Path,
    status: str,
    reasons: List[Mapping[str, Any]],
    copied_step2_inputs: List[str],
    backend: str,
    evidence_mode: str,
) -> Step3WorkflowResult:
    payload = {
        "schema_version": "dse.step3.status.v1",
        "status": status,
        "trusted_for_final_ranking": False,
        "backend": backend,
        "evidence_mode": evidence_mode,
        "step2_dir": str(step2_dir),
        "copied_step2_inputs": copied_step2_inputs,
        "reasons": [dict(reason) for reason in reasons],
        "full_flow_simulation_attempted": False,
    }
    _write_json(run_dir / "step3_status.json", payload)
    return Step3WorkflowResult(
        status=status,
        trusted_for_final_ranking=False,
        run_dir=run_dir,
        step2_dir=step2_dir,
        artifacts={"step3_status": payload},
        artifact_paths={"step3_status": "step3_status.json"},
        reasons=[dict(reason) for reason in reasons],
    )


def run_step3_simulation_evidence_workflow(
    step2_dir: Path,
    *,
    output_dir: Optional[Path] = None,
    backend: str = "systemc",
    evidence_mode: str = "summary",
    simulator_path: Optional[Path] = None,
    gem5_binary: Optional[Path] = None,
    gem5_config: Optional[Path] = None,
    driver_binary: Optional[Path] = None,
    gem5_cpu_type: str = "atomic",
    gem5_max_ticks: int = 10_000_000_000,
    allow_local_transport_fallback: bool = False,
    timeout: int = 300,
    cli_command: Optional[List[str]] = None,
) -> Step3WorkflowResult:
    """Consume Step2 artifacts, run SystemC, and write Step3 evidence artifacts."""
    step2_dir = Path(step2_dir).resolve()
    run_dir = Path(output_dir).resolve() if output_dir is not None else step2_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    copied_step2_inputs = _copy_step2_inputs(step2_dir, run_dir)

    handoff_validation = validate_step2_handoff_for_step3(step2_dir)
    if not handoff_validation.get("valid", False):
        return _write_blocked_status(
            run_dir=run_dir,
            step2_dir=step2_dir,
            status="blocked_before_simulation",
            reasons=list(handoff_validation.get("reasons", [])),
            copied_step2_inputs=copied_step2_inputs,
            backend=backend,
            evidence_mode=evidence_mode,
        )

    handoff = handoff_validation["handoff"]
    package = WorkloadPackage.from_dict(handoff["workload_package"])
    source_graph = ComputeGraph.from_dict(handoff["workload_graph"])
    executable_graph = ComputeGraph.from_dict(handoff["executable_graph"])
    design_point = design_point_from_dict(handoff["design_point"])
    codesign_candidate = handoff.get("codesign_candidate", {}) if isinstance(handoff.get("codesign_candidate", {}), Mapping) else {}
    simulator = simulator_path or Path("model/generic_sim_backend/build/generic_sim")
    gsim = GenericSystemCBackend(
        executable_path=str(simulator),
        mode="standalone_systemc" if backend == "systemc" else backend,
    )

    request = gsim._build_request(design_point, executable_graph, workload_package=package, output_dir=run_dir)
    _write_json(run_dir / "simulation_request.json", request)

    if backend == "gem5_systemc":
        adapter = Gem5SystemCClosureAdapter(gsim)
        try:
            run = adapter.run_verified_l4(
                design_point=design_point,
                compute_graph=executable_graph,
                workload_package=package,
                output_dir=run_dir,
                gem5_binary=gem5_binary,
                gem5_config=gem5_config,
                driver_binary=driver_binary,
                simulator_binary=simulator,
                max_ticks=gem5_max_ticks,
                cpu_type=gem5_cpu_type,
                timeout=timeout,
                allow_local_transport_fallback=allow_local_transport_fallback,
            )
        except Exception as exc:
            reason = _reason("gem5_systemc_exception", str(exc))
            return _write_blocked_status(
                run_dir=run_dir,
                step2_dir=step2_dir,
                status="blocked_gem5_systemc_exception",
                reasons=[reason],
                copied_step2_inputs=copied_step2_inputs,
                backend=backend,
                evidence_mode=evidence_mode,
            )
        evidence = write_full_flow_evidence(
            run_dir=run_dir,
            backend=backend,
            evidence_mode=evidence_mode,
            design_point=design_point,
            compute_graph=source_graph,
            workload_package=package,
            simulation_request=run.get("request") or request,
            simulation_result=run.get("result"),
            simulator_cmd=[str(item) for item in run.get("cmd", [])],
            simulator_returncode=int(run.get("returncode", 2)),
            systemc_stdout=str(run.get("stdout", "")),
            systemc_stderr=str(run.get("stderr", "")),
            cli_command=cli_command or ["python3", "dse_v2/evidence/step3_workflow.py", "--step2-dir", str(step2_dir), "--backend", "gem5_systemc"],
            gem5_attempted=True,
            gem5_log=str(run.get("gem5_log", "")),
            gem5_source_artifacts=(run.get("gem5_l4_transport_proof") or {}).get("source_artifacts") if isinstance(run.get("gem5_l4_transport_proof"), Mapping) else None,
            extra_artifact_paths=copied_step2_inputs,
            codesign_candidate=codesign_candidate,
            emit_step4_artifacts=False,
            emit_step5_artifacts=False,
        )
    elif not gsim.executable_path.exists():
        reason = _reason("simulator_not_found", f"Simulator not found: {gsim.executable_path}")
        return _write_blocked_status(
            run_dir=run_dir,
            step2_dir=step2_dir,
            status="blocked_simulator_unavailable",
            reasons=[reason],
            copied_step2_inputs=copied_step2_inputs,
            backend=backend,
            evidence_mode=evidence_mode,
        )

    else:
        try:
            run = gsim.run_simulation(
                design_point,
                executable_graph,
                workload_package=package,
                output_dir=run_dir,
                timeout=timeout,
            )
        except Exception as exc:  # keep Step3 blocker structured; caller/tests inspect status.
            reason = _reason("simulation_exception", str(exc))
            return _write_blocked_status(
                run_dir=run_dir,
                step2_dir=step2_dir,
                status="blocked_simulation_exception",
                reasons=[reason],
                copied_step2_inputs=copied_step2_inputs,
                backend=backend,
                evidence_mode=evidence_mode,
            )

        evidence = write_full_flow_evidence(
            run_dir=run_dir,
            backend=backend,
            evidence_mode=evidence_mode,
            design_point=design_point,
            compute_graph=source_graph,
            workload_package=package,
            simulation_request=run.get("request") or request,
            simulation_result=run.get("result"),
            simulator_cmd=[str(item) for item in run.get("cmd", [])],
            simulator_returncode=int(run.get("returncode", 1)),
            systemc_stdout=str(run.get("stdout", "")),
            systemc_stderr=str(run.get("stderr", "")),
            cli_command=cli_command or ["python3", "dse_v2/evidence/step3_workflow.py", "--step2-dir", str(step2_dir)],
            extra_artifact_paths=copied_step2_inputs,
            codesign_candidate=codesign_candidate,
            emit_step4_artifacts=False,
            emit_step5_artifacts=False,
        )

    simulation_passed = bool(evidence.get("simulation_passed", False))
    trusted = False
    status = "simulation_completed" if simulation_passed else "simulation_completed_untrusted"
    reasons: List[Dict[str, Any]] = []
    if not simulation_passed:
        verdict = evidence.get("verdict", {}) if isinstance(evidence.get("verdict", {}), Mapping) else {}
        reasons.extend({"reason_id": "evidence_gap", "detail": str(gap)} for gap in verdict.get("evidence_gaps", []) or [])
        if not reasons:
            reasons.append(_reason("simulation_untrusted", "simulation completed but Step4 evidence gates have not passed"))

    status_payload = {
        "schema_version": "dse.step3.status.v1",
        "status": status,
        "trusted_for_final_ranking": trusted,
        "backend": backend,
        "evidence_mode": evidence_mode,
        "step2_dir": str(step2_dir),
        "copied_step2_inputs": copied_step2_inputs,
        "full_flow_simulation_attempted": True,
        "simulator_returncode": int(run.get("returncode", 1)),
        "simulation_request": "simulation_request.json",
        "simulation_result": "simulation_result.json",
        "downstream_steps": {
            "step4_adjudication": "run_step4_evidence_adjudication",
            "step5_reporting": "write_step5_report_artifacts",
        },
        "reasons": reasons,
    }
    _write_json(run_dir / "step3_status.json", status_payload)

    artifact_paths = {"step3_status": "step3_status.json"}
    for artifact in STEP3_EVIDENCE_ARTIFACTS:
        if (run_dir / artifact).exists():
            artifact_paths[artifact.removesuffix(".json").replace(".", "_")] = artifact
    return Step3WorkflowResult(
        status=status,
        trusted_for_final_ranking=trusted,
        run_dir=run_dir,
        step2_dir=step2_dir,
        artifacts={"step3_status": status_payload, "evidence": evidence},
        artifact_paths=artifact_paths,
        reasons=reasons,
    )
