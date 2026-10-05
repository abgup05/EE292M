"""Check the deployment entrypoint without Docker's PYTHONPATH setting."""

import json
import subprocess
import sys
from pathlib import Path


def test_entrypoint_without_pythonpath():
    """The hosted app must import and read its snapshot from the project root."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-E",
            "-c",
            (
                "import json; from main import app; "
                "from app.api import catalog, index; "
                "from pathlib import Path; "
                "print(json.dumps({'industries': len(catalog()['industries']), "
                "'page_exists': Path(index().path).is_file(), 'title': app.title}))"
            ),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    assert data["industries"] == 71
    assert data["page_exists"]
