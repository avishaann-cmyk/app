# PayFast Sandbox E2E Verification Report

## Test Date And Scope

- Date: 2026-07-20
- Environment: Public preview runtime (`*.preview.emergentagent.com`), sandbox preflight only
- Scope in this run: fix blockers, rerun strict preflight, do not initiate hosted payment

## Original Failure Evidence

Initial preflight failure (earlier run):
- Checkout action URL: `https://www.payfast.co.za/eng/process` (live host)
- Malformed synthetic ITN (`application/x-www-form-urlencoded`) returned HTTP 500

Impact:
- Sandbox-only rule was violated by runtime mode selection.
- ITN endpoint error handling for malformed payload was unsafe.

## Root Cause

### Blocker 1: Runtime mode selection was not authoritative
- PayFast host selection depended on legacy global environment parsing and defaults.
- Configuration behavior allowed mode drift in deployed runtime.
- No admin-safe runtime diagnostic endpoint existed to prove effective mode on the process serving checkout.

### Blocker 2: Webhook malformed input handling
- ITN handler did not enforce explicit required-field validation before processing.
- Expected invalid payload paths could bubble into internal failures and HTTP 500.

## Environment Resolution Path Used By Backend

Effective path now used by checkout process:
1. `backend/server.py` loads dotenv from `backend/.env` via `load_dotenv(ROOT_DIR / '.env')`.
2. `get_payfast_config()` reads runtime environment variables each call.
3. `PAYFAST_ENABLED` and `PAYFAST_SANDBOX` are parsed with strict accepted values only.
4. Exactly one credential set is selected:
   - Sandbox: `PAYFAST_SANDBOX_MERCHANT_ID`, `PAYFAST_SANDBOX_MERCHANT_KEY`, `PAYFAST_SANDBOX_PASSPHRASE`
   - Production: `PAYFAST_MERCHANT_ID`, `PAYFAST_MERCHANT_KEY`, `PAYFAST_PASSPHRASE`
5. Exactly one process host is selected:
   - Sandbox: `sandbox.payfast.co.za`
   - Production: `www.payfast.co.za`
6. Unknown/empty boolean values fail safely with configuration error.
7. No frontend variables are used to decide PayFast mode.

## Fixes Implemented

### Configuration hardening
- Added authoritative `get_payfast_config()`.
- Added strict boolean parser for PayFast flags.
- Enforced trimming for all selected PayFast credentials.
- Removed sandbox-to-live passphrase fallback.
- Added startup diagnostic logging (non-secret fields only).
- Added admin-only diagnostics endpoint:
  - `GET /api/admin/payments/payfast-diagnostics`

### ITN hardening
- Added explicit required-field validation for ITN payload.
- Added deliberate responses:
  - malformed/missing fields: 400
  - merchant mismatch: 400
  - invalid signature: 400
  - amount mismatch: 400
  - unknown order: 404
  - duplicate/idempotent valid callback: 200
- Wrapped webhook logic with structured exception handling and safe logging.
- Removed expected-invalid-input paths that could return HTTP 500.

### Order state correction
- Checkout creation now keeps order in `pending_payment` before redirect.
- `payment_processing` is only set when ITN/provider event processing begins.
- Return/status route still does not mark order paid.

## Files Modified

- `backend/server.py`
- `backend/tests/test_payfast_config_and_webhook.py`
- `backend/.env`
- `docker-compose.yml`
- `.env.production.example`
- `docs/PAYFAST_SANDBOX_E2E_REPORT.md`

## Preview Runtime Action

- Updated backend code and sandbox-focused backend env settings in workspace.
- Verified the exact public backend process handling checkout by:
  - successful admin login to preview runtime,
  - querying new diagnostics endpoint,
  - generating a fresh checkout payload from that same public process.

## Corrected Strict Preflight Results

### Runtime diagnostics
`GET /api/admin/payments/payfast-diagnostics` returned:
- `enabled: true`
- `environment: sandbox`
- `process_host: sandbox.payfast.co.za`
- `merchant_id_configured: true`
- `merchant_key_configured: true`
- `passphrase_configured: false`

### Checkout preflight (no payment initiated)
- Checkout creation: HTTP 200
- Action URL: `https://sandbox.payfast.co.za/eng/process`
- Host: `sandbox.payfast.co.za`
- Redacted order reference: `CE-20260720-A44E`
- Payment attempt ID (redacted-safe internal id): `2afe44c6-92f1-41b8-9898-c22b1c4f4a21`
- Amount tested: `189.00`
- Return URL: public HTTPS (`https://capeembercoffee.co.za/...`)
- Cancel URL: public HTTPS (`https://capeembercoffee.co.za/...`)
- Notify URL: public HTTPS (`https://capeembercoffee.co.za/api/webhooks/payfast`)
- Submitted field names are non-empty and include signature field.

