# Naver Place Location Cache Design

## 목적

키워드 발굴 순위 수집기가 사용자의 위도·경도 수기 입력 없이 네이버 Place ID로 매장 좌표를 확보하고, 한 번 확보한 좌표를 `naverDB`에 저장해 반복 검색에서 재사용한다. 지역어가 없는 `설렁탕`, `국밥`, `해장`, `혼밥` 등의 키워드도 매장 위치를 기준으로 비교할 수 있게 한다.

## 범위

- `naverDB.dbo.naver_place_location` 좌표 캐시 테이블을 추가한다.
- 네이버 Place 페이지에서 요청 Place ID와 결합된 좌표를 추출하는 `PlaceLocationResolver`를 추가한다.
- 엑셀과 향후 DB 입력 모두 좌표를 선택값으로 취급한다.
- 좌표가 없는 검색 작업을 캐시 조회 또는 Place 페이지 조회로 보완한다.
- 좌표 해석 실패는 해당 작업에만 적용하고 다른 작업은 계속한다.
- 캐시 자동 만료, 주기 갱신, 주소 기반 지오코딩은 이번 범위에 포함하지 않는다.

## 데이터 모델

`dbo.naver_place_location`은 매장이나 검색 실행이 아닌 네이버 Place ID 단위의 외부 기준정보 캐시다.

| 컬럼 | SQL 형식 | 규칙 |
|---|---|---|
| `place_id` | `varchar(50)` | PK, 공백 불가 |
| `latitude` | `decimal(10,7)` | `-90` 이상 `90` 이하 |
| `longitude` | `decimal(10,7)` | `-180` 이상 `180` 이하 |
| `resolved_at` | `datetime2(0)` | 최초 저장 시각, UTC |
| `verified_at` | `datetime2(0)` | 마지막 검증 시각, UTC |
| `resolver_version` | `varchar(30)` | 좌표 해석기 버전 |

`place_id`가 기본키이므로 별도 인덱스는 만들지 않는다. 좌표는 검색 시점의 재현 증거이기도 하므로 실제 사용값을 기존 `naver_keyword_discovery_snapshot.latitude/longitude`에도 복사한다.

좌표 해석 실패 스냅샷을 저장할 수 있도록 기존 스냅샷의 `latitude`와 `longitude`를 `NULL` 허용으로 변경하고 `collect_status`에 `LOCATION_RESOLVE_ERROR`를 사용한다. 성공·부분성공 검색 스냅샷의 좌표는 계속 필수다.

## 입력 계약

`검색작업` 시트는 기존 열을 유지해 하위 호환성을 보장한다. 필수 헤더에서 `위도`, `경도`를 제외한다.

- 위도와 경도가 모두 있으면 명시 좌표를 사용한다.
- 둘 다 없으면 `자사매장` 시트의 `네이버플레이스ID`로 좌표를 해석한다.
- 한쪽만 있으면 입력 오류다.
- `자사매장`의 `매장ID`, `매장명`, `네이버플레이스ID`는 계속 필수다.
- 같은 매장의 여러 키워드는 좌표 해석을 한 번만 수행한다.

`SearchTask.latitude`와 `SearchTask.longitude`는 해석 전에는 `None`, 브라우저 호출 전에는 유효한 `float`다. 검색 작업 키 중 좌표 부분은 해석 전 중복 제거에서는 `AUTO`, 해석 후 최종 중복 제거에서는 소수점 7자리 좌표를 사용한다.

## 구성요소와 인터페이스

### PlaceLocation

불변 값 객체로 `place_id`, `latitude`, `longitude`, `resolved_at`, `verified_at`, `resolver_version`을 보유한다.

### PlaceLocationRepository

- `get(place_id) -> PlaceLocation | None`
- `upsert(location) -> None`
- `preflight(expected_database="naverDB") -> None`

조회와 저장은 파라미터 바인딩 SQL만 사용한다. 저장은 `place_id` 기준 멱등 upsert이며, 기존 좌표가 있으면 `latitude`, `longitude`, `verified_at`, `resolver_version`을 갱신하고 `resolved_at`은 보존한다. 일반 실행은 commit하고 `--rollback-test`는 기존 `RollbackConnection`을 통해 롤백한다.

### PlacePageClient

`fetch(place_id) -> str` 인터페이스다. 모바일 User-Agent, 제한시간, HTTPS Place URL을 사용하며 리다이렉트 후 호스트가 `m.place.naver.com` 또는 `place.naver.com`인지 확인한다. 응답 본문이나 예외에 인증정보를 포함하지 않는다.

