#!/usr/bin/env python3
"""Test generic SystemC backend integration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dse_v2.core.ir.compute_graph import create_dft_scf_graph
from dse_v2.core.ir.dft_workload import create_complete_qe_scf_graph
from dse_v2.core.architecture.accelerator import create_gpu_a100, create_fpga_u280, create_cim_array
from dse_v2.dse.orchestrator import DesignPoint, SystemArchitecture
from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend
from dse_v2.evidence.full_flow import REQUIRED_QE_SCF_PHASES


def test_request_builder():
    print("Testing GenericSystemCBackend request builder...")
    
    g = create_dft_scf_graph()
    sys_arch = SystemArchitecture(
        system_id='test',
        accelerators=[create_gpu_a100('gpu-0')],
    )
    m = {nid: 'gpu-0' for nid in g.nodes}
    dp = DesignPoint('dp_test', sys_arch, m)
    
    backend = GenericSystemCBackend()
    request = backend._build_request(dp, g)
    
    assert request['schema_version'] == 'gsim.request.v1'
    assert request['run_id'] == 'dp_test'
    assert len(request['workload']['nodes']) == 4
    assert len(request['architecture']['accelerators']) == 1
    
    print("  Request structure: PASS")
    
    # Check accelerator capabilities
    accel = request['architecture']['accelerators'][0]
    assert accel['accel_type'] == 'gpu'
    assert 'gemm' in accel['capabilities']
    
    print("  Accelerator capabilities: PASS")
    print("  All tests passed!")


def test_complete_workload():
    print("\nTesting with complete workload...")
    
    g = create_complete_qe_scf_graph()
    sys_arch = SystemArchitecture(
        system_id='test',
        accelerators=[
            create_gpu_a100('gpu-0'),
            create_fpga_u280('fpga-0'),
        ],
    )
    
    # Map different ops to different accelerators
    m = {
        'h_psi': 'gpu-0',
        's_psi': 'gpu-0',
        'vnl': 'gpu-0',
        'precondition': 'gpu-0',
        'orthogonalize': 'fpga-0',
        'build_H_sub': 'fpga-0',
        'build_S_sub': 'fpga-0',
        'diagonalize': 'fpga-0',
        'subspace_rotation': 'gpu-0',
        'refresh': 'gpu-0',
        'residual': 'gpu-0',
        'rho_out': 'gpu-0',
        'mix_rho': 'gpu-0',
        'veff': 'gpu-0',
    }
    
    dp = DesignPoint('dp_complete', sys_arch, m)
    backend = GenericSystemCBackend()
    request = backend._build_request(dp, g)
    
    assert len(request['workload']['nodes']) == 14
    for phase in REQUIRED_QE_SCF_PHASES:
        assert phase in request['workload']['nodes']
    assert len(request['architecture']['accelerators']) == 2
    
    print("  Complete workload: PASS")
    print(f"  Nodes: {len(request['workload']['nodes'])}")
    print(f"  Accelerators: {len(request['architecture']['accelerators'])}")


def test_error_handling():
    print("\nTesting error handling...")
    
    g = create_dft_scf_graph()
    sys_arch = SystemArchitecture(system_id='test', accelerators=[create_gpu_a100('gpu-0')])
    m = {nid: 'gpu-0' for nid in g.nodes}
    dp = DesignPoint('dp_error', sys_arch, m)
    
    backend = GenericSystemCBackend(executable_path='/nonexistent/path')
    result = backend.evaluate(dp, g)
    
    assert not result['feasible']
    assert 'error' in result
    
    print("  Error handling: PASS")
    print(f"  Error message: {result['error']}")


def main():
    print("=" * 70)
    print("Generic SystemC Backend Integration Test")
    print("=" * 70)
    
    test_request_builder()
    test_complete_workload()
    test_error_handling()
    
    print("\n" + "=" * 70)
    print("All tests passed!")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
