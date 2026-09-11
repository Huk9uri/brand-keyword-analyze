/* 2. T4: 2026 매장별 기준선·사전행사·본행사 연결 */
SET NOCOUNT ON;
WITH event_calendar AS (
 SELECT CONVERT(date,'20260501') baseline_start,CONVERT(date,'20260531') baseline_end,
 CONVERT(date,'20260601') pre_start,CONVERT(date,'20260628') pre_end,
 CONVERT(date,'20260629') event_start,CONVERT(date,'20260816') event_end
), s AS (
 SELECT a.store_code,MAX(a.store_name) store_name,
 SUM(CASE WHEN a.sda_dt BETWEEN c.baseline_start AND c.baseline_end THEN a.net_amt ELSE 0 END)/31.0 baseline_daily,
 SUM(CASE WHEN a.sda_dt BETWEEN c.pre_start AND c.pre_end THEN a.net_amt ELSE 0 END)/28.0 pre_daily,
 SUM(CASE WHEN a.sda_dt BETWEEN c.event_start AND c.event_end THEN a.net_amt ELSE 0 END)/49.0 event_daily
 FROM midaworks.dbo.v_yksd_pos_sale a CROSS JOIN event_calendar c
 WHERE a.sda_dt BETWEEN c.baseline_start AND c.event_end GROUP BY a.store_code
)
SELECT *,CAST(pre_daily/NULLIF(baseline_daily,0)-1 AS decimal(12,4)) pre_lift,
 CAST(event_daily/NULLIF(baseline_daily,0)-1 AS decimal(12,4)) event_lift,
 CAST(event_daily/NULLIF(pre_daily,0)-1 AS decimal(12,4)) pre_to_event_lift
FROM s ORDER BY event_lift DESC;
