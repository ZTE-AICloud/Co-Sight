"""
格式无关的评测产物扫描器（极简兜底）
====================================
仅在 ExtractionAgent 完全失败时使用，返回零分并记录错误。
"""

from pathlib import Path
from typing import Optional

from .models import RawMetric


class ArtifactScanner:
    """极简兜底：ExtractionAgent 失败时返回零分。"""

    def scan_run(self, run_data_dir: Path, round_num: int,
                 candidate_id: int, run_index: int) -> RawMetric:
        """兜底返回零分。"""
        return RawMetric(
            round_num=round_num,
            candidate_id=candidate_id,
            run_index=run_index,
            result_score=0.0,
            info={
                "result_score_raw": 0.0,
                "result_score_source": "ArtifactScanner（兜底，ExtractionAgent 失败）",
            },
        )