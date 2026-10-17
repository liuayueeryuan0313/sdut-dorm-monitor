"""SDUT dorm electricity lookup: WebForms postbacks + existing, verified CAS AES.

Only query/postback controls are submitted. No recharge or payment action exists here.
All dependencies are from Python's standard library and this project's sdut_login module.
"""
import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import getpass
from html.parser import HTMLParser
import http.cookiejar
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from sdut_login import LoginBlocked, make_opener, parse_login_form, post_credentials

QUERY_URL = "https://hqfw.sdut.edu.cn/stu_elc.aspx"
CAS_HOST = "authserver.sdut.edu.cn"
HQ_HOST = "hqfw.sdut.edu.cn"
CHINA = timezone(timedelta(hours=8))


class ElectricityError(RuntimeError):
    pass


class SelectionError(ElectricityError):
    pass


class ResultParseError(ElectricityError):
    pass


class _NeedsLogin(Exception):
    def __init__(self, url, html):
        self.url, self.html = url, html


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def event_target(script):
    script = script.replace("\\'", "'").replace('\\"', '"')
    match = re.search(r"__doPostBack\(\s*['\"]([^'\"]+)['\"]", script)
    return match.group(1) if match else None


class FormPage(HTMLParser):
    """Parse successful form controls and table text without guessing hidden tokens."""
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.hidden = {}
        self.fields = {}
        self.inputs = {}
        self.radios = {}
        self.selects = {}
        self.targets = {}
        self.buttons = {}
        self.labels = {}
        self.action = ""
        self.rows = []
        self.text_parts = []
        self._select = None
        self._option = None
        self._label = None
        self._label_parts = []
        self._row_stack = []
        self._cell = None
        self._cell_parts = []
        self._skip = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "form" and not self.action:
            self.action = attrs.get("action", "")
        name = attrs.get("name")
        disabled = "disabled" in attrs
        if tag == "input" and name and not disabled:
            kind, value = attrs.get("type", "text").lower(), attrs.get("value", "")
            self.inputs[name] = value
            if kind == "hidden":
                self.hidden[name] = value
                self.fields[name] = value
            elif kind == "radio":
                self.radios.setdefault(name, []).append(dict(
                    value=value, id=attrs.get("id", ""), target=event_target(attrs.get("onclick", ""))))
                if "checked" in attrs:
                    self.fields[name] = value
            elif kind in ("submit", "button", "image", "reset"):
                self.buttons[name] = value
            elif kind != "checkbox" or "checked" in attrs:
                self.fields[name] = value
        if tag == "select" and name and not disabled:
            self._select = name
            self.selects[name] = []
            self.targets[name] = event_target(attrs.get("onchange", ""))
        if tag == "option" and self._select:
            self._option = dict(value=attrs.get("value"), label="", disabled=disabled,
                                selected="selected" in attrs)
        if tag == "label" and attrs.get("for"):
            self._label, self._label_parts = attrs["for"], []
        if tag == "tr":
            self._row_stack.append([])
        if tag in ("td", "th") and self._row_stack:
            self._cell, self._cell_parts = tag, []

    def handle_data(self, data):
        if self._skip:
            return
        if data.strip():
            self.text_parts.append(data)
        if self._option is not None:
            self._option["label"] += data
        if self._label:
            self._label_parts.append(data)
        if self._cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        if tag == "option" and self._option is not None:
            self._option["label"] = clean(self._option["label"])
            if self._option["value"] is None:
                self._option["value"] = self._option["label"]
            self.selects[self._select].append(self._option)
            self._option = None
        if tag == "select" and self._select:
            options = self.selects[self._select]
            selected = next((option for option in options if option["selected"] and not option["disabled"]),
                            next((option for option in options if not option["disabled"]), None))
            if selected:
                self.fields[self._select] = selected["value"]
            self._select = None
        if tag == "label" and self._label:
            self.labels[self._label] = clean(" ".join(self._label_parts))
            self._label = None
        if tag in ("td", "th") and self._cell and self._row_stack:
            self._row_stack[-1].append(clean(" ".join(self._cell_parts)))
            self._cell = None
        if tag == "tr" and self._row_stack:
            row = self._row_stack.pop()
            if row:
                self.rows.append(row)

    def options(self, name):
        return [dict(value=o["value"], label=o["label"]) for o in self.selects.get(name, [])
                if not o["disabled"] and o["value"] not in ("", "0")
                and not re.search(r"请选择|请先选择", o["label"])]


