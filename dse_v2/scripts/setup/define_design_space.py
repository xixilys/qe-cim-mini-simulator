#!/usr/bin/env python3

import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any
from enum import Enum

class OffloadStrategy(Enum):
    H_PSI_ONLY = "h_psi_only"
    H_S_PSI_FUSED = "h_s_psi_fused"
    FULL_OPERATOR_SWEEP = "full_operator_sweep"
    INCLUDE_DIAG = "include_diag"

class DataflowPattern(Enum):
    STREAMING = "streaming"
    BUFFERED = "buffered"
    HYBRID = "hybrid"

class KernelImpl(Enum):
    FFT_DSP = "fft_dsp"
    FFT_BRAM = "fft_bram"
    SYSTOLIC = "systolic"
    MIXED = "mixed"

@dataclass
class DesignSpaceDefinition:
    version: str = "v2.0"
    description: str = "Host+FPGA two-layer architecture design space"
    
    categorical_params: Dict[str, List[str]] = None
    integer_params: Dict[str, Dict[str, Any]] = None
    constraints: List[Dict[str, Any]] = None
    objectives: Dict[str, Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.categorical_params is None:
            self.categorical_params = {
                "offload_strategy": [s.value for s in OffloadStrategy],
                "dataflow_pattern": [p.value for p in DataflowPattern],
                "psi_strategy": ["stream", "tile", "resident"],
                "beta_strategy": ["resident", "cache", "stream"],
                "h_psi_impl": [impl.value for impl in KernelImpl],
                "gemm_impl": ["dsp_array", "systolic", "winograd"],
                "overlap_policy": ["none", "compute_dma", "full_pipeline"],
            }
        
        if self.integer_params is None:
            self.integer_params = {
                "pipeline_depth": {"min": 2, "max": 5},
                "parallel_units": {"values": [1, 2, 4, 8]},
                "intermediate_buffer_kb": {"values": [64, 128, 256, 512, 1024]},
                "tile_npw": {"values": [256, 512, 1024, 2048]},
                "tile_nkb": {"values": [16, 32, 64, 144]},
                "tile_m": {"values": [4, 8, 16, 32]},
                "dma_channels": {"values": [1, 2, 4]},
                "pcie_gen": {"values": [3, 4, 5]},
            }
        
        if self.constraints is None:
            self.constraints = [
                {
                    "type": "resource",
                    "name": "dsp_utilization",
                    "max": 0.85,
                    "description": "DSP utilization must not exceed 85%"
                },
                {
                    "type": "resource",
                    "name": "bram_utilization",
                    "max": 0.85,
                    "description": "BRAM utilization must not exceed 85%"
                },
            ]
        
        if self.objectives is None:
            self.objectives = {
                "primary": {
                    "name": "time_to_convergence_s",
                    "minimize": True,
                    "weight": 1.0
                },
                "secondary": {
                    "name": "energy_to_convergence_j",
                    "minimize": True,
                    "weight": 0.5
                },
            }
    
    def calculate_space_size(self) -> int:
        cat_size = 1
        for values in self.categorical_params.values():
            cat_size *= len(values)
        
        int_size = 1
        for param in self.integer_params.values():
            if 'values' in param:
                int_size *= len(param['values'])
            else:
                int_size *= (param['max'] - param['min'] + 1)
        
        return cat_size * int_size
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'version': self.version,
            'description': self.description,
            'categorical_params': self.categorical_params,
            'integer_params': self.integer_params,
            'constraints': self.constraints,
            'objectives': self.objectives,
            'total_configurations': self.calculate_space_size(),
        }

def create_design_space():
    design_space = DesignSpaceDefinition()
    
    output_dir = Path('design_space/definitions')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / 'host_fpga_design_space_v2.json'
    
    with open(output_file, 'w') as f:
        json.dump(design_space.to_dict(), f, indent=2)
    
    total_size = design_space.calculate_space_size()
    
    print(f"✅ Design space definition saved to {output_file}")
    print(f"📊 Total configurations: {total_size:,}")
    print(f"⚠️  Requires intelligent search (Bayesian Optimization)")
    
    return design_space

if __name__ == '__main__':
    create_design_space()
