# CST 超表面单元批量变体工具

这个工具用于从一个已有的 `.cst` 单元模板工程出发，读取建模历史树，提取可变尺寸候选项，并按显式变体配置批量生成多个独立的单元工程。

第一版目标是生成“单元库”，不包含阵列拼装。

## 当前能力

- 读取现有 `.cst` 工程的历史树
- 导出 `history_manifest.json` 供人工标记可变尺寸
- 读取 `variant_config.json` 中的显式变体列表
- 为每个变体生成独立 `.cst` 工程
- 输出 `variants_manifest.json` 记录生成结果
- 支持 `--dry-run`，先验证配置和历史改写结果，不实际调用 CST 建模

## 主要文件

- `cst_variant_tool.py`
  - 主脚本
  - 包含以下命令：
    - `info`
    - `connect`
    - `new-mws`
    - `inspect-history`
    - `build-variants`

- `scripts/run-cst-variant.ps1`
  - PowerShell 启动入口
  - 使用 CST 自带 Python 运行主脚本

- `scripts/run-cst-variant.cmd`
  - CMD 启动入口
  - 适合直接在 Windows 命令行中调用

- `examples/history_manifest.sample.json`
  - 历史树清单示例

- `examples/variant_config.sample.json`
  - 变体配置示例

- `tests/test_cst_variant_tool.py`
  - 不依赖 live CST 会话的本地解析测试

## 依赖说明

本工具默认使用 CST 自带 Python：

- `D:\CST\Python\python.exe`

并自动注入：

- `D:\CST\AMD64`
- `D:\CST\AMD64\python_cst_libraries`

所以通常不需要你单独安装系统 Python。

## 工作流程

### 1. 导出历史树清单

先从模板工程导出历史树候选项：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-cst-variant.ps1 inspect-history --project D:\path\template.cst --output D:\path\history_manifest.json
```

或者：

```cmd
.\scripts\run-cst-variant.cmd inspect-history --project D:\path\template.cst --output D:\path\history_manifest.json
```

### 2. 手工标记可变尺寸

打开 `history_manifest.json`，把你希望参与批量变体的候选项改成：

```json
"enabled": true
```

建议只开启你明确要控制的尺寸，不要一次性把所有数值都打开。

## 也可以直接当 Python 函数调用

如果你不想走命令行，也可以在自己的 Python 脚本里直接调用：

```python
from cst_variant_tool import export_history_manifest

manifest = export_history_manifest(
    project_path=r"D:\path\template.cst",
    output_path=r"D:\path\history_manifest.json",
    connect_to_any=True,
    options=["-m", "-i"],
)

print(manifest["history_item_count"])
print(manifest["candidate_count"])
```

最稳的运行方式有两个：

1. 先切到仓库根目录 `D:\CSTapi` 再运行你的 Python 脚本
2. 或者先把仓库根目录加入 `sys.path`

例如：

```python
import sys
sys.path.append(r"D:\CSTapi")

from cst_variant_tool import export_history_manifest
```

说明：

- `project_path`
  - 模板 `.cst` 工程路径

- `output_path`
  - 如果提供，就会把清单写入 JSON 文件
  - 如果设为 `None`，则只返回 Python 字典对象

- `connect_to_any`
  - `True` 表示优先连接已有 CST 会话

- `options`
  - 传给 CST 启动参数，例如 `["-m", "-i"]`

### 3. 编写变体配置

准备 `variant_config.json`，定义：

- 模板工程路径
- 历史清单路径
- 输出目录
- 输出模式
- 显式变体列表

示例见：

- `examples/variant_config.sample.json`

### 4. 生成批量变体工程

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-cst-variant.ps1 build-variants --config D:\path\variant_config.json --dump-rendered-history
```

或者：

```cmd
.\scripts\run-cst-variant.cmd build-variants --config D:\path\variant_config.json
```

## 命令说明

### `info`

查看当前可见的 CST Design Environment 会话。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-cst-variant.ps1 info
```

### `connect`

测试是否能连接到 CST 前端。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-cst-variant.ps1 connect --connect-to-any
```

### `new-mws`

