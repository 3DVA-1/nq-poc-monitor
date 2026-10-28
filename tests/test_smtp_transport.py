"""Offline checks for a bounded, verified Gmail SMTP transport fallback."""
import smtplib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor


class SMTPTransportTests(unittest.TestCase):
    def setUp(self):
        replacements = (
            patch.object(monitor, "mail_settings",
                         return_value=("sender@example.com", "dummy-app-password", "recipient@example.com")),
            patch.object(monitor.smtplib, "SMTP"),
            patch.object(monitor.smtplib, "SMTP_SSL"),
        )
        self.settings, self.connect_587, self.connect_465 = [item.start() for item in replacements]
        for item in replacements:
            self.addCleanup(item.stop)
        self.context_587 = self.connect_587.return_value
        self.context_465 = self.connect_465.return_value
        self.smtp_587 = self.context_587.__enter__.return_value
        self.smtp_465 = self.context_465.__enter__.return_value
        self.smtp_587.send_message.return_value = {}
        self.smtp_465.send_message.return_value = {}

    def test_login_disconnect_uses_verified_465_once_and_sends_one_message(self):
        self.smtp_587.login.side_effect = smtplib.SMTPServerDisconnected("simulated pre-send disconnect")
        monitor.send_mail("Numbered signal [1/3]", "A test body, no market action.", "signal-copy-1")
        self.connect_587.assert_called_once_with("smtp.gmail.com", 587, timeout=30)
        self.connect_465.assert_called_once()
        self.assertEqual(self.connect_465.call_args.args, ("smtp.gmail.com", 465))
        self.assertEqual(self.connect_465.call_args.kwargs["timeout"], 30)
        context = self.connect_465.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, monitor.ssl.CERT_REQUIRED)
        self.assertEqual([item[0] for item in self.smtp_587.method_calls],
                         ["ehlo", "starttls", "ehlo", "login"])
        self.assertEqual([item[0] for item in self.smtp_465.method_calls],
                         ["ehlo", "login", "send_message"])
        self.smtp_465.starttls.assert_not_called()
        self.smtp_587.send_message.assert_not_called()
        self.smtp_465.login.assert_called_once_with("sender@example.com", "dummy-app-password")
        self.smtp_465.send_message.assert_called_once()
        message = self.smtp_465.send_message.call_args.args[0]
        self.assertEqual(message["Subject"], "Numbered signal [1/3]")
        self.assertEqual(message["To"], "recipient@example.com")
        self.assertEqual(message["Message-ID"], "<nq-signal-copy-1@nq-monitor.local>")
        self.assertEqual(message.get_content().strip(), "A test body, no market action.")

    def test_rejected_credentials_do_not_retry_on_465(self):
        rejection = smtplib.SMTPAuthenticationError(535, b"simulated authentication rejection")
        self.smtp_587.login.side_effect = rejection
        with self.assertRaises(smtplib.SMTPAuthenticationError) as raised:
            monitor.send_mail("Test", "Test body", "rejected-login")
        self.assertIs(raised.exception, rejection)
        self.connect_465.assert_not_called()
        self.smtp_587.send_message.assert_not_called()

    def test_starttls_certificate_failure_never_authenticates_or_falls_back(self):
        failure = monitor.ssl.SSLCertVerificationError(1, "simulated certificate verification failure")
        self.smtp_587.starttls.side_effect = failure
        with self.assertRaises(monitor.ssl.SSLCertVerificationError) as raised:
            monitor.send_mail("Test", "Test body", "unverified-starttls")
        self.assertIs(raised.exception, failure)
        self.connect_465.assert_not_called()
        self.smtp_587.login.assert_not_called()
        self.smtp_587.send_message.assert_not_called()

    def test_disconnect_during_submission_never_sends_another_transport_copy(self):
        failure = smtplib.SMTPServerDisconnected("simulated ambiguous DATA result")
        self.smtp_587.send_message.side_effect = failure
        with self.assertRaises(smtplib.SMTPServerDisconnected) as raised:
            monitor.send_mail("Test", "Test body", "ambiguous-submission")
        self.assertIs(raised.exception, failure)
        self.smtp_587.send_message.assert_called_once()
        self.connect_465.assert_not_called()

    def test_disconnect_during_quit_after_acceptance_does_not_fall_back(self):
        failure = smtplib.SMTPServerDisconnected("simulated post-acceptance QUIT disconnect")
        self.context_587.__exit__.side_effect = failure
        with self.assertRaises(smtplib.SMTPServerDisconnected) as raised:
            monitor.send_mail("Test", "Test body", "accepted-before-quit")
        self.assertIs(raised.exception, failure)
        self.smtp_587.send_message.assert_called_once()
        self.connect_465.assert_not_called()

    def test_both_login_disconnects_propagate_after_only_two_attempts(self):
        first = smtplib.SMTPServerDisconnected("simulated port587 login disconnect")
        second = smtplib.SMTPServerDisconnected("simulated port465 login disconnect")
        self.smtp_587.login.side_effect = first
        self.smtp_465.login.side_effect = second
        with self.assertRaises(smtplib.SMTPServerDisconnected) as raised:
            monitor.send_mail("Test", "Test body", "both-transport-logins-failed")
        self.assertIs(raised.exception, second)
        self.connect_587.assert_called_once()
        self.connect_465.assert_called_once()
        self.smtp_587.send_message.assert_not_called()
        self.smtp_465.send_message.assert_not_called()

    def test_fallback_certificate_failure_is_propagated_without_any_submission(self):
        self.smtp_587.login.side_effect = smtplib.SMTPServerDisconnected("simulated pre-send disconnect")
        failure = monitor.ssl.SSLCertVerificationError(1, "simulated implicit TLS certificate failure")
        self.connect_465.side_effect = failure
        with self.assertRaises(monitor.ssl.SSLCertVerificationError) as raised:
            monitor.send_mail("Test", "Test body", "unverified-implicit-tls")
        self.assertIs(raised.exception, failure)
        self.connect_587.assert_called_once()
        self.connect_465.assert_called_once()
        self.smtp_587.send_message.assert_not_called()
        self.smtp_465.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
