#!/usr/bin/env python3
"""VASP source-fact importer for the DFT Step1 reference adapter.

This module mirrors the QE ``pw.x`` frontdoor boundary: it parses a small,
deterministic subset of VASP INCAR/KPOINTS/OUTCAR/profile inputs into
provenance-carrying ``SourceFact`` records and then delegates graph construction
to the generic DFT normalizer.  It intentionally emits source/workflow facts
only; it does not claim VASP numerical correctness or select Step2 mappings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from dse_v2.core.workload.importers import ImporterRegistry, WorkloadImporter
from dse_v2.core.workload.package import WorkloadPackage
from dse_v2.core.workload.profiles import WorkloadProfile
from dse_v2.reference_workloads.dft import (
    SourceFact,
    canonicalize_phase_id,
    dft_phase_reference_profile,
    normalize_dft_case_from_facts,
    package_from_dft_case,
)


_VASP_FLOAT = r"[-+]?\d+(?:\.\d*)?(?:[eEdD][-+]?\d+)?"
_VASP_ASSIGNMENT_RE = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>[^;#!]+)"
)


def _read_text_source(source: Any) -> tuple[str, Optional[str]]:
    if source is None:
        return "", None
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8"), str(source)
    if isinstance(source, str):
        path = Path(source)
        if "\n" not in source and path.exists():
            return path.read_text(encoding="utf-8"), str(path)
        return source, None
    raise TypeError(f"expected text or path source, got {type(source).__name__}")


def _strip_vasp_comment(line: str) -> str:
    for marker in ("#", "!"):
        if marker in line:
            line = line.split(marker, 1)[0]
    return line.strip()


def _parse_vasp_value(raw: str) -> Any:
    value = raw.strip().rstrip(";").strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered in {".true.", "true", "t"}:
        return True
    if lowered in {".false.", "false", "f"}:
        return False
    normalized = value.replace("D", "E").replace("d", "e")
    try:
        if re.fullmatch(r"[-+]?\d+", normalized):
            return int(normalized)
        if re.fullmatch(_VASP_FLOAT, normalized):
            return float(normalized)
    except Exception:
        pass
    parts = [part for part in value.split() if part]
    if len(parts) > 1:
        return [_parse_vasp_value(part) for part in parts]
    return value


def _fact(
    field: str,
    value: Any,
    *,
    unit: str = "",
    source_type: str,
    source_path: Optional[str],
    evidence_level: str,
    confidence: str = "medium",
    raw_excerpt: Optional[str] = None,
    run_id: Optional[str] = None,
) -> SourceFact:
    return SourceFact(
        field=field,
        value=value,
        unit=unit,
        source_type=source_type,
        source_path=source_path,
        evidence_level=evidence_level,
        confidence=confidence,
        raw_excerpt=raw_excerpt,
        run_id=run_id,
    )


def parse_vasp_incar(source: Any, *, source_path: Optional[str] = None, run_id: Optional[str] = None) -> List[SourceFact]:
    """Parse selected VASP INCAR settings into DFT source facts."""
    text, detected_path = _read_text_source(source)
    path = source_path or detected_path
    facts: List[SourceFact] = []
    assignments: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = _strip_vasp_comment(raw_line)
        if not line:
            continue
        for segment in line.split(";"):
            match = _VASP_ASSIGNMENT_RE.search(segment)
            if not match:
                continue
            key = match.group("key").upper()
            value = _parse_vasp_value(match.group("value"))
            assignments[key] = value
            field = _vasp_incar_field(key)
            if field is None:
                continue
            facts.append(_fact(
                field,
                value,
                unit=_vasp_field_unit(field),
                source_type="input",
                source_path=path,
                evidence_level="declared_input",
                confidence="medium",
                raw_excerpt=segment.strip(),
                run_id=run_id,
            ))
    if "EDIFF" in assignments:
        facts.append(_fact(
            "parameter.conv_thr",
            assignments["EDIFF"],
            unit="eV",
            source_type="input",
            source_path=path,
            evidence_level="declared_input",
            confidence="medium",
            raw_excerpt="EDIFF",
            run_id=run_id,
        ))
    return facts


def _vasp_incar_field(key: str) -> Optional[str]:
    mapping = {
        "ENCUT": "parameter.ecutwfc",
        "NBANDS": "dimension.nbnd",
        "ISPIN": "dimension.nspin",
        "NELM": "iteration.scf.maxstep",
        "PREC": "parameter.precision",
        "ALGO": "parameter.diagonalization",
        "GGA": "parameter.input_dft",
        "METAGGA": "parameter.input_dft",
        "LHFCALC": "parameter.hybrid_exact_exchange",
    }
    return mapping.get(key)


def _vasp_field_unit(field: str) -> str:
    if field == "parameter.ecutwfc":
        return "eV"
    if field.startswith("dimension.") or field.startswith("iteration."):
        return "count"
    return ""


def parse_vasp_kpoints(source: Any, *, source_path: Optional[str] = None, run_id: Optional[str] = None) -> List[SourceFact]:
    """Parse a deterministic subset of VASP KPOINTS automatic meshes."""
    text, detected_path = _read_text_source(source)
    path = source_path or detected_path
    lines = [_strip_vasp_comment(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    facts: List[SourceFact] = []
    if len(lines) < 4:
        return facts
    mode = lines[2].strip().lower()
    facts.append(_fact(
        "input.k_points_mode",
        mode,
        source_type="input",
        source_path=path,
        evidence_level="declared_input",
        confidence="medium",
        raw_excerpt=lines[2],
        run_id=run_id,
    ))
    grid_parts = [int(float(part)) for part in lines[3].split()[:3] if re.fullmatch(r"[-+]?\d+(?:\.0*)?", part)]
    if len(grid_parts) == 3:
        facts.append(_fact(
            "dimension.kpoint_grid",
            grid_parts,
            unit="grid",
            source_type="input",
            source_path=path,
            evidence_level="declared_input",
            confidence="medium",
            raw_excerpt=lines[3],
            run_id=run_id,
        ))
        facts.append(_fact(
            "dimension.kpoint_count",
            max(1, grid_parts[0] * grid_parts[1] * grid_parts[2]),
            unit="count",
            source_type="heuristic",
            source_path=path,
            evidence_level="pre_symmetry_estimate",
            confidence="low",
            raw_excerpt=lines[3],
            run_id=run_id,
        ))
    return facts


def parse_vasp_poscar(source: Any, *, source_path: Optional[str] = None, run_id: Optional[str] = None) -> List[SourceFact]:
    """Parse POSCAR species/count metadata needed by the generic DFT normalizer."""
    text, detected_path = _read_text_source(source)
    path = source_path or detected_path
    lines = [_strip_vasp_comment(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < 7:
        return []
    count_line_index = 6
    counts = [int(float(part)) for part in lines[count_line_index].split() if re.fullmatch(r"[-+]?\d+(?:\.0*)?", part)]
    if not counts:
        count_line_index = 5
        counts = [int(float(part)) for part in lines[count_line_index].split() if re.fullmatch(r"[-+]?\d+(?:\.0*)?", part)]
    facts: List[SourceFact] = []
    if counts:
        facts.append(_fact(
            "dimension.nat",
            sum(counts),
            unit="count",
            source_type="input",
            source_path=path,
            evidence_level="declared_input",
            confidence="medium",
            raw_excerpt=lines[count_line_index],
            run_id=run_id,
        ))
        facts.append(_fact(
            "dimension.ntyp",
            len(counts),
            unit="count",
            source_type="input",
            source_path=path,
            evidence_level="declared_input",
            confidence="medium",
            raw_excerpt=lines[count_line_index - 1] if count_line_index > 0 else lines[count_line_index],
            run_id=run_id,
        ))
    return facts


def parse_vasp_outcar(source: Any, *, source_path: Optional[str] = None, run_id: Optional[str] = None) -> List[SourceFact]:
    """Parse selected observed dimensions and timing facts from VASP OUTCAR."""
    text, detected_path = _read_text_source(source)
    path = source_path or detected_path
    facts: List[SourceFact] = []
    iteration_count = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if not line:
            continue
        match = re.search(r"nkpts\s*=\s*(\d+)", lower)
        if match:
            facts.append(_fact("dimension.kpoint_count", int(match.group(1)), unit="count", source_type="log", source_path=path, evidence_level="observed_preprocessed", confidence="high", raw_excerpt=line, run_id=run_id))
            continue
        match = re.search(r"nbands\s*[=:]\s*(\d+)", lower)
        if match:
            facts.append(_fact("dimension.nbnd", int(match.group(1)), unit="count", source_type="log", source_path=path, evidence_level="observed_preprocessed", confidence="high", raw_excerpt=line, run_id=run_id))
            continue
        match = re.search(r"nions\s*=\s*(\d+)", lower)
        if match:
            facts.append(_fact("dimension.nat", int(match.group(1)), unit="count", source_type="log", source_path=path, evidence_level="observed_preprocessed", confidence="high", raw_excerpt=line, run_id=run_id))
            continue
        match = re.search(r"number of plane waves\s*[=:]\s*(\d+)", lower)
        if match:
            facts.append(_fact("dimension.npw", int(match.group(1)), unit="count", source_type="log", source_path=path, evidence_level="observed_preprocessed", confidence="high", raw_excerpt=line, run_id=run_id))
            continue
        match = re.search(r"ngx\s*=\s*(\d+).*?ngy\s*=\s*(\d+).*?ngz\s*=\s*(\d+)", lower)
        if match:
            grid = [int(match.group(1)), int(match.group(2)), int(match.group(3))]
            facts.append(_fact("dimension.fft_grid", grid, unit="grid", source_type="log", source_path=path, evidence_level="observed_preprocessed", confidence="medium", raw_excerpt=line, run_id=run_id))
            facts.append(_fact("dimension.nfft", grid[0] * grid[1] * grid[2], unit="count", source_type="log", source_path=path, evidence_level="observed_preprocessed", confidence="medium", raw_excerpt=line, run_id=run_id))
            continue
        if re.search(r"\biteration\s+\d+", lower):
            iteration_count += 1
        timing = _parse_vasp_timing_line(line)
        if timing is not None:
            label, seconds = timing
            phase_id = _vasp_phase_id(label)
            facts.append(_fact(
                f"phase_timing.{phase_id}.wall_seconds",
                seconds,
                unit="s",
                source_type="log",
                source_path=path,
                evidence_level="observed_timing",
                confidence="medium",
                raw_excerpt=line,
                run_id=run_id,
            ))
    if iteration_count:
        facts.append(_fact("iteration.scf.count", iteration_count, unit="count", source_type="log", source_path=path, evidence_level="observed_runtime", confidence="medium", raw_excerpt="counted VASP iteration lines", run_id=run_id))
    return facts


def parse_vasp_profile(source: Any, *, source_path: Optional[str] = None, run_id: Optional[str] = None) -> List[SourceFact]:
    """Parse VASP timing/profile summaries from JSON, mappings, or simple text."""
    path = source_path
    payload: Any = source
    if isinstance(source, (str, Path)):
        text, detected_path = _read_text_source(source)
        path = path or detected_path
        stripped = text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            payload = json.loads(stripped)
        else:
            return _parse_vasp_profile_text(text, source_path=path, run_id=run_id)
    facts: List[SourceFact] = []
    if isinstance(payload, Mapping):
        items = payload.get("phases", payload.get("phase_timings", payload))
        if isinstance(items, Mapping):
            iterable = items.items()
        elif isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
            iterable = []
            for item in items:
                if isinstance(item, Mapping):
                    label = item.get("phase_id", item.get("phase", item.get("label", item.get("name", "unknown"))))
                    seconds = item.get("wall_seconds", item.get("seconds", item.get("time_seconds")))
                    iterable.append((label, seconds))
        else:
            iterable = []
        for label, seconds in iterable:
            if seconds is None:
                continue
            try:
                value = float(seconds)
            except Exception:
                continue
            phase_id = _vasp_phase_id(str(label))
            facts.append(_fact(
                f"phase_timing.{phase_id}.wall_seconds",
                value,
                unit="s",
                source_type="profile",
                source_path=path,
                evidence_level="observed_timing",
                confidence="high",
                raw_excerpt=f"{label}: {seconds}",
                run_id=run_id,
            ))
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        for item in payload:
            if isinstance(item, Mapping):
                facts.extend(parse_vasp_profile({"phases": [item]}, source_path=path, run_id=run_id))
    return facts


def _parse_vasp_profile_text(text: str, *, source_path: Optional[str], run_id: Optional[str]) -> List[SourceFact]:
    facts: List[SourceFact] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        timing = _parse_vasp_timing_line(line)
        if timing is not None:
            label, seconds = timing
        else:
            parts = re.split(r"[,\s:]+", line)
            if len(parts) < 2:
                continue
            label = parts[0]
            try:
                seconds = float(parts[1])
            except Exception:
                continue
        phase_id = _vasp_phase_id(label)
        facts.append(_fact(
            f"phase_timing.{phase_id}.wall_seconds",
            seconds,
            unit="s",
            source_type="profile",
            source_path=source_path,
            evidence_level="observed_timing",
            confidence="high",
            raw_excerpt=line,
            run_id=run_id,
        ))
    return facts


def _parse_vasp_timing_line(line: str) -> Optional[tuple[str, float]]:
    match = re.match(
        rf"^\s*(?P<label>[A-Za-z0-9_()./+:-]+)\s*[:=]\s*(?P<seconds>{_VASP_FLOAT})\s*(?:s|sec|seconds)?\s*$",
        line,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            rf"\b(?P<label>FFT|DAV|RMM(?:-DIIS)?|ORTHCH|CHARGE|MIXING|HAMILT|LOOP)\b.*?(?P<seconds>{_VASP_FLOAT})\s*(?:s|sec|seconds)?",
            line,
            re.IGNORECASE,
        )
    if not match:
        return None
    return match.group("label"), float(match.group("seconds").replace("D", "E").replace("d", "e"))


def _vasp_phase_id(label: str) -> str:
    normalized = str(label).strip().lower().replace("-", "_")
    aliases = {
        "dav": "diagonalization",
        "rmm": "diagonalization",
        "rmm_diis": "diagonalization",
        "orthch": "diagonalization",
        "charge": "charge_density",
        "mixing": "mixing",
        "hamilt": "h_psi",
        "loop": "scf_iteration",
    }
    if normalized in aliases:
        return aliases[normalized]
    return canonicalize_phase_id(label, extension_namespace="vasp")


def normalize_vasp_dft_case(
    facts: Sequence[SourceFact | Mapping[str, Any]],
    *,
    case_id: str = "vasp_static_case",
    profile_id: str = "dft_vasp_static",
    importer_id: str = "dft_vasp",
    claim_boundary: str = "diagnostic",
    parameters: Optional[Mapping[str, Any]] = None,
):
    return normalize_dft_case_from_facts(
        facts,
        case_id=case_id,
        source_program="vasp",
        workload_family="dft",
        profile_id=profile_id,
        importer_id=importer_id,
        claim_boundary=claim_boundary,
        parameters=parameters,
    )


class DftVaspImporter(WorkloadImporter):
    """VASP source importer for the DFT-first Step1 frontdoor."""

    importer_id = "dft_vasp"
    importer_version = "v1"
    supported_source_kinds = [
        "vasp_bundle",
        "vasp_incar",
        "vasp_kpoints",
        "vasp_poscar",
        "vasp_outcar",
        "vasp_profile",
        "dft_config",
        "generated",
    ]
    compatible_profiles = ["dft_vasp_static", "dft"]

    def import_workload(
        self,
        source: Any = None,
        *,
        profile: WorkloadProfile | Mapping[str, Any],
        parameters: Optional[Mapping[str, Any]] = None,
    ) -> WorkloadPackage:
        parameters = dict(parameters or {})
        profile_payload = profile.to_dict() if isinstance(profile, WorkloadProfile) else dict(profile)
        profile_id = str(profile_payload.get("profile_id", "dft_vasp_static"))
        claim_boundary = str(parameters.get("claim_boundary", profile_payload.get("default_claim_boundary", "diagnostic")))
        case_id = str(parameters.get("case_id", parameters.get("workload_id", parameters.get("graph_id", "vasp_static_case"))))
        source_kind = str(parameters.get("source_kind", "vasp_bundle"))
        run_id = str(parameters.get("run_id")) if parameters.get("run_id") is not None else None

        if hasattr(source, "to_dict") and getattr(source, "schema_version", "") == "dse.dft.case.v1":
            case = source
        else:
            facts = self._collect_facts(source, parameters, source_kind=source_kind, run_id=run_id)
            case = normalize_vasp_dft_case(
                facts,
                case_id=case_id,
                profile_id=profile_id,
                importer_id=self.importer_id,
                claim_boundary=claim_boundary,
                parameters=parameters,
            )
        package = package_from_dft_case(
            case,
            profile=profile_payload,
            graph_id=str(parameters.get("graph_id", f"{case_id}_graph")),
            source_kind=source_kind,
            source_path=parameters.get("source_path"),
        )
        package.importer["importer_version"] = self.importer_version
        return package

    def _collect_facts(
        self,
        source: Any,
        parameters: Mapping[str, Any],
        *,
        source_kind: str,
        run_id: Optional[str],
    ) -> List[SourceFact]:
        facts: List[SourceFact] = []
        if isinstance(source, Mapping):
            if "facts" in source:
                for item in source.get("facts", []) or []:
                    facts.append(item if isinstance(item, SourceFact) else SourceFact.from_dict(item))
            for source_key, path_key, parser in [
                ("incar", "incar_path", parse_vasp_incar),
                ("kpoints", "kpoints_path", parse_vasp_kpoints),
                ("poscar", "poscar_path", parse_vasp_poscar),
                ("outcar", "outcar_path", parse_vasp_outcar),
                ("profile", "profile_path", parse_vasp_profile),
            ]:
                source_value = _first_present(source, source_key, f"{source_key}_text")
                if source_value is not None:
                    facts.extend(parser(source_value, source_path=_source_path_hint(source, path_key), run_id=run_id))
        elif source is not None:
            parser_by_kind = {
                "vasp_incar": parse_vasp_incar,
                "vasp_kpoints": parse_vasp_kpoints,
                "vasp_poscar": parse_vasp_poscar,
                "vasp_outcar": parse_vasp_outcar,
                "vasp_profile": parse_vasp_profile,
            }
            parser = parser_by_kind.get(source_kind)
            if parser is not None:
                facts.extend(parser(source, source_path=parameters.get("source_path"), run_id=run_id))
        for key, parser in [
            ("incar_path", parse_vasp_incar),
            ("kpoints_path", parse_vasp_kpoints),
            ("poscar_path", parse_vasp_poscar),
            ("outcar_path", parse_vasp_outcar),
            ("profile_path", parse_vasp_profile),
        ]:
            if parameters.get(key):
                facts.extend(parser(str(parameters[key]), source_path=str(parameters[key]), run_id=run_id))
        for key in ["npw", "nfft", "nbnd", "kpoint_count", "nat", "ntyp"]:
            if key in parameters:
                field = "dimension.kpoint_count" if key == "kpoint_count" else f"dimension.{key}"
                facts.append(_fact(
                    field,
                    int(parameters[key]),
                    unit="count",
                    source_type="generated",
                    source_path=parameters.get("source_path"),
                    evidence_level="caller_parameter",
                    confidence="medium",
                    raw_excerpt=f"parameter.{key}",
                    run_id=run_id,
                ))
        return facts


def register_dft_vasp_importer(registry: ImporterRegistry) -> ImporterRegistry:
    return registry.register(DftVaspImporter())


def dft_vasp_profile() -> WorkloadProfile:
    base = dft_phase_reference_profile().to_dict()
    base.update({
        "profile_id": "dft_vasp_static",
        "profile_version": "v1",
        "accepted_source_kinds": list(DftVaspImporter.supported_source_kinds),
        "description": "Optional DFT/VASP static source frontdoor that emits architecture-independent phase/kernel workload facts.",
        "plugin_metadata": {"reference_only": True, "domain": "dft", "source_program": "vasp"},
    })
    return WorkloadProfile.from_dict(base)


def create_dft_vasp_package(source: Any = None, parameters: Optional[Mapping[str, Any]] = None) -> WorkloadPackage:
    return DftVaspImporter().import_workload(source, profile=dft_vasp_profile(), parameters=parameters)


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _source_path_hint(mapping: Mapping[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        if mapping.get(key):
            return str(mapping[key])
    return None
