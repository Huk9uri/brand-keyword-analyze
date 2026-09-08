SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.naver_place_keyword_snapshot', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.naver_place_keyword_snapshot (
        snapshot_id bigint IDENTITY(1,1) NOT NULL,
        run_id uniqueidentifier NOT NULL,
        rank_run_id uniqueidentifier NOT NULL,
        place_id varchar(50) NOT NULL,
        place_name nvarchar(300) NOT NULL,
        source_url nvarchar(2000) NOT NULL,
        collect_status varchar(30) NOT NULL,
        collect_method varchar(20) NOT NULL,
        content_hash char(64) NULL,
        is_changed bit NOT NULL,
        effective_snapshot_id bigint NULL,
        keyword_count smallint NOT NULL,
        parser_version varchar(30) NOT NULL,
        collect_msg nvarchar(1000) NULL,
        checked_at datetime2(3) NOT NULL,
        CONSTRAINT PK_naver_place_keyword_snapshot PRIMARY KEY (snapshot_id),
        CONSTRAINT UQ_naver_place_keyword_snapshot_run_place UNIQUE (run_id, place_id),
        CONSTRAINT FK_naver_place_keyword_snapshot_effective_snapshot
            FOREIGN KEY (effective_snapshot_id)
            REFERENCES dbo.naver_place_keyword_snapshot(snapshot_id),
        CONSTRAINT CK_naver_place_keyword_snapshot_status
            CHECK (collect_status IN ('SUCCESS','EMPTY','BLOCKED','LOAD_TIMEOUT','PLACE_MISMATCH','PARSE_ERROR')),
        CONSTRAINT CK_naver_place_keyword_snapshot_keyword_count
            CHECK (keyword_count >= 0)
    );
END;

GO
CREATE OR ALTER TRIGGER dbo.TR_naver_place_keyword_snapshot_validate_effective
ON dbo.naver_place_keyword_snapshot
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    IF EXISTS (
        SELECT 1
        FROM inserted
        LEFT JOIN dbo.naver_place_keyword_snapshot AS effective
          ON effective.snapshot_id = inserted.effective_snapshot_id
        WHERE inserted.effective_snapshot_id IS NOT NULL
          AND (
               effective.snapshot_id IS NULL
            OR effective.place_id <> inserted.place_id
            OR effective.collect_status NOT IN ('SUCCESS', 'EMPTY')
          )
    )
        THROW 51020, 'effective_snapshot_id must reference a valid snapshot for the same Place.', 1;
END;
GO

IF OBJECT_ID(N'dbo.naver_place_keyword_result', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.naver_place_keyword_result (
        snapshot_id bigint NOT NULL,
        keyword_order smallint NOT NULL,
        raw_keyword nvarchar(255) NOT NULL,
        normalized_keyword nvarchar(255) NOT NULL,
        CONSTRAINT UQ_naver_place_keyword_result_snapshot_keyword_order
            UNIQUE (snapshot_id, keyword_order),
        CONSTRAINT FK_naver_place_keyword_result_snapshot
            FOREIGN KEY (snapshot_id)
            REFERENCES dbo.naver_place_keyword_snapshot(snapshot_id),
        CONSTRAINT CK_naver_place_keyword_result_keyword_order
            CHECK (keyword_order >= 1)
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.naver_place_keyword_snapshot')
      AND name = N'IX_naver_place_keyword_snapshot_place_checked_at'
)
BEGIN
    CREATE INDEX IX_naver_place_keyword_snapshot_place_checked_at
        ON dbo.naver_place_keyword_snapshot(place_id, checked_at DESC);
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.naver_place_keyword_snapshot')
      AND name = N'IX_naver_place_keyword_snapshot_rank_run_id'
)
BEGIN
    CREATE INDEX IX_naver_place_keyword_snapshot_rank_run_id
        ON dbo.naver_place_keyword_snapshot(rank_run_id);
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.naver_place_keyword_snapshot')
      AND name = N'IX_naver_place_keyword_snapshot_effective_snapshot_id'
)
BEGIN
    CREATE INDEX IX_naver_place_keyword_snapshot_effective_snapshot_id
        ON dbo.naver_place_keyword_snapshot(effective_snapshot_id);
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.naver_place_keyword_result')
      AND name = N'IX_naver_place_keyword_result_snapshot_keyword_order'
)
BEGIN
    CREATE INDEX IX_naver_place_keyword_result_snapshot_keyword_order
        ON dbo.naver_place_keyword_result(snapshot_id, keyword_order);
END;
