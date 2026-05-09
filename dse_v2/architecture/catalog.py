#!/usr/bin/env python3
"""Architecture catalog schema and seed families for generic DSE.

The catalog is deliberately separated from mapping/search/reporting code. It
owns reusable architecture families, concrete instances, component definitions,
constraints, simulation-binding metadata, status labels, and the minimum
DesignPoint payload needed by downstream lanes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


class ArchitectureStatus:
    """Canonical architecture and binding status labels for P2."""

    IMPLEMENTED = "implemented"
    UNVERIFIED = "unverified"
    PROTOTYPE = "prototype"
    STUB = "stub"
    PLANNED = "planned"
    UNSUPPORTED = "unsupported"
    CANDIDATE_ONLY = "candidate-only"
    TRUSTED_FINAL_ELIGIBLE = "trusted-final-eligible"


ALLOWED_STATUS_LABELS = {
    ArchitectureStatus.IMPLEMENTED,
    ArchitectureStatus.UNVERIFIED,
    ArchitectureStatus.PROTOTYPE,
    ArchitectureStatus.STUB,
    ArchitectureStatus.PLANNED,
    ArchitectureStatus.UNSUPPORTED,
    ArchitectureStatus.CANDIDATE_ONLY,
    ArchitectureStatus.TRUSTED_FINAL_ELIGIBLE,
}

TRUSTED_BINDING_BACKENDS = {"systemc", "gem5_systemc"}
TRUSTED_BINDING_STATUSES = {
    ArchitectureStatus.IMPLEMENTED,
    ArchitectureStatus.TRUSTED_FINAL_ELIGIBLE,
}


@dataclass(frozen=True)
class ArchitectureParameter:
    """Parameterized family knob with validation metadata."""

    name: str
    kind: str
    default: Any
    allowed_values: Optional[Sequence[Any]] = None
    value_range: Optional[Tuple[float, float]] = None
    unit: str = ""
    description: str = ""

    def validate_value(self, value: Any) -> Optional[str]:
        if self.allowed_values is not None and value not in self.allowed_values:
            return f"parameter {self.name}={value!r} is not in allowed values {list(self.allowed_values)!r}"
        if self.value_range is not None:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return f"parameter {self.name}={value!r} is not numeric for range check"
            lo, hi = self.value_range
            if numeric < lo or numeric > hi:
                return f"parameter {self.name}={numeric} outside range [{lo}, {hi}]"
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "default": self.default,
            "allowed_values": list(self.allowed_values) if self.allowed_values is not None else None,
            "range": list(self.value_range) if self.value_range is not None else None,
            "unit": self.unit,
            "description": self.description,
        }


@dataclass(frozen=True)
class ComponentType:
    """Reusable component type in the architecture catalog."""

    component_type_id: str
    category: str
    description: str
    supported_ops: Sequence[str] = field(default_factory=list)
    precision_support: Sequence[str] = field(default_factory=lambda: ["FP64"])
    default_attributes: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component_type_id": self.component_type_id,
            "category": self.category,
            "description": self.description,
            "supported_ops": list(self.supported_ops),
            "precision_support": list(self.precision_support),
            "default_attributes": dict(self.default_attributes),
        }


@dataclass(frozen=True)
class ComponentInstance:
    """Concrete component instance inside an architecture instance."""

    component_id: str
    component_type_id: str
    role: str
    status: str = ArchitectureStatus.UNVERIFIED
    supported_ops: Sequence[str] = field(default_factory=list)
    precision_support: Sequence[str] = field(default_factory=lambda: ["FP64"])
    memory_bytes: int = 0
    bandwidth_gbps: float = 0.0
    power_w: float = 0.0
    area_mm2: float = 0.0
    connected_to: Sequence[str] = field(default_factory=list)
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component_id": self.component_id,
            "component_type_id": self.component_type_id,
            "role": self.role,
            "status": self.status,
            "supported_ops": list(self.supported_ops),
            "precision_support": list(self.precision_support),
            "memory_bytes": self.memory_bytes,
            "bandwidth_gbps": self.bandwidth_gbps,
            "power_w": self.power_w,
            "area_mm2": self.area_mm2,
            "connected_to": list(self.connected_to),
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class ConstraintSet:
    """Catalog-level constraints checked before an instance is trusted."""

    max_power_w: Optional[float] = None
    max_area_mm2: Optional[float] = None
    min_memory_bytes: int = 0
    required_routes: Sequence[Tuple[str, str]] = field(default_factory=list)
    required_ops: Sequence[str] = field(default_factory=list)
    notes: Sequence[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_power_w": self.max_power_w,
            "max_area_mm2": self.max_area_mm2,
            "min_memory_bytes": self.min_memory_bytes,
            "required_routes": [list(route) for route in self.required_routes],
            "required_ops": list(self.required_ops),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class SimulationBinding:
    """SystemC/gem5 binding metadata used to gate trusted eligibility."""

    binding_id: str
    backend: str
    status: str
    adapter: str
    executable: Optional[str] = None
    supported_ops: Sequence[str] = field(default_factory=list)
    required_artifacts: Sequence[str] = field(default_factory=list)
    unavailable_reason: str = ""
    notes: Sequence[str] = field(default_factory=list)

    def is_trusted_eligible(self) -> bool:
        return self.backend in TRUSTED_BINDING_BACKENDS and self.status in TRUSTED_BINDING_STATUSES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "backend": self.backend,
            "status": self.status,
            "adapter": self.adapter,
            "executable": self.executable,
            "supported_ops": list(self.supported_ops),
            "required_artifacts": list(self.required_artifacts),
            "unavailable_reason": self.unavailable_reason,
            "notes": list(self.notes),
            "trusted_eligible": self.is_trusted_eligible(),
        }


@dataclass(frozen=True)
class ArchitectureFamily:
    """Reusable architecture family definition."""

    family_id: str
    name: str
    description: str
    parameters: Sequence[ArchitectureParameter] = field(default_factory=list)
    component_template: Mapping[str, Any] = field(default_factory=dict)
    default_status: str = ArchitectureStatus.CANDIDATE_ONLY
    extension_rules: Sequence[str] = field(default_factory=list)
    binding_requirements: Mapping[str, str] = field(default_factory=dict)

    def default_parameters(self) -> Dict[str, Any]:
        return {parameter.name: parameter.default for parameter in self.parameters}

    def validate_parameters(self, values: Mapping[str, Any]) -> List[str]:
        errors: List[str] = []
        known = {parameter.name: parameter for parameter in self.parameters}
        for key in values:
            if key not in known:
                errors.append(f"unknown parameter {key!r} for family {self.family_id}")
        for parameter in self.parameters:
            value = values.get(parameter.name, parameter.default)
            error = parameter.validate_value(value)
            if error:
                errors.append(error)
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family_id": self.family_id,
            "name": self.name,
            "description": self.description,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "component_template": dict(self.component_template),
            "default_status": self.default_status,
            "extension_rules": list(self.extension_rules),
            "binding_requirements": dict(self.binding_requirements),
        }


@dataclass(frozen=True)
class ArchitectureInstance:
    """Concrete architecture candidate emitted by the catalog."""

    architecture_id: str
    family_id: str
    parameters: Mapping[str, Any]
    components: Sequence[ComponentInstance]
    memory_hierarchy: Mapping[str, Any]
    interconnect_topology: Mapping[str, Any]
    constraints: ConstraintSet = field(default_factory=ConstraintSet)
    simulation_bindings: Mapping[str, str] = field(default_factory=dict)  # backend -> binding_id
    status: str = ArchitectureStatus.CANDIDATE_ONLY
    legacy_reference: bool = False
    notes: Sequence[str] = field(default_factory=list)

    def total_memory_bytes(self) -> int:
        component_memory = sum(max(0, component.memory_bytes) for component in self.components)
        explicit_memory = int(self.memory_hierarchy.get("total_capacity_bytes", 0) or 0)
        return max(component_memory, explicit_memory)

    def total_power_w(self) -> float:
        return sum(max(0.0, component.power_w) for component in self.components)

    def total_area_mm2(self) -> float:
        return sum(max(0.0, component.area_mm2) for component in self.components)

    def supported_ops(self) -> List[str]:
        ops = sorted({op for component in self.components for op in component.supported_ops})
        return ops

    def has_route(self, source: str, target: str) -> bool:
        if source == target:
            return True
        direct = {(component.component_id, peer) for component in self.components for peer in component.connected_to}
        return (source, target) in direct or (target, source) in direct

    def trusted_final_eligible(self, bindings: Mapping[str, SimulationBinding]) -> bool:
        if self.legacy_reference or self.status not in {ArchitectureStatus.IMPLEMENTED, ArchitectureStatus.TRUSTED_FINAL_ELIGIBLE}:
            return False
        return any(
            binding_id in bindings and bindings[binding_id].is_trusted_eligible()
            for binding_id in self.simulation_bindings.values()
        )

    def candidate_only_reason(self, bindings: Mapping[str, SimulationBinding]) -> Optional[str]:
        if self.legacy_reference:
            return "legacy/reference architecture; available for comparison only"
        if self.status == ArchitectureStatus.CANDIDATE_ONLY:
            return "architecture status is candidate-only"
        if not self.trusted_final_eligible(bindings):
            return "no implemented SystemC/gem5+SystemC binding is attached"
        return None

    def minimum_design_point_payload(
        self,
        *,
        workload_id: str,
        mapping: Optional[Mapping[str, str]] = None,
        data_placement: Optional[Mapping[str, str]] = None,
        scheduling_policy: str = "static",
        precision_policy: Optional[Mapping[str, Any]] = None,
        fallback_policy: Optional[Mapping[str, Any]] = None,
        simulation_config: Optional[Mapping[str, Any]] = None,
        output_config: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Emit the P2.3 minimum DesignPoint payload without hidden state."""
        return {
            "design_point_id": f"{workload_id}::{self.architecture_id}",
            "workload_id": workload_id,
            "architecture_instance": self.to_dict(include_bindings=True),
            "component_parameters": dict(self.parameters),
            "memory_hierarchy": dict(self.memory_hierarchy),
            "interconnect_topology": dict(self.interconnect_topology),
            "mapping": dict(mapping or {}),
            "data_placement": dict(data_placement or {}),
            "scheduling_policy": scheduling_policy,
            "precision_policy": dict(precision_policy or {"default": "FP64"}),
            "fallback_policy": dict(fallback_policy or {"unsupported_ops": "host_fallback_and_mark_untrusted"}),
            "simulation_config": dict(simulation_config or {"backend_preference": ["systemc", "gem5_systemc"]}),
            "output_config": dict(output_config or {"evidence_mode": "summary"}),
            "constraints": self.constraints.to_dict(),
        }

    def to_dict(self, include_bindings: bool = True) -> Dict[str, Any]:
        payload = {
            "architecture_id": self.architecture_id,
            "family_id": self.family_id,
            "parameters": dict(self.parameters),
            "components": [component.to_dict() for component in self.components],
            "memory_hierarchy": dict(self.memory_hierarchy),
            "interconnect_topology": dict(self.interconnect_topology),
            "constraints": self.constraints.to_dict(),
            "status": self.status,
            "legacy_reference": self.legacy_reference,
            "notes": list(self.notes),
        }
        if include_bindings:
            payload["simulation_bindings"] = dict(self.simulation_bindings)
        return payload


