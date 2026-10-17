# 查寝监测 → QQ 机器人推送 · 项目交接文档

| 项 | 值 |
|---|---|
| 生成时间 | 2026-10-17 |
| 工作区 | C:\Users\liuay\OneDrive\文档\deepseek-harness\default-workspace |
| 运行平台 | Windows 10/11 + Python 3.12（DSH 自带运行时） |
| 状态 | 数据采集层已完全跑通；推送层待 QQ 机器人凭据 |

---

## 0. 这个项目做什么

> **定时读取山东理工大学学工系统的「宿舍卫生 / 查寝」结果，发现新记录时通过 QQ 机器人推送到指定群。**

### 做
- CAS 自动登录 + 会话长期复用
- 周期轮询查寝接口
- 按 WID 做增量比对、去重
- 推送到 QQ 群

### 不做（边界）
- 不代签、不伪造打卡、不发起任何写操作
- 不碰他人账号
- 不绕过验证码/风控，遇到就告警停下

---

## 1. 当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | CAS 登录链路（含前端 AES 加密） | ✅ 已验证 |
| P1 | 业务会话 + 角色引导 | ✅ 已验证 |
| P2 | 查寝数据接口定位与调用 | ✅ 已验证 |
| P3 | 全量数据导出 | ✅ 34 条已落盘 |
| P4 | 定时同步脚本 + 增量比对 | ✅ 端到端已跑通（3 轮测试） |
| P5 | QQ 机器人创建 | ⏸ **待人工操作**（见第 7 节） |
| P6 | group_openid 采集工具 | ✅ 已就绪，待凭据 |
| P7 | Docker 化 | ❌ 未开始 |
| P8 | 云服务器部署 | ❌ 未开始 |

**关键结论：除了 QQ 推送那一环，其余全部可用。**

---

## 2. 目录结构与文件职责

### 核心代码

| 文件 | 职责 | 状态 |
|---|---|---|
| aes_tool.py | 纯 Python AES-128-CBC（无第三方库），过 FIPS-197 / NIST SP800-38A 向量 | ✅ |
| sdut_login.py | CAS 登录 + 会话（含 401 限流友好报错） | ✅ |
| sdut_ssws.py | 角色引导 + 查寝数据拉取，SswsClient 类 | ✅ |
| export_ssws.py | 导出全量数据为 JSON/CSV | ✅ |
| sync_qqbot.py | **定时同步主程序**（配置区在文件顶部） | ✅ |
| get_group_openid.py | 抓取 group_openid（自带最小 WebSocket 客户端，零依赖） | ✅ |

### 文档

| 文件 | 内容 |
|---|---|
| HANDOVER.md | 本文件 |
| ssws-flow-review.md | 登录到数据的完整复盘 + 踩坑清单 |
| ssws-api.md | 数据接口参考（请求约定 / 接口清单 / 字段字典） |
| qqbot-create-guide.md | QQ 机器人创建清单 |
| qqbot-config.md | QQ 机器人能力速查表 |
| qqbot-docs-raw.md | QQ 机器人官方文档原始抓取存档（423 页中精选 16 页） |

### 数据与产物

| 路径 | 内容 |
|---|---|
| data/ssws_all.json | 全量 34 条记录（含原始字段、角色、配置、字段字典） |
| data/ssws_records.csv | 同一批数据的扁平表格（17 列中文表头） |
| data/ssws_summary.txt | 可读汇总 |
| data/sync_state.json | **增量状态：34 条已见 WID**（首次正式运行不会刷屏靠它） |
| data/sync.log | 同步运行日志 |
| _profile_backup/ | DSH profile 配置备份（与查寝项目无关，见第 6 节） |

---

## 3. 技术档案

### 3.1 登录链路

    GET 业务系统 index.do
      → 302 到 https://authserver.sdut.edu.cn/authserver/login?service=<原URL>
    GET 登录页，取出 pwdEncryptSalt / execution / lt
    POST 凭据 → 302 带 ?ticket=ST-xxx 回业务系统
    业务系统消费 ticket → 下发 _WEU 会话 Cookie

**密码加密公式（逆向自 encrypt.js）**

    password = Base64( AES-128-CBC(
        key  = pwdEncryptSalt      # 16 个 ASCII 字符，每次刷新都变
        iv   = randomString(16)    # 随机
        data = randomString(64) + 明文密码
        PKCS7 填充 ))

