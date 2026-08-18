"""Client for the official LDTS ``portal/Where`` JSON search endpoint."""
from __future__ import annotations

import time
from typing import Iterable

import requests

from .parser import FIELDS, normalize_case_id
from ..processing.geography import normalize_city


PORTAL_URL = "https://ldts.mohw.gov.tw/portal/Where"
PORTAL_SEARCH_URL = "https://ldts.mohw.gov.tw/portal/Where/Search"

PORTAL_FIELD_MAP = {
    "caseNo": "案件編號",
    "city": "縣市",
    "hospital": "醫療機構名稱",
    "testName": "檢測項目名稱",
    "target": "分析標的",
    "category": "檢測項目類別",
    "price": "費用(新台幣)",
    "labName": "認證實驗室名稱",
    "labOrg": "認證實驗室所屬機構",
}


def portal_records(payload: dict[str, object]) -> list[dict[str, str]]:
    """Map the public portal payload into the project's canonical field names."""
    if not payload.get("success"):
        message = payload.get("message") or "portal 查詢未成功"
        raise ValueError(str(message))
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("portal 回應缺少 data 陣列")
    records: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        row = {field: str(item.get(source, "") or "").strip() for source, field in PORTAL_FIELD_MAP.items()}
        row["案件編號"] = normalize_case_id(row["案件編號"])
        row["city_raw"] = row["縣市"]
        row["縣市"] = normalize_city(row["縣市"])
        if row["案件編號"]:
            row["data_source"] = "portal_where"
            records.append({**{field: row.get(field, "") for field in FIELDS}, "city_raw": row["city_raw"], "data_source": row["data_source"]})
    return records


class PortalClient:
    def __init__(self, delay: float = 3, timeout: int = 30, user_agent: str = "LDTSResearchBot/0.1", verify: bool = True):
        self.delay = delay
        self.timeout = timeout
        self.verify = verify
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent

    def search(
        self,
        *,
        city: str = "",
        institution: str = "",
        test_name: str = "",
        lab_name: str = "",
        categories: Iterable[str] = (),
    ) -> tuple[dict[str, object], list[dict[str, str]]]:
        data: list[tuple[str, str]] = [
            ("city", city),
            ("miName", institution),
            ("name", test_name),
            ("labName", lab_name),
        ]
        data.extend(("categories", category) for category in categories if category)
        response = self.session.post(PORTAL_SEARCH_URL, data=data, timeout=self.timeout, verify=self.verify)
        response.raise_for_status()
        payload = response.json()
        time.sleep(self.delay)
        if not isinstance(payload, dict):
            raise ValueError("portal 回應不是 JSON 物件")
        return payload, portal_records(payload)
