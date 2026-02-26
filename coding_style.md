# Coding Style & Workflow

## 0. 一句话原则

- **docstring 是唯一真源**：函数怎么用、输入输出、关键规则、最小示例，都写在函数体内。
- **样例要可回归**：notebook 里的最小样例，最终要落到 pytest（smoke + 边界）。
- **小步提交可回退**：以“函数级变更”为粒度提交，保证随时能回到上一版。
- **简洁，敏捷开发**：不需要写太稳健的代码，比如各种错误处理、特殊情况判断等，先写出MVP，需要时再往里加。

## 1. 推荐开发闭环（最常用）

1) 写函数（尽量纯函数：输入 `df/cols/params` → 返回 `pl.DataFrame`/`pl.Expr`/`dict`）   
2) 在 notebook 用最小数据验证（确保功能正确 + 边界可解释）  
3) 把 notebook 的最小样例迁移到 `tests/`（smoke test，固定 seed，小数据，<10s）  


## 2. Docstring 模板（中文，术语保留英文）

每个函数必须包含 6 段；最后一段“实现说明”不超过 100 字（越短越好）。

```python
def func_name(...):
    """
    功能描述:
    - （1~2 句：这函数做什么，用在什么场景）

    参数:
    - df (pl.DataFrame): ...
    - x_col (str): ...
    - bins (list[float], default=None): ...

    返回值:
    - (pl.DataFrame): （关键列/shape/含义）

    关键规则:
    - missing/特殊取值如何处理
    - weight=0、分母=0、clip 等策略
    - 任何“业务口径”都写这里（AI 不知道）

    示例:
    - 最小可运行示例（后续复制到 pytest）

    实现说明(<=100字):
    - （一句话说明思路/步骤/关键算子）
    """
```

## 3. pytest（把 notebook 样例变成可回归快测）

### 3.1 基本规则

- 每个新函数至少 1 个 smoke test（小数据 + 固定 seed + 运行很快）
- 合成数据优先；不要把真实业务数据写进仓库
- 只测“关键行为”：输入/输出 schema、关键边界、极端值策略、是否报错

### 3.2 推荐测试文件结构

- `tests/test_<module>.py`：对应模块的 smoke tests
- `tests/fixtures_*.py`：复用的造数/小样本生成器

运行：

```bash
pytest -q
```

## 4. git：保证随时可回退

建议习惯：

- 小步提交：一次提交只做一类事情（新增/修复一个函数，或只改 docstring/测试）
- 提交信息前缀建议：`iv:`、`psi:`、`lgb:`、`utils:`（便于检索）
- 不确定的改动：先开分支试验；不满意直接丢分支

## 5. 给 AI 的“业务上下文底座”

维护：`docs/ai_context.md`

你每次新开 codex/与 AI 对话时，建议固定提供：

1) `docs/ai_context.md`（业务规则 + 数据契约 + 造数先验）  
2) 目标模块的 `helper/<module>.md`（模块能力总表）  
3) 当前要改的函数签名/目标行为（用例优先）
