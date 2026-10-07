# Operator guide (selling Door)

Door has two halves. **You run the cloud half** (panel + one cloud agent per customer). **Each customer runs the Mac half**
(`door-host` + an isolated container) on their own machine, installed with `scripts/install-mac.sh`.

## Onboard a customer (billing phase A: manual)
1. Create the customer (shows the tokens **once**; only hashes are stored):
   ```
   curl -s -X POST https://panel.YOUR-DOMAIN/admin/tenants -H "Authorization: Bearer $DOOR_PANEL_ADMIN_TOKEN" \
        -H 'Content-Type: application/json' -d '{"name":"Acme"}'
   # -> {"tenant_id":"t_...","owner_token":"dro_...","agent_token":"dra_..."}
   ```
   Give the customer `owner_token` (their panel login). Put `agent_token` in `/etc/door/cloud-<customer>.env`.
2. Create `/etc/door/cloud-<customer>.json` from `deploy/cloud.config.example.json` and start `door-cloud@<customer>`.
3. The customer runs the Mac installer, pairs their Mac, texts `Door Activate: <code>` from their phone.
4. Take payment (bank transfer / Pix / payment link), then mark the plan active:
   ```
   curl -s -X POST https://panel.YOUR-DOMAIN/admin/tenants/t_.../plan -H "Authorization: Bearer $DOOR_PANEL_ADMIN_TOKEN" \
        -H 'Content-Type: application/json' -d '{"status":"active","active_until":1893456000}'
   ```
   The customer's agent picks it up on its next cycle (seconds). After `active_until` there are 7 days of grace in which only the
   owner is warned; then new guest requests are refused. `status: canceled` stops them immediately.

## Day-to-day
- List customers and last contact: `GET /admin/tenants`.
- Lost token / leaked token: `POST /admin/tenants/<id>/rotate` (new tokens, old sessions cut immediately).
- Stop a customer: `POST /admin/tenants/<id>/disable` (and `/enable`).
- Back up `/var/lib/door/` (`tenants.json` holds token hashes + plans; each `cloud.db` holds guests and request history).

## Billing phase B (not built)
A payment provider webhook (e.g. Stripe) should call the same `/plan` endpoint. The endpoint is the integration point; no
billing code lives in Door. Refunds/denied/expired requests are never billed because Door only counts completed ones.

## Before the first paying customer
- The SMS line depends on the Plow API terms for reselling to third parties (spec items P1–P3). Get that in writing, or switch the
  `PlowAPI` adapter for another SMS provider.
- Privacy policy and terms: you will store guest phone numbers and the text of questions/answers for 30 days. See `docs/LEGAL-CHECKLIST.md`.
- Run `door-host selftest` on a representative customer Mac (the four isolation checks must print `ok`).
- Put TLS in front of the panel (`deploy/nginx-door.conf`) and keep `/admin/` restricted to your IP.
