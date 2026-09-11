/* 04: 배달팁 텍스트 패턴 및 1차 파싱 품질 진단
   입력 계약: #fee_raw(platform, seed_shop_number, rival_shop_number, snapshot_date,
                      condition_type, raw_text). 02와 03 결과를 적재 후 실행한다.
   인식하지 못한 값은 0원으로 보정하지 않고 FAILED로 남긴다. */
SET NOCOUNT ON;

WITH normalized AS (
    SELECT DISTINCT
        platform, seed_shop_number, rival_shop_number, snapshot_date, condition_type, raw_text,
        REPLACE(REPLACE(REPLACE(LOWER(LTRIM(RTRIM(raw_text))), N',', N''), N'원', N''), N' ', N'') AS compact_text
    FROM #fee_raw
), parsed AS (
    SELECT *,
        CASE
            WHEN compact_text LIKE N'%무료%' OR compact_text IN (N'0', N'0~0') THEN 0
            WHEN PATINDEX(N'%[0-9]%', compact_text) > 0 THEN
                TRY_CONVERT(int, SUBSTRING(
                    compact_text,
                    PATINDEX(N'%[0-9]%', compact_text),
                    PATINDEX(N'%[^0-9]%', SUBSTRING(compact_text, PATINDEX(N'%[0-9]%', compact_text), 30) + N'X') - 1
                ))
            ELSE NULL
        END AS delivery_fee
    FROM normalized
), classified AS (
    SELECT *,
        CASE
            WHEN raw_text IS NULL OR LTRIM(RTRIM(raw_text)) = N'' THEN 'FAILED'
            WHEN delivery_fee IS NOT NULL AND compact_text LIKE N'%~%' THEN 'PARTIAL'
            WHEN delivery_fee IS NOT NULL THEN 'SUCCESS'
            ELSE 'FAILED'
        END AS parse_status
    FROM parsed
)
SELECT
    platform, condition_type, raw_text, delivery_fee, parse_status,
    COUNT(*) AS row_count,
    CAST(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY platform) AS decimal(6,2)) AS platform_share_pct
FROM classified
GROUP BY platform, condition_type, raw_text, delivery_fee, parse_status
ORDER BY platform, parse_status DESC, row_count DESC;

