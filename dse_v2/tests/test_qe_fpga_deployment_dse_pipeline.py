#!/usr/bin/env python3
"""CLI regression for the QE-to-FPGA deployment DSE L1 pipeline."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.qe_workflow_fpga_abstraction import build_qe_workflow_fpga_abstraction


REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_qe_fpga_deployment_dse.py"
VERIFY_REPLAY = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "verify_qe_fpga_replay_manifest.py"
RUN_L3_GSIM = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_qe_fpga_l3_generic_sim_feedback.py"
RUN_L3_CLOSED_LOOP = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_qe_fpga_l3_feedback_closed_loop.py"
BUILD_REPRESENTATIVE_CORPUS = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "build_qe_fpga_representative_workflow_corpus.py"
PREFLIGHT_CORPUS = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "build_qe_fpga_workflow_corpus_preflight.py"
BUILD_MEASURED_WORKFLOW = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "build_qe_measured_workflow_bundle.py"
RUN_MEASURED_WORKFLOW = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_qe_measured_workflow_capture.py"
IMPORT_QE_REFERENCE_BUNDLE = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "import_qe_measured_reference_bundle.py"
GENERIC_SIM = REPO_ROOT / "model" / "generic_sim_backend" / "build" / "generic_sim"


EXTERNAL_SCF_INPUT = """
&CONTROL
  calculation = 'scf',
  prefix = 'external_si',
/
&SYSTEM
  nat = 2,
  ntyp = 1,
  ecutwfc = 24.0,
  nbnd = 14,
/
&ELECTRONS
  electron_maxstep = 50,
/
K_POINTS automatic
3 3 2 0 0 0
"""


EXTERNAL_SCF_LOG = """
     number of k points=     8
     number of Kohn-Sham states= 14
     number of plane waves= 1536
     dense FFT grid: ( 36, 36, 30)
     iteration # 1
     iteration # 2
     h_psi        :      0.20s CPU      6.20s WALL
     FFT          :      0.05s CPU      1.80s WALL
     mix_rho      :      0.02s CPU      0.40s WALL
     convergence has been achieved in 2 iterations
"""


EXTERNAL_NSCF_INPUT = """
&CONTROL
  calculation = 'nscf',
  prefix = 'external_si',
/
&SYSTEM
  nat = 2,
  ntyp = 1,
  ecutwfc = 24.0,
  nbnd = 28,
/
K_POINTS automatic
5 5 4 0 0 0
"""


EXTERNAL_NSCF_LOG = """
     number of k points=     20
     number of Kohn-Sham states= 28
     number of plane waves= 3072
     dense FFT grid: ( 42, 42, 36)
     h_psi        :      0.40s CPU      9.50s WALL
     c_bands      :      0.10s CPU      1.30s WALL
