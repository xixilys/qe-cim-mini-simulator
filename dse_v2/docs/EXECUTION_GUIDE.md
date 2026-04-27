# DSE v2 完整执行指南

## 🎯 项目概述

这是一个**完全重建**的 Host+FPGA 设计空间探索框架，采用现代 Bayesian Optimization 方法，吸取了现有系统的经验教训。

### 核心改进

1. **简化架构**: Host+FPGA 两层（暂不考虑 Chip 内部复杂性）
2. **智能搜索**: Bayesian Optimization 替代 rule-based grid search
3. **完全开放设计空间**: 不受现有 4-cluster pipeline 约束
4. **扩展 workload**: 新增半导体、2D 材料、过渡金属氧化物等

---

## 📋 立即开始（5 分钟快速启动）

### 方法 1: 一键启动（推荐）

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/dse_v2
bash scripts/quickstart.sh
```

这个脚本会自动完成：
- ✅ 环境设置
- ✅ 分析现有 workload
- ✅ 定义设计空间
- ✅ 测试性能模型
- ✅ 运行 Bayesian Optimization（50 次迭代）

### 方法 2: 分步执行

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/dse_v2

# Step 1: 设置环境
bash scripts/setup/setup_env.sh
source venv/bin/activate

# Step 2: 运行系统测试
python3 tests/test_system.py

# Step 3: 分析现有 workload
python3 scripts/workload/analyze_existing_workloads.py

# Step 4: 定义设计空间
python3 scripts/setup/define_design_space.py

# Step 5: 测试快速性能模型
python3 models/fast/performance_model.py

# Step 6: 运行 Bayesian Optimization
python3 scripts/dse/run_bayesian_dse.py
```

---

## 📊 预期输出

### 1. Workload 分析结果

位置: `workloads/analysis/existing_workloads_analysis.csv`

```
case_name,material,atoms,functional,pseudo,solver,avg_npw,avg_nkb,avg_m,total_time_s
si8_pbe_uspp,Si,8,PBE,USPP,Davidson,2945,144,16,12.5
graphene_pbe_uspp,graphene,4,PBE,USPP,Davidson,1856,96,12,8.3
...
```

### 2. 设计空间定义

位置: `design_space/definitions/host_fpga_design_space_v2.json`

```json
{
  "version": "v2.0",
  "total_configurations": 10321920,
  "categorical_params": {
    "offload_strategy": ["h_psi_only", "h_s_psi_fused", ...],
    "dataflow_pattern": ["streaming", "buffered", "hybrid"],
    ...
  },
  "integer_params": {
    "pipeline_depth": {"min": 2, "max": 5},
    "parallel_units": {"values": [1, 2, 4, 8]},
    ...
  }
}
```

### 3. Bayesian Optimization 结果

位置: `results/pareto/bayesian_dse_results_v2.csv`

```
offload_strategy,pipeline_depth,parallel_units,time_s,energy_j,dsp_utilization,bram_utilization
h_s_psi_fused,4,4,0.0234,0.68,0.42,0.35
full_operator_sweep,5,8,0.0189,0.95,0.71,0.58
...
```

**Pareto Frontier**: 时间-能耗的最优权衡点集合

---

## 🔧 自定义配置

### 修改 FPGA 目标平台

编辑 `scripts/dse/run_bayesian_dse.py`:

```python
fpga_specs = {
    'peak_gflops': 1300,      # 修改为你的 FPGA 峰值算力
    'memory_bw_gbs': 77,      # 修改为你的内存带宽
    'pcie_bw_gbs': 16,        # 修改为你的 PCIe 带宽
    'bram_kb': 34000,         # 修改为你的 BRAM 容量
    'dsp_count': 12288,       # 修改为你的 DSP 数量
}
```

### 修改优化迭代次数

```python
results = dse.run_optimization(workload, n_iterations=100)  # 默认 50
```

### 修改目标 workload

```python
workload = {
    'npw': 2945,   # 平面波数量
    'nkb': 144,    # 投影子数量
    'm': 16,       # band 数量
}
```

---

## 📈 Week 1-4 详细计划

### Week 1: Workload 扩展（当前周）

**目标**: 增加 10-15 个新 workload cases

#### 任务清单

- [x] 分析现有 workload（已完成）
- [ ] 定义新 workload matrix
  - [ ] GaN (4, 8, 16 atoms)
  - [ ] MoS2 (3, 6, 12 atoms)
  - [ ] TiO2 (6, 12 atoms)
- [ ] 准备 QE 输入文件
- [ ] 运行 QE 并提取 trace
- [ ] 分析新 workload 特征

#### 执行步骤

```bash
# 1. 创建新 workload 定义
cat > workloads/definitions/new_workloads_v2.json << 'EOF'
{
  "semiconductors": {
    "GaN": {"atoms": [4, 8, 16], "pseudo": ["NC", "USPP"]},
    "GaAs": {"atoms": [4, 8], "pseudo": ["NC", "USPP"]}
  },
  "2d_materials": {
    "MoS2": {"atoms": [3, 6, 12], "pseudo": ["USPP", "PAW"]},
    "hBN": {"atoms": [4, 8], "pseudo": ["NC", "USPP"]}
  }
}
EOF

# 2. 生成 QE 输入文件（需要实现）
python3 scripts/workload/generate_qe_inputs.py \
  --definition workloads/definitions/new_workloads_v2.json \
  --output qe_inputs/

# 3. 运行 QE
for input in qe_inputs/*.in; do
    soft/qe-7.5/build_subspace_trace/bin/pw.x -i $input > ${input%.in}.out
done

# 4. 提取 trace
python3 scripts/workload/extract_traces.py \
  --input-dir qe_outputs/ \
  --output-dir workloads/traces/

# 5. 分析新 workload
python3 scripts/workload/analyze_new_workloads.py
```

