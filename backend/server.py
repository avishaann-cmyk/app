"""
Cape Ember Coffee Co. - Production E-commerce Backend
Enterprise-grade e-commerce platform with PayFast payments
"""
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Query, Body, BackgroundTasks, Header
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import json
import logging
import secrets
import hashlib
import base64
import re
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr, validator
from typing import List, Optional, Dict, Any, Union
from abc import ABC, abstractmethod
import uuid
from datetime import datetime, timezone, timedelta
import urllib.parse
import jwt
import bcrypt
from enum import Enum
from decimal import Decimal
from bson import ObjectId
import resend_events

ROOT_DIR = Path(__file__).parent
APP_DIR = ROOT_DIR.parent
load_dotenv(ROOT_DIR / '.env')

# ============ CONFIGURATION ============

TRUE_BOOL_VALUES = {"true", "1", "yes", "on"}
FALSE_BOOL_VALUES = {"false", "0", "no", "off"}


class PayFastConfigurationError(Exception):
    pass

def _get_env_stripped(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _get_env_bool(name: str, default: bool = False) -> bool:
    raw_default = "true" if default else "false"
    return _get_env_stripped(name, raw_default).lower() == "true"


def _parse_strict_bool_env(name: str) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        raise PayFastConfigurationError(f"{name} is required")

    value = raw_value.strip().lower()
    if value in TRUE_BOOL_VALUES:
        return True
    if value in FALSE_BOOL_VALUES:
        return False

    raise PayFastConfigurationError(
        f"{name} must be one of: true,1,yes,on,false,0,no,off"
    )

# MongoDB
MONGO_URL = _get_env_stripped('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = _get_env_stripped('DB_NAME', 'cape_ember_coffee')

# JWT
JWT_SECRET = _get_env_stripped('JWT_SECRET', secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24
REFRESH_TOKEN_DAYS = 30

# PayFast
PAYFAST_DEBUG = _get_env_bool('PAYFAST_DEBUG', False)

# Email (placeholder for SendGrid/Resend)
EMAIL_API_KEY = _get_env_stripped('EMAIL_API_KEY', '')
EMAIL_FROM = _get_env_stripped('EMAIL_FROM', 'orders@capeembercoffee.co.za')
ADMIN_NOTIFICATION_EMAIL = _get_env_stripped('ADMIN_NOTIFICATION_EMAIL', 'hello@capeembercoffee.co.za')

# URLs
FRONTEND_URL = _get_env_stripped('FRONTEND_URL', 'https://capeembercoffee.co.za').rstrip('/')
BACKEND_URL = _get_env_stripped('BACKEND_URL', _get_env_stripped('REACT_APP_BACKEND_URL', 'https://capeembercoffee.co.za')).rstrip('/')

# Tax configuration defaults (store-level values can override these)
TAX_REGISTRATION_STATUS = os.environ.get('TAX_REGISTRATION_STATUS', 'registered').strip().lower()
VAT_NUMBER = os.environ.get('VAT_NUMBER', '').strip()
PRICES_INCLUDE_TAX = os.environ.get('PRICES_INCLUDE_TAX', 'true').lower() == 'true'

# VAT Rate (South Africa)
VAT_RATE = 0.15
DEFAULT_SHIPPING_FEE = 75.0
DEFAULT_FREE_SHIPPING_THRESHOLD = 399.0

# MongoDB Connection
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

# App Setup
app = FastAPI(
    title="Cape Ember Coffee API",
    description="Production E-commerce API",
    version="2.0.0"
)

api_router = APIRouter(prefix="/api")
admin_router = APIRouter(prefix="/api/admin")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============ ENUMS ============

class OrderStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    PENDING_PAYMENT = "pending_payment"
    PAYMENT_PROCESSING = "payment_processing"
    PAID = "paid"
    PAYMENT_FAILED = "payment_failed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    FULFILLED = "fulfilled"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"

class PaymentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"

class PaymentMethod(str, Enum):
    PAYFAST = "payfast"


class PaymentAttemptStatus(str, Enum):
    CREATED = "created"
    REDIRECTED = "redirected"
    PENDING = "pending"
    SUCCESSFUL = "successful"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INVALID_NOTIFICATION = "invalid_notification"

class ProductCategory(str, Enum):
    COFFEE_BEANS = "coffee_beans"
    GROUND_COFFEE = "ground_coffee"
    GIFT_BOXES = "gift_boxes"
    ACCESSORIES = "accessories"

class RoastLevel(str, Enum):
    LIGHT = "light"
    MEDIUM_LIGHT = "medium_light"
    MEDIUM = "medium"
    MEDIUM_DARK = "medium_dark"
    DARK = "dark"

class GrindType(str, Enum):
    WHOLE_BEAN = "whole_bean"
    COARSE = "coarse"
    MEDIUM = "medium"
    FINE = "fine"
    EXTRA_FINE = "extra_fine"

class ShippingMethod(str, Enum):
    STANDARD = "standard"
    EXPRESS = "express"
    COLLECTION = "collection"
    LOCAL_DELIVERY = "local_delivery"


# ============ PYDANTIC MODELS ============

# User Models
class AddressModel(BaseModel):
    id: Optional[str] = None
    label: Optional[str] = "Home"
    first_name: str
    last_name: str
    street: str
    apartment: Optional[str] = None
    city: str
    province: str
    postal_code: str
    country: str = "South Africa"
    phone: Optional[str] = None
    is_default: bool = False

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    accepts_marketing: bool = False

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    accepts_marketing: Optional[bool] = None

class PasswordReset(BaseModel):
    email: EmailStr

class PasswordChange(BaseModel):
    current_password: str
    new_password: str

class UserResponse(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    addresses: List[AddressModel] = []
    accepts_marketing: bool = False
    is_admin: bool = False
    admin_role: Optional[str] = None
    created_at: Optional[str] = None

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: UserResponse


# Product Models
class ProductImage(BaseModel):
    url: str
    alt: str
    is_primary: bool = False
    sort_order: int = 0

class ProductVariant(BaseModel):
    id: str
    name: str
    sku: str
    price: float
    compare_at_price: Optional[float] = None
    grind: Optional[GrindType] = None
    weight: str
    stock_quantity: int = 0
    barcode: Optional[str] = None

class TastingNote(BaseModel):
    note: str
    intensity: int  # 1-5

class BrewingMethod(BaseModel):
    method: str
    description: str
    ratio: str
    time: str
    temperature: str

class ProductCreate(BaseModel):
    name: str
    slug: str
    description: str
    short_description: Optional[str] = None
    category: ProductCategory
    roast_level: Optional[RoastLevel] = None
    origin: Optional[str] = None
    strength: Optional[int] = None  # 1-5
    flavor_notes: str
    tasting_notes: List[TastingNote] = []
    brewing_methods: List[BrewingMethod] = []
    images: List[ProductImage] = []
    variants: List[ProductVariant] = []
    tags: List[str] = []
    is_active: bool = True
    is_featured: bool = False
    is_bundle: bool = False
    bundle_items: List[str] = []
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None

class ProductResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    short_description: Optional[str] = None
    category: str
    roast_level: Optional[str] = None
    origin: Optional[str] = None
    strength: Optional[int] = None
    flavor_notes: str
    tasting_notes: List[TastingNote] = []
    brewing_methods: List[BrewingMethod] = []
    images: List[ProductImage] = []
    variants: List[ProductVariant] = []
    price: float
    compare_at_price: Optional[float] = None
    tags: List[str] = []
    is_active: bool = True
    is_featured: bool = False
    is_bundle: bool = False
    bundle_items: List[str] = []
    stock_status: str = "in_stock"
    total_stock: int = 0
    average_rating: float = 0.0
    review_count: int = 0
    created_at: Optional[str] = None


# Cart Models
class CartItemAdd(BaseModel):
    product_id: str
    variant_id: Optional[str] = None
    quantity: int = 1

class CartItemUpdate(BaseModel):
    quantity: int

class CartItemResponse(BaseModel):
    id: str
    product_id: str
    variant_id: Optional[str] = None
    product_name: str
    variant_name: Optional[str] = None
    price: float
    quantity: int
    image_url: str
    stock_available: int

class CartResponse(BaseModel):
    items: List[CartItemResponse]
    subtotal: float
    discount: float = 0.0
    shipping: float = 0.0
    vat: float = 0.0
    total: float = 0.0
    coupon_code: Optional[str] = None
    item_count: int = 0


# Coupon Models
class CouponCreate(BaseModel):
    code: str
    description: Optional[str] = None
    discount_type: str  # percentage, fixed_amount, free_shipping
    discount_value: float
    minimum_order: float = 0.0
    maximum_uses: Optional[int] = None
    uses_per_customer: int = 1
    valid_from: datetime
    valid_until: datetime
    applies_to_products: List[str] = []
    applies_to_categories: List[str] = []
    is_active: bool = True


# Order Models
class OrderItemCreate(BaseModel):
    product_id: str
    variant_id: Optional[str] = None
    quantity: int
    price: float

class ShippingInfo(BaseModel):
    method: ShippingMethod
    address: AddressModel
    notes: Optional[str] = None

class BillingInfo(BaseModel):
    same_as_shipping: bool = True
    address: Optional[AddressModel] = None

class CheckoutCreate(BaseModel):
    shipping: ShippingInfo
    billing: BillingInfo
    payment_method: PaymentMethod
    coupon_code: Optional[str] = None
    is_guest: bool = False
    guest_email: Optional[EmailStr] = None
    is_subscription: bool = False

# Simple order creation for legacy frontend
class SimpleOrderCreate(BaseModel):
    shipping_address: dict
    is_subscription: bool = False
    subscription_frequency: Optional[str] = None
    payment_method: Optional[str] = "payfast"

class SimplePaymentCreate(BaseModel):
    order_id: str

class OrderResponse(BaseModel):
    id: str
    order_number: str
    user_id: Optional[str] = None
    guest_email: Optional[str] = None
    items: List[dict]
    subtotal: float
    discount: float
    shipping_cost: float
    vat: float
    total: float
    status: str
    payment_status: str
    payment_method: str
    shipping: dict
    billing: dict
    coupon_code: Optional[str] = None
    tracking_number: Optional[str] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: str


# Review Models
class ReviewCreate(BaseModel):
    product_id: str
    rating: int  # 1-5
    title: str
    content: str

class ReviewResponse(BaseModel):
    id: str
    product_id: str
    user_id: str
    user_name: str
    rating: int
    title: str
    content: str
    is_verified_purchase: bool
    helpful_votes: int = 0
    created_at: str


class ContactSubmissionRequest(BaseModel):
    name: str
    email: EmailStr
    subject: str
    message: str
    website: Optional[str] = None


class SubscriptionRequestCreate(BaseModel):
    plan_name: str
    blend: Optional[str] = None
    grind: str
    frequency: str
    quantity: int = 1
    customer_name: Optional[str] = None
    customer_email: Optional[EmailStr] = None
    delivery_address: dict
    preferred_delivery_day: Optional[str] = None
    delivery_notes: Optional[str] = None


class SubscriptionStatusUpdate(BaseModel):
    status: str
    next_delivery_date: Optional[str] = None
    payment_status: Optional[str] = None
    admin_notes: Optional[str] = None


# Wishlist Models
class WishlistItemAdd(BaseModel):
    product_id: str


# Search & Filter Models
class ProductFilter(BaseModel):
    category: Optional[str] = None
    roast_level: Optional[str] = None
    grind: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    in_stock: Optional[bool] = None
    tags: List[str] = []


class AnalyticsEventIn(BaseModel):
    event_name: str
    anonymous_id: Optional[str] = None
    session_id: Optional[str] = None
    page_path: Optional[str] = None
    referrer: Optional[str] = None
    params: Dict[str, Any] = {}


# Admin Models
class AdminDashboardStats(BaseModel):
    total_orders: int
    total_revenue: float
    orders_today: int
    revenue_today: float
    pending_orders: int
    low_stock_products: int
    new_customers: int
    conversion_rate: float


# ============ UTILITY FUNCTIONS ============

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_access_token(user_id: str, email: str, is_admin: bool = False, admin_role: Optional[str] = None) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "is_admin": is_admin,
        "admin_role": admin_role,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def generate_order_number() -> str:
    """Generate unique order number: CE-YYYYMMDD-XXXX"""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = secrets.token_hex(2).upper()
    return f"CE-{date_part}-{random_part}"

def generate_sku(category: str, name: str) -> str:
    """Generate SKU from category and name"""
    cat_code = category[:2].upper()
    name_code = ''.join(c for c in name if c.isalnum())[:4].upper()
    random_part = secrets.token_hex(2).upper()
    return f"{cat_code}-{name_code}-{random_part}"

def is_sedgefield_destination(*parts: Optional[str]) -> bool:
    location_text = " ".join(part.strip() for part in parts if part and str(part).strip()).lower()
    return bool(re.search(r"\bsedgefield\b", location_text))


def normalize_location_token(value: Optional[str]) -> str:
    raw = str(value or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", raw)
    collapsed = re.sub(r"\s+", " ", cleaned)
    return collapsed.strip()


def is_free_local_delivery(address: Optional[Dict[str, Any]], alias_list: Optional[List[str]] = None) -> Dict[str, Any]:
    alias_set = {"sedgefield"}
    for alias in alias_list or []:
        token = normalize_location_token(alias)
        if token:
            alias_set.add(token)

    address = address or {}
    city = normalize_location_token(address.get("city"))
    locality = normalize_location_token(address.get("locality"))
    suburb = normalize_location_token(address.get("suburb"))
    province = normalize_location_token(address.get("province"))
    tokens = [token for token in [city, locality, suburb] if token]
    matched = next((token for token in tokens if token in alias_set), None)

    if matched:
        return {
            "eligible": True,
            "matched_rule": "sedgefield_local_delivery",
            "reason": f"matched {matched}",
            "final_delivery_charge": 0.0,
            "normalized_city": city,
            "normalized_province": province,
        }

    return {
        "eligible": False,
        "matched_rule": None,
        "reason": "city not eligible for local free delivery",
        "final_delivery_charge": None,
        "normalized_city": city,
        "normalized_province": province,
    }


def resolve_tax_config(store_settings: Optional[dict] = None) -> dict:
    settings = store_settings or {}
    registration_status = str(settings.get("tax_registration_status") or TAX_REGISTRATION_STATUS or "registered").strip().lower()
    if registration_status not in {"registered", "not_registered"}:
        registration_status = "registered"

    vat_rate = float(settings.get("vat_rate", VAT_RATE) or 0)
    prices_include_tax = bool(settings.get("vat_inclusive_prices", PRICES_INCLUDE_TAX))
    vat_number = str(settings.get("vat_number") or VAT_NUMBER or "").strip()

    return {
        "taxRegistrationStatus": registration_status,
        "taxRate": max(vat_rate, 0.0),
        "pricesIncludeTax": prices_include_tax,
        "vatNumber": vat_number or None,
    }


def calculate_vat_components(gross_amount: float, tax_config: dict) -> dict:
    gross = round(max(float(gross_amount or 0), 0.0), 2)
    if tax_config.get("taxRegistrationStatus") != "registered":
        return {"gross": gross, "net": gross, "vat": 0.0}

    tax_rate = max(float(tax_config.get("taxRate") or 0), 0.0)
    if tax_rate <= 0:
        return {"gross": gross, "net": gross, "vat": 0.0}

    if tax_config.get("pricesIncludeTax", True):
        vat = round(gross * tax_rate / (1 + tax_rate), 2)
        net = round(gross - vat, 2)
        return {"gross": gross, "net": net, "vat": vat}

    net = gross
    vat = round(net * tax_rate, 2)
    gross_with_tax = round(net + vat, 2)
    return {"gross": gross_with_tax, "net": net, "vat": vat}


def resolve_shipping_charge(
    *,
    subtotal_after_discount: float,
    method: ShippingMethod,
    province: Optional[str],
    city: Optional[str],
    postal_code: Optional[str],
    is_subscription: bool,
    order_items: List[dict],
    coupon: Optional[dict],
    free_shipping_threshold: float,
    default_shipping_fee: float,
    sedgefield_aliases: Optional[List[str]] = None,
) -> dict:
    base_rate = calculate_shipping(
        subtotal_after_discount,
        method,
        province or "Western Cape",
        is_subscription,
        city,
        free_shipping_threshold,
        default_shipping_fee,
    )

    applied_rule = None
    reason = "standard_zone_rate"
    waived_amount = 0.0
    final_rate = float(base_rate)

    if coupon and coupon.get("discount_type") == "free_shipping":
        applied_rule = "coupon_free_shipping"
        reason = "valid free-shipping coupon"
        waived_amount = final_rate
        final_rate = 0.0
    elif any(item.get("product_id") == "landscape-bundle" for item in order_items):
        applied_rule = "landscape_bundle"
        reason = "bundle qualifies for complimentary delivery"
        waived_amount = final_rate
        final_rate = 0.0
    else:
        local_result = is_free_local_delivery(
            {
                "city": city,
                "province": province,
                "postal_code": postal_code,
            },
            sedgefield_aliases,
        )
        if local_result["eligible"]:
            applied_rule = "sedgefield_local_delivery"
            reason = local_result["reason"]
            waived_amount = final_rate
            final_rate = 0.0
        elif subtotal_after_discount >= free_shipping_threshold:
            applied_rule = "national_threshold"
            reason = f"subtotal meets threshold {free_shipping_threshold:.2f}"
            waived_amount = final_rate
            final_rate = 0.0

    final_rate = round(max(final_rate, 0.0), 2)
    waived_amount = round(max(min(waived_amount, base_rate), 0.0), 2)

    return {
        "original_delivery_rate": round(float(base_rate), 2),
        "waived_amount": waived_amount,
        "applied_rule": applied_rule,
        "reason": reason,
        "final_delivery_rate": final_rate,
    }


async def get_store_rules() -> dict:
    settings = await db.settings.find_one({"_id": "store"}) or {}

    def _safe_float(value: Any, default: float) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    return {
        "shipping_fee": max(_safe_float(settings.get("shipping_fee"), DEFAULT_SHIPPING_FEE), 0.0),
        "free_shipping_threshold": max(_safe_float(settings.get("free_shipping_threshold"), DEFAULT_FREE_SHIPPING_THRESHOLD), 0.0),
        "vat_rate": max(_safe_float(settings.get("vat_rate"), VAT_RATE), 0.0),
    }


def calculate_shipping(
    subtotal: float,
    method: ShippingMethod,
    province: str,
    is_subscription: bool = False,
    city: Optional[str] = None,
    free_shipping_threshold: float = 399.0,
    default_shipping_fee: float = 75.0,
) -> float:
    """Calculate shipping cost using shipping zones, with complimentary delivery for Sedgefield."""
    if method == ShippingMethod.COLLECTION:
        return 0.0
    if is_subscription:
        return 0.0
    if is_sedgefield_destination(city, province):
        return 0.0
    if subtotal >= free_shipping_threshold:
        return 0.0
    zone_rates = SHIPPING_ZONES.get(province, SHIPPING_ZONES.get("Western Cape", {}))
    if method == ShippingMethod.LOCAL_DELIVERY and "local_delivery" in zone_rates:
        return float(zone_rates["local_delivery"])
    if method == ShippingMethod.EXPRESS and "express" in zone_rates:
        return float(zone_rates["express"])
    return float(zone_rates.get("standard", default_shipping_fee))

def calculate_vat(amount: float, vat_rate: float = VAT_RATE) -> float:
    """Calculate the VAT portion included in a VAT-inclusive amount."""
    safe_amount = max(float(amount or 0), 0.0)
    safe_rate = max(float(vat_rate or 0), 0.0)
    if safe_rate == 0:
        return 0.0
    return round(safe_amount * safe_rate / (1 + safe_rate), 2)


# ============ AUTH DEPENDENCIES ============

async def get_current_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        
        user = await db.users.find_one(
            {"_id": payload["sub"]},
            {"password_hash": 0}
        )
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_current_user_optional(request: Request) -> Optional[dict]:
    """Get current user if authenticated, else return None"""
    try:
        return await get_current_user(request)
    except HTTPException:
        return None

async def get_admin_user(request: Request) -> dict:
    user = await get_current_user(request)
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_admin_roles(allowed_roles: List[str]):
    async def _role_dependency(request: Request) -> dict:
        user = await get_admin_user(request)
        user_role = user.get("admin_role", "staff")
        if user_role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Admin role required: {', '.join(allowed_roles)}")
        return user
    return _role_dependency


# ============ PAYFAST FUNCTIONS ============

def get_payfast_config() -> Dict[str, Any]:
    enabled = _parse_strict_bool_env("PAYFAST_ENABLED")
    sandbox = _parse_strict_bool_env("PAYFAST_SANDBOX")

    if not enabled:
        return {
            "enabled": False,
            "environment": "disabled",
            "process_host": "",
            "action_url": "",
            "merchant_id": "",
            "merchant_key": "",
            "passphrase": "",
            "merchant_id_configured": False,
            "merchant_key_configured": False,
            "passphrase_configured": False,
        }

    if sandbox:
        merchant_id = _get_env_stripped("PAYFAST_SANDBOX_MERCHANT_ID", "")
        merchant_key = _get_env_stripped("PAYFAST_SANDBOX_MERCHANT_KEY", "")
        passphrase = _get_env_stripped("PAYFAST_SANDBOX_PASSPHRASE", "")
        environment = "sandbox"
        process_host = "sandbox.payfast.co.za"
        missing = []
        if not merchant_id:
            missing.append("PAYFAST_SANDBOX_MERCHANT_ID")
        if not merchant_key:
            missing.append("PAYFAST_SANDBOX_MERCHANT_KEY")
    else:
        merchant_id = _get_env_stripped("PAYFAST_MERCHANT_ID", "")
        merchant_key = _get_env_stripped("PAYFAST_MERCHANT_KEY", "")
        passphrase = _get_env_stripped("PAYFAST_PASSPHRASE", "")
        environment = "production"
        process_host = "www.payfast.co.za"
        missing = []
        if not merchant_id:
            missing.append("PAYFAST_MERCHANT_ID")
        if not merchant_key:
            missing.append("PAYFAST_MERCHANT_KEY")

    if missing:
        raise PayFastConfigurationError(
            f"PayFast {environment} credentials are incomplete: {', '.join(missing)}"
        )

    return {
        "enabled": True,
        "environment": environment,
        "process_host": process_host,
        "action_url": f"https://{process_host}/eng/process",
        "merchant_id": merchant_id,
        "merchant_key": merchant_key,
        "passphrase": passphrase,
        "merchant_id_configured": bool(merchant_id),
        "merchant_key_configured": bool(merchant_key),
        "passphrase_configured": bool(passphrase),
    }


def get_payfast_host() -> str:
    return get_payfast_config()["process_host"]


class PaymentProvider(ABC):
    @abstractmethod
    async def create_checkout(self, order: dict, customer: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def verify_notification(self, request: Request, payload: Dict[str, Any]) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def get_payment_status(self, reference: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def refund_payment(self, payment_id: str, amount: float) -> dict:
        raise NotImplementedError


class PayFastPaymentProvider(PaymentProvider):
    async def create_checkout(self, order: dict, customer: dict) -> dict:
        payfast_config = get_payfast_config()
        if not payfast_config["enabled"]:
            raise HTTPException(status_code=503, detail="PayFast is disabled")

        credentials = get_payfast_credentials()
        order_id = order["_id"]
        order_number = order.get("order_number", order_id)
        status_token = order.get("status_token") or ""
        status_query = f"&status_token={urllib.parse.quote_plus(status_token)}" if status_token else ""
        action_url = payfast_config["action_url"]

        if not FRONTEND_URL:
            raise HTTPException(status_code=500, detail="FRONTEND_URL is not configured")
        if not BACKEND_URL:
            raise HTTPException(status_code=500, detail="BACKEND_URL is not configured")
        for url_name, url_value in (("FRONTEND_URL", FRONTEND_URL), ("BACKEND_URL", BACKEND_URL)):
            if not url_value.startswith("https://") and "localhost" not in url_value and "127.0.0.1" not in url_value:
                raise HTTPException(status_code=500, detail=f"{url_name} must use https in production")

        payfast_data = {
            "merchant_id": credentials["merchant_id"],
            "merchant_key": credentials["merchant_key"],
            "return_url": f"{FRONTEND_URL}/payment/success?order_id={order_id}{status_query}",
            "cancel_url": f"{FRONTEND_URL}/payment/cancel?order_id={order_id}{status_query}",
            "notify_url": f"{BACKEND_URL}/api/webhooks/payfast",
            "m_payment_id": order_id,
            "amount": f"{float(order['total']):.2f}",
            "item_name": f"Cape Ember Order {order_number}",
            "item_description": f"Cape Ember order {order_number}",
            "email_address": customer.get("email") or order.get("guest_email") or "",
            "name_first": customer.get("first_name") or "Customer",
            "name_last": customer.get("last_name") or "",
        }

        signature = generate_payfast_signature(payfast_data, credentials["passphrase"])
        payfast_data["signature"] = signature
        logger.info(
            "PayFast checkout prepared: order_id=%s amount=%s action_url=%s fields=%s",
            order_id,
            payfast_data.get("amount"),
            action_url,
            sorted(payfast_data.keys()),
        )
        return {
            "provider": "payfast",
            "host": payfast_config["process_host"],
            "action_url": action_url,
            "fields": payfast_data,
        }

    async def verify_notification(self, request: Request, payload: Dict[str, Any]) -> dict:
        verified = await verify_payfast_itn(request)
        return {"verified": verified, "provider": "payfast"}

    async def get_payment_status(self, reference: str) -> dict:
        return {"provider": "payfast", "reference": reference, "status": "unknown"}

    async def refund_payment(self, payment_id: str, amount: float) -> dict:
        raise HTTPException(status_code=501, detail="PayFast refund API is not implemented in this service")


def get_payment_provider(provider_name: str) -> PaymentProvider:
    provider = (provider_name or "").lower()
    if provider == "payfast":
        return PayFastPaymentProvider()
    raise HTTPException(status_code=400, detail=f"Unsupported payment provider: {provider_name}")

def get_payfast_credentials() -> Dict[str, str]:
    try:
        config = get_payfast_config()
    except PayFastConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not config["enabled"]:
        raise HTTPException(status_code=503, detail="PayFast is disabled")

    return {
        "merchant_id": config["merchant_id"],
        "merchant_key": config["merchant_key"],
        "passphrase": config["passphrase"],
    }


def generate_payfast_signature(data: Dict[str, str], passphrase: Optional[str] = None) -> str:
    # Build canonical payload in insertion order to match PayFast docs/examples.
    payload_parts = []
    for key, value in data.items():
        if key == "signature" or value is None:
            continue

        normalized_value = str(value).strip().replace("\r", "").replace("\n", "")
        if normalized_value == "":
            continue

        encoded_value = urllib.parse.quote_plus(normalized_value.replace("+", " "))
        payload_parts.append(f"{key}={encoded_value}")

    param_string = "&".join(payload_parts)

    if passphrase is None:
        try:
            effective_passphrase = get_payfast_config().get("passphrase", "")
        except PayFastConfigurationError:
            effective_passphrase = ""
    else:
        effective_passphrase = passphrase

    effective_passphrase = str(effective_passphrase or "").strip().replace("\r", "").replace("\n", "")
    if effective_passphrase:
        passphrase_encoded = urllib.parse.quote_plus(effective_passphrase.replace("+", " "))
        if param_string:
            param_string += f"&passphrase={passphrase_encoded}"
        else:
            param_string = f"passphrase={passphrase_encoded}"

    signature = hashlib.md5(param_string.encode("utf-8")).hexdigest()
    
    if PAYFAST_DEBUG:
        # Never log canonical signature payloads to avoid leaking sensitive values.
        logger.info("PayFast signature debug: field_count=%s has_passphrase=%s signature=%s", len(payload_parts), bool(effective_passphrase), signature)
    return signature


async def verify_payfast_itn(request: Request) -> bool:
    """Verify PayFast ITN request using the same canonical payload validator as webhook route."""
    form_data = await request.form()
    data = {k: str(v).strip() for k, v in dict(form_data).items()}

    if not data:
        logger.warning("PayFast ITN: empty payload")
        return False

    validation = validate_payfast_itn_payload(data)
    if not validation["valid"]:
        logger.warning("PayFast ITN validation failed: reason=%s", validation.get("reason_code"))
        return False

    return True


def validate_payfast_itn_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    required_fields = [
        "m_payment_id",
        "payment_status",
        "amount_gross",
        "merchant_id",
        "merchant_key",
        "signature",
    ]
    missing_fields = [field for field in required_fields if not str(data.get(field, "")).strip()]
    if missing_fields:
        return {
            "valid": False,
            "reason_code": "missing_required_fields",
            "status_code": 400,
            "missing_fields": missing_fields,
            "merchant_valid": False,
            "signature_valid": False,
        }

    try:
        credentials = get_payfast_credentials()
    except HTTPException as exc:
        return {
            "valid": False,
            "reason_code": "config_error",
            "status_code": 500,
            "missing_fields": [],
            "merchant_valid": False,
            "signature_valid": False,
            "detail": str(exc.detail),
        }

    received_merchant_id = str(data.get("merchant_id", "")).strip()
    received_merchant_key = str(data.get("merchant_key", "")).strip()
    merchant_valid = (
        received_merchant_id == credentials["merchant_id"]
        and received_merchant_key == credentials["merchant_key"]
    )
    if not merchant_valid:
        return {
            "valid": False,
            "reason_code": "merchant_mismatch",
            "status_code": 400,
            "missing_fields": [],
            "merchant_valid": False,
            "signature_valid": False,
        }

    signature_input = {k: v for k, v in data.items() if k != "signature"}
    received_signature = str(data.get("signature", "")).strip().lower()
    expected_signature = generate_payfast_signature(signature_input, credentials["passphrase"]).strip().lower()
    signature_valid = bool(received_signature) and received_signature == expected_signature
    if not signature_valid:
        return {
            "valid": False,
            "reason_code": "invalid_signature",
            "status_code": 400,
            "missing_fields": [],
            "merchant_valid": True,
            "signature_valid": False,
        }

    return {
        "valid": True,
        "reason_code": "ok",
        "status_code": 200,
        "missing_fields": [],
        "merchant_valid": True,
        "signature_valid": True,
    }


# ============ EMAIL FUNCTIONS ============

async def send_order_confirmation(order: dict, email: str):
    """Send order confirmation email with premium Cape Ember branding"""
    try:
        import resend
        import asyncio
        
        resend_key = os.environ.get("RESEND_API_KEY")
        sender_email = os.environ.get("SENDER_EMAIL", "Cape Ember Coffee Co. <hello@capeembercoffee.co.za>")
        
        if not resend_key:
            logger.warning("RESEND_API_KEY not configured - skipping email")
            return
        
        resend.api_key = resend_key
        
        # Build items HTML
        items_html = ""
        for item in order.get("items", []):
            items_html += f"""
            <tr>
                <td style="padding: 16px 0; border-bottom: 1px solid #E6DCD1;">
                    <div style="font-weight: 600; color: #2C1A12;">{item.get('product_name', 'Product')}</div>
                    <div style="font-size: 14px; color: #6B5048;">{item.get('variant_name', '')}</div>
                </td>
                <td style="padding: 16px 0; border-bottom: 1px solid #E6DCD1; text-align: center; color: #6B5048;">
                    {item.get('quantity', 1)}
                </td>
                <td style="padding: 16px 0; border-bottom: 1px solid #E6DCD1; text-align: right; color: #2C1A12; font-weight: 500;">
                    R {item.get('price', 0) * item.get('quantity', 1):.2f}
                </td>
            </tr>
            """
        
        # Shipping address
        shipping = order.get("shipping", {})
        address = shipping.get("address", {}) if isinstance(shipping, dict) else {}
        address_html = f"""
            {address.get('first_name', '')} {address.get('last_name', '')}<br>
            {address.get('address_line1', '')}<br>
            {address.get('address_line2', '') + '<br>' if address.get('address_line2') else ''}
            {address.get('city', '')}, {address.get('province', '')} {address.get('postal_code', '')}<br>
            South Africa
        """
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; background-color: #F8F5F0; font-family: 'Segoe UI', Arial, sans-serif;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #F8F5F0; padding: 40px 20px;">
                <tr>
                    <td align="center">
                        <table width="600" cellpadding="0" cellspacing="0" style="background-color: #FFFFFF; border: 1px solid #E6DCD1;">
                            <!-- Header -->
                            <tr>
                                <td style="background-color: #2C1A12; padding: 30px; text-align: center;">
                                    <h1 style="margin: 0; color: #D05C23; font-size: 28px; font-weight: 400; letter-spacing: 2px;">CAPE EMBER</h1>
                                    <p style="margin: 5px 0 0; color: #FFFFFF; font-size: 11px; letter-spacing: 3px;">COFFEE CO.</p>
                                </td>
                            </tr>
                            
                            <!-- Thank You Message -->
                            <tr>
                                <td style="padding: 40px 40px 20px; text-align: center;">
                                    <h2 style="margin: 0; color: #2C1A12; font-size: 24px; font-weight: 400;">Thank You for Your Order</h2>
                                    <p style="margin: 15px 0 0; color: #6B5048; font-size: 16px; line-height: 1.6;">
                                        Your order has been confirmed and we're preparing it with care.
                                    </p>
                                </td>
                            </tr>
                            
                            <!-- Order Details -->
                            <tr>
                                <td style="padding: 20px 40px;">
                                    <table width="100%" style="background-color: #F8F5F0; padding: 20px;">
                                        <tr>
                                            <td>
                                                <p style="margin: 0; font-size: 12px; color: #6B5048; text-transform: uppercase; letter-spacing: 1px;">Order Number</p>
                                                <p style="margin: 5px 0 0; font-size: 18px; color: #D05C23; font-weight: 600;">#{order.get('order_number', 'N/A')}</p>
                                            </td>
                                            <td style="text-align: right;">
                                                <p style="margin: 0; font-size: 12px; color: #6B5048; text-transform: uppercase; letter-spacing: 1px;">Order Date</p>
                                                <p style="margin: 5px 0 0; font-size: 16px; color: #2C1A12;">{order.get('created_at', '')[:10]}</p>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                            
                            <!-- Items -->
                            <tr>
                                <td style="padding: 20px 40px;">
                                    <h3 style="margin: 0 0 15px; color: #2C1A12; font-size: 16px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Order Items</h3>
                                    <table width="100%" cellpadding="0" cellspacing="0">
                                        <tr style="border-bottom: 2px solid #E6DCD1;">
                                            <th style="padding: 10px 0; text-align: left; font-size: 12px; color: #6B5048; text-transform: uppercase; letter-spacing: 1px;">Item</th>
                                            <th style="padding: 10px 0; text-align: center; font-size: 12px; color: #6B5048; text-transform: uppercase; letter-spacing: 1px;">Qty</th>
                                            <th style="padding: 10px 0; text-align: right; font-size: 12px; color: #6B5048; text-transform: uppercase; letter-spacing: 1px;">Price</th>
                                        </tr>
                                        {items_html}
                                    </table>
                                </td>
                            </tr>
                            
                            <!-- Totals -->
                            <tr>
                                <td style="padding: 20px 40px;">
                                    <table width="100%" cellpadding="0" cellspacing="0">
                                        <tr>
                                            <td style="padding: 8px 0; color: #6B5048;">Subtotal</td>
                                            <td style="padding: 8px 0; text-align: right; color: #2C1A12;">R {order.get('subtotal', 0):.2f}</td>
                                        </tr>
                                        {"<tr><td style='padding: 8px 0; color: #2F855A;'>Discount</td><td style='padding: 8px 0; text-align: right; color: #2F855A;'>- R " + f"{order.get('discount', 0):.2f}</td></tr>" if order.get('discount', 0) > 0 else ""}
                                        <tr>
                                            <td style="padding: 8px 0; color: #6B5048;">Shipping</td>
                                            <td style="padding: 8px 0; text-align: right; color: #2C1A12;">{"Free" if order.get('shipping_cost', 0) == 0 else f"R {order.get('shipping_cost', 0):.2f}"}</td>
                                        </tr>
                                        <tr>
                                            <td style="padding: 8px 0; color: #6B5048;">VAT (included)</td>
                                            <td style="padding: 8px 0; text-align: right; color: #6B5048;">R {order.get('vat', 0):.2f}</td>
                                        </tr>
                                        <tr style="border-top: 2px solid #E6DCD1;">
                                            <td style="padding: 15px 0 0; font-size: 18px; font-weight: 600; color: #2C1A12;">Total</td>
                                            <td style="padding: 15px 0 0; text-align: right; font-size: 18px; font-weight: 600; color: #D05C23;">R {order.get('total', 0):.2f}</td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                            
                            <!-- Shipping Address -->
                            <tr>
                                <td style="padding: 20px 40px;">
                                    <h3 style="margin: 0 0 15px; color: #2C1A12; font-size: 16px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Shipping Address</h3>
                                    <p style="margin: 0; color: #6B5048; line-height: 1.8;">
                                        {address_html}
                                    </p>
                                </td>
                            </tr>
                            
                            <!-- Footer -->
                            <tr>
                                <td style="background-color: #F8F5F0; padding: 30px 40px; text-align: center;">
                                    <p style="margin: 0; color: #6B5048; font-size: 14px; line-height: 1.6;">
                                        Questions about your order?<br>
                                        <a href="mailto:hello@capeembercoffee.co.za" style="color: #D05C23; text-decoration: none;">hello@capeembercoffee.co.za</a>
                                    </p>
                                    <p style="margin: 20px 0 0; color: #A9998C; font-size: 12px;">
                                        © 2024 Cape Ember Coffee Co. | Premium South African Coffee
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        
        params = {
            "from": sender_email,
            "to": [email],
            "subject": f"Order Confirmed - #{order.get('order_number', 'N/A')} | Cape Ember Coffee Co.",
            "html": html_content
        }
        
        await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Order confirmation email sent to {email} for order {order['order_number']}")
        
    except Exception as e:
        logger.error(f"Failed to send order confirmation email: {str(e)}")

async def send_shipping_notification(order: dict, tracking_number: str):
    """Send shipping notification email with tracking info"""
    try:
        import resend
        import asyncio
        
        resend_key = os.environ.get("RESEND_API_KEY")
        sender_email = os.environ.get("SENDER_EMAIL", "Cape Ember Coffee Co. <hello@capeembercoffee.co.za>")
        
        if not resend_key:
            logger.warning("RESEND_API_KEY not configured - skipping email")
            return
        
        resend.api_key = resend_key
        
        # Get customer email
        email = order.get("guest_email", "")
        if order.get("user_id"):
            user = await db.users.find_one({"_id": order["user_id"]})
            if user:
                email = user.get("email", "")
        
        if not email:
            logger.warning(f"No email found for order {order.get('order_number')}")
            return
        
        # Shipping address
        shipping = order.get("shipping", {})
        address = shipping.get("address", {}) if isinstance(shipping, dict) else {}
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; background-color: #F8F5F0; font-family: 'Segoe UI', Arial, sans-serif;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #F8F5F0; padding: 40px 20px;">
                <tr>
                    <td align="center">
                        <table width="600" cellpadding="0" cellspacing="0" style="background-color: #FFFFFF; border: 1px solid #E6DCD1;">
                            <!-- Header -->
                            <tr>
                                <td style="background-color: #2C1A12; padding: 30px; text-align: center;">
                                    <h1 style="margin: 0; color: #D05C23; font-size: 28px; font-weight: 400; letter-spacing: 2px;">CAPE EMBER</h1>
                                    <p style="margin: 5px 0 0; color: #FFFFFF; font-size: 11px; letter-spacing: 3px;">COFFEE CO.</p>
                                </td>
                            </tr>
                            
                            <!-- Shipping Icon & Message -->
                            <tr>
                                <td style="padding: 40px 40px 20px; text-align: center;">
                                    <div style="width: 80px; height: 80px; background-color: #D05C23; border-radius: 50%; margin: 0 auto 20px; line-height: 80px;">
                                        <span style="color: #FFFFFF; font-size: 36px;">📦</span>
                                    </div>
                                    <h2 style="margin: 0; color: #2C1A12; font-size: 24px; font-weight: 400;">Your Order is On Its Way!</h2>
                                    <p style="margin: 15px 0 0; color: #6B5048; font-size: 16px; line-height: 1.6;">
                                        Great news! Your Cape Ember coffee has been shipped and is making its way to you.
                                    </p>
                                </td>
                            </tr>
                            
                            <!-- Tracking Info -->
                            <tr>
                                <td style="padding: 20px 40px;">
                                    <table width="100%" style="background-color: #F8F5F0; padding: 25px; text-align: center;">
                                        <tr>
                                            <td>
                                                <p style="margin: 0; font-size: 12px; color: #6B5048; text-transform: uppercase; letter-spacing: 1px;">Order Number</p>
                                                <p style="margin: 5px 0 15px; font-size: 18px; color: #2C1A12; font-weight: 600;">#{order.get('order_number', 'N/A')}</p>
                                                
                                                <p style="margin: 0; font-size: 12px; color: #6B5048; text-transform: uppercase; letter-spacing: 1px;">Tracking Number</p>
                                                <p style="margin: 5px 0 0; font-size: 20px; color: #D05C23; font-weight: 600; font-family: monospace;">{tracking_number}</p>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                            
                            <!-- Delivery Address -->
                            <tr>
                                <td style="padding: 20px 40px;">
                                    <h3 style="margin: 0 0 15px; color: #2C1A12; font-size: 16px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Delivering To</h3>
                                    <p style="margin: 0; color: #6B5048; line-height: 1.8;">
                                        {address.get('first_name', '')} {address.get('last_name', '')}<br>
                                        {address.get('address_line1', '')}<br>
                                        {address.get('city', '')}, {address.get('province', '')} {address.get('postal_code', '')}
                                    </p>
                                </td>
                            </tr>
                            
                            <!-- What's Next -->
                            <tr>
                                <td style="padding: 20px 40px;">
                                    <h3 style="margin: 0 0 15px; color: #2C1A12; font-size: 16px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">What's Next?</h3>
                                    <p style="margin: 0; color: #6B5048; line-height: 1.8;">
                                        Your package is on its way via our courier partner. You can track your delivery using the tracking number above. 
                                        Most orders arrive within 2-5 business days.
                                    </p>
                                </td>
                            </tr>
                            
                            <!-- Footer -->
                            <tr>
                                <td style="background-color: #F8F5F0; padding: 30px 40px; text-align: center;">
                                    <p style="margin: 0; color: #6B5048; font-size: 14px; line-height: 1.6;">
                                        Questions about your delivery?<br>
                                        <a href="mailto:hello@capeembercoffee.co.za" style="color: #D05C23; text-decoration: none;">hello@capeembercoffee.co.za</a>
                                    </p>
                                    <p style="margin: 20px 0 0; color: #A9998C; font-size: 12px;">
                                        © 2024 Cape Ember Coffee Co. | Premium South African Coffee
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        
        params = {
            "from": sender_email,
            "to": [email],
            "subject": f"Your Order Has Shipped! 📦 - #{order.get('order_number', 'N/A')} | Cape Ember Coffee Co.",
            "html": html_content
        }
        
        await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Shipping notification sent to {email} for order {order['order_number']}")
        
    except Exception as e:
        logger.error(f"Failed to send shipping notification: {str(e)}")

async def send_password_reset(email: str, reset_token: str):
    """Send password reset email"""
    try:
        import resend
        import asyncio
        
        resend_key = os.environ.get("RESEND_API_KEY")
        sender_email = os.environ.get("SENDER_EMAIL", "Cape Ember Coffee <noreply@capeembercoffee.co.za>")
        
        if not resend_key:
            logger.warning("RESEND_API_KEY not configured - skipping email")
            return
        
        resend.api_key = resend_key
        
        # Reset link (uses configured frontend URL)
        reset_link = f"{FRONTEND_URL}/reset-password?token={reset_token}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; background-color: #F8F5F0; font-family: 'Segoe UI', Arial, sans-serif;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #F8F5F0; padding: 40px 20px;">
                <tr>
                    <td align="center">
                        <table width="600" cellpadding="0" cellspacing="0" style="background-color: #FFFFFF; border: 1px solid #E6DCD1;">
                            <!-- Header -->
                            <tr>
                                <td style="background-color: #2C1A12; padding: 30px; text-align: center;">
                                    <h1 style="margin: 0; color: #D05C23; font-size: 28px; font-weight: 400; letter-spacing: 2px;">CAPE EMBER</h1>
                                    <p style="margin: 5px 0 0; color: #FFFFFF; font-size: 11px; letter-spacing: 3px;">COFFEE CO.</p>
                                </td>
                            </tr>
                            
                            <!-- Message -->
                            <tr>
                                <td style="padding: 40px;">
                                    <h2 style="margin: 0 0 20px; color: #2C1A12; font-size: 24px; font-weight: 400; text-align: center;">Reset Your Password</h2>
                                    <p style="margin: 0 0 30px; color: #6B5048; font-size: 16px; line-height: 1.6; text-align: center;">
                                        We received a request to reset your password. Click the button below to create a new password.
                                    </p>
                                    
                                    <table width="100%" cellpadding="0" cellspacing="0">
                                        <tr>
                                            <td align="center">
                                                <a href="{reset_link}" style="display: inline-block; background-color: #D05C23; color: #FFFFFF; padding: 15px 40px; text-decoration: none; font-size: 16px; font-weight: 600; letter-spacing: 1px;">
                                                    RESET PASSWORD
                                                </a>
                                            </td>
                                        </tr>
                                    </table>
                                    
                                    <p style="margin: 30px 0 0; color: #A9998C; font-size: 14px; line-height: 1.6; text-align: center;">
                                        This link will expire in 1 hour. If you didn't request a password reset, you can safely ignore this email.
                                    </p>
                                </td>
                            </tr>
                            
                            <!-- Footer -->
                            <tr>
                                <td style="background-color: #F8F5F0; padding: 30px 40px; text-align: center;">
                                    <p style="margin: 0; color: #A9998C; font-size: 12px;">
                                        © 2024 Cape Ember Coffee Co. | Premium South African Coffee
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        
        params = {
            "from": sender_email,
            "to": [email],
            "subject": "Reset Your Password | Cape Ember Coffee Co.",
            "html": html_content
        }
        
        await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Password reset email sent to {email}")
        
    except Exception as e:
        logger.error(f"Failed to send password reset email: {str(e)}")


async def send_welcome_email(email: str, first_name: str):
    """Send welcome email to new customers"""
    try:
        import resend
        import asyncio
        
        resend_key = os.environ.get("RESEND_API_KEY")
        sender_email = os.environ.get("SENDER_EMAIL", "Cape Ember Coffee <noreply@capeembercoffee.co.za>")
        
        if not resend_key:
            logger.warning("RESEND_API_KEY not configured - skipping email")
            return
        
        resend.api_key = resend_key
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; background-color: #F8F5F0; font-family: 'Segoe UI', Arial, sans-serif;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #F8F5F0; padding: 40px 20px;">
                <tr>
                    <td align="center">
                        <table width="600" cellpadding="0" cellspacing="0" style="background-color: #FFFFFF; border: 1px solid #E6DCD1;">
                            <!-- Header -->
                            <tr>
                                <td style="background-color: #2C1A12; padding: 30px; text-align: center;">
                                    <h1 style="margin: 0; color: #D05C23; font-size: 28px; font-weight: 400; letter-spacing: 2px;">CAPE EMBER</h1>
                                    <p style="margin: 5px 0 0; color: #FFFFFF; font-size: 11px; letter-spacing: 3px;">COFFEE CO.</p>
                                </td>
                            </tr>
                            
                            <!-- Welcome Message -->
                            <tr>
                                <td style="padding: 40px; text-align: center;">
                                    <h2 style="margin: 0 0 20px; color: #2C1A12; font-size: 28px; font-weight: 400;">
                                        Welcome to Cape Ember, {first_name}!
                                    </h2>
                                    <p style="margin: 0 0 30px; color: #6B5048; font-size: 16px; line-height: 1.8;">
                                        Thank you for joining us. You're now part of a community that appreciates 
                                        premium coffee inspired by South Africa's most beautiful landscapes.
                                    </p>
                                </td>
                            </tr>
                            
                            <!-- Features -->
                            <tr>
                                <td style="padding: 0 40px 30px;">
                                    <table width="100%" cellpadding="0" cellspacing="0">
                                        <tr>
                                            <td width="33%" style="text-align: center; padding: 20px;">
                                                <div style="font-size: 36px; margin-bottom: 10px;">☕</div>
                                                <p style="margin: 0; color: #2C1A12; font-weight: 600; font-size: 14px;">Small-Batch<br>Quality</p>
                                            </td>
                                            <td width="33%" style="text-align: center; padding: 20px;">
                                                <div style="font-size: 36px; margin-bottom: 10px;">🇿🇦</div>
                                                <p style="margin: 0; color: #2C1A12; font-weight: 600; font-size: 14px;">Proudly<br>South African</p>
                                            </td>
                                            <td width="33%" style="text-align: center; padding: 20px;">
                                                <div style="font-size: 36px; margin-bottom: 10px;">🚚</div>
                                                <p style="margin: 0; color: #2C1A12; font-weight: 600; font-size: 14px;">Complimentary Delivery<br>Over R399</p>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                            
                            <!-- CTA -->
                            <tr>
                                <td style="padding: 0 40px 40px; text-align: center;">
                                    <p style="margin: 0 0 20px; color: #6B5048; font-size: 16px;">
                                        Ready to explore? Use code <strong style="color: #D05C23;">WELCOME10</strong> for 10% off your first order.
                                    </p>
                                    <a href="{FRONTEND_URL}/shop" style="display: inline-block; background-color: #D05C23; color: #FFFFFF; padding: 15px 40px; text-decoration: none; font-size: 16px; font-weight: 600; letter-spacing: 1px;">
                                        EXPLORE THE COLLECTION
                                    </a>
                                </td>
                            </tr>
                            
                            <!-- Footer -->
                            <tr>
                                <td style="background-color: #F8F5F0; padding: 30px 40px; text-align: center;">
                                    <p style="margin: 0 0 15px; color: #6B5048; font-size: 14px;">
                                        Follow us for updates, brewing tips, and behind-the-scenes content.
                                    </p>
                                    <p style="margin: 0; color: #A9998C; font-size: 12px;">
                                        © 2024 Cape Ember Coffee Co. | Premium South African Coffee
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        
        params = {
            "from": sender_email,
            "to": [email],
            "subject": f"Welcome to Cape Ember Coffee Co., {first_name}! ☕",
            "html": html_content
        }
        
        await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Welcome email sent to {email}")
        
    except Exception as e:
        logger.error(f"Failed to send welcome email: {str(e)}")


def resend_is_configured() -> bool:
        return bool(os.environ.get("RESEND_API_KEY"))


async def send_resend_email(to_email: str, subject: str, html: str):
        """Send an email via Resend with safe fallback logging when not configured."""
        try:
                import resend
                import asyncio

                resend_key = os.environ.get("RESEND_API_KEY")
                sender_email = os.environ.get("SENDER_EMAIL", "Cape Ember Coffee Co. <hello@capeembercoffee.co.za>")

                if not resend_key:
                        logger.warning(f"RESEND_API_KEY not configured - email not sent: subject={subject}, to={to_email}")
                        return False

                resend.api_key = resend_key
                params = {
                        "from": sender_email,
                        "to": [to_email],
                        "subject": subject,
                        "html": html
                }
                await asyncio.to_thread(resend.Emails.send, params)
                return True
        except Exception as e:
                logger.error(f"Failed to send email via Resend: {str(e)}")
                return False


async def send_contact_emails(name: str, email: str, subject: str, message: str):
        owner_html = f"""
        <div style=\"font-family: Arial, sans-serif; color: #15110E;\">
            <h2>New Contact Submission</h2>
            <p><strong>Name:</strong> {name}</p>
            <p><strong>Email:</strong> {email}</p>
            <p><strong>Subject:</strong> {subject}</p>
            <p><strong>Message:</strong><br>{message}</p>
        </div>
        """
        await send_resend_email(ADMIN_NOTIFICATION_EMAIL, f"Contact Form: {subject}", owner_html)

        customer_html = f"""
        <div style=\"font-family: Arial, sans-serif; color: #15110E;\">
            <h2 style=\"color: #B56A35;\">Thanks for contacting Cape Ember</h2>
            <p>Hi {name},</p>
            <p>We've received your message and will get back to you shortly.</p>
            <p><strong>Your subject:</strong> {subject}</p>
            <p style=\"margin-top: 20px;\">If urgent, please WhatsApp us on +27 81 026 1618.</p>
        </div>
        """
        await send_resend_email(email, "We received your message | Cape Ember Coffee Co.", customer_html)


async def send_subscription_request_emails(subscription: dict):
        email = subscription.get("customer_email")
        plan = subscription.get("plan_name", "Ember Circle")
        blend = subscription.get("blend", "Not specified")

        owner_html = f"""
        <div style=\"font-family: Arial, sans-serif; color: #15110E;\">
            <h2>New Ember Circle Subscription Request</h2>
            <p><strong>Customer:</strong> {subscription.get('customer_name', '')}</p>
            <p><strong>Email:</strong> {email}</p>
            <p><strong>Plan:</strong> {plan}</p>
            <p><strong>Blend:</strong> {blend}</p>
            <p><strong>Grind:</strong> {subscription.get('grind', '')}</p>
            <p><strong>Frequency:</strong> {subscription.get('frequency', '')}</p>
            <p><strong>Quantity:</strong> {subscription.get('quantity', 1)}</p>
            <p><strong>Status:</strong> {subscription.get('status', '')}</p>
        </div>
        """
        await send_resend_email(ADMIN_NOTIFICATION_EMAIL, "New Subscription Request | Cape Ember", owner_html)

        if email:
                customer_html = f"""
                <div style=\"font-family: Arial, sans-serif; color: #15110E;\">
                    <h2 style=\"color: #B56A35;\">Your Ember Circle request is in</h2>
                    <p>Thanks for your subscription request for <strong>{plan}</strong>.</p>
                    <p>We'll review and confirm your delivery schedule shortly.</p>
                    <p>Selected blend: <strong>{blend}</strong></p>
                </div>
                """
                await send_resend_email(email, "Subscription request received | Cape Ember", customer_html)


async def send_admin_order_notification(order: dict):
        order_number = order.get("order_number", "N/A")
        total = order.get("total", 0)
        customer_email = order.get("guest_email") or "Registered user"
        html = f"""
        <div style=\"font-family: Arial, sans-serif; color: #15110E;\">
            <h2>New Paid Order Received</h2>
            <p><strong>Order:</strong> #{order_number}</p>
            <p><strong>Total:</strong> R {total:.2f}</p>
            <p><strong>Customer:</strong> {customer_email}</p>
            <p>Please log into admin to fulfil this order.</p>
        </div>
        """
        await send_resend_email(ADMIN_NOTIFICATION_EMAIL, f"New Paid Order #{order_number}", html)


# ============ PRODUCT DATA ============

# Extended product catalog
PRODUCTS = [
    {
        "id": "fynbos-roast",
        "name": "Fynbos Roast",
        "slug": "fynbos-roast",
        "description": "Inspired by the wild fynbos of the Cape Peninsula, this medium roast offers a grounded, comforting cup with natural sweetness. Smooth, nutty, and perfectly balanced — this is coffee for those who appreciate quiet mornings and the simple beauty of the Cape landscape.",
        "short_description": "Smooth medium roast with nutty sweetness",
        "category": ProductCategory.COFFEE_BEANS,
        "roast_level": RoastLevel.MEDIUM,
        "origin": "South African Roasted",
        "strength": 3,
        "flavor_notes": "Smooth · Nutty · Balanced",
        "tasting_notes": [
            {"note": "Hazelnut", "intensity": 4},
            {"note": "Caramel", "intensity": 3},
            {"note": "Cocoa", "intensity": 2}
        ],
        "brewing_methods": [
            {"method": "French Press", "description": "Full-bodied extraction", "ratio": "1:15", "time": "4 min", "temperature": "93°C"},
            {"method": "Pour Over", "description": "Clean, bright cup", "ratio": "1:16", "time": "3 min", "temperature": "92°C"},
            {"method": "AeroPress", "description": "Smooth concentrate", "ratio": "1:12", "time": "1.5 min", "temperature": "88°C"}
        ],
        "images": [
            {"url": "/assets/cape-ember/cape-ember-fynbos-lifestyle.jpeg", "alt": "Cape Ember Fynbos Roast surrounded by indigenous South African fynbos", "is_primary": True, "sort_order": 0}
        ],
        "variants": [
            {"id": "fynbos-250g-whole", "name": "250g Whole Bean", "sku": "CB-FYNB-250W", "price": 139.00, "grind": GrindType.WHOLE_BEAN, "weight": "250g", "stock_quantity": 50},
            {"id": "fynbos-250g-ground", "name": "250g Ground", "sku": "CB-FYNB-250G", "price": 139.00, "grind": GrindType.MEDIUM, "weight": "250g", "stock_quantity": 30}
        ],
        "tags": ["bestseller", "everyday", "brazilian"],
        "is_active": True,
        "is_featured": True,
        "is_bundle": False
    },
    {
        "id": "garden-route",
        "name": "Garden Route Blend",
        "slug": "garden-route-blend",
        "description": "A tribute to South Africa's iconic Garden Route coast. This balanced house blend offers a smooth cup with hints of cocoa and gentle citrus — crafted for everyday enjoyment, whether you're starting your morning or winding down your afternoon.",
        "short_description": "Smooth house blend with cocoa notes",
        "category": ProductCategory.COFFEE_BEANS,
        "roast_level": RoastLevel.MEDIUM,
        "origin": "South African Roasted",
        "strength": 3,
        "flavor_notes": "Smooth · Cocoa · Gentle Citrus",
        "tasting_notes": [
            {"note": "Milk Chocolate", "intensity": 4},
            {"note": "Orange Zest", "intensity": 2},
            {"note": "Brown Sugar", "intensity": 3}
        ],
        "brewing_methods": [
            {"method": "Pour Over", "description": "Bright and clean", "ratio": "1:16", "time": "3.5 min", "temperature": "92°C"},
            {"method": "Cold Brew", "description": "Sweet and smooth", "ratio": "1:8", "time": "18 hrs", "temperature": "Cold"},
            {"method": "Espresso", "description": "Rich crema", "ratio": "1:2", "time": "28 sec", "temperature": "93°C"}
        ],
        "images": [
            {"url": "/assets/cape-ember/cape-ember-garden-route-lifestyle.jpeg", "alt": "Cape Ember Garden Route Blend overlooking a South African coastal landscape", "is_primary": True, "sort_order": 0}
        ],
        "variants": [
            {"id": "garden-250g-whole", "name": "250g Whole Bean", "sku": "CB-GARD-250W", "price": 139.00, "grind": GrindType.WHOLE_BEAN, "weight": "250g", "stock_quantity": 45},
            {"id": "garden-250g-ground", "name": "250g Ground", "sku": "CB-GARD-250G", "price": 139.00, "grind": GrindType.MEDIUM, "weight": "250g", "stock_quantity": 35}
        ],
        "tags": ["house-blend", "everyday", "cold-brew-friendly"],
        "is_active": True,
        "is_featured": True,
        "is_bundle": False
    },
    {
        "id": "ember-reserve",
        "name": "Ember Reserve",
        "slug": "ember-reserve",
        "description": "Inspired by the rugged grandeur of the Drakensberg mountains. Ember Reserve delivers a bold, lingering finish with rich dark chocolate notes and full-bodied intensity. For those who appreciate depth and strength in their cup.",
        "short_description": "Bold dark roast with chocolate intensity",
        "category": ProductCategory.COFFEE_BEANS,
        "roast_level": RoastLevel.DARK,
        "origin": "South African Roasted",
        "strength": 5,
        "flavor_notes": "Rich · Dark Chocolate · Intense",
        "tasting_notes": [
            {"note": "Dark Chocolate", "intensity": 5},
            {"note": "Molasses", "intensity": 3},
            {"note": "Smoke", "intensity": 2}
        ],
        "brewing_methods": [
            {"method": "Espresso", "description": "Bold and intense", "ratio": "1:2", "time": "26 sec", "temperature": "94°C"},
            {"method": "French Press", "description": "Full body", "ratio": "1:15", "time": "4.5 min", "temperature": "95°C"},
            {"method": "Moka Pot", "description": "Stovetop intensity", "ratio": "1:10", "time": "4 min", "temperature": "Stovetop"}
        ],
        "images": [
            {"url": "/assets/cape-ember/cape-ember-ember-reserve-lifestyle.jpeg", "alt": "Cape Ember Ember Reserve dark roast inspired by South African mountain valleys", "is_primary": True, "sort_order": 0}
        ],
        "variants": [
            {"id": "ember-250g-whole", "name": "250g Whole Bean", "sku": "CB-EMBR-250W", "price": 169.00, "grind": GrindType.WHOLE_BEAN, "weight": "250g", "stock_quantity": 40},
            {"id": "ember-250g-ground", "name": "250g Ground", "sku": "CB-EMBR-250G", "price": 169.00, "grind": GrindType.FINE, "weight": "250g", "stock_quantity": 25}
        ],
        "tags": ["bold", "espresso", "colombian", "premium"],
        "is_active": True,
        "is_featured": True,
        "is_bundle": False
    },
    {
        "id": "karoo-horizon",
        "name": "Karoo Horizon",
        "slug": "karoo-horizon",
        "description": "From the vast, open plains of the Great Karoo. This expressive light roast offers delicate blueberry and wildflower notes with a relaxed honey finish — capturing the quiet, endless beauty of the Karoo horizon. A limited release for adventurous palates.",
        "short_description": "Delicate light roast with fruity florals",
        "category": ProductCategory.COFFEE_BEANS,
        "roast_level": RoastLevel.LIGHT,
        "origin": "South African Roasted",
        "strength": 2,
        "flavor_notes": "Floral · Blueberry · Bright",
        "tasting_notes": [
            {"note": "Blueberry", "intensity": 4},
            {"note": "Jasmine", "intensity": 3},
            {"note": "Honey", "intensity": 3}
        ],
        "brewing_methods": [
            {"method": "Pour Over", "description": "Highlight florals", "ratio": "1:17", "time": "3 min", "temperature": "90°C"},
            {"method": "AeroPress", "description": "Concentrated fruit", "ratio": "1:13", "time": "1.5 min", "temperature": "85°C"}
        ],
        "images": [
            {"url": "/assets/cape-ember/cape-ember-karoo-horizon-lifestyle.jpeg", "alt": "Cape Ember Karoo Horizon coffee inspired by the open Karoo landscape", "is_primary": True, "sort_order": 0}
        ],
        "variants": [
            {"id": "karoo-250g-whole", "name": "250g Whole Bean", "sku": "CB-KARO-250W", "price": 159.00, "grind": GrindType.WHOLE_BEAN, "weight": "250g", "stock_quantity": 25},
            {"id": "karoo-250g-ground", "name": "250g Ground", "sku": "CB-KARO-250G", "price": 159.00, "grind": GrindType.MEDIUM, "weight": "250g", "stock_quantity": 15}
        ],
        "tags": ["limited-edition", "single-origin", "ethiopian", "specialty"],
        "is_active": True,
        "is_featured": True,
        "is_bundle": False
    },
    {
        "id": "landscape-bundle",
        "name": "Landscape Bundle",
        "slug": "landscape-bundle",
        "description": "Experience the complete Cape Ember journey in one curated bundle. The Landscape Bundle brings together our four signature coffees in a single collection inspired by South Africa's coastlines, mountains, plains, and ember-lit evenings.",
        "short_description": "A curated four-coffee collection inspired by South African landscapes",
        "category": ProductCategory.GIFT_BOXES,
        "roast_level": RoastLevel.MEDIUM,
        "origin": "South African Roasted",
        "strength": 3,
        "flavor_notes": "Four signature coffees · 1kg total · curated savings",
        "tasting_notes": [
            {"note": "Nutty Sweetness", "intensity": 3},
            {"note": "Cocoa Depth", "intensity": 4},
            {"note": "Floral Brightness", "intensity": 3}
        ],
        "brewing_methods": [
            {"method": "French Press", "description": "A rich way to explore the darker and medium profiles", "ratio": "1:15", "time": "4 min", "temperature": "93°C"},
            {"method": "Pour Over", "description": "Best for comparing the bundle's brighter notes", "ratio": "1:16", "time": "3 min", "temperature": "92°C"}
        ],
        "images": [
            {"url": "/assets/cape-ember/cape-ember-landscape-bundle-banner.jpeg", "alt": "Cape Ember Coffee Co. Landscape Range featuring four South African landscape-inspired coffees", "is_primary": True, "sort_order": 0}
        ],
        "variants": [
            {"id": "landscape-bundle-1kg", "name": "4 x 250g Signature Collection", "sku": "CB-LAND-4X250", "price": 599.00, "grind": GrindType.WHOLE_BEAN, "weight": "4 x 250g", "stock_quantity": 12}
        ],
        "bundle_items": ["fynbos-roast", "garden-route", "ember-reserve", "karoo-horizon"],
        "tags": ["bundle", "gift-set", "featured"],
        "is_active": True,
        "is_featured": True,
        "is_bundle": True
    },
]

PRODUCTS_MAP = {p["id"]: p for p in PRODUCTS}


# ============ SHIPPING ZONES ============

SHIPPING_ZONES = {
    "Western Cape": {"standard": 50, "express": 95, "local_delivery": 35},
    "Gauteng": {"standard": 65, "express": 120},
    "KwaZulu-Natal": {"standard": 70, "express": 130},
    "Eastern Cape": {"standard": 70, "express": 130},
    "Free State": {"standard": 70, "express": 125},
    "Limpopo": {"standard": 75, "express": 140},
    "Mpumalanga": {"standard": 75, "express": 135},
    "North West": {"standard": 75, "express": 135},
    "Northern Cape": {"standard": 80, "express": 150}
}


# ============ AUTH ROUTES ============

@api_router.post("/auth/register", response_model=TokenResponse)
async def register(user_data: UserCreate, background_tasks: BackgroundTasks):
    existing = await db.users.find_one({"email": user_data.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    user_doc = {
        "_id": user_id,
        "email": user_data.email.lower(),
        "password_hash": hash_password(user_data.password),
        "first_name": user_data.first_name,
        "last_name": user_data.last_name,
        "phone": user_data.phone,
        "addresses": [],
        "notes": "",
        "tags": [],
        "accepts_marketing": user_data.accepts_marketing,
        "is_admin": False,
        "admin_role": None,
        "created_at": now,
        "updated_at": now
    }
    await db.users.insert_one(user_doc)
    
    # Create empty cart
    await db.carts.insert_one({"_id": user_id, "items": [], "coupon_code": None, "updated_at": now})
    
    # Create empty wishlist
    await db.wishlists.insert_one({"_id": user_id, "items": [], "updated_at": now})
    
    # Send welcome email and sync the customer to Resend
    background_tasks.add_task(send_welcome_email, user_data.email.lower(), user_data.first_name)
    background_tasks.add_task(
        resend_events.sync_resend_contact,
        user_data.email.lower(),
        user_data.first_name,
        user_data.last_name,
        {"accepts_marketing": user_data.accepts_marketing},
        unsubscribed=not user_data.accepts_marketing,
        segment_ids=[resend_events.SEGMENT_IDS["ember_circle"]] if resend_events.SEGMENT_IDS.get("ember_circle") else None
    )
    background_tasks.add_task(
        resend_events.emit_lifecycle_event,
        resend_events.EventName.subscriber_confirmed.value,
        {"email": user_data.email.lower(), "first_name": user_data.first_name},
        {"accepts_marketing": user_data.accepts_marketing, "created_account": True},
        None,
        None,
        user_id,
        None,
        None,
        "user",
        user_id
    )
    
    access_token = create_access_token(user_id, user_data.email, False, None)
    refresh_token = create_refresh_token(user_id)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(
            id=user_id,
            email=user_data.email,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            phone=user_data.phone,
            addresses=[],
            accepts_marketing=user_data.accepts_marketing,
            is_admin=False,
            admin_role=None,
            created_at=now
        )
    )


@api_router.post("/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    user = await db.users.find_one({"email": credentials.email.lower()})
    if not user or not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    access_token = create_access_token(user["_id"], user["email"], user.get("is_admin", False), user.get("admin_role"))
    refresh_token = create_refresh_token(user["_id"])
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(
            id=user["_id"],
            email=user["email"],
            first_name=user["first_name"],
            last_name=user["last_name"],
            phone=user.get("phone"),
            addresses=[AddressModel(**a) for a in user.get("addresses", [])],
            accepts_marketing=user.get("accepts_marketing", False),
            is_admin=user.get("is_admin", False),
            admin_role=user.get("admin_role"),
            created_at=user.get("created_at")
        )
    )


@api_router.post("/auth/refresh")
async def refresh_token(refresh_token: str = Header(...)):
    try:
        payload = jwt.decode(refresh_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        
        user = await db.users.find_one({"_id": payload["sub"]})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        new_access_token = create_access_token(user["_id"], user["email"], user.get("is_admin", False), user.get("admin_role"))
        
        return {"access_token": new_access_token, "token_type": "bearer"}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@api_router.post("/auth/forgot-password")
async def forgot_password(data: PasswordReset, background_tasks: BackgroundTasks):
    user = await db.users.find_one({"email": data.email.lower()})
    if user:
        reset_token = secrets.token_urlsafe(32)
        await db.password_resets.insert_one({
            "user_id": user["_id"],
            "token": reset_token,
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        background_tasks.add_task(send_password_reset, data.email, reset_token)
    
    return {"message": "If an account exists, a reset email has been sent"}


@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    return UserResponse(
        id=user["_id"],
        email=user["email"],
        first_name=user["first_name"],
        last_name=user["last_name"],
        phone=user.get("phone"),
        addresses=[AddressModel(**a) for a in user.get("addresses", [])],
        accepts_marketing=user.get("accepts_marketing", False),
        is_admin=user.get("is_admin", False),
        admin_role=user.get("admin_role"),
        created_at=user.get("created_at")
    )


@api_router.put("/auth/me", response_model=UserResponse)
async def update_me(data: UserUpdate, user: dict = Depends(get_current_user)):
    update_fields = {k: v for k, v in data.dict().items() if v is not None}
    if update_fields:
        update_fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        await db.users.update_one({"_id": user["_id"]}, {"$set": update_fields})
    
    updated_user = await db.users.find_one({"_id": user["_id"]})
    return UserResponse(
        id=updated_user["_id"],
        email=updated_user["email"],
        first_name=updated_user["first_name"],
        last_name=updated_user["last_name"],
        phone=updated_user.get("phone"),
        addresses=[AddressModel(**a) for a in updated_user.get("addresses", [])],
        accepts_marketing=updated_user.get("accepts_marketing", False),
        is_admin=updated_user.get("is_admin", False),
        admin_role=updated_user.get("admin_role"),
        created_at=updated_user.get("created_at")
    )


# ============ ADDRESS ROUTES ============

@api_router.post("/addresses")
async def add_address(address: AddressModel, user: dict = Depends(get_current_user)):
    address_data = address.dict()
    address_data["id"] = str(uuid.uuid4())
    
    # If this is the first address or marked as default, set it as default
    addresses = user.get("addresses", [])
    if not addresses or address_data.get("is_default"):
        # Remove default from other addresses
        for a in addresses:
            a["is_default"] = False
        address_data["is_default"] = True
    
    addresses.append(address_data)
    
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"addresses": addresses, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"message": "Address added", "address": address_data}


@api_router.put("/addresses/{address_id}")
async def update_address(address_id: str, address: AddressModel, user: dict = Depends(get_current_user)):
    addresses = user.get("addresses", [])
    
    for i, a in enumerate(addresses):
        if a["id"] == address_id:
            address_data = address.dict()
            address_data["id"] = address_id
            
            if address_data.get("is_default"):
                for other in addresses:
                    other["is_default"] = False
            
            addresses[i] = address_data
            break
    else:
        raise HTTPException(status_code=404, detail="Address not found")
    
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"addresses": addresses, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"message": "Address updated"}


@api_router.delete("/addresses/{address_id}")
async def delete_address(address_id: str, user: dict = Depends(get_current_user)):
    addresses = [a for a in user.get("addresses", []) if a["id"] != address_id]
    
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"addresses": addresses, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"message": "Address deleted"}


# ============ PRODUCT ROUTES ============

@api_router.get("/products")
async def get_products(
    category: Optional[str] = None,
    roast_level: Optional[str] = None,
    grind: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    in_stock: Optional[bool] = None,
    tags: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "featured",  # featured, newest, price_asc, price_desc, bestselling
    page: int = 1,
    limit: int = 20
):
    products = PRODUCTS.copy()
    
    # Filter by category
    if category:
        products = [p for p in products if p.get("category") == category or (hasattr(p.get("category"), "value") and p["category"].value == category)]
    
    # Filter by roast level
    if roast_level:
        products = [p for p in products if p.get("roast_level") and (p["roast_level"] == roast_level or (hasattr(p["roast_level"], "value") and p["roast_level"].value == roast_level))]
    
    # Filter by price
    if min_price:
        products = [p for p in products if p["variants"][0]["price"] >= min_price]
    if max_price:
        products = [p for p in products if p["variants"][0]["price"] <= max_price]
    
    # Filter by stock
    if in_stock:
        products = [p for p in products if sum(v["stock_quantity"] for v in p["variants"]) > 0]
    
    # Filter by tags
    if tags:
        tag_list = tags.split(",")
        products = [p for p in products if any(t in p.get("tags", []) for t in tag_list)]
    
    # Search
    if search:
        search_lower = search.lower()
        products = [p for p in products if 
            search_lower in p["name"].lower() or 
            search_lower in p.get("description", "").lower() or
            search_lower in p.get("flavor_notes", "").lower()
        ]
    
    # Sort
    if sort == "price_asc":
        products.sort(key=lambda p: p["variants"][0]["price"])
    elif sort == "price_desc":
        products.sort(key=lambda p: p["variants"][0]["price"], reverse=True)
    elif sort == "newest":
        products.reverse()  # Assuming newest at end
    # featured is default order
    
    # Pagination
    total = len(products)
    start = (page - 1) * limit
    end = start + limit
    products = products[start:end]
    
    # Format response
    result = []
    for p in products:
        base_variant = p["variants"][0]
        result.append({
            "id": p["id"],
            "name": p["name"],
            "slug": p["slug"],
            "description": p["description"],
            "short_description": p.get("short_description"),
            "category": p["category"].value if hasattr(p["category"], "value") else p["category"],
            "roast_level": p["roast_level"].value if p.get("roast_level") and hasattr(p["roast_level"], "value") else p.get("roast_level"),
            "origin": p.get("origin"),
            "strength": p.get("strength"),
            "flavor_notes": p["flavor_notes"],
            "images": p["images"],
            "price": base_variant["price"],
            "compare_at_price": base_variant.get("compare_at_price"),
            "variants": p["variants"],
            "tags": p.get("tags", []),
            "is_featured": p.get("is_featured", False),
            "is_bundle": p.get("is_bundle", False),
            "stock_status": "in_stock" if sum(v["stock_quantity"] for v in p["variants"]) > 0 else "out_of_stock",
            "total_stock": sum(v["stock_quantity"] for v in p["variants"])
        })
    
    return {
        "products": result,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit
    }


@api_router.get("/products/search")
async def search_products(q: str, limit: int = 10):
    """Autocomplete search"""
    if len(q) < 2:
        return {"results": []}
    
    q_lower = q.lower()
    results = []
    
    for p in PRODUCTS:
        if q_lower in p["name"].lower():
            results.append({
                "id": p["id"],
                "name": p["name"],
                "slug": p["slug"],
                "image": p["images"][0]["url"] if p["images"] else None,
                "price": p["variants"][0]["price"]
            })
            if len(results) >= limit:
                break
    
    return {"results": results}


@api_router.get("/products/categories")
async def get_categories():
    """Get all product categories with counts"""
    categories = {}
    for p in PRODUCTS:
        cat = p["category"].value if hasattr(p["category"], "value") else p["category"]
        if cat not in categories:
            categories[cat] = {"name": cat.replace("_", " ").title(), "count": 0}
        categories[cat]["count"] += 1
    
    return list(categories.values())


@api_router.get("/products/{product_id}")
async def get_product(product_id: str):
    product = PRODUCTS_MAP.get(product_id)
    if not product:
        product = next((p for p in PRODUCTS if p.get("slug") == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    canonical_product_id = product["id"]
    
    # Get reviews
    reviews = await db.reviews.find({"product_id": canonical_product_id, "is_approved": True}).to_list(10)
    avg_rating = sum(r["rating"] for r in reviews) / len(reviews) if reviews else 0
    
    # Get related products (same category, different product)
    related = [p for p in PRODUCTS if p["id"] != canonical_product_id and p.get("category") == product.get("category")][:4]
    
    base_variant = product["variants"][0]
    
    return {
        "id": product["id"],
        "name": product["name"],
        "slug": product["slug"],
        "description": product["description"],
        "short_description": product.get("short_description"),
        "category": product["category"].value if hasattr(product["category"], "value") else product["category"],
        "roast_level": product["roast_level"].value if product.get("roast_level") and hasattr(product["roast_level"], "value") else product.get("roast_level"),
        "origin": product.get("origin"),
        "strength": product.get("strength"),
        "flavor_notes": product["flavor_notes"],
        "tasting_notes": product.get("tasting_notes", []),
        "brewing_methods": product.get("brewing_methods", []),
        "images": product["images"],
        "variants": product["variants"],
        "price": base_variant["price"],
        "compare_at_price": base_variant.get("compare_at_price"),
        "tags": product.get("tags", []),
        "is_featured": product.get("is_featured", False),
        "is_bundle": product.get("is_bundle", False),
        "bundle_items": product.get("bundle_items", []),
        "stock_status": "in_stock" if sum(v["stock_quantity"] for v in product["variants"]) > 0 else "out_of_stock",
        "total_stock": sum(v["stock_quantity"] for v in product["variants"]),
        "average_rating": round(avg_rating, 1),
        "review_count": len(reviews),
        "related_products": [{
            "id": r["id"],
            "name": r["name"],
            "slug": r["slug"],
            "price": r["variants"][0]["price"],
            "image": r["images"][0]["url"] if r["images"] else None
        } for r in related]
    }


# ============ CART ROUTES ============

async def get_or_create_cart(user_id: Optional[str], session_id: Optional[str]) -> dict:
    """Get or create cart for user or guest session"""
    if user_id:
        cart = await db.carts.find_one({"_id": user_id})
        if not cart:
            cart = {"_id": user_id, "items": [], "coupon_code": None, "updated_at": datetime.now(timezone.utc).isoformat()}
            await db.carts.insert_one(cart)
        return cart
    elif session_id:
        cart = await db.guest_carts.find_one({"session_id": session_id})
        if not cart:
            cart = {"session_id": session_id, "items": [], "coupon_code": None, "updated_at": datetime.now(timezone.utc).isoformat()}
            await db.guest_carts.insert_one(cart)
        return cart
    raise HTTPException(status_code=400, detail="Authentication or session required")


def calculate_cart_totals(items: list, coupon: Optional[dict] = None, shipping_cost: float = 0.0, vat_rate: float = VAT_RATE) -> dict:
    """Calculate cart totals with optional coupon and shipping."""
    subtotal = sum(item["price"] * item["quantity"] for item in items)
    discount = 0.0
    
    if coupon:
        if coupon["discount_type"] == "percentage":
            discount = subtotal * (coupon["discount_value"] / 100)
        elif coupon["discount_type"] == "fixed_amount":
            discount = min(coupon["discount_value"], subtotal)
    
    discounted_subtotal = subtotal - discount
    vat = calculate_vat(discounted_subtotal, vat_rate)
    total = discounted_subtotal + shipping_cost
    
    return {
        "subtotal": round(subtotal, 2),
        "discount": round(discount, 2),
        "shipping": round(shipping_cost, 2),
        "vat": round(vat, 2),
        "total": round(total, 2),
        "item_count": sum(item["quantity"] for item in items)
    }


@api_router.get("/cart", response_model=CartResponse)
async def get_cart(
    user: Optional[dict] = Depends(get_current_user_optional),
    session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    user_id = user["_id"] if user else None
    cart = await get_or_create_cart(user_id, session_id)
    
    # Get coupon if applied
    coupon = None
    if cart.get("coupon_code"):
        coupon = await db.coupons.find_one({"code": cart["coupon_code"], "is_active": True})
    
    items = []
    for item in cart.get("items", []):
        product = PRODUCTS_MAP.get(item["product_id"])
        if product:
            variant = next((v for v in product["variants"] if v["id"] == item.get("variant_id")), product["variants"][0])
            items.append(CartItemResponse(
                id=f"{item['product_id']}_{item.get('variant_id', 'default')}",
                product_id=product["id"],
                variant_id=item.get("variant_id"),
                product_name=product["name"],
                variant_name=variant["name"],
                price=variant["price"],
                quantity=item["quantity"],
                image_url=product["images"][0]["url"] if product["images"] else "",
                stock_available=variant["stock_quantity"]
            ))
    
    store_rules = await get_store_rules()
    raw_subtotal = sum(i.price * i.quantity for i in items)
    shipping = 0.0 if raw_subtotal >= store_rules["free_shipping_threshold"] else store_rules["shipping_fee"]
    totals = calculate_cart_totals(
        [{"price": i.price, "quantity": i.quantity} for i in items],
        coupon,
        shipping,
        store_rules["vat_rate"],
    )
    
    return CartResponse(
        items=items,
        subtotal=totals["subtotal"],
        discount=totals["discount"],
        shipping=shipping,
        vat=totals["vat"],
        total=totals["total"],
        coupon_code=cart.get("coupon_code"),
        item_count=totals["item_count"]
    )


@api_router.post("/cart/add")
async def add_to_cart(
    item: CartItemAdd,
    user: Optional[dict] = Depends(get_current_user_optional),
    session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    product = PRODUCTS_MAP.get(item.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Validate variant
    variant_id = item.variant_id or product["variants"][0]["id"]
    variant = next((v for v in product["variants"] if v["id"] == variant_id), None)
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")
    
    # Check stock
    if variant["stock_quantity"] < item.quantity:
        raise HTTPException(status_code=400, detail="Insufficient stock")
    
    user_id = user["_id"] if user else None
    cart = await get_or_create_cart(user_id, session_id)
    
    items = cart.get("items", [])
    
    # Check if item already in cart
    existing = next((i for i in items if i["product_id"] == item.product_id and i.get("variant_id") == variant_id), None)
    
    if existing:
        existing["quantity"] += item.quantity
    else:
        items.append({
            "product_id": item.product_id,
            "variant_id": variant_id,
            "quantity": item.quantity
        })
    
    collection = db.carts if user_id else db.guest_carts
    key = "_id" if user_id else "session_id"
    value = user_id or session_id
    
    await collection.update_one(
        {key: value},
        {"$set": {"items": items, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"message": "Item added to cart"}


@api_router.put("/cart/items/{item_id}")
async def update_cart_item(
    item_id: str,
    update: CartItemUpdate,
    user: Optional[dict] = Depends(get_current_user_optional),
    session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    user_id = user["_id"] if user else None
    cart = await get_or_create_cart(user_id, session_id)
    
    items = cart.get("items", [])
    product_id, variant_id = item_id.rsplit("_", 1) if "_" in item_id else (item_id, "default")
    
    if update.quantity <= 0:
        items = [i for i in items if not (i["product_id"] == product_id and (i.get("variant_id") == variant_id or variant_id == "default"))]
    else:
        for item in items:
            if item["product_id"] == product_id and (item.get("variant_id") == variant_id or variant_id == "default"):
                item["quantity"] = update.quantity
                break
    
    collection = db.carts if user_id else db.guest_carts
    key = "_id" if user_id else "session_id"
    value = user_id or session_id
    
    await collection.update_one(
        {key: value},
        {"$set": {"items": items, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"message": "Cart updated"}


@api_router.delete("/cart/items/{item_id}")
async def remove_from_cart(
    item_id: str,
    user: Optional[dict] = Depends(get_current_user_optional),
    session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    user_id = user["_id"] if user else None
    cart = await get_or_create_cart(user_id, session_id)
    
    product_id, variant_id = item_id.rsplit("_", 1) if "_" in item_id else (item_id, "default")
    items = [i for i in cart.get("items", []) if not (i["product_id"] == product_id and (i.get("variant_id") == variant_id or variant_id == "default"))]
    
    collection = db.carts if user_id else db.guest_carts
    key = "_id" if user_id else "session_id"
    value = user_id or session_id
    
    await collection.update_one(
        {key: value},
        {"$set": {"items": items, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"message": "Item removed"}


@api_router.delete("/cart")
async def clear_cart(
    user: Optional[dict] = Depends(get_current_user_optional),
    session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    user_id = user["_id"] if user else None
    
    collection = db.carts if user_id else db.guest_carts
    key = "_id" if user_id else "session_id"
    value = user_id or session_id
    
    await collection.update_one(
        {key: value},
        {"$set": {"items": [], "coupon_code": None, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"message": "Cart cleared"}


# ============ COUPON ROUTES ============

class CouponApply(BaseModel):
    code: str

@api_router.post("/cart/coupon")
async def apply_coupon(
    coupon_data: CouponApply,
    user: Optional[dict] = Depends(get_current_user_optional),
    session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    code = coupon_data.code
    coupon = await db.coupons.find_one({"code": code.upper(), "is_active": True})
    
    if not coupon:
        raise HTTPException(status_code=404, detail="Invalid coupon code")
    
    now = datetime.now(timezone.utc)
    
    # Normalize timezone-naive datetimes from MongoDB to UTC
    valid_from = coupon["valid_from"]
    valid_until = coupon["valid_until"]
    
    # Handle both datetime objects and ISO strings
    if isinstance(valid_from, str):
        valid_from = datetime.fromisoformat(valid_from.replace('Z', '+00:00'))
    elif valid_from.tzinfo is None:
        valid_from = valid_from.replace(tzinfo=timezone.utc)
    
    if isinstance(valid_until, str):
        valid_until = datetime.fromisoformat(valid_until.replace('Z', '+00:00'))
    elif valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)
    
    if valid_from > now or valid_until < now:
        raise HTTPException(status_code=400, detail="Coupon has expired")
    
    user_id = user["_id"] if user else None
    cart = await get_or_create_cart(user_id, session_id)
    
    # Check minimum order
    items = cart.get("items", [])
    subtotal = 0
    for item in items:
        product = PRODUCTS_MAP.get(item["product_id"])
        if product:
            variant = next((v for v in product["variants"] if v["id"] == item.get("variant_id")), product["variants"][0])
            subtotal += variant["price"] * item["quantity"]
    
    if subtotal < coupon.get("minimum_order", 0):
        raise HTTPException(status_code=400, detail=f"Minimum order of R{coupon['minimum_order']} required")
    
    collection = db.carts if user_id else db.guest_carts
    key = "_id" if user_id else "session_id"
    value = user_id or session_id
    
    await collection.update_one(
        {key: value},
        {"$set": {"coupon_code": code.upper(), "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {
        "message": "Coupon applied", 
        "coupon": {
            "code": code.upper(),
            "discount_type": coupon["discount_type"], 
            "discount_value": coupon["discount_value"]
        }
    }


@api_router.delete("/cart/coupon")
async def remove_coupon(
    user: Optional[dict] = Depends(get_current_user_optional),
    session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    user_id = user["_id"] if user else None
    
    collection = db.carts if user_id else db.guest_carts
    key = "_id" if user_id else "session_id"
    value = user_id or session_id
    
    await collection.update_one(
        {key: value},
        {"$set": {"coupon_code": None, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"message": "Coupon removed"}


# ============ SHIPPING ROUTES ============

@api_router.get("/shipping/rates")
async def get_shipping_rates(province: str, subtotal: float, city: Optional[str] = None, postal_code: Optional[str] = None):
    """Get shipping rates for a province"""
    store_rules = await get_store_rules()
    threshold = store_rules["free_shipping_threshold"]

    local_delivery = is_free_local_delivery({"city": city, "province": province, "postal_code": postal_code}, ["sedgefield"])
    if local_delivery["eligible"]:
        return {
            "rates": [
                {"method": "standard", "name": "Standard Delivery (3-5 days)", "price": 0, "free": True},
                {"method": "express", "name": "Express Delivery (1-2 days)", "price": 0, "free": True},
                {"method": "local_delivery", "name": "Local Delivery (Same Day)", "price": 0, "free": True},
            ],
            "free_shipping_threshold": threshold,
            "message": "Free local delivery - Sedgefield"
        }

    if subtotal >= threshold:
        return {
            "rates": [
                {"method": "standard", "name": "Standard Delivery (3-5 days)", "price": 0, "free": True},
                {"method": "express", "name": "Express Delivery (1-2 days)", "price": 0, "free": True}
            ],
            "free_shipping_threshold": threshold,
            "message": f"Complimentary delivery on orders over R{int(threshold)}"
        }
    
    zone_rates = SHIPPING_ZONES.get(province, SHIPPING_ZONES.get("Western Cape"))
    rates = []
    
    if "standard" in zone_rates:
        rates.append({"method": "standard", "name": "Standard Delivery (3-5 days)", "price": zone_rates["standard"]})
    if "express" in zone_rates:
        rates.append({"method": "express", "name": "Express Delivery (1-2 days)", "price": zone_rates["express"]})
    if "local_delivery" in zone_rates:
        rates.append({"method": "local_delivery", "name": "Local Delivery (Same Day)", "price": zone_rates["local_delivery"]})
    
    rates.append({"method": "collection", "name": "Store Collection", "price": 0})
    
    return {
        "rates": rates,
        "free_shipping_threshold": threshold,
        "amount_until_free": max(0, threshold - subtotal)
    }


@api_router.get("/payments/providers")
async def get_payment_providers():
    providers = [
        {
            "id": "payfast",
            "label": "PayFast",
            "description": "Pay securely by card, Instant EFT or another enabled PayFast method.",
            "active": True,
        }
    ]
    return {"providers": providers}


# ============ CHECKOUT & ORDER ROUTES ============

@api_router.post("/checkout")
async def create_checkout(
    checkout: CheckoutCreate,
    background_tasks: BackgroundTasks,
    user: Optional[dict] = Depends(get_current_user_optional),
    session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    user_id = user["_id"] if user else None
    
    # For guest checkout, require email
    if not user_id and not checkout.guest_email:
        raise HTTPException(status_code=400, detail="Email required for guest checkout")
    
    cart = await get_or_create_cart(user_id, session_id)
    
    if not cart.get("items"):
        raise HTTPException(status_code=400, detail="Cart is empty")
    
    # Build order items
    order_items = []
    subtotal = 0.0
    
    for item in cart["items"]:
        product = PRODUCTS_MAP.get(item["product_id"])
        if not product:
            continue
        
        variant = next((v for v in product["variants"] if v["id"] == item.get("variant_id")), product["variants"][0])
        
        # Check stock
        if variant["stock_quantity"] < item["quantity"]:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {product['name']}")
        
        item_total = variant["price"] * item["quantity"]
        subtotal += item_total
        
        order_items.append({
            "product_id": product["id"],
            "product_name": product["name"],
            "variant_id": variant["id"],
            "variant_name": variant["name"],
            "sku": variant["sku"],
            "price": variant["price"],
            "quantity": item["quantity"],
            "total": item_total,
            "image_url": product["images"][0]["url"] if product["images"] else ""
        })
    
    # Calculate totals
    discount = 0.0
    coupon = None
    if cart.get("coupon_code"):
        coupon = await db.coupons.find_one({"code": cart["coupon_code"], "is_active": True})
        if coupon:
            if coupon["discount_type"] == "percentage":
                discount = subtotal * (coupon["discount_value"] / 100)
            elif coupon["discount_type"] == "fixed_amount":
                discount = min(coupon["discount_value"], subtotal)
    
    store_rules = await get_store_rules()
    store_settings = await db.settings.find_one({"_id": "store"}) or {}
    tax_config = resolve_tax_config(store_settings)

    shipping_result = resolve_shipping_charge(
        subtotal_after_discount=subtotal - discount,
        method=checkout.shipping.method,
        province=checkout.shipping.address.province,
        city=checkout.shipping.address.city,
        postal_code=checkout.shipping.address.postal_code,
        is_subscription=checkout.is_subscription,
        order_items=order_items,
        coupon=coupon,
        free_shipping_threshold=store_rules["free_shipping_threshold"],
        default_shipping_fee=store_rules["shipping_fee"],
        sedgefield_aliases=["sedgefield"],
    )
    shipping_cost = shipping_result["final_delivery_rate"]

    totals = calculate_cart_totals(
        [{"price": item["price"], "quantity": item["quantity"]} for item in order_items],
        coupon,
        shipping_cost,
        tax_config["taxRate"],
    )
    vat_components = calculate_vat_components(totals["subtotal"] - totals["discount"], tax_config)
    vat = vat_components["vat"]
    total = totals["total"]
    
    if total < 5.0:
        raise HTTPException(status_code=400, detail="Minimum order amount is R5.00")
    
    # Create order
    order_id = str(uuid.uuid4())
    order_number = generate_order_number()
    now = datetime.now(timezone.utc).isoformat()
    
    payment_snapshot = {
        "lines": [
            {
                "product_id": item["product_id"],
                "variant_id": item.get("variant_id"),
                "product_name": item["product_name"],
                "variant_name": item.get("variant_name"),
                "quantity": item["quantity"],
                "unit_price": round(float(item["price"]), 2),
                "line_total": round(float(item["total"]), 2),
            }
            for item in order_items
        ],
        "discount": totals["discount"],
        "delivery": {
            "original_rate": shipping_result["original_delivery_rate"],
            "waived_amount": shipping_result["waived_amount"],
            "applied_rule": shipping_result["applied_rule"],
            "reason": shipping_result["reason"],
            "final_rate": shipping_cost,
        },
        "vat": {
            "registration_status": tax_config["taxRegistrationStatus"],
            "rate": tax_config["taxRate"],
            "prices_include_tax": tax_config["pricesIncludeTax"],
            "gross": vat_components["gross"],
            "net": vat_components["net"],
            "vat": vat_components["vat"],
        },
        "currency": "ZAR",
        "customer_identifier": user_id or checkout.guest_email,
        "coupon_code": cart.get("coupon_code"),
    }

    payment_provider = "payfast"

    order_doc = {
        "_id": order_id,
        "order_number": order_number,
        "status_token": secrets.token_urlsafe(24),
        "user_id": user_id,
        "guest_email": checkout.guest_email if not user_id else None,
        "items": order_items,
        "subtotal": totals["subtotal"],
        "discount": totals["discount"],
        "shipping_cost": round(shipping_cost, 2),
        "shipping_snapshot": shipping_result,
        "vat": vat,
        "total": round(total, 2),
        "status": OrderStatus.PENDING_PAYMENT,
        "payment_status": PaymentStatus.PENDING,
        "payment_method": PaymentMethod.PAYFAST.value,
        "payment_provider": payment_provider,
        "payment_snapshot": payment_snapshot,
        "shipping": {
            "method": checkout.shipping.method,
            "address": checkout.shipping.address.dict(),
            "notes": checkout.shipping.notes
        },
        "billing": {
            "same_as_shipping": checkout.billing.same_as_shipping,
            "address": checkout.billing.address.dict() if checkout.billing.address else checkout.shipping.address.dict()
        },
        "coupon_code": cart.get("coupon_code"),
        "created_at": now,
        "updated_at": now
    }
    
    await db.orders.insert_one(order_doc)

    # Sync checkout contact and emit lifecycle event
    email = user["email"] if user else checkout.guest_email
    first_name = checkout.shipping.address.first_name
    background_tasks.add_task(
        resend_events.sync_resend_contact,
        email,
        first_name,
        checkout.shipping.address.last_name,
        {
            "checkout_id": order_id,
            "payment_method": PaymentMethod.PAYFAST.value,
            "subtotal": totals["subtotal"],
            "is_subscription": checkout.is_subscription,
        },
        unsubscribed=False
    )
    background_tasks.add_task(
        resend_events.emit_lifecycle_event,
        resend_events.EventName.checkout_started.value,
        {"email": email, "first_name": first_name},
        {
            "order_id": order_id,
            "payment_method": PaymentMethod.PAYFAST.value,
            "subtotal": totals["subtotal"],
            "is_subscription": checkout.is_subscription,
        },
        None,
        None,
        user_id,
        None,
        None,
        "order",
        order_id
    )
    
    provider = get_payment_provider(payment_provider)
    customer_identity = {
        "email": user["email"] if user else checkout.guest_email,
        "first_name": checkout.shipping.address.first_name,
        "last_name": checkout.shipping.address.last_name,
    }
    provider_checkout = await provider.create_checkout(order_doc, customer_identity)

    payment_attempt_id = str(uuid.uuid4())
    payment_attempt = {
        "_id": payment_attempt_id,
        "order_id": order_id,
        "order_number": order_number,
        "provider": payment_provider,
        "provider_reference": payment_attempt_id,
        "status": PaymentAttemptStatus.CREATED.value,
        "currency": "ZAR",
        "expected_total": round(float(total), 2),
        "request_payload": {
            "host": provider_checkout.get("host"),
            "field_keys": sorted(list((provider_checkout.get("fields") or {}).keys())),
        },
        "created_at": now,
        "updated_at": now,
    }
    await db.payment_attempts.insert_one(payment_attempt)

    await db.orders.update_one(
        {"_id": order_id},
        {
            "$set": {
                "payment_attempt_id": payment_attempt_id,
                "updated_at": now,
            }
        }
    )

    payment_data = {
        "method": "payfast",
        "action_url": provider_checkout.get("action_url") or f"https://{provider_checkout['host']}/eng/process",
        "host": provider_checkout["host"],
        "fields": provider_checkout["fields"],
        "attempt_id": payment_attempt_id,
    }
    
    return {
        "order_id": order_id,
        "order_number": order_number,
        "subtotal": totals["subtotal"],
        "discount": totals["discount"],
        "shipping_cost": round(shipping_cost, 2),
        "vat": vat,
        "total": total,
        "currency": "ZAR",
        "shipping_rule": shipping_result,
        "tax_config": {
            "taxRegistrationStatus": tax_config["taxRegistrationStatus"],
            "pricesIncludeTax": tax_config["pricesIncludeTax"],
        },
        "payment": payment_data
    }


# ============ SIMPLE ORDER ENDPOINTS (Legacy Frontend Support) ============

@api_router.post("/orders")
async def create_simple_order(
    order_data: SimpleOrderCreate,
    user: dict = Depends(get_current_user)
):
    """Create order using simple format for legacy frontend"""
    user_id = user["_id"]
    
    # Get cart
    cart = await db.carts.find_one({"_id": user_id})
    if not cart or not cart.get("items"):
        raise HTTPException(status_code=400, detail="Cart is empty")
    
    # Build order items
    order_items = []
    subtotal = 0.0
    
    for item in cart["items"]:
        product = PRODUCTS_MAP.get(item["product_id"])
        if not product:
            continue
        
        variant = next((v for v in product["variants"] if v["id"] == item.get("variant_id")), product["variants"][0])
        item_total = variant["price"] * item["quantity"]
        subtotal += item_total
        
        order_items.append({
            "product_id": product["id"],
            "product_name": product["name"],
            "variant_id": variant["id"],
            "variant_name": variant["name"],
            "sku": variant["sku"],
            "price": variant["price"],
            "quantity": item["quantity"],
            "total": item_total,
            "image_url": product["images"][0]["url"] if product["images"] else ""
        })
    
    # Calculate totals using the same coupon/shipping/VAT rules as cart.
    coupon = None
    if cart.get("coupon_code"):
        coupon = await db.coupons.find_one({"code": cart["coupon_code"], "is_active": True})

    discount = 0.0
    if coupon:
        if coupon["discount_type"] == "percentage":
            discount = subtotal * (coupon["discount_value"] / 100)
        elif coupon["discount_type"] == "fixed_amount":
            discount = min(coupon["discount_value"], subtotal)

    store_rules = await get_store_rules()
    store_settings = await db.settings.find_one({"_id": "store"}) or {}
    tax_config = resolve_tax_config(store_settings)
    shipping_result = resolve_shipping_charge(
        subtotal_after_discount=subtotal - discount,
        method=ShippingMethod.STANDARD,
        province=order_data.shipping_address.get("province", "Western Cape"),
        city=order_data.shipping_address.get("city"),
        postal_code=order_data.shipping_address.get("postal_code"),
        is_subscription=order_data.is_subscription,
        order_items=order_items,
        coupon=coupon,
        free_shipping_threshold=store_rules["free_shipping_threshold"],
        default_shipping_fee=store_rules["shipping_fee"],
        sedgefield_aliases=["sedgefield"],
    )
    shipping_cost = shipping_result["final_delivery_rate"]
    totals = calculate_cart_totals(
        [{"price": item["price"], "quantity": item["quantity"]} for item in order_items],
        coupon,
        shipping_cost,
        tax_config["taxRate"],
    )
    total = totals["total"]
    vat = calculate_vat_components(totals["subtotal"] - totals["discount"], tax_config)["vat"]
    discount = totals["discount"]
    
    # Generate order number and ID
    order_id = str(uuid.uuid4())
    order_count = await db.orders.count_documents({})
    order_number = f"CE-{(order_count + 1):06d}"
    now = datetime.now(timezone.utc).isoformat()
    
    # Create order document
    order_doc = {
        "_id": order_id,
        "order_number": order_number,
        "user_id": user_id,
        "items": order_items,
        "subtotal": totals["subtotal"],
        "discount": discount,
        "shipping_cost": round(shipping_cost, 2),
        "vat": vat,
        "total": total,
        "status": OrderStatus.PENDING_PAYMENT.value,
        "payment_status": PaymentStatus.PENDING.value,
        "payment_method": order_data.payment_method or "payfast",
        "payment_provider": "payfast",
        "shipping_snapshot": shipping_result,
        "shipping": {
            "method": "standard",
            "address": order_data.shipping_address,
            "notes": None
        },
        "billing": {
            "same_as_shipping": True,
            "address": order_data.shipping_address
        },
        "is_subscription": order_data.is_subscription,
        "subscription_frequency": order_data.subscription_frequency,
        "coupon_code": cart.get("coupon_code"),
        "created_at": now,
        "updated_at": now
    }
    
    await db.orders.insert_one(order_doc)
    
    # Generate WhatsApp link
    whatsapp_phone = "27810261618"
    items_text = ", ".join([f"{i['product_name']} x{i['quantity']}" for i in order_items])
    whatsapp_message = f"Hi! I just placed order {order_number}. Items: {items_text}. Total: R{total:.2f}"
    whatsapp_link = f"https://wa.me/{whatsapp_phone}?text={urllib.parse.quote(whatsapp_message)}"
    
    return {
        "order_id": order_id,
        "order_number": order_number,
        "total": total,
        "whatsapp_link": whatsapp_link
    }


@api_router.post("/payfast/create-payment")
async def create_payfast_payment(payment: SimplePaymentCreate, user: dict = Depends(get_current_user)):
    """Create PayFast payment for an existing order"""
    order = await db.orders.find_one({"_id": payment.order_id, "user_id": user["_id"]})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    provider = get_payment_provider("payfast")
    payment_payload = await provider.create_checkout(
        order,
        {
            "email": user.get("email"),
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
        },
    )

    attempt_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    if hasattr(db, "payment_attempts"):
        await db.payment_attempts.insert_one(
            {
                "_id": attempt_id,
                "order_id": payment.order_id,
                "order_number": order.get("order_number"),
                "provider": "payfast",
                "provider_reference": attempt_id,
                "status": PaymentAttemptStatus.CREATED.value,
                "currency": "ZAR",
                "expected_total": round(float(order.get("total", 0)), 2),
                "request_payload": {
                    "host": payment_payload.get("host"),
                    "field_keys": sorted(list((payment_payload.get("fields") or {}).keys())),
                },
                "created_at": now,
                "updated_at": now,
            }
        )
    if hasattr(db.orders, "update_one"):
        await db.orders.update_one({"_id": payment.order_id}, {"$set": {"payment_attempt_id": attempt_id, "updated_at": now}})

    if PAYFAST_DEBUG:
        payload_debug = {k: v for k, v in (payment_payload.get("fields") or {}).items() if k != "passphrase"}
        logger.info("PayFast create-payment debug: %s", payload_debug)

    logger.info(
        "PayFast create-payment prepared: order_id=%s attempt_id=%s amount=%s action_url=%s fields=%s",
        payment.order_id,
        attempt_id,
        (payment_payload.get("fields") or {}).get("amount"),
        payment_payload.get("action_url") or f"https://{payment_payload.get('host')}/eng/process",
        sorted(list((payment_payload.get("fields") or {}).keys())),
    )
    
    return {
        "payfast_host": payment_payload["host"],
        "action_url": payment_payload.get("action_url") or f"https://{payment_payload['host']}/eng/process",
        "fields": payment_payload["fields"],
        "attempt_id": attempt_id,
    }



@api_router.get("/orders")
async def get_orders(user: dict = Depends(get_current_user), page: int = 1, limit: int = 10):
    skip = (page - 1) * limit
    
    orders = await db.orders.find(
        {"user_id": user["_id"]},
        {"_id": 1, "order_number": 1, "items": 1, "total": 1, "status": 1, "payment_status": 1, "created_at": 1}
    ).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    
    total = await db.orders.count_documents({"user_id": user["_id"]})
    
    return {
        "orders": [{
            "id": o["_id"],
            "order_number": o["order_number"],
            "items": o["items"],
            "total": o["total"],
            "status": o["status"],
            "payment_status": o["payment_status"],
            "created_at": o["created_at"]
        } for o in orders],
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit
    }


@api_router.get("/orders/{order_id}/status")
async def get_order_status(order_id: str, status_token: Optional[str] = None, user: Optional[dict] = Depends(get_current_user_optional)):
    """Public lightweight status endpoint for payment return page polling.
    Returns only non-sensitive status fields so guests can poll post-payment."""
    order = await db.orders.find_one({"_id": order_id}, {"status": 1, "payment_status": 1, "order_number": 1})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if user:
        owner_id = user.get("_id")
        full_order = await db.orders.find_one({"_id": order_id}, {"user_id": 1})
        if full_order and full_order.get("user_id") and full_order.get("user_id") != owner_id:
            raise HTTPException(status_code=403, detail="Forbidden")
    else:
        full_order = await db.orders.find_one({"_id": order_id}, {"status_token": 1})
        expected_token = (full_order or {}).get("status_token")
        if expected_token and status_token != expected_token:
            raise HTTPException(status_code=403, detail="Invalid status token")

    return {
        "order_id": order_id,
        "order_number": order.get("order_number"),
        "status": order.get("status"),
        "payment_status": order.get("payment_status"),
    }


@api_router.post("/orders/{order_id}/payment/cancel")
async def cancel_order_payment(order_id: str, status_token: Optional[str] = None, user: Optional[dict] = Depends(get_current_user_optional)):
    order = await db.orders.find_one({"_id": order_id}, {"_id": 1, "user_id": 1, "status_token": 1})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if user:
        if order.get("user_id") and order.get("user_id") != user.get("_id"):
            raise HTTPException(status_code=403, detail="Forbidden")
    elif order.get("status_token") and status_token != order.get("status_token"):
        raise HTTPException(status_code=403, detail="Invalid status token")

    now = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one(
        {"_id": order_id},
        {"$set": {"status": OrderStatus.PENDING_PAYMENT.value, "payment_status": PaymentStatus.CANCELLED.value, "updated_at": now}},
    )
    await db.payment_attempts.update_many(
        {"order_id": order_id, "status": {"$in": [PaymentAttemptStatus.CREATED.value, PaymentAttemptStatus.PENDING.value, PaymentAttemptStatus.REDIRECTED.value]}},
        {"$set": {"status": PaymentAttemptStatus.CANCELLED.value, "updated_at": now}},
    )
    return {"message": "Payment attempt cancelled"}


@api_router.get("/orders/{order_id}")
async def get_order(order_id: str, user: Optional[dict] = Depends(get_current_user_optional)):
    query = {"_id": order_id}
    if user:
        query["user_id"] = user["_id"]
    
    order = await db.orders.find_one(query)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    return {
        "id": order["_id"],
        "order_number": order["order_number"],
        "items": order["items"],
        "subtotal": order["subtotal"],
        "discount": order["discount"],
        "shipping_cost": order["shipping_cost"],
        "vat": order["vat"],
        "total": order["total"],
        "status": order["status"],
        "payment_status": order["payment_status"],
        "payment_method": order["payment_method"],
        "shipping": order["shipping"],
        "billing": order["billing"],
        "tracking_number": order.get("tracking_number"),
        "created_at": order["created_at"],
        "updated_at": order["updated_at"]
    }


@api_router.post("/orders/{order_id}/reorder")
async def reorder(order_id: str, user: dict = Depends(get_current_user)):
    """Add items from a previous order to cart"""
    order = await db.orders.find_one({"_id": order_id, "user_id": user["_id"]})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    cart = await db.carts.find_one({"_id": user["_id"]})
    items = cart.get("items", []) if cart else []
    
    for item in order["items"]:
        existing = next((i for i in items if i["product_id"] == item["product_id"] and i.get("variant_id") == item.get("variant_id")), None)
        if existing:
            existing["quantity"] += item["quantity"]
        else:
            items.append({
                "product_id": item["product_id"],
                "variant_id": item.get("variant_id"),
                "quantity": item["quantity"]
            })
    
    await db.carts.update_one(
        {"_id": user["_id"]},
        {"$set": {"items": items, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True
    )
    
    return {"message": "Items added to cart"}


# ============ WEBHOOK ROUTES ============

@api_router.post("/webhooks/payfast")
async def payfast_webhook(request: Request, background_tasks: BackgroundTasks):
    """PayFast ITN webhook handler — authoritative payment signal."""
    now = datetime.now(timezone.utc).isoformat()
    order_id = None
    payment_status = ""
    validation_stage = "received"
    failure_reason = ""
    response_status = 500
    idempotency_outcome = "none"

    try:
        content_type = (request.headers.get("content-type") or "").lower()
        if "application/x-www-form-urlencoded" not in content_type and "multipart/form-data" not in content_type:
            validation_stage = "content_type"
            failure_reason = "unsupported_content_type"
            response_status = 400
            return JSONResponse({"detail": "Malformed ITN payload"}, status_code=400)

        form_data = await request.form()
        data = {k: str(v).strip() for k, v in dict(form_data).items()}
        order_id = data.get("m_payment_id")
        payment_status = data.get("payment_status", "")
        pf_payment_id = data.get("pf_payment_id", "")
        amount_gross = data.get("amount_gross", "0")

        validation = validate_payfast_itn_payload(data)
        validation_stage = "payload_validation"
        if not validation["valid"]:
            failure_reason = validation["reason_code"]
            response_status = validation["status_code"]
            if order_id:
                await db.payment_attempts.update_many(
                    {"order_id": order_id, "provider": "payfast"},
                    {"$set": {"status": PaymentAttemptStatus.INVALID_NOTIFICATION.value, "updated_at": now}},
                )
            return JSONResponse({"detail": "Invalid PayFast ITN"}, status_code=response_status)

        event_key = f"payfast:{order_id}:{pf_payment_id}:{payment_status}:{amount_gross}"
        webhook_result = await db.webhook_events.update_one(
            {"provider": "payfast", "event_key": event_key},
            {
                "$setOnInsert": {
                    "_id": str(uuid.uuid4()),
                    "provider": "payfast",
                    "event_key": event_key,
                    "order_id": order_id,
                    "payload": data,
                    "received_at": now,
                }
            },
            upsert=True,
        )
        if getattr(webhook_result, "matched_count", 0):
            idempotency_outcome = "duplicate_event_key"

        order = await db.orders.find_one({"_id": order_id})
        validation_stage = "order_lookup"
        if not order:
            failure_reason = "order_not_found"
            response_status = 404
            return JSONResponse({"detail": "Order not found"}, status_code=404)

        await db.orders.update_one(
            {"_id": order_id},
            {"$set": {"status": OrderStatus.PAYMENT_PROCESSING.value, "updated_at": now}},
        )

        if pf_payment_id:
            conflicting = await db.orders.find_one(
                {
                    "payfast_payment_id": pf_payment_id,
                    "_id": {"$ne": order_id},
                    "payment_status": PaymentStatus.COMPLETE.value,
                },
                {"_id": 1, "order_number": 1},
            )
            if conflicting:
                failure_reason = "transaction_reuse"
                response_status = 400
                await db.payment_attempts.update_many(
                    {"order_id": order_id, "provider": "payfast"},
                    {"$set": {"status": PaymentAttemptStatus.INVALID_NOTIFICATION.value, "updated_at": now}},
                )
                return JSONResponse({"detail": "Invalid PayFast ITN"}, status_code=400)

        if payment_status == "COMPLETE":
            validation_stage = "complete_processing"
            if str(order.get("payment_status")) == PaymentStatus.COMPLETE.value:
                idempotency_outcome = "already_paid"
                response_status = 200
                return Response(content="OK", status_code=200)

            try:
                reported_amount = round(float(amount_gross), 2)
                expected_amount = round(float(order["total"]), 2)
            except (TypeError, ValueError):
                failure_reason = "invalid_amount_format"
                response_status = 400
                return JSONResponse({"detail": "Invalid PayFast ITN"}, status_code=400)

            if abs(reported_amount - expected_amount) > 0.05:
                failure_reason = "amount_mismatch"
                response_status = 400
                await db.orders.update_one(
                    {"_id": order_id},
                    {"$set": {"status": OrderStatus.PAYMENT_FAILED.value, "payment_status": PaymentStatus.FAILED.value, "payment_failure_reason": "payfast_amount_mismatch", "updated_at": now}},
                )
                await db.payment_attempts.update_many(
                    {"order_id": order_id, "provider": "payfast"},
                    {"$set": {"status": PaymentAttemptStatus.INVALID_NOTIFICATION.value, "updated_at": now}},
                )
                return JSONResponse({"detail": "Invalid PayFast ITN"}, status_code=400)

            await db.orders.update_one(
                {"_id": order_id},
                {
                    "$set": {
                        "status": OrderStatus.PAID.value,
                        "payment_status": PaymentStatus.COMPLETE.value,
                        "payfast_payment_id": pf_payment_id,
                        "paid_at": now,
                        "updated_at": now,
                    }
                },
            )
            await db.payment_attempts.update_many(
                {"order_id": order_id, "provider": "payfast"},
                {"$set": {"status": PaymentAttemptStatus.SUCCESSFUL.value, "provider_reference": pf_payment_id, "updated_at": now}},
            )

            if order.get("user_id"):
                await db.carts.update_one({"_id": order["user_id"]}, {"$set": {"items": [], "coupon_code": None}})

            email = order.get("guest_email")
            if order.get("user_id"):
                user = await db.users.find_one({"_id": order["user_id"]})
                email = user["email"] if user else email

            if email:
                background_tasks.add_task(send_order_confirmation, order, email)
                background_tasks.add_task(
                    resend_events.emit_lifecycle_event,
                    resend_events.EventName.order_placed.value,
                    {"email": email},
                    {
                        "order_number": order["order_number"],
                        "total": order["total"],
                        "payment_method": order["payment_method"],
                    },
                    None,
                    None,
                    order.get("user_id"),
                    None,
                    None,
                    "order",
                    order_id,
                )
                background_tasks.add_task(
                    resend_events.emit_lifecycle_event,
                    resend_events.EventName.order_payment_confirmed.value,
                    {"email": email},
                    {
                        "order_number": order["order_number"],
                        "total": order["total"],
                        "payment_method": order["payment_method"],
                    },
                    None,
                    None,
                    order.get("user_id"),
                    None,
                    None,
                    "order",
                    order_id,
                )
            background_tasks.add_task(send_admin_order_notification, order)

        elif payment_status == "CANCELLED":
            validation_stage = "cancelled_processing"
            await db.orders.update_one(
                {"_id": order_id},
                {"$set": {"status": OrderStatus.PENDING_PAYMENT.value, "payment_status": PaymentStatus.CANCELLED.value, "updated_at": now}},
            )
            await db.payment_attempts.update_many(
                {"order_id": order_id, "provider": "payfast"},
                {"$set": {"status": PaymentAttemptStatus.CANCELLED.value, "updated_at": now}},
            )

        elif payment_status == "FAILED":
            validation_stage = "failed_processing"
            await db.orders.update_one(
                {"_id": order_id},
                {"$set": {"status": OrderStatus.PAYMENT_FAILED.value, "payment_status": PaymentStatus.FAILED.value, "updated_at": now}},
            )
            await db.payment_attempts.update_many(
                {"order_id": order_id, "provider": "payfast"},
                {"$set": {"status": PaymentAttemptStatus.FAILED.value, "updated_at": now}},
            )

        response_status = 200
        return Response(content="OK", status_code=200)
    except HTTPException as exc:
        failure_reason = "http_exception"
        response_status = exc.status_code
        return JSONResponse({"detail": str(exc.detail)}, status_code=exc.status_code)
    except Exception:
        failure_reason = "unexpected_internal_error"
        response_status = 500
        logger.exception("PayFast ITN unexpected failure")
        return JSONResponse({"detail": "Internal Server Error"}, status_code=500)
    finally:
        logger.info(
            "PayFast ITN event: timestamp=%s order_id=%s payment_status=%s stage=%s reason=%s response_status=%s idempotency=%s",
            now,
            order_id or "",
            payment_status,
            validation_stage,
            failure_reason or "none",
            response_status,
            idempotency_outcome,
        )


@api_router.post("/webhooks/resend")
async def resend_webhook(request: Request, background_tasks: BackgroundTasks):
    """Resend webhook handler for event verification and logging"""
    body = await request.body()
    try:
        verified_payload = await resend_events.verify_resend_webhook(request, body)
    except Exception:
        logger.warning("Resend webhook verification failed")
        return Response(content="Invalid webhook", status_code=400)

    await db.resend_webhook_events.insert_one({
        "id": verified_payload.get("id"),
        "event": verified_payload.get("event"),
        "payload": verified_payload,
        "received_at": datetime.now(timezone.utc).isoformat()
    })

    return Response(content="OK", status_code=200)


# ============ WISHLIST ROUTES ============

@api_router.get("/wishlist")
async def get_wishlist(user: dict = Depends(get_current_user)):
    wishlist = await db.wishlists.find_one({"_id": user["_id"]})
    items = []
    
    for product_id in wishlist.get("items", []) if wishlist else []:
        product = PRODUCTS_MAP.get(product_id)
        if product:
            items.append({
                "id": product["id"],
                "name": product["name"],
                "slug": product["slug"],
                "price": product["variants"][0]["price"],
                "image": product["images"][0]["url"] if product["images"] else None,
                "stock_status": "in_stock" if sum(v["stock_quantity"] for v in product["variants"]) > 0 else "out_of_stock"
            })
    
    return {"items": items}


@api_router.post("/wishlist")
async def add_to_wishlist(item: WishlistItemAdd, user: dict = Depends(get_current_user)):
    if item.product_id not in PRODUCTS_MAP:
        raise HTTPException(status_code=404, detail="Product not found")
    
    await db.wishlists.update_one(
        {"_id": user["_id"]},
        {"$addToSet": {"items": item.product_id}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True
    )
    
    return {"message": "Added to wishlist"}


@api_router.delete("/wishlist/{product_id}")
async def remove_from_wishlist(product_id: str, user: dict = Depends(get_current_user)):
    await db.wishlists.update_one(
        {"_id": user["_id"]},
        {"$pull": {"items": product_id}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"message": "Removed from wishlist"}


# ============ REVIEW ROUTES ============

@api_router.get("/products/{product_id}/reviews")
async def get_product_reviews(product_id: str, page: int = 1, limit: int = 10):
    skip = (page - 1) * limit
    
    reviews = await db.reviews.find(
        {"product_id": product_id, "is_approved": True}
    ).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    
    total = await db.reviews.count_documents({"product_id": product_id, "is_approved": True})
    
    return {
        "reviews": [{
            "id": str(r["_id"]),
            "user_name": r["user_name"],
            "rating": r["rating"],
            "title": r["title"],
            "content": r["content"],
            "is_verified_purchase": r.get("is_verified_purchase", False),
            "helpful_votes": r.get("helpful_votes", 0),
            "created_at": r["created_at"]
        } for r in reviews],
        "total": total,
        "page": page,
        "average_rating": await get_average_rating(product_id)
    }


async def get_average_rating(product_id: str) -> float:
    pipeline = [
        {"$match": {"product_id": product_id, "is_approved": True}},
        {"$group": {"_id": None, "avg": {"$avg": "$rating"}}}
    ]
    result = await db.reviews.aggregate(pipeline).to_list(1)
    return round(result[0]["avg"], 1) if result else 0.0


@api_router.post("/products/{product_id}/reviews")
async def create_review(product_id: str, review: ReviewCreate, user: dict = Depends(get_current_user)):
    if product_id not in PRODUCTS_MAP:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Check if user has purchased this product
    has_purchased = await db.orders.find_one({
        "user_id": user["_id"],
        "items.product_id": product_id,
        "payment_status": PaymentStatus.COMPLETE
    })
    
    # Check if user already reviewed
    existing = await db.reviews.find_one({"product_id": product_id, "user_id": user["_id"]})
    if existing:
        raise HTTPException(status_code=400, detail="You have already reviewed this product")
    
    now = datetime.now(timezone.utc).isoformat()
    
    review_doc = {
        "product_id": product_id,
        "user_id": user["_id"],
        "user_name": f"{user['first_name']} {user['last_name'][0]}.",
        "rating": review.rating,
        "title": review.title,
        "content": review.content,
        "is_verified_purchase": has_purchased is not None,
        "is_approved": True,  # Auto-approve for now
        "helpful_votes": 0,
        "created_at": now
    }
    
    result = await db.reviews.insert_one(review_doc)
    
    return {"message": "Review submitted", "review_id": str(result.inserted_id)}


# ============ CONTACT ROUTES ============

@api_router.post("/contact")
async def submit_contact(
    payload: ContactSubmissionRequest,
    background_tasks: BackgroundTasks
):
    if payload.website and payload.website.strip():
        raise HTTPException(status_code=400, detail="Invalid submission")

    await db.contact_submissions.insert_one({
        "_id": str(uuid.uuid4()),
        "name": payload.name,
        "email": payload.email,
        "subject": payload.subject,
        "message": payload.message,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_read": False
    })

    background_tasks.add_task(send_contact_emails, payload.name, str(payload.email), payload.subject, payload.message)
    return {"message": "Thanks — we've received your message and will get back to you shortly."}


# ============ SUBSCRIPTION ROUTES ============

@api_router.post("/subscriptions/request")
async def create_subscription_request(
    request_data: SubscriptionRequestCreate,
    background_tasks: BackgroundTasks,
    user: Optional[dict] = Depends(get_current_user_optional)
):
    now = datetime.now(timezone.utc)
    subscription_id = str(uuid.uuid4())
    customer_email = user.get("email") if user else (str(request_data.customer_email).lower() if request_data.customer_email else None)
    customer_name = (
        f"{user.get('first_name','')} {user.get('last_name','')}".strip()
        if user
        else (request_data.customer_name or "Guest")
    )

    if not customer_email:
        raise HTTPException(status_code=400, detail="Customer email is required for subscription requests")

    doc = {
        "_id": subscription_id,
        "user_id": user.get("_id") if user else None,
        "customer_email": customer_email,
        "customer_name": customer_name,
        "plan_name": request_data.plan_name,
        "blend": request_data.blend,
        "grind": request_data.grind,
        "frequency": request_data.frequency,
        "quantity": request_data.quantity,
        "delivery_address": request_data.delivery_address,
        "preferred_delivery_day": request_data.preferred_delivery_day,
        "delivery_notes": request_data.delivery_notes,
        "status": "requested",
        "payment_status": "pending_manual",
        "next_delivery_date": None,
        "order_history": [],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat()
    }
    await db.subscriptions.insert_one(doc)
    background_tasks.add_task(send_subscription_request_emails, doc)
    background_tasks.add_task(
        resend_events.sync_resend_contact,
        customer_email,
        None,
        None,
        {
            "subscription_request": True,
            "plan_name": request_data.plan_name,
            "blend": request_data.blend,
            "frequency": request_data.frequency,
        },
        unsubscribed=False,
        segment_ids=[resend_events.SEGMENT_IDS["ember_circle"]] if resend_events.SEGMENT_IDS.get("ember_circle") else None
    )
    background_tasks.add_task(
        resend_events.emit_lifecycle_event,
        resend_events.EventName.subscriber_form_submitted.value,
        {"email": customer_email, "first_name": user.get("first_name") if user else None},
        {
            "plan_name": request_data.plan_name,
            "blend": request_data.blend,
            "frequency": request_data.frequency,
            "delivery_notes": request_data.delivery_notes,
        },
        None,
        None,
        user.get("_id") if user else None,
        None,
        None,
        "subscription_request",
        subscription_id
    )

    return {"message": "Subscription request submitted", "id": subscription_id}


@api_router.post("/analytics/event")
async def ingest_analytics_event(event: AnalyticsEventIn, request: Request):
    """Ingest first-party analytics events from the storefront."""
    now_iso = datetime.now(timezone.utc).isoformat()
    forwarded_for = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "")

    event_doc = {
        "_id": str(uuid.uuid4()),
        "event_name": event.event_name[:64],
        "anonymous_id": (event.anonymous_id or "")[:128],
        "session_id": (event.session_id or "")[:128],
        "page_path": (event.page_path or "")[:255],
        "referrer": (event.referrer or "")[:1024],
        "params": event.params or {},
        "user_agent": request.headers.get("user-agent", "")[:512],
        "ip": client_ip,
        "created_at": now_iso
    }

    await db.analytics_events.insert_one(event_doc)
    return {"message": "Event captured"}


@api_router.get("/subscriptions")
async def list_my_subscriptions(user: dict = Depends(get_current_user)):
    subscriptions = await db.subscriptions.find({"user_id": user["_id"]}).sort("created_at", -1).to_list(None)
    return [{
        "id": s.get("_id"),
        "plan_name": s.get("plan_name"),
        "blend": s.get("blend"),
        "grind": s.get("grind"),
        "frequency": s.get("frequency"),
        "quantity": s.get("quantity", 1),
        "status": s.get("status", "requested"),
        "payment_status": s.get("payment_status", "pending_manual"),
        "next_delivery_date": s.get("next_delivery_date")
    } for s in subscriptions]


@api_router.put("/subscriptions/{subscription_id}/pause")
async def pause_subscription(subscription_id: str, user: dict = Depends(get_current_user)):
    result = await db.subscriptions.update_one(
        {"_id": subscription_id, "user_id": user["_id"]},
        {"$set": {"status": "paused", "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"message": "Subscription paused"}


@api_router.put("/subscriptions/{subscription_id}/resume")
async def resume_subscription(subscription_id: str, user: dict = Depends(get_current_user)):
    result = await db.subscriptions.update_one(
        {"_id": subscription_id, "user_id": user["_id"]},
        {"$set": {"status": "active", "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"message": "Subscription resumed"}


@api_router.delete("/subscriptions/{subscription_id}")
async def cancel_subscription(subscription_id: str, user: dict = Depends(get_current_user)):
    result = await db.subscriptions.update_one(
        {"_id": subscription_id, "user_id": user["_id"]},
        {"$set": {"status": "cancelled", "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"message": "Subscription cancelled"}


@api_router.get("/admin/subscriptions")
async def get_admin_subscriptions(
    admin: dict = Depends(get_admin_user),
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 30
):
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    skip = max(0, (page - 1) * limit)
    total = await db.subscriptions.count_documents(query)
    subscriptions = await db.subscriptions.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {
        "subscriptions": [{
            "id": s.get("_id"),
            "customer_name": s.get("customer_name", ""),
            "customer_email": s.get("customer_email", ""),
            "plan_name": s.get("plan_name"),
            "blend": s.get("blend"),
            "grind": s.get("grind"),
            "frequency": s.get("frequency"),
            "quantity": s.get("quantity", 1),
            "status": s.get("status"),
            "payment_status": s.get("payment_status"),
            "next_delivery_date": s.get("next_delivery_date"),
            "delivery_notes": s.get("delivery_notes"),
            "created_at": s.get("created_at")
        } for s in subscriptions],
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit
    }


@api_router.put("/admin/subscriptions/{subscription_id}")
async def update_admin_subscription(
    subscription_id: str,
    update: SubscriptionStatusUpdate,
    admin: dict = Depends(get_admin_user)
):
    payload = {k: v for k, v in update.dict().items() if v is not None}
    if not payload:
        raise HTTPException(status_code=400, detail="No update fields supplied")
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.subscriptions.update_one({"_id": subscription_id}, {"$set": payload})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"message": "Subscription updated", "id": subscription_id}


# ============ ADMIN DASHBOARD ROUTES ============

@api_router.get("/admin/dashboard")
async def get_admin_dashboard(admin: dict = Depends(get_admin_user)):
    """Get admin dashboard statistics"""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    
    # Total orders and revenue
    all_orders = await db.orders.find({"payment_status": "complete"}).to_list(None)
    total_orders = len(all_orders)
    total_revenue = sum(order.get("total", 0) for order in all_orders)
    
    # Today's stats
    today_orders = [o for o in all_orders if o.get("created_at", "") >= today_start.isoformat()]
    orders_today = len(today_orders)
    revenue_today = sum(order.get("total", 0) for order in today_orders)
    
    # This week's stats
    week_orders = [o for o in all_orders if o.get("created_at", "") >= week_ago.isoformat()]
    orders_this_week = len(week_orders)
    revenue_this_week = sum(order.get("total", 0) for order in week_orders)
    
    # This month's stats
    month_orders = [o for o in all_orders if o.get("created_at", "") >= month_ago.isoformat()]
    orders_this_month = len(month_orders)
    revenue_this_month = sum(order.get("total", 0) for order in month_orders)
    
    # Pending orders
    pending_orders = await db.orders.count_documents({"status": {"$in": ["pending", "pending_payment", "processing"]}})
    
    # Low stock products (less than 10 units)
    low_stock_count = sum(
        1 for p in PRODUCTS 
        for v in p.get("variants", []) 
        if v.get("stock_quantity", 0) < 10
    )
    
    # New customers (registered this month)
    new_customers = await db.users.count_documents({
        "created_at": {"$gte": month_ago.isoformat()}
    })
    
    # Total customers
    total_customers = await db.users.count_documents({})

    # Subscription stats
    active_subscriptions = await db.subscriptions.count_documents({"status": {"$in": ["active", "requested"]}})
    
    # Recent orders
    recent_orders = await db.orders.find().sort("created_at", -1).limit(5).to_list(5)
    recent_orders_formatted = []
    for order in recent_orders:
        recent_orders_formatted.append({
            "id": order["_id"],
            "order_number": order.get("order_number", "N/A"),
            "customer_email": order.get("guest_email") or "Registered User",
            "total": order.get("total", 0),
            "status": order.get("status", "unknown"),
            "created_at": order.get("created_at", "")
        })
    
    # Top products by orders
    product_counts = {}
    for order in all_orders:
        for item in order.get("items", []):
            pid = item.get("product_id", "")
            product_counts[pid] = product_counts.get(pid, 0) + item.get("quantity", 1)
    
    top_products = sorted(product_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_products_formatted = []
    for pid, count in top_products:
        product = PRODUCTS_MAP.get(pid)
        if product:
            top_products_formatted.append({
                "id": pid,
                "name": product["name"],
                "units_sold": count,
                "revenue": count * product["variants"][0]["price"]
            })
    
    return {
        "overview": {
            "total_orders": total_orders,
            "total_revenue": round(total_revenue, 2),
            "orders_today": orders_today,
            "revenue_today": round(revenue_today, 2),
            "orders_this_week": orders_this_week,
            "revenue_this_week": round(revenue_this_week, 2),
            "orders_this_month": orders_this_month,
            "revenue_this_month": round(revenue_this_month, 2),
            "pending_orders": pending_orders,
            "low_stock_products": low_stock_count,
            "new_customers": new_customers,
            "total_customers": total_customers,
            "active_subscriptions": active_subscriptions
        },
        "recent_orders": recent_orders_formatted,
        "top_products": top_products_formatted
    }


@api_router.get("/admin/orders")
async def get_admin_orders(
    admin: dict = Depends(get_admin_user),
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 20
):
    """Get all orders with filtering and pagination"""
    query = {}
    if status:
        query["status"] = status
    
    total = await db.orders.count_documents(query)
    skip = (page - 1) * limit
    
    orders = await db.orders.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    
    orders_formatted = []
    for order in orders:
        # Get customer info if registered user
        customer_name = "Guest"
        customer_email = order.get("guest_email", "")
        
        if order.get("user_id"):
            user = await db.users.find_one({"_id": order["user_id"]})
            if user:
                customer_name = f"{user.get('first_name', '')} {user.get('last_name', '')}"
                customer_email = user.get("email", "")
        
        orders_formatted.append({
            "id": order["_id"],
            "order_number": order.get("order_number", "N/A"),
            "customer_name": customer_name,
            "customer_email": customer_email,
            "items_count": len(order.get("items", [])),
            "subtotal": order.get("subtotal", 0),
            "discount": order.get("discount", 0),
            "shipping_cost": order.get("shipping_cost", 0),
            "total": order.get("total", 0),
            "status": order.get("status", "unknown"),
            "payment_status": order.get("payment_status", "unknown"),
            "payment_method": order.get("payment_method", "unknown"),
            "shipping_address": order.get("shipping", {}).get("address", {}) if isinstance(order.get("shipping"), dict) else {},
            "created_at": order.get("created_at", ""),
            "updated_at": order.get("updated_at", "")
        })
    
    return {
        "orders": orders_formatted,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit
    }


@api_router.get("/admin/reconciliation/payments")
async def get_payment_reconciliation_report(
    admin: dict = Depends(get_admin_user),
    page: int = 1,
    limit: int = 50,
):
    skip = max(page - 1, 0) * limit
    total = await db.payment_attempts.count_documents({})
    attempts = await db.payment_attempts.find({}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)

    rows = []
    for attempt in attempts:
        order = await db.orders.find_one({"_id": attempt.get("order_id")}, {"_id": 1, "order_number": 1, "total": 1, "payment_status": 1})
        webhook = await db.webhook_events.find_one(
            {
                "provider": attempt.get("provider"),
                "order_id": attempt.get("order_id"),
            },
            sort=[("received_at", -1)],
        )

        reported_total = None
        if webhook and webhook.get("provider") == "payfast":
            try:
                reported_total = round(float((webhook.get("payload") or {}).get("amount_gross", 0)), 2)
            except (TypeError, ValueError):
                reported_total = None

        expected_total = round(float((order or {}).get("total") or attempt.get("expected_total") or 0), 2)
        reconciliation_status = "matched"
        failure_reason = None

        if reported_total is not None and abs(reported_total - expected_total) > 0.05:
            reconciliation_status = "amount_mismatch"
            failure_reason = f"expected {expected_total:.2f}, got {reported_total:.2f}"
        elif attempt.get("status") in {
            PaymentAttemptStatus.FAILED.value,
            PaymentAttemptStatus.INVALID_NOTIFICATION.value,
            PaymentAttemptStatus.CANCELLED.value,
        }:
            reconciliation_status = "failed"
            failure_reason = attempt.get("status")

        rows.append(
            {
                "order_number": (order or {}).get("order_number") or attempt.get("order_number"),
                "order_id": attempt.get("order_id"),
                "payment_attempt_id": attempt.get("_id"),
                "provider": attempt.get("provider"),
                "provider_reference": attempt.get("provider_reference"),
                "expected_total": expected_total,
                "reported_total": reported_total,
                "payment_status": (order or {}).get("payment_status"),
                "attempt_status": attempt.get("status"),
                "notification_received_at": (webhook or {}).get("received_at"),
                "reconciliation_status": reconciliation_status,
                "failure_reason": failure_reason,
            }
        )

    return {
        "rows": rows,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
    }


@api_router.get("/admin/orders/{order_id}")
async def get_admin_order_detail(order_id: str, admin: dict = Depends(get_admin_user)):
    """Get detailed order information"""
    order = await db.orders.find_one({"_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Get customer info
    customer_info = None
    if order.get("user_id"):
        user = await db.users.find_one({"_id": order["user_id"]}, {"password_hash": 0})
        if user:
            customer_info = {
                "id": user["_id"],
                "name": f"{user.get('first_name', '')} {user.get('last_name', '')}",
                "email": user.get("email", ""),
                "phone": user.get("phone", "")
            }
    
    return {
        "id": order["_id"],
        "order_number": order.get("order_number", "N/A"),
        "customer": customer_info,
        "guest_email": order.get("guest_email"),
        "items": order.get("items", []),
        "subtotal": order.get("subtotal", 0),
        "discount": order.get("discount", 0),
        "shipping_cost": order.get("shipping_cost", 0),
        "vat": order.get("vat", 0),
        "total": order.get("total", 0),
        "status": order.get("status", "unknown"),
        "payment_status": order.get("payment_status", "unknown"),
        "payment_method": order.get("payment_method", "unknown"),
        "payment_reference": order.get("payment_reference"),
        "shipping": order.get("shipping", {}),
        "billing": order.get("billing", {}),
        "coupon_code": order.get("coupon_code"),
        "tracking_number": order.get("tracking_number"),
        "notes": order.get("notes"),
        "created_at": order.get("created_at", ""),
        "updated_at": order.get("updated_at", "")
    }


class OrderStatusUpdate(BaseModel):
    status: str
    tracking_number: Optional[str] = None
    notes: Optional[str] = None

@api_router.put("/admin/orders/{order_id}/status")
async def update_order_status(
    order_id: str, 
    update: OrderStatusUpdate,
    background_tasks: BackgroundTasks,
    admin: dict = Depends(get_admin_user)
):
    """Update order status"""
    order = await db.orders.find_one({"_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    update_data = {
        "status": update.status,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    if update.tracking_number:
        update_data["tracking_number"] = update.tracking_number
    if update.notes:
        update_data["notes"] = update.notes
    
    await db.orders.update_one({"_id": order_id}, {"$set": update_data})
    
    # Send notification email if shipped
    if update.status == "shipped" and update.tracking_number:
        email = order.get("guest_email") or ""
        if order.get("user_id"):
            user = await db.users.find_one({"_id": order["user_id"]})
            if user:
                email = user.get("email", "")
        if email:
            background_tasks.add_task(send_shipping_notification, order, update.tracking_number)
            background_tasks.add_task(
                resend_events.emit_lifecycle_event,
                resend_events.EventName.order_shipped.value,
                {"email": email},
                {
                    "order_number": order["order_number"],
                    "tracking_number": update.tracking_number,
                },
                None,
                None,
                order.get("user_id"),
                None,
                None,
                "order",
                order_id
            )
    
    return {"message": "Order status updated", "status": update.status}


@api_router.get("/admin/orders/{order_id}/packing-slip")
async def get_order_packing_slip(order_id: str, admin: dict = Depends(get_admin_user)):
    """Generate printable packing slip text for fulfillment workflow."""
    order = await db.orders.find_one({"_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    shipping = order.get("shipping", {}) if isinstance(order.get("shipping"), dict) else {}
    address = shipping.get("address", {}) if isinstance(shipping.get("address"), dict) else {}
    items = order.get("items", [])

    lines = [
        "Cape Ember Coffee Co. - Packing Slip",
        f"Order Number: {order.get('order_number', order_id)}",
        f"Order ID: {order_id}",
        f"Created At: {order.get('created_at', '')}",
        "",
        "Ship To:",
        f"{address.get('first_name', '')} {address.get('last_name', '')}".strip(),
        address.get("street", ""),
        address.get("apartment", ""),
        f"{address.get('city', '')}, {address.get('province', '')} {address.get('postal_code', '')}".strip(),
        address.get("country", "South Africa"),
        f"Phone: {address.get('phone', '')}",
        "",
        "Items:"
    ]

    for idx, item in enumerate(items, start=1):
        lines.append(
            f"{idx}. {item.get('product_name', 'Product')} | Variant: {item.get('variant_name', '')} | Qty: {item.get('quantity', 0)}"
        )

    lines.extend([
        "",
        f"Subtotal: R{order.get('subtotal', 0):.2f}",
        f"Discount: R{order.get('discount', 0):.2f}",
        f"Shipping: R{order.get('shipping_cost', 0):.2f}",
        f"VAT: R{order.get('vat', 0):.2f}",
        f"Total: R{order.get('total', 0):.2f}",
        "",
        "South African landscapes in every cup"
    ])

    return PlainTextResponse("\n".join(lines), media_type="text/plain")


@api_router.post("/admin/orders/{order_id}/resend-confirmation")
async def resend_order_confirmation(order_id: str, background_tasks: BackgroundTasks, admin: dict = Depends(get_admin_user)):
    """Resend order confirmation email to customer/guest."""
    order = await db.orders.find_one({"_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    email = order.get("guest_email", "")
    if order.get("user_id"):
        user = await db.users.find_one({"_id": order["user_id"]})
        if user:
            email = user.get("email", email)

    if not email:
        raise HTTPException(status_code=400, detail="No customer email found for this order")

    background_tasks.add_task(send_order_confirmation, order, email)
    return {"message": "Order confirmation resent", "email": email}


@api_router.get("/admin/customers")
async def get_admin_customers(
    admin: dict = Depends(get_admin_user),
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 20
):
    """Get all customers with search and pagination"""
    query = {}
    if search:
        query["$or"] = [
            {"email": {"$regex": search, "$options": "i"}},
            {"first_name": {"$regex": search, "$options": "i"}},
            {"last_name": {"$regex": search, "$options": "i"}}
        ]
    
    total = await db.users.count_documents(query)
    skip = (page - 1) * limit
    
    users = await db.users.find(query, {"password_hash": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    
    customers = []
    for user in users:
        # Get order count and total spent
        order_stats = await db.orders.aggregate([
            {"$match": {"user_id": user["_id"], "payment_status": "complete"}},
            {"$group": {"_id": None, "count": {"$sum": 1}, "total": {"$sum": "$total"}}}
        ]).to_list(1)
        
        stats = order_stats[0] if order_stats else {"count": 0, "total": 0}
        
        customers.append({
            "id": user["_id"],
            "email": user.get("email", ""),
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
            "phone": user.get("phone", ""),
            "address_count": len(user.get("addresses", [])),
            "notes": user.get("notes", ""),
            "tags": user.get("tags", []),
            "orders_count": stats.get("count", 0),
            "total_spent": round(stats.get("total", 0), 2),
            "is_admin": user.get("is_admin", False),
            "created_at": user.get("created_at", "")
        })
    
    return {
        "customers": customers,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit
    }


@api_router.get("/admin/customers/{customer_id}")
async def get_admin_customer_detail(customer_id: str, admin: dict = Depends(get_admin_user)):
    """Get full customer profile including order history, addresses, tags, and notes."""
    user = await db.users.find_one({"_id": customer_id}, {"password_hash": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Customer not found")

    orders = await db.orders.find({"user_id": customer_id}).sort("created_at", -1).to_list(None)
    order_history = []
    total_spent = 0.0
    paid_orders = 0

    for order in orders:
        paid = order.get("payment_status") == PaymentStatus.COMPLETE
        if paid:
            total_spent += float(order.get("total", 0) or 0)
            paid_orders += 1
        order_history.append({
            "id": order.get("_id"),
            "order_number": order.get("order_number", "N/A"),
            "status": order.get("status", "unknown"),
            "payment_status": order.get("payment_status", "unknown"),
            "subtotal": order.get("subtotal", 0),
            "shipping_cost": order.get("shipping_cost", 0),
            "vat": order.get("vat", 0),
            "total": order.get("total", 0),
            "items_count": len(order.get("items", [])),
            "created_at": order.get("created_at", "")
        })

    return {
        "customer": {
            "id": user.get("_id"),
            "email": user.get("email", ""),
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
            "phone": user.get("phone", ""),
            "addresses": user.get("addresses", []),
            "notes": user.get("notes", ""),
            "tags": user.get("tags", []),
            "accepts_marketing": user.get("accepts_marketing", False),
            "created_at": user.get("created_at", ""),
            "updated_at": user.get("updated_at", "")
        },
        "summary": {
            "orders_count": paid_orders,
            "total_spent": round(total_spent, 2),
            "address_count": len(user.get("addresses", []))
        },
        "order_history": order_history
    }


@api_router.put("/admin/customers/{customer_id}")
async def update_admin_customer(
    customer_id: str,
    payload: "AdminCustomerUpdate",
    admin: dict = Depends(get_admin_user)
):
    """Update admin-managed customer fields such as phone, notes, and tags."""
    update_data = {k: v for k, v in payload.dict().items() if v is not None}
    if "tags" in update_data:
        update_data["tags"] = [str(tag).strip() for tag in update_data["tags"] if str(tag).strip()]
    if not update_data:
        raise HTTPException(status_code=400, detail="No changes supplied")

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.users.update_one({"_id": customer_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {"message": "Customer updated", "id": customer_id}


@api_router.get("/admin/inventory")
async def get_admin_inventory(admin: dict = Depends(get_admin_user)):
    """Get inventory status for all products"""
    inventory = []
    
    for product in PRODUCTS:
        for variant in product.get("variants", []):
            stock = variant.get("stock_quantity", 0)
            inventory.append({
                "product_id": product["id"],
                "product_name": product["name"],
                "variant_id": variant["id"],
                "variant_name": variant["name"],
                "sku": variant.get("sku", ""),
                "price": variant["price"],
                "stock_quantity": stock,
                "stock_status": "out_of_stock" if stock == 0 else "low_stock" if stock < 10 else "in_stock"
            })
    
    # Sort by stock quantity (lowest first)
    inventory.sort(key=lambda x: x["stock_quantity"])

    low_stock_alerts = [
        i for i in inventory
        if i["stock_status"] in ["low_stock", "out_of_stock"]
    ]

    recent_adjustments = await db.inventory_adjustments.find({}).sort("created_at", -1).limit(20).to_list(20)
    
    return {
        "inventory": inventory,
        "summary": {
            "total_products": len(PRODUCTS),
            "total_variants": len(inventory),
            "out_of_stock": sum(1 for i in inventory if i["stock_status"] == "out_of_stock"),
            "low_stock": sum(1 for i in inventory if i["stock_status"] == "low_stock"),
            "in_stock": sum(1 for i in inventory if i["stock_status"] == "in_stock")
        },
        "alerts": low_stock_alerts,
        "recent_adjustments": [{
            "id": entry.get("_id"),
            "product_id": entry.get("product_id"),
            "variant_id": entry.get("variant_id"),
            "old_stock": entry.get("old_stock"),
            "new_stock": entry.get("new_stock"),
            "delta": entry.get("delta"),
            "reason": entry.get("reason", "manual_adjustment"),
            "admin_email": entry.get("admin_email"),
            "created_at": entry.get("created_at")
        } for entry in recent_adjustments]
    }


class InventoryUpdate(BaseModel):
    stock_quantity: int
    reason: Optional[str] = None


class InventoryAdjustmentCreate(BaseModel):
    delta: int
    reason: str = "manual_adjustment"


class AdminCustomerUpdate(BaseModel):
    phone: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class AdminProductUpsert(BaseModel):
    name: str
    slug: str
    description: str
    short_description: Optional[str] = None
    category: str = "coffee_beans"
    roast_level: Optional[str] = None
    origin: Optional[str] = None
    flavor_notes: str = ""
    weight: str = "250g"
    grind_options: List[str] = ["Whole Bean", "Ground"]
    price: float
    sale_price: Optional[float] = None
    stock_quantity: int = 0
    low_stock_alert: int = 10
    image_url: Optional[str] = None
    gallery_images: List[str] = []
    is_active: bool = True
    is_featured: bool = False
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None


class DeliveryCreate(BaseModel):
    order_id: str
    delivery_date: str
    delivery_method: str  # local_delivery, pickup, nationwide_courier
    courier: Optional[str] = None
    tracking_number: Optional[str] = None
    status: str = "scheduled"
    notes: Optional[str] = None
    customer_name: str
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    address: Optional[dict] = None


class DeliveryUpdate(BaseModel):
    delivery_date: Optional[str] = None
    delivery_method: Optional[str] = None
    courier: Optional[str] = None
    tracking_number: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class AdminReviewUpdate(BaseModel):
    is_approved: Optional[bool] = None
    is_visible: Optional[bool] = None


class AdminReviewCreate(BaseModel):
    product_id: str
    user_name: str
    rating: int
    title: str
    content: str
    is_approved: bool = True
    is_visible: bool = True


class StoreSettingsUpdate(BaseModel):
    store_name: Optional[str] = None
    contact_email: Optional[str] = None
    whatsapp_number: Optional[str] = None
    shipping_fee: Optional[float] = None
    free_shipping_threshold: Optional[float] = None
    vat_rate: Optional[float] = None
    vat_inclusive_prices: Optional[bool] = None
    tax_registration_status: Optional[str] = None
    vat_number: Optional[str] = None
    sedgefield_local_delivery_enabled: Optional[bool] = None
    sedgefield_local_delivery_label: Optional[str] = None
    social_links: Optional[dict] = None
    seo_defaults: Optional[dict] = None


class ContentUpdate(BaseModel):
    hero_title: Optional[str] = None
    hero_subtitle: Optional[str] = None
    brand_story: Optional[str] = None
    shipping_policy: Optional[str] = None
    returns_policy: Optional[str] = None
    contact_details: Optional[dict] = None
    footer_links: Optional[dict] = None
    announcement_bar: Optional[str] = None

@api_router.put("/admin/inventory/{product_id}/{variant_id}")
async def update_inventory(
    product_id: str,
    variant_id: str,
    update: InventoryUpdate,
    admin: dict = Depends(get_admin_user)
):
    """Update stock quantity for a variant (NOTE: In production, this should update DB)"""
    # Find the product and variant
    product = PRODUCTS_MAP.get(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    variant = next((v for v in product["variants"] if v["id"] == variant_id), None)
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")
    
    previous_stock = int(variant.get("stock_quantity", 0))
    variant["stock_quantity"] = update.stock_quantity

    await db.inventory_adjustments.insert_one({
        "_id": str(uuid.uuid4()),
        "product_id": product_id,
        "variant_id": variant_id,
        "old_stock": previous_stock,
        "new_stock": int(update.stock_quantity),
        "delta": int(update.stock_quantity) - previous_stock,
        "reason": update.reason or "set_stock",
        "admin_user_id": admin.get("_id"),
        "admin_email": admin.get("email"),
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    return {
        "message": "Inventory updated",
        "product_id": product_id,
        "variant_id": variant_id,
        "new_stock": update.stock_quantity
    }


@api_router.post("/admin/inventory/{product_id}/{variant_id}/adjust")
async def adjust_inventory(
    product_id: str,
    variant_id: str,
    payload: InventoryAdjustmentCreate,
    admin: dict = Depends(get_admin_user)
):
    """Adjust stock by delta and record an auditable adjustment entry."""
    product = PRODUCTS_MAP.get(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    variant = next((v for v in product["variants"] if v["id"] == variant_id), None)
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")

    previous_stock = int(variant.get("stock_quantity", 0))
    new_stock = max(0, previous_stock + int(payload.delta))
    variant["stock_quantity"] = new_stock

    await db.inventory_adjustments.insert_one({
        "_id": str(uuid.uuid4()),
        "product_id": product_id,
        "variant_id": variant_id,
        "old_stock": previous_stock,
        "new_stock": new_stock,
        "delta": int(payload.delta),
        "reason": payload.reason,
        "admin_user_id": admin.get("_id"),
        "admin_email": admin.get("email"),
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    return {
        "message": "Inventory adjusted",
        "product_id": product_id,
        "variant_id": variant_id,
        "old_stock": previous_stock,
        "new_stock": new_stock,
        "applied_delta": int(payload.delta)
    }


@api_router.get("/admin/inventory/alerts")
async def get_inventory_alerts(admin: dict = Depends(get_admin_user)):
    """Low-stock and out-of-stock alerts based on per-product thresholds."""
    alerts = []
    for product in PRODUCTS:
        threshold = int(product.get("low_stock_alert", 10))
        for variant in product.get("variants", []):
            stock = int(variant.get("stock_quantity", 0))
            if stock <= threshold:
                severity = "critical" if stock == 0 else "warning"
                alerts.append({
                    "product_id": product.get("id"),
                    "product_name": product.get("name"),
                    "variant_id": variant.get("id"),
                    "variant_name": variant.get("name"),
                    "sku": variant.get("sku", ""),
                    "stock_quantity": stock,
                    "threshold": threshold,
                    "severity": severity
                })

    alerts.sort(key=lambda row: (0 if row["severity"] == "critical" else 1, row["stock_quantity"]))
    return {
        "alerts": alerts,
        "critical": sum(1 for a in alerts if a["severity"] == "critical"),
        "warning": sum(1 for a in alerts if a["severity"] == "warning")
    }


@api_router.get("/admin/inventory/export")
async def export_inventory_csv(admin: dict = Depends(get_admin_user)):
    """Export inventory as CSV."""
    lines = ["product_id,product_name,variant_id,variant_name,sku,price,stock_quantity,stock_status"]
    for product in PRODUCTS:
        for variant in product.get("variants", []):
            stock = variant.get("stock_quantity", 0)
            status = "out_of_stock" if stock == 0 else "low_stock" if stock < 10 else "in_stock"
            lines.append(
                f"{product['id']},{product['name']},{variant.get('id','')},{variant.get('name','')},{variant.get('sku','')},{variant.get('price',0)},{stock},{status}"
            )
    return PlainTextResponse("\n".join(lines), media_type="text/csv")


@api_router.get("/admin/customers/export")
async def export_customers_csv(admin: dict = Depends(get_admin_user)):
    """Export customers as CSV."""
    users = await db.users.find({}, {"password_hash": 0}).to_list(None)
    lines = ["id,email,first_name,last_name,phone,address_count,tags,notes,orders_count,total_spent,accepts_marketing,created_at"]
    for user in users:
        order_stats = await db.orders.aggregate([
            {"$match": {"user_id": user.get("_id"), "payment_status": "complete"}},
            {"$group": {"_id": None, "count": {"$sum": 1}, "total": {"$sum": "$total"}}}
        ]).to_list(1)
        stats = order_stats[0] if order_stats else {"count": 0, "total": 0}
        notes_clean = (user.get("notes", "") or "").replace(",", " ").replace("\n", " ").strip()
        tags_csv = "|".join([str(tag).strip() for tag in user.get("tags", []) if str(tag).strip()])
        lines.append(
            f"{user.get('_id','')},{user.get('email','')},{user.get('first_name','')},{user.get('last_name','')},{user.get('phone','')},{len(user.get('addresses', []))},{tags_csv},{notes_clean},{stats.get('count', 0)},{round(stats.get('total', 0), 2)},{user.get('accepts_marketing',False)},{user.get('created_at','')}"
        )
    return PlainTextResponse("\n".join(lines), media_type="text/csv")


@api_router.get("/admin/products")
async def get_admin_products(admin: dict = Depends(get_admin_user)):
    """Get products for admin management."""
    products = []
    for p in PRODUCTS:
        first_variant = p.get("variants", [{}])[0]
        stock_quantity = sum(v.get("stock_quantity", 0) for v in p.get("variants", []))
        products.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "slug": p.get("slug"),
            "description": p.get("description"),
            "short_description": p.get("short_description"),
            "category": p.get("category"),
            "roast_level": p.get("roast_level"),
            "origin": p.get("origin"),
            "flavor_notes": p.get("flavor_notes", ""),
            "weight": first_variant.get("weight", "250g"),
            "grind_options": [v.get("grind", "Whole Bean") for v in p.get("variants", [])],
            "price": first_variant.get("price", 0),
            "sale_price": first_variant.get("compare_at_price"),
            "stock_quantity": stock_quantity,
            "low_stock_alert": p.get("low_stock_alert", 10),
            "image_url": p.get("images", [{}])[0].get("url", "") if p.get("images") else "",
            "gallery_images": [img.get("url") for img in p.get("images", [])],
            "is_active": p.get("is_active", True),
            "is_featured": p.get("is_featured", False),
            "meta_title": p.get("meta_title"),
            "meta_description": p.get("meta_description")
        })
    return {"products": products}


@api_router.post("/admin/products")
async def create_admin_product(product: AdminProductUpsert, admin: dict = Depends(require_admin_roles(["owner", "staff"]))):
    """Create product (in-memory for this deployment target)."""
    product_id = product.slug
    if product_id in PRODUCTS_MAP:
        raise HTTPException(status_code=400, detail="Product slug already exists")

    now = datetime.now(timezone.utc).isoformat()
    variants = []
    for grind in product.grind_options:
        grind_slug = grind.lower().replace(" ", "_")
        variants.append({
            "id": f"{product_id}_{grind_slug}",
            "name": f"{product.weight} - {grind}",
            "sku": f"CE-{product_id.upper()}-{grind_slug.upper()}",
            "price": product.price,
            "compare_at_price": product.sale_price,
            "grind": grind,
            "weight": product.weight,
            "stock_quantity": max(0, int(product.stock_quantity / max(1, len(product.grind_options))))
        })

    new_product = {
        "id": product_id,
        "name": product.name,
        "slug": product.slug,
        "description": product.description,
        "short_description": product.short_description,
        "category": product.category,
        "roast_level": product.roast_level,
        "origin": product.origin,
        "strength": 3,
        "flavor_notes": product.flavor_notes,
        "images": [{"url": url, "alt": product.name, "is_primary": idx == 0, "sort_order": idx} for idx, url in enumerate(product.gallery_images or ([product.image_url] if product.image_url else []))],
        "variants": variants,
        "is_active": product.is_active,
        "is_featured": product.is_featured,
        "meta_title": product.meta_title,
        "meta_description": product.meta_description,
        "low_stock_alert": product.low_stock_alert,
        "created_at": now,
        "updated_at": now
    }

    PRODUCTS.append(new_product)
    PRODUCTS_MAP[new_product["id"]] = new_product
    return {"message": "Product created", "product_id": product_id}


@api_router.put("/admin/products/{product_id}")
async def update_admin_product(product_id: str, product: AdminProductUpsert, admin: dict = Depends(require_admin_roles(["owner", "staff"]))):
    """Update product details."""
    existing = PRODUCTS_MAP.get(product_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Product not found")

    existing["name"] = product.name
    existing["slug"] = product.slug
    existing["description"] = product.description
    existing["short_description"] = product.short_description
    existing["category"] = product.category
    existing["roast_level"] = product.roast_level
    existing["origin"] = product.origin
    existing["flavor_notes"] = product.flavor_notes
    existing["is_active"] = product.is_active
    existing["is_featured"] = product.is_featured
    existing["meta_title"] = product.meta_title
    existing["meta_description"] = product.meta_description
    existing["low_stock_alert"] = product.low_stock_alert
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()

    if existing.get("variants"):
        price_per_variant_stock = max(0, int(product.stock_quantity / max(1, len(existing["variants"]))))
        for v in existing["variants"]:
            v["price"] = product.price
            v["compare_at_price"] = product.sale_price
            v["stock_quantity"] = price_per_variant_stock
            v["weight"] = product.weight

    if product.gallery_images or product.image_url:
        image_urls = product.gallery_images or ([product.image_url] if product.image_url else [])
        existing["images"] = [
            {"url": url, "alt": product.name, "is_primary": idx == 0, "sort_order": idx}
            for idx, url in enumerate(image_urls)
        ]

    return {"message": "Product updated", "product_id": product_id}


@api_router.delete("/admin/products/{product_id}")
async def archive_admin_product(product_id: str, admin: dict = Depends(require_admin_roles(["owner"]))):
    """Archive product (soft delete)."""
    existing = PRODUCTS_MAP.get(product_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Product not found")
    existing["is_active"] = False
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    return {"message": "Product archived", "product_id": product_id}


@api_router.get("/admin/deliveries")
async def get_admin_deliveries(
    admin: dict = Depends(get_admin_user),
    status: Optional[str] = None,
    date: Optional[str] = None
):
    """Get delivery schedule list."""
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    if date:
        query["delivery_date"] = date

    deliveries = await db.deliveries.find(query).sort("delivery_date", 1).to_list(None)
    return {"deliveries": deliveries}


@api_router.post("/admin/deliveries")
async def create_admin_delivery(delivery: DeliveryCreate, admin: dict = Depends(get_admin_user)):
    """Schedule delivery record."""
    delivery_doc = delivery.dict()
    delivery_doc["_id"] = str(uuid.uuid4())
    delivery_doc["created_at"] = datetime.now(timezone.utc).isoformat()
    delivery_doc["updated_at"] = delivery_doc["created_at"]
    await db.deliveries.insert_one(delivery_doc)
    return {"message": "Delivery scheduled", "id": delivery_doc["_id"]}


@api_router.put("/admin/deliveries/{delivery_id}")
async def update_admin_delivery(delivery_id: str, update: DeliveryUpdate, admin: dict = Depends(get_admin_user)):
    """Update delivery status/details."""
    payload = {k: v for k, v in update.dict().items() if v is not None}
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.deliveries.update_one({"_id": delivery_id}, {"$set": payload})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return {"message": "Delivery updated", "id": delivery_id}


@api_router.get("/admin/deliveries/export")
async def export_deliveries_csv(admin: dict = Depends(get_admin_user)):
    """Export deliveries as CSV."""
    deliveries = await db.deliveries.find().sort("delivery_date", 1).to_list(None)
    lines = ["id,order_id,delivery_date,delivery_method,courier,tracking_number,status,customer_name,customer_phone,customer_email"]
    for d in deliveries:
        lines.append(
            f"{d.get('_id','')},{d.get('order_id','')},{d.get('delivery_date','')},{d.get('delivery_method','')},{d.get('courier','')},{d.get('tracking_number','')},{d.get('status','')},{d.get('customer_name','')},{d.get('customer_phone','')},{d.get('customer_email','')}"
        )
    return PlainTextResponse("\n".join(lines), media_type="text/csv")


@api_router.get("/admin/reviews")
async def get_admin_reviews(admin: dict = Depends(get_admin_user), status: Optional[str] = None):
    """Review moderation list."""
    query: Dict[str, Any] = {}
    if status == "approved":
        query["is_approved"] = True
    elif status == "pending":
        query["is_approved"] = False

    reviews = await db.reviews.find(query).sort("created_at", -1).to_list(None)
    return {
        "reviews": [{
            "id": str(r.get("_id")),
            "product_id": r.get("product_id"),
            "user_name": r.get("user_name"),
            "rating": r.get("rating"),
            "title": r.get("title"),
            "content": r.get("content"),
            "is_approved": r.get("is_approved", False),
            "is_visible": r.get("is_visible", True),
            "created_at": r.get("created_at")
        } for r in reviews]
    }


@api_router.post("/admin/reviews")
async def create_admin_review(review: AdminReviewCreate, admin: dict = Depends(get_admin_user)):
    """Create review manually from admin."""
    if review.product_id not in PRODUCTS_MAP:
        raise HTTPException(status_code=404, detail="Product not found")

    review_doc = {
        "_id": str(uuid.uuid4()),
        "product_id": review.product_id,
        "user_id": "admin_manual",
        "user_name": review.user_name,
        "rating": review.rating,
        "title": review.title,
        "content": review.content,
        "is_verified_purchase": False,
        "is_approved": review.is_approved,
        "is_visible": review.is_visible,
        "helpful_votes": 0,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.reviews.insert_one(review_doc)
    return {"message": "Review added", "id": review_doc["_id"]}


@api_router.put("/admin/reviews/{review_id}")
async def update_admin_review(review_id: str, update: AdminReviewUpdate, admin: dict = Depends(get_admin_user)):
    """Approve/reject/show/hide review."""
    payload = {k: v for k, v in update.dict().items() if v is not None}
    query: Dict[str, Any] = {"_id": review_id}
    if ObjectId.is_valid(review_id):
        query = {"$or": [{"_id": review_id}, {"_id": ObjectId(review_id)}]}

    result = await db.reviews.update_one(query, {"$set": payload})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Review not found")
    return {"message": "Review updated", "id": review_id}


@api_router.get("/reviews/public")
async def get_public_reviews(limit: int = 6):
    """Public approved+visible reviews for homepage/testimonials."""
    reviews = await db.reviews.find({"is_approved": True, "is_visible": {"$ne": False}}).sort("created_at", -1).limit(limit).to_list(limit)
    return {
        "reviews": [{
            "id": str(r.get("_id")),
            "product_id": r.get("product_id"),
            "user_name": r.get("user_name"),
            "rating": r.get("rating"),
            "title": r.get("title"),
            "content": r.get("content"),
            "is_verified_purchase": r.get("is_verified_purchase", False),
            "created_at": r.get("created_at")
        } for r in reviews]
    }


@api_router.get("/admin/reports")
async def get_admin_reports(
    admin: dict = Depends(get_admin_user),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None
):
    """Aggregate sales, products, and stock report data."""
    order_query: Dict[str, Any] = {"payment_status": PaymentStatus.COMPLETE}
    if date_from or date_to:
        order_query["created_at"] = {}
        if date_from:
            order_query["created_at"]["$gte"] = date_from
        if date_to:
            order_query["created_at"]["$lte"] = date_to

    orders = await db.orders.find(order_query).to_list(None)
    total_sales = round(sum(o.get("total", 0) for o in orders), 2)
    total_orders = len(orders)

    product_sales: Dict[str, Dict[str, Any]] = {}
    for order in orders:
        for item in order.get("items", []):
            pid = item.get("product_id")
            if not pid:
                continue
            if pid not in product_sales:
                product_sales[pid] = {
                    "product_id": pid,
                    "product_name": item.get("product_name", pid),
                    "units_sold": 0,
                    "revenue": 0.0
                }
            qty = item.get("quantity", 0)
            product_sales[pid]["units_sold"] += qty
            product_sales[pid]["revenue"] += item.get("total", item.get("price", 0) * qty)

    low_stock = []
    for p in PRODUCTS:
        threshold = p.get("low_stock_alert", 10)
        stock = sum(v.get("stock_quantity", 0) for v in p.get("variants", []))
        if stock <= threshold:
            low_stock.append({"product_id": p["id"], "product_name": p["name"], "stock": stock, "threshold": threshold})

    return {
        "sales": {
            "total_sales": total_sales,
            "total_orders": total_orders,
            "average_order_value": round(total_sales / total_orders, 2) if total_orders else 0
        },
        "sales_by_product": sorted(product_sales.values(), key=lambda x: x["revenue"], reverse=True),
        "low_stock": low_stock,
        "customers_total": await db.users.count_documents({})
    }


@api_router.get("/admin/traffic")
async def get_admin_traffic_insights(
    admin: dict = Depends(get_admin_user),
    range_days: int = 30
):
    """Aggregate first-party website traffic analytics for admin insights."""
    def classify_channel(source: str, medium: str, referrer: str) -> str:
        src = (source or "").lower()
        med = (medium or "").lower()
        ref = (referrer or "").lower()

        if med in ["paid_social", "social_paid", "cpc_social"]:
            return "Paid Social"
        if med in ["social", "organic_social"]:
            return "Organic Social"
        if med in ["cpc", "ppc", "paid_search", "sem"]:
            return "Paid Search"
        if med in ["email", "newsletter", "edm"]:
            return "Email"
        if med in ["affiliate", "affiliates"]:
            return "Affiliate"
        if med in ["display", "banner", "programmatic"]:
            return "Display"
        if med in ["sms", "whatsapp", "messaging"]:
            return "Messaging"
        if med == "referral":
            return "Referral"
        if med == "organic":
            return "Organic Search"

        if src in ["google", "bing", "yahoo", "duckduckgo"] or any(s in ref for s in ["google.", "bing.", "yahoo.", "duckduckgo."]):
            return "Organic Search"
        if src in ["facebook", "instagram", "meta", "tiktok", "x", "twitter", "linkedin", "youtube"]:
            return "Organic Social"
        if src in ["direct", "(direct)", ""] and (ref in ["", "direct"]):
            return "Direct"
        if ref not in ["", "direct"]:
            return "Referral"
        return "Other"

    range_days = max(1, min(range_days, 90))
    now = datetime.now(timezone.utc)
    start_dt = (now - timedelta(days=range_days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_iso = start_dt.isoformat()

    events = await db.analytics_events.find({"created_at": {"$gte": start_iso}}).to_list(None)

    day_map: Dict[str, Dict[str, Any]] = {}
    page_counter: Dict[str, int] = {}
    referrer_counter: Dict[str, int] = {}
    campaign_counter: Dict[str, int] = {}
    campaign_channel_map: Dict[str, str] = {}
    source_counter: Dict[str, int] = {}
    channel_counter: Dict[str, int] = {}
    event_counter: Dict[str, int] = {}
    unique_visitors = set()
    unique_sessions = set()

    for event in events:
        created_at = str(event.get("created_at", ""))
        day_key = created_at[:10] if len(created_at) >= 10 else now.strftime("%Y-%m-%d")
        bucket = day_map.setdefault(day_key, {
            "date": day_key,
            "page_views": 0,
            "unique_visitors": set(),
            "sessions": set(),
            "add_to_cart": 0,
            "begin_checkout": 0,
            "purchase": 0
        })

        event_name = str(event.get("event_name", "unknown"))
        event_counter[event_name] = event_counter.get(event_name, 0) + 1

        anon_id = event.get("anonymous_id") or ""
        session_id = event.get("session_id") or ""
        if anon_id:
            bucket["unique_visitors"].add(anon_id)
            unique_visitors.add(anon_id)
        if session_id:
            bucket["sessions"].add(session_id)
            unique_sessions.add(session_id)

        if event_name == "page_view":
            bucket["page_views"] += 1
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            page_path = event.get("page_path") or params.get("path") or "/"
            page_counter[page_path] = page_counter.get(page_path, 0) + 1

            raw_referrer = event.get("referrer") or params.get("referrer") or ""
            if raw_referrer:
                parsed = urllib.parse.urlparse(raw_referrer)
                normalized_referrer = parsed.netloc or raw_referrer
            else:
                normalized_referrer = "direct"
            referrer_counter[normalized_referrer] = referrer_counter.get(normalized_referrer, 0) + 1

            utm_source = (params.get("utm_source") or "").strip()
            utm_medium = (params.get("utm_medium") or "").strip()
            utm_campaign = (params.get("utm_campaign") or "").strip()

            source = utm_source or normalized_referrer or "direct"
            medium = utm_medium or ("organic" if normalized_referrer not in ["", "direct"] else "direct")
            campaign = utm_campaign or "(not set)"
            channel = classify_channel(source, medium, normalized_referrer)
            campaign_key = f"{source}|{medium}|{campaign}"

            campaign_counter[campaign_key] = campaign_counter.get(campaign_key, 0) + 1
            if campaign_key not in campaign_channel_map:
                campaign_channel_map[campaign_key] = channel
            source_counter[source] = source_counter.get(source, 0) + 1
            channel_counter[channel] = channel_counter.get(channel, 0) + 1
        elif event_name == "add_to_cart":
            bucket["add_to_cart"] += 1
        elif event_name == "begin_checkout":
            bucket["begin_checkout"] += 1
        elif event_name == "purchase":
            bucket["purchase"] += 1

    daily = []
    for offset in range(range_days):
        day = (start_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
        source = day_map.get(day, {
            "date": day,
            "page_views": 0,
            "unique_visitors": set(),
            "sessions": set(),
            "add_to_cart": 0,
            "begin_checkout": 0,
            "purchase": 0
        })
        daily.append({
            "date": day,
            "page_views": source["page_views"],
            "unique_visitors": len(source["unique_visitors"]),
            "sessions": len(source["sessions"]),
            "add_to_cart": source["add_to_cart"],
            "begin_checkout": source["begin_checkout"],
            "purchase": source["purchase"]
        })

    total_page_views = sum(day["page_views"] for day in daily)
    total_add_to_cart = sum(day["add_to_cart"] for day in daily)
    total_begin_checkout = sum(day["begin_checkout"] for day in daily)
    total_purchase = sum(day["purchase"] for day in daily)

    top_pages = [
        {"path": path, "views": views}
        for path, views in sorted(page_counter.items(), key=lambda item: item[1], reverse=True)[:10]
    ]
    top_referrers = [
        {"referrer": referrer, "visits": visits}
        for referrer, visits in sorted(referrer_counter.items(), key=lambda item: item[1], reverse=True)[:10]
    ]
    top_sources = [
        {"source": source, "visits": visits}
        for source, visits in sorted(source_counter.items(), key=lambda item: item[1], reverse=True)[:10]
    ]
    top_channels = [
        {"channel": channel, "visits": visits}
        for channel, visits in sorted(channel_counter.items(), key=lambda item: item[1], reverse=True)[:10]
    ]
    top_campaigns = []
    for key, visits in sorted(campaign_counter.items(), key=lambda item: item[1], reverse=True)[:10]:
        source, medium, campaign = key.split("|", 2)
        top_campaigns.append({
            "source": source,
            "medium": medium,
            "campaign": campaign,
            "channel": campaign_channel_map.get(key, "Other"),
            "visits": visits
        })
    events_breakdown = [
        {"event_name": name, "count": count}
        for name, count in sorted(event_counter.items(), key=lambda item: item[1], reverse=True)
    ]

    # ---- Web Vitals aggregation ----
    vitals_lcp: List[float] = []
    vitals_fcp: List[float] = []
    vitals_cls: List[float] = []
    vitals_ttfb: List[float] = []

    for event in events:
        if event.get("event_name") != "web_vitals":
            continue
        p = event.get("params") if isinstance(event.get("params"), dict) else {}
        if isinstance(p.get("lcp_ms"), (int, float)) and p["lcp_ms"] > 0:
            vitals_lcp.append(float(p["lcp_ms"]))
        if isinstance(p.get("fcp_ms"), (int, float)) and p["fcp_ms"] > 0:
            vitals_fcp.append(float(p["fcp_ms"]))
        if isinstance(p.get("cls"), (int, float)) and p["cls"] >= 0:
            vitals_cls.append(float(p["cls"]))
        if isinstance(p.get("ttfb_ms"), (int, float)) and p["ttfb_ms"] > 0:
            vitals_ttfb.append(float(p["ttfb_ms"]))

    def p75(lst: List[float]) -> float:
        if not lst:
            return 0.0
        lst_sorted = sorted(lst)
        idx = int(len(lst_sorted) * 0.75)
        return round(lst_sorted[min(idx, len(lst_sorted) - 1)], 1)

    def avg(lst: List[float]) -> float:
        return round(sum(lst) / len(lst), 1) if lst else 0.0

    def score_lcp(ms: float) -> str:
        if ms == 0:
            return "no data"
        return "good" if ms <= 2500 else "needs-improvement" if ms <= 4000 else "poor"

    def score_fcp(ms: float) -> str:
        if ms == 0:
            return "no data"
        return "good" if ms <= 1800 else "needs-improvement" if ms <= 3000 else "poor"

    def score_cls(val: float) -> str:
        if val == 0 and not vitals_cls:
            return "no data"
        return "good" if val <= 0.1 else "needs-improvement" if val <= 0.25 else "poor"

    def score_ttfb(ms: float) -> str:
        if ms == 0:
            return "no data"
        return "good" if ms <= 800 else "needs-improvement" if ms <= 1800 else "poor"

    lcp_p75 = p75(vitals_lcp)
    fcp_p75 = p75(vitals_fcp)
    cls_avg = avg(vitals_cls)
    ttfb_p75 = p75(vitals_ttfb)

    web_vitals = {
        "sample_count": len(vitals_lcp),
        "lcp_ms_p75": lcp_p75,
        "lcp_rating": score_lcp(lcp_p75),
        "fcp_ms_p75": fcp_p75,
        "fcp_rating": score_fcp(fcp_p75),
        "cls_avg": round(cls_avg, 4),
        "cls_rating": score_cls(cls_avg),
        "ttfb_ms_p75": ttfb_p75,
        "ttfb_rating": score_ttfb(ttfb_p75)
    }

    # ---- Funnel conversion rates ----
    add_to_cart_rate = round((total_add_to_cart / total_page_views) * 100, 2) if total_page_views else 0
    checkout_rate = round((total_begin_checkout / total_add_to_cart) * 100, 2) if total_add_to_cart else 0
    purchase_rate = round((total_purchase / total_begin_checkout) * 100, 2) if total_begin_checkout else 0

    return {
        "range_days": range_days,
        "overview": {
            "page_views": total_page_views,
            "unique_visitors": len(unique_visitors),
            "sessions": len(unique_sessions),
            "add_to_cart": total_add_to_cart,
            "begin_checkout": total_begin_checkout,
            "purchase": total_purchase,
            "purchase_conversion_rate": round((total_purchase / total_page_views) * 100, 2) if total_page_views else 0
        },
        "funnel": {
            "page_views": total_page_views,
            "add_to_cart": total_add_to_cart,
            "begin_checkout": total_begin_checkout,
            "purchase": total_purchase,
            "add_to_cart_rate": add_to_cart_rate,
            "checkout_rate": checkout_rate,
            "purchase_rate": purchase_rate
        },
        "web_vitals": web_vitals,
        "daily": daily,
        "top_pages": top_pages,
        "top_referrers": top_referrers,
        "top_sources": top_sources,
        "top_channels": top_channels,
        "top_campaigns": top_campaigns,
        "events": events_breakdown
    }


@api_router.get("/admin/settings")
async def get_admin_settings(admin: dict = Depends(get_admin_user)):
    """Get store settings."""
    default_settings = {
        "_id": "store",
        "store_name": "Cape Ember Coffee Co.",
        "contact_email": "hello@capeembercoffee.co.za",
        "whatsapp_number": "+27810261618",
        "shipping_fee": 75,
        "free_shipping_threshold": 399,
        "vat_rate": 0.15,
        "vat_inclusive_prices": True,
        "tax_registration_status": "registered",
        "vat_number": "",
        "sedgefield_local_delivery_enabled": True,
        "sedgefield_local_delivery_label": "Sedgefield",
        "social_links": {
            "instagram": "https://instagram.com/capeembercoffee",
            "facebook": "https://facebook.com/capeembercoffee"
        },
        "seo_defaults": {
            "title": "Cape Ember Coffee Co. | South African Landscapes in Every Cup",
            "description": "Premium coffee crafted with trusted roasting partners, inspired by South African landscapes."
        }
    }
    settings = await db.settings.find_one({"_id": "store"}) or default_settings
    # Backfill missing fields so partial updates never expose nulls in admin.
    settings = {**default_settings, **settings}
    settings["social_links"] = {**default_settings.get("social_links", {}), **(settings.get("social_links") or {})}
    settings["seo_defaults"] = {**default_settings.get("seo_defaults", {}), **(settings.get("seo_defaults") or {})}
    settings.pop("_id", None)
    settings["resend_configured"] = resend_is_configured()
    try:
        payfast_config = get_payfast_config()
        settings["payfast_configured"] = bool(
            payfast_config.get("enabled")
            and payfast_config.get("merchant_id_configured")
            and payfast_config.get("merchant_key_configured")
        )
    except PayFastConfigurationError:
        settings["payfast_configured"] = False
    settings["jwt_custom"] = bool(
        os.environ.get("JWT_SECRET") and
        os.environ.get("JWT_SECRET") != "cape-ember-secret-2024-south-africa"
    )
    return settings


@api_router.get("/settings/public")
async def get_public_settings():
    """Get public-safe store settings for storefront contact/social links."""
    default_public = {
        "store_name": "Cape Ember Coffee Co.",
        "contact_email": "hello@capeembercoffee.co.za",
        "whatsapp_number": "+27810261618",
        "social_links": {
            "instagram": "https://instagram.com/capeembercoffee",
            "facebook": "https://facebook.com/capeembercoffee"
        }
    }
    settings = await db.settings.find_one({"_id": "store"}) or default_public
    social_links = {**default_public.get("social_links", {}), **(settings.get("social_links") or {})}

    return {
        "store_name": settings.get("store_name") or default_public["store_name"],
        "contact_email": settings.get("contact_email") or default_public["contact_email"],
        "whatsapp_number": settings.get("whatsapp_number") or default_public["whatsapp_number"],
        "shipping_fee": settings.get("shipping_fee") if settings.get("shipping_fee") is not None else DEFAULT_SHIPPING_FEE,
        "free_shipping_threshold": settings.get("free_shipping_threshold") if settings.get("free_shipping_threshold") is not None else DEFAULT_FREE_SHIPPING_THRESHOLD,
        "vat_rate": settings.get("vat_rate") if settings.get("vat_rate") is not None else VAT_RATE,
        "vat_inclusive_prices": settings.get("vat_inclusive_prices") if settings.get("vat_inclusive_prices") is not None else True,
        "tax_registration_status": settings.get("tax_registration_status") or TAX_REGISTRATION_STATUS,
        "vat_number": settings.get("vat_number") or VAT_NUMBER,
        "sedgefield_local_delivery_enabled": settings.get("sedgefield_local_delivery_enabled") if settings.get("sedgefield_local_delivery_enabled") is not None else True,
        "sedgefield_local_delivery_label": settings.get("sedgefield_local_delivery_label") or "Sedgefield",
        "social_links": social_links
    }


@api_router.put("/admin/settings")
async def update_admin_settings(update: StoreSettingsUpdate, admin: dict = Depends(require_admin_roles(["owner"]))):
    """Update store settings."""
    payload = {k: v for k, v in update.dict().items() if v is not None}
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.settings.update_one({"_id": "store"}, {"$set": payload}, upsert=True)
    return {"message": "Settings updated"}


@api_router.get("/admin/content")
async def get_admin_content(admin: dict = Depends(get_admin_user)):
    """Get editable marketing/content blocks."""
    content = await db.content.find_one({"_id": "site_content"}) or {
        "_id": "site_content",
        "hero_title": "South African Landscapes in Every Cup",
        "hero_subtitle": "Premium coffee crafted with trusted roasting partners and inspired by the landscapes we love.",
        "brand_story": "Cape Ember Coffee Co. was created to bring the feeling of South Africa's landscapes into the everyday coffee ritual.",
        "shipping_policy": "Nationwide shipping available.",
        "returns_policy": "Returns accepted on damaged goods.",
        "contact_details": {
            "email": "hello@capeembercoffee.co.za",
            "whatsapp": "+27810261618"
        },
        "footer_links": {
            "shop": "/shop",
            "story": "/about"
        },
        "announcement_bar": "Complimentary nationwide delivery over R399"
    }
    content.pop("_id", None)
    return content


@api_router.put("/admin/content")
async def update_admin_content(update: ContentUpdate, admin: dict = Depends(require_admin_roles(["owner", "staff"]))):
    """Update editable content blocks."""
    payload = {k: v for k, v in update.dict().items() if v is not None}
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.content.update_one({"_id": "site_content"}, {"$set": payload}, upsert=True)
    return {"message": "Content updated"}


@api_router.get("/admin/coupons")
async def get_admin_coupons(admin: dict = Depends(get_admin_user)):
    """Get all coupons"""
    coupons = await db.coupons.find().to_list(100)
    
    coupons_formatted = []
    for coupon in coupons:
        coupons_formatted.append({
            "id": str(coupon.get("_id", "")),
            "code": coupon.get("code", ""),
            "description": coupon.get("description", ""),
            "discount_type": coupon.get("discount_type", ""),
            "discount_value": coupon.get("discount_value", 0),
            "minimum_order": coupon.get("minimum_order", 0),
            "is_active": coupon.get("is_active", False),
            "valid_from": coupon.get("valid_from", ""),
            "valid_until": coupon.get("valid_until", ""),
            "uses_count": coupon.get("uses_count", 0)
        })
    
    return {"coupons": coupons_formatted}


class CouponCreate(BaseModel):
    code: str
    description: Optional[str] = None
    discount_type: str  # percentage or fixed_amount
    discount_value: float
    minimum_order: float = 0
    valid_from: str
    valid_until: str
    is_active: bool = True

@api_router.post("/admin/coupons")
async def create_coupon(coupon: CouponCreate, admin: dict = Depends(require_admin_roles(["owner", "staff"]))):
    """Create a new coupon"""
    # Check if code already exists
    existing = await db.coupons.find_one({"code": coupon.code.upper()})
    if existing:
        raise HTTPException(status_code=400, detail="Coupon code already exists")
    
    coupon_doc = {
        "code": coupon.code.upper(),
        "description": coupon.description,
        "discount_type": coupon.discount_type,
        "discount_value": coupon.discount_value,
        "minimum_order": coupon.minimum_order,
        "valid_from": coupon.valid_from,
        "valid_until": coupon.valid_until,
        "is_active": coupon.is_active,
        "uses_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.coupons.insert_one(coupon_doc)
    
    return {"message": "Coupon created", "code": coupon.code.upper()}


@api_router.delete("/admin/coupons/{coupon_code}")
async def delete_coupon(coupon_code: str, admin: dict = Depends(require_admin_roles(["owner"]))):
    """Delete a coupon"""
    result = await db.coupons.delete_one({"code": coupon_code.upper()})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Coupon not found")
    
    return {"message": "Coupon deleted"}


# ============ STATIC IMAGES ROUTE ============

@api_router.get("/images/products/{product_id}")
async def get_product_image(product_id: str):
    """Serve generated lifestyle product background images"""
    backgrounds_dir = APP_DIR / "generated_backgrounds"
    image_path = backgrounds_dir / f"{product_id}_background.png"
    
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(
        path=str(image_path),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000"}
    )


# ============ HEALTH CHECK ============

@api_router.get("/")
async def root():
    return {"message": "Cape Ember Coffee API", "version": "2.0.0", "status": "healthy"}


@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@api_router.get("/admin/payments/payfast-diagnostics")
async def payfast_diagnostics(admin: dict = Depends(get_admin_user)):
    try:
        payfast_config = get_payfast_config()
        return {
            "enabled": bool(payfast_config.get("enabled")),
            "environment": payfast_config.get("environment"),
            "process_host": payfast_config.get("process_host"),
            "merchant_id_configured": bool(payfast_config.get("merchant_id_configured")),
            "merchant_key_configured": bool(payfast_config.get("merchant_key_configured")),
            "passphrase_configured": bool(payfast_config.get("passphrase_configured")),
        }
    except PayFastConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/health")
async def k8s_health_check():
    """Kubernetes liveness / readiness probe endpoint. Kept at root path (no /api prefix)
    because k8s probes are configured against GET /health directly."""
    return {"status": "healthy"}


# ============ COFFEE CONCIERGE (AI CHAT) ============

class ConciergeMessageIn(BaseModel):
    session_id: str
    message: str


CONCIERGE_SYSTEM_PROMPT = """You are the Cape Ember Coffee Concierge — a warm, knowledgeable South African coffee guide for Cape Ember Coffee Co.

Cape Ember Coffee Co. is a premium South African coffee brand that partners with experienced local roasters to create landscape-inspired coffees. We are NOT a roastery ourselves.

Our four signature blends:
1. Fynbos Roast — Medium roast inspired by the Cape Peninsula fynbos. Smooth, nutty, balanced. Notes of hazelnut, caramel, cocoa. R139 for 250g.
2. Garden Route Blend — Medium roast tribute to the Garden Route coast. Smooth with cocoa and gentle citrus. Notes of milk chocolate, orange zest, brown sugar. R139 for 250g.
3. Ember Reserve — Dark roast inspired by the Drakensberg mountains. Bold, rich dark chocolate, molasses, hint of smoke. R139 for 250g.
4. Karoo Horizon — Inspired by the vast Karoo plains. R139 for 250g.

Also available: Landscape Bundle (all four blends).

Shipping: Complimentary over R399. Sedgefield gets free local delivery. Standard R75. Nationwide via courier, 2-5 business days.
Subscribe & Save: 15% off with Ember Circle subscription (weekly, fortnightly, or monthly).
Welcome coupon: WELCOME10 (10% off first order, min R100).

Your job:
- Help customers pick the right blend based on taste preferences ("I like dark chocolate flavors", "I want something smooth", etc.)
- Answer brewing method questions (French Press, Pour Over, AeroPress, Espresso, Cold Brew) with our specific ratios/times
- Explain the South African landscape story behind each blend
- Answer shipping, subscription, coupon questions

Conversion moments (soft-mention WELCOME10 exactly once per session, only when it feels natural):
- When a first-time buyer signals they're ready to order — phrases like "I want to try", "I'll go with", "I'll buy", "which one should I get", "how do I order", "add to cart", "checkout", or when they've narrowed it to a specific blend after asking for a recommendation.
- Weave it in warmly at the end of your reply, e.g.: "If it's your first order, use **WELCOME10** at checkout for 10% off (min R100)."
- If they've already used or heard the code in this conversation, do NOT repeat it. Do not lead with the coupon — always answer their actual question first.
- Never pitch WELCOME10 for subscriptions (Ember Circle already includes 15% off) or if the total order clearly won't hit R100.

Tone: Warm, elegant, knowledgeable — like a boutique coffee shop host in Cape Town. Never pushy. Prices in ZAR (R). Keep replies concise (2-4 sentences) unless the customer asks for detail. Do not invent facts, roasting history, or claims. If you don't know something, say so and suggest they email hello@capeembercoffee.co.za."""


@api_router.post("/concierge/chat")
async def concierge_chat(payload: ConciergeMessageIn):
    """Send a user message to the Coffee Concierge and stream the reply back as SSE."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone
    from fastapi.responses import StreamingResponse

    emergent_key = os.environ.get("EMERGENT_LLM_KEY")
    if not emergent_key:
        raise HTTPException(status_code=500, detail="Coffee Concierge is not configured")

    user_text = (payload.message or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(user_text) > 1000:
        raise HTTPException(status_code=400, detail="Message too long (max 1000 chars)")

    # Load existing history for this session
    session_doc = await db.concierge_sessions.find_one({"_id": payload.session_id})
    history = session_doc.get("messages", []) if session_doc else []

    # Persist user message immediately
    now_iso = datetime.now(timezone.utc).isoformat()
    user_entry = {"role": "user", "content": user_text, "created_at": now_iso}
    await db.concierge_sessions.update_one(
        {"_id": payload.session_id},
        {"$push": {"messages": user_entry}, "$setOnInsert": {"created_at": now_iso}, "$set": {"updated_at": now_iso}},
        upsert=True,
    )

    chat = LlmChat(
        api_key=emergent_key,
        session_id=payload.session_id,
        system_message=CONCIERGE_SYSTEM_PROMPT,
    ).with_model("openai", "gpt-5.4-mini")

    # Replay prior history so the model has context (library maintains history per-instance)
    for msg in history:
        if msg.get("role") == "user":
            try:
                await chat.send_message(UserMessage(text=msg["content"]))
            except Exception:
                # If replay fails, continue with fresh context
                break

    async def event_generator():
        assistant_text_parts = []
        try:
            async for event in chat.stream_message(UserMessage(text=user_text)):
                if isinstance(event, TextDelta):
                    assistant_text_parts.append(event.content)
                    yield f"data: {json.dumps({'delta': event.content})}\n\n"
                elif isinstance(event, StreamDone):
                    break
            full_reply = "".join(assistant_text_parts).strip()
            if full_reply:
                await db.concierge_sessions.update_one(
                    {"_id": payload.session_id},
                    {"$push": {"messages": {"role": "assistant", "content": full_reply, "created_at": datetime.now(timezone.utc).isoformat()}},
                     "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}},
                )
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            logger.error(f"Concierge stream error: {e}")
            yield f"data: {json.dumps({'error': 'The concierge is briefly unavailable. Please try again in a moment.'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api_router.get("/concierge/history/{session_id}")
async def concierge_history(session_id: str):
    session_doc = await db.concierge_sessions.find_one({"_id": session_id})
    if not session_doc:
        return {"session_id": session_id, "messages": []}
    return {"session_id": session_id, "messages": session_doc.get("messages", [])}


# ============ INCLUDE ROUTERS ============

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Seed test coupon and admin user on startup"""
    try:
        payfast_config = get_payfast_config()
        logger.info(
            "PayFast startup config: enabled=%s environment=%s process_host=%s merchant_id_configured=%s merchant_key_configured=%s passphrase_configured=%s",
            payfast_config.get("enabled"),
            payfast_config.get("environment"),
            payfast_config.get("process_host"),
            payfast_config.get("merchant_id_configured"),
            payfast_config.get("merchant_key_configured"),
            payfast_config.get("passphrase_configured"),
        )
    except PayFastConfigurationError as exc:
        logger.error("PayFast startup config invalid: %s", exc)
        raise

    # Create a test coupon if it doesn't exist
    test_coupon = await db.coupons.find_one({"code": "WELCOME10"})
    if not test_coupon:
        await db.coupons.insert_one({
            "code": "WELCOME10",
            "discount_type": "percentage",
            "discount_value": 10,
            "minimum_order": 100,
            "is_active": True,
            "valid_from": "2024-01-01T00:00:00+00:00",
            "valid_until": "2027-12-31T23:59:59+00:00",
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        logger.info("Created test coupon: WELCOME10")
    else:
        # Update existing coupon to use ISO strings if needed
        await db.coupons.update_one(
            {"code": "WELCOME10"},
            {"$set": {
                "valid_from": "2024-01-01T00:00:00+00:00",
                "valid_until": "2027-12-31T23:59:59+00:00"
            }}
        )
    
    # Create admin user if it doesn't exist
    admin_email = "admin@capeember.co.za"
    admin_password = os.environ.get("ADMIN_SEED_PASSWORD", "CapeEmber2024!")
    admin_user = await db.users.find_one({"email": admin_email})
    if not admin_user:
        admin_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await db.users.insert_one({
            "_id": admin_id,
            "email": admin_email,
            "password_hash": hash_password(admin_password),
            "first_name": "Admin",
            "last_name": "User",
            "phone": "",
            "addresses": [],
            "accepts_marketing": False,
            "is_admin": True,
            "admin_role": "owner",
            "created_at": now,
            "updated_at": now
        })
        logger.info(f"Created admin user: {admin_email}")
    else:
        # Ensure existing admin has is_admin flag AND correct password
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {
                "is_admin": True,
                "admin_role": "owner",
            }}
        )
        logger.info(f"Updated admin user password: {admin_email}")

    # Indexes for fast traffic analytics queries
    await db.analytics_events.create_index([("created_at", -1)])
    await db.analytics_events.create_index([("event_name", 1), ("created_at", -1)])
    await db.analytics_events.create_index([("anonymous_id", 1), ("created_at", -1)])
    await db.orders.create_index([("order_number", 1)], unique=True)
    await db.orders.create_index([("payfast_payment_id", 1)], unique=True, sparse=True)
    await db.payment_attempts.create_index([("order_id", 1), ("provider", 1), ("created_at", -1)])
    await db.payment_attempts.create_index([("provider", 1), ("provider_reference", 1)], unique=True, sparse=True)
    await db.webhook_events.create_index([("provider", 1), ("event_key", 1)], unique=True, sparse=True)
    await db.webhook_events.create_index([("order_id", 1), ("received_at", -1)])
    await resend_events.ensure_event_indexes()


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


# ============ SEO ROUTES ============

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    """Generate robots.txt for SEO"""
    content = f"""User-agent: *
Allow: /
Disallow: /admin/
Disallow: /cart
Disallow: /checkout
Disallow: /account
Disallow: /api/
Disallow: /cdn

Sitemap: {FRONTEND_URL}/sitemap.xml
"""
    return content


@app.get("/sitemap.xml")
async def sitemap_xml():
    """Generate XML sitemap for SEO"""
    base_url = FRONTEND_URL
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    urls = [
        {"loc": f"{base_url}/", "changefreq": "weekly", "priority": "1.0"},
        {"loc": f"{base_url}/shop", "changefreq": "daily", "priority": "0.9"},
        {"loc": f"{base_url}/about", "changefreq": "monthly", "priority": "0.7"},
        {"loc": f"{base_url}/contact", "changefreq": "monthly", "priority": "0.7"},
        {"loc": f"{base_url}/subscriptions", "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base_url}/brew-guide", "changefreq": "monthly", "priority": "0.6"},
    ]
    
    # Add product pages
    for product in PRODUCTS:
        if product.get("is_bundle"):
            continue
        urls.append({
            "loc": f"{base_url}/products/{product['slug']}",
            "changefreq": "weekly",
            "priority": "0.8"
        })
    
    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    for url in urls:
        xml_content += f"""  <url>
    <loc>{url['loc']}</loc>
    <lastmod>{now}</lastmod>
    <changefreq>{url['changefreq']}</changefreq>
    <priority>{url['priority']}</priority>
  </url>\n"""
    
    xml_content += '</urlset>'
    
    return Response(content=xml_content, media_type="application/xml")


@app.get("/cdn")
async def redirect_cdn_root():
    return RedirectResponse(url="/", status_code=301)


@app.get("/cdn/{path:path}")
async def redirect_cdn_path(path: str):
    return RedirectResponse(url="/", status_code=301)

