from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("build_qe_final_best_architecture_decision_v0.py")
SPEC = importlib.util.spec_from_file_location("build_qe_final_best_architecture_decision_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def stage_c_payload(candidate_id: str, *, claim: bool = True) -> dict[str, Any]:
    return {
        "schema_version": "qe_dse_qe_equivalent_correctness_report_v0",
        "execution_status": "executed",
        "claim_ceiling": "qe_equivalent_scf_correctness_only" if claim else "correctness_report_reference_only",
        "report_id": f"stage_c::{candidate_id}",
        "candidate_id": candidate_id,
        "workload_id": "si4_pbe_uspp_small",
        "case_id": "si4_pbe_uspp_small",
        "family": "F3" if candidate_id.endswith("F3") else "F2",
        "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
        "correctness_status": "pass" if claim else "mismatch",
        "qe_equivalent_scf_claim": claim,
        "compare_report": {
            "schema_name": "qe_gold_numerical_tolerance_schema_v0",
            "schema_version": "2026-04-13",
            "overall_pass": claim,
            "summary": {"status": "pass" if claim else "mismatch", "failed_required_fields": [] if claim else ["final_total_energy_ry"]},
        },
        "evidence_refs": {},
    }


def stage_d_payload(candidate_id: str, stage_c_ref: Path, *, kind: str = "hls_synthesis") -> dict[str, Any]:
    if kind == "hls_synthesis":
        return {
            "schema_version": "qe_dse_fpga_asic_implementation_evidence_v0",
            "execution_status": "external_evidence_referenced",
            "evidence_id": f"stage_d::{candidate_id}",
            "candidate_id": candidate_id,
            "implementation_target_class": "fpga",
            "evidence_kind": "hls_synthesis",
            "evidence_status": "available",
            "claim_ceiling": "hls_synthesis_only",
            "artifact_refs": {"hls_report": "reports/hls_synthesis.rpt"},
            "metrics": {"estimated_lut": 1234, "estimated_bram": 12, "fmax_mhz": 250.0},
            "correctness_dependency": {"qe_equivalent_scf_claim": True, "qe_correctness_report_ref": str(stage_c_ref)},
            "final_public_family_winner": None,
            "public_winner_claim": False,
            "production_release_ready": False,
        }
    return {
        "schema_version": "qe_dse_fpga_asic_implementation_evidence_v0",
        "execution_status": "external_evidence_referenced",
        "evidence_id": f"stage_d::{candidate_id}",
        "candidate_id": candidate_id,
        "implementation_target_class": "fpga",
        "evidence_kind": "implementation_projection",
        "evidence_status": "partial",
        "claim_ceiling": "implementation_evidence_only",
        "artifact_refs": {"projection_note": "projection.json"},
        "metrics": {"projected_latency_cycles": 42},
        "correctness_dependency": {"qe_equivalent_scf_claim": True, "qe_correctness_report_ref": str(stage_c_ref)},
        "final_public_family_winner": None,
        "public_winner_claim": False,
        "production_release_ready": False,
    }


def b4_payload(candidate_id: str, ticks: int, *, strict: bool = True) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "execution_status": "executed",
        "backend_class": "gem5_systemc_timed_proxy",
        "claim_ceiling": "gem5_systemc_timed_proxy_only",
        "metrics": {
            "cycle_proxy": ticks,
            "cycle_source": "gem5_event_timed_device_observed" if strict else "timing_sidecar_projection",
            "event_timed_device_activity_observed": strict,
            "candidate_device_event_delta_ticks": ticks if strict else None,
            "host_control_mmio_read_count": 3 if strict else 0,
            "host_control_mmio_write_count": 1 if strict else 0,
            "successful_dma_transfer_bytes": 4096,
        },
    }


