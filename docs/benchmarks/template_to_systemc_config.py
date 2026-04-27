#!/usr/bin/env python3
"""
Template to SystemC Configuration Projector

Projects Phase 1 architecture templates (JSON) to SystemC ArchitectureConfig format.
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, List


class TemplateProjector:
    """Projects architecture templates to SystemC configuration"""
    
    def __init__(self):
        self.compute_unit_type_map = {
            "cim_array": "cim_array",
            "traditional_fpga_dsp": "traditional_fpga",
            "pim_array": "pim",
            "pim_bram_based": "pim",
            "pim_3d_stacked": "pim",
            "hybrid": "hybrid",
            "hybrid_cim_dsp": "hybrid",
            "custom": "cim_array"
        }
        
        self.cluster_type_map = {
            "operator_sweep": "operator_sweep",
            "reduced_build": "reduced_build",
            "hardware_diag": "hardware_diag",
            "refresh_residual": "refresh_residual",
            "fused_build_diag": "fused_build_diag",
            "fused_operator_build": "fused_build_diag",
            "fused_diag_refresh": "custom",
            "custom": "custom"
        }
    
    def project_template(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Project a template to SystemC configuration format"""
        
        systemc_config = {
            "schema_version": "systemc_architecture_config_v1",
            "template_id": template.get("template_id", "unknown"),
            "template_label": template.get("label", "Unknown Template"),
            "architecture_family": template.get("family", template.get("base_family", "F2")),
            "clusters": [],
            "global_policies": self._project_policies(template.get("policies", {})),
            "resource_limits": {
                "max_dsp": 6840,
                "max_bram_18k": 4320,
                "max_uram": 960,
                "max_lut": 1182240,
                "max_ff": 2364480
            },
            "interconnect": self._project_interconnect(template.get("interconnect", {})),
            "timing": self._project_timing(template.get("timing", {})),
            "template_metadata": {
                "template_version": template.get("template_version"),
                "dse_metadata": template.get("dse_metadata", {}),
                "notes": template.get("notes", {}),
                "component_overrides": template.get("component_overrides", {})
            }
        }
        
        for cluster in template.get("clusters", []):
            if cluster.get("enabled", True):
                systemc_config["clusters"].append(
                    self._project_cluster(
                        cluster,
                        template.get("compute_config", {}),
                        template.get("memory_hierarchy", {}),
                        template.get("policies", {})
                    )
                )
        
        return systemc_config
    
    def _project_cluster(
        self,
        cluster: Dict[str, Any],
        global_compute_config: Dict[str, Any],
        global_memory_hierarchy: Dict[str, Any],
        global_policies: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Project a single cluster configuration"""
        
        cluster_role = cluster.get("role", "operator_sweep")
        cluster_type = self.cluster_type_map.get(cluster_role, "operator_sweep")
        
        compute_unit_str = cluster.get("compute_unit", "cim_array")
        compute_unit_type = self.compute_unit_type_map.get(compute_unit_str, "cim_array")
        compute_config = dict(global_compute_config)
        compute_config.update(cluster.get("compute_config", {}))
        projection_notes = []
        if compute_unit_str in {"pim_bram_based", "pim_3d_stacked"}:
            projection_notes.append(f"{compute_unit_str} projected to generic pim SystemC category")
        if compute_unit_str == "hybrid_cim_dsp":
            projection_notes.append("hybrid_cim_dsp projected to generic hybrid SystemC category")
        if compute_unit_str == "custom":
            projection_notes.append("custom compute unit projected to cim_array fallback category")
        if cluster_role in {"fused_operator_build", "fused_diag_refresh"}:
            projection_notes.append(f"{cluster_role} is projection-only; no new C++ runtime behavior is implied")
        
        systemc_cluster = {
            "cluster_id": cluster.get("cluster_id", "cluster_unknown"),
            "type": cluster_type,
            "source_role": cluster_role,
            "compute_unit": self._project_compute_unit(
                compute_unit_type,
                compute_config,
                compute_unit_str
            ),
            "on_chip_buffer_kb": cluster.get("resource_budget", {}).get("buffer_kb", 512),
            "dma_bandwidth_gbps": 100,
            "enable_pipelining": True,
            "pipeline_depth": 4,
            "resident_policy": cluster.get("resident_policy", global_policies.get("resident_policy", "fit_first")),
            "resident_budget_scale": global_memory_hierarchy.get("resident_budget_scale", 1.0),
            "enable_backpressure": True,
            "max_concurrent_ops": 8,
            "projection_notes": projection_notes
        }
        if cluster.get("fusion_group"):
            systemc_cluster["fusion_group"] = cluster["fusion_group"]
        
        return systemc_cluster
    
    def _project_compute_unit(
        self,
        unit_type: str,
        compute_config: Dict[str, Any],
        source_compute_unit: str
    ) -> Dict[str, Any]:
        """Project compute unit configuration"""
        
        compute_unit = {
            "type": unit_type,
            "source_compute_unit": source_compute_unit,
            "parallelism": 4,
            "enable_karatsuba": True
        }
        
        if unit_type == "cim_array":
            compute_unit.update({
                "cim_moduli_count": 16,
                "cim_array_rows": 256,
                "cim_array_cols": 256,
                "cim_frequency_mhz": compute_config.get("clock_mhz", 150.0)
            })
        elif unit_type == "traditional_fpga":
            dsp_array_dims = compute_config.get("dsp_array_dims", {})
            compute_unit.update({
                "fpga_tile_size": compute_config.get("gemm_tile_size", 32),
                "fpga_dsp_count": dsp_array_dims.get("rows", 16) * dsp_array_dims.get("cols", 16),
                "fpga_frequency_mhz": compute_config.get("clock_mhz", 300.0)
            })
        elif unit_type == "pim":
            pim_style = "3d_stacked" if source_compute_unit == "pim_3d_stacked" else "bram_based"
            compute_unit.update({
                "pim_style": pim_style,
                "pim_bank_count": 8,
                "pim_subarray_count": 16
            })
        elif unit_type == "hybrid":
            dsp_array_dims = compute_config.get("dsp_array_dims", {})
            compute_unit.update({
                "hybrid_mode": source_compute_unit,
                "cim_moduli_count": compute_config.get("cim_config", {}).get("moduli_count", 16),
                "fpga_tile_size": compute_config.get("gemm_tile_size", 32),
                "fpga_dsp_count": dsp_array_dims.get("rows", 8) * dsp_array_dims.get("cols", 8),
                "hybrid_frequency_mhz": compute_config.get("clock_mhz", 250.0)
            })
        
        return compute_unit
    
    def _project_policies(self, policies: Dict[str, Any]) -> Dict[str, Any]:
        """Project global policies"""
        
        return {
            "offload_scope": policies.get("offload_scope", "balanced"),
            "diag_policy": policies.get("diag_policy", "device_first_fallback"),
            "enable_device_fft": True,
            "force_host_diag": False,
            "allow_cpu_diag_fallback": True
        }
    
    def _project_interconnect(self, interconnect: Dict[str, Any]) -> Dict[str, Any]:
        """Project interconnect configuration"""
        
        return {
            "axi_data_width": 512,
            "axi_burst_length": 256,
            "pcie_bandwidth_gbps": 32.0,
            "ddr_bandwidth_gbps": 76.8
        }
    
    def _project_timing(self, timing: Dict[str, Any]) -> Dict[str, Any]:
        """Project timing configuration"""
        
        return {
            "system_clock_mhz": 250.0,
            "use_proxy_formulas": True,
            "proxy_uncertainty": 0.20
        }


def main():
    """Main entry point"""
    
    if len(sys.argv) < 2:
        print("Usage: template_to_systemc_config.py <template.json> [output.json]")
        print("\nExample:")
        print("  python3 template_to_systemc_config.py \\")
        print("    docs/architecture/architecture_templates/4cluster_cim_baseline_v1.json \\")
        print("    tmp/systemc_config.json")
        sys.exit(1)
    
    template_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("systemc_config.json")
    
    if not template_path.exists():
        print(f"Error: Template file not found: {template_path}")
        sys.exit(1)
    
    print(f"Loading template: {template_path}")
    with open(template_path) as f:
        template = json.load(f)
    
    projector = TemplateProjector()
    systemc_config = projector.project_template(template)
    
    print(f"Projecting template: {systemc_config['template_id']}")
    print(f"  Label: {systemc_config['template_label']}")
    print(f"  Family: {systemc_config['architecture_family']}")
    print(f"  Clusters: {len(systemc_config['clusters'])}")
    
    for cluster in systemc_config['clusters']:
        print(f"    - {cluster['cluster_id']}: {cluster['type']} ({cluster['compute_unit']['type']})")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(systemc_config, f, indent=2)
    
    print(f"\nSystemC configuration written to: {output_path}")
    print(f"Size: {output_path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
