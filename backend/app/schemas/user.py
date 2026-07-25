from datetime import datetime

from pydantic import BaseModel, Field

from app.models.entities import VerifyStatus
from app.schemas.common import ORMModel


class ProfileUpdateIn(BaseModel):
    real_name: str = Field(default="", max_length=64)
    phone: str | None = Field(default=None, max_length=20)
    display_name: str | None = Field(default=None, max_length=64)
    id_number_masked: str = Field(default="", max_length=32)
    organization: str = Field(default="", max_length=128)
    remark: str = ""


class SubmitVerificationIn(BaseModel):
    material_note: str = Field(min_length=1, max_length=2000)


class ReviewVerificationIn(BaseModel):
    approve: bool
    review_note: str = ""


class VerificationOut(ORMModel):
    id: str
    profile_id: str
    material_note: str
    status: VerifyStatus
    reviewer_id: str | None
    review_note: str
    created_at: datetime
    reviewed_at: datetime | None
    # enriched fields for admin review
    user_id: str | None = None
    username: str | None = None
    real_name: str | None = None
    phone: str | None = None
    organization: str | None = None


class UserListItem(ORMModel):
    id: str
    username: str
    display_name: str
    phone: str | None
    real_name: str
    organization: str
    verify_status: VerifyStatus
    created_at: datetime
    id_number_masked: str | None = None
    remark: str | None = None
    latest_material_note: str | None = None


class BatchReviewIn(BaseModel):
    verification_ids: list[str] = Field(min_length=1, max_length=100)
    approve: bool
    review_note: str = ""
