from ldts.cli import _merge_source_rows, _portal_increment
from ldts.processing.geography import normalize_city_rows
from ldts.scraper.portal import portal_records


def test_portal_records_use_canonical_columns_and_preserve_source():
    payload = {
        "success": True,
        "data": [{
            "caseNo": "2024LDT2178",
            "city": "台北市",
            "hospital": "衛生福利部雙和醫院",
            "testName": "Centogene BRCA1/2基因突變檢測",
            "target": "",
            "category": "癌症篩檢、診斷、治療及預後之基因檢測",
            "price": "",
            "labName": "Centogene GmbH",
            "labOrg": "",
        }],
    }
    row = portal_records(payload)[0]
    assert row["案件編號"] == "2024LDT2178"
    assert row["縣市"] == "臺北市"
    assert row["認證實驗室名稱"] == "Centogene GmbH"
    assert row["data_source"] == "portal_where"


def test_merge_sources_deduplicates_case_id_and_keeps_all_sources():
    merged = _merge_source_rows([
        {"案件編號": "2024LDT2178", "醫療機構名稱": "雙和醫院", "data_source": "legacy_apy_list"},
        {"案件編號": "2024LDT2178", "醫療機構名稱": "雙和醫院", "認證實驗室名稱": "Centogene GmbH", "data_source": "portal_where"},
    ])
    assert len(merged) == 1
    assert merged[0]["認證實驗室名稱"] == "Centogene GmbH"
    assert merged[0]["data_sources"] == "legacy_apy_list;portal_where"


def test_merge_sources_prefers_portal_identity_fields_and_keeps_legacy_details():
    merged = _merge_source_rows([
        {
            "案件編號": "2024LDTS00062",
            "縣市": "新竹縣",
            "醫療機構名稱": "舊機構名稱",
            "分析標的": "BRCA1",
            "費用(新台幣)": "30000",
            "data_source": "legacy_apy_list",
        },
        {
            "案件編號": "2024LDTS00062",
            "縣市": "臺北市",
            "醫療機構名稱": "王家瑋婦產科診所",
            "認證實驗室名稱": "英緹檢測服務實驗室",
            "data_source": "portal_where",
        },
    ])
    row = merged[0]
    assert row["縣市"] == "臺北市"
    assert row["醫療機構名稱"] == "王家瑋婦產科診所"
    assert row["分析標的"] == "BRCA1"
    assert row["費用(新台幣)"] == "30000"
    assert row["data_source"] == "portal_where"


def test_city_normalization_handles_portal_typos_townships_and_postcodes():
    rows = normalize_city_rows([
        {"縣市": "臺北縣", "醫療機構名稱": "甲"},
        {"縣市": "員林鎮", "醫療機構名稱": "乙"},
        {"縣市": "馨北市", "醫療機構名稱": "丙"},
        {"縣市": "221", "醫療機構名稱": "丁"},
        {"縣市": "", "醫療機構名稱": "甲"},
        {"縣市": "", "醫療機構名稱": "郭綜合醫院"},
    ])
    assert [row["縣市"] for row in rows] == ["新北市", "彰化縣", "新北市", "新北市", "新北市", "臺南市"]
    assert rows[2]["city_raw"] == "馨北市"


def test_portal_increment_only_returns_unseen_case_ids_and_reports_changed_existing_rows():
    baseline = [
        {"案件編號": "2026LDTS00001", "縣市": "臺北市", "醫療機構名稱": "甲診所", "檢測項目名稱": "檢測 A"},
        {"案件編號": "2026LDTS00002", "縣市": "臺北市", "醫療機構名稱": "乙診所", "檢測項目名稱": "檢測 B"},
    ]
    portal = [
        {"案件編號": "2026LDTS00001", "縣市": "台北市", "醫療機構名稱": "甲 診所", "檢測項目名稱": "檢測 A"},
        {"案件編號": "2026LDTS00002", "縣市": "臺北市", "醫療機構名稱": "乙診所", "檢測項目名稱": "修正後檢測 B"},
        {"案件編號": "2026LDTS00003", "縣市": "臺北市", "醫療機構名稱": "丙診所", "檢測項目名稱": "檢測 C"},
    ]

    new_rows, changes = _portal_increment(baseline, portal)

    assert [row["案件編號"] for row in new_rows] == ["2026LDTS00003"]
    assert changes == [{
        "案件編號": "2026LDTS00002",
        "欄位": "檢測項目名稱",
        "baseline_value": "檢測 B",
        "portal_value": "修正後檢測 B",
    }]
