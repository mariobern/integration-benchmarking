"""Tests for generate_short_name_candidates.py."""

from generate_short_name_candidates import (
    extract_exchange_code,
    strip_corporate_suffix,
)


class TestExtractExchangeCode:
    def test_hk_symbol(self):
        assert extract_exchange_code("Equity.HK.9901/HKD") == "9901"

    def test_kr_symbol(self):
        assert extract_exchange_code("Equity.KR.005380/KRW") == "005380"

    def test_cn_symbol_with_letter_suffix(self):
        assert extract_exchange_code("Equity.JP.285A/JPY") == "285A"


class TestStripCorporateSuffix:
    def test_single_suffix_corp(self):
        assert strip_corporate_suffix("TAISEI CORP") == "TAISEI"

    def test_single_suffix_corporation(self):
        assert strip_corporate_suffix("TOYOTA MOTOR CORPORATION") == "TOYOTA MOTOR"

    def test_co_ltd_strips_both_words(self):
        assert strip_corporate_suffix("KWEICHOW MOUTAI CO LTD") == "KWEICHOW MOUTAI"

    def test_holdings_inc_strips_both_words(self):
        assert strip_corporate_suffix("BANDAI NAMCO HOLDINGS INC") == "BANDAI NAMCO"

    def test_plc_and_holdings_strip_iteratively(self):
        assert strip_corporate_suffix("HSBC HOLDINGS PLC") == "HSBC"

    def test_kabushiki_kaisha_strips_both_words(self):
        assert strip_corporate_suffix("NIPPON YUSEN KABUSHIKI KAISHA") == "NIPPON YUSEN"

    def test_dangling_ampersand_is_also_stripped(self):
        assert strip_corporate_suffix("MITSUI & CO") == "MITSUI"

    def test_meaningful_ampersand_is_preserved(self):
        assert strip_corporate_suffix("SEVEN & I HOLDINGS CO LTD") == "SEVEN & I"

    def test_group_is_never_stripped(self):
        assert strip_corporate_suffix("RAKUTEN GROUP INC") == "RAKUTEN GROUP"
        assert strip_corporate_suffix("SOFTBANK GROUP CORP") == "SOFTBANK GROUP"

    def test_industries_and_heavy_are_never_stripped(self):
        assert (
            strip_corporate_suffix("MITSUBISHI HEAVY INDUSTRIES LTD")
            == "MITSUBISHI HEAVY INDUSTRIES"
        )

    def test_no_match_returns_unchanged(self):
        assert strip_corporate_suffix("SEKISUI HOUSE") == "SEKISUI HOUSE"

    def test_typo_no_space_is_left_unchanged(self):
        assert strip_corporate_suffix("IDEMITSU KOSAN COLTD") == "IDEMITSU KOSAN COLTD"

    def test_never_strips_down_to_nothing(self):
        assert strip_corporate_suffix("CORP") == "CORP"


from generate_short_name_candidates import normalize_yahoo_name


class TestNormalizeYahooName:
    def test_already_uppercase_single_word(self):
        assert normalize_yahoo_name("TENCENT") == "TENCENT"

    def test_camel_case_two_words(self):
        assert normalize_yahoo_name("SamsungElec") == "SAMSUNG ELEC"

    def test_camel_case_three_words(self):
        assert normalize_yahoo_name("SamsungHvyInd") == "SAMSUNG HVY IND"

    def test_acronym_then_word_boundary(self):
        assert normalize_yahoo_name("SKTelecom") == "SK TELECOM"

    def test_lowercase_input(self):
        assert normalize_yahoo_name("kakaopay") == "KAKAOPAY"

    def test_already_spaced_title_case(self):
        assert normalize_yahoo_name("Hanwha Ocean") == "HANWHA OCEAN"

    def test_punctuation_replaced_not_glued(self):
        assert normalize_yahoo_name("SAMSUNG SDI CO.,LTD.") == "SAMSUNG SDI CO LTD"

    def test_apostrophe_preserved(self):
        assert normalize_yahoo_name("HENGAN INT'L") == "HENGAN INT'L"

    def test_share_class_hyphen_preserved(self):
        assert normalize_yahoo_name("ZTO EXPRESS-W") == "ZTO EXPRESS-W"
