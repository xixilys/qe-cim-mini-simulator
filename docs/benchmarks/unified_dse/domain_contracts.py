from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


CANDIDATE_DESCRIPTOR_SCHEMA_VERSION = "candidate_descriptor_v0"
BACKEND_EXECUTION_REQUEST_SCHEMA_VERSION = "backend_execution_request_v0"
BACKEND_EXECUTION_REPORT_SCHEMA_VERSION = "backend_execution_report_v0"
WORKLOAD_ANCHOR_REFS_SCHEMA_VERSION = "workload_anchor_refs_v0"
APP_GRAPH_IR_SCHEMA_VERSION = "app_graph_ir_v0"
ARCHITECTURE_TEMPLATE_IR_SCHEMA_VERSION = "architecture_template_ir_v0"
MAPPING_IR_SCHEMA_VERSION = "mapping_ir_v0"
EVIDENCE_IR_SCHEMA_VERSION = "evidence_ir_v0"
MULTI_FIDELITY_PLAN_SCHEMA_VERSION = "multi_fidelity_plan_v0"
RELEASE_BUNDLE_SCHEMA_VERSION = "release_bundle_v0"

DESCRIPTOR_ONLY_CLAIM_CEILING = "descriptor_only"
FAST_MODEL_SCREENING_CLAIM_CEILING = "fast_model_screening_only"
FAST_MODEL_CALIBRATED_CLAIM_CEILING = "fast_model_calibrated_screening_only"
SYSTEMC_PROXY_CLAIM_CEILING = "systemc_proxy_only"
GEM5_SMOKE_CLAIM_CEILING = "gem5_smoke_only"
GEM5_TIMED_CLAIM_CEILING = "gem5_timed_only"
CORRECTNESS_CLAIM_CEILING = "correctness_only"
IMPLEMENTATION_CLAIM_CEILING = "implementation_evidence_only"
BOARD_MEASURED_CLAIM_CEILING = "board_physical_measured_only"
BACKEND_REPORT_REFERENCE_CLAIM_CEILING = "backend_report_reference_only"

# The canonical enum is intentionally wider than the current frontend can produce,
# because external backends must be able to report higher-fidelity evidence while
# the frontend keeps its own claim posture bounded.
CLAIM_CEILING_ENUM = {
    DESCRIPTOR_ONLY_CLAIM_CEILING,
    FAST_MODEL_SCREENING_CLAIM_CEILING,
    FAST_MODEL_CALIBRATED_CLAIM_CEILING,
    SYSTEMC_PROXY_CLAIM_CEILING,
    GEM5_SMOKE_CLAIM_CEILING,
    GEM5_TIMED_CLAIM_CEILING,
    CORRECTNESS_CLAIM_CEILING,
    IMPLEMENTATION_CLAIM_CEILING,
    BOARD_MEASURED_CLAIM_CEILING,
    BACKEND_REPORT_REFERENCE_CLAIM_CEILING,
    # Backward-compatible ceilings already present in Gate-A fixtures.
    "stage_a_screening_only",
    "timed_functional_proxy_contract_only",
    "timed_functional_proxy_feedback_only",
    "trace_calibrated_proxy_feedback_only",
    "systemc_standalone_proxy_only",
    "systemc_timed_functional_proxy_only",
    "gem5_systemc_timed_proxy_only",
    "systemc_config_descriptor_only",
    "stage_b0_handoff_descriptor_only",
    "descriptor_generation_only",
    "anchor_reference_only",
    "gem5_systemc_smoke_only",
    "qe_equivalent_scf_correctness_only",
    "correctness_report_reference_only",
    "implementation_evidence_reference_only",
    "hls_synthesis_only",
    "rtl_simulation_only",
    "fpga_board_measurement_only",
    "openroad_physical_estimate_only",
    "asic_ppa_estimate_only",
}

EXECUTION_STATUS_ENUM = {
    "not_executed",
    "planned",
    "screened",
    "executed",
    "partial",
    "failed",
    "refused",
    "external_artifact_referenced",
}

FIDELITY_ENUM = {
    "descriptor_only",
    "fast_model_screening",
    "systemc_smoke",
    "systemc_standalone",
    "systemc_timed_functional",
    "gem5_smoke",
    "gem5_systemc_smoke",
    "gem5_timed",
    "gem5_systemc_timed_proxy",
    "qe_correctness",
    "implementation_evidence",
    "board_physical_measured",
    # Backward-compatible Stage labels used by handoff plans.
    "B0",
    "B1",
    "B2",
    "B3",
    "B4",
}

TARGET_CLASS_ENUM = {"fpga", "asic", "cpu_only_baseline", "simulated_accelerator", "unknown"}

BACKEND_METRICS_REQUIRED_GROUPS = [
    "time_to_completion_s",
    "device_busy_s",
    "host_wait_s",
    "dma_read_bytes",
    "dma_write_bytes",
    "bytes_moved_to_convergence",
    "resident_reuse_ratio",
    "fallback_ratio",
    "spill_ratio",
    "cycle_proxy",
]

