from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum

# ==========================================
# جدول التجار
# ==========================================
class Merchant(Base):
    __tablename__ = "merchants"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(100), nullable=False)
    email      = Column(String(150), unique=True, nullable=False)
    password   = Column(String(255), nullable=False)  # مشفرة
    phone      = Column(String(20), nullable=True)
    plan       = Column(String(50), default="starter")
    is_active  = Column(Boolean, default=True)
    orders_used= Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    # العلاقات
    carriers       = relationship("Carrier", back_populates="merchant", cascade="all, delete")
    parcels        = relationship("Parcel",  back_populates="merchant", cascade="all, delete")


# ==========================================
# جدول شركات التوصيل المربوطة بكل تاجر
# ==========================================
class Carrier(Base):
    __tablename__ = "carriers"

    id           = Column(Integer, primary_key=True, index=True)
    merchant_id  = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    carrier_code = Column(String(50), nullable=False)   # yalidine, zr_express...
    carrier_name = Column(String(100), nullable=False)
    api_key      = Column(Text, nullable=True)           # API Token
    api_id       = Column(Text, nullable=True)           # API ID (Yalidine)
    is_connected = Column(Boolean, default=False)
    created_at   = Column(DateTime, server_default=func.now())

    # العلاقات
    merchant = relationship("Merchant", back_populates="carriers")
    parcels  = relationship("Parcel",   back_populates="carrier")


# ==========================================
# جدول الطرود
# ==========================================
class DeliveryType(str, enum.Enum):
    home   = "home"    # توصيل للمنزل
    office = "office"  # توصيل للمكتب

class ParcelStatus(str, enum.Enum):
    at_origin        = "at_origin"        # وصل مكتب الإرسال
    in_transit       = "in_transit"       # في الطريق
    at_destination   = "at_destination"   # وصل مكتب الوصول
    out_for_delivery = "out_for_delivery" # عند الساعي
    delivered        = "delivered"        # تم التسليم
    failed_attempt   = "failed_attempt"   # محاولة فاشلة
    returned         = "returned"         # مرتجع

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

    # العلاقات
    merchant = relationship("Merchant", back_populates="parcels")
    carrier  = relationship("Carrier",  back_populates="parcels")
    events   = relationship("TrackingEvent", back_populates="parcel", cascade="all, delete")


# ==========================================
# جدول تحديثات التتبع
# ==========================================
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

    # العلاقات
    parcel = relationship("Parcel", back_populates="events")


# ==========================================
# جدول الإشعارات المرسلة
# ==========================================
class Notification(Base):
    __tablename__ = "notifications"

    id          = Column(Integer, primary_key=True, index=True)
    parcel_id   = Column(Integer, ForeignKey("parcels.id"), nullable=False)
    channel     = Column(String(20), nullable=False)  # whatsapp / sms
    phone       = Column(String(20), nullable=False)
    message     = Column(Text,       nullable=False)
    status      = Column(String(20), default="sent")  # sent / failed
    sent_at     = Column(DateTime, server_default=func.now())
