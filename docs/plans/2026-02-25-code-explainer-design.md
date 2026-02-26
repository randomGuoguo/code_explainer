# 2026-02-25 Code Explainer（自动补全 Docstring + 生成函数概要 MD）设计

状态：已与用户确认并通过（Brainstorming -> Design）

## 背景与问题

公司/个人存在大量存量 Python 代码，缺少注释与 docstring，导致：
- 代码难以理解、维护成本高
- 新函数越来越多，容易重复造轮子

目标是做一个脚本：输入一个 `.py` 文件路径，自动为其中的函数/方法补全 docstring，并生成该文件的功能概述与函数概要表（Markdown）。

## 目标（Goals）

- 提供一个可执行脚本 `.py`：
  - 运行脚本后输入目标 `.py` 文件路径
  - 基于 `ast` 提取顶层函数与类方法（不含 `__dunder__`）
  - 通过 OpenAI 官方 API（默认模型 `gpt-4.1`）生成 docstring 与摘要
  - 回写 docstring 到原文件（原地修改、不备份）
  - 在目标文件同目录输出 `<目标文件夹名>_doc.md`
- docstring 风格遵循 `coding_style.md`：中文为主、术语保留英文、固定 6 段模板，且“实现说明”<=100字。
- “尽量不乱改”：已有 docstring 默认保留，仅当明显不足时才补全。

## 非目标（Non-goals）

- 不追求一次性覆盖所有复杂语法与极端格式（先做 MVP，按需要迭代）
- 不实现复杂的错误恢复/断点续跑/并发等（MVP 阶段）
- 不在本阶段做 IDE 插件或 CI 集成

## 约束与已确认决策（Decisions）

来自用户确认：
- Docstring 策略：**保留为主**；缺失必补；“过短/缺段/不符合模板”则补全为模板风格（选项 C）
- 落盘方式：**原地修改目标 `.py`，不备份**（选项 B）
- 覆盖范围：仅 **顶层函数 + 类方法**；跳过 `__dunder__`；但处理 `_private`（选项 A）
- LLM：OpenAI 官方 API（`OPENAI_API_KEY`）；默认模型 **`gpt-4.1`**
- Markdown：输出在目标 `.py` 同目录；文件名为 **`<目标文件夹名>_doc.md`**

## 用户体验（CLI/I-O）

### 输入
- 运行脚本：`python <tool>.py`
- 交互输入：目标 `.py` 路径（相对/绝对均可）

### 输出
- 修改后的目标 `.py`（插入/替换 docstring；不改其它逻辑代码）
- 生成 `<目标文件夹名>_doc.md`，包含：
  1) 文件功能概述
  2) 函数概要表：函数名｜入参｜返回值｜功能概述

## 解析与更新（AST）

### 提取对象
使用标准库 `ast`：
- `ast.FunctionDef` / `ast.AsyncFunctionDef`（模块顶层）
- `ast.ClassDef` 内的 `FunctionDef/AsyncFunctionDef`（类方法）

### 过滤规则
- 跳过 `__dunder__`：名称以 `__` 开头且以 `__` 结尾
- 保留 `_private`：名称以单下划线开头仍处理
- 默认不处理嵌套函数（MVP）；如后续需要可加开关

### “docstring 不足”的判定（needs_update）

对每个函数/方法：
- `existing = ast.get_docstring(node, clean=False)`
- 若 `existing is None`：需要补全
- 若 `existing` 非空：
  - 若包含任意模板段标题关键字（`功能描述/参数/返回值/关键规则/示例/实现说明`）但不齐全：视为不足，需要补全
  - 否则若内容明显过短（例如去空行后 < 3 行或总字符 < 60）：视为不足，需要补全
  - 否则：认为足够，保持不变

> 设计意图：避免把已有的长 docstring（即使不是模板）强行重写；只对明显不足的做补全。

### 回写策略（只动 docstring）

脚本只插入/替换“函数体第一条字符串字面量语句”的 docstring，不修改其它语句与格式。

