"""Prompt templates for the Figure Interpreter node (plan P5).

Type-conditional (review §10 D4): flowcharts are transcribed into a Mermaid
diagram plus a prose walkthrough; any other figure class gets a faithful prose
description only. The prompts constrain the model to transcribe what is visible
and never invent branches, thresholds, or drugs — clinical safety.
"""

FIGURE_SYSTEM = """\
You are a clinical-informatics assistant that transcribes figures from Clinical \
Practice Guidelines into structured, faithful representations. Transcribe ONLY \
what the image shows. Do not invent branches, thresholds, drugs, or values. If \
text is illegible, mark it "[illegible]" rather than guessing.\
"""

FLOWCHART_USER = """\
This image is a clinical decision flowchart extracted from a Clinical Practice \
Guideline. Return a single JSON object with EXACTLY these keys:
  - "mermaid": a Mermaid `flowchart TD` diagram that reproduces the chart. Use \
`{{...}}` for decision/diamond nodes and `[...]` for action/step nodes. Put \
Yes/No (or other) branch labels on the edges: `A -->|Yes| B`.
  - "description": a short prose walkthrough of the algorithm a clinician could \
follow.
  - "nodes": an array of the node label strings, verbatim.
  - "edges": an array of [from_label, to_label, branch_label] triples \
(branch_label "" when unlabeled).
Return ONLY the JSON object, no prose around it, no code fences.\
"""

DESCRIPTION_ONLY_USER = """\
This image is a figure ({cls}) from a Clinical Practice Guideline. Return a \
single JSON object with one key "description": a faithful prose description of \
what the figure shows (axes/labels/values for charts; structures for diagrams). \
Transcribe only what is visible. Return ONLY the JSON object, no code fences.\
"""
