# Web Control Plane v0 Product Specification

Status: v0 and Slice 15 accounts/private ownership are implemented. Slice 19 extends
the historical account policy below with recovery and verification.
This document owns product scope and user-visible outcomes.
`web-control-plane-architecture.md` owns technical contracts. The implementation
plan references those contracts instead of restating them.

## Purpose

The private control plane lets signed-in users configure, launch and observe
their own paper bots. Accounts are local to this application; organization
tenancy, billing and live trading remain outside this product.

## Goals

- Present one user-facing node-based bot concept backed by the trusted
  server-owned definition and node catalogs.
- Configure each bot and edit its strategy graph in one workspace.
- Start a new graph fresh or copy it from another configured bot.
- Save reusable bot configurations before running them.
- Render bot forms from backend-provided metadata.
- Let the trusted operator compose and run a validated paper-trading graph from
  framework-described lifecycle triggers, event outputs, typed constants,
  comparisons, and BUY/SELL broker actions.
- Launch multiple paper runs and queue work above worker capacity.
- Stop queued or running runs.
- Persist run state and useful progress in PostgreSQL.
- stream progress and live chart updates to a SvelteKit browser UI;
- restore durable progress after reload or reconnect; and
- match the existing terminal dashboard's information and controls, including
  the `v`-toggled followed-wallet timeline.

## Non-goals

- Organizations, payments, plans, or quotas.
- Public-internet exposure without an external access boundary.
- Live trading or web collection of wallet/CLOB credentials.
- Pause, resume, automatic restart, or restoration of bot-local paper state.
- Scheduling or bulk actions. Later extensions below define account/data lifecycle
  and saved-bot deletion; users do not configure retention policy.
- A user-facing bot catalog or isolated graph-template management workflow.
- Template revision history, template-to-bot propagation, graph deduplication,
  or retained template provenance.
- Recorder or backtest controls.
- User-supplied Python paths, arbitrary code, plugins, unbounded loops, or
  node-defined network/protocol operations. Graphs use only the finite
  code-owned node catalog.
- ECS implementation. v0 keeps only the narrow launcher seam described in the
  architecture; it adds no ECS fields or adapters.

If a feature is not in Goals, it is not implied by “SaaS,” “future,” or
“extensible.” Add it in a later slice when it has a real consumer.

## Trust Boundary

Email/password sessions authenticate users and scope each private resource to
its owner. The application must still run locally or on a private network, or
behind an external access boundary. Accounts do not authorize public deployment.

Every web launch is paper-only. The browser cannot select live mode or submit
credentials. Existing live-execution gates remain unchanged; the control plane
does not wrap, duplicate, or weaken them. Do not add placeholder billing, entitlement, trading credential, or organization fields.

## Bot Catalog

A bot definition is a trusted, code-owned mapping from a stable public ID to a
private Python factory and one typed launch-input model. The API never returns
or accepts factory/import paths. During alpha there is no public definition or
graph schema version. Code and generated clients move together, while databases
containing accounts require explicit migrations that preserve private ownership.

The descriptor tells the frontend whether market and wallet selection are
user-configured, bot-managed, or absent. A bot-managed definition remains
launchable and shows an explanation instead of an irrelevant editor. The
backend launch model is the sole field definition; its JSON Schema and small
typed widget annotations drive the generic frontend form.

The initial catalog is exactly:

| Definition ID | Factory | Market | Wallet | Label |
| --- | --- | --- | --- | --- |
| `btc-five-minute-winner` | `polybot.examples.winner_trading_bot:create` | bot-managed | absent | standard |
| `btc-five-minute-momentum-example` | `polybot.examples.example_btc_five_minute_momentum:create` | bot-managed | absent | example |
| `btc-five-minute-contrarian` | `polybot.examples.meh_trading_bot:create` | bot-managed | absent | standard |
| `btc-five-minute-market-watcher` | `polybot.examples.btc_5m:create` | bot-managed | absent | non-trading |
| `dynamic-random-hold-example` | `polybot.examples.example_dynamic_random_hold:create` | bot-managed | absent | example |
| `dynamic-wallet-filter-copy-example` | `polybot.examples.example_dynamic_random_hold_wallet_filter_copy:create` | bot-managed | user-configured | example |
| `node-based-bot` | `api.catalog.node_based.bot:NodeBasedBot` | user-configured | absent | standard |

