# Design System: Polybot supporting pages

## 1. Visual theme and atmosphere

A compact operator interface, derived from the existing home dashboard. This is
an evolution of the product, preserving its identity and workflow. Use the existing
Svelte components and native CSS, Geist fonts and Phosphor icons. No new UI system
or animation dependency is needed.

DESIGN_VARIANCE: 3. MOTION_INTENSITY: 2. VISUAL_DENSITY: 7.

Scope: `/login`, `/register`, `/forgot-password`, `/reset-password`, `/verify-email`,
`/account`, `/start`, `/welcome`, `/help`, `/support`, `/terms`, `/privacy`.
The home dashboard, bot editor and run pages retain their own existing layouts.

## 2. Color palette and roles

Consume the semantic tokens in `src/app.css`; do not duplicate these values in
page styles. The established product theme is dark throughout, including when the
OS prefers light. Preserving the user's dashboard reference takes priority over
introducing a separate light theme on supporting pages.

- **Forest canvas** (#0B0E0C): page background, `--canvas`.
- **Quiet surface** (#101411): forms and grouped controls, `--surface`.
- **Raised forest** (#151B17): selected navigation and options, `--surface-raised`.
- **Input well** (#0D110E): editable fields, `--surface-input`.
- **Primary text** (#F1F4F2): headings and selected state, `--text`.
- **Secondary text** (#BBC3BE): body copy and labels, `--text-soft`.
- **Muted text** (#858F89): metadata and inactive navigation, `--text-muted`.
- **Sage accent** (#AFC4B8): selection edges and focus, `--accent`.
- **Action surface** (#D0DAD3) with **action ink** (#18211C): primary buttons.
- **Soft danger** (#E1A6A0): errors and destructive controls only.
- Preserve the existing lime brand mark (#C7E76B); do not spread it across controls.

Structural dividers use `--line`; editable controls use the higher-contrast
`--control-line`. Status colors convey actual state, never decoration.

## 3. Typography

- Self-hosted Geist Variable for all interface text.
- Geist Mono Variable for account identifiers, numeric settings and list markers.
- Page titles: 24-28px (1.5-1.75rem), weight 610, line height 1.2-1.25.
- Authentication titles: 24px (1.5rem).
- Section titles: 15-16px (0.9375-1rem), weight 600.
- Reading text: 14px (0.875rem), line height 1.6-1.65, maximum 65ch.
- Controls and navigation: 13px (0.8125rem), with 44px minimum control height.
- Inputs: 14px desktop, 16px mobile to avoid focus zoom.
- Metadata: 12-13px. Never use metadata styling for essential instructions.

Use size sparingly. Weight, alignment and grouping establish hierarchy. No
oversized promotional headings, decorative uppercase eyebrows, serif accents,
gradient text or arbitrary font changes.

## 4. Components

Global header: every route uses the homepage header from `src/routes/+layout.svelte`.
The brand always links home; Help is always available. Support remains in the
public information navigation, not the global header. A known
signed-in session adds the account email, Account settings and Sign out. Otherwise,
show Sign in in the same navigation. Do not switch header variants by route.
Public pages retain the existing no-preload/no-session-polling boundary; a cold
public visit does not probe for an account. Sign-out failures remain visible and
retryable without hiding public content.

Authentication: a 400px maximum-width surface with 28px desktop padding,
24px mobile padding (20px on small phones), 8px radius and a fine border.
Use a separated footer for switching between registration and sign-in.

Forms: visible labels above fields, 8px label gaps, 44px controls, 5px radii.
Retain field order, autocomplete, password requirements and existing inline
failure/success states. Checkbox labels use a horizontal alignment and natural
wrapping, never a full-width checkbox. Primary actions use the existing pale
sage fill; session actions are secondary; deletion uses the danger treatment.

Account settings: 960px maximum width. Sections pair a heading/explanation with
controls in a second column, separated by real structural dividers. Deletion
retains all consequences and the explicit confirmation checkbox.

Public information: a shared navigation rail and a readable article. Selected
navigation uses a quiet surface, a fine accent edge and `aria-current`. Contact
readiness is a restrained notice; never imply an unconfigured mailbox works.

Guided setup: reuse account usage, preserve the three-step flow and keyboard
focus transfer, show the current stage with an accent edge. Selectable examples
have clear native radios, muted descriptions and a distinct checked state.
Skeletons match the example rows while loading. Keep the settings form mounted
when moving between steps so user input persists.

## 5. Layout

Public information uses a 168px navigation rail, 48px gap and an article up to
720px within a 1000px container. Section rhythm is 24px; account section rhythm
is 28px. Use 1px dividers only where content groups change.

Below 768px, columns collapse. Public navigation becomes wrapping horizontal
links, setup progress becomes a vertical list, and account controls follow their
descriptions. No fixed widths that overflow 320px viewports. Keep focus rings,
44px buttons and the existing skip link.

## 6. Motion and interaction

Use existing 180ms hover and press feedback. No automatic reveals or perpetual
motion: these are task-focused product pages. Respect the global reduced-motion
and reduced-transparency rules. No scroll listeners or animation dependencies.

## 7. Anti-patterns and deliberate scope choices

No decorative imagery, fake dashboard previews, inline headline photos, neon,
large shadows, marketing cards, fake metrics or decorative status dots. The
requested skills' landing-page imagery and perpetual-motion defaults do not fit
these product, help and legal surfaces. No new light theme, brand redesign,
route renames, form-field reorder, or legal/consent copy changes.

## 8. Audit and verification

Before: public headlines reached 60.8px, introductions were 18.4px and sections
had 40px margins. Auth headings inherited the 44px global display scale. Account
settings stacked every concern in one narrow column. Setup used a plain numbered
progress list. The dashboard already supplied the appropriate fonts, palette,
radii, fine borders and compact hierarchy.

After: scoped supporting-page styles align these surfaces with that dashboard.
Public titles and descriptions, route slugs, primary navigation labels and all
legal text remain intact. Public navigation retains its no-preload boundary.
No API, authentication, run, market-data or trading behavior changes are intended.
The Stitch-inspired semantic specification here documents the implemented local
system; no remote Stitch generation or external design upload is required.

Validate with `npm run check`, `npm test`, `npm run build` and `npm run test:e2e`
from `frontend/`. Inspect desktop and mobile layouts, recovery errors, account
settings and each setup step. The existing browser suite covers public resource
isolation, account lifecycle, recovery and guided paper runs. Review every
supporting route for horizontal overflow and visible action labels.

Acceptance audit (2026-09-18): 419 frontend tests and 12 browser scenarios passed;
Svelte diagnostics reported zero errors or warnings and the production build
passed. Visual checks covered desktop, 390px mobile and 320px narrow layouts,
including recovery errors and destructive controls. No horizontal overflow was
observed. A production mobile Lighthouse run of `/welcome` scored performance 93,
accessibility 100 and best practices 100. Its simulated LCP was 2.9s, above the
2.5s target; this is a lab measurement, not field Core Web Vitals certification.

Final documentation-drift audit: route/content contracts and the implementation
plan remain accurate. This is a presentation-only refinement of existing pages,
not a new numbered implementation slice. Authentication, public-resource
isolation, legal copy, operational limits and trading gates are unchanged. No
Polymarket protocol work or MCP verification was needed. Existing dark-only
branding is an intentional preservation choice.
