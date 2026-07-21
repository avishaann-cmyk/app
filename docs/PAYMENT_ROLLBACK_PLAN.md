# Payment Rollback Plan

## Scope

This rollback plan covers payment-provider routing, checkout totals enforcement, webhook/idempotency logic, and return-page status-token behavior.

## Trigger Conditions

Execute rollback when any of the following occur:

1. Payment completion rate drops significantly post-release.
2. Orders remain in pending_payment despite confirmed gateway success.
3. Webhook processing errors spike or duplicate webhook side effects are observed.
4. Payment callback failures increase despite successful customer redirects.

## Immediate Containment

1. Keep PayFast path active unless PayFast itself is impacted.
2. If all payments are unstable, temporarily disable checkout submit endpoint behind maintenance guard and show a clear customer message.

## Code Rollback Procedure

1. Identify release commit range with git log --oneline.
2. Revert payment refactor commits using non-destructive git revert sequence.
3. Redeploy backend with reverted commits.
4. Run focused smoke tests before reopening checkout:
	- PayFast create-payment
	- PayFast webhook verification
	- Order status polling

## Configuration Rollback Procedure

1. Restore last known-good payment environment snapshot.
2. Confirm BACKEND_URL points to publicly reachable webhook host.
3. Confirm PayFast credentials/passphrase are consistent with merchant portal.
4. Clear any temporary debug logging flags in production.

## Data Safety and Reconciliation

1. Do not delete pending_payment orders.
2. Preserve payment_attempt and webhook_events collections for forensic analysis.
3. Run reconciliation endpoint/admin query to classify:
	- paid but not fulfilled
	- pending with gateway success evidence
	- failed/cancelled requiring customer retry
4. For affected paid orders, perform controlled manual status repair and customer confirmation outreach.

## Validation Before Re-enable

1. One full sandbox checkout lifecycle succeeds end-to-end.
2. Duplicate webhook replay proves idempotent behavior.
3. Amount mismatch webhook does not mark order as paid.
4. Frontend success/cancel pages map correctly to backend status transitions.

## Communication Plan

1. Notify internal ops/support immediately when rollback starts.
2. Post customer-facing banner if checkout is temporarily unavailable.
3. Publish incident summary with root cause and resolution criteria before re-enable.