`polybot.my_bot:create` is an alias of the winner strategy and is not another
catalog entry.

## Saved Bot and Run

A saved bot has an immutable definition ID and one editable configuration document
containing all paper settings and its strategy graph. Creation and edits save the
whole configuration atomically. Copying a graph creates an independent bot draft.
There are no separate saved templates, graph revisions, or allowances for either.

Each Run action creates a UUID-backed run with its own immutable definition ID,
saved-bot ID, and a deep copy of the complete configuration in `config_snapshot`.
The snapshot is committed while queueing, before worker delivery. Later bot edits
never affect queued, active, or historical runs. Unsaved edit history is not retained.
The public run response exposes this document as `config`, including `config.graph`.
The user approved rewriting migration `0001` and discarding local data for this
undeployed change; no migration backfill is needed.

The public lifecycle is:

```text
queued -> starting -> running -> stop_requested -> stopping -> stopped

queued | starting | running | stop_requested | stopping -> failed
starting | running | stop_requested | stopping -> interrupted
```

- A worker obtains ownership with one atomic database claim.
- Duplicate delivery cannot start a claimed or terminal run again.
- Stop is idempotent. A queued stop goes directly to `stopped`; a running stop
  uses the existing cooperative `run_bot()` cleanup path.
- A missing heartbeat beyond the deployment lease produces `interrupted`.
- Restart or redelivery never resumes an interrupted run. Running the saved bot
  again creates a new run, paper portfolio, and source-event claim lifetime.

## User Experience

### Home and bot creation

The home page is an operator workspace with one primary **New bot** action, a
structured list of configured node-based bots, and recent runs. Both lists start
expanded, with integrated section headers, displayed-item counts, and independent
keyboard-accessible collapse controls. Collapsing a section is local to the page
visit; returning home shows both lists again. The Runs section shows up to ten recent rows.
Bot rows expose
the information needed for comparison: name, market scope, max order size,
saved-configuration status, run status, and last update. The frontend does not expose
other definition types or a graph-template page. A failed Runs row
exposes the same latest runtime error and recorded failure outcome shown on its
failed lifecycle event, on hover or keyboard focus.

The bot builder renders typed configuration fields and the Svelte Flow graph in
one form. A graph starts from the server-provided starter graph or a copy of
another bot's latest graph. Saving creates the bot without running it and opens
bot detail. Decimal inputs remain decimal strings across the API boundary.
Frontend validation is only feedback; backend ingress is authoritative.
The Markets control is a searchable multi-select backed by the control-plane
API, not a direct browser-to-Polymarket integration. Suggestions show individual
market questions and event context; selected rows retain exact slugs and can be
removed or extended with more searches. New selections must resolve to available
markets on save. Existing unavailable selections stay visible and removable.
Failed saves preserve the operator's edits. Backend field violations appear
under their owning controls, while graph violations appear in a focused summary
beside the canvas with the server message and any available node or connection
location. Transport failures remain page-level notices.
The new-bot and saved-bot detail pages render a Svelte Flow canvas. Its
trigger palette is derived from `BaseBot` lifecycle hooks, and each trigger exposes the
outputs derived from that hook's annotated event dataclass and explicitly
marked computed outputs. Drawn edges determine which outputs the graph uses.
`BookSnapshot.best_bid` and `best_ask` provide nullable
top-level price/size fields without duplicating the underlying books. The same
backend catalog describes Number/Boolean/Text values, parameters, comparisons,
logic, arithmetic, event controls, portfolio queries, diagnostics and fixed-side
BUY/SELL actions derived from `Broker.submit(OrderRequest)`. The frontend
uses these descriptors for ports and operation choices.

