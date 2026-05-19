from dse_v2.mapping.search_policy import (
    BottleneckGuidedPolicy,
    ComponentCapability,
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
