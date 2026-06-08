#!/usr/bin/env python3
"""QE mainflow workload-suite and patch-manifest contracts.

The artifacts here deliberately live under ``reference_workloads``.  They make
QE-specific workload and runtime-patch facts explicit for the DFT/QE reference
vertical slice without adding mandatory QE fields to the domain-neutral core IR
or candidate identity layer.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, List, Mapping, Sequence

from dse_v2.core.workload.package import WorkloadPackage
from dse_v2.mapping.search_policy import SearchProblem
from dse_v2.reference_workloads.dft_qe import DftQePwImporter, dft_qe_pw_profile


QE_MAINFLOW_WORKLOAD_SUITE_SCHEMA = "dse.qe_mainflow_workload_suite_manifest.v1"
QE_PATCH_RUNTIME_MANIFEST_SCHEMA = "dse.qe_patch_runtime_manifest.v1"
QE_PATCH_RUNTIME_MANIFEST_VALIDATION_SCHEMA = "dse.qe_patch_runtime_manifest_validation.v1"
QE_MAINFLOW_WORKLOAD_SUITE_VALIDATION_SCHEMA = "dse.qe_mainflow_workload_suite_validation.v1"

REQUIRED_MAINFLOW_CLASSES = ("scf", "nscf", "post_processing")
POST_PROCESSING_STAGE_TYPES = {"bands", "dos", "projwfc"}
RELAX_STAGE_TYPES = {"relax", "vc_relax"}
REQUIRED_CASE_FIELDS = (
    "case_id",
    "stage_type",
    "qe_command",
    "input_hashes",
    "expected_outputs",
    "kernel_coverage",
    "physical_quantities",
    "baseline_run_provenance",
    "tolerance_reference",
    "blocker_status",
    "candidate_identity_participation",
    "adapter_boundary",
)
REQUIRED_PATCH_ROW_FIELDS = (
    "patch_id",
    "workload_case_id",
    "changed_files",
    "transformed_kernels",
    "changed_assumptions",
    "data_layout_policy",
    "precision_policy",
    "fallback_path",
    "tolerance_impact",
    "performance_impact",
)

_QE_SCF_INPUT = """
&CONTROL
  calculation = 'scf',
  prefix = 'si',
  outdir = './tmp',
  pseudo_dir = './pseudo',
  verbosity = 'high',
  tstress = .true.,
  tprnfor = .true.
/
&SYSTEM
  ibrav = 2,
  celldm(1) = 10.26,
  nat = 2,
  ntyp = 1,
  ecutwfc = 12.0,
  nbnd = 8
/
&ELECTRONS
  conv_thr = 1.0d-6,
  mixing_beta = 0.7,
  electron_maxstep = 40
/

ATOMIC_SPECIES
  Si 28.0855 Si.pz-vbc.UPF
ATOMIC_POSITIONS alat
  Si 0.00 0.00 0.00
  Si 0.25 0.25 0.25

K_POINTS automatic
2 2 2 0 0 0
"""

_QE_NSCF_INPUT = """
&CONTROL
  calculation = 'nscf',
  prefix = 'si',
  outdir = './tmp',
  pseudo_dir = './pseudo',
  verbosity = 'high',
  tstress = .true.,
  tprnfor = .true.
/
&SYSTEM
  ibrav = 2,
  celldm(1) = 10.26,
  nat = 2,
  ntyp = 1,
  ecutwfc = 12.0,
  nbnd = 12,
  occupations = 'tetrahedra'
/
&ELECTRONS
  conv_thr = 1.0d-6,
  mixing_beta = 0.7,
  electron_maxstep = 40
/

ATOMIC_SPECIES
  Si 28.0855 Si.pz-vbc.UPF
ATOMIC_POSITIONS alat
  Si 0.00 0.00 0.00
  Si 0.25 0.25 0.25

K_POINTS automatic
4 4 4 0 0 0
"""

# Compact high-symmetry band path for proof campaigns.  The path still
# exercises a real QE ``bands`` workflow, but uses 13 k-points instead of the
# earlier 41-point fixture so native-h_psi 36-row campaigns can finish inside
# the per-stage timeout on the available workstation.
_QE_BANDS_PW_INPUT = """
&CONTROL
  calculation = 'bands',
  prefix = 'si',
  outdir = './tmp',
  pseudo_dir = './pseudo',
  verbosity = 'high',
  tstress = .true.,
  tprnfor = .true.
/
&SYSTEM
  ibrav = 2,
  celldm(1) = 10.26,
  nat = 2,
  ntyp = 1,
  ecutwfc = 12.0,
  nbnd = 12
/
&ELECTRONS
  conv_thr = 1.0d-6,
  mixing_beta = 0.7,
  electron_maxstep = 40
/

ATOMIC_SPECIES
  Si 28.0855 Si.pz-vbc.UPF
ATOMIC_POSITIONS alat
  Si 0.00 0.00 0.00
  Si 0.25 0.25 0.25

K_POINTS crystal_b
5
  0.000 0.000 0.000 3
  0.500 0.000 0.000 3
  0.500 0.500 0.000 3
  0.000 0.000 0.000 3
  0.500 0.500 0.500 1
"""

_QE_BANDS_X_INPUT = """
&BANDS
  prefix = 'si',
  outdir = './tmp',
  filband = 'si.bands.dat'
/
"""

_QE_RELAX_INPUT = """
&CONTROL
  calculation = 'relax',
  prefix = 'si_relax',
  outdir = './tmp_relax',
  pseudo_dir = './pseudo',
  verbosity = 'high',
  tstress = .true.,
  tprnfor = .true.,
  nstep = 2
/
&SYSTEM
  ibrav = 2,
  celldm(1) = 10.26,
  nat = 2,
  ntyp = 1,
  ecutwfc = 12.0,
  nbnd = 8
/
&ELECTRONS
  conv_thr = 1.0d-6,
  mixing_beta = 0.7,
  electron_maxstep = 40
/
&IONS
  ion_dynamics = 'bfgs'
/

ATOMIC_SPECIES
  Si 28.0855 Si.pz-vbc.UPF
ATOMIC_POSITIONS alat
  Si 0.00 0.00 0.00
  Si 0.25 0.25 0.25

K_POINTS automatic
2 2 2 0 0 0
"""

_QE_SCF_LOG = """
     number of k points=     2
     number of Kohn-Sham states= 8
     number of plane waves= 321
     FFT dimensions: ( 16, 16, 16)
     iteration # 1
     h_psi        :      0.10s CPU      1.20s WALL
     c_bands      :      0.05s CPU      0.20s WALL
     FFT          :      0.02s CPU      0.10s WALL
     convergence has been achieved in 1 iterations
"""

_QE_NSCF_LOG = """
     number of k points=     2
     number of Kohn-Sham states= 16
     number of plane waves= 321
     FFT dimensions: ( 16, 16, 16)
     iteration # 1
     h_psi        :      0.08s CPU      0.90s WALL
     c_bands      :      0.04s CPU      0.18s WALL
"""

_QE_RELAX_LOG = """
     number of k points=     2
     number of Kohn-Sham states= 8
     number of plane waves= 321
     FFT dimensions: ( 16, 16, 16)
     iteration # 1
     h_psi        :      0.11s CPU      1.25s WALL
     forces       :      0.03s CPU      0.14s WALL
