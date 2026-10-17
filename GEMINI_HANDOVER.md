# Gemini 项目交接 · 2026-10-17

## 当前目标与边界

这是山东理工大学宿舍管理工具，用户希望尽量简单，在网页配置学校账号、查寝刷新计划、群通知、月度网费提醒，以及新增的宿舍电量查询。用户将自行把本项目交给 Gemini 继续修改并部署。本轮只完成源代码与本地验证，没有修改 Dockerfile/.dockerignore，没有重建或重启现有容器。

交接包不含学校密码、QQ 密钥、管理密码、Cookie、实际运行配置、私人查寝记录。账号密码由用户在网页填写，不要向聊天中索要明文密码。

## 已实现

- 查寝：统一认证，读取本人检查记录；自定义 1–10080 分钟间隔；手动采集；启动/停止；首次自动采集只建基线；手动预览不消耗待推送记录。
- 电量：在“最近查寝记录”下方和侧栏新增“宿舍电量”，校区、楼栋、楼层、房间、类型均可编辑。默认西校区 / 26号北楼 / 8 / 814 / 照明插座。复用上方学校账号。
- 电量手动：保存并查询，在后台执行，前端每 4 秒读取状态。显示剩余度数、房间、读取时间、明确提供的人民币余额；没有金额时显示“人民币余额未提供”。
- 电量自动：独立开关及 5–10080 分钟间隔（支持小数，默认 60）；不依赖查寝监测开关。计划持久化，完成一次查询后再等待所设间隔；重启后已开启计划在约 5 秒后查询。学校与电量查询互斥；手动查询也至少间隔 5 分钟。
- 电量认证受阻：出现验证码、CAS 拒绝等 LoginBlocked 时关闭电量自动查询，需用户处理后重新开启；普通网络错误按计划下次再查。电量结果目前仅在内存，重启后清空，保持简单。
- 月度网费：独立开关、日期与北京时间、人数、每人金额、Decimal 总额，通知前往微信宿舍群转账；短月份按最后一天，成功后按月/群去重；不执行转账。
- QQ：免费 OneBot 11 HTTP 通道，所有实际群通知强制原生 @全体，先检查权限/额度，失败不降级成普通文字。未安装或登录实际 QQ 客户端，未做真实群发送。官方 QQ 普通群 API 不能满足 @全体，旧发送已禁用。
- 管理：首次设置管理密码、scrypt、HttpOnly SameSite Cookie、CSRF、Origin/Host 校验、秘密字段不回显。配置在本机 data/ 中明文存储学校与机器人凭据（Linux 0600），迁移时仅由用户在私有环境操作。

电量自动查询只更新网页，不推送 QQ；用户没有要求电量推送阈值、充值、历史图表或额外收费服务，不必扩展。

## 重要文件

| 文件 | 职责 |
| --- | --- |
| webui.py | HTTP API、登录保护、查寝/电量/网费调度及配置 |
| web/index.html, app.js, style.css | 原生网页，电量区位于查寝记录下方 |
| sdut_electricity.py | 电费 WebForms 五级选择、CAS 回调、结果解析、CLI |
| sdut_login.py, aes_tool.py | 已验证 CAS 与纯 Python AES-128-CBC |
| sdut_ssws.py | 查寝读取 |
| notifications.py | OneBot HTTP 与原生 at-all，禁止跳转与权限降级 |
| reminders.py | 月度日期、Decimal 金额与提醒文案 |
| sync_qqbot.py | 原查寝同步及格式化，旧官方发送已禁用 |
| test_*.py | 5 组单元/HTTP/调度测试，远端请求均为模拟 |
| ELECTRICITY.md | 电量函数、CLI、真实表单差异与返回值 |
| Dockerfile, compose.yaml, .dockerignore | 旧版本已验证部署配置；本轮电量模块待加入 |
| verification-electricity.json | 2026-10-17 的真实查询结果，不含凭据 |

API：`POST /api/electricity-config` 保存电量计划，`POST /api/electricity` 保存并查询。两者接收 elc_campus、elc_building、elc_floor、elc_room、elc_type、elc_enabled（布尔）、elc_minutes（数字），需当前会话与 X-CSRF-Token。`GET /api/status` 的 electricity 返回 busy/result/error/next_due，next_due 为 Unix 秒。

## 已验证事实

学校实测：西校区 26号北楼 814，2026-10-17 19:59:34 +08:00，剩余 **74.62 kWh**；页面注明每小时更新，未提供人民币余额或已用电量，分别返回 null 与空字典，禁止用假定电价换算。内部楼栋 476、房间 25961 仅为当次读取，代码动态匹配，不硬编码。

真实单选回发目标为 `RadioButtonList2$0` 等子控件。每次响应重新读取全部隐藏状态（包括分段 VIEWSTATE），CAS 后重新选择，不能复用登录前的 VIEWSTATE。CAS 使用页面 16 字节 salt、随机前缀/IV 的既有实现，不能采用交接材料中猜测的固定 IV 或任意截断 salt。

原工作目录 Windows 全部 **94 项测试通过**。干净交接包不含私人历史数据，`test_handover` 中 1 项历史数据验收自动跳过，其余测试可运行。电量网页已使用模拟的 12.34 度验证“手动查询 + 自动开关 + 30 分钟计划 + 下次查询时间”，模拟值不是真实余额；真实登录查询已在上一轮验证，本轮不重复登录学校。

旧查寝/提醒版本此前 68 项测试在 Docker Linux 通过，旧容器构建/健康检查通过；这不代表本轮新增电量功能已经在 Docker 部署或测试。

## 本地继续开发

Python 3.10+，推荐 3.12，零 pip 依赖。在本目录：

```powershell
python -m unittest -q test_webui test_handover test_reminders test_electricity test_electricity_webui
python webui.py --port 8788
```

打开 http://127.0.0.1:8788，首次创建管理密码，再填写学校账号。8788 用于避免和用户旧 Docker 的 8787 冲突。data/ 首次启动自动生成。电量区“保存电量计划”不会立刻查询，“保存并查询电量”会立即查询一次；启用自动查询后再按间隔运行。

## 交给 Gemini 的下一步

1. 阅读本文件与 ELECTRICITY.md，保留用户要求的简单界面，继续用户提出的修改。
2. 准备部署时，在 Dockerfile 的 COPY 列表加入 `sdut_electricity.py`，并在 .dockerignore 增加 `!sdut_electricity.py`。当前采用延迟导入，旧镜像仍能使用查寝，但电量查询会因镜像缺少模块而失败；必须先补齐。
3. 运行上述测试，再构建镜像并验证 Linux 与网页。容器内真实学校访问需要可用网络，不能把“容器健康”当作“学校或 QQ 连接成功”。
4. 如要迁移现有数据，由用户私下备份旧目录 data/，恢复时保留 webui_config.json、webui_admin.json、webui_state_*.json、webui_fee_state.json、webui_records.json。不要把它们上传给模型或覆盖掉月度去重状态。
5. OneBot 服务与 QQ 登录尚需用户准备。没有服务时只启用查询，关闭实际群推送和网费提醒；不要接入收费服务。需要通知时始终原生 @全体。

用户此前遇过 Docker Desktop 的 sailor-ingest.sock 无法访问，已通过 Docker 停止后备份整个本地 run 目录并重建解决。现在不要重复清理 Docker 数据或卷；只有故障实际复现时再诊断。
