# Account recovery and management

Account settings expose email verification, password change and session revocation.
Forgot-password recovery starts from the sign-in page. New accounts can sign in,
edit bots and read their workspace immediately, but must verify before launching a
paper run. The consolidated initial migration defaults new accounts to requiring
verification and leaves their verification timestamp empty. Accounts explicitly
exempted from verification remain supported by the runtime access policy.

Email links expire after 30 minutes and work once. Reset and verification ask for
a new password and sign out all sessions, including the current browser. Sign in
normally afterward. Verification replaces any password set before mailbox ownership
was proved. Reset alone does not mark an unverified email verified. Authenticated
password change and signing out other/all sessions require the current password;
other-session revocation keeps the current session. Authorization changes apply to
subsequent requests immediately and open streams within the policy recheck interval. Previously
authorized paper runs continue until explicit Stop, expiry or their normal outcome.

Request a verification link explicitly in Account settings. Resending replaces the
prior same-purpose link when the digest commits, including when subsequent SMTP
delivery fails. Every explicit resend is a new issuance; there is no automatic
mail retry. Each mail-request endpoint is limited to 5 attempts per
client IP in 15 minutes; all mail requests together have 3 attempts per normalized
email in that window. Redemption, password change and session revocation are also
limited to 5 attempts per endpoint per client IP in that window. Quotas include
unknown emails and do not lock account sign-in. Requests have generic results and
send a conditional link even when the address is not eligible; such links cannot
change an account. A relay failure returns the same retryable error in either case. A one-second
minimum response time reduces ordinary eligibility timing differences. Slow
dependencies can exceed this floor; exact response latency equality is not promised.

The browser removes a link's fragment before requesting account data, retains its
token only in memory and never redeems on GET. Reopen the email after reloading a
link form. Invalid, expired and already-used links require a fresh request. The
interface confirms only relay acceptance, not inbox delivery. Check spam folders,
then retry later if mail has not arrived. A lost response may require a new link.

The following policy values are checked against the runtime by the contract tests:

| Policy | Value |
| --- | --- |
| Token entropy (bytes) | 32 |
| Token lifetime (seconds) | 1800 |
| Attempt window (seconds) | 900 |
| Attempts per endpoint/IP | 5 |
| Mail attempts per email | 3 |
| Minimum mail response (seconds) | 1 |
| SMTP socket timeout (seconds) | 5 |
| Test mailbox retention (seconds) | 120 |
| Session recheck interval (seconds) | 15 |
| SMTP security values | starttls, tls, local |

## SMTP setup

Use your existing transactional SMTP submission relay. No vendor subscription or
public deployment is created by this slice. The sender domain must be configured
with the relay's required domain authentication and delivery policies.

For local development configure:

```dotenv
POLYBOT_SMTP_HOST=smtp.example.com
POLYBOT_SMTP_PORT=587
POLYBOT_SMTP_SECURITY=starttls
POLYBOT_SMTP_FROM=accounts@example.com
POLYBOT_SMTP_USERNAME_FILE=/absolute/path/to/smtp_username
POLYBOT_SMTP_PASSWORD_FILE=/absolute/path/to/smtp_password
```

`starttls` requires certificate-checked STARTTLS; `tls` uses implicit TLS (usually
port 465). Port selection is explicit. Plain environment username/password values
are supported locally, mutually exclusive with their `_FILE` variant. Both
credentials must be provided together; local relay testing can omit both.
`local` transport is permitted only with explicit local HTTP auth and a loopback
SMTP address. It cannot be used in the production HTTPS deployment.

The Compose release manifest takes host, port, security and sender; put
`smtp_username` and `smtp_password` in its existing private runtime secrets
directory. Only the API mounts them. Production startup checks configuration;
it does not send a message or test inbox delivery. SMTP work runs off the async
event loop with the policy timeout per socket operation. Tokens are never stored
in PostgreSQL as plaintext, logged or placed in worker queues. Mail delivery is
attempted synchronously after the digest transaction commits. A process crash
can leave an undelivered link; a new request replaces it. Signing in remains
available during a mail outage. No recovery is reported complete before redemption.

## Ownership limits

Recovery requires access to the registered mailbox. There is no email-change flow,
manual identity-transfer override, social login, account linking, organization or
MFA in this slice. A user who loses both their password and mailbox access cannot
recover through this application. A still-signed-in user who knows their password
can change it. Account deletion and retention are implemented by Slice 21; see [the data lifecycle runbook](beta-data-lifecycle.md).

The September 10 approved local consolidation includes recovery in the initial
migration. Recreate disposable databases from the former chain; see the README.
Future retained deployments require forward migrations and a compatible rollback
release. Do not downgrade a retained deployment to bypass verification.

## Acceptance

Run from the repository root with disposable PostgreSQL and Redis configured:

```sh
uv run pytest backend/tests/control_plane/test_account_recovery.py backend/tests/control_plane/test_initial_migration.py backend/tests/control_plane/test_account_mail.py backend/tests/control_plane/test_account_startup.py backend/tests/control_plane/test_account_contracts.py
npm --prefix frontend run test:e2e
```

Python tests cover SMTP TLS and failure sanitization, replay, expiry, concurrent
redemption, login/reset races, reauthentication, mailbox throttling, launch gating,
stream revocation and preservation of other accounts and run state. Browser tests
use real API/database/session paths and a test-only mailbox. That sink exists only
in test launchers, expires messages according to the policy table and is never shipped as an
application endpoint. Browser traces are disabled to avoid retaining secrets.

Regenerate the test-only browser paths with
`PYTHONPATH=backend/tests uv run python -m control_plane.account_browser_contract`. Runtime UI contracts use
`PYTHONPATH=backend/tests uv run python -m control_plane.run_contract_fixture`; OpenAPI client generation
remains documented in the control-plane architecture.
