/* 02: 배민 기준점-경쟁점-배달팁 원문 추출
   PK 없는 하위 테이블의 완전 중복은 SELECT DISTINCT로 제거한다. */
SET NOCOUNT ON;

WITH rival AS (
    SELECT DISTINCT
        CONVERT(varchar(255), seed_shop_number) AS seed_shop_number,
        CONVERT(varchar(255), shop_number) AS rival_shop_number,
        collect_date_kst AS snapshot_date,
        category,
        ranking AS rival_rank,
        ranking_minimum_order_price AS minimum_order_amount,
        is_baemin_one,
        shop_name AS rival_shop_name
    FROM yuksudang_delivery.dbo.bae_rank_rival
),
fee_raw AS (
    SELECT DISTINCT seed_shop_number, shop_number, collect_date_kst, is_baemin_one,
           'ORDER_AMOUNT' AS condition_type, name, content, description
    FROM yuksudang_delivery.dbo.bae_rank_rival_delivery_tip_by_order_amount
    UNION
    SELECT DISTINCT seed_shop_number, shop_number, collect_date_kst, is_baemin_one,
           'REGION', name, content, description
    FROM yuksudang_delivery.dbo.bae_rank_rival_delivery_tip_by_region
    UNION
    SELECT DISTINCT seed_shop_number, shop_number, collect_date_kst, is_baemin_one,
           'ETC', name, content, description
    FROM yuksudang_delivery.dbo.bae_rank_rival_delivery_tip_by_etc
)
SELECT
    'BAE' AS platform,
    r.seed_shop_number,
    r.rival_shop_number,
    r.rival_shop_name,
    r.snapshot_date,
    r.category,
    r.rival_rank,
    r.minimum_order_amount,
    r.is_baemin_one AS membership_flag,
    f.condition_type,
    CONCAT_WS(N' | ', f.name, f.content, f.description) AS raw_text
FROM rival AS r
JOIN fee_raw AS f
  ON CONVERT(varchar(255), f.seed_shop_number) = r.seed_shop_number
 AND CONVERT(varchar(255), f.shop_number) = r.rival_shop_number
 AND f.collect_date_kst = r.snapshot_date
 AND ISNULL(f.is_baemin_one, 0) = ISNULL(r.is_baemin_one, 0);

