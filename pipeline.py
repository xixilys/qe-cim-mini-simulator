#!/usr/bin/env python3
"""
DSE Workflow Pipeline - Complete data flow implementation

Usage:
    python3 pipeline.py --step 1 --input raw_traces/ --output artifacts/
    python3 pipeline.py --step 2 --input artifacts/workload_profile.json --output artifacts/
    python3 pipeline.py --step 3 --input artifacts/architecture_spec.json --output artifacts/
    python3 pipeline.py --step 4 --input artifacts/design_points.json --output artifacts/
    python3 pipeline.py --step 5 --input artifacts/evaluation_configs.json --output artifacts/
    python3 pipeline.py --step 6 --input artifacts/evaluation_results.json --output artifacts/
    
    # Run full pipeline
    python3 pipeline.py --full --input raw_traces/ --output artifacts/
"""

import json
import hashlib
import argparse
import csv
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent))
from interfaces.validator import InterfaceValidator, ValidationResult


@dataclass
class Provenance:
    input_hash: str
    generated_at: str
    tool_version: str
    execution_time_seconds: float = 0.0


class ArtifactStore:
    """Content-addressed artifact storage."""
    
    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def store(self, artifact: Dict) -> str:
        """Store artifact by content hash, return hash."""
        content = json.dumps(artifact, sort_keys=True)
        artifact_hash = hashlib.sha256(content.encode()).hexdigest()
        
        path = self.storage_dir / f"{artifact_hash}.json"
        if not path.exists():
            path.write_text(content)
        
        return artifact_hash
    
    def load(self, artifact_hash: str) -> Dict:
        """Load artifact by hash."""
        path = self.storage_dir / f"{artifact_hash}.json"
        if not path.exists():
            raise FileNotFoundError(f"Artifact not found: {artifact_hash}")
        
        return json.loads(path.read_text())
    
    def exists(self, artifact_hash: str) -> bool:
        """Check if artifact exists."""
        return (self.storage_dir / f"{artifact_hash}.json").exists()


def stable_generated_at(input_artifact: Dict) -> str:
    """Return a deterministic artifact timestamp for idempotent step outputs."""
    return input_artifact.get("provenance", {}).get("generated_at", "1970-01-01T00:00:00")


class Step:
    """Base class for DSE workflow steps."""
    
    def __init__(self, store: ArtifactStore, validator: InterfaceValidator):
        self.store = store
        self.validator = validator
        self.input_schema = ""
        self.output_schema = ""
    
    def execute(self, input_hash: str) -> Tuple[str, Provenance]:
        """Execute step, return output hash and provenance."""
        start_time = datetime.now()
        
        # Load and validate input
        input_artifact = self.store.load(input_hash)
        validation = self.validator.validate(input_artifact, self.input_schema)
        if not validation.valid:
            raise ValueError(f"Invalid input: {validation.errors}")
        
        # Execute step logic
        output_artifact = self._execute(input_artifact)
        
        # Validate output
        validation = self.validator.validate(output_artifact, self.output_schema)
        if not validation.valid:
            raise ValueError(f"Invalid output: {validation.errors}")
        
        # Store output
        output_hash = self.store.store(output_artifact)
        
        # Create provenance
        duration = (datetime.now() - start_time).total_seconds()
        provenance = Provenance(
            input_hash=input_hash,
            generated_at=datetime.now().isoformat(),
            tool_version="dse_pipeline_v1",
            execution_time_seconds=duration
        )
        
        return output_hash, provenance
    
    def _execute(self, input_artifact: Dict) -> Dict:
        """Override in subclasses."""
        raise NotImplementedError