@dataclass(frozen=True)
class CatalogValidationMessage:
    """Structured validation result for catalog checks."""

    severity: str
    item_id: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {"severity": self.severity, "item_id": self.item_id, "message": self.message}


@dataclass
class ArchitectureCatalog:
    """Top-level P2 architecture catalog."""

    version: str
    families: Dict[str, ArchitectureFamily] = field(default_factory=dict)
    component_types: Dict[str, ComponentType] = field(default_factory=dict)
    simulation_bindings: Dict[str, SimulationBinding] = field(default_factory=dict)
    instances: Dict[str, ArchitectureInstance] = field(default_factory=dict)

    def add_family(self, family: ArchitectureFamily) -> ArchitectureCatalog:
        self.families[family.family_id] = family
        return self

    def add_component_type(self, component_type: ComponentType) -> ArchitectureCatalog:
        self.component_types[component_type.component_type_id] = component_type
        return self

    def add_binding(self, binding: SimulationBinding) -> ArchitectureCatalog:
        self.simulation_bindings[binding.binding_id] = binding
        return self

    def add_instance(self, instance: ArchitectureInstance) -> ArchitectureCatalog:
        self.instances[instance.architecture_id] = instance
        return self

    def trusted_final_eligible_instances(self) -> List[ArchitectureInstance]:
        return [
            instance
            for instance in self.instances.values()
            if instance.trusted_final_eligible(self.simulation_bindings)
        ]

    def candidate_only_instances(self) -> List[ArchitectureInstance]:
        return [
            instance
            for instance in self.instances.values()
            if instance.candidate_only_reason(self.simulation_bindings) is not None
        ]

    def validate(self) -> List[CatalogValidationMessage]:
        messages: List[CatalogValidationMessage] = []
        messages.extend(self._validate_families())
        messages.extend(self._validate_component_types())
        messages.extend(self._validate_bindings())
        messages.extend(self._validate_instances())
        return messages

    def raise_if_invalid(self) -> None:
        errors = [message for message in self.validate() if message.severity == "error"]
        if errors:
            formatted = "; ".join(f"{error.item_id}: {error.message}" for error in errors)
            raise ValueError(f"invalid architecture catalog: {formatted}")

    def _validate_families(self) -> List[CatalogValidationMessage]:
        messages: List[CatalogValidationMessage] = []
        for family in self.families.values():
            if family.default_status not in ALLOWED_STATUS_LABELS:
                messages.append(CatalogValidationMessage("error", family.family_id, f"invalid family status {family.default_status!r}"))
            parameter_names = [parameter.name for parameter in family.parameters]
            if len(parameter_names) != len(set(parameter_names)):
                messages.append(CatalogValidationMessage("error", family.family_id, "duplicate parameter names"))
            messages.extend(
                CatalogValidationMessage("error", family.family_id, error)
                for error in family.validate_parameters(family.default_parameters())
            )
        return messages

    def _validate_component_types(self) -> List[CatalogValidationMessage]:
        messages: List[CatalogValidationMessage] = []
        for component_type in self.component_types.values():
            if not component_type.category:
                messages.append(CatalogValidationMessage("error", component_type.component_type_id, "component category is required"))
            if not component_type.precision_support:
                messages.append(CatalogValidationMessage("error", component_type.component_type_id, "precision_support must not be empty"))
        return messages

    def _validate_bindings(self) -> List[CatalogValidationMessage]:
        messages: List[CatalogValidationMessage] = []
        for binding in self.simulation_bindings.values():
            if binding.status not in ALLOWED_STATUS_LABELS:
                messages.append(CatalogValidationMessage("error", binding.binding_id, f"invalid binding status {binding.status!r}"))
            if binding.backend in TRUSTED_BINDING_BACKENDS and binding.status in TRUSTED_BINDING_STATUSES and not binding.required_artifacts:
                messages.append(CatalogValidationMessage("error", binding.binding_id, "trusted binding must declare required artifacts"))
            if binding.status in {ArchitectureStatus.UNSUPPORTED, ArchitectureStatus.STUB, ArchitectureStatus.PLANNED} and not binding.unavailable_reason:
                messages.append(CatalogValidationMessage("warning", binding.binding_id, "blocked/non-executable binding should include unavailable_reason"))
        return messages

    def _validate_instances(self) -> List[CatalogValidationMessage]:
        messages: List[CatalogValidationMessage] = []
        for instance in self.instances.values():
            messages.extend(self._validate_instance(instance))
        return messages

    def _validate_instance(self, instance: ArchitectureInstance) -> List[CatalogValidationMessage]:
        messages: List[CatalogValidationMessage] = []
        item_id = instance.architecture_id
        if instance.status not in ALLOWED_STATUS_LABELS:
            messages.append(CatalogValidationMessage("error", item_id, f"invalid instance status {instance.status!r}"))
        family = self.families.get(instance.family_id)
        if family is None:
            messages.append(CatalogValidationMessage("error", item_id, f"unknown family_id {instance.family_id!r}"))
        else:
            messages.extend(CatalogValidationMessage("error", item_id, error) for error in family.validate_parameters(instance.parameters))

        component_ids = [component.component_id for component in instance.components]
        if len(component_ids) != len(set(component_ids)):
            messages.append(CatalogValidationMessage("error", item_id, "duplicate component ids"))
        for component in instance.components:
            if component.status not in ALLOWED_STATUS_LABELS:
                messages.append(CatalogValidationMessage("error", component.component_id, f"invalid component status {component.status!r}"))
            if component.component_type_id not in self.component_types:
                messages.append(CatalogValidationMessage("error", component.component_id, f"unknown component_type_id {component.component_type_id!r}"))
            if component.memory_bytes < 0 or component.bandwidth_gbps < 0 or component.power_w < 0 or component.area_mm2 < 0:
                messages.append(CatalogValidationMessage("error", component.component_id, "component units must be non-negative"))
            for peer in component.connected_to:
                if peer not in component_ids:
                    messages.append(CatalogValidationMessage("error", component.component_id, f"route points to missing component {peer!r}"))

        if instance.constraints.max_power_w is not None and instance.total_power_w() > instance.constraints.max_power_w:
            messages.append(CatalogValidationMessage("error", item_id, "total component power exceeds max_power_w"))
        if instance.constraints.max_area_mm2 is not None and instance.total_area_mm2() > instance.constraints.max_area_mm2:
            messages.append(CatalogValidationMessage("error", item_id, "total component area exceeds max_area_mm2"))
        if instance.total_memory_bytes() < instance.constraints.min_memory_bytes:
            messages.append(CatalogValidationMessage("error", item_id, "total memory below min_memory_bytes"))
        for source, target in instance.constraints.required_routes:
            if not instance.has_route(source, target):
                messages.append(CatalogValidationMessage("error", item_id, f"missing required communication route {source}->{target}"))
        supported_ops = set(instance.supported_ops())
        for op in instance.constraints.required_ops:
            if op not in supported_ops:
                messages.append(CatalogValidationMessage("error", item_id, f"required op {op!r} is unsupported by components"))

        for backend, binding_id in instance.simulation_bindings.items():
            binding = self.simulation_bindings.get(binding_id)
            if binding is None:
                messages.append(CatalogValidationMessage("error", item_id, f"{backend} binding {binding_id!r} is missing"))
                continue
            if binding.backend != backend:
                messages.append(CatalogValidationMessage("error", item_id, f"binding {binding_id!r} backend mismatch: expected {backend}, got {binding.backend}"))
            missing_ops = sorted(set(instance.constraints.required_ops) - set(binding.supported_ops))
            if binding.is_trusted_eligible() and missing_ops:
                messages.append(CatalogValidationMessage("error", item_id, f"trusted binding {binding_id!r} lacks required ops {missing_ops}"))

        if instance.status == ArchitectureStatus.TRUSTED_FINAL_ELIGIBLE and not instance.trusted_final_eligible(self.simulation_bindings):
            messages.append(CatalogValidationMessage("error", item_id, "trusted-final-eligible instance lacks implemented SystemC/gem5+SystemC binding"))
        if instance.status != ArchitectureStatus.CANDIDATE_ONLY and not instance.simulation_bindings:
            messages.append(CatalogValidationMessage("warning", item_id, "non-candidate architecture has no simulation binding and will be report-gated"))
        return messages

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "status_labels": sorted(ALLOWED_STATUS_LABELS),
            "families": [family.to_dict() for family in self.families.values()],
            "component_types": [component_type.to_dict() for component_type in self.component_types.values()],
            "simulation_bindings": [binding.to_dict() for binding in self.simulation_bindings.values()],
            "instances": [instance.to_dict() for instance in self.instances.values()],
            "trusted_final_eligible_instances": [instance.architecture_id for instance in self.trusted_final_eligible_instances()],
            "candidate_only_instances": [instance.architecture_id for instance in self.candidate_only_instances()],
        }


