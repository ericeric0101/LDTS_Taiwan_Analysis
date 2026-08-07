"""HTML table parser. Selects the table by header names, not fragile CSS classes."""
from __future__ import annotations
from bs4 import BeautifulSoup
import re
import unicodedata

FIELDS = ["案件編號", "縣市", "醫療機構名稱", "檢測項目名稱", "分析標的", "檢測項目類別", "費用(新台幣)", "認證實驗室名稱", "認證實驗室所屬機構"]
ALIASES = {"費用（新台幣）": "費用(新台幣)", "費用": "費用(新台幣)"}

# 官網案件編號有多個合法系列，例如 2026LDTS00053、2023LDTB0064。
# 不以某一個固定字尾（如 LDTS）判斷資料是否有效，避免舊批次資料被漏掉。
CASE_ID_PATTERN = re.compile(r"^(?P<year>20\d{2})(?P<series>LDT[A-Z]*)(?P<number>\d+)$")

def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def normalize_case_id(value: str) -> str:
    """Normalize display noise without changing the official LDT series."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or "")).upper()


def case_id_series(value: str) -> str:
    """Return the official series (LDT/LDTB/LDTS/...) or ``unknown``."""
    match = CASE_ID_PATTERN.fullmatch(normalize_case_id(value))
    return match.group("series") if match else "unknown"

def parse_table(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows: continue
        headers = [clean_text(c.get_text(" ", strip=True)) for c in rows[0].find_all(["th", "td"])]
        headers = [ALIASES.get(h, h) for h in headers]
        if not {"案件編號", "醫療機構名稱", "檢測項目名稱"}.issubset(headers): continue
        out = []
        for row in rows[1:]:
            cells = [clean_text(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
            if len(cells) != len(headers): continue
            item = dict(zip(headers, cells))
            if item.get("案件編號"):
                item["案件編號"] = normalize_case_id(item["案件編號"])
                out.append({f: item.get(f, "") for f in FIELDS})
        return out
    raise ValueError("找不到包含必要欄位的結果表格")
