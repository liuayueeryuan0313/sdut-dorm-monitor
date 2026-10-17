# QQ 机器人官方文档 · 原始抓取存档

> 来源: https://bot.q.qq.com/wiki/develop/api-v2/ · 抓取时间 2026-10-17

> 精炼版见 qqbot-config.md


======================================================================
## 启动接入
URL: https://bot.q.qq.com/wiki/develop/api-v2/

# # 启动接入

## # 账号注册

QQ 机器人：一个机器人可以被添加到 群聊/频道 内互动对话，QQ 用户也可以直接跟机器人 单独对话。

注册地址：QQ 开放平台官网  (opens new window)

## # 接入票据

注册创建机器人后：获得的开发机器人接入票据 AppID AppSecret

| 名称 | 描述 | 备注 |
|---|---|---|
| AppID | 机器人 ID | 必须使用 |
| AppSecret | 机器人密钥 | 用于在 oauth 场景进行请求签名的密钥 |
| Token(已弃用) | 机器人 Token | 可用于调用开放接口的鉴权。 |

Token 的鉴权方式已废弃，请使用更安全的 Access Token 鉴权方式。

开发过程中如遇任何问题，可联系 QQ 机器人反馈助手反馈。

## # SDK DEMO

快速搭建机器人服务端可参考以下 SDK DEMO。（SDK 仅提供接入参考，详情能力以官方文档能力描述为准）

Go: botgo  (opens new window)

Python: botpy  (opens new window)

NodeJs: bot-node-sdk  (opens new window)

======================================================================
## access-token
URL: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html

# # 获取访问凭证

QQ 机器人开放平台提供以下类型的访问凭证：

| 凭证类型 | 是否需要用户授权 | 说明 |
|---|---|---|
| access_token | 否 | 机器人身份调用 API 时使用的凭证，可读写的数据范围由机器人的权限范围决定。适用于机器人主动发消息、管理群聊等场景。 |

## # 获取 access_token

### # 请求

| 基本 |
|---|
| HTTP URL | https://api.bot.qq.com/app/getAppAccessToken |
| HTTP Method | POST |

### # 请求参数

| 属性 | 类型 | 必填 | 说明 |
|---|---|---|---|
| appId | string | 是 | 在开放平台管理端上获得。 |
| clientSecret | string | 是 | 在开放平台管理端上获得。 |

### # 返回参数

成功响应

| 属性 | 类型 | 说明 |
|---|---|---|
| access_token | string | 获取到的凭证。 |
| expires_in | number | 凭证有效时间，单位：秒。目前是 7200 秒之内的值。 |

失败响应

| 属性 | 类型 | 说明 |
|---|---|---|
| code | number | 错误码，取值见下方「业务错误码」。 |
| message | string | 错误信息，仅用于人工排查，内容可能随时调整。 |

注意 该接口的业务错误通过响应体的 code 返回，即使调用失败，HTTP 返回码仍为 200。请优先依据 code 判断请求是否成功，不要只依赖 HTTP 返回码；也不要依据 message 判定错误类型。详见下方「错误返回码」。

### # 错误码

#### # 业务错误码

| 错误码 | 错误信息 | 排查指南 |
|---|---|---|
| 100001 | Too many requests | 请求过于频繁，请降低调用频率后重试 |
| 100007 | appid invalid | AppID 无效，或机器人状态不正常（被封禁或已删除），请检查 AppID 是否正确以及机器人状态 |
| 100016 | invalid appid or secret | AppID 或 ClientSecret 不正确，请检查传入的 appId 和 clientSecret 是否与开放平台管理端一致 |
| 10004 | 机器人不存在 | AppID 对应的机器人不存在，请确认 AppID 是否正确 |

### # 调用示例

curl --location 'https://api.bot.qq.com/app/getAppAccessToken' \
--header 'Content-Type: application/json' \
--data '{
  "appId": "APPID",
  "clientSecret": "CLIENTSECRET"
}'
 123456

### # 返回示例

成功

{
  "access_token": "ACCESS_TOKEN",
  "expires_in": "7200"
}
 1234

失败

{
  "code": 100007,
  "message": "appid invalid"
}
 1234

## # 凭证有效期与刷新

目前 access_token 生命周期默认 7200 秒（2 小时），开发者需要在过期后自行刷新 access_token，保证调用链路权限正常。

每次请求不会刷新新的 access_token，在有效期内重复获取会返回相同的值 在上一个 access_token 接近过期时间 60 秒内，获取 access_token 时，会获得一个新的 access_token，老的 access_token 在这个 60 秒内仍然有效 建议开发者在服务端设置定时刷新凭证的业务逻辑，以防止过期

## # 使用访问凭证

在每次调用 OpenAPI 开放接口时，需要在 HTTP 请求头中引入 access_token 进行调用权限验证。

请求头：

| 名称 | 类型 | 必填 | 描述 |
|---|---|---|---|
| Authorization | string | 是 | 格式值：QQBot ACCESS_TOKEN |

示例：

curl --location 'https://api.bot.qq.com/users/@me' \
--header 'Authorization: QQBot ACCESS_TOKEN'
 12

注意 为了安全考虑，请勿在应用前端使用访问凭证。请在应用服务端发起 API 访问请求。

======================================================================
## api-call-guide
URL: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/api-call-guide.html

# # API 调用指南

QQ 机器人开放平台提供了基于 HTTPS 协议的 OpenAPI 接口，开发者可以通过这些接口实现消息收发、群聊管理、频道管理等功能。

## # 调用方式

### # 统一请求地址

https://api.bot.qq.com
 1

### # 鉴权方式

调用 API 时，需要将 access_token 放入请求 Header 中：

Authorization: QQBot {ACCESS_TOKEN}
 1

### # 请求示例

以发送单聊消息为例：

curl -X POST 'https://api.bot.qq.com/v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages' \
-H 'Authorization: QQBot {ACCESS_TOKEN}' \
-H 'Content-Type: application/json; charset=utf-8' \
-d '{
  "content": "Hello World",
  "msg_type": 0,
  "msg_id": "previous_msg_id"
}'
 12345678

### # 响应结构

API 调用成功时，响应体直接返回业务数据；调用失败时，响应体包含 err_code、message 等错误信息：

err_code：错误码。成功时为 0 message：错误信息 trace_id：链路追踪 ID，用于问题排查

成功响应示例：

{
  "id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "timestamp": "2026-07-21T10:30:00+08:00"
}
 1234

失败响应示例：

{
  "err_code": 40034005,
  "message": "回复消息msg_id已过期",
  "trace_id": "4a8a61565b909f199b1ec169fdd6f49e"
}
 12345

注意 请不要依据 message 来判定一个请求是否失败，message 可能会随时调整，建议根据 err_code 判断请求是否失败。

## # 唯一身份机制

不同的 bot(AppID) 获取到的用户 openid，群 openid，频道 openid 均不相同，若跨业务有关联用户身份需求，后续提供跨 AppID 绑定后，使用类似 unionid 的机制打通身份。

举例 不同 bot 在单聊场景，获取到的用户唯一识别 openid 不一样，称为 user_openid 不同 bot 在群聊场景，获取到的群唯一识别号 openid 不一样，称为 group_openid bot 在群聊场景，获取到用户在群内的唯一识别号，称为 member_openid

## # 全链路追踪

平台的链路追踪 TraceID 可通过两种方式获取：

HTTP 响应头：X-Tps-trace-ID 字段 响应 Body：返回体中的 trace_id 字段

如果开发者有无法自行定位的问题，需要找平台协助时，可提取该 ID 提交给平台方，方便查询相关日志。

## # OpenAPI 错误码

错误码分为两部分：

HTTP 状态码 HTTP Body 返回的 JSON 中的 err_code

### # HTTP 状态码

| 值 | 含义 |
|---|---|
| 200 | 成功 |
| 204 | 成功，但是无包体，一般用于删除操作 |
| 201, 202 | 异步操作成功，虽然说成功，但是会返回一个 error body，需要特殊处理 |
| 401 | 认证失败 |
| 404 | 未找到 API |
| 405 | HTTP Method 不允许 |
| 429 | 频率限制 |
| 500 | 处理失败 |
| 504 | 处理失败 |

### # 公共错误码

以下为所有接口通用的公共错误码。各接口特有的错误码请查阅具体接口文档中的「错误码」章节。

