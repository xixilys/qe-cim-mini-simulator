from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


HELPER_PATH = Path(__file__).with_name('qe_ic_graph_projection_utils.py')
HELPER_SPEC = importlib.util.spec_from_file_location('qe_ic_graph_projection_utils', HELPER_PATH)
assert HELPER_SPEC is not None
assert HELPER_SPEC.loader is not None
HELPER_MODULE = importlib.util.module_from_spec(HELPER_SPEC)
HELPER_SPEC.loader.exec_module(HELPER_MODULE)

CHECKER_PATH = Path(__file__).with_name('check_qe_ic_component_graph_v1.py')
CHECKER_SPEC = importlib.util.spec_from_file_location('check_qe_ic_component_graph_v1', CHECKER_PATH)
assert CHECKER_SPEC is not None
assert CHECKER_SPEC.loader is not None
CHECKER_MODULE = importlib.util.module_from_spec(CHECKER_SPEC)
CHECKER_SPEC.loader.exec_module(CHECKER_MODULE)

ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT / 'docs/architecture/qe_ic_graph_seed_system_level_v1.json'
FRONTDOOR_TEMPLATE_PATH = ROOT / 'docs/architecture/qe_ic_graph_seed_templates_v0.json'


class QeIcGraphProjectionUtilsTests(unittest.TestCase):
    def load_graph(self) -> dict:
        return CHECKER_MODULE.load_json(GRAPH_PATH)

    def load_frontdoor_graph(self, seed_template_id: str = 'f2_balanced_graph_v0') -> dict:
        payload = json.loads(FRONTDOOR_TEMPLATE_PATH.read_text(encoding='utf-8'))
        return next(item for item in payload['templates'] if item['seed_template_id'] == seed_template_id)

    def test_design_point_contains_only_authority_keys(self) -> None:
        graph = self.load_graph()

        projected = HELPER_MODULE.project_system_level_v1_design_point(graph)

        self.assertEqual(tuple(projected), HELPER_MODULE.DESIGN_POINT_AUTHORITY_KEYS)
        self.assertEqual(set(projected), set(HELPER_MODULE.DESIGN_POINT_AUTHORITY_KEYS))
        self.assertNotIn('workload_id', projected)
        self.assertEqual(
            projected,
            {
                'family': 'F2',
                'diag_policy': 'device_first_fallback',
                'offload_scope': 'balanced',
                'resident_policy': 'fit_first',
                'partition_strategy': 'operator__build__diag__refresh',
            },
        )

    def test_shared_join_keys_preserve_sorted_non_authority_members(self) -> None:
        graph = self.load_graph()

        projected = HELPER_MODULE.project_system_level_v1_shared_join_keys(graph)

        expected_keys = HELPER_MODULE.SYSTEM_LEVEL_V1_REQUIRED_SHARED_JOIN_KEYS
        self.assertEqual(tuple(projected), expected_keys)
        self.assertNotIn('family', projected)
        self.assertIn('workload_id', projected)
        self.assertEqual(
            projected,
            {
                'fairness_policy_id': 'qe_cpu_gpu_fpga_fairness_v0',
                'observability_contract_id': 'qe_simulator_board_observability_v0',
                'qe_tolerance_schema_id': 'qe_gold_numerical_tolerance_schema_v0',
                'workload_group_id': 'qe_next_stage_mainline',
                'workload_id': 'si4_pbe_uspp_small',
            },
        )

    def test_shared_join_keys_ignore_extra_non_authority_members(self) -> None:
        graph = json.loads(json.dumps(self.load_graph()))
        graph['join_keys']['extra_non_authority_key'] = 'ignore-me'

        projected = HELPER_MODULE.project_system_level_v1_shared_join_keys(graph)

        self.assertNotIn('extra_non_authority_key', projected)
        self.assertEqual(tuple(projected), HELPER_MODULE.SYSTEM_LEVEL_V1_REQUIRED_SHARED_JOIN_KEYS)

    def test_helper_matches_checker_projection_semantics(self) -> None:
        graph = json.loads(json.dumps(self.load_graph()))

        self.assertEqual(
            HELPER_MODULE.project_system_level_v1_design_point(graph),
            CHECKER_MODULE.project_design_point(graph),
        )
        self.assertEqual(
            HELPER_MODULE.project_system_level_v1_shared_join_keys(graph),
            CHECKER_MODULE.project_shared_join_keys(graph),
        )
        self.assertEqual(
            HELPER_MODULE.project_system_level_v1_system_run_config_patch(graph),
            CHECKER_MODULE.project_system_run_config_patch(graph),
        )

    def test_system_run_config_patch_matches_canonical_checker_output(self) -> None:
        graph = self.load_graph()

        patch = HELPER_MODULE.project_system_level_v1_system_run_config_patch(graph)

        self.assertEqual(patch['software_family'], 'QE')
        self.assertEqual(patch['flow_family'], 'CBANDS_DIAG')
        self.assertEqual(patch['case_id'], 'si4_pbe_uspp_small')
        self.assertEqual(patch['architecture_family'], 'F2')
        self.assertEqual(patch['projector_pressure'], 'medium')
        self.assertEqual(patch['generalized_ratio_bucket'], 'medium')
        self.assertEqual(patch['diag_dominance'], 'medium')
        self.assertEqual(patch['fft_grid_pressure'], 'medium')
        self.assertEqual(patch['offload_scope_override'], 'balanced')
        self.assertEqual(patch['resident_policy_override'], 'fit_first')
        self.assertEqual(patch['graph_frontdoor_mode'], 'system_level_graph_v1')
        self.assertEqual(patch['graph_id'], 'qe_f2_balanced_system_level_seed_v1')
        self.assertEqual(patch['graph_topology_style'], 'balanced_hybrid')
        self.assertEqual(patch['graph_module_count'], 16)
        self.assertEqual(patch['graph_flow_count'], 5)
        self.assertEqual(patch['graph_leaf_component_count'], 0)
        self.assertTrue(patch['graph_has_fft_unit'])
        self.assertTrue(patch['graph_has_reduction_unit'])
        self.assertTrue(patch['graph_has_diag_unit'])
        self.assertFalse(patch['graph_has_vector_diag_companion'])
        self.assertTrue(patch['graph_has_refresh_unit'])
        self.assertFalse(patch['graph_has_leaf_hotpath_flow'])
        self.assertFalse(patch['graph_prefers_diag_before_reduction'])
        self.assertFalse(patch['graph_prefers_refresh_before_diag'])
        self.assertEqual(
            patch['graph_requested_cluster_sequence'],
            'operator_apply,reduced_build,diag,refresh_residual',
        )
        self.assertEqual(patch['graph_resolved_cluster_sequence'], 'A,B,C,D')
        self.assertEqual(
            patch['graph_sequence_constraints'],
            'host_keeps_outer_scf;device_runtime_owns_resident_dma_launch;chip_keeps_operator_reduced_refresh;diag_must_allow_host_fallback;diag_dim_gt_device_limit -> host_diag_assist;resident_spill_can_force_host_diag',
        )
        self.assertNotIn('signature_id', patch)

    def test_system_run_config_patch_defaults_missing_signature_hints_to_empty_strings(self) -> None:
        graph = json.loads(json.dumps(self.load_graph()))
        del graph['workload_class']['signature_hints']

        patch = HELPER_MODULE.project_system_level_v1_system_run_config_patch(graph)

        self.assertEqual(patch['projector_pressure'], '')
        self.assertEqual(patch['generalized_ratio_bucket'], '')
        self.assertEqual(patch['diag_dominance'], '')
        self.assertEqual(patch['fft_grid_pressure'], '')

    def test_system_run_config_patch_defaults_partial_signature_hints_to_empty_strings(self) -> None:
        graph = json.loads(json.dumps(self.load_graph()))
        graph['workload_class']['signature_hints'] = {
            'projector_pressure': 'high',
            'diag_dominance': 'low',
        }

        patch = HELPER_MODULE.project_system_level_v1_system_run_config_patch(graph)

        self.assertEqual(patch['projector_pressure'], 'high')
        self.assertEqual(patch['generalized_ratio_bucket'], '')
        self.assertEqual(patch['diag_dominance'], 'low')
        self.assertEqual(patch['fft_grid_pressure'], '')

    def test_system_run_config_patch_omits_missing_signature_id_and_passthroughs_present_value(self) -> None:
        graph_without_signature = json.loads(json.dumps(self.load_graph()))
        graph_without_signature['workload_class'].pop('signature_id', None)

        patch_without_signature = HELPER_MODULE.project_system_level_v1_system_run_config_patch(graph_without_signature)
        self.assertNotIn('signature_id', patch_without_signature)

        graph_with_signature = json.loads(json.dumps(self.load_graph()))
        graph_with_signature['workload_class']['signature_id'] = 'sig::qe_f2_balanced'

        patch_with_signature = HELPER_MODULE.project_system_level_v1_system_run_config_patch(graph_with_signature)
        self.assertEqual(patch_with_signature['signature_id'], 'sig::qe_f2_balanced')

    def test_system_run_config_patch_uses_fixed_requested_stage_order_and_conditional_resolved_sequence(self) -> None:
        graph = json.loads(json.dumps(self.load_graph()))
        graph['flows'] = [
            {'flow_id': 'diag_flow', 'stage_id': 'diag_stage'},
            {'flow_id': 'operator_flow', 'stage_id': 'operator_apply_stage'},
            {'flow_id': 'ignored_flow', 'stage_id': 'untracked_stage'},
        ]

        patch = HELPER_MODULE.project_system_level_v1_system_run_config_patch(graph)

        self.assertEqual(patch['graph_requested_cluster_sequence'], 'operator_apply,diag')
        self.assertEqual(patch['graph_resolved_cluster_sequence'], 'A,B,C,D')

        graph['flows'] = [
            {'flow_id': 'ignored_flow', 'stage_id': 'untracked_stage'},
        ]

        patch_without_requested_stages = HELPER_MODULE.project_system_level_v1_system_run_config_patch(graph)
        self.assertEqual(patch_without_requested_stages['graph_requested_cluster_sequence'], '')
        self.assertEqual(patch_without_requested_stages['graph_resolved_cluster_sequence'], '')

    def test_system_run_config_patch_preserves_sequence_constraint_join_order(self) -> None:
        graph = json.loads(json.dumps(self.load_graph()))
        graph['constraints'] = {
            'host_fpga_split_rules': ['host_rule_a', 'host_rule_b'],
            'fallback_rules': ['fallback_rule_c', 'fallback_rule_d'],
        }

        patch = HELPER_MODULE.project_system_level_v1_system_run_config_patch(graph)

        self.assertEqual(
            patch['graph_sequence_constraints'],
            'host_rule_a;host_rule_b;fallback_rule_c;fallback_rule_d',
        )

    def test_normalize_system_level_v1_semantic_state_matches_canonical_projection_state(self) -> None:
        graph = self.load_graph()

        normalized = HELPER_MODULE.normalize_system_level_v1_semantic_state(graph)

        self.assertEqual(normalized['adapter_id'], HELPER_MODULE.SYSTEM_LEVEL_V1_ADAPTER_ID)
        self.assertEqual(normalized['graph_schema_version'], HELPER_MODULE.SYSTEM_LEVEL_V1_GRAPH_SCHEMA_VERSION)
        self.assertEqual(normalized['graph_frontdoor_mode'], 'system_level_graph_v1')
        self.assertEqual(normalized['graph_id'], 'qe_f2_balanced_system_level_seed_v1')
        self.assertEqual(normalized['graph_topology_style'], 'balanced_hybrid')
        self.assertEqual(normalized['graph_module_count'], 16)
        self.assertEqual(normalized['graph_flow_count'], 5)
        self.assertEqual(normalized['graph_leaf_component_count'], 0)
        self.assertTrue(normalized['graph_has_fft_unit'])
        self.assertTrue(normalized['graph_has_reduction_unit'])
        self.assertTrue(normalized['graph_has_diag_unit'])
        self.assertFalse(normalized['graph_has_vector_diag_companion'])
        self.assertTrue(normalized['graph_has_refresh_unit'])
        self.assertFalse(normalized['graph_has_leaf_hotpath_flow'])
        self.assertFalse(normalized['graph_prefers_diag_before_reduction'])
        self.assertFalse(normalized['graph_prefers_refresh_before_diag'])
        self.assertEqual(
            normalized['graph_requested_cluster_sequence'],
            'operator_apply,reduced_build,diag,refresh_residual',
        )
        self.assertEqual(normalized['graph_resolved_cluster_sequence'], 'A,B,C,D')
        self.assertEqual(
            normalized['graph_sequence_constraints'],
            'host_keeps_outer_scf;device_runtime_owns_resident_dma_launch;chip_keeps_operator_reduced_refresh;diag_must_allow_host_fallback;diag_dim_gt_device_limit -> host_diag_assist;resident_spill_can_force_host_diag',
        )

    def test_normalize_frontdoor_v0_semantic_state_matches_balanced_graph_template(self) -> None:
        graph = self.load_frontdoor_graph('f2_balanced_graph_v0')

        normalized = HELPER_MODULE.normalize_frontdoor_v0_semantic_state(graph)
        execution_hints = HELPER_MODULE.derive_frontdoor_v0_execution_hints(graph)

        self.assertEqual(normalized['adapter_id'], HELPER_MODULE.FRONTDOOR_V0_ADAPTER_ID)
        self.assertEqual(normalized['graph_schema_version'], HELPER_MODULE.FRONTDOOR_V0_GRAPH_SCHEMA_VERSION)
        self.assertEqual(normalized['graph_frontdoor_mode'], 'frontdoor_graph_v0')
        self.assertEqual(normalized['graph_id'], 'f2_balanced_graph_v0')
        self.assertEqual(normalized['graph_topology_style'], 'balanced')
        self.assertEqual(normalized['graph_module_count'], 25)
        self.assertEqual(normalized['graph_flow_count'], 3)
        self.assertEqual(normalized['graph_leaf_component_count'], 12)
        self.assertTrue(normalized['graph_has_fft_unit'])
        self.assertTrue(normalized['graph_has_reduction_unit'])
        self.assertTrue(normalized['graph_has_diag_unit'])
        self.assertTrue(normalized['graph_has_vector_diag_companion'])
        self.assertFalse(normalized['graph_has_refresh_unit'])
        self.assertTrue(normalized['graph_has_leaf_hotpath_flow'])
        self.assertFalse(normalized['graph_prefers_diag_before_reduction'])
        self.assertFalse(normalized['graph_prefers_refresh_before_diag'])
        self.assertEqual(normalized['graph_requested_cluster_sequence'], 'A>B>C')
        self.assertEqual(normalized['graph_resolved_cluster_sequence'], 'A>B>C>D_bypass')
        self.assertEqual(
            normalized['graph_sequence_constraints'],
            'requested=A>B>C | resolved=A>B>C>D_bypass',
        )
        self.assertEqual(execution_hints['requested_cluster_sequence'], 'A>B>C')
        self.assertEqual(execution_hints['resolved_cluster_sequence'], 'A>B>C>D_bypass')
        self.assertEqual(
            execution_hints['sequence_constraint_notes'],
            'requested=A>B>C | resolved=A>B>C>D_bypass',
        )
        self.assertEqual(execution_hints['leaf_component_count'], 12)
        self.assertTrue(execution_hints['enable_fft'])
        self.assertTrue(execution_hints['allow_cpu_diag_fallback'])
        self.assertFalse(execution_hints['force_host_diag'])
        self.assertEqual(execution_hints['execution_mode'], 'projected_design_point_only')
        self.assertEqual(execution_hints['device_diag_max_dim'], 32)

    def test_unsupported_schema_raises_graph_projection_error(self) -> None:
        graph = json.loads(json.dumps(self.load_graph()))
        graph['graph_schema_version'] = 'qe_ic_graph_schema_unknown'

        with self.assertRaisesRegex(HELPER_MODULE.GraphProjectionError, 'requires graph_schema_version'):
            HELPER_MODULE.normalize_system_level_v1_semantic_state(graph)

    def test_unknown_alias_raises_graph_projection_error(self) -> None:
        graph = json.loads(json.dumps(self.load_frontdoor_graph('f2_balanced_graph_v0')))
        graph['modules'][0]['component_ref'] = 'unknown_frontdoor_component_alias'

        with self.assertRaisesRegex(HELPER_MODULE.GraphProjectionError, 'unknown frontdoor_v0 component alias'):
            HELPER_MODULE.normalize_frontdoor_v0_semantic_state(graph)

    def test_missing_v1_authority_key_raises_graph_projection_error(self) -> None:
        graph = json.loads(json.dumps(self.load_graph()))
        del graph['join_keys']['family']

        with self.assertRaisesRegex(HELPER_MODULE.GraphProjectionError, 'missing required field: family'):
            HELPER_MODULE.project_system_level_v1_design_point(graph)

    def test_missing_v1_workload_field_raises_graph_projection_error(self) -> None:
        graph = json.loads(json.dumps(self.load_graph()))
        del graph['workload_class']['software_family']

        with self.assertRaisesRegex(HELPER_MODULE.GraphProjectionError, 'missing required field: software_family'):
            HELPER_MODULE.project_system_level_v1_system_run_config_patch(graph)

    def test_frontdoor_v0_requires_main_flow_and_validates_all_flow_steps(self) -> None:
        graph_without_main = json.loads(json.dumps(self.load_frontdoor_graph('f2_balanced_graph_v0')))
        graph_without_main['flows'] = [flow for flow in graph_without_main['flows'] if flow['flow_id'] != 'main']

        with self.assertRaisesRegex(HELPER_MODULE.GraphProjectionError, 'requires main flow'):
            HELPER_MODULE.normalize_frontdoor_v0_semantic_state(graph_without_main)

        graph_with_bad_sidecar_step = json.loads(json.dumps(self.load_frontdoor_graph('f2_balanced_graph_v0')))
        for flow in graph_with_bad_sidecar_step['flows']:
            if flow['flow_id'] == 'diag_fallback_sidecar':
                flow['steps'] = ['diag0', 'missing_instance_ref']

        with self.assertRaisesRegex(HELPER_MODULE.GraphProjectionError, 'diag_fallback_sidecar references unknown instance_id'):
            HELPER_MODULE.normalize_frontdoor_v0_semantic_state(graph_with_bad_sidecar_step)


if __name__ == '__main__':
    unittest.main()
