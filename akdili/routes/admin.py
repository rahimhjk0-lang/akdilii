from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from models import Merchant
from config import ADMIN_PASSWORD, PLANS
from datetime import datetime, timedelta

router    = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")

def is_admin(request: Request):
    return request.cookies.get("akdili_admin") == "1"

# ── Login ──────────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

@router.post("/login")
async def login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        r = RedirectResponse("/admin", status_code=302)
        r.set_cookie("akdili_admin", "1", max_age=12*3600, httponly=True)
        return r
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": "كلمة السر غلطة"})

@router.get("/logout")
async def logout():
    r = RedirectResponse("/admin/login", status_code=302)
    r.delete_cookie("akdili_admin")
    return r

# ── لوحة الأدمن الرئيسية ───────────────────────────────
@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=302)

    rows = db.execute(text("""
        SELECT
            m.id,
            m.name,
            m.email,
            m.phone,
            m.plan,
            m.sub_plan,
            m.sub_active,
            m.sub_expires,
            m.created_at,
            COUNT(p.id) AS parcel_count
        FROM merchants m
        LEFT JOIN parcels p ON p.merchant_id = m.id
        GROUP BY m.id
        ORDER BY m.created_at DESC
    """)).fetchall()

    merchants = []
    for r in rows:
        merchants.append({
            "id":           r[0],
            "name":         r[1],
            "email":        r[2],
            "phone":        r[3] or "—",
            "plan":         (r[5] or r[4] or "starter").upper(),
            "sub_active":   bool(r[6]),
            "sub_expires":  r[7].strftime("%d/%m/%Y") if r[7] else "—",
            "created_at":   r[8].strftime("%d/%m/%Y") if r[8] else "—",
            "parcel_count": r[9],
        })

    total        = len(merchants)
    active_count = sum(1 for m in merchants if m["sub_active"])

    return templates.TemplateResponse("admin.html", {
        "request":  request,
        "merchants": merchants,
        "total":     total,
        "active":    active_count,
        "plans":     PLANS,
    })

# ── تفعيل ──────────────────────────────────────────────
@router.post("/activate")
async def activate(request: Request, merchant_id: int = Form(...), plan: str = Form(...), days: int = Form(30), db: Session = Depends(get_db)):
    if not is_admin(request):
        return JSONResponse({"ok": False})
    m = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not m:
        return JSONResponse({"ok": False, "msg": "تاجر ما لقيناهش"})
    now = datetime.utcnow()
    base = m.sub_expires if (m.sub_active and m.sub_expires and m.sub_expires > now) else now
    m.sub_expires = base + timedelta(days=days)
    m.sub_active  = True
    m.sub_plan    = plan
    m.plan        = plan
    db.commit()
    return JSONResponse({"ok": True, "msg": f"✅ تم تفعيل {plan} لـ {m.name} حتى {m.sub_expires.strftime('%d/%m/%Y')}"})

# ── إيقاف ──────────────────────────────────────────────
@router.post("/deactivate")
async def deactivate(request: Request, merchant_id: int = Form(...), db: Session = Depends(get_db)):
    if not is_admin(request):
        return JSONResponse({"ok": False})
    m = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if m:
        m.sub_active = False
        db.commit()
    return JSONResponse({"ok": True})

# ── حذف ────────────────────────────────────────────────
@router.post("/delete")
async def delete(request: Request, merchant_id: int = Form(...), db: Session = Depends(get_db)):
    if not is_admin(request):
        return JSONResponse({"ok": False})
    m = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if m:
        db.delete(m)
        db.commit()
    return JSONResponse({"ok": True})

# ── تعديل ──────────────────────────────────────────────
@router.post("/edit")
async def edit(request: Request, merchant_id: int = Form(...), name: str = Form(...), email: str = Form(...), phone: str = Form(""), db: Session = Depends(get_db)):
    if not is_admin(request):
        return JSONResponse({"ok": False})
    m = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if m:
        m.name  = name
        m.email = email
        m.phone = phone
        db.commit()
    return JSONResponse({"ok": True})
