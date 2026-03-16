# 算法冻结状态 v0

## 1. 目的

这份文档专门回答两个问题：

1. `Ozaki-II / CRT` 复数 `FP64 GEMM` 主算法到底冻结到了什么程度
2. `NML` 侧近存微对角化流程到底冻结到了什么程度

当前项目最容易出问题的地方，不是“没有方向”，而是：

- 大方向已经基本形成
- 但关键实现细节还没有被逐条冻结

所以这里不写愿景，只写：

- 已经固定的内容
- 还没固定的内容
- 下一步必须优先冻结的内容

## 2. 复数 GEMM 主路径：当前状态

### 2.1 已基本固定

以下内容现在已经可以视为主线共识：

1. 主算法路线
   - `Ozaki-II + CRT + Karatsuba 3M`

2. `3M` 的角色
   - 主设计中的默认复数模乘分解
   - 在模域整数上与 `4M` 数学等价

3. `4M` 的角色
   - 只保留为对照基线
   - 不再作为主系统路线

4. 系统角色
   - 服务 `QE / PySCF`
   - 不是孤立复数乘法器，而是 generalized Hermitian 子空间路径里的主算力底座

### 2.2 还没有冻结

下面这些才是你刚刚指出的核心未定点：

1. 缩放 / 整数化 contract
   - `mu / nu` 的最终生成策略
   - 行缩放、列缩放还是混合
   - 截断/取整策略是否固定

2. 模数个数策略
   - 是固定 `L = 13`
   - 还是 `13~17` 自适应
   - 还是根据 workload 统计分档

3. residue 调度
   - 全模并行
   - 部分模并行
   - 纯时分多模

4. `CRT` 重构组织
   - 先完整保留所有模结果再重构
   - 还是边到边做 streaming accumulation
   - `s1+s2` 风格恢复流水是否作为主实现

5. fallback 触发条件
   - 超过模数上限时怎么回退
   - 小矩阵 crossover 点多少
   - 哪些异常由 `NML` 判定

### 2.3 当前最需要冻结的不是“3M 还是 4M”

这一点必须说清楚：

- `3M/4M` 现在不是主要矛盾
- 主要矛盾是 `取模 + residue 缓冲 + CRT 重构` 的真实代价和数据流组织

也就是说，下一步最该冻结的是：

1. `L` 的策略
2. residue 是不是 streaming
3. `CRT` 是不是边收边重构
4. 哪些场景触发 fallback

## 3. 近存微对角化：当前状态

### 3.1 已基本固定

以下内容已经可以认为方向上确定了：

1. 目标问题
   - `QE Davidson` reduced matrix
   - Hermitian / generalized Hermitian 子空间问题

2. 主系统边界
   - `CIM` 负责 dense matrix update / GEMM
   - `NML` 负责控制流强的对角化步骤

3. 当前主流程方向
   - `Hermitianize`
   - `S` 正定检查
   - `Cholesky`
   - generalized 到 standard 变换
   - standard Hermitian eigensolve
   - 回代

4. 当前工作负载前提
   - 从真实 `QE` 数据集看，当前代表性维度已经覆盖到 `N = 128`
   - 仍然属于“小规模 dense generalized Hermitian”问题

### 3.2 还没有完全冻结

这里真正没定完的地方有 4 类：

1. 主对角化算法选型是否最终固定为“direct dense”
   - 目前文档倾向 direct dense generalized Hermitian solver
   - 但还没有正式把 `LOBPCG / block iterative` 排除为主路线

2. standard Hermitian 求解内部流程
   - blocked Householder tridiagonalization
   - 之后是 implicit QR、bisection、divide-and-conquer 中哪一条
   - 还没最后冻结

3. selective spectrum 策略
   - `QE diaghg` 常见是 `m < n`
   - 我们现在还没完全冻结“近存微求解器是求全谱还是只求低端部分谱”

4. `CIM` 参与到对角化内部哪一步
   - 只做 trailing update
   - 还是还要支撑某些 block transform
   - 目前还没在行为模型层面完全钉死

## 4. 当前建议的冻结结论

如果按项目推进效率来讲，我建议现在就先冻结成下面这样：

### 4.1 复数 GEMM 路线

冻结为：

- 主算法：`Ozaki-II + CRT + Karatsuba 3M`
- `4M`：只保留为 reference / ablation
- `L`：先以 `13` 作为主配置，`17` 作为压力测试上界
- residue：主设计按 streaming 优先
- `CRT`：主设计按边收边做 accumulation 优先

原因很简单：

- 这样最直接回应“取模和恢复会不会吃很多性能”这个核心问题
- 也最符合当前 cost model 已经暴露出来的瓶颈：真正危险的是 residue buffer，不是 `3M` 本身

### 4.2 近存微对角化路线

冻结为：

- 当前 paper cut 的主路线是 **direct dense generalized Hermitian solver**
- 不是 `LOBPCG` 这类外层块迭代法

具体流程先冻结成：

1. `H/S` Hermitian 化
2. `S` 正定检查
3. Cholesky `S = L L^H`
4. 变换为标准 Hermitian 问题
5. blocked tridiagonalization
6. tridiagonal eigensolver
7. eigenvector back-transform

理由：

- 当前 `QE` 抽出来的是 **已经 reduced 的小 dense 矩阵**
- 这和“大稀疏本征问题”不是一类东西
- 如果这时候再引入 `LOBPCG`，会把系统边界弄乱，论文也更难讲清楚

换句话说：

- `QE` 外层已经用 Davidson 做过大问题迭代了
- 我们这里不需要在近存里再重复引入一层“外层本征迭代”
- 当前最合理的是把小规模 dense generalized Hermitian solver 做扎实

## 5. 当前最需要做的两份冻结文档

为了真正把这两块收口，下一步最值得直接产出的是：

1. `Ozaki/CRT algorithm freeze`
   - 固定 `L`、streaming residue、CRT accumulation、fallback contract

2. `NML generalized eigensolver freeze`
   - 固定 direct dense 路线
   - 固定 `Cholesky -> standardize -> tridiagonal -> eig -> back-transform`
   - 说明哪些替代路线不作为当前 paper cut 主线

## 6. 当前结论

所以，针对你刚刚的问题，最准确的回答是：

- **复数 GEMM 主线的大方向已经形成，但取模和恢复的数据流组织还没有完全冻结**
- **近存对角化的总流程方向已经形成，但具体算法路线还没有形成正式冻结版**

也正因为这样，项目下一步不应该继续泛化讨论，而应该进入：

- 逐项冻结主算法
- 逐项冻结近存微对角化

这两件事。
