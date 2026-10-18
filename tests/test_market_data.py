"""Offline regressions for provider quotes outside real NQ candle boundaries."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor
from volume_profile import Bar


def utc_stamp(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


def config(frame="15m", **updates):
    cfg = {"symbol": "NQ=F", "timeframes": ["15m", "1h"], "timeframe": frame,
           "bars": 2, "rows": 5, "value_area_percent": 70,
           "alert_up": True, "alert_down": True, "assumed_delay_seconds": 600,
           "finalization_buffer_seconds": 60, "maximum_alert_age_seconds": 5400,
           "display_timezone": "Europe/Vilnius"}
    cfg.update(updates)
    return cfg


def chart_data(stamps, frame="15m", bars=None, symbol="NQ=F"):
    bars = bars or [Bar(100, 102, 98, 100, 100) for _ in stamps]
    fields = ("open", "high", "low", "close", "volume")
    return {"meta": {"symbol": symbol, "dataGranularity": frame, "shortName": "NQ Dec"},
            "timestamp": list(stamps),
            "indicators": {"quote": [{field: [getattr(bar, field) for bar in bars]
                                        for field in fields}]}}


def friday_candles(frame, count=4):
    duration = 3600 if frame == "1h" else 900
    closed = utc_stamp("2026-10-16T21:00:00")  # Friday 17:00 New York.
    return [(closed - duration * (count - index), Bar(100, 102, 98, 100, 100))
            for index in range(count)]


def pending_event(cfg, stamp):
    return {"id": f"{monitor.identity(cfg)}-{stamp}-up", "bar_open": stamp,
            "direction": "up", "close": 100, "poc": 99,
            "previous_close": 100, "previous_poc": 101}


class MarketDataTests(unittest.TestCase):
    def test_recorded_weekend_quote_is_excluded_regardless_of_ohlcv_shape(self):
        quote_stamp = 1792184399  # Actual Yahoo final quote: Friday 20:59:59 UTC.
        for frame, real_stamp in (("15m", 1792183500), ("1h", 1792180800)):
            for quote in (Bar(29391.5, 29391.5, 29391.5, 29391.5, 0),
                          Bar(29391.5, 29393, 29390, 29392, 10)):
                with self.subTest(frame=frame, quote=quote):
                    real_bar = Bar(29390, 29394, 29388, 29391.5, 100)
                    parsed = monitor.parse_candles(chart_data(
                        [real_stamp, quote_stamp], frame, [real_bar, quote]), frame)
                    self.assertEqual(parsed, [(real_stamp, real_bar)])

    def test_aligned_zero_volume_candle_during_trading_is_retained(self):
        stamp = utc_stamp("2026-10-16T20:00:00")  # Friday 16:00 New York.
        flat = Bar(29391.5, 29391.5, 29391.5, 29391.5, 0)
        for frame in ("15m", "1h"):
            with self.subTest(frame=frame):
                self.assertEqual(monitor.parse_candles(chart_data([stamp], frame, [flat]), frame),
                                 [(stamp, flat)])

    def test_weekly_closure_and_maintenance_do_not_become_candles(self):
        for frame, friday_open in (("15m", "2026-10-16T20:45:00"),
                                   ("1h", "2026-10-16T20:00:00")):
            valid = [utc_stamp(friday_open), utc_stamp("2026-10-18T22:00:00"),
                     utc_stamp("2026-10-19T22:00:00")]
            invalid = [utc_stamp("2026-10-16T21:00:00"),  # Friday 17:00 NY.
                       utc_stamp("2026-10-17T16:00:00"),  # Saturday noon NY.
                       utc_stamp("2026-10-18T21:00:00"),  # Sunday 17:00 NY.
                       utc_stamp("2026-10-19T21:00:00"),  # Monday maintenance.
                       utc_stamp("2026-10-20T21:00:00"),
                       utc_stamp("2026-10-21T21:00:00"),
                       utc_stamp("2026-10-22T21:00:00")]
            with self.subTest(frame=frame):
                parsed = monitor.parse_candles(chart_data(sorted(valid + invalid), frame), frame)
                self.assertEqual([stamp for stamp, _ in parsed], valid)

    def test_new_york_dst_changes_utc_session_boundary(self):
        # UTC values are explicit so a fixed UTC-4/UTC-5 implementation cannot pass.
        valid = ["2026-10-30T20:00:00",  # Friday 16:00 EDT.
                 "2026-11-06T21:00:00",  # Friday 16:00 EST.
                 "2026-10-25T22:00:00",  # Sunday 18:00 EDT.
                 "2026-11-01T23:00:00"]  # Sunday 18:00 EST.
        invalid = ["2026-10-30T21:00:00", "2026-11-06T22:00:00",
                   "2026-10-25T21:00:00", "2026-11-01T22:00:00"]
        for frame in ("15m", "1h"):
            with self.subTest(frame=frame):
                expected = sorted(utc_stamp(text) for text in valid)
                all_stamps = sorted(expected + [utc_stamp(text) for text in invalid])
                parsed = monitor.parse_candles(chart_data(all_stamps, frame), frame)
                self.assertEqual([stamp for stamp, _ in parsed], expected)

    def test_nq_weekly_session_filter_does_not_close_other_symbols(self):
        stamp = utc_stamp("2026-10-17T16:00:00")
        for frame in ("15m", "1h"):
            with self.subTest(frame=frame):
                parsed = monitor.parse_candles(chart_data([stamp], frame, symbol="BTC-USD"),
                                               frame, symbol="BTC-USD")
                self.assertEqual([row[0] for row in parsed], [stamp])

    def test_finalization_cannot_reintroduce_off_grid_or_closed_session_rows(self):
        now = utc_stamp("2026-10-18T18:50:00")
        for frame in ("15m", "1h"):
            cfg, real = config(frame), friday_candles(frame)
            bad = [(1792184399, Bar(100, 100, 100, 100, 0)),
                   (utc_stamp("2026-10-17T03:00:00"), Bar(100, 102, 98, 100, 1))]
            with self.subTest(frame=frame):
                self.assertEqual(monitor.finalized(real + bad, cfg, now), real)

    def test_invalid_saved_weekend_checkpoint_repairs_without_historical_alerts(self):
        now = utc_stamp("2026-10-18T18:50:00")
        for frame, bad_checkpoint in (("15m", 1792208700), ("1h", 1792206000)):
            for checkpoint in (bad_checkpoint, 1792184399):
                with self.subTest(frame=frame, checkpoint=checkpoint):
                    cfg, real = config(frame), friday_candles(frame)
                    genuine = pending_event(cfg, real[-2][0])
                    invalid = pending_event(cfg, bad_checkpoint)
                    state = monitor.new_state()
                    state.update(last_bar=checkpoint, pending=[genuine, invalid], contract_hint="NQ Dec")
                    with patch.object(monitor, "crossing", side_effect=AssertionError("historical rescan")), \
                         patch.object(monitor.smtplib, "SMTP", side_effect=AssertionError("mail during repair")):
                        monitor.process(real, cfg, now, state, "NQ Dec")
                    self.assertEqual(state["last_bar"], real[-1][0])
                    self.assertEqual(state["pending"], [genuine])
                    self.assertEqual(state["contract_hint"], "NQ Dec")

    def test_valid_checkpoint_is_never_reset_when_provider_snapshot_is_older(self):
        now = utc_stamp("2026-10-18T18:50:00")
        for frame in ("15m", "1h"):
            cfg, real = config(frame), friday_candles(frame, count=5)
            state = monitor.new_state()
            state.update(last_bar=real[-1][0], pending=[pending_event(cfg, real[-2][0])],
                         contract_hint="NQ Dec")
            original = {**state, "pending": [dict(item) for item in state["pending"]]}
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                monitor.process(real[:-1], cfg, now, state, "NQ Dec")
            self.assertEqual(state, original)

    def test_market_data_filter_keeps_existing_state_identities(self):
        cfg = config(bars=150, rows=24)
        self.assertEqual(monitor.identity(cfg), "74cfa9ae90bb5618")
        self.assertEqual(monitor.identity(dict(cfg, timeframe="1h")), "a4bd3ed3f251e0b6")


if __name__ == "__main__":
    unittest.main()
