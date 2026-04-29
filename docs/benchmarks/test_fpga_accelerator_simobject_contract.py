from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FPGA_SIMOBJECT = ROOT / "gem5_integration/src/dev/fpga/FPGAAccelerator.py"
FPGA_HEADER = ROOT / "gem5_integration/src/dev/fpga/fpga_accelerator.hh"
FPGA_IMPL = ROOT / "gem5_integration/src/dev/fpga/fpga_accelerator.cc"


class FPGAAcceleratorSimObjectContractTests(unittest.TestCase):
    def test_config_consumed_proxy_params_are_declared_and_stored(self) -> None:
        simobject = FPGA_SIMOBJECT.read_text(encoding="utf-8")
        header = FPGA_HEADER.read_text(encoding="utf-8")
        impl = FPGA_IMPL.read_text(encoding="utf-8")

        for param in (
            "execution_mode",
            "real_systemc_target",
            "roi_stats_enabled",
            "roi_label",
        ):
            with self.subTest(param=param):
                self.assertIn(param, simobject)
                self.assertIn(f"p.{param}", impl)

        for member in (
            "executionMode",
            "realSystemCTarget",
            "roiStatsEnabled",
            "roiLabel",
        ):
            with self.subTest(member=member):
                self.assertIn(member, header)
                self.assertIn(member, impl)

    def test_real_bridge_mode_has_local_hard_gate(self) -> None:
        impl = FPGA_IMPL.read_text(encoding="utf-8")

        self.assertIn('executionMode == "real_bridge"', impl)
        self.assertIn("realSystemCTarget", impl)
        self.assertIn("requires real_systemc_target=true", impl)


if __name__ == "__main__":
    unittest.main()
