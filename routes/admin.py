from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
from database import get_db
from models import Merchant, Parcel, Notification
from config import ADMIN_PASSWORD, PLANS
from datetime import datetime, timedelta

router    = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")

# ==========================================
# التحقق من Admin
# ==========================================
def check_admin(request: Request):
    if not request.cookies.get("akdili_admin"):
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})

# ==========================================
# صفحة دخول Admin
# ==========================================
@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

@router.post("/login")
async def admin_login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        response = RedirectResponse(url="/admin", status_code=302)
        response.set_cookie("akdili_admin", "1", max_age=12*3600, httponly=True)
        return response
    return templates.TemplateResponse("admin_login.html", {
        "request": request,
        "error": "كلمة السر غلطة"
    })

@router.get("/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("akdili_admin")
    return response

# ==========================================
# لوحة Admin الرئيسية
# ==========================================
@router.get("", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    check_admin(request)

    merchants   = db.query(Merchant).order_by(Merchant.created_at.desc()).all()
    total       = len(merchants)
    active_subs = sum(1 for m in merchants if m.sub_active)
    expired     = sum(1 for m in merchants if not m.sub_active)
    total_parcels = db.query(Parcel).count()

    now = datetime.utcnow()
    # التجار اللي ينتهي اشتراكهم خلال 3 أيام
    expiring_soon = [
        m for m in merchants
        if m.sub_active and m.sub_expires and
        (m.sub_expires - now).days <= 3
    ]

    return templates.TemplateResponse("admin.html", {
        "request":      request,
        "merchants":    merchants,
        "total":        total,
        "active_subs":  active_subs,
        "expired":      expired,
        "total_parcels":total_parcels,
        "expiring_soon":expiring_soon,
        "plans":        PLANS,
        "now":          now,
    })

# ==========================================
# تفعيل اشتراك
# ==========================================
@router.post("/activate")
async def activate_subscription(
    merchant_id: int = Form(...),
    plan:        str = Form(...),
    days:        int = Form(30),
    db: Session = Depends(get_db),
    request: Request = None
):
    check_admin(request)

    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        return JSONResponse({"success": False, "error": "تاجر ما لقيناهش"})

    now = datetime.utcnow()
    # إذا عنده اشتراك نشط → نمدد من تاريخ الانتهاء
    if merchant.sub_active and merchant.sub_expires and merchant.sub_expires > now:
        merchant.sub_expires = merchant.sub_expires + timedelta(days=days)
    else:
        merchant.sub_expires = now + timedelta(days=days)

    merchant.sub_active = True
    merchant.sub_plan   = plan
    merchant.plan       = plan
    db.commit()

    return JSONResponse({
        "success": True,
        "message": f"✅ تم تفعيل {plan} لـ {merchant.name} حتى {merchant.sub_expires.strftime('%d/%m/%Y')}"
    })

# ==========================================
# إيقاف اشتراك
# ==========================================
@router.post("/deactivate")
async def deactivate_subscription(
    merchant_id: int = Form(...),
    db: Session = Depends(get_db),
    request: Request = None
):
    check_admin(request)

    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        return JSONResponse({"success": False})

    merchant.sub_active = False
    db.commit()
    return JSONResponse({"success": True})

# ==========================================
# حذف تاجر
# ==========================================
@router.post("/delete")
async def delete_merchant(
    merchant_id: int = Form(...),
    db: Session = Depends(get_db),
    request: Request = None
):
    check_admin(request)

    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if merchant:
        db.delete(merchant)
        db.commit()
    return JSONResponse({"success": True})
