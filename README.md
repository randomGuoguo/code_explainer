# code_explainer

一个简单的 Python 脚本：输入（或通过命令行传入）目标 `.py` 文件路径，自动补全/补齐函数与类方法的 docstring（OpenAI API），并在同目录为每个文件生成 `<目标文件名stem>_doc.md`（文件概述 + 函数概要表）。

## Quickstart

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

PowerShell：
```powershell
$env:OPENAI_API_KEY="你的key"
python .\code_explainer.py
```

按提示输入目标 `.py` 路径即可。

多文件：
```powershell
python .\code_explainer.py .\a.py .\b.py
# 或（PowerShell 会自动展开）
python .\code_explainer.py *.py
```

自定义 Markdown 输出目录：
```powershell
python .\code_explainer.py .\a.py --md-out-dir .\docs\out
```

删除全部函数/方法 docstring：
```powershell
python .\code_explainer.py .\a.py --remove-docstrings-all
```

删除指定函数/方法 docstring：
```powershell
python .\code_explainer.py .\a.py --remove-docstrings foo Cls.bar
```

删除 docstring 时仍生成 Markdown：
```powershell
python .\code_explainer.py .\a.py --remove-docstrings-all --emit-md-when-removing
```

## 输出

- 原地修改目标 `.py`：仅插入/替换函数体开头的 docstring（不改逻辑代码）
- 同目录生成（每个 `.py` 一个）：`<目标文件名stem>_doc.md`（如 `a.py -> a_doc.md`）
- 传入 `--md-out-dir` 时，Markdown 改为输出到指定目录，文件名仍为 `<目标文件名stem>_doc.md`
- 删除模式默认只改 `.py` 不生成 Markdown；若需要报告，显式加 `--emit-md-when-removing`