The builder draft stores the editable catalog graph. Copying another bot takes
its latest graph as an independent draft and saves it into a new immutable
bot-owned revision.
For each accepted event, the node bot evaluates the matching acyclic branch once
and submits each reachable enabled action at most once through the existing
paper broker. While a condition remains true, each accepted event may submit
another order unless the graph adds an explicit portfolio condition or event
control. Cooldown, Once Per Key and Deduplicate Event retain bounded state for
one bot run; a new run starts with fresh state.

### Bot and run detail

Bot detail edits settings and graph in one form, saves both in one transaction,
and runs the latest fully saved state. Run is disabled while the form has unsaved changes. The graph can also
be reset or copied from another bot without creating an ongoing relationship.

The detail page shows lifecycle/timing, immutable configuration, bootstrap and
activity progress, portfolio/equity, orders/fills/failures/settlements, stream
health, the dashboard charts, the saved bot, the exact executed graph,
and Stop while the run is stoppable. Running
stream health is ephemeral and the final graceful-shutdown summary is durable.
Terminal runs remain readable. Rerunning happens from saved-bot detail and uses
the latest saved configuration; historical run configuration never changes.

Run configuration uses the builder's field order and responsive layout with
read-only text values. Selection lists stay readable, and graph JSON is omitted
in favor of the executed graph viewer. Timing follows as a separate section.
Both bot and run graphs fit automatically once all nodes and the viewport are
ready. Run graphs allow pan, zoom and Fit View without enabling graph edits.

## Dashboard Parity

`docs/architecture.md` section **Terminal Observability** is the behavioral
source for accepted-book freshness, price gaps/stale spans, stable token
admission, trade markers, settlement removal, executable equity, followed-wallet
lanes/buckets, time navigation, and the `z`/`x`/`r`/`v`/`j`/`k` controls.

The web implementation must present those same meanings with browser-native
ECharts and visible controls. It may improve layout, tooltips, and pointer
interaction; it must not invent a second valuation or chart policy.

The technical chart cadence, persistence, and stream contract is owned by
`web-control-plane-architecture.md`.

## Availability

Committed progress survives reload and reconnect; ephemeral frames are not
recoverable. Reload immediately restores only the newest bounded event page,
and the operator explicitly requests older progress. While streaming, the
browser keeps a rolling window sized to the loaded event pages, forgetting the
oldest overflow locally; the operator can fetch those stored events again.
Chart rendering retains a bounded terminal-equivalent history rather than
automatically loading the complete run. `web-control-plane-architecture.md`
owns the storage and delivery mechanism.

Web observability failure must not change paper-bot execution. The technical
invariant and mechanism are owned by `web-control-plane-architecture.md`
section **Execution and Lifecycle**.

## Acceptance

v0 is complete when one trusted operator can:

- save and launch at least two registered paper bots concurrently and see excess work
  remain queued;
- stop queued and running runs without duplicate execution;
- see worker loss become `interrupted` without automatic resume;
- reload or reconnect, recover the newest committed progress in order, and load
  older committed pages on demand;
- use market, equity, and followed-wallet views with terminal-equivalent
  semantics and controls;
- add a trusted configuration field using an already-supported field/widget
  kind without editing the builder page; and
- create a node-based bot in one form, optionally copy another bot's graph,
  save the complete bot configuration, and launch a paper bot that compares a computed best bid/ask value with
  a constant, submits the configured BUY or SELL through the existing broker,
  reports its order/fill through the existing progress path, reloads its exact
  graph snapshot, and stops cooperatively.

No endpoint may violate the **Trust Boundary**, and the existing CLI must remain
usable without control-plane services.


## Graph MVP update