_CANONICAL_CEILINGS_BY_FIDELITY = {
    "descriptor_only": {DESCRIPTOR_ONLY_CLAIM_CEILING, "descriptor_generation_only"},
    "fast_model_screening": {
        FAST_MODEL_SCREENING_CLAIM_CEILING,
        FAST_MODEL_CALIBRATED_CLAIM_CEILING,
    },
    "systemc_smoke": {SYSTEMC_PROXY_CLAIM_CEILING, "systemc_timed_functional_proxy_only"},
    "systemc_standalone": {SYSTEMC_PROXY_CLAIM_CEILING, "systemc_standalone_proxy_only"},
    "systemc_timed_functional": {
        SYSTEMC_PROXY_CLAIM_CEILING,
        "systemc_timed_functional_proxy_only",
        "timed_functional_proxy_feedback_only",
        "trace_calibrated_proxy_feedback_only",
    },
    "gem5_smoke": {GEM5_SMOKE_CLAIM_CEILING, "gem5_systemc_smoke_only"},
    "gem5_systemc_smoke": {GEM5_SMOKE_CLAIM_CEILING, "gem5_systemc_smoke_only"},
    "gem5_timed": {GEM5_TIMED_CLAIM_CEILING},
    "gem5_systemc_timed_proxy": {GEM5_TIMED_CLAIM_CEILING, "gem5_systemc_timed_proxy_only"},
    "qe_correctness": {
        CORRECTNESS_CLAIM_CEILING,
        "qe_equivalent_scf_correctness_only",
        "correctness_report_reference_only",
    },
    "implementation_evidence": {
        IMPLEMENTATION_CLAIM_CEILING,
        "implementation_evidence_reference_only",
        "hls_synthesis_only",
        "rtl_simulation_only",
        "fpga_board_measurement_only",
        "openroad_physical_estimate_only",
        "asic_ppa_estimate_only",
    },
    "board_physical_measured": {
        BOARD_MEASURED_CLAIM_CEILING,
        "fpga_board_measurement_only",
    },
}


