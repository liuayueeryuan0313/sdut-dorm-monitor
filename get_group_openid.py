#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取 QQ 群 group_openid（推送目标地址）.

为什么需要它: group_openid 每个机器人各不相同, 且没有查询接口,
只能从"群里 @ 机器人"时下发的事件里取.

前置:
  1. QQ 开放平台已创建机器人
  2. 开发设置里"事件订阅与回调方式"选 WebSocket
  3. 机器人已加入目标群

用法:
    set QQ_APPID=你的AppID
    set QQ_SECRET=你的AppSecret
    python get_group_openid.py

    然后在目标群里 @ 一次机器人, 脚本打印 group_openid 并退出.

    python get_group_openid.py --selftest    # 只测 WebSocket 帧编解码, 不联网
"""
import argparse
import base64
import json
import os
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request

from sync_qqbot import QQBotClient

OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

INTENTS_GROUP_AND_C2C = 1 << 25   # 33554432: 群@ / 单聊 / 加群/退群 等事件

UA = "dsh-qqbot-openid/1.0"

# RFC 6455 关闭码
CLOSE_CODES = {
    4001: "无效的 opcode", 4002: "无效的 payload", 4006: "无效的 session id",
    4007: "seq 错误", 4008: "发送 payload 过快", 4009: "连接过期",
    4010: "无效的 shard", 4011: "需要处理的 guild 过多", 4012: "无效的 version",
    4013: "无效的 intent", 4014: "intent 无权限",
    4914: "机器人已下架(仅沙箱)", 4915: "机器人已封禁",
}


# ------------------------- WebSocket 最小实现 -------------------------

def parse_header(buf):
    """返回 (opcode, masked, payload_len, header_len); 数据不够时返回 None."""
    if len(buf) < 2:
        return None
    b0, b1 = buf[0], buf[1]
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    n = b1 & 0x7F
    offset = 2
    if n == 126:
        if len(buf) < 4:
            return None
        n = struct.unpack(">H", buf[2:4])[0]
        offset = 4
    elif n == 127:
        if len(buf) < 10:
            return None
        n = struct.unpack(">Q", buf[2:10])[0]
        offset = 10
    if masked:
        offset += 4
    return opcode, masked, n, offset


def encode_frame(payload, opcode=0x1):
    """客户端 -> 服务端, 必须加掩码."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    n = len(payload)
    head = bytearray([0x80 | opcode])
    if n < 126:
        head.append(0x80 | n)
    elif n < 65536:
        head.append(0x80 | 126)
        head += struct.pack(">H", n)
    else:
        head.append(0x80 | 127)
        head += struct.pack(">Q", n)
    mask = os.urandom(4)
    head += mask
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return bytes(head) + masked


def decode_frame(raw):
    """仅供自检: 解一个完整帧, 返回 (opcode, payload)."""
    h = parse_header(raw)
    if h is None:
        raise ValueError("帧不完整")
    opcode, masked, n, offset = h
    body = raw[offset:offset + n]
    if masked:
        key = raw[offset - 4:offset]
        body = bytes(b ^ key[i % 4] for i, b in enumerate(body))
    return opcode, body


class WSSock:
    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def _need(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self.buf)))
            if not chunk:
                raise ConnectionError("连接被服务端关闭")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv_frame(self):
        """返回 (opcode, payload_bytes). 控制帧也会返回."""
        while True:
            h = parse_header(self.buf)
            if h is not None:
                opcode, masked, n, offset = h
                if len(self.buf) >= offset + n:
                    frame = self._need(offset + n)
                    body = frame[offset:]
                    if masked:
                        key = frame[offset - 4:offset]
                        body = bytes(b ^ key[i % 4] for i, b in enumerate(body))
                    return opcode, body
            # 缓冲不足, 再读
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("连接被服务端关闭")
            self.buf += chunk

    def send_text(self, text):
        self.sock.sendall(encode_frame(text, 0x1))

    def send_control(self, opcode, payload=b""):
        self.sock.sendall(encode_frame(payload, opcode))


def ws_connect(url, timeout=20):
    import urllib.parse as up
    u = up.urlparse(url)
    host = u.hostname
    port = u.port or (443 if u.scheme == "wss" else 80)
    path = u.path or "/"
    if u.query:
        path += "?" + u.query

    raw = socket.create_connection((host, port), timeout=timeout)
    if u.scheme == "wss":
        ctx = ssl.create_default_context()
        raw = ctx.wrap_socket(raw, server_hostname=host)

    key = base64.b64encode(os.urandom(16)).decode()
    handshake = (
        "GET " + path + " HTTP/1.1\r\n"
        "Host: " + host + "\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: " + key + "\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "User-Agent: " + UA + "\r\n\r\n"
    )
    raw.sendall(handshake.encode("utf-8"))

    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = raw.recv(4096)
        if not chunk:
            raise RuntimeError("WebSocket 握手失败: 连接被关闭")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n")[0].decode("utf-8", "replace")
    if "101" not in status_line:
        raise RuntimeError("WebSocket 握手失败: " + status_line + " | "
                           + head.decode("utf-8", "replace")[:300])

    ws = WSSock(raw)
    ws.buf = rest
    return ws


# ------------------------- 主流程 -------------------------

