from dse_v2.mapping.multifidelity_benchmark import build_multifidelity_search_benchmark_report
from dse_v2.mapping.multifidelity_benchmark import build_multifidelity_search_benchmark_suite_report
from dse_v2.mapping.multifidelity_benchmark import build_workflow_conditioned_multifidelity_benchmark_suite_report
from dse_v2.mapping.multifidelity_validation import build_multifidelity_algorithm_validation_report
from dse_v2.mapping.multifidelity_validation import build_validation_gated_next_evaluation_queue
from dse_v2.mapping.multifidelity_validation import build_validation_gated_search_control_report
from dse_v2.reference_workloads.qe_workflow_fpga_abstraction import build_qe_workflow_fpga_abstraction


SCF_INPUT = """
&CONTROL
  calculation = 'scf',
  prefix = 'si',
/
&SYSTEM
  nat = 2,
  ntyp = 1,
  ecutwfc = 30.0,
  nbnd = 16,
/
&ELECTRONS
  electron_maxstep = 60,
/
K_POINTS automatic
4 4 2 0 0 0
"""


NSCF_INPUT = """
&CONTROL
  calculation = 'nscf',
  prefix = 'si',
/
&SYSTEM
  nat = 2,
  ntyp = 1,
  ecutwfc = 35.0,
  nbnd = 48,
/
K_POINTS automatic
8 8 4 0 0 0
"""


HOST_HEAVY_LOG = """
     number of k points=     12
     number of Kohn-Sham states= 16
     number of plane waves= 2048
     dense FFT grid: ( 40, 40, 32)
     iteration # 1
     iteration # 2
     iteration # 3
     h_psi        :      0.10s CPU      3.50s WALL
     FFT          :      0.03s CPU      1.20s WALL
     mix_rho      :      0.01s CPU      2.40s WALL
     convergence_check : 0.01s CPU      1.60s WALL
"""


DATA_HEAVY_LOG = """
     number of k points=     48
     number of Kohn-Sham states= 48
     number of plane waves= 8192
     dense FFT grid: ( 96, 96, 72)
     h_psi        :      0.20s CPU      12.00s WALL
     FFT          :      0.05s CPU      5.00s WALL
     c_bands      :      0.04s CPU      1.00s WALL
"""


def test_multifidelity_benchmark_exposes_independent_oracle_under_model_mismatch():
    report = build_multifidelity_search_benchmark_report(
        scenario_id="workflow_shift_resource_cliff",
        candidate_count=64,
        budgets=(2, 4, 8),
        top_k=5,
    )

    assert report["schema_version"] == "dse.multifidelity_search_benchmark.v1"
    assert report["scenario_id"] == "workflow_shift_resource_cliff"
    assert report["oracle"]["oracle_kind"] == "independent_synthetic_workflow_mismatch"
    assert report["oracle"]["not_derived_from_l1_objectives"] is True
    assert {
        "l1_bias",
        "noise",
        "resource_cliff",
        "data_residency_interaction",
        "workflow_shift",
        "host_control_penalty",
    }.issubset(report["oracle"]["mismatch_axes"])
    assert report["candidate_count"] == 64
    assert report["budgets"] == [2, 4, 8]
    assert report["oracle"]["best_candidate_id"]

    policy_ids = {row["policy_id"] for row in report["policies"]}
    assert {
        "wamf_constrained_active_pareto",
        "sequential_surrogate_expected_improvement",
        "nsga2_ea_l1_multi_objective",
        "cheap_l1_edp",
        "random_seeded",
        "manual_hbm_streaming",
        "kernel_hotspot_only",
    }.issubset(policy_ids)

    wamf = next(row for row in report["policies"] if row["policy_id"] == "wamf_constrained_active_pareto")
    surrogate = next(row for row in report["policies"] if row["policy_id"] == "sequential_surrogate_expected_improvement")
    ea = next(row for row in report["policies"] if row["policy_id"] == "nsga2_ea_l1_multi_objective")
    cheap = next(row for row in report["policies"] if row["policy_id"] == "cheap_l1_edp")
    random = next(row for row in report["policies"] if row["policy_id"] == "random_seeded")

    assert wamf["uses_global_acquisition"] is True
    assert wamf["uses_oracle_during_selection"] is False
    assert surrogate["uses_oracle_during_selection"] is False
    assert surrogate["selection_model"] == "online_residual_expected_improvement"
    assert surrogate["initial_design_count"] >= 2
    assert surrogate["observation_count"] == 8
    assert surrogate["budget_curve"][-1]["budget"] == 8
    assert surrogate["budget_curve"][-1]["simple_regret"] <= cheap["budget_curve"][-1]["simple_regret"]
    assert ea["selection_model"] == "nsga2_style_evolutionary_search_on_l1_objectives"
    assert ea["uses_oracle_during_selection"] is False
    assert ea["generation_count"] >= 3
    assert ea["population_size"] >= 16
    assert ea["budget_curve"][-1]["budget"] == 8
    assert ea["budget_curve"][-1]["simple_regret"] >= 0.0
    assert wamf["budget_curve"][-1]["budget"] == 8
    assert wamf["budget_curve"][-1]["simple_regret"] <= cheap["budget_curve"][-1]["simple_regret"]
    assert wamf["budget_curve"][-1]["oracle_pareto_coverage_at_budget"] > 0.0
    assert 0.0 <= wamf["budget_curve"][-1]["hypervolume_ratio"] <= 1.0
    assert wamf["budget_curve"][-1]["cost_normalized_hv_gain_at_budget"] >= 0.0
    assert 0.0 <= wamf["budget_curve"][-1]["feasibility_weighted_hv_ratio"] <= 1.0
    assert all(
        "hypervolume_ratio" in point and "oracle_pareto_coverage_at_budget" in point
        for policy in report["policies"]
        for point in policy["budget_curve"]
    )
    assert wamf["budget_curve"][-1]["top_k_hit"] is True
    assert random["random_seed"] == 17
    assert all(point["simple_regret"] >= 0.0 for policy in report["policies"] for point in policy["budget_curve"])


