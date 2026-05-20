#!/usr/bin/env python3
"""DFT-scoped nonlocal-projector RTL probe flow helpers.

This module intentionally lives under the DFT reference workload surface, not
in the generic DSE core. It writes a minimal deterministic fixed-point
``nonlocal_projector`` RTL smoke kernel plus testbench/TCL scripts and
normalizes real VCS/Vivado/DC attempt artifacts into the evidence rows consumed
by the DFT hardware claim gates.
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


NONLOCAL_PROJECTOR_KERNEL_ID = "nonlocal_projector"
NONLOCAL_PROJECTOR_FLOW_SCHEMA = "dse.dft_scf.nonlocal_projector_rtl_flow.v1"

NONLOCAL_PROJECTOR_VERILOG = r"""module nonlocal_projector #(
    parameter WIDTH = 16
) (
    input  signed [WIDTH-1:0] beta0,
    input  signed [WIDTH-1:0] beta1,
    input  signed [WIDTH-1:0] beta2,
    input  signed [WIDTH-1:0] beta3,
    input  signed [WIDTH-1:0] psi0,
    input  signed [WIDTH-1:0] psi1,
    input  signed [WIDTH-1:0] psi2,
    input  signed [WIDTH-1:0] psi3,
    output signed [(2*WIDTH)+1:0] coeff,
    output signed [(3*WIDTH)+1:0] out0,
    output signed [(3*WIDTH)+1:0] out1,
    output signed [(3*WIDTH)+1:0] out2,
    output signed [(3*WIDTH)+1:0] out3
);
    wire signed [(2*WIDTH)-1:0] p0 = beta0 * psi0;
    wire signed [(2*WIDTH)-1:0] p1 = beta1 * psi1;
    wire signed [(2*WIDTH)-1:0] p2 = beta2 * psi2;
    wire signed [(2*WIDTH)-1:0] p3 = beta3 * psi3;
    wire signed [(2*WIDTH):0] sum01 = {p0[(2*WIDTH)-1], p0} + {p1[(2*WIDTH)-1], p1};
    wire signed [(2*WIDTH):0] sum23 = {p2[(2*WIDTH)-1], p2} + {p3[(2*WIDTH)-1], p3};
    assign coeff = {sum01[(2*WIDTH)], sum01} + {sum23[(2*WIDTH)], sum23};

    assign out0 = beta0 * coeff;
    assign out1 = beta1 * coeff;
    assign out2 = beta2 * coeff;
    assign out3 = beta3 * coeff;
