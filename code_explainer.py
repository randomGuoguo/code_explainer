from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Target:
    qualname: str
    node: ast.AST


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def scan_targets(source_text: str) -> list[Target]:
    """
    功能描述:
    - 扫描 Python 源码，提取“模块顶层函数 + 类方法”的目标列表（跳过 __dunder__）。

    参数:
    - source_text (str): Python 源码文本

    返回值:
    - (list[Target]): 目标函数/方法列表，qualname 形如 `foo` / `Cls.bar`

    关键规则:
    - 仅包含顶层 `def/async def` 与 `class` 内的方法
    - 跳过 __dunder__，保留 `_private`

    示例:
    - `scan_targets("def a(): ...")` -> `[Target("a", ...)]`

    实现说明(<=100字):
    - 用 `ast.parse` 遍历模块 body；遇到函数直接收集，遇到类则遍历其 body 收集方法。
    """

    tree = ast.parse(source_text)
    targets: list[Target] = []

    for top_level_node in tree.body:
        if isinstance(top_level_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _is_dunder(top_level_node.name):
                targets.append(Target(qualname=top_level_node.name, node=top_level_node))
            continue

        if isinstance(top_level_node, ast.ClassDef):
            class_name = top_level_node.name
            for class_item in top_level_node.body:
                if isinstance(class_item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not _is_dunder(class_item.name):
                        targets.append(
                            Target(qualname=f"{class_name}.{class_item.name}", node=class_item)
                        )

    return targets


TEMPLATE_KEYS: tuple[str, ...] = ("功能描述", "参数", "返回值", "关键规则", "示例", "实现说明")


def needs_update(existing_docstring: str | None) -> bool:
    """
    功能描述:
    - 判断一个已有 docstring 是否“不足”，不足则需要补全/重写为统一模板风格。

    参数:
    - existing_docstring (str | None): `ast.get_docstring(..., clean=False)` 的返回值

    返回值:
    - (bool): True 表示需要补全；False 表示保留原 docstring

    关键规则:
    - 缺失/空 docstring 一律需要补全
    - 明显过短（行数或字符数过少）需要补全
    - 若已出现模板段标题但不齐全，视为“不足”并补齐为完整 6 段

    示例:
    - `needs_update(None)` -> True
    - `needs_update("Line1\\n" + "x"*200)` -> False

    实现说明(<=100字):
    - 先做空/短判断，再检测模板关键段落是否部分出现但不完整。
    """

    if existing_docstring is None:
        return True

    text = existing_docstring.strip()
    if not text:
        return True

    nonempty_lines = [line_text for line_text in text.splitlines() if line_text.strip()]
    if len(text) < 60:
        return True
    if len(nonempty_lines) < 3 and len(text) < 120:
        return True

    present_keys = [key for key in TEMPLATE_KEYS if key in text]
    if present_keys and len(present_keys) != len(TEMPLATE_KEYS):
        return True

    return False


def _indent_of_line(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _format_docstring_block(docstring_text: str, indent: str) -> list[str]:
    safe_text = docstring_text.replace('"""', '\\"""').rstrip()
    content_lines = safe_text.splitlines()

    block_lines: list[str] = [f'{indent}"""\n']
    for content_line in content_lines:
        if content_line.strip():
            block_lines.append(f"{indent}{content_line}\n")
        else:
            block_lines.append(f"{indent}\n")
    block_lines.append(f'{indent}"""\n')
    return block_lines


def _iter_qualname_function_nodes(
    tree: ast.Module,
) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    out: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for top_level_node in tree.body:
        if isinstance(top_level_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((top_level_node.name, top_level_node))
            continue

        if isinstance(top_level_node, ast.ClassDef):
            class_name = top_level_node.name
            for class_item in top_level_node.body:
                if isinstance(class_item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append((f"{class_name}.{class_item.name}", class_item))

    return out


def apply_docstring_updates(*, source_text: str, updates: dict[str, str]) -> str:
    """
    功能描述:
    - 将 `updates` 中的 docstring（按 qualname）插入/替换到源代码对应函数/方法的函数体开头。

    参数:
    - source_text (str): 原始 Python 源码文本
    - updates (dict[str, str]): qualname -> docstring 文本（不含三引号）

    返回值:
    - (str): 更新后的源码文本

    关键规则:
    - 仅修改函数/方法的 docstring，不改动其它逻辑代码
    - 对于已有 docstring：替换第一条字符串表达式语句范围
    - 对于缺失 docstring：在函数体第一条语句之前插入

    示例:
    - `apply_docstring_updates(source_text, {"foo": "功能描述:\\n- ..."})`

    实现说明(<=100字):
    - 基于 AST 的 `lineno/end_lineno` 做行级替换/插入，并按行号倒序应用，避免位移影响。
    """

    if not updates:
        return source_text

    lines = source_text.splitlines(keepends=True)
    tree = ast.parse(source_text)

    ops: list[tuple[int, int | None, list[str]]] = []
    for qualname, function_node in _iter_qualname_function_nodes(tree):
        if qualname not in updates:
            continue
        if _is_dunder(function_node.name):
            continue
        if not function_node.body:
            continue

        first_stmt = function_node.body[0]
        if getattr(first_stmt, "lineno", 0) <= getattr(function_node, "lineno", 0):
            continue

        indent = _indent_of_line(lines[first_stmt.lineno - 1])
        new_block = _format_docstring_block(updates[qualname], indent)

        doc_expr: ast.stmt | None = None
        if (
            isinstance(first_stmt, ast.Expr)
            and isinstance(first_stmt.value, ast.Constant)
            and isinstance(first_stmt.value.value, str)
        ):
            doc_expr = first_stmt

        if doc_expr is None:
            insert_at = first_stmt.lineno - 1
            ops.append((insert_at, None, new_block))
            continue

        start_line = doc_expr.lineno - 1
        end_line = (doc_expr.end_lineno or doc_expr.lineno) - 1
        ops.append((start_line, end_line, new_block))

    for start_line, end_line, new_block in sorted(ops, key=lambda x: x[0], reverse=True):
        if end_line is None:
            lines[start_line:start_line] = new_block
        else:
            lines[start_line : end_line + 1] = new_block

    return "".join(lines)


def _md_escape_cell(text: str) -> str:
    return (text or "").replace("\n", " ").replace("|", "\\|").strip()


def build_markdown(*, file_summary: str, rows: list[dict[str, str]]) -> str:
    """
    功能描述:
    - 生成 Markdown 报告：文件概述 + 函数概要表格。

    参数:
    - file_summary (str): 文件整体概述
    - rows (list[dict[str, str]]): 表格行数据（qualname/params/returns/summary）

    返回值:
    - (str): Markdown 文本

    关键规则:
    - 表格内需转义 `|`，并把换行压成空格
    - 表头固定：函数名｜入参｜返回值｜功能概述

    示例:
    - `build_markdown(file_summary="...", rows=[...])`

    实现说明(<=100字):
    - 直接拼接字符串；对每个单元格做最小转义以避免破坏表格。
    """

    parts: list[str] = []
    parts.append("## 文件概述\n\n")
    parts.append(f"{file_summary.strip()}\n\n")
    parts.append("## 函数概要\n\n")
    parts.append("| 函数名 | 入参 | 返回值 | 功能概述 |\n")
    parts.append("| --- | --- | --- | --- |\n")
    for row in rows:
        parts.append(
            f"| {_md_escape_cell(row.get('qualname', ''))} | {_md_escape_cell(row.get('params', ''))} | {_md_escape_cell(row.get('returns', ''))} | {_md_escape_cell(row.get('summary', ''))} |\n"
        )
    return "".join(parts)


def parse_llm_json(text: str) -> dict:
    """
    功能描述:
    - 解析并校验 LLM 返回的 JSON 文本，确保具备最基本的字段结构。

    参数:
    - text (str): LLM 输出（应为严格 JSON）

    返回值:
    - (dict): 解析后的对象（至少包含 file_summary 与 updates）

    关键规则:
    - 必须是 JSON object
    - 必须包含 `file_summary: str` 与 `updates: list`

    示例:
    - `parse_llm_json('{"file_summary":"...","updates":[]}')`

    实现说明(<=100字):
    - 用 `json.loads` 解析并做轻量类型校验；更严格校验留待后续迭代。
    """

    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("LLM JSON must be an object")
    if "file_summary" not in data or "updates" not in data:
        raise ValueError("LLM JSON missing required keys: file_summary/updates")
    if not isinstance(data["file_summary"], str):
        raise TypeError("file_summary must be a string")
    if not isinstance(data["updates"], list):
        raise TypeError("updates must be a list")
    return data


def build_prompt_payload(*, source_text: str, target_qualnames: list[str]) -> str:
    """
    功能描述:
    - 构建用于 OpenAI 的 prompt：要求输出结构化 JSON，包含文件概述与 docstring 更新列表。

    参数:
    - source_text (str): 目标 .py 源码（完整文本）
    - target_qualnames (list[str]): 需要补全/重写 docstring 的函数/方法 qualname 列表

    返回值:
    - (str): 可直接发送给 LLM 的 prompt 文本

    关键规则:
    - 只允许输出 JSON（不得包含解释性文字/markdown/代码块）
    - docstring 内容不包含三引号
    - docstring 使用 6 段模板：功能描述/参数/返回值/关键规则/示例/实现说明(<=100字)

    示例:
    - `build_prompt_payload(source_text, ["foo", "Cls.bar"])`

    实现说明(<=100字):
    - 直接拼接指令、目标 qualname 列表与源码文本；后续可改为 messages 结构。
    """

    targets_text = "\n".join(f"- {name}" for name in target_qualnames) or "- (none)"
    return (
        "你是一个资深 Python 代码审阅助手。\n"
        "你的任务：根据给定源码，为指定函数/方法生成或补全 docstring，并给出文件整体概述。\n"
        "\n"
        "输出要求（必须严格遵守）：\n"
        "1) 你必须且只能输出一个 JSON object（不要任何额外文字）。\n"
        "2) JSON 结构：\n"
        '   {"file_summary": string, "updates": [{"qualname": string, "docstring": string, "summary": string}, ...]}\n'
        "3) `updates` 只包含我提供的 qualname（不要输出其它函数）。\n"
        "4) `docstring` 字段是不包含三引号的纯文本，按以下 6 段标题组织（中文为主，术语保留英文；不同参数、返回值需要换行显示）：\n"
        "   - 功能描述:\n"
        "   - 参数:\n"
        "   - 返回值:\n"
        "   - 关键规则:\n"
        "   - 示例:\n"
        "   - 实现说明(<=100字):\n"
        "5) 不要编造业务规则；不确定时用保守表述（如“待确认/待补充”）。\n"
        "\n"
        "需要生成/补全 docstring 的 qualname 列表：\n"
        f"{targets_text}\n"
        "\n"
        "源码如下（仅供理解，不要在输出里重复源码）：\n"
        f"{source_text}\n"
    )


_LLM_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "file_summary": {"type": "string"},
        "updates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "qualname": {"type": "string"},
                    "docstring": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["qualname", "docstring", "summary"],
            },
        },
    },
    "required": ["file_summary", "updates"],
}


def call_openai_for_updates(*, prompt_text: str, model: str = "gpt-4.1") -> dict:
    """
    功能描述:
    - 调用 OpenAI Responses API，获取结构化 JSON（file_summary + updates）。

    参数:
    - prompt_text (str): build_prompt_payload 生成的 prompt
    - model (str): OpenAI 模型名（默认 gpt-4.1）

    返回值:
    - (dict): parse_llm_json 后的结果

    关键规则:
    - 默认尝试 Structured Outputs（json_schema, strict=true）
    - 若 Structured Outputs 不可用，则退化为“要求只输出 JSON”的普通调用，并在解析失败时重试一次

    示例:
    - `call_openai_for_updates(prompt_text, model="gpt-4.1")`

    实现说明(<=100字):
    - openai SDK 作为可选依赖；仅在调用时导入。先用 json_schema，异常时回退并重试。
    """

    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: openai. Install with `pip install openai`.") from exc

    client = OpenAI()
    try:  # pragma: no cover
        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": prompt_text}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "code_explainer",
                    "strict": True,
                    "schema": _LLM_JSON_SCHEMA,
                }
            },
        )
        return parse_llm_json(response.output_text)
    except Exception:  # pragma: no cover
        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": prompt_text}],
        )
        try:
            return parse_llm_json(response.output_text)
        except Exception:
            retry_prompt = (
                prompt_text
                + "\n\n你上一次输出不是合法 JSON。请只输出合法 JSON，不要额外文字、不要 markdown。\n"
            )
            retry_response = client.responses.create(
                model=model,
                input=[{"role": "user", "content": retry_prompt}],
            )
            return parse_llm_json(retry_response.output_text)


