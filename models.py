from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum

class Merchant(Base):
    __tablename__ = "merchants"

    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String(100), nullable=False)
    email         = Column(String(150), unique=True, nullable=False)
    password      = Column(String(255), nullable=False)
    phone         = Column(String(20),  nullable=True)
    plan          = Column(String(50),  default="starter")
    is_active     = Column(Boolean, default=True)
    orders_used   = Column(Integer, default=0)
    created_at    = Column(DateTime, server_default=func.now())

    # ---- الاشتراك ----
    sub_active    = Column(Boolean,  default=False)   # هل الاشتراك فعّال؟
    sub_expires   = Column(DateTime, nullable=True)    # تاريخ الانتهاء
    sub_plan      = Column(String(50), nullable=True)  # الباقة المدفوعة

    carriers  = relationship("Carrier", back_populates="merchant", cascade="all, delete")
    parcels   = relationship("Parcel",  back_populates="merchant", cascade="all, delete")


class Carrier(Base):
    __tablename__ = "carriers"

    id           = Column(Integer, primary_key=True, index=True)
    merchant_id  = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    carrier_code = Column(String(50),  nullable=False)
    carrier_name = Column(String(100), nullable=False)
    api_key      = Column(Text, nullable=True)
    api_id       = Column(Text, nullable=True)
    is_connected = Column(Boolean, default=False)
    created_at   = Column(DateTime, server_default=func.now())

    merchant = relationship("Merchant", back_populates="carriers")
    parcels  = relationship("Parcel",   back_populates="carrier")


class DeliveryType(str, enum.Enum):
    home   = "home"
    office = "office"

class ParcelStatus(str, enum.Enum):
    at_origin        = "at_origin"
    in_transit       = "in_transit"
    at_destination   = "at_destination"
    out_for_delivery = "out_for_delivery"
    delivered        = "delivered"
    failed_attempt   = "failed_attempt"
    returned         = "returned"

class Parcel(Base):
    __tablename__ = "parcels"

    id               = Column(Integer, primary_key=True, index=True)
    merchant_id      = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    carrier_id       = Column(Integer, ForeignKey("carriers.id"),  nullable=False)
    tracking_number  = Column(String(100), unique=True, nullable=False)
    customer_name    = Column(String(100), nullable=False)
    customer_phone   = Column(String(20),  nullable=False)
    wilaya           = Column(String(50),  nullable=True)
    delivery_type    = Column(String(20),  default="home")
    current_status   = Column(String(50),  default="at_origin")
    is_active        = Column(Boolean, default=True)
    created_at       = Column(DateTime, server_default=func.now())
    updated_at       = Column(DateTime, server_default=func.now(), onupdate=func.now())

    merchant = relationship("Merchant", back_populates="parcels")
    carrier  = relationship("Carrier",  back_populates="parcels")
    events   = relationship("TrackingEvent", back_populates="parcel", cascade="all, delete")


class TrackingEvent(Base):
    __tablename__ = "tracking_events"

    id            = Column(Integer, primary_key=True, index=True)
    parcel_id     = Column(Integer, ForeignKey("parcels.id"), nullable=False)
    status        = Column(String(50),  nullable=False)
    location      = Column(String(100), nullable=True)
    description   = Column(Text,        nullable=True)
    whatsapp_sent = Column(Boolean, default=False)
    sms_sent      = Column(Boolean, default=False)
    event_time    = Column(DateTime, server_default=func.now())

    parcel = relationship("Parcel", back_populates="events")


class Notification(Base):
    __tablename__ = "notifications"

    id          = Column(Integer, primary_key=True, index=True)
    parcel_id   = Column(Integer, ForeignKey("parcels.id"), nullable=False)
    channel     = Column(String(20), nullable=False)
    phone       = Column(String(20), nullable=False)
    message     = Column(Text,       nullable=False)
    status      = Column(String(20), default="sent")
    sent_at     = Column(DateTime, server_default=func.now())
