# 小组件持久化接口

## 使用

1. 更新代码、备份原 data/ 目录后执行 `docker compose up -d --build monitor`，保留原 data 挂载。仅 restart 或继续拉取尚未更新的 Docker Hub 镜像不会包含本功能。
2. 登录管理网页，先保存学校账号。在“连接与计划”下方找到“小组件接口”，点击“生成 / 轮换 Token”。
3. 将页面的接口地址和新 Token 填入组件。Token 仅本次生成时返回，刷新后无法找回；再次轮换会使旧 Token 立即失效。可点击“显示 / 隐藏”核对，或“撤销 Token”停止访问。
4. 组件请求 `GET https://你的域名/api/widget/v1/dorm`，请求头为 `Authorization: Bearer 专用Token`，不发送管理密码或学校密码，不使用查询字符串传 Token。
5. 更新后成功采集一次电量，生成持久化快照。读取接口不执行采集，更新频率取决于项目原采集计划。圆环最大电量由手机端手动保存，服务端不提供或假设最大值。

手机需要实际可达的 HTTPS 地址。页面显示的是当前打开网站的来源地址；若浏览器通过 localhost 访问，不能直接把这个 localhost 给手机使用。使用已有反向代理与 HTTPS，给原 `WEBUI_ALLOWED_HOSTS` 添加实际域名，保留登录、Host、同源、CSRF 校验。此次没有配置外网域名或改动运行中的容器。

## 持久化与隔离

- `data/webui_widget_token.json`：只存随机 Token 的 SHA-256 哈希、账号绑定键与创建时间，Linux 权限 600。原始 Token 不写文件或日志。
- `data/webui_widget_electricity.json`：成功电量白名单与账号/宿舍绑定摘要；不保存学校密码、机器人 Token、Cookie 或原始 HTML。与 Token 文件一样使用同目录临时文件、fsync、原子替换。
- 查寝继续使用原 `webui_records.json`；保留同一个 data/ 挂载即可跨进程或容器重启恢复。
- 电量查询中或失败时仍可读取上次成功快照，并返回 stale；重启恢复的快照也标记 stale。checkedAt 为实际采集时间，非接口访问时间。
- 更换账号或宿舍时清空旧电量快照；Token 绑定账号，不可读其他账号。轮换或撤销会使对应旧 Token 立即失效。
- 没有记录、余额缺失或非法时返回 null，不伪造 0。真实 0 电量保留。接口仅白名单输出，不开放管理权限。

完整字段及错误码见 [WIDGET_API.md](WIDGET_API.md)。接口永久路径为 `/api/widget/v1/dorm`；Token 无自动到期时间，但可轮换、撤销。

## 无网页时的本机管理

```sh
docker compose exec monitor python widget_token.py rotate
docker compose exec monitor python widget_token.py status
docker compose exec monitor python widget_token.py revoke
```

rotate 输出中包含真实 Token，只在私有本机终端执行，不贴进聊天、Git 或公开日志。status 不返回原 Token。CLI 与网页使用同一持久化文件。

## 验证

```sh
python -m unittest discover -q
node --check web/app.js
```

本次使用临时数据、模拟学校/QQ 与本地 HTTP 测试。未调用真实学校、未发送群通知，未创建正式 Token，未重建运行中的容器。本地浏览器访问在应用设置中被关闭，因此本轮未完成视觉浏览器验收。
