# Code Explainer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python CLI script that reads a target `.py`, fills missing/insufficient docstrings using the OpenAI API, writes docstrings back into the original file (in-place, no backup), and generates a sibling Markdown report `<target_folder>_doc.md` with a file summary + function overview table.

**Architecture:** Parse the file with `ast` to collect top-level functions and class methods (excluding `__dunder__`). Use a small heuristic to decide which existing docstrings are “insufficient”. Call OpenAI once to generate structured JSON containing `file_summary` and per-function docstring updates. Apply docstring insert/replace as minimal line-based edits (descending by line number). Generate Markdown from AST signatures + summaries.

**Tech Stack:** Python 3.11 stdlib (`ast`, `pathlib`, `dataclasses`, `json`, `re`) + `openai` SDK (Responses API) + `pytest` for fast regression tests.

---

## Pre-flight (one-time)

### Task 0: Set up local deps + test runner

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/test_code_explainer.py`

**Step 1: Write minimal dev requirements**

Create `requirements-dev.txt`:
```txt
openai
pytest
```

**Step 2: Install deps**

Run:
```bash
python -m pip install -r requirements-dev.txt
```
Expected: installs `openai` + `pytest`.

**Step 3: Create empty test file**

Create `tests/test_code_explainer.py` with:
```python
def test_placeholder():
    assert True
```

**Step 4: Run tests**

Run:
```bash
python -m pytest -q
```
Expected: PASS.

**Step 5: Commit (optional)**

If this directory is a git repo:
```bash
git add requirements-dev.txt tests/test_code_explainer.py
git commit -m "chore: add dev requirements and pytest"
```

---

## Core AST scan + heuristics

### Task 1: Implement AST target scanning (top-level + methods, skip dunder)

**Files:**
- Create: `code_explainer.py`
- Modify: `tests/test_code_explainer.py`

**Step 1: Write failing test for scanning**

Append to `tests/test_code_explainer.py`:
```python
import textwrap

from code_explainer import scan_targets


def test_scan_targets_top_level_and_methods_skip_dunder():
    src = textwrap.dedent(
        '''
        def a(x):
            return x

        class C:
            def m(self, y):
                return y
            def __repr__(self):
                return "C()"
        '''
    ).lstrip()

    qualnames = [t.qualname for t in scan_targets(src)]
    assert "a" in qualnames
    assert "C.m" in qualnames
    assert "C.__repr__" not in qualnames
```

**Step 2: Run test to verify it fails**

Run:
```bash
python -m pytest -q
```
Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `code_explainer`.

**Step 3: Write minimal implementation**

Create `code_explainer.py` with:
```python
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Target:
    qualname: str
    node: ast.AST


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def scan_targets(source_text: str) -> list[Target]:
    tree = ast.parse(source_text)
    targets: list[Target] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _is_dunder(node.name):
                targets.append(Target(qualname=node.name, node=node))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not _is_dunder(item.name):
                        targets.append(Target(qualname=f"{node.name}.{item.name}", node=item))
    return targets
```

**Step 4: Run tests**

Run:
```bash
python -m pytest -q
```
Expected: PASS.

**Step 5: Commit (optional)**
```bash
git add code_explainer.py tests/test_code_explainer.py
git commit -m "feat: scan top-level functions and class methods"
```

---

### Task 2: Add docstring “insufficient” heuristic (needs_update)

**Files:**
- Modify: `code_explainer.py`
- Modify: `tests/test_code_explainer.py`

**Step 1: Write failing tests for needs_update**

Append to `tests/test_code_explainer.py`:
```python
from code_explainer import needs_update


def test_needs_update_missing_docstring():
    assert needs_update(None) is True


def test_needs_update_short_docstring():
    assert needs_update("too short") is True


def test_needs_update_keeps_long_non_template_docstring():
    long_doc = "Line1\\n" + ("x" * 200)
    assert needs_update(long_doc) is False


