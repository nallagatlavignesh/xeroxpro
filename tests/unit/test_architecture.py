"""business/ must stay pure: no Qt, SQLAlchemy, or other app layers."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = {"PySide6", "sqlalchemy", "ui", "database", "infrastructure", "application"}


def test_business_layer_is_pure():
    offenders = []
    for path in (ROOT / "business").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else []
            offenders += [f"{path.name}: {n}" for n in names if n.split(".")[0] in FORBIDDEN]
    assert not offenders, offenders
