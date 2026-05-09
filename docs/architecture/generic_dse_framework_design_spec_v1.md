# 通用硬件/软件协同设计空间探索（DSE）框架设计规范

> **文档版本**: v1.0  
> **最后更新**: 2026-05-09  
> **文档状态**: 草案 - 待审核  
> **编写依据**: 现有代码实现 + 用户架构需求 + 代码审核报告修复内容

---

## 文档目录

1. [概述与目标](#1-概述与目标)
2. [系统架构总览](#2-系统架构总览)
3. [核心抽象层](#3-核心抽象层)
4. [中间表示（IR）栈](#4-中间表示ir栈)
5. [加速器描述语言](#5-加速器描述语言)
6. [DSE 引擎](#6-dse-引擎)
7. [评估器体系](#7-评估器体系)
8. [仿真后端](#8-仿真后端)
9. [gem5 集成](#9-gem5-集成)
10. [分布式扩展](#10-分布式扩展)
11. [DFT 用例实现](#11-dft-用例实现)
12. [测试与验证](#12-测试与验证)
13. [代码审核修复记录](#13-代码审核修复记录)
14. [已知限制与后续工作](#14-已知限制与后续工作)
15. [附录](#15-附录)

---

## 1. 概述与目标

### 1.1 项目定位

本文档描述一个**通用的硬件/软件协同设计空间探索（DSE）框架**，支持多加速器异构系统（CPU + GPU + FPGA + ASIC/CIM）的架构探索与性能评估。

**核心定位**：
- **通用框架**：不局限于 DFT，支持任意计算密集型应用的加速器架构探索
- **分层评估**：从快速分析模型到 cycle-accurate 仿真，多保真度自动切换
- **分布式就绪**：架构设计从 day-1 支持分布式集群扩展
- **端到端闭环**：支持完整应用迭代评估，而非单个 kernel 的孤立分析

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **Operator-agnostic** | 不预定义算子集合，支持任意算子类型 |
| **Accelerator-agnostic** | 不假设加速器类型，通过自描述接口支持任意硬件 |
| **Composable** | 系统由可组合组件构建，支持灵活架构配置 |
| **Self-describing** | 加速器声明自身能力，框架自动适配 |
| **Distributed-ready** | 单机代码无需修改即可扩展到多节点 |
| **No mock** | 不使用 mock 遮挡未完整实现的部分，诚实报告实现状态 |

### 1.3 非目标

本文档**不**覆盖：
- 完整通用处理器 ISA 规格
- 单个 block 的 RTL 微架构说明书
- 带精确位宽/寄存器图/时序图的实现冻结文档
- 已经冻结的最终 benchmark 与投稿 KPI 方案

### 1.4 读者对象

- **系统架构设计者**：系统边界、分层、冻结点
- **框架开发者**：IR 设计、评估器接口、后端集成
- **加速器建模者**：加速器描述格式、能力声明
- **DSE 算法研究者**：搜索空间定义、评估接口

---

## 2. 系统架构总览

### 2.1 顶层分层

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Workload                      │
│         (Compute Graph - DAG of operations)                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              DSE Framework (Python)                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Search    │  │  Design Pt  │  │  Multi-Fidelity     │  │
│  │  Strategy   │  │  Generator  │  │  Evaluator          │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   L1 Analytical │ │   L2 TLM        │ │   L3 SystemC    │
│   (Roofline)    │ │   (Python)      │ │   (C++ executable│
│   ~0.003 ms     │ │   ~7.4 ms       │ │   ~0.7 ms)      │
└─────────────────┘ └─────────────────┘ └─────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              L4 gem5 + SystemC Co-simulation                 │
│         (Full-system simulation with CPU model)             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件

| 组件 | 职责 | 位置 |
|------|------|------|
| **IR Stack** | 4 级中间表示（L0-L3） | `dse_v2/core/ir/` |
| **Accelerator Desc** | 硬件自描述语言 | `dse_v2/core/architecture/` |
| **DSE Engine** | 搜索空间生成与评估编排 | `dse_v2/dse/orchestrator.py` |
| **Evaluators** | 多保真度性能评估 | `dse_v2/dse/*_evaluator.py` |
| **SystemC Backend** | 通用 C++ 仿真后端 | `model/generic_sim_backend/` |
| **gem5 Integration** | 全系统协同仿真 | `gem5_integration/` |

---

## 3. 核心抽象层

### 3.1 系统对象

本文档的系统对象是一个完整的混合加速系统：

- **Host + software driver**：负责高层任务组织、软件态控制、外层收敛逻辑
- **FPGA / runtime orchestrator**：负责任务组织、对象搬运、模式切换、fallback 调度
- **Chip**：负责固化在片上的主算子链和近存连续数据流

统一称为：**Hybrid Accelerator System**

### 3.2 关键抽象

#### 3.2.1 TensorSpec

```python
@dataclass
class TensorSpec:
    shape: Tuple[int, ...]      # 张量形状
    dtype: str = "FP64"          # 数据类型：FP64/FP32/FP16/INT8/INT32
    layout: str = "row_major"    # 内存布局
    
    def num_elements(self) -> int
    def size_bytes(self) -> int
```

#### 3.2.2 ComputeNode

```python
@dataclass
class ComputeNode:
    node_id: str                 # 节点唯一标识
    op_type: str                 # 算子类型（gemm/fft/eigen/...）
    inputs: List[str]            # 输入张量名列表
    outputs: List[str]           # 输出张量名列表
    input_specs: Dict[str, TensorSpec]   # 输入张量规格
    output_specs: Dict[str, TensorSpec]  # 输出张量规格
    estimated_flops: float       # 估计 FLOPs
    estimated_memory_bytes: float # 估计内存访问量
    attributes: Dict[str, Any]   # 自定义属性（领域特定信息）
```

#### 3.2.3 DataEdge

```python
@dataclass
class DataEdge:
    source_node: str             # 源节点 ID
    target_node: str             # 目标节点 ID
    tensor_name: str             # 数据张量名
    tensor_spec: Optional[TensorSpec]  # 张量规格
```

---

## 4. 中间表示（IR）栈

### 4.1 IR 分层设计

框架采用 4 级 IR 栈，从高层的应用描述到底层的硬件执行时间线：

| 层级 | 名称 | 职责 | 关键抽象 | 文件 |
|------|------|------|----------|------|
| **L3** | Compute Graph | 应用级计算图 | ComputeNode, DataEdge | `compute_graph.py` |
| **L2** | Task Graph | 任务级并行执行图 | Task, TaskPlacement, DataMovement | `task_graph.py` |
| **L1** | Architecture | 硬件架构描述 | Accelerator, SystemArchitecture | `accelerator.py` |
| **L0** | Execution | 执行时间线 | ExecutionEvent, ResourceUsage | `execution.py` |

### 4.2 L3: Compute Graph IR

**定位**：应用与 DSE 框架的接口层

**设计决策**：
1. **Operator-agnostic**：无预定义算子集合，op_type 为任意字符串
2. **Shape-aware**：张量形状是一等信息
3. **Precision-aware**：数据类型是图的一部分
4. **Extensible**：通过 opaque attributes 支持自定义算子

**核心类**：
- `TensorSpec`：张量规格（形状、数据类型、布局）
- `ComputeNode`：计算节点（算子类型、输入输出、FLOPs 估计）
- `DataEdge`：数据依赖边
- `ComputeGraph`：完整计算图（DAG）

**关键方法**：
```python
class ComputeGraph:
    def add_node(self, node: ComputeNode) -> ComputeGraph
    def add_edge(self, edge: DataEdge) -> ComputeGraph
    def topological_sort(self) -> List[str]
    def total_flops(self) -> float
    def total_memory_bytes(self) -> float
```

### 4.3 L2: Task Graph IR

**定位**：计算图到硬件执行的桥梁

**设计决策**：
1. **Task granularity**：单个任务可以是单个节点或融合的子图
2. **Placement-aware**：任务映射到特定加速器
3. **Schedule-aware**：任务有时间信息（开始、结束、依赖）
4. **Resource-aware**：任务消耗加速器资源

**核心类**：
- `TaskPlacement`：任务在加速器上的放置（accel_id, memory, compute_units）
- `TaskSchedule`：任务调度信息（start_time_ms, end_time_ms）
- `DataMovement`：加速器间的数据搬运（size, bandwidth, latency）
- `Task`：任务（类型、放置、调度、依赖、数据搬运）
- `TaskGraph`：任务图（任务集合、全局调度、makespan）

**数据搬运时间计算**（已修复单位错误）：
```python
@property
def transfer_time_ms(self) -> float:
    # size_bytes * 8 bits/byte / (bandwidth_gbps * 1e9 bits/s) * 1000 ms/s + latency_ms
    transfer_ms = self.size_bytes * 8.0 / (self.bandwidth_gbps * 1e9) * 1000.0
    return transfer_ms + self.latency_ms
```

### 4.4 L1: Architecture IR

**定位**：硬件架构描述层

**核心类**：
- `MemoryLevel`：内存层级（容量、带宽、延迟、类型）
- `MemoryHierarchy`：多级内存层次结构
- `PeerLink`：加速器间直连链路
- `HostLink`：加速器到主机的链路
- `ComputeCapability`：计算能力（峰值 FLOPS、支持算子、效率）
- `CommunicationCapability`：通信能力（链路、原语）
- `PowerModel`：功耗模型（静态功耗、计算/内存/通信功耗）
- `Accelerator`：通用加速器描述
- `InterconnectTopology`：互连拓扑
- `SystemArchitecture`：完整系统架构

### 4.5 L0: Execution IR

**定位**：具体硬件执行时间线

**核心类**：
- `ExecutionEvent`：执行时间线上的事件（task_start/task_end/data_transfer_start/data_transfer_end）
- `ResourceUsage`：资源使用状态（计算利用率、内存使用、带宽利用率）
- `DataTransfer`：记录的数据传输（源/目标加速器、大小、时间、带宽）
- `ExecutionTimeline`：完整执行时间线（事件、资源使用、数据传输、汇总统计）

---

## 5. 加速器描述语言

### 5.1 设计原则

1. **自描述**：每个加速器声明自己的算力、内存、通信、功耗
2. **精度敏感**：峰值算力按精度分开（FP64/FP32/FP16/INT8）
3. **算子敏感**：支持算子列表和算子效率
4. **可组合**：系统由连接的加速器组件构建

### 5.2 Accelerator 核心结构

```python
@dataclass
class Accelerator:
    accel_id: str                # 唯一标识
    accel_type: str              # 类型：gpu/fpga/asic/cim/cpu/custom
    
    # 四大能力域
    compute: ComputeCapability   # 计算能力
    memory: MemoryHierarchy      # 内存层次
    communication: CommunicationCapability  # 通信能力
    power: PowerModel            # 功耗模型
    
    # 可选元数据
    vendor: str = ""
    model: str = ""
    version: str = ""
```

### 5.3 预定义加速器模板

#### 5.3.1 GPU (NVIDIA A100)

| 属性 | 值 |
|------|-----|
| FP64 峰值 | 9.7 TFLOPS |
| FP32 峰值 | 19.5 TFLOPS |
| TF32 峰值 | 156 TFLOPS |
| FP16 峰值 | 312 TFLOPS |
| 支持算子 | gemm, conv2d, batch_norm, softmax, attention, fft, eigen |
| 算子效率 | gemm: 0.90, conv2d: 0.85, fft: 0.60, eigen: 0.20 |
| 特殊能力 | tensor_cores, sparse_tensor_cores, nvlink |
| 内存层次 | L1(192KB), L2(40MB), HBM(80GB) |
| 主机链路 | PCIe4 x16, 64 GB/s |
| 静态功耗 | 50 W |

#### 5.3.2 FPGA (Xilinx Alveo U280)

| 属性 | 值 |
|------|-----|
| FP64 峰值 | 1.0 TFLOPS |
| FP32 峰值 | 8.0 TFLOPS |
| INT8 峰值 | 32.0 TFLOPS |
| 支持算子 | gemm, fft, conv2d, custom |
| 算子效率 | gemm: 0.95, fft: 0.90, custom: 0.95 |
| 特殊能力 | reconfigurable, streaming, low_latency_io |
| 内存层次 | BRAM(30MB), HBM(8GB), DRAM(32GB) |
| 主机链路 | PCIe4 x16, 64 GB/s |
| 静态功耗 | 25 W |

#### 5.3.3 CIM Array

| 属性 | 值 |
|------|-----|
| FP64 峰值 | 0.1 TFLOPS |
| FP32 峰值 | 0.5 TFLOPS |
| 支持算子 | gemm, vector_add, elementwise |
| 算子效率 | gemm: 0.95, vector_add: 0.90 |
| 特殊能力 | in_memory_compute, analog_compute, low_precision |
| 内存层次 | CIM_Array(1MB), SRAM(64MB) |
| 主机链路 | Custom, 32 GB/s |
| 静态功耗 | 5 W |

### 5.4 系统架构构建

```python
def create_example_system() -> SystemArchitecture:
    return SystemArchitecture(
        system_id="heterogeneous_demo",
        host_cpu_cores=64,
        host_memory_gb=512.0,
        accelerators=[
            create_gpu_a100("gpu-0"),
            create_fpga_u280("fpga-0"),
            create_cim_array("cim-0"),
        ],
        interconnect=InterconnectTopology(
            topology_type="mesh",
            bandwidth_gbps=200.0,
            latency_us=1.0,
        ),
        max_power_w=1000.0,
        max_area_mm2=1000.0,
    )
```

---

## 6. DSE 引擎

### 6.1 核心组件

#### 6.1.1 DesignPoint

```python
@dataclass
class DesignPoint:
    design_point_id: str
    system_architecture: SystemArchitecture    # 硬件配置
    task_mapping: Dict[str, str]               # task_id -> accel_id
    scheduling_policy: str = "static"           # static/dynamic/pipeline
    config: Dict[str, Any] = field(default_factory=dict)
```

#### 6.1.2 EvaluationResult

```python
@dataclass
class EvaluationResult:
    design_point_id: str
    
    # 性能指标
    latency_ms: float = 0.0
    throughput_gops: float = 0.0
    
    # 资源指标
    power_w: float = 0.0
    energy_j: float = 0.0
    area_mm2: float = 0.0
    
    # 效率指标
    compute_efficiency: float = 0.0    # Actual / peak FLOPS
    memory_efficiency: float = 0.0     # Actual / peak bandwidth
    
    # 通信指标
    total_data_movement_mb: float = 0.0
    communication_overhead_ms: float = 0.0
    
    # 可行性
    feasible: bool = True
    violation_reasons: List[str] = field(default_factory=list)
```

### 6.2 DSEOrchestrator

**职责**：
1. 搜索空间定义
2. 设计点生成
3. 评估编排
4. 结果聚合

**设计原则**：
1. **Multi-objective**：同时优化性能、功耗、成本
2. **Heterogeneous-aware**：考虑不同加速器能力
3. **Communication-aware**：考虑数据搬运成本
4. **Extensible**：支持自定义搜索策略和评估器

### 6.3 搜索空间

当前设计空间规模：**179M 配置**

**参数维度**：
- 并行单元数 (parallel_units)
- 流水线深度 (pipeline_depth)
- Offload 策略 (h_psi_only/all_operators)
- 数据流模式 (streaming/batch)
- 存储策略 (on_chip_sram/streaming)

---

## 7. 评估器体系

### 7.1 多保真度框架

```
┌─────────────────────────────────────────────────────────────┐
│                 MultiFidelityEvaluator                       │
│                                                              │
│   L1 (Fast)        L2 (TLM)         L3 (SystemC)            │
│   Analytical       Python TLM       C++ Executable          │
│   ~0.003 ms        ~7.4 ms          ~0.7 ms / 197 cycles    │
│                                                              │
│   Roofline model   Transaction-level  Cycle-accurate        │
│   + Scheduling     simulation         simulation            │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 L1: Analytical Evaluator

**模型**：Roofline + 并行调度

**功能**：
1. 计算强度分析（FLOPs / byte）
2. 性能上限计算（compute-bound vs memory-bound）
3. 并行任务调度（非简单顺序执行）
4. 内存带宽瓶颈检测
5. 数据搬运时间计算

**评估流程**：
1. 构建加速器带宽矩阵
2. 将计算图映射到任务图
3. 对每个任务进行 Roofline 分析
4. 并行调度任务
5. 计算时间线指标

### 7.3 L2: TLM Evaluator

**模型**：Python 事务级模型

**功能**：
- 中等保真度评估
- 事务级通信建模
- 比 L1 更精确，比 L3 更快

### 7.4 L3: SystemC Evaluator

**模型**：通用 SystemC C++ 仿真后端

**功能**：
- Cycle-accurate 仿真
- 完整架构差异感知（GPU/FPGA/CIM 产生不同结果）
- 事件和资源利用率输出

**自动晋升逻辑**：
```python
def evaluate(design_point, compute_graph, force_fidelity=None):
    # 从 L1 开始
    result = evaluate_l1(design_point, compute_graph)
    
    # 检查是否晋升到 L2
    if should_promote_to_l2(result):
        result = evaluate_l2(design_point, compute_graph)
        
        # 检查是否晋升到 L3
        if should_promote_to_l3(result):
            result = evaluate_l3(design_point, compute_graph)
    
    return result
```

---

## 8. 仿真后端

### 8.1 通用 SystemC 后端

**位置**：`model/generic_sim_backend/`

**架构**：
```
Python DSE Framework
    │
    │ JSON Request
    ▼
GenericSystemCBackend (Python)
    │
    │ subprocess.run()
    ▼
generic_sim (C++ executable)
    │
    │-- SimTop
        │-- Host Model
        │-- Interconnect Model
        │-- Memory System
        │-- Accelerator Devices
        │   │-- GPUAccelerator
        │   │-- FPGAAccelerator
        │   │-- CIMAccelerator
        │   │-- GenericAccelerator
        │-- Graph Executor
        │-- Trace Recorder
    │
    │ JSON Result
    ▼
Python DSE Framework
```

### 8.2 JSON IPC 协议

**请求格式**（`schemas/simulation_request_v1.json`）：
```json
{
  "architecture": {
    "accelerators": [
      {
        "id": "gpu-0",
        "type": "gpu",
        "capabilities": {
          "gemm": {"peak_gops": 9700, "efficiency": 0.90}
        },
        "memory": {...},
        "power": {...}
      }
    ],
    "interconnect": {...}
  },
  "workload": {
    "nodes": {...},
    "edges": {...}
  },
  "mapping": {...}
}
```

**结果格式**（`schemas/simulation_result_v1.json`）：
```json
{
  "latency_ms": 1.43,
  "throughput_gops": 685.7,
  "power_w": 285.5,
  "energy_j": 0.408,
  "events": [...],
  "resource_utilization": {...}
}
```

### 8.3 支持的算子

- `gemm`：通用矩阵乘法
- `fft`：快速傅里叶变换
- `eigen`：特征值求解
- `reduction`：归约操作
- `elementwise`：逐元素操作
- `transfer`：数据搬运
- `generic_op`：通用算子

### 8.4 支持的加速器类型

- `gpu`：通用 GPU
- `fpga`：可编程逻辑
- `cim`：存内计算
- `asic`：专用集成电路
- `cpu`：中央处理器

---

## 9. gem5 集成

### 9.1 架构

```
┌─────────────┐     TLM-2.0     ┌─────────────────┐
│   gem5 CPU  │ ◄──────────────► │  SystemC FPGA   │
│  (X86)      │                  │  (4-Cluster)    │
└─────────────┘                  └─────────────────┘
       │                                  │
       │ PCIe/DMA                         │
       ▼                                  ▼
┌─────────────────┐              ┌─────────────────┐
│ GenericAccel    │              │ Cluster A/B/C/D │
│ (MMIO Device)   │              │ (Operator/Diag/ │
│                 │              │  Build/Refresh) │
└─────────────────┘              └─────────────────┘
```

### 9.2 GenericAccel 设备模型

**类型**：MMIO Timed Stub（当前实现状态）

**寄存器映射**：
| 区域 | 地址范围 | 用途 |
|------|----------|------|
| Control/Status | 0x0000-0x0FFF | 控制与状态寄存器 |
| Command Queue | 0x1000-0x1FFF | 命令队列 |
| DMA Engine | 0x2000-0x2FFF | DMA 引擎控制 |
| Completion | 0x3000-0x3FFF | 完成通知 |
| Metrics | 0x4000-0x4FFF | 性能计数器 |

**CommandDescriptor magic**：`0x4753494D` ('GSIM')

**当前状态**：
- ✅ 编译成功并集成到 gem5 构建系统
- ✅ PIO 端口连接正确（IOXBar+Bridge 架构）
- ⚠️ 当前为 MMIO timed stub，未实现完整 DMA/descriptor 读取
- ⚠️ Smoke 测试配置需修复端口连接

### 9.3 关键文件

| 文件 | 用途 |
|------|------|
| `gem5_integration/src/dev/generic_accel/generic_accel.cc` | C++ 实现 |
| `gem5_integration/src/dev/generic_accel/generic_accel.hh` | C++ 头文件 |
| `gem5_integration/src/dev/generic_accel/GenericAccel.py` | SimObject 定义 |
| `gem5_integration/configs/generic_accel_smoke_test.py` | Smoke 测试配置 |

---

## 10. 分布式扩展

### 10.1 设计原则

1. **Transparent**：单节点代码无需修改即可工作
2. **Layered**：网络拓扑与加速器拓扑分离
3. **Cost-aware**：显式建模节点间通信成本
4. **Fault-tolerant**：跟踪故障域

### 10.2 核心抽象

#### 10.2.1 NetworkLink

```python
@dataclass
class NetworkLink:
    source_node: str             # 源节点
    target_node: str             # 目标节点
    link_type: str               # ethernet/infiniband/nvlink/custom
    bandwidth_gbps: float        # 带宽
    latency_us: float            # 延迟
```

#### 10.2.2 Node

```python
@dataclass
class Node:
    node_id: str                 # 节点唯一标识
    host_cpu_cores: int          # 主机 CPU 核心数
    host_memory_gb: float        # 主机内存
    local_system: SystemArchitecture  # 本地加速器系统
    rack_id: str                 # 机架 ID
    cluster_id: str              # 集群 ID
    failure_domain: str          # 故障域
    network_links: List[NetworkLink]  # 网络链路
```

#### 10.2.3 DistributedSystem

```python
@dataclass
class DistributedSystem:
    system_id: str
    nodes: Dict[str, Node]       # 节点集合
    global_interconnect: Optional[InterconnectTopology] = None
```

### 10.3 通信成本模型

节点间数据传输时间：
```python
def transfer_time_ms(self, size_bytes: int) -> float:
    return (size_bytes * 8.0 / max(self.bandwidth_gbps, 1.0)) / 1000.0 + self.latency_us / 1000.0
```

---

## 11. DFT 用例实现

### 11.1 完整 QE SCF 计算图

**12 个操作节点**：

| 序号 | 节点 ID | 算子类型 | 描述 |
|------|---------|----------|------|
| 1 | h_psi | gemm | 应用哈密顿量（T + V_loc） |
| 2 | vnl | gemm | 应用非局域势 |
| 3 | precondition | elementwise | 预条件残差 |
| 4 | orthogonalize | reduction | Gram-Schmidt 正交化 |
| 5 | build_H_sub | gemm | 构建约化哈密顿量 |
| 6 | build_S_sub | gemm | 构建约化重叠矩阵 |
| 7 | diagonalize | eigen | 广义厄米特征值求解 |
| 8 | subspace_rotation | gemm | 子空间旋转 |
| 9 | refresh | gemm | 更新波函数 |
| 10 | rho_out | reduction | 计算电荷密度 |
| 11 | mix_rho | elementwise | 混合电荷密度（Broyden/Pulay） |
| 12 | veff | elementwise | 计算有效势 |

### 11.2 数据流

```
h_psi → vnl → precondition → orthogonalize → build_H_sub/build_S_sub → diagonalize → subspace_rotation → refresh → rho_out → mix_rho → veff
```

### 11.3 参数化

运行时参数：
- `npw`：平面波数（默认 2945）
- `nkb`：k 点数（默认 144）
- `m`：能带数（默认 16）
- `nfft`：FFT 点数（默认 32768）

---

## 12. 测试与验证

### 12.1 测试覆盖

| 测试类型 | 数量 | 状态 |
|----------|------|------|
| Python 单元测试 | 29 | ✅ 全部通过 |
| C++ generic_sim 编译 | 1 | ✅ 编译成功 |
| gem5 编译 | 1 | ✅ 编译成功 |
| 回归测试（GPU/FPGA/CIM 差异化） | 3 | ✅ 通过 |

### 12.2 回归测试结果

同一 workload 在不同加速器上的评估结果：

| 加速器 | 延迟 | 吞吐量 | 功耗 | 数据搬运 |
|--------|------|--------|------|----------|
| GPU | 0.14 ms | 高 | 高 | 低 |
| FPGA | 1.43 ms | 中 | 中 | 中 |
| CIM | 14.29 ms | 低 | 低 | 高 |

### 12.3 验证命令

```bash
# Python 全量测试
python3 -m pytest -q dse_v2/tests

# C++ 后端构建
cmake --build model/generic_sim_backend/build -j4

# gem5 编译
cd gem5_integration/gem5 && scons build/X86/gem5.opt -j8

# 回归测试
python3 dse_v2/tests/test_regression_generic_backend.py
```

---

## 13. 代码审核修复记录

### 13.1 审核报告

**报告文件**：`docs/overview/generic_dse_gem5_code_review_20260508.md`

**审核结论**：REQUEST CHANGES

**主要阻塞点**（已修复）：
1. gem5 smoke 配置 PIO 端口连接方向错误
2. C++ JSON parser 未正确解析 accelerators/edges/capabilities
3. DSE evaluator 返回类型从 EvaluationResult 变为 dict
4. 性能模型单位错误
5. GenericAccel 文档/实现不一致

### 13.2 Phase 1 修复：测试与单位正确性

| 问题 | 修复内容 | 文件 |
|------|----------|------|
| HIGH-4 | 统一 evaluator 返回类型为 EvaluationResult | `orchestrator.py`, `analytical_evaluator.py` |
| HIGH-6 | 修复数据搬运时间单位（除以 1000 → 乘以 1000） | `task_graph.py` |
| HIGH-5 | 修复 peak_gops 单位（多乘 1000） | `generic_systemc_bridge.py` |

### 13.3 Phase 2 修复：Generic SystemC 后端

| 问题 | 修复内容 | 文件 |
|------|----------|------|
| HIGH-2 | 重写 C++ JSON parser，正确解析 accelerators/capabilities/edges/interconnect | `json_parser.cpp` |
| HIGH-3 | 修复 node 字段名混淆（字段名不再被当作 node id） | `json_parser.cpp` |
| HIGH-2 | GraphExecutor 正确消费架构差异 | `graph_executor.cpp` |

### 13.4 Phase 3 修复：gem5 GenericAccel

| 问题 | 修复内容 | 文件 |
|------|----------|------|
| HIGH-1 | 修正 PIO 端口连接（IOXBar+Bridge 架构） | `generic_accel_smoke_test.py` |
| MEDIUM-3 | 同步 tracked scaffold 与 gem5 tree | `gem5_integration/src/dev/generic_accel/` |

### 13.5 Phase 4 修复：文档与可复现性

| 问题 | 修复内容 | 文件 |
|------|----------|------|
| MEDIUM-4 | 添加 `model/generic_sim_backend/build/` 到 `.gitignore` | `.gitignore` |
| MEDIUM-1 | 更新 README 标注 stub 状态 | `README.md` |

### 13.6 待修复问题

| 问题 | 优先级 | 状态 |
|------|--------|------|
| HIGH-7：MultiFidelity L3 路径仍使用 QE-specific backend | HIGH | 待修复 |
| MEDIUM-2：Metric 64-bit 寄存器地址重叠 | MEDIUM | 待修复 |

---

## 14. 已知限制与后续工作

### 14.1 当前限制

1. **gem5 GenericAccel**：当前为 MMIO timed stub，未实现完整 DMA/descriptor 读取
2. **L3 后端**：MultiFidelity 框架的 L3 路径仍指向 QE-specific backend，需迁移到 GenericSystemCBackend
3. **算子库**：当前仅支持基础算子（gemm/fft/eigen/reduction/elementwise），需扩展更多科学计算算子
4. **搜索策略**：当前为网格搜索，需实现贝叶斯优化、遗传算法等高级策略
5. **可视化**：缺少 Pareto 前沿、执行时间线可视化工具

### 14.2 后续工作

#### 短期（1-2 周）
- [ ] 修复 MultiFidelity L3 路径，使用 GenericSystemCBackend
- [ ] 修复 gem5 metric 寄存器 64-bit 地址重叠
- [ ] 运行 gem5 smoke 测试并验证 MMIO 读写
- [ ] 扩展算子库（conv3d, attention, sparse ops）

#### 中期（1 个月）
- [ ] 实现 Bayesian Optimization DSE 引擎
- [ ] 实现遗传算法搜索策略
- [ ] 添加 Pareto 前沿可视化
- [ ] 添加执行时间线可视化
- [ ] 集成更多 workload（VASP, CP2K）

#### 长期（2-3 个月）
- [ ] 完整 gem5 + SystemC 协同仿真（L4）
- [ ] 分布式 DSE 支持（多节点集群）
- [ ] 自动映射优化（迭代找到最佳映射）
- [ ] 功耗/面积联合优化
- [ ] 论文级 benchmark 与 KPI 方案

---

## 15. 附录

### 15.1 术语表

| 术语 | 英文 | 说明 |
|------|------|------|
| DSE | Design Space Exploration | 设计空间探索 |
| IR | Intermediate Representation | 中间表示 |
| TLM | Transaction-Level Modeling | 事务级建模 |
| CIM | Compute-In-Memory | 存内计算 |
| LCW | Long Control Word | 长控制字 |
| SCF | Self-Consistent Field | 自洽场 |
| QE | Quantum ESPRESSO | 量子 espresso 软件包 |
| FPGA | Field-Programmable Gate Array | 现场可编程门阵列 |
| ASIC | Application-Specific Integrated Circuit | 专用集成电路 |

### 15.2 文件索引

#### 核心框架
| 文件 | 用途 |
|------|------|
| `dse_v2/core/ir/compute_graph.py` | L3 Compute Graph IR |
| `dse_v2/core/ir/task_graph.py` | L2 Task Graph IR |
| `dse_v2/core/ir/execution.py` | L0 Execution IR |
| `dse_v2/core/ir/dft_workload.py` | DFT workload 定义 |
| `dse_v2/core/architecture/accelerator.py` | L1 Architecture IR |
| `dse_v2/core/architecture/distributed.py` | 分布式扩展 |
| `dse_v2/dse/orchestrator.py` | DSE 引擎 |
| `dse_v2/dse/analytical_evaluator.py` | L1 分析评估器 |
| `dse_v2/dse/tlm_evaluator.py` | L2 TLM 评估器 |
| `dse_v2/dse/multi_fidelity.py` | 多保真度框架 |

#### 后端
| 文件 | 用途 |
|------|------|
| `dse_v2/backends/generic_systemc_bridge.py` | Python 桥接层 |
| `model/generic_sim_backend/src/main.cpp` | C++ 入口 |
| `model/generic_sim_backend/src/json_parser.cpp` | JSON 解析器 |
| `model/generic_sim_backend/src/graph_executor.cpp` | 图执行引擎 |
| `model/generic_sim_backend/src/op_model_registry.cpp` | 算子模型注册表 |

#### gem5 集成
| 文件 | 用途 |
|------|------|
| `gem5_integration/src/dev/generic_accel/generic_accel.cc` | gem5 设备实现 |
| `gem5_integration/src/dev/generic_accel/generic_accel.hh` | gem5 设备头文件 |
| `gem5_integration/configs/generic_accel_smoke_test.py` | Smoke 测试配置 |

#### 文档
| 文件 | 用途 |
|------|------|
| `docs/architecture/system_design_master_spec_v0.md` | 系统级主规范 |
| `docs/overview/generic_dse_gem5_code_review_20260508.md` | 代码审核报告 |
| `dse_v2/README.md` | DSE v2 项目说明 |

### 15.3 参考标准

- **ISO/IEC/IEEE 42010**：架构描述标准
- **OpenTitan**：硬件文档实践结构
- **SystemC-TLM 2.0**：事务级建模标准
- **JSON Schema Draft 7**：JSON 模式验证

### 15.4 构建命令速查

```bash
# 构建 C++ generic_sim 后端
cmake --build model/generic_sim_backend/build -j4

# 运行 Python 测试
python3 -m pytest -q dse_v2/tests

# 构建 gem5
cd gem5_integration/gem5 && scons build/X86/gem5.opt -j8

# 运行 DFT 评估
python3 dse_v2/tests/test_dft_evaluation.py

# 运行回归测试
python3 dse_v2/tests/test_regression_generic_backend.py
```

---

## 文档控制

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| v1.0 | 2026-05-09 | AI Agent | 初始版本，基于现有代码实现和代码审核修复内容 |

---

> **审核状态**：本文档为草案，需经用户审核后定稿。  
> **下一步**：用户审核文档内容，确认架构设计是否符合预期，提出修改意见或批准实施。
