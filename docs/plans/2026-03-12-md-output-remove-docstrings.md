# Md Output Dir And Remove Docstrings Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a configurable Markdown output directory and a docstring removal mode that can delete all or selected function/method docstrings.

**Architecture:** Keep `run_on_file()` as the single-file worker and extend it with explicit modes instead of introducing subcommands. Reuse the current AST line-based docstring editing approach for both replacement and deletion, and centralize Markdown path resolution in one helper.

**Tech Stack:** Python stdlib (`argparse`, `ast`, `pathlib`), existing `pytest` suite.

---

### Task 1: Add focused failing tests for new pure helpers

**Files:**
- Modify: `tests/test_code_explainer.py`
- Modify: `code_explainer.py`

**Step 1: Write the failing test**

Add tests for:

- removing all docstrings from top-level functions and class methods
- removing only named qualnames
- resolving default and custom Markdown output paths

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_code_explainer.py`
Expected: FAIL because helper functions do not exist yet.

**Step 3: Write minimal implementation**

Add:

- `resolve_md_output_path(target_path, md_out_dir)`
- `remove_docstrings(source_text, qualnames)`

Reusing the existing AST scan and line replacement strategy.

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_code_explainer.py`
Expected: helper tests PASS.

**Step 5: Commit**

```bash
git add code_explainer.py tests/test_code_explainer.py
git commit -m "feat: add md path and docstring removal helpers"
```

### Task 2: Extend single-file execution modes

**Files:**
- Modify: `code_explainer.py`
- Modify: `tests/test_code_explainer.py`

**Step 1: Write the failing test**

Add tests for:

- `run_on_file(..., md_out_dir=...)` writes Markdown to the given directory
- removal mode deletes docstrings and skips Markdown by default
- removal mode with Markdown emission enabled writes output

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_code_explainer.py`
Expected: FAIL because `run_on_file()` does not accept the new options.

**Step 3: Write minimal implementation**

Extend `run_on_file()` with:

- `mode`
- `remove_qualnames`
- `emit_md_when_removing`
- `md_out_dir`

Generate mode keeps current LLM flow. Remove mode updates source text without calling LLM unless Markdown emission is requested.

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_code_explainer.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add code_explainer.py tests/test_code_explainer.py
git commit -m "feat: support remove mode in run_on_file"
```

### Task 3: Extend CLI and README

**Files:**
- Modify: `code_explainer.py`
- Modify: `README.md`

**Step 1: Write the failing test (optional)**

Keep this task CLI-light; no subprocess coverage required for MVP.

**Step 2: Implement CLI parsing**

Add:

- `--md-out-dir`
- `--remove-docstrings-all`
- `--remove-docstrings`
- `--emit-md-when-removing`

Use an `argparse` mutually exclusive group for the two remove flags and pass the resolved mode/options into `run_on_file()`.

**Step 3: Update README**

Add examples for:

- custom Markdown output directory
- remove all docstrings
- remove specific docstrings
- emit Markdown while removing

**Step 4: Run tests**

Run: `python -m pytest -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add code_explainer.py README.md tests/test_code_explainer.py
git commit -m "feat: add md output dir and docstring removal cli"
```
