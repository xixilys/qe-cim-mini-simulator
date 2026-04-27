# DSE v2 项目状态跟踪

## 📅 项目时间线

**开始日期**: 2026-04-22  
**预计完成**: 2026-05-22 (4 周)  
**当前状态**: Week 1 - 初始化完成

---

## ✅ 已完成任务

### Phase 0: 项目初始化 (2026-04-22)

- [x] 创建项目目录结构
- [x] 编写 requirements.txt
- [x] 创建环境设置脚本 (setup_env.sh)
- [x] 编写 README.md
- [x] 创建快速启动脚本 (quickstart.sh)
- [x] 实现快速性能模型 (performance_model.py)
- [x] 实现设计空间定义 (define_design_space.py)
- [x] 实现 Bayesian DSE 引擎 (run_bayesian_dse.py)
- [x] 创建系统测试脚本 (test_system.py)
- [x] 编写执行指南 (EXECUTION_GUIDE.md)
- [x] 创建项目配置 (project_config.json)

---

## 🚧 进行中任务

### Week 1: Workload 扩展 (2026-04-22 - 2026-04-26)

- [ ] **今天**: 运行环境设置和系统测试
- [ ] **明天**: 分析现有 workload，定义新 workload matrix
- [ ] **后天**: 准备新 QE 输入文件
- [ ] **Day 4**: 运行新 QE cases，提取 traces
- [ ] **Day 5**: 分析新 workload 特征，生成报告

---

## 📋 待办任务

### Week 2: 设计空间定义 (2026-04-29 - 2026-05-03)

- [ ] 验证快速模型准确性
- [ ] 与 SystemC 模型对比
- [ ] 误差分析和模型优化
- [ ] 添加更多约束条件
- [ ] 生成模型验证报告

### Week 3: Bayesian Optimization (2026-05-06 - 2026-05-10)

- [ ] 运行多个 workload 的优化
- [ ] 生成 Pareto frontier
- [ ] 可视化结果
- [ ] 对比不同搜索策略
- [ ] 敏感性分析

### Week 4: 验证与报告 (2026-05-13 - 2026-05-17)

- [ ] 选择 top-5 设计点
- [ ] SystemC 中等保真度验证
- [ ] FPGA board 高保真度验证（可选）
- [ ] 生成技术报告
- [ ] 文档完善

---

## 🎯 当前优先级

### 🔥 高优先级（本周必须完成）

1. **环境设置**: 运行 `setup_env.sh`，确保所有依赖安装成功
2. **系统测试**: 运行 `test_system.py`，验证系统可用性
3. **Workload 分析**: 分析现有 workload，识别扩展方向
4. **设计空间定义**: 确认设计空间参数合理性

### ⚡ 中优先级（本周尽量完成）

1. **快速模型测试**: 验证性能模型输出合理
2. **Bayesian DSE 试运行**: 小规模测试（10 次迭代）
3. **新 workload 定义**: 准备 GaN, MoS2 等输入文件

### 📌 低优先级（下周处理）

1. 可视化工具开发
2. 文档完善
3. 单元测试编写

---

## 📊 进度指标

| 阶段 | 计划任务数 | 已完成 | 进行中 | 待办 | 完成率 |
|------|-----------|--------|--------|------|--------|
| Phase 0 | 11 | 11 | 0 | 0 | 100% |
| Week 1 | 5 | 0 | 1 | 4 | 0% |
| Week 2 | 5 | 0 | 0 | 5 | 0% |
| Week 3 | 5 | 0 | 0 | 5 | 0% |
| Week 4 | 5 | 0 | 0 | 5 | 0% |
| **总计** | **31** | **11** | **1** | **19** | **35%** |

---

## 🚀 下一步行动

### 立即执行（今天）

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/dse_v2

# 1. 设置环境（10 分钟）
bash scripts/setup/setup_env.sh
source venv/bin/activate

# 2. 运行系统测试（2 分钟）
python3 tests/test_system.py

# 3. 测试快速模型（1 分钟）
python3 models/fast/performance_model.py

# 4. 定义设计空间（1 分钟）
python3 scripts/setup/define_design_space.py

# 5. 试运行 Bayesian DSE（5 分钟，10 次迭代）
# 编辑 scripts/dse/run_bayesian_dse.py，将 n_iterations 改为 10
python3 scripts/dse/run_bayesian_dse.py
```

### 明天执行

```bash
# 1. 分析现有 workload
python3 scripts/workload/analyze_existing_workloads.py

# 2. 定义新 workload matrix
vim workloads/definitions/new_workloads_v2.json

# 3. 准备 QE 输入文件（需要实现）
# TODO: 创建 generate_qe_inputs.py
```

---

## 📝 笔记与决策

### 2026-04-22: 项目启动

**决策**:
- 采用 Host+FPGA 两层架构，暂不考虑 Chip
- 使用 BoTorch + Ax 作为 Bayesian Optimization 框架
- 目标 FPGA: Xilinx Alveo U250

**理由**:
- 简化设计空间，专注于 Host-FPGA 协同优化
- BoTorch 是 Meta 开源的成熟框架，文档完善
- U250 是常见的高性能 FPGA 平台

**风险**:
- 快速模型可能不够准确（需要验证）
- 新 workload 可能需要较长时间运行
- Bayesian Optimization 可能需要调参

---

## 🐛 已知问题

1. **workload 分析脚本**: 依赖现有 trace 目录，如果不存在会失败
   - **解决方案**: 添加路径检查和友好错误提示

2. **Bayesian DSE**: 初始几次迭代可能不稳定
   - **解决方案**: 增加初始随机采样点数

3. **快速模型**: 未经验证，可能误差较大
   - **解决方案**: Week 2 进行系统性验证

---

## 📈 成功指标

### Week 1 成功标志
- [ ] 环境设置成功，所有测试通过
- [ ] 至少分析 5 个现有 workload
- [ ] 定义至少 10 个新 workload
- [ ] 提取至少 5 个新 workload trace

### Week 2 成功标志
- [ ] 快速模型误差 < 20%
- [ ] 设计空间包含 > 1M 配置
- [ ] 完成至少 1 个完整的 BO 运行（50+ 迭代）

### Week 3 成功标志
- [ ] 生成至少 3 个 workload 的 Pareto frontier
- [ ] Pareto frontier 包含 10+ 非支配解
- [ ] 完成搜索策略对比

### Week 4 成功标志
- [ ] Top-5 设计点通过 SystemC 验证
- [ ] 生成完整技术报告
- [ ] 文档完善度 > 80%

---

## 🎉 里程碑

- [ ] **M1**: 环境设置完成 (2026-04-22)
- [ ] **M2**: 第一个 Bayesian DSE 运行成功 (2026-04-23)
- [ ] **M3**: 10 个新 workload trace 完成 (2026-04-26)
- [ ] **M4**: 快速模型验证完成 (2026-05-03)
- [ ] **M5**: 多 workload Pareto frontier 生成 (2026-05-10)
- [ ] **M6**: 最终报告完成 (2026-05-17)

---

**最后更新**: 2026-04-22  
**更新人**: DSE v2 Team
