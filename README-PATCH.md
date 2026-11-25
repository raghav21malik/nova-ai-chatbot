# Lyftr AI chat history sidebar patch

Replace `frontend/src/main.jsx` and `frontend/src/style.css` with the included files.

From the repository root run:

    docker compose up -d --build frontend

Refresh the browser with Ctrl+Shift+R.

How it works:
- Every page load starts a new session as the assignment requires.
- After a successful chat reply, its session ID and first-message title are indexed in browser localStorage.
- Selecting a past session fetches its messages from the existing GET /sessions/{session_id}/messages endpoint, preserving the three-endpoint API contract.
- The X button removes a session from this browser's sidebar only; it does not delete SQLite records.
- Past conversations from before installing this patch cannot be discovered automatically, because the backend has no session-list endpoint. New conversations will appear in the sidebar.
- The sidebar index is browser/device-specific; clearing browser storage removes the index, not the SQLite messages.
- Stored system prompts cannot be recovered through the existing history endpoint. The system-prompt field is cleared on reopening a session; the backend continues to use its stored prompt unless you explicitly supply a new one.
- Session switching is disabled while a request is running.
