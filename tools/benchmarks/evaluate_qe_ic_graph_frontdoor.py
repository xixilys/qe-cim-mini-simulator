#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = ROOT / 'docs/benchmarks'
TOOLS_BENCHMARKS_DIR = Path(__file__).resolve().parent
ARCH_DIR = ROOT / 'docs/architecture'
RUNNER_PATH = TOOLS_BENCHMARKS_DIR / 'run_systemc_architecture_family_dse_sweep.py'
REGISTRY_BUILDER_PATH = TOOLS_BENCHMARKS_DIR / 'build_qe_ic_component_registry.py'
DEFAULT_CATALOG_PATH = ARCH_DIR / 'qe_ic_component_catalog_seed_v0.json'
DEFAULT_SCHEMA_PATH = ARCH_DIR / 'qe_ic_graph_schema_v0.json'
DEFAULT_OUTPUT_PATH = BENCHMARKS_DIR / 'results/qe_ic_graph_frontdoor_eval_v0.json'


class GraphFrontdoorError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GraphFrontdoorError(message)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GraphFrontdoorError(f'cannot import module from {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def normalize_graph_payload(payload: dict[str, Any], graph_path: Path) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault('graph_schema_version', 'qe_ic_graph_schema_v0')
    normalized.setdefault(
        'graph_id',
        str(normalized.get('seed_template_id') or graph_path.stem),
    )
    return normalized


def validate_graph_payload(payload: dict[str, Any]) -> None:
    required_top = {
        'graph_schema_version',
        'graph_id',
        'seed_template_id',
        'workload_class',
        'join_keys',
        'modules',
        'links',
        'flows',
        'placement',
        'estimation_profile',
        'constraints',
        'observability_requirements',
    }
    missing = sorted(required_top - set(payload))
    require(not missing, f'graph missing required keys: {", ".join(missing)}')
    require(payload['graph_schema_version'] == 'qe_ic_graph_schema_v0', 'graph_schema_version drifted')
    join_keys = payload['join_keys']
    for key in ('family', 'diag_policy', 'offload_scope', 'resident_policy', 'partition_strategy'):
        require(key in join_keys and str(join_keys[key]).strip(), f'join_keys missing {key}')
    modules = payload['modules']
    links = payload['links']
    flows = payload['flows']
    require(isinstance(modules, list) and modules, 'modules must be a non-empty list')
    require(isinstance(flows, list) and flows, 'flows must be a non-empty list')
    require(isinstance(links, list), 'links must be a list')


def validate_graph_connectivity(payload: dict[str, Any], catalog_ids: set[str]) -> dict[str, Any]:
    modules = payload['modules']
    links = payload['links']
    flows = payload['flows']
    module_ids = [str(item['instance_id']) for item in modules]
    link_ids = [str(item['link_id']) for item in links]
    flow_ids = [str(item['flow_id']) for item in flows]
    require(len(module_ids) == len(set(module_ids)), 'duplicate module instance_id found')
    require(len(link_ids) == len(set(link_ids)), 'duplicate link_id found')
    require(len(flow_ids) == len(set(flow_ids)), 'duplicate flow_id found')
    module_id_set = set(module_ids)
    component_refs = []
    for item in modules:
        component_ref = str(item['component_ref'])
        require(component_ref in catalog_ids, f'unknown component_ref: {component_ref}')
        component_refs.append(component_ref)
    for item in links:
        require(str(item['src']) in module_id_set, f"link src missing module: {item['src']}")
        require(str(item['dst']) in module_id_set, f"link dst missing module: {item['dst']}")
    for item in flows:
        steps = [str(step) for step in item.get('steps', [])]
        require(steps, f"flow {item['flow_id']} missing steps")
        for step in steps:
            require(step in module_id_set, f'flow step missing module: {step}')
    return {
        'module_ids': module_ids,
        'link_ids': link_ids,
        'flow_ids': flow_ids,
        'component_refs': component_refs,
    }


def component_type_counts(component_refs: list[str], catalog_by_id: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for component_ref in component_refs:
        component_type = str(catalog_by_id[component_ref]['component_type'])
        counts[component_type] = counts.get(component_type, 0) + 1
    return counts


def placement_counts(modules: list[dict[str, Any]]) -> dict[str, int]:
    counts = {'host': 0, 'fpga': 0, 'shared': 0}
    for item in modules:
        placement = str(item.get('placement'))
        counts[placement] = counts.get(placement, 0) + 1
    return counts


def estimate_total_time_proxy_score(
    payload: dict[str, Any],
    key_component_refs: list[str],
    leaf_component_refs: list[str],
) -> float:
    join_keys = payload['join_keys']
    steps = max(len(item.get('steps', [])) for item in payload['flows'])
    placement = placement_counts(payload['modules'])
    score = (
        1.0 * steps
        + 0.35 * len(payload['links'])
        + 0.55 * max(0, len(payload['flows']) - 1)
        + 0.85 * placement.get('host', 0)
        + 0.45 * placement.get('shared', 0)
    )
    family = str(join_keys['family'])
    diag_policy = str(join_keys['diag_policy'])
    offload_scope = str(join_keys['offload_scope'])
    resident_policy = str(join_keys['resident_policy'])
    if family == 'F1':
        score += 2.0
    elif family == 'F3':
        score -= 0.4
    if diag_policy == 'cpu_only':
        score += 2.5
    elif diag_policy == 'aggressive_device':
        score -= 0.2
    if offload_scope == 'single_hotpath':
        score += 1.5
    elif offload_scope == 'device_heavy':
        score -= 0.4
    if resident_policy == 'spill_tolerant':
        score += 0.8
    if 'refresh_unit' in key_component_refs:
        score -= 0.2
    if 'reduction_closure_engine' in leaf_component_refs:
        score -= 0.25
    if 'cim_array_core' in leaf_component_refs:
        score -= 0.15
    if 'near_sram_support' in leaf_component_refs:
        score -= 0.10
    return round(max(score, 0.1), 6)


def estimate_total_energy_proxy_score(
    payload: dict[str, Any],
    key_component_refs: list[str],
    leaf_component_refs: list[str],
) -> float:
    placement = placement_counts(payload['modules'])
    join_keys = payload['join_keys']
    score = (
        0.6 * len(payload['modules'])
        + 0.3 * len(payload['links'])
        + 0.7 * placement.get('fpga', 0)
        + 0.4 * placement.get('shared', 0)
    )
    if str(join_keys['offload_scope']) == 'device_heavy':
        score += 1.0
    if str(join_keys['resident_policy']) == 'spill_tolerant':
        score += 0.8
    if 'refresh_unit' in key_component_refs:
        score += 0.4
    if 'near_sram_support' in leaf_component_refs:
        score += 0.2
    return round(max(score, 0.1), 6)


def evaluate_graph(
    graph_path: Path,
    payload: dict[str, Any],
    catalog_by_id: dict[str, dict[str, Any]],
    runner: Any,
) -> dict[str, Any]:
    payload = normalize_graph_payload(payload, graph_path)
    validate_graph_payload(payload)
    connectivity = validate_graph_connectivity(payload, set(catalog_by_id))
    key_component_refs = runner.graph_key_component_refs(payload, str(payload['seed_template_id']))
    leaf_component_refs = runner.graph_leaf_component_refs(key_component_refs)
    family = str(payload['join_keys']['family'])
    resident_policy = str(payload['join_keys']['resident_policy'])
    component_scores = runner.graph_component_scores(family, key_component_refs, resident_policy)
    canonical_template = runner.load_graph_seed_templates(runner.GRAPH_SEED_TEMPLATES_PATH).get(
        (
            str(payload['join_keys']['family']),
            str(payload['join_keys']['diag_policy']),
            str(payload['join_keys']['offload_scope']),
            str(payload['join_keys']['resident_policy']),
            str(payload['join_keys']['partition_strategy']),
        )
    )
    canonical_seed_template_id = None if canonical_template is None else str(canonical_template['seed_template_id'])
    return {
        'graph_path': str(graph_path),
        'graph_id': payload['graph_id'],
        'seed_template_id': payload['seed_template_id'],
        'projected_design_point': dict(payload['join_keys']),
        'canonical_seed_template_id': canonical_seed_template_id,
        'canonical_seed_match': canonical_seed_template_id == str(payload['seed_template_id']),
        'module_instance_count': len(payload['modules']),
        'link_count': len(payload['links']),
        'flow_count': len(payload['flows']),
        'placement_counts': placement_counts(payload['modules']),
        'component_type_counts': component_type_counts(connectivity['component_refs'], catalog_by_id),
        'topology_style': payload.get('placement', {}).get('style'),
        'control_plane_summary': runner.graph_control_plane_summary(payload.get('placement', {}), key_component_refs),
        'datapath_stage_summary': runner.graph_datapath_stage_summary(key_component_refs),
        'key_component_refs_summary': ', '.join(key_component_refs) if key_component_refs else None,
        'leaf_component_refs_summary': ', '.join(leaf_component_refs) if leaf_component_refs else None,
        'bottleneck_component_summary': runner.graph_bottleneck_component_summary(
            family, key_component_refs, resident_policy
        ),
        'leaf_bottleneck_component_summary': runner.graph_leaf_bottleneck_component_summary(component_scores),
        'risk_driver_component_summary': runner.graph_risk_driver_component_summary(
            family, key_component_refs, resident_policy
        ),
        'component_score_summary': runner.graph_component_score_summary(component_scores),
        'component_score_source': 'graph_frontdoor_structural_proxy',
        'dataflow_bottleneck_summary': runner.graph_dataflow_bottleneck_summary(
            family,
            str(payload['join_keys']['offload_scope']),
            resident_policy,
            str(payload['join_keys']['partition_strategy']),
        ),
        'mapping_risk_summary': runner.graph_mapping_risk_summary(
            family,
            str(payload['join_keys']['offload_scope']),
            resident_policy,
        ),
        'critical_path_summary': ' -> '.join(payload['flows'][0].get('steps', [])) if payload['flows'] else None,
        'estimated_total_time_proxy_score': estimate_total_time_proxy_score(payload, key_component_refs, leaf_component_refs),
        'estimated_total_energy_proxy_score': estimate_total_energy_proxy_score(payload, key_component_refs, leaf_component_refs),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Evaluate one or more QE IC graph JSON specs through the front-door evaluator.')
    parser.add_argument('--graph', type=Path, nargs='+', required=True)
    parser.add_argument('--catalog', type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument('--schema', type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runner = load_module('qe_dse_runner_frontdoor', RUNNER_PATH)
    _ = load_module('qe_ic_component_registry_builder_frontdoor', REGISTRY_BUILDER_PATH)
    catalog = load_json(args.catalog)
    catalog_by_id = {str(item['component_id']): item for item in catalog['components']}
    evaluations = [evaluate_graph(graph_path, load_json(graph_path), catalog_by_id, runner) for graph_path in args.graph]
    ranked = sorted(
        evaluations,
        key=lambda item: (
            item['estimated_total_time_proxy_score'],
            item['estimated_total_energy_proxy_score'],
            item['graph_id'],
        ),
    )
    payload = {
        'schema_version': 'qe_ic_graph_frontdoor_eval_v0',
        'graph_schema_path': str(args.schema),
        'catalog_path': str(args.catalog),
        'graph_count': len(evaluations),
        'best_graph_id': None if not ranked else ranked[0]['graph_id'],
        'best_graph_path': None if not ranked else ranked[0]['graph_path'],
        'objective': 'estimated_total_time_proxy_score',
        'ranked_graphs': ranked,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'[ok] wrote graph frontdoor eval: {args.output}')
    if ranked:
        print(f"[summary] best_graph_id={ranked[0]['graph_id']} objective={ranked[0]['estimated_total_time_proxy_score']}")
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except GraphFrontdoorError as exc:
        print(f'[FAIL] {exc}')
        raise SystemExit(1)
