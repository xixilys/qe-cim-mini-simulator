#!/usr/bin/env python3
"""Generated EDA stub evidence for QE-IC real opportunity campaigns."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


EDA_STUB_EVIDENCE_SCHEMA_VERSION = "dse.qe_ic.eda_stub_evidence.v1"
CLAIM_BOUNDARY = (
    "Generated HLS/RTL/SystemC stubs and EDA syntax/resource attempts are "
    "non-claimable implementation-readiness evidence. They do not prove "
    "workflow speedup or hardware acceleration."
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_name(value: Any, *, prefix: str = "stub") -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "")).strip("_").lower()
    if not text or text[0].isdigit():
        text = f"{prefix}_{text}" if text else prefix
    return text[:80]


def _module_name(candidate: Mapping[str, Any]) -> str:
    candidate_id = str(candidate.get("candidate_id") or "candidate")
    digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:10]
    return f"qe_ic_{_safe_name(candidate_id, prefix='candidate')}_{digest}"


def _candidate_role(candidate: Mapping[str, Any]) -> str:
    params = _as_mapping(candidate.get("candidate_parameters"))
    return str(candidate.get("target_candidate_kind") or candidate.get("template_id") or params.get("template_family") or "generated_stub")


def _rtl_stub(candidate: Mapping[str, Any]) -> str:
    module = _module_name(candidate)
    role_hash = int(hashlib.sha256(_candidate_role(candidate).encode("utf-8")).hexdigest()[:8], 16)
    return f"""// Generated non-claimable RTL stub for {candidate.get("candidate_id")}
