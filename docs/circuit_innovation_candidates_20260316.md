# QE / VASP / PySCF 负载挖掘后的电路创新候选（2026-03-16）

## 1. 这份 memo 的目标

这份 memo 不再围绕：

- `FP64`
- `mixed precision`
- 或“把某个已有算法搬到 CIM”

来找创新点。

它只回答三个更硬的问题：

1. `dual-operator projection` 这种想法有没有明显前人直接做过
2. 如果只提“支持 transpose”，是不是足够成为大创新点
3. 从 `QE / VASP / PySCF` 的真实负载看，**更值得打的电路创新点**到底是什么

## 2. 先说结论

## 2.1 直接对口的“科学计算 dual-operator projection CIM”我目前没有找到成熟先例

我没有在近期 `ISSCC / VLSI / JSSC` 的公开 program 和可检索资料里看到很直接对口的方向：

- 面向 `QE / VASP / PySCF`
- 或面向 generalized-eigen / non-orthogonal 工作负载
- 原生支持 `forward + adjoint + local projection`
- 并把它包装成 `CIM primitive`

所以这条线**不是拥挤红海**。

但要注意，这不等于“只要做了就一定成立”。  
真正危险的是做成“没人做过，因为也没人关心”的方向。

## 2.2 “支持 transpose”本身不够大，而且近年已经有人做

近年的 `CIM` 宏已经出现了明显的 `transpose / non-transpose / bidirectional` 倾向。  
至少从 `VLSI 2025` 官方 advance program 可以直接看到：

- `A 28nm 384Kb 8T SRAM-CIM Macro Utilizing Concurrent-Transpose/Non-Transpose Computation ...`

这说明：

- **transpose 能力本身不是空白**
- 如果我们的主张只是“阵列支持转置访问”，那很难成为核心创新点

更准确地说：

- `transpose` 更像一个**硬件机制**
- 不是最终想打的**工作负载创新点**

真正的问题应该是：

- `QE / VASP / PySCF` 到底需要什么样的 `transpose / adjoint / reduction`

## 2.3 当前最值得打的点，不是“转置”，而是“adjoint-aware projector/projection primitive”

如果把三个软件的负载放在一起看，最深的共性不是：

- 单次 `GEMM`
- 也不是单次 `FFT`
- 更不是“高精度”本身

而是下面这一类模式反复出现：

1. 固定或半固定的 basis / projector / operator 常驻
2. 流入 block / orbital batch / wavefunction batch
3. 先做 **forward projection**
4. 再做一个小矩阵变换或对角权重
5. 再做 **adjoint / back-projection**
6. 同时常常伴随：
   - conjugation
   - Hermitian / triangular symmetry
   - local reduction

所以更强的候选创新点应该是：

- `Adjoint-Aware Projector/Projection CIM Primitive`

或者更贴近电子结构语言地说：

- `Bra-Ket Fused CIM Primitive`

## 3. 负载到底在告诉我们什么

## 3.1 QE：不是只有小对角化，而是大量“project -> small transform -> back-project”

### 3.1.1 子空间路径本身就要求 paired operator

`QE` 的子空间接口明确写着：

- 调用 `h_psi`
- 调用 `s_psi`
- 保存 `H|psi>` 和 `S|psi>`
- 再在子空间里旋转 / 对角化

这在源码接口里是直接暴露出来的：

- [`ks_solver_interfaces.h`](../soft/qe-7.5/KS_Solvers/ks_solver_interfaces.h)

尤其这里已经把 primitive 轮廓写得很清楚：

- `H|psi>`
- `S|psi>`
- `hevc`
- `sevc`

所以当前我们之前提的 `{HX, SX, X^H H X, X^H S X}` 并不是拍脑袋，而是 workload 本身的直接投影。

### 3.1.2 USPP/PAW 非局域项更像“projector stationary + adjoint”

`QE` 的 `add_vuspsi` 路径其实更值得重视。  
它不是简单的 dense `GEMM`，而是明显的三段式：

1. `becp = <vkb|psi>`
2. `ps = D * becp`
3. `hpsi += vkb * ps`

在源码里可以直接看到：

- 先对 `becp` 做小矩阵乘
- 再用 `vkb` 回投到 `hpsi`

参考：

- [`add_vuspsi.f90`](../soft/qe-7.5/PW/src/add_vuspsi.f90)

这类路径的真实硬件结构，不是普通 `GEMM`，而更像：

- `project`
- `small center matrix`
- `back-project`

这和“支持 transpose”相比，层级明显更高。

### 3.1.3 EXX/ACE 路径说明 projector 常驻的复用非常夸张

仓库里已有的 `QE` 分析已经指出：

- `xi (ACE projector)` 写入次数极低
- 读取复用次数极高
- 单轮计算里接近 `1:1680` 的写读比

