#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = ROOT / 'docs/benchmarks'
TOOLS_BENCHMARKS_DIR = Path(__file__).resolve().parent
RUNNER_PATH = TOOLS_BENCHMARKS_DIR / 'run_systemc_architecture_family_dse_sweep.py'
FRONTDOOR_EVAL_PATH = TOOLS_BENCHMARKS_DIR / 'evaluate_qe_ic_graph_frontdoor.py'
PROJECTION_HELPER_PATH = TOOLS_BENCHMARKS_DIR / 'qe_ic_graph_projection_utils.py'
DEFAULT_OUTPUT_PATH = BENCHMARKS_DIR / 'results/qe_ic_graph_frontdoor_run_v0.json'


class GraphFrontdoorRunError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GraphFrontdoorRunError(message)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GraphFrontdoorRunError(f'cannot import module from {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def build_execution_plan_summary(
    requested: str | None,
    resolved: str | None,
    *,
    executed: str | None = None,
    source: str | None = None,
    constraints: str | None = None,
) -> str | None:
    parts: list[str] = []
    if requested:
        parts.append(f'requested={requested}')
    if resolved:
        parts.append(f'resolved={resolved}')
    if executed:
        parts.append(f'executed={executed}')
    if source:
        parts.append(f'source={source}')
    if constraints:
        parts.append(f'constraints={constraints}')
    return ' | '.join(parts) if parts else None


def execution_plan_summary_from_candidate(candidate_payload: dict[str, Any] | None) -> str | None:
    if not isinstance(candidate_payload, dict):
        return None
    profile = candidate_payload.get('graph_frontdoor_profile')
    if not isinstance(profile, dict):
        return None
    return build_execution_plan_summary(
        profile.get('requested_cluster_sequence'),
        profile.get('resolved_cluster_sequence'),
        executed=profile.get('executed_cluster_sequence'),
        source=profile.get('execution_plan_source'),
        constraints=profile.get('sequence_constraints'),
    )


def build_runner_args(args: argparse.Namespace, runner: Any) -> SimpleNamespace:
    return SimpleNamespace(
        source_kind=args.source_kind,
        qe_tolerance_schema_id=args.qe_tolerance_schema_id,
        assumption_set_id=args.assumption_set_id,
        model_max_scf_iters=args.model_max_scf_iters,
        auto_match_baseline_iters=args.auto_match_baseline_iters,
        cpu_shell_aggregate_path=args.cpu_shell_aggregate_path,
        fast_layer_proxy_assumptions_path=args.fast_layer_proxy_assumptions_path,
        model_bin=args.model_bin,
        compare_helper=args.compare_helper,
        normalize_gold_helper=args.normalize_gold_helper,
        gold_baseline_root=args.gold_baseline_root,
        fail_on_gold_mismatch=False,
        source_model='graph_frontdoor_projected',
        run_id='graph_frontdoor_runtime',
    )


def load_workload_descriptor(runner: Any, workload_id: str) -> dict[str, Any]:
    rows = runner.validate_workloads([workload_id])
    require(rows, f'unknown workload_id: {workload_id}')
    return rows[0]


def derive_graph_execution_hints(graph_payload: dict[str, Any], projection_helper: Any) -> dict[str, Any]:
    return projection_helper.derive_frontdoor_v0_execution_hints(graph_payload)


