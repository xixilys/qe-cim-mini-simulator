# Phase 1 实施计划：DSE架构模板系统

## 执行摘要

**目标：** 让DSE框架能够探索不同的系统架构（不同cluster数量、不同计算单元类型），而不仅仅是参数。

**当前进度：** 50% 完成
- ✅ 分析现有系统
- ✅ 设计架构模板schema
- ✅ 创建3个初始模板
- 🔄 实现模板加载器（进行中）
- ⏳ 实现候选生成器
- ⏳ 验证模板系统

---

## 已完成工作

### 1. 系统分析 ✅

**发现：**
- F1/F2/F3只是"工作分配策略"不同，不是架构本质不同
- 当前DSE硬编码了4-Cluster + CIM架构
- SystemC模型模块化较好，但配置不灵活
- Timing模型使用代理公式（±20%精度）

**关键文件：**
- `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py` - DSE主框架
- `docs/architecture/qe_ic_component_catalog_system_level_v1.json` - 组件目录
- `docs/architecture/qe_ic_graph_seed_system_level_v1.json` - F2架构定义

### 2. 架构模板Schema设计 ✅

**文件：** `docs/architecture/architecture_template_schema_v1.json`

**核心概念：**
```json
{
  "template_id": "唯一标识",
  "family": "F1/F2/F3/F4/F5/custom",
  "clusters": [
    {
      "cluster_id": "cluster_a",
      "role": "operator_sweep",
      "compute_unit": "cim_array | traditional_fpga_dsp | pim_*",
      "enabled": true,
      "timing_model": "proxy_formula | cycle_accurate | hybrid"
    }
  ],
  "policies": {
    "diag_policy": "...",
    "offload_scope": "...",
    "resident_policy": "...",
    "partition_strategy": "..."
  }
}
```

**支持的架构变体：**
- Cluster数量：1-8个（灵活配置）
- 计算单元：CIM Array, Traditional FPGA DSP, PIM, Hybrid
- Timing模型：代理公式、cycle-accurate、混合
- 融合策略：可以标记cluster为融合组

### 3. 初始架构模板 ✅

**已创建3个模板：**

#### 模板1: `4cluster_cim_baseline_v1.json`
- **描述：** 当前baseline，4-Cluster + CIM Array
- **特点：** Cluster A使用CIM（Ozaki-II），其他用Traditional FPGA
- **状态：** 已验证（si4: 24.75x, si8: 125x speedup）
- **用途：** 作为对比基准

#### 模板2: `4cluster_traditional_fpga_v1.json`
- **描述：** 4-Cluster + 全Traditional FPGA DSP
- **特点：** Cluster A使用16x16 DSP阵列，300MHz时钟
- **状态：** 未验证，需要DSE评估
- **用途：** 测试Traditional FPGA是否能与CIM竞争

#### 模板3: `3cluster_fused_build_diag_v1.json`
- **描述：** 3-Cluster，融合Build+Diag
- **特点：** 减少inter-cluster通信，增加单cluster复杂度
- **状态：** 实验性，需要实现和验证
- **用途：** 探索cluster融合的性能影响

---

## 接下来的工作

### Task 1.4: 实现模板加载器 🔄

**目标：** 在DSE框架中添加模板加载和验证功能

**实现位置：** `tools/benchmarks/architecture_template_loader.py`

**功能需求：**
```python
class ArchitectureTemplateLoader:
    def load_template(self, template_path: Path) -> ArchitectureTemplate:
        """加载并验证单个模板"""
        
    def load_all_templates(self, template_dir: Path) -> List[ArchitectureTemplate]:
        """加载目录下所有模板"""
        
    def validate_template(self, template: dict) -> ValidationResult:
        """根据schema验证模板"""
        
    def get_enabled_clusters(self, template: ArchitectureTemplate) -> List[ClusterConfig]:
        """获取启用的cluster配置"""
```

**验证规则：**
1. JSON格式正确
2. 符合schema定义
3. cluster_id唯一
4. 至少有1个enabled cluster
5. fusion_group引用有效
6. resource_budget合理（不超过FPGA总资源）

**工作量：** 2-3小时

---

### Task 1.5: 实现候选生成器 ⏳

**目标：** 根据模板生成候选架构（参数sweep）

**实现位置：** `tools/benchmarks/architecture_candidate_generator.py`

**功能需求：**
```python
class ArchitectureCandidateGenerator:
    def generate_candidates(
        self, 
        template: ArchitectureTemplate,
        sweep_strategy: str = "grid_search"
    ) -> List[CandidateArchitecture]:
        """根据模板生成候选架构"""
        
    def apply_parameter_sweep(
        self,
        base_config: dict,
        param_ranges: dict
    ) -> List[dict]:
        """对参数进行sweep"""
```

**Sweep策略：**

**1. Grid Search（网格搜索）**
```python
# 示例：对clock_mhz和gemm_tile_size进行sweep
param_ranges = {
    "compute_config.clock_mhz": [200, 250, 300],
    "compute_config.gemm_tile_size": [16, 32, 64]
}
# 生成 3 × 3 = 9 个候选
```

**2. Random Sampling（随机采样）**
```python
# 从参数空间随机采样N个点
n_samples = 50
candidates = random_sample(param_ranges, n_samples)
```

**3. Latin Hypercube Sampling（拉丁超立方采样）**
```python
# 更均匀地覆盖参数空间
candidates = lhs_sample(param_ranges, n_samples)
```

