"""조회·선별·수집·재검증·결과 저장을 한 번의 실행으로 연결한다."""
import json
from datetime import datetime,timezone
from pathlib import Path
from collections import Counter
from scripts.keyword_evaluation.contracts import digest
from scripts.keyword_evaluation.collection import _reusable_rank
from .core import aggregate,evaluate,changes,rank_input,volume_for,validate_registry


def find_previous(parent):
    candidates=[]
    for folder in Path(parent).iterdir():
        if not folder.is_dir(): continue
        try:
            status=json.loads((folder/'status.json').read_text(encoding='utf-8'))
            if (status.get('pipeline')=='menu-keyword-v1' and status.get('stage')=='DONE'
                    and all((folder/n).is_file() for n in ('results.json','registry.json','quality.json'))):
                candidates.append((status['as_of'],folder.name,folder))
        except (OSError,ValueError,KeyError):
            continue
    return max(candidates,default=(None,None,None))[2]


def write(root,name,data):
    destination=root/name
    temp=destination.with_suffix(destination.suffix+'.tmp')
    content=json.dumps(data,ensure_ascii=False,indent=2,default=str)+'\n'
    # Windows에서 진행 파일을 읽는 순간 교체가 잠시 거부될 수 있다.
    # 영구 권한 오류는 숨기지 않고 제한된 재시도 후 그대로 전달한다.
    import time
    for attempt in range(7):
        try:
            temp.write_text(content,encoding='utf-8')
            temp.replace(destination)
            return
        except PermissionError:
            if attempt==6:raise
            time.sleep(.05*2**attempt)


def execute(registry,root,adapter,*,collect=False,previous=None,clock=lambda:datetime.now(timezone.utc)):
    validate_registry(registry)
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    now=clock();stage='SALES';receipts={}
    write(root,'registry.json',registry)
    write(root,'status.json',dict(status='RUNNING',stage=stage,started_at=now.isoformat()))
    try:
        source=adapter.read_sales(registry,now)
        # 설정 파일 외에 ERP 매핑·대상 식별 변화도 판매 없음으로 오인하지 않는다.
        identity=[{k:t.get(k) for k in ('store_code','place_id','target_store_id','status')} for t in source['inventory']]
        positions=[dict(store_code=t['store_code'],place_id=t['place_id'],target_store_id=t['target_store_id'],
                        latitude=t['search_location']['latitude'],longitude=t['search_location']['longitude']) for t in source['targets']]
        context=[source.get('store_mapping',[]),source.get('menu_mapping',[]),identity,positions]
        source['quality']['source_mapping_hash']=digest([sorted(items,key=lambda r:json.dumps(r,sort_keys=True,default=str)) for items in context])
        write(root,'sales.json',source)
        a=aggregate(source['targets'],source['sales'],registry['candidates'])
        write(root,'sales-pairs.json',a['pairs']);write(root,'unmapped-menus.json',a['unmapped'])
        write(root,'quality.json',source['quality'])
        volumes,ranks=adapter.observations(source['targets'],a['keywords'],registry,clock())
        needed=[q for q in a['keywords'] if volume_for(volumes,q,clock(),registry['volume_ttl_days'])[1] not in ('EXACT','CENSORED','NOT_PROVIDED')]
        write(root,'volume-plan.json',needed)
        stage='VOLUME'
        if collect and needed:
            write(root,'status.json',dict(status='RUNNING',stage=stage))
            receipts['volume']=adapter.collect_volume(needed,registry)
            write(root,'receipts.json',receipts)
            volumes,ranks=adapter.observations(source['targets'],a['keywords'],registry,clock())
        # 정확한 검색량이 없는 후보는 보류하며 0으로 간주하거나 비용 큰 순위 수집을 하지 않는다.
        eligible=[p for p in a['pairs'] if volume_for(volumes,p['query'],clock(),registry['volume_ttl_days'])[1]=='EXACT']
        e=rank_input(source['targets'],eligible,ranks,clock(),registry)
        ts={t['place_id']:t for t in source['targets']}
        pending=[q for q in e['collection_queue'] if not _reusable_rank(e,q,ts[q['target_place_id']])]
        write(root,'rank-plan.json',pending)
        stage='RANK'
        if collect and pending:
            write(root,'status.json',dict(status='RUNNING',stage=stage,planned=len(pending)))
            receipts['rank']=adapter.collect_rank(dict(e,collection_queue=pending),root)
            write(root,'receipts.json',receipts)
            volumes,ranks=adapter.observations(source['targets'],a['keywords'],registry,clock())
        stage='ANALYSIS';as_of=clock()
        rows=evaluate(source['targets'],a['pairs'],volumes,ranks,as_of,registry)
        write(root,'observations.json',dict(volumes=volumes,ranks=ranks))
        write(root,'results.json',rows)
        stores=[dict(store_code=t['store_code'],store_name=t['store_name'],
                     candidates=[r for r in rows if r['store_code']==t['store_code'] and r['decision']=='CANDIDATE'],
                     held=[r for r in rows if r['store_code']==t['store_code'] and r['decision']=='HOLD']) for t in source['targets']]
        write(root,'store-candidates.json',stores)
        comparison=dict(baseline=None,comparable_sales=False,rows=[])
        if previous:
            prev=Path(previous)
            old=json.loads((prev/'results.json').read_text(encoding='utf-8'))
            oldreg=json.loads((prev/'registry.json').read_text(encoding='utf-8'))
            oldquality=json.loads((prev/'quality.json').read_text(encoding='utf-8'))
            same=digest(oldreg)==digest(registry)
            same_source=source['quality']['source_mapping_hash']==oldquality.get('source_mapping_hash')
            comparable=same and same_source and source['quality']['comparable'] and oldquality['comparable']
            comparison=dict(baseline=str(prev.resolve()),same_registry=same,same_source_mapping=same_source,comparable_sales=comparable,
                            note='기간은 매번 최근 30일이며 서로 겹칠 수 있습니다. 매핑 변경·관측 공백이 있으면 매출 증감을 보류합니다.',
                            rows=changes(rows,old,comparable_sales=comparable) if same and same_source else [],
                            status='REGISTRY_CHANGED' if not same else 'SOURCE_MAPPING_CHANGED' if not same_source else 'COMPARED')
        write(root,'changes.json',comparison)
        held=sum(r['decision']=='HOLD' for r in rows)
        receipt=receipts.get('rank',{})
        partial=bool(held or source['blocked_stores'] or not source['quality']['comparable'] or
                     any(t['status']!='ELIGIBLE' for t in source['inventory']) or receipt.get('aborted') or receipt.get('persistence_failures'))
        status=dict(pipeline='menu-keyword-v1',status='PARTIAL' if partial else 'COMPLETE',stage='DONE',as_of=as_of.isoformat(),
                    collected=collect,pair_count=len(rows),candidate_count=sum(r['decision']=='CANDIDATE' for r in rows),
                    held_count=held,unmapped_menu_count=len(a['unmapped']),receipts=receipts)
        report(root,status,source,stores,comparison)
        write(root,'status.json',status)
        return status
    except Exception as exc:
        # DB 비밀번호나 요청 URL이 포함될 수 있는 예외 원문은 기록하지 않는다.
        status=dict(status='FAILED',stage=stage,error_type=type(exc).__name__,
                    message='단계 실행 실패. 저장된 원자료와 계획을 확인한 뒤 새 출력 경로에서 재실행하세요.',receipts=receipts)
        write(root,'status.json',status)
        return status


