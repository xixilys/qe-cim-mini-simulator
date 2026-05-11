#!/usr/bin/env python3
"""
Architecture Candidate Generator

Generates candidate architectures from templates by sweeping parameter spaces.
Supports multiple sweep strategies: grid search, random sampling, and Latin Hypercube Sampling.
"""

import json
import copy
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import itertools
import random


class SweepStrategy(Enum):
    GRID_SEARCH = "grid_search"
    RANDOM_SAMPLING = "random_sampling"
    LATIN_HYPERCUBE = "latin_hypercube"


@dataclass
class ParameterRange:
    """Defines a parameter and its sweep range"""
    path: str
    values: List[Any]
    
    def get_nested_value(self, data: Dict[str, Any]) -> Any:
        """Get value from nested dictionary using dot notation"""
        keys = self.path.split('.')
        value = data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        return value
    
    def set_nested_value(self, data: Dict[str, Any], value: Any):
        """Set value in nested dictionary using dot notation"""
        keys = self.path.split('.')
        target = data
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value


@dataclass
class CandidateArchitecture:
    """A candidate architecture generated from a template"""
    template_id: str
    candidate_id: str
    config: Dict[str, Any]
    parameter_values: Dict[str, Any] = field(default_factory=dict)
    
    def to_json(self) -> str:
        """Serialize to JSON"""
        return json.dumps(self.config, indent=2)
    
    def save(self, output_path: Path):
        """Save candidate to file"""
        with open(output_path, 'w') as f:
            f.write(self.to_json())


class ArchitectureCandidateGenerator:
    """Generates candidate architectures from templates"""
    
    def __init__(self, seed: Optional[int] = None):
        """Initialize generator with optional random seed"""
        if seed is not None:
            random.seed(seed)
        self.seed = seed
    
    def generate_candidates(
        self,
        template: Dict[str, Any],
        param_ranges: Dict[str, List[Any]],
        strategy: SweepStrategy = SweepStrategy.GRID_SEARCH,
        n_samples: Optional[int] = None
    ) -> List[CandidateArchitecture]:
        """Generate candidate architectures from template"""
        
        if strategy == SweepStrategy.GRID_SEARCH:
            return self._grid_search(template, param_ranges)
        elif strategy == SweepStrategy.RANDOM_SAMPLING:
            if n_samples is None:
                raise ValueError("n_samples required for random sampling")
            return self._random_sampling(template, param_ranges, n_samples)
        elif strategy == SweepStrategy.LATIN_HYPERCUBE:
            if n_samples is None:
                raise ValueError("n_samples required for Latin Hypercube sampling")
            return self._latin_hypercube_sampling(template, param_ranges, n_samples)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")
    
    def _grid_search(
        self,
        template: Dict[str, Any],
        param_ranges: Dict[str, List[Any]]
    ) -> List[CandidateArchitecture]:
        """Generate all combinations using grid search"""
        
        param_names = list(param_ranges.keys())
        param_value_lists = [param_ranges[name] for name in param_names]
        
        candidates = []
        for i, combination in enumerate(itertools.product(*param_value_lists)):
            candidate_config = copy.deepcopy(template)
            param_values = {}
            
            for param_name, value in zip(param_names, combination):
                param_range = ParameterRange(param_name, [])
                param_range.set_nested_value(candidate_config, value)
                param_values[param_name] = value
            
            candidate_id = f"{template['template_id']}_grid_{i:04d}"
            candidate = CandidateArchitecture(
                template_id=template['template_id'],
                candidate_id=candidate_id,
                config=candidate_config,
                parameter_values=param_values
            )
            candidates.append(candidate)
        
        return candidates
    
    def _random_sampling(
        self,
        template: Dict[str, Any],
        param_ranges: Dict[str, List[Any]],
        n_samples: int
    ) -> List[CandidateArchitecture]:
        """Generate random samples from parameter space"""
        
        candidates = []
        for i in range(n_samples):
            candidate_config = copy.deepcopy(template)
            param_values = {}
            
            for param_name, values in param_ranges.items():
                value = random.choice(values)
                param_range = ParameterRange(param_name, [])
                param_range.set_nested_value(candidate_config, value)
                param_values[param_name] = value
            
            candidate_id = f"{template['template_id']}_random_{i:04d}"
            candidate = CandidateArchitecture(
                template_id=template['template_id'],
                candidate_id=candidate_id,
                config=candidate_config,
                parameter_values=param_values
            )
            candidates.append(candidate)
        
        return candidates
    
    def _latin_hypercube_sampling(
        self,
        template: Dict[str, Any],
        param_ranges: Dict[str, List[Any]],
        n_samples: int
    ) -> List[CandidateArchitecture]:
        """Generate samples using Latin Hypercube Sampling"""
        
        param_names = list(param_ranges.keys())
        n_params = len(param_names)
        
        lhs_indices = []
        for _ in range(n_params):
            indices = list(range(n_samples))
            random.shuffle(indices)
            lhs_indices.append(indices)
        
        candidates = []
        for i in range(n_samples):
            candidate_config = copy.deepcopy(template)
            param_values = {}
            
            for param_idx, param_name in enumerate(param_names):
                values = param_ranges[param_name]
                n_values = len(values)
                
                lhs_idx = lhs_indices[param_idx][i]
                value_idx = int((lhs_idx / n_samples) * n_values)
                value_idx = min(value_idx, n_values - 1)
                
                value = values[value_idx]
                param_range = ParameterRange(param_name, [])
                param_range.set_nested_value(candidate_config, value)
                param_values[param_name] = value
            
            candidate_id = f"{template['template_id']}_lhs_{i:04d}"
            candidate = CandidateArchitecture(
                template_id=template['template_id'],
                candidate_id=candidate_id,
                config=candidate_config,
                parameter_values=param_values
            )
            candidates.append(candidate)
        
        return candidates
    
    def generate_default_param_ranges(
        self,
        template: Dict[str, Any]
    ) -> Dict[str, List[Any]]:
        """Generate default parameter ranges based on template"""
        
        param_ranges = {}
        
        if "compute_config" in template:
            compute_config = template["compute_config"]
            
            if "clock_mhz" in compute_config:
                base_clock = compute_config["clock_mhz"]
                param_ranges["compute_config.clock_mhz"] = [
                    int(base_clock * 0.8),
                    base_clock,
                    int(base_clock * 1.2)
                ]
            
            if "gemm_tile_size" in compute_config:
                param_ranges["compute_config.gemm_tile_size"] = [16, 32, 64]
            
            if "dsp_array_dims" in compute_config:
                param_ranges["compute_config.dsp_array_dims.rows"] = [8, 16, 32]
                param_ranges["compute_config.dsp_array_dims.cols"] = [8, 16, 32]
        
        if "memory_hierarchy" in template:
            mem_hierarchy = template["memory_hierarchy"]
            
            if "l1_buffer_kb" in mem_hierarchy:
                base_l1 = mem_hierarchy["l1_buffer_kb"]
                param_ranges["memory_hierarchy.l1_buffer_kb"] = [
                    base_l1 // 2,
                    base_l1,
                    base_l1 * 2
                ]
            
            if "resident_budget_scale" in mem_hierarchy:
                param_ranges["memory_hierarchy.resident_budget_scale"] = [0.8, 1.0, 1.2]
        
        return param_ranges


