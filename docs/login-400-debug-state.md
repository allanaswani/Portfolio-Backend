# Login 400 Debug — Saved State (2026-07-15)

## Symptom
Frontend login fails. Backend gunicorn logs show:
- `OPTIONS /auth/api/token/ 200` (CORS preflight OK — CORS is already FIXED)
- `POST /auth/api/token/ HTTP/1.1 400 143` (from origin https://ceo.hfgroup.co.ke)

A **400** (not 401) = the JSON body arrives at Django **empty** → serializer returns
"field required". (401 would mean wrong creds; this is not that.)

## What was VERIFIED CORRECT (no code bug on either side)

### Frontend (portfolio-management-frontend) — ALL CORRECT
- `app/(auth)/login/page.tsx` — collects `username` + `password`, both required.
- `store/authStore.ts:45` — `api.post(AUTH + "api/token/", { username, password })`.
- `lib/api.ts:39` — axios with plain object → auto-sends `Content-Type: application/json`
  + JSON-serialized body.
- `lib/api.ts` base URL: `https://ceo.hfgroup.co.ke` → posts to
  `https://ceo.hfgroup.co.ke:9000/`.

### Backend (hf_group_backend) — ALL CORRECT
- `apps/authentication/urls.py:9` — stock `rest_framework_simplejwt.TokenObtainPairView`
  (no custom serializer).
- No custom `AUTH_USER_MODEL` → Django default User → `USERNAME_FIELD = "username"`
  (matches what frontend sends).
- `config/settings/base.py:180` REST_FRAMEWORK has **no** `DEFAULT_PARSER_CLASSES`
  override → DRF defaults INCLUDE `JSONParser`. So Django CAN parse the JSON body.
- No custom `SIMPLE_JWT` serializer override.

## CONCLUSION
There is **nothing in the code to fix** — frontend and backend are both correct.
The JSON request body is being **dropped in transit** between the browser and gunicorn.

Key clue that confirms transport (not code): **Django admin login works** with the
same credentials. Admin is a same-origin **form-encoded** POST; the frontend login is
a cross-origin **JSON** POST to `:9000`. gunicorn on `:9000` is **plain HTTP**, yet the
frontend hits `https://...:9000` — so something is terminating TLS / proxying in front
of `:9000`, and THAT layer is dropping the JSON body.

## NEXT STEP (to pinpoint the exact fix — pick one)
1. Find the proxy in front of :9000 (fix likely lives in one line here):
   ```bash
   sudo grep -rl 9000 /etc/nginx/ /etc/httpd/ 2>/dev/null
   ```
2. If no proxy exists, prove it directly (bypasses proxy, hits gunicorn):
   ```bash
   curl -s -X POST http://127.0.0.1:9000/auth/api/token/ \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"Admin@2024"}'
   ```
   - Returns tokens → confirms proxy is dropping the body (fix the proxy config).
   - Returns 400 → the issue is deeper in Django; paste the body.

## Standing constraints (do not violate)
- OLD SECRET_KEY `&ontpif1mpz8jjn+n0^79h9-&_!w)gibw%-6)!!dbn&kqj(m%1` must NOT be reused.
- `.env` gitignored; secrets never committed; new SECRET_KEY generated on server only.
- Never plain `migrate` on shared prod DB; back up before migrating live prod DB.
- Exposed ANTHROPIC_API_KEY must be rotated (new key only in /etc/hf/prod.env).
- Container runtime = DOCKER (podman failed on old RHEL). Port 9000, --network=host,
  --env-file /etc/hf/prod.env. Env changes need `docker rm -f` + re-run (restart insufficient).
