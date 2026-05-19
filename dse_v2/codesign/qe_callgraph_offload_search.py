#!/usr/bin/env python3
"""QE full-callgraph offload-search contracts for Complete-DSE.

This module is the execution surface for
``prd-complete-dse-qe-callgraph-offload-search.md``.  It intentionally keeps
QE-specific callgraph and patch semantics outside the generic DSE core while
making the *choice of what to offload* a stable design identity dimension for
this QE reference branch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from dse_v2.codesign.complete_dse_search_space import (
    IDENTITY_LAYER_KEYS,
    NON_IDENTITY_FIELDS,
    RELEASE_ID,
    _as_dict,
    _forbidden_identity_field_paths,
    _stable_hash_without,
    build_release_subset_manifest,
    canonical_candidate_identity,
)
from dse_v2.codesign.release_domain import stable_json_hash
from dse_v2.reference_workloads.qe_mainflow import (
    default_qe_mainflow_workload_suite,
    validate_qe_mainflow_workload_suite,
)

OFFLOAD_SEARCH_SCHEMA = "dse.codesign.qe_callgraph_offload_search.v1"
OFFLOAD_IDENTITY_SCHEMA = "dse.codesign.qe_offload_candidate_identity.v1"
WORKLOAD_VARIANT_SEARCH_SCHEMA = "dse.qe_workload_variant_search_space.v1"
WORKLOAD_VARIANT_BINDING_SCHEMA = "dse.qe_workload_variant_binding.v1"
BUNDLE_RUNTIME_CONTRACT_SCHEMA = "dse.qe_bundle_runtime_contract_report.v1"
OFFLOAD_TARGET_LAYER = "offload_target_parameters"
OFFLOAD_IDENTITY_LAYER_KEYS = IDENTITY_LAYER_KEYS + (OFFLOAD_TARGET_LAYER,)

OFFLOAD_NON_IDENTITY_FIELDS = NON_IDENTITY_FIELDS + (
    "workload_case_id",
    "workload_case_ids",
    "evidence_source",
    "evidence_kind",
    "projection_score",
    "l4_attempt_status",
    "value_label",
)

BANNED_VALUE_EVIDENCE_KINDS = {
    "l1_projection",
    "l2_model_projection",
    "l3_timing_projection",
    "profile_only",
    "static_model_only",
    "python_sidecar",
    "component_model",
    "descriptor_only",
    "hpsi_only_without_callgraph_inventory",
    "real_qe_l4_dataflow_smoke",
    "real_qe_l4_attempt_smoke",
}

SMOKE_ONLY_EVIDENCE_SCOPES = {
    "smoke",
    "dataflow_smoke",
    "dataflow_smoke_only",
    "bridge_smoke_only",
}

VALUE_LABELS = (
    "queued_by_projection",
    "attempted_l4",
    "valuable_l4",
    "not_valuable_l4",
    "blocked",
    "research_only",
    "out_of_scope_with_reason",
)

KERNEL_FAMILY_MAP = {
    "h_psi": "dense_subspace",
    "s_psi": "dense_subspace",
    "diagonalization": "dense_subspace",
    "subspace_rotation": "dense_subspace",
    "rho_out": "density_update",
    "mix_rho": "vector_update",
    "veff": "potential_update",
    "fft": "fft_grid",
    "forces": "force_stress",
    "stress": "force_stress",
    "band_path_projection": "post_processing",
}

FIRST_PASS_ACTUAL_COMPUTE_RUNTIME_SUPPORTED_KERNELS = (
    "fft",
    "subspace_rotation",
)

SOURCE_SYMBOL_HINTS = {
    "h_psi": ("h_psi", "hpsi"),
    "s_psi": ("s_psi", "spsi"),
    "diagonalization": ("diagh", "cdiagh", "rdiagh"),
    "subspace_rotation": ("rotate", "subspace"),
    "rho_out": ("rho", "sum_band"),
    "mix_rho": ("mix_rho", "mix"),
    "veff": ("v_of_rho", "veff"),
    "fft": ("fft",),
    "forces": ("force", "forces"),
    "stress": ("stress",),
    "band_path_projection": ("bands", "punch_band"),
}

SOURCE_SUFFIXES = {".f90", ".F90", ".f", ".F", ".c", ".cc", ".cpp", ".h"}

WORKLOAD_SELECTION_AXES = (
    "program",
    "stage_type",
    "phase",
    "kernel",
    "callsite",
    "bundle",
    "workload_variant",
    "pseudopotential_family",
)

SPSI_USPP_WORKLOAD_VARIANT_ID = "qe_si_uspp_spsi_probe_v1"
SPSI_NC_CG_WORKLOAD_VARIANT_ID = "qe_si_nc_cg_spsi_identity_probe_v1"
SPSI_NC_CG_LARGER_WORKLOAD_VARIANT_ID = (
    "qe_si_nc_cg_spsi_larger_bandgrid_probe_v1"
)
SPSI_NC_CG_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID = (
    "qe_si_nc_cg_spsi_amortized_bandgrid_probe_v1"
)
NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID = (
    "qe_si_nscf_amortized_bandgrid_probe_v1"
)
NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID = "qe_si_nscf_heavy_bandgrid_probe_v1"
NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID = "qe_si_nscf_ultra_bandgrid_probe_v1"
NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID = "qe_si_nscf_stress_bandgrid_probe_v1"


def _default_source_root() -> Path:
    return Path("runs/dse/_tools/q-e-src")


def _default_build_root(source_root: Path) -> Path:
    if source_root.name == "q-e-src":
        return source_root.parent / "q-e-build"
    return source_root.parent / "q-e-build"


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_root_payload(source_root: Path) -> Dict[str, Any]:
    root = Path(source_root)
    if not root.exists():
        marker_hash = stable_json_hash({"path": str(root), "exists": False})
        return {
            "path": str(root),
            "exists": False,
            "status": "blocked_source_unavailable",
            "hash": marker_hash,
            "tree_hash": marker_hash,
        }
    marker_files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
    )[:256]
    marker_hash = stable_json_hash(
        [
            {"path": str(path.relative_to(root)), "size": path.stat().st_size}
            for path in marker_files
        ]
    )
    return {
        "path": str(root),
        "exists": True,
        "status": "available",
        "sampled_source_file_count": len(marker_files),
        "hash": marker_hash,
        "tree_hash": marker_hash,
    }


def _build_root_payload(build_root: Path) -> Dict[str, Any]:
    root = Path(build_root)
    if not root.exists():
        marker_hash = stable_json_hash({"path": str(root), "exists": False})
        return {
            "path": str(root),
            "exists": False,
            "status": "blocked_build_unavailable",
            "hash": marker_hash,
        }
    marker_files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name
        in {"pw.x", "bands.x", "Makefile", "config.log"}
    )[:128]
    marker_hash = stable_json_hash(
        [
            {"path": str(path.relative_to(root)), "size": path.stat().st_size}
            for path in marker_files
        ]
    )
    return {
        "path": str(root),
        "exists": True,
        "status": "available",
        "sampled_build_file_count": len(marker_files),
        "hash": marker_hash,
    }


def _find_source_hits(
    source_root: Path,
    kernel: str,
    *,
    max_files: int = 4000,
    max_hits: int = 3,
) -> list[Dict[str, Any]]:
    root = Path(source_root)
    if not root.exists():
        return []
    hints = tuple(hint.lower() for hint in SOURCE_SYMBOL_HINTS.get(kernel, (kernel,)))
    hits: list[Dict[str, Any]] = []
    visited = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
            continue
        visited += 1
        if visited > max_files:
            break
        lower_name = path.name.lower()
        name_hit = any(hint in lower_name for hint in hints)
        text_hit = False
        if not name_hit:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")[:65536].lower()
            except OSError:
                text = ""
            text_hit = any(hint in text for hint in hints)
        if name_hit or text_hit:
            hits.append(
                {
                    "path": str(path.relative_to(root)),
                    "match_kind": "file_name" if name_hit else "content_probe",
                    "symbol_or_subroutine": hints[0] if hints else kernel,
                    "sha256": _file_sha256(path),
                }
            )
            if len(hits) >= max_hits:
                break
    return hits


_FORTRAN_DEF_RE = re.compile(
    r"^\s*(?:recursive\s+|pure\s+|elemental\s+|module\s+)*"
    r"(?:(?:[a-z_][\w]*(?:\s*\([^)]*\))?\s+)+)?"
    r"(subroutine|function|program|module)\s+([a-z_]\w*)\b",
    re.IGNORECASE,
)
_FORTRAN_CALL_RE = re.compile(r"\bcall\s+([a-z_]\w*)\b", re.IGNORECASE)
_FORTRAN_USE_RE = re.compile(r"^\s*use(?:\s*,\s*intrinsic\s*)?(?:\s*::)?\s+([a-z_]\w*)\b", re.IGNORECASE)
_FORTRAN_END_RE = re.compile(
    r"^\s*end\s*$|^\s*end\s+"
    r"(?:subroutine|function|program|module)(?:\s+[a-z_]\w*)?\s*$",
    re.IGNORECASE,
)
_C_DEF_RE = re.compile(
    r"^\s*(?:static\s+|extern\s+|inline\s+|const\s+|volatile\s+|unsigned\s+|signed\s+|long\s+|short\s+|struct\s+\w+\s+|enum\s+\w+\s+|[a-z_]\w*\s+|[*]\s*)+"
    r"([a-z_]\w*)\s*\([^;{}]*\)\s*\{",
    re.IGNORECASE,
)
_C_CALL_RE = re.compile(r"\b([a-z_]\w*)\s*\(", re.IGNORECASE)
_C_NON_CALL_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
    "defined",
    "case",
    "do",
}


def _strip_fortran_comment(line: str) -> str:
    in_single = False
    in_double = False
    result: list[str] = []
    for ch in line:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "!" and not in_single and not in_double:
            break
        result.append(ch)
    return "".join(result)


def _strip_c_comment(line: str, *, in_block_comment: bool) -> tuple[str, bool]:
    """Strip C/C++ comments while preserving code outside string literals."""
    result: list[str] = []
    index = 0
    in_single = False
    in_double = False
    while index < len(line):
        ch = line[index]
        nxt = line[index + 1] if index + 1 < len(line) else ""
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                index += 2
            else:
                index += 1
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            result.append(ch)
            index += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            result.append(ch)
            index += 1
            continue
        if not in_single and not in_double and ch == "/" and nxt == "*":
            in_block_comment = True
            index += 2
            continue
        if not in_single and not in_double and ch == "/" and nxt == "/":
            break
        result.append(ch)
        index += 1
    return "".join(result), in_block_comment


def _count_c_braces(line: str) -> int:
    return line.count("{") - line.count("}")


def _guess_kernel_from_static_symbol(symbol: str, source_file: str) -> str | None:
    haystack = f"{symbol} {source_file}".lower()
    scored: list[tuple[int, str]] = []
    for kernel, hints in SOURCE_SYMBOL_HINTS.items():
        for hint in hints:
            hint_text = str(hint).lower()
            if not hint_text:
                continue
            if hint_text == symbol.lower():
                scored.append((0, kernel))
            elif hint_text in haystack:
                scored.append((1, kernel))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]))
    return scored[0][1]


def _static_offload_candidate_summary(
    definitions: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    candidates: list[Dict[str, Any]] = []
    kernel_counts: Dict[str, int] = {}
    for row in definitions:
        symbol = str(row.get("symbol") or "")
        source_file = str(row.get("source_file") or "")
        kernel = _guess_kernel_from_static_symbol(symbol, source_file)
        if kernel is None:
            continue
        kernel_counts[kernel] = kernel_counts.get(kernel, 0) + 1
        candidates.append(
            {
                "symbol": symbol,
                "source_file": source_file,
                "line": row.get("line"),
                "kind": row.get("kind"),
                "kernel_guess": kernel,
                "kernel_family": KERNEL_FAMILY_MAP.get(
                    kernel,
                    "unknown_or_control",
                ),
                "call_count": row.get("call_count", 0),
                "classification": "research_only_static_candidate",
                "promotion_requirement": (
                    "bind to a concrete workload/stage/callsite and pass real "
                    "QE trace plus L4 value gates before it can become an "
                    "attempted_l4 opportunity"
                ),
                "claim_boundary": (
                    "static source candidate only; not a value claim and not "
                    "yet a workload-bound offload opportunity"
                ),
            }
        )
    candidates.sort(
        key=lambda row: (
            -int(row.get("call_count") or 0),
            str(row.get("kernel_guess") or ""),
            str(row.get("source_file") or ""),
            str(row.get("symbol") or ""),
        )
    )
    return {
        "schema_version": "dse.qe_static_offload_candidate_summary.v1",
        "candidate_count": len(candidates),
        "kernel_counts": dict(sorted(kernel_counts.items())),
        "candidates_sample": candidates[:256],
        "classification": "research_only_until_workload_bound",
        "claim_boundary": (
            "full static QE source scan can discover research candidates, but "
            "DSE value requires workload binding, trace observation, real L4, "
            "correctness, replacement consumption, and positive speed"
        ),
    }


def _extract_static_callgraph(
    source_root: Path,
    *,
    max_files: int = 12000,
) -> Dict[str, Any]:
    root = Path(source_root)
    if not root.exists():
        return {
            "schema_version": "dse.qe_static_callgraph_extract.v1",
            "status": "blocked",
            "source_root": str(root),
            "blockers": ["source_root_unavailable"],
            "definition_count": 0,
            "edge_count": 0,
            "files_scanned": 0,
            "claim_boundary": (
                "static parser did not run; inventory falls back to workload seeds"
            ),
        }

    definitions: Dict[str, Dict[str, Any]] = {}
    edges: Dict[tuple[str, str], Dict[str, Any]] = {}
    uses: Dict[str, set[str]] = {}
    parse_blockers: list[str] = []
    files_scanned = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
            continue
        files_scanned += 1
        if files_scanned > max_files:
            parse_blockers.append("static_callgraph_file_scan_cap_reached")
            break
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            parse_blockers.append(f"source_read_failed:{path.name}:{exc.__class__.__name__}")
            continue
        relative = str(path.relative_to(root))
        current_symbol: str | None = None
        current_kind: str | None = None
        continued = ""
        c_block_comment = False
        c_brace_depth = 0
        is_c_like = path.suffix.lower() in {".c", ".cc", ".cpp", ".h"}
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            if is_c_like:
                line, c_block_comment = _strip_c_comment(
                    raw_line,
                    in_block_comment=c_block_comment,
                )
            else:
                line = _strip_fortran_comment(raw_line)
            line = line.strip()
            if not line:
                continue
            if is_c_like:
                definition = _C_DEF_RE.match(line)
                counted_c_definition_braces = False
                if current_symbol is None and definition:
                    symbol = definition.group(1).lower()
                    if symbol not in _C_NON_CALL_KEYWORDS:
                        current_symbol = symbol
                        current_kind = "c_function"
                        c_brace_depth = _count_c_braces(line)
                        counted_c_definition_braces = True
                        definitions.setdefault(
                            symbol,
                            {
                                "symbol": symbol,
                                "kind": "c_function",
                                "source_file": relative,
                                "line": line_number,
                                "call_count": 0,
                                "use_count": 0,
                            },
                        )
                if current_symbol is None:
                    continue
                for callee in _C_CALL_RE.findall(line):
                    callee_text = callee.lower()
                    if (
                        callee_text in _C_NON_CALL_KEYWORDS
                        or callee_text == current_symbol
                    ):
                        continue
                    key = (current_symbol, callee_text)
                    edge = edges.setdefault(
                        key,
                        {
                            "caller": current_symbol,
                            "callee": callee_text,
                            "source_file": relative,
                            "first_line": line_number,
                            "count": 0,
                        },
                    )
                    edge["count"] += 1
                    if current_symbol in definitions:
                        definitions[current_symbol]["call_count"] += 1
                if not counted_c_definition_braces:
                    c_brace_depth += _count_c_braces(line)
                if c_brace_depth <= 0:
                    current_symbol = None
                    current_kind = None
                    c_brace_depth = 0
                continue
            if continued:
                line = continued + " " + line.lstrip("&").strip()
            if line.endswith("&"):
                continued = line[:-1].strip()
                continue
            continued = ""

            lower = line.lower()
            if _FORTRAN_END_RE.match(lower):
                current_symbol = None
                current_kind = None
                continue

            definition = _FORTRAN_DEF_RE.match(line)
            if definition:
                kind = definition.group(1).lower()
                symbol = definition.group(2).lower()
                if kind == "module" and symbol.startswith("procedure"):
                    continue
                current_symbol = symbol
                current_kind = kind
                definitions.setdefault(
                    symbol,
                    {
                        "symbol": symbol,
                        "kind": kind,
                        "source_file": relative,
                        "line": line_number,
                        "call_count": 0,
                        "use_count": 0,
                    },
                )
                continue

            if current_symbol is None:
                continue

            for used in _FORTRAN_USE_RE.findall(line):
                uses.setdefault(current_symbol, set()).add(used.lower())
            for callee in _FORTRAN_CALL_RE.findall(line):
                callee_text = callee.lower()
                key = (current_symbol, callee_text)
                edge = edges.setdefault(
                    key,
                    {
                        "caller": current_symbol,
                        "callee": callee_text,
                        "source_file": relative,
                        "first_line": line_number,
                        "count": 0,
                    },
                )
                edge["count"] += 1
                if current_symbol in definitions:
                    definitions[current_symbol]["call_count"] += 1
        if current_symbol is not None and current_kind is not None:
            # Unterminated program units are common in simple regex parsing when
            # preprocessor branches hide the matching end; record but keep data.
            parse_blockers.append(f"unterminated_unit_probe:{relative}:{current_symbol}")

    for symbol, modules in uses.items():
        if symbol in definitions:
            definitions[symbol]["use_count"] = len(modules)

    definitions_list = sorted(
        definitions.values(), key=lambda row: (str(row["source_file"]), str(row["symbol"]))
    )
    edges_list = sorted(edges.values(), key=lambda row: (str(row["caller"]), str(row["callee"])))
    defined_symbols = set(definitions)
    unresolved_callees = sorted(
        {str(edge["callee"]) for edge in edges_list if edge["callee"] not in defined_symbols}
    )
    offload_candidate_summary = _static_offload_candidate_summary(definitions_list)
    payload = {
        "schema_version": "dse.qe_static_callgraph_extract.v1",
        "status": "passed" if definitions_list else "blocked",
        "source_root": str(root),
        "files_scanned": files_scanned,
        "definition_count": len(definitions_list),
        "edge_count": len(edges_list),
        "unresolved_callee_count": len(unresolved_callees),
        "unresolved_callees_sample": unresolved_callees[:64],
        "definitions_sample": definitions_list[:128],
        "edges_sample": edges_list[:256],
        "offload_candidate_summary": offload_candidate_summary,
        "offload_candidate_count": offload_candidate_summary["candidate_count"],
        "offload_candidate_kernel_counts": offload_candidate_summary["kernel_counts"],
        "blockers": _dedupe_strings(parse_blockers),
        "parser_limitations": [
            "regex_fortran_frontend_no_interprocedural_type_resolution",
            "call_statements_only_function_references_not_resolved",
            "preprocessor_and_interface_dispatch_are_best_effort",
        ],
        "semantic_resolution_complete": False,
        "claim_boundary": (
            "real QE source static extraction for inventory breadth; not a "
            "proof of complete semantic whole-program callgraph closure"
        ),
    }
    payload["callgraph_hash"] = _stable_hash_without(payload, "callgraph_hash")
    return payload


def _case_workflow_programs(case: Mapping[str, Any]) -> list[str]:
    programs = []
    command = case.get("qe_command") or []
    if command:
        programs.append(str(command[0]))
    for stage in case.get("workflow_stages") or []:
        if isinstance(stage, Mapping) and stage.get("program"):
            programs.append(str(stage["program"]))
    return sorted(set(programs))


def _case_profile_phases(case: Mapping[str, Any]) -> Dict[str, float]:
    phases: Dict[str, float] = {}
    for stage in case.get("step1_source", {}).get("stages", []) or []:
        if not isinstance(stage, Mapping):
            continue
        profile = stage.get("profile")
        if not isinstance(profile, Mapping):
            continue
        for name, value in dict(profile.get("phases") or {}).items():
            if isinstance(value, (int, float)):
                phases[str(name)] = float(value)
    return phases


def _offload_forbidden_identity_field_paths(
    value: Any, *, prefix: str = ""
) -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in OFFLOAD_NON_IDENTITY_FIELDS:
                paths.append(path)
            paths.extend(
                _offload_forbidden_identity_field_paths(child, prefix=path)
            )
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, child in enumerate(value):
            paths.extend(
                _offload_forbidden_identity_field_paths(
                    child, prefix=f"{prefix}[{index}]"
                )
            )
    return paths


def example_offload_target_parameters(
    *,
    opportunity_ids: Sequence[str] | None = None,
    bundle_id: str | None = None,
    granularity: str = "bundle",
    workload_variant_binding: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    ids = list(opportunity_ids or ["opp_qe_si_scf_small_v1_h_psi"])
    payload: Dict[str, Any] = {
        "granularity": granularity,
        "opportunity_ids": ids,
        "bundle_id": bundle_id or "bundle_" + stable_json_hash(ids)[:12],
        "patch_strategy": "qe_source_patch_callsite_instrumentation",
        "runtime_payload_schema": "qe.offload.extension_payload.v1",
        "fallback_policy": "pure_qe_software_fallback",
    }
    if workload_variant_binding is not None:
        payload["workload_variant_binding"] = _as_dict(
            workload_variant_binding,
            field_name="workload_variant_binding",
        )
    return payload


def _validate_workload_variant_binding(binding: Any) -> None:
    if binding is None:
        return
    if not isinstance(binding, Mapping) or not binding:
        raise ValueError(
            "offload_target_parameters.workload_variant_binding must be a non-empty mapping"
        )
    required = ("schema_version", "workload_variant_id", "formal_status")
    missing = [field for field in required if not binding.get(field)]
    if missing:
        raise ValueError(
            "offload_target_parameters.workload_variant_binding missing fields: "
            + ", ".join(missing)
        )
    if binding.get("schema_version") != WORKLOAD_VARIANT_BINDING_SCHEMA:
        raise ValueError(
            "offload_target_parameters.workload_variant_binding.schema_version "
            f"must be {WORKLOAD_VARIANT_BINDING_SCHEMA}"
        )


def canonical_offload_candidate_identity(
    identity_layers: Mapping[str, Any],
) -> Dict[str, Any]:
    missing = [layer for layer in OFFLOAD_IDENTITY_LAYER_KEYS if layer not in identity_layers]
    if missing:
        raise ValueError(
            "missing offload candidate identity layers: " + ", ".join(missing)
        )
    unexpected = sorted(set(identity_layers) - set(OFFLOAD_IDENTITY_LAYER_KEYS))
    unexpected_design = [field for field in unexpected if field not in OFFLOAD_NON_IDENTITY_FIELDS]
    if unexpected_design:
        raise ValueError(
            "unknown offload candidate identity layers: " + ", ".join(unexpected_design)
        )

    forbidden = sorted(
        set(_forbidden_identity_field_paths(identity_layers))
        | set(_offload_forbidden_identity_field_paths(identity_layers))
    )
    forbidden.extend(field for field in unexpected if field in OFFLOAD_NON_IDENTITY_FIELDS and field not in forbidden)
    if forbidden:
        raise ValueError(
            "non-identity fields supplied as offload identity layers: " + ", ".join(forbidden)
        )

    base_layers = {layer: identity_layers[layer] for layer in IDENTITY_LAYER_KEYS}
    base_identity = canonical_candidate_identity(base_layers)
    offload_target = _as_dict(
        identity_layers[OFFLOAD_TARGET_LAYER],
        field_name=OFFLOAD_TARGET_LAYER,
    )
    if not offload_target.get("opportunity_ids"):
        raise ValueError("offload_target_parameters.opportunity_ids must be non-empty")
    if not offload_target.get("bundle_id"):
        raise ValueError("offload_target_parameters.bundle_id is required")
    _validate_workload_variant_binding(
        offload_target.get("workload_variant_binding")
    )

    layers = dict(base_identity["identity_layers"])
    layers[OFFLOAD_TARGET_LAYER] = offload_target
    return {
        "schema_version": OFFLOAD_IDENTITY_SCHEMA,
        "base_identity_schema": base_identity["schema_version"],
        "identity_layer_order": list(OFFLOAD_IDENTITY_LAYER_KEYS),
        "identity_layers": layers,
        "candidate_id_rule": (
            "cdse_offload_ + sha256(schema + ordered base layers + "
            "offload_target_parameters)[:20]; workload/evidence/projection state excluded"
        ),
        "excluded_fields": list(OFFLOAD_NON_IDENTITY_FIELDS),
        "claim_boundary": "offload target identity only; not L4 value evidence",
    }


def complete_dse_offload_candidate_id(identity_layers: Mapping[str, Any]) -> str:
    return "cdse_offload_" + stable_json_hash(
        canonical_offload_candidate_identity(identity_layers)
    )[:20]


def build_offload_candidate_record(
    identity_layers: Mapping[str, Any],
    *,
    evaluation_context: Mapping[str, Any] | None = None,
    generation_source: str = "qe_callgraph_offload_search",
) -> Dict[str, Any]:
    identity = canonical_offload_candidate_identity(identity_layers)
    record = {
        "schema_version": "dse.codesign.qe_offload_candidate_record.v1",
        "candidate_id": complete_dse_offload_candidate_id(identity_layers),
        "identity": identity,
        "identity_hash": stable_json_hash(identity),
        "generation_source": generation_source,
        "evaluation_context": dict(evaluation_context or {}),
        "candidate_id_provenance": {
            "identity_layers": list(OFFLOAD_IDENTITY_LAYER_KEYS),
            "excluded_fields": list(OFFLOAD_NON_IDENTITY_FIELDS),
            "offload_target_affects_identity": True,
            "formal_workload_variant_binding_affects_identity": True,
            "workload_affects_identity": False,
            "evidence_fidelity_affects_identity": False,
            "queue_order_affects_identity": False,
            "blocker_status_affects_identity": False,
            "stable_id_requires_all_identity_layers": True,
        },
        "claim_boundary": "offload candidate identity record only; no value claim",
    }
    record["record_hash"] = _stable_hash_without(record, "record_hash")
    return record


def build_offload_target_identity_schema() -> Dict[str, Any]:
    payload = {
        "schema_version": "dse.codesign.qe_offload_target_identity_schema.v1",
        "status": "draft",
        "release_id": RELEASE_ID,
        "identity_layers": list(OFFLOAD_IDENTITY_LAYER_KEYS),
        "new_identity_layer": OFFLOAD_TARGET_LAYER,
        "required_fields": [
            "granularity",
            "opportunity_ids",
            "bundle_id",
            "patch_strategy",
            "runtime_payload_schema",
            "fallback_policy",
        ],
        "conditional_identity_fields": {
            "workload_variant_binding": {
                "schema_version": WORKLOAD_VARIANT_BINDING_SCHEMA,
                "required_when": (
                    "a non-canonical workload extension such as USPP/PAW s_psi "
                    "is selected as the workload variant to exercise an offload"
                ),
                "required_fields": [
                    "schema_version",
                    "workload_variant_id",
                    "formal_status",
                    "pseudopotential_family",
                    "target_kernel",
                ],
                "candidate_id_effect": "changes offload candidate id",
                "claim_boundary": (
                    "formal workload-variant binding identifies what workload "
                    "is being offloaded; it is not evidence of L4 value"
                ),
            }
        },
        "non_identity_fields": list(OFFLOAD_NON_IDENTITY_FIELDS),
        "workload_case_ids_participate": False,
        "evidence_or_projection_participates": False,
        "formal_workload_variant_binding_affects_identity": True,
        "claim_boundary": "schema only; value requires real L4 evidence",
    }
    payload["schema_hash"] = _stable_hash_without(payload, "schema_hash")
    return payload


def _opportunity_id(case_id: str, kernel: str, stage_type: str) -> str:
    text = f"{case_id}:{stage_type}:{kernel}"
    safe = "".join(ch if ch.isalnum() else "_" for ch in text.lower()).strip("_")
    return "opp_" + safe


def _safe_identifier(text: Any) -> str:
    return "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_"
        for ch in str(text).lower()
    ).strip("_")


def _env_suffix(text: Any) -> str:
    suffix = "".join(
        ch.upper() if ch.isalnum() else "_"
        for ch in str(text)
    ).strip("_")
    return suffix or "TARGET"


def build_qe_callgraph_inventory(
    *,
    source_root: Path | str | None = None,
    workload_suite: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    root = Path(source_root) if source_root is not None else _default_source_root()
    build_root = _default_build_root(root)
    suite = dict(workload_suite or default_qe_mainflow_workload_suite(status="draft"))
    validation = validate_qe_mainflow_workload_suite(suite)
    source_payload = _source_root_payload(root)
    build_payload = _build_root_payload(build_root)
    static_callgraph = _extract_static_callgraph(root)
    nodes: list[Dict[str, Any]] = []
    blockers: list[Dict[str, Any]] = []
    if source_payload["status"] != "available":
        blockers.append(
            {
                "id": "blocked_source_unavailable",
                "source_root": str(root),
                "reason": "QE source tree is unavailable; inventory falls back to workload manifest kernels only",
            }
        )
    if build_payload["status"] != "available":
        blockers.append(
            {
                "id": "blocked_build_unavailable",
                "build_root": str(build_root),
                "reason": "QE build tree is unavailable; real patched-QE L4 attempts must remain blocked until a build is available",
            }
        )
    if not validation.get("valid"):
        blockers.append(
            {
                "id": "blocked_workload_suite_invalid",
                "errors": validation.get("errors", []),
            }
        )

    for case in suite.get("cases", []) or []:
        if not isinstance(case, Mapping):
            continue
        case_id = str(case.get("case_id") or case.get("workload_case_id"))
        stage_type = str(case.get("stage_type", "unknown_stage"))
        programs = _case_workflow_programs(case)
        kernels = list(case.get("kernel_coverage") or [])
        profile_phases = _case_profile_phases(case)
        for kernel in kernels:
            kernel_text = str(kernel)
            source_hits = _find_source_hits(root, kernel_text)
            source_status = "source_probe_hit" if source_hits else "source_probe_missing"
            profile_wall_seconds = profile_phases.get(kernel_text)
            source_file = source_hits[0]["path"] if source_hits else None
            symbol = (
                source_hits[0].get("symbol_or_subroutine")
                if source_hits
                else SOURCE_SYMBOL_HINTS.get(kernel_text, (kernel_text,))[0]
            )
            callsite_id = "callsite_" + stable_json_hash(
                {
                    "case_id": case_id,
                    "stage_type": stage_type,
                    "kernel": kernel_text,
                    "source_file": source_file,
                    "symbol_or_subroutine": symbol,
                }
            )[:16]
            nodes.append(
                {
                    "opportunity_id": _opportunity_id(case_id, kernel_text, stage_type),
                    "callsite_id": callsite_id,
                    "workload_case_id": case_id,
                    "stage_type": stage_type,
                    "phase": stage_type,
                    "programs": programs,
                    "kernel": kernel_text,
                    "source_file": source_file,
                    "symbol_or_subroutine": symbol,
                    "kernel_family": KERNEL_FAMILY_MAP.get(kernel_text, "unknown_or_control"),
                    "granularity": "callsite",
                    "source_probe": {
                        "status": source_status,
                        "source_root": str(root),
                        "hits": source_hits,
                    },
                    "profile_evidence": {
                        "status": (
                            "fixture_profile_observed"
                            if profile_wall_seconds is not None
                            else "not_observed_in_fixture_profile"
                        ),
                        "wall_seconds": profile_wall_seconds,
                        "profile_source": "qe_mainflow_fixture_profile",
                        "claim_boundary": (
                            "profile evidence can prioritize DSE attempts but "
                            "cannot claim valuable_l4"
                        ),
                    },
                    "dependency_edges": [
                        str(stage.get("stage_id"))
                        for stage in case.get("workflow_stages") or []
                        if isinstance(stage, Mapping) and stage.get("stage_id")
                    ],
                    "classification": "offload_opportunity_seed",
                    "candidate_identity_participation": True,
                    "workload_case_id_participates_in_identity": False,
                    "claim_boundary": "callgraph inventory only; not a value claim",
                }
            )

    missing_source_nodes = [
        str(node["opportunity_id"])
        for node in nodes
        if node.get("source_probe", {}).get("status") == "source_probe_missing"
    ]
    if missing_source_nodes and source_payload["status"] == "available":
        blockers.append(
            {
                "id": "blocked_source_probe_missing",
                "count": len(missing_source_nodes),
                "opportunity_ids_sample": missing_source_nodes[:16],
                "reason": "Source tree exists but first-pass probe did not resolve every QE call-site seed",
            }
        )
    blockers.append(
        {
            "id": "blocked_full_static_qe_callgraph_parser_not_yet_complete",
            "reason": (
                "A first-pass static parser now extracts real QE source "
                "definitions and CALL edges when source is available, but it "
                "does not yet resolve interfaces, function references, "
                "preprocessor branches, or dynamic dispatch well enough to "
                "claim semantic whole-QE static callgraph closure."
            ),
            "current_scope": (
                "qe_mainflow_kernel_callgraph_with_source_probe"
                "+first_pass_static_source_callgraph"
            ),
            "static_callgraph_status": static_callgraph.get("status"),
            "static_definition_count": static_callgraph.get("definition_count", 0),
            "static_edge_count": static_callgraph.get("edge_count", 0),
            "required_for_full_qe_callgraph_claim": True,
        }
    )

    mainflow_classes = sorted({str(case.get("stage_type")) for case in suite.get("cases", []) or [] if isinstance(case, Mapping)})
    inventory_status = (
        "passed"
        if nodes and not blockers
        else "partial_or_blocked"
        if nodes
        else "blocked"
    )
    payload = {
        "schema_version": "dse.qe_callgraph_inventory.v1",
        "status": inventory_status,
        "release_id": RELEASE_ID,
        "inventory_scope": "qe_mainflow_kernel_callgraph_with_source_probe",
        "full_static_qe_callgraph_complete": False,
        "full_static_qe_callgraph_status": "blocked_parser_not_yet_complete",
        "first_pass_static_callgraph_extracted": (
            static_callgraph.get("status") == "passed"
        ),
        "static_callgraph": static_callgraph,
        "static_callgraph_hash": static_callgraph.get("callgraph_hash"),
        "static_offload_candidate_count": static_callgraph.get(
            "offload_candidate_count",
            0,
        ),
        "static_offload_candidate_kernel_counts": dict(
            static_callgraph.get("offload_candidate_kernel_counts") or {}
        ),
        "source_root": source_payload,
        "source_root_hash": source_payload.get("hash"),
        "qe_provenance": {
            "source_root": source_payload,
            "build_root": build_payload,
            "source_version": {
                "status": "unknown_first_pass",
                "version_string": None,
                "claim_boundary": "source version is unresolved until real QE source/build introspection is complete",
            },
        },
        "workload_suite_hash": suite.get("suite_hash"),
        "workload_suite_validation": validation,
        "mainflow_classes": mainflow_classes,
        "node_count": len(nodes),
        "nodes": nodes,
        "blockers": blockers,
        "claim_boundary": "inventory/classification only; value requires real L4 evidence",
    }
    payload["inventory_hash"] = _stable_hash_without(payload, "inventory_hash")
    return payload


def build_offload_opportunity_manifest(
    inventory: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    inv = dict(inventory or build_qe_callgraph_inventory())
    opportunities: list[Dict[str, Any]] = []
    for node in inv.get("nodes", []) or []:
        if not isinstance(node, Mapping):
            continue
        kernel = str(node.get("kernel", "unknown"))
        opportunity_id = str(node.get("opportunity_id"))
        source_probe = dict(node.get("source_probe") or {})
        opportunities.append(
            {
                "opportunity_id": opportunity_id,
                "workload_case_id": node.get("workload_case_id"),
                "granularity": node.get("granularity", "kernel"),
                "programs": list(node.get("programs") or []),
                "stage_type": node.get("stage_type"),
                "phase": node.get("phase"),
                "kernel": kernel,
                "callsite_id": node.get("callsite_id"),
                "source_file": node.get("source_file"),
                "symbol_or_subroutine": node.get("symbol_or_subroutine"),
                "kernel_family": node.get("kernel_family"),
                "semantic_role": _semantic_role_for_kernel(kernel),
                "source_provenance": {
                    "inventory_hash": inv.get("inventory_hash"),
                    "source_probe_status": source_probe.get("status"),
                    "source_hits": source_probe.get("hits", []),
                },
                "profile_evidence": dict(node.get("profile_evidence") or {}),
                "workload_selection": _workload_selection_for_kernel(kernel, node),
                "data_shape_expression": _shape_expression_for_kernel(kernel),
                "correctness_oracle_requirements": _oracle_requirements_for_kernel(kernel),
                "patch_feasibility": _patch_feasibility_for_kernel(kernel, source_probe),
                "runtime_payload_requirements": _runtime_payload_requirements_for_kernel(kernel),
                "classification": "queued_by_projection",
                "value_label": "queued_by_projection",
                "claim_boundary": "opportunity only; no value without real L4 evidence",
            }
        )
        opportunities[-1]["selection_priority"] = _selection_priority_for_opportunity(
            opportunities[-1]
        )
    payload = {
        "schema_version": "dse.qe_offload_opportunity_manifest.v1",
        "status": "passed" if opportunities else "blocked",
        "release_id": RELEASE_ID,
        "inventory_hash": inv.get("inventory_hash"),
        "opportunity_count": len(opportunities),
        "opportunities": opportunities,
        "all_opportunities_classified": all(row.get("classification") for row in opportunities),
        "claim_boundary": "manifest can queue work but cannot claim valuable_l4",
    }
    payload["manifest_hash"] = _stable_hash_without(payload, "manifest_hash")
    return payload


def _spsi_uspp_workload_extension_candidate() -> Dict[str, Any]:
    return {
        "variant_id": SPSI_USPP_WORKLOAD_VARIANT_ID,
        "variant_status": "formal_workload_variant_candidate",
        "formalization_status": (
            "formalized_as_workload_variant_search_space_object"
        ),
        "pseudo_family": "uspp",
        "pseudo_substitution": {
            "input_symbol": "Si.pz-vbc.UPF",
            "observed_probe_source": (
                "runs/dse/_tools/qe_local/usr/share/espresso/pseudo/"
                "Si.pbe-nl-rrkjus_psl.1.0.0.UPF"
            ),
            "probe_pseudo_dir": "runs/dse/_tools/qe_spsi_uspp_pseudo",
        },
        "evidence_artifacts": [
            "runs/dse/qe_callgraph_offload_l4_smoke_spsi_uspp_probe/"
            "l4_offload_attempt_evidence.json",
            "runs/dse/qe_callgraph_offload_l4_smoke_nscf_spsi_uspp_probe/"
            "l4_offload_attempt_evidence.json",
            "runs/dse/qe_callgraph_offload_l4_multi_probe_uspp_spsi_extension/"
            "workload_extension_note.json",
        ],
        "offload_target_binding": {
            "schema_version": WORKLOAD_VARIANT_BINDING_SCHEMA,
            "workload_variant_id": SPSI_USPP_WORKLOAD_VARIANT_ID,
            "formal_status": "formal_workload_variant_candidate",
            "pseudopotential_family": "uspp",
            "target_kernel": "s_psi",
        },
        "promotion_policy": (
            "formal workload-variant search object exists, but it cannot "
            "replace frozen first-pass canonical rows unless the report binds "
            "offload_target_parameters.workload_variant_binding and preserves "
            "canonical/research-extension boundaries"
        ),
    }


def _spsi_nc_cg_workload_extension_candidate() -> Dict[str, Any]:
    return {
        "variant_id": SPSI_NC_CG_WORKLOAD_VARIANT_ID,
        "variant_status": "formal_workload_variant_candidate",
        "formalization_status": (
            "formalized_as_workload_variant_search_space_object"
        ),
        "pseudo_family": "norm_conserving",
        "solver_policy": {
            "electrons_diagonalization": "cg",
            "reason": (
                "CG diagonalization exercises the QE s_1psi/s_psi path for "
                "the frozen norm-conserving Si input, making the s_psi "
                "offload target observable without switching to USPP/PAW "
                "semantics."
            ),
        },
        "replacement_semantics": {
            "target_kernel": "s_psi",
            "identity_overlap_required": True,
            "safe_writeback_condition": "nkb == 0 .OR. .NOT. okvan",
            "accelerated_writeback_policy": (
                "GenericAccel L4 completion gates an in-process writeback that "
                "uses the already-written identity-overlap spsi=psi result; "
                "USPP/PAW/non-identity overlap remains blocked."
            ),
        },
        "input_overrides": {
            "namelist": "ELECTRONS",
            "assignments": {"diagonalization": "'cg'"},
        },
        "evidence_artifacts": [
            "runs/dse/qe_callgraph_offload_l4_smoke_spsi_nc_cg_identity_probe/"
            "l4_offload_attempt_evidence.json",
        ],
        "offload_target_binding": {
            "schema_version": WORKLOAD_VARIANT_BINDING_SCHEMA,
            "workload_variant_id": SPSI_NC_CG_WORKLOAD_VARIANT_ID,
            "formal_status": "formal_workload_variant_candidate",
            "pseudopotential_family": "norm_conserving",
            "target_kernel": "s_psi",
            "solver_policy": "cg",
        },
        "promotion_policy": (
            "This variant may be selected by DSE as a real workload-variant "
            "probe for s_psi replacement readiness, but it must remain "
            "explicitly bound in offload_target_parameters and cannot replace "
            "canonical frozen-workload rows silently."
        ),
    }


def _spsi_nc_cg_larger_workload_extension_candidate() -> Dict[str, Any]:
    return {
        "variant_id": SPSI_NC_CG_LARGER_WORKLOAD_VARIANT_ID,
        "variant_status": "formal_workload_variant_candidate",
        "formalization_status": (
            "formalized_as_workload_variant_search_space_object"
        ),
        "pseudo_family": "norm_conserving",
        "solver_policy": {
            "electrons_diagonalization": "cg",
            "reason": (
                "Uses the same NC+CG identity-overlap s_psi semantics as the "
                "canonical probe, but scales the nscf/band-grid workload so "
                "DSE can search whether larger real QE work amortizes the "
                "gem5 GenericAccel bridge overhead."
            ),
        },
        "workload_scale_policy": {
            "target_workload_case_id": "qe_si_nscf_bandgrid_v1",
            "system_overrides": {"ecutwfc": "20.0", "nbnd": "24"},
            "nscf_k_points_automatic": "6 6 6 0 0 0",
            "scale_rationale": (
                "increase band-grid/diagonalization work without changing "
                "candidate identity; workload variant must be explicit in "
                "offload_target_parameters"
            ),
        },
        "replacement_semantics": {
            "target_kernel": "s_psi",
            "identity_overlap_required": True,
            "safe_writeback_condition": "nkb == 0 .OR. .NOT. okvan",
            "accelerated_writeback_policy": (
                "Same GenericAccel-gated identity-overlap writeback as the "
                "NC+CG s_psi probe; the scaled workload is only a DSE search "
                "variant and cannot relax value gates."
            ),
        },
        "input_overrides": {
            "namelist": ["SYSTEM", "ELECTRONS"],
            "assignments": {
                "SYSTEM.ecutwfc": "20.0",
                "SYSTEM.nbnd": "24",
                "ELECTRONS.diagonalization": "'cg'",
                "stage_01_nscf.K_POINTS automatic": "6 6 6 0 0 0",
            },
        },
        "evidence_artifacts": [],
        "offload_target_binding": {
            "schema_version": WORKLOAD_VARIANT_BINDING_SCHEMA,
            "workload_variant_id": SPSI_NC_CG_LARGER_WORKLOAD_VARIANT_ID,
            "formal_status": "formal_workload_variant_candidate",
            "pseudopotential_family": "norm_conserving",
            "target_kernel": "s_psi",
            "solver_policy": "cg",
            "workload_scale_policy": "larger_bandgrid",
        },
        "promotion_policy": (
            "This is a workload-variant search candidate for speed/value "
            "discovery only.  It does not replace canonical frozen rows and "
            "cannot claim valuable_l4 without real QE + gem5 L4 correctness, "
            "replacement consumption, and positive speed."
        ),
    }


def _spsi_nc_cg_amortized_workload_extension_candidate() -> Dict[str, Any]:
    return {
        "variant_id": SPSI_NC_CG_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
        "variant_status": "formal_workload_variant_candidate",
        "formalization_status": (
            "formalized_as_workload_variant_search_space_object"
        ),
        "pseudo_family": "norm_conserving",
        "solver_policy": {
            "electrons_diagonalization": "cg",
            "reason": (
                "Extends the NC+CG identity-overlap s_psi probe to the same "
                "8x8x8/48-band nscf scale used by non-s_psi amortization "
                "probes, so DSE can test whether larger real QE work changes "
                "the L4 value decision without treating projection as value."
            ),
        },
        "workload_scale_policy": {
            "target_workload_case_id": "qe_si_nscf_bandgrid_v1",
            "system_overrides": {"ecutwfc": "20.0", "nbnd": "48"},
            "nscf_k_points_automatic": "8 8 8 0 0 0",
            "scale_rationale": (
                "increase real s_psi/c_bands work under the same explicit "
                "offload target identity to test bridge amortization with a "
                "non-smoke QE/gem5 actual-compute run"
            ),
        },
        "replacement_semantics": {
            "target_kernel": "s_psi",
            "identity_overlap_required": True,
            "safe_writeback_condition": "nkb == 0 .OR. .NOT. okvan",
            "accelerated_writeback_policy": (
                "Same GenericAccel-gated identity-overlap writeback as the "
                "NC+CG s_psi probe; the larger workload is a DSE search "
                "variant and cannot relax the strict valuable_l4 gates."
            ),
        },
        "input_overrides": {
            "namelist": ["SYSTEM", "ELECTRONS"],
            "assignments": {
                "SYSTEM.ecutwfc": "20.0",
                "SYSTEM.nbnd": "48",
                "ELECTRONS.diagonalization": "'cg'",
                "stage_01_nscf.K_POINTS automatic": "8 8 8 0 0 0",
            },
        },
        "evidence_artifacts": [],
        "offload_target_binding": {
            "schema_version": WORKLOAD_VARIANT_BINDING_SCHEMA,
            "workload_variant_id": SPSI_NC_CG_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
            "formal_status": "formal_workload_variant_candidate",
            "pseudopotential_family": "norm_conserving",
            "target_kernel": "s_psi",
            "solver_policy": "cg",
            "workload_scale_policy": "amortized_bandgrid",
        },
        "promotion_policy": (
            "This is a workload-variant search candidate for s_psi speed/value "
            "discovery only. It does not replace canonical frozen rows and "
            "cannot claim valuable_l4 without real QE + gem5 L4 correctness, "
            "replacement consumption, and positive speed."
        ),
    }


def _nscf_amortized_bandgrid_workload_extension_candidate() -> Dict[str, Any]:
    return {
        "variant_id": NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
        "variant_status": "formal_workload_variant_candidate",
        "formalization_status": (
            "formalized_as_workload_variant_search_space_object"
        ),
        "pseudo_family": "norm_conserving",
        "workload_scale_policy": {
            "target_workload_case_id": "qe_si_nscf_bandgrid_v1",
            "target_kernels": ["diagonalization", "fft", "subspace_rotation"],
            "system_overrides": {"ecutwfc": "20.0", "nbnd": "48"},
            "nscf_k_points_automatic": "8 8 8 0 0 0",
            "scale_rationale": (
                "increase real nscf band-grid and band-count work so DSE can "
                "test whether non-s_psi offload candidates amortize gem5 "
                "GenericAccel bridge overhead without changing the value gate"
            ),
        },
        "input_overrides": {
            "namelist": "SYSTEM",
            "assignments": {
                "SYSTEM.ecutwfc": "20.0",
                "SYSTEM.nbnd": "48",
                "stage_01_nscf.K_POINTS automatic": "8 8 8 0 0 0",
            },
        },
        "evidence_artifacts": [],
        "offload_target_binding": {
            "schema_version": WORKLOAD_VARIANT_BINDING_SCHEMA,
            "workload_variant_id": NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
            "formal_status": "formal_workload_variant_candidate",
            "pseudopotential_family": "norm_conserving",
            "target_workload_case_id": "qe_si_nscf_bandgrid_v1",
            "target_kernels": ["diagonalization", "fft", "subspace_rotation"],
            "workload_scale_policy": "amortized_bandgrid",
        },
        "promotion_policy": (
            "This is a larger-workload DSE search candidate for non-s_psi "
            "nscf kernels.  It cannot replace canonical rows or claim value "
            "unless a real non-smoke QE/gem5 L4 attempt passes correctness, "
            "replacement consumption, pure baseline, and positive speed."
        ),
    }


def _nscf_heavy_bandgrid_workload_extension_candidate() -> Dict[str, Any]:
    return {
        "variant_id": NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID,
        "variant_status": "formal_workload_variant_candidate",
        "formalization_status": (
            "formalized_as_workload_variant_search_space_object"
        ),
        "pseudo_family": "norm_conserving",
        "workload_scale_policy": {
            "target_workload_case_id": "qe_si_nscf_bandgrid_v1",
            "target_kernels": ["diagonalization", "fft", "subspace_rotation"],
            "system_overrides": {"ecutwfc": "20.0", "nbnd": "64"},
            "nscf_k_points_automatic": "10 10 10 0 0 0",
            "scale_rationale": (
                "extend the real nscf band-grid and band-count search beyond "
                "the 8x8x8/48-band amortization probe so DSE can test whether "
                "heavier full-QE work changes the L4 speed/value decision "
                "without treating projection or smoke as value"
            ),
        },
        "input_overrides": {
            "namelist": "SYSTEM",
            "assignments": {
                "SYSTEM.ecutwfc": "20.0",
                "SYSTEM.nbnd": "64",
                "stage_01_nscf.K_POINTS automatic": "10 10 10 0 0 0",
            },
        },
        "evidence_artifacts": [],
        "offload_target_binding": {
            "schema_version": WORKLOAD_VARIANT_BINDING_SCHEMA,
            "workload_variant_id": NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID,
            "formal_status": "formal_workload_variant_candidate",
            "pseudopotential_family": "norm_conserving",
            "target_workload_case_id": "qe_si_nscf_bandgrid_v1",
            "target_kernels": ["diagonalization", "fft", "subspace_rotation"],
            "workload_scale_policy": "heavy_bandgrid",
        },
        "promotion_policy": (
            "This is a heavier-workload DSE search candidate for non-s_psi "
            "nscf kernels. It must be explicitly bound in offload target "
            "identity and cannot claim valuable_l4 without non-smoke QE + "
            "gem5 L4 correctness, replacement consumption, pure baseline, "
            "and positive speed."
        ),
    }


def _nscf_ultra_bandgrid_workload_extension_candidate() -> Dict[str, Any]:
    return {
        "variant_id": NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID,
        "variant_status": "formal_workload_variant_candidate",
        "formalization_status": (
            "formalized_as_workload_variant_search_space_object"
        ),
        "pseudo_family": "norm_conserving",
        "workload_scale_policy": {
            "target_workload_case_id": "qe_si_nscf_bandgrid_v1",
            "target_kernels": ["diagonalization", "fft", "subspace_rotation"],
            "system_overrides": {"ecutwfc": "20.0", "nbnd": "96"},
            "nscf_k_points_automatic": "12 12 12 0 0 0",
            "scale_rationale": (
                "extend DSE workload search beyond the 10x10x10/64-band "
                "heavy probe to test whether a larger real full-QE nscf "
                "band-grid can amortize L4 dispatch overhead without "
                "treating projection or smoke as value"
            ),
        },
        "input_overrides": {
            "namelist": "SYSTEM",
            "assignments": {
                "SYSTEM.ecutwfc": "20.0",
                "SYSTEM.nbnd": "96",
                "stage_01_nscf.K_POINTS automatic": "12 12 12 0 0 0",
            },
        },
        "evidence_artifacts": [],
        "offload_target_binding": {
            "schema_version": WORKLOAD_VARIANT_BINDING_SCHEMA,
            "workload_variant_id": NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID,
            "formal_status": "formal_workload_variant_candidate",
            "pseudopotential_family": "norm_conserving",
            "target_workload_case_id": "qe_si_nscf_bandgrid_v1",
            "target_kernels": ["diagonalization", "fft", "subspace_rotation"],
            "workload_scale_policy": "ultra_bandgrid",
        },
        "promotion_policy": (
            "This is a larger real-QE workload-scale candidate for checking "
            "whether replacement-ready nscf FFT/subspace offloads amortize "
            "gem5 GenericAccel overhead. It must be explicitly bound in "
            "offload target identity and cannot claim valuable_l4 without "
            "non-smoke QE + gem5 L4 correctness, replacement consumption, "
            "pure baseline, and positive speed."
        ),
    }


def _nscf_stress_bandgrid_workload_extension_candidate() -> Dict[str, Any]:
    return {
        "variant_id": NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID,
        "variant_status": "formal_workload_variant_candidate",
        "formalization_status": (
            "formalized_as_workload_variant_search_space_object"
        ),
        "pseudo_family": "norm_conserving",
        "workload_scale_policy": {
            "target_workload_case_id": "qe_si_nscf_bandgrid_v1",
            "target_kernels": ["diagonalization", "fft", "subspace_rotation"],
            "system_overrides": {"ecutwfc": "20.0", "nbnd": "128"},
            "nscf_k_points_automatic": "14 14 14 0 0 0",
            "scale_rationale": (
                "stress DSE workload selection after ultra probes showed mixed "
                "FFT value; this keeps a real full-QE workload while increasing "
                "nscf FFT/subspace work to test whether strict replacement can "
                "amortize bridge overhead"
            ),
        },
        "input_overrides": {
            "namelist": "SYSTEM",
            "assignments": {
                "SYSTEM.ecutwfc": "20.0",
                "SYSTEM.nbnd": "128",
                "stage_01_nscf.K_POINTS automatic": "14 14 14 0 0 0",
            },
        },
        "evidence_artifacts": [],
        "offload_target_binding": {
            "schema_version": WORKLOAD_VARIANT_BINDING_SCHEMA,
            "workload_variant_id": NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID,
            "formal_status": "formal_workload_variant_candidate",
            "pseudopotential_family": "norm_conserving",
            "target_workload_case_id": "qe_si_nscf_bandgrid_v1",
            "target_kernels": ["diagonalization", "fft", "subspace_rotation"],
            "workload_scale_policy": "stress_bandgrid",
        },
        "promotion_policy": (
            "This is a stress real-QE workload-scale candidate for checking "
            "whether replacement-ready nscf FFT/subspace offloads amortize "
            "gem5 GenericAccel overhead. It must be explicitly bound in "
            "offload target identity and cannot claim valuable_l4 without "
            "non-smoke QE + gem5 L4 correctness, replacement consumption, "
            "pure baseline, and positive speed."
        ),
    }


def _workload_selection_for_kernel(
    kernel: str,
    node: Mapping[str, Any],
) -> Dict[str, Any]:
    profile = dict(node.get("profile_evidence") or {})
    profile_status = str(profile.get("status") or "unknown")
    profile_observed = profile_status == "fixture_profile_observed"
    extension_candidates: list[Dict[str, Any]] = []
    exercise_requirements = [
        "real_qe_trace_observation_required_before_l4_value_claim",
    ]
    if kernel == "s_psi":
        exercise_requirements.append(
            "ultrasoft_or_paw_pseudopotential_or_nontrivial_overlap_operator"
        )
        exercise_requirements.append(
            "norm_conserving_cg_solver_variant_for_identity_overlap_spsi"
        )
        extension_candidates.append(_spsi_uspp_workload_extension_candidate())
        extension_candidates.append(_spsi_nc_cg_workload_extension_candidate())
        extension_candidates.append(
            _spsi_nc_cg_larger_workload_extension_candidate()
        )
    return {
        "schema_version": "dse.qe_workload_offload_selection.v1",
        "workload_case_id": node.get("workload_case_id"),
        "stage_type": node.get("stage_type"),
        "phase": node.get("phase"),
        "programs": list(node.get("programs") or []),
        "selection_axes": list(WORKLOAD_SELECTION_AXES),
        "canonical_first_pass_profile_status": profile_status,
        "kernel_exercise_status": (
            "observed_in_fixture_profile"
            if profile_observed
            else "requires_real_trace_or_workload_extension"
        ),
        "exercise_requirements": exercise_requirements,
        "extension_candidates": extension_candidates,
        "workload_identity_boundary": (
            "workload features guide what to attempt and explain blockers; "
            "workload_case_id remains outside generic candidate identity; "
            "formal workload variants bind through "
            "offload_target_parameters.workload_variant_binding when they "
            "change the offload target being evaluated"
        ),
        "claim_boundary": (
            "workload/offload selection metadata only; not value evidence"
        ),
    }


def build_workload_variant_search_space(
    opportunity_manifest: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return formal workload variants that DSE may bind to offload choices.

    Workload variants live in this QE reference branch, not in the generic
    complete-DSE core.  Frozen workload cases remain non-identity evaluation
    context, while non-canonical variants such as USPP/PAW s_psi probes must be
    explicitly bound into ``offload_target_parameters`` before they can replace
    a frozen-row blocker or attempt.
    """
    manifest = dict(opportunity_manifest or build_offload_opportunity_manifest())
    rows = [
        row
        for row in manifest.get("opportunities", []) or []
        if isinstance(row, Mapping)
    ]
    opportunities_by_case: Dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        case_id = str(row.get("workload_case_id"))
        opportunities_by_case.setdefault(case_id, []).append(row)

    variants: list[Dict[str, Any]] = []
    for case_id, case_rows in sorted(opportunities_by_case.items()):
        stage_types = sorted({str(row.get("stage_type")) for row in case_rows})
        programs = sorted(
            {
                str(program)
                for row in case_rows
                for program in (row.get("programs") or [])
            }
        )
        opportunity_ids = sorted(str(row.get("opportunity_id")) for row in case_rows)
        variant = {
            "variant_id": "wv_frozen_" + stable_json_hash(case_id)[:12],
            "variant_kind": "canonical_frozen_first_pass_workload",
            "variant_status": "canonical_frozen_first_pass_variant",
            "formalization_status": "formalized_as_workload_variant_search_space_object",
            "workload_case_reference": case_id,
            "stage_types": stage_types,
            "programs": programs,
            "pseudopotential_family": "frozen_first_pass_default",
            "applies_to_opportunity_ids": opportunity_ids,
            "selection_axes": list(WORKLOAD_SELECTION_AXES),
            "offload_target_binding_required_for_candidate_identity": False,
            "canonical_matrix_role": "canonical_first_pass_row_source",
            "canonical_replacement_allowed": True,
            "identity_boundary": {
                "participates_in_generic_candidate_identity": False,
                "participates_in_offload_target_identity_when_bound": False,
                "reason": (
                    "frozen workload cases are evaluation context; offload "
                    "target identity changes only when a non-canonical formal "
                    "variant is selected"
                ),
            },
            "claim_boundary": "canonical workload variant only; not L4 value evidence",
        }
        variant["variant_hash"] = _stable_hash_without(variant, "variant_hash")
        variants.append(variant)

    spsi_rows = [row for row in rows if row.get("kernel") == "s_psi"]
    if spsi_rows:
        spsi_opportunity_ids = sorted(
            str(row.get("opportunity_id")) for row in spsi_rows
        )
        nc_cg_extension = _spsi_nc_cg_workload_extension_candidate()
        nc_cg_variant = {
            "variant_id": nc_cg_extension["variant_id"],
            "variant_kind": "solver_policy_extension",
            "variant_status": nc_cg_extension["variant_status"],
            "formalization_status": nc_cg_extension["formalization_status"],
            "pseudopotential_family": nc_cg_extension["pseudo_family"],
            "applies_to_kernel": "s_psi",
            "applies_to_opportunity_ids": spsi_opportunity_ids,
            "selection_axes": list(WORKLOAD_SELECTION_AXES),
            "exercise_requirements": [
                "norm_conserving_cg_solver_variant_for_identity_overlap_spsi",
                "real_qe_trace_observation_required_before_l4_value_claim",
                "real_l4_correctness_and_positive_speed_required_for_value",
            ],
            "solver_policy": nc_cg_extension["solver_policy"],
            "replacement_semantics": nc_cg_extension["replacement_semantics"],
            "input_overrides": nc_cg_extension["input_overrides"],
            "evidence_artifacts": nc_cg_extension["evidence_artifacts"],
            "offload_target_binding": nc_cg_extension["offload_target_binding"],
            "offload_target_binding_required_for_candidate_identity": True,
            "canonical_matrix_role": (
                "non_canonical_extension_probe; does_not_replace_frozen_rows"
            ),
            "canonical_replacement_allowed": False,
            "canonical_replacement_policy": (
                "A report may compare this variant beside frozen rows, but it "
                "must not silently replace canonical blocked s_psi rows.  The "
                "selected workload_variant_id, pseudopotential_family, and "
                "solver_policy must be visible in the offload target identity "
                "and value report."
            ),
            "identity_boundary": {
                "participates_in_generic_candidate_identity": False,
                "participates_in_offload_target_identity_when_bound": True,
                "binding_field": (
                    "offload_target_parameters.workload_variant_binding"
                ),
                "generic_core_contamination_allowed": False,
            },
            "claim_boundary": (
                "formal workload variant search object only; NC+CG s_psi "
                "identity-overlap probe evidence remains separate and cannot "
                "claim deliverable_complete or valuable_l4 without real L4 "
                "correctness and positive speed"
            ),
        }
        nc_cg_variant["variant_hash"] = _stable_hash_without(
            nc_cg_variant, "variant_hash"
        )
        variants.append(nc_cg_variant)

        larger_extension = _spsi_nc_cg_larger_workload_extension_candidate()
        larger_variant = {
            "variant_id": larger_extension["variant_id"],
            "variant_kind": "workload_scale_extension",
            "variant_status": larger_extension["variant_status"],
            "formalization_status": larger_extension["formalization_status"],
            "pseudopotential_family": larger_extension["pseudo_family"],
            "applies_to_kernel": "s_psi",
            "applies_to_opportunity_ids": spsi_opportunity_ids,
            "selection_axes": list(WORKLOAD_SELECTION_AXES),
            "exercise_requirements": [
                "larger_real_qe_workload_to_test_bridge_amortization",
                "norm_conserving_cg_solver_variant_for_identity_overlap_spsi",
                "real_qe_trace_observation_required_before_l4_value_claim",
                "real_l4_correctness_and_positive_speed_required_for_value",
            ],
            "solver_policy": larger_extension["solver_policy"],
            "workload_scale_policy": larger_extension["workload_scale_policy"],
            "replacement_semantics": larger_extension["replacement_semantics"],
            "input_overrides": larger_extension["input_overrides"],
            "evidence_artifacts": larger_extension["evidence_artifacts"],
            "offload_target_binding": larger_extension["offload_target_binding"],
            "offload_target_binding_required_for_candidate_identity": True,
            "canonical_matrix_role": (
                "non_canonical_workload_scale_probe; "
                "does_not_replace_frozen_rows"
            ),
            "canonical_replacement_allowed": False,
            "canonical_replacement_policy": (
                "The report may compare this scaled workload variant beside "
                "frozen rows, but must keep workload_variant_id and scale "
                "policy visible in selection/value artifacts."
            ),
            "identity_boundary": {
                "participates_in_generic_candidate_identity": False,
                "participates_in_offload_target_identity_when_bound": True,
                "binding_field": (
                    "offload_target_parameters.workload_variant_binding"
                ),
                "generic_core_contamination_allowed": False,
            },
            "claim_boundary": (
                "formal workload-scale search object only; value gates remain "
                "unchanged and first-pass deliverable_complete stays false"
            ),
        }
        larger_variant["variant_hash"] = _stable_hash_without(
            larger_variant, "variant_hash"
        )
        variants.append(larger_variant)

        amortized_spsi_extension = (
            _spsi_nc_cg_amortized_workload_extension_candidate()
        )
        amortized_spsi_variant = {
            "variant_id": amortized_spsi_extension["variant_id"],
            "variant_kind": "workload_scale_extension",
            "variant_status": amortized_spsi_extension["variant_status"],
            "formalization_status": amortized_spsi_extension[
                "formalization_status"
            ],
            "pseudopotential_family": amortized_spsi_extension["pseudo_family"],
            "applies_to_kernel": "s_psi",
            "applies_to_opportunity_ids": spsi_opportunity_ids,
            "selection_axes": list(WORKLOAD_SELECTION_AXES),
            "exercise_requirements": [
                "amortized_real_qe_workload_to_test_bridge_overhead",
                "norm_conserving_cg_solver_variant_for_identity_overlap_spsi",
                "real_qe_trace_observation_required_before_l4_value_claim",
                "real_l4_correctness_and_positive_speed_required_for_value",
            ],
            "solver_policy": amortized_spsi_extension["solver_policy"],
            "workload_scale_policy": amortized_spsi_extension[
                "workload_scale_policy"
            ],
            "replacement_semantics": amortized_spsi_extension[
                "replacement_semantics"
            ],
            "input_overrides": amortized_spsi_extension["input_overrides"],
            "evidence_artifacts": amortized_spsi_extension["evidence_artifacts"],
            "offload_target_binding": amortized_spsi_extension[
                "offload_target_binding"
            ],
            "offload_target_binding_required_for_candidate_identity": True,
            "canonical_matrix_role": (
                "non_canonical_workload_scale_probe; "
                "does_not_replace_frozen_rows"
            ),
            "canonical_replacement_allowed": False,
            "canonical_replacement_policy": (
                "The report may compare this scaled s_psi workload variant "
                "beside frozen rows, but must keep workload_variant_id and "
                "scale policy visible in selection/value artifacts."
            ),
            "identity_boundary": {
                "participates_in_generic_candidate_identity": False,
                "participates_in_offload_target_identity_when_bound": True,
                "binding_field": (
                    "offload_target_parameters.workload_variant_binding"
                ),
                "generic_core_contamination_allowed": False,
            },
            "claim_boundary": (
                "formal workload-scale search object only; value gates remain "
                "unchanged, smoke is dataflow-only, and first-pass "
                "deliverable_complete stays false"
            ),
        }
        amortized_spsi_variant["variant_hash"] = _stable_hash_without(
            amortized_spsi_variant, "variant_hash"
        )
        variants.append(amortized_spsi_variant)

        uspp_extension = _spsi_uspp_workload_extension_candidate()
        uspp_variant = {
            "variant_id": uspp_extension["variant_id"],
            "variant_kind": "pseudopotential_family_extension",
            "variant_status": uspp_extension["variant_status"],
            "formalization_status": uspp_extension["formalization_status"],
            "pseudopotential_family": uspp_extension["pseudo_family"],
            "applies_to_kernel": "s_psi",
            "applies_to_opportunity_ids": spsi_opportunity_ids,
            "selection_axes": list(WORKLOAD_SELECTION_AXES),
            "exercise_requirements": [
                "ultrasoft_or_paw_pseudopotential_or_nontrivial_overlap_operator",
                "real_qe_trace_observation_required_before_l4_value_claim",
                "real_l4_correctness_and_positive_speed_required_for_value",
            ],
            "pseudo_substitution": uspp_extension["pseudo_substitution"],
            "evidence_artifacts": uspp_extension["evidence_artifacts"],
            "offload_target_binding": uspp_extension["offload_target_binding"],
            "offload_target_binding_required_for_candidate_identity": True,
            "canonical_matrix_role": (
                "non_canonical_extension_probe; does_not_replace_frozen_rows"
            ),
            "canonical_replacement_allowed": False,
            "canonical_replacement_policy": (
                "A report may compare this variant beside frozen rows, but it "
                "must not silently replace canonical blocked s_psi rows.  The "
                "selected workload_variant_id and pseudopotential_family must "
                "be visible in the offload target identity and value report."
            ),
            "identity_boundary": {
                "participates_in_generic_candidate_identity": False,
                "participates_in_offload_target_identity_when_bound": True,
                "binding_field": (
                    "offload_target_parameters.workload_variant_binding"
                ),
                "generic_core_contamination_allowed": False,
            },
            "claim_boundary": (
                "formal workload variant search object only; USPP trace/L4 "
                "probe evidence remains separate and cannot claim "
                "deliverable_complete"
            ),
        }
        uspp_variant["variant_hash"] = _stable_hash_without(
            uspp_variant, "variant_hash"
        )
        variants.append(uspp_variant)

    nscf_scale_rows = [
        row
        for row in rows
        if row.get("workload_case_id") == "qe_si_nscf_bandgrid_v1"
        and row.get("kernel") in {"diagonalization", "fft", "subspace_rotation"}
    ]
    if nscf_scale_rows:
        for nscf_scale_extension in (
            _nscf_amortized_bandgrid_workload_extension_candidate(),
            _nscf_heavy_bandgrid_workload_extension_candidate(),
            _nscf_ultra_bandgrid_workload_extension_candidate(),
            _nscf_stress_bandgrid_workload_extension_candidate(),
        ):
            nscf_scale_variant = {
                "variant_id": nscf_scale_extension["variant_id"],
                "variant_kind": "workload_scale_extension",
                "variant_status": nscf_scale_extension["variant_status"],
                "formalization_status": nscf_scale_extension["formalization_status"],
                "pseudopotential_family": nscf_scale_extension["pseudo_family"],
                "applies_to_workload_case_id": "qe_si_nscf_bandgrid_v1",
                "applies_to_kernels": ["diagonalization", "fft", "subspace_rotation"],
                "applies_to_opportunity_ids": sorted(
                    str(row.get("opportunity_id")) for row in nscf_scale_rows
                ),
                "selection_axes": list(WORKLOAD_SELECTION_AXES),
                "exercise_requirements": [
                    "larger_real_qe_workload_to_test_bridge_amortization",
                    "real_qe_trace_observation_required_before_l4_value_claim",
                    "real_l4_correctness_and_positive_speed_required_for_value",
                ],
                "workload_scale_policy": nscf_scale_extension["workload_scale_policy"],
                "input_overrides": nscf_scale_extension["input_overrides"],
                "evidence_artifacts": nscf_scale_extension["evidence_artifacts"],
                "offload_target_binding": nscf_scale_extension[
                    "offload_target_binding"
                ],
                "offload_target_binding_required_for_candidate_identity": True,
                "canonical_matrix_role": (
                    "non_canonical_workload_scale_probe; "
                    "does_not_replace_frozen_rows"
                ),
                "canonical_replacement_allowed": False,
                "canonical_replacement_policy": (
                    "The report may compare this scaled workload variant beside "
                    "frozen nscf rows, but must keep workload_variant_id and scale "
                    "policy visible in selection/value artifacts."
                ),
                "identity_boundary": {
                    "participates_in_generic_candidate_identity": False,
                    "participates_in_offload_target_identity_when_bound": True,
                    "binding_field": (
                        "offload_target_parameters.workload_variant_binding"
                    ),
                    "generic_core_contamination_allowed": False,
                },
                "claim_boundary": (
                    "formal workload-scale search object only; value gates remain "
                    "unchanged, smoke is dataflow-only, and first-pass "
                    "deliverable_complete stays false"
                ),
            }
            nscf_scale_variant["variant_hash"] = _stable_hash_without(
                nscf_scale_variant, "variant_hash"
            )
            variants.append(nscf_scale_variant)

    payload = {
        "schema_version": WORKLOAD_VARIANT_SEARCH_SCHEMA,
        "status": "passed" if variants else "blocked",
        "release_id": RELEASE_ID,
        "manifest_hash": manifest.get("manifest_hash"),
        "selection_axes": list(WORKLOAD_SELECTION_AXES),
        "variant_count": len(variants),
        "canonical_variant_count": sum(
            1
            for variant in variants
            if variant.get("variant_status")
            == "canonical_frozen_first_pass_variant"
        ),
        "formal_workload_variant_count": sum(
            1
            for variant in variants
            if variant.get("variant_status")
            == "formal_workload_variant_candidate"
        ),
        "research_only_variant_count": sum(
            1
            for variant in variants
            if str(variant.get("variant_status")).startswith("research_only")
        ),
        "canonical_replacement_requires_explicit_binding": True,
        "workload_case_ids_participate_in_generic_identity": False,
        "formal_variant_binding_affects_offload_identity": True,
        "variants": variants,
        "claim_boundary": (
            "workload-variant search space tells DSE which workload variant to "
            "exercise; value still requires real QE + gem5 L4 correctness and "
            "positive speed"
        ),
    }
    payload["search_space_hash"] = _stable_hash_without(
        payload, "search_space_hash"
    )
    return payload


