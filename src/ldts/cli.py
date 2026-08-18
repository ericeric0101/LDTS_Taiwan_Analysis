from pathlib import Path
from urllib.parse import urlencode
import csv, typer, json, hashlib
from datetime import datetime, timezone
from .scraper.client import Client
from .scraper.parser import FIELDS, case_id_series, normalize_case_id, parse_table
from .scraper.portal import PORTAL_SEARCH_URL, PortalClient
from .processing.geography import normalize_city_rows
from .processing.cleaner import enrich
from .analysis.report import build_report
app = typer.Typer()


def _normalized_text(value: str) -> str:
    """Normalize display variations without altering the source value."""
    return "".join((value or "").casefold().split()).replace("台", "臺")


def _query_result_is_verified(rows: list[dict[str, str]], *, city: str, institution: str, test_name: str, lab_name: str) -> bool:
    """Return whether every returned row satisfies the filters sent to the site.

    The legacy site sometimes returns its unfiltered default listing with HTTP 200
    when it does not accept an automated form postback.  Treat that as a failed
    query rather than silently writing misleading CSV data.
    """
    checks = (
        ("縣市", city, True),
        ("醫療機構名稱", institution, False),
        ("檢測項目名稱", test_name, False),
        ("認證實驗室名稱", lab_name, False),
    )
    for column, requested, exact in checks:
        needle = _normalized_text(requested)
        if not needle:
            continue
        values = [_normalized_text(row.get(column, "")) for row in rows]
        if exact:
            if not all(value == needle for value in values):
                return False
        elif not all(needle in value for value in values):
            return False
    return True

def _quality(rows):
    required = ["案件編號", "縣市", "醫療機構名稱", "檢測項目名稱"]
    ids = [normalize_case_id(r.get("案件編號", "")) for r in rows]
    series_counts = {}
    for case_id in ids:
        series = case_id_series(case_id)
        series_counts[series] = series_counts.get(series, 0) + 1
    return {"rows": len(rows), "unique_case_ids": len(set(ids)), "duplicate_case_ids": len(ids) - len(set(ids)), "missing_required": sum(any(not r.get(k) for k in required) for r in rows), "case_id_series": series_counts}


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise typer.BadParameter("沒有可輸出的資料")
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


PORTAL_AUTHORITATIVE_FIELDS = (
    "縣市",
    "醫療機構名稱",
    "檢測項目名稱",
    "檢測項目類別",
    "認證實驗室名稱",
    "認證實驗室所屬機構",
)


def _merge_portal_record(existing: dict[str, str], portal: dict[str, str], sources: set[str]) -> dict[str, str]:
    """Use portal for current registration identity, preserving legacy detail gaps."""
    merged = dict(existing)
    for key, value in portal.items():
        if key in {"data_source", "data_sources"}:
            continue
        if key in PORTAL_AUTHORITATIVE_FIELDS:
            if value:
                merged[key] = value
        elif not merged.get(key) and value:
            merged[key] = value
    merged["data_source"] = "portal_where"
    merged["data_sources"] = ";".join(sorted(sources))
    return merged


