---
name: cst-python-automation-zh-cn
description: 当用户希望模型通过自然语言控制 CST Studio Suite 时使用，包括连接或启动 CST、打开或复用 .cst 工程、修改参数、建模增删结构、设置仿真、运行求解器、读取 S 参数/远场/效率/日志、做优化闭环，以及联合机器学习或深度学习代理模型。
---

# CST 自然语言自动化 Skill

## 1. 目标

把用户的自然语言需求转换成安全、可验证、可复现的 CST Python 自动化流程。模型不能只给概念建议，要明确项目路径、操作步骤、保存策略、结果读取方式、日志和输出产物。

## 2. 官方资料优先级

生成 CST 命令前先查官方资料，不要硬猜。

1. Python API：`official-docs/python/`，重点看 `main.html`、`source/cst.interface.html`、`source/cst.results.html`。
2. Python 包源码：`official-docs/python_cst_libraries/cst/`，重点看 `interface/studio.py`、`results.py`。
3. 3D 建模和 History/VBA 命令：`official-docs/vba-3d/`。
4. Design Studio / schematic 命令：`official-docs/vba-des/`。
5. 启动、OLE、环境变量：`official-docs/advanced/`。
6. 如果仓库内资料不足，按 `official-docs/source-index.md` 去 `D:\CST` 安装目录查完整官方文档。

核心分工：

- `cst.interface`：连接 CST、创建/打开工程、复用工程、运行求解器、访问 3D/Schematic 应用。
- `cst.results`：离线读取已保存 `.cst` 的 0D/1D/2D 结果，不需要启动 CST。
- VBA/History：具体几何建模、端口、材料、边界、网格、监视器、求解器设置。
- `model3d.add_to_history(header, vba_code)`：Python 驱动 CST 建模的主要桥梁。

## 3. 任务解析协议

收到用户描述后先整理成任务规格：

```yaml
task_type: connect | parameter_edit | geometry_edit | build_model | simulate | read_results | optimize | ml_loop
project_path: path-or-null
save_policy: no_save | save_copy | save_original
parameters: name/value pairs
geometry_ops: add/remove/replace operations
solver: time_domain | frequency_domain | existing
metrics: S11, S21, bandwidth, gain, efficiency, farfield, logs
budget: simulation count or time limit
risk_level: low | medium | high
outputs: expected project, dataset, metrics, plots, logs
```

可从仓库或 CST 工程发现的信息先自己查。只有保存原工程、删除结构、运行长仿真、覆盖 GitHub 等高风险偏好才需要明确用户意图。

## 4. 执行决策树

- 用户要连接或测试 CST：使用 `DesignEnvironment.connect_to_any_or_new()`；如果要求必须复用已打开工程，则无可见 Design Environment 时直接失败。
- 用户要修改参数：读取原值，写入新值，rebuild；默认不保存原工程。
- 用户要新建模型：新建 MWS，写参数，添加 setup、几何、端口、求解器，rebuild，保存到新路径。
- 用户要增删结构：优先复制工程，在副本中用 History/VBA 增删改。
- 用户要读取结果：优先用 `cst.results.ProjectFile` 离线读取；若工程未保存或需要实时结果，再用 live CST API。
- 用户要运行仿真：复制工程到 job 目录，应用参数，rebuild，run solver，读取日志和指标。
- 用户要优化或深度学习：CST 作为昂贵真实评估器；所有 trial 记录参数、指标、状态、日志和工程路径。

## 5. 核心工作流

### 新建模型

1. 提取频率、尺寸、材料、端口、边界、目标指标。
2. 建参数表，尺寸尽量参数化。
3. `DesignEnvironment.new()` 或 `connect_to_any_or_new()` 后 `new_mws()`。
4. `StoreParameterWithDescription` 或 `StoreParameter` 写参数。
5. `add_to_history()` 添加单位、频率范围、背景、边界、网格、监视器。
6. 添加组件、材料、几何体、端口、集总元件。
7. 添加求解器设置。
8. `full_history_rebuild()`，失败时尝试 `RebuildOnParametricChange(True, False)`。
9. 保存到新 `.cst` 路径。

### 修改已有工程

1. 连接 CST 并查 `list_open_projects()`。
2. 若用户要求实时修改已打开工程，必须用 `get_open_project()` 复用。
3. 写参数前读取原值。
4. 写入新值并 rebuild。
5. 根据保存策略决定恢复、不保存、另存副本或保存原工程。

### 运行仿真

