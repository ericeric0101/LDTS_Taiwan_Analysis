"""HTML table parser. Selects the table by header names, not fragile CSS classes."""
from __future__ import annotations
from bs4 import BeautifulSoup
import re

FIELDS = ["案件編號", "縣市", "醫療機構名稱", "檢測項目名稱", "分析標的", "檢測項目類別", "費用(新台幣)", "認證實驗室名稱", "認證實驗室所屬機構"]
ALIASES = {"費用（新台幣）": "費用(新台幣)", "費用": "費用(新台幣)"}

def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()

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
                out.append({f: item.get(f, "") for f in FIELDS})
        return out
    raise ValueError("找不到包含必要欄位的結果表格")
