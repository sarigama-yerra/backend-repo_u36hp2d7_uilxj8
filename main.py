import os
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document
from schemas import User, Pet, Tag, ScanEvent, Coupon

app = FastAPI(title="Whoofsy API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Helpers

def _collection(name: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    return db[name]


def _now():
    return datetime.utcnow()


# Simple auth stub (Google-ready): client passes email+name for now
class AuthPayload(BaseModel):
    email: str
    name: Optional[str] = None
    phone: Optional[str] = None
    external_id: Optional[str] = None


@app.post("/auth/google")
def auth_google(payload: AuthPayload):
    col = _collection("user")
    existing = col.find_one({"email": payload.email})
    if existing:
        col.update_one(
            {"_id": existing["_id"]},
            {"$set": {"name": payload.name, "phone": payload.phone, "updated_at": _now()}},
        )
        user = col.find_one({"_id": existing["_id"]})
    else:
        user_model = User(
            provider="google",
            external_id=payload.external_id,
            email=payload.email,
            name=payload.name,
            phone=payload.phone,
            tier="basic",
            created_at=_now(),
            updated_at=_now(),
        )
        user_id = create_document("user", user_model)
        user = col.find_one({"_id": ObjectId(user_id)})
    user["id"] = str(user["_id"])  # normalize
    return user


# Tag activation
class ActivatePayload(BaseModel):
    code: str
    user_id: str
    model: Optional[str] = "smart_tag"


@app.post("/tags/activate")
def activate_tag(p: ActivatePayload):
    col = _collection("tag")
    tag = col.find_one({"code": p.code})
    if tag and tag.get("activated"):
        raise HTTPException(status_code=400, detail="Tag already activated")
    if not tag:
        # Pre-provisioned or create on the fly
        tag_model = Tag(code=p.code, activated=False, model=p.model, created_at=_now(), updated_at=_now())
        create_document("tag", tag_model)
        tag = col.find_one({"code": p.code})

    col.update_one(
        {"_id": tag["_id"]},
        {"$set": {"owner_id": p.user_id, "activated": True, "updated_at": _now()}},
    )
    tag = col.find_one({"_id": tag["_id"]})
    tag["id"] = str(tag["_id"])  # normalize
    return tag


# Pet profile CRUD (minimal for MVP)
class PetPayload(BaseModel):
    owner_id: str
    name: str
    breed: Optional[str] = None
    color: Optional[str] = None
    medical_notes: Optional[str] = None
    allergies: Optional[str] = None
    contact_visibility: Optional[str] = "phone"


@app.post("/pets")
def create_pet(p: PetPayload):
    pet_model = Pet(**p.model_dump(), created_at=_now(), updated_at=_now())
    pet_id = create_document("pet", pet_model)
    pet = _collection("pet").find_one({"_id": ObjectId(pet_id)})
    pet["id"] = str(pet["_id"])  # normalize
    return pet


@app.patch("/pets/{pet_id}/status")
def set_status(pet_id: str, status: str):
    if status not in ("ACTIVE", "LOST"):
        raise HTTPException(400, detail="Invalid status")
    col = _collection("pet")
    res = col.update_one(
        {"_id": ObjectId(pet_id)},
        {"$set": {"status": status, "updated_at": _now()}},
    )
    if not res.matched_count:
        raise HTTPException(404, detail="Pet not found")
    pet = col.find_one({"_id": ObjectId(pet_id)})
    pet["id"] = str(pet["_id"])  # normalize
    return pet


# Link tag to pet
class LinkPayload(BaseModel):
    code: str
    pet_id: str


@app.post("/tags/link")
def link_tag(p: LinkPayload):
    tcol = _collection("tag")
    pcol = _collection("pet")
    tag = tcol.find_one({"code": p.code})
    if not tag:
        raise HTTPException(404, detail="Tag not found")
    res = tcol.update_one(
        {"_id": tag["_id"]}, {"$set": {"pet_id": p.pet_id, "updated_at": _now()}}
    )
    if not res.matched_count:
        raise HTTPException(500, detail="Failed to link tag")
    pet = pcol.find_one({"_id": ObjectId(p.pet_id)})
    return {
        "success": True,
        "tag": {"code": tag["code"]},
        "pet": {"id": str(pet["_id"]), "name": pet.get("name")},
    }


# Finder scan → urgent profile payload
class FinderScanPayload(BaseModel):
    code: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    accuracy: Optional[float] = None


@app.post("/scan")
async def record_scan(p: FinderScanPayload, request: Request):
    tcol = _collection("tag")
    tag = tcol.find_one({"code": p.code})
    if not tag or not tag.get("activated"):
        raise HTTPException(404, detail="Tag not active")

    # fetch pet & owner
    pcol = _collection("pet")
    ucol = _collection("user")
    pet = (
        pcol.find_one({"_id": ObjectId(tag.get("pet_id"))})
        if tag.get("pet_id")
        else None
    )
    owner = (
        ucol.find_one({"_id": ObjectId(tag.get("owner_id"))})
        if tag.get("owner_id")
        else None
    )

    # store scan event
    scan_model = ScanEvent(
        code=p.code,
        pet_id=str(pet["_id"]) if pet else None,
        owner_id=str(owner["_id"]) if owner else None,
        timestamp=_now(),
        lat=p.lat,
        lng=p.lng,
        accuracy=p.accuracy,
        user_agent=request.headers.get("user-agent"),
        referrer=request.headers.get("referer"),
    )
    create_document("scanevent", scan_model)

    # Premium: instant alert + GPS snapshot (stub)
    tier = (owner or {}).get("tier", "basic")
    alert = None
    if tier == "premium":
        alert = {
            "type": "scan_alert",
            "delivered": True,
            "channel": "email",
            "gps": {"lat": p.lat, "lng": p.lng, "accuracy": p.accuracy},
        }

    # Response for finder urgent page
    payload: Dict[str, Any] = {
        "status": (pet or {}).get("status", "ACTIVE"),
        "pet": {
            "name": (pet or {}).get("name"),
            "photos": (pet or {}).get("photos", []),
            "medical": {
                "notes": (pet or {}).get("medical_notes"),
                "allergies": (pet or {}).get("allergies"),
            },
        },
        "contact": {
            "visibility": (pet or {}).get("contact_visibility", "phone"),
            "phone": (owner or {}).get("phone"),
        },
        "good_samaritan_offer": {
            "headline": "Thank you for helping!",
            "copy": "Get 50% off your first Whoofsy tag.",
        },
        "premium_alert": alert,
    }

    return payload


# Test My Tag – simulate a scan for owner dashboard
@app.post("/scan/test")
async def test_my_tag(code: str):
    # Reuse scan without GPS
    dummy_request = Request(scope={"type": "http", "headers": []})
    return await record_scan(FinderScanPayload(code=code), dummy_request)


# Good Samaritan coupon creation (one-time after reunion)
class ReunionPayload(BaseModel):
    code: str


@app.post("/reunion")
def mark_reunion(p: ReunionPayload):
    # create a one-time coupon if not exists
    col = _collection("coupon")
    existing = col.find_one({"code": p.code, "redeemed": False})
    if existing:
        existing["id"] = str(existing["_id"])  # normalize
        return existing
    coupon = Coupon(code=p.code, redeemed=False, created_at=_now())
    create_document("coupon", coupon)
    saved = col.find_one({"code": p.code, "redeemed": False})
    saved["id"] = str(saved["_id"])  # normalize
    return saved


@app.get("/test")
def test_database():
    resp = {
        "backend": "✅ Running",
        "database": "❌ Not Available" if db is None else "✅ Connected",
        "collections": [],
    }
    try:
        if db:
            resp["collections"] = db.list_collection_names()
    except Exception as e:
        resp["database"] = f"⚠️ {str(e)[:80]}"
    return resp


@app.get("/")
def root():
    return {"message": "Whoofsy backend is live"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
