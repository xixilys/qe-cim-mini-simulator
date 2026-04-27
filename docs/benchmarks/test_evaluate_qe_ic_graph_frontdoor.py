from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name('evaluate_qe_ic_graph_frontdoor.py')
SPEC = importlib.util.spec_from_file_location('evaluate_qe_ic_graph_frontdoor', MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = ROOT / 'docs/architecture/qe_ic_graph_seed_templates_v0.json'


class EvaluateQeIcGraphFrontdoorTests(unittest.TestCase):
    def load_seed_templates(self) -> list[dict]:
        return json.loads(SEED_PATH.read_text(encoding='utf-8'))['templates']

    def test_frontdoor_evaluator_ranks_balanced_graph_ahead_of_host_heavy_graph(self) -> None:
        templates = self.load_seed_templates()
        f1 = next(item for item in templates if item['seed_template_id'] == 'f1_single_hotpath_graph_v0')
        f2 = next(item for item in templates if item['seed_template_id'] == 'f2_balanced_graph_v0')
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            f1_path = root / 'f1.json'
            f2_path = root / 'f2.json'
            out = root / 'eval.json'
            f1_path.write_text(json.dumps(f1, indent=2) + '\n', encoding='utf-8')
            f2_path.write_text(json.dumps(f2, indent=2) + '\n', encoding='utf-8')
            old_argv = sys.argv
            try:
                sys.argv = [
                    'evaluate_qe_ic_graph_frontdoor.py',
                    '--graph', str(f1_path), str(f2_path),
                    '--output', str(out),
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(payload['schema_version'], 'qe_ic_graph_frontdoor_eval_v0')
            self.assertEqual(payload['graph_count'], 2)
            self.assertEqual(payload['best_graph_id'], 'f2_balanced_graph_v0')
            ranked = payload['ranked_graphs']
            self.assertEqual(ranked[0]['seed_template_id'], 'f2_balanced_graph_v0')
            self.assertIn('context_loader', ranked[0]['leaf_component_refs_summary'])
            self.assertEqual(ranked[0]['component_score_source'], 'graph_frontdoor_structural_proxy')

    def test_frontdoor_evaluator_accepts_noncanonical_json_graph(self) -> None:
        templates = self.load_seed_templates()
        graph = json.loads(json.dumps(next(item for item in templates if item['seed_template_id'] == 'f1_single_hotpath_graph_v0')))
        graph['graph_id'] = 'custom_graph_noncanonical'
        graph['seed_template_id'] = 'custom_noncanonical_graph_v0'
        graph['modules'].append(
            {
                'instance_id': 'diag_helper0',
                'component_ref': 'vector_diag_companion',
                'role': 'diag_helper',
                'placement': 'fpga',
            }
        )
        graph['links'].append(
            {
                'link_id': 'l_extra',
                'src': 'diag0',
                'dst': 'diag_helper0',
                'payload_kind': 'diag_postprocess',
            }
        )
        graph['flows'].append(
            {
                'flow_id': 'diag_sidecar',
                'steps': ['diag0', 'diag_helper0'],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            graph_path = root / 'custom.json'
            out = root / 'eval.json'
            graph_path.write_text(json.dumps(graph, indent=2) + '\n', encoding='utf-8')
            old_argv = sys.argv
            try:
                sys.argv = [
                    'evaluate_qe_ic_graph_frontdoor.py',
                    '--graph', str(graph_path),
                    '--output', str(out),
                ]
                rc = MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding='utf-8'))
            ranked = payload['ranked_graphs'][0]
            self.assertFalse(ranked['canonical_seed_match'])
            self.assertEqual(ranked['canonical_seed_template_id'], 'f1_single_hotpath_graph_v0')
            self.assertIn('vector_diag_companion', ranked['key_component_refs_summary'])

    def test_frontdoor_evaluator_rejects_unknown_component_ref(self) -> None:
        templates = self.load_seed_templates()
        graph = json.loads(json.dumps(next(item for item in templates if item['seed_template_id'] == 'f1_single_hotpath_graph_v0')))
        graph['modules'][0]['component_ref'] = 'definitely_missing_component'
        with tempfile.TemporaryDirectory() as tmpdir:
            graph_path = Path(tmpdir) / 'bad.json'
            graph_path.write_text(json.dumps(graph, indent=2) + '\n', encoding='utf-8')
            with self.assertRaisesRegex(MODULE.GraphFrontdoorError, 'unknown component_ref'):
                MODULE.evaluate_graph(
                    graph_path,
                    graph,
                    {str(item['component_id']): item for item in json.loads(MODULE.DEFAULT_CATALOG_PATH.read_text(encoding='utf-8'))['components']},
                    MODULE.load_module('runner_for_test', MODULE.RUNNER_PATH),
                )


if __name__ == '__main__':
    unittest.main()
