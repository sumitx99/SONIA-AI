# Project navigation

Paths are relative to this repository. This is a compact navigation index of known
entry points, not an exhaustive inventory or a record of production verification.
Read only the relevant row's files first; verify current behavior in source.

| Area | Entry points and responsibilities | Relevant checks |
| --- | --- | --- |
| Chat UI | `frontend/app/chat/page.tsx`: composer, messages, Stop/Resume state. `frontend/lib/api.ts`: authenticated requests and SSE reader. | `frontend/tests/client-regressions.test.mjs` |
| Chat history | `frontend/lib/chat-context.ts`: history selection and prompt edits. `frontend/lib/hooks/use-conversations.ts`: loading, local backup and syncing. `backend/app/api/conversations.py`: saved message schema and endpoints. | `backend/tests/test_conversations.py`, `backend/tests/test_chat_memory.py` |
| Answer generation | `backend/app/api/chat.py`: chat endpoints, stream events and final citation checking. `backend/app/services/llm.py`: model calls and instructions. | `backend/tests/test_llm.py`, `backend/tests/test_tool_fallback.py` |
| Connected tools | `backend/app/mcp_client/agent.py`: tool execution loop, policy, approvals and evidence. `session.py` in the same directory: MCP transport and result limits. `connections.py`, `store.py`, `oauth.py`, `safety.py`: connection management, credentials and URL checks. | `backend/tests/test_mcp_client.py`, `backend/tests/test_tool_fallback.py` |
| Citations | `backend/app/services/answer_verification.py`: source lookup and exact quote matching. `tool_evidence.py`: valid JSON size budgeting and local decoded-field matching; `mcp_client/session.py` selects structured data and applies the 8,000-character budget. Model and verifier use the same bounded result, without duplicate excerpts. Production fix unverified. `frontend/components/chat/citation-marker.tsx`: citation popup; `frontend/lib/markdown/remark-citations.ts`: inline markers. | `backend/tests/test_tool_evidence.py`, `backend/tests/test_answer_verification.py`, `backend/tests/test_mcp_client.py`, frontend regressions |
| Web/tool activity | `backend/app/services/web_search.py`, `source_reader.py`, `web_activity.py`: search, page reading and activity data. `frontend/components/chat/tool-calls.tsx`, `tool-activity.module.css`, `frontend/lib/web-activity.ts`: event-driven timeline, collapsed Details and approval controls. Chat page passes streaming state and marks interrupted calls stopped; `backend/app/api/conversations.py` accepts saved stopped status. No added model calls. | Frontend regressions (rendered activity lifecycle), `backend/tests/test_conversations.py`, `backend/tests/test_web_activity.py`, `backend/tests/test_search_policy.py` |
| Charts | `frontend/lib/markdown/chart-spec.ts`: chart parsing and table data. `frontend/components/chat/graph-component.tsx` and its CSS module: Plotly rendering, hover labels and controls. | Frontend regressions, frontend typecheck; browser verification for visual behavior |
| Documents and images | `backend/app/api/documents.py`; `backend/app/services/parsing/`, `backend/app/services/images/`: upload, parsing, extraction and storage. `frontend/components/chat/document-image.tsx`, `web-images.tsx`: galleries. | `backend/tests/test_upload_reliability.py`, `test_pdf_utils.py`, `test_document_images.py`, `test_image_pipeline.py`, `test_web_images.py` |
| Auth and app setup | `backend/app/main.py`: app setup. `backend/app/core/auth.py`, `config.py`, `db.py`: auth, config and DB. `frontend/lib/supabase.ts`, `frontend/lib/hooks/use-session.ts`: frontend auth. | Relevant backend tests and frontend typecheck |
| Styling | `frontend/app/styles/identity.css`, `globals.css`; component CSS modules beside components. | Typecheck/build where needed; browser check for layout changes |

## Commands

- From `frontend`: `npm test`, `npm run typecheck`, `npm run build`.
- From `backend`: `.venv/bin/python -m unittest discover -s tests -p 'test_<area>.py'`.
- Start with relevant tests. Broaden only for cross-cutting changes or unresolved failures.

## Verification boundary

Local unit/mocked tests do not establish production behavior. The reported JSearch
citation failure still needs its actual tool result and generated citation compared;
browser access to that production chat was declined. Do not infer it is resolved.
