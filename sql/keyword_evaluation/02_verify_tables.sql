-- 읽기 전용 검증. 테이블이 있다고 해서 타입·제약 일치를 보장하지 않는다.
SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,CHARACTER_MAXIMUM_LENGTH,IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA='dbo' AND (TABLE_NAME LIKE 'naver_keyword_evaluation_%'
 OR TABLE_NAME='naver_keyword_search_volume_snapshot')
ORDER BY TABLE_NAME,ORDINAL_POSITION;
SELECT name,is_disabled,is_not_trusted FROM sys.foreign_keys
WHERE name LIKE 'FK_keyword_evaluation_%';
SELECT name,is_disabled,is_not_trusted FROM sys.check_constraints
WHERE name LIKE 'CK_keyword_%';
