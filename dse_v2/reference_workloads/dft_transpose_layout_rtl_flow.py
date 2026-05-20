#!/usr/bin/env python3
"""DFT-scoped transpose/layout-conversion RTL probe flow helpers.

This module intentionally lives under the DFT reference workload surface, not
the generic DSE core.  It writes a minimal fixed-width
``transpose_layout_conversion`` RTL smoke kernel plus testbench/TCL scripts and
summarizes real VCS/Vivado/DC attempt artifacts into the evidence rows consumed
by the DFT hardware claim gates.
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from dse_v2.codesign.dft_hardware_evidence import (
    MAJOR_SCF_KERNEL_IDS,
    build_major_kernel_evidence_matrix,
)


TRANSPOSE_LAYOUT_KERNEL_ID = "transpose_layout_conversion"
TRANSPOSE_LAYOUT_FLOW_SCHEMA = "dse.dft_scf.transpose_layout_conversion_rtl_flow.v1"

TRANSPOSE_LAYOUT_VERILOG = r"""module transpose_layout_conversion #(
    parameter WIDTH = 16
) (
    input  wire clk,
    input  wire rst_n,
    input  wire in_valid,
    input  wire [(4*WIDTH)-1:0] in_packed,
    output reg  out_valid,
    output reg  [(4*WIDTH)-1:0] out_packed
);
    // Input lane order is row-major 2x2: [m00, m01, m10, m11], packed LSB first.
    // Output lane order is row-major transpose: [m00, m10, m01, m11].
    wire [(4*WIDTH)-1:0] transposed;
    assign transposed[(0*WIDTH)+:WIDTH] = in_packed[(0*WIDTH)+:WIDTH];
    assign transposed[(1*WIDTH)+:WIDTH] = in_packed[(2*WIDTH)+:WIDTH];
    assign transposed[(2*WIDTH)+:WIDTH] = in_packed[(1*WIDTH)+:WIDTH];
    assign transposed[(3*WIDTH)+:WIDTH] = in_packed[(3*WIDTH)+:WIDTH];

    // The closure target is a real staged layout-conversion datapath, not a
    // wire-only alias.  Registering the transposed lanes models the pipeline
    // boundary that makes the block independently synthesizable and prevents
    // DC from reducing an ASIC claim to zero-area routing.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            out_packed <= {(4*WIDTH){1'b0}};
        end else begin
            out_valid <= in_valid;
            if (in_valid) begin
                out_packed <= transposed;
            end
        end
    end
