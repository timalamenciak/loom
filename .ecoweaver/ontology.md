# Ontology and Controlled Vocabulary Rules

Ontology grounding is a scientific claim. Treat it with the same care as a citation.

## Core principles

- Do not invent ontology identifiers.
- Prefer existing authoritative terms.
- Preserve local language and practitioner terminology where relevant.
- Record provenance for mappings.
- Distinguish exact matches from broad, narrow, close, or related matches.
- Preserve uncertainty rather than forcing a term.

## Term selection order

Use project-approved sources first. Customize this list per repository.

1. Project vocabulary or schema enum
2. Domain ontology approved by the project
3. Widely used general ontology
4. Controlled free-text with provenance
5. Candidate term flagged for review

## Mapping fields

When storing an ontology mapping, prefer fields equivalent to:

- original label
- normalized label
- ontology identifier
- ontology name/version
- mapping relation
- confidence or review status
- evidence/provenance
- curator or agent
- timestamp

## No-invention policy

Agents must not create fake CURIEs, fake ontology classes, or plausible-looking identifiers. If a term cannot be grounded, mark it as ungrounded/candidate and explain why.

## Human review

Ontology changes should be reviewable by a human. Prefer small diffs and include examples showing how terms are used in context.

## Indigenous, local, and practitioner knowledge

Do not collapse local or Indigenous knowledge into external ontology terms without preserving the original wording, source context, rights, and governance constraints. Respect labels, licenses, and permissions attached to knowledge artifacts.
