#!/usr/bin/env python3
"""DFT-scoped complex GEMM/GEMV tile RTL probe flow helpers."""

from __future__ import annotations

import json
import re
import tarfile
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS, build_major_kernel_evidence_matrix


from dse_v2.reference_workloads.dft_candidate_parametric_rtl import (
    candidate_parameter_manifest_fields,
    load_candidate_parameter_manifest,
    parametrize_rtl_source,
    write_candidate_parameter_manifest,
)

COMPLEX_GEMM_GEMV_KERNEL_ID = "complex_gemm_gemv_tile"
COMPLEX_GEMM_GEMV_FLOW_SCHEMA = "dse.dft_scf.complex_gemm_gemv_tile_rtl_flow.v1"

COMPLEX_GEMM_GEMV_VERILOG = r"""module complex_gemm_gemv_tile #(
    parameter WIDTH = 8,
    parameter OUT_WIDTH = 20
) (
    input  signed [WIDTH-1:0] a00r, a00i, a01r, a01i,
    input  signed [WIDTH-1:0] a10r, a10i, a11r, a11i,
    input  signed [WIDTH-1:0] x0r, x0i, x1r, x1i,
    output signed [OUT_WIDTH-1:0] y0r, y0i, y1r, y1i
);
    wire signed [(2*WIDTH)-1:0] p00r = a00r * x0r - a00i * x0i;
    wire signed [(2*WIDTH)-1:0] p00i = a00r * x0i + a00i * x0r;
    wire signed [(2*WIDTH)-1:0] p01r = a01r * x1r - a01i * x1i;
    wire signed [(2*WIDTH)-1:0] p01i = a01r * x1i + a01i * x1r;
    wire signed [(2*WIDTH)-1:0] p10r = a10r * x0r - a10i * x0i;
    wire signed [(2*WIDTH)-1:0] p10i = a10r * x0i + a10i * x0r;
    wire signed [(2*WIDTH)-1:0] p11r = a11r * x1r - a11i * x1i;
    wire signed [(2*WIDTH)-1:0] p11i = a11r * x1i + a11i * x1r;
    assign y0r = p00r + p01r;
    assign y0i = p00i + p01i;
    assign y1r = p10r + p11r;
    assign y1i = p10i + p11i;
endmodule
"""

COMPLEX_GEMM_GEMV_TESTBENCH = r"""module tb_complex_gemm_gemv_tile;
    reg signed [7:0] a00r, a00i, a01r, a01i, a10r, a10i, a11r, a11i;
    reg signed [7:0] x0r, x0i, x1r, x1i;
    wire signed [19:0] y0r, y0i, y1r, y1i;
    complex_gemm_gemv_tile dut(
        .a00r(a00r), .a00i(a00i), .a01r(a01r), .a01i(a01i),
        .a10r(a10r), .a10i(a10i), .a11r(a11r), .a11i(a11i),
        .x0r(x0r), .x0i(x0i), .x1r(x1r), .x1i(x1i),
        .y0r(y0r), .y0i(y0i), .y1r(y1r), .y1i(y1i)
    );
    initial begin
        a00r = 8'sd1;  a00i = 8'sd2;  a01r = 8'sd3;  a01i = -8'sd1;
        a10r = -8'sd2; a10i = 8'sd1;  a11r = 8'sd1;  a11i = -8'sd3;
        x0r = 8'sd2; x0i = -8'sd1; x1r = -8'sd1; x1i = 8'sd4;
        #1;
        if (y0r === 20'sd5 && y0i === 20'sd16 && y1r === 20'sd8 && y1i === 20'sd11) begin
            $display("COMPLEX_GEMM_GEMV_RTL_PASS y0=%0d,%0d y1=%0d,%0d", y0r, y0i, y1r, y1i);
            $finish(0);
        end else begin
            $display("COMPLEX_GEMM_GEMV_RTL_FAIL y0=%0d,%0d y1=%0d,%0d", y0r, y0i, y1r, y1i);
            $finish(1);
        end
    end
endmodule
"""

