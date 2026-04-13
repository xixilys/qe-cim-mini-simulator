# 2026-04-13 Advisor Figures and Tables Layout Guide — SystemC System-Level DSE v0

## 1. 文档定位

这份 guide 用于统一 advisor pack 的图表布局建议。目标不是强制视觉设计，而是确保老师在最短时间内看到：

- 推荐 family 是谁
- correctness_status / confidence 是什么
- `speedup_to_convergence_range` / `energy_to_convergence_range` 大概落在哪
- 为什么这个结论可信、但又不过度承诺

## 2. 最推荐的图表顺序

如果时间很紧，优先保留下面 4 个元素：

1. **One-row recommendation table**
2. **Family ranking summary table**
3. **QE gold correctness gate table**
4. **Projection range figure**

如果篇幅允许，再补：

5. CPU/device/datapath responsibility figure
6. assumptions / limitations box

## 3. 图表 1：One-row recommendation table（首页必需）

### 目的
用一行就让老师知道“当前推荐什么，以及可以信到什么程度”。

### 建议字段
| recommended_family | correctness_status | confidence | speedup_to_convergence_range | energy_to_convergence_range | main_reason | main_caveat |
|---|---|---|---|---|---|---|
| `TODO` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` |

### 注意
- 这里不放长段文字
- `speedup` / `energy` 必须是 range
- 如果 `correctness_status != gold_pass`，这一行要显式降级或标红说明

## 4. 图表 2：Family ranking summary table（首页或主报告第一页）

### 目的
把 `F1 / F2 / F3` 的相对关系快速讲清楚。

### 建议字段
| Family | CPU/device split | correctness_status | confidence | speedup_to_convergence_range | energy_to_convergence_range | role |
|---|---|---|---|---|---|---|
| `F1` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` | conservative baseline |
| `F2` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` | primary candidate |
| `F3` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` | stretch candidate |

### 注意
- 角色描述建议固定成：`conservative baseline / primary candidate / stretch candidate`
- 避免只写 cluster 名称，不写 CPU/device 分工

## 5. 图表 3：QE gold correctness gate table（主报告必需）

### 目的
证明这不是“只会讲故事”的 projection，而是有 numerical gate 的。

### 建议字段
| QE case | final total energy match | residual threshold state match | converged/not-converged state match | tolerance schema ID | pass/fail |
|---|---|---|---|---|---|
| `QE USPP-heavy` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` |
| `QE NC-light / si8_pbe_nc` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` |

### 注意
- 这个表不要藏到太后面
- 没有这个表时，projection-grade recommendation 不应该上首页

## 6. 图表 4：Projection range figure（主报告必需）

### 目的
直观展示三类 family 在 convergence-scoped projection 上的大致位置。

### 推荐形式
- 横向区间条形图，分别画：
  - `speedup_to_convergence_range`
  - `energy_to_convergence_range`
- 每个 family 一行
- 用颜色或标记表示 `confidence`

### 示例视觉编码
- `high`：实色
- `medium`：浅色
- `exploratory`：虚线/空心

### 注意
- 不要画单点柱状图来假装精确值
- 区间图旁边建议放 `assumption_set_id`

## 7. 图表 5：CPU/device/datapath responsibility figure（建议）

### 目的
帮助老师快速理解架构差异不是 cluster 名字差异，而是 system contract 差异。

### 推荐形式
三栏框图：
- Host CPU
- Device runtime
- Hardware datapath

然后按 `F1 / F2 / F3` 分三行，标出：
- 哪些功能留 CPU
- 哪些功能交 runtime
- 哪些功能进 datapath
- `diag` 默认走哪条路径

## 8. 图表 6：Assumptions and limitations box（建议）

### 目的
防止老师误以为这就是最终实现结论。

### 至少包含
- v1 是 system-level 架构筛选器
- 不是 RTL 参数冻结器
- 不是最终 board-level power claim
- projection 只在 QE gold correctness gate 通过时成立

## 9. 版式建议

### 如果只有 1 页
- 上半页：recommendation table + one-paragraph summary
- 下半页：family ranking summary + QE gold gate mini table

### 如果有 2 页
- 第 1 页：cover memo + recommendation table + family ranking
- 第 2 页：QE gold gate + projection range figure + limitations box

### 如果有主报告 + 附录
- 首页：cover memo / one-row recommendation
- 第 2 页：family ranking + projection figure
- 第 3 页：QE gold correctness gate
- 附录：portability evidence / assumptions / extra tables

## 10. 常见图表错误

### 不推荐
- 用单个 speedup 数字当作最终结论
- 只给 projection 不给 correctness gate
- 图里只写 cluster，不写 CPU/device/datapath 分工
- 把 portability evidence 图放在 QE gold gate 前面

### 推荐
- 先 recommendation，再 correctness，再 projection
- 所有结论都带 `correctness_status` / `confidence`
- 所有 projection 都显式为 range

## 11. 最小可交付图表集

如果最后时间不够，至少保留：

1. one-row recommendation table
2. family ranking summary table
3. QE gold correctness gate table
4. one-paragraph limitations box

这四项已经足够支持一次比较稳妥的老师汇报。
