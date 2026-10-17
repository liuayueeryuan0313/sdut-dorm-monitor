"""Group notifications with mandatory, native @all via OneBot 11 HTTP."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse


def validate_notification(config):
    if config["notification_provider"] != "onebot":
        raise ValueError("官方 QQ 群聊接口不支持 @全体成员，请配置免费的 OneBot 通道")
    url = urlparse(config["onebot_url"])
    if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
            or url.query or url.fragment):
        raise ValueError("请填写有效的 OneBot HTTP 地址（不含账号、查询参数或片段）")
    group = config["onebot_group_id"]
    if not group.isascii() or not group.isdigit() or not 1 <= int(group) < 2**63:
        raise ValueError("OneBot 目标群须填写普通 QQ 群号")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class GroupNotifier:
    def __init__(self, config):
        validate_notification(config)
        self.base = config["onebot_url"].rstrip("/")
        self.token = config["onebot_token"]
        self.group = int(config["onebot_group_id"])
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, action, payload):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(self.base + "/" + action,
                                         data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers)
        try:
            with self.opener.open(request, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError("OneBot %s 请求失败 HTTP %s" % (action, error.code)) from None
        if not isinstance(result, dict) or result.get("status") != "ok" or result.get("retcode") != 0:
            code = result.get("retcode") if isinstance(result, dict) else "invalid"
            raise RuntimeError("OneBot %s 未确认成功，retcode=%s" % (action, code))
        return result.get("data")

    def check_at_all(self):
        result = self.call("get_group_at_all_remain", {"group_id": self.group})
        if not isinstance(result, dict) or result.get("can_at_all") is not True:
            raise RuntimeError("机器人当前无法 @全体成员，请检查群管理员权限与 @全体额度")
        for key in ("remain_at_all_count_for_group", "remain_at_all_count_for_uin"):
            if key in result and (not isinstance(result[key], int) or result[key] <= 0):
                raise RuntimeError("@全体成员剩余额度不足，通知未发送")
        return result

    def send(self, content):
        self.check_at_all()
        result = self.call("send_group_msg", {
            "group_id": self.group,
            "message": [{"type": "at", "data": {"qq": "all"}},
                        {"type": "text", "data": {"text": "\n" + content}}],
        })
        if not isinstance(result, dict) or result.get("message_id") is None:
            raise RuntimeError("OneBot 未返回消息 ID，发送结果待确认")
        return result
