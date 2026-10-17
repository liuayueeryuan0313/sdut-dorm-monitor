"""Small WebUI integration checks; school and QQ are always mocked."""
import tempfile
import unittest
from unittest.mock import Mock, patch
import webui
from sdut_login import LoginBlocked


class ElectricityWebTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = 1000.0
        self.monitor = webui.Monitor(self.directory.name, clock=lambda: self.now)
        self.addCleanup(self.monitor.close)
        self.monitor.save_config(dict(sdut_user="test", sdut_pwd="school-secret"))
        self.values = {key: self.monitor.config[key] for key in webui.ELC_CONFIG}
        self.client = Mock()
        self.client.query.return_value.to_dict.return_value = dict(remaining_kwh="74.62", balance_cny=None)

    def finish(self):
        with self.monitor.condition:
            self.assertTrue(self.monitor.condition.wait_for(lambda: not self.monitor.elc_busy, timeout=3))

    def test_manual_query_reuses_credentials_and_returns_result_without_notifications(self):
        with patch("sdut_electricity.ElectricityClient", return_value=self.client) as factory, patch.object(webui, "GroupNotifier") as notifier:
            self.monitor.request_electricity(self.values)
            self.finish()
            factory.assert_called_once_with("test", "school-secret")
            self.client.query.assert_called_once_with("西校区", "26号北楼", "8", "814", "照明插座")
            self.assertEqual(self.monitor.snapshot()["electricity"]["result"]["remaining_kwh"], "74.62")
            notifier.assert_not_called()
            with self.assertRaises(ValueError):
                self.monitor.request_electricity(self.values)

    def test_save_plan_does_not_query_and_survives_restart(self):
        self.values.update(elc_enabled=True, elc_minutes=30)
        self.monitor.request_electricity(self.values, query=False)
        self.assertEqual(self.monitor.elc_next_due, self.now + 1800)
        self.assertFalse(self.monitor.config["enabled"])
        reloaded = webui.Monitor(self.directory.name)
        self.addCleanup(reloaded.close)
        self.assertTrue(reloaded.config["elc_enabled"])
        self.assertEqual(reloaded.config["elc_minutes"], 30)

    def test_worker_queries_electricity_when_school_monitor_is_off(self):
        self.values.update(elc_enabled=True, elc_minutes=10)
        self.monitor.request_electricity(self.values, query=False)
        self.now += 600
        with patch("sdut_electricity.ElectricityClient", return_value=self.client):
            self.monitor.start_worker()
            with self.monitor.condition:
                self.assertTrue(self.monitor.condition.wait_for(lambda: self.monitor.elc_result is not None, timeout=3))
            self.finish()
        self.assertEqual(self.monitor.elc_next_due, self.now + 600)
        self.client.query.assert_called_once()

    def test_bad_intervals_and_concurrent_school_query_are_rejected(self):
        for value in (0, 4.99, True, None, float("nan"), 10081):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.monitor.request_electricity({**self.values, "elc_minutes": value}, query=False)
        self.monitor.busy = True
        with self.assertRaises(ValueError):
            self.monitor.request_electricity(self.values)

    def test_authentication_block_disables_automatic_query_and_redacts_password(self):
        self.values["elc_enabled"] = True
        self.client.query.side_effect = LoginBlocked("rejected school-secret")
        with patch("sdut_electricity.ElectricityClient", return_value=self.client):
            self.monitor.request_electricity(self.values)
            self.finish()
        self.assertFalse(self.monitor.config["elc_enabled"])
        self.assertIsNone(self.monitor.elc_next_due)
        self.assertNotIn("school-secret", self.monitor.elc_error)
        self.assertFalse(webui.read_json(self.monitor.data_dir / "webui_config.json", {})["elc_enabled"])

    def test_room_change_clears_result_and_invalid_fields_fail(self):
        self.monitor.elc_result = {"remaining_kwh": "74.62"}
        self.monitor.save_config({"elc_room": "815"})
        self.assertIsNone(self.monitor.elc_result)
        with self.assertRaises(ValueError):
            self.monitor.request_electricity({"elc_room": "814"})


if __name__ == "__main__":
    unittest.main()
