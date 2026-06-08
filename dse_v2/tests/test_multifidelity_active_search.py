from dse_v2.mapping.multifidelity_active_search import (
    ActiveSearchCandidate,
    ActiveSearchFidelity,
    ActiveSearchObservation,
    MultiFidelityActiveSearchPolicy,
)


def test_active_search_selects_candidate_by_constrained_pareto_gain_not_l1_rank_only():
    policy = MultiFidelityActiveSearchPolicy()
    candidates = [
        ActiveSearchCandidate(
            candidate_id="cheap-best-but-infeasible",
            objectives={
                "latency_ms": 80.0,
                "energy_mj": 120.0,
                "resource_pressure": 0.98,
                "data_movement_mb": 80.0,
            },
            constraints={"resource_pressure": 0.98, "feasibility": 0.30},
            uncertainty=0.05,
            evaluation_cost=1.0,
            risk_axes={"host_control_intensity": 0.1, "transfer_sync": 0.1},
            design_key="wide/hbm",
        ),
        ActiveSearchCandidate(
            candidate_id="pareto-feasible-risk-informative",
            objectives={
                "latency_ms": 92.0,
                "energy_mj": 96.0,
                "resource_pressure": 0.66,
                "data_movement_mb": 40.0,
            },
            constraints={"resource_pressure": 0.66, "feasibility": 0.86},
            uncertainty=0.22,
            evaluation_cost=1.2,
            risk_axes={"host_control_intensity": 0.9, "transfer_sync": 0.8},
            design_key="stream/hbm",
        ),
        ActiveSearchCandidate(
            candidate_id="cheap-duplicate",
            objectives={
                "latency_ms": 89.0,
                "energy_mj": 150.0,
                "resource_pressure": 0.72,
                "data_movement_mb": 105.0,
            },
            constraints={"resource_pressure": 0.72, "feasibility": 0.90},
            uncertainty=0.02,
            evaluation_cost=0.8,
            risk_axes={"host_control_intensity": 0.1, "transfer_sync": 0.1},
            design_key="wide/hbm",
        ),
    ]

    selected = policy.select(candidates, budget=1)

    assert [row.candidate_id for row in selected] == ["pareto-feasible-risk-informative"]
    score = selected[0].acquisition
    assert score.policy == "wamf_constrained_active_pareto"
    assert score.components["constrained_pareto_gain"] > 0.0
    assert score.components["feasibility_probability"] > 0.0
    assert score.components["workflow_risk_coverage"] > 0.0
    assert score.components["evaluation_cost_penalty"] < 0.0
    assert "maximize_cost_aware_constrained_ehvi_proxy" in score.equation


def test_active_search_preserves_strong_scalar_quality_prior_before_risk_exploration():
    policy = MultiFidelityActiveSearchPolicy(
        objective_names=(
            "latency_ms",
            "energy_mj",
            "resource_pressure",
            "data_movement_mb",
        ),
        scalar_quality_objective_name="estimated_edp",
    )
    candidates = [
        ActiveSearchCandidate(
            candidate_id="strong-cheap-prior",
            objectives={
                "latency_ms": 90.0,
                "energy_mj": 90.0,
                "resource_pressure": 0.70,
                "data_movement_mb": 90.0,
                "estimated_edp": 8_100.0,
            },
            constraints={"resource_pressure": 0.70, "feasibility": 0.95},
            uncertainty=0.02,
            evaluation_cost=1.0,
            risk_axes={"host_control_intensity": 0.1, "transfer_sync": 0.1},
            design_key="balanced/prior",
        ),
        ActiveSearchCandidate(
            candidate_id="risk-informative-but-weaker-prior",
            objectives={
                "latency_ms": 115.0,
                "energy_mj": 115.0,
                "resource_pressure": 0.50,
                "data_movement_mb": 36.0,
                "estimated_edp": 13_225.0,
            },
            constraints={"resource_pressure": 0.50, "feasibility": 0.97},
            uncertainty=0.60,
            evaluation_cost=1.0,
            risk_axes={"host_control_intensity": 0.9, "transfer_sync": 0.9},
            design_key="stream/risk",
        ),
    ]

    selected = policy.select(candidates, budget=1)

    assert [row.candidate_id for row in selected] == ["strong-cheap-prior"]
    components = selected[0].acquisition.components
    assert components["scalar_quality_prior"] > 0.0
    assert components["scalar_quality_objective"] == 8100.0


def test_active_search_anchors_first_batch_slot_on_scalar_quality_prior():
    policy = MultiFidelityActiveSearchPolicy(
        objective_names=("latency_ms", "energy_mj", "resource_pressure", "data_movement_mb"),
        scalar_quality_objective_name="estimated_edp",
    )
    candidates = [
        ActiveSearchCandidate(
            candidate_id="risk-heavy",
            objectives={
                "latency_ms": 104.0,
                "energy_mj": 104.0,
                "resource_pressure": 0.45,
                "data_movement_mb": 20.0,
                "estimated_edp": 10_816.0,
            },
            constraints={"resource_pressure": 0.45, "feasibility": 0.98},
            uncertainty=0.90,
            risk_axes={"host_control_intensity": 1.0, "transfer_sync": 1.0},
            design_key="risk-heavy",
        ),
        ActiveSearchCandidate(
            candidate_id="best-prior",
            objectives={
                "latency_ms": 80.0,
                "energy_mj": 80.0,
                "resource_pressure": 0.75,
                "data_movement_mb": 85.0,
                "estimated_edp": 6_400.0,
            },
            constraints={"resource_pressure": 0.75, "feasibility": 0.93},
            uncertainty=0.03,
            risk_axes={"host_control_intensity": 0.1, "transfer_sync": 0.1},
            design_key="best-prior",
        ),
        ActiveSearchCandidate(
            candidate_id="second-prior",
            objectives={
                "latency_ms": 86.0,
                "energy_mj": 88.0,
                "resource_pressure": 0.72,
                "data_movement_mb": 78.0,
                "estimated_edp": 7_568.0,
            },
            constraints={"resource_pressure": 0.72, "feasibility": 0.94},
            uncertainty=0.05,
            risk_axes={"host_control_intensity": 0.1, "transfer_sync": 0.2},
            design_key="second-prior",
        ),
    ]

    selected = policy.select(candidates, budget=3)

    assert selected[0].candidate_id == "best-prior"
    assert selected[0].acquisition.components["scalar_quality_anchor"] == 1.0


