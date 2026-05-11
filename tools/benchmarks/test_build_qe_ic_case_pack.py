from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name('build_qe_ic_case_pack.py')
SPEC = importlib.util.spec_from_file_location('build_qe_ic_case_pack', MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BuildQeIcCasePackTests(unittest.TestCase):
    def test_build_case_pack_contains_stage_a_stage_b_and_generalization(self) -> None:
        runner = MODULE.load_runner()
        matrix = MODULE.load_json(MODULE.MATRIX_PATH)
        phase_config = MODULE.load_json(MODULE.PHASE_CONFIG_PATH)
        bundle = MODULE.build_case_pack(matrix, phase_config, runner)
        self.assertEqual(bundle['bundle_role'], 'canonical_f1_seed_pack')
        self.assertEqual(bundle['seed_family'], 'F1')
        self.assertIn('canonical F1 seed pack', bundle['seed_bundle_note'])
        fast_required = set(phase_config['layers']['fast_layer']['descriptor_fields'])
        accurate_required = set(phase_config['layers']['accurate_layer']['descriptor_fields'])
        self.assertEqual(
            [item['workload_id'] for item in bundle['stage_a_bringup_descriptors']],
            ['si4_pbe_uspp_small', 'graphene_pbe_uspp', 'si8_pbe_nc'],
        )
        self.assertEqual(
            [item['workload_id'] for item in bundle['stage_b_nonblocking_signature_descriptors']],
            ['au_slab_subspace', 'sic32_subspace'],
        )
        self.assertEqual(
            [item['workload_id'] for item in bundle['accurate_layer_anchor_descriptors']],
            ['si8_pbe_nc'],
        )
        self.assertEqual(
            [item['workload_id'] for item in bundle['accurate_layer_coverage_descriptors']],
            ['si8_pbe_uspp'],
        )
        self.assertEqual(
            [item['workload_id'] for item in bundle['accurate_layer_generalization_descriptors']],
            ['si4_pbe_uspp_small', 'graphene_pbe_uspp', 'graphene_pbe_paw', 'h2_tiny'],
        )
        for section in [
            'stage_a_bringup_descriptors',
            'stage_b_nonblocking_signature_descriptors',
        ]:
            for item in bundle[section]:
                self.assertTrue(item['signature_id'])
                self.assertEqual(item['workload_group_id'], runner.PHASE1_WORKLOAD_GROUP_ID)
                self.assertEqual(item['observability_contract_id'], runner.PHASE1_OBSERVABILITY_CONTRACT_ID)
                self.assertEqual(item['qe_tolerance_schema_id'], MODULE.DEFAULT_QE_TOLERANCE_SCHEMA_ID)
                self.assertEqual(item['accounting_boundary_id'], MODULE.DEFAULT_ACCOUNTING_BOUNDARY_ID)
                self.assertIn('algorithm_contract_deviation', item)
                self.assertFalse(item['algorithm_contract_deviation'])
                for field in [
                    'projector_pressure',
                    'nonlocal_pressure',
                    'generalized_ratio_bucket',
                    'diag_dominance',
                    'fft_grid_pressure',
                ]:
                    self.assertIn(field, item)
                    self.assertTrue(item[field])
                self.assertTrue(fast_required.issubset(item.keys()))

        for section in [
            'accurate_layer_anchor_descriptors',
            'accurate_layer_coverage_descriptors',
            'accurate_layer_generalization_descriptors',
        ]:
            for item in bundle[section]:
                self.assertTrue(item['signature_id'])
                self.assertEqual(item['workload_group_id'], runner.PHASE1_WORKLOAD_GROUP_ID)
                self.assertEqual(item['observability_contract_id'], runner.PHASE1_OBSERVABILITY_CONTRACT_ID)
                self.assertEqual(item['qe_tolerance_schema_id'], MODULE.DEFAULT_QE_TOLERANCE_SCHEMA_ID)
                self.assertEqual(item['accounting_boundary_id'], MODULE.DEFAULT_ACCOUNTING_BOUNDARY_ID)
                self.assertTrue(accurate_required.issubset(item.keys()))
                self.assertNotIn('canonical_profile_match', item)
                self.assertTrue(item['gold_required'])
                if section == 'accurate_layer_generalization_descriptors':
                    self.assertEqual(item['numerical_provenance_tag'], 'calibrated')


    def test_main_writes_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / 'case_pack.json'
            import sys
            old_argv = sys.argv
            try:
                sys.argv = ['build_qe_ic_case_pack.py', '--output', str(out)]
                result = MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(result, 0)
            self.assertTrue(out.exists())
            payload = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(payload['schema_version'], 'qe_ic_case_pack_v0')
            self.assertEqual(payload['bundle_role'], 'canonical_f1_seed_pack')

    def test_main_records_override_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            matrix_copy = root / 'matrix.json'
            phase_copy = root / 'phase.json'
            matrix_copy.write_text(MODULE.MATRIX_PATH.read_text(encoding='utf-8'), encoding='utf-8')
            phase_copy.write_text(MODULE.PHASE_CONFIG_PATH.read_text(encoding='utf-8'), encoding='utf-8')
            out = root / 'case_pack.json'
            import sys
            old_argv = sys.argv
            try:
                sys.argv = [
                    'build_qe_ic_case_pack.py',
                    '--matrix', str(matrix_copy),
                    '--phase-config', str(phase_copy),
                    '--output', str(out),
                ]
                result = MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(result, 0)
            payload = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(payload['matrix_path'], str(matrix_copy))
            self.assertEqual(payload['phase_config_path'], str(phase_copy))
            self.assertEqual(payload['seed_family'], 'F1')


if __name__ == '__main__':
    unittest.main()
