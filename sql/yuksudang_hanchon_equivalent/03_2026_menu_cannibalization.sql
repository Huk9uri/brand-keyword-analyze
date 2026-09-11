/* ============================================================================
   육수당 2026 보양행사 카니발리즘 분석
   목적: 누룽지반계탕 증가가 도가니탕·동일 중분류 메뉴 감소와 동반됐는지 확인
   그레인: 매장×ACORN 채널
   비교: 기준선(5/1~5/31) vs 사전행사(6/1~6/28) vs 본행사(6/29~8/16)
   판정은 인과관계가 아닌 '대체 징후'이다.
   ============================================================================ */
SET NOCOUNT ON;

WITH event_calendar AS (
    SELECT * FROM (VALUES
        (N'기준선',CONVERT(date,'20260501'),CONVERT(date,'20260531'),31),
        (N'사전행사',CONVERT(date,'20260601'),CONVERT(date,'20260628'),28),
        (N'본행사',CONVERT(date,'20260629'),CONVERT(date,'20260816'),49)
    ) v(구간,시작일,종료일,구간일수)
),
menu_rank AS (
    SELECT CD_STMENU,CD_SYSITEM,
           ROW_NUMBER() OVER(
               PARTITION BY CD_STMENU
               ORDER BY ISNULL(DT_UPDDATE,DT_INSDATE) DESC,CD_SYSITEM DESC
           ) rn
    FROM SEIERP_HD.dbo.FRMI_MENULINKCODE
    WHERE CD_CORP='02'
),
menu AS (
    SELECT m.CD_STMENU,m.CD_SYSITEM,i.NM_ITEM,i.CD_ITEM_H,
           ISNULL(NULLIF(i.QTY_OUT,0),1) QTY_OUT
    FROM menu_rank m
    LEFT JOIN SEIERP_HD.dbo.BSIT_ITEM i
      ON i.CD_CORP='02' AND i.CD_SYSITEM=m.CD_SYSITEM
    WHERE m.rn=1
),
fact AS (
    SELECT c.구간,c.구간일수,a.store_code,MAX(a.store_name) OVER(PARTITION BY a.store_code) 매장명,
           a.channel,m.CD_SYSITEM,m.CD_ITEM_H,
           a.net_amt 순판매,a.qty 판매수량,a.qty*ISNULL(m.QTY_OUT,1) 출수,
           CASE
             WHEN m.CD_SYSITEM='000000027081' THEN N'행사메뉴_누룽지반계탕'
             WHEN m.CD_SYSITEM='000000029748' THEN N'비교메뉴_도가니탕'
             WHEN m.CD_ITEM_H='W2001' THEN N'동일중분류_기타'
             ELSE N'기타메뉴'
           END 메뉴군
    FROM event_calendar c
    JOIN midaworks.dbo.v_yksd_pos_sale a ON a.sda_dt BETWEEN c.시작일 AND c.종료일
    LEFT JOIN menu m ON m.CD_STMENU=a.cmdt_cd
),
common_store_channel AS (
    /* 세 구간 모두 매출이 있는 동일 매장×채널만 비교해 개폐점·채널 중단 영향을 축소 */
    SELECT store_code,channel
    FROM fact GROUP BY store_code,channel HAVING COUNT(DISTINCT 구간)=3
),
period_agg AS (
    SELECT f.store_code,MAX(f.매장명) 매장명,f.channel,f.구간,MAX(f.구간일수) 구간일수,
           SUM(f.순판매) 총매출,
           SUM(CASE WHEN f.메뉴군=N'행사메뉴_누룽지반계탕' THEN f.순판매 ELSE 0 END) 행사메뉴매출,
           SUM(CASE WHEN f.메뉴군=N'비교메뉴_도가니탕' THEN f.순판매 ELSE 0 END) 도가니탕매출,
           SUM(CASE WHEN f.메뉴군=N'동일중분류_기타' THEN f.순판매 ELSE 0 END) 동일중분류기타매출,
           SUM(CASE WHEN f.메뉴군=N'행사메뉴_누룽지반계탕' THEN f.출수 ELSE 0 END) 행사메뉴출수
    FROM fact f JOIN common_store_channel c ON c.store_code=f.store_code AND c.channel=f.channel
    GROUP BY f.store_code,f.channel,f.구간
),
pivoted AS (
    SELECT store_code,MAX(매장명) 매장명,channel,
      MAX(CASE WHEN 구간=N'기준선' THEN 총매출/구간일수 END) 기준선_총매출일평균,
      MAX(CASE WHEN 구간=N'본행사' THEN 총매출/구간일수 END) 본행사_총매출일평균,
      MAX(CASE WHEN 구간=N'기준선' THEN 행사메뉴매출/구간일수 END) 기준선_행사메뉴일평균,
      MAX(CASE WHEN 구간=N'사전행사' THEN 행사메뉴매출/구간일수 END) 사전_행사메뉴일평균,
      MAX(CASE WHEN 구간=N'본행사' THEN 행사메뉴매출/구간일수 END) 본행사_행사메뉴일평균,
      MAX(CASE WHEN 구간=N'기준선' THEN 도가니탕매출/구간일수 END) 기준선_도가니탕일평균,
      MAX(CASE WHEN 구간=N'본행사' THEN 도가니탕매출/구간일수 END) 본행사_도가니탕일평균,
      MAX(CASE WHEN 구간=N'기준선' THEN 동일중분류기타매출/구간일수 END) 기준선_동일중분류기타일평균,
      MAX(CASE WHEN 구간=N'본행사' THEN 동일중분류기타매출/구간일수 END) 본행사_동일중분류기타일평균,
      MAX(CASE WHEN 구간=N'기준선' THEN 행사메뉴출수/구간일수 END) 기준선_행사메뉴출수일평균,
      MAX(CASE WHEN 구간=N'본행사' THEN 행사메뉴출수/구간일수 END) 본행사_행사메뉴출수일평균,
      MAX(CASE WHEN 구간=N'기준선' THEN 행사메뉴매출*1.0/NULLIF(총매출,0) END) 기준선_행사메뉴비,
      MAX(CASE WHEN 구간=N'본행사' THEN 행사메뉴매출*1.0/NULLIF(총매출,0) END) 본행사_행사메뉴비
    FROM period_agg GROUP BY store_code,channel
)
SELECT *,
       본행사_행사메뉴일평균-기준선_행사메뉴일평균 행사메뉴_일평균증감,
       본행사_도가니탕일평균-기준선_도가니탕일평균 도가니탕_일평균증감,
       본행사_동일중분류기타일평균-기준선_동일중분류기타일평균 동일중분류기타_일평균증감,
       본행사_총매출일평균-기준선_총매출일평균 총매출_일평균증감,
       CAST((본행사_행사메뉴비-기준선_행사메뉴비)*100 AS decimal(8,2)) 행사메뉴비_증감p,
       CASE
         WHEN 본행사_행사메뉴일평균>기준선_행사메뉴일평균
          AND (본행사_도가니탕일평균+본행사_동일중분류기타일평균)
              <(기준선_도가니탕일평균+기준선_동일중분류기타일평균)
          AND 본행사_총매출일평균<=기준선_총매출일평균 THEN N'강한 대체 징후'
         WHEN 본행사_행사메뉴일평균>기준선_행사메뉴일평균
          AND (본행사_도가니탕일평균+본행사_동일중분류기타일평균)
              <(기준선_도가니탕일평균+기준선_동일중분류기타일평균) THEN N'부분 대체 징후'
         WHEN 본행사_행사메뉴일평균>기준선_행사메뉴일평균
          AND 본행사_총매출일평균>기준선_총매출일평균 THEN N'증분 성장'
         ELSE N'징후 없음·기타'
       END 카니발리즘판정
FROM pivoted
ORDER BY 카니발리즘판정,행사메뉴_일평균증감 DESC;
