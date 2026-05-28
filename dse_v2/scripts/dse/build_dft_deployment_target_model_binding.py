#!/usr/bin/env python3
"""Build a fail-closed deployment target model-binding artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_candidate_specific_ppa_execution import (  # noqa: E402
    vivado_part_support_probe_inputs,
    write_dft_deployment_target_model_binding,
)


def _split_csv(values: Sequence[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for item in str(value).split(","):
            stripped = item.strip()
            if stripped:
                items.append(stripped)
    return items


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True, help="dft_deployment_hard_gate_execution_queue.json")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--vivado-supported-part",
        action="append",
        default=[],
        help="Vivado part/device observed as supported by a real tool probe; repeatable or comma-separated.",
    )
    parser.add_argument(
        "--vivado-part-probe-attempted",
        action="store_true",
        help="Record that a real Vivado part-support probe was attempted even if no matching parts were found.",
    )
    parser.add_argument(
        "--vivado-part-support-probe",
        type=Path,
        action="append",
        default=[],
        help=(
            "dft_vivado_part_support_probe.json (or compatible) artifact. "
            "Supported parts are imported from the artifact, and probe attempted "
            "is recorded even when no requested parts matched."
        ),
    )
    parser.add_argument(
        "--dc-supported-target-library",
        action="append",
        default=[],
        help="DC target library observed as supported by a real probe/evidence; repeatable or comma-separated.",
    )
    parser.add_argument(
        "--dc-library-db-path",
        action="append",
        default=[],
        help="DC .db path observed as available to dc_shell; repeatable or comma-separated.",
    )
    parser.add_argument(
        "--dc-target-library-probe-attempted",
        action="store_true",
        help="Record that a real dc_shell target-library probe/evidence check was attempted.",
    )
    parser.add_argument(
        "--allow-asic-model-inference-from-dc-probe",
        action="store_true",
        help=(
            "Allow a missing ASIC selected_model to be inferred from explicit DC "
            "target-library probe inputs. The inferred row remains admission evidence only."
        ),
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    probe_supported_parts, probe_attempted = vivado_part_support_probe_inputs(args.vivado_part_support_probe)
    status = write_dft_deployment_target_model_binding(
        args.queue,
        out_path=args.out,
        vivado_supported_parts=sorted(
            dict.fromkeys([*_split_csv(args.vivado_supported_part), *probe_supported_parts])
        ),
        vivado_part_probe_attempted=args.vivado_part_probe_attempted or probe_attempted,
        dc_supported_target_libraries=_split_csv(args.dc_supported_target_library),
        dc_library_db_paths=_split_csv(args.dc_library_db_path),
        dc_target_library_probe_attempted=args.dc_target_library_probe_attempted,
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