module {module} (
    input wire clk,
    input wire rst_n,
    input wire valid_in,
    input wire [63:0] in_word,
    output reg valid_out,
    output reg [63:0] out_word
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_out <= 1'b0;
            out_word <= 64'd0;
        end else begin
            valid_out <= valid_in;
            out_word <= in_word ^ 64'h{role_hash:08x}{role_hash:08x};
        end
    end
endmodule
"""


def _hls_stub(candidate: Mapping[str, Any]) -> str:
    function = _safe_name(candidate.get("candidate_id"), prefix="candidate")
    return f"""// Generated non-claimable HLS stub for {candidate.get("candidate_id")}
#include <stdint.h>

extern "C" void {function}_hls_stub(const double *in, double *out, int n) {{
#pragma HLS INTERFACE m_axi port=in offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=out offset=slave bundle=gmem1
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    for (int i = 0; i < n; ++i) {{
#pragma HLS PIPELINE II=1
        out[i] = in[i];
    }}
}}
"""


def _systemc_stub(candidate: Mapping[str, Any]) -> str:
    module = _safe_name(candidate.get("candidate_id"), prefix="candidate")
    return f"""// Generated non-claimable SystemC-style stub for {candidate.get("candidate_id")}
#include <systemc>

SC_MODULE({module}_systemc_stub) {{
    sc_core::sc_in<bool> clk;
    sc_core::sc_in<bool> rst_n;
    sc_core::sc_in<bool> valid_in;
    sc_core::sc_in<sc_dt::sc_uint<64>> in_word;
    sc_core::sc_out<bool> valid_out;
    sc_core::sc_out<sc_dt::sc_uint<64>> out_word;

    void tick() {{
        if (!rst_n.read()) {{
            valid_out.write(false);
            out_word.write(0);
        }} else {{
            valid_out.write(valid_in.read());
            out_word.write(in_word.read());
        }}
    }}

    SC_CTOR({module}_systemc_stub) {{
        SC_METHOD(tick);
        sensitive << clk.pos();
    }}
}};
"""


def _combined_rtl(modules: list[str], module_names: list[str]) -> str:
    wires: list[str] = []
    instances: list[str] = []
    previous = "top_in_word"
    for index, module in enumerate(module_names):
        out_wire = f"stage_{index}_word"
        valid_wire = f"stage_{index}_valid"
        wires.append(f"    wire [63:0] {out_wire};")
        wires.append(f"    wire {valid_wire};")
        instances.append(
            f"    {module} u_{index} (.clk(clk), .rst_n(rst_n), .valid_in(top_valid_in), "
            f".in_word({previous}), .valid_out({valid_wire}), .out_word({out_wire}));"
        )
        previous = out_wire
    return "\n".join(
        [
            *modules,
            "module qe_ic_generated_stub_top (",
            "    input wire clk,",
            "    input wire rst_n,",
            "    input wire top_valid_in,",
            "    input wire [63:0] top_in_word,",
            "    output wire [63:0] top_out_word",
            ");",
            *wires,
            *instances,
            f"    assign top_out_word = {previous};" if module_names else "    assign top_out_word = top_in_word;",
            "endmodule",
            "",
        ]
    )


def _tool_paths(environment: Mapping[str, Any]) -> Mapping[str, str]:
    eda = _as_mapping(_as_mapping(environment.get("tools")).get("eda"))
    return {
        str(tool): str(path)
        for tool, path in _as_mapping(eda.get("available_tools")).items()
        if isinstance(path, str) and path
    }


def _select_tool(environment: Mapping[str, Any]) -> tuple[str | None, str | None]:
    paths = _tool_paths(environment)
    for tool in ("vcs", "vivado", "dc_shell"):
        if tool in paths:
            return tool, paths[tool]
    return None, None


def _write_log(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8", errors="replace")
    return _sha256_file(path)


def _run_vcs_syntax(
    *,
    tool_path: str,
    combined_source: Path,
    run_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    start_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    stdout_path = run_dir / "vcs.stdout.log"
    stderr_path = run_dir / "vcs.stderr.log"
    parsed = urlparse(tool_path)
    command_text: str
    try:
        if parsed.scheme == "ssh":
            alias = parsed.netloc
            remote_tool = parsed.path
            remote_dir = f"/tmp/dse_qe_ic_eda_stub_{hashlib.sha256(str(combined_source).encode()).hexdigest()[:12]}"
            remote_source = f"{remote_dir}/{combined_source.name}"
            setup_command = (
                f"export LC_ALL=C LANG=C; rm -rf {shlex.quote(remote_dir)}; "
                f"mkdir -p {shlex.quote(remote_dir)}; cat > {shlex.quote(remote_source)}"
            )
            setup = subprocess.run(
                ["ssh", alias, setup_command],
                input=combined_source.read_text(encoding="utf-8"),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            if setup.returncode != 0:
                end_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                stdout_hash = _write_log(stdout_path, setup.stdout or "")
                stderr_hash = _write_log(stderr_path, setup.stderr or "")
                return {
                    "tool": "vcs",
                    "tool_path": tool_path,
                    "status": "failed",
                    "syntax_check_passed": False,
                    "returncode": setup.returncode,
                    "reason": "failed to stage generated RTL on remote EDA host",
                    "command": ["ssh", alias, setup_command],
                    "start_timestamp": start_timestamp,
                    "end_timestamp": end_timestamp,
                    "stdout_log_path": str(stdout_path),
                    "stderr_log_path": str(stderr_path),
                    "stdout_hash": stdout_hash,
                    "stderr_hash": stderr_hash,
                }
            remote_command = (
                f"export LC_ALL=C LANG=C; cd {shlex.quote(remote_dir)} && "
                f"{shlex.quote(remote_tool)} -full64 -sverilog {shlex.quote(remote_source)} -o simv"
            )
            command = ["ssh", alias, remote_command]
            command_text = " ".join(command)
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        else:
            command = [tool_path, "-full64", "-sverilog", str(combined_source), "-o", "simv"]
            command_text = " ".join(command)
            result = subprocess.run(
                command,
                cwd=run_dir,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        end_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        stdout_hash = _write_log(stdout_path, "")
        stderr_hash = _write_log(stderr_path, str(exc))
        return {
            "tool": "vcs",
            "tool_path": tool_path,
            "status": "failed",
            "syntax_check_passed": False,
            "returncode": None,
            "reason": str(exc),
            "command": command_text if "command_text" in locals() else None,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "stdout_log_path": str(stdout_path),
            "stderr_log_path": str(stderr_path),
            "stdout_hash": stdout_hash,
            "stderr_hash": stderr_hash,
        }
    end_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    stdout_hash = _write_log(stdout_path, result.stdout or "")
    stderr_hash = _write_log(stderr_path, result.stderr or "")
    return {
        "tool": "vcs",
        "tool_path": tool_path,
        "status": "executed",
        "syntax_check_passed": result.returncode == 0,
        "returncode": result.returncode,
        "reason": None if result.returncode == 0 else "VCS syntax compile returned nonzero",
        "command": command_text,
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "stdout_log_path": str(stdout_path),
        "stderr_log_path": str(stderr_path),
        "stdout_hash": stdout_hash,
        "stderr_hash": stderr_hash,
    }


def _unsupported_tool_attempt(tool: str | None, tool_path: str | None, environment: Mapping[str, Any]) -> dict[str, Any]:
    if tool is None or tool_path is None:
        return {
            "tool": None,
            "tool_path": None,
            "status": "blocked",
            "syntax_check_passed": False,
            "reason": "no VCS/Vivado/DC EDA tool is available locally or through ic-eda",
            "available_tools": dict(_tool_paths(environment)),
        }
    return {
        "tool": tool,
        "tool_path": tool_path,
        "status": "blocked",
        "syntax_check_passed": False,
        "reason": f"generated stub runner currently supports VCS syntax execution; selected {tool}",
        "available_tools": dict(_tool_paths(environment)),
    }


def build_generated_eda_stub_evidence(
    *,
    selected_candidates: Sequence[Mapping[str, Any]],
    environment: Mapping[str, Any],
    out_dir: Path,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Generate HLS/RTL/SystemC stubs and run the lightest available EDA syntax check."""

    stub_root = out_dir / "generated_candidate_stubs"
    stub_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    rtl_sources: list[str] = []
    module_names: list[str] = []
    for candidate in selected_candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = str(candidate.get("candidate_id") or f"candidate_{len(rows)}")
        candidate_dir = stub_root / _safe_name(candidate_id, prefix="candidate")
        candidate_dir.mkdir(parents=True, exist_ok=True)
        module = _module_name(candidate)
        rtl_path = candidate_dir / f"{module}.sv"
        hls_path = candidate_dir / f"{module}_hls.cpp"
        systemc_path = candidate_dir / f"{module}_systemc.cpp"
        rtl_text = _rtl_stub(candidate)
        rtl_path.write_text(rtl_text, encoding="utf-8")
        hls_path.write_text(_hls_stub(candidate), encoding="utf-8")
        systemc_path.write_text(_systemc_stub(candidate), encoding="utf-8")
        rtl_sources.append(rtl_text)
        module_names.append(module)
        rows.append(
            {
                "candidate_id": candidate_id,
                "workload_family_id": candidate.get("workload_family_id"),
                "motif_id": candidate.get("motif_id"),
                "target_type": candidate.get("target_type"),
                "target_candidate_kind": candidate.get("target_candidate_kind"),
                "template_id": candidate.get("template_id"),
                "implementation_maturity": "generated_stub",
                "claim_strength": "none",
                "evidence_kind": "eda_stub_syntax",
                "resource_timing_scope": "syntax_only",
                "resource_metrics_available": False,
                "timing_metrics_available": False,
                "rtl_stub_path": str(rtl_path),
                "hls_stub_path": str(hls_path),
                "systemc_stub_path": str(systemc_path),
                "top_module": module,
                "stub_source_hash": _sha256_text(rtl_text),
            }
        )

    combined_path = stub_root / "qe_ic_generated_stub_bundle.sv"
    combined_path.write_text(_combined_rtl(rtl_sources, module_names), encoding="utf-8")
    run_dir = out_dir / "runs" / "candidate_evidence" / "generated_eda_stub_resource_timing"
    run_dir.mkdir(parents=True, exist_ok=True)
    tool, tool_path = _select_tool(environment)
    if tool == "vcs" and tool_path:
        tool_attempt = _run_vcs_syntax(
            tool_path=tool_path,
            combined_source=combined_path,
            run_dir=run_dir,
            timeout_seconds=timeout_seconds,
        )
    else:
        tool_attempt = _unsupported_tool_attempt(tool, tool_path, environment)
    for row in rows:
        row["tool"] = tool_attempt.get("tool")
        row["tool_status"] = tool_attempt.get("status")
        row["syntax_check_passed"] = tool_attempt.get("syntax_check_passed") is True
        row["tool_attempt_hash"] = _sha256_text(json.dumps(tool_attempt, sort_keys=True, default=str))

    artifact = {
        "schema_version": EDA_STUB_EVIDENCE_SCHEMA_VERSION,
        "results_are_real": False,
        "tool_execution_is_real": tool_attempt.get("status") == "executed",
        "claim_strength": "none",
        "evidence_status": "generated_stub_eda_attempted",
        "evidence_kind": "eda_stub_syntax",
        "resource_timing_scope": "syntax_only",
        "resource_metrics_available": False,
        "timing_metrics_available": False,
        "claim_boundary": CLAIM_BOUNDARY,
        "selected_candidate_count": len(rows),
        "combined_rtl_stub_path": str(combined_path),
        "combined_rtl_stub_hash": _sha256_file(combined_path),
        "tool_attempts": [tool_attempt],
        "candidate_stub_results": rows,
    }
    return {
        "evidence_status": "generated_stub_eda_attempted",
        "results_are_real": False,
        "tool_execution_is_real": artifact["tool_execution_is_real"],
        "artifact": artifact,
        "blocker_reasons": [] if rows else ["blocked_by_missing_candidate_design"],
        "attempt": {
            "attempt": "generated_eda_stub_resource_timing",
            "status": str(tool_attempt.get("status")),
            "reason": tool_attempt.get("reason"),
            "tool": tool_attempt.get("tool"),
            "tool_path": tool_attempt.get("tool_path"),
            "syntax_check_passed": tool_attempt.get("syntax_check_passed") is True,
            "selected_candidate_count": len(rows),
            "combined_rtl_stub_path": str(combined_path),
            "tool_execution_is_real": artifact["tool_execution_is_real"],
        },
    }