def _parameter(name: str, kind: str, default: Any, *, unit: str = "", value_range: Optional[Tuple[float, float]] = None, allowed_values: Optional[Sequence[Any]] = None, description: str = "") -> ArchitectureParameter:
    return ArchitectureParameter(name, kind, default, allowed_values=allowed_values, value_range=value_range, unit=unit, description=description)


def _component(
    component_id: str,
    component_type_id: str,
    role: str,
    *,
    status: str = ArchitectureStatus.PROTOTYPE,
    ops: Sequence[str] = (),
    memory_gb: float = 0.0,
    bandwidth_gbps: float = 0.0,
    power_w: float = 0.0,
    area_mm2: float = 0.0,
    connected_to: Sequence[str] = (),
    attributes: Optional[Mapping[str, Any]] = None,
) -> ComponentInstance:
    return ComponentInstance(
        component_id=component_id,
        component_type_id=component_type_id,
        role=role,
        status=status,
        supported_ops=list(ops),
        memory_bytes=int(memory_gb * 1024**3),
        bandwidth_gbps=bandwidth_gbps,
        power_w=power_w,
        area_mm2=area_mm2,
        connected_to=list(connected_to),
        attributes=dict(attributes or {}),
    )


def _family(family_id: str, name: str, description: str, *, status: str, component_roles: Sequence[str], binding_requirement: str) -> ArchitectureFamily:
    return ArchitectureFamily(
        family_id=family_id,
        name=name,
        description=description,
        parameters=[
            _parameter("replicas", "int", 1, value_range=(1, 16), description="Family-level component replication factor."),
            _parameter("clock_mhz", "float", 250.0, unit="MHz", value_range=(50.0, 2000.0), description="Nominal accelerator clock for generated instances."),
            _parameter("evidence_mode", "enum", "summary", allowed_values=["summary", "debug", "forensic"], description="Default evidence verbosity for simulations."),
        ],
        component_template={"roles": list(component_roles)},
        default_status=status,
        extension_rules=[
            "Add new parameters without changing downstream mapping/report contracts.",
            "Attach SystemC/gem5+SystemC binding metadata before trusted-final eligibility.",
            "Leave unbound families candidate-only; do not remove them from screening catalogs.",
        ],
        binding_requirements={"trusted_final": binding_requirement},
    )