def test_needs_update_template_missing_sections():
    doc = "功能描述:\\n- a\\n\\n参数:\\n- x (int): ...\\n"
    assert needs_update(doc) is True
```

**Step 2: Run tests to verify they fail**

Run:
```bash
python -m pytest -q
```
Expected: FAIL because `needs_update` is not defined.

**Step 3: Implement needs_update**

Modify `code_explainer.py` to add:
```python
TEMPLATE_KEYS = ("功能描述", "参数", "返回值", "关键规则", "示例", "实现说明")


def needs_update(existing_docstring: str | None) -> bool:
    if existing_docstring is None:
        return True

    text = existing_docstring.strip()
    if not text:
        return True

    nonempty_lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(nonempty_lines) < 3 or len(text) < 60:
        return True

    present = [k for k in TEMPLATE_KEYS if k in text]
    if present and len(present) != len(TEMPLATE_KEYS):
        return True

    return False
```

**Step 4: Run tests**

Run:
```bash
python -m pytest -q
```
Expected: PASS.

**Step 5: Commit (optional)**
```bash
git add code_explainer.py tests/test_code_explainer.py
git commit -m "feat: add needs_update heuristic for docstrings"
```

---

## Patching docstrings into source (line-based, minimal)

### Task 3: Format a docstring block and insert into missing-docstring functions

**Files:**
- Modify: `code_explainer.py`
- Modify: `tests/test_code_explainer.py`

**Step 1: Write failing test for insertion**

Append to `tests/test_code_explainer.py`:
```python
import ast

from code_explainer import apply_docstring_updates


def test_apply_docstring_updates_inserts_docstring():
    src = "def f(x):\\n    return x\\n"
    updated = apply_docstring_updates(
        source_text=src,
        updates={"f": "功能描述:\\n- demo\\n\\n参数:\\n- x (Any): ...\\n\\n返回值:\\n- (Any): ...\\n\\n关键规则:\\n- ...\\n\\n示例:\\n- ...\\n\\n实现说明(<=100字):\\n- ...\\n"},
    )
    assert '"""' in updated
    tree = ast.parse(updated)
    fn = tree.body[0]
    assert ast.get_docstring(fn) is not None