def main():
    """Test the candidate generator"""
    import sys
    from architecture_template_loader import ArchitectureTemplateLoader
    
    if len(sys.argv) > 1:
        template_path = Path(sys.argv[1])
    else:
        template_dir = Path(__file__).parent.parent / "architecture" / "architecture_templates"
        template_path = template_dir / "4cluster_traditional_fpga_v1.json"
    
    print(f"Loading template: {template_path}")
    print("=" * 60)
    
    loader = ArchitectureTemplateLoader()
    template_obj = loader.load_template(template_path)
    template_dict = json.loads(template_path.read_text())
    
    generator = ArchitectureCandidateGenerator(seed=42)
    
    print("\n1. Grid Search Strategy")
    print("-" * 60)
    param_ranges_grid = {
        "compute_config.clock_mhz": [250, 300, 350],
        "compute_config.gemm_tile_size": [16, 32]
    }
    candidates_grid = generator.generate_candidates(
        template_dict,
        param_ranges_grid,
        strategy=SweepStrategy.GRID_SEARCH
    )
    print(f"Generated {len(candidates_grid)} candidates")
    for i, candidate in enumerate(candidates_grid[:3]):
        print(f"  Candidate {i}: {candidate.parameter_values}")
    
    print("\n2. Random Sampling Strategy")
    print("-" * 60)
    param_ranges_random = {
        "compute_config.clock_mhz": [200, 250, 300, 350],
        "compute_config.gemm_tile_size": [16, 32, 64],
        "memory_hierarchy.l1_buffer_kb": [128, 256, 512]
    }
    candidates_random = generator.generate_candidates(
        template_dict,
        param_ranges_random,
        strategy=SweepStrategy.RANDOM_SAMPLING,
        n_samples=10
    )
    print(f"Generated {len(candidates_random)} candidates")
    for i, candidate in enumerate(candidates_random[:3]):
        print(f"  Candidate {i}: {candidate.parameter_values}")
    
    print("\n3. Latin Hypercube Sampling Strategy")
    print("-" * 60)
    candidates_lhs = generator.generate_candidates(
        template_dict,
        param_ranges_random,
        strategy=SweepStrategy.LATIN_HYPERCUBE,
        n_samples=10
    )
    print(f"Generated {len(candidates_lhs)} candidates")
    for i, candidate in enumerate(candidates_lhs[:3]):
        print(f"  Candidate {i}: {candidate.parameter_values}")
    
    print("\n4. Auto-generated Parameter Ranges")
    print("-" * 60)
    auto_ranges = generator.generate_default_param_ranges(template_dict)
    print(f"Auto-generated {len(auto_ranges)} parameter ranges:")
    for param_name, values in auto_ranges.items():
        print(f"  {param_name}: {values}")
    
    print("\n" + "=" * 60)
    print(f"Total candidates generated: {len(candidates_grid) + len(candidates_random) + len(candidates_lhs)}")


if __name__ == "__main__":
    main()
