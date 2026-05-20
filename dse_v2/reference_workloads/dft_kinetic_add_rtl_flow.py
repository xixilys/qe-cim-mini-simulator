#!/usr/bin/env python3
"""DFT-scoped kinetic-add RTL probe flow helpers.

This module intentionally lives under the DFT reference workload surface, not
the generic DSE core.  It writes a minimal fixed-point ``kinetic_add`` RTL smoke
kernel plus testbench/TCL scripts and summarizes real VCS/Vivado/DC attempt
artifacts into the evidence rows consumed by the DFT hardware claim gates.
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


KINETIC_ADD_KERNEL_ID = "kinetic_add"
KINETIC_ADD_FLOW_SCHEMA = "dse.dft_scf.kinetic_add_rtl_flow.v1"

KINETIC_ADD_VERILOG = r"""module kinetic_add #(
    parameter WIDTH = 16
) (
    input  signed [WIDTH-1:0] psi_re,
    input  signed [WIDTH-1:0] psi_im,
    input  signed [WIDTH-1:0] hpsi_re_in,
    input  signed [WIDTH-1:0] hpsi_im_in,
    input  signed [WIDTH-1:0] g2kin,
    output signed [(2*WIDTH):0] hpsi_re_out,
    output signed [(2*WIDTH):0] hpsi_im_out
);
    wire signed [(2*WIDTH)-1:0] kinetic_re = psi_re * g2kin;
    wire signed [(2*WIDTH)-1:0] kinetic_im = psi_im * g2kin;
    wire signed [(2*WIDTH):0] hpsi_re_ext = {{(WIDTH+1){hpsi_re_in[WIDTH-1]}}, hpsi_re_in};
    wire signed [(2*WIDTH):0] hpsi_im_ext = {{(WIDTH+1){hpsi_im_in[WIDTH-1]}}, hpsi_im_in};
    assign hpsi_re_out = hpsi_re_ext + {kinetic_re[(2*WIDTH)-1], kinetic_re};
    assign hpsi_im_out = hpsi_im_ext + {kinetic_im[(2*WIDTH)-1], kinetic_im};
endmodule
"""

KINETIC_ADD_TESTBENCH = r"""module tb_kinetic_add;
    reg signed [15:0] psi_re, psi_im, hpsi_re_in, hpsi_im_in, g2kin;
    wire signed [32:0] hpsi_re_out, hpsi_im_out;
    kinetic_add dut(.psi_re(psi_re), .psi_im(psi_im), .hpsi_re_in(hpsi_re_in), .hpsi_im_in(hpsi_im_in), .g2kin(g2kin), .hpsi_re_out(hpsi_re_out), .hpsi_im_out(hpsi_im_out));
    initial begin
        psi_re = 16'sd7; psi_im = -16'sd3; hpsi_re_in = 16'sd11; hpsi_im_in = 16'sd5; g2kin = 16'sd4;
        #1;
        if (hpsi_re_out === 33'sd39 && hpsi_im_out === -33'sd7) begin
            $display("KINETIC_ADD_RTL_PASS re=%0d im=%0d", hpsi_re_out, hpsi_im_out);
            $finish(0);
        end else begin
            $display("KINETIC_ADD_RTL_FAIL re=%0d im=%0d", hpsi_re_out, hpsi_im_out);
            $finish(1);
        end
    end
