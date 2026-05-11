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
MATRIX_PATH = BENCHMARKS_DIR / 'qe_ic_case_signature_matrix_v0.json'
PHASE_CONFIG_PATH = BENCHMARKS_DIR / 'qe_ic_full_flow_phase_config_v0.json'
RUNNER_PATH = TOOLS_BENCHMARKS_DIR / 'run_systemc_architecture_family_dse_sweep.py'
DEFAULT_QE_TOLERANCE_SCHEMA_ID = 'qe_gold_numerical_tolerance_schema_v0'
DEFAULT_ACCOUNTING_BOUNDARY_ID = 'scf_shell_convergence_scope_v1'
DEFAULT_FAST_PROXY_ASSUMPTION_SET_ID = 'qe_next_stage_phase_v0'
DEFAULT_REDUCED_SPACE_CONTRACT_ID = 'qe_reduced_space_validation_contract_v0'


def load_runner() -> Any:
    spec = importlib.util.spec_from_file_location('qe_dse_runner', RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit(f'cannot import runner module from {RUNNER_PATH}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def canonical_design_point_defaults(runner: Any, family: str = 'F1') -> dict[str, Any]:
    profile = runner.FAMILY_PROFILES[family]
    return {
        'family': family,
        'diag_policy': profile['canonical_diag_policy'],
        'offload_scope': profile['canonical_offload_scope'],
        'resident_policy': profile['canonical_resident_policy'],
        'partition_strategy': profile['canonical_partition_strategy'],
        'canonical_profile_match': True,
    }


def accurate_design_point_defaults(runner: Any, family: str = 'F1') -> dict[str, Any]:
    defaults = canonical_design_point_defaults(runner, family)
    defaults.pop('canonical_profile_match', None)
    return defaults


def build_case_pack(
    matrix: dict[str, Any],
    phase_config: dict[str, Any],
    runner: Any,
    *,
    matrix_path: Path = MATRIX_PATH,
    phase_config_path: Path = PHASE_CONFIG_PATH,
) -> dict[str, Any]:
    cases_by_id = {item['machine_workload_id']: item for item in matrix['cases']}
    default_workloads = runner.DEFAULT_WORKLOADS
    fast_defaults = canonical_design_point_defaults(runner, 'F1')
    accurate_defaults = accurate_design_point_defaults(runner, 'F1')

    def make_descriptor(workload_id: str, *, lane_kind: str) -> dict[str, Any]:
        base = dict(default_workloads[workload_id])
        signature = dict(cases_by_id[workload_id])
        defaults = fast_defaults if lane_kind in {'stage_a', 'stage_b'} else accurate_defaults
        gold_source_path = str(ROOT / 'docs/benchmarks/results/qe_workload_revalidation' / workload_id)
        descriptor = {
            'workload_id': workload_id,
            'display_label': signature['display_label'],
            'signature_id': signature['signature_id'],
            'property_target': signature['property_target'],
            'pseudopotential_family': signature['pseudopotential_family'],
            'solver_path_class': signature['solver_path_class'],
            'workload_topology': signature['workload_topology'],
            'post_scf_extension_level': signature['post_scf_extension_level'],
            'projector_pressure': signature['operator_signature']['projector_pressure'],
            'nonlocal_pressure': signature['operator_signature']['nonlocal_pressure'],
            'generalized_ratio_bucket': signature['operator_signature']['generalized_ratio_bucket'],
            'diag_dominance': signature['operator_signature']['diag_dominance'],
            'fft_grid_pressure': signature['operator_signature']['fft_grid_pressure'],
            'topology_role': signature['topology_role'],
            'signature_confidence': signature['signature_confidence'],
            'software_family': base['software_family'],
            'flow_family': base['flow_family'],
            'trait_bucket': base['trait_bucket'],
            'lane': base['lane'],
            'gold_required': base['gold_required'],
            'first_priority_convergence_case': base['first_priority_convergence_case'],
            **defaults,
            'workload_group_id': runner.PHASE1_WORKLOAD_GROUP_ID,
            'qe_tolerance_schema_id': DEFAULT_QE_TOLERANCE_SCHEMA_ID,
            'accounting_boundary_id': DEFAULT_ACCOUNTING_BOUNDARY_ID,
            'fairness_policy_id': runner.PHASE1_FAIRNESS_POLICY_ID,
            'power_boundary_id': runner.PHASE1_POWER_BOUNDARY_ID,
            'observability_contract_id': runner.PHASE1_OBSERVABILITY_CONTRACT_ID,
            'algorithm_rewrite_manifest_id': runner.PHASE1_REWRITE_MANIFEST_ID,
            'algorithm_contract_deviation': False,
        }
        if lane_kind == 'accurate_generalization':
            descriptor['gold_required'] = True
        if lane_kind in {'stage_a', 'stage_b'}:
            descriptor.update(
                {
                    'source_kind': 'trace_calibrated_proxy',
                    'trace_shape_id': f'{workload_id}__trace_shape_v0',
                    'trace_shape_summary': {
                        'trait_bucket': base['trait_bucket'],
                        'signature_id': signature['signature_id'],
                    },
                    'fast_proxy_assumption_set_id': DEFAULT_FAST_PROXY_ASSUMPTION_SET_ID,
                    'gpu_baseline_state': 'pending',
                    'gpu_baseline_row_ref': None,
                }
            )
        else:
            descriptor.update(
                {
                    'source_kind': 'trace_calibrated_proxy',
                    'calibration_manifest_id': f'{workload_id}__calibration_manifest_v0',
                    'gold_case_bundle_id': f'{workload_id}__qe_reference_bundle_v0',
                    'gold_source_path': gold_source_path,
                    'reduced_space_contract_id': DEFAULT_REDUCED_SPACE_CONTRACT_ID,
                    'convergence_reference_id': f'{workload_id}__convergence_ref_v0',
                    'numerical_provenance_tag': 'calibrated',
                    'gpu_baseline_state': 'pending',
                    'gpu_baseline_row_ref': None,
                    'decisive_for_case': False,
                }
            )
        return descriptor

    stage_a = [make_descriptor(workload_id, lane_kind='stage_a') for workload_id in matrix['stage_a_bringup_cases']]
    stage_b = [make_descriptor(workload_id, lane_kind='stage_b') for workload_id in matrix['stage_b_nonblocking_signature_coverage']]
    accurate_anchor = [
        make_descriptor(workload_id, lane_kind='accurate_generalization')
        for workload_id in phase_config['layers']['accurate_layer'].get('anchor_cases', [])
    ]
    accurate_coverage = [
        make_descriptor(workload_id, lane_kind='accurate_generalization')
        for workload_id in phase_config['layers']['accurate_layer'].get('coverage_cases', [])
    ]
    generalization = [make_descriptor(workload_id, lane_kind='accurate_generalization') for workload_id in phase_config['layers']['accurate_layer']['generalization_cases']]

    return {
        'schema_version': 'qe_ic_case_pack_v0',
        'bundle_role': 'canonical_f1_seed_pack',
        'seed_family': 'F1',
        'seed_bundle_note': (
            'This artifact is a canonical F1 seed pack for Stage A/B/accurate-layer '
            'descriptor grounding; it is not yet a full multi-family expanded execution bundle.'
        ),
        'matrix_path': str(matrix_path),
        'phase_config_path': str(phase_config_path),
        'stage_a_bringup_descriptors': stage_a,
        'stage_b_nonblocking_signature_descriptors': stage_b,
        'accurate_layer_anchor_descriptors': accurate_anchor,
        'accurate_layer_coverage_descriptors': accurate_coverage,
        'accurate_layer_generalization_descriptors': generalization,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build the IC-oriented QE case-pack descriptor bundle.')
    parser.add_argument('--matrix', type=Path, default=MATRIX_PATH)
    parser.add_argument('--phase-config', type=Path, default=PHASE_CONFIG_PATH)
    parser.add_argument('--output', type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runner = load_runner()
    matrix = load_json(args.matrix)
    phase_config = load_json(args.phase_config)
    bundle = build_case_pack(
        matrix,
        phase_config,
        runner,
        matrix_path=args.matrix,
        phase_config_path=args.phase_config,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2) + '\n', encoding='utf-8')
    print(f'[ok] wrote case pack: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
