#!/usr/bin/env python3
"""Validate a canonical Step3 admission queue fail-closed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.dse.step3_admission_queue_validation import (  # noqa: E402
    load_json_mapping,
    validate_step3_admission_queue,
    write_step3_admission_queue_validation,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step3_queue", type=Path, help="Path to step2/step3_simulation_queue.json")
    parser.add_argument("--campaign-evaluation-plan", type=Path, default=None)
    parser.add_argument("--search-iteration-plan", type=Path, default=None)
    parser.add_argument("--campaign-search-admission-plan", type=Path, default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional output directory for step3_admission_queue_validation.json and status.json.",
    )
    args = parser.parse_args(argv)

    if args.out:
        status = write_step3_admission_queue_validation(
            step3_queue_path=args.step3_queue,
            campaign_evaluation_plan_path=args.campaign_evaluation_plan,
            search_iteration_plan_path=args.search_iteration_plan,
            campaign_search_admission_plan_path=args.campaign_search_admission_plan,
            out_dir=args.out,
        )
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0 if status["valid"] else 1

    validation = validate_step3_admission_queue(
        step3_simulation_queue=load_json_mapping(args.step3_queue),
        campaign_evaluation_plan=(
            load_json_mapping(args.campaign_evaluation_plan)
            if args.campaign_evaluation_plan and args.campaign_evaluation_plan.exists()
            else None
        ),
        search_iteration_plan=(
            load_json_mapping(args.search_iteration_plan)
            if args.search_iteration_plan and args.search_iteration_plan.exists()
            else None
        ),
        campaign_search_admission_plan=(
            load_json_mapping(args.campaign_search_admission_plan)
            if args.campaign_search_admission_plan and args.campaign_search_admission_plan.exists()
            else None
        ),
    )
    print(json.dumps(validation, indent=2, sort_keys=True))
    return 0 if validation["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