"""

_BANDS_PROFILE = {"phases": {"diagonalization": 0.25, "band_path_projection": 0.05}}


def _stable_json_hash(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _without_hash(payload: Mapping[str, Any], *hash_keys: str) -> Dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in payload.items() if key not in set(hash_keys)}


def workflow_bundle_from_qe_mainflow_manifest(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Adapt the QE mainflow manifest into the workflow-bundle input contract."""

    stages: List[Dict[str, Any]] = []
    seen_stage_ids: set[str] = set()
    for case in manifest.get("cases", []) or []:
        if not isinstance(case, Mapping):
            continue
        source = case.get("step1_source", {}) if isinstance(case.get("step1_source"), Mapping) else {}
        for index, stage in enumerate(source.get("stages", []) or []):
            if not isinstance(stage, Mapping):
                continue
            stage_id = str(stage.get("stage_id") or f"{case.get('case_id', 'case')}_{index:02d}")
            dedupe_id = f"{case.get('case_id', '')}:{stage_id}"
            if dedupe_id in seen_stage_ids:
                continue
            seen_stage_ids.add(dedupe_id)
            row = copy.deepcopy(dict(stage))
            row["stage_id"] = dedupe_id.replace(":", "__")
            row.setdefault("stage_type", str(case.get("stage_type", "")))
            row.setdefault("program", str(case.get("qe_command", ["pw.x"])[0] if case.get("qe_command") else "pw.x"))
            stages.append(row)
    return {
        "workflow_id": str(manifest.get("suite_id", "qe_mainflow_workload_suite")),
        "stages": stages,
    }


def _stage_class(stage_type: str) -> str:
    normalized = str(stage_type).strip().lower().replace("-", "_")
    if normalized in POST_PROCESSING_STAGE_TYPES:
        return "post_processing"
    return normalized


def _input_artifact(name: str, content: str, purpose: str) -> Dict[str, Any]:
    return {
        "path": f"fixtures/qe/{name}",
        "sha256": _sha256_text(content),
        "hash_algorithm": "sha256",
        "purpose": purpose,
    }


