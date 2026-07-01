# Proposed CAMO schema changes

## Tim proposed changes
- Remove all mention of NCBITaxon because it is server-breakingly huge. Wikidata should be preferred for taxa.
- Add annotation property loom_note: with values:
    - hidden
    - collapsed



These are review notes only. No CAMO schema file has been changed as part of the excerpt-bin interface work.

## 1. Represent plural evidence explicitly

The current `CausalEdge.evidential_basis` is a single inlined object. A causal claim can be supported by several distinct evidence lines, including both difference-making evidence and production/mechanism evidence.

For a future CAMO release, add an `EvidenceItem` class and a multivalued `evidence_items` slot on `CausalEdge`.

Suggested `EvidenceItem` slots:

- `evidence_id`
- `epistemic_game`
- `study_design`
- `n_observations`
- `statistical_test`
- `p_value`
- `effect_size`
- `effect_unit`
- `confidence_interval_low`
- `confidence_interval_high`
- `mechanism_description`
- `source_spans`
- `evidence_notes`

Suggested `EpistemicGameEnum` values:

- `difference_maker`
- `production_or_mechanism`
- `not_addressed`

Because `evidence_items` would be multivalued, an edge can carry both kinds without a lossy `both` enum value. Keep `philosophical_account` separate: an epistemic game classifies the evidence-seeking activity, not the philosophical theory of causation.

Migration option: retain `evidential_basis` for one compatibility release, migrate it to a one-item `evidence_items` list, then deprecate it.

## 2. Allow source spans on nodes

Loom now lets annotators ground nodes in one or more excerpts, but the current CAMO `CausalNode` class does not declare `source_spans`. Add the existing multivalued, inlined `source_spans` slot to `CausalNode` so node grounding survives schema-valid export.

No change is needed to the stable character-offset model.

## 3. Consider an optional causal-purpose classification

If EcoWeaver needs to capture the purpose pursued by the paper or passage, add an optional, multivalued `causal_purpose` slot with:

- `causal_inference`
- `causal_explanation`
- `prediction`
- `control`

This should record the authors' stated purpose, not the annotator's or a downstream user's intended use. Those uses are contextual and should not become intrinsic properties of a universal causal edge.

## 4. Separate association evidence from causal assertions

An observational association should not automatically become a weak causal edge. `EvidenceItem` would provide a place to retain difference-making or correlational evidence and link it to a candidate or explicit causal claim without asserting that the association is itself causal.

If CAMO needs this distinction explicitly, consider an `evidence_relation` enum such as `supports`, `challenges`, and `contextualizes` on `EvidenceItem`.

## 5. Clarify confidence semantics

`certainty_grade` currently sits beside `philosophical_account`, but its meaning is ambiguous. Decide whether it represents:

- annotator confidence in the philosophical-account classification, or
- the authors' expressed certainty in the causal claim.

The first could be renamed `account_classification_confidence`. The second overlaps with `claim_strength` and should be defined carefully rather than inferred from the current placement.

## 6. Add semantic descriptions to slots and enum values

Add concise `title` and `description` metadata to CAMO slots and permissible values, especially `predicate`, `claim_strength`, `philosophical_account`, and the evidence fields. Semantic definitions belong in the schema; workflow prompts, examples, ordering, and progressive-disclosure rules should remain in `config/loom_ui.yaml`.

## Suggested versioning

These changes are suitable for a CAMO `0.6.0` proposal because they alter class structure and cardinality. The Loom migration assistant should report:

- conversion of `evidential_basis` to `evidence_items[0]`;
- preservation of existing edge `source_spans`;
- newly exportable node `source_spans`; and
- unresolved confidence semantics requiring human review.