```

**Step 2: Run tests to verify they fail**
Run:
```bash
python -m pytest -q
```
Expected: FAIL because `apply_docstring_updates` not defined.

**Step 3: Implement minimal insertion-only patching**

Modify `code_explainer.py` to add:
```python
def _indent_of_line(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _format_docstring_block(docstring_text: str, indent: str) -> list[str]:
    safe = docstring_text.replace('"""', '\\"""')
    lines = safe.splitlines()
    out: list[str] = []
    out.append(f'{indent}"""\\n')
    for ln in lines:
        if ln.strip():
            out.append(f"{indent}{ln}\\n")
        else:
            out.append(f"{indent}\\n")
    out.append(f'{indent}"""\\n')
    return out


def apply_docstring_updates(*, source_text: str, updates: dict[str, str]) -> str:
    lines = source_text.splitlines(keepends=True)
    tree = ast.parse(source_text)

    inserts: list[tuple[int, list[str]]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name not in updates:
                continue
            if ast.get_docstring(node, clean=False) is not None:
                continue
            if not node.body:
                continue
            insert_at = node.body[0].lineno - 1
            indent = _indent_of_line(lines[insert_at])
            block = _format_docstring_block(updates[node.name], indent)
            inserts.append((insert_at, block))

    for insert_at, block in sorted(inserts, key=lambda x: x[0], reverse=True):
        lines[insert_at:insert_at] = block

    return "".join(lines)
```

**Step 4: Run tests**
Run:
```bash
python -m pytest -q
```
Expected: PASS.

**Step 5: Commit (optional)**
```bash
git add code_explainer.py tests/test_code_explainer.py
git commit -m "feat: insert generated docstrings into functions"
```

---

### Task 4: Replace existing docstrings and support class methods (non-dunder)

**Files:**
- Modify: `code_explainer.py`
- Modify: `tests/test_code_explainer.py`

**Step 1: Write failing tests for replacement + methods**

Append to `tests/test_code_explainer.py`:
```python
import ast
import textwrap

from code_explainer import apply_docstring_updates


def test_apply_docstring_updates_replaces_existing_docstring():
    src = textwrap.dedent(
        '''
        def f(x):
            "old"
            return x
        '''
    ).lstrip()
    updated = apply_docstring_updates(source_text=src, updates={"f": "功能描述:\\n- new"})
    fn = ast.parse(updated).body[0]
    assert ast.get_docstring(fn) == "功能描述:\\n- new"


def test_apply_docstring_updates_updates_class_method():
    src = textwrap.dedent(
        '''
        class C:
            def m(self, y):
                return y
        '''
    ).lstrip()
    updated = apply_docstring_updates(source_text=src, updates={"C.m": "功能描述:\\n- method"})
    cls = ast.parse(updated).body[0]
    m = cls.body[0]
    assert ast.get_docstring(m) == "功能描述:\\n- method"
```

**Step 2: Run tests to verify they fail**
Run:
```bash
python -m pytest -q
```
Expected: FAIL (replacement and `C.m` not supported yet).

**Step 3: Implement replacement + method traversal**

Update `apply_docstring_updates` to:
- Traverse module-level functions and `ClassDef` methods; build `qualname` (`f` / `C.m`)
- If docstring exists: find the first body statement, confirm it is a docstring `Expr(Constant(str))`, then replace lines `[lineno-1:end_lineno]` with formatted block.
- If missing: insert before first body statement.
- Apply operations in reverse line order (descending start line).

Pseudo-code to implement:
```python
ops: list[tuple[int, int | None, list[str]]] = []
# for each target
# if replace: (start, end, block)
# if insert: (start, None, block)
# then apply reverse
```

**Step 4: Run tests**
Run:
```bash
python -m pytest -q
```
Expected: PASS.

**Step 5: Commit (optional)**
```bash
git add code_explainer.py tests/test_code_explainer.py
git commit -m "feat: replace existing docstrings and handle class methods"
```

---

## Markdown report

### Task 5: Build Markdown report `<folder>_doc.md`

**Files:**
- Modify: `code_explainer.py`
- Modify: `tests/test_code_explainer.py`

**Step 1: Write failing tests for markdown**

Append to `tests/test_code_explainer.py`:
```python
from code_explainer import build_markdown


def test_build_markdown_contains_sections_and_table():
    md = build_markdown(
        file_summary="This file does X.",
        rows=[
            {"qualname": "a", "params": "x", "returns": "int", "summary": "do a"},
            {"qualname": "C.m", "params": "self, y", "returns": "", "summary": "do m"},
        ],
    )
    assert "## 文件概述" in md
    assert "## 函数概要" in md
    assert "| 函数名 | 入参 | 返回值 | 功能概述 |" in md
    assert "| a | x | int | do a |" in md
```

**Step 2: Run tests to verify they fail**
Run:
```bash
python -m pytest -q
```
Expected: FAIL because `build_markdown` not defined.

**Step 3: Implement build_markdown**

Add to `code_explainer.py`:
```python
def _md_escape_cell(text: str) -> str:
    return (text or "").replace("\\n", " ").replace("|", "\\\\|").strip()


def build_markdown(*, file_summary: str, rows: list[dict[str, str]]) -> str:
    out: list[str] = []
    out.append("## 文件概述\\n\\n")
    out.append(f"{file_summary.strip()}\\n\\n")
    out.append("## 函数概要\\n\\n")
    out.append("| 函数名 | 入参 | 返回值 | 功能概述 |\\n")
    out.append("| --- | --- | --- | --- |\\n")
    for r in rows:
        out.append(
            f"| {_md_escape_cell(r['qualname'])} | {_md_escape_cell(r['params'])} | {_md_escape_cell(r['returns'])} | {_md_escape_cell(r['summary'])} |\\n"
        )
    return "".join(out)
```

**Step 4: Run tests**
Run:
```bash
python -m pytest -q
```
Expected: PASS.

**Step 5: Commit (optional)**
```bash
git add code_explainer.py tests/test_code_explainer.py
git commit -m "feat: generate markdown file summary and function table"
```

---

## OpenAI integration (real + fake for tests)

### Task 6: Define LLM result contract + implement Fake LLM for tests

**Files:**
- Modify: `code_explainer.py`
- Modify: `tests/test_code_explainer.py`

**Step 1: Add a failing test for parsing LLM JSON**

Append to `tests/test_code_explainer.py`:
```python
import json

from code_explainer import parse_llm_json


def test_parse_llm_json_happy_path():
    payload = {
        "file_summary": "sum",
        "updates": [{"qualname": "a", "docstring": "功能描述:\\n- x", "summary": "do a"}],
    }
    parsed = parse_llm_json(json.dumps(payload))
    assert parsed["file_summary"] == "sum"
    assert parsed["updates"][0]["qualname"] == "a"
```

**Step 2: Run tests to verify they fail**
Run:
```bash
python -m pytest -q
```
Expected: FAIL because `parse_llm_json` not defined.

**Step 3: Implement parse_llm_json (strict-ish)**

Add to `code_explainer.py`:
```python
import json


def parse_llm_json(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("LLM JSON must be an object")
    if "file_summary" not in data or "updates" not in data:
        raise ValueError("missing required keys")
    if not isinstance(data["updates"], list):
        raise TypeError("updates must be a list")
    return data
```

**Step 4: Run tests**
Run:
```bash
python -m pytest -q
```
Expected: PASS.

**Step 5: Commit (optional)**
```bash
git add code_explainer.py tests/test_code_explainer.py
git commit -m "feat: add LLM JSON contract parser"
```

---

### Task 7: Implement real OpenAI call (Responses API) behind a small function

**Files:**
- Modify: `code_explainer.py`
- Modify: `tests/test_code_explainer.py`

**Step 1: Write a test that uses a fake client (no network)**

Append to `tests/test_code_explainer.py`:
```python
from code_explainer import build_prompt_payload


def test_build_prompt_payload_contains_function_list():
    payload = build_prompt_payload(
        source_text="def a(x):\\n    return x\\n",
        target_qualnames=["a"],
    )
    assert "a" in payload
```

**Step 2: Run tests to verify they fail**
Run:
```bash
python -m pytest -q
```
Expected: FAIL because `build_prompt_payload` not defined.

**Step 3: Implement prompt payload builder + OpenAI call**

In `code_explainer.py`, implement:
- `build_prompt_payload(source_text, target_qualnames) -> str` that includes:
  - your docstring template headings and constraints
  - list of functions to update (qualnames)
  - full source text
- `call_openai_for_updates(prompt_text, model="gpt-4.1") -> dict`:
  - `from openai import OpenAI`
  - `client = OpenAI()`
  - `resp = client.responses.create(model=model, input=[{"role":"user","content": prompt_text}])`
  - `return parse_llm_json(resp.output_text)`

Optional (recommended): use Structured Outputs if available:
```python
resp = client.responses.create(
    model=model,
    input=[{"role": "user", "content": prompt_text}],
    text={"format": {"type": "json_schema", "name": "code_explainer", "strict": True, "schema": {...}}},
)
data = json.loads(resp.output_text)
```
If the API returns a “format not supported” error, fall back to plain JSON-in-text + retry once.

**Step 4: Run tests**
Run:
```bash
python -m pytest -q
```
Expected: PASS (tests only cover prompt builder; OpenAI call remains untested and is exercised manually).

**Step 5: Commit (optional)**
```bash
git add code_explainer.py tests/test_code_explainer.py
git commit -m "feat: add OpenAI Responses API integration"
```

---

## End-to-end command flow (interactive input, writes .py + .md)

### Task 8: Wire end-to-end runner and file I/O

**Files:**
- Modify: `code_explainer.py`
- Modify: `tests/test_code_explainer.py`

**Step 1: Write failing e2e-ish test using a fake LLM result**

Append to `tests/test_code_explainer.py`:
```python
from pathlib import Path

from code_explainer import run_on_file


def test_run_on_file_writes_md_and_updates_py(tmp_path: Path):
    target_dir = tmp_path / "proj"
    target_dir.mkdir()
    py = target_dir / "t.py"
    py.write_text("def a(x):\\n    return x\\n", encoding="utf-8")

    def fake_llm(_source_text: str, _qualnames: list[str]):
        return {
            "file_summary": "sum",
            "updates": [{"qualname": "a", "docstring": "功能描述:\\n- demo", "summary": "do a"}],
        }

    run_on_file(py, llm=fake_llm)

    assert "功能描述" in py.read_text(encoding="utf-8")
    assert (target_dir / "proj_doc.md").exists()
```

**Step 2: Run tests to verify they fail**
Run:
```bash
python -m pytest -q
```
Expected: FAIL because `run_on_file` not defined.

**Step 3: Implement run_on_file**

In `code_explainer.py`, implement:
- `run_on_file(path: Path, llm: Callable | None = None, model="gpt-4.1") -> None`
  - read file text (use `utf-8-sig` to handle BOM)
  - `targets = scan_targets(text)`
  - decide which qualnames need updates using `needs_update(ast.get_docstring(..., clean=False))`
  - call `llm(text, qualnames_to_update)` if provided, else call OpenAI
  - `apply_docstring_updates(...)` for updates only
  - generate Markdown rows for *all* scanned targets:
    - params from AST signature
    - returns from annotation or empty
    - summary: LLM summary if available else first non-empty line of existing docstring (or "")
  - write updated `.py` back in-place (preserve trailing newline)
  - write `<folder>_doc.md` in same directory

**Step 4: Run tests**
Run:
```bash
python -m pytest -q
```
Expected: PASS.

**Step 5: Commit (optional)**
```bash
git add code_explainer.py tests/test_code_explainer.py
git commit -m "feat: end-to-end runner writes updated py and markdown report"
```

---

### Task 9: Add interactive CLI entrypoint

**Files:**
- Modify: `code_explainer.py`

**Step 1: Add a `main()` that prompts for file path**

In `code_explainer.py` add:
```python
def main() -> None:
    raw = input("请输入待解析的 .py 文件路径: ").strip().strip('\"')
    if not raw:
        raise SystemExit("empty path")
    from pathlib import Path
    run_on_file(Path(raw))


if __name__ == "__main__":
    main()
```

**Step 2: Manual run**

Set key (Windows PowerShell):
```powershell
$env:OPENAI_API_KEY="..."
```

Run:
```bash
python code_explainer.py
```

Input: `D:\\path\\to\\target.py`

Expected:
- target file updated with docstrings
- `<target_folder>_doc.md` created next to it

**Step 3: Commit (optional)**
```bash
git add code_explainer.py
git commit -m "feat: interactive CLI for docstring completion"
```

---

## Acceptance checklist

- [ ] Running `python code_explainer.py` prompts for a `.py` path and completes without crashing
- [ ] Updates only top-level functions + class methods; skips `__dunder__`
- [ ] Missing/insufficient docstrings are filled to the 6-section template; sufficient ones remain unchanged
- [ ] Generates `<target_folder>_doc.md` with file summary + function table
- [ ] `python -m pytest -q` passes in <10s

