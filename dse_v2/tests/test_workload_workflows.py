#!/usr/bin/env python3
"""Step1 multi-workload workflow handoff regressions."""

from __future__ import annotations

import json

from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend
from dse_v2.core.architecture.accelerator import InterconnectTopology, SystemArchitecture, create_cim_array, create_fpga_u280, create_gpu_a100
from dse_v2.reference_workloads.dft_qe import QE_SCF_REQUIRED_COVERAGE, create_qe_reference_package
from dse_v2.core.workload import (
    WorkloadPackage,
    create_dynamic_custom_graph,
    create_graph_analytics_graph,
    create_sparse_spmv_graph,
    create_stencil_streaming_graph,
    create_tensor_chain_graph,
    create_vector_search_graph,
    default_workflow_registry,
    lower_compute_graph,
    package_from_graph,
)
from dse_v2.dse.orchestrator import DesignPoint
from dse_v2.evidence.full_flow import _reference_timing_result, write_full_flow_evidence
from dse_v2.mapping.search import run_mapping_search, select_initial_mapping


REPRESENTATIVE_BUILDERS = {
    "ml_tensor": create_tensor_chain_graph,
    "sparse_la": create_sparse_spmv_graph,
    "stencil_streaming": create_stencil_streaming_graph,
    "graph_analytics": create_graph_analytics_graph,
    "database_vector_search": create_vector_search_graph,
    "dynamic_custom": lambda graph_id: create_dynamic_custom_graph(graph_id, supported=True),
}


def _host_architecture() -> SystemArchitecture:
    return SystemArchitecture(
        system_id="generic_workload_host_arch",
        host_cpu_cores=8,
        host_memory_gb=64.0,
        accelerators=[],
        interconnect=InterconnectTopology("host_bus", 128.0, 1.0),
    )


def _host_design_point(graph, design_point_id: str) -> DesignPoint:
    return DesignPoint(
        design_point_id=design_point_id,
        system_architecture=_host_architecture(),
        task_mapping={node_id: "host" for node_id in graph.nodes},
        scheduling_policy="static_timing_level",
    )


def _heterogeneous_architecture(extra_ops=None) -> SystemArchitecture:
    extra_ops = list(extra_ops or [])
    gpu = create_gpu_a100("gpu-0")
    fpga = create_fpga_u280("fpga-0")
    cim = create_cim_array("cim-0")
    for accel in [gpu, fpga, cim]:
        for op_type in extra_ops:
            if op_type not in accel.compute.supported_ops:
                accel.compute.supported_ops.append(op_type)
            accel.compute.op_efficiency[op_type] = max(accel.compute.op_efficiency.get(op_type, 0.0), 0.5)
    return SystemArchitecture(
        system_id="generic_workload_heterogeneous_arch",
        host_cpu_cores=16,
        host_memory_gb=128.0,
        accelerators=[gpu, fpga, cim],
        interconnect=InterconnectTopology("pcie_mesh", 128.0, 1.0),
    )


def test_workflow_registry_declares_all_required_families():
    registry = default_workflow_registry()

    assert {
        "ml_tensor",
        "sparse_la",
        "stencil_streaming",
        "graph_analytics",
        "database_vector_search",
        "dynamic_custom",
    } <= set(registry)
    for family, workflow in registry.items():
        assert workflow["workload_family"] == family
        assert workflow["accepted_sources"]
        assert workflow["graph_pattern"]
        assert workflow["lowering_policy"]
        assert workflow["default_mapping_policies"]
        assert workflow["domain_validation"]["correctness_claim_requires_profile_evidence"] is True
        assert workflow["final_claim_boundary"] == "full_workload"
        assert workflow["required_coverage"] == []
        assert "qe" not in json.dumps(workflow).lower()


def test_workload_package_round_trip_carries_workflow_metadata_and_required_coverage():
    graph = create_sparse_spmv_graph("sparse_pkg")
    package = package_from_graph(
        graph,
        workload_id="sparse_pkg_workload",
        workload_family="sparse_la",
        importer_id="generic_json",
        required_coverage=["spmv", "norm"],
        domain_metadata={"sparse_format": "csr"},
    )

    validation = package.validate()
    payload = package.to_dict()
    restored = WorkloadPackage.from_dict(payload)

    assert validation["valid"] is True
    assert payload["workflow"]["workload_family"] == "sparse_la"
    assert payload["workflow"]["required_coverage"] == ["spmv", "norm"]
    assert restored.required_coverage()["required_coverage"] == ["spmv", "norm"]
    assert restored.domain_metadata == {"sparse_format": "csr"}


def test_qe_reference_profile_coverage_is_not_global_default():
    qe_package = create_qe_reference_package({"npw": 128, "nkb": 16, "m": 8, "nfft": 1024})
    ml_graph = create_tensor_chain_graph("ml_not_qe")
    ml_package = package_from_graph(ml_graph, workload_family="ml_tensor", importer_id="generic_json")

    assert qe_package.required_coverage()["required_coverage"] == QE_SCF_REQUIRED_COVERAGE
    assert ml_package.required_coverage()["required_coverage"] == ["input", "linear", "activation"]
    assert not set(QE_SCF_REQUIRED_COVERAGE) & set(ml_package.required_coverage()["required_coverage"])


