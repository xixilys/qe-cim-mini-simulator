from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

BENCHMARKS_DIR = Path(__file__).resolve().parent
if str(BENCHMARKS_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS_DIR))

from unified_dse.interfaces import DesignPoint, EvaluationConfig, WorkloadDescriptor
from unified_dse.systemc_backend import SystemCBackend


class UnifiedDseSystemCBackendTests(unittest.TestCase):
    def make_workload(self) -> WorkloadDescriptor:
        return WorkloadDescriptor.from_dict(
            {
                "workload_id": "si8_proxy",
                "domain": "dft",
                "app_adapter": "qe",
                "dimension_n": 128,
                "dimension_m": 16,
                "scf_iterations": 2,
                "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
            }
        )

    def make_design_point(self) -> DesignPoint:
        return DesignPoint.from_dict(
            {
                "family": "F2",
                "diag_policy": "device_first_fallback",
                "offload_scope": "balanced",
                "resident_policy": "fit_first",
                "partition_strategy": "operator__build__diag__refresh",
            }
        )

    def write_fake_systemc_model(self, directory: Path) -> Path:
        exe = directory / "fake_qe_band_solver_model.py"
        exe.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os\n"
            "from pathlib import Path\n"
            "out = Path(os.environ['QEBS_RESULT_JSON'])\n"
            "payload = {\n"
            "  'schema_version': 'systemc_architecture_candidate_result_v0',\n"
            "  'case_id': os.environ.get('QEBS_CASE_ID'),\n"
            "  'architecture_family': os.environ.get('QEBS_ARCH_FAMILY'),\n"
            "  'assumption_set_id': os.environ.get('QEBS_ASSUMPTION_SET_ID'),\n"
            "  'run_config': {'max_scf_iters': int(os.environ.get('QEBS_MAX_SCF_ITERS', '1'))},\n"
            "  'final': {'converged': True, 'scf_iterations': 2},\n"
            "  'run_summary': {'total_ref_cycles': 1000, 'total_episodes': 2},\n"
            "  'metrics': {\n"
            "    'device_busy_ref_cycles': 700,\n"
            "    'dma_ref_cycles': 200,\n"
            "    'host_assist_ref_cycles': 100,\n"
            "    'cpu_fallbacks': 1,\n"
            "    'resident_reuse_hits': 1,\n"
            "    'total_data_movement_kib': 8,\n"
            "    'dma_read_kib': 5,\n"
            "    'dma_write_kib': 3\n"
            "  },\n"
            "  'iteration_diagnostics': [{'spill_active': False}, {'spill_active': True}],\n"
            "  'cluster_metrics': {},\n"
            "  'timing': {'wall_time_s': 0.02}\n"
            "}\n"
            "out.parent.mkdir(parents=True, exist_ok=True)\n"
            "out.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        exe.chmod(exe.stat().st_mode | 0o111)
        return exe

    def test_l0_uses_real_fast_model_metrics_not_stub(self) -> None:
        backend = SystemCBackend(
            model_path="unused",
            config=EvaluationConfig(fidelity_level="L0"),
        )

        result = backend.evaluate(self.make_workload(), self.make_design_point())

        self.assertEqual(result.backend, "fast_model")
        self.assertEqual(result.result_status, "screened")
        self.assertIn("latency_s", result.metrics)
        self.assertIn("throughput_workloads_per_s", result.metrics)
        self.assertIn("avg_system_power_proxy_w", result.metrics)
        self.assertGreater(result.metrics["latency_s"], 0.0)

    def test_l2_invokes_systemc_and_returns_latency_throughput_power(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            executable = self.write_fake_systemc_model(tmp)
            backend = SystemCBackend(
                model_path=executable,
                config=EvaluationConfig(
                    fidelity_level="L2",
                    output_dir=tmp / "out",
                    allow_execute=True,
                    max_scf_iters=2,
                ),
            )

            result = backend.evaluate(self.make_workload(), self.make_design_point())

            self.assertEqual(result.backend, "systemc")
            self.assertEqual(result.result_status, "executed")
            self.assertEqual(result.source_kind, "timed_functional_proxy")
            self.assertEqual(result.metrics["latency_s"], 0.02)
            self.assertEqual(result.metrics["cycle_proxy"], 1000)
            self.assertEqual(result.metrics["bytes_moved_to_convergence"], 8192)
            self.assertGreater(result.metrics["throughput_workloads_per_s"], 0.0)
            self.assertGreater(result.metrics["avg_system_power_proxy_w"], 0.0)
            self.assertTrue(Path(result.extra_fields["backend_observability"]["metrics_path"]).exists())


if __name__ == "__main__":
    unittest.main()
