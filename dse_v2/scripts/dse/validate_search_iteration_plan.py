#!/usr/bin/env python3
"""Validate a Step2 search_iteration_plan.json artifact fail-closed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.mapping.search_plan_validation import (  # noqa: E402
    load_search_iteration_plan,
    validate_search_iteration_plan,
    write_search_iteration_plan_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="Path to search_iteration_plan.json")
    parser.add_argument(
        "--out",
        type=Path,
        help="Optional output directory for search_iteration_plan_validation.json and status.json.",
    )
    args = parser.parse_args()

    if args.out:
        status = write_search_iteration_plan_validation(args.plan, args.out)
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0 if status.get("valid") is True else 1

    validation = validate_search_iteration_plan(load_search_iteration_plan(args.plan))
    print(json.dumps(validation, indent=2, sort_keys=True))
    return 0 if validation.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
