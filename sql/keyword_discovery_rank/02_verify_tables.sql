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
    (N'naver_keyword_discovery_snapshot', N'collected_at', N'datetime2', 6, 19, 0, 0, 0),
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
      ON tables.name COLLATE DATABASE_DEFAULT = expected.table_name
     AND SCHEMA_NAME(tables.schema_id) = N'dbo'
    LEFT JOIN sys.columns AS columns
      ON columns.object_id = tables.object_id
     AND columns.name COLLATE DATABASE_DEFAULT = expected.column_name
    LEFT JOIN sys.types AS types
      ON types.user_type_id = columns.user_type_id
    WHERE columns.column_id IS NULL
       OR types.name COLLATE DATABASE_DEFAULT <> expected.type_name
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
      ON expected.table_name = tables.name COLLATE DATABASE_DEFAULT
     AND expected.column_name = columns.name COLLATE DATABASE_DEFAULT
    WHERE SCHEMA_NAME(tables.schema_id) = N'dbo'
      AND tables.name IN (N'naver_keyword_discovery_snapshot', N'naver_keyword_discovery_result')
      AND expected.column_name IS NULL
)
    THROW 51000, 'Unexpected keyword discovery column found.', 1;

DECLARE @expected_key_constraints TABLE (
    table_name sysname NOT NULL,
    constraint_name sysname NOT NULL,
    constraint_type char(2) NOT NULL,
    PRIMARY KEY (table_name, constraint_name)
);

INSERT INTO @expected_key_constraints (table_name, constraint_name, constraint_type)
VALUES
    (N'naver_keyword_discovery_snapshot', N'PK_naver_keyword_discovery_snapshot', N'PK'),
    (N'naver_keyword_discovery_snapshot', N'UQ_naver_keyword_discovery_snapshot_run_task', N'UQ'),
    (N'naver_keyword_discovery_result', N'PK_naver_keyword_discovery_result', N'PK');

IF EXISTS (
    SELECT 1
    FROM @expected_key_constraints AS expected
    LEFT JOIN sys.tables AS tables
      ON tables.name COLLATE DATABASE_DEFAULT = expected.table_name
     AND SCHEMA_NAME(tables.schema_id) = N'dbo'
    LEFT JOIN sys.key_constraints AS key_constraints
      ON key_constraints.parent_object_id = tables.object_id
     AND key_constraints.name COLLATE DATABASE_DEFAULT = expected.constraint_name
    WHERE key_constraints.object_id IS NULL
       OR key_constraints.type COLLATE DATABASE_DEFAULT <> expected.constraint_type
)
    THROW 51000, 'Keyword discovery key constraint mismatch.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.key_constraints AS key_constraints
    JOIN sys.tables AS tables ON tables.object_id = key_constraints.parent_object_id
    LEFT JOIN @expected_key_constraints AS expected
      ON expected.table_name = tables.name COLLATE DATABASE_DEFAULT
     AND expected.constraint_name = key_constraints.name COLLATE DATABASE_DEFAULT
    WHERE SCHEMA_NAME(tables.schema_id) = N'dbo'
      AND tables.name IN (N'naver_keyword_discovery_snapshot', N'naver_keyword_discovery_result')
      AND expected.constraint_name IS NULL
)
    THROW 51000, 'Unexpected keyword discovery key constraint found.', 1;

DECLARE @expected_foreign_keys TABLE (
    table_name sysname NOT NULL,
    constraint_name sysname NOT NULL,
    referenced_table_name sysname NOT NULL,
    parent_columns nvarchar(4000) NOT NULL,
    referenced_columns nvarchar(4000) NOT NULL,
    PRIMARY KEY (table_name, constraint_name)
);

INSERT INTO @expected_foreign_keys (
    table_name,
    constraint_name,
    referenced_table_name,
    parent_columns,
    referenced_columns
)
VALUES
    (N'naver_keyword_discovery_result', N'FK_naver_keyword_discovery_result_snapshot', N'naver_keyword_discovery_snapshot', N'snapshot_id', N'snapshot_id');

