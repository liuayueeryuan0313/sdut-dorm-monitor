"""Comprehensive tests for new feature enhancements:
1. Multi-threshold electricity warnings & recharge reset
2. Combined dorm inspection & electricity query with session reuse
3. School account login test endpoint (/api/test-login)
4. Categorized logging system
5. Independent tab interface HTML structure verification
"""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import webui

HERE = Path(__file__).resolve().parent


class FeatureEnhancementsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000.0
        self.fake_client = Mock()
        self.fake_client.op = Mock()
        self.fake_client.bootstrap.return_value = [{"ROLENAME": "学生"}]
        self.fake_client.list_records.return_value = [{"WID": "rec_001", "JCRQ": "2026-10-18", "FS": 98, "DJMC": "优秀"}]
        self.factory = Mock(return_value=self.fake_client)

        self.monitor = webui.Monitor(self.temp.name, client_factory=self.factory, clock=lambda: self.now)
        self.addCleanup(self.monitor.close)

        self.app = webui.WebApp(self.monitor)
        self.server = webui.ThreadingHTTPServer(("127.0.0.1", 0), webui.handler_for(self.app))
        self.addCleanup(self.server.server_close)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

        # Initialize admin credentials and login
        self.app.authenticate("admin123456", setup=True)
        token, session = self.app.authenticate("admin123456", setup=False)
        self.cookie = "ssws_session=" + token
        self.csrf = session["csrf"]

    def request(self, method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {
            "Origin": f"http://127.0.0.1:{self.port}",
            "Content-Type": "application/json",
            "X-CSRF-Token": self.csrf,
            "Cookie": self.cookie
        }
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        conn.request(method, path, body, headers)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, resp.headers, data

    def test_html_contains_independent_tabs_and_controls(self):
        status, _, raw = self.request("GET", "/")
        self.assertEqual(status, 200)
        html = raw.decode("utf-8")

        # Independent tab views
        self.assertIn('id="view-overview"', html)
        self.assertIn('id="view-configuration"', html)
        self.assertIn('id="view-records"', html)
        self.assertIn('id="view-electricity"', html)
        self.assertIn('id="view-activity"', html)

        # Tab navigation items
        self.assertIn('data-target="overview"', html)
        self.assertIn('data-target="configuration"', html)
        self.assertIn('data-target="records"', html)
        self.assertIn('data-target="electricity"', html)
        self.assertIn('data-target="activity"', html)

        # School test login button
        self.assertIn('id="school-test-login"', html)
        self.assertIn('id="school-test-feedback"', html)

        # Electricity multi-thresholds & templates
        self.assertIn('id="elc-warn-thresholds"', html)
        self.assertIn('id="template-elc"', html)

        # Log filter buttons
        self.assertIn('id="log-filters"', html)
        self.assertIn('data-cat="auth"', html)
        self.assertIn('data-cat="dorm"', html)
        self.assertIn('data-cat="electricity"', html)
        self.assertIn('data-cat="bot"', html)

    def test_school_login_endpoint(self):
        # Configure credentials
        self.monitor.save_config({"sdut_user": "2021001", "sdut_pwd": "pwd-secret"})

        # Successful test login
        status, _, raw = self.request("POST", "/api/test-login", {"sdut_user": "2021001", "sdut_pwd": "pwd-secret"})
        self.assertEqual(status, 200)
        data = json.loads(raw.decode())
        self.assertTrue(data["ok"])
        self.assertIn("2021001", data["message"])
        self.factory.assert_called_once_with("2021001", "pwd-secret")
        self.fake_client.bootstrap.assert_called_once()

        # Check logs for auth event
        snapshot = self.monitor.snapshot()
        auth_logs = [e for e in snapshot["logs"] if e.get("category") == "auth"]
        self.assertTrue(any("测试登录成功" in e["message"] for e in auth_logs))

    def test_multi_threshold_warning_sequence_and_recharge_reset(self):
        self.monitor.save_config({
            "sdut_user": "2021001",
            "sdut_pwd": "pwd",
            "elc_warn_thresholds": "50, 20, 10, 5",
            "template_elc": "【电量报警】剩余: {balance}度 阈值: {threshold}度 楼栋: {building}",
            "push_enabled": True,
            "notification_provider": "onebot",
            "onebot_url": "http://127.0.0.1:3000",
            "onebot_group_id": "99999",
            "at_all_enabled": False
        })

        with patch.object(webui, "GroupNotifier") as notifier_cls:
            notifier = Mock()
            notifier_cls.return_value = notifier

            # 1. 55 kWh: above 50, no alert
            self.monitor.check_electricity_alerts({
                "remaining_kwh": "55.00", "building": "26号北楼", "room": "814"
            }, deliver=True)
            notifier.send.assert_not_called()
            self.assertEqual(self.monitor.elc_alerted_thresholds, set())

            # 2. 48 kWh: crossed 50 threshold -> triggers alert
            self.monitor.check_electricity_alerts({
                "remaining_kwh": "48.00", "building": "26号北楼", "room": "814"
            }, deliver=True)
            self.assertEqual(notifier.send.call_count, 1)
            msg = notifier.send.call_args[0][0]
            self.assertIn("剩余: 48.00度", msg)
            self.assertIn("阈值: 50.0度", msg)
            self.assertIn("楼栋: 26号北楼", msg)
            self.assertEqual(self.monitor.elc_alerted_thresholds, {50.0})

            # 3. 30 kWh: between 50 and 20, 50 already alerted -> no new alert
            self.monitor.check_electricity_alerts({
                "remaining_kwh": "30.00", "building": "26号北楼", "room": "814"
            }, deliver=True)
            self.assertEqual(notifier.send.call_count, 1)

            # 4. 19.5 kWh: crossed 20 threshold -> triggers alert
            self.monitor.check_electricity_alerts({
                "remaining_kwh": "19.50", "building": "26号北楼", "room": "814"
            }, deliver=True)
            self.assertEqual(notifier.send.call_count, 2)
            msg2 = notifier.send.call_args[0][0]
            self.assertIn("阈值: 20.0度", msg2)
            self.assertEqual(self.monitor.elc_alerted_thresholds, {50.0, 20.0})

            # 5. 9.8 kWh: crossed 10 threshold -> triggers alert
            self.monitor.check_electricity_alerts({
                "remaining_kwh": "9.80", "building": "26号北楼", "room": "814"
            }, deliver=True)
            self.assertEqual(notifier.send.call_count, 3)
            self.assertEqual(self.monitor.elc_alerted_thresholds, {50.0, 20.0, 10.0})

            # 6. 4.2 kWh: crossed 5 threshold -> triggers alert
            self.monitor.check_electricity_alerts({
                "remaining_kwh": "4.20", "building": "26号北楼", "room": "814"
            }, deliver=True)
            self.assertEqual(notifier.send.call_count, 4)
            self.assertEqual(self.monitor.elc_alerted_thresholds, {50.0, 20.0, 10.0, 5.0})

            # 7. Student recharged! New reading is 100 kWh -> resets all alerted thresholds
            self.monitor.check_electricity_alerts({
                "remaining_kwh": "100.00", "building": "26号北楼", "room": "814"
            }, deliver=True)
            self.assertEqual(notifier.send.call_count, 4)  # No alert on recharge
            self.assertEqual(self.monitor.elc_alerted_thresholds, set())

            # 8. Electricity drops to 45 kWh again -> triggers 50 kWh alert again!
            self.monitor.check_electricity_alerts({
                "remaining_kwh": "45.00", "building": "26号北楼", "room": "814"
            }, deliver=True)
            self.assertEqual(notifier.send.call_count, 5)
            self.assertIn(50.0, self.monitor.elc_alerted_thresholds)

    def test_combined_polling_and_session_reuse(self):
        self.monitor.save_config({
            "sdut_user": "2021001",
            "sdut_pwd": "pwd",
            "elc_enabled": True,
            "elc_campus": "西校区",
            "elc_building": "26号北楼",
            "elc_floor": "8",
            "elc_room": "814",
            "elc_type": "照明插座"
        })
        self.monitor.set_enabled(True)

        fake_elc = Mock()
        fake_elc.query.return_value.to_dict.return_value = {
            "remaining_kwh": "62.30", "balance_cny": "30.00", "page_location": "西校区 26号北楼 814"
        }

        with patch("sdut_electricity.ElectricityClient", return_value=fake_elc) as elc_cls:
            # First poll: initial login
            self.monitor.poll()
            self.factory.assert_called_once()
            self.fake_client.bootstrap.assert_called_once()
            self.fake_client.list_records.assert_called_once()
            fake_elc.query.assert_called_once()
            self.assertEqual(self.monitor.elc_result["remaining_kwh"], "62.30")

            # Second poll: session is reused! Zero new logins
            self.now += 60
            self.monitor.poll()
            # client_factory not called again!
            self.assertEqual(self.factory.call_count, 1)

            # Check logs contain session reuse indication
            snapshot = self.monitor.snapshot()
            logs = snapshot["logs"]
            self.assertTrue(any("复用现有学校认证会话" in log["message"] for log in logs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
