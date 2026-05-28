#!/usr/bin/env python3
"""Raw-reference producer tests for DFT deployment target input JSONs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.codesign.evidence_ledger import sha256_file
from dse_v2.reference_workloads.dft_target_input_json_producer import (
    build_dft_target_input_jsons_from_raw_refs,
    write_dft_target_input_jsons_from_raw_refs,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _raw_ref(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "exists": True,
        "sha256": sha256_file(path),
        "hash_algorithm": "sha256",
        "status": "present_hash_valid",
        "source_role": "raw_target_input_reference",
    }


def _seed_raw_sources(raw_dir: Path) -> tuple[Path, Path]:
    fpga_raw = _write_json(
        raw_dir / "vendor_fpga_capacity_catalog_raw.json",
        {
            "schema_version": "vendor.fpga_capacity_catalog.raw.v1",
            "source_kind": "fpga_capacity_catalog_raw",
            "targets": [
                {
                    "target_device_id": "xcvu19p-current-catalog",
                    "vendor": "xilinx",
                    "part": "xcvu19p-fsva3824-2L-e",
                    "family": "virtex-ultrascale-plus",
                    "status": "available",
                    "capacity": {
                        "slice_luts": 2_586_000,
                        "dsps": 6_840,
                        "block_ram_tiles": 2_160,
                    },
                }
            ],
        },
    )
    asic_raw = _write_json(
        raw_dir / "dc_target_library_probe_raw.json",
        {
            "schema_version": "dc.target_library_probe.raw.v1",
            "source_kind": "asic_target_library_probe_raw",
            "target_libraries": [
                {
                    "target_library_id": "fsa0a_c_generic_core_tt1p8v25c",
                    "process_node": "library_defined",
                    "pvt_corner": "tt_1p8v_25c",
                    "voltage_v": 1.8,
                    "temperature_c": 25,
                    "discovery_status": "real_target_library_present",
                }
            ],
        },
    )
    return fpga_raw, asic_raw


def test_raw_ref_producer_emits_target_jsons_with_source_hash_refs(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    out_dir = tmp_path / "run"
    fpga_raw, asic_raw = _seed_raw_sources(raw_dir)

    result = write_dft_target_input_jsons_from_raw_refs(
        out_dir,
        fpga_raw_ref=_raw_ref(fpga_raw),
        asic_raw_ref=_raw_ref(asic_raw),
    )

    assert result["status"] == "passed"
    assert result["blocked"] is False
    fpga_catalog = json.loads((out_dir / "fpga_target_catalog.json").read_text(encoding="utf-8"))
    asic_probe = json.loads((out_dir / "asic_target_library_probe.json").read_text(encoding="utf-8"))
    assert fpga_catalog["schema_version"] == "dse.dft.fpga_target_catalog.v1"
    assert asic_probe["schema_version"] == "dse.dft.asic_target_library_probe.v1"
    assert fpga_catalog["targets"][0]["source_refs"] == [_raw_ref(fpga_raw)]
    assert asic_probe["target_libraries"][0]["source_refs"] == [_raw_ref(asic_raw)]
    assert fpga_catalog["targets"][0]["capacity"]["slice_luts"] == 2_586_000
    assert asic_probe["target_libraries"][0]["target_library_id"] == "fsa0a_c_generic_core_tt1p8v25c"
    assert fpga_catalog["target_catalog_from_vivado_part_support_probe"] is False
    assert fpga_catalog["deliverable_complete"] is False
    assert asic_probe["deliverable_complete"] is False


def test_raw_ref_producer_blocks_missing_or_stale_hash_refs(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    fpga_raw, asic_raw = _seed_raw_sources(raw_dir)

    result = build_dft_target_input_jsons_from_raw_refs(
        tmp_path / "run",
        fpga_raw_ref={"path": str(fpga_raw), "hash_algorithm": "sha256"},
        asic_raw_ref={**_raw_ref(asic_raw), "sha256": "0" * 64},
    )

    assert result["status"] == "blocked"
    assert result["blocked"] is True
    blocker_ids = {blocker["blocker_id"] for blocker in result["blockers"]}
    assert "fpga_raw_ref_missing_sha256" in blocker_ids
    assert "asic_raw_ref_hash_mismatch" in blocker_ids
    assert result["outputs"] == {}


def test_raw_ref_producer_rejects_target_json_self_refs_and_vivado_part_probe_shortcut(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "run"
    target_json_as_raw = _write_json(
        out_dir / "fpga_target_catalog.json",
        {
            "schema_version": "dse.dft.fpga_target_catalog.v1",
            "targets": [],
        },
    )
    vivado_part_probe = _write_json(
        tmp_path / "raw" / "vivado_part_support_probe.json",
        {
            "schema_version": "dse.dft.vivado_part_support_probe.v1",
            "supported_parts": ["xc7a35tcsg324-1"],
            "requested_part_results": [{"requested_part": "xc7a35tcsg324-1", "match_count": 1}],
        },
    )
    asic_raw = _write_json(
        tmp_path / "raw" / "asic_self_referential.json",
        {
            "schema_version": "dc.target_library_probe.raw.v1",
            "target_libraries": [
                {
                    "target_library_id": "fsa0a_c_generic_core_tt1p8v25c",
                    "process_node": "library_defined",
                    "pvt_corner": "tt_1p8v_25c",
                }
            ],
        },
    )
    asic_payload = json.loads(asic_raw.read_text(encoding="utf-8"))
    asic_payload["source_refs"] = [_raw_ref(asic_raw)]
    _write_json(asic_raw, asic_payload)

    result = build_dft_target_input_jsons_from_raw_refs(
        out_dir,
        fpga_raw_ref=_raw_ref(vivado_part_probe),
        asic_raw_ref=_raw_ref(asic_raw),
    )
    target_self_result = build_dft_target_input_jsons_from_raw_refs(
        out_dir,
        fpga_raw_ref=_raw_ref(target_json_as_raw),
        asic_raw_ref=_raw_ref(asic_raw),
    )

    blocker_ids = {blocker["blocker_id"] for blocker in result["blockers"]}
    target_self_blocker_ids = {blocker["blocker_id"] for blocker in target_self_result["blockers"]}
    assert "fpga_raw_ref_vivado_part_support_probe_not_capacity_catalog" in blocker_ids
    assert "asic_raw_payload_self_referential_source_ref" in blocker_ids
    assert "fpga_raw_ref_points_to_target_json" in target_self_blocker_ids
    assert result["blocked"] is True
    assert target_self_result["blocked"] is True


def test_raw_ref_producer_cli_writes_blocked_result_without_target_jsons(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    out_dir = tmp_path / "run"
    fpga_raw, asic_raw = _seed_raw_sources(raw_dir)
    fpga_ref = _write_json(raw_dir / "fpga_ref.json", _raw_ref(fpga_raw))
    asic_ref = _write_json(raw_dir / "asic_ref.json", {**_raw_ref(asic_raw), "sha256": "bad"})

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_target_input_jsons_from_raw_refs.py",
            "--out",
            str(out_dir),
            "--fpga-raw-ref",
            str(fpga_ref),
            "--asic-raw-ref",
            str(asic_ref),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 2
    status = json.loads((out_dir / "dft_target_input_json_producer_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "blocked"
    assert status["deliverable_complete"] is False
    assert {blocker["blocker_id"] for blocker in status["blockers"]} == {"asic_raw_ref_hash_mismatch"}
    assert not (out_dir / "fpga_target_catalog.json").exists()
    assert not (out_dir / "asic_target_library_probe.json").exists()