**参数sweep范围：**
- `clock_mhz`: [200, 250, 300, 350]
- `gemm_tile_size`: [16, 32, 64]
- `dsp_array_dims`: [(8,8), (16,16), (32,32)]
- `l1_buffer_kb`: [128, 256, 512]
- `resident_budget_scale`: [0.8, 1.0, 1.2]

**工作量：** 3-4小时

---

### Task 1.6: 验证模板系统 ⏳

**目标：** 端到端测试模板系统

**测试用例：**

**Test 1: 模板加载**
```python
def test_load_template():
    loader = ArchitectureTemplateLoader()
    template = loader.load_template("4cluster_cim_baseline_v1.json")
    assert template.template_id == "4cluster_cim_baseline_v1"
    assert len(template.clusters) == 4
```

**Test 2: 候选生成**
```python
def test_generate_candidates():
    generator = ArchitectureCandidateGenerator()
    candidates = generator.generate_candidates(
        template,
        sweep_strategy="grid_search"
    )
    assert len(candidates) > 0
    assert all(c.is_valid() for c in candidates)
```

**Test 3: 转换为SystemC配置**
```python
def test_to_systemc_config():
    candidate = candidates[0]
    systemc_config = candidate.to_systemc_config()
    
    # 验证生成的配置可以被SystemC模型读取
    assert "architecture" in systemc_config
    assert "clusters" in systemc_config["architecture"]
```

**Test 4: 端到端DSE**
```python
def test_end_to_end_dse():
    # 加载模板
    templates = loader.load_all_templates("architecture_templates/")
    
    # 生成候选
    all_candidates = []
    for template in templates:
        candidates = generator.generate_candidates(template)
        all_candidates.extend(candidates)
    
    # 运行DSE（dry-run，不实际运行SystemC）
    results = dse_runner.run_sweep(all_candidates, dry_run=True)
    
    assert len(results) == len(all_candidates)
```

**工作量：** 2-3小时

---

## 集成到现有DSE框架

### 修改 `run_systemc_architecture_family_dse_sweep.py`

**当前流程：**
```python
# 硬编码的架构
FAMILY_PROFILES = {"F1": {...}, "F2": {...}, "F3": {...}}

for family in ["F1", "F2", "F3"]:
    for workload in workloads:
        # 运行仿真
```

**新流程：**
```python
# 从模板加载架构
loader = ArchitectureTemplateLoader()
templates = loader.load_all_templates("docs/architecture/architecture_templates/")

generator = ArchitectureCandidateGenerator()

for template in templates:
    # 生成候选
    candidates = generator.generate_candidates(template, sweep_strategy="grid_search")
    
    for candidate in candidates:
        for workload in workloads:
            # 转换为SystemC配置
            systemc_config = candidate.to_systemc_config()
            
            # 运行仿真
            result = run_systemc_simulation(systemc_config, workload)
            
            # 记录结果
            record_result(template, candidate, workload, result)
```

**向后兼容：**
- 保留原有的F1/F2/F3支持
- 添加 `--use-templates` 标志启用新模板系统
- 默认行为不变

---

## 文件结构

```
docs/architecture/
├── architecture_template_schema_v1.json          # Schema定义
├── architecture_template_system_design.md        # 设计文档
└── architecture_templates/                       # 模板目录
    ├── 4cluster_cim_baseline_v1.json            # ✅ 已创建
    ├── 4cluster_traditional_fpga_v1.json        # ✅ 已创建
    ├── 3cluster_fused_build_diag_v1.json        # ✅ 已创建
    ├── 5cluster_specialized_v1.json             # 待创建
    └── 2cluster_aggressive_fusion_v1.json       # 待创建

docs/benchmarks/
├── architecture_template_loader.py               # 🔄 实现中
├── architecture_candidate_generator.py           # ⏳ 待实现
├── test_architecture_templates.py                # ⏳ 待实现
└── run_systemc_architecture_family_dse_sweep.py  # 需要修改
```

---

## 时间估算

| Task | 工作量 | 状态 |
|------|--------|------|
| 1.1 系统分析 | 2小时 | ✅ 完成 |
| 1.2 Schema设计 | 2小时 | ✅ 完成 |
| 1.3 创建初始模板 | 2小时 | ✅ 完成 |
| 1.4 模板加载器 | 3小时 | 🔄 进行中 |
| 1.5 候选生成器 | 4小时 | ⏳ 待开始 |
| 1.6 验证测试 | 3小时 | ⏳ 待开始 |
| **总计** | **16小时** | **~2天** |

---

## 下一步行动

**立即开始：**
1. 实现 `architecture_template_loader.py`
2. 编写单元测试验证加载功能
3. 实现 `architecture_candidate_generator.py`
4. 端到端测试

**验证标准：**
- ✅ 能加载3个已创建的模板
- ✅ 能生成至少10个候选架构
- ✅ 生成的配置符合SystemC输入格式
- ✅ 所有单元测试通过

---

## 风险和缓解

### 风险1: SystemC配置格式不兼容
**缓解：** 先用dry-run模式测试，不实际运行SystemC

### 风险2: 参数sweep组合爆炸
**缓解：** 使用采样策略（LHS）而非穷举

### 风险3: 模板验证规则不完善
**缓解：** 从简单规则开始，逐步完善

---

## 成功标准

Phase 1完成的标志：
1. ✅ 至少3个架构模板可用
2. ✅ DSE能加载模板并生成候选
3. ✅ 生成的配置格式正确
4. ✅ 所有测试通过
5. ✅ 文档完整

**交付物：**
- Architecture template schema
- 3个初始模板
- 模板加载器和候选生成器
- 单元测试
- 集成到DSE框架的代码

