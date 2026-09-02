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
