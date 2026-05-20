#!/usr/bin/env python3
"""DFT-scoped DMA/HBM movement RTL probe flow helpers.

This module intentionally lives under the DFT reference workload surface, not
in the generic DSE core.  It writes a minimal deterministic
``dma_hbm_movement_engine`` RTL address-generator smoke kernel plus testbench /
TCL scripts and normalizes real VCS/Vivado/DC attempt artifacts into the DFT
hardware claim-gate evidence rows.
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


DMA_HBM_KERNEL_ID = "dma_hbm_movement_engine"
DMA_HBM_FLOW_SCHEMA = "dse.dft_scf.dma_hbm_movement_engine_rtl_flow.v1"

DMA_HBM_VERILOG = r"""module dma_hbm_movement_engine #(
    parameter ADDR_WIDTH = 8,
    parameter LEN_WIDTH = 4
) (
    input  [1:0] mode,
    input  [ADDR_WIDTH-1:0] src_base,
    input  [ADDR_WIDTH-1:0] dst_base,
    input  [ADDR_WIDTH-1:0] src_stride,
    input  [ADDR_WIDTH-1:0] dst_stride,
    input  [ADDR_WIDTH-1:0] gather_base,
    input  [ADDR_WIDTH-1:0] scatter_base,
    input  [LEN_WIDTH-1:0] index,
    output reg [ADDR_WIDTH-1:0] src_addr,
    output reg [ADDR_WIDTH-1:0] dst_addr,
    output reg burst_like,
    output valid
);
    assign valid = 1'b1;

    always @* begin
        src_addr = src_base + index;
        dst_addr = dst_base + index;
        burst_like = 1'b1;
        case (mode)
            2'b00: begin
                src_addr = src_base + index;
                dst_addr = dst_base + index;
                burst_like = 1'b1;
            end
            2'b01: begin
                src_addr = src_base + (index * src_stride);
                dst_addr = dst_base + (index * dst_stride);
                burst_like = 1'b0;
            end
            2'b10: begin
                src_addr = gather_base + (index * src_stride);
                dst_addr = dst_base + index;
                burst_like = 1'b0;
            end
            default: begin
                src_addr = src_base + index;
                dst_addr = scatter_base + (index * dst_stride);
                burst_like = 1'b0;
            end
        endcase
    end
