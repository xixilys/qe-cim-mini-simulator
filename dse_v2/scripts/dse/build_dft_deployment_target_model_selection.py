#!/usr/bin/env python3
"""Build a replayable DFT deployment target-model selection artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_deployment_target_model_selection import (  # noqa: E402
    write_dft_deployment_target_model_selection,
)


def _split_csv(values: Sequence[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for item in str(value).split(","):
            stripped = item.strip()
            if stripped:
                items.append(stripped)
    return items


def _parse_selected_model_ids(values: Sequence[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in _split_csv(values):
        if "=" in value:
            target, model_id = value.split("=", 1)
        elif ":" in value:
            target, model_id = value.split(":", 1)
        else:
            target, model_id = "fpga", value
        target = target.strip()
        model_id = model_id.strip()
        if target and model_id:
            parsed[target] = model_id
    return parsed


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--deployment-plan", type=Path, default=None)
    parser.add_argument("--target", action="append", default=[], help="Target filter; repeatable or comma-separated.")
    parser.add_argument("--candidate-id", action="append", default=[], help="Candidate filter; repeatable or comma-separated.")
    parser.add_argument(
        "--selected-model-id",
        action="append",
        default=[],
        help=(
            "Preferred model override as target=model_id, target:model_id, or "
            "a bare FPGA model id. FPGA overrides resolve through the deployment "
            "catalog/recommended candidates; ASIC overrides are interpreted as "
            "DC target-library names or .db paths. Repeatable or comma-separated."
        ),
    )
    parser.add_argument(
        "--vivado-supported-part",
        action="append",
        default=[],
        help=(
            "Vivado part/device observed by a real support probe. When combined "
            "with --prefer-fpga-model-with-supported-vivado-part, FPGA selection "
            "may choose a catalog/recommended model matching the probe instead "
            "of the default HBM target. Repeatable or comma-separated."
        ),
    )
    parser.add_argument(
        "--prefer-fpga-model-with-supported-vivado-part",
        action="store_true",
        help=(
            "If no explicit FPGA selected-model override/profile selected_model "
            "is present, prefer a recommended/catalog FPGA model whose Vivado "
            "part matches explicit probe-supported parts. This remains admission "
            "evidence only and does not upgrade smoke parts into deployment claims."
        ),
    )
    parser.add_argument(
        "--dc-supported-target-library",
        action="append",
        default=[],
        help="DC target library observed by probe/evidence; repeatable or comma-separated.",
    )
    parser.add_argument(
        "--dc-library-db-path",
        action="append",
        default=[],
        help="DC .db path observed as available to dc_shell; repeatable or comma-separated.",
    )
    parser.add_argument(
        "--allow-asic-model-inference-from-dc-probe",
        action="store_true",
        help="Emit an ASIC selected_model row inferred from explicit DC target-library probe inputs.",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = write_dft_deployment_target_model_selection(
        args.run_dir,
        out_path=args.out,
        deployment_plan_path=args.deployment_plan,
        targets=_split_csv(args.target),
        candidate_ids=_split_csv(args.candidate_id),
        selected_model_ids=_parse_selected_model_ids(args.selected_model_id),
        fpga_vivado_supported_parts=_split_csv(args.vivado_supported_part),
        prefer_fpga_model_with_supported_vivado_part=bool(
            args.prefer_fpga_model_with_supported_vivado_part
        ),
        dc_supported_target_libraries=_split_csv(args.dc_supported_target_library),
        dc_library_db_paths=_split_csv(args.dc_library_db_path),
        allow_asic_model_inference_from_dc_probe=args.allow_asic_model_inference_from_dc_probe,
    )
    if not args.quiet:
        print(json.dumps(status, indent=2, sort_keys=True))
    if status.get("validation_status") != "passed":
        return 1
    if str(status.get("status", "")).startswith("blocked"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
