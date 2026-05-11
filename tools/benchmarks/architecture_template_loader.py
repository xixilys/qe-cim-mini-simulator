#!/usr/bin/env python3
"""
Architecture Template Loader

Loads and validates architecture templates for DSE exploration.
Supports the architecture_template_schema_v1.json format.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False
    print("Warning: jsonschema not installed. Using basic validation only.")


class ComputeUnitType(Enum):
    """Supported compute unit types"""
    CIM_ARRAY = "cim_array"
    TRADITIONAL_FPGA_DSP = "traditional_fpga_dsp"
    PIM_BRAM_BASED = "pim_bram_based"
    PIM_3D_STACKED = "pim_3d_stacked"
    HYBRID_CIM_DSP = "hybrid_cim_dsp"
    CUSTOM = "custom"


class TimingModel(Enum):
    """Timing model types"""
    PROXY_FORMULA = "proxy_formula"
    CYCLE_ACCURATE = "cycle_accurate"
    HYBRID = "hybrid"


@dataclass
class ResourceBudget:
    """FPGA resource budget for a cluster"""
    dsp_count: int = 0
    bram_18k_count: int = 0
    lut_count: int = 0
    uram_count: int = 0
    
    def total_resources(self) -> Dict[str, int]:
        return {
            "dsp": self.dsp_count,
            "bram_18k": self.bram_18k_count,
            "lut": self.lut_count,
            "uram": self.uram_count
        }


@dataclass
class ClusterConfig:
    """Configuration for a single cluster"""
    cluster_id: str
    role: str
    compute_unit: ComputeUnitType
    enabled: bool
    timing_model: TimingModel = TimingModel.PROXY_FORMULA
    fusion_group: Optional[str] = None
    resource_budget: Optional[ResourceBudget] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ClusterConfig':
        """Create ClusterConfig from dictionary"""
        resource_budget = None
        if "resource_budget" in data:
            rb = data["resource_budget"]
            resource_budget = ResourceBudget(
                dsp_count=rb.get("dsp_count", 0),
                bram_18k_count=rb.get("bram_18k_count", 0),
                lut_count=rb.get("lut_count", 0),
                uram_count=rb.get("uram_count", 0)
            )
        
        return cls(
            cluster_id=data["cluster_id"],
            role=data["role"],
            compute_unit=ComputeUnitType(data["compute_unit"]),
            enabled=data["enabled"],
            timing_model=TimingModel(data.get("timing_model", "proxy_formula")),
            fusion_group=data.get("fusion_group"),
            resource_budget=resource_budget
        )


@dataclass
class ArchitecturePolicies:
    """Architecture-level policies"""
    diag_policy: str
    offload_scope: str
    resident_policy: str
    partition_strategy: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ArchitecturePolicies':
        return cls(
            diag_policy=data["diag_policy"],
            offload_scope=data["offload_scope"],
            resident_policy=data["resident_policy"],
            partition_strategy=data["partition_strategy"]
        )


@dataclass
class ArchitectureTemplate:
    """Complete architecture template"""
    template_id: str
    template_version: str
    family: str
    label: str
    clusters: List[ClusterConfig]
    policies: ArchitecturePolicies
    compute_config: Dict[str, Any] = field(default_factory=dict)
    memory_hierarchy: Dict[str, Any] = field(default_factory=dict)
    component_overrides: Dict[str, Any] = field(default_factory=dict)
    dse_metadata: Dict[str, Any] = field(default_factory=dict)
    notes: Dict[str, Any] = field(default_factory=dict)
    
    def get_enabled_clusters(self) -> List[ClusterConfig]:
        """Get list of enabled clusters"""
        return [c for c in self.clusters if c.enabled]
    
    def get_cluster_by_id(self, cluster_id: str) -> Optional[ClusterConfig]:
        """Get cluster by ID"""
        for cluster in self.clusters:
            if cluster.cluster_id == cluster_id:
                return cluster
        return None
    
    def total_resource_budget(self) -> ResourceBudget:
        """Calculate total resource budget across all enabled clusters"""
        total = ResourceBudget()
        for cluster in self.get_enabled_clusters():
            if cluster.resource_budget:
                total.dsp_count += cluster.resource_budget.dsp_count
                total.bram_18k_count += cluster.resource_budget.bram_18k_count
                total.lut_count += cluster.resource_budget.lut_count
                total.uram_count += cluster.resource_budget.uram_count
        return total
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ArchitectureTemplate':
        """Create ArchitectureTemplate from dictionary"""
        clusters = [ClusterConfig.from_dict(c) for c in data["clusters"]]
        policies = ArchitecturePolicies.from_dict(data["policies"])
        
        return cls(
            template_id=data["template_id"],
            template_version=data["template_version"],
            family=data["family"],
            label=data.get("label", ""),
            clusters=clusters,
            policies=policies,
            compute_config=data.get("compute_config", {}),
            memory_hierarchy=data.get("memory_hierarchy", {}),
            component_overrides=data.get("component_overrides", {}),
            dse_metadata=data.get("dse_metadata", {}),
            notes=data.get("notes", {})
        )


@dataclass
class ValidationResult:
    """Result of template validation"""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def add_error(self, message: str):
        self.valid = False
        self.errors.append(message)
    
    def add_warning(self, message: str):
        self.warnings.append(message)


class ArchitectureTemplateLoader:
    """Loads and validates architecture templates"""
    
    # FPGA resource limits (Xilinx VU9P as reference)
    MAX_RESOURCES = {
        "dsp": 6840,
        "bram_18k": 4320,
        "lut": 1182240,
        "uram": 960
    }
    
    def __init__(self, schema_path: Optional[Path] = None):
        """Initialize loader with optional schema path"""
        if schema_path is None:
            # Default schema location
            schema_path = Path(__file__).parent.parent / "architecture" / "architecture_template_schema_v1.json"
        
        self.schema_path = schema_path
        self.schema = self._load_schema()
    
    def _load_schema(self) -> Dict[str, Any]:
        """Load JSON schema"""
        if not self.schema_path.exists():
            raise FileNotFoundError(f"Schema not found: {self.schema_path}")
        
        with open(self.schema_path, 'r') as f:
            return json.load(f)
    
    def load_template(self, template_path: Path) -> ArchitectureTemplate:
        """Load and validate a single template"""
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        with open(template_path, 'r') as f:
            data = json.load(f)
        
        # Validate against schema
        validation = self.validate_template(data)
        if not validation.valid:
            error_msg = "\n".join(validation.errors)
            raise ValueError(f"Template validation failed:\n{error_msg}")
        
        # Print warnings if any
        if validation.warnings:
            print(f"Warnings for {template_path.name}:")
            for warning in validation.warnings:
                print(f"  - {warning}")
        
        return ArchitectureTemplate.from_dict(data)
    
    def load_all_templates(self, template_dir: Path) -> List[ArchitectureTemplate]:
        """Load all templates from a directory"""
        if not template_dir.exists():
            raise FileNotFoundError(f"Template directory not found: {template_dir}")
        
        templates = []
        for template_file in sorted(template_dir.glob("*.json")):
            try:
                template = self.load_template(template_file)
                templates.append(template)
                print(f"✓ Loaded: {template.template_id} ({template.label})")
            except Exception as e:
                print(f"✗ Failed to load {template_file.name}: {e}")
        
        return templates
    
    def validate_template(self, template_data: Dict[str, Any]) -> ValidationResult:
        """Validate template against schema and additional rules"""
        result = ValidationResult(valid=True)
        
        # 1. JSON Schema validation
        if HAS_JSONSCHEMA:
            try:
                jsonschema.validate(instance=template_data, schema=self.schema)
            except jsonschema.ValidationError as e:
                result.add_error(f"Schema validation failed: {e.message}")
                return result
        else:
            # Basic validation without jsonschema
            required_fields = ["template_id", "template_version", "family", "clusters", "policies"]
            for field in required_fields:
                if field not in template_data:
                    result.add_error(f"Missing required field: {field}")
            
            if result.errors:
                return result
        
        # 2. Cluster ID uniqueness
        cluster_ids = [c["cluster_id"] for c in template_data["clusters"]]
        if len(cluster_ids) != len(set(cluster_ids)):
            result.add_error("Cluster IDs must be unique")
        
        # 3. At least one enabled cluster
        enabled_clusters = [c for c in template_data["clusters"] if c["enabled"]]
        if not enabled_clusters:
            result.add_error("At least one cluster must be enabled")
        
        # 4. Fusion group references
        fusion_groups = set()
        for cluster in template_data["clusters"]:
            if "fusion_group" in cluster and cluster["fusion_group"]:
                fusion_groups.add(cluster["fusion_group"])
        
        for cluster in template_data["clusters"]:
            if "fusion_group" in cluster and cluster["fusion_group"]:
                # Check that fusion group has at least 2 members
                group_members = [c for c in template_data["clusters"] 
                               if c.get("fusion_group") == cluster["fusion_group"]]
                if len(group_members) < 2:
                    result.add_warning(f"Fusion group '{cluster['fusion_group']}' has only 1 member")
        
        # 5. Resource budget validation
        total_dsp = 0
        total_bram = 0
        total_lut = 0
        total_uram = 0
        
        for cluster in enabled_clusters:
            if "resource_budget" in cluster:
                rb = cluster["resource_budget"]
                total_dsp += rb.get("dsp_count", 0)
                total_bram += rb.get("bram_18k_count", 0)
                total_lut += rb.get("lut_count", 0)
                total_uram += rb.get("uram_count", 0)
        
        # Check against FPGA limits
        if total_dsp > self.MAX_RESOURCES["dsp"]:
            result.add_error(f"Total DSP count ({total_dsp}) exceeds FPGA limit ({self.MAX_RESOURCES['dsp']})")
        
        if total_bram > self.MAX_RESOURCES["bram_18k"]:
            result.add_error(f"Total BRAM count ({total_bram}) exceeds FPGA limit ({self.MAX_RESOURCES['bram_18k']})")
        
        if total_lut > self.MAX_RESOURCES["lut"]:
            result.add_error(f"Total LUT count ({total_lut}) exceeds FPGA limit ({self.MAX_RESOURCES['lut']})")
        
        if total_uram > self.MAX_RESOURCES["uram"]:
            result.add_error(f"Total URAM count ({total_uram}) exceeds FPGA limit ({self.MAX_RESOURCES['uram']})")
        
        # Warnings for high resource usage
        if total_dsp > self.MAX_RESOURCES["dsp"] * 0.9:
            result.add_warning(f"DSP usage is >90% of FPGA capacity")
        
        if total_lut > self.MAX_RESOURCES["lut"] * 0.9:
            result.add_warning(f"LUT usage is >90% of FPGA capacity")
        
        return result


def main():
    """Test the template loader"""
    import sys
    
    # Get template directory from command line or use default
    if len(sys.argv) > 1:
        template_dir = Path(sys.argv[1])
    else:
        template_dir = Path(__file__).parent.parent / "architecture" / "architecture_templates"
    
    print(f"Loading templates from: {template_dir}")
    print("=" * 60)
    
    loader = ArchitectureTemplateLoader()
    templates = loader.load_all_templates(template_dir)
    
    print("\n" + "=" * 60)
    print(f"Successfully loaded {len(templates)} template(s)\n")
    
    # Print summary
    for template in templates:
        print(f"Template: {template.template_id}")
        print(f"  Label: {template.label}")
        print(f"  Family: {template.family}")
        print(f"  Enabled Clusters: {len(template.get_enabled_clusters())}/{len(template.clusters)}")
        
        total_resources = template.total_resource_budget()
        print(f"  Total Resources:")
        print(f"    DSP: {total_resources.dsp_count}")
        print(f"    BRAM: {total_resources.bram_18k_count}")
        print(f"    LUT: {total_resources.lut_count}")
        print(f"    URAM: {total_resources.uram_count}")
        print()


if __name__ == "__main__":
    main()