def test_multifidelity_benchmark_ablation_removes_workflow_risk_from_wamf():
    report = build_multifidelity_search_benchmark_report(
        scenario_id="host_control_heavy_shift",
        candidate_count=72,
        budgets=(4, 8),
        top_k=5,
        include_ablations=True,
    )

    ablations = {row["policy_id"]: row for row in report["ablations"]}
    assert "wamf_no_workflow_risk" in ablations
    assert "wamf_no_uncertainty" in ablations
    assert "wamf_no_diversity" in ablations
    assert "wamf_no_feasibility" in ablations

    full = next(row for row in report["policies"] if row["policy_id"] == "wamf_constrained_active_pareto")
    no_workflow = ablations["wamf_no_workflow_risk"]

    assert no_workflow["removed_components"] == ["workflow_risk_coverage"]
    assert no_workflow["budget_curve"][-1]["budget"] == 8
    assert no_workflow["budget_curve"][-1]["simple_regret"] >= full["budget_curve"][-1]["simple_regret"]
    assert report["experiment_role"] == "algorithm_method_validation_not_hardware_evidence"


def test_multifidelity_benchmark_surrogate_baseline_records_observation_only_updates():
    report = build_multifidelity_search_benchmark_report(
        scenario_id="workflow_shift_resource_cliff",
        candidate_count=64,
        budgets=(3, 6),
        top_k=5,
    )

    surrogate = next(
        row for row in report["policies"]
        if row["policy_id"] == "sequential_surrogate_expected_improvement"
    )

    assert surrogate["selection_model"] == "online_residual_expected_improvement"
    assert surrogate["uses_oracle_during_selection"] is False
    assert surrogate["surrogate_update_rule"] == "fit_residuals_only_from_previously_selected_observations"
    assert surrogate["trace"]
    assert [row["iteration"] for row in surrogate["trace"]] == list(range(1, 7))
    assert surrogate["trace"][0]["selection_phase"] == "initial_diverse_l1_seed"
    assert surrogate["trace"][3]["selection_phase"] == "surrogate_expected_improvement"
    assert all(
        row["oracle_observation_available_after_selection"] is True
        for row in surrogate["trace"]
    )
    assert all(
        row["observed_before_selection_count"] == row["iteration"] - 1
        for row in surrogate["trace"]
    )
    assert all(
        row["unobserved_oracle_used_for_selection"] is False
        for row in surrogate["trace"]
    )


