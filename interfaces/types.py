#!/usr/bin/env python3
"""Typed Layer 1 DSE interface containers."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _drop_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


@dataclass
class WorkloadSpecialization:
    workload_id: str
    kernels: List[str] = field(default_factory=list)
    precision: str = "FP64"
    dominant_solver: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))

    def __getitem__(self, key: str) -> Any:
        if key == "time_s":
            return self.metrics.get("time_s")
        if key == "energy_j":
            return self.metrics.get("energy_j")
        if key == "feasible":
            return self.status == "passed"
        if key == "area":
            area_mm2 = self.metrics.get("area_mm2", 0.0)
            dsp_util = self.resource_utilization.get("dsp_utilization", 0.0)
            bram_util = self.resource_utilization.get("bram_utilization", 0.0)
            lut_util = self.resource_utilization.get("lut_utilization", 0.0)
            return {
                "area_mm2": area_mm2,
                "dsp_count": dsp_util * 12288.0,
                "dsp_utilization": dsp_util,
                "bram_kb": bram_util * 34000.0,
                "bram_utilization": bram_util,
                "lut_count": lut_util * 600000.0,
                "lut_utilization": lut_util,
            }
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

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
class ResourceLimits:
    max_area_mm2: Optional[float] = None
    max_power_w: Optional[float] = None
    max_latency_ms: Optional[float] = None
    min_throughput_gops: Optional[float] = None
    max_cost_usd: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))

    def __getitem__(self, key: str) -> Any:
        if key == "time_s":
            return self.metrics.get("time_s")
        if key == "energy_j":
            return self.metrics.get("energy_j")
        if key == "feasible":
            return self.status == "passed"
        if key == "area":
            area_mm2 = self.metrics.get("area_mm2", 0.0)
            dsp_util = self.resource_utilization.get("dsp_utilization", 0.0)
            bram_util = self.resource_utilization.get("bram_utilization", 0.0)
            lut_util = self.resource_utilization.get("lut_utilization", 0.0)
            return {
                "area_mm2": area_mm2,
                "dsp_count": dsp_util * 12288.0,
                "dsp_utilization": dsp_util,
                "bram_kb": bram_util * 34000.0,
                "bram_utilization": bram_util,
                "lut_count": lut_util * 600000.0,
                "lut_utilization": lut_util,
            }
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

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
        if key == "time_s":
            return self.metrics.get("time_s")
        if key == "energy_j":
            return self.metrics.get("energy_j")
        if key == "feasible":
            return self.status == "passed"
        if key == "area":
            area_mm2 = self.metrics.get("area_mm2", 0.0)
            dsp_util = self.resource_utilization.get("dsp_utilization", 0.0)
            bram_util = self.resource_utilization.get("bram_utilization", 0.0)
            lut_util = self.resource_utilization.get("lut_utilization", 0.0)
            return {
                "area_mm2": area_mm2,
                "dsp_count": dsp_util * 12288.0,
                "dsp_utilization": dsp_util,
                "bram_kb": bram_util * 34000.0,
                "bram_utilization": bram_util,
                "lut_count": lut_util * 600000.0,
                "lut_utilization": lut_util,
            }
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

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
    """Hardware architecture specification."""
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
    """Software-to-hardware mapping specification.
    
    Each SCF phase maps to a compute target:
    - 'cluster_a', 'cluster_b', 'cluster_c', 'cluster_d': FPGA clusters
    - 'cpu': Host CPU
    - 'fpga': FPGA (unspecified cluster)
    - 'auto': Let the framework decide
    """
    operator_sweep: str = "cluster_a"
    reduced_build: str = "cluster_b"
    diag: str = "cluster_c"
    refresh: str = "cluster_d"
    # Optional: per-kernel overrides for finer control
    kernel_mapping: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))

    def get_target(self, phase: str) -> str:
        """Get compute target for a given SCF phase."""
        mapping = {
            'operator_sweep': self.operator_sweep,
            'reduced_build': self.reduced_build,
            'diag': self.diag,
            'refresh': self.refresh,
        }
        return self.kernel_mapping.get(phase, mapping.get(phase, 'cpu'))


@dataclass
class DataflowSpec:
    """Dataflow optimization switches."""
    double_buffer: bool = False
    overlap_dma_compute: bool = False
    keep_resident: bool = False
    # Additional dataflow parameters
    prefetch_distance: int = 1
    tile_size_kb: float = 64.0

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))


@dataclass
class WorkloadSpec:
    """Workload specification for SCF execution."""
    npw: int = 2945
    nkb: int = 144
    m: int = 16
    iterations: int = 1
    kernel_mix: Dict[str, float] = field(default_factory=lambda: {
        'h_psi': 0.68,
        'cdiaghg': 0.23,
        'reduction': 0.04,
        'refresh': 0.05,
    })

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
    target_layers: List[str] = field(default_factory=lambda: ['L1', 'L2', 'L3'])
    schema_version: str = "design_point_v2"
    architecture_spec_ref: Optional[str] = None
    constraints: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    # Legacy compatibility
    family: Optional[str] = None
    topology_type: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    workload_specialization: Optional[WorkloadSpecialization] = None

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))

    def __getitem__(self, key: str) -> Any:
        if key == "time_s":
            return self.metrics.get("time_s")
        if key == "energy_j":
            return self.metrics.get("energy_j")
        if key == "feasible":
            return self.status == "passed"
        if key == "area":
            area_mm2 = self.metrics.get("area_mm2", 0.0)
            dsp_util = self.resource_utilization.get("dsp_utilization", 0.0)
            bram_util = self.resource_utilization.get("bram_utilization", 0.0)
            lut_util = self.resource_utilization.get("lut_utilization", 0.0)
            return {
                "area_mm2": area_mm2,
                "dsp_count": dsp_util * 12288.0,
                "dsp_utilization": dsp_util,
                "bram_kb": bram_util * 34000.0,
                "bram_utilization": bram_util,
                "lut_count": lut_util * 600000.0,
                "lut_utilization": lut_util,
            }
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

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
        if key == "time_s":
            return self.metrics.get("time_s")
        if key == "energy_j":
            return self.metrics.get("energy_j")
        if key == "feasible":
            return self.status == "passed"
        if key == "area":
            area_mm2 = self.metrics.get("area_mm2", 0.0)
            dsp_util = self.resource_utilization.get("dsp_utilization", 0.0)
            bram_util = self.resource_utilization.get("bram_utilization", 0.0)
            lut_util = self.resource_utilization.get("lut_utilization", 0.0)
            return {
                "area_mm2": area_mm2,
                "dsp_count": dsp_util * 12288.0,
                "dsp_utilization": dsp_util,
                "bram_kb": bram_util * 34000.0,
                "bram_utilization": bram_util,
                "lut_count": lut_util * 600000.0,
                "lut_utilization": lut_util,
            }
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

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