endmodule
"""

VIVADO_SYNTH_TCL = """read_verilog kinetic_add.v
synth_design -top kinetic_add -part xc7a35tcsg324-1
report_utilization -file vivado_utilization.rpt
report_timing_summary -file vivado_timing_summary.rpt
write_checkpoint -force kinetic_add_synth.dcp
opt_design
place_design
route_design
puts "ROUTE_DESIGN COMPLETE"
report_timing_summary -file vivado_route_timing_summary.rpt
report_route_status -file vivado_route_status.rpt
write_checkpoint -force kinetic_add_routed.dcp
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
analyze -format verilog {kinetic_add.v}
elaborate kinetic_add
current_design kinetic_add
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
write -format verilog -hierarchy -output kinetic_add_dc_mapped.v
write -format ddc -hierarchy -output dc_synth.ddc
exit
"""


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_kinetic_add_rtl_sources(out_dir: Path) -> Dict[str, str]:
    """Write RTL/testbench/TCL sources and return run-local file names."""

    out_dir = Path(out_dir)
    files = {
        "rtl": "kinetic_add.v",
        "testbench": "tb_kinetic_add.v",
        "vivado_tcl": "vivado_synth.tcl",
        "dc_tcl": "dc_synth.tcl",
    }
    _write_text(out_dir / files["rtl"], KINETIC_ADD_VERILOG)
    _write_text(out_dir / files["testbench"], KINETIC_ADD_TESTBENCH)
    _write_text(out_dir / files["vivado_tcl"], VIVADO_SYNTH_TCL)
    _write_text(out_dir / files["dc_tcl"], DC_SYNTH_TCL)
    return files


def write_golden_correctness(out_dir: Path) -> Dict[str, Any]:
    """Emit the fixed-point kinetic-add golden correctness artifact."""

    out_dir = Path(out_dir)
    inputs = {
        "psi_re": 7,
        "psi_im": -3,
        "hpsi_re_in": 11,
        "hpsi_im_in": 5,
        "g2kin": 4,
    }
    expected = {
        "re": inputs["hpsi_re_in"] + inputs["psi_re"] * inputs["g2kin"],
        "im": inputs["hpsi_im_in"] + inputs["psi_im"] * inputs["g2kin"],
    }
    payload = {
        "schema_version": "dse.dft.kernel_golden_correctness.v1",
        "kernel_id": KINETIC_ADD_KERNEL_ID,
        "status": "passed" if expected == {"re": 39, "im": -7} else "failed",
        "inputs": inputs,
        "expected": expected,
        "claim_boundary": (
            "Golden fixed-point microkernel correctness for kinetic_add RTL smoke only; "
            "not full-SCF correctness."
        ),
    }
    write_json(out_dir / "golden_correctness.json", payload)
    return payload


def initialize_kinetic_add_rtl_flow(out_dir: Path, *, candidate_id: str | None = None) -> Dict[str, Any]:
    """Create all local source/golden artifacts for a kinetic-add RTL run."""

    out_dir = Path(out_dir)
    source_files = write_kinetic_add_rtl_sources(out_dir)
    golden = write_golden_correctness(out_dir)
    manifest = {
        "schema_version": KINETIC_ADD_FLOW_SCHEMA,
        "kernel_id": KINETIC_ADD_KERNEL_ID,
        "candidate_id": candidate_id,
        "source_files": source_files,
        "golden_correctness": "golden_correctness.json",
        "claim_boundary": (
            "DFT-scoped RTL smoke flow for one fixed-point kinetic_add microkernel. "
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
        "kernel_id": KINETIC_ADD_KERNEL_ID,
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


def build_kinetic_add_evidence_rows(
    out_dir: Path,
    *,
    environment: str = "ssh ic-eda",
) -> Dict[str, Any]:
    """Summarize generated outputs into FPGA-gate rows plus ASIC-attempt rows."""

    out_dir = Path(out_dir)
    vcs_pass = "KINETIC_ADD_RTL_PASS" in _read_text(out_dir / "vcs_run.log")
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
        _artifact_row(
            evidence_type="golden_correctness",
            status="passed" if _load_status(out_dir / "golden_correctness.json") == "passed" else "failed",
            artifact=out_dir / "golden_correctness.json",
            tool="python",
            tool_stage="golden",
            command="compute fixed-point kinetic_add golden output",
            environment="local",
            claim_boundary="Fixed-point kinetic_add scalar golden correctness only; not full-SCF correctness.",
        ),
        _artifact_row(
            evidence_type="rtl_sim",
            status="passed" if vcs_pass else "blocked",
            artifact=out_dir / "vcs_run.log",
            tool="vcs",
            tool_stage="rtl_sim",
            command="vcs -full64 -sverilog kinetic_add.v tb_kinetic_add.v -o simv && ./simv",
            environment=environment,
            claim_boundary="VCS RTL simulation for one kinetic_add microkernel testbench; not full-SCF closure.",
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
            evidence_type="vivado_impl",
            status="passed" if vivado_route_pass else "blocked",
            artifact=out_dir / "vivado_route_status.rpt",
            tool="vivado",
            tool_stage="implementation",
            command="vivado -mode batch -source vivado_synth.tcl",
            environment=environment,
            claim_boundary="Vivado implementation-route completion for this microkernel only; no board measurement or full-SCF claim.",
            failure_evidence=None if vivado_route_pass else "Vivado implementation route completion marker/report missing",
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
            claim_boundary="DC attempt audit for kinetic_add; only a real mapped technology-library run with dc_synth.ddc can support ASIC PPA.",
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
        "schema_version": "dse.dft_scf.kinetic_add_rtl_evidence_rows.v1",
        "kernel_id": KINETIC_ADD_KERNEL_ID,
        "evidence_rows": evidence_rows,
        "asic_attempt_evidence_rows": asic_attempt_rows,
        "fpga_gate_candidate": all(row["status"] == "passed" for row in evidence_rows),
        "asic_gate_candidate": all(row["status"] == "passed" for row in asic_attempt_rows),
        "claim_boundary": (
            "FPGA rows can satisfy the kinetic_add FPGA microkernel gate when all pass. "
            "ASIC rows are separate audit attempts and are not mixed into FPGA claim evidence."
        ),
    }
    write_json(out_dir / "evidence_rows.json", {"evidence_rows": evidence_rows})
    write_json(out_dir / "asic_attempt_evidence.json", {"evidence_rows": asic_attempt_rows})
    write_json(out_dir / "kinetic_add_rtl_evidence_summary.json", payload)
    return payload


def _load_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "invalid"
    return str(payload.get("status", "missing")) if isinstance(payload, Mapping) else "invalid"


def default_kernel_dispositions(*, accelerated_kernel_id: str = KINETIC_ADD_KERNEL_ID) -> list[Dict[str, Any]]:
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


def write_kinetic_add_major_kernel_matrix(
    out_dir: Path,
    *,
    candidate_id: str,
    evidence_rows: Iterable[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Write the eight-kernel matrix for this kinetic-add FPGA smoke candidate."""

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
