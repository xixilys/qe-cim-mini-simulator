from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("materialize_systemc_cycle_accounted_evidence_v0.py")
SPEC = importlib.util.spec_from_file_location("materialize_systemc_cycle_accounted_evidence_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def systemc_candidate(*, include_total_ref_cycles: bool = True, candidate_id: str | None = None) -> dict[str, Any]:
    run_summary: dict[str, Any] = {
        "total_episodes": 4,
        "total_backpressure_ref_cycles": 20,
        "convergence_reason": "mixed_density_converged",
    }
    if include_total_ref_cycles:
        run_summary["total_ref_cycles"] = 1000
    payload: dict[str, Any] = {
        "schema_version": "systemc_architecture_candidate_result_v0",
        "generated_at_utc": "2026-05-01T00:00:00Z",
        "case_id": "si4_pbe_uspp_small",
        "architecture_family": "F3",
        "run_summary": run_summary,
        "metrics": {
            "device_busy_ref_cycles": 600,
            "dma_ref_cycles": 200,
            "host_assist_ref_cycles": 100,
            "cpu_fallbacks": 1,
            "resident_reuse_hits": 3,
            "total_data_movement_kib": 512.0,
        },
        "cluster_metrics": {
            "cluster_a": {
                "cluster_name": "ClusterA",
                "invocations": 4,
                "accounted_ref_cycles": 360,
                "backpressure_ref_cycles": 9,
                "data_movement_kib": 320.0,
                "dominant_resource": "CIM_PROJECT_BACKPROJECT_CHAIN",
            },
            "cluster_b": {
                "cluster_name": "ClusterB",
                "invocations": 4,
                "accounted_ref_cycles": 120,
                "backpressure_ref_cycles": 4,
                "data_movement_kib": 24.0,
                "dominant_resource": "ReductionClosureEngine",
            },
            "cluster_c": {
                "cluster_name": "ClusterC",
                "invocations": 4,
                "accounted_ref_cycles": 80,
                "backpressure_ref_cycles": 3,
                "data_movement_kib": 8.0,
                "dominant_resource": "ClusterC.SolverPipeline",
            },
            "cluster_d": {
                "cluster_name": "ClusterD",
                "invocations": 4,
                "accounted_ref_cycles": 40,
                "backpressure_ref_cycles": 2,
                "data_movement_kib": 6.0,
                "dominant_resource": "ClusterD.RefreshWriteback",
            },
        },
    }
    if candidate_id is not None:
        payload["candidate_id"] = candidate_id
    return payload


class SystemcCycleAccountedEvidenceTests(unittest.TestCase):
    def test_materializes_candidate_cycle_report_with_hashes_and_non_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate_result = write_json(root / "candidate_result.json", systemc_candidate())
            template = write_json(
                root / "template.json",
                {
                    "template_id": "f3_template",
                    "family": "F3",
                    "clusters": [],
                    "policies": {},
                },
            )
            config = write_json(
                root / "candidate.systemc_config.json",
                {
                    "projection_metadata": {
                        "candidate_id": "candidate_F3",
                        "source_template_id": "f3_template",
                        "source_template_sha256": "sha256:template_from_loader",
                        "support_status": "supported",
                        "support_evidence": {"executor": "native_systemc_model"},
                    }
                },
            )
            calibration = write_json(root / "calibration.json", {"calibration_status": "not_measured"})

            payload = MODULE_ANY.materialize_systemc_cycle_evidence(
                systemc_candidate_result=candidate_result,
                candidate_id="candidate_F3",
                workload_id="si4_pbe_uspp_small",
                architecture_template_ref=template,
                systemc_config_ref=config,
                calibration_refs={"stage_d_projection": calibration},
                output_ref=root / "report.json",
            )

            self.assertEqual(payload["schema_version"], "systemc_cycle_accounted_evidence_v0")
            self.assertEqual(payload["evidence_tier_label"], "systemc-cycle-accounted")
            self.assertEqual(payload["claim_label"], "systemc-cycle-accounted")
            self.assertEqual(payload["candidate_id"], "candidate_F3")
            self.assertEqual(payload["workload_id"], "si4_pbe_uspp_small")
            self.assertEqual(payload["architecture_template_id"], "f3_template")
            self.assertEqual(payload["model_support_status"]["status"], "supported")
            self.assertEqual(payload["cycle_accounting"]["total_cycles"], 1000)
            self.assertEqual(payload["cycle_accounting"]["included_stage_cycle_total"], 1000)
            stage_ids = {row["stage_id"] for row in payload["cycle_accounting"]["per_stage_cycle_table"]}
            self.assertIn("cluster_a", stage_ids)
            self.assertIn("dma_transfer", stage_ids)
            self.assertIn("host_assist_control", stage_ids)
            self.assertIn("unattributed_control_or_scheduler_residual", stage_ids)
            component_ids = {
                row["component_id"] for row in payload["cycle_accounting"]["per_component_cycle_table"]
            }
            self.assertIn("CIM_PROJECT_BACKPROJECT_CHAIN", component_ids)
            self.assertTrue(payload["template_config_hash"].startswith("sha256:"))
            self.assertTrue(payload["artifact_hashes"]["systemc_candidate_result"]["sha256"].startswith("sha256:"))
            self.assertTrue(payload["artifact_hashes"]["architecture_template"]["sha256"].startswith("sha256:"))
            self.assertEqual(
                payload["calibration_refs"][0]["ref_id"],
                "stage_d_projection",
            )
            self.assertFalse(payload["final_best_eligible"])
            self.assertFalse(payload["final_best_claim"])
            self.assertFalse(payload["claim_boundary"]["cycle_accuracy_claim"])
            self.assertIn("not_rtl_cycle_accurate", payload["non_claims"])
            self.assertIn("not_final_best_architecture_claim", payload["non_claims"])

    def test_missing_run_summary_total_uses_component_metric_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate_result = write_json(
                root / "candidate_result.json",
                systemc_candidate(include_total_ref_cycles=False),
            )

            payload = MODULE_ANY.materialize_systemc_cycle_evidence(
                systemc_candidate_result=candidate_result,
                candidate_id="candidate_F3",
                workload_id="si4_pbe_uspp_small",
            )

            self.assertEqual(payload["cycle_accounting"]["total_cycles"], 900)
            self.assertEqual(payload["cycle_accounting"]["included_stage_cycle_total"], 900)
            diagnostic = [
                row
                for row in payload["cycle_accounting"]["per_stage_cycle_table"]
                if row["stage_id"] == "backpressure_diagnostic"
            ][0]
            self.assertFalse(diagnostic["included_in_total"])

    def test_identity_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate_result = write_json(
                root / "candidate_result.json",
                systemc_candidate(candidate_id="candidate_A"),
            )

            with self.assertRaisesRegex(MODULE_ANY.CycleEvidenceInputError, "candidate_id mismatch"):
                MODULE_ANY.materialize_systemc_cycle_evidence(
                    systemc_candidate_result=candidate_result,
                    candidate_id="candidate_B",
                    workload_id="si4_pbe_uspp_small",
                )

    def test_cli_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate_result = write_json(root / "candidate_result.json", systemc_candidate())
            output = root / "systemc_cycle_report.json"

            rc = MODULE_ANY.main(
                [
                    "--systemc-candidate-result",
                    str(candidate_result),
                    "--candidate-id",
                    "candidate_F3",
                    "--workload-id",
                    "si4_pbe_uspp_small",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(rc, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["evidence_tier_label"], "systemc-cycle-accounted")
            self.assertEqual(payload["candidate_id"], "candidate_F3")


if __name__ == "__main__":
    unittest.main()