| 值 | 含义 |
|---|---|
| 10001 | UnknownAccount 账号异常 |
| 10003 | UnknownChannel 子频道异常 |
| 10004 | UnknownGuild 频道异常 |
| 11281 | ErrorCheckAdminFailed 检查是否是管理员失败，系统错误，一般重试一次会好，最多只能重试一次 |
| 11282 | ErrorCheckAdminNotPass 检查是否是管理员未通过，该接口需要管理员权限，但是用户在添加机器人的时候并未授予该权限，属于逻辑错误，可以提示用户进行授权 |
| 11251 | ErrorWrongAppid 参数中的 appid 错误，开发者填的 token 错误，appid 无法识别 |
| 11252 | ErrorCheckAppPrivilegeFailed 检查应用权限失败，系统错误，一般重试一次会好，最多只能重试一次 |
| 11253 | ErrorCheckAppPrivilegeNotPass 检查应用权限不通过，该机器人应用未获得调用该接口的权限，需要向平台申请 |
| 11254 | ErrorInterfaceForbidden 应用接口被封禁，该机器人虽然获得了该接口权限，但是被封禁了 |
| 11261 | ErrorWrongAppid 参数中缺少 appid，同 11251 |
| 11262 | ErrorCheckRobot 当前接口不支持使用机器人 Bot Token 调用 |
| 11263 | ErrorCheckGuildAuth 检查频道权限失败，系统错误，一般重试一次会好，最多只能重试一次 |
| 11264 | ErrorGuildAuthNotPass 检查小站权限未通过，管理员添加机器人的时候未授予该接口权限，属于逻辑错误，可提示用户进行授权，如果已经给予授权，请检查传递的 guild id 是否正确 |
| 11265 | ErrorRobotHasBaned 机器人已经被封禁 |
| 11241 | ErrorWrongToken 参数中缺少 token |
| 11242 | ErrorCheckTokenFailed 校验 token 失败，系统错误，一般重试一次会好，最多只能重试一次 |
| 11243 | ErrorCheckTokenNotPass 校验 token 未通过，用户填充的 token 错误，需要开发者进行检查 |
| 11273 | ErrorCheckUserAuth 检查用户权限失败，当前接口不支持使用 Bearer Token 调用 |
| 11274 | ErrorUserAuthNotPass 检查用户权限未通过，用户 OAuth 授权时未给与该接口权限，可提示用户重新进行授权 |
| 11275 | ErrorWrongAppid 无 appid，同 11251 |
| 11301 | ErrorGetHTTPHeader HTTP Header 无效 |
| 11302 | ErrorGetHeaderUIN HTTP Header 无效 |
| 11303 | ErrorGetNick 获取昵称失败 |
| 11304 | ErrorGetAvatar 获取头像失败 |
| 11305 | ErrorGetGuildID 获取频道 ID 失败 |
| 11306 | ErrorGetGuildInfo 获取频道信息失败 |
| 12001 | ReplaceIDFailed 替换 id 失败 |
| 12002 | RequestInvalid 请求体错误 |
| 12003 | ResponseInvalid 回包错误 |
| 20028 | ChannelHitWriteRateLimit 子频道消息触发限频 |
| 50006 | CannotSendEmptyMessage 消息为空 |
| 50035 | InvalidFormBody form-data 内容异常 |
| 50037 | 带有 markdown 消息只支持 markdown 或者 keyboard 组合 |
| 50038 | 非同频道同子频道 |
| 50039 | 获取消息失败 |
| 50040 | 消息模版类型错误 |
| 50041 | markdown 有空值 |
| 50042 | markdown 列表长达最大值 |
| 50043 | guild_id 转换失败 |
| 50045 | 不能回复机器人自己产生的消息 |
| 50046 | 非 at 机器人消息 |
| 50047 | 非机器人产生的消息 或者 at 机器人消息 |
| 50048 | message id 不能为空 |
| 50049 | 只能修改含有 keyboard 元素的消息 |
| 50050 | 修改消息时，keyboard 元素不能为空 |
| 50051 | 只能修改机器人自己发送的消息 |
| 50053 | 修改消息错误 |
| 50054 | markdown 模版参数错误 |
| 50055 | 无效的 markdown content |
| 50056 | 不允许发送 markdown content |
| 50057 | markdown 参数只支持原生语法或者模版二选一 |
| 301000~301099 | 子频道权限错误 |
| 301000 | 参数错误 |
| 301001 | 查询频道信息错误 |
| 301002 | 查询子频道权限错误 |
| 301003 | 修改子频道权限错误 |
| 301004 | 私密子频道关联的人数到达上限 |
| 301005 | 调用 Rpc 服务失败 |
| 301006 | 非群成员没有查询权限 |
| 301007 | 参数超过数量限制 |
| 302000 | 参数错误 |
| 302001 | 查询频道信息错误 |
| 302002 | 查询日程列表失败 |
| 302003 | 查询日程失败 |
| 302004 | 修改日程失败 |
| 302005 | 删除日程失败 |
| 302006 | 创建日程失败 |
| 302007 | 获取创建者信息失败 |
| 302008 | 子频道 ID 不能为空 |
| 302009 | 频道系统错误，请联系客服 |
| 302010 | 暂无修改日程权限 |
| 302011 | 日程活动已被删除 |
| 302012 | 每天只能创建 10 个日程，明天再来吧！ |
| 302013 | 创建日程触发安全打击 |
| 302014 | 日程持续时间超过 7 天，请重新选择 |
| 302015 | 开始时间不能早于当前时间 |
| 302016 | 结束时间不能早于开始时间 |
| 302017 | Schedule 对象为空 |
| 302018 | 参数类型转换失败 |
| 302019 | 调用下游失败，请联系客服 |
| 302020 | 日程内容违规、账号违规 |
| 302021 | 频道内当日新增活动达上限 |
| 302022 | 不能绑定非当前频道的子频道 |
| 302023 | 开始时跳转不可绑定日程子频道 |
| 302024 | 绑定的子频道不存在 |
| 304003 | URL_NOT_ALLOWED url 未报备 |
| 304004 | ARK_NOT_ALLOWED 没有发 ark 消息权限 |
| 304005 | EMBED_LIMIT embed 长度超限 |
| 304006 | SERVER_CONFIG 后台配置错误 |
| 304007 | GET_GUILD 查询频道异常 |
| 304008 | GET_BOT 查询机器人异常 |
| 304009 | GET_CHENNAL 查询子频道异常 |
| 304010 | CHANGE_IMAGE_URL 图片转存错误 |
| 304011 | NO_TEMPLATE 模板不存在 |
| 304012 | GET_TEMPLATE 取模板错误 |
| 304014 | TEMPLATE_PRIVILEGE 没有模板权限 |
| 304016 | SEND_ERROR 发消息错误 |
| 304017 | UPLOAD_IMAGE 图片上传错误 |
| 304018 | SESSION_NOT_EXIST 机器人没连上 gateway |
| 304019 | AT_EVERYONE_TIMES @全体成员 次数超限 |
| 304020 | FILE_SIZE 文件大小超限 |
| 304021 | GET_FILE 下载文件错误 |
| 304022 | PUSH_TIME 推送消息时间限制 |
| 304023 | PUSH_MSG_ASYNC_OK 推送消息异步调用成功，等待人工审核 |
| 304024 | REPLY_MSG_ASYNC_OK 回复消息异步调用成功，等待人工审核 |
| 304025 | BEAT 消息被打击 |
| 304026 | MSG_ID 回复的消息 id 错误 |
| 304027 | MSG_EXPIRE 回复的消息过期 |
| 304028 | MSG_PROTECT 非 At 当前用户的消息不允许回复 |
| 304029 | CORPUS_ERROR 调语料服务错误 |
| 304030 | CORPUS_NOT_MATCH 语料不匹配 |
| 304031 | 私信已关闭 |
| 304032 | 私信不存在 |
| 304033 | 拉私信错误 |
| 304034 | 不是私信成员 |
| 304035 | 推送消息超过子频道数量限制 |
| 304036 | 没有 markdown 模板的权限 |
| 304037 | 没有发消息按钮组件的权限 |
| 304038 | 消息按钮组件不存在 |
| 304039 | 消息按钮组件解析错误 |
| 304040 | 消息按钮组件消息内容错误 |
| 304044 | 取消息设置错误 |
| 304045 | 子频道主动消息数限频 |
| 304046 | 不允许在此子频道发主动消息 |
| 304047 | 主动消息推送超过限制的子频道数 |
| 304048 | 不允许在此频道发主动消息 |
| 304049 | 私信主动消息数限频 |
| 304050 | 私信主动消息总量限频 |
| 304051 | 消息设置引导请求构造错误 |
| 304052 | 发消息设置引导超频 |
| 306001 | param invalid 撤回消息参数错误 |
| 306002 | msgid error 消息 id 错误 |
| 306003 | fail to get message 获取消息错误(可重试) |
| 306004 | no permission to delete message 没有撤回此消息的权限 |
| 306005 | retract message error 消息撤回失败(可重试) |
| 306006 | fail to get channel 获取子频道失败(可重试) |
| 501000~501999 | 公告错误 |
| 501001 | 参数校验失败 |
| 501002 | 创建子频道公告失败(可重试) |
| 501003 | 删除子频道公告失败(可重试) |
| 501004 | 获取频道信息失败(可重试) |
| 501005 | MessageID 错误 |
| 501006 | 创建频道全局公告失败(可重试) |
| 501007 | 删除频道全局公告失败(可重试) |
| 501008 | MessageID 不存在 |
| 501009 | MessageID 解析失败 |
| 501010 | 此条消息非子频道内消息 |
| 501011 | 创建精华消息失败(可重试) |
| 501012 | 删除精华消息失败(可重试) |
| 501013 | 精华消息超过最大数量 |
| 501014 | 安全打击 |
| 501015 | 此消息不允许设置 |
| 501016 | 频道公告子频道推荐超过最大数量 |
| 501017 | 非频道主或管理员 |
| 501018 | 推荐子频道 ID 无效 |
| 501019 | 公告类型错误 |
| 501020 | 创建推荐子频道类型频道公告失败 |
| 502000~502099 | 禁言相关错误 |
| 502001 | 频道 id 无效 |
| 502002 | 频道 id 为空 |
| 502003 | 用户 id 无效 |
| 502004 | 用户 id 为空 |
| 502005 | timestamp 不合法 |
| 502006 | timestamp 无效 |
| 502007 | 参数转换错误 |
| 502008 | rpc 调用失败 |
| 502009 | 安全打击 |
| 502010 | 请求头错误 |
| 503001 | 频道 id 无效 |
| 503002 | 频道 id 为空 |
| 503003 | 获取子频道信息失败 |
| 503004 | 超出发布帖子的频次限制 |
| 503005 | 帖子标题为空 |
| 503006 | 帖子内容为空 |
| 503007 | 帖子ID为空 |
| 503008 | 获取X-Uin失败 |
| 503009 | 帖子ID无效或不合法 |
| 503010 | 通过Uin获取TinyID失败 |
| 503011 | 帖子ID里面的时间戳无效或不合法 |
| 503012 | 帖子不存在或已删除 |
| 503013 | 服务器内部错误 |
| 503014 | 帖子JSON内容解析失败 |
| 503015 | 帖子内容转换失败 |
| 503016 | 链接数量超过限制 |
| 503017 | 字数超过限制 |
| 503018 | 图片数量超过限制 |
| 503019 | 视频数量超过限制 |
| 503020 | 标题长度超过限制 |
| 504000~504999 | 消息频率相关错误 |
| 504001 | 请求参数无效错误 |
| 504002 | 获取 HTTP 头失败 |
| 504003 | 获取 BOT UIN 错误 |
| 504004 | 获取消息频率设置信息错误 |
| 610000-619999 | 频道权限错误 |
| 610001 | 获取频道 ID 失败 |
| 610002 | 获取 HTTP 头失败 |
| 610003 | 获取机器人号码失败 |
| 610004 | 获取机器人角色失败 |
| 610005 | 获取机器人角色内部错误 |
| 610006 | 拉取机器人权限列表失败 |
| 610007 | 机器人不在频道内 |
| 610008 | 无效参数 |
| 610009 | 获取 API 接口详情失败 |
| 610010 | API 接口已授权 |
| 610011 | 获取机器人信息失败 |
| 610012 | 限频失败 |
| 610013 | 已限频 |
| 610014 | api 授权链接发送失败 |
| 620001-629999 | 表情表态错误 |
| 620001 | 表情表态无效参数 |
| 620002 | 已经达到表情反应的类型数量上限 |
| 620003 | 已经设置过该表情表态 |
| 620004 | 没有设置过该表情表态 |
| 620005 | 没有权限设置表情表态 |
| 620006 | 操作限频 |
| 620007 | 表情表态操作失败，请重试 |
| 630001-639999 | 互动回调数据更新 |
| 630001 | 互动回调数据更新无效参数 |
| 630002 | 互动回调数据更新获取AppID失败 |
| 630003 | 互动回调数据AppID不匹配 |
| 630004 | 互动回调数据更新内部存储错误 |
| 630005 | 互动回调数据更新内部存储读取错误 |
| 630006 | 互动回调数据更新读取请求AppID失败 |
| 630007 | 互动回调数据太大 |
| 1000000~2999999 | 发消息错误 |
| 1100100 | 安全打击：消息被限频 |
| 1100101 | 安全打击：内容涉及敏感，请返回修改 |
| 1100102 | 安全打击：抱歉，暂未获得新功能体验资格 |
| 1100103 | 安全打击 |
| 1100104 | 安全打击：该群已失效或当前群已不存在 |
| 1100300 | 系统内部错误 |
| 1100301 | 调用方不是群成员 |
| 1100302 | 获取指定频道名称失败 |
| 1100303 | 主页频道非管理员不允许发消息 |
| 1100304 | @次数鉴权失败 |
| 1100305 | TinyId 转换 Uin 失败 |
| 1100306 | 非私有频道成员 |
| 1100307 | 非白名单应用子频道 |
| 1100308 | 触发频道内限频 |
| 1100499 | 其他错误 |
| 3000000~3999999 | 编辑消息错误 |
| 3300006 | 安全打击 |

