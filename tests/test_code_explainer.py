def test_placeholder():
    assert True


def test_scan_targets_top_level_and_methods_skip_dunder():
    import textwrap

    from code_explainer import scan_targets

    src = textwrap.dedent(
        """
        def a(x):
            return x

        class C:
            def m(self, y):
                return y

            def __repr__(self):
                return "C()"
        """
    ).lstrip()

    qualnames = [target.qualname for target in scan_targets(src)]
    assert "a" in qualnames
    assert "C.m" in qualnames
    assert "C.__repr__" not in qualnames


def test_needs_update_missing_docstring():
    from code_explainer import needs_update

    assert needs_update(None) is True


def test_needs_update_short_docstring():
    from code_explainer import needs_update

    assert needs_update("too short") is True


def test_needs_update_keeps_long_non_template_docstring():
    from code_explainer import needs_update

    long_doc = "Line1\n" + ("x" * 200)
    assert needs_update(long_doc) is False


def test_needs_update_template_missing_sections():
    from code_explainer import needs_update

    doc = "功能描述:\n- a\n\n参数:\n- x (int): ...\n"
    assert needs_update(doc) is True


def test_apply_docstring_updates_inserts_docstring():
    import ast

    from code_explainer import apply_docstring_updates

    src = "def f(x):\n    return x\n"
    updated = apply_docstring_updates(
        source_text=src,
        updates={
            "f": "功能描述:\n- demo\n\n参数:\n- x (Any): ...\n\n返回值:\n- (Any): ...\n\n关键规则:\n- ...\n\n示例:\n- ...\n\n实现说明(<=100字):\n- ...\n"
        },
    )

    assert '"""' in updated
    tree = ast.parse(updated)
    fn = tree.body[0]
    assert ast.get_docstring(fn) is not None


def test_apply_docstring_updates_replaces_existing_docstring():
    import ast
    import textwrap

    from code_explainer import apply_docstring_updates

    src = textwrap.dedent(
        '''
        def f(x):
            "old"
            return x
        '''
    ).lstrip()
    updated = apply_docstring_updates(source_text=src, updates={"f": "功能描述:\n- new"})
    fn = ast.parse(updated).body[0]
    assert ast.get_docstring(fn) == "功能描述:\n- new"


def test_apply_docstring_updates_updates_class_method():
    import ast
    import textwrap

    from code_explainer import apply_docstring_updates

    src = textwrap.dedent(
        '''
        class C:
            def m(self, y):
                return y
        '''
    ).lstrip()
    updated = apply_docstring_updates(source_text=src, updates={"C.m": "功能描述:\n- method"})
    cls = ast.parse(updated).body[0]
    method = cls.body[0]
    assert ast.get_docstring(method) == "功能描述:\n- method"


def test_remove_docstrings_removes_all_targets():
    import ast
    import textwrap

    from code_explainer import remove_docstrings

    src = textwrap.dedent(
        '''
        def f(x):
            "old"
            return x

        class C:
            def m(self, y):
                "method"
                return y
        '''
    ).lstrip()

    updated = remove_docstrings(source_text=src)
    tree = ast.parse(updated)
    assert ast.get_docstring(tree.body[0]) is None
    assert ast.get_docstring(tree.body[1].body[0]) is None


def test_remove_docstrings_only_removes_selected_qualnames():
    import ast
    import textwrap

    from code_explainer import remove_docstrings

    src = textwrap.dedent(
        '''
        def f(x):
            "old"
            return x

        class C:
            def m(self, y):
                "method"
                return y
        '''
    ).lstrip()

    updated = remove_docstrings(source_text=src, qualnames={"C.m"})
    tree = ast.parse(updated)
    assert ast.get_docstring(tree.body[0]) == "old"
    assert ast.get_docstring(tree.body[1].body[0]) is None


