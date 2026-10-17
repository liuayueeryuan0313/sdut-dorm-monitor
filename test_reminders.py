"""Monthly reminders and native @all transport tests; all network is mocked."""
from datetime import datetime
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock, MagicMock, patch

import webui
from reminders import CHINA, fee_message, money, total_amount, month_date, following_month
from notifications import GroupNotifier, validate_notification


class CalendarTests(unittest.TestCase):
    def test_short_month_uses_last_day(self):
        due = month_date(datetime(2026, 2, 1, tzinfo=CHINA), 31, "09:30")
        self.assertEqual((due.day, due.hour, due.minute), (28, 9, 30))

    def test_leap_year_and_year_transition(self):
        self.assertEqual(month_date(datetime(2028, 2, 1, tzinfo=CHINA), 30, "00:00").day, 29)
        self.assertEqual(following_month(datetime(2026, 12, 31, tzinfo=CHINA)).isoformat(), "2027-01-01T00:00:00+08:00")

    def test_money_uses_exact_decimal_arithmetic(self):
        self.assertEqual(total_amount({"fee_amount": "0.10", "fee_people": 3}), "0.30")
        self.assertEqual(total_amount({"fee_amount": "18.88", "fee_people": 6}), "113.28")

    def test_invalid_money_is_rejected(self):
        for amount in (True, None, "NaN", "Infinity", "0", "-1", "2.001", "1000000", "bad"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                money(amount)

    def test_template_has_all_payment_details_and_wechat_instruction(self):
        content = fee_message({"fee_amount": "18.88", "fee_people": 6}, datetime(2026, 10, 1, tzinfo=CHINA))
        for required in ("2026年10月", "6 人", "18.88 元", "113.28 元", "前往微信宿舍群转账"):
            self.assertIn(required, content)


class MonthlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026, 10, 17, 12, tzinfo=CHINA).timestamp()
        self.monitor = webui.Monitor(self.temp.name, Mock(), clock=lambda: self.now)
        self.addCleanup(self.monitor.close)
        self.monitor.save_config({"onebot_url": "http://127.0.0.1:3000", "onebot_group_id": "123456",
                                  "fee_enabled": True, "fee_day": 15, "fee_time": "09:00",
                                  "fee_people": 6, "fee_amount": "18.88"})
        self.notifier_patch = patch.object(webui, "GroupNotifier")
        self.notifier = self.notifier_patch.start()
        self.addCleanup(self.notifier_patch.stop)
        self.notifier.return_value.send.return_value = {"message_id": 42}

    def test_monthly_notice_works_with_school_monitoring_stopped(self):
        self.assertFalse(self.monitor.config["enabled"])
        self.assertEqual(self.monitor.config["sdut_user"], "")
        self.monitor.send_fee()
        self.notifier.return_value.send.assert_called_once()
        self.assertEqual(self.monitor.fee_status()["status"], "sent")

    def test_success_is_once_per_month_even_after_restart(self):
        self.monitor.send_fee()
        self.monitor.send_fee()
        reloaded = webui.Monitor(self.temp.name, Mock(), clock=lambda: self.now)
        self.addCleanup(reloaded.close)
        reloaded.send_fee()
        self.notifier.return_value.send.assert_called_once()
        self.assertEqual(reloaded.fee_status()["next_at"], "2026-11-15T09:00:00+08:00")

    def test_config_change_after_success_does_not_resend_same_month(self):
        self.monitor.send_fee()
        self.monitor.save_config({"fee_amount": "30.00", "fee_day": 1})
        self.monitor.send_fee()
        self.notifier.return_value.send.assert_called_once()

    def test_next_month_sends_once_again(self):
        self.monitor.send_fee()
        self.now = datetime(2026, 11, 15, 10, tzinfo=CHINA).timestamp()
        self.monitor.send_fee()
        self.assertEqual(self.notifier.return_value.send.call_count, 2)

    def test_disabled_or_future_plan_sends_nothing(self):
        self.monitor.save_config({"fee_day": 31})
        self.monitor.send_fee()
        self.monitor.save_config({"fee_enabled": False, "fee_day": 1})
        self.monitor.send_fee()
        self.notifier.return_value.send.assert_not_called()

    def test_failed_or_uncertain_send_is_not_automatically_retried(self):
        self.notifier.return_value.send.side_effect = RuntimeError("timeout; result uncertain")
        self.monitor.send_fee()
        self.monitor.send_fee()
        self.notifier.return_value.send.assert_called_once()
        self.assertEqual(self.monitor.fee_status()["status"], "failed")
        self.assertIsNone(self.monitor.fee_schedule())

    def test_explicit_retry_can_send_after_failure(self):
        self.notifier.return_value.send.side_effect = [RuntimeError("failed"), {"message_id": 43}]
        self.monitor.send_fee()
        self.monitor.retry_fee()
        self.monitor.send_fee()
        self.assertEqual(self.notifier.return_value.send.call_count, 2)
        self.assertEqual(self.monitor.fee_status()["status"], "sent")
        with self.assertRaises(ValueError):
            self.monitor.retry_fee()

    def test_interrupted_attempt_is_not_resent_on_restart(self):
        self.monitor.fee_journal[self.monitor.fee_key(datetime.fromtimestamp(self.now, CHINA))] = {"status": "sending"}
        webui.write_json(self.monitor.fee_journal_path, self.monitor.fee_journal)
        reloaded = webui.Monitor(self.temp.name, Mock(), clock=lambda: self.now)
        self.addCleanup(reloaded.close)
        reloaded.send_fee()
        self.notifier.return_value.send.assert_not_called()

    def test_different_target_group_has_separate_receipt(self):
        self.monitor.send_fee()
        self.monitor.save_config({"onebot_group_id": "654321"})
        self.monitor.send_fee()
        self.assertEqual(self.notifier.return_value.send.call_count, 2)

    def test_fee_config_validation(self):
        for patch_values in ({"fee_day": 32}, {"fee_day": True}, {"fee_people": 0},
                             {"fee_people": 1.5}, {"fee_time": "24:00"}, {"fee_time": "9:00"},
                             {"fee_enabled": "yes"}, {"fee_amount": "1.001"}):
            with self.subTest(values=patch_values), self.assertRaises(ValueError):
                self.monitor.save_config(patch_values)

    def test_onebot_token_never_appears_in_config_response_or_error(self):
        self.monitor.save_config({"onebot_token": "private-onebot-token"})
        self.notifier.return_value.send.side_effect = RuntimeError("private-onebot-token must be hidden")
        self.monitor.send_fee()
        self.assertNotIn("private-onebot-token", json.dumps(self.monitor.snapshot()))

    def test_worker_sends_monthly_fee_without_school_monitoring(self):
        sent = threading.Event()
        def send(_):
            sent.set()
            return {"message_id": 42}
        self.notifier.return_value.send.side_effect = send
        self.monitor.start_worker()
        self.assertTrue(sent.wait(3))
        self.assertFalse(self.monitor.config["enabled"])

    def test_permission_probe_shows_reason_without_sending(self):
        self.notifier.return_value.check_at_all.side_effect = RuntimeError("@全体额度不足")
        with self.assertRaisesRegex(ValueError, "额度不足"):
            self.monitor.check_onebot()
        self.notifier.return_value.send.assert_not_called()


