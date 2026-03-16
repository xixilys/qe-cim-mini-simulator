# NML Generalized Eigensolver Freeze v0

## 1. 作用

这份文档只处理当前 `NML` 侧近存微对角化路线的冻结。

目标问题是：

- `QE Davidson` 已经 reduced 后的
- 小规模 dense
- Hermitian / generalized Hermitian

子空间本征问题。

当前版本不再把“direct dense generalized solver”视为唯一主线，而是明确区分：

- 主候选：固定矩阵负载的 near-memory 迭代微对角化
- baseline：direct dense generalized Hermitian solver

## 2. 已冻结内容

以下内容当前可视为已基本确定：

1. 问题类型
   - `H_sub c = lambda S_sub c`
   - 或标准 Hermitian 特例

2. 工作负载形态
   - `H_sub / S_sub` 为小规模 dense 矩阵
   - 当前更重视“本地固定矩阵 + 反复输入 block vector”的负载模式

3. 系统边界
   - near-memory tile 负责主矩阵算子：`H_sub X`、`S_sub X`
   - `NML` 负责 reduced-space 构造、正交化、微型广义本征求解与 fixed-step 控制

4. 前处理
   - `H/S` Hermitian 化
   - `S` 正定检查

## 3. 需要确认的冻结项

### 决策 A：主算法路线

**选项 A1，fixed-matrix block iterative generalized solver**

- 形式上接近 `LOBPCG` / block Rayleigh-Ritz
- 但在实现上允许采用 fixed-step、硬件友好的简化版本

优点：

- 最符合 `CIM` / near-memory 的固定矩阵负载模型
- 能让 `H_sub / S_sub` 常驻 tile，突出架构创新点
- 与当前 dual-bank + row residue buffer + `3M` tile 组织天然匹配

风险：

- reduced-space 更新与正交化逻辑仍需仔细设计
- 与 textbook 算法的偏差需要解释清楚
- 需要单独建立 fixed-step 误差与收敛行为验证

**选项 A2，direct dense generalized Hermitian solver**

优点：

- 数学链最传统
- 更容易和 reference/LAPACK 对齐
- 可作为很强的 baseline

风险：

- `CIM` 更像 dense kernel accelerator，而不是迭代主回路的核心
- 对当前论文的架构创新点支撑较弱

**推荐**

- 主候选选 `A1`
- 同时保留 `A2` 作为 baseline / reference flow

### 决策 B：迭代子空间形态

**选项 B1，`Q = [X, W]`**

- `X`：当前 block Ritz vector
- `W`：当前 residual / correction block

优点：

- 结构更简单
- reduced solver 规模更小
- 更适合第一版行为模型

风险：

- 比完整 `LOBPCG` 的方向信息更少

**选项 B2，`Q = [X, W, P]`**

- 额外保留上一轮方向 `P`

优点：

- 更接近 textbook `LOBPCG`
- 可能带来更好的 fixed-step 收敛行为

风险：

- 控制、buffer 和 reduced solver 规模都更大

**推荐**

- `v0` 先选 `B1`

### 决策 C：步长策略

**选项 C1，固定步长 `T`**

优点：

- 最符合硬件实现
- 最容易形成确定性调度
- 适合把近存模块定义为 refinement engine

风险：

- 需要后续实验来选 `T`

**选项 C2，按残差自适应终止**

优点：

- 算法上更标准

风险：

- 与硬件定步调度冲突
- 系统叙事更复杂

**推荐**

- `v0` 选 `C1`

### 决策 D：谱范围

**选项 D1，内部只服务最低 `m` 个本征对**

优点：

- 与 `QE diaghg` 需求一致
- 更符合 block iterative 路线的意义

风险：

- 与全谱 direct dense baseline 的对齐要额外说明

**选项 D2，内部仍做全谱**

优点：

- 更容易对齐 baseline

风险：

- 会削弱 iterative 路线的意义

**推荐**

- 对主候选 `A1` 选 `D1`
- 对 baseline `A2` 保留全谱

## 4. 当前建议冻结版

如果这一轮确认通过，近存微对角化路线就冻结成：

1. 主候选
   - fixed-matrix block iterative generalized solver

2. baseline
   - direct dense generalized Hermitian solver