======================================================================
## interface-framework/api-use
URL: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/api-use.html

# # 接口调用与鉴权

说明 QQ 机器人 服务端开放的 openapi 接口，均使用 https 方式进行调用，通过  AccessToken 机制实现对 openapi 接口调用的鉴权。

## # 获取调用凭证

请求

| 基本 |
|---|
| HTTP URL | https://api.bot.qq.com/app/getAppAccessToken |
| HTTP Method | POST |

请求参数

| 属性 | 类型 | 必填 | 说明 |
|---|---|---|---|
| appId | string | 是 | 在开放平台管理端上获得。 |
| clientSecret | string | 是 | 在开放平台管理端上获得。 |

返回参数

| 属性 | 类型 | 说明 |
|---|---|---|
| access_token | string | 获取到的凭证。 |
| expires_in | number | 凭证有效时间，单位：秒。目前是7200秒之内的值。 |

错误码

| 错误码 | 错误码取值 |
|---|---|
| 0 | ok |

调用示例

curl --location 'https://api.bot.qq.com/app/getAppAccessToken' \
--header 'Content-Type: application/json' \
--data '{
  "appId": "APPID",
  "clientSecret": "CLIENTSECRET"
}'
 123456

返回示例

{
  "access_token": "ACCESS_TOKEN",
  "expires_in": "7200"
}
 1234

其他说明

目前 access_token 生命周期默认 7200 秒，每次请求不会刷新新的 access_token，开发者需要在过期后自行刷新 access_token，保证调用链路权限正常。

在上一个 access_token 接近过期时间 60 秒内，获取 access_token 时，会获得一个新的 access_token，老的 access_token 在这个60秒内仍然有效。

## # 鉴权方式

在每次调用 https 的 openapi 开放接口请求的时候，需要在 header 内引入 access_token 进行调用权限验证。

统一地址

https://api.bot.qq.com
 1

请求头

| 名称 | 类型 | 必填 | 描述 |
|---|---|---|---|
| Authorization | string | 是 | 格式值："QQBot ACCESS_TOKEN" |

示例

{
  "headers": {
    "Authorization": "QQBot {ACCESS_TOKEN}"
  }
}
 12345

======================================================================
## interface-framework/sign
URL: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/sign.html

# # 安全和授权

开发者需要对每一次回调请求，根据回调中的签名等信息验证请求者身份，避免安全隐患。目前签名算法使用Ed25519。

## # 安全凭证

开发者平台的 Bot Secret 用于加密签名字符串和服务器端验证签名字符串的密钥。用户必须严格保管安全凭证，避免泄露。

## # 验证签名

### # 1. 签名验证参数

| 字段名 | 说明 | 参考值 |
|---|---|---|
| X-Signature-Ed25519 | HTTP Header 中透传 Signature | 3ecd***（64字节） |
| X-Signature-Timestamp | HTTP Header 透传的签名时间戳 | 1636373772 |
| HTTP Body | HTTP 请求中 Body 值 | {"msg":"hello"} |

### # 2. 验证签名过程

以下代码以Go语言为例,引用 crypto/ed25519 包实现 Ed25519 算法

