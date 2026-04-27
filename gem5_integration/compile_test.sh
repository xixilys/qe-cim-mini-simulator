#!/bin/bash
set -e

echo "Cross-compiling QE FPGA test program for x86_64..."

docker run --rm \
  -v "$(pwd)/qe_test_program:/build" \
  gem5-cross-compile \
  x86_64-linux-gnu-gcc -static -o /build/fpga_test /build/fpga_test.c

echo "Compilation successful!"
ls -lh qe_test_program/fpga_test
file qe_test_program/fpga_test