"""


def _load_script_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_qe_fpga_l3_feedback_closed_loop_parse_args_resolves_paths_from_invocation_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script_module(RUN_L3_CLOSED_LOOP, "run_qe_fpga_l3_feedback_closed_loop_under_test")
    paper_dir = REPO_ROOT / "paper" / "dac_qe_fpga_dse"
    monkeypatch.chdir(paper_dir)

    args = module.parse_args([
        "--out",
        str(tmp_path.relative_to(paper_dir) if tmp_path.is_relative_to(paper_dir) else "relative_closed_loop_out"),
        "--workflow-corpus",
        "../../some_corpus/workflow_corpus.json",
        "--generic-sim",
        "../../model/generic_sim_backend/build/generic_sim",
    ])

    assert args.generic_sim == GENERIC_SIM.resolve()
    assert args.workflow_corpus == (paper_dir / "../../some_corpus/workflow_corpus.json").resolve()
    assert args.out == (paper_dir / "relative_closed_loop_out").resolve()


def test_l3_closed_loop_paper_summary_embeds_multi_workload_search_quality() -> None:
    module = _load_script_module(RUN_L3_CLOSED_LOOP, "run_qe_fpga_l3_feedback_closed_loop_summary_under_test")
    multi_workload_experiment = {
        "schema_version": "dse.qe_fpga_multi_workload_experiment_report.v1",
        "workload_count": 4,
        "method_policy_id": "wamf_generic_active_pareto",
        "aggregate": {
            "search_quality_summary": {
                "schema_version": "dse.qe_fpga.multi_workload_search_quality_summary.v1",
                "evaluation_protocol": "equal_budget_multi_workload_l2_tlm_oracle",
                "workload_count": 4,
                "method_policy_id": "wamf_generic_active_pareto",
                "budget": 5,
                "policy_rows": [
                    {
                        "policy_id": "wamf_generic_active_pareto",
                        "workload_count": 4,
                        "selection_count_mean": 5,
                        "final_simple_regret_mean": 0.02,
                        "final_simple_regret_std": 0.01,
                        "final_oracle_rank_mean": 1.25,
                        "top_k_hit_rate": 1.0,
                        "evaluations_to_top_5_hit_mean": 2.0,
                    }
                ],
            }
        },
    }

    summary = module._paper_ready_experiment_summary(
        report={
            "method_name": "QEFPGA_L3_GenericSimFeedbackClosedLoop",
            "workload_run_id": "unit_summary",
            "workflow_input": {
                "source_kind": "representative_fixture_corpus",
                "corpus_id": "unit_corpus",
                "workload_count": 4,
                "coverage": {"workflow_classes": ["scf", "nscf"]},
                "measured_qe_corpus_readiness": {"status": "blocked"},
            },
            "l3_feedback": {"validation_metrics": {}},
        },
        seed_summary={
            "candidate_count": 128,
            "pareto_candidate_count": 8,
            "promotion_count": 5,
            "implementation_package_count": 1,
        },
        seed_baseline={
            "oracle_fidelity": "L2_python_tlm",
            "budget_sweep": {"budgets": [1, 2, 5], "baseline_policy_results": []},
            "feature_ablation_report": {"ablations": []},
            "independent_feedback_coverage_plan": {"candidate_feedback_queue": []},
        },
        neuromf_policy_evaluation_report={"policies": [], "aggregate": {}},
        neuromf_policy_evaluation_ref={"path": "neuromf.json"},
        seed_wamf_dse={"method_name": "WAMF-DSE", "method_full_name": "Workflow-Abstraction-Guided Multi-Fidelity Active DSE"},
        seed_wamf_dse_ref={"path": "wamf.json"},
        seed_multi_workload_experiment=multi_workload_experiment,
        seed_multi_workload_experiment_ref={"path": "multi.json", "sha256": "sha256:abc"},
        feedback_validation={"policy_validation": {"status": "empty"}},
    )

    embedded = summary["multi_workload_experiment"]
    assert embedded["schema_version"] == "dse.qe_fpga_multi_workload_experiment_report.v1"
    assert embedded["artifact"] == "qe_fpga_multi_workload_experiment_report.json"
    assert embedded["artifact_ref"]["path"] == "multi.json"
    quality = embedded["aggregate"]["search_quality_summary"]
    assert quality["schema_version"] == "dse.qe_fpga.multi_workload_search_quality_summary.v1"
    assert quality["method_policy_id"] == "wamf_generic_active_pareto"
    assert quality["policy_rows"][0]["policy_id"] == "wamf_generic_active_pareto"


def test_l3_closed_loop_paper_summary_preserves_wamf_ablation_contract_fields() -> None:
    module = _load_script_module(RUN_L3_CLOSED_LOOP, "run_qe_fpga_l3_feedback_closed_loop_ablation_contract_under_test")

    summary = module._paper_ready_experiment_summary(
        report={
            "method_name": "QEFPGA_L3_GenericSimFeedbackClosedLoop",
            "workload_run_id": "unit_ablation_contract",
            "workflow_input": {
                "source_kind": "representative_fixture_corpus",
                "corpus_id": "unit_corpus",
                "workload_count": 1,
                "coverage": {"workflow_classes": ["scf", "nscf"]},
            },
            "l3_feedback": {"validation_metrics": {}},
        },
        seed_summary={
            "candidate_count": 128,
            "pareto_candidate_count": 8,
            "promotion_count": 5,
            "implementation_package_count": 1,
        },
        seed_baseline={
            "oracle_fidelity": "L2_python_tlm",
            "budget_sweep": {"budgets": [1, 2, 5], "baseline_policy_results": []},
            "feature_ablation_report": {"ablations": []},
            "independent_feedback_coverage_plan": {"candidate_feedback_queue": []},
        },
        neuromf_policy_evaluation_report={"policies": [], "aggregate": {}},
        neuromf_policy_evaluation_ref={"path": "neuromf.json"},
        seed_wamf_dse={
            "method_name": "WAMF-DSE",
            "method_full_name": "Workflow-Abstraction-Guided Multi-Fidelity Active DSE",
            "ablations": {
                "required_ablations": [
                    {
                        "ablation_id": "no_multifidelity_feedback",
                        "maps_to": "single_fidelity_l1_edp",
                        "status": "implemented",
                        "algorithm_contract": {
                            "removed_components": ["multi_fidelity_feedback"],
                            "replacement_policy_id": "single_fidelity_l1_edp",
                            "same_candidate_pool_as_method": True,
                            "same_evaluation_budget_as_method": True,
                            "retrospective_oracle_only": True,
                            "uses_workflow_abstraction": True,
                            "uses_multi_fidelity_feedback": False,
                            "uses_active_pareto_selection": False,
                        },
                        "selection_basis": {"ablation_removes": "multi_fidelity_feedback"},
                        "evaluation": {
                            "oracle_fidelity": "L2_python_tlm",
                            "final_budget": 5,
                            "final_best_edp": 115.0,
                            "final_oracle_rank": 3,
                            "final_simple_regret": 0.15,
                            "top_k_hit": True,
                        },
                        "comparison_to_method": {
                            "method_policy_id": "wamf_generic_active_pareto",
                            "same_budget": True,
                            "edp_ratio_vs_method": 1.15,
                            "rank_delta_vs_method": 2,
                            "regret_delta_vs_method": 0.1,
                        },
                        "sample_efficiency": {"evaluations_to_top_5_hit": 4},
                    }
                ]
            },
        },
        seed_wamf_dse_ref={"path": "wamf.json"},
        seed_multi_workload_experiment={},
        seed_multi_workload_experiment_ref={"path": "multi.json"},
        feedback_validation={"policy_validation": {"status": "empty"}},
    )

    row = summary["paper_table_rows"]["wamf_required_ablations"][0]
    assert row["algorithm_contract"]["removed_components"] == ["multi_fidelity_feedback"]
    assert row["algorithm_contract"]["same_candidate_pool_as_method"] is True
    assert row["algorithm_contract"]["same_evaluation_budget_as_method"] is True
    assert row["algorithm_contract"]["retrospective_oracle_only"] is True
    assert row["uses_workflow_abstraction"] is True
    assert row["uses_multi_fidelity_feedback"] is False
    assert row["uses_active_pareto_selection"] is False
    assert row["method_policy_id"] == "wamf_generic_active_pareto"
    assert row["same_budget_vs_method"] is True
    assert row["edp_ratio_vs_method"] == 1.15
    assert row["rank_delta_vs_method"] == 2
    assert row["regret_delta_vs_method"] == 0.1


def test_l3_closed_loop_paper_summary_uses_workflow_conditioned_algorithm_benchmark() -> None:
    module = _load_script_module(RUN_L3_CLOSED_LOOP, "run_qe_fpga_l3_feedback_closed_loop_workflow_benchmark_under_test")
    workflow_abstraction = build_qe_workflow_fpga_abstraction(
        {
            "workflow_id": "unit_workflow_conditioned_benchmark",
            "stages": [
                {
                    "stage_id": "scf",
                    "program": "pw.x",
                    "input": EXTERNAL_SCF_INPUT,
                    "stdout": EXTERNAL_SCF_LOG,
                },
                {
                    "stage_id": "nscf",
                    "program": "pw.x",
                    "input": EXTERNAL_NSCF_INPUT,
                    "stdout": EXTERNAL_NSCF_LOG,
                },
                {
                    "stage_id": "bands",
                    "program": "bands.x",
                    "profile": {"phases": {"band_path_projection": 1.0, "write_bands": 0.5}},
                    "depends_on": ["nscf"],
                },
            ],
        },
        workload_id="unit_workflow_conditioned_benchmark",
    )

    summary = module._paper_ready_experiment_summary(
        report={
            "method_name": "QEFPGA_L3_GenericSimFeedbackClosedLoop",
            "workload_run_id": "unit_summary",
            "workflow_input": {
                "source_kind": "workflow_bundle",
                "workload_count": 1,
                "coverage": {"workflow_classes": ["scf", "nscf", "bands"]},
            },
            "l3_feedback": {"validation_metrics": {}},
        },
        seed_summary={
            "candidate_count": 128,
            "pareto_candidate_count": 8,
            "promotion_count": 5,
            "implementation_package_count": 1,
        },
        seed_baseline={
            "oracle_fidelity": "L2_python_tlm",
            "budget_sweep": {"budgets": [1, 2, 5], "baseline_policy_results": []},
            "feature_ablation_report": {"ablations": []},
            "independent_feedback_coverage_plan": {"candidate_feedback_queue": []},
        },
        neuromf_policy_evaluation_report={"policies": [], "aggregate": {}},
        neuromf_policy_evaluation_ref={"path": "neuromf.json"},
        seed_wamf_dse={"method_name": "WAMF-DSE", "method_full_name": "Workflow-Abstraction-Guided Multi-Fidelity Active DSE"},
        seed_wamf_dse_ref={"path": "wamf.json"},
        seed_multi_workload_experiment={},
        seed_multi_workload_experiment_ref={},
        seed_workflow_abstraction=workflow_abstraction,
        seed_workflow_abstraction_ref={"path": "qe_workflow_fpga_abstraction.json", "sha256": "sha256:abc"},
        feedback_validation={"policy_validation": {"status": "empty"}},
    )

    benchmark = summary["independent_algorithm_benchmark"]
    assert benchmark["schema_version"] == "dse.multifidelity_search_benchmark.v1"
    assert benchmark["oracle_kind"] == "workflow_conditioned_independent_synthetic_mismatch"
    assert benchmark["workflow_conditioning"]["workflow_id"] == "unit_workflow_conditioned_benchmark"
    assert benchmark["workflow_conditioning"]["source_schema"] == "dse.qe_workflow_fpga_abstraction.v1"
    assert benchmark["workflow_conditioning"]["feature_contract_schema"] == "dse.workflow_feature_contract.v1"
    assert benchmark["workflow_conditioning"]["conditioning_applied_to_oracle"] is True
    assert benchmark["workflow_conditioning"]["stage_count"] == 3
    assert benchmark["workflow_abstraction_ref"]["path"] == "qe_workflow_fpga_abstraction.json"

    suite = summary["independent_algorithm_benchmark_suite"]
    assert suite["schema_version"] == "dse.workflow_conditioned_multifidelity_search_benchmark_suite.v1"
    assert suite["conditioning_source"] == "workflow_feature_contract"
    assert suite["workflow_ids"] == ["unit_workflow_conditioned_benchmark"]
    assert suite["scenario_count"] == 1
    assert "wamf_constrained_active_pareto" in {row["policy_id"] for row in suite["policy_statistics"]}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _stable_payload_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _rehash_manifest_artifact(run_dir: Path, rel_path: str) -> None:
    artifact_path = run_dir / rel_path
    replay_path = run_dir / "qe_fpga_replay_manifest.json"
    replay_manifest = json.loads(replay_path.read_text(encoding="utf-8"))
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    replay_manifest["artifact_byte_hashes"][rel_path] = {
        "sha256": _file_sha256(artifact_path),
        "size_bytes": artifact_path.stat().st_size,
    }
    replay_manifest["artifact_payload_hashes"][rel_path] = _stable_payload_hash(payload)
    replay_path.write_text(json.dumps(replay_manifest, indent=2, sort_keys=True), encoding="utf-8")


def test_feedback_next_promotion_queue_obeys_validation_gated_exploration_control() -> None:
    module = _load_script_module(PIPELINE, "run_qe_fpga_deployment_dse_next_control_under_test")
    search_iteration_plan = {
        "problem_id": "tiny_problem",
        "workload_run_id": "tiny_run",
        "next_candidates": [
            {
                "candidate_id": "nominal_a",
                "search_policy_rank": 1,
                "step2_screenable": True,
                "simulation_blockers": ["not_promoted_for_simulation"],
            },
            {
                "candidate_id": "fallback_b",
                "search_policy_rank": 7,
                "step2_screenable": True,
                "simulation_blockers": ["not_promoted_for_simulation"],
            },
            {
                "candidate_id": "fallback_c",
                "search_policy_rank": 9,
                "step2_screenable": True,
                "simulation_blockers": ["not_promoted_for_simulation"],
            },
        ],
    }
    validation_gated_queue = {
        "schema_version": "dse.multifidelity_next_evaluation_queue.v1",
        "mode": "exploration_fallback",
        "control_reason": "algorithm_not_validated",
        "recommended_next_action": "recalibrate_models_and_run_exploration_fallback",
        "selected_candidate_ids": ["fallback_b", "fallback_c"],
        "queue": [
            {
                "candidate_id": "fallback_b",
                "queue_reason": "calibration_exploration_after_validation_failure",
                "control_score": 0.91,
            },
            {
                "candidate_id": "fallback_c",
                "queue_reason": "calibration_exploration_after_validation_failure",
                "control_score": 0.88,
            },
        ],
        "algorithm_contract": {
            "domain_neutral": True,
            "validation_controls_next_iteration": True,
        },
    }

    next_promotion = module._feedback_informed_next_promotion_queue(
        search_iteration_plan,
        promotion_budget=2,
        validation_gated_queue=validation_gated_queue,
    )

    assert next_promotion["schema_version"] == "dse.qe_fpga_feedback_informed_next_promotion_queue.v1"
    assert next_promotion["control_mode"] == "exploration_fallback"
    assert next_promotion["control_reason"] == "algorithm_not_validated"
    assert next_promotion["validation_gated_queue_applied"] is True
    assert next_promotion["candidate_ids"] == ["fallback_b", "fallback_c"]
    assert next_promotion["promotion_queue"][0]["validation_control_rank"] == 1
    assert next_promotion["promotion_queue"][0]["feedback_informed_rank"] == 1
    assert next_promotion["promotion_queue"][0]["source_search_policy_rank"] == 7
    assert next_promotion["promotion_queue"][0]["promotion"]["rationale"][0] == (
        "validation_gated_exploration_fallback"
    )
    assert all(row["execution_allowed"] is False for row in next_promotion["promotion_queue"])
    assert next_promotion["not_a_step3_queue"] is True


def test_qe_fpga_replay_verifier_rejects_rehashed_semantically_invalid_artifact(tmp_path: Path) -> None:
    out_dir = tmp_path / "qe_fpga_schema_tamper"

    completed = subprocess.run(
        [
            sys.executable,
            str(PIPELINE),
            "--out",
            str(out_dir),
            "--workload-run-id",
            "schema_tamper_run",
            "--candidate-budget",
            "256",
            "--promotion-budget",
            "4",
            "--implementation-package-budget",
            "1",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    artifact_rel = "qe_workflow_fpga_abstraction.json"
    artifact_path = out_dir / artifact_rel
    abstraction = json.loads(artifact_path.read_text(encoding="utf-8"))
    abstraction.pop("graph")
    artifact_path.write_text(json.dumps(abstraction, indent=2, sort_keys=True), encoding="utf-8")
    _rehash_manifest_artifact(out_dir, artifact_rel)

    verified = subprocess.run(
        [sys.executable, str(VERIFY_REPLAY), "--run-dir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert verified.returncode == 1
    verification = json.loads(verified.stdout)
    assert verification["status"] == "failed"
    assert artifact_rel in verification["semantic_error_artifacts"]
    assert any(
        error["artifact"] == artifact_rel and error["field"] == "graph"
        for error in verification["semantic_errors"]
    )


def test_qe_fpga_replay_verifier_rejects_rehashed_invalid_neural_search_artifact(tmp_path: Path) -> None:
    out_dir = tmp_path / "qe_fpga_neural_schema_tamper"

    completed = subprocess.run(
        [
            sys.executable,
            str(PIPELINE),
            "--out",
            str(out_dir),
            "--workload-run-id",
            "neural_schema_tamper_run",
            "--candidate-budget",
            "256",
            "--promotion-budget",
            "4",
            "--implementation-package-budget",
            "1",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    artifact_rel = "qe_fpga_neural_multifidelity_search_report.json"
    artifact_path = out_dir / artifact_rel
    neural_search = json.loads(artifact_path.read_text(encoding="utf-8"))
    neural_search.pop("feature_schema")
    neural_search.pop("surrogate_model")
    artifact_path.write_text(json.dumps(neural_search, indent=2, sort_keys=True), encoding="utf-8")
    _rehash_manifest_artifact(out_dir, artifact_rel)

    verified = subprocess.run(
        [sys.executable, str(VERIFY_REPLAY), "--run-dir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert verified.returncode == 1
    verification = json.loads(verified.stdout)
    assert verification["status"] == "failed"
    assert artifact_rel in verification["semantic_error_artifacts"]
    assert {
        error["field"]
        for error in verification["semantic_errors"]
        if error["artifact"] == artifact_rel
    } >= {"feature_schema", "surrogate_model"}


def test_qe_fpga_replay_verifier_rejects_rehashed_invalid_neural_training_artifact(tmp_path: Path) -> None:
    out_dir = tmp_path / "qe_fpga_neural_training_schema_tamper"

    completed = subprocess.run(
        [
            sys.executable,
            str(PIPELINE),
            "--out",
            str(out_dir),
            "--workload-run-id",
            "neural_training_schema_tamper_run",
            "--candidate-budget",
            "256",
            "--promotion-budget",
            "4",
            "--implementation-package-budget",
            "1",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    artifact_rel = "qe_fpga_neural_surrogate_training_report.json"
    artifact_path = out_dir / artifact_rel
    neural_training = json.loads(artifact_path.read_text(encoding="utf-8"))
    neural_training.pop("checkpoint")
    neural_training.pop("normalizer")
    artifact_path.write_text(json.dumps(neural_training, indent=2, sort_keys=True), encoding="utf-8")
    _rehash_manifest_artifact(out_dir, artifact_rel)

    verified = subprocess.run(
        [sys.executable, str(VERIFY_REPLAY), "--run-dir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert verified.returncode == 1
    verification = json.loads(verified.stdout)
    assert verification["status"] == "failed"
    assert artifact_rel in verification["semantic_error_artifacts"]
    assert {
        error["field"]
        for error in verification["semantic_errors"]
        if error["artifact"] == artifact_rel
    } >= {"checkpoint", "normalizer"}


def test_qe_fpga_replay_verifier_rejects_rehashed_invalid_wamf_report(tmp_path: Path) -> None:
    out_dir = tmp_path / "qe_fpga_wamf_schema_tamper"

    completed = subprocess.run(
        [
            sys.executable,
            str(PIPELINE),
            "--out",
            str(out_dir),
            "--workload-run-id",
            "wamf_schema_tamper_run",
            "--candidate-budget",
            "256",
            "--promotion-budget",
            "4",
            "--implementation-package-budget",
            "1",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    artifact_rel = "qe_fpga_wamf_dse_report.json"
    artifact_path = out_dir / artifact_rel
    wamf_report = json.loads(artifact_path.read_text(encoding="utf-8"))
    wamf_report.pop("active_pareto_acquisition")
    wamf_report.pop("deployment_search_space")
    artifact_path.write_text(json.dumps(wamf_report, indent=2, sort_keys=True), encoding="utf-8")
    _rehash_manifest_artifact(out_dir, artifact_rel)

    verified = subprocess.run(
        [sys.executable, str(VERIFY_REPLAY), "--run-dir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert verified.returncode == 1
    verification = json.loads(verified.stdout)
    assert verification["status"] == "failed"
    assert artifact_rel in verification["semantic_error_artifacts"]
    assert {
        error["field"]
        for error in verification["semantic_errors"]
        if error["artifact"] == artifact_rel
    } >= {"active_pareto_acquisition", "deployment_search_space"}


def test_l3_generic_sim_request_translation_omits_lifetime_edges_from_execution_dag() -> None:
    module = _load_script_module(RUN_L3_GSIM, "run_qe_fpga_l3_generic_sim_feedback_translation_under_test")
    l2_request = {
        "schema_version": "dse.qe_fpga_l2_evaluation_request.v1",
        "request_id": "req_lifetime_cycle",
        "candidate_id": "cand_lifetime_cycle",
        "design_key": "architecture_template=fpga_hybrid_cpu_control_accel_kernels",
        "candidate_parameters": {
            "memory_topology": "ddr_streaming",
            "runtime_schedule": "batched_stage_offload",
        },
        "request_payload": {
            "run_id": "graph_with_lifetime_cycle",
            "deployment": {
                "architecture_template": "fpga_hybrid_cpu_control_accel_kernels",
                "memory_topology": "ddr_streaming",
                "runtime_schedule": "batched_stage_offload",
            },
            "graph": {
                "nodes": {
                    "stage_a": {
                        "stage_type": "pw.x",
                        "workflow_class": "scf",
                        "kernels": ["h_psi"],
                        "estimated_weight_ms": 2.0,
                    },
                    "stage_b": {
                        "stage_type": "bands.x",
                        "workflow_class": "bands",
                        "kernels": ["band_path_projection"],
                        "estimated_weight_ms": 3.0,
                    },
                },
                "edges": [
                    {
                        "source": "stage_a",
                        "target": "stage_b",
                        "edge_kind": "stage_order",
                        "data_mb": 1.0,
                    },
                    {
                        "source": "stage_b",
                        "target": "stage_a",
                        "edge_kind": "data_object_lifetime",
                        "data_mb": 16.0,
                    },
                ],
            },
        },
    }

    gsim_request = module.build_gsim_request(l2_request)

    assert gsim_request["workload"]["edges"] == [
        {
            "source": "stage_a",
            "target": "stage_b",
            "tensor_name": "stage_order",
            "tensor_dtype": "FP64",
            "element_size": 8,
            "size_bytes": 1048576,
        }
    ]
    assert gsim_request["workload"]["metadata"]["omitted_non_execution_edge_count"] == 1
    assert gsim_request["workload"]["metadata"]["omitted_non_execution_edge_kind_counts"] == {
        "data_object_lifetime": 1
    }


def test_qe_fpga_l3_feedback_validation_ignores_failed_metric_bearing_samples(tmp_path: Path) -> None:
    out_dir = tmp_path / "qe_fpga_l3_failed_metric_sample"
    seed = subprocess.run(
        [
            sys.executable,
            str(PIPELINE),
            "--out",
            str(out_dir / "seed"),
            "--workload-run-id",
            "l3_failed_metric_seed",
            "--candidate-budget",
            "96",
            "--promotion-budget",
            "2",
            "--implementation-package-budget",
            "1",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert seed.returncode == 0, seed.stdout + seed.stderr

    fake_gsim = tmp_path / "fake_generic_sim.py"
    fake_gsim.write_text(
        """#!/usr/bin/env python3
