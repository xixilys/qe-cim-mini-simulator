#!/usr/bin/env python3
"""DFT-scoped Hψ local-potential RTL probe flow helpers."""

from __future__ import annotations

import json
import re
import tarfile
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS, build_major_kernel_evidence_matrix


HPSI_LOCAL_KERNEL_ID = "hpsi_local_potential"
HPSI_LOCAL_FLOW_SCHEMA = "dse.dft_scf.hpsi_local_potential_rtl_flow.v1"

HPSI_LOCAL_VERILOG = r"""module hpsi_local_potential #(
    parameter WIDTH = 16
) (
    input  signed [WIDTH-1:0] psi0,
    input  signed [WIDTH-1:0] psi1,
    input  signed [WIDTH-1:0] psi2,
    input  signed [WIDTH-1:0] psi3,
    input  signed [WIDTH-1:0] v0,
    input  signed [WIDTH-1:0] v1,
    input  signed [WIDTH-1:0] v2,
    input  signed [WIDTH-1:0] v3,
    output signed [(2*WIDTH)-1:0] hpsi0,
    output signed [(2*WIDTH)-1:0] hpsi1,
    output signed [(2*WIDTH)-1:0] hpsi2,
    output signed [(2*WIDTH)-1:0] hpsi3
);
    assign hpsi0 = psi0 * v0;
    assign hpsi1 = psi1 * v1;
    assign hpsi2 = psi2 * v2;
    assign hpsi3 = psi3 * v3;
endmodule
"""

HPSI_LOCAL_TESTBENCH = r"""module tb_hpsi_local_potential;
    reg signed [15:0] psi0, psi1, psi2, psi3, v0, v1, v2, v3;
    wire signed [31:0] hpsi0, hpsi1, hpsi2, hpsi3;
    hpsi_local_potential dut(
        .psi0(psi0), .psi1(psi1), .psi2(psi2), .psi3(psi3),
        .v0(v0), .v1(v1), .v2(v2), .v3(v3),
        .hpsi0(hpsi0), .hpsi1(hpsi1), .hpsi2(hpsi2), .hpsi3(hpsi3)
    );
    initial begin
        psi0 = 16'sd2;  psi1 = -16'sd3; psi2 = 16'sd4;  psi3 = -16'sd5;
        v0   = 16'sd7;  v1   = 16'sd11; v2   = -16'sd2; v3   = 16'sd3;
        #1;
        if (hpsi0 === 32'sd14 && hpsi1 === -32'sd33 && hpsi2 === -32'sd8 && hpsi3 === -32'sd15) begin
            $display("HPSI_LOCAL_RTL_PASS hpsi=%0d,%0d,%0d,%0d", hpsi0, hpsi1, hpsi2, hpsi3);
            $finish(0);
        end else begin
            $display("HPSI_LOCAL_RTL_FAIL hpsi=%0d,%0d,%0d,%0d", hpsi0, hpsi1, hpsi2, hpsi3);
            $finish(1);
        end
    end
endmodule
"""

VIVADO_SYNTH_TCL = """read_verilog hpsi_local_potential.v
synth_design -top hpsi_local_potential -part xc7a35tcsg324-1
report_utilization -file vivado_utilization.rpt
report_timing_summary -file vivado_timing_summary.rpt
write_checkpoint -force hpsi_local_potential_synth.dcp
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
analyze -format verilog {hpsi_local_potential.v}
elaborate hpsi_local_potential
current_design hpsi_local_potential
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
write -format verilog -hierarchy -output hpsi_local_potential_dc_mapped.v
write -format ddc -hierarchy -output dc_synth.ddc
exit
"""


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_hpsi_local_rtl_sources(out_dir: Path) -> Dict[str, str]:
    out_dir = Path(out_dir)
    files = {"rtl": "hpsi_local_potential.v", "testbench": "tb_hpsi_local_potential.v", "vivado_tcl": "vivado_synth.tcl", "dc_tcl": "dc_synth.tcl"}
    _write_text(out_dir / files["rtl"], HPSI_LOCAL_VERILOG)
    _write_text(out_dir / files["testbench"], HPSI_LOCAL_TESTBENCH)
    _write_text(out_dir / files["vivado_tcl"], VIVADO_SYNTH_TCL)
    _write_text(out_dir / files["dc_tcl"], DC_SYNTH_TCL)
    return files


def write_golden_correctness(out_dir: Path) -> Dict[str, Any]:
    inputs = {"psi": [2, -3, 4, -5], "local_potential": [7, 11, -2, 3]}
    expected = {"hpsi_local": [p * v for p, v in zip(inputs["psi"], inputs["local_potential"])]}
    payload = {
        "schema_version": "dse.dft.kernel_golden_correctness.v1",
        "kernel_id": HPSI_LOCAL_KERNEL_ID,
        "status": "passed" if expected["hpsi_local"] == [14, -33, -8, -15] else "failed",
        "inputs": inputs,
        "expected": expected,
        "claim_boundary": "Golden fixed-point Hpsi local-potential multiply semantics only; not full-SCF correctness and not evidence for any other kernel_id.",
    }
    write_json(Path(out_dir) / "golden_correctness.json", payload)
    return payload


