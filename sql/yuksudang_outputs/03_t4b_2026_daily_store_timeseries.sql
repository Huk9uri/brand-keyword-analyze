/* 3. T4-b: 2026 일자×매장×채널 시계열 */
SET NOCOUNT ON;
WITH event_calendar AS (
 SELECT CONVERT(date,'20260501') baseline_start,CONVERT(date,'20260531') baseline_end,
 CONVERT(date,'20260601') pre_start,CONVERT(date,'20260628') pre_end,
 CONVERT(date,'20260629') event_start,CONVERT(date,'20260816') event_end,
 CONVERT(date,'20260715') chobok,CONVERT(date,'20260725') jungbok,CONVERT(date,'20260814') malbok
)
SELECT a.sda_dt,a.store_code,MAX(a.store_name) store_name,a.channel,
 CASE WHEN a.sda_dt<=c.baseline_end THEN N'기준선' WHEN a.sda_dt<=c.pre_end THEN N'사전행사' ELSE N'본행사' END period_name,
 CASE WHEN a.sda_dt=c.chobok THEN N'초복' WHEN a.sda_dt=c.jungbok THEN N'중복'
      WHEN a.sda_dt=c.malbok THEN N'말복' ELSE N'일반일' END bok_type,
 SUM(a.net_amt) net_sales,SUM(a.qty) sale_qty
FROM midaworks.dbo.v_yksd_pos_sale a CROSS JOIN event_calendar c
WHERE a.sda_dt BETWEEN c.baseline_start AND c.event_end
GROUP BY a.sda_dt,a.store_code,a.channel,
 CASE WHEN a.sda_dt<=c.baseline_end THEN N'기준선' WHEN a.sda_dt<=c.pre_end THEN N'사전행사' ELSE N'본행사' END,
 CASE WHEN a.sda_dt=c.chobok THEN N'초복' WHEN a.sda_dt=c.jungbok THEN N'중복'
      WHEN a.sda_dt=c.malbok THEN N'말복' ELSE N'일반일' END
ORDER BY a.sda_dt,a.store_code,a.channel;
