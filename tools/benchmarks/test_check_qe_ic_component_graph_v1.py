from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name('check_qe_ic_component_graph_v1.py')
SPEC = importlib.util.spec_from_file_location('check_qe_ic_component_graph_v1', MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / 'docs/architecture/qe_ic_component_catalog_system_level_v1.json'
GRAPH_PATH = ROOT / 'docs/architecture/qe_ic_graph_seed_system_level_v1.json'


class CheckQeIcComponentGraphV1Tests(unittest.TestCase):
    def load_inputs(self) -> tuple[dict, dict]:
        catalog = MODULE.load_json(CATALOG_PATH)
        graph = MODULE.load_json(GRAPH_PATH)
        return catalog, graph

    def test_canonical_seed_projects_expected_outputs(self) -> None:
        catalog, graph = self.load_inputs()
        index = MODULE.validate_catalog(catalog)
        MODULE.validate_graph(graph, index)

        self.assertEqual(
            MODULE.project_design_point(graph),
            {
                'family': 'F2',
                'diag_policy': 'device_first_fallback',
                'offload_scope': 'balanced',
                'resident_policy': 'fit_first',
                'partition_strategy': 'operator__build__diag__refresh',
            },
        )
        self.assertEqual(
            MODULE.project_shared_join_keys(graph),
            {
                'fairness_policy_id': 'qe_cpu_gpu_fpga_fairness_v0',
                'observability_contract_id': 'qe_simulator_board_observability_v0',
                'qe_tolerance_schema_id': 'qe_gold_numerical_tolerance_schema_v0',
                'workload_group_id': 'qe_next_stage_mainline',
                'workload_id': 'si4_pbe_uspp_small',
            },
        )

        patch = MODULE.project_system_run_config_patch(graph)
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

    def test_projection_passes_through_signature_id_when_present(self) -> None:
        _, graph = self.load_inputs()
        graph = json.loads(json.dumps(graph))
        graph['workload_class']['signature_id'] = 'sig::qe_f2_balanced'

        patch = MODULE.project_system_run_config_patch(graph)
        self.assertEqual(patch['signature_id'], 'sig::qe_f2_balanced')


if __name__ == '__main__':
    unittest.main()
