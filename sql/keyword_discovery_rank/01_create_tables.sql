SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.naver_keyword_discovery_snapshot', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.naver_keyword_discovery_snapshot (
        snapshot_id bigint IDENTITY(1,1) NOT NULL,
        run_id uniqueidentifier NOT NULL,
        task_key char(64) NOT NULL,
        query nvarchar(255) NOT NULL,
        normalized_query nvarchar(255) NOT NULL,
        target_store_id nvarchar(100) NOT NULL,
        target_store_name nvarchar(200) NOT NULL,
        location_name nvarchar(200) NOT NULL,
        latitude decimal(10,7) NULL,
        longitude decimal(10,7) NULL,
        device_type varchar(10) NOT NULL,
        source_type varchar(20) NOT NULL,
        source_id nvarchar(100) NOT NULL,
        requested_result_limit smallint NOT NULL,
        observed_result_count smallint NOT NULL,
        result_end_reached bit NOT NULL,
        collect_status varchar(30) NOT NULL,
        collect_msg nvarchar(1000) NULL,
        parser_version varchar(30) NOT NULL,
        final_url nvarchar(2000) NOT NULL,
        collected_at datetime2(0) NOT NULL,
        CONSTRAINT PK_naver_keyword_discovery_snapshot PRIMARY KEY (snapshot_id),
        CONSTRAINT UQ_naver_keyword_discovery_snapshot_run_task UNIQUE (run_id, task_key),
        CONSTRAINT CK_naver_keyword_discovery_snapshot_device_type CHECK (device_type IN ('MOBILE', 'PC')),
        CONSTRAINT CK_naver_keyword_discovery_snapshot_source_type CHECK (source_type IN ('EXCEL', 'DATABASE')),
        CONSTRAINT CK_naver_keyword_discovery_snapshot_latitude CHECK (latitude BETWEEN -90 AND 90),
        CONSTRAINT CK_naver_keyword_discovery_snapshot_longitude CHECK (longitude BETWEEN -180 AND 180),
        CONSTRAINT CK_naver_keyword_discovery_snapshot_observed_count CHECK (observed_result_count >= 0)
    );
END;
IF OBJECT_ID(N'dbo.naver_keyword_discovery_result', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.naver_keyword_discovery_result (
        snapshot_id bigint NOT NULL,
        raw_position smallint NOT NULL,
        organic_rank smallint NULL,
        place_id varchar(50) NOT NULL,
        place_name nvarchar(300) NOT NULL,
        category nvarchar(300) NULL,
        is_ad bit NOT NULL,
        detail_url nvarchar(2000) NOT NULL,
        distance_text nvarchar(100) NULL,
        is_own_store bit NOT NULL,
        matched_store_id nvarchar(100) NULL,
        match_method varchar(30) NOT NULL,
        is_target_store bit NOT NULL CONSTRAINT DF_naver_keyword_discovery_result_is_target_store DEFAULT (0),
        CONSTRAINT PK_naver_keyword_discovery_result PRIMARY KEY (snapshot_id, raw_position),
        CONSTRAINT FK_naver_keyword_discovery_result_snapshot FOREIGN KEY (snapshot_id) REFERENCES dbo.naver_keyword_discovery_snapshot(snapshot_id),
        CONSTRAINT CK_naver_keyword_discovery_result_raw_position CHECK (raw_position >= 1),
        CONSTRAINT CK_naver_keyword_discovery_result_organic_rank CHECK (organic_rank IS NULL OR organic_rank >= 1)
    );
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'UX_naver_keyword_discovery_result_snapshot_organic_rank'
      AND object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_result', N'U')
)
BEGIN
    CREATE UNIQUE INDEX UX_naver_keyword_discovery_result_snapshot_organic_rank
        ON dbo.naver_keyword_discovery_result(snapshot_id, organic_rank)
        WHERE organic_rank IS NOT NULL;
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_naver_keyword_discovery_snapshot_query_collected_at'
      AND object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_snapshot', N'U')
)
BEGIN
    CREATE INDEX IX_naver_keyword_discovery_snapshot_query_collected_at
        ON dbo.naver_keyword_discovery_snapshot(query, collected_at);
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_naver_keyword_discovery_snapshot_target_store_id_collected_at'
      AND object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_snapshot', N'U')
)
BEGIN
    CREATE INDEX IX_naver_keyword_discovery_snapshot_target_store_id_collected_at
        ON dbo.naver_keyword_discovery_snapshot(target_store_id, collected_at);
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_naver_keyword_discovery_snapshot_collect_status_collected_at'
      AND object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_snapshot', N'U')
)
BEGIN
    CREATE INDEX IX_naver_keyword_discovery_snapshot_collect_status_collected_at
        ON dbo.naver_keyword_discovery_snapshot(collect_status, collected_at);
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_naver_keyword_discovery_snapshot_run_id'
      AND object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_snapshot', N'U')
)
BEGIN
    CREATE INDEX IX_naver_keyword_discovery_snapshot_run_id
        ON dbo.naver_keyword_discovery_snapshot(run_id);
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_naver_keyword_discovery_result_place_id_snapshot_id'
      AND object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_result', N'U')
)
BEGIN
    CREATE INDEX IX_naver_keyword_discovery_result_place_id_snapshot_id
        ON dbo.naver_keyword_discovery_result(place_id, snapshot_id);
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_naver_keyword_discovery_result_snapshot_id_is_ad_organic_rank'
      AND object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_result', N'U')
)
BEGIN
    CREATE INDEX IX_naver_keyword_discovery_result_snapshot_id_is_ad_organic_rank
        ON dbo.naver_keyword_discovery_result(snapshot_id, is_ad, organic_rank);
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_naver_keyword_discovery_result_is_own_store_matched_store_id'
      AND object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_result', N'U')
)
BEGIN
    CREATE INDEX IX_naver_keyword_discovery_result_is_own_store_matched_store_id
        ON dbo.naver_keyword_discovery_result(is_own_store, matched_store_id);
END;