def test_active_search_calibrates_scalar_quality_prior_from_observed_residuals():
    policy = MultiFidelityActiveSearchPolicy(
        objective_names=("latency_ms", "energy_mj", "resource_pressure", "data_movement_mb"),
        scalar_quality_objective_name="estimated_edp",
        weights={
            "uncertainty": 0.0,
            "workflow_risk_coverage": 0.0,
            "design_diversity": 0.0,
            "cost_normalized_hv_gain": 0.0,
            "pareto_gain": 0.0,
            "evaluation_cost": 0.0,
            "scalar_quality_prior": 1.0,
        },
    )
    observations = [
        ActiveSearchObservation(
            candidate_id="observed-optimistic-stream",
            fidelity="L2_systemc_or_tlm",
            objectives={
                "latency_ms": 150.0,
                "energy_mj": 150.0,
                "resource_pressure": 0.70,
                "data_movement_mb": 55.0,
                "estimated_edp": 22_500.0,
            },
            feasible=True,
            metadata={
                "prior_objectives": {
                    "latency_ms": 90.0,
                    "energy_mj": 90.0,
                    "resource_pressure": 0.70,
                    "data_movement_mb": 50.0,
                    "estimated_edp": 8_100.0,
                },
                "prior_risk_axes": {"transfer_sync": 0.9, "host_control_intensity": 0.8},
                "prior_design_key": "stream/hbm",
            },
        )
    ]
    candidates = [
        ActiveSearchCandidate(
            candidate_id="same-risk-low-l1-prior",
            objectives={
                "latency_ms": 88.0,
                "energy_mj": 88.0,
                "resource_pressure": 0.70,
                "data_movement_mb": 52.0,
                "estimated_edp": 7_744.0,
            },
            constraints={"resource_pressure": 0.70, "feasibility": 0.95},
            risk_axes={"transfer_sync": 0.88, "host_control_intensity": 0.82},
            design_key="stream/hbm",
        ),
        ActiveSearchCandidate(
            candidate_id="different-risk-better-calibrated",
            objectives={
                "latency_ms": 112.0,
                "energy_mj": 112.0,
                "resource_pressure": 0.55,
                "data_movement_mb": 62.0,
                "estimated_edp": 12_544.0,
            },
            constraints={"resource_pressure": 0.55, "feasibility": 0.95},
            risk_axes={"transfer_sync": 0.1, "host_control_intensity": 0.2},
            design_key="tile/uram",
        ),
    ]

    selected = policy.select(candidates, observations=observations, budget=1)

    assert [row.candidate_id for row in selected] == ["different-risk-better-calibrated"]
    components = selected[0].acquisition.components
    assert components["scalar_quality_residual_sample_count"] == 1.0
    assert components["calibrated_scalar_quality_objective"] < 22_500.0
    same_risk_report = policy.selection_report(candidates, observations=observations, budget=2)
    by_id = {
        row["candidate_id"]: row["acquisition"]["components"]
        for row in same_risk_report["selection"]
    }
    assert (
        by_id["same-risk-low-l1-prior"]["calibrated_scalar_quality_objective"]
        > components["calibrated_scalar_quality_objective"]
    )


def test_active_search_prioritizes_calibrated_qor_over_workflow_risk_exploration():
    policy = MultiFidelityActiveSearchPolicy(
        objective_names=("latency_ms", "energy_mj", "resource_pressure", "data_movement_mb"),
        scalar_quality_objective_name="estimated_edp",
        weights={
            "uncertainty": 0.0,
            "workflow_risk_coverage": 0.16,
            "design_diversity": 0.0,
            "cost_normalized_hv_gain": 0.0,
            "pareto_gain": 0.0,
            "evaluation_cost": 0.0,
            "scalar_quality_prior": 0.85,
        },
    )
    observations = [
        ActiveSearchObservation(
            candidate_id="observed-balanced",
            fidelity="L2_systemc_or_tlm",
            objectives={
                "latency_ms": 90.0,
                "energy_mj": 90.0,
                "resource_pressure": 0.60,
                "data_movement_mb": 50.0,
                "estimated_edp": 8_100.0,
            },
            feasible=True,
            metadata={
                "prior_objectives": {
                    "latency_ms": 90.0,
                    "energy_mj": 90.0,
                    "resource_pressure": 0.60,
                    "data_movement_mb": 50.0,
                    "estimated_edp": 8_100.0,
                },
                "prior_risk_axes": {"transfer_sync": 0.2, "host_control_intensity": 0.2},
                "prior_design_key": "balanced/ddr",
            },
        )
    ]
    candidates = [
        ActiveSearchCandidate(
            candidate_id="calibrated-qor-best",
            objectives={
                "latency_ms": 82.0,
                "energy_mj": 92.0,
                "resource_pressure": 0.62,
                "data_movement_mb": 52.0,
                "estimated_edp": 7_544.0,
            },
            constraints={"resource_pressure": 0.62, "feasibility": 0.95},
            risk_axes={"transfer_sync": 0.2, "host_control_intensity": 0.2},
            design_key="balanced/ddr",
        ),
        ActiveSearchCandidate(
            candidate_id="risk-only-weaker-qor",
            objectives={
                "latency_ms": 110.0,
                "energy_mj": 110.0,
                "resource_pressure": 0.45,
                "data_movement_mb": 40.0,
                "estimated_edp": 12_100.0,
            },
            constraints={"resource_pressure": 0.45, "feasibility": 0.95},
            risk_axes={"transfer_sync": 1.0, "host_control_intensity": 1.0},
            design_key="risk/explore",
        ),
    ]

    selected = policy.select(candidates, observations=observations, budget=1)

    assert [row.candidate_id for row in selected] == ["calibrated-qor-best"]
    components = selected[0].acquisition.components
    assert components["scalar_quality_prior"] > 0.90
    assert components["workflow_risk_coverage"] < 0.5


