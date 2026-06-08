#!/usr/bin/env python3
"""Build a measured QE workflow bundle and corpus from existing run artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


QE_NATIVE_WORKFLOW_BUNDLE_SCHEMA = "dse.qe.native_workflow_bundle.v1"
QE_WORKFLOW_CORPUS_SCHEMA = "dse.qe_fpga_workflow_corpus.v1"


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True, help="Directory containing measured QE run artifacts")
    parser.add_argument("--out", type=Path, required=True, help="Output bundle/corpus directory")
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--workload-id", required=True)
    parser.add_argument("--material", required=True)
    parser.add_argument("--size-class", required=True)
    parser.add_argument("--selection-policy", required=True)
    parser.add_argument("--scf-input", default="scf.in")
    parser.add_argument("--scf-log", default="scf.out")
    parser.add_argument("--nscf-input", default="")
    parser.add_argument("--nscf-log", default="")
    parser.add_argument("--save-dir", default="")
    parser.add_argument("--pseudopotential", action="append", default=[])
    parser.add_argument("--profile", action="append", default=[])
    return parser.parse_args(list(argv))


def _resolve_existing(path_value: str | Path, *, source_dir: Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = source_dir / path
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _relative_to_out(path: Path, *, out_dir: Path) -> str:
    return path.relative_to(out_dir).as_posix()


def _workflow_scope_from_stages(stages: Sequence[Dict[str, Any]]) -> str:
    stage_ids = {str(stage.get("stage_id", "")).lower() for stage in stages}
    if stage_ids == {"scf"}:
        return "scf_only_measured_seed"
    return "external_qe_workflow_corpus"


def _copy_run_artifacts(args: argparse.Namespace) -> Dict[str, Any]:
    source_dir = args.source_dir.resolve()
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    copied: Dict[str, Any] = {}

    scf_input = _resolve_existing(args.scf_input, source_dir=source_dir)
    scf_log = _resolve_existing(args.scf_log, source_dir=source_dir)
    _copy_file(scf_input, out_dir / "scf.in")
    _copy_file(scf_log, out_dir / "scf.out")
    copied["scf_input"] = "scf.in"
    copied["scf_log"] = "scf.out"

    if args.nscf_input:
        nscf_input = _resolve_existing(args.nscf_input, source_dir=source_dir)
        _copy_file(nscf_input, out_dir / "nscf.in")
        copied["nscf_input"] = "nscf.in"
    if args.nscf_log:
        nscf_log = _resolve_existing(args.nscf_log, source_dir=source_dir)
        _copy_file(nscf_log, out_dir / "nscf.out")
        copied["nscf_log"] = "nscf.out"

    if args.save_dir:
        save_dir = _resolve_existing(args.save_dir, source_dir=source_dir)
        if not save_dir.is_dir():
            raise ValueError(f"--save-dir must point to a directory: {save_dir}")
        copied_save = out_dir / "tmp" / save_dir.name
        _copy_tree(save_dir, copied_save)
        copied["save_dir"] = _relative_to_out(copied_save, out_dir=out_dir)

    pseudo_paths: List[str] = []
    for index, pseudo_value in enumerate(args.pseudopotential or []):
        pseudo_src = _resolve_existing(pseudo_value, source_dir=source_dir)
        pseudo_dst = out_dir / "pseudo" / pseudo_src.name
        _copy_file(pseudo_src, pseudo_dst)
        pseudo_paths.append(_relative_to_out(pseudo_dst, out_dir=out_dir))
    copied["pseudopotential_paths"] = pseudo_paths

    profile_paths: List[str] = []
    for profile_value in args.profile or []:
        profile_src = _resolve_existing(profile_value, source_dir=source_dir)
        profile_dst = out_dir / "profiles" / profile_src.name
        _copy_file(profile_src, profile_dst)
        profile_paths.append(_relative_to_out(profile_dst, out_dir=out_dir))
    copied["profile_paths"] = profile_paths
    return copied


def build_bundle_and_corpus(args: argparse.Namespace) -> Dict[str, Any]:
    copied = _copy_run_artifacts(args)
    out_dir = args.out
    scf_stage: Dict[str, Any] = {
        "stage_id": "scf",
        "program": "pw.x",
        "input_path": copied["scf_input"],
        "log_path": copied["scf_log"],
    }
    if copied.get("save_dir"):
        scf_stage["save_dir"] = copied["save_dir"]
    if copied.get("pseudopotential_paths"):
        scf_stage["pseudopotential_paths"] = list(copied["pseudopotential_paths"])
    if copied.get("profile_paths"):
        scf_stage["profile_path"] = copied["profile_paths"][0]

    stages: List[Dict[str, Any]] = [scf_stage]
    if copied.get("nscf_input") and copied.get("nscf_log"):
        stages.append({
            "stage_id": "nscf",
            "program": "pw.x",
            "input_path": copied["nscf_input"],
            "log_path": copied["nscf_log"],
            "depends_on": ["scf"],
        })

    bundle = {
        "schema_version": QE_NATIVE_WORKFLOW_BUNDLE_SCHEMA,
        "workflow_id": str(args.workflow_id),
        "measurement_source": "measured_qe_run",
        "selection_policy": str(args.selection_policy),
        "workflow_scope": _workflow_scope_from_stages(stages),
        "source_run_directory": str(args.source_dir),
        "stages": stages,
        "claim_boundary": "measured_qe_workflow_bundle_input_only_not_hardware_or_accelerated_correctness_evidence",
    }
    corpus = {
        "schema_version": QE_WORKFLOW_CORPUS_SCHEMA,
        "corpus_id": f"{args.workload_id}_measured_corpus",
        "primary_workload_id": str(args.workload_id),
        "workloads": [
            {
                "workload_id": str(args.workload_id),
                "bundle_path": ".",
                "material": str(args.material),
                "size_class": str(args.size_class),
                "measurement_source": "measured_qe_run",
                "selection_policy": str(args.selection_policy),
                "workflow_scope": bundle["workflow_scope"],
            }
        ],
        "workflow_scope": bundle["workflow_scope"],
    }
    bundle_path = out_dir / "workflow_bundle.json"
    corpus_path = out_dir / "workflow_corpus.json"
    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    corpus_path.write_text(json.dumps(corpus, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "status": "built",
        "workflow_bundle": str(bundle_path),
        "workflow_corpus": str(corpus_path),
        "stage_count": len(stages),
        "workflow_scope": bundle["workflow_scope"],
        "claim_boundary": bundle["claim_boundary"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = build_bundle_and_corpus(args)
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