def _normal(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text))).casefold()


def resolve_option(options, selector, kind):
    """Exact display label or explicit id:VALUE; numeric room suffix must be unique."""
    wanted = str(selector).strip()
    if wanted.startswith("id:"):
        matches = [o for o in options if o["value"] == wanted[3:]]
    else:
        matches = [o for o in options if _normal(o["label"]) == _normal(wanted.removeprefix("label:"))]
        if not matches and wanted.isdigit():
            if kind == "building":
                matches = [o for o in options if re.match(r"^0*" + re.escape(wanted) + r"(?:#|号|公寓|宿舍|\b)", _normal(o["label"]))]
            elif kind == "floor":
                matches = [o for o in options if _normal(o["label"]) in (wanted + "楼", wanted + "层")]
            elif kind == "room":
                matches = [o for o in options if re.search(r"(?<!\d)0*" + re.escape(wanted) + r"(?:室|房|号)?(?:照明插座|照明|空调用电|空调)?$", _normal(o["label"]))]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise SelectionError("%s 选项不唯一，请使用完整名称或 id:值：%s" %
                             (kind, json.dumps(matches, ensure_ascii=False)))
    raise SelectionError("未找到 %s=%s；可选项：%s" %
                         (kind, wanted, json.dumps(options, ensure_ascii=False)))


def parse_balance(html):
    """Only return amounts explicitly present in the page, never infer yuan from kWh."""
    page = FormPage(html)
    text = clean(" ".join(page.text_parts))
    number = r"[￥¥]?\s*([+-]?\d[\d,]*(?:\.\d+)?)"
    labels = {
        "remaining_kwh": r"(?:剩余电[（(]水[）)]量|剩余电量|剩余度数|电量余额|剩余电度|剩余用电量)",
        "balance_cny": r"(?:剩余金额|剩余电费|电费余额|账户余额|余额[（(]元[）)])",
    }
    result = {}
    for key, label in labels.items():
        values = {format(Decimal(match.group(1).replace(",", "")), "f")
                  for match in re.finditer(label + r"\s*(?:[（(][^()（）]{0,12}[）)])?\s*[:：]?\s*" + number, text)}
        if len(values) > 1:
            raise ResultParseError("页面存在多个不同的%s，不能确定当前房间余额" % key)
        result[key] = next(iter(values), None)
    # Generic balance labels require an explicit currency unit to avoid confusing kWh.
    if result["balance_cny"] is None:
        match = re.search(r"(?:余额|剩余)\s*[:：]?\s*" + number + r"\s*元", text)
        if match:
            result["balance_cny"] = format(Decimal(match.group(1).replace(",", "")), "f")
    usage = {}
    for match in re.finditer(r"(已用电量|累计用电量|本月用电量|总用电量|已用度数)\s*[:：]?\s*" + number, text):
        usage[match.group(1)] = format(Decimal(match.group(2).replace(",", "")), "f")
    if all(result[key] is None for key in labels):
        raise ResultParseError("页面未识别到明确的剩余电量或电费余额，不能把空结果当成 0；请核对结果页字段")
    result["usage_kwh"] = usage
    location = re.search(r"房间位置\s*[:：]?\s*(.*?)(?=\s*注意事项|\s*返回|$)", text)
    result["page_location"] = location.group(1).strip() if location else None
    result["source_notes"] = [line.strip() for line in page.text_parts if "每小时更新" in line]
    return result


@dataclass
class ElectricityBalance:
    campus: str
    building: str
    floor: str
    room: str
    electricity_type: str
    remaining_kwh: str | None
    balance_cny: str | None
    usage_kwh: dict
    page_location: str | None
    source_notes: list
    checked_at: str
    selection_ids: dict

    def to_dict(self):
        return asdict(self)


