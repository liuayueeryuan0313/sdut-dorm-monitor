# 山东理工大学宿舍电费查询

`sdut_electricity.py` 提供函数、可复用会话的客户端类和命令行。Python 3.10 及以上可运行，使用标准库；须将 `sdut_login.py`、`aes_tool.py` 放在同目录，无需 pip 安装依赖。

## Python 调用

```python
from getpass import getpass
from sdut_electricity import query_electricity, ElectricityClient

result = query_electricity(
    username=input("学号："),
    password=getpass("学校密码："),
    campus="西校区",
    building="26号北楼",
    floor="8",
    room="814",
    electricity_type="照明插座",  # 或“空调用电”
)
print(result)
```

需要多次查询时使用 `client = ElectricityClient(username, password)`，然后调用 `client.query("西校区", "26号北楼", "8", "814").to_dict()`，以复用同一个内存 Cookie 会话。请求超时默认为 30 秒，可在构造客户端时传入 `timeout`。

## 命令行

```powershell
python sdut_electricity.py --campus 西校区 --building 26号北楼 --floor 8 --room 814
```

启动后交互输入学号和密码，密码不回显、不写文件。也支持既有 `SDUT_USER` / `SDUT_PWD` 进程环境变量；不提供命令行明文密码参数。

网页“查寝记录”下方已加入“宿舍电量”：复用学校账号，可保存宿舍、手动查询、开关自动查询并设置独立间隔（5–10080 分钟，默认 60 分钟）。自动查询与查寝开关独立；认证受阻会关闭电量自动查询。查询结果暂存在内存，重启后需要重新查询；计划持久化在网页配置中。

本轮未修改 Docker 配置，未重建或重启现有容器。Dockerfile 与 .dockerignore 尚未包含电费模块，交由 Gemini 补齐后再部署；当前用本地 Python 运行网页可使用完整功能。

## 选择宿舍

楼栋、楼层、房间均从当前后勤页面动态读取。优先传页面完整名称；唯一的数字房号也可用。直接填写 `26` 时，南楼和北楼会产生歧义，脚本会报错并列出选择，不会随意查询其中一栋。若需指定内部编号，必须明确写为 `id:476`，不把普通房号误认为内部 ID。

可逐级列出选项，公开表单通常无需登录：

```powershell
python sdut_electricity.py --list-options --campus 西校区
python sdut_electricity.py --list-options --campus 西校区 --building 26号北楼
python sdut_electricity.py --list-options --campus 西校区 --building 26号北楼 --floor 8
```

对应 Python 方法为 `client.list_options(campus="西校区", building="26号北楼", floor="8")`。2026-10-17 读取到北楼编号为 476、814 照明房间编号为 25961；这些值仅记录当次验证，代码不写死编号。

## 返回值与缺失字段

数值使用十进制字符串，保留页面精度；`None` 在 JSON 中为 `null`。主要字段：

| 字段 | 含义 |
| --- | --- |
| `remaining_kwh` | 剩余电量，单位 kWh（度）；页面未给出时为 `null` |
| `balance_cny` | 页面明确给出的人民币余额；未给出时为 `null` |
| `usage_kwh` | 页面明确给出的本月、累计等已用电量；未给出时为 `{}` |
| `page_location` | 结果页原始房间位置，可用于核对 |
| `source_notes` | 结果页更新频率等说明 |
| `checked_at` | 本次读取时间，带北京时间时区；不是电表抄表时间 |
| `selection_ids` | 本次使用的楼栋、楼层和房间内部编号 |

西校区 26 号北楼 8 楼 814 的实际结果页显示“剩余电（水）量”，单位为 `kW·h`，并注明“每小时更新，未尽事宜请到营业室咨询。”该页没有人民币余额和已用电量，因此返回 `balance_cny: null`、`usage_kwh: {}`，不按假定电价换算。最近实测值与读取时间见 `verification-electricity.json`。

## 流程与失败处理

- 同一个 Cookie 会话执行初始 GET、两级单选回发、楼栋/楼层回发及查询。每次提交都使用最新响应的隐藏字段，包括分段 `__VIEWSTATE`，不硬编码 `__VIEWSTATEGENERATOR`。
- 从页面读取真实 `__doPostBack` 目标。当前单选事件使用 `RadioButtonList2$0` 等子控件名，与普通表单字段名不同。
- 查询跳转 CAS 时提取动态 `execution` 与 `pwdEncryptSalt`，复用项目已经验证的 AES-128-CBC 登录实现（随机前缀、随机 IV、PKCS7 填充），保持原始 service URL，跟随票据回调后重新选择完整表单。
- 不使用固定 IV，也不截断或猜测 64 字节 salt。遇到验证码、认证拒绝、未知加密参数或认证后再次跳回登录页即报错；单次查询最多提交一次密码。同一客户端两次认证尝试至少间隔 5 分钟。
- 选项不存在/不唯一、状态缺失、结果字段缺失或冲突均明确报错；不会把解析失败当成零余额。网络错误不自动重试。

可用 `python -m unittest -v test_electricity` 运行模拟站点测试。脚本仅提交查询与必要回发，不执行充值；本次验证也没有触发 QQ 通知。
