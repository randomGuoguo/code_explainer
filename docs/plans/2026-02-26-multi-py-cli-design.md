# 2026-02-26 Multi-Py CLI（一次处理多个 .py）设计

状态：已与用户确认并通过（Design）

## 背景

当前 `code_explainer.py` 仅支持交互输入单个 `.py` 文件路径并处理。用户希望一次运行脚本即可处理多个 `.py` 文件。

## 目标（Goals）

- 支持命令行直接传入多个 `.py`：
  - `python code_explainer.py a.py b.py c.py`
- 保持兼容：不传参数时仍走交互输入单个 `.py` 的流程。
- 每个 `.py` 文件独立产出 Markdown 报告，避免同目录覆盖：
  - 输出到目标文件同目录，文件名为 `<目标文件名stem>_doc.md`
  - 示例：`a.py` -> `a_doc.md`
- 批处理顺序执行；某个文件失败时打印错误并继续处理后续文件；最终以退出码体现是否存在失败。

## 非目标（Non-goals）

- 不实现目录扫描/递归/通配规则等额外能力（PowerShell 可用 `*.py` 自行展开）。
- 不引入并发、断点续跑、复杂日志系统（保持 MVP 简洁）。

## CLI/I-O 设计

### 用法

- 单文件（交互）：
  - `python code_explainer.py`
  - 按提示输入：`some.py`
- 多文件（参数）：
  - `python code_explainer.py a.py b.py`
  - PowerShell 可用：`python code_explainer.py *.py`

### 输出

对每个目标文件：
- 原地更新该 `.py` 的函数/方法 docstring（不改逻辑代码）。
- 在同目录生成 `<stem>_doc.md`（文件概述 + 函数概要表）。

## 实现要点

- `run_on_file()`：`md_path` 从“按文件夹命名”改为“按目标文件命名”。
- `main()`：使用 `argparse` 解析多个 positional paths；为空时回退到 `input()`。
- 批处理错误处理：逐个验证路径存在且后缀为 `.py`；失败记录错误并继续，最后返回 `0/1` 退出码。

## 测试与文档

- `tests/test_code_explainer.py`：
  - 更新现有 `run_on_file` 测试中的 Markdown 文件名断言为 `<stem>_doc.md`。
- `README.md`：
  - 增加多文件调用示例与输出命名说明。