import argparse, json, pathlib
parser = argparse.ArgumentParser()
parser.add_argument('--request', required=True)
parser.add_argument('--result', required=True)
args = parser.parse_args()
request = json.loads(pathlib.Path(args.request).read_text(encoding='utf-8'))
run_id = str(request.get('run_id', ''))
failed = run_id.endswith('_001') or run_id.endswith('001')
payload = {
    'schema_version': 'gsim.result.v1',
    'run_id': run_id,
    'status': 'failed' if failed else 'passed',
    'metrics': {'latency_ms': 2.0 if failed else 1.0, 'energy_j': 0.5 if failed else 0.25},
    'error_message': 'intentional_failed_metric_sample' if failed else '',
}
pathlib.Path(args.result).parent.mkdir(parents=True, exist_ok=True)
pathlib.Path(args.result).write_text(json.dumps(payload), encoding='utf-8')
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    fake_gsim.chmod(0o755)

    completed = subprocess.run(
        [
            sys.executable,
            str(RUN_L3_GSIM),
            "--l2-request-bundle",
            str(out_dir / "seed" / "qe_fpga_l2_request_bundle.json"),
            "--out",
            str(out_dir / "l3_feedback"),
            "--generic-sim",
            str(fake_gsim),
            "--max-requests",
            "2",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    report = json.loads((out_dir / "l3_feedback" / "qe_fpga_l3_generic_sim_feedback.json").read_text(encoding="utf-8"))
    feedback = json.loads((out_dir / "l3_feedback" / "feedback_samples.json").read_text(encoding="utf-8"))

    assert report["status"] == "partial"
    assert report["passed_count"] == 1
    assert report["failed_count"] == 1
    assert feedback["sample_count"] == 2
    assert {sample["status"] for sample in feedback["samples"]} == {"failed", "passed"}
    validation = report["validation_metrics"]
    assert validation["sample_count"] == 2
    assert validation["usable_sample_count"] == 1
    assert validation["excluded_sample_count"] == 1
    assert validation["excluded_samples"][0]["status"] == "failed"
    assert validation["selection_role_counts"] == {"promoted": 1}
    assert validation["status"] == "insufficient_for_sampled_rank_validation"
    assert len(validation["sample_rows_preview"]) == 1
    assert validation["sample_rows_preview"][0]["sample_status"] == "passed"
