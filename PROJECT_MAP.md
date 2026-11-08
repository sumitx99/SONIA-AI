# Project navigation

Paths are relative to this repository. This is a compact navigation index of known
entry points, not an exhaustive inventory or a record of production verification.
Read only the relevant row's files first; verify current behavior in source.

| Area | Entry points and responsibilities | Relevant checks |
| --- | --- | --- |
| Chat UI | `frontend/app/chat/page.tsx`: composer, messages, Stop/Resume state. `frontend/lib/api.ts`: authenticated requests and SSE reader. | `frontend/tests/client-regressions.test.mjs` |
| Chat history | `frontend/lib/chat-context.ts`: history selection and prompt edits. `frontend/lib/hooks/use-conversations.ts`: loading, local backup and syncing. `backend/app/api/conversations.py`: saved message schema and endpoints. | `backend/tests/test_conversations.py`, `backend/tests/test_chat_memory.py` |
| Answer generation | `backend/app/api/chat.py`: chat endpoints, stream events and final citation checking. `backend/app/services/llm.py`: model calls and instructions. | `backend/tests/test_llm.py`, `backend/tests/test_tool_fallback.py` |
| Connected tools | `backend/app/mcp_client/agent.py`: tool execution loop, policy, approvals, evidence, Gemini grounding-support annotations and one bounded continuation on `MAX_TOKENS`. `session.py` in the same directory: MCP transport and result limits. `connections.py`, `store.py`, `oauth.py`, `safety.py`: connection management, credentials and URL checks. | `backend/tests/test_mcp_client.py`, `backend/tests/test_tool_fallback.py`, `backend/tests/test_web_activity.py` |
| Citations | `backend/app/mcp_client/agent.py` maps Gemini grounding-support segments to safe inline source links in the current stream, without an extra model call; `backend/app/api/chat.py` passes events. `frontend/lib/api.ts` and `frontend/app/chat/page.tsx` receive and retain them; `frontend/lib/markdown/inline-grounding.ts` applies UTF-16 positions; `markdown-message.tsx` renders compact source links. `answer_verification.py` remains the exact-quote verifier for model-numbered citations; `tool_evidence.py` and `mcp_client/session.py` bound structured connector evidence. Model markers for document/MCP/Groq sources remain best-effort. Mocked grounding tests cover source mapping and offsets; live Gemini behavior and the reported JSearch production issue remain unverified. `citation-marker.tsx` and `remark-citations.ts` render numbered citations. | `backend/tests/test_tool_evidence.py`, `backend/tests/test_answer_verification.py`, `backend/tests/test_mcp_client.py`, `backend/tests/test_web_activity.py`, frontend regressions |
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
