# DFT在集成电路器件与材料设计仿真中的应用调研

## 执行摘要

密度泛函理论（DFT）在集成电路（IC）器件和材料设计仿真中发挥着关键作用，主要体现在以下几个核心领域：半导体材料筛选与发现、载流子迁移率计算、载流子输运性质模拟、以及器件-level的量子力学建模。DFT通过求解Kohn-Sham方程，能够从第一性原理出发预测材料的电子结构、带隙、态密度、载流子有效质量、晶格振动性质等关键参数，这些参数直接决定了IC器件的性能。本调研基于本地paper_db数据库中的学术论文和VLSI Symposium最新研究成果，系统梳理了DFT在IC材料和器件设计中的应用现状。

## 1. 研究背景与动机

### 1.1 集成电路材料工程的核心挑战

集成电路制造正处于后摩尔时代的转型期。根据VLSI Symposium 2022-2025的研究，先进制程的持续演进依赖于材料创新、器件结构优化和系统架构协同设计的三重驱动[1][2]。Materials-to-Systems™策略要求从原子级材料控制出发，实现性能、功耗、面积、成本（PPACt）的协同优化[3]。

IC材料工程面临的核心挑战包括：
- 高迁移率沟道材料的选择与优化（Ge、InGaAs、氧化物半导体等）
- 超低功耗器件的界面工程与缺陷控制
- 先进制程中的BEOL兼容材料开发
- 3D堆叠和CFET架构对新材料的需求

DFT作为"计算显微镜"，能够在原子尺度揭示材料性质的本质，为实验提供理论指导和预测能力。

### 1.2 DFT在IC领域的定位

DFT在IC材料设计中的核心价值在于其**第一性原理预测能力**：
- 无需经验参数即可计算材料电子结构
- 能够预测新材料的性质（高通量筛选）
- 可解释实验现象的物理本源
- 为经验模型和TCAD仿真提供参数

## 2. DFT在半导体材料设计中的应用

### 2.1 高迁移率沟道材料

VLSI Symposium 2021-2025展示了大量关于高迁移率沟道材料的研究，这些研究背后都有DFT计算的支撑。

#### 2.1.1 氧化物半导体

氧化物半导体（如InGaZnO、In₂O₃、ITO等）因其BEOL兼容性和高迁移率成为研究热点[4][5][6]：

**In₂O₃基器件（VLSI 2021）**
- ALD沉积的In₂O₃ FinFET实现113 cm²/V·s的迁移率
- 3D Fin结构的高迁移率展示了DFT辅助材料工程的价值
- 关键材料参数：态密度有效质量、载流子浓度

**InGaZnO基器件（VLSI 2023-2024）**
- Sn掺杂InGaZnO实现110 cm²/V·s的有效迁移率
- ITO-IGZO异质结通道实现自缺陷补偿[7]
- 迁移率对沟道厚度的独立性行为需要DFT解释

**Ge掺杂In₂O₃（VLSI 2024）**
- Ge作为氧空位消费者打破迁移率-可靠性trade-off
- DFT计算揭示了Ge在In₂O₃中的掺杂机制和电子结构效应

#### 2.1.2 Ge和SiGe材料

Ge因其高空穴迁移率（~3倍于Si）在CFET和GAA架构中备受关注[8][9]：

**GOI和SGOI pMOSFETs（VLSI 2018）**
- 通过Ge浓缩法实现~1.75%压缩应变
- 10nm厚GOI pMOSFETs的空穴迁移率达到467 cm²/V·s
- 应变诱导的带结构变化需要DFT计算验证

**Ge(110) GAA Nanosheet CFETs（VLSI 2024）**
- 创纪录的空穴迁移率
- 异质取向n-Ge(111)/p-Ge(100)堆叠实现迁移率平衡工程

#### 2.1.3 III-V族化合物