3. 主候选子空间形态
   - `Q = [X, W]`

4. 主候选步长策略
   - fixed-step `T`

5. 主候选谱范围
   - 只服务最低 `m` 个本征对

## 5. 主候选算法流程

当前主候选路线可细化为下面 8 步。

### 5.1 Step 0：输入与矩阵驻留

输入是 `QE Davidson` reduced 后的：

- `H_sub`
- `S_sub`
- 初始 block vector `X`

其中：

- `H_sub / S_sub` 固定写入 near-memory tile
- 在固定步长迭代期间保持常驻

### 5.2 Step 1：Hermitianize 与 SPD 检查

`NML` 执行：

- `H_sub` Hermitian 一致性检查与必要的对称化
- `S_sub` Hermitian 检查
- generalized 路径下的 SPD 预检查

### 5.3 Step 2：tile 主算子计算

每一轮迭代里，tile 负责：

- `HX = H_sub X`
- generalized 路径下的 `SX = S_sub X`

这一层复用当前已冻结的 tile 微架构：

- `real bank + imag bank`
- `row residue buffer`
- per-tile `mod encode`
- `3M residue MAC`
- 输出边界重构

### 5.4 Step 3：reduced-space 构造

`NML` 构造：

- `A_X = X^H H X`
- `B_X = X^H S X`

然后先解小规模 generalized 问题，得到当前 Ritz 对。

### 5.5 Step 4：residual / correction block

根据当前 Ritz 对形成：

- `R = HX - SX Theta`

然后由 `NML` 执行：

- 与当前 `X` 的 `S`-正交化
- 归一化
- 得到 correction block `W`

### 5.6 Step 5：扩展子空间求解

构造：

- `Q = [X, W]`

并在 `NML` 中形成：

- `Q^H H Q`
- `Q^H S Q`

然后解 reduced generalized eigensystem，取最低 `m` 个 Ritz 对。

### 5.7 Step 6：更新 block vector

用 reduced-space 解更新：

- 新一轮 `X`
- 对应 Ritz 值 `Theta`

### 5.8 Step 7：固定步长终止

重复上述流程固定 `T` 步后：

- 输出最低 `m` 个候选本征对
- 回送给外层 `QE Davidson`

当前主候选在系统里的正确定位是：

- near-memory subspace refinement engine

而不是一个独立替代外层 Davidson 的全局求解器。

## 6. Baseline 路线

当前仍保留一条 direct dense generalized baseline：

- `Hermitianize`
- `SPD check`
- `Cholesky`
- generalized 到 standard
- tridiagonalization
- implicit QR
- back-transform

这条路线的作用是：

- 作为数值 reference / golden flow
- 为 fixed-step iterative 路线提供误差、残差和正交性对照
- 在早期验证阶段提供 fallback 与行为基线

## 7. `NML / CIM` 的细化边界

### 7.1 `NML` 必做内容

- Hermitianize 与输入检查
- `S_sub` SPD 检查
- 初始 block vector 组织
- fixed-step 调度
- reduced-space generalized matrix 构造
- `S`-正交化
- 微型 generalized eigensolve
- 输出排序与结果打包

### 7.2 near-memory tile 负责内容

- `H_sub X`
- `S_sub X`
- `Q^H H Q` 与 `Q^H S Q` 所需主矩阵乘法
- 实部 / 虚部分离行读出
- residue 行复用
- `3M` 模域乘加与输出边界重构

### 7.3 当前不下放到 tile 的内容

- `S`-正交化控制
- reduced generalized eigensolver 本身
- fixed-step 终止控制
- fallback / fail reason 判定

## 8. 验证指标

对主候选路线，至少统一报告：

- lowest-`m` eigenvalue max / rms relative error
- generalized residual
- `V^H S V - I` 缺陷
- fixed-step `T` 下的误差变化
- 与 direct dense baseline 的对照

## 9. 当前最需要确认的点

如果只挑对整体系统影响最大的 3 个，这轮最值得确认的是：

1. 主候选是否正式冻结为 fixed-matrix iterative，而 direct dense 退为 baseline
2. `Q = [X, W]` 是否作为 `v0` 的 reduced-space 形态
3. fixed-step `T` 的首轮实验范围是 `4 / 6 / 8` 还是其他配置
