SET NOCOUNT ON;
SET ANSI_NULLS ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET ARITHABORT ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET QUOTED_IDENTIFIER ON;
SET NUMERIC_ROUNDABORT OFF;

IF OBJECT_ID(N'dbo.naver_place_keyword_snapshot', N'U') IS NULL
    THROW 51000, 'Missing dbo.naver_place_keyword_snapshot.', 1;

IF OBJECT_ID(N'dbo.naver_place_keyword_result', N'U') IS NULL
    THROW 51000, 'Missing dbo.naver_place_keyword_result.', 1;

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
    table_name, column_name, type_name, max_length, precision_value, scale_value, is_nullable, is_identity
)
VALUES
    (N'naver_place_keyword_snapshot', N'snapshot_id', N'bigint', 8, 19, 0, 0, 1),
    (N'naver_place_keyword_snapshot', N'run_id', N'uniqueidentifier', 16, 0, 0, 0, 0),
    (N'naver_place_keyword_snapshot', N'rank_run_id', N'uniqueidentifier', 16, 0, 0, 0, 0),
    (N'naver_place_keyword_snapshot', N'place_id', N'varchar', 50, 0, 0, 0, 0),
    (N'naver_place_keyword_snapshot', N'place_name', N'nvarchar', 600, 0, 0, 0, 0),
    (N'naver_place_keyword_snapshot', N'source_url', N'nvarchar', 4000, 0, 0, 0, 0),
    (N'naver_place_keyword_snapshot', N'collect_status', N'varchar', 30, 0, 0, 0, 0),
    (N'naver_place_keyword_snapshot', N'collect_method', N'varchar', 20, 0, 0, 0, 0),
    (N'naver_place_keyword_snapshot', N'content_hash', N'char', 64, 0, 0, 1, 0),
    (N'naver_place_keyword_snapshot', N'is_changed', N'bit', 1, 1, 0, 0, 0),
    (N'naver_place_keyword_snapshot', N'effective_snapshot_id', N'bigint', 8, 19, 0, 1, 0),
    (N'naver_place_keyword_snapshot', N'keyword_count', N'smallint', 2, 5, 0, 0, 0),
    (N'naver_place_keyword_snapshot', N'parser_version', N'varchar', 30, 0, 0, 0, 0),
    (N'naver_place_keyword_snapshot', N'collect_msg', N'nvarchar', 2000, 0, 0, 1, 0),
    (N'naver_place_keyword_snapshot', N'checked_at', N'datetime2', 7, 23, 3, 0, 0),
    (N'naver_place_keyword_result', N'snapshot_id', N'bigint', 8, 19, 0, 0, 0),
    (N'naver_place_keyword_result', N'keyword_order', N'smallint', 2, 5, 0, 0, 0),
    (N'naver_place_keyword_result', N'raw_keyword', N'nvarchar', 510, 0, 0, 0, 0),
    (N'naver_place_keyword_result', N'normalized_keyword', N'nvarchar', 510, 0, 0, 0, 0);

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
    THROW 51001, 'Place keyword column definition mismatch.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.tables AS tables
    JOIN sys.columns AS columns ON columns.object_id = tables.object_id
    LEFT JOIN @expected_columns AS expected
      ON expected.table_name = tables.name COLLATE DATABASE_DEFAULT
     AND expected.column_name = columns.name COLLATE DATABASE_DEFAULT
    WHERE SCHEMA_NAME(tables.schema_id) = N'dbo'
      AND tables.name IN (N'naver_place_keyword_snapshot', N'naver_place_keyword_result')
      AND expected.column_name IS NULL
)
    THROW 51002, 'Unexpected place keyword column found.', 1;

DECLARE @expected_key_constraints TABLE (
    table_name sysname NOT NULL,
    constraint_name sysname NOT NULL,
    constraint_type char(2) NOT NULL,
    PRIMARY KEY (table_name, constraint_name)
);

