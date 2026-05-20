#!/usr/bin/env python3
"""Build a DFT/QE major-kernel hardware evidence matrix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.dft_hardware_evidence import build_major_kernel_evidence_matrix  # noqa: E402


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(payload: Any, key: str) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        rows = payload.get(key, payload.get("rows", []))
        return [item for item in rows if isinstance(item, Mapping)] if isinstance(rows, list) else []
    return []


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-dispositions", type=Path, required=True)
    parser.add_argument("--evidence-rows", type=Path)
    parser.add_argument("--candidate-id")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    dispositions = _rows(_load_json(args.kernel_dispositions), "kernel_dispositions")
    evidence_rows = _rows(_load_json(args.evidence_rows), "evidence_rows") if args.evidence_rows else []
    matrix = build_major_kernel_evidence_matrix(
        dispositions,
        evidence_rows=evidence_rows,
        candidate_id=args.candidate_id,
    )
    output_path = args.out / "dft_hardware_evidence_matrix.json"
    _write_json(output_path, matrix)
    print(json.dumps({
        "schema_version": "dse.dft_scf.hardware_evidence_matrix_cli_status.v1",
        "status": matrix["status"],
        "trusted": matrix["trusted"],
        "dft_hardware_evidence_matrix": str(output_path),
        "blocker_count": len(matrix["blockers"]),
    }, indent=2, sort_keys=True))
    return 0 if matrix["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

