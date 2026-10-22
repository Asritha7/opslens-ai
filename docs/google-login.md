# Google OIDC login and application sessions

Google login is optional and requires your own OAuth Web client. The implementation is available, but a live Google login is not verified until real credentials are configured and the end-to-end flow is exercised. No project, OAuth client, billing account, or cloud deployment is created by this code.

## Configure locally

1. In the [Google Auth Platform console](https://console.cloud.google.com/auth/overview), select or create the intended project. Configure the consent/branding and audience for your application. Use testing access and add your Google account as a test user where applicable. Do not enable billing or unrelated paid APIs for this setup.
2. Create an OAuth client of type **Web application**. Register this exact authorized redirect URI: `http://127.0.0.1:8000/auth/google/callback`. The server uses this fixed address, not a caller-supplied host or redirect. This server-side flow needs no Google JavaScript SDK or authorized JavaScript origin.
3. From the repository, run `./uv-local sync --frozen`, then `.venv/bin/python -m opslens.oidc`. Enter the client ID and secret at the prompts. The secret is hidden and neither value is placed in command-line arguments. This creates `.local/google-oidc.json` with mode 600 and refuses to overwrite an existing file. Never paste the secret into chat or commit it.
4. Restart `.venv/bin/python -m opslens.api serve` and open `http://127.0.0.1:8000/`. Select **Continue with Google** and complete login. Use 127.0.0.1, not localhost; Google mode rejects other Host names.
5. The initial configuration grants nobody access. After login, the page displays your verified Google subject ID and explains that no role is assigned. As trusted operator, edit only the `allowed_subjects` object in the private configuration, mapping that exact subject to `platform`, `security`, or `intern`. For example, `"allowed_subjects": {"YOUR_VERIFIED_SUBJECT": "platform"}`. Preserve file mode 600. Reload the page; no restart is needed for role changes.

Do not grant roles based on a typed email, email domain, or a role supplied by the browser. The subject comes from Google's verified ID token. Google is the only supported issuer, so the effective identity key is the fixed Google issuer plus subject.

The [official Google OIDC guide](https://developers.google.com/identity/openid-connect/openid-connect) explains registration, redirect configuration, and server-side identity verification. Google account authentication/consent must be completed by the account holder. This integration does not use Firebase Authentication or Google Cloud Identity Platform.

## Modes and permissions

At startup, the presence of `.local/google-oidc.json` selects Google mode. Demo bearer keys are then disabled, including the demo HTTP CLI. Absence selects the existing demo mode. Mode is fixed for that process: removing or corrupting a configured Google file fails closed with 503, without falling back to demo keys. Changing modes requires an intentional configuration change and restart.

Current role assignments are read on every authenticated request. Removing a subject blocks subsequent evidence requests for its existing sessions; changing a role immediately changes its reader account. A signed-in account with no assignment may view only its own subject/assignment status, not evidence. The operating-system owner and database administrator remain trusted. Existing RBAC, read-only database accounts, and PostgreSQL row-level security continue to apply, including to historical revisions.

## Login and session protection

- Authorization Code flow uses PKCE S256, random state, and nonce. State is bound to an HttpOnly browser cookie, expires after ten minutes, and is consumed once.
- The backend exchanges the code at Google's fixed HTTPS token endpoint. PyJWT validates the RS256 signature using Google's JWKS, issuer, audience, expiry, issued-at time, required claims, nonce, and authorized party where relevant. It does not accept unsigned tokens or a browser-supplied signing-key URL.
- Google ID/access tokens are not stored in the browser or persisted by OpsLens. Only the identity subject is retained in the application session; no offline access/refresh token is requested. The only requested scope is `openid`.
- A fresh random session ID is sent in an HttpOnly, SameSite=Lax cookie. Only its SHA-256 digest is stored server-side. Sessions expire after at most one hour, capped by ID-token expiry; they do not refresh automatically. Re-login replaces the browser's old session.
- Logout invalidates the server session and clears its cookie. It signs out of OpsLens, not the user's Google account. Restarting the API invalidates every session and pending login. Reloading the browser restores a still-valid Google session, unlike demo-key mode.
- Cookie-authenticated POST requests require the fixed Origin and `X-OpsLens-Request: 1` header. Cross-origin API access is not enabled. The UI clears displayed evidence on 401/403 and discards stale responses after disconnect.

## Boundaries

This is a single-process, loopback-only implementation. Cookies deliberately lack Secure on this local HTTP address; public deployment would require HTTPS, Secure cookies, production redirect configuration, and a separate review. Do not expose this server through a tunnel. In-memory stores are bounded to 1,000 pending logins and 1,000 sessions and prune expired entries. There is no distributed session store, audit log, account-management UI, or general rate limiter.

Google requires internet access during login and signing-key retrieval. Existing sessions still use local role configuration and PostgreSQL. Prior returned evidence cannot be retracted. Google MFA is controlled by the user's Google account; OpsLens does not enforce its own MFA policy.

## Endpoint contract

| Endpoint | Purpose |
|---|---|
| `GET /auth/config` | Public mode (`demo` or `google`); never credentials |
| `GET /auth/google/login` | Starts browser-bound Google login |
| `GET /auth/google/callback` | Consumes state/code; redirects to the workspace |
| `GET /auth/session` | Requires session; returns own subject and assigned role, possibly null |
| `POST /auth/logout` | Same-origin logout; returns 204 |

Google routes other than `/auth/config` are absent in demo mode. Protected evidence endpoints use the session in Google mode and bearer credentials in demo mode. Invalid/expired sessions return 401; unassigned accounts or rejected cross-origin POSTs return 403; invalid configuration returns 503. Provider failures use a generic failed-login redirect without reflecting provider error bodies.

## Verification

Offline tests use generated RSA keys and a fake token exchange; they cover signatures, required claims, nonce, audience, issuer, expiry, callback replay/browser binding, role revocation, CSRF/Host checks, cookie flags, session logout, and fail-closed configuration. They do not establish that a particular Google client registration is correct. Finish validation with a real Google account after setup: sign in unassigned, assign a role, query evidence, revoke the role, and sign out.
