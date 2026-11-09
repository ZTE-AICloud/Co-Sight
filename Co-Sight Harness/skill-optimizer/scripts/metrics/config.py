"""
MetricsConfig — 指标配置系统（自然语言 task 单一格式）
================================================

设计原则：
- 唯一配置格式：`extraction.task` 自然语言 + `output_schema` 机器可读契约
- `metrics` 段只保留必要元信息（name / weight / direction）
- 不再有硬编码 file_pattern / json_path / aggregate（由 LLM 自主探查）
- 不再有 RuleBasedExtractor 旁路（删除依赖）

加载优先级：
    --eval-config CLI 参数  >  SKILLX_EVAL_CONFIG 环境变量
    >  framework_configs/eval-config.yaml（新默认路径，由 framework 维护者管）
    >  内嵌默认 task 兜底
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

# ── 内嵌默认 task（无 yaml 时的兜底） ────────────────────────────

DEFAULT_TASK_TEMPLATE = """\
**⚠️ 必读参考文档**（执行任务前先用 Read 工具读完）：
`framework_configs/skill-create-guidelines.md`（587 行）—— 业务方 Skill 制作标准，
含代码化精神(Code-First)、scripts/ 拆分、references/ 复用、LLM 断点协议、异常处理规范、16 章节模板等。
**本任务虽不直接制作 Skill，但提取规则的精度取决于你对此标准的理解**：
- `recall` / `precision` 字段是 5 维评分法算出的**原始召回/精确率**（0~1），不是 f1
- `f1` 不在 JSON 顶层直接存在，**必须用 `F1 = 2 × recall × precision / (recall + precision)` 算**
- precision 是 `null` 时（candidate_scenarios_count=0）直接 f1=0
- 5 维详情在 `scenarios[0].dimension_scores` dict 里（theme_match/granularity_match 等 5 键各 0-20）

---

扫描 {data_dir} 下的所有子目录，自主探查产物 schema（不要假设具体字段名或
目录结构），按以下目标提取 1 个指标：

1. result_score: 在所有 .json 文件中递归查找数值型评分字段（接受顶层或
   嵌套对象中的 score / f1 / value / metric 等字段名），跨所有文件求算术
   平均，**统一以百分制 0~100 输出**(若原值是 0~100,保留原值;若原值是 0~1,乘以 100),
   保留 2 位小数。

**重要**:本配置只评估 result_score 一个维度。不需要提取耗时/Token/工具调用
等效率指标。