def test_multifidelity_benchmark_ea_baseline_records_oracle_free_generations():
    report = build_multifidelity_search_benchmark_report(
        scenario_id="workflow_shift_resource_cliff",
        candidate_count=80,
        budgets=(4, 8),
        top_k=5,
    )

    ea = next(
        row for row in report["policies"]
        if row["policy_id"] == "nsga2_ea_l1_multi_objective"
    )

    assert ea["uses_oracle_during_selection"] is False
    assert ea["selection_model"] == "nsga2_style_evolutionary_search_on_l1_objectives"
    assert ea["objectives_minimized"] == [
        "latency_ms",
        "energy_mj",
        "resource_pressure",
        "data_movement_mb",
    ]
    assert ea["generation_trace"]
    assert len(ea["generation_trace"]) == ea["generation_count"]
    assert all(
        row["oracle_used_for_fitness"] is False
        for row in ea["generation_trace"]
    )
    assert all(
        row["population_size"] == ea["population_size"]
        for row in ea["generation_trace"]
    )
    assert len(ea["selected_candidate_ids"]) == 8
    assert len(set(ea["selected_candidate_ids"])) == 8


def test_multifidelity_benchmark_budget_points_include_pareto_quality_metrics():
    report = build_multifidelity_search_benchmark_report(
        scenario_id="workflow_shift_resource_cliff",
        candidate_count=72,
        budgets=(2, 4, 8),
        top_k=5,
    )

    assert report["oracle"]["pareto_frontier_size"] > 0
    assert report["oracle"]["reference_hypervolume"] > 0.0
    for policy in report["policies"]:
        for point in policy["budget_curve"]:
            assert 0.0 <= point["oracle_pareto_coverage_at_budget"] <= 1.0
            assert 0.0 <= point["hypervolume_ratio"] <= 1.0
            assert 0.0 <= point["feasibility_weighted_hv_ratio"] <= 1.0
            assert point["cost_normalized_hv_gain_at_budget"] >= 0.0
            assert point["selected_pareto_hit_count"] >= 0


def test_workflow_conditioned_benchmark_pareto_coverage_uses_design_signatures():
    report = build_multifidelity_search_benchmark_report(
        scenario_id="workflow_shift_resource_cliff",
        candidate_count=128,
        budgets=(4, 8, 12),
        top_k=5,
        workflow_conditioning={
            "workflow_id": "signature_regression",
            "host_control_pressure": 0.72,
            "data_movement_pressure": 0.18,
            "post_processing_pressure": 0.1,
            "stage_count": 2,
            "source_schema": "dse.workflow_feature_contract.v1",
            "feature_contract_schema": "dse.workflow_feature_contract.v1",
        },
    )

    policy = next(row for row in report["policies"] if row["policy_id"] == "nsga2_ea_l1_multi_objective")
    budget_8 = next(point for point in policy["budget_curve"] if point["budget"] == 8)

    assert budget_8["selected_pareto_hit_count"] == 0
    assert budget_8["exact_oracle_pareto_coverage_at_budget"] == 0.0
    assert budget_8["selected_pareto_signature_hit_count"] == 1
    assert budget_8["oracle_pareto_coverage_at_budget"] == 0.25


def test_multifidelity_benchmark_suite_aggregates_multi_scenario_policy_statistics():
    suite = build_multifidelity_search_benchmark_suite_report(
        scenario_ids=(
            "workflow_shift_resource_cliff",
            "host_control_heavy_shift",
            "data_residency_resource_cliff",
        ),
        candidate_count=64,
        budgets=(2, 4, 8),
        top_k=5,
    )

    assert suite["schema_version"] == "dse.multifidelity_search_benchmark_suite.v1"
    assert suite["scenario_count"] == 3
    assert suite["budgets"] == [2, 4, 8]
    assert suite["final_budget"] == 8
    assert suite["experiment_role"] == "algorithm_robustness_validation_not_hardware_evidence"
    assert len(suite["scenario_reports"]) == 3
    assert all(
        report["oracle"]["not_derived_from_l1_objectives"] is True
        for report in suite["scenario_reports"]
    )

    policy_stats = {row["policy_id"]: row for row in suite["policy_statistics"]}
    assert {
        "wamf_constrained_active_pareto",
        "sequential_surrogate_expected_improvement",
        "nsga2_ea_l1_multi_objective",
        "cheap_l1_edp",
        "random_seeded",
    }.issubset(policy_stats)
    wamf = policy_stats["wamf_constrained_active_pareto"]
    cheap = policy_stats["cheap_l1_edp"]
    random = policy_stats["random_seeded"]

    assert wamf["scenario_count"] == 3
    assert 0.0 <= wamf["top_k_hit_rate"] <= 1.0
    assert 0.0 <= wamf["win_rate_by_simple_regret"] <= 1.0
    assert wamf["mean_simple_regret"] <= cheap["mean_simple_regret"]
    assert wamf["mean_simple_regret"] <= random["mean_simple_regret"]
    assert wamf["mean_hypervolume_ratio"] >= 0.0
    assert wamf["std_simple_regret"] >= 0.0
    assert suite["best_policy_by_mean_regret"]["policy_id"]