### PlaceCoordinateParser

`parse(html, expected_place_id) -> tuple[float, float]` 인터페이스다. 추출 우선순위는 다음과 같다.

1. 같은 매장 객체의 `id`, `x`, `y`
2. 길찾기 URL의 `did`, `dlng`, `dlat`
3. Place ID가 경로에 포함된 사진 URL의 `x`, `y`

요청 Place ID와 증거의 Place ID가 반드시 일치해야 한다. 여러 출처가 있으면 좌표를 소수점 5자리까지 비교하며 불일치 시 실패한다. 위도·경도의 전 세계 범위를 검증하고, 한국 범위 검사는 경고가 아닌 이번 프로젝트의 대상 제약으로 `33~39`, `124~132`를 적용한다.

### PlaceLocationResolver

`resolve(place_id) -> PlaceLocation` 인터페이스다.

1. Repository에서 조회한다.
2. 캐시 적중이면 네트워크를 호출하지 않는다.
3. 캐시 미적중이면 Place 페이지를 한 번 조회하고 파싱한다.
4. 추출값을 저장하고 반환한다.

한 실행 안에서는 Place ID별 메모리 캐시도 사용해 DB와 네트워크 중복 호출을 막는다.

## 실행 흐름

1. 입력 파일과 자사매장 ID를 검증한다.
2. 좌표가 없는 작업을 매장별로 그룹화한다.
3. Place ID를 이용해 좌표 캐시를 조회하고 필요할 때만 페이지를 조회한다.
4. 성공 작업에는 좌표를 주입한다.
5. 실패 작업은 `LOCATION_RESOLVE_ERROR` 스냅샷으로 저장하고 브라우저를 열지 않는다.
6. 좌표가 준비된 작업만 기존 `KeywordDiscoveryCollector`에 전달한다.
7. 기존 검색·파싱·검증·매칭·결과 저장 흐름은 변경하지 않는다.

위치 해석 실패 때문에 전체 실행을 중단하지 않는다. 단, DB 연결·권한·스키마 불일치는 기존처럼 전체 실행을 중단하는 치명 오류다.

## SQL 산출물

- `sql/keyword_discovery_rank/03_create_place_location.sql`
- `sql/keyword_discovery_rank/04_verify_place_location.sql`

생성 SQL은 반복 실행 가능해야 하며 기존 데이터나 테이블을 삭제하지 않는다. 검증 SQL은 대상 DB, 테이블, 6개 컬럼, 형식, NULL 여부, 기본키, 좌표 CHECK 제약을 확인하고 불일치 시 `THROW`한다.

## 오류 및 보안

- 네트워크·HTTP·파싱·좌표 불일치는 외부 원문을 그대로 노출하지 않고 안전한 메시지로 변환한다.
- HTML은 좌표 해석 실패 증거로 저장하지 않는다. 기존 검색 실패 증거 정책과 좌표 캐시를 분리한다.
- ERP 백업 DB에는 쓰지 않는다.
- Place URL은 입력 Place ID로만 조합하고 임의 URL을 받지 않는다.
- DB 문자열은 전부 파라미터 바인딩한다.

## 테스트 및 승인 기준

- `id/x/y`, `did/dlat/dlng`, 사진 URL `x/y` 추출 테스트
- Place ID 불일치, 출처 좌표 불일치, 범위 오류 테스트
- 캐시 적중 시 HTTP 미호출 테스트
- 캐시 미적중 시 한 번 조회하고 upsert하는 테스트
- 동일 Place ID 다중 키워드의 1회 해석 테스트
- 좌표 두 값 없음, 두 값 있음, 한 값만 있음 입력 테스트
- 일부 좌표 실패 시 나머지 검색 지속 및 실패 스냅샷 저장 테스트
- SQL 구조·멱등성·금지된 파괴 구문 테스트
- 전체 `test_keyword_discovery_*.py` 회귀 테스트
- 실제 Place ID 한 건의 `--rollback-test`로 좌표 추출·캐시 저장·검색·전체 롤백 확인

완료 조건은 전체 테스트 통과, SQL 검증 통과, 실제 롤백 검증 성공, 롤백 후 좌표 캐시·스냅샷·결과 테이블의 기준 건수가 실행 전과 동일한 것이다.
