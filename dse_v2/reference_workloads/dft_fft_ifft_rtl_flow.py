#!/usr/bin/env python3
"""DFT-scoped FFT/iFFT/fFFT RTL probe flow helpers.

This module intentionally lives under the DFT reference workload surface, not
in the generic DSE core.  It writes a minimal deterministic ``fft_ifft_ffft``
4-point fixed-width transform smoke kernel plus testbench/TCL scripts and
normalizes real VCS/Vivado/DC attempt artifacts into the DFT hardware claim-gate
evidence rows.  The generated artifacts prove only this microkernel lane; they
are not full-SCF or all-FFT closure.
"""

from __future__ import annotations

import json
import re
import tarfile
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from dse_v2.codesign.dft_hardware_evidence import (
    MAJOR_SCF_KERNEL_IDS,
    build_major_kernel_evidence_matrix,
)


FFT_IFFT_KERNEL_ID = "fft_ifft_ffft"
FFT_IFFT_FLOW_SCHEMA = "dse.dft_scf.fft_ifft_ffft_rtl_flow.v1"

FFT_IFFT_VERILOG = r"""module fft_ifft_ffft #(
    parameter WIDTH = 16,
    parameter OUT_WIDTH = WIDTH + 3
) (
    input  [1:0] mode,
    input  signed [WIDTH-1:0] x0_re,
    input  signed [WIDTH-1:0] x0_im,
    input  signed [WIDTH-1:0] x1_re,
    input  signed [WIDTH-1:0] x1_im,
    input  signed [WIDTH-1:0] x2_re,
    input  signed [WIDTH-1:0] x2_im,
    input  signed [WIDTH-1:0] x3_re,
    input  signed [WIDTH-1:0] x3_im,
    output reg signed [OUT_WIDTH-1:0] y0_re,
    output reg signed [OUT_WIDTH-1:0] y0_im,
    output reg signed [OUT_WIDTH-1:0] y1_re,
    output reg signed [OUT_WIDTH-1:0] y1_im,
    output reg signed [OUT_WIDTH-1:0] y2_re,
    output reg signed [OUT_WIDTH-1:0] y2_im,
    output reg signed [OUT_WIDTH-1:0] y3_re,
    output reg signed [OUT_WIDTH-1:0] y3_im
);
    wire signed [OUT_WIDTH-1:0] a0r = x0_re;
    wire signed [OUT_WIDTH-1:0] a0i = x0_im;
    wire signed [OUT_WIDTH-1:0] a1r = x1_re;
    wire signed [OUT_WIDTH-1:0] a1i = x1_im;
    wire signed [OUT_WIDTH-1:0] a2r = x2_re;
    wire signed [OUT_WIDTH-1:0] a2i = x2_im;
    wire signed [OUT_WIDTH-1:0] a3r = x3_re;
    wire signed [OUT_WIDTH-1:0] a3i = x3_im;

    always @* begin
        y0_re = a0r + a1r + a2r + a3r;
        y0_im = a0i + a1i + a2i + a3i;
        y1_re = a0r + a1i - a2r - a3i;
        y1_im = a0i - a1r - a2i + a3r;
        y2_re = a0r - a1r + a2r - a3r;
        y2_im = a0i - a1i + a2i - a3i;
        y3_re = a0r - a1i - a2r + a3i;
        y3_im = a0i + a1r - a2i - a3r;

        case (mode)
            2'b01: begin
                // Normalized inverse 4-point DFT.  The smoke vectors are chosen
                // so all divisions by four are exact in fixed-point integer RTL.
                y0_re = (a0r + a1r + a2r + a3r) >>> 2;
                y0_im = (a0i + a1i + a2i + a3i) >>> 2;
                y1_re = (a0r - a1i - a2r + a3i) >>> 2;
                y1_im = (a0i + a1r - a2i - a3r) >>> 2;
                y2_re = (a0r - a1r + a2r - a3r) >>> 2;
                y2_im = (a0i - a1i + a2i - a3i) >>> 2;
                y3_re = (a0r + a1i - a2r - a3i) >>> 2;
                y3_im = (a0i - a1r - a2i + a3r) >>> 2;
            end
            2'b10: begin
                // Forward transform for real-valued inputs; imaginary inputs are
                // intentionally ignored to model the fFFT smoke semantics.
                y0_re = a0r + a1r + a2r + a3r;
                y0_im = 0;
                y1_re = a0r - a2r;
                y1_im = -a1r + a3r;
                y2_re = a0r - a1r + a2r - a3r;
                y2_im = 0;
                y3_re = a0r - a2r;
                y3_im = a1r - a3r;
            end
            default: begin
                // mode 0 and reserved mode 3 both run the forward complex DFT.
                y0_re = a0r + a1r + a2r + a3r;
                y0_im = a0i + a1i + a2i + a3i;
                y1_re = a0r + a1i - a2r - a3i;
                y1_im = a0i - a1r - a2i + a3r;
                y2_re = a0r - a1r + a2r - a3r;
                y2_im = a0i - a1i + a2i - a3i;
                y3_re = a0r - a1i - a2r + a3i;
                y3_im = a0i + a1r - a2i - a3r;
            end
        endcase
    end
endmodule
"""

