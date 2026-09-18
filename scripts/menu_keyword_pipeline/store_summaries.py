"""추천 가능 매장을 순회하고 검증된 매장별 요약을 통합한다."""
import hashlib
import json
from pathlib import Path
from .summary import generate
from .recommendation import eligible
from .workflow import write
from .summary_db import SummaryDB
from .overview import generate as generate_overview

MODEL='gpt-5.6-luna'


def run(root,key,*,model=MODEL,generate_store=generate,overview=None,workers=1):
    root=Path(root)
    status=json.loads((root/'status.json').read_text(encoding='utf-8'))
    if status.get('stage')!='DONE' or status.get('status') not in ('COMPLETE','PARTIAL'):
        raise ValueError('ANALYSIS_NOT_FINISHED')
    rows=json.loads((root/'results.json').read_text(encoding='utf-8'))
    names={r['store_code']:r['store_name'] for r in rows}
    selected=sorted({r['store_code'] for r in rows if eligible(r)})
    if selected and not key:raise ValueError('OPENAI_API_KEY_REQUIRED')
    lock=root/'store-summaries.lock'
    try:
        with lock.open('x',encoding='utf-8') as f:f.write('매장별 요약 실행 중')
    except FileExistsError:raise ValueError('STORE_SUMMARIES_LOCKED') from None
    db=None;executor=None
    try:
        db=SummaryDB(root)
        records=[];sections=[]
        def checkpoint(state):
            result=dict(status=state,model=model,target_count=len(selected),
                        completed_count=sum(r['status']=='VALIDATED' for r in records),
                        failed_count=sum(r['status']=='FAILED' for r in records),
                        skipped_stores=sorted(set(names)-set(selected)),stores=records)
            result.update(db_path=str(db.path),run_id=db.run_id)
            write(root,'store-summary-status.json',result)
            db.state(state,result)
            return result
        checkpoint('RUNNING')
        # 과거 통합본을 현재 실행의 완료 결과로 오인하지 않도록 표시한다.
        (root/'summary.md').write_text('# 매장별 요약 생성 중\n',encoding='utf-8')
        def produce(code):
            try:return generate_store(root,model,key,store_code=code),None
            except Exception as exc:return None,exc
        from concurrent.futures import ThreadPoolExecutor
        executor=ThreadPoolExecutor(max_workers=workers)
        pending={code:executor.submit(produce,code) for code in selected}
        for code in selected:
            folder=root/'store-summaries'/hashlib.sha256(code.encode()).hexdigest()[:16]
            try:
                receipt,error=pending[code].result()
                if error:raise error
                if receipt.get('status')!='VALIDATED':raise ValueError('SUMMARY_NOT_VALIDATED')
                body=(folder/'summary.md').read_text(encoding='utf-8')
                db.save_store(code,folder,receipt)
                db.event(code,'VALIDATED',receipt)
                records.append(dict(store_code=code,store_name=names[code],status='VALIDATED',
                                    summary=str(folder/'summary.md'),receipt=receipt))
                sections.append(body)
            except Exception as exc:
                # 외부 응답 본문·인증값은 오류 기록에 넣지 않는다.
                records.append(dict(store_code=code,store_name=names[code],status='FAILED',error_type=type(exc).__name__))
                db.event(code,'FAILED',dict(error_type=type(exc).__name__))
            checkpoint('RUNNING')
        executor.shutdown(wait=True)
        failed=any(r['status']=='FAILED' for r in records)
        heading='# 매장별 키워드 추천 요약\n\n'
        heading+=f'대상 {len(selected)}개 · 정상 {len(sections)}개 · 실패 {len(selected)-len(sections)}개\n\n'
        if failed:heading+='일부 매장 생성 실패로 발송을 보류합니다. 재실행하면 정상 요약을 재사용합니다.\n\n'
        if not selected:heading+='현재 추천 가능한 매장이 없습니다.\n\n'
        (root/'summary.md').write_text(heading+'\n\n---\n\n'.join(sections),encoding='utf-8')
        (root/'store-reports.md').write_text(heading+'\n\n---\n\n'.join(sections),encoding='utf-8')
        if not failed and selected and overview is not None:
            checkpoint('OVERVIEW_RUNNING')
            try:overview(root,db,key,model=model)
            except Exception as exc:
                db.event(None,'OVERVIEW_FAILED',dict(error_type=type(exc).__name__))
                checkpoint('OVERVIEW_FAILED')
                raise
        return checkpoint('PARTIAL' if failed else 'VALIDATED')
    finally:
        if executor:executor.shutdown(wait=True,cancel_futures=True)
        if db:db.close()
        lock.unlink(missing_ok=True)
