"""插件契约 —— 与 Claude Code 插件系统的约定。

这些约定错了不会让测试变红，而是让插件装上去后行为不对：skill 不出现在 `/`
菜单、hook 不触发、agents/ 里的文档被当成 agent 加载。故此处静态校验。

官方 `claude plugin validate --strict` 覆盖更全，已接进 pack.sh；本文件是不依赖
CLI 的第二道防线，供无 claude 的 CI 使用。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_JSON = PLUGIN_ROOT / "hooks" / "hooks.json"

# 官方文档列出的 hook 事件名（plugins-reference）。写错事件名不会报错，只是永不触发。
KNOWN_HOOK_EVENTS = frozenset({
    "SessionStart", "Setup", "UserPromptSubmit", "UserPromptExpansion",
    "PreToolUse", "PermissionRequest", "PermissionDenied", "PostToolUse",
    "PostToolUseFailure", "PostToolBatch", "Notification", "MessageDisplay",
    "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted", "Stop",
    "StopFailure", "TeammateIdle", "InstructionsLoaded", "ConfigChange",
    "CwdChanged", "FileChanged", "WorktreeCreate", "WorktreeRemove",
    "PreCompact", "PostCompact", "Elicitation", "ElicitationResult",
    "SessionEnd",
})

KNOWN_MANIFEST_FIELDS = frozenset({
    "$schema", "name", "displayName", "version", "description", "author",
    "homepage", "repository", "license", "keywords", "defaultEnabled",
    "skills", "commands", "agents", "workflows", "hooks", "mcpServers",
    "outputStyles", "lspServers", "experimental", "userConfig", "channels",
    "dependencies",
})

# 插件根下这些目录必须在根，不能塞进 .claude-plugin/
ROOT_ONLY_COMPONENT_DIRS = ("skills", "agents", "hooks", "commands")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def hooks_config() -> dict:
    return json.loads(HOOKS_JSON.read_text(encoding="utf-8"))


# =============================================================================
# manifest
# =============================================================================

class TestManifest:
    def test_manifest_exists(self):
        assert MANIFEST.is_file()

    def test_name_is_kebab_case(self, manifest):
        """name 用于组件命名空间，含空格或大写会破坏 `plugin:component` 引用。"""
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", manifest["name"]), manifest["name"]

    def test_no_unknown_fields(self, manifest):
        """未知字段不会让插件加载失败，但常是拼错的已知字段。"""
        unknown = sorted(set(manifest) - KNOWN_MANIFEST_FIELDS)
        assert not unknown, f"未知 manifest 字段: {unknown}"

    def test_keywords_is_array(self, manifest):
        """类型错误是加载错误 —— keywords 写成字符串会让插件整个装不上。"""
        assert isinstance(manifest.get("keywords", []), list)

    def test_version_is_set(self, manifest):
        """不设 version 会退化为按 git SHA 计版本，每次提交都算新版本。"""
        assert manifest.get("version")

    def test_declared_agents_exist(self, manifest):
        for rel in manifest.get("agents", []):
            assert (PLUGIN_ROOT / rel).is_file(), f"manifest 声明的 agent 不存在: {rel}"

    def test_does_not_redeclare_default_skill_dir(self, manifest):
        """skills 字段是"追加"到默认 skills/ 扫描，重复声明会扫两遍同一目录。"""
        declared = manifest.get("skills")
        values = [declared] if isinstance(declared, str) else (declared or [])
        for v in values:
            assert v.strip("./").rstrip("/") != "skills", (
                "skills 已是默认扫描路径，不要重复声明"
            )

    def test_does_not_redeclare_default_hooks_path(self, manifest):
        """hooks/hooks.json 是默认位置，重复声明有双重注册风险。"""
        declared = manifest.get("hooks")
        values = [declared] if isinstance(declared, str) else (declared or [])
        for v in values:
            if isinstance(v, str):
                assert v.strip("./") != "hooks/hooks.json", (
                    "hooks/hooks.json 已是默认位置，不要重复声明"
                )

    def test_license_claim_backed_by_file(self, manifest):
        """声明了 license 就得有 LICENSE 文件，否则是空头承诺。"""
        if "license" in manifest:
            candidates = list(PLUGIN_ROOT.glob("LICENSE*")) + list(
                PLUGIN_ROOT.parent.glob("LICENSE*")
            )
            assert candidates, "manifest 声明了 license 但仓库无 LICENSE 文件"


# =============================================================================
# marketplace（分发索引，与 plugin 同根）
# =============================================================================

MARKETPLACE = PLUGIN_ROOT / ".claude-plugin" / "marketplace.json"


@pytest.fixture(scope="module")
def marketplace() -> dict:
    return json.loads(MARKETPLACE.read_text(encoding="utf-8"))


class TestMarketplace:
    def test_marketplace_exists(self):
        assert MARKETPLACE.is_file()

    def test_name_is_kebab_case(self, marketplace):
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", marketplace["name"])

    def test_owner_present(self, marketplace):
        """owner 是必填字段，缺了整个 marketplace 加载失败。"""
        assert marketplace["owner"].get("name")

    def test_lists_this_plugin(self, marketplace, manifest):
        names = {p["name"] for p in marketplace["plugins"]}
        assert manifest["name"] in names, (
            f"marketplace 未列出本插件 {manifest['name']}"
        )

    def test_source_points_at_plugin_root(self, marketplace, manifest):
        """marketplace 与 plugin 同根，source 必须是 "."。写成子目录路径会让
        安装时拷错目录。"""
        entry = next(p for p in marketplace["plugins"] if p["name"] == manifest["name"])
        assert entry["source"].strip("./") == "", (
            f'同根布局下 source 应为 "."，实际是 {entry["source"]!r}'
        )

    def test_every_source_resolves(self, marketplace):
        for entry in marketplace["plugins"]:
            target = (MARKETPLACE.parent.parent / entry["source"]).resolve()
            assert target.is_dir(), f"{entry['name']} 的 source 不存在: {entry['source']}"

    def test_name_differs_from_plugin_name(self, marketplace, manifest):
        """安装标识是 <plugin>@<marketplace>，两者同名会读起来像 drive@drive。"""
        assert marketplace["name"] != manifest["name"]

    def test_not_using_reserved_name(self, marketplace):
        """官方保留名会让 marketplace 被判为不可信来源而停止加载。"""
        reserved = {
            "claude-code-marketplace", "claude-code-plugins", "claude-plugins-official",
            "claude-plugins-community", "claude-community", "anthropic-marketplace",
            "anthropic-plugins", "agent-skills", "anthropic-agent-skills",
            "knowledge-work-plugins", "life-sciences", "claude-for-legal",
            "claude-for-financial-services", "financial-services-plugins",
            "first-party-plugins", "healthcare",
        }
        assert marketplace["name"] not in reserved


# =============================================================================
# 目录布局
# =============================================================================

class TestLayout:
    @pytest.mark.parametrize("name", ROOT_ONLY_COMPONENT_DIRS)
    def test_component_dirs_not_inside_claude_plugin(self, name):
        """组件目录必须在插件根，塞进 .claude-plugin/ 不会被发现。"""
        assert not (PLUGIN_ROOT / ".claude-plugin" / name).exists()

    def test_agents_dir_holds_only_agent_definitions(self):
        """agents/ 下的每个 .md 都会被当 agent 加载 —— 文档放这里会变成坏 agent。"""
        offenders = []
        for path in (PLUGIN_ROOT / "agents").rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            if not text.startswith("---"):
                offenders.append(path.relative_to(PLUGIN_ROOT))
        assert not offenders, f"agents/ 下有无 frontmatter 的 .md（应移出）: {offenders}"

    def test_every_skill_dir_has_skill_md(self):
        for d in (PLUGIN_ROOT / "skills").iterdir():
            if d.is_dir() and not d.name.startswith("."):
                assert (d / "SKILL.md").is_file(), f"{d.name} 缺 SKILL.md"

    def test_skill_dirs_are_kebab_case(self):
        for d in (PLUGIN_ROOT / "skills").iterdir():
            if d.is_dir() and not d.name.startswith("."):
                assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", d.name), d.name

    def test_no_claude_md_at_plugin_root(self):
        """插件根的 CLAUDE.md 不会被当项目上下文加载，放这里是误解。"""
        assert not (PLUGIN_ROOT / "CLAUDE.md").exists()


# =============================================================================
# hooks 配置
# =============================================================================

class TestHooksConfig:
    def test_hooks_json_exists_at_default_location(self):
        assert HOOKS_JSON.is_file()

    def test_all_events_are_known(self, hooks_config):
        """事件名写错不会报错，只是那个 hook 永不触发。"""
        unknown = sorted(set(hooks_config["hooks"]) - KNOWN_HOOK_EVENTS)
        assert not unknown, f"未知 hook 事件: {unknown}"

    def test_every_hook_command_uses_plugin_root_var(self, hooks_config):
        """硬编码路径在装进 plugin cache 后会失效。"""
        for event, entries in hooks_config["hooks"].items():
            for entry in entries:
                for hook in entry["hooks"]:
                    if hook.get("type") != "command":
                        continue
                    assert "${CLAUDE_PLUGIN_ROOT}" in hook["command"], (
                        f"{event} 的命令未用 ${{CLAUDE_PLUGIN_ROOT}}: {hook['command']}"
                    )

    def test_every_referenced_hook_script_exists(self, hooks_config):
        for event, entries in hooks_config["hooks"].items():
            for entry in entries:
                for hook in entry["hooks"]:
                    cmd = hook.get("command", "")
                    for m in re.finditer(r'\$\{CLAUDE_PLUGIN_ROOT\}"?/([\w\-./]+)', cmd):
                        target = PLUGIN_ROOT / m.group(1)
                        assert target.is_file(), (
                            f"{event} 引用了不存在的脚本: {m.group(1)}"
                        )

    def test_every_hook_declares_timeout(self, hooks_config):
        """无超时的 hook 卡住会拖死整个工具调用。"""
        for event, entries in hooks_config["hooks"].items():
            for entry in entries:
                for hook in entry["hooks"]:
                    assert "timeout" in hook, f"{event} 的 hook 未设 timeout"

    def test_guard_hooks_registered_on_pretooluse(self, hooks_config):
        """守卫必须在 PreToolUse —— PostToolUse 时副作用已发生，拦不住。"""
        commands = [
            h["command"]
            for entry in hooks_config["hooks"]["PreToolUse"]
            for h in entry["hooks"]
        ]
        joined = " ".join(commands)
        assert "planning_write_guard.py" in joined
        assert "state_transition_guard.py" in joined


# =============================================================================
# 打包边界
# =============================================================================

class TestPackaging:
    def test_pack_script_excludes_tests(self):
        body = (PLUGIN_ROOT / "scripts" / "pack.sh").read_text(encoding="utf-8")
        assert "--exclude='tests'" in body

    def test_pack_script_runs_official_validate(self):
        body = (PLUGIN_ROOT / "scripts" / "pack.sh").read_text(encoding="utf-8")
        assert "plugin validate" in body

    def test_pack_validates_both_manifests_explicitly(self):
        """marketplace.json 与 plugin.json 同根时，把目录传给校验器只会校验
        marketplace，plugin 层的组件检查被静默跳过。必须逐个 manifest 显式校验。"""
        body = (PLUGIN_ROOT / "scripts" / "pack.sh").read_text(encoding="utf-8")
        assert ".claude-plugin/plugin.json" in body, "pack.sh 未显式校验 plugin.json"
        assert ".claude-plugin/marketplace.json" in body, (
            "pack.sh 未显式校验 marketplace.json"
        )

    def test_install_script_ships_component_dirs(self):
        body = (PLUGIN_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        for item in (".claude-plugin", "skills", "agents", "hooks"):
            assert item in body, f"install.sh 未安装 {item}"

    def test_changelog_present(self):
        assert (PLUGIN_ROOT.parent / "02-changelogs" / "CHANGELOG.md").is_file()

    @pytest.mark.parametrize(
        "item", [".claude-plugin", "skills", "agents", "hooks", "README.md"]
    )
    def test_shipped_items_listed_in_both_scripts(self, item):
        """pack 与 install 的清单必须一致，否则装出来的和打出来的不是一个东西。"""
        pack = (PLUGIN_ROOT / "scripts" / "pack.sh").read_text(encoding="utf-8")
        install = (PLUGIN_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        assert item in pack, f"pack.sh 未打包 {item}"
        assert item in install, f"install.sh 未安装 {item}"


# =============================================================================
# skill frontmatter
# =============================================================================

class TestSkillFrontmatter:
    def _frontmatter(self, path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---"), f"{path.name} 无 frontmatter"
        return text[3 : text.index("---", 3)]

    @pytest.mark.parametrize(
        "skill_dir",
        sorted(
            d.name for d in (PLUGIN_ROOT / "skills").iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ),
    )
    def test_skill_declares_name_and_description(self, skill_dir):
        """description 是触发器；缺了 Claude 不知道何时该用它。"""
        fm = self._frontmatter(PLUGIN_ROOT / "skills" / skill_dir / "SKILL.md")
        assert "name:" in fm, f"{skill_dir} 缺 name"
        assert "description:" in fm, f"{skill_dir} 缺 description"

    @pytest.mark.parametrize(
        "skill_dir",
        sorted(
            d.name for d in (PLUGIN_ROOT / "skills").iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ),
    )
    def test_skill_name_matches_directory(self, skill_dir):
        """name 与目录名不一致会让调用名与预期不符。"""
        fm = self._frontmatter(PLUGIN_ROOT / "skills" / skill_dir / "SKILL.md")
        declared = re.search(r"^name:\s*(\S+)", fm, re.M)
        if declared:
            assert declared.group(1) == skill_dir

    def test_public_skill_count_matches_documented(self):
        """README 与文档都称若干个 public skill —— 数量漂移说明文档过期。"""
        public = [
            d.name
            for d in (PLUGIN_ROOT / "skills").iterdir()
            if d.is_dir()
            and "user-invocable: false" not in (d / "SKILL.md").read_text(encoding="utf-8")
        ]
        assert len(public) == 6, f"public skill 数变了: {sorted(public)}"
