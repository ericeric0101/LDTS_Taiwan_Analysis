from pathlib import Path
from urllib.parse import urlencode
import csv, typer, json, hashlib
from datetime import datetime, timezone
from .scraper.client import Client
from .scraper.parser import case_id_series, normalize_case_id, parse_table
from .processing.cleaner import enrich
from .analysis.report import build_report
app = typer.Typer()

def _quality(rows):
    required = ["案件編號", "縣市", "醫療機構名稱", "檢測項目名稱"]
    ids = [normalize_case_id(r.get("案件編號", "")) for r in rows]
    series_counts = {}
    for case_id in ids:
        series = case_id_series(case_id)
        series_counts[series] = series_counts.get(series, 0) + 1
    return {"rows": len(rows), "unique_case_ids": len(set(ids)), "duplicate_case_ids": len(ids) - len(set(ids)), "missing_required": sum(any(not r.get(k) for k in required) for r in rows), "case_id_series": series_counts}

@app.command("scrape")
def scrape(
    city: str = typer.Option("", help="縣市；目前先以取得頁面後本地篩選"),
    institution: str = typer.Option("", "--institution", help="醫療機構名稱；送至網站表單查詢"),
    test_name: str = typer.Option("", "--test-name", help="檢測項目名稱；送至網站表單查詢"),
    lab_name: str = typer.Option("", "--lab-name", help="認證實驗室名稱；送至網站表單查詢"),
    local_lab_name: str = typer.Option("", "--local-lab-name", help="本機以認證實驗室名稱部分比對；仍會抓取該縣市所有頁面"),
    max_pages: int = typer.Option(1, "--max-pages", min=1, max=200),
    url: str = typer.Option("https://ldts.mohw.gov.tw/main_ch/apyList.aspx?uid=2155&pid=63"),
    output: Path = typer.Option(Path("data/processed/taipei_preview.csv")),
    insecure: bool = typer.Option(False, "--insecure", help="停用 TLS 憑證驗證；僅限憑證鏈問題時臨時使用"),
    resume: bool = typer.Option(False, "--resume", help="讀取既有 CSV/raw，從最後已完成頁面繼續"),
):
    """Phase 1 proof-of-concept：最多抓取兩頁並保存原始 HTML。"""
    if insecure:
        typer.echo("警告：本次請求將停用 TLS 憑證驗證。")
    client = Client(verify=not insecure)
    all_rows = []
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started_at = datetime.now(timezone.utc).isoformat()
    pages_meta = []
    start_page = 1
    if resume and output.exists():
        with output.open(encoding="utf-8-sig", newline="") as f: all_rows = list(csv.DictReader(f))
        cached_pages = sorted(client.raw_dir.glob("*_page*.html"), key=lambda p: p.stat().st_mtime)
        if cached_pages:
            import re
            last_path = cached_pages[-1]; match = re.search(r"_page(\d+)\.html$", last_path.name)
            if match:
                start_page = int(match.group(1)) + 1
                current_html = last_path.read_text(encoding="utf-8")
                client.get(url, force=True)  # 建立新的 session/cookies，再以快取頁面的 ViewState 繼續
                typer.echo(f"續抓：既有 {len(all_rows)} 筆，從第 {start_page} 頁開始")
    if start_page == 1:
        html, raw_path = client.get(url, force=True)
        query_html = client.aspnet_postback(url, html, "ctl00$ContentPlaceHolder1$lkb_sh", {
            "ctl00$ContentPlaceHolder1$txt_city": city,
            "ctl00$ContentPlaceHolder1$txt_MIname": institution,
            "ctl00$ContentPlaceHolder1$txtName": test_name,
            "ctl00$ContentPlaceHolder1$txtLabName": lab_name,
        })
        query_path = client.save(url, query_html, "query")
        typer.echo(f"查詢結果 raw={query_path}")
        pages_meta.append({"page": 1, "kind": "query", "raw_path": str(query_path), "sha256": hashlib.sha256(query_html.encode()).hexdigest()})
        current_html = query_html
    seen_ids = {normalize_case_id(r.get("案件編號", "")) for r in all_rows if r.get("案件編號")}
    duplicate_pages = []
    for page in range(start_page, max_pages + 1):
        request_url = url
        try:
            rows = parse_table(current_html)
        except Exception as exc:
            raise typer.BadParameter(f"第 {page} 頁抓取或解析失敗：{exc}") from exc
        page_row_count = len(rows)
        if local_lab_name:
            keyword = local_lab_name.casefold()
            rows = [row for row in rows if keyword in row.get("認證實驗室名稱", "").casefold()]
        row_ids = {normalize_case_id(r.get("案件編號", "")) for r in rows if r.get("案件編號")}
        repeated = row_ids & seen_ids
        actual_page = client.current_page_number(current_html) or page
        if repeated:
            duplicate_pages.append({"page": actual_page, "duplicate_case_ids": sorted(repeated)})
            typer.echo(f"警告：第 {actual_page} 頁與既有資料重複 {len(repeated)} 筆，停止以避免污染資料")
            break
        all_rows.extend(enrich(r) for r in rows); seen_ids.update(row_ids)
        if local_lab_name:
            typer.echo(f"第 {actual_page} 頁：原始 {page_row_count} 筆，實驗室篩選後 {len(rows)} 筆")
        else:
            typer.echo(f"第 {actual_page} 頁：{len(rows)} 筆")
        if actual_page >= max_pages:
            break
        page = actual_page
        if page < max_pages:
            target = client.next_page_target(current_html)
            if not target:
                break
            current_html = client.aspnet_postback(url, current_html, target)
            actual_next = client.current_page_number(current_html) or (page + 1)
            page_path = client.save(url, current_html, f"page{actual_next}")
            pages_meta.append({"page": actual_next, "kind": "pagination", "raw_path": str(page_path), "sha256": hashlib.sha256(current_html.encode()).hexdigest()})
    if not all_rows:
        raise typer.BadParameter("沒有解析到資料；請先確認站台連線與實際表單／分頁機制。")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=all_rows[0].keys()); w.writeheader(); w.writerows(all_rows)
    typer.echo(f"完成：{len(all_rows)} 筆 -> {output}")
    review_rows = [r for r in all_rows if r.get("manual_review_required")]
    review_path = output.with_name(output.stem + "_manual_review.csv")
    if review_rows:
        with review_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=review_rows[0].keys()); w.writeheader(); w.writerows(review_rows)
    else:
        review_path.write_text("", encoding="utf-8-sig")
    typer.echo(f"人工複核清單：{review_path}（{len(review_rows)} 筆）")
    quality = _quality(all_rows)
    quality_path = output.with_name(output.stem + "_quality.json")
    quality.update({"run_id": run_id, "started_at": started_at, "finished_at": datetime.now(timezone.utc).isoformat(), "city": city, "filters": {"institution": institution, "test_name": test_name, "lab_name": lab_name, "local_lab_name": local_lab_name}, "source_url": url, "pages": len(pages_meta), "raw_pages": pages_meta, "duplicate_pages": duplicate_pages, "manual_review_count": sum(bool(r.get("manual_review_required")) for r in all_rows)})
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"品質報告：{quality_path}")
    typer.echo(f"品質檢查：{_quality(all_rows)}")

