"""Offline regressions for independent 15-minute and hourly POC monitoring."""
import io
import json
import smtplib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor
from volume_profile import Bar

BASE = 1_800_000_000
PRODUCTION_CONFIG = {
    "symbol": "NQ=F", "bars": 150, "rows": 24, "value_area_percent": 70,
    "alert_up": True, "alert_down": True, "assumed_delay_seconds": 600,
    "finalization_buffer_seconds": 60, "maximum_alert_age_seconds": 5400,
    "display_timezone": "Europe/Vilnius",
}


def config(**updates):
    cfg = dict(PRODUCTION_CONFIG, bars=2, rows=5)
    cfg.update(updates)
    return cfg


def candles(timeframe="15m", count=4, closed=None):
    duration = 3600 if timeframe == "1h" else 900
    start = BASE if closed is None else closed - count * duration
    return [(start + i * duration, Bar(100, 102, 98, 100, 100))
            for i in range(count)]


def chart_data(items, timeframe="15m"):
    fields = ("open", "high", "low", "close", "volume")
    return {
        "meta": {"dataGranularity": timeframe, "shortName": "NQ Dec"},
        "timestamp": [stamp for stamp, _ in items],
        "indicators": {"quote": [
            {field: [getattr(bar, field) for _, bar in items] for field in fields}
        ]},
    }


def event(cfg, stamp=BASE):
    return {"id": f"{monitor.identity(cfg)}-{stamp}-up", "bar_open": stamp,
            "direction": "up", "close": 100, "poc": 99,
            "previous_close": 100, "previous_poc": 101}


def write_config(directory, cfg):
    path = Path(directory) / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