INSERT INTO @expected_key_constraints (table_name, constraint_name, constraint_type)
VALUES
    (N'naver_place_keyword_snapshot', N'PK_naver_place_keyword_snapshot', N'PK'),
    (N'naver_place_keyword_snapshot', N'UQ_naver_place_keyword_snapshot_run_place', N'UQ'),
    (N'naver_place_keyword_result', N'UQ_naver_place_keyword_result_snapshot_keyword_order', N'UQ');

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
    THROW 51003, 'Place keyword key constraint mismatch.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.key_constraints AS key_constraints
    JOIN sys.tables AS tables ON tables.object_id = key_constraints.parent_object_id
    LEFT JOIN @expected_key_constraints AS expected
      ON expected.table_name = tables.name COLLATE DATABASE_DEFAULT
     AND expected.constraint_name = key_constraints.name COLLATE DATABASE_DEFAULT
    WHERE SCHEMA_NAME(tables.schema_id) = N'dbo'
      AND tables.name IN (N'naver_place_keyword_snapshot', N'naver_place_keyword_result')
      AND expected.constraint_name IS NULL
)
    THROW 51004, 'Unexpected place keyword key constraint found.', 1;

DECLARE @expected_foreign_keys TABLE (
    table_name sysname NOT NULL,
    constraint_name sysname NOT NULL,
    referenced_table_name sysname NOT NULL,
    parent_columns nvarchar(4000) NOT NULL,
    referenced_columns nvarchar(4000) NOT NULL,
    PRIMARY KEY (table_name, constraint_name)
);

INSERT INTO @expected_foreign_keys (
    table_name, constraint_name, referenced_table_name, parent_columns, referenced_columns
)
VALUES
    (N'naver_place_keyword_snapshot', N'FK_naver_place_keyword_snapshot_effective_snapshot', N'naver_place_keyword_snapshot', N'effective_snapshot_id', N'snapshot_id'),
    (N'naver_place_keyword_result', N'FK_naver_place_keyword_result_snapshot', N'naver_place_keyword_snapshot', N'snapshot_id', N'snapshot_id');

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
       OR foreign_keys.is_disabled <> 0
       OR foreign_keys.is_not_trusted <> 0
)
    THROW 51005, 'Place keyword foreign key definition mismatch.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.foreign_keys AS foreign_keys
    JOIN sys.tables AS tables ON tables.object_id = foreign_keys.parent_object_id
    LEFT JOIN @expected_foreign_keys AS expected
      ON expected.table_name = tables.name COLLATE DATABASE_DEFAULT
     AND expected.constraint_name = foreign_keys.name COLLATE DATABASE_DEFAULT
    WHERE SCHEMA_NAME(tables.schema_id) = N'dbo'
      AND tables.name IN (N'naver_place_keyword_snapshot', N'naver_place_keyword_result')
      AND expected.constraint_name IS NULL
)
    THROW 51006, 'Unexpected place keyword foreign key found.', 1;

DECLARE @expected_checks TABLE (
    table_name sysname NOT NULL,
    constraint_name sysname NOT NULL,
    normalized_definition nvarchar(4000) NOT NULL,
    PRIMARY KEY (table_name, constraint_name, normalized_definition)
);

INSERT INTO @expected_checks (table_name, constraint_name, normalized_definition)
VALUES
    (N'naver_place_keyword_snapshot', N'CK_naver_place_keyword_snapshot_status', N''),
    (N'naver_place_keyword_snapshot', N'CK_naver_place_keyword_snapshot_keyword_count', N'keyword_count>=0'),
    (N'naver_place_keyword_result', N'CK_naver_place_keyword_result_keyword_order', N'keyword_order>=1');

DECLARE @expected_status_values TABLE (
    status_value varchar(30) NOT NULL PRIMARY KEY
);

