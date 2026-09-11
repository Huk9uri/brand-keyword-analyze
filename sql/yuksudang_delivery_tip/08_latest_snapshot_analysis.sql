/* 육수당 경쟁점 배달팁 최신 스냅샷 실행 분석
   기준일: 2026-08-20 (실행 전 MAX 수집일과 일치 여부 재확인)
   결과셋: SUMMARY_KPI, STORE_PRIORITY, EXCLUDED_OWN_LISTING, PARSE_QUALITY
*/
SET NOCOUNT ON;
DECLARE @snapshot_date date = '2026-08-20';

DROP TABLE IF EXISTS #scenario;
CREATE TABLE #scenario (scenario_id varchar(20), order_amount int);
INSERT #scenario VALUES ('A15000',15000),('A20000',20000),('A25000',25000),('A30000',30000);

/* ---------- 배민: 주문금액 조건표를 숫자로 구조화 ---------- */
WITH raw AS (
    SELECT DISTINCT seed_shop_number, shop_number, collect_date_kst, ISNULL(is_baemin_one,0) is_baemin_one,
           name, content, description,
           REPLACE(REPLACE(REPLACE(name,N',',N''),N'원 이상',N''),N' ',N'') amount_text,
           REPLACE(REPLACE(REPLACE(content,N',',N''),N'원',N''),N' ',N'') fee_text
    FROM yuksudang_delivery.dbo.bae_rank_rival_delivery_tip_by_order_amount
    WHERE collect_date_kst=@snapshot_date
), parsed AS (
    SELECT *, TRY_CONVERT(int,amount_text) threshold_amount,
           CASE WHEN fee_text=N'무료' THEN 0 ELSE TRY_CONVERT(int,fee_text) END delivery_fee
    FROM raw
)
SELECT *, CASE WHEN threshold_amount IS NOT NULL AND delivery_fee IS NOT NULL THEN 'SUCCESS' ELSE 'FAILED' END parse_status
INTO #bae_fee
FROM parsed;

WITH rival AS (
    SELECT DISTINCT seed_shop_number,shop_number,shop_name,category,ISNULL(is_baemin_one,0) is_baemin_one
    FROM yuksudang_delivery.dbo.bae_rank_rival
    WHERE collect_date_kst=@snapshot_date
), candidate AS (
    SELECT r.seed_shop_number,r.shop_number,r.shop_name,r.category,r.is_baemin_one,
           s.scenario_id,s.order_amount,f.description,f.delivery_fee,f.threshold_amount,
           ROW_NUMBER() OVER (
             PARTITION BY r.seed_shop_number,r.shop_number,r.category,r.is_baemin_one,s.scenario_id,ISNULL(f.description,N'')
             ORDER BY f.threshold_amount DESC
           ) rn
    FROM rival r CROSS JOIN #scenario s
    JOIN #bae_fee f ON f.seed_shop_number=r.seed_shop_number AND f.shop_number=r.shop_number
                   AND f.is_baemin_one=r.is_baemin_one AND f.parse_status='SUCCESS'
                   AND f.threshold_amount<=s.order_amount
), selected AS (
    SELECT * FROM candidate WHERE rn=1
), own AS (
    SELECT seed_shop_number,category,is_baemin_one,scenario_id,description,
           MAX(shop_name) own_shop_name,MAX(delivery_fee) own_fee
    FROM selected
    WHERE CONVERT(varchar(255),shop_number)=CONVERT(varchar(255),seed_shop_number)
      AND shop_name LIKE N'%육수당%'
    GROUP BY seed_shop_number,category,is_baemin_one,scenario_id,description
), competitor AS (
    SELECT s.*, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY delivery_fee) OVER
        (PARTITION BY seed_shop_number,category,is_baemin_one,scenario_id,description) competitor_median_fee
    FROM selected s
    WHERE CONVERT(varchar(255),shop_number)<>CONVERT(varchar(255),seed_shop_number)
), comp_summary AS (
    SELECT seed_shop_number,category,is_baemin_one,scenario_id,description,
           MAX(competitor_median_fee) competitor_median_fee,
           COUNT(DISTINCT shop_number) competitor_count,
           AVG(CASE WHEN delivery_fee=0 THEN 1.0 ELSE 0.0 END) free_delivery_ratio
    FROM competitor
    GROUP BY seed_shop_number,category,is_baemin_one,scenario_id,description
)
SELECT 'BAE' platform,o.seed_shop_number,o.own_shop_name,o.category,o.scenario_id,
       o.description delivery_mode,CONVERT(float,o.own_fee) own_fee,
       CONVERT(float,c.competitor_median_fee) competitor_median_fee,
       CONVERT(float,o.own_fee-c.competitor_median_fee) fee_gap,
       c.free_delivery_ratio,c.competitor_count
