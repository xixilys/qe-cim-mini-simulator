#!/usr/bin/env python3
"""First-stage DFT common-mode templates under the reference adapter boundary.

The objects in this module are deliberately *not* part of the domain-neutral
core schema.  They provide a small, reviewable DFT plugin contract that can
express the six first-stage common modes requested by the active DSE plan as
standardized workflow templates.  The templates are source/workflow facts only:
they do not choose mappings, schedules, runtime policies, descriptor protocols,
simulator verdicts, or hardware resources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Sequence

from dse_v2.reference_workloads.dft_workflow import (
    DftClaimEvidence,
    DftHotspotClaim,
    DftReviewGate,
    DftStage,
    DftStageDependency,
    DftWorkflowSpec,
)


DFT_CONFIG_SCHEMA = "dse.dft.config.v1"
DFT_MODE_TEMPLATE_SCHEMA = "dse.dft.mode_template.v1"
DFT_MODE_COVERAGE_SCHEMA = "dse.dft.first_stage_mode_coverage.v1"

FIRST_STAGE_DFT_MODE_IDS = (
    "scf_ground_state",
    "nscf_bands_dos",
    "relax_vc_relax",
    "aimd_md",
    "hybrid_exact_exchange",
    "postprocess_charge_density",
)

_NON_DECISION_NOTE = (
    "First-stage DFT mode templates are Step1 source/workflow facts only; "
    "they do not select mapping, placement, schedule, runtime policy, "
    "descriptor protocol, simulator verdict, or architecture resources."
)


@dataclass(frozen=True)
class DftConfig:
    """Stable DFT workload configuration record for a common-mode template."""

    mode_id: str
    source_software: str = "qe"
    workload_family: str = "dft"
    calculation_sequence: tuple[str, ...] = ()
    parameters: Dict[str, Any] = field(default_factory=dict)
    claim_boundary: str = "workflow_template"
    schema_version: str = DFT_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.mode_id not in FIRST_STAGE_DFT_MODE_IDS:
            raise ValueError(f"unsupported first-stage DFT mode: {self.mode_id}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode_id": self.mode_id,
            "workload_family": self.workload_family,
            "source_software": self.source_software,
            "calculation_sequence": list(self.calculation_sequence),
            "parameters": dict(self.parameters),
            "claim_boundary": self.claim_boundary,
            "non_decision_contract": _NON_DECISION_NOTE,
        }


@dataclass(frozen=True)
class DftModeStageTemplate:
    """One architecture-independent stage in a first-stage DFT mode."""

    stage_id: str
    stage_type: str
    source_program: str
    calculation_kind: str
    phase_ids: tuple[str, ...]
    input_artifacts: tuple[str, ...] = ()
    output_artifacts: tuple[str, ...] = ()
    hotspot_phase_ids: tuple[str, ...] = ()
    evidence_level: str = "template_static"
    confidence: str = "medium"
    coverage_level: str = "common_mode_template"
    notes: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "stage_type": self.stage_type,
            "source_program": self.source_program,
            "calculation_kind": self.calculation_kind,
            "phase_ids": list(self.phase_ids),
            "hotspot_phase_ids": list(self.hotspot_phase_ids),
            "input_artifacts": list(self.input_artifacts),
            "output_artifacts": list(self.output_artifacts),
            "evidence_level": self.evidence_level,
            "confidence": self.confidence,
            "coverage_level": self.coverage_level,
            "notes": list(self.notes),
            "non_decision_contract": _NON_DECISION_NOTE,
        }


@dataclass(frozen=True)
class DftModeTemplate:
    """Reviewable common-mode DFT workflow template."""

    mode_id: str
    display_name: str
    source_software: str
    calculation_sequence: tuple[str, ...]
    stages: tuple[DftModeStageTemplate, ...]
    required_input_kinds: tuple[str, ...]
    expected_output_kinds: tuple[str, ...]
    claim_boundary: str = "workflow_template"
    limitations: tuple[str, ...] = (
        "Template coverage is not DFT numerical/scientific correctness evidence.",
        "Template coverage is not all-candidate timing/gem5/EDA/formal closure.",
    )
    schema_version: str = DFT_MODE_TEMPLATE_SCHEMA

    def __post_init__(self) -> None:
        if self.mode_id not in FIRST_STAGE_DFT_MODE_IDS:
            raise ValueError(f"unsupported first-stage DFT mode: {self.mode_id}")
        if not self.stages:
            raise ValueError(f"DFT mode template has no stages: {self.mode_id}")

    @property
    def phase_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for stage in self.stages:
            for phase_id in stage.phase_ids:
                if phase_id not in seen:
                    seen.append(phase_id)
        return tuple(seen)

    def config(self, *, parameters: Mapping[str, Any] | None = None) -> DftConfig:
        merged = {"mode_template_id": self.mode_id}
        merged.update(dict(parameters or {}))
        return DftConfig(
            mode_id=self.mode_id,
            source_software=self.source_software,
            calculation_sequence=self.calculation_sequence,
            parameters=merged,
            claim_boundary=self.claim_boundary,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode_id": self.mode_id,
            "display_name": self.display_name,
            "source_software": self.source_software,
            "calculation_sequence": list(self.calculation_sequence),
            "phase_ids": list(self.phase_ids),
            "stages": [stage.to_dict() for stage in self.stages],
            "required_input_kinds": list(self.required_input_kinds),
            "expected_output_kinds": list(self.expected_output_kinds),
            "claim_boundary": self.claim_boundary,
            "limitations": list(self.limitations),
            "non_decision_contract": _NON_DECISION_NOTE,
        }

    def workflow_spec(self, *, config: DftConfig | None = None) -> DftWorkflowSpec:
        resolved_config = config or self.config()
        stages: list[DftStage] = []
        claims: list[DftHotspotClaim] = []
        review_gates: list[DftReviewGate] = []
        dependencies: list[DftStageDependency] = []
        previous_stage_id: str | None = None
        for stage_template in self.stages:
            phase_skeleton = [
                {
                    "phase_id": phase_id,
                    "label": phase_id.replace("_", " "),
                    "kernel_count": 1,
                    "estimated_flops": 0.0,
                    "estimated_memory_bytes": 0.0,
                    "evidence_level": stage_template.evidence_level,
                    "confidence": stage_template.confidence,
                    "dominance": "candidate",
                    "dominance_reason": (
                        "mode template marks required workflow phase; dominance "
                        "requires observed profile/log or reviewed static evidence"
                    ),
                    "source_fact_ids": [f"template:{self.mode_id}:{stage_template.stage_id}:{phase_id}"],
                }
                for phase_id in stage_template.phase_ids
            ]
            stage = DftStage(
                stage_id=stage_template.stage_id,
                stage_type=stage_template.stage_type,
                source_program=stage_template.source_program,
                calculation_kind=stage_template.calculation_kind,
                phase_skeleton=phase_skeleton,
                input_artifacts=list(stage_template.input_artifacts),
                output_artifacts=list(stage_template.output_artifacts),
                evidence=[
                    DftClaimEvidence(
                        evidence_level=stage_template.evidence_level,
                        source_type="mode_template",
                        confidence=stage_template.confidence,
                        source_fact_ids=[f"template:{self.mode_id}:{stage_template.stage_id}"],
                        description="stage emitted by first-stage DFT common-mode template",
                    )
                ],
                source_facts=[
                    {
                        "schema_version": DFT_CONFIG_SCHEMA,
                        "field": "dft.mode_id",
                        "value": self.mode_id,
                        "source_type": "mode_template",
                        "evidence_level": stage_template.evidence_level,
                    },
                    {
                        "schema_version": DFT_CONFIG_SCHEMA,
                        "field": "dft.calculation_kind",
                        "value": stage_template.calculation_kind,
                        "source_type": "mode_template",
                        "evidence_level": stage_template.evidence_level,
                    },
                ],
                review_flags=["template_requires_profile_or_fixture_for_strong_claim"],
                coverage_level=stage_template.coverage_level,
                attributes={
                    "dft_mode_id": self.mode_id,
                    "claim_boundary": resolved_config.claim_boundary,
                    "full_workload_reconstruction": False,
                    "non_decision_contract": _NON_DECISION_NOTE,
                    "stage_notes": list(stage_template.notes),
                },
            )
            stages.append(stage)
            for phase_id in stage_template.hotspot_phase_ids:
                claims.append(DftHotspotClaim(
                    claim_id=f"{stage.stage_id}:{phase_id}:predicted:hotspot",
                    stage_id=stage.stage_id,
                    phase_id=phase_id,
                    kernel_kind=_kernel_kind_for_phase(phase_id),
                    claim_kind="hotspot",
                    evidence_label="predicted",
                    estimated_flops=0.0,
                    estimated_memory_bytes=0.0,
                    evidence_level=stage_template.evidence_level,
                    confidence=stage_template.confidence,
                    source_fact_ids=[f"template:{self.mode_id}:{stage.stage_id}:{phase_id}"],
                    review_status="needs_review",
                    reason="first-stage DFT mode template hotspot requires observed or calibrated evidence before strong claim",
                    attributes={"dft_mode_id": self.mode_id},
                ))
            if previous_stage_id is not None:
                dependencies.append(DftStageDependency(
                    source_stage_id=previous_stage_id,
                    target_stage_id=stage.stage_id,
                    artifact_names=_dependency_artifacts_for(stage_template.stage_type),
                    dependency_kind="common_mode_stage_artifact_dependency",
                    evidence=DftClaimEvidence(
                        evidence_level="template_static",
                        source_type="mode_template",
                        confidence="medium",
                        source_fact_ids=[f"template:{self.mode_id}:dependency:{previous_stage_id}:{stage.stage_id}"],
                    ),
                ))
            previous_stage_id = stage.stage_id

        if claims:
            review_gates.append(DftReviewGate(
                gate_id=f"{self.mode_id}:template_hotspot_review",
                reason="mode-template hotspot and dominance claims require observed profile/log or calibrated fixture evidence before release-strength claims",
                related_stage_ids=[stage.stage_id for stage in stages],
                related_phase_ids=sorted({claim.phase_id for claim in claims}),
                related_claim_ids=[claim.claim_id for claim in claims],
            ))
        return DftWorkflowSpec(
            workflow_id=f"{self.mode_id}_workflow_template",
            workflow_family="dft",
            source_software=self.source_software,
            coverage_level="first_stage_common_mode_template",
            stages=stages,
            dependencies=dependencies,
            hotspot_claims=claims,
            review_gates=review_gates,
            limitations=list(self.limitations) + [_NON_DECISION_NOTE],
            review_flags=["template_requires_profile_or_fixture_for_strong_claim"],
        )


def _stage(
    stage_id: str,
    stage_type: str,
    source_program: str,
    calculation_kind: str,
    phase_ids: Sequence[str],
    *,
    inputs: Sequence[str] = (),
    outputs: Sequence[str] = (),
    hotspots: Sequence[str] = (),
    notes: Sequence[str] = (),
) -> DftModeStageTemplate:
    return DftModeStageTemplate(
        stage_id=stage_id,
        stage_type=stage_type,
        source_program=source_program,
        calculation_kind=calculation_kind,
        phase_ids=tuple(phase_ids),
        input_artifacts=tuple(inputs),
        output_artifacts=tuple(outputs),
        hotspot_phase_ids=tuple(hotspots),
        notes=tuple(notes),
    )


def _templates() -> Dict[str, DftModeTemplate]:
    templates = [
        DftModeTemplate(
            mode_id="scf_ground_state",
            display_name="SCF ground-state calculation",
            source_software="qe",
            calculation_sequence=("pw.x:scf",),
            required_input_kinds=("structure", "pseudopotentials", "k_points", "plane_wave_cutoff"),
            expected_output_kinds=("charge_density", "wavefunctions", "total_energy"),
            stages=(
                _stage(
                    "stage_00_pw_scf",
                    "scf",
                    "pw.x",
                    "scf",
                    ("setup", "h_psi", "diagonalization", "charge_density", "mixing", "scf_convergence"),
                    outputs=("charge_density", "wavefunctions", "total_energy"),
                    hotspots=("h_psi", "diagonalization", "charge_density", "mixing"),
                ),
            ),
        ),
        DftModeTemplate(
            mode_id="nscf_bands_dos",
            display_name="NSCF bands and density-of-states workflow",
            source_software="qe",
            calculation_sequence=("pw.x:nscf", "bands.x:bands", "dos.x:dos"),
            required_input_kinds=("ground_state_charge_density", "band_k_path", "dos_k_mesh"),
            expected_output_kinds=("eigenvalues", "band_structure", "density_of_states"),
            stages=(
                _stage(
                    "stage_00_pw_nscf",
                    "nscf",
                    "pw.x",
                    "nscf",
                    ("h_psi", "diagonalization", "kpoint_sampling", "wavefunction_write"),
                    inputs=("ground_state_charge_density",),
                    outputs=("nscf_eigenvalues", "wavefunctions"),
                    hotspots=("h_psi", "diagonalization"),
                ),
                _stage(
                    "stage_01_bands",
                    "bands",
                    "bands.x",
                    "bands",
                    ("band_path_interpolation", "eigenvalue_collection", "io"),
                    inputs=("nscf_eigenvalues",),
                    outputs=("band_structure",),
                    hotspots=("eigenvalue_collection",),
                ),
                _stage(
                    "stage_02_dos",
                    "dos",
                    "dos.x",
                    "dos",
                    ("dos_histogram", "smearing", "io"),
                    inputs=("nscf_eigenvalues",),
                    outputs=("density_of_states",),
                    hotspots=("dos_histogram",),
                ),
            ),
        ),
        DftModeTemplate(
            mode_id="relax_vc_relax",
            display_name="Ionic and variable-cell relaxation workflow",
            source_software="qe",
            calculation_sequence=("pw.x:relax", "pw.x:vc-relax"),
            required_input_kinds=("initial_structure", "pseudopotentials", "force_threshold", "stress_threshold"),
            expected_output_kinds=("relaxed_structure", "relaxed_cell", "forces", "stress"),
            stages=(
                _stage(
                    "stage_00_pw_relax",
                    "relax",
                    "pw.x",
                    "relax",
                    ("scf_iteration", "h_psi", "diagonalization", "forces", "ionic_update"),
                    outputs=("relaxed_ionic_positions", "forces"),
                    hotspots=("h_psi", "diagonalization", "forces"),
                ),
                _stage(
                    "stage_01_pw_vc_relax",
                    "vc_relax",
                    "pw.x",
                    "vc-relax",
                    ("scf_iteration", "h_psi", "diagonalization", "forces", "stress", "cell_update"),
                    inputs=("relaxed_ionic_positions",),
                    outputs=("relaxed_structure", "relaxed_cell", "forces", "stress"),
                    hotspots=("h_psi", "diagonalization", "forces", "stress"),
                ),
            ),
        ),
        DftModeTemplate(
            mode_id="aimd_md",
            display_name="Ab-initio molecular dynamics workflow",
            source_software="qe",
            calculation_sequence=("pw.x:md",),
            required_input_kinds=("initial_structure", "pseudopotentials", "time_step", "temperature_control"),
            expected_output_kinds=("trajectory", "energies", "forces"),
            stages=(
                _stage(
                    "stage_00_pw_md",
                    "md",
                    "pw.x",
                    "md",
                    ("md_step", "scf_iteration", "h_psi", "diagonalization", "forces", "velocity_update", "thermostat"),
                    outputs=("trajectory", "energies", "forces"),
                    hotspots=("h_psi", "diagonalization", "forces"),
                    notes=("Each MD step nests an SCF/force calculation; template is a loop fact, not a schedule decision.",),
                ),
            ),
        ),
        DftModeTemplate(
            mode_id="hybrid_exact_exchange",
            display_name="Hybrid-functional exact-exchange workflow",
            source_software="qe",
            calculation_sequence=("pw.x:hybrid-scf",),
            required_input_kinds=("structure", "pseudopotentials", "hybrid_functional", "exx_parameters"),
            expected_output_kinds=("charge_density", "wavefunctions", "exact_exchange_energy"),
            stages=(
                _stage(
                    "stage_00_pw_hybrid_scf",
                    "hybrid_scf",
                    "pw.x",
                    "hybrid-scf",
                    ("setup", "exact_exchange", "h_psi", "fft", "diagonalization", "charge_density", "mixing"),
                    outputs=("charge_density", "wavefunctions", "exact_exchange_energy"),
                    hotspots=("exact_exchange", "h_psi", "fft", "diagonalization"),
                ),
            ),
        ),
        DftModeTemplate(
            mode_id="postprocess_charge_density",
            display_name="Charge-density post-processing workflow",
            source_software="qe",
            calculation_sequence=("pp.x:charge-density", "projwfc.x:projection"),
            required_input_kinds=("ground_state_charge_density", "wavefunctions", "projection_request"),
            expected_output_kinds=("charge_density_grid", "projected_dos", "visualization_cube"),
            stages=(
                _stage(
                    "stage_00_pp_charge_density",
                    "postprocess_charge_density",
                    "pp.x",
                    "charge-density",
                    ("charge_density_read", "fft", "grid_interpolation", "charge_density_write", "io"),
                    inputs=("ground_state_charge_density",),
                    outputs=("charge_density_grid", "visualization_cube"),
                    hotspots=("fft", "grid_interpolation", "charge_density_write"),
                ),
                _stage(
                    "stage_01_projwfc",
                    "projwfc",
                    "projwfc.x",
                    "projection",
                    ("wavefunction_projection", "dos_histogram", "io"),
                    inputs=("wavefunctions",),
                    outputs=("projected_dos",),
                    hotspots=("wavefunction_projection", "dos_histogram"),
                ),
            ),
        ),
    ]
    return {template.mode_id: template for template in templates}


def first_stage_dft_mode_templates() -> Dict[str, DftModeTemplate]:
    """Return all six first-stage DFT common-mode templates."""
    return dict(_templates())


def first_stage_dft_configs() -> Dict[str, DftConfig]:
    """Return a default ``DftConfig`` for each first-stage DFT mode."""
    return {mode_id: template.config() for mode_id, template in first_stage_dft_mode_templates().items()}


def workflow_spec_for_mode(mode_id: str, *, parameters: Mapping[str, Any] | None = None) -> DftWorkflowSpec:
    """Build a workflow spec for one first-stage DFT mode template."""
    templates = first_stage_dft_mode_templates()
    if mode_id not in templates:
        raise ValueError(f"unsupported first-stage DFT mode: {mode_id}")
    template = templates[mode_id]
    return template.workflow_spec(config=template.config(parameters=parameters))


def build_first_stage_dft_mode_coverage_report() -> Dict[str, Any]:
    """Build an auditable coverage report for the six first-stage DFT modes."""
    templates = first_stage_dft_mode_templates()
    missing_modes = [mode_id for mode_id in FIRST_STAGE_DFT_MODE_IDS if mode_id not in templates]
    records: list[Dict[str, Any]] = []
    for mode_id in FIRST_STAGE_DFT_MODE_IDS:
        template = templates.get(mode_id)
        if template is None:
            records.append({"mode_id": mode_id, "status": "missing_template"})
            continue
        workflow = template.workflow_spec()
        records.append({
            "mode_id": mode_id,
            "status": "covered_by_workflow_template" if workflow.stages and template.phase_ids else "incomplete_template",
            "config": template.config().to_dict(),
            "template": template.to_dict(),
            "workflow_summary": workflow.workflow_summary(),
            "claim_summary": workflow.claim_summary(),
            "stage_count": len(workflow.stages),
            "phase_ids": list(template.phase_ids),
            "hotspot_claim_count": len(workflow.hotspot_claims),
            "review_gate_count": len(workflow.review_gates),
        })
    incomplete = [
        record["mode_id"]
        for record in records
        if record.get("status") != "covered_by_workflow_template"
    ]
    return {
        "schema_version": DFT_MODE_COVERAGE_SCHEMA,
        "status": "passed" if not missing_modes and not incomplete else "failed",
        "claim_boundary": "workflow-template coverage only; not release-complete evidence",
        "required_mode_ids": list(FIRST_STAGE_DFT_MODE_IDS),
        "covered_mode_ids": [
            record["mode_id"]
            for record in records
            if record.get("status") == "covered_by_workflow_template"
        ],
        "missing_mode_ids": missing_modes,
        "incomplete_mode_ids": incomplete,
        "mode_count": len(records),
        "records": records,
        "non_decision_contract": _NON_DECISION_NOTE,
    }


def _dependency_artifacts_for(stage_type: str) -> list[str]:
    if stage_type in {"bands", "dos", "projwfc"}:
        return ["eigenvalues", "wavefunctions"]
    if stage_type in {"vc_relax", "relax"}:
        return ["structure", "charge_density", "wavefunctions"]
    return ["charge_density", "wavefunctions"]


def _kernel_kind_for_phase(phase_id: str) -> str:
    phase = phase_id.lower()
    if "exchange" in phase or "projection" in phase:
        return "batched_gemm"
    if "diag" in phase or "eigen" in phase:
        return "eigen"
    if "fft" in phase or "grid" in phase or "density" in phase or "rho" in phase:
        return "fft"
    if "mix" in phase or "force" in phase or "stress" in phase or "histogram" in phase:
        return "reduction"
    if "io" in phase or "write" in phase or "read" in phase:
        return "dma_load"
    return "gemm"


def assert_first_stage_modes_covered(mode_ids: Iterable[str] | None = None) -> None:
    """Raise ``AssertionError`` if any required first-stage mode lacks coverage."""
    required = tuple(mode_ids or FIRST_STAGE_DFT_MODE_IDS)
    report = build_first_stage_dft_mode_coverage_report()
    records = {record["mode_id"]: record for record in report["records"]}
    missing = [
        mode_id for mode_id in required
        if mode_id not in records or records[mode_id].get("status") != "covered_by_workflow_template"
    ]
    if missing:
        raise AssertionError(f"missing first-stage DFT mode template coverage: {missing}")
