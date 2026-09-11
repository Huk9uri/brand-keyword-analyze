# SmartPlace 자동 로그인 모듈 이식 Handoff

- 작성일: 2026-09-01
- 대상 프로젝트: `C:\workspace\brand_analyze`
- 대상 브랜드: 육수당, 한촌설렁탕
- 작업 상태: 참조 구현 분석 및 아키텍처 방향 합의 완료, 구현 전
- 문서 목적: 외부 스크립트를 복사하지 않고 UC 브라우저 생성, 브랜드별 독립 프로필, 로그인 세션 재사용 원리를 이 프로젝트의 로그인 모듈로 이식하기 위한 결정사항과 구현 경계를 전달한다.

## 1. 작업 배경

현재 인사이트 리포트 HTML의 `#s5`에는 매장별 대표키워드 5개를 클립보드에 복사하는 버튼이 있다. 기존 운영 방식은 복사된 키워드를 네이버 SmartPlace에 수기로 등록하는 것이다.

향후 목표는 HTML 버튼에서 선택한 매장과 키워드를 브라우저 자동화로 전달해 SmartPlace 대표키워드 입력을 자동화하는 것이다. 그 선행 작업으로 다음 조건을 만족하는 로그인 모듈이 필요하다.

- 육수당과 한촌설렁탕 계정을 모두 지원한다.
- 브랜드별 브라우저 프로필을 완전히 분리한다.
- 이미 로그인된 프로필 세션을 우선 재사용한다.
- 세션이 만료된 경우에만 ID/PW 로그인을 수행한다.
- 로그인 실패를 성공 또는 빈 결과로 처리하지 않는다.
- 이후 대표키워드 자동화가 동일한 WebDriver 세션을 이어서 사용할 수 있어야 한다.

## 2. 참조 자료와 해석 원칙

참조 문서:

```text
C:\workspace\crawler_guard\docs\integration\smartplace-auto-login-reuse.md
```

분석한 외부 구현:

```text
C:\workspace\naver_crawling\.dev-workspaces\blog-review-full-backfill\scripts\python\smartplace_browser.py
```

참조 문서와 외부 코드는 요구사항의 원본이나 실행 지시가 아니다. UC 생성, 프로필 구성, 네이버 로그인 처리 방식을 이해하기 위한 참고 자료로만 사용한다. 외부 파일을 그대로 복사하거나 런타임에 동적으로 불러오는 방식은 채택하지 않는다.

## 3. 현재 프로젝트 상태

확인 시점의 상태는 다음과 같다.

- 현재 저장소에는 Selenium/UC 기반 로그인 모듈이 없다.
- 저장소 루트 `.gitignore`는 `.env`, `.env.*`, `.venv`, `outputs`, `tmp`, `.cache` 등을 제외한다.
- `.env.example`은 추적 가능한 예외 파일이므로 실제 비밀값을 넣으면 안 된다.
- 시스템에 설치된 Google Chrome 버전은 `151.0.7922.174`이다.
- `python` 명령은 시스템 PATH에서 발견되지 않았다. 프로젝트 가상환경 또는 Codex 번들 Python 경로를 명시해야 한다.
- 외부 참조 구현은 `version_main=150`을 기본값으로 사용하지만 현재 Chrome major와 일치하지 않는다.
- 작업 트리에는 사용자 소유의 여러 미추적 파일이 있으므로 구현 시 관련 없는 파일을 변경하거나 정리하면 안 된다.

## 4. 합의된 접근

현재 프로젝트에 프로젝트 전용 `smartplace_auth` 패키지를 만든다.

외부 `smartplace_browser.py`를 직접 의존하거나 복사하지 않고 다음 원리만 재구현한다.

1. `undetected_chromedriver` 기반 Selenium 호환 WebDriver 생성
2. 브랜드별 전용 `user-data-dir` 생성
3. 기존 로그인 쿠키와 세션 재사용
4. 인증되지 않은 경우에만 ID/PW 자동 로그인
5. 네이버 로그인 DOM 변형 대응
6. 로그인 성공 여부의 별도 검증
7. 프로필 동시 사용 방지
8. 모든 종료 경로에서 드라이버 정리