def test_workflow_conditioned_multifidelity_benchmark_uses_qe_abstraction_features():
    host_heavy = build_qe_workflow_fpga_abstraction(
        {
            "workflow_id": "host_heavy_scf_workflow",
            "stages": [
                {
                    "stage_id": "scf",
                    "program": "pw.x",
                    "input": SCF_INPUT,
                    "stdout": HOST_HEAVY_LOG,
                },
            ],
        },
        workload_id="host_heavy_scf_workflow",
    )
    data_heavy = build_qe_workflow_fpga_abstraction(
        {
            "workflow_id": "data_heavy_nscf_bands_workflow",
            "stages": [
                {
                    "stage_id": "scf",
                    "program": "pw.x",
                    "input": SCF_INPUT,
                    "stdout": HOST_HEAVY_LOG,
                },
                {
                    "stage_id": "nscf",
                    "program": "pw.x",
                    "input": NSCF_INPUT,
                    "stdout": DATA_HEAVY_LOG,
                },
                {
                    "stage_id": "bands",
                    "program": "bands.x",
                    "profile": {"phases": {"band_path_projection": 2.0, "write_bands": 1.0}},
                    "depends_on": ["nscf"],
                },
            ],
        },
        workload_id="data_heavy_nscf_bands_workflow",
    )

    suite = build_workflow_conditioned_multifidelity_benchmark_suite_report(
        workflow_abstractions=[host_heavy, data_heavy],
        candidate_count=64,
        budgets=(2, 4, 8),
        top_k=5,
        include_ablations=True,
    )

    assert suite["schema_version"] == "dse.workflow_conditioned_multifidelity_search_benchmark_suite.v1"
    assert suite["conditioning_source"] == "workflow_feature_contract"
    assert suite["scenario_count"] == 2
    assert suite["workflow_ids"] == [
        "host_heavy_scf_workflow",
        "data_heavy_nscf_bands_workflow",
    ]
    assert suite["experiment_role"] == "workflow_conditioned_algorithm_validation_not_hardware_evidence"
    assert "wamf_constrained_active_pareto" in {
        row["policy_id"] for row in suite["policy_statistics"]
    }

    host_report, data_report = suite["scenario_reports"]
    assert host_report["schema_version"] == "dse.multifidelity_search_benchmark.v1"
    assert host_report["oracle"]["oracle_kind"] == "workflow_conditioned_independent_synthetic_mismatch"
    assert host_report["workflow_conditioning"]["workflow_id"] == "host_heavy_scf_workflow"
    assert host_report["workflow_conditioning"]["host_control_pressure"] > 0.0
    assert host_report["workflow_conditioning"]["stage_count"] == 1
    assert "host_control_pressure" in host_report["oracle"]["mismatch_axes"]

    assert data_report["workflow_conditioning"]["workflow_id"] == "data_heavy_nscf_bands_workflow"
    assert data_report["workflow_conditioning"]["stage_count"] == 3
    assert data_report["workflow_conditioning"]["data_movement_pressure"] >= host_report["workflow_conditioning"][
        "data_movement_pressure"
    ]
    assert data_report["workflow_conditioning"]["post_processing_pressure"] > 0.0
    assert "data_movement_pressure" in data_report["oracle"]["mismatch_axes"]
    assert "post_processing_pressure" in data_report["oracle"]["mismatch_axes"]

    for report in suite["scenario_reports"]:
        assert report["oracle"]["not_derived_from_l1_objectives"] is True
        assert report["workflow_conditioning"]["source_schema"] == "dse.qe_workflow_fpga_abstraction.v1"
        assert report["workflow_conditioning"]["feature_contract_schema"] == "dse.workflow_feature_contract.v1"
        assert report["workflow_conditioning"]["conditioning_applied_to_oracle"] is True
        assert report["policies"]
        assert report["ablations"]


