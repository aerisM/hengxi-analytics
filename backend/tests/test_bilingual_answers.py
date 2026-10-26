"""Offline contract tests: stubbed model, real workflow, MCP and DuckDB."""
import json
import re
from unittest.mock import patch

import pytest

from app.config import Settings
from app.demo_data import seed_demo_data
from app.language import response_language
from app.querying.models import SqlExecution
from app.querying.response_generator import ResponseGenerator
from app.retrieval import SchemaIndex
from app.service import AskDataService
from tests.test_service import FakeModelClient


@pytest.mark.parametrize('query,expected', [
    ('Show sales revenue by region', 'en'), ('按地区统计销售额', 'zh'),
    ('按 region 统计 paid_amount', 'zh'), ('Show sales for "华东"', 'en'),
    ('Show sales for `客户等级`', 'en'), ('统计销售额，用英文回答', 'en'),
    ('Show sales; reply in Chinese', 'zh'), ('2026-08', 'zh'),
])
def test_language_policy(query, expected):
    assert response_language(query) == expected


class LanguageModel(FakeModelClient):
    def __init__(self):
        super().__init__()
        self.prompts = []

    def chat_json(self, system, user):
        self.prompts.append(system)
        english = 'Response language: English.' in system
        if system.startswith('你是问数系统的请求预处理器'):
            query = user.split('当前问题：', 1)[1].split('\n近期轻量上下文：', 1)[0]
            if query in ('Hello', '你好'):
                return dict(action='direct_response', response='Hello!' if english else '你好！')
            if query in ('Explain the result', '解释刚才的结果', 'Write a report', '写一份分析报告'):
                return dict(action='data_qa')
            # Intentionally rewrite to Chinese to verify original language survives.
            return dict(action='database_query', standalone_query='统计各地区销售额', retrieval={
                'retrieval_terms': ['region', 'sales revenue', '地区', '销售额'],
                'metrics': [], 'operations': [],
            })
        if system.startswith('你是单数据库问数智能体'):
            columns = ('Region', 'Revenue') if english else ('地区', '销售额')
            return dict(action='call_tool', tool_name='query_askdata_mock', arguments={
                'sql': f'SELECT region AS "{columns[0]}", SUM(paid_amount) AS "{columns[1]}" '
                       'FROM orders_current GROUP BY region ORDER BY region'
            })
        if system.startswith('你是数据问答智能体'):
            payload = json.loads(user)
            if payload['query'] in ('Write a report', '写一份分析报告'):
                source = payload['available_data_sources'][0]
                return dict(action='report', title='Sales report' if english else '销售报告',
                            markdown='# Sales report\n\nRevenue by region.' if english else '# 销售报告\n\n地区销售额。',
                            tool_calls=[dict(name='build_bar_chart', arguments=dict(
                                title='Revenue by region' if english else '地区销售额',
                                source_task_id=source['task_id'], category_field=source['columns'][0],
                                value_field=source['columns'][1]))])
            return dict(action='answer', answer='Here is the analysis.' if english else '这是结果分析。')
        if system.startswith('你是查询结果整理器'):
            return dict(valid=True, title='Results' if english else '结果', analysis='Completed.' if english else '已完成。')
        return super().chat_json(system, user)


@pytest.fixture
def service(tmp_path):
    root = tmp_path / 'databases'
    seed_demo_data(database_dir=root / 'askdata_mock')
    model = LanguageModel()
    config = Settings(api_key='', embedding_dimensions=32, session_archive_enabled=False,
                      short_term_summary_enabled=False)
    with patch('app.querying.duckdb_engine.DATABASE_ROOT', root):
        yield AskDataService(model, SchemaIndex(model, config, tmp_path / 'schema.json'))


def test_paired_queries_preserve_values_and_localize_answers(service):
    zh = service.submit('按地区统计销售额', 'zh')
    en = service.submit('Show sales revenue by region', 'en')
    assert zh.status == en.status == 'completed'
    assert [list(row.values()) for row in zh.rows] == [list(row.values()) for row in en.rows]
    assert en.columns == ['Region', 'Revenue']
    assert zh.columns == ['地区', '销售额']
    assert en.analysis.startswith('Summarized')
    assert zh.analysis.startswith('已按')
    assert en.message == 'Query completed'
    assert not re.search(r'[\u4e00-\u9fff]', en.result_title)
    assert en.standalone_query == '统计各地区销售额'
    assert all('Response language:' in prompt for prompt in service.model_client.prompts)


