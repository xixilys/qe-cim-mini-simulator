#!/bin/bash
# Quick Start DSE + Simulator 测试脚本
# 用法: ./quick_start_dse.sh

set -e

PROJECT_ROOT="/Volumes/remote/phd/year_2/project/dft加速"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "Step 1: 验证 Component Catalog 和 Graph"
echo "=========================================="
python3 tools/benchmarks/check_qe_ic_component_graph_v1.py \
  --component-catalog docs/architecture/qe_ic_component_catalog_system_level_v1.json \
  --graph-seed docs/architecture/qe_ic_graph_seed_system_level_v1.json \
  --print-projection

echo ""
echo "=========================================="
echo "Step 2: 构建 SystemC Model"
echo "=========================================="
if [ ! -d "model/qe_band_solver_model/build" ]; then
  cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
fi
cmake --build model/qe_band_solver_model/build -j4

echo ""
echo "=========================================="
echo "Step 3: 运行快速 DSE Sweep (stub 模式)"
echo "=========================================="
mkdir -p results/quick_start
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --workloads si4_pbe_uspp_small \
  --families F1 F2 \
  --diag-policies device_first_fallback cpu_only \
  --offload-scopes balanced \
  --resident-policies fit_first \
  --partition-strategies operator__build__diag__refresh \
  --canonical-only \
  --max-design-points 4 \
  --output-dir results/quick_start/stub_sweep \
  --json-name sweep_stub.json \
  --csv-name sweep_stub.csv

echo ""
echo "=========================================="
echo "Step 4: 查看 Stub 结果"
echo "=========================================="
echo "CSV 结果:"
cat results/quick_start/stub_sweep/sweep_stub.csv | head -5
echo ""
echo "完整结果: results/quick_start/stub_sweep/sweep_stub.json"

echo ""
echo "=========================================="
echo "Step 5: (可选) 运行 SystemC Model 执行"
echo "=========================================="
echo "如果要运行真实 simulator，执行:"
echo ""
echo "python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \\"
echo "  --workloads si4_pbe_uspp_small \\"
echo "  --families F2 \\"
echo "  --execute-model \\"
echo "  --model-bin model/qe_band_solver_model/build/qe_band_solver_model \\"
echo "  --output-dir results/quick_start/real_sweep"

echo ""
echo "=========================================="
echo "✅ Quick Start 完成！"
echo "=========================================="
echo "下一步:"
echo "1. 查看结果: cat results/quick_start/stub_sweep/sweep_stub.csv"
echo "2. 运行真实 simulator (见上面的命令)"
echo "3. 扩展到更多 workloads 和 families"
echo "4. 自定义 component catalog 和 graph"
