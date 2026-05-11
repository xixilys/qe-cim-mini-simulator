from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name('run_qe_ic_graph_frontdoor.py')
SPEC = importlib.util.spec_from_file_location('run_qe_ic_graph_frontdoor', MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = ROOT / 'docs/architecture/qe_ic_graph_seed_templates_v0.json'


class RunQeIcGraphFrontdoorTests(unittest.TestCase):
    def load_seed_templates(self) -> list[dict]:
        return json.loads(SEED_PATH.read_text(encoding='utf-8'))['templates']

    def test_frontdoor_run_ranks_graphs_for_workload_without_execute_model(self) -> None:
        templates = self.load_seed_templates()
        f1 = next(item for item in templates if item['seed_template_id'] == 'f1_single_hotpath_graph_v0')
        f2 = next(item for item in templates if item['seed_template_id'] == 'f2_balanced_graph_v0')
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            f1_path = root / 'f1.json'
            f2_path = root / 'f2.json'
            out = root / 'run.json'
            f1_path.write_text(json.dumps(f1, indent=2) + '\n', encoding='utf-8')
            f2_path.write_text(json.dumps(f2, indent=2) + '\n', encoding='utf-8')
            old_argv = sys.argv
            try:
                sys.argv = [
                    'run_qe_ic_graph_frontdoor.py',
                    '--graph', str(f1_path), str(f2_path),
                    '--workload-id', 'si4_pbe_uspp_small',
                    '--output', str(out),
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(payload['schema_version'], 'qe_ic_graph_frontdoor_run_v0')
            self.assertFalse(payload['execute_model'])
            self.assertEqual(payload['best_graph_id'], 'f2_balanced_graph_v0')
            self.assertEqual(len(payload['ranked_results']), 2)
            top = payload['ranked_results'][0]
            self.assertEqual(top['result_row']['workload']['workload_id'], 'si4_pbe_uspp_small')
            self.assertEqual(top['result_row']['graph_evidence']['graph_export_authority'], 'frontdoor_graph_json')
            self.assertIn('requested=A>B>C', top['result_row']['graph_evidence']['execution_plan_summary'])
            self.assertIn('resolved=A>B>C>D_bypass', top['result_row']['graph_evidence']['execution_plan_summary'])
            self.assertIn('source=projected_hints', top['result_row']['graph_evidence']['execution_plan_summary'])
            self.assertEqual(top['execution_plan_summary'], top['result_row']['graph_evidence']['execution_plan_summary'])
            self.assertTrue(top['result_row']['artifacts']['graph_evidence_path'])
            self.assertIn('join_keys projection', top['projection_limitation'])

    def test_frontdoor_run_execute_model_emits_runtime_graph_scores(self) -> None:
        templates = self.load_seed_templates()
        f1 = next(item for item in templates if item['seed_template_id'] == 'f1_single_hotpath_graph_v0')
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            graph_path = root / 'f1.json'
            out = root / 'run.json'
            graph_path.write_text(json.dumps(f1, indent=2) + '\n', encoding='utf-8')
            old_argv = sys.argv
            try:
                sys.argv = [
                    'run_qe_ic_graph_frontdoor.py',
                    '--graph', str(graph_path),
                    '--workload-id', 'si4_pbe_uspp_small',
                    '--output', str(out),
                    '--execute-model',
                    '--model-bin', str(ROOT / 'model/qe_band_solver_model/build/qe_band_solver_model'),
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding='utf-8'))
            self.assertTrue(payload['execute_model'])
            row = payload['ranked_results'][0]['result_row']
            self.assertEqual(row['graph_evidence']['component_score_source'], 'runtime_cluster_signature_weighted')
            self.assertTrue(row['graph_evidence']['cluster_cycle_summary'])
            self.assertTrue(row['graph_evidence']['component_score_signal_summary'])
            self.assertIn('executed=A>B_bypass>C>D_bypass', row['graph_evidence']['execution_plan_summary'])
            self.assertIn('source=resolved_cluster_sequence', row['graph_evidence']['execution_plan_summary'])
            self.assertTrue(row['primary_metrics']['time_to_convergence_s'] is not None)
            self.assertIn('graph_frontdoor_execution_mode=projected_design_point_only', row['correctness']['notes'])
            candidate = json.loads(Path(row['artifacts']['metrics_path']).read_text(encoding='utf-8'))
            self.assertIn('graph_frontdoor_profile', candidate)
            self.assertEqual(candidate['graph_frontdoor_profile']['mode'], 'projected_design_point_only')
            self.assertEqual(candidate['graph_frontdoor_profile']['graph_id'], 'f1_single_hotpath_graph_v0')
            self.assertEqual(candidate['graph_frontdoor_profile']['has_fft_unit'], False)
            self.assertEqual(candidate['graph_frontdoor_profile']['has_reduction_unit'], False)
            self.assertEqual(candidate['graph_frontdoor_profile']['has_diag_unit'], True)
            self.assertEqual(candidate['graph_frontdoor_profile']['requested_cluster_sequence'], 'A>C')
            self.assertTrue(candidate['graph_frontdoor_profile']['resolved_cluster_sequence'])
            self.assertEqual(candidate['graph_frontdoor_profile']['resolved_cluster_sequence'], 'A>B_bypass>C>D_bypass')
            self.assertEqual(
                candidate['graph_frontdoor_profile']['executed_cluster_sequence'],
                candidate['graph_frontdoor_profile']['resolved_cluster_sequence'],
            )
            self.assertEqual(candidate['graph_frontdoor_profile']['execution_plan_source'], 'resolved_cluster_sequence')
            self.assertEqual(candidate['run_config']['enable_fft'], False)
            self.assertGreater(candidate['run_config']['device_diag_max_dim'], 8)
            self.assertTrue(candidate['run_config']['allow_cpu_diag_fallback'])
            self.assertEqual(candidate['cluster_metrics']['cluster_b']['cluster_name'], 'ClusterBBypass')
            self.assertEqual(candidate['cluster_metrics']['cluster_b']['dominant_resource'], 'GraphFrontdoor.ReductionBypass')
            self.assertEqual(candidate['cluster_metrics']['cluster_d']['cluster_name'], 'ClusterDBypass')
            self.assertEqual(candidate['cluster_metrics']['cluster_d']['dominant_resource'], 'GraphFrontdoor.RefreshBypass')
            self.assertIn('graph_leaf_flow=present', candidate['cluster_metrics']['cluster_a']['detail'])
            self.assertIn('graph_fft=no', candidate['cluster_metrics']['cluster_a']['detail'])

    def test_frontdoor_run_execute_model_can_flip_diag_before_reduction(self) -> None:
        templates = self.load_seed_templates()
        graph = json.loads(json.dumps(next(item for item in templates if item['seed_template_id'] == 'f2_balanced_graph_v0')))
        graph['graph_id'] = 'custom_diag_before_reduction'
        graph['seed_template_id'] = 'custom_diag_before_reduction'
        for flow in graph['flows']:
            if flow['flow_id'] == 'main':
                flow['steps'] = ['sys0', 'host', 'dma0', 'chip0', 'flow0', 'epc0', 'sched0', 'nmem0', 'fft0', 'cim0', 'diag0']
            if flow['flow_id'] == 'leaf_hotpath_chain':
                flow['steps'] = [step for step in flow['steps'] if step != 'red0' and step != 'close0']
        graph['modules'] = [item for item in graph['modules'] if item['instance_id'] != 'red0']
        graph['links'] = [item for item in graph['links'] if item['src'] != 'red0' and item['dst'] != 'red0']
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            graph_path = root / 'graph.json'
            out = root / 'run.json'
            graph_path.write_text(json.dumps(graph, indent=2) + '\n', encoding='utf-8')
            old_argv = sys.argv
            try:
                sys.argv = [
                    'run_qe_ic_graph_frontdoor.py',
                    '--graph', str(graph_path),
                    '--workload-id', 'si4_pbe_uspp_small',
                    '--output', str(out),
                    '--execute-model',
                    '--model-bin', str(ROOT / 'model/qe_band_solver_model/build/qe_band_solver_model'),
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding='utf-8'))
            candidate = json.loads(Path(payload['ranked_results'][0]['result_row']['artifacts']['metrics_path']).read_text(encoding='utf-8'))
            self.assertEqual(candidate['graph_frontdoor_profile']['has_reduction_unit'], False)
            self.assertEqual(candidate['graph_frontdoor_profile']['requested_cluster_sequence'], 'A>C')
            self.assertEqual(candidate['graph_frontdoor_profile']['resolved_cluster_sequence'], 'A>B_bypass>C>D_bypass')
            self.assertEqual(candidate['graph_frontdoor_profile']['executed_cluster_sequence'], 'A>B_bypass>C>D_bypass')
            self.assertEqual(candidate['graph_frontdoor_profile']['execution_plan_source'], 'resolved_cluster_sequence')
            self.assertIn('requested=A>C', candidate['graph_frontdoor_profile']['sequence_constraints'])
            self.assertIn('resolved=A>B_bypass>C>D_bypass', candidate['graph_frontdoor_profile']['sequence_constraints'])
            self.assertEqual(candidate['cluster_metrics']['cluster_b']['cluster_name'], 'ClusterBBypass')
            self.assertEqual(candidate['cluster_metrics']['cluster_d']['cluster_name'], 'ClusterDBypass')

    def test_frontdoor_run_execute_model_resolves_refresh_before_diag_order(self) -> None:
        templates = self.load_seed_templates()
        graph = json.loads(json.dumps(next(item for item in templates if item['seed_template_id'] == 'f3_device_heavy_graph_v0')))
        graph['graph_id'] = 'custom_refresh_before_diag'
        graph['seed_template_id'] = 'custom_refresh_before_diag'
        for flow in graph['flows']:
            if flow['flow_id'] == 'main':
                flow['steps'] = ['sys0', 'host', 'dma0', 'chip0', 'flow0', 'epc0', 'sched0', 'nmem0', 'fft0', 'cim0', 'red0', 'ref0', 'diag0', 'vdiag0']
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            graph_path = root / 'graph.json'
            out = root / 'run.json'
            graph_path.write_text(json.dumps(graph, indent=2) + '\n', encoding='utf-8')
            old_argv = sys.argv
            try:
                sys.argv = [
                    'run_qe_ic_graph_frontdoor.py',
                    '--graph', str(graph_path),
                    '--workload-id', 'si4_pbe_uspp_small',
                    '--output', str(out),
                    '--execute-model',
                    '--model-bin', str(ROOT / 'model/qe_band_solver_model/build/qe_band_solver_model'),
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding='utf-8'))
            candidate = json.loads(Path(payload['ranked_results'][0]['result_row']['artifacts']['metrics_path']).read_text(encoding='utf-8'))
            self.assertEqual(candidate['graph_frontdoor_profile']['requested_cluster_sequence'], 'A>B>D>C')
            self.assertEqual(candidate['graph_frontdoor_profile']['resolved_cluster_sequence'], 'A>B>C>D')
            self.assertEqual(candidate['graph_frontdoor_profile']['executed_cluster_sequence'], 'A>B>C>D')
            self.assertEqual(candidate['graph_frontdoor_profile']['execution_plan_source'], 'resolved_cluster_sequence')
            self.assertIn('requested=A>B>D>C', candidate['graph_frontdoor_profile']['sequence_constraints'])
            self.assertIn('resolved=A>B>C>D', candidate['graph_frontdoor_profile']['sequence_constraints'])
            self.assertEqual(candidate['cluster_metrics']['cluster_b']['cluster_name'], 'ClusterB')
            self.assertEqual(candidate['cluster_metrics']['cluster_c']['cluster_name'], 'ClusterC')
            self.assertEqual(candidate['cluster_metrics']['cluster_d']['cluster_name'], 'ClusterD')
            self.assertIn('graph_vdiag=yes', candidate['cluster_metrics']['cluster_c']['detail'])
            self.assertIn('graph_vdiag=yes', candidate['cluster_metrics']['cluster_d']['detail'])

    def test_frontdoor_run_execute_model_supports_diag_bypass_sequence(self) -> None:
        templates = self.load_seed_templates()
        graph = json.loads(json.dumps(next(item for item in templates if item['seed_template_id'] == 'f3_device_heavy_graph_v0')))
        graph['graph_id'] = 'custom_diag_bypass'
        graph['seed_template_id'] = 'custom_diag_bypass'
        graph['modules'] = [item for item in graph['modules'] if item['instance_id'] != 'diag0']
        graph['links'] = [item for item in graph['links'] if item['src'] != 'diag0' and item['dst'] != 'diag0']
        for flow in graph['flows']:
            if flow['flow_id'] == 'main':
                flow['steps'] = ['sys0', 'host', 'dma0', 'chip0', 'flow0', 'epc0', 'sched0', 'nmem0', 'fft0', 'cim0', 'red0', 'vdiag0', 'ref0']
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            graph_path = root / 'graph.json'
            out = root / 'run.json'
            graph_path.write_text(json.dumps(graph, indent=2) + '\n', encoding='utf-8')
            old_argv = sys.argv
            try:
                sys.argv = [
                    'run_qe_ic_graph_frontdoor.py',
                    '--graph', str(graph_path),
                    '--workload-id', 'si4_pbe_uspp_small',
                    '--output', str(out),
                    '--execute-model',
                    '--model-bin', str(ROOT / 'model/qe_band_solver_model/build/qe_band_solver_model'),
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding='utf-8'))
            candidate = json.loads(Path(payload['ranked_results'][0]['result_row']['artifacts']['metrics_path']).read_text(encoding='utf-8'))
            self.assertEqual(candidate['graph_frontdoor_profile']['has_diag_unit'], False)
            self.assertEqual(candidate['graph_frontdoor_profile']['requested_cluster_sequence'], 'A>B>C>D')
            self.assertEqual(candidate['graph_frontdoor_profile']['resolved_cluster_sequence'], 'A>B>C_bypass>D')
            self.assertEqual(candidate['graph_frontdoor_profile']['executed_cluster_sequence'], 'A>B>C_bypass>D')
            self.assertEqual(candidate['graph_frontdoor_profile']['execution_plan_source'], 'resolved_cluster_sequence')
            self.assertEqual(candidate['cluster_metrics']['cluster_c']['cluster_name'], 'ClusterCBypass')
            self.assertEqual(candidate['cluster_metrics']['cluster_d']['cluster_name'], 'ClusterD')

    def test_frontdoor_run_execute_model_leaf_flow_absence_changes_cluster_a_metrics(self) -> None:
        templates = self.load_seed_templates()
        baseline = json.loads(json.dumps(next(item for item in templates if item['seed_template_id'] == 'f2_balanced_graph_v0')))
        no_leaf = json.loads(json.dumps(baseline))
        no_leaf['graph_id'] = 'custom_no_leaf_hotpath'
        no_leaf['seed_template_id'] = 'custom_no_leaf_hotpath'
        no_leaf['flows'] = [flow for flow in no_leaf['flows'] if flow['flow_id'] != 'leaf_hotpath_chain']
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline_path = root / 'baseline.json'
            no_leaf_path = root / 'no_leaf.json'
            baseline_out = root / 'baseline_run.json'
            no_leaf_out = root / 'no_leaf_run.json'
            baseline_path.write_text(json.dumps(baseline, indent=2) + '\n', encoding='utf-8')
            no_leaf_path.write_text(json.dumps(no_leaf, indent=2) + '\n', encoding='utf-8')
            old_argv = sys.argv
            try:
                sys.argv = [
                    'run_qe_ic_graph_frontdoor.py',
                    '--graph', str(baseline_path),
                    '--workload-id', 'si4_pbe_uspp_small',
                    '--output', str(baseline_out),
                    '--execute-model',
                    '--model-bin', str(ROOT / 'model/qe_band_solver_model/build/qe_band_solver_model'),
                ]
                rc = MODULE.main()
                self.assertEqual(rc, 0)
                baseline_payload = json.loads(baseline_out.read_text(encoding='utf-8'))
                baseline_candidate = json.loads(
                    Path(baseline_payload['ranked_results'][0]['result_row']['artifacts']['metrics_path']).read_text(encoding='utf-8')
                )
                sys.argv = [
                    'run_qe_ic_graph_frontdoor.py',
                    '--graph', str(no_leaf_path),
                    '--workload-id', 'si4_pbe_uspp_small',
                    '--output', str(no_leaf_out),
                    '--execute-model',
                    '--model-bin', str(ROOT / 'model/qe_band_solver_model/build/qe_band_solver_model'),
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            no_leaf_payload = json.loads(no_leaf_out.read_text(encoding='utf-8'))
            no_leaf_candidate = json.loads(
                Path(no_leaf_payload['ranked_results'][0]['result_row']['artifacts']['metrics_path']).read_text(encoding='utf-8')
            )
            self.assertTrue(baseline_candidate['graph_frontdoor_profile']['has_leaf_hotpath_flow'])
            self.assertFalse(no_leaf_candidate['graph_frontdoor_profile']['has_leaf_hotpath_flow'])
            self.assertIn('graph_leaf_flow=present', baseline_candidate['cluster_metrics']['cluster_a']['detail'])
            self.assertIn('graph_leaf_flow=absent', no_leaf_candidate['cluster_metrics']['cluster_a']['detail'])
            self.assertLess(
                no_leaf_candidate['cluster_metrics']['cluster_a']['accounted_ref_cycles'],
                baseline_candidate['cluster_metrics']['cluster_a']['accounted_ref_cycles'],
            )


if __name__ == '__main__':
    unittest.main()
