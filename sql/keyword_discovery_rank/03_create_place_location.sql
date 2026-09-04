SET NOCOUNT ON;
SET XACT_ABORT ON;

IF DB_NAME() <> N'naverDB'
    THROW 51000, 'Run this script in naverDB.', 1;

IF OBJECT_ID(N'dbo.naver_place_location', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.naver_place_location (
        place_id varchar(50) NOT NULL,
        latitude decimal(10,7) NOT NULL,
        longitude decimal(10,7) NOT NULL,
        resolved_at datetime2(0) NOT NULL,
        verified_at datetime2(0) NOT NULL,
        resolver_version varchar(30) NOT NULL,
        CONSTRAINT PK_naver_place_location PRIMARY KEY (place_id),
        CONSTRAINT CK_naver_place_location_latitude CHECK (latitude BETWEEN -90 AND 90),
        CONSTRAINT CK_naver_place_location_longitude CHECK (longitude BETWEEN -180 AND 180)
    );
END;

IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_snapshot', N'U')
      AND name = N'latitude' AND is_nullable = 0
)
    ALTER TABLE dbo.naver_keyword_discovery_snapshot ALTER COLUMN latitude decimal(10,7) NULL;

IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_snapshot', N'U')
      AND name = N'longitude' AND is_nullable = 0
)
    ALTER TABLE dbo.naver_keyword_discovery_snapshot ALTER COLUMN longitude decimal(10,7) NULL;
