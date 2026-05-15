"""Contract checks for GenericAccel's extended GSIM runtime descriptor."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HEADER = REPO_ROOT / "runtime_api" / "command_descriptor.h"
DRIVER = REPO_ROOT / "gem5_integration" / "test_programs" / "generic_accel" / "generic_accel_l4_driver.c"
DEVICE_CC = REPO_ROOT / "gem5_integration" / "src" / "dev" / "generic_accel" / "generic_accel.cc"
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
    if (OFFLOAD_GSIM_DESCRIPTOR_FLAG_CANDIDATE_IDENTITY != (1u << 4)) return 7;
    if (OFFLOAD_GSIM_DESCRIPTOR_FLAG_COMPILE_SCHEDULE != (1u << 5)) return 8;
    if (OFFLOAD_GSIM_DESCRIPTOR_FLAG_RUNTIME_SCHEDULE != (1u << 6)) return 9;
    if (OFFLOAD_GSIM_DESCRIPTOR_FLAG_SIDECAR_DISPATCH != (1u << 7)) return 10;
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


def test_generic_accel_logs_identity_schedule_sidecar_and_qe_extension_markers() -> None:
    source = DEVICE_CC.read_text(encoding="utf-8")
    for marker in [
        "candidate_identity_trace",
        "compile_schedule_trace",
        "runtime_schedule_trace",
        "sidecar_dispatch_trace",
        "extension_payload_trace",
        "claim_scope",
        "vertical_slice_only",
    ]:
        assert marker in source


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