The current node editor adds backend-catalogued logic/math, custom parameters,
unified Number ports, own-portfolio queries, signal controls and diagnostics.
`POST /api/v1/graphs/preview` evaluates a draft against synthetic inputs without
submitting orders or creating a run. The starting-point selector includes two
example strategies. See [Graph MVP authoring](graph-node-mvp.md) for the complete
contract and [delivery checklist](graph-mvp-plan.md) for both implementation phases.
These capabilities supersede earlier graph-MVP exclusions; public deployment and
live trading remain outside this work.

## Slice 15: Users and Private Ownership

This implemented extension supersedes v0's single-operator and no-authentication
restrictions. The private-network boundary still applies. Delivery and acceptance live in
[Slice 15 of the implementation plan](implementation-plan.md#slice-15-users-authentication-and-resource-ownership).

Agreed MVP scope:

- Anyone who can reach the application can create an account with email and
  password, then log in and log out. No invitation or administrator role is
  required. Registration checks email syntax but sends no email and requires no
  proof of mailbox ownership. Successful registration signs the user in.
- Accounts have stable internal user IDs. An email is a login identifier, not a
  verified identity, public profile, or resource-ownership key.
- Each user sees and manages only their own saved bots, configurations, graphs,
  runs, history, and event streams. The server assigns ownership from the
  authenticated user; the browser cannot choose an owner.
- Existing copy workflows copy only the user's own bot graph in this slice.
  Code-owned starter/example graphs remain available to every signed-in user.
- Runs inherit the owning bot's user. Bot ownership cannot
  transfer, and bots referenced by historical runs remain present.
- Login and registration are the only new account screens. The app restores
  the signed-in user on reload and clears private state on logout or expiry.
- Paper-only execution, immutable run snapshots, and framework isolation remain
  unchanged. This slice does not itself authorize public deployment.

Deferred: email verification/delivery, password recovery, email/password changes,
Google/GitHub or other social login, account linking, MFA, account deletion,
organizations, roles, billing, quotas, and marketplace browsing/publishing.
At the Slice 15 checkpoint there was no self-service forgotten-password recovery (superseded by Slice 19 below); the UI must
not offer a flow that does not exist.

A later marketplace slice can publish a selected configuration/graph snapshot
and copy it into a new bot owned by the copying user. Sharing must not expose
private runs or make either bot track the other's edits. Visibility and
provenance fields belong to that later slice, not this foundation.

Future social login must attach to stable internal users through an explicitly
designed account-linking flow. Matching an email supplied during unverified
registration is not sufficient proof to link accounts. Existing email/password
accounts must not become implicitly verified when those features arrive.

## Public Paper-Trading Beta

The user-approved next direction is a public paper-only service. The
[readiness roadmap](implementation-plan.md#public-paper-trading-beta-roadmap)
assigns production deployment, resource limits, run reliability, account recovery,
operational controls, backups/data lifecycle, onboarding and launch/support
information to Slices 16–23 after the Slice 12F foundation.

Slices 16–23 are delivered. The policies below describe their implementation.
Keep the current private boundary until the complete operational open-signup
gate passes, including configured operator/support ownership. Private bot/run ownership remains in force
after public launch. Marketplace and live trading are outside this beta roadmap.

Slice 16 implementation uses a private HTTPS staging entrypoint. Browser
authentication and resource ownership have the same behavior through the proxy;
release maintenance may briefly make the service unavailable. Failed migrations
keep it unavailable until an operator repairs the release. This infrastructure
does not enable public signup. Recovery from interrupted workers is owned by
Slice 18 and never resumes a paper portfolio automatically.

## Slice 17: Paper-beta allowances

The allowance heading includes an information icon for run limits and history
retention. Its details appear on hover or keyboard focus and can be pinned by
tapping; Escape or an outside tap dismisses them.

Each account has the same free allowance returned with its private usage by
`GET /api/v1/usage`. The owning numeric contract is `api.limits.policy.PAPER_BETA`;
there are no paid tiers or account-supplied limit overrides. The approved initial
values are conditional on the bounded load rehearsal documented in the plan.

New runs enter a bounded queue. Workers select the oldest queued run whose
account has a free active slot (creation time, then run ID). A busy account does
not block eligible accounts behind it. Starting and stopping runs occupy active
capacity until their terminal transition commits. Queue saturation distinguishes
an account allowance from temporary shared capacity; invalid subscription
configuration is a validation failure. The browser displays these explanations
and the account's own usage, never other users' details.

The duration allowance starts at worker claim, includes startup, and expires
without a browser. Expiry stops the paper run with an explanation. The unresolved
market union is capped throughout execution, including dynamic discoveries and
positions; exceeding it ends the run explicitly instead of silently dropping
portfolio interests. CLI users retain their existing unlimited default.

Saved bots have a creation allowance; configuration edits have no revision cap
and there is no separate template allowance. Run lists return a bounded recent window. The policy
also declares the retained-history allowance. Slice 21 now enforces both its
count and age boundaries with bounded cleanup; the Slice 17 checkpoint itself
did not delete history.
Authenticated requests have shared rate limits, with a tighter budget for costly
operations. Open streams have account/global caps and bounded lifetimes; normal
SSE reconnection resumes from the durable cursor. Dependency outages fail closed.


### Reliable paper-run lifecycle (Slice 18)

Retrying a browser launch after a lost response or reload recovers the same run.
A confirmed launch followed by Run bot creates a new run. API clients send a UUID
`Idempotency-Key` for retry safety; omitting it requests a deliberate fresh launch.
Delivery outages retain the queued run for scheduled retry. A lost worker becomes
`interrupted`, keeps committed history and explains that a new run is required.
No paper portfolio or graph execution is automatically restored. Browser reload
and stream reconnect read authoritative PostgreSQL history. Recovery operations
are internal process operations, with no public HTTP route.

## Slice 19: Account recovery and management

Approved September 10, 2026: use a configurable SMTP relay; new accounts must
verify their mailbox before launching runs. Registration still signs in so users
can edit bots, inspect their account and request verification. Existing accounts
retain access without being marked verified; the account page prompts them to
verify. Verification and password reset use a single-use email link with the lifetime in the
[runtime-checked account policy](account-recovery.md),
ask the mailbox owner to choose a new password, revoke every browser session,
and require ordinary sign-in. This also removes credentials chosen by someone
who registered another person's email before ownership was proved.

Account settings provide authenticated password change and revocation of other
or all sessions. Each requires the current password again. Password change and
all-session revocation sign out the current browser; other-session revocation
retains it. Revocation prevents subsequent requests immediately and active SSE
access within the recheck interval in that account policy. Authorized paper runs
continue; explicit Stop remains a separate operation.

Forgot-password and verification requests return the same result for existing,
unknown and already-verified addresses. Each sends the same conditional email
link to the requested address; an ineligible address receives an unusable link.
The interface says to check email without claiming recovery has completed.
Delivery failures return a generic retryable service failure independent of
account eligibility. A relay accepting a message does not guarantee inbox delivery.
Verification is requested explicitly from account settings after registration;
resend uses the same request form and commits a new digest, invalidating the
previous same-purpose link before attempting SMTP. That replacement remains even
if SMTP fails. Requesting a link cannot change password or verification state.

Links are usable only on the configured application origin. The browser removes
the fragment before rendering the form and keeps its token in memory only; reload
requires reopening the email. Missing, invalid, expired and used links have clear
recovery instructions. Passwords and tokens are never saved in browser storage.
Without access to the registered mailbox, forgotten-password recovery is unavailable;
there is no support override, email change, account linking or identity transfer.

## Slice 20: Operations policy

Operators use an OS-authorized maintenance command on the private deployment host;
there is no operator HTTP endpoint or browser role. Account suspension revokes
sessions and recovery links, prevents login/new work, stops queued runs and
interrupts active runs in the same transaction. History remains readable after an
operator resumes the account and the user signs in again. Global incident stop
rejects new launches and interrupts all active work; resume only reopens admission,
never restarts a run. A specific run can also be stopped by its UUID.

The committed terminal transition immediately fences further paper mutations.
Default worker cleanup budget: heartbeat 5 seconds plus cleanup 10 seconds.
The deployed heartbeat setting overrides that default; this bound assumes available
dependencies. Database outages cannot authorize fills.
Operator actions are retry-safe and audited with OS actor, UUID target, action,
outcome and time. Support and operational ownership are the deployment operator
until the release checklist supplies a named public contact.

## Slice 21: Data policy

Approved beta policy: encrypted backups every 24 hours, retained 14 days; recovery point ≤24 hours and isolated restore ≤2 hours; up to 100 terminal runs per account for 30 days; immediate deletion quiescence and eligible erasure within 24 hours; minimal completed deletion receipts and operator audits retained 90 days.

The approved beta policy keeps up to 100 completed runs per account for 30 days,
with active runs preserved. Expired history is unavailable in lists and private
run URLs. Account exposes a password-confirmed deletion request: revoke all access
and stop paper jobs immediately, then erase eligible owner data within 24 hours.
Encrypted daily backups expire after 14 days; minimal operator/deletion receipts
expire after 90 days. The recovery point is at most 24 hours and isolated restore
target at most two hours. Restored accounts stay quarantined until individually
reconciled with current deletion/suspension records; previous jobs never resume.
See [data lifecycle](beta-data-lifecycle.md) for export/support handling and the
explicit public-opening gates.

## Slice 22: Guided first use

After account verification, the empty Bots page links to **Create your first
paper bot**; Account settings also exposes this route. Users choose a
catalog-owned example, select available markets, review conditions and paper
settings, then save a private bot. Back navigation preserves settings. An unknown save result requires checking
existing bots before creating another; it cannot blindly resend the current draft. Saving
never launches; the saved page requires **Run bot** and the existing gates.

Run pages explain simulated cash/equity, loaded orders and fill outcomes,
existing skipped/rejected progress, stale or missing inputs, reconnection and
terminal failures. Conditions may produce no order and no progress entry.
Keyboard step focus, mobile layout, retry feedback and allowance/account links
cover the basic first-use path.

## Slice 23: Launch information and acceptance

Public overview, help, privacy, preview terms and support pages describe only the
delivered visual builder and simulated paper execution. The dashboard, bots,
graphs, runs, events and usage stay private. Anonymous information navigation does
not request account state or preload private resources. Existing authentication
and recovery entrypoints retain their prior boundaries; no public data API is added.

The approved operator/support placeholders are visible as unconfigured, with no
fake mailbox or submitting feedback form. Self-service recovery/help links work.
The public-opening gate remains blocked until a named operator and monitored
support contact replace the placeholders, appropriate service terms/privacy are
reviewed, email and incident ownership are tested, and deployment/backups are
installed. The [release checklist](beta-launch.md) owns final acceptance evidence
and the separate deliberate ingress-opening step. Coding completion does not
publish the service.


## Saved-bot soft deletion

On a saved bot page, **Delete bot** opens an explicit confirmation explaining that
past runs remain. Every run must first be terminal; queued, starting, running,
stop-requested and stopping runs all block deletion. The user stops runs through
the existing run controls and retries deletion after they finish.

Confirmed deletion hides the configuration from the workspace and graph-copy
choices and prevents further edits or launches. The bot row and run snapshots
stay in the system. Old runs, their executed graphs and events remain visible to
their owner under the existing retention policy, with a deleted-configuration
label on run detail. Deleted bots no longer consume the visible saved-bot allowance.
Account erasure still removes retained bot data through its established lifecycle.
