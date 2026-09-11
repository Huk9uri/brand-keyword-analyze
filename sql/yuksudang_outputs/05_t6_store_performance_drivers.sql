/* 5. T6: 2026 매장별 성과요인 */
SET NOCOUNT ON;
WITH event_calendar AS (SELECT CONVERT(date,'20260629') event_start,CONVERT(date,'20260816') event_end),
store_rank AS (
 SELECT NO_POSCONNCODE store_code,CD_STORE,NM_STORE,
 ROW_NUMBER() OVER(PARTITION BY NO_POSCONNCODE ORDER BY ISNULL(DT_UPDDATE,DT_INSDATE) DESC,CD_STORE DESC) rn
 FROM SEIERP_HD.dbo.FROP_STORE
 WHERE CD_CORP='02' AND CD_BRAND='002' AND CD_STORETYPE='002' AND NULLIF(NO_POSCONNCODE,'') IS NOT NULL
), sales AS (
 SELECT a.store_code,MAX(a.store_name) acorn_store_name,SUM(a.net_amt) event_sales,
 SUM(CASE WHEN a.channel='Hall' THEN a.net_amt ELSE 0 END) hall_sales,
 SUM(CASE WHEN a.channel='Delivery' THEN a.net_amt ELSE 0 END) delivery_sales,
 CAST(SUM(CASE WHEN a.channel='Delivery' THEN a.net_amt ELSE 0 END)*1.0/NULLIF(SUM(a.net_amt),0) AS decimal(12,4)) delivery_mix
 FROM midaworks.dbo.v_yksd_pos_sale a CROSS JOIN event_calendar c
 WHERE a.sda_dt BETWEEN c.event_start AND c.event_end GROUP BY a.store_code
)
SELECT s.*,sm.CD_STORE,COALESCE(sm.NM_STORE,s.acorn_store_name) erp_store_name,
 h.CD_OPERATION,h.CD_MARKETAREA,h.AM_AREA,h.QT_CHAIR,h.CD_SV,
 p.[참여여부],p.[등급],p.[담당SV],p.[상권],p.[메뉴비],p.[매출LIFT],p.[출수유지율]
FROM sales s LEFT JOIN store_rank sm ON sm.store_code=s.store_code AND sm.rn=1
OUTER APPLY (
 SELECT TOP(1) sh.CD_OPERATION,sh.CD_MARKETAREA,sh.AM_AREA,sh.QT_CHAIR,sh.CD_SV
 FROM SEIERP_HD.dbo.FROP_STORESUB sh CROSS JOIN event_calendar c
 WHERE sh.CD_CORP='02' AND sh.CD_STORE=sm.CD_STORE AND TRY_CONVERT(date,sh.DT_MODIFY,112)<=c.event_end
 ORDER BY TRY_CONVERT(date,sh.DT_MODIFY,112) DESC
) h
OUTER APPLY (
 SELECT TOP(1) pc.[참여여부],pc.[등급],pc.[담당SV],pc.[상권],pc.[메뉴비],pc.[매출LIFT],pc.[출수유지율]
 FROM IYN_PromotionDB.dbo.T_PROMO_STORE_CLASSIFICATION pc WHERE pc.[매장코드]=sm.CD_STORE
 ORDER BY pc.DT_BATCH DESC,pc.[분석기준일] DESC
) p ORDER BY s.event_sales DESC;
