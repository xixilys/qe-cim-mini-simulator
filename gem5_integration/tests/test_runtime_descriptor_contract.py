"""Contract checks for GenericAccel's extended GSIM runtime descriptor."""

from __future__ import annotations

import subprocess
from pathlib import Path

from dse_v2.backends.gem5_systemc_adapter import (
    GENERIC_ACCEL_COMMAND_DESCRIPTOR_BYTES,
    GENERIC_ACCEL_LEGACY_COMMAND_DESCRIPTOR_BYTES,
    build_generic_accel_command_descriptor,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
HEADER = REPO_ROOT / "runtime_api" / "command_descriptor.h"
DRIVER = REPO_ROOT / "gem5_integration" / "test_programs" / "generic_accel" / "generic_accel_l4_driver.c"
FAST_DRIVER = REPO_ROOT / "gem5_integration" / "test_programs" / "generic_accel" / "generic_accel_l4_driver_fast.c"
DEVICE_CC = REPO_ROOT / "gem5_integration" / "src" / "dev" / "generic_accel" / "generic_accel.cc"
GEM5_DEVICE_CC = REPO_ROOT / "gem5_integration" / "gem5" / "src" / "dev" / "generic_accel" / "generic_accel.cc"
PROTOCOL = REPO_ROOT / "gem5_integration" / "src" / "dev" / "generic_accel" / "generic_mmio_protocol.md"


def test_gsim_descriptor_keeps_legacy_prefix_and_generic_extensions(tmp_path: Path) -> None:
    probe = tmp_path / "probe.c"
    probe.write_text(
        """
#include <stddef.h>
#include "runtime_api/command_descriptor.h"
int main(void) {
    if (OFFLOAD_GSIM_LEGACY_COMMAND_DESCRIPTOR_BYTES != 48u) return 1;
    if (offsetof(offload_gsim_command_descriptor, extension_payload_addr) != 48u) return 2;
    if (offsetof(offload_gsim_command_descriptor, candidate_identity_addr) <= 48u) return 3;
    if (offsetof(offload_gsim_command_descriptor, compile_schedule_addr) <= 48u) return 4;
    if (offsetof(offload_gsim_command_descriptor, runtime_schedule_addr) <= 48u) return 5;
    if (offsetof(offload_gsim_command_descriptor, sidecar_dispatch_addr) <= 48u) return 6;
    if (OFFLOAD_GSIM_DESCRIPTOR_FLAG_EXTENSION_PAYLOAD != (1u << 3)) return 7;
    if (OFFLOAD_GSIM_DESCRIPTOR_FLAG_CANDIDATE_IDENTITY != (1u << 4)) return 8;
    if (OFFLOAD_GSIM_DESCRIPTOR_FLAG_COMPILE_SCHEDULE != (1u << 5)) return 9;
    if (OFFLOAD_GSIM_DESCRIPTOR_FLAG_RUNTIME_SCHEDULE != (1u << 6)) return 10;
    if (OFFLOAD_GSIM_DESCRIPTOR_FLAG_SIDECAR_DISPATCH != (1u << 7)) return 11;
    return 0;
}
""",
        encoding="utf-8",
    )
    binary = tmp_path / "probe"
    subprocess.run(
        ["gcc", "-std=c99", "-Wall", "-Wextra", "-I", str(REPO_ROOT), str(probe), "-o", str(binary)],
        check=True,
        cwd=REPO_ROOT,
    )
    subprocess.run([str(binary)], check=True)


def test_l4_driver_builds_against_shared_runtime_descriptor(tmp_path: Path) -> None:
    subprocess.run(
        ["gcc", "-std=c99", "-Wall", "-Wextra", "-I", str(REPO_ROOT), "-c", str(DRIVER), "-o", str(tmp_path / "driver.o")],
        check=True,
        cwd=REPO_ROOT,
    )
    source = DRIVER.read_text(encoding="utf-8")
    assert "OFFLOAD_GSIM_DESCRIPTOR_FLAG_EXTENSION_PAYLOAD" in source


def test_l4_driver_does_not_clear_large_workspace_on_critical_path() -> None:
    source = DRIVER.read_text(encoding="utf-8")

    assert "memset((void *)WORK_BASE, 0, WORK_BYTES)" not in source
    assert "memset((void *)result, 0, RESULT_BYTES)" not in source
    assert "result[0] = '\\0';" in source


def test_fast_l4_driver_builds_without_libc_startup(tmp_path: Path) -> None:
    binary = tmp_path / "generic_accel_l4_driver_fast"
    regular_binary = tmp_path / "generic_accel_l4_driver"
    subprocess.run(
        [
            "gcc",
            "-std=c99",
            "-O2",
            "-Wall",
            "-Wextra",
            "-fno-builtin",
            "-fno-stack-protector",
            "-fno-asynchronous-unwind-tables",
            "-fno-unwind-tables",
            "-nostdlib",
            "-static",
            "-I",
            str(REPO_ROOT),
            str(FAST_DRIVER),
            "-o",
            str(binary),
        ],
        check=True,
        cwd=REPO_ROOT,
    )
    subprocess.run(
        [
            "gcc",
            "-std=c99",
            "-O2",
            "-Wall",
            "-Wextra",
            "-static",
            "-I",
            str(REPO_ROOT),
            str(DRIVER),
            "-o",
            str(regular_binary),
        ],
        check=True,
        cwd=REPO_ROOT,
    )
    source = FAST_DRIVER.read_text(encoding="utf-8")
    assert "void _start(void)" in source
    assert "SYS_OPENAT" in source
    assert binary.stat().st_size < regular_binary.stat().st_size


def test_python_descriptor_translation_records_extended_generic_lanes() -> None:
    translation = build_generic_accel_command_descriptor(
        {
            "schema_version": "test",
            "run_id": "run",
            "mode": "gem5_cosim",
            "extension_payload": {"adapter_metadata": {"source_kind": "fixture"}},
        }
    )
    descriptor = translation["descriptor"]
    assert translation["legacy_prefix_bytes"] == GENERIC_ACCEL_LEGACY_COMMAND_DESCRIPTOR_BYTES == 48
    assert translation["descriptor_size_bytes"] == GENERIC_ACCEL_COMMAND_DESCRIPTOR_BYTES == 128
    assert descriptor["flags"] == 0xFF
    assert descriptor["extension_payload_addr"] == descriptor["request_addr"]
    assert "extension_payload_bytes_estimate" in descriptor


def test_generic_accel_logs_identity_schedule_sidecar_and_extension_markers() -> None:
    source = DEVICE_CC.read_text(encoding="utf-8")
    for marker in [
        "candidate_identity_trace",
        "compile_schedule_trace",
        "runtime_schedule_trace",
        "sidecar_dispatch_trace",
        "extension_payload_trace",
        "extension_payload_present",
        "claim_scope",
        "vertical_slice_only",
    ]:
        assert marker in source


def test_generic_accel_surfaces_do_not_parse_or_emit_workload_specific_evidence() -> None:
    forbidden_markers = ("qe_", "quantum espresso", "h_psi", "pw.x")
    offenders: list[str] = []
    paths = [DEVICE_CC, DRIVER, PROTOCOL]
    if GEM5_DEVICE_CC.exists():
        paths.append(GEM5_DEVICE_CC)
    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        for marker in forbidden_markers:
            if marker in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)} contains {marker!r}")

    assert offenders == []



