/* 03: 쿠팡이츠 기준점-경쟁점-배달비 원문 추출
   request_shop_number(DECIMAL)는 문자열로 표준화한 뒤 기준점 키로 사용한다. */
SET NOCOUNT ON;

WITH rival AS (
    SELECT DISTINCT
        CONVERT(varchar(255), CONVERT(decimal(38,0), request_shop_number)) AS seed_shop_number,
        CONVERT(varchar(255), shop_number) AS rival_shop_number,
        collect_date_kst AS snapshot_date,
        distance_km,
        CONVERT(decimal(18,0), minimum_order_price_for_delivery) AS minimum_order_amount,
        CONVERT(int, [rank]) AS rival_rank,
        is_wow_store AS membership_flag,
        name AS rival_shop_name,
        request_category_id
    FROM yuksudang_delivery.dbo.eat_rank_rival
),
fee_raw AS (
    SELECT DISTINCT
        CONVERT(varchar(255), shop_number) AS rival_shop_number,
        collect_date_kst AS snapshot_date,
        [text] AS raw_text
    FROM yuksudang_delivery.dbo.eat_rank_rival_delivery_fee_info
)
SELECT
    'EAT' AS platform,
    r.seed_shop_number,
    r.rival_shop_number,
    r.rival_shop_name,
    r.snapshot_date,
    r.request_category_id AS category,
    r.distance_km,
    r.minimum_order_amount,
    r.rival_rank,
    r.membership_flag,
    'DISPLAY_FEE' AS condition_type,
    f.raw_text
FROM rival AS r
JOIN fee_raw AS f
  ON f.rival_shop_number = r.rival_shop_number
 AND f.snapshot_date = r.snapshot_date;

