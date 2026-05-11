#!/usr/bin/env python3
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

    os.environ["VECLIB_MAXIMUM_THREADS"] = str(args.threads)
    os.environ["OPENBLAS_NUM_THREADS"] = str(args.threads)
    os.environ["OMP_NUM_THREADS"] = str(args.threads)

    import numpy as np
    import scipy.linalg as sla
    from scipy.linalg import blas
    from pyscf import lib

    rng = np.random.default_rng(args.seed)
    results = {
        "env": {
            "threads": args.threads,
            "seed": args.seed,
            "VECLIB_MAXIMUM_THREADS": os.environ["VECLIB_MAXIMUM_THREADS"],
            "OPENBLAS_NUM_THREADS": os.environ["OPENBLAS_NUM_THREADS"],
            "OMP_NUM_THREADS": os.environ["OMP_NUM_THREADS"],
        },
        "gemm": {},
        "fft": {},
        "diag": {},
    }

    for m, k, n in [(3072, 256, 64), (2048, 512, 256)]:
        a = np.ascontiguousarray(rng.standard_normal((m, k), dtype=np.float64))
        b = np.ascontiguousarray(rng.standard_normal((k, n), dtype=np.float64))
        c = np.empty((m, n), order="C")

        def run():
            lib.numpy_helper._dgemm("N", "N", m, n, k, a, b, c)

        stat = bench(run, warmup=2, repeat=7)
        stat["gflops_median"] = 2.0 * m * k * n / stat["median_s"] / 1e9
        results["gemm"][f"{m}x{k}x{n}"] = stat

    for n in [64, 96, 128]:
        x = rng.standard_normal((n, n, n), dtype=np.float64) + 1j * rng.standard_normal(
            (n, n, n), dtype=np.float64
        )

        def run_fft():
            np.fft.fftn(x)

        stat = bench(run_fft, warmup=2, repeat=7)
        stat["points_per_sec_median"] = (n**3) / stat["median_s"]
        results["fft"][f"{n}^3"] = stat

    for n in [256, 512, 768]:
        a = rng.standard_normal((n, n), dtype=np.float64)
        h = np.ascontiguousarray((a + a.T) * 0.5)
        b = rng.standard_normal((n, n), dtype=np.float64) * (1.0 / np.sqrt(n))
        # Use BLAS to build SPD overlap matrix more stably than raw matmul on this platform.
        s = np.ascontiguousarray(blas.dgemm(alpha=1.0, a=b, b=b, trans_a=True))
        s[np.diag_indices(n)] += 1e-2

        def run_diag():
            sla.eigh(h, s, check_finite=False, driver="gvd")

        results["diag"][str(n)] = bench(run_diag, warmup=1, repeat=5)

    text = json.dumps(results, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
