from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from unified_dse.stage_d_implementation_evidence import (
    CLAIM_CEILING_BY_EVIDENCE_KIND,
    EVIDENCE_KINDS_BY_TARGET,
    IMPLEMENTATION_EVIDENCE_SCHEMA_VERSION,
    validate_implementation_evidence,
)
from unified_dse import stage_c_qe_correctness


MATRIX_SCHEMA_VERSION = "stage_d_implementation_evidence_matrix_v0"
DEFAULT_MATRIX_NAME = "stage_d_implementation_evidence_matrix_v0.json"
PLACEHOLDER_TOKENS = (
    "placeholder",
    "template",
    "example",
    "dummy",
    "todo",
    "tbd",
    "fill_me",
    "fill-me",
    "changeme",
    "change_me",
    "replace_me",
    "replace-me",
    "none",
    "null",
)

REAL_EVIDENCE_KINDS = (
    "hls_synthesis",
    "rtl_simulation",
    "fpga_board",
    "openroad_physical",
    "asic_ppa",
)


class EvidenceInputError(ValueError):
    pass


def parse_key_value(raw: str, option_name: str) -> tuple[str, str]:
    if "=" not in raw:
        raise EvidenceInputError(f"{option_name} must use key=value form: {raw}")
    key, value = raw.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        raise EvidenceInputError(f"{option_name} key must be non-empty")
    return key, value


def parse_metric_value(raw: str) -> Any:
    value = raw.strip()
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        if re.fullmatch(r"[-+]?\d+", value):
            return int(value)
        return float(value)
    except ValueError:
        return value


