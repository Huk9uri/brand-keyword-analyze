/* ============================================================================
   육수당 가맹점 5개년 보양행사 일자별 주차·복날 실적
   그레인: 연도×판매일자×매장×채널 / 메뉴: 누룽지반계탕·도가니탕
   ============================================================================ */
SET NOCOUNT ON;
SET DATEFIRST 7;

WITH event_calendar AS (
    SELECT * FROM (VALUES
        (2022,CONVERT(date,'20220701'),CONVERT(date,'20220821'),CONVERT(date,'20220716'),CONVERT(date,'20220726'),CONVERT(date,'20220815')),
        (2023,'20230630','20230820','20230711','20230721','20230810'),
        (2024,'20240701','20240818','20240715','20240725','20240814'),
        (2025,'20250701','20250817','20250720','20250730','20250809'),
        (2026,'20260629','20260816','20260715','20260725','20260814')
    ) v(연도,행사시작,행사종료,초복,중복,말복)
),
analysis_menu AS (
    SELECT * FROM (VALUES
        ('000000027081',N'누룽지반계탕'),('000000029748',N'도가니탕')
    ) v(CD_SYSITEM,메뉴)
),
channel_map AS (
    SELECT cmdt_cd,MAX(channel) channel
    FROM midaworks.dbo.v_yksd_pos_sale GROUP BY cmdt_cd
),
frn AS (
    SELECT NO_POSCONNCODE STR_NO
    FROM SEIERP_HD.dbo.FROP_STORE
    WHERE CD_CORP='02' AND CD_BRAND='002' AND NULLIF(NO_POSCONNCODE,'') IS NOT NULL
    GROUP BY NO_POSCONNCODE HAVING MIN(CD_STORETYPE)='002'
),
store_name AS (
    SELECT NO_POSCONNCODE STR_NO,MIN(NM_STORE) NM_STORE
    FROM SEIERP_HD.dbo.FROP_STORE
    WHERE CD_CORP='02' AND CD_BRAND='002' AND NULLIF(NO_POSCONNCODE,'') IS NOT NULL
    GROUP BY NO_POSCONNCODE
),
menu_rank AS (
    SELECT CD_STMENU,CD_SYSITEM,
           ROW_NUMBER() OVER(PARTITION BY CD_STMENU ORDER BY ISNULL(DT_UPDDATE,DT_INSDATE) DESC,CD_SYSITEM DESC) rn
    FROM SEIERP_HD.dbo.FRMI_MENULINKCODE WHERE CD_CORP='02'
),
src AS (
    SELECT c.연도,CONVERT(date,p.SDA_DT) 일자,p.STR_NO,
           CASE cm.channel WHEN 'Delivery' THEN N'배달' WHEN 'Hall' THEN N'홀' ELSE N'미매핑' END 채널,
           p.SC_QTY,p.SC_AMT_TTL-ISNULL(p.SC_ADD_AMT,0) 순판매,
           m.CD_SYSITEM,ISNULL(NULLIF(i.QTY_OUT,0),1) QTY_OUT
    FROM event_calendar c
    JOIN SKYPOS.dbo.T_POS_SALE_CMDT p WITH (INDEX(T_POS_SALE_CMDT_IDX))
      ON p.SDA_DT>=c.행사시작 AND p.SDA_DT<DATEADD(day,1,c.행사종료)
    JOIN frn f ON f.STR_NO=p.STR_NO
    LEFT JOIN channel_map cm ON cm.cmdt_cd=p.CMDT_CD
    LEFT JOIN menu_rank m ON m.CD_STMENU=p.CMDT_CD AND m.rn=1
    LEFT JOIN SEIERP_HD.dbo.BSIT_ITEM i ON i.CD_CORP='02' AND i.CD_SYSITEM=m.CD_SYSITEM
    WHERE p.gubun='02' AND p.FRC_CD='FRZIYF' AND p.BRD_CD='YKSD'
)
SELECT s.연도,s.일자 판매일자,
       FLOOR(DATEDIFF(day,c.행사시작,s.일자)/7.0)+1 행사주차,
       CHOOSE(DATEPART(weekday,s.일자),N'일',N'월',N'화',N'수',N'목',N'금',N'토') 요일,
       CASE WHEN DATEPART(weekday,s.일자) IN(1,7) THEN N'주말' ELSE N'평일' END 주중구분,
       CASE WHEN ABS(DATEDIFF(day,c.초복,s.일자))<=1 THEN N'초복'
            WHEN ABS(DATEDIFF(day,c.중복,s.일자))<=1 THEN N'중복'
            WHEN ABS(DATEDIFF(day,c.말복,s.일자))<=1 THEN N'말복' ELSE N'평시' END 복날구분,
       CASE WHEN ABS(DATEDIFF(day,c.초복,s.일자))<=1 THEN DATEDIFF(day,c.초복,s.일자)
            WHEN ABS(DATEDIFF(day,c.중복,s.일자))<=1 THEN DATEDIFF(day,c.중복,s.일자)
            WHEN ABS(DATEDIFF(day,c.말복,s.일자))<=1 THEN DATEDIFF(day,c.말복,s.일자) END 복날D,
       s.STR_NO 매장코드,n.NM_STORE 매장명,s.채널,
       SUM(s.순판매) 순판매금액,SUM(s.SC_QTY) 판매수량,SUM(s.SC_QTY*s.QTY_OUT) 출수,
       SUM(CASE WHEN mu.메뉴=N'누룽지반계탕' THEN s.순판매 ELSE 0 END) 누룽지반계탕_순판매,
       SUM(CASE WHEN mu.메뉴=N'도가니탕' THEN s.순판매 ELSE 0 END) 도가니탕_순판매,
       SUM(CASE WHEN mu.메뉴=N'누룽지반계탕' THEN s.SC_QTY*s.QTY_OUT ELSE 0 END) 누룽지반계탕_출수,
       SUM(CASE WHEN mu.메뉴=N'도가니탕' THEN s.SC_QTY*s.QTY_OUT ELSE 0 END) 도가니탕_출수
FROM src s JOIN event_calendar c ON c.연도=s.연도
LEFT JOIN analysis_menu mu ON mu.CD_SYSITEM=s.CD_SYSITEM
LEFT JOIN store_name n ON n.STR_NO=s.STR_NO
GROUP BY s.연도,s.일자,c.행사시작,c.초복,c.중복,c.말복,s.STR_NO,n.NM_STORE,s.채널
ORDER BY s.연도,s.일자,s.STR_NO,s.채널;