- 随机前缀 64 字符，服务端解密后丢弃
- name=passwordText 的输入框被 JS 设为 disabled，disabled 控件不提交
  ⇒ **明文密码永不出现在网络请求里**

### 3.2 数据接口的三个必守约定

**① 提交格式是单个 data 字段**

    金智 WIS 的 MOB_UTIL.doPost：
      transformRequest: function (data) {
          return "data=" + encodeURIComponent(JSON.stringify(data));
      }

    POST <url>
    Content-Type: application/x-www-form-urlencoded
    X-Requested-With: XMLHttpRequest
    data=%7B%22PAGENUM%22%3A1%2C%22PAGESIZE%22%3A50%7D

按普通表单展开 ⇒ **403**

**② 必须先设置角色，否则业务接口一律 403**

    POST /xsfw/sys/swpubapp/NewMobileAPIController/getUserRoles.do  {"APPID":"5012298006853004"}
    POST /xsfw/sys/swpubapp/NewMobileAPIController/setAppRole.do    {...,"ROLENAME":"学生组"}

**③ querySetting 是数组，不是对象**

    [{"name":"JCRQ","caption":"检查日期","value":"2026-09-01","builder":"moreEqual","linkOpt":"AND"},
     {"name":"JCRQ","caption":"检查日期","value":"2026-10-17","builder":"lessEqual","linkOpt":"AND"}]

传对象 ⇒ 服务器**静默返回空数组**（不报错，最坑）

### 3.3 核心常量

    APPID          = 5012298006853004
    APPNAME        = swmsswsapp
    数据接口         = /xsfw/sys/swmsswsapp/MobileStudentDormHygieneInfoController/
                     getStudentDormHygieneInfoDz.do
    角色接口         = /xsfw/sys/swpubapp/NewMobileAPIController/
    成功判据         = 响应体 code == "0"（HTTP 状态码不可靠，失败时也是 200）

### 3.4 踩坑清单

| # | 现象 | 真因 | 解法 |
|---|---|---|---|
| 1 | curl / .NET 全部 TLS 失败 | schannel: SEC_E_NO_CREDENTIALS | 用 Python(OpenSSL) |
| 2 | 业务接口全 403 | 没先 setAppRole | 必须先角色引导 |
| 3 | 业务接口仍 403 | 参数没按 data=<json> 提交 | 单个 data 字段 |
| 4 | 查询静默返回空数组 | querySetting 传了对象 | 必须传数组 |
| 5 | 中文输出乱码 | 控制台 GBK | 写 UTF-8 文件再读 |
| 6 | **CAS 返回 401** | **短时间登录次数过多被限流** | **复用会话；退避重试** |

---

## 4. 运行手册

### 环境要求
- Python 3.12（DSH 自带：C:\Users\liuay\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe）
- **不需要任何第三方 Python 包**（AES、WebSocket 都是手写实现）
- 能访问 xgfw.sdut.edu.cn 与 authserver.sdut.edu.cn

### 4.1 离线自检（不联网）

    python sync_qqbot.py --selftest

### 4.2 导出全量数据

    set SDUT_USER=学号
    set SDUT_PWD=密码
    python export_ssws.py

### 4.3 首次建立基线（强烈建议先跑）

    python sync_qqbot.py --baseline

把现有记录全部记为已读，之后只推新增。

### 4.4 试跑（不真的发 QQ）

    python sync_qqbot.py --dry-run

### 4.5 正式运行

    python sync_qqbot.py            # 常驻循环
    python sync_qqbot.py --once     # 单轮，可挂 cron

### 4.6 抓 group_openid

    set QQ_APPID=...
    set QQ_SECRET=...
    python get_group_openid.py

然后在群里 @ 一次机器人。

### 4.7 环境变量一览

| 变量 | 用途 |
|---|---|
| SDUT_USER / SDUT_PWD | 学工系统账号 |
| QQ_APPID / QQ_SECRET | QQ 机器人凭据 |
| QQ_GROUP_OPENID | 推送目标群 |
| POLL_INTERVAL_MINUTES | 轮询间隔（默认 15） |
| LOOKBACK_DAYS | 每次拉取回溯天数（默认 45） |

---

## 5. 未来目标与路线图

