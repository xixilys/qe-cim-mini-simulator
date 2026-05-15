#!/usr/bin/env python3
"""Emit complete-DSE search-space foundation artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dse_v2.codesign.complete_dse_search_space import write_complete_dse_search_space_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output directory for JSON artifacts.")
    args = parser.parse_args()
    status = write_complete_dse_search_space_artifacts(args.out)
    print(json.dumps(status, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
