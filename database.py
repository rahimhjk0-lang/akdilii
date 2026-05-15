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
    # أنشئ الجداول الجديدة
    Base.metadata.create_all(bind=engine)
    # تشغيل migrations يدوية للـ columns الجديدة
    _run_migrations()
    print("✅ قاعدة البيانات جاهزة")


def _run_migrations():
    """يضيف columns جديدة للجداول الموجودة بطريقة آمنة"""
    from sqlalchemy import text, inspect

    migrations = [
        ("merchants", "webhook_token", "VARCHAR(64)"),
        ("merchants", "sub_active",    "BOOLEAN DEFAULT FALSE"),
        ("merchants", "sub_expires",   "TIMESTAMP"),
        ("merchants", "sub_plan",      "VARCHAR(50)"),
        ("carriers",  "api_id",        "TEXT"),
    ]

    insp = inspect(engine)
    with engine.connect() as conn:
        for table, col, col_type in migrations:
            try:
                existing = [c["name"] for c in insp.get_columns(table)]
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                    conn.commit()
                    print(f"[MIGRATION] ✅ أضفنا {table}.{col}")
                else:
                    pass  # موجود مسبقاً
            except Exception as e:
                print(f"[MIGRATION] ⚠️ {table}.{col}: {e}")
                try: conn.rollback()
                except: pass
    print("✅ Migrations شغالة")

