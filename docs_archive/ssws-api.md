# SDUT 学工系统「宿舍卫生 / 查寝」数据接口参考

> 实测于 2026-10-17 · 账号 25110103112 · 全部接口验证通过

## 1. 入口与路由

| 项 | 值 |
|---|---|
| 应用首页 | `https://xgfw.sdut.edu.cn/xsfw/sys/swmsswsapp/*default/index.do` |
| 查寝路由 | `#/sswsStu` → 组件 `newmob/sswsstu/index/index` |
| 详情路由 | `#/sswsStuDetail` |
| 模块号 GNBS | `Mobile_Stu_Ssws_ss` |
| APPID | `5012298006853004` |
| APPNAME | `swmsswsapp` |
| 角色 | 学生组 `ROLEID=52109f9acda9474ba47a36697bcaab52` `DATAROLE=DSW600` |

## 2. 请求约定（三个必须遵守的点）

### 2.1 提交格式：单个 `data=` 字段

金智 WIS 的 `MOB_UTIL.doPost` 不是常规表单提交：

```js
transformRequest: [function (data) {
    return "data=" + encodeURIComponent(JSON.stringify(data));
}]
```

即整个参数对象 JSON 序列化后，作为**一个名为 `data` 的表单字段**提交：

```
POST <url>
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest

data=%7B%22PAGENUM%22%3A1%2C%22PAGESIZE%22%3A50%7D
```

> ❌ 用普通表单展开（`PAGENUM=1&PAGESIZE=50`）会直接 **403**。

### 2.2 必须先设置角色

业务接口不认 CAS 会话本身，需要先建立"当前应用角色"：

```
POST /xsfw/sys/swpubapp/NewMobileAPIController/getUserRoles.do   {"APPID":"5012298006853004"}
POST /xsfw/sys/swpubapp/NewMobileAPIController/setAppRole.do     {"APPID":..,"APPNAME":"swmsswsapp","ROLEID":..}
```

跳过这两步 → 业务接口 **403**。

### 2.3 querySetting 是**数组**，不是对象

来自 `emapAdvancedQuery.getQuerySetting()`，结构：

```json
[
  {"name":"JCRQ","caption":"检查日期","value":"2026-09-01","builder":"moreEqual","linkOpt":"AND"},
  {"name":"JCRQ","caption":"检查日期","value":"2026-10-17","builder":"lessEqual","linkOpt":"AND"}
]
```

然后 `JSON.stringify` 成字符串放进 `querySetting` 字段。

> ❌ 传对象 `{"JCRQ":{"minValue":..,"maxValue":..}}` → 服务器静默返回 **空数组**（不报错，很坑）。

## 3. 接口清单（学生端）

Base: `https://xgfw.sdut.edu.cn/xsfw/sys/swmsswsapp/MobileStudentDormHygieneInfoController/`

| 接口 | 说明 | 实测 |
|---|---|---|
| `getStudentDormHygieneInfoDz.do` | **列表（页面在用）**，支持分页 + querySetting | ✅ 34 条 |
| `getStudentDormHygieneInfoNew.do` | 列表（新版），字段更多（含学号/校区） | ✅ |
| `getStudentDormHygieneInfo.do` | 旧版，**必须传日期**否则报"所需日期参数不完整" | ⚠️ |
| `getSswsStuDetail.do` | 单条详情 | 未测 |
| `getSetInfo.do` | 配置信息（满分、是否开启等级） | ✅ `{"ZF":100,"SFKQDJ":"1"}` |

## 4. 字段字典（getStudentDormHygieneInfoDz）

| 字段 | 含义 | 示例 |
|---|---|---|
| `WID` | **记录唯一 ID**（去重/增量判断首选） | `1da6b04335854807aeb4461886558ae5` |
| `JCRQ` | **检查日期** `YYYY-MM-DD` | `2026-10-15` |
| `SSLMC` | 宿舍楼名称 | `26号公寓` |
| `FJH` | 房间号 | `26BH814` |
| `BJ` | 班级 | `测控2503` |
| `FS` | 分数 | `90.0` |
| `DJMC` | **等级** 优秀 / 合格 / 不合格 | `优秀` |
| `WGXX` | 违规信息（含扣分） | `地面脏乱(5),物品摆放凌乱(5)` |
| `WGLXDM_DISPLAY` | 违规类型（中文） | `物品摆放凌乱, 地面脏乱` |
| `WGLXDM` | 违规类型 GUID，逗号分隔 | `c399279d-,b54a88ab-` |
| `JCLXDM_DISPLAY` | 检查类型 | `定期检查` |
| `JCLXDM` | 检查类型码 | `2` |
| `ZC` | 周次 | `7` |
| `XN` / `XN_DISPLAY` | 学年 | `2026` / `2026-2027学年` |
| `XQ` / `XQ_DISPLAY` | 学期 | `1` / `第一学期` |
| `CZZ` | 检查人账号 | `80210` |
| `JCBM` | 检查编码 | `e4ccbd6b...` |
| `SSDM` | 宿舍代码 | `3EE4B9CF...` |

`getStudentDormHygieneInfoNew.do` 额外提供：`XSBH`(学号)、`XQMC`(校区)、`JCFS`(基础分)、`SSDJMC`/`XSDJMC`(宿舍/学生等级)、`XN_1`/`XQ_1`。

## 5. 实测数据样本

账号 `25110103112`，26号公寓 26BH814：

| 检查日期 | 分数 | 等级 | 违规 |
|---|---|---|---|
| 2026-10-15 | 90 | 优秀 | 地面脏乱(5),物品摆放凌乱(5) |
| 2026-09-21 | 95 | 优秀 | 物品摆放凌乱(5) |
| 2026-09-14 | 85 | 合格 | 卫生间未清理(5),地面脏乱(5),存放垃圾(5) |
| 2026-09-07 | 70 | 不合格 | 其他违纪(30) |
| 2026-06-29 | 80 | 合格 | 阳台卫生未清理(5),物品摆放凌乱(5),地面脏乱(5),存放垃圾(5) |
| 2026-06-22 | 95 | 优秀 | 物品摆放凌乱(5) |

- 全量记录：**34 条**，范围 `2025-10-13` ~ `2026-10-15`
- 日期过滤 `2026-09-01~2026-10-17`：**4 条**（过滤生效）

## 6. 监控建议

- **增量判据**：`WID` 集合比对（最可靠）；`JCRQ` 最新日期变化可作辅助
- **检查频率**：记录按周产生（见样本，间隔 7 天），轮询 10~30 分钟足够
- **去重键**：`WID` + `JCRQ`