def systemc_cycle_payload(candidate_id: str, total_cycles: int = 1000) -> dict[str, Any]:
    return {
        "schema_version": "qe_systemc_cycle_accounted_evidence_v0",
        "candidate_id": candidate_id,
        "workload_id": "si4_pbe_uspp_small",
        "evidence_tier": "systemc-cycle-accounted",
        "cycle_accounting": {
            "total_cycles": total_cycles,
            "components": {"control": 10, "dma": 20, "compute": total_cycles - 30},
        },
        "non_claims": [
            "systemc_cycle_accounted_is_not_rtl_cycle_accurate_timing",
            "not_board_or_asic_measured",
        ],
    }


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_fixture(
    root: Path,
    *,
    include_stage_c: bool = True,
    stage_d_kind: str = "hls_synthesis",
    strict_b4: bool = True,
    include_systemc_cycle: bool = True,
    systemc_cycle_candidate_override: str | None = None,
) -> tuple[Path, Path, Path]:
    candidate_ids = ["candidate_F3", "candidate_F2"]
    candidate_runs = []
    rows = []
    candidate_reports: dict[str, Any] = {}
    for index, candidate_id in enumerate(candidate_ids):
        candidate_dir = root / "candidate_runs" / candidate_id
        b4_ref = write_json(candidate_dir / "gem5_systemc_timed_proxy_report.json", b4_payload(candidate_id, 100 + index * 50, strict=strict_b4))
        stage_c_ref = write_json(root / f"{candidate_id}.stage_c.json", stage_c_payload(candidate_id)) if include_stage_c else None
        stage_d_ref = write_json(root / f"{candidate_id}.stage_d.json", stage_d_payload(candidate_id, stage_c_ref or Path("missing"), kind=stage_d_kind)) if include_stage_c else None
        cycle_ref = None
        cycle_sha = None
        if include_systemc_cycle:
            cycle_candidate = systemc_cycle_candidate_override or candidate_id
            cycle_ref = write_json(
                candidate_dir / "systemc_cycle_accounted_evidence.json",
                systemc_cycle_payload(cycle_candidate, total_cycles=1000 + index * 100),
            )
            cycle_sha = sha256_path(cycle_ref)
        candidate_run = {
            "candidate_id": candidate_id,
            "stage_b0_request": str(root / f"{candidate_id}.stage_b0.json"),
            "gem5_b4_report": str(b4_ref),
        }
        if cycle_ref is not None:
            candidate_run["systemc_cycle_evidence_ref"] = str(cycle_ref)
            candidate_run["systemc_cycle_evidence_sha256"] = cycle_sha
        candidate_runs.append(candidate_run)
        row = {
            "candidate_id": candidate_id,
            "family": "F3" if candidate_id.endswith("F3") else "F2",
            "workload_id": "si4_pbe_uspp_small",
            "case_id": "si4_pbe_uspp_small",
            "screening_rank": index + 1,
            "stage_c_report_ref": str(stage_c_ref) if stage_c_ref else None,
            "stage_d_report_ref": str(stage_d_ref) if stage_d_ref else None,
            "blockers": [] if include_stage_c else ["missing_stage_c_qe_correctness_report", "missing_stage_d_implementation_evidence"],
            "same_candidate_evidence_only": True,
            "final_observed_conclusion_ceiling": "qe_equivalent_scf_correctness_plus_hls_synthesis_only" if include_stage_c and stage_d_kind == "hls_synthesis" else "gem5_systemc_timed_proxy_only",
        }
        if cycle_ref is not None:
            row["systemc_cycle_evidence_ref"] = str(cycle_ref)
            row["systemc_cycle_evidence_sha256"] = cycle_sha
            row["evidence_refs"] = {"systemc_cycle_evidence": str(cycle_ref)}
            row["evidence_hashes"] = {"systemc_cycle_evidence_sha256": cycle_sha}
        rows.append(row)
        candidate_reports[candidate_id] = {"B4": {"report_ref": str(b4_ref), "summary": {"cycle_proxy": 100 + index * 50}}}
    manifest = write_json(
        root / "qe_fpga_dse_e2e_manifest_v0.json",
        {
            "schema_version": "qe_fpga_dse_e2e_manifest_v0",
            "repo_root": str(root),
            "candidate_runs": candidate_runs,
            "claim_ceiling_status_matrix": str(root / "claim_ceiling_status_matrix_v0.json"),
            "backend_report_collection": str(root / "backend_report_collection_v0.json"),
        },
    )
    matrix = write_json(
        root / "claim_ceiling_status_matrix_v0.json",
        {"schema_version": "claim_ceiling_status_matrix_v0", "row_count": len(rows), "rows": rows},
    )
    backend_collection = write_json(
        root / "backend_report_collection_v0.json",
        {"schema_version": "backend_execution_report_collection_v0", "candidate_reports": candidate_reports},
    )
    return manifest, matrix, backend_collection