当 result_score < 100 时,必须把根因写到 info.zero_root_cause:
- 候选文档某章节为空
- 候选与对比标准无交集(字段名/格式不一致)
- 提取规则与本批次产物 schema 不匹配
"""


DEFAULT_OUTPUT_SCHEMA = {
    "result_score": {"type": "number", "range": [0, 100]},
    "info": {
        "result_score_raw": {"type": "number", "range": [0, 100]},
        "result_score_source": {"type": "string"},
        "case_scores": {"type": "object"},
        "aggregate_formula": {"type": "string"},
        "zero_root_cause": {"type": "string", "required": False},
    },
}


# ── 数据结构 ───────────────────────────────────────────────

@dataclass(frozen=True)
class MetricDefinition:
    """单个指标的元信息。仅保留必要字段。"""
    name: str
    weight: float = 0.0
    direction: str = "higher_is_better"  # higher_is_better | lower_is_better
    normalization: str = "min_max"       # min_max | none | linear


@dataclass
class MetricsConfig:
    """指标配置。唯一合法格式：extraction_task + output_schema。"""
    extraction_task: str                                            # 必填，自然语言任务
    output_schema: Dict[str, Any] = field(default_factory=dict)    # 必填，输出契约
    metrics: Dict[str, MetricDefinition] = field(default_factory=dict)
    composite_formula: str = "result_score"
    extractor_agent: str = "ExtractionAgent"                       # 子 Agent 类型
    focus_blocks: Dict[str, str] = field(default_factory=dict)     # 可选,按 only_f1 注入引导文本

    @staticmethod
    def default_eval_config() -> "MetricsConfig":
        """代码兜底：内嵌默认 task + schema + 单指标元信息。"""
        return MetricsConfig(
            extraction_task=DEFAULT_TASK_TEMPLATE,
            output_schema=DEFAULT_OUTPUT_SCHEMA,
            metrics={
                "result_score":    MetricDefinition("result_score",    weight=1.0, normalization="none"),
            },
        )

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "MetricsConfig":
        """从 dict 加载。"""
        extraction = d.get("extraction", {})

        # 唯一合法格式：extraction.task 非空
        task = extraction.get("task")
        if not task:
            raise ValueError(
                "eval-config 必须包含 extraction.task（自然语言任务描述）。"
                "请参考 framework_configs/eval-config.yaml。"
            )

        schema = d.get("output_schema", {})

        metrics = {}
        for name, info in d.get("metrics", {}).items():
            metrics[name] = MetricDefinition(
                name=name,
                weight=float(info.get("weight", 0)),
                direction=info.get("direction", "higher_is_better"),
                normalization=info.get("normalization", "min_max"),
            )

        return MetricsConfig(
            extraction_task=task,
            output_schema=schema,
            metrics=metrics,
            composite_formula=d.get("composite_formula", "result_score"),
            extractor_agent=extraction.get("agent", "ExtractionAgent"),
            focus_blocks=d.get("focus_blocks", {}) or {},
        )

    @staticmethod
    def from_yaml(path: str) -> "MetricsConfig":
        """从 YAML 文件加载。

        支持的格式：
        - `framework_configs/eval-config.yaml`(含 `{{ user.xxx }}` 渲染)
        - 用户自定义任意路径
        """
        import yaml
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"评估配置文件不存在: {path}")
        raw = p.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        # 兼容旧 framework_configs/eval-config.yaml（无 jinja2 引用）；framework YAML
        # 的 `{{ user.xxx }}` 已在加载时由 config_layered 渲染过，传进来的
        # 已是渲染后的 dict,from_dict 不会重复处理
        return MetricsConfig.from_dict(data)

    @staticmethod
    def load(config_path: str = "") -> "MetricsConfig":
        """按加载优先级加载：CLI > env > framework 默认 > 代码兜底。"""
        import os as _os

        # 1. CLI 显式指定
        if config_path and Path(config_path).exists():
            return MetricsConfig.from_yaml(config_path)

        # 2. 环境变量
        env_path = _os.environ.get("SKILLX_EVAL_CONFIG", "")
        if env_path and Path(env_path).exists():
            return MetricsConfig.from_yaml(env_path)

        # 3. framework_configs/eval-config.yaml（新默认，含 user-config 渲染）
        framework_yaml = Path(__file__).parent.parent.parent / "framework_configs" / "eval-config.yaml"
        if framework_yaml.exists():
            try:
                from config_layered import load_framework_config_with_user
                rendered = load_framework_config_with_user("eval", framework_path=framework_yaml)
                if rendered:
                    return MetricsConfig.from_dict(rendered)
            except Exception as e:
                print(f"  [MetricsConfig] framework YAML 加载失败: {type(e).__name__}: {e}")

        # 4. 代码兜底
        return MetricsConfig.default_eval_config()

    # ── 查询方法 ──

    def has_extraction_task(self) -> bool:
        return bool(self.extraction_task)

    def get_extractor_agent(self) -> str:
        return self.extractor_agent

    def quantitative_names(self) -> list[str]:
        """返回量化指标（weight > 0）列表。"""
        return [n for n, m in self.metrics.items() if m.weight > 0]

    def reference_names(self) -> list[str]:
        """返回参考指标（weight == 0）列表。"""
        return [n for n, m in self.metrics.items() if m.weight == 0]

    def get_definition(self, name: str) -> Optional[MetricDefinition]:
        return self.metrics.get(name)

    def total_weight(self) -> float:
        return sum(m.weight for m in self.metrics.values() if m.weight > 0)

    def is_only_f1_mode(self) -> bool:
        """是否仅 result_score 一个量化指标(weight>0)。

        业务方配置示例:result_score weight=1.0,其他 4 个指标 weight=0.0 → True
        """
        quant = self.quantitative_names()
        return len(quant) == 1 and quant[0] == "result_score"

    def get_focus_block(self, only_f1: bool) -> str:
        """按 only_f1 选 focus_blocks 中对应 block,缺失时返回空字符串。

        用于在 extraction.task 模板中替换 {{ focus_block }} 占位符,
        让 LLM 在 only_f1 模式下明确**不要**分析耗时/Token/工具调用等指标。
        """
        blocks = self.focus_blocks or {}
        key = "f1_focus" if only_f1 else "general_focus"
        return blocks.get(key, "") or ""
