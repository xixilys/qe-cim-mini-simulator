from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from typing import Any, cast


MODULE_PATH = Path(__file__).with_name("run_qe_fpga_dse_e2e_v0.py")
SPEC = importlib.util.spec_from_file_location("run_qe_fpga_dse_e2e_v0", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE_ANY = cast(Any, MODULE)


class RunQeFpgaDseE2ETests(unittest.TestCase):
    def test_require_real_gem5_smoke_rejects_refused_report(self) -> None:
        with self.assertRaisesRegex(MODULE_ANY.E2EError, "execution_status='refused'"):
            MODULE_ANY._enforce_real_gem5_smoke_gate(
                {
                    "execution_status": "refused",
                    "claim_ceiling": "gem5_systemc_smoke_only",
                    "backend_class": "gem5_systemc_smoke",
                    "artifact_refs": {"gem5_executable": "missing-gem5.opt"},
                    "correctness_gate": {"workload_equivalent_claim": False},
                },
                Path("report.json"),
            )

    def test_require_real_gem5_smoke_rejects_legacy_b3_conversion(self) -> None:
        with self.assertRaisesRegex(MODULE_ANY.E2EError, "legacy_b3_conversion_used"):
            MODULE_ANY._enforce_real_gem5_smoke_gate(
                {
                    "execution_status": "executed",
                    "claim_ceiling": "gem5_systemc_smoke_only",
                    "backend_class": "gem5_systemc_smoke",
                    "artifact_refs": {"legacy_b3_smoke_report": "legacy.json"},
                    "control_path": {"completion_source": "smoke_immediate_complete"},
                    "correctness_gate": {"workload_equivalent_claim": False},
                },
                Path("report.json"),
            )

    def test_require_real_gem5_smoke_accepts_real_qe_gem5_smoke_envelope(self) -> None:
        MODULE_ANY._enforce_real_gem5_smoke_gate(
            {
                "execution_status": "executed",
                "claim_ceiling": "gem5_systemc_smoke_only",
                "backend_class": "gem5_systemc_smoke",
                "artifact_refs": {"artifact_subtype": "real_qe_gem5_se_scf_smoke_v0"},
                "control_path": {"completion_source": "gem5_se_real_pw_stdout_parser"},
                "correctness_gate": {
                    "workload_equivalent_claim": False,
                    "qe_equivalent_scf_claim": False,
                },
            },
            Path("report.json"),
        )


if __name__ == "__main__":
    unittest.main()