### P5 · 接通 QQ 推送（阻塞中）
1. 按 qqbot-create-guide.md 创建机器人
2. 事件订阅方式选 **WebSocket**
3. 机器人拉进目标群
4. 跑 get_group_openid.py 抓 group_openid
5. 填入 sync_qqbot.py，跑一次真实推送验证

### P6 · 容器化
- 单容器 Python 服务
- 组件：AuthMgr（会话复用+重登）→ Poller → DiffEngine → StateStore(SQLite/JSON) → Notifier
- **QQ 机器人走 WebSocket，不需要公网/域名/证书**
- 配置全部走环境变量；volume 挂载 ./data 存状态与日志
- 健康检查 + 日志可查

    ┌──────────────── Docker Container ────────────────┐
    │  AuthMgr ──▶ SessionJar（_WEU / CASTGC）         │
    │      ▼                                            │
    │  Poller（APScheduler，时段+间隔可配）              │
    │      ▼                                            │
    │  DiffEngine + StateStore（WID 增量）              │
    │      ▼                                            │
    │  Notifier → QQ Bot（WebSocket 长连，主动推群）     │
    └──────────────────────────────────────────────────┘

### P7 · 部署上线
- 云服务器（有公网 IP，但 WebSocket 模式不需要暴露端口）
- 建议用 systemd 或 docker compose 托管
- 观察 3-7 天，确认登录不被限流

### 优化项
- 登录会话持久化（把 _WEU/CASTGC 存盘，重启用而不是重登）—— 直接缓解坑 6
- 失败告警（连续 N 轮抓取失败 → 推一条告警到群）
- 多账号支持（帮室友一起看）
- 每晚固定汇总（不只是增量推送）

---

## 6. 已知风险与注意事项

| 风险 | 说明 | 缓解 |
|---|---|---|
| **CAS 登录限流** | 短时间多次登录返回 401，严重时可能临时锁定 | 会话复用 + MIN_RELOGIN_GAP_SECONDS=300 退避 |
| **接口结构变更** | 学校改版后 api.js 路径/字段可能变 | 代码里留了清晰的常量与错误信息，便于快速定位 |
| **首次运行刷屏** | 不建基线就直接跑会把 34 条历史全推出去 | 先跑 --baseline；脚本本身也有首次自动基线保护 |
| **个人数据** | data/ 下含学号、宿舍号、查寝记录 | 对外分享前先清理 |
| **凭据** | 已确认工作区无明文密码，全部走环境变量 | 保持这个约定 |

### 与查寝项目无关的内容
- _profile_backup/ ：DSH profile 配置备份（安装 dsh-chat-cost 插件前的快照）
- .dsh-cost/cost.jsonl ：DSH 插件生成的 token 费用日志
- dsh-chat-cost-dsh-0.2.0-compat.patch ：DSH 插件兼容补丁（已应用）

这些是 DSH 环境相关，不属于查寝项目，可自行取舍。

---

## 7. 交接清单

### 接手方需要自备
1. **学工系统账号密码**（当前账号 25110103112）
2. **QQ 机器人 AppID / AppSecret**（未创建，见 qqbot-create-guide.md）
3. **目标 QQ 群**（并把机器人拉进去）
4. 部署目标服务器（如需容器化上线）

### 交接方已交付
- 全部源码（6 个 Python 文件，零第三方依赖）
- 全部技术文档（4 份）
- 全量数据样本（34 条，2025-10-13 ~ 2026-10-15）
- 已验证的完整链路（登录 → 采集 → 增量 → 消息格式）
- 同步状态文件（含 34 条基线 WID）

### 建议的接手动作（按顺序）
1. 读 ssws-flow-review.md 建立全局认知
2. 跑 sync_qqbot.py --selftest 确认环境
3. 跑 export_ssws.py 确认能拉到数据
4. 按 qqbot-create-guide.md 创建机器人
5. 接 P5，然后进 P6 容器化

---

## 8. 参考

- 学工系统：https://xgfw.sdut.edu.cn/xsfw/sys/swmsswsapp/*default/index.do
- 认证服务器：https://authserver.sdut.edu.cn/authserver/
- QQ 机器人官方文档：https://bot.q.qq.com/wiki/develop/api-v2/
- 本地文档存档：qqbot-docs-raw.md

---

*本文档由 DSH 会话生成，覆盖截至 2026-10-17 的全部进展。*