@app.command("scrape-batch")
def scrape_batch(
    city: list[str] = typer.Option(None, "--city", help="可重複指定，例如 --city 臺北市 --city 臺中市"),
    cities_file: Path = typer.Option(None, "--cities-file", help="每行一個縣市名稱"),
    max_pages: int = typer.Option(1, "--max-pages", min=1, max=200),
    output_dir: Path = typer.Option(Path("data/processed"), "--output-dir"),
    insecure: bool = typer.Option(False, "--insecure"),
    resume: bool = typer.Option(False, "--resume", help="跳過已有成功品質報告的縣市"),
):
    """依序抓取多個縣市；不使用平行請求。"""
    cities = list(city or [])
    if cities_file:
        cities.extend(x.strip() for x in cities_file.read_text(encoding="utf-8-sig").splitlines() if x.strip() and not x.strip().startswith("#"))
    cities = list(dict.fromkeys(cities))
    if not cities:
        raise typer.BadParameter("請至少提供 --city 或 --cities-file")
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "batch_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if resume and status_path.exists() else {}
    for current_city in cities:
        safe = {"臺北市":"taipei", "新北市":"new_taipei", "桃園市":"taoyuan", "臺中市":"taichung", "臺南市":"tainan", "高雄市":"kaohsiung"}.get(current_city, current_city.replace("臺", "tai").replace("台", "tai").replace("市", "").replace("縣", "_county").replace(" ", "_"))
        output = output_dir / f"{safe}_full.csv"
        existing_valid = False
        for candidate in sorted(output_dir.glob(f"{safe}_full*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
            quality_candidate = candidate.with_name(candidate.stem + "_quality.json")
            try:
                q = json.loads(quality_candidate.read_text(encoding="utf-8"))
                existing_valid = candidate.exists() and q.get("rows") == q.get("unique_case_ids") and q.get("duplicate_case_ids", 0) == 0 and q.get("missing_required", 1) == 0
            except (FileNotFoundError, json.JSONDecodeError):
                existing_valid = False
            if existing_valid:
                break
        if resume and (status.get(current_city, {}).get("status") == "success" or existing_valid):
            typer.echo(f"跳過已完成：{current_city}")
            continue
        typer.echo(f"開始抓取：{current_city}")
        try:
            scrape(city=current_city, max_pages=max_pages, url="https://ldts.mohw.gov.tw/main_ch/apyList.aspx?uid=2155&pid=63", output=output, insecure=insecure, resume=False)
            status[current_city] = {"status": "success", "output": str(output), "updated_at": datetime.now(timezone.utc).isoformat()}
        except Exception as exc:
            status[current_city] = {"status": "failed", "error": str(exc), "updated_at": datetime.now(timezone.utc).isoformat()}
            typer.echo(f"失敗：{current_city}：{exc}", err=True)
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"批次狀態：{status_path}")

@app.command("parse")
def parse(path: Path, output: Path = Path("data/processed/records.csv")):
    rows = [enrich(r) for r in parse_table(path.read_text(encoding="utf-8"))]; output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    typer.echo(f"解析 {len(rows)} 筆：{output}")

@app.command("analyze")
def analyze(input_csv: list[Path] = typer.Option(None, "--input-csv", help="可重複指定多個 CSV"), output_dir: Path = typer.Option(Path("reports/taiwan_preview"), "--output-dir"), category: list[str] = typer.Option(None, "--category", help="可重複指定檢測類別"), all_categories: bool = typer.Option(False, "--all-categories", help="忽略 target_categories.txt，分析全部類別"), reference_year: int = typer.Option(None, "--reference-year", min=2000, max=2100, help="年份追蹤比較基準；預設為今年")):
    """合併一個或多個 CSV，產生摘要表與 HTML 分析報告。"""
    paths = input_csv or [Path("data/processed/taipei_preview.csv")]
    missing = [str(p) for p in paths if not p.exists()]
    if missing: raise typer.BadParameter("找不到 CSV：" + ", ".join(missing))
    selected_categories = category or None
    if not selected_categories and not all_categories:
        target_file = Path("config/target_categories.txt")
        if target_file.exists():
            selected_categories = [x.strip() for x in target_file.read_text(encoding="utf-8-sig").splitlines() if x.strip() and not x.startswith("#")]
    report = build_report(paths, output_dir, selected_categories, reference_year=reference_year)
    typer.echo(f"合併檔案：{len(paths)} 個")
    if selected_categories: typer.echo(f"分析類別：{', '.join(selected_categories)}")
    elif all_categories: typer.echo("分析類別：全部")
    if reference_year: typer.echo(f"年份追蹤基準年：{reference_year}")
    typer.echo(f"分析完成：{report}")

if __name__ == "__main__": app()
