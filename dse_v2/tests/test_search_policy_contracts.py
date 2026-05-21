from dse_v2.mapping.search_policy import (
    BottleneckGuidedPolicy,
    ComponentCapability,
    HIERARCHICAL_FUNNEL_STAGES,
    HierarchicalFunnelSearchPolicy,
    RandomBaselinePolicy,
    SearchProblem,
    SeededBeamSearchPolicy,
)


def test_component_capability_supports_returns_deterministic_blockers():
    capability = ComponentCapability(
        component_id="fpga_fft",
        op_semantics=("fft", "reduction"),
        dtypes=("fp64",),
        schedules=("streaming",),
        placements=("fpga",),
        precision_policies=("strict",),
    )

    ok = capability.supports("fft", "fp64", "streaming", "fpga", "strict")
    blocked = capability.supports("gemm", "fp32", "batch", "gpu", "relaxed")

    assert ok.supported is True
    assert ok.blockers == ()
    assert blocked.supported is False
    assert blocked.blockers == (
        "unsupported_op:gemm",
        "unsupported_dtype:fp32",
        "unsupported_schedule:batch",
        "unsupported_placement:gpu",
        "unsupported_precision_policy:relaxed",
    )


def test_seeded_beam_records_parameters_provenance_and_promotion_reason():
    problem = SearchProblem(
        problem_id="p1",
        workload_run_id="w1",
        objective="maximize throughput",
        parameters={"pe_count": [1, 2], "memory": ["local", "shared"]},
        seed_candidates=({"pe_count": 8, "memory": "local"},),
    )
    policy = SeededBeamSearchPolicy()

    records = policy.propose(problem, budget=2)
    payloads = [record.to_dict() for record in records]

    assert len(records) == 2
    assert all(payload["parameters"] for payload in payloads)
    assert all(payload["parameter_hash"].startswith("sha256:") for payload in payloads)
    assert all(
        payload["provenance"]["candidate_identity_policy"]
        == "stable_problem_policy_parameter_hash"
        for payload in payloads
    )
    assert all(payload["provenance"]["policy_name"] == "seeded_beam" for payload in payloads)
    assert all("promoted_for_simulation" in payload["promotion_reasons"] for payload in payloads)
    assert all(payload["step2_screenable"] is True for payload in payloads)
    assert all(payload["step3_evaluable"] is True for payload in payloads)
    assert all(payload["simulation_eligible"] is True for payload in payloads)
    assert all(payload["simulation_blockers"] == [] for payload in payloads)


def test_random_baseline_is_seeded_and_checkpoint_observes_feedback():
    problem = SearchProblem(
        problem_id="p2",
        workload_run_id="w2",
        objective="maximize score",
        parameters={"tile": [1, 2, 4], "target": ["host", "fpga"]},
    )
    policy_a = RandomBaselinePolicy(seed=7)
    policy_b = RandomBaselinePolicy(seed=7)

    a = [record.to_dict()["parameters"] for record in policy_a.propose(problem, budget=3)]
    b = [record.to_dict()["parameters"] for record in policy_b.propose(problem, budget=3)]
    assert a == b

    first_id = next(iter(policy_a.checkpoint(problem).to_dict()["candidates"]))["candidate_id"]
    policy_a.observe(first_id, {"latency_ms": 3.2, "promoted": False})
    checkpoint = policy_a.checkpoint(problem).to_dict()

    assert checkpoint["schema_version"] == "dse.step2.search_checkpoint.v1"
    assert checkpoint["observed_count"] == 1
    assert any(candidate["observed_metrics"].get("latency_ms") == 3.2 for candidate in checkpoint["candidates"])


def test_bottleneck_guided_policy_emits_auditable_candidate_records():
    problem = SearchProblem(
        problem_id="p3",
        workload_run_id="w3",
        objective="maximize bandwidth",
        parameters={"dma_channels": [1, 4], "pe_count": [2, 8]},
    )
    policy = BottleneckGuidedPolicy(bottleneck_keys=("dma_channels",))

    records = policy.propose(problem, budget=4)

    assert len(records) == 4
    assert {record.generation_reason for record in records} == {"bottleneck_guided_parameter_grid"}
    assert all(record.provenance["workload_run_id"] == "w3" for record in records)
    assert all(record.to_dict()["simulation_eligible"] for record in records)


def test_hierarchical_funnel_records_required_stages_and_isolates_exploratory_rows():
    problem = SearchProblem(
        problem_id="p4",
        workload_run_id="w4",
        objective="maximize throughput",
        parameters={
            "release_lane": ["release", "exploratory"],
            "template_family": ["streaming", "wide"],
            "pe_count": [4],
        },
        constraints={
            "formal_pareto_lane_field": "release_lane",
            "release_lane": "release",
            "hierarchical_funnel_stages": HIERARCHICAL_FUNNEL_STAGES,
            "requires_physical_evidence": True,
        },
    )
    policy = HierarchicalFunnelSearchPolicy(bottleneck_keys=("pe_count",))

    records = policy.propose(problem, budget=4)
    payloads = [record.to_dict() for record in records]
    release_rows = [payload for payload in payloads if payload["parameters"]["release_lane"] == "release"]
    exploratory_rows = [payload for payload in payloads if payload["parameters"]["release_lane"] == "exploratory"]

    assert release_rows
    assert exploratory_rows
    assert all(payload["generation_reason"] == "hierarchical_funnel_search" for payload in payloads)
    assert all(
        [stage["stage_id"] for stage in payload["provenance"]["funnel_stages"]]
        == list(HIERARCHICAL_FUNNEL_STAGES)
        for payload in payloads
    )
    assert all(payload["simulation_eligible"] is True for payload in release_rows)
    assert all("formal_release_pareto_eligible" in payload["promotion_reasons"] for payload in release_rows)
    assert all(payload["simulation_eligible"] is False for payload in exploratory_rows)
    assert all("non_release_lane:exploratory" in payload["blocker_reasons"] for payload in exploratory_rows)
    assert all(
        payload["provenance"]["release_lane_policy"]["exploratory_rows_can_enter_formal_pareto"] is False
        for payload in payloads
    )
    assert all(
        payload["provenance"]["release_lane_policy"]["formal_pareto_lane_field"] == "release_lane"
        and payload["provenance"]["release_lane_policy"]["release_lane"] == "release"
        for payload in payloads
    )


