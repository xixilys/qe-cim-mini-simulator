from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name('build_qe_ic_component_registry.py')
SPEC = importlib.util.spec_from_file_location('build_qe_ic_component_registry', MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BuildQeIcComponentRegistryTests(unittest.TestCase):
    def test_build_registry_validates_live_catalog_and_graph_seed_refs(self) -> None:
        catalog = MODULE.load_json(MODULE.CATALOG_PATH)
        graph_seeds = MODULE.load_json(MODULE.GRAPH_SEEDS_PATH)
        active_sources = MODULE.load_cmake_active_sources(MODULE.CMAKE_PATH)
        registry = MODULE.build_registry(
            catalog,
            graph_seeds,
            active_sources,
            catalog_path=MODULE.CATALOG_PATH,
            graph_seeds_path=MODULE.GRAPH_SEEDS_PATH,
            cmake_path=MODULE.CMAKE_PATH,
            readme_path=MODULE.README_PATH,
        )
        validation = registry['validation']
        self.assertTrue(validation['all_strict_checks_pass'])
        self.assertTrue(validation['graph_component_ref_pass'])
        self.assertTrue(validation['strict_backbone_coverage_pass'])
        self.assertEqual(validation['component_count'], len(registry['component_registry']))
        self.assertEqual(validation['component_count'], 29)
        self.assertEqual(validation['strict_backbone_component_count'], 16)
        self.assertEqual(validation['shared_anchor_count'], 1)
        self.assertEqual(
            registry['anchor_to_components']['model/qe_band_solver_model/src/interconnect.cpp'],
            ['dma_channel', 'interconnect_fabric'],
        )
        component_ids = {entry['component_id'] for entry in registry['component_registry']}
        self.assertTrue(
            {
                'system_container',
                'chip_execution_facade',
                'cluster_flow_executor',
                'command_scheduler',
                'vector_diag_companion',
                'near_memory_domain',
                'cim_operator_subchain',
                'cim_array_core',
                'residue_3m_core',
                'coefficient_accumulator',
                'row_merge_tree',
                'context_loader',
                'digit_serial_input_boundary',
                'conjugate_sign_selector',
                'near_sram_coeff_buffer',
                'near_sram_row_buffer',
                'near_sram_support',
                'reduction_closure_engine',
            }
            <= component_ids
        )
        for entry in registry['component_registry']:
            self.assertTrue(entry['anchor_exists'])
            self.assertTrue(entry['anchor_in_active_build'])
            self.assertTrue(entry['header_exists'])
            self.assertTrue(entry['symbol_match_pass'])
        self.assertEqual(len(registry['graph_seed_validation']['templates']), 3)
        self.assertFalse(registry['graph_seed_validation']['unresolved_component_refs'])

    def test_registry_surfaces_intentional_and_future_gap_sources(self) -> None:
        catalog = MODULE.load_json(MODULE.CATALOG_PATH)
        graph_seeds = MODULE.load_json(MODULE.GRAPH_SEEDS_PATH)
        active_sources = MODULE.load_cmake_active_sources(MODULE.CMAKE_PATH)
        registry = MODULE.build_registry(
            catalog,
            graph_seeds,
            active_sources,
            catalog_path=MODULE.CATALOG_PATH,
            graph_seeds_path=MODULE.GRAPH_SEEDS_PATH,
            cmake_path=MODULE.CMAKE_PATH,
            readme_path=MODULE.README_PATH,
        )
        gaps = {item['path']: item for item in registry['unmapped_active_sources']}
        self.assertNotIn('model/qe_band_solver_model/src/dft_hybrid_system.cpp', gaps)
        self.assertNotIn('model/qe_band_solver_model/src/chip_top.cpp', gaps)
        self.assertNotIn('model/qe_band_solver_model/src/clusters/cluster_graph_executor.cpp', gaps)
        self.assertIn('model/qe_band_solver_model/src/architecture_template.cpp', gaps)
        self.assertEqual(
            gaps['model/qe_band_solver_model/src/architecture_template.cpp']['category'],
            'intentional_v0_container_gap',
        )
        self.assertIn('model/qe_band_solver_model/sc_main.cpp', gaps)
        self.assertEqual(
            gaps['model/qe_band_solver_model/sc_main.cpp']['category'],
            'runtime_support_not_seeded_yet',
        )
        self.assertEqual(registry['validation']['intentional_unmapped_active_source_count'], 1)
        self.assertEqual(registry['validation']['future_catalog_expansion_candidate_count'], 1)
        self.assertEqual(len(gaps), 2)

    def test_main_writes_registry_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / 'component_registry.json'
            old_argv = sys.argv
            try:
                sys.argv = ['build_qe_ic_component_registry.py', '--output', str(out)]
                result = MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(result, 0)
            payload = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(payload['schema_version'], 'qe_ic_component_registry_v0')
            self.assertEqual(payload['catalog_version'], 'qe_ic_component_catalog_seed_v0')
            self.assertTrue(payload['validation']['all_strict_checks_pass'])
            self.assertTrue(payload['unmapped_active_sources'])


if __name__ == '__main__':
    unittest.main()
