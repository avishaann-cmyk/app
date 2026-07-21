# Resend Trigger Audit

## Current framework
- Backend: Python FastAPI application in /app/backend/server.py
- Database: MongoDB via motor.motor_asyncio.AsyncIOMotorClient
- Frontend: React app under /app/frontend using create-react-app/craco
- Email provider: Resend Python SDK (resend>=2.0.0)
- Payment provider: PayFast
- Hosting: environment variables and .env driven configuration

## Resend package version
- Resend dependency declared in backend/requirements.txt as resend>=2.0.0

## Existing API routes
- /api/auth/register, /api/auth/login, /api/auth/me, /api/auth/refresh
- /api/cart, /api/cart/add, /api/cart/items/{item_id}, /api/cart/coupon
- /api/checkout for server-side checkout and order creation
- /api/orders, /api/payfast/create-payment
- /api/subscriptions/request for Ember Circle manual subscription requests
- /api/webhooks/payfast
- /api/admin/orders/{order_id}/resend-confirmation

## Database collections
- users, carts, guest_carts, orders, subscriptions
- wishlists, reviews, deliveries, coupons, analytics_events, webhook_events
- settings, content, inventory_adjustments

## Checkout and payment flow
- /api/checkout builds orders from authoritative cart data
- Shipping, VAT, discounts, and totals are calculated server-side
- PayFast ITN callback at /api/webhooks/payfast confirms payment state
- Order confirmation emails are sent from successful payment handlers

## Environment variables in use
- MONGO_URL, DB_NAME
- JWT_SECRET, CORS_ORIGINS
- PAYFAST_MERCHANT_ID, PAYFAST_MERCHANT_KEY, PAYFAST_PASSPHRASE, PAYFAST_SANDBOX
- EMAIL_API_KEY, EMAIL_FROM, ADMIN_NOTIFICATION_EMAIL
- RESEND_API_KEY, SENDER_EMAIL
- FRONTEND_URL, REACT_APP_BACKEND_URL

## Security and trigger gaps
- No dedicated central event store for lifecycle-trigger idempotency outside existing webhook event logs
- No Resend webhook verification/suppression processing for marketing events
- No explicit subscriber double opt-in confirmation endpoint
- No scheduled cart-abandonment automation trigger

## Duplicate event risks
- Duplicate PayFast callbacks may trigger repeated downstream email/lifecycle actions if guards regress
- Background email helper invocations are not fully centralized in a single dispatch layer
