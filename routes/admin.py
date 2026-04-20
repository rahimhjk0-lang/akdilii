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

def is_admin(req): return req.cookies.get("akdili_admin") == "1"

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

@router.post("/login")
async def login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        resp = RedirectResponse("/admin", status_code=302)
        resp.set_cookie("akdili_admin", "1", max_age=12*3600, httponly=True)
        return resp
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": "كلمة السر غلطة"})

@router.get("/logout")
async def logout():
    resp = RedirectResponse("/admin/login", status_code=302)
    resp.delete_cookie("akdili_admin")
    return resp

@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    try:
        rows = db.execute(text("SELECT id, name, email, plan, sub_active FROM merchants ORDER BY id DESC")).fetchall()
        merchants = []
        for row in rows:
            merchants.append({
                "id":     row[0],
                "name":   row[1],
                "email":  row[2],
                "plan":   (row[3] or "starter").upper(),
                "active": bool(row[4]),
            })
        return templates.TemplateResponse("admin.html", {
            "request":   request,
            "merchants": merchants,
            "total":     len(merchants),
            "active":    sum(1 for m in merchants if m["active"]),
            "plans":     PLANS,
        })
    except Exception as ex:
        return HTMLResponse(f"<pre style='color:red;padding:20px;direction:ltr'>ERROR: {ex}</pre>", status_code=500)

@router.post("/activate")
async def activate(request: Request, merchant_id: int = Form(...), plan: str = Form(...), days: int = Form(30), db: Session = Depends(get_db)):
    if not is_admin(request): return JSONResponse({"ok": False})
    m = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not m: return JSONResponse({"ok": False, "msg": "ما لقيناهش"})
    now  = datetime.utcnow()
    base = m.sub_expires if (m.sub_active and m.sub_expires and m.sub_expires > now) else now
    m.sub_expires = base + timedelta(days=days)
    m.sub_active = True
    m.sub_plan   = plan
    m.plan       = plan
    db.commit()
    return JSONResponse({"ok": True, "msg": f"تم تفعيل {plan} لـ {m.name}"})

@router.post("/deactivate")
async def deactivate(request: Request, merchant_id: int = Form(...), db: Session = Depends(get_db)):
    if not is_admin(request): return JSONResponse({"ok": False})
    m = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if m:
        m.sub_active = False
        db.commit()
    return JSONResponse({"ok": True})

@router.post("/delete")
async def delete_merchant(request: Request, merchant_id: int = Form(...), db: Session = Depends(get_db)):
    if not is_admin(request): return JSONResponse({"ok": False})
    m = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if m:
        db.delete(m)
        db.commit()
    return JSONResponse({"ok": True})

@router.post("/edit")
async def edit(request: Request, merchant_id: int = Form(...), name: str = Form(...), email: str = Form(...), db: Session = Depends(get_db)):
    if not is_admin(request): return JSONResponse({"ok": False})
    m = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if m:
        m.name  = name
        m.email = email
        db.commit()
    return JSONResponse({"ok": True})
