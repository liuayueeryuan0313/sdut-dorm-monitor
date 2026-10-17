# 查寝监测项目 · 接手入口

此文件为旧 CLI 操作归档。由于所有群通知现要求原生 @全体，旧官方 QQ 群聊发送已停用；请使用当前 [WebUI OneBot 通道](README.md)。

本目录是 2026-10-17 从原交接包整理出的接手副本。先阅读 [接手验收报告](ACCEPTANCE.md)，再参考原始 [交接说明](HANDOVER.md) 与 [链路复盘](ssws-flow-review.md)。原文中的历史验证结论不等于本次已联网复验。

## 当前状态

- 已恢复全部 6 个业务 Python 文件、6 份原始文档，以及 34 条数据与对应基线。
- 11 项离线验收测试通过；WebSocket 帧编解码自检通过。
- 已修复试跑消耗待推送记录、自检输出凭据前缀、采集群 ID 时缺少数据目录的问题。
- 学校登录、角色引导、实时采集、日期筛选及同会话复用已联网验收通过：全量 34 条，近 45 天 4 条，新增 0 条。见 `verification-live.json`。QQ 鉴权与目标群推送仍待机器人创建；凭据仅用于单次验证，未保存。
- 已补本地交互启动脚本及 Docker 部署文件；镜像构建、容器启动与服务器部署尚未验证。

## 接下来从这里操作

最新步骤见 [开始联调](NEXT_STEPS.md)。可直接在 PowerShell 运行 `start.ps1 -Mode school-preview`，按提示在本机输入学校账号和密码；机器人尚未创建时也能先验证学校采集。

## 本机运行

在 PowerShell 中先切换到本目录。代码的 `data/` 路径相对当前工作目录解析，务必从本目录启动，保留随包的 `data/sync_state.json`。

```powershell
Set-Location 'C:\Users\liuay\Documents\Codex\2026-10-17\wo\outputs\ssws-monitor'
$python = 'C:\Users\liuay\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONUTF8 = '1'
& $python sync_qqbot.py --selftest
& $python get_group_openid.py --selftest
& $python -m unittest -v test_handover
```

本机已验证该 Python 为 3.12.14。换机器后替换解释器路径即可；业务代码只依赖标准库。在受限运行环境中若系统临时目录不可写，可把 `TMP`、`TEMP` 指向一个已创建且可写的临时目录后运行验收测试。

## 配置与后续联调

配置参考 `.env.example`。脚本不会自动读取 `.env`；须在启动进程中设置环境变量。

| 变量 | 用途 |
| --- | --- |
| `SDUT_USER` / `SDUT_PWD` | 本人学校账号及密码 |
| `QQ_APPID` / `QQ_SECRET` | 自己创建的 QQ 机器人凭据 |
| `QQ_GROUP_OPENID` | 已加入机器人的目标群标识，不能用普通群号代替 |
| `POLL_INTERVAL_MINUTES` | 默认 15 分钟 |
| `LOOKBACK_DAYS` | 默认回溯 45 天 |

密码和密钥请在本机配置，不需要发到聊天中。接通步骤为：

1. 配置学校账号后，运行 `& $python sync_qqbot.py --dry-run`，验收实时抓取。该操作会联网，但不发 QQ、不修改增量状态；预览仍会写本地日志。
2. 在 QQ 开放平台创建机器人、配置群事件订阅并加入目标群；配置 `QQ_APPID`、`QQ_SECRET` 后运行 `& $python get_group_openid.py`，在目标群手动 @ 机器人以获取群标识。
3. 配置 `QQ_GROUP_OPENID`。本次保留原有 34 条已读基线；若希望把接手期间的新记录也全部标为已读，可自行运行 `--baseline`，其行为会消耗当前未读记录。
4. 获得一次真实测试消息发送的明确授权后，验收群推送，再启动 `& $python sync_qqbot.py` 常驻监测。`--once` 遇到新记录会真实发送消息；没有新记录时不会发送，不能据此判定推送已验证。
5. 联调通过后补 Docker 持久化目录、时区、健康检查和服务器托管，再观察实际运行稳定性。

同时运行多个实例会竞争同一个状态文件，目前只支持单实例。

`data/` 含个人记录，已加入 `.gitignore`。此目录和接手 ZIP 供私人交接使用；不要直接作为公开仓库或公开下载包。