INTO #metrics
FROM own o JOIN comp_summary c ON c.seed_shop_number=o.seed_shop_number AND c.category=o.category
 AND c.is_baemin_one=o.is_baemin_one AND c.scenario_id=o.scenario_id
 AND ISNULL(c.description,N'')=ISNULL(o.description,N'')
WHERE c.competitor_count>=5;

/* ---------- 쿠팡이츠: 표시 배달비 범위의 하한·상한 구조화 ---------- */
WITH raw AS (
    SELECT DISTINCT shop_number,collect_date_kst,[text] raw_text,
      REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM([text])),N'배달비',N''),N',',N''),N'원',N''),N' ',N''),N'-',N'~') compact
    FROM yuksudang_delivery.dbo.eat_rank_rival_delivery_fee_info
    WHERE collect_date_kst=@snapshot_date
), parsed AS (
    SELECT *,CHARINDEX(N'~',compact) split_at FROM raw
)
SELECT *,
  TRY_CONVERT(int,CASE WHEN split_at>0 THEN LEFT(compact,split_at-1) ELSE compact END) fee_min,
  TRY_CONVERT(int,CASE WHEN split_at>0 THEN SUBSTRING(compact,split_at+1,30) ELSE compact END) fee_max
INTO #eat_fee
FROM parsed;

WITH rival AS (
    SELECT DISTINCT CONVERT(varchar(255),CONVERT(decimal(38,0),request_shop_number)) seed_shop_number,
      CONVERT(varchar(255),shop_number) shop_number,name,CONVERT(varchar(50),request_category_id) category
    FROM yuksudang_delivery.dbo.eat_rank_rival
    WHERE collect_date_kst=@snapshot_date
), joined AS (
    SELECT r.*,f.fee_min,f.fee_max
    FROM rival r JOIN #eat_fee f ON f.shop_number=r.shop_number
    WHERE f.fee_min IS NOT NULL AND f.fee_max IS NOT NULL
), own AS (
    SELECT seed_shop_number,category,MAX(name) own_shop_name,MAX(fee_min) own_fee_min,MAX(fee_max) own_fee_max
    FROM joined
    WHERE TRY_CONVERT(decimal(38,0),shop_number)=TRY_CONVERT(decimal(38,0),seed_shop_number)
      AND name LIKE N'%육수당%'
    GROUP BY seed_shop_number,category
), competitor AS (
    SELECT *,
      PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY fee_min) OVER (PARTITION BY seed_shop_number,category) median_min,
      PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY fee_max) OVER (PARTITION BY seed_shop_number,category) median_max
    FROM joined
    WHERE TRY_CONVERT(decimal(38,0),shop_number)<>TRY_CONVERT(decimal(38,0),seed_shop_number)
), comp_summary AS (
    SELECT seed_shop_number,category,MAX(median_min) median_min,MAX(median_max) median_max,
      COUNT(DISTINCT shop_number) competitor_count,
      AVG(CASE WHEN fee_min=0 THEN 1.0 ELSE 0.0 END) free_delivery_ratio
    FROM competitor GROUP BY seed_shop_number,category
)
INSERT #metrics(platform,seed_shop_number,own_shop_name,category,scenario_id,delivery_mode,
 own_fee,competitor_median_fee,fee_gap,free_delivery_ratio,competitor_count)
SELECT 'EAT',o.seed_shop_number,o.own_shop_name,o.category,'DISPLAY_MIN','표시배달비 하한',o.own_fee_min,
 c.median_min,o.own_fee_min-c.median_min,c.free_delivery_ratio,c.competitor_count
