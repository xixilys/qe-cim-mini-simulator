#!/bin/bash

set -e

echo "🚀 Generic DSE / TLM / SystemC quick start"
echo "=========================================="

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
cd "$PROJECT_ROOT"

echo "Step 1: Validate Python modules"
python3 -m compileall -q dse_v2

echo "Step 2: Run focused generic workflow tests"
python3 -m pytest -q \
  dse_v2/tests/test_workload_importer_registry.py \
  dse_v2/tests/test_generic_workload_ir.py \
  dse_v2/tests/test_step2_architecture_mapping_workflow.py \
  dse_v2/tests/test_step3_cross_step_workflow.py

echo "Step 3: Run a generic sparse workload pilot"
python3 dse_v2/scripts/dse/run_full_flow_pilot.py \
  --profile sparse_la \
  --importer generic_json \
  --generator sparse_spmv \
  --backend systemc \
  --out runs/dse/generic_systemc_pilot \
  --timeout 60

echo "✅ Quick start complete. Active output: runs/dse/generic_systemc_pilot"
echo "Legacy application-specific files are not part of the active tree."