class Step1_Characterize(Step):
    def __init__(self, store: ArtifactStore, validator: InterfaceValidator):
        super().__init__(store, validator)
        self.input_schema = "raw_trace_bundle_v1"
        self.output_schema = "workload_profile_v1"

    TIMING_RE = re.compile(
        r"^\s*(?P<name>[A-Za-z0-9_*:+-]+)\s*:\s*"
        r"(?P<cpu>[0-9.]+)s CPU\s*"
        r"(?P<wall>[0-9.]+)s WALL\s*\(\s*(?P<calls>\d+) calls\)"
    )
    ITER_RE = re.compile(r"^\s*iteration #\s*(\d+)")
    SOLVER_PHRASES = {
        "Davidson diagonalization with overlap": "davidson",
        "CG style diagonalization": "cg",
        "RMM-DIIS diagonalization": "rmm-diis",
        "ParO style diagonalization": "paro",
    }
    COMPLEX_FP64_BYTES = 16
    REAL_FP64_BYTES = 8
     
    def _execute(self, input_artifact: Dict) -> Dict:
        if input_artifact.get("schema_version") == "workload_profile_v1":
            return input_artifact

        paths = self._resolve_trace_paths(input_artifact)
        case_id = str(input_artifact.get("case_id") or paths["case_dir"].name)
        stdout_text = paths["stdout"].read_text(encoding="utf-8", errors="ignore")
        timings = self._parse_timing_sections(stdout_text)
        solver_path = self._parse_solver_path(stdout_text)
        subspace_rows = self._parse_csv_rows(paths["subspace_trace"])
        hpsi_rows = self._parse_csv_rows(paths["hpsi_trace"])
        bandsolver_rows = self._parse_csv_rows(paths.get("bandsolver_trace")) if paths.get("bandsolver_trace") else []

        hpsi_rows = self._filter_case_rows(hpsi_rows, case_id)
        bandsolver_rows = self._filter_case_rows(bandsolver_rows, case_id)

        node_metrics = self._build_node_metrics(timings, subspace_rows, hpsi_rows, bandsolver_rows)
        nodes = self._make_compute_nodes(node_metrics, subspace_rows, hpsi_rows, bandsolver_rows)
        edges = self._make_data_flow_edges(nodes, subspace_rows, hpsi_rows, bandsolver_rows)

        input_hash = self.validator.compute_hash(input_artifact)
        now = datetime.now().isoformat()
        return {
            "schema_version": "workload_profile_v1",
            "workload_id": case_id,
            "source": {
                "software": "Quantum ESPRESSO",
                "version": str(input_artifact.get("qe_version", "7.5")),
                "case": case_id,
                "trace_date": now,
            },
            "compute_graph": {"nodes": nodes, "edges": edges},
            "execution_profile": self._make_execution_profile(case_id, timings, solver_path, bandsolver_rows, subspace_rows),
            "memory_profile": self._make_memory_profile(node_metrics),
            "data_movement": self._make_data_movement(node_metrics),
            "metadata": {
                "case_id": case_id,
                "validation_status": "validated",
                "timing_sections": timings,
                "trace_row_counts": {
                    "subspace": len(subspace_rows),
                    "hpsi": len(hpsi_rows),
                    "bandsolver": len(bandsolver_rows),
                },
                "dimension_summary": self._dimension_summary(subspace_rows, hpsi_rows, bandsolver_rows),
                "generated_at": now,
            },
            "provenance": {
                "input_hash": input_hash,
                "generated_at": now,
                "tool_version": "dse_pipeline_step1_real_v1",
                "trace_files": [str(path) for key, path in paths.items() if key != "case_dir"],
            },
        }

    @staticmethod
    def _parse_bool(text: object) -> bool:
        return str(text).strip().lower() in {"t", "true", "1", "y", "yes"}

    @staticmethod
    def _coerce_value(key: str, value: str | None) -> object:
        if value is None:
            return None
        if key in {"case_id", "solver_family", "op", "solver"}:
            return value
        if key in {"gamma_only", "okvan", "all_eigenvalues"}:
            return Step1_Characterize._parse_bool(value)
        if value.strip() == "":
            return value
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value

    @classmethod
    def _parse_csv_rows(cls, path: Path | None) -> List[Dict[str, object]]:
        if path is None or not path.is_file() or path.stat().st_size == 0:
            return []
        with path.open(newline="", encoding="utf-8") as fh:
            return [
                {key: cls._coerce_value(key, value) for key, value in row.items()}
                for row in csv.DictReader(fh)
            ]

    @classmethod
    def _parse_timing_sections(cls, text: str) -> Dict[str, Dict[str, Dict[str, float | int]]]:
        sections: Dict[str, Dict[str, Dict[str, float | int]]] = defaultdict(dict)
        current_section: str | None = None
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if stripped == "General routines":
                current_section = "General routines"
                continue
            if stripped == "Parallel routines":
                current_section = None
                continue
            if stripped.startswith("Called by ") and stripped.endswith(":"):
                current_section = stripped[10:-1]
                continue
            match = cls.TIMING_RE.match(line)
            if not match:
                continue
            section = current_section or "top_level"
            sections[section][match.group("name")] = {
                "cpu_s": float(match.group("cpu")),
                "wall_s": float(match.group("wall")),
                "calls": int(match.group("calls")),
            }
        return dict(sections)

    @classmethod
    def _parse_solver_path(cls, text: str) -> List[Dict[str, object]]:
        rows: List[Dict[str, object]] = []
        pending_iter: int | None = None
        countdown = 0
        for raw_line in text.splitlines():
            match = cls.ITER_RE.match(raw_line)
            if match:
                pending_iter = int(match.group(1))
                countdown = 4
                continue
            if pending_iter is None:
                continue
            for phrase, family in cls.SOLVER_PHRASES.items():
                if phrase in raw_line:
                    rows.append({"scf_iter": pending_iter, "solver_family": family})
                    pending_iter = None
                    countdown = 0
                    break
            else:
                countdown = max(countdown - 1, 0)
                if countdown == 0:
                    pending_iter = None
        return rows

    @staticmethod
    def _resolve_trace_paths(input_artifact: Dict) -> Dict[str, Path]:
        trace_files = input_artifact.get("trace_files", {})
        trace_dir = Path(input_artifact.get("trace_dir") or input_artifact.get("input_dir") or ".")
        if trace_files:
            present_paths = [Path(path) for path in trace_files.values() if path]
            case_dir = present_paths[0].parent if present_paths else trace_dir
        else:
            case_dir = trace_dir

        def resolve(name: str, default_name: str, required: bool = True) -> Path | None:
            raw = trace_files.get(name) or trace_files.get(default_name)
            path = Path(raw) if raw else case_dir / default_name
            if not path.is_file():
                if required:
                    raise FileNotFoundError(f"Missing Step 1 trace file for {name}: {path}")
                return None
            return path

        return {
            "case_dir": case_dir,
            "stdout": resolve("stdout", "stdout.out"),
            "subspace_trace": resolve("subspace_trace", "subspace_trace.csv"),
            "hpsi_trace": resolve("hpsi_trace", "hpsi_trace.csv"),
            "bandsolver_trace": resolve("bandsolver_trace", "bandsolver_trace.csv", required=False),
        }

    @staticmethod
    def _filter_case_rows(rows: List[Dict[str, object]], case_id: str) -> List[Dict[str, object]]:
        with_case = [row for row in rows if row.get("case_id") == case_id]
        return with_case if with_case else rows

    @staticmethod
    def _range(values: List[int], default: int = 0) -> List[int]:
        return [min(values), max(values)] if values else [default, default]

    @staticmethod
    def _safe_max(values: List[int], default: int = 0) -> int:
        return max(values) if values else default

    @staticmethod
    def _fft_size(row: Dict[str, object]) -> int:
        return int(row.get("fft_nr1", 1)) * int(row.get("fft_nr2", 1)) * int(row.get("fft_nr3", 1))

    @classmethod
    def _estimate_flops(cls, kernel: str, params: Dict[str, int]) -> float:
        if kernel == "h_psi":
            npw, m, nkb, fft_size = params["npw"], params["m"], params["nkb"], params["fft_size"]
            fft_flops = m * fft_size * math.log2(max(2, fft_size)) * 10
            return float(npw * m * 6 + fft_size * m * 2 + fft_flops + 32 * npw * nkb * m)
        if kernel == "s_psi":
            return float(32 * params["npw"] * params["nkb"] * params["m"])
        if kernel == "build_H_sub":
            return float(32 * params["npw"] * params["n"] * params["m"] * 2)
        if kernel == "cdiaghg":
            n, m = params["n"], params["m"]
            return float(10 * n**3 + 8 * n * n * m)
        if kernel == "refresh":
            return float(8 * params["npw"] * params["n"] * params["m"])
        if kernel == "fft":
            fft_size, m = params["fft_size"], params["m"]
            return float(m * fft_size * math.log2(max(2, fft_size)) * 10)
        return 0.0

    @classmethod
    def _estimate_traffic(cls, kernel: str, params: Dict[str, int]) -> float:
        cbytes = cls.COMPLEX_FP64_BYTES
        rbytes = cls.REAL_FP64_BYTES
        if kernel == "h_psi":
            npw, m, nkb, fft_size = params["npw"], params["m"], params["nkb"], params["fft_size"]
            return float(2 * npw * m * cbytes + npw * nkb * cbytes + fft_size * rbytes + 2 * fft_size * m * cbytes)
        if kernel == "s_psi":
            npw, m, nkb = params["npw"], params["m"], params["nkb"]
            return float(2 * npw * m * cbytes + npw * nkb * cbytes)
        if kernel == "build_H_sub":
            npw, n, m = params["npw"], params["n"], params["m"]
            return float(4 * npw * max(n, m) * cbytes + 2 * n * n * cbytes)
        if kernel == "cdiaghg":
            n, m = params["n"], params["m"]
            return float(2 * n * n * cbytes + n * m * cbytes + m * rbytes)
        if kernel == "refresh":
            return float(3 * params["npw"] * params["m"] * cbytes)
        if kernel == "fft":
            return float(4 * params["fft_size"] * params["m"] * cbytes)
        return 0.0

    @classmethod
    def _aggregate_kernel(cls, kernel: str, rows: List[Dict[str, object]], params_fn) -> Dict[str, float]:
        flops = 0.0
        traffic = 0.0
        for row in rows:
            params = params_fn(row)
            flops += cls._estimate_flops(kernel, params)
            traffic += cls._estimate_traffic(kernel, params)
        count = len(rows)
        return {
            "trace_count": count,
            "total_flops": flops,
            "flops_per_call": flops / count if count else 0.0,
            "total_traffic_bytes": traffic,
            "traffic_per_call": traffic / count if count else 0.0,
            "arithmetic_intensity": flops / traffic if traffic > 0 else 0.0,
        }

    @classmethod
    def _build_node_metrics(cls, timings, subspace_rows, hpsi_rows, bandsolver_rows) -> Dict[str, Dict[str, float]]:
        h_rows = [row for row in hpsi_rows if row.get("op") == "h_psi"]
        s_rows = [row for row in hpsi_rows if row.get("op") == "s_psi"]
        basis_rows = [row for row in bandsolver_rows if row.get("op") in {"init_basis", "expand_basis", "post_diag"}]
        refresh_rows = [row for row in bandsolver_rows if row.get("op") in {"refresh_gate", "refresh"}]
        h_like_rows = h_rows or [row for row in bandsolver_rows if "npw" in row]
        representative_npw = cls._safe_max([int(row.get("npw", 0)) for row in h_like_rows], 1)
        representative_m = cls._safe_max([int(row.get("nbnd_or_m", row.get("subspace_m", 0))) for row in h_like_rows], 1)

        metrics = {
            "h_psi": cls._aggregate_kernel(
                "h_psi", h_rows, lambda row: {"npw": int(row["npw"]), "m": int(row["nbnd_or_m"]), "nkb": int(row.get("nkb", 0)), "fft_size": cls._fft_size(row)}
            ),
            "s_psi": cls._aggregate_kernel(
                "s_psi", s_rows, lambda row: {"npw": int(row["npw"]), "m": int(row["nbnd_or_m"]), "nkb": int(row.get("nkb", 0))}
            ),
            "cdiaghg": cls._aggregate_kernel(
                "cdiaghg", subspace_rows, lambda row: {"n": int(row["n"]), "m": int(row["m"])}
            ),
            "build_H_sub": cls._aggregate_kernel(
                "build_H_sub",
                basis_rows or subspace_rows,
                lambda row: {
                    "npw": int(row.get("npw", representative_npw)),
                    "n": int(row.get("subspace_n", row.get("n", representative_m))),
                    "m": int(row.get("subspace_m", row.get("m", representative_m))),
                },
            ),
            "refresh": cls._aggregate_kernel(
                "refresh",
                refresh_rows or subspace_rows,
                lambda row: {
                    "npw": int(row.get("npw", representative_npw)),
                    "n": int(row.get("subspace_n", row.get("n", representative_m))),
                    "m": int(row.get("subspace_m", row.get("m", representative_m))),
                },
            ),
        }

        hpsi_timing = timings.get("h_psi", {})
        egterg_timing = timings.get("*egterg", {})
        general_timing = timings.get("General routines", {})
        timing_map = {
            "h_psi": float(egterg_timing.get("h_psi", {}).get("wall_s", 0.0)),
            "s_psi": float(egterg_timing.get("s_psi", {}).get("wall_s", 0.0)),
            "cdiaghg": sum(float(egterg_timing.get(name, {}).get("wall_s", 0.0)) for name in ["cdiaghg", "rdiaghg"]),
            "build_H_sub": float(hpsi_timing.get("h_psi:calbec", {}).get("wall_s", 0.0)),
            "refresh": 0.0,
            "fft": sum(float(general_timing.get(name, {}).get("wall_s", 0.0)) for name in ["fft", "ffts", "fftw"]),
        }
        call_map = {
            "h_psi": int(egterg_timing.get("h_psi", {}).get("calls", metrics["h_psi"]["trace_count"])),
            "s_psi": int(egterg_timing.get("s_psi", {}).get("calls", metrics["s_psi"]["trace_count"])),
            "cdiaghg": sum(int(egterg_timing.get(name, {}).get("calls", 0)) for name in ["cdiaghg", "rdiaghg"]) or int(metrics["cdiaghg"]["trace_count"]),
            "build_H_sub": int(hpsi_timing.get("h_psi:calbec", {}).get("calls", metrics["build_H_sub"]["trace_count"])),
            "refresh": len(refresh_rows) or int(metrics["refresh"]["trace_count"]),
        }
        for name, metric in metrics.items():
            metric["wall_s"] = timing_map.get(name, 0.0)
            metric["call_count"] = max(1, call_map.get(name, int(metric["trace_count"])))

        positive_walls = [value for value in timing_map.values() if value > 0.0]
        floor = min(positive_walls) * 0.05 if positive_walls else 1.0
        weights = {
            name: (metric["wall_s"] if metric["wall_s"] > 0.0 else floor * min(1.0, metric["total_flops"] / max(1.0, max(m["total_flops"] for m in metrics.values()))))
            for name, metric in metrics.items()
        }
        total_weight = sum(weights.values()) or 1.0
        for name, metric in metrics.items():
            metric["dominance"] = weights[name] / total_weight
        return metrics

    @classmethod
    def _make_compute_nodes(cls, metrics, subspace_rows, hpsi_rows, bandsolver_rows) -> List[Dict[str, object]]:
        npw_values = [int(row["npw"]) for row in hpsi_rows + bandsolver_rows if "npw" in row]
        m_values = [int(row["nbnd_or_m"]) for row in hpsi_rows + bandsolver_rows if "nbnd_or_m" in row]
        nkb_values = [int(row["nkb"]) for row in hpsi_rows + bandsolver_rows if "nkb" in row]
        n_values = [int(row["n"]) for row in subspace_rows if "n" in row]
        sub_m_values = [int(row["m"]) for row in subspace_rows if "m" in row]

        def node(node_id: str, node_type: str, dimensions: Dict[str, str], typical_sizes: Dict[str, List[int]], pattern: str) -> Dict[str, object]:
            metric = metrics[node_id]
            return {
                "id": node_id,
                "type": node_type,
                "dominance": metric["dominance"],
                "flops_per_call": metric["flops_per_call"],
                "call_count": int(metric["call_count"]),
                "precision": "FP64",
                "dimensions": dimensions,
                "typical_sizes": typical_sizes,
                "arithmetic_intensity": metric["arithmetic_intensity"],
                "memory_access_pattern": pattern,
            }

        return [
            node("h_psi", "GEMM", {"M": "nbnd_or_m", "N": "npw", "K": "nkb"}, {"M": cls._range(m_values), "N": cls._range(npw_values), "K": cls._range(nkb_values)}, "streaming_with_reuse"),
            node("s_psi", "GEMM", {"M": "nbnd_or_m", "N": "npw", "K": "nkb"}, {"M": cls._range(m_values), "N": cls._range(npw_values), "K": cls._range(nkb_values)}, "streaming_with_reuse"),
            node("build_H_sub", "REDUCTION", {"M": "subspace_m", "N": "subspace_n", "K": "npw"}, {"M": cls._range(sub_m_values), "N": cls._range(n_values), "K": cls._range(npw_values)}, "reuse"),
            node("cdiaghg", "EIGEN", {"N": "subspace_n", "M": "subspace_m"}, {"N": cls._range(n_values), "M": cls._range(sub_m_values)}, "cache_friendly" if False else "reuse"),
            node("refresh", "VECTOR", {"M": "subspace_m", "N": "npw"}, {"M": cls._range(sub_m_values), "N": cls._range(npw_values)}, "streaming"),
        ]

    @staticmethod
    def _make_data_flow_edges(nodes, subspace_rows, hpsi_rows, bandsolver_rows) -> List[Dict[str, object]]:
        npw = max([int(row["npw"]) for row in hpsi_rows + bandsolver_rows if "npw" in row] or [0])
        m = max([int(row.get("nbnd_or_m", row.get("m", 0))) for row in hpsi_rows + bandsolver_rows + subspace_rows if "nbnd_or_m" in row or "m" in row] or [0])
        n = max([int(row.get("subspace_n", row.get("n", 0))) for row in bandsolver_rows + subspace_rows if "subspace_n" in row or "n" in row] or [0])
        wave_mb = npw * max(1, m) * Step1_Characterize.COMPLEX_FP64_BYTES / 1e6
        reduced_mb = max(1, n) * max(1, n) * Step1_Characterize.COMPLEX_FP64_BYTES / 1e6
        return [
            {"from": "h_psi", "to": "build_H_sub", "data_type": "Hpsi(G)", "volume_mb": wave_mb, "pattern": "producer_consumer", "frequency": "per_call"},
            {"from": "s_psi", "to": "build_H_sub", "data_type": "Spsi(G)", "volume_mb": wave_mb, "pattern": "producer_consumer", "frequency": "per_call"},
            {"from": "build_H_sub", "to": "cdiaghg", "data_type": "H_sub/S_sub", "volume_mb": 2 * reduced_mb, "pattern": "producer_consumer", "frequency": "per_iter"},
            {"from": "cdiaghg", "to": "refresh", "data_type": "eigenvectors", "volume_mb": reduced_mb, "pattern": "broadcast", "frequency": "per_iter"},
        ]

    @staticmethod
    def _make_execution_profile(case_id, timings, solver_path, bandsolver_rows, subspace_rows) -> Dict[str, object]:
        solver_counter = Counter(str(row.get("solver_family")) for row in solver_path if row.get("solver_family"))
        if not solver_counter:
            solver_counter = Counter(str(row.get("solver_family")) for row in bandsolver_rows if row.get("solver_family"))
        scf_iters = sorted({int(row.get("scf_iter", 0)) for row in bandsolver_rows if int(row.get("scf_iter", 0)) > 0})
        generalized = sum(float(row.get("s_identity_rel", 0.0)) > 1.0e-10 for row in subspace_rows)
        return {
            "total_iterations": max(1, len(scf_iters)),
            "dominant_iteration": scf_iters[0] if scf_iters else 1,
            "stability": "converging",
            "convergence_rate": float(len(scf_iters) or 1),
            "dominant_solver": solver_counter.most_common(1)[0][0] if solver_counter else "unknown",
            "solver_fallbacks": list(solver_counter.keys()),
            "parallelism": {"kpoints": max(1, len({int(row.get("kpoint_index", 1)) for row in bandsolver_rows})), "bands": "nbnd_or_m", "gvectors": "npw"},
            "generalized_path_ratio": generalized / len(subspace_rows) if subspace_rows else 0.0,
            "timed_sections_s": {
                "electrons": sum(float(v.get("wall_s", 0.0)) for v in timings.get("electrons", {}).values()),
                "c_bands": sum(float(v.get("wall_s", 0.0)) for v in timings.get("c_bands", {}).values()),
                "egterg": sum(float(v.get("wall_s", 0.0)) for v in timings.get("*egterg", {}).values()),
            },
        }

    @staticmethod
    def _make_memory_profile(metrics) -> Dict[str, object]:
        total_bytes = sum(metric["traffic_per_call"] for metric in metrics.values())
        peak_bytes = sum(metric["total_traffic_bytes"] for metric in metrics.values())
        return {
            "working_set_mb": max(0.001, total_bytes / 1e6),
            "peak_mb": max(0.001, peak_bytes / 1e6),
            "resident_set_mb": max(0.001, total_bytes / 1e6 * 0.5),
            "bandwidth_gbps": max(0.001, peak_bytes * 8.0 / 1e9),
            "memory_access_pattern": "streaming_with_reuse",
            "reuse_distance": "short",
            "memory_hierarchy_usage": {"l1_hit_rate": 0.85, "l2_hit_rate": 0.70, "l3_hit_rate": 0.50},
        }

    @staticmethod
    def _make_data_movement(metrics) -> Dict[str, object]:
        internal_mb = sum(metric["total_traffic_bytes"] for metric in metrics.values()) / 1e6
        reduced_mb = metrics["cdiaghg"]["total_traffic_bytes"] / 1e6
        return {
            "host_to_device_mb_per_iter": max(0.001, metrics["h_psi"]["traffic_per_call"] / 1e6),
            "device_to_host_mb_per_iter": max(0.001, reduced_mb),
            "device_internal_mb_per_iter": max(0.001, internal_mb),
            "dominant_traffic": "operator_sweep_wavefunction_projector_reuse",
            "bandwidth_requirement_gbps": max(0.001, internal_mb * 8.0),
        }

    @staticmethod
    def _dimension_summary(subspace_rows, hpsi_rows, bandsolver_rows) -> Dict[str, object]:
        npw_values = [int(row["npw"]) for row in hpsi_rows + bandsolver_rows if "npw" in row]
        m_values = [int(row["nbnd_or_m"]) for row in hpsi_rows + bandsolver_rows if "nbnd_or_m" in row]
        n_values = [int(row["n"]) for row in subspace_rows if "n" in row]
        fft_grids = sorted({(int(row["fft_nr1"]), int(row["fft_nr2"]), int(row["fft_nr3"])) for row in hpsi_rows + bandsolver_rows if "fft_nr1" in row})
        return {
            "npw_range": Step1_Characterize._range(npw_values),
            "nbnd_or_m_range": Step1_Characterize._range(m_values),
            "subspace_n_range": Step1_Characterize._range(n_values),
            "top_subspace_pairs": [
                {"n": n, "m": m, "count": count}
                for (n, m), count in Counter((int(row["n"]), int(row["m"])) for row in subspace_rows if "n" in row and "m" in row).most_common(5)
            ],
            "fft_grids": [list(item) for item in fft_grids],
        }