def _semantic_role_for_kernel(kernel: str) -> str:
    return {
        "h_psi": "Hamiltonian application / dense stencil-linear algebra",
        "s_psi": "overlap application / dense linear algebra",
        "diagonalization": "eigensolver/subspace solve",
        "subspace_rotation": "subspace basis transform",
        "rho_out": "charge density accumulation",
        "mix_rho": "density residual mixing",
        "veff": "effective potential update",
        "fft": "grid transform / producer-consumer stream",
        "forces": "force accumulation",
        "stress": "stress accumulation",
        "band_path_projection": "post-processing band projection",
    }.get(kernel, "unknown/control or unclassified QE callgraph node")


def _shape_expression_for_kernel(kernel: str) -> str:
    return {
        "h_psi": "complex_fp64[nbnd][npw] -> complex_fp64[nbnd][npw]",
        "s_psi": "complex_fp64[nbnd][npw] -> complex_fp64[nbnd][npw]",
        "diagonalization": "dense_matrix[nstate][nstate] eigensolve",
        "subspace_rotation": "complex matrix/vector rotation over bands",
        "rho_out": "grid_accumulate[fft_grid]",
        "mix_rho": "vector_reduce[fft_grid]",
        "veff": "grid_update[fft_grid]",
        "fft": "complex_grid[fft_dims] transform",
        "forces": "atom_force[nat][3] accumulation",
        "stress": "stress_tensor[3][3] accumulation",
        "band_path_projection": "eigenvalue_path[nk][nbnd] projection",
    }.get(kernel, "blocked_shape_expression_unknown")


