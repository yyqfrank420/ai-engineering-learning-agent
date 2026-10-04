# Workspace design

The frontend is an operating and reading surface for people who can code and are
learning AI architecture. Preserve the split conversation and D3 diagram workspace,
its editing workflow, history, and existing product identity.

## Visual system

Use the semantic tokens in `frontend/src/index.css`. Charcoal surfaces distinguish
navigation, conversation, canvas, and overlays. Violet identifies actions and focus.
Graph component colors retain their architectural meaning. Error and connection
status colors communicate state.

Geist Variable is self-hosted through Fontsource, with a system fallback. Use 15px
conversation text, 14px inspector body text, and 13px secondary content where space
allows. Use monospace for code and measurements. Keep explanation measure at 72ch.

Controls use 6px corners, fields and grouped surfaces use 10px, and larger message
surfaces use 14px. Circular jump controls are the small-control exception. Keep
opaque surfaces; reserve shadows for floating overlays. Avoid gradient text, glowing
status dots, and decorative backdrop blur.

## Interaction and layout

The desktop header is 48px high and the history rail is 240px wide. Preserve the
existing stacked workspace at 1023px and below. Diagram editing remains available.
Use dynamic viewport height and scroll within the individual panes.

Every action has a readable disabled state and immediate visible keyboard focus.
Use at least 36px compact controls, 44px primary composer controls, and larger touch
targets for coarse pointers. Deletion retains explicit confirmation, with keyboard
focus held inside the confirmation and restored to its trigger on cancellation.

Keep motion brief and purposeful. Frequent navigation and keyboard actions are
instant. Respect reduced motion. Use Phosphor for newly changed interface icons.

## Boundaries

Keep product claims, provider notices, activity, sources, and errors truthful.
Preserve the book badge until product naming and attribution prominence are decided.
Frontend presentation changes do not change generation, retrieval, authentication
services, database storage, or diagram topology.
