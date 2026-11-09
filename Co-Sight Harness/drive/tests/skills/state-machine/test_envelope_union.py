"""envelope 本地副本独立性测试。

各 skill / hook 各自维护 envelope.py 本地副本（capability skill 不共享代码硬约束）。
本测试验证：
1. 各 envelope.py 不再跨域引用 state-machine/scripts/
2. 仓库 envelope.py 数 = 4（state-machine + drive + wave-scheduling + wave-barrier）
3. `class Envelope` 定义数 = 7（4 envelope.py + aggregate 内联 + startup
   init_planning + drive-record/env.py）
4. 各副本含自己的 REASON 子集（不强求一致）
"""
from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
STATE_MACHINE_ENVELOPE = (
    PLUGIN_ROOT / "skills" / "state-machine" / "scripts" / "envelope.py"
)


class TestEnvelopeLocalReplicas:
    def test_no_cross_skill_envelope_references(self):
        """envelope.py 副本不应再跨域引用 state-machine/scripts/。"""
        offenders: list[str] = []
        for env_path in PLUGIN_ROOT.rglob("envelope.py"):
            if "__pycache__" in env_path.parts:
                continue
            text = env_path.read_text()
            # 排除 state-machine 自己 + drive-record（prop 范围外）
            if "state-machine/scripts" in env_path.parts:
                continue
            if "drive-record/scripts" in env_path.parts:
                continue
            if "state-machine" in text and env_path != STATE_MACHINE_ENVELOPE:
                offenders.append(str(env_path))
        assert not offenders, (
            f"envelope.py 副本仍跨域引用 state-machine: {offenders}"
        )

    def test_envelope_py_count_is_five(self):
        """仓库 envelope.py 数 = 5：state-machine + drive + wave-scheduling + wave-barrier + dag-runtime。

        各 skill 自负责 envelope 协议。context-packaging envelope.py 是死文件，已删。
        """
        envelope_pys = sorted(
            p for p in PLUGIN_ROOT.rglob("envelope.py")
            if "__pycache__" not in p.parts
        )
        assert len(envelope_pys) == 5, (
            f"envelope.py 数量={len(envelope_pys)}: {envelope_pys}"
        )
        names = {p.relative_to(PLUGIN_ROOT).as_posix() for p in envelope_pys}
        assert "skills/state-machine/scripts/envelope.py" in names
        assert "skills/drive/scripts/envelope.py" in names
        assert "skills/wave-scheduling/scripts/envelope.py" in names
        assert "skills/wave-barrier/scripts/envelope.py" in names
        assert "skills/dag-runtime/scripts/envelope.py" in names

    def test_class_envelope_definitions_count(self):
        """`class Envelope` 定义数 = 8：

        - state-machine/scripts/envelope.py
        - drive/scripts/envelope.py
        - wave-scheduling/scripts/envelope.py
        - wave-barrier/scripts/envelope.py
        - wave-barrier/scripts/aggregate.py（脚本内联定义）
        - startup/scripts/init_planning.py（prop 显式保留）
        - drive-record/scripts/env.py（prop 范围外，独立 skill 协议）
        - dag-runtime/scripts/envelope.py（CHG-20260909-001 新增）
        """
        result = subprocess.run(
            ["grep", "-rn", "^class Envelope", str(PLUGIN_ROOT / "skills"),
             str(PLUGIN_ROOT / "hooks")],
            capture_output=True, text=True,
        )
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        assert len(lines) == 8, f"class Envelope 数量={len(lines)}: {lines}"
        expected_substrings = (
            "state-machine/scripts/envelope.py",
            "drive/scripts/envelope.py",
            "wave-scheduling/scripts/envelope.py",
            "wave-barrier/scripts/envelope.py",
            "wave-barrier/scripts/aggregate.py",
            "startup/scripts/init_planning.py",
            "drive-record/scripts/env.py",
            "dag-runtime/scripts/envelope.py",
        )
        for needle in expected_substrings:
            assert any(needle in l for l in lines), f"缺: {needle}"

    def test_each_local_envelope_has_own_reason_subset(self):
        """3 个 envelope.py 各含自己的 REASON 子集（不强求一致）。"""
        # state-machine = 29 (full set)
        spec = importlib.util.spec_from_file_location(
            "_sm_envelope", STATE_MACHINE_ENVELOPE
        )
        sm_mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules["_sm_envelope"] = sm_mod
        spec.loader.exec_module(sm_mod)  # type: ignore[union-attr]
        sm_reasons = {
            v for k, v in vars(sm_mod).items()
            if k.startswith("REASON_") and isinstance(v, str)
        }
        assert len(sm_reasons) >= 13  # 至少 13 个原集

        # wave-scheduling = 3 (FILE_MISSING / INVALID_ARG / SCHEMA_INVALID)
        ws_env = PLUGIN_ROOT / "skills" / "wave-scheduling" / "scripts" / "envelope.py"
        spec = importlib.util.spec_from_file_location("_ws_envelope", ws_env)
        ws_mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules["_ws_envelope"] = ws_mod
        spec.loader.exec_module(ws_mod)  # type: ignore[union-attr]
        ws_reasons = {
            v for k, v in vars(ws_mod).items()
            if k.startswith("REASON_") and isinstance(v, str)
        }
        assert ws_reasons == {"file_missing", "invalid_arg", "schema_invalid"}

        # wave-barrier = 2 (SCHEMA_INVALID / FILE_MISSING)
        wb_env = PLUGIN_ROOT / "skills" / "wave-barrier" / "scripts" / "envelope.py"
        spec = importlib.util.spec_from_file_location("_wb_envelope", wb_env)
        wb_mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules["_wb_envelope"] = wb_mod
        spec.loader.exec_module(wb_mod)  # type: ignore[union-attr]
        wb_reasons = {
            v for k, v in vars(wb_mod).items()
            if k.startswith("REASON_") and isinstance(v, str)
        }
        assert wb_reasons == {"schema_invalid", "file_missing"}