**InGaAs FinFETs（VLSI 2019）**
- sub-10nm fin宽度InGaAs FinFETs的迁移率重评估
- 发现了氧化层 trapping导致的表观性能退化
- DFT计算辅助理解界面态对迁移率的影响[10]

**Cryogenic InGaAs QW HEMTs（VLSI 2025）**
- 应用于量子计算和太赫兹频段
- 低温下的迁移率机制需要DFT辅助分析

### 2.2 DFT加速：机器学习与硬件协同设计

DFT计算的主要瓶颈在于其O(N³)计算复杂度与Kohn-Sham方程求解的高昂成本。当前主要有三条加速路径：

#### 2.2.1 机器学习替代模型

**Neural-network DFT（PRL 2024）**
- 将神经网络与变分能量最小化统一
- 实现无监督学习框架
- 自动微分和反向传播算法引入DFT[11]

**ML DFT加速Finite-temperature DFT（PRB 2021）**
- 深度神经网络预测有限电子温度下的态密度
- 成本降低数个数量级
- 适用于固体和液体金属[12]

**Deep learning emulated DFT（npj Computational Materials 2023）**
- 端到端ML模型从原子结构预测电荷密度
- 速度提升：与系统规模线性标度
- 保持化学精度[13]

**SCFbench数据集（2025）**
- E(3)等变神经网络预测电子密度
- 平均SCF步数减少33.3%
- 跨基组和XC泛函的强迁移性[14]

#### 2.2.2 硬件/软件协同设计

**NDFT：Near-Data Computing加速DFT（2025）**
- 针对线性响应TDDFT的硬件/软件协同设计
- 解决host-memory与device-memory数据移动开销
- 计算步骤本质上是memory-bound[15]

### 2.3 高通量筛选与数据驱动材料发现

**MXenes for氢 generation（2022）**
- ML+DFT筛选4500种MM'XT₂型MXenes
- 随机森林回归预测ΔG_H，MAE仅0.374 eV
- 发现Nb、V、Mo、Cr、Ti基催化剂性能超越Pt[16]

**2D材料STM图像数据库（2024）**
- 基于DFT的扫描隧道显微镜图像数据库
- 716种可剥离2D材料
- CNN模型从STM图像识别Bravais格子[17]

**Li/Na离子电池材料电压预测（2025）**
- DNN模型预测电池材料电压
- 结合Materials Project数据集
- DFT验证确认预测准确性[18]

## 3. 载流子迁移率计算

### 3.1 迁移率的物理基础与DFT方法

载流子迁移率μ由散射机制决定：
```
μ = qτ/m*
```
其中τ为散射时间，m*为有效质量，q为载流子电荷。

DFT在迁移率计算中的核心作用：

1. **有效质量计算**：从能带结构通过曲率提取
2. **散射机制分析**：声子散射、缺陷散射、界面散射
3. **晶格振动性质**：声子谱、比热、热导率

### 3.2 第一性原理迁移率计算方法

#### 3.2.1 Boltzmann输运方程（BTE）方法

基于BTE的迁移率计算流程：
1. DFT计算电子能带结构
2. DFPT计算声子谱和电声子耦合
3. 求解BTE得到迁移率

**CPA（coherent potential approximation）**
- 处理无序合金的迁移率
- 适用于半导体合金如SiGe、InGaAs

#### 3.2.2 Kubo-Greenwood公式

基于线性响应理论的迁移率计算：
```
σ(ω) = (2πe²/h) Σ ∫ dE A(E) A(E+ħω) [f(E) - f(E+ħω)]
```

### 3.3 VLSI器件中的迁移率工程

#### 3.3.1 应变工程

**应变Si/Ge沟道**
- 单轴/双轴应变调节带结构和迁移率
- DFT计算应变-迁移率关系

**GOI中空穴迁移率增强（VLSI 2018）**
- Ge浓缩产生~1.75%压缩应变
- 10nm厚GOI中μh达467 cm²/V·s
- 应变维持到2nm厚度[8]

