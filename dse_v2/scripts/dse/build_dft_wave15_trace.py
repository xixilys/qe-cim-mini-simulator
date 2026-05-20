#!/usr/bin/env python3
"""Build a replayable Wave 1.5 DFT/QE progress-only trace bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.dft_scf_workstreams import (
    STRICT_DFT_QE_WORKLOAD_CLASSES,
    build_wave15_trace,
)


def _load_json(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _strict_case(workload_class: str) -> Dict[str, Any]:
    return {
        "case_id": f"{workload_class}_case",
        "workload_class": workload_class,
        "qe_input": f"&CONTROL calculation='{workload_class}' /",
        "pseudopotentials": ["Si.pz-vbc.UPF"],
        "run_command": ["pw.x", "-in", f"{workload_class}.in"],
        "reference_output_hash": f"sha256:{workload_class}",
        "provenance": {
            "source": "wave15-fixture",
            "license": "fixture-only",
        },
        "parser_version": "qe-parser-v1",
        "tool_version": "qe-7.x-fixture",
        "proof_class": "strict_replay_fixture",
    }


def default_strict_bundle() -> Dict[str, Any]:
    return {
        "bundle_id": "wave15-strict-qe-six-class",
        "campaign_id": "campaign-wave15",
        "workload_run_id": "workload-wave15",
        "strict": True,
        "workload_classes": list(STRICT_DFT_QE_WORKLOAD_CLASSES),
        "cases": [_strict_case(workload_class) for workload_class in STRICT_DFT_QE_WORKLOAD_CLASSES],
    }


def default_release_candidate() -> Dict[str, Any]:
    return {
        "candidate_id": "release-dma-hbm-wave15",
        "release_policy": {
            "lane": "release",
            "formal_pareto_allowed": True,
            "exploratory_only": False,
            "authority": "wave15.default_release_candidate",
        },
        "release_lane": "release",
        "seed_source": "release_seed_manifest",
        "trial_id": "trial-wave15",
        "metrics": {
            "kernel_speedup": 3.0,
            "baseline_scf_time_s": 30.0,
            "accelerated_scf_time_s": 20.0,
            "end_to_end_scf_time_s": 20.0,
        },
        "costs": {
            "host_bound_compute_cost_s": 10.0,
            "transfer_cost_s": 2.0,
            "synchronization_cost_s": 1.0,
            "queueing_cost_s": 1.0,
            "layout_cost_s": 1.0,
        },
        "cpu_bound_costs_s": {
            "io": 1.0,
            "scf_control": 2.0,
            "convergence": 3.0,
            "diagonalization": 4.0,
            "mixing": 1.0,
        },
        "claim_eligibility": {
            "formal_pareto": True,
            "deliverable_complete": False,
        },
    }


def default_tool_evidence() -> Dict[str, Any]:
    return {
        "evidence_rows": [
            {"evidence_class": "golden_correctness", "status": "passed"},
            {"evidence_class": "hls_csim", "status": "passed"},
            {"evidence_class": "hls_csynth", "status": "passed"},
            {
                "evidence_class": "vivado_synth",
                "status": "unavailable",
                "command": "vivado -mode batch -source wave15_dma_hbm.tcl",
                "environment": "wave15 fixture unless overridden",
                "failure_evidence": "tool transcript not attached in default fixture",
            },
        ],
    }


def render_wave15_runbook(trace: Mapping[str, Any]) -> str:
    chain = trace.get("artifact_chain", [])
    lines = [
        "# Wave 1.5 DFT/QE Progress-Only Trace Runbook",
        "",
        "This bundle is a **progress-only** Step1→Step5 pressure test.  It is not MVP, not vertical-slice completion, and not final DFT/QE full-SCF hardware DSE closure.",
        "",
        "## Replay command",
        "",
        "```bash",
        "python3 dse_v2/scripts/dse/build_dft_wave15_trace.py --out runs/dse/<wave15_trace_run>",
        "```",
        "",
        "## Artifact chain",
        "",
    ]
    for item in chain if isinstance(chain, list) else []:
        if not isinstance(item, Mapping):
            continue
        lines.append(f"- {item.get('step')}: `{item.get('artifact')}` → `{item.get('status')}`")
    lines.extend([
        "",
        "## Claim boundary",
        "",
        str(trace.get("claim_boundary")),
        "",
        "## Required outputs",
        "",
        "- `strict_workload_bundle.json`",
        "- `release_candidate.json`",
        "- `tool_evidence.json`",
        "- `wave15_trace.json`",
        "- `wave15_summary.json`",
        "- `wave15_runbook.md`",
        "",
    ])
    return "\n".join(lines)


def build_wave15_trace_artifacts(
    out_dir: Path,
    *,
    strict_bundle: Optional[Mapping[str, Any]] = None,
    release_candidate: Optional[Mapping[str, Any]] = None,
    tool_evidence: Optional[Mapping[str, Any]] = None,
    claim_type: str = "fpga",
) -> Dict[str, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    strict_payload = dict(strict_bundle) if isinstance(strict_bundle, Mapping) and strict_bundle else default_strict_bundle()
    candidate_payload = dict(release_candidate) if isinstance(release_candidate, Mapping) and release_candidate else default_release_candidate()
    evidence_payload = dict(tool_evidence) if isinstance(tool_evidence, Mapping) and tool_evidence else default_tool_evidence()
    trace = build_wave15_trace(
        strict_bundle=strict_payload,
        release_candidate=candidate_payload,
        tool_evidence=evidence_payload,
        claim_type=claim_type,
    )
    summary = {
        "schema_version": "dse.dft_scf.wave15_trace_summary.v1",
        "status": trace.get("status"),
        "progress_only": trace.get("progress_only"),
        "completion_claim": trace.get("completion_claim"),
        "mvp_claim": trace.get("mvp_claim"),
        "claim_type": claim_type,
        "campaign_id": trace.get("campaign_id"),
        "workload_run_id": trace.get("workload_run_id"),
        "trial_id": trace.get("trial_id"),
        "step_chain_status": [
            {"step": item.get("step"), "status": item.get("status")}
            for item in trace.get("artifact_chain", [])
            if isinstance(item, Mapping)
        ],
        "claim_boundary": trace.get("claim_boundary"),
    }
    outputs = {
        "strict_workload_bundle": "strict_workload_bundle.json",
        "release_candidate": "release_candidate.json",
        "tool_evidence": "tool_evidence.json",
        "wave15_trace": "wave15_trace.json",
        "wave15_summary": "wave15_summary.json",
        "wave15_runbook": "wave15_runbook.md",
    }
    _write_json(out_dir / outputs["strict_workload_bundle"], strict_payload)
    _write_json(out_dir / outputs["release_candidate"], candidate_payload)
    _write_json(out_dir / outputs["tool_evidence"], evidence_payload)
    _write_json(out_dir / outputs["wave15_trace"], trace)
    _write_json(out_dir / outputs["wave15_summary"], summary)
    (out_dir / outputs["wave15_runbook"]).write_text(render_wave15_runbook(trace), encoding="utf-8")
    return outputs


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--strict-bundle-json", type=Path, default=None)
    parser.add_argument("--release-candidate-json", type=Path, default=None)
    parser.add_argument("--tool-evidence-json", type=Path, default=None)
    parser.add_argument("--claim-type", choices=["fpga", "asic"], default="fpga")
    return parser.parse_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    outputs = build_wave15_trace_artifacts(
        args.out,
        strict_bundle=_load_json(args.strict_bundle_json),
        release_candidate=_load_json(args.release_candidate_json),
        tool_evidence=_load_json(args.tool_evidence_json),
        claim_type=args.claim_type,
    )
    print(json.dumps({"out_dir": str(args.out), "outputs": outputs}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
