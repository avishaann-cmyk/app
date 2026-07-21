# Cape Ember Payment & Checkout Audit
**Date:** 2026-07-20  
**Branch:** cape-ember-payments-checkout-audit

## 1. Executive Summary

The payment and checkout stack is now PayFast-only. Stitch credentials, endpoints, webhook handlers, tests, and UI branches have been removed to reduce payment complexity and isolate PayFast reliability.

## 2. Implemented Architecture

### Backend payment model

- PayFast is the only supported provider.
- Checkout totals are recalculated server-side and persisted with payment snapshots.
- Payment attempts are tracked for reconciliation and support workflows.
- PayFast ITN remains the authoritative payment confirmation signal.

### Frontend checkout model

- Checkout submits `payment_method=payfast` only.
- Payment handoff uses PayFast form post only.
- Success/cancel status checks continue using secure order status token flow.

## 3. PayFast Hardening

- Signature field consistency validated at create-payment and ITN verification.
- Amount mismatch handling protects against incorrect paid transitions.
- Webhook dedupe and reconciliation indexes retained.
- Payment attempt lifecycle updates retained.

## 4. VAT and Shipping Integrity

- VAT remains inclusive and extracted for reporting only.
- Sedgefield free local delivery remains server-enforced.
- Shipping rule metadata is retained in checkout response.

## 5. Security and Reliability Controls

1. Token-protected order status endpoint.
2. Explicit payment cancel endpoint.
3. Webhook event idempotency persistence.
4. Admin reconciliation endpoint for payment diagnostics.

## 6. Verification Evidence

- Frontend production build: pass.
- Backend test suite: pass.
- Focused PayFast signature and shipping tests: pass.

## 7. Required Manual Production Checks

1. Confirm backend public URL is reachable by PayFast ITN callbacks.
2. Validate PayFast merchant credentials and passphrase in deployment secrets.
3. Execute one controlled sandbox lifecycle and verify order state transitions.

## 8. Deployment Readiness Verdict

PayFast path is conditionally ready after production callback reachability and credential checks are confirmed.