class QeFinalBestArchitectureDecisionTests(unittest.TestCase):
    def test_current_b4_only_fixture_has_no_winner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest, matrix, collection = write_fixture(root, include_stage_c=False, include_systemc_cycle=False)

            decision = MODULE_ANY.build_decision(
                manifest_path=manifest,
                claim_matrix_path=matrix,
                backend_report_collection_path=collection,
            )

            self.assertIsNone(decision["winner"])
            self.assertEqual(decision["decision_status"], "blocked_no_eligible_candidates")
            self.assertIn("missing_stage_c_qe_correctness_report", decision["ineligible_candidates"][0]["ineligible_reasons"])

    def test_same_candidate_stage_c_hls_stage_d_and_strict_b4_selects_winner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest, matrix, collection = write_fixture(root)

            decision = MODULE_ANY.build_decision(
                manifest_path=manifest,
                claim_matrix_path=matrix,
                backend_report_collection_path=collection,
            )

            self.assertEqual(decision["winner"]["candidate_id"], "candidate_F3")
            self.assertEqual(decision["claim_ceiling"], "final_best_under_hls_synthesis_policy")
            self.assertEqual(len(decision["eligible_candidates"]), 2)
            self.assertEqual(decision["winner"]["evidence_tier"], "final-best-eligible")
            self.assertTrue(decision["winner"]["systemc_cycle_evidence_ref"])
            self.assertTrue(decision["winner"]["systemc_cycle_evidence_sha256"])
            self.assertTrue(decision["winner"]["evidence_hashes"]["stage_c_report_sha256"])
            self.assertTrue(decision["winner"]["evidence_hashes"]["systemc_cycle_evidence_sha256"])

    def test_missing_systemc_cycle_evidence_blocks_final_best(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest, matrix, collection = write_fixture(root, include_systemc_cycle=False)

            decision = MODULE_ANY.build_decision(
                manifest_path=manifest,
                claim_matrix_path=matrix,
                backend_report_collection_path=collection,
            )

            self.assertIsNone(decision["winner"])
            self.assertEqual(decision["decision_status"], "blocked_no_eligible_candidates")
            reasons = decision["ineligible_candidates"][0]["ineligible_reasons"]
            self.assertIn("missing_systemc_cycle_evidence", reasons)
            self.assertIn("missing_systemc_cycle_evidence_ref", reasons)
            self.assertEqual(decision["ineligible_candidates"][0]["evidence_tier"], "projection-screened")

    def test_systemc_cycle_candidate_mismatch_blocks_final_best(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest, matrix, collection = write_fixture(root, systemc_cycle_candidate_override="other_candidate")

            decision = MODULE_ANY.build_decision(
                manifest_path=manifest,
                claim_matrix_path=matrix,
                backend_report_collection_path=collection,
            )

            self.assertIsNone(decision["winner"])
            self.assertIn(
                "systemc_cycle_evidence_candidate_id_mismatch",
                decision["ineligible_candidates"][0]["ineligible_reasons"],
            )
            self.assertEqual(decision["ineligible_candidates"][0]["evidence_tier"], "projection-screened")

    def test_projection_stage_d_is_not_final_best(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest, matrix, collection = write_fixture(root, stage_d_kind="implementation_projection")

            decision = MODULE_ANY.build_decision(
                manifest_path=manifest,
                claim_matrix_path=matrix,
                backend_report_collection_path=collection,
            )

            self.assertIsNone(decision["winner"])
            reasons = decision["ineligible_candidates"][0]["ineligible_reasons"]
            self.assertIn("stage_d_evidence_status_not_available", reasons)
            self.assertIn("implementation_projection_not_allowed_for_final_best", reasons)

    def test_non_strict_b4_is_not_final_best_even_with_stage_c_d(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest, matrix, collection = write_fixture(root, strict_b4=False)

            decision = MODULE_ANY.build_decision(
                manifest_path=manifest,
                claim_matrix_path=matrix,
                backend_report_collection_path=collection,
            )

            self.assertIsNone(decision["winner"])
            self.assertIn(
                "b4_cycle_source_not_gem5_event_timed_device_observed",
                decision["ineligible_candidates"][0]["ineligible_reasons"],
            )

    def test_cli_writes_decision_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest, matrix, collection = write_fixture(root)
            output = root / "decision.json"

            rc = MODULE_ANY.main([
                "--manifest", str(manifest),
                "--claim-matrix", str(matrix),
                "--backend-report-collection", str(collection),
                "--output", str(output),
            ])

            self.assertEqual(rc, 0)
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(written["winner"]["candidate_id"], "candidate_F3")


if __name__ == "__main__":
    unittest.main()
