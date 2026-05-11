from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODEL_BIN = ROOT / 'model/qe_band_solver_model/build/qe_band_solver_model'


class QeSignatureRuntimeHookupTests(unittest.TestCase):
    def run_case(self, case_id: str, extra_env: dict[str, str]) -> dict:
        if not MODEL_BIN.exists():
            self.skipTest(f'model binary missing: {MODEL_BIN}')

        with tempfile.TemporaryDirectory() as tmpdir:
            result_path = Path(tmpdir) / 'candidate.json'
            env = os.environ.copy()
            env.update(
                {
                    'QEBS_CASE_ID': case_id,
                    'QEBS_SIGNATURE_ID': extra_env['QEBS_SIGNATURE_ID'],
                    'QEBS_PROPERTY_TARGET': extra_env['QEBS_PROPERTY_TARGET'],
                    'QEBS_PSEUDOPOTENTIAL_FAMILY': extra_env['QEBS_PSEUDOPOTENTIAL_FAMILY'],
                    'QEBS_SOLVER_PATH_CLASS': extra_env['QEBS_SOLVER_PATH_CLASS'],
                    'QEBS_WORKLOAD_TOPOLOGY': extra_env['QEBS_WORKLOAD_TOPOLOGY'],
                    'QEBS_POST_SCF_EXTENSION_LEVEL': extra_env['QEBS_POST_SCF_EXTENSION_LEVEL'],
                    'QEBS_PROJECTOR_PRESSURE': extra_env['QEBS_PROJECTOR_PRESSURE'],
                    'QEBS_NONLOCAL_PRESSURE': extra_env['QEBS_NONLOCAL_PRESSURE'],
                    'QEBS_GENERALIZED_RATIO_BUCKET': extra_env['QEBS_GENERALIZED_RATIO_BUCKET'],
                    'QEBS_DIAG_DOMINANCE': extra_env['QEBS_DIAG_DOMINANCE'],
                    'QEBS_FFT_GRID_PRESSURE': extra_env['QEBS_FFT_GRID_PRESSURE'],
                    'QEBS_MAX_SCF_ITERS': '1',
                    'QEBS_RESULT_JSON': str(result_path),
                }
            )
            subprocess.run([str(MODEL_BIN)], check=True, env=env, cwd=ROOT)
            return json.loads(result_path.read_text(encoding='utf-8'))

    def test_signature_fields_change_runtime_behavior_for_custom_case(self) -> None:
        nc_2d = self.run_case(
            'custom_sig_case',
            {
                'QEBS_SIGNATURE_ID': 'sig_custom__nc__generalized_overlap__2D__band_gap',
                'QEBS_PROPERTY_TARGET': 'band_gap',
                'QEBS_PSEUDOPOTENTIAL_FAMILY': 'NC',
                'QEBS_SOLVER_PATH_CLASS': 'generalized_overlap',
                'QEBS_WORKLOAD_TOPOLOGY': '2D',
                'QEBS_POST_SCF_EXTENSION_LEVEL': 'mobility_extension_expected',
                'QEBS_PROJECTOR_PRESSURE': 'high',
                'QEBS_NONLOCAL_PRESSURE': 'medium',
                'QEBS_GENERALIZED_RATIO_BUCKET': 'high',
                'QEBS_DIAG_DOMINANCE': 'high',
                'QEBS_FFT_GRID_PRESSURE': 'high',
            }
        )
        uspp_bulk = self.run_case(
            'custom_sig_case',
            {
                'QEBS_SIGNATURE_ID': 'sig_custom__uspp__standard_band__bulk__band_structure',
                'QEBS_PROPERTY_TARGET': 'band_structure',
                'QEBS_PSEUDOPOTENTIAL_FAMILY': 'USPP',
                'QEBS_SOLVER_PATH_CLASS': 'standard_band',
                'QEBS_WORKLOAD_TOPOLOGY': 'bulk',
                'QEBS_POST_SCF_EXTENSION_LEVEL': 'shell_only',
                'QEBS_PROJECTOR_PRESSURE': 'low',
                'QEBS_NONLOCAL_PRESSURE': 'low',
                'QEBS_GENERALIZED_RATIO_BUCKET': 'low',
                'QEBS_DIAG_DOMINANCE': 'low',
                'QEBS_FFT_GRID_PRESSURE': 'low',
            }
        )

        self.assertEqual(nc_2d['run_config']['pseudopotential_family'], 'NC')
        self.assertEqual(uspp_bulk['run_config']['pseudopotential_family'], 'USPP')
        self.assertEqual(nc_2d['run_config']['case_id'], 'custom_sig_case')
        self.assertEqual(nc_2d['iteration_diagnostics'][0]['projector_mode'], 'NC-light')
        self.assertEqual(uspp_bulk['iteration_diagnostics'][0]['projector_mode'], 'USPP')
        self.assertNotEqual(
            nc_2d['iteration_diagnostics'][0]['support_grid_mode'],
            uspp_bulk['iteration_diagnostics'][0]['support_grid_mode'],
        )
        self.assertNotEqual(
            nc_2d['iteration_diagnostics'][0]['diag_path'],
            uspp_bulk['iteration_diagnostics'][0]['diag_path'],
        )
        self.assertNotEqual(
            nc_2d['iteration_diagnostics'][0]['density_delta'],
            uspp_bulk['iteration_diagnostics'][0]['density_delta'],
        )
        self.assertNotEqual(
            nc_2d['final']['total_energy_ry'],
            uspp_bulk['final']['total_energy_ry'],
        )

    def test_named_stage_b_cases_use_signature_aware_runtime_shaping(self) -> None:
        au_slab = self.run_case(
            'au_slab_subspace',
            {
                'QEBS_SIGNATURE_ID': 'sig_au_slab__uspp__standard_band__slab_interface__band_gap',
                'QEBS_PROPERTY_TARGET': 'band_gap',
                'QEBS_PSEUDOPOTENTIAL_FAMILY': 'USPP',
                'QEBS_SOLVER_PATH_CLASS': 'standard_band',
                'QEBS_WORKLOAD_TOPOLOGY': 'slab_interface',
                'QEBS_POST_SCF_EXTENSION_LEVEL': 'shell_only',
                'QEBS_PROJECTOR_PRESSURE': 'high',
                'QEBS_NONLOCAL_PRESSURE': 'high',
                'QEBS_GENERALIZED_RATIO_BUCKET': 'medium',
                'QEBS_DIAG_DOMINANCE': 'high',
                'QEBS_FFT_GRID_PRESSURE': 'high',
            },
        )
        sic32 = self.run_case(
            'sic32_subspace',
            {
                'QEBS_SIGNATURE_ID': 'sig_sic32__uspp__generalized_overlap__wide_bandgap__transport_proxy',
                'QEBS_PROPERTY_TARGET': 'transport_proxy',
                'QEBS_PSEUDOPOTENTIAL_FAMILY': 'USPP',
                'QEBS_SOLVER_PATH_CLASS': 'generalized_overlap',
                'QEBS_WORKLOAD_TOPOLOGY': 'wide_bandgap',
                'QEBS_POST_SCF_EXTENSION_LEVEL': 'mobility_extension_expected',
                'QEBS_PROJECTOR_PRESSURE': 'high',
                'QEBS_NONLOCAL_PRESSURE': 'high',
                'QEBS_GENERALIZED_RATIO_BUCKET': 'high',
                'QEBS_DIAG_DOMINANCE': 'high',
                'QEBS_FFT_GRID_PRESSURE': 'high',
            },
        )

        au_diag = au_slab['iteration_diagnostics'][0]
        sic_diag = sic32['iteration_diagnostics'][0]

        self.assertEqual(au_slab['run_config']['case_id'], 'au_slab_subspace')
        self.assertEqual(sic32['run_config']['case_id'], 'sic32_subspace')
        self.assertEqual(au_diag['support_grid_mode'], 'FFT_AUX')
        self.assertEqual(sic_diag['support_grid_mode'], 'FFT_AUX')
        self.assertEqual(au_diag['diag_path'], 'host_cpu_fallback')
        self.assertEqual(sic_diag['diag_path'], 'host_cpu_fallback')
        self.assertEqual(au_diag['workload_bucket'], 'large')
        self.assertEqual(sic_diag['workload_bucket'], 'large')
        self.assertTrue(au_diag['spill_active'])
        self.assertTrue(sic_diag['spill_active'])
        self.assertLess(au_diag['max_inner_steps'], sic_diag['max_inner_steps'])
        self.assertLess(au_diag['inner_steps'], sic_diag['inner_steps'])
        self.assertLess(au_diag['device_busy_ref_cycles'], sic_diag['device_busy_ref_cycles'])
        self.assertGreater(au_diag['host_assist_ref_cycles'], 0)
        self.assertLess(sic_diag['max_diag_condition_estimate'], au_diag['max_diag_condition_estimate'])
        self.assertNotEqual(au_diag['band_count'], sic_diag['band_count'])
        self.assertNotEqual(au_diag['density_delta'], sic_diag['density_delta'])
        self.assertNotEqual(au_slab['final']['total_energy_ry'], sic32['final']['total_energy_ry'])


if __name__ == '__main__':
    unittest.main()
