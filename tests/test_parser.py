from ldts.cli import _query_result_is_verified
from ldts.scraper.parser import case_id_series, normalize_case_id, parse_table

def test_parse_wrapped_cells():
    html='''<table><tr><th>案件編號</th><th>縣市</th><th>醫療機構名稱</th><th>檢測項目名稱</th><th>分析標的</th><th>檢測項目類別</th><th>費用（新台幣）</th><th>認證實驗室名稱</th><th>認證實驗室所屬機構</th></tr><tr><td>2026LDTS00001</td><td>臺北市</td><td>甲<br>診所</td><td>基因<br>檢測</td><td>BRCA1, BRCA2</td><td>癌症</td><td>4,000</td><td>實驗室A</td><td>機構A</td></tr></table>'''
    row=parse_table(html)[0]
    assert row["案件編號"] == "2026LDTS00001"
    assert row["醫療機構名稱"] == "甲 診所"
    assert row["費用(新台幣)"] == "4,000"


def test_case_id_variants_are_kept_distinct_and_supported():
    assert normalize_case_id(" 2026 ldts00053 ") == "2026LDTS00053"
    assert case_id_series("2024LDT0026") == "LDT"
    assert case_id_series("2023LDTB0064") == "LDTB"
    assert case_id_series("2026LDTS00053") == "LDTS"


def test_query_verification_rejects_an_unfiltered_default_page():
    rows = [{"縣市": "臺中市", "認證實驗室名稱": "其他實驗室"}]
    assert not _query_result_is_verified(rows, city="新北市", institution="", test_name="", lab_name="")
    assert not _query_result_is_verified(rows, city="", institution="", test_name="", lab_name="centogene")