参考：

- [`CIM_data_residency_analysis.md`](../soft/qe-7.5/CIM_data_residency_analysis.md)

而 `vexxace` 的结构本质上也是：

- `<xi|phi>`
- 然后 `xi * coeff`

这再次说明，真正值得硬件化的不是“再造一个 GEMM”，而是：

- `forward projection + adjoint back-projection`

## 3.2 VASP：官方算法口径也在重复同一个模式

`VASP` 官方 `IALGO` 页面明确说：

- `IALGO=38` 是 blocked-Davidson

参考：

- [VASP Wiki: IALGO](https://vasp.at/wiki/IALGO)

而官方 workshop slides 对 blocked-Davidson 的分解更直接：

- optimize orbitals
- orthogonalize
- sub-space rotation

参考：

- [VASP Workshop 2024 Lecture 01A PDF](https://www.vasp.at/wiki/images/1/17/Ltmatwork24_1.1.pdf)

这说明 `VASP` 的主路径也不是“一个算子打天下”，而是反复出现：

- block update
- orthogonalization
- Rayleigh-Ritz / subspace rotation

这背后同样要求：

- conjugate transpose
- Gram / overlap build
- 小矩阵旋转
- basis back-update

所以如果只做“支持 transpose”，其实只吃到了这条链里最浅的一层。

## 3.3 PySCF：不仅有 generalized Davidson，还有更深的“共轭对 + FFT + 对称压缩”

`PySCF` 在 `pbc.df.fft_ao2mo` 里把这一点写得非常直白：

- `(G|ij) = fft[i*(r) j(r)]`
- `inverse` 路径和 `conj(...)`、交换指标是直接绑定的
- `gamma point` 下还能用对称性和 compact 存储

参考本机源码：

- [`fft_ao2mo.py`](/Users/xixilys/Library/Python/3.9/lib/python/site-packages/pyscf/pbc/df/fft_ao2mo.py)

这说明 `PySCF` 的重负载也不是简单 `GEMM`，而是：

- 先形成 orbital pair / density pair
- forward transform
- 乘一个对角或结构化 kernel
- inverse / conjugate-related transform
- 再做归约

而在本机 `pyscf.lib.linalg_helper` 里，generalized Davidson 也明确暴露了：

- `abop(x) -> (Ax, Bx)`

也就是说，`PySCF` 同时存在：

- paired-operator eigensolver 负载
- adjoint-aware pair-density / FFT 负载

## 4. 所以真正更强的创新点是什么

## 4.1 第一推荐：Adjoint-Aware Projector/Projection CIM Primitive

这是我现在最推荐的方向。

### primitive 语义

让一个常驻矩阵 / basis / projector `P` 支持下面这组操作：

- `C = P^H X`
- `T = M C`
- `Y = P T`
- 可选：`G = X^H Y`

其中：

- `P` 是常驻 basis / projector / ACE / subspace basis
- `X` 是流式输入的 block
- `M` 是片上很小的 dense 中心矩阵
  - 比如 `D`
  - `U`
  - 子空间系数矩阵
  - 或对角 `Coulomb` / 权重块

### 它覆盖什么

1. `QE` USPP / PAW 非局域项
   - `<vkb|psi>`
   - `D * becp`
   - `vkb * (...)`

2. `QE` ACE / EXX
   - `<xi|phi>`
   - `xi * coeff`

3. `QE / VASP` 子空间旋转
   - `Q^H H Q`
   - `Q^H S Q`
   - `X <- QY`

4. `PySCF` 的一部分 DF / FFTDF / AO-pair 变换
   - 虽然不完全同构，但“前向 pair 构造 + 权重 + 回归约”的骨架是一样的

### 它为什么比 transpose 更强

因为它把：

- transpose
- conjugation
- forward
- adjoint
- local reduction
- middle-matrix coupling

全部放进了同一个 workload-native primitive。

换句话说：

- `transpose` 只是这个 primitive 里的一个子机制

## 4.2 第二推荐：Hermitian Rank-k / Subspace Projection Primitive

如果你希望先收窄到更容易讲清楚、也更贴近当前已有 work 的方向，那第二个候选是：

- `Hermitian Projection CIM Primitive`

它专门支持：

- `G = X^H A X`
- `B = X^H X`
- `X <- XU`
- `X <- QY`

以及：

- Hermitian-only output
- triangular compression
- local conjugate accumulation

这个方向的优点是：

- 和现有 `QE` subspace trace 最贴
- 和 `VASP` 的 subspace rotation / orthogonalization 也对口
- 电路上更容易落成一个“局部 Hermitian accumulator + dual-view read”故事

但它的缺点也明确：

- 比 projector primitive 更窄
- 对 `PySCF` 主线覆盖没有第一种那么强

## 4.3 第三推荐：FFT-Neighbor Pair-Density Fabric

这个方向更激进，也更偏系统。

核心不是单个 `FFT`，而是：

- pair-density formation
- phase multiply
- FFT / IFFT 邻接
- conjugate pair symmetry
- grid scatter/gather / transpose

它对：

- `QE / VASP` 的 plane-wave / EXX
- `PySCF PBC FFTDF`

都很有意义。

但当前不建议把它作为第一主线，因为：

- 太大
- 太像完整数据通路重构
- 反而会把当前论文边界拉得过宽

## 5. 从电路角度，第一候选具体能创新到哪里

如果主打 `Adjoint-Aware Projector/Projection Primitive`，真正能写进芯片论文的电路点至少有这几类：

1. `projector-stationary` 存储
   - `P` 常驻
   - 不为 `P^H` 单独存一份完整转置副本

2. `dual-view / bidirectional access`
   - 同一常驻权重支持 forward 和 adjoint
   - 这里才会用到你师弟提到的 transpose 类能力
   - 但它只是机制，不是故事本体

3. `on-the-fly conjugation`
   - 对复数路径支持共轭，不是简单转置

4. `local small-matrix center`
   - 在阵列边上直接做 `M * C`
   - 避免 `P^H X` 结果大搬运后再回来

5. `Hermitian / triangular reduction`
   - 对 `X^H Y`
   - `X^H A X`
   - 只保留必要输出

6. `selective writeback`
   - 有些轮次只需要 reduced result
   - 不必把完整中间大矩阵全部写回

这套东西一旦打通，论文就不再是：

- “我们也支持 transpose”

而会变成：

- “我们定义了一个面向 projector/projection workloads 的新硬件原语”

## 6. 为什么这个点比“FP64”更像电路创新

因为它的收益来源不再主要是数值格式，而是：

- 数据流形态
- 常驻策略
- adjoint 复用
- reduction 边界
- 写回路径裁剪

也就是说，你的优势会落在：

- macro organization
- local datapath
- accumulator
- memory traffic
- control sequencing

这更像真正的 `IC innovation`。

## 7. 当前推荐排序

如果今天必须排序，我会这样排：

1. `Adjoint-Aware Projector/Projection CIM Primitive`
   - 最强主线
   - 覆盖 `QE / VASP / PySCF` 最自然
   - 也最像电路创新

2. `Hermitian Rank-k / Subspace Projection Primitive`
   - 更容易落地
   - 更适合接现有子空间工作

3. `FFT-Neighbor Pair-Density Fabric`
   - 野心最大
   - 但当前最容易把边界拉炸

## 8. 一句话判断

所以这轮更新后的判断是：

- **“transpose”不应该作为论文主创新点**
- 它最多是 `Adjoint-Aware Projector/Projection Primitive` 里的一个关键硬件机制
- 如果真想从 `QE / VASP / PySCF` 里挖一个更深、更有电路味的点，当前最值得打的是：
  - **projector-stationary**
  - **forward/adjoint fused**
  - **local reduction aware**
  - **small-center-matrix coupled**
  - 这一整套 primitive

## 9. 参考来源

### 官方 / 在线来源

- VASP Wiki: `IALGO`  
  <https://vasp.at/wiki/IALGO>
- VASP Workshop 2024 Lecture 01A PDF  
  <https://www.vasp.at/wiki/images/1/17/Ltmatwork24_1.1.pdf>
- VLSI 2025 Advance Program  
  <https://archive.vlsisymposium.org/25web/wp-content/uploads/VLSI2025_Advanceprogram0611.pdf>

### 仓库内与本机源码证据

- [`soft/qe-7.5/PW/src/add_vuspsi.f90`](../soft/qe-7.5/PW/src/add_vuspsi.f90)
- [`soft/qe-7.5/KS_Solvers/ks_solver_interfaces.h`](../soft/qe-7.5/KS_Solvers/ks_solver_interfaces.h)
- [`soft/qe-7.5/CIM_data_residency_analysis.md`](../soft/qe-7.5/CIM_data_residency_analysis.md)
- [`docs/benchmarks/qe_subspace_profile_20260312.md`](benchmarks/qe_subspace_profile_20260312.md)
- [`/Users/xixilys/Library/Python/3.9/lib/python/site-packages/pyscf/pbc/df/fft_ao2mo.py`](/Users/xixilys/Library/Python/3.9/lib/python/site-packages/pyscf/pbc/df/fft_ao2mo.py)
- [`/Users/xixilys/Library/Python/3.9/lib/python/site-packages/pyscf/lib/linalg_helper.py`](/Users/xixilys/Library/Python/3.9/lib/python/site-packages/pyscf/lib/linalg_helper.py)
