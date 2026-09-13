from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


class RecipientIn(BaseModel):
    name: str
    email: EmailStr
    company: Optional[str] = None
    role: Optional[str] = None
    custom_fields: Optional[dict] = None


class CampaignIn(BaseModel):
    name: str
    template_variant: Optional[str] = "A"
    subject_template: str
    body_template: str
    follow_up_subject_template: Optional[str] = None
    follow_up_body_template: Optional[str] = None
    follow_up_after_days: int = 3
    max_follow_ups: int = 1


class CampaignOut(CampaignIn):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class SendCampaignRequest(BaseModel):
    campaign_id: int
    recipient_ids: Optional[list[int]] = None  # None = all recipients
    batch_size: int = 20
    delay_seconds: float = 2.0  # rate-limit between sends
