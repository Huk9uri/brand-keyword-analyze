# Brand Keyword Analyze

브랜드와 매장의 네이버 검색 키워드를 수집하고 분석하는 Python 도구입니다. 검색 수요, 장소 검색 결과 노출 순위, 리뷰 기반 키워드 후보를 분석해 매장별 로컬 SEO 운영에 필요한 자료를 만듭니다.

엑셀 기반 검색량 산출기와 SQL Server 기반 수집·분석 모듈로 구성되어 있습니다. 내부 운영 환경을 바탕으로 개발되었으며, 일부 기능에는 전용 DB 스키마와 Codex 번들 런타임이 필요합니다.

## 주요 기능

| 기능 | 데이터 소스 | 결과 | 실행 조건 |
| --- | --- | --- | --- |
| 일간 검색량 추정 | 키워드 엑셀, 검색광고 API, DataLab | 매장·키워드별 요약 및 일간 추정량 엑셀·JSON | 네이버 API 인증, Codex Node.js 런타임 |
| 장소 검색 순위 수집 | 검색 작업·자사 매장 엑셀, 장소 검색 결과 | 매장 매칭 및 검색 순위 스냅샷 | Chrome, SQL Server, 전용 테이블 |
| 키워드 후보 발굴 | 최근 12개월 리뷰, 메뉴, 운영 키워드, 선택적 검색광고 연관어 | 매장별 후보 및 브랜드 공통 후보 | SQL Server의 리뷰 및 후보 테이블 |
| 플레이스 대표키워드 수집 | 순위 수집 결과의 Place ID | 대표키워드 스냅샷 및 변경 이력 | Chrome, SQL Server, 전용 테이블 |

각 모듈은 별도로 실행합니다. 아래 빠른 시작은 **엑셀 기반 일간 검색량 추정**을 기준으로 합니다.

## 입력과 결과 예시

`templates/keyword_input_template.xlsx`의 `키워드입력` 시트에 매장명과 최대 5개의 키워드를 입력합니다. 다음은 형식을 보여주는 가상 데이터입니다.

| 매장명 | 키워드1 | 키워드2 | 키워드3 | 키워드4 | 키워드5 |
| --- | --- | --- | --- | --- | --- |
| 데모 강남점 | 강남 국밥 | 강남 점심 | 강남 혼밥 | | |
| 데모 성수점 | 성수 국밥 | 성수 점심 | | | |

```text
매장별 키워드 엑셀
  → 입력 검증 및 중복 키워드 정리
  → 검색광고 API의 월간 PC·모바일 검색량 조회
  → DataLab의 최근 30일 일별 검색 추이 조회
  → 일별 비율에 따른 검색량 배분
  → 결과 엑셀, JSON, 미리보기 저장
```

정상 실행 결과는 실행마다 생성되는 `outputs/YYYYMMDD_HHMMSS/`에 저장됩니다.

```text
outputs/YYYYMMDD_HHMMSS/
├── input_keywords.json
├── daily_volume_results.json
├── 매장별_키워드_30일_일간검색량_YYYY-MM-DD.xlsx
└── previews/
```

결과에는 월간 검색량, 일간 추정량, 일평균, 최대 추정일과 처리 상태 등이 포함됩니다. 입력 검증만 실행하면 `input_keywords.json`만 생성됩니다.

## 빠른 시작

### 1. 실행 환경 준비

Windows PowerShell 및 Python 3.10 이상을 기준으로 안내합니다. 검색량 산출기의 엑셀 입출력에는 Node.js와 `@oai/artifact-tool`이 필요합니다.

현재 `scripts/run_keyword_volume.py`는 다음 Codex 번들 Node.js 경로를 사용합니다.

```text
~/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe
```

해당 실행 파일이 있고 Node.js에서 `@oai/artifact-tool`을 불러올 수 있어야 합니다. 일반 Node.js 설치만으로 이 조건이 충족되지는 않습니다. Codex 번들 런타임이 없는 환경에서는 실행 경로와 엑셀 라이브러리 의존성을 먼저 조정해야 합니다.

