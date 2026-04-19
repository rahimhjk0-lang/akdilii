from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import URL
from urllib.parse import urlparse, unquote
from config import DATABASE_URL

def build_engine(url_str: str):
    """يبني engine بطريقة آمنة بدون مشاكل parsing في كلمة السر أو اسم المستخدم"""
    url_str = url_str.strip()

    # SQLite — مباشر
    if "sqlite" in url_str:
        return create_engine(url_str, connect_args={"check_same_thread": False})

    # PostgreSQL — نحلّل يدوياً
    try:
        parsed = urlparse(url_str)
        engine_url = URL.create(
            drivername  = "postgresql+psycopg2",
            username    = unquote(parsed.username or "postgres"),
            password    = unquote(parsed.password or ""),
            host        = parsed.hostname,
            port        = parsed.port or 5432,
            database    = (parsed.path or "/postgres").lstrip("/") or "postgres",
        )
        return create_engine(engine_url, pool_pre_ping=True)
    except Exception as e:
        raise RuntimeError(f"خطأ في رابط قاعدة البيانات: {e}")

engine       = build_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from models import Merchant, Carrier, Parcel, TrackingEvent, Notification
    Base.metadata.create_all(bind=engine)
    print("✅ قاعدة البيانات جاهزة")

