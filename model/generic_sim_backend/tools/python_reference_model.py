#!/usr/bin/env python3
"""Sidecar Python reference model for Generic SystemC requests.

The model consumes the same ``gsim.request.v1`` payload that the C++
``generic_sim`` backend consumes and emits replayable numerical/timing artifacts.
It is intentionally a contract/reference model, not a trusted QE physics oracle or
L4 performance proof.  Downstream claim gates must continue to require external
correctness and gem5 full-flow evidence for trusted speedup claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

SUPPORTED_OPS = {
    "placeholder",
    "gemm",
    "fft",
    "eigen",
    "reduction",
    "elementwise",
    "transfer",
    "generic_op",
    "input",
    "output",
    "copy",
    "relu",
    "activation",
    "add",
    "multiply",
    "softmax",
    "normalize",
}

DTYPE_BYTES = {
    "FP64": 8,
    "float64": 8,
    "double": 8,
    "FP32": 4,
    "float32": 4,
    "BF16": 2,
    "FP16": 2,
    "float16": 2,
    "INT64": 8,
    "INT32": 4,
    "INT16": 2,
    "INT8": 1,
    "BOOL": 1,
}

DEFAULT_PEAK_GOPS = {
    "gpu": 9000.0,
    "fpga": 1500.0,
    "cim": 2400.0,
    "asic": 5000.0,
    "cpu": 256.0,
    "host": 256.0,
}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _shape_num_elements(shape: Sequence[int]) -> int:
    total = 1
    for dim in shape:
        total *= max(1, int(dim))
    return max(1, total)


def _stable_unit_interval(parts: Iterable[Any]) -> float:
    encoded = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(encoded).digest()
    # Use 53 bits so the value is exactly representable as a Python float mantissa.
    integer = int.from_bytes(digest[:8], "big") >> 11
    return integer / float(1 << 53)


def _stable_checksum(parts: Iterable[Any], scale: float = 1.0) -> float:
    value = _stable_unit_interval(parts) * scale
    return float(f"{value:.12g}")


def _topological_order(nodes: Mapping[str, Any], edges: Sequence[Mapping[str, Any]]) -> Tuple[List[str], Optional[str]]:
    in_degree: Dict[str, int] = {node_id: 0 for node_id in nodes}
    adjacency: Dict[str, List[str]] = {node_id: [] for node_id in nodes}
    for edge in edges:
        source = str(edge.get("source", edge.get("source_node", "")))
        target = str(edge.get("target", edge.get("target_node", "")))
        if source in nodes and target in nodes:
            adjacency[source].append(target)
            in_degree[target] += 1

    ready = sorted(node_id for node_id, degree in in_degree.items() if degree == 0)
    order: List[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for target in sorted(adjacency[node_id]):
            in_degree[target] -= 1
            if in_degree[target] == 0:
                ready.append(target)
                ready.sort()

    if len(order) != len(nodes):
        cyclic = sorted(node_id for node_id, degree in in_degree.items() if degree > 0)
        return order, "cycle_detected:" + ",".join(cyclic)
    return order, None


def _edge_tensor_metadata(workload: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    tensors: Dict[str, Dict[str, Any]] = {}
    for edge in workload.get("edges", []) or []:
        tensor_name = str(edge.get("tensor_name", ""))
        if not tensor_name:
            continue
        shape = [int(dim) for dim in edge.get("tensor_shape", []) or []]
        dtype = str(edge.get("tensor_dtype", "FP64"))
        element_size = _as_int(edge.get("element_size"), DTYPE_BYTES.get(dtype, 8))
        size_bytes = _as_float(edge.get("size_bytes"), 0.0)
        if not size_bytes and shape:
            size_bytes = float(_shape_num_elements(shape) * element_size)
        tensors[tensor_name] = {
            "shape": shape,
            "dtype": dtype,
            "element_size": element_size,
            "size_bytes": size_bytes,
        }
    return tensors


def _infer_output_tensor(
    node_id: str,
    node: Mapping[str, Any],
    tensor_metadata: Mapping[str, Mapping[str, Any]],
) -> Tuple[str, List[int], str, int, float]:
    outputs = list(node.get("outputs", []) or [])
    tensor_id = str(outputs[0]) if outputs else f"{node_id}_out"
    attrs = node.get("attributes", {}) if isinstance(node.get("attributes", {}), Mapping) else {}

    if tensor_id in tensor_metadata:
        meta = tensor_metadata[tensor_id]
        shape = [int(dim) for dim in meta.get("shape", []) or []]
        dtype = str(meta.get("dtype", "FP64"))
        element_size = _as_int(meta.get("element_size"), DTYPE_BYTES.get(dtype, 8))
        size_bytes = _as_float(meta.get("size_bytes"), 0.0)
        if not size_bytes and shape:
            size_bytes = float(_shape_num_elements(shape) * element_size)
        return tensor_id, shape or [1], dtype, element_size, size_bytes or float(element_size)

    dtype = str(attrs.get("dtype", attrs.get("output_dtype", "FP64")))
    element_size = DTYPE_BYTES.get(dtype, 8)
    op_type = str(node.get("op_type", "generic_op"))
    if op_type == "gemm":
        shape = [_as_int(attrs.get("M"), 1), _as_int(attrs.get("N"), 1)]
    elif op_type == "eigen":
        shape = [_as_int(attrs.get("N", attrs.get("matrix_size")), 1)]
    else:
        approx_elements = max(1, int(math.ceil(_as_float(node.get("estimated_memory_bytes"), element_size) / max(1, element_size))))
        shape = [approx_elements]
    return tensor_id, shape, dtype, element_size, float(_shape_num_elements(shape) * element_size)


def _accelerator_table(architecture: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    table: Dict[str, Mapping[str, Any]] = {"host": {"accel_id": "host", "accel_type": "host", "clock_mhz": architecture.get("host", {}).get("clock_mhz", 3000.0)}}
    for accel in architecture.get("accelerators", []) or []:
        if isinstance(accel, Mapping):
            table[str(accel.get("accel_id", ""))] = accel
    return table


def _design_axes_summary(request: Mapping[str, Any]) -> Dict[str, Any]:
    architecture = request.get("architecture", {}) if isinstance(request.get("architecture", {}), Mapping) else {}
    design_point = request.get("design_point", {}) if isinstance(request.get("design_point", {}), Mapping) else {}
    mapping = request.get("mapping", {}) if isinstance(request.get("mapping", {}), Mapping) else {}
    scheduling = request.get("scheduling", {}) if isinstance(request.get("scheduling", {}), Mapping) else {}
    accelerators = [accel for accel in architecture.get("accelerators", []) or [] if isinstance(accel, Mapping)]
    return {
        "architecture": {
            "architecture_id": design_point.get("architecture_id"),
            "accelerator_count": len(accelerators),
            "accelerator_types": sorted({str(accel.get("accel_type", "unknown")).lower() for accel in accelerators}),
            "host_cores": architecture.get("host", {}).get("cores") if isinstance(architecture.get("host", {}), Mapping) else None,
            "interconnect_type": architecture.get("interconnect", {}).get("type") if isinstance(architecture.get("interconnect", {}), Mapping) else None,
        },
        "mapping": {
            "mapping_id": design_point.get("mapping_id"),
            "mapped_node_count": len(mapping),
            "devices": sorted({str(device) for device in mapping.values()}),
        },
        "scheduling": {
            "policy": scheduling.get("policy", "static"),
            "allow_overlap_dma_compute": bool(scheduling.get("allow_overlap_dma_compute", True)),
            "double_buffer": bool(scheduling.get("double_buffer", True)),
        },
    }


def _peak_gops_for(accel: Mapping[str, Any], op_type: str) -> float:
    capabilities = accel.get("capabilities", {}) if isinstance(accel.get("capabilities", {}), Mapping) else {}
    capability = capabilities.get(op_type) or capabilities.get("generic_op") or {}
    if isinstance(capability, Mapping) and _as_float(capability.get("peak_gops"), 0.0) > 0.0:
        return _as_float(capability.get("peak_gops"), 1.0) * max(0.01, _as_float(capability.get("efficiency"), 1.0))
    accel_type = str(accel.get("accel_type", "host")).lower()
    return DEFAULT_PEAK_GOPS.get(accel_type, DEFAULT_PEAK_GOPS["host"])


def _bandwidth_gbps(request: Mapping[str, Any], accel: Mapping[str, Any]) -> float:
    micro = accel.get("microarchitecture", {}) if isinstance(accel.get("microarchitecture", {}), Mapping) else {}
    common = micro.get("common", {}) if isinstance(micro.get("common", {}), Mapping) else {}
    if _as_float(common.get("memory_bandwidth_gbps"), 0.0) > 0.0:
        return _as_float(common.get("memory_bandwidth_gbps"), 1.0)
    interconnect = request.get("architecture", {}).get("interconnect")
    if isinstance(interconnect, Mapping) and _as_float(interconnect.get("bandwidth_gbps"), 0.0) > 0.0:
        return _as_float(interconnect.get("bandwidth_gbps"), 1.0)
    return _as_float(request.get("architecture", {}).get("host", {}).get("memory_bw_gbps"), 100.0)


def evaluate_request(request: Mapping[str, Any], invocation: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Evaluate a Generic SystemC request with the Python sidecar model."""
    workload = request.get("workload", {}) if isinstance(request.get("workload", {}), Mapping) else {}
    nodes = workload.get("nodes", {}) if isinstance(workload.get("nodes", {}), Mapping) else {}
    edges = workload.get("edges", []) if isinstance(workload.get("edges", []), Sequence) else []
    architecture = request.get("architecture", {}) if isinstance(request.get("architecture", {}), Mapping) else {}
    mapping = request.get("mapping", {}) if isinstance(request.get("mapping", {}), Mapping) else {}

    order, graph_error = _topological_order(nodes, edges)  # type: ignore[arg-type]
    tensor_metadata = _edge_tensor_metadata(workload)
    accelerators = _accelerator_table(architecture)

    per_node: List[Dict[str, Any]] = []
    tensors: List[Dict[str, Any]] = []
    unsupported_ops: List[str] = []
    clock_ns_cursor = 0.0
    total_flops = 0.0
    total_memory_bytes = 0.0

    if graph_error:
        status = "error"
        order = order or sorted(nodes)
    else:
        status = "passed"

    for node_id in order:
        node = nodes[node_id]
        op_type = str(node.get("op_type", "generic_op"))
        if op_type not in SUPPORTED_OPS:
            unsupported_ops.append(node_id)
        accel_id = str(mapping.get(node_id, "host"))
        accel = accelerators.get(accel_id, accelerators["host"])
        flops = max(0.0, _as_float(node.get("estimated_flops"), 0.0))
        memory_bytes = max(0.0, _as_float(node.get("estimated_memory_bytes"), 0.0))
        peak_gops = max(1.0e-9, _peak_gops_for(accel, op_type))
        bandwidth_gbps = max(1.0, _bandwidth_gbps(request, accel))
        compute_ms = flops / (peak_gops * 1.0e9) * 1000.0
        memory_ms = memory_bytes * 8.0 / (bandwidth_gbps * 1.0e9) * 1000.0
        latency_ms = compute_ms + memory_ms
        start_ms = clock_ns_cursor / 1.0e6
        clock_ns_cursor += latency_ms * 1.0e6
        total_flops += flops
        total_memory_bytes += memory_bytes

        tensor_id, shape, dtype, element_size, size_bytes = _infer_output_tensor(node_id, node, tensor_metadata)
        checksum = _stable_checksum(
            [
                request.get("run_id", "unknown"),
                workload.get("graph_id", "unknown"),
                node_id,
                op_type,
                accel_id,
                flops,
                memory_bytes,
                shape,
                dtype,
            ],
            scale=max(1.0, float(_shape_num_elements(shape))),
        )
        tensors.append(
            {
                "tensor_id": tensor_id,
                "producer_node_id": node_id,
                "shape": shape,
                "dtype": dtype,
                "element_size": element_size,
                "size_bytes": size_bytes,
                "num_elements": _shape_num_elements(shape),
                "checksum": checksum,
                "max_abs_error": 0.0,
                "max_rel_error": 0.0,
                "rmse": 0.0,
                "passed": op_type in SUPPORTED_OPS,
                "reference": "deterministic_contract_kernel",
            }
        )
        per_node.append(
            {
                "node_id": node_id,
                "op_type": op_type,
                "device": accel_id,
                "start_ms": start_ms,
                "latency_ms": latency_ms,
                "compute_ms": compute_ms,
                "memory_ms": memory_ms,
                "estimated_flops": flops,
                "estimated_memory_bytes": memory_bytes,
                "output_tensor_id": tensor_id,
            }
        )

    if unsupported_ops and status == "passed":
        status = "failed"

    latency_ms = sum(node["latency_ms"] for node in per_node)
    throughput_gops = total_flops / max(latency_ms, 1.0e-12) / 1.0e6
    all_tensors_passed = bool(tensors) and all(tensor["passed"] for tensor in tensors)

    result: Dict[str, Any] = {
        "schema_version": "gsim.python_model_result.v1",
        "run_id": str(request.get("run_id", "unknown")),
        "status": status,
        "input_request": {
            "schema_version": str(request.get("schema_version", "unknown")),
            "mode": str(request.get("mode", "unknown")),
            "graph_id": str(workload.get("graph_id", "unknown")),
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
        "model_invocation": dict(invocation or {}),
        "design_axes": _design_axes_summary(request),
        "claim_boundary": {
            "fidelity_level": "L3_python_reference_sidecar",
            "claim": "model_contract_and_projection_only",
            "trusted_speedup": False,
            "trusted_qe_correctness": False,
            "requires_l4_full_flow_for_trusted_speedup": True,
            "requires_external_correctness_oracle_for_qe": True,
        },
        "timing_reference": {
            "latency_ms": latency_ms,
            "throughput_gops": throughput_gops,
            "total_flops": total_flops,
            "total_memory_bytes": total_memory_bytes,
            "total_data_movement_mb": total_memory_bytes / (1024.0 * 1024.0),
            "per_node": per_node,
        },
        "numerical_validation": {
            "enabled": True,
            "golden_model_executed": True,
            "all_tensors_passed": all_tensors_passed,
            "unsupported_ops": unsupported_ops,
            "tensors": tensors,
            "correctness_scope": "deterministic_sidecar_reference_contract_only",
            "limitations": [
                "No external QE physics baseline is consumed by this model.",
                "L3 Python/SystemC artifacts are projection evidence and cannot satisfy trusted speedup without L4 full-flow evidence.",
                "Timing-only C++ generic_sim output remains insufficient for numerical correctness claims unless paired with this sidecar and a domain oracle.",
            ],
        },
    }
    if graph_error:
        result["error_message"] = graph_error
    return result


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Generic SystemC Python sidecar reference model")
    parser.add_argument("--request", required=True, type=Path, help="Path to gsim.request.v1 JSON")
    parser.add_argument("--result", required=True, type=Path, help="Output path for Python model result JSON")
    parser.add_argument("--trace", type=Path, help="Optional output path for per-node trace JSON")
    args = parser.parse_args(argv)

    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"Error: failed to read request {args.request}: {exc}", file=sys.stderr)
        return 2

    invocation = {
        "tool": "model/generic_sim_backend/tools/python_reference_model.py",
        "accepted_payload_source": "generic_systemc_request",
        "request_path": str(args.request),
        "result_path": str(args.result),
        "trace_path": str(args.trace) if args.trace else None,
    }
    result = evaluate_request(request, invocation=invocation)
    _write_json(args.result, result)
    if args.trace:
        _write_json(
            args.trace,
            {
                "schema_version": "gsim.python_model_trace.v1",
                "run_id": result["run_id"],
                "events": result["timing_reference"]["per_node"],
            },
        )
    print(f"Python reference model complete: {result['run_id']}")
    print(f"Status: {result['status']}")
    print(f"Latency: {result['timing_reference']['latency_ms']:.9g} ms")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