@pytest.mark.parametrize('language,query,metric', [
    ('en', 'Best customers', 'sales revenue'), ('zh', '表现最好的客户', '销售额'),
])
def test_clarification_resume_keeps_language(service, language, query, metric):
    waiting = service.submit(query, language)
    assert waiting.status == 'waiting_clarification'
    assert waiting.clarification.allow_free_text
    assert ('Which metric' in waiting.clarification.question) is (language == 'en')
    unknown = service.submit('unknown metric', language)
    assert unknown.task_id == waiting.task_id
    assert unknown.status == 'waiting_clarification'
    result = service.submit(metric, language)
    assert result.status == 'completed'
    assert result.task_id == waiting.task_id
    assert result.analysis.startswith('Summarized' if language == 'en' else '已按')


def test_each_new_turn_can_change_language_in_same_session(service):
    en = service.submit('Show sales revenue by region', 'switch')
    zh = service.submit('按地区统计销售额', 'switch')
    assert en.message == 'Query completed'
    assert zh.message == '查询完成'


@pytest.mark.parametrize('query,expected', [('Hello', 'Hello!'), ('你好', '你好！')])
def test_direct_answer_language(service, query, expected):
    assert service.submit(query, query).analysis == expected


@pytest.mark.parametrize('language,query,report', [
    ('en', 'Explain the result', False), ('zh', '解释刚才的结果', False),
    ('en', 'Write a report', True), ('zh', '写一份分析报告', True),
])
def test_analysis_and_report_language_without_new_database_query(service, language, query, report):
    previous = service.submit('按地区统计销售额', 'qa')
    result = service.submit(query, 'qa')
    assert result.route == 'data_qa'
    assert result.sql is None
    assert bool(result.report) is report
    assert bool(re.search(r'[\u4e00-\u9fff]', result.analysis)) is (language == 'zh')
    if report:
        chart = result.report.visualizations[0]
        assert chart.source_task_id == previous.task_id
        assert chart.category_field == previous.columns[0]
        assert bool(re.search(r'[\u4e00-\u9fff]', chart.title)) is (language == 'zh')


@pytest.mark.parametrize('query,language', [('Show sales', 'en'), ('查询销售额', 'zh')])
def test_empty_summary_and_model_summary(query, language):
    model = LanguageModel()
    execution = SqlExecution(sql='SELECT region, SUM(paid_amount) AS revenue FROM orders_current GROUP BY region',
                             success=True, columns=['region', 'revenue'], rows=[])
    result = ResponseGenerator(model).finalize(query, execution, '', '')
    assert ('no matching data' in result['analysis']) is (language == 'en')
    execution.sql = 'SELECT region, paid_amount FROM orders_current'
    ResponseGenerator(model).finalize(query, execution, '', '')
    assert f'Response language: {"English" if language == "en" else "Simplified Chinese"}.' in model.prompts[-1]


def test_english_failure_paths(service):
    with patch.object(service.model_client, 'chat_json', side_effect=RuntimeError('连接失败')):
        result = service.submit('Show sales', 'offline')
    assert result.analysis.startswith('The model service')
    from app.errors import PipelineStageError
    with patch.object(service.schema_index, 'retrieve', side_effect=PipelineStageError('schema_rerank', '失败')):
        result = service.submit('Show sales', 'failed')
    assert result.status == 'failed'
    assert result.analysis.startswith('The request could not')
    assert result.execution_log[0]['error'] == '失败'


def test_summary_failure_preserves_english_and_data(service):
    from app.errors import PipelineStageError
    with patch.object(service.workflow.response_generator, 'finalize', side_effect=PipelineStageError('result_analysis', '失败')):
        result = service.submit('Show sales revenue by region', 'summary-failed')
    assert result.status == 'completed'
    assert result.rows
    assert result.analysis.startswith('SQL executed successfully')
