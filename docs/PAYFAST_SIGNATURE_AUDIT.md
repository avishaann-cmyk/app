# PayFast Signature Audit

Date: 2026-07-21
Scope: Signature generation only. Checkout behavior unchanged.

## 1) Location Of Signature Function

- Signature generation function: backend/server.py (generate_payfast_signature)
- Form submission path: frontend/src/pages/CheckoutPage.js

## 2) Official Algorithm Comparison (Line-by-Line)

Reference used: current PayFast developer docs code examples (PHP/Node/Python), which specify:
- iterate fields in provided order
- exclude empty values
- URL encode each value
- encode spaces as +
- remove trailing &
- append passphrase once
- MD5 hash of final canonical string

Backend implementation after repair:
- Iteration order preserved (insertion order): backend/server.py:994-1004
- Empty values excluded after trim: backend/server.py:1000-1002
- signature excluded: backend/server.py:996-997
- URL encoding via quote_plus with +/space normalization: backend/server.py:1003
- Canonical join with no trailing &: backend/server.py:1006
- Passphrase appended once, encoded, and trimmed: backend/server.py:1016-1022
- UTF-8 bytes for MD5 input: backend/server.py:1024
- Newlines stripped from values and passphrase: backend/server.py:1000, 1016

Primary mismatch found during audit:
- Previous code sorted fields alphabetically before signing.
- PayFast documented examples build canonical strings from field insertion order.
- This produced different signatures for the same submitted fields.

## 3) Output A: Canonical String For One Test Order (Redacted)

Order: CE-20260721-4E8F

Canonical string used for signature:

merchant_id=34064005&merchant_key=[REDACTED_MERCHANT_KEY]&return_url=https%3A%2F%2Fcapeembercoffee.co.za%2Fpayment%2Fsuccess%3Forder_id%3Da2479060-b3c3-4b00-97e6-68d0c6dd53c7%26status_token%3DCOEm1NSSsEiDw6ZeoBY9UF28NCVD0_Lx&cancel_url=https%3A%2F%2Fcapeembercoffee.co.za%2Fpayment%2Fcancel%3Forder_id%3Da2479060-b3c3-4b00-97e6-68d0c6dd53c7%26status_token%3DCOEm1NSSsEiDw6ZeoBY9UF28NCVD0_Lx&notify_url=https%3A%2F%2Fcapeembercoffee.co.za%2Fapi%2Fwebhooks%2Fpayfast&m_payment_id=a2479060-b3c3-4b00-97e6-68d0c6dd53c7&amount=189.00&item_name=Cape+Ember+Order+CE-20260721-4E8F&item_description=Cape+Ember+order+CE-20260721-4E8F&email_address=sig.audit%40example.com&name_first=Sig&name_last=Audit&passphrase=[REDACTED_PASSPHRASE]

## 4) Output B: Actual Submitted HTML Form Fields

- merchant_id: 34064005
- merchant_key: [REDACTED_MERCHANT_KEY]
- return_url: https://capeembercoffee.co.za/payment/success?order_id=a2479060-b3c3-4b00-97e6-68d0c6dd53c7&status_token=COEm1NSSsEiDw6ZeoBY9UF28NCVD0_Lx
- cancel_url: https://capeembercoffee.co.za/payment/cancel?order_id=a2479060-b3c3-4b00-97e6-68d0c6dd53c7&status_token=COEm1NSSsEiDw6ZeoBY9UF28NCVD0_Lx
- notify_url: https://capeembercoffee.co.za/api/webhooks/payfast
- m_payment_id: a2479060-b3c3-4b00-97e6-68d0c6dd53c7
- amount: 189.00
- item_name: Cape Ember Order CE-20260721-4E8F
- item_description: Cape Ember order CE-20260721-4E8F
- email_address: sig.audit@example.com
- name_first: Sig
- name_last: Audit
- signature: b0377a27fffaa0512dc03c0edafa3a69

## 5) Field-By-Field Comparison

- amount before signing == amount submitted: PASS
- item_name before signing == item_name submitted: PASS
- return_url before signing == return_url submitted: PASS
- cancel_url before signing == cancel_url submitted: PASS
- notify_url before signing == notify_url submitted: PASS

Signature parity check for same field set:
- submitted signature: b0377a27fffaa0512dc03c0edafa3a69
- insertion-order algorithm signature: b0377a27fffaa0512dc03c0edafa3a69 (MATCH)
- alphabetically sorted algorithm signature: c5464a4e80b0e3e8771a0223c28a8099 (MISMATCH)

Conclusion:
- Signature mismatch root cause is consistent with incorrect canonical ordering (alphabetical sort) relative to PayFast documented canonical build style.

## 6) Additional Verification Items

- amount formatted to two decimals: PASS (189.00)
- newline characters in submitted fields: PASS (none)
- UTF-8 encoding for hash input: PASS
- + vs %20 behavior: PASS (space encoded as +)
- frontend modifies fields after signature generation: NO
  - frontend only copies backend fields into hidden inputs and submits form (no mutation): frontend/src/pages/CheckoutPage.js:224-232

## 7) Test Added

- Added documented-example regression test:
  - backend/tests/test_payfast_signature.py:23
  - Expected signature for PayFast documented Python example data: f74a321292f7a839c770d42868e21db1

## 8) Constraints

- Credentials unchanged.
- Checkout behavior unchanged.
- Only signature generation logic repaired.
