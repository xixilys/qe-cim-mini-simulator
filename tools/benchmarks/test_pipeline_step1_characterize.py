#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

import sys

sys.path.insert(0, str(ROOT))

from interfaces.validator import InterfaceValidator
from pipeline import ArtifactStore, Step1_Characterize


class Step1CharacterizeTest(unittest.TestCase):
    def test_characterizes_existing_qe_trace_bundle(self) -> None:
        case_dir = ROOT / "docs/benchmarks/archive/results/qe_workload_revalidation/h2_tiny"
        raw_bundle = {
            "schema_version": "raw_trace_bundle_v1",
            "case_id": "h2_tiny",
            "trace_files": {
                "stdout": str(case_dir / "stdout.out"),
                "subspace_trace": str(case_dir / "subspace_trace.csv"),
                "hpsi_trace": str(case_dir / "hpsi_trace.csv"),
                "bandsolver_trace": str(case_dir / "bandsolver_trace.csv"),
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            store = ArtifactStore(Path(tmp))
            validator = InterfaceValidator()
            input_hash = store.store(raw_bundle)

            output_hash, provenance = Step1_Characterize(store, validator).execute(input_hash)
            artifact = store.load(output_hash)

        self.assertEqual("workload_profile_v1", artifact["schema_version"])
        self.assertEqual("h2_tiny", artifact["workload_id"])
        self.assertGreater(provenance.execution_time_seconds, 0.0)

        validation = InterfaceValidator().validate(artifact, "workload_profile_v1")
        self.assertTrue(validation.valid, validation.errors)

        nodes = {node["id"]: node for node in artifact["compute_graph"]["nodes"]}
        self.assertIn("h_psi", nodes)
        self.assertIn("s_psi", nodes)
        self.assertIn("cdiaghg", nodes)
        self.assertIn("build_H_sub", nodes)
        self.assertIn("refresh", nodes)

        self.assertEqual(32, nodes["h_psi"]["call_count"])
        self.assertEqual(32, nodes["s_psi"]["call_count"])
        self.assertEqual(31, nodes["cdiaghg"]["call_count"])
        self.assertGreater(nodes["h_psi"]["flops_per_call"], 0.0)
        self.assertGreater(nodes["h_psi"]["arithmetic_intensity"], 0.0)
        self.assertEqual([129, 129], nodes["h_psi"]["typical_sizes"]["N"])

        total_dominance = sum(node["dominance"] for node in nodes.values())
        self.assertLessEqual(total_dominance, 1.01)
        self.assertGreater(nodes["h_psi"]["dominance"], 0.0)
        self.assertGreater(nodes["cdiaghg"]["dominance"], 0.0)

        self.assertGreaterEqual(len(artifact["compute_graph"]["edges"]), 4)
        self.assertGreater(artifact["memory_profile"]["working_set_mb"], 0.0)
        self.assertGreater(artifact["data_movement"]["device_internal_mb_per_iter"], 0.0)
        self.assertEqual("h2_tiny", artifact["metadata"]["case_id"])


if __name__ == "__main__":
    unittest.main()