_UTF8_BOM = b"\xef\xbb\xbf"


def _read_text_preserve_utf8_bom(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    has_bom = raw.startswith(_UTF8_BOM)
    text = raw.decode("utf-8-sig")
    return text, has_bom


def _write_text_preserve_utf8_bom(*, path: Path, text: str, has_bom: bool) -> None:
    raw = text.encode("utf-8")
    if has_bom:
        raw = _UTF8_BOM + raw
    path.write_bytes(raw)


def _format_params(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = function_node.args

    parts: list[str] = []
    for arg in args.posonlyargs:
        parts.append(arg.arg)
    if args.posonlyargs:
        parts.append("/")
    for arg in args.args:
        parts.append(arg.arg)

    if args.vararg is not None:
        parts.append(f"*{args.vararg.arg}")
    elif args.kwonlyargs:
        parts.append("*")

    for arg in args.kwonlyargs:
        parts.append(arg.arg)
    if args.kwarg is not None:
        parts.append(f"**{args.kwarg.arg}")

    return ", ".join(parts)


def _first_nonempty_line(text: str) -> str:
    for line_text in text.splitlines():
        stripped = line_text.strip()
        if stripped:
            return stripped
    return ""


def _extract_returns_from_docstring(docstring_text: str | None) -> str:
    if not docstring_text:
        return ""

    lines = docstring_text.splitlines()
    start_idx: int | None = None
    for index, line_text in enumerate(lines):
        if line_text.strip().startswith("返回值"):
            start_idx = index
            break
    if start_idx is None:
        return ""

    for line_text in lines[start_idx + 1 :]:
        stripped = line_text.strip()
        if not stripped:
            continue
        if any(stripped.startswith(f"{key}:") or stripped == f"{key}" for key in TEMPLATE_KEYS):
            break
        match = re.match(r"^-\s*\(([^)]+)\)\s*:", stripped)
        if match:
            return match.group(1).strip()

    return ""


def run_on_file(
    target_path: Path,
    *,
    llm: Callable[[str, list[str]], dict] | None = None,
    model: str = "gpt-4.1",
) -> None:
    """
    功能描述:
    - 对单个 `.py` 文件执行：扫描函数/方法 -> 需要补全的调用 LLM -> 原地写回 docstring -> 生成 Markdown 报告。

    参数:
    - target_path (Path): 目标 `.py` 文件路径
    - llm (Callable, default=None): 注入的 LLM 函数（用于测试）；签名 (source_text, qualnames)->dict
    - model (str): OpenAI 模型名（llm=None 时生效）

    返回值:
    - (None): 原地写文件与生成 Markdown

    关键规则:
    - 只更新顶层函数与类方法（跳过 __dunder__）
    - docstring 足够则保留，不足则补全
    - 写回不做备份
    - Markdown 输出到同目录，文件名 `<目标文件夹名>_doc.md`

    示例:
    - `run_on_file(Path("x.py"))`

    实现说明(<=100字):
    - 先计算需更新的 qualname 列表，再调用 LLM 取回 updates 并应用；最后用 AST 生成函数表并写 md。
    """

    source_text, has_bom = _read_text_preserve_utf8_bom(target_path)
    targets = scan_targets(source_text)

    qualnames_to_update: list[str] = []
    for target in targets:
        existing = ast.get_docstring(target.node, clean=False)
        if needs_update(existing):
            qualnames_to_update.append(target.qualname)

    if llm is None:
        prompt_text = build_prompt_payload(source_text=source_text, target_qualnames=qualnames_to_update)
        llm_result = call_openai_for_updates(prompt_text=prompt_text, model=model)
    else:
        llm_result = llm(source_text, qualnames_to_update)

    file_summary = str(llm_result.get("file_summary", "")).strip()
    updates_list = llm_result.get("updates") or []

    allowed = set(qualnames_to_update)
    normalized_updates: list[dict] = []
    for item in updates_list:
        if not isinstance(item, dict):
            continue
        qualname = item.get("qualname")
        if not isinstance(qualname, str):
            continue
        if allowed and qualname not in allowed:
            continue
        normalized_updates.append(item)

    docstring_updates: dict[str, str] = {}
    summary_updates: dict[str, str] = {}
    for item in normalized_updates:
        qualname = item.get("qualname")
        docstring = item.get("docstring")
        summary = item.get("summary")
        if isinstance(qualname, str) and isinstance(docstring, str):
            docstring_updates[qualname] = docstring
        if isinstance(qualname, str) and isinstance(summary, str):
            summary_updates[qualname] = summary

    updated_source = apply_docstring_updates(source_text=source_text, updates=docstring_updates)
    _write_text_preserve_utf8_bom(path=target_path, text=updated_source, has_bom=has_bom)

    rows: list[dict[str, str]] = []
    for target in targets:
        function_node = target.node
        if not isinstance(function_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        params = _format_params(function_node)
        returns = ast.unparse(function_node.returns) if function_node.returns is not None else ""

        if not returns:
            if target.qualname in docstring_updates:
                returns = _extract_returns_from_docstring(docstring_updates[target.qualname])
            else:
                existing_clean = ast.get_docstring(function_node, clean=True)
                returns = _extract_returns_from_docstring(existing_clean)

        summary = summary_updates.get(target.qualname, "").strip()
        if not summary:
            existing_clean = ast.get_docstring(function_node, clean=True) or ""
            summary = _first_nonempty_line(existing_clean)

        rows.append(
            {
                "qualname": target.qualname,
                "params": params,
                "returns": returns,
                "summary": summary,
            }
        )

    md_text = build_markdown(file_summary=file_summary, rows=rows)
    md_path = target_path.parent / f"{target_path.parent.name}_doc.md"
    md_path.write_text(md_text, encoding="utf-8")


def main() -> None:
    raw = input("请输入待解析的 .py 文件路径: ").strip().strip('"')
    if not raw:
        raise SystemExit("empty path")

    target_path = Path(raw)
    if not target_path.exists():
        raise SystemExit(f"file not found: {target_path}")
    if target_path.suffix.lower() != ".py":
        raise SystemExit(f"not a .py file: {target_path}")

    run_on_file(target_path,model='stepfun/step-3.5-flash:free')#'z-ai/glm-4.5-air:free')


if __name__ == "__main__":
    main()
