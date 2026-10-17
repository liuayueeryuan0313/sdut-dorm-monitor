#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查寝结果 -> QQ 机器人 定时同步.

设计约束(来自实测):
  1. CAS 登录会被限流 -> 只登录一次并长期复用会话, 失败退避重试
  2. 增量判据用 WID(记录唯一 ID), 不用日期
  3. 首次运行只做基线, 不推送历史记录

用法:
    python sync_qqbot.py --selftest    # 离线自检: 配置/状态/消息格式
    python sync_qqbot.py --baseline    # 把现有记录记为已读, 不推送
    python sync_qqbot.py --once        # 跑一轮(可用于 cron)
    python sync_qqbot.py               # 常驻定时循环
    python sync_qqbot.py --dry-run     # 跑一轮但不真的发 QQ
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from sdut_ssws import SswsClient
from sdut_login import LoginBlocked

# ============================ 配置区 ============================
# 全部支持环境变量覆盖, 优先级: 环境变量 > 文件内取值
# 这样密码与密钥可以不落盘

# --- 学工系统账号 ---
SDUT_USER = os.environ.get("SDUT_USER", "")       # TODO 学号
SDUT_PWD = os.environ.get("SDUT_PWD", "")         # TODO 密码

# --- QQ 机器人 ---
QQ_APPID = os.environ.get("QQ_APPID", "")                    # TODO 机器人 AppID
QQ_SECRET = os.environ.get("QQ_SECRET", "")                  # TODO 机器人 AppSecret
QQ_GROUP_OPENID = os.environ.get("QQ_GROUP_OPENID", "")      # TODO 推送目标群的 group_openid

# --- 调度 ---
POLL_INTERVAL_MINUTES = int(os.environ.get("POLL_INTERVAL_MINUTES", "15"))  # TODO 轮询间隔(分钟)
ACTIVE_HOURS = []                   # TODO 活跃时段, 如 [(21, 0), (23, 30)]; 留空 = 全天
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "45"))   # 每次拉取的日期回溯范围

# --- 行为 ---
PUSH_ON_FIRST_RUN = False           # 首次运行是否把历史记录也推出去
STATE_FILE = os.path.join("data", "sync_state.json")
LOG_FILE = os.path.join("data", "sync.log")

# 同一进程内两次登录的最小间隔(秒), 防止触发 CAS 限流
MIN_RELOGIN_GAP_SECONDS = 300
# ================================================================


def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


# ------------------------- 状态 -------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as fh:
                st = json.load(fh)
            st.setdefault("seen", [])
            return st
        except Exception as e:
            log("状态文件损坏, 重建: %s" % e)
    return {"seen": [], "last_run": None, "last_push": None, "initialized": False}


def save_state(st):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


# ------------------------- QQ 机器人 -------------------------

