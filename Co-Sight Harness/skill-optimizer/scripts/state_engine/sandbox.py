"""
Sandbox Manager — 沙箱物理隔离
===============================
实现 Gold/候选产物的文件系统级隔离，阻断泄漏链路。

隔离策略：
- Gold: 符号链接到沙箱（评测完成后立即删除）
- Skill: 复制到沙箱（优化器修改沙箱副本，审批后拷回）
- 候选产物: 写入沙箱（不污染 workspace）
- 生命周期: 评测前创建 → 评测后删 Gold → 优化后清理全部

默认沙箱根目录通过 SKILLX_SANDBOX_ROOT 环境变量配置（推荐大磁盘路径，避免 /tmp 占满），
未设置时回退到 /tmp。

用法：
    manager = SandboxManager(round_num=0)
    manager.setup()
    manager.stage_gold(gold_base_dir, case_filter)
    manager.stage_skill(skill_dir)
    gold_dir = manager.gold_dir       # /tmp/skillx-0-12345/gold/
    skill_dir = manager.skill_dir     # /tmp/skillx-0-12345/skill/

    # 评测完成后
    manager.purge_gold()              # Gold 立即不可见

    # 轮次结束后
    manager.cleanup()
"""

import atexit
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


# 全局注册表，确保进程退出时清理所有沙箱
_active_sandboxes: List["SandboxManager"] = []


def _cleanup_all_sandboxes():
    """atexit 回调：清理所有活跃沙箱"""
    for sb in _active_sandboxes:
        try:
            sb.cleanup()
        except Exception:
            pass


atexit.register(_cleanup_all_sandboxes)


