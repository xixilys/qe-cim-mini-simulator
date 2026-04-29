from __future__ import annotations

import importlib.util
import json
import tempfile
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
    def test_stage_b0_request_selection_prefers_f2_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            request_dir = root / "backend_execution_requests"
            request_dir.mkdir(parents=True)
            descriptors = []
            for family in ("F1", "F2", "F3"):
                name = f"{family}.json"
                request = request_dir / name
                request.write_text(
                    json.dumps(
                        {
                            "candidate_identity": {
                                "architecture_template_id": family,
                                "design_axes": {"family": family},
                            }
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                descriptors.append({"backend_execution_request_ref": f"backend_execution_requests/{name}"})
            (root / "stage_b0_descriptor_manifest_v0.json").write_text(
                json.dumps({"descriptors": descriptors}) + "\n",
                encoding="utf-8",
            )

            selected = MODULE_ANY._first_stage_b0_request(root, preferred_family="F2")

            self.assertEqual(selected.name, "F2.json")

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

    def test_require_real_gem5_b4_rejects_refused_report(self) -> None:
        with self.assertRaisesRegex(MODULE_ANY.E2EError, "execution_status='refused'"):
            MODULE_ANY._enforce_real_gem5_b4_gate(
                {
                    "execution_status": "refused",
                    "claim_ceiling": "gem5_systemc_timed_proxy_only",
                    "backend_class": "gem5_systemc_timed_proxy",
                    "environment": {},
                    "artifact_refs": {},
                    "control_path": {},
                    "metrics": {},
                    "correctness_gate": {"workload_equivalent_claim": False},
                },
                Path("report.json"),
                expected_bridge=Path("libbridge.so"),
            )

    def test_require_real_gem5_b4_accepts_bridge_provenance_and_metrics(self) -> None:
        bridge = Path("libbridge.so")
        MODULE_ANY._enforce_real_gem5_b4_gate(
            {
                "execution_status": "executed",
                "claim_ceiling": "gem5_systemc_timed_proxy_only",
                "backend_class": "gem5_systemc_timed_proxy",
                "environment": {
                    "fpga_execution_mode": "real_bridge",
                    "real_systemc_target": "1",
                    "systemc_bridge": str(bridge),
                },
                "artifact_refs": {"systemc_bridge": str(bridge)},
                "control_path": {
                    "mmio_read_count": 0,
                    "mmio_write_count": 0,
                    "systemc_start_tick": 0,
                    "systemc_end_tick": 100,
                    "completion_tick": 100,
                    "dma_start_tick": 0,
                    "dma_end_tick": 100,
                },
                "metrics": {
                    "host_control_mmio_read_count": 0,
                    "host_control_mmio_write_count": 0,
                    "systemc_datapath_device_busy_ns": 100,
                    "successful_dma_transfer_bytes": 0,
                    "dma_warning_count": 0,
                },
                "correctness_gate": {
                    "workload_equivalent_claim": False,
                    "domain_equivalence_claim": False,
                },
            },
            Path("report.json"),
            expected_bridge=bridge,
        )


if __name__ == "__main__":
    unittest.main()
