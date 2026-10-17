# QQ 机器人 (QQBot) 接入配置速查

> 来源: [bot.q.qq.com/wiki/develop/api-v2](https://bot.q.qq.com/wiki/develop/api-v2/)
> 原始抓取存档: qqbot-docs-raw.md (39 KB) · 整理时间 2026-10-17

---

## 1. 管理端配置（QQ 开放平台）

| 步骤 | 位置 | 要点 |
|---|---|---|
| 注册 | QQ 开放平台 | QQ 账号 或 邮箱注册 |
| 主体认证 | 开发者管理端 | 个人 / 企业(个体户)，权限不同 |
| 创建机器人 | 机器人管理端 | 个人 5 个，企业 10 个（同主体上限 50） |
| 服务范围 | 机器人管理页 | 未认证=仅管理员；个人认证=公开，进群上限 **500**；企业认证=全场景 |
| 隐私协议 | 机器人管理页 | 必填 |

### 开发设置（核心配置区）

| 项 | 说明 |
|---|---|
| AppID / AppSecret | 接入票据。**AppSecret = Bot Secret**，同时用于 Ed25519 签名种子 |
| 事件订阅与回调方式 | **WebSocket / Webhook 二选一，切换立即生效** |
| 服务器 IP 白名单 | **仅支持单个 IPv4，不支持 CIDR**，最多 50 条；不设置 = 全部放行 |
| 内部体验号码 | 最多 20 个，不受服务范围限制 |

- **WebSocket**：不依赖公网服务器，适合个人/单机，需维护长连接
- **Webhook**：需公网 HTTPS 服务，适合对外服务的机器人

---

## 2. 凭证体系

| 凭证 | 获取方式 | 用途 |
|---|---|---|
| AppID | 管理端 | 机器人 ID |
| AppSecret | 管理端 | 换 access_token / 回调签名 |
| **access_token** | `POST https://api.bot.qq.com/app/getAppAccessToken` | OpenAPI 鉴权 |
| Token（已废弃） | — | 旧鉴权方式，勿用 |

**换取 access_token**

```bash
curl --location 'https://api.bot.qq.com/app/getAppAccessToken' \
--header 'Content-Type: application/json' \
--data '{"appId":"APPID","clientSecret":"CLIENTSECRET"}'
```

```json
{"access_token":"ACCESS_TOKEN","expires_in":"7200"}
```

**有效期规则**
- 默认 **7200 秒**（2 小时）
- 有效期内重复获取返回**同一个值**，不会自动续期
- 到期前 **60 秒内**获取会拿到新 token，老 token 这 60 秒内仍有效
- 服务端需自建定时刷新

**调用 OpenAPI**

```
统一入口: https://api.bot.qq.com
请求头:   Authorization: QQBot {ACCESS_TOKEN}
```

> ⚠️ 业务错误通过响应体 `code`/`err_code` 返回，**HTTP 可能仍是 200**。判断成败只看错误码，别看 message。
> 常见：100007 appid invalid / 100016 invalid appid or secret / 100001 Too many requests

---

## 3. 事件接入：WebSocket

```
1. GET /gateway            → {"url":"wss://api.bot.qq.com/websocket/"}
   GET /gateway/bot        → 额外返回 shards + session_start_limit
2. 连 wss://api.bot.qq.com/websocket/   → 收 op 10 Hello
3. 发 op 2 Identify
4. 收 op 0 t=READY (含 session_id)
5. 周期发 op 1 Heartbeat → 收 op 11 Heartbeat ACK
6. 断线重连发 op 6 Resume → 补发事件后收 RESUMED
```

**op 10 Hello**
```json
{"op":10,"d":{"heartbeat_interval":45000}}
```

**op 2 Identify**
```json
{"op":2,"d":{
  "token":"QQBot {AccessToken}",
  "intents":513,
  "shard":[0,1],
  "properties":{"$os":"linux","$browser":"my_library","$device":"my_library"}
}}
```

**op 0 READY**
```json
{"op":0,"s":1,"t":"READY","d":{"version":1,"session_id":"...","user":{"id":"...","username":"...","bot":true},"shard":[0,0]}}
```

**op 1 Heartbeat**（d = 最新 s，首连传 null）
```json
{"op":1,"d":251}
```

**op 6 Resume**
```json
{"op":6,"d":{"token":"...","session_id":"...","seq":1337}}
```

**分片**：`shard_id = (guild_id >> 22) % num_shards`；不分片用 `[0,1]`。
每个 bot 的连接数不能超过 `session_start_limit.remaining`。

---

## 4. 事件接入：Webhook

- 回调地址**只允许端口 80 / 443 / 8080 / 8443**，必须 HTTPS
- 配置后平台先验证地址：推 `op 13`，`d = {plain_token, event_ts}`

**验证签名（Ed25519）**

```go
seed := botSecret
for len(seed) < ed25519.SeedSize { seed = strings.Repeat(seed, 2) }
seed = seed[:ed25519.SeedSize]
_, privateKey, _ := ed25519.GenerateKey(strings.NewReader(seed))

msg := eventTs + plainToken
signature := hex.EncodeToString(ed25519.Sign(privateKey, []byte(msg)))
// 返回 {"plain_token": "...", "signature": "..."}
```

**每次回调验签**
- Header：`X-Signature-Ed25519`（hex，64 字节）、`X-Signature-Timestamp`
- 用同一 seed 推出 **publicKey**，验签体 = `timestamp + raw_body`
- 请求头特征：`User-Agent: QQBot-Callback`、`X-Bot-Appid`
- 收到后回 `op 12` 表示已接收

---

## 5. Intents 位掩码

| 位 | 常量 | 值 | 事件 |
|---|---|---|---|
| 0 | GUILDS | 1 | GUILD/CHANNEL 增删改 |
| 1 | GUILD_MEMBERS | 2 | 成员增删改 |
| 9 | GUILD_MESSAGES | 512 | 频道全量消息（**仅私域**） |
| 10 | GUILD_MESSAGE_REACTIONS | 1024 | 表情表态 |
| 12 | DIRECT_MESSAGE | 4096 | 频道私信 |
| **25** | **GROUP_AND_C2C_EVENT** | **33554432** | **C2C_MESSAGE_CREATE / FRIEND_ADD / FRIEND_DEL / C2C_MSG_REJECT / C2C_MSG_RECEIVE / GROUP_AT_MESSAGE_CREATE / GROUP_ADD_ROBOT / GROUP_DEL_ROBOT / GROUP_MSG_REJECT / GROUP_MSG_RECEIVE** |
| 26 | INTERACTION | 67108864 | 互动事件 |
| 27 | MESSAGE_AUDIT | 134217728 | 消息审核通过/拒绝 |
| 28 | FORUMS_EVENT | 268435456 | 论坛（**仅私域**） |
| 29 | AUDIO_ACTION | 536870912 | 上麦/下麦/音频播放 |
| 30 | PUBLIC_GUILD_MESSAGES | 1073741824 | AT_MESSAGE_CREATE（公域 @） |

- 多事件用**按位或**：`0 | 1<<30 | 1<<1`
- **免申请基础权限**：GUILDS、PUBLIC_GUILD_MESSAGES、GUILD_MEMBERS
- 其他特殊事件需申请；**订阅无权限的 intents 会导致 WebSocket 直接报错断开**
- 权限被取消：当前连接不报错但收不到事件，重连才报错

> 群里被 @ → `GROUP_AT_MESSAGE_CREATE`；单聊 → `C2C_MESSAGE_CREATE`，二者同属 **1<<25**。

---

## 6. opcode 全表

| CODE | 名称 | 接入方式 | 行为 |
|---|---|---|---|
| 0 | Dispatch | webhook/websocket | Receive |
| 1 | Heartbeat | websocket | Send/Receive |
| 2 | Identify | websocket | Send |
| 6 | Resume | websocket | Send |
| 7 | Reconnect | websocket | Receive |
| 9 | Invalid Session | websocket | Receive |
| 10 | Hello | websocket | Receive |
| 11 | Heartbeat ACK | websocket | Receive/Reply |
| 12 | HTTP Callback ACK | webhook | Reply |
| 13 | 回调地址验证 | webhook | Receive |

**通用 payload 结构**
```json
{"id":"event_id","op":0,"d":{},"s":42,"t":"GATEWAY_EVENT_NAME"}
```

---

## 7. 消息收发

| msg_type | 类型 | 字段 | 发送 | 接收 |
|---|---|---|---|---|
| 0 | 文本 | content | ✅ | ✅ |
| 2 | Markdown | markdown | ✅ | - |
| 7 | 富媒体 | media.file_info | ✅ | ✅ |

- **富媒体**：先上传拿 `file_info`（分片上传推荐，或用单聊/群聊整文件上传），`file_info` 有 ttl；**单聊与群聊上传接口不互通**
- **去重**：同一 `msg_id` 可能多次推送，用 `msg_seq` 去重；相同 `msg_id + msg_seq` 重复发送会失败，递增 seq 可多次回复

**被动消息时效**

| 场景 | 有效期 | 可回复次数 |
|---|---|---|
| 单聊 | 60 分钟 | 4 |
| 群聊 | 5 分钟 | 5 |
| 频道 | 5 分钟 | - |

**主动消息频控**

| 认证 | 场景 | Bot 维度 | 单关系维度 | 每日上限 |
|---|---|---|---|---|
| 企业 | 单聊 | 10/qps | 20/qpm | 1000 条/用户 |
| 个人 | 单聊 | 10/qps | 20/qpm | 1000 条/用户 |
| 未认证 | 单聊 | 5/qps & 30/qpm | 20/qpm | 1000 条/用户 |
| 企业/个人 | 群 | 60/qpm | 20/qpm | 1000 条/群 |
| 未认证 | 群 | 30/qpm | 20/qpm | 1000 条/群 |

- 频道：默认每天每子频道 20 条，每天最多 2 个子频道；每子频道 **5 条/秒**
- 频道私信：每 bot 每天对单用户 2 条，累计 200 条
- **互动召回消息**（`is_wakeup:true`）：用户对话后 30 天内，每个周期可发 1 条；周期 = 当天 / 1-3 天 / 3-7 天 / 7-30 天，共 4 条
- **撤回**：只能撤回自己发的，且**超过 2 分钟不可撤回**

---

## 8. WebSocket 错误码

| code | 含义 | RESUME 重试 | IDENTIFY 重试 |
|---|---|---|---|
| 4001 | 无效 opcode | 否 | 否 |
| 4002 | 无效 payload | 否 | 否 |
| 4006 | 无效 session id | 否 | 是 |
| 4007 | seq 错误 | 否 | 是 |
| 4008 | payload 过快 | 是 | 是 |
| 4009 | 连接过期 | 是 | 是 |
| 4010 | 无效 shard | 否 | 否 |
| 4011 | 处理的 guild 过多 | 否 | 否 |
| 4012 | 无效 version | 否 | 否 |
| 4013 | 无效 intent | 否 | 否 |
| 4014 | intent 无权限 | 否 | 否 |
| 4900~4913 | 内部错误 | 否 | 是 |
| 4914 | 机器人已下架，仅沙箱 | 否 | 否 |
| 4915 | 机器人已封禁 | 否 | 否 |

处理策略：4009 重新 resume；4914/4915 不可连；其他重新 identify。

---

## 9. 最小可用接入流程

```
① 开放平台建机器人 → 取 AppID + AppSecret
② 开发设置 → 选 WebSocket（本地/个人）或 Webhook（公网 HTTPS）
   · Webhook 需先处理 op13 地址验证（Ed25519 签名回包）
   · 建议配置 IP 白名单
③ POST /app/getAppAccessToken → access_token（7200s）
④ 建立事件通道
   · WS: GET /gateway → 连 wss → op2 Identify(intents 按需)
   · Webhook: 平台推送 + 每次 Ed25519 验签 + 回 op12
⑤ 收事件 → 回复
   · 群: POST /v2/groups/{group_openid}/messages
   · 单聊: POST /v2/users/{user_openid}/messages
   · 携带 msg_id/event_id 走被动回复（免主动消息频控）
```

## 10. 常量速记

```
AccessToken : POST https://api.bot.qq.com/app/getAppAccessToken
OpenAPI     : https://api.bot.qq.com
WSS 入口    : GET  https://api.bot.qq.com/gateway  (或 /gateway/bot)
WS  地址    : wss://api.bot.qq.com/websocket/
鉴权头      : Authorization: QQBot {ACCESS_TOKEN}
回调端口    : 80 / 443 / 8080 / 8443
Token 格式  : "QQBot {AccessToken}"
```

## 11. 身份唯一性

不同 bot(AppID) 拿到的 openid 完全不同：
- `user_openid` — 单聊场景用户标识
- `group_openid` — 群标识
- `member_openid` — 用户在群内的标识

跨 bot 关联用户需等平台提供 unionid 类机制。

## 12. 全链路追踪

- HTTP 响应头 `X-Tps-trace-ID`
- 响应体 `trace_id`

提工单时带上该 ID。

## 13. SDK

- Go: [botgo](https://github.com/tencent-connect/botgo)
- Python: [botpy](https://github.com/tencent-connect/botpy)
- Node.js: bot-node-sdk
