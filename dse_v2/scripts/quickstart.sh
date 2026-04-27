#!/bin/bash

set -e

echo "🚀 DSE v2 Quick Start Guide"
echo "================================"
echo ""

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

cd "$PROJECT_ROOT/dse_v2"

echo "Step 1: Setup environment"
echo "-------------------------"
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    bash scripts/setup/setup_env.sh
else
    echo "✓ Virtual environment already exists"
fi

echo ""
echo "Step 2: Activate environment"
echo "----------------------------"
source venv/bin/activate
echo "✓ Environment activated"

echo ""
echo "Step 3: Analyze existing workloads"
echo "-----------------------------------"
python3 scripts/workload/analyze_existing_workloads.py

echo ""
echo "Step 4: Define design space"
echo "---------------------------"
python3 scripts/setup/define_design_space.py

echo ""
echo "Step 5: Test fast performance model"
echo "------------------------------------"
python3 models/fast/performance_model.py

echo ""
echo "Step 6: Run Bayesian Optimization (50 iterations)"
echo "--------------------------------------------------"
python3 scripts/dse/run_bayesian_dse.py

echo ""
echo "✅ Quick start complete!"
echo ""
echo "Results saved to: results/pareto/bayesian_dse_results_v2.csv"
echo ""
echo "Next steps:"
echo "  - Review Pareto frontier in results/"
echo "  - Add new workloads to workloads/definitions/"
echo "  - Adjust design space in design_space/definitions/"
