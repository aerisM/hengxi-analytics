from __future__ import annotations

import json, statistics, sys, time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.querying.duckdb_engine import DuckDbEngine
from app.security.access_control import AccessController
from app.services.askdata_service import AskDataService
from run_benchmark import percentile, ratio, results_equal

HERE=Path(__file__).resolve().parent

def main():
    base=json.loads((HERE/'cases.json').read_text())
    extra=json.loads((HERE/'cases-v2-extra.json').read_text())
    clear=[]
    for c in base['clear_cases']:
        clear.append({**c,'id':'v1_'+c['id'],'difficulty':'medium','database':'askdata_mock','user_id':'demo_analyst'})
    clear.extend(extra['clear_cases'])
    ambiguous=[]
    for c in base['ambiguous_cases']:
        ambiguous.append({**c,'id':'v1_'+c['id'],'user_id':'demo_analyst'})
    ambiguous.extend(extra['ambiguous_cases'])
    cases=[*({**c,'expected':'completed'} for c in clear),*({**c,'expected':'waiting_clarification'} for c in ambiguous)]
    service=AskDataService(); engine=DuckDbEngine(); records=[]
    print(f"locked_suite=v2-extended clear={len(clear)} ambiguous={len(ambiguous)}",flush=True)
    for i,c in enumerate(cases,1):
        started=time.perf_counter(); result=None; error=None
        try: result=service.submit(c['query'],f"eval-v2-{c['id']}",user_id=c['user_id'])
        except Exception as exc: error=f"{type(exc).__name__}: {exc}"
        rec={'id':c['id'],'query':c['query'],'difficulty':c.get('difficulty'),'database':c.get('database'),'expected_status':c['expected'],'actual_status':result.status if result else None,'elapsed_seconds':round(time.perf_counter()-started,3),'exception':error}
        if result:
            hits={str(x.get('doc_id')) for x in (result.retrieval or {}).get('hits',[])}
            rec.update({'sql':result.sql,'analysis':result.analysis,'retrieved_doc_ids':sorted(hits),'execution_log':result.execution_log,'stage_timings_ms':result.stage_timings_ms,'clarification':result.clarification.model_dump() if result.clarification else None})
            if c['expected']=='completed':
                req=set(c['required_fields']); gold=engine.execute(c['database'],c['gold_sql'],AccessController().resolve(c['user_id']))
                rec.update({'required_fields':sorted(req),'recalled_required_fields':sorted(req&hits),'field_recall':ratio(len(req&hits),len(req)),'complete_schema_recall':req<=hits,'gold_sql':c['gold_sql'],'gold_rows':gold.rows,'actual_rows':result.rows,'result_match':bool(result.status=='completed' and gold.success and results_equal(result.rows,gold.rows))})
        records.append(rec)
        print(f"[{i:02d}/{len(cases)}] {c['id']} status={rec['actual_status']} match={rec.get('result_match','-')} time={rec['elapsed_seconds']}s",flush=True)
    clear_r=[r for r in records if r['expected_status']=='completed']; amb_r=[r for r in records if r['expected_status']=='waiting_clarification']; triggered=[r for r in records if r['actual_status']=='waiting_clarification']
    by_diff={}
    for d in ('easy','medium','hard'):
        group=[r for r in clear_r if r['difficulty']==d]
        by_diff[d]={'cases':len(group),'execution_success_rate':ratio(sum(r['actual_status']=='completed' for r in group),len(group)),'result_match_rate':ratio(sum(r.get('result_match') is True for r in group),len(group))}
    req=sum(len(r.get('required_fields',[])) for r in clear_r); recalled=sum(len(r.get('recalled_required_fields',[])) for r in clear_r); lats=[r['elapsed_seconds'] for r in records]
    summary={'suite_version':'v2-extended','run_at_utc':datetime.now(timezone.utc).isoformat(),'clear_case_count':len(clear_r),'ambiguous_case_count':len(amb_r),'schema_field_recall':ratio(recalled,req),'schema_fields':f'{recalled}/{req}','complete_schema_recall_rate':ratio(sum(r.get('complete_schema_recall') is True for r in clear_r),len(clear_r)),'sql_execution_success_rate':ratio(sum(r['actual_status']=='completed' for r in clear_r),len(clear_r)),'result_match_rate':ratio(sum(r.get('result_match') is True for r in clear_r),len(clear_r)),'clarification_recall':ratio(sum(r['actual_status']=='waiting_clarification' for r in amb_r),len(amb_r)),'clarification_precision':ratio(sum(r['actual_status']=='waiting_clarification' for r in amb_r),len(triggered)),'false_clarifications_on_clear_cases':sum(r['actual_status']=='waiting_clarification' for r in clear_r),'by_difficulty':by_diff,'latency_seconds':{'mean':round(statistics.mean(lats),3),'p50':percentile(lats,.5),'p95':percentile(lats,.95)}}
    payload={'summary':summary,'records':records}; out=HERE/'results';out.mkdir(exist_ok=True); stamp=datetime.now().strftime('%Y%m%d-%H%M%S'); path=out/f'benchmark-v2-extended-{stamp}.json'; text=json.dumps(payload,ensure_ascii=False,indent=2);path.write_text(text);(out/'extended-latest.json').write_text(text)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True);print(f'result_file={path}',flush=True)

if __name__=='__main__': main()