class TimeframeTests(unittest.TestCase):
    def test_config_defaults_to_existing_frame_and_accepts_both(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_config(directory, config())
            self.assertEqual(monitor.read_config(path)["timeframes"], ["15m"])
            path = write_config(directory, config(timeframes=["15m", "1h"]))
            self.assertEqual(monitor.read_config(path)["timeframes"], ["15m", "1h"])

    def test_invalid_frame_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for invalid in ([], "1h", ["15m", "15m"], ["1m"], ["15m", None]):
                with self.subTest(timeframes=invalid):
                    path = write_config(directory, config(timeframes=invalid))
                    with self.assertRaises(ValueError):
                        monitor.read_config(path)

    def test_adding_hourly_preserves_production_15m_state_identity(self):
        legacy = monitor.identity(PRODUCTION_CONFIG)
        self.assertEqual(legacy, "74cfa9ae90bb5618")
        both = dict(PRODUCTION_CONFIG, timeframes=["15m", "1h"])
        self.assertEqual(monitor.identity(dict(both, timeframe="15m")), legacy)
        hourly = monitor.identity(dict(both, timeframe="1h"))
        self.assertNotEqual(hourly, legacy)
        self.assertEqual(hourly, monitor.identity(dict(PRODUCTION_CONFIG, timeframe="1h")))

    def test_hourly_parser_accepts_native_aliases_and_rejects_wrong_frame(self):
        items = candles("1h")
        for alias in ("1h", "60m"):
            with self.subTest(alias=alias):
                self.assertEqual(monitor.parse_candles(chart_data(items, alias), "1h"), items)
        for provider, requested in (("15m", "1h"), ("1h", "15m"), ("1m", "1h")):
            with self.subTest(provider=provider, requested=requested), self.assertRaises(ValueError):
                monitor.parse_candles(chart_data(items, provider), requested)

    def test_fetch_requests_native_candles_for_each_frame(self):
        for timeframe in ("15m", "1h"):
            payload = {"chart": {"result": [chart_data(candles(timeframe), timeframe)], "error": None}}
            with self.subTest(timeframe=timeframe), \
                 patch.object(monitor, "urlopen", return_value=io.StringIO(json.dumps(payload))) as request:
                received = monitor.fetch_chart("NQ=F", timeframe)
                query = parse_qs(urlparse(request.call_args.args[0].full_url).query)
                self.assertEqual(query["interval"], [timeframe])
                self.assertEqual(received["meta"]["dataGranularity"], timeframe)

    def test_hour_finalizes_at_hour_end_plus_delay_and_buffer(self):
        cfg, items = config(timeframe="1h"), candles("1h", count=3)
        stamp = items[1][0]
        # A 1H candle is still open at the 15-minute finalization time.
        fifteen_minute_cutoff = stamp + 900 + 600 + 60
        self.assertNotIn(items[1], monitor.finalized(items, cfg, fifteen_minute_cutoff))
        ready = stamp + 3600 + 600 + 60
        self.assertEqual(monitor.finalized(items, cfg, ready - 1), items[:1])
        self.assertEqual(monitor.finalized(items, cfg, ready), items[:2])

    def test_hourly_recovery_age_is_measured_from_hour_close(self):
        cfg, items = config(timeframe="1h"), candles("1h", count=3)
        closed = items[-1][0] + 3600
        for extra, queued in ((0, True), (1, False)):
            with self.subTest(extra_seconds=extra):
                state = monitor.new_state()
                state["last_bar"] = items[-2][0]
                with patch.object(monitor, "crossing", return_value="up"):
                    monitor.process(items, cfg, closed + cfg["maximum_alert_age_seconds"] + extra, state)
                self.assertEqual(bool(state["pending"]), queued)
                self.assertEqual(state["last_bar"], items[-1][0])

    def test_hourly_pending_expiry_uses_hour_close_inclusive_boundary(self):
        cfg = config(timeframe="1h")
        closed = BASE + 3600
        for extra, delivered in ((0, True), (1, False)):
            with self.subTest(extra_seconds=extra), tempfile.TemporaryDirectory() as directory:
                state = monitor.new_state()
                state["pending"] = [event(cfg)]
                accepted = []
                path = Path(directory) / "state.json"
                monitor.deliver_pending(state, path, cfg,
                                        closed + cfg["maximum_alert_age_seconds"] + extra,
                                        sender=lambda *args: accepted.append(args))
                self.assertEqual(bool(accepted), delivered)
                self.assertEqual(monitor.load_state(path)["pending"], [])

    def test_hourly_email_names_frame_and_correct_local_candle_close(self):
        closed = int(datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc).timestamp())
        cfg = config(timeframe="1h")
        subject, body = monitor.describe_event(event(cfg, closed - 3600), cfg, closed + 720)
        self.assertIn("1H", subject)
        self.assertIn("1H", body)
        self.assertIn("2026-10-13 13:00 EEST", body)
        self.assertIn("apie 12 min.", body)

    def test_same_open_and_direction_create_distinct_events_for_each_frame(self):
        pending_ids = []
        for timeframe in ("15m", "1h"):
            cfg, items = config(timeframe=timeframe), candles(timeframe, count=3)
            state = monitor.new_state()
            state["last_bar"] = items[-2][0]
            # Give both frames the same opening timestamp, so only the frame differentiates IDs.
            items[-1] = (BASE + 7200, items[-1][1])
            now = items[-1][0] + (3600 if timeframe == "1h" else 900) + 660
            with patch.object(monitor, "crossing", return_value="up"):
                monitor.process(items, cfg, now, state)
            pending_ids.append(state["pending"][0]["id"])
        self.assertNotEqual(*pending_ids)

    def test_new_hourly_baseline_keeps_existing_15m_checkpoint_and_no_old_mail(self):
        cfg = config(timeframes=["15m", "1h"])
        series = {frame: candles(frame) for frame in cfg["timeframes"]}
        now = series["1h"][-1][0] + 3600 + 660
        with tempfile.TemporaryDirectory() as directory:
            cfg_path = write_config(directory, cfg)
            paths = {frame: Path(directory) / f"{monitor.identity(dict(cfg, timeframe=frame))}.json"
                     for frame in cfg["timeframes"]}
            existing = monitor.new_state()
            existing.update(last_bar=series["15m"][-1][0], contract_hint="NQ Dec")
            monitor.save_state(paths["15m"], existing)
            with patch.object(monitor, "fetch_chart", side_effect=lambda symbol, frame: chart_data(series[frame], frame)), \
                 patch.object(monitor, "mail_settings", return_value=("sender@example.com", "dummy", "recipient@example.com")), \
                 patch.object(monitor.time, "time", return_value=now), \
                 patch.object(monitor, "crossing", side_effect=AssertionError("historical crossing scan")), \
                 patch.object(monitor.smtplib, "SMTP", side_effect=AssertionError("historical email")):
                result = monitor.main(["--config", str(cfg_path), "--state-dir", directory])
            self.assertEqual(result, 0)
            self.assertEqual(monitor.load_state(paths["15m"]), existing)
            hourly = monitor.load_state(paths["1h"])
            self.assertEqual(hourly["last_bar"], series["1h"][-1][0])
            self.assertEqual(hourly["pending"], [])

    def test_both_frame_dry_run_does_not_send_or_change_any_state(self):
        cfg = config(timeframes=["15m", "1h"])
        closed, now = BASE + 14400, BASE + 14400 + 660
        series = {frame: candles(frame, closed=closed) for frame in cfg["timeframes"]}
        with tempfile.TemporaryDirectory() as directory:
            cfg_path = write_config(directory, cfg)
            originals = {}
            for frame in cfg["timeframes"]:
                frame_cfg = dict(cfg, timeframe=frame)
                path = Path(directory) / f"{monitor.identity(frame_cfg)}.json"
                state = monitor.new_state()
                state.update(last_bar=series[frame][-1][0], pending=[event(frame_cfg, series[frame][-1][0])])
                monitor.save_state(path, state)
                originals[path] = path.read_bytes()
            with patch.object(monitor, "fetch_chart", side_effect=lambda symbol, frame: chart_data(series[frame], frame)) as fetch, \
                 patch.object(monitor.time, "time", return_value=now), \
                 patch.object(monitor, "mail_settings", side_effect=AssertionError("dry-run mail settings")), \
                 patch.object(monitor, "save_state", side_effect=AssertionError("dry-run persistence")), \
                 patch.object(monitor.smtplib, "SMTP", side_effect=AssertionError("dry-run SMTP")):
                result = monitor.main(["--config", str(cfg_path), "--state-dir", directory, "--dry-run"])
            self.assertEqual(result, 0)
            self.assertEqual(fetch.call_args_list, [call("NQ=F", "15m"), call("NQ=F", "1h")])
            for path, original in originals.items():
                self.assertEqual(path.read_bytes(), original)

    def test_failed_15m_provider_does_not_stop_hourly_processing(self):
        cfg, items = config(timeframes=["15m", "1h"]), candles("1h")
        now = items[-1][0] + 3600 + 660
        with tempfile.TemporaryDirectory() as directory:
            cfg_path = write_config(directory, cfg)
            def fetch(symbol, frame):
                if frame == "15m":
                    raise RuntimeError("simulated provider outage")
                return chart_data(items, frame)
            with patch.object(monitor, "fetch_chart", side_effect=fetch) as requested, \
                 patch.object(monitor, "mail_settings", return_value=("sender@example.com", "dummy", "recipient@example.com")), \
                 patch.object(monitor.time, "time", return_value=now), \
                 patch.object(monitor.smtplib, "SMTP", side_effect=AssertionError("mail on initial baseline")):
                result = monitor.main(["--config", str(cfg_path), "--state-dir", directory])
            self.assertEqual(result, 1)
            self.assertEqual(requested.call_args_list, [call("NQ=F", "15m"), call("NQ=F", "1h")])
            path = Path(directory) / f"{monitor.identity(dict(cfg, timeframe='1h'))}.json"
            self.assertEqual(monitor.load_state(path)["last_bar"], items[-1][0])

    def test_smtp_failure_retains_15m_outbox_and_hourly_is_delivered_separately(self):
        cfg, closed = config(timeframes=["15m", "1h"]), BASE + 14400
        now = closed + 660
        series = {frame: candles(frame, closed=closed) for frame in cfg["timeframes"]}
        failed_context, accepted_context = MagicMock(), MagicMock()
        failed_context.__enter__.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b"simulated failure")
        accepted = accepted_context.__enter__.return_value
        accepted.send_message.return_value = {}
        with tempfile.TemporaryDirectory() as directory:
            cfg_path = write_config(directory, cfg)
            paths, original_states = {}, {}
            for frame in cfg["timeframes"]:
                frame_cfg = dict(cfg, timeframe=frame)
                paths[frame] = Path(directory) / f"{monitor.identity(frame_cfg)}.json"
                state = monitor.new_state()
                state.update(last_bar=series[frame][-1][0], pending=[event(frame_cfg, series[frame][-1][0])])
                monitor.save_state(paths[frame], state)
                original_states[frame] = json.loads(json.dumps(state))
            with patch.object(monitor, "fetch_chart", side_effect=lambda symbol, frame: chart_data(series[frame], frame)), \
                 patch.object(monitor, "mail_settings", return_value=("sender@example.com", "dummy", "recipient@example.com")), \
                 patch.object(monitor.time, "time", return_value=now), \
                 patch.object(monitor.smtplib, "SMTP", side_effect=[failed_context, accepted_context]):
                result = monitor.main(["--config", str(cfg_path), "--state-dir", directory])
            self.assertEqual(result, 1)
            self.assertEqual(monitor.load_state(paths["15m"])["pending"], original_states["15m"]["pending"])
            self.assertEqual(monitor.load_state(paths["15m"])["last_bar"], original_states["15m"]["last_bar"])
            self.assertEqual(monitor.load_state(paths["1h"])["pending"], [])
            self.assertEqual(monitor.load_state(paths["1h"])["last_bar"], original_states["1h"]["last_bar"])
            accepted.send_message.assert_called_once()
            self.assertIn("1H", str(accepted.send_message.call_args.args[0]["Subject"]))
            failed_context.__enter__.return_value.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
