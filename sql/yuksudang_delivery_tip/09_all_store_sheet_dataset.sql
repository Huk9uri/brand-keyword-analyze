/* 전매장 엑셀 시트용 평면 데이터
   최근 13개 완료 주차: 2026-05-18 이상, 2026-08-17 미만
   경쟁점 스냅샷: 배민 최신 수집일
*/
SET NOCOUNT ON;
DECLARE @start_date date='2026-05-18', @end_date date='2026-08-17';
DECLARE @snapshot_date date=(SELECT MAX(collect_date_kst) FROM yuksudang_delivery.dbo.bae_rank_rival);

WITH store_map AS (
    SELECT DISTINCT no,name
    FROM yuksudang_delivery.dbo.channel_group_store_info
    WHERE app_type='Baemin' AND status='OPERATING'
),
stores AS (
    SELECT DISTINCT name store_name FROM store_map
),
orders AS (
    SELECT m.name store_name,o.order_number,o.pay_amount,o.delivery_tip
    FROM yuksudang_delivery.dbo.bae_order o
    JOIN store_map m ON m.no=o.shop_number
    WHERE o.status='CLOSED' AND o.order_datetime>=@start_date AND o.order_datetime<@end_date
),
order_window AS (
    SELECT *,
      PERCENTILE_CONT(.5) WITHIN GROUP (ORDER BY delivery_tip) OVER (PARTITION BY store_name) median_fee
    FROM orders
),
actual AS (
    SELECT store_name,COUNT(*) order_count,AVG(pay_amount*1.0) avg_order_amount,
      AVG(delivery_tip*1.0) avg_fee,MAX(median_fee) median_fee,
      COUNT(delivery_tip)*1.0/NULLIF(COUNT(*),0) record_rate,
      AVG(CASE WHEN delivery_tip=0 THEN 1.0 WHEN delivery_tip IS NOT NULL THEN 0.0 END) free_rate
    FROM order_window GROUP BY store_name
),
sample_window AS (
    SELECT *,PERCENTILE_CONT(.5) WITHIN GROUP (ORDER BY delivery_tip) OVER (PARTITION BY store_name) sample_median
    FROM orders
    WHERE pay_amount>=15000 AND pay_amount<25000 AND delivery_tip IS NOT NULL
),
sample AS (
    SELECT store_name,COUNT(*) sample_count,MAX(sample_median) sample_median
    FROM sample_window GROUP BY store_name
),
order_dist AS (
    SELECT store_name,pay_amount,COUNT(*) weight
    FROM orders WHERE pay_amount>=15000 AND pay_amount<25000
    GROUP BY store_name,pay_amount
),
fee_raw AS (
    SELECT DISTINCT seed_shop_number,shop_number,ISNULL(is_baemin_one,0) is_baemin_one,
      description,name raw_condition,content raw_delivery_fee,
      REPLACE(REPLACE(name,N',',N''),N' ',N'') normalized_condition,
      REPLACE(REPLACE(REPLACE(content,N',',N''),N'원',N''),N' ',N'') normalized_fee
    FROM yuksudang_delivery.dbo.bae_rank_rival_delivery_tip_by_order_amount
    WHERE collect_date_kst=@snapshot_date
),
fee_parsed_base AS (
    SELECT *,
      CASE
        WHEN normalized_condition LIKE N'%~%미만' THEN 'RANGE_EXCLUSIVE'
        WHEN normalized_condition LIKE N'%원이상' THEN 'LOWER_OPEN'
        ELSE 'UNSUPPORTED'
      END parse_rule_id,
      CASE
        WHEN normalized_condition LIKE N'%~%미만'
          THEN TRY_CONVERT(int,LEFT(normalized_condition,CHARINDEX(N'~',normalized_condition)-1))
        WHEN normalized_condition LIKE N'%원이상'
          THEN TRY_CONVERT(int,REPLACE(normalized_condition,N'원이상',N''))
      END order_amount_min,
      CASE
        WHEN normalized_condition LIKE N'%~%미만'
          THEN TRY_CONVERT(int,REPLACE(SUBSTRING(normalized_condition,CHARINDEX(N'~',normalized_condition)+1,50),N'원미만',N''))
        ELSE NULL
      END order_amount_max,
      CASE WHEN normalized_fee=N'무료' THEN 0 ELSE TRY_CONVERT(int,normalized_fee) END fee
    FROM fee_raw
),
fee_parsed AS (
    SELECT *,
      CASE
        WHEN order_amount_min IS NULL THEN 'FAILED_MIN_AMOUNT'
        WHEN parse_rule_id='RANGE_EXCLUSIVE' AND order_amount_max IS NULL THEN 'FAILED_MAX_AMOUNT'
        WHEN fee IS NULL THEN 'FAILED_DELIVERY_FEE'
        WHEN order_amount_max IS NOT NULL AND order_amount_min>=order_amount_max THEN 'FAILED_INVALID_RANGE'
        ELSE 'SUCCESS'
      END parse_status
    FROM fee_parsed_base
),
seed_map AS (
    SELECT DISTINCT CONVERT(varchar(255),m.no) seed_shop_number,m.name store_name
    FROM store_map m
    JOIN yuksudang_delivery.dbo.bae_rank_rival r
      ON CONVERT(varchar(255),r.seed_shop_number)=CONVERT(varchar(255),m.no)
     AND r.collect_date_kst=@snapshot_date
),
expected_application AS (
    SELECT sm.store_name,f.seed_shop_number,f.shop_number,f.is_baemin_one,f.description,d.pay_amount,d.weight
    FROM seed_map sm
    JOIN (SELECT DISTINCT seed_shop_number,shop_number,is_baemin_one,description
          FROM fee_parsed WHERE parse_status='SUCCESS') f ON f.seed_shop_number=sm.seed_shop_number
      AND CONVERT(varchar(255),f.shop_number)<>CONVERT(varchar(255),f.seed_shop_number)
    JOIN order_dist d ON d.store_name=sm.store_name
),
candidate_group AS (
    SELECT e.store_name,e.seed_shop_number,e.shop_number,e.is_baemin_one,e.description,e.pay_amount,e.weight,
      MIN(f.fee) min_fee,MAX(f.fee) max_fee,COUNT(f.fee) matched_rows
    FROM expected_application e
    LEFT JOIN fee_parsed f ON f.seed_shop_number=e.seed_shop_number AND f.shop_number=e.shop_number
      AND f.is_baemin_one=e.is_baemin_one AND ISNULL(f.description,N'')=ISNULL(e.description,N'')
      AND f.parse_status='SUCCESS'
      AND e.pay_amount>=f.order_amount_min
      AND (f.order_amount_max IS NULL OR e.pay_amount<f.order_amount_max)
    GROUP BY e.store_name,e.seed_shop_number,e.shop_number,e.is_baemin_one,e.description,e.pay_amount,e.weight
),
application_quality AS (
    SELECT *,
      CASE
        WHEN matched_rows=0 THEN 'NO_APPLICABLE_RANGE'
        WHEN min_fee<>max_fee THEN 'AMBIGUOUS_OVERLAP'
        ELSE 'SUCCESS'
      END application_status
    FROM candidate_group
),
weighted_fee AS (
    SELECT store_name,description,min_fee fee,SUM(weight) weight
    FROM application_quality
    WHERE application_status='SUCCESS' AND description IN (N'가게배달',N'알뜰배달',N'한집배달')
    GROUP BY store_name,description,min_fee
),
weighted_rank AS (
    SELECT *,SUM(weight) OVER (PARTITION BY store_name,description ORDER BY fee ROWS UNBOUNDED PRECEDING) cum_weight,
      SUM(weight) OVER (PARTITION BY store_name,description) total_weight
    FROM weighted_fee
),
weighted_median AS (
    SELECT store_name,description,MIN(fee) weighted_median
    FROM weighted_rank WHERE cum_weight*2>=total_weight
    GROUP BY store_name,description
),
competitor AS (
    SELECT store_name,
      MAX(CASE WHEN description=N'가게배달' THEN weighted_median END) comp_store_fee,
      MAX(CASE WHEN description=N'알뜰배달' THEN weighted_median END) comp_economy_fee,
      MAX(CASE WHEN description=N'한집배달' THEN weighted_median END) comp_single_fee
    FROM weighted_median GROUP BY store_name
)
SELECT s.store_name,
  a.order_count,a.avg_order_amount,a.avg_fee,a.median_fee,a.record_rate,a.free_rate,
  CASE WHEN a.order_count IS NULL THEN N'분석기간 내 완료 배달주문 없음' ELSE N'' END left_note,
  p.sample_count,p.sample_median,c.comp_store_fee,c.comp_economy_fee,c.comp_single_fee,
  CASE WHEN ISNULL(p.sample_count,0)=0 THEN N'2만원 대표구간 배달팁 기록 주문 없음'
       WHEN p.sample_count<10 THEN CONCAT(N'2만원 대표구간 유효 표본 ',p.sample_count,N'건으로 판단 유보')
       ELSE N'' END diagnosis
FROM stores s
LEFT JOIN actual a ON a.store_name=s.store_name
LEFT JOIN sample p ON p.store_name=s.store_name
LEFT JOIN competitor c ON c.store_name=s.store_name
ORDER BY CASE WHEN a.order_count IS NULL THEN 1 ELSE 0 END,a.order_count DESC,s.store_name;
