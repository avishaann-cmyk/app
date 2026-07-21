# PAYFAST Root Cause Analysis

Date: 2026-07-20
Scope: Production checkout failures, reported CloudFront 403, and PayFast hosted flow correctness.
Method: Evidence-only analysis from repository code, targeted tests, and live HTTP header checks.

## Executive Summary

Primary causes found and fixed:
1. Missing webhook signature verifier implementation (`verify_payfast_itn`) while webhook handler invoked it.
2. Potential environment mode/credential drift due non-normalized env values (whitespace/boolean parsing risks).
3. Frontend relied on host fallback instead of a strict backend-provided PayFast action URL contract.

Operational finding (edge/CDN):
1. Current live domain is served by Cloudflare, not CloudFront, based on response headers.
2. `/cdn` and `/cdn/*` are intentionally redirected to `/` in both backend and nginx config.

## Root Cause Details

### 1) Webhook verification path was incomplete

Evidence:
- `POST /api/webhooks/payfast` calls `verify_payfast_itn(request)`.
- A missing verifier function causes webhook verification failure path to break and prevents reliable payment finalization.

Fix implemented:
- Added `verify_payfast_itn(request)` to validate:
  - payload presence
  - merchant id/key match expected credentials
  - signature integrity via `generate_payfast_signature`

Why this matters:
- PayFast hosted redirect is not authoritative for payment completion.
- ITN verification is authoritative; if this path is broken, orders can remain unconfirmed or inconsistent.

### 2) Environment parsing and credential mode drift risk

Evidence:
- Payment mode and credentials are selected from env vars (`PAYFAST_SANDBOX`, merchant id/key/passphrase values).
- Non-normalized env strings can lead to wrong mode/host selection or missing credential detection.

Fix implemented:
- Added normalized env helpers for stripped string and strict boolean parsing.
- Hardened credential checks with explicit errors for missing sandbox or production credentials.

Why this matters:
- A single mode mismatch (sandbox vs production) breaks signatures and merchant validation.

### 3) Hosted form endpoint contract ambiguity

Evidence:
- Checkout must submit browser form to PayFast `https://{host}/eng/process`.
- Frontend used host-derived fallback action URL.

Fix implemented:
- Backend now returns explicit `action_url` in checkout/create-payment payloads.
- Frontend now prefers backend `payment.action_url`.

Why this matters:
- Prevents accidental drift in target endpoint construction and keeps source of truth server-side.

## CloudFront 403 Analysis

Repository evidence:
- No CloudFront-specific runtime logic exists in app code.
- `/cdn` and `/cdn/*` are deliberately redirected to `/`:
  - backend routes return 301 redirect
  - nginx rules return 301 redirect

Live probe evidence (2026-07-20):
- `curl -I https://capeembercoffee.co.za/` returned `200` with `server: cloudflare`.
- `curl -I https://capeembercoffee.co.za/cdn` returned `200` with `server: cloudflare`.
- `curl -I https://www.capeembercoffee.co.za/cdn/some-path` returned `200` with `server: cloudflare`.

Conclusion:
- The observed CloudFront 403 is not reproducible from current public endpoints and is not explained by current app routing.
- Most likely historical or external edge-layer issue (stale DNS/old distribution path/alternate route), not current PayFast request construction.

## Flow Compliance Audit (PayFast Hosted)

Checklist:
- Browser HTML POST to PayFast hosted endpoint: PASS
- Frontend sending card data directly to backend: PASS (not occurring)
- Backend signed payload generation: PASS
- Explicit action URL contract backend -> frontend: PASS
- ITN webhook verification implemented: PASS

## Signature Correctness

Current behavior:
- Signature generated from sorted, URL-encoded fields (excluding `signature`).
- Optional passphrase appended consistently.
- ITN verification recomputes and compares signature plus merchant identity.

Status: PASS (code-path verified and tests passing).

## Sandbox vs Production Status

Current capability:
- Sandbox and production credentials are now validated explicitly by mode.
- Mode selection hardening applied.

Validation performed in this session:
- Focused backend tests passed.
- Frontend build passed.

Not yet completed:
- A real PayFast Sandbox browser payment and real ITN callback confirmation in this environment.

## Totals Consistency Status

Controls in place:
- Backend computes totals and expected amount.
- Payment attempt stores expected total.
- Frontend checks submitted PayFast amount vs backend payable total before redirect.

Status: PASS for implemented controls.

## Production Readiness Assessment

Code readiness: READY (for PayFast-only flow hardening scope).
Operational readiness: CONDITIONAL.

Required final gate not yet satisfied:
- Must execute a successful end-to-end PayFast Sandbox transaction (hosted form submit -> PayFast success -> ITN verified -> order/payment marked complete).

## Verification Evidence

Commands run:
- Focused tests: `pytest -q tests/test_payfast_signature.py tests/test_checkout_payments.py tests/test_shipping_logic.py`
- Result: `14 passed, 12 warnings`.
- Frontend build: `npm run build`
- Result: compiled successfully; SEO pages generated.
- Live headers: `curl -I` checks for root and `/cdn` paths.

## Remaining Blocker

A true end-to-end sandbox payment cannot be proven complete in this run without:
1. Valid sandbox merchant credentials in the active runtime.
2. Executing an actual hosted PayFast payment interaction.
3. Receiving and verifying real ITN callback for that transaction.

Until this is performed and captured, full completion cannot be claimed.