def seed_generic_dse_architecture_catalog() -> ArchitectureCatalog:
    """Create the initial generic DSE architecture catalog required by P2."""
    catalog = ArchitectureCatalog(version="generic-dse-architecture-catalog-v0")

    for component_type in [
        ComponentType("host_cpu", "host", "CPU host/control component", ["control", "fallback", "elementwise", "reduction", "fft"], ["FP64", "FP32"]),
        ComponentType("fpga_fabric", "accelerator", "Reconfigurable FPGA fabric", ["gemm", "fft", "stencil", "reduction", "elementwise", "eigen"], ["FP64", "FP32", "INT8"]),
        ComponentType("gpu_sm", "accelerator", "GPU streaming multiprocessor fabric", ["gemm", "fft", "stencil", "elementwise", "reduction", "eigen"], ["FP64", "FP32", "FP16"]),
        ComponentType("cim_array", "accelerator", "Compute-in-memory array", ["gemm", "elementwise", "vector_add", "reduction"], ["FP64", "FP32", "INT8"]),
        ComponentType("asic_block", "accelerator", "Fixed-function ASIC block", ["gemm", "reduction", "eigen", "elementwise"], ["FP64", "FP32"]),
        ComponentType("hbm_memory", "memory", "High-bandwidth memory stack", [], ["bytes"]),
        ComponentType("noc_interconnect", "interconnect", "NoC/CXL/PCIe communication fabric", ["dma", "collective", "stream"], ["bytes"]),
        ComponentType("legacy_cluster", "legacy", "Legacy four-cluster DFT reference block", ["h_psi", "s_psi", "build_subspace", "diagonalize", "refresh"], ["FP64"]),
    ]:
        catalog.add_component_type(component_type)

    required_artifacts = [
        "manifest.json",
        "verdict.json",
        "architecture.json",
        "simulation_request.json",
        "simulation_result.json",
        "phase_breakdown.csv",
    ]
    catalog.add_binding(SimulationBinding(
        binding_id="standalone_generic_systemc_v1",
        backend="systemc",
        status=ArchitectureStatus.IMPLEMENTED,
        adapter="dse_v2.backends.generic_systemc_bridge.GenericSystemCBackend",
        executable="model/generic_sim_backend/build/generic_sim",
        supported_ops=["gemm", "fft", "stencil", "reduction", "elementwise", "eigen", "vector_add", "control", "fallback", "dma", "stream"],
        required_artifacts=required_artifacts,
        notes=["Timing-level generic SystemC backend; evidence still required per design point."],
    ))
    catalog.add_binding(SimulationBinding(
        binding_id="gem5_systemc_descriptor_path_v1",
        backend="gem5_systemc",
        status=ArchitectureStatus.STUB,
        adapter="gem5_integration GenericAccel descriptor bridge",
        supported_ops=["gemm", "fft", "stencil", "reduction", "elementwise", "eigen", "vector_add"],
        required_artifacts=required_artifacts + ["gem5.log"],
        unavailable_reason="Descriptor ingestion and completion/result writeback are not yet closed for full QE SCF shell evidence.",
        notes=["Keep L4 claims blocked until real gem5-driven descriptor/completion evidence exists."],
    ))

    families = [
        ("cpu-only-baseline", "CPU-only baseline", "Software reference and host fallback baseline.", ArchitectureStatus.CANDIDATE_ONLY, ["host"], "calibrated CPU baseline or SystemC-equivalent evidence"),
        ("host-fpga-minimal", "Host+FPGA minimal", "Smallest host-managed FPGA offload candidate.", ArchitectureStatus.PROTOTYPE, ["host", "fpga", "interconnect"], "standalone SystemC binding for offloaded operators"),
        ("host-fpga-cim", "Host+FPGA+CIM", "Hybrid FPGA fabric plus CIM array for GEMM/vector-heavy kernels.", ArchitectureStatus.PROTOTYPE, ["host", "fpga", "cim", "interconnect"], "CIM op-model binding with SystemC artifacts"),
        ("diag-heavy", "Diag-heavy", "Eigensolver-heavy architecture for cdiaghg/diagonalization phases.", ArchitectureStatus.PROTOTYPE, ["host", "fpga", "asic", "interconnect"], "eigensolver SystemC model coverage"),
        ("streaming-heavy", "Streaming-heavy", "Operator-sweep and h_psi/s_psi streaming-oriented family.", ArchitectureStatus.PROTOTYPE, ["host", "fpga", "hbm", "interconnect"], "streaming/buffer SystemC model coverage"),
        ("memory-rich", "Memory-rich", "Large local memory/HBM/buffer exploration family.", ArchitectureStatus.PROTOTYPE, ["host", "fpga", "hbm", "interconnect"], "memory contention model coverage"),
        ("low-power", "Low-power", "Energy-constrained candidate family.", ArchitectureStatus.UNVERIFIED, ["host", "fpga", "cim"], "power model confidence label plus SystemC evidence"),
        ("balanced", "Balanced", "Pareto-balanced heterogeneous template.", ArchitectureStatus.TRUSTED_FINAL_ELIGIBLE, ["host", "fpga", "gpu", "cim", "interconnect"], "all relevant component bindings"),
        ("debug", "Debug/observability", "Trace-heavy architecture for evidence and co-debug runs.", ArchitectureStatus.PROTOTYPE, ["host", "fpga", "gpu", "cim", "interconnect"], "debug-capable SystemC artifacts"),
        ("future-custom", "Future custom", "Extension hook for new Host/FPGA/Chip/CIM/GPU/ASIC/custom families.", ArchitectureStatus.CANDIDATE_ONLY, ["custom"], "candidate-only until explicit binding exists"),
        ("legacy-four-cluster-reference", "Legacy 4-cluster reference", "Reference-only representation of the previous four-cluster DFT pipeline.", ArchitectureStatus.CANDIDATE_ONLY, ["legacy_cluster"], "reference only; not default or only architecture"),
    ]
    for family_args in families:
        catalog.add_family(_family(*family_args[:3], status=family_args[3], component_roles=family_args[4], binding_requirement=family_args[5]))

    catalog.add_instance(ArchitectureInstance(
        architecture_id="balanced-generic-systemc-v0",
        family_id="balanced",
        parameters={"replicas": 1, "clock_mhz": 250.0, "evidence_mode": "summary"},
        components=[
            _component("host-0", "host_cpu", "control_host", status=ArchitectureStatus.IMPLEMENTED, ops=["control", "fallback", "elementwise", "reduction"], memory_gb=512, bandwidth_gbps=100, power_w=180, area_mm2=0, connected_to=["fpga-0", "gpu-0", "cim-0"]),
            _component("fpga-0", "fpga_fabric", "operator_sweep_and_reduction", ops=["gemm", "fft", "reduction", "elementwise", "eigen", "stream"], memory_gb=32, bandwidth_gbps=460, power_w=225, area_mm2=900, connected_to=["host-0", "gpu-0", "cim-0", "hbm-0"]),
            _component("gpu-0", "gpu_sm", "dense_linear_algebra", ops=["gemm", "fft", "stencil", "elementwise", "reduction", "eigen"], memory_gb=80, bandwidth_gbps=2000, power_w=300, area_mm2=826, connected_to=["host-0", "fpga-0"]),
            _component("cim-0", "cim_array", "near_memory_vector_gemm", ops=["gemm", "elementwise", "vector_add", "reduction"], memory_gb=4, bandwidth_gbps=1024, power_w=60, area_mm2=120, connected_to=["host-0", "fpga-0"]),
            _component("hbm-0", "hbm_memory", "shared_hbm", ops=[], memory_gb=64, bandwidth_gbps=1600, power_w=25, area_mm2=80, connected_to=["fpga-0"]),
        ],
        memory_hierarchy={"levels": ["host_dram", "gpu_hbm", "fpga_hbm", "cim_local"], "total_capacity_bytes": int((512 + 80 + 64 + 4) * 1024**3)},
        interconnect_topology={"type": "pcie_cxl_mixed", "bandwidth_gbps": 128.0, "latency_us": 1.0},
        constraints=ConstraintSet(max_power_w=1000.0, max_area_mm2=2200.0, min_memory_bytes=int(128 * 1024**3), required_routes=[("host-0", "fpga-0"), ("fpga-0", "hbm-0")], required_ops=["gemm", "fft", "reduction", "elementwise", "eigen"]),
        simulation_bindings={"systemc": "standalone_generic_systemc_v1", "gem5_systemc": "gem5_systemc_descriptor_path_v1"},
        status=ArchitectureStatus.TRUSTED_FINAL_ELIGIBLE,
        notes=["Catalog eligibility only; final claims still require run evidence and claim gating."],
    ))

    catalog.add_instance(ArchitectureInstance(
        architecture_id="host-fpga-minimal-v0",
        family_id="host-fpga-minimal",
        parameters={"replicas": 1, "clock_mhz": 250.0, "evidence_mode": "summary"},
        components=[
            _component("host-0", "host_cpu", "control_host", status=ArchitectureStatus.IMPLEMENTED, ops=["control", "fallback"], memory_gb=256, bandwidth_gbps=100, power_w=140, connected_to=["fpga-0"]),
            _component("fpga-0", "fpga_fabric", "minimal_offload", ops=["gemm", "fft", "reduction", "elementwise"], memory_gb=32, bandwidth_gbps=460, power_w=225, area_mm2=900, connected_to=["host-0"]),
        ],
        memory_hierarchy={"levels": ["host_dram", "fpga_hbm"], "total_capacity_bytes": int((256 + 32) * 1024**3)},
        interconnect_topology={"type": "pcie", "bandwidth_gbps": 64.0, "latency_us": 2.0},
        constraints=ConstraintSet(max_power_w=500.0, min_memory_bytes=int(64 * 1024**3), required_routes=[("host-0", "fpga-0")], required_ops=["gemm", "fft", "reduction", "elementwise"]),
        simulation_bindings={"systemc": "standalone_generic_systemc_v1"},
        status=ArchitectureStatus.PROTOTYPE,
    ))

    catalog.add_instance(ArchitectureInstance(
        architecture_id="future-custom-candidate-v0",
        family_id="future-custom",
        parameters={"replicas": 1, "clock_mhz": 250.0, "evidence_mode": "summary"},
        components=[],
        memory_hierarchy={"levels": [], "total_capacity_bytes": 0},
        interconnect_topology={"type": "custom", "bandwidth_gbps": 0.0, "latency_us": 0.0},
        constraints=ConstraintSet(notes=["Deliberately candidate-only until a concrete component set and binding are supplied."]),
        simulation_bindings={},
        status=ArchitectureStatus.CANDIDATE_ONLY,
    ))

    catalog.add_instance(ArchitectureInstance(
        architecture_id="legacy-four-cluster-reference-v0",
        family_id="legacy-four-cluster-reference",
        parameters={"replicas": 4, "clock_mhz": 250.0, "evidence_mode": "summary"},
        components=[
            _component("cluster-a", "legacy_cluster", "operator_sweep_reference", status=ArchitectureStatus.CANDIDATE_ONLY, ops=["h_psi", "s_psi"], connected_to=["cluster-b"]),
            _component("cluster-b", "legacy_cluster", "reduced_build_reference", status=ArchitectureStatus.CANDIDATE_ONLY, ops=["build_subspace"], connected_to=["cluster-a", "cluster-c"]),
            _component("cluster-c", "legacy_cluster", "diagonalization_reference", status=ArchitectureStatus.CANDIDATE_ONLY, ops=["diagonalize"], connected_to=["cluster-b", "cluster-d"]),
            _component("cluster-d", "legacy_cluster", "refresh_residual_reference", status=ArchitectureStatus.CANDIDATE_ONLY, ops=["refresh"], connected_to=["cluster-c"]),
        ],
        memory_hierarchy={"levels": ["legacy_cluster_local"], "total_capacity_bytes": int(16 * 1024**3)},
        interconnect_topology={"type": "legacy_pipeline", "bandwidth_gbps": 64.0, "latency_us": 1.0},
        constraints=ConstraintSet(notes=["Reference only; do not use as default/only architecture family."]),
        simulation_bindings={},
        status=ArchitectureStatus.CANDIDATE_ONLY,
        legacy_reference=True,
        notes=["Represents historical four-cluster split as legacy/reference, not as the catalog default."],
    ))

    catalog.raise_if_invalid()
    return catalog


def catalog_summary(catalog: ArchitectureCatalog) -> Dict[str, Any]:
    """Return a compact summary useful for CLI smoke checks and docs."""
    validation = [message.to_dict() for message in catalog.validate()]
    return {
        "version": catalog.version,
        "family_count": len(catalog.families),
        "instance_count": len(catalog.instances),
        "binding_count": len(catalog.simulation_bindings),
        "status_labels": sorted(ALLOWED_STATUS_LABELS),
        "families": sorted(catalog.families),
        "trusted_final_eligible_instances": [instance.architecture_id for instance in catalog.trusted_final_eligible_instances()],
        "candidate_only_instances": [instance.architecture_id for instance in catalog.candidate_only_instances()],
        "validation": validation,
    }