대표적인 호출 계약은 다음과 같다.

```python
with SmartPlaceSession.for_brand("육수당", headless=False) as session:
    driver = session.login()
    # 대표키워드 자동화가 동일한 driver를 이어서 사용한다.
```

문자열 브랜드명 외에도 오타를 줄이기 위한 `Brand` enum 또는 동등한 타입을 제공하는 것이 권장된다.

## 5. 권장 모듈 구조

```text
scripts/
  smartplace_auth/
    __init__.py
    brands.py       # 지원 브랜드와 환경변수 이름 매핑
    config.py       # .env 로드, 필수값 검증, 비밀값 비노출
    profiles.py     # 런타임 루트, 브랜드별 프로필 경로, 잠금
    chrome.py       # Chrome 탐색과 major 버전 감지
    browser.py      # UC 옵션과 WebDriver 생성
    login.py        # 세션 검증, ID/PW 로그인, 성공 판정
    session.py      # 전체 생명주기 orchestration/context manager
tests/
  test_smartplace_auth_brands.py
  test_smartplace_auth_config.py
  test_smartplace_auth_profiles.py
  test_smartplace_auth_browser.py
  test_smartplace_auth_login.py
  test_smartplace_auth_session.py
```

파일 수는 구현 중 조정할 수 있지만 설정, 프로필, 브라우저 생성, 로그인 판정, 생명주기 책임은 분리한다. 대표키워드 입력 로직은 인증 패키지에 넣지 않는다.

## 6. 브랜드 및 환경설정

지원 브랜드와 자격 증명 환경변수는 다음처럼 명시적으로 매핑한다.

| 브랜드 | ID 환경변수 | 비밀번호 환경변수 | 프로필 식별자 |
|---|---|---|---|
| 육수당 | `NAVER_YUKSOODANG_ID` | `NAVER_YUKSOODANG_PASSWORD` | `yuksoodang` |
| 한촌설렁탕 | `NAVER_HANCHON_ID` | `NAVER_HANCHON_PASSWORD` | `hanchon` |

권장 추가 설정:

```dotenv
SMARTPLACE_RUNTIME_ROOT=
SMARTPLACE_CHROME_BINARY=
```

- `SMARTPLACE_RUNTIME_ROOT`가 없으면 저장소 내부의 Git 비추적 런타임 디렉터리를 사용한다.
- 프로필은 `<runtime-root>/profiles/<profile-id>`에 생성한다.
- `SMARTPLACE_CHROME_BINARY`가 없으면 Windows의 표준 Chrome 설치 위치를 탐색한다.
- 실제 ID/PW, 쿠키, 프로필 경로의 내용은 로그와 예외 메시지에 출력하지 않는다.
- `.env.example`에는 변수 이름과 빈 값만 기록한다.

기존 `scripts/yuksudang_volume/config.py`의 단순 dotenv 파싱 규칙을 재사용 가능한 유틸리티로 추출할지는 구현 시 판단한다. 관련 없는 검색량 설정 구조를 로그인 설정과 결합해서는 안 된다.

## 7. 브랜드별 독립 프로필

프로필은 반드시 브랜드 단위로 분리한다.

```text
<SMARTPLACE_RUNTIME_ROOT>/profiles/yuksoodang
<SMARTPLACE_RUNTIME_ROOT>/profiles/hanchon
```

필수 동작:

- 경로를 절대경로로 정규화한다.
- 프로필 디렉터리를 실행 전에 생성한다.
- 프로필과 쿠키를 Git에 포함하지 않는다.
- 동일 브랜드 프로필을 여러 프로세스가 동시에 열지 못하도록 잠금 파일을 사용한다.
- 다른 브랜드는 서로 다른 프로필이므로 동시에 실행할 수 있게 설계할 수 있다.
- 비정상 종료 뒤 남은 잠금의 처리 원칙과 오류 메시지를 명시한다.

