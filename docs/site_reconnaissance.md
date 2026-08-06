# LDTS 站點勘查（Phase 1）

目標 URL：`https://ldts.mohw.gov.tw/main_ch/apyList.aspx?uid=2155&pid=63`

## 目前結果

2026-08-06 在本執行環境以直接 HTTPS 請求與網頁擷取服務嘗試連線，分別收到「Unable to connect to the remote server」及 timeout，因此尚未取得可驗證的 HTML、HTTP method、hidden fields、cookies、分頁控制項或 XHR。不得據此臆測 selector、API 或查詢參數。

依使用者提供的畫面，頁面至少呈現縣市下拉選單與結果表格；欄位包含案件編號、縣市、醫療機構名稱、檢測項目名稱、分析標的、檢測項目類別、費用、認證實驗室名稱、認證實驗室所屬機構。這些僅是畫面觀察，待成功取得 HTML 後再確認 DOM。

## 暫定方法

先採 Strategy A/B 的保守探測：保存首頁 response，再判斷是 GET table、ASP.NET postback 或 JavaScript/XHR。解析器以欄位文字辨識 table，不依賴未驗證的 CSS class。每頁保存原始 HTML，預設請求間隔 3 秒；不繞過 CAPTCHA、登入或存取控制。

## 待確認

- robots.txt、網站條款與是否允許自動化查詢
- HTTP method、ASP.NET ViewState、查詢欄位及分頁 postback
- 總筆數、每頁筆數與臺北市前 20 筆的可重現查詢
- 是否存在官方 Excel/CSV/API
- 是否需要瀏覽器或人工匯出

目前不能宣稱已抓取臺北市資料；請先在可連線環境執行探測或提供一份已下載的結果頁 HTML。
