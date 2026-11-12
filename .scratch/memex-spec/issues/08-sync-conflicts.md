# Disk sync & auto-save conflict model

Type: grilling
Status: open
Blocked by: 02

## Question

How do the UI and disk stay in sync when files change outside the app? Decide: how the client learns of external changes (push via SSE/WebSocket vs. polling vs. on-focus refresh), the optimistic-concurrency token for auto-save (mtime, content hash, ETag), what the user sees on a conflict (reload, keep mine, diff), the debounce interval, and how the tree and derived views (Person View, To-do lists) refresh.