초기 구현은 단일 프로세스 내 `threading.Lock`만으로 충분하지 않다. 별도 CLI 또는 HTML 브리지 프로세스가 같은 프로필을 열 수 있으므로 프로세스 간 파일 잠금이 필요하다.

## 8. UC 브라우저 생성

참조 구현에서 유지할 옵션:

- `--lang=ko-KR`
- `--window-size=1920,1080`
- 브랜드별 `user_data_dir`
- `use_subprocess=True`
- 호출자가 선택하는 `headless`
- UC 연결 타임아웃의 제한적 설정과 실행 후 복원

변경할 부분:

- `version_main=150`을 하드코딩하지 않는다.
- Chrome 실행 파일의 버전에서 major를 감지한다.
- 현재 환경에서는 `version_main=151`이 예상되지만 테스트에서 숫자를 고정하지 않는다.
- Chrome을 찾지 못하거나 버전을 해석하지 못하면 UC 실행 전에 구성 오류로 중단한다.
- UC 드라이버 설치 또는 패치 실패를 로그인 실패와 구분한다.

초기 로그인과 CAPTCHA/추가 인증 대응을 위해 기본 검증은 `headless=False`로 수행하는 것이 안전하다. 프로필 로그인 재사용이 안정적으로 확인된 뒤 headless 동작을 별도 검증한다.

## 9. 로그인 및 세션 재사용 흐름

권장 흐름:

```text
브랜드 선택
→ 설정과 자격 증명 검증
→ 브랜드 프로필 잠금 획득
→ Chrome major 감지
→ UC WebDriver 생성
→ SmartPlace 인증 상태 확인
→ 인증됨: 기존 세션 재사용
→ 인증 안 됨: 네이버 로그인 수행
→ SmartPlace 인증 상태 재확인
→ 인증된 driver 반환
```

중요한 점은 네이버 로그인 페이지를 벗어났다는 사실만으로 SmartPlace 인증 성공을 판단하지 않는 것이다. 로그인 이후 SmartPlace의 인증 필요 페이지에 접근해 다음 중 안정적인 신호를 확인해야 한다.

- 로그인 페이지로 리다이렉트되지 않음
- SmartPlace의 인증된 사용자 UI 또는 계정/사업장 선택 UI 존재
- 로그아웃 또는 인증 사용자 전용 API/화면의 정상 응답

정확한 성공 신호는 실제 페이지를 브라우저로 조사한 뒤 상수 또는 검증 함수에 캡슐화한다.

## 10. ID/PW 로그인 방식

참조 구현의 핵심은 입력 요소의 `value`를 단순 할당하지 않고 `HTMLInputElement.prototype.value`의 native setter를 호출한 뒤 `input`과 `change` 이벤트를 발생시키는 것이다. 이 원리는 유지한다.

로그인 버튼은 현재 확인된 여러 ID 후보를 순서대로 탐색하되 다음 조건을 확인한다.

- 화면에 표시됨
- 활성화됨
- stale element 발생 시 제한적으로 재탐색
- 일반 클릭 실패 시 JavaScript 클릭을 제한적으로 시도

성공하지 못하면 반드시 예외를 발생시킨다. CAPTCHA, 2단계 인증, 새 기기 확인 또는 보안 알림은 자동 우회하지 않는다. 표시 브라우저를 유지해 사용자가 완료할 수 있는 수동 개입 모드를 별도 설계하거나, 명확한 `ManualAuthenticationRequired` 오류로 중단한다.

클립보드 로그인 방식은 시스템 클립보드 오염과 비밀번호 잔류 위험 때문에 기본 구현에서 제외한다.

## 11. 생명주기와 공개 인터페이스

`SmartPlaceSession`이 다음 책임을 가진다.

