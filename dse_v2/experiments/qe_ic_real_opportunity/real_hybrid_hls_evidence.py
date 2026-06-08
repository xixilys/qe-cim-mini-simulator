#!/usr/bin/env python3
"""Real non-stub hybrid HLS evidence helpers for QE-IC campaigns.

This module deliberately separates real HLS kernels from the earlier generated
stub/proxy evidence path.  The kernels are still compact benchmark kernels, but
all evidence rows must be labelled as real HLS kernel attempts and must carry
correctness/simulation/synthesis provenance before they can influence a strong
GPU-vs-hybrid conclusion.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


DEFAULT_FPGA_PART = "xc7z020clg400-1"


def _safe_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    if not text:
        return "architecture"
    if text[0].isdigit():
        text = f"arch_{text}"
    return text[:96]


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def build_real_hybrid_architecture_specs() -> list[dict[str, Any]]:
    """Return non-stub hybrid FPGA HLS architecture candidates."""

    common = {
        "target_type": "gpu_fpga_hybrid",
        "implementation_maturity": "real_hls_kernel",
        "evidence_level": "vivado_hls_csim_csynth_cosim_attempt",
        "claim_strength": "none_until_golden_cosim_synth_and_workflow_gate_pass",
        "gpu_role": "retain full QE dense kernels and SCF orchestration",
        "host_role": "SCF control, diagonalization, mixing, launch and accounting retained",
        "memory_interface": "AXI master streams with explicit transfer accounting",
        "why_real_kernel": "deterministic arithmetic kernel with golden numerical testbench and latency-bearing loops",
    }
    return [
        {
            **common,
            "architecture_id": "hybrid_streaming_reduction_accumulator_v1",
            "kernel_name": "qeic_real_streaming_reduction_accumulator",
            "motif_id": "reduction_collective",
            "golden_vector_length": 64,
            "algorithm_description": "Pairwise complex reduction sidecar for accumulated charge or overlap partial sums.",
            "fpga_role": "stream complex partial sums and emit one deterministic accumulated complex result",
        },
        {
            **common,
            "architecture_id": "hybrid_tiled_complex_axpy_v1",
            "kernel_name": "qeic_real_tiled_complex_axpy",
            "motif_id": "wavefunction_memory",
            "golden_vector_length": 64,
            "algorithm_description": "Tiled complex AXPY/update sidecar for wavefunction-memory staging and overlap with GPU work.",
            "fpga_role": "perform complex vector update y = alpha*x + y over tiled stream buffers",
        },
        {
            **common,
            "architecture_id": "hybrid_fft_twiddle_stream_v1",
            "kernel_name": "qeic_real_fft_twiddle_stream",
            "motif_id": "fft_transpose",
            "golden_vector_length": 64,
            "algorithm_description": "Streaming complex twiddle multiply and deterministic lane remap for FFT/transpose motif.",
            "fpga_role": "apply generated twiddle factors and reorder lanes for a stream tile",
        },
        {
            **common,
            "architecture_id": "hybrid_sum_band_density_accumulator_v1",
            "kernel_name": "qeic_real_sum_band_density_accumulator",
            "motif_id": "sum_band_density_accumulation",
            "golden_vector_length": 128,
            "golden_grid_points": 32,
            "golden_band_count": 4,
            "implementation_coverage": "qe_routine_equivalent_miniapp",
            "mapped_qe_timer_names": ["sum_band"],
            "algorithm_description": "Miniapp for QE sum_band-style density accumulation over bands and grid points.",
            "fpga_role": "accumulate weighted |psi|^2 density contributions across bands for each grid point",
        },
        {
            **common,
            "architecture_id": "hybrid_hpsi_local_potential_v1",
            "kernel_name": "qeic_real_hpsi_local_potential",
            "motif_id": "h_psi_local_potential",
            "golden_vector_length": 96,
            "golden_grid_points": 96,
            "golden_stencil_radius": 1,
            "implementation_coverage": "qe_routine_equivalent_miniapp",
            "mapped_qe_timer_names": ["h_psi"],
            "algorithm_description": "Miniapp for QE h_psi-style local potential plus nearest-neighbor kinetic stencil over a wavefunction grid.",
            "fpga_role": "apply vloc*psi and a compact finite-difference kinetic stencil to complex wavefunction samples",
        },
    ]


def build_evidence_row_static_metadata(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Return spec metadata that every evidence row must preserve."""

    shape: dict[str, int] = {}
    if isinstance(spec.get("golden_grid_points"), int):
        shape["grid_points"] = int(spec["golden_grid_points"])
    if isinstance(spec.get("golden_band_count"), int):
        shape["band_count"] = int(spec["golden_band_count"])
    if isinstance(spec.get("golden_stencil_radius"), int):
        shape["stencil_radius"] = int(spec["golden_stencil_radius"])
    if not shape and isinstance(spec.get("golden_vector_length"), int):
        shape["vector_length"] = int(spec["golden_vector_length"])
    return {
        "implementation_coverage": str(spec.get("implementation_coverage") or "partial_sidecar_motif"),
        "mapped_qe_timer_names": list(spec.get("mapped_qe_timer_names") or _MOTIF_TIMER_MAP.get(str(spec.get("motif_id") or ""), [])),
        "golden_problem_shape": shape,
    }


def _reduction_kernel(spec: Mapping[str, Any]) -> str:
    fn = str(spec["kernel_name"])
    return f"""#include <math.h>
extern "C" void {fn}(const double *real_in, const double *imag_in, double *real_out, double *imag_out, int n) {{
#pragma HLS INTERFACE m_axi port=real_in depth=64 offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=imag_in depth=64 offset=slave bundle=gmem1
#pragma HLS INTERFACE m_axi port=real_out depth=1 offset=slave bundle=gmem2
#pragma HLS INTERFACE m_axi port=imag_out depth=1 offset=slave bundle=gmem3
#pragma HLS INTERFACE s_axilite port=real_in bundle=control
#pragma HLS INTERFACE s_axilite port=imag_in bundle=control
#pragma HLS INTERFACE s_axilite port=real_out bundle=control
#pragma HLS INTERFACE s_axilite port=imag_out bundle=control
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    double acc_re = 0.0;
    double acc_im = 0.0;
    for (int i = 0; i < n; ++i) {{
#pragma HLS PIPELINE II=1
        double wr = 1.0 + 0.0005 * (double)(i & 7);
        double wi = 0.00025 * (double)((i + 3) & 5);
        acc_re += real_in[i] * wr - imag_in[i] * wi;
        acc_im += real_in[i] * wi + imag_in[i] * wr;
    }}
    real_out[0] = acc_re;
    imag_out[0] = acc_im;
}}
"""


def _axpy_kernel(spec: Mapping[str, Any]) -> str:
    fn = str(spec["kernel_name"])
    return f"""extern "C" void {fn}(const double *x_re, const double *x_im, const double *y_re, const double *y_im, double *out_re, double *out_im, int n) {{
#pragma HLS INTERFACE m_axi port=x_re depth=64 offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=x_im depth=64 offset=slave bundle=gmem1
#pragma HLS INTERFACE m_axi port=y_re depth=64 offset=slave bundle=gmem2
#pragma HLS INTERFACE m_axi port=y_im depth=64 offset=slave bundle=gmem3
#pragma HLS INTERFACE m_axi port=out_re depth=64 offset=slave bundle=gmem4
#pragma HLS INTERFACE m_axi port=out_im depth=64 offset=slave bundle=gmem5
#pragma HLS INTERFACE s_axilite port=x_re bundle=control
#pragma HLS INTERFACE s_axilite port=x_im bundle=control
#pragma HLS INTERFACE s_axilite port=y_re bundle=control
#pragma HLS INTERFACE s_axilite port=y_im bundle=control
#pragma HLS INTERFACE s_axilite port=out_re bundle=control
#pragma HLS INTERFACE s_axilite port=out_im bundle=control
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    const double alpha_re = 0.75;
    const double alpha_im = -0.125;
    for (int i = 0; i < n; ++i) {{
#pragma HLS PIPELINE II=1
        double xr = x_re[i];
        double xi = x_im[i];
        out_re[i] = y_re[i] + alpha_re * xr - alpha_im * xi;
        out_im[i] = y_im[i] + alpha_re * xi + alpha_im * xr;
    }}
}}
"""


def _twiddle_kernel(spec: Mapping[str, Any]) -> str:
    fn = str(spec["kernel_name"])
    return f"""#include <math.h>
extern "C" void {fn}(const double *in_re, const double *in_im, double *out_re, double *out_im, int n) {{
#pragma HLS INTERFACE m_axi port=in_re depth=64 offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=in_im depth=64 offset=slave bundle=gmem1
#pragma HLS INTERFACE m_axi port=out_re depth=64 offset=slave bundle=gmem2
#pragma HLS INTERFACE m_axi port=out_im depth=64 offset=slave bundle=gmem3
#pragma HLS INTERFACE s_axilite port=in_re bundle=control
#pragma HLS INTERFACE s_axilite port=in_im bundle=control
#pragma HLS INTERFACE s_axilite port=out_re bundle=control
#pragma HLS INTERFACE s_axilite port=out_im bundle=control
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    for (int i = 0; i < n; ++i) {{
#pragma HLS PIPELINE II=1
        int dst = (i * 17) & (n - 1);
        double angle = 0.02454369260617026 * (double)i;
        double c = cos(angle);
        double s = sin(angle);
        out_re[dst] = in_re[i] * c - in_im[i] * s;
        out_im[dst] = in_re[i] * s + in_im[i] * c;
    }}
}}
"""


def _sum_band_density_kernel(spec: Mapping[str, Any]) -> str:
    fn = str(spec["kernel_name"])
    return f"""extern "C" void {fn}(const double *psi_re, const double *psi_im, const double *weights, double *rho_out, int ngrid, int nbands) {{
#pragma HLS INTERFACE m_axi port=psi_re depth=128 offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=psi_im depth=128 offset=slave bundle=gmem1
#pragma HLS INTERFACE m_axi port=weights depth=4 offset=slave bundle=gmem2
#pragma HLS INTERFACE m_axi port=rho_out depth=64 offset=slave bundle=gmem3
#pragma HLS INTERFACE s_axilite port=psi_re bundle=control
#pragma HLS INTERFACE s_axilite port=psi_im bundle=control
#pragma HLS INTERFACE s_axilite port=weights bundle=control
#pragma HLS INTERFACE s_axilite port=rho_out bundle=control
#pragma HLS INTERFACE s_axilite port=ngrid bundle=control
#pragma HLS INTERFACE s_axilite port=nbands bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    for (int g = 0; g < ngrid; ++g) {{
#pragma HLS PIPELINE II=1
        double acc = 0.0;
        for (int b = 0; b < nbands; ++b) {{
            int idx = b * ngrid + g;
            double re = psi_re[idx];
            double im = psi_im[idx];
            acc += weights[b] * (re * re + im * im);
        }}
        rho_out[g] = acc;
    }}
}}
"""



def _hpsi_local_potential_kernel(spec: Mapping[str, Any]) -> str:
    fn = str(spec["kernel_name"])
    return f"""extern "C" void {fn}(const double *psi_re, const double *psi_im, const double *vloc, double *out_re, double *out_im, int ngrid) {{
#pragma HLS INTERFACE m_axi port=psi_re depth=96 offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=psi_im depth=96 offset=slave bundle=gmem1
#pragma HLS INTERFACE m_axi port=vloc depth=96 offset=slave bundle=gmem2
#pragma HLS INTERFACE m_axi port=out_re depth=96 offset=slave bundle=gmem3
#pragma HLS INTERFACE m_axi port=out_im depth=96 offset=slave bundle=gmem4
#pragma HLS INTERFACE s_axilite port=psi_re bundle=control
#pragma HLS INTERFACE s_axilite port=psi_im bundle=control
#pragma HLS INTERFACE s_axilite port=vloc bundle=control
#pragma HLS INTERFACE s_axilite port=out_re bundle=control
#pragma HLS INTERFACE s_axilite port=out_im bundle=control
#pragma HLS INTERFACE s_axilite port=ngrid bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    const double kinetic_scale = -0.5;
    for (int g = 0; g < ngrid; ++g) {{
#pragma HLS PIPELINE II=1
        int left = (g == 0) ? 0 : g - 1;
        int right = (g == ngrid - 1) ? ngrid - 1 : g + 1;
        double lap_re = psi_re[left] - 2.0 * psi_re[g] + psi_re[right];
        double lap_im = psi_im[left] - 2.0 * psi_im[g] + psi_im[right];
        out_re[g] = kinetic_scale * lap_re + vloc[g] * psi_re[g];
        out_im[g] = kinetic_scale * lap_im + vloc[g] * psi_im[g];
    }}
}}
"""

def _kernel_source(spec: Mapping[str, Any]) -> str:
    architecture_id = str(spec["architecture_id"])
    if "sum_band" in architecture_id:
        return _sum_band_density_kernel(spec)
    if "hpsi" in architecture_id:
        return _hpsi_local_potential_kernel(spec)
    if "reduction" in architecture_id:
        return _reduction_kernel(spec)
    if "axpy" in architecture_id:
        return _axpy_kernel(spec)
    return _twiddle_kernel(spec)


def _reduction_tb(spec: Mapping[str, Any]) -> str:
    fn = str(spec["kernel_name"])
    n = int(spec["golden_vector_length"])
    return f"""#include <math.h>
#include <stdio.h>
extern "C" void {fn}(const double *real_in, const double *imag_in, double *real_out, double *imag_out, int n);
int main() {{
    const int n = {n};
    double real_in[n], imag_in[n], real_out[1], imag_out[1];
    double expected_re = 0.0, expected_im = 0.0;
    for (int i = 0; i < n; ++i) {{
        real_in[i] = 0.125 * (double)(i + 1);
        imag_in[i] = -0.0625 * (double)((i % 11) + 1);
        double wr = 1.0 + 0.0005 * (double)(i & 7);
        double wi = 0.00025 * (double)((i + 3) & 5);
        expected_re += real_in[i] * wr - imag_in[i] * wi;
        expected_im += real_in[i] * wi + imag_in[i] * wr;
    }}
    {fn}(real_in, imag_in, real_out, imag_out, n);
    if (fabs(real_out[0] - expected_re) > 1.0e-8 || fabs(imag_out[0] - expected_im) > 1.0e-8) {{
        printf("DSE_REAL_HLS_FAIL expected %.12f %.12f got %.12f %.12f\\n", expected_re, expected_im, real_out[0], imag_out[0]);
        return 1;
    }}
    printf("DSE_REAL_HLS_PASS {fn} %.12f %.12f\\n", real_out[0], imag_out[0]);
    return 0;
}}
"""


def _axpy_tb(spec: Mapping[str, Any]) -> str:
    fn = str(spec["kernel_name"])
    n = int(spec["golden_vector_length"])
    return f"""#include <math.h>
#include <stdio.h>
extern "C" void {fn}(const double *x_re, const double *x_im, const double *y_re, const double *y_im, double *out_re, double *out_im, int n);
int main() {{
    const int n = {n};
    double x_re[n], x_im[n], y_re[n], y_im[n], out_re[n], out_im[n];
    const double alpha_re = 0.75;
    const double alpha_im = -0.125;
    for (int i = 0; i < n; ++i) {{
        x_re[i] = 0.03125 * (double)(i + 2);
        x_im[i] = -0.015625 * (double)(i + 3);
        y_re[i] = 0.0078125 * (double)(i + 5);
        y_im[i] = -0.00390625 * (double)(i + 7);
        out_re[i] = 0.0;
        out_im[i] = 0.0;
    }}
    {fn}(x_re, x_im, y_re, y_im, out_re, out_im, n);
    for (int i = 0; i < n; ++i) {{
        double expected_re = y_re[i] + alpha_re * x_re[i] - alpha_im * x_im[i];
        double expected_im = y_im[i] + alpha_re * x_im[i] + alpha_im * x_re[i];
        if (fabs(out_re[i] - expected_re) > 1.0e-9 || fabs(out_im[i] - expected_im) > 1.0e-9) {{
            printf("DSE_REAL_HLS_FAIL %d expected %.12f %.12f got %.12f %.12f\\n", i, expected_re, expected_im, out_re[i], out_im[i]);
            return 1;
        }}
    }}
    printf("DSE_REAL_HLS_PASS {fn} %d\\n", n);
    return 0;
}}
"""


def _twiddle_tb(spec: Mapping[str, Any]) -> str:
    fn = str(spec["kernel_name"])
    n = int(spec["golden_vector_length"])
    return f"""#include <math.h>
#include <stdio.h>
extern "C" void {fn}(const double *in_re, const double *in_im, double *out_re, double *out_im, int n);
int main() {{
    const int n = {n};
    double in_re[n], in_im[n], out_re[n], out_im[n], expected_re[n], expected_im[n];
    for (int i = 0; i < n; ++i) {{
        in_re[i] = 0.02 * (double)(i + 1);
        in_im[i] = -0.01 * (double)(i + 2);
        out_re[i] = 0.0;
        out_im[i] = 0.0;
        expected_re[i] = 0.0;
        expected_im[i] = 0.0;
    }}
    for (int i = 0; i < n; ++i) {{
        int dst = (i * 17) & (n - 1);
        double angle = 0.02454369260617026 * (double)i;
        double c = cos(angle);
        double s = sin(angle);
        expected_re[dst] = in_re[i] * c - in_im[i] * s;
        expected_im[dst] = in_re[i] * s + in_im[i] * c;
    }}
    {fn}(in_re, in_im, out_re, out_im, n);
    for (int i = 0; i < n; ++i) {{
        if (fabs(out_re[i] - expected_re[i]) > 1.0e-8 || fabs(out_im[i] - expected_im[i]) > 1.0e-8) {{
            printf("DSE_REAL_HLS_FAIL %d expected %.12f %.12f got %.12f %.12f\\n", i, expected_re[i], expected_im[i], out_re[i], out_im[i]);
            return 1;
        }}
    }}
    printf("DSE_REAL_HLS_PASS {fn} %d\\n", n);
    return 0;
}}
"""


def _sum_band_density_tb(spec: Mapping[str, Any]) -> str:
    fn = str(spec["kernel_name"])
    ngrid = int(spec.get("golden_grid_points") or 32)
    nbands = int(spec.get("golden_band_count") or 4)
    n = ngrid * nbands
    return f"""#include <math.h>
#include <stdio.h>
extern "C" void {fn}(const double *psi_re, const double *psi_im, const double *weights, double *rho_out, int ngrid, int nbands);
int main() {{
    const int ngrid = {ngrid};
    const int nbands = {nbands};
    const int n = {n};
    double psi_re[n], psi_im[n], weights[nbands], rho_out[ngrid], expected[ngrid];
    for (int b = 0; b < nbands; ++b) {{
        weights[b] = 0.5 + 0.125 * (double)(b + 1);
    }}
    for (int g = 0; g < ngrid; ++g) {{
        expected[g] = 0.0;
        rho_out[g] = 0.0;
    }}
    for (int b = 0; b < nbands; ++b) {{
        for (int g = 0; g < ngrid; ++g) {{
            int idx = b * ngrid + g;
            psi_re[idx] = 0.01 * (double)(idx + 1) + 0.001 * (double)(g & 3);
            psi_im[idx] = -0.0075 * (double)(idx + 2) + 0.0005 * (double)(b & 1);
            expected[g] += weights[b] * (psi_re[idx] * psi_re[idx] + psi_im[idx] * psi_im[idx]);
        }}
    }}
    {fn}(psi_re, psi_im, weights, rho_out, ngrid, nbands);
    for (int g = 0; g < ngrid; ++g) {{
        if (fabs(rho_out[g] - expected[g]) > 1.0e-8) {{
            printf("DSE_REAL_HLS_FAIL %d expected %.12f got %.12f\\n", g, expected[g], rho_out[g]);
            return 1;
        }}
    }}
    printf("DSE_REAL_HLS_PASS {fn} %d %d\\n", ngrid, nbands);
    return 0;
}}
"""



def _hpsi_local_potential_tb(spec: Mapping[str, Any]) -> str:
    fn = str(spec["kernel_name"])
    ngrid = int(spec.get("golden_grid_points") or spec.get("golden_vector_length") or 96)
    return f"""#include <math.h>
#include <stdio.h>
extern "C" void {fn}(const double *psi_re, const double *psi_im, const double *vloc, double *out_re, double *out_im, int ngrid);
int main() {{
    const int ngrid = {ngrid};
    const double kinetic_scale = -0.5;
    double psi_re[ngrid], psi_im[ngrid], vloc[ngrid], out_re[ngrid], out_im[ngrid], expected_re[ngrid], expected_im[ngrid];
    for (int g = 0; g < ngrid; ++g) {{
        psi_re[g] = 0.0125 * (double)(g + 1) + 0.00025 * (double)(g & 7);
        psi_im[g] = -0.009 * (double)(g + 2) + 0.000125 * (double)((g + 3) & 5);
        vloc[g] = 0.2 + 0.00075 * (double)((g * 13) & 31);
        out_re[g] = 0.0;
        out_im[g] = 0.0;
    }}
    for (int g = 0; g < ngrid; ++g) {{
        int left = (g == 0) ? 0 : g - 1;
        int right = (g == ngrid - 1) ? ngrid - 1 : g + 1;
        double lap_re = psi_re[left] - 2.0 * psi_re[g] + psi_re[right];
        double lap_im = psi_im[left] - 2.0 * psi_im[g] + psi_im[right];
        expected_re[g] = kinetic_scale * lap_re + vloc[g] * psi_re[g];
        expected_im[g] = kinetic_scale * lap_im + vloc[g] * psi_im[g];
    }}
    {fn}(psi_re, psi_im, vloc, out_re, out_im, ngrid);
    for (int g = 0; g < ngrid; ++g) {{
        if (fabs(out_re[g] - expected_re[g]) > 1.0e-8 || fabs(out_im[g] - expected_im[g]) > 1.0e-8) {{
            printf("DSE_REAL_HLS_FAIL %d expected %.12f %.12f got %.12f %.12f\\n", g, expected_re[g], expected_im[g], out_re[g], out_im[g]);
            return 1;
        }}
    }}
    printf("DSE_REAL_HLS_PASS {fn} %d\\n", ngrid);
    return 0;
}}
"""

def _tb_source(spec: Mapping[str, Any]) -> str:
    architecture_id = str(spec["architecture_id"])
    if "sum_band" in architecture_id:
        return _sum_band_density_tb(spec)
    if "hpsi" in architecture_id:
        return _hpsi_local_potential_tb(spec)
    if "reduction" in architecture_id:
        return _reduction_tb(spec)
    if "axpy" in architecture_id:
        return _axpy_tb(spec)
    return _twiddle_tb(spec)


def _hls_tcl(spec: Mapping[str, Any], fpga_part: str) -> str:
    kernel = str(spec["kernel_name"])
    return f"""open_project -reset real_hybrid_hls
set_top {kernel}
add_files kernel.cpp
add_files -tb tb.cpp
open_solution -reset sol1
set_part {{{fpga_part}}}
create_clock -period 10 -name default
csim_design
csynth_design
cosim_design -trace_level none
exit
"""