def test_active_search_rank_prior_limits_hv_exploration_when_qor_gap_is_large():
    policy = MultiFidelityActiveSearchPolicy(
        objective_names=("latency_ms", "energy_mj", "resource_pressure", "data_movement_mb"),
        scalar_quality_objective_name="estimated_edp",
        weights={
            "uncertainty": 0.0,
            "workflow_risk_coverage": 0.0,
            "design_diversity": 0.0,
            "cost_normalized_hv_gain": 1.0,
            "pareto_gain": 0.0,
            "evaluation_cost": 0.0,
            "scalar_quality_prior": 0.85,
        },
    )
    observations = [
        ActiveSearchObservation(
            candidate_id="observed-frontier",
            fidelity="L2_systemc_or_tlm",
            objectives={
                "latency_ms": 100.0,
                "energy_mj": 100.0,
                "resource_pressure": 0.60,
                "data_movement_mb": 60.0,
                "estimated_edp": 10_000.0,
            },
            feasible=True,
            metadata={
                "prior_objectives": {
                    "latency_ms": 100.0,
                    "energy_mj": 100.0,
                    "resource_pressure": 0.60,
                    "data_movement_mb": 60.0,
                    "estimated_edp": 10_000.0,
                },
                "prior_design_key": "frontier",
            },
        )
    ]
    candidates = [
        ActiveSearchCandidate(
            candidate_id="rank-prior-best",
            objectives={
                "latency_ms": 92.0,
                "energy_mj": 101.0,
                "resource_pressure": 0.61,
                "data_movement_mb": 61.0,
                "estimated_edp": 9_292.0,
            },
            constraints={"resource_pressure": 0.61, "feasibility": 0.95},
            design_key="rank-best",
        ),
        ActiveSearchCandidate(
            candidate_id="hv-broad-but-rank-weaker",
            objectives={
                "latency_ms": 96.0,
                "energy_mj": 96.0,
                "resource_pressure": 0.36,
                "data_movement_mb": 28.0,
                "estimated_edp": 18_000.0,
            },
            constraints={"resource_pressure": 0.36, "feasibility": 0.99},
            design_key="hv-broad",
        ),
    ]

    selected = policy.select(candidates, observations=observations, budget=1)

    assert [row.candidate_id for row in selected] == ["rank-prior-best"]
    components = selected[0].acquisition.components
    assert components["scalar_quality_rank_prior"] == 1.0
    assert components["scalar_quality_topk_probability"] == 1.0


def test_active_search_transfers_residuals_across_matching_categorical_features():
    policy = MultiFidelityActiveSearchPolicy(
        objective_names=("latency_ms", "energy_mj", "resource_pressure", "data_movement_mb"),
        scalar_quality_objective_name="estimated_edp",
        weights={
            "uncertainty": 0.0,
            "workflow_risk_coverage": 0.0,
            "design_diversity": 0.0,
            "cost_normalized_hv_gain": 0.0,
            "pareto_gain": 0.0,
            "evaluation_cost": 0.0,
            "scalar_quality_prior": 1.0,
            "scalar_quality_rank_prior": 0.0,
        },
    )
    observations = [
        ActiveSearchObservation(
            candidate_id="observed-hybrid-optimistic",
            fidelity="L2_systemc_or_tlm",
            objectives={
                "latency_ms": 160.0,
                "energy_mj": 160.0,
                "resource_pressure": 0.65,
                "data_movement_mb": 55.0,
                "estimated_edp": 25_600.0,
            },
            feasible=True,
            metadata={
                "prior_objectives": {
                    "latency_ms": 80.0,
                    "energy_mj": 80.0,
                    "resource_pressure": 0.65,
                    "data_movement_mb": 55.0,
                    "estimated_edp": 6_400.0,
                },
                "prior_categorical_features": {
                    "architecture_template": "hybrid",
                    "offload_boundary": "workflow",
                },
                "prior_design_key": "hybrid/observed",
            },
        )
    ]
    candidates = [
        ActiveSearchCandidate(
            candidate_id="same-family-optimistic-l1",
            objectives={
                "latency_ms": 78.0,
                "energy_mj": 78.0,
                "resource_pressure": 0.65,
                "data_movement_mb": 55.0,
                "estimated_edp": 6_084.0,
            },
            constraints={"resource_pressure": 0.65, "feasibility": 0.95},
            metadata={
                "categorical_features": {
                    "architecture_template": "hybrid",
                    "offload_boundary": "workflow",
                },
            },
            design_key="hybrid/new",
        ),
        ActiveSearchCandidate(
            candidate_id="different-family-better-after-calibration",
            objectives={
                "latency_ms": 104.0,
                "energy_mj": 104.0,
                "resource_pressure": 0.58,
                "data_movement_mb": 60.0,
                "estimated_edp": 10_816.0,
            },
            constraints={"resource_pressure": 0.58, "feasibility": 0.95},
            metadata={
                "categorical_features": {
                    "architecture_template": "streaming",
                    "offload_boundary": "workflow",
                },
            },
            design_key="streaming/new",
        ),
    ]

    selected = policy.select(candidates, observations=observations, budget=1)

    assert [row.candidate_id for row in selected] == ["different-family-better-after-calibration"]
    report = policy.selection_report(candidates, observations=observations, budget=2)
    by_id = {
        row["candidate_id"]: row["acquisition"]["components"]
        for row in report["selection"]
    }
    assert (
        by_id["same-family-optimistic-l1"]["calibrated_scalar_quality_objective"]
        > by_id["different-family-better-after-calibration"]["calibrated_scalar_quality_objective"]
    )
    assert by_id["same-family-optimistic-l1"]["scalar_quality_residual_similarity"] > 0.5


