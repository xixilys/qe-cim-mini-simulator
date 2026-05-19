#!/usr/bin/env python3
"""QE full-callgraph inventory artifact tests."""

from __future__ import annotations

from dse_v2.codesign.qe_callgraph_offload_search import (
    build_qe_callgraph_inventory,
)


def test_missing_qe_source_tree_emits_blocker_not_passed_inventory(tmp_path):
    inventory = build_qe_callgraph_inventory(source_root=tmp_path / "missing-qe-src")

    assert inventory["status"] != "passed"
    assert inventory["node_count"] >= 10
    assert inventory["source_root"]["status"] == "blocked_source_unavailable"
    assert inventory["source_root_hash"]
    assert inventory["qe_provenance"]["build_root"]["status"] == "blocked_build_unavailable"
    blocker_ids = {blocker["id"] for blocker in inventory["blockers"]}
    assert {"blocked_source_unavailable", "blocked_build_unavailable"}.issubset(
        blocker_ids
    )


def test_inventory_rows_cover_first_pass_qe_mainflows_and_callsite_fields(tmp_path):
    source_root = tmp_path / "q-e-src"
    source_root.mkdir()
    (source_root / "h_psi.f90").write_text(
        "subroutine h_psi\n  call s_psi\nend subroutine h_psi\n"
        "subroutine s_psi\nend subroutine s_psi\n",
        encoding="utf-8",
    )
    (source_root / "forces.f90").write_text(
        "subroutine force\nend subroutine force\n", encoding="utf-8"
    )

    inventory = build_qe_callgraph_inventory(source_root=source_root)

    assert inventory["status"] == "partial_or_blocked"
    assert (
        "blocked_full_static_qe_callgraph_parser_not_yet_complete"
        in {blocker["id"] for blocker in inventory["blockers"]}
    )
    assert inventory["full_static_qe_callgraph_complete"] is False
    assert inventory["first_pass_static_callgraph_extracted"] is True
    static = inventory["static_callgraph"]
    assert static["status"] == "passed"
    assert static["definition_count"] >= 3
    assert static["edge_count"] >= 1
    assert any(
        edge["caller"] == "h_psi" and edge["callee"] == "s_psi"
        for edge in static["edges_sample"]
    )
    static_blocker = next(
        blocker
        for blocker in inventory["blockers"]
        if blocker["id"] == "blocked_full_static_qe_callgraph_parser_not_yet_complete"
    )
    assert static_blocker["static_definition_count"] >= 3
    assert {"scf", "nscf", "bands", "relax"}.issubset(
        set(inventory["mainflow_classes"])
    )
    kernels = {node["kernel"] for node in inventory["nodes"]}
    assert "h_psi" in kernels
    assert "fft" in kernels
    assert kernels - {"h_psi"}
    for node in inventory["nodes"]:
        assert node["opportunity_id"].startswith("opp_")
        assert node["callsite_id"].startswith("callsite_")
        assert node["stage_type"]
        assert node["phase"] == node["stage_type"]
        assert isinstance(node["programs"], list)
        assert "source_file" in node
        assert node["symbol_or_subroutine"]
        assert isinstance(node["dependency_edges"], list)
        assert node["classification"]
        assert node["claim_boundary"].endswith("not a value claim")
