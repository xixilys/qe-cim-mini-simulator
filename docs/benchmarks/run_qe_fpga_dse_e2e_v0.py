#!/usr/bin/env python3
"""Run the QE FPGA DSE JSON-v0 frontend/backend closed loop.

This orchestrator is intentionally claim-conservative: it runs frontend DSE,
executes the backend SystemC timed-functional proxy for one executable Stage-B0
candidate, ingests that report back into frontend EvidenceIR, and optionally
adds gem5 smoke-only evidence. It does not claim QE numerical equivalence,
cycle accuracy, RTL/HLS/board evidence, or physical FPGA performance.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import gmtime, strftime
from typing import Any, Mapping, Sequence


SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_qe_dse_claim_ceiling_status_matrix_v0 as claim_ceiling_matrix
import build_qe_final_best_architecture_decision_v0 as final_best_decision
import materialize_qe_gem5_systemc_b4_v0 as b4_materializer

REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_DESIGN_SPACE = REPO_ROOT / "docs/benchmarks/qe_architecture_family_design_space_spec_v0.json"
DEFAULT_WORKLOAD = REPO_ROOT / "docs/benchmarks/testdata/unified_dse/minimal_workload.json"
DEFAULT_B3_REQUEST = REPO_ROOT / "docs/benchmarks/testdata/unified_dse/backend_execution_request_b3_smoke.json"
DEFAULT_LEGACY_B3_REPORT = REPO_ROOT / "docs/benchmarks/results/qe_dse_gem5_systemc_smoke_report_v0.json"
DEFAULT_GEM5_EXECUTABLE = REPO_ROOT / "gem5_integration/gem5/build/X86/gem5.opt"
DEFAULT_GEM5_B4_CONFIG = REPO_ROOT / "gem5_integration/configs/fpga/simple_fpga_test.py"
DEFAULT_SYSTEMC_BRIDGE = REPO_ROOT / "gem5_integration/systemc_model/build/libgem5_systemc_bridge.a"
DEFAULT_CLAIM_MATRIX_NAME = "claim_ceiling_status_matrix_v0.json"
DEFAULT_CLAIM_MATRIX_MARKDOWN_NAME = "claim_ceiling_status_matrix_v0.md"
BACKEND_REPORT_COLLECTION_NAME = "backend_report_collection_v0.json"
RERANKED_RESULTS_NAME = "reranked_results_v0.json"
FINAL_BEST_DECISION_NAME = "qe_fpga_final_best_architecture_decision_v0.json"
B4_STAGE_B0_FILE_INPUT_REF_KEYS = {
    "application_graph",
    "architecture_template",
    "mapping",
    "architecture_config",
    "systemc_config",
}


class E2EError(RuntimeError):
    pass


class _CandidateEvidenceResolver:
    """Resolve optional Stage C/D evidence without cross-candidate splicing."""

    def __init__(
        self,
        *,
        singular_ref: Path | None,
        singular_payload: Mapping[str, Any] | None,
        per_candidate: Mapping[str, tuple[Path, Mapping[str, Any]]],
        candidate_count: int,
    ) -> None:
        self.singular_ref = singular_ref
        self.singular_payload = singular_payload
        self.per_candidate = dict(per_candidate)
        self.candidate_count = candidate_count

    def for_candidate(self, candidate_id: str | None) -> tuple[Path | None, Mapping[str, Any] | None]:
        if candidate_id is not None and candidate_id in self.per_candidate:
            return self.per_candidate[candidate_id]
        if not isinstance(self.singular_payload, Mapping):
            return None, None
        payload_candidate = self.singular_payload.get("candidate_id")
        if payload_candidate is None:
            if self.candidate_count == 1:
                return self.singular_ref, self.singular_payload
            return None, None
        if candidate_id is not None and str(payload_candidate) == str(candidate_id):
            return self.singular_ref, self.singular_payload
        return None, None


def _parse_candidate_path_bindings(items: Sequence[str] | None, option_name: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in items or []:
        if "=" not in item:
            raise E2EError(f"{option_name} must use candidate_id=path form: {item}")
        candidate_id, raw_path = item.split("=", 1)
        candidate_id = candidate_id.strip()
        raw_path = raw_path.strip()
        if not candidate_id:
            raise E2EError(f"{option_name} candidate_id must be non-empty")
        if not raw_path:
            raise E2EError(f"{option_name} path must be non-empty for {candidate_id}")
        if candidate_id in result:
            raise E2EError(f"{option_name} specified more than once for candidate_id={candidate_id}")
        result[candidate_id] = Path(raw_path)
    return result


def _load_candidate_evidence_map(
    bindings: Mapping[str, Path] | None,
    *,
    loader: Any,
    option_name: str,
) -> dict[str, tuple[Path, Mapping[str, Any]]]:
    loaded: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    for candidate_id, path in (bindings or {}).items():
        payload = loader(path)
        if not isinstance(payload, Mapping):
            raise E2EError(f"{option_name} payload is not a JSON object for candidate_id={candidate_id}: {path}")
        payload_candidate = payload.get("candidate_id")
        if payload_candidate is None:
            raise E2EError(f"{option_name} payload missing candidate_id for map key {candidate_id}: {path}")
        if str(payload_candidate) != str(candidate_id):
            raise E2EError(
                f"{option_name} candidate_id mismatch for map key {candidate_id}: "
                f"payload has {payload_candidate} in {path}"
            )
        loaded[str(candidate_id)] = (path, payload)
    return loaded


def _json_load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise E2EError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _relative(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


def _resolve_non_strict(path: Path, base: Path) -> Path:
    if path.is_absolute():
        return path.expanduser().resolve(strict=False)
    return (base / path).expanduser().resolve(strict=False)


def _same_path_ref(left: Any, right: Path) -> bool:
    if not isinstance(left, str) or not left:
        return False
    return Path(left).expanduser().resolve(strict=False) == right.expanduser().resolve(strict=False)


def _stage_b0_artifact_root(stage_b0_request_path: Path) -> Path:
    request_dir = stage_b0_request_path.resolve().parent
    if request_dir.name in {
        "backend_execution_requests",
        "gem5_systemc_handoff",
        "backend_requests",
    }:
        return request_dir.parent
    return request_dir


def _run(cmd: Sequence[str], *, cwd: Path, log_dir: Path, name: str, timeout_s: int | None = None) -> dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = log_dir / f"{name}.stdout.log"
    stderr = log_dir / f"{name}.stderr.log"
    env = dict(os.environ)
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    with stdout.open("w", encoding="utf-8") as out, stderr.open("w", encoding="utf-8") as err:
        completed = subprocess.run(
            list(cmd),
            cwd=str(cwd),
            env=env,
            stdout=out,
            stderr=err,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    result = {
        "name": name,
        "cmd": list(cmd),
        "returncode": completed.returncode,
        "stdout_log": str(stdout),
        "stderr_log": str(stderr),
    }
    if completed.returncode != 0:
        raise E2EError(
            f"command failed ({name}, rc={completed.returncode}); "
            f"stdout={stdout} stderr={stderr}"
        )
    return result


def _stage_b0_request_family(request: Path) -> str | None:
    try:
        payload = _json_load(request)
    except Exception:
        return None
    candidate_identity = payload.get("candidate_identity")
    if not isinstance(candidate_identity, Mapping):
        return None
    design_axes = candidate_identity.get("design_axes")
    if isinstance(design_axes, Mapping) and design_axes.get("family"):
        return str(design_axes["family"])
    template_id = candidate_identity.get("architecture_template_id")
    return str(template_id) if template_id else None


def _stage_b0_request_candidate_id(request: Path) -> str | None:
    try:
        payload = _json_load(request)
    except Exception:
        return None
    if payload.get("candidate_id"):
        return str(payload["candidate_id"])
    candidate_identity = payload.get("candidate_identity")
    if isinstance(candidate_identity, Mapping) and candidate_identity.get("candidate_id"):
        return str(candidate_identity["candidate_id"])
    return request.stem


def _first_stage_b0_request(frontend_dir: Path, *, preferred_family: str = "F2") -> Path:
    manifest_path = frontend_dir / "stage_b0_descriptor_manifest_v0.json"
    manifest = _json_load(manifest_path)
    descriptors = manifest.get("descriptors")
    if not isinstance(descriptors, list) or not descriptors:
        raise E2EError(f"no Stage-B0 descriptors in {manifest_path}")
    usable: list[Path] = []
    for item in descriptors:
        if isinstance(item, dict) and item.get("backend_execution_request_ref"):
            request = frontend_dir / str(item["backend_execution_request_ref"])
            if request.exists():
                usable.append(request)
                if preferred_family and _stage_b0_request_family(request) == preferred_family:
                    return request
    if usable:
        return usable[0]
    raise E2EError(f"Stage-B0 manifest has no usable backend request: {manifest_path}")


def _stage_b0_request_map(frontend_dir: Path) -> dict[str, Path]:
    manifest_path = frontend_dir / "stage_b0_descriptor_manifest_v0.json"
    manifest = _json_load(manifest_path)
    descriptors = manifest.get("descriptors")
    if not isinstance(descriptors, list):
        raise E2EError(f"Stage-B0 manifest has no descriptors list: {manifest_path}")
    requests: dict[str, Path] = {}
    for item in descriptors:
        if not isinstance(item, Mapping) or not item.get("backend_execution_request_ref"):
            continue
        candidate_id = item.get("candidate_id")
        request_path = frontend_dir / str(item["backend_execution_request_ref"])
        if not request_path.exists():
            continue
        if not candidate_id:
            candidate_id = _stage_b0_request_candidate_id(request_path)
        if candidate_id:
            requests[str(candidate_id)] = request_path
    return requests


def _selected_stage_b0_requests(
    frontend_dir: Path,
    *,
    top_k: int,
    preferred_family: str,
    candidate_id: str | None = None,
) -> list[Path]:
    if top_k <= 0 and not candidate_id:
        return [_first_stage_b0_request(frontend_dir, preferred_family=preferred_family)]
    request_by_candidate = _stage_b0_request_map(frontend_dir)
    plan_path = frontend_dir / "multi_fidelity_plan_v0.json"
    selected: list[Path] = []
    if plan_path.exists():
        plan = _json_load(plan_path)
        candidates = plan.get("selected_candidates")
        if isinstance(candidates, list):
            ranked_candidates: list[tuple[int, int, str]] = []
            unranked_candidates: list[tuple[int, str]] = []
            for ordinal, item in enumerate(candidates):
                if not isinstance(item, Mapping) or not item.get("candidate_id"):
                    continue
                cid = str(item["candidate_id"])
                if candidate_id and cid != candidate_id:
                    continue
                rank = item.get("screening_rank")
                if isinstance(rank, int):
                    ranked_candidates.append((rank, ordinal, cid))
                else:
                    unranked_candidates.append((ordinal, cid))
            ordered_candidates = [
                cid
                for _, _, cid in sorted(ranked_candidates, key=lambda item: (item[0], item[1]))
            ] + [cid for _, cid in unranked_candidates]
            for cid in ordered_candidates:
                request = request_by_candidate.get(cid)
                if request is not None:
                    selected.append(request)
                if not candidate_id and top_k > 0 and len(selected) >= top_k:
                    break
    if candidate_id:
        request = request_by_candidate.get(candidate_id)
        if request is None:
            raise E2EError(f"candidate_id is not available as a Stage-B0 request: {candidate_id}")
        return [request]
    if selected:
        return selected
    return [_first_stage_b0_request(frontend_dir, preferred_family=preferred_family)]


def _metric(report: Mapping[str, Any], key: str) -> Any:
    metrics = report.get("metrics")
    if isinstance(metrics, Mapping):
        return metrics.get(key)
    return None


def _report_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": report.get("candidate_id"),
        "execution_status": report.get("execution_status"),
        "fidelity": report.get("fidelity"),
        "claim_ceiling": report.get("claim_ceiling"),
        "backend_class": report.get("backend_class"),
        "source_kind": report.get("source_kind"),
        "time_to_completion_s": _metric(report, "time_to_completion_s"),
        "device_busy_s": _metric(report, "device_busy_s"),
        "host_wait_s": _metric(report, "host_wait_s"),
        "dma_read_bytes": _metric(report, "dma_read_bytes"),
        "dma_write_bytes": _metric(report, "dma_write_bytes"),
        "bytes_moved_to_convergence": _metric(report, "bytes_moved_to_convergence"),
        "resident_reuse_ratio": _metric(report, "resident_reuse_ratio"),
        "fallback_ratio": _metric(report, "fallback_ratio"),
        "spill_ratio": _metric(report, "spill_ratio"),
        "cycle_proxy": _metric(report, "cycle_proxy"),
        "systemc_converged": _metric(report, "systemc_converged"),
        "timing_sidecar": (
            report.get("artifact_refs", {}).get("timing_sidecar")
            if isinstance(report.get("artifact_refs"), Mapping)
            else None
        ),
        "non_claims": list(report.get("non_claims", [])) if isinstance(report.get("non_claims"), list) else [],
    }


def _path_safe_candidate_id(candidate_id: str | None) -> str:
    value = candidate_id or "unknown_candidate"
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)




def _enforce_real_gem5_smoke_gate(report: Mapping[str, Any], report_path: Path) -> None:
    """Require --require-real-gem5-smoke to prove a real executed gem5 smoke path.

    The backend runner writes refusal reports with rc=0 for many safe failure paths.
    That behavior is useful for artifact capture, but the E2E gate must be hard:
    legacy B3 conversion, dry-run/refusal reports, and non-real smoke envelopes do
    not satisfy the Real gem5/B4 acceptance gate.
    """
    artifact_refs = report.get("artifact_refs")
    if not isinstance(artifact_refs, Mapping):
        artifact_refs = {}
    control_path = report.get("control_path")
    if not isinstance(control_path, Mapping):
        control_path = {}

    failures: list[str] = []
    if report.get("execution_status") != "executed":
        failures.append(f"execution_status={report.get('execution_status')!r}")
    if report.get("claim_ceiling") != "gem5_systemc_smoke_only":
        failures.append(f"claim_ceiling={report.get('claim_ceiling')!r}")
    if report.get("backend_class") != "gem5_systemc_smoke":
        failures.append(f"backend_class={report.get('backend_class')!r}")
    if artifact_refs.get("legacy_b3_smoke_report"):
        failures.append("legacy_b3_conversion_used")
    if artifact_refs.get("artifact_subtype") != "real_qe_gem5_se_scf_smoke_v0":
        failures.append(f"artifact_subtype={artifact_refs.get('artifact_subtype')!r}")
    if control_path.get("completion_source") != "gem5_se_real_pw_stdout_parser":
        failures.append(f"completion_source={control_path.get('completion_source')!r}")
    correctness_gate = report.get("correctness_gate")
    if isinstance(correctness_gate, Mapping):
        if correctness_gate.get("workload_equivalent_claim") is not False:
            failures.append("workload_equivalent_claim_not_false")
        if correctness_gate.get("qe_equivalent_scf_claim") is True:
            failures.append("qe_equivalent_scf_claim_true")

    if failures:
        raise E2EError(
            "--require-real-gem5-smoke gate failed for "
            f"{report_path}: {', '.join(failures)}"
        )


def _enforce_real_gem5_b4_gate(report: Mapping[str, Any], report_path: Path, *, expected_bridge: Path) -> None:
    """Require B4 to be an executed real-gem5 timed-proxy report with bridge provenance."""
    artifact_refs = report.get("artifact_refs")
    if not isinstance(artifact_refs, Mapping):
        artifact_refs = {}
    control_path = report.get("control_path")
    if not isinstance(control_path, Mapping):
        control_path = {}
    metrics = report.get("metrics")
    if not isinstance(metrics, Mapping):
        metrics = {}
    environment = report.get("environment")
    if not isinstance(environment, Mapping):
        environment = {}

    failures: list[str] = []
    if report.get("execution_status") != "executed":
        failures.append(f"execution_status={report.get('execution_status')!r}")
    if report.get("claim_ceiling") != "gem5_systemc_timed_proxy_only":
        failures.append(f"claim_ceiling={report.get('claim_ceiling')!r}")
    if report.get("backend_class") != "gem5_systemc_timed_proxy":
        failures.append(f"backend_class={report.get('backend_class')!r}")
    if environment.get("fpga_execution_mode") != "real_bridge":
        failures.append(f"fpga_execution_mode={environment.get('fpga_execution_mode')!r}")
    if environment.get("real_systemc_target") not in (True, "1", "true", "True"):
        failures.append(f"real_systemc_target={environment.get('real_systemc_target')!r}")
    if not _same_path_ref(environment.get("systemc_bridge"), expected_bridge):
        failures.append(f"systemc_bridge={environment.get('systemc_bridge')!r}")
    if not _same_path_ref(artifact_refs.get("systemc_bridge"), expected_bridge):
        failures.append(f"artifact_refs.systemc_bridge={artifact_refs.get('systemc_bridge')!r}")
    if not environment.get("timing_sidecar"):
        failures.append("missing environment.timing_sidecar")
    if not artifact_refs.get("timing_sidecar"):
        failures.append("missing artifact_refs.timing_sidecar")
    for key in (
        "mmio_read_count",
        "mmio_write_count",
        "systemc_start_tick",
        "systemc_end_tick",
        "completion_tick",
        "dma_start_tick",
        "dma_end_tick",
    ):
        if key not in control_path:
            failures.append(f"missing control_path.{key}")
    for key in (
        "cycle_source",
        "host_control_mmio_read_count",
        "host_control_mmio_write_count",
        "systemc_datapath_device_busy_ns",
        "successful_dma_transfer_bytes",
        "dma_warning_count",
        "event_timed_device_activity_observed",
    ):
        if key not in metrics:
            failures.append(f"missing metrics.{key}")
    cycle_source = str(metrics.get("cycle_source") or environment.get("cycle_source") or "")
    if cycle_source not in {
        "timing_sidecar_projection",
        "gem5_exit_tick",
        "gem5_event_timed_device_observed",
    }:
        failures.append(f"unsupported cycle_source={cycle_source!r}")
    event_activity = metrics.get("event_timed_device_activity_observed") is True
    mmio_activity = int(metrics.get("host_control_mmio_read_count") or 0) + int(
        metrics.get("host_control_mmio_write_count") or 0
    )
    if cycle_source == "gem5_event_timed_device_observed":
        if not event_activity:
            failures.append("event_timed_cycle_source_without_observed_device_activity")
        if mmio_activity <= 0:
            failures.append("event_timed_cycle_source_without_nonzero_mmio_activity")
        delta = metrics.get("candidate_device_event_delta_ticks")
        if not isinstance(delta, int) or delta <= 0:
            failures.append("event_timed_cycle_source_without_positive_event_delta")
        profile_value = (
            environment.get("candidate_timing_profile")
            or artifact_refs.get("candidate_timing_profile")
            or artifact_refs.get("strict_b4_runtime_timing_input")
        )
        if not profile_value:
            failures.append("event_timed_cycle_source_without_candidate_timing_profile")
        activity_source = (
            metrics.get("observed_device_activity_source")
            or control_path.get("mmio_activity_source")
            or control_path.get("event_activity_source")
        )
        if activity_source not in {"gem5_simobject_counters", "gem5_device_event_report"}:
            failures.append("event_timed_cycle_source_without_simobject_activity_source")
    elif event_activity:
        failures.append("event_activity_marked_for_non_event_timing_source")
    correctness_gate = report.get("correctness_gate")
    if isinstance(correctness_gate, Mapping):
        if correctness_gate.get("workload_equivalent_claim") is not False:
            failures.append("workload_equivalent_claim_not_false")
        if correctness_gate.get("domain_equivalence_claim") is not False:
            failures.append("domain_equivalence_claim_not_false")

    if failures:
        raise E2EError(
            "--require-real-gem5-b4 gate failed for "
            f"{report_path}: {', '.join(failures)}"
        )


def _write_b4_request_from_stage_b0(
    stage_b0_request_path: Path,
    output_dir: Path,
    *,
    gem5_executable: Path,
    gem5_config: Path,
    systemc_bridge: Path,
) -> Path:
    try:
        result = b4_materializer.materialize_b4_from_stage_b0(
            stage_b0_request_path,
            output_dir,
            gem5_executable=gem5_executable,
            gem5_config=gem5_config,
            systemc_bridge=systemc_bridge,
            repo_root=REPO_ROOT,
        )
    except Exception as exc:
        raise E2EError(f"B4 materialization failed for {stage_b0_request_path}: {exc}") from exc
    return Path(result["request"])


def _stage_b0_request_context(stage_b0_request_path: Path) -> dict[str, str | None]:
    request = _json_load(stage_b0_request_path)
    candidate_identity = request.get("candidate_identity")
    if not isinstance(candidate_identity, Mapping):
        candidate_identity = {}
    design_axes = candidate_identity.get("design_axes")
    if not isinstance(design_axes, Mapping):
        design_axes = {}
    domain_extension = request.get("domain_extension")
    qe_extension = {}
    if isinstance(domain_extension, Mapping):
        maybe_qe = domain_extension.get("qe")
        if isinstance(maybe_qe, Mapping):
            qe_extension = maybe_qe

    candidate_id = (
        request.get("candidate_id")
        or candidate_identity.get("candidate_id")
        or stage_b0_request_path.stem
    )
    family = design_axes.get("family") or candidate_identity.get("architecture_template_id")
    workload_identity = request.get("workload_identity")
    workload_id = None
    if isinstance(workload_identity, Mapping):
        workload_id = workload_identity.get("workload_id")
    workload_id = workload_id or qe_extension.get("workload_id") or qe_extension.get("case_id")
    case_id = qe_extension.get("case_id") or workload_id
    return {
        "candidate_id": str(candidate_id) if candidate_id is not None else None,
        "family": str(family) if family is not None else None,
        "workload_id": str(workload_id) if workload_id is not None else None,
        "case_id": str(case_id) if case_id is not None else None,
    }


def _claim_matrix_output_path(output_dir: Path, requested: Path | None) -> Path:
    if requested is None:
        return output_dir / DEFAULT_CLAIM_MATRIX_NAME
    if requested.is_absolute():
        return requested
    return output_dir / requested


def _write_claim_ceiling_status_matrix(
    *,
    output_dir: Path,
    stage_b0_request_path: Path,
    systemc_report: Path,
    systemc_payload: Mapping[str, Any],
    gem5_report: Path | None = None,
    gem5_payload: Mapping[str, Any] | None = None,
    gem5_b4_report: Path | None = None,
    gem5_b4_payload: Mapping[str, Any] | None = None,
    qe_correctness_report: Path | None = None,
    implementation_evidence: Path | None = None,
    requested_matrix_path: Path | None = None,
) -> dict[str, Path]:
    context = _stage_b0_request_context(stage_b0_request_path)
    matrix_path = _claim_matrix_output_path(output_dir, requested_matrix_path)
    markdown_path = (
        output_dir / DEFAULT_CLAIM_MATRIX_MARKDOWN_NAME
        if requested_matrix_path is None
        else matrix_path.with_suffix(".md")
    )
    stage_c_payload = claim_ceiling_matrix.load_stage_c_report(qe_correctness_report)
    stage_d_payload = claim_ceiling_matrix.load_implementation_evidence(implementation_evidence)
    matrix = claim_ceiling_matrix.build_matrix(
        output_ref=matrix_path,
        candidate_id=context["candidate_id"],
        workload_id=context["workload_id"],
        case_id=context["case_id"],
        family=context["family"],
        stage_c_report_ref=qe_correctness_report,
        stage_c_report=stage_c_payload,
        implementation_evidence_ref=implementation_evidence,
        implementation_evidence=stage_d_payload,
        b2_report_ref=systemc_report,
        b2_report=systemc_payload,
        b3_report_ref=gem5_report,
        b3_report=gem5_payload,
        b4_report_ref=gem5_b4_report,
        b4_report=gem5_b4_payload,
    )
    claim_ceiling_matrix.write_json(matrix_path, matrix)
    claim_ceiling_matrix.write_markdown(markdown_path, matrix)
    return {"matrix": matrix_path, "markdown": markdown_path}


def _write_claim_ceiling_status_matrix_for_runs(
    *,
    output_dir: Path,
    candidate_runs: Sequence[Mapping[str, Any]],
    qe_correctness_report: Path | None = None,
    implementation_evidence: Path | None = None,
    qe_correctness_report_for: Mapping[str, Path] | None = None,
    implementation_evidence_for: Mapping[str, Path] | None = None,
    requested_matrix_path: Path | None = None,
) -> dict[str, Path]:
    matrix_path = _claim_matrix_output_path(output_dir, requested_matrix_path)
    markdown_path = (
        output_dir / DEFAULT_CLAIM_MATRIX_MARKDOWN_NAME
        if requested_matrix_path is None
        else matrix_path.with_suffix(".md")
    )
    candidate_count = len(candidate_runs)
    stage_c_payload = claim_ceiling_matrix.load_stage_c_report(qe_correctness_report)
    stage_d_payload = claim_ceiling_matrix.load_implementation_evidence(implementation_evidence)
    stage_c_resolver = _CandidateEvidenceResolver(
        singular_ref=qe_correctness_report,
        singular_payload=stage_c_payload,
        per_candidate=_load_candidate_evidence_map(
            qe_correctness_report_for,
            loader=claim_ceiling_matrix.load_stage_c_report,
            option_name="--qe-correctness-report-for",
        ),
        candidate_count=candidate_count,
    )
    stage_d_resolver = _CandidateEvidenceResolver(
        singular_ref=implementation_evidence,
        singular_payload=stage_d_payload,
        per_candidate=_load_candidate_evidence_map(
            implementation_evidence_for,
            loader=claim_ceiling_matrix.load_implementation_evidence,
            option_name="--implementation-evidence-for",
        ),
        candidate_count=candidate_count,
    )
    rows: list[dict[str, Any]] = []
    for run in candidate_runs:
        request_path = Path(str(run["stage_b0_request"]))
        context = _stage_b0_request_context(request_path)
        candidate_id = context["candidate_id"]
        b2_report = Path(str(run["systemc_report"]))
        b2_payload = run.get("systemc_payload")
        b4_report = Path(str(run["gem5_b4_report"])) if run.get("gem5_b4_report") else None
        b4_payload = run.get("gem5_b4_payload") if isinstance(run.get("gem5_b4_payload"), Mapping) else None
        stage_c_ref, row_stage_c_payload = stage_c_resolver.for_candidate(candidate_id)
        stage_d_ref, row_stage_d_payload = stage_d_resolver.for_candidate(candidate_id)
        one = claim_ceiling_matrix.build_matrix(
            output_ref=matrix_path,
            candidate_id=candidate_id,
            workload_id=context["workload_id"],
            case_id=context["case_id"],
            family=context["family"],
            stage_c_report_ref=stage_c_ref,
            stage_c_report=row_stage_c_payload,
            implementation_evidence_ref=stage_d_ref,
            implementation_evidence=row_stage_d_payload,
            b2_report_ref=b2_report,
            b2_report=b2_payload if isinstance(b2_payload, Mapping) else None,
            b4_report_ref=b4_report,
            b4_report=b4_payload,
        )
        row = dict(one["rows"][0])
        row["screening_rank"] = run.get("screening_rank")
        row["candidate_alignment"] = {
            "stage_b0_candidate_id": candidate_id,
            "b2_candidate_id": b2_payload.get("candidate_id") if isinstance(b2_payload, Mapping) else None,
            "b4_candidate_id": b4_payload.get("candidate_id") if isinstance(b4_payload, Mapping) else None,
            "stage_c_candidate_id": (
                row_stage_c_payload.get("candidate_id") if isinstance(row_stage_c_payload, Mapping) else None
            ),
            "stage_d_candidate_id": (
                row_stage_d_payload.get("candidate_id") if isinstance(row_stage_d_payload, Mapping) else None
            ),
        }
        row["same_candidate_evidence_only"] = (
            row["candidate_alignment"]["b2_candidate_id"] in (None, candidate_id)
            and row["candidate_alignment"]["b4_candidate_id"] in (None, candidate_id)
            and row["candidate_alignment"]["stage_c_candidate_id"] in (None, candidate_id)
            and row["candidate_alignment"]["stage_d_candidate_id"] in (None, candidate_id)
        )
        if not row["same_candidate_evidence_only"]:
            row.setdefault("blockers", []).append("candidate_evidence_alignment_mismatch")
            row["final_observed_conclusion_ceiling"] = "candidate_alignment_mismatch_no_conclusion"
        rows.append(row)
    matrix = {
        "schema_version": claim_ceiling_matrix.SCHEMA_VERSION,
        "adjudicator_permission_scope": "not_evaluated",
        "matrix_ref": str(matrix_path),
        "row_count": len(rows),
        "rows": rows,
        "global_non_claims": [
            "status_matrix_is_not_adjudicator_permission",
            "no_hidden_qe_or_implementation_execution",
            "no_cycle_accuracy_claim_without_rtl_or_board_timing_evidence",
            "no_final_public_winner",
            "no_cross_candidate_evidence_splicing",
        ],
    }
    claim_ceiling_matrix.write_json(matrix_path, matrix)
    claim_ceiling_matrix.write_markdown(markdown_path, matrix)
    return {"matrix": matrix_path, "markdown": markdown_path}


def _write_backend_report_collection(
    path: Path,
    candidate_runs: Sequence[Mapping[str, Any]],
    *,
    generated_at_utc: str,
) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    candidate_reports: dict[str, Any] = {}
    for run in candidate_runs:
        candidate_id = str(run.get("candidate_id") or "unknown_candidate")
        candidate_reports.setdefault(candidate_id, {})
        systemc_payload = run.get("systemc_payload")
        if isinstance(systemc_payload, Mapping):
            reports.append(dict(systemc_payload))
            candidate_reports[candidate_id]["B2"] = {
                "report_ref": str(run.get("systemc_report")),
                "summary": _report_summary(systemc_payload),
            }
        b4_payload = run.get("gem5_b4_payload")
        if isinstance(b4_payload, Mapping):
            reports.append(dict(b4_payload))
            candidate_reports[candidate_id]["B4"] = {
                "report_ref": str(run.get("gem5_b4_report")),
                "summary": _report_summary(b4_payload),
                "materialization_manifest": str(run.get("gem5_b4_materialization_manifest")),
            }
    payload = {
        "schema_version": "backend_execution_report_collection_v0",
        "generated_at_utc": generated_at_utc,
        "report_count": len(reports),
        "reports": reports,
        "candidate_reports": candidate_reports,
        "non_claims": [
            "collection_is_evidence_only",
            "not_final_public_family_winner",
            "no_cross_candidate_evidence_splicing",
        ],
    }
    _write_json(path, payload)
    return payload


def _ranking_metric(run: Mapping[str, Any]) -> tuple[int, float, int]:
    b4_payload = run.get("gem5_b4_payload")
    b2_payload = run.get("systemc_payload")
    if isinstance(b4_payload, Mapping):
        value = _metric(b4_payload, "cycle_proxy")
        if isinstance(value, (int, float)):
            return (0, float(value), int(run.get("screening_rank") or 10**9))
    if isinstance(b2_payload, Mapping):
        value = _metric(b2_payload, "cycle_proxy")
        if isinstance(value, (int, float)):
            return (1, float(value), int(run.get("screening_rank") or 10**9))
    return (2, float(run.get("screening_rank") or 10**9), int(run.get("screening_rank") or 10**9))


def _strict_b4_event_observed(run: Mapping[str, Any]) -> bool:
    payload = run.get("gem5_b4_payload")
    if not isinstance(payload, Mapping):
        return False
    metrics = payload.get("metrics")
    if not isinstance(metrics, Mapping):
        return False
    return (
        metrics.get("cycle_source") == "gem5_event_timed_device_observed"
        and metrics.get("event_timed_device_activity_observed") is True
        and isinstance(metrics.get("candidate_device_event_delta_ticks"), int)
        and metrics.get("candidate_device_event_delta_ticks") > 0
    )


def _final_recommendation_candidate_ids(
    claim_matrix: Mapping[str, Any] | None,
    candidate_runs: Sequence[Mapping[str, Any]],
) -> set[str]:
    if not isinstance(claim_matrix, Mapping):
        return set()
    strict_b4_candidates = {
        str(run.get("candidate_id"))
        for run in candidate_runs
        if run.get("candidate_id") is not None and _strict_b4_event_observed(run)
    }
    rows = claim_matrix.get("rows")
    if not isinstance(rows, list):
        return set()
    promotable: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        candidate_id = row.get("candidate_id")
        if not candidate_id:
            continue
        blockers = row.get("blockers")
        if blockers not in (None, []):
            continue
        if row.get("same_candidate_evidence_only") is False:
            continue
        if str(candidate_id) not in strict_b4_candidates:
            continue
        ceiling = str(row.get("final_observed_conclusion_ceiling") or "")
        if not ceiling or ceiling in {
            "candidate_alignment_mismatch_no_conclusion",
            "gem5_systemc_timed_proxy_only",
            "systemc_proxy_only",
            "no_evidence",
        }:
            continue
        promotable.add(str(candidate_id))
    return promotable


def _write_reranked_results(
    path: Path,
    candidate_runs: Sequence[Mapping[str, Any]],
    *,
    claim_matrix: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ranked_runs = sorted(candidate_runs, key=_ranking_metric)
    final_candidate_ids = _final_recommendation_candidate_ids(claim_matrix, ranked_runs)
    rows: list[dict[str, Any]] = []
    for observed_rank, run in enumerate(ranked_runs, start=1):
        screening_rank = run.get("screening_rank")
        b2_payload = run.get("systemc_payload")
        b4_payload = run.get("gem5_b4_payload")
        row = {
            "candidate_id": run.get("candidate_id"),
            "screening_rank": screening_rank,
            "observed_rank": observed_rank,
            "rank_delta": (
                None
                if not isinstance(screening_rank, int)
                else int(screening_rank) - observed_rank
            ),
            "b2_cycle_proxy": _metric(b2_payload, "cycle_proxy") if isinstance(b2_payload, Mapping) else None,
            "b4_cycle_proxy": _metric(b4_payload, "cycle_proxy") if isinstance(b4_payload, Mapping) else None,
            "b2_claim_ceiling": b2_payload.get("claim_ceiling") if isinstance(b2_payload, Mapping) else None,
            "b4_claim_ceiling": b4_payload.get("claim_ceiling") if isinstance(b4_payload, Mapping) else None,
            "recommendation_scope": "bounded_observed_proxy_rank",
            "strict_b4_event_observed": _strict_b4_event_observed(run),
            "eligible_for_final_recommendation": str(run.get("candidate_id")) in final_candidate_ids,
            "non_claims": [
                "not_final_public_family_winner",
                "not_qe_equivalent_scf_claim",
                "not_cycle_accurate_claim",
            ],
        }
        rows.append(row)
    bounded_best = rows[0] if rows else None
    final_best = next((row for row in rows if row["eligible_for_final_recommendation"]), None)
    payload = {
        "schema_version": "qe_fpga_dse_reranked_results_v0",
        "row_count": len(rows),
        "ranking_basis": "B4 cycle_proxy when present, otherwise B2 cycle_proxy, otherwise screening_rank",
        "bounded_recommendation": (
            {
                "candidate_id": bounded_best["candidate_id"],
                "observed_rank": bounded_best["observed_rank"],
                "recommendation_scope": "bounded_proxy_evidence_only",
            }
            if bounded_best
            else None
        ),
        "final_recommendation": (
            {
                "candidate_id": final_best["candidate_id"],
                "observed_rank": final_best["observed_rank"],
                "recommendation_scope": "same_candidate_stage_c_d_plus_strict_b4_event_tick_observed",
            }
            if final_best
            else None
        ),
        "final_recommendation_gate": {
            "requires_no_stage_c_d_blockers": True,
            "requires_same_candidate_evidence_only": True,
            "requires_strict_b4_cycle_source": "gem5_event_timed_device_observed",
            "blocked_candidates_remain_bounded_proxy_rank_only": True,
        },
        "rows": rows,
        "non_claims": [
            "not_final_public_family_winner",
            "no_cross_candidate_evidence_splicing",
            "no_cycle_accuracy_claim",
            "bounded_proxy_rank_is_not_final_recommendation",
        ],
    }
    _write_json(path, payload)
    return payload


def _write_final_best_architecture_decision(
    path: Path,
    *,
    manifest_path: Path,
    claim_matrix_path: Path,
    backend_collection_path: Path,
    policy_path: Path | None,
) -> dict[str, Any]:
    decision = final_best_decision.build_decision(
        manifest_path=manifest_path,
        claim_matrix_path=claim_matrix_path,
        backend_report_collection_path=backend_collection_path,
        policy_path=policy_path,
        output_ref=path,
    )
    final_best_decision.write_json(path, decision)
    return decision


def run_e2e(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    if output_dir.exists() and args.clean:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir = output_dir / "logs"
    frontend_dir = output_dir / "frontend_dse"
    backend_dir = output_dir / "backend_reports"
    ingest_dir = output_dir / "frontend_ingest_systemc"
    gem5_ingest_dir = output_dir / "frontend_ingest_gem5_smoke"
    commands: list[dict[str, Any]] = []

    frontend_cmd = [
        sys.executable,
        "docs/benchmarks/run_unified_dse_v0.py",
        "--design-space-spec",
        str(Path(args.design_space_spec)),
        "--workload",
        str(Path(args.workload)),
        "--output-dir",
        str(frontend_dir),
        "--source-kind",
        args.source_kind,
        "--search-backend",
        args.search_backend,
        "--shortlist-policy",
        args.shortlist_policy,
        "--shortlist-size",
        str(args.shortlist_size),
        "--emit-multi-fidelity-plan",
        "--emit-stage-b0-descriptors",
        "--emit-release-bundle",
        "--dry-run",
        "--max-design-points",
        str(args.max_design_points),
    ]
    if args.qe_correctness_report:
        frontend_cmd.extend(["--qe-correctness-report", str(Path(args.qe_correctness_report))])
    if args.implementation_evidence:
        frontend_cmd.extend(["--implementation-evidence", str(Path(args.implementation_evidence))])
    if args.emit_full_stage_status:
        frontend_cmd.append("--emit-full-stage-status")
    commands.append(_run(frontend_cmd, cwd=REPO_ROOT, log_dir=log_dir, name="frontend_dse", timeout_s=args.timeout_s))

    request_paths = _selected_stage_b0_requests(
        frontend_dir,
        top_k=args.top_k,
        preferred_family=args.preferred_family,
        candidate_id=args.candidate_id,
    )
    candidate_runs: list[dict[str, Any]] = []
    screening_rank_by_candidate: dict[str, int] = {}
    plan_path = frontend_dir / "multi_fidelity_plan_v0.json"
    if plan_path.exists():
        plan = _json_load(plan_path)
        selected_candidates = plan.get("selected_candidates")
        if isinstance(selected_candidates, list):
            for item in selected_candidates:
                if isinstance(item, Mapping) and item.get("candidate_id"):
                    rank = item.get("screening_rank")
                    if isinstance(rank, int):
                        screening_rank_by_candidate[str(item["candidate_id"])] = rank

    for index, request_path in enumerate(request_paths, start=1):
        candidate_id = _stage_b0_request_candidate_id(request_path) or request_path.stem
        safe_candidate = _path_safe_candidate_id(candidate_id)
        candidate_dir = output_dir / "candidate_runs" / safe_candidate
        systemc_report = candidate_dir / "systemc_timed_functional_report.json"
        backend_cmd = [
            sys.executable,
            "backend/runners/run_backend_execution_v0.py",
            "--request",
            str(request_path),
            "--output",
            str(systemc_report),
            "--mode",
            "systemc_timed_functional",
            "--allow-execute",
            "--timeout-s",
            str(args.timeout_s),
        ]
        commands.append(
            _run(
                backend_cmd,
                cwd=REPO_ROOT,
                log_dir=log_dir,
                name=f"backend_systemc_{index}_{safe_candidate}",
                timeout_s=args.timeout_s + 5,
            )
        )
        systemc_payload = _json_load(systemc_report)
        candidate_runs.append(
            {
                "candidate_id": candidate_id,
                "screening_rank": screening_rank_by_candidate.get(candidate_id),
                "stage_b0_request": request_path,
                "candidate_dir": candidate_dir,
                "systemc_report": systemc_report,
                "systemc_payload": systemc_payload,
            }
        )

    generated_at_utc = strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())
    request_path = Path(str(candidate_runs[0]["stage_b0_request"]))
    systemc_report = Path(str(candidate_runs[0]["systemc_report"]))
    systemc_payload = candidate_runs[0]["systemc_payload"]
    gem5_report: Path | None = None
    gem5_payload: dict[str, Any] | None = None
    gem5_mode = "skipped"
    gem5_b4_request: Path | None = None
    gem5_b4_report: Path | None = None
    gem5_b4_payload: dict[str, Any] | None = None
    gem5_b4_mode = "skipped"
    if args.include_gem5_smoke:
        gem5_report = backend_dir / "gem5_systemc_smoke_report.json"
        gem5_cmd = [
            sys.executable,
            "backend/runners/run_backend_execution_v0.py",
            "--request",
            str(Path(args.gem5_smoke_request)),
            "--output",
            str(gem5_report),
            "--mode",
            "gem5_systemc_smoke",
        ]
        if args.require_real_gem5_smoke:
            gem5_cmd.extend(["--allow-execute", "--timeout-s", str(args.gem5_timeout_s)])
            gem5_mode = "real_gem5_requested"
        else:
            gem5_cmd.extend(["--legacy-b3-report", str(Path(args.legacy_b3_report))])
            gem5_mode = "legacy_b3_conversion"
        commands.append(_run(gem5_cmd, cwd=REPO_ROOT, log_dir=log_dir, name="backend_gem5_smoke", timeout_s=args.gem5_timeout_s + 5))
        gem5_payload = _json_load(gem5_report)
        if args.require_real_gem5_smoke:
            _enforce_real_gem5_smoke_gate(gem5_payload, gem5_report)
        gem5_ingest_cmd = [
            sys.executable,
            "docs/benchmarks/qedse_frontend.py",
            "frontend",
            "ingest-feedback",
            "--backend-report",
            str(gem5_report),
            "--output-dir",
            str(gem5_ingest_dir),
        ]
        commands.append(_run(gem5_ingest_cmd, cwd=REPO_ROOT, log_dir=log_dir, name="frontend_ingest_gem5_smoke", timeout_s=args.timeout_s))

    if args.include_gem5_b4 or args.require_real_gem5_b4:
        gem5_b4_mode = "real_gem5_b4_requested" if args.require_real_gem5_b4 else "real_gem5_b4_optional"
        b4_systemc_bridge = _resolve_non_strict(Path(args.systemc_bridge_library), REPO_ROOT)
        b4_runs = candidate_runs[: max(0, int(args.b4_top_n))]
        if not b4_runs:
            gem5_b4_mode = "skipped_b4_top_n_zero"
        for index, run in enumerate(b4_runs, start=1):
            run_request_path = Path(str(run["stage_b0_request"]))
            safe_candidate = _path_safe_candidate_id(str(run["candidate_id"]))
            materialized_dir = Path(str(run["candidate_dir"])) / "b4_materialized"
            b4_request = _write_b4_request_from_stage_b0(
                run_request_path,
                materialized_dir,
                gem5_executable=Path(args.gem5_executable),
                gem5_config=Path(args.gem5_b4_config),
                systemc_bridge=b4_systemc_bridge,
            )
            b4_report = Path(str(run["candidate_dir"])) / "gem5_systemc_timed_proxy_report.json"
            gem5_b4_cmd = [
                sys.executable,
                "backend/runners/run_backend_execution_v0.py",
                "--request",
                str(b4_request),
                "--output",
                str(b4_report),
                "--mode",
                "gem5_systemc_timed_proxy",
                "--allow-execute",
                "--timeout-s",
                str(args.gem5_timeout_s),
            ]
            commands.append(
                _run(
                    gem5_b4_cmd,
                    cwd=REPO_ROOT,
                    log_dir=log_dir,
                    name=f"backend_gem5_b4_{index}_{safe_candidate}",
                    timeout_s=args.gem5_timeout_s + 5,
                )
            )
            b4_payload = _json_load(b4_report)
            if args.require_real_gem5_b4:
                _enforce_real_gem5_b4_gate(
                    b4_payload,
                    b4_report,
                    expected_bridge=b4_systemc_bridge,
                )
            run["gem5_b4_request"] = b4_request
            run["gem5_b4_report"] = b4_report
            run["gem5_b4_payload"] = b4_payload
            run["gem5_b4_materialization_manifest"] = materialized_dir / "manifest_v0.json"
            if gem5_b4_request is None:
                gem5_b4_request = b4_request
                gem5_b4_report = b4_report
                gem5_b4_payload = b4_payload

    qe_correctness_report = Path(args.qe_correctness_report) if args.qe_correctness_report else None
    implementation_evidence = Path(args.implementation_evidence) if args.implementation_evidence else None
    qe_correctness_report_for = _parse_candidate_path_bindings(
        args.qe_correctness_report_for,
        "--qe-correctness-report-for",
    )
    implementation_evidence_for = _parse_candidate_path_bindings(
        args.implementation_evidence_for,
        "--implementation-evidence-for",
    )
    claim_matrix_refs = _write_claim_ceiling_status_matrix_for_runs(
        output_dir=output_dir,
        candidate_runs=candidate_runs,
        qe_correctness_report=qe_correctness_report,
        implementation_evidence=implementation_evidence,
        qe_correctness_report_for=qe_correctness_report_for,
        implementation_evidence_for=implementation_evidence_for,
        requested_matrix_path=Path(args.claim_ceiling_status_matrix) if args.claim_ceiling_status_matrix else None,
    )
    claim_matrix_payload = _json_load(claim_matrix_refs["matrix"])
    backend_collection_path = output_dir / BACKEND_REPORT_COLLECTION_NAME
    backend_collection = _write_backend_report_collection(
        backend_collection_path,
        candidate_runs,
        generated_at_utc=generated_at_utc,
    )
    ingest_cmd = [
        sys.executable,
        "docs/benchmarks/qedse_frontend.py",
        "frontend",
        "ingest-feedback",
        "--backend-report",
        str(backend_collection_path),
        "--output-dir",
        str(ingest_dir),
    ]
    commands.append(_run(ingest_cmd, cwd=REPO_ROOT, log_dir=log_dir, name="frontend_ingest_backend_collection", timeout_s=args.timeout_s))
    reranked_results_path = output_dir / RERANKED_RESULTS_NAME
    reranked_results = _write_reranked_results(
        reranked_results_path,
        candidate_runs,
        claim_matrix=claim_matrix_payload,
    )
    final_best_decision_path = (
        output_dir / FINAL_BEST_DECISION_NAME
        if args.emit_final_best_decision
        else None
    )
    final_best_policy_path = Path(args.final_best_policy) if args.final_best_policy else None

    non_claims = [
        "no_hidden_qe_execution",
        "not_cycle_accurate_claim",
        "not_physical_fpga_performance_measurement",
        "not_final_public_family_winner",
    ]
    if qe_correctness_report is None and not qe_correctness_report_for:
        non_claims.append("not_qe_equivalent_scf_claim")
    else:
        non_claims.append("qe_equivalent_scf_claim_limited_to_external_stage_c_report")
    if implementation_evidence is None and not implementation_evidence_for:
        non_claims.append("not_rtl_hls_board_or_asic_implementation_claim")
    else:
        non_claims.append("implementation_claim_limited_to_external_stage_d_evidence_ceiling")

    summary = {
        "schema_version": "qe_fpga_dse_performance_summary_v0",
        "generated_at_utc": generated_at_utc,
        "claim_boundary": (
            "bounded_e2e_with_external_stage_c_d_evidence_when_provided_"
            "no_hidden_qe_or_implementation_execution_no_final_winner"
        ),
        "selected_request_ref": str(request_path),
        "selected_request_refs": [str(run["stage_b0_request"]) for run in candidate_runs],
        "candidate_count": len(candidate_runs),
        "candidate_summaries": [
            {
                "candidate_id": run.get("candidate_id"),
                "screening_rank": run.get("screening_rank"),
                "systemc_timed_functional": _report_summary(run["systemc_payload"]),
                "gem5_b4_timed_proxy": (
                    _report_summary(run["gem5_b4_payload"])
                    if isinstance(run.get("gem5_b4_payload"), Mapping)
                    else None
                ),
            }
            for run in candidate_runs
        ],
        "systemc_timed_functional": _report_summary(systemc_payload),
        "gem5_smoke": _report_summary(gem5_payload) if gem5_payload is not None else None,
        "gem5_b4_timed_proxy": _report_summary(gem5_b4_payload) if gem5_b4_payload is not None else None,
        "qe_correctness_report": str(qe_correctness_report) if qe_correctness_report else None,
        "qe_correctness_report_for": {
            candidate_id: str(path)
            for candidate_id, path in sorted(qe_correctness_report_for.items())
        },
        "implementation_evidence": str(implementation_evidence) if implementation_evidence else None,
        "implementation_evidence_for": {
            candidate_id: str(path)
            for candidate_id, path in sorted(implementation_evidence_for.items())
        },
        "backend_report_collection": str(backend_collection_path),
        "reranked_results": str(reranked_results_path),
        "bounded_recommendation": reranked_results.get("bounded_recommendation"),
        "final_recommendation": reranked_results.get("final_recommendation"),
        "final_recommendation_gate": reranked_results.get("final_recommendation_gate"),
        "final_best_architecture_decision": str(final_best_decision_path) if final_best_decision_path else None,
        "final_best_policy": str(final_best_policy_path) if final_best_policy_path else "default:hls_synthesis_minimum",
        "claim_ceiling_status_matrix": str(claim_matrix_refs["matrix"]),
        "known_metric_limits": [
            "systemc_timed_functional_proxy_only",
            "gem5_systemc_smoke_only_when_present",
            "gem5_systemc_timed_proxy_only_when_B4_present",
            "stage_c_and_stage_d_are_external_materialized_inputs_when_present",
            "cycle_proxy/device_busy may be absent or proxy-grade depending on backend report",
        ],
        "non_claims": non_claims,
    }
    summary_path = output_dir / "qe_fpga_dse_performance_summary_v0.json"
    _write_json(summary_path, summary)

    manifest = {
        "schema_version": "qe_fpga_dse_e2e_manifest_v0",
        "generated_at_utc": summary["generated_at_utc"],
        "repo_root": str(REPO_ROOT),
        "frontend_dse_dir": str(frontend_dir),
        "selected_backend_request": str(request_path),
        "selected_backend_requests": [str(run["stage_b0_request"]) for run in candidate_runs],
        "candidate_runs": [
            {
                "candidate_id": run.get("candidate_id"),
                "stage_b0_request": str(run["stage_b0_request"]),
                "systemc_backend_report": str(run["systemc_report"]),
                "gem5_b4_request": str(run["gem5_b4_request"]) if run.get("gem5_b4_request") else None,
                "gem5_b4_report": str(run["gem5_b4_report"]) if run.get("gem5_b4_report") else None,
                "gem5_b4_materialization_manifest": (
                    str(run["gem5_b4_materialization_manifest"])
                    if run.get("gem5_b4_materialization_manifest")
                    else None
                ),
            }
            for run in candidate_runs
        ],
        "systemc_backend_report": str(systemc_report),
        "systemc_frontend_evidence_ir": str(ingest_dir / "evidence_ir_collection_v0.json"),
        "qe_correctness_report": str(qe_correctness_report) if qe_correctness_report else None,
        "qe_correctness_report_for": {
            candidate_id: str(path)
            for candidate_id, path in sorted(qe_correctness_report_for.items())
        },
        "implementation_evidence": str(implementation_evidence) if implementation_evidence else None,
        "implementation_evidence_for": {
            candidate_id: str(path)
            for candidate_id, path in sorted(implementation_evidence_for.items())
        },
        "frontend_full_stage_status": (
            str(frontend_dir / "unified_dse_full_stage_status_v0.json")
            if args.emit_full_stage_status
            else None
        ),
        "gem5_smoke_mode": gem5_mode,
        "gem5_smoke_report": str(gem5_report) if gem5_report else None,
        "gem5_frontend_evidence_ir": str(gem5_ingest_dir / "evidence_ir_collection_v0.json") if gem5_report else None,
        "gem5_b4_mode": gem5_b4_mode,
        "gem5_b4_request": str(gem5_b4_request) if gem5_b4_request else None,
        "gem5_b4_report": str(gem5_b4_report) if gem5_b4_report else None,
        "backend_report_collection": str(backend_collection_path),
        "reranked_results": str(reranked_results_path),
        "performance_summary": str(summary_path),
        "claim_ceiling_status_matrix": str(claim_matrix_refs["matrix"]),
        "claim_ceiling_status_matrix_markdown": str(claim_matrix_refs["markdown"]),
        "final_best_architecture_decision": str(final_best_decision_path) if final_best_decision_path else None,
        "final_best_policy": str(final_best_policy_path) if final_best_policy_path else "default:hls_synthesis_minimum",
        "commands": commands,
        "non_claims": non_claims,
    }
    manifest_path = output_dir / "qe_fpga_dse_e2e_manifest_v0.json"
    _write_json(manifest_path, manifest)
    final_best_payload: dict[str, Any] | None = None
    if final_best_decision_path is not None:
        final_best_payload = _write_final_best_architecture_decision(
            final_best_decision_path,
            manifest_path=manifest_path,
            claim_matrix_path=claim_matrix_refs["matrix"],
            backend_collection_path=backend_collection_path,
            policy_path=final_best_policy_path,
        )
        summary["final_best_decision_status"] = final_best_payload.get("decision_status")
        summary["final_best_winner"] = final_best_payload.get("winner")
        _write_json(summary_path, summary)
    return {
        "manifest": manifest_path,
        "summary": summary_path,
        "manifest_payload": manifest,
        "final_best_decision": final_best_decision_path,
        "final_best_payload": final_best_payload,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run QE FPGA DSE frontend/backend JSON-v0 E2E flow")
    parser.add_argument("--design-space-spec", default=str(DEFAULT_DESIGN_SPACE))
    parser.add_argument("--workload", default=str(DEFAULT_WORKLOAD))
    parser.add_argument("--output-dir", default="tmp/qe_fpga_dse_e2e_v0")
    parser.add_argument("--max-design-points", type=int, default=8)
    parser.add_argument("--source-kind", default="fast_model_screening")
    parser.add_argument("--search-backend", default="stratified_cartesian")
    parser.add_argument("--shortlist-policy", default="top_fast_uncertain_diverse")
    parser.add_argument("--shortlist-size", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=3, help="Number of multi-fidelity selected candidates to run through B2.")
    parser.add_argument("--b4-top-n", type=int, default=1, help="Number of selected B2 candidates to escalate into B4.")
    parser.add_argument("--candidate-id", help="Optional explicit candidate_id to run instead of the Top-K selection.")
    parser.add_argument("--preferred-family", default="F2")
    parser.add_argument("--timeout-s", type=int, default=10)
    parser.add_argument("--clean", action="store_true", default=True)
    parser.add_argument("--no-clean", dest="clean", action="store_false")
    parser.add_argument("--include-gem5-smoke", action="store_true")
    parser.add_argument("--require-real-gem5-smoke", action="store_true")
    parser.add_argument("--gem5-timeout-s", type=int, default=60)
    parser.add_argument("--gem5-smoke-request", default=str(DEFAULT_B3_REQUEST))
    parser.add_argument("--legacy-b3-report", default=str(DEFAULT_LEGACY_B3_REPORT))
    parser.add_argument("--include-gem5-b4", action="store_true")
    parser.add_argument("--require-real-gem5-b4", action="store_true")
    parser.add_argument("--gem5-executable", default=str(DEFAULT_GEM5_EXECUTABLE))
    parser.add_argument("--gem5-b4-config", default=str(DEFAULT_GEM5_B4_CONFIG))
    parser.add_argument("--systemc-bridge-library", default=str(DEFAULT_SYSTEMC_BRIDGE))
    parser.add_argument("--qe-correctness-report", type=Path)
    parser.add_argument(
        "--qe-correctness-report-for",
        action="append",
        default=[],
        metavar="candidate_id=path",
        help=(
            "Attach a Stage C QE correctness report to exactly one candidate. "
            "May be repeated; the report JSON candidate_id must match the key."
        ),
    )
    parser.add_argument("--implementation-evidence", type=Path)
    parser.add_argument(
        "--implementation-evidence-for",
        action="append",
        default=[],
        metavar="candidate_id=path",
        help=(
            "Attach a Stage D implementation-evidence report to exactly one candidate. "
            "May be repeated; the evidence JSON candidate_id must match the key."
        ),
    )
    parser.add_argument("--emit-full-stage-status", action="store_true")
    parser.add_argument(
        "--claim-ceiling-status-matrix",
        type=Path,
        help=(
            "Optional output path for claim_ceiling_status_matrix_v0.json. "
            "Relative paths are written under --output-dir."
        ),
    )
    parser.add_argument(
        "--final-best-policy",
        type=Path,
        help=(
            "Optional qe_fpga_final_best_policy_v0 JSON. Defaults to HLS synthesis "
            "minimum Stage-D threshold when --emit-final-best-decision is used."
        ),
    )
    parser.add_argument(
        "--emit-final-best-decision",
        action="store_true",
        help=(
            "Emit qe_fpga_final_best_architecture_decision_v0.json. This does not "
            "weaken Stage C/D/B4 gates; winner remains null unless the policy passes."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.top_k < 0:
        parser.error("--top-k must be non-negative")
    if args.b4_top_n < 0:
        parser.error("--b4-top-n must be non-negative")
    if args.require_real_gem5_smoke:
        args.include_gem5_smoke = True
    if args.require_real_gem5_b4:
        args.include_gem5_b4 = True
    try:
        result = run_e2e(args)
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"manifest: {result['manifest']}")
    print(f"summary: {result['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
