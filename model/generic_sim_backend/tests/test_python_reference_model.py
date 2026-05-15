#!/usr/bin/env python3
"""Contract tests for the SystemC/Python sidecar reference model."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_ROOT = REPO_ROOT / "model" / "generic_sim_backend"
sys.path.insert(0, str(REPO_ROOT))

from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend  # noqa: E402
from dse_v2.core.architecture.accelerator import create_fpga_u280, create_gpu_a100  # noqa: E402
from dse_v2.core.workload import create_tensor_chain_graph  # noqa: E402
from dse_v2.dse.orchestrator import DesignPoint, SystemArchitecture  # noqa: E402


class PythonReferenceModelContractTest(unittest.TestCase):
    def test_dse_built_systemc_request_runs_python_model_and_preserves_claim_boundary(self) -> None:
        graph = create_tensor_chain_graph("python_sidecar_contract")
        architecture = SystemArchitecture(
            system_id="python-sidecar-arch",
            accelerators=[create_gpu_a100("gpu-0"), create_fpga_u280("fpga-0")],
        )
        mapping = {node_id: ("gpu-0" if index % 2 == 0 else "fpga-0") for index, node_id in enumerate(graph.nodes)}
        design_point = DesignPoint("python_sidecar_dp", architecture, mapping)
        request = GenericSystemCBackend()._build_request(design_point, graph)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            request_path = tmp / "simulation_request.json"
            result_path = tmp / "python_model_result.json"
            trace_path = tmp / "python_model_trace.json"
            request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(MODEL_ROOT / "tools" / "python_reference_model.py"),
                    "--request",
                    str(request_path),
                    "--result",
                    str(result_path),
                    "--trace",
                    str(trace_path),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            trace = json.loads(trace_path.read_text(encoding="utf-8"))

        self.assertEqual(result["schema_version"], "gsim.python_model_result.v1")
        self.assertEqual(result["input_request"]["schema_version"], "gsim.request.v1")
        self.assertEqual(result["input_request"]["node_count"], len(request["workload"]["nodes"]))
        self.assertEqual(result["model_invocation"]["accepted_payload_source"], "generic_systemc_request")

        claim_boundary = result["claim_boundary"]
        self.assertEqual(claim_boundary["claim"], "model_contract_and_projection_only")
        self.assertFalse(claim_boundary["trusted_speedup"])
        self.assertFalse(claim_boundary["trusted_qe_correctness"])
        self.assertTrue(claim_boundary["requires_l4_full_flow_for_trusted_speedup"])

        numerical = result["numerical_validation"]
        self.assertTrue(numerical["enabled"])
        self.assertTrue(numerical["golden_model_executed"])
        self.assertTrue(numerical["all_tensors_passed"])
        self.assertEqual(numerical["unsupported_ops"], [])
        self.assertEqual(len(numerical["tensors"]), len(request["workload"]["nodes"]))
        self.assertTrue(all(tensor["reference"] == "deterministic_contract_kernel" for tensor in numerical["tensors"]))

        timing = result["timing_reference"]
        self.assertGreater(timing["latency_ms"], 0.0)
        self.assertGreater(timing["throughput_gops"], 0.0)
        self.assertEqual(len(timing["per_node"]), len(request["workload"]["nodes"]))
        self.assertEqual(trace["schema_version"], "gsim.python_model_trace.v1")
        self.assertEqual(len(trace["events"]), len(request["workload"]["nodes"]))

    def test_contract_schema_declares_projection_not_trusted_claim(self) -> None:
        schema_path = MODEL_ROOT / "schemas" / "systemc_python_model_contract_v1.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        claim_props = schema["properties"]["claim_boundary"]["properties"]

        self.assertEqual(claim_props["trusted_speedup"]["const"], False)
        self.assertEqual(claim_props["trusted_qe_correctness"]["const"], False)
        self.assertEqual(claim_props["requires_l4_full_flow_for_trusted_speedup"]["const"], True)
        self.assertEqual(
            schema["properties"]["numerical_validation"]["properties"]["correctness_scope"]["const"],
            "deterministic_sidecar_reference_contract_only",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