INSERT INTO @expected_status_values (status_value)
VALUES
    (N'SUCCESS'),
    (N'EMPTY'),
    (N'BLOCKED'),
    (N'LOAD_TIMEOUT'),
    (N'PLACE_MISMATCH'),
    (N'PARSE_ERROR');

DECLARE @expected_status_terms TABLE (
    status_value varchar(30) NOT NULL PRIMARY KEY,
    normalized_or_term nvarchar(100) NOT NULL
);

INSERT INTO @expected_status_terms (status_value, normalized_or_term)
VALUES
    (N'SUCCESS', N'collect_status=''success'''),
    (N'EMPTY', N'collect_status=''empty'''),
    (N'BLOCKED', N'collect_status=''blocked'''),
    (N'LOAD_TIMEOUT', N'collect_status=''load_timeout'''),
    (N'PLACE_MISMATCH', N'collect_status=''place_mismatch'''),
    (N'PARSE_ERROR', N'collect_status=''parse_error''');

DECLARE @actual_status_definition nvarchar(4000) = (
    SELECT LOWER(
        REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
            check_constraints.definition COLLATE DATABASE_DEFAULT,
            N'[', N''), N']', N''), N'(', N''), N')', N''),
            N' ', N''), NCHAR(9), N''), NCHAR(10), N''), NCHAR(13), N'')
    )
    FROM sys.check_constraints AS check_constraints
    WHERE check_constraints.parent_object_id = OBJECT_ID(N'dbo.naver_place_keyword_snapshot')
      AND check_constraints.name COLLATE DATABASE_DEFAULT = N'CK_naver_place_keyword_snapshot_status'
      AND check_constraints.is_disabled = 0
      AND check_constraints.is_not_trusted = 0
);

