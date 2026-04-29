from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from . import domain_contracts


class WorkloadAdapter(Protocol):
    name: str

    def detect(self, payload: Mapping[str, Any]) -> bool:
        ...

    def identity(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def domain_extension(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def workload_anchor_refs(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def application_graph(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def correctness_contract(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def legacy_aliases(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class QeWorkloadAdapter:
    name: str = "qe"

    def detect(self, payload: Mapping[str, Any]) -> bool:
        return domain_contracts.is_qe_workload(payload)

    def identity(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        identity = domain_contracts.workload_identity(payload)
        identity["app_adapter"] = "qe"
        identity["domain"] = identity.get("domain") or "dft"
        return identity

    def domain_extension(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return domain_contracts.domain_extension(payload)

    def workload_anchor_refs(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return domain_contracts.workload_anchor_refs(payload)

    def application_graph(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return domain_contracts.build_application_graph_ir(payload)

    def correctness_contract(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "correctness_contract_ref_v0",
            "correctness_contract_id": payload.get("correctness_contract_id")
            or payload.get("qe_tolerance_schema_id")
            or "not_applicable",
            "claim_ceiling": "correctness_contract_reference_only",
            "qe_equivalent_scf_claim": False,
        }

    def legacy_aliases(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {"qe_anchor_refs": domain_contracts.qe_anchor_refs_compat(payload)}


@dataclass(frozen=True)
class GenericTraceAdapter:
    name: str = "generic_trace"

    def detect(self, payload: Mapping[str, Any]) -> bool:
        return not domain_contracts.is_qe_workload(payload)

    def identity(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        identity = domain_contracts.workload_identity(payload)
        identity["app_adapter"] = identity.get("app_adapter") or "generic_trace"
        identity["domain"] = identity.get("domain") or "generic"
        return identity

    def domain_extension(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {}

    def workload_anchor_refs(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return domain_contracts.workload_anchor_refs(payload)

    def application_graph(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return domain_contracts.build_application_graph_ir(payload)

    def correctness_contract(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "correctness_contract_ref_v0",
            "correctness_contract_id": payload.get("correctness_contract_id") or "not_applicable",
            "claim_ceiling": "correctness_contract_reference_only",
            "workload_equivalent_claim": False,
        }

    def legacy_aliases(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {}


@dataclass(frozen=True)
class SyntheticKernelAdapter:
    name: str
    kernel_type: str
    op_type: str
    math_tags: tuple[str, ...]

    def detect(self, payload: Mapping[str, Any]) -> bool:
        adapter = payload.get("app_adapter") or payload.get("adapter")
        kernel = payload.get("kernel_type")
        return adapter == self.name or kernel == self.kernel_type

    def identity(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        identity = domain_contracts.workload_identity(payload)
        identity["app_adapter"] = self.name
        identity["domain"] = payload.get("domain") or "synthetic_kernel"
        return identity

    def domain_extension(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "synthetic_kernel": {
                "kernel_type": self.kernel_type,
                "shape": dict(payload.get("shape", {}))
                if isinstance(payload.get("shape"), Mapping)
                else {},
                "operation_count": payload.get("operation_count"),
            }
        }

    def workload_anchor_refs(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return domain_contracts.workload_anchor_refs(payload)

    def application_graph(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        patched = dict(payload)
        patched.setdefault(
            "application_nodes",
            [
                {
                    "node_id": self.kernel_type,
                    "op_type": self.op_type,
                    "math_tags": list(self.math_tags),
                    "data_objects": list(payload.get("data_objects", [])),
                    "control_role": "hotpath",
                    "candidate_mappings": ["software", "fpga", "asic", "systemc_proxy"],
                    "precision_contract": payload.get("precision_contract", "workload_defined"),
                    "correctness_contract": payload.get("correctness_contract_id", "synthetic_reference"),
                    "hotpath": True,
                }
            ],
        )
        patched.setdefault("application_edges", [])
        return domain_contracts.build_application_graph_ir(patched)

    def correctness_contract(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "correctness_contract_ref_v0",
            "correctness_contract_id": payload.get("correctness_contract_id")
            or f"{self.kernel_type}_reference_contract_v0",
            "claim_ceiling": "correctness_contract_reference_only",
            "workload_equivalent_claim": False,
        }

    def legacy_aliases(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {}


class SyntheticGemmAdapter(SyntheticKernelAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="synthetic_gemm",
            kernel_type="gemm",
            op_type="dense_matrix_multiply",
            math_tags=("dense_linear_algebra", "gemm"),
        )


class SyntheticStencilAdapter(SyntheticKernelAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="synthetic_stencil",
            kernel_type="stencil",
            op_type="structured_grid_stencil",
            math_tags=("stencil", "structured_grid"),
        )


class SyntheticSpmvAdapter(SyntheticKernelAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="synthetic_spmv",
            kernel_type="spmv",
            op_type="sparse_matrix_vector_multiply",
            math_tags=("sparse_linear_algebra", "spmv"),
        )


ADAPTERS: tuple[WorkloadAdapter, ...] = (
    QeWorkloadAdapter(),
    SyntheticGemmAdapter(),
    SyntheticStencilAdapter(),
    SyntheticSpmvAdapter(),
    GenericTraceAdapter(),
)


def detect_workload_adapter(payload: Mapping[str, Any]) -> WorkloadAdapter:
    for adapter in ADAPTERS:
        if adapter.detect(payload):
            return adapter
    return GenericTraceAdapter()


def workload_sidecar_bundle(payload: Mapping[str, Any]) -> dict[str, Any]:
    adapter = detect_workload_adapter(payload)
    return {
        "adapter_name": adapter.name,
        "workload_identity": adapter.identity(payload),
        "domain_extension": adapter.domain_extension(payload),
        "workload_anchor_refs": adapter.workload_anchor_refs(payload),
        "application_graph": adapter.application_graph(payload),
        "correctness_contract": adapter.correctness_contract(payload),
        "legacy_aliases": adapter.legacy_aliases(payload),
    }
