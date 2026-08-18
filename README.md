# LDTS Market Intelligence

臺灣衛生福利部 LDTS 公開登記資料的收集、清理與分析工具。本專案只處理公開資料，不繞過 CAPTCHA、登入、反爬或存取控制；分析結論必須能追溯至 raw HTML 與來源 URL。

## 安裝

需要 Python 3.11+：

```powershell
cd C:\Users\User\Documents\LDTS_CompetitorAnalysis
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pytest
```

若 PowerShell 阻擋啟用：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 測試

```powershell
pytest -q
```

## 單一縣市抓取

```powershell
ldts scrape `
  --city 臺北市 `
  --max-pages 2 `
  --output data\processed\taipei_preview.csv `
  --insecure
```

輸出包括 `data/raw/`、CSV、`_manual_review.csv` 與 `_quality.json`。`--insecure` 只用於本機 TLS 憑證鏈問題；正式環境應修復憑證後移除。

完整臺北市抓取：

```powershell
ldts scrape `
  --city 臺北市 `
  --max-pages 120 `
  --output data\processed\taipei_full.csv `
  --insecure
```

## 中斷後續抓

```powershell
ldts scrape `
  --city 臺北市 `
  --max-pages 120 `
  --output data\processed\taipei_full.csv `
  --resume `
  --insecure
```

若既有 raw page 有頁碼錯位、重複案件或缺頁，請改用新輸出檔名重新抓取，不要使用 `--resume`。

## 多縣市批次抓取

指定多個縣市：

```powershell
ldts scrape-batch `
  --city 臺北市 `
  --city 臺中市 `
  --max-pages 120 `
  --output-dir data\processed `
  --insecure
```

使用完整 22 縣市清單：

```powershell
ldts scrape-batch `
  --cities-file config\cities.txt `
  --max-pages 120 `
  --output-dir data\processed `
  --insecure
```

中斷後只重跑未完成或品質不合格的縣市：

```powershell
ldts scrape-batch `
  --cities-file config\cities.txt `
  --max-pages 120 `
  --output-dir data\processed `
  --resume `
  --insecure
```

批次狀態位於 `data/processed/batch_status.json`；程式依序抓取，不使用平行請求。

## 官方 portal 補充資料與多來源合併

舊入口若未正確套用自動化篩選，`scrape` 會中止而不再寫出可能錯誤的 CSV。可改用官方 `portal/Where/Search` 補充特定資料；此指令會保留原始 JSON 與 `data_source=portal_where`：

```powershell
ldts scrape-portal `
  --lab-name centogene `
  --output data\processed\centogene_portal.csv `
  --raw-output data\raw\centogene_portal.json `
  --insecure
```

將既有舊入口 CSV 與 portal CSV 依「案件編號」合併、去重，並保留 `data_sources` 來源追溯欄位。若同案號同時存在，portal 的縣市、醫療機構、檢測名稱／類別及認證實驗室資料優先；portal 未提供的分析標的、價格等欄位才由舊入口補足：

```powershell
ldts merge-sources `
  --input-csv data\processed\new_taipei_full.csv `
  --input-csv data\processed\centogene_portal.csv `
  --output data\processed\new_taipei_merged.csv
```

合併後再以 `new_taipei_merged.csv` 執行 `ldts analyze`。請保留原始 CSV 和 portal JSON，不要用合併檔覆寫它們。

## 增量更新：只補新增案件

`update-portal` 會以目前的合併 CSV 當作 baseline，向官方 portal 取得一次最新清單後，只輸出其中「案件編號尚未存在於 baseline」的案件。它不會逐筆重抓歷史案件，也不會覆寫你的舊 CSV。

```powershell
ldts update-portal `
  --baseline data\processed\taiwan_merged_normalized.csv `
  --output data\processed\portal_incremental.csv `
  --merged-output data\processed\taiwan_merged_updated.csv `
  --raw-output data\raw\portal_update_snapshot.json `
  --insecure
```

輸出說明：

- `portal_incremental.csv`：只有本次新發現的案件；若沒有新增案件，程式只會顯示 `0 筆`，不會改動舊檔。
- `taiwan_merged_updated.csv`：原 baseline 加上新增案件的安全新檔；原 baseline 不會被覆寫。
- `portal_incremental_changed_existing.csv`：逐欄列出既有案件的重要差異（案件編號、欄位、baseline 值、portal 值），可直接用 Excel 人工複核。
- `portal_incremental_quality.json`：列出新增案件編號與重要差異案件的彙總；程式不會自動覆寫這類案件。portal 空白欄位及價格／分析標的的格式差異不會列為變更。

目前官方 portal 查詢沒有「自某日期／案件編號後」的公開篩選參數，因此每次更新仍會取得一份最新清單來比對；但這是一次節流後的請求與本機案件編號比較，不是重新逐頁／逐案爬取數千筆舊資料。若 baseline 只涵蓋特定檢測類別，請在更新時用相同的重複 `--category` 條件，避免把其他類別誤判成新增。

## 單一 CSV 分析

```powershell
ldts analyze `
  --input-csv data\processed\taipei_full.csv `
  --output-dir reports\taipei_full
Start-Process .\reports\taipei_full\ldts_analysis_report.html
```

報告包括合作網絡、Portfolio Explorer、縣市篩選、互動圖表、地圖、panel size 價格摘要與品質限制。互動圖表與地圖需要網路載入 Plotly、Leaflet、OpenStreetMap。

## 多 CSV 合併分析

```powershell
ldts analyze `
  --input-csv data\processed\taipei_full.csv `
  --input-csv data\processed\taichung_full.csv `
  --output-dir reports\taiwan_all_categories
```

自動帶入所有完整 CSV：

```powershell
$csvArgs = @()
Get-ChildItem .\data\processed\*_full*.csv |
  Where-Object { $_.Name -notmatch "manual_review" } |
  ForEach-Object { $csvArgs += "--input-csv"; $csvArgs += $_.FullName }
ldts analyze @csvArgs --output-dir reports\taiwan_all_categories
```

整合報告會產生 `city_summary.csv`，包含 22 個縣市的案件數與醫療機構數；無案件縣市會列為 0。

## 只分析指定類別

完整 CSV 會保留所有類別，分析時使用重複的 `--category` 篩選：

```powershell
ldts analyze `
  --input-csv data\processed\taipei_full.csv `
  --input-csv data\processed\taichung_full.csv `
  --output-dir reports\target_categories `
  --category "癌症篩檢、診斷、治療及預後之基因檢測" `
  --category "產前及新生兒染色體與基因變異檢測" `
  --category "遺傳代謝與罕見疾病之基因檢測"
```

不指定 `--category` 即分析所有類別。常用類別也位於 `config/target_categories.txt`。

## 品質檢查

```powershell
Get-Content data\processed\taipei_full_quality.json
```

正式分析前應確認：

```text
rows = unique_case_ids
duplicate_case_ids = 0
missing_required = 0
```

## GitHub 分享注意事項

不要提交 `.venv/`、`.env`、大量 raw HTML、未驗證完整 CSV 或敏感本機檔案。建議提交 `src/`、`tests/`、`config/`、`docs/`、README 與脫敏 fixture。大型資料可使用 Git LFS 或受控儲存，並確認符合網站使用規範。

## 重要限制

登記案件數不是實際檢測量、營收或市占率；機構登記所在地也不等於實際服務範圍。價格應依檢測類別、panel size、樣本類型與價格 basis 分組比較；`price_per_gene` 僅為輔助欄位。網站勘查紀錄位於 `docs/site_reconnaissance.md`。