- 브랜드 설정 로드
- 프로필 잠금 획득 및 해제
- WebDriver 생성
- 기존 세션 검증과 필요 시 로그인
- 정상/예외 종료 시 `driver.quit()` 보장
- 로그인 완료 후 같은 driver를 후속 자동화에 제공

권장 인터페이스 예시:

```python
session = SmartPlaceSession.for_brand(
    "한촌설렁탕",
    env_file=Path(".env"),
    headless=False,
)

with session:
    driver = session.login()
```

`login()`을 여러 번 호출할 경우 새 브라우저를 계속 만들지 않고 현재 세션의 인증 상태를 확인해 같은 driver를 반환하도록 한다.

## 12. 오류 분류

후속 자동화가 재시도 또는 사용자 개입 여부를 판단할 수 있도록 오류를 구분한다.

```text
SmartPlaceAuthError
├─ AuthConfigError
├─ ChromeNotFoundError
├─ ChromeVersionError
├─ ProfileInUseError
├─ BrowserStartError
├─ LoginPageChangedError
├─ LoginFailedError
└─ ManualAuthenticationRequired
```

오류 메시지에는 브랜드명, 실패 단계, 사용자가 취할 수 있는 조치를 포함할 수 있다. ID, 비밀번호, 쿠키, 전체 프로필 내용은 포함하지 않는다.

## 13. 테스트 전략

운영 계정과 실제 브라우저를 사용하기 전에 fake driver로 호출 계약을 검증한다.

### 단위 테스트

- 두 브랜드의 환경변수와 프로필 식별자 매핑
- 알 수 없는 브랜드 거부
- 누락된 자격 증명 오류와 비밀값 비노출
- 브랜드별 프로필 경로 분리
- 프로필 잠금 충돌 감지
- Chrome 버전 문자열에서 major 추출
- UC에 올바른 옵션과 프로필 경로 전달
- 기존 인증 세션이면 ID/PW 로그인을 건너뜀
- 만료 세션이면 로그인 후 재검증
- 로그인 성공 판정 실패 시 예외
- 예외 발생 시 driver 종료와 잠금 해제
- 같은 세션에서 `login()` 재호출 시 driver 재사용

### 제한된 통합 테스트

1. 육수당 표시 브라우저로 최초 로그인
2. 종료 후 같은 프로필로 재실행해 자동 로그인 생략 확인
3. 한촌설렁탕 프로필이 육수당 세션을 공유하지 않는지 확인
4. 한촌설렁탕 최초 로그인과 재사용 확인
5. 잘못된 비밀번호 또는 로그인 취소 시 명시적 실패 확인
6. 같은 브랜드 프로필 동시 실행 차단 확인
7. 로그인된 driver로 SmartPlace 인증 페이지 접근 확인

통합 테스트는 비밀번호나 페이지 원문을 테스트 출력에 남기지 않는다.

## 14. 의존성과 실행 환경

예상 Python 의존성:

- `selenium`
- `undetected-chromedriver`
- 프로세스 간 잠금 라이브러리 또는 Windows에서도 동작하는 소규모 잠금 구현
- `pytest`

현재 `python` 명령이 PATH에 없으므로 구현 전에 다음 중 하나를 확정해야 한다.

1. 저장소에 `.venv`를 만들고 `\.venv\Scripts\python.exe`를 표준 실행기로 사용
2. Codex가 제공하는 번들 Python을 사용해 `.venv` 구성

의존성 버전을 파일로 고정하고 재현 가능한 설치 명령을 문서화한다. 전역 Python이나 외부 프로젝트의 가상환경을 암묵적으로 재사용하지 않는다.

## 15. 보안 및 운영 경계

- 실제 계정정보를 코드, 테스트 fixture, 문서, 로그에 넣지 않는다.
- 비밀번호가 포함된 설정 객체는 `repr`에서 마스킹한다.
- 프로필과 쿠키는 저장소 밖 또는 Git 비추적 런타임에 둔다.
- CAPTCHA와 2단계 인증을 우회하지 않는다.
- 로그인 실패를 빈 데이터 또는 정상 값으로 변환하지 않는다.
- 네이버 DOM이나 인증 정책이 바뀔 수 있으므로 선택자와 성공 판정을 한곳에 모은다.
- 브라우저 자동화가 실행되는 동안 동일 프로필을 사람이 Chrome에서 열지 않는다.
- 실제 대표키워드 저장은 로그인 검증과 별개의 명시적 승인 단계로 둔다.

