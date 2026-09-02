SET NOCOUNT ON;

IF OBJECT_ID(N'dbo.naver_keyword_discovery_snapshot', N'U') IS NULL
    THROW 51000, 'Missing dbo.naver_keyword_discovery_snapshot.', 1;

IF OBJECT_ID(N'dbo.naver_keyword_discovery_result', N'U') IS NULL
    THROW 51000, 'Missing dbo.naver_keyword_discovery_result.', 1;

DECLARE @expected_columns TABLE (
    table_name sysname NOT NULL,
    column_name sysname NOT NULL,
    type_name sysname NOT NULL,
    max_length smallint NOT NULL,
    precision_value tinyint NOT NULL,
    scale_value tinyint NOT NULL,
    is_nullable bit NOT NULL,
    is_identity bit NOT NULL,
    PRIMARY KEY (table_name, column_name)
);

INSERT INTO @expected_columns (
    table_name,
    column_name,
    type_name,
    max_length,
    precision_value,
    scale_value,
    is_nullable,
    is_identity
)
VALUES
    (N'naver_keyword_discovery_snapshot', N'snapshot_id', N'bigint', 8, 19, 0, 0, 1),
    (N'naver_keyword_discovery_snapshot', N'run_id', N'uniqueidentifier', 16, 0, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'task_key', N'char', 64, 0, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'query', N'nvarchar', 510, 0, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'normalized_query', N'nvarchar', 510, 0, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'target_store_id', N'nvarchar', 200, 0, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'target_store_name', N'nvarchar', 400, 0, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'location_name', N'nvarchar', 400, 0, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'latitude', N'decimal', 9, 10, 7, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'longitude', N'decimal', 9, 10, 7, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'device_type', N'varchar', 10, 0, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'source_type', N'varchar', 20, 0, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'source_id', N'nvarchar', 200, 0, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'requested_result_limit', N'smallint', 2, 5, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'observed_result_count', N'smallint', 2, 5, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'result_end_reached', N'bit', 1, 1, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'collect_status', N'varchar', 30, 0, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'collect_msg', N'nvarchar', 2000, 0, 0, 1, 0),
    (N'naver_keyword_discovery_snapshot', N'parser_version', N'varchar', 30, 0, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'final_url', N'nvarchar', 4000, 0, 0, 0, 0),
    (N'naver_keyword_discovery_snapshot', N'collected_at', N'datetime2', 6, 0, 0, 0, 0),
    (N'naver_keyword_discovery_result', N'snapshot_id', N'bigint', 8, 19, 0, 0, 0),
    (N'naver_keyword_discovery_result', N'raw_position', N'smallint', 2, 5, 0, 0, 0),
    (N'naver_keyword_discovery_result', N'organic_rank', N'smallint', 2, 5, 0, 1, 0),
    (N'naver_keyword_discovery_result', N'place_id', N'varchar', 50, 0, 0, 0, 0),
    (N'naver_keyword_discovery_result', N'place_name', N'nvarchar', 600, 0, 0, 0, 0),
    (N'naver_keyword_discovery_result', N'category', N'nvarchar', 600, 0, 0, 1, 0),
    (N'naver_keyword_discovery_result', N'is_ad', N'bit', 1, 1, 0, 0, 0),
    (N'naver_keyword_discovery_result', N'detail_url', N'nvarchar', 4000, 0, 0, 0, 0),
    (N'naver_keyword_discovery_result', N'distance_text', N'nvarchar', 200, 0, 0, 1, 0),
    (N'naver_keyword_discovery_result', N'is_own_store', N'bit', 1, 1, 0, 0, 0),
    (N'naver_keyword_discovery_result', N'matched_store_id', N'nvarchar', 200, 0, 0, 1, 0),
    (N'naver_keyword_discovery_result', N'match_method', N'varchar', 30, 0, 0, 0, 0);

IF EXISTS (
    SELECT 1
    FROM @expected_columns AS expected
    LEFT JOIN sys.tables AS tables
      ON tables.name = expected.table_name
     AND SCHEMA_NAME(tables.schema_id) = N'dbo'
    LEFT JOIN sys.columns AS columns
      ON columns.object_id = tables.object_id
     AND columns.name = expected.column_name
    LEFT JOIN sys.types AS types
      ON types.user_type_id = columns.user_type_id
    WHERE columns.column_id IS NULL
       OR types.name <> expected.type_name
       OR columns.max_length <> expected.max_length
       OR columns.precision <> expected.precision_value
       OR columns.scale <> expected.scale_value
       OR columns.is_nullable <> expected.is_nullable
       OR columns.is_identity <> expected.is_identity
)
    THROW 51000, 'Keyword discovery column definition mismatch.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.tables AS tables
    JOIN sys.columns AS columns ON columns.object_id = tables.object_id
    LEFT JOIN @expected_columns AS expected
      ON expected.table_name = tables.name
     AND expected.column_name = columns.name
    WHERE SCHEMA_NAME(tables.schema_id) = N'dbo'
      AND tables.name IN (N'naver_keyword_discovery_snapshot', N'naver_keyword_discovery_result')
      AND expected.column_name IS NULL
)
    THROW 51000, 'Unexpected keyword discovery column found.', 1;

