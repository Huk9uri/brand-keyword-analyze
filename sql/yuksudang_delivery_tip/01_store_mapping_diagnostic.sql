/* 육수당 배달팁 경쟁점 분석 01: ERP-플랫폼 매장 매핑 진단
   ERP 기준: SEIERP_HD / 법인 02 / 브랜드 002
   주의: channel_group_store_info 누락 매장은 분석 대상에서 버리지 말고 별도 보완 목록으로 출력한다. */
SET NOCOUNT ON;

WITH erp_store AS (
    SELECT DISTINCT
        s.CD_STORE AS erp_store_code,
        s.NM_STORE AS erp_store_name
    FROM SEIERP_HD.dbo.FROP_STORE AS s
    WHERE s.CD_CORP = '02'
      AND s.CD_BRAND = '002'
),
platform_store AS (
    SELECT 'BAE' AS platform, CONVERT(varchar(255), no) AS platform_shop_number, shop_name
    FROM yuksudang_delivery.dbo.bae_shop
    UNION ALL
    SELECT 'EAT', CONVERT(varchar(255), no), shop_name
    FROM yuksudang_delivery.dbo.eat_shop
),
group_map AS (
    SELECT DISTINCT
        CASE
            WHEN app_type = 'Baemin' THEN 'BAE'
            WHEN app_type = 'CoupangEats' THEN 'EAT'
        END AS platform,
        CONVERT(varchar(255), no) AS platform_shop_number,
        name AS mapped_store_name
    FROM yuksudang_delivery.dbo.channel_group_store_info
    WHERE app_type IN ('Baemin', 'CoupangEats')
)
SELECT
    p.platform,
    p.platform_shop_number,
    p.shop_name,
    g.mapped_store_name,
    e.erp_store_code,
    e.erp_store_name,
    CASE
        WHEN g.platform_shop_number IS NULL THEN 'CHANNEL_GROUP_MISSING'
        WHEN e.erp_store_code IS NULL THEN 'ERP_NAME_UNMATCHED'
        ELSE 'MATCHED'
    END AS mapping_status
FROM platform_store AS p
LEFT JOIN group_map AS g
  ON g.platform = p.platform
 AND g.platform_shop_number = p.platform_shop_number
LEFT JOIN erp_store AS e
  ON REPLACE(REPLACE(e.erp_store_name, N'육수당', N''), N'점', N'')
   = REPLACE(REPLACE(COALESCE(g.mapped_store_name, p.shop_name), N'육수당', N''), N'점', N'')
ORDER BY p.platform, mapping_status, p.shop_name;
