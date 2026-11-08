# Engineering preferences

- Keep investigation token-efficient. Start with `PROJECT_MAP.md` and the relevant
  feature's entry points; use scoped `rg -n` searches and bounded reads rather than
  repeated repository-wide scans or full-file dumps. Expand only when evidence
  requires it. Reuse findings within the chat and run checks relevant to the change.
- Maintain the compact feature map when entry points or responsibilities change.
  Treat it as a navigation index, not proof of current behavior: verify relevant
  code before editing. Do not store secrets, raw production data, or unsupported
  diagnoses in it. Do not sacrifice necessary validation to save tokens.
- Before implementing a bug fix or feature, analyze the existing flow and discuss
  the evidence, intended behavior, proposed approach, and relevant tradeoffs with
  the user. Prefer the smallest effective, maintainable change; avoid speculative
  edits and unnecessary abstractions.
- Distinguish confirmed causes from hypotheses. For reported bugs, reproduce with
  the actual failing input/output or logs where available. If that evidence is
  missing, state the limitation rather than presenting an inferred cause as proven.
- Validate changes against the reported failure and meaningful regression cases.
  Report separately what unit/mocked tests establish and what has actually been
  verified end to end or in production. Passing tests alone do not prove the user's
  production issue is fixed.
- Implement root-cause fixes with minimal, reusable, production-quality changes.
- Do not create unnecessary files. Reuse existing files and components where
  appropriate; add a new file only when it has a clear, necessary responsibility.
  Avoid redundant documentation, helper scripts, and implementation-mirroring tests.
- Do not route natural-language intent with hardcoded greeting/keyword lists or hide
  incorrect behavior in the UI. Let the LLM choose tools under clear instructions.
- Keep deterministic backend checks for authorization, source provenance, citations,
  validation, resource limits, and security boundaries.
- Factual answers must cite supporting evidence inline. Do not present assumptions,
  model memory, or previous assistant answers as verified evidence.
- Verify meaningful behavior and report limitations honestly; do not promise zero
  hallucinations based only on prompting or the presence of a citation.