def test_hierarchical_funnel_keeps_legacy_tier_constraints_non_authoritative():
    problem = SearchProblem(
        problem_id="p4-legacy",
        workload_run_id="w4-legacy",
        objective="maximize throughput",
        parameters={
            "candidate_tier": ["release", "exploratory"],
            "template_family": ["streaming"],
        },
        constraints={
            "formal_pareto_tier_field": "candidate_tier",
            "release_tier": "release",
            "hierarchical_funnel_stages": HIERARCHICAL_FUNNEL_STAGES,
        },
    )
    policy = HierarchicalFunnelSearchPolicy()

    payloads = [record.to_dict() for record in policy.propose(problem, budget=2)]
    exploratory_rows = [
        payload for payload in payloads
        if payload["parameters"]["candidate_tier"] == "exploratory"
    ]

    assert exploratory_rows
    assert all("non_release_lane:exploratory" in row["blocker_reasons"] for row in exploratory_rows)
    assert all(
        payload["provenance"]["release_lane_policy"]["lane_field_source"]
        == "legacy_formal_pareto_tier_field"
        for payload in payloads
    )
    assert all(
        payload["provenance"]["release_lane_policy"]["legacy_compatibility"]
        ["legacy_tier_constraints_authoritative"] is False
        for payload in payloads
    )
    assert all(
        payload["provenance"]["release_tier_policy"]["compatibility_alias_for"]
        == "release_lane_policy"
        for payload in payloads
    )


def test_hierarchical_funnel_observations_change_later_proposal_order():
    problem = SearchProblem(
        problem_id="p5",
        workload_run_id="w5",
        objective="maximize throughput",
        parameters={
            "release_lane": ["release"],
            "template_family": ["baseline", "calibrated"],
            "pe_count": [1],
        },
        constraints={"formal_pareto_lane_field": "release_lane", "release_lane": "release"},
    )
    policy = HierarchicalFunnelSearchPolicy()

    first_round = policy.propose(problem, budget=2)
    baseline = next(record for record in first_round if record.parameters["template_family"] == "baseline")
    policy.observe(
        baseline.candidate_id,
        {
            "step4_verdict": "trusted_pass",
            "step4_quality_score": 95,
            "calibrated_score_delta": 100,
            "promoted": True,
        },
    )
    second_round = policy.propose(problem, budget=1)
    checkpoint = policy.checkpoint(problem).to_dict()

    assert second_round[0].parameters["template_family"] == "baseline"
    assert second_round[0].candidate_id == baseline.candidate_id
    assert second_round[0].parameter_hash == baseline.parameter_hash
    assert checkpoint["observed_count"] == 1
    assert checkpoint["best_candidate_id"] == second_round[0].candidate_id


def test_hierarchical_funnel_considers_full_grid_before_budgeting_outputs():
    problem = SearchProblem(
        problem_id="p6",
        workload_run_id="w6",
        objective="maximize throughput",
        parameters={
            "release_lane": ["release"],
            "template_family": ["small", "medium", "large"],
            "pe_count": [1, 2, 100],
        },
        constraints={"formal_pareto_lane_field": "release_lane", "release_lane": "release"},
    )
    policy = HierarchicalFunnelSearchPolicy()

    selected = policy.propose(problem, budget=1)[0].to_dict()
    enumeration = selected["provenance"]["search_space_enumeration"]

    assert selected["parameters"]["pe_count"] == 100
    assert enumeration["grid_candidate_count"] == 9
    assert enumeration["grid_candidate_enumerated_count"] == 9
    assert enumeration["complete_grid_enumeration"] is True
    assert enumeration["output_budget"] == 1


def test_hierarchical_funnel_declares_bounded_candidate_enumeration():
    problem = SearchProblem(
        problem_id="p7",
        workload_run_id="w7",
        objective="maximize throughput",
        parameters={
            "release_lane": ["release"],
            "template_family": ["small", "medium", "large"],
            "pe_count": [1, 2, 100],
        },
        constraints={
            "formal_pareto_lane_field": "release_lane",
            "release_lane": "release",
            "max_candidate_enumeration": 4,
        },
    )
    policy = HierarchicalFunnelSearchPolicy()

    selected = policy.propose(problem, budget=1)[0].to_dict()
    enumeration = selected["provenance"]["search_space_enumeration"]

    assert enumeration["grid_candidate_count"] == 9
    assert enumeration["grid_candidate_enumerated_count"] == 4
    assert enumeration["complete_grid_enumeration"] is False
    assert enumeration["max_candidate_enumeration"] == 4
