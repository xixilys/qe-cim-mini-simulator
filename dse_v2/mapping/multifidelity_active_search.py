#!/usr/bin/env python3
"""Domain-neutral active multi-fidelity search acquisition.

The module owns the algorithmic Step2 decision of which candidates deserve the
next expensive observation.  Workload adapters may translate their candidate
rows into this contract, but domain-specific fields must not be required here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Mapping, Sequence


DEFAULT_OBJECTIVE_NAMES = (
    "latency_ms",
    "energy_mj",
    "resource_pressure",
    "data_movement_mb",
)


@dataclass(frozen=True)
class ActiveSearchCandidate:
    """A candidate projected into a domain-neutral acquisition space.

    All objectives are minimized.  `constraints["feasibility"]`, when present,
    is interpreted as a probability in [0, 1].  Other constraints stay as
    numeric descriptors for policy-specific feasibility scoring.
    """

    candidate_id: str
    objectives: Mapping[str, float]
    constraints: Mapping[str, float] = field(default_factory=dict)
    uncertainty: float = 0.0
    evaluation_cost: float = 1.0
    risk_axes: Mapping[str, float] = field(default_factory=dict)
    design_key: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "objectives": {key: float(value) for key, value in self.objectives.items()},
            "constraints": {key: float(value) for key, value in self.constraints.items()},
            "uncertainty": float(self.uncertainty),
            "evaluation_cost": float(self.evaluation_cost),
            "risk_axes": {key: float(value) for key, value in self.risk_axes.items()},
            "design_key": self.design_key,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ActiveSearchObservation:
    """Previously measured candidate feedback used to calibrate selection."""

    candidate_id: str
    fidelity: str
    objectives: Mapping[str, float]
    feasible: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "fidelity": self.fidelity,
            "objectives": {key: float(value) for key, value in self.objectives.items()},
            "feasible": bool(self.feasible),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ActiveSearchFidelity:
    """A domain-neutral evaluation action available to the active search.

    The candidate contract describes what may be evaluated; this contract
    describes where the next budget unit may be spent.  Fidelity names stay
    opaque to the generic policy so adapters can map them to SystemC, gem5,
    HLS, RTL, or other tool levels without leaking domain facts into Step2.
    """

    fidelity: str
    evaluation_cost: float = 1.0
    information_gain: float = 1.0
    uncertainty_reduction: float = 0.0
    calibration_value: float = 0.0
    feasibility: float = 1.0
    requires_observed_fidelities: Sequence[str] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fidelity": self.fidelity,
            "evaluation_cost": float(self.evaluation_cost),
            "information_gain": float(self.information_gain),
            "uncertainty_reduction": float(self.uncertainty_reduction),
            "calibration_value": float(self.calibration_value),
            "feasibility": float(self.feasibility),
            "requires_observed_fidelities": [
                str(item) for item in self.requires_observed_fidelities
            ],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AcquisitionScore:
    """Acquisition details for a candidate."""

    policy: str
    score: float
    components: Mapping[str, float]
    equation: str
    frontier_source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy": self.policy,
            "score": float(self.score),
            "components": {key: float(value) for key, value in self.components.items()},
            "equation": self.equation,
            "frontier_source": self.frontier_source,
        }


@dataclass(frozen=True)
class ActiveSearchActionSelection:
    """Selected candidate and the fidelity level to evaluate next."""

    candidate: ActiveSearchCandidate
    fidelity_action: ActiveSearchFidelity
    acquisition: AcquisitionScore
    action_score: float
    components: Mapping[str, float]

    @property
    def candidate_id(self) -> str:
        return self.candidate.candidate_id

    @property
    def fidelity(self) -> str:
        return self.fidelity_action.fidelity

    @property
    def action_id(self) -> str:
        return f"{self.candidate_id}::{self.fidelity}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.candidate.to_dict(),
            "fidelity": self.fidelity,
            "fidelity_action": self.fidelity_action.to_dict(),
            "action_id": self.action_id,
            "action_score": float(self.action_score),
            "action_components": {
                key: float(value) for key, value in self.components.items()
            },
            "acquisition": self.acquisition.to_dict(),
        }


@dataclass(frozen=True)
class ActiveSearchSelection:
    """Selected candidate plus its acquisition explanation."""

    candidate: ActiveSearchCandidate
    acquisition: AcquisitionScore

    @property
    def candidate_id(self) -> str:
        return self.candidate.candidate_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.candidate.to_dict(),
            "acquisition": self.acquisition.to_dict(),
        }


class MultiFidelityActiveSearchPolicy:
    """Constrained active Pareto acquisition for budgeted DSE.

    This is a deterministic, lightweight approximation to constrained EHVI.  It
    intentionally avoids depending on a domain-specific oracle or a full Bayesian
    optimization stack.  The policy rewards Pareto improvement against the
    current high-fidelity frontier, uncertainty, workflow-risk coverage, and
    design diversity, then discounts infeasible or expensive candidates.  The
    primary ranking signal is a cost-normalized constrained hypervolume proxy;
    weighted side terms are retained for exploration tie-breaking and backward
    compatible ablations.
    """

    policy_id = "wamf_constrained_active_pareto"
    equation = "maximize_cost_aware_constrained_ehvi_proxy_plus_exploration_terms"

    def __init__(
        self,
        *,
        objective_names: Sequence[str] = DEFAULT_OBJECTIVE_NAMES,
        scalar_quality_objective_name: str | None = None,
        resource_pressure_limit: float = 0.90,
        weights: Mapping[str, float] | None = None,
    ) -> None:
        self.objective_names = tuple(str(name) for name in objective_names)
        self.scalar_quality_objective_name = (
            str(scalar_quality_objective_name)
            if scalar_quality_objective_name is not None
            else ""
        )
        self.resource_pressure_limit = float(resource_pressure_limit)
        defaults = {
            "pareto_gain": 1.00,
            "uncertainty": 0.18,
            "workflow_risk_coverage": 0.16,
            "design_diversity": 0.08,
            "evaluation_cost": 0.18,
            "cost_normalized_hv_gain": 1.00,
            "scalar_quality_prior": 0.85,
            "scalar_quality_rank_prior": 0.55,
        }
        if weights:
            defaults.update({str(key): float(value) for key, value in weights.items()})
        self.weights = defaults

    def select(
        self,
        candidates: Sequence[ActiveSearchCandidate],
        *,
        observations: Sequence[ActiveSearchObservation] | None = None,
        budget: int = 1,
    ) -> List[ActiveSearchSelection]:
        observation_rows = [row for row in observations or [] if row.feasible]
        observed_ids = {row.candidate_id for row in observations or []}
        scalar_quality_calibration = self._scalar_quality_calibration_model(observation_rows)
        frontier = self._frontier_from_observations(observation_rows)
        if not frontier:
            frontier = self._frontier_from_candidates(candidates)
            frontier_source = "cheap_model_candidate_frontier"
        else:
            frontier_source = "observed_high_fidelity_frontier"

        remaining = [
            candidate for candidate in candidates
            if candidate.candidate_id not in observed_ids
        ]
        objective_calibration = self._objective_calibration_model(observation_rows)
        scalar_quality_context = self._scalar_quality_context(
            remaining,
            frontier,
            scalar_quality_calibration,
        )
        chosen: List[ActiveSearchSelection] = []
        selected_design_keys: set[str] = set()
        if self.scalar_quality_objective_name and not observation_rows:
            anchor = self._scalar_quality_anchor_selection(
                remaining,
                frontier=frontier,
                frontier_source=frontier_source,
                scalar_quality_calibration=scalar_quality_calibration,
                scalar_quality_context=scalar_quality_context,
                objective_calibration=objective_calibration,
            )
            if anchor is not None:
                chosen.append(anchor)
                remaining = [
                    candidate for candidate in remaining
                    if candidate.candidate_id != anchor.candidate_id
                ]
                if anchor.candidate.design_key:
                    selected_design_keys.add(anchor.candidate.design_key)
        for _ in range(max(0, int(budget))):
            if len(chosen) >= max(0, int(budget)):
                break
            scored: List[ActiveSearchSelection] = []
            for candidate in remaining:
                acquisition = self._score_candidate(
                    candidate,
                    frontier=frontier,
                    frontier_source=frontier_source,
                    selected_design_keys=selected_design_keys,
                    scalar_quality_calibration=scalar_quality_calibration,
                    scalar_quality_context=scalar_quality_context,
                    objective_calibration=objective_calibration,
                )
                if acquisition.components["constrained_pareto_gain"] <= 0.0:
                    continue
                if acquisition.components["feasibility_probability"] <= 0.0:
                    continue
                scored.append(ActiveSearchSelection(candidate=candidate, acquisition=acquisition))
            if not scored:
                if not chosen:
                    scored = [
                        ActiveSearchSelection(
                            candidate=candidate,
                            acquisition=self._score_candidate(
                                candidate,
                                frontier=frontier,
                                frontier_source=frontier_source,
                                selected_design_keys=selected_design_keys,
                                scalar_quality_calibration=scalar_quality_calibration,
                                scalar_quality_context=scalar_quality_context,
                                objective_calibration=objective_calibration,
                            ),
                        )
                        for candidate in remaining
                    ]
                    scored = [
                        row for row in scored
                        if row.acquisition.score > 0.0
                        and row.acquisition.components["feasibility_probability"] > 0.0
                    ]
                    if scored:
                        scored.sort(key=lambda row: (-row.acquisition.score, row.candidate_id))
                        row = scored[0]
                        chosen.append(row)
                        remaining = [
                            candidate for candidate in remaining
                            if candidate.candidate_id != row.candidate_id
                        ]
                        if row.candidate.design_key:
                            selected_design_keys.add(row.candidate.design_key)
                        continue
                break
            scored.sort(key=lambda row: (-row.acquisition.score, row.candidate_id))
            row = scored[0]
            if len(chosen) >= max(0, int(budget)):
                break
            chosen.append(row)
            remaining = [
                candidate for candidate in remaining
                if candidate.candidate_id != row.candidate_id
            ]
            if row.candidate.design_key:
                selected_design_keys.add(row.candidate.design_key)
        return chosen

    def _scalar_quality_anchor_selection(
        self,
        candidates: Sequence[ActiveSearchCandidate],
        *,
        frontier: Sequence[Mapping[str, float]],
        frontier_source: str,
        scalar_quality_calibration: Mapping[str, Any] | None = None,
        scalar_quality_context: Mapping[str, Any] | None = None,
        objective_calibration: Mapping[str, Any] | None = None,
    ) -> ActiveSearchSelection | None:
        name = self.scalar_quality_objective_name
        if not name:
            return None
        feasible: List[ActiveSearchCandidate] = []
        for candidate in candidates:
            value = candidate.objectives.get(name)
            if value is None:
                continue
            numeric = float(value)
            if not math.isfinite(numeric) or numeric <= 0.0:
                continue
            if self._feasibility_probability(candidate) <= 0.0:
                continue
            feasible.append(candidate)
        if not feasible:
            return None
        candidate = min(
            feasible,
            key=lambda row: (
                float(row.objectives.get(name, float("inf"))),
                self._evaluation_cost(row),
                row.candidate_id,
            ),
        )
        acquisition = self._score_candidate(
            candidate,
            frontier=frontier,
            frontier_source=frontier_source,
            selected_design_keys=set(),
            scalar_quality_calibration=scalar_quality_calibration,
            scalar_quality_context=scalar_quality_context,
            objective_calibration=objective_calibration,
        )
        components = dict(acquisition.components)
        components["scalar_quality_anchor"] = 1.0
        components["scalar_quality_anchor_objective"] = float(candidate.objectives.get(name, 0.0))
        anchored = AcquisitionScore(
            policy=acquisition.policy,
            score=max(acquisition.score, self.weights["scalar_quality_prior"] + components["scalar_quality_prior"]),
            components=components,
            equation=acquisition.equation,
            frontier_source=acquisition.frontier_source,
        )
        return ActiveSearchSelection(candidate=candidate, acquisition=anchored)

    def selection_report(
        self,
        candidates: Sequence[ActiveSearchCandidate],
        *,
        observations: Sequence[ActiveSearchObservation] | None = None,
        budget: int = 1,
    ) -> Dict[str, Any]:
        selected = self.select(candidates, observations=observations, budget=budget)
        reference_point = self._hypervolume_reference_point(candidates, observations or [])
        return {
            "schema_version": "dse.multifidelity_active_search.selection.v1",
            "policy_id": self.policy_id,
            "candidate_count": len(candidates),
            "observation_count": len(observations or []),
            "budget": max(0, int(budget)),
            "selected_candidate_ids": [row.candidate_id for row in selected],
            "selection": [row.to_dict() for row in selected],
            "algorithm_contract": {
                "domain_neutral": True,
                "candidate_objectives_minimized": list(self.objective_names),
                "acquisition_family": "cost_aware_constrained_ehvi_proxy",
                "evidence_role": "feedback_calibration_not_search_objective",
                "scoring_equation": self.equation,
                "selection_scope": "global_candidate_set",
                "batch_rescoring": True,
                "cost_normalized_selection": True,
                "scalar_quality_objective_name": self.scalar_quality_objective_name,
                "prior_preserving_selection": bool(self.scalar_quality_objective_name),
                "multi_objective_residual_calibration": True,
                "hypervolume_reference_point": reference_point,
                "feedback_closed_loop": bool(observations),
            },
        }

    def select_actions(
        self,
        candidates: Sequence[ActiveSearchCandidate],
        *,
        fidelities: Sequence[ActiveSearchFidelity],
        observations: Sequence[ActiveSearchObservation] | None = None,
        action_budget: int = 1,
        cost_budget: float | None = None,
    ) -> List[ActiveSearchActionSelection]:
        """Select candidate/fidelity actions under an evaluation-cost budget."""

        observation_rows = [row for row in observations or [] if row.feasible]
        scalar_quality_calibration = self._scalar_quality_calibration_model(observation_rows)
        objective_calibration = self._objective_calibration_model(observation_rows)
        frontier = self._frontier_from_observations(observation_rows)
        if not frontier:
            frontier = self._frontier_from_candidates(candidates)
            frontier_source = "cheap_model_candidate_frontier"
        else:
            frontier_source = "observed_high_fidelity_frontier"

        observed_fidelities = self._observed_fidelities_by_candidate(observations or [])
        remaining_budget = (
            float(cost_budget)
            if cost_budget is not None and math.isfinite(float(cost_budget))
            else float("inf")
        )
        selected: List[ActiveSearchActionSelection] = []
        selected_action_ids: set[str] = set()
        selected_design_keys: set[str] = set()
        scalar_quality_context = self._scalar_quality_context(
            candidates,
            frontier,
            scalar_quality_calibration,
        )
        max_actions = max(0, int(action_budget))
        for _ in range(max_actions):
            scored: List[ActiveSearchActionSelection] = []
            for candidate in candidates:
                candidate_score = self._score_candidate(
                    candidate,
                    frontier=frontier,
                    frontier_source=frontier_source,
                    selected_design_keys=selected_design_keys,
                    scalar_quality_calibration=scalar_quality_calibration,
                    scalar_quality_context=scalar_quality_context,
                    objective_calibration=objective_calibration,
                )
                if candidate_score.components["feasibility_probability"] <= 0.0:
                    continue
                for fidelity in fidelities:
                    action = self._score_action(
                        candidate,
                        fidelity,
                        candidate_score,
                        observed_fidelities=observed_fidelities,
                        selected_action_ids=selected_action_ids,
                    )
                    if action.action_id in selected_action_ids:
                        continue
                    if action.components["already_observed_action"] > 0.0:
                        continue
                    if action.components["prerequisites_satisfied"] <= 0.0:
                        continue
                    if action.components["action_feasibility"] <= 0.0:
                        continue
                    if action.components["action_cost"] > remaining_budget:
                        continue
                    if action.action_score <= 0.0:
                        continue
                    scored.append(action)
            if not scored:
                break
            scored.sort(key=lambda row: (-row.action_score, row.components["action_cost"], row.action_id))
            chosen = scored[0]
            selected.append(chosen)
            selected_action_ids.add(chosen.action_id)
            if chosen.candidate.design_key:
                selected_design_keys.add(chosen.candidate.design_key)
            if math.isfinite(remaining_budget):
                remaining_budget -= chosen.components["action_cost"]
                if remaining_budget <= 0.0:
                    break
        return selected

    def action_selection_report(
        self,
        candidates: Sequence[ActiveSearchCandidate],
        *,
        fidelities: Sequence[ActiveSearchFidelity],
        observations: Sequence[ActiveSearchObservation] | None = None,
        action_budget: int = 1,
        cost_budget: float | None = None,
    ) -> Dict[str, Any]:
        selected = self.select_actions(
            candidates,
            fidelities=fidelities,
            observations=observations,
            action_budget=action_budget,
            cost_budget=cost_budget,
        )
        reference_point = self._hypervolume_reference_point(candidates, observations or [])
        resolved_cost_budget = (
            float(cost_budget)
            if cost_budget is not None and math.isfinite(float(cost_budget))
            else None
        )
        return {
            "schema_version": "dse.multifidelity_active_search.action_selection.v1",
            "policy_id": self.policy_id,
            "candidate_count": len(candidates),
            "fidelity_count": len(fidelities),
            "observation_count": len(observations or []),
            "action_budget": max(0, int(action_budget)),
            "cost_budget": resolved_cost_budget,
            "selected_action_ids": [row.action_id for row in selected],
            "selected_candidate_ids": [row.candidate_id for row in selected],
            "selected_candidate_fidelity_pairs": [
                {"candidate_id": row.candidate_id, "fidelity": row.fidelity}
                for row in selected
            ],
            "selection": [row.to_dict() for row in selected],
            "algorithm_contract": {
                "domain_neutral": True,
                "candidate_objectives_minimized": list(self.objective_names),
                "acquisition_family": "cost_aware_constrained_ehvi_proxy",
                "evidence_role": "feedback_calibration_not_search_objective",
                "scoring_equation": self.equation,
                "selection_scope": "joint_candidate_fidelity_action_space",
                "batch_rescoring": True,
                "cost_normalized_selection": True,
                "scalar_quality_objective_name": self.scalar_quality_objective_name,
                "prior_preserving_selection": bool(self.scalar_quality_objective_name),
                "multi_objective_residual_calibration": True,
                "fidelity_cost_aware_selection": True,
                "chooses_candidate_and_next_fidelity": True,
                "hypervolume_reference_point": reference_point,
                "feedback_closed_loop": bool(observations),
            },
        }

    def _score_candidate(
        self,
        candidate: ActiveSearchCandidate,
        *,
        frontier: Sequence[Mapping[str, float]],
        frontier_source: str,
        selected_design_keys: set[str],
        scalar_quality_calibration: Mapping[str, Any] | None = None,
        scalar_quality_context: Mapping[str, Any] | None = None,
        objective_calibration: Mapping[str, Any] | None = None,
    ) -> AcquisitionScore:
        calibrated_objectives = self._calibrated_candidate_objectives(
            candidate,
            objective_calibration,
        )
        pareto_gain = self._constrained_pareto_gain(
            candidate,
            frontier,
            candidate_objectives=calibrated_objectives["objectives"],
        )
        feasibility = self._feasibility_probability(candidate)
        uncertainty = _clamp(float(candidate.uncertainty), 0.0, 1.0)
        workflow_risk = self._workflow_risk_coverage(candidate)
        diversity = 0.0 if candidate.design_key and candidate.design_key in selected_design_keys else 1.0
        cost_penalty = -self._normalized_cost(candidate)
        exclusive_hv_gain = self._exclusive_hypervolume_gain(
            candidate,
            frontier,
            candidate_objectives=calibrated_objectives["objectives"],
        )
        feasibility_weighted_hv_gain = exclusive_hv_gain * feasibility
        evaluation_cost = self._evaluation_cost(candidate)
        cost_normalized_hv_gain = feasibility_weighted_hv_gain / evaluation_cost
        scalar_quality_prior, scalar_quality_objective = self._scalar_quality_prior(
            candidate,
            frontier,
            scalar_quality_calibration=scalar_quality_calibration,
            scalar_quality_context=scalar_quality_context,
        )
        scalar_quality_calibrated = self._calibrated_scalar_quality_objective(
            candidate,
            scalar_quality_calibration,
        )
        scalar_quality_rank = self._scalar_quality_rank_prior(
            scalar_quality_calibrated["calibrated_value"],
            scalar_quality_context,
        )
        components = {
            "constrained_pareto_gain": pareto_gain * feasibility,
            "raw_pareto_gain": pareto_gain,
            "exclusive_hypervolume_gain": exclusive_hv_gain,
            "feasibility_weighted_hv_gain": feasibility_weighted_hv_gain,
            "cost_normalized_hv_gain": cost_normalized_hv_gain,
            "feasibility_probability": feasibility,
            "uncertainty": uncertainty,
            "workflow_risk_coverage": workflow_risk,
            "design_diversity": diversity,
            "evaluation_cost": evaluation_cost,
            "evaluation_cost_penalty": cost_penalty,
            "scalar_quality_prior": scalar_quality_prior,
            "scalar_quality_objective": scalar_quality_objective,
            "calibrated_scalar_quality_objective": scalar_quality_calibrated["calibrated_value"],
            "scalar_quality_log_residual_mean": scalar_quality_calibrated["log_residual_mean"],
            "scalar_quality_residual_similarity": scalar_quality_calibrated["similarity"],
            "scalar_quality_residual_sample_count": scalar_quality_calibrated["sample_count"],
            "scalar_quality_rank_prior": scalar_quality_rank["rank_prior"],
            "scalar_quality_topk_probability": scalar_quality_rank["topk_probability"],
            "scalar_quality_rank_index": scalar_quality_rank["rank_index"],
            "scalar_quality_pool_size": scalar_quality_rank["pool_size"],
        }
        components.update(self._objective_calibration_components(calibrated_objectives))
        score = (
            self.weights["cost_normalized_hv_gain"] * cost_normalized_hv_gain
            + (
                self.weights["scalar_quality_prior"] * scalar_quality_prior
                if self.scalar_quality_objective_name
                else 0.0
            )
            + (
                self.weights["scalar_quality_rank_prior"] * scalar_quality_rank["rank_prior"]
                if self.scalar_quality_objective_name
                else 0.0
            )
            + self.weights["uncertainty"] * uncertainty
            + self.weights["workflow_risk_coverage"] * workflow_risk
            + self.weights["design_diversity"] * diversity
        )
        if cost_normalized_hv_gain <= 0.0:
            score += (
                self.weights["pareto_gain"] * components["constrained_pareto_gain"]
                + self.weights["evaluation_cost"] * cost_penalty
            )
        return AcquisitionScore(
            policy=self.policy_id,
            score=max(0.0, float(score)),
            components=components,
            equation=self.equation,
            frontier_source=frontier_source,
        )

    def _scalar_quality_prior(
        self,
        candidate: ActiveSearchCandidate,
        frontier: Sequence[Mapping[str, float]],
        *,
        scalar_quality_calibration: Mapping[str, Any] | None = None,
        scalar_quality_context: Mapping[str, Any] | None = None,
    ) -> tuple[float, float]:
        name = self.scalar_quality_objective_name
        if not name:
            return 0.0, 0.0
        raw_value = candidate.objectives.get(name)
        if raw_value is None:
            return 0.0, 0.0
        value = float(raw_value)
        if not math.isfinite(value) or value <= 0.0:
            return 0.0, value if math.isfinite(value) else 0.0
        calibration = self._calibrated_scalar_quality_objective(
            candidate,
            scalar_quality_calibration,
        )
        value = calibration["calibrated_value"]
        baseline_values = self._scalar_quality_baseline_values(
            frontier,
            scalar_quality_context,
        )
        if not baseline_values:
            return 1.0, value
        best = min(baseline_values)
        worst = max(baseline_values)
        if worst <= best:
            return _clamp(best / max(best + value, 1.0e-9), 0.0, 1.0), value
        return _clamp((worst - value) / (worst - best), 0.0, 1.0), value

    def _scalar_quality_context(
        self,
        candidates: Sequence[ActiveSearchCandidate],
        frontier: Sequence[Mapping[str, float]],
        scalar_quality_calibration: Mapping[str, Any] | None,
    ) -> Dict[str, Any]:
        name = self.scalar_quality_objective_name
        if not name:
            return {"baseline_values": []}
        values = [
            self._calibrated_scalar_quality_objective(candidate, scalar_quality_calibration)[
                "calibrated_value"
            ]
            for candidate in candidates
        ]
        values.extend(
            float(row.get(name))
            for row in frontier
            if row.get(name) is not None
            and math.isfinite(float(row.get(name)))
            and float(row.get(name)) > 0.0
        )
        values = [value for value in values if math.isfinite(float(value)) and float(value) > 0.0]
        return {"baseline_values": values}

    def _scalar_quality_baseline_values(
        self,
        frontier: Sequence[Mapping[str, float]],
        scalar_quality_context: Mapping[str, Any] | None,
    ) -> List[float]:
        name = self.scalar_quality_objective_name
        context_values = (
            scalar_quality_context.get("baseline_values", [])
            if isinstance(scalar_quality_context, Mapping)
            else []
        )
        values = [
            float(value)
            for value in context_values
            if math.isfinite(float(value)) and float(value) > 0.0
        ]
        if values:
            return values
        return [
            float(row.get(name))
            for row in frontier
            if name
            and row.get(name) is not None
            and math.isfinite(float(row.get(name)))
            and float(row.get(name)) > 0.0
        ]

    @staticmethod
    def _scalar_quality_rank_prior(
        calibrated_value: float,
        scalar_quality_context: Mapping[str, Any] | None,
    ) -> Dict[str, float]:
        if not math.isfinite(float(calibrated_value)) or calibrated_value <= 0.0:
            return {
                "rank_prior": 0.0,
                "topk_probability": 0.0,
                "rank_index": 0.0,
                "pool_size": 0.0,
            }
        values = (
            scalar_quality_context.get("baseline_values", [])
            if isinstance(scalar_quality_context, Mapping)
            else []
        )
        finite = sorted(
            float(value)
            for value in values
            if math.isfinite(float(value)) and float(value) > 0.0
        )
        if not finite:
            return {
                "rank_prior": 1.0,
                "topk_probability": 1.0,
                "rank_index": 1.0,
                "pool_size": 1.0,
            }
        rank_index = 1 + sum(1 for value in finite if value < calibrated_value)
        pool_size = max(1, len(finite))
        rank_prior = 1.0 - (float(rank_index - 1) / float(max(1, pool_size - 1)))
        topk = max(1, math.ceil(pool_size * 0.20))
        return {
            "rank_prior": _clamp(rank_prior, 0.0, 1.0),
            "topk_probability": 1.0 if rank_index <= topk else 0.0,
            "rank_index": float(rank_index),
            "pool_size": float(pool_size),
        }

    def _scalar_quality_calibration_model(
        self,
        observations: Sequence[ActiveSearchObservation],
    ) -> Dict[str, Any]:
        name = self.scalar_quality_objective_name
        samples: List[Dict[str, Any]] = []
        if not name:
            return {"sample_count": 0, "samples": samples}
        for observation in observations:
            observed = observation.objectives.get(name)
            if observed is None:
                observed = observation.metadata.get(name)
            observed_value = float(observed) if observed is not None else float("nan")
            prior_objectives = (
                observation.metadata.get("prior_objectives", {})
                if isinstance(observation.metadata.get("prior_objectives"), Mapping)
                else {}
            )
            prior = prior_objectives.get(name)
            prior_value = float(prior) if prior is not None else float("nan")
            if (
                not math.isfinite(observed_value)
                or not math.isfinite(prior_value)
                or observed_value <= 0.0
                or prior_value <= 0.0
            ):
                continue
            samples.append({
                "candidate_id": str(observation.candidate_id),
                "log_residual": _clamp(math.log(observed_value / prior_value), -4.0, 4.0),
                "prior_value": prior_value,
                "observed_value": observed_value,
                "risk_axes": {
                    str(key): float(value)
                    for key, value in (
                        observation.metadata.get("prior_risk_axes", {})
                        if isinstance(observation.metadata.get("prior_risk_axes"), Mapping)
                        else {}
                    ).items()
                    if math.isfinite(float(value))
                },
                "categorical_features": {
                    str(key): str(value)
                    for key, value in (
                        observation.metadata.get("prior_categorical_features", {})
                        if isinstance(observation.metadata.get("prior_categorical_features"), Mapping)
                        else {}
                    ).items()
                    if str(value)
                },
                "design_key": str(observation.metadata.get("prior_design_key", "")),
            })
        return {"sample_count": len(samples), "samples": samples}

    def _objective_calibration_model(
        self,
        observations: Sequence[ActiveSearchObservation],
    ) -> Dict[str, Any]:
        samples_by_objective: Dict[str, List[Dict[str, Any]]] = {
            name: [] for name in self.objective_names
        }
        for observation in observations:
            prior_objectives = (
                observation.metadata.get("prior_objectives", {})
                if isinstance(observation.metadata.get("prior_objectives"), Mapping)
                else {}
            )
            risk_axes = {
                str(key): float(value)
                for key, value in (
                    observation.metadata.get("prior_risk_axes", {})
                    if isinstance(observation.metadata.get("prior_risk_axes"), Mapping)
                    else {}
                ).items()
                if math.isfinite(float(value))
            }
            categorical_features = {
                str(key): str(value)
                for key, value in (
                    observation.metadata.get("prior_categorical_features", {})
                    if isinstance(observation.metadata.get("prior_categorical_features"), Mapping)
                    else {}
                ).items()
                if str(value)
            }
            design_key = str(observation.metadata.get("prior_design_key", ""))
            for name in self.objective_names:
                observed = observation.objectives.get(name)
                prior = prior_objectives.get(name)
                observed_value = float(observed) if observed is not None else float("nan")
                prior_value = float(prior) if prior is not None else float("nan")
                log_residual = self._zero_safe_log_residual(observed_value, prior_value)
                if log_residual is None:
                    continue
                samples_by_objective.setdefault(name, []).append({
                    "candidate_id": str(observation.candidate_id),
                    "objective_name": name,
                    "log_residual": log_residual,
                    "prior_value": prior_value,
                    "observed_value": observed_value,
                    "risk_axes": risk_axes,
                    "categorical_features": categorical_features,
                    "design_key": design_key,
                })
        return {
            "sample_count": sum(len(rows) for rows in samples_by_objective.values()),
            "samples_by_objective": samples_by_objective,
        }

    @staticmethod
    def _zero_safe_log_residual(observed_value: float, prior_value: float) -> float | None:
        if not math.isfinite(observed_value) or not math.isfinite(prior_value):
            return None
        if observed_value < 0.0 or prior_value < 0.0:
            return None
        if observed_value == 0.0 and prior_value == 0.0:
            return 0.0
        safe_observed = max(observed_value, 1.0e-9)
        safe_prior = max(prior_value, 1.0e-9)
        return _clamp(math.log(safe_observed / safe_prior), -4.0, 4.0)

    def _calibrated_scalar_quality_objective(
        self,
        candidate: ActiveSearchCandidate,
        scalar_quality_calibration: Mapping[str, Any] | None,
    ) -> Dict[str, float]:
        name = self.scalar_quality_objective_name
        raw_value = (
            float(candidate.objectives.get(name, 0.0))
            if name and candidate.objectives.get(name) is not None
            else 0.0
        )
        if not name or not math.isfinite(raw_value) or raw_value <= 0.0:
            return {
                "calibrated_value": 0.0,
                "log_residual_mean": 0.0,
                "similarity": 0.0,
                "sample_count": 0.0,
            }
        samples = (
            scalar_quality_calibration.get("samples", [])
            if isinstance(scalar_quality_calibration, Mapping)
            else []
        )
        return self._calibrated_value_from_residual_samples(candidate, raw_value, samples)

    def _calibrated_candidate_objectives(
        self,
        candidate: ActiveSearchCandidate,
        objective_calibration: Mapping[str, Any] | None,
    ) -> Dict[str, Any]:
        samples_by_objective = (
            objective_calibration.get("samples_by_objective", {})
            if isinstance(objective_calibration, Mapping)
            and isinstance(objective_calibration.get("samples_by_objective"), Mapping)
            else {}
        )
        objectives: Dict[str, float] = {}
        diagnostics: Dict[str, Dict[str, float]] = {}
        for name in self.objective_names:
            value = candidate.objectives.get(name)
            if value is None:
                continue
            raw_value = float(value)
            if not math.isfinite(raw_value):
                continue
            samples = samples_by_objective.get(name, []) if isinstance(samples_by_objective, Mapping) else []
            calibration = self._calibrated_value_from_residual_samples(
                candidate,
                raw_value,
                samples if isinstance(samples, Sequence) else [],
            )
            objectives[name] = calibration["calibrated_value"]
            diagnostics[name] = calibration
        return {"objectives": objectives, "diagnostics": diagnostics}

    def _calibrated_value_from_residual_samples(
        self,
        candidate: ActiveSearchCandidate,
        raw_value: float,
        samples: Sequence[Mapping[str, Any]],
    ) -> Dict[str, float]:
        if not math.isfinite(raw_value) or raw_value <= 0.0:
            return {
                "calibrated_value": raw_value if math.isfinite(raw_value) else 0.0,
                "log_residual_mean": 0.0,
                "similarity": 0.0,
                "sample_count": 0.0,
            }
        weighted_sum = 0.0
        weight_sum = 0.0
        max_similarity = 0.0
        sample_count = 0
        for sample in samples:
            if not isinstance(sample, Mapping):
                continue
            residual = float(sample.get("log_residual", 0.0))
            if not math.isfinite(residual):
                continue
            similarity = self._scalar_quality_calibration_similarity(candidate, sample)
            weight = max(0.0, similarity)
            if weight <= 0.0:
                continue
            weighted_sum += residual * weight
            weight_sum += weight
            max_similarity = max(max_similarity, similarity)
            sample_count += 1
        if weight_sum <= 0.0:
            return {
                "calibrated_value": raw_value,
                "log_residual_mean": 0.0,
                "similarity": 0.0,
                "sample_count": 0.0,
            }
        log_residual = _clamp(weighted_sum / max(1.0, weight_sum), -4.0, 4.0)
        return {
            "calibrated_value": max(1.0e-9, raw_value * math.exp(log_residual)),
            "log_residual_mean": log_residual,
            "similarity": _clamp(max_similarity, 0.0, 1.0),
            "sample_count": float(sample_count),
        }

    def _objective_calibration_components(
        self,
        calibrated_objectives: Mapping[str, Any],
    ) -> Dict[str, float]:
        diagnostics = (
            calibrated_objectives.get("diagnostics", {})
            if isinstance(calibrated_objectives.get("diagnostics"), Mapping)
            else {}
        )
        components: Dict[str, float] = {}
        max_sample_count = 0.0
        max_similarity = 0.0
        for name in self.objective_names:
            item = diagnostics.get(name, {}) if isinstance(diagnostics, Mapping) else {}
            if not isinstance(item, Mapping):
                continue
            safe_name = name.replace(".", "_").replace("/", "_")
            calibrated_value = float(item.get("calibrated_value", 0.0))
            log_residual = float(item.get("log_residual_mean", 0.0))
            similarity = float(item.get("similarity", 0.0))
            sample_count = float(item.get("sample_count", 0.0))
            components[f"calibrated_objective_{safe_name}"] = calibrated_value
            components[f"objective_log_residual_mean_{safe_name}"] = log_residual
            components[f"objective_residual_similarity_{safe_name}"] = similarity
            components[f"objective_residual_sample_count_{safe_name}"] = sample_count
            max_sample_count = max(max_sample_count, sample_count)
            max_similarity = max(max_similarity, similarity)
        components["objective_residual_sample_count"] = max_sample_count
        components["objective_residual_max_similarity"] = max_similarity
        return components

    @staticmethod
    def _scalar_quality_calibration_similarity(
        candidate: ActiveSearchCandidate,
        sample: Mapping[str, Any],
    ) -> float:
        design_similarity = (
            1.0
            if candidate.design_key
            and str(sample.get("design_key", ""))
            and candidate.design_key == str(sample.get("design_key", ""))
            else 0.0
        )
        sample_axes = sample.get("risk_axes", {}) if isinstance(sample.get("risk_axes"), Mapping) else {}
        common_axes = [
            key for key in candidate.risk_axes
            if key in sample_axes
            and math.isfinite(float(candidate.risk_axes[key]))
            and math.isfinite(float(sample_axes[key]))
        ]
        if common_axes:
            mean_distance = sum(
                abs(_clamp(float(candidate.risk_axes[key]), 0.0, 1.0) - _clamp(float(sample_axes[key]), 0.0, 1.0))
                for key in common_axes
            ) / float(len(common_axes))
            risk_similarity = _clamp(1.0 - mean_distance, 0.0, 1.0)
        else:
            risk_similarity = 0.0
        candidate_categories = (
            candidate.metadata.get("categorical_features", {})
            if isinstance(candidate.metadata.get("categorical_features"), Mapping)
            else {}
        )
        sample_categories = (
            sample.get("categorical_features", {})
            if isinstance(sample.get("categorical_features"), Mapping)
            else {}
        )
        common_categories = [
            key for key in candidate_categories
            if key in sample_categories
            and str(candidate_categories[key])
            and str(sample_categories[key])
        ]
        if common_categories:
            category_similarity = sum(
                1.0
                if str(candidate_categories[key]) == str(sample_categories[key])
                else 0.0
                for key in common_categories
            ) / float(len(common_categories))
        else:
            category_similarity = 0.0
        if design_similarity > 0.0:
            return 1.0
        if common_categories and common_axes:
            return max(0.15, 0.70 * category_similarity + 0.30 * risk_similarity)
        if common_categories:
            return max(0.15, category_similarity)
        if common_axes:
            return max(0.15, risk_similarity)
        return 0.15

    def _score_action(
        self,
        candidate: ActiveSearchCandidate,
        fidelity: ActiveSearchFidelity,
        acquisition: AcquisitionScore,
        *,
        observed_fidelities: Mapping[str, set[str]],
        selected_action_ids: set[str],
    ) -> ActiveSearchActionSelection:
        candidate_observed = observed_fidelities.get(candidate.candidate_id, set())
        prerequisites = {
            str(item) for item in fidelity.requires_observed_fidelities
        }
        prerequisites_satisfied = 1.0 if prerequisites.issubset(candidate_observed) else 0.0
        already_observed = 1.0 if str(fidelity.fidelity) in candidate_observed else 0.0
        action_cost = self._fidelity_evaluation_cost(fidelity)
        candidate_cost = self._evaluation_cost(candidate)
        total_cost = action_cost * candidate_cost
        action_feasibility = (
            acquisition.components["feasibility_probability"]
            * _clamp(float(fidelity.feasibility), 0.0, 1.0)
        )
        information_gain = _clamp(float(fidelity.information_gain), 0.0, 1.0)
        uncertainty_reduction = _clamp(float(fidelity.uncertainty_reduction), 0.0, 1.0)
        calibration_value = _clamp(float(fidelity.calibration_value), 0.0, 1.0)
        candidate_score = float(acquisition.score)
        action_value = (
            candidate_score
            * (0.50 + 0.50 * information_gain)
            * (0.70 + 0.30 * uncertainty_reduction)
            * (0.75 + 0.25 * calibration_value)
            * action_feasibility
            * prerequisites_satisfied
            * (1.0 - already_observed)
        )
        cost_normalized_action_value = action_value / total_cost
        action_id = f"{candidate.candidate_id}::{fidelity.fidelity}"
        if action_id in selected_action_ids:
            cost_normalized_action_value = 0.0
        components = {
            "candidate_acquisition_score": candidate_score,
            "candidate_cost": candidate_cost,
            "fidelity_evaluation_cost": action_cost,
            "action_cost": total_cost,
            "information_gain": information_gain,
            "uncertainty_reduction": uncertainty_reduction,
            "calibration_value": calibration_value,
            "action_feasibility": action_feasibility,
            "prerequisites_satisfied": prerequisites_satisfied,
            "already_observed_action": already_observed,
            "cost_normalized_action_value": cost_normalized_action_value,
        }
        return ActiveSearchActionSelection(
            candidate=candidate,
            fidelity_action=fidelity,
            acquisition=acquisition,
            action_score=max(0.0, float(cost_normalized_action_value)),
            components=components,
        )

    def _constrained_pareto_gain(
        self,
        candidate: ActiveSearchCandidate,
        frontier: Sequence[Mapping[str, float]],
        *,
        candidate_objectives: Mapping[str, float] | None = None,
    ) -> float:
        vector = self._objective_vector(candidate_objectives or candidate.objectives)
        if not vector:
            return 0.0
        if any(_dominates(self._objective_vector(row), vector) for row in frontier):
            return 0.0
        if not frontier:
            return 1.0
        best_gain = 0.0
        for row in frontier:
            base = self._objective_vector(row)
            if not base:
                continue
            gains = [
                max(0.0, (base_value - value) / max(abs(base_value), 1.0))
                for value, base_value in zip(vector, base)
            ]
            if gains:
                best_gain = max(best_gain, sum(gains) / len(gains))
        if best_gain <= 0.0 and not any(_dominates(vector, self._objective_vector(row)) for row in frontier):
            best_gain = 0.02
        return _clamp(best_gain, 0.0, 1.0)

    def _exclusive_hypervolume_gain(
        self,
        candidate: ActiveSearchCandidate,
        frontier: Sequence[Mapping[str, float]],
        *,
        candidate_objectives: Mapping[str, float] | None = None,
    ) -> float:
        vector = self._objective_vector(candidate_objectives or candidate.objectives)
        if not vector:
            return 0.0
        frontier_vectors = [
            self._objective_vector(row)
            for row in frontier
            if self._objective_vector(row)
        ]
        if any(_dominates(row, vector) for row in frontier_vectors):
            return 0.0
        reference = _reference_vector([vector, *frontier_vectors])
        if not reference or len(reference) != len(vector):
            return 0.0
        candidate_volume = _normalized_minimization_box_volume(vector, reference)
        if candidate_volume <= 0.0:
            return 0.0
        overlap_proxy = 0.0
        for row in frontier_vectors:
            if len(row) != len(vector):
                continue
            overlap_corner = [max(value, base) for value, base in zip(vector, row)]
            overlap_proxy = max(
                overlap_proxy,
                _normalized_minimization_box_volume(overlap_corner, reference),
            )
        return _clamp(candidate_volume - overlap_proxy, 0.0, 1.0)

    def _hypervolume_reference_point(
        self,
        candidates: Sequence[ActiveSearchCandidate],
        observations: Sequence[ActiveSearchObservation],
    ) -> Dict[str, float]:
        rows: List[Mapping[str, float]] = [candidate.objectives for candidate in candidates]
        rows.extend(observation.objectives for observation in observations if observation.feasible)
        vectors = [_vector(row, self.objective_names) for row in rows]
        vectors = [vector for vector in vectors if vector]
        if not vectors:
            return {}
        reference = _reference_vector(vectors)
        return {
            name: float(value)
            for name, value in zip(self.objective_names, reference)
        }

    def _hypervolume_reference_vector(
        self,
        candidates: Sequence[ActiveSearchCandidate],
        frontier: Sequence[Mapping[str, float]],
    ) -> List[float]:
        vectors = [self._objective_vector(candidate.objectives) for candidate in candidates]
        vectors.extend(self._objective_vector(row) for row in frontier)
        vectors = [vector for vector in vectors if vector]
        return _reference_vector(vectors)

    def _objective_vector(self, objectives: Mapping[str, float]) -> List[float]:
        return _vector(objectives, self.objective_names)

    def _feasibility_probability(self, candidate: ActiveSearchCandidate) -> float:
        feasibility = _clamp(float(candidate.constraints.get("feasibility", 1.0)), 0.0, 1.0)
        pressure = float(candidate.constraints.get(
            "resource_pressure",
            candidate.objectives.get("resource_pressure", 0.0),
        ))
        if math.isfinite(pressure) and pressure > self.resource_pressure_limit:
            over = min(1.0, (pressure - self.resource_pressure_limit) / max(1.0 - self.resource_pressure_limit, 1.0e-9))
            feasibility *= max(0.0, 1.0 - over)
        return _clamp(feasibility, 0.0, 1.0)

    @staticmethod
    def _workflow_risk_coverage(candidate: ActiveSearchCandidate) -> float:
        values = [
            _clamp(abs(float(value)), 0.0, 1.0)
            for value in candidate.risk_axes.values()
            if math.isfinite(float(value))
        ]
        if not values:
            return 0.0
        return sum(values) / len(values)

    @staticmethod
    def _normalized_cost(candidate: ActiveSearchCandidate) -> float:
        cost = MultiFidelityActiveSearchPolicy._evaluation_cost(candidate)
        return _clamp(cost / (1.0 + cost), 0.0, 1.0)

    @staticmethod
    def _evaluation_cost(candidate: ActiveSearchCandidate) -> float:
        cost = float(candidate.evaluation_cost)
        if not math.isfinite(cost) or cost <= 0.0:
            return 1.0
        return max(1.0e-9, cost)

    @staticmethod
    def _fidelity_evaluation_cost(fidelity: ActiveSearchFidelity) -> float:
        cost = float(fidelity.evaluation_cost)
        if not math.isfinite(cost) or cost <= 0.0:
            return 1.0
        return max(1.0e-9, cost)

    @staticmethod
    def _observed_fidelities_by_candidate(
        observations: Sequence[ActiveSearchObservation],
    ) -> Dict[str, set[str]]:
        observed: Dict[str, set[str]] = {}
        for row in observations:
            observed.setdefault(row.candidate_id, set()).add(str(row.fidelity))
        return observed

    def _frontier_from_observations(
        self,
        observations: Sequence[ActiveSearchObservation],
    ) -> List[Mapping[str, float]]:
        return _pareto_frontier([
            observation.objectives
            for observation in observations
            if self._objective_vector(observation.objectives)
        ], self.objective_names)

    def _frontier_from_candidates(
        self,
        candidates: Sequence[ActiveSearchCandidate],
    ) -> List[Mapping[str, float]]:
        feasible = [
            candidate.objectives
            for candidate in candidates
            if self._objective_vector(candidate.objectives)
            and self._feasibility_probability(candidate) > 0.0
        ]
        return _pareto_frontier(feasible, self.objective_names)


def _pareto_frontier(
    rows: Sequence[Mapping[str, float]],
    objective_names: Sequence[str],
) -> List[Mapping[str, float]]:
    frontier: List[Mapping[str, float]] = []
    vectors = [_vector(row, objective_names) for row in rows]
    for index, row in enumerate(rows):
        vector = vectors[index]
        if not vector:
            continue
        if any(other_index != index and _dominates(other, vector) for other_index, other in enumerate(vectors)):
            continue
        frontier.append(row)
    return frontier


def _vector(row: Mapping[str, float], objective_names: Sequence[str]) -> List[float]:
    vector: List[float] = []
    for name in objective_names:
        value = row.get(name)
        if value is None:
            return []
        numeric = float(value)
        if not math.isfinite(numeric):
            return []
        vector.append(numeric)
    return vector


def _dominates(left: Sequence[float], right: Sequence[float]) -> bool:
    if not left or not right or len(left) != len(right):
        return False
    return all(a <= b for a, b in zip(left, right)) and any(a < b for a, b in zip(left, right))


def _reference_vector(vectors: Sequence[Sequence[float]]) -> List[float]:
    if not vectors:
        return []
    width = min(len(vector) for vector in vectors)
    reference: List[float] = []
    for index in range(width):
        values = [float(vector[index]) for vector in vectors if index < len(vector) and math.isfinite(float(vector[index]))]
        if not values:
            reference.append(1.0)
            continue
        upper = max(values)
        lower = min(values)
        margin = max(abs(upper) * 0.10, abs(upper - lower) * 0.10, 1.0)
        reference.append(upper + margin)
    return reference


def _normalized_minimization_box_volume(vector: Sequence[float], reference: Sequence[float]) -> float:
    if not vector or not reference or len(vector) != len(reference):
        return 0.0
    volume = 1.0
    for value, ref in zip(vector, reference):
        if not math.isfinite(float(value)) or not math.isfinite(float(ref)) or ref <= 0.0:
            return 0.0
        volume *= max(0.0, (ref - value) / ref)
    return _clamp(volume, 0.0, 1.0)


def _clamp(value: float, lower: float, upper: float) -> float:
    if not math.isfinite(value):
        return lower
    return max(lower, min(upper, value))