class SandboxManager:
    """管理单个轮次的沙箱（根目录由 SKILLX_SANDBOX_ROOT 环境变量控制）"""

    def __init__(self, round_num: int, root: Optional[str] = None):
        """
        Args:
            round_num: 轮次编号（用于目录命名）
            root: 沙箱根目录，优先读取 SKILLX_SANDBOX_ROOT 环境变量（推荐大磁盘路径），
                  未设置时回退到 /tmp
        """
        self.round_num = round_num
        self._root = Path(root or os.environ.get("SKILLX_SANDBOX_ROOT", "/tmp")).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._pid = os.getpid()
        self._ts = datetime.now().strftime("%H%M%S")
        self._name = f"skillx-r{round_num}-p{self._pid}-{self._ts}"
        self._path: Optional[Path] = None
        self._gold_staged = False
        self._gold_purged = False
        self._cleaned_up = False

        _active_sandboxes.append(self)

    # ── 属性 ──────────────────────────────────────────

    @property
    def path(self) -> Path:
        if self._path is None:
            raise RuntimeError("沙箱未初始化，先调用 setup()")
        return self._path

    @property
    def gold_dir(self) -> Path:
        return self.path / "gold"

    @property
    def skill_dir(self) -> Path:
        """沙箱中的 Skill 目录（统一使用 skill/）。"""
        return self._path / "skill"

    @property
    def candidates_dir(self) -> Path:
        return self.path / "candidates"

    # ── 生命周期 ──────────────────────────────────────

    def setup(self) -> "SandboxManager":
        """创建沙箱目录结构"""
        self._path = self._root / self._name
        self._path.mkdir(parents=True, exist_ok=True)
        (self._path / "gold").mkdir(exist_ok=True)
        # 创建 skill/ 目录（统一结构）
        (self._path / "skill").mkdir(exist_ok=True)
        (self._path / "candidates").mkdir(exist_ok=True)
        self._cleaned_up = False
        return self

    def stage_gold(self, gold_base_dir: str, ran_filter: str = "") -> List[str]:
        """
        符号链接 Gold 文件到沙箱

        遍历 gold_base_dir 下子目录的 gold.md，筛选后创建符号链接。
        符号链接零 I/O 开销，且删除链接不影响原文件。

        Args:
            gold_base_dir: Gold 标准根目录
            ran_filter: case_id 筛选正则（"|" 分隔），来自 --case-filter CLI 参数

        Returns:
            已链接的 case_id 列表
        """
        import re
        gold_base = Path(gold_base_dir)
        if not gold_base.exists():
            return []

        filter_re = re.compile(ran_filter) if ran_filter else None
        staged = []

        for gold_file in sorted(gold_base.glob("*/gold.md")):
            case_id = gold_file.parent.name
            if filter_re and not filter_re.search(case_id):
                continue

            # 沙箱中创建 case 子目录，Gold 文件通过符号链接放入
            case_sandbox_dir = self.gold_dir / case_id
            case_sandbox_dir.mkdir(exist_ok=True)
            link_path = case_sandbox_dir / "gold.md"
            if not link_path.exists():
                os.symlink(str(gold_file.resolve()), str(link_path))
            staged.append(case_id)

        self._gold_staged = True
        return staged

    def stage_skill(self, skill_source_dir: Path) -> Path:
        """
        复制 Skill 目录到沙箱（优化器将修改此副本）

        Args:
            skill_source_dir: SKILL.md 所在目录

        Returns:
            沙箱中的 Skill 目录路径（含 SKILL.md）
        """
        dest = self.skill_dir
        if dest.exists():
            shutil.rmtree(str(dest))
        shutil.copytree(str(skill_source_dir), str(dest))
        return dest

    def stage_skills(self, skill_source_dirs: List[Path]) -> Dict[str, Path]:
        """复制多个 Skill 目录到沙箱 skill/ 目录"""
        dest_base = self.path / "skill"
        if dest_base.exists():
            shutil.rmtree(str(dest_base))
        dest_base.mkdir(parents=True, exist_ok=True)

        staged = {}
        for src in skill_source_dirs:
            name = src.name
            dest = dest_base / name
            shutil.copytree(str(src), str(dest))
            staged[name] = dest
        return staged

    def stage_workspace_inputs(self, workspace: Path, case_ids: List[str]) -> Path:
        """
        复制 workspace 中各 case 的 input/ 到沙箱（候选生成需要）

        只复制 input/ 目录，不复制 baseline/、round_N/ 等历史产物。
        这样候选生成 LLM 看不到 Gold 或旧产物。

        Args:
            workspace: 工作目录
            case_ids: 需要隔离的 case_id 列表

        Returns:
            沙箱 workspace 目录
        """
        ws_dir = self.path / "workspace"
        ws_dir.mkdir(exist_ok=True)

        for case_id in case_ids:
            case_ws = ws_dir / case_id
            case_ws.mkdir(exist_ok=True)
            input_dir = workspace / case_id / "input"
            if input_dir.is_dir():
                dest_input = case_ws / "input"
                shutil.copytree(str(input_dir), str(dest_input))

        return ws_dir

    def stage_external_inputs(self, inputs: Dict[str, Path]) -> Dict[str, Path]:
        """
        将通用输入拷贝到沙箱（供外部工作流使用）

        Args:
            inputs: {标签: 源路径} 映射

        Returns:
            {标签: 沙箱中路径} 映射
        """
        staged = {}
        external_dir = self.path / "external"
        external_dir.mkdir(exist_ok=True)

        for label, src_path in inputs.items():
            src = Path(src_path)
            safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", label)
            if src.is_file():
                dest = external_dir / src.name
                shutil.copy2(str(src), str(dest))
            elif src.is_dir():
                dest = external_dir / safe_label
                if dest.exists():
                    shutil.rmtree(str(dest))
                shutil.copytree(str(src), str(dest))
            else:
                continue
            staged[label] = dest

        return staged

    def create_output_dir(self) -> Path:
        """创建工作流输出目录"""
        output = self.path / "output"
        output.mkdir(exist_ok=True)
        return output

    def stage_multiple_dirs(self, dir_mappings: Dict[str, Path]) -> Dict[str, Path]:
        """
        将多个目录拷贝到沙箱（供管道工作流使用）

        Args:
            dir_mappings: {标签: 源路径} 映射

        Returns:
            {标签: 沙箱中路径} 映射
        """
        staged = {}
        for label, src_path in dir_mappings.items():
            src = Path(src_path)
            safe_label = re.sub(r"[^a-zA-Z0-9_一-鿿-]", "_", label)
            if not src.exists():
                continue
            dest = self.path / safe_label
            if src.is_file():
                shutil.copy2(str(src), str(dest))
            elif src.is_dir():
                if dest.exists():
                    shutil.rmtree(str(dest))
                shutil.copytree(str(src), str(dest))
            staged[label] = dest
        return staged

    def purge_gold(self):
        """评测完成后立即删除沙箱中的 Gold（关键安全步骤）"""
        if self._gold_purged:
            return
        gold = self.gold_dir
        if gold.exists():
            shutil.rmtree(str(gold))
        self._gold_purged = True
        self._gold_staged = False

    def cleanup(self):
        """删除整个沙箱"""
        if self._cleaned_up:
            return
        if self._path and self._path.exists():
            shutil.rmtree(str(self._path))
        self._cleaned_up = True
        if self in _active_sandboxes:
            _active_sandboxes.remove(self)

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass

    # ── 工具方法 ──────────────────────────────────────

    def is_active(self) -> bool:
        """沙箱是否仍然活跃"""
        return not self._cleaned_up and self._path is not None and self._path.exists()

    @staticmethod
    def cleanup_stale(keep_minutes: int = 120):
        """清理未正常退出的旧沙箱（orchestrator 启动时调用）"""
        import time
        root = Path(os.environ.get("SKILLX_SANDBOX_ROOT", "/tmp"))
        cutoff = time.time() - keep_minutes * 60

        for d in root.glob("skillx-r*-p*-*"):
            try:
                mtime = d.stat().st_mtime
                if mtime < cutoff:
                    shutil.rmtree(str(d))
            except Exception:
                pass
