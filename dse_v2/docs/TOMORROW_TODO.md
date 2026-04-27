# 明天的行动清单（2026-04-23）

## 🌅 早上任务（1-2 小时）

### 1. 完成 Bayesian Optimization（10 分钟）

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/dse_v2
source venv/bin/activate
python3 scripts/dse/run_bayesian_dse.py
```

**预期**: 完成剩余 3 次迭代，生成 `results/pareto/bayesian_dse_results_v2.csv`

---

### 2. 查看和分析结果（20 分钟）

```bash
# 查看 Pareto frontier
python3 -c "
import pandas as pd
df = pd.read_csv('results/pareto/bayesian_dse_results_v2.csv')
print('Pareto Frontier:')
print(df[['offload_strategy', 'pipeline_depth', 'parallel_units', 'time_s', 'energy_j']].head(10))
print(f'\nTotal Pareto points: {len(df)}')
"

# 找出最佳设计点
python3 -c "
import pandas as pd
df = pd.read_csv('results/pareto/bayesian_dse_results_v2.csv')
best_time = df.loc[df['time_s'].idxmin()]
best_energy = df.loc[df['energy_j'].idxmin()]
print('Best Time Design:')
print(best_time[['offload_strategy', 'pipeline_depth', 'parallel_units', 'time_s', 'energy_j']])
print('\nBest Energy Design:')
print(best_energy[['offload_strategy', 'pipeline_depth', 'parallel_units', 'time_s', 'energy_j']])
"
```

---

### 3. 创建简单可视化（30 分钟）

创建 `scripts/analysis/visualize_pareto.py`:

```python
#!/usr/bin/env python3
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv('results/pareto/bayesian_dse_results_v2.csv')

plt.figure(figsize=(10, 6))
plt.scatter(df['time_s']*1000, df['energy_j'], alpha=0.6, s=50)
plt.xlabel('Time to Convergence (ms)')
plt.ylabel('Energy to Convergence (J)')
plt.title('Pareto Frontier: Time vs Energy')
plt.grid(True, alpha=0.3)
plt.savefig('results/visualizations/pareto_frontier.png', dpi=300, bbox_inches='tight')
print('✅ Saved to results/visualizations/pareto_frontier.png')
```

运行:
```bash
mkdir -p results/visualizations
python3 scripts/analysis/visualize_pareto.py
```

---

## 🌤️ 下午任务（2-3 小时）

### 4. 定义新 workload matrix（1 小时）

创建 `workloads/definitions/new_workloads_v2.json`:

```json
{
  "semiconductors": {
    "GaN": {
      "atoms": [4, 8],
      "functional": "PBE",
      "pseudo": "USPP",
      "ecutwfc": 50,
      "ecutrho": 400
    },
    "GaAs": {
      "atoms": [4, 8],
      "functional": "PBE",
      "pseudo": "USPP",
      "ecutwfc": 40,
      "ecutrho": 320
    }
  },
  "2d_materials": {
    "MoS2": {
      "atoms": [3, 6],
      "functional": "PBE",
      "pseudo": "PAW",
      "ecutwfc": 60,
      "ecutrho": 480
    },
    "hBN": {
      "atoms": [4, 8],
      "functional": "PBE",
      "pseudo": "USPP",
      "ecutwfc": 50,
      "ecutrho": 400
    }
  }
}
```

---

### 5. 运行不同 workload 的 DSE（1-2 小时）

测试不同的 (npw, nkb, m) 组合:

```bash
# Small workload
python3 -c "
import sys
sys.path.append('.')
from scripts.dse.run_bayesian_dse import BayesianDSE
from pathlib import Path

fpga_specs = {
    'peak_gflops': 1300,
    'memory_bw_gbs': 77,
    'pcie_bw_gbs': 16,
    'bram_kb': 34000,
    'dsp_count': 12288,
}

dse = BayesianDSE(
    Path('design_space/definitions/host_fpga_design_space_v2.json'),
    fpga_specs
)

# Small workload
workload_small = {'npw': 1000, 'nkb': 64, 'm': 8}
results = dse.run_optimization(workload_small, n_iterations=30)
dse.save_results(results, Path('results/pareto/small_workload_pareto.csv'))

# Large workload
workload_large = {'npw': 5000, 'nkb': 200, 'm': 32}
results = dse.run_optimization(workload_large, n_iterations=30)
dse.save_results(results, Path('results/pareto/large_workload_pareto.csv'))
"
```

---

## 📊 总结任务（30 分钟）

### 6. 更新项目状态

编辑 `PROJECT_STATUS.md`:
- 标记 Week 1 任务为进行中
- 更新完成率
- 记录今天的发现

---

## 🎯 成功标志

明天结束时，你应该有：

- ✅ 完整的 50 次迭代 Bayesian Optimization 结果
- ✅ Pareto frontier 可视化图
- ✅ 至少 3 个不同 workload 的 DSE 结果
- ✅ 新 workload matrix 定义
- ✅ Top-5 设计点识别

---

## 💡 提示

1. **如果 BO 运行很慢**: 减少迭代次数到 30 次
2. **如果内存不足**: 一次只运行一个 workload
3. **如果想加速**: 使用更简单的 acquisition function

---

## 📞 遇到问题？

运行系统测试确认环境正常:
```bash
python3 tests/test_system.py
```

如果测试失败，重新激活环境:
```bash
source venv/bin/activate
```

---

**准备好了吗？明天见！** 🚀