저장소를 내려받은 뒤 프로젝트 루트에서 실행합니다.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-keyword-discovery.txt
Copy-Item .env.example .env
```

현재 의존성 파일은 수집·분석 모듈에서 사용하는 Python 패키지를 함께 포함합니다.

### 2. 네이버 API 인증 설정

`.env`에 다음 값을 입력합니다. 검색량 산출에는 DB 연결 설정이 필요하지 않습니다.

| 환경 변수 | 용도 |
| --- | --- |
| `NAVER_SEARCHAD_CUSTOMER_ID` | 검색광고 고객 ID |
| `NAVER_SEARCHAD_API_KEY` | 검색광고 API 키 |
| `NAVER_SEARCHAD_SECRET_KEY` | 검색광고 서명용 비밀 키 |
| `NAVER_DATALAB_CLIENT_ID` | DataLab 클라이언트 ID |
| `NAVER_DATALAB_CLIENT_SECRET` | DataLab 클라이언트 시크릿 |

실제 인증 정보는 `.env`에만 저장합니다. `.env`와 `outputs/`는 `.gitignore`에 등록되어 있습니다.

### 3. 입력 엑셀 작성

```powershell
Copy-Item templates/keyword_input_template.xlsx inputs/keyword_input.xlsx
```

복사한 파일에서 `키워드입력` 시트의 예시 행을 삭제하고 매장별 키워드를 입력합니다.

- 매장명은 중복될 수 없으며, 매장마다 키워드가 하나 이상 필요합니다.
- 같은 매장 안에서 공백·대소문자를 정규화한 뒤 중복되는 키워드는 최초 슬롯만 유지합니다.
- 매장당 최대 5개까지 지원합니다. `키워드6` 이상 헤더가 있으면 검증에 실패합니다.
- `예시 매장명` 또는 `예시:`로 시작하는 매장명은 예시 행으로 판정합니다.

### 4. 입력 검증 및 실행

먼저 입력만 검증합니다.

```powershell
.\run_keyword_volume.ps1 -DryRun
```

매장 수, 키워드 수, 분석 기간과 출력 폴더를 확인합니다. 이 단계는 네이버 API를 호출하지 않으며 API 인증 정보도 읽지 않습니다. 엑셀을 읽는 Node.js 런타임은 필요합니다.

검증이 통과하면 검색량을 산출합니다.

```powershell
.\run_keyword_volume.ps1
```

기본 기간은 실행일을 포함한 최근 30일입니다. 콘솔의 `output_dir`와 `result_xlsx`에서 저장 위치를 확인합니다. Python CLI로 종료일이나 매장을 지정할 수도 있습니다.

```powershell
.\.venv\Scripts\python.exe scripts/run_keyword_volume.py --end-date 2026-10-24
.\.venv\Scripts\python.exe scripts/run_keyword_volume.py --store "데모 강남점"
```

`--end-date`는 DataLab 조회 기간의 종료일을 지정합니다. 검색광고 API에서 과거 시점의 월간 검색량을 복원하는 옵션은 아닙니다.

## 검색량 추정 방식과 해석

일간 검색량은 네이버가 제공하는 일별 실측 검색 건수가 아니라, 월간 검색량을 일별 추이로 배분한 **추정값**입니다.

```text
일간 추정량 = 월간 검색량 × 해당 날짜의 DataLab 비율 / 조회 기간의 DataLab 비율 합계
```

PC와 모바일 검색량에 각각 같은 일별 가중치를 적용합니다. 정수 배분 시 먼저 소수점을 버린 뒤 나머지가 큰 날짜부터 1씩 배분해, 각 기기별 일간 추정량 합계가 입력 월간 검색량과 일치하도록 합니다.

예를 들어 월간 검색량이 300이고 30일의 DataLab 비율이 모두 같으면 하루 추정량은 10입니다. 실제 일별 검색 건수나 특정 매장의 방문·클릭 수를 의미하지 않습니다.

- 검색광고 월간 수치와 DataLab 조회 기간이 같은 모집단·기간을 나타낸다고 보장하지 않습니다.
- `< 10`처럼 정확한 정수가 아닌 검색량은 임의의 숫자로 대체하지 않고 상태로 구분합니다.
- DataLab 비율 합계가 0이면 일별 배분을 수행할 수 없습니다.
- 5개 초과 키워드 비교를 위한 앵커 키워드 모델은 현재 입력 경로에서 지원하지 않습니다.

## 다른 수집·분석 모듈

DB가 필요한 기능은 연결 정보와 테이블을 준비한 뒤 해당 런북에 따라 실행합니다. 기능마다 dry-run이 검증하는 범위가 다르므로 각 문서의 설명을 확인하세요.

| 문서 | 내용 |
| --- | --- |
| [장소 검색 순위 수집 런북](docs/keyword-discovery-rank-pilot-runbook.md) | 입력 검증, DB 스키마 확인, 파일럿 수집 및 롤백 검증 |
| [키워드 후보 발굴 런북](docs/keyword-candidate-discovery-runbook.md) | 리뷰 기반 후보 추출, 외부 후보 통합, dry-run 및 적재 |
| [플레이스 대표키워드 수집 런북](docs/place-keyword-collector-runbook.md) | 대표키워드 수집, 스냅샷 및 변경 이력 관리 |

장소 검색 순위 수집기는 현재 `--source excel`만 실행합니다. `--source database`는 DB 연결이나 브라우저 생성 전에 종료하며, `DatabaseTaskSource`는 향후 연동을 위한 인터페이스로 유지됩니다.

순위 수집 입력은 `검색작업`과 `자사매장` 시트를 모두 사용합니다. 모든 검색 작업의 기준 매장 ID가 `자사매장`에 있어야 합니다. 위도·경도는 둘 다 입력하거나 둘 다 비워야 하며, 자동 좌표 확인 결과는 `dbo.naver_place_location`에 캐시합니다. 사진 URL의 좌표는 판정 근거로 사용하지 않습니다.

실행 모드는 Chrome 생성 전에 대상 DB와 테이블 구조를 확인합니다. `--rollback-test`는 DB 커밋을 롤백하고 작업별 최종 `page.html`, `screenshot.png`, `snapshot-results.json`을 남깁니다. 자세한 수집 절차와 수동 검토 기준은 순위 수집 런북을 참고하세요.

## 문제 해결

| 증상 | 확인할 내용 |
| --- | --- |
| 가상환경을 찾을 수 없음 | 프로젝트 루트의 `.venv/Scripts/python.exe` 생성 여부 |
| Node.js 파일 또는 패키지를 찾을 수 없음 | Codex 번들 경로 및 `@oai/artifact-tool` 로딩 가능 여부 |
| 입력 파일을 찾을 수 없음 | `inputs/keyword_input.xlsx` 위치와 파일명 |
| 시트 또는 헤더 오류 | `키워드입력` 시트, `매장명` 및 `키워드1` 헤더 |
| 중복 매장·빈 키워드·예시 행 오류 | 매장명 중복, 키워드 누락, 예시 행 삭제 여부 |
| 키워드6 이상 오류 | 5개 초과 키워드 헤더 제거 |
| 인증 설정 누락 | `.env`에 네이버 API 설정 5개가 모두 있는지 확인 |

입력 검증이 실패하면 네이버 API는 호출되지 않습니다.

## 프로젝트 구조와 개발

```text
scripts/
├── run_keyword_volume.py          # 엑셀 기반 검색량 실행 진입점
├── yuksudang_volume/              # 검색광고·DataLab 연동 및 추정 로직
├── keyword_discovery_rank/        # 장소 검색 순위 수집
├── keyword_candidate_discovery/   # 키워드 후보 발굴
├── place_keyword_collector/       # 플레이스 대표키워드 수집
└── node/                         # 엑셀 입출력 및 미리보기
 templates/                       # 입력 엑셀 템플릿
 inputs/                          # 입력 예제 및 로컬 작업 파일
 sql/                             # 테이블 정의 및 분석 SQL
 tests/                           # 단위 테스트 및 통합 테스트
 docs/                            # 기능별 설계·운영 문서
```

검색량 추정 핵심 로직 테스트 예시:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_yuksudang_volume_estimation.py -q
```

일부 CLI·엑셀 통합 테스트는 Windows 가상환경과 Codex Node.js 런타임을 전제로 합니다. 테스트별 실행 환경을 확인한 뒤 전체 테스트를 실행하세요.
