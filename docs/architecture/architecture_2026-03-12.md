# architecture_2026-03-12

## 0. 项目定位
- 项目名：`code_explainer`
- 目标：对目标 `.py` 文件中的顶层函数和类方法进行 docstring 补全，或删除已有 docstring，并按需输出对应的 Markdown 说明文档

## 1. 当前目录结构
- `code_explainer.py`
  - 当前项目的核心实现，包含 AST 扫描、docstring 更新/删除、Markdown 生成、CLI 入口
- `tests/`
  - `test_code_explainer.py`：核心回归测试
  - `tests_process.md`：测试总表
- `docs/spec/`
  - `coding_style.md`：开发与测试规范
- `docs/plans/`
  - 存放设计文档与实现计划
- `docs/tasks/`
  - 存放任务状态文档
- `docs/architecture/`
  - 存放架构文档

## 2. 核心模块划分

### 2.1 目标扫描层
- `scan_targets()`
  - 扫描源码中的目标对象
  - 当前只处理：
    - 模块顶层函数
    - 类方法
  - 跳过 `__dunder__`

### 2.2 docstring 判定与修改层
- `needs_update()`
  - 判断已有 docstring 是否需要补全
- `apply_docstring_updates()`
  - 对指定函数/方法插入或替换 docstring
- `remove_docstrings()`
  - 删除全部或指定 `qualname` 的 docstring
- 这部分统一依赖 AST 的 `lineno/end_lineno` 做行级替换，避免直接字符串搜索带来的误删

### 2.3 Markdown 生成层
- `build_markdown()`
  - 生成文件概述 + 函数概要表
- `resolve_md_output_path()`
  - 统一决定 Markdown 输出路径
  - 默认输出到目标 `.py` 同目录
  - 支持 `--md-out-dir`

### 2.4 LLM 交互层
- `build_prompt_payload()`
  - 生成要求 LLM 输出 JSON 的 prompt
- `call_openai_for_updates()`
  - 调用模型接口，获取 `file_summary + updates`
- `parse_llm_json()`
  - 校验返回 JSON 的基本结构

### 2.5 文件执行层
- `run_on_file()`
  - 单文件处理核心入口
  - 当前支持两种模式：
    - `generate`：补全/替换 docstring，并生成 Markdown
    - `remove`：删除 docstring；默认不生成 Markdown，只有开启 `emit_md_when_removing` 才生成

### 2.6 CLI 层
- `main()`
  - 批量接收 `.py` 路径并逐个处理
  - 当前主要参数：
    - `paths`
    - `--model`
    - `--md-out-dir`
    - `--remove-docstrings-all`
    - `--remove-docstrings`
    - `--emit-md-when-removing`

## 3. 当前执行流程

### 3.1 生成模式
1. 读取目标 `.py`
2. 用 AST 扫描目标函数/方法
3. 判断哪些 docstring 需要更新
4. 调用 LLM 生成 `file_summary` 和 `updates`
5. 将更新写回原 `.py`
6. 生成 `<stem>_doc.md`

### 3.2 删除模式
1. 读取目标 `.py`
2. 用 AST 扫描目标函数/方法
3. 根据“全部删除”或“指定 qualname 删除”决定目标集合
4. 删除函数体首条语句中的 docstring
5. 写回原 `.py`
6. 若显式开启 `--emit-md-when-removing`，再生成 `<stem>_doc.md`

## 4. 设计原则
- docstring 编辑基于 AST，不直接靠正则全局替换
- CLI 保持 MVP 风格，不引入子命令
- 默认行为保持兼容：不传删除参数时，仍是“补全 docstring + 生成 md”
- 测试优先覆盖关键行为：扫描、更新、删除、输出路径、模式分支

## 5. 当前限制
- 不处理嵌套函数、嵌套类、局部函数
- 不处理类级 docstring、模块级 docstring
- 删除模式下若指定不存在的 `qualname`，仅 warning，不中断执行
- 当前仍为单文件脚本实现，尚未拆分到 `src/` 包结构

## 6. 后续可演进方向
- 将核心逻辑从 `code_explainer.py` 拆到 `src/code_explainer/`
- 为 CLI 增加更细的单元测试或子命令化重构
- 为删除模式生成更完整的文件概述，而不是空 `file_summary`
- 增加对更多 Python 目标类型的支持，例如嵌套函数或静态分析更细粒度对象
