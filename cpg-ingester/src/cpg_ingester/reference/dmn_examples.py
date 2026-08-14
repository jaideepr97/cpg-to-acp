"""DMN reference examples and error patterns for Drools/Kogito.

These are plain OMG DMN 1.4 — no proprietary extensions.
"""

DMN_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"
             xmlns:feel="https://www.omg.org/spec/DMN/20191111/FEEL/"
             id="definitions_{id}"
             name="{name}"
             namespace="https://www.omg.org/spec/DMN/20191111/MODEL/">

  <inputData id="input_systolic" name="Systolic BP">
    <variable id="var_systolic" name="Systolic BP" typeRef="number"/>
  </inputData>
  <inputData id="input_age" name="Patient Age">
    <variable id="var_age" name="Patient Age" typeRef="number"/>
  </inputData>

  <decision id="decision_{id}" name="{name}">
    <variable id="var_decision_{id}" name="{name}" typeRef="string"/>
    <informationRequirement id="ir_systolic">
      <requiredInput href="#input_systolic"/>
    </informationRequirement>
    <informationRequirement id="ir_age">
      <requiredInput href="#input_age"/>
    </informationRequirement>
    <decisionTable id="dt_{id}" hitPolicy="{hit_policy}" preferredOrientation="Rule-as-Row">
      <input id="inp_1">
        <inputExpression id="ie_1" typeRef="number"><text>Systolic BP</text></inputExpression>
      </input>
      <input id="inp_2">
        <inputExpression id="ie_2" typeRef="number"><text>Patient Age</text></inputExpression>
      </input>
      <output id="out_1" name="Recommendation" typeRef="string"/>
      <rule id="rule_1">
        <description>High BP in older adults</description>
        <inputEntry id="ie1_1"><text>&gt;= 150</text></inputEntry>
        <inputEntry id="ie1_2"><text>&gt;= 60</text></inputEntry>
        <outputEntry id="oe1_1"><text>"Initiate treatment"</text></outputEntry>
      </rule>
      <rule id="rule_2">
        <description>High BP in younger adults</description>
        <inputEntry id="ie2_1"><text>&gt;= 140</text></inputEntry>
        <inputEntry id="ie2_2"><text>&lt; 60</text></inputEntry>
        <outputEntry id="oe2_1"><text>"Initiate treatment"</text></outputEntry>
      </rule>
    </decisionTable>
  </decision>

</definitions>
"""

COMMON_ERRORS = """\
## Common DMN Mistakes and Corrections

### 1. Wrong namespace
WRONG: xmlns="http://www.omg.org/spec/DMN/20151101/dmn.xsd"
RIGHT: xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"

### 2. Missing hit policy
WRONG: <decisionTable id="dt_1">
RIGHT: <decisionTable id="dt_1" hitPolicy="FIRST">
Hit policies: UNIQUE (mutually exclusive), FIRST (priority order), COLLECT (multiple matches)

### 3. Missing typeRef on inputExpression
WRONG: <inputExpression id="ie_1"><text>Systolic BP</text></inputExpression>
RIGHT: <inputExpression id="ie_1" typeRef="number"><text>Systolic BP</text></inputExpression>

### 4. Invalid FEEL in inputEntry
WRONG: <inputEntry><text>Systolic BP >= 140</text></inputEntry>
RIGHT: <inputEntry><text>>= 140</text></inputEntry>
Input entries use FEEL unary tests — the variable name is NOT repeated.

### 5. String values missing quotes
WRONG: <outputEntry><text>Start medication</text></outputEntry>
RIGHT: <outputEntry><text>"Start medication"</text></outputEntry>
String literals in FEEL must be quoted with double quotes.

### 6. Boolean values wrong case
WRONG: <inputEntry><text>True</text></inputEntry>
RIGHT: <inputEntry><text>true</text></inputEntry>
FEEL booleans are lowercase: true, false.

### 7. Empty inputEntry (unintentional)
WRONG: <inputEntry><text></text></inputEntry> (means "any value" — is this intended?)
RIGHT: <inputEntry><text>-</text></inputEntry> (explicit "any value")
An empty <text> element means "any" but is ambiguous. Use "-" for clarity.

### 8. Missing informationRequirement
Every inputData referenced in the decisionTable must have a corresponding
informationRequirement element in the decision, with href="#input_id".

### 9. XML special characters not escaped
WRONG: <inputEntry><text>< 130</text></inputEntry>
RIGHT: <inputEntry><text>&lt; 130</text></inputEntry>
Use &lt; for <, &gt; for >, &amp; for &.

### 10. Range syntax
Inclusive: [130..139] means 130 <= x <= 139
Exclusive: (130..140) means 130 < x < 140
Mixed: [130..140) means 130 <= x < 140
"""

REFERENCE_EXAMPLES = f"""\
## DMN Reference for Drools/Kogito (OMG DMN 1.4)

### Template Structure
{DMN_TEMPLATE}

{COMMON_ERRORS}

### Hit Policy Guide
- **UNIQUE**: Rules are mutually exclusive — exactly one rule matches any input.
  Use for classification grids where categories don't overlap.
- **FIRST**: Rules are priority-ordered — first matching rule wins.
  Use for treatment decisions where more specific rules override general ones.
- **COLLECT**: All matching rules fire — outputs are collected.
  Use for monitoring schedules where multiple actions may apply.

### FEEL Type Reference
- number: numeric values, comparisons use >= <= > <
- string: quoted values "like this", comparisons use string equality
- boolean: true or false (lowercase)
- date: date("2026-01-01")

### FEEL Unary Test Patterns
- Comparison: >= 140, < 130, > 0
- Range: [130..139], (0..100)
- Equality (string): "Start medication"
- Equality (boolean): true, false
- List: "A", "B", "C" (matches any)
- Negation: not("Excluded")
- Any value: - (dash)
"""
