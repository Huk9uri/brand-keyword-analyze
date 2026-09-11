/* ============================================================================
   육수당 여름 보양행사 분석
   원천: SKYPOS + SEIERP_HD + IYN_PromotionDB

   육수당 식별값
     POS : FRC_CD='FRZIYF', BRD_CD='YKSD', gubun='02'
     ERP : CD_CORP='02', CD_BRAND='002', CD_STORETYPE='002'

   주의
   1) 순판매 = SC_AMT_TTL - ISNULL(SC_ADD_AMT,0)
   2) POS코드는 양수도 과정에서 재사용되므로 매장명은 운영중/최신 계약 1건만 표시한다.
      과거 매장 귀속이 필요한 감사용 분석은 DT_OPEN/DT_CLOSE 시점 조인을 추가한다.
   3) 배달은 상품코드 기준 추정값이다. 총순판매에는 영향을 주지 않지만 채널 분석 전
      ACORN 화면의 홀/배달 합계와 별도 검증해야 한다.
   ============================================================================ */

SET NOCOUNT ON;
SET DATEFIRST 7;

/* [결과 1] 2022~2026년 본행사 기본 성과 ===================================== */
WITH cal AS (
    SELECT 2022 AS 연도, CAST('2022-07-01' AS date) 행사시작,
           CAST('2022-08-21' AS date) 행사종료,
           CAST('2022-07-16' AS date) 초복, CAST('2022-07-26' AS date) 중복,
           CAST('2022-08-15' AS date) 말복
    UNION ALL SELECT 2023,'2023-06-30','2023-08-20','2023-07-11','2023-07-21','2023-08-10'
    UNION ALL SELECT 2024,'2024-07-01','2024-08-18','2024-07-15','2024-07-25','2024-08-14'
    UNION ALL SELECT 2025,'2025-07-01','2025-08-17','2025-07-20','2025-07-30','2025-08-09'
    UNION ALL SELECT 2026,'2026-06-29','2026-08-16','2026-07-15','2026-07-25','2026-08-14'
),
menu_map AS (
    SELECT CD_STMENU,CD_SYSITEM FROM (
        SELECT CD_STMENU,CD_SYSITEM,
               ROW_NUMBER() OVER (
                   PARTITION BY CD_STMENU
                   ORDER BY ISNULL(DT_UPDDATE,DT_INSDATE) DESC,CD_SYSITEM DESC
               ) rn
        FROM SEIERP_HD.dbo.FRMI_MENULINKCODE
        WHERE CD_CORP='02'
    ) m WHERE rn=1
),
item AS (
    SELECT CD_SYSITEM,NM_ITEM,ISNULL(NULLIF(QTY_OUT,0),1) QTY_OUT
    FROM SEIERP_HD.dbo.BSIT_ITEM
    WHERE CD_CORP='02'
),
src AS (
    SELECT c.연도,CONVERT(date,p.SDA_DT) 판매일자,p.STR_NO,p.CMDT_CD,
           p.SC_QTY,
           p.SC_AMT_TTL - ISNULL(p.SC_ADD_AMT,0) AS 순판매,
           mm.CD_SYSITEM,i.NM_ITEM,i.QTY_OUT,
           CASE WHEN p.CMDT_CD LIKE 'DEL%' OR p.CMDT_CD LIKE 'DLV%'
                  OR p.CMDT_CD LIKE 'MATE%' OR p.CMDT_CD LIKE 'OKBC%'
                  OR p.CMDT_CD LIKE 'BDM%' OR p.CMDT_CD LIKE 'NQR%'
                  OR p.CMDT_CD LIKE 'BDSET%' OR p.CMDT_CD LIKE 'BEA%'
                THEN 1 ELSE 0 END AS 배달추정F,
           CASE WHEN ISNULL(i.NM_ITEM,p.SC_CMDT_NM) LIKE N'%반계탕%'
                  OR ISNULL(i.NM_ITEM,p.SC_CMDT_NM) LIKE N'%삼계탕%'
                THEN 1 ELSE 0 END AS 핵심보양메뉴F,
           CASE WHEN ISNULL(i.NM_ITEM,p.SC_CMDT_NM) LIKE N'%도가니탕%'
                THEN 1 ELSE 0 END AS 도가니탕F
    FROM cal c
    JOIN SKYPOS.dbo.T_POS_SALE_CMDT p WITH (INDEX(T_POS_SALE_CMDT_IDX))
      ON p.SDA_DT>=c.행사시작 AND p.SDA_DT<DATEADD(day,1,c.행사종료)
    LEFT JOIN menu_map mm ON p.CMDT_CD=mm.CD_STMENU
    LEFT JOIN item i ON mm.CD_SYSITEM=i.CD_SYSITEM
    WHERE p.gubun='02' AND p.FRC_CD='FRZIYF' AND p.BRD_CD='YKSD'
)
SELECT 연도,COUNT(DISTINCT 판매일자) 행사일수,COUNT(DISTINCT STR_NO) 매장수,
       SUM(순판매) 총순판매금액,
       SUM(CASE WHEN 배달추정F=0 THEN 순판매 ELSE 0 END) 홀포장_추정매출,
       SUM(CASE WHEN 배달추정F=1 THEN 순판매 ELSE 0 END) 배달_추정매출,
       CAST(SUM(CASE WHEN 배달추정F=1 THEN 순판매 ELSE 0 END)*100.0
            /NULLIF(SUM(순판매),0) AS decimal(6,2)) 배달_추정비중,
       SUM(SC_QTY*QTY_OUT) 출수,
       SUM(CASE WHEN 핵심보양메뉴F=1 THEN 순판매 ELSE 0 END) 핵심보양메뉴매출,
       CAST(SUM(CASE WHEN 핵심보양메뉴F=1 THEN 순판매 ELSE 0 END)*100.0
            /NULLIF(SUM(순판매),0) AS decimal(6,2)) 핵심보양메뉴비중,
       SUM(CASE WHEN 도가니탕F=1 THEN 순판매 ELSE 0 END) 도가니탕매출