class ElectricityClient:
    def __init__(self, username=None, password=None, *, timeout=30, opener=None, clock=time.monotonic):
        self.username = username
        self.password = password
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = opener if opener is not None else make_opener(self.jar)
        self.clock = clock
        self.last_login_attempt = None
        self.page = None
        self.page_url = QUERY_URL

    def _request(self, url, data=None):
        destination = urllib.parse.urlparse(url)
        if destination.scheme != "https" or destination.hostname != HQ_HOST:
            raise ElectricityError("拒绝向非后勤站点提交查询表单")
        headers = {"Referer": QUERY_URL}
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            body = urllib.parse.urlencode(data).encode("utf-8")
        else:
            body = None
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                final_url = response.url
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                html = raw.decode(charset)
        except urllib.error.HTTPError as error:
            raise ElectricityError("电费页面 HTTP %s，未自动重试" % error.code) from None
        except (UnicodeError, LookupError):
            raise ElectricityError("电费页面编码无法识别") from None
        destination = urllib.parse.urlparse(final_url)
        if destination.hostname == CAS_HOST and "authserver/login" in destination.path:
            raise _NeedsLogin(final_url, html)
        if destination.hostname != HQ_HOST:
            raise ElectricityError("后勤查询跳转到了非预期站点")
        page = FormPage(html)
        if "__VIEWSTATE" not in page.hidden:
            raise ElectricityError("电费页面缺少 __VIEWSTATE，页面可能改版或会话失效")
        self.page_url, self.page = final_url, page
        return html

    def _post(self, changes, target="", *, query=False):
        if self.page is None:
            raise ElectricityError("尚未载入表单")
        form_url = urllib.parse.urljoin(self.page_url, self.page.action or self.page_url)
        fields = {**self.page.fields, **changes, "__EVENTTARGET": target, "__EVENTARGUMENT": ""}
        if query:
            if "btn_submit" not in self.page.buttons:
                raise ElectricityError("未找到查询按钮，停止提交以避免误操作")
            fields["btn_submit"] = self.page.buttons["btn_submit"]
        return self._request(form_url, fields)

    def _radio(self, name, value):
        options = self.page.radios.get(name, [])
        option = next((o for o in options if o["value"] == value), None)
        if option is None or not option["target"]:
            raise SelectionError("页面中未找到可回发的 %s=%r" % (name, value))
        self._post({name: value}, option["target"])

    def _authenticate(self, challenge):
        if not self.username or not self.password:
            raise LoginBlocked("后勤查询需要统一认证，请提供本人学号和密码")
        now = self.clock()
        if self.last_login_attempt is not None and now - self.last_login_attempt < 300:
            raise LoginBlocked("距上次认证尝试不足 5 分钟，停止自动重登")
        self.last_login_attempt = now
        meta = parse_login_form(challenge.html)
        form = FormPage(challenge.html)
        meta["execution"] = meta["execution"] or form.inputs.get("execution")
        if not meta["salt"]:
            meta["salt"] = form.inputs.get("pwdEncryptSalt")
        if not meta["salt"]:
            match = re.search(r"(?:var\s+)?pwdEncryptSalt\s*=\s*['\"]([^'\"]+)['\"]", challenge.html)
            meta["salt"] = match.group(1) if match else None
        if not meta["execution"] or not meta["salt"] or len(meta["salt"].encode("utf-8")) != 16:
            raise LoginBlocked("CAS 页面缺少 execution 或 16 字节加密盐，不猜测密钥或 IV")
        _, html, final_url = post_credentials(self.opener, challenge.url, self.username, self.password, meta)
        if urllib.parse.urlparse(final_url).hostname == CAS_HOST:
            raise LoginBlocked("CAS 登录未完成，可能需要验证码或凭据被拒绝；未自动重试")
        if urllib.parse.urlparse(final_url).hostname != HQ_HOST:
            raise LoginBlocked("CAS 未返回后勤系统，停止查询")
        # The postback state from before CAS must never be reused after authentication.
        self.page = None

    @staticmethod
    def power_value(electricity_type):
        if electricity_type in ("", "照明插座", "lighting"):
            return ""
        if electricity_type in ("空调", "空调用电", "aircon"):
            return "空调"
        raise SelectionError("用电类型须为照明插座或空调用电")

    def _prepare(self, campus, building, floor, room, electricity_type):
        self._request(QUERY_URL)
        self._radio("RadioButtonList2", self.power_value(electricity_type))
        self._radio("RadioButtonList1", campus)
        chosen = {}
        for name, value, kind in (("DropDownList1", building, "building"),
                                  ("DropDownList2", floor, "floor"),
                                  ("DropDownList3", room, "room")):
            if value is None:
                return {"level": kind, "options": self.page.options(name), "selected": chosen}
            option = resolve_option(self.page.options(name), value, kind)
            chosen[kind] = option
            if kind == "room":
                self.page.fields[name] = option["value"]
            else:
                target = self.page.targets.get(name)
                if not target:
                    raise SelectionError("缺少 %s 的回发事件，停止查询" % kind)
                self._post({name: option["value"]}, target)
        return chosen

    def _with_login(self, operation):
        for attempt in range(2):
            try:
                return operation()
            except _NeedsLogin as challenge:
                if attempt:
                    raise LoginBlocked("认证后仍要求登录，不再重复提交密码") from None
                self._authenticate(challenge)
        raise ElectricityError("查询流程未完成")

    def list_options(self, campus="西校区", building=None, floor=None, electricity_type="照明插座"):
        return self._with_login(lambda: self._prepare(campus, building, floor, None, electricity_type))

    def query(self, campus, building, floor, room, electricity_type="照明插座"):
        def operation():
            selected = self._prepare(campus, building, floor, room, electricity_type)
            html = self._post({}, query=True)
            values = parse_balance(html)
            return ElectricityBalance(campus=campus, building=selected["building"]["label"],
                                      floor=selected["floor"]["label"], room=selected["room"]["label"],
                                      electricity_type="空调用电" if self.power_value(electricity_type) else "照明插座",
                                      **values, checked_at=datetime.now(CHINA).isoformat(timespec="seconds"),
                                      selection_ids={key: option["value"] for key, option in selected.items()})
        return self._with_login(operation)


