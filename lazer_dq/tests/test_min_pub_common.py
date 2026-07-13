from lazer_dq.min_pub_common import (
    FeedSession,
    deprecated_stable_feeds,
    hygiene_rows,
    iter_stable_sessions,
)

CONFIG = {
    "exchanges": [
        {
            "exchangeId": 1,
            "sessions": [
                {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}
            ],
        }
    ],
    "feeds": [
        {  # STABLE, session-level minPublishers override, inline schedule
            "feedId": 10,
            "symbol": "Equity.US.AAA/USD",
            "state": "STABLE",
            "minPublishers": 2,
            "metadata": {"asset_type": "equity"},
            "marketSchedules": [
                {
                    "session": "REGULAR",
                    "minPublishers": 3,
                    "allowedPublisherIds": [1, 2, 3, 4],
                    "marketSchedule": "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;",
                },
                {
                    "session": "PRE_MARKET",
                    "allowedPublisherIds": [1, 2],
                    "marketSchedule": "America/New_York;0400-0930,0400-0930,0400-0930,0400-0930,0400-0930,C,C;",
                },
            ],
        },
        {  # STABLE crypto, feed-level min_pub only, inherited schedule
            "feedId": 11,
            "symbol": "Crypto.BBB/USD",
            "state": "STABLE",
            "minPublishers": 1,
            "exchangeId": 1,
            "metadata": {"asset_type": "crypto"},
            "marketSchedules": [{"session": "REGULAR", "allowedPublisherIds": [5]}],
        },
        {  # COMING_SOON: not audited, but hygiene-scanned
            "feedId": 12,
            "symbol": "InterestRate.CCC/USD",
            "state": "COMING_SOON",
            "minPublishers": 3,
            "metadata": {"asset_type": "interest-rate"},
            "marketSchedules": [{"session": "REGULAR", "allowedPublisherIds": []}],
        },
        {  # DEPRECATED STABLE: skipped, reported
            "feedId": 13,
            "symbol": "DEPRECATED FEED - Equity.US.DDD/USD",
            "state": "STABLE",
            "minPublishers": 1,
            "metadata": {"asset_type": "equity"},
            "marketSchedules": [{"session": "REGULAR", "allowedPublisherIds": [1]}],
        },
        {  # INACTIVE kill-switch: hygiene only
            "feedId": 14,
            "symbol": "Crypto.EEE/USD",
            "state": "INACTIVE",
            "minPublishers": 100,
            "metadata": {"asset_type": "crypto"},
            "marketSchedules": [{"session": "REGULAR", "allowedPublisherIds": [1, 2]}],
        },
    ],
}


def test_iter_stable_sessions_yields_per_session_with_effective_min_pub():
    sessions = list(iter_stable_sessions(CONFIG))
    by_key = {(s.feed_id, s.session): s for s in sessions}
    assert set(by_key) == {(10, "REGULAR"), (10, "PRE_MARKET"), (11, "REGULAR")}
    assert by_key[(10, "REGULAR")].effective_min_pub == 3  # session override
    assert by_key[(10, "PRE_MARKET")].effective_min_pub == 2  # feed-level
    assert by_key[(10, "REGULAR")].allowed == frozenset({1, 2, 3, 4})
    assert by_key[(11, "REGULAR")].schedule_str == "UTC;O,O,O,O,O,O,O;"  # inherited
    assert by_key[(11, "REGULAR")].asset_type == "crypto"


def test_deprecated_reported_not_iterated():
    assert deprecated_stable_feeds(CONFIG) == [
        {"feed_id": 13, "symbol": "DEPRECATED FEED - Equity.US.DDD/USD"}
    ]


def test_hygiene_rows_flag_min_pub_exceeding_allowed():
    rows = hygiene_rows(CONFIG)
    by_id = {r["feed_id"]: r for r in rows}
    assert set(by_id) == {12, 14}
    assert by_id[12]["issue"] == "no_allowed_publishers"
    assert by_id[14]["issue"] == "min_pub_exceeds_allowed"
    assert by_id[14]["allowed_union_count"] == 2