#### 3.3.2 量子限制效应

**GAA Nanosheet FETs（VLSI 2024-2025）**
- InGaOx、InZnO、InGaO等氧化物GAA结构
- 亚100nm栅长度实现不饱和载流子速度
- 量子限制效应需要DFT解释[19][20]

#### 3.3.3 界面工程

**SnO p型FET（VLSI 2024）**
- 新型p型氧化物半导体
- 界面缺陷密度决定迁移率

**HZO基高k栅介质（VLSI 2024）**
- In₂O₃ FET使用HZO基线性介质
- 迁移率达152 cm²/V·s
- 界面偶极子工程影响迁移率[21]

### 3.4 低温迁移率与量子限制

**Cryogenic MOSFET迁移率（VLSI 2022）**
- 导带底边缘态对Coulomb限制电子迁移率的影响
- (100)、(120)、(110)晶向Si n-MOSFETs在低温下迁移率显著不同
- 费米能级通过高密度局域化trap态时温度特性发生变化[22]

## 4. 载流子输运性质

### 4.1 弹道输运与准弹道输运

#### 4.1.1 Landauer-Büttiker公式

对于纳米尺度器件，弹道输运框架：
```
G = (2e²/h) * T(E_F)
```
其中T(E_F)为费米能级的透射系数。

#### 4.1.2 Non-Equilibrium Green's Function (NEGF) + DFT

**NEGF-DFT框架**
- DFT提供器件区域的电子结构
- NEGF处理开放边界条件
- 自能项处理电极耦合

**代表性工作**
- 量子点接触、分子电子学
- 2D材料FETs（MoS₂、WS₂等）

### 4.2 时间相关DFT（TDDFT）与非平衡态

**TDDFT for stopping power（npj Computational Materials 2024）**
- 电子阻止功率的第一性原理计算
- 质子辐照Al中Bragg Peak角度依赖性
- ML+TDDFT实现10百万倍加速[23]

**ML时间传播子 for TDDFT（2025）**
- 自回归神经算子作为电子密度时间传播器
- 物理信息约束和高分辨率训练数据
- 激光照射分子和材料的实时建模[24]

### 4.3 隧穿器件与隧穿输运

**FeFET和隧穿器件（VLSI 2023-2024）**
- 隧穿电致电阻比（TER）达2×10⁴
- 氧化物半导体-铪基自整流铁电隧穿结
- 隧穿概率的量子力学计算[25][26]

## 5. DFT与TCAD/器件仿真的集成

### 5.1 Compact Model与TCAD的DFT参数化

**Industry Standard Compact Model Integrating TCAD into SPICE（VLSI 2024）**
- DFT计算为compact model提供物理参数
- TCAD校准与SPICE模型的集成[27]

**DTCO中的Realistic Scalable TCAD（VLSI 2025）**
- 用于良率感知的全芯片DTCO
- DFT提供的基础物理参数[28]

### 5.2 从DFT到器件的桥梁

**参数提取流程**
1. DFT计算：带隙、有效质量、介电常数、声子频率
2. 物理建模：迁移率模型、散射率
3. TCAD仿真：器件静电学、量子效应
4. Compact Model：电路仿真参数

### 5.3 多尺度方法

**Quantum-Continuum跨尺度建模**
- DFT提供原子尺度参数
- 连续介质力学处理宏观结构
- ML加速跨尺度传递

## 6. 典型应用案例

### 6.1 案例一：氧化物半导体FET迁移率优化

**问题**：a-OSFETs的亚阈值摆幅过渡区（VTR）过宽（160mV-1.1V），限制低功耗应用。

**DFT作用**：
1. 识别a-OS通道中浅traps的来源
2. 通过Ga掺杂工程调控载流子浓度
3. 界面偶极子设计影响VTR

**结果**：crystalline channel FETs的VTR<80mV，性能接近理论极限[29]。

