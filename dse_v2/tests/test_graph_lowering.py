#!/usr/bin/env python3
"""Graph lowering artifact and final-claim boundary regressions."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend
from dse_v2.core.architecture.accelerator import InterconnectTopology, create_gpu_a100
from dse_v2.core.ir.compute_graph import ComputeGraph, ComputeNode, DataEdge, TensorSpec
from dse_v2.core.workload import create_tensor_chain_graph, lower_compute_graph, package_from_graph, write_graph_lowering_artifacts
from dse_v2.dse.orchestrator import DesignPoint, SystemArchitecture
from dse_v2.evidence.full_flow import _reference_timing_result, write_full_flow_evidence
from dse_v2.reporting.final_report import validate_report_claims


def test_graph_lowering_report_is_written_with_executable_graph(tmp_path):
    graph = create_tensor_chain_graph("lower_me")
    package = package_from_graph(graph, workload_family="ml_tensor", importer_id="generic_json")
    result = lower_compute_graph(graph, package)
    paths = write_graph_lowering_artifacts(tmp_path, result)

    report = json.loads((tmp_path / paths["graph_lowering_report"]).read_text(encoding="utf-8"))
    executable = json.loads((tmp_path / paths["executable_graph"]).read_text(encoding="utf-8"))

    assert report["status"] == "lowered"
    assert report["source_graph_id"] == "lower_me"
    assert report["full_workload_eligible"] is True
    assert executable["metadata"]["source_graph_id"] == "lower_me"


def test_reduced_package_cannot_validate_as_trusted_final_claim(tmp_path):
    report = {
        "workload": {
            "workload_id": "reduced",
            "claim_boundary": "diagnostic-only",
            "graph_lowering": {"status": "lowered", "full_workload_eligible": False},
        },
        "claims": [
            {
                "claim_id": "bad:diagnostic",
                "claim_type": "feasibility",
                "trusted": True,
                "predicted_only": False,
                "blocked": False,
                "backend": "systemc",
                "source_fidelity": "L3",
                "evidence_ids": ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json"],
            }
        ],
        "selected_recommendation": {"status": "not_selected"},
    }
    for rel in ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json"]:
        (tmp_path / rel).write_text("{}\n", encoding="utf-8")

    validation = validate_report_claims(report, tmp_path)

    assert validation["passed"] is False
    assert any("reduced/diagnostic" in error for error in validation["errors"])
    assert any("full-workload eligible" in error for error in validation["errors"])


def test_lowering_keeps_source_to_executable_mapping_for_feedback_edge():
    graph = ComputeGraph("streaming_graph")
    graph.add_node(ComputeNode("load", "dma_load", outputs=["tile"]))
    graph.add_node(ComputeNode("compute", "stencil", inputs=["tile"], outputs=["tile_next"]))
    graph.add_edge(DataEdge("load", "compute", "tile", TensorSpec((16, 16), dtype="FP32")))
    graph.add_edge(DataEdge("compute", "load", edge_kind="stream", attributes={"streaming": True, "bounded": True}, cycle_semantics={"kind": "streaming_recurrence", "iterations": 8}))
    package = package_from_graph(graph, workload_family="stencil", importer_id="generic_json")

    result = lower_compute_graph(graph, package)

    assert result.report["status"] == "lowered"
    assert result.report["source_to_executable_nodes"] == {"load": ["load"], "compute": ["compute"]}
    assert result.report["removed_or_summarized_edges"][0]["edge_kind"] == "stream"


def test_non_qe_full_flow_coverage_uses_executable_graph_nodes(tmp_path):
    graph = create_tensor_chain_graph("ml_tensor_full_flow")
    package = package_from_graph(graph, workload_family="ml_tensor", importer_id="generic_json")
    gpu = create_gpu_a100("gpu-0")
    for op_type in ["placeholder", "relu"]:
        if op_type not in gpu.compute.supported_ops:
            gpu.compute.supported_ops.append(op_type)
        gpu.compute.op_efficiency[op_type] = 0.8
    architecture = SystemArchitecture(
        system_id="non_qe_test_arch",
        host_cpu_cores=16,
        host_memory_gb=128.0,
        accelerators=[gpu],
        interconnect=InterconnectTopology("pcie_test", 128.0, 1.0),
    )
    design_point = DesignPoint(
        design_point_id="non_qe_full_flow",
        system_architecture=architecture,
        task_mapping={node_id: "gpu-0" for node_id in graph.nodes},
        scheduling_policy="static_timing_level",
    )
    backend = GenericSystemCBackend()
    request = backend._build_request(design_point, graph, output_dir=tmp_path)
    reference, errors = _reference_timing_result(request)
    assert errors == []

    evidence = write_full_flow_evidence(
        run_dir=tmp_path,
        backend="systemc",
        evidence_mode="summary",
        design_point=design_point,
        compute_graph=graph,
        simulation_request=request,
        simulation_result={
            "schema_version": "gsim.result.v1",
            "run_id": "non_qe_full_flow",
            "status": "passed",
            "metrics": reference["metrics"],
            "events": reference["events"],
        },
        simulator_cmd=["generic_sim"],
        simulator_returncode=0,
        systemc_stdout="",
        systemc_stderr="",
        cli_command=["probe"],
        workload_package=package,
    )

    verdict = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
    simulation_result = json.loads((tmp_path / "simulation_result.json").read_text(encoding="utf-8"))

    assert evidence["trusted_for_final_ranking"] is True
    assert verdict["phase_coverage_passed"] is True
    assert verdict["required_coverage"] == ["input", "linear", "activation"]
    assert "required_qe_scf_phases" not in verdict
    assert simulation_result["required_coverage"] == ["input", "linear", "activation"]
    assert simulation_result["missing_required_coverage"] == []
