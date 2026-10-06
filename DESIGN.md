# Workspace design

The frontend is an operating and reading surface for people who can code and are
learning AI architecture. Preserve the split conversation and D3 diagram workspace,
its editing workflow, history, and existing product identity.

## Visual system

Use the semantic tokens in `frontend/src/index.css`. Preserve the purple-blue
gradient brand and ambient radial backdrop. Translucent navigation and conversation
surfaces expose that backdrop. Violet identifies actions and focus.
Graph component colors retain their architectural meaning. Error and connection
status colors communicate state.

Geist Variable is self-hosted through Fontsource, with a system fallback. Apply the
new typography only to the visible workspace and sign-in surface. Keep body
typography unchanged because private diagram evaluation inherits it for SVG
measurements. Use 15px conversation text, 14px inspector body text, and 13px
secondary content where space allows. Use monospace for code and measurements. Keep explanation measure at 72ch.

Controls use 6px corners, fields and grouped surfaces use 10px, and larger message
surfaces use 14px. Circular jump controls are the small-control exception. Keep the
branded gradient title and primary controls. Use the existing glass surfaces and
backdrop blur while preserving readable text and visible focus.

## Interaction and layout

The desktop header is 48px high and the history rail is 240px wide. Below 1280px,
the header has a minimum height of 56px and history opens as a modal. Panes sit side
by side when the measured workspace width is at least 960px. Below 960px, full-height
Chat and Diagram tabs share the workspace. Diagram editing remains available. Use
dynamic viewport height and scroll within the individual panes.

Header navigation and history share an icon column and a text column. Use a 24px
screen-edge inset on desktop and 16px in compact layouts, with a 12px gap after
the icon column. Keep header actions evenly spaced.

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
