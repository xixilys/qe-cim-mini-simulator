#!/usr/bin/env python3

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from interfaces.validator import InterfaceValidator
from pipeline import ArtifactStore, Step3_Parameterize, Step4_FidelityConfig, Step5_Execute, Step6_Release
from tests.test_interfaces import architecture_spec, design_point, evaluation_config, evaluation_result


def execute_step(step_class, input_artifact, tmp_path):
    store = ArtifactStore(tmp_path)
    validator = InterfaceValidator()
    input_hash = store.store(input_artifact)
    step = step_class(store, validator)
    output_hash, provenance = step.execute(input_hash)
    return store, input_hash, output_hash, provenance


def test_artifact_store_is_content_addressed_and_idempotent(tmp_path):
    store = ArtifactStore(tmp_path)
    artifact = {"schema_version": "x", "payload": {"b": 2, "a": 1}}
    first_hash = store.store(artifact)
    second_hash = store.store(copy.deepcopy(artifact))
    assert first_hash == second_hash
    assert store.exists(first_hash)
    assert store.load(first_hash) == artifact


def test_artifact_hash_is_independent_of_dictionary_insertion_order(tmp_path):
    store = ArtifactStore(tmp_path)
    first = {"schema_version": "x", "a": 1, "b": 2}
    second = {"b": 2, "a": 1, "schema_version": "x"}
    assert store.store(first) == store.store(second)


def test_parameterize_step_does_not_mutate_input_artifact(tmp_path):
    input_artifact = architecture_spec()
    before = copy.deepcopy(input_artifact)
    execute_step(Step3_Parameterize, input_artifact, tmp_path)
    assert input_artifact == before


def test_fidelity_config_step_does_not_mutate_input_artifact(tmp_path):
    input_artifact = design_point()
    before = copy.deepcopy(input_artifact)
    execute_step(Step4_FidelityConfig, input_artifact, tmp_path)
    assert input_artifact == before


def test_execute_step_is_deterministic_for_same_evaluation_config(tmp_path):
    config = evaluation_config("L2")
    store = ArtifactStore(tmp_path)
    validator = InterfaceValidator()
    input_hash = store.store(config)
    step = Step5_Execute(store, validator)
    first_hash, _ = step.execute(input_hash)
    second_hash, _ = step.execute(input_hash)
    assert first_hash == second_hash
    assert store.load(first_hash) == store.load(second_hash)


def test_release_step_depends_only_on_evaluation_result_content(tmp_path):
    result = evaluation_result()
    store = ArtifactStore(tmp_path)
    validator = InterfaceValidator()
    input_hash = store.store(result)
    step = Step6_Release(store, validator)
    first_hash, _ = step.execute(input_hash)
    second_hash, _ = step.execute(input_hash)
    first = store.load(first_hash)
    second = store.load(second_hash)
    assert first == second


def test_step_provenance_links_to_exact_input_hash(tmp_path):
    store, input_hash, output_hash, provenance = execute_step(Step4_FidelityConfig, design_point(), tmp_path)
    output = store.load(output_hash)
    assert provenance.input_hash == input_hash
    assert output["provenance"]["input_hash"] == input_hash