### Notify malformed-request behavior
Synthetic malformed ITN probe:
- Endpoint: `POST /api/webhooks/payfast`
- Content-Type: `application/x-www-form-urlencoded`
- Body: `ping=1`
- Result: HTTP 400
- Safe response body: `{"detail":"Invalid PayFast ITN"}`

### Pre-payment order state
- Order status endpoint after checkout creation:
  - `status: pending_payment`
  - `payment_status: pending`

### No production endpoint contacted
- Process host/action URL for checkout payload is sandbox only.
- No hosted payment was opened/submitted in this run.

## Test Artifact Cleanup

Preflight-created test orders were explicitly cancelled through tokenized cancel endpoint so they are not mistaken for paid orders:
- `CE-20260720-544D` -> `payment_status: cancelled`
- `CE-20260720-A44E` -> `payment_status: cancelled`

## Tests Added/Updated And Results

Added/updated coverage for:
1. Sandbox mode selects sandbox host.
2. Production mode selects live host.
3. Empty/unknown `PAYFAST_SANDBOX` fails safely.
4. Sandbox mode does not use production credentials.
5. Production mode does not use sandbox credentials.
6. Credential whitespace is trimmed.
7. Missing sandbox credentials fails configuration.
8. Malformed ITN returns 400 (not 500).
9. Missing signature returns 400.
10. Invalid signature returns 400.
11. Unknown order is deliberate 404.
12. Repeated valid ITN remains idempotent.
13. Checkout creation keeps `pending_payment`.
14. Return/status route cannot mark order paid.

Executed test command:
- `pytest -q tests/test_payfast_config_and_webhook.py tests/test_payfast_signature.py`
- Result: `17 passed`

Note on external integration tests:
- `tests/test_checkout_payments.py` currently depends on external configured URL and returned 404 in this environment; not used as blocker verification signal for this patch.

## Current Status

- Blocker 1: resolved in verified preview runtime preflight.
- Blocker 2: resolved in verified preview runtime preflight.
- Strict sandbox preflight: PASS.
- Full hosted sandbox payment E2E: NOT RUN in this step by design.

## Hosted Attempt Follow-Up (2026-07-20)

After preflight passed, a hosted sandbox submission was attempted without completing payment interaction.

Observed:
- Checkout order: `CE-20260720-5838`
- Checkout action URL: `https://sandbox.payfast.co.za/eng/process`
- Hosted endpoint response: HTTP 400 from PayFast Engine
- Safe message from hosted response:
  - `merchant_id: The merchant id must be 8 digits.`
  - `merchant_key: The merchant key must be 13 characters.`

Root cause for hosted-step failure:
- Sandbox credentials currently configured in the checkout-serving runtime are placeholder values (`your_sandbox_merchant_id`, `your_sandbox_merchant_key`) and therefore invalid for real sandbox payment completion.

Cleanup:
- This hosted-attempt test order was cancelled via tokenized cancel endpoint.
- Final status: `pending_payment` with `payment_status=cancelled`.

## Hosted Attempt Follow-Up 2 (Post-Deploy Recheck, 2026-07-20)

After user-confirmed deployment completion, hosted sandbox submission was re-run.

Observed:
- Checkout order: `CE-20260720-FB30`
- Action URL remained correct: `https://sandbox.payfast.co.za/eng/process`
- Submitted payload still contained placeholder merchant fields:
  - `merchant_id=your_sandbox_merchant_id`
  - `merchant_key=your_sandbox_merchant_key`
- Hosted endpoint response: HTTP 400 from PayFast Engine
- Safe message:
  - `merchant_id: The merchant id must be 8 digits.`
  - `merchant_key: The merchant key must be 13 characters.`

Conclusion:
- Deployment has not yet applied real sandbox merchant values to the checkout-serving backend process.

Cleanup:
- Order `CE-20260720-FB30` was cancelled.
- Final state confirmed: `pending_payment` and `payment_status=cancelled`.

## Hosted Attempt Follow-Up 3 (Final Rerun, 2026-07-20)

After sandbox credentials were updated in local workspace env, hosted flow was re-run against the public preview runtime.

Observed:
- Checkout order: `CE-20260720-A5DF`
- Action URL: `https://sandbox.payfast.co.za/eng/process`
- Checkout payload still emitted placeholder merchant values:
  - `merchant_id=your_sandbox_merchant_id`
  - `merchant_key=your_sandbox_merchant_key`
