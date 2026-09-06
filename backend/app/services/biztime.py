"""业务时区统一（T18）：统计与导出按 Asia/Shanghai 定义"业务日"。

数据库一律存 UTC；"今天"的口径由业务时区决定——
北京时间跨午夜后，列表、仪表盘、导出的"今日"口径一致。
半开区间 [start, end)：与 SQL 的 >= / <= 组合时 to 侧取次日零点前的一刻。
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone, tzinfo
from zoneinfo import ZoneInfo

BUSINESS_TZ: tzinfo = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc


def biz_today_start_utc(now: datetime | None = None) -> datetime:
    """业务时区"今天 00:00"对应的 UTC 时刻（半开区间下界）。"""
    ref = (now or datetime.now(UTC)).astimezone(BUSINESS_TZ)
    local_midnight = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(UTC)


def day_bounds_utc(
    date_from: date | None,
    date_to: date | None,
) -> tuple[datetime | None, datetime | None]:
    """业务日期区间 → UTC 半开区间 [from 00:00, to+1d 00:00)。

    调用方约定：start 用 >=，end 用 <（半开）。若既有代码用 <=（闭区间），
    传入的 end 已是"当日 23:59:59"语义时保持原行为，由调用方自行适配。
    """
    start = None
    end = None
    if date_from:
        start = (
            datetime.combine(date_from, time.min, tzinfo=BUSINESS_TZ).astimezone(UTC)
        )
    if date_to:
        end = (
            datetime.combine(date_to, time.min, tzinfo=BUSINESS_TZ).astimezone(UTC)
        )
    return start, end


def day_bounds_utc_closed(
    date_from: date | None,
    date_to: date | None,
) -> tuple[datetime | None, datetime | None]:
    """闭区间版本：[from 00:00, to 23:59:59.999999]（兼容既有 <= 过滤）。"""
    start, end = day_bounds_utc(date_from, date_to)
    if end is not None:
        from datetime import timedelta

        end = end + timedelta(days=1) - timedelta(microseconds=1)
    return start, end
