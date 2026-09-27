# ERD · Auth

> Split of [ERD.md](../ERD.md), originally §8 (Auth) and §7 (auth routes).
> Product counterpart: [prd/auth.md](../prd/auth.md) (`FR-AUTH`). Auth env vars are listed in [erd/platform.md](platform.md#configuration-env-orig-9).
> Code: `backend/src/bedrock/core/auth`, `api/v1/` auth router.

## Auth (orig. §8)
- The env var `APP_PASSWORD_HASH` holds an argon2 hash, created with `bedrock hash-password`.
- `POST /auth/login` verifies the password and sets a signed, HTTP-only, `SameSite=Lax` session cookie (`Secure` behind HTTPS). The secret is `SESSION_SECRET`.
- A dependency guards all `/api/v1/*` routes except login and health. The idle timeout is `SESSION_IDLE_MINUTES` (default 720).
- A login rate limit (simple in-memory backoff) protects against guessing.
- Details fixed at M0 planning:
  - The cookie name is `bedrock_session` (Starlette `SessionMiddleware`; `https_only` = `COOKIE_SECURE`).
  - The session stores `auth=True` and `last_seen`; each authenticated request refreshes `last_seen`, and idle expiry clears the session.
  - The throttle is keyed by client IP: 5 failures within 15 min → 429 until 15 min after the last failure. A success resets it.
  - Responses: login 204 / 401 / 429; logout 204; `me` 200 `{"authenticated": true}` or 401.

## API (orig. §7)
- `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
