"""Check paired fixtures and their reference SQL without external model calls."""
import json
from pathlib import Path

import pytest

from app.language import response_language
from app.querying.duckdb_engine import DuckDbEngine
from app.security import AccessController

CASES = json.loads((Path(__file__).parents[1] / 'evaluation/cases-bilingual.json').read_text())['cases']


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_paired_fixture_and_reference_sql(case):
    assert response_language(case['en']) == 'en'
    assert response_language(case['zh']) == 'zh'
    if case.get('gold_sql'):
        result = DuckDbEngine().execute(case['database'], case['gold_sql'], AccessController().resolve(case['user_id']))
        assert result.success, result.error
        assert result.rows
        assert case['required_fields']
    else:
        assert case['expected_status'] == 'waiting_clarification'