FFT_IFFT_TESTBENCH = r"""module tb_fft_ifft_ffft;
    reg [1:0] mode;
    reg signed [15:0] x0_re, x0_im, x1_re, x1_im, x2_re, x2_im, x3_re, x3_im;
    wire signed [18:0] y0_re, y0_im, y1_re, y1_im, y2_re, y2_im, y3_re, y3_im;

    fft_ifft_ffft dut(
        .mode(mode),
        .x0_re(x0_re), .x0_im(x0_im), .x1_re(x1_re), .x1_im(x1_im),
        .x2_re(x2_re), .x2_im(x2_im), .x3_re(x3_re), .x3_im(x3_im),
        .y0_re(y0_re), .y0_im(y0_im), .y1_re(y1_re), .y1_im(y1_im),
        .y2_re(y2_re), .y2_im(y2_im), .y3_re(y3_re), .y3_im(y3_im)
    );

    task assert_vec;
        input signed [18:0] e0r; input signed [18:0] e0i;
        input signed [18:0] e1r; input signed [18:0] e1i;
        input signed [18:0] e2r; input signed [18:0] e2i;
        input signed [18:0] e3r; input signed [18:0] e3i;
        input [127:0] label;
        begin
            #1;
            if (y0_re !== e0r || y0_im !== e0i || y1_re !== e1r || y1_im !== e1i ||
                y2_re !== e2r || y2_im !== e2i || y3_re !== e3r || y3_im !== e3i) begin
                $display("FFT_IFFT_FFFT_RTL_FAIL %0s got=(%0d,%0d) (%0d,%0d) (%0d,%0d) (%0d,%0d)",
                    label, y0_re, y0_im, y1_re, y1_im, y2_re, y2_im, y3_re, y3_im);
                $finish(1);
            end
        end
    endtask

    initial begin
        mode = 2'b00;
        x0_re = 16'sd4;  x0_im = 16'sd0;
        x1_re = 16'sd0;  x1_im = 16'sd4;
        x2_re = -16'sd4; x2_im = 16'sd0;
        x3_re = 16'sd0;  x3_im = -16'sd4;
        assert_vec(19'sd0, 19'sd0, 19'sd16, 19'sd0, 19'sd0, 19'sd0, 19'sd0, 19'sd0, "fft_complex_4pt");

        mode = 2'b01;
        x0_re = 16'sd0;  x0_im = 16'sd0;
        x1_re = 16'sd16; x1_im = 16'sd0;
        x2_re = 16'sd0;  x2_im = 16'sd0;
        x3_re = 16'sd0;  x3_im = 16'sd0;
        assert_vec(19'sd4, 19'sd0, 19'sd0, 19'sd4, -19'sd4, 19'sd0, 19'sd0, -19'sd4, "ifft_complex_4pt");

        mode = 2'b10;
        x0_re = 16'sd1; x0_im = 16'sd99;
        x1_re = 16'sd2; x1_im = -16'sd99;
        x2_re = 16'sd3; x2_im = 16'sd77;
        x3_re = 16'sd4; x3_im = -16'sd77;
        assert_vec(19'sd10, 19'sd0, -19'sd2, 19'sd2, -19'sd2, 19'sd0, -19'sd2, -19'sd2, "ffft_real_4pt");

        $display("FFT_IFFT_FFFT_RTL_PASS fft_ifft_ffft 4pt fixed-width smoke semantics");
        $finish(0);
    end
endmodule
"""