实现上使用 AST 节点行号定位源码文本并进行最小化文本替换：
- 若已有 docstring：用其 `Expr(str)` 节点的 `lineno/end_lineno` 作为替换范围
- 若缺失 docstring：在函数体第一个语句行前插入 docstring

对“一行函数”（`def f(): return 1`）等边界，MVP 可选择：
- 优先：检测到 body 与 def 同行时跳过并提示（避免破坏格式）
- 后续增强：引入更稳健的 CST 工具（如 `libcst`）重写

## LLM 集成（OpenAI API）

### 依赖与鉴权
- 依赖：`openai`（Python SDK）
- 环境变量：`OPENAI_API_KEY`

### 调用方式（建议）
使用 Responses API：`client.responses.create(...)`
- 默认 `model="gpt-4.1"`
- 输出要求：**只返回 JSON**（或使用 Structured Outputs 强约束）

### 输入内容（Prompt 组成）
- 系统指令：
  - 强制按 docstring 6 段模板输出（中文为主、术语英文）
  - “实现说明”<=100字
  - 示例给最小可运行形式（后续可迁移到 pytest）
  - 不编造业务规则；不确定就保守表述（如“待确认/待补充”）
- 用户内容：
  - 目标 `.py` 源码（默认整文件；过大时只发必要片段）
  - AST 提取的函数清单（qualname、signature、已有 docstring 原文等）

### 结构化输出契约（唯一输出格式）

返回一个 JSON 对象：
- `file_summary`：string（用于 Markdown 文件概述）
- `updates`：list[object]，每项：
  - `qualname`：string（`foo` 或 `MyCls.bar`）
  - `docstring`：string（不含三引号，内部按 6 段模板排版）
  - `summary`：string（单行函数概述，用于表格）

脚本侧逻辑：解析 JSON → 按 `qualname` 定位函数节点 → 插入/替换 docstring → 生成 MD。

### 失败处理（MVP）
- JSON 解析失败：自动重试 1 次（追加提示“请只输出合法 JSON”）
- API 失败/超时：输出错误信息并退出（不做复杂恢复）

## Markdown 生成细则

输出路径：目标 `.py` 同目录，文件名 `<目标文件夹名>_doc.md`

结构：
1) `## 文件概述`：`file_summary`
2) `## 函数概要`：表格 `函数名 | 入参 | 返回值 | 功能概述`

字段来源：
- 函数名：`qualname`
- 入参：从 AST 组装（参数名 + `*`/`**` 标记；默认值可选，过长省略）
- 返回值：
  - 优先：函数返回注解 `-> ...`（用 `ast.unparse` 展示）
  - 否则：从生成 docstring 的“返回值”段首行推断类型（`- (<type>):` 形式）
- 功能概述：`summary`（压成单行）

表格转义：将 `|` 替换为 `\\|`，换行压成空格，避免破坏表格。

## 测试策略（pytest，smoke + 边界）

目标：从 notebook 最小例子迁移为可回归的 `pytest`（<10s）。

拆分为可测的纯函数：
- `needs_update(existing_docstring) -> bool`
- `apply_updates(source_text, updates) -> new_source_text`
- `build_markdown(file_summary, rows) -> md_text`

测试使用 `tmp_path` 写入小型 `.py`，并用 Fake LLM 返回固定 JSON：
- 缺失 docstring → 插入成功
- 很短 docstring → 替换为 6 段模板
- 足够长且不含模板标题 → 保留不改
- `__dunder__` 方法 → 不更新
- 生成 `<文件夹名>_doc.md`，表格行数与函数数一致

## 后续迭代方向（可选）

- 大文件/超上下文的自动分块策略（按函数分块、多次请求）
- 引入 `libcst` 提升对“一行函数/复杂格式/注释保留”的修改鲁棒性
- 支持非交互 CLI 参数：`--file`、`--model`、`--dry-run`、`--only-missing` 等
- 生成更强的结构化文档（模块级能力表、类方法分组等）

