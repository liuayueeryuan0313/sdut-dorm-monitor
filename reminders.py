"""Monthly dorm internet-fee notice formatting and calendar calculations."""
import calendar
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

CHINA = timezone(timedelta(hours=8))


def money(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("每人金额必须是有效数字")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or not Decimal("0.01") <= amount <= Decimal("999999.99"):
            raise ValueError("每人金额范围为 0.01 至 999999.99 元")
        cents = amount.quantize(Decimal("0.01"))
        if cents != amount:
            raise ValueError("每人金额最多保留两位小数")
        return format(cents, ".2f")
    except InvalidOperation:
        raise ValueError("每人金额必须是有效数字") from None


def total_amount(config):
    return format(Decimal(money(config["fee_amount"])) * config["fee_people"], ".2f")


def month_date(now, day, clock):
    now = now.astimezone(CHINA)
    hour, minute = map(int, clock.split(":"))
    day = min(day, calendar.monthrange(now.year, now.month)[1])
    return datetime(now.year, now.month, day, hour, minute, tzinfo=CHINA)


def following_month(now):
    return now.replace(year=now.year + (now.month == 12), month=now.month % 12 + 1, day=1)


def fee_message(config, now):
    now = now.astimezone(CHINA)
    month = "%d年%d月" % (now.year, now.month)
    amount = money(config["fee_amount"])
    return ("【%s宿舍网费缴纳通知】\n"
            "缴费人数：%d 人\n"
            "每人应缴：%s 元\n"
            "本月合计：%s 元\n\n"
            "请大家前往微信宿舍群转账，每人转账 %s 元，"
            "并备注姓名和%s网费。") % (
                month, config["fee_people"], amount, total_amount(config), amount, month)