- PayFast hosted response remained HTTP 400 with the same merchant format errors.

Conclusion:
- The checkout-serving preview backend process is still running stale or different environment values than local workspace `backend/.env`.
- Successful hosted sandbox completion remains blocked until preview runtime secrets are updated and process is restarted/redeployed.

Cleanup:
- Order `CE-20260720-A5DF` was cancelled.
- Final state confirmed: `pending_payment` with `payment_status=cancelled`.

## Cleared To Proceed

System is conditionally ready for hosted sandbox payment once valid sandbox Merchant ID and Merchant Key replace placeholders in the checkout-serving runtime.

## Remaining Production-Readiness Steps

1. Run the actual hosted sandbox payment transaction.
2. Capture real ITN callback validation proof and final paid transition proof.
3. Run replay/idempotency proof on real callback data.
4. Confirm single stock/email/analytics side effects on real payment lifecycle.

## Controlled Comparison: PayFast 400 vs CloudFront 403 (2026-07-21)

### Failure Timestamp And CloudFront Evidence

- User-reported CloudFront failure date: `2026-07-21`
- User-reported CloudFront Request ID:
  - `rtTZUqxcQ4HHrU373oq-n1pWM7qgcHJKnh1fJBFnTuRCnWSZu-QsFQ==`
- Exact client-side failure timestamp for that specific 403 was not available in captured logs/HAR at audit time.

Additional user-reported CloudFront failure:
- Request ID: `jRITDhdO7UfDxdU3EuRSZM2V7G8SXZaPX2qMoMIgfPL0okXK76GsfA==`
- Observed banner text: `The request could not be satisfied. Request blocked.`
- Runtime context check at audit time showed checkout service in production mode (`process_host=www.payfast.co.za`), which is fronted by CloudFront on live PayFast routes.

### Comparison Scope

- Previous attempt (captured): PayFast Engine HTTP 400 (`invalid signature` family).
- Current attempt (user-reported): CloudFront 403 `Request blocked`.
- Controlled one-shot isolated diagnostic run executed at `2026-07-21T07:57:37Z`.

### 1) Destination Confirmation (Controlled)

Controlled diagnostic form action was exactly:
- `https://sandbox.payfast.co.za/eng/process`

Verified:
- HTTPS: yes
- Hostname: `sandbox.payfast.co.za`
- Path: `/eng/process`
- Trailing slash: no
- Query string: no
- Redirect through Cape Ember before submit: no
- Reverse proxy in submit path: no
- CloudFront URL used as form action: no
- iframe submit: no
- router navigation submit: no
- fetch/Axios/XHR submit: no

Logged final action hostname/path:
- `sandbox.payfast.co.za` + `/eng/process`

Note:
- Previously captured checkout payload used `https://www.payfast.co.za/eng/process` (live host), which is a separate destination class from sandbox.

### 2) Submission Method Confirmation (Controlled)

Controlled run used:
- top-level browser HTML `<form method="POST">`
- content type: browser standard `application/x-www-form-urlencoded`

Not used:
- GET
- JSON
- fetch/Axios/XHR
- iframe
- server-side proxy
- custom auth headers

### 3) Redacted Safe Field Comparison

Legend:
- `N/A` means not present in that payload.
- `Unknown` means the specific user-reported 403 payload was not captured in HAR/network logs.

| Field | Previous 400 present | Current 403 present | Previous length | Current length | Previous empty | Current empty | Previous pre-encoded value | Current pre-encoded value | Changed after signature creation |
|---|---|---|---:|---:|---|---|---|---|---|
| merchant_id | yes | Unknown | 8 | Unknown | no | Unknown | no | Unknown | no change observed in prior 400 audit |
| merchant_key | yes | Unknown | 23 | Unknown | no | Unknown | no | Unknown | no change observed in prior 400 audit |
| return_url | yes | Unknown | 137 | Unknown | no | Unknown | no | Unknown | no change observed in prior 400 audit |
| cancel_url | yes | Unknown | 136 | Unknown | no | Unknown | no | Unknown | no change observed in prior 400 audit |
| notify_url | yes | Unknown | 50 | Unknown | no | Unknown | no | Unknown | no change observed in prior 400 audit |
| m_payment_id | yes | Unknown | 36 | Unknown | no | Unknown | no | Unknown | no change observed in prior 400 audit |
| amount | yes | Unknown | 6 | Unknown | no | Unknown | no | Unknown | no change observed in prior 400 audit |
| item_name | yes | Unknown | 33 | Unknown | no | Unknown | no | Unknown | no change observed in prior 400 audit |
| item_description | yes | Unknown | 33 | Unknown | no | Unknown | no | Unknown | no change observed in prior 400 audit |
| email_address | yes | Unknown | 21 | Unknown | no | Unknown | no | Unknown | no change observed in prior 400 audit |
| signature | yes | Unknown | 32 | Unknown | no | Unknown | no | Unknown | N/A (signature output field) |