def test_multifidelity_algorithm_validation_flags_baseline_loss_and_rank_inversion():
    report = build_multifidelity_algorithm_validation_report(
        proposed_policy_id="wamf_generic_active_pareto",
        policy_results=[
            {
                "policy_id": "wamf_generic_active_pareto",
                "final_best_edp": 196.0,
                "final_oracle_rank": 51,
                "top_k_hit": False,
            },
            {
                "policy_id": "single_fidelity_l1_edp",
                "final_best_edp": 133.0,
                "final_oracle_rank": 1,
                "top_k_hit": True,
            },
            {
                "policy_id": "nsga2_lite_multi_objective",
                "final_best_edp": 133.0,
                "final_oracle_rank": 1,
                "top_k_hit": True,
            },
        ],
        independent_feedback={
            "rank_correlation": {
                "l1_estimated_edp_vs_l3_edp_spearman": -0.667,
                "status": "usable",
            },
            "sample_count": 8,
        },
    )

    assert report["schema_version"] == "dse.multifidelity_algorithm_validation.v1"
    assert report["status"] == "algorithm_not_validated"
    assert report["proposed_policy_id"] == "wamf_generic_active_pareto"
    assert report["proposed_policy"]["final_oracle_rank"] == 51
    assert report["best_policy_by_edp"]["policy_id"] == "single_fidelity_l1_edp"
    assert report["best_policy_by_rank"]["policy_id"] == "single_fidelity_l1_edp"
    assert report["independent_feedback"]["rank_correlation"] == -0.667
    assert "proposed_policy_loses_edp_to_baseline:single_fidelity_l1_edp" in report["blockers"]
    assert "proposed_policy_loses_rank_to_baseline:single_fidelity_l1_edp" in report["blockers"]
    assert "negative_independent_feedback_rank_correlation" in report["blockers"]
    assert report["recommended_next_action"] == "recalibrate_models_and_run_exploration_fallback"


def test_multifidelity_algorithm_validation_accepts_clear_win_without_feedback_inversion():
    report = build_multifidelity_algorithm_validation_report(
        proposed_policy_id="wamf_generic_active_pareto",
        policy_results=[
            {
                "policy_id": "wamf_generic_active_pareto",
                "final_best_edp": 96.0,
                "final_oracle_rank": 1,
                "top_k_hit": True,
            },
            {
                "policy_id": "single_fidelity_l1_edp",
                "final_best_edp": 115.0,
                "final_oracle_rank": 3,
                "top_k_hit": False,
            },
            {
                "policy_id": "nsga2_lite_multi_objective",
                "final_best_edp": 110.0,
                "final_oracle_rank": 2,
                "top_k_hit": True,
            },
        ],
        independent_feedback={
            "rank_correlation": {
                "l1_estimated_edp_vs_l3_edp_spearman": 0.71,
                "status": "usable",
            },
            "sample_count": 8,
        },
    )

    assert report["status"] == "algorithm_validated_for_model_evaluation"
    assert report["blockers"] == []
    assert report["recommended_next_action"] == "promote_selected_candidates_to_independent_fidelity"


def test_validation_gated_search_control_uses_exploration_fallback_when_algorithm_fails():
    validation = build_multifidelity_algorithm_validation_report(
        proposed_policy_id="wamf_generic_active_pareto",
        policy_results=[
            {
                "policy_id": "wamf_generic_active_pareto",
                "final_best_edp": 196.0,
                "final_oracle_rank": 51,
                "top_k_hit": False,
            },
            {
                "policy_id": "single_fidelity_l1_edp",
                "final_best_edp": 133.0,
                "final_oracle_rank": 1,
                "top_k_hit": True,
            },
        ],
        independent_feedback={
            "rank_correlation": {
                "l1_estimated_edp_vs_l3_edp_spearman": -0.667,
                "status": "usable",
            },
            "sample_count": 8,
        },
    )

    control = build_validation_gated_search_control_report(
        validation_report=validation,
        candidates=[
            {
                "candidate_id": "cheap-model-favorite",
                "design_key": "hbm/wide",
                "objectives": {"latency_ms": 80.0, "energy_mj": 80.0},
                "uncertainty": 0.03,
                "risk_axes": {"host_control_intensity": 0.05},
                "evaluation_cost": 1.0,
            },
            {
                "candidate_id": "uncertain-host-control",
                "design_key": "cpu-control/hybrid",
                "objectives": {"latency_ms": 125.0, "energy_mj": 110.0},
                "uncertainty": 0.82,
                "risk_axes": {"host_control_intensity": 0.95, "transfer_sync": 0.70},
                "evaluation_cost": 1.4,
            },
            {
                "candidate_id": "uncertain-data-residency",
                "design_key": "uram/tiled",
                "objectives": {"latency_ms": 130.0, "energy_mj": 105.0},
                "uncertainty": 0.76,
                "risk_axes": {"data_residency_interaction": 0.92, "transfer_sync": 0.80},
                "evaluation_cost": 1.2,
            },
        ],
        budget=2,
    )

    assert control["schema_version"] == "dse.multifidelity_search_control.v1"
    assert control["mode"] == "exploration_fallback"
    assert control["control_reason"] == "algorithm_not_validated"
    assert control["recommended_next_action"] == "recalibrate_models_and_run_exploration_fallback"
    assert control["selected_candidate_ids"] == [
        "uncertain-host-control",
        "uncertain-data-residency",
    ]
    assert control["selection"][0]["fallback_score_components"]["uncertainty"] == 0.82
    assert control["selection"][0]["fallback_score_components"]["risk_coverage"] > 0.0
    assert "negative_independent_feedback_rank_correlation" in control["validation_blockers"]


