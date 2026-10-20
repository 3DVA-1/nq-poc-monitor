"""Offline regressions for numbered notification copies and durable progress."""
import json
import smtplib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


def config(frame="15m", **updates):
    cfg = dict(PRODUCTION_CONFIG, bars=2, rows=5, timeframe=frame)
    cfg.update(updates)
    return cfg


def candles(frame="15m", count=4, closed=None):
    duration = 3600 if frame == "1h" else 900
    start = BASE if closed is None else closed - duration * count
    return [(start + index * duration, Bar(100, 102, 98, 100, 100))
            for index in range(count)]


def chart_data(items, frame):
    fields = ("open", "high", "low", "close", "volume")
    return {"meta": {"symbol": "NQ=F", "dataGranularity": frame, "shortName": "NQ Dec"},
            "timestamp": [stamp for stamp, _ in items],
            "indicators": {"quote": [{field: [getattr(bar, field) for _, bar in items]
                                        for field in fields}]}}


def event(cfg, total=None, sent=0, stamp=BASE):
    item = {"id": f"{monitor.identity(cfg)}-{stamp}-up", "bar_open": stamp,
            "direction": "up", "close": 100, "poc": 99,
            "previous_close": 100, "previous_poc": 101}
    if total is not None:
        item.update(notifications_total=total, notifications_sent=sent)
    return item


def write_config(directory, cfg):
    path = Path(directory) / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