1. 复制 `.cst` 和同名工程文件夹到 job 目录。
2. 删除副本中的 `.lok` 锁文件。
3. 打开副本工程，应用参数，rebuild。
4. 用 `model3d.run_solver()`，失败时回退 `RunSolver()`。
5. 检查 `Result/Model.log`、`output.json`、`outputDS.json`。
6. 读取指标并写入 `metrics.json` 或 `trials.jsonl`。

### 读取结果

1. 先用 `ProjectFile(path, allow_interactive=False)` 读取已保存工程。
2. 用 `get_3d().get_tree_items()` 发现结果树，不要盲猜路径。
3. 匹配 `S-Parameters`、`Farfields`、`Efficiencies` 等树项。
4. 用 `get_result_item(treepath).get_xdata()` 和 `get_ydata()` 读 1D 曲线。
5. 报告指标来源：live API、`cst.results`、导出文本或日志解析。

## 6. 建模和仿真指令模式

History helper：

```python
def add_history(project, caption, lines):
    project.model3d.add_to_history(caption, "\n".join(lines) + "\n")
```

最小 setup：

```python
add_history(project, "setup units boundary monitor", [
    "With Units",
    '    .SetUnit "Length", "mm"',
    '    .SetUnit "Frequency", "GHz"',
    "End With",
    'Solver.FrequencyRange "fmin", "fmax"',
    "With Boundary",
    '    .Xmin "expanded open"',
    '    .Xmax "expanded open"',
    '    .Ymin "expanded open"',
    '    .Ymax "expanded open"',
    '    .Zmin "expanded open"',
    '    .Zmax "expanded open"',
    "End With",
    "With Monitor",
    "    .Reset",
    '    .Name "farfield (f=fmon)"',
    '    .Domain "Frequency"',
    '    .FieldType "Farfield"',
    '    .MonitorValue "fmon"',
    "    .Create",
    "End With",
])
```

Brick 示例：

```python
add_history(project, "create patch", [
    "With Brick",
    "    .Reset",
    '    .Name "patch"',
    '    .Component "metal"',
    '    .Material "PEC"',
    '    .Xrange "-patch_w/2", "patch_w/2"',
    '    .Yrange "-patch_l/2", "patch_l/2"',
    '    .Zrange "0", "metal_t"',
    "    .Create",
    "End With",
])
```

Discrete port 示例：

```python
add_history(project, "define port 1", [
    "With DiscretePort",
    "    .Reset",
    '    .PortNumber "1"',
    '    .Type "SParameter"',
    '    .Impedance "50.0"',
    '    .SetP1 "False", "feed_x", "-feed_gap/2", "0"',
    '    .SetP2 "False", "feed_x", "feed_gap/2", "0"',
    "    .Create",
    "End With",
])
```

运行求解器：

```python
try:
    project.model3d.full_history_rebuild()
except Exception:
    project.model3d.RebuildOnParametricChange(True, False)

try:
    project.model3d.run_solver()
except Exception:
    project.model3d.RunSolver()
```

## 7. 优化和深度学习闭环

- 参数扫描/优化：定义变量、边界、目标、约束和预算；每个候选复制工程仿真；缓存已评估参数。
- 代理模型：用 CST 生成数据集，训练模型预测 S 参数、带宽、增益、效率或远场得分。
- 主动学习：代理模型提出候选，CST 验证高价值样本，追加数据后重训。
- 逆向设计：先在代理模型上优化，再用 CST 验证 top-k。
- 每次 trial 写入 `trials.jsonl`，包含参数、指标、状态、错误、工程路径、日志路径。

## 8. 安全规则

- 默认不保存用户原工程。
- 删除结构、覆盖工程、长仿真、批量优化必须使用副本或得到明确要求。
- `pdfsrc`、junction、外部链接目录不得递归删除。
- 不要因为看到 `cstd` 等后台进程就认为 CST 前端可连接，要查 `running_design_environments()`。
- 不要把“读取已有结果”误解为“重新运行仿真”。
- 不要硬编码结果树路径，先发现再读取。

## 9. 输出契约

每次完成任务后输出：

```yaml
project_path: used or generated CST project
save_policy: no_save | save_copy | save_original
operations: list of parameter/modeling/simulation steps
metrics: extracted values with source
logs: Model.log/output.json/outputDS.json paths
artifacts: generated files, datasets, plots, manifests
warnings: assumptions, skipped steps, risks
errors: failures and recovery attempts
```