class QQBotClient:
    TOKEN_URL = "https://api.bot.qq.com/app/getAppAccessToken"
    API_BASE = "https://api.bot.qq.com"

    def __init__(self, appid, secret):
        self.appid = appid
        self.secret = secret
        self._token = None
        self._expires_at = 0.0

    def token(self):
        # access_token 有效期内重复获取返回同一个值, 到期前 60 秒才刷新
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        body = json.dumps({"appId": self.appid, "clientSecret": self.secret}).encode("utf-8")
        req = urllib.request.Request(
            self.TOKEN_URL, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data.get("access_token"):
            # 注意: 该接口失败时 HTTP 仍可能是 200, 必须看 body
            raise RuntimeError("获取 access_token 失败: %s" % json.dumps(data, ensure_ascii=False))
        self._token = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in", 7200))
        log("已刷新 access_token, 有效期 %s 秒" % data.get("expires_in"))
        return self._token

    def send_group(self, group_openid, content):
        """Legacy official-group sending is disabled: it cannot meet mandatory @all."""
        raise RuntimeError("官方 QQ 群聊接口不支持 @全体成员，请使用 WebUI 配置免费 OneBot 通道发送")


# ------------------------- 抓取 -------------------------

class Fetcher:
    """会话长期复用; 只在必要时重新登录, 且受最小间隔保护."""

    def __init__(self, user, pwd):
        self.user = user
        self.pwd = pwd
        self.client = None
        self.last_login_ts = 0.0

    def ensure(self):
        if self.client is not None:
            return self.client
        gap = time.time() - self.last_login_ts
        if self.last_login_ts and gap < MIN_RELOGIN_GAP_SECONDS:
            raise RuntimeError(
                "距上次登录仅 %.0f 秒, 为避免触发 CAS 限流, 至少再等 %.0f 秒"
                % (gap, MIN_RELOGIN_GAP_SECONDS - gap))
        self.last_login_ts = time.time()
        log("登录学工系统...")
        c = SswsClient(self.user, self.pwd)
        c.bootstrap()
        self.client = c
        log("登录成功, 会话就绪")
        return c

    def invalidate(self):
        self.client = None

    def fetch(self, start=None, end=None):
        for attempt in (1, 2):
            try:
                return self.ensure().list_records(page_size=50, max_pages=50, start=start, end=end)
            except LoginBlocked:
                self.invalidate()
                raise
            except Exception as e:
                self.invalidate()
                if attempt == 1:
                    log("抓取失败, 将重建会话重试一次: %s" % e)
                    time.sleep(5)
                else:
                    raise
        return []


# ------------------------- 消息格式 -------------------------

def format_record(rec, template=None):
    if template and template.strip():
        mapping = {
            "date": str(rec.get("JCRQ") or "-"),
            "building": str(rec.get("SSLMC") or "-"),
            "room": str(rec.get("FJH") or "-"),
            "level": str(rec.get("DJMC") or "-"),
            "score": str(rec.get("FS")) if rec.get("FS") is not None else "-",
            "type": str(rec.get("JCLXDM_DISPLAY") or "-"),
            "week": str(rec.get("ZC") or "-"),
            "violation": str(rec.get("WGXX") or "无"),
        }
        res = template
        for k, v in mapping.items():
            res = res.replace("{" + k + "}", v)
        return res

    lines = ["【查寝结果】%s" % (rec.get("JCRQ") or "未知日期")]
    lines.append("宿舍：%s %s" % (rec.get("SSLMC") or "-", rec.get("FJH") or "-"))
    lines.append("等级：%s　分数：%s" % (rec.get("DJMC") or "-",
                                        rec.get("FS") if rec.get("FS") is not None else "-"))
    extra = []
    if rec.get("JCLXDM_DISPLAY"):
        extra.append("类型：%s" % rec["JCLXDM_DISPLAY"])
    if rec.get("ZC"):
        extra.append("第 %s 周" % rec["ZC"])
    if extra:
        lines.append("　".join(extra))
    if rec.get("WGXX"):
        lines.append("违规：%s" % rec["WGXX"])
    return "\n".join(lines)


def format_batch(records, template=None):
    if len(records) == 1:
        return format_record(records[0], template)
    return "【查寝结果】新增 %d 条" % len(records) + "\n\n" + \
        "\n\n".join(format_record(r, template) for r in records)


# ------------------------- 调度 -------------------------

def in_active_window(now=None):
    if not ACTIVE_HOURS:
        return True
    now = now or datetime.now()
    cur = now.hour * 60 + now.minute
    for start, end in ACTIVE_HOURS:
        if start[0] * 60 + start[1] <= cur <= end[0] * 60 + end[1]:
            return True
    return False


def run_once(fetcher, state, qq, dry_run=False, baseline=False):
    today = datetime.now().date()
    start = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    rows = fetcher.fetch(start=start, end=end)
    rows.sort(key=lambda r: (r.get("JCRQ") or "", r.get("WID") or ""))
    log("拉取到 %d 条记录 (%s ~ %s)" % (len(rows), start, end))

    seen = set(state["seen"])
    fresh = [r for r in rows if r.get("WID") and r["WID"] not in seen]

    # A preview must not consume pending records or initialize a real baseline.
    if dry_run:
        if baseline:
            raise ValueError("--dry-run 与 --baseline 不能同时使用")
        if not state.get("initialized") and not PUSH_ON_FIRST_RUN:
            log("dry-run 模式: 正式首次运行会把现有 %d 条记为基线, 不推送; 状态未修改" % len(rows))
        elif fresh:
            log("dry-run 模式, 发现 %d 条新记录, 状态未修改; 消息预览:\n%s"
                % (len(fresh), format_batch(fresh)))
        else:
            log("dry-run 模式: 没有新记录, 状态未修改")
        return len(fresh)

    if not state.get("initialized") and not baseline and not PUSH_ON_FIRST_RUN:
        log("首次运行: 把现有 %d 条记为基线, 不推送" % len(rows))
        state["seen"] = sorted(seen | {r["WID"] for r in rows if r.get("WID")})
        state["initialized"] = True
        state["last_run"] = datetime.now().isoformat(timespec="seconds")
        save_state(state)
        return 0

    if not fresh:
        log("没有新记录")
        state["initialized"] = True
        state["last_run"] = datetime.now().isoformat(timespec="seconds")
        save_state(state)
        return 0

    log("发现 %d 条新记录" % len(fresh))
    msg = format_batch(fresh)

    if baseline:
        log("baseline 模式: 不推送, 仅记账")
    else:
        qq.send_group(QQ_GROUP_OPENID, msg)
        log("已推送 %d 条至群 %s" % (len(fresh), QQ_GROUP_OPENID))
        state["last_push"] = datetime.now().isoformat(timespec="seconds")

    state["seen"] = sorted(seen | {r["WID"] for r in fresh})
    state["initialized"] = True
    state["last_run"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)
    return len(fresh)


# ------------------------- 入口 -------------------------

def check_config(need_qq=True):
    missing = []
    if not SDUT_USER:
        missing.append("SDUT_USER")
    if not SDUT_PWD:
        missing.append("SDUT_PWD")
    if need_qq:
        for name, val in (("QQ_APPID", QQ_APPID), ("QQ_SECRET", QQ_SECRET),
                          ("QQ_GROUP_OPENID", QQ_GROUP_OPENID)):
            if not val:
                missing.append(name)
    return missing


def selftest():
    print("=== 配置自检 ===")
    for name in ("SDUT_USER", "SDUT_PWD", "QQ_APPID", "QQ_SECRET", "QQ_GROUP_OPENID"):
        val = globals()[name]
        shown = "已填写" if val else "** 留空, 待填 **"
        print("  %-16s %s" % (name, shown))
    print("  %-16s %s 分钟" % ("轮询间隔", POLL_INTERVAL_MINUTES))
    print("  %-16s %s" % ("活跃时段", ACTIVE_HOURS or "全天"))
    print("  %-16s %s 天" % ("回溯范围", LOOKBACK_DAYS))
    print("  %-16s %s" % ("首次推送历史", PUSH_ON_FIRST_RUN))
    print()

    print("=== 消息格式样例 ===")
    sample = {"JCRQ": "2026-10-15", "SSLMC": "26号公寓", "FJH": "26BH814",
              "DJMC": "优秀", "FS": 90.0, "JCLXDM_DISPLAY": "定期检查",
              "ZC": "7", "WGXX": "地面脏乱(5),物品摆放凌乱(5)"}
    print(format_record(sample))
    print()

    print("=== 活跃时段判定 ===")
    print("  现在 %s -> %s" % (datetime.now().strftime("%H:%M"),
                              "活跃" if in_active_window() else "非活跃(跳过)"))
    print()

    print("=== 状态文件 ===")
    st = load_state()
    print("  路径     : %s" % os.path.abspath(STATE_FILE))
    print("  已记录   : %d 条 WID" % len(st.get("seen", [])))
    print("  已初始化 : %s" % st.get("initialized"))
    print("  上次运行 : %s" % st.get("last_run"))
    print("  上次推送 : %s" % st.get("last_push"))
    print()

    missing = check_config()
    print("待填写: %s" % (", ".join(missing) if missing else "无, 配置齐全"))
    return 0


def main():
    ap = argparse.ArgumentParser(description="查寝结果 -> QQ 机器人定时同步")
    ap.add_argument("--selftest", action="store_true", help="离线自检, 不联网")
    ap.add_argument("--baseline", action="store_true", help="把现有记录记为基线, 不推送")
    ap.add_argument("--once", action="store_true", help="只跑一轮")
    ap.add_argument("--dry-run", action="store_true", help="跑一轮但不真的发 QQ")
    args = ap.parse_args()

    if args.baseline and args.dry_run:
        ap.error("--baseline 与 --dry-run 不能同时使用")

    if args.selftest:
        return selftest()

    need_qq = not (args.baseline or args.dry_run)
    missing = check_config(need_qq=need_qq)
    if missing:
        log("配置不完整, 缺少: %s (可先跑 --selftest 查看)" % ", ".join(missing))
        return 2

    fetcher = Fetcher(SDUT_USER, SDUT_PWD)
    state = load_state()
    qq = QQBotClient(QQ_APPID, QQ_SECRET) if need_qq else None

    if args.baseline or args.once or args.dry_run:
        n = run_once(fetcher, state, qq, dry_run=args.dry_run, baseline=args.baseline)
        log("本轮结束, 新增 %d 条" % n)
        return 0

    log("进入常驻模式, 间隔 %d 分钟, 活跃时段 %s"
        % (POLL_INTERVAL_MINUTES, ACTIVE_HOURS or "全天"))
    while True:
        try:
            if in_active_window():
                n = run_once(fetcher, state, qq)
                log("本轮结束, 新增 %d 条" % n)
            else:
                log("当前不在活跃时段, 跳过")
        except LoginBlocked as e:
            log("认证需要人工处理, 停止自动监测: %s" % e)
            return 3
        except Exception as e:
            log("本轮异常: %s" % e)
        time.sleep(max(60, POLL_INTERVAL_MINUTES * 60))


if __name__ == "__main__":
    sys.exit(main())
