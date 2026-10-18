from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import Settings
from app.retrieval.service import SchemaIndex, SYNONYMS
from app.retrieval.store import FieldDocument, LocalSchemaStore
from app.security import AccessController
from app.workflows.query_intent import QueryIntentGuard


@pytest.mark.parametrize('query,missing', [
    ('按销售额排名客户', False), ('Rank customers by sales revenue', False),
    ('订单数最多的客户', False), ('Top customers by number of orders', False),
    ('表现最好的客户', True), ('Best customers', True),
    ('Worst performing stores', True), ('Top orders', True),
    ('Top customers by corporate reputation', True),
])
def test_bilingual_ranking_criteria(query, missing):
    scope = AccessController().resolve('demo_current_sales').public()
    assert QueryIntentGuard.missing_ranking_metric(query, {}, {}, scope) is missing


def test_metric_matching_respects_english_word_boundaries():
    assert not QueryIntentGuard._matches_metric('corporate', {'rate'})
    assert QueryIntentGuard._matches_metric('sales  revenue', {'sales revenue'})


@pytest.mark.parametrize('prebuilt', [False, True])
def test_aliases_reach_all_index_channels_and_bm25(prebuilt, tmp_path):
    field = {'name': 'paid_amount', 'label': '实付金额', 'description': '实际支付金额',
             'type': '数值', 'role': 'metric', 'data_profile': {'sample_values': [12]}}
    if prebuilt:
        field['index_content'] = dict(keyword_text='实付金额', vector_text='实付金额', rerank_text='实付金额')
    table = {'id': 'orders_current', 'name': 'orders_current', 'label': '订单',
             'description': '订单数据', 'fields': [field]}
    index = SchemaIndex(config=Settings(api_key=''), index_path=tmp_path / 'index.json')
    docs = []
    index._append_table_documents(docs, None, table)
    raw = docs[0]
    for channel in ('keyword_text', 'semantic_text', 'rerank_text'):
        assert 'sales revenue' in raw[channel]
        assert '销售额' in raw[channel]
    store = LocalSchemaStore(tmp_path / 'store.json')
    store.replace_all('test', [FieldDocument(**raw, dense_vector=[1.0], schema_version='test', content_hash='test')], 'test')
    assert store.bm25_search('sales revenue', 1)[0][0] == 0
    assert store.bm25_search('销售额', 1)[0][0] == 0


def test_vocabulary_change_invalidates_cached_index():
    before = SchemaIndex._schema_signature()
    with patch.dict(SYNONYMS, {'paid_amount': ['new business synonym']}):
        assert SchemaIndex._schema_signature() != before