**交付物**:
- ✅ 10-15 个新 workload trace CSV
- ✅ 扩展的 workload characterization 报告
- ✅ Workload 多样性分析

---

### Week 2: 设计空间定义与快速模型

**目标**: 完善设计空间定义，验证快速性能模型

#### 任务清单

- [x] 定义 Host+FPGA 参数空间（已完成）
- [x] 实现快速性能模型（已完成）
- [ ] 验证模型准确性
  - [ ] 与现有 SystemC 模型对比
  - [ ] 误差分析
- [ ] 添加更多约束条件
- [ ] 优化模型性能

#### 执行步骤

```bash
# 1. 验证快速模型
python3 tests/validate_fast_model.py \
  --systemc-results ../model/qe_band_solver_model/results/ \
  --output results/model_validation/

# 2. 误差分析
python3 scripts/analysis/analyze_model_error.py

# 3. 优化模型
python3 scripts/analysis/tune_model_parameters.py
```

**交付物**:
- ✅ 验证报告（模型误差 < 20%）
- ✅ 优化后的性能模型
- ✅ 模型准确性分析

---

### Week 3: Bayesian Optimization 实现

**目标**: 完整的 BO DSE 引擎，生成 Pareto frontier

#### 任务清单

- [x] 实现 BO DSE 引擎（已完成）
- [ ] 运行多个 workload 的优化
- [ ] 生成 Pareto frontier 可视化
- [ ] 对比不同搜索策略
- [ ] 敏感性分析

#### 执行步骤

```bash
# 1. 运行多个 workload
for workload in si8 graphene gan mos2; do
    python3 scripts/dse/run_bayesian_dse.py \
      --workload $workload \
      --iterations 100 \
      --output results/pareto/${workload}_pareto.csv
done

# 2. 生成可视化
python3 scripts/analysis/visualize_pareto.py \
  --input results/pareto/ \
  --output results/visualizations/

# 3. 对比搜索策略
python3 scripts/analysis/compare_search_methods.py \
  --methods bayesian,random,grid \
  --output results/comparison/

# 4. 敏感性分析
python3 scripts/analysis/sensitivity_analysis.py
```

**交付物**:
- ✅ 每个 workload 的 Pareto frontier
- ✅ 可视化报告（时间-能耗权衡图）
- ✅ 搜索策略对比
- ✅ 参数敏感性分析

---

### Week 4: 验证与报告

**目标**: 高保真度验证，生成最终技术报告

#### 任务清单

- [ ] 选择 top-5 设计点
- [ ] SystemC 中等保真度验证
- [ ] FPGA board 高保真度验证（如果可用）
- [ ] 生成技术报告
- [ ] 文档完善

#### 执行步骤

```bash
# 1. 选择 top-5 候选
python3 scripts/analysis/select_top_candidates.py \
  --pareto results/pareto/ \
  --top 5 \
  --output results/top_candidates.json

# 2. SystemC 验证
python3 scripts/validation/run_systemc_validation.py \
  --candidates results/top_candidates.json \
  --output results/validation/systemc/

# 3. 生成报告
python3 scripts/analysis/generate_report.py \
  --results results/ \
  --output docs/final_report.pdf

# 4. 生成 README
python3 scripts/analysis/generate_summary.py \
  --output docs/SUMMARY.md
```

**交付物**:
- ✅ Top-5 设计点详细分析
- ✅ 验证报告（correctness + performance）
- ✅ 技术报告（PDF）
- ✅ 完整文档

---

## 🐛 故障排除

### 问题 1: 虚拟环境创建失败

```bash
# 确保 Python 3.9+
python3 --version

# 手动创建虚拟环境
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 问题 2: BoTorch 安装失败

```bash
# 先安装 PyTorch
pip install torch --index-url https://download.pytorch.org/whl/cpu

# 再安装 BoTorch
pip install botorch ax-platform
```

### 问题 3: 找不到现有 workload

```bash
# 检查路径
ls ../docs/benchmarks/results/qe_workload_revalidation/

# 如果不存在，跳过分析现有 workload，直接定义新的
python3 scripts/setup/define_design_space.py
```

### 问题 4: Bayesian Optimization 运行缓慢

```bash
# 减少迭代次数
python3 scripts/dse/run_bayesian_dse.py --iterations 20

# 或使用更快的 acquisition function
# 编辑 scripts/dse/run_bayesian_dse.py，修改 acquisition function
```

---

## 📚 进一步阅读

- `docs/design/architecture.md` - 架构设计文档
- `docs/design/methodology.md` - DSE 方法论
- `docs/api/` - API 文档
- `docs/tutorials/` - 教程

---

## 🎉 成功标志

完成以下里程碑即表示项目成功：

- ✅ **Week 1**: 15+ workload traces，覆盖 5+ 材料类别
- ✅ **Week 2**: 快速模型误差 < 20%，设计空间 > 1M 配置
- ✅ **Week 3**: Pareto frontier 包含 10+ 非支配解
- ✅ **Week 4**: Top-5 设计点通过 SystemC 验证

---

## 📞 联系与支持

如有问题，请查看：
- `tests/test_system.py` - 系统测试
- `docs/troubleshooting.md` - 故障排除指南
- GitHub Issues（如果有）

---

**祝你成功！🚀**
