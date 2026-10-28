"""Private, single-account WebUI and scheduler, using only Python's standard library."""
import argparse
from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import secrets
import signal
import threading
import time
from urllib.parse import urlparse
import re

from widget_api import WidgetTokenFile, snapshot as widget_snapshot, restore_electricity, save_electricity, clear_electricity
from sdut_login import LoginBlocked
from sdut_ssws import SswsClient
from sync_qqbot import format_batch
from notifications import GroupNotifier, validate_notification
from reminders import fee_message, money, total_amount, month_date, following_month

HERE = Path(__file__).resolve().parent
CHINA = timezone(timedelta(hours=8))
DEFAULTS = dict(sdut_user="", sdut_pwd="", qq_appid="", qq_secret="",
                qq_group_openid="", poll_minutes=15.0, lookback_days=45,
                push_enabled=False, enabled=False, dorm_push_enabled=True,
                notification_provider="onebot", onebot_url="", onebot_token="", onebot_group_id="",
                at_all_enabled=True, template_dorm="", template_fee="", template_elc="",
                fee_enabled=False, fee_day=1, fee_time="09:00", fee_people=4, fee_amount="20.00",
                elc_campus="西校区", elc_building="26号北楼", elc_floor="8", elc_room="814",
                elc_type="照明插座", elc_enabled=False, elc_minutes=60.0,
                elc_warn_thresholds="50, 20, 10, 5")
ELC_FIELDS = ("elc_campus", "elc_building", "elc_floor", "elc_room", "elc_type")
ELC_CONFIG = (*ELC_FIELDS, "elc_enabled", "elc_minutes")
SECRET_FIELDS = ("sdut_pwd", "qq_secret", "onebot_token")


def timestamp():
    return datetime.now(CHINA).isoformat(timespec="seconds")


def parse_thresholds(value):
    if not value:
        return []
    result = []
    for piece in re.split(r"[,，;\s]+", str(value).strip()):
        if piece:
            try:
                val = float(piece)
                if val > 0:
                    result.append(val)
            except ValueError:
                pass
    return sorted(set(result), reverse=True)


def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation gives credentials owner-only permissions on Linux.
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


