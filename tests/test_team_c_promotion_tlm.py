#!/usr/bin/env python3

import sys
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dse_v2.models.mid.python_tlm import Layer2Output, PythonTLM
from dse_v2.promotion.promotion_engine import PromotionEngine
from dse_v2.promotion.thresholds import PROMOTION_THRESHOLDS


def l1_result(**overrides):
    result = {
        "family": "F1",
        "fidelity_level_achieved": "L1",
        "status": "passed",
        "promotion_score": 0.72,
        "confidence": 0.60,
        "resource_legal": True,
    }
    result.update(overrides)
    return result


def l2_result(**overrides):
    result = {
        "family": "F1",
        "fidelity_level_achieved": "L2",
        "status": "passed",
        "promotion_score": 0.84,
        "confidence": 0.78,
        "uncertainty": {"mape_percent": 18.0},
    }
    result.update(overrides)
    return result


def test_thresholds_cover_all_architecture_families():
    assert set(PROMOTION_THRESHOLDS) == {"F1", "F2", "F3", "F4", "F5", "F6", "F7"}
    for thresholds in PROMOTION_THRESHOLDS.values():
        assert {"l1_to_l2", "l2_to_l3", "min_confidence_l1", "min_confidence_l2"} <= set(thresholds)


def test_l1_result_promotes_only_when_score_confidence_status_and_resources_pass():
    engine = PromotionEngine()

    decision = engine.evaluate(l1_result())

    assert decision.promote is True
    assert decision.from_layer == "L1"
    assert decision.to_layer == "L2"
    assert decision.reason == "eligible"

    assert engine.evaluate(l1_result(status="failed")).promote is False
    assert engine.evaluate(l1_result(promotion_score=0.69)).promote is False
    assert engine.evaluate(l1_result(confidence=0.54)).promote is False
    assert engine.evaluate(l1_result(resource_legal=False)).promote is False


def test_l2_result_promotes_to_l3_only_when_mape_and_thresholds_pass():
    engine = PromotionEngine()

    decision = engine.evaluate(l2_result())

    assert decision.promote is True
    assert decision.to_layer == "L3"
    assert engine.should_promote_to_l3(l2_result()) is True

    assert engine.should_promote_to_l3(l2_result(promotion_score=0.79)) is False
    assert engine.should_promote_to_l3(l2_result(confidence=0.74)) is False
    assert engine.should_promote_to_l3(l2_result(uncertainty={"mape_percent": 20.1})) is False


def test_promotion_engine_respects_layer_budget():
    engine = PromotionEngine(budgets={"L2": 0, "L3": 1})

    decision = engine.evaluate(l1_result())

    assert decision.promote is False
    assert decision.reason == "budget_exhausted"

    assert engine.evaluate(l2_result()).promote is True


def test_python_tlm_returns_layer2_output_for_design_point_and_workload():
    tlm = PythonTLM()
    output = tlm.run_episode(
        {"family": "F4", "n_gemm_tiles": 6, "n_eigen_tiles": 2, "tile_local_mem_kb": 1024},
        {"npw": 2945, "nkb": 144, "m": 16, "iterations": 8},
    )

    assert isinstance(output, Layer2Output)
    assert output.fidelity_level_achieved == "L2"
    assert output.status == "passed"
    assert output.metrics["latency_ms"] > 0
    assert output.metrics["power_w"] > 0
    assert 0.0 <= output.confidence <= 1.0
    assert output.to_dict()["promotion_score"] == output.promotion_score


def test_python_tlm_output_preserves_family_and_can_be_evaluated_directly():
    output = PythonTLM().run_episode(
        {"family": "F4", "n_gemm_tiles": 6, "n_eigen_tiles": 2, "tile_local_mem_kb": 1024},
        {"npw": 2945, "nkb": 144, "m": 16, "iterations": 8},
    )

    assert output.family == "F4"
    decision = PromotionEngine().evaluate(output)
    assert decision.from_layer == "L2"
    assert decision.threshold == PROMOTION_THRESHOLDS["F4"]["l2_to_l3"]


def test_python_tlm_reports_raw_overutilization_and_integer_sample_size():
    output = PythonTLM().run_episode(
        {"family": "F1", "n_gemm_tiles": 20, "n_eigen_tiles": 8, "tile_local_mem_kb": 4096},
        {"npw": 2945, "nkb": 144, "m": 16, "iterations": 8},
    )

    assert output.status == "failed"
    assert max(output.resource_utilization.values()) > 100.0
    assert isinstance(output.uncertainty["sample_size"], int)


def test_promotion_engine_source_remains_python39_parseable():
    source = (ROOT / "dse_v2" / "promotion" / "promotion_engine.py").read_text()
    ast.parse(source, feature_version=(3, 9))