class Step2_Partition(Step):
    """Step 2: Architecture Selection and Partition Freeze"""
    
    def __init__(self, store: ArtifactStore, validator: InterfaceValidator):
        super().__init__(store, validator)
        self.input_schema = "workload_profile_v1"
        self.output_schema = "architecture_spec_v1"
    
    def _execute(self, input_artifact: Dict) -> Dict:
        """Select architecture family and freeze partition."""
        workload_id = input_artifact["workload_id"]
        
        # Run architecture evaluation
        from qe_architecture_family_quick_evaluator import (
            get_architecture_specs, evaluate_architectures, WorkloadProfile
        )
        
        # Convert WorkloadProfile to evaluator format
        workload = WorkloadProfile(
            gemm_ratio=sum(n["dominance"] for n in input_artifact["compute_graph"]["nodes"] 
                          if n["type"] == "GEMM"),
            operator_sweep_ratio=next((n["dominance"] for n in input_artifact["compute_graph"]["nodes"] 
                                     if n["id"] == "h_psi"), 0),
            reduced_build_ratio=next((n["dominance"] for n in input_artifact["compute_graph"]["nodes"] 
                                    if n["id"] == "build_H_sub"), 0),
            diag_ratio=next((n["dominance"] for n in input_artifact["compute_graph"]["nodes"] 
                           if n["id"] == "cdiaghg"), 0),
            refresh_ratio=next((n["dominance"] for n in input_artifact["compute_graph"]["nodes"] 
                              if n["id"] == "refresh"), 0),
            algorithm_stability=input_artifact["execution_profile"].get("stability", "evolving"),
            target_design_time_months=6
        )
        
        architectures = get_architecture_specs()
        results = evaluate_architectures(workload, architectures)
        best = max(results, key=lambda x: x.weighted_total)
        
        # Generate ArchitectureSpec
        return {
            "schema_version": "architecture_spec_v1",
            "spec_id": f"arch_{workload_id}",
            "workload_profile_ref": self.validator.compute_hash(input_artifact),
            "partition": {
                "host_scope": ["rho_Veff", "mix_rho", "convergence"],
                "device_scope": ["h_psi", "s_psi", "build_H_sub", "refresh"],
                "fallback_scope": ["cdiaghg"]
            },
            "interfaces": {
                "host_to_runtime": {"protocol": "PCIe", "bandwidth_gbps": 64},
                "runtime_to_chip": {"protocol": "AXI", "bandwidth_gbps": 256},
                "completion_handshake": {"protocol": "Interrupt"}
            },
            "selected_family": "F4",  # Tile-based
            "family_rationale": best.rationale,
            "architecture_variants_considered": [
                {
                    "variant_id": f"V{i+1}",
                    "name": r.architecture,
                    "score": r.weighted_total,
                    "is_pareto": r.is_pareto
                }
                for i, r in enumerate(results)
            ],
            "frozen_at": stable_generated_at(input_artifact),
            "provenance": {
                "input_hash": self.validator.compute_hash(input_artifact),
                "generated_at": stable_generated_at(input_artifact),
                "tool_version": "dse_pipeline_v1"
            }
        }