class OneBotTests(unittest.TestCase):
    def setUp(self):
        self.config = {**webui.DEFAULTS, "onebot_url": "http://127.0.0.1:3000", "onebot_token": "secret",
                       "onebot_group_id": "123456"}

    def test_native_at_all_is_present_in_every_send(self):
        notifier = GroupNotifier(self.config)
        with patch.object(notifier, "call", side_effect=[{"can_at_all": True}, {"message_id": 1}]) as request:
            notifier.send("test notice")
        self.assertEqual(request.call_args_list[0].args[0], "get_group_at_all_remain")
        action, payload = request.call_args.args
        self.assertEqual(action, "send_group_msg")
        self.assertEqual(payload["message"][0], {"type": "at", "data": {"qq": "all"}})
        self.assertEqual(payload["group_id"], 123456)

    def test_no_permission_or_quota_never_falls_back_to_plain_text(self):
        for result in ({"can_at_all": False}, {"can_at_all": True, "remain_at_all_count_for_uin": 0}):
            notifier = GroupNotifier(self.config)
            with patch.object(notifier, "call", return_value=result) as request, self.assertRaises(RuntimeError):
                notifier.send("notice")
            request.assert_called_once()

    def test_official_qq_group_transport_is_rejected_for_at_all(self):
        with self.assertRaises(ValueError):
            GroupNotifier({**self.config, "notification_provider": "qq_official"})

    def test_legacy_official_sender_cannot_silently_send_without_at_all(self):
        from sync_qqbot import QQBotClient
        client = QQBotClient("fake", "secret")
        with patch.object(client, "token") as token, self.assertRaises(RuntimeError):
            client.send_group("fake-group", "notice")
        token.assert_not_called()

    def test_invalid_url_and_group_are_rejected(self):
        for fields in ({"onebot_url": "file:///test"}, {"onebot_url": "https://user:pwd@example.com"},
                       {"onebot_url": "http://example.com?token=x"}, {"onebot_group_id": "not-a-number"},
                       {"onebot_group_id": "0"}, {"onebot_group_id": "１２３"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validate_notification({**self.config, **fields})

    def test_http_payload_and_bearer_authorization(self):
        notifier = GroupNotifier(self.config)
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"status": "ok", "retcode": 0, "data": {"can_at_all": True}}).encode()
        with patch.object(notifier.opener, "open", return_value=response) as request:
            notifier.check_at_all()
        req = request.call_args.args[0]
        self.assertEqual(req.get_header("Authorization"), "Bearer secret")
        self.assertEqual(json.loads(req.data), {"group_id": 123456})
        self.assertNotIn("secret", req.full_url)

    def test_async_or_failure_response_is_not_success(self):
        for status, retcode in (("failed", 100), ("async", 1)):
            notifier = GroupNotifier(self.config)
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({"status": status, "retcode": retcode}).encode()
            with patch.object(notifier.opener, "open", return_value=response), self.assertRaises(RuntimeError):
                notifier.check_at_all()

    def test_missing_message_id_is_not_confirmed_success(self):
        notifier = GroupNotifier(self.config)
        with patch.object(notifier, "call", side_effect=[{"can_at_all": True}, {}]), self.assertRaises(RuntimeError):
            notifier.send("notice")


if __name__ == "__main__":
    unittest.main(verbosity=2)
