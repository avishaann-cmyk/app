# Cape Ember Conversion Audit
**Date:** 2026-07-20

## Summary

Conversion-critical payment reliability has materially improved through server-owned checkout totals, provider abstraction, and hardened webhook processing.

Current risk posture:

1. PayFast path is now technically stable in test coverage and build validation.
2. Stitch path remains externally constrained by credential/environment availability.
3. Funnel instrumentation has improved but still needs a backend-verified purchase signal for analytics-grade attribution.

## Funnel Health Snapshot

| Stage | Current State | Conversion Risk |
|---|---|---|
| Product discovery | Stable | Low |
| Cart & totals | Stable, VAT messaging clarified | Low |
| Shipping logic | Server-enforced free Sedgefield rule | Low |
| Checkout | Provider selection + secure handoff | Low |
| PayFast payment | Hardened and test-covered | Medium (needs production callback verification) |
| Stitch payment | Feature-flagged optional path | High (credentials currently unavailable) |
| Success confirmation | Token-gated status polling | Medium (purchase analytics still frontend-triggered) |

## What Was Fixed

### Payment reliability improvements

1. Checkout totals are recalculated server-side before order/payment creation.
2. Payment attempt records now capture lifecycle state transitions.
3. PayFast and Stitch webhooks use idempotency event keys with dedupe persistence.
4. Amount/currency mismatch handling prevents false-positive paid status.
5. Order status polling now requires ownership or status token.

### Conversion UX improvements

1. Checkout now allows explicit payment provider selection.
2. Messaging updated to secure payment framing.
3. Shipping rule analytics and provider selection analytics events added.
4. Cart VAT presentation simplified to reduce confusion.

## Remaining Conversion Risks

### High

1. Stitch live/sandbox credentials currently produce provider unavailability in environment-dependent test flow.
2. Production-level proof of ITN reachability still requires manual external callback validation.

### Medium

1. Purchase event is still initiated from success-page client state; analytics confidence would improve by recording a backend verified purchase event on webhook completion.
2. Location trust copy consistency (Garden Route/Sedgefield messaging) should be reviewed across legal/contact pages.

### Low

1. CORS policy remains broad for production.
2. Seeded admin credential path should be fully environment-driven.

## Analytics Diagnostic Notes

Observed event improvements:

- payment_provider_selected
- shipping_rule_applied
- add_payment_info includes selected provider context

Recommended next analytics hardening:

1. Emit server-side purchase_confirmed event after verified payment transition.
2. Reconcile client purchase event with server event by order ID for dedupe.
3. Alert on checkout created versus payment completed ratio by provider.

## Priority Actions

1. Verify production PayFast callback endpoint reachability and run one controlled sandbox lifecycle.
2. Regenerate/validate Stitch credentials and re-run failing Stitch redirect test.
3. Add backend-confirmed purchase analytics event.
4. Tighten production CORS and finalize secret management cleanup.
