# 매장별 키워드 검색량 산출

표준 엑셀에 매장별 키워드를 입력하면 네이버 검색광고 API와 DataLab을 이용해 최근 30일 일간 검색량을 추정합니다.

## 사용 방법

1. `templates/keyword_input_template.xlsx`를 복사합니다.
2. 복사본을 `inputs/keyword_input.xlsx`로 저장합니다.
3. `키워드입력` 시트의 예시 행을 삭제하고 매장명과 `키워드1~5`를 입력합니다.
4. 프로젝트 루트에서 `.\run_keyword_volume.ps1`을 실행합니다.
5. 콘솔에 표시된 `outputs/YYYYMMDD_HHMMSS` 폴더에서 결과를 확인합니다.

매장별 키워드는 최대 5개입니다. 같은 매장 안의 중복 키워드는 최초 슬롯만 유지됩니다. `키워드6` 이상은 DataLab 비교를 위해 앵커 키워드 기반 별도 모델이 필요하므로 입력 단계에서 중단됩니다.

## 환경 설정

프로젝트 루트의 `.env`에 다음 이름의 설정이 필요합니다. 실제 값은 Git에 커밋하지 않습니다.

- `NAVER_SEARCHAD_CUSTOMER_ID`
- `NAVER_SEARCHAD_API_KEY`
- `NAVER_SEARCHAD_SECRET_KEY`
- `NAVER_DATALAB_CLIENT_ID`
- `NAVER_DATALAB_CLIENT_SECRET`

## 입력 오류

- 파일 없음: `inputs/keyword_input.xlsx` 위치와 파일명을 확인합니다.
- 시트 없음: 시트명을 정확히 `키워드입력`으로 지정합니다.
- 중복 매장: 같은 매장명이 여러 행에 있는지 확인합니다.
- 키워드 없음: 각 매장에 키워드를 하나 이상 입력합니다.
- 예시 행: `예시 매장명` 행을 삭제합니다.
- 키워드6 이상: 키워드를 5개 이하로 줄이거나 앵커 기반 별도 모델을 사용합니다.

입력 검증이 실패하면 네이버 API는 호출되지 않습니다.

## 키워드 발견 순위 수집 파일럿

네이버 장소 검색 결과를 키워드·매장별로 수집하는 별도 수집기는
[`docs/keyword-discovery-rank-pilot-runbook.md`](docs/keyword-discovery-rank-pilot-runbook.md)의
통제된 파일럿 절차를 따라 실행합니다. 먼저 `--dry-run`으로 입력 파일을 검증하고,
라이브 수집·DB 저장은 해당 문서의 롤백 단계와 수동 검토를 마친 뒤에만 진행합니다.

입력 파일은 `검색작업` 시트와 별도의 `자사매장` 시트를 모두 사용합니다.
`자사매장`에는 매장 ID·공식 매장명·네이버 플레이스 ID·선택적 수동 매핑
플레이스 ID를 기록하며, 모든 검색 작업의 기준 매장 ID가 이 시트에 있어야 합니다.
`검색작업`의 위도·경도는 둘 다 입력하거나 둘 다 비워 둡니다. 둘 다 비어 있으면
`자사매장`의 네이버 플레이스 ID로 페이지의 매장 객체 또는 길찾기 URL에서 좌표를
확인하고 `dbo.naver_place_location`에 저장해 다음 실행에서 재사용합니다. 사진 URL의
좌표는 판정 근거로 사용하지 않습니다.
현재 릴리스의 CLI는 안전상 `--source excel`만 실행하며 `--source database`는
DB나 브라우저를 만들기 전에 종료합니다. `DatabaseTaskSource`는 향후 전용 읽기
계정이 준비될 때를 위한 인터페이스로만 유지됩니다.

실행 모드는 Chrome 생성 전에 `naverDB` 대상과 순위 수집 테이블의 정확한 컬럼
구조를 확인하며, 자동 좌표가 필요하면 좌표 캐시 테이블도 확인합니다. 첫 검색
직전에는 `run_id`를 출력하고 즉시
flush합니다. `--rollback-test`는 DB 커밋을 롤백하는 동시에 각 작업 디렉터리에
최종 `page.html`, `screenshot.png`, `snapshot-results.json`을 남겨 카드 단위
수동 검토가 가능하게 합니다. 재시도 진단과 구조화 산출물의 구성값 비밀은
`[REDACTED]`로 치환됩니다.
