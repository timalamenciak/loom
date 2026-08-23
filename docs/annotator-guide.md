# Annotator guide

The complete day-to-day workflow — receiving an assignment, grounding claims
in the text, creating nodes and edges, ontology autocomplete, work sessions,
and submitting — lives in the [user guide](user-guide/index.md). Start there
if this is your first time annotating in Loom; it walks a full assignment
from **My queue** through **Submit for review**.

This page covers one thing the user guide doesn't yet: **reviewing and
accepting LLM proposals** — only relevant if a project admin has enabled the
LLM seam for your project (most projects have it off; see the
[admin guide](admin-guide.md#configuring-the-llm-pipeline)).

## Reviewing and accepting LLM proposals

If a project has the LLM seam enabled, some edges you see may already exist
as **drafts** an LLM proposed rather than something you created — you'll find
them at **Project → Review Proposals**. Nothing an LLM proposes is ever
final: it lands as a `draft` edge with `origin: llm_proposed`, and stays that
way — read-only to everyone else, invisible in any "complete" count — until
you act on it here.

Each proposal shows:

- the proposed subject → object relationship, with its predicate;
- the exact sentence from the source text the model says supports the claim
  (`source_text`), so you can check it against the article directly, the same
  way you'd check your own grounding excerpts;
- which document it's from and when it was proposed.

For each one, you have three options:

1. **Accept** — the edge advances from `draft` to `complete` under your name,
   exactly as if you had marked it done yourself. Use this when the proposal
   is correct as-is.
2. **Edit before accepting** — opens the full annotation workspace for that
   document with the proposed edge already there, so you can correct a field
   before treating it as done. Fix what needs fixing, save, then come back to
   Review Proposals and accept it.
3. **Reject** — deletes the draft edge outright. Use this when the claim is
   wrong, hallucinated, or not actually supported by the cited sentence — not
   for "needs a small fix," which **Edit before accepting** handles without
   losing the proposal.

Treat a proposal exactly like a first-pass suggestion from a fast but
occasionally-wrong colleague: verify the cited sentence actually says what
the proposal claims before accepting. The model's confidence is not shown
because it doesn't track confidence — your judgment on the grounding text is
the only check that matters here, same as with your own annotations.

Whether you accept, edit-then-accept, or reject, that choice is recorded
(`ProposalOutcome`) — it's what feeds the acceptance-rate metrics your
project admin sees, so a rejection is useful signal, not wasted effort.