def initialize_hpsi_local_rtl_flow(out_dir: Path, *, candidate_id: str | None = None) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    source_files = write_hpsi_local_rtl_sources(out_dir)
    golden = write_golden_correctness(out_dir)
    manifest = {
        "schema_version": HPSI_LOCAL_FLOW_SCHEMA,
        "kernel_id": HPSI_LOCAL_KERNEL_ID,
        "candidate_id": candidate_id,
        "source_files": source_files,
        "golden_correctness": "golden_correctness.json",
        "claim_boundary": "DFT-scoped RTL smoke flow for one Hpsi local-potential microkernel; not full-SCF/all-kernel closure.",
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
    row: Dict[str, Any] = {"kernel_id": HPSI_LOCAL_KERNEL_ID, "evidence_type": evidence_type, "status": status, "artifact": str(artifact), "tool": tool, "tool_stage": tool_stage, "command": command, "environment": environment, "claim_boundary": claim_boundary}
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


def build_hpsi_local_evidence_rows(out_dir: Path, *, environment: str = "ssh ic-eda") -> Dict[str, Any]:
    out_dir = Path(out_dir)
    vcs_pass = "HPSI_LOCAL_RTL_PASS" in _read_text(out_dir / "vcs_run.log")
    vivado_pass = (out_dir / "vivado_utilization.rpt").exists() and "synth_design completed successfully" in _read_text(out_dir / "vivado_stdout.log")
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
        _artifact_row(evidence_type="golden_correctness", status="passed" if _load_status(out_dir / "golden_correctness.json") == "passed" else "failed", artifact=out_dir / "golden_correctness.json", tool="python", tool_stage="golden", command="compute Hpsi local-potential fixed-point golden outputs", environment="local", claim_boundary="Hpsi local-potential fixed-point correctness only; not full-SCF correctness."),
        _artifact_row(evidence_type="rtl_sim", status="passed" if vcs_pass else "blocked", artifact=out_dir / "vcs_run.log", tool="vcs", tool_stage="rtl_sim", command="vcs -full64 -sverilog hpsi_local_potential.v tb_hpsi_local_potential.v -o simv && ./simv", environment=environment, claim_boundary="VCS RTL simulation for one hpsi_local_potential microkernel testbench; not full-SCF closure.", failure_evidence=None if vcs_pass else "VCS pass marker not found in vcs_run.log"),
        _artifact_row(evidence_type="rtl_synth", status="passed" if vivado_pass else "blocked", artifact=out_dir / "vivado_stdout.log", tool="vivado", tool_stage="synthesis", command="vivado -mode batch -source vivado_synth.tcl", environment=environment, claim_boundary="Vivado synth_design proves FPGA RTL synthesis for this microkernel only.", failure_evidence=None if vivado_pass else "Vivado synthesis report/pass marker missing"),
        _artifact_row(evidence_type="vivado_synth", status="passed" if vivado_pass else "blocked", artifact=out_dir / "vivado_utilization.rpt", tool="vivado", tool_stage="synth", command="vivado -mode batch -source vivado_synth.tcl", environment=environment, claim_boundary="Vivado synthesis/utilization for this microkernel only; no board measurement or full-SCF claim.", failure_evidence=None if vivado_pass else "vivado_utilization.rpt missing or synth_design did not complete"),
    ]
    asic_attempt_rows = [_artifact_row(evidence_type="dc_synth_timing_area", status="blocked" if dc_blocked else "passed", artifact=out_dir / "dc_stdout.log", tool="dc_shell", tool_stage="synth_timing_area", command="dc_shell -f dc_synth.tcl", environment=environment, claim_boundary="DC attempt audit for hpsi_local_potential; only a real mapped technology-library run with dc_synth.ddc can support ASIC PPA.", failure_evidence=("DC output missing, dc_synth.ddc missing, target library unavailable/not observed, zero/empty timing/area, or gtech/unmapped/unconstrained output; not ASIC PPA evidence" if dc_blocked else None))]
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
    payload = {"schema_version": "dse.dft_scf.hpsi_local_potential_rtl_evidence_rows.v1", "kernel_id": HPSI_LOCAL_KERNEL_ID, "evidence_rows": evidence_rows, "asic_attempt_evidence_rows": asic_attempt_rows, "fpga_gate_candidate": all(row["status"] == "passed" for row in evidence_rows), "asic_gate_candidate": all(row["status"] == "passed" for row in asic_attempt_rows), "claim_boundary": "FPGA rows can satisfy the hpsi_local_potential FPGA microkernel gate when all pass. ASIC rows are separate audit attempts and are not mixed into FPGA claim evidence."}
    write_json(out_dir / "evidence_rows.json", {"evidence_rows": evidence_rows})
    write_json(out_dir / "asic_attempt_evidence.json", {"evidence_rows": asic_attempt_rows})
    write_json(out_dir / "hpsi_local_potential_rtl_evidence_summary.json", payload)
    return payload


def default_kernel_dispositions(*, accelerated_kernel_id: str = HPSI_LOCAL_KERNEL_ID) -> list[Dict[str, Any]]:
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


def write_hpsi_local_major_kernel_matrix(out_dir: Path, *, candidate_id: str, evidence_rows: Iterable[Mapping[str, Any]] | None = None) -> Dict[str, Any]:
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