def test_active_search_calibrates_pareto_objectives_not_only_scalar_qor():
    policy = MultiFidelityActiveSearchPolicy(
        objective_names=("latency_ms", "energy_mj", "resource_pressure", "data_movement_mb"),
        scalar_quality_objective_name="estimated_edp",
        weights={
            "uncertainty": 0.0,
            "workflow_risk_coverage": 0.0,
            "design_diversity": 0.0,
            "cost_normalized_hv_gain": 1.0,
            "pareto_gain": 0.0,
            "evaluation_cost": 0.0,
            "scalar_quality_prior": 0.0,
            "scalar_quality_rank_prior": 0.0,
        },
    )
    observations = [
        ActiveSearchObservation(
            candidate_id="observed-hbm-transfer-optimistic",
            fidelity="L2_systemc_or_tlm",
            objectives={
                "latency_ms": 180.0,
                "energy_mj": 144.0,
                "resource_pressure": 0.66,
                "data_movement_mb": 220.0,
                "estimated_edp": 25_920.0,
            },
            feasible=True,
            metadata={
                "prior_objectives": {
                    "latency_ms": 90.0,
                    "energy_mj": 120.0,
                    "resource_pressure": 0.66,
                    "data_movement_mb": 55.0,
                    "estimated_edp": 10_800.0,
                },
                "prior_categorical_features": {
                    "architecture_template": "streaming_hbm",
                    "data_residency": "host_ping_pong",
                },
                "prior_design_key": "streaming_hbm/host_ping_pong",
            },
        )
    ]
    candidates = [
        ActiveSearchCandidate(
            candidate_id="same-family-l1-hv-mirage",
            objectives={
                "latency_ms": 84.0,
                "energy_mj": 112.0,
                "resource_pressure": 0.64,
                "data_movement_mb": 48.0,
                "estimated_edp": 9_408.0,
            },
            constraints={"resource_pressure": 0.64, "feasibility": 0.95},
            metadata={
                "categorical_features": {
                    "architecture_template": "streaming_hbm",
                    "data_residency": "host_ping_pong",
                },
            },
            design_key="streaming_hbm/host_ping_pong",
        ),
        ActiveSearchCandidate(
            candidate_id="different-family-calibrated-pareto",
            objectives={
                "latency_ms": 116.0,
                "energy_mj": 116.0,
                "resource_pressure": 0.58,
                "data_movement_mb": 72.0,
                "estimated_edp": 13_456.0,
            },
            constraints={"resource_pressure": 0.58, "feasibility": 0.95},
            metadata={
                "categorical_features": {
                    "architecture_template": "systolic_uram",
                    "data_residency": "device_resident",
                },
            },
            design_key="systolic_uram/device_resident",
        ),
    ]

    selected = policy.select(candidates, observations=observations, budget=1)

    assert [row.candidate_id for row in selected] == ["different-family-calibrated-pareto"]
    report = policy.selection_report(candidates, observations=observations, budget=2)
    by_id = {
        row["candidate_id"]: row["acquisition"]["components"]
        for row in report["selection"]
    }
    mirage = by_id["same-family-l1-hv-mirage"]
    assert mirage["calibrated_objective_latency_ms"] > 160.0
    assert mirage["calibrated_objective_data_movement_mb"] > 180.0
    assert mirage["objective_residual_sample_count"] >= 1.0


def test_active_search_rejects_incomplete_objective_vectors_without_axis_shift():
    policy = MultiFidelityActiveSearchPolicy(
        objective_names=("latency_ms", "energy_mj", "resource_pressure", "data_movement_mb"),
        weights={
            "uncertainty": 0.0,
            "workflow_risk_coverage": 0.0,
            "design_diversity": 0.0,
        },
    )
    observations = [
        ActiveSearchObservation(
            candidate_id="frontier",
            fidelity="L3_systemc",
            objectives={
                "latency_ms": 100.0,
                "energy_mj": 100.0,
                "resource_pressure": 0.50,
                "data_movement_mb": 100.0,
            },
            feasible=True,
        )
    ]
    candidates = [
        ActiveSearchCandidate(
            candidate_id="missing-energy-would-axis-shift",
            objectives={
                "latency_ms": 90.0,
                "resource_pressure": 0.20,
                "data_movement_mb": 90.0,
            },
            constraints={"resource_pressure": 0.20, "feasibility": 0.95},
            uncertainty=1.0,
            design_key="incomplete",
        ),
        ActiveSearchCandidate(
            candidate_id="complete-valid-improvement",
            objectives={
                "latency_ms": 98.0,
                "energy_mj": 98.0,
                "resource_pressure": 0.48,
                "data_movement_mb": 98.0,
            },
            constraints={"resource_pressure": 0.48, "feasibility": 0.95},
            uncertainty=0.0,
            design_key="complete",
        ),
    ]

    selected = policy.select(candidates, observations=observations, budget=1)

    assert [row.candidate_id for row in selected] == ["complete-valid-improvement"]
    report = policy.selection_report(candidates, observations=observations, budget=2)
    by_id = {
        row["candidate_id"]: row["acquisition"]["components"]
        for row in report["selection"]
    }
    assert "missing-energy-would-axis-shift" not in by_id