endmodule
"""

DMA_HBM_TESTBENCH = r"""module tb_dma_hbm_movement_engine;
    reg [1:0] mode;
    reg [7:0] src_base, dst_base, src_stride, dst_stride, gather_base, scatter_base;
    reg [3:0] index;
    wire [7:0] src_addr, dst_addr;
    wire burst_like, valid;
    reg [15:0] mem [0:63];
    integer i;

    dma_hbm_movement_engine dut(
        .mode(mode),
        .src_base(src_base),
        .dst_base(dst_base),
        .src_stride(src_stride),
        .dst_stride(dst_stride),
        .gather_base(gather_base),
        .scatter_base(scatter_base),
        .index(index),
        .src_addr(src_addr),
        .dst_addr(dst_addr),
        .burst_like(burst_like),
        .valid(valid)
    );

    task copy_word;
        input [1:0] t_mode;
        input [3:0] t_index;
        begin
            mode = t_mode;
            index = t_index;
            #1;
            if (!valid) begin
                $display("DMA_HBM_RTL_FAIL valid dropped at mode=%0d index=%0d", t_mode, t_index);
                $finish(1);
            end
            mem[dst_addr] = mem[src_addr];
        end
    endtask

    initial begin
        for (i = 0; i < 64; i = i + 1) begin
            mem[i] = 16'h1000 + i;
        end
        src_base = 8'd2;
        dst_base = 8'd20;
        src_stride = 8'd3;
        dst_stride = 8'd2;
        gather_base = 8'd5;
        scatter_base = 8'd40;
        mode = 2'b00;
        index = 4'd0;

        copy_word(2'b00, 4'd0);
        copy_word(2'b00, 4'd1);
        copy_word(2'b00, 4'd2);
        copy_word(2'b00, 4'd3);
        if (mem[20] !== 16'h1002 || mem[21] !== 16'h1003 || mem[22] !== 16'h1004 || mem[23] !== 16'h1005) begin
            $display("DMA_HBM_RTL_FAIL burst copy mismatch");
            $finish(1);
        end

        copy_word(2'b01, 4'd0);
        copy_word(2'b01, 4'd1);
        copy_word(2'b01, 4'd2);
        if (mem[20] !== 16'h1002 || mem[22] !== 16'h1005 || mem[24] !== 16'h1008) begin
            $display("DMA_HBM_RTL_FAIL strided copy mismatch");
            $finish(1);
        end

        copy_word(2'b10, 4'd0);
        copy_word(2'b10, 4'd1);
        copy_word(2'b10, 4'd2);
        if (mem[20] !== 16'h1005 || mem[21] !== 16'h1008 || mem[22] !== 16'h100b) begin
            $display("DMA_HBM_RTL_FAIL gather copy mismatch");
            $finish(1);
        end

        copy_word(2'b11, 4'd0);
        copy_word(2'b11, 4'd1);
        copy_word(2'b11, 4'd2);
        if (mem[40] !== 16'h1002 || mem[42] !== 16'h1003 || mem[44] !== 16'h1004) begin
            $display("DMA_HBM_RTL_FAIL scatter copy mismatch");
            $finish(1);
        end

        $display("DMA_HBM_RTL_PASS burst_stride_gather_scatter_semantics scatter=%0h,%0h,%0h",
            mem[40], mem[42], mem[44]);
        $finish(0);
    end
endmodule
"""

VIVADO_SYNTH_TCL = """read_verilog dma_hbm_movement_engine.v
synth_design -top dma_hbm_movement_engine -part xc7a35tcsg324-1
report_utilization -file vivado_utilization.rpt
report_timing_summary -file vivado_timing_summary.rpt
write_checkpoint -force dma_hbm_movement_engine_synth.dcp
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
analyze -format verilog {dma_hbm_movement_engine.v}
elaborate dma_hbm_movement_engine
current_design dma_hbm_movement_engine
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
write -format verilog -hierarchy -output dma_hbm_movement_engine_dc_mapped.v
write -format ddc -hierarchy -output dc_synth.ddc
exit
"""


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_dma_hbm_rtl_sources(out_dir: Path) -> Dict[str, str]:
    """Write RTL/testbench/TCL sources and return run-local file names."""

    out_dir = Path(out_dir)
    files = {
        "rtl": "dma_hbm_movement_engine.v",
        "testbench": "tb_dma_hbm_movement_engine.v",
        "vivado_tcl": "vivado_synth.tcl",
        "dc_tcl": "dc_synth.tcl",
    }
    _write_text(out_dir / files["rtl"], DMA_HBM_VERILOG)
    _write_text(out_dir / files["testbench"], DMA_HBM_TESTBENCH)
    _write_text(out_dir / files["vivado_tcl"], VIVADO_SYNTH_TCL)
    _write_text(out_dir / files["dc_tcl"], DC_SYNTH_TCL)
    return files


def _initial_memory_value(address: int) -> int:
    return 0x1000 + address


def write_golden_correctness(out_dir: Path) -> Dict[str, Any]:
    """Emit deterministic DMA/HBM address-generation and memory-copy golden data."""

    out_dir = Path(out_dir)
    inputs = {
        "src_base": 2,
        "dst_base": 20,
        "src_stride": 3,
        "dst_stride": 2,
        "gather_base": 5,
        "scatter_base": 40,
        "word_count": 4,
    }
    burst = {20 + i: _initial_memory_value(2 + i) for i in range(4)}
    stride = {20 + (i * 2): _initial_memory_value(2 + (i * 3)) for i in range(3)}
    gather = {20 + i: _initial_memory_value(5 + (i * 3)) for i in range(3)}
    scatter = {40 + (i * 2): _initial_memory_value(2 + i) for i in range(3)}
    expected = {
        "burst_copy": {str(key): value for key, value in burst.items()},
        "strided_copy": {str(key): value for key, value in stride.items()},
        "gather_copy": {str(key): value for key, value in gather.items()},
        "scatter_copy": {str(key): value for key, value in scatter.items()},
    }
    payload = {
        "schema_version": "dse.dft.kernel_golden_correctness.v1",
        "kernel_id": DMA_HBM_KERNEL_ID,
        "status": "passed" if expected["scatter_copy"] == {"40": 0x1002, "42": 0x1003, "44": 0x1004} else "failed",
        "inputs": inputs,
        "expected": expected,
        "claim_boundary": (
            "Golden deterministic DMA/HBM movement-engine address-generation and small-memory copy semantics only; "
            "not full-SCF correctness and not evidence for any other kernel_id."
        ),
    }
    write_json(out_dir / "golden_correctness.json", payload)
    return payload


def initialize_dma_hbm_rtl_flow(out_dir: Path, *, candidate_id: str | None = None) -> Dict[str, Any]:
    """Create all local source/golden artifacts for a DMA/HBM RTL run."""

    out_dir = Path(out_dir)
    source_files = write_dma_hbm_rtl_sources(out_dir)
    golden = write_golden_correctness(out_dir)
    manifest = {
        "schema_version": DMA_HBM_FLOW_SCHEMA,
        "kernel_id": DMA_HBM_KERNEL_ID,
        "candidate_id": candidate_id,
        "source_files": source_files,
        "golden_correctness": "golden_correctness.json",
        "semantics": ["burst_copy", "strided_copy", "gather_copy", "scatter_copy"],
        "claim_boundary": (
            "DFT-scoped RTL smoke flow for one DMA/HBM movement address-generator microkernel. "
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
        "kernel_id": DMA_HBM_KERNEL_ID,
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


def build_dma_hbm_evidence_rows(
    out_dir: Path,
    *,
    environment: str = "ssh ic-eda",
) -> Dict[str, Any]:
    """Summarize generated outputs into FPGA-gate rows plus ASIC-attempt rows."""

    out_dir = Path(out_dir)
    vcs_pass = "DMA_HBM_RTL_PASS" in _read_text(out_dir / "vcs_run.log")
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
            command="compute deterministic DMA/HBM burst/stride/gather/scatter golden memory movement",
            environment="local",
            claim_boundary="DMA/HBM movement-engine address-generation and small-memory copy semantics only; not full-SCF correctness.",
        ),
        _artifact_row(
            evidence_type="rtl_sim",
            status="passed" if vcs_pass else "blocked",
            artifact=out_dir / "vcs_run.log",
            tool="vcs",
            tool_stage="rtl_sim",
            command="vcs -full64 -sverilog dma_hbm_movement_engine.v tb_dma_hbm_movement_engine.v -o simv && ./simv",
            environment=environment,
            claim_boundary="VCS RTL simulation for one DMA/HBM movement microkernel testbench; not full-SCF closure.",
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
    asic_attempt_rows = [
        _artifact_row(
            evidence_type="dc_synth_timing_area",
            status="blocked" if dc_blocked else "passed",
            artifact=out_dir / "dc_stdout.log",
            tool="dc_shell",
            tool_stage="synth_timing_area",
            command="dc_shell -f dc_synth.tcl",
            environment=environment,
            claim_boundary="DC attempt audit for dma_hbm_movement_engine; only a real mapped technology-library run with dc_synth.ddc can support ASIC PPA.",
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
        "schema_version": "dse.dft_scf.dma_hbm_movement_engine_rtl_evidence_rows.v1",
        "kernel_id": DMA_HBM_KERNEL_ID,
        "evidence_rows": evidence_rows,
        "asic_attempt_evidence_rows": asic_attempt_rows,
        "fpga_gate_candidate": all(row["status"] == "passed" for row in evidence_rows),
        "asic_gate_candidate": all(row["status"] == "passed" for row in asic_attempt_rows),
        "claim_boundary": (
            "FPGA rows can satisfy the dma_hbm_movement_engine FPGA microkernel gate when all pass. "
            "ASIC rows are separate audit attempts and are not mixed into FPGA claim evidence."
        ),
    }
    write_json(out_dir / "evidence_rows.json", {"evidence_rows": evidence_rows})
    write_json(out_dir / "asic_attempt_evidence.json", {"evidence_rows": asic_attempt_rows})
    write_json(out_dir / "dma_hbm_movement_engine_rtl_evidence_summary.json", payload)
    return payload


def _load_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "invalid"
    return str(payload.get("status", "missing")) if isinstance(payload, Mapping) else "invalid"


def default_kernel_dispositions(*, accelerated_kernel_id: str = DMA_HBM_KERNEL_ID) -> list[Dict[str, Any]]:
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


def write_dma_hbm_major_kernel_matrix(
    out_dir: Path,
    *,
    candidate_id: str,
    evidence_rows: Iterable[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Write the eight-kernel matrix for this DMA/HBM FPGA smoke candidate."""

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