根据开发者平台的 Bot Secret 值进行repeat操作得到签名32字节的 seed ,根据 seed 调用 Ed25519 算法生成32字节公钥

// 根据botSecret进行repeat操作后得到seed值计算出公钥
  seed := botSecret
  for len(seed) < ed25519.SeedSize {
    seed = strings.Repeat(seed, 2)
  }
  rand := strings.NewReader(seed[:ed25519.SeedSize])
  publicKey, privateKey, err := ed25519.GenerateKey(rand)
 1234567

DEMO

【输入】
secret: naOC0ocQE3shWLAfffVLB1rhYPG7
seed: naOC0ocQE3shWLAfffVLB1rhYPG7naOC
【输出】
publicKey: [215 195 98 254 120 174 248 31 242 50 135 180 147 98 139 93 176 42 60 79 227 11 33 94 77 25 96 155 93 118 103 58]
privateKey: [110 97 79 67 48 111 99 81 69 51 115 104 87 76 65 102 102 102 86 76 66 49 114 104 89 80 71 55 110 97 79 67 215 195 98 254 120 174 248 31 242 50 135 180 147 98 139 93 176 42 60 79 227 11 33 94 77 25 96 155 93 118 103 58]
 123456

获取 HTTP Header 中 X-Signature-Ed25519 的值进行 hec (十六进制解码)操作后的得到 Signature 并进行校验

// 取HTTP header中X-Signature-Ed25519(进行hex解码)并校验 
  signature := req.Header.Get("X-Signature-Ed25519")
  if signature == "" {
    return false
  }
  sig, err := hex.DecodeString(signature)
  if err != nil {
    return false
  }
  if len(sig) != ed25519.SignatureSize || sig[63]&224 != 0 {
    return false
  }
 123456789101112

获取 HTTP Header 中 X-Signature-Timestamp 的和 HTTP Body 的值按照 timestamp+body 顺序进行组合成签名体msg

// 取HTTP header中 X-Signature-Timestamp 并校验
  timestamp := req.Header.Get("X-Signature-Timestamp")
  if timestamp == "" {
    return false
  }
  httpBody, err := io.ReadAll(req.Body)
  if err != nil {
    return false
  }
  // 按照timestamp+Body顺序组成签名体
  var msg bytes.Buffer
  msg.WriteString(timestamp)
  msg.Write(httpBody)
  if err != nil {
    return false
  }
 12345678910111213141516

根据公钥、Signature、签名体调用 Ed25519 算法进行验证

ed25519.Verify(publicKey, msg.Bytes(), sig)
 1

DEMO

【输入】
secret: naOC0ocQE3shWLAfffVLB1rhYPG7
body: { "op": 0,"d": {}, "t": "GATEWAY_EVENT_NAME"}
timestamp: 1725442341
【输出】
sig: 865ad13a61752ca65e26bde6676459cd36cf1be609375b37bd62af366e1dc25a8dc789ba7f14e017ada3d554c671a911bfdf075ba54835b23391d509579ed002
 12345678

======================================================================
## interface-framework/opcode
URL: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/opcode.html

# # opcode

所有opcode列表如下：

| CODE | 名称 | 客户端操作 | 描述 |
|---|---|---|---|
| 0 | Dispatch | Receive | 服务端进行消息推送 |
| 1 | Heartbeat | Send/Receive | 客户端或服务端发送心跳 |
| 2 | Identify | Send | 客户端发送鉴权 |
| 6 | Resume | Send | 客户端恢复连接 |
| 7 | Reconnect | Receive | 服务端通知客户端重新连接 |
| 9 | Invalid Session | Receive | 当identify或resume的时候，如果参数有错，服务端会返回该消息 |
| 10 | Hello | Receive | 当客户端与网关建立ws连接之后，网关下发的第一条消息 |
| 11 | Heartbeat ACK | Receive/Reply | 当发送心跳成功之后，就会收到该消息 |
| 12 | HTTP Callback ACK | Reply | 仅用于 http 回调模式的回包，代表机器人收到了平台推送的数据() |
| 13 | 回调地址验证 | Receive | 开放平台对机器人服务端进行验证 |

客户端操作含义如下：

Receive 客户端接收到服务端 push 的消息 Send  客户端发送消息 Reply 客户端接收到服务端发送的消息之后的回包（HTTP 回调模式）

======================================================================
## interface-framework/reference
URL: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/reference.html

# # 使用 Websocket 接入

### # payload

payload 指的是在 websocket 连接上传输的数据，网关的上下行消息采用的都是同一个结构，如下：

{
  "op": 0,
  "d": {},
  "s": 42,
  "t": "GATEWAY_EVENT_NAME"
}
 123456

op 指的是 opcode，全部 opcode 列表参考 opcode。

s 下行消息都会有一个序列号，标识消息的唯一性，客户端需要再发送心跳的时候，携带客户端收到的最新的s。

t和d 主要是用在op为 0 Dispatch 的时候，t 代表事件类型，d 代表事件内容，不同事件类型的事件内容格式都不同，请注意识别。

### # 1.连接到 Gateway

第一步先调用 /gateway 或 /gateway/bot 接口获取网关地址。 会得到一个类似下面这样的地址：

wss://api.bot.qq.com/websocket/
 1

然后进行 websocket 连接，一旦连接成功，就会返回 OpCode 10 Hello 消息。这个消息主要的内容是心跳周期，单位毫秒(milliseconds)，如下：

{
  "op": 10,
  "d": {
    "heartbeat_interval": 45000
  }
}
 123456

### # 2.鉴权连接

建立 websocket 连接之后，就需要进行鉴权了，需要发送一个 OpCode 2 Identify 消息，如下：

{
  "op": 2,
  "d": {
    "token": "my_token",
    "intents": 513,
    "shard": [0, 4],
    "properties": {
      "$os": "linux",
      "$browser": "my_library",
      "$device": "my_library"
    }
  }
}
 12345678910111213

token 是创建机器人的时候分配的，格式为Bot {appid}.{app_token}

intents 是此次连接所需要接收的事件，具体可参考 Intents

shard 该参数是用来进行水平分片的。该参数是个拥有两个元素的数组。例如：[0,4]，代表分为四个片，当前链接是第 0 个片，业务稍后应该继续建立 shard 为[1,4],[2,4],[3,4]的链接，才能完整接收事件。更多详细的内容可以参考Shard。

properties 目前无实际作用，可以按照自己的实际情况填写，也可以留空

鉴权成功之后，后台会下发一个 Ready Event，结构如下：

{
  "op": 0,
  "s": 1,
  "t": "READY",
  "d": {
    "version": 1,
    "session_id": "082ee18c-0be3-491b-9d8b-fbd95c51673a",
    "user": {
      "id": "6158788878435714165",
      "username": "群pro测试机器人",
      "bot": true
    },
    "shard": [0, 0]
  }
}
 123456789101112131415

### # 3.发送心跳

鉴权成功之后，就需要按照周期进行心跳发送。d为客户端收到的最新的消息的s，如果是第一次连接，传null。

{
  "op": 1,
  "d": 251
}
 1234

心跳发送成功之后会收到 OpCode 11 Heartbeat ACK 消息，如下：

{
  "op": 11
}
 123

### # 4.恢复连接

有很多原因都会导致连接断开，断开之后短时间内重连会补发中间遗漏的事件，以保障业务逻辑的正确性。断开重连不需要发送Identify请求。在连接到 Gateway 之后，需要发送 Opcode 6 Resume消息，结构如下：

{
  "op": 6,
  "d": {
    "token": "my_token",
    "session_id": "session_id_i_stored",
    "seq": 1337
  }
}
 12345678

其中 seq 指的是在接收事件时候的 s 字段，我们推荐开发者在处理过事件之后记录下 s 这样可以在 resume 的时候传递给 websocket，websocket 会自动补发这个 seq 之后的事件。

恢复成功之后，就开始补发遗漏事件，所有事件补发完成之后，会下发一个 Resumed Event，结构如下：

{
  "op": 0,
  "s": 2002,
  "t": "RESUMED",
  "d": ""
}
 123456

======================================================================
## event-emit/payload
URL: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/payload.html

# # 通用数据结构

payload 指的是在 webhook 或 websocket 连接上传输的数据，网关的上下行消息采用的都是同一个结构，如下：

{
  "id":"event_id",
  "op": 0,
  "d": {},
  "s": 42,
  "t": "GATEWAY_EVENT_NAME"
}
 1234567

