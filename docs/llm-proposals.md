# LLM Proposal Seam

The `apps/llm` package provides a pluggable interface for LLM-backed
pre-annotation proposals. **It is disabled by default** via
`LLM_PROPOSALS_ENABLED = False` in `loom/settings/base.py`. All guidance
here applies to future implementors activating the seam.

---

## Design constraints (non-negotiable)

- Proposals land as `origin='llm_proposed'`, `status='draft'`. They do not
  auto-promote to `complete` or `gold` under any circumstances.
- Every proposal mutation goes through the annotation service layer and emits
  an `AuditEvent`. There is no silent write path.
- All UI elements that surface proposals are gated on `LLM_PROPOSALS_ENABLED`.

---

## Failure modes

| Failure | Effect | Mitigation |
|---------|--------|------------|
| Model unavailable | `propose()` returns `([], [])` — annotation proceeds without pre-fills | `NoOpProposer` is the fallback; implement retry in concrete Proposer |
| Hallucinated entity | Draft node with incorrect name/type displayed to annotator | Annotator must accept explicitly; wrong drafts are corrected or rejected |
| Hallucinated span | `source_span_start/end` points to wrong character range | Annotator sees highlighted text; mismatch is immediately visible |
| Model version change | Proposal quality changes silently | Pin model version per Proposer (see below) |
| Draft never reviewed | Stale `llm_proposed` drafts accumulate | Admin review queue; project owners can bulk-expire drafts |

---

## Model version recording

When implementing a concrete `Proposer`, record the model version in the
JSONB payload of each proposed node and edge:

```python
data = {
    **proposed_data,
    "llm_model_version": "claude-sonnet-4-6",   # exact model ID
    "llm_prompt_version": "v1.2",               # tag of prompt template used
}
```

Store prompt templates as committed files in `apps/llm/prompts/` with
semantic versioning. Never embed prompt text in Python source.

---

## Bias considerations

LLM models are trained on literature that may over-represent certain taxa,
regions, or study designs. Proposals may:

- Favour common species over rare ones when resolving ambiguous entity names.
- Reflect the publication bias of the training corpus (e.g. positive results
  over null findings).
- Systematically mis-classify predicate direction for under-represented
  ecological relationships.

Mitigation: inter-annotator agreement metrics (IRR CSVs exported by Loom)
should be compared between documents with and without LLM pre-fills to detect
systematic proposal bias before enabling the seam in production.

---

## Confidence scores

The `Proposer` Protocol does not currently include a confidence field.
Before enabling a concrete proposer, add `llm_confidence: float | None` to
`ProposedNode` and `ProposedEdge` and surface it in the annotation UI so
annotators can prioritise high-confidence proposals.

---

## Sensitive information

Loom sends document text to an external LLM API when a concrete Proposer is
active. Before enabling:

1. Confirm data sharing is permitted under your data governance agreement.
2. Strip author names and funding acknowledgements if the review is blinded.
3. Document the data processor relationship in your institution's privacy notice.
