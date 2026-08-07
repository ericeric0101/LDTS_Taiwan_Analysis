from __future__ import annotations
from datetime import date
import re
import unicodedata

def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = re.sub(r"[\s　]+", " ", value).strip()
    value = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", value)
    return value.replace("台", "臺")

def parse_price(raw: str) -> dict[str, object]:
    text = (raw or "").replace(",", "")
    nums = [int(x) for x in re.findall(r"\d+", text)]
    result = {"price_min_twd": "", "price_max_twd": "", "representative_price_twd": "", "price_basis": "unspecified", "price_parse_warning": ""}
    if not nums:
        result["price_parse_warning"] = "未找到價格數字" if raw else "空白價格"
        return result
    result["price_min_twd"], result["price_max_twd"] = min(nums), max(nums)
    result["representative_price_twd"] = (min(nums) + max(nums)) / 2
    if "血液" in raw: result["price_basis"] = "blood"
    elif "/次" in raw or "/每次" in raw: result["price_basis"] = "per_run"
    elif len(nums) == 1: result["price_basis"] = "per_test"
    if len(nums) > 1 and "血液" not in raw and "元" not in raw:
        result["price_parse_warning"] = "多個數字，需人工確認"
    return result

GENE_RE = re.compile(r"\b[A-Z][A-Z0-9-]{1,14}\b")
NON_GENES = {"DNA", "RNA", "RRNA", "MRNA", "TRNA", "FMR", "HRD", "GII", "NGS", "CNV", "WES", "WGS", "PCR", "SNP", "HLA", "MLPA", "FISH", "STR", "QF"}

def parse_genes(raw: str) -> dict[str, object]:
    text = raw or ""
    genes = []
    for gene in GENE_RE.findall(text.upper()):
        if gene not in NON_GENES and gene not in genes: genes.append(gene)
    broad = any(x in text.upper() for x in ("全外顯子", "全基因組", "WES", "WGS"))
    warning = "廣泛檢測，不計基因數" if broad else ("大型 panel，建議人工複核" if len(genes) > 200 else "")
    confidence = "low" if broad or not genes else ("medium" if len(genes) > 50 else "high")
    return {"extracted_genes": ";".join(genes), "gene_count_final": len(genes) if not broad else "", "gene_count_method": "explicit_list" if genes and not broad else ("exome_not_applicable" if broad else "unknown"), "gene_parse_confidence": confidence, "gene_parse_warning": warning}

def parse_application_year(case_id: str) -> int | str:
    """Extract the leading year from official LDT/LDTB/LDTS identifiers."""
    match = re.match(r"^(20\d{2})LDT[A-Z]*\d+$", re.sub(r"\s+", "", case_id or "").upper())
    return int(match.group(1)) if match else ""

def normalize_test_name(value: str) -> str:
    """Conservative comparison key; keep version numbers meaningful."""
    return re.sub(r"[\s\-_/、，,()（）]+", "", unicodedata.normalize("NFKC", value or "")).casefold()

def enrich(row: dict[str, str], reference_year: int | None = None) -> dict[str, object]:
    out = dict(row)
    out.update(parse_price(row.get("費用(新台幣)", row.get("費用（新台幣）", ""))))
    out.update(parse_genes(row.get("分析標的", "")))
    out["medical_institution_name_normalized"] = normalize_name(row.get("醫療機構名稱", ""))
    out["accredited_lab_name_normalized"] = normalize_name(row.get("認證實驗室名稱", ""))
    application_year = parse_application_year(str(row.get("案件編號", "")))
    out["application_year"] = application_year
    current_year = reference_year if reference_year is not None else date.today().year
    out["years_since_application"] = current_year - application_year if application_year else ""
    count = out.get("gene_count_final")
    if isinstance(count, int) and count > 0:
        out["panel_size_group"] = "single_gene" if count == 1 else "very_small_panel" if count <= 10 else "small_panel" if count <= 50 else "medium_panel" if count <= 200 else "large_panel" if count <= 500 else "very_large_panel"
        price = out.get("representative_price_twd")
        out["price_per_gene_twd"] = round(price / count, 2) if isinstance(price, (int, float)) and count > 1 else ""
    else:
        out["panel_size_group"] = "unknown"
        out["price_per_gene_twd"] = ""
    out["manual_review_required"] = bool(out.get("price_parse_warning") or out.get("gene_parse_warning"))
    return out