| 字段 | 描述 |
|---|---|
| id | 事件id |
| op | 指的是 opcode，参考连接维护 |
| s | 下行消息都会有一个序列号，标识消息的唯一性，客户端需要再发送心跳的时候，携带客户端收到的最新的 s |
| t | 代表事件类型。主要用在 op 为 0 Dispatch 的时候 |
| d | 代表事件内容，不同事件类型的事件内容格式都不同，请注意识别。主要用在 op 为 0 Dispatch 的时候 |

## # OpCode 含义

所有 opcode 列表如下：

| CODE | 名称 | 接入方式 | 客户端行为 | 描述 |
|---|---|---|---|---|
| 0 | Dispatch | webhook/websocket | Receive | 服务端进行消息推送 |
| 1 | Heartbeat | websocket | Send/Receive | 客户端或服务端发送心跳 |
| 2 | Identify | websocket | Send | 客户端发送鉴权 |
| 6 | Resume | websocket | Send | 客户端恢复连接 |
| 7 | Reconnect | websocket | Receive | 服务端通知客户端重新连接 |
| 9 | Invalid Session | websocket | Receive | 当 identify 或 resume 的时候，如果参数有错，服务端会返回该消息 |
| 10 | Hello | websocket | Receive | 当客户端与网关建立 ws 连接之后，网关下发的第一条消息 |
| 11 | Heartbeat ACK | websocket | Receive/Reply | 当发送心跳成功之后，就会收到该消息 |
| 12 | HTTP Callback ACK | webhook | Reply | 仅用于 http 回调模式的回包，代表机器人收到了平台推送的数据 |
| 13 | 回调地址验证 | webhook | Receive | 开放平台对机器人服务端进行验证 |

客户端行为含义如下：

Receive 客户端接收到服务端 push 的消息 Send 客户端发送消息 Reply 客户端接收到服务端发送的消息之后的回包（HTTP 回调模式）

## # 事件订阅 Intents

事件的 intents 是一个标记位，每一位都代表不同的事件，如果需要接收某类事件，就将该位置为 1。

每个 intents 位代表的是一类事件，可以使用 websocket 传输的数据中的 t 字段的值来区分。

事件和位移的关系如下：

GUILDS (1 << 0)
  - GUILD_CREATE           // 当机器人加入新guild时
  - GUILD_UPDATE           // 当guild资料发生变更时
  - GUILD_DELETE           // 当机器人退出guild时
  - CHANNEL_CREATE         // 当channel被创建时
  - CHANNEL_UPDATE         // 当channel被更新时
  - CHANNEL_DELETE         // 当channel被删除时
GUILD_MEMBERS (1 << 1)
  - GUILD_MEMBER_ADD       // 当成员加入时
  - GUILD_MEMBER_UPDATE    // 当成员资料变更时
  - GUILD_MEMBER_REMOVE    // 当成员被移除时
GUILD_MESSAGES (1 << 9)    // 消息事件，仅 *私域* 机器人能够设置此 intents。
  - MESSAGE_CREATE         // 发送消息事件，代表频道内的全部消息，而不只是 at 机器人的消息。内容与 AT_MESSAGE_CREATE 相同
  - MESSAGE_DELETE         // 删除（撤回）消息事件
GUILD_MESSAGE_REACTIONS (1 << 10)
  - MESSAGE_REACTION_ADD    // 为消息添加表情表态
  - MESSAGE_REACTION_REMOVE // 为消息删除表情表态
DIRECT_MESSAGE (1 << 12)
  - DIRECT_MESSAGE_CREATE   // 当收到用户发给机器人的私信消息时
  - DIRECT_MESSAGE_DELETE   // 删除（撤回）消息事件
GROUP_AND_C2C_EVENT (1 << 25)
  - C2C_MESSAGE_CREATE      // 用户单聊发消息给机器人时候
  - FRIEND_ADD              // 用户添加使用机器人
  - FRIEND_DEL              // 用户删除机器人
  - C2C_MSG_REJECT          // 用户在机器人资料卡手动关闭"主动消息"推送
  - C2C_MSG_RECEIVE         // 用户在机器人资料卡手动开启"主动消息"推送开关
  - GROUP_AT_MESSAGE_CREATE // 用户在群里@机器人时收到的消息
  - GROUP_ADD_ROBOT         // 机器人被添加到群聊
  - GROUP_DEL_ROBOT         // 机器人被移出群聊
  - GROUP_MSG_REJECT        // 群管理员主动在机器人资料页操作关闭通知
  - GROUP_MSG_RECEIVE       // 群管理员主动在机器人资料页操作开启通知
INTERACTION (1 << 26)
  - INTERACTION_CREATE     // 互动事件创建时
MESSAGE_AUDIT (1 << 27)
  - MESSAGE_AUDIT_PASS     // 消息审核通过
  - MESSAGE_AUDIT_REJECT   // 消息审核不通过
FORUMS_EVENT (1 << 28)  // 论坛事件，仅 *私域* 机器人能够设置此 intents。
  - FORUM_THREAD_CREATE     // 当用户创建主题时
  - FORUM_THREAD_UPDATE     // 当用户更新主题时
  - FORUM_THREAD_DELETE     // 当用户删除主题时
  - FORUM_POST_CREATE       // 当用户创建帖子时
  - FORUM_POST_DELETE       // 当用户删除帖子时
  - FORUM_REPLY_CREATE      // 当用户回复评论时
  - FORUM_REPLY_DELETE      // 当用户回复评论时
  - FORUM_PUBLISH_AUDIT_RESULT      // 当用户发表审核通过时
AUDIO_ACTION (1 << 29)
  - AUDIO_START             // 音频开始播放时
  - AUDIO_FINISH            // 音频播放结束时
  - AUDIO_ON_MIC            // 上麦时
  - AUDIO_OFF_MIC           // 下麦时
PUBLIC_GUILD_MESSAGES (1 << 30) // 消息事件，此为公域的消息事件
  - AT_MESSAGE_CREATE       // 当收到@机器人的消息时
  - PUBLIC_MESSAGE_DELETE   // 当频道的消息被删除时
 123456789101112131415161718192021222324252627282930313233343536373839404142434445464748495051525354555657585960616263

### # 举例

如开发者需要接收用户 at 机器人的消息，那么就需要在 intents 中设置接收 PUBLIC_GUILD_MESSAGES。则需要先计算 1 << 30 的值。然后与 0 做位或操作，得到最终需要传递的 intents。

如果涉及到多个事件类型的接收，则需要将多个结果做位或操作，如：0|1<<30|1<<1 代表订阅 PUBLIC_GUILD_MESSAGES 和 GUILD_MEMBERS 这两类事件。

### # 权限

事件类型的订阅，是有权限控制的，除了 GUILDS，PUBLIC_GUILD_MESSAGES，GUILD_MEMBERS 事件是基础的事件，默认有权限订阅之外，其他的特殊事件，都需要经过申请才能够使用，如果在鉴权的时候传递了无权限的 intents，websocket 会报错，并直接关闭连接。请开发者注意订阅事件的范围需要控制在自己所需要的范围之内。

如果拥有的某个特殊事件类型的权限被取消，则在当前连接上不会报错，但是将不会收到对应的事件类型，如果重新连接，则报错，所以如果开发者的事件类型权限被取消，请及时调整监听事件代码，避免报错导致的无法连接。

======================================================================
## event-emit/webhook
URL: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/webhook.html

# # Webhook 方式

QQ 机器人开放平台支持通过使用 HTTP 接口接收事件。开发者可通过管理端  (opens new window)设定回调地址，监听事件等。

目前回调地址允许配置的端口号为：80、443、8080、8443。

## # 签名校验

机器人服务端需要对回调请求进行签名验证以保证数据没有被篡改过。签名算法

## # 回调地址及事件监听配置

开发者需要提供一个 HTTPS 回调地址。并选定监听的事件类型。开放平台会将事件通过回调的方式推送给机器人。

配置回调地址后，开放平台会对回调地址进行验证：

请求结构(Payload.d)

| 字段 | 描述 |
|---|---|
| plain_token | 需要计算签名的字符串 |
| event_ts | 计算签名使用时间戳 |

返回结果

| 字段 | 描述 |
|---|---|
| plain_token | 需要计算签名的字符串 |
| signature | 签名 |

计算过程如下(golang)：

