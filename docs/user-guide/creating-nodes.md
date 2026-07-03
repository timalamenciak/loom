# Create nodes

A node describes one side of a causal relationship. Create at least two nodes
before creating an edge: one for the cause and one for the effect.

## Decompose the claim

Loom uses an ELMO-style decomposition. In practical terms, describe:

- the entity or process;
- the attribute or variable being discussed; and
- the direction or state of change, when the article specifies one.

For the example claim—“Experimental nitrogen addition increased above-ground
plant biomass”—you might need:

- a cause node representing nitrogen addition; and
- an effect node representing increasing plant biomass.

Use the form shown by Loom to capture the precise schema-defined details.

## Create a grounded node

1. Add the passage supporting the node to the excerpt bin.
2. Select its checkbox in the excerpt bin.
3. Select **Use for node**.
4. Confirm the correct passage is selected under **Grounding excerpts**.
5. Complete the required node fields.
6. Select **Save node**.
7. Confirm that the node appears in the graph panel.

You can instead select **+ Add node**, but you should attach a grounding
excerpt whenever the article text is available.

## Choose ontology terms carefully

Some node fields search a local ontology index.

1. Search with the wording used by the article.
2. Try a shorter or more general term if there is no result.
3. Read the result label and description before selecting it.
4. Select a term only when it represents the intended concept.

Never invent an ontology identifier. If there is no suitable term, use free
text or the term-suggestion option only when the form offers it. Otherwise,
leave an optional field empty or ask your annotation lead how the project wants
the gap recorded.

## Reuse nodes

Before creating a node, check the graph panel for an existing node with the
same entity, attribute, and direction. Reuse that node across edges when it
represents the same concept.

Create a separate node when the article describes a materially different
attribute, direction, state, or ecological entity.

## Edit or delete a node

Select **Edit** beside a node, change the fields, and select **Save node**.
Edges that reference the node continue to reference the edited node.

Deleting a node also removes its connected edges. Read the confirmation and
check the graph before confirming deletion.

Next: [connect nodes with an edge](creating-edges.md).
