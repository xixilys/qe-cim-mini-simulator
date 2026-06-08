#!/usr/bin/env python3
"""Import measured QE reference-run artifacts as a workflow corpus."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.scripts.dse.build_qe_measured_workflow_bundle import build_bundle_and_corpus  # noqa: E402
from dse_v2.scripts.dse.run_qe_fpga_deployment_dse import build_qe_fpga_workflow_corpus_report  # noqa: E402
from dse_v2.reference_workloads.qe_workflow_fpga_abstraction import load_qe_workflow_bundle  # noqa: E402


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--corpus-id", required=True)
    parser.add_argument("--selection-policy", required=True)
    parser.add_argument("--case-limit", type=int, default=0)
    return parser.parse_args(list(argv))


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _reference_manifest_path(root: Path) -> Path:
    if root.is_file():
        return root
    for name in (
        "dft_scf_six_class_bundle_manifest.json",
        "reference_bundle_manifest.json",
        "manifest.json",
    ):
        candidate = root / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"reference bundle manifest not found under {root}")


def _resolve_ref(path_value: str | Path, *, root: Path) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else root / path


def _case_id(case: Mapping[str, Any], index: int) -> str:
    return str(
        case.get("class_id")
        or case.get("workload_class")
        or case.get("case_id")
        or f"reference_case_{index:03d}"
    )


def _case_material(case: Mapping[str, Any]) -> str:
    pseudos = [row for row in case.get("pseudopotentials", []) or case.get("pseudo_refs", []) or [] if isinstance(row, Mapping)]
    elements = [str(row.get("element", "")).strip() for row in pseudos if str(row.get("element", "")).strip()]
    if elements:
        return "+".join(sorted(set(elements)))
    label = str(case.get("label") or case.get("workload_class") or case.get("class_id") or "unknown")
    return label.split("_")[0] or "unknown"


def _case_size_class(case: Mapping[str, Any]) -> str:
    workload_class = str(case.get("workload_class") or case.get("class_id") or "")
    if "large" in workload_class or "heavy" in workload_class:
        return "medium"
    if "supercell" in workload_class or "slab" in workload_class:
        return "small_medium"
    return "small"


def _case_ref_path(case: Mapping[str, Any], *keys: str) -> str:
    current: Any = case
    for key in keys:
        if not isinstance(current, Mapping):
            return ""
        current = current.get(key)
    return str(current or "")


def _case_workflow_bundle_path(case: Mapping[str, Any]) -> str:
    for key in ("workflow_bundle", "bundle_path"):
        value = case.get(key)
        if isinstance(value, Mapping):
            path = value.get("path") or value.get("bundle_path") or value.get("manifest")
            if path:
                return str(path)
        elif value:
            return str(value)
    return ""


def _pseudo_paths(case: Mapping[str, Any], *, root: Path) -> List[Path]:
    rows = [row for row in case.get("pseudopotentials", []) or case.get("pseudo_refs", []) or [] if isinstance(row, Mapping)]
    return [_resolve_ref(str(row.get("path")), root=root) for row in rows if row.get("path")]


def _stage_type(stage: Mapping[str, Any]) -> str:
    explicit = str(stage.get("stage_type", "")).strip().lower().replace("-", "_")
    if explicit:
        return explicit
    program = str(stage.get("program", "")).strip().lower()
    if program in {"dos.x", "projwfc.x", "bands.x"}:
        return program.removesuffix(".x")
    input_text = "\n".join(
        str(stage.get(key, ""))
        for key in ("input", "pw_input", "input_text")
        if stage.get(key)
    ).lower()
    for stage_type in ("vc-relax", "vc_relax", "relax", "nscf", "scf", "bands", "dos", "projwfc"):
        if stage_type.replace("_", "-") in input_text or stage_type in input_text:
            return stage_type.replace("-", "_")
    stage_id = str(stage.get("stage_id", "")).strip().lower()
    for stage_type in ("vc_relax", "relax", "nscf", "scf", "bands", "dos", "projwfc"):
        if stage_type in stage_id:
            return stage_type
    return "unknown"


def _infer_workflow_scope(bundle: Mapping[str, Any]) -> str:
    explicit = str(bundle.get("workflow_scope", "")).strip()
    if explicit:
        return explicit
    stage_types = {
        _stage_type(stage)
        for stage in bundle.get("stages", []) or []
        if isinstance(stage, Mapping)
    }
    stage_types.discard("unknown")
    return "scf_only_measured_seed" if stage_types == {"scf"} else "external_qe_workflow_corpus"


def _copy_existing_workflow_bundle(source: Path, out_dir: Path) -> Path:
    loaded = load_qe_workflow_bundle(source)
    manifest_path = Path(str(loaded.get("_bundle_manifest_path", source))).resolve()
    source_dir = manifest_path.parent
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(source_dir, out_dir)
    return out_dir / manifest_path.name


def _build_existing_workflow_bundle_case(
    *,
    case: Mapping[str, Any],
    index: int,
    root: Path,
    out_dir: Path,
    selection_policy: str,
) -> Dict[str, Any]:
    workload_id = _case_id(case, index)
    bundle_dir = out_dir / "bundles" / workload_id
    source_bundle = _resolve_ref(_case_workflow_bundle_path(case), root=root)
    copied_manifest = _copy_existing_workflow_bundle(source_bundle, bundle_dir)
    bundle = load_qe_workflow_bundle(copied_manifest)
    scope = _infer_workflow_scope(bundle)
    bundle["measurement_source"] = str(bundle.get("measurement_source", "")) or "measured_qe_run"
    bundle["selection_policy"] = str(bundle.get("selection_policy", "")) or selection_policy
    bundle["workflow_scope"] = scope
    bundle["claim_boundary"] = str(
        bundle.get("claim_boundary", "")
        or "measured_qe_workflow_bundle_input_only_not_hardware_or_accelerated_correctness_evidence"
    )
    copied_manifest.write_text(
        json.dumps(
            {key: value for key, value in bundle.items() if not str(key).startswith("_bundle_")},
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    return {
        "workload_id": workload_id,
        "bundle_path": f"bundles/{workload_id}",
        "material": _case_material(case),
        "size_class": _case_size_class(case),
        "measurement_source": "measured_qe_run",
        "workflow_scope": scope,
        "selection_policy": selection_policy,
        "source_case": {
            "case_id": str(case.get("case_id", "")),
            "class_id": str(case.get("class_id", "")),
            "workload_class": str(case.get("workload_class", "")),
            "label": str(case.get("label", "")),
            "source_workflow_bundle": str(source_bundle),
        },
        "build_status": {
            "status": "imported_existing_workflow_bundle",
            "workflow_bundle": str(copied_manifest),
            "stage_count": len(bundle.get("stages", []) or []),
            "workflow_scope": scope,
            "claim_boundary": bundle["claim_boundary"],
        },
    }


def _build_case_bundle(
    *,
    case: Mapping[str, Any],
    index: int,
    root: Path,
    out_dir: Path,
    selection_policy: str,
) -> Dict[str, Any]:
    if _case_workflow_bundle_path(case):
        return _build_existing_workflow_bundle_case(
            case=case,
            index=index,
            root=root,
            out_dir=out_dir,
            selection_policy=selection_policy,
        )
    workload_id = _case_id(case, index)
    bundle_dir = out_dir / "bundles" / workload_id
    pseudo_paths = _pseudo_paths(case, root=root)
    profile_path = _case_ref_path(case, "workload_profile", "path")
    profile_paths = [_resolve_ref(profile_path, root=root)] if profile_path else []
    save_dir = root / "qe_tmp" / f"{workload_id}.save"
    build_args = argparse.Namespace(
        source_dir=root,
        out=bundle_dir,
        workflow_id=f"{workload_id}_measured_scf_workflow",
        workload_id=workload_id,
        material=_case_material(case),
        size_class=_case_size_class(case),
        selection_policy=selection_policy,
        scf_input=_case_ref_path(case, "qe_input", "path"),
        scf_log=_case_ref_path(case, "reference_output", "path"),
        nscf_input="",
        nscf_log="",
        save_dir=save_dir if save_dir.is_dir() else "",
        pseudopotential=pseudo_paths,
        profile=profile_paths,
    )
    build_status = build_bundle_and_corpus(build_args)
    scope = str(build_status.get("workflow_scope", "scf_only_measured_seed"))
    return {
        "workload_id": workload_id,
        "bundle_path": f"bundles/{workload_id}",
        "material": build_args.material,
        "size_class": build_args.size_class,
        "measurement_source": "measured_qe_run",
        "workflow_scope": scope,
        "selection_policy": selection_policy,
        "source_case": {
            "case_id": str(case.get("case_id", "")),
            "class_id": str(case.get("class_id", "")),
            "workload_class": str(case.get("workload_class", "")),
            "label": str(case.get("label", "")),
            "reference_output_status": str(
                case.get("reference_output", {}).get("status", "")
                if isinstance(case.get("reference_output"), Mapping)
                else ""
            ),
        },
        "build_status": build_status,
    }


def _preflight_corpus(corpus_path: Path, out_dir: Path) -> Dict[str, Any]:
    report = build_qe_fpga_workflow_corpus_report(corpus_path)
    readiness = report.get("measured_qe_corpus_readiness", {})
    status = {
        "schema_version": "dse.qe_fpga.workflow_corpus_preflight_status.v1",
        "status": str(readiness.get("status", "blocked")),
        "workflow_corpus": str(corpus_path),
        "report": str(out_dir / "qe_fpga_workload_corpus_preflight.json"),
        "workload_count": int(report.get("workload_count", 0)),
        "measured_ready_workload_count": int(readiness.get("measured_ready_workload_count", 0)),
        "blockers": list(readiness.get("blockers", []) or []),
        "allowed_use": str(readiness.get("allowed_use", "")),
        "forbidden_use": list(readiness.get("forbidden_use", []) or []),
        "claim_boundary": "workflow_corpus_preflight_only_not_search_hardware_or_qe_correctness_evidence",
    }
    _write_json(out_dir / "qe_fpga_workload_corpus_preflight.json", report)
    _write_json(out_dir / "qe_fpga_workload_corpus_preflight_status.json", status)
    return status


def import_reference_bundle(args: argparse.Namespace) -> Dict[str, Any]:
    root = args.reference_bundle.resolve()
    manifest_path = _reference_manifest_path(root)
    root_dir = manifest_path.parent
    manifest = _load_json(manifest_path)
    cases = [case for case in manifest.get("cases", []) or [] if isinstance(case, Mapping)]
    if int(args.case_limit) > 0:
        cases = cases[: int(args.case_limit)]
    if not cases:
        raise ValueError(f"{manifest_path} contains no case objects")
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    workloads = [
        _build_case_bundle(
            case=case,
            index=index,
            root=root_dir,
            out_dir=out_dir,
            selection_policy=str(args.selection_policy),
        )
        for index, case in enumerate(cases)
    ]
    workload_scopes = sorted({
        str(workload.get("workflow_scope", "scf_only_measured_seed"))
        for workload in workloads
        if isinstance(workload, Mapping)
    })
    corpus_scope = (
        "scf_only_measured_seed"
        if workload_scopes == ["scf_only_measured_seed"]
        else "external_qe_workflow_corpus"
    )
    corpus = {
        "schema_version": "dse.qe_fpga_workflow_corpus.v1",
        "corpus_id": str(args.corpus_id),
        "primary_workload_id": str(workloads[0]["workload_id"]),
        "measurement_source": "measured_qe_reference_bundle_import",
        "workflow_scope": corpus_scope,
        "selection_policy": str(args.selection_policy),
        "source_reference_bundle": {
            "path": str(root_dir),
            "manifest": str(manifest_path),
            "schema_version": str(manifest.get("schema_version", "")),
            "case_count": len(cases),
        },
        "workloads": workloads,
        "claim_boundary": (
            "measured_scf_seed_corpus_not_full_qe_workflow_or_hardware_evidence"
            if corpus_scope == "scf_only_measured_seed"
            else "measured_workflow_corpus_input_only_not_hardware_evidence"
        ),
    }
    corpus_path = out_dir / "workflow_corpus.json"
    _write_json(corpus_path, corpus)
    preflight_status = _preflight_corpus(corpus_path, out_dir / "preflight")
    status = {
        "schema_version": "dse.qe_measured_reference_bundle_import_status.v1",
        "status": preflight_status["status"],
        "reference_bundle": str(root_dir),
        "workflow_corpus": str(corpus_path),
        "workload_count": len(workloads),
        "measured_ready_workload_count": int(preflight_status.get("measured_ready_workload_count", 0)),
        "blockers": list(preflight_status.get("blockers", []) or []),
        "scope_boundary": (
            "measured_scf_seed_corpus_not_full_qe_workflow_completion"
            if corpus_scope == "scf_only_measured_seed"
            else "measured_workflow_corpus_input_not_hardware_evidence"
        ),
        "claim_boundary": corpus["claim_boundary"],
    }
    _write_json(out_dir / "qe_measured_reference_bundle_import_status.json", status)
    return status


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = import_reference_bundle(args)
    print(json.dumps(status, sort_keys=True))
    return 0 if status["status"] == "ready_for_model_level_experiments" else 1


if __name__ == "__main__":
    raise SystemExit(main())