def report(root,status,source,stores,comparison):
    def safe(v): return str(v).replace('|','／').replace('\n',' ')
    q=source['quality']
    lines=['# 매장별 신규 검색 유입 후보', '',f"상태: {status['status']} / 기준 시각(UTC): {status['as_of']}",
           f"매출 기간: {q['start']} 이상 ~ {q['end']} 미만 (한국 시간, 당일 제외)",
           f"관측 조합 {status['pair_count']}건 / 후보 {status['candidate_count']}건 / 보류 {status['held_count']}건 / 미연결 메뉴 기록 {status['unmapped_menu_count']}건",'',
           '전국 검색량은 지역 수요·방문자 수가 아닙니다. 미노출은 유효한 매장 좌표 검색에서 상위 20위에 없다는 뜻입니다. 메뉴군 간 판매·검색량 중복 합산에 주의하세요.',
           '연결된 메뉴의 기간 판매 근거이며 현재 판매 여부를 보증하지 않습니다. 보류에는 수집 실패·기간 경과·검색량 구간값·미제공이 포함됩니다.',
           f"POS 품질: {q['status']} — {q.get('note','')}",
           f"매출 증감 비교 가능: {comparison['comparable_sales']}",'',
           '| 매장 | 키워드 | 전국 검색량 | 기간 매출 | 판매수 |','|---|---|---:|---:|---:|']
    for store in stores:
        for r in store['candidates']:
            lines.append('| '+' | '.join(safe(x) for x in (store['store_code']+' '+store['store_name'],r['query'],r['volume'],r['amount'],r['qty']))+' |')
    lines += ['', '## 이전 실행 대비 변화','',str(dict(Counter(r['change'] for r in comparison['rows']))), '',
              '상세: store-candidates.json / results.json / changes.json / quality.json / unmapped-menus.json / sales.json']
    (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