func handleValidation(rw http.ResponseWriter, r *http.Request, botSecret string) {
	httpBody, err := io.ReadAll(r.Body)
	if err != nil {
		log.Println("read http body err", err)
		return
	}
	payload := &Payload{}
	if err = json.Unmarshal(httpBody, payload); err != nil {
		log.Println("parse http payload err", err)
		return
	}
	validationPayload := &ValidationRequest{}
	if 	err = json.Unmarshal(payload.Data, validationPayload);err != nil {
		log.Println("parse http payload failed:", err)
		return
	}
	seed := botSecret
	for len(seed) < ed25519.SeedSize {
		seed = strings.Repeat(seed, 2)
	}
	seed = seed[:ed25519.SeedSize]
	reader := strings.NewReader(seed)
	// GenerateKey 方法会返回公钥、私钥，这里只需要私钥进行签名生成不需要返回公钥
	_, privateKey, err := ed25519.GenerateKey(reader)
	if err != nil {
		log.Println("ed25519 generate key failed:", err)
		return
	}
	var msg bytes.Buffer
	msg.WriteString(validationPayload.EventTs)
	msg.WriteString(validationPayload.PlainToken)
	signature := hex.EncodeToString(ed25519.Sign(privateKey, msg.Bytes()))
	if err != nil {
		log.Println("generate signature failed:", err)
		return
	}
	rspBytes, err := json.Marshal(
		&ValidationResponse{
			PlainToken: validationPayload.PlainToken,
			Signature:  signature,
		})
	if err != nil {
		log.Println("handle validation failed:", err)
		return
	}
	rw.Write(rspBytes)
}
 1234567891011121314151617181920212223242526272829303132333435363738394041424344454647

例如机器人账号

appid: 11111111
secret: DG5g3B4j9X2KOErG
 12

回调验证请求：

headers: User-Agent:[QQBot-Callback] X-Bot-Appid:[11111111]
body: {"d":{"plain_token":"Arq0D5A61EgUu4OxUvOp","event_ts":"1725442341"},"op":13},
 12

机器人应返回：

body: {"plain_token": "Arq0D5A61EgUu4OxUvOp","signature": "87befc99c42c651b3aac0278e71ada338433ae26fcb24307bdc5ad38c1adc2d01bcfcadc0842edac85e85205028a1132afe09280305f13aa6909ffc2d652c706"}
 1

======================================================================
## event-emit/websocket
URL: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/websocket.html

# # WebSocket 方式

## # 发起连接到 Gateway

第一步先调用 获取通用WSS 接入点 或 获取带分片WSS 接入点 接口获取网关地址。

会得到一个类似下面这样的地址：

wss://api.bot.qq.com/websocket/
 1

然后进行 websocket 长连接建立，一旦连接成功，就会返回 OpCode 10 Hello 消息。这个消息主要的内容是心跳周期，单位毫秒(milliseconds)，如下：

{
  "op": 10,
  "d": {
    "heartbeat_interval": 45000
  }
}
 123456

## # 登录鉴权获得 Session

websocket 长连接建立之后，需要进行登录鉴权，登录鉴权成功后会获得一个 session 会话 id，只有登录成功后，QQ 后台才会下发事件通知。

发送一个 OpCode 2 Identify 消息，payload 如下：

{
  "op": 2,
  "d": {
    "token": "token string",
    "intents": 513,
    "shard": [0, 4],
    "properties": {
      "$os": "linux",
      "$browser": "my_library",
      "$device": "my_library"
    }
  }
}
 12345678910111213

| 字段 | 描述 |
|---|---|
| token | 格式为 "QQBot {AccessToken}" |
| intents | 是此次连接所需要接收的事件，具体可参考 事件订阅 Intents |
| shard | 考虑到开发者事件接收时可以实现负载均衡，QQ 提供了分片逻辑，事件通知会落在不同的分片上，该参数是个拥有两个元素的数组。例如：[0,4]，代表分为四个片，当前链接是第 0 个片，业务稍后应该继续建立 shard 为 [1,4], [2,4], [3,4] 的链接，才能完整接收事件，更多详细的内容可以参考 Shard 机制。若无需分片，使用 [0, 1] 即可。 |
| properties | 目前无实际作用，可以按照自己的实际情况填写，也可以留空 |

鉴权成功之后，QQ 后台会下发一个 Ready Event，payload 如下：

{
  "op": 0,
  "s": 1,
  "t": "READY",
  "d": {
    "version": 1,
    "session_id": "082ee18c-0be3-491b-9d8b-fbd95c51673a",
    "user": {
      "id": "6158788878435714165",
      "username": "群pro测试机器人",
      "bot": true
    },
    "shard": [0, 0]
  }
}
 123456789101112131415

## # 发送心跳 Ack

鉴权成功之后，就需要按照周期进行心跳发送。d 为客户端收到的最新的消息的 s，如果是首次连接，d 为传 null，payload 如下：

{
  "op": 1,
  "d": 251
}
 1234

心跳发送成功之后会收到 OpCode 11 Heartbeat ACK 消息，payload 如下：

{
  "op": 11
}
 123

## # 恢复登录态 Session

有很多原因可能会导致 websocket 长连接断开，断开之后短时间内重连会补发中间遗漏的事件，以保障业务逻辑的正确性。断开重连 gateway 后不需要发送重新登录 OpCode 2 Identify 请求。在连接到 Gateway 之后，需要发送 OpCode 6 Resume 消息，payload 如下：

{
  "op": 6,
  "d": {
    "token": "my_token",
    "session_id": "session_id_i_stored",
    "seq": 1337
  }
}
 12345678

其中 seq 指的是在接收事件时候的 s 字段，我们推荐开发者在处理过事件之后记录下 s 这样可以在 resume 的时候传递给 websocket，websocket 会自动补发这个 seq 之后的事件。

恢复成功之后，就开始补发遗漏事件，所有事件补发完成之后，会下发一个 Resumed Event，payload 如下：

{
  "op": 0,
  "s": 2002,
  "t": "RESUMED",
  "d": ""
}
 123456

## # 分片连接 LoadBalance

随着 bot 的增长并被添加到越来越多的频道中，事件越来越多，业务有必要对事件进行水平分割，实现负载均衡。机器人网关实现了一种用户可控制的分片方法，该方法允许跨多个网关连接拆分事件。分片完全由用户控制，并且不需要在单独的连接之间进行状态共享。

要在连接上启用分片，需要在建立连接的时候指定分片参数，具体参考 gateway

### # 获得合适的分片数

使用 /gateway/bot 接口获取网关地址的时候，会同时返回一个建议的 shard 数，及最大并发限制。

{
  "url": "wss://api.bot.qq.com/websocket",
  "shards": 1,
  "session_start_limit": {
    "total": 1000,
    "remaining": 1000,
    "reset_after": 86400000,
    "max_concurrency": 1
  }
}
 12345678910

### # 分片规则

分片是按照频道 id 进行哈希的，同一个频道的信息会固定从同一个链接推送。具体哈希计算规则如下：

shard_id = (guild_id >> 22) % num_shards
 1

### # 最大连接数

每个机器人创建的连接数不能超过 remaining 剩余连接数。

## # WebSocket 错误码

| 值 | 含义 | 是否可以重试 RESUME | 是否可以重试 IDENTIFY |
|---|---|---|---|
| 4001 | 无效的 opcode | 否 | 否 |
| 4002 | 无效的 payload | 否 | 否 |
| 4007 | seq 错误 | 否 | 是 |
| 4006 | 无效的 session id，无法继续 resume，请 identify | 否 | 是 |
| 4008 | 发送 payload 过快，请重新连接，并遵守连接后返回的频控信息 | 是 | 是 |
| 4009 | 连接过期，请重连并执行 resume 进行重新连接 | 是 | 是 |
| 4010 | 无效的 shard | 否 | 否 |
| 4011 | 连接需要处理的 guild 过多，请进行合理的分片 | 否 | 否 |
| 4012 | 无效的 version | 否 | 否 |
| 4013 | 无效的 intent | 否 | 否 |
| 4014 | intent 无权限 | 否 | 否 |
| 4900~4913 | 内部错误，请重连 | 否 | 是 |
| 4914 | 机器人已下架，只允许连接沙箱环境，请断开连接，检验当前连接环境 | 否 | 否 |
| 4915 | 机器人已封禁，不允许连接，请断开连接，申请解封后再连接 | 否 | 否 |

针对 WebSocket 错误码的简单处理逻辑：

4009 可以重新发起 resume 4914，4915 不可以连接，请联系官方解封 其他错误，请重新发起 identify

======================================================================
## openapi/wss/url_get
URL: https://bot.q.qq.com/wiki/develop/api-v2/openapi/wss/url_get.html

# # 获取通用 WSS 接入点

### # 接口

GET /gateway
 1

### # 功能描述

用于获取 WSS 接入地址，通过该地址可建立 websocket 长连接。

### # Content-Type

application/json
 1

### # 返回

返回一个用于连接 websocket 的地址。

### # 错误码

详见错误码。

### # 示例

响应数据包