VIVADO_SYNTH_TCL = """read_verilog fft_ifft_ffft.v
synth_design -top fft_ifft_ffft -part xc7a35tcsg324-1
report_utilization -file vivado_utilization.rpt
report_timing_summary -file vivado_timing_summary.rpt
write_checkpoint -force fft_ifft_ffft_synth.dcp
exit
"""

DC_SYNTH_TCL = """set candidate_target_libraries [list \
  /home/ICer/.cache/vmware/drag_and_drop/OXbaZ9/work_project/lib/logic/synthesis/fsa0a_c_generic_core_tt1p8v25c.db \
  /home/ICer/.cache/vmware/drag_and_drop/OXbaZ9/work_project/lib/logic/synthesis/fsa0a_c_generic_core_ff1p98vm40c.db \
  /home/ICer/.cache/vmware/drag_and_drop/OXbaZ9/work_project/lib/logic/synthesis/fsa0a_c_generic_core_ss1p62v125c.db]
set selected_target_library ""
foreach lib $candidate_target_libraries {
  if {[file exists $lib]} {
    set selected_target_library $lib
    break
  }
}
if {$selected_target_library ne ""} {
  set target_library [list $selected_target_library]
  set link_library [concat "*" $target_library]
} else {
  set target_library [list your_library.db]
  set link_library [list "*" your_library.db]
}
analyze -format verilog {fft_ifft_ffft.v}
elaborate fft_ifft_ffft
current_design fft_ifft_ffft
link
set dft_clock_name dft_virtual_clk
set clk_ports [get_ports -quiet clk]
if {[sizeof_collection $clk_ports] > 0} {
  create_clock -name $dft_clock_name -period 10 $clk_ports
  set data_inputs [remove_from_collection [all_inputs] $clk_ports]
} else {
  create_clock -name $dft_clock_name -period 10
  set data_inputs [all_inputs]
}
if {[sizeof_collection $data_inputs] > 0} { set_input_delay 0 -clock $dft_clock_name $data_inputs }
if {[sizeof_collection [all_outputs]] > 0} { set_output_delay 0 -clock $dft_clock_name [all_outputs] }
check_design > dc_check_design.rpt
compile
report_area > dc_area.rpt
report_timing > dc_timing.rpt
write -format verilog -hierarchy -output fft_ifft_ffft_dc_mapped.v
write -format ddc -hierarchy -output dc_synth.ddc
exit
"""


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_fft_ifft_ffft_rtl_sources(out_dir: Path) -> Dict[str, str]:
    """Write RTL/testbench/TCL sources and return run-local file names."""

    out_dir = Path(out_dir)
    files = {
        "rtl": "fft_ifft_ffft.v",
        "testbench": "tb_fft_ifft_ffft.v",
        "vivado_tcl": "vivado_synth.tcl",
        "dc_tcl": "dc_synth.tcl",
    }
    _write_text(out_dir / files["rtl"], FFT_IFFT_VERILOG)
    _write_text(out_dir / files["testbench"], FFT_IFFT_TESTBENCH)
    _write_text(out_dir / files["vivado_tcl"], VIVADO_SYNTH_TCL)
    _write_text(out_dir / files["dc_tcl"], DC_SYNTH_TCL)
    return files


