# 키워드 분석 요약·메일 운영

## 구현 상태

수집 실행 → 분석 결과 저장 → 요약 생성 → 선택적 메일 발송을 연결했다. 실제 수집 운영 검증은 진행 중이며, OpenAI 키·메일 설정·실행 일정이 제공되지 않아 API 실측, 실제 발송 및 정기 실행 등록은 미완료다.

요약은 원본 POS 전체 대신 코드로 계산한 근거를 사용한다. 기존 분석 3,547건의 요약 입력은 근거 61개, JSON 약 5,400자였다. 이는 토큰 수가 아니며, 토큰과 비용은 API 사용량으로 확인한다. 전국 검색량과 지역 수요를 구분하고 보류 상태를 보존하도록 지시한다. 인용 근거와 수치는 코드 검증을 거치지만 해석·제안의 타당성은 별도 검토한다.

## 모델 선정

GPT-4.1 mini, GPT-5 mini, GPT-5.6 Luna를 동일 입력으로 비교한다. 최신 여부를 선정 기준으로 사용하지 않는다. 구조화 출력과 근거 검증 통과, 보류 상태 보존, 과장 없는 한국어 설명이 필수다. 이 기준을 만족한 모델 사이에서 실제 비용과 지연을 비교한다. 현재 최종 선정 모델은 없다.

가격 출처 및 기준일은 [설계 계획](2026-09-16-delivery-plan.md)에 기록했다. 비교 비용은 캐시 할인을 제외한 보수적 추정이며, 추론 토큰을 출력 토큰에 중복 가산하지 않는다. 실제 청구 금액은 계정의 적용 요율에 따라 확인한다.

```powershell
# 동일한 완료 분석에 대해 모델별 요약·사용량·비용을 기록한다.
.\.venv\Scripts\python.exe -m scripts.menu_keyword_pipeline.delivery_cli --output <분석결과폴더> --compare-models

# 선정 후 명시한 모델로 요약을 생성한다.
.\.venv\Scripts\python.exe -m scripts.menu_keyword_pipeline.delivery_cli --output <분석결과폴더> --model <선정모델>

# 실제 보내기 전 .eml을 작성한다.
.\.venv\Scripts\python.exe -m scripts.menu_keyword_pipeline.delivery_cli --output <분석결과폴더> --preview-mail

# 요약과 상세 보고서를 실제 발송한다.
.\.venv\Scripts\python.exe -m scripts.menu_keyword_pipeline.delivery_cli --output <분석결과폴더> --send-mail

# 정기 실행에 사용할 전체 실행 명령. 일정 등록은 별도로 필요하다.
.\.venv\Scripts\python.exe -m scripts.menu_keyword_pipeline.operations --allow-write --allow-network --send-mail
```

## 환경 설정

프로젝트 `.env` 또는 프로세스 환경변수에 설정한다. 비밀값을 문서·로그·대화에 붙여 넣지 않는다.

- `OPENAI_API_KEY`, `KEYWORD_SUMMARY_MODEL`
- `SMTP_HOST`, `SMTP_PORT`(기본 465), `SMTP_SECURITY`(`ssl` 또는 `starttls`)
- `SMTP_USERNAME`, `SMTP_PASSWORD`
- `MAIL_FROM`, `MAIL_TO`(쉼표 구분 주소)

## 재실행과 상태 확인

- 정상 요약은 입력·모델 해시가 같으면 재사용한다. 마크다운은 검증된 JSON에서 다시 만든다.
- `operations.json`이 `DELIVERY_PENDING`이면 수집을 반복하지 않고 같은 결과의 요약·메일 단계를 재시도한다.
- 수집 실패는 DB에 정상 저장된 자료를 다음 실행에서 재사용한다.
- `operations.lock`은 중복 실행을 차단한다. 비정상 종료로 남으면 해당 실행 프로세스가 종료됐는지 확인한 뒤 수동 해제해야 한다.
- 메일 `ACCEPTED`는 SMTP 수락이며 수신함 도착 확인과 다르다.
- `SENDING`, `UNKNOWN`, `PARTIAL_ACCEPTED`는 자동 재발송하지 않는다. SMTP 로그나 수신함으로 실제 전달 여부를 확인한 후 처리한다. 설정을 바꿔 기존 발송 기록을 자동 덮어쓰지 않는다.
- `mail-preview.eml`, `mail-delivery.json`, `summary-receipt.json`, `delivery-status.json`으로 단계별 결과를 확인한다.
- 메일이 수신함에 도착했는지, 스케줄이 지정 시각에 실제 실행되는지는 아직 검증하지 않았다.

## 검증

2026-09-16 브라우저 버전 조회, 요약·메일·연결 실행 및 메뉴 파이프라인 관련 테스트 49개 통과. 요약 미완료 응답 거부, 근거 불일치 거부, 정상 요약 재사용, 발송 중복 방지, 결과 불명확 시 자동 재전송 방지, 보고 단계 재개 및 동시 실행 방지를 포함한다. 실제 OpenAI 응답의 한국어 품질은 모의 테스트 결과로 대신하지 않는다.

## 운영 검증에서 발견한 오류

1. 통합 워크플로와 배치 수집기가 같은 `rank-plan.json`을 생성하면서 `FileExistsError` 발생. 배치 산출물을 `rank-collection` 하위에 분리하고 실제 배치 어댑터 회귀 테스트로 검증했다.
2. Chrome 버전을 읽는 PowerShell 프로세스가 10초 제한을 초과해 브라우저 생성 실패. 네이버 요청 이전 오류였다. Windows 파일 버전 API로 대체했으며 실제 Chrome 메이저 버전 153을 약 0.015초에 확인했다. 실패 실행을 종료하고 수정본으로 재시작했다.

수정본 실행 폴더: `outputs/menu-keywords-20260916-115834-022633-b670a68b0526431083b19de2c764860c`. 시작 시 필요한 신규 순위 조사 256건. 실행 시작만으로 전체 운영 검증 통과를 주장하지 않는다.