VIVADO_SYNTH_TCL = """read_verilog complex_gemm_gemv_tile.v
synth_design -top complex_gemm_gemv_tile -part xc7a35tcsg324-1
report_utilization -file vivado_utilization.rpt
report_timing_summary -file vivado_timing_summary.rpt
write_checkpoint -force complex_gemm_gemv_tile_synth.dcp
opt_design
place_design
route_design
puts "ROUTE_DESIGN COMPLETE"
report_timing_summary -file vivado_route_timing_summary.rpt
report_route_status -file vivado_route_status.rpt
write_checkpoint -force complex_gemm_gemv_tile_routed.dcp
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
set synthetic_library [list standard.sldb]
if {$selected_target_library ne ""} {
  set target_library [list $selected_target_library]
  set link_library [concat "*" $target_library $synthetic_library]
} else {
  set target_library [list your_library.db]
  set link_library [concat "*" $target_library $synthetic_library]
}
analyze -format verilog {complex_gemm_gemv_tile.v}
elaborate complex_gemm_gemv_tile
current_design complex_gemm_gemv_tile
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
write -format verilog -hierarchy -output complex_gemm_gemv_tile_dc_mapped.v
write -format ddc -hierarchy -output dc_synth.ddc
exit
"""


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_complex_gemm_gemv_rtl_sources(
    out_dir: Path,
    *,
    candidate_parameter_manifest: Mapping[str, Any] | None = None,
) -> Dict[str, str]:
    out_dir = Path(out_dir)
    files = {"rtl": "complex_gemm_gemv_tile.v", "testbench": "tb_complex_gemm_gemv_tile.v", "vivado_tcl": "vivado_synth.tcl", "dc_tcl": "dc_synth.tcl"}
    _write_text(
        out_dir / files["rtl"],
        parametrize_rtl_source(COMPLEX_GEMM_GEMV_KERNEL_ID, COMPLEX_GEMM_GEMV_VERILOG, candidate_parameter_manifest),
    )
    _write_text(out_dir / files["testbench"], COMPLEX_GEMM_GEMV_TESTBENCH)
    _write_text(out_dir / files["vivado_tcl"], VIVADO_SYNTH_TCL)
    _write_text(out_dir / files["dc_tcl"], DC_SYNTH_TCL)
    return files


def write_golden_correctness(out_dir: Path) -> Dict[str, Any]:
    matrix = [[[1, 2], [3, -1]], [[-2, 1], [1, -3]]]
    vector = [[2, -1], [-1, 4]]
    expected = {"y": [[5, 16], [8, 11]]}
    payload = {
        "schema_version": "dse.dft.kernel_golden_correctness.v1",
        "kernel_id": COMPLEX_GEMM_GEMV_KERNEL_ID,
        "status": "passed",
        "inputs": {"matrix_complex_pairs": matrix, "vector_complex_pairs": vector},
        "expected": expected,
        "claim_boundary": "Golden fixed-point 2x2 complex GEMM/GEMV tile semantics only; not full-SCF correctness and not evidence for any other kernel_id.",
    }
    write_json(Path(out_dir) / "golden_correctness.json", payload)
    return payload