def _merge_source_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Deduplicate by official case ID while retaining source provenance."""
    merged: dict[str, dict[str, str]] = {}
    for row in normalize_city_rows(rows):
        item = dict(row)
        case_id = normalize_case_id(item.get("案件編號", ""))
        if not case_id:
            continue
        item["案件編號"] = case_id
        source = item.get("data_source", "legacy_apy_list")
        if case_id not in merged:
            item["data_sources"] = source
            merged[case_id] = item
            continue
        previous = merged[case_id]
        sources = set(filter(None, previous.get("data_sources", "").split(";"))) | {source}
        if source == "portal_where":
            merged[case_id] = _merge_portal_record(previous, item, sources)
            continue
        if previous.get("data_source") == "portal_where":
            # A later legacy row must never replace verified portal identity
            # fields, but can still fill a portal blank such as price/target.
            merged[case_id] = _merge_portal_record(item, previous, sources)
            continue
        # Preserve the fuller business row, but do not let provenance fields
        # influence that comparison.
        score = lambda value: sum(bool(cell) for key, cell in value.items() if key not in {"data_source", "data_sources"})
        if score(item) > score(previous):
            item["data_sources"] = ";".join(sorted(sources))
            merged[case_id] = item
        else:
            previous["data_sources"] = ";".join(sorted(sources))
    return list(merged.values())


MATERIAL_PORTAL_FIELDS = (
    "縣市",
    "醫療機構名稱",
    "檢測項目名稱",
    "檢測項目類別",
    "認證實驗室名稱",
    "認證實驗室所屬機構",
)


def _portal_increment(
    baseline_rows: list[dict[str, str]],
    portal_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return new official case IDs and row-level material differences.

    Case ID is the stable append key.  A changed-ID list is reported separately
    for human review; this incremental workflow never overwrites an existing
    case silently.  Empty portal fields and presentation-only price/target
    differences are intentionally excluded because the portal often omits them.
    """
    baseline_by_id = {
        normalize_case_id(row.get("案件編號", "")): row
        for row in baseline_rows
        if normalize_case_id(row.get("案件編號", ""))
    }
    new_rows: list[dict[str, str]] = []
    changes: list[dict[str, str]] = []
    for row in portal_rows:
        case_id = normalize_case_id(row.get("案件編號", ""))
        if not case_id:
            continue
        previous = baseline_by_id.get(case_id)
        if previous is None:
            new_rows.append(row)
            continue
        for field in MATERIAL_PORTAL_FIELDS:
            portal_value = row.get(field, "")
            baseline_value = previous.get(field, "")
            if portal_value and _normalized_text(baseline_value) != _normalized_text(portal_value):
                changes.append({
                    "案件編號": case_id,
                    "欄位": field,
                    "baseline_value": baseline_value,
                    "portal_value": portal_value,
                })
    return new_rows, changes

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
        try:
            query_rows = parse_table(query_html)
        except Exception as exc:
            raise typer.BadParameter(f"查詢結果無法解析：{exc}") from exc
        if any((city, institution, test_name, lab_name)) and not _query_result_is_verified(
            query_rows,
            city=city,
            institution=institution,
            test_name=test_name,
            lab_name=lab_name,
        ):
            raise typer.BadParameter(
                "網站未套用送出的篩選條件，改回傳未篩選預設清單；已中止以避免產生不完整或錯誤 CSV。"
            "請保留輸出的 raw HTML 供複核。"
            )
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


@app.command("scrape-portal")
def scrape_portal(
    city: str = typer.Option("", help="縣市"),
    institution: str = typer.Option("", "--institution", help="醫療機構名稱"),
    test_name: str = typer.Option("", "--test-name", help="檢測項目名稱"),
    lab_name: str = typer.Option("", "--lab-name", help="認證實驗室名稱"),
    category: list[str] = typer.Option(None, "--category", help="可重複指定檢測類別"),
    output: Path = typer.Option(Path("data/processed/portal_records.csv")),
    raw_output: Path = typer.Option(Path("data/raw/portal_query.json"), "--raw-output"),
    insecure: bool = typer.Option(False, "--insecure", help="停用 TLS 憑證驗證；僅限憑證鏈問題時臨時使用"),
):
    """抓取官方 portal/Where JSON 資料；不覆寫舊入口資料。"""
    if insecure:
        typer.echo("警告：本次請求將停用 TLS 憑證驗證。")
    client = PortalClient(verify=not insecure)
    payload, rows = client.search(
        city=city,
        institution=institution,
        test_name=test_name,
        lab_name=lab_name,
        categories=category or (),
    )
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    enriched = [enrich(row) for row in rows]
    _write_csv(output, enriched)
    quality = _quality(enriched)
    quality.update({
        "source": "portal_where",
        "source_url": PORTAL_SEARCH_URL,
        "raw_path": str(raw_output),
        "filters": {"city": city, "institution": institution, "test_name": test_name, "lab_name": lab_name, "categories": category or []},
    })
    quality_path = output.with_name(output.stem + "_quality.json")
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"portal raw：{raw_output}")
    typer.echo(f"完成：{len(enriched)} 筆 -> {output}")
    typer.echo(f"品質報告：{quality_path}")


