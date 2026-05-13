#!/usr/bin/env python3
"""Graph lowering from source ComputeGraph to executable views."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from dse_v2.core.ir.compute_graph import ComputeGraph, DataEdge, GraphRegion
from dse_v2.core.workload.package import WorkloadPackage
from dse_v2.core.workload.workflows import required_coverage_from_workflow, resolve_workflow_metadata


@dataclass
class GraphLoweringResult:
    report: Dict[str, Any]
    executable_graph: Optional[ComputeGraph]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report": self.report,
            "executable_graph": self.executable_graph.to_dict() if self.executable_graph else None,
        }


def _edge_id(edge: DataEdge) -> str:
    label = edge.tensor_name or edge.edge_kind
    return f"{edge.source_node}->{edge.target_node}:{label}"


def _region_lowering(region: GraphRegion) -> Dict[str, Any]:
    if region.has_lowering_semantics():
        strategy = "preserve_region"
        if region.region_type in {"loop", "feedback"}:
            strategy = "summarize_bounded_iteration"
        elif region.region_type in {"stream", "streaming"}:
            strategy = "summarize_streaming_recurrence"
        elif region.region_type in {"dynamic_control", "branch", "conditional"}:
            strategy = "summarize_branch_distribution"
        return {
            "region_id": region.region_id,
            "region_type": region.region_type,
            "strategy": strategy,
            "status": "lowerable",
            "semantics": dict(region.semantics),
            "source_nodes": list(region.node_ids),
        }
    return {
        "region_id": region.region_id,
        "region_type": region.region_type,
        "strategy": "unsupported",
        "status": "unsupported",
        "reason": "region lacks bounds, summary model, convergence criteria, or trace distribution needed for executable lowering",
        "source_nodes": list(region.node_ids),
    }


def lower_compute_graph(
    graph: ComputeGraph,
    package: Optional[WorkloadPackage] = None,
    *,
    lowered_graph_id: Optional[str] = None,
) -> GraphLoweringResult:
    """Lower a source graph to an executable DAG-like view when possible."""
    validation = graph.validate()
    claim_boundary = package.claim_boundary if package is not None else str(graph.metadata.get("claim_boundary", "full_workload"))
    workflow = package.resolved_workflow() if package is not None else resolve_workflow_metadata(str(graph.metadata.get("workload_family", "dynamic_custom")))
    errors: List[str] = [str(issue.get("message")) for issue in validation.get("errors", [])]
    warnings: List[str] = [str(issue.get("message")) for issue in validation.get("warnings", [])]
    regions = [_region_lowering(region) for region in graph.regions.values()]
    unsupported = [region for region in regions if region.get("status") == "unsupported"]
    summarized_edges = [edge for edge in graph.edges if edge.declares_cycle_semantics()]

    executable_graph: Optional[ComputeGraph] = None
    lowering_errors = list(errors)
    order: List[str] = []
    if not lowering_errors and not unsupported:
        try:
            executable_graph = graph.clone_executable_view(lowered_graph_id or f"{graph.graph_id}.lowered")
            order = executable_graph.topological_sort()
        except Exception as exc:  # intentionally local; report as structured unsupported graph
            lowering_errors.append(str(exc))
            executable_graph = None

    status = "lowered" if executable_graph is not None else "unsupported"
    if executable_graph is not None and not graph.has_declared_non_dag_semantics():
        strategy = "identity_dag"
    elif executable_graph is not None:
        strategy = "executable_view_with_declared_cycles_summarized"
    else:
        strategy = "unsupported"

    full_workload_eligible = (
        status == "lowered"
        and claim_boundary in {"full_workload", "full", "end_to_end"}
        and not unsupported
    )
    required_coverage = required_coverage_from_workflow(
        str(workflow.get("workload_family", graph.metadata.get("workload_family", "dynamic_custom"))),
        workflow,
        graph.nodes.keys(),
        order,
    )
    report = {
        "schema_version": "dse.graph_lowering_report.v1",
        "source_graph_id": graph.graph_id,
        "executable_graph_id": executable_graph.graph_id if executable_graph else None,
        "status": status,
        "strategy": strategy,
        "claim_boundary": claim_boundary,
        "full_workload_eligible": full_workload_eligible,
        "workflow": workflow,
        "required_coverage": required_coverage,
        "source_validation": validation,
        "topological_order": order,
        "source_to_executable_nodes": {node_id: [node_id] for node_id in graph.nodes},
        "removed_or_summarized_edges": [
            {
                "edge_id": _edge_id(edge),
                "source_node": edge.source_node,
                "target_node": edge.target_node,
                "edge_kind": edge.edge_kind,
                "cycle_semantics": edge.cycle_semantics or edge.attributes,
                "reason": "declared cycle/feedback/streaming edge summarized for executable ordering",
            }
            for edge in summarized_edges
        ],
        "regions": regions,
        "unsupported_constructs": unsupported,
        "approximations": [
            "declared cycle edges are summarized rather than emitted as executable ordering edges"
        ] if summarized_edges else [],
        "errors": lowering_errors,
        "warnings": warnings,
    }
    return GraphLoweringResult(report=report, executable_graph=executable_graph)


def write_graph_lowering_artifacts(
    run_dir: Path,
    result: GraphLoweringResult,
    *,
    report_name: str = "graph_lowering_report.json",
    executable_graph_name: str = "executable_graph.json",
) -> Dict[str, str]:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / report_name
    report_path.write_text(json.dumps(result.report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths = {"graph_lowering_report": report_name}
    if result.executable_graph is not None:
        (run_dir / executable_graph_name).write_text(
            json.dumps(result.executable_graph.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paths["executable_graph"] = executable_graph_name
    return paths
