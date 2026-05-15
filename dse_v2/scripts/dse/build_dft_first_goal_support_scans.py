#!/usr/bin/env python3
"""Build reusable support scans for the DFT-first goal completion audit.

The goal completion auditor intentionally consumes explicit guard/probe JSON
artifacts instead of silently trusting transient command output.  This helper
regenerates the support scans that are safe to compute from the current working
tree and completed DFT-first run directories:

* no-smoke/demo/skip/fallback guard over the selected Step4 gem5 evidence,
* domain-boundary scan for DFT/QE terms leaking into generic core/mapping code,
* public/open-source reference anchors with claim boundaries.

Tamper probes remain separate because they intentionally copy and mutate run
artifacts.  Pass their existing JSON to ``audit_dft_first_goal_completion.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.scripts.dse.audit_dft_first_end_to_end_run import (  # noqa: E402
    _command_from_manifest,
    _forbidden_no_smoke_tokens,
    audit_run,
)


SUPPORT_SCAN_SCHEMA = "dse.dft_first.goal_support_scans.v1"
NO_SMOKE_SCHEMA = "dse.dft_first.no_smoke_guard_scan.v3"
DOMAIN_SCHEMA = "dse.dft_first.domain_boundary_scan.v1"
EXTERNAL_SCHEMA = "dse.dft_first.external_reference_scan.v2"

BLOCKED_DOMAIN_TERMS = [
    "dft",
    "qe",
    "quantum espresso",
    "pw.x",
    "pwscf",
    "kohn",
    "sham",
]


def _date_text() -> str:
    return subprocess.check_output(["date", "+%Y-%m-%d %H:%M:%S %Z (%z)"], text=True).strip()


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _audit_check(audit: Mapping[str, Any], check_id: str) -> Dict[str, Any]:
    for check in audit.get("checks", []) or []:
        if isinstance(check, Mapping) and check.get("check_id") == check_id:
            return dict(check)
    return {}


def _selected_step4(summary: Mapping[str, Any]) -> tuple[str, Path, Mapping[str, Any]]:
    step4 = summary.get("step4_gem5")
    if not isinstance(step4, Mapping):
        raise ValueError("summary is missing step4_gem5")
    architecture_id = str(step4.get("architecture_id") or "")
    run_dir = step4.get("run_dir")
    if not architecture_id or not run_dir:
        raise ValueError("step4_gem5 is missing architecture_id or run_dir")
    return architecture_id, Path(str(run_dir)), step4


def build_no_smoke_guard_scan(run_dirs: Sequence[Path]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for run_dir in run_dirs:
        summary = _load_json(run_dir / "dft_end_to_end_summary.json")
        architecture_id, step4_dir, step4 = _selected_step4(summary)
        proof = _load_json(step4_dir / "gem5_l4_proof.json")
        manifest = _load_json(step4_dir / "manifest.json")
        replay_cmd = _command_from_manifest(manifest)
        audit = audit_run(run_dir)
        formal = _audit_check(audit, "step4_no_smoke_demo_or_fallback_tokens")
        source_artifacts = proof.get("source_artifacts") if isinstance(proof.get("source_artifacts"), Mapping) else {}
        source_fallback = source_artifacts.get("fallback_from_gem5", proof.get("fallback_from_gem5"))
        item = {
            "run": str(run_dir),
            "architecture_id": architecture_id,
            "step4_dir": str(step4_dir),
            "proof_passed": proof.get("passed"),
            "fallback_from_gem5": proof.get("fallback_from_gem5"),
            "source_artifacts_fallback_from_gem5": source_fallback,
            "transport_harness": proof.get("transport_harness") or source_artifacts.get("transport_harness"),
            "trusted_step4_timing": step4.get("trusted_step4_timing"),
            "formal_audit_check_present": bool(formal),
            "formal_audit_check_passed": formal.get("passed") is True,
            "manifest_has_gem5_binary": any(
                str(token).endswith("gem5.opt") or "/gem5." in str(token)
                for token in replay_cmd
            ),
            "manifest_has_generic_accel_config": any("generic_accel" in str(token).lower() for token in replay_cmd),
            "manifest_has_required_runtime_args": "--request" in replay_cmd and "--simulator" in replay_cmd,
            "forbidden_token_hits": _forbidden_no_smoke_tokens(replay_cmd),
        }
        item["passed_guard"] = all([
            item["proof_passed"] is True,
            item["fallback_from_gem5"] is False,
            item["source_artifacts_fallback_from_gem5"] is False,
            item["transport_harness"] == "gem5_generic_accel_microarchitecture_v1",
            item["trusted_step4_timing"] is True,
            item["formal_audit_check_present"],
            item["formal_audit_check_passed"],
            item["manifest_has_gem5_binary"],
            item["manifest_has_generic_accel_config"],
            item["manifest_has_required_runtime_args"],
            not item["forbidden_token_hits"],
        ])
        items.append(item)
    return {
        "schema_version": NO_SMOKE_SCHEMA,
        "checked_at_local": _date_text(),
        "status": "passed" if items and all(item["passed_guard"] for item in items) else "failed",
        "forbidden_patterns": [
            "--skip-gem5-l4",
            "smoke_not_non_smoke",
            "demo",
            "fallback_from_gem5:true",
        ],
        "items": items,
    }


def _iter_scannable_files(roots: Iterable[Path]) -> Iterable[Path]:
    suffixes = {".py", ".md", ".json", ".yaml", ".yml", ".txt"}
    for root in roots:
        if root.is_file():
            if root.suffix in suffixes:
                yield root
            continue
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                yield path


def build_domain_boundary_scan(scan_roots: Sequence[Path]) -> Dict[str, Any]:
    patterns = [
        (
            term,
            re.compile(r"(?i)(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])"),
        )
        for term in BLOCKED_DOMAIN_TERMS
    ]
    fft_pattern = re.compile(r"(?i)(?<![a-z0-9_])fft(?![a-z0-9_])")
    blocked_hits: List[Dict[str, Any]] = []
    context_hits: List[Dict[str, Any]] = []
    for path in _iter_scannable_files(scan_roots):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, 1):
            for term, pattern in patterns:
                if pattern.search(line):
                    blocked_hits.append({
                        "path": str(path),
                        "line": line_number,
                        "term": term,
                        "text": line.strip(),
                    })
            if fft_pattern.search(line):
                context_hits.append({
                    "path": str(path),
                    "line": line_number,
                    "classification": "generic_fft_not_dft_specific",
                    "text": line.strip(),
                })
    return {
        "schema_version": DOMAIN_SCHEMA,
        "checked_at_local": _date_text(),
        "status": "passed" if not blocked_hits else "failed",
        "scanned_roots": [str(root) for root in scan_roots],
        "blocked_terms": BLOCKED_DOMAIN_TERMS,
        "blocked_hit_count": len(blocked_hits),
        "blocked_hits": blocked_hits,
        "context_hits": context_hits,
        "claim_boundary": (
            "DFT/QE-specific parsing/policy stays under dse_v2/reference_workloads; "
            "core/mapping may contain generic workflow/kernel vocabulary such as FFT "
            "only when domain-neutral."
        ),
    }


def build_external_reference_scan() -> Dict[str, Any]:
    sources = [
        {
            "id": "qe_gitlab_official",
            "type": "official_repository",
            "url": "https://gitlab.com/QEF/q-e",
            "observed_fact": (
                "Official QEF/q-e repository identifies Quantum ESPRESSO as an "
                "open-source electronic-structure suite and exposes PW, FFTXlib, "
                "KS_Solvers, LAXlib, PHonon, and related packages."
            ),
            "local_use": "Step1 source-provenance anchor and official example workflow source.",
            "claim_boundary": "No DFT numerical correctness is claimed from repository layout.",
        },
        {
            "id": "qe_pw_user_guide",
            "type": "official_documentation",
            "url": "https://www.quantum-espresso.org/Doc/pw_user_guide/",
            "observed_fact": "PWscf user guide documents pw.x workflows, input data, performance reports, and troubleshooting.",
            "local_use": "Step1 QE input/log/workflow parsing semantics for pw.x-style workloads.",
            "claim_boundary": "Final ranking still requires measured local artifacts.",
        },
        {
            "id": "qe_input_pw_reference",
            "type": "official_documentation",
            "url": "https://www.quantum-espresso.org/Doc/INPUT_PW.html",
            "observed_fact": "INPUT_PW documents pw.x/PWscf input variables.",
            "local_use": "Source-fact parser vocabulary for Step1 QE input extraction.",
            "claim_boundary": "Used for field vocabulary only.",
        },
        {
            "id": "qe_exascale_gpu_paper",
            "type": "paper",
            "url": "https://arxiv.org/abs/2104.10502",
            "observed_fact": "Quantum ESPRESSO toward the exascale discusses heterogeneous accelerator architectures.",
            "local_use": "Candidate-generation motivation for accelerator-oriented phase hints.",
            "claim_boundary": "No paper-derived performance number enters the best-architecture claim.",
        },
        {
            "id": "fpga_electronic_structure_arxiv_2602_11702",
            "type": "paper",
            "url": "https://arxiv.org/abs/2602.11702",
            "observed_fact": (
                "Recent FPGA electronic-structure work reports hardware-native "
                "streaming Hamiltonian generation/eigensolver ideas for "
                "semi-empirical methods such as EHT and DFTB0."
            ),
            "local_use": (
                "Future reference for FPGA dataflow/eigensolver candidate ideas; "
                "not a QE plane-wave DFT correctness or performance source."
            ),
            "claim_boundary": "No final DFT/QE architecture ranking claim is derived from this paper.",
        },
        {
            "id": "gem5_build_docs",
            "type": "official_documentation",
            "url": "https://www.gem5.org/documentation/general_docs/building",
            "observed_fact": "gem5 docs describe compiled gem5.opt invocation with simulation scripts and options.",
            "local_use": "Step4 real gem5 manifest/replay command boundary.",
            "claim_boundary": "Local GenericAccel proof/log/stats artifacts carry the actual evidence.",
        },
        {
            "id": "timeloop_accelergy_overview",
            "type": "official_project_documentation",
            "url": "https://timeloop.csail.mit.edu/",
            "observed_fact": "Timeloop/Accelergy documents accelerator modeling and mapping infrastructure.",
            "local_use": "Future reference for mapspace/architecture/cost-model separation.",
            "claim_boundary": "Current flow does not embed Timeloop.",
        },
        {
            "id": "maestro_github",
            "type": "open_source_repository",
            "url": "https://github.com/maestro-project/maestro",
            "observed_fact": "MAESTRO describes an analytical cost model for dataflows and tiling.",
            "local_use": "Future reference for data-centric modeling boundaries.",
            "claim_boundary": "Current Step2 hints do not claim MAESTRO-equivalent accuracy.",
        },
        {
            "id": "aladdin_github",
            "type": "open_source_repository",
            "url": "https://github.com/harvard-acc/ALADDIN",
            "observed_fact": "ALADDIN describes a pre-RTL simulator for fixed-function accelerators.",
            "local_use": "Future pre-RTL accelerator model/calibration reference.",
            "claim_boundary": "Current Step4 evidence is gem5-local; no Aladdin model is used.",
        },
        {
            "id": "accellera_systemc_downloads",
            "type": "official_standard_documentation",
            "url": "https://www.accellera.org/downloads/standards/systemc",
            "observed_fact": "Accellera distributes SystemC and TLM reference material.",
            "local_use": "Terminology boundary for Step3 SystemC-style timing simulation.",
            "claim_boundary": "generic_sim is local measured evidence, not a full SystemC compliance claim.",
        },
    ]
    return {
        "schema_version": EXTERNAL_SCHEMA,
        "checked_at_local": _date_text(),
        "status": "passed",
        "purpose": (
            "Refresh public/open-source project and paper anchors; preserve claim "
            "boundaries so final ranking remains based on local measured artifacts."
        ),
        "sources": sources,
        "integration_decision": {
            "adopt_now": [
                "QE official source/input documentation for Step1 provenance",
                "gem5 real-run invocation boundary for Step4 evidence",
                "SystemC reference boundary as Step3 timing-model terminology only",
            ],
            "future_candidates_only": [
                "Timeloop/Accelergy",
                "MAESTRO",
                "ALADDIN",
                "FPGA electronic-structure dataflow/eigensolver literature",
            ],
            "no_final_claim_from_external_models": True,
        },
    }


def build_goal_support_scans(
    *,
    main_run: Path,
    official_run: Path,
    out_dir: Path,
    scan_roots: Optional[Sequence[Path]] = None,
) -> Dict[str, Any]:
    roots = list(scan_roots) if scan_roots is not None else [Path("dse_v2/core"), Path("dse_v2/mapping")]
    outputs = {
        "no_smoke_scan": out_dir / "no_smoke_guard_scan.json",
        "domain_boundary_scan": out_dir / "domain_boundary_scan.json",
        "external_reference_scan": out_dir / "external_reference_scan.json",
    }
    no_smoke = build_no_smoke_guard_scan([main_run, official_run])
    domain = build_domain_boundary_scan(roots)
    external = build_external_reference_scan()
    _write_json(outputs["no_smoke_scan"], no_smoke)
    _write_json(outputs["domain_boundary_scan"], domain)
    _write_json(outputs["external_reference_scan"], external)
    manifest = {
        "schema_version": SUPPORT_SCAN_SCHEMA,
        "checked_at_local": _date_text(),
        "status": "passed" if (
            no_smoke.get("status") == "passed"
            and domain.get("status") == "passed"
            and external.get("status") == "passed"
        ) else "failed",
        "main_run": str(main_run),
        "official_run": str(official_run),
        "outputs": {key: str(value) for key, value in outputs.items()},
        "tamper_probe_required_separately": True,
    }
    _write_json(out_dir / "support_scan_manifest.json", manifest)
    return manifest


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-run", type=Path, required=True)
    parser.add_argument("--official-run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--scan-root",
        type=Path,
        action="append",
        default=None,
        help="Root to scan for DFT/QE leakage; defaults to dse_v2/core and dse_v2/mapping.",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    manifest = build_goal_support_scans(
        main_run=args.main_run,
        official_run=args.official_run,
        out_dir=args.out,
        scan_roots=args.scan_root,
    )
    if not args.quiet:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
