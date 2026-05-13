#!/usr/bin/env python3
"""Typed containers shared by active DSE v2 evaluators.

These classes replace the old repository-root ``interfaces`` package so the
active DSE stack is self-contained.  Field names that still appear in older L1
models are kept as compatibility dimensions; policy, coverage, and workload
semantics are supplied by workload profiles/importers rather than by these
generic containers.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _drop_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


def _result_item(payload: Any, key: str) -> Any:
    if key == "time_s":
        return payload.metrics.get("time_s")
    if key == "energy_j":
        return payload.metrics.get("energy_j")
    if key == "feasible":
        return payload.status == "passed"
    if key == "area":
        area_mm2 = payload.metrics.get("area_mm2", 0.0)
        dsp_util = payload.resource_utilization.get("dsp_utilization", 0.0)
        bram_util = payload.resource_utilization.get("bram_utilization", 0.0)
        lut_util = payload.resource_utilization.get("lut_utilization", 0.0)
        return {
            "area_mm2": area_mm2,
            "dsp_count": dsp_util * 12288.0,
            "dsp_utilization": dsp_util,
            "bram_kb": bram_util * 34000.0,
            "bram_utilization": bram_util,
            "lut_count": lut_util * 600000.0,
            "lut_utilization": lut_util,
        }
    if hasattr(payload, key):
        return getattr(payload, key)
    raise KeyError(key)


@dataclass
class WorkloadSpecialization:
    workload_id: str
    kernels: List[str] = field(default_factory=list)
    precision: str = "FP64"
    dominant_solver: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))


@dataclass
class ResourceLimits:
    max_area_mm2: Optional[float] = None
    max_power_w: Optional[float] = None
    max_latency_ms: Optional[float] = None
    min_throughput_gops: Optional[float] = None
    max_cost_usd: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))


@dataclass
class LayerResult:
    layer_id: str
    fidelity_level: str
    status: str
    metrics: Dict[str, float]
    uncertainty: Dict[str, Any] = field(default_factory=dict)
    resource_utilization: Dict[str, float] = field(default_factory=dict)
    promotion_score: Optional[float] = None
    model_used: Optional[str] = None
    execution_time_seconds: Optional[float] = None
    is_projection: bool = False
    projection_uncertainty: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))

    def __getitem__(self, key: str) -> Any:
        return _result_item(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        try:
            self[key]
        except KeyError:
            return False
        return True


@dataclass
class ArchitectureSpec:
    """Hardware architecture specification for active DSE candidates."""

    family: str = "F1"
    topology_type: str = "pipeline"
    clock_mhz: float = 250.0
    pcie_bw_gbps: float = 64.0
    dram_bw_gbps: float = 128.0
    local_mem_kb: float = 512.0
    parallel_units: int = 4
    gemm_tiles: int = 4
    eigen_tiles: int = 1
    max_power_w: float = 75.0
    dsp_budget: float = 1.0
    bram_budget: float = 1.0
    lut_budget: float = 1.0
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))


@dataclass
class MappingSpec:
    """Software-to-hardware mapping hints for generic DSE candidates."""

    compute: str = "accel_compute"
    transform: str = "accel_transform"
    solve: str = "accel_solve"
    update: str = "accel_update"
    kernel_mapping: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))

    def get_target(self, phase: str) -> str:
        mapping = {
            "compute": self.compute,
            "transform": self.transform,
            "solve": self.solve,
            "update": self.update,
        }
        return self.kernel_mapping.get(phase, mapping.get(phase, "cpu"))


@dataclass
class DataflowSpec:
    """Dataflow optimization switches."""

    double_buffer: bool = False
    overlap_dma_compute: bool = False
    keep_resident: bool = False
    prefetch_distance: int = 1
    tile_size_kb: float = 64.0

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))


@dataclass
class WorkloadSpec:
    """Generic workload dimensions for analytical/TLM estimates.

    Legacy profile/importer metadata may still include domain-specific keys, but
    active models should prefer these generic dimensions.
    """

    problem_size: int = 4096
    feature_size: int = 256
    batch_size: int = 16
    iterations: int = 1
    kernel_mix: Dict[str, float] = field(default_factory=lambda: {
        "compute": 0.55,
        "transform": 0.20,
        "reduce": 0.15,
        "update": 0.10,
    })
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))


@dataclass
class DesignPoint:
    design_point_id: str
    architecture: ArchitectureSpec
    mapping: MappingSpec
    dataflow: DataflowSpec
    workload: WorkloadSpec
    resource_limits: ResourceLimits
    target_layers: List[str] = field(default_factory=lambda: ["L1", "L2", "L3"])
    schema_version: str = "design_point_v2"
    architecture_spec_ref: Optional[str] = None
    constraints: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    family: Optional[str] = None
    topology_type: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    workload_specialization: Optional[WorkloadSpecialization] = None

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and hasattr(self, key)


@dataclass
class EvaluationResult:
    result_id: str
    design_point_id: str
    fidelity_level_achieved: str
    layer_results: List[LayerResult]
    promotion_recommendation: str
    promotion_score: float
    schema_version: str = "evaluation_result_v1"
    evaluation_config_ref: Optional[str] = None
    metrics: Dict[str, float] = field(default_factory=dict)
    status: str = "passed"
    uncertainty: Dict[str, Any] = field(default_factory=dict)
    resource_utilization: Dict[str, float] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))

    def __getitem__(self, key: str) -> Any:
        return _result_item(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        try:
            self[key]
        except KeyError:
            return False
        return True