@app.command("update-portal")
def update_portal(
    baseline: Path = typer.Option(..., "--baseline", help="目前使用中的完整／合併 CSV"),
    output: Path = typer.Option(Path("data/processed/portal_incremental.csv"), help="只包含本次新增案件的 CSV"),
    merged_output: Path = typer.Option(None, "--merged-output", help="選填：寫出舊資料加新增案件的新合併 CSV，不覆寫 baseline"),
    raw_output: Path = typer.Option(Path("data/raw/portal_update_snapshot.json"), "--raw-output", help="本次官方 portal 回應快照"),
    category: list[str] = typer.Option(None, "--category", help="可重複指定類別；未指定則檢查全部類別"),
    insecure: bool = typer.Option(False, "--insecure", help="停用 TLS 憑證驗證；僅限憑證鏈問題時臨時使用"),
):
    """以官方 portal 單次快照找出 baseline 中不存在的新案件。"""
    if not baseline.exists():
        raise typer.BadParameter(f"找不到 baseline CSV：{baseline}")
    if insecure:
        typer.echo("警告：本次請求將停用 TLS 憑證驗證。")
    with baseline.open(encoding="utf-8-sig", newline="") as f:
        baseline_rows = list(csv.DictReader(f))
    baseline_ids = {
        normalize_case_id(row.get("案件編號", ""))
        for row in baseline_rows
        if normalize_case_id(row.get("案件編號", ""))
    }
    if not baseline_ids:
        raise typer.BadParameter("baseline CSV 沒有可辨識的案件編號")

    client = PortalClient(verify=not insecure)
    payload, portal_rows = client.search(categories=category or ())
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    new_source_rows, change_rows = _portal_increment(baseline_rows, portal_rows)
    new_rows = [enrich(row) for row in new_source_rows]
    changed_ids = sorted({row["案件編號"] for row in change_rows})

    if new_rows:
        _write_csv(output, new_rows)
        typer.echo(f"新增案件：{len(new_rows)} 筆 -> {output}")
    else:
        typer.echo("新增案件：0 筆（baseline 已包含本次 portal 快照的所有案件編號）")

    if merged_output:
        # Only append truly new IDs.  Existing records are intentionally left
        # untouched, even when the portal reports changed fields.
        merged = _merge_source_rows([*baseline_rows, *new_rows])
        _write_csv(merged_output, merged)
        typer.echo(f"更新後合併檔：{len(merged)} 筆 -> {merged_output}")

    changes_path = output.with_name(output.stem + "_changed_existing.csv")
    if change_rows:
        _write_csv(changes_path, change_rows)
        typer.echo(f"既有案件重要欄位差異：{len(change_rows)} 項／{len(changed_ids)} 案 -> {changes_path}")
    else:
        changes_path.write_text(
            "案件編號,欄位,baseline_value,portal_value\n",
            encoding="utf-8-sig",
        )

    quality = {
        "source": "portal_where_incremental",
        "source_url": PORTAL_SEARCH_URL,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "baseline": str(baseline),
        "baseline_unique_case_ids": len(baseline_ids),
        "portal_rows_checked": len(portal_rows),
        "new_rows": len(new_rows),
        "new_case_ids": [row["案件編號"] for row in new_source_rows],
        "existing_case_ids_with_material_changes": changed_ids,
        "material_change_count": len(changed_ids),
        "material_field_change_count": len(change_rows),
        "changes_path": str(changes_path),
        "filters": {"categories": category or []},
        "raw_path": str(raw_output),
    }
    quality_path = output.with_name(output.stem + "_quality.json")
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"官方快照：{raw_output}")
    typer.echo(f"更新報告：{quality_path}")
    if changed_ids:
        typer.echo(f"注意：{len(changed_ids)} 筆既有案件的 portal 重要欄位不同；未自動覆寫，請查看更新報告。")


@app.command("merge-sources")
def merge_sources(
    input_csv: list[Path] = typer.Option(..., "--input-csv", help="可重複指定舊入口或 portal CSV"),
    output: Path = typer.Option(Path("data/processed/ldts_merged.csv")),
):
    """合併多來源 CSV，依案件編號去重並保留 data_sources。"""
    missing = [str(path) for path in input_csv if not path.exists()]
    if missing:
        raise typer.BadParameter("找不到 CSV：" + ", ".join(missing))
    rows: list[dict[str, str]] = []
    for path in input_csv:
        with path.open(encoding="utf-8-sig", newline="") as f:
            default_source = "portal_where" if "portal" in path.stem.casefold() else "legacy_apy_list"
            for row in csv.DictReader(f):
                row["data_source"] = row.get("data_source") or default_source
                rows.append(row)
    merged = _merge_source_rows(rows)
    _write_csv(output, merged)
    quality = _quality(merged)
    quality.update({"input_csv": [str(path) for path in input_csv], "source_count": len(input_csv)})
    quality_path = output.with_name(output.stem + "_quality.json")
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"合併：{len(rows)} 筆來源資料 -> {len(merged)} 筆唯一案件 -> {output}")
    typer.echo(f"品質報告：{quality_path}")

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
