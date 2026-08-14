"""Architecture boundary test: production code must not import from benchmark."""

import ast
from pathlib import Path


def _get_imports(filepath: Path) -> list[str]:
    """Extract all import module names from a Python file."""
    try:
        tree = ast.parse(filepath.read_text())
    except SyntaxError:
        return []
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def test_no_benchmark_imports_from_production():
    """Nothing under src/acp_writer/ outside benchmark/ may import from acp_writer.benchmark."""
    src = Path(__file__).parent.parent / "src" / "acp_writer"
    violations = []
    for py_file in src.rglob("*.py"):
        rel = py_file.relative_to(src)
        if str(rel).startswith("benchmark"):
            continue
        if "__pycache__" in str(rel):
            continue
        for imp in _get_imports(py_file):
            if imp.startswith("acp_writer.benchmark"):
                violations.append(f"{rel}: imports {imp}")

    assert not violations, (
        "Production code imports from benchmark:\n" + "\n".join(violations)
    )


def test_decision_engine_service_does_not_import_langchain():
    """The decision-engine service must not pull langchain_openai.

    This enforces the thin-wrapper property: the decision pod has no
    LLM dependency. Resolution lives in the LLM-reasoning pod.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c",
         "import acp_writer.services.decision_engine; "
         "import sys; "
         "assert 'langchain_openai' not in sys.modules, "
         "'decision_engine imports langchain_openai'"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"decision_engine service imports langchain_openai:\n{result.stderr}"
    )