### 6.2 案例二：3D堆叠CFET的迁移率平衡

**问题**：n-FET和p-FET的迁移率不匹配限制CFET性能。

**DFT作用**：
1. 计算异质取向Ge的能带结构
2. 应变分布预测
3. 载流子有效质量各向异性

**结果**：垂直堆叠n-Ge(111)/p-Ge(100)实现迁移率平衡工程[30]。

### 6.3 案例三：BEOL兼容高迁移率材料

**问题**：传统沟道材料不兼容BEOL工艺温度（<400°C）。

**DFT辅助筛选**：
1. ALD In₂O₃的稳定性计算
2. 掺杂效应（Ge、Ga、Sn）预测
3. 界面缺陷形成能计算

**结果**：BEOL兼容In₂O₃ FET实现113-152 cm²/V·s迁移率[4][21]。

## 7. 当前挑战与局限

### 7.1 计算精度与成本的矛盾

**交换-相关泛函的局限**
- LDA/GGA低估带隙
- Hybrid泛函（HSE06）成本高3-4个数量级
- GW校正可改善但成本更高

**强关联体系**
- d/f电子体系的精确描述
- 过渡金属氧化物的多体效应

### 7.2 标度性问题

**从单元胞到器件**
- DFT典型处理100-1000原子
- 实际器件包含millions原子
- 需要多尺度桥接

### 7.3 动力学与温度效应

**有限温度DFT**
- smearing技术的合理性
- 热振动自由能的精确计算
- 温致相变

## 8. 前沿发展方向

### 8.1 机器学习DFT（ML-DFT）

**端到端学习框架**
- 从原子结构直接预测性质
- 保持第一性原理精度
- 线性标度计算成本

**代表性工作**
- DeepH-pack：通用神经网络电子结构包（2026）[31]
- Neural-network DFT：变分能量最小化统一框架（2024）[11]

### 8.2 量子计算与DFT

**量子计算DFT**
- VQE（变分量子特征值求解器）处理电子结构
- 量子机器学习加速DFT
- 未来中等噪声量子硬件（NISQ）潜力

### 8.3 自动化工作流

**Materials Project风格的高通量筛选**
- 自动化DFT计算流程
- 数据驱动材料发现
- 与实验闭环

### 8.4 实时DFT与器件运行

**On-the-fly DFT**
- 分子动力学中的实时能量评估
- 自适应活性能计算
- 器件老化的动态模拟

## 9. 结论

DFT在集成电路器件和材料设计仿真中扮演着不可或缺的角色。通过第一性原理计算，DFT能够：

1. **预测**半导体材料的电子结构、带隙、载流子有效质量
2. **解释**实验观察到的迁移率、稳定性等性质的物理本源
3. **筛选**新型高迁移率沟道材料和BEOL兼容材料
4. **桥接**原子尺度理论与器件尺度仿真

当前的主要趋势包括：
- **ML-DFT融合**：机器学习加速DFT计算，保持精度的同时大幅降低成本
- **硬件协同设计**：NDFT等专用架构针对DFT特性优化
- **高通量筛选**：加速新材料的发现和优化
- **多尺度集成**：DFT与TCAD、compact model的层级化整合

对于IC材料设计的未来，DFT将继续作为"计算显微镜"的角色，在后摩尔时代的新型器件（CFET、GAA、氧化物半导体、2D材料等）的研发中发挥关键作用。

## 参考来源

### 本地paper_db数据库论文

