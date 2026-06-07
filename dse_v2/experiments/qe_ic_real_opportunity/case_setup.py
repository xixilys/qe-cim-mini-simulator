#!/usr/bin/env python3
"""QE-IC case setup for real opportunity campaigns."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


PROGRAM_BY_FAMILY = {
    "ground_state_band_structure": "pw.x",
    "electron_phonon_mobility": "epw.x",
}

GENERATED_CASE_ID_BY_FAMILY = {
    "ground_state_band_structure": "generated_silicon_scf_pw_v0",
    "electron_phonon_mobility": "generated_epw_proxy_v0",
}
SILICON_PSEUDO_NAMES = (
    "Si.pbe-n-kjpaw_psl.1.0.0.UPF",
    "Si.pbe-n-rrkjus_psl.1.0.0.UPF",
    "Si.pz-vbc.UPF",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _case_id(workload_family_id: str) -> str:
    if workload_family_id == "ground_state_band_structure":
        return "ground_state_band_structure_initial_real_case"
    if workload_family_id == "electron_phonon_mobility":
        return "electron_phonon_mobility_initial_real_case"
    return f"{workload_family_id}_initial_real_case"


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _search_roots(config: Mapping[str, Any]) -> list[Path]:
    roots: list[Path] = []
    for value in _as_list(config.get("input_deck_search_paths")):
        if isinstance(value, str) and value:
            roots.append(Path(value).expanduser())
    for env_name in ("QE_INPUT_DIR", "QE_EXAMPLES_DIR", "ESPRESSO_ROOT", "QE_ROOT"):
        value = os.environ.get(env_name)
        if not value:
            continue
        root = Path(value).expanduser()
        roots.extend([root, root / "examples"])
    repo = _repo_root()
    roots.extend(
        [
            repo / "dse_v2" / "testdata" / "qe_ic_real_opportunity",
            repo / "examples",
            repo / "runs" / "qe_ic_real_opportunity",
            repo / "artifacts" / "qe_ic_real_opportunity_inputs",
            repo.parent / "qe" / "examples",
            repo.parent / "espresso" / "examples",
            Path("/usr/local/share/qe/examples"),
            Path("/opt/qe/examples"),
            Path("/opt/espresso/examples"),
        ]
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _pseudo_search_roots(config: Mapping[str, Any] | None = None) -> list[Path]:
    roots: list[Path] = []
    config_map = _as_mapping(config)
    for value in _as_list(config_map.get("pseudo_search_paths")):
        if isinstance(value, str) and value:
            roots.append(Path(value).expanduser())
    for key in ("pseudo_dir", "qe_pseudo_dir"):
        value = config_map.get(key)
        if isinstance(value, str) and value:
            roots.append(Path(value).expanduser())
    for env_name in ("QE_PSEUDO_DIR", "ESPRESSO_PSEUDO", "PSEUDO_DIR"):
        value = os.environ.get(env_name)
        if value:
            roots.append(Path(value).expanduser())
    roots.extend(
        [
            Path.cwd() / "pseudo",
            _repo_root() / "pseudo",
            Path("/usr/share/espresso/pseudo"),
            Path("/usr/local/share/qe/pseudo"),
            Path("/opt/qe/pseudo"),
        ]
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _discover_pseudopotential(
    *,
    config: Mapping[str, Any] | None = None,
    names: tuple[str, ...] = SILICON_PSEUDO_NAMES,
) -> Path | None:
    for root in _pseudo_search_roots(config):
        if not root.exists():
            continue
        if root.is_file() and root.name in names:
            return root
        for name in names:
            direct = root / name
            if direct.exists() and direct.is_file():
                return direct
        for candidate in root.rglob("*.UPF"):
            if candidate.name in names:
                return candidate
    return None


def _candidate_deck_names(workload_family_id: str, program: str) -> list[str]:
    stem = workload_family_id
    names = [
        f"{stem}.in",
        f"{stem}.pwi",
        f"{stem}.pw.in",
        f"{program}.in",
    ]
    if workload_family_id == "ground_state_band_structure":
        names.extend(["scf.in", "bands.in", "pw.in"])
    if workload_family_id == "electron_phonon_mobility":
        names.extend(["epw.in", "ph.in", "mobility.in"])
    return list(dict.fromkeys(names))


def _discover_input_deck(
    *,
    config: Mapping[str, Any],
    workload_family_id: str,
    program: str,
) -> Path | None:
    input_decks = _as_mapping(config.get("input_decks"))
    deck_value = input_decks.get(workload_family_id)
    if isinstance(deck_value, str) and deck_value:
        deck_path = Path(deck_value).expanduser()
        return deck_path if deck_path.exists() else None
    names = _candidate_deck_names(workload_family_id, program)
    for root in _search_roots(config):
        if not root.exists():
            continue
        if root.is_file() and root.name in names:
            return root
        for name in names:
            direct = root / name
            if direct.exists() and direct.is_file():
                return direct
        for candidate in root.rglob("*.in"):
            if candidate.name in names or workload_family_id in str(candidate):
                return candidate
    return None


def prepare_qe_ic_cases(config: Mapping[str, Any], *, out_dir: Path | None = None) -> list[dict[str, Any]]:
    """Prepare case descriptors or templates without inventing physical inputs."""

    case_selection = config.get("case_selection") if isinstance(config.get("case_selection"), Mapping) else {}
    families = case_selection.get("required_workload_families")
    if not isinstance(families, list):
        families = ["ground_state_band_structure", "electron_phonon_mobility"]
    base_output = out_dir or Path("runs/qe_ic_real_opportunity_campaign")
    cases: list[dict[str, Any]] = []
    for family_id in families:
        program = PROGRAM_BY_FAMILY.get(str(family_id), "pw.x")
        deck_path = _discover_input_deck(config=config, workload_family_id=str(family_id), program=program)
        deck_exists = deck_path is not None and deck_path.exists()
        case_status = "ready" if deck_exists else "input_deck_missing"
        template_path = base_output / "case_templates" / f"{family_id}.in"
        if not deck_exists:
            template_path.parent.mkdir(parents=True, exist_ok=True)
            if not template_path.exists():
                template_path.write_text(
                    "\n".join(
                        [
                            f"# Placeholder QE input deck template for {family_id}.",
                            "# This file is intentionally not physical input data.",
                            "# Replace with a validated QE input deck before running measurements.",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
        cases.append(
            {
                "workload_family_id": family_id,
                "case_id": _case_id(str(family_id)),
                "program": program,
                "input_deck_path": str(deck_path) if deck_path is not None else str(template_path),
                "input_deck_hash": _sha256(deck_path) if deck_exists and deck_path is not None else None,
                "precision": "fp64_mixed",
                "run_command": f"{program} -in {deck_path}" if deck_exists else None,
                "profile_command": f"nsys profile {program} -in {deck_path}" if deck_exists else None,
                "output_directory": str(base_output / str(family_id)),
                "case_status": case_status,
                "evidence_status": "ready_for_run" if deck_exists else "evidence_missing",
                "template_created": not deck_exists,
                "template_note": "Template descriptor only; no physical QE input data is invented.",
            }
        )
    return cases


def generate_qe_ic_benchmark_cases(
    cases: list[Mapping[str, Any]],
    *,
    out_dir: Path,
    config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generate small benchmark/proxy QE input decks for missing cases."""

    generated_dir = out_dir / "generated_inputs"
    generated_dir.mkdir(parents=True, exist_ok=True)
    generated: list[dict[str, Any]] = []
    for case in cases:
        row = dict(case)
        if row.get("case_status") == "ready":
            generated.append(row)
            continue
        family_id = str(row.get("workload_family_id"))
        program = str(row.get("program") or PROGRAM_BY_FAMILY.get(family_id, "pw.x"))
        generated_case_id = GENERATED_CASE_ID_BY_FAMILY.get(family_id, f"generated_{family_id}_benchmark_v0")
        deck_path = generated_dir / f"{generated_case_id}.in"
        pseudo_path = _discover_pseudopotential(config=config) if program == "pw.x" else None
        pseudo_dir = str(pseudo_path.parent) if pseudo_path is not None else "./pseudo"
        pseudo_name = pseudo_path.name if pseudo_path is not None else SILICON_PSEUDO_NAMES[0]
        if program == "epw.x":
            deck_text = "\n".join(
                [
                    "! Generated EPW proxy benchmark descriptor.",
                    "! This is not a real mobility science input.",
                    "&inputepw",
                    "  prefix = 'generated_epw_proxy'",
                    "  outdir = './tmp'",
                    "/",
                    "",
                ]
            )
        else:
            deck_text = "\n".join(
                [
                    "&control",
                    "  calculation = 'scf'",
                    "  prefix = 'generated_silicon_scf_pw_v0'",
                    f"  pseudo_dir = '{pseudo_dir}'",
                    "  outdir = './tmp'",
                    "/",
                    "&system",
                    "  ibrav = 2",
                    "  celldm(1) = 10.2",
                    "  nat = 1",
                    "  ntyp = 1",
                    "  ecutwfc = 10.0",
                    "/",
                    "&electrons",
                    "  conv_thr = 1.0d-6",
                    "/",
                    "ATOMIC_SPECIES",
                    f"  Si 28.0855 {pseudo_name}",
                    "ATOMIC_POSITIONS crystal",
                    "  Si 0.00 0.00 0.00",
                    "K_POINTS automatic",
                    "  1 1 1 0 0 0",
                    "",
                ]
            )
        deck_path.write_text(deck_text, encoding="utf-8")
        row.update(
            {
                "case_id": generated_case_id,
                "input_deck_path": str(deck_path),
                "input_deck_hash": _sha256(deck_path),
                "case_status": "ready",
                "evidence_status": "generated_benchmark",
                "case_origin": "generated_benchmark",
                "scientific_claim_scope": "performance_benchmark_only",
                "run_command": f"{program} -in {deck_path}",
                "profile_command": f"nsys profile {program} -in {deck_path}",
                "template_created": False,
                "template_note": "Generated benchmark/proxy workload; not real device-physics input.",
                "pseudo_file_path": str(pseudo_path) if pseudo_path is not None else None,
                "pseudo_hash": _sha256(pseudo_path) if pseudo_path is not None else None,
                "pseudo_status": "pseudo_available" if pseudo_path is not None else "pseudo_missing",
            }
        )
        generated.append(row)
    return generated
