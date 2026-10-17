"""导出账号在「宿舍卫生 / 查寝」模块下的全部数据.

用法:
    set SDUT_USER=25110103112
    set SDUT_PWD=******
    python export_ssws.py

产出:
    data/ssws_all.json      完整结构化数据(原始字段 + 元信息)
    data/ssws_records.csv   扁平表格(中文表头, Excel 可直接打开)
    data/ssws_summary.txt   可读汇总
"""
import csv
import io
import json
import os
import sys
import time
from collections import Counter

from sdut_ssws import SswsClient, CTRL, FIELD_MAP

CSV_COLUMNS = [
    ("JCRQ", "检查日期"), ("XN_DISPLAY", "学年"), ("XQ_DISPLAY", "学期"),
    ("SSLMC", "宿舍楼"), ("FJH", "房间号"), ("BJ", "班级"), ("XSBH", "学号"), ("XQMC", "校区"),
    ("FS", "分数"), ("JCFS", "基础分"), ("DJMC", "等级"),
    ("JCLXDM_DISPLAY", "检查类型"), ("ZC", "周次"),
    ("WGXX", "违规信息"), ("WGLXDM_DISPLAY", "违规类型"),
    ("CZZ", "检查人"), ("WID", "记录ID"),
]


def main():
    user = os.environ.get("SDUT_USER") or (sys.argv[1] if len(sys.argv) > 1 else None)
    pwd = os.environ.get("SDUT_PWD") or (sys.argv[2] if len(sys.argv) > 2 else None)
    if not user or not pwd:
        print(__doc__)
        return 2

    os.makedirs("data", exist_ok=True)
    c = SswsClient(user, pwd)
    roles = c.bootstrap()

    out = io.StringIO()
    def w(*a): print(*a, file=out)

    w("登录账号: %s" % user)
    w("角色    : %s" % json.dumps(roles, ensure_ascii=False))
    w("")

    dz = c.list_records(page_size=50, max_pages=50, endpoint="dz")
    nw = c.list_records(page_size=50, max_pages=50, endpoint="new")
    w("列表 Dz  : %d 条" % len(dz))
    w("列表 New : %d 条" % len(nw))

    config = c._post(CTRL + "getSetInfo.do", {}).get("data") or {}
    w("配置     : %s" % json.dumps(config, ensure_ascii=False))
    w("")

    details, failed = {}, 0
    for r in dz:
        wid = r.get("WID")
        try:
            d = c._post(CTRL + "getSswsStuDetail.do", {"WID": wid}).get("data")
            details[wid] = d[0] if isinstance(d, list) and d else (d or {})
        except Exception as e:
            failed += 1
            details[wid] = {"__error__": str(e)}
    w("详情     : %d/%d 成功, %d 失败" % (len(dz) - failed, len(dz), failed))
    w("")

    merged = []
    for r in dz:
        rec = dict(r)
        for k, v in details.get(r.get("WID"), {}).items():
            rec.setdefault(k, v)
        merged.append(rec)
    merged.sort(key=lambda x: (x.get("JCRQ") or "", x.get("WID") or ""), reverse=True)

    with open("data/ssws_records.csv", "w", encoding="utf-8-sig", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow([n for _, n in CSV_COLUMNS])
        for r in merged:
            wr.writerow([r.get(k, "") for k, _ in CSV_COLUMNS])

    with open("data/ssws_all.json", "w", encoding="utf-8") as fh:
        json.dump({"export_time": time.strftime("%Y-%m-%d %H:%M:%S"), "account": user,
                   "roles": roles, "config": config,
                   "counts": {"list_dz": len(dz), "list_new": len(nw), "detail_failed": failed},
                   "field_map": FIELD_MAP, "records_raw": merged},
                  fh, ensure_ascii=False, indent=2)

    w("### 全部 %d 条记录 (检查日期倒序) ###" % len(merged))
    w("")
    w("%-12s %-10s %-8s %-6s %-6s %s" % ("检查日期", "宿舍楼", "房间号", "分数", "等级", "违规信息"))
    w("-" * 100)
    for r in merged:
        w("%-12s %-10s %-8s %-6s %-6s %s" % (r.get("JCRQ", ""), r.get("SSLMC", ""), r.get("FJH", ""),
                                             r.get("FS", ""), r.get("DJMC", ""), (r.get("WGXX") or "-")[:48]))
    w("")
    w("### 统计 ###")
    w("  等级分布 : %s" % dict(Counter(r.get("DJMC") for r in merged)))
    w("  日期范围 : %s ~ %s" % (merged[-1].get("JCRQ"), merged[0].get("JCRQ")))
    fs = [r.get("FS") for r in merged if isinstance(r.get("FS"), (int, float))]
    if fs:
        w("  分数     : 平均 %.1f / 最高 %.0f / 最低 %.0f" % (sum(fs) / len(fs), max(fs), min(fs)))

    open("data/ssws_summary.txt", "w", encoding="utf-8").write(out.getvalue())
    print("导出完成: %d 条 -> data/ssws_all.json, data/ssws_records.csv" % len(merged))
    return 0


if __name__ == "__main__":
    sys.exit(main())