def query_electricity(username, password, campus, building, floor, room, electricity_type="照明插座"):
    return ElectricityClient(username, password).query(campus, building, floor, room, electricity_type).to_dict()


def main():
    parser = argparse.ArgumentParser(description="SDUT 宿舍电量/电费只读查询（不充值）")
    parser.add_argument("--campus", choices=("西校区", "东校区"), default="西校区")
    parser.add_argument("--building", help="页面名称或 id:值；数字楼号须能唯一匹配")
    parser.add_argument("--floor", help="楼层名称或 id:值")
    parser.add_argument("--room", help="完整房间名称、唯一房号或 id:值")
    parser.add_argument("--type", choices=("照明插座", "空调用电", "lighting", "aircon"), default="照明插座")
    parser.add_argument("--list-options", action="store_true", help="逐级列出楼栋、楼层或房间选项")
    parser.add_argument("--user", default=os.environ.get("SDUT_USER"))
    args = parser.parse_args()
    username = args.user
    password = os.environ.get("SDUT_PWD")
    if not args.list_options:
        if not all(value is not None for value in (args.building, args.floor, args.room)):
            parser.error("查询需填写 --building、--floor、--room；也可先 --list-options")
        username = username or input("学号：").strip()
        password = password or getpass.getpass("学校密码（不保存）：")
    try:
        client = ElectricityClient(username, password)
        result = (client.list_options(args.campus, args.building, args.floor, args.type)
                  if args.list_options else client.query(args.campus, args.building, args.floor, args.room, args.type).to_dict())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        message = str(error)
        if password:
            message = message.replace(password, "[已隐藏]")
        print(json.dumps({"error": message, "type": type(error).__name__}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
