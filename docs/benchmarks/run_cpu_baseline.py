#!/usr/bin/env python3
"""
CPU micro-benchmark for baseline tracking.

Covers:
1) GEMM via PySCF lib.numpy_helper._dgemm
2) 3D FFT via NumPy fftn (PySCF-side common path)
3) Diagonalization via SciPy gvd and PySCF safe_eigh
"""

import argparse
import json
import os
import statistics
import time


def bench(fn, warmup=2, repeat=7):
    for _ in range(warmup):
        fn()
    ts = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return {
        "median_s": statistics.median(ts),
        "mean_s": statistics.mean(ts),
        "min_s": min(ts),
        "max_s": max(ts),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--seed", type=int, default=20260305)
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()

    # Set before imports to maximize backend thread control.
    os.environ["VECLIB_MAXIMUM_THREADS"] = str(args.threads)
    os.environ["OPENBLAS_NUM_THREADS"] = str(args.threads)
    os.environ["OMP_NUM_THREADS"] = str(args.threads)

    import numpy as np
    from pyscf import lib
    from pyscf.lib import linalg_helper
    from scipy.linalg import blas, eigh

    rng = np.random.default_rng(args.seed)

    results = {
        "env": {
            "VECLIB_MAXIMUM_THREADS": os.environ["VECLIB_MAXIMUM_THREADS"],
            "OPENBLAS_NUM_THREADS": os.environ["OPENBLAS_NUM_THREADS"],
            "OMP_NUM_THREADS": os.environ["OMP_NUM_THREADS"],
            "rng_seed": args.seed,
        },
        "gemm_pyscf_dgemm": {},
        "fft_numpy_fftn": {},
        "diag": {},
    }

    # GEMM (representative shapes)
    for m, k, n in [(3072, 256, 64), (2048, 512, 256)]:
        a = np.ascontiguousarray(rng.standard_normal((m, k), dtype=np.float64))
        b = np.ascontiguousarray(rng.standard_normal((k, n), dtype=np.float64))
        c = np.empty((m, n), order="C")

        def run():
            lib.numpy_helper._dgemm("N", "N", m, n, k, a, b, c)

        stat = bench(run)
        stat["gflops_median"] = 2.0 * m * k * n / stat["median_s"] / 1e9
        results["gemm_pyscf_dgemm"][f"{m}x{k}x{n}"] = stat

    # 3D FFT (NumPy path)
    for n in [64, 96, 128]:
        x = rng.standard_normal((n, n, n), dtype=np.float64) + 1j * rng.standard_normal(
            (n, n, n), dtype=np.float64
        )

        def run_fft():
            np.fft.fftn(x)

        stat = bench(run_fft)
        stat["points_per_sec_median"] = (n**3) / stat["median_s"]
        results["fft_numpy_fftn"][f"{n}^3"] = stat

    # Diagonalization (generalized EVP)
    for n in [256, 512, 768]:
        a = rng.standard_normal((n, n), dtype=np.float64)
        h = np.ascontiguousarray((a + a.T) * 0.5)
        b = rng.standard_normal((n, n), dtype=np.float64) * (1.0 / np.sqrt(n))
        s = np.ascontiguousarray(blas.dgemm(alpha=1.0, a=b, b=b, trans_a=True))
        s[np.diag_indices(n)] += 1e-2

        def run_safe():
            linalg_helper.safe_eigh(h, s)

        def run_gvd():
            eigh(h, s, check_finite=False, driver="gvd")

        results["diag"][f"pyscf_safe_eigh_{n}"] = bench(run_safe, warmup=1, repeat=5)
        results["diag"][f"scipy_gvd_{n}"] = bench(run_gvd, warmup=1, repeat=5)

    payload = json.dumps(results, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(payload + "\n")
    print(payload)


if __name__ == "__main__":
    main()

