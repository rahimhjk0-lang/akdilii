from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta
from database import get_db
from models import Merchant
from config import SECRET_KEY, PLANS

router    = APIRouter()
templates = Jinja2Templates(directory="templates")
pwd_ctx   = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_ctx.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)

def create_token(merchant_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=30)
    return jwt.encode({"sub": str(merchant_id), "exp": expire}, SECRET_KEY, algorithm="HS256")

def get_current_merchant(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("akdili_token")
    if not token:
        raise HTTPException(status_code=401)
    try:
        payload     = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        merchant_id = int(payload.get("sub"))
        merchant    = db.query(Merchant).filter(Merchant.id == merchant_id).first()
        if not merchant:
            raise HTTPException(status_code=401)
        return merchant
    except Exception:
        raise HTTPException(status_code=401)

# ---- صفحة التسجيل ----
@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@router.post("/register")
async def register(
    request:  Request,
    name:     str = Form(...),
    email:    str = Form(...),
    password: str = Form(...),
    phone:    str = Form(""),
    db: Session = Depends(get_db)
):
    existing = db.query(Merchant).filter(Merchant.email == email).first()
    if existing:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "الإيميل مسجل مسبقاً"
        })

    try:
        merchant = Merchant(
            name     = name,
            email    = email,
            password = hash_password(password),
            phone    = phone,
            plan     = "free"
        )
        db.add(merchant)
        db.commit()
        db.refresh(merchant)
    except Exception as e:
        db.rollback()
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": f"خطأ في قاعدة البيانات: {str(e)}"
        })

    token    = create_token(merchant.id)
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie("akdili_token", token, max_age=30*24*3600, httponly=True)
    return response

# ---- صفحة الدخول ----
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login")
async def login(
    request:  Request,
    email:    str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        merchant = db.query(Merchant).filter(Merchant.email == email).first()
    except Exception as e:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": f"خطأ في قاعدة البيانات: {str(e)}"
        })

    if not merchant or not verify_password(password, merchant.password):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "إيميل أو كلمة سر غلطة"
        })

    token    = create_token(merchant.id)
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie("akdili_token", token, max_age=30*24*3600, httponly=True)
    return response

# ---- تسجيل الخروج ----
@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("akdili_token")
    return response