class NotificationTests(unittest.TestCase):
    def test_repeat_configuration_defaults_to_one_and_validates_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_config(directory, config())
            self.assertEqual(monitor.read_config(path)["notification_repeats"], 1)
            for value in (1, 2, 3):
                with self.subTest(value=value):
                    path = write_config(directory, config(notification_repeats=value))
                    self.assertEqual(monitor.read_config(path)["notification_repeats"], value)
            for value in (0, -1, 4, "3", 3.0, True, False, None):
                with self.subTest(invalid=value):
                    path = write_config(directory, config(notification_repeats=value))
                    with self.assertRaises(ValueError):
                        monitor.read_config(path)

    def test_repeat_count_keeps_both_production_state_identities(self):
        for frame, expected in (("15m", "74cfa9ae90bb5618"), ("1h", "a4bd3ed3f251e0b6")):
            for repeat in (1, 2, 3):
                with self.subTest(frame=frame, repeat=repeat):
                    cfg = dict(PRODUCTION_CONFIG, timeframe=frame, notification_repeats=repeat)
                    self.assertEqual(monitor.identity(cfg), expected)

    def test_queue_snapshots_repeat_count_only_for_new_signals(self):
        for frame in ("15m", "1h"):
            with self.subTest(frame=frame):
                cfg, items = config(frame, notification_repeats=3), candles(frame)
                duration = 3600 if frame == "1h" else 900
                state = monitor.new_state()
                state["last_bar"] = items[1][0]
                with patch.object(monitor, "crossing", return_value="up"):
                    monitor.process(items[:3], cfg, items[2][0] + duration + 660, state)
                    first_id = state["pending"][0]["id"]
                    monitor.process(items, dict(cfg, notification_repeats=1),
                                    items[3][0] + duration + 660, state)
                self.assertEqual([item["notifications_total"] for item in state["pending"]], [3, 1])
                self.assertEqual([item["notifications_sent"] for item in state["pending"]], [0, 0])
                self.assertEqual(state["pending"][0]["id"], first_id)
                self.assertEqual(state["last_bar"], items[-1][0])

    def test_both_frames_send_three_numbered_copies_and_persist_each_acceptance(self):
        for frame in ("15m", "1h"):
            with self.subTest(frame=frame), tempfile.TemporaryDirectory() as directory:
                cfg = config(frame, notification_repeats=3)
                state = monitor.new_state()
                state["pending"] = [event(cfg, total=3)]
                path = Path(directory) / "state.json"
                monitor.save_state(path, state)
                accepted = []
                def sender(subject, body, ident):
                    # The previous SMTP acceptance must already survive a process restart.
                    persisted = monitor.load_state(path)["pending"][0]
                    self.assertEqual(persisted["notifications_sent"], len(accepted))
                    number = len(accepted) + 1
                    self.assertIn(f"[{number}/3]", subject)
                    self.assertIn(f"{number}/3", body)
                    self.assertIn("1H" if frame == "1h" else "15 min", subject)
                    accepted.append((subject, body, ident))
                now = BASE + (3600 if frame == "1h" else 900) + 660
                monitor.deliver_pending(state, path, cfg, now, sender=sender)
                self.assertEqual(len(accepted), 3)
                self.assertEqual(len({item[2] for item in accepted}), 3)
                self.assertEqual(monitor.load_state(path)["pending"], [])
                with patch.object(monitor, "send_mail", side_effect=AssertionError("completed notification resent")) as no_resend:
                    monitor.deliver_pending(monitor.load_state(path), path, cfg, now + 60, sender=no_resend)

    def test_partial_smtp_failure_resumes_only_remaining_stable_copy_ids(self):
        for frame in ("15m", "1h"):
            for fail_at in (2, 3):
                with self.subTest(frame=frame, fail_at=fail_at), tempfile.TemporaryDirectory() as directory:
                    cfg = config(frame, notification_repeats=3)
                    state = monitor.new_state()
                    state["pending"] = [event(cfg, total=3)]
                    path = Path(directory) / "state.json"
                    monitor.save_state(path, state)
                    attempts = []
                    def intermittent(subject, body, ident):
                        attempts.append((subject, body, ident))
                        if len(attempts) == fail_at:
                            raise smtplib.SMTPServerDisconnected("simulated copy failure")
                    now = BASE + (3600 if frame == "1h" else 900) + 660
                    with self.assertRaises(smtplib.SMTPServerDisconnected):
                        monitor.deliver_pending(state, path, cfg, now, sender=intermittent)
                    reloaded = monitor.load_state(path)
                    self.assertEqual(reloaded["pending"][0]["notifications_total"], 3)
                    self.assertEqual(reloaded["pending"][0]["notifications_sent"], fail_at - 1)
                    remaining = []
                    monitor.deliver_pending(reloaded, path, dict(cfg, notification_repeats=1), now + 60,
                                            sender=lambda *args: remaining.append(args))
                    self.assertEqual(len(remaining), 4 - fail_at)
                    self.assertEqual(remaining[0][2], attempts[-1][2])
                    self.assertIn(f"[{fail_at}/3]", remaining[0][0])
                    self.assertTrue(set(item[2] for item in attempts[:-1]).isdisjoint(
                        item[2] for item in remaining))
                    self.assertEqual(monitor.load_state(path)["pending"], [])

    def test_completed_but_not_dequeued_event_is_removed_without_resending(self):
        cfg, state = config(notification_repeats=3), monitor.new_state()
        state["pending"] = [event(cfg, total=3, sent=3)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            monitor.save_state(path, state)
            with patch.object(monitor, "send_mail", side_effect=AssertionError("already accepted copies resent")) as no_resend:
                monitor.deliver_pending(state, path, cfg, BASE + 1560, sender=no_resend)
            self.assertEqual(monitor.load_state(path)["pending"], [])

    def test_expired_remaining_copies_are_dropped_without_smtp_for_both_frames(self):
        for frame in ("15m", "1h"):
            with self.subTest(frame=frame), tempfile.TemporaryDirectory() as directory:
                cfg, state = config(frame, notification_repeats=3), monitor.new_state()
                state["pending"] = [event(cfg, total=3, sent=1)]
                path = Path(directory) / "state.json"
                monitor.save_state(path, state)
                now = BASE + (3600 if frame == "1h" else 900) + cfg["maximum_alert_age_seconds"] + 1
                with patch.object(monitor, "send_mail", side_effect=AssertionError("expired copy sent")) as no_send:
                    monitor.deliver_pending(state, path, cfg, now, sender=no_send)
                self.assertEqual(monitor.load_state(path)["pending"], [])

    def test_legacy_pending_event_still_sends_one_with_original_message_id(self):
        cfg, state = config(notification_repeats=3), monitor.new_state()
        legacy = event(cfg)
        state["pending"] = [legacy]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            monitor.save_state(path, state)
            accepted = []
            monitor.deliver_pending(state, path, cfg, BASE + 1560,
                                    sender=lambda *args: accepted.append(args))
            self.assertEqual(len(accepted), 1)
            self.assertEqual(accepted[0][2], legacy["id"])
            self.assertNotIn("[1/3]", accepted[0][0])
            self.assertEqual(monitor.load_state(path)["pending"], [])

    def test_test_email_sends_three_clearly_marked_tests_without_market_or_state_access(self):
        cfg = config(notification_repeats=3, timeframes=["15m", "1h"])
        with tempfile.TemporaryDirectory() as directory:
            cfg_path = write_config(directory, cfg)
            state_path = Path(directory) / "existing-production-state.json"
            state_path.write_text('{"sentinel": "leave untouched"}', encoding="utf-8")
            original = state_path.read_bytes()
            with patch.object(monitor, "send_mail") as sender, \
                 patch.object(monitor, "fetch_chart", side_effect=AssertionError("test queried market")), \
                 patch.object(monitor, "load_state", side_effect=AssertionError("test read production state")), \
                 patch.object(monitor, "save_state", side_effect=AssertionError("test changed production state")), \
                 patch.object(monitor.smtplib, "SMTP", side_effect=AssertionError("real SMTP")):
                result = monitor.main(["--config", str(cfg_path), "--state-dir", directory, "--test-email"])
            self.assertEqual(result, 0)
            self.assertEqual(sender.call_count, 3)
            for number, sent in enumerate(sender.call_args_list, start=1):
                subject, body, _ = sent.args
                self.assertIn(f"[{number}/3]", subject)
                self.assertIn(f"{number}/3", body)
                self.assertIn("bandom", subject.casefold())
                self.assertIn("TEST", body)
                self.assertIn("ne rinkos signalas", body)
            self.assertEqual(len({sent.args[2] for sent in sender.call_args_list}), 3)
            self.assertEqual(state_path.read_bytes(), original)

    def test_three_copy_dry_run_does_not_send_or_save_either_frame(self):
        cfg = config(notification_repeats=3, timeframes=["15m", "1h"])
        closed = BASE + 14400
        series = {frame: candles(frame, closed=closed) for frame in cfg["timeframes"]}
        with tempfile.TemporaryDirectory() as directory:
            cfg_path = write_config(directory, cfg)
            originals = {}
            for frame in cfg["timeframes"]:
                frame_cfg = dict(cfg, timeframe=frame)
                path = Path(directory) / f"{monitor.identity(frame_cfg)}.json"
                state = monitor.new_state()
                state.update(last_bar=series[frame][-1][0],
                             pending=[event(frame_cfg, total=3, sent=1, stamp=series[frame][-1][0])])
                monitor.save_state(path, state)
                originals[path] = path.read_bytes()
            with patch.object(monitor, "fetch_chart", side_effect=lambda symbol, frame: chart_data(series[frame], frame)) as fetched, \
                 patch.object(monitor.time, "time", return_value=closed + 660), \
                 patch.object(monitor, "mail_settings", side_effect=AssertionError("dry-run credential access")), \
                 patch.object(monitor, "save_state", side_effect=AssertionError("dry-run wrote notification progress")), \
                 patch.object(monitor.smtplib, "SMTP", side_effect=AssertionError("dry-run SMTP")):
                result = monitor.main(["--config", str(cfg_path), "--state-dir", directory, "--dry-run"])
            self.assertEqual(result, 0)
            self.assertEqual(fetched.call_count, 2)
            for path, original in originals.items():
                self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