FROM own o JOIN comp_summary c ON c.seed_shop_number=o.seed_shop_number AND c.category=o.category
WHERE c.competitor_count>=5
UNION ALL
SELECT 'EAT',o.seed_shop_number,o.own_shop_name,o.category,'DISPLAY_MAX','표시배달비 상한',o.own_fee_max,
 c.median_max,o.own_fee_max-c.median_max,c.free_delivery_ratio,c.competitor_count
FROM own o JOIN comp_summary c ON c.seed_shop_number=o.seed_shop_number AND c.category=o.category
WHERE c.competitor_count>=5;

/* SUMMARY_KPI */
SELECT 'SUMMARY_KPI' result_set,platform,scenario_id,delivery_mode,
 COUNT(*) comparable_store_scenarios,COUNT(DISTINCT seed_shop_number) comparable_stores,
 CAST(AVG(own_fee) AS decimal(10,1)) avg_own_fee,
 CAST(AVG(competitor_median_fee) AS decimal(10,1)) avg_competitor_median_fee,
 CAST(AVG(fee_gap) AS decimal(10,1)) avg_fee_gap,
 CAST(AVG(CASE WHEN fee_gap>0 THEN 1.0 ELSE 0.0 END) AS decimal(8,4)) expensive_ratio,
 CAST(AVG(free_delivery_ratio) AS decimal(8,4)) avg_free_delivery_ratio
FROM #metrics GROUP BY platform,scenario_id,delivery_mode ORDER BY platform,scenario_id,delivery_mode;

/* STORE_PRIORITY */
SELECT TOP 100 'STORE_PRIORITY' result_set,platform,seed_shop_number,own_shop_name,category,scenario_id,delivery_mode,
 own_fee,competitor_median_fee,fee_gap,CAST(free_delivery_ratio AS decimal(8,4)) free_delivery_ratio,competitor_count,
 CAST(CASE WHEN fee_gap<=0 THEN 0 WHEN fee_gap>=3000 THEN 40 ELSE fee_gap/3000.0*40 END
      + CASE WHEN free_delivery_ratio>1 THEN 15 ELSE free_delivery_ratio*15 END AS decimal(6,2)) priority_score
FROM #metrics ORDER BY priority_score DESC,fee_gap DESC,competitor_count DESC;

/* EXCLUDED_OWN_LISTING: 기준점 ID의 자사 노출명이 육수당이 아닌 경우 */
SELECT 'EXCLUDED_OWN_LISTING' result_set,'BAE' platform,seed_shop_number,shop_number,shop_name own_listing_name,category
FROM (SELECT DISTINCT seed_shop_number,shop_number,shop_name,category FROM yuksudang_delivery.dbo.bae_rank_rival
      WHERE collect_date_kst=@snapshot_date AND CONVERT(varchar(255),shop_number)=CONVERT(varchar(255),seed_shop_number)) x
WHERE shop_name NOT LIKE N'%육수당%'
UNION ALL
SELECT 'EXCLUDED_OWN_LISTING','EAT',CONVERT(varchar(255),CONVERT(decimal(38,0),request_shop_number)),shop_number,name,
       CONVERT(varchar(50),request_category_id)
FROM (SELECT DISTINCT request_shop_number,shop_number,name,request_category_id FROM yuksudang_delivery.dbo.eat_rank_rival
      WHERE collect_date_kst=@snapshot_date AND TRY_CONVERT(decimal(38,0),shop_number)=request_shop_number) x
WHERE name NOT LIKE N'%육수당%';

/* PARSE_QUALITY */
SELECT 'PARSE_QUALITY' result_set,'BAE' platform,parse_status,COUNT(*) rows
FROM #bae_fee GROUP BY parse_status
UNION ALL
SELECT 'PARSE_QUALITY','EAT',CASE WHEN fee_min IS NOT NULL AND fee_max IS NOT NULL THEN 'SUCCESS' ELSE 'FAILED' END,COUNT(*)
FROM #eat_fee GROUP BY CASE WHEN fee_min IS NOT NULL AND fee_max IS NOT NULL THEN 'SUCCESS' ELSE 'FAILED' END;

