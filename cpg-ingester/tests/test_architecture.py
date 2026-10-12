"""Architecture checks for pipeline state and credential handling."""

import ast
import re
from pathlib import Path


def test_state_models_do_not_define_credential_fields():
    """State TypedDicts and models must not carry credentials into traces/checkpoints."""
    src = Path(__file__).parent.parent / "src" / "cpg_ingester"
    credential_field = re.compile(r"(?i)(api_key|secret|token|password)")
    violations = []

    for py_file in src.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if py_file.name != "state.py" and not node.name.endswith("State"):
                continue
            for child in node.body:
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    if credential_field.search(child.target.id):
                        violations.append(f"{py_file.relative_to(src)}:{node.name}.{child.target.id}")

    assert not violations, "Credential fields found in state models: " + ", ".join(violations)


def test_src_contains_no_llm_api_key_literal():
    """Pipeline code must not name a credential state field."""
    src = Path(__file__).parent.parent / "src" / "cpg_ingester"
    hits = [str(path.relative_to(src)) for path in src.rglob("*.py") if "llm_api_key" in path.read_text()]
    assert not hits, "Credential state field literal found in: " + ", ".join(hits)
