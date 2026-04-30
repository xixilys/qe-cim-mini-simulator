from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("dse_evidence_tier_classifier_v0.py")
SPEC = importlib.util.spec_from_file_location("dse_evidence_tier_classifier_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)


class DseEvidenceTierClassifierTests(unittest.TestCase):
    def classify(self, **kwargs: Any) -> tuple[str, list[str]]:
        defaults = {
            "same_candidate_evidence_only": True,
            "stage_c_correct": False,
            "strict_b4_evidence": False,
            "stage_d_policy_satisfied": False,
            "systemc_cycle_evidence": False,
        }
        defaults.update(kwargs)
        return MODULE_ANY.classify_candidate_evidence(**defaults)

    def test_exact_label_taxonomy_is_centralized(self) -> None:
        self.assertEqual(
            MODULE_ANY.EVIDENCE_TIER_LABELS,
            (
                "survey-catalog",
                "projection-screened",
                "systemc-cycle-accounted",
                "final-best-eligible",
            ),
        )
        with self.assertRaises(MODULE_ANY.EvidenceTierError):
            MODULE_ANY.validate_evidence_tier("projection_grade")

    def test_catalog_only_is_survey_catalog_not_final_best(self) -> None:
        tier, reasons = self.classify(catalog_provenance=True)

        self.assertEqual(tier, "survey-catalog")
        self.assertIn("missing_systemc_cycle_evidence", reasons)
        self.assertIn("strict_b4_evidence_missing", reasons)

    def test_projection_without_systemc_is_projection_screened(self) -> None:
        tier, reasons = self.classify(projection_screened=True, strict_b4_evidence=True)

        self.assertEqual(tier, "projection-screened")
        self.assertIn("missing_systemc_cycle_evidence", reasons)
        self.assertIn("missing_stage_c_qe_correctness_report", reasons)

    def test_systemc_only_is_cycle_accounted_but_not_final_best(self) -> None:
        tier, reasons = self.classify(systemc_cycle_evidence=True)

        self.assertEqual(tier, "systemc-cycle-accounted")
        self.assertIn("missing_stage_c_qe_correctness_report", reasons)
        self.assertIn("missing_stage_d_implementation_evidence", reasons)

    def test_all_required_same_candidate_evidence_is_final_best_eligible(self) -> None:
        tier, reasons = self.classify(
            stage_c_correct=True,
            strict_b4_evidence=True,
            stage_d_policy_satisfied=True,
            systemc_cycle_evidence=True,
        )

        self.assertEqual(tier, "final-best-eligible")
        self.assertEqual(reasons, [])

    def test_alignment_blocker_prevents_final_best_even_when_evidence_exists(self) -> None:
        tier, reasons = self.classify(
            same_candidate_evidence_only=False,
            stage_c_correct=True,
            strict_b4_evidence=True,
            stage_d_policy_satisfied=True,
            systemc_cycle_evidence=True,
        )

        self.assertEqual(tier, "systemc-cycle-accounted")
        self.assertIn("candidate_evidence_alignment_mismatch", reasons)


if __name__ == "__main__":
    unittest.main()