FROM src
GROUP BY 연도
ORDER BY 연도;


/* [결과 2] 2026년 기준선→사전행사→본행사 매장별 성과 ======================= */
WITH period AS (
    SELECT N'기준선' 구간,CAST('2026-05-01' AS date) 시작일,CAST('2026-05-31' AS date) 종료일
    UNION ALL SELECT N'사전행사','2026-06-01','2026-06-28'
    UNION ALL SELECT N'본행사','2026-06-29','2026-08-16'
),
store_master AS (
    SELECT STR_NO,CD_STORE,NM_STORE,CD_MARKETAREA,CD_SV FROM (
        SELECT s.NO_POSCONNCODE STR_NO,s.CD_STORE,s.NM_STORE,s.CD_MARKETAREA,s.CD_SV,
               ROW_NUMBER() OVER (
                   PARTITION BY s.NO_POSCONNCODE
                   ORDER BY CASE WHEN s.CD_STATUS='001' THEN 0 ELSE 1 END,
                            CASE WHEN s.CD_OPERATION='002' THEN 0 ELSE 1 END,
                            ISNULL(NULLIF(s.DT_CLOSE,''),'99991231') DESC,s.CD_STORE DESC
               ) rn
        FROM SEIERP_HD.dbo.FROP_STORE s
        WHERE s.CD_CORP='02' AND s.CD_BRAND='002' AND s.CD_STORETYPE='002'
          AND NULLIF(LTRIM(RTRIM(s.NO_POSCONNCODE)),'') IS NOT NULL
    ) x WHERE rn=1
),
menu_map AS (
    SELECT CD_STMENU,CD_SYSITEM FROM (
        SELECT CD_STMENU,CD_SYSITEM,
               ROW_NUMBER() OVER (
                   PARTITION BY CD_STMENU
                   ORDER BY ISNULL(DT_UPDDATE,DT_INSDATE) DESC,CD_SYSITEM DESC
               ) rn
        FROM SEIERP_HD.dbo.FRMI_MENULINKCODE WHERE CD_CORP='02'
    ) m WHERE rn=1
),
item AS (
    SELECT CD_SYSITEM,NM_ITEM,ISNULL(NULLIF(QTY_OUT,0),1) QTY_OUT
    FROM SEIERP_HD.dbo.BSIT_ITEM WHERE CD_CORP='02'
),
promo AS (
    SELECT 매장코드,참여여부,등급,담당SV FROM (
        SELECT 매장코드,참여여부,등급,담당SV,
               ROW_NUMBER() OVER (
                   PARTITION BY 매장코드
                   ORDER BY CASE WHEN 분류단계=N'사후' THEN 0 ELSE 1 END,
                            분석기준일 DESC,주차 DESC
               ) rn
        FROM IYN_PromotionDB.dbo.T_PROMO_STORE_CLASSIFICATION
        WHERE 행사명 IN (N'26년)6월 누룽지반계탕 사전행사',N'7-8월 보양행사')
          AND NULLIF(LTRIM(RTRIM(매장코드)),'') IS NOT NULL
    ) p WHERE rn=1
),
src AS (
    SELECT pr.구간,CONVERT(date,p.SDA_DT) 판매일자,p.STR_NO,p.SC_QTY,
           p.SC_AMT_TTL - ISNULL(p.SC_ADD_AMT,0) AS 순판매,
           ISNULL(NULLIF(i.QTY_OUT,0),1) QTY_OUT,
           CASE WHEN ISNULL(i.NM_ITEM,p.SC_CMDT_NM) LIKE N'%반계탕%'
                  OR ISNULL(i.NM_ITEM,p.SC_CMDT_NM) LIKE N'%삼계탕%'
                THEN 1 ELSE 0 END 핵심보양메뉴F,
           CASE WHEN ISNULL(i.NM_ITEM,p.SC_CMDT_NM) LIKE N'%도가니탕%'
                THEN 1 ELSE 0 END 도가니탕F
    FROM period pr
    JOIN SKYPOS.dbo.T_POS_SALE_CMDT p WITH (INDEX(T_POS_SALE_CMDT_IDX))
      ON p.SDA_DT>=pr.시작일 AND p.SDA_DT<DATEADD(day,1,pr.종료일)
    LEFT JOIN menu_map mm ON p.CMDT_CD=mm.CD_STMENU
    LEFT JOIN item i ON mm.CD_SYSITEM=i.CD_SYSITEM
    WHERE p.gubun='02' AND p.FRC_CD='FRZIYF' AND p.BRD_CD='YKSD'
),
agg AS (
    SELECT STR_NO,구간,COUNT(DISTINCT 판매일자) 영업일수,SUM(순판매) 매출,
           SUM(SC_QTY*QTY_OUT) 출수,
           SUM(CASE WHEN 핵심보양메뉴F=1 THEN 순판매 ELSE 0 END) 핵심메뉴매출,
           SUM(CASE WHEN 도가니탕F=1 THEN 순판매 ELSE 0 END) 도가니탕매출
    FROM src GROUP BY STR_NO,구간
),
piv AS (
    SELECT STR_NO,
      MAX(CASE WHEN 구간=N'기준선' THEN 영업일수 END) 기준_영업일수,
      MAX(CASE WHEN 구간=N'기준선' THEN 매출 END) 기준_매출,
      MAX(CASE WHEN 구간=N'사전행사' THEN 영업일수 END) 사전_영업일수,
      MAX(CASE WHEN 구간=N'사전행사' THEN 매출 END) 사전_매출,
      MAX(CASE WHEN 구간=N'사전행사' THEN 핵심메뉴매출 END) 사전_핵심메뉴매출,
      MAX(CASE WHEN 구간=N'본행사' THEN 영업일수 END) 본_영업일수,
      MAX(CASE WHEN 구간=N'본행사' THEN 매출 END) 본_매출,
      MAX(CASE WHEN 구간=N'본행사' THEN 출수 END) 본_출수,
      MAX(CASE WHEN 구간=N'본행사' THEN 핵심메뉴매출 END) 본_핵심메뉴매출,
      MAX(CASE WHEN 구간=N'본행사' THEN 도가니탕매출 END) 본_도가니탕매출
    FROM agg GROUP BY STR_NO
)
SELECT p.STR_NO POS매장코드,sm.CD_STORE ERP매장코드,sm.NM_STORE 매장명,
       p.기준_영업일수,p.기준_매출,
       CAST(p.기준_매출*1.0/NULLIF(p.기준_영업일수,0) AS decimal(14,0)) 기준_일평균매출,
       p.사전_영업일수,p.사전_매출,
       CAST(p.사전_핵심메뉴매출*100.0/NULLIF(p.사전_매출,0) AS decimal(6,2)) 사전_핵심메뉴비중,
       p.본_영업일수,p.본_매출,
       CAST(p.본_매출*1.0/NULLIF(p.본_영업일수,0) AS decimal(14,0)) 본_일평균매출,
       CAST((p.본_매출*1.0/NULLIF(p.본_영업일수,0))
            /NULLIF(p.기준_매출*1.0/NULLIF(p.기준_영업일수,0),0)-1
            AS decimal(8,4)) 매출LIFT,
       p.본_출수,
       CAST(p.본_핵심메뉴매출*100.0/NULLIF(p.본_매출,0) AS decimal(6,2)) 본_핵심메뉴비중,
       p.본_도가니탕매출,
       CASE sm.CD_MARKETAREA WHEN '001' THEN N'주거밀집' WHEN '002' THEN N'주거복합'
            WHEN '003' THEN N'오피스' WHEN '004' THEN N'교외' WHEN '005' THEN N'특수' END 상권,
       COALESCE(pr.담당SV,sm.CD_SV) 담당SV,pr.참여여부 사전행사_참여여부,pr.등급 행사등급
FROM piv p
LEFT JOIN store_master sm ON p.STR_NO=sm.STR_NO
LEFT JOIN promo pr ON sm.CD_STORE=pr.매장코드
WHERE p.본_매출>0
ORDER BY sm.NM_STORE,p.STR_NO;
