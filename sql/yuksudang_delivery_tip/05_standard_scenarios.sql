/* 05: 표준 비교 시나리오
   실제 주문분포 확인 전 기본안이며 주문금액 4개 × 거리 3개 × 회원조건 2개를 만든다. */
SET NOCOUNT ON;

WITH order_amount AS (
    SELECT amount FROM (VALUES (15000), (20000), (25000), (30000)) v(amount)
), distance AS (
    SELECT distance_km FROM (VALUES (CAST(1.0 AS decimal(3,1))), (2.0), (3.0)) v(distance_km)
), membership AS (
    SELECT membership_flag FROM (VALUES (CAST(0 AS bit)), (CAST(1 AS bit))) v(membership_flag)
)
SELECT
    CONCAT(N'A', o.amount, N'_D', d.distance_km, N'_M', CONVERT(int, m.membership_flag)) AS scenario_id,
    o.amount AS order_amount,
    d.distance_km,
    m.membership_flag
FROM order_amount AS o
CROSS JOIN distance AS d
CROSS JOIN membership AS m
ORDER BY o.amount, d.distance_km, m.membership_flag;