IF EXISTS (
    SELECT 1
    FROM @expected_foreign_keys AS expected
    LEFT JOIN sys.tables AS tables
      ON tables.name COLLATE DATABASE_DEFAULT = expected.table_name
     AND SCHEMA_NAME(tables.schema_id) = N'dbo'
    LEFT JOIN sys.foreign_keys AS foreign_keys
      ON foreign_keys.parent_object_id = tables.object_id
     AND foreign_keys.name COLLATE DATABASE_DEFAULT = expected.constraint_name
    LEFT JOIN sys.tables AS referenced_tables
      ON referenced_tables.object_id = foreign_keys.referenced_object_id
     AND SCHEMA_NAME(referenced_tables.schema_id) = N'dbo'
    OUTER APPLY (
        SELECT STUFF((
            SELECT N',' + (parent_columns.name COLLATE DATABASE_DEFAULT)
            FROM sys.foreign_key_columns AS foreign_key_columns
            JOIN sys.columns AS parent_columns
              ON parent_columns.object_id = foreign_key_columns.parent_object_id
             AND parent_columns.column_id = foreign_key_columns.parent_column_id
            WHERE foreign_key_columns.constraint_object_id = foreign_keys.object_id
            ORDER BY foreign_key_columns.constraint_column_id
            FOR XML PATH(N''), TYPE
        ).value(N'.', N'nvarchar(max)'), 1, 1, N'') AS parent_columns
    ) AS actual_parent
    OUTER APPLY (
        SELECT STUFF((
            SELECT N',' + (referenced_columns.name COLLATE DATABASE_DEFAULT)
            FROM sys.foreign_key_columns AS foreign_key_columns
            JOIN sys.columns AS referenced_columns
              ON referenced_columns.object_id = foreign_key_columns.referenced_object_id
             AND referenced_columns.column_id = foreign_key_columns.referenced_column_id
            WHERE foreign_key_columns.constraint_object_id = foreign_keys.object_id
            ORDER BY foreign_key_columns.constraint_column_id
            FOR XML PATH(N''), TYPE
        ).value(N'.', N'nvarchar(max)'), 1, 1, N'') AS referenced_columns
    ) AS actual_referenced
    WHERE foreign_keys.object_id IS NULL
       OR ISNULL(referenced_tables.name COLLATE DATABASE_DEFAULT, N'') <> expected.referenced_table_name
       OR ISNULL(actual_parent.parent_columns COLLATE DATABASE_DEFAULT, N'') <> expected.parent_columns
       OR ISNULL(actual_referenced.referenced_columns COLLATE DATABASE_DEFAULT, N'') <> expected.referenced_columns
)
    THROW 51000, 'Keyword discovery foreign key definition mismatch.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.foreign_keys AS foreign_keys
    JOIN sys.tables AS tables ON tables.object_id = foreign_keys.parent_object_id
    LEFT JOIN @expected_foreign_keys AS expected
      ON expected.table_name = tables.name COLLATE DATABASE_DEFAULT
     AND expected.constraint_name = foreign_keys.name COLLATE DATABASE_DEFAULT
    WHERE SCHEMA_NAME(tables.schema_id) = N'dbo'
      AND tables.name IN (N'naver_keyword_discovery_snapshot', N'naver_keyword_discovery_result')
      AND expected.constraint_name IS NULL
)
    THROW 51000, 'Unexpected keyword discovery foreign key found.', 1;

DECLARE @expected_checks TABLE (
    table_name sysname NOT NULL,
    constraint_name sysname NOT NULL,
    normalized_definition nvarchar(4000) NOT NULL,
    PRIMARY KEY (table_name, constraint_name, normalized_definition)
);

INSERT INTO @expected_checks (table_name, constraint_name, normalized_definition)
VALUES
    (N'naver_keyword_discovery_snapshot', N'CK_naver_keyword_discovery_snapshot_device_type', N'device_typein(''mobile'',''pc'')'),
    (N'naver_keyword_discovery_snapshot', N'CK_naver_keyword_discovery_snapshot_device_type', N'device_type=''mobile''ordevice_type=''pc'''),
    (N'naver_keyword_discovery_snapshot', N'CK_naver_keyword_discovery_snapshot_device_type', N'device_type=''pc''ordevice_type=''mobile'''),
    (N'naver_keyword_discovery_snapshot', N'CK_naver_keyword_discovery_snapshot_source_type', N'source_typein(''excel'',''database'')'),
    (N'naver_keyword_discovery_snapshot', N'CK_naver_keyword_discovery_snapshot_source_type', N'source_type=''excel''orsource_type=''database'''),
    (N'naver_keyword_discovery_snapshot', N'CK_naver_keyword_discovery_snapshot_source_type', N'source_type=''database''orsource_type=''excel'''),
    (N'naver_keyword_discovery_snapshot', N'CK_naver_keyword_discovery_snapshot_latitude', N'latitudebetween-90and90'),
    (N'naver_keyword_discovery_snapshot', N'CK_naver_keyword_discovery_snapshot_latitude', N'latitude>=-90andlatitude<=90'),
    (N'naver_keyword_discovery_snapshot', N'CK_naver_keyword_discovery_snapshot_longitude', N'longitudebetween-180and180'),
    (N'naver_keyword_discovery_snapshot', N'CK_naver_keyword_discovery_snapshot_longitude', N'longitude>=-180andlongitude<=180'),
    (N'naver_keyword_discovery_snapshot', N'CK_naver_keyword_discovery_snapshot_observed_count', N'observed_result_count>=0'),
    (N'naver_keyword_discovery_result', N'CK_naver_keyword_discovery_result_raw_position', N'raw_position>=1'),
    (N'naver_keyword_discovery_result', N'CK_naver_keyword_discovery_result_organic_rank', N'organic_rankisnullororganic_rank>=1');