DECLARE @actual_status_literal_count int = (
    (LEN(@actual_status_definition) - LEN(REPLACE(@actual_status_definition, N'''', N''))) / 2
);

DECLARE @actual_status_constraint_form varchar(2) = CASE
    WHEN LEFT(@actual_status_definition, LEN(N'collect_statusin')) = N'collect_statusin' THEN N'IN'
    WHEN LEFT(@actual_status_definition, LEN(N'collect_status=')) = N'collect_status=' THEN N'OR'
    ELSE NULL
END;

DECLARE @canonical_status_remainder nvarchar(4000) = @actual_status_definition;

IF @actual_status_constraint_form = N'IN'
BEGIN
    SET @canonical_status_remainder = STUFF(
        @canonical_status_remainder,
        1,
        LEN(N'collect_statusin'),
        N''
    );

    SET @canonical_status_remainder = REPLACE(@canonical_status_remainder, N'''success''', N'');
    SET @canonical_status_remainder = REPLACE(@canonical_status_remainder, N'''empty''', N'');
    SET @canonical_status_remainder = REPLACE(@canonical_status_remainder, N'''blocked''', N'');
    SET @canonical_status_remainder = REPLACE(@canonical_status_remainder, N'''load_timeout''', N'');
    SET @canonical_status_remainder = REPLACE(@canonical_status_remainder, N'''place_mismatch''', N'');
    SET @canonical_status_remainder = REPLACE(@canonical_status_remainder, N'''parse_error''', N'');
END;

IF @actual_status_constraint_form = N'OR'
BEGIN
    SET @canonical_status_remainder = REPLACE(@canonical_status_remainder, N'collect_status=''success''', N'');
    SET @canonical_status_remainder = REPLACE(@canonical_status_remainder, N'collect_status=''empty''', N'');
    SET @canonical_status_remainder = REPLACE(@canonical_status_remainder, N'collect_status=''blocked''', N'');
    SET @canonical_status_remainder = REPLACE(@canonical_status_remainder, N'collect_status=''load_timeout''', N'');
    SET @canonical_status_remainder = REPLACE(@canonical_status_remainder, N'collect_status=''place_mismatch''', N'');
    SET @canonical_status_remainder = REPLACE(@canonical_status_remainder, N'collect_status=''parse_error''', N'');
END;

IF @actual_status_definition IS NULL
   OR @actual_status_literal_count <> (SELECT COUNT(*) FROM @expected_status_values)
   OR @actual_status_constraint_form IS NULL
   OR EXISTS (
        SELECT 1
        FROM @expected_status_values AS expected_status
        WHERE LEN(@actual_status_definition) - LEN(
            REPLACE(
                @actual_status_definition,
                N'''' + LOWER(expected_status.status_value) + N'''',
                N''
            )
        ) <> LEN(N'''' + expected_status.status_value + N'''')
   )
   OR (@actual_status_constraint_form = N'IN'
       AND @canonical_status_remainder <> REPLICATE(
            N',',
            (SELECT COUNT(*) - 1 FROM @expected_status_values)
       ))
   OR (@actual_status_constraint_form = N'OR'
       AND @canonical_status_remainder <> REPLICATE(
            N'or',
            (SELECT COUNT(*) - 1 FROM @expected_status_terms)
       ))
    THROW 51007, 'Place keyword status check definition mismatch.', 1;

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
                N'[', N''), N']', N''), N'(', N''), N')', N''),
                N' ', N''), NCHAR(9), N''), NCHAR(10), N''), NCHAR(13), N'')
        ) AS normalized_definition
    ) AS actual_check
    WHERE expected.constraint_name <> N'CK_naver_place_keyword_snapshot_status'
      AND (
           check_constraints.object_id IS NULL
       OR NOT EXISTS (
            SELECT 1
            FROM @expected_checks AS alternative
            WHERE alternative.table_name = expected.table_name
              AND alternative.constraint_name = expected.constraint_name
              AND alternative.normalized_definition = actual_check.normalized_definition COLLATE DATABASE_DEFAULT
       )
       OR check_constraints.is_disabled <> 0
       OR check_constraints.is_not_trusted <> 0
      )
)
    THROW 51008, 'Place keyword check constraint definition mismatch.', 1;

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
      AND tables.name IN (N'naver_place_keyword_snapshot', N'naver_place_keyword_result')
      AND expected.constraint_name IS NULL
)
    THROW 51009, 'Unexpected place keyword check constraint found.', 1;

DECLARE @expected_indexes TABLE (
    table_name sysname NOT NULL,
    index_name sysname NOT NULL,
    is_unique bit NOT NULL,
    is_primary_key bit NOT NULL,
    is_unique_constraint bit NOT NULL,
    key_definition nvarchar(4000) NOT NULL,
    PRIMARY KEY (table_name, index_name)
);