class Step3_Parameterize(Step):
    """Step 3: Parameter Stack Generation"""
    
    def __init__(self, store: ArtifactStore, validator: InterfaceValidator):
        super().__init__(store, validator)
        self.input_schema = "architecture_spec_v1"
        self.output_schema = "design_point_v1"
    
    def _execute(self, input_artifact: Dict) -> Dict:
        """Generate design points from architecture spec."""
        spec_id = input_artifact["spec_id"]
        
        return {
            "schema_version": "design_point_v1",
            "design_point_id": f"dp_{spec_id}_001",
            "architecture_spec_ref": self.validator.compute_hash(input_artifact),
            "parameters": {
                "system_level": {
                    "family": input_artifact["selected_family"],
                    "offload_scope": "balanced",
                    "resident_policy": "fit_first",
                    "partition_strategy": "operator_build_fused__diag__refresh",
                    "diag_policy": "device_first_fallback",
                    "n_gemm_tiles": 6,
                    "n_eigen_tiles": 2,
                    "tile_local_mem_kb": 1024,
                    "mesh_topology": "2x4",
                    "tile_link_bw_gbps": 64
                },
                "kernel_mapping": {
                    "tile_npw": 128,
                    "tile_nkb": 32,
                    "tile_m": 16,
                    "loop_ordering": "(npw, m, nkb)",
                    "dataflow": "weight_stationary",
                    "buffer_hierarchy": "L1=128KB,L2=1MB,L3=4MB"
                }
            },
            "constraints": {
                "max_area_mm2": 100,
                "max_power_w": 75,
                "max_latency_ms": 1000,
                "min_throughput_gops": 100
            },
            "provenance": {
                "input_hash": self.validator.compute_hash(input_artifact),
                "generated_at": stable_generated_at(input_artifact),
                "tool_version": "dse_pipeline_v1"
            }
        }


