"""
SQLAlchemy models for MailPulse.
Matches the data model from the project doc: recipients, campaigns, sends, opens, replies.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text, Float
)
from sqlalchemy.orm import relationship
from app.database import Base


class Recipient(Base):
    __tablename__ = "recipients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    company = Column(String, nullable=True)
    role = Column(String, nullable=True)
    custom_fields = Column(Text, nullable=True)  # JSON string for arbitrary merge fields

    sends = relationship("Send", back_populates="recipient")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    template_variant = Column(String, nullable=True)  # e.g. "A" or "B" for A/B testing
    subject_template = Column(Text, nullable=False)
    body_template = Column(Text, nullable=False)
    follow_up_subject_template = Column(Text, nullable=True)
    follow_up_body_template = Column(Text, nullable=True)
    follow_up_after_days = Column(Integer, default=3)
    max_follow_ups = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    sends = relationship("Send", back_populates="campaign")


class Send(Base):
    __tablename__ = "sends"

    id = Column(Integer, primary_key=True, index=True)
    recipient_id = Column(Integer, ForeignKey("recipients.id"))
    campaign_id = Column(Integer, ForeignKey("campaigns.id"))
    sent_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="sent")  # sent, bounced, failed
    is_follow_up = Column(Integer, default=0)  # 0 = original, 1+ = follow-up number
    message_id = Column(String, nullable=True)  # Gmail/SMTP message-id for thread tracking
    tracking_token = Column(String, unique=True, index=True)  # used in pixel/click URLs

    recipient = relationship("Recipient", back_populates="sends")
    campaign = relationship("Campaign", back_populates="sends")
    opens = relationship("Open", back_populates="send")
    replies = relationship("Reply", back_populates="send")
    clicks = relationship("Click", back_populates="send")


class Open(Base):
    __tablename__ = "opens"

    id = Column(Integer, primary_key=True, index=True)
    send_id = Column(Integer, ForeignKey("sends.id"))
    opened_at = Column(DateTime, default=datetime.utcnow)
    open_count = Column(Integer, default=1)

    send = relationship("Send", back_populates="opens")


class Click(Base):
    __tablename__ = "clicks"

    id = Column(Integer, primary_key=True, index=True)
    send_id = Column(Integer, ForeignKey("sends.id"))
    clicked_at = Column(DateTime, default=datetime.utcnow)
    target_url = Column(Text, nullable=False)

    send = relationship("Send", back_populates="clicks")


class Reply(Base):
    __tablename__ = "replies"

    id = Column(Integer, primary_key=True, index=True)
    send_id = Column(Integer, ForeignKey("sends.id"))
    replied_at = Column(DateTime, default=datetime.utcnow)
    body = Column(Text, nullable=True)
    sentiment = Column(String, nullable=True)  # positive / neutral / negative

    send = relationship("Send", back_populates="replies")
