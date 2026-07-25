from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class MerchantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    contact_name: str = ""
    contact_phone: str = ""
    address: str = ""
    description: str = ""


class MerchantUpdate(BaseModel):
    name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    address: str | None = None
    description: str | None = None
    is_active: bool | None = None


class MerchantOut(ORMModel):
    id: str
    name: str
    contact_name: str
    contact_phone: str
    address: str
    description: str
    is_active: bool
    created_at: datetime
