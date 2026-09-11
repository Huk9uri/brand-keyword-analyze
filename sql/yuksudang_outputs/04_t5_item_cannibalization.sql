/* 4. T5: 구간×중분류×품목×매장 카니발리즘 */
SET NOCOUNT ON;
WITH event_calendar AS (
 SELECT CONVERT(date,'20260501') baseline_start,CONVERT(date,'20260531') baseline_end,
 CONVERT(date,'20260601') pre_start,CONVERT(date,'20260628') pre_end,
 CONVERT(date,'20260629') event_start,CONVERT(date,'20260816') event_end
), menu_rank AS (
 SELECT CD_STMENU,CD_SYSITEM,ROW_NUMBER() OVER(PARTITION BY CD_STMENU ORDER BY ISNULL(DT_UPDDATE,DT_INSDATE) DESC,CD_SYSITEM DESC) rn
 FROM SEIERP_HD.dbo.FRMI_MENULINKCODE WHERE CD_CORP='02'
), menu AS (
 SELECT m.CD_STMENU,m.CD_SYSITEM,i.NM_ITEM,i.CD_ITEM_H,ISNULL(NULLIF(i.QTY_OUT,0),1) QTY_OUT,c.NM_MDDNAME
 FROM menu_rank m LEFT JOIN SEIERP_HD.dbo.BSIT_ITEM i ON i.CD_CORP='02' AND i.CD_SYSITEM=m.CD_SYSITEM
 LEFT JOIN SEIERP_HD.dbo.BSIT_ITEMCLASS_MDD c ON c.CD_CORP='02' AND c.CD_GBCODE=LEFT(i.CD_ITEM_H,1)
  AND c.CD_LGCODE=SUBSTRING(i.CD_ITEM_H,2,2) AND c.CD_MDDCODE=RIGHT(i.CD_ITEM_H,2) WHERE m.rn=1
)
SELECT CASE WHEN a.sda_dt<=c.baseline_end THEN N'기준선' WHEN a.sda_dt<=c.pre_end THEN N'사전행사' ELSE N'본행사' END period_name,
 m.CD_ITEM_H,m.NM_MDDNAME,m.CD_SYSITEM,COALESCE(m.NM_ITEM,a.menu_name) item_name,
 a.store_code,MAX(a.store_name) store_name,a.channel,SUM(a.net_amt) net_sales,SUM(a.qty) sale_qty,
 SUM(a.qty*ISNULL(m.QTY_OUT,1)) output_qty
FROM midaworks.dbo.v_yksd_pos_sale a CROSS JOIN event_calendar c LEFT JOIN menu m ON m.CD_STMENU=a.cmdt_cd
WHERE a.sda_dt BETWEEN c.baseline_start AND c.event_end
GROUP BY CASE WHEN a.sda_dt<=c.baseline_end THEN N'기준선' WHEN a.sda_dt<=c.pre_end THEN N'사전행사' ELSE N'본행사' END,
 m.CD_ITEM_H,m.NM_MDDNAME,m.CD_SYSITEM,COALESCE(m.NM_ITEM,a.menu_name),a.store_code,a.channel;
