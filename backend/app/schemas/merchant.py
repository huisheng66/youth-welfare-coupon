import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel

# 经纬度以文本存高德拾取器输出：可选负号 + 整数部分 ≤3 位 + 最多 8 位小数
_COORD_RE = re.compile(r"^-?\d{1,3}(\.\d{1,8})?$")


def _validate_coord(label: str, value: str | None, low: float, high: float) -> str:
    if value is None:
        return ""
    v = value.strip()
    if not v:
        return ""
    if not _COORD_RE.match(v) or not (low <= float(v) <= high):
        raise ValueError(f"无效的{label}（示例：116.397428）")
    return v


class MerchantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    contact_name: str = ""
    contact_phone: str = ""
    address: str = ""
    description: str = ""
    longitude: str = ""
    latitude: str = ""

    @field_validator("longitude")
    @classmethod
    def _check_longitude(cls, v: str) -> str:
        return _validate_coord("经度", v, -180.0, 180.0)

    @field_validator("latitude")
    @classmethod
    def _check_latitude(cls, v: str) -> str:
        return _validate_coord("纬度", v, -90.0, 90.0)


class MerchantUpdate(BaseModel):
    name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    address: str | None = None
    description: str | None = None
    is_active: bool | None = None
    longitude: str | None = None
    latitude: str | None = None

    @field_validator("longitude")
    @classmethod
    def _check_longitude(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_coord("经度", v, -180.0, 180.0)

    @field_validator("latitude")
    @classmethod
    def _check_latitude(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_coord("纬度", v, -90.0, 90.0)


class MerchantOut(ORMModel):
    id: str
    name: str
    contact_name: str
    contact_phone: str
    address: str
    description: str
    is_active: bool
    created_at: datetime
    longitude: str
    latitude: str
    has_photo: bool
    photo_updated_at: datetime | None = None


class GeoResultOut(BaseModel):
    """高德 POI 搜索结果（GCJ-02），供管理端点选填入经纬度。"""

    name: str
    address: str
    longitude: str
    latitude: str
