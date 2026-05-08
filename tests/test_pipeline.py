#!/usr/bin/env python3

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from interfaces.validator import InterfaceValidator
from pipeline import ArtifactStore, Step2_Partition, Step3_Parameterize, Step4_FidelityConfig, Step5_Execute, Step6_Release, run_pipeline
from tests.test_interfaces import workload_profile


def install_architecture_evaluator_stub(monkeypatch):
    module = types.ModuleType("qe_architecture_family_quick_evaluator")

    class WorkloadProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Evaluation:
        def __init__(self, architecture, weighted_total, is_pareto, rationale):
            self.architecture = architecture
            self.weighted_total = weighted_total
            self.is_pareto = is_pareto
            self.rationale = rationale

    module.WorkloadProfile = WorkloadProfile
    module.get_architecture_specs = lambda: ["F1", "F4"]
    module.evaluate_architectures = lambda workload, specs: [
        Evaluation("F1", 0.4, False, "Baseline architecture"),
        Evaluation("F4", 0.9, True, "Tile architecture matches the dominant GEMM-heavy workload."),
    ]
    monkeypatch.setitem(sys.modules, module.__name__, module)


def test_end_to_end_pipeline_from_partition_to_release(monkeypatch, tmp_path):
    install_architecture_evaluator_stub(monkeypatch)
    store = ArtifactStore(tmp_path)
    validator = InterfaceValidator()
    current_hash = store.store(workload_profile())

    expected_schemas = [
        "architecture_spec_v1",
        "design_point_v1",
        "evaluation_config_v1",
        "evaluation_result_v1",
        "release_bundle_v1",
    ]

    for step_class, schema_name in zip(
        [Step2_Partition, Step3_Parameterize, Step4_FidelityConfig, Step5_Execute, Step6_Release],
        expected_schemas,
    ):
        current_hash, provenance = step_class(store, validator).execute(current_hash)
        artifact = store.load(current_hash)
        assert provenance.input_hash == artifact["provenance"]["input_hash"]
        validation = validator.validate(artifact, schema_name)
        assert validation.valid, validation.errors

    release = store.load(current_hash)
    assert release["schema_version"] == "release_bundle_v1"
    assert release["recommendation"]["confidence"] >= 0.8
    assert set(release["pareto_frontier"]).issubset(set(release["evaluation_results"]))


def test_run_pipeline_executes_single_step_and_persists_output(tmp_path):
    input_path = tmp_path / "design_point.json"
    input_path.write_text(__import__("json").dumps(__import__("tests.test_interfaces", fromlist=["design_point"]).design_point()))
    output_hash = run_pipeline(4, input_path, tmp_path / "artifacts")
    output_path = tmp_path / "artifacts" / f"{output_hash}.json"
    assert output_path.exists()
    artifact = __import__("json").loads(output_path.read_text())
    assert artifact["schema_version"] == "evaluation_config_v1"


def test_pipeline_rejects_invalid_step_number(tmp_path):
    input_path = tmp_path / "input.json"
    input_path.write_text('{"schema_version":"workload_profile_v1"}')
    try:
        run_pipeline(99, input_path, tmp_path / "artifacts")
    except ValueError as exc:
        assert "Invalid step number" in str(exc)
    else:
        raise AssertionError("run_pipeline accepted an invalid step number")
