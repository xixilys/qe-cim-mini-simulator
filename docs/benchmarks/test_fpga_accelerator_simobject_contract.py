from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FPGA_DEVICE_DIRS = (
    ROOT / "gem5_integration/src/dev/fpga",
    ROOT / "gem5_integration/gem5/src/dev/fpga",
)
SIMPLE_FPGA_TEST_CONFIG = ROOT / "gem5_integration/configs/fpga/simple_fpga_test.py"


class FPGAAcceleratorSimObjectContractTests(unittest.TestCase):
    def test_config_consumed_proxy_params_are_declared_and_stored(self) -> None:
        for device_dir in FPGA_DEVICE_DIRS:
            with self.subTest(device_dir=device_dir):
                simobject = (device_dir / "FPGAAccelerator.py").read_text(encoding="utf-8")
                header = (device_dir / "fpga_accelerator.hh").read_text(encoding="utf-8")
                impl = (device_dir / "fpga_accelerator.cc").read_text(encoding="utf-8")

                for param in (
                    "execution_mode",
                    "real_systemc_target",
                    "roi_stats_enabled",
                    "roi_label",
                ):
                    self.assertIn(param, simobject)
                    self.assertIn(f"p.{param}", impl)

                for member in (
                    "executionMode",
                    "realSystemCTarget",
                    "roiStatsEnabled",
                    "roiLabel",
                ):
                    self.assertIn(member, header)
                    self.assertIn(member, impl)

    def test_real_bridge_mode_has_local_hard_gate(self) -> None:
        for device_dir in FPGA_DEVICE_DIRS:
            with self.subTest(device_dir=device_dir):
                impl = (device_dir / "fpga_accelerator.cc").read_text(encoding="utf-8")
                self.assertIn('executionMode == "real_bridge"', impl)
                self.assertIn("realSystemCTarget", impl)
                self.assertIn("requires real_systemc_target=true", impl)

    def test_simple_gem5_config_can_emit_b4_backend_report_shape(self) -> None:
        config = SIMPLE_FPGA_TEST_CONFIG.read_text(encoding="utf-8")
        for token in (
            "QEBS_BACKEND_EXECUTION_REPORT_JSON",
            "gem5_systemc_timed_proxy_only",
            "backend_runner_gem5_systemc",
            "host_control_mmio_read_count",
            "systemc_datapath_device_busy_ns",
            "successful_dma_transfer_bytes",
            "no_cycle_accuracy_claim",
        ):
            with self.subTest(token=token):
                self.assertIn(token, config)


if __name__ == "__main__":
    unittest.main()