@dataclass(frozen=True)
class ApplicationGraphIR:
    app_id: str
    domain: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    schema_version: str = APP_GRAPH_IR_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ApplicationGraphIR":
        return cls(
            schema_version=str(payload.get("schema_version", APP_GRAPH_IR_SCHEMA_VERSION)),
            app_id=str(payload.get("app_id", "unknown_app")),
            domain=str(payload.get("domain", "generic")),
            nodes=[dict(item) for item in payload.get("nodes", [])],
            edges=[dict(item) for item in payload.get("edges", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "app_id": self.app_id,
            "domain": self.domain,
            "nodes": deepcopy(self.nodes),
            "edges": deepcopy(self.edges),
        }


@dataclass(frozen=True)
class ArchitectureTemplateIR:
    template_id: str
    target_classes: list[str]
    components: list[dict[str, Any]]
    knobs: dict[str, Any]
    schema_version: str = ARCHITECTURE_TEMPLATE_IR_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ArchitectureTemplateIR":
        return cls(
            schema_version=str(payload.get("schema_version", ARCHITECTURE_TEMPLATE_IR_SCHEMA_VERSION)),
            template_id=str(payload.get("template_id", "unknown_template")),
            target_classes=list(payload.get("target_classes", [])),
            components=[dict(item) for item in payload.get("components", [])],
            knobs=dict(payload.get("knobs", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "template_id": self.template_id,
            "target_classes": list(self.target_classes),
            "components": deepcopy(self.components),
            "knobs": deepcopy(self.knobs),
        }


@dataclass(frozen=True)
class MappingIR:
    mapped_nodes: dict[str, Any]
    control_policy: dict[str, Any]
    schema_version: str = MAPPING_IR_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MappingIR":
        return cls(
            schema_version=str(payload.get("schema_version", MAPPING_IR_SCHEMA_VERSION)),
            mapped_nodes=dict(payload.get("mapped_nodes", {})),
            control_policy=dict(payload.get("control_policy", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mapped_nodes": deepcopy(self.mapped_nodes),
            "control_policy": deepcopy(self.control_policy),
        }


@dataclass(frozen=True)
class EvidenceIR:
    candidate_id: str
    fidelity: str
    execution_status: str
    metrics: dict[str, Any]
    claim_ceiling: str
    non_claims: list[str]
    backend_class: str = "unknown_backend"
    source_kind: str = "unknown_source"
    correctness_gate: dict[str, Any] | None = None
    artifact_refs: dict[str, Any] | None = None
    schema_version: str = EVIDENCE_IR_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvidenceIR":
        return cls(
            schema_version=str(payload.get("schema_version", EVIDENCE_IR_SCHEMA_VERSION)),
            candidate_id=str(payload.get("candidate_id", "unknown_candidate")),
            backend_class=str(payload.get("backend_class", "unknown_backend")),
            source_kind=str(payload.get("source_kind", "unknown_source")),
            fidelity=str(payload.get("fidelity", "descriptor_only")),
            execution_status=str(payload.get("execution_status", "not_executed")),
            metrics=dict(payload.get("metrics", {})),
            claim_ceiling=str(payload.get("claim_ceiling", DESCRIPTOR_ONLY_CLAIM_CEILING)),
            correctness_gate=dict(payload.get("correctness_gate", {})),
            non_claims=list(payload.get("non_claims", [])),
            artifact_refs=dict(payload.get("artifact_refs", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "backend_class": self.backend_class,
            "source_kind": self.source_kind,
            "fidelity": self.fidelity,
            "execution_status": self.execution_status,
            "metrics": deepcopy(self.metrics),
            "claim_ceiling": self.claim_ceiling,
            "correctness_gate": deepcopy(self.correctness_gate or {}),
            "non_claims": list(self.non_claims),
            "artifact_refs": deepcopy(self.artifact_refs or {}),
        }


@dataclass(frozen=True)
class BackendCapability:
    backend_class: str
    supported_fidelities: list[str]
    supports_device_diag_engine: bool
    target_resource_model: bool
    report_schema_version: str = BACKEND_EXECUTION_REPORT_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BackendCapability":
        return cls(
            backend_class=str(payload.get("backend_class", "unknown_backend")),
            supported_fidelities=[str(item) for item in payload.get("supported_fidelities", [])],
            supports_device_diag_engine=bool(payload.get("supports_device_diag_engine", False)),
            target_resource_model=bool(payload.get("target_resource_model", False)),
            report_schema_version=str(
                payload.get("report_schema_version", BACKEND_EXECUTION_REPORT_SCHEMA_VERSION)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "backend_capability_metadata_v0",
            "backend_class": self.backend_class,
            "supported_fidelities": list(self.supported_fidelities),
            "supports_device_diag_engine": self.supports_device_diag_engine,
            "target_resource_model": self.target_resource_model,
            "report_schema_version": self.report_schema_version,
        }


def _require_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"expected mapping field: {key}")
    return value


def _require_list(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"expected list field: {key}")
    return value


def validate_application_graph_ir(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != APP_GRAPH_IR_SCHEMA_VERSION:
        raise ValueError("unsupported application graph schema_version")
    if not payload.get("app_id"):
        raise ValueError("application graph requires app_id")
    if not payload.get("domain"):
        raise ValueError("application graph requires domain")
    nodes = _require_list(payload, "nodes")
    _require_list(payload, "edges")
    seen: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            raise ValueError(f"application graph node {index} must be a mapping")
        node_id = str(node.get("node_id", ""))
        if not node_id:
            raise ValueError(f"application graph node {index} requires node_id")
        if node_id in seen:
            raise ValueError(f"duplicate application graph node_id: {node_id}")
        seen.add(node_id)
        if not node.get("op_type"):
            raise ValueError(f"application graph node {node_id} requires op_type")


def validate_architecture_template_ir(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != ARCHITECTURE_TEMPLATE_IR_SCHEMA_VERSION:
        raise ValueError("unsupported architecture template schema_version")
    if not payload.get("template_id"):
        raise ValueError("architecture template requires template_id")
    target_classes = _require_list(payload, "target_classes")
    for target_class in target_classes:
        if str(target_class) not in TARGET_CLASS_ENUM:
            raise ValueError(f"unsupported target class: {target_class}")
    components = _require_list(payload, "components")
    _require_mapping(payload, "knobs")
    seen: set[str] = set()
    for index, component in enumerate(components):
        if not isinstance(component, Mapping):
            raise ValueError(f"architecture component {index} must be a mapping")
        component_id = str(component.get("component_id", ""))
        if not component_id:
            raise ValueError(f"architecture component {index} requires component_id")
        if component_id in seen:
            raise ValueError(f"duplicate architecture component_id: {component_id}")
        seen.add(component_id)
        if not component.get("type"):
            raise ValueError(f"architecture component {component_id} requires type")


def validate_mapping_ir(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != MAPPING_IR_SCHEMA_VERSION:
        raise ValueError("unsupported mapping schema_version")
    mapped_nodes = _require_mapping(payload, "mapped_nodes")
    _require_mapping(payload, "control_policy")
    if not mapped_nodes:
        raise ValueError("mapping requires at least one mapped node")


def validate_evidence_ir(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != EVIDENCE_IR_SCHEMA_VERSION:
        raise ValueError("unsupported evidence schema_version")
    required = (
        "candidate_id",
        "backend_class",
        "source_kind",
        "fidelity",
        "execution_status",
        "metrics",
        "claim_ceiling",
        "correctness_gate",
        "non_claims",
        "artifact_refs",
    )
    for key in required:
        if key not in payload:
            raise ValueError(f"evidence missing field: {key}")
    if str(payload["fidelity"]) not in FIDELITY_ENUM:
        raise ValueError("unsupported evidence fidelity")
    if str(payload["execution_status"]) not in EXECUTION_STATUS_ENUM:
        raise ValueError("unsupported evidence execution_status")
    if str(payload["claim_ceiling"]) not in CLAIM_CEILING_ENUM:
        raise ValueError("unsupported evidence claim_ceiling")
    if not isinstance(payload["metrics"], Mapping):
        raise ValueError("evidence metrics must be a mapping")
    if not isinstance(payload["correctness_gate"], Mapping):
        raise ValueError("evidence correctness_gate must be a mapping")
    if not isinstance(payload["non_claims"], list):
        raise ValueError("evidence non_claims must be a list")
    if not isinstance(payload["artifact_refs"], Mapping):
        raise ValueError("evidence artifact_refs must be a mapping")


def claim_ceiling_allowed_for_fidelity(fidelity: str, claim_ceiling: str) -> bool:
    allowed = _CANONICAL_CEILINGS_BY_FIDELITY.get(fidelity)
    if allowed is None:
        return claim_ceiling in CLAIM_CEILING_ENUM
    return claim_ceiling in allowed


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    return {}


def _clean_token(value: Any) -> str:
    token = str(value) if value not in (None, "") else "unknown"
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in token)


def _meaningful(value: Any) -> bool:
    return value not in (None, "", "not_applicable", "unknown")


def _is_qe_payload(workload: Mapping[str, Any]) -> bool:
    app_adapter = workload.get("app_adapter") or workload.get("adapter")
    domain = workload.get("domain")
    domain_implies_qe = (
        domain in {"dft", "qe"}
        and app_adapter in (None, "", "not_applicable", "qe")
    )
    if app_adapter == "qe" or domain_implies_qe:
        return True
    return any(
        _meaningful(workload.get(key))
        for key in (
            "qe_tolerance_schema_id",
            "pseudopotential_family",
            "solver_path_class",
            "projector_pressure",
            "nonlocal_pressure",
        )
    )


def is_qe_workload(workload: Any) -> bool:
    return _is_qe_payload(_payload(workload))


def backend_workload_adapter_name(workload: Any, app_adapter: Any | None = None) -> str:
    payload = _payload(workload)
    adapter = str(app_adapter or payload.get("app_adapter") or payload.get("adapter") or "")
    adapter_lc = adapter.lower()
    kernel_type = str(payload.get("kernel_type") or "").lower()
    if _is_qe_payload(payload):
        return "qe"
    if adapter_lc.startswith("synthetic_") or kernel_type in {"gemm", "stencil", "spmv"}:
        return "synthetic"
    if (
        adapter_lc in {"", "generic", "generic_trace", "trace"}
        or adapter_lc.endswith("_trace")
        or adapter_lc.endswith("-trace")
    ):
        return "generic"
    return adapter


def workload_identity(workload: Any) -> dict[str, Any]:
    payload = _payload(workload)
    domain = payload.get("domain") or ("dft" if _is_qe_payload(payload) else "generic")
    app_adapter = (
        payload.get("app_adapter")
        or payload.get("adapter")
        or ("qe" if domain == "dft" and _is_qe_payload(payload) else "generic_trace")
    )
    backend_adapter = backend_workload_adapter_name(payload, app_adapter)
    correctness_contract_id = (
        payload.get("correctness_contract_id")
        or payload.get("qe_tolerance_schema_id")
        or "not_applicable"
    )
    identity = {
        "workload_id": payload.get("workload_id"),
        "workload_group_id": payload.get("workload_group_id"),
        "domain": domain,
        "app_adapter": app_adapter,
        "adapter": backend_adapter,
        "correctness_contract_id": correctness_contract_id,
        "accounting_boundary_id": payload.get("accounting_boundary_id"),
        "fairness_policy_id": payload.get("fairness_policy_id"),
        "power_boundary_id": payload.get("power_boundary_id"),
        "observability_contract_id": payload.get("observability_contract_id"),
    }
    if str(app_adapter) != backend_adapter:
        identity["adapter_detail"] = app_adapter
    return identity


def qe_domain_extension(workload: Any) -> dict[str, Any]:
    payload = _payload(workload)
    return {
        "case_id": payload.get("case_id") or payload.get("workload_id"),
        "qe_tolerance_schema_id": payload.get("qe_tolerance_schema_id")
        or payload.get("correctness_contract_id"),
        "pseudopotential_family": payload.get("pseudopotential_family"),
        "solver_path_class": payload.get("solver_path_class"),
        "projector_pressure": payload.get("projector_pressure"),
        "nonlocal_pressure": payload.get("nonlocal_pressure"),
        "qe_equivalent_scf_claim": False,
    }


def domain_extension(workload: Any) -> dict[str, Any]:
    payload = _payload(workload)
    identity = workload_identity(payload)
    if identity["app_adapter"] == "qe" or _is_qe_payload(payload):
        return {"qe": qe_domain_extension(payload)}
    if str(identity.get("app_adapter", "")).startswith("synthetic_") or payload.get("kernel_type") in {
        "gemm",
        "stencil",
        "spmv",
    }:
        return {
            "synthetic_kernel": {
                "kernel_type": payload.get("kernel_type")
                or str(identity.get("app_adapter", "")).removeprefix("synthetic_"),
                "shape": dict(payload.get("shape", {}))
                if isinstance(payload.get("shape"), Mapping)
                else {},
                "operation_count": payload.get("operation_count"),
            }
        }
    return {}


def workload_anchor_refs(workload: Any) -> dict[str, Any]:
    payload = _payload(workload)
    return {
        "schema_version": WORKLOAD_ANCHOR_REFS_SCHEMA_VERSION,
        "status": "trace_or_correctness_anchor_only",
        "workload_id": payload.get("workload_id"),
        "case_id": payload.get("case_id") or payload.get("workload_id"),
        "workload_group_id": payload.get("workload_group_id"),
        "signature_id": payload.get("signature_id"),
        "trace_ref": payload.get("trace_ref"),
        "dump_ref": payload.get("dump_ref"),
        "correctness_anchor_ref": payload.get("correctness_anchor_ref"),
        "anchor_evidence_kind": payload.get("anchor_evidence_kind")
        or "missing_or_trace_only",
        "workload_equivalent_claim": False,
        "claim_ceiling": "anchor_reference_only",
    }


def qe_anchor_refs_compat(workload: Any) -> dict[str, Any]:
    if not is_qe_workload(workload):
        return {}
    anchors = workload_anchor_refs(workload)
    payload = _payload(workload)
    return {
        "schema_version": "qe_anchor_refs_v0",
        "status": anchors["status"],
        "qe_equivalent_scf_claim": False,
        "claim_ceiling": anchors["claim_ceiling"],
        "workload_id": anchors["workload_id"],
        "case_id": anchors["case_id"],
        "workload_group_id": anchors["workload_group_id"],
        "signature_id": anchors["signature_id"],
        "qe_tolerance_schema_id": payload.get("qe_tolerance_schema_id")
        or payload.get("correctness_contract_id"),
        "trace_ref": anchors["trace_ref"],
        "dump_ref": anchors["dump_ref"],
        "correctness_anchor_ref": anchors["correctness_anchor_ref"],
        "anchor_evidence_kind": anchors["anchor_evidence_kind"],
    }


def mapping_ref(design_point: Any) -> str:
    point = _payload(design_point)
    keys = (
        point.get("family"),
        point.get("diag_policy"),
        point.get("offload_scope"),
        point.get("resident_policy"),
        point.get("partition_strategy"),
    )
    return "mapping_" + "__".join(_clean_token(value) for value in keys)


def application_graph_ref(workload: Any) -> str:
    identity = workload_identity(workload)
    return f"application_graphs/{_clean_token(identity.get('workload_id'))}.json"


def architecture_template_ref(architecture_template_id: str) -> str:
    return f"architecture_templates/{_clean_token(architecture_template_id)}.json"


def mapping_sidecar_ref(design_point: Any) -> str:
    return f"mappings/{mapping_ref(design_point)}.json"


def candidate_descriptor_ref(candidate_id: str) -> str:
    return f"candidate_descriptors/{_clean_token(candidate_id)}.json"


def candidate_identity(
    candidate_id: str,
    design_point: Any,
    architecture_template_id: str,
    target_class: str,
    backend_profile_id: str,
    source_kind: str,
    validity_class: str | None = None,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "architecture_template_id": architecture_template_id,
        "target_class": target_class,
        "backend_profile_id": backend_profile_id,
        "source_kind": source_kind,
        "validity_class": str(validity_class or "invalid"),
        "design_axes": _payload(design_point),
    }


def build_application_graph_ir(workload: Any) -> dict[str, Any]:
    payload = _payload(workload)
    identity = workload_identity(payload)
    if is_qe_workload(payload):
        nodes = [
            {
                "node_id": "h_psi",
                "op_type": "operator_apply",
                "math_tags": ["fft", "projector", "complex_vector"],
                "data_objects": ["psi", "beta_projectors", "veff"],
                "control_role": "hotpath",
                "candidate_mappings": ["software", "fpga", "asic", "systemc_proxy"],
                "precision_contract": "fp64_required",
                "correctness_contract": payload.get("correctness_contract_id")
                or payload.get("qe_tolerance_schema_id")
                or "qe_gold_tolerance_reference",
                "hotpath": True,
            },
            {
                "node_id": "reduced_build",
                "op_type": "subspace_reduced_build",
                "math_tags": ["gram_matrix", "complex_gemm"],
                "data_objects": ["partial_h", "partial_s"],
                "control_role": "hotpath",
                "candidate_mappings": ["software", "fpga", "asic", "systemc_proxy"],
                "precision_contract": "fp64_required",
                "correctness_contract": payload.get("correctness_contract_id")
                or "qe_subspace_matrix_equivalence_reference",
                "hotpath": True,
            },
            {
                "node_id": "diag",
                "op_type": "cdiaghg",
                "math_tags": ["generalized_hermitian_eigensolve"],
                "data_objects": ["reduced_h", "reduced_s", "eigenpairs"],
                "control_role": "hotpath",
                "candidate_mappings": ["software", "fpga", "asic", "systemc_proxy"],
                "precision_contract": "fp64_required",
                "correctness_contract": payload.get("correctness_contract_id")
                or "qe_diag_equivalence_reference",
                "hotpath": True,
            },
            {
                "node_id": "refresh_residual",
                "op_type": "refresh_residual",
                "math_tags": ["vector_update", "residual_norm"],
                "data_objects": ["eigenvectors", "residuals"],
                "control_role": "hotpath",
                "candidate_mappings": ["software", "fpga", "asic", "systemc_proxy"],
                "precision_contract": "fp64_required",
                "correctness_contract": payload.get("correctness_contract_id")
                or "qe_refresh_residual_reference",
                "hotpath": True,
            },
        ]
        edges = [
            {
                "from": "h_psi",
                "to": "reduced_build",
                "src": "h_psi",
                "dst": "reduced_build",
                "edge_type": "data_dependency",
                "kind": "subspace_vectors",
                "objects": ["partial_h", "partial_s"],
            },
            {
                "from": "reduced_build",
                "to": "diag",
                "src": "reduced_build",
                "dst": "diag",
                "edge_type": "data_dependency",
                "kind": "reduced_matrices",
                "objects": ["reduced_h", "reduced_s"],
            },
            {
                "from": "diag",
                "to": "refresh_residual",
                "src": "diag",
                "dst": "refresh_residual",
                "edge_type": "data_dependency",
                "kind": "eigenpairs",
                "objects": ["eigenpairs"],
            },
        ]
    else:
        nodes = [dict(item) for item in payload.get("application_nodes", [])]
        edges = [dict(item) for item in payload.get("application_edges", [])]
        if not nodes:
            kernel_type = str(payload.get("kernel_type") or "").lower()
            synthetic_op_types = {
                "gemm": ("dense_matrix_multiply", ["dense_linear_algebra", "gemm"]),
                "stencil": ("structured_grid_stencil", ["stencil", "structured_grid"]),
                "spmv": ("sparse_matrix_vector_multiply", ["sparse_linear_algebra", "spmv"]),
            }
            op_type, math_tags = synthetic_op_types.get(
                kernel_type,
                (payload.get("kernel_type", "generic_trace_kernel"), list(payload.get("math_tags", []))),
            )
            nodes = [
                {
                    "node_id": kernel_type or "kernel_0",
                    "op_type": op_type,
                    "math_tags": math_tags,
                    "data_objects": list(payload.get("data_objects", [])),
                    "control_role": "hotpath",
                    "candidate_mappings": ["software", "fpga", "asic", "systemc_proxy"],
                    "precision_contract": payload.get("precision_contract", "workload_defined"),
                    "correctness_contract": payload.get(
                        "correctness_contract_id",
                        "not_applicable",
                    ),
                    "hotpath": True,
                }
            ]
    graph = ApplicationGraphIR(
        app_id=str(identity.get("workload_id") or "unknown_workload"),
        domain=str(identity.get("domain") or "generic"),
        nodes=nodes,
        edges=edges,
    ).to_dict()
    validate_application_graph_ir(graph)
    return graph


def build_architecture_template_ir(
    architecture_template_id: str,
    design_point: Any,
    target_class: str,
) -> dict[str, Any]:
    point = _payload(design_point)
    components = [
        {
            "component_id": "host_runtime",
            "type": "software_runtime",
            "status": "descriptor",
            "roles": ["control", "fallback", "baseline"],
        },
        {
            "component_id": "device_orchestrator",
            "type": "accelerator_runtime",
            "status": "descriptor",
            "roles": ["submission", "completion", "synchronization"],
        },
        {
            "component_id": "operator_engine",
            "type": "compute_engine",
            "status": "descriptor",
            "roles": ["operator_apply", "kernel_execution"],
        },
        {
            "component_id": "local_memory",
            "type": "memory",
            "status": "descriptor",
            "roles": ["resident_objects", "spill_buffer"],
        },
        {
            "component_id": "host_device_link",
            "type": "interconnect",
            "status": "descriptor",
            "roles": ["dma", "control_events"],
        },
        {
            "component_id": f"family_{_clean_token(point.get('family'))}",
            "type": "architecture_family",
            "status": "descriptor",
        },
    ]
    target = target_class if target_class in TARGET_CLASS_ENUM else "unknown"
    template = ArchitectureTemplateIR(
        template_id=architecture_template_id,
        target_classes=[target],
        components=components,
        knobs={
            "design_axes": point,
            "parallel_units": point.get("parallel_units", "family_default"),
            "pipeline_depth": point.get("pipeline_depth", "family_default"),
            "dma_channels": point.get("dma_channels", "backend_profile_default"),
            "resident_policy": point.get("resident_policy"),
            "resource_model_ref": point.get("resource_model_ref", "unresolved_descriptor_only"),
            "realization_status": "descriptor_only_until_backend_realization",
        },
    ).to_dict()
    validate_architecture_template_ir(template)
    return template


def build_mapping_ir(design_point: Any, workload: Any | None = None) -> dict[str, Any]:
    point = _payload(design_point)
    if workload is not None:
        graph = build_application_graph_ir(workload)
        node_ids = [str(node.get("node_id")) for node in graph.get("nodes", []) if node.get("node_id")]
    else:
        node_ids = ["h_psi", "reduced_build", "diag", "refresh_residual"]
    mapped_nodes: dict[str, Any] = {}
    for node_id in node_ids:
        if node_id == "diag":
            mapped_nodes[node_id] = point.get("diag_policy", "unknown")
        elif node_id == "reduced_build":
            mapped_nodes[node_id] = point.get("partition_strategy", "unknown")
        elif node_id == "refresh_residual":
            mapped_nodes[node_id] = point.get("resident_policy", "unknown")
        else:
            mapped_nodes[node_id] = point.get("offload_scope", "unknown")
    mapping = MappingIR(
        mapped_nodes=mapped_nodes,
        control_policy={
            "submission": "async_descriptor_until_backend_realization",
            "diag_policy": point.get("diag_policy", "unknown"),
            "buffering": "double_buffer_descriptor",
            "fallback": (
                "host_diag_allowed"
                if point.get("diag_policy") in {"cpu_only", "device_first_fallback"}
                else "device_diag_required"
            ),
            "host_device_event_sequence": [
                "host_submit",
                "device_process",
                "host_collect",
            ],
            "resolution_status": "descriptor_only_unresolved",
        },
    ).to_dict()
    validate_mapping_ir(mapping)
    return mapping


def build_candidate_descriptor(
    *,
    candidate_id: str,
    workload: Any,
    design_point: Any,
    architecture_template_id: str,
    target_class: str,
    backend_profile_id: str,
    source_kind: str,
    design_validation: Mapping[str, Any],
) -> dict[str, Any]:
    validity_class = str(design_validation.get("validity_class", "invalid"))
    claim_ceiling = (
        FAST_MODEL_SCREENING_CLAIM_CEILING
        if source_kind == "fast_model_screening"
        else DESCRIPTOR_ONLY_CLAIM_CEILING
    )
    return {
        "schema_version": CANDIDATE_DESCRIPTOR_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "application_graph_ref": application_graph_ref(workload),
        "architecture_template_ref": architecture_template_ref(architecture_template_id),
        "mapping_ref": mapping_sidecar_ref(design_point),
        "target_class": target_class,
        "validity_class": validity_class,
        "claim_ceiling_before_execution": claim_ceiling,
        "workload_identity": workload_identity(workload),
        "candidate_identity": candidate_identity(
            candidate_id,
            design_point,
            architecture_template_id,
            target_class,
            backend_profile_id,
            source_kind,
            validity_class=validity_class,
        ),
        "design_validation": deepcopy(dict(design_validation)),
        "domain_extension": domain_extension(workload),
        "non_claims": [
            "not_systemc_executed",
            "not_gem5_executed",
            "not_workload_equivalent_correctness",
            "not_fpga_board_measured",
        ],
    }


def _unresolved_placeholder(kind: str, value: Any) -> dict[str, Any]:
    return {
        "status": "unresolved_descriptor_only",
        "kind": kind,
        "value": deepcopy(value),
        "resolution_required_before_backend_execution": True,
    }


def backend_capability_profile_for_execution_mode(execution_mode: str) -> dict[str, Any]:
    profile = {
        "schema_version": "backend_capability_profile_v0",
        "profile_kind": "requested_execution_mode_gate",
        "execution_mode": execution_mode,
        "supports_systemc_standalone": False,
        "supports_systemc_timed_functional": False,
        "supports_systemc_timed": False,
        "supports_gem5_smoke": False,
        "supports_gem5_timed_proxy": False,
        "supports_real_bridge": False,
        "claim_ceiling": DESCRIPTOR_ONLY_CLAIM_CEILING,
        "non_claims": [
            "capability_profile_is_request_shape_not_execution_evidence",
            "not_systemc_executed",
            "not_gem5_executed",
            "not_real_bridge_proven",
        ],
    }
    if execution_mode == "systemc_standalone":
        profile["supports_systemc_standalone"] = True
    elif execution_mode == "systemc_timed_functional":
        profile["supports_systemc_timed_functional"] = True
        profile["supports_systemc_timed"] = True
    elif execution_mode == "gem5_systemc_smoke":
        profile["supports_gem5_smoke"] = True
    elif execution_mode == "gem5_systemc_timed_proxy":
        profile["supports_gem5_timed_proxy"] = True
    return profile


def backend_metrics_contract() -> dict[str, Any]:
    return {
        "schema_version": "backend_metrics_contract_v0",
        "contract_kind": "required_metric_groups_for_backend_report_shape",
        "required_groups": list(BACKEND_METRICS_REQUIRED_GROUPS),
        "required_for_claim": False,
        "claim_ceiling": DESCRIPTOR_ONLY_CLAIM_CEILING,
        "non_claims": [
            "metrics_contract_does_not_claim_backend_execution",
            "metrics_contract_does_not_claim_qe_correctness",
            "not_metrics_contract_board_or_physical_measurement_claim",
        ],
    }


def build_backend_execution_request(
    *,
    candidate_id: str,
    workload: Any,
    design_point: Any,
    architecture_template_id: str,
    target_class: str,
    backend_profile_id: str,
    source_kind: str,
    systemc_config_ref: str,
    execution_mode: str = "systemc_timed_functional",
    requested_fidelity: str = "B2",
    design_validation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    point = _payload(design_point)
    if design_validation is None:
        from . import constraints

        design_validation_payload = constraints.validate_design_point(point, _payload(workload))
    else:
        design_validation_payload = dict(design_validation)
    validity_class = str(design_validation_payload.get("validity_class", "invalid"))
    app_ref = application_graph_ref(workload)
    arch_ref = architecture_template_ref(architecture_template_id)
    map_ref = mapping_sidecar_ref(design_point)
    return {
        "schema_version": BACKEND_EXECUTION_REQUEST_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "workload_identity": workload_identity(workload),
        "candidate_identity": candidate_identity(
            candidate_id,
            design_point,
            architecture_template_id,
            target_class,
            backend_profile_id,
            source_kind,
            validity_class=validity_class,
        ),
        "execution_mode": execution_mode,
        "requested_fidelity": requested_fidelity,
        "input_refs": {
            "application_graph": app_ref,
            "architecture_template": arch_ref,
            "mapping": map_ref,
            "systemc_config": systemc_config_ref,
            "proxy_runtime": None,
        },
        "systemc_config": {
            "cluster_graph": _unresolved_placeholder("cluster_graph", []),
            "resident_object_map": _unresolved_placeholder("resident_object_map", {}),
            "dma_plan": _unresolved_placeholder("dma_plan", {}),
            "timing_profile_id": backend_profile_id,
        },
        "software_runtime": {
            "mode": "proxy_runtime",
            "control_policy": _unresolved_placeholder("control_policy", "sync"),
            "host_device_event_sequence": _unresolved_placeholder(
                "host_device_event_sequence",
                ["host_submit", "device_process", "host_collect"],
            ),
        },
        "expected_report_schema": BACKEND_EXECUTION_REPORT_SCHEMA_VERSION,
        "backend_capability_requirements": {
            "requested_fidelity": requested_fidelity,
            "requires_device_diag_engine": point.get("diag_policy") == "aggressive_device",
            "requires_target_resource_model": True,
            "requires_host_device_link_model": point.get("offload_scope") == "device_heavy",
            "target_class": target_class or "unknown",
        },
        "backend_capability_profile": backend_capability_profile_for_execution_mode(
            execution_mode
        ),
        "metrics_contract": backend_metrics_contract(),
        "claim_ceiling": DESCRIPTOR_ONLY_CLAIM_CEILING,
        "domain_extension": domain_extension(workload),
        "non_claims": [
            "not_systemc_executed",
            "not_gem5_executed",
            "not_qe_correctness_executed",
            "not_workload_equivalent_correctness",
            "not_rtl_hls_evidence",
            "not_fpga_board_measured",
            "not_physical_measurement",
        ],
    }


def validate_backend_execution_report(payload: Mapping[str, Any]) -> None:
    required = (
        "schema_version",
        "candidate_id",
        "backend_class",
        "source_kind",
        "fidelity",
        "execution_status",
        "metrics",
        "claim_ceiling",
        "correctness_gate",
        "non_claims",
        "artifact_refs",
    )
    for key in required:
        if key not in payload:
            raise ValueError(f"backend execution report missing field: {key}")
    if payload["schema_version"] != BACKEND_EXECUTION_REPORT_SCHEMA_VERSION:
        raise ValueError("unsupported backend execution report schema_version")
    if not payload.get("candidate_id"):
        raise ValueError("backend execution report candidate_id is required")
    if str(payload["execution_status"]) not in EXECUTION_STATUS_ENUM:
        raise ValueError("unsupported backend execution report execution_status")
    if str(payload["fidelity"]) not in FIDELITY_ENUM:
        raise ValueError("unsupported backend execution report fidelity")
    if str(payload["claim_ceiling"]) not in CLAIM_CEILING_ENUM:
        raise ValueError("unsupported backend execution report claim_ceiling")
    if not claim_ceiling_allowed_for_fidelity(str(payload["fidelity"]), str(payload["claim_ceiling"])):
        raise ValueError("backend execution report claim_ceiling exceeds fidelity")
    if not isinstance(payload["metrics"], Mapping):
        raise ValueError("backend execution report metrics must be a mapping")
    if not isinstance(payload["correctness_gate"], Mapping):
        raise ValueError("backend execution report correctness_gate must be a mapping")
    if not isinstance(payload["non_claims"], list):
        raise ValueError("backend execution report non_claims must be a list")
    if not isinstance(payload["artifact_refs"], Mapping):
        raise ValueError("backend execution report artifact_refs must be a mapping")


def evidence_from_backend_execution_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    validate_backend_execution_report(payload)
    return EvidenceIR(
        candidate_id=str(payload["candidate_id"]),
        backend_class=str(payload["backend_class"]),
        source_kind=str(payload["source_kind"]),
        fidelity=str(payload["fidelity"]),
        execution_status=str(payload["execution_status"]),
        metrics=dict(payload["metrics"]),
        claim_ceiling=str(payload["claim_ceiling"]),
        correctness_gate=dict(payload["correctness_gate"]),
        non_claims=list(payload["non_claims"]),
        artifact_refs=dict(payload["artifact_refs"]),
    ).to_dict()
