#!/usr/bin/env python3
"""Architecture-independent workload characterization for Step1 handoff.

This module extracts workload facts, summaries, and hints from the generic
``ComputeGraph`` contract.  It deliberately does not select architecture,
mapping, placement, scheduling, runtime policy, descriptor protocol, or
simulation verdicts; those decisions belong to later workflow stages.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, Mapping, Optional

from dse_v2.core.ir.compute_graph import ComputeGraph, ComputeNode, DataEdge, TensorSpec
from dse_v2.core.workload.lowering import GraphLoweringResult
from dse_v2.core.workload.package import WorkloadPackage


WORKLOAD_CHARACTERIZATION_SCHEMA = "dse.workload_characterization.v1"

NON_DECISION_PROHIBITS = [
    "selected_mapping",
    "selected_placement",
    "selected_schedule",
    "selected_runtime_policy",
    "descriptor_protocol_selection",
]

TRANSFER_TOKENS = {"dma", "transfer", "copy", "load", "store", "memcpy", "send", "recv"}
COLLECTIVE_TOKENS = {"allreduce", "reduce_scatter", "broadcast", "gather", "scatter", "collective"}
STATE_EDGE_KINDS = {"feedback", "state", "control"}
STREAMING_EDGE_KINDS = {"stream", "streaming"}


def _safe_size_bytes(spec: Optional[TensorSpec], limitations: list[str], context: str) -> Optional[float]:
    if spec is None:
        limitations.append(f"{context}: tensor spec unavailable")
        return None
    try:
        return float(spec.size_bytes())
    except Exception as exc:
        limitations.append(f"{context}: tensor byte size unavailable ({exc})")
        return None


def _shape(spec: Optional[TensorSpec]) -> list[int]:
    return [int(dim) for dim in spec.shape] if spec is not None else []


def _edge_id(edge: DataEdge) -> str:
    label = edge.tensor_name or edge.edge_kind or "edge"
    return f"{edge.source_node}->{edge.target_node}:{label}"


def _find_tensor_spec(graph: ComputeGraph, edge: DataEdge) -> Optional[TensorSpec]:
    if edge.tensor_spec is not None:
        return edge.tensor_spec
    source = graph.nodes.get(edge.source_node)
    target = graph.nodes.get(edge.target_node)
    if edge.tensor_name:
        if source and edge.tensor_name in source.output_specs:
            return source.output_specs[edge.tensor_name]
        if target and edge.tensor_name in target.input_specs:
            return target.input_specs[edge.tensor_name]
    return None


def _tensor_records(graph: ComputeGraph, limitations: list[str]) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = {}

    def upsert(
        tensor_name: str,
        *,
        spec: Optional[TensorSpec],
        producer_node: Optional[str] = None,
        consumer_node: Optional[str] = None,
        role: str,
    ) -> None:
        key = tensor_name or f"anonymous:{producer_node or consumer_node}:{role}"
        if key not in records:
            size = _safe_size_bytes(spec, limitations, f"tensor {key}") if spec is not None else None
            records[key] = {
                "tensor_name": key,
                "producer_node": producer_node,
                "consumer_nodes": [],
                "dtype": spec.dtype if spec is not None else "unknown",
                "layout": spec.layout if spec is not None else "unknown",
                "shape": _shape(spec),
                "estimated_bytes": size,
                "sources": [role],
            }
        else:
            if producer_node and not records[key].get("producer_node"):
                records[key]["producer_node"] = producer_node
            if spec is not None and records[key].get("estimated_bytes") is None:
                records[key]["estimated_bytes"] = _safe_size_bytes(spec, limitations, f"tensor {key}")
                records[key]["dtype"] = spec.dtype
                records[key]["layout"] = spec.layout
                records[key]["shape"] = _shape(spec)
            records[key].setdefault("sources", []).append(role)
        if consumer_node and consumer_node not in records[key]["consumer_nodes"]:
            records[key]["consumer_nodes"].append(consumer_node)

    for node in graph.nodes.values():
        for tensor_name, spec in node.output_specs.items():
            upsert(tensor_name, spec=spec, producer_node=node.node_id, role=f"{node.node_id}.output")
        for tensor_name, spec in node.input_specs.items():
            upsert(tensor_name, spec=spec, consumer_node=node.node_id, role=f"{node.node_id}.input")

    for edge in graph.edges:
        upsert(
            edge.tensor_name,
            spec=_find_tensor_spec(graph, edge),
            producer_node=edge.source_node,
            consumer_node=edge.target_node,
            role=f"edge:{_edge_id(edge)}",
        )

    return records


def _op_mix_summary(graph: ComputeGraph) -> Dict[str, Any]:
    by_op: Dict[str, Dict[str, Any]] = {}
    for node in graph.nodes.values():
        entry = by_op.setdefault(
            node.op_type,
            {
                "node_count": 0,
                "estimated_flops": 0.0,
                "estimated_memory_bytes": 0.0,
                "nodes": [],
            },
        )
        entry["node_count"] += 1
        entry["estimated_flops"] += float(node.estimated_flops)
        entry["estimated_memory_bytes"] += float(node.estimated_memory_bytes)
        entry["nodes"].append(node.node_id)

    def node_entry(node: ComputeNode, metric: str) -> Dict[str, Any]:
        return {
            "node_id": node.node_id,
            "op_type": node.op_type,
            metric: float(getattr(node, metric)),
        }

    return {
        "node_count": len(graph.nodes),
        "total_estimated_flops": float(sum(node.estimated_flops for node in graph.nodes.values())),
        "total_estimated_memory_bytes": float(sum(node.estimated_memory_bytes for node in graph.nodes.values())),
        "by_op_type": by_op,
        "top_nodes_by_flops": [
            node_entry(node, "estimated_flops")
            for node in sorted(graph.nodes.values(), key=lambda item: item.estimated_flops, reverse=True)[:10]
            if node.estimated_flops > 0
        ],
        "top_nodes_by_memory": [
            node_entry(node, "estimated_memory_bytes")
            for node in sorted(graph.nodes.values(), key=lambda item: item.estimated_memory_bytes, reverse=True)[:10]
            if node.estimated_memory_bytes > 0
        ],
    }


def _tensor_summary(records: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    dtype_histogram = Counter(str(record.get("dtype", "unknown")) for record in records.values())
    layout_histogram = Counter(str(record.get("layout", "unknown")) for record in records.values())
    known = [record for record in records.values() if record.get("estimated_bytes") is not None]
    return {
        "dtype_histogram": dict(sorted(dtype_histogram.items())),
        "layout_histogram": dict(sorted(layout_histogram.items())),
        "total_tensor_bytes": float(sum(float(record.get("estimated_bytes") or 0.0) for record in known)),
        "largest_tensors": [
            {
                "tensor_name": str(record.get("tensor_name", "")),
                "producer_node": record.get("producer_node"),
                "consumer_nodes": list(record.get("consumer_nodes", []) or []),
                "shape": list(record.get("shape", []) or []),
                "dtype": record.get("dtype", "unknown"),
                "layout": record.get("layout", "unknown"),
                "estimated_bytes": float(record.get("estimated_bytes") or 0.0),
            }
            for record in sorted(known, key=lambda item: float(item.get("estimated_bytes") or 0.0), reverse=True)[:10]
        ],
    }


def _edge_traffic_summary(graph: ComputeGraph, limitations: list[str]) -> Dict[str, Any]:
    edge_records: list[Dict[str, Any]] = []
    for edge in graph.edges:
        estimated_bytes = _safe_size_bytes(_find_tensor_spec(graph, edge), limitations, f"edge {_edge_id(edge)}")
        edge_records.append({
            "edge_id": _edge_id(edge),
            "source_node": edge.source_node,
            "target_node": edge.target_node,
            "tensor_name": edge.tensor_name,
            "edge_kind": edge.edge_kind,
            "estimated_bytes": estimated_bytes,
        })
    known = [record for record in edge_records if record.get("estimated_bytes") is not None]
    return {
        "edge_count": len(graph.edges),
        "total_edge_tensor_bytes": float(sum(float(record.get("estimated_bytes") or 0.0) for record in known)),
        "top_edges_by_bytes": sorted(
            known,
            key=lambda item: float(item.get("estimated_bytes") or 0.0),
            reverse=True,
        )[:10],
    }


def _region_summary(graph: ComputeGraph, lowering: Optional[GraphLoweringResult]) -> Dict[str, Any]:
    by_region = Counter(region.region_type for region in graph.regions.values())
    bounded = []
    unsupported = []
    lowering_regions = {
        str(item.get("region_id")): item
        for item in (lowering.report.get("regions", []) if lowering is not None else [])
        if isinstance(item, Mapping)
    }
    for region in graph.regions.values():
        lowered = lowering_regions.get(region.region_id, {})
        entry = {
            "region_id": region.region_id,
            "region_type": region.region_type,
            "nodes": list(region.node_ids),
            "semantics": dict(region.semantics),
        }
        if region.has_lowering_semantics() and lowered.get("status", "lowerable") != "unsupported":
            bounded.append({**entry, "reason": "region declares bounded or summarizable semantics"})
        else:
            unsupported.append({**entry, "reason": lowered.get("reason", "region lacks bounded or summary semantics")})
    return {
        "region_count": len(graph.regions),
        "by_region_type": dict(sorted(by_region.items())),
        "bounded_region_hints": bounded,
        "unsupported_region_hints": unsupported,
    }


def _producer_consumer_maps(graph: ComputeGraph) -> tuple[Dict[str, list[DataEdge]], Dict[str, list[DataEdge]]]:
    by_source: Dict[str, list[DataEdge]] = defaultdict(list)
    by_tensor: Dict[str, list[DataEdge]] = defaultdict(list)
    for edge in graph.edges:
        by_source[edge.source_node].append(edge)
        by_tensor[edge.tensor_name].append(edge)
    return by_source, by_tensor


def _reuse_potential_summary(graph: ComputeGraph, edge_summary: Mapping[str, Any]) -> Dict[str, Any]:
    _, by_tensor = _producer_consumer_maps(graph)
    single = []
    multi = []
    high = []
    for tensor_name, edges in sorted(by_tensor.items()):
        if not tensor_name:
            continue
        record = {
            "tensor_name": tensor_name,
            "producer_node": edges[0].source_node if edges else None,
            "consumer_nodes": sorted({edge.target_node for edge in edges}),
            "consumer_count": len({edge.target_node for edge in edges}),
        }
        if record["consumer_count"] <= 1:
            single.append(record)
        else:
            multi.append(record)
        if record["consumer_count"] >= 3:
            high.append(record)

    bytes_by_edge = {
        str(record.get("edge_id")): float(record.get("estimated_bytes") or 0.0)
        for record in edge_summary.get("top_edges_by_bytes", []) or []
    }
    chains = []
    for edge in graph.edges:
        if edge.edge_kind != "data" or edge.declares_cycle_semantics():
            continue
        if len(by_tensor.get(edge.tensor_name, [])) == 1:
            chains.append({
                "nodes": [edge.source_node, edge.target_node],
                "tensor_name": edge.tensor_name,
                "estimated_bytes": bytes_by_edge.get(_edge_id(edge), 0.0),
                "reason": "producer output has a single data consumer",
            })
    return {
        "single_consumer_tensors": single[:20],
        "multi_consumer_tensors": multi[:20],
        "high_fanout_tensors": high[:20],
        "producer_consumer_chains": chains[:20],
    }


def _fusion_candidate_hints(graph: ComputeGraph) -> list[Dict[str, Any]]:
    _, by_tensor = _producer_consumer_maps(graph)
    hints: list[Dict[str, Any]] = []
    for edge in graph.edges:
        if edge.edge_kind != "data" or edge.declares_cycle_semantics():
            continue
        if len(by_tensor.get(edge.tensor_name, [])) != 1:
            continue
        producer = graph.nodes.get(edge.source_node)
        consumer = graph.nodes.get(edge.target_node)
        if producer is None or consumer is None:
            continue
        confidence = "medium" if producer.op_type not in {"placeholder", "input"} and consumer.op_type not in {"placeholder", "input"} else "low"
        hints.append({
            "nodes": [edge.source_node, edge.target_node],
            "reason": "single-consumer data dependency with no declared state, feedback, or control edge",
            "confidence": confidence,
        })
    return hints[:20]


def _tensor_bytes_for_names(
    records: Mapping[str, Mapping[str, Any]],
    tensor_names: Iterable[str],
) -> float:
    total = 0.0
    for tensor_name in tensor_names:
        record = records.get(tensor_name)
        if record and record.get("estimated_bytes") is not None:
            total += float(record.get("estimated_bytes") or 0.0)
    return total


def _region_boundary_hints(
    graph: ComputeGraph,
    records: Mapping[str, Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    hints: list[Dict[str, Any]] = []
    for region in graph.regions.values():
        node_set = set(region.node_ids)
        input_tensors = sorted({
            edge.tensor_name
            for edge in graph.edges
            if edge.target_node in node_set and edge.source_node not in node_set and edge.tensor_name
        })
        output_tensors = sorted({
            edge.tensor_name
            for edge in graph.edges
            if edge.source_node in node_set and edge.target_node not in node_set and edge.tensor_name
        })
        hints.append({
            "boundary_id": f"region:{region.region_id}",
            "source_kind": "region",
            "nodes": list(region.node_ids),
            "input_tensors": input_tensors,
            "output_tensors": output_tensors,
            "estimated_input_bytes": _tensor_bytes_for_names(records, input_tensors),
            "estimated_output_bytes": _tensor_bytes_for_names(records, output_tensors),
            "reason": "region defines an architecture-independent workload boundary candidate; no deployment choice is made",
        })
    return hints


def _chain_boundary_hints(
    graph: ComputeGraph,
    records: Mapping[str, Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    _, by_tensor = _producer_consumer_maps(graph)
    hints: list[Dict[str, Any]] = []
    for edge in graph.edges:
        if edge.edge_kind != "data" or edge.declares_cycle_semantics():
            continue
        if len(by_tensor.get(edge.tensor_name, [])) != 1:
            continue
        source = graph.nodes.get(edge.source_node)
        target = graph.nodes.get(edge.target_node)
        if source is None or target is None:
            continue
        input_tensors = sorted(set(source.inputs + target.inputs) - {edge.tensor_name})
        output_tensors = sorted(set(target.outputs or [edge.tensor_name]))
        hints.append({
            "boundary_id": f"chain:{edge.source_node}->{edge.target_node}",
            "source_kind": "chain",
            "nodes": [edge.source_node, edge.target_node],
            "input_tensors": input_tensors,
            "output_tensors": output_tensors,
            "estimated_input_bytes": _tensor_bytes_for_names(records, input_tensors),
            "estimated_output_bytes": _tensor_bytes_for_names(records, output_tensors),
            "reason": "producer-consumer chain exposes a possible workload boundary; no offload plan or descriptor granularity is selected",
        })
    return hints[:10]


def _offload_boundary_hints(
    graph: ComputeGraph,
    records: Mapping[str, Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    hints = _region_boundary_hints(graph, records)
    hints.extend(_chain_boundary_hints(graph, records))
    return hints[:20]


def _communication_pattern_summary(graph: ComputeGraph) -> Dict[str, Any]:
    transfer_like_nodes = []
    collective_like_nodes = []
    for node in graph.nodes.values():
        tokens = {node.node_id.lower(), node.op_type.lower()}
        if any(any(token in value for token in TRANSFER_TOKENS) for value in tokens):
            transfer_like_nodes.append({"node_id": node.node_id, "op_type": node.op_type})
        if any(any(token in value for token in COLLECTIVE_TOKENS) for value in tokens):
            collective_like_nodes.append({"node_id": node.node_id, "op_type": node.op_type})
    return {
        "transfer_like_nodes": transfer_like_nodes,
        "collective_like_nodes": collective_like_nodes,
        "streaming_edges": [
            {
                "edge_id": _edge_id(edge),
                "source_node": edge.source_node,
                "target_node": edge.target_node,
                "edge_kind": edge.edge_kind,
            }
            for edge in graph.edges
            if edge.edge_kind in STREAMING_EDGE_KINDS or edge.attributes.get("streaming")
        ],
        "state_or_feedback_edges": [
            {
                "edge_id": _edge_id(edge),
                "source_node": edge.source_node,
                "target_node": edge.target_node,
                "edge_kind": edge.edge_kind,
            }
            for edge in graph.edges
            if edge.edge_kind in STATE_EDGE_KINDS or edge.attributes.get("state_update") or edge.attributes.get("feedback")
        ],
    }


def characterize_workload(
    package: WorkloadPackage,
    *,
    lowering: Optional[GraphLoweringResult] = None,
) -> Dict[str, Any]:
    """Return Step1 architecture-independent workload facts and hints."""
    graph = package.graph
    limitations = [
        "architecture-independent analysis only; no hardware resource, memory level, mapping, placement, schedule, runtime policy, descriptor protocol, or simulator verdict is selected"
    ]
    lowering_status = "unknown"
    executable_graph_id = None
    full_workload_eligible = False
    if lowering is not None:
        lowering_status = str(lowering.report.get("status", "unknown"))
        executable_graph_id = lowering.report.get("executable_graph_id")
        full_workload_eligible = bool(lowering.report.get("full_workload_eligible", False)) and package.is_full_workload()

    records = _tensor_records(graph, limitations)
    edge_summary = _edge_traffic_summary(graph, limitations)

    result = {
        "schema_version": WORKLOAD_CHARACTERIZATION_SCHEMA,
        "workload_id": package.workload_id,
        "workload_family": package.workload_family,
        "profile_id": package.profile_id,
        "importer_id": package.importer_id,
        "source_graph_id": graph.graph_id,
        "executable_graph_id": executable_graph_id,
        "lowering_status": lowering_status,
        "full_workload_eligible": bool(full_workload_eligible),
        "claim_boundary": package.claim_boundary,
        "analysis_scope": "architecture_independent",
        "non_decision_contract": {
            "prohibits": list(NON_DECISION_PROHIBITS),
        },
        "op_mix_summary": _op_mix_summary(graph),
        "tensor_summary": _tensor_summary(records),
        "edge_traffic_summary": edge_summary,
        "region_summary": _region_summary(graph, lowering),
        "reuse_potential_summary": _reuse_potential_summary(graph, edge_summary),
        "fusion_candidate_hints": _fusion_candidate_hints(graph),
        "offload_boundary_hints": _offload_boundary_hints(graph, records),
        "communication_pattern_summary": _communication_pattern_summary(graph),
        "limitations": sorted(set(limitations)),
    }
    domain_characterization = package.domain_metadata.get("characterization")
    if isinstance(domain_characterization, Mapping):
        domain_phase_summary = domain_characterization.get("domain_phase_summary")
        if isinstance(domain_phase_summary, Mapping):
            result["domain_phase_summary"] = dict(domain_phase_summary)
    return result
