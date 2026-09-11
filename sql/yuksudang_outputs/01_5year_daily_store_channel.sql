/* 1. 5개년 RAW: 연도×일자×매장×채널. 채널은 ACORN 확정값 사용. */
SET NOCOUNT ON;
WITH event_calendar AS (
 SELECT * FROM (VALUES
  (2022,CONVERT(date,'20220701'),CONVERT(date,'20220821'),CONVERT(date,'20220716'),CONVERT(date,'20220726'),CONVERT(date,'20220815')),
  (2023,'20230630','20230820','20230711','20230721','20230810'),
  (2024,'20240701','20240818','20240715','20240725','20240814'),
  (2025,'20250701','20250817','20250720','20250730','20250809'),
  (2026,'20260629','20260816','20260715','20260725','20260814')
 ) v(year_no,event_start,event_end,chobok,jungbok,malbok)
)
SELECT c.year_no,a.sda_dt,a.store_code,MAX(a.store_name) store_name,a.channel,
 CASE WHEN a.sda_dt=c.chobok THEN N'초복' WHEN a.sda_dt=c.jungbok THEN N'중복'
      WHEN a.sda_dt=c.malbok THEN N'말복' ELSE N'일반일' END bok_type,
 SUM(a.net_amt) net_sales,SUM(a.qty) sale_qty
FROM event_calendar c JOIN midaworks.dbo.v_yksd_pos_sale a ON a.sda_dt BETWEEN c.event_start AND c.event_end
GROUP BY c.year_no,a.sda_dt,a.store_code,a.channel,
 CASE WHEN a.sda_dt=c.chobok THEN N'초복' WHEN a.sda_dt=c.jungbok THEN N'중복'
      WHEN a.sda_dt=c.malbok THEN N'말복' ELSE N'일반일' END
ORDER BY a.sda_dt,a.store_code,a.channel;

/* 연도별 정합성: 차이 0인 연도만 채널 분석에 사용 */
WITH event_calendar AS (
 SELECT * FROM (VALUES (2022,CONVERT(date,'20220701'),CONVERT(date,'20220821')),(2023,'20230630','20230820'),
 (2024,'20240701','20240818'),(2025,'20250701','20250817'),(2026,'20260629','20260816')) v(year_no,event_start,event_end)
), pos AS (
 SELECT c.year_no,SUM(p.SC_AMT_TTL-ISNULL(p.SC_ADD_AMT,0)) amt FROM event_calendar c
 JOIN SKYPOS.dbo.T_POS_SALE_CMDT p ON p.SDA_DT>=c.event_start AND p.SDA_DT<DATEADD(day,1,c.event_end)
 WHERE p.gubun='02' AND p.FRC_CD='FRZIYF' AND p.BRD_CD='YKSD' GROUP BY c.year_no
), acorn AS (
 SELECT c.year_no,SUM(a.net_amt) amt FROM event_calendar c JOIN midaworks.dbo.v_yksd_pos_sale a
 ON a.sda_dt BETWEEN c.event_start AND c.event_end GROUP BY c.year_no
)
SELECT p.year_no,p.amt skypos_total,a.amt acorn_total,a.amt-p.amt difference,
 CASE WHEN a.amt=p.amt THEN N'사용 가능' ELSE N'채널 분석 제외' END validation_status
FROM pos p LEFT JOIN acorn a ON a.year_no=p.year_no ORDER BY p.year_no;