def test_active_search_calibration_accepts_zero_values_without_dropping_samples():
    policy = MultiFidelityActiveSearchPolicy(
        objective_names=("latency_ms", "energy_mj", "resource_pressure", "data_movement_mb"),
        scalar_quality_objective_name="estimated_edp",
        weights={
            "uncertainty": 0.0,
            "workflow_risk_coverage": 0.0,
            "design_diversity": 0.0,
            "cost_normalized_hv_gain": 0.0,
            "pareto_gain": 0.0,
            "evaluation_cost": 0.0,
            "scalar_quality_prior": 1.0,
            "scalar_quality_rank_prior": 0.0,
        },
    )
    observations = [
        ActiveSearchObservation(
            candidate_id="zero-data-movement-observed",
            fidelity="L2_systemc_or_tlm",
            objectives={
                "latency_ms": 10.0,
                "energy_mj": 0.0,
                "resource_pressure": 0.20,
                "data_movement_mb": 0.0,
                "estimated_edp": 0.0,
            },
            feasible=True,
            metadata={
                "prior_objectives": {
                    "latency_ms": 5.0,
                    "energy_mj": 0.0,
                    "resource_pressure": 0.20,
                    "data_movement_mb": 0.0,
                    "estimated_edp": 0.0,
                },
                "prior_risk_axes": {"host_control_intensity": 0.1},
                "prior_design_key": "zero/data",
            },
        )
    ]

    objective_calibration = policy._objective_calibration_model(observations)

    assert objective_calibration["sample_count"] >= 2
    assert len(objective_calibration["samples_by_objective"]["energy_mj"]) == 1
    assert len(objective_calibration["samples_by_objective"]["data_movement_mb"]) == 1
    assert objective_calibration["samples_by_objective"]["energy_mj"][0]["log_residual"] == 0.0
    assert objective_calibration["samples_by_objective"]["data_movement_mb"][0]["log_residual"] == 0.0


def test_active_search_uses_observations_as_calibrated_frontier_and_avoids_reselecting():
    policy = MultiFidelityActiveSearchPolicy()
    observations = [
        ActiveSearchObservation(
            candidate_id="already-measured",
            fidelity="L3_systemc",
            objectives={
                "latency_ms": 100.0,
                "energy_mj": 100.0,
                "resource_pressure": 0.60,
                "data_movement_mb": 45.0,
            },
            feasible=True,
        )
    ]
    candidates = [
        ActiveSearchCandidate(
            candidate_id="already-measured",
            objectives={
                "latency_ms": 85.0,
                "energy_mj": 85.0,
                "resource_pressure": 0.52,
                "data_movement_mb": 35.0,
            },
            constraints={"resource_pressure": 0.52, "feasibility": 0.95},
            uncertainty=0.1,
            evaluation_cost=1.0,
            risk_axes={"host_control_intensity": 0.2},
            design_key="same",
        ),
        ActiveSearchCandidate(
            candidate_id="improves-observed-frontier",
            objectives={
                "latency_ms": 94.0,
                "energy_mj": 88.0,
                "resource_pressure": 0.58,
                "data_movement_mb": 42.0,
            },
            constraints={"resource_pressure": 0.58, "feasibility": 0.93},
            uncertainty=0.06,
            evaluation_cost=1.0,
            risk_axes={"host_control_intensity": 0.4},
            design_key="new",
        ),
        ActiveSearchCandidate(
            candidate_id="dominated-by-observation",
            objectives={
                "latency_ms": 130.0,
                "energy_mj": 130.0,
                "resource_pressure": 0.72,
                "data_movement_mb": 70.0,
            },
            constraints={"resource_pressure": 0.72, "feasibility": 0.95},
            uncertainty=0.01,
            evaluation_cost=0.5,
            risk_axes={"host_control_intensity": 0.2},
            design_key="dominated",
        ),
    ]

    selected = policy.select(candidates, observations=observations, budget=2)

    assert [row.candidate_id for row in selected] == ["improves-observed-frontier"]
    assert selected[0].acquisition.components["constrained_pareto_gain"] > 0.0
    assert selected[0].acquisition.frontier_source == "observed_high_fidelity_frontier"


def test_active_search_keeps_exploring_when_observed_frontier_dominates_all_candidates():
    policy = MultiFidelityActiveSearchPolicy()
    observations = [
        ActiveSearchObservation(
            candidate_id="external-best",
            fidelity="L3_systemc",
            objectives={
                "latency_ms": 1.0,
                "energy_mj": 1.0,
                "resource_pressure": 0.01,
                "data_movement_mb": 0.0,
            },
            feasible=True,
        )
    ]
    candidates = [
        ActiveSearchCandidate(
            candidate_id="risk-informative",
            objectives={
                "latency_ms": 100.0,
                "energy_mj": 100.0,
                "resource_pressure": 0.50,
                "data_movement_mb": 10.0,
            },
            constraints={"resource_pressure": 0.50, "feasibility": 0.95},
            uncertainty=0.50,
            evaluation_cost=1.0,
            risk_axes={"host_control_intensity": 0.9, "transfer_sync": 0.8},
            design_key="risk",
        ),
        ActiveSearchCandidate(
            candidate_id="cheap-low-info",
            objectives={
                "latency_ms": 120.0,
                "energy_mj": 120.0,
                "resource_pressure": 0.40,
                "data_movement_mb": 12.0,
            },
            constraints={"resource_pressure": 0.40, "feasibility": 0.95},
            uncertainty=0.01,
            evaluation_cost=0.8,
            risk_axes={"host_control_intensity": 0.1},
            design_key="cheap",
        ),
    ]

    selected = policy.select(candidates, observations=observations, budget=1)

    assert [row.candidate_id for row in selected] == ["risk-informative"]
    assert selected[0].acquisition.components["constrained_pareto_gain"] == 0.0
    assert selected[0].acquisition.frontier_source == "observed_high_fidelity_frontier"


