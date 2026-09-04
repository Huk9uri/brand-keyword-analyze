SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.naver_keyword_discovery_candidate', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.naver_keyword_discovery_candidate (
        candidate_id bigint IDENTITY(1,1) NOT NULL,
        run_id uniqueidentifier NOT NULL,
        brand_code varchar(10) NOT NULL,
        candidate_scope varchar(10) NOT NULL,
        place_id varchar(50) NOT NULL CONSTRAINT DF_naver_keyword_discovery_candidate_place DEFAULT (''),
        normalized_keyword nvarchar(255) NOT NULL,
        term_category varchar(30) NOT NULL,
        store_review_count int NOT NULL,
        brand_review_count int NOT NULL,
        brand_store_count int NOT NULL,
        weighted_mention_score decimal(12,3) NOT NULL,
        from_menu bit NOT NULL,
        from_brand_menu bit NOT NULL,
        from_operation_keyword bit NOT NULL,
        from_searchad_related bit NOT NULL,
        from_review bit NOT NULL,
        candidate_status varchar(30) NOT NULL,
        generated_at datetime2(0) NOT NULL,
        CONSTRAINT PK_naver_keyword_discovery_candidate PRIMARY KEY (candidate_id),
        CONSTRAINT UQ_naver_keyword_discovery_candidate_run_scope_keyword
            UNIQUE (run_id, brand_code, candidate_scope, place_id, normalized_keyword),
        CONSTRAINT CK_naver_keyword_discovery_candidate_scope
            CHECK (candidate_scope IN ('STORE', 'BRAND')),
        CONSTRAINT CK_naver_keyword_discovery_candidate_place_scope
            CHECK ((candidate_scope = 'STORE' AND place_id <> '') OR (candidate_scope = 'BRAND' AND place_id = '')),
        CONSTRAINT CK_naver_keyword_discovery_candidate_status
            CHECK (candidate_status IN ('READY', 'INSUFFICIENT_EVIDENCE', 'REVIEW_REQUIRED', 'EXCLUDED')),
        CONSTRAINT CK_naver_keyword_discovery_candidate_counts
            CHECK (store_review_count >= 0 AND brand_review_count >= 0 AND brand_store_count >= 0),
        CONSTRAINT CK_naver_keyword_discovery_candidate_weight
            CHECK (weighted_mention_score >= 0)
    );
END;

IF OBJECT_ID(N'dbo.naver_keyword_discovery_review_term', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.naver_keyword_discovery_review_term (
        review_term_id bigint IDENTITY(1,1) NOT NULL,
        candidate_id bigint NOT NULL,
        run_id uniqueidentifier NOT NULL,
        source_type varchar(10) NOT NULL,
        source_review_id bigint NOT NULL,
        brand_code varchar(10) NOT NULL,
        place_id varchar(50) NOT NULL,
        review_date date NOT NULL,
        raw_expression nvarchar(500) NOT NULL,
        normalized_keyword nvarchar(255) NOT NULL,
        term_category varchar(30) NOT NULL,
        time_weight decimal(3,2) NOT NULL,
        extraction_method varchar(20) NOT NULL,
        review_required bit NOT NULL,
        evidence_excerpt nvarchar(1000) NOT NULL,
        analyzed_at datetime2(0) NOT NULL,
        CONSTRAINT PK_naver_keyword_discovery_review_term PRIMARY KEY (review_term_id),
        CONSTRAINT FK_naver_keyword_discovery_review_term_candidate
            FOREIGN KEY (candidate_id) REFERENCES dbo.naver_keyword_discovery_candidate(candidate_id),
        CONSTRAINT UQ_naver_keyword_discovery_review_term_run_source_keyword
            UNIQUE (run_id, source_type, source_review_id, normalized_keyword),
        CONSTRAINT CK_naver_keyword_discovery_review_term_source
            CHECK (source_type IN ('BLOG', 'VISITOR')),
        CONSTRAINT CK_naver_keyword_discovery_review_term_weight
            CHECK (time_weight IN (0.50, 0.80, 1.00)),
        CONSTRAINT CK_naver_keyword_discovery_review_term_method
            CHECK (extraction_method IN ('RULE', 'DICTIONARY', 'LLM'))
    );
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_candidate')
      AND name = N'IX_naver_keyword_discovery_candidate_place_status'
)
BEGIN
    CREATE INDEX IX_naver_keyword_discovery_candidate_place_status
        ON dbo.naver_keyword_discovery_candidate(place_id, candidate_status, generated_at);
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_review_term')
      AND name = N'IX_naver_keyword_discovery_review_term_place_keyword'
)
BEGIN
    CREATE INDEX IX_naver_keyword_discovery_review_term_place_keyword
        ON dbo.naver_keyword_discovery_review_term(place_id, normalized_keyword, review_date);
END;

