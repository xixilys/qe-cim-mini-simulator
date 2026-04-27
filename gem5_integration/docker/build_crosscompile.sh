#!/bin/bash
# Build script for cross-compiling FPGA test programs

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Docker image name
IMAGE_NAME="gem5-fpga-crosscompile"

# Build Docker image if not exists
echo "Building Docker image..."
docker build -f "${SCRIPT_DIR}/Dockerfile.crosscompile" -t "${IMAGE_NAME}" "${SCRIPT_DIR}"

# Create output directory
mkdir -p "${PROJECT_ROOT}/minimal_rootfs/rootfs/bin"

echo "Cross-compiling test programs..."

# Compile test_dma_transfer.c
docker run --rm \
    -v "${PROJECT_ROOT}:/workspace" \
    -w /workspace \
    "${IMAGE_NAME}" \
    x86_64-linux-musl-gcc -static -O2 \
    -o minimal_rootfs/rootfs/bin/test_dma_transfer \
    qe_test_program/test_dma_transfer.c

echo "Compiled: test_dma_transfer"

# Compile init_pci.c
docker run --rm \
    -v "${PROJECT_ROOT}:/workspace" \
    -w /workspace \
    "${IMAGE_NAME}" \
    x86_64-linux-musl-gcc -static -O2 \
    -o minimal_rootfs/init_pci \
    minimal_rootfs/init_pci.c

echo "Compiled: init_pci"

# Verify binaries
echo ""
echo "Verifying compiled binaries:"
file "${PROJECT_ROOT}/minimal_rootfs/rootfs/bin/test_dma_transfer"
file "${PROJECT_ROOT}/minimal_rootfs/init_pci"

echo ""
echo "Build complete!"
