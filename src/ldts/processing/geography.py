"""Conservative county/city normalization for official LDTS source values."""
from __future__ import annotations


CITY_ALIASES = {
    "臺北": "臺北市",
    "台北": "臺北市",
    "台北市": "臺北市",
    "臺北縣": "新北市",
    "新北勢": "新北市",
    "馨北市": "新北市",
    "221": "新北市",  # 汐止區郵遞區號，來源未回傳縣市名稱
    "新竹": "新竹市",
    "南投市": "南投縣",
    "員林鎮": "彰化縣",
    "彰化市": "彰化縣",
    "屏東市": "屏東縣",
    "高雄": "高雄市",
    "801": "高雄市",  # 前金區郵遞區號
    "970": "花蓮縣",  # 花蓮市郵遞區號
}

# Only use institution fallbacks where the public institution identity is
# unambiguous. This closes isolated blanks without guessing from lab names.
INSTITUTION_CITY_ALIASES = {
    "郭綜合醫院": "臺南市",
}


def normalize_city(value: str) -> str:
    """Return one of Taiwan's county/city names when the source is unambiguous."""
    text = "".join((value or "").split()).replace("台", "臺")
    return CITY_ALIASES.get(text, text)


def normalize_city_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Normalize direct aliases and infer blanks only from a unique institution match."""
    output = [dict(row) for row in rows]
    institution_cities: dict[str, set[str]] = {}
    for row in output:
        raw = row.get("縣市", "")
        city = normalize_city(raw)
        row["city_raw"] = row.get("city_raw") or raw
        row["縣市"] = city
        institution = row.get("醫療機構名稱", "")
        if institution and city:
            institution_cities.setdefault(institution, set()).add(city)
    for row in output:
        if row.get("縣市"):
            continue
        known_city = INSTITUTION_CITY_ALIASES.get(row.get("醫療機構名稱", ""))
        if known_city:
            row["縣市"] = known_city
            continue
        candidates = institution_cities.get(row.get("醫療機構名稱", ""), set())
        if len(candidates) == 1:
            row["縣市"] = next(iter(candidates))
    return output
