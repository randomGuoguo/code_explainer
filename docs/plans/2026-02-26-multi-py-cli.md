# Multi-Py CLI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow running `code_explainer.py` once to process multiple `.py` files via CLI args, while keeping the existing interactive single-file mode.

**Architecture:** Keep `run_on_file()` as the per-file worker; extend `main()` to parse positional paths and iterate sequentially. Emit one Markdown per input file using `<stem>_doc.md` to avoid collisions.

**Tech Stack:** Python stdlib (`argparse`, `pathlib`, `sys`), existing `run_on_file()` pipeline, `pytest`.

---

### Task 1: Change Markdown output naming to per-file

**Files:**
- Modify: `code_explainer.py:505` (function `run_on_file`)
- Test: `tests/test_code_explainer.py`

**Step 1: Write the failing test**

- Update `tests/test_code_explainer.py::test_run_on_file_writes_md_and_updates_py` to expect `t_doc.md` (not `proj_doc.md`).

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q`
Expected: FAIL because the script still writes `proj_doc.md`.

**Step 3: Write minimal implementation**

- In `run_on_file()`, change:
  - from: `<目标文件夹名>_doc.md`
  - to: `<目标文件名stem>_doc.md`
- Implementation: `md_path = target_path.with_name(f"{target_path.stem}_doc.md")`

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add code_explainer.py tests/test_code_explainer.py
git commit -m "feat: write per-file markdown doc"
```

### Task 2: Add CLI multi-file args (keep interactive fallback)

**Files:**
- Modify: `code_explainer.py:615` (function `main`)
- Modify: `README.md`

**Step 1: Write the failing test (optional)**

- (Optional) Add a small test that calls a new helper like `run_cli(argv)` with two temp `.py` files and asserts two `*_doc.md` are created.

**Step 2: Implement argument parsing**

- Use `argparse` with positional `paths` (`nargs="*"`) and optional `--model` (default keep current behavior).
- If `paths` is empty, keep `input()` path prompt.
- If `paths` is non-empty, iterate each path:
  - validate exists and suffix is `.py`
  - call `run_on_file(path, model=args.model)`
  - on error: print and continue
- Return an exit code (0 all ok, 1 if any failed) and `raise SystemExit(code)` in `__main__`.

**Step 3: Update README**

- Add example: `python .\\code_explainer.py a.py b.py`
- Explain Markdown naming: `a.py -> a_doc.md`

**Step 4: Run tests**

Run: `python -m pytest -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add code_explainer.py README.md tests/test_code_explainer.py
git commit -m "feat: support multi-file CLI args"
```