class Monitor:
    def __init__(self, data_dir, client_factory=SswsClient, clock=time.time):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.clock = clock
        self.client_factory = client_factory
        self.config = {**DEFAULTS, **read_json(self.data_dir / "webui_config.json", {})}
        self.client = None
        self.last_login = None
        self.busy = False
        self.closed = False
        self.thread = None
        self.capture_busy = False
        self.fee_busy = False
        self.elc_busy = False
        self.elc_result = None
        self.elc_error = ""
        self.elc_client = None
        self.elc_last_request = None
        self.elc_next_due = self.clock() + 5 if self.config["elc_enabled"] else None
        self.elc_state_path = self.data_dir / ("webui_elc_state_" + self.account_key() + ".json")
        elc_state = read_json(self.elc_state_path, {})
        self.elc_alerted_thresholds = set(elc_state.get("alerted", [])) if isinstance(elc_state.get("alerted"), list) else set()
        self.elc_last_kwh = elc_state.get("last_kwh")
        self.fee_journal_path = self.data_dir / "webui_fee_state.json"
        self.fee_journal = read_json(self.fee_journal_path, {})
        self.fee_error = ""
        self.next_due = self.clock() + 5 if self.config["enabled"] else None
        self.last_run = None
        self.last_success = None
        self.last_error = ""
        self.fresh_count = 0
        self.events = deque(maxlen=200)
        self.rows = []
        cached = read_json(self.data_dir / "webui_records.json", {})
        if self.config["sdut_user"] and cached.get("account_key") == self.account_key():
            self.rows = cached.get("rows", [])
            self.last_success = cached.get("checked_at")
        restore_electricity(self)
        self.logger = logging.getLogger("ssws.webui." + str(id(self)))
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        handler = RotatingFileHandler(self.data_dir / "webui.log", maxBytes=1_000_000,
                                      backupCount=3, encoding="utf-8")
        self.logger.addHandler(handler)

    def account_key(self):
        return hashlib.sha256(self.config["sdut_user"].encode()).hexdigest()[:24]

    def save_elc_state(self):
        write_json(self.elc_state_path, {
            "alerted": list(self.elc_alerted_thresholds),
            "last_kwh": self.elc_last_kwh
        })

    def event(self, message, level="info", category="system"):
        with self.lock:
            for field in SECRET_FIELDS:
                if self.config.get(field):
                    message = message.replace(self.config[field], "[已隐藏]")
            if category == "system":
                if any(w in message for w in ("登录", "认证", "会话", "CAS", "密码")):
                    category = "auth"
                elif any(w in message for w in ("查寝", "卫生", "记录")):
                    category = "dorm"
                elif any(w in message for w in ("电量", "电费", "度")):
                    category = "electricity"
                elif any(w in message for w in ("推送", "机器人", "OneBot", "QQ", "网费")):
                    category = "bot"
            item = dict(id=secrets.token_hex(4), time=timestamp(), category=category, level=level, message=message[:600])
            self.events.appendleft(item)
            self.logger.info("[%s][%s] %s", category.upper(), level.upper(), item["message"])

    def log_event(self, category, level, message):
        self.event(message, level=level, category=category)

    def public_config(self):
        with self.lock:
            return {**{k: v for k, v in self.config.items() if k not in SECRET_FIELDS},
                    **{k + "_set": bool(self.config[k]) for k in SECRET_FIELDS}}

    def save_config(self, values):
        if not isinstance(values, dict) or set(values) - set(DEFAULTS):
            raise ValueError("配置字段不正确")
        with self.condition:
            updated = dict(self.config)
            for key, value in values.items():
                if key in ("enabled",):
                    raise ValueError("请使用启动或停止按钮控制监测")
                if key in SECRET_FIELDS and value == "":
                    continue  # Blank means keep existing secret.
                updated[key] = value
            for key in ("sdut_user", "sdut_pwd", "qq_appid", "qq_secret", "qq_group_openid",
                        "onebot_url", "onebot_token", "onebot_group_id", "notification_provider", "fee_time",
                        "template_dorm", "template_fee", "template_elc", "elc_warn_thresholds", *ELC_FIELDS):
                if key not in updated:
                    continue
                if not isinstance(updated[key], str) or len(updated[key]) > 4096:
                    raise ValueError("文本字段类型错误或超长，最多 4096 字符")
                if key not in SECRET_FIELDS and not key.startswith("template_") and key != "elc_warn_thresholds":
                    updated[key] = updated[key].strip()
            if "at_all_enabled" in updated:
                if not isinstance(updated["at_all_enabled"], bool):
                    raise ValueError("是否 @全体成员 必须为布尔值")
            value = updated["poll_minutes"]
            if isinstance(value, bool):
                raise ValueError("刷新间隔必须是数字")
            try:
                updated["poll_minutes"] = float(value)
            except (TypeError, ValueError):
                raise ValueError("刷新间隔必须是数字") from None
            if not math.isfinite(updated["poll_minutes"]) or not 1 <= updated["poll_minutes"] <= 10080:
                raise ValueError("刷新间隔范围为 1 至 10080 分钟，支持小数")
            days = updated["lookback_days"]
            if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650:
                raise ValueError("回溯天数须为 1 至 3650 的整数")
            if not isinstance(updated["push_enabled"], bool):
                raise ValueError("推送开关必须为布尔值")
            if "dorm_push_enabled" in updated:
                if not isinstance(updated["dorm_push_enabled"], bool):
                    raise ValueError("查寝推送开关必须为布尔值")
            if updated["notification_provider"] not in ("onebot", "none", "qq_official"):
                raise ValueError("通知通道不正确")
            if not isinstance(updated["fee_enabled"], bool):
                raise ValueError("网费提醒开关必须为布尔值")
            for key, upper in (("fee_day", 31), ("fee_people", 10000)):
                if isinstance(updated[key], bool) or not isinstance(updated[key], int) or not 1 <= updated[key] <= upper:
                    raise ValueError("每月日期须为 1–31 日，缴费人数须为 1–10000 的整数")
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", updated["fee_time"]):
                raise ValueError("发送时间须为 HH:MM，例如 09:00")
            updated["fee_amount"] = money(updated["fee_amount"])
            if updated["fee_enabled"] and updated["notification_provider"] != "none":
                validate_notification(updated)
            if updated["elc_campus"] not in ("西校区", "东校区") or updated["elc_type"] not in ("照明插座", "空调用电"):
                raise ValueError("电费校区或用电类型不正确")
            if not all(updated[key] for key in ELC_FIELDS):
                raise ValueError("请填写完整的电费查询宿舍信息")
            if not isinstance(updated["elc_enabled"], bool):
                raise ValueError("电量自动查询开关必须为布尔值")
            if isinstance(updated["elc_minutes"], bool):
                raise ValueError("电量查询间隔须为 5–10080 分钟")
            try:
                updated["elc_minutes"] = float(updated["elc_minutes"])
            except (TypeError, ValueError):
                raise ValueError("电量查询间隔须为 5–10080 分钟") from None
            if not math.isfinite(updated["elc_minutes"]) or not 5 <= updated["elc_minutes"] <= 10080:
                raise ValueError("电量查询间隔须为 5–10080 分钟")
            if updated["elc_enabled"]:
                self.validate_ready({**updated, "push_enabled": False})
            elc_schedule_changed = any(updated[k] != self.config[k] for k in ELC_CONFIG)
            elc_changed = any(updated[k] != self.config[k] for k in ELC_FIELDS)
            thresholds_changed = updated.get("elc_warn_thresholds") != self.config.get("elc_warn_thresholds")
            if elc_changed and (self.busy or self.elc_busy):
                raise ValueError("采集执行中，请稍后修改宿舍")
            credentials_changed = any(updated[k] != self.config[k] for k in
                                      ("sdut_user", "sdut_pwd", "qq_appid", "qq_secret", "qq_group_openid",
                                       "onebot_url", "onebot_token", "onebot_group_id", "notification_provider"))
            if credentials_changed and (self.busy or self.capture_busy or self.fee_busy or self.elc_busy):
                raise ValueError("正在执行任务，请结束后再更改账号或机器人配置")
            if updated["enabled"]:
                self.validate_ready(updated)
            account_changed = updated["sdut_user"] != self.config["sdut_user"]
            school_changed = any(updated[k] != self.config[k] for k in ("sdut_user", "sdut_pwd"))
            write_json(self.data_dir / "webui_config.json", updated)
            self.config = updated
            if elc_schedule_changed:
                self.elc_next_due = self.clock() + updated["elc_minutes"] * 60 if updated["elc_enabled"] else None
            if school_changed:
                self.client = None
                self.elc_client = None
                # Keep the login cooldown even when credentials are edited.
            if school_changed or elc_changed:
                self.elc_result = None
                clear_electricity(self)
                self.elc_error = ""
                self.elc_alerted_thresholds.clear()
                self.elc_last_kwh = None
                self.save_elc_state()
            elif thresholds_changed:
                self.elc_alerted_thresholds.clear()
                self.save_elc_state()
            if account_changed:
                self.rows = []
                self.last_success = None
                self.last_run = None
                self.last_error = ""
                self.fresh_count = 0
                self.elc_state_path = self.data_dir / ("webui_elc_state_" + self.account_key() + ".json")
                self.elc_alerted_thresholds.clear()
                self.elc_last_kwh = None
                self.save_elc_state()
            if self.config["enabled"]:
                self.next_due = self.clock() + self.config["poll_minutes"] * 60
            self.condition.notify_all()
            self.event("配置已保存，刷新间隔 %s 分钟" % self.config["poll_minutes"])

    @staticmethod
    def validate_ready(config):
        if not config["sdut_user"] or not config["sdut_pwd"]:
            raise ValueError("请先保存学校账号和密码")
        if config["push_enabled"] and config.get("notification_provider") != "none":
            validate_notification(config)

    def set_enabled(self, enabled):
        with self.condition:
            if enabled:
                self.validate_ready(self.config)
            updated = {**self.config, "enabled": enabled}
            write_json(self.data_dir / "webui_config.json", updated)
            self.config = updated
            self.next_due = self.clock() if enabled else None
            self.condition.notify_all()
            self.event("已启动定时监测" if enabled else "已停止监测；正在进行的请求结束后不再推送")

    def state_path(self):
        return self.data_dir / ("webui_state_" + self.account_key() + ".json")

    def load_state(self):
        path = self.state_path()
        if path.exists():
            state = read_json(path, {})
        else:
            # Only reuse an imported baseline when its account is proven to match.
            exported = read_json(self.data_dir / "ssws_all.json", {})
            if str(exported.get("account", "")) == self.config["sdut_user"]:
                state = read_json(self.data_dir / "sync_state.json", {})
            else:
                state = {}
        if not isinstance(state.get("seen", []), list):
            raise ValueError("增量状态损坏，请检查数据目录")
        return {"seen": [], "initialized": False, **state}

    def request_preview(self):
        with self.condition:
            self.validate_ready({**self.config, "push_enabled": False})
            if self.busy or self.elc_busy:
                raise ValueError("已有采集任务执行中")
            self.busy = True
        threading.Thread(target=self.poll, args=(True,), daemon=True).start()

    def ensure_session(self, force=False):
        with self.lock:
            if not force and self.client is not None:
                return self.client, True
            now = self.clock()
            if self.last_login is not None and now - self.last_login < 300:
                raise RuntimeError("登录冷却中，请在上次登录尝试 5 分钟后再试")
            self.last_login = now
            user = self.config["sdut_user"]
            pwd = self.config["sdut_pwd"]
            self.log_event("auth", "info", "正在通过 CAS 统一身份认证登录学校系统 (账号: %s)" % user)
            client = self.client_factory(user, pwd)
            client.bootstrap()
            self.client = client
            try:
                from sdut_electricity import ElectricityClient
                self.elc_client = ElectricityClient(user, pwd, opener=getattr(client, "op", None))
            except Exception:
                pass
            self.log_event("auth", "success", "学校 CAS 统一身份认证成功，已建立认证会话 (CASTGC)")
            return self.client, False

    def test_login(self, user=None, pwd=None):
        with self.lock:
            user = user or self.config["sdut_user"]
            pwd = pwd or self.config["sdut_pwd"]
        if not user or not pwd:
            raise ValueError("请提供学号和登录密码")
        self.log_event("auth", "info", "正在测试学校统一认证登录 (学号: %s)..." % user)
        try:
            client = self.client_factory(user, pwd)
            roles = client.bootstrap()
            with self.lock:
                if user == self.config["sdut_user"]:
                    self.client = client
                    try:
                        from sdut_electricity import ElectricityClient
                        self.elc_client = ElectricityClient(user, pwd, opener=getattr(client, "op", None))
                    except Exception:
                        pass
            role_desc = roles[0].get("ROLENAME", "学生") if roles and isinstance(roles, list) else "已认证"
            self.log_event("auth", "success", "学校账号 (%s) 测试登录成功，身份: %s" % (user, role_desc))
            return {"ok": True, "message": "账号 %s 登录成功！身份认证正常（角色：%s）。" % (user, role_desc)}
        except Exception as error:
            err_msg = str(error)
            for field in SECRET_FIELDS:
                if pwd:
                    err_msg = err_msg.replace(pwd, "[已隐藏]")
            self.log_event("auth", "error", "学校账号 (%s) 测试登录失败: %s" % (user, err_msg))
            raise ValueError("登录失败: %s" % err_msg) from None

    def format_electricity_message(self, elc_result, threshold):
        cfg = self.config
        custom_tpl = (cfg.get("template_elc") or "").strip()
        kwh_str = str(elc_result.get("remaining_kwh") or "")
        cny_str = str(elc_result.get("balance_cny") or "")
        cny_text = ("账户余额：%s 元" % cny_str) if cny_str and cny_str != "None" else ""
        campus = str(elc_result.get("campus") or cfg.get("elc_campus", ""))
        building = str(elc_result.get("building") or cfg.get("elc_building", ""))
        room = str(elc_result.get("room") or cfg.get("elc_room", ""))
        elc_type = str(elc_result.get("electricity_type") or cfg.get("elc_type", ""))
        location = str(elc_result.get("page_location") or ("%s %s %s" % (campus, building, room)))
        checked_at = str(elc_result.get("checked_at") or timestamp())

        at_prefix = "@全体成员\n" if cfg.get("at_all_enabled") and cfg.get("notification_provider") == "onebot" else ""

        if custom_tpl:
            rendered = custom_tpl \
                .replace("{balance}", kwh_str) \
                .replace("{threshold}", str(threshold)) \
                .replace("{campus}", campus) \
                .replace("{building}", building) \
                .replace("{room}", room) \
                .replace("{type}", elc_type) \
                .replace("{location}", location) \
                .replace("{balance_cny}", cny_str) \
                .replace("{balance_cny_text}", cny_text) \
                .replace("{checked_at}", checked_at)
            return at_prefix + rendered
        else:
            cny_part = ("\n账户余额：%s 元" % cny_str) if cny_str and cny_str != "None" else ""
            return ("%s【宿舍低电量预警】\n"
                    "宿舍位置：%s\n"
                    "用电类型：%s\n"
                    "剩余电量：%s 度（已低于 %s 度预警线）%s\n\n"
                    "请宿舍成员及时充值电费，以防断电影响正常用电！" %
                    (at_prefix, location, elc_type, kwh_str, threshold, cny_part))

    def check_electricity_alerts(self, elc_result, deliver=True):
        if not elc_result or not elc_result.get("remaining_kwh"):
            return
        try:
            kwh = float(elc_result["remaining_kwh"])
        except (ValueError, TypeError):
            return

        if self.elc_last_kwh is not None and kwh > self.elc_last_kwh + 0.5:
            self.elc_alerted_thresholds.clear()
            self.log_event("electricity", "info",
                           "检测到电费充值（电量由 %.2f 度增加至 %.2f 度），已重置多级预警状态" %
                           (self.elc_last_kwh, kwh))

        for t in list(self.elc_alerted_thresholds):
            if kwh > t:
                self.elc_alerted_thresholds.remove(t)

        self.elc_last_kwh = kwh
        self.save_elc_state()

        thresholds = parse_thresholds(self.config.get("elc_warn_thresholds", "50, 20, 10, 5"))
        newly_triggered = [t for t in thresholds if kwh <= t and t not in self.elc_alerted_thresholds]
        if not newly_triggered:
            return

        for t in newly_triggered:
            self.elc_alerted_thresholds.add(t)
        self.save_elc_state()

        active_threshold = min(newly_triggered)

        if not deliver or not self.config.get("push_enabled") or self.config.get("notification_provider") == "none":
            self.log_event("electricity", "warn",
                           "电量预警触发：当前 %.2f 度低于预警线 %s 度（未启用群推送，仅本地记录）" %
                           (kwh, active_threshold))
            return

        msg = self.format_electricity_message(elc_result, active_threshold)
        try:
            notifier = GroupNotifier(self.config)
            notifier.send(msg)
            at_text = " @全体成员" if self.config.get("at_all_enabled") and self.config.get("notification_provider") == "onebot" else ""
            self.log_event("bot", "success",
                           "已%s 发送电量低电预警通知：剩余 %.2f 度（低于阈值 %s 度）" %
                           (at_text, kwh, active_threshold))
        except Exception as error:
            self.log_event("bot", "error", "电量预警群消息发送失败: %s" % error)

    def poll(self, preview=False):
        with self.lock:
            config = dict(self.config)
            self.last_run = timestamp()
        try:
            # 1. 会话复用与 CAS 认证
            client, reused = self.ensure_session(force=False)
            if reused:
                self.log_event("auth", "info", "复用现有学校认证会话 (CAS SSO 免登)")

            # 2. 拉取查寝记录
            self.log_event("dorm", "info", "正在拉取宿舍查寝记录...")
            today = datetime.now(CHINA).date()
            try:
                rows = client.list_records(page_size=50, max_pages=50,
                                           start=(today - timedelta(days=config["lookback_days"])).isoformat(),
                                           end=today.isoformat())
            except Exception as query_err:
                self.log_event("auth", "warn", "查寝接口请求异常 (%s)，尝试重新登录认证..." % query_err)
                client, _ = self.ensure_session(force=True)
                rows = client.list_records(page_size=50, max_pages=50,
                                           start=(today - timedelta(days=config["lookback_days"])).isoformat(),
                                           end=today.isoformat())

            # Deduplicate repeated rows within one API response.
            rows = list({r["WID"]: r for r in rows if r.get("WID")}.values())
            rows.sort(key=lambda row: (str(row.get("JCRQ", "")), str(row["WID"])), reverse=True)
            with self.lock:
                state = self.load_state()
                seen = set(state["seen"])
                fresh = [row for row in rows if row["WID"] not in seen]
                self.rows = rows
                self.fresh_count = len(fresh)
                checked = timestamp()
                write_json(self.data_dir / "webui_records.json",
                           dict(account_key=self.account_key(), checked_at=checked, rows=rows))
                deliver = not preview and self.config["enabled"]
                dorm_push = config.get("push_enabled") and config.get("dorm_push_enabled", True)
                if deliver and not state["initialized"]:
                    state.update(seen=sorted(seen | {row["WID"] for row in rows}), initialized=True)
                    write_json(self.state_path(), state)
                    self.fresh_count = 0
                    self.log_event("dorm", "info", "首次运行已建立 %d 条基线，不推送历史记录" % len(rows))
                elif deliver and fresh and dorm_push and self.config.get("push_enabled") and self.config.get("dorm_push_enabled", True):
                    notifier = GroupNotifier(config)
                    for offset in range(0, len(fresh), 5):
                        batch = fresh[offset:offset + 5]
                        notifier.send(format_batch(batch, template=config.get("template_dorm")))
                        seen.update(row["WID"] for row in batch)
                        state.update(seen=sorted(seen), initialized=True, last_push=timestamp())
                        write_json(self.state_path(), state)
                    self.fresh_count = 0
                    at_text = " @全体成员" if config.get("at_all_enabled") and config.get("notification_provider") == "onebot" else ""
                    self.log_event("bot", "success", "已%s 推送 %d 条新记录至目标群" % (at_text, len(fresh)))
                elif deliver and fresh and not dorm_push:
                    self.log_event("dorm", "info", "检测到 %d 条新查寝记录（查寝推送已关闭，保留待推送）" % len(fresh))
                self.last_success = checked
                self.last_error = ""
                self.log_event("dorm", "success", "%s完成：%d 条记录，%d 条未读" %
                               ("手动采集（不推送）" if preview else "自动采集", len(rows), self.fresh_count))

            # 3. 合并查询宿舍电量（共用同一个 CAS 会话）
            if config.get("elc_enabled"):
                self.log_event("electricity", "info", "合并采集宿舍电量 (复用 SSO 会话)...")
                try:
                    from sdut_electricity import ElectricityClient
                    kwargs = {}
                    if hasattr(self.client, "op") and self.client.op is not None:
                        kwargs["opener"] = self.client.op
                    if self.elc_client is None:
                        self.elc_client = ElectricityClient(config["sdut_user"], config["sdut_pwd"], **kwargs)
                    elif "opener" in kwargs and getattr(self.elc_client, "opener", None) != kwargs["opener"]:
                        self.elc_client.opener = kwargs["opener"]

                    elc_result = self.elc_client.query(*(config[key] for key in ELC_FIELDS)).to_dict()
                    with self.lock:
                        self.elc_result = elc_result
                        save_electricity(self, elc_result)
                        self.elc_error = ""
                    kwh = elc_result.get("remaining_kwh")
                    cny = elc_result.get("balance_cny")
                    cny_desc = ("，余额 %s 元" % cny) if cny is not None else ""
                    self.log_event("electricity", "success", "宿舍电量查询成功：剩余 %s 度%s" % (kwh, cny_desc))
                    self.check_electricity_alerts(elc_result, deliver=deliver)
                except Exception as elc_err:
                    elc_msg = str(elc_err)
                    for key in SECRET_FIELDS:
                        if config[key]:
                            elc_msg = elc_msg.replace(config[key], "[已隐藏]")
                    with self.lock:
                        self.elc_error = elc_msg[:600]
                    self.log_event("electricity", "error", "宿舍电量采集失败: %s" % elc_msg)
        except LoginBlocked as error:
            self.client = None
            self.elc_client = None
            with self.condition:
                self.config["enabled"] = False
                write_json(self.data_dir / "webui_config.json", self.config)
                self.next_due = None
            self.record_error("%s；监测已停止，请处理后手动启动" % error)
        except Exception as error:
            # Rebuild a failed business session next time, subject to the login cooldown.
            self.client = None
            self.elc_client = None
            self.record_error(str(error))
        finally:
            with self.condition:
                self.busy = False
                self.next_due = (self.clock() + self.config["poll_minutes"] * 60
                                 if self.config["enabled"] else None)
                self.condition.notify_all()

    def record_error(self, message):
        with self.lock:
            for field in SECRET_FIELDS:
                if self.config[field]:
                    message = message.replace(self.config[field], "[已隐藏]")
            self.last_error = message[:500]
            self.event(self.last_error, "error")

    def fee_key(self, now):
        provider = self.config.get("notification_provider", "onebot")
        target = self.config.get("qq_group_openid") if provider == "qq_official" else self.config.get("onebot_group_id", "")
        return now.strftime("%Y-%m") + ":" + str(target)

    def fee_schedule(self):
        """Return current-month eligible send time; completed/uncertain attempts are not retried."""
        if not self.config["fee_enabled"]:
            return None
        now = datetime.fromtimestamp(self.clock(), CHINA)
        receipt = self.fee_journal.get(self.fee_key(now))
        if receipt:
            return self.clock() if receipt.get("status") == "queued" else None
        return month_date(now, self.config["fee_day"], self.config["fee_time"]).timestamp()

    def fee_status(self):
        now = datetime.fromtimestamp(self.clock(), CHINA)
        receipt = self.fee_journal.get(self.fee_key(now), {})
        due = self.fee_schedule()
        next_at = None
        if self.config["fee_enabled"]:
            if due is not None:
                next_at = datetime.fromtimestamp(max(due, self.clock()), CHINA).isoformat(timespec="seconds")
            elif receipt.get("status") == "sent":
                next_at = month_date(following_month(now), self.config["fee_day"], self.config["fee_time"]).isoformat(timespec="seconds")
        prefix = "@全体成员\n" if self.config.get("at_all_enabled") and self.config.get("notification_provider") == "onebot" else ""
        return dict(busy=self.fee_busy, total=total_amount(self.config), next_at=next_at,
                    month=now.strftime("%Y-%m"), status=receipt.get("status", "pending"),
                    last_sent=receipt.get("sent_at"), error=self.fee_error or receipt.get("error", ""),
                    preview=prefix + fee_message(self.config, now, template=self.config.get("template_fee")))

    def send_fee(self):
        with self.condition:
            due = self.fee_schedule()
            if self.fee_busy or due is None or due > self.clock():
                return
            config = dict(self.config)
            now = datetime.fromtimestamp(self.clock(), CHINA)
            key = self.fee_key(now)
            # Persist the attempt before networking. Restart never repeats an uncertain send.
            self.fee_journal[key] = dict(status="sending", attempted_at=now.isoformat(timespec="seconds"))
            write_json(self.fee_journal_path, self.fee_journal)
            self.fee_busy = True
            try:
                result = GroupNotifier(config).send(fee_message(config, now, template=config.get("template_fee")))
                self.fee_journal[key].update(status="sent", sent_at=timestamp(), message_id=result.get("message_id", 0))
                self.fee_error = ""
                at_text = " @全体成员" if config.get("at_all_enabled") else ""
                self.event("已%s 发送本月网费通知：%d 人，每人 %s 元，合计 %s 元" % (
                    at_text, config["fee_people"], config["fee_amount"], total_amount(config)))
            except Exception as error:
                message = str(error)
                for field in SECRET_FIELDS:
                    if config[field]:
                        message = message.replace(config[field], "[已隐藏]")
                self.fee_error = message[:500]
                self.fee_journal[key].update(status="failed", error=self.fee_error)
                self.event("网费通知发送失败或结果待确认；为避免重复，未自动重发：" + self.fee_error, "error")
            finally:
                self.fee_busy = False
                write_json(self.fee_journal_path, self.fee_journal)
                self.condition.notify_all()

    def retry_fee(self):
        with self.condition:
            if not self.config["fee_enabled"]:
                raise ValueError("请先开启网费提醒")
            now = datetime.fromtimestamp(self.clock(), CHINA)
            key = self.fee_key(now)
            receipt = self.fee_journal.get(key, {})
            if self.fee_busy or receipt.get("status") not in ("failed", "sending"):
                raise ValueError("本月没有待确认的失败通知，已成功发送的月份不能重发")
            self.fee_journal[key] = dict(status="queued")
            write_json(self.fee_journal_path, self.fee_journal)
            self.condition.notify_all()
            self.event("用户已确认群内未收到，安排重试本月网费通知")

    def check_onebot(self):
        with self.lock:
            config = dict(self.config)
        provider = config.get("notification_provider", "onebot")
        try:
            if provider == "qq_official":
                result = GroupNotifier(config).check_connection()
                self.event("QQ 官方机器人凭据验证通过（成功获取 access_token）")
                return result
            elif provider == "none":
                return {"status": "ok", "provider": "none"}
            else:
                if config.get("at_all_enabled", True):
                    result = GroupNotifier(config).check_at_all()
                    self.event("OneBot 连接及 @全体成员 权限检查通过（未发送消息）")
                else:
                    result = GroupNotifier(config).check_connection()
                    self.event("OneBot 基础连接检查通过（未开启 @全体成员，未发送消息）")
                return result
        except Exception as error:
            self.record_error(str(error))
            raise ValueError(self.last_error) from None

    def test_send_message(self, test_text=None):
        with self.lock:
            config = dict(self.config)
        provider = config.get("notification_provider", "onebot")
        if not test_text:
            if provider == "qq_official":
                test_text = "【SDUT 宿舍监控】这是一条测试消息，QQ 官方机器人与群通知配置正常！"
            elif provider == "none":
                raise ValueError("当前通知通道为『关闭外部推送』，无法发送测试群消息")
            else:
                at_note = "（已开启 @全体成员）" if config.get("at_all_enabled") else "（未开启 @全体成员）"
                test_text = "【SDUT 宿舍监控】这是一条测试消息，OneBot 机器人与群通知配置正常！%s" % at_note
        try:
            result = GroupNotifier(config).send(test_text)
        except Exception as error:
            self.record_error(str(error))
            raise ValueError(self.last_error) from None
        target = "目标 QQ 群" if provider != "none" else "本地"
        self.event("已向%s发送测试消息" % target)
        return result

    def capture_group(self):
        with self.lock:
            if self.capture_busy:
                raise ValueError("群标识采集已经在等待消息")
            if not self.config["qq_appid"] or not self.config["qq_secret"]:
                raise ValueError("请先保存 AppID 和 AppSecret")
            config = dict(self.config)
            self.capture_busy = True
        def task():
            try:
                from get_group_openid import capture
                self.event("正在连接 QQ 网关，请在 4 分钟内到目标群 @ 机器人")
                result = capture(config["qq_appid"], config["qq_secret"], 240, quiet=True)
                if not result or not result.get("group_openid"):
                    raise RuntimeError("等待群 @ 消息超时，请确认机器人已加入群并启用群事件")
                with self.lock:
                    updated = {**self.config, "qq_group_openid": result["group_openid"]}
                    write_json(self.data_dir / "webui_config.json", updated)
                    self.config = updated
                self.event("已获取并保存目标群标识，请核对后启用推送")
            except Exception as error:
                self.record_error(str(error))
            finally:
                with self.lock:
                    self.capture_busy = False
        threading.Thread(target=task, daemon=True).start()

    def request_electricity(self, values, *, query=True):
        """Save the simple room form and run one read-only query in the background."""
        if not isinstance(values, dict) or set(values) != set(ELC_CONFIG):
            raise ValueError("电量查询字段不完整")
        with self.condition:
            self.validate_ready({**self.config, "push_enabled": False})
            if self.busy or self.elc_busy:
                raise ValueError("已有采集任务执行中，请稍后查询")
            if query and self.elc_last_request is not None and self.clock() - self.elc_last_request < 300:
                raise ValueError("请在上次电量查询 5 分钟后再试；学校数据每小时更新")
            self.save_config(values)
            if not query:
                return
            config = dict(self.config)
            self.elc_busy = True
            self.elc_error = ""
            self.elc_result = None
            self.elc_last_request = self.clock()
        def task():
            try:
                from sdut_electricity import ElectricityClient
                kwargs = {}
                if self.client is not None and hasattr(self.client, "op") and self.client.op is not None:
                    kwargs["opener"] = self.client.op
                if self.elc_client is None:
                    self.elc_client = ElectricityClient(config["sdut_user"], config["sdut_pwd"], **kwargs)
                elif "opener" in kwargs and getattr(self.elc_client, "opener", None) != kwargs["opener"]:
                    self.elc_client.opener = kwargs["opener"]

                result = self.elc_client.query(*(config[key] for key in ELC_FIELDS)).to_dict()
                with self.lock:
                    self.elc_result = result
                    save_electricity(self, result)
                    self.elc_error = ""
                reused_note = " (复用 SSO 会话)" if "opener" in kwargs else ""
                self.log_event("electricity", "success", "宿舍电量查询成功%s：%s，剩余 %s 度" %
                               (reused_note, result.get("page_location", config["elc_room"]), result.get("remaining_kwh", "—")))
                self.check_electricity_alerts(result, deliver=False)
            except Exception as error:
                message = str(error)
                for key in SECRET_FIELDS:
                    if config[key]:
                        message = message.replace(config[key], "[已隐藏]")
                with self.lock:
                    self.elc_error = message[:600]
                    if isinstance(error, LoginBlocked):
                        self.config["elc_enabled"] = False
                        write_json(self.data_dir / "webui_config.json", self.config)
                self.log_event("electricity", "error", "电量查询失败：" + message)
            finally:
                with self.condition:
                    self.elc_busy = False
                    self.elc_next_due = (self.clock() + self.config["elc_minutes"] * 60
                                         if self.config["elc_enabled"] else None)
                    self.condition.notify_all()
        threading.Thread(target=task, daemon=True).start()

    def snapshot(self):
        with self.lock:
            return dict(config=self.public_config(), busy=self.busy, fee=self.fee_status(),
                        electricity=dict(busy=self.elc_busy, result=self.elc_result, error=self.elc_error,
                                         next_due=self.elc_next_due,
                                         alerted_thresholds=list(self.elc_alerted_thresholds),
                                         last_kwh=self.elc_last_kwh),
                        capture_busy=self.capture_busy, next_due=self.next_due,
                        last_run=self.last_run, last_success=self.last_success,
                        last_error=self.last_error, fresh_count=self.fresh_count,
                        record_count=len(self.rows), records=self.rows[:200],
                        events=list(self.events),
                        logs=list(self.events))

    def start_worker(self):
        def worker():
            while True:
                with self.condition:
                    if self.closed:
                        return
                    if (self.config["elc_enabled"] and not self.busy and not self.elc_busy
                            and self.elc_next_due is not None and self.elc_next_due <= self.clock()):
                        try:
                            self.request_electricity({key: self.config[key] for key in ELC_CONFIG})
                        except ValueError as error:
                            self.elc_next_due = self.clock() + 300
                            self.event("自动电量查询暂缓：" + str(error), "error")
                    fee_due = self.fee_schedule()
                    if fee_due is not None and fee_due <= self.clock():
                        self.send_fee()
                        continue
                    if not self.config["enabled"] or self.busy or self.elc_busy or self.next_due is None:
                        self.condition.wait(1)
                        continue
                    delay = self.next_due - self.clock()
                    if delay > 0:
                        self.condition.wait(min(delay, 30))
                        continue
                    self.busy = True
                self.poll()
        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=40)
        for handler in list(self.logger.handlers):
            handler.close()
            self.logger.removeHandler(handler)


