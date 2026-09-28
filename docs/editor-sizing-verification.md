# Editor sizing verification

Verified on 2026-09-28 using the current App and components with an isolated dev/local fixture transport. The fixture served a saved 7-node, 11-edge RAG graph and a selectable assistant paragraph. It imported no application backend or provider client. No model calls or production writes occurred.

The tested base was `e07070f5b5266f538c86678384d7785291cf11cb` with the uncommitted sizing changes. The browser actions and measurements below were recorded by the parent agent through CUA.

## Browser evidence

The fixed App ran at an actual 1280x720 browser viewport with a 328px composer. The connection panel's "Edit connection" button measured 115.15625x36px, kept its label on one line, and opened the correct connection Label editor.

The empty textarea measured 39px high with a 37px scroll height before selection, after highlighting the assistant text, and after activating "Referenced". An eight-line draft grew to the 120px limit with a 184px scroll height. Clearing the draft using the keyboard restored the 39px height.

A scratch Vite pre-transform then loaded the base revision's ChatInput.tsx and D3Graph.css into the same App. The old connection buttons measured 36x36px with `white-space: normal`, and their text wrapped. The old selection test ran at a changed actual viewport width of 1015px with a 937px composer. Its textarea did not expand in that wider composer. This run did not reproduce the old selection-height defect.

## Tested identities

SHA-256 of the fixed files:

- `frontend/src/components/Chat/ChatInput.tsx`: `e63cf8f5b5ab09d13582505804568d0d4c01727f63a1e3d0d156ff15f0810df2`
- `frontend/src/components/GraphCanvas/D3Graph.css`: `3c0b31b74386dd69faebebdfedd3a992cb2cde46a586197e3d3e22a96621b75d`

SHA-256 of the base files used for the old comparison:

- `frontend/src/components/Chat/ChatInput.tsx`: `cbeec4c551eadc257ddfddd8cbbc4fc5f0200f8b1ff1af5bc3c9c82a68e09ca9`
- `frontend/src/components/GraphCanvas/D3Graph.css`: `0d82695e558870c7367a69c8423edfc6bdd6d147724bb558a905cb2862b7c87f`

The saved graph input SHA-256 was `93ec5dc04c444ee3a4db31cfda148fa11e00f67a51af05ad7f522a4f6c676c61`. Both fixed source hashes still matched after the browser checks.

## Limits

The viewport-control request did not set the requested mobile viewport. Mobile behavior remains unverified. The measurements above cover desktop behavior, saved graph interactions, and the composer state transitions. This presentation-only verification does not establish generation quality or persistence behavior. Normal frontend deployment rollback applies; no migration is involved.