IF EXISTS (
    SELECT 1
    FROM (
        SELECT DISTINCT table_name, constraint_name
        FROM @expected_checks
    ) AS expected
    LEFT JOIN sys.tables AS tables
      ON tables.name COLLATE DATABASE_DEFAULT = expected.table_name
     AND SCHEMA_NAME(tables.schema_id) = N'dbo'
    LEFT JOIN sys.check_constraints AS check_constraints
      ON check_constraints.parent_object_id = tables.object_id
     AND check_constraints.name COLLATE DATABASE_DEFAULT = expected.constraint_name
    OUTER APPLY (
        SELECT LOWER(
            REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                check_constraints.definition COLLATE DATABASE_DEFAULT,
                N'[', N''),
                N']', N''),
                N'(', N''),
                N')', N''),
                N' ', N''),
                NCHAR(9), N''),
                NCHAR(10), N''),
                NCHAR(13), N'')
        ) AS normalized_definition
    ) AS actual_check
    WHERE check_constraints.object_id IS NULL
       OR NOT EXISTS (
            SELECT 1
            FROM @expected_checks AS alternative
            WHERE alternative.table_name = expected.table_name
              AND alternative.constraint_name = expected.constraint_name
              AND alternative.normalized_definition = actual_check.normalized_definition COLLATE DATABASE_DEFAULT
       )
)
    THROW 51000, 'Keyword discovery check constraint definition mismatch.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.check_constraints AS check_constraints
    JOIN sys.tables AS tables ON tables.object_id = check_constraints.parent_object_id
    LEFT JOIN (
        SELECT DISTINCT table_name, constraint_name
        FROM @expected_checks
    ) AS expected
      ON expected.table_name = tables.name COLLATE DATABASE_DEFAULT
     AND expected.constraint_name = check_constraints.name COLLATE DATABASE_DEFAULT
    WHERE SCHEMA_NAME(tables.schema_id) = N'dbo'
      AND tables.name IN (N'naver_keyword_discovery_snapshot', N'naver_keyword_discovery_result')
      AND expected.constraint_name IS NULL
)
    THROW 51000, 'Unexpected keyword discovery check constraint found.', 1;

DECLARE @expected_indexes TABLE (
    table_name sysname NOT NULL,
    index_name sysname NOT NULL,
    is_unique bit NOT NULL,
    is_primary_key bit NOT NULL,
    is_unique_constraint bit NOT NULL,
    has_filter bit NOT NULL,
    normalized_filter nvarchar(4000) NULL,
    key_columns nvarchar(4000) NOT NULL,
    PRIMARY KEY (table_name, index_name)
);