def test_representative_non_qe_workflows_validate_lower_and_build_backend_request_without_qe_fields():
    backend = GenericSystemCBackend()

    for family, build_graph in REPRESENTATIVE_BUILDERS.items():
        graph = build_graph(f"{family}_graph")
        package = package_from_graph(graph, workload_family=family, importer_id="generic_json")
        design_point = _host_design_point(graph, f"{family}_dp")

        validation = package.validate()
        lowering = lower_compute_graph(graph, package)
        request = backend._build_request(design_point, graph, workload_package=package)
        workload = request["workload"]

        assert validation["valid"] is True, family
        assert lowering.report["status"] == "lowered", family
        assert workload["workflow"]["workload_family"] == family
        assert workload["workload_package"]["workload_family"] == family
        assert workload["workload_package"]["importer"]["importer_id"] == "generic_json"
        assert workload["required_coverage"] == lowering.report["required_coverage"]
        assert workload["source_to_executable_nodes"]
        assert workload["required_coverage"]
        assert workload["workflow"].get("unavailable_metric_labels")
        assert "npw" not in json.dumps(workload)
        assert workload["required_coverage"] != QE_SCF_REQUIRED_COVERAGE
        assert not {"h_psi", "s_psi", "diagonalize", "mix_rho", "veff"} & set(workload["required_coverage"])


def test_mapping_search_uses_workload_family_seed_metadata_for_non_qe_graph():
    graph = create_vector_search_graph("vector_search_mapping")
    architecture = _heterogeneous_architecture(["index_scan", "distance_compute", "topk", "predicate_filter"])
    artifacts = run_mapping_search(
        graph,
        architecture,
        selected_mapping={node_id: "host" for node_id in graph.nodes},
        simulation_result={
            "backend": "systemc",
            "status": "passed",
            "metrics": {"latency_ms": 1.0, "power_w": 0.0, "energy_j": 0.0, "total_data_movement_mb": 0.0},
        },
        trusted_sample=True,
    )

    seed_names = {seed["seed_name"] for seed in artifacts["seed_set"]["seeds"]}
    assert artifacts["legality_matrix"]["workload"]["workload_family"] == "database_vector_search"
    assert artifacts["candidate_records"]["workload"]["workload_family"] == "database_vector_search"
    assert "database_vector_search_workflow_balanced" in seed_names
    assert "qe_domain_balanced" not in seed_names
    assert artifacts["selected_record"]["workload"]["workload_family"] == "database_vector_search"


def test_qe_reference_mapping_seed_is_profile_scoped_not_global_default():
    package = create_qe_reference_package({"npw": 128, "nkb": 16, "m": 8, "nfft": 1024})
    qe_graph = package.graph
    architecture = _heterogeneous_architecture(["elementwise", "reduction"])
    selected = select_initial_mapping(qe_graph, architecture)
    artifacts = run_mapping_search(qe_graph, architecture, selected_mapping=selected)

    seed_names = {seed["seed_name"] for seed in artifacts["seed_set"]["seeds"]}
    assert artifacts["seed_set"]["workload"]["workload_family"] == "dft_qe_reference"
    assert "dft_qe_reference_workflow_balanced" in seed_names
    assert "dft_qe_adapter_balanced" not in seed_names
    assert "qe_domain_balanced" not in seed_names


def test_dynamic_custom_without_lowering_semantics_is_unsupported_and_non_final():
    graph = create_dynamic_custom_graph("unsupported_dynamic", supported=False)
    package = package_from_graph(graph, workload_family="dynamic_custom", importer_id="generic_json")

    lowering = lower_compute_graph(graph, package)

    assert package.validate()["valid"] is True
    assert lowering.report["status"] == "unsupported"
    assert lowering.report["full_workload_eligible"] is False
    assert lowering.report["unsupported_constructs"]
    assert lowering.executable_graph is None


def test_non_qe_sparse_workload_hands_off_to_evidence_and_report_with_domain_boundary(tmp_path):
    graph = create_sparse_spmv_graph("sparse_full_flow")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")
    design_point = _host_design_point(graph, "sparse_full_flow_dp")
    backend = GenericSystemCBackend()
    request = backend._build_request(design_point, graph, workload_package=package, output_dir=tmp_path)
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
            "run_id": "sparse_full_flow_dp",
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
    final_report = json.loads((tmp_path / "final_report.json").read_text(encoding="utf-8"))

    assert evidence["trusted_for_final_ranking"] is True
    assert verdict["workload_package"]["workload_family"] == "sparse_la"
    assert "required_qe_scf_phases" not in verdict
    assert verdict["required_coverage"] == ["load_csr", "spmv", "norm"]
    assert verdict["profile_required_coverage"] == ["load_csr", "spmv", "norm"]
    assert simulation_result["missing_required_coverage"] == []
    assert simulation_result["profile_domain_validation"]["status"] == "unavailable_unclaimed"
    assert any(metric["metric"] == "sparse_residual" for metric in simulation_result["unavailable_metrics"])
    assert final_report["workload"]["workflow"]["workload_family"] == "sparse_la"
    assert final_report["workload"]["required_coverage"] == ["load_csr", "spmv", "norm"]
    assert final_report["workload"]["profile_domain_validation"]["status"] == "unavailable_unclaimed"
    assert any("Sparse residual" in limitation for limitation in final_report["limitations"])