测试是否能创建新的 MWS 工程。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-cst-variant.ps1 new-mws --connect-to-any
```

### `inspect-history`

打开模板工程并导出历史树清单。

常用参数：

- `--project`
  - 输入模板 `.cst` 工程路径

- `--output`
  - 输出 `history_manifest.json` 路径

- `--connect-to-any`
  - 优先连接已有 CST 会话，没有则新建

### `build-variants`

根据配置批量生成单元变体工程。

常用参数：

- `--config`
  - 变体配置 JSON 路径

- `--dry-run`
  - 只做配置校验和历史改写预览，不实际生成 `.cst`

- `--dump-rendered-history`
  - 为每个变体额外输出一份改写后的历史记录 JSON，便于排查

## `history_manifest.json` 说明

这个文件由 `inspect-history` 自动生成。

主要内容包括：

- `history_index`
  - 历史项序号

- `name`
  - 历史项名称

- `feature_type`
  - 推断出的特征类型，例如 `Brick`

- `command_text`
  - 原始历史命令文本

- `candidates`
  - 从当前历史项中提取出的数值候选列表

每个 candidate 包含：

- `candidate_id`
  - 唯一标识，例如 `h0001_v01`

- `suggested_label`
  - 推荐别名，可在配置里直接使用

- `original_value`
  - 原始数值

- `enabled`
  - 是否允许这个尺寸参与变体生成

- `span`
  - 在历史命令文本中的位置

- `line` / `column`
  - 便于人工定位

## `variant_config.json` 说明

当前版本采用显式变体列表方式。

结构示意：

```json
{
  "template_project": "D:/models/unit_cell_template.cst",
  "history_manifest": "D:/CSTapi/history_manifest.json",
  "output_dir": "D:/CSTapi/output/unit_cell_library",
  "output_mode": "separate_projects",
  "variants": [
    {
      "variant_id": "variant_001",
      "values": {
        "h0001_v01": -2.8,
        "h0001_v02": 2.8
      }
    }
  ]
}
```

说明：

- `output_mode`
  - 第一版只支持 `"separate_projects"`

- `variant_id`
  - 每个变体的唯一名称

- `values`
  - 需要改写的尺寸键值对
  - 键可以用：
    - `candidate_id`
    - `suggested_label`

## 输出结果

执行 `build-variants` 后，输出目录中通常会包含：

- `variant_config.json`
  - 本次运行实际使用的配置副本

- `variants_manifest.json`
  - 每个变体的执行结果汇总

- `projects/`
  - 每个变体输出的独立 `.cst` 工程

- `rendered_history/`
  - 如果加了 `--dump-rendered-history`，这里会保存每个变体改写后的历史树内容

## `variants_manifest.json` 说明

每个变体至少会记录：

- `variant_id`
- `output_project`
- `applied_values`
- `status`

其中 `status` 可能是：

- `success`
  - 生成成功

- `failed`
  - 生成失败

- `dry_run`
  - 只是预演，没有真正建模

如果失败，还会带上 `error` 字段。

## 注意事项

- 第一版只适合“单个超表面单元模板”的批量变体生成。
- 还没有实现阵列拼装。
- 第一版不自动修改所有历史树数值，只修改你手工启用的候选项。
- 第一版默认每个变体输出独立 `.cst` 文件。
- 如果目标输出目录已存在，程序不会直接覆盖，而是自动创建带时间戳的新目录。

## 当前实现方式

历史树读取使用：

- `model3d._GetHistory()`

变体生成方式是：

- 根据模板历史记录生成改写后的命令文本
- 对每个变体新建一个 MWS 工程
- 逐条回放历史命令
- 执行 `full_history_rebuild()`
- 最后另存为独立 `.cst`

## 已完成验证

已验证内容：

- 历史树候选项提取
- 显式变体值校验
- 改写后的历史命令渲染
- `dry-run` 输出目录与 manifest 生成

本地测试命令：

```powershell
& 'D:\CST\Python\python.exe' -m unittest discover -s .\tests -v
```

## 说明

如果当前 Codex 会话里仍然无法稳定接管 CST 前端，这个工具最终联调建议在你自己的 Windows 桌面会话中运行。  
也就是说，脚本已经写好，但真实 `.cst` 工程生成是否完全成功，还取决于你本机上的 CST 自动化会话是否能正常连接。
