SET NOCOUNT ON;

IF DB_NAME() <> N'naverDB'
    THROW 51000, 'Run this script in naverDB.', 1;

IF OBJECT_ID(N'dbo.naver_place_location', N'U') IS NULL
    THROW 51000, 'Missing dbo.naver_place_location.', 1;

IF (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME='naver_place_location') <> 6
    THROW 51000, 'Unexpected naver_place_location column count.', 1;

IF EXISTS (
    SELECT required.column_name, required.data_type, required.is_nullable
    FROM (VALUES
        (N'place_id', N'varchar', N'NO'),
        (N'latitude', N'decimal', N'NO'),
        (N'longitude', N'decimal', N'NO'),
        (N'resolved_at', N'datetime2', N'NO'),
        (N'verified_at', N'datetime2', N'NO'),
        (N'resolver_version', N'varchar', N'NO')
    ) required(column_name, data_type, is_nullable)
    LEFT JOIN INFORMATION_SCHEMA.COLUMNS actual
      ON actual.TABLE_SCHEMA='dbo' AND actual.TABLE_NAME='naver_place_location'
     AND actual.COLUMN_NAME=required.column_name
     AND actual.DATA_TYPE=required.data_type AND actual.IS_NULLABLE=required.is_nullable
    WHERE actual.COLUMN_NAME IS NULL
)
    THROW 51000, 'naver_place_location column contract mismatch.', 1;

IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE parent_object_id=OBJECT_ID(N'dbo.naver_place_location') AND type='PK' AND name=N'PK_naver_place_location')
    THROW 51000, 'Missing naver_place_location primary key.', 1;

IF (SELECT COUNT(*) FROM sys.check_constraints WHERE parent_object_id=OBJECT_ID(N'dbo.naver_place_location') AND name IN (N'CK_naver_place_location_latitude',N'CK_naver_place_location_longitude')) <> 2
    THROW 51000, 'Missing naver_place_location coordinate checks.', 1;

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID(N'dbo.naver_keyword_discovery_snapshot') AND name IN (N'latitude',N'longitude') AND is_nullable=0)
    THROW 51000, 'Snapshot coordinates must allow NULL.', 1;

SELECT DB_NAME() AS database_name, 1 AS verified_table_count, 6 AS verified_column_count, 3 AS verified_constraint_count;