## 16. 이번 단계에서 제외하는 범위

다음은 로그인 모듈 이후의 별도 작업이다.

- HTML `5개 복사` 버튼과 로컬 자동화 브리지 연결
- HTML에서 선택한 매장과 SmartPlace 사업장 매핑
- 기존 대표키워드 삭제 및 신규 키워드 입력
- 키워드별 15자 제한, 중복, 금칙어 등 SmartPlace 검증 대응
- 최종 저장 버튼 클릭
- 다수 매장 일괄 처리와 재시도 큐
- 변경 전후 감사 로그와 롤백 자료 생성

로그인 모듈은 위 작업이 동일한 인증 driver를 안전하게 사용할 수 있는 기반만 제공한다.

## 17. 구현 순서 제안

1. Python 실행 환경과 의존성 파일 확정
2. 브랜드 타입과 설정 로더 구현
3. 런타임/프로필 경로 및 프로세스 간 잠금 구현
4. Chrome 탐색과 major 감지 구현
5. UC driver factory 구현
6. 인증 상태 검사와 네이버 로그인 구현
7. `SmartPlaceSession` 생명주기 조립
8. fake driver 기반 단위 테스트 완료
9. 육수당 표시 브라우저 최초 로그인 및 세션 재사용 검증
10. 한촌설렁탕 독립 프로필 검증
11. headless 재사용 가능 여부 별도 검증
12. 대표키워드 자동화 모듈에 공개 인터페이스 연결

## 18. 완료 기준

다음 조건을 모두 충족하면 로그인 모듈 이식이 완료된 것으로 본다.

- 육수당과 한촌설렁탕이 각각 독립 프로필을 사용한다.
- 최초 로그인 후 브라우저를 재실행했을 때 유효한 세션을 재사용한다.
- 세션 만료 시에만 자격 증명 로그인을 수행한다.
- 설치된 Chrome major를 감지해 UC에 전달한다.
- 동일 프로필 동시 실행을 차단한다.
- 로그인 성공을 SmartPlace 인증 상태로 재검증한다.
- 실패 시 구분 가능한 예외를 발생시킨다.
- 자격 증명이 로그, 예외, 테스트 출력에 노출되지 않는다.
- 모든 종료 경로에서 driver와 프로필 잠금이 정리된다.
- fake driver 단위 테스트와 브랜드별 제한 통합 테스트가 통과한다.
- 후속 대표키워드 자동화가 로그인된 driver를 같은 세션에서 사용할 수 있다.

## 19. 남은 의사결정

구현 시작 전에 다음을 확정하거나 실제 페이지 조사로 결정해야 한다.

1. 기본 `SMARTPLACE_RUNTIME_ROOT`의 정확한 위치
2. 프로젝트 표준 Python/가상환경 경로
3. 의존성 잠금 방식
4. 사용할 프로세스 간 파일 잠금 방식
5. SmartPlace 로그인 성공을 판단할 안정적인 URL 또는 DOM 신호
6. CAPTCHA/2단계 인증 시 브라우저 유지와 수동 완료를 지원할지 여부
7. 운영 시 headless를 기본값으로 허용할지 여부
8. 로그인 모듈 CLI 진입점을 함께 제공할지 여부

## 20. 한 문장 요약

> 육수당과 한촌설렁탕 계정을 브랜드별 독립 Chrome 프로필로 격리하고, UC 브라우저에서 기존 인증 세션을 우선 재사용하되 만료 시에만 안전한 네이버 로그인을 수행하는 프로젝트 전용 `smartplace_auth` 모듈을 구현한다.
