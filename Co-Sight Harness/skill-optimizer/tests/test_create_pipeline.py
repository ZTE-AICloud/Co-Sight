"""无头 create 流水线（Phase A–E）单元测试。

mock `orchestrators.create_pipeline._run_create_subagent` 为写入固定产物，
验证编排顺序、各阶段产物落盘、校验门槛（spec 16 项 / impl 行数 / scaffold 骨架）、
以及失败路径的中止与返回码。全程不调用真实 agent CLI。
"""
import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import commands.skill_create as sc
import orchestrators.create_pipeline as cp

SKILL = "demo-skill"

# 一份能通过 validate_spec_hard_constraints 的规格（刻意回避会让覆盖度误报的记法：
# 不用 "### 步骤 N"/"### §2.x" 子标题、不写 .md/.json 文件名、不写 "🧠 LLM-"，只用 🧠）。
VALID_SPEC = """\
# 规格说明书

## 1. 输入与输出
输入原始资料，输出代码化 Skill 目录。

## 2. 核心概念
产出物与执行流程。

## 3. 执行流程总览
五阶段流水线。

## 4. 步骤 1 组装
按模板落盘 🟢 可代码化。
（🟡 需要判断 / 🔴 需要人工的场景按断点处理。）

## 附录 A
模板清单。

## 附录 B
校验清单。

## 附录 C
断点契约 🧠 说明。
"""


def _write_valid_skill(skill_dir: Path) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "references").mkdir(parents=True, exist_ok=True)
    (skill_dir / "templates").mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: sample\nversion: 1.0.0\ndescription: 测试 skill\n"
        "allowed-tools: Read,Write,Edit,Bash\n---\n# 描述\n",
        encoding="utf-8",
    )
    (skill_dir / "scripts" / "run.py").write_text(
        "def main():\n    return 0\n", encoding="utf-8"
    )
    (skill_dir / "references" / "output-schema.md").write_text(
        "# schema\n", encoding="utf-8"
    )
    (skill_dir / "references" / "llm_a_breakpoint.md").write_text(
        '# LLM 断点\n```json\n{"$schema": "https://x/schema", "type": "object"}\n```\n',
        encoding="utf-8",
    )
    (skill_dir / "templates" / "output-template.md").write_text(
        "# 模板\n", encoding="utf-8"
    )


@pytest.fixture
def config(monkeypatch):
    """注入默认 args + 让覆盖度校验跳过业务模式依赖（保持确定性）。"""
    monkeypatch.setattr(sc, "_load_business_patterns", lambda: None)
    ns = argparse.Namespace(
        skill_name=SKILL,
        requirement="做一个处理批量数据的代码化 Skill",
        output_dir="",
        expert_guidance="",
        agent_cli=None,
        non_interactive=True,
        decisions_file=None,
    )
    return ns


def _make_pipeline(monkeypatch, calls: list, tmp_path: Path) -> None:
    """把子 Agent 调度替换为写固定产物的假实现。"""
    def fake(subagent_type, description, prompt, cwd):
        calls.append(subagent_type)
        out = Path(cwd)
        if subagent_type == "specification-writer-agent":
            (out / cp.SPEC_FILE).write_text(VALID_SPEC, encoding="utf-8")
        elif subagent_type == "code-implementer-agent":
            impl = "# 单体实现\n" + "\n".join(f"x{i} = {i}" for i in range(cp.MIN_IMPL_LINES + 5))
            (out / cp.IMPL_FILE).write_text(impl, encoding="utf-8")
        elif subagent_type == "skill-scaffolder-agent":
            _write_valid_skill(out / cp.SKILL_DIR / SKILL)
        return "DONE"

    monkeypatch.setattr(cp, "_run_create_subagent", fake)


def test_create_pipeline_happy_path(config, tmp_path, monkeypatch):
    config.output_dir = str(tmp_path / "ws")
    calls: list = []
    _make_pipeline(monkeypatch, calls, tmp_path)

    rc = cp.run_create_pipeline(config)

    assert rc == 0, "全成功路径应返回 0"
    out = Path(config.output_dir)
    # 四个阶段产物
    assert list(out.glob("01_*.md")), "阶段 1 brief"
    assert (out / cp.SPEC_FILE).exists()          # 阶段 2 规格
    assert (out / cp.IMPL_FILE).exists()          # 阶段 3 单体
    assert (out / cp.SKILL_DIR / SKILL).exists()  # 阶段 4 Skill 目录
    assert (out / "final_report.md").exists()     # 阶段 5 报告
    # 调度顺序：spec → impl → scaffold（+ 终检，不额外调度）
    assert calls == [
        "specification-writer-agent",
        "code-implementer-agent",
        "skill-scaffolder-agent",
    ]
    # 单体实现行数满足下限
    lines = sum(1 for _ in (out / cp.IMPL_FILE).read_text(encoding="utf-8").splitlines())
    assert lines >= cp.MIN_IMPL_LINES


def test_create_pipeline_aborts_when_spec_fails(config, tmp_path, monkeypatch):
    config.output_dir = str(tmp_path / "ws")
    calls: list = []
    monkeypatch.setattr(sc, "_load_business_patterns", lambda: None)

    def bad_spec(subagent_type, description, prompt, cwd):
        calls.append(subagent_type)
        out = Path(cwd)
        if subagent_type == "specification-writer-agent":
            (out / cp.SPEC_FILE).write_text("# 不完整\n", encoding="utf-8")  # 校验必失败
        return "DONE"

    monkeypatch.setattr(cp, "_run_create_subagent", bad_spec)
    rc = cp.run_create_pipeline(config)

    assert rc != 0, "规格校验未通过应中止"
    out = Path(config.output_dir)
    assert not (out / cp.IMPL_FILE).exists(), "规格失败后不应进入单体阶段"
    assert calls == ["specification-writer-agent"] * 3, (
        "规格失败应 1 次生成 + MAX_SPEC_RETRY(2) 次修正后中止"
    )
    assert (out / "final_report.md").exists(), "失败也应出报告"


def test_create_pipeline_aborts_when_impl_too_short(config, tmp_path, monkeypatch):
    config.output_dir = str(tmp_path / "ws")
    calls: list = []
    monkeypatch.setattr(sc, "_load_business_patterns", lambda: None)

    def short_impl(subagent_type, description, prompt, cwd):
        calls.append(subagent_type)
        out = Path(cwd)
        if subagent_type == "specification-writer-agent":
            (out / cp.SPEC_FILE).write_text(VALID_SPEC, encoding="utf-8")
        elif subagent_type == "code-implementer-agent":
            (out / cp.IMPL_FILE).write_text("# 太短\n", encoding="utf-8")
        return "DONE"

    monkeypatch.setattr(cp, "_run_create_subagent", short_impl)
    rc = cp.run_create_pipeline(config)

    assert rc != 0
    out = Path(config.output_dir)
    assert not (out / cp.SKILL_DIR / SKILL).exists(), "实现不达标不应进入工程化阶段"


def test_script_extension_from_requirement_file(config, tmp_path, monkeypatch):
    """@file.md 需求 → brief 用原文件名拷贝。"""
    src = tmp_path / "req.md"
    src.write_text("需求正文", encoding="utf-8")
    config.requirement = f"@{src}"
    config.output_dir = str(tmp_path / "ws2")
    calls: list = []
    _make_pipeline(monkeypatch, calls, tmp_path)
    rc = cp.run_create_pipeline(config)

    assert rc == 0
    out = Path(config.output_dir)
    assert (out / "01_req.md").exists()
    assert (out / "01_req.md").read_text(encoding="utf-8") == "需求正文"