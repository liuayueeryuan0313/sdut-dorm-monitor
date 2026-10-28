import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import webui
from widget_api import WidgetTokenFile, snapshot, save_electricity, restore_electricity

class WidgetTests(unittest.TestCase):
    def test_cached_zero_survives_error_and_actual_config_change_clears_it(self):
        result={'remaining_kwh':'0', 'checked_at':'2026-10-28T10:55:00+08:00'}
        save_electricity(self.monitor,result)
        self.monitor.elc_result=None
        self.monitor.elc_error='network unavailable'
        state=snapshot(self.monitor)['electricity']
        self.assertEqual(state['remainingKwh'],0)
        self.assertEqual(state['state'],'error')
        self.assertTrue(state['stale'])
        self.assertEqual(state['checkedAt'],result['checked_at'])
        self.monitor.save_config({'elc_room':'815'})
        self.assertIsNone(snapshot(self.monitor)['electricity']['remainingKwh'])
        self.assertEqual(json.loads((self.monitor.data_dir/'webui_widget_electricity.json').read_text()),{})

    def test_snapshot_never_collects_or_sends_and_reports_manual_collection(self):
        self.monitor.elc_busy=True
        with patch.object(self.monitor,'poll') as poll, patch.object(self.monitor,'request_electricity') as collect, patch.object(webui,'GroupNotifier') as notify:
            self.assertTrue(snapshot(self.monitor)['monitor']['collecting'])
            snapshot(self.monitor)
            poll.assert_not_called(); collect.assert_not_called(); notify.assert_not_called()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.monitor=webui.Monitor(self.temp.name)
        self.monitor.config.update(sdut_user='student-a', sdut_pwd='PRIVATE-PASSWORD')
        self.tokens=WidgetTokenFile(Path(self.temp.name)/'webui_widget_token.json')
    def tearDown(self):
        self.monitor.close(); self.temp.cleanup()
    def test_persistent_token_rotation_revoke_account_binding(self):
        key=self.monitor.account_key(); token=self.tokens.rotate(key)['token']
        self.assertTrue(WidgetTokenFile(self.tokens.path).authenticate('Bearer '+token,key))
        contents=self.tokens.path.read_text(); self.assertNotIn(token,contents)
        if os.name=='posix': self.assertEqual(self.tokens.path.stat().st_mode & 0o777,0o600)
        self.assertFalse(self.tokens.authenticate('Bearer '+token,'other-account'))
        other=self.tokens.rotate(key)['token']; self.assertFalse(self.tokens.authenticate('Bearer '+token,key))
        self.tokens.revoke(); self.assertFalse(self.tokens.authenticate('Bearer '+other,key))
    def test_projection_latest_and_missing_not_zero(self):
        self.monitor.rows=[{'JCRQ':'2026-10-01','FS':'96','DJMC':'合格'},
                           {'JCRQ':'2026-10-27','FS':'','DJMC':'合格','XSBH':'PRIVATE-ID','CZZ':'PRIVATE-STAFF','FJH':'814'}]
        response=snapshot(self.monitor)
        self.assertEqual(response['inspection']['date'],'2026-10-27')
        self.assertIsNone(response['inspection']['score'])
        self.assertIsNone(response['electricity']['remainingKwh'])
        for private in ('PRIVATE-ID','PRIVATE-STAFF','PRIVATE-PASSWORD'): self.assertNotIn(private,json.dumps(response))
        self.monitor.rows[-1]['FS']='0';self.assertEqual(snapshot(self.monitor)['inspection']['score'],0)
    def test_electricity_snapshot_restarts_and_room_isolation(self):
        result={'remaining_kwh':'58.60','checked_at':'2026-10-28T10:55:00+08:00','room':'814','raw_secret':'PRIVATE'}
        save_electricity(self.monitor,result)
        webui.write_json(Path(self.temp.name)/'webui_config.json', self.monitor.config)
        restarted=webui.Monitor(self.temp.name)
        try:
            self.assertEqual(snapshot(restarted)['electricity']['remainingKwh'],58.6)
            self.assertTrue(snapshot(restarted)['electricity']['stale'])
        finally:restarted.close()
        self.monitor.elc_result=None
        self.assertEqual(snapshot(self.monitor)['electricity']['remainingKwh'],58.6)
        restore_electricity(self.monitor)
        response=snapshot(self.monitor)
        self.assertEqual(response['electricity']['remainingKwh'],58.6)
        self.assertTrue(response['electricity']['stale'])
        self.assertNotIn('PRIVATE',(Path(self.temp.name)/'webui_widget_electricity.json').read_text())
        self.monitor.config['elc_room']='815';self.monitor.elc_result=None;restore_electricity(self.monitor)
        self.assertIsNone(self.monitor.elc_result)
        # A scheduled poll must finish before its room can change, just like a manual query.
        self.monitor.busy=True
        try:
            with self.assertRaises(ValueError):self.monitor.save_config({'elc_room':'816'})
            self.assertEqual(self.monitor.config['elc_room'],'815')
        finally:self.monitor.busy=False
    def test_http_auth_csrf_bearer_cannot_mutate(self):
        app=webui.WebApp(self.monitor);app.authenticate('Admin-test-password',setup=True)
        server=ThreadingHTTPServer(('127.0.0.1',0),webui.handler_for(app))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        def request(path,body=None,headers=None):
            return urlopen(Request(base+path,data=json.dumps(body).encode() if body is not None else None,
                headers={'Content-Type':'application/json','Origin':base,**(headers or {})}),timeout=5)
        try:
            with request('/api/login',{'password':'Admin-test-password'}) as r:cookie=r.headers['Set-Cookie'].split(';')[0];csrf=json.load(r)['csrf']
            with self.assertRaises(HTTPError) as e:request('/api/widget/token',{'action':'rotate'},{'Cookie':cookie})
            self.assertEqual(e.exception.code,403)
            with request('/api/widget/token',{'action':'rotate'},{'Cookie':cookie,'X-CSRF-Token':csrf}) as r:token=json.load(r)['token']
            with request('/api/widget/v1/dorm',headers={'Authorization':'Bearer '+token}) as r:self.assertEqual(json.load(r)['schemaVersion'],1)
            with self.assertRaises(HTTPError) as e:request('/api/widget/v1/dorm?token=forbidden',headers={'Authorization':'Bearer '+token})
            self.assertEqual(e.exception.code,400)
            with self.assertRaises(HTTPError) as e:request('/api/widget/token',{'action':'rotate'},{'Authorization':'Bearer '+token})
            self.assertEqual(e.exception.code,401)
            with self.assertRaises(HTTPError) as e:request('/api/widget/v1/dorm',headers={'Authorization':'Bearer '+token,'Host':'untrusted.example'})
            self.assertEqual(e.exception.code,421)
            with self.assertRaises(HTTPError) as e:request('/api/config',{}, {'Authorization':'Bearer '+token})
            self.assertEqual(e.exception.code,401)
            with request('/api/widget/token',{'action':'revoke'},{'Cookie':cookie,'X-CSRF-Token':csrf}):pass
            with self.assertRaises(HTTPError) as e:request('/api/widget/v1/dorm',headers={'Authorization':'Bearer '+token})
            self.assertEqual(e.exception.code,401)
        finally:server.shutdown();server.server_close();thread.join(timeout=3)

if __name__=='__main__':unittest.main()
