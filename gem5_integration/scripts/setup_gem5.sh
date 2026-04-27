#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
GEM5_DIR="$PROJECT_ROOT/gem5"

echo "=== gem5 Setup Script ==="
echo "Project root: $PROJECT_ROOT"
echo "gem5 will be installed to: $GEM5_DIR"

if [ -d "$GEM5_DIR" ]; then
    echo "gem5 directory already exists. Skipping clone."
else
    echo "Cloning gem5 (stable branch)..."
    cd "$PROJECT_ROOT"
    git clone https://github.com/gem5/gem5.git
    cd gem5
    git checkout stable
fi

echo "Checking SystemC installation..."
if [ -z "$SYSTEMC_HOME" ]; then
    echo "WARNING: SYSTEMC_HOME not set. Checking common locations..."
    
    SYSTEMC_PATHS=(
        "/usr/local/systemc-2.3.3"
        "/opt/systemc"
        "/usr/local/systemc"
        "$HOME/systemc"
    )
    
    for path in "${SYSTEMC_PATHS[@]}"; do
        if [ -d "$path" ]; then
            export SYSTEMC_HOME="$path"
            echo "Found SystemC at: $SYSTEMC_HOME"
            break
        fi
    done
    
    if [ -z "$SYSTEMC_HOME" ]; then
        echo "ERROR: SystemC not found. Please install SystemC 2.3.3+ and set SYSTEMC_HOME"
        exit 1
    fi
fi

echo "SystemC location: $SYSTEMC_HOME"

echo "Copying FPGA device to gem5 source tree..."
mkdir -p "$GEM5_DIR/src/dev/fpga"
cp "$PROJECT_ROOT/src/dev/fpga/"* "$GEM5_DIR/src/dev/fpga/"

echo "Creating debug flags..."
cat > "$GEM5_DIR/src/dev/fpga/FPGADebug.py" << 'EOF'
from m5.params import *
from m5.SimObject import SimObject

class FPGADebug(SimObject):
    type = 'FPGADebug'
    cxx_header = "dev/fpga/fpga_accelerator.hh"
EOF

echo "Verifying FPGA SConscript registration..."
if ! grep -q "DebugFlag('FPGAAccelerator'" "$GEM5_DIR/src/dev/fpga/SConscript" 2>/dev/null; then
    echo "ERROR: FPGA SConscript is missing FPGAAccelerator debug flag registration"
    exit 1
fi
if ! grep -q "SimObject('FPGAAccelerator.py'" "$GEM5_DIR/src/dev/fpga/SConscript" 2>/dev/null; then
    echo "ERROR: FPGA SConscript is missing FPGAAccelerator SimObject registration"
    exit 1
fi

echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Build gem5 with SystemC support:"
echo "   cd $GEM5_DIR"
echo "   scons build/X86/gem5.opt USE_SYSTEMC=1 -j\$(nproc)"
echo ""
echo "2. Run FPGA test:"
echo "   build/X86/gem5.opt $PROJECT_ROOT/configs/fpga/simple_fpga_test.py"
