"""山东理工大学 学工系统「宿舍卫生 / 查寝」数据采集.

Login 复用 sdut_login.py (CAS + AES).
数据接口: MobileStudentDormHygieneInfoController
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from sdut_login import login

X = "https://xgfw.sdut.edu.cn/xsfw"
APPDIR = X + "/sys/swmsswsapp/*default/"
BOOT = X + "/sys/swpubapp/NewMobileAPIController/"
CTRL = X + "/sys/swmsswsapp/MobileStudentDormHygieneInfoController/"

APPID = "5012298006853004"
APPNAME = "swmsswsapp"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 原始字段 -> 中文含义
FIELD_MAP = {
    "WID": "记录ID",
    "JCRQ": "检查日期",
    "SSLMC": "宿舍楼",
    "FJH": "房间号",
    "BJ": "班级",
    "XSBH": "学号",
    "FS": "分数",
    "JCFS": "基础分",
    "DJMC": "等级",
    "XSDJMC": "学生等级",
    "SSDJMC": "宿舍等级",
    "WGXX": "违规信息",
    "WGLXDM_DISPLAY": "违规类型",
    "JCLXDM_DISPLAY": "检查类型",
    "JCLXDM": "检查类型码",
    "ZC": "周次",
    "XN": "学年",
    "XQ": "学期",
    "XN_DISPLAY": "学年名称",
    "XQ_DISPLAY": "学期名称",
    "XQMC": "校区",
    "CZZ": "检查人账号",
    "JCBM": "检查编码",
    "SSDM": "宿舍代码",
}


class SswsError(RuntimeError):
    pass


class SswsClient:
    """一次登录，可反复调用。"""

    def __init__(self, user, pwd, verbose=False):
        self.op, self.jar, self.landed = login(user, pwd, verbose=verbose)
        self.role_id = None

    # ---------- 底层请求 ----------
    def _post(self, url, params):
        """金智 WIS 约定的提交格式: 单个 data= 字段, 值为 JSON 的 URI 编码."""
        body = "data=" + urllib.parse.quote(json.dumps(params, ensure_ascii=False), safe="!*'()")
        req = urllib.request.Request(
            url, data=body.encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": APPDIR + "index.do",
                "Origin": "https://xgfw.sdut.edu.cn",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "User-Agent": UA,
            })
        try:
            r = self.op.open(req, timeout=30)
            raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise SswsError("HTTP %s on %s" % (e.code, url))
        try:
            return json.loads(raw)
        except ValueError:
            raise SswsError("非 JSON 响应 (%d bytes): %s" % (len(raw), raw[:200]))

    # ---------- 引导 ----------
    def bootstrap(self):
        """必须先设置当前角色, 否则业务接口 403."""
        res = self._post(BOOT + "getUserRoles.do", {"APPID": APPID})
        if res.get("code") != "0":
            raise SswsError("getUserRoles 失败: %s" % res.get("msg"))
        roles = res.get("data") or []
        if not roles:
            raise SswsError("该账号在此应用下没有可用角色")
        self.role_id = roles[0]["ROLEID"]
        res = self._post(BOOT + "setAppRole.do",
                         {"APPID": APPID, "APPNAME": APPNAME, "ROLEID": self.role_id})
        if res.get("code") != "0":
            raise SswsError("setAppRole 失败: %s" % res.get("msg"))
        return roles

    # ---------- 业务 ----------
    @staticmethod
    def build_date_filter(start, end, field="JCRQ"):
        """构造 querySetting 数组 (emapAdvancedQuery 的 getQuerySetting 输出格式)."""
        q = []
        if start:
            q.append({"name": field, "caption": "检查日期", "value": start,
                      "builder": "moreEqual", "linkOpt": "AND"})
        if end:
            q.append({"name": field, "caption": "检查日期", "value": end,
                      "builder": "lessEqual", "linkOpt": "AND"})
        return q

    def list_records(self, page_size=50, max_pages=50, start=None, end=None, endpoint="dz"):
        """翻页拉取全部查寝记录. start/end 为 'YYYY-MM-DD', 留空则拉全量."""
        url = CTRL + {
            "dz": "getStudentDormHygieneInfoDz.do",
            "new": "getStudentDormHygieneInfoNew.do",
        }[endpoint]
        rows, page = [], 1
        qs = self.build_date_filter(start, end)
        while page <= max_pages:
            params = {"PAGENUM": page, "PAGESIZE": page_size}
            if qs:
                params["querySetting"] = json.dumps(qs, ensure_ascii=False)
            res = self._post(url, params)
            if res.get("code") != "0":
                raise SswsError("查询失败: %s" % res.get("msg"))
            batch = res.get("data") or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
            page += 1
        return rows

    @staticmethod
    def normalize(row):
        """原始字段 -> 中文键."""
        return {FIELD_MAP.get(k, k): v for k, v in row.items()}

    def latest(self, **kw):
        rows = self.list_records(**kw)
        rows.sort(key=lambda r: (r.get("JCRQ") or ""), reverse=True)
        return rows