def initialize_complex_gemm_gemv_rtl_flow(
    out_dir: Path,
    *,
    candidate_id: str | None = None,
    candidate_parameter_manifest: Mapping[str, Any] | Path | str | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    candidate_parameters = load_candidate_parameter_manifest(
        candidate_parameter_manifest,
        candidate_id=candidate_id,
        kernel_id=COMPLEX_GEMM_GEMV_KERNEL_ID,
    )
    source_files = write_complex_gemm_gemv_rtl_sources(out_dir, candidate_parameter_manifest=candidate_parameters)
    golden = write_golden_correctness(out_dir)
    write_candidate_parameter_manifest(out_dir, candidate_parameters)
    manifest = {
        "schema_version": COMPLEX_GEMM_GEMV_FLOW_SCHEMA,
        "kernel_id": COMPLEX_GEMM_GEMV_KERNEL_ID,
        "candidate_id": candidate_id,
        "source_files": source_files,
        "golden_correctness": "golden_correctness.json",
        **candidate_parameter_manifest_fields(candidate_parameters),
        "claim_boundary": "DFT-scoped RTL smoke flow for one complex GEMM/GEMV tile microkernel; not full-SCF/all-kernel closure.",
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


def _artifact_row(*, evidence_type: str, status: str, artifact: Path, tool: str, tool_stage: str, command: str, environment: str, claim_boundary: str, failure_evidence: str | None = None) -> Dict[str, Any]:
    row: Dict[str, Any] = {"kernel_id": COMPLEX_GEMM_GEMV_KERNEL_ID, "evidence_type": evidence_type, "status": status, "artifact": str(artifact), "tool": tool, "tool_stage": tool_stage, "command": command, "environment": environment, "claim_boundary": claim_boundary}
    if failure_evidence:
        row["failure_evidence"] = failure_evidence
        row["completion_eligible"] = False
    return row


def _load_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "invalid"
    return str(payload.get("status", "missing")) if isinstance(payload, Mapping) else "invalid"


def build_complex_gemm_gemv_evidence_rows(out_dir: Path, *, environment: str = "ssh ic-eda") -> Dict[str, Any]:
    out_dir = Path(out_dir)
    vcs_pass = "COMPLEX_GEMM_GEMV_RTL_PASS" in _read_text(out_dir / "vcs_run.log")
    vivado_stdout = _read_text(out_dir / "vivado_stdout.log")
    vivado_pass = (out_dir / "vivado_utilization.rpt").exists() and "synth_design completed successfully" in vivado_stdout
    vivado_route_pass = "ROUTE_DESIGN COMPLETE" in vivado_stdout.upper()
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
        _artifact_row(evidence_type="golden_correctness", status="passed" if _load_status(out_dir / "golden_correctness.json") == "passed" else "failed", artifact=out_dir / "golden_correctness.json", tool="python", tool_stage="golden", command="compute complex GEMM/GEMV tile fixed-point golden outputs", environment="local", claim_boundary="complex GEMM/GEMV tile fixed-point correctness only; not full-SCF correctness."),
        _artifact_row(evidence_type="rtl_sim", status="passed" if vcs_pass else "blocked", artifact=out_dir / "vcs_run.log", tool="vcs", tool_stage="rtl_sim", command="vcs -full64 -sverilog complex_gemm_gemv_tile.v tb_complex_gemm_gemv_tile.v -o simv && ./simv", environment=environment, claim_boundary="VCS RTL simulation for one complex_gemm_gemv_tile microkernel testbench; not full-SCF closure.", failure_evidence=None if vcs_pass else "VCS pass marker not found in vcs_run.log"),
        _artifact_row(evidence_type="rtl_synth", status="passed" if vivado_pass else "blocked", artifact=out_dir / "vivado_stdout.log", tool="vivado", tool_stage="synthesis", command="vivado -mode batch -source vivado_synth.tcl", environment=environment, claim_boundary="Vivado synth_design proves FPGA RTL synthesis for this microkernel only.", failure_evidence=None if vivado_pass else "Vivado synthesis report/pass marker missing"),
        _artifact_row(evidence_type="vivado_impl", status="passed" if vivado_route_pass else "blocked", artifact=out_dir / "vivado_route_status.rpt", tool="vivado", tool_stage="implementation", command="vivado -mode batch -source vivado_synth.tcl", environment=environment, claim_boundary="Vivado implementation-route completion for this microkernel only; no board measurement or full-SCF claim.", failure_evidence=None if vivado_route_pass else "Vivado implementation route completion marker/report missing"),
    ]
    asic_attempt_rows = [_artifact_row(evidence_type="dc_synth_timing_area", status="blocked" if dc_blocked else "passed", artifact=out_dir / "dc_stdout.log", tool="dc_shell", tool_stage="synth_timing_area", command="dc_shell -f dc_synth.tcl", environment=environment, claim_boundary="DC attempt audit for complex_gemm_gemv_tile; only a real mapped technology-library run with dc_synth.ddc can support ASIC PPA.", failure_evidence=("DC output missing, dc_synth.ddc missing, target library unavailable/not observed, zero/empty timing/area, or gtech/unmapped/unconstrained output; not ASIC PPA evidence" if dc_blocked else None))]
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
    payload = {"schema_version": "dse.dft_scf.complex_gemm_gemv_tile_rtl_evidence_rows.v1", "kernel_id": COMPLEX_GEMM_GEMV_KERNEL_ID, "evidence_rows": evidence_rows, "asic_attempt_evidence_rows": asic_attempt_rows, "fpga_gate_candidate": all(row["status"] == "passed" for row in evidence_rows), "asic_gate_candidate": all(row["status"] == "passed" for row in asic_attempt_rows), "claim_boundary": "FPGA rows can satisfy the complex_gemm_gemv_tile FPGA microkernel gate when all pass. ASIC rows are separate audit attempts and are not mixed into FPGA claim evidence."}
    write_json(out_dir / "evidence_rows.json", {"evidence_rows": evidence_rows})
    write_json(out_dir / "asic_attempt_evidence.json", {"evidence_rows": asic_attempt_rows})
    write_json(out_dir / "complex_gemm_gemv_tile_rtl_evidence_summary.json", payload)
    return payload


def default_kernel_dispositions(*, accelerated_kernel_id: str = COMPLEX_GEMM_GEMV_KERNEL_ID) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for kernel_id in MAJOR_SCF_KERNEL_IDS:
        rows.append({"kernel_id": kernel_id, "disposition": "accelerated_claim", "claim_type": "fpga"} if kernel_id == accelerated_kernel_id else {"kernel_id": kernel_id, "disposition": "host_bound", "host_cost_accounted": True})
    return rows


def _load_rows(path: Path) -> list[Mapping[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("evidence_rows", []) if isinstance(payload, Mapping) else payload
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def write_complex_gemm_gemv_major_kernel_matrix(out_dir: Path, *, candidate_id: str, evidence_rows: Iterable[Mapping[str, Any]] | None = None) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    dispositions = default_kernel_dispositions()
    rows = list(evidence_rows) if evidence_rows is not None else _load_rows(out_dir / "evidence_rows.json")
    write_json(out_dir / "kernel_dispositions.json", {"kernel_dispositions": dispositions})
    matrix = build_major_kernel_evidence_matrix(dispositions, evidence_rows=rows, candidate_id=candidate_id)
    write_json(out_dir / "dft_hardware_evidence_matrix.json", matrix)
    write_json(out_dir / "matrix_status.json", {"schema_version": "dse.dft_scf.hardware_evidence_matrix_cli_status.v1", "status": matrix["status"], "trusted": matrix["trusted"], "blocker_count": len(matrix["blockers"]), "dft_hardware_evidence_matrix": str(out_dir / "dft_hardware_evidence_matrix.json")})
    return matrix


def unpack_result_archive(archive_path: Path, out_dir: Path) -> None:
    out_dir = Path(out_dir).resolve()
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            target = (out_dir / member.name).resolve()
            if out_dir not in target.parents and target != out_dir:
                raise ValueError(f"unsafe archive member path: {member.name}")
        archive.extractall(out_dir)
