# DSE v2 Project

完全重建的 Host+FPGA 设计空间探索框架，采用现代 Bayesian Optimization 方法。

## 项目目标

1. **简化架构**: Host+FPGA 两层（暂不考虑 Chip）
2. **扩展 workload**: 增加新材料体系和计算场景
3. **现代 DSE**: Bayesian Optimization 替代 rule-based
4. **完全开放设计空间**: 不受现有 4-cluster pipeline 约束

## 目录结构

```
dse_v2/
├── workloads/          # Workload 定义和 trace 数据
│   ├── traces/         # QE trace CSV 文件
│   ├── analysis/       # Workload 分析结果
│   └── definitions/    # Workload matrix 定义
├── design_space/       # 设计空间定义
│   ├── definitions/    # 参数空间定义
│   ├── constraints/    # 约束条件
│   └── templates/      # 设计点模板
├── models/             # 性能模型
│   ├── fast/           # 快速分析模型（Roofline）
│   ├── mid/            # 中等保真度模型（SystemC）
│   └── high/           # 高保真度模型（FPGA board）
├── optimization/       # 优化算法
│   ├── bayesian/       # Bayesian Optimization
│   ├── evolutionary/   # 进化算法
│   └── hybrid/         # 混合方法
├── results/            # DSE 结果
│   ├── pareto/         # Pareto frontier
│   ├── reports/        # 分析报告
│   └── visualizations/ # 可视化
├── scripts/            # 执行脚本
│   ├── setup/          # 环境设置
│   ├── workload/       # Workload 处理
│   ├── dse/            # DSE 执行
│   └── analysis/       # 结果分析
├── docs/               # 文档
│   ├── design/         # 设计文档
│   ├── api/            # API 文档
│   └── tutorials/      # 教程
└── tests/              # 测试
    ├── unit/           # 单元测试
    └── integration/    # 集成测试
```

## 快速开始

### 1. 环境设置

```bash
cd dse_v2
bash scripts/setup/setup_env.sh
source venv/bin/activate
```

### 2. 分析现有 workload

```bash
python3 scripts/workload/analyze_existing_workloads.py
```

### 3. 定义设计空间

```bash
python3 scripts/setup/define_design_space.py
```

### 4. 运行 Bayesian Optimization

```bash
python3 scripts/dse/run_bayesian_dse.py --workload si8_pbe_uspp --iterations 50
```

### 5. 运行 Generic DSE QE SCF shell full-flow pilot

```bash
cmake -S ../model/generic_sim_backend -B ../model/generic_sim_backend/build
cmake --build ../model/generic_sim_backend/build -j4
python3 scripts/dse/run_full_flow_pilot.py --workload qe_scf_shell --backend systemc --out ../runs/dse/qe_scf_shell_systemc
```

该 pilot 会生成 `manifest.json`、`verdict.json`、SystemC timing evidence、`final_report.json`、`final_report.md` 和 `claim_validation.json`。报告规则见 `docs/GENERIC_DSE_FULL_FLOW_REPORTING.md`；单个 pilot 只能作为可行性/phase timing evidence，不能升级为最终 best-architecture 或 Pareto claim。

## 开发路线图

### Week 1: Workload 扩展
- [x] 分析现有 workload
- [ ] 定义新 workload matrix
- [ ] 运行新 QE cases
- [ ] 提取和分析 traces

### Week 2: 设计空间定义
- [ ] 定义 Host+FPGA 参数空间
- [ ] 实现快速性能模型
- [ ] 验证模型准确性

### Week 3: Bayesian Optimization
- [ ] 实现 BO DSE 引擎
- [ ] 运行初步优化
- [ ] 生成 Pareto frontier

### Week 4: 验证和报告
- [ ] 高保真度验证
- [ ] 生成技术报告
- [ ] 文档完善

## 依赖

- Python 3.9+
- PyTorch 2.0+
- BoTorch 0.9+
- Ax Platform 0.3+

详见 `requirements.txt`

## 许可

内部研究项目
