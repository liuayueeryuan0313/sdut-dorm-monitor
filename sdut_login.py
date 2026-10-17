"""山东理工大学 统一身份认证 (金智 wisedu CAS) 登录客户端.

用法:
    set SDUT_USER=25110103112
    set SDUT_PWD=******
    python sdut_login.py

依赖同目录下的 aes_tool.py (纯 Python AES-128-CBC, 无第三方库).
"""
import http.cookiejar
import os
import re
import sys
import urllib.parse
import urllib.request

from aes_tool import encrypt_password

class LoginBlocked(RuntimeError):
    """Authentication needs user attention; automatic retries must stop."""

APP = "https://xgfw.sdut.edu.cn/xsfw/sys/swmsswsapp/*default/index.do"
BASE = "https://authserver.sdut.edu.cn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def make_opener(jar):
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [
        ("User-Agent", UA),
        ("Accept", "text/html,application/xhtml+xml,*/*;q=0.8"),
        ("Accept-Language", "zh-CN,zh;q=0.9"),
    ]
    return op


def fetch_login_page(op, app_url=APP):
    """第 1 步: 访问业务系统 -> 302 到 CAS -> 返回登录页 HTML 与登录地址."""
    resp = op.open(app_url + "?", timeout=25)
    html = resp.read().decode("utf-8", "replace")
    return resp.url, html


def parse_login_form(html):
    """从登录页提取服务端下发的动态参数."""
    salt = re.search(r'id="pwdEncryptSalt"[^>]*value="([^"]*)"', html)
    execution = re.search(r'name="execution"[^>]*value="([^"]*)"', html)
    lt = re.search(r'id="lt"[^>]*value="([^"]*)"', html)
    need_captcha = re.search(r"var needCaptcha\s*=\s*([^;]+);", html)
    captcha_switch = re.search(r'var captchaSwitch\s*=\s*"([^"]*)"', html)
    return {
        "salt": salt.group(1) if salt else None,
        "execution": execution.group(1) if execution else None,
        "lt": lt.group(1) if lt else "",
        "needCaptcha": need_captcha.group(1).strip() if need_captcha else "false",
        "captchaSwitch": captcha_switch.group(1) if captcha_switch else None,
    }


def post_credentials(op, login_url, user, pwd, meta, captcha=None):
    """第 2 步: POST /authserver/login."""
    need = str(meta.get("needCaptcha", "false")).strip().lower()
    if len(need) >= 2 and need[0] == need[-1] and need[0] in ("'", '"'):
        need = need[1:-1]
    if need not in ("", "false", "0", "null", "none") and not captcha:
        raise LoginBlocked("登录需要验证码，请先在学校官网处理，再手动启动监测")
    form = {
        "username": user,
        "password": encrypt_password(pwd, meta["salt"]),
        "lt": meta["lt"],
        "execution": meta["execution"],
        "_eventId": "submit",
        "cllt": "userNameLogin",
        "dllt": "generalLogin",
        "rmShown": "1",
    }
    if captcha:
        form["captcha"] = captcha
    req = urllib.request.Request(
        login_url,
        data=urllib.parse.urlencode(form).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": login_url,
            "Origin": BASE,
            "User-Agent": UA,
        },
    )
    try:
        resp = op.open(req, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise LoginBlocked(
                "CAS 返回 401: 登录被拒绝。常见原因是短时间内登录次数过多触发限流/临时封锁；"
                "请等待 30-60 分钟再试, 不要连续重试。")
        if e.code == 403:
            raise LoginBlocked("CAS 返回 403: 请求被拒绝(可能是 WAF 或 IP 限制)。")
        raise
    return resp.status, resp.read().decode("utf-8", "replace"), resp.url


def login(user, pwd, captcha=None, app_url=APP, verbose=True):
    """返回 (opener, cookie_jar, 登录后落地的 URL). 失败抛 RuntimeError."""
    jar = http.cookiejar.CookieJar()
    op = make_opener(jar)

    login_url, html = fetch_login_page(op, app_url)
    meta = parse_login_form(html)
    if verbose:
        print("[1] 业务系统 -> 302 -> %s" % login_url)
        print("    下发参数: salt=%r execution=%r lt=%r needCaptcha=%s captchaSwitch=%s"
              % (meta["salt"], meta["execution"], meta["lt"], meta["needCaptcha"], meta["captchaSwitch"]))
    if not meta["salt"] or not meta["execution"]:
        raise RuntimeError("登录页结构变了, 未取到 salt/execution")

    status, body, final_url = post_credentials(op, login_url, user, pwd, meta, captcha)
    if verbose:
        print("[2] POST /authserver/login -> %s" % status)
        print("    落地: %s" % final_url)
    if "authserver/login" in urllib.parse.urlparse(final_url).path:
        tip = re.search(r'id="showErrorTip"[^>]*>(.*?)</', body, re.S)
        msg = re.sub(r"<[^>]+>", "", tip.group(1)).strip() if tip else "登录被拒 (可能需要验证码)"
        raise LoginBlocked("登录失败: %s" % msg)
    if verbose:
        print("[3] 会话 Cookie: %s" % ", ".join(sorted({c.name for c in jar})))
    return op, jar, final_url


def main():
    user = os.environ.get("SDUT_USER") or (sys.argv[1] if len(sys.argv) > 1 else None)
    pwd = os.environ.get("SDUT_PWD") or (sys.argv[2] if len(sys.argv) > 2 else None)
    if not user or not pwd:
        print(__doc__)
        print("缺少凭据: 设置 SDUT_USER / SDUT_PWD 环境变量")
        return 2
    op, jar, url = login(user, pwd)
    print("[4] 复用会话再次访问业务系统 (无 ticket):")
    r = op.open(APP, timeout=25)
    body = r.read().decode("utf-8", "replace")
    m = re.search(r'"params":\s*\{"userId":"([^"]*)"', body)
    print("    status=%s bytes=%d userId=%s 需要重新登录=%s"
          % (r.status, len(body), m.group(1) if m else "?", "authserver/login" in r.url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