endmodule
"""

NONLOCAL_PROJECTOR_TESTBENCH = r"""module tb_nonlocal_projector;
    reg signed [15:0] beta0, beta1, beta2, beta3, psi0, psi1, psi2, psi3;
    wire signed [33:0] coeff;
    wire signed [49:0] out0, out1, out2, out3;
    nonlocal_projector dut(
        .beta0(beta0), .beta1(beta1), .beta2(beta2), .beta3(beta3),
        .psi0(psi0), .psi1(psi1), .psi2(psi2), .psi3(psi3),
        .coeff(coeff), .out0(out0), .out1(out1), .out2(out2), .out3(out3)
    );
    initial begin
        beta0 = 16'sd2; beta1 = -16'sd1; beta2 = 16'sd3; beta3 = 16'sd4;
        psi0 = 16'sd5;  psi1 = -16'sd6; psi2 = 16'sd7;  psi3 = 16'sd1;
        #1;
        if (coeff === 34'sd41 && out0 === 50'sd82 && out1 === -50'sd41 && out2 === 50'sd123 && out3 === 50'sd164) begin
            $display("NONLOCAL_PROJECTOR_RTL_PASS coeff=%0d out0=%0d out1=%0d out2=%0d out3=%0d", coeff, out0, out1, out2, out3);
            $finish(0);
        end else begin
            $display("NONLOCAL_PROJECTOR_RTL_FAIL coeff=%0d out0=%0d out1=%0d out2=%0d out3=%0d", coeff, out0, out1, out2, out3);
            $finish(1);
        end
    end
endmodule
"""

VIVADO_SYNTH_TCL = """read_verilog nonlocal_projector.v
synth_design -top nonlocal_projector -part xc7a35tcsg324-1
report_utilization -file vivado_utilization.rpt
report_timing_summary -file vivado_timing_summary.rpt
write_checkpoint -force nonlocal_projector_synth.dcp
opt_design
place_design
route_design
puts "ROUTE_DESIGN COMPLETE"
report_timing_summary -file vivado_route_timing_summary.rpt
report_route_status -file vivado_route_status.rpt
write_checkpoint -force nonlocal_projector_routed.dcp
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
analyze -format verilog {nonlocal_projector.v}
elaborate nonlocal_projector
current_design nonlocal_projector
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
write -format verilog -hierarchy -output nonlocal_projector_dc_mapped.v
write -format ddc -hierarchy -output dc_synth.ddc
exit
"""


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_nonlocal_projector_rtl_sources(out_dir: Path) -> Dict[str, str]:
    """Write RTL/testbench/TCL sources and return run-local file names."""

    out_dir = Path(out_dir)
    files = {
        "rtl": "nonlocal_projector.v",
        "testbench": "tb_nonlocal_projector.v",
        "vivado_tcl": "vivado_synth.tcl",
        "dc_tcl": "dc_synth.tcl",
    }
    _write_text(out_dir / files["rtl"], NONLOCAL_PROJECTOR_VERILOG)
    _write_text(out_dir / files["testbench"], NONLOCAL_PROJECTOR_TESTBENCH)
    _write_text(out_dir / files["vivado_tcl"], VIVADO_SYNTH_TCL)
    _write_text(out_dir / files["dc_tcl"], DC_SYNTH_TCL)
    return files


def write_golden_correctness(out_dir: Path) -> Dict[str, Any]:
    """Emit deterministic nonlocal-projector golden correctness data."""

    out_dir = Path(out_dir)
    inputs = {
        "beta": [2, -1, 3, 4],
        "psi": [5, -6, 7, 1],
    }
    coeff = sum(beta_i * psi_i for beta_i, psi_i in zip(inputs["beta"], inputs["psi"]))
    expected = {
        "coeff": coeff,
        "out": [beta_i * coeff for beta_i in inputs["beta"]],
    }
    payload = {
        "schema_version": "dse.dft.kernel_golden_correctness.v1",
        "kernel_id": NONLOCAL_PROJECTOR_KERNEL_ID,
        "status": "passed" if expected == {"coeff": 41, "out": [82, -41, 123, 164]} else "failed",
        "inputs": inputs,
        "expected": expected,
        "semantics": "coeff=sum(beta_i*psi_i); out_i=beta_i*coeff for four deterministic lanes",
        "claim_boundary": (
            "Golden fixed-point nonlocal_projector beta-projection/application correctness only; "
            "not full-SCF correctness and not evidence for any other kernel_id."
        ),
    }
    write_json(out_dir / "golden_correctness.json", payload)
    return payload


def initialize_nonlocal_projector_rtl_flow(out_dir: Path, *, candidate_id: str | None = None) -> Dict[str, Any]:
    """Create all local source/golden artifacts for a nonlocal-projector RTL run."""

    out_dir = Path(out_dir)
    source_files = write_nonlocal_projector_rtl_sources(out_dir)
    golden = write_golden_correctness(out_dir)
    manifest = {
        "schema_version": NONLOCAL_PROJECTOR_FLOW_SCHEMA,
        "kernel_id": NONLOCAL_PROJECTOR_KERNEL_ID,
        "candidate_id": candidate_id,
        "source_files": source_files,
        "golden_correctness": "golden_correctness.json",
        "semantics": ["beta_projection_coeff", "projector_apply"],
        "claim_boundary": (
            "DFT-scoped RTL smoke flow for one fixed-point nonlocal_projector microkernel. "
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
        "kernel_id": NONLOCAL_PROJECTOR_KERNEL_ID,
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


def build_nonlocal_projector_evidence_rows(
    out_dir: Path,
    *,
    environment: str = "ssh ic-eda",
) -> Dict[str, Any]:
    """Summarize generated outputs into FPGA-gate rows plus ASIC-attempt rows."""

    out_dir = Path(out_dir)
    vcs_pass = "NONLOCAL_PROJECTOR_RTL_PASS" in _read_text(out_dir / "vcs_run.log")
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
            command="compute fixed-point nonlocal_projector beta projection and application golden output",
            environment="local",
            claim_boundary="Fixed-point nonlocal_projector beta projection/application correctness only; not full-SCF correctness.",
        ),
        _artifact_row(
            evidence_type="rtl_sim",
            status="passed" if vcs_pass else "blocked",
            artifact=out_dir / "vcs_run.log",
            tool="vcs",
            tool_stage="rtl_sim",
            command="vcs -full64 -sverilog nonlocal_projector.v tb_nonlocal_projector.v -o simv && ./simv",
            environment=environment,
            claim_boundary="VCS RTL simulation for one nonlocal_projector microkernel testbench; not full-SCF closure.",
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
            claim_boundary="DC attempt audit for nonlocal_projector; only a real mapped technology-library run with dc_synth.ddc can support ASIC PPA.",
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
        "schema_version": "dse.dft_scf.nonlocal_projector_rtl_evidence_rows.v1",
        "kernel_id": NONLOCAL_PROJECTOR_KERNEL_ID,
        "evidence_rows": evidence_rows,
        "asic_attempt_evidence_rows": asic_attempt_rows,
        "fpga_gate_candidate": all(row["status"] == "passed" for row in evidence_rows),
        "asic_gate_candidate": all(row["status"] == "passed" for row in asic_attempt_rows),
        "claim_boundary": (
            "FPGA rows can satisfy the nonlocal_projector FPGA microkernel gate when all pass. "
            "ASIC rows are separate audit attempts and are not mixed into FPGA claim evidence."
        ),
    }
    write_json(out_dir / "evidence_rows.json", {"evidence_rows": evidence_rows})
    write_json(out_dir / "asic_attempt_evidence.json", {"evidence_rows": asic_attempt_rows})
    write_json(out_dir / "nonlocal_projector_rtl_evidence_summary.json", payload)
    return payload


def _load_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "invalid"
    return str(payload.get("status", "missing")) if isinstance(payload, Mapping) else "invalid"


def default_kernel_dispositions(*, accelerated_kernel_id: str = NONLOCAL_PROJECTOR_KERNEL_ID) -> list[Dict[str, Any]]:
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


def write_nonlocal_projector_major_kernel_matrix(
    out_dir: Path,
    *,
    candidate_id: str,
    evidence_rows: Iterable[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Write the eight-kernel matrix for this nonlocal-projector FPGA smoke candidate."""

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