def capture(appid, secret, timeout, quiet=False):
    def say(msg):
        if not quiet:
            print(msg, flush=True)

    say("1) 获取 access_token ...")
    token = QQBotClient(appid, secret).token()
    say("   成功")

    say("2) 获取 WebSocket 接入点 ...")
    req = urllib.request.Request(
        "https://api.bot.qq.com/gateway",
        headers={"Authorization": "QQBot " + token, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        gw = json.loads(resp.read().decode("utf-8"))
    url = gw.get("url")
    if not url:
        raise RuntimeError("获取网关地址失败: " + json.dumps(gw, ensure_ascii=False))
    say("   " + url)

    say("3) 建立 WebSocket 长连接 ...")
    ws = ws_connect(url, timeout=20)
    say("   已连接")

    heartbeat_ms = 45000
    next_beat = time.time() + heartbeat_ms / 1000.0
    last_seq = None
    identified = False
    deadline = time.time() + timeout
    result = None

    ws.sock.settimeout(2.0)
    while time.time() < deadline:
        # 心跳
        if identified and time.time() >= next_beat:
            ws.send_text(json.dumps({"op": OP_HEARTBEAT, "d": last_seq}))
            next_beat = time.time() + heartbeat_ms / 1000.0

        try:
            opcode, body = ws.recv_frame()
        except socket.timeout:
            continue

        if opcode == 0x8:   # close
            code = struct.unpack(">H", body[:2])[0] if len(body) >= 2 else 0
            raise RuntimeError("服务端关闭连接 code=%s %s"
                               % (code, CLOSE_CODES.get(code, "")))
        if opcode == 0x9:   # ping
            ws.send_control(0xA, body)
            continue
        if opcode == 0xA:   # pong
            continue

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            continue

        op = payload.get("op")
        if payload.get("s") is not None:
            last_seq = payload["s"]

        if op == OP_HELLO:
            heartbeat_ms = (payload.get("d") or {}).get("heartbeat_interval", 45000)
            next_beat = time.time() + heartbeat_ms / 1000.0
            say("   Hello, 心跳周期 %dms, 发送 Identify ..." % heartbeat_ms)
            ws.send_text(json.dumps({
                "op": OP_IDENTIFY,
                "d": {
                    "token": "QQBot " + token,
                    "intents": INTENTS_GROUP_AND_C2C,
                    "shard": [0, 1],
                    "properties": {"$os": "windows", "$browser": "dsh", "$device": "dsh"},
                }}))
        elif op == OP_HEARTBEAT_ACK:
            pass
        elif op == OP_INVALID_SESSION:
            raise RuntimeError("鉴权失败: 服务端返回 Invalid Session (检查 AppID/AppSecret 与 intents 权限)")
        elif op == OP_DISPATCH:
            t = payload.get("t")
            d = payload.get("d") or {}
            if t == "READY":
                identified = True
                user = d.get("user") or {}
                say("   鉴权成功, 机器人: %s (id=%s) session=%s"
                    % (user.get("username"), user.get("id"), d.get("session_id")))
                say("")
                say(">>> 现在请在目标群里 @ 一次机器人 <<<")
                say("")
            elif t == "GROUP_AT_MESSAGE_CREATE":
                goid = d.get("group_openid")
                author = (d.get("author") or {}).get("member_openid")
                say("   收到群消息: group_openid=%s member_openid=%s" % (goid, author))
                result = {"group_openid": goid, "member_openid": author,
                          "content": d.get("content"), "raw": d}
                break

    ws.send_control(0x8, struct.pack(">H", 1000))
    return result


def selftest():
    print("=== WebSocket 帧编解码自检 ===")
    cases = [b"", b"x", b"a" * 125, b"b" * 126, b"c" * 65535, b"d" * 65536,
             json.dumps({"op": 2, "d": {"token": "QQBot x"}}).encode()]
    ok = True
    for i, payload in enumerate(cases):
        raw = encode_frame(payload, 0x1)
        opcode, out = decode_frame(raw)
        good = (opcode == 0x1 and out == payload)
        ok = ok and good
        print("  用例 %d: %6d bytes -> %-6s" % (i, len(payload), "OK" if good else "FAIL"))
    # 掩码位必须为 1
    raw = encode_frame(b"hi", 0x1)
    h = parse_header(raw)
    print("  掩码位: %s" % ("OK" if h[1] else "FAIL"))
    ok = ok and h[1]
    print()
    print("自检结果: %s" % ("全部通过" if ok else "有失败"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="抓取 QQ 群 group_openid")
    ap.add_argument("--appid", default=os.environ.get("QQ_APPID", ""))
    ap.add_argument("--secret", default=os.environ.get("QQ_SECRET", ""))
    ap.add_argument("--timeout", type=int, default=240, help="等待秒数, 默认 240")
    ap.add_argument("--selftest", action="store_true", help="只测帧编解码, 不联网")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not args.appid or not args.secret:
        print(__doc__)
        print("缺少 AppID / AppSecret: 用 --appid --secret 或环境变量 QQ_APPID / QQ_SECRET")
        return 2

    try:
        res = capture(args.appid, args.secret, args.timeout)
    except urllib.error.HTTPError as e:
        print("HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:300]))
        return 1
    except Exception as e:
        print("失败: %s" % e)
        return 1

    if not res:
        print("超时, 没收到群消息事件。确认: 1) 机器人已在群里 2) 事件订阅方式为 WebSocket 3) 已 @ 机器人")
        return 1

    print()
    print("=" * 60)
    print("group_openid = %s" % res["group_openid"])
    print("=" * 60)
    print()
    print("把这个值填进 sync_qqbot.py 的 QQ_GROUP_OPENID, 或设为环境变量。")
    os.makedirs("data", exist_ok=True)
    with open(os.path.join("data", "group_openid.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    print("已保存到 data/group_openid.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
