#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import gmtime, strftime
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "qe_candidate_evidence_manifest_v0"


class CandidateManifestError(ValueError):
    pass


def load_json(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CandidateManifestError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve(ref: Any, base: Path) -> Path | None:
    if not isinstance(ref, str) or not ref:
        return None
    path = Path(ref)
    if path.is_absolute():
        return path.resolve(strict=False)
    return (base / path).resolve(strict=False)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _request_context(request_path: Path | None) -> dict[str, Any]:
    if request_path is None or not request_path.exists():
        return {}
    payload = load_json(request_path)
    candidate_identity = _mapping(payload.get("candidate_identity"))
    design_axes = _mapping(candidate_identity.get("design_axes"))
    workload_identity = _mapping(payload.get("workload_identity"))
    domain_extension = _mapping(payload.get("domain_extension"))
    qe_extension = _mapping(domain_extension.get("qe"))
    candidate_id = payload.get("candidate_id") or candidate_identity.get("candidate_id") or request_path.stem
    workload_id = workload_identity.get("workload_id") or qe_extension.get("workload_id") or qe_extension.get("case_id")
    case_id = qe_extension.get("case_id") or workload_id
    family = design_axes.get("family") or candidate_identity.get("architecture_template_id")
    return {
        "candidate_id": str(candidate_id) if candidate_id is not None else None,
        "family": str(family) if family is not None else None,
        "workload_id": str(workload_id) if workload_id is not None else None,
        "case_id": str(case_id) if case_id is not None else None,
        "design_axes": dict(design_axes),
        "candidate_identity": dict(candidate_identity),
    }


def build_manifest(e2e_manifest_path: Path, *, output_ref: Path | None = None) -> dict[str, Any]:
    e2e_manifest = load_json(e2e_manifest_path)
    base = e2e_manifest_path.resolve().parent
    runs = e2e_manifest.get("candidate_runs")
    if not isinstance(runs, list):
        raise CandidateManifestError("E2E manifest must contain candidate_runs list")
    candidates: list[dict[str, Any]] = []
    for index, run in enumerate(runs):
        if not isinstance(run, Mapping):
            raise CandidateManifestError(f"candidate_runs[{index}] must be an object")
        request_path = _resolve(run.get("stage_b0_request"), base)
        context = _request_context(request_path)
        candidate_id = str(run.get("candidate_id") or context.get("candidate_id") or (request_path.stem if request_path else f"candidate_{index}"))
        candidates.append(
            {
                "candidate_id": candidate_id,
                "family": context.get("family"),
                "workload_id": context.get("workload_id"),
                "case_id": context.get("case_id"),
                "implementation_target_class": "fpga",
                "stage_b0_request": str(request_path) if request_path is not None else run.get("stage_b0_request"),
                "systemc_backend_report": run.get("systemc_backend_report"),
                "gem5_b4_report": run.get("gem5_b4_report"),
                "gem5_b4_materialization_manifest": run.get("gem5_b4_materialization_manifest"),
                "design_axes": context.get("design_axes", {}),
                "candidate_identity": context.get("candidate_identity", {}),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
        "source_e2e_manifest": str(e2e_manifest_path),
        "manifest_ref": str(output_ref) if output_ref is not None else None,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "non_claims": [
            "candidate_manifest_is_join_key_only",
            "no_qe_correctness_claim",
            "no_implementation_evidence_claim",
            "no_final_best_architecture_claim",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build candidate evidence manifest for QE FPGA final-best evidence producers.")
    parser.add_argument("--e2e-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_manifest(args.e2e_manifest, output_ref=args.output)
    write_json(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
