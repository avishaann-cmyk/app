# Checkout Test Plan

## Automated Regression Status (Current)

| Suite | Result | Notes |
|---|---|---|
| Focused backend tests (PayFast signature + shipping) | Pass | 7 passed |
| Full backend suite | Pass | 62 passed |
| Frontend production build | Pass | No blocking warnings/errors |

## PayFast Lifecycle Tests

| # | Test | Expected |
|---|---|---|
| 1 | Valid sandbox payment | Order transitions to paid after ITN; payment attempt status becomes paid |
| 2 | Cancelled payment | Order transitions to cancelled or payment_failed per return/webhook state; cancellation endpoint succeeds with token |
| 3 | Failed payment | Order/payment attempt move to failed state with reason captured |
| 4 | Duplicate ITN event key | Duplicate event ignored idempotently |
| 5 | Invalid ITN signature | Event rejected from status mutation path |
| 6 | Amount mismatch in ITN | Order not marked paid; mismatch logged for reconciliation |
| 7 | Success page opened before ITN | Status polling remains pending until verified state arrives |
| 8 | Success page refresh | Purchase event deduplicated per order |

## VAT and Total Integrity Tests

| # | Test | Expected |
|---|---|---|
| 1 | Cart subtotal calculation | VAT extracted from inclusive price, not added on top |
| 2 | Checkout server recomputation | Server total matches persisted payment snapshot |
| 3 | Provider payload amount | Provider amount equals server order total (2dp precision) |

## Sedgefield Shipping Rule Tests

| # | Input | Expected |
|---|---|---|
| 1 | Sedgefield token exact/case variants | Free local delivery applies |
| 2 | Non-Sedgefield city | Zone/threshold shipping applies |
| 3 | Mid-checkout city change | Shipping recalculates deterministically |
| 4 | Rule metadata response | shipping_rule field matches applied branch |

## Security and Access Tests

| # | Test | Expected |
|---|---|---|
| 1 | Order status without auth/token | Unauthorized |
| 2 | Order status with valid status_token | Allowed |
| 3 | Cancel payment without token/ownership | Unauthorized |
| 4 | Webhook replay event | Idempotent no-op on duplicate key |

## Manual End-to-End Script

1. Create cart with standard product and complete checkout with PayFast selected.
2. Verify checkout response includes status token and provider metadata.
3. Complete sandbox payment and observe return page status polling.
4. Confirm backend order status and payment attempt status transition to paid.
5. Confirm reconciliation endpoint surfaces transaction with expected state.
6. Repeat with cancellation path and verify explicit cancel endpoint behavior.