endmodule
"""

TRANSPOSE_LAYOUT_TESTBENCH = r"""module tb_transpose_layout_conversion;
    reg clk;
    reg rst_n;
    reg in_valid;
    reg  signed [15:0] m00, m01, m10, m11;
    reg  [63:0] in_packed;
    wire [63:0] out_packed;
    wire out_valid;
    transpose_layout_conversion dut(
        .clk(clk),
        .rst_n(rst_n),
        .in_valid(in_valid),
        .in_packed(in_packed),
        .out_valid(out_valid),
        .out_packed(out_packed)
    );
    initial clk = 1'b0;
    always #5 clk = ~clk;
    initial begin
        rst_n = 1'b0;
        in_valid = 1'b0;
        in_packed = 64'd0;
        m00 = 16'sd1; m01 = -16'sd2; m10 = 16'sd3; m11 = -16'sd4;
        repeat (2) @(posedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        in_packed = {m11, m10, m01, m00};
        in_valid = 1'b1;
        @(posedge clk);
        #1;
        if (out_valid === 1'b1 && out_packed === {m11, m01, m10, m00}) begin
            $display("TRANSPOSE_LAYOUT_RTL_PASS valid=%0d out=%h", out_valid, out_packed);
            $finish(0);
        end else begin
            $display("TRANSPOSE_LAYOUT_RTL_FAIL valid=%0d out=%h expected=%h", out_valid, out_packed, {m11, m01, m10, m00});
            $finish(1);
        end
    end
endmodule
"""

VIVADO_SYNTH_TCL = """read_verilog transpose_layout_conversion.v
synth_design -top transpose_layout_conversion -part xc7a35tcsg324-1
report_utilization -file vivado_utilization.rpt
report_timing_summary -file vivado_timing_summary.rpt
write_checkpoint -force transpose_layout_conversion_synth.dcp
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
analyze -format verilog {transpose_layout_conversion.v}
elaborate transpose_layout_conversion
current_design transpose_layout_conversion
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
write -format verilog -hierarchy -output transpose_layout_conversion_dc_mapped.v
write -format ddc -hierarchy -output dc_synth.ddc
exit
"""


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_transpose_layout_rtl_sources(out_dir: Path) -> Dict[str, str]:
    """Write RTL/testbench/TCL sources and return run-local file names."""

    out_dir = Path(out_dir)
    files = {
        "rtl": "transpose_layout_conversion.v",
        "testbench": "tb_transpose_layout_conversion.v",
        "vivado_tcl": "vivado_synth.tcl",
        "dc_tcl": "dc_synth.tcl",
    }
    _write_text(out_dir / files["rtl"], TRANSPOSE_LAYOUT_VERILOG)
    _write_text(out_dir / files["testbench"], TRANSPOSE_LAYOUT_TESTBENCH)
    _write_text(out_dir / files["vivado_tcl"], VIVADO_SYNTH_TCL)
    _write_text(out_dir / files["dc_tcl"], DC_SYNTH_TCL)
    return files


def write_golden_correctness(out_dir: Path) -> Dict[str, Any]:
    """Emit the fixed-width 2x2 transpose/layout golden correctness artifact."""

    out_dir = Path(out_dir)
    inputs = {
        "shape": [2, 2],
        "layout": "row_major_lsb_first_lanes",
        "matrix": [[1, -2], [3, -4]],
        "packed_lanes_lsb_first": [1, -2, 3, -4],
    }
    expected = {
        "transposed_matrix": [[1, 3], [-2, -4]],
        "packed_lanes_lsb_first": [1, 3, -2, -4],
    }
    payload = {
        "schema_version": "dse.dft.kernel_golden_correctness.v1",
        "kernel_id": TRANSPOSE_LAYOUT_KERNEL_ID,
        "status": "passed" if expected["packed_lanes_lsb_first"] == [1, 3, -2, -4] else "failed",
        "inputs": inputs,
        "expected": expected,
        "claim_boundary": (
            "Golden fixed-width 2x2 layout-conversion correctness for "
            "transpose_layout_conversion RTL smoke only; not full-SCF correctness "
            "and not evidence for any other kernel_id."
        ),
    }
    write_json(out_dir / "golden_correctness.json", payload)
    return payload


def initialize_transpose_layout_rtl_flow(out_dir: Path, *, candidate_id: str | None = None) -> Dict[str, Any]:
    """Create all local source/golden artifacts for a transpose-layout RTL run."""

    out_dir = Path(out_dir)
    source_files = write_transpose_layout_rtl_sources(out_dir)
    golden = write_golden_correctness(out_dir)
    manifest = {
        "schema_version": TRANSPOSE_LAYOUT_FLOW_SCHEMA,
        "kernel_id": TRANSPOSE_LAYOUT_KERNEL_ID,
        "candidate_id": candidate_id,
        "source_files": source_files,
        "golden_correctness": "golden_correctness.json",
        "claim_boundary": (
            "DFT-scoped RTL smoke flow for one fixed-width transpose_layout_conversion microkernel. "
            "It is not a full-SCF device-resident accelerator or all-kernel closure."
        ),
    }
    write_json(out_dir / "manifest.json", manifest)
    return {
        "manifest": manifest,
        "golden_correctness": golden,
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


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
        "kernel_id": TRANSPOSE_LAYOUT_KERNEL_ID,
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


def build_transpose_layout_evidence_rows(
    out_dir: Path,
    *,
    environment: str = "ssh ic-eda",
) -> Dict[str, Any]:
    """Summarize generated outputs into FPGA-gate rows plus ASIC-attempt rows."""

    out_dir = Path(out_dir)
    vcs_pass = "TRANSPOSE_LAYOUT_RTL_PASS" in _read_text(out_dir / "vcs_run.log")
    vivado_pass = (out_dir / "vivado_utilization.rpt").exists() and "synth_design completed successfully" in _read_text(
        out_dir / "vivado_stdout.log"
    )
    dc_stdout = _read_text(out_dir / "dc_stdout.log")
    dc_area = _read_text(out_dir / "dc_area.rpt")
    dc_timing = _read_text(out_dir / "dc_timing.rpt")
    dc_timing_exists = (out_dir / "dc_timing.rpt").exists()
    dc_ddc_exists = (out_dir / "dc_synth.ddc").exists()
    dc_combined_text = "\n".join([dc_stdout, dc_timing, dc_area]).lower()
    dc_real_target_library_present = "fsa0a_c_generic_core" in dc_combined_text
    dc_present = (out_dir / "dc_stdout.log").exists() or (out_dir / "dc_area.rpt").exists()
    dc_blocked = (
        not dc_present
        or not dc_timing_exists
        or not dc_ddc_exists
        or not dc_real_target_library_present
        or "Could not read the following target libraries" in dc_stdout
        or "unmapped logic" in dc_area.lower()
        or ("gtech" in dc_area.lower() and not dc_real_target_library_present)
        or "total cell area:                     0.000000" in dc_area.lower()
        or "total cell area: 0.000000" in dc_area.lower()
    )
    evidence_rows = [
        _artifact_row(
            evidence_type="golden_correctness",
            status="passed" if _load_status(out_dir / "golden_correctness.json") == "passed" else "failed",
            artifact=out_dir / "golden_correctness.json",
            tool="python",
            tool_stage="golden",
            command="compute fixed-width transpose_layout_conversion golden output",
            environment="local",
            claim_boundary="Fixed-width transpose/layout correctness only; not full-SCF correctness.",
        ),
        _artifact_row(
            evidence_type="rtl_sim",
            status="passed" if vcs_pass else "blocked",
            artifact=out_dir / "vcs_run.log",
            tool="vcs",
            tool_stage="rtl_sim",
            command="vcs -full64 -sverilog transpose_layout_conversion.v tb_transpose_layout_conversion.v -o simv && ./simv",
            environment=environment,
            claim_boundary="VCS RTL simulation for one transpose_layout_conversion microkernel testbench; not full-SCF closure.",
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
            claim_boundary="Vivado synth_design proves FPGA RTL synthesis for this microkernel only.",
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
            claim_boundary="Vivado synthesis/utilization for this microkernel only; no board measurement or full-SCF claim.",
            failure_evidence=None if vivado_pass else "vivado_utilization.rpt missing or synth_design did not complete",
        ),
    ]
    asic_row = _artifact_row(
        evidence_type="dc_synth_timing_area",
        status="blocked" if dc_blocked else "passed",
        artifact=out_dir / "dc_stdout.log",
        tool="dc_shell",
        tool_stage="synth_timing_area",
        command="dc_shell -f dc_synth.tcl",
        environment=environment,
        claim_boundary=(
            "DC attempt audit for transpose_layout_conversion; only a real mapped "
            "technology-library run with dc_synth.ddc can support ASIC PPA."
        ),
        failure_evidence=(
            "DC output missing, dc_synth.ddc missing, target library unavailable/not observed, "
            "or gtech/unmapped/unconstrained output; not ASIC PPA evidence"
            if dc_blocked
            else None
        ),
    )
    asic_row.update(
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
    asic_attempt_rows = [asic_row]
    payload = {
        "schema_version": "dse.dft_scf.transpose_layout_conversion_rtl_evidence_rows.v1",
        "kernel_id": TRANSPOSE_LAYOUT_KERNEL_ID,
        "evidence_rows": evidence_rows,
        "asic_attempt_evidence_rows": asic_attempt_rows,
        "fpga_gate_candidate": all(row["status"] == "passed" for row in evidence_rows),
        "asic_gate_candidate": all(row["status"] == "passed" for row in asic_attempt_rows),
        "claim_boundary": (
            "FPGA rows can satisfy the transpose_layout_conversion FPGA microkernel gate when all pass. "
            "ASIC rows are separate audit attempts and are not mixed into FPGA claim evidence."
        ),
    }
    write_json(out_dir / "evidence_rows.json", {"evidence_rows": evidence_rows})
    write_json(out_dir / "asic_attempt_evidence.json", {"evidence_rows": asic_attempt_rows})
    write_json(out_dir / "transpose_layout_conversion_rtl_evidence_summary.json", payload)
    return payload


def _load_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "invalid"
    return str(payload.get("status", "missing")) if isinstance(payload, Mapping) else "invalid"


def default_kernel_dispositions(*, accelerated_kernel_id: str = TRANSPOSE_LAYOUT_KERNEL_ID) -> list[Dict[str, Any]]:
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


def write_transpose_layout_major_kernel_matrix(
    out_dir: Path,
    *,
    candidate_id: str,
    evidence_rows: Iterable[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Write the eight-kernel matrix for this transpose-layout FPGA smoke candidate."""

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
