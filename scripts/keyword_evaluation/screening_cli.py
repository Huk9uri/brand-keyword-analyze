"""후보 선별 → 검색량 → 매장 좌표 순위를 단계별 영수증과 함께 실행한다."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .cli import _connection, _load, _write
from .contracts import digest
from .pipeline import validate_bundle
from .screening import screen_bundle, collection_plan, rank_input, exposure_rows


def write_report(root, data, screened):
    _write(root/'input.json', data)
    _write(root/'screening.json', screened)
    _write(root/'collection-plan.json', collection_plan(data, screened))
    observations = exposure_rows(data, screened)
    _write(root/'exposure.json', observations)
    names = {'PRIORITY':'우선 수집','HOLD':'보류','EXCLUDED':'제외'}
    lines = ['# 매장별 후보 선별 및 노출 확인', '',
             f"기준 시각: {data['as_of_at']}", '',
             '원본 후보는 보존한다. 아래 분류는 수집 적합성이며 최종 추천 판정이 아니다.',
             '검색량 부족·미제공·자사 미노출은 자동 제외 사유가 아니다. 보류는 정보 부족을 뜻한다.', '',
             '| 매장 | 우선 수집 | 보류 | 제외 |', '|---|---:|---:|---:|']
    for target in data['targets']:
        counts = Counter(r['status'] for r in screened['rows'] if r['place_id'] == target['place_id'])
        lines.append(f"| {target['store_name']} | {counts['PRIORITY']} | {counts['HOLD']} | {counts['EXCLUDED']} |")
    lines.extend(['', '## 우선 후보 관측값', '', '| 매장 | 검색어 | 검색량 | 순위 상태 | 자사 순위 | 경쟁점 수 |', '|---|---|---|---|---|---|'])
    for r in observations:
        lines.append(f"| {r['store_name']} | {r['query']} | {r['total_count'] if r['volume_status']=='EXACT' else r['volume_status']} | {r['rank_status']} | {r['own_organic_rank'] or r['visibility']} | {r['competitor_count'] if r['competitor_count'] is not None else '미확인'} |")
    lines.extend(['', '## 후보별 분류와 근거', '', '| 매장 | 검색어 | 분류 | 이유 |', '|---|---|---|---|'])
    for r in screened['rows']:
        lines.append(f"| {r['store_name']} | {r['query'].replace('|','／')} | {names[r['status']]} | {r['reason']} |")
    (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--source-config',type=Path)
    source.add_argument('--input',type=Path,help='오프라인 선별용 동결 입력')
    parser.add_argument('--policy',type=Path,default=Path('inputs/keyword_screening_policy.json'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--env-file',type=Path,default=Path('.env'))
    parser.add_argument('--collect',action='store_true')
    parser.add_argument('--allow-write',action='store_true')
    parser.add_argument('--allow-network',action='store_true')
    args = parser.parse_args(argv)
    if args.collect and not (args.allow_write and args.allow_network):
        raise ValueError('수집에는 --allow-write --allow-network가 필요합니다')
    if args.collect and args.source_config is None:
        raise ValueError('실제 수집에는 --source-config가 필요합니다')
    if args.output.exists():
        raise ValueError('새 출력 경로를 지정하세요. 재개는 이전 source-config.json을 입력으로 새 출력 경로를 사용합니다.')
    config = _load(args.source_config) if args.source_config else {'bundle':_load(args.input)}
    policy = _load(args.policy)
    root = args.output
    root.mkdir(parents=True)
    connection = None
    def refresh(stage):
        config['bundle']['as_of_at'] = datetime.now(timezone.utc).isoformat()
        from .source_export import export_bundle
        data = export_bundle(connection, config)
        validate_bundle(data)
        screened = screen_bundle(data,policy)
        folder = root/stage
        folder.mkdir()
        write_report(folder,data,screened)
        _write(folder/'source-config.json',config)
        print(stage, screened['counts'], collection_plan(data,screened)['volume_keywords'],flush=True)
        return data, screened
    try:
        if not args.collect:
            data = config['bundle']
            validate_bundle(data)
            write_report(root,data,screen_bundle(data,policy))
            return 0
        connection = _connection(args.env_file)
        data, screened = refresh('01-screened')
        keywords = collection_plan(data,screened)['volume_keywords']
        if keywords:
            from dotenv import dotenv_values
            from scripts.yuksudang_volume.config import NaverConfig
            from scripts.yuksudang_volume.searchad import SearchAdClient
            from .collection import collect_volumes
            from .repository import VolumeRepository
            env = dotenv_values(args.env_file)
            client = SearchAdClient(NaverConfig(env['NAVER_SEARCHAD_CUSTOMER_ID'],env['NAVER_SEARCHAD_API_KEY'],
                                               env['NAVER_SEARCHAD_SECRET_KEY'],'',''))
            periods = [v for v in data['volumes'] if v.get('period_verified') and v.get('period_type')=='PROVIDER_MONTHLY']
            if not periods:
                raise ValueError('검증된 검색광고 기간 정의가 필요합니다')
            period = {k:periods[-1][k] for k in ('period_type','period_definition','period_start','period_end','period_verified') if k in periods[-1]}
            observations = collect_volumes(keywords,client._request,period)
            _write(root/'volume-observations.json',observations)
            _write(root/'volume-receipt.json',VolumeRepository(connection).save(observations))
        data, screened = refresh('02-volume')
        from .collection import build_rank_tasks, collect_ranks
        from scripts.keyword_discovery_rank.config import CollectorConfig
        evaluated = rank_input(data,screened)
        tasks = build_rank_tasks(evaluated)
        _write(root/'rank-plan.json',[dict(query=t.query,target_store_id=t.target_store_id) for t in tasks])
        print('신규 순위 수집',len(tasks),'건',flush=True)
        if tasks:
            receipt = collect_ranks(evaluated,connection,CollectorConfig.from_env(args.env_file.resolve().parent),root/'rank-artifacts')
            _write(root/'rank-receipt.json',receipt)
            config['rank_runs'].append(receipt)
            _write(root/'source-config.json',config)
            print('순위 영수증',receipt['statuses'],'중단',receipt['aborted'],flush=True)
        data, screened = refresh('03-final')
        _write(root/'verification.json',dict(input_hash=digest(data),candidate_count=len(data['candidates']),
                screened_count=len(screened['rows']),unique_queries=len({r['query'] for r in screened['rows']}),
                counts=screened['counts'],rank_statuses=dict(Counter(r['rank_status'] for r in exposure_rows(data,screened))),
                remaining_rank_tasks=len(build_rank_tasks(rank_input(data,screened))),
                remaining_volume_keywords=collection_plan(data,screened)['volume_keywords']))
        return 0
    finally:
        if connection is not None:
            connection.close()


if __name__ == '__main__':
    raise SystemExit(main())