def test_resolve_md_output_path_supports_default_and_custom_dir(tmp_path):
    from pathlib import Path

    from code_explainer import resolve_md_output_path

    target_path = Path(tmp_path) / "proj" / "a.py"
    target_path.parent.mkdir(parents=True)
    target_path.write_text("def a():\n    return 1\n", encoding="utf-8")

    default_md_path = resolve_md_output_path(target_path)
    custom_md_path = resolve_md_output_path(target_path, Path(tmp_path) / "docs" / "out")

    assert default_md_path == target_path.parent / "a_doc.md"
    assert custom_md_path == Path(tmp_path) / "docs" / "out" / "a_doc.md"
    assert custom_md_path.parent.exists()


def test_build_markdown_contains_sections_and_table():
    from code_explainer import build_markdown

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


def test_parse_llm_json_happy_path():
    import json

    from code_explainer import parse_llm_json

    payload = {
        "file_summary": "sum",
        "updates": [{"qualname": "a", "docstring": "功能描述:\n- x", "summary": "do a"}],
    }
    parsed = parse_llm_json(json.dumps(payload))
    assert parsed["file_summary"] == "sum"
    assert parsed["updates"][0]["qualname"] == "a"


def test_build_prompt_payload_contains_function_list():
    from code_explainer import build_prompt_payload

    payload = build_prompt_payload(
        source_text="def a(x):\n    return x\n",
        target_qualnames=["a"],
    )
    assert "a" in payload


def test_run_on_file_writes_md_and_updates_py(tmp_path):
    from pathlib import Path

    from code_explainer import run_on_file

    target_dir = Path(tmp_path) / "proj"
    target_dir.mkdir()
    py_path = target_dir / "t.py"
    py_path.write_text("def a(x):\n    return x\n", encoding="utf-8")

    def fake_llm(_source_text: str, _qualnames: list[str]):
        return {
            "file_summary": "sum",
            "updates": [{"qualname": "a", "docstring": "功能描述:\n- demo", "summary": "do a"}],
        }

    run_on_file(py_path, llm=fake_llm)

    assert "功能描述" in py_path.read_text(encoding="utf-8")
    assert (target_dir / "t_doc.md").exists()


def test_run_on_file_supports_custom_md_out_dir(tmp_path):
    from pathlib import Path

    from code_explainer import run_on_file

    target_dir = Path(tmp_path) / "proj"
    md_dir = Path(tmp_path) / "docs" / "out"
    target_dir.mkdir()
    py_path = target_dir / "t.py"
    py_path.write_text("def a(x):\n    return x\n", encoding="utf-8")

    def fake_llm(_source_text: str, _qualnames: list[str]):
        return {
            "file_summary": "sum",
            "updates": [{"qualname": "a", "docstring": "功能描述:\n- demo", "summary": "do a"}],
        }

    run_on_file(py_path, llm=fake_llm, md_out_dir=md_dir)

    assert (md_dir / "t_doc.md").exists()
    assert not (target_dir / "t_doc.md").exists()


def test_run_on_file_remove_mode_skips_md_by_default(tmp_path):
    from pathlib import Path

    from code_explainer import run_on_file

    target_dir = Path(tmp_path) / "proj"
    target_dir.mkdir()
    py_path = target_dir / "t.py"
    py_path.write_text('def a(x):\n    "old"\n    return x\n', encoding="utf-8")

    run_on_file(py_path, mode="remove")

    assert '"old"' not in py_path.read_text(encoding="utf-8")
    assert not (target_dir / "t_doc.md").exists()


def test_run_on_file_remove_mode_can_emit_md(tmp_path):
    from pathlib import Path

    from code_explainer import run_on_file

    target_dir = Path(tmp_path) / "proj"
    md_dir = Path(tmp_path) / "docs"
    target_dir.mkdir()
    py_path = target_dir / "t.py"
    py_path.write_text('def a(x) -> int:\n    "old"\n    return x\n', encoding="utf-8")

    run_on_file(py_path, mode="remove", emit_md_when_removing=True, md_out_dir=md_dir)

    assert '"old"' not in py_path.read_text(encoding="utf-8")
    assert (md_dir / "t_doc.md").exists()
