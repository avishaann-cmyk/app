# PayFast Merchant Account Checklist
**Important:** The items below are merchant-account operations that cannot be resolved by code changes. They must be completed in the PayFast merchant portal or by contacting PayFast support.

---

## 1. Account Verification
- [ ] Log in to https://my.payfast.io
- [ ] Confirm account status is **Verified** (not Pending or Limited)
- [ ] Confirm FICA / KYC documents have been submitted and approved
- [ ] Confirm business name, registration number, and VAT number (if applicable) are correct

## 2. Bank Account
- [ ] Confirm a South African bank account is linked
- [ ] Confirm the bank account is **verified** (PayFast makes a micro-deposit to verify)
- [ ] Confirm the bank account details match the registered entity

## 3. Balance and Payouts
- [ ] Inspect the **Available Balance** in the dashboard
- [ ] Inspect **Cleared Balance** vs **Uncleared Balance**
- [ ] Check payout history for any held, pending, or failed payouts
- [ ] Confirm the **settlement schedule** (Daily / Weekly / Monthly)
- [ ] Confirm **Immediate Payout** is enabled if required
- [ ] Check for any payout holds or compliance flags on the account

## 4. Transaction History
- [ ] Search for recent transactions matching order numbers from your system
- [ ] Confirm whether PayFast shows the transactions as **COMPLETE** or **FAILED**
- [ ] If transactions are COMPLETE on PayFast but orders are still **pending** in your system, the ITN (webhook) is not being processed — this is a code issue, not a payout issue
- [ ] Check for any reversed, chargebacks, or disputed transactions

## 5. Payment Methods
- [ ] Confirm which payment methods are enabled on your account (Card, Instant EFT, SCode, etc.)
- [ ] Confirm no methods are suspended or require re-activation

## 6. Notification URL
- [ ] In merchant settings → Integration, confirm your **Notify URL** is set to:  
  `https://capeembercoffee.co.za/api/webhooks/payfast`
- [ ] Confirm the URL is publicly reachable (not behind a VPN or local dev server)
- [ ] Use the PayFast ITN test tool in the dashboard to send a test notification
- [ ] Confirm deployment env uses backend public URL variable consumed by server (BACKEND_URL precedence)
- [ ] Verify firewall/reverse proxy allows PayFast POST requests to webhook path

## 7. Merchant Credentials
- [ ] Confirm your **Merchant ID** and **Merchant Key** in Integration Settings match what is in your backend `.env`
- [ ] Confirm your **Passphrase** (if set) matches `PAYFAST_PASSPHRASE` in your backend `.env`
- [ ] If `PAYFAST_SANDBOX=true`, confirm the deployment uses sandbox-specific credentials (`PAYFAST_SANDBOX_MERCHANT_ID`, `PAYFAST_SANDBOX_MERCHANT_KEY`, `PAYFAST_SANDBOX_PASSPHRASE`) rather than live values
- [ ] Never share or commit these credentials to a public repository
- [ ] Confirm credentials are stored in runtime secrets store and not hardcoded in image or repository

## 8. Account Limits
- [ ] Check if there are any transaction amount limits on your account
- [ ] Check if there are daily or monthly volume limits
- [ ] Check if the account requires manual approval above a certain amount

## 9. Contact PayFast Support
If payouts are confirmed as COMPLETE on PayFast but funds are not arriving in your bank:
- Contact: support@payfast.co.za
- Reference your merchant ID and the specific transaction IDs
- Ask for a payout trace for the specific settlement dates

## 10. Integration-Specific Validation
- [ ] Confirm checkout payload includes merchant_key in PayFast form field set
- [ ] Confirm m_payment_id sent to PayFast maps to backend order lookup key
- [ ] Confirm duplicate ITN events do not change order state after first successful processing
- [ ] Confirm amount mismatch ITN does not mark order paid
- [ ] Confirm first successful ITN updates both order status and payment attempt status

---

**Note:** No code deployment can release held merchant funds or resolve PayFast account verification issues. These are business-account matters that must be resolved directly with PayFast.