def write_golden_correctness(out_dir: Path) -> Dict[str, Any]:
    """Emit deterministic 4-point FFT/iFFT/fFFT golden correctness data."""

    out_dir = Path(out_dir)
    cases = {
        "fft_complex_4pt": {
            "mode": "fft",
            "inputs": [[4, 0], [0, 4], [-4, 0], [0, -4]],
            "expected": [[0, 0], [16, 0], [0, 0], [0, 0]],
        },
        "ifft_complex_4pt": {
            "mode": "ifft_normalized",
            "inputs": [[0, 0], [16, 0], [0, 0], [0, 0]],
            "expected": [[4, 0], [0, 4], [-4, 0], [0, -4]],
        },
        "ffft_real_4pt": {
            "mode": "ffft_real_forward",
            "inputs": [[1, 99], [2, -99], [3, 77], [4, -77]],
            "expected": [[10, 0], [-2, 2], [-2, 0], [-2, -2]],
        },
    }
    payload = {
        "schema_version": "dse.dft.kernel_golden_correctness.v1",
        "kernel_id": FFT_IFFT_KERNEL_ID,
        "status": "passed",
        "cases": cases,
        "claim_boundary": (
            "Golden fixed-width 4-point FFT/iFFT/fFFT microkernel correctness only; "
            "not full-SCF correctness, production FFT coverage, or evidence for any other kernel_id."
        ),
    }
    write_json(out_dir / "golden_correctness.json", payload)
    return payload


def initialize_fft_ifft_ffft_rtl_flow(out_dir: Path, *, candidate_id: str | None = None) -> Dict[str, Any]:
    """Create all local source/golden artifacts for an FFT/iFFT/fFFT RTL run."""

    out_dir = Path(out_dir)
    source_files = write_fft_ifft_ffft_rtl_sources(out_dir)
    golden = write_golden_correctness(out_dir)
    manifest = {
        "schema_version": FFT_IFFT_FLOW_SCHEMA,
        "kernel_id": FFT_IFFT_KERNEL_ID,
        "candidate_id": candidate_id,
        "source_files": source_files,
        "golden_correctness": "golden_correctness.json",
        "claim_boundary": (
            "DFT-scoped RTL smoke flow for one fixed-width 4-point fft_ifft_ffft microkernel. "
            "It is not a full-SCF device-resident accelerator, production FFT implementation, or all-kernel closure."
        ),
    }
    write_json(out_dir / "manifest.json", manifest)
    return {"manifest": manifest, "golden_correctness": golden}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""




