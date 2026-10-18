"""Live paired evaluation; requires LLM_API_KEY and consumes model credits."""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.language import response_language
from app.querying.duckdb_engine import DuckDbEngine
from app.security import AccessController
from app.services.askdata_service import AskDataService
from run_benchmark import results_equal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'results' / 'bilingual-latest.json')
    args = parser.parse_args()
    service = AskDataService()
    if not service.model_client.enabled:
        parser.error('Set LLM_API_KEY in the environment or backend/.env before running the live benchmark.')
    suite = json.loads((Path(__file__).parent / 'cases-bilingual.json').read_text())
    run_id = uuid.uuid4().hex[:12]
    records = []
    engine = DuckDbEngine()
    for case in suite['cases']:
        pair = {'id': case['id'], 'languages': {}}
        gold = None
        if case.get('gold_sql'):
            gold = engine.execute(case['database'], case['gold_sql'], AccessController().resolve(case['user_id']))
        for language in ('zh', 'en'):
            start = time.perf_counter()
            try:
                result = service.submit(case[language], f'{run_id}-{case["id"]}-{language}', user_id=case['user_id'])
                hits = {hit['doc_id'] for hit in (result.retrieval or {}).get('hits', [])}
                record = dict(
                    query=case[language], status=result.status,
                    status_match=result.status == case['expected_status'],
                    sql=result.sql, rows=result.rows, columns=result.columns,
                    title=result.result_title, analysis=result.analysis,
                    clarification=result.clarification.model_dump() if result.clarification else None,
                    required_fields=case.get('required_fields', []), retrieved_fields=sorted(hits),
                )
                prose = result.clarification.question if result.clarification else result.analysis or result.message
                # Only a review aid: untranslated data values can affect this heuristic.
                record['language_heuristic_match'] = response_language(prose) == language
                if gold is not None:
                    record['gold_match'] = bool(gold.success and result.status == 'completed' and results_equal(result.rows, gold.rows))
                    record['complete_schema_recall'] = set(case['required_fields']) <= hits
                pair['languages'][language] = record
            except Exception as exc:
                pair['languages'][language] = dict(query=case[language], status_match=False, error=str(exc))
            pair['languages'][language]['elapsed_seconds'] = round(time.perf_counter() - start, 3)
        zh, en = (pair['languages'][key] for key in ('zh', 'en'))
        if gold is not None:
            pair['pair_result_match'] = bool(zh.get('gold_match') and en.get('gold_match') and results_equal(zh['rows'], en['rows']))
        pair['passed'] = all(r['status_match'] for r in (zh, en)) and (gold is None or pair['pair_result_match'])
        records.append(pair)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(dict(version=suite['version'], run_id=run_id, records=records), ensure_ascii=False, indent=2))
        print(f"{case['id']}: {'PASS' if pair['passed'] else 'FAIL'}", flush=True)
    print(f'Results: {args.output}. Review language_heuristic_match and generated text manually.')
    return 0 if all(pair['passed'] for pair in records) else 1


if __name__ == '__main__':
    raise SystemExit(main())
