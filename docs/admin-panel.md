# Read-only admin panel

The application serves SQLAdmin at `/admin` on the same HTTPS origin as the
product (production: `https://polybotlab.com/admin`). Sign in through the normal
application login. An Admin navigation link appears only for administrators.
An anonymous request redirects to login; an ordinary account receives 403.

## Access and operator commands

All accounts start with `is_admin=false`, including the development seed account.
Admin grants require an existing verified account that is neither suspended nor
quarantined and has no pending deletion request. Use the existing OS-authorized
operator entrypoint from the repository root, with the target environment loaded:

```sh
uv run --env-file .env python -m api.operations grant-admin USER_UUID
uv run --env-file .env python -m api.operations revoke-admin USER_UUID
```

Replace `USER_UUID` with the existing account ID, available in that account's
`GET /api/v1/auth/me` response. On the deployed host, execute the same
`python -m api.operations` command inside the API container using the release's
Compose environment, as described in [beta operations](beta-operations.md).
Browser sessions cannot invoke either operator command.

Changing privileges revokes all sessions for the target account; sign in again.
Unchanged retries are recorded as unchanged and do not revoke sessions again.
Every successful command records the OS actor, action, target and outcome in the
existing operator journal. Invalid grants fail without changing privileges.
Revocation remains possible for suspended or quarantined accounts.

Every admin request checks the current database session and admin flag. Expiry,
sign-out, suspension, quarantine and revocation prevent subsequent access.
The normal bot/run APIs retain their owner-only behavior even for administrators.
Registration and account-management requests cannot set the admin flag.

## Browsing

- **Users:** identity, email, verification, suspension, quarantine and admin status,
  with links to their configurations and runs.
- **Configurations:** saved bots with owners and formatted configuration/graph JSON.
  Retained deleted configurations remain visible and are labeled on their detail page.
- **Runs:** owner derived from the saved bot, status and timestamps, heartbeat,
  recorded failure, history-expiry date and immutable configuration snapshot.

Search users by email/ID and configurations/runs by ID or owner email. Filter
configurations by owner, and runs by owner, bot and status. Lists default to 25
records, newest first, with a maximum of 100 per page. JSON is displayed only on
detail pages. Existing retention rules still apply; deleted history is not restored.

Only explicitly allowlisted fields are shown. Password hashes, authentication
and recovery tokens, execution tokens and deployment credentials are excluded.
Text and JSON are escaped. Create, edit, delete, import, export, bulk-action and
helper routes are unavailable. The entire mounted application, including static
assets, is behind the same admin guard.

## Deployment and extension

SQLAdmin 0.31.1 is pinned. Caddy and the Vite development proxy route `/admin` and
its descendants to FastAPI, preserving the path. Login/logout reuse the existing
opaque session cookie, HTTPS policy, login throttling and same-origin JSON checks.
Admin responses are non-cacheable and cannot be framed. Public access uses normal
application credentials; this iteration does not add MFA or Cloudflare Access.
PostgreSQL, Redis and the API listener remain private.

Migration `0002` adds the admin flag with a database default of false and extends
the operator audit vocabulary. Upgrade with the release's existing migration step;
never recreate a retained database. Upgrade the API, frontend and migration together,
then grant the first verified account explicitly and check ordinary-account denial.
Downgrading to `0001` is refused if admin-operation audit records exist, preserving
that history. The release schema check also prevents rolling an older application
back onto a newer schema; use a compatible forward fix rather than deleting audit
records or resetting production data.

Admin views live in `api.admin`. Add new read-only views explicitly to its registry.
The integration shares the application's database engine and session configuration,
with an admin-local session factory because SQLAdmin disables autoflush on its
factory. It must not change the application's write-session behavior. Future
mutations must call application services with explicit authorization, CSRF checks
and auditing; do not enable generic ORM editing for operational actions.

## Verification

With disposable PostgreSQL and Redis configured through
`POLYBOT_TEST_POSTGRES_URL` and `POLYBOT_TEST_REDIS_URL`:

```sh
uv run pytest backend/tests/control_plane/test_admin.py backend/tests/control_plane/test_auth.py backend/tests/control_plane/test_initial_migration.py backend/tests/control_plane/test_operation_cli.py
npm --prefix frontend run generate:check
npm --prefix frontend run check
npm --prefix frontend test
npm --prefix frontend run build
uv build
```

The browser suite includes `admin.spec.ts`; the HTTPS deployment rehearsal runs the
same scenarios through Caddy. Admin fixture credentials and seeding exist only in
the disposable acceptance harness, never in the production application.
