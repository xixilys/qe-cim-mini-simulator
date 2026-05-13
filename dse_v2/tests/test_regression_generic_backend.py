#!/usr/bin/env python3
"""Regression test: GPU/FPGA/CIM must produce different results."""

import json
import tempfile
import subprocess
from pathlib import Path


def create_test_request(accel_type, peak_gops):
    """Create a test request with a single accelerator."""
    return {
        "schema_version": "gsim.request.v1",
        "run_id": f"test_{accel_type}",
        "mode": "standalone_systemc",
        "workload": {
            "graph_id": "test_graph",
            "nodes": {
                "node1": {
                    "op_type": "gemm",
                    "inputs": ["input1"],
                    "outputs": ["output1"],
                    "estimated_flops": 1e9,
                    "estimated_memory_bytes": 8e6,
                    "attributes": {}
                }
            },
            "edges": [],
            "metadata": {}
        },
        "architecture": {
            "host": {
                "cpu_model": "abstract",
                "clock_mhz": 3000,
                "memory_bw_gbps": 100,
                "cores": 1
            },
            "interconnect": {
                "type": "pcie",
                "bandwidth_gbps": 64,
                "latency_ns": 800
            },
            "accelerators": [
                {
                    "accel_id": f"accel_{accel_type}",
                    "accel_type": accel_type,
                    "clock_mhz": 250,
                    "local_memory_kb": 2048,
                    "power": {
                        "static_w": 10,
                        "max_w": 100
                    },
                    "capabilities": {
                        "gemm": {
                            "peak_gops": peak_gops,
                            "efficiency": 0.7
                        }
                    }
                }
            ]
        },
        "mapping": {
            "node1": f"accel_{accel_type}"
        },
        "scheduling": {
            "policy": "static",
            "allow_overlap_dma_compute": True,
            "double_buffer": True
        },
        "output": {
            "result_json": "/tmp/test_result.json",
            "trace_json": "/tmp/test_trace.json"
        }
    }


def run_simulation(request):
    """Run the C++ simulator with the given request."""
    executable = Path("model/generic_sim_backend/build/generic_sim")
    if not executable.exists():
        executable = Path("/mnt/f/phd/year_2/project/dft_accelerate/model/generic_sim_backend/build/generic_sim")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(request, f)
        request_path = f.name
    
    result_path = request_path.replace('.json', '.result.json')
    
    cmd = [
        str(executable),
        "--request", request_path,
        "--result", result_path,
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    
    if result.returncode != 0:
        print(f"Simulation failed: {result.stderr}")
        return None
    
    with open(result_path) as f:
        return json.load(f)


def check_architecture_differentiation():
    """Test that different accelerators produce different latencies."""
    print("Testing architecture differentiation...")
    
    configs = [
        ("gpu", 10000),    # 10 TFLOPS
        ("fpga", 1000),    # 1 TFLOPS
        ("cim", 100),      # 100 GFLOPS
    ]
    
    results = {}
    for accel_type, peak_gops in configs:
        request = create_test_request(accel_type, peak_gops)
        result = run_simulation(request)
        if result is None:
            print(f"  FAIL: Could not run simulation for {accel_type}")
            return False
        
        latency = result["metrics"]["latency_ms"]
        results[accel_type] = latency
        print(f"  {accel_type}: {latency:.4f} ms (peak_gops={peak_gops})")
    
    # Check that results are different
    gpu_latency = results["gpu"]
    fpga_latency = results["fpga"]
    cim_latency = results["cim"]
    
    # GPU should be fastest, CIM slowest
    if not (gpu_latency < fpga_latency < cim_latency):
        print(f"  FAIL: Expected gpu < fpga < cim")
        print(f"  Got: gpu={gpu_latency}, fpga={fpga_latency}, cim={cim_latency}")
        return False
    
    # Check that differences are significant (> 10%)
    if fpga_latency / gpu_latency < 1.1:
        print(f"  FAIL: GPU/FPGA difference too small")
        return False
    
    if cim_latency / fpga_latency < 1.1:
        print(f"  FAIL: FPGA/CIM difference too small")
        return False
    
    print("  PASS: Architecture differentiation works correctly")
    return True


def test_architecture_differentiation():
    """Pytest wrapper for architecture differentiation regression."""
    assert check_architecture_differentiation()


def check_parser_node_count():
    """Test that parser correctly counts nodes."""
    print("Testing parser node count...")
    
    request = create_test_request("gpu", 1000)
    request["workload"]["nodes"]["node2"] = {
        "op_type": "fft",
        "inputs": ["output1"],
        "outputs": ["output2"],
        "estimated_flops": 5e8,
        "estimated_memory_bytes": 4e6,
        "attributes": {}
    }
    request["workload"]["edges"] = [
        {
            "source": "node1",
            "target": "node2",
            "tensor_name": "output1",
            "tensor_shape": [1024, 1024],
            "tensor_dtype": "FP64"
        }
    ]
    
    result = run_simulation(request)
    if result is None:
        print("  FAIL: Simulation failed")
        return False
    
    # Check that we have 2 events (one per node)
    events = result.get("events", [])
    if len(events) != 2:
        print(f"  FAIL: Expected 2 events, got {len(events)}")
        return False
    
    print(f"  PASS: Correctly parsed 2 nodes and 1 edge")
    return True


def test_parser_node_count():
    """Pytest wrapper for parser node count regression."""
    assert check_parser_node_count()


def test_invalid_schema_version_is_rejected():
    request = create_test_request("gpu", 1000)
    request["schema_version"] = "gsim.request.v0"

    assert run_simulation(request) is None


if __name__ == "__main__":
    print("Running Generic SystemC Backend Regression Tests\n")
    
    test1 = check_architecture_differentiation()
    print()
    test2 = check_parser_node_count()
    print()
    test3 = test_invalid_schema_version_is_rejected() is None
    print()
    
    if test1 and test2 and test3:
        print("All regression tests passed!")
    else:
        print("Some tests failed!")
        exit(1)
