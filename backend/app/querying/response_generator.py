from __future__ import annotations

from decimal import Decimal
from typing import Any

import sqlglot
from sqlglot import exp

from ..config import Settings, settings
from ..errors import PipelineStageError
from ..model_client import ModelClient
from .models import SqlExecution


class ResponseGenerator:
    """生成问答内容和查询结果说明。"""

    def __init__(
        self,
        model_client: ModelClient,
        config: Settings | None = None,
    ) -> None:
        self.model_client = model_client
        self.table_row_limit = max(1, (config or settings).context_table_row_limit)

    def finalize(
        self,
        query: str,
        execution: SqlExecution,
        schema_context: str,
        analysis_context: str,
    ) -> dict[str, Any]:
        simple_result = self._simple_grouped_result(execution, analysis_context)
        if simple_result is not None:
            return simple_result

        system = """你是查询结果整理器。检查结果能否回答问题，并生成简短标题和一到两句说明。
只能使用结果中真实存在的数值。只返回JSON：
{"valid":true,"reason":"...","title":"...","analysis":"..."}。"""
        user = (
            f"问题：{query}\nSQL：{execution.sql}\n列：{execution.columns}\n"
            f"结果数据：{execution.rows[: self.table_row_limit]}\nSchema：{schema_context}\n"
            f"用户保存的分析表格：{analysis_context or '无'}"
        )
        try:
            payload = self.model_client.chat_json(system, user)
            return {
                "valid": bool(payload.get("valid", True)),
                "reason": str(payload.get("reason") or "结果检查通过"),
                "title": str(payload.get("title") or "查询结果"),
                "analysis": str(payload.get("analysis") or f"查询返回{len(execution.rows)}行。"),
            }
        except RuntimeError as exc:
            raise PipelineStageError("result_analysis", str(exc)) from exc

    @staticmethod
    def _simple_grouped_result(
        execution: SqlExecution, analysis_context: str
    ) -> dict[str, Any] | None:
        """简单二列表格直接生成保守摘要，避免额外模型调用及数值幻觉。"""
        if analysis_context or len(execution.columns) != 2 or len(execution.rows) > 20:
            return None
        try:
            statement = sqlglot.parse_one(execution.sql, read="duckdb")
        except sqlglot.errors.ParseError:
            return None
        if not isinstance(statement, exp.Select) or not statement.args.get("group"):
            return None
        dimension, metric = execution.columns
        if not all(
            isinstance(row.get(metric), (int, float, Decimal))
            and not isinstance(row.get(metric), bool)
            and not isinstance(row.get(dimension), (int, float, Decimal))
            for row in execution.rows
        ):
            return None
        count = len(execution.rows)
        return {
            "valid": True,
            "reason": "SQL已成功执行；简单分组结果使用确定性摘要",
            "title": f"{dimension}·{metric}",
            "analysis": (
                f"已按{dimension}汇总{metric}，返回{count}行结果。"
                if count else "查询已完成，但没有符合条件的数据。"
            ),
        }