{
  "url": "wss://api.bot.qq.com/websocket/"
}
 123

======================================================================
## openapi/wss/shard_url_get
URL: https://bot.q.qq.com/wiki/develop/api-v2/openapi/wss/shard_url_get.html

# # 获取带分片 WSS 接入点

### # 接口

GET /gateway/bot
 1

### # 功能描述

用于获取 WSS 接入地址及相关信息，通过该地址可建立 websocket 长连接。相关信息包括：

建议的分片数。 目前连接数使用情况。

### # Content-Type

application/json
 1

### # 返回

| 字段名 | 类型 | 描述 |
|---|---|---|
| url | string | WebSocket 的连接地址 |
| shards | int | 建议的 shard 数 |
| session_start_limit | SessionStartLimit | 创建 Session 限制信息 |

### # SessionStartLimit

| 字段名 | 类型 | 描述 |
|---|---|---|
| total | int | 每 24 小时可创建 Session 数 |
| remaining | int | 目前还可以创建的 Session 数 |
| reset_after | int | 重置计数的剩余时间(ms) |
| max_concurrency | int | 每 5s 可以创建的 Session 数 |

### # 错误码

详见错误码。

### # 示例

{
  "wss://api.bot.qq.com/websocket/",
  "shards": 9,
  "session_start_limit": {
    "total": 1000,
    "remaining": 999,
    "reset_after": 14400000,
    "max_concurrency": 1
  }
}
 12345678910

======================================================================
## message/overview
URL: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/overview.html

# # 消息收发概述

机器人可在 QQ 单聊、群聊、频道三种场景下收发消息。本页介绍基础概念与通用规则，具体接口与事件请参考对应子分类。

## # 收发场景

| 场景 | 发送消息 | 接收事件 |
|---|---|---|
| QQ 单聊 | 发送单聊消息 / 流式消息 | C2C_MESSAGE_CREATE |
| QQ 群聊 | 发送群消息 | GROUP_AT_MESSAGE_CREATE / GROUP_MESSAGE_CREATE |
| 频道 | 发送子频道消息 / 频道私信 | 频道消息事件 |

### # 对话场景图示

说明 机器人可以被添加各种聊天场景下

| 单聊 | 群聊 | 文字子频道 | 频道私信 |
|---|---|---|---|
|  |  |  |  |

## # 主动消息与被动消息

| 类型 | 特征 | 说明 |
|---|---|---|
| 主动消息 | 无任何条件 | 机器人主动触达用户，用户可在客户端关闭「允许主动发送」开关，关闭后主动消息将发送失败 |
| 互动召回消息 | is_wakeup=true | 用户主动与机器人对话之后每个周期内可下发 1 条召回消息 |
| 被动消息（回复用户） | 携带 msg_id | 对用户消息的回复 |
| 被动消息（响应事件） | 携带 event_id | 对事件的回复 |

## # 消息类型

通过 msg_type 指定消息内容格式：

| msg_type | 类型 | 内容字段 | 发送 | 接收 |
|---|---|---|---|---|
| 0 | 文本 | content | ✅ | ✅ |
| 2 | Markdown | markdown | ✅ | - |
| 7 | 富媒体 | media（需先上传文件获取 file_info） | ✅ | ✅ |

除上述之外，响应中还可能收到图片、视频、语音、表情、卡片等类型，详见 消息类型。

## # 富媒体消息

图片、视频、语音、文件等富媒体需先上传获取 file_info，再通过发消息接口（msg_type=7）携带 media.file_info 发送。

上传方式：

分片上传：推荐使用，无需开发者提供公网 CDN 地址，参考 分片上传流程 整文件上传：单聊上传 / 群聊上传

file_info 有时效性（ttl），过期需重新上传。 单聊和群聊的文件上传接口不互通。

## # 频率与时效规则

### # 被动消息

| 场景 | 有效期 | 每条消息可回复次数 |
|---|---|---|
| 单聊 | 60 分钟 | 4 次 |
| 群聊 | 5 分钟 | 5 次 |
| 频道 | 5 分钟 | - |

### # 主动消息

主动消息与被动消息说明： QQ 用户可以在 QQ 客户端主动设置是否接收机器人发送的主动消息，如果设置了关闭，主动消息一律发送失败。

#### # 单聊

主动消息发送频率限制（HTTP接口）

| 认证类型 | 场景 | Bot 维度频控 | 单关系维度频控 | 每日上限 |
|---|---|---|---|---|
| 企业认证 | 单聊 | 10/qps | 20/qpm | 1000 条/用户 |
| 个人认证 | 单聊 | 10/qps | 20/qpm | 1000 条/用户 |
| 未认证 | 单聊 | 5/qps & 30/qpm | 20/qpm | 1000 条/用户 |

互动召回消息：在用户主动与机器人对话之后，机器人在未来 30 天内可下发互动召回消息给用户（消息类型与当前机器人拥有的消息类型权限一致），每个周期内可下发一条。分别为：当天、1 - 3 天、3 - 7 天、7 - 30 天，合计：4 个周期。在发消息接口中使用 is_wakeup 字段声明使用该能力。

#### # 群聊

主动消息发送频率限制（HTTP接口）

| 认证类型 | 场景 | Bot 维度频控 | 单关系维度频控 | 每日上限 |
|---|---|---|---|---|
| 企业认证 | 群 | 60/qpm | 20/qpm | 1000 条/群 |
| 个人认证 | 群 | 60/qpm | 20/qpm | 1000 条/群 |
| 未认证 | 群 | 30/qpm | 20/qpm | 1000 条/群 |

#### # 文字子频道

主动消息在频道主或管理设置了情况下，按设置的数量进行限频。在未设置的情况遵循如下限制:
主动推送消息，默认每天往每个子频道可推送的消息数是 20 条，超过会被限制。 主动推送消息在每个频道中，每天可以往 2 个子频道推送消息。超过后会被限制。 不论主动消息还是被动消息，在一个子频道中，每秒 最多可发送 5 条 消息。 被动回复消息有效期为 5 分钟，超时会发送失败。 发送消息接口要求机器人接口需要连接到 WebSocket 上保持在线状态 有关主动消息审核，可以通过 事件订阅 Intents 中审核事件 MESSAGE_AUDIT 返回 MessageAudited 对象获取结果。

#### # 频道私信

私信场景下，每个机器人每天可以对一个用户发 2 条 主动消息。 私信场景下，每个机器人每天累计可以发 200 条 主动消息。 被动回复消息有效期为 5 分钟，超时会发送失败。

## # 消息去重

相同 msg_id 可能多次推送，请结合 msg_seq 去重。被动回复时，相同的 msg_id + msg_seq 重复发送会失败，可递增 msg_seq 实现对同一消息的多次回复。

## # 撤回消息

机器人可撤回自己发送的消息（发送超过 2 分钟不可撤回）：

撤回单聊消息 撤回群聊消息 撤回频道消息 / 撤回频道私信

======================================================================
## gateway/error
URL: https://bot.q.qq.com/wiki/develop/api-v2/gateway/error/error.html

# # websocket 错误

### # code

| 值 | 含义 | 是否可以重试 RESUME | 是否可以重试 IDENTIFY |
|---|---|---|---|
| 4001 | 无效的 opcode | 否 | 否 |
| 4002 | 无效的 payload | 否 | 否 |
| 4007 | seq 错误 | 否 | 是 |
| 4006 | 无效的 session id，无法继续 resume，请 identify | 否 | 是 |
| 4008 | 发送 payload 过快，请重新连接，并遵守连接后返回的频控信息 | 是 | 是 |
| 4009 | 连接过期，请重连并执行 resume 进行重新连接 | 是 | 是 |
| 4010 | 无效的 shard | 否 | 否 |
| 4011 | 连接需要处理的 guild 过多，请进行合理的分片 | 否 | 否 |
| 4012 | 无效的 version | 否 | 否 |
| 4013 | 无效的 intent | 否 | 否 |
| 4014 | intent 无权限 | 否 | 否 |
| 4014 | intent 无权限 | 否 | 否 |
| 4900~4913 | 内部错误，请重连 | 否 | 是 |
| 4914 | 机器人已下架,只允许连接沙箱环境,请断开连接,检验当前连接环境 | 否 | 否 |
| 4915 | 机器人已封禁,不允许连接,请断开连接,申请解封后再连接 | 否 | 否 |

### # 针对 websocket 错误码的简单处理逻辑

4009 可以重新发起 resume 4914，4915 不可以连接，请联系官方解封 其他错误，请重新发起 identify

======================================================================
## error-trace/websocket
URL: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/error-trace/websocket.html