def project_result_row(
    graph_path: Path,
    graph_payload: dict[str, Any],
    frontdoor_eval: dict[str, Any],
    workload: dict[str, Any],
    runner: Any,
    runner_args: SimpleNamespace,
    projection_helper: Any,
) -> dict[str, Any]:
    join = graph_payload['join_keys']
    projected_workload = dict(workload)
    execution_hints = derive_graph_execution_hints(graph_payload, projection_helper)
    projected_workload['graph_frontdoor_execution_hints'] = execution_hints
    row = runner.build_result_row(
        projected_workload,
        str(join['family']),
        str(join['diag_policy']),
        str(join['offload_scope']),
        str(join['resident_policy']),
        runner_args,
        partition_strategy=str(join['partition_strategy']),
    )
    row['graph_evidence'] = {
        'graph_id': frontdoor_eval['graph_id'],
        'graph_schema_version': graph_payload['graph_schema_version'],
        'seed_template_id': frontdoor_eval['seed_template_id'],
        'graph_export_authority': 'frontdoor_graph_json',
        'lossless_export_pass': True,
        'module_instance_count': frontdoor_eval['module_instance_count'],
        'link_count': frontdoor_eval['link_count'],
        'flow_count': frontdoor_eval['flow_count'],
        'topology_style': frontdoor_eval['topology_style'],
        'control_plane_summary': frontdoor_eval['control_plane_summary'],
        'datapath_stage_summary': frontdoor_eval['datapath_stage_summary'],
        'key_component_refs_summary': frontdoor_eval['key_component_refs_summary'],
        'leaf_component_refs_summary': frontdoor_eval['leaf_component_refs_summary'],
        'bottleneck_component_summary': frontdoor_eval['bottleneck_component_summary'],
        'leaf_bottleneck_component_summary': frontdoor_eval['leaf_bottleneck_component_summary'],
        'risk_driver_component_summary': frontdoor_eval['risk_driver_component_summary'],
        'component_score_summary': frontdoor_eval['component_score_summary'],
        'component_score_source': frontdoor_eval['component_score_source'],
        'execution_plan_summary': build_execution_plan_summary(
            execution_hints.get('requested_cluster_sequence'),
            execution_hints.get('resolved_cluster_sequence'),
            source='projected_hints',
            constraints=execution_hints.get('sequence_constraint_notes'),
        ),
        'cluster_cycle_summary': None,
        'component_score_signal_summary': None,
        'iteration_behavior_summary': None,
        'critical_path_summary': frontdoor_eval['critical_path_summary'],
        'dataflow_bottleneck_summary': frontdoor_eval['dataflow_bottleneck_summary'],
        'mapping_risk_summary': frontdoor_eval['mapping_risk_summary'],
    }
    row['correctness']['notes'].append('graph_frontdoor_execution_mode=projected_design_point_only')
    row['correctness']['notes'].append(
        f'graph_frontdoor_projection_limitation=simulator follows join_keys projection, not arbitrary module/link semantics ({graph_path})'
    )
    return row


def maybe_execute_row(
    row: dict[str, Any],
    runner: Any,
    runner_args: SimpleNamespace,
    artifacts_dir: Path,
) -> None:
    workload = row['workload']
    baseline_payload = None
    baseline_json_path = None
    if workload['gold_required']:
        baseline_payload, baseline_json_path, error = runner.prepare_qe_gold_baseline(
            workload,
            runner_args,
            artifacts_dir,
        )
        if error is not None:
            row['stub_reason'] = error
            row['result_status'] = 'baseline_missing' if 'missing QE baseline' in error else 'baseline_normalization_error'
            row['correctness']['status'] = row['result_status']
            return
    ok, reason = runner.run_model_for_row(
        {'experiment': {'run_id': 'graph_frontdoor_runtime'}},
        row,
        runner_args,
        artifacts_dir,
        baseline_payload=baseline_payload,
    )
    if not ok:
        row['stub_reason'] = reason
        return
    runner.maybe_run_qe_gold_compare(
        row,
        runner_args,
        artifacts_dir,
        baseline_payload=baseline_payload,
        baseline_json_path=baseline_json_path,
    )
    candidate_payload = None
    metrics_path = (row.get('artifacts') or {}).get('metrics_path')
    if metrics_path:
        path = Path(str(metrics_path))
        if path.exists():
            candidate_payload = json.loads(path.read_text(encoding='utf-8'))
    execution_plan_summary = execution_plan_summary_from_candidate(candidate_payload)
    if execution_plan_summary is not None:
        row.setdefault('graph_evidence', {})['execution_plan_summary'] = execution_plan_summary


def write_graph_sidecar(output_root: Path, graph_path: Path, graph_payload: dict[str, Any], frontdoor_eval: dict[str, Any], row: dict[str, Any]) -> str:
    graph_dir = output_root / 'graph_frontdoor_sidecars'
    graph_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = graph_dir / f"{row['result_id']}.graph.frontdoor.json"
    sidecar_path.write_text(
        json.dumps(
            {
                'graph_path': str(graph_path),
                'graph_payload': graph_payload,
                'frontdoor_evaluation': frontdoor_eval,
                'result_id': row['result_id'],
                'design_point': row['design_point'],
            },
            indent=2,
            ensure_ascii=False,
        ) + '\n',
        encoding='utf-8',
    )
    row['artifacts']['graph_evidence_path'] = str(sidecar_path)
    return str(sidecar_path)


def ranking_key(entry: dict[str, Any], execute_model: bool) -> tuple[float, float, str]:
    row = entry['result_row']
    if execute_model:
        time_s = row['primary_metrics']['time_to_convergence_s']
        energy_j = row['primary_metrics']['energy_to_convergence_j']
        if time_s is not None:
            return (float(time_s), float('inf') if energy_j is None else float(energy_j), row['result_id'])
    frontdoor_eval = entry['frontdoor_evaluation']
    return (
        float(frontdoor_eval['estimated_total_time_proxy_score']),
        float(frontdoor_eval['estimated_total_energy_proxy_score']),
        row['result_id'],
    )


