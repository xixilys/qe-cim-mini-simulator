#!/usr/bin/env python3
"""Search-policy contracts for Step2 architecture/mapping exploration.

This module is intentionally domain-neutral.  It gives Step2 code a small,
testable interface for parameterized candidate generation without pretending
that a fixed candidate list is a real search system.  Policies must emit
candidate records with parameters, provenance, generation reasons, and explicit
promotion/blocker reasons so downstream Step3 admission can be audited.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from random import Random
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


STEP2_SCREENABLE = "step2_screenable"
STEP3_EVALUABLE = "step3_evaluable"
SIMULATION_ELIGIBLE = "simulation_eligible"
SIMULATION_BLOCKERS = "simulation_blockers"


@dataclass(frozen=True)
class CapabilityDecision:
    """Deterministic legality result for one component/query pair."""

    supported: bool
    blockers: Tuple[str, ...] = ()
    reasons: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "supported": self.supported,
            "blockers": list(self.blockers),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class ComponentCapability:
    """Domain-neutral component capability model.

    `op_semantics` are generic operation classes (for example `fft`, `gemm`,
    `reduction`); DFT-specific intent must be translated by a profile before it
    reaches this contract.
    """

    component_id: str
    op_semantics: Tuple[str, ...]
    dtypes: Tuple[str, ...] = ("fp64",)
    schedules: Tuple[str, ...] = ("batch", "streaming")
    placements: Tuple[str, ...] = ("host",)
    precision_policies: Tuple[str, ...] = ("strict",)

    def supports(
        self,
        op_semantics: str,
        dtype: str,
        schedule: str,
        placement: str,
        precision_policy: str,
    ) -> CapabilityDecision:
        blockers: List[str] = []
        reasons: List[str] = []
        checks = [
            (op_semantics in self.op_semantics, f"unsupported_op:{op_semantics}", f"op_supported:{op_semantics}"),
            (dtype.lower() in {item.lower() for item in self.dtypes}, f"unsupported_dtype:{dtype}", f"dtype_supported:{dtype}"),
            (schedule in self.schedules, f"unsupported_schedule:{schedule}", f"schedule_supported:{schedule}"),
            (placement in self.placements, f"unsupported_placement:{placement}", f"placement_supported:{placement}"),
            (
                precision_policy in self.precision_policies,
                f"unsupported_precision_policy:{precision_policy}",
                f"precision_policy_supported:{precision_policy}",
            ),
        ]
        for ok, blocker, reason in checks:
            if ok:
                reasons.append(reason)
            else:
                blockers.append(blocker)
        return CapabilityDecision(not blockers, tuple(blockers), tuple(reasons))


@dataclass(frozen=True)
class SearchProblem:
    """Serializable Step2 search input."""

    problem_id: str
    workload_run_id: str
    objective: str
    parameters: Mapping[str, Sequence[Any]]
    constraints: Mapping[str, Any] = field(default_factory=dict)
    seed_candidates: Sequence[Mapping[str, Any]] = field(default_factory=tuple)

    def parameter_grid(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        keys = list(self.parameters.keys())
        records: List[Dict[str, Any]] = []

        def visit(index: int, current: Dict[str, Any]) -> None:
            if limit is not None and len(records) >= limit:
                return
            if index == len(keys):
                records.append(dict(current))
                return
            key = keys[index]
            for value in self.parameters[key]:
                current[key] = value
                visit(index + 1, current)
            current.pop(key, None)

        visit(0, {})
        return records


@dataclass
class SearchCandidateRecord:
    """Auditable output from a SearchPolicy."""

    candidate_id: str
    parameters: Dict[str, Any]
    provenance: Dict[str, Any]
    generation_reason: str
    score: float = 0.0
    promotion_reasons: List[str] = field(default_factory=list)
    blocker_reasons: List[str] = field(default_factory=list)
    observed_metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def step2_screenable(self) -> bool:
        return bool(self.parameters) and not self.blocker_reasons

    @property
    def step3_evaluable(self) -> bool:
        return self.step2_screenable and "promoted_for_simulation" in self.promotion_reasons

    @property
    def simulation_eligible(self) -> bool:
        return self.step3_evaluable

    @property
    def simulation_blockers(self) -> List[str]:
        if self.simulation_eligible:
            return []
        return list(self.blocker_reasons or ["not_promoted_for_simulation"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "parameters": dict(self.parameters),
            "provenance": dict(self.provenance),
            "generation_reason": self.generation_reason,
            "score": float(self.score),
            "promotion_reasons": list(self.promotion_reasons),
            "blocker_reasons": list(self.blocker_reasons),
            STEP2_SCREENABLE: self.step2_screenable,
            STEP3_EVALUABLE: self.step3_evaluable,
            SIMULATION_ELIGIBLE: self.simulation_eligible,
            SIMULATION_BLOCKERS: self.simulation_blockers,
            "observed_metrics": dict(self.observed_metrics),
        }


@dataclass(frozen=True)
class SearchCheckpoint:
    policy_name: str
    problem_id: str
    proposed_count: int
    observed_count: int
    best_candidate_id: Optional[str]
    candidates: Tuple[SearchCandidateRecord, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "dse.step2.search_checkpoint.v1",
            "policy_name": self.policy_name,
            "problem_id": self.problem_id,
            "proposed_count": self.proposed_count,
            "observed_count": self.observed_count,
            "best_candidate_id": self.best_candidate_id,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


class SearchPolicy(ABC):
    """Minimal plugin interface for Step2 search policies."""

    policy_name: str

    @abstractmethod
    def propose(self, problem: SearchProblem, budget: int) -> List[SearchCandidateRecord]:
        """Return at most `budget` candidate records."""

    @abstractmethod
    def observe(self, candidate_id: str, metrics: Mapping[str, Any]) -> None:
        """Record feedback from Step3/Step4 or lower-fidelity screening."""

    @abstractmethod
    def checkpoint(self, problem: SearchProblem) -> SearchCheckpoint:
        """Return a replayable state snapshot."""


def _score_candidate(parameters: Mapping[str, Any], objective: str) -> float:
    score = 0.0
    for key, value in sorted(parameters.items()):
        if isinstance(value, bool):
            score += 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            score += float(value)
        else:
            score += (sum(ord(ch) for ch in f"{key}:{value}") % 100) / 100.0
    if "min" in objective.lower():
        return -score
    return score


class _BasePolicy(SearchPolicy):
    policy_name = "base"

    def __init__(self) -> None:
        self._proposed: Dict[str, SearchCandidateRecord] = {}
        self._observed_count = 0

    def observe(self, candidate_id: str, metrics: Mapping[str, Any]) -> None:
        record = self._proposed.get(candidate_id)
        if record is None:
            return
        record.observed_metrics.update(dict(metrics))
        if "promoted" in metrics:
            if metrics["promoted"] and "promoted_for_simulation" not in record.promotion_reasons:
                record.promotion_reasons.append("promoted_for_simulation")
            if not metrics["promoted"] and "feedback_rejected" not in record.blocker_reasons:
                record.blocker_reasons.append("feedback_rejected")
        self._observed_count += 1

    def checkpoint(self, problem: SearchProblem) -> SearchCheckpoint:
        candidates = tuple(self._proposed.values())
        best = max(candidates, key=lambda item: item.score, default=None)
        return SearchCheckpoint(
            policy_name=self.policy_name,
            problem_id=problem.problem_id,
            proposed_count=len(candidates),
            observed_count=self._observed_count,
            best_candidate_id=best.candidate_id if best else None,
            candidates=candidates,
        )

    def _record(self, problem: SearchProblem, index: int, parameters: Mapping[str, Any], reason: str) -> SearchCandidateRecord:
        blockers = [] if parameters else ["empty_parameter_record"]
        promotions = ["promoted_for_simulation"] if not blockers else []
        record = SearchCandidateRecord(
            candidate_id=f"{problem.problem_id}:{self.policy_name}:{index}",
            parameters=dict(parameters),
            provenance={
                "policy_name": self.policy_name,
                "problem_id": problem.problem_id,
                "workload_run_id": problem.workload_run_id,
                "candidate_index": index,
            },
            generation_reason=reason,
            score=_score_candidate(parameters, problem.objective),
            promotion_reasons=promotions,
            blocker_reasons=blockers,
        )
        self._proposed[record.candidate_id] = record
        return record


class SeededBeamSearchPolicy(_BasePolicy):
    """Deterministic beam policy that prefers explicit seeds, then grid records."""

    policy_name = "seeded_beam"

    def propose(self, problem: SearchProblem, budget: int) -> List[SearchCandidateRecord]:
        if budget <= 0:
            return []
        raw: List[Tuple[str, Mapping[str, Any]]] = []
        raw.extend(("seed_candidate", seed) for seed in problem.seed_candidates)
        raw.extend(("parameter_grid", item) for item in problem.parameter_grid(limit=max(budget * 2, budget)))
        scored = sorted(raw, key=lambda item: _score_candidate(item[1], problem.objective), reverse=True)
        return [self._record(problem, index, params, reason) for index, (reason, params) in enumerate(scored[:budget])]


class RandomBaselinePolicy(_BasePolicy):
    """Deterministic random baseline for comparing guided search policies."""

    policy_name = "random_baseline"

    def __init__(self, seed: int = 0) -> None:
        super().__init__()
        self._random = Random(seed)

    def propose(self, problem: SearchProblem, budget: int) -> List[SearchCandidateRecord]:
        grid = problem.parameter_grid()
        self._random.shuffle(grid)
        return [self._record(problem, index, params, "seeded_random_baseline") for index, params in enumerate(grid[:max(0, budget)])]


class BottleneckGuidedPolicy(_BasePolicy):
    """Simple guided policy that prioritizes records touching bottleneck keys."""

    policy_name = "bottleneck_guided"

    def __init__(self, bottleneck_keys: Iterable[str] = ()) -> None:
        super().__init__()
        self.bottleneck_keys = tuple(bottleneck_keys)

    def propose(self, problem: SearchProblem, budget: int) -> List[SearchCandidateRecord]:
        if budget <= 0:
            return []
        grid = problem.parameter_grid()

        def priority(params: Mapping[str, Any]) -> Tuple[int, float]:
            touched = sum(1 for key in self.bottleneck_keys if key in params)
            return touched, _score_candidate(params, problem.objective)

        ordered = sorted(grid, key=priority, reverse=True)
        return [self._record(problem, index, params, "bottleneck_guided_parameter_grid") for index, params in enumerate(ordered[:budget])]


__all__ = [
    "BottleneckGuidedPolicy",
    "CapabilityDecision",
    "ComponentCapability",
    "RandomBaselinePolicy",
    "SearchCandidateRecord",
    "SearchCheckpoint",
    "SearchPolicy",
    "SearchProblem",
    "SeededBeamSearchPolicy",
    "SIMULATION_BLOCKERS",
    "SIMULATION_ELIGIBLE",
    "STEP2_SCREENABLE",
    "STEP3_EVALUABLE",
]
