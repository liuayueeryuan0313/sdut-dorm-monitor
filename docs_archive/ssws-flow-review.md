# 复盘：从 CAS 登录到查寝数据落盘

> 实测账号 25110103112 · 2026-10-17 · 全链路验证通过

---

## 全景图

    ┌──────────────┐   302     ┌────────────────┐   POST 凭据   ┌───────────────┐
    │ 业务系统      │ ───────▶ │ CAS 统一认证    │ ───────────▶ │ 302 + ticket  │
    │ index.do     │           │ authserver     │              │               │
    └──────────────┘           └────────────────┘              └───────┬───────┘
                                                                       │ 带 ticket 回跳
                                                                       ▼
    ┌─────────────────────────────────────────────────────────────────────────┐
    │ 业务会话建立：_WEU + JSESSIONID                                          │
    └──────────────────────────────────┬──────────────────────────────────────┘
                                       ▼
    ┌─────────────────┐      ┌──────────────────┐      ┌────────────────────┐
    │ 角色引导         │ ───▶ │ 查寝数据接口      │ ───▶ │ 落盘 JSON / CSV     │
    │ getUserRoles    │      │ getStudent...Dz  │      │ 34 条               │
    │ setAppRole      │      │                  │      │                    │
    └─────────────────┘      └──────────────────┘      └────────────────────┘

---

## 阶段 1 · CAS 登录（已封装在 sdut_login.py）

| 步骤 | 动作 | 关键点 |
|---|---|---|
| 1.1 | GET 业务系统 index.do | 得到 **302**，Location 指向 CAS，service 参数回带原始 URL |
| 1.2 | GET CAS 登录页 | 从页面取出 pwdEncryptSalt / execution / lt |
| 1.3 | 前端 AES 加密 | 见下方公式 |
| 1.4 | POST /authserver/login | 302 回业务系统，带 ?ticket=ST-xxx |
| 1.5 | 带 ticket 回跳 | 业务系统消费 ticket，下发 **_WEU** 会话 Cookie |

### 密码加密公式（逆向自 encrypt.js）

    password = Base64( AES-128-CBC(
        key  = pwdEncryptSalt        # 16 个 ASCII 字符，每次刷新都变
        iv   = randomString(16)      # 随机
        data = randomString(64) + 明文密码
        PKCS7 填充 ))

- 随机前缀 64 字符，服务端解密后丢弃
- **name=passwordText 的输入框被 JS 设为 disabled**，disabled 控件不参与提交
  ⇒ 请求体里只有密文，明文密码永不出现在网络里
- 本机没有任何加密库，aes_tool.py 是纯 Python 实现，已过 FIPS-197 / NIST SP800-38A 标准向量

---

## 阶段 2 · 会话与角色

### 2.1 Cookie 分工

| Cookie | 域 / 路径 | 作用 |
|---|---|---|
| JSESSIONID | xgfw / /xsfw | 业务侧会话 |
| JSESSIONID | authserver / /authserver | 认证侧会话 |
| **_WEU** | xgfw / /xsfw/ （secure） | **业务侧登录态，业务接口靠它鉴权** |
| CASTGC | authserver | CAS 全局票据（TGT），SSO 复用核心 |
| route | 两个域 | openresty 负载均衡粘滞 |
| happyVoyage | authserver | 金智附加载荷 |

### 2.2 角色引导（最容易漏的一步）

    POST /xsfw/sys/swpubapp/NewMobileAPIController/getUserRoles.do
         {"APPID":"5012298006853004"}
      → {"code":"0","data":[{"ROLEID":"52109f9a...","ROLENAME":"学生组","DATAROLE":"DSW600"}]}

    POST /xsfw/sys/swpubapp/NewMobileAPIController/setAppRole.do
         {"APPID":"5012298006853004","APPNAME":"swmsswsapp","ROLEID":"52109f9a..."}
      → {"code":"0","msg":"成功"}

**跳过这两步，业务接口一律 403。**

---

