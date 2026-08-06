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