def test_active_search_serializes_replayable_selection_report():
    policy = MultiFidelityActiveSearchPolicy()
    candidates = [
        ActiveSearchCandidate(
            candidate_id="a",
            objectives={"latency_ms": 10.0, "energy_mj": 20.0, "resource_pressure": 0.4},
            constraints={"feasibility": 0.9, "resource_pressure": 0.4},
            uncertainty=0.2,
            evaluation_cost=1.0,
            risk_axes={"transfer_sync": 0.8},
            design_key="a",
        )
    ]

    report = policy.selection_report(candidates, budget=1)

    assert report["schema_version"] == "dse.multifidelity_active_search.selection.v1"
    assert report["policy_id"] == "wamf_constrained_active_pareto"
    assert report["selected_candidate_ids"] == ["a"]
    assert report["selection"][0]["acquisition"]["components"]["uncertainty"] > 0.0
    assert report["algorithm_contract"]["domain_neutral"] is True
    assert report["algorithm_contract"]["evidence_role"] == "feedback_calibration_not_search_objective"


def test_active_search_prefers_constrained_hv_gain_over_low_scalar_edp():
    policy = MultiFidelityActiveSearchPolicy(
        weights={
            "uncertainty": 0.0,
            "workflow_risk_coverage": 0.0,
            "design_diversity": 0.0,
        }
    )
    observations = [
        ActiveSearchObservation(
            candidate_id="frontier",
            fidelity="L3_systemc",
            objectives={
                "latency_ms": 100.0,
                "energy_mj": 100.0,
                "resource_pressure": 0.70,
                "data_movement_mb": 100.0,
            },
            feasible=True,
        )
    ]
    candidates = [
        ActiveSearchCandidate(
            candidate_id="scalar-edp-only",
            objectives={
                "latency_ms": 70.0,
                "energy_mj": 140.0,
                "resource_pressure": 0.70,
                "data_movement_mb": 100.0,
            },
            constraints={"resource_pressure": 0.70, "feasibility": 0.95},
            uncertainty=0.0,
            evaluation_cost=1.0,
            design_key="scalar",
        ),
        ActiveSearchCandidate(
            candidate_id="broad-hv-improvement",
            objectives={
                "latency_ms": 92.0,
                "energy_mj": 92.0,
                "resource_pressure": 0.55,
                "data_movement_mb": 70.0,
            },
            constraints={"resource_pressure": 0.55, "feasibility": 0.95},
            uncertainty=0.0,
            evaluation_cost=1.0,
            design_key="broad",
        ),
    ]

    selected = policy.select(candidates, observations=observations, budget=1)

    assert [row.candidate_id for row in selected] == ["broad-hv-improvement"]
    components = selected[0].acquisition.components
    assert components["exclusive_hypervolume_gain"] > 0.0
    assert components["feasibility_weighted_hv_gain"] > 0.0
    assert components["cost_normalized_hv_gain"] > 0.0


def test_active_search_discounts_hv_gain_by_feasibility():
    policy = MultiFidelityActiveSearchPolicy(
        weights={
            "uncertainty": 0.0,
            "workflow_risk_coverage": 0.0,
            "design_diversity": 0.0,
        }
    )
    observations = [
        ActiveSearchObservation(
            candidate_id="frontier",
            fidelity="L3_systemc",
            objectives={
                "latency_ms": 100.0,
                "energy_mj": 100.0,
                "resource_pressure": 0.70,
                "data_movement_mb": 100.0,
            },
            feasible=True,
        )
    ]
    candidates = [
        ActiveSearchCandidate(
            candidate_id="large-gain-low-feasibility",
            objectives={
                "latency_ms": 84.0,
                "energy_mj": 84.0,
                "resource_pressure": 0.50,
                "data_movement_mb": 62.0,
            },
            constraints={"resource_pressure": 0.50, "feasibility": 0.05},
            evaluation_cost=1.0,
            design_key="low-feasibility",
        ),
        ActiveSearchCandidate(
            candidate_id="smaller-gain-feasible",
            objectives={
                "latency_ms": 92.0,
                "energy_mj": 92.0,
                "resource_pressure": 0.60,
                "data_movement_mb": 82.0,
            },
            constraints={"resource_pressure": 0.60, "feasibility": 0.95},
            evaluation_cost=1.0,
            design_key="feasible",
        ),
    ]

    selected = policy.select(candidates, observations=observations, budget=1)

    assert [row.candidate_id for row in selected] == ["smaller-gain-feasible"]
    assert selected[0].acquisition.components["feasibility_probability"] == 0.95


