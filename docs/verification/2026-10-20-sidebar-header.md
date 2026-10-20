# Sidebar header refinement

Based on main 356108a5c55a3e4f83e5772d0baddee08d0373dc.

The user compared the sidebar with a compact chat navigation reference. The heading
was indented by the full reserved icon column, and transient startup copy wrapped
into two lines. The refinement uses a left-aligned Chats heading, a compose icon
with the visible New chat action, a 24px icon column and a shorter Connecting label.
The sidebar surface is quieter. Existing history entries, API calls, readiness
predicates, disabled controls, deletion and modal focus behavior are preserved.

## Verification

- Existing sidebar suite: 34 tests passed. Scoped ESLint passed.
- TypeScript and production build passed. Layout detector and whitespace checks are clean.
- CI policy suite: 504 passed, 5 skipped; manifest validation passed.
- Chrome local fixture imports the actual component, CSS and workspace tokens. It
  uses synthetic local authentication and mocked thread data, with no provider calls.
- Desktop at 1728px: heading and action begin at the 24px inset. Long titles use
  ellipsis, the sidebar has no horizontal overflow and keyboard focus is visible.
- Mobile at 390x844: native modal drawer, 16px heading inset, 44px close control, no
  horizontal overflow, close autofocus and Escape dismissal verified. Existing
  coarse-pointer CSS retains a 44px New chat target.
- Browser warning/error log is empty. Temporary viewport emulation was cleared.
- Presentation review is pinned to the exact sidebar blob pair in ci/quality.json.
  No generation, transport, retrieval, storage or private diagram rendering changes
  are included. No paid generation evaluation is required for this refinement.