[1] "Holistic Patterning to Advance Semiconductor Manufacturing in the 2020s and Beyond", VLSI 2022
[2] "Semiconductor Innovations, from Device to System", VLSI 2022
[3] "Materials to Systems in Semiconductor Manufacturing and Beyond", VLSI 2024
[4] "First Demonstration of Atomic-Layer-Deposited BEOL-Compatible In2O3 3D Fin Transistors", VLSI 2021
[5] "First Demonstration of BEOL-Compatible Write-Enhanced Ferroelectric-Modulated Diode", VLSI 2023
[6] "Ultra-high Tunneling Electroresistance Ratio in Oxide Semiconductor-Hafnia Ferroelectric Tunnel Junction", VLSI 2023
[7] "Overcoming Negative nFET VTH by Defect-Compensated Low-Thermal Budget ITO-IGZO Hetero-Oxide Channel", VLSI 2023
[8] "Hole mobility enhancement in extremely-thin-body strained GOI and SGOI pMOSFETs", VLSI 2018
[9] "Ge(110) GAA Nanosheet Si(100) Tri-gate Nanosheet Monolithic CFETs", VLSI 2024
[10] "Reassessing InGaAs for Logic Mobility Extraction in sub-10nm Fin-Width FinFETs", VLSI 2019
[11] "Neural-network Density Functional Theory Based on Variational Energy Minimization", PRL 2024
[12] "Accelerating Finite-temperature Kohn-Sham Density Functional Theory with Deep Neural Networks", PRB 2021
[13] "A deep learning framework to emulate density functional theory", npj Computational Materials 2023
[14] "Towards A Universally Transferable Acceleration Method for Density Functional Theory", 2025
[15] "NDFT: accelerating density functional theory calculations via hardware/software Co-design", 2025
[16] "Fusing machine learning strategy with density functional theory to hasten the discovery of MXenes", 2022
[17] "Density Functional Theory and Deep-learning to Accelerate Data Analytics in Scanning Tunneling Microscopy", 2024
[18] "Integrating Density Functional Theory with Deep Neural Networks for Accurate Voltage Prediction", 2025
[19] "Scaling Potential of Nanosheet Oxide Semiconductor FETs for Monolithic 3D Integration", VLSI 2024
[20] "A Gate-All-Around Nanosheet Oxide Semiconductor Transistor", VLSI 2025
[21] "Enhancement of In2O3 Field-Effect Mobility Up To 152 cm2V−1s−1Using HZO-Based Higher-k Linear Dielectric", VLSI 2024
[22] "Effect of Conduction Band Edge States on Coulomb-Limiting Electron Mobility in Cryogenic MOSFET Operation", VLSI 2022
[23] "Accelerating multiscale electronic stopping power predictions with time-dependent density functional theory and machine learning", npj Computational Materials 2024
[24] "Machine Learning Time Propagators for Time-Dependent Density Functional Theory Simulations", 2025
[25] "Ultra-high Tunneling Electroresistance Ratio & Endurance in Oxide Semiconductor-Hafnia Ferroelectric Tunnel Junction", VLSI 2023
[26] "First Demonstration of BEOL-Compatible Write-Enhanced Ferroelectric-Modulated Diode", VLSI 2023
[27] "A New Industry Standard Compact Model Integrating TCAD Into SPICE", VLSI 2024
[28] "Realistic and Scalable TCAD for Yield-Aware Full-Chip DTCO", VLSI 2025
[29] "Key to Low Supply Voltage Transition Region of Oxide Semiconductor Transistors", VLSI 2025
[30] "First Demonstration of Vertical Stacked Hetero-Oriented n-Ge(111) p-Ge(100) CFET", VLSI 2022
[31] "DeepH-pack: A general-purpose neural network package for deep-learning electronic structure calculations", 2026

### 补充来源

- Quantum ESPRESSO User Guide 7.5.0: https://www.quantum-espresso.org/Doc/user_guide/node2.html
- VASP Wiki: https://www.vasp.at/wiki/
- PySCF Documentation: https://pyscf.org/
- Materials Project: https://materialsproject.org/
- JARVIS-DFT: https://www.ctcms.nist.gov/~knc6/JVASP.html

---

*本报告生成于 2026-03-31，基于本地paper_db数据库（截至2026-03-31的论文记录）和VLSI Symposium 2018-2025会议论文。*
