-- 승인 후 naverDB에서 별도 실행. 애플리케이션은 이 파일을 자동 실행하지 않는다.
SET NOCOUNT ON;
SET XACT_ABORT ON;
IF DB_NAME() <> N'naverDB' THROW 51030, N'대상 DB는 naverDB여야 합니다.', 1;
BEGIN TRANSACTION;
IF OBJECT_ID(N'dbo.naver_keyword_search_volume_snapshot', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.naver_keyword_search_volume_snapshot (
        volume_snapshot_id bigint IDENTITY PRIMARY KEY,
        collection_run_id uniqueidentifier NOT NULL,
        request_keyword nvarchar(255) NOT NULL,
        response_keyword nvarchar(255) NULL,
        searchad_lookup_key nvarchar(255) COLLATE Latin1_General_100_BIN2 NOT NULL,
        provider varchar(30) NOT NULL,
        fetched_at datetimeoffset(3) NOT NULL,
        period_type varchar(30) NOT NULL,
        period_start date NULL,
        period_end date NULL,
        period_definition nvarchar(1000) NOT NULL,
        raw_pc nvarchar(100) NULL,
        raw_mobile nvarchar(100) NULL,
        pc_count bigint NULL,
        mobile_count bigint NULL,
        total_count bigint NULL,
        observation_status varchar(30) NOT NULL,
        response_json nvarchar(max) NULL,
        response_hash char(64) NULL,
        failure_code varchar(50) NULL,
        parser_version varchar(50) NOT NULL,
        CONSTRAINT UQ_keyword_volume_run_key UNIQUE(collection_run_id, provider, searchad_lookup_key),
        CONSTRAINT CK_keyword_volume_status CHECK(observation_status IN ('EXACT','CENSORED','NOT_PROVIDED','FAILED','INVALID')),
        CONSTRAINT CK_keyword_volume_period CHECK(period_type IN ('PROVIDER_MONTHLY','EXACT_30D','UNVERIFIED')),
        CONSTRAINT CK_keyword_volume_dates CHECK((period_start IS NULL AND period_end IS NULL) OR (period_start IS NOT NULL AND period_end IS NOT NULL AND period_start <= period_end)),
        CONSTRAINT CK_keyword_volume_30d CHECK(period_type <> 'EXACT_30D' OR (period_start IS NOT NULL AND period_end IS NOT NULL AND DATEDIFF(day,period_start,period_end)=29)),
        CONSTRAINT CK_keyword_volume_nonnegative CHECK((pc_count IS NULL OR pc_count>=0) AND (mobile_count IS NULL OR mobile_count>=0) AND (total_count IS NULL OR total_count>=0)),
        CONSTRAINT CK_keyword_volume_exact CHECK((observation_status='EXACT' AND pc_count IS NOT NULL AND mobile_count IS NOT NULL AND total_count IS NOT NULL AND CAST(total_count AS decimal(20,0))=CAST(pc_count AS decimal(20,0))+CAST(mobile_count AS decimal(20,0))) OR (observation_status<>'EXACT' AND total_count IS NULL)),
        CONSTRAINT CK_keyword_volume_json CHECK(response_json IS NULL OR ISJSON(response_json)=1)
    );
    CREATE INDEX IX_keyword_volume_latest ON dbo.naver_keyword_search_volume_snapshot(provider,searchad_lookup_key,fetched_at DESC,volume_snapshot_id DESC);
END;
IF OBJECT_ID(N'dbo.naver_keyword_evaluation_run', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.naver_keyword_evaluation_run (
        evaluation_run_id uniqueidentifier PRIMARY KEY,
        as_of_at datetimeoffset(3) NOT NULL,
        calculation_version varchar(50) NOT NULL,
        input_manifest_json nvarchar(max) NOT NULL,
        rules_json nvarchar(max) NOT NULL,
        input_hash char(64) NOT NULL,
        created_at datetimeoffset(3) NOT NULL,
        CONSTRAINT CK_keyword_evaluation_run_json CHECK(ISJSON(input_manifest_json)=1 AND ISJSON(rules_json)=1)
    );
END;
IF OBJECT_ID(N'dbo.naver_keyword_evaluation_result', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.naver_keyword_evaluation_result (
        evaluation_result_id bigint IDENTITY PRIMARY KEY,
        evaluation_run_id uniqueidentifier NOT NULL,
        candidate_id bigint NOT NULL,
        target_place_id varchar(50) NOT NULL,
        normalized_keyword nvarchar(255) NOT NULL,
        volume_snapshot_id bigint NULL,
        rank_snapshot_id bigint NULL,
        raw_scores_json nvarchar(max) NOT NULL,
        normalized_scores_json nvarchar(max) NOT NULL,
        gate_results_json nvarchar(max) NOT NULL,
        reason_codes_json nvarchar(max) NOT NULL,
        quality_json nvarchar(max) NOT NULL,
        final_class varchar(20) NOT NULL,
        created_at datetimeoffset(3) NOT NULL,
        CONSTRAINT UQ_keyword_evaluation_candidate UNIQUE(evaluation_run_id,candidate_id),
        CONSTRAINT FK_keyword_evaluation_run FOREIGN KEY(evaluation_run_id) REFERENCES dbo.naver_keyword_evaluation_run(evaluation_run_id),
        CONSTRAINT FK_keyword_evaluation_candidate FOREIGN KEY(candidate_id) REFERENCES dbo.naver_keyword_discovery_candidate(candidate_id),
        CONSTRAINT FK_keyword_evaluation_volume FOREIGN KEY (volume_snapshot_id) REFERENCES dbo.naver_keyword_search_volume_snapshot(volume_snapshot_id),
        CONSTRAINT FK_keyword_evaluation_rank FOREIGN KEY(rank_snapshot_id) REFERENCES dbo.naver_keyword_discovery_snapshot(snapshot_id),
        CONSTRAINT CK_keyword_evaluation_class CHECK(final_class IN ('VACANT','COMPETITIVE','EXCLUDED','REVIEW_REQUIRED')),
        CONSTRAINT CK_keyword_evaluation_result_json CHECK(ISJSON(raw_scores_json)=1 AND ISJSON(normalized_scores_json)=1 AND ISJSON(gate_results_json)=1 AND ISJSON(reason_codes_json)=1 AND ISJSON(quality_json)=1)
    );
END;
IF OBJECT_ID(N'dbo.naver_keyword_evaluation_evidence', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.naver_keyword_evaluation_evidence (
        evaluation_result_id bigint NOT NULL,
        evidence_no int NOT NULL,
        evidence_type varchar(30) NOT NULL,
        source_refs_json nvarchar(max) NOT NULL,
        observed_values_json nvarchar(max) NOT NULL,
        decision_json nvarchar(max) NOT NULL,
        CONSTRAINT PK_keyword_evaluation_evidence PRIMARY KEY(evaluation_result_id,evidence_no),
        CONSTRAINT FK_keyword_evaluation_evidence FOREIGN KEY(evaluation_result_id) REFERENCES dbo.naver_keyword_evaluation_result(evaluation_result_id),
        CONSTRAINT CK_keyword_evaluation_evidence_json CHECK(ISJSON(source_refs_json)=1 AND ISJSON(observed_values_json)=1 AND ISJSON(decision_json)=1)
    );
END;
IF OBJECT_ID(N'dbo.naver_keyword_evaluation_review', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.naver_keyword_evaluation_review (
        review_id bigint IDENTITY PRIMARY KEY,
        evaluation_result_id bigint NOT NULL,
        reviewer nvarchar(100) NOT NULL,
        reviewed_at datetimeoffset(3) NOT NULL,
        dining_intent varchar(30) NOT NULL,
        store_fit varchar(30) NOT NULL,
        competition_type varchar(30) NOT NULL,
        market_type varchar(30) NOT NULL,
        recommendation varchar(30) NOT NULL,
        confidence varchar(30) NOT NULL,
        reason nvarchar(max) NOT NULL,
        CONSTRAINT FK_keyword_evaluation_review FOREIGN KEY(evaluation_result_id) REFERENCES dbo.naver_keyword_evaluation_result(evaluation_result_id),
        CONSTRAINT CK_keyword_review_intent CHECK(dining_intent IN ('DINING','MIXED','NON_DINING','UNKNOWN')),
        CONSTRAINT CK_keyword_review_fit CHECK(store_fit IN ('PASS','FAIL','UNKNOWN')),
        CONSTRAINT CK_keyword_review_competition CHECK(competition_type IN ('DIRECT','INDIRECT','MIXED','NONE','UNKNOWN')),
        CONSTRAINT CK_keyword_review_market CHECK(market_type IN ('VACANT','COMPETITIVE','EXCLUDED','REVIEW_REQUIRED')),
        CONSTRAINT CK_keyword_review_recommendation CHECK(recommendation IN ('YES','NO','HOLD')),
        CONSTRAINT CK_keyword_review_confidence CHECK(confidence IN ('HIGH','MEDIUM','LOW')),
        CONSTRAINT CK_keyword_review_reason CHECK(LEN(LTRIM(RTRIM(reason)))>0)
    );
END;
COMMIT TRANSACTION;