INSERT INTO @expected_indexes (
    table_name, index_name, is_unique, is_primary_key, is_unique_constraint, key_definition
)
VALUES
    (N'naver_place_keyword_snapshot', N'PK_naver_place_keyword_snapshot', 1, 1, 0, N'snapshot_id'),
    (N'naver_place_keyword_snapshot', N'UQ_naver_place_keyword_snapshot_run_place', 1, 0, 1, N'run_id,place_id'),
    (N'naver_place_keyword_snapshot', N'IX_naver_place_keyword_snapshot_place_checked_at', 0, 0, 0, N'place_id,checked_at desc'),
    (N'naver_place_keyword_snapshot', N'IX_naver_place_keyword_snapshot_rank_run_id', 0, 0, 0, N'rank_run_id'),
    (N'naver_place_keyword_snapshot', N'IX_naver_place_keyword_snapshot_effective_snapshot_id', 0, 0, 0, N'effective_snapshot_id'),
    (N'naver_place_keyword_result', N'UQ_naver_place_keyword_result_snapshot_keyword_order', 1, 0, 1, N'snapshot_id,keyword_order'),
    (N'naver_place_keyword_result', N'IX_naver_place_keyword_result_snapshot_keyword_order', 0, 0, 0, N'snapshot_id,keyword_order');

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
                 + CASE WHEN index_columns.is_descending_key = 1 THEN N' desc' ELSE N'' END
            FROM sys.index_columns AS index_columns
            JOIN sys.columns AS columns
              ON columns.object_id = index_columns.object_id
             AND columns.column_id = index_columns.column_id
            WHERE index_columns.object_id = indexes.object_id
              AND index_columns.index_id = indexes.index_id
              AND index_columns.key_ordinal > 0
            ORDER BY index_columns.key_ordinal
            FOR XML PATH(N''), TYPE
        ).value(N'.', N'nvarchar(max)'), 1, 1, N'') AS key_definition
    ) AS actual_keys
    WHERE indexes.index_id IS NULL
       OR indexes.is_unique <> expected.is_unique
       OR indexes.is_primary_key <> expected.is_primary_key
       OR indexes.is_unique_constraint <> expected.is_unique_constraint
       OR ISNULL(actual_keys.key_definition COLLATE DATABASE_DEFAULT, N'') <> expected.key_definition
       OR indexes.is_disabled <> 0
)
    THROW 51010, 'Place keyword index definition mismatch.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.indexes AS indexes
    JOIN sys.tables AS tables ON tables.object_id = indexes.object_id
    LEFT JOIN @expected_indexes AS expected
      ON expected.table_name = tables.name COLLATE DATABASE_DEFAULT
     AND expected.index_name = indexes.name COLLATE DATABASE_DEFAULT
    WHERE SCHEMA_NAME(tables.schema_id) = N'dbo'
      AND tables.name IN (N'naver_place_keyword_snapshot', N'naver_place_keyword_result')
      AND indexes.index_id > 0
      AND expected.index_name IS NULL
)
    THROW 51011, 'Unexpected place keyword index found.', 1;

DECLARE @verified_table_count int = (
    SELECT COUNT(*)
    FROM sys.tables
    WHERE schema_id = SCHEMA_ID(N'dbo')
      AND name IN (N'naver_place_keyword_snapshot', N'naver_place_keyword_result')
);
DECLARE @verified_column_count int = (
    SELECT COUNT(*)
    FROM sys.columns AS columns
    JOIN sys.tables AS tables ON tables.object_id = columns.object_id
    WHERE SCHEMA_NAME(tables.schema_id) = N'dbo'
      AND tables.name IN (N'naver_place_keyword_snapshot', N'naver_place_keyword_result')
);
DECLARE @verified_constraint_count int = (
    SELECT COUNT(*)
    FROM sys.objects AS objects
    WHERE objects.parent_object_id IN (
        OBJECT_ID(N'dbo.naver_place_keyword_snapshot'),
        OBJECT_ID(N'dbo.naver_place_keyword_result')
    )
      AND objects.type IN ('PK', 'UQ', 'F', 'C')
);
DECLARE @verified_index_count int = (
    SELECT COUNT(*)
    FROM sys.indexes AS indexes
    WHERE indexes.object_id IN (
        OBJECT_ID(N'dbo.naver_place_keyword_snapshot'),
        OBJECT_ID(N'dbo.naver_place_keyword_result')
    )
      AND indexes.index_id > 0
);

IF @verified_table_count <> 2 THROW 51012, 'Place keyword table count mismatch.', 1;
IF @verified_column_count <> 19 THROW 51013, 'Place keyword column count mismatch.', 1;
IF @verified_constraint_count <> 8 THROW 51014, 'Place keyword constraint count mismatch.', 1;
IF @verified_index_count <> 7 THROW 51015, 'Place keyword index count mismatch.', 1;

SELECT
    DB_NAME() AS database_name,
    @verified_table_count AS verified_table_count,
    @verified_column_count AS verified_column_count,
    @verified_constraint_count AS verified_constraint_count,
    @verified_index_count AS verified_index_count;
