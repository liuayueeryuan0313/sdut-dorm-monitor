# 查寝 / 电量小组件接口 v1

对应包内代码和 `example-response.json`，示例为虚构数据。JSON 使用 UTF-8，响应为 `Cache-Control: no-store`。该项目是单学校账号监控服务，专用 Token 绑定当前学校账号。

## 读取摘要

```http
GET /api/widget/v1/dorm
Authorization: Bearer <本服务的 dw_ 专用 Token>
Accept: application/json
```

仅 GET，不接受查询参数。无需管理 Cookie、CSRF 或学校密码。此请求只读本地记录、最近成功电量快照，不触发学校采集、不发送 QQ 消息、不改变监控开关。

| 顶层字段 | 类型 | 含义 |
| --- | --- | --- |
| schemaVersion | integer | 固定 1 |
| generatedAt | string | UTC ISO 8601，此次响应生成时间，不代表学校采集时间 |
| timezone | string | 固定 Asia/Shanghai |
| inspection | object/null | 按检查日期取最近一条记录；同日期按 WID 排序；没有记录时 null |
| electricity | object | 最近已知电量及状态 |
| monitor | object | 后台运行状态摘要 |

### inspection

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| date | string/null | 原 JCRQ 检查日期 |
| score | number/null | 原 FS，缺失、空值或非法数字为 null；真实 0 仍返回 0 |
| level | string/null | 原 DJMC 等级 |
| building | string/null | 原 SSLMC 宿舍楼 |
| room | string/null | 原 FJH 房间号 |
| checkType | string/null | 原 JCLXDM_DISPLAY 检查类型 |

不拼造满分、百分比或评分。左侧小组件显示 date、score、level 即可；无成绩显示“—”，无记录显示“暂无查寝记录”。不返回检查人、学生标识、后台原始记录或登录凭证。

### electricity

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| remainingKwh | number/null | 剩余度数；空值、非法数字或负值为 null；真实 0 保留 |
| unit | string | 固定 kWh |
| checkedAt | string/null | 原采集时间 checked_at，不改写为接口访问时间 |
| campus、building、floor、room、type | string/null | 原电量结果中的查询对象；type 来自 electricity_type |
| stale | boolean | 后台电量查询有错误、快照从磁盘恢复、或读取历史快照时为 true |
| state | string | error：电量查询出错；ok：有合法电量且无查询错误；unavailable：无合法电量 |

`stale` 是已知缓存状态，不是按固定时长自动过期。手机应另据 checkedAt 显示上次更新时间。重启后的历史成功值可能是 `state:ok, stale:true`；查询失败但有历史值时是 `state:error, stale:true` 且仍返回历史剩余电量。查寝采集错误与电量错误可能独立，另看 monitor.hasError。

接口没有 `maxKwh`。用户在手机端手动填写并保存大于零的最大电量，圆环比例为 `min(1,max(0,remainingKwh/maxKwh))`。分母缺失时要求配置，剩余值缺失时显示“—”；不把金额当度数，不反推电价。

### monitor

`running` 是 config.enabled 监控开关，`collecting` 表示目前有采集任务，`lastSuccess` 为原监控最近成功时间，`hasError` 为是否有采集错误。它不是实时学校在线状态，也不包含原始异常详情。

## Token 管理

仅原管理网页登录后使用，保留原 Host、同源和 CSRF 校验。

| 方法和路径 | 请求 | 响应 |
| --- | --- | --- |
| GET /api/widget/token | 原登录 Cookie | configured、createdAt、scope、expiresAt；不返回原 Token |
| POST /api/widget/token | Cookie + X-CSRF-Token + JSON `{"action":"rotate"}` | 新 token、createdAt、scope、expiresAt |
| POST /api/widget/token | Cookie + X-CSRF-Token + JSON `{"action":"revoke"}` | `{"configured":false}` |

POST 带 `Content-Type: application/json` 并保持原同源 Origin。scope 固定 `dorm-electricity:read`，expiresAt 为 null。只有一个专用 Token，rotate 替换旧 Token，多个手机需要一起更新。原始 Token 只在生成时返回，文件仅存 SHA-256 哈希，Linux 权限 600。

Token 绑定学校账号；配置切换到不同账号时旧 Token 不能查询。更换宿舍后旧电量快照不再返回，但同账号 Token 无需轮换。Token、成功电量均保存在原 data/，沿用原数据挂载即可跨重启保留。首次升级后须成功采集一次电量生成快照；Token CLI 见 WIDGET_SETUP.md。

## 错误与手机缓存

错误响应为 `{"error":"中文原因"}`。401：Token 缺失、错误、撤销或账号不匹配；400：带了查询参数；421：原 WEBUI_ALLOWED_HOSTS 未允许访问域名，需配置原部署而非删除校验。404 通常表示服务尚未升级。

无记录或电量查询失败仍可能返回 200，应看业务状态与 null。手机离线或服务失败时保留上次成功响应并标记缓存时间；401 提示更新凭证。建议 15–30 分钟后请求刷新，实际刷新时机由 iOS 决定；频繁读取不会加快服务端采集。界面固定深色，沿用原项目深色玻璃和青色高光。
