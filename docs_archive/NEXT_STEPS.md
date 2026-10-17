# 从这里开始联调

**最新入口已升级为 Docker WebUI，直接阅读 [README.md](README.md) 并打开 http://127.0.0.1:8787。以下内容保留为先前命令行联调记录，旧 Docker 准备状态不再代表当前版本。**

2026-10-17 检查结果：学校与 QQ 的 5 项配置在当前进程、用户级与系统级环境变量中均不存在；用户确认尚未创建 QQ 机器人。Docker CLI 已安装，但 Linux 容器引擎没有运行。

后续进度（2026-10-17 00:55，Asia/Shanghai）：经用户提供账号并授权，学校在线采集已验证通过。单次登录及角色引导成功，同一会话拉取全量 34 条、近 45 天 4 条，日期筛选核对一致，新增 0 条；34 条基线未修改，未发送 QQ 消息。结果见 `verification-live.json`。账号密码只用于该次进程，未写入配置文件。下一步是创建 QQ 机器人并加入目标群，学校预览无需重复执行。

## 现在可以做：学校采集预览

在本机交互式 PowerShell 中执行：

```powershell
& 'C:\Users\liuay\Documents\Codex\2026-10-17\wo\outputs\ssws-monitor\start.ps1' -Mode school-preview
```

启动脚本会自动切换到项目目录，提示输入 `SDUT_USER` 与 `SDUT_PWD`。密码隐藏输入，不保存到磁盘；退出后恢复当前进程原来的环境变量。这个模式只采集并预览，不发群消息、不修改 34 条已读基线。若系统阻止执行脚本，先按 README 手动切换到目录并用 Python 启动；无需改变机器的执行策略。

不需要学校账号的离线检查：

```powershell
& 'C:\Users\liuay\Documents\Codex\2026-10-17\wo\outputs\ssws-monitor\start.ps1' -Mode selftest
```

## 并行准备：创建 QQ 机器人

1. 打开 [QQ 开放平台](https://q.qq.com/)，用你自己的 QQ 登录并按平台要求注册开发者、创建机器人。账号实名、扫码、验证码需要你本人完成。
2. 在机器人管理页面取得 AppID 和 AppSecret，保存在本机。参考项目 `qqbot-create-guide.md` 完成机器人设置；可选项、认证及额度以你的管理后台为准。
3. 在事件订阅设置中启用所需群事件并选择可用的 WebSocket 接入方式。当前官方站点仍提供 [WebSocket 接入流程](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/websocket.html)。
4. 按后台提供的沙箱或发布流程把机器人加入目标群。
5. 运行下面的采集脚本，按提示输入 QQ_APPID、QQ_SECRET，然后在目标群 @ 一次机器人。群标识会保存到项目 `data/group_openid.json`，不是普通 QQ 群号。

```powershell
& 'C:\Users\liuay\Documents\Codex\2026-10-17\wo\outputs\ssws-monitor\start.ps1' -Mode capture-group
```

完成后告诉我“机器人已创建并加入群，学校预览已通过”，即可继续校验群标识与真实推送。AppSecret 和学校密码不用发给我。

`once` 与 `run` 模式会向已配置群发送新记录，启动前须确认目标群与发送意图；`baseline` 会把当前新记录标为已读。创建机器人阶段无需运行这三个模式。

## 已准备：Docker 部署文件

本目录已提供 `Dockerfile`、`compose.yaml` 和 `.dockerignore`，镜像仅复制 6 个业务源码，不带账号、历史数据或其他交接资料；`./data` 挂载保存基线、日志和群标识。不开放入站端口，时区为 Asia/Shanghai。配置缺失时 Compose 会直接提示缺少项。

启动 Docker Desktop 并确保 Linux 容器引擎可用后，从项目目录构建：

```powershell
docker compose build
```

在本机环境变量配置好全部凭据后，也可通过项目目录下的本地 `.env` 配置 Compose；参考 `.env.example` 填值。Compose 会读取该文件用于变量替换，原 Python 脚本与 start.ps1 不读取它。不要把实际 `.env` 加入交接包；[Docker 官方文档](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)说明了配置机制。

联调通过后使用：

```powershell
docker compose config --quiet
docker compose up -d
docker compose logs --tail 100 -f
docker compose stop
```

当前 Docker 文件是部署准备版：Compose 语法可在没有引擎的情况下验证，但本次没有构建镜像或启动容器。未提供业务健康检查，重启策略为不自动重启；现有业务循环仍会在普通异常后按轮询间隔继续运行。验证码/风控停机保护、健康状态与稳定性验收完成后，再配置自动重启和服务器托管。不要同时启动本机常驻脚本和容器。

本机日志 `data/sync.log` 尚无大小轮转；Compose 的日志轮转只限制 Docker 标准输出日志，长期运行前需补文件日志保留策略。
