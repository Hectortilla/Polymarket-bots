# Design System: Polybot Operator Workspace

## 1. Visual Theme and Atmosphere

Polybot is a calm technical workspace for one trusted operator. It should feel
precise, quiet, and dependable, like a well-designed development tool rather
than a trading spectacle.

- **Design variance: 5/10.** Layouts use clear structure with modest asymmetry
  in page headings and editor composition.
- **Motion intensity: 4/10.** Motion communicates loading, state changes, and
  interaction feedback. It never competes with market or run information.
- **Visual density: 6/10.** The bot list and run views support quick scanning,
  while configuration fields and the graph canvas have enough room to work.
- Use one dark theme across the product. Do not invert individual sections.
- Prefer structural lines and spacing over collections of floating cards.

## 2. Color Palette and Roles

- **Night Canvas** (`#0B0E0C`): application background.
- **Workspace Surface** (`#101411`): grouped controls and primary work areas.
- **Raised Surface** (`#151B17`): graph nodes, menus, and selected rows.
- **Input Surface** (`#0D110E`): inputs, text areas, and select controls.
- **Primary Ink** (`#F1F4F2`): headings and essential values.
- **Secondary Ink** (`#BBC3BE`): body copy and labels.
- **Muted Ink** (`#858F89`): helper text, timestamps, and inactive metadata.
- **Quiet Line** (`rgba(235, 244, 239, 0.10)`): section structure.
- **Strong Line** (`rgba(235, 244, 239, 0.18)`): control boundaries.
- **Signal Lime** (`#C7E76B`): the only accent, used for primary actions,
  active controls, connections, and focus rings.
- **Danger Rose** (`#E1A6A0`): destructive actions and errors only. It is a
  semantic status color, not a competing brand accent.
- **Warning Sand** (`#D1BA82`) and **Success Sage** (`#91BDA5`): semantic run
  states only.

Never use pure black, neon glows, purple gradients, or unrelated accent colors.

## 3. Typography Rules

- **Display and body:** Geist Variable. Headings use tight tracking and moderate
  scale. Product hierarchy comes from weight, spacing, and contrast.
- **Code and operational values:** Geist Mono Variable. Use for revisions,
  timestamps, IDs, graph handles, and numeric telemetry.
- Body text uses relaxed line height and stays within 65 characters where it is
  prose.
- Do not use serif type in this software UI.
- Avoid all-caps micro-labels except true table column headers.

## 4. Information Architecture

- The primary destination is **Bots**.
- The operator never chooses a bot type. Every visible bot is node-based.
- The bot catalog is not part of the user interface.
- Graph templates are not a user-facing resource or destination.
- **New bot** opens one builder containing configuration and strategy graph.
- A graph starts clean or copies the latest graph from another configured bot.
- Existing bot detail uses the same builder model and one save action.
- Run detail is a historical snapshot and never appears editable.

## 5. Component Styling

- **Buttons:** 10px radius, minimum 44px target, flat fill or quiet outline.
  Primary buttons use Signal Lime with dark text. Active feedback translates
  down by 1px and scales to 0.98.
- **Surfaces:** 14px radius when a boundary is necessary. Most sections use a
  top rule and whitespace instead of a card.
- **Status badges:** full-pill shape is allowed only because status is a compact
  semantic token. Do not use pills for ordinary labels.
- **Inputs:** labels above controls, helper text beneath the label, errors below
  the control. Inputs use 10px radius and a visible lime focus ring.
- **Bot list:** one responsive structured list with column headers on wide
  screens and labeled stacked values on narrow screens. The row is the target.
- **Run history:** a compact table with responsive stacked rows below 768px.
- **Graph canvas:** a large bounded workspace. Node addition and viewport
  controls remain close to the canvas. Graph validation stays beside it.
- **Loading:** skeletons match the final page structure. No circular spinners.
- **Empty state:** explain what is missing and include the next valid action.

## 6. Layout Principles

- Use CSS Grid for bot rows, configuration fields, run summaries, and page
  composition.
- Contain pages at 1240px with 32px desktop gutters and 16px mobile gutters.
- Page headings are left aligned. The sole primary action sits at the upper
  right on wide screens and becomes full width on mobile.
- Multi-column layouts collapse to one column below 768px.
- Never allow horizontal page scrolling. The graph canvas may pan internally.
- Keep the sticky application header at 64px or less.
- Every interactive control has at least a 44px touch target.

## 7. Motion and Interaction

- Use a 180ms ease-out transition for hover, focus, and selection feedback.
- Page content may enter once with a small opacity and vertical transform.
- Skeleton shimmer communicates loading only.
- Animate only transform and opacity.
- Honor `prefers-reduced-motion` and collapse transitions to effectively instant.
- Do not add perpetual animation to inactive UI. Live status may pulse only when
  it conveys a real running state.

## 8. Responsive Behavior

- Below 768px, bot list column headers disappear and each value receives a
  visible contextual label.
- Builder sections become a single column, and primary actions span the width.
- The graph canvas keeps a useful minimum height without forcing page overflow.
- Run detail summary panels stack vertically.
- Typography uses `clamp()` and never forces headings beyond two or three short
  lines.

## 9. Anti-Patterns

- No bot catalog or bot-type chooser.
- No standalone template navigation, template library, or template editor.
- No three-equal-card dashboard layout.
- No nested cards, glass panels, outer glows, or decorative gradients.
- No pure black or pure white.
- No emojis, decorative status dots, fake version labels, or filler copy.
- No generic marketing language such as “elevate,” “seamless,” or “unleash.”
- No centered marketing hero.
- No hidden placeholder labels or placeholder-only form labels.
- No custom cursor, scroll cue, or gratuitous animation.
- No em dash or en dash in visible copy.