def _oracle_requirements_for_kernel(kernel: str) -> list[str]:
    base = ["pure_qe_baseline", "kernel_numeric_equivalence"]
    if kernel in {"forces", "stress"}:
        return base + ["force_stress_physical_equivalence"]
    if kernel in {"diagonalization", "subspace_rotation", "band_path_projection"}:
        return base + ["eigenvalue_summary_equivalence"]
    return base + ["scf_physical_equivalence_when_in_scf_loop"]


def _patch_feasibility_for_kernel(kernel: str, source_probe: Mapping[str, Any]) -> Dict[str, Any]:
    source_hit = source_probe.get("status") == "source_probe_hit"
    return {
        "status": "feasible_source_hit" if source_hit else "blocked_source_probe_missing",
        "patch_strategy": "qe_source_patch_callsite_instrumentation",
        "blockers": [] if source_hit else ["source_probe_missing_for_kernel"],
    }


def _runtime_payload_requirements_for_kernel(kernel: str) -> Dict[str, Any]:
    return {
        "schema": "qe.offload.extension_payload.v1",
        "must_include": [
            "opportunity_id",
            "tensor_shape",
            "dtype",
            "input_buffer_refs",
            "output_buffer_refs",
            "fallback_policy",
        ],
        "kernel": kernel,
    }


def _selection_priority_for_opportunity(row: Mapping[str, Any]) -> Dict[str, Any]:
    profile = dict(row.get("profile_evidence") or {})
    patch_feasibility = dict(row.get("patch_feasibility") or {})
    source = dict(row.get("source_provenance") or {})
    profile_seconds = profile.get("wall_seconds")
    profile_component = (
        float(profile_seconds) if isinstance(profile_seconds, (int, float)) else 0.0
    )
    source_component = (
        0.05 if source.get("source_probe_status") == "source_probe_hit" else 0.0
    )
    patch_component = (
        0.05 if patch_feasibility.get("status") == "feasible_source_hit" else 0.0
    )
    score = round(profile_component + source_component + patch_component, 6)
    blockers: list[str] = []
    if profile_component <= 0.0:
        blockers.append("profile_phase_not_observed_for_priority")
    if source_component <= 0.0:
        blockers.append("source_probe_missing_for_priority")
    if patch_component <= 0.0:
        blockers.append("patch_feasibility_missing_for_priority")
    return {
        "score": score,
        "components": {
            "fixture_profile_wall_seconds": profile_component,
            "source_probe_bonus": source_component,
            "patch_feasibility_bonus": patch_component,
        },
        "blockers": blockers,
        "policy": "rank DSE offload attempts only; not a value claim",
    }


