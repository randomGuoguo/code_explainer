# Tests Process

| 测试文件 | 测试时间 | 覆盖的测试样例 | 验证点 |
| --- | --- | --- | --- |
| `tests/test_code_explainer.py` | 2026-03-12 | `remove_docstrings` 删除全部 docstring；按 `qualname` 删除指定函数；`resolve_md_output_path` 默认/自定义输出目录；`run_on_file` 自定义 `md_out_dir`；删除模式默认不生成 md；删除模式显式生成 md；原有 docstring 补全与 Markdown 生成回归 | `python -m pytest -q tests/test_code_explainer.py` 与 `python -m pytest -q` 均通过，结果为 `19 passed`；确认 AST 删除仅作用于函数体首条 docstring，CLI 新参数未破坏原生成流程 |