def materialize_hls_project(spec: Mapping[str, Any], out_dir: Path, *, fpga_part: str = DEFAULT_FPGA_PART) -> dict[str, Any]:
    """Materialize a real HLS kernel project for a hybrid architecture spec."""

    architecture_id = str(spec["architecture_id"])
    project_dir = out_dir / _safe_name(architecture_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    kernel_cpp = project_dir / "kernel.cpp"
    tb_cpp = project_dir / "tb.cpp"
    run_hls_tcl = project_dir / "run_hls.tcl"
    kernel_source = _kernel_source(spec)
    tb_source = _tb_source(spec)
    tcl_source = _hls_tcl(spec, fpga_part)
    kernel_cpp.write_text(kernel_source, encoding="utf-8")
    tb_cpp.write_text(tb_source, encoding="utf-8")
    run_hls_tcl.write_text(tcl_source, encoding="utf-8")
    return {
        "architecture_id": architecture_id,
        "project_dir": str(project_dir),
        "kernel_cpp": str(kernel_cpp),
        "tb_cpp": str(tb_cpp),
        "run_hls_tcl": str(run_hls_tcl),
        "kernel_hash": _sha256_text(kernel_source),
        "testbench_hash": _sha256_text(tb_source),
        "tcl_hash": _sha256_text(tcl_source),
    }


def _hpsi_vcs_rtl_source() -> str:
    return r"""module qeic_real_hpsi_local_potential_rtl #(
    parameter integer N = 96,
    parameter integer WIDTH = 18,
    parameter integer ACC_WIDTH = 40
) (
    input  wire clk,
    input  wire reset_n,
    input  wire start,
    input  wire sample_valid,
    input  wire signed [WIDTH-1:0] psi_re_left,
    input  wire signed [WIDTH-1:0] psi_re_center,
    input  wire signed [WIDTH-1:0] psi_re_right,
    input  wire signed [WIDTH-1:0] psi_im_left,
    input  wire signed [WIDTH-1:0] psi_im_center,
    input  wire signed [WIDTH-1:0] psi_im_right,
    input  wire signed [WIDTH-1:0] vloc_center,
    output wire signed [ACC_WIDTH-1:0] out_re,
    output wire signed [ACC_WIDTH-1:0] out_im,
    output wire valid,
    output reg  done
);
    reg active;
    integer sample_count;
    wire signed [ACC_WIDTH-1:0] lap_re =
        {{(ACC_WIDTH-WIDTH){psi_re_left[WIDTH-1]}}, psi_re_left}
        - ({{(ACC_WIDTH-WIDTH){psi_re_center[WIDTH-1]}}, psi_re_center} <<< 1)
        + {{(ACC_WIDTH-WIDTH){psi_re_right[WIDTH-1]}}, psi_re_right};
    wire signed [ACC_WIDTH-1:0] lap_im =
        {{(ACC_WIDTH-WIDTH){psi_im_left[WIDTH-1]}}, psi_im_left}
        - ({{(ACC_WIDTH-WIDTH){psi_im_center[WIDTH-1]}}, psi_im_center} <<< 1)
        + {{(ACC_WIDTH-WIDTH){psi_im_right[WIDTH-1]}}, psi_im_right};
    wire signed [(2*WIDTH)-1:0] pot_re = vloc_center * psi_re_center;
    wire signed [(2*WIDTH)-1:0] pot_im = vloc_center * psi_im_center;
    wire signed [ACC_WIDTH-1:0] pot_re_ext = {{(ACC_WIDTH-(2*WIDTH)){pot_re[(2*WIDTH)-1]}}, pot_re};
    wire signed [ACC_WIDTH-1:0] pot_im_ext = {{(ACC_WIDTH-(2*WIDTH)){pot_im[(2*WIDTH)-1]}}, pot_im};

    assign out_re = -(lap_re >>> 1) + (pot_re_ext >>> 8);
    assign out_im = -(lap_im >>> 1) + (pot_im_ext >>> 8);
    assign valid = sample_valid;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            active <= 1'b0;
            sample_count <= 0;
            done <= 1'b0;
        end else begin
            if (start) begin
                active <= 1'b1;
                sample_count <= 0;
                done <= 1'b0;
            end else if (active && sample_valid) begin
                if (sample_count == N - 1) begin
                    active <= 1'b0;
                    done <= 1'b1;
                end
                sample_count <= sample_count + 1;
            end
        end
    end
endmodule
"""


def _hpsi_vcs_tb_source(samples: int) -> str:
    return f"""module tb_qeic_real_hpsi_local_potential_rtl;
    localparam integer N = {samples};
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 40;
    reg clk;
    reg reset_n;
    reg start;
    reg sample_valid;
    reg signed [WIDTH-1:0] psi_re [0:N-1];
    reg signed [WIDTH-1:0] psi_im [0:N-1];
    reg signed [WIDTH-1:0] vloc [0:N-1];
    reg signed [WIDTH-1:0] psi_re_left;
    reg signed [WIDTH-1:0] psi_re_center;
    reg signed [WIDTH-1:0] psi_re_right;
    reg signed [WIDTH-1:0] psi_im_left;
    reg signed [WIDTH-1:0] psi_im_center;
    reg signed [WIDTH-1:0] psi_im_right;
    reg signed [WIDTH-1:0] vloc_center;
    wire signed [ACC_WIDTH-1:0] out_re;
    wire signed [ACC_WIDTH-1:0] out_im;
    wire valid;
    wire done;
    reg signed [ACC_WIDTH-1:0] expected_re [0:N-1];
    reg signed [ACC_WIDTH-1:0] expected_im [0:N-1];
    integer g;
    integer left;
    integer right;
    integer valid_count;
    integer latency_cycles;
    reg signed [ACC_WIDTH-1:0] lap_re;
    reg signed [ACC_WIDTH-1:0] lap_im;

    qeic_real_hpsi_local_potential_rtl #(.N(N), .WIDTH(WIDTH), .ACC_WIDTH(ACC_WIDTH)) dut (
        .clk(clk),
        .reset_n(reset_n),
        .start(start),
        .sample_valid(sample_valid),
        .psi_re_left(psi_re_left),
        .psi_re_center(psi_re_center),
        .psi_re_right(psi_re_right),
        .psi_im_left(psi_im_left),
        .psi_im_center(psi_im_center),
        .psi_im_right(psi_im_right),
        .vloc_center(vloc_center),
        .out_re(out_re),
        .out_im(out_im),
        .valid(valid),
        .done(done)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        reset_n = 1'b0;
        start = 1'b0;
        sample_valid = 1'b0;
        psi_re_left = 0;
        psi_re_center = 0;
        psi_re_right = 0;
        psi_im_left = 0;
        psi_im_center = 0;
        psi_im_right = 0;
        vloc_center = 0;
        valid_count = 0;
        latency_cycles = 0;
        for (g = 0; g < N; g = g + 1) begin
            psi_re[g] = 18'sd64 + g * 18'sd3;
            psi_im[g] = -18'sd51 - g * 18'sd2;
            vloc[g] = 18'sd128 + ((g * 17) & 31);
        end
        for (g = 0; g < N; g = g + 1) begin
            left = (g == 0) ? 0 : g - 1;
            right = (g == N - 1) ? N - 1 : g + 1;
            lap_re = psi_re[left] - (psi_re[g] <<< 1) + psi_re[right];
            lap_im = psi_im[left] - (psi_im[g] <<< 1) + psi_im[right];
            expected_re[g] = -(lap_re >>> 1) + ((vloc[g] * psi_re[g]) >>> 8);
            expected_im[g] = -(lap_im >>> 1) + ((vloc[g] * psi_im[g]) >>> 8);
        end
        repeat (3) @(posedge clk);
        reset_n = 1'b1;
        @(posedge clk);
        start = 1'b1;
        @(posedge clk);
        start = 1'b0;
        for (g = 0; g < N; g = g + 1) begin
            left = (g == 0) ? 0 : g - 1;
            right = (g == N - 1) ? N - 1 : g + 1;
            psi_re_left = psi_re[left];
            psi_re_center = psi_re[g];
            psi_re_right = psi_re[right];
            psi_im_left = psi_im[left];
            psi_im_center = psi_im[g];
            psi_im_right = psi_im[right];
            vloc_center = vloc[g];
            sample_valid = 1'b1;
            @(posedge clk);
            #1;
            latency_cycles = latency_cycles + 1;
            if (valid !== 1'b1 || out_re !== expected_re[g] || out_im !== expected_im[g]) begin
                $display("DSE_REAL_RTL_FAIL sample=%0d expected=%0d,%0d got=%0d,%0d valid=%0d", g, expected_re[g], expected_im[g], out_re, out_im, valid);
                $finish(1);
            end
            valid_count = valid_count + 1;
        end
        sample_valid = 1'b0;
        #1;
        if (done !== 1'b1 || valid_count != N) begin
            $display("DSE_REAL_RTL_FAIL done=%0d valid_count=%0d", done, valid_count);
            $finish(1);
        end
        $display("DSE_REAL_RTL_PASS qeic_real_hpsi_local_potential_rtl samples=%0d", valid_count);
        $display("DSE_REAL_RTL_LATENCY_CYCLES %0d", latency_cycles);
        $finish(0);
    end
endmodule
"""


def _sum_band_vcs_rtl_source() -> str:
    return r"""module qeic_real_sum_band_density_accumulator_rtl #(
    parameter integer SAMPLES = 128,
    parameter integer WIDTH = 18,
    parameter integer ACC_WIDTH = 48
) (
    input  wire clk,
    input  wire reset_n,
    input  wire start,
    input  wire sample_valid,
    input  wire band_first,
    input  wire band_last,
    input  wire signed [WIDTH-1:0] psi_re,
    input  wire signed [WIDTH-1:0] psi_im,
    input  wire signed [WIDTH-1:0] weight,
    output reg  signed [ACC_WIDTH-1:0] rho_out,
    output reg  valid,
    output reg  done
);
    reg active;
    integer sample_count;
    reg signed [ACC_WIDTH-1:0] rho_acc;
    wire signed [(2*WIDTH)-1:0] re_sq = psi_re * psi_re;
    wire signed [(2*WIDTH)-1:0] im_sq = psi_im * psi_im;
    wire signed [ACC_WIDTH-1:0] abs_sq = {{(ACC_WIDTH-(2*WIDTH)){1'b0}}, re_sq + im_sq};
    wire signed [(ACC_WIDTH+WIDTH)-1:0] weighted_wide = abs_sq * weight;
    wire signed [ACC_WIDTH-1:0] contribution = weighted_wide[ACC_WIDTH+WIDTH-1:WIDTH];
    wire signed [ACC_WIDTH-1:0] rho_acc_next = band_first ? contribution : (rho_acc + contribution);

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            active <= 1'b0;
            sample_count <= 0;
            rho_acc <= 0;
            rho_out <= 0;
            valid <= 1'b0;
            done <= 1'b0;
        end else begin
            valid <= 1'b0;
            if (start) begin
                active <= 1'b1;
                sample_count <= 0;
                rho_acc <= 0;
                rho_out <= 0;
                done <= 1'b0;
            end else if (active && sample_valid) begin
                rho_acc <= rho_acc_next;
                rho_out <= rho_acc_next;
                valid <= band_last;
                if (sample_count == SAMPLES - 1) begin
                    active <= 1'b0;
                    done <= 1'b1;
                end
                sample_count <= sample_count + 1;
            end
        end
    end
endmodule
"""


def _sum_band_vcs_tb_source(ngrid: int, nbands: int) -> str:
    samples = ngrid * nbands
    return f"""module tb_qeic_real_sum_band_density_accumulator_rtl;
    localparam integer NGRID = {ngrid};
    localparam integer NBANDS = {nbands};
    localparam integer SAMPLES = {samples};
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 48;
    reg clk;
    reg reset_n;
    reg start;
    reg sample_valid;
    reg band_first;
    reg band_last;
    reg signed [WIDTH-1:0] psi_re [0:SAMPLES-1];
    reg signed [WIDTH-1:0] psi_im [0:SAMPLES-1];
    reg signed [WIDTH-1:0] weight [0:NBANDS-1];
    reg signed [WIDTH-1:0] psi_re_in;
    reg signed [WIDTH-1:0] psi_im_in;
    reg signed [WIDTH-1:0] weight_in;
    wire signed [ACC_WIDTH-1:0] rho_out;
    wire valid;
    wire done;
    reg signed [ACC_WIDTH-1:0] expected_rho [0:NGRID-1];
    reg signed [ACC_WIDTH-1:0] acc;
    reg signed [(2*WIDTH)-1:0] re_sq;
    reg signed [(2*WIDTH)-1:0] im_sq;
    reg signed [ACC_WIDTH-1:0] abs_sq;
    integer g;
    integer b;
    integer idx;
    integer valid_count;
    integer latency_cycles;

    qeic_real_sum_band_density_accumulator_rtl #(.SAMPLES(SAMPLES), .WIDTH(WIDTH), .ACC_WIDTH(ACC_WIDTH)) dut (
        .clk(clk),
        .reset_n(reset_n),
        .start(start),
        .sample_valid(sample_valid),
        .band_first(band_first),
        .band_last(band_last),
        .psi_re(psi_re_in),
        .psi_im(psi_im_in),
        .weight(weight_in),
        .rho_out(rho_out),
        .valid(valid),
        .done(done)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        reset_n = 1'b0;
        start = 1'b0;
        sample_valid = 1'b0;
        band_first = 1'b0;
        band_last = 1'b0;
        psi_re_in = 0;
        psi_im_in = 0;
        weight_in = 0;
        valid_count = 0;
        latency_cycles = 0;
        for (b = 0; b < NBANDS; b = b + 1) begin
            weight[b] = 18'sd64 + b * 18'sd11;
        end
        for (g = 0; g < NGRID; g = g + 1) begin
            expected_rho[g] = 0;
        end
        for (b = 0; b < NBANDS; b = b + 1) begin
            for (g = 0; g < NGRID; g = g + 1) begin
                idx = b * NGRID + g;
                psi_re[idx] = 18'sd32 + idx * 18'sd2 + (g & 3);
                psi_im[idx] = -18'sd21 - idx;
            end
        end
        for (g = 0; g < NGRID; g = g + 1) begin
            acc = 0;
            for (b = 0; b < NBANDS; b = b + 1) begin
                idx = b * NGRID + g;
                re_sq = psi_re[idx] * psi_re[idx];
                im_sq = psi_im[idx] * psi_im[idx];
                abs_sq = re_sq + im_sq;
                acc = acc + ((abs_sq * weight[b]) >>> WIDTH);
            end
            expected_rho[g] = acc;
        end
        repeat (3) @(posedge clk);
        reset_n = 1'b1;
        @(posedge clk);
        start = 1'b1;
        @(posedge clk);
        start = 1'b0;
        for (g = 0; g < NGRID; g = g + 1) begin
            for (b = 0; b < NBANDS; b = b + 1) begin
                @(negedge clk);
                idx = b * NGRID + g;
                psi_re_in = psi_re[idx];
                psi_im_in = psi_im[idx];
                weight_in = weight[b];
                band_first = (b == 0);
                band_last = (b == NBANDS - 1);
                sample_valid = 1'b1;
                @(posedge clk);
                #1;
                latency_cycles = latency_cycles + 1;
                if (band_last) begin
                    if (valid !== 1'b1 || rho_out !== expected_rho[g]) begin
                        $display("DSE_REAL_RTL_FAIL grid=%0d expected=%0d got=%0d valid=%0d", g, expected_rho[g], rho_out, valid);
                        $finish(1);
                    end
                    valid_count = valid_count + 1;
                end
            end
        end
        @(negedge clk);
        sample_valid = 1'b0;
        band_first = 1'b0;
        band_last = 1'b0;
        #1;
        if (done !== 1'b1 || valid_count != NGRID) begin
            $display("DSE_REAL_RTL_FAIL done=%0d valid_count=%0d", done, valid_count);
            $finish(1);
        end
        $display("DSE_REAL_RTL_PASS qeic_real_sum_band_density_accumulator_rtl samples=%0d", SAMPLES);
        $display("DSE_REAL_RTL_LATENCY_CYCLES %0d", latency_cycles);
        $finish(0);
    end
endmodule
"""


def _axpy_vcs_rtl_source() -> str:
    return r"""module qeic_real_tiled_complex_axpy_rtl #(
    parameter integer N = 64,
    parameter integer WIDTH = 18,
    parameter integer ACC_WIDTH = 48,
    parameter signed [WIDTH-1:0] ALPHA_RE = 18'sd192,
    parameter signed [WIDTH-1:0] ALPHA_IM = -18'sd32
) (
    input  wire clk,
    input  wire reset_n,
    input  wire start,
    input  wire sample_valid,
    input  wire signed [WIDTH-1:0] x_re,
    input  wire signed [WIDTH-1:0] x_im,
    input  wire signed [WIDTH-1:0] y_re,
    input  wire signed [WIDTH-1:0] y_im,
    output reg  signed [ACC_WIDTH-1:0] out_re,
    output reg  signed [ACC_WIDTH-1:0] out_im,
    output reg  valid,
    output reg  done
);
    reg active;
    integer sample_count;
    wire signed [WIDTH-1:0] alpha_re = ALPHA_RE;
    wire signed [WIDTH-1:0] alpha_im = ALPHA_IM;
    wire signed [(2*WIDTH)-1:0] ar_xr = alpha_re * x_re;
    wire signed [(2*WIDTH)-1:0] ai_xi = alpha_im * x_im;
    wire signed [(2*WIDTH)-1:0] ar_xi = alpha_re * x_im;
    wire signed [(2*WIDTH)-1:0] ai_xr = alpha_im * x_re;
    wire signed [ACC_WIDTH-1:0] y_re_ext = {{(ACC_WIDTH-WIDTH){y_re[WIDTH-1]}}, y_re} <<< 8;
    wire signed [ACC_WIDTH-1:0] y_im_ext = {{(ACC_WIDTH-WIDTH){y_im[WIDTH-1]}}, y_im} <<< 8;
    wire signed [ACC_WIDTH-1:0] alpha_x_re = ar_xr - ai_xi;
    wire signed [ACC_WIDTH-1:0] alpha_x_im = ar_xi + ai_xr;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            active <= 1'b0;
            sample_count <= 0;
            out_re <= 0;
            out_im <= 0;
            valid <= 1'b0;
            done <= 1'b0;
        end else begin
            valid <= 1'b0;
            if (start) begin
                active <= 1'b1;
                sample_count <= 0;
                out_re <= 0;
                out_im <= 0;
                done <= 1'b0;
            end else if (active && sample_valid) begin
                out_re <= y_re_ext + alpha_x_re;
                out_im <= y_im_ext + alpha_x_im;
                valid <= 1'b1;
                if (sample_count == N - 1) begin
                    active <= 1'b0;
                    done <= 1'b1;
                end
                sample_count <= sample_count + 1;
            end
        end
    end
endmodule
"""


def _axpy_vcs_tb_source(samples: int) -> str:
    return f"""module tb_qeic_real_tiled_complex_axpy_rtl;
    localparam integer N = {samples};
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 48;
    localparam signed [WIDTH-1:0] ALPHA_RE = 18'sd192;
    localparam signed [WIDTH-1:0] ALPHA_IM = -18'sd32;
    reg clk;
    reg reset_n;
    reg start;
    reg sample_valid;
    reg signed [WIDTH-1:0] x_re_mem [0:N-1];
    reg signed [WIDTH-1:0] x_im_mem [0:N-1];
    reg signed [WIDTH-1:0] y_re_mem [0:N-1];
    reg signed [WIDTH-1:0] y_im_mem [0:N-1];
    reg signed [WIDTH-1:0] x_re;
    reg signed [WIDTH-1:0] x_im;
    reg signed [WIDTH-1:0] y_re;
    reg signed [WIDTH-1:0] y_im;
    wire signed [ACC_WIDTH-1:0] out_re;
    wire signed [ACC_WIDTH-1:0] out_im;
    wire valid;
    wire done;
    reg signed [ACC_WIDTH-1:0] expected_re [0:N-1];
    reg signed [ACC_WIDTH-1:0] expected_im [0:N-1];
    integer i;
    integer valid_count;
    integer latency_cycles;

    qeic_real_tiled_complex_axpy_rtl #(.N(N), .WIDTH(WIDTH), .ACC_WIDTH(ACC_WIDTH), .ALPHA_RE(ALPHA_RE), .ALPHA_IM(ALPHA_IM)) dut (
        .clk(clk),
        .reset_n(reset_n),
        .start(start),
        .sample_valid(sample_valid),
        .x_re(x_re),
        .x_im(x_im),
        .y_re(y_re),
        .y_im(y_im),
        .out_re(out_re),
        .out_im(out_im),
        .valid(valid),
        .done(done)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        reset_n = 1'b0;
        start = 1'b0;
        sample_valid = 1'b0;
        x_re = 0;
        x_im = 0;
        y_re = 0;
        y_im = 0;
        valid_count = 0;
        latency_cycles = 0;
        for (i = 0; i < N; i = i + 1) begin
            x_re_mem[i] = 18'sd16 + i * 18'sd3;
            x_im_mem[i] = -18'sd11 - i * 18'sd2;
            y_re_mem[i] = 18'sd7 + (i & 7);
            y_im_mem[i] = -18'sd5 - (i & 5);
            expected_re[i] = (y_re_mem[i] <<< 8) + (ALPHA_RE * x_re_mem[i]) - (ALPHA_IM * x_im_mem[i]);
            expected_im[i] = (y_im_mem[i] <<< 8) + (ALPHA_RE * x_im_mem[i]) + (ALPHA_IM * x_re_mem[i]);
        end
        repeat (3) @(posedge clk);
        reset_n = 1'b1;
        @(posedge clk);
        start = 1'b1;
        @(posedge clk);
        start = 1'b0;
        for (i = 0; i < N; i = i + 1) begin
            @(negedge clk);
            x_re = x_re_mem[i];
            x_im = x_im_mem[i];
            y_re = y_re_mem[i];
            y_im = y_im_mem[i];
            sample_valid = 1'b1;
            @(posedge clk);
            #1;
            latency_cycles = latency_cycles + 1;
            if (valid !== 1'b1 || out_re !== expected_re[i] || out_im !== expected_im[i]) begin
                $display("DSE_REAL_RTL_FAIL sample=%0d expected=%0d,%0d got=%0d,%0d valid=%0d", i, expected_re[i], expected_im[i], out_re, out_im, valid);
                $finish(1);
            end
            valid_count = valid_count + 1;
        end
        @(negedge clk);
        sample_valid = 1'b0;
        #1;
        if (done !== 1'b1 || valid_count != N) begin
            $display("DSE_REAL_RTL_FAIL done=%0d valid_count=%0d", done, valid_count);
            $finish(1);
        end
        $display("DSE_REAL_RTL_PASS qeic_real_tiled_complex_axpy_rtl samples=%0d", valid_count);
        $display("DSE_REAL_RTL_LATENCY_CYCLES %0d", latency_cycles);
        $finish(0);
    end
endmodule
"""


_INTEGRATED_SIDECAR_ID = "hybrid_integrated_combined_sidecar_v1"
_INTEGRATED_SIDECAR_KERNEL = "qeic_real_integrated_combined_sidecar_rtl"
_PIPELINED_SIDECAR_ID = "hybrid_integrated_pipelined_sidecar_v2"
_PIPELINED_SIDECAR_KERNEL = "qeic_real_integrated_pipelined_sidecar_rtl"
_PIPELINED_SIDECAR_PIPELINE_LATENCY = 4
_STREAMING_SIDECAR_ID = "hybrid_integrated_streaming_pipeline_sidecar_v3"
_STREAMING_SIDECAR_KERNEL = "qeic_real_integrated_streaming_pipeline_sidecar_rtl"
_STREAMING_SIDECAR_PIPELINE_LATENCY = 4
_INTEGRATED_VIVADO_RESULT_KEYS = {
    _INTEGRATED_SIDECAR_ID: "integrated_vivado_impl_result",
    _PIPELINED_SIDECAR_ID: "integrated_pipelined_vivado_impl_result",
    _STREAMING_SIDECAR_ID: "integrated_streaming_vivado_impl_result",
}
_INTEGRATED_COMPONENT_TIMER_MAP: dict[str, list[str]] = {
    "hpsi": ["h_psi"],
    "sum_band": ["sum_band"],
    "axpy": ["mix_rho", "h_psi:calbec", "calbec"],
}


def _integrated_vcs_rtl_source() -> str:
    return r"""module qeic_real_integrated_combined_sidecar_rtl #(
    parameter integer TOTAL_SAMPLES = 288,
    parameter integer WIDTH = 18,
    parameter integer ACC_WIDTH = 48,
    parameter signed [WIDTH-1:0] ALPHA_RE = 18'sd192,
    parameter signed [WIDTH-1:0] ALPHA_IM = -18'sd32
) (
    input  wire clk,
    input  wire reset_n,
    input  wire start,
    input  wire sample_valid,
    input  wire [1:0] mode,
    input  wire band_first,
    input  wire band_last,
    input  wire signed [WIDTH-1:0] a_re,
    input  wire signed [WIDTH-1:0] a_im,
    input  wire signed [WIDTH-1:0] b_re,
    input  wire signed [WIDTH-1:0] b_im,
    input  wire signed [WIDTH-1:0] c_re,
    input  wire signed [WIDTH-1:0] c_im,
    input  wire signed [WIDTH-1:0] weight,
    input  wire signed [WIDTH-1:0] y_re,
    input  wire signed [WIDTH-1:0] y_im,
    output reg  signed [ACC_WIDTH-1:0] out_re,
    output reg  signed [ACC_WIDTH-1:0] out_im,
    output reg  signed [ACC_WIDTH-1:0] rho_out,
    output reg  valid,
    output reg  done
);
    localparam [1:0] MODE_HPSI = 2'd0;
    localparam [1:0] MODE_SUM_BAND = 2'd1;
    localparam [1:0] MODE_AXPY = 2'd2;

    reg active;
    integer sample_count;
    reg signed [ACC_WIDTH-1:0] rho_acc;

    wire signed [ACC_WIDTH-1:0] lap_re = {{(ACC_WIDTH-WIDTH){a_re[WIDTH-1]}}, a_re}
        - ({{(ACC_WIDTH-WIDTH){b_re[WIDTH-1]}}, b_re} <<< 1)
        + {{(ACC_WIDTH-WIDTH){c_re[WIDTH-1]}}, c_re};
    wire signed [ACC_WIDTH-1:0] lap_im = {{(ACC_WIDTH-WIDTH){a_im[WIDTH-1]}}, a_im}
        - ({{(ACC_WIDTH-WIDTH){b_im[WIDTH-1]}}, b_im} <<< 1)
        + {{(ACC_WIDTH-WIDTH){c_im[WIDTH-1]}}, c_im};
    wire signed [(2*WIDTH)-1:0] vloc_re = weight * b_re;
    wire signed [(2*WIDTH)-1:0] vloc_im = weight * b_im;
    wire signed [ACC_WIDTH-1:0] hpsi_re = -(lap_re >>> 1) + (vloc_re >>> 8);
    wire signed [ACC_WIDTH-1:0] hpsi_im = -(lap_im >>> 1) + (vloc_im >>> 8);

    wire signed [(2*WIDTH)-1:0] sb_re_sq = b_re * b_re;
    wire signed [(2*WIDTH)-1:0] sb_im_sq = b_im * b_im;
    wire signed [ACC_WIDTH-1:0] sb_abs_sq = {{(ACC_WIDTH-(2*WIDTH)){1'b0}}, sb_re_sq + sb_im_sq};
    wire signed [(ACC_WIDTH+WIDTH)-1:0] sb_weighted = sb_abs_sq * weight;
    wire signed [ACC_WIDTH-1:0] sb_contribution = sb_weighted[ACC_WIDTH+WIDTH-1:WIDTH];
    wire signed [ACC_WIDTH-1:0] rho_acc_next = band_first ? sb_contribution : (rho_acc + sb_contribution);

    wire signed [(2*WIDTH)-1:0] ar_xr = ALPHA_RE * a_re;
    wire signed [(2*WIDTH)-1:0] ai_xi = ALPHA_IM * a_im;
    wire signed [(2*WIDTH)-1:0] ar_xi = ALPHA_RE * a_im;
    wire signed [(2*WIDTH)-1:0] ai_xr = ALPHA_IM * a_re;
    wire signed [ACC_WIDTH-1:0] y_re_ext = {{(ACC_WIDTH-WIDTH){y_re[WIDTH-1]}}, y_re} <<< 8;
    wire signed [ACC_WIDTH-1:0] y_im_ext = {{(ACC_WIDTH-WIDTH){y_im[WIDTH-1]}}, y_im} <<< 8;
    wire signed [ACC_WIDTH-1:0] alpha_x_re = ar_xr - ai_xi;
    wire signed [ACC_WIDTH-1:0] alpha_x_im = ar_xi + ai_xr;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            active <= 1'b0;
            sample_count <= 0;
            rho_acc <= 0;
            out_re <= 0;
            out_im <= 0;
            rho_out <= 0;
            valid <= 1'b0;
            done <= 1'b0;
        end else begin
            valid <= 1'b0;
            if (start) begin
                active <= 1'b1;
                sample_count <= 0;
                rho_acc <= 0;
                out_re <= 0;
                out_im <= 0;
                rho_out <= 0;
                done <= 1'b0;
            end else if (active && sample_valid) begin
                case (mode)
                    MODE_HPSI: begin
                        out_re <= hpsi_re;
                        out_im <= hpsi_im;
                        valid <= 1'b1;
                    end
                    MODE_SUM_BAND: begin
                        rho_acc <= rho_acc_next;
                        rho_out <= rho_acc_next;
                        valid <= band_last;
                    end
                    MODE_AXPY: begin
                        out_re <= y_re_ext + alpha_x_re;
                        out_im <= y_im_ext + alpha_x_im;
                        valid <= 1'b1;
                    end
                    default: begin
                        out_re <= 0;
                        out_im <= 0;
                        rho_out <= 0;
                        valid <= 1'b0;
                    end
                endcase
                if (sample_count == TOTAL_SAMPLES - 1) begin
                    active <= 1'b0;
                    done <= 1'b1;
                end
                sample_count <= sample_count + 1;
            end
        end
    end
endmodule
"""


def _integrated_vcs_tb_source(*, hpsi_samples: int, sum_band_grid_points: int, sum_band_bands: int, axpy_samples: int) -> str:
    sum_band_samples = sum_band_grid_points * sum_band_bands
    total_samples = hpsi_samples + sum_band_samples + axpy_samples
    return f"""module tb_qeic_real_integrated_combined_sidecar_rtl;
    localparam integer HPSI_N = {hpsi_samples};
    localparam integer SUM_GRID = {sum_band_grid_points};
    localparam integer SUM_BANDS = {sum_band_bands};
    localparam integer SUM_SAMPLES = {sum_band_samples};
    localparam integer AXPY_N = {axpy_samples};
    localparam integer TOTAL_SAMPLES = {total_samples};
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 48;
    localparam [1:0] MODE_HPSI = 2'd0;
    localparam [1:0] MODE_SUM_BAND = 2'd1;
    localparam [1:0] MODE_AXPY = 2'd2;
    localparam signed [WIDTH-1:0] ALPHA_RE = 18'sd192;
    localparam signed [WIDTH-1:0] ALPHA_IM = -18'sd32;
    reg clk;
    reg reset_n;
    reg start;
    reg sample_valid;
    reg [1:0] mode;
    reg band_first;
    reg band_last;
    reg signed [WIDTH-1:0] a_re;
    reg signed [WIDTH-1:0] a_im;
    reg signed [WIDTH-1:0] b_re;
    reg signed [WIDTH-1:0] b_im;
    reg signed [WIDTH-1:0] c_re;
    reg signed [WIDTH-1:0] c_im;
    reg signed [WIDTH-1:0] weight;
    reg signed [WIDTH-1:0] y_re;
    reg signed [WIDTH-1:0] y_im;
    wire signed [ACC_WIDTH-1:0] out_re;
    wire signed [ACC_WIDTH-1:0] out_im;
    wire signed [ACC_WIDTH-1:0] rho_out;
    wire valid;
    wire done;

    reg signed [WIDTH-1:0] hpsi_re [0:HPSI_N-1];
    reg signed [WIDTH-1:0] hpsi_im [0:HPSI_N-1];
    reg signed [WIDTH-1:0] hpsi_vloc [0:HPSI_N-1];
    reg signed [ACC_WIDTH-1:0] hpsi_expected_re [0:HPSI_N-1];
    reg signed [ACC_WIDTH-1:0] hpsi_expected_im [0:HPSI_N-1];
    reg signed [WIDTH-1:0] sum_re [0:SUM_SAMPLES-1];
    reg signed [WIDTH-1:0] sum_im [0:SUM_SAMPLES-1];
    reg signed [WIDTH-1:0] sum_weight [0:SUM_BANDS-1];
    reg signed [ACC_WIDTH-1:0] sum_expected [0:SUM_GRID-1];
    reg signed [WIDTH-1:0] axpy_x_re [0:AXPY_N-1];
    reg signed [WIDTH-1:0] axpy_x_im [0:AXPY_N-1];
    reg signed [WIDTH-1:0] axpy_y_re [0:AXPY_N-1];
    reg signed [WIDTH-1:0] axpy_y_im [0:AXPY_N-1];
    reg signed [ACC_WIDTH-1:0] axpy_expected_re [0:AXPY_N-1];
    reg signed [ACC_WIDTH-1:0] axpy_expected_im [0:AXPY_N-1];
    reg signed [ACC_WIDTH-1:0] lap_re;
    reg signed [ACC_WIDTH-1:0] lap_im;
    reg signed [ACC_WIDTH-1:0] acc;
    reg signed [(2*WIDTH)-1:0] re_sq;
    reg signed [(2*WIDTH)-1:0] im_sq;
    reg signed [ACC_WIDTH-1:0] abs_sq;
    integer i;
    integer g;
    integer b;
    integer left;
    integer right;
    integer idx;
    integer latency_cycles;
    integer hpsi_cycles;
    integer sum_band_cycles;
    integer axpy_cycles;

    qeic_real_integrated_combined_sidecar_rtl #(
        .TOTAL_SAMPLES(TOTAL_SAMPLES),
        .WIDTH(WIDTH),
        .ACC_WIDTH(ACC_WIDTH),
        .ALPHA_RE(ALPHA_RE),
        .ALPHA_IM(ALPHA_IM)
    ) dut (
        .clk(clk),
        .reset_n(reset_n),
        .start(start),
        .sample_valid(sample_valid),
        .mode(mode),
        .band_first(band_first),
        .band_last(band_last),
        .a_re(a_re),
        .a_im(a_im),
        .b_re(b_re),
        .b_im(b_im),
        .c_re(c_re),
        .c_im(c_im),
        .weight(weight),
        .y_re(y_re),
        .y_im(y_im),
        .out_re(out_re),
        .out_im(out_im),
        .rho_out(rho_out),
        .valid(valid),
        .done(done)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        reset_n = 1'b0;
        start = 1'b0;
        sample_valid = 1'b0;
        mode = MODE_HPSI;
        band_first = 1'b0;
        band_last = 1'b0;
        a_re = 0;
        a_im = 0;
        b_re = 0;
        b_im = 0;
        c_re = 0;
        c_im = 0;
        weight = 0;
        y_re = 0;
        y_im = 0;
        latency_cycles = 0;
        hpsi_cycles = 0;
        sum_band_cycles = 0;
        axpy_cycles = 0;

        for (g = 0; g < HPSI_N; g = g + 1) begin
            hpsi_re[g] = 18'sd64 + g * 18'sd3;
            hpsi_im[g] = -18'sd51 - g * 18'sd2;
            hpsi_vloc[g] = 18'sd128 + ((g * 17) & 31);
        end
        for (g = 0; g < HPSI_N; g = g + 1) begin
            left = (g == 0) ? 0 : g - 1;
            right = (g == HPSI_N - 1) ? HPSI_N - 1 : g + 1;
            lap_re = hpsi_re[left] - (hpsi_re[g] <<< 1) + hpsi_re[right];
            lap_im = hpsi_im[left] - (hpsi_im[g] <<< 1) + hpsi_im[right];
            hpsi_expected_re[g] = -(lap_re >>> 1) + ((hpsi_vloc[g] * hpsi_re[g]) >>> 8);
            hpsi_expected_im[g] = -(lap_im >>> 1) + ((hpsi_vloc[g] * hpsi_im[g]) >>> 8);
        end
        for (b = 0; b < SUM_BANDS; b = b + 1) begin
            sum_weight[b] = 18'sd64 + b * 18'sd11;
        end
        for (g = 0; g < SUM_GRID; g = g + 1) begin
            sum_expected[g] = 0;
        end
        for (b = 0; b < SUM_BANDS; b = b + 1) begin
            for (g = 0; g < SUM_GRID; g = g + 1) begin
                idx = b * SUM_GRID + g;
                sum_re[idx] = 18'sd32 + idx * 18'sd2 + (g & 3);
                sum_im[idx] = -18'sd21 - idx;
            end
        end
        for (g = 0; g < SUM_GRID; g = g + 1) begin
            acc = 0;
            for (b = 0; b < SUM_BANDS; b = b + 1) begin
                idx = b * SUM_GRID + g;
                re_sq = sum_re[idx] * sum_re[idx];
                im_sq = sum_im[idx] * sum_im[idx];
                abs_sq = re_sq + im_sq;
                acc = acc + ((abs_sq * sum_weight[b]) >>> WIDTH);
            end
            sum_expected[g] = acc;
        end
        for (i = 0; i < AXPY_N; i = i + 1) begin
            axpy_x_re[i] = 18'sd16 + i * 18'sd3;
            axpy_x_im[i] = -18'sd11 - i * 18'sd2;
            axpy_y_re[i] = 18'sd7 + (i & 7);
            axpy_y_im[i] = -18'sd5 - (i & 5);
            axpy_expected_re[i] = (axpy_y_re[i] <<< 8) + (ALPHA_RE * axpy_x_re[i]) - (ALPHA_IM * axpy_x_im[i]);
            axpy_expected_im[i] = (axpy_y_im[i] <<< 8) + (ALPHA_RE * axpy_x_im[i]) + (ALPHA_IM * axpy_x_re[i]);
        end

        repeat (3) @(posedge clk);
        reset_n = 1'b1;
        @(posedge clk);
        start = 1'b1;
        @(posedge clk);
        start = 1'b0;

        for (g = 0; g < HPSI_N; g = g + 1) begin
            left = (g == 0) ? 0 : g - 1;
            right = (g == HPSI_N - 1) ? HPSI_N - 1 : g + 1;
            @(negedge clk);
            mode = MODE_HPSI;
            a_re = hpsi_re[left];
            a_im = hpsi_im[left];
            b_re = hpsi_re[g];
            b_im = hpsi_im[g];
            c_re = hpsi_re[right];
            c_im = hpsi_im[right];
            weight = hpsi_vloc[g];
            band_first = 1'b0;
            band_last = 1'b0;
            sample_valid = 1'b1;
            @(posedge clk);
            #1;
            latency_cycles = latency_cycles + 1;
            hpsi_cycles = hpsi_cycles + 1;
            if (valid !== 1'b1 || out_re !== hpsi_expected_re[g] || out_im !== hpsi_expected_im[g]) begin
                $display("DSE_REAL_RTL_FAIL hpsi sample=%0d expected=%0d,%0d got=%0d,%0d valid=%0d", g, hpsi_expected_re[g], hpsi_expected_im[g], out_re, out_im, valid);
                $finish(1);
            end
        end

        for (g = 0; g < SUM_GRID; g = g + 1) begin
            for (b = 0; b < SUM_BANDS; b = b + 1) begin
                @(negedge clk);
                idx = b * SUM_GRID + g;
                mode = MODE_SUM_BAND;
                b_re = sum_re[idx];
                b_im = sum_im[idx];
                weight = sum_weight[b];
                band_first = (b == 0);
                band_last = (b == SUM_BANDS - 1);
                sample_valid = 1'b1;
                @(posedge clk);
                #1;
                latency_cycles = latency_cycles + 1;
                sum_band_cycles = sum_band_cycles + 1;
                if (band_last) begin
                    if (valid !== 1'b1 || rho_out !== sum_expected[g]) begin
                        $display("DSE_REAL_RTL_FAIL sum_band grid=%0d expected=%0d got=%0d valid=%0d", g, sum_expected[g], rho_out, valid);
                        $finish(1);
                    end
                end
            end
        end

        for (i = 0; i < AXPY_N; i = i + 1) begin
            @(negedge clk);
            mode = MODE_AXPY;
            a_re = axpy_x_re[i];
            a_im = axpy_x_im[i];
            y_re = axpy_y_re[i];
            y_im = axpy_y_im[i];
            band_first = 1'b0;
            band_last = 1'b0;
            sample_valid = 1'b1;
            @(posedge clk);
            #1;
            latency_cycles = latency_cycles + 1;
            axpy_cycles = axpy_cycles + 1;
            if (valid !== 1'b1 || out_re !== axpy_expected_re[i] || out_im !== axpy_expected_im[i]) begin
                $display("DSE_REAL_RTL_FAIL axpy sample=%0d expected=%0d,%0d got=%0d,%0d valid=%0d", i, axpy_expected_re[i], axpy_expected_im[i], out_re, out_im, valid);
                $finish(1);
            end
        end

        @(negedge clk);
        sample_valid = 1'b0;
        #1;
        if (done !== 1'b1 || latency_cycles != TOTAL_SAMPLES) begin
            $display("DSE_REAL_RTL_FAIL done=%0d latency=%0d total=%0d", done, latency_cycles, TOTAL_SAMPLES);
            $finish(1);
        end
        $display("DSE_REAL_RTL_COMPONENT hpsi samples=%0d cycles=%0d", HPSI_N, hpsi_cycles);
        $display("DSE_REAL_RTL_COMPONENT sum_band samples=%0d cycles=%0d", SUM_SAMPLES, sum_band_cycles);
        $display("DSE_REAL_RTL_COMPONENT axpy samples=%0d cycles=%0d", AXPY_N, axpy_cycles);
        $display("DSE_REAL_RTL_PASS qeic_real_integrated_combined_sidecar_rtl samples=%0d", TOTAL_SAMPLES);
        $display("DSE_REAL_RTL_LATENCY_CYCLES %0d", latency_cycles);
        $finish(0);
    end
endmodule
"""


def materialize_integrated_vcs_sidecar_project(specs: Sequence[Mapping[str, Any]], out_dir: Path) -> dict[str, Any]:
    """Materialize one integrated RTL/VCS sidecar covering h_psi, sum_band, and AXPY motifs."""

    by_id = {str(spec.get("architecture_id")): spec for spec in specs if spec.get("architecture_id")}
    hpsi = by_id.get("hybrid_hpsi_local_potential_v1", {})
    sum_band = by_id.get("hybrid_sum_band_density_accumulator_v1", {})
    axpy = by_id.get("hybrid_tiled_complex_axpy_v1", {})
    hpsi_samples = int(hpsi.get("golden_grid_points") or hpsi.get("golden_vector_length") or 96)
    sum_grid = int(sum_band.get("golden_grid_points") or 32)
    sum_bands = int(sum_band.get("golden_band_count") or 4)
    axpy_samples = int(axpy.get("golden_vector_length") or 64)
    component_samples = {
        "hpsi": hpsi_samples,
        "sum_band": sum_grid * sum_bands,
        "axpy": axpy_samples,
    }
    project_dir = Path(out_dir) / _INTEGRATED_SIDECAR_ID / "vcs_rtl"
    project_dir.mkdir(parents=True, exist_ok=True)
    rtl_source = _integrated_vcs_rtl_source()
    tb_source = _integrated_vcs_tb_source(
        hpsi_samples=hpsi_samples,
        sum_band_grid_points=sum_grid,
        sum_band_bands=sum_bands,
        axpy_samples=axpy_samples,
    )
    rtl_sv = project_dir / "qeic_real_integrated_combined_sidecar_rtl.sv"
    tb_sv = project_dir / "tb_qeic_real_integrated_combined_sidecar_rtl.sv"
    rtl_sv.write_text(rtl_source, encoding="utf-8")
    tb_sv.write_text(tb_source, encoding="utf-8")
    return {
        "architecture_id": _INTEGRATED_SIDECAR_ID,
        "kernel_name": _INTEGRATED_SIDECAR_KERNEL,
        "project_dir": str(project_dir),
        "rtl_sv": str(rtl_sv),
        "tb_sv": str(tb_sv),
        "rtl_hash": _sha256_text(rtl_source),
        "testbench_hash": _sha256_text(tb_source),
        "samples": sum(component_samples.values()),
        "component_samples": component_samples,
        "clock_ns": 8.75,
        "claim_boundary": "Single integrated RTL/VCS sidecar miniapp covering h_psi, sum_band, and AXPY motifs; not full QE kernel integration or board measurement.",
    }


def _integrated_pipelined_vcs_rtl_source() -> str:
    return r"""module qeic_real_integrated_pipelined_sidecar_rtl #(
    parameter integer TOTAL_SAMPLES = 288,
    parameter integer WIDTH = 18,
    parameter integer ACC_WIDTH = 48,
    parameter signed [WIDTH-1:0] ALPHA_RE = 18'sd192,
    parameter signed [WIDTH-1:0] ALPHA_IM = -18'sd32
) (
    input  wire clk,
    input  wire reset_n,
    input  wire start,
    input  wire sample_valid,
    input  wire [1:0] mode,
    input  wire band_first,
    input  wire band_last,
    input  wire signed [WIDTH-1:0] a_re,
    input  wire signed [WIDTH-1:0] a_im,
    input  wire signed [WIDTH-1:0] b_re,
    input  wire signed [WIDTH-1:0] b_im,
    input  wire signed [WIDTH-1:0] c_re,
    input  wire signed [WIDTH-1:0] c_im,
    input  wire signed [WIDTH-1:0] weight,
    input  wire signed [WIDTH-1:0] y_re,
    input  wire signed [WIDTH-1:0] y_im,
    output reg  signed [ACC_WIDTH-1:0] out_re,
    output reg  signed [ACC_WIDTH-1:0] out_im,
    output reg  signed [ACC_WIDTH-1:0] rho_out,
    output reg  valid,
    output reg  done
);
    localparam [1:0] MODE_HPSI = 2'd0;
    localparam [1:0] MODE_SUM_BAND = 2'd1;
    localparam [1:0] MODE_AXPY = 2'd2;

    reg active;
    reg busy;
    reg [2:0] phase;
    integer processed_count;
    reg stage1_valid;
    reg stage2_valid;
    reg stage3_valid;
    reg stage4_valid;

    reg [1:0] mode_r;
    reg band_first_r;
    reg band_last_r;
    reg signed [WIDTH-1:0] a_re_r;
    reg signed [WIDTH-1:0] a_im_r;
    reg signed [WIDTH-1:0] b_re_r;
    reg signed [WIDTH-1:0] b_im_r;
    reg signed [WIDTH-1:0] c_re_r;
    reg signed [WIDTH-1:0] c_im_r;
    reg signed [WIDTH-1:0] weight_r;
    reg signed [WIDTH-1:0] y_re_r;
    reg signed [WIDTH-1:0] y_im_r;

    reg signed [ACC_WIDTH-1:0] lap_re_s2;
    reg signed [ACC_WIDTH-1:0] lap_im_s2;
    reg signed [(2*WIDTH)-1:0] vloc_re_s2;
    reg signed [(2*WIDTH)-1:0] vloc_im_s2;
    reg signed [(2*WIDTH)-1:0] re_sq_s2;
    reg signed [(2*WIDTH)-1:0] im_sq_s2;
    reg signed [WIDTH-1:0] weight_s2;
    reg signed [ACC_WIDTH-1:0] alpha_x_re_s2;
    reg signed [ACC_WIDTH-1:0] alpha_x_im_s2;
    reg signed [ACC_WIDTH-1:0] y_re_ext_s2;
    reg signed [ACC_WIDTH-1:0] y_im_ext_s2;

    reg signed [ACC_WIDTH-1:0] hpsi_re_s3;
    reg signed [ACC_WIDTH-1:0] hpsi_im_s3;
    reg signed [ACC_WIDTH-1:0] abs_sq_s3;
    reg signed [(ACC_WIDTH+WIDTH)-1:0] weighted_s3;
    reg signed [ACC_WIDTH-1:0] axpy_re_s3;
    reg signed [ACC_WIDTH-1:0] axpy_im_s3;
    reg signed [ACC_WIDTH-1:0] rho_acc;
    wire signed [ACC_WIDTH-1:0] sb_contribution_s3 = weighted_s3[ACC_WIDTH+WIDTH-1:WIDTH];
    wire signed [ACC_WIDTH-1:0] rho_acc_next = band_first_r ? sb_contribution_s3 : (rho_acc + sb_contribution_s3);

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            active <= 1'b0;
            busy <= 1'b0;
            phase <= 3'd0;
            processed_count <= 0;
            stage1_valid <= 1'b0;
            stage2_valid <= 1'b0;
            stage3_valid <= 1'b0;
            stage4_valid <= 1'b0;
            rho_acc <= 0;
            out_re <= 0;
            out_im <= 0;
            rho_out <= 0;
            valid <= 1'b0;
            done <= 1'b0;
        end else begin
            stage1_valid <= 1'b0;
            stage2_valid <= 1'b0;
            stage3_valid <= 1'b0;
            stage4_valid <= 1'b0;
            valid <= 1'b0;
            if (start) begin
                active <= 1'b1;
                busy <= 1'b0;
                phase <= 3'd0;
                processed_count <= 0;
                rho_acc <= 0;
                out_re <= 0;
                out_im <= 0;
                rho_out <= 0;
                done <= 1'b0;
            end else if (active) begin
                if (!busy && sample_valid) begin
                    mode_r <= mode;
                    band_first_r <= band_first;
                    band_last_r <= band_last;
                    a_re_r <= a_re;
                    a_im_r <= a_im;
                    b_re_r <= b_re;
                    b_im_r <= b_im;
                    c_re_r <= c_re;
                    c_im_r <= c_im;
                    weight_r <= weight;
                    y_re_r <= y_re;
                    y_im_r <= y_im;
                    busy <= 1'b1;
                    phase <= 3'd1;
                    stage1_valid <= 1'b1;
                end else if (busy) begin
                    case (phase)
                        3'd1: begin
                            lap_re_s2 <= {{(ACC_WIDTH-WIDTH){a_re_r[WIDTH-1]}}, a_re_r}
                                - ({{(ACC_WIDTH-WIDTH){b_re_r[WIDTH-1]}}, b_re_r} <<< 1)
                                + {{(ACC_WIDTH-WIDTH){c_re_r[WIDTH-1]}}, c_re_r};
                            lap_im_s2 <= {{(ACC_WIDTH-WIDTH){a_im_r[WIDTH-1]}}, a_im_r}
                                - ({{(ACC_WIDTH-WIDTH){b_im_r[WIDTH-1]}}, b_im_r} <<< 1)
                                + {{(ACC_WIDTH-WIDTH){c_im_r[WIDTH-1]}}, c_im_r};
                            vloc_re_s2 <= weight_r * b_re_r;
                            vloc_im_s2 <= weight_r * b_im_r;
                            re_sq_s2 <= b_re_r * b_re_r;
                            im_sq_s2 <= b_im_r * b_im_r;
                            weight_s2 <= weight_r;
                            alpha_x_re_s2 <= (ALPHA_RE * a_re_r) - (ALPHA_IM * a_im_r);
                            alpha_x_im_s2 <= (ALPHA_RE * a_im_r) + (ALPHA_IM * a_re_r);
                            y_re_ext_s2 <= {{(ACC_WIDTH-WIDTH){y_re_r[WIDTH-1]}}, y_re_r} <<< 8;
                            y_im_ext_s2 <= {{(ACC_WIDTH-WIDTH){y_im_r[WIDTH-1]}}, y_im_r} <<< 8;
                            stage2_valid <= 1'b1;
                            phase <= 3'd2;
                        end
                        3'd2: begin
                            hpsi_re_s3 <= -(lap_re_s2 >>> 1) + (vloc_re_s2 >>> 8);
                            hpsi_im_s3 <= -(lap_im_s2 >>> 1) + (vloc_im_s2 >>> 8);
                            abs_sq_s3 <= {{(ACC_WIDTH-(2*WIDTH)){1'b0}}, re_sq_s2 + im_sq_s2};
                            weighted_s3 <= ({{(ACC_WIDTH-(2*WIDTH)){1'b0}}, re_sq_s2 + im_sq_s2}) * weight_s2;
                            axpy_re_s3 <= y_re_ext_s2 + alpha_x_re_s2;
                            axpy_im_s3 <= y_im_ext_s2 + alpha_x_im_s2;
                            stage3_valid <= 1'b1;
                            phase <= 3'd3;
                        end
                        default: begin
                            case (mode_r)
                                MODE_HPSI: begin
                                    out_re <= hpsi_re_s3;
                                    out_im <= hpsi_im_s3;
                                    rho_out <= 0;
                                    valid <= 1'b1;
                                end
                                MODE_SUM_BAND: begin
                                    rho_acc <= rho_acc_next;
                                    rho_out <= rho_acc_next;
                                    out_re <= 0;
                                    out_im <= 0;
                                    valid <= band_last_r;
                                end
                                MODE_AXPY: begin
                                    out_re <= axpy_re_s3;
                                    out_im <= axpy_im_s3;
                                    rho_out <= 0;
                                    valid <= 1'b1;
                                end
                                default: begin
                                    out_re <= 0;
                                    out_im <= 0;
                                    rho_out <= 0;
                                    valid <= 1'b0;
                                end
                            endcase
                            stage4_valid <= 1'b1;
                            if (processed_count == TOTAL_SAMPLES - 1) begin
                                active <= 1'b0;
                                done <= 1'b1;
                            end
                            processed_count <= processed_count + 1;
                            busy <= 1'b0;
                            phase <= 3'd0;
                        end
                    endcase
                end
            end
        end
    end
endmodule
"""


def _integrated_pipelined_vcs_tb_source(*, hpsi_samples: int, sum_band_grid_points: int, sum_band_bands: int, axpy_samples: int) -> str:
    sum_band_samples = sum_band_grid_points * sum_band_bands
    total_samples = hpsi_samples + sum_band_samples + axpy_samples
    pipeline_latency = _PIPELINED_SIDECAR_PIPELINE_LATENCY
    return f"""module tb_qeic_real_integrated_pipelined_sidecar_rtl;
    localparam integer HPSI_N = {hpsi_samples};
    localparam integer SUM_GRID = {sum_band_grid_points};
    localparam integer SUM_BANDS = {sum_band_bands};
    localparam integer SUM_SAMPLES = {sum_band_samples};
    localparam integer AXPY_N = {axpy_samples};
    localparam integer TOTAL_SAMPLES = {total_samples};
    localparam integer PIPELINE_LATENCY = {pipeline_latency};
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 48;
    localparam [1:0] MODE_HPSI = 2'd0;
    localparam [1:0] MODE_SUM_BAND = 2'd1;
    localparam [1:0] MODE_AXPY = 2'd2;
    localparam signed [WIDTH-1:0] ALPHA_RE = 18'sd192;
    localparam signed [WIDTH-1:0] ALPHA_IM = -18'sd32;
    reg clk;
    reg reset_n;
    reg start;
    reg sample_valid;
    reg [1:0] mode;
    reg band_first;
    reg band_last;
    reg signed [WIDTH-1:0] a_re;
    reg signed [WIDTH-1:0] a_im;
    reg signed [WIDTH-1:0] b_re;
    reg signed [WIDTH-1:0] b_im;
    reg signed [WIDTH-1:0] c_re;
    reg signed [WIDTH-1:0] c_im;
    reg signed [WIDTH-1:0] weight;
    reg signed [WIDTH-1:0] y_re;
    reg signed [WIDTH-1:0] y_im;
    wire signed [ACC_WIDTH-1:0] out_re;
    wire signed [ACC_WIDTH-1:0] out_im;
    wire signed [ACC_WIDTH-1:0] rho_out;
    wire valid;
    wire done;

    reg signed [WIDTH-1:0] hpsi_re [0:HPSI_N-1];
    reg signed [WIDTH-1:0] hpsi_im [0:HPSI_N-1];
    reg signed [WIDTH-1:0] hpsi_vloc [0:HPSI_N-1];
    reg signed [ACC_WIDTH-1:0] hpsi_expected_re [0:HPSI_N-1];
    reg signed [ACC_WIDTH-1:0] hpsi_expected_im [0:HPSI_N-1];
    reg signed [WIDTH-1:0] sum_re [0:SUM_SAMPLES-1];
    reg signed [WIDTH-1:0] sum_im [0:SUM_SAMPLES-1];
    reg signed [WIDTH-1:0] sum_weight [0:SUM_BANDS-1];
    reg signed [ACC_WIDTH-1:0] sum_expected [0:SUM_GRID-1];
    reg signed [WIDTH-1:0] axpy_x_re [0:AXPY_N-1];
    reg signed [WIDTH-1:0] axpy_x_im [0:AXPY_N-1];
    reg signed [WIDTH-1:0] axpy_y_re [0:AXPY_N-1];
    reg signed [WIDTH-1:0] axpy_y_im [0:AXPY_N-1];
    reg signed [ACC_WIDTH-1:0] axpy_expected_re [0:AXPY_N-1];
    reg signed [ACC_WIDTH-1:0] axpy_expected_im [0:AXPY_N-1];
    reg signed [ACC_WIDTH-1:0] lap_re;
    reg signed [ACC_WIDTH-1:0] lap_im;
    reg signed [ACC_WIDTH-1:0] acc;
    reg signed [(2*WIDTH)-1:0] re_sq;
    reg signed [(2*WIDTH)-1:0] im_sq;
    reg signed [ACC_WIDTH-1:0] abs_sq;
    integer i;
    integer g;
    integer b;
    integer left;
    integer right;
    integer idx;
    integer latency_cycles;
    integer hpsi_cycles;
    integer sum_band_cycles;
    integer axpy_cycles;

    qeic_real_integrated_pipelined_sidecar_rtl #(
        .TOTAL_SAMPLES(TOTAL_SAMPLES),
        .WIDTH(WIDTH),
        .ACC_WIDTH(ACC_WIDTH),
        .ALPHA_RE(ALPHA_RE),
        .ALPHA_IM(ALPHA_IM)
    ) dut (
        .clk(clk),
        .reset_n(reset_n),
        .start(start),
        .sample_valid(sample_valid),
        .mode(mode),
        .band_first(band_first),
        .band_last(band_last),
        .a_re(a_re),
        .a_im(a_im),
        .b_re(b_re),
        .b_im(b_im),
        .c_re(c_re),
        .c_im(c_im),
        .weight(weight),
        .y_re(y_re),
        .y_im(y_im),
        .out_re(out_re),
        .out_im(out_im),
        .rho_out(rho_out),
        .valid(valid),
        .done(done)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    task automatic drive_and_check;
        input [1:0] in_mode;
        input in_band_first;
        input in_band_last;
        input signed [WIDTH-1:0] in_a_re;
        input signed [WIDTH-1:0] in_a_im;
        input signed [WIDTH-1:0] in_b_re;
        input signed [WIDTH-1:0] in_b_im;
        input signed [WIDTH-1:0] in_c_re;
        input signed [WIDTH-1:0] in_c_im;
        input signed [WIDTH-1:0] in_weight;
        input signed [WIDTH-1:0] in_y_re;
        input signed [WIDTH-1:0] in_y_im;
        input expect_valid;
        input signed [ACC_WIDTH-1:0] expect_re;
        input signed [ACC_WIDTH-1:0] expect_im;
        input signed [ACC_WIDTH-1:0] expect_rho;
        begin
            @(negedge clk);
            mode = in_mode;
            band_first = in_band_first;
            band_last = in_band_last;
            a_re = in_a_re;
            a_im = in_a_im;
            b_re = in_b_re;
            b_im = in_b_im;
            c_re = in_c_re;
            c_im = in_c_im;
            weight = in_weight;
            y_re = in_y_re;
            y_im = in_y_im;
            sample_valid = 1'b1;
            @(posedge clk);
            #1;
            latency_cycles = latency_cycles + 1;
            @(negedge clk);
            sample_valid = 1'b0;
            repeat (PIPELINE_LATENCY - 1) begin
                @(posedge clk);
                #1;
                latency_cycles = latency_cycles + 1;
            end
            if (valid !== expect_valid) begin
                $display("DSE_REAL_RTL_FAIL pipeline valid expected=%0d got=%0d mode=%0d", expect_valid, valid, in_mode);
                $finish(1);
            end
            if (expect_valid && in_mode == MODE_SUM_BAND && rho_out !== expect_rho) begin
                $display("DSE_REAL_RTL_FAIL pipeline sum_band expected=%0d got=%0d", expect_rho, rho_out);
                $finish(1);
            end
            if (expect_valid && in_mode != MODE_SUM_BAND && (out_re !== expect_re || out_im !== expect_im)) begin
                $display("DSE_REAL_RTL_FAIL pipeline vector expected=%0d,%0d got=%0d,%0d mode=%0d", expect_re, expect_im, out_re, out_im, in_mode);
                $finish(1);
            end
        end
    endtask

    initial begin
        reset_n = 1'b0;
        start = 1'b0;
        sample_valid = 1'b0;
        mode = MODE_HPSI;
        band_first = 1'b0;
        band_last = 1'b0;
        a_re = 0;
        a_im = 0;
        b_re = 0;
        b_im = 0;
        c_re = 0;
        c_im = 0;
        weight = 0;
        y_re = 0;
        y_im = 0;
        latency_cycles = 0;
        hpsi_cycles = 0;
        sum_band_cycles = 0;
        axpy_cycles = 0;

        for (g = 0; g < HPSI_N; g = g + 1) begin
            hpsi_re[g] = 18'sd64 + g * 18'sd3;
            hpsi_im[g] = -18'sd51 - g * 18'sd2;
            hpsi_vloc[g] = 18'sd128 + ((g * 17) & 31);
        end
        for (g = 0; g < HPSI_N; g = g + 1) begin
            left = (g == 0) ? 0 : g - 1;
            right = (g == HPSI_N - 1) ? HPSI_N - 1 : g + 1;
            lap_re = hpsi_re[left] - (hpsi_re[g] <<< 1) + hpsi_re[right];
            lap_im = hpsi_im[left] - (hpsi_im[g] <<< 1) + hpsi_im[right];
            hpsi_expected_re[g] = -(lap_re >>> 1) + ((hpsi_vloc[g] * hpsi_re[g]) >>> 8);
            hpsi_expected_im[g] = -(lap_im >>> 1) + ((hpsi_vloc[g] * hpsi_im[g]) >>> 8);
        end
        for (b = 0; b < SUM_BANDS; b = b + 1) begin
            sum_weight[b] = 18'sd64 + b * 18'sd11;
        end
        for (g = 0; g < SUM_GRID; g = g + 1) begin
            sum_expected[g] = 0;
        end
        for (b = 0; b < SUM_BANDS; b = b + 1) begin
            for (g = 0; g < SUM_GRID; g = g + 1) begin
                idx = b * SUM_GRID + g;
                sum_re[idx] = 18'sd32 + idx * 18'sd2 + (g & 3);
                sum_im[idx] = -18'sd21 - idx;
            end
        end
        for (g = 0; g < SUM_GRID; g = g + 1) begin
            acc = 0;
            for (b = 0; b < SUM_BANDS; b = b + 1) begin
                idx = b * SUM_GRID + g;
                re_sq = sum_re[idx] * sum_re[idx];
                im_sq = sum_im[idx] * sum_im[idx];
                abs_sq = re_sq + im_sq;
                acc = acc + ((abs_sq * sum_weight[b]) >>> WIDTH);
            end
            sum_expected[g] = acc;
        end
        for (i = 0; i < AXPY_N; i = i + 1) begin
            axpy_x_re[i] = 18'sd16 + i * 18'sd3;
            axpy_x_im[i] = -18'sd11 - i * 18'sd2;
            axpy_y_re[i] = 18'sd7 + (i & 7);
            axpy_y_im[i] = -18'sd5 - (i & 5);
            axpy_expected_re[i] = (axpy_y_re[i] <<< 8) + (ALPHA_RE * axpy_x_re[i]) - (ALPHA_IM * axpy_x_im[i]);
            axpy_expected_im[i] = (axpy_y_im[i] <<< 8) + (ALPHA_RE * axpy_x_im[i]) + (ALPHA_IM * axpy_x_re[i]);
        end

        repeat (3) @(posedge clk);
        reset_n = 1'b1;
        @(posedge clk);
        start = 1'b1;
        @(posedge clk);
        start = 1'b0;

        for (g = 0; g < HPSI_N; g = g + 1) begin
            left = (g == 0) ? 0 : g - 1;
            right = (g == HPSI_N - 1) ? HPSI_N - 1 : g + 1;
            drive_and_check(MODE_HPSI, 1'b0, 1'b0, hpsi_re[left], hpsi_im[left], hpsi_re[g], hpsi_im[g], hpsi_re[right], hpsi_im[right], hpsi_vloc[g], 0, 0, 1'b1, hpsi_expected_re[g], hpsi_expected_im[g], 0);
            hpsi_cycles = hpsi_cycles + PIPELINE_LATENCY;
        end

        for (g = 0; g < SUM_GRID; g = g + 1) begin
            for (b = 0; b < SUM_BANDS; b = b + 1) begin
                idx = b * SUM_GRID + g;
                drive_and_check(MODE_SUM_BAND, b == 0, b == SUM_BANDS - 1, 0, 0, sum_re[idx], sum_im[idx], 0, 0, sum_weight[b], 0, 0, b == SUM_BANDS - 1, 0, 0, sum_expected[g]);
                sum_band_cycles = sum_band_cycles + PIPELINE_LATENCY;
            end
        end

        for (i = 0; i < AXPY_N; i = i + 1) begin
            drive_and_check(MODE_AXPY, 1'b0, 1'b0, axpy_x_re[i], axpy_x_im[i], 0, 0, 0, 0, 0, axpy_y_re[i], axpy_y_im[i], 1'b1, axpy_expected_re[i], axpy_expected_im[i], 0);
            axpy_cycles = axpy_cycles + PIPELINE_LATENCY;
        end

        #1;
        if (done !== 1'b1 || latency_cycles != TOTAL_SAMPLES * PIPELINE_LATENCY) begin
            $display("DSE_REAL_RTL_FAIL pipeline done=%0d latency=%0d total=%0d", done, latency_cycles, TOTAL_SAMPLES * PIPELINE_LATENCY);
            $finish(1);
        end
        $display("DSE_REAL_RTL_COMPONENT hpsi samples=%0d cycles=%0d", HPSI_N, hpsi_cycles);
        $display("DSE_REAL_RTL_COMPONENT sum_band samples=%0d cycles=%0d", SUM_SAMPLES, sum_band_cycles);
        $display("DSE_REAL_RTL_COMPONENT axpy samples=%0d cycles=%0d", AXPY_N, axpy_cycles);
        $display("DSE_REAL_RTL_PASS qeic_real_integrated_pipelined_sidecar_rtl samples=%0d", TOTAL_SAMPLES);
        $display("DSE_REAL_RTL_LATENCY_CYCLES %0d", latency_cycles);
        $finish(0);
    end
endmodule
"""


def materialize_integrated_pipelined_vcs_sidecar_project(specs: Sequence[Mapping[str, Any]], out_dir: Path) -> dict[str, Any]:
    """Materialize a second integrated RTL/VCS sidecar with explicit intra-sample pipeline stages."""

    by_id = {str(spec.get("architecture_id")): spec for spec in specs if spec.get("architecture_id")}
    hpsi = by_id.get("hybrid_hpsi_local_potential_v1", {})
    sum_band = by_id.get("hybrid_sum_band_density_accumulator_v1", {})
    axpy = by_id.get("hybrid_tiled_complex_axpy_v1", {})
    hpsi_samples = int(hpsi.get("golden_grid_points") or hpsi.get("golden_vector_length") or 96)
    sum_grid = int(sum_band.get("golden_grid_points") or 32)
    sum_bands = int(sum_band.get("golden_band_count") or 4)
    axpy_samples = int(axpy.get("golden_vector_length") or 64)
    component_samples = {
        "hpsi": hpsi_samples,
        "sum_band": sum_grid * sum_bands,
        "axpy": axpy_samples,
    }
    project_dir = Path(out_dir) / _PIPELINED_SIDECAR_ID / "vcs_rtl"
    project_dir.mkdir(parents=True, exist_ok=True)
    rtl_source = _integrated_pipelined_vcs_rtl_source()
    tb_source = _integrated_pipelined_vcs_tb_source(
        hpsi_samples=hpsi_samples,
        sum_band_grid_points=sum_grid,
        sum_band_bands=sum_bands,
        axpy_samples=axpy_samples,
    )
    rtl_sv = project_dir / "qeic_real_integrated_pipelined_sidecar_rtl.sv"
    tb_sv = project_dir / "tb_qeic_real_integrated_pipelined_sidecar_rtl.sv"
    rtl_sv.write_text(rtl_source, encoding="utf-8")
    tb_sv.write_text(tb_source, encoding="utf-8")
    return {
        "architecture_id": _PIPELINED_SIDECAR_ID,
        "kernel_name": _PIPELINED_SIDECAR_KERNEL,
        "project_dir": str(project_dir),
        "rtl_sv": str(rtl_sv),
        "tb_sv": str(tb_sv),
        "rtl_hash": _sha256_text(rtl_source),
        "testbench_hash": _sha256_text(tb_source),
        "samples": sum(component_samples.values()),
        "component_samples": component_samples,
        "pipeline_latency_cycles": _PIPELINED_SIDECAR_PIPELINE_LATENCY,
        "clock_ns": 10.0,
        "claim_boundary": "Pipelined integrated RTL/VCS sidecar miniapp covering h_psi, sum_band, and AXPY motifs; not full QE kernel integration or board measurement.",
    }


def _integrated_streaming_vcs_rtl_source() -> str:
    return r"""module qeic_real_integrated_streaming_pipeline_sidecar_rtl #(
    parameter integer TOTAL_SAMPLES = 288,
    parameter integer WIDTH = 18,
    parameter integer ACC_WIDTH = 48,
    parameter signed [WIDTH-1:0] ALPHA_RE = 18'sd192,
    parameter signed [WIDTH-1:0] ALPHA_IM = -18'sd32
) (
    input  wire clk,
    input  wire reset_n,
    input  wire start,
    input  wire sample_valid,
    input  wire [1:0] mode,
    input  wire band_first,
    input  wire band_last,
    input  wire signed [WIDTH-1:0] a_re,
    input  wire signed [WIDTH-1:0] a_im,
    input  wire signed [WIDTH-1:0] b_re,
    input  wire signed [WIDTH-1:0] b_im,
    input  wire signed [WIDTH-1:0] c_re,
    input  wire signed [WIDTH-1:0] c_im,
    input  wire signed [WIDTH-1:0] weight,
    input  wire signed [WIDTH-1:0] y_re,
    input  wire signed [WIDTH-1:0] y_im,
    output reg  signed [ACC_WIDTH-1:0] out_re,
    output reg  signed [ACC_WIDTH-1:0] out_im,
    output reg  signed [ACC_WIDTH-1:0] rho_out,
    output reg  valid,
    output reg  done
);
    localparam [1:0] MODE_HPSI = 2'd0;
    localparam [1:0] MODE_SUM_BAND = 2'd1;
    localparam [1:0] MODE_AXPY = 2'd2;

    reg active;
    integer accepted_count;
    integer completed_count;

    reg stage1_valid;
    reg [1:0] mode_s1;
    reg band_first_s1;
    reg band_last_s1;
    reg signed [WIDTH-1:0] a_re_s1;
    reg signed [WIDTH-1:0] a_im_s1;
    reg signed [WIDTH-1:0] b_re_s1;
    reg signed [WIDTH-1:0] b_im_s1;
    reg signed [WIDTH-1:0] c_re_s1;
    reg signed [WIDTH-1:0] c_im_s1;
    reg signed [WIDTH-1:0] weight_s1;
    reg signed [WIDTH-1:0] y_re_s1;
    reg signed [WIDTH-1:0] y_im_s1;

    reg stage2_valid;
    reg [1:0] mode_s2;
    reg band_first_s2;
    reg band_last_s2;
    reg signed [ACC_WIDTH-1:0] lap_re_s2;
    reg signed [ACC_WIDTH-1:0] lap_im_s2;
    reg signed [(2*WIDTH)-1:0] vloc_re_s2;
    reg signed [(2*WIDTH)-1:0] vloc_im_s2;
    reg signed [(2*WIDTH)-1:0] re_sq_s2;
    reg signed [(2*WIDTH)-1:0] im_sq_s2;
    reg signed [WIDTH-1:0] weight_s2;
    reg signed [ACC_WIDTH-1:0] alpha_x_re_s2;
    reg signed [ACC_WIDTH-1:0] alpha_x_im_s2;
    reg signed [ACC_WIDTH-1:0] y_re_ext_s2;
    reg signed [ACC_WIDTH-1:0] y_im_ext_s2;

    reg stage3_valid;
    reg [1:0] mode_s3;
    reg band_first_s3;
    reg band_last_s3;
    reg signed [ACC_WIDTH-1:0] hpsi_re_s3;
    reg signed [ACC_WIDTH-1:0] hpsi_im_s3;
    reg signed [(ACC_WIDTH+WIDTH)-1:0] weighted_s3;
    reg signed [ACC_WIDTH-1:0] axpy_re_s3;
    reg signed [ACC_WIDTH-1:0] axpy_im_s3;
    reg signed [ACC_WIDTH-1:0] rho_acc;

    wire signed [ACC_WIDTH-1:0] sb_contribution_s3 = weighted_s3[ACC_WIDTH+WIDTH-1:WIDTH];
    wire signed [ACC_WIDTH-1:0] rho_acc_next = band_first_s3 ? sb_contribution_s3 : (rho_acc + sb_contribution_s3);

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            active <= 1'b0;
            accepted_count <= 0;
            completed_count <= 0;
            stage1_valid <= 1'b0;
            stage2_valid <= 1'b0;
            stage3_valid <= 1'b0;
            rho_acc <= 0;
            out_re <= 0;
            out_im <= 0;
            rho_out <= 0;
            valid <= 1'b0;
            done <= 1'b0;
        end else begin
            valid <= 1'b0;
            if (start) begin
                active <= 1'b1;
                accepted_count <= 0;
                completed_count <= 0;
                stage1_valid <= 1'b0;
                stage2_valid <= 1'b0;
                stage3_valid <= 1'b0;
                rho_acc <= 0;
                out_re <= 0;
                out_im <= 0;
                rho_out <= 0;
                done <= 1'b0;
            end else if (active) begin
                if (stage3_valid) begin
                    case (mode_s3)
                        MODE_HPSI: begin
                            out_re <= hpsi_re_s3;
                            out_im <= hpsi_im_s3;
                            rho_out <= 0;
                            valid <= 1'b1;
                        end
                        MODE_SUM_BAND: begin
                            rho_acc <= rho_acc_next;
                            rho_out <= rho_acc_next;
                            out_re <= 0;
                            out_im <= 0;
                            valid <= band_last_s3;
                        end
                        MODE_AXPY: begin
                            out_re <= axpy_re_s3;
                            out_im <= axpy_im_s3;
                            rho_out <= 0;
                            valid <= 1'b1;
                        end
                        default: begin
                            out_re <= 0;
                            out_im <= 0;
                            rho_out <= 0;
                            valid <= 1'b0;
                        end
                    endcase
                    if (completed_count == TOTAL_SAMPLES - 1) begin
                        active <= 1'b0;
                        done <= 1'b1;
                    end
                    completed_count <= completed_count + 1;
                end

                stage3_valid <= stage2_valid;
                mode_s3 <= mode_s2;
                band_first_s3 <= band_first_s2;
                band_last_s3 <= band_last_s2;
                hpsi_re_s3 <= -(lap_re_s2 >>> 1) + (vloc_re_s2 >>> 8);
                hpsi_im_s3 <= -(lap_im_s2 >>> 1) + (vloc_im_s2 >>> 8);
                weighted_s3 <= ({{(ACC_WIDTH-(2*WIDTH)){1'b0}}, re_sq_s2 + im_sq_s2}) * weight_s2;
                axpy_re_s3 <= y_re_ext_s2 + alpha_x_re_s2;
                axpy_im_s3 <= y_im_ext_s2 + alpha_x_im_s2;

                stage2_valid <= stage1_valid;
                mode_s2 <= mode_s1;
                band_first_s2 <= band_first_s1;
                band_last_s2 <= band_last_s1;
                lap_re_s2 <= {{(ACC_WIDTH-WIDTH){a_re_s1[WIDTH-1]}}, a_re_s1}
                    - ({{(ACC_WIDTH-WIDTH){b_re_s1[WIDTH-1]}}, b_re_s1} <<< 1)
                    + {{(ACC_WIDTH-WIDTH){c_re_s1[WIDTH-1]}}, c_re_s1};
                lap_im_s2 <= {{(ACC_WIDTH-WIDTH){a_im_s1[WIDTH-1]}}, a_im_s1}
                    - ({{(ACC_WIDTH-WIDTH){b_im_s1[WIDTH-1]}}, b_im_s1} <<< 1)
                    + {{(ACC_WIDTH-WIDTH){c_im_s1[WIDTH-1]}}, c_im_s1};
                vloc_re_s2 <= weight_s1 * b_re_s1;
                vloc_im_s2 <= weight_s1 * b_im_s1;
                re_sq_s2 <= b_re_s1 * b_re_s1;
                im_sq_s2 <= b_im_s1 * b_im_s1;
                weight_s2 <= weight_s1;
                alpha_x_re_s2 <= (ALPHA_RE * a_re_s1) - (ALPHA_IM * a_im_s1);
                alpha_x_im_s2 <= (ALPHA_RE * a_im_s1) + (ALPHA_IM * a_re_s1);
                y_re_ext_s2 <= {{(ACC_WIDTH-WIDTH){y_re_s1[WIDTH-1]}}, y_re_s1} <<< 8;
                y_im_ext_s2 <= {{(ACC_WIDTH-WIDTH){y_im_s1[WIDTH-1]}}, y_im_s1} <<< 8;

                if (sample_valid && accepted_count < TOTAL_SAMPLES) begin
                    stage1_valid <= 1'b1;
                    mode_s1 <= mode;
                    band_first_s1 <= band_first;
                    band_last_s1 <= band_last;
                    a_re_s1 <= a_re;
                    a_im_s1 <= a_im;
                    b_re_s1 <= b_re;
                    b_im_s1 <= b_im;
                    c_re_s1 <= c_re;
                    c_im_s1 <= c_im;
                    weight_s1 <= weight;
                    y_re_s1 <= y_re;
                    y_im_s1 <= y_im;
                    accepted_count <= accepted_count + 1;
                end else begin
                    stage1_valid <= 1'b0;
                end
            end
        end
    end
endmodule
"""


def _integrated_streaming_vcs_tb_source(*, hpsi_samples: int, sum_band_grid_points: int, sum_band_bands: int, axpy_samples: int) -> str:
    sum_band_samples = sum_band_grid_points * sum_band_bands
    total_samples = hpsi_samples + sum_band_samples + axpy_samples
    output_samples = hpsi_samples + sum_band_grid_points + axpy_samples
    pipeline_latency = _STREAMING_SIDECAR_PIPELINE_LATENCY
    expected_latency = total_samples + pipeline_latency - 1
    hpsi_component_cycles = hpsi_samples + pipeline_latency - 1
    sum_band_component_cycles = sum_band_samples + pipeline_latency - 1
    axpy_component_cycles = axpy_samples + pipeline_latency - 1
    return f"""module tb_qeic_real_integrated_streaming_pipeline_sidecar_rtl;
    localparam integer HPSI_N = {hpsi_samples};
    localparam integer SUM_GRID = {sum_band_grid_points};
    localparam integer SUM_BANDS = {sum_band_bands};
    localparam integer SUM_SAMPLES = {sum_band_samples};
    localparam integer AXPY_N = {axpy_samples};
    localparam integer TOTAL_SAMPLES = {total_samples};
    localparam integer OUTPUT_SAMPLES = {output_samples};
    localparam integer PIPELINE_LATENCY = {pipeline_latency};
    localparam integer EXPECTED_LATENCY = {expected_latency};
    localparam integer HPSI_COMPONENT_CYCLES = {hpsi_component_cycles};
    localparam integer SUM_BAND_COMPONENT_CYCLES = {sum_band_component_cycles};
    localparam integer AXPY_COMPONENT_CYCLES = {axpy_component_cycles};
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 48;
    localparam [1:0] MODE_HPSI = 2'd0;
    localparam [1:0] MODE_SUM_BAND = 2'd1;
    localparam [1:0] MODE_AXPY = 2'd2;
    localparam signed [WIDTH-1:0] ALPHA_RE = 18'sd192;
    localparam signed [WIDTH-1:0] ALPHA_IM = -18'sd32;
    reg clk;
    reg reset_n;
    reg start;
    reg sample_valid;
    reg [1:0] mode;
    reg band_first;
    reg band_last;
    reg signed [WIDTH-1:0] a_re;
    reg signed [WIDTH-1:0] a_im;
    reg signed [WIDTH-1:0] b_re;
    reg signed [WIDTH-1:0] b_im;
    reg signed [WIDTH-1:0] c_re;
    reg signed [WIDTH-1:0] c_im;
    reg signed [WIDTH-1:0] weight;
    reg signed [WIDTH-1:0] y_re;
    reg signed [WIDTH-1:0] y_im;
    wire signed [ACC_WIDTH-1:0] out_re;
    wire signed [ACC_WIDTH-1:0] out_im;
    wire signed [ACC_WIDTH-1:0] rho_out;
    wire valid;
    wire done;

    reg signed [WIDTH-1:0] hpsi_re [0:HPSI_N-1];
    reg signed [WIDTH-1:0] hpsi_im [0:HPSI_N-1];
    reg signed [WIDTH-1:0] hpsi_vloc [0:HPSI_N-1];
    reg signed [ACC_WIDTH-1:0] hpsi_expected_re [0:HPSI_N-1];
    reg signed [ACC_WIDTH-1:0] hpsi_expected_im [0:HPSI_N-1];
    reg signed [WIDTH-1:0] sum_re [0:SUM_SAMPLES-1];
    reg signed [WIDTH-1:0] sum_im [0:SUM_SAMPLES-1];
    reg signed [WIDTH-1:0] sum_weight [0:SUM_BANDS-1];
    reg signed [ACC_WIDTH-1:0] sum_expected [0:SUM_GRID-1];
    reg signed [WIDTH-1:0] axpy_x_re [0:AXPY_N-1];
    reg signed [WIDTH-1:0] axpy_x_im [0:AXPY_N-1];
    reg signed [WIDTH-1:0] axpy_y_re [0:AXPY_N-1];
    reg signed [WIDTH-1:0] axpy_y_im [0:AXPY_N-1];
    reg signed [ACC_WIDTH-1:0] axpy_expected_re [0:AXPY_N-1];
    reg signed [ACC_WIDTH-1:0] axpy_expected_im [0:AXPY_N-1];
    reg signed [ACC_WIDTH-1:0] expected_re [0:OUTPUT_SAMPLES-1];
    reg signed [ACC_WIDTH-1:0] expected_im [0:OUTPUT_SAMPLES-1];
    reg signed [ACC_WIDTH-1:0] expected_rho [0:OUTPUT_SAMPLES-1];
    reg expected_is_sum [0:OUTPUT_SAMPLES-1];
    reg signed [ACC_WIDTH-1:0] lap_re;
    reg signed [ACC_WIDTH-1:0] lap_im;
    reg signed [ACC_WIDTH-1:0] acc;
    reg signed [(2*WIDTH)-1:0] re_sq;
    reg signed [(2*WIDTH)-1:0] im_sq;
    reg signed [ACC_WIDTH-1:0] abs_sq;
    integer i;
    integer g;
    integer b;
    integer left;
    integer right;
    integer idx;
    integer output_idx;
    integer expected_idx;
    integer latency_cycles;

    qeic_real_integrated_streaming_pipeline_sidecar_rtl #(
        .TOTAL_SAMPLES(TOTAL_SAMPLES),
        .WIDTH(WIDTH),
        .ACC_WIDTH(ACC_WIDTH),
        .ALPHA_RE(ALPHA_RE),
        .ALPHA_IM(ALPHA_IM)
    ) dut (
        .clk(clk),
        .reset_n(reset_n),
        .start(start),
        .sample_valid(sample_valid),
        .mode(mode),
        .band_first(band_first),
        .band_last(band_last),
        .a_re(a_re),
        .a_im(a_im),
        .b_re(b_re),
        .b_im(b_im),
        .c_re(c_re),
        .c_im(c_im),
        .weight(weight),
        .y_re(y_re),
        .y_im(y_im),
        .out_re(out_re),
        .out_im(out_im),
        .rho_out(rho_out),
        .valid(valid),
        .done(done)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    task automatic check_output;
        begin
            if (valid === 1'b1) begin
                if (output_idx >= OUTPUT_SAMPLES) begin
                    $display("DSE_REAL_RTL_FAIL streaming extra_valid output_idx=%0d", output_idx);
                    $finish(1);
                end
                if (expected_is_sum[output_idx]) begin
                    if (rho_out !== expected_rho[output_idx]) begin
                        $display("DSE_REAL_RTL_FAIL streaming sum output=%0d expected=%0d got=%0d", output_idx, expected_rho[output_idx], rho_out);
                        $finish(1);
                    end
                end else if (out_re !== expected_re[output_idx] || out_im !== expected_im[output_idx]) begin
                    $display("DSE_REAL_RTL_FAIL streaming vector output=%0d expected=%0d,%0d got=%0d,%0d", output_idx, expected_re[output_idx], expected_im[output_idx], out_re, out_im);
                    $finish(1);
                end
                output_idx = output_idx + 1;
            end
        end
    endtask

    task automatic tick_and_check;
        begin
            @(posedge clk);
            #1;
            latency_cycles = latency_cycles + 1;
            check_output();
        end
    endtask

    initial begin
        reset_n = 1'b0;
        start = 1'b0;
        sample_valid = 1'b0;
        mode = MODE_HPSI;
        band_first = 1'b0;
        band_last = 1'b0;
        a_re = 0;
        a_im = 0;
        b_re = 0;
        b_im = 0;
        c_re = 0;
        c_im = 0;
        weight = 0;
        y_re = 0;
        y_im = 0;
        output_idx = 0;
        expected_idx = 0;
        latency_cycles = 0;

        for (g = 0; g < HPSI_N; g = g + 1) begin
            hpsi_re[g] = 18'sd64 + g * 18'sd3;
            hpsi_im[g] = -18'sd51 - g * 18'sd2;
            hpsi_vloc[g] = 18'sd128 + ((g * 17) & 31);
        end
        for (g = 0; g < HPSI_N; g = g + 1) begin
            left = (g == 0) ? 0 : g - 1;
            right = (g == HPSI_N - 1) ? HPSI_N - 1 : g + 1;
            lap_re = hpsi_re[left] - (hpsi_re[g] <<< 1) + hpsi_re[right];
            lap_im = hpsi_im[left] - (hpsi_im[g] <<< 1) + hpsi_im[right];
            hpsi_expected_re[g] = -(lap_re >>> 1) + ((hpsi_vloc[g] * hpsi_re[g]) >>> 8);
            hpsi_expected_im[g] = -(lap_im >>> 1) + ((hpsi_vloc[g] * hpsi_im[g]) >>> 8);
            expected_re[expected_idx] = hpsi_expected_re[g];
            expected_im[expected_idx] = hpsi_expected_im[g];
            expected_rho[expected_idx] = 0;
            expected_is_sum[expected_idx] = 1'b0;
            expected_idx = expected_idx + 1;
        end
        for (b = 0; b < SUM_BANDS; b = b + 1) begin
            sum_weight[b] = 18'sd64 + b * 18'sd11;
        end
        for (g = 0; g < SUM_GRID; g = g + 1) begin
            sum_expected[g] = 0;
        end
        for (b = 0; b < SUM_BANDS; b = b + 1) begin
            for (g = 0; g < SUM_GRID; g = g + 1) begin
                idx = b * SUM_GRID + g;
                sum_re[idx] = 18'sd32 + idx * 18'sd2 + (g & 3);
                sum_im[idx] = -18'sd21 - idx;
            end
        end
        for (g = 0; g < SUM_GRID; g = g + 1) begin
            acc = 0;
            for (b = 0; b < SUM_BANDS; b = b + 1) begin
                idx = b * SUM_GRID + g;
                re_sq = sum_re[idx] * sum_re[idx];
                im_sq = sum_im[idx] * sum_im[idx];
                abs_sq = re_sq + im_sq;
                acc = acc + ((abs_sq * sum_weight[b]) >>> WIDTH);
            end
            sum_expected[g] = acc;
            expected_re[expected_idx] = 0;
            expected_im[expected_idx] = 0;
            expected_rho[expected_idx] = acc;
            expected_is_sum[expected_idx] = 1'b1;
            expected_idx = expected_idx + 1;
        end
        for (i = 0; i < AXPY_N; i = i + 1) begin
            axpy_x_re[i] = 18'sd16 + i * 18'sd3;
            axpy_x_im[i] = -18'sd11 - i * 18'sd2;
            axpy_y_re[i] = 18'sd7 + (i & 7);
            axpy_y_im[i] = -18'sd5 - (i & 5);
            axpy_expected_re[i] = (axpy_y_re[i] <<< 8) + (ALPHA_RE * axpy_x_re[i]) - (ALPHA_IM * axpy_x_im[i]);
            axpy_expected_im[i] = (axpy_y_im[i] <<< 8) + (ALPHA_RE * axpy_x_im[i]) + (ALPHA_IM * axpy_x_re[i]);
            expected_re[expected_idx] = axpy_expected_re[i];
            expected_im[expected_idx] = axpy_expected_im[i];
            expected_rho[expected_idx] = 0;
            expected_is_sum[expected_idx] = 1'b0;
            expected_idx = expected_idx + 1;
        end
        if (expected_idx != OUTPUT_SAMPLES) begin
            $display("DSE_REAL_RTL_FAIL streaming expected_idx=%0d output_samples=%0d", expected_idx, OUTPUT_SAMPLES);
            $finish(1);
        end

        repeat (3) @(posedge clk);
        reset_n = 1'b1;
        @(posedge clk);
        start = 1'b1;
        @(posedge clk);
        start = 1'b0;

        for (g = 0; g < HPSI_N; g = g + 1) begin
            left = (g == 0) ? 0 : g - 1;
            right = (g == HPSI_N - 1) ? HPSI_N - 1 : g + 1;
            @(negedge clk);
            mode = MODE_HPSI;
            a_re = hpsi_re[left];
            a_im = hpsi_im[left];
            b_re = hpsi_re[g];
            b_im = hpsi_im[g];
            c_re = hpsi_re[right];
            c_im = hpsi_im[right];
            weight = hpsi_vloc[g];
            band_first = 1'b0;
            band_last = 1'b0;
            y_re = 0;
            y_im = 0;
            sample_valid = 1'b1;
            tick_and_check();
        end

        for (g = 0; g < SUM_GRID; g = g + 1) begin
            for (b = 0; b < SUM_BANDS; b = b + 1) begin
                @(negedge clk);
                idx = b * SUM_GRID + g;
                mode = MODE_SUM_BAND;
                a_re = 0;
                a_im = 0;
                b_re = sum_re[idx];
                b_im = sum_im[idx];
                c_re = 0;
                c_im = 0;
                weight = sum_weight[b];
                y_re = 0;
                y_im = 0;
                band_first = (b == 0);
                band_last = (b == SUM_BANDS - 1);
                sample_valid = 1'b1;
                tick_and_check();
            end
        end

        for (i = 0; i < AXPY_N; i = i + 1) begin
            @(negedge clk);
            mode = MODE_AXPY;
            a_re = axpy_x_re[i];
            a_im = axpy_x_im[i];
            b_re = 0;
            b_im = 0;
            c_re = 0;
            c_im = 0;
            weight = 0;
            y_re = axpy_y_re[i];
            y_im = axpy_y_im[i];
            band_first = 1'b0;
            band_last = 1'b0;
            sample_valid = 1'b1;
            tick_and_check();
        end

        @(negedge clk);
        sample_valid = 1'b0;
        band_first = 1'b0;
        band_last = 1'b0;
        while (done !== 1'b1) begin
            tick_and_check();
        end
        if (output_idx != OUTPUT_SAMPLES || latency_cycles != EXPECTED_LATENCY) begin
            $display("DSE_REAL_RTL_FAIL streaming done=%0d outputs=%0d expected_outputs=%0d latency=%0d expected_latency=%0d", done, output_idx, OUTPUT_SAMPLES, latency_cycles, EXPECTED_LATENCY);
            $finish(1);
        end
        $display("DSE_REAL_RTL_COMPONENT hpsi samples=%0d cycles=%0d", HPSI_N, HPSI_COMPONENT_CYCLES);
        $display("DSE_REAL_RTL_COMPONENT sum_band samples=%0d cycles=%0d", SUM_SAMPLES, SUM_BAND_COMPONENT_CYCLES);
        $display("DSE_REAL_RTL_COMPONENT axpy samples=%0d cycles=%0d", AXPY_N, AXPY_COMPONENT_CYCLES);
        $display("DSE_REAL_RTL_PASS qeic_real_integrated_streaming_pipeline_sidecar_rtl samples=%0d", TOTAL_SAMPLES);
        $display("DSE_REAL_RTL_LATENCY_CYCLES %0d", latency_cycles);
        $finish(0);
    end
endmodule
"""


def materialize_integrated_streaming_vcs_sidecar_project(specs: Sequence[Mapping[str, Any]], out_dir: Path) -> dict[str, Any]:
    """Materialize an integrated RTL/VCS sidecar with II=1 streaming pipeline stages."""

    by_id = {str(spec.get("architecture_id")): spec for spec in specs if spec.get("architecture_id")}
    hpsi = by_id.get("hybrid_hpsi_local_potential_v1", {})
    sum_band = by_id.get("hybrid_sum_band_density_accumulator_v1", {})
    axpy = by_id.get("hybrid_tiled_complex_axpy_v1", {})
    hpsi_samples = int(hpsi.get("golden_grid_points") or hpsi.get("golden_vector_length") or 96)
    sum_grid = int(sum_band.get("golden_grid_points") or 32)
    sum_bands = int(sum_band.get("golden_band_count") or 4)
    axpy_samples = int(axpy.get("golden_vector_length") or 64)
    component_samples = {
        "hpsi": hpsi_samples,
        "sum_band": sum_grid * sum_bands,
        "axpy": axpy_samples,
    }
    project_dir = Path(out_dir) / _STREAMING_SIDECAR_ID / "vcs_rtl"
    project_dir.mkdir(parents=True, exist_ok=True)
    rtl_source = _integrated_streaming_vcs_rtl_source()
    tb_source = _integrated_streaming_vcs_tb_source(
        hpsi_samples=hpsi_samples,
        sum_band_grid_points=sum_grid,
        sum_band_bands=sum_bands,
        axpy_samples=axpy_samples,
    )
    rtl_sv = project_dir / "qeic_real_integrated_streaming_pipeline_sidecar_rtl.sv"
    tb_sv = project_dir / "tb_qeic_real_integrated_streaming_pipeline_sidecar_rtl.sv"
    rtl_sv.write_text(rtl_source, encoding="utf-8")
    tb_sv.write_text(tb_source, encoding="utf-8")
    return {
        "architecture_id": _STREAMING_SIDECAR_ID,
        "kernel_name": _STREAMING_SIDECAR_KERNEL,
        "project_dir": str(project_dir),
        "rtl_sv": str(rtl_sv),
        "tb_sv": str(tb_sv),
        "rtl_hash": _sha256_text(rtl_source),
        "testbench_hash": _sha256_text(tb_source),
        "samples": sum(component_samples.values()),
        "component_samples": component_samples,
        "pipeline_latency_cycles": _STREAMING_SIDECAR_PIPELINE_LATENCY,
        "initiation_interval_cycles": 1,
        "clock_ns": 10.0,
        "claim_boundary": "Streaming II=1 integrated RTL/VCS sidecar miniapp covering h_psi, sum_band, and AXPY motifs; not full QE kernel integration or board measurement.",
    }


def _integrated_vivado_impl_wrapper_source(
    *,
    hpsi_samples: int,
    sum_band_grid_points: int,
    sum_band_bands: int,
    axpy_samples: int,
) -> str:
    sum_band_samples = sum_band_grid_points * sum_band_bands
    total_samples = hpsi_samples + sum_band_samples + axpy_samples
    return f"""module qeic_real_integrated_combined_sidecar_impl_top (
    input  wire clk,
    input  wire reset_n,
    input  wire start,
    output wire done,
    output wire [47:0] checksum
);
    localparam integer HPSI_N = {hpsi_samples};
    localparam integer SUM_GRID = {sum_band_grid_points};
    localparam integer SUM_BANDS = {sum_band_bands};
    localparam integer SUM_SAMPLES = {sum_band_samples};
    localparam integer AXPY_N = {axpy_samples};
    localparam integer TOTAL_SAMPLES = {total_samples};
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 48;
    localparam [1:0] MODE_HPSI = 2'd0;
    localparam [1:0] MODE_SUM_BAND = 2'd1;
    localparam [1:0] MODE_AXPY = 2'd2;

    reg sidecar_start;
    reg active;
    reg sample_valid;
    reg [1:0] mode;
    reg band_first;
    reg band_last;
    reg signed [WIDTH-1:0] a_re;
    reg signed [WIDTH-1:0] a_im;
    reg signed [WIDTH-1:0] b_re;
    reg signed [WIDTH-1:0] b_im;
    reg signed [WIDTH-1:0] c_re;
    reg signed [WIDTH-1:0] c_im;
    reg signed [WIDTH-1:0] weight;
    reg signed [WIDTH-1:0] y_re;
    reg signed [WIDTH-1:0] y_im;
    reg [15:0] sample_index;
    reg [47:0] checksum_reg;
    reg done_reg;

    wire signed [ACC_WIDTH-1:0] out_re;
    wire signed [ACC_WIDTH-1:0] out_im;
    wire signed [ACC_WIDTH-1:0] rho_out;
    wire valid;
    wire sidecar_done;
    wire [15:0] sum_phase = sample_index - 16'd{hpsi_samples};
    wire [1:0] sum_band_mod = sum_phase[1:0];

    assign checksum = checksum_reg;
    assign done = done_reg | sidecar_done;

    qeic_real_integrated_combined_sidecar_rtl #(
        .TOTAL_SAMPLES(TOTAL_SAMPLES),
        .WIDTH(WIDTH),
        .ACC_WIDTH(ACC_WIDTH)
    ) sidecar (
        .clk(clk),
        .reset_n(reset_n),
        .start(sidecar_start),
        .sample_valid(sample_valid),
        .mode(mode),
        .band_first(band_first),
        .band_last(band_last),
        .a_re(a_re),
        .a_im(a_im),
        .b_re(b_re),
        .b_im(b_im),
        .c_re(c_re),
        .c_im(c_im),
        .weight(weight),
        .y_re(y_re),
        .y_im(y_im),
        .out_re(out_re),
        .out_im(out_im),
        .rho_out(rho_out),
        .valid(valid),
        .done(sidecar_done)
    );

    always @* begin
        if (sample_index < HPSI_N) begin
            mode = MODE_HPSI;
        end else if (sample_index < HPSI_N + SUM_SAMPLES) begin
            mode = MODE_SUM_BAND;
        end else begin
            mode = MODE_AXPY;
        end
        sample_valid = active;
        band_first = active && mode == MODE_SUM_BAND && sum_band_mod == 2'd0;
        band_last = active && mode == MODE_SUM_BAND && sum_band_mod == 2'd3;
        a_re = 18'sd64 + $signed({{2'b00, sample_index}});
        a_im = -18'sd51 - $signed({{2'b00, sample_index}});
        b_re = 18'sd32 + $signed({{2'b00, sample_index[14:0], 1'b0}});
        b_im = -18'sd21 - $signed({{2'b00, sample_index}});
        c_re = 18'sd67 + $signed({{2'b00, sample_index}});
        c_im = -18'sd47 - $signed({{2'b00, sample_index}});
        weight = 18'sd64 + $signed({{12'b0, sample_index[5:0]}});
        y_re = 18'sd7 + $signed({{15'b0, sample_index[2:0]}});
        y_im = -18'sd5 - $signed({{15'b0, sample_index[2:0]}});
    end

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            sidecar_start <= 1'b0;
            active <= 1'b0;
            sample_index <= 16'd0;
            checksum_reg <= 48'd0;
            done_reg <= 1'b0;
        end else begin
            sidecar_start <= 1'b0;
            if (start && !active) begin
                sidecar_start <= 1'b1;
                active <= 1'b1;
                sample_index <= 16'd0;
                checksum_reg <= 48'd0;
                done_reg <= 1'b0;
            end else if (active) begin
                if (valid) begin
                    checksum_reg <= checksum_reg + out_re[47:0] + out_im[47:0] + rho_out[47:0];
                end
                if (sample_index == 16'd{total_samples - 1}) begin
                    active <= 1'b0;
                    done_reg <= 1'b1;
                end else begin
                    sample_index <= sample_index + 16'd1;
                end
            end
        end
    end
endmodule
"""


def _integrated_vivado_impl_tcl(*, fpga_part: str, clock_period_ns: float) -> str:
    return f"""set_msg_config -id {{Common 17-55}} -new_severity {{INFO}}
read_verilog -sv qeic_real_integrated_combined_sidecar_rtl.sv
read_verilog -sv qeic_real_integrated_combined_sidecar_impl_top.sv
read_xdc vivado_impl.xdc
synth_design -top qeic_real_integrated_combined_sidecar_impl_top -part {fpga_part}
opt_design
place_design
route_design
report_utilization -file vivado_utilization.rpt
report_timing_summary -file vivado_timing_summary.rpt
write_checkpoint -force post_route.dcp
"""


def materialize_integrated_vivado_impl_project(
    specs: Sequence[Mapping[str, Any]],
    out_dir: Path,
    *,
    fpga_part: str = DEFAULT_FPGA_PART,
    clock_period_ns: float = 10.0,
) -> dict[str, Any]:
    """Materialize a Vivado implementation project for the integrated RTL sidecar."""

    by_id = {str(spec.get("architecture_id")): spec for spec in specs if spec.get("architecture_id")}
    hpsi = by_id.get("hybrid_hpsi_local_potential_v1", {})
    sum_band = by_id.get("hybrid_sum_band_density_accumulator_v1", {})
    axpy = by_id.get("hybrid_tiled_complex_axpy_v1", {})
    hpsi_samples = int(hpsi.get("golden_grid_points") or hpsi.get("golden_vector_length") or 96)
    sum_grid = int(sum_band.get("golden_grid_points") or 32)
    sum_bands = int(sum_band.get("golden_band_count") or 4)
    axpy_samples = int(axpy.get("golden_vector_length") or 64)
    component_samples = {
        "hpsi": hpsi_samples,
        "sum_band": sum_grid * sum_bands,
        "axpy": axpy_samples,
    }
    project_dir = Path(out_dir) / _INTEGRATED_SIDECAR_ID / "vivado_impl"
    project_dir.mkdir(parents=True, exist_ok=True)
    rtl_source = _integrated_vcs_rtl_source()
    wrapper_source = _integrated_vivado_impl_wrapper_source(
        hpsi_samples=hpsi_samples,
        sum_band_grid_points=sum_grid,
        sum_band_bands=sum_bands,
        axpy_samples=axpy_samples,
    )
    tcl_source = _integrated_vivado_impl_tcl(fpga_part=fpga_part, clock_period_ns=clock_period_ns)
    xdc_source = f"""create_clock -period {clock_period_ns:.3f} -name clk [get_ports clk]
set_false_path -from [get_ports reset_n]
"""
    rtl_sv = project_dir / "qeic_real_integrated_combined_sidecar_rtl.sv"
    wrapper_sv = project_dir / "qeic_real_integrated_combined_sidecar_impl_top.sv"
    vivado_impl_tcl = project_dir / "vivado_impl.tcl"
    vivado_impl_xdc = project_dir / "vivado_impl.xdc"
    rtl_sv.write_text(rtl_source, encoding="utf-8")
    wrapper_sv.write_text(wrapper_source, encoding="utf-8")
    vivado_impl_tcl.write_text(tcl_source, encoding="utf-8")
    vivado_impl_xdc.write_text(xdc_source, encoding="utf-8")
    return {
        "architecture_id": _INTEGRATED_SIDECAR_ID,
        "kernel_name": _INTEGRATED_SIDECAR_KERNEL,
        "top_module": "qeic_real_integrated_combined_sidecar_impl_top",
        "project_dir": str(project_dir),
        "rtl_sv": str(rtl_sv),
        "wrapper_sv": str(wrapper_sv),
        "vivado_impl_tcl": str(vivado_impl_tcl),
        "vivado_impl_xdc": str(vivado_impl_xdc),
        "rtl_hash": _sha256_text(rtl_source),
        "wrapper_hash": _sha256_text(wrapper_source),
        "tcl_hash": _sha256_text(tcl_source),
        "xdc_hash": _sha256_text(xdc_source),
        "samples": sum(component_samples.values()),
        "component_samples": component_samples,
        "fpga_part": fpga_part,
        "clock_period_ns": clock_period_ns,
        "claim_boundary": "Integrated RTL sidecar Vivado implementation project covering h_psi, sum_band, and AXPY motifs; not full QE kernel integration or board measurement.",
    }


def _integrated_pipelined_vivado_impl_wrapper_source(
    *,
    hpsi_samples: int,
    sum_band_grid_points: int,
    sum_band_bands: int,
    axpy_samples: int,
) -> str:
    return _integrated_vivado_impl_wrapper_source(
        hpsi_samples=hpsi_samples,
        sum_band_grid_points=sum_band_grid_points,
        sum_band_bands=sum_band_bands,
        axpy_samples=axpy_samples,
    ).replace(
        "qeic_real_integrated_combined_sidecar_impl_top",
        "qeic_real_integrated_pipelined_sidecar_impl_top",
    ).replace(
        "qeic_real_integrated_combined_sidecar_rtl",
        "qeic_real_integrated_pipelined_sidecar_rtl",
    )


def _integrated_pipelined_vivado_impl_tcl(*, fpga_part: str) -> str:
    return f"""set_msg_config -id {{Common 17-55}} -new_severity {{INFO}}
read_verilog -sv qeic_real_integrated_pipelined_sidecar_rtl.sv
read_verilog -sv qeic_real_integrated_pipelined_sidecar_impl_top.sv
read_xdc vivado_impl.xdc
synth_design -top qeic_real_integrated_pipelined_sidecar_impl_top -part {fpga_part}
opt_design
place_design
route_design
report_utilization -file vivado_utilization.rpt
report_timing_summary -file vivado_timing_summary.rpt
write_checkpoint -force post_route.dcp
"""


def materialize_integrated_pipelined_vivado_impl_project(
    specs: Sequence[Mapping[str, Any]],
    out_dir: Path,
    *,
    fpga_part: str = DEFAULT_FPGA_PART,
    clock_period_ns: float = 10.0,
) -> dict[str, Any]:
    """Materialize a Vivado implementation project for the pipelined integrated RTL sidecar."""

    by_id = {str(spec.get("architecture_id")): spec for spec in specs if spec.get("architecture_id")}
    hpsi = by_id.get("hybrid_hpsi_local_potential_v1", {})
    sum_band = by_id.get("hybrid_sum_band_density_accumulator_v1", {})
    axpy = by_id.get("hybrid_tiled_complex_axpy_v1", {})
    hpsi_samples = int(hpsi.get("golden_grid_points") or hpsi.get("golden_vector_length") or 96)
    sum_grid = int(sum_band.get("golden_grid_points") or 32)
    sum_bands = int(sum_band.get("golden_band_count") or 4)
    axpy_samples = int(axpy.get("golden_vector_length") or 64)
    component_samples = {
        "hpsi": hpsi_samples,
        "sum_band": sum_grid * sum_bands,
        "axpy": axpy_samples,
    }
    project_dir = Path(out_dir) / _PIPELINED_SIDECAR_ID / "vivado_impl"
    project_dir.mkdir(parents=True, exist_ok=True)
    rtl_source = _integrated_pipelined_vcs_rtl_source()
    wrapper_source = _integrated_pipelined_vivado_impl_wrapper_source(
        hpsi_samples=hpsi_samples,
        sum_band_grid_points=sum_grid,
        sum_band_bands=sum_bands,
        axpy_samples=axpy_samples,
    )
    tcl_source = _integrated_pipelined_vivado_impl_tcl(fpga_part=fpga_part)
    xdc_source = f"""create_clock -period {clock_period_ns:.3f} -name clk [get_ports clk]
set_false_path -from [get_ports reset_n]
"""
    rtl_sv = project_dir / "qeic_real_integrated_pipelined_sidecar_rtl.sv"
    wrapper_sv = project_dir / "qeic_real_integrated_pipelined_sidecar_impl_top.sv"
    vivado_impl_tcl = project_dir / "vivado_impl.tcl"
    vivado_impl_xdc = project_dir / "vivado_impl.xdc"
    rtl_sv.write_text(rtl_source, encoding="utf-8")
    wrapper_sv.write_text(wrapper_source, encoding="utf-8")
    vivado_impl_tcl.write_text(tcl_source, encoding="utf-8")
    vivado_impl_xdc.write_text(xdc_source, encoding="utf-8")
    return {
        "architecture_id": _PIPELINED_SIDECAR_ID,
        "kernel_name": _PIPELINED_SIDECAR_KERNEL,
        "top_module": "qeic_real_integrated_pipelined_sidecar_impl_top",
        "project_dir": str(project_dir),
        "rtl_sv": str(rtl_sv),
        "wrapper_sv": str(wrapper_sv),
        "vivado_impl_tcl": str(vivado_impl_tcl),
        "vivado_impl_xdc": str(vivado_impl_xdc),
        "rtl_hash": _sha256_text(rtl_source),
        "wrapper_hash": _sha256_text(wrapper_source),
        "tcl_hash": _sha256_text(tcl_source),
        "xdc_hash": _sha256_text(xdc_source),
        "samples": sum(component_samples.values()),
        "component_samples": component_samples,
        "pipeline_latency_cycles": _PIPELINED_SIDECAR_PIPELINE_LATENCY,
        "fpga_part": fpga_part,
        "clock_period_ns": clock_period_ns,
        "claim_boundary": "Pipelined integrated RTL sidecar Vivado implementation project covering h_psi, sum_band, and AXPY motifs; not full QE kernel integration or board measurement.",
    }


def _integrated_streaming_vivado_impl_wrapper_source(
    *,
    hpsi_samples: int,
    sum_band_grid_points: int,
    sum_band_bands: int,
    axpy_samples: int,
) -> str:
    return _integrated_vivado_impl_wrapper_source(
        hpsi_samples=hpsi_samples,
        sum_band_grid_points=sum_band_grid_points,
        sum_band_bands=sum_band_bands,
        axpy_samples=axpy_samples,
    ).replace(
        "qeic_real_integrated_combined_sidecar_impl_top",
        "qeic_real_integrated_streaming_pipeline_sidecar_impl_top",
    ).replace(
        "qeic_real_integrated_combined_sidecar_rtl",
        "qeic_real_integrated_streaming_pipeline_sidecar_rtl",
    )


def _integrated_streaming_vivado_impl_tcl(*, fpga_part: str) -> str:
    return f"""set_msg_config -id {{Common 17-55}} -new_severity {{INFO}}
read_verilog -sv qeic_real_integrated_streaming_pipeline_sidecar_rtl.sv
read_verilog -sv qeic_real_integrated_streaming_pipeline_sidecar_impl_top.sv
read_xdc vivado_impl.xdc
synth_design -top qeic_real_integrated_streaming_pipeline_sidecar_impl_top -part {fpga_part}
opt_design
place_design
route_design
report_utilization -file vivado_utilization.rpt
report_timing_summary -file vivado_timing_summary.rpt
write_checkpoint -force post_route.dcp
"""


def materialize_integrated_streaming_vivado_impl_project(
    specs: Sequence[Mapping[str, Any]],
    out_dir: Path,
    *,
    fpga_part: str = DEFAULT_FPGA_PART,
    clock_period_ns: float = 10.0,
) -> dict[str, Any]:
    """Materialize a Vivado implementation project for the II=1 streaming integrated RTL sidecar."""

    by_id = {str(spec.get("architecture_id")): spec for spec in specs if spec.get("architecture_id")}
    hpsi = by_id.get("hybrid_hpsi_local_potential_v1", {})
    sum_band = by_id.get("hybrid_sum_band_density_accumulator_v1", {})
    axpy = by_id.get("hybrid_tiled_complex_axpy_v1", {})
    hpsi_samples = int(hpsi.get("golden_grid_points") or hpsi.get("golden_vector_length") or 96)
    sum_grid = int(sum_band.get("golden_grid_points") or 32)
    sum_bands = int(sum_band.get("golden_band_count") or 4)
    axpy_samples = int(axpy.get("golden_vector_length") or 64)
    component_samples = {
        "hpsi": hpsi_samples,
        "sum_band": sum_grid * sum_bands,
        "axpy": axpy_samples,
    }
    project_dir = Path(out_dir) / _STREAMING_SIDECAR_ID / "vivado_impl"
    project_dir.mkdir(parents=True, exist_ok=True)
    rtl_source = _integrated_streaming_vcs_rtl_source()
    wrapper_source = _integrated_streaming_vivado_impl_wrapper_source(
        hpsi_samples=hpsi_samples,
        sum_band_grid_points=sum_grid,
        sum_band_bands=sum_bands,
        axpy_samples=axpy_samples,
    )
    tcl_source = _integrated_streaming_vivado_impl_tcl(fpga_part=fpga_part)
    xdc_source = f"""create_clock -period {clock_period_ns:.3f} -name clk [get_ports clk]
set_false_path -from [get_ports reset_n]
"""
    rtl_sv = project_dir / "qeic_real_integrated_streaming_pipeline_sidecar_rtl.sv"
    wrapper_sv = project_dir / "qeic_real_integrated_streaming_pipeline_sidecar_impl_top.sv"
    vivado_impl_tcl = project_dir / "vivado_impl.tcl"
    vivado_impl_xdc = project_dir / "vivado_impl.xdc"
    rtl_sv.write_text(rtl_source, encoding="utf-8")
    wrapper_sv.write_text(wrapper_source, encoding="utf-8")
    vivado_impl_tcl.write_text(tcl_source, encoding="utf-8")
    vivado_impl_xdc.write_text(xdc_source, encoding="utf-8")
    return {
        "architecture_id": _STREAMING_SIDECAR_ID,
        "kernel_name": _STREAMING_SIDECAR_KERNEL,
        "top_module": "qeic_real_integrated_streaming_pipeline_sidecar_impl_top",
        "project_dir": str(project_dir),
        "rtl_sv": str(rtl_sv),
        "wrapper_sv": str(wrapper_sv),
        "vivado_impl_tcl": str(vivado_impl_tcl),
        "vivado_impl_xdc": str(vivado_impl_xdc),
        "rtl_hash": _sha256_text(rtl_source),
        "wrapper_hash": _sha256_text(wrapper_source),
        "tcl_hash": _sha256_text(tcl_source),
        "xdc_hash": _sha256_text(xdc_source),
        "samples": sum(component_samples.values()),
        "component_samples": component_samples,
        "pipeline_latency_cycles": _STREAMING_SIDECAR_PIPELINE_LATENCY,
        "initiation_interval_cycles": 1,
        "fpga_part": fpga_part,
        "clock_period_ns": clock_period_ns,
        "claim_boundary": "Streaming II=1 integrated RTL sidecar Vivado implementation project covering h_psi, sum_band, and AXPY motifs; not full QE kernel integration or board measurement.",
    }


def materialize_vcs_rtl_project(spec: Mapping[str, Any], out_dir: Path) -> dict[str, Any]:
    """Materialize a non-HLS RTL/VCS project for a supported QE miniapp."""

    architecture_id = str(spec["architecture_id"])
    project_dir = Path(out_dir) / _safe_name(architecture_id) / "vcs_rtl"
    project_dir.mkdir(parents=True, exist_ok=True)
    if "hpsi" in architecture_id:
        samples = int(spec.get("golden_grid_points") or spec.get("golden_vector_length") or 96)
        rtl_source = _hpsi_vcs_rtl_source()
        tb_source = _hpsi_vcs_tb_source(samples)
        rtl_name = "qeic_real_hpsi_local_potential_rtl.sv"
        tb_name = "tb_qeic_real_hpsi_local_potential_rtl.sv"
    elif "sum_band" in architecture_id:
        ngrid = int(spec.get("golden_grid_points") or 32)
        nbands = int(spec.get("golden_band_count") or 4)
        samples = ngrid * nbands
        rtl_source = _sum_band_vcs_rtl_source()
        tb_source = _sum_band_vcs_tb_source(ngrid, nbands)
        rtl_name = "qeic_real_sum_band_density_accumulator_rtl.sv"
        tb_name = "tb_qeic_real_sum_band_density_accumulator_rtl.sv"
    elif "axpy" in architecture_id:
        samples = int(spec.get("golden_vector_length") or 64)
        rtl_source = _axpy_vcs_rtl_source()
        tb_source = _axpy_vcs_tb_source(samples)
        rtl_name = "qeic_real_tiled_complex_axpy_rtl.sv"
        tb_name = "tb_qeic_real_tiled_complex_axpy_rtl.sv"
    else:
        raise ValueError(f"VCS RTL materialization does not support architecture {architecture_id}")
    rtl_sv = project_dir / rtl_name
    tb_sv = project_dir / tb_name
    rtl_sv.write_text(rtl_source, encoding="utf-8")
    tb_sv.write_text(tb_source, encoding="utf-8")
    return {
        "architecture_id": architecture_id,
        "project_dir": str(project_dir),
        "rtl_sv": str(rtl_sv),
        "tb_sv": str(tb_sv),
        "rtl_hash": _sha256_text(rtl_source),
        "testbench_hash": _sha256_text(tb_source),
        "samples": samples,
    }


def parse_vcs_rtl_run_log(text: str) -> dict[str, Any]:
    """Parse the deterministic RTL/VCS run log emitted by the miniapp testbench."""

    if not text:
        return {"status": "missing", "rtl_status": None, "latency_cycles": None, "samples": None, "blockers": ["vcs_run_log_missing"]}
    pass_match = re.search(r"DSE_REAL_RTL_PASS\s+\S+\s+samples=(\d+)", text)
    fail_match = re.search(r"DSE_REAL_RTL_FAIL[^\n]*", text)
    latency_match = re.search(r"DSE_REAL_RTL_LATENCY_CYCLES\s+(\d+)", text)
    component_cycles = {
        match.group(1): {"samples": int(match.group(2)), "cycles": int(match.group(3))}
        for match in re.finditer(r"DSE_REAL_RTL_COMPONENT\s+([A-Za-z0-9_:+.-]+)\s+samples=(\d+)\s+cycles=(\d+)", text)
    }
    if pass_match and latency_match:
        parsed = {
            "status": "parsed",
            "rtl_status": "Pass",
            "latency_cycles": int(latency_match.group(1)),
            "samples": int(pass_match.group(1)),
            "blockers": [],
        }
        if component_cycles:
            parsed["component_cycles"] = component_cycles
        return parsed
    blockers: list[str] = []
    if fail_match:
        blockers.append("vcs_rtl_testbench_failed")
    if not pass_match:
        blockers.append("vcs_rtl_pass_marker_missing")
    if not latency_match:
        blockers.append("vcs_rtl_latency_missing")
    return {
        "status": "failed" if fail_match else "partial",
        "rtl_status": "Fail" if fail_match else None,
        "latency_cycles": int(latency_match.group(1)) if latency_match else None,
        "samples": int(pass_match.group(1)) if pass_match else None,
        "blockers": blockers,
    }


def merge_vcs_rtl_evidence_into_summary(summary: Mapping[str, Any], vcs_result: Mapping[str, Any]) -> dict[str, Any]:
    """Return a summary copy with VCS RTL evidence attached to the matching row."""

    merged = json.loads(json.dumps(summary))
    architecture_id = str(vcs_result.get("architecture_id") or "")
    evidence_rows = merged.get("evidence_rows")
    if not isinstance(evidence_rows, list):
        raise ValueError("summary does not contain evidence_rows list")
    matched = False
    for row in evidence_rows:
        if not isinstance(row, dict) or str(row.get("architecture_id") or "") != architecture_id:
            continue
        for key in (
            "vcs_attempted",
            "vcs_passed",
            "vcs_parsed",
            "vcs_command",
            "vcs_returncode",
            "vcs_compile_log_path",
            "vcs_run_log_path",
            "vcs_stdout_log_path",
            "vcs_stderr_log_path",
            "vcs_compile_log_hash",
            "vcs_run_log_hash",
            "vcs_stdout_log_hash",
            "vcs_stderr_log_hash",
            "vcs_evidence_json_path",
            "vcs_evidence_json_hash",
            "vcs_rtl_project",
            "claim_boundary",
        ):
            if key in vcs_result:
                row[key] = vcs_result[key]
        matched = True
        break
    if not matched:
        raise ValueError(f"no evidence row for VCS architecture {architecture_id}")
    return merged


def parse_vivado_impl_utilization_report(text: str) -> dict[str, Any]:
    """Parse Vivado post-route utilization report resource totals."""

    if not text:
        return {
            "status": "missing",
            "resource": {},
            "resource_available": {},
            "resource_utilization_percent": {},
            "resource_feasible": False,
            "blockers": ["vivado_impl_utilization_report_missing"],
        }
    resource: dict[str, int] = {}
    available: dict[str, int] = {}
    utilization_percent: dict[str, float] = {}
    resource_names = {
        "slice luts": "lut",
        "slice registers": "ff",
        "block ram tile": "bram_tile",
        "dsps": "dsp",
    }
    for line in text.splitlines():
        columns = _table_columns(line)
        if len(columns) < 4:
            continue
        name = columns[0].strip().lower()
        key = resource_names.get(name)
        if key is None:
            continue
        used = _parse_int_cell(columns[1])
        capacity = _parse_int_cell(columns[3])
        util = _parse_float(columns[4]) if len(columns) > 4 else None
        if used is not None:
            resource[key] = used
        if capacity is not None:
            available[key] = capacity
        if util is not None:
            utilization_percent[key] = util

    expected = {"lut", "ff", "bram_tile", "dsp"}
    missing = sorted(expected - set(resource))
    blockers = [f"vivado_impl_{name}_utilization_missing" for name in missing]
    resource_feasible = bool(resource) and not missing
    for key, used in resource.items():
        capacity = available.get(key)
        if isinstance(capacity, int) and used > capacity:
            resource_feasible = False
            blockers.append(f"vivado_impl_{key}_resource_infeasible")
    return {
        "status": "parsed" if not blockers else "partial",
        "resource": resource,
        "resource_available": available,
        "resource_utilization_percent": utilization_percent,
        "resource_feasible": resource_feasible,
        "blockers": blockers,
    }


def _next_numeric_line_values(lines: Sequence[str], start_index: int) -> list[float]:
    for raw_line in lines[start_index + 1 :]:
        line = raw_line.strip()
        if not line or set(line) <= {"-", " "}:
            continue
        columns = _table_columns(line)
        if columns:
            values = [_parse_float(column) for column in columns]
            parsed = [value for value in values if value is not None]
        else:
            parsed = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", line)]
        if parsed:
            return parsed
    return []


def parse_vivado_impl_timing_summary_report(text: str) -> dict[str, Any]:
    """Parse Vivado post-route timing summary status."""

    if not text:
        return {
            "status": "missing",
            "wns_ns": None,
            "tns_ns": None,
            "whs_ns": None,
            "ths_ns": None,
            "wpws_ns": None,
            "tpws_ns": None,
            "timing_met": False,
            "blockers": ["vivado_impl_timing_summary_missing"],
        }
    lines = text.splitlines()
    parsed: dict[str, Any] = {
        "status": "parsed",
        "wns_ns": None,
        "tns_ns": None,
        "whs_ns": None,
        "ths_ns": None,
        "wpws_ns": None,
        "tpws_ns": None,
        "timing_met": False,
        "blockers": [],
    }
    found_design_summary = False
    in_design_summary = False
    for index, line in enumerate(lines):
        lower = line.lower()
        if "design timing summary" in lower:
            in_design_summary = True
            continue
        if in_design_summary and ("clock summary" in lower or "intra clock table" in lower):
            break
        if not in_design_summary and (
            lower.lstrip().startswith("from clock")
            or lower.lstrip().startswith("path group")
            or lower.lstrip().startswith("clock ")
        ):
            continue
        if not in_design_summary and (parsed["wns_ns"] is not None or parsed["tns_ns"] is not None):
            continue
        if "wns(ns)" in lower and "tns(ns)" in lower:
            values = _next_numeric_line_values(lines, index)
            if len(values) < 2:
                continue
            parsed["wns_ns"] = values[0]
            parsed["tns_ns"] = values[1]
            if len(values) >= 6:
                parsed["whs_ns"] = values[4]
                parsed["ths_ns"] = values[5]
            if len(values) >= 10:
                parsed["wpws_ns"] = values[8]
                parsed["tpws_ns"] = values[9]
            found_design_summary = in_design_summary
            if found_design_summary:
                break
        elif "whs(ns)" in lower and "ths(ns)" in lower:
            values = _next_numeric_line_values(lines, index)
            if len(values) >= 2:
                parsed["whs_ns"] = values[0]
                parsed["ths_ns"] = values[1]
        elif "wpws(ns)" in lower and "tpws(ns)" in lower:
            values = _next_numeric_line_values(lines, index)
            if len(values) >= 2:
                parsed["wpws_ns"] = values[0]
                parsed["tpws_ns"] = values[1]

    if parsed["wns_ns"] is None or parsed["tns_ns"] is None:
        parsed["status"] = "partial"
        parsed["blockers"].append("vivado_impl_setup_timing_missing")
    else:
        parsed["timing_met"] = float(parsed["wns_ns"]) >= 0.0 and float(parsed["tns_ns"]) >= 0.0
        if not parsed["timing_met"]:
            parsed["blockers"].append("vivado_impl_setup_timing_not_met")
    if parsed["whs_ns"] is not None and float(parsed["whs_ns"]) < 0.0:
        parsed["timing_met"] = False
        parsed["blockers"].append("vivado_impl_hold_timing_not_met")
    if parsed["wpws_ns"] is not None and float(parsed["wpws_ns"]) < 0.0:
        parsed["timing_met"] = False
        parsed["blockers"].append("vivado_impl_pulse_width_timing_not_met")
    return parsed


def merge_integrated_vivado_impl_evidence_into_summary(summary: Mapping[str, Any], vivado_result: Mapping[str, Any]) -> dict[str, Any]:
    """Attach integrated Vivado implementation evidence while preserving claim boundaries."""

    merged = json.loads(json.dumps(summary))
    classification = merged.setdefault("classification", {})
    if not isinstance(classification, dict):
        raise ValueError("summary classification is not a JSON object")
    util = vivado_result.get("vivado_impl_utilization_parsed") if isinstance(vivado_result.get("vivado_impl_utilization_parsed"), Mapping) else {}
    timing = vivado_result.get("vivado_impl_timing_parsed") if isinstance(vivado_result.get("vivado_impl_timing_parsed"), Mapping) else {}
    impl_passed = vivado_result.get("vivado_impl_passed") is True
    resource_feasible = util.get("resource_feasible") is True
    timing_met = timing.get("timing_met") is True

    architecture_id = str(vivado_result.get("architecture_id") or _INTEGRATED_SIDECAR_ID)
    result_key = _INTEGRATED_VIVADO_RESULT_KEYS.get(architecture_id, "integrated_vivado_impl_result")
    merged[result_key] = json.loads(json.dumps(vivado_result))
    legacy_result = merged.get("integrated_vivado_impl_result")
    if isinstance(legacy_result, Mapping):
        legacy_architecture_id = str(legacy_result.get("architecture_id") or "")
        legacy_key = _INTEGRATED_VIVADO_RESULT_KEYS.get(legacy_architecture_id)
        if legacy_key and legacy_key != "integrated_vivado_impl_result" and legacy_key not in merged:
            merged[legacy_key] = json.loads(json.dumps(legacy_result))
    if architecture_id != _INTEGRATED_SIDECAR_ID and result_key != "integrated_vivado_impl_result":
        legacy_result = merged.get("integrated_vivado_impl_result")
        if isinstance(legacy_result, Mapping) and str(legacy_result.get("architecture_id") or "") != _INTEGRATED_SIDECAR_ID:
            merged.pop("integrated_vivado_impl_result", None)
    else:
        merged["integrated_vivado_impl_result"] = json.loads(json.dumps(vivado_result))

    integrated_results = [
        value
        for key in _INTEGRATED_VIVADO_RESULT_KEYS.values()
        if isinstance((value := merged.get(key)), Mapping)
    ]
    if not integrated_results and isinstance(merged.get("integrated_vivado_impl_result"), Mapping):
        integrated_results = [merged["integrated_vivado_impl_result"]]
    satisfying_results = [
        item
        for item in integrated_results
        if item.get("vivado_impl_passed") is True
        and isinstance(item.get("vivado_impl_utilization_parsed"), Mapping)
        and item["vivado_impl_utilization_parsed"].get("resource_feasible") is True
        and isinstance(item.get("vivado_impl_timing_parsed"), Mapping)
        and item["vivado_impl_timing_parsed"].get("timing_met") is True
    ]
    representative = satisfying_results[-1] if satisfying_results else vivado_result
    representative_util = (
        representative.get("vivado_impl_utilization_parsed")
        if isinstance(representative.get("vivado_impl_utilization_parsed"), Mapping)
        else util
    )
    representative_timing = (
        representative.get("vivado_impl_timing_parsed")
        if isinstance(representative.get("vivado_impl_timing_parsed"), Mapping)
        else timing
    )
    classification["integrated_vivado_impl_attempted"] = any(item.get("vivado_impl_attempted") is True for item in integrated_results)
    classification["integrated_vivado_impl_passed"] = bool(satisfying_results) or impl_passed
    classification["integrated_vivado_impl_resource_feasible"] = bool(satisfying_results) or resource_feasible
    classification["integrated_vivado_impl_timing_met"] = bool(satisfying_results) or timing_met
    classification["integrated_vivado_impl_resource"] = representative_util.get("resource")
    classification["integrated_vivado_impl_wns_ns"] = representative_timing.get("wns_ns")
    classification["integrated_vivado_impl_architecture_ids"] = sorted(
        {str(item.get("architecture_id")) for item in integrated_results if item.get("architecture_id")}
    )
    satisfied = set(str(item) for item in _as_list(classification.get("satisfied_preliminary_gates")))
    if impl_passed:
        satisfied.add("vivado_impl_executed")
    if resource_feasible:
        satisfied.add("vivado_impl_resource_feasible")
    if timing_met:
        satisfied.add("vivado_impl_timing_met")
    classification["satisfied_preliminary_gates"] = sorted(satisfied)
    blockers = set(str(item) for item in _as_list(classification.get("blockers")))
    for blocker in _as_list(util.get("blockers")) + _as_list(timing.get("blockers")) + _as_list(vivado_result.get("blockers")):
        if blocker:
            blockers.add(str(blocker))
    classification["blockers"] = sorted(blockers)
    classification["final_claim_allowed"] = False
    boundary = str(vivado_result.get("claim_boundary") or "")
    if boundary:
        merged["claim_boundary"] = boundary
        classification["claim_boundary"] = (
            boundary
            + " Current conclusion remains bounded by full QE kernel integration and physical FPGA board measurement gates."
        )
    return merged


def _first_ints(line: str) -> list[int]:
    return [int(value) for value in re.findall(r"(?<![A-Za-z0-9_])-?\d+(?![A-Za-z0-9_])", line)]


def _table_columns(line: str) -> list[str]:
    if "|" not in line:
        return []
    return [part.strip() for part in line.strip().strip("|").split("|")]


def _parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int_cell(value: str) -> int | None:
    text = value.strip()
    if text in {"", "?", "-"}:
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return None


def _parse_resource_cell(value: str) -> int:
    parsed = _parse_int_cell(value)
    return 0 if parsed is None else parsed


def _parse_clock_summary(text: str) -> tuple[float, float] | None:
    in_timing = False
    for line in text.splitlines():
        lower = line.lower()
        if "timing (ns)" in lower:
            in_timing = True
            continue
        if in_timing and "latency (clock cycles)" in lower:
            break
        if not in_timing:
            continue
        columns = _table_columns(line)
        if len(columns) < 3:
            continue
        if any("clock" in column.lower() for column in columns):
            continue
        target = _parse_float(columns[1])
        estimated = _parse_float(columns[2])
        if target is not None and estimated is not None:
            return target, estimated
    return None


def _parse_latency_summary(text: str) -> tuple[int, int, int, int] | None:
    in_latency = False
    for line in text.splitlines():
        lower = line.lower()
        if "latency (clock cycles)" in lower:
            in_latency = True
            continue
        if in_latency and "utilization estimates" in lower:
            break
        if not in_latency:
            continue
        columns = _table_columns(line)
        if len(columns) < 5:
            continue
        # Vivado 2019.1 summary row: | min | max | min | max | Type |
        latency_min = _parse_int_cell(columns[0])
        latency_max = _parse_int_cell(columns[1])
        interval_min = _parse_int_cell(columns[2])
        interval_max = _parse_int_cell(columns[3])
        if None not in (latency_min, latency_max, interval_min, interval_max):
            return int(latency_min), int(latency_max), int(interval_min), int(interval_max)
        # Older/wider report fixture: columns may contain absolute latency before interval.
        if len(columns) >= 7:
            latency_min = _parse_int_cell(columns[0])
            latency_max = _parse_int_cell(columns[1])
            interval_min = _parse_int_cell(columns[4])
            interval_max = _parse_int_cell(columns[5])
            if None not in (latency_min, latency_max, interval_min, interval_max):
                return int(latency_min), int(latency_max), int(interval_min), int(interval_max)
    return None


def _parse_loop_detail(text: str) -> tuple[int, int, int | None] | None:
    in_latency = False
    for line in text.splitlines():
        lower = line.lower()
        if "latency (clock cycles)" in lower:
            in_latency = True
            continue
        if in_latency and "utilization estimates" in lower:
            break
        if not in_latency:
            continue
        columns = _table_columns(line)
        if not columns or not columns[0].lstrip("-").strip().lower().startswith("loop"):
            continue
        if len(columns) < 7:
            continue
        iteration_latency = _parse_int_cell(columns[3])
        achieved_ii = _parse_int_cell(columns[4])
        trip_count = _parse_int_cell(columns[6])
        if iteration_latency is not None and achieved_ii is not None:
            return int(iteration_latency), int(achieved_ii), trip_count
    return None


def _parse_resource_row(columns: Sequence[str]) -> dict[str, int]:
    values = list(columns)[-5:]
    return {
        "bram_18k": _parse_resource_cell(values[0]),
        "dsp48e": _parse_resource_cell(values[1]),
        "ff": _parse_resource_cell(values[2]),
        "lut": _parse_resource_cell(values[3]),
        "uram": _parse_resource_cell(values[4]),
    }


def _parse_resource_table(text: str) -> tuple[dict[str, int] | None, dict[str, int] | None]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        columns = _table_columns(line)
        normalized = [column.lower() for column in columns]
        if not {"bram_18k", "dsp48e", "ff", "lut"}.issubset(set(normalized)):
            continue
        candidate: dict[str, int] | None = None
        total: dict[str, int] | None = None
        available: dict[str, int] | None = None
        for data_line in lines[index + 1 : index + 20]:
            data_columns = _table_columns(data_line)
            if len(data_columns) < 5:
                continue
            label = data_columns[0].strip().lower()
            values = data_columns[-5:]
            if not any(_parse_int_cell(value) is not None for value in values):
                continue
            parsed = _parse_resource_row(values)
            if label == "total":
                total = parsed
            elif label == "available":
                available = parsed
            elif candidate is None:
                candidate = parsed
        return total or candidate, available
    return None, None


def _parse_resource_summary(text: str) -> dict[str, int] | None:
    resource, _available = _parse_resource_table(text)
    return resource


def _resource_feasible(resource: Mapping[str, int], available: Mapping[str, int]) -> bool:
    for key, value in resource.items():
        limit = available.get(key)
        if limit is None:
            continue
        if limit == 0:
            if value > 0:
                return False
        elif value > limit:
            return False
    return True


def parse_vivado_hls_csynth_report(text: str, *, fallback_trip_count: int | None = None) -> dict[str, Any]:
    """Parse the subset of Vivado HLS csynth report needed for comparison.

    Vivado-HLS 2019.1 often reports top-level latency as ``?`` for kernels whose
    loop bound is a runtime argument.  In that case, use loop-detail iteration
    latency plus achieved II with the benchmark golden trip count as a bounded
    campaign estimate: ``iteration_latency + (trip_count - 1) * II``.
    """

    parsed: dict[str, Any] = {"status": "parsed", "blockers": []}
    clock = _parse_clock_summary(text)
    if clock is not None:
        parsed["target_clock_ns"] = clock[0]
        parsed["estimated_clock_ns"] = clock[1]
    else:
        parsed["blockers"].append("hls_clock_summary_missing")

    latency = _parse_latency_summary(text)
    if latency is not None:
        parsed["latency_cycles_min"] = latency[0]
        parsed["latency_cycles_max"] = latency[1]
        parsed["interval_cycles_min"] = latency[2]
        parsed["interval_cycles_max"] = latency[3]
    else:
        loop_detail = _parse_loop_detail(text)
        if loop_detail is not None:
            iteration_latency, achieved_ii, report_trip_count = loop_detail
            trip_count = report_trip_count if report_trip_count is not None else fallback_trip_count
            parsed["loop_iteration_latency_cycles"] = iteration_latency
            parsed["loop_achieved_ii_cycles"] = achieved_ii
            if report_trip_count is not None:
                parsed["loop_report_trip_count"] = report_trip_count
            if trip_count is not None and trip_count > 0:
                estimated_latency = iteration_latency + max(0, trip_count - 1) * achieved_ii
                estimated_interval = trip_count * achieved_ii
                parsed["latency_cycles_min"] = estimated_latency
                parsed["latency_cycles_max"] = estimated_latency
                parsed["interval_cycles_min"] = estimated_interval
                parsed["interval_cycles_max"] = estimated_interval
                parsed["latency_estimate_source"] = "loop_detail_fallback_trip_count"
                parsed["latency_estimate_trip_count"] = trip_count
            else:
                parsed["blockers"].append("hls_latency_summary_missing")
                parsed["blockers"].append("hls_loop_trip_count_required_for_latency_estimate")
        else:
            parsed["blockers"].append("hls_latency_summary_missing")

    resource, available = _parse_resource_table(text)
    if resource is not None:
        parsed["resource"] = resource
        if available is not None:
            parsed["resource_available"] = available
            parsed["resource_feasible"] = _resource_feasible(resource, available)
            if parsed["resource_feasible"] is False:
                parsed["blockers"].append("hls_resource_infeasible")
    else:
        parsed["blockers"].append("hls_resource_summary_missing")
    if parsed["blockers"]:
        parsed["status"] = "partial"
    return parsed



def parse_vivado_hls_cosim_report(text: str) -> dict[str, Any]:
    """Parse Vivado-HLS C/RTL cosim report status and Verilog latency."""

    parsed: dict[str, Any] = {"status": "missing", "blockers": ["cosim_report_missing"]}
    if not text.strip():
        return parsed
    for line in text.splitlines():
        columns = _table_columns(line)
        if len(columns) < 5:
            continue
        rtl = columns[0].strip()
        status = columns[1].strip()
        if rtl.lower() not in {"verilog", "vhdl"}:
            continue
        latency_min = _parse_int_cell(columns[2])
        latency_avg = _parse_int_cell(columns[3])
        latency_max = _parse_int_cell(columns[4])
        if status.lower() == "pass" and None not in (latency_min, latency_avg, latency_max):
            return {
                "status": "parsed",
                "blockers": [],
                "rtl": rtl,
                "rtl_status": status,
                "latency_cycles_min": int(latency_min),
                "latency_cycles_avg": int(latency_avg),
                "latency_cycles_max": int(latency_max),
            }
        if status and status.upper() != "NA":
            return {
                "status": "failed",
                "blockers": ["cosim_report_status_not_pass"],
                "rtl": rtl,
                "rtl_status": status,
            }
    return {"status": "partial", "blockers": ["cosim_verilog_pass_latency_missing"]}



_QE_TIMER_RE = re.compile(
    r"^\s*([A-Za-z0-9_*:.+-]+)\s*:\s*([0-9]+(?:\.[0-9]+)?)s\s+CPU\s+([0-9]+(?:\.[0-9]+)?)s\s+WALL(?:\s*\(\s*([0-9]+)\s+calls?\))?",
)

_MOTIF_TIMER_MAP: dict[str, list[str]] = {
    "reduction_collective": ["sum_band"],
    "sum_band_density_accumulation": ["sum_band"],
    "h_psi_local_potential": ["h_psi"],
    "wavefunction_memory": ["mix_rho", "h_psi:calbec", "calbec"],
    "fft_transpose": ["fft", "ffts", "fftw"],
}


def parse_qe_timer_stdout(text: str) -> dict[str, Any]:
    """Extract QE full-SCF routine wall timers from a PWSCF stdout log."""

    routines: dict[str, dict[str, Any]] = {}
    pwscf_cpu: float | None = None
    pwscf_wall: float | None = None
    for line in text.splitlines():
        match = _QE_TIMER_RE.match(line)
        if not match:
            continue
        name = match.group(1)
        cpu_seconds = float(match.group(2))
        wall_seconds = float(match.group(3))
        calls = int(match.group(4)) if match.group(4) is not None else None
        if name == "PWSCF":
            pwscf_cpu = cpu_seconds
            pwscf_wall = wall_seconds
            continue
        routines[name] = {
            "cpu_seconds": cpu_seconds,
            "wall_seconds": wall_seconds,
            "calls": calls,
        }
    return {
        "pwscf_cpu_seconds": pwscf_cpu,
        "pwscf_wall_seconds": pwscf_wall,
        "routines": routines,
    }


def _mean(values: Sequence[float]) -> float | None:
    clean = [float(value) for value in values if isinstance(value, (int, float))]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _clock_ns_from_row(row: Mapping[str, Any]) -> float | None:
    parsed = row.get("csynth_parsed") if isinstance(row.get("csynth_parsed"), Mapping) else {}
    clock_ns = parsed.get("estimated_clock_ns") or parsed.get("target_clock_ns") if isinstance(parsed, Mapping) else None
    if not isinstance(clock_ns, (int, float)):
        return None
    return float(clock_ns)


def _trace_replay_latency_candidates(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    clock_ns = _clock_ns_from_row(row)
    if clock_ns is None:
        return []
    candidates: list[dict[str, Any]] = []
    fields = _performance_latency_fields(row)
    latency = fields.get("performance_latency_cycles_max")
    source = str(fields.get("performance_latency_source") or "missing")
    if isinstance(latency, (int, float)) and source != "missing":
        candidates.append(
            {
                "latency_source": source,
                "latency_cycles": int(latency),
                "clock_ns": clock_ns,
                "kernel_seconds": float(clock_ns) * float(latency) * 1.0e-9,
                "status": "trace_replay_optimistic",
                "claim_boundary": "Optimistic trace replay of measured QE timers using real HLS C/RTL cosim or C-synth latency; compact miniapp/routine evidence still requires full QE integration before final claims.",
            }
        )
    vcs = row.get("vcs_parsed") if isinstance(row.get("vcs_parsed"), Mapping) else {}
    vcs_latency = vcs.get("latency_cycles") if isinstance(vcs, Mapping) else None
    if row.get("vcs_passed") is True and isinstance(vcs_latency, (int, float)):
        candidates.append(
            {
                "latency_source": "vcs_rtl",
                "latency_cycles": int(vcs_latency),
                "clock_ns": clock_ns,
                "kernel_seconds": float(clock_ns) * float(vcs_latency) * 1.0e-9,
                "status": "trace_replay_vcs_rtl_sensitivity",
                "claim_boundary": "VCS RTL latency sensitivity over measured QE timer traces; standalone handwritten RTL miniapp evidence is not full-QE integration, board measurement, or final FPGA superiority evidence.",
            }
        )
    return candidates


def _microkernel_seconds(row: Mapping[str, Any]) -> float | None:
    candidates = _trace_replay_latency_candidates(row)
    if not candidates:
        return None
    return float(candidates[0]["kernel_seconds"])


def _performance_latency_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    cosim = row.get("cosim_parsed") if isinstance(row.get("cosim_parsed"), Mapping) else {}
    csynth = row.get("csynth_parsed") if isinstance(row.get("csynth_parsed"), Mapping) else {}
    if isinstance(cosim.get("latency_cycles_max"), (int, float)):
        return {
            "performance_latency_source": "vivado_hls_cosim",
            "performance_latency_cycles_max": cosim.get("latency_cycles_max"),
        }
    if isinstance(csynth.get("latency_cycles_max"), (int, float)):
        return {
            "performance_latency_source": "vivado_hls_csynth",
            "performance_latency_cycles_max": csynth.get("latency_cycles_max"),
        }
    return {
        "performance_latency_source": "missing",
        "performance_latency_cycles_max": None,
    }


def render_real_hybrid_hls_report(summary: Mapping[str, Any]) -> str:
    """Render a reproducible markdown summary for the real-HLS campaign."""

    classification = summary.get("classification") if isinstance(summary.get("classification"), Mapping) else {}
    evidence_rows = [row for row in _as_list(summary.get("evidence_rows")) if isinstance(row, Mapping)]
    lines: list[str] = []
    lines.append("# Real Hybrid HLS Evidence Campaign Summary")
    lines.append("")
    lines.append(f"- Preliminary label: `{classification.get('preliminary_label')}`")
    lines.append(f"- Confidence: `{classification.get('confidence')}`")
    lines.append(f"- Final hardware claim allowed: `{classification.get('final_claim_allowed')}`")
    if classification.get("best_architecture_id"):
        lines.append(f"- Best architecture: `{classification.get('best_architecture_id')}`")
    if classification.get("best_speedup_vs_gpu_mean") is not None:
        lines.append(f"- Best optimistic trace-replay speedup vs GPU: `{float(classification.get('best_speedup_vs_gpu_mean')):.6g}x`")
    if classification.get("best_vivado_implemented_architecture_id"):
        lines.append(f"- Best Vivado-implemented architecture: `{classification.get('best_vivado_implemented_architecture_id')}`")
    if classification.get("best_vivado_implemented_speedup_vs_gpu_mean") is not None:
        lines.append(
            f"- Best Vivado-implemented trace-replay speedup vs GPU: `{float(classification.get('best_vivado_implemented_speedup_vs_gpu_mean')):.6g}x`"
        )
    if classification.get("resource_infeasible_architecture_ids"):
        lines.append(
            "- Resource-infeasible architectures filtered: `"
            + ", ".join(str(item) for item in _as_list(classification.get("resource_infeasible_architecture_ids")))
            + "`"
        )
    if summary.get("claim_closure_path"):
        lines.append(f"- Claim closure audit: `{summary.get('claim_closure_path')}`")
    impl_result: Mapping[str, Any] = {}
    best_impl_architecture = str(classification.get("best_vivado_implemented_architecture_id") or "")
    if best_impl_architecture:
        best_impl_key = _INTEGRATED_VIVADO_RESULT_KEYS.get(best_impl_architecture)
        if best_impl_key and isinstance(summary.get(best_impl_key), Mapping):
            impl_result = summary[best_impl_key]
    if not impl_result:
        impl_candidates = [
            value
            for key in _INTEGRATED_VIVADO_RESULT_KEYS.values()
            if isinstance((value := summary.get(key)), Mapping) and value.get("vivado_impl_passed") is True
        ]
        impl_result = impl_candidates[-1] if impl_candidates else {}
    if impl_result:
        impl_util = impl_result.get("vivado_impl_utilization_parsed") if isinstance(impl_result.get("vivado_impl_utilization_parsed"), Mapping) else {}
        impl_timing = impl_result.get("vivado_impl_timing_parsed") if isinstance(impl_result.get("vivado_impl_timing_parsed"), Mapping) else {}
        impl_resource = impl_util.get("resource") if isinstance(impl_util.get("resource"), Mapping) else {}
        lines.append(
            "- Integrated Vivado implementation: "
            f"`{impl_result.get('architecture_id')}` passed `{impl_result.get('vivado_impl_passed')}`, "
            f"WNS `{impl_timing.get('wns_ns')}` ns, "
            f"implemented clock `{impl_result.get('implemented_clock_ns')}` ns, "
            f"LUT `{impl_resource.get('lut')}`, FF `{impl_resource.get('ff')}`, "
            f"BRAM tile `{impl_resource.get('bram_tile')}`, DSP `{impl_resource.get('dsp')}`"
        )
    lines.append("")
    lines.append("## Direct answer")
    lines.append("")
    lines.append(
        "The current non-stub hybrid FPGA/HLS evidence supports **FPGA/hybrid weaker / not superior to the GPU baseline** for claim purposes unless all hard gates pass. The evidence includes real HLS kernels and Vivado-HLS C/RTL co-simulation, but miniapps and sidecar motifs are not final full-QE integration evidence."
    )
    lines.append("")
    lines.append("## Evidence gates")
    lines.append("")
    for row in evidence_rows:
        parsed = row.get("csynth_parsed") if isinstance(row.get("csynth_parsed"), Mapping) else {}
        cosim = row.get("cosim_parsed") if isinstance(row.get("cosim_parsed"), Mapping) else {}
        resource = parsed.get("resource") if isinstance(parsed.get("resource"), Mapping) else {}
        perf_source = row.get("performance_latency_source") or _performance_latency_fields(row).get("performance_latency_source")
        perf_latency = row.get("performance_latency_cycles_max") or _performance_latency_fields(row).get("performance_latency_cycles_max")
        lines.append(f"- `{row.get('architecture_id')}`")
        lines.append(
            f"  - Coverage: `{row.get('implementation_coverage')}`; mapped timers: `"
            + ", ".join(str(item) for item in _as_list(row.get("mapped_qe_timer_names")))
            + "`"
        )
        lines.append(f"  - C-sim golden: `{row.get('csim_passed')}`")
        lines.append(
            f"  - C-synth parsed: `{parsed.get('status')}`, latency `{parsed.get('latency_cycles_max')}` cycles, estimated clock `{parsed.get('estimated_clock_ns')}` ns"
        )
        lines.append(f"  - Verilog C/RTL cosim: `{row.get('cosim_passed')}`, latency `{cosim.get('latency_cycles_max')}` cycles")
        if row.get("vcs_attempted") or row.get("vcs_passed"):
            vcs = row.get("vcs_parsed") if isinstance(row.get("vcs_parsed"), Mapping) else {}
            lines.append(
                f"  - VCS RTL sim: `{row.get('vcs_passed')}`, latency `{vcs.get('latency_cycles')}` cycles, samples `{vcs.get('samples')}`"
            )
        lines.append(f"  - Performance latency source: `{perf_source}`, latency `{perf_latency}` cycles")
        lines.append(
            f"  - Resource feasible on target: `{parsed.get('resource_feasible')}`; BRAM18K `{resource.get('bram_18k')}`, DSP `{resource.get('dsp48e')}`, FF `{resource.get('ff')}`, LUT `{resource.get('lut')}`, URAM `{resource.get('uram')}`"
        )
        if parsed.get("blockers"):
            lines.append("  - HLS blockers: `" + ", ".join(str(item) for item in _as_list(parsed.get("blockers"))) + "`")
    lines.append("")
    lines.append("## Workflow accounting result")
    lines.append("")
    lines.append(
        "Trace replay used measured QE full-SCF timer logs from `artifacts/qe_ic_7day_prelim/runs/<case>/gpu_only_baseline/run_*.stdout.log` plus real HLS C/RTL cosim latency; rows with handwritten RTL evidence also include a VCS RTL latency-sensitivity channel. Rows marked `partial_sidecar_motif` or `qe_routine_equivalent_miniapp` are not final full-QE integration evidence."
    )
    lines.append("")
    comparisons = [row for row in _as_list(classification.get("architecture_comparisons")) if isinstance(row, Mapping)]
    if comparisons:
        lines.append("| Architecture | Case | Latency source | Mapped QE timers | Speedup | Status | Coverage |")
        lines.append("| --- | --- | --- | --- | ---: | --- | --- |")
        for comparison in comparisons:
            timers = ", ".join(str(item) for item in _as_list(comparison.get("mapped_timer_names")))
            speedup = float(comparison.get("speedup_vs_gpu_mean") or 0.0)
            lines.append(
                f"| `{comparison.get('architecture_id')}` | `{comparison.get('case_id')}` | `{comparison.get('latency_source')}` | `{timers}` | {speedup:.4f}x | `{comparison.get('workflow_accounting_status')}` | `{comparison.get('implementation_coverage')}` |"
            )
    else:
        lines.append("No claimable case-matched workflow comparison rows survived the hard gates.")
    if impl_result:
        impl_util = impl_result.get("vivado_impl_utilization_parsed") if isinstance(impl_result.get("vivado_impl_utilization_parsed"), Mapping) else {}
        impl_timing = impl_result.get("vivado_impl_timing_parsed") if isinstance(impl_result.get("vivado_impl_timing_parsed"), Mapping) else {}
        impl_resource = impl_util.get("resource") if isinstance(impl_util.get("resource"), Mapping) else {}
        lines.append("")
        lines.append("## Integrated Vivado implementation evidence")
        lines.append("")
        lines.append(
            "This is post-synthesis/place/route FPGA implementation evidence for the single integrated RTL sidecar. "
            "It improves hardware feasibility evidence, but it is still not physical board measurement and not full QE kernel integration."
        )
        lines.append("")
        lines.append(f"- Passed: `{impl_result.get('vivado_impl_passed')}`")
        lines.append(f"- Timing met: `{impl_timing.get('timing_met')}`; WNS `{impl_timing.get('wns_ns')}` ns; TNS `{impl_timing.get('tns_ns')}` ns")
        lines.append(
            f"- Resource feasible: `{impl_util.get('resource_feasible')}`; LUT `{impl_resource.get('lut')}`, "
            f"FF `{impl_resource.get('ff')}`, BRAM tile `{impl_resource.get('bram_tile')}`, DSP `{impl_resource.get('dsp')}`"
        )
        if impl_result.get("vivado_impl_evidence_json_path"):
            lines.append(f"- Evidence JSON: `{impl_result.get('vivado_impl_evidence_json_path')}`")
    lines.append("")
    lines.append("## Claim boundary")
    lines.append("")
    lines.append(str(classification.get("claim_boundary") or "unknown"))
    lines.append("")
    lines.append("Blockers:")
    for blocker in _as_list(classification.get("blockers")):
        lines.append(f"- `{blocker}`")
    lines.append("")
    lines.append(
        "Therefore this artifact improves the evidence chain beyond generated stubs/proxies and includes a QE-routine miniapp when present, but it still does not allow final hardware superiority or fundamental no-opportunity wording without full QE integration and board/implementation closure."
    )
    return "\n".join(lines) + "\n"


def build_trace_replay_workflow_accounting(
    gpu_baseline: Mapping[str, Any],
    gpu_runs_root: Path,
    row: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Build optimistic full-SCF trace-replay accounting from measured QE timers.

    This is intentionally labelled as partial-sidecar trace replay: it uses real
    QE full-SCF routine timers and real HLS C/RTL cosim latency, but it does not
    prove that the compact sidecar kernel is a full QE kernel replacement.
    """

    motif_id = str(row.get("motif_id") or "")
    timer_names = list(row.get("mapped_qe_timer_names") or _MOTIF_TIMER_MAP.get(motif_id, []))
    implementation_coverage = str(row.get("implementation_coverage") or "partial_sidecar_motif")
    latency_candidates = _trace_replay_latency_candidates(row)
    records = [record for record in _as_list(gpu_baseline.get("baseline_records")) if isinstance(record, Mapping)]
    accountings: list[dict[str, Any]] = []
    for record in records:
        case_id = str(record.get("case_id") or "")
        gpu_runtime = record.get("runtime_seconds_mean")
        if not case_id or not isinstance(gpu_runtime, (int, float)):
            continue
        stdout_paths = sorted((gpu_runs_root / case_id / "gpu_only_baseline").glob("run_*.stdout.log"))
        if not stdout_paths:
            accountings.append(
                {
                    "status": "missing_qe_timer_trace",
                    "case_id": case_id,
                    "blockers": ["qe_stdout_timer_logs_missing"],
                    "implementation_coverage": implementation_coverage,
                }
            )
            continue
        parsed_logs = [parse_qe_timer_stdout(path.read_text(encoding="utf-8", errors="replace")) for path in stdout_paths]
        routine_means: dict[str, float] = {}
        routine_call_means: dict[str, float] = {}
        for timer_name in timer_names:
            walls: list[float] = []
            calls: list[float] = []
            for parsed_log in parsed_logs:
                routine = parsed_log["routines"].get(timer_name)
                if not isinstance(routine, Mapping):
                    continue
                if isinstance(routine.get("wall_seconds"), (int, float)):
                    walls.append(float(routine["wall_seconds"]))
                if isinstance(routine.get("calls"), (int, float)):
                    calls.append(float(routine["calls"]))
            mean_wall = _mean(walls)
            if mean_wall is not None:
                routine_means[timer_name] = mean_wall
            mean_calls = _mean(calls)
            if mean_calls is not None:
                routine_call_means[timer_name] = mean_calls
        mapped_timer_names = [name for name in timer_names if name in routine_means]
        replaceable_seconds = sum(routine_means.values())
        if not mapped_timer_names or not latency_candidates:
            accountings.append(
                {
                    "status": "missing_trace_replay_inputs",
                    "case_id": case_id,
                    "mapped_timer_names": mapped_timer_names,
                    "blockers": ["mapped_qe_timer_or_hls_latency_missing"],
                    "implementation_coverage": implementation_coverage,
                }
            )
            continue
        transaction_count = max(1.0, sum(routine_call_means.get(name, 1.0) for name in mapped_timer_names))
        pwscf_wall = _mean(
            [parsed_log.get("pwscf_wall_seconds") for parsed_log in parsed_logs if isinstance(parsed_log.get("pwscf_wall_seconds"), (int, float))]
        )
        electrons_wall = _mean(
            [
                parsed_log["routines"].get("electrons", {}).get("wall_seconds")
                for parsed_log in parsed_logs
                if isinstance(parsed_log["routines"].get("electrons", {}).get("wall_seconds"), (int, float))
            ]
        )
        scf_control = max(float(gpu_runtime) - float(electrons_wall), 0.0) if electrons_wall is not None else max(float(gpu_runtime) - float(pwscf_wall or gpu_runtime), 0.0)
        for latency_candidate in latency_candidates:
            kernel_seconds = float(latency_candidate["kernel_seconds"])
            fpga_compute_seconds = kernel_seconds * transaction_count
            launch_overhead = 0.00005 * transaction_count
            host_device_transfer = 0.00005 * transaction_count
            synchronization = 0.00005 * transaction_count
            cpu_retained = max(float(gpu_runtime) - replaceable_seconds, 0.0)
            hybrid_runtime = cpu_retained + fpga_compute_seconds + launch_overhead + host_device_transfer + synchronization
            accountings.append(
                {
                    "status": latency_candidate["status"],
                    "case_id": case_id,
                    "source_gpu_runtime_seconds_mean": float(gpu_runtime),
                    "qe_pwscf_wall_seconds_mean": pwscf_wall,
                    "mapped_timer_names": mapped_timer_names,
                    "mapped_timer_wall_seconds_mean": routine_means,
                    "mapped_timer_call_count_mean": routine_call_means,
                    "replaceable_seconds_mean": replaceable_seconds,
                    "latency_source": latency_candidate["latency_source"],
                    "fpga_latency_cycles_per_transaction": latency_candidate["latency_cycles"],
                    "fpga_clock_ns": latency_candidate["clock_ns"],
                    "fpga_kernel_seconds_per_transaction": kernel_seconds,
                    "fpga_transaction_count_estimate": transaction_count,
                    "fpga_compute_seconds": fpga_compute_seconds,
                    "scf_control_seconds": scf_control,
                    "cpu_retained_seconds": cpu_retained,
                    "host_device_transfer_seconds": host_device_transfer,
                    "synchronization_seconds": synchronization,
                    "launch_overhead_seconds": launch_overhead,
                    "hybrid_workflow_runtime_seconds": hybrid_runtime,
                    "implementation_coverage": implementation_coverage,
                    "blockers": [] if implementation_coverage == "full_qe_kernel_equivalent" else ["full_qe_kernel_equivalent_missing"],
                    "timer_trace_paths": [str(path) for path in stdout_paths],
                    "claim_boundary": latency_candidate["claim_boundary"],
                }
            )
    return accountings


def build_combined_vcs_sidecar_accounting(
    gpu_baseline: Mapping[str, Any],
    gpu_runs_root: Path,
    evidence_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build a combined VCS-RTL sidecar trace replay across multiple motifs."""

    components: list[dict[str, Any]] = []
    for row in evidence_rows:
        if row.get("vcs_passed") is not True:
            continue
        clock_ns = _clock_ns_from_row(row)
        vcs = row.get("vcs_parsed") if isinstance(row.get("vcs_parsed"), Mapping) else {}
        latency = vcs.get("latency_cycles") if isinstance(vcs, Mapping) else None
        if not isinstance(clock_ns, (int, float)) or not isinstance(latency, (int, float)):
            continue
        timer_names = list(row.get("mapped_qe_timer_names") or _MOTIF_TIMER_MAP.get(str(row.get("motif_id") or ""), []))
        if not timer_names:
            continue
        components.append(
            {
                "architecture_id": row.get("architecture_id"),
                "mapped_timer_names": timer_names,
                "latency_cycles": int(latency),
                "clock_ns": float(clock_ns),
                "kernel_seconds": float(clock_ns) * float(latency) * 1.0e-9,
            }
        )
    if len(components) < 2:
        return []

    records = [record for record in _as_list(gpu_baseline.get("baseline_records")) if isinstance(record, Mapping)]
    accountings: list[dict[str, Any]] = []
    for record in records:
        case_id = str(record.get("case_id") or "")
        gpu_runtime = record.get("runtime_seconds_mean")
        if not case_id or not isinstance(gpu_runtime, (int, float)):
            continue
        stdout_paths = sorted((gpu_runs_root / case_id / "gpu_only_baseline").glob("run_*.stdout.log"))
        if not stdout_paths:
            accountings.append(
                {
                    "architecture_id": "hybrid_combined_vcs_sidecar_v1",
                    "status": "missing_qe_timer_trace",
                    "case_id": case_id,
                    "blockers": ["qe_stdout_timer_logs_missing"],
                    "implementation_coverage": "combined_partial_sidecar_motif",
                }
            )
            continue
        parsed_logs = [parse_qe_timer_stdout(path.read_text(encoding="utf-8", errors="replace")) for path in stdout_paths]
        routine_means: dict[str, float] = {}
        routine_call_means: dict[str, float] = {}
        component_rows: list[dict[str, Any]] = []
        used_timers: set[str] = set()
        replaceable_seconds = 0.0
        fpga_compute_seconds = 0.0
        transaction_count_total = 0.0
        for component in components:
            mapped_timer_names: list[str] = []
            component_replaceable = 0.0
            component_transaction_count = 0.0
            for timer_name in component["mapped_timer_names"]:
                if timer_name in used_timers:
                    continue
                walls: list[float] = []
                calls: list[float] = []
                for parsed_log in parsed_logs:
                    routine = parsed_log["routines"].get(timer_name)
                    if not isinstance(routine, Mapping):
                        continue
                    if isinstance(routine.get("wall_seconds"), (int, float)):
                        walls.append(float(routine["wall_seconds"]))
                    if isinstance(routine.get("calls"), (int, float)):
                        calls.append(float(routine["calls"]))
                mean_wall = _mean(walls)
                if mean_wall is None:
                    continue
                mean_calls = _mean(calls) or 1.0
                used_timers.add(timer_name)
                mapped_timer_names.append(timer_name)
                routine_means[timer_name] = mean_wall
                routine_call_means[timer_name] = mean_calls
                component_replaceable += mean_wall
                component_transaction_count += mean_calls
            if not mapped_timer_names:
                continue
            component_compute = float(component["kernel_seconds"]) * max(1.0, component_transaction_count)
            replaceable_seconds += component_replaceable
            fpga_compute_seconds += component_compute
            transaction_count_total += max(1.0, component_transaction_count)
            component_rows.append(
                {
                    "architecture_id": component["architecture_id"],
                    "mapped_timer_names": mapped_timer_names,
                    "latency_cycles": component["latency_cycles"],
                    "clock_ns": component["clock_ns"],
                    "kernel_seconds_per_transaction": component["kernel_seconds"],
                    "transaction_count_estimate": max(1.0, component_transaction_count),
                    "fpga_compute_seconds": component_compute,
                    "replaceable_seconds_mean": component_replaceable,
                }
            )
        if len(component_rows) < 2 or replaceable_seconds <= 0.0:
            accountings.append(
                {
                    "architecture_id": "hybrid_combined_vcs_sidecar_v1",
                    "status": "missing_trace_replay_inputs",
                    "case_id": case_id,
                    "mapped_timer_names": sorted(used_timers),
                    "blockers": ["combined_vcs_timer_or_latency_missing"],
                    "implementation_coverage": "combined_partial_sidecar_motif",
                }
            )
            continue
        launch_overhead = 0.00005 * transaction_count_total
        host_device_transfer = 0.00005 * transaction_count_total
        synchronization = 0.00005 * transaction_count_total
        cpu_retained = max(float(gpu_runtime) - replaceable_seconds, 0.0)
        hybrid_runtime = cpu_retained + fpga_compute_seconds + launch_overhead + host_device_transfer + synchronization
        accountings.append(
            {
                "architecture_id": "hybrid_combined_vcs_sidecar_v1",
                "status": "trace_replay_combined_vcs_sidecar_sensitivity",
                "case_id": case_id,
                "source_gpu_runtime_seconds_mean": float(gpu_runtime),
                "mapped_timer_names": sorted(used_timers),
                "mapped_timer_wall_seconds_mean": routine_means,
                "mapped_timer_call_count_mean": routine_call_means,
                "replaceable_seconds_mean": replaceable_seconds,
                "latency_source": "combined_vcs_rtl",
                "fpga_component_count": len(component_rows),
                "fpga_components": component_rows,
                "fpga_transaction_count_estimate": transaction_count_total,
                "fpga_compute_seconds": fpga_compute_seconds,
                "scf_control_seconds": 0.0,
                "cpu_retained_seconds": cpu_retained,
                "host_device_transfer_seconds": host_device_transfer,
                "synchronization_seconds": synchronization,
                "launch_overhead_seconds": launch_overhead,
                "hybrid_workflow_runtime_seconds": hybrid_runtime,
                "implementation_coverage": "combined_partial_sidecar_motif",
                "blockers": ["full_qe_kernel_equivalent_missing", "full_qe_kernel_integration_missing"],
                "timer_trace_paths": [str(path) for path in stdout_paths],
                "claim_boundary": "Combined VCS RTL sidecar sensitivity over measured QE timer traces; not full-QE integration, board measurement, or final FPGA superiority evidence.",
            }
        )
    return accountings


def merge_combined_vcs_sidecar_comparisons(
    gpu_baseline: Mapping[str, Any],
    classification: Mapping[str, Any],
    combined_accounting: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return classification with combined VCS sidecar accounting rows appended."""

    merged = json.loads(json.dumps(classification))
    baseline_records = [row for row in _as_list(gpu_baseline.get("baseline_records")) if isinstance(row, Mapping)]
    baseline_by_case = {
        str(row.get("case_id")): float(row["runtime_seconds_mean"])
        for row in baseline_records
        if row.get("case_id") is not None and row.get("runtime_seconds_mean") is not None
    }
    rows = [row for row in _as_list(merged.get("architecture_comparisons")) if isinstance(row, Mapping)]
    for accounting in combined_accounting:
        if accounting.get("status") != "trace_replay_combined_vcs_sidecar_sensitivity":
            continue
        case_id = str(accounting.get("case_id") or "")
        gpu_seconds = baseline_by_case.get(case_id)
        hybrid_value = accounting.get("hybrid_workflow_runtime_seconds")
        if gpu_seconds is None or not isinstance(hybrid_value, (int, float)) or float(hybrid_value) <= 0:
            continue
        rows.append(
            {
                "architecture_id": accounting.get("architecture_id"),
                "case_id": case_id,
                "gpu_runtime_seconds_mean": gpu_seconds,
                "hybrid_workflow_runtime_seconds": float(hybrid_value),
                "speedup_vs_gpu_mean": gpu_seconds / float(hybrid_value),
                "workflow_accounting_status": accounting.get("status"),
                "latency_source": accounting.get("latency_source"),
                "implementation_coverage": accounting.get("implementation_coverage"),
                "replaceable_seconds_mean": accounting.get("replaceable_seconds_mean"),
                "mapped_timer_names": accounting.get("mapped_timer_names"),
                "microkernel": {"fpga_components": accounting.get("fpga_components"), "fpga_component_count": accounting.get("fpga_component_count")},
            }
        )
    merged["architecture_comparisons"] = rows
    if rows:
        best = max(rows, key=lambda item: (float(item.get("speedup_vs_gpu_mean") or 0.0), 1 if item.get("architecture_id") == _INTEGRATED_SIDECAR_ID else 0))
        merged["best_architecture_id"] = best.get("architecture_id")
        merged["best_speedup_vs_gpu_mean"] = best.get("speedup_vs_gpu_mean")
    blockers = sorted(set(str(item) for item in _as_list(merged.get("blockers"))) | {"full_qe_kernel_equivalent_missing", "full_qe_kernel_integration_missing"})
    merged["blockers"] = blockers
    merged["preliminary_label"] = "fpga_hybrid_weaker" if merged.get("preliminary_label") != "insufficient_evidence" else merged.get("preliminary_label")
    merged["final_claim_allowed"] = False
    merged["claim_boundary"] = "Combined VCS RTL sidecar trace replay can improve optimistic sensitivity, but it is still partial-sidecar evidence rather than full QE kernel integration; report current implementation as weaker/not superior."
    return merged


def build_integrated_vcs_sidecar_accounting(
    gpu_baseline: Mapping[str, Any],
    gpu_runs_root: Path,
    integrated_result: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build trace replay from one integrated VCS RTL sidecar result."""

    if not isinstance(integrated_result, Mapping) or integrated_result.get("vcs_passed") is not True:
        return []
    architecture_id = str(integrated_result.get("architecture_id") or _INTEGRATED_SIDECAR_ID)
    if architecture_id == _STREAMING_SIDECAR_ID:
        implementation_coverage = "integrated_streaming_pipeline_sidecar_motif"
    elif architecture_id == _PIPELINED_SIDECAR_ID:
        implementation_coverage = "integrated_pipelined_sidecar_motif"
    else:
        implementation_coverage = "integrated_partial_sidecar_motif"
    vcs = integrated_result.get("vcs_parsed") if isinstance(integrated_result.get("vcs_parsed"), Mapping) else {}
    latency = vcs.get("latency_cycles") if isinstance(vcs, Mapping) else None
    component_cycles = vcs.get("component_cycles") if isinstance(vcs.get("component_cycles"), Mapping) else {}
    clock_source = "vcs_project_default"
    clock_ns = integrated_result.get("implemented_clock_ns")
    if isinstance(clock_ns, (int, float)):
        clock_source = str(integrated_result.get("implemented_clock_source") or "vivado_post_route_timing_met")
    else:
        clock_ns = integrated_result.get("clock_ns")
    if not isinstance(clock_ns, (int, float)):
        clock_ns = 8.75
        clock_source = "default_unimplemented_clock"
    if not isinstance(latency, (int, float)):
        return []
    records = [record for record in _as_list(gpu_baseline.get("baseline_records")) if isinstance(record, Mapping)]
    accountings: list[dict[str, Any]] = []
    for record in records:
        case_id = str(record.get("case_id") or "")
        gpu_runtime = record.get("runtime_seconds_mean")
        if not case_id or not isinstance(gpu_runtime, (int, float)):
            continue
        stdout_paths = sorted((gpu_runs_root / case_id / "gpu_only_baseline").glob("run_*.stdout.log"))
        if not stdout_paths:
            accountings.append(
                {
                    "architecture_id": architecture_id,
                    "status": "missing_qe_timer_trace",
                    "case_id": case_id,
                    "blockers": ["qe_stdout_timer_logs_missing"],
                    "implementation_coverage": implementation_coverage,
                }
            )
            continue
        parsed_logs = [parse_qe_timer_stdout(path.read_text(encoding="utf-8", errors="replace")) for path in stdout_paths]
        used_timers: set[str] = set()
        routine_means: dict[str, float] = {}
        routine_call_means: dict[str, float] = {}
        component_rows: list[dict[str, Any]] = []
        replaceable_seconds = 0.0
        fpga_compute_seconds = 0.0
        transaction_count_total = 0.0
        for component_id, timer_names in _INTEGRATED_COMPONENT_TIMER_MAP.items():
            component = component_cycles.get(component_id) if isinstance(component_cycles, Mapping) else None
            component_latency = component.get("cycles") if isinstance(component, Mapping) else None
            component_samples = component.get("samples") if isinstance(component, Mapping) else None
            if not isinstance(component_latency, (int, float)):
                continue
            mapped_timer_names: list[str] = []
            component_replaceable = 0.0
            component_transaction_count = 0.0
            for timer_name in timer_names:
                if timer_name in used_timers:
                    continue
                walls: list[float] = []
                calls: list[float] = []
                for parsed_log in parsed_logs:
                    routine = parsed_log["routines"].get(timer_name)
                    if not isinstance(routine, Mapping):
                        continue
                    if isinstance(routine.get("wall_seconds"), (int, float)):
                        walls.append(float(routine["wall_seconds"]))
                    if isinstance(routine.get("calls"), (int, float)):
                        calls.append(float(routine["calls"]))
                mean_wall = _mean(walls)
                if mean_wall is None:
                    continue
                mean_calls = _mean(calls) or 1.0
                used_timers.add(timer_name)
                mapped_timer_names.append(timer_name)
                routine_means[timer_name] = mean_wall
                routine_call_means[timer_name] = mean_calls
                component_replaceable += mean_wall
                component_transaction_count += mean_calls
            if not mapped_timer_names:
                continue
            kernel_seconds = float(clock_ns) * float(component_latency) * 1.0e-9
            transactions = max(1.0, component_transaction_count)
            component_compute = kernel_seconds * transactions
            replaceable_seconds += component_replaceable
            fpga_compute_seconds += component_compute
            transaction_count_total += transactions
            component_rows.append(
                {
                    "component_id": component_id,
                    "mapped_timer_names": mapped_timer_names,
                    "latency_cycles": int(component_latency),
                    "samples": component_samples,
                    "clock_ns": float(clock_ns),
                    "kernel_seconds_per_transaction": kernel_seconds,
                    "transaction_count_estimate": transactions,
                    "fpga_compute_seconds": component_compute,
                    "replaceable_seconds_mean": component_replaceable,
                }
            )
        if len(component_rows) < 2 or replaceable_seconds <= 0.0:
            accountings.append(
                {
                    "architecture_id": architecture_id,
                    "status": "missing_trace_replay_inputs",
                    "case_id": case_id,
                    "mapped_timer_names": sorted(used_timers),
                    "blockers": ["integrated_vcs_timer_or_component_latency_missing"],
                    "implementation_coverage": implementation_coverage,
                }
            )
            continue
        launch_overhead = 0.00005 * transaction_count_total
        host_device_transfer = 0.00005 * transaction_count_total
        synchronization = 0.00005 * transaction_count_total
        cpu_retained = max(float(gpu_runtime) - replaceable_seconds, 0.0)
        hybrid_runtime = cpu_retained + fpga_compute_seconds + launch_overhead + host_device_transfer + synchronization
        accountings.append(
            {
                "architecture_id": architecture_id,
                "status": "trace_replay_integrated_vcs_sidecar_sensitivity",
                "case_id": case_id,
                "source_gpu_runtime_seconds_mean": float(gpu_runtime),
                "mapped_timer_names": sorted(used_timers),
                "mapped_timer_wall_seconds_mean": routine_means,
                "mapped_timer_call_count_mean": routine_call_means,
                "replaceable_seconds_mean": replaceable_seconds,
                "latency_source": "integrated_vcs_rtl",
                "integrated_latency_cycles": int(latency),
                "fpga_clock_ns": float(clock_ns),
                "fpga_clock_source": clock_source,
                "fpga_component_count": len(component_rows),
                "fpga_components": component_rows,
                "fpga_transaction_count_estimate": transaction_count_total,
                "fpga_compute_seconds": fpga_compute_seconds,
                "scf_control_seconds": 0.0,
                "cpu_retained_seconds": cpu_retained,
                "host_device_transfer_seconds": host_device_transfer,
                "synchronization_seconds": synchronization,
                "launch_overhead_seconds": launch_overhead,
                "hybrid_workflow_runtime_seconds": hybrid_runtime,
                "implementation_coverage": implementation_coverage,
                "blockers": ["full_qe_kernel_equivalent_missing", "full_qe_kernel_integration_missing"],
                "timer_trace_paths": [str(path) for path in stdout_paths],
                "claim_boundary": "Trace replay using a single integrated RTL/VCS sidecar miniapp over measured QE timer traces; not full-QE integration, board measurement, or final FPGA superiority evidence.",
            }
        )
    return accountings


def merge_integrated_vcs_sidecar_comparisons(
    gpu_baseline: Mapping[str, Any],
    classification: Mapping[str, Any],
    integrated_accounting: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return classification with integrated VCS sidecar accounting rows appended."""

    merged = json.loads(json.dumps(classification))
    baseline_records = [row for row in _as_list(gpu_baseline.get("baseline_records")) if isinstance(row, Mapping)]
    baseline_by_case = {
        str(row.get("case_id")): float(row["runtime_seconds_mean"])
        for row in baseline_records
        if row.get("case_id") is not None and row.get("runtime_seconds_mean") is not None
    }
    rows = [row for row in _as_list(merged.get("architecture_comparisons")) if isinstance(row, Mapping)]
    for accounting in integrated_accounting:
        if accounting.get("status") != "trace_replay_integrated_vcs_sidecar_sensitivity":
            continue
        case_id = str(accounting.get("case_id") or "")
        gpu_seconds = baseline_by_case.get(case_id)
        hybrid_value = accounting.get("hybrid_workflow_runtime_seconds")
        if gpu_seconds is None or not isinstance(hybrid_value, (int, float)) or float(hybrid_value) <= 0:
            continue
        rows.append(
            {
                "architecture_id": accounting.get("architecture_id"),
                "case_id": case_id,
                "gpu_runtime_seconds_mean": gpu_seconds,
                "hybrid_workflow_runtime_seconds": float(hybrid_value),
                "speedup_vs_gpu_mean": gpu_seconds / float(hybrid_value),
                "workflow_accounting_status": accounting.get("status"),
                "latency_source": accounting.get("latency_source"),
                "implementation_coverage": accounting.get("implementation_coverage"),
                "replaceable_seconds_mean": accounting.get("replaceable_seconds_mean"),
                "mapped_timer_names": accounting.get("mapped_timer_names"),
                "microkernel": {"fpga_components": accounting.get("fpga_components"), "fpga_component_count": accounting.get("fpga_component_count")},
            }
        )
    merged["architecture_comparisons"] = rows
    if rows:
        best = max(rows, key=lambda item: (float(item.get("speedup_vs_gpu_mean") or 0.0), 1 if item.get("architecture_id") == _INTEGRATED_SIDECAR_ID else 0))
        merged["best_architecture_id"] = best.get("architecture_id")
        merged["best_speedup_vs_gpu_mean"] = best.get("speedup_vs_gpu_mean")
    blockers = sorted(set(str(item) for item in _as_list(merged.get("blockers"))) | {"full_qe_kernel_equivalent_missing", "full_qe_kernel_integration_missing"})
    merged["blockers"] = blockers
    merged["preliminary_label"] = "fpga_hybrid_weaker" if merged.get("preliminary_label") != "insufficient_evidence" else merged.get("preliminary_label")
    merged["final_claim_allowed"] = False
    merged["claim_boundary"] = "Integrated VCS RTL sidecar trace replay improves hardware-integration evidence, but it remains a compact sidecar miniapp rather than full QE kernel integration; report current implementation as weaker/not superior."
    return merged


def _workflow_accounting_items(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    accounting = row.get("workflow_accounting")
    if isinstance(accounting, Mapping):
        return [accounting]
    if isinstance(accounting, list):
        return [item for item in accounting if isinstance(item, Mapping)]
    return []

def _workflow_accounting_is_claimable(row: Mapping[str, Any]) -> bool:
    required = [
        "scf_control_seconds",
        "cpu_retained_seconds",
        "host_device_transfer_seconds",
        "synchronization_seconds",
        "launch_overhead_seconds",
        "hybrid_workflow_runtime_seconds",
    ]
    for accounting in _workflow_accounting_items(row):
        if accounting.get("status") not in {"measured", "trace_replay", "trace_replay_optimistic", "trace_replay_vcs_rtl_sensitivity", "full_scf_accounted", "claimable_estimate"}:
            continue
        if all(isinstance(accounting.get(key), (int, float)) for key in required):
            return True
    return False


def _microkernel_row(row: Mapping[str, Any]) -> dict[str, Any]:
    parsed = row.get("csynth_parsed") if isinstance(row.get("csynth_parsed"), Mapping) else {}
    cosim = row.get("cosim_parsed") if isinstance(row.get("cosim_parsed"), Mapping) else {}
    vcs = row.get("vcs_parsed") if isinstance(row.get("vcs_parsed"), Mapping) else {}
    csynth_latency = parsed.get("latency_cycles_max") if isinstance(parsed, Mapping) else None
    cosim_latency = cosim.get("latency_cycles_max") if isinstance(cosim, Mapping) else None
    vcs_latency = vcs.get("latency_cycles") if row.get("vcs_passed") is True and isinstance(vcs, Mapping) else None
    clock_ns = None
    if isinstance(parsed, Mapping):
        clock_ns = parsed.get("estimated_clock_ns") or parsed.get("target_clock_ns")
    latency_cycles = cosim_latency or csynth_latency
    kernel_seconds = None
    if isinstance(latency_cycles, (int, float)) and isinstance(clock_ns, (int, float)):
        kernel_seconds = float(latency_cycles) * float(clock_ns) * 1.0e-9
    vcs_kernel_seconds = None
    if isinstance(vcs_latency, (int, float)) and isinstance(clock_ns, (int, float)):
        vcs_kernel_seconds = float(vcs_latency) * float(clock_ns) * 1.0e-9
    return {
        "architecture_id": row.get("architecture_id"),
        "csynth_latency_cycles_max": csynth_latency,
        "rtl_cosim_latency_cycles_max": cosim_latency,
        "vcs_rtl_latency_cycles": vcs_latency,
        "estimated_clock_ns": clock_ns,
        "microkernel_seconds": kernel_seconds,
        "vcs_rtl_microkernel_seconds": vcs_kernel_seconds,
        "resource": parsed.get("resource") if isinstance(parsed, Mapping) else None,
        "resource_available": parsed.get("resource_available") if isinstance(parsed, Mapping) else None,
        "resource_feasible": parsed.get("resource_feasible") if isinstance(parsed, Mapping) else None,
    }


def _row_resource_feasible(row: Mapping[str, Any]) -> bool:
    parsed = row.get("csynth_parsed")
    if not isinstance(parsed, Mapping):
        return False
    if parsed.get("resource_feasible") is False:
        return False
    blockers = {str(item) for item in _as_list(parsed.get("blockers"))}
    return "hls_resource_infeasible" not in blockers


def _gate(gate_id: str, status: str, evidence: Mapping[str, Any], required_for: str) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "status": status,
        "evidence": dict(evidence),
        "required_for": required_for,
    }


def build_real_hybrid_claim_closure(
    gpu_baseline: Mapping[str, Any],
    evidence_rows: Sequence[Mapping[str, Any]],
    classification: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an auditable hard-gate closure record for GPU-vs-hybrid claims."""

    baseline_records = [row for row in _as_list(gpu_baseline.get("baseline_records")) if isinstance(row, Mapping)]
    architecture_ids = sorted({str(row.get("architecture_id")) for row in evidence_rows if row.get("architecture_id")})
    real_kernel_architectures = sorted(
        {str(row.get("architecture_id")) for row in evidence_rows if row.get("implementation_maturity") == "real_hls_kernel" and row.get("architecture_id")}
    )
    resource_feasible_architectures = sorted(
        {str(row.get("architecture_id")) for row in evidence_rows if row.get("architecture_id") and _row_resource_feasible(row)}
    )
    vcs_passed_architectures = sorted({str(row.get("architecture_id")) for row in evidence_rows if row.get("architecture_id") and row.get("vcs_passed") is True})
    cosim_passed_architectures = sorted({str(row.get("architecture_id")) for row in evidence_rows if row.get("architecture_id") and row.get("cosim_passed") is True})
    workflow_accounted_architectures = sorted(
        {str(row.get("architecture_id")) for row in evidence_rows if row.get("architecture_id") and _workflow_accounting_is_claimable(row)}
    )
    integrated_vivado_impl_passed = classification.get("integrated_vivado_impl_passed") is True
    integrated_vivado_impl_timing_met = classification.get("integrated_vivado_impl_timing_met") is True
    integrated_vivado_impl_resource_feasible = classification.get("integrated_vivado_impl_resource_feasible") is True
    full_qe_kernel_architectures = sorted(
        {
            str(row.get("architecture_id"))
            for row in evidence_rows
            if row.get("architecture_id")
            and any(accounting.get("implementation_coverage") == "full_qe_kernel_equivalent" for accounting in _workflow_accounting_items(row))
        }
    )
    board_measured_architectures = sorted(
        {
            str(row.get("architecture_id"))
            for row in evidence_rows
            if row.get("architecture_id")
            and any(
                str(accounting.get("status") or "") in {"measured", "board_measured", "full_scf_board_measured"}
                for accounting in _workflow_accounting_items(row)
            )
        }
    )

    gates = [
        _gate(
            "measured_gpu_baseline",
            "satisfied" if gpu_baseline.get("measurements_are_real") is True and baseline_records else "missing",
            {"measurements_are_real": gpu_baseline.get("measurements_are_real"), "baseline_record_count": len(baseline_records)},
            "preliminary_and_final_gpu_comparison",
        ),
        _gate(
            "multiple_real_architectures",
            "satisfied" if len(real_kernel_architectures) >= 2 else "missing",
            {"architecture_count": len(architecture_ids), "real_kernel_architecture_count": len(real_kernel_architectures), "architecture_ids": real_kernel_architectures},
            "preliminary_multi_architecture_screening",
        ),
        _gate(
            "resource_feasible_hls",
            "satisfied" if len(resource_feasible_architectures) >= 2 else "missing",
            {"resource_feasible_architecture_count": len(resource_feasible_architectures), "architecture_ids": resource_feasible_architectures},
            "preliminary_fpga_feasibility",
        ),
        _gate(
            "golden_csim",
            "satisfied" if evidence_rows and all(row.get("csim_passed") is True for row in evidence_rows) else "missing",
            {"csim_passed_count": sum(1 for row in evidence_rows if row.get("csim_passed") is True), "row_count": len(evidence_rows)},
            "correctness_before_performance",
        ),
        _gate(
            "vcs_or_cosim_performance",
            "satisfied" if vcs_passed_architectures or cosim_passed_architectures else "missing",
            {
                "vcs_passed_architecture_count": len(vcs_passed_architectures),
                "vcs_passed_architecture_ids": vcs_passed_architectures,
                "cosim_passed_architecture_count": len(cosim_passed_architectures),
                "cosim_passed_architecture_ids": cosim_passed_architectures,
            },
            "non_stub_latency_evidence",
        ),
        _gate(
            "full_scf_workflow_accounting",
            "satisfied" if workflow_accounted_architectures else "missing",
            {"workflow_accounted_architecture_count": len(workflow_accounted_architectures), "architecture_ids": workflow_accounted_architectures},
            "preliminary_full_workflow_comparison",
        ),
        _gate(
            "integrated_vivado_implementation",
            "satisfied" if integrated_vivado_impl_passed and integrated_vivado_impl_timing_met and integrated_vivado_impl_resource_feasible else "missing",
            {
                "integrated_vivado_impl_passed": integrated_vivado_impl_passed,
                "integrated_vivado_impl_timing_met": integrated_vivado_impl_timing_met,
                "integrated_vivado_impl_resource_feasible": integrated_vivado_impl_resource_feasible,
                "integrated_vivado_impl_resource": classification.get("integrated_vivado_impl_resource"),
                "integrated_vivado_impl_wns_ns": classification.get("integrated_vivado_impl_wns_ns"),
            },
            "preliminary_fpga_implementation_feasibility",
        ),
        _gate(
            "full_qe_kernel_integration",
            "satisfied" if full_qe_kernel_architectures else "missing",
            {"full_qe_kernel_architecture_count": len(full_qe_kernel_architectures), "architecture_ids": full_qe_kernel_architectures},
            "strong_hybrid_superiority_claim",
        ),
        _gate(
            "physical_fpga_board_measurement",
            "satisfied" if board_measured_architectures else "missing",
            {"board_measured_architecture_count": len(board_measured_architectures), "architecture_ids": board_measured_architectures},
            "final_hardware_superiority_claim",
        ),
    ]
    missing_gate_ids = [gate["gate_id"] for gate in gates if gate["status"] != "satisfied"]
    final_claim_allowed = bool(classification.get("final_claim_allowed")) and not missing_gate_ids
    label = str(classification.get("preliminary_label") or "insufficient_evidence")
    if final_claim_allowed and label == "fpga_hybrid_stronger":
        verdict = "superior_final_claim_allowed"
    elif label == "insufficient_evidence":
        verdict = "insufficient_evidence"
    else:
        verdict = "not_superior_current_evidence"
    return {
        "schema_version": "dse.qe_ic.real_hybrid_claim_closure.v1",
        "preliminary_label": label,
        "claim_verdict": verdict,
        "final_claim_allowed": final_claim_allowed,
        "gates": gates,
        "missing_gate_ids": missing_gate_ids,
        "blockers": sorted(set(str(item) for item in _as_list(classification.get("blockers")))),
        "claim_boundary": classification.get("claim_boundary"),
    }


def classify_real_hybrid_vs_gpu(gpu_baseline: Mapping[str, Any], evidence_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Classify real hybrid evidence against GPU baseline with hard gates.

    Real HLS C-sim/C-synth/C/RTL-cosim proves a microkernel is not a stub.  It
    does **not** by itself prove GPU-vs-hybrid full-SCF superiority, because the
    baseline is a full QE SCF wall time and the HLS rows are standalone motifs.
    A stronger/weaker conclusion therefore requires explicit full-SCF workflow
    accounting/coupling evidence for the hybrid path.
    """

    blockers: list[str] = []
    baseline_records = [row for row in _as_list(gpu_baseline.get("baseline_records")) if isinstance(row, Mapping)]
    if gpu_baseline.get("measurements_are_real") is not True or not baseline_records:
        blockers.append("measured_gpu_baseline_required")
    architecture_ids = {str(row.get("architecture_id")) for row in evidence_rows if row.get("architecture_id")}
    feasible_rows = [row for row in evidence_rows if _row_resource_feasible(row)]
    feasible_architecture_ids = {str(row.get("architecture_id")) for row in feasible_rows if row.get("architecture_id")}
    resource_infeasible_architecture_ids = sorted(architecture_ids - feasible_architecture_ids)
    if len(architecture_ids) < 2:
        blockers.append("at_least_two_architecture_families_required")
    elif len(feasible_architecture_ids) < 2:
        blockers.append("resource_feasible_hls_required")
    if any(str(row.get("implementation_maturity")) != "real_hls_kernel" for row in evidence_rows):
        blockers.append("real_hls_kernel_implementation_required")
    if not evidence_rows:
        blockers.append("real_hybrid_hls_evidence_required")
    if not all(row.get("csim_passed") is True for row in evidence_rows):
        blockers.append("golden_csim_required")
    if not all(isinstance(row.get("csynth_parsed"), Mapping) and row["csynth_parsed"].get("status") in {"parsed", "partial"} for row in evidence_rows):
        blockers.append("hls_synthesis_latency_resource_required")
    if not any(row.get("cosim_passed") is True or row.get("vcs_passed") is True for row in feasible_rows):
        blockers.append("cosim_or_vcs_required_for_strong_conclusion")
    if not any(_workflow_accounting_is_claimable(row) for row in feasible_rows):
        blockers.append("full_scf_workflow_accounting_required")

    microkernel_evidence = [_microkernel_row(row) for row in evidence_rows]

    if blockers:
        return {
            "preliminary_label": "insufficient_evidence",
            "confidence": "low",
            "final_claim_allowed": False,
            "blockers": sorted(set(blockers)),
            "microkernel_evidence": microkernel_evidence,
            "resource_infeasible_architecture_ids": resource_infeasible_architecture_ids,
            "claim_boundary": "Real-HLS C/RTL evidence is microkernel evidence. Strong GPU-vs-hybrid conclusions require measured GPU baseline, multiple resource-feasible architectures, golden correctness, synthesis latency/resource, cosim/VCS, and full-SCF workflow accounting/coupling.",
        }

    baseline_by_case = {
        str(row.get("case_id")): float(row["runtime_seconds_mean"])
        for row in baseline_records
        if row.get("case_id") is not None and row.get("runtime_seconds_mean") is not None
    }
    rows: list[dict[str, Any]] = []
    has_partial_sidecar = False
    for row in feasible_rows:
        for accounting in _workflow_accounting_items(row):
            if accounting.get("status") not in {"measured", "trace_replay", "trace_replay_optimistic", "trace_replay_vcs_rtl_sensitivity", "full_scf_accounted", "claimable_estimate"}:
                continue
            case_id = str(accounting.get("case_id") or row.get("case_id") or "")
            gpu_seconds = baseline_by_case.get(case_id)
            hybrid_value = accounting.get("hybrid_workflow_runtime_seconds")
            if gpu_seconds is None or not isinstance(hybrid_value, (int, float)) or float(hybrid_value) <= 0:
                continue
            coverage = str(accounting.get("implementation_coverage") or "unknown")
            if coverage != "full_qe_kernel_equivalent":
                has_partial_sidecar = True
            rows.append(
                {
                    "architecture_id": row.get("architecture_id"),
                    "case_id": case_id,
                    "gpu_runtime_seconds_mean": gpu_seconds,
                    "hybrid_workflow_runtime_seconds": float(hybrid_value),
                    "speedup_vs_gpu_mean": gpu_seconds / float(hybrid_value),
                    "workflow_accounting_status": accounting.get("status"),
                    "latency_source": accounting.get("latency_source"),
                    "fpga_latency_cycles_per_transaction": accounting.get("fpga_latency_cycles_per_transaction"),
                    "implementation_coverage": coverage,
                    "replaceable_seconds_mean": accounting.get("replaceable_seconds_mean"),
                    "mapped_timer_names": accounting.get("mapped_timer_names"),
                    "microkernel": _microkernel_row(row),
                }
            )
    if not rows:
        return {
            "preliminary_label": "insufficient_evidence",
            "confidence": "low",
            "final_claim_allowed": False,
            "blockers": ["claimable_case_matched_workflow_accounting_required"],
            "microkernel_evidence": microkernel_evidence,
            "claim_boundary": "No case-matched hybrid full-SCF workflow runtime could be compared to the measured GPU baseline.",
        }
    best = max(rows, key=lambda item: item["speedup_vs_gpu_mean"])
    result_blockers = ["physical_fpga_board_measurement_missing", "full_qe_kernel_integration_missing"]
    if resource_infeasible_architecture_ids:
        result_blockers.append("hls_resource_infeasible_architectures_filtered")
    if has_partial_sidecar:
        label = "fpga_hybrid_weaker"
        confidence = "medium"
        result_blockers.append("full_qe_kernel_equivalent_missing")
        claim_boundary = "Real HLS C/RTL cosim passed, and optimistic trace replay shows sidecar microkernel potential, but the implemented kernels are partial motifs rather than full QE kernel-equivalent replacements; report current implementation as weaker/not superior."
    elif best["speedup_vs_gpu_mean"] >= 1.05:
        label = "fpga_hybrid_stronger"
        confidence = "medium"
        claim_boundary = "Preliminary real-HLS architecture comparison with explicit workflow accounting; final hardware superiority still requires full integration and board/implementation closure."
    else:
        label = "fpga_hybrid_weaker"
        confidence = "medium"
        claim_boundary = "Preliminary real-HLS architecture comparison with explicit workflow accounting; final hardware superiority still requires full integration and board/implementation closure."
    return {
        "preliminary_label": label,
        "confidence": confidence,
        "final_claim_allowed": False,
        "best_architecture_id": best["architecture_id"],
        "best_speedup_vs_gpu_mean": best["speedup_vs_gpu_mean"],
        "architecture_comparisons": rows,
        "microkernel_evidence": microkernel_evidence,
        "resource_infeasible_architecture_ids": resource_infeasible_architecture_ids,
        "blockers": sorted(set(result_blockers)),
        "claim_boundary": claim_boundary,
    }


def build_real_hybrid_superiority_proof_audit(
    *,
    summary: Mapping[str, Any],
    claim_closure: Mapping[str, Any],
    gpu_baseline: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a fail-closed audit for GPU-vs-hybrid superiority claims.

    This is deliberately stricter than a report renderer: it binds measured GPU
    baseline, distinct non-stub integrated RTL/VCS architectures, Vivado
    implementation evidence, and hard final-claim gates into one compact
    artifact.  It may support a preliminary label, but final superiority remains
    blocked unless full-QE integration and board measurement gates are present.
    """

    classification = summary.get("classification") if isinstance(summary.get("classification"), Mapping) else {}
    baseline_records = [row for row in _as_list(gpu_baseline.get("baseline_records")) if isinstance(row, Mapping)]
    vcs_result_keys = {
        "integrated_vcs_sidecar_result",
        "integrated_pipelined_vcs_sidecar_result",
        "integrated_streaming_vcs_sidecar_result",
    }
    vcs_results = [
        value
        for key in vcs_result_keys
        if isinstance((value := summary.get(key)), Mapping) and value.get("architecture_id")
    ]
    vivado_results = [
        value
        for key in _INTEGRATED_VIVADO_RESULT_KEYS.values()
        if isinstance((value := summary.get(key)), Mapping) and value.get("architecture_id")
    ]
    architecture_ids = sorted(
        {
            str(item.get("architecture_id"))
            for item in [*vcs_results, *vivado_results]
            if item.get("architecture_id")
        }
    )
    vcs_passed_ids = sorted(
        {
            str(item.get("architecture_id"))
            for item in vcs_results
            if item.get("vcs_passed") is True
            and isinstance(item.get("vcs_parsed"), Mapping)
            and item["vcs_parsed"].get("rtl_status") == "Pass"
            and isinstance(item["vcs_parsed"].get("latency_cycles"), (int, float))
        }
    )
    vivado_passed_ids = sorted(
        {
            str(item.get("architecture_id"))
            for item in vivado_results
            if item.get("vivado_impl_passed") is True
            and isinstance(item.get("implemented_clock_ns"), (int, float))
            and isinstance(item.get("vivado_impl_timing_parsed"), Mapping)
            and item["vivado_impl_timing_parsed"].get("timing_met") is True
            and isinstance(item.get("vivado_impl_utilization_parsed"), Mapping)
            and item["vivado_impl_utilization_parsed"].get("resource_feasible") is True
        }
    )
    missing_gate_ids = [str(item) for item in _as_list(claim_closure.get("missing_gate_ids"))]
    final_claim_allowed = claim_closure.get("final_claim_allowed") is True and not missing_gate_ids
    checks = [
        {
            "check_id": "measured_gpu_baseline",
            "status": "satisfied" if gpu_baseline.get("measurements_are_real") is True and baseline_records else "missing",
            "evidence": {
                "measurements_are_real": gpu_baseline.get("measurements_are_real"),
                "baseline_record_count": len(baseline_records),
            },
        },
        {
            "check_id": "multiple_distinct_integrated_architectures",
            "status": "satisfied" if len(architecture_ids) >= 2 else "missing",
            "evidence": {"architecture_count": len(architecture_ids), "architecture_ids": architecture_ids},
        },
        {
            "check_id": "vcs_non_stub_latency",
            "status": "satisfied" if len(vcs_passed_ids) >= 2 else "missing",
            "evidence": {"vcs_passed_architecture_count": len(vcs_passed_ids), "architecture_ids": vcs_passed_ids},
        },
        {
            "check_id": "vivado_post_route_implementation",
            "status": "satisfied" if len(vivado_passed_ids) >= 1 else "missing",
            "evidence": {"vivado_passed_architecture_count": len(vivado_passed_ids), "architecture_ids": vivado_passed_ids},
        },
        {
            "check_id": "full_qe_kernel_integration",
            "status": "satisfied" if "full_qe_kernel_integration" not in missing_gate_ids else "missing",
            "evidence": {"missing_gate": "full_qe_kernel_integration" in missing_gate_ids},
        },
        {
            "check_id": "physical_fpga_board_measurement",
            "status": "satisfied" if "physical_fpga_board_measurement" not in missing_gate_ids else "missing",
            "evidence": {"missing_gate": "physical_fpga_board_measurement" in missing_gate_ids},
        },
    ]
    checks_by_id = {str(check["check_id"]): check for check in checks}
    return {
        "schema_version": "dse.qe_ic.real_hybrid_superiority_proof_audit.v1",
        "decision": str(claim_closure.get("preliminary_label") or classification.get("preliminary_label") or "insufficient_evidence"),
        "claim_verdict": str(claim_closure.get("claim_verdict") or "unknown"),
        "strong_superiority_claim_allowed": final_claim_allowed,
        "final_claim_allowed": final_claim_allowed,
        "missing_gate_ids": missing_gate_ids,
        "best_vivado_implemented_architecture_id": classification.get("best_vivado_implemented_architecture_id"),
        "best_vivado_implemented_speedup_vs_gpu_mean": classification.get("best_vivado_implemented_speedup_vs_gpu_mean"),
        "architecture_count": len(architecture_ids),
        "vcs_passed_architecture_count": len(vcs_passed_ids),
        "vivado_passed_architecture_count": len(vivado_passed_ids),
        "checks": checks,
        "checks_by_id": checks_by_id,
        "claim_boundary": (
            "Fail-closed superiority audit: VCS/Vivado sidecar evidence can support preliminary comparison only; "
            "full-QE kernel integration and physical FPGA board measurement are required for a strong hardware superiority claim."
        ),
    }


__all__ = [
    "build_real_hybrid_architecture_specs",
    "build_evidence_row_static_metadata",
    "build_combined_vcs_sidecar_accounting",
    "build_integrated_vcs_sidecar_accounting",
    "build_real_hybrid_claim_closure",
    "build_real_hybrid_superiority_proof_audit",
    "build_trace_replay_workflow_accounting",
    "classify_real_hybrid_vs_gpu",
    "materialize_integrated_pipelined_vcs_sidecar_project",
    "materialize_integrated_pipelined_vivado_impl_project",
    "materialize_integrated_streaming_vcs_sidecar_project",
    "materialize_integrated_streaming_vivado_impl_project",
    "materialize_integrated_vcs_sidecar_project",
    "materialize_integrated_vivado_impl_project",
    "materialize_hls_project",
    "materialize_vcs_rtl_project",
    "merge_combined_vcs_sidecar_comparisons",
    "merge_integrated_vcs_sidecar_comparisons",
    "merge_integrated_vivado_impl_evidence_into_summary",
    "merge_vcs_rtl_evidence_into_summary",
    "parse_qe_timer_stdout",
    "parse_vcs_rtl_run_log",
    "render_real_hybrid_hls_report",
    "parse_vivado_hls_cosim_report",
    "parse_vivado_hls_csynth_report",
    "parse_vivado_impl_timing_summary_report",
    "parse_vivado_impl_utilization_report",
]
