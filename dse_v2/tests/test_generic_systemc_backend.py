#!/usr/bin/env python3
"""Test generic SystemC backend integration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dse_v2.core.ir.compute_graph import ComputeGraph, ComputeNode, DataEdge, TensorSpec
from dse_v2.reference_workloads.dft_qe import QE_SCF_REQUIRED_COVERAGE, create_qe_reference_package
from dse_v2.core.architecture.accelerator import create_gpu_a100, create_fpga_u280, create_cim_array
from dse_v2.dse.orchestrator import DesignPoint, SystemArchitecture
from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend


def test_request_builder():
    print("Testing GenericSystemCBackend request builder...")
    
    from dse_v2.core.workload import create_tensor_chain_graph
    g = create_tensor_chain_graph("tensor_request")
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
    assert len(request['workload']['nodes']) == 3
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
    
    package = create_qe_reference_package()
    g = package.graph
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
    request = backend._build_request(dp, g, workload_package=package)
    
    assert len(request['workload']['nodes']) == 14
    assert request['workload']['required_coverage'] == QE_SCF_REQUIRED_COVERAGE
    for phase in QE_SCF_REQUIRED_COVERAGE:
        assert phase in request['workload']['nodes']
    assert len(request['architecture']['accelerators']) == 2
    
    print("  Complete workload: PASS")
    print(f"  Nodes: {len(request['workload']['nodes'])}")
    print(f"  Accelerators: {len(request['architecture']['accelerators'])}")


def test_request_builder_preserves_tensor_byte_metadata():
    g = ComputeGraph(graph_id='byte_metadata_graph')
    g.add_node(ComputeNode(
        node_id='producer',
        op_type='gemm',
        outputs=['x'],
        estimated_flops=1024.0,
        estimated_memory_bytes=256.0,
    ))
    g.add_node(ComputeNode(
        node_id='consumer',
        op_type='reduction',
        inputs=['x'],
        estimated_flops=256.0,
        estimated_memory_bytes=128.0,
    ))
    g.add_edge(DataEdge(
        source_node='producer',
        target_node='consumer',
        tensor_name='x',
        tensor_spec=TensorSpec(shape=(8, 4), dtype='BF16'),
    ))

    sys_arch = SystemArchitecture(
        system_id='test',
        accelerators=[create_fpga_u280('fpga-0'), create_cim_array('cim-0')],
    )
    dp = DesignPoint('dp_tensor_bytes', sys_arch, {'producer': 'fpga-0', 'consumer': 'cim-0'})
    request = GenericSystemCBackend()._build_request(dp, g)

    edge = request['workload']['edges'][0]
    assert edge['tensor_shape'] == [8, 4]
    assert edge['tensor_dtype'] == 'BF16'
    assert edge['element_size'] == 2
    assert edge['size_bytes'] == 64


def test_generic_request_schema_declares_supported_modes_and_tensor_sizes():
    schema_path = Path(__file__).resolve().parents[2] / 'model' / 'generic_sim_backend' / 'schemas' / 'simulation_request_v1.json'
    schema = __import__('json').loads(schema_path.read_text())

    assert 'standalone_systemc' in schema['properties']['mode']['enum']
    assert 'legacy_4cluster' not in schema['properties']['mode']['enum']
    edge_props = schema['properties']['workload']['properties']['edges']['items']['properties']
    assert 'size_bytes' in edge_props
    assert 'element_size' in edge_props


def test_error_handling():
    print("\nTesting error handling...")
    
    from dse_v2.core.workload import create_tensor_chain_graph
    g = create_tensor_chain_graph("tensor_request")
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
    test_request_builder_preserves_tensor_byte_metadata()
    test_generic_request_schema_declares_supported_modes_and_tensor_sizes()
    test_error_handling()
    
    print("\n" + "=" * 70)
    print("All tests passed!")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