def test_validation_gated_search_control_keeps_nominal_policy_when_algorithm_validates():
    validation = build_multifidelity_algorithm_validation_report(
        proposed_policy_id="wamf_generic_active_pareto",
        policy_results=[
            {
                "policy_id": "wamf_generic_active_pareto",
                "final_best_edp": 96.0,
                "final_oracle_rank": 1,
                "top_k_hit": True,
            },
            {
                "policy_id": "single_fidelity_l1_edp",
                "final_best_edp": 115.0,
                "final_oracle_rank": 3,
                "top_k_hit": False,
            },
        ],
        independent_feedback={
            "rank_correlation": {
                "l1_estimated_edp_vs_l3_edp_spearman": 0.71,
                "status": "usable",
            },
            "sample_count": 8,
        },
    )

    control = build_validation_gated_search_control_report(
        validation_report=validation,
        candidates=[
            {"candidate_id": "a", "uncertainty": 0.9, "risk_axes": {"host": 0.9}},
        ],
        budget=1,
    )

    assert control["mode"] == "nominal_policy"
    assert control["selected_candidate_ids"] == []
    assert control["recommended_next_action"] == "promote_selected_candidates_to_independent_fidelity"


def test_validation_gated_next_evaluation_queue_uses_fallback_selection_after_validation_failure():
    control = {
        "schema_version": "dse.multifidelity_search_control.v1",
        "mode": "exploration_fallback",
        "control_reason": "algorithm_not_validated",
        "recommended_next_action": "recalibrate_models_and_run_exploration_fallback",
        "selected_candidate_ids": ["uncertain-host-control", "uncertain-data-residency"],
        "selection": [
            {
                "candidate_id": "uncertain-host-control",
                "design_key": "cpu-control/hybrid",
                "fallback_score": 0.86,
                "selection_reason": "calibration_exploration_after_validation_failure",
            },
            {
                "candidate_id": "uncertain-data-residency",
                "design_key": "uram/tiled",
                "fallback_score": 0.82,
                "selection_reason": "calibration_exploration_after_validation_failure",
            },
        ],
    }

    queue = build_validation_gated_next_evaluation_queue(
        search_control=control,
        nominal_candidates=[
            {
                "candidate_id": "cheap-model-favorite",
                "design_key": "hbm/wide",
                "objectives": {"latency_ms": 80.0},
            },
            {
                "candidate_id": "uncertain-host-control",
                "design_key": "cpu-control/hybrid",
                "objectives": {"latency_ms": 125.0},
            },
            {
                "candidate_id": "uncertain-data-residency",
                "design_key": "uram/tiled",
                "objectives": {"latency_ms": 130.0},
            },
        ],
        budget=2,
        next_fidelity="L3_generic_sim_or_systemc",
    )

    assert queue["schema_version"] == "dse.multifidelity_next_evaluation_queue.v1"
    assert queue["mode"] == "exploration_fallback"
    assert queue["selected_candidate_ids"] == [
        "uncertain-host-control",
        "uncertain-data-residency",
    ]
    assert "cheap-model-favorite" not in queue["selected_candidate_ids"]
    assert [row["candidate_id"] for row in queue["queue"]] == queue["selected_candidate_ids"]
    assert all(row["recommended_next_fidelity"] == "L3_generic_sim_or_systemc" for row in queue["queue"])
    assert all(
        row["queue_reason"] == "calibration_exploration_after_validation_failure"
        for row in queue["queue"]
    )
    assert queue["algorithm_contract"]["domain_neutral"] is True
    assert queue["algorithm_contract"]["validation_controls_next_iteration"] is True