IF NOT EXISTS (
    SELECT 1 FROM sys.key_constraints
    WHERE name = N'PK_naver_keyword_discovery_snapshot'
      AND parent_object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_snapshot', N'U')
      AND type = N'PK'
)
    THROW 51000, 'Missing snapshot primary key.', 1;

IF NOT EXISTS (
    SELECT 1 FROM sys.key_constraints
    WHERE name = N'UQ_naver_keyword_discovery_snapshot_run_task'
      AND parent_object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_snapshot', N'U')
      AND type = N'UQ'
)
    THROW 51000, 'Missing run/task uniqueness constraint.', 1;

IF NOT EXISTS (
    SELECT 1 FROM sys.key_constraints
    WHERE name = N'PK_naver_keyword_discovery_result'
      AND parent_object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_result', N'U')
      AND type = N'PK'
)
    THROW 51000, 'Missing result primary key.', 1;

IF NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = N'FK_naver_keyword_discovery_result_snapshot'
      AND parent_object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_result', N'U')
      AND referenced_object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_snapshot', N'U')
)
    THROW 51000, 'Missing result-to-snapshot foreign key.', 1;

DECLARE @expected_indexes TABLE (
    table_name sysname NOT NULL,
    index_name sysname NOT NULL,
    is_unique bit NOT NULL,
    has_filter bit NOT NULL,
    PRIMARY KEY (table_name, index_name)
);

INSERT INTO @expected_indexes (table_name, index_name, is_unique, has_filter)
VALUES
    (N'naver_keyword_discovery_snapshot', N'IX_naver_keyword_discovery_snapshot_query_collected_at', 0, 0),
    (N'naver_keyword_discovery_snapshot', N'IX_naver_keyword_discovery_snapshot_target_store_id_collected_at', 0, 0),
    (N'naver_keyword_discovery_snapshot', N'IX_naver_keyword_discovery_snapshot_collect_status_collected_at', 0, 0),
    (N'naver_keyword_discovery_snapshot', N'IX_naver_keyword_discovery_snapshot_run_id', 0, 0),
    (N'naver_keyword_discovery_result', N'UX_naver_keyword_discovery_result_snapshot_organic_rank', 1, 1),
    (N'naver_keyword_discovery_result', N'IX_naver_keyword_discovery_result_place_id_snapshot_id', 0, 0),
    (N'naver_keyword_discovery_result', N'IX_naver_keyword_discovery_result_snapshot_id_is_ad_organic_rank', 0, 0),
    (N'naver_keyword_discovery_result', N'IX_naver_keyword_discovery_result_is_own_store_matched_store_id', 0, 0);

IF EXISTS (
    SELECT 1
    FROM @expected_indexes AS expected
    LEFT JOIN sys.tables AS tables
      ON tables.name = expected.table_name
     AND SCHEMA_NAME(tables.schema_id) = N'dbo'
    LEFT JOIN sys.indexes AS indexes
      ON indexes.object_id = tables.object_id
     AND indexes.name = expected.index_name
    WHERE indexes.index_id IS NULL
       OR indexes.is_unique <> expected.is_unique
       OR indexes.has_filter <> expected.has_filter
)
    THROW 51000, 'Keyword discovery index definition mismatch.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = N'UX_naver_keyword_discovery_result_snapshot_organic_rank'
      AND object_id = OBJECT_ID(N'dbo.naver_keyword_discovery_result', N'U')
      AND REPLACE(filter_definition, N' ', N'') <> N'([organic_rank]ISNOTNULL)'
)
    THROW 51000, 'Organic-rank filtered index predicate mismatch.', 1;

SELECT
    DB_NAME() AS database_name,
    2 AS verified_table_count,
    (SELECT COUNT(*) FROM @expected_columns) AS verified_column_count,
    (SELECT COUNT(*) FROM @expected_indexes) AS verified_nonconstraint_index_count;
