"""WebUI acceptance tests. No requests to SDUT or QQ are made."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import sdut_login
import webui


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000.0
        self.client = Mock()
        self.rows = [{"WID": "new", "JCRQ": "2026-10-17", "FS": 95}]
        self.client.list_records.return_value = self.rows
        self.factory = Mock(return_value=self.client)
        self.monitor = webui.Monitor(self.temp.name, self.factory, clock=lambda: self.now)
        self.addCleanup(self.monitor.close)
        self.monitor.save_config({"sdut_user": "test-account", "sdut_pwd": "school-secret"})

    def test_credentials_are_masked_and_blank_preserves_secret(self):
        self.monitor.save_config({"sdut_pwd": "", "qq_secret": "bot-secret"})
        result = self.monitor.public_config()
        self.assertNotIn("sdut_pwd", result)
        self.assertNotIn("qq_secret", result)
        self.assertTrue(result["sdut_pwd_set"])
        self.assertEqual(self.monitor.config["sdut_pwd"], "school-secret")

    def test_config_survives_restart(self):
        self.monitor.save_config({"poll_minutes": 2.5, "lookback_days": 90})
        reloaded = webui.Monitor(self.temp.name)
        self.addCleanup(reloaded.close)
        self.assertEqual(reloaded.config["poll_minutes"], 2.5)
        self.assertEqual(reloaded.config["sdut_pwd"], "school-secret")

    def test_interval_change_reschedules_without_restart(self):
        self.monitor.set_enabled(True)
        self.now += 2
        self.monitor.save_config({"poll_minutes": 2.5})
        self.assertEqual(self.monitor.next_due, self.now + 150)
        self.assertTrue(self.monitor.config["enabled"])

    def test_invalid_intervals_never_change_saved_config(self):
        for value in (0, -1, True, None, "oops", float("nan"), float("inf"), 10081):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.monitor.save_config({"poll_minutes": value})
        self.assertEqual(self.monitor.config["poll_minutes"], 15)

    def test_school_only_monitoring_does_not_require_qq(self):
        self.monitor.set_enabled(True)
        self.assertTrue(self.monitor.config["enabled"])
        self.monitor.set_enabled(False)
        self.assertIsNone(self.monitor.next_due)

    def test_qq_push_requires_complete_config(self):
        self.monitor.save_config({"push_enabled": True})
        with self.assertRaises(ValueError):
            self.monitor.set_enabled(True)

    def test_manual_preview_never_creates_read_baseline(self):
        self.monitor.poll(preview=True)
        self.assertFalse(self.monitor.state_path().exists())
        self.assertEqual(self.monitor.fresh_count, 1)
        self.assertTrue(self.monitor.last_success)

    def test_first_automatic_round_only_creates_baseline(self):
        self.monitor.set_enabled(True)
        with patch.object(webui, "GroupNotifier") as qq:
            self.monitor.poll()
            qq.assert_not_called()
        self.assertEqual(webui.read_json(self.monitor.state_path(), {})["seen"], ["new"])

    def test_existing_matching_account_imports_handover_baseline(self):
        webui.write_json(self.monitor.data_dir / "ssws_all.json", {"account": "test-account"})
        webui.write_json(self.monitor.data_dir / "sync_state.json", {"seen": ["imported"], "initialized": True})
        self.assertEqual(self.monitor.load_state()["seen"], ["imported"])
        self.monitor.save_config({"sdut_user": "different-account"})
        self.assertEqual(self.monitor.load_state()["seen"], [])

    def test_changing_accounts_clears_visible_records(self):
        self.monitor.poll(preview=True)
        self.monitor.save_config({"sdut_user": "another-account"})
        self.assertEqual(self.monitor.snapshot()["records"], [])
        self.assertEqual(self.monitor.snapshot()["record_count"], 0)

    def test_session_is_reused_for_multiple_rounds(self):
        self.monitor.poll(preview=True)
        self.monitor.poll(preview=True)
        self.factory.assert_called_once()
        self.client.bootstrap.assert_called_once()

    def test_failed_login_obeys_cooldown(self):
        self.factory.side_effect = RuntimeError("network unavailable")
        self.monitor.poll(preview=True)
        self.now += 60
        self.monitor.poll(preview=True)
        self.factory.assert_called_once()
        self.assertIn("冷却", self.monitor.last_error)

    def test_captcha_or_rejection_disables_monitor_persistently(self):
        self.monitor.set_enabled(True)
        self.factory.side_effect = sdut_login.LoginBlocked("captcha required")
        self.monitor.poll()
        self.assertFalse(self.monitor.config["enabled"])
        self.assertFalse(webui.read_json(self.monitor.data_dir / "webui_config.json", {})["enabled"])
        self.assertIsNone(self.monitor.next_due)

    def test_disabled_qq_keeps_new_records_pending(self):
        self.monitor.set_enabled(True)
        webui.write_json(self.monitor.state_path(), {"seen": [], "initialized": True})
        self.monitor.poll()
        self.assertEqual(self.monitor.load_state()["seen"], [])
        self.assertEqual(self.monitor.fresh_count, 1)

    def configure_push(self):
        self.monitor.save_config({"push_enabled": True, "qq_appid": "test-id",
                                  "qq_secret": "bot-secret", "qq_group_openid": "test-group",
                                  "onebot_url": "http://127.0.0.1:3000", "onebot_group_id": "123456"})
        self.monitor.set_enabled(True)
        webui.write_json(self.monitor.state_path(), {"seen": [], "initialized": True})

    def test_send_failure_does_not_consume_pending_records(self):
        self.configure_push()
        with patch.object(webui, "GroupNotifier") as qq:
            qq.return_value.send.side_effect = RuntimeError("simulated QQ failure")
            self.monitor.poll()
        self.assertEqual(self.monitor.load_state()["seen"], [])
        self.assertIn("simulated QQ failure", self.monitor.last_error)

    def test_sent_records_are_not_sent_twice(self):
        self.configure_push()
        with patch.object(webui, "GroupNotifier") as qq:
            self.monitor.poll()
            self.monitor.poll()
            qq.return_value.send.assert_called_once()
        self.assertEqual(self.monitor.load_state()["seen"], ["new"])

    def test_stopping_during_fetch_prevents_sending(self):
        self.configure_push()
        self.client.list_records.side_effect = lambda **_: (self.monitor.set_enabled(False), self.rows)[1]
        with patch.object(webui, "GroupNotifier") as qq:
            self.monitor.poll()
            qq.assert_not_called()
        self.assertEqual(self.monitor.load_state()["seen"], [])

    def test_disabling_push_during_fetch_prevents_sending(self):
        self.configure_push()
        self.client.list_records.side_effect = lambda **_: (self.monitor.save_config({"push_enabled": False}), self.rows)[1]
        with patch.object(webui, "GroupNotifier") as qq:
            self.monitor.poll()
            qq.assert_not_called()
        self.assertEqual(self.monitor.load_state()["seen"], [])

    def test_partial_batch_failure_only_consumes_confirmed_batch(self):
        self.configure_push()
        self.client.list_records.return_value = [{"WID": "r%d" % i} for i in range(7)]
        with patch.object(webui, "GroupNotifier") as qq:
            qq.return_value.send.side_effect = [{"id": "sent"}, RuntimeError("second batch failed")]
            self.monitor.poll()
        self.assertEqual(len(self.monitor.load_state()["seen"]), 5)

    def test_secret_values_never_appear_in_logs_or_status_error(self):
        self.monitor.record_error("school-secret should be hidden")
        self.assertNotIn("school-secret", json.dumps(self.monitor.snapshot()))
        self.assertNotIn("school-secret", (self.monitor.data_dir / "webui.log").read_text(encoding="utf-8"))

    def test_busy_round_allows_interval_edit_but_not_account_change(self):
        self.monitor.busy = True
        self.monitor.save_config({"poll_minutes": 7})
        with self.assertRaises(ValueError):
            self.monitor.save_config({"sdut_user": "new-account"})


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.monitor = webui.Monitor(self.temp.name, Mock())
        self.addCleanup(self.monitor.close)
        self.app = webui.WebApp(self.monitor)
        self.server = webui.ThreadingHTTPServer(("127.0.0.1", 0), webui.handler_for(self.app))
        self.addCleanup(self.server.server_close)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        self.cookie = None
        self.csrf = ""

    def request(self, method, path, payload=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        request_headers = {"Origin": "http://127.0.0.1:%d" % self.port,
                           "Content-Type": "application/json", "X-CSRF-Token": self.csrf}
        if self.cookie:
            request_headers["Cookie"] = self.cookie
        request_headers.update(headers or {})
        conn.request(method, path, json.dumps(payload) if payload is not None else None, request_headers)
        response = conn.getresponse()
        status, received, raw = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return status, received, raw

    def login(self):
        status, headers, raw = self.request("POST", "/api/setup", {"password": "test-admin-password"})
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";")[0]
        self.csrf = json.loads(raw)["csrf"]

    def test_status_requires_login(self):
        self.assertEqual(self.request("GET", "/api/status")[0], 401)

    def test_admin_password_hash_not_plaintext_and_cannot_reset_over_http(self):
        self.login()
        saved = self.app.admin_path.read_text(encoding="utf-8")
        self.assertNotIn("test-admin-password", saved)
        self.assertEqual(self.request("POST", "/api/setup", {"password": "other-admin-password"})[0], 400)

    def test_cross_origin_posts_and_bad_csrf_are_rejected(self):
        self.login()
        self.assertEqual(self.request("POST", "/api/config", {}, {"Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.request("POST", "/api/config", {}, {"X-CSRF-Token": "wrong"})[0], 403)

    def test_unknown_host_is_rejected(self):
        self.assertEqual(self.request("GET", "/api/session", headers={"Host": "malicious.example"})[0], 421)

    def test_api_config_save_and_secret_redaction(self):
        self.login()
        payload = dict(sdut_user="test-account", sdut_pwd="private-password", poll_minutes=3.5)
        self.assertEqual(self.request("POST", "/api/config", payload)[0], 200)
        status, _, raw = self.request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertNotIn(b"private-password", raw)
        self.assertEqual(json.loads(raw)["config"]["poll_minutes"], 3.5)

    def test_logout_invalidates_session(self):
        self.login()
        self.assertEqual(self.request("POST", "/api/logout", {})[0], 200)
        self.assertEqual(self.request("GET", "/api/status")[0], 401)

    def test_wrong_login_password_rejected(self):
        self.login()
        self.assertEqual(self.request("POST", "/api/login", {"password": "incorrect-password"})[0], 400)

    def test_static_assets_have_csp_and_no_data_paths_exposed(self):
        status, headers, raw = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Content-Security-Policy", headers)
        self.assertIn("监测控制台".encode(), raw)
        self.assertEqual(self.request("GET", "/data/webui_config.json")[0], 404)


class CaptchaTests(unittest.TestCase):
    def test_true_captcha_stops_before_any_password_submission(self):
        opener = Mock()
        with self.assertRaises(sdut_login.LoginBlocked):
            sdut_login.post_credentials(opener, "https://example.com", "user", "password",
                                        {"needCaptcha": "true"})
        opener.open.assert_not_called()

    def test_quoted_empty_captcha_allows_normal_login_request(self):
        opener = Mock()
        opener.open.return_value.read.return_value = b"ok"
        with patch.object(sdut_login, "encrypt_password", return_value="encrypted"):
            sdut_login.post_credentials(opener, "https://example.com", "user", "password",
                                        {"needCaptcha": '\"\"', "salt": "salt", "lt": "", "execution": "flow"})
        opener.open.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