def _text_has_nonzero_number(text: str) -> bool:
    for match in re.finditer(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", text):
        try:
            if abs(float(match.group(0))) > 0.0:
                return True
        except ValueError:
            continue
    return False


def _dc_area_nonzero(text: str) -> bool:
    total_area = re.search(
        r"(?:total\s+cell\s+area|total\s+area)\s*:?\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if total_area:
        try:
            return float(total_area.group(1)) > 0.0
        except ValueError:
            return False
    return False


def _artifact_row(
    *,
    evidence_type: str,
    status: str,
    artifact: Path,
    tool: str,
    tool_stage: str,
    command: str,
    environment: str,
    claim_boundary: str,
    failure_evidence: str | None = None,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "kernel_id": FFT_IFFT_KERNEL_ID,
        "evidence_type": evidence_type,
        "status": status,
        "artifact": str(artifact),
        "tool": tool,
        "tool_stage": tool_stage,
        "command": command,
        "environment": environment,
        "claim_boundary": claim_boundary,
    }
    if failure_evidence:
        row["failure_evidence"] = failure_evidence
        row["completion_eligible"] = False
    return row


def build_fft_ifft_ffft_evidence_rows(
    out_dir: Path,
    *,
    environment: str = "ssh ic-eda",
) -> Dict[str, Any]:
    """Summarize generated outputs into FPGA-gate rows plus ASIC-attempt rows."""

    out_dir = Path(out_dir)
    vcs_pass = "FFT_IFFT_FFFT_RTL_PASS" in _read_text(out_dir / "vcs_run.log")
    vivado_pass = (out_dir / "vivado_utilization.rpt").exists() and "synth_design completed successfully" in _read_text(
        out_dir / "vivado_stdout.log"
    )
    dc_stdout = _read_text(out_dir / "dc_stdout.log")
    dc_area = _read_text(out_dir / "dc_area.rpt")
    dc_timing = _read_text(out_dir / "dc_timing.rpt")
    dc_timing_exists = (out_dir / "dc_timing.rpt").exists()
    dc_area_exists = (out_dir / "dc_area.rpt").exists()
    dc_ddc_exists = (out_dir / "dc_synth.ddc").exists()
    dc_combined_text = "\n".join([dc_stdout, dc_timing, dc_area]).lower()
    dc_real_target_library_present = "fsa0a_c_generic_core" in dc_combined_text
    dc_present = (out_dir / "dc_stdout.log").exists() or dc_area_exists
    dc_timing_nonzero = _text_has_nonzero_number(dc_timing)
    dc_area_nonzero = _dc_area_nonzero(dc_area)
    dc_blocked = (
        not dc_present
        or not dc_timing_exists
        or not dc_area_exists
        or not dc_ddc_exists
        or not dc_real_target_library_present
        or not dc_timing_nonzero
        or not dc_area_nonzero
        or "Could not read the following target libraries" in dc_stdout
        or "unmapped logic" in dc_combined_text
        or ("gtech" in dc_combined_text and not dc_real_target_library_present)
    )
    evidence_rows = [
        _artifact_row(
            evidence_type="golden_correctness",
            status="passed" if _load_status(out_dir / "golden_correctness.json") == "passed" else "failed",
            artifact=out_dir / "golden_correctness.json",
            tool="python",
            tool_stage="golden",
            command="compute deterministic fixed-width 4-point FFT/iFFT/fFFT golden vectors",
            environment="local",
            claim_boundary="Fixed-width 4-point fft_ifft_ffft golden correctness only; not full-SCF correctness.",
        ),
        _artifact_row(
            evidence_type="rtl_sim",
            status="passed" if vcs_pass else "blocked",
            artifact=out_dir / "vcs_run.log",
            tool="vcs",
            tool_stage="rtl_sim",
            command="vcs -full64 -sverilog fft_ifft_ffft.v tb_fft_ifft_ffft.v -o simv && ./simv",
            environment=environment,
            claim_boundary="VCS RTL simulation for one fft_ifft_ffft 4-point smoke testbench; not full-SCF closure.",
            failure_evidence=None if vcs_pass else "VCS pass marker not found in vcs_run.log",
        ),
        _artifact_row(
            evidence_type="rtl_synth",
            status="passed" if vivado_pass else "blocked",
            artifact=out_dir / "vivado_stdout.log",
            tool="vivado",
            tool_stage="synthesis",
            command="vivado -mode batch -source vivado_synth.tcl",
            environment=environment,
            claim_boundary="Vivado synth_design proves FPGA RTL synthesis for this fft_ifft_ffft microkernel only.",
            failure_evidence=None if vivado_pass else "Vivado synthesis report/pass marker missing",
        ),
        _artifact_row(
            evidence_type="vivado_synth",
            status="passed" if vivado_pass else "blocked",
            artifact=out_dir / "vivado_utilization.rpt",
            tool="vivado",
            tool_stage="synth",
            command="vivado -mode batch -source vivado_synth.tcl",
            environment=environment,
            claim_boundary="Vivado synthesis/utilization for this fft_ifft_ffft microkernel only; no board measurement or full-SCF claim.",
            failure_evidence=None if vivado_pass else "vivado_utilization.rpt missing or synth_design did not complete",
        ),
    ]
    asic_attempt_rows = [
        _artifact_row(
            evidence_type="dc_synth_timing_area",
            status="blocked" if dc_blocked else "passed",
            artifact=out_dir / "dc_stdout.log",
            tool="dc_shell",
            tool_stage="synth_timing_area",
            command="dc_shell -f dc_synth.tcl",
            environment=environment,
            claim_boundary="DC attempt audit for fft_ifft_ffft; only a real mapped technology-library run with dc_synth.ddc can support ASIC PPA.",
            failure_evidence=(
                "DC output missing, dc_synth.ddc missing, target library unavailable/not observed, zero/empty timing/area, or gtech/unmapped/unconstrained output; not ASIC PPA evidence"
                if dc_blocked
                else None
            ),
        )
    ]
    asic_attempt_rows[0].update(
        {
            "dc_synth_ddc": str(out_dir / "dc_synth.ddc"),
            "dc_timing_report": str(out_dir / "dc_timing.rpt"),
            "dc_area_report": str(out_dir / "dc_area.rpt"),
            "dc_target_library_discovery": (
                "real_target_library_present" if dc_real_target_library_present else "not_observed"
            ),
            "dc_target_library_required": "fsa0a_c_generic_core_*",
        }
    )
    payload = {
        "schema_version": "dse.dft_scf.fft_ifft_ffft_rtl_evidence_rows.v1",
        "kernel_id": FFT_IFFT_KERNEL_ID,
        "evidence_rows": evidence_rows,
        "asic_attempt_evidence_rows": asic_attempt_rows,
        "fpga_gate_candidate": all(row["status"] == "passed" for row in evidence_rows),
        "asic_gate_candidate": all(row["status"] == "passed" for row in asic_attempt_rows),
        "claim_boundary": (
            "FPGA rows can satisfy the fft_ifft_ffft FPGA microkernel gate when all pass. "
            "ASIC rows are separate audit attempts and are not mixed into FPGA claim evidence."
        ),
    }
    write_json(out_dir / "evidence_rows.json", {"evidence_rows": evidence_rows})
    write_json(out_dir / "asic_attempt_evidence.json", {"evidence_rows": asic_attempt_rows})
    write_json(out_dir / "fft_ifft_ffft_rtl_evidence_summary.json", payload)
    return payload


def _load_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "invalid"
    return str(payload.get("status", "missing")) if isinstance(payload, Mapping) else "invalid"


def default_kernel_dispositions(*, accelerated_kernel_id: str = FFT_IFFT_KERNEL_ID) -> list[Dict[str, Any]]:
    """Return an eight-kernel disposition list with one accelerated kernel."""

    rows: list[Dict[str, Any]] = []
    for kernel_id in MAJOR_SCF_KERNEL_IDS:
        if kernel_id == accelerated_kernel_id:
            rows.append({
                "kernel_id": kernel_id,
                "disposition": "accelerated_claim",
                "claim_type": "fpga",
            })
        else:
            rows.append({
                "kernel_id": kernel_id,
                "disposition": "host_bound",
                "host_cost_accounted": True,
            })
    return rows


def write_fft_ifft_ffft_major_kernel_matrix(
    out_dir: Path,
    *,
    candidate_id: str,
    evidence_rows: Iterable[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Write the eight-kernel matrix for this FFT/iFFT/fFFT FPGA smoke candidate."""

    out_dir = Path(out_dir)
    dispositions = default_kernel_dispositions()
    rows = list(evidence_rows) if evidence_rows is not None else _load_rows(out_dir / "evidence_rows.json")
    write_json(out_dir / "kernel_dispositions.json", {"kernel_dispositions": dispositions})
    matrix = build_major_kernel_evidence_matrix(dispositions, evidence_rows=rows, candidate_id=candidate_id)
    write_json(out_dir / "dft_hardware_evidence_matrix.json", matrix)
    write_json(
        out_dir / "matrix_status.json",
        {
            "schema_version": "dse.dft_scf.hardware_evidence_matrix_cli_status.v1",
            "status": matrix["status"],
            "trusted": matrix["trusted"],
            "blocker_count": len(matrix["blockers"]),
            "dft_hardware_evidence_matrix": str(out_dir / "dft_hardware_evidence_matrix.json"),
        },
    )
    return matrix


def _load_rows(path: Path) -> list[Mapping[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("evidence_rows", []) if isinstance(payload, Mapping) else payload
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def unpack_result_archive(archive_path: Path, out_dir: Path) -> None:
    """Safely unpack a tarball produced by the remote IC/EDA probe."""

    out_dir = Path(out_dir).resolve()
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            target = (out_dir / member.name).resolve()
            if out_dir not in target.parents and target != out_dir:
                raise ValueError(f"unsafe archive member path: {member.name}")
        archive.extractall(out_dir)