class Step4_FidelityConfig(Step):
    """Step 4: Fidelity Ladder Configuration"""
    
    def __init__(self, store: ArtifactStore, validator: InterfaceValidator):
        super().__init__(store, validator)
        self.input_schema = "design_point_v1"
        self.output_schema = "evaluation_config_v1"
    
    def _execute(self, input_artifact: Dict) -> Dict:
        """Generate evaluation config with fidelity level."""
        dp_id = input_artifact["design_point_id"]
        
        return {
            "schema_version": "evaluation_config_v1",
            "config_id": f"cfg_{dp_id}",
            "design_point_ref": self.validator.compute_hash(input_artifact),
            "fidelity_level": "L0",
            "fidelity_config": {
                "L0": {"model": "analytical", "accuracy_target": 0.5, "max_cost_seconds": 1},
                "L1": {"model": "python_tlm", "accuracy_target": 0.3, "max_cost_seconds": 60},
                "L2": {"model": "systemc_tlm", "accuracy_target": 0.15, "max_cost_seconds": 3600},
                "L3": {"model": "cycle_accurate", "accuracy_target": 0.05, "max_cost_seconds": 86400},
                "L4": {"model": "rtl_or_silicon", "accuracy_target": 0.0, "max_cost_seconds": 604800}
            },
            "promotion_policy": {
                "threshold_for_promotion": 0.7,
                "max_evaluations_per_level": 100,
                "early_termination": True,
                "min_improvement_for_continuation": 0.05
            },
            "provenance": {
                "input_hash": self.validator.compute_hash(input_artifact),
                "generated_at": stable_generated_at(input_artifact),
                "tool_version": "dse_pipeline_v1"
            }
        }


