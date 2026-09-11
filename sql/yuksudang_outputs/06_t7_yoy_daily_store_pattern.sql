/* 6. T7: 2025~2026 일자×매장×채널 전년 대비 패턴. 2025 누락은 산출물 1 검증표 확인. */
SET NOCOUNT ON;
WITH event_calendar AS (
 SELECT * FROM (VALUES
  (2025,CONVERT(date,'20250501'),CONVERT(date,'20250817'),CONVERT(date,'20250720'),CONVERT(date,'20250730'),CONVERT(date,'20250809')),
  (2026,'20260501','20260816','20260715','20260725','20260814')
 ) v(year_no,analysis_start,analysis_end,chobok,jungbok,malbok)
)
SELECT c.year_no,a.sda_dt,a.store_code,MAX(a.store_name) store_name,a.channel,
 CASE WHEN a.sda_dt=c.chobok THEN N'초복' WHEN a.sda_dt=c.jungbok THEN N'중복'
      WHEN a.sda_dt=c.malbok THEN N'말복' ELSE N'일반일' END bok_type,
 DATEDIFF(day,c.analysis_start,a.sda_dt)+1 aligned_day,SUM(a.net_amt) net_sales,SUM(a.qty) sale_qty
FROM event_calendar c JOIN midaworks.dbo.v_yksd_pos_sale a ON a.sda_dt BETWEEN c.analysis_start AND c.analysis_end
GROUP BY c.year_no,a.sda_dt,a.store_code,a.channel,DATEDIFF(day,c.analysis_start,a.sda_dt)+1,
 CASE WHEN a.sda_dt=c.chobok THEN N'초복' WHEN a.sda_dt=c.jungbok THEN N'중복'
      WHEN a.sda_dt=c.malbok THEN N'말복' ELSE N'일반일' END
ORDER BY c.year_no,a.sda_dt,a.store_code,a.channel;
