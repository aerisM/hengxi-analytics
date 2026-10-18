from __future__ import annotations

from typing import Any

from ..language import choose, response_language
from ..database import SCHEMA
from ..models import Clarification, Interpretation, QueryResult
from ..querying.models import SqlExecution
from ..querying.data_qa_agent import DataQaResult


class ResultBuilder:
    """将工作流状态转换为 API 响应。"""

    @staticmethod
    def qa(
        task_id: str,
        generated: DataQaResult,
        intent: dict[str, Any],
        analysis_sources: list[dict[str, Any]],
    ) -> QueryResult:
        language = intent.get("response_language", "zh")
        def t(zh: str, en: str) -> str:
            return choose(language, zh, en)

        return QueryResult(
            task_id=task_id,
            status="completed",
            route="data_qa",
            message=t("已进入数据问答，没有重复查询数据库。", "Analyzing existing data without querying the database again."),
            columns=[],
            rows=[],
            analysis=generated.report.markdown if generated.report else generated.answer,
            route_reason=str(intent.get("reason") or t("数据问答", "Data analysis")),
            steps=(
                [t("一级意图路由：数据问答", "Route request to data analysis"), t("读取可用分析上下文", "Read available analysis context"), t("生成Markdown报告并调用展示工具", "Generate a Markdown report and charts")]
                if generated.report
                else [t("一级意图路由：数据问答", "Route request to data analysis"), t("读取可用分析上下文", "Read available analysis context"), t("生成文字回答", "Generate an answer")]
            ),
            result_title=generated.report.title if generated.report else t("结果解读", "Result analysis"),
            analysis_sources=analysis_sources,
            workflow_mode="qa_report" if generated.report else "qa",
            report=generated.report,
            report_tool_calls=generated.tool_calls,
        )

    @staticmethod
    def direct_response(
        task_id: str,
        response: str,
        intent: dict[str, Any],
        execution_log: list[dict[str, Any]],
    ) -> QueryResult:
        language = intent.get("response_language", "zh")
        def t(zh: str, en: str) -> str:
            return choose(language, zh, en)

        response_type = str(intent.get("response_type") or "answer")
        fallback_used = intent.get("source") == "model_unavailable_fallback"
        return QueryResult(
            task_id=task_id,
            status="completed",
            route="direct_response",
            message=t("请补充说明", "Please provide more details") if response_type == "clarification" else t("已直接回答", "Answered directly"),
            columns=[],
            rows=[],
            analysis=response,
            route_reason=str(intent.get("reason") or t("预处理模型直接回复", "Direct response from preprocessing")),
            steps=[t("一次请求预处理", "Preprocess the request"), t("预处理模型直接生成回复", "Generate a direct response")],
            execution_log=execution_log,
            workflow_mode="route_fallback" if fallback_used else "direct_response",
        )

    @staticmethod
    def waiting(state: dict[str, Any]) -> QueryResult:
        language = state.get("response_language") or response_language(state.get("query", ""))
        def t(zh: str, en: str) -> str:
            return choose(language, zh, en)

        payload = state.get("clarification") or {}
        clarification = Clarification(
            parameter=str(payload.get("parameter") or "other"),
            question=str(payload.get("question") or t("请补充本次查询所需信息", "Please provide the information needed for this query")),
            reason=str(payload.get("reason") or t("该信息会改变查询结果", "This information affects the query results")),
            options=payload.get("options") or [],
            allow_free_text=bool(payload.get("allow_free_text")),
        )
        labels = (", " if language == "en" else "、").join(item.label for item in clarification.options)
        return QueryResult(
            task_id=state["task_id"],
            status="waiting_clarification",
            route="database_query",
            message=t("查询已暂停，等待你的补充信息。", "The query is paused while awaiting your clarification."),
            clarification=clarification,
            analysis=(
                t(f"{clarification.question} 请回复具体指标名称。", f"{clarification.question} Please specify a metric.")
                if clarification.allow_free_text
                else t(f"{clarification.question} 你可以直接回复：{labels}。", f"{clarification.question} You can reply with: {labels}.")
            ),
            route_reason=str(state.get("intent", {}).get("reason") or t("问数", "Data query")),
            retrieval=ResultBuilder.public_retrieval(state.get("retrieval") or {}),
            standalone_query=state.get("standalone_query"),
            schema_graph=state.get("schema_graph"),
            steps=[t("一次请求预处理：路由并提取检索词", "Route the request and extract search terms"), t("召回字段并构建Schema图", "Retrieve fields and build the schema graph"), t("LangGraph暂停并等待用户回复", "Pause the workflow for clarification")],
            workflow_mode=str(state.get("workflow_mode") or "langgraph_hitl"),
        )

    @staticmethod
    def completed(
        state: dict[str, Any],
        executions: list[SqlExecution],
        combined: SqlExecution,
        final: dict[str, Any],
        tool_calls: list[dict[str, Any]],
        execution_log: list[dict[str, Any]],
    ) -> QueryResult:
        language = state.get("response_language") or response_language(state.get("query", ""))
        def t(zh: str, en: str) -> str:
            return choose(language, zh, en)

        separator = ", " if language == "en" else "、"
        graph = state.get("schema_graph") or {}
        table_ids = [item["id"] for item in graph.get("tables", [])]
        table_labels = [item["id"] if language == "en" else item["label"] for item in SCHEMA if item["id"] in table_ids]
        metric_columns = [
            column for column in combined.columns
            if any(term in column.lower() for term in ("额", "数", "率", "平均", "目标", "amount", "revenue", "count", "rate", "average", "target", "sales", "total"))
        ]
        dimension_columns = [column for column in combined.columns if column not in metric_columns]
        mode = str(state.get("workflow_mode") or "single_database_agent")
        steps = [
            t("一次预处理：上下文聚合、问答/问数路由、检索词提取", "Resolve context, route the request, and extract search terms"),
            *([t(f"独立查询改写：{state.get('standalone_query')}", f"Standalone query: {state.get('standalone_query')}")] if state.get("rewritten") else []),
            t("BM25与Dense召回，经RRF融合和Rerank阈值筛选", "Retrieve with BM25 and embeddings, fuse with RRF, and rerank"),
            t(f"构建Schema图：{len(graph.get('tables', []))}张表 / {len(graph.get('fields', []))}个字段", f"Schema graph: {len(graph.get('tables', []))} tables / {len(graph.get('fields', []))} fields"),
            t("单库智能体选择MCP工具并生成SQL", "Select MCP tools and generate SQL for one database") if mode == "single_database_agent" else t("多库路径：按数据库生成Handoff", "Prepare database handoffs"),
            t("通过MCP数据库工具调用DuckDB并整理结果", "Execute DuckDB queries through MCP and format results"),
        ]
        if state.get("analysis_sources"):
            steps.append(t(f"综合分析{len(state['analysis_sources'])}张用户指定历史表", f"Analyze {len(state['analysis_sources'])} selected historical result tables"))
        return QueryResult(
            task_id=state["task_id"],
            status="completed" if final.get("valid", True) else "failed",
            route="database_query",
            message=t("查询完成", "Query completed") if final.get("valid", True) else t("结果校验未通过", "Result validation failed"),
            interpretation=Interpretation(
                metric=separator.join(metric_columns) or t("查询结果指标", "Result metrics"),
                dimension=separator.join(dimension_columns) or t("无分组维度", "No grouping dimension"),
                time_range=separator.join(
                    (state.get("extraction") or {}).get("time_expressions") or []
                ) or t("未指定", "Not specified"),
                table=separator.join(table_labels) or t("Schema召回数据表", "Retrieved schema tables"),
                assumptions=[t("Schema字段经过Rerank阈值筛选", "Schema fields passed the reranking threshold"), t("用户拖入字段为确定性约束", "User-selected fields are explicit constraints")],
            ),
            steps=steps,
            sql=combined.sql,
            columns=combined.columns,
            rows=combined.rows,
            analysis=final.get("analysis"),
            route_reason=str(state.get("intent", {}).get("reason") or t("问数", "Data query")),
            retrieval=ResultBuilder.public_retrieval(state.get("retrieval") or {}),
            execution_log=execution_log,
            tool_calls=tool_calls,
            result_title=final.get("title") or t("查询结果", "Query results"),
            analysis_sources=state.get("analysis_sources") or [],
            standalone_query=state.get("standalone_query"),
            schema_graph=graph,
            workflow_mode=mode,
        )

    @staticmethod
    def failed(state: dict[str, Any], execution: SqlExecution, log: list[dict[str, Any]]) -> QueryResult:
        language = state.get("response_language") or response_language(state.get("query", ""))
        def t(zh: str, en: str) -> str:
            return choose(language, zh, en)

        return QueryResult(
            task_id=state["task_id"],
            status="failed",
            route="database_query",
            message=t("SQL生成或执行失败", "SQL generation or execution failed"),
            analysis=t(execution.error or "查询失败", "The query could not be generated or executed. Please review the question and try again."),
            sql=execution.sql or None,
            route_reason=str(state.get("intent", {}).get("reason") or t("问数", "Data query")),
            retrieval=ResultBuilder.public_retrieval(state.get("retrieval") or {}),
            execution_log=log,
            standalone_query=state.get("standalone_query"),
            schema_graph=state.get("schema_graph"),
            workflow_mode=str(state.get("workflow_mode") or "single_database_agent"),
        )

    @staticmethod
    def public_retrieval(retrieval: dict[str, Any]) -> dict[str, Any]:
        visible = {
            "query", "retrieval_terms", "extraction", "embedding_source",
            "rerank_source", "threshold", "bm25_count", "dense_count", "rrf_count",
            "candidate_count", "selected_count", "hits", "table_candidates",
            "low_confidence_candidates", "schema_graph",
        }
        return {key: value for key, value in retrieval.items() if key in visible}