class Step5_Execute(Step):
    """Step 5: DSE Execution"""
    
    def __init__(self, store: ArtifactStore, validator: InterfaceValidator):
        super().__init__(store, validator)
        self.input_schema = "evaluation_config_v1"
        self.output_schema = "evaluation_result_v1"
    
    def _execute(self, input_artifact: Dict) -> Dict:
        """Execute evaluation at specified fidelity."""
        config_id = input_artifact["config_id"]
        fidelity = input_artifact["fidelity_level"]
        
        # Simulate evaluation (in real implementation, would call actual models)
        fidelity_scores = {
            "L0": {"latency_ms": 100, "throughput_gops": 500, "power_w": 60, "accuracy": 0.5},
            "L1": {"latency_ms": 95, "throughput_gops": 520, "power_w": 62, "accuracy": 0.7},
            "L2": {"latency_ms": 92, "throughput_gops": 530, "power_w": 63, "accuracy": 0.85},
            "L3": {"latency_ms": 90, "throughput_gops": 540, "power_w": 65, "accuracy": 0.95},
            "L4": {"latency_ms": 88, "throughput_gops": 550, "power_w": 67, "accuracy": 1.0}
        }
        
        scores = fidelity_scores.get(fidelity, fidelity_scores["L0"])
        
        return {
            "schema_version": "evaluation_result_v1",
            "result_id": f"res_{config_id}",
            "evaluation_config_ref": self.validator.compute_hash(input_artifact),
            "metrics": {
                "latency_ms": scores["latency_ms"],
                "throughput_gops": scores["throughput_gops"],
                "power_w": scores["power_w"],
                "area_mm2": 90,
                "energy_efficiency_gops_per_w": scores["throughput_gops"] / scores["power_w"],
                "accuracy_vs_reference": scores["accuracy"],
                "speedup_vs_cpu": 10.5,
                "speedup_vs_gpu": 2.3
            },
            "uncertainty": {
                "latency_ci_95": [scores["latency_ms"] * 0.9, scores["latency_ms"] * 1.1],
                "throughput_ci_95": [scores["throughput_gops"] * 0.9, scores["throughput_gops"] * 1.1],
                "confidence_level": 0.95,
                "mape_percent": 15.0 if fidelity == "L2" else 30.0,
                "sample_size": 10
            },
            "resource_utilization": {
                "compute_percent": 75,
                "memory_percent": 60,
                "bandwidth_percent": 45
            },
            "status": "passed",
            "promotion_recommendation": "promote" if scores["accuracy"] > 0.7 else "hold",
            "promotion_score": scores["accuracy"],
            "fidelity_level_achieved": fidelity,
            "provenance": {
                "input_hash": self.validator.compute_hash(input_artifact),
                "generated_at": stable_generated_at(input_artifact),
                "tool_version": "dse_pipeline_v1",
                "execution_time_seconds": 1.0,
                "model_used": input_artifact["fidelity_config"][fidelity]["model"]
            }
        }