## 阶段 3 · 接口定位路径

    index.do                                ← SPA 空壳，pageMeta 是空的
      └─ index/configExtend.js              ← 路由表
           └─ path: /sswsStu
              component: newmob/sswsstu/index/index
                └─ require('api')
                     └─ api.js 定义:
                        getStudentDormHygieneInfoDz =
                          /xsfw/sys/swmsswsapp/MobileStudentDormHygieneInfoController/
                          getStudentDormHygieneInfoDz.do

关键：**数据不在 HTML 里**，是 SPA 加载后由 XHR 取回的，必须先找路由再找 api.js。

---

## 阶段 4 · 接口调用（三个必守约定）

### 4.1 提交格式：单个 data 字段

金智 WIS 的 MOB_UTIL.doPost 不是常规表单：

    transformRequest: function (data) {
        return "data=" + encodeURIComponent(JSON.stringify(data));
    }

    POST <url>
    Content-Type: application/x-www-form-urlencoded
    X-Requested-With: XMLHttpRequest
    data=%7B%22PAGENUM%22%3A1%2C%22PAGESIZE%22%3A50%7D

按普通表单展开（PAGENUM=1&PAGESIZE=50）⇒ **403**。

### 4.2 querySetting 是数组不是对象

来自 emapAdvancedQuery.getQuerySetting()：

    [{"name":"JCRQ","caption":"检查日期","value":"2026-09-01","builder":"moreEqual","linkOpt":"AND"},
     {"name":"JCRQ","caption":"检查日期","value":"2026-10-17","builder":"lessEqual","linkOpt":"AND"}]

传对象 {"JCRQ":{"minValue":..,"maxValue":..}} ⇒ 服务器**静默返回空数组**（不报错，最坑）。

### 4.3 成功判据是 code == "0"

    {"code":"0","msg":"成功","data":[ ... ]}

失败时 code 是 #E101... 之类，而 HTTP 仍然是 200。

---

## 阶段 5 · 数据形态

getStudentDormHygieneInfoDz.do 返回 34 条，核心字段：

| 字段 | 含义 |
|---|---|
| WID | 记录唯一 ID ← **增量判据首选** |
| JCRQ | 检查日期 |
| SSLMC / FJH | 宿舍楼 / 房间号 |
| FS / DJMC | 分数 / 等级（优秀·合格·不合格） |
| WGXX / WGLXDM_DISPLAY | 违规信息 / 违规类型 |
| JCLXDM_DISPLAY / ZC | 检查类型 / 周次 |

实测：34 条，2025-10-13 ~ 2026-10-15，优秀 30 / 合格 3 / 不合格 1，均分 91.6。

---

## 踩坑清单

| # | 现象 | 真因 | 解法 |
|---|---|---|---|
| 1 | curl / .NET 全部 TLS 失败 | schannel: SEC_E_NO_CREDENTIALS | 用 Python(OpenSSL)，别用 curl |
| 2 | 业务接口全 403 | 没先 setAppRole | 必须先角色引导 |
| 3 | 业务接口仍 403 | 参数没按 data=<json> 提交 | 单个 data 字段 |
| 4 | 查询返回空数组 | querySetting 传了对象 | 必须传数组 |
| 5 | 中文输出乱码 | 控制台 GBK | 写 UTF-8 文件再读 |
| 6 | **CAS 返回 401** | **短时间登录次数过多被限流** | **复用会话，别反复重登；退避重试** |

---

## 给定时同步脚本的三条硬约束

1. **登录一次，长期复用会话**（约束来自坑 6）
2. **增量靠 WID 集合比对**，不要靠日期
3. **失败要退避**，不要把限流升级成账号锁定

---

## 复用资产

| 文件 | 职责 |
|---|---|
| aes_tool.py | 纯 Python AES-128-CBC |
| sdut_login.py | CAS 登录 + 会话（含 401 友好报错） |
| sdut_ssws.py | 角色引导 + 查寝数据拉取 |
| ssws-api.md | 接口参考 |
| sync_qqbot.py | 定时同步到 QQ 机器人（配置留空待填） |
