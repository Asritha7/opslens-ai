# Local API contract

Start the server using [SETUP.md](../SETUP.md). Base address: `http://127.0.0.1:8000`. The supplied server command binds only to loopback. Browser documentation/OpenAPI endpoints and CORS access are disabled. No production login, TLS, rate limiting, or automatic key expiry is implemented.

## Endpoints and authentication

| Endpoint | Credential | Response |
|---|---|---|
| `GET /health` | None | `{"status":"ok"}`; process liveness only |
| `GET /v1/me` | Bearer key | `subject` and assigned `role` |
| `POST /v1/select` | Bearer key | Selection result below |

Protected requests use `Authorization: Bearer <local-key>`. Use the supplied `opslens.client` command to avoid putting keys into shell history. The private key file is plaintext with owner-only permissions and is Git-ignored. Records map a unique subject and token to platform, security, or intern. The server reloads it per request; revocation applies to subsequent authentication, not already-running requests.

## Selection request

```json
{
  "service": "identity-service",
  "software_version": "2.4.0",
  "environment": "production",
  "key_rotation_enabled": true
}
```

`service` is a 1–100 character identifier containing ASCII letters, digits, `_`, or `-`. `software_version` is an exact three-part numeric string, maximum 32 characters. `environment` is `production` or `staging`. The first three fields are required. `key_rotation_enabled` is a strict boolean or null, defaults to null, and means unknown when omitted/null. Extra fields, including `role`, are rejected. The supplied context is not checked against live infrastructure.

## Selection response

All four domain outcomes return HTTP 200. A conflict is a completed evaluation, not an HTTP server error.

| Status | Meaning |
|---|---|
| `selected` | Applicable verified guidance is available without detected conflict or uncertainty |
| `conflict` | Applicable documents contain opposing normalized rules |
| `needs_context_or_review` | Relevant documents require more user context or metadata review |
| `insufficient_evidence` | Suitable approved guidance accessible to the caller was not found |

| Field | Shape and meaning |
|---|---|
| `message` | Human-readable result summary |
| `next_steps` | List of suggested actions; the system executes none |
| `questions` | Objects with `field`, `question`, and `allowed_answers`; currently key rotation with true/false answers |
| `review_items` | Document ID, title, revision, path, and `reasons` |
| `conflict_details` | Action, `basis: catalog_rules`, explanation, and opposing document references/rules |
| `applicable_documents` | IDs of matching verified documents |
| `uncertain_documents` | IDs of otherwise relevant documents requiring context/review |
| `conflicts` | Pairs of conflicting document IDs |
| `recommended_documents` | Matching IDs only for `selected`; empty otherwise |
| `evidence` | Document ID, revision, and source path for applicable documents |

Review reasons are `metadata_unverified`, `missing_environment`, `missing_version_min`, and `missing_version_max_exclusive`. Missing context and metadata review can coexist. Follow-up answers are submitted in a new request; there is no conversation/session memory.

For example, a version-2.5.0 production query with key rotation enabled under the platform identity reports `disable_key_rotation` with `must` from RB-050 and `must_not` from RB-051. These are catalog rules, not direct source quotations. A version-2.4.0 query with unknown key rotation asks whether rotation is enabled. An intern production query reports insufficient evidence without identifying restricted documents.

All result details are generated after access filtering. Paths are references, not download URLs. A future UI should display message/next steps and the appropriate question, review, or conflict details; no graphical interface exists yet.

## Request and service errors

| HTTP code | Meaning |
|---|---|
| 401 | Missing or invalid credentials; includes `WWW-Authenticate: Bearer` |
| 422 | Invalid request fields or values |
| 503 | Authentication configuration or evidence store unavailable |

Handled errors return a generic `detail` string without echoing credentials, invalid input, or database source rows. Responses use `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`. Database failure never falls back to unrestricted local files.
