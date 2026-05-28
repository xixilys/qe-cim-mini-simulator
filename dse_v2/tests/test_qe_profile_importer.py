#!/usr/bin/env python3
"""Tests for the standalone QE profile importer."""

from __future__ import annotations

from pathlib import Path

from dse_v2.profiling.qe_profile import (
    load_qe_profile,
    qe_profile_to_compute_graph,
    qe_profile_to_workload_package,
)


TESTDATA = Path(__file__).parents[1] / "profiling" / "testdata" / "qe_profile_small.json"


def test_load_qe_profile_reads_small_testdata():
    profile = load_qe_profile(TESTDATA)

    assert profile["case_id"] == "qe_profile_small"
    assert profile["problem"]["system"] == "Si2"
    assert len(profile["phases"]) == 3
    assert len(profile["edges"]) == 2


def test_qe_profile_to_compute_graph_preserves_phase_edges_and_metrics():
    profile = load_qe_profile(TESTDATA)
    graph = qe_profile_to_compute_graph(profile)

    assert graph.graph_id == "qe_profile_small_graph"
    assert len(graph.nodes) == len(profile["phases"]) == 3
    assert len(graph.edges) == len(profile["edges"]) == 2
    assert graph.regions == {}
    assert graph.topological_sort() == [
        "charge_density_fft",
        "h_psi_apply",
        "band_residual_reduce",
    ]

    fft = graph.nodes["charge_density_fft"]
    assert fft.op_type == "fft3d"
    assert fft.estimated_flops == 18432
    assert fft.estimated_memory_bytes == 16384

    hpsi = graph.nodes["h_psi_apply"]
    assert hpsi.op_type == "h_psi"
    assert hpsi.estimated_flops == 65536
    assert hpsi.estimated_memory_bytes == 32768

    reduce = graph.nodes["band_residual_reduce"]
    assert reduce.op_type == "reduction"
    assert reduce.estimated_flops == 4096
    assert reduce.estimated_memory_bytes == 8192

    metadata = graph.metadata
    assert metadata["domain"] == "dft_qe"
    assert metadata["workload_family"] == "dft_qe_profiled"
    assert metadata["profile_id"] == "qe_profile_imported"
    assert metadata["case_id"] == "qe_profile_small"
    assert metadata["problem"] == profile["problem"]


def test_qe_profile_to_workload_package_validates():
    profile = load_qe_profile(TESTDATA)
    package = qe_profile_to_workload_package(profile)

    validation = package.validate()

    assert package.workload_id == "qe_profile_small"
    assert package.workload_family == "dft_qe_profiled"
    assert package.profile_id == "qe_profile_imported"
    assert package.importer_id == "qe_profile_json"
    assert package.graph.metadata["domain"] == "dft_qe"
    assert validation["valid"] is True
