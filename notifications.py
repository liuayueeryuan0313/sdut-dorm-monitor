"""Group notifications with optional OneBot 11 HTTP transport and optional @all."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse


def validate_notification(config):
    provider = config.get("notification_provider", "onebot")
    if provider == "none":
        return
    if provider == "onebot":
        url = urlparse(config.get("onebot_url", ""))
        if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
                or url.query or url.fragment):
            raise ValueError("请填写有效的 OneBot HTTP 地址（不含账号、查询参数或片段）")
        group = str(config.get("onebot_group_id", "")).strip()
        if not group.isascii() or not group.isdigit() or not 1 <= int(group) < 2**63:
            raise ValueError("OneBot 目标群须填写普通 QQ 群号")
    elif provider == "qq_official":
        if not config.get("qq_appid") or not config.get("qq_secret"):
            raise ValueError("请填写 QQ 官方机器人的 AppID 和 AppSecret")
        if not config.get("qq_group_openid"):
            raise ValueError("请填写 QQ 官方机器人的目标群 group_openid（可通过『获取群标识』获取）")
    else:
        raise ValueError("不支持的通知通道：%s（可选 OneBot、QQ 官方或关闭外部推送）" % provider)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class GroupNotifier:
    def __init__(self, config):
        validate_notification(config)
        self.config = config
        self.provider = config.get("notification_provider", "onebot")
        self.base = config.get("onebot_url", "").rstrip("/")
        self.token = config.get("onebot_token", "")
        group_raw = str(config.get("onebot_group_id", "0")).strip()
        self.group = int(group_raw) if group_raw.isdigit() else 0
        self.at_all_enabled = bool(config.get("at_all_enabled", False))
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, action, payload=None):
        if self.provider == "none":
            return {"status": "ok", "message_id": 0}
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = json.dumps(payload or {}, ensure_ascii=False).encode()
        request = urllib.request.Request(self.base + "/" + action,
                                         data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError("OneBot %s 请求失败 HTTP %s" % (action, error.code)) from None
        except Exception as error:
            raise RuntimeError("OneBot %s 连接失败：%s" % (action, error)) from None

        if not isinstance(result, dict) or result.get("status") not in ("ok", "async") or result.get("retcode", 0) != 0:
            code = result.get("retcode") if isinstance(result, dict) else "invalid"
            msg = result.get("msg") or result.get("message") if isinstance(result, dict) else ""
            extra = " (%s)" % msg if msg else ""
            raise RuntimeError("OneBot %s 失败，retcode=%s%s" % (action, code, extra))
        return result.get("data") if result.get("data") is not None else {}

    def check_connection(self):
        if self.provider == "none":
            return {"status": "ok", "provider": "none"}
        if self.provider == "qq_official":
            from sync_qqbot import QQBotClient
            client = QQBotClient(self.config["qq_appid"], self.config["qq_secret"])
            token = client.token()
            return {"status": "ok", "provider": "qq_official", "token_ready": bool(token)}
        if self.at_all_enabled:
            return self.check_at_all()
        # Non-at-all basic connection check
        try:
            res = self.call("get_status")
        except Exception:
            try:
                res = self.call("get_version_info")
            except Exception:
                res = {"status": "ok"}
        return {"status": "ok", "at_all": False, "data": res}

    def check_at_all(self):
        if self.provider == "qq_official":
            raise RuntimeError("QQ 官方机器人接口暂不支持 @全体成员，请取消勾选或改用 OneBot")
        result = self.call("get_group_at_all_remain", {"group_id": self.group})
        if not isinstance(result, dict) or result.get("can_at_all") is not True:
            raise RuntimeError("机器人当前无法 @全体成员，请检查群管理员权限与 @全体额度（或在群通知设置中取消勾选『@全体成员』）")
        for key in ("remain_at_all_count_for_group", "remain_at_all_count_for_uin"):
            if key in result and (not isinstance(result[key], int) or result[key] <= 0):
                raise RuntimeError("@全体成员剩余额度不足，通知未发送")
        return result

    def send(self, content):
        if self.provider == "none":
            return {"status": "ok", "message_id": 0}

        if self.provider == "qq_official":
            from sync_qqbot import QQBotClient
            client = QQBotClient(self.config["qq_appid"], self.config["qq_secret"])
            return client.send_group(self.config["qq_group_openid"], content)

        message_segments = []
        if self.at_all_enabled:
            self.check_at_all()
            message_segments.append({"type": "at", "data": {"qq": "all"}})
            message_segments.append({"type": "text", "data": {"text": "\n" + content}})
        else:
            message_segments.append({"type": "text", "data": {"text": content}})

        result = self.call("send_group_msg", {
            "group_id": self.group,
            "message": message_segments,
        })
        if not isinstance(result, dict) or result.get("message_id") is None:
            raise RuntimeError("OneBot 未返回消息 ID，发送结果待确认")
        return result
