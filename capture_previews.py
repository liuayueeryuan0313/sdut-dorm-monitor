import socket
import base64
import os
import json
import urllib.request
import subprocess
import time
from pathlib import Path

ARTIFACT_DIR = Path(r"C:\Users\liuay\.gemini\antigravity\brain\b7d11344-cc56-4a05-a889-5849f93e2418")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

def ws_connect(host, port, path):
    s = socket.create_connection((host, port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\n"
           f"Host: {host}:{port}\r\n"
           f"Upgrade: websocket\r\n"
           f"Connection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\n"
           f"Sec-WebSocket-Version: 13\r\n\r\n")
    s.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = s.recv(1024)
        if not chunk:
            break
        resp += chunk
    if b"101" not in resp:
        raise RuntimeError("WebSocket handshake failed: " + resp.decode('latin1', 'replace'))
    return s

def ws_send(s, data):
    payload = data.encode('utf-8')
    header = bytearray([0x81])
    mask = os.urandom(4)
    length = len(payload)
    if length <= 125:
        header.append(0x80 | length)
    elif length <= 65535:
        header.append(0x80 | 126)
        header.extend(length.to_bytes(2, 'big'))
    else:
        header.append(0x80 | 127)
        header.extend(length.to_bytes(8, 'big'))
    header.extend(mask)
    masked = bytearray(b ^ mask[i % 4] for i, b in enumerate(payload))
    s.sendall(header + masked)

def ws_recv(s):
    hdr = bytearray()
    while len(hdr) < 2:
        hdr.extend(s.recv(2 - len(hdr)))
    b1, b2 = hdr[0], hdr[1]
    length = b2 & 0x7f
    if length == 126:
        ext = bytearray()
        while len(ext) < 2:
            ext.extend(s.recv(2 - len(ext)))
        length = int.from_bytes(ext, 'big')
    elif length == 127:
        ext = bytearray()
        while len(ext) < 8:
            ext.extend(s.recv(8 - len(ext)))
        length = int.from_bytes(ext, 'big')
    data = bytearray()
    while len(data) < length:
        chunk = s.recv(min(length - len(data), 65536))
        if not chunk:
            break
        data.extend(chunk)
    return data.decode('utf-8', 'replace')

def cdp_call(s, method, params=None, msg_id=[1]):
    mid = msg_id[0]
    msg_id[0] += 1
    req = {"id": mid, "method": method, "params": params or {}}
    ws_send(s, json.dumps(req))
    while True:
        raw = ws_recv(s)
        try:
            msg = json.loads(raw)
            if msg.get("id") == mid:
                return msg.get("result", {})
        except Exception:
            pass

def main():
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    user_data = Path(r"C:\Users\liuay\.gemini\antigravity\scratch\ssws-gemini-handoff-20261017\.chrome_temp")
    user_data.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        chrome_path,
        "--headless=new",
        "--remote-debugging-port=9444",
        f"--user-data-dir={user_data}",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1280,900"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(2)
    
    try:
        req = urllib.request.Request("http://127.0.0.1:9444/json/new?http://127.0.0.1:8787/", method="PUT")
        try:
            with urllib.request.urlopen(req) as r:
                target = json.loads(r.read())
        except Exception:
            with urllib.request.urlopen("http://127.0.0.1:9444/json/list") as r:
                targets = json.loads(r.read())
                target = targets[0]
        ws_url = target["webSocketDebuggerUrl"]
        
        # Connect to page websocket
        from urllib.parse import urlparse
        u = urlparse(ws_url)
        ws = ws_connect(u.hostname, u.port, u.path)
        
        # Set viewport
        cdp_call(ws, "Emulation.setDeviceMetricsOverride", {
            "width": 1280, "height": 900, "deviceScaleFactor": 1.5, "mobile": False
        })
        
        # Log in
        time.sleep(1)
        cdp_call(ws, "Runtime.evaluate", {
            "expression": """
                document.getElementById('admin-password').value = '@A117803737478a';
                document.getElementById('auth-submit').click();
            """
        })
        time.sleep(1.5)
        
        # Function to capture view screenshot
        tabs = [
            ("overview", "tab1_overview.png"),
            ("configuration", "tab2_configuration.png"),
            ("records", "tab3_records.png"),
            ("electricity", "tab4_electricity.png"),
            ("activity", "tab5_activity.png")
        ]
        
        for tab_id, filename in tabs:
            cdp_call(ws, "Runtime.evaluate", {
                "expression": f"switchView('{tab_id}')"
            })
            time.sleep(0.5)
            res = cdp_call(ws, "Page.captureScreenshot", {"format": "png"})
            data = base64.b64decode(res["data"])
            out_path = ARTIFACT_DIR / filename
            out_path.write_bytes(data)
            print(f"Captured {tab_id} -> {out_path} ({len(data)} bytes)")
            
    finally:
        proc.terminate()
        proc.wait()
        print("Chrome closed.")

if __name__ == "__main__":
    main()
