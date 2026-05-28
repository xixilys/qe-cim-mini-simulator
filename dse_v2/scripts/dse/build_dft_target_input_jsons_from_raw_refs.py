#!/usr/bin/env python3
"""Build DFT FPGA/ASIC target input JSONs from hash-backed raw refs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_target_input_json_producer import (  # noqa: E402
    load_raw_ref_file,
    write_dft_target_input_jsons_from_raw_refs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument(
        "--fpga-raw-ref",
        type=Path,
        required=True,
        help="JSON object with path, sha256, and hash_algorithm for the raw FPGA capacity catalog",
    )
    parser.add_argument(
        "--asic-raw-ref",
        type=Path,
        required=True,
        help="JSON object with path, sha256, and hash_algorithm for the raw ASIC target-library probe",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress JSON status on stdout")
    args = parser.parse_args()

    fpga_ref, fpga_base_dir = load_raw_ref_file(args.fpga_raw_ref)
    asic_ref, asic_base_dir = load_raw_ref_file(args.asic_raw_ref)
    result = write_dft_target_input_jsons_from_raw_refs(
        args.out,
        fpga_raw_ref=fpga_ref,
        asic_raw_ref=asic_ref,
        fpga_ref_base_dir=fpga_base_dir,
        asic_ref_base_dir=asic_base_dir,
    )
    if not args.quiet:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result.get("blocked") is True else 0


if __name__ == "__main__":
    raise SystemExit(main())