def test_adapter_prefers_uarch_result_path_over_sidecar_result_path() -> None:
    from dse_v2.backends.gem5_systemc_adapter import _extract_token

    gem5_log = "\n".join([
        "100: system.generic_accel: systemc_submit verified=true executable=/tmp/generic_sim request_path=/tmp/sidecar.request.json result_path=/tmp/sidecar.result.json return_code=0 result_bytes=123",
        "200: system.generic_accel: uarch_request_decode verified=true engine=gem5_generic_accel_microarchitecture_v1 request_bytes=456 micro_ops=7 result_bytes=789 result_path=/tmp/uarch.result.json result_file_written=true total_cycles=42 total_payload_bytes=0",
    ])

    assert _extract_token(r"uarch_request_decode verified=true.*result_path=(\S+)", gem5_log) == "/tmp/uarch.result.json"
    assert _extract_token(r"systemc_submit verified=true.*result_path=(\S+)", gem5_log) == "/tmp/sidecar.result.json"


def test_adapter_makes_sidecar_artifact_paths_durable_and_not_aliased_to_uarch() -> None:
    adapter_source = (REPO_ROOT / "dse_v2" / "backends" / "gem5_systemc_adapter.py").read_text(encoding="utf-8")
    assert "systemc_sidecar_request.raw.json" in adapter_source
    assert "systemc_sidecar_result.raw.json" in adapter_source
    assert '"systemc_submit_verified": systemc_submit_verified' in adapter_source
    assert "legacy_systemc_or_microarchitecture_verified" in adapter_source


def test_protocol_documents_extended_markers_as_non_completion_evidence() -> None:
    protocol = PROTOCOL.read_text(encoding="utf-8")
    assert "CANDIDATE_IDENTITY" in protocol
    assert "COMPILE_SCHEDULE" in protocol
    assert "RUNTIME_SCHEDULE" in protocol
    assert "SIDECAR_DISPATCH" in protocol
    assert "vertical_slice_only" in protocol
    assert "not by themselves prove numerical correctness" in protocol


def test_runtime_header_does_not_make_qe_fields_part_of_c_abi() -> None:
    header = HEADER.read_text(encoding="utf-8")
    struct_body = header.split("typedef struct offload_gsim_command_descriptor", 1)[1].split("} offload_gsim_command_descriptor", 1)[0]
    assert "qe" not in struct_body.lower()
    assert "extension_payload" in struct_body
