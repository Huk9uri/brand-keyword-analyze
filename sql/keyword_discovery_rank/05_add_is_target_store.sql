SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.naver_keyword_discovery_snapshot', N'U') IS NULL
    THROW 51000, 'Missing dbo.naver_keyword_discovery_snapshot.', 1;

IF OBJECT_ID(N'dbo.naver_keyword_discovery_result', N'U') IS NULL
    THROW 51000, 'Missing dbo.naver_keyword_discovery_result.', 1;

IF COL_LENGTH(N'dbo.naver_keyword_discovery_result', N'is_target_store') IS NULL
BEGIN
    ALTER TABLE dbo.naver_keyword_discovery_result
        ADD is_target_store bit NOT NULL
            CONSTRAINT DF_naver_keyword_discovery_result_is_target_store DEFAULT (0)
            WITH VALUES;
END;
GO

UPDATE result
SET is_target_store = CASE
    WHEN result.is_own_store = 1
     AND result.matched_store_id = snapshot.target_store_id
    THEN 1
    ELSE 0
END
FROM dbo.naver_keyword_discovery_result AS result
JOIN dbo.naver_keyword_discovery_snapshot AS snapshot
  ON snapshot.snapshot_id = result.snapshot_id
WHERE result.is_target_store <> CASE
    WHEN result.is_own_store = 1
     AND result.matched_store_id = snapshot.target_store_id
    THEN 1
    ELSE 0
END;

SELECT
    COUNT(*) AS result_row_count,
    SUM(CASE WHEN is_own_store = 1 THEN 1 ELSE 0 END) AS own_store_row_count,
    SUM(CASE WHEN is_target_store = 1 THEN 1 ELSE 0 END) AS target_store_row_count
FROM dbo.naver_keyword_discovery_result;