INSERT INTO @expected_indexes (
    table_name,
    index_name,
    is_unique,
    is_primary_key,
    is_unique_constraint,
    has_filter,
    normalized_filter,
    key_columns
)
VALUES
    (N'naver_keyword_discovery_snapshot', N'PK_naver_keyword_discovery_snapshot', 1, 1, 0, 0, NULL, N'snapshot_id'),
    (N'naver_keyword_discovery_snapshot', N'UQ_naver_keyword_discovery_snapshot_run_task', 1, 0, 1, 0, NULL, N'run_id,task_key'),
    (N'naver_keyword_discovery_snapshot', N'IX_naver_keyword_discovery_snapshot_query_collected_at', 0, 0, 0, 0, NULL, N'query,collected_at'),
    (N'naver_keyword_discovery_snapshot', N'IX_naver_keyword_discovery_snapshot_target_store_id_collected_at', 0, 0, 0, 0, NULL, N'target_store_id,collected_at'),
    (N'naver_keyword_discovery_snapshot', N'IX_naver_keyword_discovery_snapshot_collect_status_collected_at', 0, 0, 0, 0, NULL, N'collect_status,collected_at'),
    (N'naver_keyword_discovery_snapshot', N'IX_naver_keyword_discovery_snapshot_run_id', 0, 0, 0, 0, NULL, N'run_id'),
    (N'naver_keyword_discovery_result', N'PK_naver_keyword_discovery_result', 1, 1, 0, 0, NULL, N'snapshot_id,raw_position'),
    (N'naver_keyword_discovery_result', N'UX_naver_keyword_discovery_result_snapshot_organic_rank', 1, 0, 0, 1, N'organic_rankisnotnull', N'snapshot_id,organic_rank'),
    (N'naver_keyword_discovery_result', N'IX_naver_keyword_discovery_result_place_id_snapshot_id', 0, 0, 0, 0, NULL, N'place_id,snapshot_id'),
    (N'naver_keyword_discovery_result', N'IX_naver_keyword_discovery_result_snapshot_id_is_ad_organic_rank', 0, 0, 0, 0, NULL, N'snapshot_id,is_ad,organic_rank'),
    (N'naver_keyword_discovery_result', N'IX_naver_keyword_discovery_result_is_own_store_matched_store_id', 0, 0, 0, 0, NULL, N'is_own_store,matched_store_id');

IF EXISTS (
    SELECT 1
    FROM @expected_indexes AS expected
    LEFT JOIN sys.tables AS tables
      ON tables.name COLLATE DATABASE_DEFAULT = expected.table_name
     AND SCHEMA_NAME(tables.schema_id) = N'dbo'
    LEFT JOIN sys.indexes AS indexes
      ON indexes.object_id = tables.object_id
     AND indexes.name COLLATE DATABASE_DEFAULT = expected.index_name
    OUTER APPLY (
        SELECT STUFF((
            SELECT N',' + (columns.name COLLATE DATABASE_DEFAULT)
            FROM sys.index_columns AS index_columns
            JOIN sys.columns AS columns
              ON columns.object_id = index_columns.object_id
             AND columns.column_id = index_columns.column_id
            WHERE index_columns.object_id = indexes.object_id
              AND index_columns.index_id = indexes.index_id
              AND index_columns.key_ordinal > 0
            ORDER BY index_columns.key_ordinal
            FOR XML PATH(N''), TYPE
        ).value(N'.', N'nvarchar(max)'), 1, 1, N'') AS key_columns
    ) AS actual_keys
    OUTER APPLY (
        SELECT LOWER(
            REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                indexes.filter_definition COLLATE DATABASE_DEFAULT,
                N'[', N''),
                N']', N''),
                N'(', N''),
                N')', N''),
                N' ', N'')
        ) AS normalized_filter
    ) AS actual_filter
    WHERE indexes.index_id IS NULL
       OR indexes.is_unique <> expected.is_unique
       OR indexes.is_primary_key <> expected.is_primary_key
       OR indexes.is_unique_constraint <> expected.is_unique_constraint
       OR indexes.has_filter <> expected.has_filter
       OR ISNULL(actual_filter.normalized_filter COLLATE DATABASE_DEFAULT, N'') <> ISNULL(expected.normalized_filter, N'')
       OR ISNULL(actual_keys.key_columns COLLATE DATABASE_DEFAULT, N'') <> expected.key_columns
)
    THROW 51000, 'Keyword discovery index definition mismatch.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.indexes AS indexes
    JOIN sys.tables AS tables ON tables.object_id = indexes.object_id
    LEFT JOIN @expected_indexes AS expected
      ON expected.table_name = tables.name COLLATE DATABASE_DEFAULT
     AND expected.index_name = indexes.name COLLATE DATABASE_DEFAULT
    WHERE SCHEMA_NAME(tables.schema_id) = N'dbo'
      AND tables.name IN (N'naver_keyword_discovery_snapshot', N'naver_keyword_discovery_result')
      AND indexes.index_id > 0
      AND expected.index_name IS NULL
)
    THROW 51000, 'Unexpected keyword discovery index found.', 1;

SELECT
    DB_NAME() AS database_name,
    2 AS verified_table_count,
    (SELECT COUNT(*) FROM @expected_columns) AS verified_column_count,
    (SELECT COUNT(*) FROM @expected_indexes) AS verified_index_count;
