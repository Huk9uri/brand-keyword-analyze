SET NOCOUNT ON;
SET ANSI_NULLS ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET ARITHABORT ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET QUOTED_IDENTIFIER ON;
SET NUMERIC_ROUNDABORT OFF;

DECLARE @verified_table_count int = (
    SELECT COUNT(*) FROM sys.tables
    WHERE schema_id = SCHEMA_ID(N'dbo')
      AND name IN (N'naver_keyword_discovery_candidate', N'naver_keyword_discovery_review_term')
);
DECLARE @verified_column_count int = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'dbo'
      AND TABLE_NAME IN ('naver_keyword_discovery_candidate', 'naver_keyword_discovery_review_term')
);
DECLARE @verified_constraint_count int = (
    SELECT COUNT(*) FROM sys.objects
    WHERE parent_object_id IN (
        OBJECT_ID(N'dbo.naver_keyword_discovery_candidate'),
        OBJECT_ID(N'dbo.naver_keyword_discovery_review_term')
    ) AND type IN ('PK', 'F', 'UQ', 'C', 'D')
);
DECLARE @verified_index_count int = (
    SELECT COUNT(*) FROM sys.indexes
    WHERE object_id IN (
        OBJECT_ID(N'dbo.naver_keyword_discovery_candidate'),
        OBJECT_ID(N'dbo.naver_keyword_discovery_review_term')
    ) AND name IS NOT NULL
);

IF @verified_table_count <> 2 THROW 51000, 'candidate discovery table count mismatch', 1;
IF @verified_column_count <> 34 THROW 51001, 'candidate discovery column count mismatch', 1;
IF @verified_constraint_count < 13 THROW 51002, 'candidate discovery constraint count mismatch', 1;
IF @verified_index_count < 6 THROW 51003, 'candidate discovery index count mismatch', 1;

SELECT DB_NAME() AS database_name,
       @verified_table_count AS verified_table_count,
       @verified_column_count AS verified_column_count,
       @verified_constraint_count AS verified_constraint_count,
       @verified_index_count AS verified_index_count;
