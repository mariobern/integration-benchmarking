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


from unittest.mock import MagicMock, patch

from generate_short_name_candidates import (
    Candidate,
    SkipReason,
    suggest_from_yahoo,
    yahoo_tickers,
)


def _feed(
    feed_id=100,
    symbol="Equity.HK.0700/HKD",
    name="0700",
):
    return {
        "feedId": feed_id,
        "symbol": symbol,
        "metadata": {
            "asset_type": "equity",
            "name": name,
        },
    }


class TestYahooTickers:
    def test_hk_zero_pads_to_four_digits(self):
        assert yahoo_tickers("HK", "700") == ["0700.HK"]

    def test_hk_already_four_digits(self):
        assert yahoo_tickers("HK", "0005") == ["0005.HK"]

    def test_kr_tries_kospi_then_kosdaq(self):
        assert yahoo_tickers("KR", "005380") == ["005380.KS", "005380.KQ"]


class TestSuggestFromYahoo:
    @patch("yfinance.Ticker")
    def test_kospi_hit_on_first_try(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.info = {"shortName": "HyundaiMtr"}
        mock_ticker_cls.return_value = mock_ticker

        candidate, skip = suggest_from_yahoo(
            _feed(symbol="Equity.KR.005380/KRW", name="005380")
        )
        assert skip is None
        assert candidate == Candidate(
            feed_id=100,
            symbol="Equity.KR.005380/KRW",
            current_name="005380",
            proposed_name="HYUNDAI MTR",
            source="yahoo_shortname",
            notes="",
        )
        mock_ticker_cls.assert_called_once_with("005380.KS")

    @patch("yfinance.Ticker")
    def test_kosdaq_fallback_when_kospi_has_no_shortname(self, mock_ticker_cls):
        kospi_miss = MagicMock()
        kospi_miss.info = {}
        kosdaq_hit = MagicMock()
        kosdaq_hit.info = {"shortName": "SomeKosdaqCo"}
        mock_ticker_cls.side_effect = [kospi_miss, kosdaq_hit]

        candidate, skip = suggest_from_yahoo(
            _feed(symbol="Equity.KR.377300/KRW", name="377300")
        )
        assert skip is None
        assert candidate.proposed_name == "SOME KOSDAQ CO"
        assert candidate.source == "yahoo_shortname"
        assert mock_ticker_cls.call_args_list[0].args == ("377300.KS",)
        assert mock_ticker_cls.call_args_list[1].args == ("377300.KQ",)

    @patch("yfinance.Ticker")
    def test_no_shortname_on_any_ticker_is_skipped(self, mock_ticker_cls):
        miss = MagicMock()
        miss.info = {}
        mock_ticker_cls.return_value = miss

        candidate, skip = suggest_from_yahoo(
            _feed(symbol="Equity.KR.000000/KRW", name="000000")
        )
        assert candidate is None
        assert isinstance(skip, SkipReason)
        assert skip.feed_id == 100

    @patch("yfinance.Ticker")
    def test_network_error_is_skipped_not_raised(self, mock_ticker_cls):
        mock_ticker_cls.side_effect = ConnectionError("network unreachable")

        candidate, skip = suggest_from_yahoo(_feed())
        assert candidate is None
        assert isinstance(skip, SkipReason)

    @patch("yfinance.Ticker")
    def test_result_matching_current_name_is_skipped(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.info = {"shortName": "TENCENT"}
        mock_ticker_cls.return_value = mock_ticker

        candidate, skip = suggest_from_yahoo(
            _feed(symbol="Equity.HK.0700/HKD", name="TENCENT")
        )
        assert candidate is None
        assert "matches current name" in skip.reason

    @patch("yfinance.Ticker")
    def test_share_class_suffix_is_flagged_in_notes(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.info = {"shortName": "ZTO EXPRESS-W"}
        mock_ticker_cls.return_value = mock_ticker

        candidate, skip = suggest_from_yahoo(
            _feed(symbol="Equity.HK.2057/HKD", name="2057")
        )
        assert skip is None
        assert candidate.proposed_name == "ZTO EXPRESS-W"
        assert candidate.notes == "share_class_suffix_retained"

    @patch("yfinance.Ticker")
    def test_yfinance_rate_limit_error_is_skipped_not_raised(self, mock_ticker_cls):
        import yfinance

        mock_ticker_cls.side_effect = yfinance.exceptions.YFRateLimitError()

        candidate, skip = suggest_from_yahoo(_feed())
        assert candidate is None
        assert isinstance(skip, SkipReason)


from generate_short_name_candidates import build_candidates, suggest_from_suffix_strip


def _jp_feed(
    feed_id=200,
    symbol="Equity.JP.7203/JPY",
    name="7203",
    description="TOYOTA MOTOR CORPORATION / JAPANESE YEN",
):
    return {
        "feedId": feed_id,
        "symbol": symbol,
        "metadata": {
            "asset_type": "equity",
            "description": description,
            "name": name,
            "quote_currency": "JPY",
        },
    }


class TestSuggestFromSuffixStrip:
    def test_happy_path(self):
        candidate, skip = suggest_from_suffix_strip(_jp_feed())
        assert skip is None
        assert candidate.proposed_name == "TOYOTA MOTOR"
        assert candidate.source == "suffix_stripped"

    def test_no_suffix_matched_is_skipped(self):
        candidate, skip = suggest_from_suffix_strip(
            _jp_feed(description="SEKISUI HOUSE / JAPANESE YEN")
        )
        assert candidate is None
        assert "no corporate suffix" in skip.reason

    def test_currency_mismatch_propagates_as_skip(self):
        candidate, skip = suggest_from_suffix_strip(
            _jp_feed(description="TOYOTA MOTOR CORP / US DOLLAR")
        )
        assert candidate is None
        assert "does not match expected" in skip.reason

    def test_works_on_already_renamed_feed(self):
        """derive_name reads description, not the current name, so this works
        whether metadata.name is still numeric or already the long name."""
        candidate, skip = suggest_from_suffix_strip(
            _jp_feed(name="TOYOTA MOTOR CORPORATION")
        )
        assert skip is None
        assert candidate.current_name == "TOYOTA MOTOR CORPORATION"
        assert candidate.proposed_name == "TOYOTA MOTOR"


class TestBuildCandidates:
    def test_routes_hk_kr_to_yahoo_and_jp_cn_to_suffix_strip(self, monkeypatch):
        import generate_short_name_candidates as module

        calls = []

        def fake_yahoo(feed):
            calls.append(("yahoo", feed["feedId"]))
            return None, SkipReason(feed["feedId"], feed["symbol"], "stub")

        def fake_suffix(feed):
            calls.append(("suffix", feed["feedId"]))
            return None, SkipReason(feed["feedId"], feed["symbol"], "stub")

        monkeypatch.setattr(module, "suggest_from_yahoo", fake_yahoo)
        monkeypatch.setattr(module, "suggest_from_suffix_strip", fake_suffix)

        feeds = [
            _feed(feed_id=1, symbol="Equity.HK.0700/HKD", name="0700"),
            _feed(feed_id=2, symbol="Equity.KR.005380/KRW", name="005380"),
            _jp_feed(feed_id=3),
            _jp_feed(feed_id=4, symbol="Equity.CN.600519/CNY"),
        ]
        module.build_candidates(feeds)
        assert sorted(calls) == [
            ("suffix", 3),
            ("suffix", 4),
            ("yahoo", 1),
            ("yahoo", 2),
        ]

    def test_feed_outside_prefixes_is_never_touched(self, monkeypatch):
        import generate_short_name_candidates as module

        def fail(_feed):
            raise AssertionError("should not be called")

        monkeypatch.setattr(module, "suggest_from_yahoo", fail)
        monkeypatch.setattr(module, "suggest_from_suffix_strip", fail)

        feeds = [_feed(symbol="Equity.US.AAPL/USD", name="AAPL")]
        candidates, skips = module.build_candidates(feeds)
        assert candidates == []
        assert skips == []

    def test_combines_candidates_and_skips(self):
        feeds = [
            _jp_feed(feed_id=5),
            _jp_feed(feed_id=6, description="SEKISUI HOUSE / JAPANESE YEN"),
        ]
        candidates, skips = build_candidates(feeds)
        assert [c.feed_id for c in candidates] == [5]
        assert [s.feed_id for s in skips] == [6]
