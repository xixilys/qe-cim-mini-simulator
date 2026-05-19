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
    "package_qe_mainflow_case",
    "qe_patch_runtime_manifest_schema",
    "qe_workload_case_to_step1_source",
    "validate_qe_mainflow_workload_suite",
    "validate_qe_patch_runtime_manifest",
]
