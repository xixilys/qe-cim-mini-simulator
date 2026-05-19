#!/usr/bin/env bash
# Build the native QE h_psi L4 payload helper used by the GenericAccel/SystemC sidecar.
# This is a domain-specific payload tool; it must not be folded into the generic simulator core.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
SRC="$SCRIPT_DIR/qe_hpsi_native_kernel.cpp"
OUT_DIR="${1:-$REPO_ROOT/runs/dse/_tools/qe_hpsi_native_kernel}"
CXX_BIN="${CXX:-g++}"
CXXFLAGS_VALUE="${CXXFLAGS:--std=c++17 -O2}"
BIN="$OUT_DIR/qe_hpsi_native_kernel"
SHA_FILE="$OUT_DIR/qe_hpsi_native_kernel.sha256"
MANIFEST="$OUT_DIR/qe_hpsi_native_kernel_build_manifest.json"

mkdir -p "$OUT_DIR"
# shellcheck disable=SC2086 # CXXFLAGS_VALUE is intentionally split into compiler args.
"$CXX_BIN" $CXXFLAGS_VALUE "$SRC" -o "$BIN"
chmod +x "$BIN"
BIN_SHA=$(sha256sum "$BIN" | awk '{print $1}')
SRC_SHA=$(sha256sum "$SRC" | awk '{print $1}')
printf '%s  %s\n' "$BIN_SHA" "$BIN" > "$SHA_FILE"
export SRC SRC_SHA BIN BIN_SHA SHA_FILE MANIFEST CXX_BIN CXXFLAGS_VALUE
python3 - <<PY
import json, os, pathlib, platform, subprocess
manifest = {
    "schema_version": "dse.qe_hpsi_native_kernel_build_manifest.v1",
    "claim_boundary": "Native C++ h_psi payload helper for SystemC/GenericAccel model L4 offload evidence; not silicon/RTL proof.",
    "source": str(pathlib.Path(os.environ["SRC"]).resolve()),
    "source_sha256": os.environ["SRC_SHA"],
    "binary": str(pathlib.Path(os.environ["BIN"]).resolve()),
    "binary_sha256": os.environ["BIN_SHA"],
    "sha256_file": str(pathlib.Path(os.environ["SHA_FILE"]).resolve()),
    "compiler": os.environ["CXX_BIN"],
    "cxxflags": os.environ["CXXFLAGS_VALUE"],
    "platform": platform.platform(),
}
try:
    manifest["compiler_version"] = subprocess.check_output([os.environ["CXX_BIN"], "--version"], text=True, errors="replace").splitlines()[0]
except Exception as exc:
    manifest["compiler_version_error"] = str(exc)
pathlib.Path(os.environ["MANIFEST"]).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "native_hpsi_binary=$BIN"
echo "native_hpsi_binary_sha256=$BIN_SHA"
echo "native_hpsi_source_sha256=$SRC_SHA"
echo "native_hpsi_manifest=$MANIFEST"