# # WebSocket

### # 错误码 code

| 值 | 含义 | 是否可以重试 RESUME | 是否可以重试 IDENTIFY |
|---|---|---|---|
| 4001 | 无效的 opcode | 否 | 否 |
| 4002 | 无效的 payload | 否 | 否 |
| 4007 | seq 错误 | 否 | 是 |
| 4006 | 无效的 session id，无法继续 resume，请 identify | 否 | 是 |
| 4008 | 发送 payload 过快，请重新连接，并遵守连接后返回的频控信息 | 是 | 是 |
| 4009 | 连接过期，请重连并执行 resume 进行重新连接 | 是 | 是 |
| 4010 | 无效的 shard | 否 | 否 |
| 4011 | 连接需要处理的 guild 过多，请进行合理的分片 | 否 | 否 |
| 4012 | 无效的 version | 否 | 否 |
| 4013 | 无效的 intent | 否 | 否 |
| 4014 | intent 无权限 | 否 | 否 |
| 4014 | intent 无权限 | 否 | 否 |
| 4900~4913 | 内部错误，请重连 | 否 | 是 |
| 4914 | 机器人已下架,只允许连接沙箱环境,请断开连接,检验当前连接环境 | 否 | 否 |
| 4915 | 机器人已封禁,不允许连接,请断开连接,申请解封后再连接 | 否 | 否 |

### # 针对 WebSocket 错误码的简单处理逻辑

4009 可以重新发起 resume 4914，4915 不可以连接，请联系官方解封 其他错误，请重新发起 identify

======================================================================
## 产品简介
URL: https://bot.q.qq.com/wiki/bot_new_product-intro/

# # QQ Bot介绍与接入指南

## # 简介

QQ 机器人是 QQ 开放平台面向开发者提供的智能对话服务。开发者可以通过开放接口进行机器人定制化开发，也可直接接入 AI Agent 服务，让机器人具备自然语言理解和多轮对话能力。机器人可运行于 QQ 频道、QQ 群、消息列表单聊等多个场景，深度融入 QQ 社交生态。

QQ 机器人管理端统一集成在 QQ 开放平台中，开发者通过同一账号体系即可完成主体认证、机器人创建、开发配置、发布上线的全流程操作。

## # 核心亮点

便捷：允许开发者进行 AI Agent 直连机器人，或通过开放接口的形式灵活定制化开发原创机器人。

高效：支持WebSocket、WebHook回调连接方式灵活切换，可帮助开发者实现机器人快速开发迭代。

协同：手机端协同管理机器人，支持创建、修改、群聊配置等操作，让多样化服务变得触手可达。

灵活：机器人服务范围灵活切换免审核，频道、群、单聊等QQ场景全面打通，深度融入QQ社交生态。

## # 接入流程

为了更高效的进驻到 QQ 机器人平台，建议先阅读下列文档后再启动进驻工作。

运营规范 | QQ 机器人官方文档  (opens new window)

开发文档 | QQ 机器人官方文档  (opens new window)

### # 1.注册账号

在创建机器人之前，需先登录QQ开放平台  (opens new window)完成账号注册、开发主体认证。

QQ 开放平台是机器人管理端、应用管理和开发者服务的一站式入口，开发者使用同一账号即可访问所有功能。

#### # 1.1 选择注册方式

##### # 方式一：通过QQ账号注册认证

👉温馨提示：通过 QQ 账号可快捷注册 QQ 开放平台并绑定管理员，如需体验更多能力需认证主体。

##### # 方式二：通过邮箱完成注册认证

通过邮箱注册认证不同的主体，可以绑定相同的管理员账号（QQ 账号）。

#### # 1.2 绑定邮箱账号

👉温馨提示 如未收到邮件，请检查垃圾箱或者点击重新发送进行尝试。之前已经注册过的邮箱不需再注册，直接去登录界面登录即可。

### # 2.主体认证

#### # 2.1 设置超级管理员

姓名和身份证号码务必与手机号码对应运营商实名登记的信息一致，否则会提示错误。

#### # 2.2 填写主体资质信息

企业、个体户入驻需提供工商信息：营业执照、对公账号，如不具备的用户请前往个人入口进行入驻。邮箱一旦填写完毕进入激活步骤，则被占用不可修改，所以选错邮箱的用户需要更换邮箱重新注册。

审核中-资料审核：注册完成即自动进入工商信息审核，此步骤无需开发者操作，但请随时关注状态变更。

审核中-待打款：填写银行信息，点击查看详情，进入二级页面填写对公账户银行信息，如系统没有对应【银行所在地的区】，可选同市其他区。

审核中-银行打款中：如银行信息审核无误，则 3 天内腾讯公司将会对填写的对公银行账户进行 1 元以下小额打款，请关注银行收款。

打款帐号主体：深圳市腾讯计算机系统有限公司，打款银行账号：755901658210820。

审核中-校验金额：收到打款后，请在规定时间内于开发者管理端回填收到的打款金额进行验证。金额校验次数有限，请确认收到打款后进入二级页面，填写具体的金额，如次数用完且校验不通过，该账号将被冻结。

👉温馨提示 择对应主体类型，填写和上传资质信息，选择对应的验证方式进行认证。 入驻开发者认证，企业开发者（个体户）与个人开发者权限存在差异。 姓名和身份证号码务必与手机号码对应运营商实名登记的信息一致，否则会提示错误。

填写主体信息，信息审核成功后，完成 QQ 开放平台主体信息认证，可随时登录 QQ 开放平台，绑定成功即可进入应用管理页开始创建应用。

### # 3.创建机器人

登录开放平台后，进入机器人管理端入口。

#### # 3.1 点击「创建机器人」

👉温馨提示 个人主体：个人认证开发者，支持创建 5 个机器人。 企业主体：企业认证开发者，支持创建 10 个机器人；同一企业主体下所有认证账号共用机器人创建名额，创建上限为 50个。

#### # 3.2 机器人资料填写

使用默认或上传头像，填写机器人昵称、简介即可创建机器人。

👉温馨提示：创建机器人如遇报错，请注意头像、昵称、简介规范，避免冒充官方、侵权、低俗等有害内容。

#### # 3.3 设置 AI 服务（可选）

若计划开发原创机器人，可点击「稍后连接」跳过本步骤。

### # 4.机器人管理

创建成功后，点击对应机器人，即可进入机器人管理页。

### # 5.服务范围管理

#### # 5.1 服务范围修改

👉温馨提示 未认证：机器人仅管理员使用，可添加到管理员作为群主的群内。 个人认证：可设置为公开使用，机器人进群数量添加上限为 500 个。 企业认证：场景均可设置为公开被使用的服务范围。

#### # 5.2 隐私协议填写

点击填写协议内容，可修改联系邮箱，检查无异议即可提交。

👉温馨提示 QQ 平台仅向开发者及用户提供 QQ 机器人运行的相关技术支持。机器人相关服务由开发者提供，开发者对相关服务信息内容、数据资料及其运营行为等的真实性、合法性及有效性承担全部责任。

### # 6.运营数据

查看机器人运营数据，支持下载数据表到本地。

### # 7.高级设置（AI 服务）

点击高级设置，进入「设置机器人服务」，可进入 AI Agent 接入服务，如 OpenClaw、WorkBuddy 等。

### # 8.开发基础设置

#### # 8.1 事件与回调方式选择

点击「事件订阅与回调地址」，配置接收平台事件回调通知的方式，可切换 WebSocket 与 Webhook 连接方式。

👉提示：切换后立刻生效，请谨慎操作，避免影响在线服务。 WebSocket：不依赖公网服务器部署，适合个人单机使用，需维护长连接。如果你是想用于连接 OpenClaw 等类似 AI Agent 服务，在 AI 服务提供方没有明确说明和指引的前提下，选用 WebSocket 即可。 Webhook：事件推送至你配置的 HTTPS 服务上，适合提供公开服务的机器人使用，运维更可靠。

#### # 8.2 服务器 IP 白名单

IP 白名单支持添加、删除，仅支持单个 IPv4，暂不支持 CIDR 网段。

👉温馨提示 未设置 IP 白名单时，所有请求来源 IP 都会被允许调用，建议至少添加一条以提升安全性。 设置白名单后，仅白名单地址允许调通机器人 OpenAPI，支持最多 50 个 IP 地址。

#### # 8.3 内部体验号码

支持添加 20 个用户号码用于内部开发与内邀体验的场景；配置后不受服务范围的设置影响，可测试体验机器人的对话能力。

详细开发指引，请查看开发文档：开发文档 | QQ 机器人官方文档  (opens new window) 。