def _case_payload(
    *,
    case_id: str,
    stage_type: str,
    qe_command: Sequence[str],
    input_name: str,
    input_text: str,
    log_text: str | None,
    profile: Mapping[str, Any] | None,
    expected_outputs: Mapping[str, Any],
    kernel_coverage: Sequence[str],
    physical_quantities: Sequence[str],
    baseline_status: str = "fixture_reference",
    workflow_stages: Sequence[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    workflow_stage_payloads: List[Dict[str, Any]]
    if workflow_stages is None:
        workflow_stage_payloads = [
            {
                "stage_id": f"stage_00_{stage_type}",
                "program": qe_command[0],
                "stage_type": stage_type,
                "command": list(qe_command),
                "input": input_text,
                "input_path": f"fixtures/qe/{input_name}",
            }
        ]
    else:
        workflow_stage_payloads = [copy.deepcopy(dict(stage)) for stage in workflow_stages]

    artifacts: List[Dict[str, Any]] = []
    seen_inputs: set[str] = set()
    for stage in workflow_stage_payloads:
        stage_input_path = str(stage.get("input_path") or "")
        stage_input_text = stage.get("input")
        if isinstance(stage_input_text, str) and stage_input_path and stage_input_path not in seen_inputs:
            artifacts.append(_input_artifact(stage_input_path.rsplit("/", 1)[-1], stage_input_text, "qe_input"))
            seen_inputs.add(stage_input_path)

    stage: Dict[str, Any] = dict(workflow_stage_payloads[-1]) if workflow_stage_payloads else {
        "program": qe_command[0],
        "stage_type": stage_type,
        "input": input_text,
        "input_path": f"fixtures/qe/{input_name}",
        "command": list(qe_command),
    }
    if log_text is not None:
        artifacts.append(_input_artifact(input_name.replace(".in", ".out"), log_text, "qe_stdout_fixture"))
        stage["log"] = log_text
        stage["log_path"] = f"fixtures/qe/{input_name.replace('.in', '.out')}"
    if profile is not None:
        stage["profile"] = dict(profile)
    stage = {key: value for key, value in stage.items() if value is not None}
    if workflow_stage_payloads:
        workflow_stage_payloads[-1] = stage

    case: Dict[str, Any] = {
        "case_id": case_id,
        "stage_type": stage_type,
        "workflow_class": _stage_class(stage_type),
        "qe_command": list(qe_command),
        "source_kind": "qe_workflow_bundle",
        "adapter_boundary": {
            "profile_id": "dft_qe_pw_static",
            "importer_id": "dft_qe_pw",
            "qe_specific_fields_scope": "reference_workload_domain_metadata_only",
            "generic_core_required_qe_fields": [],
        },
        "input_artifacts": artifacts,
        "input_hashes": {artifact["path"]: artifact["sha256"] for artifact in artifacts},
        "step1_source": {"stages": workflow_stage_payloads},
        "baseline_sequence": [
            {
                "step_id": str(stage.get("stage_id", f"stage_{index:02d}")),
                "program": str(stage.get("program", qe_command[0])),
                "command": list(stage.get("command", [stage.get("program", qe_command[0]), "-in", stage.get("input_path", input_name)])),
                "input_path": str(stage.get("input_path", "")),
                "input": stage.get("input"),
                "include_in_performance": True,
            }
            for index, stage in enumerate(workflow_stage_payloads)
        ],
        "expected_outputs": dict(expected_outputs),
        "kernel_coverage": list(kernel_coverage),
        "physical_quantities": list(physical_quantities),
        "baseline_run_provenance": {
            "status": baseline_status,
            "source": "repo_qe_mainflow_contract_fixture",
            "command": list(qe_command),
            "claim_boundary": "structural oracle fields only; not a real QE runtime/L4 performance baseline",
        },
        "tolerance_reference": {
            "tolerance_profile_id": "qe_mainflow_correctness_v1",
            "required_fields": [
                "kernel_absolute_tolerance",
                "kernel_relative_tolerance",
                "kernel_error_metric",
                "scf_total_energy_tolerance_ry",
                "density_residual_tolerance",
                "eigenvalue_summary_tolerance_ry",
                "force_tolerance_ry_bohr",
                "stress_tolerance_kbar",
                "source",
                "rationale",
            ],
        },
        "blocker_status": {
            "structural_status": "ready",
            "trusted_closure_status": "blocked_until_real_qe_baseline_and_l4_evidence",
            "reason": "This manifest freezes workload semantics; trusted speedup still needs real QE baseline, L4 trace, and correctness artifacts.",
        },
        "candidate_identity_participation": False,
    }
    case["case_hash"] = _stable_json_hash(_without_hash(case, "case_hash"))
    return case


def default_qe_mainflow_workload_suite(*, status: str = "draft", include_relax: bool = True) -> Dict[str, Any]:
    """Return a deterministic QE mainflow suite manifest draft.

    The suite is structurally complete for release-v1 workload composition, but
    each case honestly records that trusted performance closure still requires
    real QE baseline and L4 evidence rows.
    """
    cases = [
        _case_payload(
            case_id="qe_si_scf_small_v1",
            stage_type="scf",
            qe_command=["pw.x", "-in", "si_scf.in"],
            input_name="si_scf.in",
            input_text=_QE_SCF_INPUT,
            log_text=_QE_SCF_LOG,
            profile={"phases": {"h_psi": 1.2, "diagonalization": 0.2, "fft": 0.1}},
            expected_outputs={
                "total_energy_ry": {"value": -15.850126, "unit": "Ry", "role": "scf_physical_oracle"},
                "density_residual": {"value": 5.0e-9, "unit": "relative_norm", "role": "convergence_oracle"},
            },
            kernel_coverage=["h_psi", "s_psi", "diagonalization", "fft", "rho_out", "mix_rho", "veff"],
            physical_quantities=["total_energy_ry", "density_residual", "eigenvalue_summary"],
        ),
        _case_payload(
            case_id="qe_si_nscf_bandgrid_v1",
            stage_type="nscf",
            qe_command=["pw.x", "-in", "si_nscf.in"],
            input_name="si_nscf.in",
            input_text=_QE_NSCF_INPUT,
            log_text=_QE_NSCF_LOG,
            profile={"phases": {"h_psi": 0.9, "diagonalization": 0.18, "fft": 0.08}},
            expected_outputs={
                "eigenvalue_summary_ry": {"max_abs": 2.0, "min_abs": 0.0, "unit": "Ry", "role": "band_orbital_oracle"},
                "density_residual": {"value": 1.0e-8, "unit": "relative_norm", "role": "nscf_consistency_oracle"},
            },
            kernel_coverage=["h_psi", "s_psi", "diagonalization", "fft", "subspace_rotation"],
            physical_quantities=["eigenvalue_summary", "band_occupations"],
            workflow_stages=[
                {
                    "stage_id": "stage_00_scf_prerequisite",
                    "program": "pw.x",
                    "stage_type": "scf",
                    "command": ["pw.x", "-in", "si_scf.in"],
                    "input": _QE_SCF_INPUT,
                    "input_path": "fixtures/qe/si_scf.in",
                    "dependency_role": "real_qe_prerequisite",
                },
                {
                    "stage_id": "stage_01_nscf",
                    "program": "pw.x",
                    "stage_type": "nscf",
                    "command": ["pw.x", "-in", "si_nscf.in"],
                    "input": _QE_NSCF_INPUT,
                    "input_path": "fixtures/qe/si_nscf.in",
                },
            ],
        ),
        _case_payload(
            case_id="qe_si_bands_path_v1",
            stage_type="bands",
            qe_command=["bands.x", "-in", "si_bands_x.in"],
            input_name="si_bands_x.in",
            input_text=_QE_BANDS_X_INPUT,
            log_text=None,
            profile=_BANDS_PROFILE,
            expected_outputs={
                "band_path_eigenvalue_summary_ry": {"max_abs": 2.5, "min_abs": 0.0, "unit": "Ry", "role": "post_processing_oracle"}
            },
            kernel_coverage=["diagonalization", "band_path_projection"],
            physical_quantities=["band_path_eigenvalue_summary"],
            workflow_stages=[
                {
                    "stage_id": "stage_00_scf_prerequisite",
                    "program": "pw.x",
                    "stage_type": "scf",
                    "command": ["pw.x", "-in", "si_scf.in"],
                    "input": _QE_SCF_INPUT,
                    "input_path": "fixtures/qe/si_scf.in",
                    "dependency_role": "real_qe_prerequisite",
                },
                {
                    "stage_id": "stage_01_bands_pw",
                    "program": "pw.x",
                    "stage_type": "bands",
                    "command": ["pw.x", "-in", "si_bands_pw.in"],
                    "input": _QE_BANDS_PW_INPUT,
                    "input_path": "fixtures/qe/si_bands_pw.in",
                },
                {
                    "stage_id": "stage_02_bands_x",
                    "program": "bands.x",
                    "stage_type": "bands",
                    "command": ["bands.x", "-in", "si_bands_x.in"],
                    "input": _QE_BANDS_X_INPUT,
                    "input_path": "fixtures/qe/si_bands_x.in",
                },
            ],
        ),
    ]
    relax_policy: Dict[str, Any]
    if include_relax:
        cases.append(
            _case_payload(
                case_id="qe_si_relax_forces_v1",
                stage_type="relax",
                qe_command=["pw.x", "-in", "si_relax.in"],
                input_name="si_relax.in",
                input_text=_QE_RELAX_INPUT,
                log_text=_QE_RELAX_LOG,
                profile={"phases": {"h_psi": 1.25, "forces": 0.14, "fft": 0.11}},
                expected_outputs={
                    "total_energy_ry": {"value": -15.851002, "unit": "Ry", "role": "relax_physical_oracle"},
                    "max_force_ry_bohr": {"value": 8.0e-5, "unit": "Ry/Bohr", "role": "force_oracle"},
                    "stress_kbar": {"value": 0.05, "unit": "kbar", "role": "stress_oracle"},
                },
                kernel_coverage=["h_psi", "fft", "rho_out", "mix_rho", "veff", "forces"],
                physical_quantities=["total_energy_ry", "density_residual", "forces", "stress"],
            )
        )
        relax_policy = {"status": "selected", "stage_types": ["relax"], "rationale": "Release-v1 draft includes force/stress correctness coverage."}
    else:
        relax_policy = {"status": "deferred", "stage_types": [], "rationale": "Relax coverage explicitly deferred for this draft suite."}

    manifest: Dict[str, Any] = {
        "schema_version": QE_MAINFLOW_WORKLOAD_SUITE_SCHEMA,
        "status": status,
        "suite_id": "qe_mainflow_release_v1_draft",
        "release_id": "complete_dse_search_space_release_v1",
        "claim_boundary": "workload_suite_contract_only_not_deliverable_complete",
        "candidate_identity_policy": {
            "workload_case_ids_participate": False,
            "workload_features_participate": False,
            "forbidden_candidate_identity_fields": [
                "case_id",
                "stage_type",
                "qe_command",
                "input_hashes",
                "expected_outputs",
                "kernel_coverage",
                "physical_quantities",
                "baseline_run_provenance",
            ],
            "candidate_identity_axes_owner": "schema_dse_lane",
        },
        "required_mainflow_classes": list(REQUIRED_MAINFLOW_CLASSES),
        "relax_policy": relax_policy,
        "cases": cases,
    }
    manifest["suite_hash"] = _stable_json_hash(_without_hash(manifest, "suite_hash"))
    return manifest


def _case_errors(case: Mapping[str, Any], index: int) -> List[Dict[str, Any]]:
    errors: List[Dict[str, Any]] = []
    for field in REQUIRED_CASE_FIELDS:
        if field not in case or case.get(field) in (None, "", [], {}):
            errors.append({"field": f"cases[{index}].{field}", "message": "required QE workload case field is missing"})
    if case.get("candidate_identity_participation") is not False:
        errors.append({"field": f"cases[{index}].candidate_identity_participation", "message": "workload case must not participate in candidate identity"})
    for name, digest in dict(case.get("input_hashes", {}) or {}).items():
        if not isinstance(digest, str) or len(digest) != 64:
            errors.append({"field": f"cases[{index}].input_hashes.{name}", "message": "input hash must be a sha256 hex digest"})
    boundary = dict(case.get("adapter_boundary", {}) or {})
    if boundary.get("generic_core_required_qe_fields") not in ([], None):
        errors.append({"field": f"cases[{index}].adapter_boundary.generic_core_required_qe_fields", "message": "QE fields must not be mandatory in generic core"})
    if not case.get("kernel_coverage"):
        errors.append({"field": f"cases[{index}].kernel_coverage", "message": "kernel coverage is required"})
    if not case.get("physical_quantities"):
        errors.append({"field": f"cases[{index}].physical_quantities", "message": "physical quantities are required"})
    return errors


def validate_qe_mainflow_workload_suite(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate structural release-v1 QE workload-suite requirements."""
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    if manifest.get("schema_version") != QE_MAINFLOW_WORKLOAD_SUITE_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected QE mainflow suite schema"})
    cases = manifest.get("cases", [])
    if not isinstance(cases, list) or not cases:
        errors.append({"field": "cases", "message": "at least one QE workload case is required"})
        cases = []

    case_ids = [str(case.get("case_id", "")) for case in cases if isinstance(case, Mapping)]
    duplicate_case_ids = sorted({case_id for case_id in case_ids if case_ids.count(case_id) > 1})
    if duplicate_case_ids:
        errors.append({"field": "cases.case_id", "message": "case ids must be unique", "duplicates": duplicate_case_ids})

    classes = sorted({_stage_class(str(case.get("stage_type", ""))) for case in cases if isinstance(case, Mapping)})
    missing_classes = [stage_class for stage_class in REQUIRED_MAINFLOW_CLASSES if stage_class not in classes]
    if missing_classes:
        errors.append({"field": "cases.stage_type", "message": "QE suite is not release-v1 mainflow complete", "missing_mainflow_classes": missing_classes})
    if classes == ["scf"]:
        errors.append({"field": "cases.stage_type", "message": "SCF-only suite cannot satisfy release-v1 acceptance"})

    relax_policy = dict(manifest.get("relax_policy", {}) or {})
    has_relax = any(_stage_class(str(case.get("stage_type", ""))) in RELAX_STAGE_TYPES for case in cases if isinstance(case, Mapping))
    if not has_relax and not relax_policy.get("rationale"):
        errors.append({"field": "relax_policy.rationale", "message": "relax coverage must be selected or explicitly deferred with rationale"})
    if has_relax and relax_policy.get("status") not in {"selected", "included"}:
        warnings.append({"field": "relax_policy.status", "message": "relax case present but policy is not selected/included"})

    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            errors.append({"field": f"cases[{index}]", "message": "case must be an object"})
            continue
        errors.extend(_case_errors(case, index))

    policy = dict(manifest.get("candidate_identity_policy", {}) or {})
    if policy.get("workload_case_ids_participate") is not False:
        errors.append({"field": "candidate_identity_policy.workload_case_ids_participate", "message": "workload cases must be outside candidate identity"})

    expected_hash = _stable_json_hash(_without_hash(manifest, "suite_hash")) if isinstance(manifest, Mapping) else ""
    if manifest.get("suite_hash") and manifest.get("suite_hash") != expected_hash:
        errors.append({"field": "suite_hash", "message": "suite hash does not match manifest content"})

    closure_blockers = [
        str(case.get("case_id"))
        for case in cases
        if isinstance(case, Mapping)
        and dict(case.get("blocker_status", {}) or {}).get("trusted_closure_status") != "not_blocked"
    ]
    if closure_blockers:
        warnings.append({
            "field": "cases.blocker_status.trusted_closure_status",
            "message": "trusted closure still needs downstream QE baseline/L4 evidence",
            "case_ids": closure_blockers,
        })

    return {
        "schema_version": QE_MAINFLOW_WORKLOAD_SUITE_VALIDATION_SCHEMA,
        "valid": not errors,
        "release_v1_workload_suite_accepted": not errors,
        "trusted_closure_ready": not closure_blockers and not errors,
        "case_count": len(cases),
        "case_ids": case_ids,
        "mainflow_classes": classes,
        "missing_mainflow_classes": missing_classes,
        "suite_hash": manifest.get("suite_hash"),
        "computed_suite_hash": expected_hash,
        "errors": errors,
        "warnings": warnings,
    }


def qe_workload_case_to_step1_source(case: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the Step1 importer payload for a suite case."""
    source = case.get("step1_source")
    if not isinstance(source, Mapping):
        raise ValueError("QE workload case lacks a Step1 source payload")
    return copy.deepcopy(dict(source))


def package_qe_mainflow_case(case: Mapping[str, Any]) -> WorkloadPackage:
    """Round-trip one workload case through the existing QE Step1 importer."""
    source = qe_workload_case_to_step1_source(case)
    return DftQePwImporter().import_workload(
        source,
        profile=dft_qe_pw_profile(),
        parameters={
            "source_kind": "qe_workflow_bundle",
            "case_id": str(case.get("case_id", "qe_case")),
            "graph_id": f"{case.get('case_id', 'qe_case')}_graph",
            "claim_boundary": "diagnostic",
        },
    )


def build_qe_fpga_deployment_search_problem(
    manifest: Mapping[str, Any],
    *,
    workload_run_id: str,
    workflow_abstraction: Mapping[str, Any] | None = None,
) -> SearchProblem:
    """Build a Step2 search problem for QE workflow-level FPGA deployment DSE.

    The output is intentionally a search input, not an implementation result.
    It keeps SCF as one stage in the workflow and makes FPGA deployment choices
    explicit: architecture template, offload boundary, mapping granularity,
    runtime schedule, data residency, memory topology, and precision policy.
    """
    contract = (
        workflow_abstraction.get("workflow_feature_contract", {})
        if isinstance(workflow_abstraction, Mapping)
        else {}
    )
    if _workflow_feature_contract_is_valid(contract):
        return build_qe_fpga_deployment_search_problem_from_workflow_contract(
            contract,
            workload_run_id=workload_run_id,
            manifest=manifest,
        )
    validation = validate_qe_mainflow_workload_suite(manifest)
    workflow_scope = str(manifest.get("workflow_scope", "full_qe_mainflow"))
    allow_measured_scf_seed = workflow_scope == "scf_only_measured_seed"
    if not validation["valid"] and not allow_measured_scf_seed:
        raise ValueError("QE mainflow suite must be structurally valid before DSE search construction")

    stage_types = sorted({str(case.get("stage_type")) for case in manifest.get("cases", []) or [] if isinstance(case, Mapping)})
    workflow_classes = sorted({_stage_class(stage_type) for stage_type in stage_types})
    release_completion_eligible = validation["valid"] and workflow_classes != ["scf"] and "post_processing" in workflow_classes
    if not release_completion_eligible and not allow_measured_scf_seed:
        raise ValueError("QE FPGA deployment DSE requires a multi-program workflow, not an SCF-only slice")

    kernel_kinds = sorted({
        str(kernel)
        for case in manifest.get("cases", []) or []
        if isinstance(case, Mapping)
        for kernel in case.get("kernel_coverage", []) or []
    })
    physical_quantities = sorted({
        str(quantity)
        for case in manifest.get("cases", []) or []
        if isinstance(case, Mapping)
        for quantity in case.get("physical_quantities", []) or []
    })
    dependency_edges = _workflow_dependency_edges_from_cases(manifest.get("cases", []) or [])
    data_artifacts = _workflow_data_artifacts_from_cases(manifest.get("cases", []) or [])
    parameters = {
        "deployment_target": [
            "fpga",
        ],
        "release_lane": [
            "release",
            "exploratory",
        ],
        "architecture_template": [
            "fpga_hbm_streaming_dataflow",
            "fpga_fft_transpose_pipeline",
            "fpga_hybrid_cpu_control_accel_kernels",
        ],
        "offload_boundary": [
            "workflow_hotspot_bundle",
            "stage_cluster_bundle",
            "kernel_callsite_bundle",
        ],
        "mapping_granularity": [
            "stage_phase",
            "kernel_callsite",
        ],
        "runtime_schedule": [
            "cpu_orchestrated_sequential",
            "overlap_dma_compute",
            "batched_stage_pipeline",
        ],
        "data_residency": [
            "host_resident_with_streaming_windows",
            "fpga_hbm_resident_hot_arrays",
            "hybrid_checkpointed_residency",
        ],
        "memory_topology": [
            "ddr_streaming",
            "hbm_multi_channel",
            "bram_uram_tiled_locality",
        ],
        "vector_lanes": [
            2,
            4,
            8,
        ],
        "hbm_channel_count": [
            0,
            4,
            8,
        ],
        "tile_doubles": [
            1024,
            2048,
            4096,
        ],
        "precision_policy": [
            "fp64_strict",
            "mixed_precision_candidate_requires_tolerance_review",
        ],
    }
    seed_candidates = [
        {
            "seed_id": "qe_fpga_hbm_streaming_workflow_seed",
            "deployment_target": "fpga",
            "release_lane": "release",
            "architecture_template": "fpga_hbm_streaming_dataflow",
            "offload_boundary": "workflow_hotspot_bundle",
            "mapping_granularity": "kernel_callsite",
            "runtime_schedule": "overlap_dma_compute",
            "data_residency": "fpga_hbm_resident_hot_arrays",
            "memory_topology": "hbm_multi_channel",
            "vector_lanes": 8,
            "hbm_channel_count": 8,
            "tile_doubles": 2048,
            "precision_policy": "fp64_strict",
            "source": "qe_workflow_dse_method_seed",
        },
        {
            "seed_id": "qe_fpga_cpu_control_hybrid_seed",
            "deployment_target": "fpga",
            "release_lane": "release",
            "architecture_template": "fpga_hybrid_cpu_control_accel_kernels",
            "offload_boundary": "stage_cluster_bundle",
            "mapping_granularity": "stage_phase",
            "runtime_schedule": "cpu_orchestrated_sequential",
            "data_residency": "host_resident_with_streaming_windows",
            "memory_topology": "ddr_streaming",
            "vector_lanes": 2,
            "hbm_channel_count": 0,
            "tile_doubles": 1024,
            "precision_policy": "fp64_strict",
            "source": "qe_workflow_dse_method_seed",
        },
        {
            "seed_id": "qe_fpga_mid_tier_tiled_seed",
            "deployment_target": "fpga",
            "release_lane": "release",
            "architecture_template": "fpga_fft_transpose_pipeline",
            "offload_boundary": "stage_cluster_bundle",
            "mapping_granularity": "kernel_callsite",
            "runtime_schedule": "batched_stage_pipeline",
            "data_residency": "hybrid_checkpointed_residency",
            "memory_topology": "hbm_multi_channel",
            "vector_lanes": 4,
            "hbm_channel_count": 4,
            "tile_doubles": 2048,
            "precision_policy": "fp64_strict",
            "source": "qe_workflow_dse_method_seed",
        },
    ]
    constraints = {
        "search_problem_source": "qe_mainflow_manifest_compatibility_fallback",
        "feature_source_priority": ["qe_mainflow_manifest_compatibility_fallback"],
        "manifest_compatibility_fallback_used": True,
        "input_scope": "qe_measured_scf_seed_model_input" if allow_measured_scf_seed else "qe_multi_program_workflow",
        "workflow_scope": workflow_scope,
        "release_completion_eligible": release_completion_eligible,
        "model_level_seed_only": allow_measured_scf_seed,
        "workflow_coverage_limitations": (
            ["scf_only_measured_seed_missing_nscf_post_processing_relax_workflow_coverage"]
            if allow_measured_scf_seed
            else []
        ),
        "workflow_stage_types": stage_types,
        "workflow_classes": workflow_classes,
        "requires_post_processing_stage": "post_processing" in workflow_classes,
        "kernel_kinds": kernel_kinds,
        "physical_quantities": physical_quantities,
        "workflow_dependency_edges": dependency_edges,
        "workflow_data_artifacts": data_artifacts,
        "deployment_target": "fpga",
        "required_parameters": [
            "deployment_target",
            "release_lane",
            "architecture_template",
            "offload_boundary",
            "mapping_granularity",
            "runtime_schedule",
            "data_residency",
            "memory_topology",
            "vector_lanes",
            "hbm_channel_count",
            "tile_doubles",
            "precision_policy",
        ],
        "formal_pareto_lane_field": "release_lane",
        "release_lane": "release",
        "proposal_only_before_model_promotion": True,
        "fail_closed_candidate_budget": True,
        "coverage_axes": [
            "architecture_template",
            "offload_boundary",
            "mapping_granularity",
            "runtime_schedule",
            "data_residency",
            "memory_topology",
            "vector_lanes",
            "hbm_channel_count",
            "tile_doubles",
        ],
        "feedback_generalization_axes": [
            "architecture_template",
            "offload_boundary",
            "mapping_granularity",
            "runtime_schedule",
            "data_residency",
            "memory_topology",
        ],
        "feedback_generalization_strength": 0.15,
        "requires_physical_evidence": True,
        "legal_values": {
            "deployment_target": ["fpga"],
            "precision_policy": ["fp64_strict"],
        },
        "cross_axis_constraints": [
            {
                "rule_id": "hbm_topology_requires_positive_hbm_channels",
                "when": {"memory_topology": "hbm_multi_channel"},
                "require": {"hbm_channel_count": {"gt": 0}},
                "blocker": "illegal_hbm_channel_count_for_hbm_topology",
            },
            {
                "rule_id": "non_hbm_topology_requires_zero_hbm_channels",
                "when": {"memory_topology": {"ne": "hbm_multi_channel"}},
                "require": {"hbm_channel_count": 0},
                "blocker": "illegal_hbm_channel_count_for_non_hbm_topology",
            },
        ],
        "model_objectives": [
            {
                "metric": "vector_lanes",
                "direction": "maximize",
                "weight": 0.25,
                "scale": 8.0,
                "role": "cheap_proxy_for_candidate_compute_parallelism_before_L1_screening",
            },
            {
                "metric": "hbm_channel_count",
                "direction": "maximize",
                "weight": 0.20,
                "scale": 8.0,
                "role": "cheap_proxy_for_memory_bandwidth_before_L1_screening",
            },
            {
                "metric": "tile_doubles",
                "direction": "maximize",
                "weight": 0.05,
                "scale": 4096.0,
                "role": "cheap_proxy_for_locality_before_L1_screening",
            },
        ],
        "model_objective_boundary": (
            "pre_l1_candidate_ordering_only; L1 workflow model and later "
            "multi_fidelity feedback remain authoritative for promotion"
        ),
        "optimization_metrics": [
            "workflow_wall_time",
            "energy",
            "edp",
            "fpga_resource_pressure",
            "implementation_feasibility",
        ],
        "forbidden_shortcuts": [
            "single_kernel_speedup_as_workflow_result",
            "scf_only_as_final_boundary",
            "hls_report_without_implementation_feasibility",
        ],
    }
    return SearchProblem(
        problem_id="qe_mainflow_fpga_deployment_dse",
        workload_run_id=workload_run_id,
        objective="pareto_latency_energy_resource_feasibility",
        parameters=parameters,
        constraints=constraints,
        seed_candidates=seed_candidates,
    )


def build_qe_fpga_deployment_search_problem_from_workflow_contract(
    workflow_feature_contract: Mapping[str, Any],
    *,
    workload_run_id: str,
    manifest: Mapping[str, Any] | None = None,
) -> SearchProblem:
    """Build Step2 FPGA deployment search input from a workflow contract.

    The workflow feature contract is the authoritative Step1-to-Step2 method
    boundary.  QE mainflow manifests are accepted only as compatibility
    provenance for legacy callers and measured-SCF seed policy.
    """

    if not _workflow_feature_contract_is_valid(workflow_feature_contract):
        raise ValueError("valid workflow_feature_contract is required for contract-first QE FPGA DSE search construction")
    facts = _workflow_contract_search_facts(workflow_feature_contract)
    workflow_classes = facts["workflow_classes"]
    workflow_stage_types = facts["workflow_stage_types"]
    allow_measured_scf_seed = (
        isinstance(manifest, Mapping)
        and str(manifest.get("workflow_scope", "")) == "scf_only_measured_seed"
    )
    release_completion_eligible = (
        workflow_classes != ["scf"]
        and "post_processing" in workflow_classes
        and len(workflow_stage_types) >= 2
    )
    if not release_completion_eligible and not allow_measured_scf_seed:
        raise ValueError("QE FPGA deployment DSE requires a workflow_feature_contract with a multi-stage workflow, not an SCF-only slice")

    constraints = _qe_fpga_base_search_constraints(
        input_scope="qe_measured_scf_seed_model_input" if allow_measured_scf_seed else "qe_workflow_feature_contract",
        workflow_scope="scf_only_measured_seed" if allow_measured_scf_seed else "contract_full_qe_workflow",
        release_completion_eligible=release_completion_eligible,
        model_level_seed_only=allow_measured_scf_seed,
        workflow_coverage_limitations=(
            ["scf_only_measured_seed_missing_nscf_post_processing_relax_workflow_coverage"]
            if allow_measured_scf_seed
            else []
        ),
        workflow_stage_types=workflow_stage_types,
        workflow_classes=workflow_classes,
        kernel_kinds=facts["kernel_kinds"],
        physical_quantities=facts["physical_quantities"],
        dependency_edges=facts["workflow_dependency_edges"],
        data_artifacts=facts["workflow_data_artifacts"],
    )
    constraints.update({
        "search_problem_source": "workflow_feature_contract",
        "feature_source_priority": [
            "workflow_feature_contract",
            "qe_mainflow_manifest_compatibility_fallback",
        ],
        "manifest_compatibility_fallback_used": False,
        "workflow_feature_contract": {
            "schema_version": str(workflow_feature_contract.get("schema_version", "")),
            "domain_neutral": bool(workflow_feature_contract.get("domain_neutral", False)),
            "source_adapter": str(workflow_feature_contract.get("source_adapter", "")),
            "workload_family": str(workflow_feature_contract.get("workload_family", "")),
            "workflow_id": str(workflow_feature_contract.get("workflow_id", "")),
            "claim_boundary": str(workflow_feature_contract.get("claim_boundary", "")),
        },
        "workflow_stage_features": facts["workflow_stage_features"],
        "workflow_compute_features": facts["workflow_compute_features"],
        "workflow_correctness_observables": facts["workflow_correctness_observables"],
        "workflow_search_objectives": facts["workflow_search_objectives"],
        "workflow_model_update_policy": facts["workflow_model_update_policy"],
        "workflow_contract_statistics": facts["workflow_contract_statistics"],
    })
    return SearchProblem(
        problem_id="qe_mainflow_fpga_deployment_dse",
        workload_run_id=workload_run_id,
        objective="pareto_latency_energy_resource_feasibility",
        parameters=_qe_fpga_deployment_parameters(),
        constraints=constraints,
        seed_candidates=_qe_fpga_deployment_seed_candidates(),
    )


def _workflow_feature_contract_is_valid(contract: Mapping[str, Any]) -> bool:
    if not isinstance(contract, Mapping):
        return False
    if contract.get("schema_version") != "dse.workflow_feature_contract.v1":
        return False
    if contract.get("domain_neutral") is not True:
        return False
    if contract.get("source_adapter") != "qe_workflow_fpga_abstraction":
        return False
    if contract.get("claim_boundary") != "workflow_features_only_not_evidence_not_candidate_identity":
        return False
    return isinstance(contract.get("workflow_dag"), Mapping)


def _workflow_contract_search_facts(contract: Mapping[str, Any]) -> Dict[str, Any]:
    dag = contract.get("workflow_dag", {}) if isinstance(contract.get("workflow_dag"), Mapping) else {}
    stages = [row for row in dag.get("stages", []) or [] if isinstance(row, Mapping)]
    stage_features = [row for row in contract.get("stage_feature_table", []) or [] if isinstance(row, Mapping)]
    compute_features = [row for row in contract.get("compute_feature_table", []) or [] if isinstance(row, Mapping)]
    data_objects = [row for row in contract.get("data_object_table", []) or [] if isinstance(row, Mapping)]
    correctness = (
        contract.get("correctness_observable_table", {})
        if isinstance(contract.get("correctness_observable_table"), Mapping)
        else {}
    )
    workflow_stage_types = sorted({
        str(row.get("stage_type", ""))
        for row in stages
        if str(row.get("stage_type", ""))
    })
    workflow_classes = sorted({
        str(row.get("stage_class") or _stage_class(str(row.get("stage_type", ""))))
        for row in stages
        if str(row.get("stage_class") or row.get("stage_type") or "")
    })
    kernel_kinds = sorted({
        str(row.get("compute_id", ""))
        for row in compute_features
        if str(row.get("compute_id", ""))
    })
    workflow_edges = [
        {
            "source_stage": str(row.get("source_stage", "")),
            "target_stage": str(row.get("target_stage", "")),
            "dependency_kind": str(row.get("edge_kind", "workflow_dag_edge")),
            "tensor_name": str(row.get("tensor_name", "")),
            "estimated_bytes": int(_safe_int(row.get("estimated_bytes"), default=0)),
            "source": "workflow_feature_contract",
        }
        for row in dag.get("edges", []) or []
        if isinstance(row, Mapping)
    ]
    workflow_data_artifacts = [
        {
            "object_id": str(row.get("object_id", "")),
            "object_kind": str(row.get("object_kind", "")),
            "bytes": int(_safe_int(row.get("bytes"), default=0)),
            "producer_stages": [str(item) for item in row.get("producer_stages", []) or []],
            "consumer_stages": [str(item) for item in row.get("consumer_stages", []) or []],
            "lifetime": str(row.get("lifetime", "")),
            "residency_constraint": str(row.get("residency_constraint", "")),
            "transfer_sync_requirement": str(row.get("transfer_sync_requirement", "")),
            "source": "workflow_feature_contract",
        }
        for row in data_objects
        if str(row.get("object_id", ""))
    ]
    workflow_compute_features = [
        {
            "compute_id": str(row.get("compute_id", "")),
            "weight_seconds": _safe_float(row.get("weight_seconds"), default=0.0),
            "source_confidence": str(row.get("source_confidence", "")),
            "uncertainty": copy.deepcopy(dict(row.get("uncertainty", {}) if isinstance(row.get("uncertainty"), Mapping) else {})),
            "estimated_memory_bytes": int(_safe_int(row.get("estimated_memory_bytes"), default=0)),
            "estimated_flops": int(_safe_int(row.get("estimated_flops"), default=0)),
            "accelerator_candidate": bool(row.get("accelerator_candidate", False)),
            "host_retained_hint": bool(row.get("host_retained_hint", False)),
        }
        for row in compute_features
        if str(row.get("compute_id", ""))
    ]
    workflow_stage_features = [
        {
            "stage_id": str(row.get("stage_id", "")),
            "stage_type": str(row.get("stage_type", "")),
            "stage_class": str(row.get("stage_class") or _stage_class(str(row.get("stage_type", "")))),
            "program": str(row.get("program", "")),
            "dimensions": copy.deepcopy(dict(row.get("dimensions", {}) if isinstance(row.get("dimensions"), Mapping) else {})),
            "expected_repetition": int(_safe_int(row.get("expected_repetition"), default=1)),
            "host_control_barrier": bool(row.get("host_control_barrier", False)),
            "include_in_performance_model": bool(row.get("include_in_performance_model", True)),
            "observed_wall_seconds": _safe_float(row.get("observed_wall_seconds"), default=0.0),
            "source_confidence": str(row.get("source_confidence", "")),
        }
        for row in stage_features
        if str(row.get("stage_id", ""))
    ]
    physical_quantities = sorted({
        str(item)
        for item in correctness.get("workflow", []) or []
        if str(item)
    })
    search_objectives = [str(item) for item in contract.get("search_objectives", []) or [] if str(item)]
    model_update_policy = (
        copy.deepcopy(dict(contract.get("model_update_policy", {})))
        if isinstance(contract.get("model_update_policy"), Mapping)
        else {}
    )
    return {
        "workflow_stage_types": workflow_stage_types,
        "workflow_classes": workflow_classes,
        "kernel_kinds": kernel_kinds,
        "physical_quantities": physical_quantities,
        "workflow_dependency_edges": workflow_edges,
        "workflow_data_artifacts": workflow_data_artifacts,
        "workflow_stage_features": workflow_stage_features,
        "workflow_compute_features": workflow_compute_features,
        "workflow_correctness_observables": copy.deepcopy(dict(correctness)),
        "workflow_search_objectives": search_objectives,
        "workflow_model_update_policy": model_update_policy,
        "workflow_contract_statistics": {
            "stage_count": int(_safe_int(dag.get("stage_count"), default=len(stages))),
            "stage_feature_count": len(stage_features),
            "compute_feature_count": len(compute_features),
            "data_object_count": len(data_objects),
            "dependency_edge_count": len(workflow_edges),
            "accelerator_candidate_compute_count": sum(1 for row in compute_features if row.get("accelerator_candidate") is True),
            "host_retained_compute_count": sum(1 for row in compute_features if row.get("host_retained_hint") is True),
        },
    }


def _safe_float(value: Any, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(_safe_float(value, default=float(default)))
    except (TypeError, ValueError, OverflowError):
        return default


def _qe_fpga_deployment_parameters() -> Dict[str, List[Any]]:
    return {
        "deployment_target": [
            "fpga",
        ],
        "release_lane": [
            "release",
            "exploratory",
        ],
        "architecture_template": [
            "fpga_hbm_streaming_dataflow",
            "fpga_fft_transpose_pipeline",
            "fpga_hybrid_cpu_control_accel_kernels",
        ],
        "offload_boundary": [
            "workflow_hotspot_bundle",
            "stage_cluster_bundle",
            "kernel_callsite_bundle",
        ],
        "mapping_granularity": [
            "stage_phase",
            "kernel_callsite",
        ],
        "runtime_schedule": [
            "cpu_orchestrated_sequential",
            "overlap_dma_compute",
            "batched_stage_pipeline",
        ],
        "data_residency": [
            "host_resident_with_streaming_windows",
            "fpga_hbm_resident_hot_arrays",
            "hybrid_checkpointed_residency",
        ],
        "memory_topology": [
            "ddr_streaming",
            "hbm_multi_channel",
            "bram_uram_tiled_locality",
        ],
        "vector_lanes": [
            2,
            4,
            8,
        ],
        "hbm_channel_count": [
            0,
            4,
            8,
        ],
        "tile_doubles": [
            1024,
            2048,
            4096,
        ],
        "precision_policy": [
            "fp64_strict",
            "mixed_precision_candidate_requires_tolerance_review",
        ],
    }


def _qe_fpga_deployment_seed_candidates() -> List[Dict[str, Any]]:
    return [
        {
            "seed_id": "qe_fpga_hbm_streaming_workflow_seed",
            "deployment_target": "fpga",
            "release_lane": "release",
            "architecture_template": "fpga_hbm_streaming_dataflow",
            "offload_boundary": "workflow_hotspot_bundle",
            "mapping_granularity": "kernel_callsite",
            "runtime_schedule": "overlap_dma_compute",
            "data_residency": "fpga_hbm_resident_hot_arrays",
            "memory_topology": "hbm_multi_channel",
            "vector_lanes": 8,
            "hbm_channel_count": 8,
            "tile_doubles": 2048,
            "precision_policy": "fp64_strict",
            "source": "qe_workflow_dse_method_seed",
        },
        {
            "seed_id": "qe_fpga_cpu_control_hybrid_seed",
            "deployment_target": "fpga",
            "release_lane": "release",
            "architecture_template": "fpga_hybrid_cpu_control_accel_kernels",
            "offload_boundary": "stage_cluster_bundle",
            "mapping_granularity": "stage_phase",
            "runtime_schedule": "cpu_orchestrated_sequential",
            "data_residency": "host_resident_with_streaming_windows",
            "memory_topology": "ddr_streaming",
            "vector_lanes": 2,
            "hbm_channel_count": 0,
            "tile_doubles": 1024,
            "precision_policy": "fp64_strict",
            "source": "qe_workflow_dse_method_seed",
        },
        {
            "seed_id": "qe_fpga_mid_tier_tiled_seed",
            "deployment_target": "fpga",
            "release_lane": "release",
            "architecture_template": "fpga_fft_transpose_pipeline",
            "offload_boundary": "stage_cluster_bundle",
            "mapping_granularity": "kernel_callsite",
            "runtime_schedule": "batched_stage_pipeline",
            "data_residency": "hybrid_checkpointed_residency",
            "memory_topology": "hbm_multi_channel",
            "vector_lanes": 4,
            "hbm_channel_count": 4,
            "tile_doubles": 2048,
            "precision_policy": "fp64_strict",
            "source": "qe_workflow_dse_method_seed",
        },
    ]


def _qe_fpga_base_search_constraints(
    *,
    input_scope: str,
    workflow_scope: str,
    release_completion_eligible: bool,
    model_level_seed_only: bool,
    workflow_coverage_limitations: Sequence[str],
    workflow_stage_types: Sequence[str],
    workflow_classes: Sequence[str],
    kernel_kinds: Sequence[str],
    physical_quantities: Sequence[str],
    dependency_edges: Sequence[Mapping[str, Any]],
    data_artifacts: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    return {
        "input_scope": input_scope,
        "workflow_scope": workflow_scope,
        "release_completion_eligible": release_completion_eligible,
        "model_level_seed_only": model_level_seed_only,
        "workflow_coverage_limitations": list(workflow_coverage_limitations),
        "workflow_stage_types": list(workflow_stage_types),
        "workflow_classes": list(workflow_classes),
        "requires_post_processing_stage": "post_processing" in set(workflow_classes),
        "kernel_kinds": list(kernel_kinds),
        "physical_quantities": list(physical_quantities),
        "workflow_dependency_edges": [dict(row) for row in dependency_edges],
        "workflow_data_artifacts": [dict(row) for row in data_artifacts],
        "deployment_target": "fpga",
        "required_parameters": [
            "deployment_target",
            "release_lane",
            "architecture_template",
            "offload_boundary",
            "mapping_granularity",
            "runtime_schedule",
            "data_residency",
            "memory_topology",
            "vector_lanes",
            "hbm_channel_count",
            "tile_doubles",
            "precision_policy",
        ],
        "formal_pareto_lane_field": "release_lane",
        "release_lane": "release",
        "proposal_only_before_model_promotion": True,
        "fail_closed_candidate_budget": True,
        "coverage_axes": [
            "architecture_template",
            "offload_boundary",
            "mapping_granularity",
            "runtime_schedule",
            "data_residency",
            "memory_topology",
            "vector_lanes",
            "hbm_channel_count",
            "tile_doubles",
        ],
        "feedback_generalization_axes": [
            "architecture_template",
            "offload_boundary",
            "mapping_granularity",
            "runtime_schedule",
            "data_residency",
            "memory_topology",
        ],
        "feedback_generalization_strength": 0.15,
        "requires_physical_evidence": True,
        "legal_values": {
            "deployment_target": ["fpga"],
            "precision_policy": ["fp64_strict"],
        },
        "cross_axis_constraints": [
            {
                "rule_id": "hbm_topology_requires_positive_hbm_channels",
                "when": {"memory_topology": "hbm_multi_channel"},
                "require": {"hbm_channel_count": {"gt": 0}},
                "blocker": "illegal_hbm_channel_count_for_hbm_topology",
            },
            {
                "rule_id": "non_hbm_topology_requires_zero_hbm_channels",
                "when": {"memory_topology": {"ne": "hbm_multi_channel"}},
                "require": {"hbm_channel_count": 0},
                "blocker": "illegal_hbm_channel_count_for_non_hbm_topology",
            },
        ],
        "model_objectives": [
            {
                "metric": "vector_lanes",
                "direction": "maximize",
                "weight": 0.25,
                "scale": 8.0,
                "role": "cheap_proxy_for_candidate_compute_parallelism_before_L1_screening",
            },
            {
                "metric": "hbm_channel_count",
                "direction": "maximize",
                "weight": 0.20,
                "scale": 8.0,
                "role": "cheap_proxy_for_memory_bandwidth_before_L1_screening",
            },
            {
                "metric": "tile_doubles",
                "direction": "maximize",
                "weight": 0.05,
                "scale": 4096.0,
                "role": "cheap_proxy_for_locality_before_L1_screening",
            },
        ],
        "model_objective_boundary": (
            "pre_l1_candidate_ordering_only; L1 workflow model and later "
            "multi_fidelity feedback remain authoritative for promotion"
        ),
        "optimization_metrics": [
            "workflow_wall_time",
            "energy",
            "edp",
            "fpga_resource_pressure",
            "implementation_feasibility",
        ],
        "forbidden_shortcuts": [
            "single_kernel_speedup_as_workflow_result",
            "scf_only_as_final_boundary",
            "hls_report_without_implementation_feasibility",
        ],
    }


def _workflow_dependency_edges_from_cases(cases: Sequence[Any]) -> List[Dict[str, Any]]:
    edges_by_key: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        sequence = case.get("baseline_sequence", []) or []
        if not isinstance(sequence, Sequence) or isinstance(sequence, (str, bytes)):
            continue
        previous_step_id: str | None = None
        for index, step in enumerate(sequence):
            if not isinstance(step, Mapping):
                continue
            step_id = str(step.get("step_id") or f"step_{index:02d}")
            if previous_step_id is not None:
                key = (str(case.get("case_id", "qe_case")), previous_step_id, step_id)
                edges_by_key.setdefault(key, {
                    "case_id": key[0],
                    "source_step_id": previous_step_id,
                    "target_step_id": step_id,
                    "dependency_kind": "baseline_sequence_order",
                })
            previous_step_id = step_id
    return [edges_by_key[key] for key in sorted(edges_by_key)]


def _workflow_data_artifacts_from_cases(cases: Sequence[Any]) -> List[Dict[str, Any]]:
    artifacts_by_path: Dict[str, Dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        for artifact in case.get("input_artifacts", []) or []:
            if not isinstance(artifact, Mapping):
                continue
            path = str(artifact.get("path") or "")
            if not path:
                continue
            artifacts_by_path.setdefault(path, {
                "path": path,
                "purpose": str(artifact.get("purpose", "unknown")),
                "sha256": str(artifact.get("sha256", "")),
            })
    return [artifacts_by_path[key] for key in sorted(artifacts_by_path)]


def qe_patch_runtime_manifest_schema(*, status: str = "draft") -> Dict[str, Any]:
    """Return the machine-readable QE patch/runtime manifest schema contract."""
    return {
        "schema_version": QE_PATCH_RUNTIME_MANIFEST_SCHEMA,
        "status": status,
        "required_row_fields": list(REQUIRED_PATCH_ROW_FIELDS),
        "trusted_status_rules": [
            "fallback_path is required for every accelerated/refactored QE path",
            "tolerance_impact is required for every accelerated/refactored QE path",
            "performance_impact is recorded but never substitutes for correctness evidence",
        ],
        "qe_specific_fields_scope": "reference_workloads_or_runtime_extension_payloads_only",
    }


def example_qe_patch_runtime_manifest(*, status: str = "draft") -> Dict[str, Any]:
    """Build a minimal valid patch/runtime manifest row for tests and examples."""
    row = {
        "patch_id": "qe_hpsi_extension_payload_v1",
        "workload_case_id": "qe_si_scf_small_v1",
        "changed_files": ["runtime_api/qe_extension_payload.h"],
        "transformed_kernels": ["h_psi"],
        "changed_assumptions": ["extension payload carries kernel dimensions; core descriptor remains generic"],
        "data_layout_policy": "column_major_complex_fp64_preserved_at_QE_boundary",
        "precision_policy": "complex_fp64_no_relaxed_precision_without_new_tolerance_review",
        "fallback_path": "pure_software_qe_kernel_path",
        "tolerance_impact": {
            "kernel_absolute_tolerance_delta": 0.0,
            "kernel_relative_tolerance_delta": 0.0,
            "scf_physical_tolerance_delta": 0.0,
            "review_required": False,
        },
        "performance_impact": {
            "expected_direction": "speedup_possible",
            "claim_boundary": "projection_until_L4_and_correctness_pass",
        },
    }
    manifest = {
        "schema_version": QE_PATCH_RUNTIME_MANIFEST_SCHEMA,
        "status": status,
        "rows": [row],
    }
    manifest["manifest_hash"] = _stable_json_hash(_without_hash(manifest, "manifest_hash"))
    return manifest


def _is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


def validate_qe_patch_runtime_manifest(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate QE patch/runtime rows and block trusted status on missing safety fields."""
    errors: List[Dict[str, Any]] = []
    trusted_blocks: List[Dict[str, Any]] = []
    if manifest.get("schema_version") != QE_PATCH_RUNTIME_MANIFEST_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected QE patch/runtime manifest schema"})
    rows = manifest.get("rows", [])
    if not isinstance(rows, list) or not rows:
        errors.append({"field": "rows", "message": "at least one patch/runtime row is required"})
        rows = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append({"field": f"rows[{index}]", "message": "row must be an object"})
            continue
        for field in REQUIRED_PATCH_ROW_FIELDS:
            if _is_empty(row.get(field)):
                error = {"field": f"rows[{index}].{field}", "message": "required patch/runtime field is missing"}
                errors.append(error)
                if field in {"fallback_path", "tolerance_impact"}:
                    trusted_blocks.append({**error, "patch_id": row.get("patch_id", f"row_{index}")})
        tolerance_impact = row.get("tolerance_impact")
        if isinstance(tolerance_impact, Mapping) and any(value is None for value in tolerance_impact.values()):
            trusted_blocks.append({"field": f"rows[{index}].tolerance_impact", "message": "tolerance impact cannot contain null values", "patch_id": row.get("patch_id", f"row_{index}")})
    return {
        "schema_version": QE_PATCH_RUNTIME_MANIFEST_VALIDATION_SCHEMA,
        "valid": not errors,
        "trusted_status_allowed": not trusted_blocks and not errors,
        "row_count": len(rows),
        "errors": errors,
        "trusted_blocks": trusted_blocks,
    }


__all__ = [
    "POST_PROCESSING_STAGE_TYPES",
    "QE_MAINFLOW_WORKLOAD_SUITE_SCHEMA",
    "QE_MAINFLOW_WORKLOAD_SUITE_VALIDATION_SCHEMA",
    "QE_PATCH_RUNTIME_MANIFEST_SCHEMA",
    "QE_PATCH_RUNTIME_MANIFEST_VALIDATION_SCHEMA",
    "RELAX_STAGE_TYPES",
    "REQUIRED_CASE_FIELDS",
    "REQUIRED_MAINFLOW_CLASSES",
    "REQUIRED_PATCH_ROW_FIELDS",
    "default_qe_mainflow_workload_suite",
    "example_qe_patch_runtime_manifest",
    "build_qe_fpga_deployment_search_problem",
    "build_qe_fpga_deployment_search_problem_from_workflow_contract",
    "package_qe_mainflow_case",
    "qe_patch_runtime_manifest_schema",
    "qe_workload_case_to_step1_source",
    "validate_qe_mainflow_workload_suite",
    "validate_qe_patch_runtime_manifest",
    "workflow_bundle_from_qe_mainflow_manifest",
]
