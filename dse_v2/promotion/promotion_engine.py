#!/usr/bin/env python3

from dataclasses import asdict, dataclass, field, is_dataclass
import logging
from typing import Any, Dict, Iterable, Mapping, Optional

from .thresholds import DEFAULT_FAMILY, MAX_L2_TO_L3_MAPE_PERCENT, PROMOTION_THRESHOLDS


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromotionDecision:
    from_layer: str
    to_layer: Optional[str]
    promote: bool
    reason: str
    promotion_score: float
    confidence: float
    threshold: float
    details: Dict[str, Any] = field(default_factory=dict)


class PromotionEngine:
    def __init__(
        self,
        thresholds: Optional[Mapping[str, Mapping[str, float]]] = None,
        budgets: Optional[Mapping[str, int]] = None,
        pareto_frontier: Optional[Iterable[Mapping[str, Any]]] = None,
    ):
        self.thresholds = thresholds or PROMOTION_THRESHOLDS
        self.budgets = dict(budgets or {})
        self.pareto_frontier = list(pareto_frontier or [])

    def evaluate(self, layer_result: Any) -> PromotionDecision:
        result = self._as_mapping(layer_result)
        layer = str(result.get('fidelity_level_achieved') or result.get('layer') or result.get('fidelity_level') or 'L1').upper()
        if layer == 'L2':
            return self._evaluate_l2_to_l3(result)
        return self._evaluate_l1_to_l2(result)

    def should_promote_to_l3(self, layer2_result: Any) -> bool:
        result = self._as_mapping(layer2_result)
        if bool(result.get('is_projection', False)):
            LOGGER.warning('L3 promotion request is based on projection_only data; requiring confidence >= 0.90')
        return self._evaluate_l2_to_l3(result, consume_budget=False).promote

    def calculate_promotion_score(self, layer_result: Mapping[str, Any]) -> float:
        if 'promotion_score' in layer_result and layer_result['promotion_score'] is not None:
            return float(layer_result['promotion_score'])

        metrics = layer_result.get('metrics', {}) or {}
        confidence = self._confidence(layer_result)
        accuracy = float(metrics.get('accuracy_vs_reference', confidence))
        efficiency = float(metrics.get('energy_efficiency_gops_per_w', 0.0)) / 10.0
        resource_margin = self._resource_margin(layer_result)
        return max(0.0, min(1.0, 0.45 * accuracy + 0.25 * min(efficiency, 1.0) + 0.20 * resource_margin + 0.10 * confidence))

    def _evaluate_l1_to_l2(self, result: Mapping[str, Any]) -> PromotionDecision:
        family = self._family(result)
        threshold = float(self.thresholds[family]['l1_to_l2'])
        min_confidence = float(self.thresholds[family]['min_confidence_l1'])
        score = self.calculate_promotion_score(result)
        confidence = self._confidence(result)
        checks = {
            'status_passed': result.get('status') == 'passed',
            'resource_legal': self._resource_legal(result),
            'score_passed': score >= threshold,
            'confidence_passed': confidence >= min_confidence,
            'pareto_passed': self._pareto_passed(result),
        }
        return self._decision('L1', 'L2', score, confidence, threshold, checks, details={'pareto_frontier_size': len(self._frontier_for(result))})

    def _evaluate_l2_to_l3(self, result: Mapping[str, Any], consume_budget: bool = True) -> PromotionDecision:
        family = self._family(result)
        threshold = float(self.thresholds[family]['l2_to_l3'])
        min_confidence = float(self.thresholds[family]['min_confidence_l2'])
        is_projection = bool(result.get('is_projection', False))
        if is_projection:
            min_confidence = max(min_confidence, 0.90)
        score = self.calculate_promotion_score(result)
        confidence = self._confidence(result)
        mape = self._mape(result)
        status = str(result.get('status', ''))
        status_passed = status in {'passed', 'projection_only'}
        checks = {
            'status_passed': status_passed,
            'score_passed': score >= threshold,
            'confidence_passed': confidence >= min_confidence,
            'mape_passed': mape <= MAX_L2_TO_L3_MAPE_PERCENT,
            'pareto_passed': self._pareto_passed(result),
        }
        if is_projection:
            LOGGER.warning('Evaluating projection_only L3 promotion for family %s with confidence %.3f (threshold %.3f)', family, confidence, min_confidence)
        return self._decision('L2', 'L3', score, confidence, threshold, checks, consume_budget=consume_budget, details={'mape_percent': mape, 'pareto_frontier_size': len(self._frontier_for(result)), 'is_projection': is_projection, 'projection_uncertainty': float(result.get('projection_uncertainty', 0.0))})

    def _decision(
        self,
        from_layer: str,
        to_layer: str,
        score: float,
        confidence: float,
        threshold: float,
        checks: Dict[str, bool],
        consume_budget: bool = True,
        details: Optional[Dict[str, Any]] = None,
    ) -> PromotionDecision:
        merged_details = dict(details or {})
        merged_details.update(checks)
        if not self._has_budget(to_layer):
            merged_details['budget_remaining'] = self.budgets.get(to_layer, 1)
            return PromotionDecision(from_layer, None, False, 'budget_exhausted', score, confidence, threshold, merged_details)
        if not all(checks.values()):
            failed = next(name for name, passed in checks.items() if not passed)
            return PromotionDecision(from_layer, None, False, failed, score, confidence, threshold, merged_details)
        if consume_budget:
            self._consume_budget(to_layer)
        merged_details['budget_remaining'] = self.budgets.get(to_layer, 1)
        return PromotionDecision(from_layer, to_layer, True, 'eligible', score, confidence, threshold, merged_details)

    def _family(self, result: Mapping[str, Any]) -> str:
        family = str(result.get('family') or result.get('selected_family') or DEFAULT_FAMILY)
        return family if family in self.thresholds else DEFAULT_FAMILY

    def _as_mapping(self, result: Any) -> Mapping[str, Any]:
        if isinstance(result, Mapping):
            return result
        if is_dataclass(result):
            return asdict(result)
        if hasattr(result, 'to_dict'):
            return result.to_dict()
        raise TypeError('layer_result must be a mapping, dataclass, or expose to_dict()')

    def _confidence(self, result: Mapping[str, Any]) -> float:
        if 'confidence' in result and result['confidence'] is not None:
            return float(result['confidence'])
        uncertainty = result.get('uncertainty', {}) or {}
        return float(uncertainty.get('confidence_level', 0.0))

    def _mape(self, result: Mapping[str, Any]) -> float:
        uncertainty = result.get('uncertainty', {}) or {}
        return float(result.get('mape_percent', uncertainty.get('mape_percent', 100.0)))

    def _resource_legal(self, result: Mapping[str, Any]) -> bool:
        if result.get('resource_legal') is False:
            return False
        resource_limits = result.get('resource_limits', {}) or {}
        if resource_limits:
            for value in resource_limits.values():
                if isinstance(value, (int, float)) and value < 0.0:
                    return False
        utilization = result.get('resource_utilization', {}) or {}
        return all(float(value) <= 100.0 for value in utilization.values() if isinstance(value, (int, float)))

    def _resource_margin(self, result: Mapping[str, Any]) -> float:
        utilization = result.get('resource_utilization', {}) or {}
        numeric = [float(value) for value in utilization.values() if isinstance(value, (int, float))]
        if not numeric:
            return 0.5
        return max(0.0, min(1.0, 1.0 - max(numeric) / 100.0))

    def _frontier_for(self, result: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
        frontier = result.get('pareto_frontier') or result.get('frontier') or self.pareto_frontier
        if isinstance(frontier, Mapping):
            return [frontier]
        return frontier or []

    def _pareto_passed(self, result: Mapping[str, Any]) -> bool:
        frontier = list(self._frontier_for(result))
        if not frontier:
            return True
        current = self._pareto_objectives(result)
        if not current:
            return True
        for candidate in frontier:
            candidate_obj = self._pareto_objectives(candidate)
            if candidate_obj and self._dominates(candidate_obj, current):
                return False
        return True

    def _pareto_objectives(self, result: Mapping[str, Any]) -> Dict[str, float]:
        metrics = result.get('metrics', {}) or {}
        objectives: Dict[str, float] = {}
        if isinstance(metrics, Mapping):
            for key in ('latency_ms', 'power_w', 'area_mm2'):
                value = metrics.get(key)
                if isinstance(value, (int, float)):
                    objectives[key] = float(value)
            for key in ('throughput_gops', 'energy_efficiency_gops_per_w', 'accuracy_vs_reference'):
                value = metrics.get(key)
                if isinstance(value, (int, float)):
                    objectives[key] = float(value)
        return objectives

    def _dominates(self, candidate: Mapping[str, float], current: Mapping[str, float]) -> bool:
        directions = {
            'latency_ms': 'min',
            'power_w': 'min',
            'area_mm2': 'min',
            'throughput_gops': 'max',
            'energy_efficiency_gops_per_w': 'max',
            'accuracy_vs_reference': 'max',
        }
        comparable = [key for key in current.keys() if key in candidate and key in directions]
        if not comparable:
            return False
        better_or_equal = True
        strictly_better = False
        for key in comparable:
            direction = directions[key]
            cand = float(candidate[key])
            cur = float(current[key])
            if direction == 'min':
                if cand > cur:
                    better_or_equal = False
                    break
                if cand < cur:
                    strictly_better = True
            else:
                if cand < cur:
                    better_or_equal = False
                    break
                if cand > cur:
                    strictly_better = True
        return better_or_equal and strictly_better

    def _has_budget(self, target_layer: str) -> bool:
        return self.budgets.get(target_layer, 1) > 0

    def _consume_budget(self, target_layer: str) -> None:
        if target_layer in self.budgets:
            self.budgets[target_layer] -= 1