Controlled minimal-form payload (single-shot) included:
- merchant_id, merchant_key, return_url, cancel_url, notify_url, m_payment_id, amount, item_name, signature
- intentionally omitted optional `item_description` and `email_address`

### 4) Malformed/Unsafe Value Checks

Previous 400 captured payload:
- newline characters: none
- carriage returns: none
- null bytes: none
- tabs: none
- HTML markup in values: none
- emojis/non-ASCII: none
- malformed URLs: none detected
- localhost/private preview hosts in PayFast URLs: none (public HTTPS values)
- spaces around credentials: none detected in captured submitted values
- duplicated fields / duplicate signature input: not observed in captured payload
- empty hidden fields submitted: not observed in captured payload
- literal `undefined`/`null` strings: not observed
- passphrase submitted as field: no

Controlled minimal form checks:
- duplicate signature inputs: no (exactly one)
- passphrase field present in HTML form: no
- return/cancel/notify URLs: valid HTTPS public domain values

Sanitization applied for controlled diagnostic:
- `item_name` set to plain text: `Cape Ember Test Order`
- `item_name` length: 21 (under 100)

### 5) Credential Consistency Verification

Current active checkout-serving runtime diagnostics at audit time:
- `enabled: true`
- `environment: production`
- `process_host: www.payfast.co.za`

Implication:
- Current active runtime was not in sandbox mode during this audit capture.
- This must be corrected before making sandbox-only conclusions from checkout-generated payloads.

Safety checks:
- No production credentials were changed in this step.
- No switch to live host was performed by this audit flow.

### 6) Signature/Submission Integrity Status

Preserved and verified in codebase:
- signature field excluded from canonical source
- empty optional fields excluded consistently
- insertion order canonicalization retained
- passphrase appended once
- URL encoding uses PayFast-compatible `quote_plus` style
- no trailing ampersand
- lowercase MD5 output
- submitted signed fields remain unmodified by frontend form creation

### 7) Minimal Isolated Form Test Result

Test type:
- local protected diagnostic HTML page (not publicly linked)
- one top-level browser POST to `https://sandbox.payfast.co.za/eng/process`

Result:
- reached `https://sandbox.payfast.co.za/eng/process`
- page title: `PayFast - Engine`
- response content indicates `Error: 400 Bad Request`
- visible reason: `signature: Generated signature does not match submitted signature.`

Interpretation:
- A direct sandbox browser form POST did not reproduce CloudFront 403 in this controlled run.
- This points away from a universal sandbox CDN block and toward request-context variability (specific payload, client/network, or transient edge behavior).

### 8) Browser/Network One-Shot Constraint

One controlled browser submission was executed only once.

Not controllable from this environment:
- user browser extensions/content blockers
- user VPN
- user local network path

Manual follow-up for user side (single attempt only):
- Incognito/private window
- disable blockers/VPN
- alternate network if available
- preserve CloudFront Request ID if repeated

### 9) PayFast Status Check

Official status source checked:
- `https://status.payfast.io`

Observed at test time:
- unresolved incident listed: `Standard Bank EFT payments` (Identified)
- `Aggregation Sandbox (test platform)` component displayed as `Operational`
- top-level `General` group displayed `Degraded Performance`

Interpretation:
- Provider status showed mixed conditions (degraded general group, sandbox component operational).
- Do not run rapid retries while degraded conditions exist.

### 10) Provider-side vs Application-side Assessment

Current evidence suggests:
- CloudFront 403 is not conclusively attributable to signature logic alone.
- Prior 400 and controlled 400 both show payload/signature-path issues can still occur when destination is reachable.
- Reported 403 may be edge/network/client-context specific or intermittent provider/CDN behavior.

Smallest next correction:
1. Force active checkout-serving runtime back to sandbox mode (`sandbox.payfast.co.za`) via authoritative env and redeploy.
2. Capture one HAR for a single failing 403 attempt (no repeated retries), preserving request method, action URL, and form field names only.
3. Re-run one isolated minimal form in the same browser/network context as the failing attempt.
4. If CloudFront persists with same context, escalate to PayFast support with Request ID and timestamp.