def test_active_search_normalizes_hv_gain_by_evaluation_cost():
    policy = MultiFidelityActiveSearchPolicy(
        weights={
            "uncertainty": 0.0,
            "workflow_risk_coverage": 0.0,
            "design_diversity": 0.0,
        }
    )
    observations = [
        ActiveSearchObservation(
            candidate_id="frontier",
            fidelity="L3_systemc",
            objectives={
                "latency_ms": 100.0,
                "energy_mj": 100.0,
                "resource_pressure": 0.70,
                "data_movement_mb": 100.0,
            },
            feasible=True,
        )
    ]
    candidates = [
        ActiveSearchCandidate(
            candidate_id="expensive-larger-gain",
            objectives={
                "latency_ms": 88.0,
                "energy_mj": 88.0,
                "resource_pressure": 0.52,
                "data_movement_mb": 68.0,
            },
            constraints={"resource_pressure": 0.52, "feasibility": 0.95},
            evaluation_cost=6.0,
            design_key="expensive",
        ),
        ActiveSearchCandidate(
            candidate_id="cheap-smaller-gain",
            objectives={
                "latency_ms": 92.0,
                "energy_mj": 92.0,
                "resource_pressure": 0.62,
                "data_movement_mb": 82.0,
            },
            constraints={"resource_pressure": 0.62, "feasibility": 0.95},
            evaluation_cost=1.0,
            design_key="cheap",
        ),
    ]

    selected = policy.select(candidates, observations=observations, budget=1)

    assert [row.candidate_id for row in selected] == ["cheap-smaller-gain"]
    chosen = selected[0].acquisition.components
    assert chosen["cost_normalized_hv_gain"] == chosen["feasibility_weighted_hv_gain"]


def test_active_search_report_exposes_ehvi_proxy_contract():
    policy = MultiFidelityActiveSearchPolicy()
    candidates = [
        ActiveSearchCandidate(
            candidate_id="a",
            objectives={
                "latency_ms": 80.0,
                "energy_mj": 80.0,
                "resource_pressure": 0.4,
                "data_movement_mb": 30.0,
            },
            constraints={"feasibility": 0.9, "resource_pressure": 0.4},
            uncertainty=0.2,
            evaluation_cost=1.0,
            risk_axes={"transfer_sync": 0.8},
            design_key="a",
        )
    ]

    report = policy.selection_report(candidates, budget=1)

    assert report["algorithm_contract"]["acquisition_family"] == "cost_aware_constrained_ehvi_proxy"
    assert report["algorithm_contract"]["cost_normalized_selection"] is True
    assert report["algorithm_contract"]["hypervolume_reference_point"]["latency_ms"] > 0.0
    components = report["selection"][0]["acquisition"]["components"]
    assert "exclusive_hypervolume_gain" in components
    assert "feasibility_weighted_hv_gain" in components
    assert "cost_normalized_hv_gain" in components


def test_active_search_batch_selection_rescores_after_each_choice_for_design_diversity():
    policy = MultiFidelityActiveSearchPolicy()
    candidates = [
        ActiveSearchCandidate(
            candidate_id="stream-b-best",
            objectives={
                "latency_ms": 78.0,
                "energy_mj": 80.0,
                "resource_pressure": 0.55,
                "data_movement_mb": 34.0,
            },
            constraints={"resource_pressure": 0.60, "feasibility": 0.92},
            uncertainty=0.10,
            evaluation_cost=1.0,
            risk_axes={"transfer_sync": 0.8},
            design_key="stream/hbm",
        ),
        ActiveSearchCandidate(
            candidate_id="stream-a-duplicate",
            objectives={
                "latency_ms": 77.0,
                "energy_mj": 81.0,
                "resource_pressure": 0.56,
                "data_movement_mb": 35.0,
            },
            constraints={"resource_pressure": 0.61, "feasibility": 0.92},
            uncertainty=0.10,
            evaluation_cost=1.0,
            risk_axes={"transfer_sync": 0.8},
            design_key="stream/hbm",
        ),
        ActiveSearchCandidate(
            candidate_id="tile-c-diverse",
            objectives={
                "latency_ms": 84.0,
                "energy_mj": 79.0,
                "resource_pressure": 0.57,
                "data_movement_mb": 33.0,
            },
            constraints={"resource_pressure": 0.62, "feasibility": 0.91},
            uncertainty=0.10,
            evaluation_cost=1.0,
            risk_axes={"transfer_sync": 0.8},
            design_key="tile/uram",
        ),
    ]

    selected = policy.select(candidates, budget=2)

    assert [row.candidate_id for row in selected] == ["stream-a-duplicate", "tile-c-diverse"]
    assert selected[1].acquisition.components["design_diversity"] == 1.0
    assert all(row.candidate.design_key != "stream/hbm" for row in selected[1:])


def test_active_search_selects_joint_candidate_and_fidelity_under_cost_budget():
    policy = MultiFidelityActiveSearchPolicy()
    observations = [
        ActiveSearchObservation(
            candidate_id="frontier",
            fidelity="L3_systemc",
            objectives={
                "latency_ms": 100.0,
                "energy_mj": 100.0,
                "resource_pressure": 0.70,
                "data_movement_mb": 100.0,
            },
            feasible=True,
        )
    ]
    candidates = [
        ActiveSearchCandidate(
            candidate_id="workflow-hbm-resident",
            objectives={
                "latency_ms": 86.0,
                "energy_mj": 88.0,
                "resource_pressure": 0.58,
                "data_movement_mb": 55.0,
            },
            constraints={"resource_pressure": 0.58, "feasibility": 0.94},
            uncertainty=0.34,
            evaluation_cost=1.0,
            risk_axes={"host_control_intensity": 0.8, "transfer_sync": 0.9},
            design_key="hbm/resident",
        ),
        ActiveSearchCandidate(
            candidate_id="kernel-only",
            objectives={
                "latency_ms": 94.0,
                "energy_mj": 97.0,
                "resource_pressure": 0.48,
                "data_movement_mb": 88.0,
            },
            constraints={"resource_pressure": 0.48, "feasibility": 0.96},
            uncertainty=0.10,
            evaluation_cost=1.0,
            risk_axes={"host_control_intensity": 0.1, "transfer_sync": 0.1},
            design_key="kernel/local",
        ),
    ]
    fidelities = [
        ActiveSearchFidelity(
            fidelity="L2_systemc_or_tlm",
            evaluation_cost=1.0,
            information_gain=0.45,
            uncertainty_reduction=0.35,
            calibration_value=0.35,
        ),
        ActiveSearchFidelity(
            fidelity="HLS_c_synthesis",
            evaluation_cost=8.0,
            information_gain=1.0,
            uncertainty_reduction=0.80,
            calibration_value=0.95,
            requires_observed_fidelities=("L2_systemc_or_tlm",),
        ),
    ]

    selected = policy.select_actions(
        candidates,
        fidelities=fidelities,
        observations=observations,
        action_budget=1,
        cost_budget=2.0,
    )

    assert len(selected) == 1
    assert selected[0].candidate_id == "workflow-hbm-resident"
    assert selected[0].fidelity == "L2_systemc_or_tlm"
    assert selected[0].components["action_cost"] <= 2.0
    assert selected[0].components["candidate_acquisition_score"] > 0.0
    assert selected[0].components["cost_normalized_action_value"] > 0.0


