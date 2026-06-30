from fastapi import FastAPI, APIRouter, HTTPException, Header, Query
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import secrets
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

#mongo_url = os.environ["MONGO_URL"]
#client = AsyncIOMotorClient(mongo_url)
#db = client[os.environ["DB_NAME"]]
MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DB_NAME", "health-assist-hub-2")

if not MONGO_URL:
    raise RuntimeError("MONGO_URL environment variable is missing")

client = AsyncIOMotorClient(
    MONGO_URL,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000,
)
db = client[DB_NAME]

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "aevum-admin-2025")

app = FastAPI(title="Aevum Health API")
api = APIRouter(prefix="/api")

# ---------- Seed data ----------
SEED_SERVICES = [
    {
        "id": "gp",
        "title": "General Physician",
        "subtitle": "MBBS doctor at your doorstep",
        "price": 999,
        "duration": "30 min",
        "rating": 4.9,
        "image": "https://images.pexels.com/photos/7653119/pexels-photo-7653119.jpeg?auto=compress&cs=tinysrgb&w=1200",
        "icon": "Stethoscope",
        "description": "Same-day MBBS / MD doctor consultation at your home. Includes physical exam, prescription, and follow-up note.",
    },
    {
        "id": "nurse",
        "title": "Home Nurse",
        "subtitle": "Trained nurse for daily care",
        "price": 1299,
        "duration": "60 min",
        "rating": 4.8,
        "image": "https://images.unsplash.com/photo-1631815590058-860e4f83c1e8?auto=format&fit=crop&w=1200&q=80",
        "icon": "HeartPulse",
        "description": "IV, injections, wound dressing, post-op recovery and chronic care by certified GNM nurses.",
    },
    {
        "id": "physio",
        "title": "Physiotherapist",
        "subtitle": "Recover & rebuild at home",
        "price": 799,
        "duration": "45 min",
        "rating": 4.7,
        "image": "https://images.unsplash.com/photo-1706353399656-210cca727a33?auto=format&fit=crop&w=1200&q=80",
        "icon": "Activity",
        "description": "Targeted physiotherapy for back pain, sports injury, post-stroke and orthopaedic recovery.",
    },
    {
        "id": "lab",
        "title": "Lab Sample Collection",
        "subtitle": "Tests collected from home",
        "price": 299,
        "duration": "15 min",
        "rating": 4.7,
        "image": "https://images.unsplash.com/photo-1639772823849-6efbd173043c?auto=format&fit=crop&w=1200&q=80",
        "icon": "FlaskConical",
        "description": "NABL-accredited labs. 300+ tests including blood, urine, thyroid and full body checkups.",
    },
    {
        "id": "elderly",
        "title": "Elderly Care",
        "subtitle": "Compassionate senior care",
        "price": 1499,
        "duration": "120 min",
        "rating": 4.9,
        "image": "https://images.pexels.com/photos/36706841/pexels-photo-36706841.jpeg?auto=compress&cs=tinysrgb&w=1200",
        "icon": "HandHeart",
        "description": "Dedicated attendants and geriatricians for vitals, mobility, companionship and medication.",
    },
]


# ---------- Models ----------
class Service(BaseModel):
    id: str
    title: str
    subtitle: str
    price: int
    duration: str
    rating: float
    image: str
    icon: str
    description: str


class BookingCreate(BaseModel):
    service_id: str
    date: str
    slot: str
    name: str
    phone: str
    address: str
    city: Optional[str] = None
    age: Optional[str] = None
    gender: Optional[str] = None
    notes: Optional[str] = None
    pay_method: Optional[str] = None


class Booking(BaseModel):
    id: str = Field(default_factory=lambda: "bk_" + uuid.uuid4().hex[:10])
    service_id: str
    service_title: str
    service_image: str
    price: int
    duration: str
    date: str
    slot: str
    name: str
    phone: str
    address: str
    city: Optional[str] = None
    age: Optional[str] = None
    gender: Optional[str] = None
    notes: Optional[str] = None
    pay_method: Optional[str] = None
    status: str = "confirmed"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AdminLogin(BaseModel):
    password: str


class StatusUpdate(BaseModel):
    status: str


def _normalize_phone(p: str) -> str:
    return "".join(ch for ch in (p or "") if ch.isdigit())


def _phone_query(p: str) -> dict:
    """Match a stored phone by its last 10 digits (country-code agnostic)."""
    norm = _normalize_phone(p)
    tail = norm[-10:] if len(norm) >= 10 else norm
    if not tail:
        return {"phone": "__none__"}
    return {"phone": {"$regex": tail + "$"}}


def _scrub(doc: dict) -> dict:
    if not doc:
        return doc
    doc.pop("_id", None)
    if isinstance(doc.get("created_at"), datetime):
        doc["created_at"] = doc["created_at"].isoformat()
    return doc


async def _ensure_services_seeded():
    count = await db.services.count_documents({})
    if count == 0:
        await db.services.insert_many([dict(s) for s in SEED_SERVICES])


# ---------- Public routes ----------
@api.get("/")
async def root():
    return {"service": "Aevum Health API", "status": "ok"}


@api.get("/services", response_model=List[Service])
async def list_services():
    await _ensure_services_seeded()
    items = await db.services.find().to_list(length=100)
    return [Service(**_scrub(i)) for i in items]