def _bundle_selection_priority(
    bundle: Mapping[str, Any],
    opportunity_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    ids = [str(item) for item in bundle.get("opportunity_ids") or []]
    priorities = [
        dict(opportunity_by_id.get(opportunity_id, {}).get("selection_priority") or {})
        for opportunity_id in ids
    ]
    scores = [
        float(priority.get("score", 0.0))
        for priority in priorities
        if isinstance(priority.get("score", 0.0), (int, float))
    ]
    profile_observed_count = sum(
        1
        for opportunity_id in ids
        if dict(opportunity_by_id.get(opportunity_id, {}).get("profile_evidence") or {}).get(
            "status"
        )
        == "fixture_profile_observed"
    )
    blockers = _dedupe_strings(
        blocker
        for priority in priorities
        for blocker in priority.get("blockers", []) or []
    )
    bundle_bonus = 0.01 * max(0, len(ids) - 1)
    score = round(sum(scores) + bundle_bonus, 6)
    return {
        "score": score,
        "profile_observed_opportunity_count": profile_observed_count,
        "component_scores": scores,
        "bundle_size_bonus": round(bundle_bonus, 6),
        "blockers": blockers,
        "policy": "rank candidate bundles for attempt order; not a value claim",
    }


def _bundle_kernel_list(
    ids: Sequence[str],
    opportunity_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    return _dedupe_strings(
        opportunity_by_id.get(str(opportunity_id), {}).get("kernel")
        for opportunity_id in ids
    )


def _bundle_kernel_families(
    ids: Sequence[str],
    opportunity_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    return _dedupe_strings(
        opportunity_by_id.get(str(opportunity_id), {}).get("kernel_family")
        for opportunity_id in ids
    )


def build_offload_bundle_search_space(
    opportunities: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    manifest = dict(opportunities or build_offload_opportunity_manifest())
    rows = [row for row in manifest.get("opportunities", []) if isinstance(row, Mapping)]
    opportunity_by_id = {str(row.get("opportunity_id")): row for row in rows}
    bundles: list[Dict[str, Any]] = []
    for row in rows:
        opportunity_id = str(row["opportunity_id"])
        bundle = {
            "bundle_id": "bundle_" + stable_json_hash([opportunity_id])[:12],
            "opportunity_ids": [opportunity_id],
            "granularity": row.get("granularity", "kernel"),
            "kernel_families": [row.get("kernel_family")],
            "classification": "single_opportunity_l4_attempt_candidate",
            "hpsi_only": row.get("kernel") == "h_psi",
            "completion_allowed": False,
            "selection_priority": dict(row.get("selection_priority") or {}),
            "claim_boundary": "bundle can be attempted for L4 value; it is not completion evidence",
        }
        bundle["bundle_hash"] = _stable_hash_without(bundle, "bundle_hash")
        bundles.append(bundle)

    family_groups: Dict[str, list[str]] = {}
    for row in rows:
        family = str(row.get("kernel_family", "unknown"))
        family_groups.setdefault(family, []).append(str(row["opportunity_id"]))
    for family, ids in sorted(family_groups.items()):
        if len(ids) <= 1:
            continue
        bundle = {
            "bundle_id": "bundle_family_" + family + "_" + stable_json_hash(ids)[:8],
            "opportunity_ids": sorted(ids),
            "granularity": "bundle",
            "kernel_families": [family],
            "classification": "family_bundle_l4_attempt_candidate",
            "hpsi_only": family == "dense_subspace" and all("h_psi" in item for item in ids),
            "completion_allowed": False,
            "claim_boundary": "family bundle can be attempted for L4 value; not completion evidence",
        }
        bundle["selection_priority"] = _bundle_selection_priority(
            bundle, opportunity_by_id
        )
        bundle["bundle_hash"] = _stable_hash_without(bundle, "bundle_hash")
        bundles.append(bundle)

    workload_stage_groups: Dict[tuple[str, str], list[str]] = {}
    for row in rows:
        workload_case_id = str(row.get("workload_case_id") or "")
        stage_type = str(row.get("stage_type") or "")
        if not workload_case_id or not stage_type:
            continue
        workload_stage_groups.setdefault((workload_case_id, stage_type), []).append(
            str(row["opportunity_id"])
        )
    for (workload_case_id, stage_type), ids in sorted(workload_stage_groups.items()):
        ids = sorted(ids)
        if len(ids) <= 1:
            continue
        kernels = _bundle_kernel_list(ids, opportunity_by_id)
        bundle = {
            "bundle_id": (
                "bundle_workload_stage_"
                + _safe_identifier(workload_case_id)
                + "_"
                + _safe_identifier(stage_type)
                + "_"
                + stable_json_hash(ids)[:8]
            ),
            "opportunity_ids": ids,
            "granularity": "bundle",
            "workload_case_id": workload_case_id,
            "stage_type": stage_type,
            "kernel_list": kernels,
            "kernel_families": _bundle_kernel_families(ids, opportunity_by_id),
            "classification": "workload_stage_bundle_l4_attempt_candidate",
            "hpsi_only": bool(kernels) and all(kernel == "h_psi" for kernel in kernels),
            "completion_allowed": False,
            "bundle_execution_policy": (
                "same_workload_multi_callsite_actual_compute_candidate"
            ),
            "runnable_as_single_qe_workflow": True,
            "requires_real_qe_trace_for_all_targets": True,
            "claim_boundary": (
                "workload-stage bundle chooses a larger offload granularity for "
                "real L4 attempts; it is not completion or value evidence"
            ),
        }
        bundle["selection_priority"] = _bundle_selection_priority(
            bundle, opportunity_by_id
        )
        bundle["bundle_hash"] = _stable_hash_without(bundle, "bundle_hash")
        bundles.append(bundle)

        runtime_supported_ids = [
            opportunity_id
            for opportunity_id in ids
            if str(opportunity_by_id[opportunity_id].get("kernel") or "")
            in FIRST_PASS_ACTUAL_COMPUTE_RUNTIME_SUPPORTED_KERNELS
        ]
        if len(runtime_supported_ids) > 1:
            runtime_supported_ids = sorted(runtime_supported_ids)
            runtime_supported_kernels = _bundle_kernel_list(
                runtime_supported_ids,
                opportunity_by_id,
            )
            runtime_bundle = {
                "bundle_id": (
                    "bundle_runtime_supported_workload_stage_"
                    + _safe_identifier(workload_case_id)
                    + "_"
                    + _safe_identifier(stage_type)
                    + "_"
                    + stable_json_hash(runtime_supported_ids)[:8]
                ),
                "opportunity_ids": runtime_supported_ids,
                "granularity": "bundle",
                "workload_case_id": workload_case_id,
                "stage_type": stage_type,
                "kernel_list": runtime_supported_kernels,
                "kernel_families": _bundle_kernel_families(
                    runtime_supported_ids,
                    opportunity_by_id,
                ),
                "classification": (
                    "runtime_supported_workload_stage_bundle_l4_attempt_candidate"
                ),
                "parent_workload_stage_bundle_id": bundle["bundle_id"],
                "hpsi_only": False,
                "completion_allowed": False,
                "bundle_execution_policy": (
                    "same_workload_multi_callsite_actual_compute_candidate"
                ),
                "runnable_as_single_qe_workflow": True,
                "runtime_harness_supported": True,
                "first_pass_actual_compute_runtime_supported_kernels": list(
                    FIRST_PASS_ACTUAL_COMPUTE_RUNTIME_SUPPORTED_KERNELS
                ),
                "requires_real_qe_trace_for_all_targets": True,
                "claim_boundary": (
                    "runtime-supported sub-bundle is a searchable offload "
                    "target subset for the current non-smoke QE/gem5 harness; "
                    "it is not value evidence and does not complete unsupported "
                    "kernels from the parent workload-stage bundle"
                ),
            }
            runtime_bundle["selection_priority"] = _bundle_selection_priority(
                runtime_bundle,
                opportunity_by_id,
            )
            runtime_bundle["bundle_hash"] = _stable_hash_without(
                runtime_bundle,
                "bundle_hash",
            )
            bundles.append(runtime_bundle)
    bundles = sorted(
        bundles,
        key=lambda bundle: (
            -float(dict(bundle.get("selection_priority") or {}).get("score", 0.0)),
            str(bundle.get("bundle_id")),
        ),
    )

    payload = {
        "schema_version": "dse.qe_offload_bundle_search_space.v1",
        "status": "passed" if bundles else "blocked",
        "release_id": RELEASE_ID,
        "manifest_hash": manifest.get("manifest_hash"),
        "bundle_count": len(bundles),
        "cardinality_budget": {
            "first_pass_bundle_hard_cap": 256,
            "generated_bundle_count": len(bundles),
            "within_budget": len(bundles) <= 256,
            "unattempted_combinations_policy": "classify_or_block_before_value_claim",
        },
        "bundles": bundles,
        "hpsi_only_completion_allowed": False,
        "deliverable_complete_allowed": False,
        "claim_boundary": "search space only; value requires real L4 evidence",
    }
    payload["search_space_hash"] = _stable_hash_without(payload, "search_space_hash")
    return payload


def _patch_diff_targets(text: str) -> list[str]:
    targets: list[str] = []
    for line in text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4 and parts[3].startswith("b/"):
                targets.append(parts[3][2:])
        elif line.startswith("+++ b/"):
            targets.append(line.removeprefix("+++ b/").strip())
    return _dedupe_strings(targets)


def _inspect_materialized_callsite_patch(patch_file: str) -> Dict[str, Any]:
    path = Path(patch_file)
    if not path.exists():
        return {
            "path": patch_file,
            "exists": False,
            "source_targets": [],
            "trace_hook_present": False,
            "generic_bridge_hook_present": False,
            "sidecar_command_hook_present": False,
            "runtime_replacement_evidence_hook_present": False,
            "accelerated_result_writeback_present": False,
            "accelerated_consumption_marker_declared": False,
            "kernel_work_replacement_marker_declared": False,
            "accelerated_result_materialization_marker_declared": False,
            "accelerated_result_materialization_denial_declared": False,
            "qe_software_kernel_execution_skip_marker_declared": False,
            "qe_software_kernel_execution_skip_denial_declared": False,
            "accelerated_output_data_path_declared": False,
            "accelerator_numeric_payload_marker_declared": False,
            "component_model_boundary_declared": False,
            "l4_execution_proof_declared": False,
            "pure_software_fallback_marker_declared": False,
            "software_fallback_on_critical_path_declared": False,
            "replacement_mode": "not_materialized",
            "trusted_l4_replacement_precheck_passed": False,
            "value_gate_blockers": ["patch_file_not_materialized"],
            "claim_boundary": "missing patch file cannot prove replacement readiness",
        }

    text = path.read_text(encoding="utf-8", errors="ignore")
    trace_hook = "QE_OFFLOAD_TRACE_FILE" in text and "QE_OFFLOAD_CALLSITE" in text
    bridge_hook = "QE_OFFLOAD_BRIDGE_COMMAND" in text
    runtime_replacement_evidence_hook = (
        "QE_OFFLOAD_KERNEL_EVIDENCE_JSON" in text
        and "QE_OFFLOAD_PROVENANCE_JSON" in text
    )
    sidecar_hook = "SIDECAR_CMD" in text or "QE_OFFLOAD_HPSI_SIDECAR_CMD" in text
    sidecar_writeback = bool(
        re.search(
            r"\b(?:hpsi|spsi|psi)\s*\([^=\n]*\)\s*=\s*qe_[a-z0-9_]*sidecar",
            text,
            re.IGNORECASE,
        )
    )
    accelerated_materialized_marker = bool(
        re.search(
            r'"(?:accelerated_result_materialized_in_qe_memory|accelerated_output_written_to_qe_buffer|qe_consumed_accelerator_output_buffer)"\s*:\s*true',
            text,
            re.IGNORECASE,
        )
    )
    accelerated_materialization_denial = bool(
        re.search(
            r'"(?:qe_memory_materialization_claimed|qe_memory_writeback_materialized|accelerated_result_materialized_in_qe_memory|accelerated_output_written_to_qe_buffer|qe_consumed_accelerator_output_buffer)"\s*:\s*false',
            text,
            re.IGNORECASE,
        )
    )
    software_kernel_skipped_marker = bool(
        re.search(
            r'"(?:qe_software_kernel_execution_skipped|software_kernel_execution_removed_from_critical_path|software_kernel_work_skipped)"\s*:\s*true',
            text,
            re.IGNORECASE,
        )
    )
    software_kernel_skip_denial = bool(
        re.search(
            r'"(?:qe_software_fft_skipped|qe_software_kernel_execution_skipped|software_kernel_execution_skipped|software_kernel_execution_removed_from_critical_path|software_kernel_work_skipped)"\s*:\s*false',
            text,
            re.IGNORECASE,
        )
    )
    l4_identity_writeback = (
        "QE_OFFLOAD_ACCELERATED_WRITEBACK" in text
        and "generic_accel_l4_spsi" in text
        and accelerated_materialized_marker
        and software_kernel_skipped_marker
    )
    l4_diagonalization_writeback = (
        "QE_OFFLOAD_DIAGONALIZATION_ACCELERATED_WRITEBACK" in text
        and "generic_accel_l4_diagonalization" in text
        and "accelerated_results_consumed_by_qe" in text
    )
    l4_fft_writeback = (
        "QE_OFFLOAD_FFT_ACCELERATED_WRITEBACK" in text
        and "generic_accel_l4_fft" in text
        and "accelerated_results_consumed_by_qe" in text
    )
    l4_subspace_rotation_writeback = (
        "QE_OFFLOAD_SUBSPACE_ROTATION_ACCELERATED_WRITEBACK" in text
        and "generic_accel_l4_subspace_rotation" in text
        and "accelerated_results_consumed_by_qe" in text
    )
    l4_veff_writeback = (
        "QE_OFFLOAD_VEFF_ACCELERATED_WRITEBACK" in text
        and "generic_accel_l4_veff" in text
        and "accelerated_results_consumed_by_qe" in text
    )
    l4_rho_out_writeback = (
        "QE_OFFLOAD_RHO_OUT_ACCELERATED_WRITEBACK" in text
        and "generic_accel_l4_rho_out" in text
        and "accelerated_results_consumed_by_qe" in text
    )
    l4_mix_rho_writeback = (
        "QE_OFFLOAD_MIX_RHO_ACCELERATED_WRITEBACK" in text
        and "generic_accel_l4_mix_rho" in text
        and "accelerated_results_consumed_by_qe" in text
    )
    l4_forces_writeback = (
        "QE_OFFLOAD_FORCES_ACCELERATED_WRITEBACK" in text
        and "generic_accel_l4_forces" in text
        and "accelerated_results_consumed_by_qe" in text
    )
    non_identity_l4_writeback = (
        l4_diagonalization_writeback
        or l4_fft_writeback
        or l4_subspace_rotation_writeback
        or l4_veff_writeback
        or l4_rho_out_writeback
        or l4_mix_rho_writeback
        or l4_forces_writeback
    )
    writeback = (
        sidecar_writeback
        or l4_identity_writeback
        or l4_diagonalization_writeback
        or l4_fft_writeback
        or l4_subspace_rotation_writeback
        or l4_veff_writeback
        or l4_rho_out_writeback
        or l4_mix_rho_writeback
        or l4_forces_writeback
    )
    accelerated_output_data_path = bool(
        re.search(
            r"QE_OFFLOAD_ACCELERATED_(?:OUTPUT|RESULT|DATA)_(?:FILE|PATH|JSON|BIN|BINARY)",
            text,
            re.IGNORECASE,
        )
        or re.search(
            r"\b(?:accelerated|accelerator)_(?:output|result|data)_(?:file|path|buffer)\b",
            text,
            re.IGNORECASE,
        )
        or re.search(
            r"\b(?:read|load)_[a-z0-9_]*(?:accelerated|accelerator)_[a-z0-9_]*(?:output|result|data)",
            text,
            re.IGNORECASE,
        )
    )
    accelerator_numeric_payload_marker = bool(
        re.search(
            r'"(?:numeric_payload|numeric_result|numeric_values|output_values|'
            r'result_values|accelerated_result_values|payload_sha256|'
            r'payload_digest|result_sha256|result_digest|output_sha256|'
            r'output_digest|buffer_sha256|output_buffer_sha256|'
            r'accelerator_result_hash|kernel_result_digest|binary_output_path|'
            r'output_buffer_path|output_buffer_bytes|payload_bytes|'
            r'sample_values|matrix_digest|vector_digest)"\s*:',
            text,
            re.IGNORECASE,
        )
    )
    consumed_marker = "accelerated_results_consumed_by_qe" in text
    kernel_work_replacement_marker = (
        "qe_kernel_work_replaced_on_critical_path" in text
        or "accelerated_kernel_work_removed_from_critical_path" in text
    )
    component_boundary = (
        "software_component_model_not_l4" in text
        or "python_component_sidecar_not_l4" in text
        or "python_component_sidecar_reference_assisted" in text
    )
    l4_proof = "l4_execution_proof" in text
    pure_fallback = "pure_software_qe_baseline" in text or "software fallback" in text.lower()
    software_fallback_on_critical_path = bool(
        re.search(
            r'"(?:software_fallback_on_critical_path|pure_software_fallback_on_critical_path)"\s*:\s*true',
            text,
            re.IGNORECASE,
        )
    )

    blockers: list[str] = []
    if not trace_hook:
        blockers.append("callsite_trace_hook_missing")
    if bridge_hook and not runtime_replacement_evidence_hook:
        blockers.append("runtime_replacement_evidence_hook_missing")
    if not writeback:
        blockers.append("accelerated_result_writeback_missing")
    if component_boundary:
        blockers.append("component_model_boundary_not_l4")
    if writeback and not consumed_marker:
        blockers.append("accelerated_consumption_marker_missing")
    if writeback and not kernel_work_replacement_marker:
        blockers.append("kernel_work_replacement_marker_missing")
    if writeback and not accelerated_materialized_marker:
        blockers.append("accelerated_result_materialization_marker_missing")
    if (
        writeback
        and accelerated_materialization_denial
        and not accelerated_materialized_marker
    ):
        blockers.append("patch_declares_qe_materialization_denied")
    if writeback and not software_kernel_skipped_marker:
        blockers.append("qe_software_kernel_execution_skip_marker_missing")
    if (
        writeback
        and software_kernel_skip_denial
        and not software_kernel_skipped_marker
    ):
        blockers.append("patch_declares_software_kernel_skip_denied")
    if (
        writeback
        and software_fallback_on_critical_path
        and not kernel_work_replacement_marker
    ):
        blockers.append("patch_declares_software_fallback_on_critical_path")
    if writeback and not l4_proof:
        blockers.append("l4_execution_proof_marker_missing")
    if non_identity_l4_writeback and not accelerated_output_data_path:
        blockers.append("accelerated_output_data_path_missing")
    if writeback and not accelerator_numeric_payload_marker:
        blockers.append("accelerator_numeric_payload_marker_missing")

    if writeback and component_boundary:
        replacement_mode = "in_process_component_sidecar_writeback"
    elif writeback:
        replacement_mode = "in_process_result_writeback_candidate"
    elif trace_hook and bridge_hook:
        replacement_mode = "trace_plus_bridge_fallback"
    elif trace_hook:
        replacement_mode = "trace_only"
    else:
        replacement_mode = "materialized_unclassified"

    trusted_precheck = (
        writeback
        and consumed_marker
        and kernel_work_replacement_marker
        and accelerated_materialized_marker
        and software_kernel_skipped_marker
        and l4_proof
        and accelerator_numeric_payload_marker
        and not component_boundary
        and not blockers
    )
    return {
        "path": patch_file,
        "exists": True,
        "source_targets": _patch_diff_targets(text),
        "trace_hook_present": trace_hook,
        "generic_bridge_hook_present": bridge_hook,
        "sidecar_command_hook_present": sidecar_hook,
        "runtime_replacement_evidence_hook_present": (
            runtime_replacement_evidence_hook
        ),
        "accelerated_result_writeback_present": writeback,
        "accelerated_consumption_marker_declared": consumed_marker,
        "kernel_work_replacement_marker_declared": kernel_work_replacement_marker,
        "accelerated_result_materialization_marker_declared": accelerated_materialized_marker,
        "accelerated_result_materialization_denial_declared": accelerated_materialization_denial,
        "qe_software_kernel_execution_skip_marker_declared": software_kernel_skipped_marker,
        "qe_software_kernel_execution_skip_denial_declared": software_kernel_skip_denial,
        "accelerated_output_data_path_declared": accelerated_output_data_path,
        "accelerator_numeric_payload_marker_declared": accelerator_numeric_payload_marker,
        "component_model_boundary_declared": component_boundary,
        "l4_execution_proof_declared": l4_proof,
        "pure_software_fallback_marker_declared": pure_fallback,
        "software_fallback_on_critical_path_declared": (
            software_fallback_on_critical_path
        ),
        "replacement_mode": replacement_mode,
        "trusted_l4_replacement_precheck_passed": trusted_precheck,
        "value_gate_blockers": _dedupe_strings(blockers),
        "claim_boundary": (
            "patch text capability inspection only; it never upgrades a row to "
            "valuable_l4 without runtime L4/correctness/baseline/speed evidence"
        ),
    }


def _aggregate_patch_capabilities(
    patch_capabilities: Sequence[Mapping[str, Any]],
    *,
    trusted_precheck_allowed: bool = True,
) -> Dict[str, Any]:
    materialized = [row for row in patch_capabilities if row.get("exists") is True]
    missing = [str(row.get("path")) for row in patch_capabilities if row.get("exists") is not True]
    blockers: list[str] = []
    if not materialized:
        blockers.append("no_materialized_callsite_patch")
    else:
        for row in materialized:
            blockers.extend(str(item) for item in row.get("value_gate_blockers", []) or [])

    any_writeback = any(
        row.get("accelerated_result_writeback_present") is True for row in materialized
    )
    any_component_boundary = any(
        row.get("component_model_boundary_declared") is True for row in materialized
    )
    raw_trusted_precheck = any(
        row.get("trusted_l4_replacement_precheck_passed") is True for row in materialized
    )
    if raw_trusted_precheck and not trusted_precheck_allowed:
        blockers.append("multi_opportunity_bundle_patch_precheck_not_trusted")
    any_trusted_precheck = (
        raw_trusted_precheck
        and trusted_precheck_allowed
        and not blockers
    )
    if any_trusted_precheck:
        precheck_status = "trusted_l4_replacement_candidate_precheck_only"
    elif not materialized:
        precheck_status = "blocked_no_materialized_patch"
    elif any_component_boundary:
        precheck_status = "blocked_component_model_not_l4"
    elif not any_writeback:
        precheck_status = "blocked_bridge_or_trace_fallback_only"
    else:
        precheck_status = "blocked_replacement_evidence_incomplete"

    return {
        "materialized_patch_count": len(materialized),
        "missing_declared_patch_files": missing,
        "source_targets": _dedupe_strings(
            target
            for row in materialized
            for target in row.get("source_targets", []) or []
        ),
        "trace_hook_present": any(row.get("trace_hook_present") is True for row in materialized),
        "generic_bridge_hook_present": any(row.get("generic_bridge_hook_present") is True for row in materialized),
        "sidecar_command_hook_present": any(row.get("sidecar_command_hook_present") is True for row in materialized),
        "runtime_replacement_evidence_hook_present": any(
            row.get("runtime_replacement_evidence_hook_present") is True
            for row in materialized
        ),
        "accelerated_result_writeback_present": any_writeback,
        "accelerated_consumption_marker_declared": any(
            row.get("accelerated_consumption_marker_declared") is True
            for row in materialized
        ),
        "kernel_work_replacement_marker_declared": any(
            row.get("kernel_work_replacement_marker_declared") is True
            for row in materialized
        ),
        "accelerated_result_materialization_marker_declared": any(
            row.get("accelerated_result_materialization_marker_declared") is True
            for row in materialized
        ),
        "accelerated_result_materialization_denial_declared": any(
            row.get("accelerated_result_materialization_denial_declared") is True
            for row in materialized
        ),
        "qe_software_kernel_execution_skip_marker_declared": any(
            row.get("qe_software_kernel_execution_skip_marker_declared") is True
            for row in materialized
        ),
        "qe_software_kernel_execution_skip_denial_declared": any(
            row.get("qe_software_kernel_execution_skip_denial_declared") is True
            for row in materialized
        ),
        "accelerated_output_data_path_declared": any(
            row.get("accelerated_output_data_path_declared") is True
            for row in materialized
        ),
        "accelerator_numeric_payload_marker_declared": any(
            row.get("accelerator_numeric_payload_marker_declared") is True
            for row in materialized
        ),
        "component_model_boundary_declared": any_component_boundary,
        "l4_execution_proof_declared": any(row.get("l4_execution_proof_declared") is True for row in materialized),
        "software_fallback_on_critical_path_declared": any(
            row.get("software_fallback_on_critical_path_declared") is True
            for row in materialized
        ),
        "replacement_modes": _dedupe_strings(
            row.get("replacement_mode") for row in materialized
        ),
        "trusted_l4_replacement_precheck_passed": any_trusted_precheck,
        "trusted_l4_replacement_precheck_raw_present": raw_trusted_precheck,
        "trusted_l4_replacement_precheck_allowed_for_row": trusted_precheck_allowed,
        "replacement_precheck_status": precheck_status,
        "value_gate_blockers": _dedupe_strings(blockers),
        "claim_boundary": (
            "aggregates materialized QE patch capabilities; positive precheck "
            "would still be only a precondition, not a value claim"
        ),
    }


def _patch_replacement_precheck_not_provided() -> Dict[str, Any]:
    return {
        "status": "patch_manifest_not_provided",
        "patch_ids": [],
        "bundle_ids": [],
        "replacement_modes": [],
        "source_targets": [],
        "trace_hook_present": False,
        "generic_bridge_hook_present": False,
        "sidecar_command_hook_present": False,
        "runtime_replacement_evidence_hook_present": False,
        "accelerated_result_writeback_present": False,
        "accelerated_consumption_marker_declared": False,
        "kernel_work_replacement_marker_declared": False,
        "accelerated_result_materialization_marker_declared": False,
        "accelerated_result_materialization_denial_declared": False,
        "qe_software_kernel_execution_skip_marker_declared": False,
        "qe_software_kernel_execution_skip_denial_declared": False,
        "accelerated_output_data_path_declared": False,
        "accelerator_numeric_payload_marker_declared": False,
        "component_model_boundary_declared": False,
        "software_fallback_on_critical_path_declared": False,
        "trusted_l4_replacement_precheck_passed": False,
        "value_gate_blockers": ["patch_manifest_not_provided"],
        "claim_boundary": (
            "patch precheck was unavailable; replacement readiness remains "
            "blocked until runtime evidence proves the value gate"
        ),
    }


def _patch_replacement_precheck_for_opportunity(
    opportunity_id: str,
    patch_manifest: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    if not isinstance(patch_manifest, Mapping):
        return _patch_replacement_precheck_not_provided()

    patch_rows = [
        row
        for row in patch_manifest.get("patch_rows", []) or []
        if isinstance(row, Mapping)
        and opportunity_id in [str(item) for item in row.get("opportunity_ids") or []]
    ]
    exact_rows = [
        row
        for row in patch_rows
        if [str(item) for item in row.get("opportunity_ids") or []]
        == [opportunity_id]
    ]
    selected_rows = exact_rows or patch_rows
    if not selected_rows:
        return {
            "status": "blocked_no_patch_row_for_opportunity",
            "patch_ids": [],
            "bundle_ids": [],
            "replacement_modes": [],
            "source_targets": [],
            "trace_hook_present": False,
            "generic_bridge_hook_present": False,
            "sidecar_command_hook_present": False,
            "runtime_replacement_evidence_hook_present": False,
            "accelerated_result_writeback_present": False,
            "accelerated_consumption_marker_declared": False,
            "kernel_work_replacement_marker_declared": False,
            "accelerated_result_materialization_marker_declared": False,
            "accelerated_result_materialization_denial_declared": False,
            "qe_software_kernel_execution_skip_marker_declared": False,
            "qe_software_kernel_execution_skip_denial_declared": False,
            "accelerated_output_data_path_declared": False,
            "accelerator_numeric_payload_marker_declared": False,
            "component_model_boundary_declared": False,
            "software_fallback_on_critical_path_declared": False,
            "trusted_l4_replacement_precheck_passed": False,
            "value_gate_blockers": ["no_patch_row_for_opportunity"],
            "claim_boundary": "no patch manifest row covers this opportunity",
        }

    caps = [
        dict(row.get("instrumentation_capabilities") or {})
        for row in selected_rows
    ]
    blockers = _dedupe_strings(
        blocker
        for cap in caps
        for blocker in cap.get("value_gate_blockers", []) or []
    )
    trusted = any(
        cap.get("trusted_l4_replacement_precheck_passed") is True for cap in caps
    )
    component_blocked = any(
        cap.get("component_model_boundary_declared") is True for cap in caps
    )
    writeback = any(
        cap.get("accelerated_result_writeback_present") is True for cap in caps
    )
    if trusted:
        status = "trusted_l4_replacement_candidate_precheck_only"
    elif component_blocked:
        status = "blocked_component_model_not_l4"
    elif not writeback:
        status = "blocked_bridge_or_trace_fallback_only"
    else:
        status = "blocked_replacement_evidence_incomplete"
    return {
        "status": status,
        "patch_ids": _dedupe_strings(row.get("patch_id") for row in selected_rows),
        "bundle_ids": _dedupe_strings(row.get("bundle_id") for row in selected_rows),
        "selected_single_opportunity_patch": bool(exact_rows),
        "replacement_modes": _dedupe_strings(
            mode
            for cap in caps
            for mode in cap.get("replacement_modes", []) or []
        ),
        "source_targets": _dedupe_strings(
            target
            for cap in caps
            for target in cap.get("source_targets", []) or []
        ),
        "trace_hook_present": any(cap.get("trace_hook_present") is True for cap in caps),
        "generic_bridge_hook_present": any(
            cap.get("generic_bridge_hook_present") is True for cap in caps
        ),
        "sidecar_command_hook_present": any(
            cap.get("sidecar_command_hook_present") is True for cap in caps
        ),
        "runtime_replacement_evidence_hook_present": any(
            cap.get("runtime_replacement_evidence_hook_present") is True
            for cap in caps
        ),
        "accelerated_result_writeback_present": writeback,
        "accelerated_consumption_marker_declared": any(
            cap.get("accelerated_consumption_marker_declared") is True
            for cap in caps
        ),
        "kernel_work_replacement_marker_declared": any(
            cap.get("kernel_work_replacement_marker_declared") is True
            for cap in caps
        ),
        "accelerated_result_materialization_marker_declared": any(
            cap.get("accelerated_result_materialization_marker_declared") is True
            for cap in caps
        ),
        "accelerated_result_materialization_denial_declared": any(
            cap.get("accelerated_result_materialization_denial_declared") is True
            for cap in caps
        ),
        "qe_software_kernel_execution_skip_marker_declared": any(
            cap.get("qe_software_kernel_execution_skip_marker_declared") is True
            for cap in caps
        ),
        "qe_software_kernel_execution_skip_denial_declared": any(
            cap.get("qe_software_kernel_execution_skip_denial_declared") is True
            for cap in caps
        ),
        "accelerated_output_data_path_declared": any(
            cap.get("accelerated_output_data_path_declared") is True
            for cap in caps
        ),
        "accelerator_numeric_payload_marker_declared": any(
            cap.get("accelerator_numeric_payload_marker_declared") is True
            for cap in caps
        ),
        "component_model_boundary_declared": component_blocked,
        "software_fallback_on_critical_path_declared": any(
            cap.get("software_fallback_on_critical_path_declared") is True
            for cap in caps
        ),
        "trusted_l4_replacement_precheck_passed": trusted,
        "value_gate_blockers": blockers,
        "claim_boundary": (
            "patch precheck only; runtime replacement, L4 provenance, "
            "correctness, baseline, and positive speed are still required"
        ),
    }


def build_qe_callsite_patch_manifest(
    bundle_space: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    space = dict(bundle_space or build_offload_bundle_search_space())
    rows: list[Dict[str, Any]] = []
    for bundle in space.get("bundles", []) or []:
        if not isinstance(bundle, Mapping):
            continue
        bundle_id = str(bundle.get("bundle_id"))
        opportunity_ids = [str(item) for item in bundle.get("opportunity_ids") or []]
        patch_files = [
            "patches/qe_callsite_offload_hooks/" + bundle_id + ".patch",
            *[
                "patches/qe_callsite_offload_hooks/" + opportunity_id + ".patch"
                for opportunity_id in opportunity_ids
            ],
        ]
        materialized_patch_files = [
            {
                "path": patch_file,
                "exists": Path(patch_file).exists(),
            }
            for patch_file in patch_files
        ]
        patch_capabilities = [
            _inspect_materialized_callsite_patch(patch_file)
            for patch_file in patch_files
        ]
        instrumentation_capabilities = _aggregate_patch_capabilities(
            patch_capabilities,
            trusted_precheck_allowed=(len(opportunity_ids) == 1),
        )
        row = {
            "patch_id": "patch_" + stable_json_hash(bundle_id)[:12],
            "bundle_id": bundle_id,
            "opportunity_ids": opportunity_ids,
            "changed_files": patch_files,
            "materialized_patch_files": materialized_patch_files,
            "materialized_patch_capabilities": patch_capabilities,
            "instrumentation_capabilities": instrumentation_capabilities,
            "callsite_ids": [
                str(opportunity_id).replace("opp_", "callsite_", 1)
                for opportunity_id in opportunity_ids
            ],
            "patch_strategy": "qe_source_patch_callsite_instrumentation",
            "runtime_extension_payload": {
                "schema": "qe.offload.extension_payload.v1",
                "bundle_id": bundle_id,
                "opportunity_ids": opportunity_ids,
            },
            "runtime_payload_schema": "qe.offload.extension_payload.v1",
            "fallback_path": "pure_qe_software_fallback",
            "tolerance_impact": {
                "kernel_absolute_tolerance_delta": 0.0,
                "kernel_relative_tolerance_delta": 0.0,
                "scf_physical_tolerance_delta": 0.0,
                "review_required": True,
            },
            "correctness_oracle": [
                "kernel_numeric_equivalence",
                "scf_or_physical_equivalence_when_applicable",
            ],
            "performance_impact_hypothesis": "requires_real_l4_measurement",
            "trusted_status_rules": [
                "fallback_path_required",
                "tolerance_impact_required",
                "correctness_oracle_required",
                "real_l4_required_for_value",
                "materialized_patch_capabilities_are_precheck_only",
            ],
            "status": (
                "materialized_patch_available"
                if any(item["exists"] for item in materialized_patch_files)
                else "draft_patch_manifest_only"
            ),
            "claim_boundary": "patch manifest only; not evidence that patch was applied or valuable",
        }
        row["patch_hash"] = _stable_hash_without(row, "patch_hash")
        rows.append(row)
    payload = {
        "schema_version": "dse.qe_callsite_patch_manifest.v1",
        "status": "passed" if rows else "blocked",
        "release_id": RELEASE_ID,
        "bundle_search_space_hash": space.get("search_space_hash"),
        "patch_rows": rows,
        "materialized_patch_row_count": sum(
            1 for row in rows if row.get("status") == "materialized_patch_available"
        ),
        "trace_hook_patch_row_count": sum(
            1
            for row in rows
            if dict(row.get("instrumentation_capabilities") or {}).get(
                "trace_hook_present"
            )
            is True
        ),
        "replacement_writeback_patch_row_count": sum(
            1
            for row in rows
            if dict(row.get("instrumentation_capabilities") or {}).get(
                "accelerated_result_writeback_present"
            )
            is True
        ),
        "component_model_boundary_patch_row_count": sum(
            1
            for row in rows
            if dict(row.get("instrumentation_capabilities") or {}).get(
                "component_model_boundary_declared"
            )
            is True
        ),
        "trusted_l4_replacement_precheck_count": sum(
            1
            for row in rows
            if dict(row.get("instrumentation_capabilities") or {}).get(
                "trusted_l4_replacement_precheck_passed"
            )
            is True
        ),
        "all_rows_have_fallback_tolerance_correctness": all(
            row.get("fallback_path")
            and row.get("tolerance_impact")
            and row.get("correctness_oracle")
            for row in rows
        ),
        "claim_boundary": "patch provenance schema only; value requires real L4 row",
    }
    payload["manifest_hash"] = _stable_hash_without(payload, "manifest_hash")
    return payload


def validate_qe_callsite_patch_manifest(
    manifest: Mapping[str, Any],
) -> Dict[str, Any]:
    blockers: list[Dict[str, Any]] = []
    rows = [
        row
        for row in manifest.get("patch_rows", []) or []
        if isinstance(row, Mapping)
    ]
    required = (
        "changed_files",
        "callsite_ids",
        "runtime_extension_payload",
        "fallback_path",
        "tolerance_impact",
        "correctness_oracle",
        "performance_impact_hypothesis",
    )
    for index, row in enumerate(rows):
        for field in required:
            if not row.get(field):
                blockers.append(
                    {
                        "row_index": index,
                        "field": field,
                        "reason": f"{field} is required before L4 value can be trusted",
                    }
                )
    valid = bool(rows) and not blockers
    payload = {
        "schema_version": "dse.qe_callsite_patch_manifest.validation.v1",
        "valid": valid,
        "trusted_l4_value_allowed": valid,
        "trusted_blocks": blockers,
        "claim_boundary": "patch manifest validation only; real L4 value still requires evidence matrix gates",
    }
    payload["validation_hash"] = _stable_hash_without(
        payload, "validation_hash"
    )
    return payload


def build_l4_offload_attempt_queue(
    bundle_space: Mapping[str, Any] | None = None,
    *,
    max_attempts: int = 8,
    static_candidate_summary: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    space = dict(bundle_space or build_offload_bundle_search_space())
    bundles = [
        bundle
        for bundle in space.get("bundles", []) or []
        if isinstance(bundle, Mapping)
    ]
    rows: list[Dict[str, Any]] = []
    for index, bundle in enumerate(bundles[:max_attempts]):
        row = {
            "queue_id": f"l4_attempt_{index:03d}",
            "bundle_id": bundle.get("bundle_id"),
            "opportunity_ids": list(bundle.get("opportunity_ids") or []),
            "priority_rank": index + 1,
            "selection_priority": dict(bundle.get("selection_priority") or {}),
            "attempt_status": "blocked_until_qe_patch_and_build_available",
            "required_command_evidence": [
                "patched_qe_baseline_command",
                "gem5_genericaccel_qe_l4_command",
                "correctness_oracle_command",
                "speed_signal_extraction_command",
            ],
            "value_gate": "classify_l4_offload_value",
            "claim_boundary": "queue only; not a value claim",
        }
        row["queue_hash"] = _stable_hash_without(row, "queue_hash")
        rows.append(row)
    static_candidates = (
        list(static_candidate_summary.get("candidates_sample") or [])
        if isinstance(static_candidate_summary, Mapping)
        else []
    )
    static_candidate_rows: list[Dict[str, Any]] = []
    for index, candidate in enumerate(static_candidates[:64]):
        if not isinstance(candidate, Mapping):
            continue
        row = {
            "queue_id": f"static_research_{index:03d}",
            "symbol": candidate.get("symbol"),
            "source_file": candidate.get("source_file"),
            "kernel_guess": candidate.get("kernel_guess"),
            "kernel_family": candidate.get("kernel_family"),
            "call_count": candidate.get("call_count", 0),
            "classification": "research_only_static_candidate",
            "attempt_status": "blocked_until_workload_stage_callsite_binding",
            "required_promotion_evidence": [
                "concrete_qe_workload_case",
                "program_stage_phase_binding",
                "real_qe_trace_observation",
                "auditable_qe_patch_or_runtime_binding",
                "real_l4_correctness_replacement_speed_gate",
            ],
            "claim_boundary": (
                "static full-callgraph candidate queued for research; not an "
                "attempted_l4 row and not value evidence"
            ),
        }
        row["queue_hash"] = _stable_hash_without(row, "queue_hash")
        static_candidate_rows.append(row)
    skipped = max(0, len(bundles) - len(rows))
    payload = {
        "schema_version": "dse.qe_l4_offload_attempt_queue.v1",
        "status": "blocked" if rows else "blocked_no_attempt_candidates",
        "release_id": RELEASE_ID,
        "bundle_search_space_hash": space.get("search_space_hash"),
        "max_attempts": max_attempts,
        "attempt_count": len(rows),
        "skipped_bundle_count": skipped,
        "skipped_policy": "skipped bundles remain queued_by_projection or blocked; no skipped bundle can be valuable_l4",
        "attempts": rows,
        "static_research_candidate_count": (
            int(static_candidate_summary.get("candidate_count") or 0)
            if isinstance(static_candidate_summary, Mapping)
            else 0
        ),
        "static_research_candidate_kernel_counts": (
            dict(static_candidate_summary.get("kernel_counts") or {})
            if isinstance(static_candidate_summary, Mapping)
            else {}
        ),
        "static_research_candidates_sample": static_candidate_rows,
        "deliverable_complete": False,
        "claim_boundary": "bounded queue for future real L4 attempts",
    }
    payload["queue_hash"] = _stable_hash_without(payload, "queue_hash")
    return payload


def _l4_evidence_point_passed(real_l4: Mapping[str, Any], name: str) -> bool:
    value = real_l4.get(name)
    if isinstance(value, Mapping):
        return value.get("status") == "passed" or value.get("verified") is True
    if value is True:
        return True
    return real_l4.get(f"{name}_verified") is True


def _replacement_truthy(replacement: Mapping[str, Any], *keys: str) -> bool:
    return any(replacement.get(key) is True for key in keys)


def _replacement_nonempty_string(
    replacement: Mapping[str, Any],
    *keys: str,
) -> bool:
    return any(str(replacement.get(key) or "").strip() for key in keys)


def _accelerated_output_data_path_present(replacement: Mapping[str, Any]) -> bool:
    if replacement.get("accelerated_output_data_path_present") is True:
        return True
    output_paths = replacement.get("accelerated_output_data_paths")
    if isinstance(output_paths, Sequence) and not isinstance(
        output_paths, (str, bytes)
    ):
        if any(str(path or "").strip() for path in output_paths):
            return True
    return _replacement_nonempty_string(
        replacement,
        "accelerated_output_data_path",
        "accelerated_output_file",
        "accelerated_output_json",
        "accelerated_result_data_path",
        "accelerated_result_file",
        "accelerated_result_json",
        "accelerator_output_data_path",
        "accelerator_output_file",
        "QE_OFFLOAD_ACCELERATED_OUTPUT_JSON",
    )


def _runtime_rows_from_attempt(attempt: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    bridge = attempt.get("patched_qe_bridge_evidence")
    if not isinstance(bridge, Mapping):
        return []
    payload = bridge.get("runtime_kernel_evidence")
    if isinstance(payload, Mapping):
        rows = payload.get("kernel_evidence", payload.get("rows", payload))
    else:
        rows = payload
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, Mapping)]
    if isinstance(rows, Mapping):
        return [rows]
    return []


def _accelerated_output_payload(attempt: Mapping[str, Any]) -> Mapping[str, Any]:
    bridge = attempt.get("patched_qe_bridge_evidence")
    if not isinstance(bridge, Mapping):
        return {}
    payload = bridge.get("accelerated_output_json")
    return dict(payload) if isinstance(payload, Mapping) else {}


def _payload_has_accelerator_numeric_data(payload: Mapping[str, Any]) -> bool:
    """Return true only for payloads that carry data/digest, not status flags.

    A JSON file that merely says the bridge completed or that QE performed a
    writeback is transport/provenance evidence.  It is not proof that
    GenericAccel produced replacement numeric data consumed by QE.
    """

    strong_numeric_output_keys = {
        "numeric_result",
        "numeric_values",
        "output_values",
        "result_values",
        "accelerated_result_values",
        "binary_output_path",
        "output_buffer_path",
        "output_buffer_bytes",
        "matrix_values",
        "vector_values",
        "eigenvalues",
        "eigenvectors",
        "force_values",
        "forces",
    }
    numeric_keys = {
        "numeric_payload",
        "numeric_result",
        "numeric_values",
        "output_values",
        "result_values",
        "accelerated_result_values",
        "payload_sha256",
        "payload_digest",
        "result_sha256",
        "result_digest",
        "output_sha256",
        "output_digest",
        "buffer_sha256",
        "output_buffer_sha256",
        "accelerator_result_hash",
        "kernel_result_digest",
        "binary_output_path",
        "output_buffer_path",
        "output_buffer_bytes",
        "payload_bytes",
        "sample_values",
        "matrix_digest",
        "vector_digest",
    }
    payload_kind = str(payload.get("accelerator_numeric_payload_kind") or "").lower()
    generic_completion_digest = (
        payload_kind == "genericaccel_completion_result_json_digest"
    )
    for key, value in payload.items():
        normalized = str(key).strip().lower()
        if generic_completion_digest:
            if normalized in strong_numeric_output_keys and value not in (
                None,
                "",
                [],
                {},
            ):
                return True
            if isinstance(value, Mapping) and _payload_has_accelerator_numeric_data(
                value
            ):
                return True
            continue
        if normalized in numeric_keys and value not in (None, "", [], {}):
            return True
        if isinstance(value, Mapping) and _payload_has_accelerator_numeric_data(value):
            return True
    return False


PLACEHOLDER_KERNEL_NUMERIC_PAYLOAD_POLICIES = {
    "genericaccel_diagonalization_numeric_payload",
    "genericaccel_fft_numeric_payload",
    "genericaccel_identity_overlap_numeric_payload",
    "genericaccel_identity_subspace_rotation_payload",
    "genericaccel_zero_force_numeric_payload",
}


def _collect_payload_policy_markers(payload: Any) -> list[str]:
    markers: list[str] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if str(key).strip().lower() in {
                "replacement_policy",
                "writeback_policy",
                "force_vector_policy",
                "numeric_payload_policy",
            } and str(value or "").strip():
                markers.append(str(value).strip())
            elif isinstance(value, (Mapping, list)):
                markers.extend(_collect_payload_policy_markers(value))
    elif isinstance(payload, list):
        for item in payload:
            markers.extend(_collect_payload_policy_markers(item))
    return _dedupe_strings(markers)


def _placeholder_numeric_payload_blockers(attempt: Mapping[str, Any]) -> list[str]:
    """Block synthetic bridge payloads from satisfying actual-compute value.

    These policies are useful engineering probes because they prove QE can
    consume a GenericAccel-returned JSON payload. They are still not proof that
    GenericAccel performed the selected QE kernel's real numeric computation.
    Correctness and speed can only create value once the payload policy is a
    full-kernel compute result, not an identity/zero/synthetic placeholder.
    """

    payload = _accelerated_output_payload(attempt)
    blockers: list[str] = []
    if isinstance(payload, Mapping):
        payload_kind = str(
            payload.get("accelerator_numeric_payload_kind") or ""
        ).strip().lower()
        if (
            payload.get("placeholder_numeric_payload") is True
            or payload_kind == "genericaccel_placeholder_kernel_numeric_output_json"
        ):
            blockers.append(
                "accelerated_replacement_placeholder_numeric_payload:"
                "genericaccel_placeholder_kernel_numeric_output_json"
            )
    for marker in _collect_payload_policy_markers(payload):
        normalized = marker.lower()
        if normalized in PLACEHOLDER_KERNEL_NUMERIC_PAYLOAD_POLICIES:
            blockers.append(
                "accelerated_replacement_placeholder_numeric_payload:"
                + normalized
            )
    return _dedupe_strings(blockers)


def _runtime_text_markers(attempt: Mapping[str, Any]) -> str:
    bridge = attempt.get("patched_qe_bridge_evidence")
    sections: list[Mapping[str, Any]] = []
    if isinstance(bridge, Mapping):
        provenance = bridge.get("runtime_offload_provenance")
        if isinstance(provenance, Mapping):
            sections.append(provenance)
        payload = bridge.get("accelerated_output_json")
        if isinstance(payload, Mapping):
            sections.append(payload)
    sections.extend(_runtime_rows_from_attempt(attempt))
    fields = (
        "source",
        "source_kind",
        "producer",
        "accelerated_runtime",
        "offload_target",
        "claim_boundary",
        "replacement_policy",
        "writeback_policy",
        "force_vector_policy",
    )
    values: list[str] = []
    for section in sections:
        for field in fields:
            value = section.get(field)
            if value is not None:
                values.append(str(value))
    return " ".join(values).lower()


def _local_writeback_without_accelerator_payload_blockers(
    attempt: Mapping[str, Any],
) -> list[str]:
    text = _runtime_text_markers(attempt)
    local_writeback_markers = (
        "identity_writeback",
        "identity-overlap",
        "qe_memory_writeback",
        "l4 gated qe-memory replacement",
        "zero_force_writeback",
        "zero-force replacement",
    )
    if not any(marker in text for marker in local_writeback_markers):
        return []
    if _payload_has_accelerator_numeric_data(_accelerated_output_payload(attempt)):
        return []
    return [
        "accelerated_replacement_local_writeback_not_accelerator_numeric_output"
    ]


def _non_identity_target_requires_output_data_path(kernel: str | None) -> bool:
    return bool(kernel) and kernel not in {"h_psi", "s_psi"}


def _replacement_has_accelerator_numeric_payload(
    replacement: Mapping[str, Any], attempt: Mapping[str, Any]
) -> bool:
    return (
        replacement.get("accelerated_output_payload_numeric_data_present") is True
        or _payload_has_accelerator_numeric_data(_accelerated_output_payload(attempt))
    )


def classify_l4_offload_value(row: Mapping[str, Any]) -> Dict[str, Any]:
    evidence_kind = str(row.get("evidence_kind", ""))
    evidence_scope = str(row.get("evidence_scope", ""))
    blockers: list[str] = []
    if evidence_kind in BANNED_VALUE_EVIDENCE_KINDS:
        blockers.append(f"banned_value_evidence_kind:{evidence_kind}")
    if "smoke" in evidence_kind or evidence_scope in SMOKE_ONLY_EVIDENCE_SCOPES:
        blockers.append("smoke_dataflow_only_not_actual_compute")
    actual_compute = dict(row.get("actual_compute_evidence") or {})
    if actual_compute.get("status") != "passed":
        blockers.append("actual_compute_full_qe_evidence_not_passed")
    if actual_compute.get("smoke_only") is True:
        blockers.append("actual_compute_marked_smoke_only")
    if actual_compute and actual_compute.get("qe_consumed_accelerated_outputs") is not True:
        blockers.append("actual_compute_qe_consumed_replacement_not_proven")
    if (
        actual_compute
        and actual_compute.get("accelerated_result_materialized_in_qe_memory")
        is not True
    ):
        blockers.append("actual_compute_materialization_not_proven")
    if (
        actual_compute
        and actual_compute.get("qe_software_kernel_execution_skipped") is not True
    ):
        blockers.append("actual_compute_software_kernel_skip_not_proven")
    if (
        actual_compute
        and actual_compute.get("qe_kernel_work_replaced_on_critical_path")
        is not True
    ):
        blockers.append("actual_compute_kernel_work_replacement_not_proven")
    if (
        actual_compute.get("single_qe_workflow_bundle_run") is True
        and actual_compute.get("single_qe_workflow_covers_full_bundle") is False
    ):
        blockers.append("single_qe_workflow_does_not_cover_full_bundle")

    real_l4 = dict(row.get("real_l4_provenance") or {})
    correctness = dict(row.get("correctness") or {})
    baseline = dict(row.get("pure_qe_baseline") or {})
    replacement = dict(row.get("accelerated_replacement") or {})
    speed = dict(row.get("speed_signal") or {})

    if real_l4.get("status") != "passed":
        blockers.append("real_l4_provenance_not_passed")
    if real_l4.get("source") != "gem5_genericaccel_qe_patched":
        blockers.append("real_l4_source_not_qe_patched_genericaccel")
    for point in (
        "descriptor",
        "request_decode",
        "microarchitecture_execute",
        "completion",
    ):
        if not _l4_evidence_point_passed(real_l4, point):
            blockers.append(f"real_l4_{point}_evidence_missing_or_failed")
    if correctness.get("status") != "passed":
        blockers.append("correctness_not_passed")
    if baseline.get("status") != "passed":
        blockers.append("pure_qe_baseline_not_passed")
    replacement_passed = (
        replacement.get("status") == "passed"
        and replacement.get("accelerated_results_consumed_by_qe") is True
        and replacement.get("software_fallback_on_critical_path") is False
    )
    if not replacement_passed:
        blockers.append("accelerated_replacement_not_passed")
    materialized_in_qe = _replacement_truthy(
        replacement,
        "accelerated_result_materialized_in_qe_memory",
        "accelerated_output_written_to_qe_buffer",
        "qe_consumed_accelerator_output_buffer",
    )
    if not materialized_in_qe:
        blockers.append("accelerated_result_materialization_not_proven")
    software_kernel_skipped = _replacement_truthy(
        replacement,
        "qe_software_kernel_execution_skipped",
        "software_kernel_execution_removed_from_critical_path",
        "software_kernel_work_skipped",
    )
    if not software_kernel_skipped:
        blockers.append("qe_software_kernel_execution_skip_not_proven")
    kernel_work_replaced = (
        _replacement_truthy(
            replacement,
            "qe_kernel_work_replaced_on_critical_path",
            "accelerated_kernel_work_removed_from_critical_path",
        )
        and materialized_in_qe
        and software_kernel_skipped
    )
    if not kernel_work_replaced:
        blockers.append("qe_kernel_work_replacement_not_proven")
    selected_kernel = str(
        replacement.get("selected_kernel")
        or replacement.get("target_kernel")
        or row.get("kernel")
        or ""
    )
    if (
        _non_identity_target_requires_output_data_path(selected_kernel)
        and not _accelerated_output_data_path_present(replacement)
    ):
        blockers.append("accelerated_replacement_output_data_path_missing")
    if (
        _non_identity_target_requires_output_data_path(selected_kernel)
        and not _replacement_has_accelerator_numeric_payload(replacement, row)
    ):
        blockers.append(
            "accelerated_replacement_numeric_payload_missing_for_non_identity_target"
        )
    blockers.extend(_local_writeback_without_accelerator_payload_blockers(row))
    blockers.extend(_placeholder_numeric_payload_blockers(row))

    speedup = speed.get("speedup_vs_pure_qe")
    positive_speed = speed.get("status") == "positive" or (
        isinstance(speedup, (int, float)) and speedup > 1.0
    )
    if not positive_speed:
        blockers.append("positive_speed_signal_missing")

    valuable = not blockers
    hard_attempt_blockers = {
        "actual_compute_full_qe_evidence_not_passed",
        "actual_compute_marked_smoke_only",
        "real_l4_provenance_not_passed",
        "real_l4_source_not_qe_patched_genericaccel",
        "correctness_not_passed",
        "pure_qe_baseline_not_passed",
    }
    if valuable:
        label = "valuable_l4"
    elif set(blockers).isdisjoint(hard_attempt_blockers) and (
        real_l4.get("status") == "passed"
        and correctness.get("status") == "passed"
        and actual_compute.get("status") == "passed"
    ):
        label = "not_valuable_l4"
    elif real_l4:
        label = "blocked"
    else:
        label = "queued_by_projection"

    result = {
        "schema_version": "dse.qe_l4_offload_value_verdict.v1",
        "status": "passed" if valuable else "blocked_or_not_valuable",
        "valuable_l4": valuable,
        "value_label": label,
        "deliverable_complete": False,
        "blockers": blockers,
        "claim_boundary": "only valuable_l4 rows have real L4 correctness plus speed; first pass never claims deliverable_complete",
    }
    result["verdict_hash"] = _stable_hash_without(result, "verdict_hash")
    return result


def _evidence_selection_rank(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Rank duplicate evidence rows for one opportunity without hiding attempts.

    Cumulative reports may contain several attempts for the same callsite, for
    example a successful single-launch replacement probe followed by a blocked
    batched-dispatch probe.  Per-opportunity matrix/readiness rows should keep
    the strongest achieved evidence while aggregate attempt counters continue
    to count every raw attempt.
    """
    verdict = classify_l4_offload_value(row)
    actual_compute = dict(row.get("actual_compute_evidence") or {})
    real_l4 = dict(row.get("real_l4_provenance") or {})
    correctness = dict(row.get("correctness") or {})
    baseline = dict(row.get("pure_qe_baseline") or {})
    replacement = dict(row.get("accelerated_replacement") or {})
    speed = dict(row.get("speed_signal") or {})
    speedup = speed.get("speedup_vs_pure_qe")
    speedup_rank = float(speedup) if isinstance(speedup, (int, float)) else -1.0
    kernel_work_replaced = (
        _replacement_truthy(
            replacement,
            "qe_kernel_work_replaced_on_critical_path",
            "accelerated_kernel_work_removed_from_critical_path",
        )
        and _replacement_truthy(
            replacement,
            "accelerated_result_materialized_in_qe_memory",
            "accelerated_output_written_to_qe_buffer",
            "qe_consumed_accelerator_output_buffer",
        )
        and _replacement_truthy(
            replacement,
            "qe_software_kernel_execution_skipped",
            "software_kernel_execution_removed_from_critical_path",
            "software_kernel_work_skipped",
        )
    )
    strict_replacement_ready = (
        replacement.get("status") == "passed"
        and replacement.get("accelerated_results_consumed_by_qe") is True
        and kernel_work_replaced
        and replacement.get("software_fallback_on_critical_path") is False
    )
    non_smoke_actual_compute = (
        actual_compute.get("non_smoke_actual_compute_run") is True
        or row.get("evidence_mode") == "actual_compute"
        or row.get("evidence_scope") == "full_qe_actual_compute"
    )
    label_rank = {
        "valuable_l4": 5,
        "not_valuable_l4": 4,
        "blocked": 2,
        "queued_by_projection": 1,
    }.get(str(verdict.get("value_label") or ""), 0)
    blocker_count = len(verdict.get("blockers") or [])
    return (
        1 if verdict.get("valuable_l4") is True else 0,
        1 if actual_compute.get("status") == "passed" and strict_replacement_ready else 0,
        1 if strict_replacement_ready else 0,
        label_rank,
        1 if speed.get("status") == "positive" or speedup_rank > 1.0 else 0,
        1 if correctness.get("status") == "passed" else 0,
        1 if real_l4.get("status") == "passed" else 0,
        1 if baseline.get("status") == "passed" else 0,
        1 if non_smoke_actual_compute else 0,
        speedup_rank,
        -blocker_count,
    )


def _best_evidence_rows_by_opportunity(
    rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Mapping[str, Any]]:
    best_by_opp: Dict[str, Mapping[str, Any]] = {}
    best_rank_by_opp: Dict[str, tuple[Any, ...]] = {}
    for index, row in enumerate(rows):
        opportunity_id = str(row.get("opportunity_id") or "")
        if not opportunity_id:
            continue
        rank = (*_evidence_selection_rank(row), index)
        if opportunity_id not in best_rank_by_opp or rank > best_rank_by_opp[opportunity_id]:
            best_rank_by_opp[opportunity_id] = rank
            best_by_opp[opportunity_id] = row
    return best_by_opp


def build_offload_value_l4_evidence_matrix(
    opportunity_manifest: Mapping[str, Any] | None = None,
    evidence_rows: Sequence[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    manifest = dict(opportunity_manifest or build_offload_opportunity_manifest())
    opportunity_by_id = {
        str(row.get("opportunity_id")): row
        for row in manifest.get("opportunities", []) or []
        if isinstance(row, Mapping) and row.get("opportunity_id")
    }
    raw_evidence_rows = [
        row for row in (evidence_rows or []) if isinstance(row, Mapping)
    ]
    evidence_by_opp = _best_evidence_rows_by_opportunity(raw_evidence_rows)
    rows: list[Dict[str, Any]] = []
    for opportunity in manifest.get("opportunities", []) or []:
        if not isinstance(opportunity, Mapping):
            continue
        opportunity_id = str(opportunity["opportunity_id"])
        evidence = evidence_by_opp.get(opportunity_id, {})
        verdict = classify_l4_offload_value(evidence) if evidence else {
            "valuable_l4": False,
            "value_label": "queued_by_projection",
            "blockers": ["real_l4_not_attempted"],
            "status": "queued_by_projection",
        }
        row = {
            "opportunity_id": opportunity_id,
            "kernel": opportunity.get("kernel"),
            "stage_type": opportunity.get("stage_type"),
            "evidence_present": bool(evidence),
            "value_label": verdict["value_label"],
            "valuable_l4": verdict["valuable_l4"],
            "deliverable_complete_eligible": False,
            "blockers": verdict.get("blockers", []),
            "claim_boundary": "row value only; first-pass report cannot claim deliverable_complete",
        }
        row["row_hash"] = _stable_hash_without(row, "row_hash")
        rows.append(row)
    value_counts: Dict[str, int] = {}
    for row in rows:
        label = str(row["value_label"])
        value_counts[label] = value_counts.get(label, 0) + 1
    raw_verdicts = [
        classify_l4_offload_value(evidence)
        for evidence in raw_evidence_rows
        if evidence.get("opportunity_id")
    ]
    actual_compute_blocked_count = sum(
        1
        for verdict in raw_verdicts
        if set(verdict.get("blockers") or []).intersection(
            {
                "actual_compute_full_qe_evidence_not_passed",
                "accelerated_replacement_not_passed",
                "accelerated_result_materialization_not_proven",
                "qe_software_kernel_execution_skip_not_proven",
                "qe_kernel_work_replacement_not_proven",
                "accelerated_replacement_local_writeback_not_accelerator_numeric_output",
            }
        )
    )
    smoke_dataflow_only_count = sum(
        1
        for verdict in raw_verdicts
        if "smoke_dataflow_only_not_actual_compute"
        in set(verdict.get("blockers") or [])
    )
    actual_compute_passed_count = 0
    non_smoke_actual_compute_attempt_count = 0
    actual_compute_not_valuable_l4_count = 0
    actual_compute_kernel_counts: Dict[str, int] = {}
    non_hpsi_actual_compute_attempt_count = 0
    non_hpsi_non_spsi_actual_compute_attempt_count = 0
    non_hpsi_non_spsi_actual_compute_blocked_count = 0
    for evidence in raw_evidence_rows:
        opportunity_id = str(evidence.get("opportunity_id") or "")
        if not opportunity_id:
            continue
        actual_compute = dict(evidence.get("actual_compute_evidence") or {})
        kernel = str(
            evidence.get("kernel")
            or actual_compute.get("selected_kernel")
            or dict(opportunity_by_id.get(opportunity_id) or {}).get("kernel")
            or ""
        )
        if (
            actual_compute.get("non_smoke_actual_compute_run") is True
            or evidence.get("evidence_mode") == "actual_compute"
            or evidence.get("evidence_scope") == "full_qe_actual_compute"
        ):
            accelerated_replacement = dict(evidence.get("accelerated_replacement") or {})
            qe_consumed_accelerated_outputs = (
                actual_compute.get("qe_consumed_accelerated_outputs") is True
                or accelerated_replacement.get("accelerated_results_consumed_by_qe")
                is True
            )
            qe_kernel_work_replaced = (
                (
                    actual_compute.get("qe_kernel_work_replaced_on_critical_path")
                    is True
                    or accelerated_replacement.get(
                        "qe_kernel_work_replaced_on_critical_path"
                    )
                    is True
                    or accelerated_replacement.get(
                        "accelerated_kernel_work_removed_from_critical_path"
                    )
                    is True
                )
                and (
                    actual_compute.get("accelerated_result_materialized_in_qe_memory")
                    is True
                    or accelerated_replacement.get(
                        "accelerated_result_materialized_in_qe_memory"
                    )
                    is True
                    or accelerated_replacement.get(
                        "accelerated_output_written_to_qe_buffer"
                    )
                    is True
                    or accelerated_replacement.get(
                        "qe_consumed_accelerator_output_buffer"
                    )
                    is True
                )
                and (
                    actual_compute.get("qe_software_kernel_execution_skipped")
                    is True
                    or accelerated_replacement.get(
                        "qe_software_kernel_execution_skipped"
                    )
                    is True
                    or accelerated_replacement.get(
                        "software_kernel_execution_removed_from_critical_path"
                    )
                    is True
                    or accelerated_replacement.get("software_kernel_work_skipped")
                    is True
                )
            )
            local_writeback_payload_blockers = (
                _local_writeback_without_accelerator_payload_blockers(evidence)
            )
            trusted_actual_compute_passed = (
                actual_compute.get("status") == "passed"
                and actual_compute.get("smoke_only") is not True
                and qe_consumed_accelerated_outputs
                and qe_kernel_work_replaced
                and not local_writeback_payload_blockers
            )
            non_smoke_actual_compute_attempt_count += 1
            if kernel:
                actual_compute_kernel_counts[kernel] = (
                    actual_compute_kernel_counts.get(kernel, 0) + 1
                )
            if kernel != "h_psi":
                non_hpsi_actual_compute_attempt_count += 1
            if kernel not in {"h_psi", "s_psi"}:
                non_hpsi_non_spsi_actual_compute_attempt_count += 1
                if not trusted_actual_compute_passed:
                    non_hpsi_non_spsi_actual_compute_blocked_count += 1
        else:
            trusted_actual_compute_passed = False
        if trusted_actual_compute_passed:
            actual_compute_passed_count += 1
            if classify_l4_offload_value(evidence).get("valuable_l4") is not True:
                actual_compute_not_valuable_l4_count += 1
    payload = {
        "schema_version": "dse.qe_offload_value_l4_evidence_matrix.v1",
        "status": "passed" if rows else "blocked",
        "release_id": RELEASE_ID,
        "manifest_hash": manifest.get("manifest_hash"),
        "row_count": len(rows),
        "rows": rows,
        "value_counts": value_counts,
        "valuable_l4_count": value_counts.get("valuable_l4", 0),
        "real_l4_attempt_count": sum(1 for row in rows if row["evidence_present"]),
        "actual_compute_full_qe_evidence_required": True,
        "non_smoke_actual_compute_attempt_count": (
            non_smoke_actual_compute_attempt_count
        ),
        "actual_compute_attempted_kernels": sorted(actual_compute_kernel_counts),
        "actual_compute_attempted_kernel_count": len(actual_compute_kernel_counts),
        "actual_compute_attempted_kernel_counts": actual_compute_kernel_counts,
        "non_hpsi_actual_compute_attempt_count": (
            non_hpsi_actual_compute_attempt_count
        ),
        "non_hpsi_non_spsi_actual_compute_attempt_count": (
            non_hpsi_non_spsi_actual_compute_attempt_count
        ),
        "non_hpsi_non_spsi_actual_compute_blocked_count": (
            non_hpsi_non_spsi_actual_compute_blocked_count
        ),
        "actual_compute_full_qe_evidence_passed_count": (
            actual_compute_passed_count
        ),
        "actual_compute_not_valuable_l4_count": (
            actual_compute_not_valuable_l4_count
        ),
        "actual_compute_full_qe_evidence_blocked_count": (
            actual_compute_blocked_count
        ),
        "smoke_dataflow_only_value_blocked_count": smoke_dataflow_only_count,
        "deliverable_complete": False,
        "hpsi_only_completion_allowed": False,
        "projection_only_value_allowed": False,
        "smoke_value_allowed": False,
        "claim_boundary": "first-pass value matrix; deliverable_complete is false by contract",
    }
    payload["matrix_hash"] = _stable_hash_without(payload, "matrix_hash")
    return payload


def _stable_repeatability_rows_by_opportunity(
    repeatability_report: Mapping[str, Any] | None,
) -> Dict[str, list[Dict[str, Any]]]:
    rows_by_opp: Dict[str, list[Dict[str, Any]]] = {}
    for row in (repeatability_report or {}).get("rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        if row.get("repeatability_stable_value") is not True:
            continue
        opportunity_id = str(row.get("opportunity_id") or "")
        if not opportunity_id:
            continue
        rows_by_opp.setdefault(opportunity_id, []).append(dict(row))
    for rows in rows_by_opp.values():
        rows.sort(
            key=lambda row: (
                -float(row.get("max_speedup_vs_pure_qe") or -1.0),
                str(row.get("replacement_configuration_identity_key") or ""),
            )
        )
    return rows_by_opp


def _stable_repeatability_summary(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "workload_variant_id": row.get("workload_variant_id"),
        "runtime_workload_case_id": row.get("runtime_workload_case_id"),
        "replacement_configuration_identity_key": row.get(
            "replacement_configuration_identity_key"
        ),
        "replacement_configuration": dict(
            row.get("replacement_configuration") or {}
        ),
        "replacement_ready_sample_count": row.get(
            "replacement_ready_sample_count"
        ),
        "valuable_l4_sample_count": row.get("valuable_l4_sample_count"),
        "positive_speed_sample_count": row.get("positive_speed_sample_count"),
        "non_positive_speed_sample_count": row.get(
            "non_positive_speed_sample_count"
        ),
        "speedups_vs_pure_qe": list(row.get("speedups_vs_pure_qe") or []),
        "min_speedup_vs_pure_qe": row.get("min_speedup_vs_pure_qe"),
        "max_speedup_vs_pure_qe": row.get("max_speedup_vs_pure_qe"),
        "source_attempt_artifacts": list(row.get("source_attempt_artifacts") or []),
    }


def build_offload_value_report(
    matrix: Mapping[str, Any] | None = None,
    repeatability_report: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    mat = dict(matrix or build_offload_value_l4_evidence_matrix())
    blocked = [row for row in mat.get("rows", []) if row.get("value_label") == "blocked"]
    queued = [row for row in mat.get("rows", []) if row.get("value_label") == "queued_by_projection"]
    valuable = [row for row in mat.get("rows", []) if row.get("valuable_l4") is True]
    stable_by_opp = _stable_repeatability_rows_by_opportunity(
        repeatability_report
    )
    stable_configurations = [
        {
            "opportunity_id": opportunity_id,
            "kernel": next(
                (
                    row.get("kernel")
                    for row in mat.get("rows", []) or []
                    if isinstance(row, Mapping)
                    and str(row.get("opportunity_id") or "") == opportunity_id
                ),
                None,
            ),
            **_stable_repeatability_summary(stable_row),
        }
        for opportunity_id, stable_rows in sorted(stable_by_opp.items())
        for stable_row in stable_rows
    ]
    payload = {
        "schema_version": "dse.qe_offload_value_report.v1",
        "status": "partial_or_blocked" if blocked or queued else "offload_value_discovery_complete",
        "release_id": RELEASE_ID,
        "matrix_hash": mat.get("matrix_hash"),
        "summary": {
            "row_count": mat.get("row_count", 0),
            "valuable_l4_count": len(valuable),
            "stable_repeatability_valuable_l4_count": len(
                stable_configurations
            ),
            "blocked_count": len(blocked),
            "queued_by_projection_count": len(queued),
            "non_smoke_actual_compute_attempt_count": mat.get(
                "non_smoke_actual_compute_attempt_count", 0
            ),
            "actual_compute_attempted_kernel_count": mat.get(
                "actual_compute_attempted_kernel_count", 0
            ),
            "actual_compute_attempted_kernels": mat.get(
                "actual_compute_attempted_kernels", []
            ),
            "non_hpsi_non_spsi_actual_compute_attempt_count": mat.get(
                "non_hpsi_non_spsi_actual_compute_attempt_count", 0
            ),
        },
        "claims": {
            "offload_value_discovery_complete": not blocked and not queued and bool(mat.get("rows")),
            "deliverable_complete": False,
            "hpsi_only_completion_allowed": False,
            "projection_only_value_allowed": False,
        },
        "stable_repeatability_configurations": stable_configurations,
        "claim_boundary": "reports discovered value only; final deliverable_complete requires a later finite release closure plan",
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _nested_attempt_blockers(attempt: Mapping[str, Any]) -> list[str]:
    blockers: list[Any] = []
    blockers.extend(attempt.get("blockers") or [])
    for section_name in (
        "trace_evidence",
        "gem5_transport_evidence",
        "patched_qe_bridge_evidence",
        "accelerated_replacement",
        "correctness",
        "speed_signal",
    ):
        section = attempt.get(section_name)
        if isinstance(section, Mapping):
            blockers.extend(section.get("blockers") or [])
    real_l4 = attempt.get("real_l4_provenance")
    if isinstance(real_l4, Mapping):
        blockers.extend(real_l4.get("blockers") or [])
        for point in (
            "descriptor",
            "request_decode",
            "microarchitecture_execute",
            "completion",
        ):
            point_payload = real_l4.get(point)
            if isinstance(point_payload, Mapping):
                blockers.extend(point_payload.get("blockers") or [])
    selection = attempt.get("selection_profile")
    if isinstance(selection, Mapping) and selection.get("selection_blocker"):
        selection_blocker = str(selection.get("selection_blocker"))
        trace_observed = _selected_kernel_observed_in_trace(
            attempt, attempt.get("kernel")
        )
        if not (
            selection_blocker
            == "explicit_opportunity_kernel_not_observed_in_real_qe_profile"
            and trace_observed is True
        ):
            blockers.append(selection_blocker)
    return _dedupe_strings(blockers)


def _status_from_section(
    attempt: Mapping[str, Any],
    section_name: str,
    *,
    default: str,
) -> str:
    section = attempt.get(section_name)
    if isinstance(section, Mapping) and section.get("status"):
        return str(section["status"])
    return default


def _attempt_gpu_runtime_context(attempt: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the pure-QE baseline GPU context, if the attempt recorded one."""
    for candidate in (
        attempt.get("baseline_gpu_runtime_context"),
        dict(attempt.get("pure_qe_baseline") or {}).get("gpu_runtime_context"),
    ):
        if isinstance(candidate, Mapping):
            return dict(candidate)
    baseline = dict(attempt.get("pure_qe_baseline") or {}).get("baseline_result")
    if isinstance(baseline, Mapping) and isinstance(
        baseline.get("gpu_runtime_context"), Mapping
    ):
        return dict(baseline["gpu_runtime_context"])
    return {}


def _attempt_workload_variant_identity(
    attempt: Mapping[str, Any],
    matrix_value_row: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return the workload identity used by an L4 attempt.

    ``opportunity_id`` is not sufficient for value-repeatability grouping:
    the same QE callsite can be re-run under a canonical workload and one or
    more formal workload variants.  Keeping this identity in speed rows makes
    the DSE decision surface explicitly answer *which workload* was offloaded
    instead of mixing scaled and canonical samples.
    """

    selection = attempt.get("selection_profile")
    selection_profile = dict(selection) if isinstance(selection, Mapping) else {}
    raw_variant_id = selection_profile.get("workload_variant_id")
    workload_variant_id = (
        str(raw_variant_id) if raw_variant_id not in (None, "") else None
    )
    workload_variant_applied = selection_profile.get("workload_variant_applied")
    if not isinstance(workload_variant_applied, bool):
        workload_variant_applied = workload_variant_id is not None
    binding = selection_profile.get("workload_variant_binding")
    workload_variant_binding = dict(binding) if isinstance(binding, Mapping) else {}
    matrix_row = dict(matrix_value_row or {})
    original_workload_case_id = (
        selection_profile.get("original_workload_case_id")
        or attempt.get("original_workload_case_id")
        or attempt.get("workload_case_id")
        or matrix_row.get("workload_case_id")
    )
    runtime_workload_case_id = (
        selection_profile.get("runtime_workload_case_id")
        or attempt.get("runtime_workload_case_id")
        or attempt.get("workload_case_id")
        or matrix_row.get("workload_case_id")
        or original_workload_case_id
    )
    workload_variant_identity_key = (
        f"workload_variant:{workload_variant_id}"
        if workload_variant_id is not None
        else "canonical_workload"
    )
    return {
        "workload_variant_id": workload_variant_id,
        "workload_variant_applied": workload_variant_applied,
        "workload_variant_identity_key": workload_variant_identity_key,
        "workload_variant_binding": workload_variant_binding,
        "original_workload_case_id": (
            str(original_workload_case_id)
            if original_workload_case_id not in (None, "")
            else None
        ),
        "runtime_workload_case_id": (
            str(runtime_workload_case_id)
            if runtime_workload_case_id not in (None, "")
            else None
        ),
    }


def _first_payload_policy_marker(payload: Mapping[str, Any]) -> str | None:
    for marker in _collect_payload_policy_markers(payload):
        if marker:
            return marker
    return None


def _attempt_replacement_configuration_identity(
    attempt: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return a stable identity for the measured replacement implementation.

    Opportunity/workload identity answers *what* QE work was targeted.  It is
    not enough for repeatability because the same workload can be measured with
    materially different replacement implementations: completion-digest JSON,
    input-buffer binary payload, fast-shell tail copy, single-launch bridge, or
    prelaunched bridge.  Mixing those configurations can hide whether the
    current DSE-selected implementation is repeatable.  This identity is only a
    reporting partition; it never upgrades a row past the underlying value gate.
    """

    bridge = dict(attempt.get("patched_qe_bridge_evidence") or {})
    dispatch_policy = dict(bridge.get("dispatch_policy") or {})
    speed_policy = dict(bridge.get("speed_measurement_policy") or {})
    payload = dict(bridge.get("accelerated_output_json") or {})
    real_l4 = dict(attempt.get("real_l4_provenance") or {})
    gem5_preflight = dict(real_l4.get("gem5_preflight") or {})
    replacement = dict(attempt.get("accelerated_replacement") or {})
    selected_kernel = str(
        replacement.get("selected_kernel")
        or replacement.get("target_kernel")
        or attempt.get("kernel")
        or ""
    )
    config = {
        "selected_kernel": selected_kernel or None,
        "bridge_invocation_policy": (
            dispatch_policy.get("policy")
            or speed_policy.get("bridge_invocation_policy")
            or "one_gem5_bridge_invocation_per_patched_QE_process"
        ),
        "batched_request_count_per_launch": (
            dispatch_policy.get("batched_request_count_per_launch")
            or speed_policy.get("batched_request_count_per_launch")
        ),
        "persistent_or_batched_dispatch_observed": (
            dispatch_policy.get("persistent_or_batched_dispatch_observed")
            is True
            or speed_policy.get("persistent_or_batched_dispatch_observed") is True
        ),
        "accelerator_numeric_payload_kind": payload.get(
            "accelerator_numeric_payload_kind"
        ),
        "numeric_compute_backend": payload.get("numeric_compute_backend"),
        "numeric_payload_policy": _first_payload_policy_marker(payload),
        "output_buffer_fast_copy_from_qe_input": payload.get(
            "output_buffer_fast_copy_from_qe_input"
        ),
        "driver_binary": gem5_preflight.get("driver_binary"),
    }
    return {
        "replacement_configuration_identity_key": (
            "replacement_config:" + stable_json_hash(config)[:16]
        ),
        "replacement_configuration": config,
    }


def _speed_measurement_summary(attempt: Mapping[str, Any]) -> Dict[str, Any]:
    speed_signal = dict(attempt.get("speed_signal") or {})
    bridge = dict(attempt.get("patched_qe_bridge_evidence") or {})
    baseline_elapsed = bridge.get("baseline_elapsed_seconds")
    patched_elapsed = bridge.get("patched_qe_elapsed_seconds")
    if not isinstance(baseline_elapsed, (int, float)):
        baseline = dict(attempt.get("pure_qe_baseline") or {}).get(
            "baseline_result"
        )
        if isinstance(baseline, Mapping):
            baseline_elapsed = baseline.get("elapsed_seconds")
    speedup = speed_signal.get("speedup_vs_pure_qe")
    speed_delta = None
    if isinstance(baseline_elapsed, (int, float)) and isinstance(
        patched_elapsed, (int, float)
    ):
        speed_delta = float(patched_elapsed) - float(baseline_elapsed)
    gpu_runtime_context = _attempt_gpu_runtime_context(attempt)
    return {
        "speedup_vs_pure_qe": speedup if isinstance(speedup, (int, float)) else None,
        "baseline_elapsed_seconds": (
            float(baseline_elapsed)
            if isinstance(baseline_elapsed, (int, float))
            else None
        ),
        "patched_qe_elapsed_seconds": (
            float(patched_elapsed)
            if isinstance(patched_elapsed, (int, float))
            else None
        ),
        "patched_minus_baseline_seconds": speed_delta,
        "speed_signal_blockers": list(speed_signal.get("blockers") or []),
        "baseline_gpu_available": (
            gpu_runtime_context.get("gpu_available")
            if gpu_runtime_context
            else None
        ),
        "baseline_nvidia_smi_available": (
            gpu_runtime_context.get("nvidia_smi_available")
            if gpu_runtime_context
            else None
        ),
        "baseline_gpu_runtime_context": gpu_runtime_context,
        "claim_boundary": (
            "numeric speed evidence explains not_valuable_l4; positive speed "
            "is still required before valuable_l4; GPU availability is "
            "recorded as baseline context, not as a value claim"
        ),
    }


def build_l4_speed_optimization_report(
    matrix: Mapping[str, Any],
    evidence_rows: Sequence[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Summarize what must change before slow L4 attempts can be valuable."""
    value_by_opp = {
        str(row.get("opportunity_id")): row
        for row in matrix.get("rows", []) or []
        if isinstance(row, Mapping) and row.get("opportunity_id")
    }
    rows: list[Dict[str, Any]] = []
    for attempt in evidence_rows or []:
        if not isinstance(attempt, Mapping) or not attempt.get("opportunity_id"):
            continue
        opportunity_id = str(attempt.get("opportunity_id"))
        matrix_value_row = dict(value_by_opp.get(opportunity_id) or {})
        workload_identity = _attempt_workload_variant_identity(
            attempt,
            matrix_value_row,
        )
        replacement_configuration_identity = (
            _attempt_replacement_configuration_identity(attempt)
        )
        # Recompute the attempt verdict instead of trusting a serialized
        # ``value_verdict`` embedded in older attempt artifacts.  The value
        # gate evolves as anti-downgrade checks are tightened (for example,
        # placeholder numeric payloads that were once accepted must now be
        # rejected), so stale attempt-local verdicts are diagnostic provenance
        # only and must not leak into the current speed/value reports.
        attempt_verdict = dict(classify_l4_offload_value(attempt))
        matrix_label = matrix_value_row.get("value_label")
        if (
            attempt_verdict.get("value_label") == "queued_by_projection"
            and matrix_label
            and matrix_label != "valuable_l4"
        ):
            attempt_verdict["value_label"] = matrix_label
            attempt_verdict["valuable_l4"] = False
        serialized_attempt_verdict = (
            dict(attempt.get("value_verdict") or {})
            if isinstance(attempt.get("value_verdict"), Mapping)
            else {}
        )
        attempt_value_label = (
            attempt_verdict.get("value_label")
            or matrix_value_row.get("value_label")
        )
        attempt_valuable_l4 = attempt_verdict.get("valuable_l4")
        if not isinstance(attempt_valuable_l4, bool):
            matrix_valuable = matrix_value_row.get("valuable_l4")
            attempt_valuable_l4 = (
                matrix_valuable if isinstance(matrix_valuable, bool) else None
            )
        speed = _speed_measurement_summary(attempt)
        speedup = speed.get("speedup_vs_pure_qe")
        baseline_elapsed = speed.get("baseline_elapsed_seconds")
        patched_elapsed = speed.get("patched_qe_elapsed_seconds")
        bridge = dict(attempt.get("patched_qe_bridge_evidence") or {})
        dispatch_policy = dict(bridge.get("dispatch_policy") or {})
        speed_policy = dict(bridge.get("speed_measurement_policy") or {})
        bridge_invocation_policy = str(
            dispatch_policy.get("policy")
            or speed_policy.get("bridge_invocation_policy")
            or "one_gem5_bridge_invocation_per_patched_QE_process"
        )
        gem5_bridge_invocation_count = dispatch_policy.get(
            "gem5_bridge_invocation_count_on_qe_critical_path"
        )
        if not isinstance(gem5_bridge_invocation_count, int):
            gem5_bridge_invocation_count = speed_policy.get(
                "gem5_bridge_invocation_count_on_qe_critical_path"
            )
        if not isinstance(gem5_bridge_invocation_count, int):
            top_level_count = bridge.get("gem5_bridge_invocation_count")
            if isinstance(top_level_count, int):
                gem5_bridge_invocation_count = top_level_count
        if (
            not isinstance(gem5_bridge_invocation_count, int)
            and bridge.get("gem5_returncode") is not None
        ):
            gem5_bridge_invocation_count = 1
        gem5_bridge_launch_count = dispatch_policy.get(
            "gem5_bridge_launch_count_on_qe_critical_path"
        )
        if not isinstance(gem5_bridge_launch_count, int):
            gem5_bridge_launch_count = speed_policy.get(
                "gem5_bridge_launch_count_on_qe_critical_path"
            )
        if not isinstance(gem5_bridge_launch_count, int):
            top_level_launch_count = bridge.get("gem5_bridge_launch_count")
            if isinstance(top_level_launch_count, int):
                gem5_bridge_launch_count = top_level_launch_count
        if (
            not isinstance(gem5_bridge_launch_count, int)
            and bridge.get("gem5_returncode") is not None
        ):
            gem5_bridge_launch_count = 1
        batched_request_count = dispatch_policy.get(
            "batched_request_count_per_launch"
        )
        if not isinstance(batched_request_count, int):
            batched_request_count = speed_policy.get(
                "batched_request_count_per_launch"
            )
        persistent_dispatch_observed = (
            dispatch_policy.get("persistent_or_batched_dispatch_observed")
            is True
            or speed_policy.get("persistent_or_batched_dispatch_observed")
            is True
        )
        required_elapsed = (
            float(baseline_elapsed)
            if isinstance(baseline_elapsed, (int, float))
            else None
        )
        observed_overhead = (
            float(patched_elapsed) - float(baseline_elapsed)
            if isinstance(patched_elapsed, (int, float))
            and isinstance(baseline_elapsed, (int, float))
            else None
        )
        required_elapsed_reduction = (
            max(0.0, float(patched_elapsed) - float(baseline_elapsed))
            if isinstance(patched_elapsed, (int, float))
            and isinstance(baseline_elapsed, (int, float))
            else None
        )
        required_overhead_reduction_fraction = (
            round(float(required_elapsed_reduction) / float(observed_overhead), 6)
            if isinstance(required_elapsed_reduction, (int, float))
            and isinstance(observed_overhead, (int, float))
            and observed_overhead > 0
            else None
        )
        speed_status = (
            "positive"
            if isinstance(speedup, (int, float)) and speedup > 1.0
            else "non_positive"
            if isinstance(speedup, (int, float))
            else "blocked"
        )
        replacement = _accelerated_replacement_summary(attempt)
        replacement_passed = replacement.get("ready_for_value_gate") is True
        persistent_dispatch_required = (
            replacement_passed and speed_status == "non_positive"
            and persistent_dispatch_observed is not True
        )
        replacement_writeback_required = not replacement_passed
        if replacement_passed and speed_status == "positive":
            replacement_gap = (
                "QE consumed the selected-kernel accelerated replacement and "
                "the end-to-end patched QE measurement is faster than the pure "
                "QE baseline; remaining work is value-gate verification, "
                "repeatability, and broader candidate comparison rather than "
                "bridge-overhead reduction."
            )
            replacement_required_action = (
                "candidate has positive speed and strict replacement evidence; "
                "verify correctness/value gates and repeatability"
            )
            non_positive_action = replacement_required_action
        elif replacement_passed and persistent_dispatch_observed:
            replacement_gap = (
                "QE consumed the selected-kernel accelerated replacement and "
                "batched L4 dispatch was observed, but the patched QE path is "
                "still slower than the pure QE baseline; remaining value work "
                "must reduce residual bridge/driver overhead or choose a "
                "larger-granularity target."
            )
            non_positive_action = (
                "batched L4 dispatch is now observed; quantify and reduce the "
                "remaining patched-QE overhead or promote a larger-granularity "
                "offload target before rerunning value classification"
            )
        elif replacement_passed:
            replacement_gap = (
                "QE consumed the selected-kernel accelerated replacement, but "
                "the one-process-per-attempt gem5 bridge launch dominates this "
                "small QE workload; speed value now requires persistent/"
                "batched L4 dispatch or a larger-granularity target."
            )
            non_positive_action = (
                "remove per-attempt gem5 process launch from the QE critical "
                "path or batch multiple selected-kernel replacements, then "
                "rerun value classification"
            )
        else:
            replacement_gap = (
                "positive raw speed was observed, but strict selected-kernel "
                "replacement is still unproven; implement materialized QE "
                "writeback plus software-kernel skip before any value claim"
                if speed_status == "positive"
                else (
                    "current patched bridge continues through pure software "
                    "fallback, so it can prove transport/correctness but adds "
                    "overhead rather than replacing enough QE work"
                )
            )
            replacement_required_action = (
                "implement selected-kernel in-process result materialization "
                "and prove the QE software kernel was removed from the "
                "critical path before treating speed as value evidence"
            )
            non_positive_action = (
                "implement in-process result replacement or a batched "
                "accelerated kernel path before rerunning value classification"
            )
        row = {
            "opportunity_id": opportunity_id,
            "kernel": attempt.get("kernel"),
            **workload_identity,
            **replacement_configuration_identity,
            "source_attempt_artifact": attempt.get("source_attempt_artifact"),
            "value_label": attempt_value_label,
            "valuable_l4": attempt_valuable_l4,
            "serialized_attempt_value_label": serialized_attempt_verdict.get(
                "value_label"
            ),
            "serialized_attempt_valuable_l4": serialized_attempt_verdict.get(
                "valuable_l4"
            ),
            "matrix_value_label": matrix_value_row.get("value_label"),
            "speed_status": speed_status,
            "speedup_vs_pure_qe": speedup,
            "baseline_elapsed_seconds": baseline_elapsed,
            "patched_qe_elapsed_seconds": patched_elapsed,
            "patched_minus_baseline_seconds": observed_overhead,
            "baseline_gpu_available": speed.get("baseline_gpu_available"),
            "baseline_nvidia_smi_available": speed.get(
                "baseline_nvidia_smi_available"
            ),
            "baseline_gpu_runtime_context": speed.get(
                "baseline_gpu_runtime_context", {}
            ),
            "required_patched_elapsed_seconds_for_positive_speed": required_elapsed,
            "required_elapsed_reduction_seconds_for_positive_speed": (
                required_elapsed_reduction
            ),
            "required_bridge_overhead_reduction_fraction": (
                required_overhead_reduction_fraction
            ),
            "bridge_invocation_policy": bridge_invocation_policy,
            "gem5_bridge_invocation_count_on_qe_critical_path": (
                gem5_bridge_invocation_count
            ),
            "gem5_bridge_launch_count_on_qe_critical_path": (
                gem5_bridge_launch_count
            ),
            "batched_request_count_per_launch": batched_request_count,
            "persistent_or_batched_dispatch_observed": (
                persistent_dispatch_observed
            ),
            "replacement_ready": replacement_passed,
            "persistent_or_batched_dispatch_required": (
                persistent_dispatch_required
            ),
            "replacement_writeback_required_before_speed_optimization": (
                replacement_writeback_required
            ),
            "next_engineering_gate": (
                "replacement_capable_qe_writeback"
                if replacement_writeback_required
                else "persistent_or_batched_l4_dispatch"
                if persistent_dispatch_required
                else "verify_value_gate"
                if speed_status == "positive"
                else "resolve_blocked_speed_measurement"
            ),
            "replacement_gap": replacement_gap,
            "recommended_next_action": (
                replacement_required_action
                if replacement_writeback_required
                else non_positive_action
                if speed_status == "non_positive"
                else "resolve speed/correctness blockers before value claim"
                if speed_status == "blocked"
                else "candidate has positive speed; verify all value gates"
            ),
            "claim_boundary": (
                "speed optimization diagnosis only; not a valuable_l4 claim"
            ),
        }
        row["row_hash"] = _stable_hash_without(row, "row_hash")
        rows.append(row)
    rows.sort(
        key=lambda row: (
            -float(row.get("speedup_vs_pure_qe") or -1.0),
            str(row.get("opportunity_id")),
            str(row.get("workload_variant_identity_key")),
            str(row.get("runtime_workload_case_id")),
        )
    )
    positive = [
        row
        for row in rows
        if isinstance(row.get("speedup_vs_pure_qe"), (int, float))
        and float(row["speedup_vs_pure_qe"]) > 1.0
    ]
    non_positive = [
        row
        for row in rows
        if isinstance(row.get("speedup_vs_pure_qe"), (int, float))
        and float(row["speedup_vs_pure_qe"]) <= 1.0
    ]
    blocked = [row for row in rows if row.get("speed_status") == "blocked"]
    replacement_ready_non_positive = [
        row
        for row in rows
        if row.get("replacement_ready") is True
        and row.get("speed_status") == "non_positive"
    ]
    replacement_writeback_required_rows = [
        row
        for row in rows
        if row.get("replacement_writeback_required_before_speed_optimization")
        is True
    ]
    persistent_dispatch_required_rows = [
        row
        for row in rows
        if row.get("persistent_or_batched_dispatch_required") is True
    ]
    best_speedup = (
        max(
            float(row["speedup_vs_pure_qe"])
            for row in rows
            if isinstance(row.get("speedup_vs_pure_qe"), (int, float))
        )
        if any(
            isinstance(row.get("speedup_vs_pure_qe"), (int, float))
            for row in rows
        )
        else None
    )
    replacement_ready_rows = [
        row for row in rows if row.get("replacement_ready") is True
    ]
    best_replacement_ready_speedup = (
        max(
            float(row["speedup_vs_pure_qe"])
            for row in replacement_ready_rows
            if isinstance(row.get("speedup_vs_pure_qe"), (int, float))
        )
        if any(
            isinstance(row.get("speedup_vs_pure_qe"), (int, float))
            for row in replacement_ready_rows
        )
        else None
    )
    gpu_context_rows = [
        row
        for row in rows
        if isinstance(row.get("baseline_gpu_runtime_context"), Mapping)
        and row.get("baseline_gpu_runtime_context")
    ]
    gpu_available_rows = [
        row for row in gpu_context_rows if row.get("baseline_gpu_available") is True
    ]
    payload = {
        "schema_version": "dse.qe_l4_speed_optimization_report.v1",
        "status": (
            "blocked_or_not_valuable"
            if not positive or matrix.get("valuable_l4_count", 0) == 0
            else "positive_speed_candidates_present"
        ),
        "release_id": RELEASE_ID,
        "matrix_hash": matrix.get("matrix_hash"),
        "attempt_count": len(rows),
        "positive_speed_count": len(positive),
        "non_positive_speed_count": len(non_positive),
        "blocked_speed_count": len(blocked),
        "replacement_ready_non_positive_speed_count": len(
            replacement_ready_non_positive
        ),
        "persistent_or_batched_dispatch_required_count": len(
            persistent_dispatch_required_rows
        ),
        "replacement_writeback_required_count": len(
            replacement_writeback_required_rows
        ),
        "best_speedup_vs_pure_qe": best_speedup,
        "best_replacement_ready_speedup_vs_pure_qe": (
            best_replacement_ready_speedup
        ),
        "baseline_gpu_context_observed_count": len(gpu_context_rows),
        "baseline_gpu_available_count": len(gpu_available_rows),
        "valuable_l4_count": matrix.get("valuable_l4_count", 0),
        "bridge_fallback_cannot_claim_value": True,
        "positive_speed_value_claim_allowed": False,
        "deliverable_complete": False,
        "rows": rows,
        "claim_boundary": (
            "diagnoses why L4 attempts are not valuable; real valuable_l4 "
            "still requires gem5/QE L4 correctness, strict replacement, pure "
            "QE baseline, and positive speed"
        ),
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def build_l4_value_repeatability_report(
    speed_report: Mapping[str, Any],
    *,
    min_replacement_ready_samples: int = 2,
) -> Dict[str, Any]:
    """Summarize whether positive value samples repeat for strict replacements.

    ``valuable_l4`` is a row-level value gate.  This repeatability report is a
    stricter follow-up guard so a single borderline positive measurement is not
    silently presented as a stable value claim.
    """

    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in speed_report.get("rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        if row.get("replacement_ready") is not True:
            continue
        opportunity_id = str(row.get("opportunity_id") or "")
        if not opportunity_id:
            continue
        workload_variant_identity_key = str(
            row.get("workload_variant_identity_key")
            or (
                f"workload_variant:{row.get('workload_variant_id')}"
                if row.get("workload_variant_id") not in (None, "")
                else "canonical_workload"
            )
        )
        replacement_configuration_identity_key = str(
            row.get("replacement_configuration_identity_key")
            or f"{workload_variant_identity_key}:replacement_config:unspecified"
        )
        grouped.setdefault(
            (
                opportunity_id,
                workload_variant_identity_key,
                replacement_configuration_identity_key,
            ),
            [],
        ).append(row)

    rows: list[Dict[str, Any]] = []
    for (
        opportunity_id,
        workload_variant_identity_key,
        replacement_configuration_identity_key,
    ), samples in sorted(
        grouped.items()
    ):
        numeric_speedups = [
            float(row["speedup_vs_pure_qe"])
            for row in samples
            if isinstance(row.get("speedup_vs_pure_qe"), (int, float))
        ]
        positive = [value for value in numeric_speedups if value > 1.0]
        non_positive = [value for value in numeric_speedups if value <= 1.0]
        sample_count = len(numeric_speedups)
        valuable_samples = [
            row for row in samples if row.get("value_label") == "valuable_l4"
        ]
        non_valuable_sample_count = len(samples) - len(valuable_samples)
        if (
            positive
            and not non_positive
            and sample_count >= min_replacement_ready_samples
        ):
            speed_repeatability_status = "stable_positive"
            speed_blockers: list[str] = []
        elif positive and non_positive:
            speed_repeatability_status = "mixed_positive_and_non_positive"
            speed_blockers = ["replacement_ready_speed_repeatability_mixed"]
        elif positive:
            speed_repeatability_status = "single_positive_unconfirmed"
            speed_blockers = ["replacement_ready_positive_speed_repeat_missing"]
        elif non_positive:
            speed_repeatability_status = "stable_non_positive"
            speed_blockers = ["replacement_ready_positive_speed_missing"]
        else:
            speed_repeatability_status = "blocked_no_numeric_speed"
            speed_blockers = ["replacement_ready_numeric_speed_missing"]
        if non_valuable_sample_count:
            repeatability_status = "value_gate_not_passed"
            blockers = ["valuable_l4_value_label_missing", *speed_blockers]
        else:
            repeatability_status = speed_repeatability_status
            blockers = list(speed_blockers)
        first = samples[0]
        payload_row = {
            "opportunity_id": opportunity_id,
            "kernel": first.get("kernel"),
            "workload_variant_id": first.get("workload_variant_id"),
            "workload_variant_applied": first.get("workload_variant_applied"),
            "workload_variant_identity_key": workload_variant_identity_key,
            "workload_variant_binding": dict(
                first.get("workload_variant_binding") or {}
            ),
            "replacement_configuration_identity_key": (
                replacement_configuration_identity_key
            ),
            "replacement_configuration": dict(
                first.get("replacement_configuration") or {}
            ),
            "source_attempt_artifacts": _dedupe_strings(
                row.get("source_attempt_artifact") for row in samples
            ),
            "original_workload_case_id": first.get("original_workload_case_id"),
            "runtime_workload_case_id": first.get("runtime_workload_case_id"),
            "value_label": first.get("value_label"),
            "replacement_ready_sample_count": sample_count,
            "min_replacement_ready_samples": min_replacement_ready_samples,
            "valuable_l4_sample_count": len(valuable_samples),
            "non_valuable_l4_sample_count": non_valuable_sample_count,
            "positive_speed_sample_count": len(positive),
            "non_positive_speed_sample_count": len(non_positive),
            "speedups_vs_pure_qe": numeric_speedups,
            "min_speedup_vs_pure_qe": min(numeric_speedups)
            if numeric_speedups
            else None,
            "max_speedup_vs_pure_qe": max(numeric_speedups)
            if numeric_speedups
            else None,
            "speed_repeatability_status": speed_repeatability_status,
            "speed_repeatability_blockers": speed_blockers,
            "repeatability_status": repeatability_status,
            "repeatability_stable_value": repeatability_status == "stable_positive",
            "blockers": blockers,
            "claim_boundary": (
                "repeatability is a follow-up stability guard; first-pass "
                "deliverable_complete remains false"
            ),
        }
        payload_row["row_hash"] = _stable_hash_without(payload_row, "row_hash")
        rows.append(payload_row)

    stable_rows = [
        row for row in rows if row.get("repeatability_stable_value") is True
    ]
    mixed_rows = [
        row
        for row in rows
        if row.get("repeatability_status") == "mixed_positive_and_non_positive"
    ]
    speed_mixed_rows = [
        row
        for row in rows
        if row.get("speed_repeatability_status")
        == "mixed_positive_and_non_positive"
    ]
    single_positive_rows = [
        row
        for row in rows
        if row.get("repeatability_status") == "single_positive_unconfirmed"
    ]
    value_gate_not_passed_rows = [
        row
        for row in rows
        if row.get("repeatability_status") == "value_gate_not_passed"
    ]
    payload = {
        "schema_version": "dse.qe_l4_value_repeatability_report.v1",
        "status": (
            "stable_positive_candidates_present"
            if stable_rows
            else "repeatability_blocked_or_mixed"
        ),
        "release_id": RELEASE_ID,
        "speed_report_hash": speed_report.get("report_hash"),
        "replacement_ready_opportunity_count": len(rows),
        "replacement_ready_identity_count": len(rows),
        "repeatability_stable_valuable_l4_count": len(stable_rows),
        "repeatability_mixed_count": len(mixed_rows),
        "speed_mixed_count": len(speed_mixed_rows),
        "single_positive_unconfirmed_count": len(single_positive_rows),
        "value_gate_not_passed_count": len(value_gate_not_passed_rows),
        "min_replacement_ready_samples": min_replacement_ready_samples,
        "deliverable_complete": False,
        "rows": rows,
        "claim_boundary": (
            "does not downgrade raw valuable_l4 evidence; it prevents a "
            "single or mixed speed sample from being reported as stable value"
        ),
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def build_offload_bundle_viability_report(
    bundle_space: Mapping[str, Any],
    matrix: Mapping[str, Any],
    replacement_report: Mapping[str, Any],
    speed_report: Mapping[str, Any],
    repeatability_report: Mapping[str, Any],
) -> Dict[str, Any]:
    """Join bundle search candidates with real L4 member evidence.

    Bundle search is a DSE decision surface, not a value shortcut.  This report
    prevents a valuable or positive single callsite from being presented as a
    workload-stage/family bundle value claim unless there is explicit
    bundle-level evidence.
    """

    matrix_by_opp = {
        str(row.get("opportunity_id")): row
        for row in matrix.get("rows", []) or []
        if isinstance(row, Mapping) and row.get("opportunity_id")
    }
    replacement_by_opp = {
        str(row.get("opportunity_id")): row
        for row in replacement_report.get("rows", []) or []
        if isinstance(row, Mapping) and row.get("opportunity_id")
    }
    speed_by_opp: dict[str, list[Mapping[str, Any]]] = {}
    for row in speed_report.get("rows", []) or []:
        if isinstance(row, Mapping) and row.get("opportunity_id"):
            speed_by_opp.setdefault(str(row.get("opportunity_id")), []).append(row)
    repeatability_by_opp: dict[str, list[Mapping[str, Any]]] = {}
    for row in repeatability_report.get("rows", []) or []:
        if isinstance(row, Mapping) and row.get("opportunity_id"):
            repeatability_by_opp.setdefault(
                str(row.get("opportunity_id")),
                [],
            ).append(row)

    rows: list[Dict[str, Any]] = []
    for bundle in bundle_space.get("bundles", []) or []:
        if not isinstance(bundle, Mapping):
            continue
        opportunity_ids = [
            str(item) for item in bundle.get("opportunity_ids") or []
        ]
        replacement_rows = [
            replacement_by_opp[opportunity_id]
            for opportunity_id in opportunity_ids
            if opportunity_id in replacement_by_opp
        ]
        matrix_rows = [
            matrix_by_opp[opportunity_id]
            for opportunity_id in opportunity_ids
            if opportunity_id in matrix_by_opp
        ]
        speed_rows = [
            speed_row
            for opportunity_id in opportunity_ids
            for speed_row in speed_by_opp.get(opportunity_id, [])
        ]
        repeatability_rows = [
            repeatability_row
            for opportunity_id in opportunity_ids
            for repeatability_row in repeatability_by_opp.get(opportunity_id, [])
        ]
        attempted_count = sum(
            1
            for row in replacement_rows
            if row.get("real_l4_status") not in (None, "not_attempted")
        )
        replacement_ready_count = sum(
            1 for row in replacement_rows if row.get("ready_for_value_gate") is True
        )
        valuable_member_count = sum(
            1 for row in matrix_rows if row.get("value_label") == "valuable_l4"
        )
        stable_repeatable_member_count = sum(
            1
            for row in repeatability_rows
            if row.get("repeatability_stable_value") is True
        )
        stable_member_configurations = [
            {
                "opportunity_id": str(row.get("opportunity_id") or ""),
                "kernel": row.get("kernel"),
                **_stable_repeatability_summary(row),
            }
            for row in repeatability_rows
            if row.get("repeatability_stable_value") is True
        ]
        positive_blocked_member_count = sum(
            1
            for row in speed_rows
            if isinstance(row.get("speedup_vs_pure_qe"), (int, float))
            and float(row["speedup_vs_pure_qe"]) > 1.0
            and row.get("value_label") != "valuable_l4"
        )
        blockers: list[str] = []
        if not opportunity_ids:
            blockers.append("bundle_has_no_opportunities")
        if bundle.get("hpsi_only") is True:
            blockers.append("hpsi_only_bundle_cannot_complete_first_pass")
        if attempted_count < len(opportunity_ids):
            blockers.append("bundle_member_l4_attempts_incomplete")
        if replacement_ready_count == 0:
            blockers.append("bundle_has_no_replacement_ready_members")
        if valuable_member_count == 0:
            blockers.append("bundle_has_no_valuable_l4_members")
        if stable_repeatable_member_count == 0:
            blockers.append("bundle_has_no_stable_repeatable_value_members")
        if bundle.get("granularity") == "bundle":
            blockers.append("single_workflow_bundle_l4_evidence_missing")
        if positive_blocked_member_count:
            blockers.append("positive_speed_members_still_value_blocked")

        if bundle.get("hpsi_only") is True:
            viability_status = "blocked_hpsi_only"
        elif stable_repeatable_member_count:
            viability_status = "has_stable_member_but_bundle_unproven"
        elif valuable_member_count:
            viability_status = "has_raw_valuable_member_but_bundle_unproven"
        elif positive_blocked_member_count:
            viability_status = "positive_members_blocked"
        elif attempted_count:
            viability_status = "attempted_members_not_valuable_or_blocked"
        else:
            viability_status = "queued_by_projection"

        runnable_as_single_qe_workflow = (
            bundle.get("runnable_as_single_qe_workflow") is True
        )
        bundle_execution_policy = bundle.get("bundle_execution_policy")
        if (
            bundle.get("granularity") == "bundle"
            and runnable_as_single_qe_workflow
            and stable_member_configurations
        ):
            recommended_next_action = (
                "run a single-workflow multi-callsite actual_compute L4 "
                "bundle attempt seeded by the stable member configuration; "
                "bundle value remains blocked until the full workflow proves "
                "QE consumed accelerated outputs, skipped selected software "
                "work, passed correctness, and has positive speed"
            )
        elif bundle.get("granularity") == "bundle" and stable_member_configurations:
            recommended_next_action = (
                "define a runnable single-QE-workflow bundle harness before "
                "attempting bundle-level value; stable member evidence is a "
                "seed only"
            )
        elif stable_member_configurations:
            recommended_next_action = (
                "promote this stable callsite configuration into a larger "
                "workload-stage bundle candidate; do not upgrade member value "
                "to bundle value"
            )
        elif valuable_member_count:
            recommended_next_action = (
                "repeat raw valuable member samples under a stable replacement "
                "configuration before bundle promotion"
            )
        else:
            recommended_next_action = (
                "run real non-smoke full-QE L4 attempts for bundle members, "
                "then re-evaluate bundle viability"
            )

        row = {
            "bundle_id": bundle.get("bundle_id"),
            "classification": bundle.get("classification"),
            "granularity": bundle.get("granularity"),
            "workload_case_id": bundle.get("workload_case_id"),
            "stage_type": bundle.get("stage_type"),
            "bundle_execution_policy": bundle_execution_policy,
            "runnable_as_single_qe_workflow": runnable_as_single_qe_workflow,
            "selection_priority": dict(bundle.get("selection_priority") or {}),
            "bundle_priority_score": dict(
                bundle.get("selection_priority") or {}
            ).get("score"),
            "kernel_list": list(bundle.get("kernel_list") or []),
            "kernel_families": list(bundle.get("kernel_families") or []),
            "opportunity_ids": opportunity_ids,
            "hpsi_only": bundle.get("hpsi_only") is True,
            "opportunity_count": len(opportunity_ids),
            "attempted_member_count": attempted_count,
            "replacement_ready_member_count": replacement_ready_count,
            "valuable_l4_member_count": valuable_member_count,
            "stable_repeatable_value_member_count": stable_repeatable_member_count,
            "stable_repeatable_value_member_opportunity_ids": _dedupe_strings(
                row.get("opportunity_id") for row in stable_member_configurations
            ),
            "stable_repeatable_member_configurations": (
                stable_member_configurations
            ),
            "positive_speed_value_blocked_member_count": positive_blocked_member_count,
            "bundle_value_allowed": False,
            "viability_status": viability_status,
            "recommended_next_action": recommended_next_action,
            "blockers": _dedupe_strings(blockers),
            "claim_boundary": (
                "bundle viability report only; member evidence cannot be "
                "upgraded to bundle-level value without explicit full-QE "
                "single-workflow bundle L4 correctness/replacement/speed "
                "evidence"
            ),
        }
        row["row_hash"] = _stable_hash_without(row, "row_hash")
        rows.append(row)

    bundle_rows = [row for row in rows if row.get("granularity") == "bundle"]
    raw_member_rows = [
        row
        for row in rows
        if row.get("valuable_l4_member_count", 0) > 0
    ]
    stable_member_rows = [
        row
        for row in rows
        if row.get("stable_repeatable_value_member_count", 0) > 0
    ]
    runnable_stable_bundle_rows = [
        row
        for row in rows
        if row.get("granularity") == "bundle"
        and row.get("runnable_as_single_qe_workflow") is True
        and row.get("stable_repeatable_value_member_count", 0) > 0
    ]
    payload = {
        "schema_version": "dse.qe_offload_bundle_viability_report.v1",
        "status": (
            "bundle_value_unproven"
            if rows
            else "blocked_no_bundle_candidates"
        ),
        "release_id": RELEASE_ID,
        "bundle_search_space_hash": bundle_space.get("search_space_hash"),
        "matrix_hash": matrix.get("matrix_hash"),
        "replacement_report_hash": replacement_report.get("report_hash"),
        "speed_report_hash": speed_report.get("report_hash"),
        "repeatability_report_hash": repeatability_report.get("report_hash"),
        "bundle_count": len(rows),
        "larger_granularity_bundle_count": len(bundle_rows),
        "bundles_with_raw_valuable_members_count": len(raw_member_rows),
        "bundles_with_stable_repeatable_members_count": len(stable_member_rows),
        "single_workflow_bundle_candidates_with_stable_members_count": len(
            runnable_stable_bundle_rows
        ),
        "stable_repeatable_member_configuration_count": sum(
            len(row.get("stable_repeatable_member_configurations") or [])
            for row in rows
        ),
        "bundle_level_valuable_l4_count": 0,
        "deliverable_complete": False,
        "rows": rows,
        "claim_boundary": (
            "DSE may rank workload/callsite/family bundles, but bundle-level "
            "valuable_l4 remains blocked until a real non-smoke full-QE "
            "bundle workflow passes the same L4 gates"
        ),
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def build_bundle_single_workflow_l4_evidence_report(
    bundle_space: Mapping[str, Any],
    campaign_statuses: Sequence[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Gate bundle-level value on explicit single-QE-workflow evidence.

    A DSE campaign may select a bundle and expand it into per-opportunity L4
    attempts.  That is useful search evidence, but it is not the same as one QE
    workflow executing multiple offloaded call sites in a single run.  This
    report makes that boundary machine-visible so an expanded campaign cannot
    be mistaken for bundle-level ``valuable_l4``.
    """

    statuses = [
        dict(status)
        for status in (campaign_statuses or [])
        if isinstance(status, Mapping)
    ]
    statuses_by_bundle: dict[str, list[dict[str, Any]]] = {}
    for status in statuses:
        for bundle_id in status.get("selected_bundle_ids", []) or []:
            statuses_by_bundle.setdefault(str(bundle_id), []).append(status)

    def _bundle_speed_repeatability_summary(
        bundle_statuses: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        speedups: list[float] = []
        speed_statuses: list[str] = []
        status_paths: list[str] = []
        for status in bundle_statuses:
            speed_signal = status.get("speed_signal")
            if not isinstance(speed_signal, Mapping):
                speed_signal = {}
            raw_speedup = speed_signal.get("speedup_vs_pure_qe")
            if isinstance(raw_speedup, (int, float)):
                speedups.append(float(raw_speedup))
                speed_statuses.append(str(speed_signal.get("status") or "unknown"))
                if status.get("status_path"):
                    status_paths.append(str(status.get("status_path")))
        positive_count = sum(1 for value in speedups if value > 1.0)
        non_positive_count = sum(1 for value in speedups if value <= 1.0)
        blockers: list[str] = []
        if not speedups:
            repeatability_status = "no_speed_samples"
            blockers.append("bundle_speed_samples_missing")
        elif positive_count and non_positive_count:
            repeatability_status = "mixed"
            blockers.append("bundle_speed_repeatability_mixed")
        elif positive_count == len(speedups):
            repeatability_status = (
                "stable_positive" if len(speedups) >= 2 else "single_positive"
            )
            if len(speedups) < 2:
                blockers.append("bundle_positive_speed_single_sample_only")
        else:
            repeatability_status = "stable_non_positive"
            blockers.append("bundle_positive_speed_missing")
        return {
            "bundle_speed_sample_count": len(speedups),
            "bundle_speedups_vs_pure_qe": speedups,
            "bundle_speed_statuses": speed_statuses,
            "bundle_positive_speed_sample_count": positive_count,
            "bundle_non_positive_speed_sample_count": non_positive_count,
            "bundle_speed_repeatability_status": repeatability_status,
            "bundle_speed_repeatability_blockers": _dedupe_strings(blockers),
            "bundle_speed_sample_status_paths": status_paths,
            "claim_boundary": (
                "bundle speed repeatability is a stability guard; it does not "
                "downgrade a valid single-run bundle value row, but it blocks "
                "stable bundle-value wording while samples are mixed"
            ),
        }

    rows: list[Dict[str, Any]] = []
    for bundle in bundle_space.get("bundles", []) or []:
        if not isinstance(bundle, Mapping):
            continue
        bundle_id = str(bundle.get("bundle_id") or "")
        if not bundle_id:
            continue
        bundle_statuses = statuses_by_bundle.get(bundle_id, [])
        speed_repeatability = _bundle_speed_repeatability_summary(bundle_statuses)
        latest_status = (
            max(
                bundle_statuses,
                key=lambda status: (
                    (
                        (
                            status.get("bundle_level_valuable_l4") is True
                            or status.get("bundle_valuable_l4") is True
                        )
                        and status.get("single_qe_workflow_proven") is True
                    ),
                    status.get("single_qe_workflow_proven") is True,
                    status.get("bundle_level_valuable_l4") is True
                    or status.get("bundle_valuable_l4") is True,
                    status.get("single_qe_workflow_covers_full_bundle") is not False,
                    int(status.get("actual_compute_full_qe_evidence_passed_count") or 0),
                    int(status.get("non_smoke_actual_compute_attempt_count") or 0),
                    int(status.get("attempted_count") or 0),
                    str(status.get("status_path") or ""),
                ),
            )
            if bundle_statuses
            else {}
        )
        attempted_count = int(latest_status.get("attempted_count") or 0)
        expanded_count = int(
            latest_status.get("selected_bundle_expanded_opportunity_count") or 0
        )
        non_smoke_actual_count = int(
            latest_status.get("non_smoke_actual_compute_attempt_count") or 0
        )
        actual_compute_passed_count = int(
            latest_status.get("actual_compute_full_qe_evidence_passed_count") or 0
        )
        member_value_count = int(latest_status.get("valuable_l4_count") or 0)
        single_workflow_proven = latest_status.get("single_qe_workflow_proven") is True
        full_bundle_covered = (
            latest_status.get("single_qe_workflow_covers_full_bundle") is not False
        )
        per_opportunity_expanded = (
            bool(bundle_statuses)
            and expanded_count > 1
            and attempted_count >= expanded_count
            and single_workflow_proven is False
        )
        bundle_level_value_claimed = (
            latest_status.get("bundle_level_valuable_l4") is True
            or latest_status.get("bundle_valuable_l4") is True
        )

        blockers: list[str] = []
        if bundle.get("granularity") != "bundle":
            blockers.append("not_larger_granularity_bundle")
        if bundle.get("hpsi_only") is True:
            blockers.append("hpsi_only_bundle_cannot_complete_first_pass")
        if not bundle_statuses:
            blockers.append("bundle_single_workflow_l4_evidence_missing")
        if per_opportunity_expanded:
            blockers.append("per_opportunity_expanded_campaign_not_single_qe_workflow")
        if not single_workflow_proven:
            blockers.append("single_qe_workflow_not_proven")
        if single_workflow_proven and not full_bundle_covered:
            blockers.append("single_qe_workflow_does_not_cover_full_bundle")
        if non_smoke_actual_count <= 0:
            blockers.append("non_smoke_bundle_actual_compute_missing")
        if actual_compute_passed_count <= 0:
            blockers.append("bundle_actual_compute_full_qe_evidence_not_passed")
        if member_value_count <= 0:
            blockers.append("bundle_member_valuable_l4_missing")
        if bundle_level_value_claimed and not single_workflow_proven:
            blockers.append("bundle_value_claim_without_single_workflow_proof")

        bundle_level_valuable_l4 = (
            bundle_level_value_claimed
            and single_workflow_proven
            and full_bundle_covered
            and non_smoke_actual_count > 0
            and actual_compute_passed_count > 0
            and not per_opportunity_expanded
            and "hpsi_only_bundle_cannot_complete_first_pass" not in blockers
        )
        if not bundle_level_valuable_l4 and bundle_level_value_claimed:
            blockers.append("bundle_level_value_claim_rejected")

        row = {
            "bundle_id": bundle_id,
            "classification": bundle.get("classification"),
            "granularity": bundle.get("granularity"),
            "workload_case_id": bundle.get("workload_case_id"),
            "stage_type": bundle.get("stage_type"),
            "opportunity_ids": list(bundle.get("opportunity_ids") or []),
            "kernel_list": list(bundle.get("kernel_list") or []),
            "hpsi_only": bundle.get("hpsi_only") is True,
            "campaign_status_count": len(bundle_statuses),
            "campaign_status_paths": [
                str(status.get("status_path"))
                for status in bundle_statuses
                if status.get("status_path")
            ],
            "single_qe_workflow_proven": single_workflow_proven,
            "single_qe_workflow_covers_full_bundle": full_bundle_covered,
            "per_opportunity_expanded_campaign_observed": per_opportunity_expanded,
            "attempted_member_count": attempted_count,
            "selected_bundle_expanded_opportunity_count": expanded_count,
            "non_smoke_actual_compute_attempt_count": non_smoke_actual_count,
            "actual_compute_full_qe_evidence_passed_count": (
                actual_compute_passed_count
            ),
            "member_valuable_l4_count": member_value_count,
            "bundle_level_valuable_l4": bundle_level_valuable_l4,
            "bundle_value_allowed": bundle_level_valuable_l4,
            **speed_repeatability,
            "blockers": _dedupe_strings(blockers),
            "claim_boundary": (
                "bundle-level value requires one non-smoke full-QE workflow "
                "that proves all selected bundle callsites used accelerated "
                "replacement outputs; per-opportunity expanded campaigns are "
                "search evidence only"
            ),
        }
        row["row_hash"] = _stable_hash_without(row, "row_hash")
        rows.append(row)

    valuable_rows = [
        row for row in rows if row.get("bundle_level_valuable_l4") is True
    ]
    mixed_speed_rows = [
        row for row in rows if row.get("bundle_speed_repeatability_status") == "mixed"
    ]
    stable_positive_speed_rows = [
        row
        for row in rows
        if row.get("bundle_speed_repeatability_status") == "stable_positive"
    ]
    expanded_rows = [
        row
        for row in rows
        if row.get("per_opportunity_expanded_campaign_observed") is True
    ]
    payload = {
        "schema_version": "dse.qe_bundle_single_workflow_l4_evidence_report.v1",
        "status": (
            "bundle_value_proven"
            if valuable_rows
            else (
                "bundle_value_unproven"
                if rows
                else "blocked_no_bundle_candidates"
            )
        ),
        "release_id": RELEASE_ID,
        "bundle_search_space_hash": bundle_space.get("search_space_hash"),
        "bundle_count": len(rows),
        "campaign_status_count": len(statuses),
        "per_opportunity_expanded_campaign_bundle_count": len(expanded_rows),
        "bundle_level_valuable_l4_count": len(valuable_rows),
        "bundle_speed_repeatability_mixed_count": len(mixed_speed_rows),
        "bundle_speed_repeatability_stable_positive_count": len(
            stable_positive_speed_rows
        ),
        "deliverable_complete": False,
        "rows": rows,
        "claim_boundary": (
            "this is a bundle-level anti-downgrade gate; it cannot complete "
            "the first pass and rejects member/campaign evidence unless a "
            "single QE workflow proves bundle-level actual compute"
        ),
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def _default_bundle_runtime_capabilities() -> Dict[str, Any]:
    return {
        "contract_artifact_present": True,
        "runtime_contract_schema": BUNDLE_RUNTIME_CONTRACT_SCHEMA,
        "bundle_runtime_manifest_env": "QE_OFFLOAD_BUNDLE_RUNTIME_MANIFEST",
        "multi_kernel_selector_env": "QE_OFFLOAD_BUNDLE_TARGETS",
        "bridge_command_env": "QE_OFFLOAD_BRIDGE_COMMAND",
        "bridge_kernel_selector": "QE_OFFLOAD_BRIDGE_KERNEL",
        "accelerated_output_json_slots": 1,
        "accelerated_output_data_slots": 1,
        "legacy_single_kernel_selector": "QE_OFFLOAD_BRIDGE_KERNEL",
        "legacy_single_output_json_slot": "QE_OFFLOAD_ACCELERATED_OUTPUT_JSON",
        "legacy_single_output_data_slot": "QE_OFFLOAD_ACCELERATED_OUTPUT_DATA",
        "supports_bundle_runtime_manifest": False,
        "supports_single_target_bundle_runtime_manifest_alias": True,
        "supports_multi_kernel_selector": False,
        "supports_multi_output_slots": False,
        "supports_per_callsite_l4_provenance_slots": False,
        "supports_single_qe_workflow_multi_callsite_bundle": False,
        "claim_boundary": (
            "capabilities describe whether the QE/gem5 runtime can execute a "
            "single QE workflow with multiple offloaded callsites; this is "
            "readiness metadata, not actual-compute value evidence"
        ),
    }


def _coerce_bundle_runtime_capabilities(
    runtime_capabilities: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return normalized bundle-runtime capabilities.

    Callers may pass either a raw capability mapping or a full
    ``build_bundle_runtime_contract_report`` payload.  Missing fields default
    to the current single-kernel runtime so readiness stays blocked unless
    explicit multi-kernel support is supplied.
    """

    runtime = _default_bundle_runtime_capabilities()
    if isinstance(runtime_capabilities, Mapping):
        source = runtime_capabilities
        if isinstance(runtime_capabilities.get("runtime_capabilities"), Mapping):
            source = runtime_capabilities["runtime_capabilities"]
            runtime["contract_report_hash"] = runtime_capabilities.get("report_hash")
            runtime["contract_report_schema"] = runtime_capabilities.get(
                "schema_version"
            )
            runtime["contract_report_status"] = runtime_capabilities.get("status")
        runtime.update(dict(source))
    return runtime


def _bundle_runtime_target_rows(
    bundle: Mapping[str, Any],
    opportunity_by_id: Mapping[str, Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    opportunity_ids = [str(item) for item in bundle.get("opportunity_ids") or []]
    bundle_kernels = [str(item) for item in bundle.get("kernel_list") or []]
    kernel_occurrences: Dict[str, int] = {}
    for opportunity_id in opportunity_ids:
        opportunity = opportunity_by_id.get(opportunity_id, {})
        kernel = str(
            opportunity.get("kernel")
            or (
                bundle_kernels[opportunity_ids.index(opportunity_id)]
                if opportunity_ids.index(opportunity_id) < len(bundle_kernels)
                else ""
            )
            or "unknown"
        )
        kernel_occurrences[kernel] = kernel_occurrences.get(kernel, 0) + 1

    rows: list[Dict[str, Any]] = []
    for index, opportunity_id in enumerate(opportunity_ids):
        opportunity = opportunity_by_id.get(opportunity_id, {})
        kernel = str(
            opportunity.get("kernel")
            or (bundle_kernels[index] if index < len(bundle_kernels) else "")
            or "unknown"
        )
        kernel_suffix = _env_suffix(kernel)
        unique_suffix = _env_suffix(
            f"{kernel}_{stable_json_hash([bundle.get('bundle_id'), opportunity_id])[:8]}"
        )
        kernel_slot_unique = kernel_occurrences.get(kernel, 0) == 1
        row = {
            "target_index": index,
            "opportunity_id": opportunity_id,
            "kernel": kernel,
            "callsite_id": str(
                opportunity.get("callsite_id")
                or opportunity_id.replace("opp_", "callsite_", 1)
            ),
            "selector_token": f"{opportunity_id}:{kernel}",
            "manifest_target_key": opportunity_id,
            "kernel_slot_envs": {
                "bridge_command": f"QE_OFFLOAD_BRIDGE_COMMAND_{kernel_suffix}",
                "accelerated_input_json": (
                    f"QE_OFFLOAD_ACCELERATED_INPUT_JSON_{kernel_suffix}"
                ),
                "accelerated_input_data": (
                    f"QE_OFFLOAD_ACCELERATED_INPUT_DATA_{kernel_suffix}"
                ),
                "accelerated_output_json": (
                    f"QE_OFFLOAD_ACCELERATED_OUTPUT_JSON_{kernel_suffix}"
                ),
                "accelerated_output_data": (
                    f"QE_OFFLOAD_ACCELERATED_OUTPUT_DATA_{kernel_suffix}"
                ),
                "kernel_evidence_json": (
                    f"QE_OFFLOAD_KERNEL_EVIDENCE_JSON_{kernel_suffix}"
                ),
                "provenance_json": (
                    f"QE_OFFLOAD_PROVENANCE_JSON_{kernel_suffix}"
                ),
            },
            "callsite_slot_envs": {
                "bridge_command": f"QE_OFFLOAD_BRIDGE_COMMAND_{unique_suffix}",
                "accelerated_input_json": (
                    f"QE_OFFLOAD_ACCELERATED_INPUT_JSON_{unique_suffix}"
                ),
                "accelerated_input_data": (
                    f"QE_OFFLOAD_ACCELERATED_INPUT_DATA_{unique_suffix}"
                ),
                "accelerated_output_json": (
                    f"QE_OFFLOAD_ACCELERATED_OUTPUT_JSON_{unique_suffix}"
                ),
                "accelerated_output_data": (
                    f"QE_OFFLOAD_ACCELERATED_OUTPUT_DATA_{unique_suffix}"
                ),
                "kernel_evidence_json": (
                    f"QE_OFFLOAD_KERNEL_EVIDENCE_JSON_{unique_suffix}"
                ),
                "provenance_json": (
                    f"QE_OFFLOAD_PROVENANCE_JSON_{unique_suffix}"
                ),
            },
            "kernel_slot_envs_unique_within_bundle": kernel_slot_unique,
            "required_provenance_markers": [
                "bridge_invoked",
                "trusted_l4_replacement_consumed",
                "accelerated_output_materialized",
                "qe_software_kernel_execution_not_skipped",
            ],
            "claim_boundary": (
                "target slot contract only; each target still needs real "
                "non-smoke QE/gem5 actual-compute correctness and speed"
            ),
        }
        row["target_hash"] = _stable_hash_without(row, "target_hash")
        rows.append(row)
    return rows


def build_bundle_runtime_contract_report(
    bundle_space: Mapping[str, Any],
    opportunity_manifest: Mapping[str, Any] | None = None,
    runtime_capabilities: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Define the multi-kernel runtime contract required by bundle harnesses.

    This report is deliberately *not* value evidence.  It records the contract
    that a true single-QE-workflow bundle run must satisfy: one authoritative
    manifest/selector can address multiple callsites, and each callsite has
    independent input/output/provenance slots.  The default capability payload
    represents the current single-kernel bridge, so readiness remains blocked
    until implementation supplies explicit multi-kernel support.
    """

    opportunities = [
        row
        for row in (opportunity_manifest or {}).get("opportunities", []) or []
        if isinstance(row, Mapping)
    ]
    opportunity_by_id = {
        str(row.get("opportunity_id")): row
        for row in opportunities
        if row.get("opportunity_id")
    }
    runtime = _coerce_bundle_runtime_capabilities(runtime_capabilities)
    rows: list[Dict[str, Any]] = []
    for bundle in bundle_space.get("bundles", []) or []:
        if not isinstance(bundle, Mapping) or not bundle.get("bundle_id"):
            continue
        opportunity_ids = [str(item) for item in bundle.get("opportunity_ids") or []]
        target_rows = _bundle_runtime_target_rows(bundle, opportunity_by_id)
        requires_bundle_contract = (
            bundle.get("granularity") == "bundle" and len(opportunity_ids) > 1
        )
        blockers: list[str] = []
        if bundle.get("granularity") != "bundle":
            blockers.append("not_larger_granularity_bundle")
        if len(opportunity_ids) <= 1:
            blockers.append("single_opportunity_does_not_need_bundle_runtime")
        if requires_bundle_contract:
            if runtime.get("supports_bundle_runtime_manifest") is not True:
                blockers.append("bundle_runtime_manifest_not_implemented")
            if runtime.get("supports_multi_kernel_selector") is not True:
                blockers.append("runtime_bridge_multi_kernel_selector_not_implemented")
            if runtime.get("supports_multi_output_slots") is not True:
                blockers.append("runtime_bridge_multi_output_slots_not_implemented")
            if runtime.get("supports_per_callsite_l4_provenance_slots") is not True:
                blockers.append("per_callsite_l4_provenance_slots_not_implemented")
            if (
                runtime.get("supports_single_qe_workflow_multi_callsite_bundle")
                is not True
            ):
                blockers.append(
                    "single_qe_workflow_multi_callsite_runtime_not_implemented"
                )

        selector_tokens = [
            str(row.get("selector_token"))
            for row in target_rows
            if row.get("selector_token")
        ]
        row = {
            "bundle_id": str(bundle["bundle_id"]),
            "classification": bundle.get("classification"),
            "granularity": bundle.get("granularity"),
            "workload_case_id": bundle.get("workload_case_id"),
            "stage_type": bundle.get("stage_type"),
            "opportunity_ids": opportunity_ids,
            "kernel_list": list(bundle.get("kernel_list") or []),
            "requires_bundle_runtime_contract": requires_bundle_contract,
            "bundle_runtime_manifest_env": runtime.get(
                "bundle_runtime_manifest_env"
            ),
            "multi_kernel_selector_env": runtime.get("multi_kernel_selector_env"),
            "multi_kernel_selector_value": ",".join(selector_tokens),
            "legacy_single_kernel_selector": runtime.get(
                "legacy_single_kernel_selector"
            ),
            "legacy_single_output_slots": [
                runtime.get("legacy_single_output_json_slot"),
                runtime.get("legacy_single_output_data_slot"),
            ],
            "runtime_capabilities": runtime,
            "target_slots": target_rows,
            "runtime_contract_ready": requires_bundle_contract and not blockers,
            "blockers": _dedupe_strings(blockers),
            "claim_boundary": (
                "runtime contract/readiness only; does not prove QE consumed "
                "accelerated replacements and cannot mark a bundle valuable_l4"
            ),
        }
        row["row_hash"] = _stable_hash_without(row, "row_hash")
        rows.append(row)

    required_rows = [
        row for row in rows if row.get("requires_bundle_runtime_contract") is True
    ]
    ready_rows = [
        row for row in required_rows if row.get("runtime_contract_ready") is True
    ]
    payload = {
        "schema_version": BUNDLE_RUNTIME_CONTRACT_SCHEMA,
        "status": (
            "runtime_contract_implemented"
            if ready_rows
            else (
                "blocked_no_multi_callsite_bundle_candidates"
                if not required_rows
                else "runtime_contract_defined_runtime_unimplemented"
            )
        ),
        "release_id": RELEASE_ID,
        "bundle_search_space_hash": bundle_space.get("search_space_hash"),
        "opportunity_manifest_hash": (
            opportunity_manifest or {}
        ).get("manifest_hash"),
        "bundle_count": len(rows),
        "multi_callsite_bundle_count": len(required_rows),
        "runtime_contract_ready_bundle_count": len(ready_rows),
        "runtime_capabilities": runtime,
        "manifest_schema": {
            "env": runtime.get("bundle_runtime_manifest_env"),
            "schema_version": "qe.offload.bundle_runtime_manifest.v1",
            "required_fields": [
                "bundle_id",
                "targets[].opportunity_id",
                "targets[].kernel",
                "targets[].bridge_command",
                "targets[].accelerated_input_json",
                "targets[].accelerated_input_data",
                "targets[].accelerated_output_json",
                "targets[].accelerated_output_data",
                "targets[].kernel_evidence_json",
                "targets[].provenance_json",
            ],
            "selector_env_fallback": runtime.get("multi_kernel_selector_env"),
            "selector_token_format": "opportunity_id:kernel",
            "legacy_single_kernel_env": runtime.get(
                "legacy_single_kernel_selector"
            ),
            "legacy_single_output_slots": [
                runtime.get("legacy_single_output_json_slot"),
                runtime.get("legacy_single_output_data_slot"),
            ],
        },
        "deliverable_complete": False,
        "claim_boundary": (
            "contract artifact for future true bundle harnesses; it is not "
            "smoke, not actual-compute evidence, and not a value claim"
        ),
        "rows": rows,
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def build_bundle_harness_readiness_report(
    bundle_space: Mapping[str, Any],
    patch_manifest: Mapping[str, Any],
    runtime_capabilities: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Describe what blocks a true multi-callsite single-QE-workflow harness."""

    runtime = _coerce_bundle_runtime_capabilities(runtime_capabilities)
    patch_rows = [
        row
        for row in patch_manifest.get("patch_rows", []) or []
        if isinstance(row, Mapping)
    ]
    patch_by_bundle = {
        str(row.get("bundle_id")): row
        for row in patch_rows
        if row.get("bundle_id")
    }
    rows: list[Dict[str, Any]] = []
    for bundle in bundle_space.get("bundles", []) or []:
        if not isinstance(bundle, Mapping) or not bundle.get("bundle_id"):
            continue
        bundle_id = str(bundle["bundle_id"])
        opportunity_ids = [str(item) for item in bundle.get("opportunity_ids") or []]
        patch_row = patch_by_bundle.get(bundle_id, {})
        caps = (
            dict(patch_row.get("instrumentation_capabilities") or {})
            if isinstance(patch_row, Mapping)
            else {}
        )
        changed_files = [
            str(item) for item in patch_row.get("changed_files", []) or []
        ] if isinstance(patch_row, Mapping) else []
        missing_declared_patch_files = [
            str(item)
            for item in caps.get("missing_declared_patch_files", []) or []
        ]
        blockers: list[str] = []
        if bundle.get("granularity") != "bundle":
            blockers.append("not_larger_granularity_bundle")
        if not patch_row:
            blockers.append("bundle_patch_manifest_row_missing")
        if missing_declared_patch_files:
            blockers.append("bundle_patch_file_missing")
        if len(opportunity_ids) > 1:
            if runtime.get("supports_multi_kernel_selector") is not True:
                blockers.append("runtime_bridge_single_kernel_selector")
            if runtime.get("supports_multi_output_slots") is not True:
                blockers.append("runtime_bridge_single_output_slot")
            if (
                runtime.get("supports_single_qe_workflow_multi_callsite_bundle")
                is not True
            ):
                blockers.append("single_qe_workflow_multi_callsite_runtime_missing")
        if caps.get("runtime_replacement_evidence_hook_present") is not True:
            blockers.append("runtime_replacement_evidence_hook_missing")
        if caps.get("generic_bridge_hook_present") is not True:
            blockers.append("generic_bridge_hook_missing")
        if caps.get("accelerated_result_writeback_present") is not True:
            blockers.append("accelerated_result_writeback_missing")
        if caps.get("trusted_l4_replacement_precheck_passed") is not True:
            blockers.append("trusted_l4_replacement_precheck_not_passed")

        row = {
            "bundle_id": bundle_id,
            "classification": bundle.get("classification"),
            "granularity": bundle.get("granularity"),
            "workload_case_id": bundle.get("workload_case_id"),
            "stage_type": bundle.get("stage_type"),
            "opportunity_ids": opportunity_ids,
            "kernel_list": list(bundle.get("kernel_list") or []),
            "opportunity_count": len(opportunity_ids),
            "patch_manifest_row_present": bool(patch_row),
            "changed_files": changed_files,
            "missing_declared_patch_files": missing_declared_patch_files,
            "instrumentation_capabilities": caps,
            "runtime_capabilities": runtime,
            "ready_for_single_workflow_bundle_harness": not blockers,
            "blockers": _dedupe_strings(blockers),
            "claim_boundary": (
                "readiness only; a ready harness still needs a non-smoke "
                "single-QE-workflow L4 actual-compute run before any bundle "
                "value claim"
            ),
        }
        row["row_hash"] = _stable_hash_without(row, "row_hash")
        rows.append(row)

    ready_rows = [
        row
        for row in rows
        if row.get("ready_for_single_workflow_bundle_harness") is True
    ]
    payload = {
        "schema_version": "dse.qe_bundle_harness_readiness_report.v1",
        "status": (
            "ready"
            if ready_rows
            else (
                "blocked_no_bundle_candidates"
                if not rows
                else "blocked"
            )
        ),
        "release_id": RELEASE_ID,
        "bundle_search_space_hash": bundle_space.get("search_space_hash"),
        "patch_manifest_hash": patch_manifest.get("manifest_hash"),
        "bundle_count": len(rows),
        "ready_bundle_harness_count": len(ready_rows),
        "blocked_bundle_harness_count": len(rows) - len(ready_rows),
        "deliverable_complete": False,
        "rows": rows,
        "claim_boundary": (
            "readiness report for true bundle harness implementation; it is "
            "not QE/gem5 value evidence and cannot complete the first pass"
        ),
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def materialize_qe_bundle_patch_files(
    bundle_space: Mapping[str, Any],
    *,
    patch_dir: Path | str = Path("patches/qe_callsite_offload_hooks"),
    overwrite: bool = True,
) -> Dict[str, Any]:
    """Write bundle patch files as concatenations of member callsite patches."""

    patch_root = Path(patch_dir)
    rows: list[Dict[str, Any]] = []
    for bundle in bundle_space.get("bundles", []) or []:
        if not isinstance(bundle, Mapping) or not bundle.get("bundle_id"):
            continue
        bundle_id = str(bundle["bundle_id"])
        opportunity_ids = [str(item) for item in bundle.get("opportunity_ids") or []]
        bundle_patch_path = patch_root / f"{bundle_id}.patch"
        member_patch_paths = [patch_root / f"{opportunity_id}.patch" for opportunity_id in opportunity_ids]
        missing_member_patches = [
            str(path) for path in member_patch_paths if not path.exists()
        ]
        blockers: list[str] = []
        if not opportunity_ids:
            blockers.append("bundle_has_no_opportunities")
        if missing_member_patches:
            blockers.append("member_patch_file_missing")
        wrote = False
        if not blockers and (overwrite or not bundle_patch_path.exists()):
            bundle_patch_path.parent.mkdir(parents=True, exist_ok=True)
            combined = "\n\n".join(
                path.read_text(encoding="utf-8").rstrip()
                for path in member_patch_paths
            )
            bundle_patch_path.write_text(combined + "\n", encoding="utf-8")
            wrote = True
        row = {
            "bundle_id": bundle_id,
            "bundle_patch_path": str(bundle_patch_path),
            "opportunity_ids": opportunity_ids,
            "member_patch_paths": [str(path) for path in member_patch_paths],
            "missing_member_patches": missing_member_patches,
            "materialized": bundle_patch_path.exists() and not blockers,
            "wrote": wrote,
            "blockers": _dedupe_strings(blockers),
            "claim_boundary": (
                "bundle patch file is a composed source-patch artifact only; "
                "it does not prove the patch applies cleanly, runs in one QE "
                "workflow, or has L4 value"
            ),
        }
        row["row_hash"] = _stable_hash_without(row, "row_hash")
        rows.append(row)

    materialized_rows = [row for row in rows if row.get("materialized") is True]
    payload = {
        "schema_version": "dse.qe_bundle_patch_materialization_report.v1",
        "status": (
            "passed"
            if rows and len(materialized_rows) == len(rows)
            else ("blocked_no_bundle_candidates" if not rows else "blocked")
        ),
        "release_id": RELEASE_ID,
        "bundle_search_space_hash": bundle_space.get("search_space_hash"),
        "bundle_count": len(rows),
        "materialized_bundle_patch_count": len(materialized_rows),
        "blocked_bundle_patch_count": len(rows) - len(materialized_rows),
        "deliverable_complete": False,
        "rows": rows,
        "claim_boundary": (
            "materialized bundle patch files remove a provenance blocker only; "
            "runtime single-workflow L4 evidence remains separately required"
        ),
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def _accelerated_replacement_summary(
    attempt: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """Normalize replacement evidence without upgrading missing evidence."""
    if not attempt:
        return {
            "status": "not_attempted",
            "accelerated_results_consumed_by_qe": False,
            "accelerated_results_observed_by_qe_before_strict_replacement": False,
            "accelerated_result_materialized_in_qe_memory": False,
            "qe_software_kernel_execution_skipped": False,
            "qe_kernel_work_replaced_on_critical_path": False,
            "software_fallback_on_critical_path": None,
            "selected_kernel": None,
            "target_kernel": None,
            "accelerated_output_data_path_present": False,
            "target_kernel_matches_selected": None,
            "target_kernel_mismatch": False,
            "ready_for_value_gate": False,
            "blockers": [
                "accelerated_replacement_not_attempted",
                "real_l4_not_attempted",
            ],
            "claim_boundary": (
                "no real L4 attempt exists for this opportunity, so there is "
                "no accelerated replacement evidence"
            ),
        }
    replacement = attempt.get("accelerated_replacement")
    if not isinstance(replacement, Mapping):
        return {
            "status": "missing",
            "accelerated_results_consumed_by_qe": False,
            "accelerated_results_observed_by_qe_before_strict_replacement": False,
            "accelerated_result_materialized_in_qe_memory": False,
            "qe_software_kernel_execution_skipped": False,
            "qe_kernel_work_replaced_on_critical_path": False,
            "software_fallback_on_critical_path": True,
            "selected_kernel": str(attempt.get("kernel") or "") or None,
            "target_kernel": None,
            "accelerated_output_data_path_present": False,
            "target_kernel_matches_selected": None,
            "target_kernel_mismatch": False,
            "ready_for_value_gate": False,
            "blockers": [
                "accelerated_replacement_evidence_missing",
                "accelerated_replacement_not_passed",
                "software_fallback_on_critical_path_not_cleared",
            ],
            "claim_boundary": (
                "legacy or incomplete L4 attempt evidence did not include the "
                "required accelerated_replacement section; the value gate "
                "therefore treats fallback as uncleared"
            ),
        }

    consumed = replacement.get("accelerated_results_consumed_by_qe") is True
    materialized_in_qe = _replacement_truthy(
        replacement,
        "accelerated_result_materialized_in_qe_memory",
        "accelerated_output_written_to_qe_buffer",
        "qe_consumed_accelerator_output_buffer",
    )
    software_kernel_skipped = _replacement_truthy(
        replacement,
        "qe_software_kernel_execution_skipped",
        "software_kernel_execution_removed_from_critical_path",
        "software_kernel_work_skipped",
    )
    kernel_work_replaced = (
        _replacement_truthy(
            replacement,
            "qe_kernel_work_replaced_on_critical_path",
            "accelerated_kernel_work_removed_from_critical_path",
        )
        and materialized_in_qe
        and software_kernel_skipped
    )
    strict_consumed = consumed and materialized_in_qe and software_kernel_skipped
    fallback = replacement.get("software_fallback_on_critical_path")
    fallback_clear = fallback is False
    runtime_status = str(replacement.get("status") or "unknown")
    selected_kernel = str(replacement.get("selected_kernel") or attempt.get("kernel") or "")
    target_kernel = str(replacement.get("target_kernel") or "")
    gate_kernel = target_kernel or selected_kernel
    accelerated_output_data_path_present = _accelerated_output_data_path_present(
        replacement
    )
    target_match_raw = replacement.get("target_kernel_matches_selected")
    target_mismatch = (
        target_match_raw is False
        or (
            bool(selected_kernel)
            and bool(target_kernel)
            and selected_kernel != target_kernel
        )
    )
    blockers = [str(item) for item in replacement.get("blockers", []) or []]
    if runtime_status != "passed":
        blockers.append(f"accelerated_replacement_status_not_passed:{runtime_status}")
    if target_mismatch:
        blockers.append(
            "runtime_replacement_target_kernel_mismatch:"
            f"{selected_kernel or 'unknown'}:{target_kernel or 'unknown'}"
        )
    if not consumed:
        blockers.append("accelerated_results_not_consumed_by_qe")
    if not materialized_in_qe:
        blockers.append("accelerated_result_materialization_not_proven")
    if not software_kernel_skipped:
        blockers.append("qe_software_kernel_execution_skip_not_proven")
    if not kernel_work_replaced:
        blockers.append("qe_kernel_work_replacement_not_proven")
    if fallback is True:
        blockers.append("software_fallback_on_critical_path")
    elif fallback is not False:
        blockers.append("software_fallback_on_critical_path_unknown")
    if (
        _non_identity_target_requires_output_data_path(gate_kernel)
        and not accelerated_output_data_path_present
    ):
        blockers.append("accelerated_replacement_output_data_path_missing")
    blockers.extend(_local_writeback_without_accelerator_payload_blockers(attempt))
    ready = (
        runtime_status == "passed"
        and consumed
        and kernel_work_replaced
        and fallback_clear
        and not blockers
    )
    if not ready:
        blockers.append("accelerated_replacement_not_passed")
    return {
        "status": "passed" if ready else "blocked",
        "runtime_replacement_status": runtime_status,
        "accelerated_results_consumed_by_qe": strict_consumed,
        "accelerated_results_observed_by_qe_before_strict_replacement": consumed,
        "accelerated_result_materialized_in_qe_memory": materialized_in_qe,
        "qe_software_kernel_execution_skipped": software_kernel_skipped,
        "qe_kernel_work_replaced_on_critical_path": kernel_work_replaced,
        "software_fallback_on_critical_path": fallback,
        "selected_kernel": selected_kernel or None,
        "target_kernel": target_kernel or None,
        "accelerated_output_data_path_present": accelerated_output_data_path_present,
        "target_kernel_matches_selected": (
            False
            if target_mismatch
            else True
            if target_match_raw is True
            else None
        ),
        "target_kernel_mismatch": target_mismatch,
        "ready_for_value_gate": ready,
        "blockers": _dedupe_strings(blockers),
        "claim_boundary": (
            "replacement readiness is necessary but not sufficient for "
            "valuable_l4; consumed_by_qe is strict and only becomes true after "
            "runtime evidence also proves QE-memory materialization and skipped "
            "software kernel work; real L4, correctness, baseline, and positive "
            "speed must also pass"
        ),
    }


def _numeric_evidence_kernel_ids(row: Mapping[str, Any]) -> set[str]:
    kernel_ids: set[str] = set()
    for item in row.get("kernel_evidence", []) or []:
        if isinstance(item, Mapping) and item.get("kernel_id"):
            kernel_ids.add(str(item["kernel_id"]))
    provenance = row.get("offload_provenance")
    if isinstance(provenance, Mapping) and provenance.get("full_h_psi_recomputed") is True:
        kernel_ids.add("h_psi")
    return kernel_ids


def _accelerated_numeric_evidence_by_workload_kernel(
    rows: Sequence[Mapping[str, Any]] | None,
) -> Dict[tuple[str, str], list[Dict[str, Any]]]:
    by_key: Dict[tuple[str, str], list[Dict[str, Any]]] = {}
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        workload_case_id = str(row.get("workload_case_id") or "")
        if not workload_case_id:
            continue
        for kernel_id in _numeric_evidence_kernel_ids(row):
            by_key.setdefault((workload_case_id, kernel_id), []).append(dict(row))
    return by_key


def _external_numeric_replacement_summary(
    rows: Sequence[Mapping[str, Any]] | None,
) -> Dict[str, Any]:
    evidence_rows = [dict(row) for row in rows or [] if isinstance(row, Mapping)]
    if not evidence_rows:
        return {
            "status": "not_provided",
            "accelerated_results_consumed_by_qe": False,
            "trusted_accelerated_numeric_source": False,
            "l4_execution_proof_passed": False,
            "all_observed_calls_consumed": False,
            "component_model_boundary_blocks_replacement": False,
            "blockers": ["external_accelerated_numeric_evidence_not_provided"],
            "sources": [],
        }

    blockers: list[str] = []
    sources: list[str] = []
    consumed = False
    trusted = False
    l4_passed = False
    all_observed = False
    component_model_blocked = False
    for row in evidence_rows:
        blockers.extend(str(item) for item in row.get("blockers", []) or [])
        if row.get("source"):
            sources.append(str(row["source"]))
        accelerated_reference = row.get("accelerated_reference")
        if isinstance(accelerated_reference, Mapping):
            for key in (
                "stdout_path",
                "offload_provenance_path",
                "kernel_evidence_path",
            ):
                if accelerated_reference.get(key):
                    sources.append(str(accelerated_reference[key]))
        provenance = row.get("offload_provenance")
        provenance_map = provenance if isinstance(provenance, Mapping) else {}
        if provenance_map.get("accelerated_results_consumed_by_qe") is True:
            consumed = True
        if provenance_map.get("all_observed_hpsi_calls_sidecar_consumed") is True:
            all_observed = True
        l4_proof = provenance_map.get("l4_execution_proof")
        if isinstance(l4_proof, Mapping) and l4_proof.get("passed") is True:
            l4_passed = True
        if provenance_map.get("software_component_model_not_l4") is True:
            component_model_blocked = True
        if row.get("trusted_accelerated_numeric_source") is True:
            trusted = True
        for kernel_row in row.get("kernel_evidence", []) or []:
            if not isinstance(kernel_row, Mapping):
                continue
            if kernel_row.get("accelerated_results_consumed_by_qe") is True:
                consumed = True
            if kernel_row.get("all_observed_hpsi_calls_sidecar_consumed") is True:
                all_observed = True
            if kernel_row.get("software_component_model_not_l4") is True:
                component_model_blocked = True

    if trusted and consumed and l4_passed:
        status = "trusted_consumed_by_qe"
    elif consumed:
        status = "consumed_by_qe_but_blocked"
    else:
        status = "present_but_not_consumed_by_qe"
    if consumed and not trusted:
        blockers.append("external_numeric_consumed_by_qe_but_not_trusted")
    if consumed and not l4_passed:
        blockers.append("external_numeric_l4_execution_proof_not_passed")
    if component_model_blocked:
        blockers.append("external_numeric_software_component_model_not_l4")
    return {
        "status": status,
        "accelerated_results_consumed_by_qe": consumed,
        "trusted_accelerated_numeric_source": trusted,
        "l4_execution_proof_passed": l4_passed,
        "all_observed_calls_consumed": all_observed,
        "component_model_boundary_blocks_replacement": component_model_blocked,
        "blockers": _dedupe_strings(blockers),
        "sources": _dedupe_strings(sources),
    }


def build_accelerated_replacement_readiness_report(
    matrix: Mapping[str, Any],
    evidence_rows: Sequence[Mapping[str, Any]] | None = None,
    source_attempt_artifacts: Mapping[str, str] | None = None,
    opportunity_manifest: Mapping[str, Any] | None = None,
    accelerated_numeric_evidence_rows: Sequence[Mapping[str, Any]] | None = None,
    patch_manifest: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Report whether attempted callsites actually replace QE work."""
    attempts_by_opp = _best_evidence_rows_by_opportunity(
        [row for row in (evidence_rows or []) if isinstance(row, Mapping)]
    )
    artifact_by_opp = dict(source_attempt_artifacts or {})
    opportunity_by_id = {
        str(row.get("opportunity_id")): row
        for row in (opportunity_manifest or {}).get("opportunities", []) or []
        if isinstance(row, Mapping) and row.get("opportunity_id")
    }
    external_numeric_by_key = _accelerated_numeric_evidence_by_workload_kernel(
        accelerated_numeric_evidence_rows
    )
    rows: list[Dict[str, Any]] = []
    for matrix_row in matrix.get("rows", []) or []:
        if not isinstance(matrix_row, Mapping) or not matrix_row.get("opportunity_id"):
            continue
        opportunity_id = str(matrix_row.get("opportunity_id"))
        attempt = attempts_by_opp.get(opportunity_id, {})
        opportunity = opportunity_by_id.get(opportunity_id, {})
        workload_case_id = str(opportunity.get("workload_case_id") or "")
        kernel = str(matrix_row.get("kernel") or opportunity.get("kernel") or "")
        replacement = _accelerated_replacement_summary(attempt)
        speed_summary = _speed_measurement_summary(attempt)
        external_numeric = _external_numeric_replacement_summary(
            external_numeric_by_key.get((workload_case_id, kernel), [])
        )
        patch_precheck = _patch_replacement_precheck_for_opportunity(
            opportunity_id,
            patch_manifest,
        )
        evidence_present = bool(matrix_row.get("evidence_present"))
        real_l4_default = "not_attempted" if not evidence_present else "unknown"
        row = {
            "opportunity_id": opportunity_id,
            "workload_case_id": workload_case_id or None,
            "stage_type": matrix_row.get("stage_type"),
            "kernel": kernel,
            "value_label": matrix_row.get("value_label"),
            "evidence_present": evidence_present,
            "real_l4_status": _status_from_section(
                attempt, "real_l4_provenance", default=real_l4_default
            ),
            "correctness_status": _status_from_section(
                attempt, "correctness", default=real_l4_default
            ),
            "speed_status": _status_from_section(
                attempt, "speed_signal", default=real_l4_default
            ),
            "speedup_vs_pure_qe": speed_summary.get("speedup_vs_pure_qe"),
            "accelerated_replacement_status": replacement["status"],
            "accelerated_replacement_selected_kernel": replacement[
                "selected_kernel"
            ],
            "accelerated_replacement_target_kernel": replacement[
                "target_kernel"
            ],
            "accelerated_replacement_target_kernel_matches_selected": replacement[
                "target_kernel_matches_selected"
            ],
            "accelerated_replacement_target_kernel_mismatch": replacement[
                "target_kernel_mismatch"
            ],
            "accelerated_replacement_output_data_path_present": replacement[
                "accelerated_output_data_path_present"
            ],
            "accelerated_results_consumed_by_qe": replacement[
                "accelerated_results_consumed_by_qe"
            ],
            "accelerated_results_observed_by_qe_before_strict_replacement": replacement[
                "accelerated_results_observed_by_qe_before_strict_replacement"
            ],
            "qe_kernel_work_replaced_on_critical_path": replacement[
                "qe_kernel_work_replaced_on_critical_path"
            ],
            "software_fallback_on_critical_path": replacement[
                "software_fallback_on_critical_path"
            ],
            "ready_for_value_gate": replacement["ready_for_value_gate"],
            "replacement_blockers": replacement["blockers"],
            "external_consumption_evidence_status": external_numeric["status"],
            "external_accelerated_results_consumed_by_qe": external_numeric[
                "accelerated_results_consumed_by_qe"
            ],
            "external_trusted_accelerated_numeric_source": external_numeric[
                "trusted_accelerated_numeric_source"
            ],
            "external_l4_execution_proof_passed": external_numeric[
                "l4_execution_proof_passed"
            ],
            "external_all_observed_calls_consumed": external_numeric[
                "all_observed_calls_consumed"
            ],
            "component_model_boundary_blocks_replacement": external_numeric[
                "component_model_boundary_blocks_replacement"
            ],
            "external_numeric_blockers": external_numeric["blockers"],
            "external_numeric_sources": external_numeric["sources"],
            "patch_replacement_precheck_status": patch_precheck["status"],
            "patch_replacement_modes": patch_precheck["replacement_modes"],
            "patch_source_targets": patch_precheck["source_targets"],
            "patch_accelerated_result_writeback_present": patch_precheck[
                "accelerated_result_writeback_present"
            ],
            "patch_component_model_boundary_declared": patch_precheck[
                "component_model_boundary_declared"
            ],
            "patch_accelerated_output_data_path_declared": patch_precheck[
                "accelerated_output_data_path_declared"
            ],
            "patch_trusted_l4_replacement_precheck_passed": patch_precheck[
                "trusted_l4_replacement_precheck_passed"
            ],
            "patch_value_gate_blockers": patch_precheck["value_gate_blockers"],
            "value_gate_replacement_blockers": [
                str(blocker)
                for blocker in matrix_row.get("blockers", []) or []
                if "replacement" in str(blocker) or "fallback" in str(blocker)
            ],
            "source_attempt_artifact": artifact_by_opp.get(opportunity_id)
            or attempt.get("source_attempt_artifact"),
            "required_next_evidence": [
                "patched QE callsite or batch path replaces numerical work",
                "QE consumes accelerated results in the mainflow",
                "software fallback is not on the measured critical path",
                "runtime emits trusted offload provenance and kernel numeric evidence",
                "gem5 GenericAccel L4 execution proof remains passed",
            ],
            "recommended_next_action": (
                "run remaining L4 attempt before replacement analysis"
                if replacement["status"] == "not_attempted"
                else "implement replacement-capable QE runtime path, then rerun L4"
                if not replacement["ready_for_value_gate"]
                else "replacement gate passed; verify speed/correctness gates"
            ),
            "claim_boundary": replacement["claim_boundary"],
        }
        row["row_hash"] = _stable_hash_without(row, "row_hash")
        rows.append(row)

    attempted_rows = [row for row in rows if row["evidence_present"]]
    ready_rows = [row for row in rows if row["ready_for_value_gate"]]
    consumed_rows = [
        row for row in rows if row["accelerated_results_consumed_by_qe"] is True
    ]
    raw_observed_consumed_rows = [
        row
        for row in rows
        if row["accelerated_results_observed_by_qe_before_strict_replacement"]
        is True
    ]
    kernel_work_replaced_rows = [
        row for row in rows if row["qe_kernel_work_replaced_on_critical_path"] is True
    ]
    external_consumed_rows = [
        row for row in rows if row["external_accelerated_results_consumed_by_qe"] is True
    ]
    external_consumed_but_blocked_rows = [
        row
        for row in external_consumed_rows
        if row["external_consumption_evidence_status"] == "consumed_by_qe_but_blocked"
    ]
    external_trusted_rows = [
        row for row in rows if row["external_trusted_accelerated_numeric_source"] is True
    ]
    component_blocked_rows = [
        row for row in rows if row["component_model_boundary_blocks_replacement"] is True
    ]
    patch_linked_rows = [
        row
        for row in rows
        if row["patch_replacement_precheck_status"]
        != "patch_manifest_not_provided"
    ]
    patch_component_blocked_rows = [
        row
        for row in rows
        if row["patch_component_model_boundary_declared"] is True
    ]
    patch_writeback_rows = [
        row
        for row in rows
        if row["patch_accelerated_result_writeback_present"] is True
    ]
    patch_trusted_precheck_rows = [
        row
        for row in rows
        if row["patch_trusted_l4_replacement_precheck_passed"] is True
    ]
    fallback_rows = [
        row
        for row in rows
        if row["software_fallback_on_critical_path"] is True
    ]
    missing_rows = [
        row
        for row in rows
        if row["accelerated_replacement_status"] in {"missing", "not_attempted"}
    ]
    blocker_rows = [row for row in rows if row["replacement_blockers"]]
    target_mismatch_rows = [
        row
        for row in rows
        if row["accelerated_replacement_target_kernel_mismatch"] is True
    ]
    non_hpsi_non_spsi_rows = [
        row
        for row in rows
        if row["kernel"] not in {"h_psi", "s_psi"}
    ]
    non_hpsi_non_spsi_ready_rows = [
        row for row in non_hpsi_non_spsi_rows if row["ready_for_value_gate"] is True
    ]
    non_hpsi_non_spsi_blocked_rows = [
        row for row in non_hpsi_non_spsi_rows if row["ready_for_value_gate"] is not True
    ]
    non_hpsi_non_spsi_priority_rows = sorted(
        non_hpsi_non_spsi_blocked_rows,
        key=lambda row: (
            row["evidence_present"] is not True,
            row["patch_accelerated_result_writeback_present"] is not True,
            row["speed_status"] != "positive",
            row["speed_status"] != "non_positive",
            -float(row.get("speedup_vs_pure_qe") or 0.0),
            str(row.get("opportunity_id")),
        ),
    )
    next_non_hpsi_non_spsi_replacement_targets = [
        {
            "opportunity_id": row["opportunity_id"],
            "workload_case_id": row["workload_case_id"],
            "stage_type": row["stage_type"],
            "kernel": row["kernel"],
            "speed_status": row["speed_status"],
            "speedup_vs_pure_qe": row.get("speedup_vs_pure_qe"),
            "patch_replacement_precheck_status": row[
                "patch_replacement_precheck_status"
            ],
            "patch_accelerated_result_writeback_present": row[
                "patch_accelerated_result_writeback_present"
            ],
            "patch_accelerated_output_data_path_declared": row[
                "patch_accelerated_output_data_path_declared"
            ],
            "accelerated_replacement_output_data_path_present": row[
                "accelerated_replacement_output_data_path_present"
            ],
            "replacement_blockers": row["replacement_blockers"],
            "patch_value_gate_blockers": row["patch_value_gate_blockers"],
            "recommended_next_action": row["recommended_next_action"],
            "claim_boundary": (
                "priority target only; not valuable_l4 until strict runtime "
                "replacement, correctness, baseline, and positive speed pass"
            ),
        }
        for row in non_hpsi_non_spsi_priority_rows[:8]
    ]
    payload = {
        "schema_version": "dse.qe_accelerated_replacement_readiness_report.v1",
        "status": (
            "replacement_ready"
            if ready_rows
            else "blocked_or_not_attempted"
        ),
        "release_id": RELEASE_ID,
        "matrix_hash": matrix.get("matrix_hash"),
        "row_count": len(rows),
        "attempted_row_count": len(attempted_rows),
        "replacement_ready_count": len(ready_rows),
        "accelerated_results_consumed_by_qe_count": len(consumed_rows),
        "accelerated_results_observed_by_qe_before_strict_replacement_count": len(
            raw_observed_consumed_rows
        ),
        "qe_kernel_work_replaced_on_critical_path_count": len(
            kernel_work_replaced_rows
        ),
        "external_accelerated_results_consumed_by_qe_count": len(
            external_consumed_rows
        ),
        "external_consumed_but_blocked_count": len(
            external_consumed_but_blocked_rows
        ),
        "external_trusted_accelerated_numeric_source_count": len(
            external_trusted_rows
        ),
        "component_model_boundary_blocked_count": len(component_blocked_rows),
        "patch_precheck_linked_count": len(patch_linked_rows),
        "patch_precheck_writeback_count": len(patch_writeback_rows),
        "patch_precheck_component_model_blocked_count": len(
            patch_component_blocked_rows
        ),
        "patch_precheck_trusted_l4_replacement_candidate_count": len(
            patch_trusted_precheck_rows
        ),
        "software_fallback_on_critical_path_count": len(fallback_rows),
        "target_kernel_mismatch_count": len(target_mismatch_rows),
        "missing_or_not_attempted_replacement_count": len(missing_rows),
        "replacement_blocker_count": len(blocker_rows),
        "non_hpsi_non_spsi_replacement_ready_count": len(
            non_hpsi_non_spsi_ready_rows
        ),
        "non_hpsi_non_spsi_replacement_blocked_count": len(
            non_hpsi_non_spsi_blocked_rows
        ),
        "next_non_hpsi_non_spsi_replacement_targets": (
            next_non_hpsi_non_spsi_replacement_targets
        ),
        "valuable_l4_count": matrix.get("valuable_l4_count", 0),
        "value_claim_allowed_by_replacement_gate": bool(ready_rows),
        "all_attempted_rows_replacement_ready": (
            bool(attempted_rows) and len(ready_rows) == len(attempted_rows)
        ),
        "hpsi_only_completion_allowed": False,
        "deliverable_complete": False,
        "rows": rows,
        "claim_boundary": (
            "replacement readiness requires QE to consume accelerator results, "
            "proof that the selected kernel's software work was removed from the "
            "critical path, and no measured critical-path fallback; it cannot "
            "claim value without the full L4/correctness/baseline/speed gate"
        ),
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def _selected_kernel_observed_in_trace(
    attempt: Mapping[str, Any],
    kernel: Any,
) -> bool | None:
    if not attempt:
        return None
    kernel_text = str(kernel)
    for section_name in ("trace_evidence", "gem5_transport_evidence"):
        section = attempt.get(section_name)
        if not isinstance(section, Mapping):
            continue
        counts = section.get("trace_kernel_counts")
        if isinstance(counts, Mapping):
            return bool(counts.get(kernel_text, 0))
    selection = attempt.get("selection_profile")
    if isinstance(selection, Mapping) and "initial_kernel_observed" in selection:
        return bool(selection.get("initial_kernel_observed"))
    return None


def _primary_blocker_class(blockers: Sequence[str]) -> str:
    if not blockers:
        return "none"
    if any(
        blocker.startswith("patch_file_missing:")
        or blocker == "qe_source_patch_not_materialized_for_callsite"
        or blocker == "qe_source_patch_not_applied_to_build"
        for blocker in blockers
    ):
        return "patch_artifact_missing"
    if any(
        blocker.startswith("trace_evidence_missing_selected_kernel:")
        or blocker == "explicit_opportunity_kernel_not_observed_in_real_qe_profile"
        for blocker in blockers
    ):
        return "trace_not_observed"
    if "genericaccel_offload_bridge_missing" in blockers:
        return "offload_bridge_missing"
    if "real_l4_not_attempted" in blockers:
        return "not_attempted"
    if any(
        blocker.startswith("real_l4_")
        or blocker.startswith("patched_qe_")
        and (
            "request" in blocker
            or "completion" in blocker
            or "gem5_execution" in blocker
            or "executable" in blocker
        )
        for blocker in blockers
    ):
        return "real_l4_incomplete"
    if any("correctness" in blocker for blocker in blockers):
        return "correctness_incomplete"
    if any(
        blocker == "accelerated_results_not_consumed_by_qe"
        or blocker == "actual_compute_qe_consumed_replacement_not_proven"
        or blocker.startswith("offload_provenance_missing_accelerated_results_consumed_by_qe")
        for blocker in blockers
    ):
        return "accelerated_replacement_not_consumed"
    if any("replacement" in blocker or "fallback" in blocker for blocker in blockers):
        return "accelerated_replacement_missing"
    if any(
        blocker in {
            "actual_compute_full_qe_evidence_not_passed",
            "actual_compute_marked_smoke_only",
        }
        for blocker in blockers
    ):
        return "actual_compute_incomplete"
    if any("speed" in blocker for blocker in blockers):
        return "speed_signal_non_positive_or_missing"
    return "other_blocker"


def _recommended_next_action(primary_blocker_class: str) -> str:
    return {
        "patch_artifact_missing": (
            "materialize the QE callsite patch artifact, apply it to the "
            "local QE tree, rebuild, then rerun this opportunity"
        ),
        "trace_not_observed": (
            "instrument or reclassify the QE callsite until the selected "
            "kernel appears in the real QE trace before trusting L4 transport"
        ),
        "offload_bridge_missing": (
            "implement the QE-to-GenericAccel bridge for this callsite and "
            "emit descriptor/request/completion evidence"
        ),
        "real_l4_incomplete": (
            "run or fix the patched-QE gem5 GenericAccel L4 execution until "
            "descriptor, request decode, microarchitecture execute, and "
            "completion all pass"
        ),
        "correctness_incomplete": (
            "produce patched-QE numeric correctness evidence against the pure "
            "QE baseline for this workload/callsite"
        ),
        "actual_compute_incomplete": (
            "rerun a non-smoke full-QE actual-compute path that proves QE "
            "consumed the selected GenericAccel replacement output before "
            "treating speed as value evidence"
        ),
        "accelerated_replacement_missing": (
            "implement an accelerated result replacement or batched in-process "
            "path so QE consumes accelerator results instead of timing a "
            "fallback-only bridge"
        ),
        "accelerated_replacement_not_consumed": (
            "connect the selected-kernel GenericAccel result path back into "
            "QE state update/writeback so accelerated_results_consumed_by_qe "
            "becomes true without relying on the software fallback"
        ),
        "speed_signal_non_positive_or_missing": (
            "optimize or deprioritize this candidate; do not claim valuable_l4 "
            "until speedup_vs_pure_qe is positive"
        ),
        "not_attempted": "run a real QE + gem5 L4 attempt for this opportunity",
        "other_blocker": "resolve the listed blockers in order of the report",
        "none": "no blocker action required",
    }[primary_blocker_class]


def _requires_patch_artifact(blockers: Sequence[str]) -> bool:
    return any(
        blocker.startswith("patch_file_missing:")
        or blocker == "qe_source_patch_not_materialized_for_callsite"
        or blocker == "qe_source_patch_not_applied_to_build"
        for blocker in blockers
    )


def build_callgraph_offload_blocker_report(
    inventory: Mapping[str, Any] | None = None,
    matrix: Mapping[str, Any] | None = None,
    evidence_rows: Sequence[Mapping[str, Any]] | None = None,
    source_attempt_artifacts: Mapping[str, str] | None = None,
) -> Dict[str, Any]:
    inv = dict(inventory or build_qe_callgraph_inventory())
    mat = dict(matrix or build_offload_value_l4_evidence_matrix())
    attempts_by_opp = _best_evidence_rows_by_opportunity(
        [row for row in (evidence_rows or []) if isinstance(row, Mapping)]
    )
    artifact_by_opp = dict(source_attempt_artifacts or {})
    blocker_counts: Dict[str, int] = {}
    for blocker in inv.get("blockers", []) or []:
        blocker_id = str(blocker.get("id", "unknown_inventory_blocker"))
        blocker_counts[blocker_id] = blocker_counts.get(blocker_id, 0) + 1
    blocker_rows: list[Dict[str, Any]] = []
    for row in mat.get("rows", []) or []:
        opportunity_id = str(row.get("opportunity_id"))
        attempt = attempts_by_opp.get(opportunity_id, {})
        value_gate_blockers = _dedupe_strings(row.get("blockers", []) or [])
        attempt_blockers = _nested_attempt_blockers(attempt)
        all_blockers = _dedupe_strings(value_gate_blockers + attempt_blockers)
        for blocker in all_blockers:
            blocker_text = str(blocker)
            blocker_counts[blocker_text] = blocker_counts.get(blocker_text, 0) + 1
        if not all_blockers:
            continue
        real_l4_default = "not_attempted" if not row.get("evidence_present") else "unknown"
        status_row = {
            "opportunity_id": opportunity_id,
            "stage_type": row.get("stage_type"),
            "kernel": row.get("kernel"),
            "value_label": row.get("value_label"),
            "primary_blocker_class": _primary_blocker_class(all_blockers),
            "blockers": all_blockers,
            "value_gate_blockers": value_gate_blockers,
            "attempt_blockers": attempt_blockers,
            "source_attempt_artifact": artifact_by_opp.get(opportunity_id)
            or attempt.get("source_attempt_artifact"),
            "requires_patch_artifact": _requires_patch_artifact(all_blockers),
            "observed_in_trace": _selected_kernel_observed_in_trace(
                attempt, row.get("kernel")
            ),
            "real_l4_status": _status_from_section(
                attempt,
                "real_l4_provenance",
                default=real_l4_default,
            ),
            "correctness_status": _status_from_section(
                attempt,
                "correctness",
                default=real_l4_default,
            ),
            "speed_status": _status_from_section(
                attempt,
                "speed_signal",
                default=real_l4_default,
            ),
            "speed_measurement": _speed_measurement_summary(attempt),
        }
        status_row["recommended_next_action"] = _recommended_next_action(
            str(status_row["primary_blocker_class"])
        )
        status_row["row_hash"] = _stable_hash_without(status_row, "row_hash")
        blocker_rows.append(status_row)
    payload = {
        "schema_version": "dse.qe_callgraph_offload_blocker_report.v1",
        "status": "blocked" if blocker_counts or blocker_rows else "passed",
        "release_id": RELEASE_ID,
        "inventory_hash": inv.get("inventory_hash"),
        "matrix_hash": mat.get("matrix_hash"),
        "row_count": mat.get("row_count", 0),
        "blocker_row_count": len(blocker_rows),
        "blocked_value_row_count": sum(
            1 for row in blocker_rows if row.get("value_label") == "blocked"
        ),
        "not_valuable_row_count": sum(
            1 for row in blocker_rows if row.get("value_label") == "not_valuable_l4"
        ),
        "queued_by_projection_row_count": sum(
            1
            for row in blocker_rows
            if row.get("value_label") == "queued_by_projection"
        ),
        "blocker_counts": blocker_counts,
        "blocker_rows": blocker_rows,
        "deliverable_complete": False,
        "claim_boundary": "blockers are first-class; they cannot be hidden as completion",
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def build_offload_selection_search_report(
    opportunity_manifest: Mapping[str, Any],
    matrix: Mapping[str, Any],
    blocker_report: Mapping[str, Any] | None = None,
    workload_variant_search_space: Mapping[str, Any] | None = None,
    inventory: Mapping[str, Any] | None = None,
    repeatability_report: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    variant_space = dict(
        workload_variant_search_space
        or build_workload_variant_search_space(opportunity_manifest)
    )
    variants_by_opp: Dict[str, list[Dict[str, Any]]] = {}
    for variant in variant_space.get("variants", []) or []:
        if not isinstance(variant, Mapping):
            continue
        summary = {
            "variant_id": variant.get("variant_id"),
            "variant_status": variant.get("variant_status"),
            "pseudopotential_family": variant.get("pseudopotential_family"),
            "binding_required": variant.get(
                "offload_target_binding_required_for_candidate_identity",
                False,
            ),
            "canonical_replacement_allowed": variant.get(
                "canonical_replacement_allowed"
            ),
        }
        for opportunity_id in variant.get("applies_to_opportunity_ids", []) or []:
            variants_by_opp.setdefault(str(opportunity_id), []).append(dict(summary))
    blocker_by_opp = {
        str(row.get("opportunity_id")): row
        for row in (blocker_report or {}).get("blocker_rows", []) or []
        if isinstance(row, Mapping) and row.get("opportunity_id")
    }
    value_by_opp = {
        str(row.get("opportunity_id")): row
        for row in matrix.get("rows", []) or []
        if isinstance(row, Mapping) and row.get("opportunity_id")
    }
    stable_repeatability_by_opp = _stable_repeatability_rows_by_opportunity(
        repeatability_report
    )
    ranked_rows: list[Dict[str, Any]] = []
    for opportunity in opportunity_manifest.get("opportunities", []) or []:
        if not isinstance(opportunity, Mapping):
            continue
        opportunity_id = str(opportunity.get("opportunity_id"))
        value_row = dict(value_by_opp.get(opportunity_id) or {})
        blocker_row = dict(blocker_by_opp.get(opportunity_id) or {})
        stable_configurations = [
            _stable_repeatability_summary(row)
            for row in stable_repeatability_by_opp.get(opportunity_id, [])
        ]
        best_stable_speedup = (
            max(
                float(row.get("max_speedup_vs_pure_qe"))
                for row in stable_configurations
                if isinstance(row.get("max_speedup_vs_pure_qe"), (int, float))
            )
            if any(
                isinstance(row.get("max_speedup_vs_pure_qe"), (int, float))
                for row in stable_configurations
            )
            else None
        )
        selection_priority = dict(opportunity.get("selection_priority") or {})
        if stable_configurations:
            recommended_next_action = (
                "promote this stable full-QE L4 configuration for bundle/"
                "workflow comparison; do not claim bundle-level value until "
                "a single-workflow bundle passes the same gates"
            )
        elif value_row.get("valuable_l4") is True:
            recommended_next_action = (
                "repeat the positive full-QE L4 value sample under the same "
                "replacement configuration before treating it as stable"
            )
        else:
            recommended_next_action = blocker_row.get(
                "recommended_next_action",
                "run a real QE + gem5 L4 attempt for this opportunity",
            )
        ranked_row = {
            "opportunity_id": opportunity_id,
            "workload_case_id": opportunity.get("workload_case_id"),
            "stage_type": opportunity.get("stage_type"),
            "kernel": opportunity.get("kernel"),
            "kernel_family": opportunity.get("kernel_family"),
            "selection_priority": selection_priority,
            "workload_selection": dict(opportunity.get("workload_selection") or {}),
            "workload_variant_options": variants_by_opp.get(opportunity_id, []),
            "profile_evidence": dict(opportunity.get("profile_evidence") or {}),
            "value_label": value_row.get("value_label", "queued_by_projection"),
            "valuable_l4": value_row.get("valuable_l4", False),
            "stable_repeatability_configuration_count": len(
                stable_configurations
            ),
            "stable_repeatability_configurations": stable_configurations,
            "best_stable_speedup_vs_pure_qe": best_stable_speedup,
            "primary_blocker_class": blocker_row.get("primary_blocker_class"),
            "speed_measurement": dict(blocker_row.get("speed_measurement") or {}),
            "source_attempt_artifact": blocker_row.get("source_attempt_artifact"),
            "recommended_next_action": recommended_next_action,
            "claim_boundary": (
                "selection priority ranks what to attempt; value_label still "
                "comes only from L4/correctness/speed evidence; stable "
                "repeatability ranks measured replacement configurations but "
                "does not create bundle-level value"
            ),
        }
        ranked_row["row_hash"] = _stable_hash_without(ranked_row, "row_hash")
        ranked_rows.append(ranked_row)
    ranked_rows.sort(
        key=lambda row: (
            -float(dict(row.get("selection_priority") or {}).get("score", 0.0)),
            str(row.get("opportunity_id")),
        )
    )
    static_candidate_summary = {}
    if isinstance(inventory, Mapping):
        static_callgraph = inventory.get("static_callgraph")
        if isinstance(static_callgraph, Mapping):
            static_candidate_summary = dict(
                static_callgraph.get("offload_candidate_summary") or {}
            )
    static_candidates = [
        dict(row)
        for row in static_candidate_summary.get("candidates_sample", []) or []
        if isinstance(row, Mapping)
    ][:64]
    payload = {
        "schema_version": "dse.qe_offload_selection_search_report.v1",
        "status": (
            "partial_or_blocked"
            if matrix.get("valuable_l4_count", 0) == 0
            or blocker_report and blocker_report.get("status") == "blocked"
            else "selection_search_has_valuable_l4"
        ),
        "release_id": RELEASE_ID,
        "manifest_hash": opportunity_manifest.get("manifest_hash"),
        "matrix_hash": matrix.get("matrix_hash"),
        "blocker_report_hash": (blocker_report or {}).get("report_hash"),
        "workload_variant_search_space_hash": variant_space.get("search_space_hash"),
        "workload_variant_selection_axes": list(
            variant_space.get("selection_axes") or WORKLOAD_SELECTION_AXES
        ),
        "formal_workload_variant_count": variant_space.get(
            "formal_workload_variant_count", 0
        ),
        "canonical_replacement_requires_explicit_binding": variant_space.get(
            "canonical_replacement_requires_explicit_binding", True
        ),
        "ranked_opportunity_count": len(ranked_rows),
        "ranked_opportunities": ranked_rows,
        "static_research_candidate_count": int(
            static_candidate_summary.get("candidate_count") or 0
        ),
        "static_research_candidate_kernel_counts": dict(
            static_candidate_summary.get("kernel_counts") or {}
        ),
        "static_research_candidates_sample": static_candidates,
        "static_research_candidate_policy": (
            "static full-callgraph candidates are queued for workload binding "
            "and cannot become attempted_l4 or valuable_l4 without trace, "
            "patch/runtime binding, correctness, replacement, and positive speed"
        ),
        "valuable_l4_count": matrix.get("valuable_l4_count", 0),
        "stable_repeatability_valuable_l4_count": sum(
            len(rows) for rows in stable_repeatability_by_opp.values()
        ),
        "value_counts": dict(matrix.get("value_counts") or {}),
        "hpsi_only_completion_allowed": False,
        "projection_only_value_allowed": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "DSE offload-target selection report; priority/profile evidence is "
            "not value evidence and cannot complete the deliverable"
        ),
    }
    payload["report_hash"] = _stable_hash_without(payload, "report_hash")
    return payload


def _markdown_text(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ")


def render_offload_value_report_markdown(
    report: Mapping[str, Any],
    matrix: Mapping[str, Any] | None = None,
) -> str:
    mat = dict(matrix or {})
    summary = dict(report.get("summary") or {})
    rows = [
        "# QE callgraph offload value report",
        "",
        f"- status: `{_markdown_text(report.get('status'))}`",
        f"- deliverable_complete: `{str(report.get('claims', {}).get('deliverable_complete', False)).lower()}`",
        f"- valuable_l4_count: `{summary.get('valuable_l4_count', mat.get('valuable_l4_count', 0))}`",
        f"- stable_repeatability_valuable_l4_count: `{summary.get('stable_repeatability_valuable_l4_count', 0)}`",
        f"- blocked_count: `{summary.get('blocked_count', mat.get('value_counts', {}).get('blocked', 0))}`",
        f"- queued_by_projection_count: `{summary.get('queued_by_projection_count', mat.get('value_counts', {}).get('queued_by_projection', 0))}`",
        "",
        "## Value counts",
        "",
        "| value_label | count |",
        "|---|---:|",
    ]
    for label, count in sorted(dict(mat.get("value_counts") or {}).items()):
        rows.append(f"| {_markdown_text(label)} | {count} |")
    stable_configs = [
        row
        for row in report.get("stable_repeatability_configurations", []) or []
        if isinstance(row, Mapping)
    ]
    if stable_configs:
        rows.extend(
            [
                "",
                "## Stable repeatable value configurations",
                "",
                "| opportunity_id | kernel | workload_variant | replacement_config | speedups_vs_pure_qe |",
                "|---|---|---|---|---|",
            ]
        )
        for row in stable_configs:
            rows.append(
                "| "
                + " | ".join(
                    [
                        _markdown_text(row.get("opportunity_id")),
                        _markdown_text(row.get("kernel")),
                        _markdown_text(row.get("workload_variant_id")),
                        _markdown_text(
                            row.get("replacement_configuration_identity_key")
                        ),
                        _markdown_text(row.get("speedups_vs_pure_qe")),
                    ]
                )
                + " |"
            )
    rows.extend(
        [
            "",
            "## Claim boundary",
            "",
            _markdown_text(report.get("claim_boundary")),
            "",
        ]
    )
    return "\n".join(rows)


def render_callgraph_offload_blocker_report_markdown(
    report: Mapping[str, Any],
) -> str:
    rows = [
        "# QE callgraph offload blocker report",
        "",
        f"- status: `{_markdown_text(report.get('status'))}`",
        f"- row_count: `{report.get('row_count', 0)}`",
        f"- blocker_row_count: `{report.get('blocker_row_count', 0)}`",
        f"- blocked_value_row_count: `{report.get('blocked_value_row_count', 0)}`",
        f"- not_valuable_row_count: `{report.get('not_valuable_row_count', 0)}`",
        f"- queued_by_projection_row_count: `{report.get('queued_by_projection_row_count', 0)}`",
        f"- deliverable_complete: `{str(report.get('deliverable_complete', False)).lower()}`",
        "",
        "## Top blockers",
        "",
        "| blocker | count |",
        "|---|---:|",
    ]
    counts = dict(report.get("blocker_counts") or {})
    for blocker, count in sorted(counts.items(), key=lambda item: (-int(item[1]), item[0]))[:20]:
        rows.append(f"| {_markdown_text(blocker)} | {count} |")
    rows.extend(
        [
            "",
            "## Per-row closure actions",
            "",
            "| opportunity_id | kernel | label | primary_blocker_class | observed_in_trace | real_l4 | correctness | speed | speedup_vs_pure_qe | next_action |",
            "|---|---|---|---|---|---|---|---|---:|---|",
        ]
    )
    for row in report.get("blocker_rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        speed_measurement = dict(row.get("speed_measurement") or {})
        rows.append(
            "| "
            + " | ".join(
                _markdown_text(row.get(key))
                for key in (
                    "opportunity_id",
                    "kernel",
                    "value_label",
                    "primary_blocker_class",
                    "observed_in_trace",
                    "real_l4_status",
                    "correctness_status",
                    "speed_status",
                )
            )
            + " | "
            + _markdown_text(speed_measurement.get("speedup_vs_pure_qe"))
            + " | "
            + _markdown_text(row.get("recommended_next_action"))
            + " |"
        )
    rows.extend(
        [
            "",
            "## Claim boundary",
            "",
            _markdown_text(report.get("claim_boundary")),
            "",
        ]
    )
    return "\n".join(rows)


def render_offload_selection_search_report_markdown(
    report: Mapping[str, Any],
) -> str:
    rows = [
        "# QE offload selection search report",
        "",
        f"- status: `{_markdown_text(report.get('status'))}`",
        f"- ranked_opportunity_count: `{report.get('ranked_opportunity_count', 0)}`",
        f"- valuable_l4_count: `{report.get('valuable_l4_count', 0)}`",
        f"- stable_repeatability_valuable_l4_count: `{report.get('stable_repeatability_valuable_l4_count', 0)}`",
        f"- formal_workload_variant_count: `{report.get('formal_workload_variant_count', 0)}`",
        f"- deliverable_complete: `{str(report.get('deliverable_complete', False)).lower()}`",
        "",
        "## Ranked opportunities",
        "",
        "| rank | opportunity_id | workload | variants | stage | kernel | score | label | stable_configs | best_stable_speedup | speedup_vs_pure_qe | primary blocker | next action |",
        "|---:|---|---|---|---|---|---:|---|---:|---:|---:|---|---|",
    ]
    for index, row in enumerate(report.get("ranked_opportunities", []) or [], start=1):
        if not isinstance(row, Mapping):
            continue
        speed_measurement = dict(row.get("speed_measurement") or {})
        variant_options = [
            str(option.get("variant_id"))
            for option in row.get("workload_variant_options", []) or []
            if isinstance(option, Mapping) and option.get("variant_id")
        ]
        rows.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _markdown_text(row.get("opportunity_id")),
                    _markdown_text(row.get("workload_case_id")),
                    _markdown_text(",".join(variant_options)),
                    _markdown_text(row.get("stage_type")),
                    _markdown_text(row.get("kernel")),
                    _markdown_text(
                        dict(row.get("selection_priority") or {}).get("score", 0.0)
                    ),
                    _markdown_text(row.get("value_label")),
                    _markdown_text(
                        row.get("stable_repeatability_configuration_count", 0)
                    ),
                    _markdown_text(row.get("best_stable_speedup_vs_pure_qe")),
                    _markdown_text(speed_measurement.get("speedup_vs_pure_qe")),
                    _markdown_text(row.get("primary_blocker_class")),
                    _markdown_text(row.get("recommended_next_action")),
                ]
            )
            + " |"
        )
    rows.extend(
        [
            "",
            "## Claim boundary",
            "",
            _markdown_text(report.get("claim_boundary")),
            "",
        ]
    )
    return "\n".join(rows)


def render_l4_speed_optimization_report_markdown(
    report: Mapping[str, Any],
) -> str:
    rows = [
        "# QE L4 speed optimization report",
        "",
        f"- status: `{_markdown_text(report.get('status'))}`",
        f"- attempt_count: `{report.get('attempt_count', 0)}`",
        f"- positive_speed_count: `{report.get('positive_speed_count', 0)}`",
        f"- non_positive_speed_count: `{report.get('non_positive_speed_count', 0)}`",
        f"- blocked_speed_count: `{report.get('blocked_speed_count', 0)}`",
        f"- replacement_ready_non_positive_speed_count: `{report.get('replacement_ready_non_positive_speed_count', 0)}`",
        f"- persistent_or_batched_dispatch_required_count: `{report.get('persistent_or_batched_dispatch_required_count', 0)}`",
        f"- replacement_writeback_required_count: `{report.get('replacement_writeback_required_count', 0)}`",
        f"- best_speedup_vs_pure_qe: `{_markdown_text(report.get('best_speedup_vs_pure_qe'))}`",
        f"- best_replacement_ready_speedup_vs_pure_qe: `{_markdown_text(report.get('best_replacement_ready_speedup_vs_pure_qe'))}`",
        f"- baseline_gpu_context_observed_count: `{report.get('baseline_gpu_context_observed_count', 0)}`",
        f"- baseline_gpu_available_count: `{report.get('baseline_gpu_available_count', 0)}`",
        f"- valuable_l4_count: `{report.get('valuable_l4_count', 0)}`",
        f"- deliverable_complete: `{str(report.get('deliverable_complete', False)).lower()}`",
        "",
        "## Ranked speed rows",
        "",
        "| rank | opportunity_id | workload_variant | runtime_workload | kernel | label | speed_status | speedup_vs_pure_qe | baseline_s | patched_s | patched_minus_baseline_s | baseline_gpu_available | reduction_needed_s | overhead_reduction_fraction | bridge_policy | bridge_invocations | gem5_launches | batch_size | batched_observed | replacement_ready | next_engineering_gate | next action |",
        "|---:|---|---|---|---|---|---|---:|---:|---:|---:|---|---:|---:|---|---:|---:|---:|---|---|---|---|",
    ]
    for index, row in enumerate(report.get("rows", []) or [], start=1):
        if not isinstance(row, Mapping):
            continue
        rows.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _markdown_text(row.get("opportunity_id")),
                    _markdown_text(
                        row.get("workload_variant_id")
                        or row.get("workload_variant_identity_key")
                    ),
                    _markdown_text(row.get("runtime_workload_case_id")),
                    _markdown_text(row.get("kernel")),
                    _markdown_text(row.get("value_label")),
                    _markdown_text(row.get("speed_status")),
                    _markdown_text(row.get("speedup_vs_pure_qe")),
                    _markdown_text(row.get("baseline_elapsed_seconds")),
                    _markdown_text(row.get("patched_qe_elapsed_seconds")),
                    _markdown_text(row.get("patched_minus_baseline_seconds")),
                    _markdown_text(row.get("baseline_gpu_available")),
                    _markdown_text(
                        row.get(
                            "required_elapsed_reduction_seconds_for_positive_speed"
                        )
                    ),
                    _markdown_text(
                        row.get("required_bridge_overhead_reduction_fraction")
                    ),
                    _markdown_text(row.get("bridge_invocation_policy")),
                    _markdown_text(
                        row.get(
                            "gem5_bridge_invocation_count_on_qe_critical_path"
                        )
                    ),
                    _markdown_text(
                        row.get("gem5_bridge_launch_count_on_qe_critical_path")
                    ),
                    _markdown_text(row.get("batched_request_count_per_launch")),
                    _markdown_text(
                        row.get("persistent_or_batched_dispatch_observed")
                    ),
                    _markdown_text(row.get("replacement_ready")),
                    _markdown_text(row.get("next_engineering_gate")),
                    _markdown_text(row.get("recommended_next_action")),
                ]
            )
            + " |"
        )
    rows.extend(
        [
            "",
            "## Claim boundary",
            "",
            _markdown_text(report.get("claim_boundary")),
            "",
        ]
    )
    return "\n".join(rows)


def render_l4_value_repeatability_report_markdown(
    report: Mapping[str, Any],
) -> str:
    rows = [
        "# QE L4 value repeatability report",
        "",
        f"- status: `{_markdown_text(report.get('status'))}`",
        f"- replacement_ready_opportunity_count: `{report.get('replacement_ready_opportunity_count', 0)}`",
        f"- repeatability_stable_valuable_l4_count: `{report.get('repeatability_stable_valuable_l4_count', 0)}`",
        f"- repeatability_mixed_count: `{report.get('repeatability_mixed_count', 0)}`",
        f"- speed_mixed_count: `{report.get('speed_mixed_count', 0)}`",
        f"- single_positive_unconfirmed_count: `{report.get('single_positive_unconfirmed_count', 0)}`",
        f"- value_gate_not_passed_count: `{report.get('value_gate_not_passed_count', 0)}`",
        f"- min_replacement_ready_samples: `{report.get('min_replacement_ready_samples', 0)}`",
        f"- deliverable_complete: `{str(report.get('deliverable_complete', False)).lower()}`",
        "",
        "## Replacement-ready repeatability rows",
        "",
        "| opportunity_id | workload_variant | runtime_workload | kernel | repeatability_status | speed_repeatability_status | stable_value | valuable_l4_samples | non_valuable_samples | positive | non_positive | speedups | blockers |",
        "|---|---|---|---|---|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in report.get("rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        rows.append(
            "| "
            + " | ".join(
                [
                    _markdown_text(row.get("opportunity_id")),
                    _markdown_text(
                        row.get("workload_variant_id")
                        or row.get("workload_variant_identity_key")
                    ),
                    _markdown_text(row.get("runtime_workload_case_id")),
                    _markdown_text(row.get("kernel")),
                    _markdown_text(row.get("repeatability_status")),
                    _markdown_text(row.get("speed_repeatability_status")),
                    _markdown_text(row.get("repeatability_stable_value")),
                    _markdown_text(row.get("valuable_l4_sample_count")),
                    _markdown_text(row.get("non_valuable_l4_sample_count")),
                    _markdown_text(row.get("positive_speed_sample_count")),
                    _markdown_text(row.get("non_positive_speed_sample_count")),
                    _markdown_text(row.get("speedups_vs_pure_qe")),
                    _markdown_text(row.get("blockers")),
                ]
            )
            + " |"
        )
    rows.extend(
        [
            "",
            "## Claim boundary",
            "",
            _markdown_text(report.get("claim_boundary")),
            "",
        ]
    )
    return "\n".join(rows)


def render_offload_bundle_viability_report_markdown(
    report: Mapping[str, Any],
) -> str:
    rows = [
        "# QE offload bundle viability report",
        "",
        f"- status: `{_markdown_text(report.get('status'))}`",
        f"- bundle_count: `{report.get('bundle_count', 0)}`",
        f"- larger_granularity_bundle_count: `{report.get('larger_granularity_bundle_count', 0)}`",
        f"- bundles_with_raw_valuable_members_count: `{report.get('bundles_with_raw_valuable_members_count', 0)}`",
        f"- bundles_with_stable_repeatable_members_count: `{report.get('bundles_with_stable_repeatable_members_count', 0)}`",
        f"- single_workflow_bundle_candidates_with_stable_members_count: `{report.get('single_workflow_bundle_candidates_with_stable_members_count', 0)}`",
        f"- stable_repeatable_member_configuration_count: `{report.get('stable_repeatable_member_configuration_count', 0)}`",
        f"- bundle_level_valuable_l4_count: `{report.get('bundle_level_valuable_l4_count', 0)}`",
        f"- deliverable_complete: `{str(report.get('deliverable_complete', False)).lower()}`",
        "",
        "## Bundle rows",
        "",
        "| bundle_id | status | granularity | single_workflow | workload | stage | kernels | attempted | ready | valuable_members | stable_members | blockers | next action |",
        "|---|---|---|---|---|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in report.get("rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        rows.append(
            "| "
            + " | ".join(
                [
                    _markdown_text(row.get("bundle_id")),
                    _markdown_text(row.get("viability_status")),
                    _markdown_text(row.get("granularity")),
                    _markdown_text(row.get("runnable_as_single_qe_workflow")),
                    _markdown_text(row.get("workload_case_id")),
                    _markdown_text(row.get("stage_type")),
                    _markdown_text(
                        row.get("kernel_list") or row.get("kernel_families")
                    ),
                    _markdown_text(row.get("attempted_member_count")),
                    _markdown_text(row.get("replacement_ready_member_count")),
                    _markdown_text(row.get("valuable_l4_member_count")),
                    _markdown_text(row.get("stable_repeatable_value_member_count")),
                    _markdown_text(row.get("blockers")),
                    _markdown_text(row.get("recommended_next_action")),
                ]
            )
            + " |"
        )
    stable_configs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for row in report.get("rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        for config in row.get("stable_repeatable_member_configurations", []) or []:
            if isinstance(config, Mapping):
                stable_configs.append((row, config))
    if stable_configs:
        rows.extend(
            [
                "",
                "## Stable repeatable member configurations",
                "",
                "| bundle_id | opportunity_id | kernel | workload_variant | replacement_config | speedups_vs_pure_qe |",
                "|---|---|---|---|---|---|",
            ]
        )
        for bundle_row, config in stable_configs:
            rows.append(
                "| "
                + " | ".join(
                    [
                        _markdown_text(bundle_row.get("bundle_id")),
                        _markdown_text(config.get("opportunity_id")),
                        _markdown_text(config.get("kernel")),
                        _markdown_text(config.get("workload_variant_id")),
                        _markdown_text(
                            config.get("replacement_configuration_identity_key")
                        ),
                        _markdown_text(config.get("speedups_vs_pure_qe")),
                    ]
                )
                + " |"
            )
    rows.extend(
        [
            "",
            "## Claim boundary",
            "",
            _markdown_text(report.get("claim_boundary")),
            "",
        ]
    )
    return "\n".join(rows)


def render_accelerated_replacement_readiness_report_markdown(
    report: Mapping[str, Any],
) -> str:
    rows = [
        "# QE accelerated replacement readiness report",
        "",
        f"- status: `{_markdown_text(report.get('status'))}`",
        f"- row_count: `{report.get('row_count', 0)}`",
        f"- attempted_row_count: `{report.get('attempted_row_count', 0)}`",
        f"- replacement_ready_count: `{report.get('replacement_ready_count', 0)}`",
        f"- accelerated_results_consumed_by_qe_count: `{report.get('accelerated_results_consumed_by_qe_count', 0)}`",
        f"- accelerated_results_observed_by_qe_before_strict_replacement_count: `{report.get('accelerated_results_observed_by_qe_before_strict_replacement_count', 0)}`",
        f"- qe_kernel_work_replaced_on_critical_path_count: `{report.get('qe_kernel_work_replaced_on_critical_path_count', 0)}`",
        f"- external_accelerated_results_consumed_by_qe_count: `{report.get('external_accelerated_results_consumed_by_qe_count', 0)}`",
        f"- external_consumed_but_blocked_count: `{report.get('external_consumed_but_blocked_count', 0)}`",
        f"- component_model_boundary_blocked_count: `{report.get('component_model_boundary_blocked_count', 0)}`",
        f"- patch_precheck_linked_count: `{report.get('patch_precheck_linked_count', 0)}`",
        f"- patch_precheck_writeback_count: `{report.get('patch_precheck_writeback_count', 0)}`",
        f"- patch_precheck_component_model_blocked_count: `{report.get('patch_precheck_component_model_blocked_count', 0)}`",
        f"- patch_precheck_trusted_l4_replacement_candidate_count: `{report.get('patch_precheck_trusted_l4_replacement_candidate_count', 0)}`",
        f"- software_fallback_on_critical_path_count: `{report.get('software_fallback_on_critical_path_count', 0)}`",
        f"- target_kernel_mismatch_count: `{report.get('target_kernel_mismatch_count', 0)}`",
        f"- missing_or_not_attempted_replacement_count: `{report.get('missing_or_not_attempted_replacement_count', 0)}`",
        f"- replacement_blocker_count: `{report.get('replacement_blocker_count', 0)}`",
        f"- non_hpsi_non_spsi_replacement_ready_count: `{report.get('non_hpsi_non_spsi_replacement_ready_count', 0)}`",
        f"- non_hpsi_non_spsi_replacement_blocked_count: `{report.get('non_hpsi_non_spsi_replacement_blocked_count', 0)}`",
        f"- value_claim_allowed_by_replacement_gate: `{str(report.get('value_claim_allowed_by_replacement_gate', False)).lower()}`",
        f"- deliverable_complete: `{str(report.get('deliverable_complete', False)).lower()}`",
        "",
        "## Next non-h_psi/non_s_psi strict replacement targets",
        "",
        "| opportunity_id | workload | kernel | speed | speedup | patch_precheck | patch_writeback | patch_output_data_path | next action | blockers |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in report.get("next_non_hpsi_non_spsi_replacement_targets", []) or []:
        if not isinstance(row, Mapping):
            continue
        rows.append(
            "| "
            + " | ".join(
                _markdown_text(row.get(key))
                for key in (
                    "opportunity_id",
                    "workload_case_id",
                    "kernel",
                    "speed_status",
                    "speedup_vs_pure_qe",
                    "patch_replacement_precheck_status",
                    "patch_accelerated_result_writeback_present",
                    "patch_accelerated_output_data_path_declared",
                    "recommended_next_action",
                    "replacement_blockers",
                )
            )
            + " |"
        )
    rows.extend(
        [
            "",
        "## Replacement rows",
        "",
        "| opportunity_id | workload | kernel | label | real_l4 | correctness | speed | replacement | replacement_target | target_matches | consumed_by_qe | kernel_work_replaced_on_path | external_consumption | component_blocked | patch_precheck | patch_modes | fallback_on_path | next action |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in report.get("rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        rows.append(
            "| "
            + " | ".join(
                _markdown_text(row.get(key))
                for key in (
                    "opportunity_id",
                    "workload_case_id",
                    "kernel",
                    "value_label",
                    "real_l4_status",
                    "correctness_status",
                    "speed_status",
                    "accelerated_replacement_status",
                    "accelerated_replacement_target_kernel",
                    "accelerated_replacement_target_kernel_matches_selected",
                    "accelerated_results_consumed_by_qe",
                    "qe_kernel_work_replaced_on_critical_path",
                    "external_consumption_evidence_status",
                    "component_model_boundary_blocks_replacement",
                    "patch_replacement_precheck_status",
                    "patch_replacement_modes",
                    "software_fallback_on_critical_path",
                    "recommended_next_action",
                )
            )
            + " |"
        )
    rows.extend(
        [
            "",
            "## Claim boundary",
            "",
            _markdown_text(report.get("claim_boundary")),
            "",
        ]
    )
    return "\n".join(rows)


def render_prompt_to_artifact_checklist_markdown(
    checklist: Mapping[str, Any],
) -> str:
    rows = [
        "# QE callgraph offload prompt-to-artifact checklist",
        "",
        f"- status: `{_markdown_text(checklist.get('status'))}`",
        "",
        "| requirement | artifact | status |",
        "|---|---|---|",
    ]
    for row in checklist.get("checks", []) or []:
        if not isinstance(row, Mapping):
            continue
        rows.append(
            "| "
            + " | ".join(
                _markdown_text(row.get(key))
                for key in ("requirement", "artifact", "status")
            )
            + " |"
        )
    rows.extend(
        [
            "",
            "## Claim boundary",
            "",
            _markdown_text(checklist.get("claim_boundary")),
            "",
        ]
    )
    return "\n".join(rows)


def offload_artifact_bundle(
    *, source_root: Path | str | None = None
) -> Dict[str, Dict[str, Any]]:
    inventory = build_qe_callgraph_inventory(source_root=source_root)
    opportunities = build_offload_opportunity_manifest(inventory)
    workload_variants = build_workload_variant_search_space(opportunities)
    bundles = build_offload_bundle_search_space(opportunities)
    patches = build_qe_callsite_patch_manifest(bundles)
    bundle_runtime_contract = build_bundle_runtime_contract_report(
        bundles,
        opportunity_manifest=opportunities,
    )
    bundle_harness_readiness = build_bundle_harness_readiness_report(
        bundles,
        patches,
        runtime_capabilities=bundle_runtime_contract,
    )
    static_candidate_summary = dict(
        dict(inventory.get("static_callgraph") or {}).get(
            "offload_candidate_summary"
        )
        or {}
    )
    attempt_queue = build_l4_offload_attempt_queue(
        bundles,
        static_candidate_summary=static_candidate_summary,
    )
    matrix = build_offload_value_l4_evidence_matrix(opportunities)
    value_report = build_offload_value_report(matrix)
    blocker_report = build_callgraph_offload_blocker_report(inventory, matrix)
    replacement_report = build_accelerated_replacement_readiness_report(
        matrix,
        opportunity_manifest=opportunities,
        patch_manifest=patches,
    )
    selection_report = build_offload_selection_search_report(
        opportunities,
        matrix,
        blocker_report,
        workload_variants,
        inventory,
    )
    identity_schema = build_offload_target_identity_schema()
    checklist = build_prompt_to_artifact_checklist(
        inventory=inventory,
        opportunities=opportunities,
        workload_variants=workload_variants,
        bundles=bundles,
        patches=patches,
        attempt_queue=attempt_queue,
        matrix=matrix,
        value_report=value_report,
        blocker_report=blocker_report,
        replacement_report=replacement_report,
        selection_report=selection_report,
        identity_schema=identity_schema,
        bundle_runtime_contract=bundle_runtime_contract,
        bundle_harness_readiness=bundle_harness_readiness,
    )
    return {
        "qe_callgraph_inventory.json": inventory,
        "offload_opportunity_manifest.json": opportunities,
        "offload_workload_variant_search_space.json": workload_variants,
        "offload_target_identity_schema.json": identity_schema,
        "offload_bundle_search_space.json": bundles,
        "qe_callsite_patch_manifest.json": patches,
        "bundle_runtime_contract_report.json": bundle_runtime_contract,
        "bundle_harness_readiness_report.json": bundle_harness_readiness,
        "l4_offload_attempt_queue.json": attempt_queue,
        "offload_value_l4_evidence_matrix.json": matrix,
        "offload_value_report.json": value_report,
        "callgraph_offload_blocker_report.json": blocker_report,
        "accelerated_replacement_readiness_report.json": replacement_report,
        "offload_selection_search_report.json": selection_report,
        "prompt_to_artifact_checklist.json": checklist,
    }


def build_prompt_to_artifact_checklist(**artifacts: Mapping[str, Any]) -> Dict[str, Any]:
    checks = [
        {
            "requirement": "offload_target_parameters identity exists",
            "artifact": "offload_target_identity_schema.json",
            "status": "passed" if artifacts["identity_schema"].get("new_identity_layer") == OFFLOAD_TARGET_LAYER else "failed",
        },
        {
            "requirement": "QE callgraph inventory exists",
            "artifact": "qe_callgraph_inventory.json",
            "status": "passed" if artifacts["inventory"].get("node_count", 0) > 0 else "blocked",
        },
        {
            "requirement": "whole-QE static callgraph incompleteness is explicit",
            "artifact": "qe_callgraph_inventory.json",
            "status": (
                "passed"
                if artifacts["inventory"].get("full_static_qe_callgraph_complete")
                is True
                or any(
                    blocker.get("id")
                    == "blocked_full_static_qe_callgraph_parser_not_yet_complete"
                    for blocker in artifacts["inventory"].get("blockers", []) or []
                    if isinstance(blocker, Mapping)
                )
                else "failed"
            ),
        },
        {
            "requirement": "opportunities are classified",
            "artifact": "offload_opportunity_manifest.json",
            "status": "passed" if artifacts["opportunities"].get("all_opportunities_classified") is True else "failed",
        },
        {
            "requirement": "workload/offload selection axes are explicit",
            "artifact": "offload_opportunity_manifest.json",
            "status": (
                "passed"
                if all(
                    isinstance(row, Mapping)
                    and dict(row.get("workload_selection") or {}).get("selection_axes")
                    for row in artifacts["opportunities"].get("opportunities", []) or []
                )
                else "failed"
            ),
        },
        {
            "requirement": "formal workload-variant search space exists",
            "artifact": "offload_workload_variant_search_space.json",
            "status": (
                "passed"
                if artifacts["workload_variants"].get("schema_version")
                == WORKLOAD_VARIANT_SEARCH_SCHEMA
                and artifacts["workload_variants"].get(
                    "formal_workload_variant_count", 0
                )
                >= 1
                and artifacts["workload_variants"].get(
                    "canonical_replacement_requires_explicit_binding"
                )
                is True
                else "failed"
            ),
        },
        {
            "requirement": "h_psi-only cannot complete",
            "artifact": "offload_bundle_search_space.json",
            "status": "passed" if artifacts["bundles"].get("hpsi_only_completion_allowed") is False else "failed",
        },
        {
            "requirement": "projection cannot claim value",
            "artifact": "offload_value_l4_evidence_matrix.json",
            "status": "passed" if artifacts["matrix"].get("projection_only_value_allowed") is False else "failed",
        },
        {
            "requirement": "smoke/dataflow evidence cannot claim actual-compute or valuable_l4",
            "artifact": "offload_value_l4_evidence_matrix.json",
            "status": (
                "passed"
                if artifacts["matrix"].get("smoke_value_allowed") is False
                and artifacts["matrix"].get("actual_compute_full_qe_evidence_required")
                is True
                else "failed"
            ),
        },
        {
            "requirement": "valuable_l4 remains gated on real L4, correctness, replacement, baseline, and positive speed",
            "artifact": "offload_value_l4_evidence_matrix.json + accelerated_replacement_readiness_report.json",
            "status": (
                "passed"
                if artifacts["matrix"].get("projection_only_value_allowed") is False
                and artifacts["matrix"].get("smoke_value_allowed") is False
                and artifacts["matrix"].get("actual_compute_full_qe_evidence_required")
                is True
                and "value_claim_allowed_by_replacement_gate"
                in artifacts["replacement_report"]
                else "failed"
            ),
        },
        {
            "requirement": "first pass cannot claim deliverable_complete",
            "artifact": "offload_value_report.json",
            "status": "passed" if artifacts["value_report"].get("claims", {}).get("deliverable_complete") is False else "failed",
        },
        {
            "requirement": "L4 attempt queue exists but cannot claim value",
            "artifact": "l4_offload_attempt_queue.json",
            "status": "passed" if artifacts["attempt_queue"].get("deliverable_complete") is False else "failed",
        },
        {
            "requirement": "DSE ranks which workload/callsite/bundle to offload",
            "artifact": "offload_selection_search_report.json",
            "status": (
                "passed"
                if artifacts["selection_report"].get("ranked_opportunity_count")
                == artifacts["opportunities"].get("opportunity_count")
                and artifacts["selection_report"].get("projection_only_value_allowed")
                is False
                else "failed"
            ),
        },
        {
            "requirement": "bundle/member evidence is separated from bundle-level value",
            "artifact": "offload_bundle_viability_report.json",
            "status": (
                "passed"
                if artifacts.get("bundle_viability_report") is None
                or (
                    artifacts["bundle_viability_report"].get(
                        "bundle_level_valuable_l4_count", 0
                    )
                    == 0
                    and artifacts["bundle_viability_report"].get(
                        "deliverable_complete"
                    )
                    is False
                )
                else "failed"
            ),
            "evidence": (
                "no bundle viability report in static artifact bundle"
                if artifacts.get("bundle_viability_report") is None
                else {
                    "larger_granularity_bundle_count": artifacts[
                        "bundle_viability_report"
                    ].get("larger_granularity_bundle_count", 0),
                    "bundles_with_raw_valuable_members_count": artifacts[
                        "bundle_viability_report"
                    ].get("bundles_with_raw_valuable_members_count", 0),
                    "bundles_with_stable_repeatable_members_count": artifacts[
                        "bundle_viability_report"
                    ].get("bundles_with_stable_repeatable_members_count", 0),
                    "bundle_level_valuable_l4_count": artifacts[
                        "bundle_viability_report"
                    ].get("bundle_level_valuable_l4_count", 0),
                }
            ),
        },
        {
            "requirement": "single-QE-workflow bundle evidence is gated separately from member evidence",
            "artifact": "bundle_single_workflow_l4_evidence_report.json",
            "status": (
                "passed"
                if artifacts.get("bundle_single_workflow_report") is None
                or (
                    artifacts["bundle_single_workflow_report"].get(
                        "schema_version"
                    )
                    == "dse.qe_bundle_single_workflow_l4_evidence_report.v1"
                    and artifacts["bundle_single_workflow_report"].get(
                        "deliverable_complete"
                    )
                    is False
                )
                else "failed"
            ),
            "evidence": (
                "no bundle single-workflow report in static artifact bundle"
                if artifacts.get("bundle_single_workflow_report") is None
                else {
                    "status": artifacts["bundle_single_workflow_report"].get(
                        "status"
                    ),
                    "campaign_status_count": artifacts[
                        "bundle_single_workflow_report"
                    ].get("campaign_status_count", 0),
                    "per_opportunity_expanded_campaign_bundle_count": artifacts[
                        "bundle_single_workflow_report"
                    ].get("per_opportunity_expanded_campaign_bundle_count", 0),
                    "bundle_level_valuable_l4_count": artifacts[
                        "bundle_single_workflow_report"
                    ].get("bundle_level_valuable_l4_count", 0),
                }
            ),
        },
        {
            "requirement": "bundle runtime contract is explicit and value-neutral",
            "artifact": "bundle_runtime_contract_report.json",
            "status": (
                "passed"
                if artifacts.get("bundle_runtime_contract") is not None
                and artifacts["bundle_runtime_contract"].get("schema_version")
                == BUNDLE_RUNTIME_CONTRACT_SCHEMA
                and artifacts["bundle_runtime_contract"].get("deliverable_complete")
                is False
                and "not actual-compute evidence"
                in artifacts["bundle_runtime_contract"].get("claim_boundary", "")
                else "failed"
            ),
            "evidence": (
                {
                    "status": artifacts["bundle_runtime_contract"].get("status"),
                    "multi_callsite_bundle_count": artifacts[
                        "bundle_runtime_contract"
                    ].get("multi_callsite_bundle_count", 0),
                    "runtime_contract_ready_bundle_count": artifacts[
                        "bundle_runtime_contract"
                    ].get("runtime_contract_ready_bundle_count", 0),
                }
                if artifacts.get("bundle_runtime_contract") is not None
                else "missing bundle runtime contract report"
            ),
        },
        {
            "requirement": "bundle harness readiness keeps runtime blockers until explicit multi-kernel support",
            "artifact": "bundle_harness_readiness_report.json",
            "status": (
                "passed"
                if artifacts.get("bundle_harness_readiness") is not None
                and artifacts["bundle_harness_readiness"].get(
                    "deliverable_complete"
                )
                is False
                and artifacts["bundle_harness_readiness"].get(
                    "ready_bundle_harness_count", 0
                )
                == 0
                else "failed"
            ),
            "evidence": (
                {
                    "status": artifacts["bundle_harness_readiness"].get("status"),
                    "ready_bundle_harness_count": artifacts[
                        "bundle_harness_readiness"
                    ].get("ready_bundle_harness_count", 0),
                    "blocked_bundle_harness_count": artifacts[
                        "bundle_harness_readiness"
                    ].get("blocked_bundle_harness_count", 0),
                }
                if artifacts.get("bundle_harness_readiness") is not None
                else "missing bundle harness readiness report"
            ),
        },
        {
            "requirement": "GPU availability is baseline context, not value evidence",
            "artifact": "offload_speed_optimization_report.json/status.json",
            "status": (
                "passed"
                if artifacts.get("speed_report") is None
                or (
                    artifacts["speed_report"].get("valuable_l4_count", 0)
                    == artifacts["matrix"].get("valuable_l4_count", 0)
                    and artifacts["speed_report"].get("positive_speed_value_claim_allowed")
                    is False
                )
                else "failed"
            ),
            "evidence": (
                "no speed report in static artifact bundle"
                if artifacts.get("speed_report") is None
                else {
                    "baseline_gpu_context_observed_count": artifacts[
                        "speed_report"
                    ].get("baseline_gpu_context_observed_count", 0),
                    "baseline_gpu_available_count": artifacts["speed_report"].get(
                        "baseline_gpu_available_count", 0
                    ),
                }
            ),
        },
        {
            "requirement": "IC/EDA evidence is optional side evidence and cannot substitute for QE/gem5 value",
            "artifact": "offload_value_l4_evidence_matrix.json",
            "status": (
                "passed"
                if artifacts["matrix"].get("actual_compute_full_qe_evidence_required")
                is True
                and artifacts["matrix"].get("deliverable_complete") is False
                else "failed"
            ),
        },
        {
            "requirement": "accelerated QE replacement gate is explicit",
            "artifact": "accelerated_replacement_readiness_report.json",
            "status": (
                "passed"
                if artifacts["replacement_report"].get("deliverable_complete")
                is False
                and artifacts["replacement_report"].get(
                    "hpsi_only_completion_allowed"
                )
                is False
                and "value_claim_allowed_by_replacement_gate"
                in artifacts["replacement_report"]
                else "failed"
            ),
        },
    ]
    payload = {
        "schema_version": "dse.qe_callgraph_offload_prompt_to_artifact_checklist.v1",
        "status": "passed" if all(row["status"] == "passed" for row in checks) else "partial_or_blocked",
        "checks": checks,
        "claim_boundary": "checklist maps first-pass PRD only; not deliverable_complete",
    }
    payload["checklist_hash"] = _stable_hash_without(payload, "checklist_hash")
    return payload


def write_qe_callgraph_offload_search_artifacts(
    out_dir: Path,
    *,
    source_root: Path | str | None = None,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = offload_artifact_bundle(source_root=source_root)
    artifacts: Dict[str, str] = {}
    for name, payload in bundle.items():
        path = out_dir / name
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        artifacts[name.removesuffix(".json")] = str(path)
    checklist = bundle["prompt_to_artifact_checklist.json"]
    blocker_report = bundle["callgraph_offload_blocker_report.json"]
    replacement_report = bundle["accelerated_replacement_readiness_report.json"]
    value_report = bundle["offload_value_report.json"]
    selection_report = bundle["offload_selection_search_report.json"]
    markdown_outputs = {
        "offload_value_report.md": render_offload_value_report_markdown(
            value_report,
            bundle["offload_value_l4_evidence_matrix.json"],
        ),
        "callgraph_offload_blocker_report.md": (
            render_callgraph_offload_blocker_report_markdown(blocker_report)
        ),
        "accelerated_replacement_readiness_report.md": (
            render_accelerated_replacement_readiness_report_markdown(
                replacement_report
            )
        ),
        "offload_selection_search_report.md": (
            render_offload_selection_search_report_markdown(selection_report)
        ),
        "prompt_to_artifact_checklist.md": (
            render_prompt_to_artifact_checklist_markdown(checklist)
        ),
    }
    for name, text in markdown_outputs.items():
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        artifacts[name.removesuffix(".md") + "_md"] = str(path)
    status_label = checklist["status"]
    if status_label == "passed" and (
        blocker_report.get("status") == "blocked"
        or value_report.get("status") == "partial_or_blocked"
    ):
        status_label = "partial_or_blocked"
    status = {
        "schema_version": "dse.qe_callgraph_offload_artifact_status.v1",
        "status": status_label,
        "release_id": RELEASE_ID,
        "artifacts": artifacts,
        "checklist_hash": checklist["checklist_hash"],
        "deliverable_complete": False,
        "claim_boundary": "artifact emission for first-pass offload search; deliverable_complete is false",
    }
    status["status_hash"] = _stable_hash_without(status, "status_hash")
    (out_dir / "status.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return status


def example_offload_identity_layers() -> Dict[str, Any]:
    base = build_release_subset_manifest()["candidates"][0]["identity"]["identity_layers"]
    return {
        **base,
        OFFLOAD_TARGET_LAYER: example_offload_target_parameters(),
    }
