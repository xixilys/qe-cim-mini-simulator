#!/usr/bin/env python3
"""Build DFT-first per-candidate evidence ledger artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_evidence_ledger import write_dft_candidate_evidence_artifacts  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument(
        "--release-artifact-dir",
        type=Path,
        required=True,
        help="Directory containing seven-axis release-domain artifacts",
    )
    parser.add_argument(
        "--mode-coverage-dir",
        type=Path,
        default=None,
        help="Optional directory containing DFT mode coverage artifacts",
    )
    parser.add_argument(
        "--timing-run-dir",
        type=Path,
        default=Path("runs/dse/dft_first_qe_real_gem5_hardened_audit"),
        help="Optional existing non-smoke timing/gem5 sample used only as calibration/reference evidence",
    )
    parser.add_argument(
        "--ic-eda-tool-availability",
        type=Path,
        default=None,
        help="Optional ic_eda_tool_availability.json from probe_dft_ic_eda_tools.py",
    )
    parser.add_argument(
        "--dft-hardware-evidence-matrix",
        type=Path,
        default=None,
        help="Optional dft_hardware_evidence_matrix.json from build_dft_hardware_evidence_matrix.py",
    )
    parser.add_argument(
        "--full-scf-hybrid-artifact-dir",
        type=Path,
        default=None,
        help="Optional directory containing full-SCF evaluated-hybrid descriptor/schedule/residency/correctness/PPA-summary artifacts",
    )
    args = parser.parse_args(argv)
    status = write_dft_candidate_evidence_artifacts(
        args.out,
        release_artifact_dir=args.release_artifact_dir,
        mode_coverage_dir=args.mode_coverage_dir,
        timing_run_dir=args.timing_run_dir,
        ic_eda_tool_availability_path=args.ic_eda_tool_availability,
        dft_hardware_evidence_matrix_path=args.dft_hardware_evidence_matrix,
        full_scf_hybrid_artifact_dir=args.full_scf_hybrid_artifact_dir,
    )
    print(json.dumps(status, indent=2))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