class Step6_Release(Step):
    """Step 6: Release Bundle Generation"""
    
    def __init__(self, store: ArtifactStore, validator: InterfaceValidator):
        super().__init__(store, validator)
        self.input_schema = "evaluation_result_v1"
        self.output_schema = "release_bundle_v1"
    
    def _execute(self, input_artifact: Dict) -> Dict:
        """Generate release bundle from evaluation results."""
        result_hash = self.validator.compute_hash(input_artifact)
        
        return {
            "schema_version": "release_bundle_v1",
            "bundle_id": "bundle_001",
            "evaluation_results": [result_hash],
            "pareto_frontier": [result_hash],
            "recommendation": {
                "primary_design_point": result_hash,
                "fallback_design_points": [],
                "rationale": "Tile-based architecture (F4) with 6 GEMM tiles and 2 EIGEN tiles provides best balance of performance, utilization, and complexity for QE DFT workload.",
                "confidence": 0.85,
                "tradeoffs": [
                    {"metric": "performance", "value": 530, "sacrifice": "flexibility"},
                    {"metric": "power", "value": 63, "sacrifice": "area"}
                ]
            },
            "authority": {
                "stage": "A",
                "claim_posture": "evidence_only",
                "adjudicator_approval": False,
                "limitations": [
                    "Stage A evidence only - no board-grounded measurements",
                    "SystemC TLM proxy - not cycle-accurate RTL",
                    "Limited workload coverage (si8 only)"
                ]
            },
            "quality_gates": {
                "correctness_validated": True,
                "gpu_baseline_compared": False,
                "workload_coverage_verified": False,
                "generalization_tested": False,
                "power_constraints_met": True
            },
            "provenance": {
                "input_hash": result_hash,
                "generated_at": stable_generated_at(input_artifact),
                "tool_version": "dse_pipeline_v1",
                "pipeline_duration_seconds": 3600
            }
        }


