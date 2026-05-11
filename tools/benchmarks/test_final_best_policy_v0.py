from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("final_best_policy_v0.py")
SPEC = importlib.util.spec_from_file_location("final_best_policy_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)


class FinalBestPolicyTests(unittest.TestCase):
    def hls_evidence(self) -> dict[str, Any]:
        return {
            "evidence_kind": "hls_synthesis",
            "evidence_status": "available",
            "claim_ceiling": "hls_synthesis_only",
            "correctness_dependency": {"qe_equivalent_scf_claim": True},
        }

    def projection_evidence(self) -> dict[str, Any]:
        return {
            "evidence_kind": "implementation_projection",
            "evidence_status": "partial",
            "claim_ceiling": "implementation_evidence_only",
            "correctness_dependency": {"qe_equivalent_scf_claim": True},
        }

    def test_default_policy_requires_hls_and_rejects_projection(self) -> None:
        policy = MODULE_ANY.load_policy(None)
        ok, reasons = MODULE_ANY.stage_d_satisfies_policy(self.projection_evidence(), policy)

        self.assertFalse(ok)
        self.assertIn("stage_d_evidence_status_not_available", reasons)
        self.assertIn("implementation_projection_not_allowed_for_final_best", reasons)
        self.assertEqual(policy["minimum_stage_d_tier"], "hls_synthesis")
        self.assertEqual(policy["required_final_best_evidence_tier"], "final-best-eligible")
        self.assertTrue(policy["require_systemc_cycle_accounted_evidence"])
        self.assertIn(
            "no_final_best_without_same_candidate_stage_c_stage_d_strict_b4_and_systemc_cycle_evidence",
            policy["non_claims"],
        )

    def test_hls_available_satisfies_default_policy(self) -> None:
        policy = MODULE_ANY.load_policy(None)
        ok, reasons = MODULE_ANY.stage_d_satisfies_policy(self.hls_evidence(), policy)

        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_policy_file_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "policy.json"
            policy = MODULE_ANY.default_policy()
            policy["minimum_stage_d_tier"] = "rtl_simulation"
            path.write_text(json.dumps(policy), encoding="utf-8")

            loaded = MODULE_ANY.load_policy(path)

            self.assertEqual(loaded["minimum_stage_d_tier"], "rtl_simulation")
            ok, reasons = MODULE_ANY.stage_d_satisfies_policy(self.hls_evidence(), loaded)
            self.assertFalse(ok)
            self.assertIn("stage_d_tier_below_policy_minimum:hls_synthesis<rtl_simulation", reasons)

    def test_policy_rejects_non_final_best_evidence_tier_requirement(self) -> None:
        policy = MODULE_ANY.default_policy()
        policy["required_final_best_evidence_tier"] = "systemc-cycle-accounted"

        with self.assertRaisesRegex(MODULE_ANY.PolicyError, "final-best-eligible"):
            MODULE_ANY.validate_policy(policy)

    def test_systemc_b4_minimum_policy_treats_stage_d_as_optional_upgrade(self) -> None:
        policy = MODULE_ANY.systemc_b4_minimum_policy()
        ok, reasons = MODULE_ANY.stage_d_satisfies_policy(None, policy)

        self.assertTrue(ok)
        self.assertEqual(reasons, [])
        self.assertFalse(policy["stage_d_required_for_final_best"])
        self.assertIsNone(policy["minimum_stage_d_tier"])
        self.assertEqual(policy["policy_id"], MODULE_ANY.SYSTEMC_B4_MINIMUM_POLICY_ID)
        self.assertIn(
            "no_final_best_without_same_candidate_stage_c_strict_b4_systemc_cycle_catalog_freeze_and_dominance_evidence",
            policy["non_claims"],
        )
        self.assertEqual(
            MODULE_ANY.filter_policy_blockers(
                [
                    "missing_stage_c_qe_correctness_report",
                    "missing_stage_d_implementation_evidence",
                    "strict_b4_evidence_missing",
                ],
                policy,
            ),
            ["missing_stage_c_qe_correctness_report", "strict_b4_evidence_missing"],
        )
        self.assertEqual(
            MODULE_ANY.optional_precision_upgrade_risks(None, policy),
            ["missing_optional_stage_d_hls_or_stronger_evidence"],
        )

    def test_systemc_b4_minimum_policy_file_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "policy.json"
            MODULE_ANY.write_policy(path, MODULE_ANY.systemc_b4_minimum_policy())

            loaded = MODULE_ANY.load_policy(path)

            self.assertFalse(MODULE_ANY.stage_d_required_for_final_best(loaded))
            self.assertEqual(
                MODULE_ANY.claim_label_for_policy({"candidate_id": "cand-a"}, loaded),
                "final_best_under_systemc_b4_minimum_policy::cand-a",
            )


if __name__ == "__main__":
    unittest.main()