def parse_key_value_list(items: Sequence[str], option_name: str, *, parse_metric: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        key, value = parse_key_value(item, option_name)
        result[key] = parse_metric_value(value) if parse_metric else value
    return result


def parse_path_bindings(items: Sequence[str], option_name: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in items:
        key, value = parse_key_value(item, option_name)
        if key in result:
            raise EvidenceInputError(f"{option_name} specified more than once for candidate_id={key}")
        result[key] = Path(value)
    return result


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvidenceInputError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def is_placeholder_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return True
        lowered = stripped.lower()
        exact_placeholder_tokens = {"none", "null"}
        if lowered in exact_placeholder_tokens:
            return True
        return any(token in lowered for token in PLACEHOLDER_TOKENS if token not in exact_placeholder_tokens)
    return False


def has_placeholder_content(mapping: Mapping[str, Any]) -> bool:
    if not mapping:
        return True
    for key, value in mapping.items():
        if is_placeholder_value(key) or is_placeholder_value(value):
            return True
    return False


def has_any_metric(metrics: Mapping[str, Any], names: Sequence[str]) -> bool:
    return any(name in metrics and not is_placeholder_value(metrics[name]) for name in names)


def has_all_metrics(metrics: Mapping[str, Any], names: Sequence[str]) -> bool:
    return all(name in metrics and not is_placeholder_value(metrics[name]) for name in names)


def has_metric_prefix(metrics: Mapping[str, Any], prefixes: Sequence[str]) -> bool:
    return any(any(str(key).startswith(prefix) for prefix in prefixes) and not is_placeholder_value(value) for key, value in metrics.items())


def has_metric_fragment(metrics: Mapping[str, Any], fragments: Sequence[str]) -> bool:
    return any(any(fragment in str(key) for fragment in fragments) and not is_placeholder_value(value) for key, value in metrics.items())


def real_evidence_requirements_met(
    evidence_kind: str,
    artifact_refs: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> bool:
    if evidence_kind == "hls_synthesis":
        return (
            has_any_metric(artifact_refs, ("hls_report",))
            and has_any_metric(metrics, ("estimated_lut",))
            and has_any_metric(metrics, ("estimated_bram", "fmax_mhz"))
        )
    if evidence_kind == "rtl_simulation":
        return (
            has_any_metric(artifact_refs, ("rtl_sim_report",))
            and has_any_metric(metrics, ("simulation_passed",))
            and has_any_metric(metrics, ("cycle_count", "latency_cycles"))
        )
    if evidence_kind == "fpga_board":
        return (
            has_all_metrics(artifact_refs, ("board_manifest", "board_metrics", "board_compare"))
            and has_metric_prefix(metrics, ("measured_",))
        )
    if evidence_kind == "openroad_physical":
        return (
            has_any_metric(artifact_refs, ("openroad_report",))
            and has_metric_fragment(metrics, ("area",))
            and has_metric_fragment(metrics, ("timing", "slack", "fmax", "power"))
        )
    if evidence_kind == "asic_ppa":
        return (
            has_any_metric(artifact_refs, ("asic_ppa_report",))
            and has_metric_fragment(metrics, ("area",))
            and has_metric_fragment(metrics, ("power",))
            and has_metric_fragment(metrics, ("frequency", "freq", "fmax"))
        )
    return False


def materialized_evidence_kind(
    requested_evidence_kind: str,
    artifact_refs: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> str:
    if requested_evidence_kind == "implementation_projection":
        return "implementation_projection"
    if requested_evidence_kind not in REAL_EVIDENCE_KINDS:
        return "implementation_projection"
    if has_placeholder_content(artifact_refs) or has_placeholder_content(metrics):
        return "implementation_projection"
    if not real_evidence_requirements_met(requested_evidence_kind, artifact_refs, metrics):
        return "implementation_projection"
    return requested_evidence_kind


def sanitize_id_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("_") or "unknown"


def build_payload(
    *,
    candidate_id: str,
    implementation_target_class: str,
    requested_evidence_kind: str,
    requested_evidence_status: str | None,
    artifact_refs: Mapping[str, Any],
    metrics: Mapping[str, Any],
    qe_correctness_report: Path | None,
) -> dict[str, Any]:
    if implementation_target_class not in EVIDENCE_KINDS_BY_TARGET:
        raise EvidenceInputError("implementation_target_class must be fpga or asic")
    if requested_evidence_kind not in EVIDENCE_KINDS_BY_TARGET[implementation_target_class]:
        raise EvidenceInputError("evidence_kind is not valid for implementation_target_class")

    evidence_kind = materialized_evidence_kind(requested_evidence_kind, artifact_refs, metrics)
    evidence_status = requested_evidence_status or "available"
    if evidence_kind == "implementation_projection":
        evidence_status = "partial"
    qe_claim = False
    if qe_correctness_report is not None:
        correctness_payload = stage_c_qe_correctness.load_and_validate_qe_correctness_report(
            qe_correctness_report
        )
        if str(correctness_payload.get("candidate_id")) != candidate_id:
            raise EvidenceInputError("QE correctness report candidate_id must match --candidate-id")
        qe_claim = correctness_payload.get("qe_equivalent_scf_claim") is True

    payload = {
        "schema_version": IMPLEMENTATION_EVIDENCE_SCHEMA_VERSION,
        "execution_status": "external_evidence_referenced",
        "evidence_id": "stage_d_{}_{}_{}".format(
            sanitize_id_part(implementation_target_class),
            sanitize_id_part(candidate_id),
            sanitize_id_part(evidence_kind),
        ),
        "candidate_id": candidate_id,
        "implementation_target_class": implementation_target_class,
        "evidence_kind": evidence_kind,
        "evidence_status": evidence_status,
        "claim_ceiling": CLAIM_CEILING_BY_EVIDENCE_KIND[evidence_kind],
        "artifact_refs": dict(artifact_refs),
        "metrics": dict(metrics),
        "correctness_dependency": {
            "qe_equivalent_scf_claim": qe_claim,
            "qe_correctness_report_ref": str(qe_correctness_report) if qe_correctness_report else None,
        },
        "final_public_family_winner": None,
        "public_winner_claim": False,
        "production_release_ready": False,
    }
    validate_implementation_evidence(payload)
    return payload


def _candidate_entries_from_map(path: Path) -> list[dict[str, Any]]:
    payload = load_json_object(path)
    raw_entries: Any = None
    for key in ("candidates", "evidence", "rows"):
        if isinstance(payload.get(key), list):
            raw_entries = payload[key]
            break
    if raw_entries is None:
        raw_entries = []
        for candidate_id, value in payload.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("candidate_id", candidate_id)
                raw_entries.append(item)
    if not isinstance(raw_entries, list):
        raise EvidenceInputError("candidate evidence map must contain a candidates/evidence/rows list or candidate-id object")
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(raw_entries):
        if not isinstance(item, dict):
            raise EvidenceInputError(f"candidate evidence map entry {index} must be an object")
        if not item.get("candidate_id"):
            raise EvidenceInputError(f"candidate evidence map entry {index} missing candidate_id")
        entries.append(dict(item))
    return entries


def _entry_mapping(entry: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = entry.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise EvidenceInputError(f"{key} must be a JSON object for candidate_id={entry.get('candidate_id')}")
    return dict(value)


def _qe_report_for_candidate(
    candidate_id: str,
    *,
    entry_ref: Any,
    singular_ref: Path | None,
    per_candidate_refs: Mapping[str, Path],
) -> Path | None:
    if entry_ref:
        return Path(str(entry_ref))
    if candidate_id in per_candidate_refs:
        return per_candidate_refs[candidate_id]
    if singular_ref is not None:
        try:
            payload = stage_c_qe_correctness.load_and_validate_qe_correctness_report(singular_ref)
        except Exception as exc:  # pragma: no cover - build_payload reports the details on the normal path
            raise EvidenceInputError(f"QE correctness report validation failed: {exc}") from exc
        if str(payload.get("candidate_id")) == candidate_id:
            return singular_ref
    return None


def materialize_many(
    *,
    candidate_evidence_map: Path,
    output_dir: Path,
    implementation_target_class: str | None = None,
    evidence_kind: str | None = None,
    evidence_status: str | None = None,
    qe_correctness_report: Path | None = None,
    qe_correctness_report_for: Mapping[str, Path] | None = None,
    matrix_name: str = DEFAULT_MATRIX_NAME,
) -> dict[str, Any]:
    entries = _candidate_entries_from_map(candidate_evidence_map)
    rows: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    evidence_kind_counts: dict[str, int] = {}
    per_candidate_refs = dict(qe_correctness_report_for or {})
    reports_dir = output_dir / "stage_d_evidence"
    reports_dir.mkdir(parents=True, exist_ok=True)

    for entry in entries:
        candidate_id = str(entry["candidate_id"])
        target = str(entry.get("implementation_target_class") or implementation_target_class or "")
        kind = str(entry.get("evidence_kind") or evidence_kind or "")
        if not target:
            raise EvidenceInputError(f"implementation_target_class missing for candidate_id={candidate_id}")
        if not kind:
            raise EvidenceInputError(f"evidence_kind missing for candidate_id={candidate_id}")
        qe_ref = _qe_report_for_candidate(
            candidate_id,
            entry_ref=entry.get("qe_correctness_report"),
            singular_ref=qe_correctness_report,
            per_candidate_refs=per_candidate_refs,
        )
        payload = build_payload(
            candidate_id=candidate_id,
            implementation_target_class=target,
            requested_evidence_kind=kind,
            requested_evidence_status=str(entry.get("evidence_status") or evidence_status)
            if (entry.get("evidence_status") or evidence_status)
            else None,
            artifact_refs=_entry_mapping(entry, "artifact_refs"),
            metrics=_entry_mapping(entry, "metrics"),
            qe_correctness_report=qe_ref,
        )
        report_path = reports_dir / f"{sanitize_id_part(candidate_id)}.qe_dse_fpga_asic_implementation_evidence_v0.json"
        write_json(report_path, payload)
        status = str(payload["evidence_status"])
        kind_key = str(payload["evidence_kind"])
        status_counts[status] = status_counts.get(status, 0) + 1
        evidence_kind_counts[kind_key] = evidence_kind_counts.get(kind_key, 0) + 1
        rows.append(
            {
                "candidate_id": candidate_id,
                "implementation_target_class": payload["implementation_target_class"],
                "evidence_kind": payload["evidence_kind"],
                "evidence_status": payload["evidence_status"],
                "claim_ceiling": payload["claim_ceiling"],
                "qe_correctness_report_ref": payload["correctness_dependency"]["qe_correctness_report_ref"],
                "qe_equivalent_scf_claim": payload["correctness_dependency"]["qe_equivalent_scf_claim"],
                "report_path": str(report_path),
            }
        )

    matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "source_candidate_evidence_map": str(candidate_evidence_map),
        "report_schema_version": IMPLEMENTATION_EVIDENCE_SCHEMA_VERSION,
        "reports_dir": str(reports_dir),
        "row_count": len(rows),
        "status_counts": status_counts,
        "evidence_kind_counts": evidence_kind_counts,
        "rows": rows,
        "non_claims": [
            "implementation_projection_is_partial_not_hardware_evidence",
            "no_final_public_family_winner",
            "no_production_release_ready_claim",
        ],
    }
    write_json(output_dir / matrix_name, matrix)
    return matrix


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize a Stage D FPGA/ASIC implementation-evidence JSON artifact for Unified DSE."
    )
    parser.add_argument("--candidate-id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--candidate-evidence-map", type=Path)
    parser.add_argument("--matrix-name", default=DEFAULT_MATRIX_NAME)
    parser.add_argument("--implementation-target-class", choices=sorted(EVIDENCE_KINDS_BY_TARGET))
    parser.add_argument(
        "--evidence-kind",
        choices=sorted({kind for kinds in EVIDENCE_KINDS_BY_TARGET.values() for kind in kinds}),
    )
    parser.add_argument("--evidence-status", choices=("available", "partial", "failed"), default=None)
    parser.add_argument("--artifact-ref", action="append", default=[], metavar="key=path")
    parser.add_argument("--metric", action="append", default=[], metavar="key=value")
    parser.add_argument("--qe-correctness-report", type=Path, default=None)
    parser.add_argument("--qe-correctness-report-for", action="append", default=[], metavar="candidate_id=path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        qe_correctness_report_for = parse_path_bindings(
            args.qe_correctness_report_for,
            "--qe-correctness-report-for",
        )
        if args.candidate_evidence_map is not None:
            if args.output_dir is None:
                raise EvidenceInputError("--output-dir is required with --candidate-evidence-map")
            materialize_many(
                candidate_evidence_map=args.candidate_evidence_map,
                output_dir=args.output_dir,
                implementation_target_class=args.implementation_target_class,
                evidence_kind=args.evidence_kind,
                evidence_status=args.evidence_status,
                qe_correctness_report=args.qe_correctness_report,
                qe_correctness_report_for=qe_correctness_report_for,
                matrix_name=args.matrix_name,
            )
            return 0
        if args.candidate_id is None:
            raise EvidenceInputError("--candidate-id is required without --candidate-evidence-map")
        if args.output is None:
            raise EvidenceInputError("--output is required without --candidate-evidence-map")
        if args.implementation_target_class is None:
            raise EvidenceInputError("--implementation-target-class is required without --candidate-evidence-map")
        if args.evidence_kind is None:
            raise EvidenceInputError("--evidence-kind is required without --candidate-evidence-map")
        artifact_refs = parse_key_value_list(args.artifact_ref, "--artifact-ref")
        metrics = parse_key_value_list(args.metric, "--metric", parse_metric=True)
        payload = build_payload(
            candidate_id=args.candidate_id,
            implementation_target_class=args.implementation_target_class,
            requested_evidence_kind=args.evidence_kind,
            requested_evidence_status=args.evidence_status,
            artifact_refs=artifact_refs,
            metrics=metrics,
            qe_correctness_report=args.qe_correctness_report,
        )
    except EvidenceInputError as exc:
        parser.error(str(exc))

    write_json(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