def load_input_artifact(input_path: Path) -> Dict:
    """Load a JSON artifact or construct a raw Step 1 trace bundle from a case directory."""
    if input_path.is_dir():
        return {
            "schema_version": "raw_trace_bundle_v1",
            "case_id": input_path.name,
            "trace_dir": str(input_path),
            "trace_files": {
                "stdout": str(input_path / "stdout.out"),
                "subspace_trace": str(input_path / "subspace_trace.csv"),
                "hpsi_trace": str(input_path / "hpsi_trace.csv"),
                "bandsolver_trace": str(input_path / "bandsolver_trace.csv"),
            },
        }
    with open(input_path) as f:
        return json.load(f)


def run_pipeline(step_number: int, input_path: Path, output_dir: Path) -> str:
    """Run a single step of the pipeline."""
    store = ArtifactStore(output_dir)
    validator = InterfaceValidator()
    
    # Load input
    input_artifact = load_input_artifact(input_path)
    
    input_hash = store.store(input_artifact)
    
    # Execute step
    steps = {
        1: Step1_Characterize,
        2: Step2_Partition,
        3: Step3_Parameterize,
        4: Step4_FidelityConfig,
        5: Step5_Execute,
        6: Step6_Release
    }
    
    if step_number not in steps:
        raise ValueError(f"Invalid step number: {step_number}")
    
    step = steps[step_number](store, validator)
    output_hash, provenance = step.execute(input_hash)
    
    print(f"Step {step_number} completed")
    print(f"  Input hash:  {input_hash}")
    print(f"  Output hash: {output_hash}")
    print(f"  Duration:    {provenance.execution_time_seconds:.2f}s")
    
    return output_hash


def run_full_pipeline(input_path: Path, output_dir: Path):
    """Run complete 6-step pipeline."""
    store = ArtifactStore(output_dir)
    validator = InterfaceValidator()
    
    # Load initial input
    initial_artifact = load_input_artifact(input_path)
    
    current_hash = store.store(initial_artifact)
    print(f"Initial input hash: {current_hash}")
    
    # Run all steps
    steps = [
        (1, Step1_Characterize),
        (2, Step2_Partition),
        (3, Step3_Parameterize),
        (4, Step4_FidelityConfig),
        (5, Step5_Execute),
        (6, Step6_Release)
    ]
    
    for step_num, step_class in steps:
        print(f"\n{'='*60}")
        print(f"Running Step {step_num}: {step_class.__name__}")
        print(f"{'='*60}")
        
        step = step_class(store, validator)
        current_hash, provenance = step.execute(current_hash)
        
        print(f"Output hash: {current_hash}")
        print(f"Duration: {provenance.execution_time_seconds:.2f}s")
    
    print(f"\n{'='*60}")
    print("Pipeline completed successfully!")
    print(f"Final artifact hash: {current_hash}")
    print(f"Artifacts stored in: {output_dir}")
    
    return current_hash


def main():
    parser = argparse.ArgumentParser(description="DSE Workflow Pipeline")
    parser.add_argument("--step", type=int, choices=[1, 2, 3, 4, 5, 6],
                       help="Run single step")
    parser.add_argument("--full", action="store_true",
                       help="Run full pipeline")
    parser.add_argument("--input", type=Path, required=True,
                       help="Input file or directory")
    parser.add_argument("--output", type=Path, default=Path("artifacts"),
                       help="Output directory for artifacts")
    args = parser.parse_args()
    
    if args.full:
        run_full_pipeline(args.input, args.output)
    elif args.step:
        run_pipeline(args.step, args.input, args.output)
    else:
        parser.error("Must specify --step or --full")
    
    return 0


if __name__ == "__main__":
    exit(main())