@api.post("/bookings", response_model=Booking)
async def create_booking(payload: BookingCreate):
    svc = await db.services.find_one({"id": payload.service_id})
    if not svc:
        await _ensure_services_seeded()
        svc = await db.services.find_one({"id": payload.service_id})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")

    booking = Booking(
        service_id=svc["id"],
        service_title=svc["title"],
        service_image=svc["image"],
        price=svc["price"],
        duration=svc["duration"],
        date=payload.date,
        slot=payload.slot,
        name=payload.name.strip(),
        phone=_normalize_phone(payload.phone),
        address=payload.address.strip(),
        city=payload.city,
        age=payload.age,
        gender=payload.gender,
        notes=payload.notes,
        pay_method=payload.pay_method,
    )
    await db.bookings.insert_one(booking.dict())
    return booking


@api.get("/bookings", response_model=List[Booking])
async def list_user_bookings(phone: str = Query(..., min_length=4)):
    items = (
        await db.bookings.find(_phone_query(phone))
        .sort("created_at", -1)
        .to_list(length=200)
    )
    return [Booking(**_scrub(i)) for i in items]


@api.patch("/bookings/{booking_id}/cancel", response_model=Booking)
async def cancel_booking(booking_id: str, phone: str = Query(...)):
    bk = await db.bookings.find_one({"id": booking_id})
    if not bk:
        raise HTTPException(status_code=404, detail="Booking not found")
    norm = _normalize_phone(phone)
    tail = norm[-10:] if len(norm) >= 10 else norm
    if not tail or not bk["phone"].endswith(tail):
        raise HTTPException(status_code=403, detail="Phone mismatch")
    await db.bookings.update_one({"id": booking_id}, {"$set": {"status": "cancelled"}})
    bk["status"] = "cancelled"
    return Booking(**_scrub(bk))


# ---------- Admin routes ----------
async def _require_admin(token: Optional[str]):
    if not token:
        raise HTTPException(status_code=401, detail="Missing admin token")
    found = await db.admin_sessions.find_one({"token": token})
    if not found:
        raise HTTPException(status_code=401, detail="Invalid admin token")


@api.post("/admin/login")
async def admin_login(payload: AdminLogin):
    if payload.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Incorrect password")
    token = secrets.token_urlsafe(32)
    await db.admin_sessions.insert_one(
        {"token": token, "created_at": datetime.utcnow()}
    )
    return {"token": token}


@api.get("/admin/bookings", response_model=List[Booking])
async def admin_list_bookings(
    x_admin_token: Optional[str] = Header(default=None),
    status: Optional[str] = None,
    q: Optional[str] = None,
):
    await _require_admin(x_admin_token)
    query = {}
    if status and status != "all":
        query["status"] = status
    if q:
        query["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"phone": {"$regex": q, "$options": "i"}},
            {"service_title": {"$regex": q, "$options": "i"}},
            {"address": {"$regex": q, "$options": "i"}},
        ]
    items = (
        await db.bookings.find(query).sort("created_at", -1).to_list(length=1000)
    )
    return [Booking(**_scrub(i)) for i in items]


@api.get("/admin/stats")
async def admin_stats(x_admin_token: Optional[str] = Header(default=None)):
    await _require_admin(x_admin_token)
    total = await db.bookings.count_documents({})
    confirmed = await db.bookings.count_documents({"status": "confirmed"})
    completed = await db.bookings.count_documents({"status": "completed"})
    cancelled = await db.bookings.count_documents({"status": "cancelled"})
    pipeline = [
        {"$match": {"status": {"$in": ["confirmed", "completed"]}}},
        {"$group": {"_id": None, "revenue": {"$sum": "$price"}}},
    ]
    rev_agg = await db.bookings.aggregate(pipeline).to_list(length=1)
    revenue = rev_agg[0]["revenue"] if rev_agg else 0
    return {
        "total": total,
        "confirmed": confirmed,
        "completed": completed,
        "cancelled": cancelled,
        "revenue": revenue,
    }


@api.patch("/admin/bookings/{booking_id}/status", response_model=Booking)
async def admin_update_status(
    booking_id: str,
    payload: StatusUpdate,
    x_admin_token: Optional[str] = Header(default=None),
):
    await _require_admin(x_admin_token)
    if payload.status not in ("confirmed", "completed", "cancelled"):
        raise HTTPException(status_code=400, detail="Invalid status")
    res = await db.bookings.find_one_and_update(
        {"id": booking_id},
        {"$set": {"status": payload.status}},
        return_document=True,
    )
    if not res:
        raise HTTPException(status_code=404, detail="Booking not found")
    return Booking(**_scrub(res))


app.include_router(api)

# CORS: comma-separated list in env CORS_ORIGINS, or "*" to allow all.
_cors_raw = os.environ.get("CORS_ORIGINS", "*").strip()
if _cors_raw == "*":
    _cors_kwargs = {"allow_origin_regex": ".*"}
else:
    _cors_kwargs = {
        "allow_origins": [o.strip() for o in _cors_raw.split(",") if o.strip()]
    }

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    **_cors_kwargs,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def _startup():
    try:
        # Verify MongoDB connection
        await client.admin.command("ping")
        logger.info("✅ MongoDB connected successfully")

        # Seed initial data
        await _ensure_services_seeded()

    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")

    logger.info("🚀 Aevum Health API started")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()