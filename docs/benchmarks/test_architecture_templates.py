#!/usr/bin/env python3
"""
End-to-End Test for Architecture Template System

Tests the complete workflow:
1. Load templates
2. Generate candidates
3. Validate configurations
4. Export for DSE
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent))

from architecture_template_loader import ArchitectureTemplateLoader, ArchitectureTemplate
from architecture_candidate_generator import ArchitectureCandidateGenerator, SweepStrategy
from template_to_systemc_config import TemplateProjector


REQUIRED_TEMPLATE_IDS = {
    "f1_host_heavy_cpu_baseline_v1",
    "f3_tensor_systolic_fpga_offload_v1",
    "f2_systolic_fpga_dense_path_v1",
    "f3_hbm_streaming_operator_pipeline_v1",
    "custom_multichiplet_noc_partition_v1",
    "custom_near_memory_pim_resident_v1",
    "f5_cgra_dataflow_operator_v1",
    "f4_cim_dsp_hbm_hybrid_v1",
}

PROJECTION_ONLY_TEMPLATE_FAMILIES = {"F4", "F5", "custom"}


class TemplateSystemValidator:
    """Validates the complete template system"""
    
    def __init__(self):
        self.loader = ArchitectureTemplateLoader()
        self.generator = ArchitectureCandidateGenerator(seed=42)
        self.test_results = []
    
    def run_all_tests(self) -> bool:
        """Run all validation tests"""
        print("=" * 70)
        print("Architecture Template System - End-to-End Validation")
        print("=" * 70)
        
        all_passed = True
        
        all_passed &= self.test_template_loading()
        all_passed &= self.test_candidate_generation()
        all_passed &= self.test_parameter_sweep()
        all_passed &= self.test_resource_validation()
        all_passed &= self.test_config_export()
        all_passed &= self.test_projector_schema_compute_units()
        
        print("\n" + "=" * 70)
        if all_passed:
            print("✓ ALL TESTS PASSED")
        else:
            print("✗ SOME TESTS FAILED")
        print("=" * 70)
        
        return all_passed
    
    def test_template_loading(self) -> bool:
        """Test 1: Template Loading"""
        print("\n[Test 1] Template Loading")
        print("-" * 70)
        
        try:
            template_dir = Path(__file__).parent.parent / "architecture" / "architecture_templates"
            templates = self.loader.load_all_templates(template_dir)
            
            if len(templates) < len(REQUIRED_TEMPLATE_IDS):
                print(f"✗ Expected at least {len(REQUIRED_TEMPLATE_IDS)} templates, got {len(templates)}")
                return False
            loaded_ids = {template.template_id for template in templates}
            missing_ids = sorted(REQUIRED_TEMPLATE_IDS - loaded_ids)
            if missing_ids:
                print(f"✗ Missing required template IDs: {missing_ids}")
                return False
             
            print(f"✓ Loaded {len(templates)} templates")
            
            for template in templates:
                enabled_clusters = template.get_enabled_clusters()
                print(f"  - {template.template_id}: {len(enabled_clusters)} enabled clusters")
            
            return True
            
        except Exception as e:
            print(f"✗ Template loading failed: {e}")
            return False
    
    def test_candidate_generation(self) -> bool:
        """Test 2: Candidate Generation"""
        print("\n[Test 2] Candidate Generation")
        print("-" * 70)
        
        try:
            template_path = Path(__file__).parent.parent / "architecture" / "architecture_templates" / "4cluster_traditional_fpga_v1.json"
            template_obj = self.loader.load_template(template_path)
            template_dict = json.loads(template_path.read_text())
            
            param_ranges = {
                "compute_config.clock_mhz": [250, 300],
                "compute_config.gemm_tile_size": [16, 32]
            }
            
            candidates = self.generator.generate_candidates(
                template_dict,
                param_ranges,
                strategy=SweepStrategy.GRID_SEARCH
            )
            
            expected_count = 2 * 2
            if len(candidates) != expected_count:
                print(f"✗ Expected {expected_count} candidates, got {len(candidates)}")
                return False
            
            print(f"✓ Generated {len(candidates)} candidates (grid search)")
            
            for i, candidate in enumerate(candidates[:3]):
                print(f"  - Candidate {i}: {candidate.parameter_values}")
            
            return True
            
        except Exception as e:
            print(f"✗ Candidate generation failed: {e}")
            return False
    
    def test_parameter_sweep(self) -> bool:
        """Test 3: Parameter Sweep Strategies"""
        print("\n[Test 3] Parameter Sweep Strategies")
        print("-" * 70)
        
        try:
            template_path = Path(__file__).parent.parent / "architecture" / "architecture_templates" / "4cluster_cim_baseline_v1.json"
            template_dict = json.loads(template_path.read_text())
            
            param_ranges = {
                "compute_config.clock_mhz": [200, 250, 300],
                "memory_hierarchy.l1_buffer_kb": [128, 256, 512]
            }
            
            strategies = [
                (SweepStrategy.GRID_SEARCH, None, 9),
                (SweepStrategy.RANDOM_SAMPLING, 10, 10),
                (SweepStrategy.LATIN_HYPERCUBE, 10, 10)
            ]
            
            for strategy, n_samples, expected_count in strategies:
                candidates = self.generator.generate_candidates(
                    template_dict,
                    param_ranges,
                    strategy=strategy,
                    n_samples=n_samples
                )
                
                if len(candidates) != expected_count:
                    print(f"✗ {strategy.value}: Expected {expected_count}, got {len(candidates)}")
                    return False
                
                print(f"✓ {strategy.value}: {len(candidates)} candidates")
            
            return True
            
        except Exception as e:
            print(f"✗ Parameter sweep test failed: {e}")
            return False
    
    def test_resource_validation(self) -> bool:
        """Test 4: Resource Budget Validation"""
        print("\n[Test 4] Resource Budget Validation")
        print("-" * 70)
        
        try:
            template_dir = Path(__file__).parent.parent / "architecture" / "architecture_templates"
            templates = self.loader.load_all_templates(template_dir)
            
            for template in templates:
                total_resources = template.total_resource_budget()
                
                if total_resources.dsp_count > self.loader.MAX_RESOURCES["dsp"]:
                    print(f"✗ {template.template_id}: DSP count exceeds limit")
                    return False
                
                if total_resources.lut_count > self.loader.MAX_RESOURCES["lut"]:
                    print(f"✗ {template.template_id}: LUT count exceeds limit")
                    return False
                
                utilization = (total_resources.dsp_count / self.loader.MAX_RESOURCES["dsp"]) * 100
                print(f"✓ {template.template_id}: DSP utilization {utilization:.1f}%")
            
            return True
            
        except Exception as e:
            print(f"✗ Resource validation failed: {e}")
            return False
    
    def test_config_export(self) -> bool:
        """Test 5: Configuration Export"""
        print("\n[Test 5] Configuration Export")
        print("-" * 70)
        
        try:
            template_path = Path(__file__).parent.parent / "architecture" / "architecture_templates" / "4cluster_traditional_fpga_v1.json"
            template_dict = json.loads(template_path.read_text())
            
            param_ranges = {"compute_config.clock_mhz": [300]}
            candidates = self.generator.generate_candidates(
                template_dict,
                param_ranges,
                strategy=SweepStrategy.GRID_SEARCH
            )
            
            candidate = candidates[0]
            
            config_json = candidate.to_json()
            parsed_config = json.loads(config_json)
            
            required_fields = ["template_id", "clusters", "policies"]
            for field in required_fields:
                if field not in parsed_config:
                    print(f"✗ Missing required field: {field}")
                    return False
            
            print(f"✓ Exported configuration has all required fields")
            print(f"  - template_id: {parsed_config['template_id']}")
            print(f"  - clusters: {len(parsed_config['clusters'])}")
            print(f"  - policies: {list(parsed_config['policies'].keys())}")
            
            return True
            
        except Exception as e:
            print(f"✗ Config export failed: {e}")
            return False

    def test_projector_schema_compute_units(self) -> bool:
        """Test 6: Projector support for expanded schema templates and metadata"""
        print("\n[Test 6] Projector Schema Compute Units")
        print("-" * 70)

        try:
            template_dir = Path(__file__).parent.parent / "architecture" / "architecture_templates"
            projector = TemplateProjector()

            for template_id in sorted(REQUIRED_TEMPLATE_IDS):
                template_path = template_dir / f"{template_id}.json"
                if not template_path.exists():
                    print(f"✗ Missing required expanded template file: {template_path.name}")
                    return False
                template_dict = json.loads(template_path.read_text())
                projected = projector.project_template(template_dict)
                projected_types = {
                    cluster["compute_unit"]["type"]
                    for cluster in projected["clusters"]
                }

                if not projected_types:
                    print(f"✗ {template_id}: no projected compute types")
                    return False

                if projected["architecture_family"] != template_dict["family"]:
                    print(f"✗ {template_id}: family not preserved in projection")
                    return False

                metadata = projected.get("template_metadata", {})
                tags = set(metadata.get("dse_metadata", {}).get("tags", []))
                if not ({"scaffold_only", "projection_only"} <= tags):
                    print(f"✗ {template_id}: expanded scaffold template missing scaffold/projection tags")
                    return False

                if "notes" not in metadata or "component_overrides" not in metadata:
                    print(f"✗ {template_id}: projection metadata incomplete")
                    return False

                source_units = {
                    cluster["compute_unit"].get("source_compute_unit")
                    for cluster in projected["clusters"]
                }
                if not source_units:
                    print(f"✗ {template_id}: source compute units not preserved")
                    return False

                print(f"✓ {template_dict['template_id']}: projected compute types {sorted(projected_types)}")

            return True

        except Exception as e:
            print(f"✗ Projector schema compute-unit test failed: {e}")
            return False


def main():
    """Run end-to-end validation"""
    validator = TemplateSystemValidator()
    success = validator.run_all_tests()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
