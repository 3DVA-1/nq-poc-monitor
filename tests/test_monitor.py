"""Offline monitor tests; no provider request or SMTP call is made."""
import json
import smtplib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor
from volume_profile import Bar

BASE = 1_800_000_000


def config(**updates):
    result = {"symbol": "NQ=F", "bars": 2, "rows": 5, "value_area_percent": 70,
              "alert_up": True, "alert_down": True, "assumed_delay_seconds": 900,
              "finalization_buffer_seconds": 120, "maximum_alert_age_seconds": 7200,
              "display_timezone": "Europe/Vilnius"}
    result.update(updates)
    return result


def candles(count=5):
    return [(BASE + i * monitor.INTERVAL, Bar(100, 102, 98, 100, 100)) for i in range(count)]


def chart_data(items):
    fields = ("open", "high", "low", "close", "volume")
    q = {field: [] for field in fields}
    for _, bar in items:
        for field in fields:
            q[field].append(getattr(bar, field) if bar else None)
    return {"meta": {"dataGranularity": "15m", "shortName": "NQ Dec"},
            "timestamp": [stamp for stamp, _ in items], "indicators": {"quote": [q]}}


def event(stamp=BASE, direction="up"):
    return {"id": f"test-{stamp}-{direction}", "bar_open": stamp, "direction": direction,
            "close": 100, "poc": 99, "previous_close": 100, "previous_poc": 101}


