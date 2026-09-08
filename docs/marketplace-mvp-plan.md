# Bot Marketplace MVP — Slice 16

Status: proposed implementation plan, September 8, 2026. No marketplace code or
migration is implemented by this document. Depends on completed Slices 13–15;
Slice 12F deployment and live-trading slices are not prerequisites for local work.

The user confirmed **visual node bots only** and **signed-in browsing**. All
other choices below are recommended MVP design decisions for review, not claims
of previously approved policy. This document owns the proposed marketplace
design; [Slice 16](implementation-plan.md#slice-16-bot-marketplace-mvp) owns
delivery order and acceptance. Existing product and architecture contracts remain
authoritative for implemented behavior. Resolve changes to these proposed choices
before implementing the affected sub-slice.

## Product outcome and scope

An author publishes a saved strategy. Another account finds it, inspects the
graph and suggested configuration, and saves an independent private copy.
The recipient can edit that copy and explicitly start a paper run through the
existing bot workspace. Publishing and copying never launch a run.

Here, public means shared with all authenticated accounts inside the existing
private application boundary. It does not mean anonymous access or an Internet
deployment. The MVP is a free strategy library: no purchases or subscriptions.

| Include in MVP | Defer |
| --- | --- |
| Publish saved visual node bots | Python uploads, packages, user-supplied code execution |
| Browse, title/description search, newest-first pagination | Recommendations, popularity ranking, categories and tags |
| Listing detail with graph and suggested paper settings | Public run history, returns, leaderboards or verified performance |
| Independent private copies with source attribution | Auto-updates, merging upstream changes, copying live trades |
| Explicit publication versions and unpublish | Ratings, comments, follows, payments, creator dashboards |
| Publisher alias entered during publication | Profiles, unique handles, verified identities, social login |
| Existing account and paper execution boundaries | Anonymous browsing, public hosting, moderation platform |

MVP success is behavioral: two accounts complete publish → discover → inspect →
copy → edit → paper run, while neither can access the other's private resources.
Use acceptance tests and a small private pilot; no analytics service is required.

## User journeys

### Publish and maintain a listing

1. From an owned saved node bot, select **Publish to marketplace**. Save pending
   edits first; publication must never silently combine unsaved browser state
   with a different server revision.
2. Enter a title, a short plain-text description explaining the strategy, and a
   publisher alias. The alias is a display label, not a unique or verified identity;
   it is never derived from the account's email. No profile table is needed.
3. Review the exact graph, parameters, and suggested paper configuration that
   other accounts will receive. The public configuration name uses the listing
   title, not the private bot name. Explain that literals, addresses, market
   references, and other text inside the graph are shared too. Do not attempt
   automatic redaction that could change strategy behavior.
4. Confirm sharing this snapshot for other users to inspect, copy, modify and
   republish within the app. This is product consent, not a new legal license.
   The backend verifies ownership and that the preview still matches saved state.
5. Publication creates version 1 and opens its detail page. Each source bot has
   at most one listing; saving the private bot later does not change the listing.
6. **Publish update** creates another immutable version after the same review.
   Metadata changes also create a version, so previously copied versions retain
   their title, description, alias and payload. No automatic update notifications.
7. **Unpublish** hides the listing and prevents new reads/copies by other accounts.
   It neither deletes existing copies nor stops their runs. Republishing restores
   visibility, optionally with a new version. There is no hard-delete workflow.

### Browse and copy

1. The authenticated shell adds **Marketplace** alongside **My bots**. The listing
   page shows title, description excerpt, alias, version and publication date.
   Search covers current published title/description; **My publications** also
   shows the signed-in author's unpublished listings.
2. Detail shows a read-only graph, its parameter values, suggested markets and
   paper settings, and **Copy to my bots**. It exposes no publisher runs or equity.
   Render text without raw HTML, embeds, remote images, or fetched URLs.
3. Copy opens a configuration review using the existing bot form, prefilled from
   the selected version. The recipient chooses a private bot name and can replace
   markets or paper settings. Save copies that exact published graph; graph edits
   happen afterwards in the normal private editor.
4. On save, validate all selected markets as new selections through the existing
   discovery boundary. Old/closed/unavailable markets require replacement; an
   infrastructure failure shows the existing unavailable outcome and creates no
   bot. Viewing a listing itself does not require market discovery.
5. Create the recipient's bot, its own graph revision 1 and source attribution in
   one transaction. Open the private bot workspace without starting execution.
6. Display **Copied from [title], version N** on the owned copy. Its lineage is
   informational: it grants no access to the author's bot. If the source is
   unpublished, keep the attribution text but show the listing as unavailable.

Old copies stay independent after source edits, updates or unpublishing. A user
may deliberately create multiple copies; retrying one save must create only one.
Republished copies show their immediate source attribution when available;
recursive ancestry browsing and update propagation are deferred.

## Existing implementation to reuse

| Existing owner | Marketplace use |
| --- | --- |
| `api.auth` | Current user, mandatory authentication, CSRF, no-store responses |
| `api.bots` | Private bot ownership, bot locks, append-only graph revisions |
| `api.catalog.inputs.NodeBasedLaunchInputs` | Validate recipient settings and produce `PaperRunConfig` |
| `api.catalog.graphs` | The existing typed graph, node catalog and graph validation |
| `api.http.routes.bots.market_validation` | Validate new market selections before saving a copy |
| `api.runs` and `api.execution` | Existing explicit paper launch, snapshots, history and streams |
| Frontend bot form and graph components | Configuration review, read-only graph and subsequent editing |

The node definition currently accepts explicit market slugs, not the wallet-input
contract used by other catalog definitions. Do not expand its inputs for this
marketplace. `PaperRunConfig` and launch inputs have different shapes: use the
existing configuration-to-form mapping where available, and one explicit backend
projection into `NodeBasedLaunchInputs` for publication. Never pass persisted
config JSON directly as launch inputs or publish an unrestricted `BotRead`.

## Proposed persistence and contracts

Keep marketplace persistence and application behavior in `api.marketplace` and
its HTTP routes. Nothing here requires a `polybot` change, queue, search service,
object store, new runtime or SDK dependency. Create focused modules only as their
sub-slice needs them, following the architecture's field and abstraction budgets.

Use a forward Alembic migration after the current head; preserve all accounts,
bots, templates, revisions and runs. Do not rewrite 0005 or reuse its reset policy.

| Record | Minimum data and present consumer |
| --- | --- |
| Marketplace listing | UUID, unique private source bot FK, published/unpublished state, integer edit version, created/updated timestamps. The owner inherits through the source bot; owner management and conditional writes consume these fields. |
| Marketplace release | UUID, listing FK, positive sequential version, source graph revision FK, title, description, publisher alias, validated graph JSON, validated suggested node inputs JSON, publication timestamp. Detail/copy consume the payload; preview consistency uses the private source reference. |
| Marketplace copy | Target bot FK as primary key, source release FK, client request UUID and canonical request digest. Private attribution consumes provenance; retries consume the request claim and digest. Owner inherits through the target bot. |

Enforce unique `(listing_id, version)` and source graph revision membership in the
listing's source bot. Readers derive the current release as the highest version;
there is no redundant current-version pointer or mutable release payload. A listing
exists only after first publication and always has a release, created atomically.
Use database constraints where possible and serialize writes under the owning bot
and listing locks in one documented lock order. No ownership transfer or cascading
deletion of copies is introduced.

A successful copy request UUID is globally unique in the copy table. Only the
owning recipient can replay its result; another account using the same UUID gets
a generic conflict without a target ID. Compare the normalized request digest so
reusing a key with different source/settings returns conflict. Retain the receipt
with the bot. A deliberate new copy uses a new UUID. Concurrent identical saves
converge on one committed target; failed transactions leave no bot or claim.

Public listing DTOs are explicit projections: listing/release IDs, version,
publication metadata, graph and suggested inputs, plus immediate public source
attribution for a republished copy. List DTOs omit graph/config payloads. Never
expose source bot/revision IDs, internal user IDs, email, credentials, sessions,
private config names, run IDs, events, logs or performance. Separate owner-management
DTOs can include the source bot reference and conditional-write fields.

Public source attribution must not join through unpublished listing data. An
owned copy can still read the immutable title/version of its own source release;
republishing it must not expose additional hidden source metadata. At minimum show
an unavailable-source label once that upstream listing is unpublished.

Proposed new text limits: title 1–80, description 1–2,000, alias 1–40 characters,
trimmed; search at most 120 characters; list size defaults to 20 and caps at 50.
Keep these values in a narrowly owned policy contract and export relevant schema
constraints to the frontend. Reuse existing graph limits. Set an explicit request
byte limit for marketplace mutations in 16A from their bounded metadata and node
input contracts; graphs are read from storage, not uploaded by these routes.
Reject oversized input before expensive parsing. Do not silently
truncate text or introduce per-account execution quotas in this slice.

## Proposed API and consistency rules

All paths below are relative to `/api/v1`. Every endpoint requires the existing
session; mutations use existing same-origin JSON/CSRF protection. Do not alter the
anonymous allowlist or broaden any private bot/template/run route.

| Method and path | Behavior |
| --- | --- |
| `POST /bots/{bot_id}/publication-preview` | Owner-only; accept proposed metadata and return the exact candidate payload plus a deterministic fingerprint. Read-only despite POST. |
| `POST /bots/{bot_id}/publication` | Create listing/release 1, or append a release, from owned saved state. Require the preview fingerprint and expected listing edit version (absent on first publication). |
| `GET /marketplace/listings` | Published current releases only; bounded `q`, cursor and limit. |
| `GET /marketplace/listings/{listing_id}` | Current published release, including exact copyable release ID. |
| `GET /marketplace/publications` | Current user's listings, including unpublished entries and management fields. |
| `GET /marketplace/publications/{listing_id}` | Owner-only detail for managing an unpublished or published listing. |
| `PATCH /marketplace/publications/{listing_id}` | Owner-only visibility change with expected edit version. Metadata changes go through publication review. |
| `POST /marketplace/listings/{listing_id}/copies` | Exact release ID, recipient node inputs and copy request UUID; returns the newly owned `BotRead` with safe source attribution. |

Compute the preview fingerprint from the selected source revision, the projected
saved configuration and submitted publication metadata. On publish, lock and
re-read the owned source, recompute and reject changed state with `409`. The
fingerprint is a consistency check, never authorization. First publication is
protected by source uniqueness; concurrent/retried updates with a stale edit
version return `409` and the frontend reloads owner state before retrying.

Copy accepts only a release belonging to the requested listing. An older version
that the user already inspected remains copyable while its listing is published;
there is no public version-history browser in the MVP. Never substitute the latest
version silently. Revalidate graph compatibility at the persistence/catalog
boundary before copying; incompatible historical payloads cannot create a bot and
produce a stable unavailable/unsupported result instead of a fallback strategy.

After validating request shape, check for an already-committed owned copy receipt
before market discovery; a matching retry returns that bot even if the original
markets have since closed. For a new request, validate recipient inputs and market
availability before the short write transaction; then lock/recheck publication
visibility and atomically persist the copy. Recheck the request claim inside the
transaction to handle concurrent retries. Define visibility at that transaction's serialization point: an unpublish
that wins the lock blocks a new copy; an already-committed copy survives. A retry
of a successful request may return its own existing bot even after unpublishing.

`BotStore.create()` currently commits internally. Introduce only the transaction
ownership change needed to compose bot + initial revision + copy record under one
commit, preserving existing create callers. Do not orchestrate a new marketplace
copy as separate browser calls to create a template and then a bot. No template
row is required for a published copy.

Use `401` for unauthenticated calls, indistinguishable `404` for missing or
inaccessible resources, `409` for state/request conflicts, and existing structured
validation/unavailability responses where appropriate. New stable reason values,
paths and DTOs have one backend owner and generated frontend contracts.

Implement newest-first ordering by current release publication timestamp and
listing UUID as a tie-breaker, using an opaque validated cursor. Use parameterized
PostgreSQL search over current title/description; no external search dependency.
Release updates can move an item between pages: document refresh semantics and
deduplicate visible listing IDs. Do not claim a snapshot-consistent feed.

## Verification and release gate

Test at the boundary where each failure could occur:

- Real PostgreSQL: upgrade with populated Slice 15 accounts; uniqueness and
  immutable releases; publication/edit races; transaction rollback; same-key
  concurrent copy saves; unpublish/copy races; source/target independence.
- API with accounts A/B: B sees only A's published DTO, cannot use A's private
  IDs, cannot publish/manage A's bot, cannot spoof ownership, and cannot read
  A's runs/SSE after copying. Test nested foreign release IDs and hidden listings.
- Input/contract: preview drift; unsupported graphs; bounded and escaped text;
  stale markets versus discovery outage; no payload leaks; generated schemas,
  response validation and route-inventory authentication tests.
- Browser with real auth/storage: A publishes; B searches, inspects, reviews and
  copies; B edits and explicitly runs; A publishes an update then unpublishes;
  B's saved copy/history remain intact. Include refresh, duplicate save, empty
  search, failed save, expiry and account switching during publication/copy.

Run from the repository root for the delivered slice:

```sh
uv run pytest
npm --prefix frontend run generate:check
npm --prefix frontend run check
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

Use the separate disposable PostgreSQL/Redis test services and browser settings
documented in README. Service-dependent acceptance must pass without skips. After
API changes regenerate with `uv run python -m api.http.openapi` and
`npm --prefix frontend run generate` before checking the generated artifacts.

All of 16A–16E must pass before calling the MVP complete. Retain the private
deployment boundary. Internet exposure requires a separate decision and plan for
abuse handling, account recovery, publishing/copy limits, operational capacity and
content takedown; authentication alone does not deliver that deployment work.

This plan introduces no Polymarket protocol, endpoint, fee or transport change.
It references the existing market validator without redefining exchange behavior,
so no PolymarketDocs check is required for this planning change. If implementation
requires changing market discovery or any protocol behavior, consult that MCP
first and stop that work if unavailable, following AGENTS.md.

Planning documentation-drift audit: source ownership, revision and copy behavior
were checked against the working-tree Slice 15 implementation, including its
uncommitted changes. README, product/architecture pointers and the main slice plan
distinguish this proposal from delivered functionality. Before delivering each
implementation sub-slice, reconcile its adopted product/technical contract with
the control-plane spec/architecture and update generated contracts where changed.
