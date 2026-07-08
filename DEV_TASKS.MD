## High
- It should save as the annotator types, and make it clear through an icon that shows when the entry was last saved.

## Medium
- Implement lookup of province and country based on StudyCoordinates
- Implement GeoNames lookup for nearest named location based on StudyCoordinates
- Implement auto-calculation for study_duration_month if possible.
- Make sure Loom is writing the annotator ORCID to       CausalEdge.annotator
- Replace the ELMO type-ahead for `entity_type: management_intervention` with an
  "Insert ELMO term" button that opens a popup class-tree browser (navigate the
  hierarchy, click "insert" on the class that fits) — mirrors the existing
  `node_picker` widget pattern. Removes an entire class of autocomplete
  fragility (debounce timing, dropdown click races) in favor of an explicit,
  visible pick. Also: when an annotator submits free text instead of a real
  ontology term on any ontology-routed slot, flag that node/edge for reviewer
  attention rather than letting it pass silently.

## Non-urgent
 - Remove credit for icon from every single page (it should just appear once)
