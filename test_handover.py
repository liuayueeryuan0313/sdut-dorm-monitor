"""Offline acceptance checks; never contacts SDUT or QQ."""
import copy
import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import aes_tool
import sync_qqbot as sync


class SyncAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "data" / "state.json"
        self.path.parent.mkdir()
        self.state = {"seen": ["old"], "initialized": True,
                      "last_run": "previous", "last_push": None}
        self.path.write_text(json.dumps(self.state), encoding="utf-8")
        self.original = self.path.read_bytes()
        self.rows = [{"WID": "old", "JCRQ": "2026-10-15"},
                     {"WID": "new", "JCRQ": "2026-10-16"}]
        self.fetcher = Mock()
        self.fetcher.fetch.return_value = copy.deepcopy(self.rows)
        self.qq = Mock()
        self.enterContext(patch.object(sync, "STATE_FILE", str(self.path)))
        self.enterContext(patch.object(sync, "log"))

    def assert_preview_unchanged(self, state):
        before = copy.deepcopy(state)
        sync.run_once(self.fetcher, state, self.qq, dry_run=True)
        self.assertEqual(state, before)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.qq.send_group.assert_not_called()

    def test_preview_does_not_consume_new_records(self):
        self.assert_preview_unchanged(self.state)

    def test_preview_does_not_update_no_change_state(self):
        self.fetcher.fetch.return_value = self.rows[:1]
        self.assert_preview_unchanged(self.state)

    def test_preview_does_not_initialize_baseline(self):
        self.assert_preview_unchanged({"seen": [], "initialized": False})

    def test_first_real_run_only_initializes_baseline(self):
        state = {"seen": [], "initialized": False}
        sync.run_once(self.fetcher, state, self.qq)
        self.assertEqual(set(state["seen"]), {"old", "new"})
        self.assertTrue(state["initialized"])
        self.qq.send_group.assert_not_called()

    def test_explicit_baseline_does_not_send(self):
        sync.run_once(self.fetcher, self.state, self.qq, baseline=True)
        self.assertEqual(set(self.state["seen"]), {"old", "new"})
        self.qq.send_group.assert_not_called()

    def test_failed_send_keeps_record_pending(self):
        before = copy.deepcopy(self.state)
        self.qq.send_group.side_effect = RuntimeError("simulated send failure")
        with self.assertRaises(RuntimeError):
            sync.run_once(self.fetcher, self.state, self.qq)
        self.assertEqual(self.state, before)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_successful_send_is_not_repeated(self):
        sync.run_once(self.fetcher, self.state, self.qq)
        sync.run_once(self.fetcher, self.state, self.qq)
        self.qq.send_group.assert_called_once()
        self.assertEqual(set(self.state["seen"]), {"old", "new"})
        self.assertIsNotNone(self.state["last_push"])

    def test_selftest_does_not_print_secret_prefixes(self):
        output = io.StringIO()
        with patch.object(sync, "SDUT_PWD", "sentinel-school-password"), \
                patch.object(sync, "QQ_SECRET", "sentinel-bot-secret"), \
                redirect_stdout(output):
            sync.selftest()
        self.assertNotIn("sent", output.getvalue())


class ArchiveAcceptanceTests(unittest.TestCase):
    @unittest.skipUnless((Path(__file__).resolve().parent / "data" / "ssws_all.json").exists(),
                         "源码交接包不含私人原始数据，跳过历史数据验收")
    def test_preserved_data_and_baseline_match(self):
        root = Path(__file__).resolve().parent / "data"
        exported = json.loads((root / "ssws_all.json").read_text(encoding="utf-8"))
        state = json.loads((root / "sync_state.json").read_text(encoding="utf-8"))
        rows = exported["records_raw"]
        identifiers = [row["WID"] for row in rows]
        self.assertEqual(len(rows), 34)
        self.assertEqual(len(set(identifiers)), 34)
        self.assertEqual(set(identifiers), set(state["seen"]))
        self.assertTrue(state["initialized"])
        with (root / "ssws_records.csv").open(encoding="utf-8-sig", newline="") as source:
            csv_rows = list(csv.reader(source))
        self.assertEqual(len(csv_rows), 35)
        self.assertTrue(all(len(row) == 17 for row in csv_rows))

    def test_fips197_block_vector(self):
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        plain = bytes.fromhex("00112233445566778899aabbccddeeff")
        cipher = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
        keys = aes_tool.expand(key)
        self.assertEqual(aes_tool.enc_block(plain, keys), cipher)
        self.assertEqual(aes_tool.dec_block(cipher, keys), plain)

    def test_nist_cbc_vector_and_padding_roundtrip(self):
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        plain = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
        cipher = aes_tool.cbc_encrypt(plain, key, iv)
        self.assertEqual(cipher[:16].hex(), "7649abac8119b246cee98e9b12e9197d")
        self.assertEqual(aes_tool.cbc_decrypt(cipher, key, iv), plain)


if __name__ == "__main__":
    unittest.main(verbosity=2)