class MonitorTests(unittest.TestCase):
    def test_delay_uses_bar_end_with_buffer_inclusive_boundary(self):
        items, cfg = candles(3), config()
        stamp = items[1][0]
        ready = stamp + 900 + 900 + 120
        self.assertEqual(monitor.finalized(items, cfg, ready - 1), items[:1])
        self.assertEqual(monitor.finalized(items, cfg, ready), items[:2])

    def test_parse_sorts_and_keeps_partially_invalid_rows(self):
        payload = chart_data(candles(5))
        payload["indicators"]["quote"][0]["volume"][2] = None
        parsed = monitor.parse_candles(payload)
        self.assertEqual(len(parsed), 5)
        self.assertIsNone(parsed[2][1])
        self.assertIsNone(monitor.poc_at(parsed, 2, config()))
        self.assertIsNone(monitor.poc_at(parsed, 3, config()))
        self.assertIsNotNone(monitor.poc_at(parsed, 4, config()))
        reverse_payload = chart_data(list(reversed(candles())))
        self.assertEqual(monitor.parse_candles(reverse_payload), candles())

    def test_explicit_empty_row_skipped_and_invalid_numeric_row_retained(self):
        items = candles()
        items[1] = (items[1][0], None)
        payload = chart_data(items)
        payload["indicators"]["quote"][0]["high"][2] = 90
        parsed = monitor.parse_candles(payload)
        self.assertEqual([t for t, _ in parsed], [items[i][0] for i in (0, 2, 3, 4)])
        self.assertIsNone(parsed[1][1])

    def test_reject_duplicate_timestamps_array_mismatch_wrong_interval(self):
        for fault in ("duplicate", "length", "interval"):
            payload = chart_data(candles())
            if fault == "duplicate":
                payload["timestamp"][1] = payload["timestamp"][0]
            elif fault == "length":
                payload["indicators"]["quote"][0]["close"].pop()
            else:
                payload["meta"]["dataGranularity"] = "1m"
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                monitor.parse_candles(payload)

    def test_bootstrap_suppresses_all_historical_crossings(self):
        state, items = monitor.new_state(), candles()
        with patch.object(monitor, "crossing", side_effect=AssertionError("historical scan")):
            monitor.process(items, config(), items[-1][0] + 1500, state)
        self.assertEqual(state["last_bar"], items[-1][0])
        self.assertEqual(state["pending"], [])

    def test_current_previous_windows_and_dedupe_after_reload(self):
        items, cfg, state = candles(3), config(), monitor.new_state()
        state["last_bar"] = items[1][0]
        with patch.object(monitor, "poc_at", side_effect=lambda seq, idx, cfg: {"poc": 99 if idx == 2 else 101}):
            monitor.process(items, cfg, items[-1][0] + 1500, state)
        self.assertEqual(len(state["pending"]), 1)
        self.assertEqual(state["pending"][0]["direction"], "up")
        self.assertEqual(state["pending"][0]["previous_poc"], 101)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            monitor.save_state(path, state)
            reloaded = monitor.load_state(path)
            monitor.process(items, cfg, items[-1][0] + 1500, reloaded)
            self.assertEqual(reloaded, state)

    def test_actual_rolling_window_drops_oldest_bar(self):
        items = [(BASE, Bar(0, 5, 0, 5, 10)),
                 (BASE + 900, Bar(0, 5, 0, 5, 20)),
                 (BASE + 1800, Bar(5, 10, 5, 10, 100))]
        previous = monitor.poc_at(items, 1, config())
        current = monitor.poc_at(items, 2, config())
        self.assertEqual(previous["volumes"], [6] * 5)
        self.assertEqual(previous["poc"], 0.5)
        self.assertEqual(current["volumes"], [8, 8, 24, 40, 40])
        self.assertEqual(current["poc"], 7.0)

    def test_recovery_events_are_chronological_and_not_resent(self):
        items, cfg, state = candles(5), config(), monitor.new_state()
        state["last_bar"] = items[1][0]
        now = items[-1][0] + 1500
        with patch.object(monitor, "poc_at", side_effect=lambda seq, idx, cfg: {"poc": 99 if idx % 2 == 0 else 101}):
            monitor.process(items, cfg, now, state)
        self.assertEqual([e["bar_open"] for e in state["pending"]], [items[i][0] for i in (2, 3, 4)])
        self.assertEqual([e["direction"] for e in state["pending"]], ["up", "down", "up"])
        accepted = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            monitor.save_state(path, state)
            monitor.deliver_pending(state, path, cfg, now,
                                    sender=lambda subject, body, ident: accepted.append(ident))
            reloaded = monitor.load_state(path)
            monitor.process(items, cfg, now, reloaded)
            self.assertEqual(reloaded["pending"], [])
        self.assertEqual(len(accepted), 3)
        self.assertEqual(len(set(accepted)), 3)

    def test_invalid_rows_are_not_bridged_by_crossing(self):
        items, cfg, state = candles(6), config(), monitor.new_state()
        items[3] = (items[3][0], None)
        state["last_bar"] = items[2][0]
        with patch.object(monitor, "crossing", side_effect=AssertionError("invalid sequence bridged")):
            monitor.process(items, cfg, items[-1][0] + 1500, state)
        self.assertEqual(state["pending"], [])
        self.assertEqual(state["last_bar"], items[-1][0])

    def test_old_recovery_signal_skipped_but_checkpoint_advances(self):
        items, cfg, state = candles(3), config(), monitor.new_state()
        state["last_bar"] = items[1][0]
        with patch.object(monitor, "crossing", return_value="up"):
            monitor.process(items, cfg, items[-1][0] + 900 + 7201, state)
        self.assertEqual(state["pending"], [])
        self.assertEqual(state["last_bar"], items[-1][0])

    def test_disabled_direction_and_empty_signal_not_queued(self):
        items = candles(3)
        for direction in ("up", None):
            state = monitor.new_state()
            state["last_bar"] = items[1][0]
            with patch.object(monitor, "crossing", return_value=direction):
                monitor.process(items, config(alert_up=False), items[-1][0] + 1500, state)
            self.assertEqual(state["pending"], [])

    def test_smtp_failure_retains_outbox_then_retry_removes_it(self):
        cfg, state = config(), monitor.new_state()
        state["pending"] = [event()]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            monitor.save_state(path, state)
            def fail(*args):
                raise smtplib.SMTPException("simulated failure")
            with self.assertRaises(smtplib.SMTPException):
                monitor.deliver_pending(state, path, cfg, BASE + 1500, sender=fail)
            self.assertEqual(len(state["pending"]), 1)
            self.assertEqual(monitor.load_state(path), state)
            accepted = []
            monitor.deliver_pending(state, path, cfg, BASE + 1600,
                                    sender=lambda subject, body, ident: accepted.append(ident))
            self.assertEqual(accepted, [event()["id"]])
            self.assertEqual(monitor.load_state(path)["pending"], [])

    def test_smtp_authentication_and_message_follow_verified_starttls(self):
        credentials = ("sender@example.com", "dummy-app-password", "recipient@example.com")
        with patch.object(monitor, "mail_settings", return_value=credentials), \
             patch.object(monitor.smtplib, "SMTP") as connect:
            smtp = connect.return_value.__enter__.return_value
            smtp.send_message.return_value = {}
            monitor.send_mail("Test subject", "Test body", "test-secure-mail")
            connect.assert_called_once_with("smtp.gmail.com", 587, timeout=30)
            self.assertEqual([call[0] for call in smtp.method_calls],
                             ["ehlo", "starttls", "ehlo", "login", "send_message"])
            context = smtp.starttls.call_args.kwargs["context"]
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, monitor.ssl.CERT_REQUIRED)
            smtp.login.assert_called_once_with(credentials[0], credentials[1])
            smtp.send_message.assert_called_once()
            message = smtp.send_message.call_args.args[0]
            self.assertEqual(message["To"], credentials[2])

    def test_smtp_never_authenticates_or_sends_if_starttls_fails(self):
        failures = (smtplib.SMTPNotSupportedError("STARTTLS unavailable"),
                    monitor.ssl.SSLError("TLS handshake failed"))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), \
                 patch.object(monitor, "mail_settings", return_value=("sender@example.com", "dummy-app-password", "recipient@example.com")), \
                 patch.object(monitor.smtplib, "SMTP") as connect:
                smtp = connect.return_value.__enter__.return_value
                smtp.starttls.side_effect = failure
                with self.assertRaises(type(failure)):
                    monitor.send_mail("Test subject", "Test body", "test-no-plaintext")
                smtp.starttls.assert_called_once()
                smtp.login.assert_not_called()
                smtp.send_message.assert_not_called()
                self.assertEqual(smtp.ehlo.call_count, 1)

    def test_expired_outbox_event_discarded_without_smtp(self):
        state = monitor.new_state()
        state["pending"] = [event()]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch.object(monitor, "send_mail", side_effect=AssertionError("expired mail")) as sender:
                monitor.deliver_pending(state, path, config(), BASE + 900 + 7201, sender=sender)
            self.assertEqual(state["pending"], [])
            self.assertEqual(monitor.load_state(path)["pending"], [])

    def test_state_and_configuration_identities_are_isolated(self):
        first = monitor.identity(config())
        for key, value in (("symbol", "MNQ=F"), ("bars", 150), ("rows", 24),
                           ("value_area_percent", 80), ("alert_up", False), ("alert_down", False)):
            with self.subTest(key=key):
                self.assertNotEqual(first, monitor.identity(config(**{key: value})))
        self.assertEqual(first, monitor.identity(config(display_timezone="UTC")))
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(monitor.load_state(Path(directory) / "absent.json"), monitor.new_state())

    def test_contract_hint_change_resets_without_recovery_alerts(self):
        state, items = monitor.new_state(), candles()
        state.update(last_bar=items[1][0], pending=[event()], contract_hint="NQ Sep")
        with patch.object(monitor, "crossing", side_effect=AssertionError("rollover scan")):
            monitor.process(items, config(), items[-1][0] + 1500, state, "NQ Dec")
        self.assertEqual(state["last_bar"], items[-1][0])
        self.assertEqual(state["pending"], [])
        self.assertEqual(state["contract_hint"], "NQ Dec")

    def test_main_reset_replaces_checkpoint_and_does_not_email(self):
        cfg, items = config(), candles(4)
        now = items[-1][0] + 900 + 1020
        with tempfile.TemporaryDirectory() as directory:
            cfg_path = Path(directory) / "config.json"
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            state_path = Path(directory) / f"{monitor.identity(cfg)}.json"
            state = monitor.new_state()
            state.update(last_bar=items[1][0], pending=[event()])
            monitor.save_state(state_path, state)
            with patch.object(monitor, "fetch_chart", return_value=chart_data(items)), \
                 patch.object(monitor, "mail_settings", return_value=("a@b.c", "fake", "a@b.c")), \
                 patch.object(monitor.time, "time", return_value=now), \
                 patch.object(monitor, "send_mail", side_effect=AssertionError("mail on reset")), \
                 patch.object(monitor.smtplib, "SMTP", side_effect=AssertionError("SMTP on reset")):
                result = monitor.main(["--config", str(cfg_path), "--state-dir", directory, "--reset-state"])
            self.assertEqual(result, 0)
            self.assertEqual(monitor.load_state(state_path)["last_bar"], items[-1][0])
            self.assertEqual(monitor.load_state(state_path)["pending"], [])

    def test_dry_run_never_saves_or_sends(self):
        cfg, items = config(), candles(4)
        now = items[-1][0] + 900 + 1020
        with tempfile.TemporaryDirectory() as directory:
            cfg_path = Path(directory) / "config.json"
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(monitor, "fetch_chart", return_value=chart_data(items)), \
                 patch.object(monitor.time, "time", return_value=now), \
                 patch.object(monitor, "mail_settings", side_effect=AssertionError("mail settings")), \
                 patch.object(monitor, "save_state", side_effect=AssertionError("saved dry run")):
                self.assertEqual(monitor.main(["--config", str(cfg_path), "--state-dir", directory, "--dry-run"]), 0)
            self.assertFalse((Path(directory) / f"{monitor.identity(cfg)}.json").exists())

    def test_vilnius_fall_back_same_local_time_distinct_dst_zone(self):
        utc_earlier = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc).timestamp()
        utc_later = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc).timestamp()
        bodies = []
        for closed in (utc_earlier, utc_later):
            _, body = monitor.describe_event(event(int(closed) - 900), config(), closed + 1500)
            bodies.append(body)
        self.assertIn("2026-10-25 03:30 EEST", bodies[0])
        self.assertIn("2026-10-25 03:30 EET", bodies[1])
        self.assertIn("Europe/Vilnius", bodies[0])
        self.assertIn("apie 25 min.", bodies[0])

    def test_reject_stale_snapshot_and_short_history(self):
        state, items = monitor.new_state(), candles()
        state["last_bar"] = items[-1][0] + 900
        with self.assertRaises(ValueError):
            monitor.process(items, config(), BASE + 10000, state)
        with self.assertRaises(ValueError):
            monitor.process(items[:2], config(), BASE + 10000, monitor.new_state())


if __name__ == "__main__":
    unittest.main()