def test_active_search_can_promote_observed_candidate_to_required_next_fidelity():
    policy = MultiFidelityActiveSearchPolicy()
    observations = [
        ActiveSearchObservation(
            candidate_id="promising",
            fidelity="L2_systemc_or_tlm",
            objectives={
                "latency_ms": 96.0,
                "energy_mj": 98.0,
                "resource_pressure": 0.62,
                "data_movement_mb": 58.0,
            },
            feasible=True,
        )
    ]
    candidates = [
        ActiveSearchCandidate(
            candidate_id="promising",
            objectives={
                "latency_ms": 84.0,
                "energy_mj": 88.0,
                "resource_pressure": 0.60,
                "data_movement_mb": 48.0,
            },
            constraints={"resource_pressure": 0.60, "feasibility": 0.93},
            uncertainty=0.24,
            evaluation_cost=1.0,
            risk_axes={"transfer_sync": 0.9},
            design_key="hbm/pipeline",
        )
    ]
    fidelities = [
        ActiveSearchFidelity(
            fidelity="L2_systemc_or_tlm",
            evaluation_cost=1.0,
            information_gain=0.45,
        ),
        ActiveSearchFidelity(
            fidelity="HLS_c_synthesis",
            evaluation_cost=5.0,
            information_gain=1.0,
            uncertainty_reduction=0.75,
            calibration_value=0.90,
            requires_observed_fidelities=("L2_systemc_or_tlm",),
        ),
    ]

    selected = policy.select_actions(
        candidates,
        fidelities=fidelities,
        observations=observations,
        action_budget=1,
        cost_budget=6.0,
    )

    assert [row.action_id for row in selected] == ["promising::HLS_c_synthesis"]
    assert selected[0].components["prerequisites_satisfied"] == 1.0
    assert selected[0].components["already_observed_action"] == 0.0


def test_active_search_batch_prerequisites_require_prior_observations_not_same_batch_actions():
    policy = MultiFidelityActiveSearchPolicy()
    candidates = [
        ActiveSearchCandidate(
            candidate_id="candidate-a",
            objectives={
                "latency_ms": 84.0,
                "energy_mj": 88.0,
                "resource_pressure": 0.60,
                "data_movement_mb": 48.0,
            },
            constraints={"resource_pressure": 0.60, "feasibility": 0.93},
            uncertainty=0.24,
            evaluation_cost=1.0,
            risk_axes={"transfer_sync": 0.9},
            design_key="hbm/pipeline",
        )
    ]
    fidelities = [
        ActiveSearchFidelity(
            fidelity="L2_systemc_or_tlm",
            evaluation_cost=1.0,
            information_gain=0.45,
        ),
        ActiveSearchFidelity(
            fidelity="HLS_c_synthesis",
            evaluation_cost=1.1,
            information_gain=1.0,
            requires_observed_fidelities=("L2_systemc_or_tlm",),
        ),
    ]

    selected = policy.select_actions(
        candidates,
        fidelities=fidelities,
        action_budget=2,
        cost_budget=4.0,
    )

    assert [row.action_id for row in selected] == ["candidate-a::L2_systemc_or_tlm"]


def test_active_search_action_report_exposes_joint_candidate_fidelity_contract():
    policy = MultiFidelityActiveSearchPolicy()
    candidates = [
        ActiveSearchCandidate(
            candidate_id="a",
            objectives={
                "latency_ms": 80.0,
                "energy_mj": 82.0,
                "resource_pressure": 0.50,
                "data_movement_mb": 35.0,
            },
            constraints={"resource_pressure": 0.50, "feasibility": 0.92},
            uncertainty=0.20,
            evaluation_cost=1.0,
            risk_axes={"transfer_sync": 0.7},
            design_key="a",
        )
    ]
    fidelities = [
        ActiveSearchFidelity(
            fidelity="L2_systemc_or_tlm",
            evaluation_cost=1.0,
            information_gain=0.5,
        )
    ]

    report = policy.action_selection_report(
        candidates,
        fidelities=fidelities,
        action_budget=1,
        cost_budget=1.0,
    )

    assert report["schema_version"] == "dse.multifidelity_active_search.action_selection.v1"
    assert report["selected_action_ids"] == ["a::L2_systemc_or_tlm"]
    assert report["selection"][0]["candidate_id"] == "a"
    assert report["selection"][0]["fidelity"] == "L2_systemc_or_tlm"
    assert report["algorithm_contract"]["selection_scope"] == "joint_candidate_fidelity_action_space"
    assert report["algorithm_contract"]["fidelity_cost_aware_selection"] is True
    assert report["algorithm_contract"]["evidence_role"] == "feedback_calibration_not_search_objective"
