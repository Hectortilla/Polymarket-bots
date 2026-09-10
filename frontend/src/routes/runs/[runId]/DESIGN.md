# Run detail design

## Visual theme and atmosphere

A restrained monitoring screen for bot operators. Preserve the application's
existing dark theme, Geist typography, and flat structural dividers. Prioritize
financial observation over setup details. DESIGN_VARIANCE: 3,
MOTION_INTENSITY: 2, VISUAL_DENSITY: 7. These values adapt the requested
Design Taste and Stitch guidance to a working data interface; marketing heroes,
photography, decorative animation, and a new component framework do not belong
on this surface.

## Color palette and roles

Use the existing semantic tokens in `src/app.css`, which own the values:

- Canvas (`#0b0e0c`): page background.
- Surface (`#101411`): chart plotting areas.
- Primary text (`#f1f4f2`): headings and controls.
- Secondary text (`#bbc3be`): readable values and supporting labels.
- Muted text (`#858f89`): timestamps and context.
- Accent (`#afc4b8`): interaction emphasis and focus.

Preserve existing chart series and status colors because they encode data,
including stale valuations and failures. Do not introduce decorative accents.
This page inherits the application's dark theme rather than introducing a local
theme switch or changing the rest of the product.

## Typography and components

Use Geist Variable for headings and labels, Geist Mono Variable for numeric
values, timestamps, and chart controls. Section titles use 1.15rem, weight 600.
Use 8px surface corners and 5px control corners from the existing token scale.
No elevated cards around sections; chart surfaces alone have a quiet border.
Section headers share a 76px minimum height. Interactive targets are at least
44px high with visible keyboard focus. Existing errors and loading/empty states
remain contextual and readable.

## Information hierarchy and layout

Keep a compact run name, lifecycle status, saved-bot link, and stop action above
a two-tab strip. Tabs use 48px targets, 18px Phosphor icons, muted inactive text,
and a restrained accent underline for the active view. No pill containers or
extra page headings. Tab panels have 20px top separation, 12px on mobile.

- **Live data**, initially selected: executable equity, market prices or
  followed-wallet activity, Events, then timing. Timing stays with live data
  because heartbeat and end time can change during the run.
- **Configuration**: executed strategy graph (when present), then immutable
  configuration in the builder's field order. Both sections initially expanded;
  entering the tab should immediately reveal the saved content. Use compact
  64px section headers here.

Equity and market charts remain expanded within Live data. Shared time navigation sits above
equity; the market/wallet view toggle sits beside the second chart title.
The equity plot is 300px high and the market plot 460px high on desktop.

Events starts closed on each visit, with a compact right-side toggle and loaded
progress-event count. Opening it changes the chart column's available width and
reveals a 360px drawer, reduced to 300px on smaller desktop widths. The drawer
contains stream health, pagination, and a vertically scrolling event list.
The drawer stays within the viewport while scrolling the charts. Failure detail
expands inside its event row on hover or keyboard focus, without clipping outside
the scroll container. Chart samples are excluded from the progress-event list.

Below 768px, Events becomes a full-width disclosure beneath the charts. All run
section layouts fit one column; event scrolling is bounded to 560px. Charts use
260px (equity) and 380px (market) heights. No horizontal page scrolling.

## Disclosure and motion

Timing, the executed graph, and configuration start open. Each uses
the same accessible disclosure header with an expansion indicator,
`aria-expanded`, and a controlled content ID. Their states are independent.
The Configuration panel mounts on its first visit, then stays mounted while
hidden to preserve graph navigation and disclosures. Reopening a collapsed graph
mounts it into a visible viewport so its existing automatic fit behavior works.
The live panel stays mounted, preserving chart zoom, selected view, wallet page,
and the Events disclosure. Hidden charts ignore shortcuts and pause option updates;
stream ingestion continues. Tabs have tablist/tab/tabpanel semantics, one tab stop,
and arrow/Home/End navigation with automatic activation.

Layout resizing is immediate, with ECharts' existing ResizeObserver updating the
plots. Do not animate width or height, pulse numeric data, or stagger live rows.
Use the existing restrained hover/focus feedback. No motion dependency is needed.

## Anti-patterns

Avoid nested card shells, oversized headings, decorative numbering, generic
marketing copy, fabricated values, perpetual motion, and new palette families.
Do not hide primary financial information behind disclosures or reuse an
unavailable/stale estimate as a fresh valuation.
