#!/usr/bin/env python3
"""Step4 evidence adjudication over completed Step3 simulation outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.core.workload.package import WorkloadPackage
from dse_v2.dse.orchestrator import DesignPoint
from dse_v2.evidence.full_flow import write_full_flow_evidence
from dse_v2.mapping.step2_workflow import design_point_from_dict

STEP4_ADJUDICATION_ARTIFACTS = [
    "manifest.json",
    "artifact_manifest.json",
    "provenance.json",
    "verdict.json",
    "evidence_requirements.json",
    "claim_validation.json",
    "simulator_consistency_check.json",
    "timing_model_calibration.json",
    "calibration_record.json",
    "feedback_update.json",
    "gem5_l4_proof.json",
    "codesign_verdict.json",
]


@dataclass
class Step4AdjudicationResult:
    """Summary of a Step4 adjudication attempt."""

    status: str
    trusted_for_final_ranking: bool
    run_dir: Path
    artifact_paths: Dict[str, str] = field(default_factory=dict)
    reasons: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "trusted_for_final_ranking": self.trusted_for_final_ranking,
            "run_dir": str(self.run_dir),
            "artifact_paths": dict(self.artifact_paths),
            "reasons": list(self.reasons),
        }


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _reason(reason_id: str, detail: str, **extra: Any) -> Dict[str, Any]:
    payload = {"reason_id": reason_id, "detail": detail}
    payload.update(extra)
    return payload


def _step2_input_path(run_dir: Path, filename: str, step2_dir: Optional[Path]) -> Path:
    copied = run_dir / "step2_input" / filename
    if copied.exists():
        return copied
    if step2_dir is not None:
        return step2_dir / filename
    return copied


def run_step4_evidence_adjudication(
    step3_dir: Path,
    *,
    step2_dir: Optional[Path] = None,
    emit_step5_artifacts: bool = False,
) -> Step4AdjudicationResult:
    """Consume Step3 outputs and write Step4-owned adjudication artifacts.

    Step4 reconstructs the context from copied Step2 inputs plus Step3
    simulation artifacts.  It does not run simulation and does not write final
    reports unless the caller explicitly opts into the compatibility shortcut.
    """
    run_dir = Path(step3_dir).resolve()
    status_payload = _load_json(run_dir / "step3_status.json")
    resolved_step2_dir = Path(step2_dir).resolve() if step2_dir is not None else None
    if resolved_step2_dir is None and status_payload.get("step2_dir"):
        resolved_step2_dir = Path(str(status_payload["step2_dir"])).resolve()

    missing = [
        rel
        for rel in ["simulation_request.json", "simulation_result.json", "step3_status.json"]
        if not (run_dir / rel).exists()
    ]
    context_files = ["workload_package.json", "workload_graph.json", "design_point.json"]
    missing.extend(
        f"step2_input/{rel}"
        for rel in context_files
        if not _step2_input_path(run_dir, rel, resolved_step2_dir).exists()
    )
    if missing:
        return Step4AdjudicationResult(
            status="blocked_missing_step3_or_step2_context",
            trusted_for_final_ranking=False,
            run_dir=run_dir,
            reasons=[_reason("missing_context", "Step4 requires Step3 outputs and Step2 context", missing_artifacts=missing)],
        )

    package = WorkloadPackage.from_dict(_load_json(_step2_input_path(run_dir, "workload_package.json", resolved_step2_dir)))
    source_graph = ComputeGraph.from_dict(_load_json(_step2_input_path(run_dir, "workload_graph.json", resolved_step2_dir)))
    design_point: DesignPoint = design_point_from_dict(_load_json(_step2_input_path(run_dir, "design_point.json", resolved_step2_dir)))
    codesign_candidate = _load_json(_step2_input_path(run_dir, "codesign_candidate.json", resolved_step2_dir))
    raw_result = _load_json(run_dir / "simulation_result.raw.json") or _load_json(run_dir / "simulation_result.json")
    request = _load_json(run_dir / "simulation_request.json")
    stdout = (run_dir / "systemc_stdout.log").read_text(encoding="utf-8") if (run_dir / "systemc_stdout.log").exists() else ""
    stderr = (run_dir / "systemc_stderr.log").read_text(encoding="utf-8") if (run_dir / "systemc_stderr.log").exists() else ""
    gem5_log = (run_dir / "gem5.log").read_text(encoding="utf-8") if (run_dir / "gem5.log").exists() else None
    backend = str(status_payload.get("backend", raw_result.get("backend", "systemc")))
    evidence = write_full_flow_evidence(
        run_dir=run_dir,
        backend=backend,
        evidence_mode=str(status_payload.get("evidence_mode", "summary")),
        design_point=design_point,
        compute_graph=source_graph,
        workload_package=package,
        simulation_request=request,
        simulation_result=raw_result,
        simulator_cmd=[],
        simulator_returncode=int(status_payload.get("simulator_returncode", 0 if raw_result.get("status") == "passed" else 1)),
        systemc_stdout=stdout,
        systemc_stderr=stderr,
        cli_command=["python3", "-m", "dse_v2.evidence.step4_adjudication", str(run_dir)],
        gem5_attempted=backend == "gem5_systemc",
        gem5_log=gem5_log,
        extra_artifact_paths=[str(path.relative_to(run_dir)) for path in sorted((run_dir / "step2_input").glob("*.json"))]
        if (run_dir / "step2_input").exists()
        else [],
        codesign_candidate=codesign_candidate,
        emit_step4_artifacts=True,
        emit_step5_artifacts=emit_step5_artifacts,
    )
    trusted = bool(evidence.get("trusted_for_final_ranking", False))
    artifact_paths = {
        artifact.removesuffix(".json").replace(".", "_"): artifact
        for artifact in STEP4_ADJUDICATION_ARTIFACTS
        if (run_dir / artifact).exists()
    }
    return Step4AdjudicationResult(
        status="adjudicated" if trusted else "adjudicated_untrusted",
        trusted_for_final_ranking=trusted,
        run_dir=run_dir,
        artifact_paths=artifact_paths,
        reasons=[] if trusted else [_reason("untrusted_evidence", "Step4 adjudication did not pass all trusted final gates")],
    )