def run_frontdoor(
    graph_paths: list[Path],
    workload_id: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    runner = load_module('qe_dse_runner_frontdoor_run', RUNNER_PATH)
    frontdoor = load_module('qe_frontdoor_eval', FRONTDOOR_EVAL_PATH)
    projection_helper = load_module('qe_ic_graph_projection_utils_frontdoor_run', PROJECTION_HELPER_PATH)
    catalog = frontdoor.load_json(frontdoor.DEFAULT_CATALOG_PATH)
    catalog_by_id = {str(item['component_id']): item for item in catalog['components']}
    runner_args = build_runner_args(args, runner)
    workload = load_workload_descriptor(runner, workload_id)
    output_root = args.output.parent
    output_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    artifacts_dir = output_root / 'artifacts'
    for graph_path in graph_paths:
        graph_payload = frontdoor.normalize_graph_payload(load_json(graph_path), graph_path)
        frontdoor_eval = frontdoor.evaluate_graph(graph_path, graph_payload, catalog_by_id, runner)
        row = project_result_row(graph_path, graph_payload, frontdoor_eval, workload, runner, runner_args, projection_helper)
        if args.execute_model:
            maybe_execute_row(row, runner, runner_args, artifacts_dir)
        write_graph_sidecar(output_root, graph_path, graph_payload, frontdoor_eval, row)
        results.append(
            {
                'graph_path': str(graph_path),
                'graph_id': graph_payload['graph_id'],
                'execution_mode': 'projected_design_point_only' if args.execute_model else 'structural_only',
                'execution_plan_summary': (row.get('graph_evidence') or {}).get('execution_plan_summary'),
                'projection_limitation': 'simulator execution follows join_keys projection; arbitrary graph semantics remain evaluator-side evidence',
                'frontdoor_evaluation': frontdoor_eval,
                'result_row': row,
            }
        )

    ranked = sorted(results, key=lambda item: ranking_key(item, args.execute_model))
    return {
        'schema_version': 'qe_ic_graph_frontdoor_run_v0',
        'generated_at_utc': iso_utc_now(),
        'workload_id': workload_id,
        'execute_model': args.execute_model,
        'graph_execution_mode': 'projected_design_point_only' if args.execute_model else 'structural_only',
        'projection_limitation': 'full arbitrary graph semantics are evaluated and preserved, but simulator execution currently projects through family/diag/offload/resident/partition join_keys',
        'objective': 'time_to_convergence_s' if args.execute_model else 'estimated_total_time_proxy_score',
        'best_graph_id': None if not ranked else ranked[0]['graph_id'],
        'best_graph_path': None if not ranked else ranked[0]['graph_path'],
        'ranked_results': ranked,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run the QE IC graph front-door on one or more graph JSON specs.')
    parser.add_argument('--graph', type=Path, nargs='+', required=True)
    parser.add_argument('--workload-id', required=True)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument('--execute-model', action='store_true')
    parser.add_argument('--source-kind', default='timed_functional_proxy')
    parser.add_argument('--assumption-set-id', default='qe_next_stage_phase_v0')
    parser.add_argument('--qe-tolerance-schema-id', default='qe_gold_numerical_tolerance_schema_v0')
    parser.add_argument('--model-bin', type=Path, default=ROOT / 'model/qe_band_solver_model/build/qe_band_solver_model')
    parser.add_argument('--model-max-scf-iters', type=int, default=1)
    parser.add_argument('--auto-match-baseline-iters', action='store_true')
    parser.add_argument('--cpu-shell-aggregate-path', type=Path, default=ROOT / 'docs/benchmarks/results/qe_cpu_shell_aggregate_extract_20260402.json')
    parser.add_argument('--fast-layer-proxy-assumptions-path', type=Path, default=ROOT / 'docs/benchmarks/qe_fast_layer_proxy_assumption_set_v0.json')
    parser.add_argument('--compare-helper', type=Path, default=ROOT / 'tools/benchmarks/compare_qe_gold_correctness.py')
    parser.add_argument('--normalize-gold-helper', type=Path, default=ROOT / 'tools/benchmarks/normalize_qe_gold_baseline.py')
    parser.add_argument('--gold-baseline-root', type=Path, default=ROOT / 'docs/benchmarks/results/qe_workload_revalidation')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run_frontdoor(args.graph, args.workload_id, args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'[ok] wrote graph frontdoor run: {args.output}')
    if payload['best_graph_id'] is not None:
        print(f"[summary] best_graph_id={payload['best_graph_id']} objective={payload['objective']}")
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except GraphFrontdoorRunError as exc:
        print(f'[FAIL] {exc}')
        raise SystemExit(1)
