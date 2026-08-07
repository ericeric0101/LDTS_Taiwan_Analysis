from ldts.processing.cleaner import parse_application_year, parse_price, parse_genes, normalize_name, normalize_test_name

def test_price_range():
    x = parse_price("血液：4,000 元")
    assert x["price_min_twd"] == 4000
    assert x["price_basis"] == "blood"

def test_gene_list():
    x = parse_genes("BRCA1, BRCA2, BRCA1")
    assert x["extracted_genes"] == "BRCA1;BRCA2"
    assert x["gene_count_final"] == 2

def test_non_gene_terms_are_excluded():
    x = parse_genes("RRNA, BRCA1, DNA")
    assert x["extracted_genes"] == "BRCA1"

def test_normalize_name():
    assert normalize_name(" 台灣 生醫 ") == "臺灣生醫"

def test_zero_gene_count_is_unknown():
    from ldts.processing.cleaner import enrich
    row = {"分析標的": "", "費用(新台幣)": "5,000", "醫療機構名稱": "甲", "認證實驗室名稱": "乙"}
    x = enrich(row)
    assert x["panel_size_group"] == "unknown"
    assert x["price_per_gene_twd"] == ""

def test_application_year_supports_ldt_variants():
    assert parse_application_year("2024LDT0026") == 2024
    assert parse_application_year("2023LDTB0064") == 2023
    assert parse_application_year("2026LDTS00053") == 2026
    assert parse_application_year("not-a-case") == ""

def test_test_name_comparison_key_is_conservative():
    assert normalize_test_name("NIPT-1.0（經典款）") == normalize_test_name("NIPT 1.0 經典款")
    assert normalize_test_name("NIPT-1.0") != normalize_test_name("NIPT-2.0")
