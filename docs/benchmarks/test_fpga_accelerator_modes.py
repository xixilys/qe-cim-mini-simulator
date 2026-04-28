from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PY_SIMOBJECT = ROOT / "gem5_integration/src/dev/fpga/FPGAAccelerator.py"
HEADER = ROOT / "gem5_integration/src/dev/fpga/fpga_accelerator.hh"
SOURCE = ROOT / "gem5_integration/src/dev/fpga/fpga_accelerator.cc"


class FPGAAcceleratorModeSplitTests(unittest.TestCase):
    def test_simobject_exposes_explicit_execution_mode(self) -> None:
        text = PY_SIMOBJECT.read_text(encoding="utf-8")
        self.assertIn("execution_mode = Param.String", text)
        self.assertIn("smoke", text)
        self.assertIn("timed_proxy", text)
        self.assertIn("real_bridge", text)
        self.assertIn("guarded real_bridge", text)
        self.assertIn("real_systemc_target", text)

    def test_header_defines_completion_sources_and_counters(self) -> None:
        text = HEADER.read_text(encoding="utf-8")
        self.assertIn("enum class ExecutionMode", text)
        self.assertIn("COMPLETION_SMOKE_IMMEDIATE", text)
        self.assertIn("COMPLETION_TIMED_EVENT", text)
        self.assertIn("COMPLETION_REAL_BRIDGE_EVENT", text)
        self.assertIn("electronsCommandCount", text)
        self.assertIn("electronsCompletionCount", text)

    def test_smoke_mode_is_only_immediate_completion_path(self) -> None:
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("bool FPGAAccelerator::immediateElectronsCompletion() const", text)
        self.assertIn("return executionMode == ExecutionMode::Smoke", text)
        self.assertIn("completeElectrons(COMPLETION_SMOKE_IMMEDIATE)", text)
        self.assertIn("COMPLETION_TIMED_EVENT", text)
        self.assertIn("real_bridge execution requires", text)
        self.assertIn("real_systemc_target", text)
        self.assertIn("schedule(electronsDoneEvent, curTick() + compute_delay)", text)


    def test_stub_binding_is_smoke_only_and_timed_proxy_uses_local_event(self) -> None:
        text = SOURCE.read_text(encoding="utf-8")
        init_start = text.index("void FPGAAccelerator::init()")
        init_end = text.index("void FPGAAccelerator::startup()", init_start + 1)
        init_body = text[init_start:init_end]
        self.assertIn("executionMode != ExecutionMode::Smoke", init_body)
        self.assertIn("tlmStub = new FPGATLMStub", init_body)

        exec_start = text.index("void FPGAAccelerator::executeElectrons()")
        exec_end = text.index("namespace TimingProxy", exec_start + 1)
        exec_body = text[exec_start:exec_end]
        self.assertIn("executionMode == ExecutionMode::Smoke", exec_body)
        self.assertIn("sendTLMTransaction", exec_body)
        self.assertIn("ExecutionMode::TimedProxy", exec_body)
        self.assertIn("COMPLETION_TIMED_EVENT", exec_body)
        smoke_branch_start = exec_body.index("executionMode == ExecutionMode::Smoke")
        timed_branch_start = exec_body.index("ExecutionMode::TimedProxy")
        self.assertLess(smoke_branch_start, timed_branch_start)
        timed_body = exec_body[timed_branch_start:]
        self.assertNotIn("sendTLMTransaction", timed_body.split("#else")[0])

    def test_real_bridge_requires_explicit_target_flag(self) -> None:
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("real_systemc_target", PY_SIMOBJECT.read_text(encoding="utf-8"))
        self.assertIn("p.real_systemc_target", text)
        self.assertIn("ExecutionMode::RealBridge", text)
        self.assertIn("COMPLETION_REAL_BRIDGE_EVENT", HEADER.read_text(encoding="utf-8"))
        self.assertIn("B4 must refuse when unavailable", text)
        self.assertIn("no smoke/timed_proxy fallback", text)

    def test_timed_path_does_not_unconditionally_set_done_in_command_body(self) -> None:
        text = SOURCE.read_text(encoding="utf-8")
        start = text.index("void FPGAAccelerator::executeElectrons()")
        end = text.index("namespace TimingProxy", start + 1)
        body = text[start:end]
        immediate_done_index = body.find("completeElectrons(COMPLETION_SMOKE_IMMEDIATE)")
        schedule_index = body.find("schedule(electronsDoneEvent, curTick() + compute_delay)")
        self.assertGreater(immediate_done_index, -1)
        self.assertGreater(schedule_index, -1)
        self.assertLess(immediate_done_index, schedule_index)
        self.assertIn("if (immediateElectronsCompletion())", body)
        self.assertIn("else", body)
        self.assertIn("executionMode == ExecutionMode::RealBridge", body)
        self.assertIn("panic(", body)
        scheduled_body = body[body.index("if (immediateElectronsCompletion())"):]
        self.assertNotIn("COMPLETION_REAL_BRIDGE_EVENT", scheduled_body)

    def test_unsupported_execution_mode_does_not_fallback_to_smoke(self) -> None:
        text = SOURCE.read_text(encoding="utf-8")
        constructor_start = text.index("FPGAAccelerator::FPGAAccelerator")
        constructor_end = text.index("dmaEngine = new DMAEngine", constructor_start + 1)
        constructor_body = text[constructor_start:constructor_end]

        self.assertIn("Unsupported FPGAAccelerator execution_mode", constructor_body)
        self.assertNotIn("falling back to smoke", constructor_body)

    def test_timed_proxy_command_latency_is_not_shadowed_by_config_window(self) -> None:
        text = SOURCE.read_text(encoding="utf-8")
        start = text.index("static double get_register_latency")
        end = text.index("static uint64_t calculate_electrons_time_ns", start + 1)
        body = text[start:end]

        self.assertLess(
            body.index("addr == 0x0128"),
            body.index("addr >= 0x0100 && addr < 0x0200"),
        )
        self.assertIn("return ELECTRONS_CMD_LATENCY_NS", body)


if __name__ == "__main__":
    unittest.main()