class WebApp:
    def __init__(self, monitor):
        self.monitor = monitor
        self.widget_tokens = WidgetTokenFile(monitor.data_dir / "webui_widget_token.json")
        self.lock = threading.RLock()
        self.admin_path = monitor.data_dir / "webui_admin.json"
        self.admin = read_json(self.admin_path, None)
        self.sessions = {}
        self.failures = deque(maxlen=100)

    def authenticate(self, password, setup=False):
        if not isinstance(password, str) or not 10 <= len(password) <= 256:
            raise ValueError("管理密码须为 10 至 256 个字符")
        with self.lock:
            now = time.time()
            self.failures = deque((t for t in self.failures if now - t < 300), maxlen=100)
            if len(self.failures) >= 10:
                raise ValueError("登录尝试过多，请 5 分钟后再试")
            if setup:
                if self.admin:
                    raise ValueError("管理密码已经设置，请登录")
                salt = secrets.token_bytes(16)
                hashed = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()
                admin = dict(salt=salt.hex(), password_hash=hashed)
                write_json(self.admin_path, admin)
                self.admin = admin
            else:
                if not self.admin:
                    raise ValueError("请先设置管理密码")
                hashed = hashlib.scrypt(password.encode(), salt=bytes.fromhex(self.admin["salt"]),
                                        n=16384, r=8, p=1).hex()
                if not hmac.compare_digest(hashed, self.admin["password_hash"]):
                    self.failures.append(now)
                    raise ValueError("管理密码错误")
            self.sessions = {k: v for k, v in self.sessions.items() if v["expires"] > now}
            token = secrets.token_urlsafe(32)
            session = dict(csrf=secrets.token_urlsafe(32), expires=now + 12 * 3600)
            self.sessions[token] = session
            return token, session

    def session(self, cookie_header):
        try:
            cookies = SimpleCookie(cookie_header or "")
            token = cookies["ssws_session"].value
        except (KeyError, ValueError):
            return None
        with self.lock:
            session = self.sessions.get(token)
            return session if session and session["expires"] > time.time() else None


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SSWS-WebUI"

        def valid_host(self):
            hostname = urlparse("//" + self.headers.get("Host", "")).hostname
            allowed = {name.strip().lower() for name in os.environ.get(
                "WEBUI_ALLOWED_HOSTS", "127.0.0.1,localhost,::1").split(",")}
            return "*" in allowed or (hostname is not None and hostname.lower() in allowed)

        def log_message(self, *args):
            pass  # Never log request bodies or credential query strings.

        def send(self, status, value, content_type="application/json; charset=utf-8", cookie=None):
            body = (json.dumps(value, ensure_ascii=False).encode("utf-8")
                    if content_type.startswith("application/json") else value)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.valid_host():
                self.send(421, {"error": "访问主机未获允许，请配置 WEBUI_ALLOWED_HOSTS"})
                return
            path = urlparse(self.path).path
            if path in ("/", "/app.js", "/style.css"):
                name, mime = {"/": ("index.html", "text/html; charset=utf-8"),
                              "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                              "/style.css": ("style.css", "text/css; charset=utf-8")}[path]
                self.send(200, (HERE / "web" / name).read_bytes(), mime)
            elif path == "/healthz":
                self.send(200, {"status": "ok", "worker_alive": bool(app.monitor.thread and app.monitor.thread.is_alive())})
            elif path == "/api/widget/v1/dorm":
                # Authorize and project against the same account/config snapshot.
                with app.monitor.lock:
                    authorized = app.widget_tokens.authenticate(self.headers.get("Authorization", ""), app.monitor.account_key())
                    result = widget_snapshot(app.monitor) if authorized and not urlparse(self.path).query else None
                if not authorized:
                    self.send(401, {"error": "小组件凭证无效或已撤销"})
                elif urlparse(self.path).query:
                    self.send(400, {"error": "此接口不接受查询参数"})
                else:
                    self.send(200, result)
            elif path == "/api/widget/token":
                if not app.session(self.headers.get("Cookie")):
                    self.send(401, {"error": "请先登录"})
                else:
                    self.send(200, app.widget_tokens.status(app.monitor.account_key()))
            elif path == "/api/session":
                session = app.session(self.headers.get("Cookie"))
                self.send(200, dict(setup_required=app.admin is None, authenticated=bool(session),
                                    csrf=session["csrf"] if session else None))
            elif path == "/api/status":
                if not app.session(self.headers.get("Cookie")):
                    self.send(401, {"error": "请先登录"})
                else:
                    self.send(200, app.monitor.snapshot())
            else:
                self.send(404, {"error": "页面不存在"})

        def do_POST(self):
            try:
                if not self.valid_host():
                    self.send(421, {"error": "访问主机未获允许"})
                    return
                # Require a browser's same-origin request, including login/setup.
                origin = urlparse(self.headers.get("Origin", ""))
                if origin.scheme not in ("http", "https") or origin.netloc != self.headers.get("Host"):
                    self.send(403, {"error": "请求来源不匹配"})
                    return
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("请求须使用 JSON")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("请求体长度不正确")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("请求须为对象")
                path = urlparse(self.path).path
                if path in ("/api/setup", "/api/login"):
                    token, session = app.authenticate(payload.get("password"), setup=path == "/api/setup")
                    self.send(200, {"csrf": session["csrf"]}, cookie=
                              "ssws_session=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200" % token)
                    return
                session = app.session(self.headers.get("Cookie"))
                if not session:
                    self.send(401, {"error": "登录已过期，请重新登录"})
                    return
                if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf"]):
                    self.send(403, {"error": "请求校验失败，请刷新页面"})
                    return
                if path == "/api/widget/token":
                    with app.monitor.lock:
                        if payload.get("action") == "rotate":
                            if not app.monitor.config.get("sdut_user"):
                                raise ValueError("请先保存学校账号，再生成小组件 Token")
                            return self.send(200, app.widget_tokens.rotate(app.monitor.account_key()))
                        if payload.get("action") == "revoke":
                            return self.send(200, app.widget_tokens.revoke())
                    return self.send(400, {"error": "action 只支持 rotate 或 revoke"})
                elif path == "/api/config":
                    app.monitor.save_config(payload)
                elif path == "/api/start":
                    app.monitor.set_enabled(True)
                elif path == "/api/stop":
                    app.monitor.set_enabled(False)
                elif path == "/api/preview":
                    app.monitor.request_preview()
                elif path == "/api/electricity":
                    app.monitor.request_electricity(payload)
                elif path == "/api/electricity-config":
                    app.monitor.request_electricity(payload, query=False)
                elif path == "/api/capture-group":
                    app.monitor.capture_group()
                elif path in ("/api/onebot-check", "/api/bot-check"):
                    result = app.monitor.check_onebot()
                    self.send(200, {"ok": True, "permissions": result})
                    return
                elif path == "/api/bot-test-send":
                    result = app.monitor.test_send_message(payload.get("message") if isinstance(payload, dict) else None)
                    self.send(200, {"ok": True, "result": result})
                    return
                elif path == "/api/fee-retry":
                    app.monitor.retry_fee()
                elif path == "/api/test-login":
                    result = app.monitor.test_login(payload.get("sdut_user"), payload.get("sdut_pwd"))
                    self.send(200, result)
                    return
                elif path == "/api/logout":
                    with app.lock:
                        for token, value in list(app.sessions.items()):
                            if value is session:
                                del app.sessions[token]
                    self.send(200, {"ok": True}, cookie="ssws_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
                    return
                else:
                    self.send(404, {"error": "接口不存在"})
                    return
                self.send(200, {"ok": True})
            except (ValueError, TypeError, UnicodeError) as error:
                self.send(400, {"error": str(error)[:300]})
            except Exception:
                self.send(500, {"error": "操作失败，请检查数据目录权限及服务日志"})
    return Handler


def main():
    parser = argparse.ArgumentParser(description="查寝监测 WebUI")
    parser.add_argument("--host", default=os.environ.get("WEBUI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("WEBUI_PORT", "8787")))
    parser.add_argument("--data-dir", default=os.environ.get("SSWS_DATA_DIR", str(HERE / "data")))
    args = parser.parse_args()
    monitor = Monitor(args.data_dir)
    server = ThreadingHTTPServer((args.host, args.port), handler_for(WebApp(monitor)))
    server.daemon_threads = True
    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    monitor.start_worker()
    print("WebUI: http://%s:%s" % (args.host, args.port), flush=True)
    try:
        server.serve_forever()
    finally:
        monitor.close()
        server.server_close()


if __name__ == "__main__":
    main()
