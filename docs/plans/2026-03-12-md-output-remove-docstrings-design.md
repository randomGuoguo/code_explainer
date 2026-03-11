# 2026-03-12 Markdown 输出目录与 Docstring 删除设计

状态：已与用户确认并通过（Design）

## 背景

当前 `code_explainer.py` 仅支持：

- 原地补全/替换目标 `.py` 中的函数与类方法 docstring
- 将 Markdown 报告固定输出到目标文件同目录，文件名为 `<stem>_doc.md`

用户希望补充两个能力：

- 指定生成的 `.md` 输出目录
- 删除指定 `.py` 文件中所有函数或指定函数的 docstring

## 目标（Goals）

- 新增 `--md-out-dir DIR`，仅支持指定 Markdown 输出目录。
- 新增删除模式，支持：
  - 删除全部目标函数/方法 docstring
  - 删除指定 qualname 的 docstring
- 删除模式下支持两种行为：
  - 默认只删除 `.py` 中的 docstring，不生成 `.md`
  - 通过参数显式开启“删除后仍生成 `.md`”
- 保持现有默认行为兼容：不传删除参数时，仍执行“补全 docstring + 生成 md”。

## 非目标（Non-goals）

- 不改为子命令式 CLI。
- 不支持为多文件分别指定不同输出目录。
- 不处理嵌套函数、嵌套类方法、属性 getter/setter 等超出当前扫描范围的对象。
- 不为不存在的 qualname 抛出致命错误。

## CLI 设计

### 新增参数

- `--md-out-dir DIR`
  - 仅在需要生成 Markdown 时生效
  - 不存在则自动创建
- `--remove-docstrings-all`
  - 删除当前目标 `.py` 中所有“可扫描到的目标函数/方法”docstring
- `--remove-docstrings NAME [NAME ...]`
  - 删除指定 qualname 列表，如 `foo`、`Cls.bar`
- `--emit-md-when-removing`
  - 删除模式下显式开启 Markdown 生成

### 参数关系

- `--remove-docstrings-all` 与 `--remove-docstrings` 互斥
- 不传删除参数：按现有生成模式执行
- 传删除参数：进入删除模式
- 删除模式下，仅当传入 `--emit-md-when-removing` 时生成 Markdown

## 核心实现

### 1. Markdown 输出路径

- 新增小函数统一解析 Markdown 目标路径：
  - 默认：`target_path.with_name(f"{target_path.stem}_doc.md")`
  - 自定义目录：`Path(md_out_dir) / f"{target_path.stem}_doc.md"`
- 目录不存在时，调用 `mkdir(parents=True, exist_ok=True)`

### 2. Docstring 删除

- 新增 `remove_docstrings(source_text, qualnames)`：
  - 复用 AST 扫描的 `qualname -> function node` 识别逻辑
  - 仅当函数体第一条语句是字符串表达式时，判定为 docstring 并删除
  - 删除全部时处理所有可扫描目标
  - 按 qualname 删除时仅处理命中的函数/方法
- 删除实现继续基于 `lineno/end_lineno` 行级替换，和现有 `apply_docstring_updates()` 一致

### 3. 运行模式

- 在 `run_on_file()` 中引入模式参数：
  - `generate`：现有流程
  - `remove`：删除 docstring，可选生成 Markdown
- 删除模式下：
  - 默认不调用 LLM
  - 若显式开启 Markdown 生成，则基于更新后的源码直接生成 Markdown 概览

## 边界与错误处理

- 指定不存在的 qualname 时仅输出提示，不中断其它文件处理
- 删除模式仍保持“单文件失败不阻塞其它文件”
- 仅删除函数体首条语句 docstring，不删除普通字符串常量
- 继续仅处理模块顶层函数与类方法，跳过 `__dunder__`

## 测试与文档

- `tests/test_code_explainer.py`
  - 增加 `remove_docstrings()` 的全部删除、按 qualname 删除、无 docstring 跳过测试
  - 增加 Markdown 输出路径解析测试
  - 增加 `run_on_file()` 在自定义 `md_out_dir`、删除模式默认不生成 md、删除模式显式生成 md 的测试
- `README.md`
  - 增加新 CLI 参数示例
  - 说明删除模式与自定义 Markdown 输出目录
