"""
Database Schemas for Whoofsy

Each Pydantic model below corresponds to a MongoDB collection (lowercased class name).
These are used for validation in the API and to document the data shape.
"""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from datetime import datetime

# Users
class User(BaseModel):
    provider: Literal["google"] = Field("google")
    external_id: Optional[str] = Field(None, description="Provider user id")
    email: str
    name: Optional[str] = None
    phone: Optional[str] = None
    tier: Literal["basic", "premium"] = Field("basic")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

# Pet profiles
class Pet(BaseModel):
    owner_id: str
    name: str
    breed: Optional[str] = None
    color: Optional[str] = None
    photos: List[str] = Field(default_factory=list)
    medical_notes: Optional[str] = None
    allergies: Optional[str] = None
    status: Literal["ACTIVE", "LOST"] = Field("ACTIVE")
    contact_visibility: Literal["phone", "form", "both"] = Field("phone")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

# Physical/digital tag that maps to a pet
class Tag(BaseModel):
    code: str = Field(..., description="Unique code encoded in QR/NFC")
    owner_id: Optional[str] = None
    pet_id: Optional[str] = None
    activated: bool = Field(False)
    model: Literal["smart_tag", "smart_case"] = Field("smart_tag")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

# Scan event
class ScanEvent(BaseModel):
    code: str
    pet_id: Optional[str] = None
    owner_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    accuracy: Optional[float] = None
    user_agent: Optional[str] = None
    referrer: Optional[str] = None

# Subscription snapshot
class Subscription(BaseModel):
    user_id: str
    tier: Literal["basic", "premium"] = Field("basic")
    status: Literal["active", "canceled", "none"] = Field("none")
    started_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None

# One-time Good Samaritan coupon tied to a code
class Coupon(BaseModel):
    code: str
    offer: str = Field("50% off your first Whoofsy tag")
    redeemed: bool = False
    created_at: Optional[datetime] = None
    redeemed_at: Optional[datetime] = None
