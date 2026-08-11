"""Tests for parsing DecisionVariable.codes from DMN XML."""

from acp_writer.api import _parse_dmn_metadata


DMN_WITHOUT_CODES = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"
             name="Test Model" namespace="test">
  <inputData id="input_sbp" name="Systolic BP">
    <variable id="var_sbp" name="Systolic BP" typeRef="number"/>
  </inputData>
  <inputData id="input_diabetes" name="Has Diabetes">
    <variable id="var_diabetes" name="Has Diabetes" typeRef="boolean"/>
  </inputData>
  <decision id="d1" name="Test Decision">
    <variable id="var_d1" name="Test Decision" typeRef="string"/>
    <decisionTable id="dt1" hitPolicy="UNIQUE">
      <input id="i1"><inputExpression typeRef="number"><text>Systolic BP</text></inputExpression></input>
      <output id="o1" name="Result" typeRef="string"/>
      <rule id="r1"><inputEntry><text>&gt;= 140</text></inputEntry><outputEntry><text>"High"</text></outputEntry></rule>
    </decisionTable>
  </decision>
</definitions>"""


DMN_WITH_EXTENSION_CODES = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"
             name="Test Model With Codes" namespace="test">
  <inputData id="input_sbp" name="Systolic BP">
    <variable id="var_sbp" name="Systolic BP" typeRef="number"/>
    <extensionElements>
      <clinicalCode system="http://loinc.org" code="8480-6"/>
    </extensionElements>
  </inputData>
  <inputData id="input_diabetes" name="Has Diabetes">
    <variable id="var_diabetes" name="Has Diabetes" typeRef="boolean"/>
    <extensionElements>
      <clinicalCode system="http://snomed.info/sct" code="44054006"/>
    </extensionElements>
  </inputData>
  <decision id="d1" name="Test Decision">
    <variable id="var_d1" name="Test Decision" typeRef="string"/>
    <decisionTable id="dt1" hitPolicy="UNIQUE">
      <input id="i1"><inputExpression typeRef="number"><text>Systolic BP</text></inputExpression></input>
      <output id="o1" name="Result" typeRef="string"/>
      <rule id="r1"><inputEntry><text>&gt;= 140</text></inputEntry><outputEntry><text>"High"</text></outputEntry></rule>
    </decisionTable>
  </decision>
</definitions>"""


DMN_WITH_DESCRIPTION_CODES = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"
             name="Test Model Desc Codes" namespace="test">
  <inputData id="input_sbp" name="Systolic BP">
    <variable id="var_sbp" name="Systolic BP" typeRef="number"/>
    <description>Office systolic blood pressure in mmHg. Code: http://loinc.org|8480-6</description>
  </inputData>
  <inputData id="input_egfr" name="eGFR">
    <variable id="var_egfr" name="eGFR" typeRef="number"/>
    <description>Estimated glomerular filtration rate. Code: http://loinc.org|33914-3</description>
  </inputData>
  <decision id="d1" name="Test Decision">
    <variable id="var_d1" name="Test Decision" typeRef="string"/>
    <decisionTable id="dt1" hitPolicy="UNIQUE">
      <input id="i1"><inputExpression typeRef="number"><text>Systolic BP</text></inputExpression></input>
      <output id="o1" name="Result" typeRef="string"/>
      <rule id="r1"><inputEntry><text>&gt;= 140</text></inputEntry><outputEntry><text>"High"</text></outputEntry></rule>
    </decisionTable>
  </decision>
</definitions>"""


class TestCodesAbsent:
    def test_no_codes_returns_none(self):
        summary = _parse_dmn_metadata(DMN_WITHOUT_CODES)
        for inp in summary.inputs:
            assert inp.codes is None

    def test_inputs_still_parsed(self):
        summary = _parse_dmn_metadata(DMN_WITHOUT_CODES)
        assert len(summary.inputs) == 2
        assert summary.inputs[0].name == "Systolic BP"
        assert summary.inputs[1].name == "Has Diabetes"


class TestCodesFromExtensionElements:
    def test_codes_extracted(self):
        summary = _parse_dmn_metadata(DMN_WITH_EXTENSION_CODES)
        sbp = summary.inputs[0]
        assert sbp.name == "Systolic BP"
        assert sbp.codes == ["http://loinc.org|8480-6"]

    def test_condition_code_extracted(self):
        summary = _parse_dmn_metadata(DMN_WITH_EXTENSION_CODES)
        diabetes = summary.inputs[1]
        assert diabetes.name == "Has Diabetes"
        assert diabetes.codes == ["http://snomed.info/sct|44054006"]


class TestCodesFromDescription:
    def test_codes_from_description_text(self):
        summary = _parse_dmn_metadata(DMN_WITH_DESCRIPTION_CODES)
        sbp = summary.inputs[0]
        assert sbp.codes == ["http://loinc.org|8480-6"]
        assert sbp.description is not None
        assert "systolic" in sbp.description.lower()

    def test_egfr_code_from_description(self):
        summary = _parse_dmn_metadata(DMN_WITH_DESCRIPTION_CODES)
        egfr = summary.inputs[1]
        assert egfr.codes == ["http://loinc.org|33914-3"]


class TestExistingBehaviorPreserved:
    def test_golden_dmn_still_parses(self):
        """Verify the existing golden DMN files still parse correctly."""
        from pathlib import Path

        golden_dir = Path(__file__).parent.parent.parent / "cpg-ingester" / "data" / "golden"
        for dmn_file in golden_dir.glob("*.dmn"):
            dmn_xml = dmn_file.read_text()
            summary = _parse_dmn_metadata(dmn_xml)
            assert summary.name
            assert len(summary.inputs) > 0
            for inp in summary.inputs:
                assert inp.codes is None
