/* 06: 점포·플랫폼·시나리오별 배달팁 경쟁력 지표
   입력 계약: #scenario_fee에 자사/경쟁점의 적용 배달비가 1행씩 있어야 한다.
   (platform, seed_shop_number, scenario_id, shop_number, is_own, delivery_fee) */
SET NOCOUNT ON;

WITH base AS (
    SELECT DISTINCT platform, seed_shop_number, scenario_id, shop_number, is_own, delivery_fee
    FROM #scenario_fee
    WHERE delivery_fee IS NOT NULL
), competitor AS (
    SELECT *,
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY delivery_fee)
            OVER (PARTITION BY platform, seed_shop_number, scenario_id) AS competitor_p25_fee,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY delivery_fee)
            OVER (PARTITION BY platform, seed_shop_number, scenario_id) AS competitor_median_fee,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY delivery_fee)
            OVER (PARTITION BY platform, seed_shop_number, scenario_id) AS competitor_p75_fee
    FROM base
    WHERE is_own = 0
), competitor_summary AS (
    SELECT platform, seed_shop_number, scenario_id,
        MAX(competitor_p25_fee) AS competitor_p25_fee,
        MAX(competitor_median_fee) AS competitor_median_fee,
        MAX(competitor_p75_fee) AS competitor_p75_fee,
        AVG(CASE WHEN delivery_fee = 0 THEN 1.0 ELSE 0.0 END) AS free_delivery_ratio,
        COUNT(*) AS competitor_count
    FROM competitor
    GROUP BY platform, seed_shop_number, scenario_id
), own_fee AS (
    SELECT platform, seed_shop_number, scenario_id, MAX(delivery_fee) AS own_delivery_fee
    FROM base WHERE is_own = 1
    GROUP BY platform, seed_shop_number, scenario_id
)
SELECT
    o.platform, o.seed_shop_number, o.scenario_id, o.own_delivery_fee,
    c.competitor_p25_fee, c.competitor_median_fee, c.competitor_p75_fee,
    o.own_delivery_fee - c.competitor_median_fee AS fee_gap,
    CAST(AVG(CASE WHEN b.delivery_fee <= o.own_delivery_fee THEN 1.0 ELSE 0.0 END) AS decimal(8,4)) AS own_fee_percentile,
    c.free_delivery_ratio,
    CAST(AVG(CASE WHEN b.delivery_fee < o.own_delivery_fee THEN 1.0 ELSE 0.0 END) AS decimal(8,4)) AS cheaper_competitor_ratio,
    c.competitor_count
FROM own_fee AS o
JOIN competitor_summary AS c
  ON c.platform = o.platform AND c.seed_shop_number = o.seed_shop_number AND c.scenario_id = o.scenario_id
JOIN base AS b
  ON b.platform = o.platform AND b.seed_shop_number = o.seed_shop_number
 AND b.scenario_id = o.scenario_id AND b.is_own = 0
GROUP BY o.platform, o.seed_shop_number, o.scenario_id, o.own_delivery_fee,
         c.competitor_p25_fee, c.competitor_median_fee, c.competitor_p75_fee,
         c.free_delivery_ratio, c.competitor_count;

