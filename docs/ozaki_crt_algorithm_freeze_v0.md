# Ozaki / CRT Algorithm Freeze v0

## 1. 作用

这份文档只处理一件事：

- 冻结当前系统论文里 `complex FP64 GEMM` 的主算法路线

它不讨论总系统架构，不讨论 `NML` 微对角化，只讨论：

- `Ozaki-II`
- residue 组织
- `CRT` 重构
- fallback contract

## 2. 已冻结内容

以下内容在当前版本中视为已冻结：

1. 主路线
   - `Ozaki-II + CRT + Karatsuba 3M`

2. `3M` 的角色
   - 主设计默认复数模乘分解
   - 不是近似路线

3. `4M` 的角色
   - 只作为对照和 ablation
   - 不再作为并行主路径

4. 输入数据类型
   - `complex FP64`

5. 工作负载角色
   - `QE / PySCF` 中的 complex GEMM 主路径

## 3. 需要确认的冻结项

### 决策 A：模数个数策略

**选项 A1，固定 `L = 13`**

- 优点
  - 设计和控制最简单
  - 更利于论文主线收敛
  - 面积和 buffer 更容易估
- 风险
  - 坏案例下可能需要 fallback 更早触发
  - 压力测试说服力略弱

**选项 A2，主配置 `L = 13`，压力上界 `L = 17`**

- 优点
  - 主线清楚
  - 还能覆盖更坏的动态范围样本
  - 更适合论文里的 robustness 叙事
- 风险
  - runtime / NML 需要支持模数配置切换
  - 文档和 cost model 需要同时维护主配置与上界

**推荐**

- 选 `A2`

理由：

- 主设计仍然可以按 `L = 13` 讲清楚
- 但又不会把系统写成“只有一组模数能活”的脆弱方案

### 决策 B：residue 数据流

**选项 B1，全模缓存后再算**

- 优点
  - 控制简单
  - 更容易做功能验证
- 风险
  - residue buffer 会很大
  - 当前 cost model 已经说明这会很快把 SRAM 顶高

**选项 B2，按模 streaming**

- 优点
  - 大幅压低 residue buffer
  - 更符合当前主瓶颈判断
- 风险
  - 调度更复杂
  - 数据流验证难度更高

**推荐**

- 选 `B2`

理由：

- 这是当前最直接回应“取模和恢复会不会吃很多性能”的方案
- 如果还保留全模缓存作为主线，后面很容易被问“那你们不是被 buffer 吃死了吗”

### 决策 C：CRT 组织方式

**选项 C1，所有模算完后整块重构**

- 优点
  - 逻辑更直观
  - 便于和数学公式一一对应
- 风险
  - 需要保留更多中间 residue 结果
  - 和 `B2` 的 streaming residue 不匹配

**选项 C2，边收边 accumulation，再统一恢复**

- 优点
  - 更适合 streaming residue
  - 可减少中间结果保留
- 风险
  - 控制更复杂
  - 需要更明确的 accumulator 位宽和异常处理

**推荐**

- 选 `C2`

理由：

- 如果 `B` 选 streaming，`C` 最自然也应选 accumulation
- 这样数据流才是一致的

### 决策 D：scaling / integerization contract

**选项 D1，power-of-two row/column scaling + truncation**

- 优点
  - 最接近当前行为模型
  - 硬件实现最自然
  - 可复现性最好
- 风险
  - 不是最激进的数值利用率

**选项 D2，更复杂的自适应缩放 / rounding**

- 优点
  - 可能减少个别样本上的模数需求
- 风险
  - 控制复杂度上升
  - 论文主线容易被细节拖散

**推荐**

- 选 `D1`

理由：

- 当前阶段更需要稳定、可解释、可落地的 contract
- 不是先去追求极限缩放策略

### 决策 E：fallback contract

**选项 E1，只在明显失败时 fallback**

- 优点
  - 主路径命中率更高
- 风险
  - 容易把异常情况拖到后段才暴露

**选项 E2，在前处理阶段就保守判定**

- 优点
  - 系统行为更稳定
  - 更像正式产品级 contract
- 风险
  - 会损失一部分可跑样本

**推荐**

- 选 `E2`

建议冻结为：

- 超过 `L_max = 17` 的模数需求时 fallback
- 非 `{N, C}` 模式 fallback
- tile 小于 crossover 点时 fallback
- precheck 发现潜在溢出或非法值时 fallback

## 4. 当前建议冻结版

如果本轮确认通过，`Ozaki / CRT` 主算法就冻结成：

1. 主路线
   - `Ozaki-II + CRT + Karatsuba 3M`

2. 模数策略
   - 主配置 `L = 13`
   - 压力测试上界 `L = 17`

3. residue 数据流
   - streaming 优先

4. CRT 组织
   - accumulation 优先

5. scaling / integerization
   - power-of-two row/column scaling
   - truncation contract

6. fallback
   - 前置保守判定

## 5. 当前最需要你确认的点

如果只挑对系统影响最大的 3 个，这轮最值得确认的是：

1. `A`：`L` 固定还是 `13 + 17` 双档
2. `B`：residue 是 streaming 还是全缓存
3. `C`：CRT 是 accumulation 还是整块重构

只要这 3 个点定下来，主算法就已经冻结了大半。
