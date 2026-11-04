# Engineering preferences

- Implement root-cause fixes with minimal, reusable, production-quality changes.
- Do not route natural-language intent with hardcoded greeting/keyword lists or hide
  incorrect behavior in the UI. Let the LLM choose tools under clear instructions.
- Keep deterministic backend checks for authorization, source provenance, citations,
  validation, resource limits, and security boundaries.
- Factual answers must cite supporting evidence inline. Do not present assumptions,
  model memory, or previous assistant answers as verified evidence.
- Verify meaningful behavior and report limitations honestly; do not promise zero
  hallucinations based only on prompting or the presence of a citation.
