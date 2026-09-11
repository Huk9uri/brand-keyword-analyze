/* 07: 개선 우선순위
   입력 계약: #competitiveness_metrics는 06 결과이며 표본 5개 미만은 권고 대상에서 제외한다. */
SET NOCOUNT ON;

WITH scored AS (
    SELECT *,
        CASE
            WHEN fee_gap <= 0 THEN 0
            WHEN fee_gap >= 3000 THEN 1.0
            ELSE fee_gap / 3000.0
        END * 40
      + own_fee_percentile * 25
      + cheaper_competitor_ratio * 20
      + free_delivery_ratio * 15 AS priority_score
    FROM #competitiveness_metrics
    WHERE competitor_count >= 5
)
SELECT
    platform, seed_shop_number, scenario_id, own_delivery_fee,
    competitor_median_fee, fee_gap, own_fee_percentile,
    free_delivery_ratio, cheaper_competitor_ratio, competitor_count,
    CAST(priority_score AS decimal(6,2)) AS priority_score,
    CASE
        WHEN priority_score >= 70 THEN 'P1_IMMEDIATE_REVIEW'
        WHEN priority_score >= 50 THEN 'P2_REVIEW'
        ELSE 'P3_MONITOR'
    END AS recommendation,
    CASE WHEN fee_gap > 0 THEN competitor_median_fee ELSE own_delivery_fee END AS suggested_fee_ceiling
FROM scored
ORDER BY priority_score DESC, fee_gap DESC;
