from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_FPGA_DEVICE_DIR = ROOT / "gem5_integration/src/dev/fpga"
OPTIONAL_GEM5_CHECKOUT_FPGA_DEVICE_DIR = ROOT / "gem5_integration/gem5/src/dev/fpga"
SIMPLE_FPGA_TEST_CONFIG = ROOT / "gem5_integration/configs/fpga/simple_fpga_test.py"


def fpga_device_dirs() -> tuple[Path, ...]:
    """Return SimObject source dirs that are present in this checkout.

    The repository always carries the canonical gem5 device sources under
    ``gem5_integration/src/dev/fpga``.  A built/vendor gem5 checkout under
    ``gem5_integration/gem5`` is an environment artifact created by setup/build
    workflows, so this contract test must not fail before the B4 runner has a
    chance to report the missing gem5 executable/bridge as a guarded refusal.
    """

    dirs = [SOURCE_FPGA_DEVICE_DIR]
    if OPTIONAL_GEM5_CHECKOUT_FPGA_DEVICE_DIR.exists():
        dirs.append(OPTIONAL_GEM5_CHECKOUT_FPGA_DEVICE_DIR)
    return tuple(dirs)


class FPGAAcceleratorSimObjectContractTests(unittest.TestCase):
    def test_config_consumed_proxy_params_are_declared_and_stored(self) -> None:
        self.assertTrue(SOURCE_FPGA_DEVICE_DIR.exists())
        for device_dir in fpga_device_dirs():
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
        self.assertTrue(SOURCE_FPGA_DEVICE_DIR.exists())
        for device_dir in fpga_device_dirs():
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
            "QEBS_TIMING_SIDECAR_JSON",
            "systemc_sidecar_cycle_proxy",
            "gem5_tick_observed",
            "cycle_source",
            "timing_sidecar_projection",
            "QEBS_CANDIDATE_TIMING_PROFILE_JSON",
            "QEBS_STRICT_B4_RUNTIME_TIMING_INPUT",
            "QEBS_STRICT_B4_EVENT_TIMING",
            "QEBS_STRICT_B4_DEVICE_EVENT_REPORT_JSON",
            "FPGAAcceleratorSE",
            "gem5_simobject_counters",
            "event_timed_device_activity_observed",
            "candidate_device_event_delta_ticks",
            "no_cycle_accuracy_claim",
        ):
            with self.subTest(token=token):
                self.assertIn(token, config)
        self.assertIn(
            'cycle_proxy = sidecar_cycle_proxy if timing_source == "timing_sidecar_projection"',
            config,
        )
        self.assertIn(
            'timing_source = "gem5_event_timed_device_observed"',
            config,
        )
        self.assertIn(
            "system.cpu.workload[0].map(STRICT_PIO_BASE, STRICT_PIO_BASE, STRICT_PIO_SIZE, False)",
            config,
        )

    def test_strict_event_se_simobject_declares_schedules_and_reports_observed_ticks(self) -> None:
        self.assertTrue(SOURCE_FPGA_DEVICE_DIR.exists())
        for device_dir in fpga_device_dirs():
            with self.subTest(device_dir=device_dir):
                simobject = (device_dir / "FPGAAcceleratorSE.py").read_text(encoding="utf-8")
                header = (device_dir / "fpga_accelerator_se.hh").read_text(encoding="utf-8")
                impl = (device_dir / "fpga_accelerator_se.cc").read_text(encoding="utf-8")

                for param in (
                    "strict_event_timing",
                    "candidate_profile_ref",
                    "candidate_event_delay_ticks",
                    "candidate_dma_read_bytes",
                    "candidate_dma_write_bytes",
                    "strict_event_report_path",
                ):
                    self.assertIn(param, simobject)
                    self.assertIn(f"p.{param}", impl)

                for member in (
                    "strictEventTiming",
                    "candidateProfileRef",
                    "candidateEventDelayTicks",
                    "observedReadCount",
                    "observedWriteCount",
                    "pollingReadCount",
                    "commandIssueTick",
                    "deviceAcceptTick",
                    "completionTick",
                    "eventDeltaTicks",
                    "completionEvent",
                ):
                    self.assertIn(member, header)
                    self.assertIn(member, impl)

                for token in (
                    "schedule(completionEvent",
                    "completeComputation",
                    "writeStrictEventReport",
                    "qebs_gem5_fpga_se_event_report_v0",
                    "gem5_simobject_counters",
                    "candidate_device_event_delta_ticks",
                ):
                    self.assertIn(token, impl)


if __name__ == "__main__":
    unittest.main()
