/* ============================================================================
   육수당 가맹점 5개년 보양행사 기간 성과
   - 한촌 T1과 동일한 결과 구조
   - 총액/수량/출수: SKYPOS 원장
   - 채널: ACORN에서 검증된 상품코드별 channel을 SKYPOS에 매핑
   - 행사메뉴 바스켓: 현재 확인된 누룽지반계탕(000000027081) 적용
     ※ 연도별 마케팅 공문에서 다른 행사메뉴가 확인되면 basket CTE만 수정
   ============================================================================ */
SET NOCOUNT ON;

WITH event_calendar AS (
    SELECT * FROM (VALUES
        (2022,CONVERT(date,'20220701'),CONVERT(date,'20220821')),
        (2023,'20230630','20230820'),(2024,'20240701','20240818'),
        (2025,'20250701','20250817'),(2026,'20260629','20260816')
    ) v(연도,행사시작,행사종료)
),
basket AS (
    SELECT * FROM (VALUES
        (2022,'000000027081',N'누룽지반계탕'),(2023,'000000027081',N'누룽지반계탕'),
        (2024,'000000027081',N'누룽지반계탕'),(2025,'000000027081',N'누룽지반계탕'),
        (2026,'000000027081',N'누룽지반계탕')
    ) v(연도,CD_SYSITEM,메뉴)
),
channel_map AS (
    /* ACORN에서 동일 cmdt_cd의 채널 충돌 0건 확인 */
    SELECT cmdt_cd,MAX(channel) channel
    FROM midaworks.dbo.v_yksd_pos_sale GROUP BY cmdt_cd
),
frn AS (
    SELECT NO_POSCONNCODE STR_NO
    FROM SEIERP_HD.dbo.FROP_STORE
    WHERE CD_CORP='02' AND CD_BRAND='002' AND NULLIF(NO_POSCONNCODE,'') IS NOT NULL
    GROUP BY NO_POSCONNCODE HAVING MIN(CD_STORETYPE)='002'
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
),
agg AS (
    SELECT c.연도,DATEDIFF(day,c.행사시작,c.행사종료)+1 행사일수,
           COUNT(DISTINCT s.STR_NO) 매장수,SUM(s.순판매) 총순판매금액,
           SUM(CASE WHEN s.채널=N'홀' THEN s.순판매 ELSE 0 END) 홀,
           SUM(CASE WHEN s.채널=N'배달' THEN s.순판매 ELSE 0 END) 배달,
           SUM(CASE WHEN s.채널=N'미매핑' THEN s.순판매 ELSE 0 END) 채널미매핑금액,
           SUM(s.SC_QTY*s.QTY_OUT) 출수,
           SUM(CASE WHEN b.CD_SYSITEM IS NOT NULL THEN s.순판매 ELSE 0 END) 행사메뉴매출,
           SUM(CASE WHEN b.메뉴=N'누룽지반계탕' THEN s.순판매 ELSE 0 END) 누룽지반계탕
    FROM src s JOIN event_calendar c ON c.연도=s.연도
    LEFT JOIN basket b ON b.연도=s.연도 AND b.CD_SYSITEM=s.CD_SYSITEM
    GROUP BY c.연도,c.행사시작,c.행사종료
)
SELECT 연도,매장수,행사일수,총순판매금액,홀,배달,채널미매핑금액,
       CAST(배달*100.0/NULLIF(총순판매금액,0) AS decimal(5,1)) 배달비중,
       출수,CAST(총순판매금액*1.0/NULLIF(출수,0) AS decimal(12,0)) 객단가,
       행사메뉴매출,1 행사메뉴수,
       CAST(행사메뉴매출*100.0/NULLIF(총순판매금액,0) AS decimal(5,1)) 메뉴비,
       누룽지반계탕,
       CAST(누룽지반계탕*100.0/NULLIF(총순판매금액,0) AS decimal(5,1)) 누룽지반계탕_비중,
       CAST(총순판매금액*1.0/NULLIF(매장수*행사일수,0) AS decimal(12,0)) 매장당일평균,
       CAST((총순판매금액*1.0/NULLIF(매장수*행사일수,0)) /
            NULLIF(LAG(총순판매금액*1.0/NULLIF(매장수*행사일수,0)) OVER(ORDER BY 연도),0)*100-100
            AS decimal(5,1)) 성장률
FROM agg ORDER BY 연도;
