"""Acquire the official BEA use table and record its provenance."""

import hashlib
import io
import json
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

URL = "https://apps.bea.gov/industry/release/zip/SUPPLY-USE.zip"
DEST = Path("data/raw/bea")


def main() -> None:
    """Save an unchanged official workbook; never overwrite a snapshot."""
    DEST.mkdir(parents=True, exist_ok=True)
    path = DEST / "Use_Summary.xlsx"
    if not path.exists():
        with urllib.request.urlopen(URL, timeout=120) as response:
            archive = response.read()
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = [n for n in bundle.namelist() if Path(n).name == path.name]
            if len(names) != 1:
                raise ValueError(
                    f"Expected one use summary workbook: {bundle.namelist()}"
                )
            data = bundle.read(names[0])
        path.write_bytes(data)
        (DEST / "source.json").write_text(
            json.dumps(
                {
                    "url": URL,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "file": path.name,
                },
                indent=2,
            )
            + "\n"
        )
    book = load_workbook(path, read_only=True, data_only=True)
    print("Sheets:", book.sheetnames)
    sheet = book[book.sheetnames[-1]]
    print("Sheet:", sheet.title, "dimensions:", sheet.max_row, sheet.max_column)
    rows = list(sheet.values)
    print("Column codes:", list(enumerate(rows[5], 1)))
    print("Commodity codes:", [(r[0], r[1]) for r in rows[7:81]])
    print(
        "Cell types:",
        sorted(
            {
                str(v)
                for r in rows[7:80]
                for v in r[2:73]
                if not isinstance(v, (int, float))
            }
        ),
    )
    for i, row in enumerate(sheet.iter_rows(values_only=True), 1):
        if i < 12 or i > sheet.max_row - 20:
            print(i, list(row[:6]), "...", list(row[-5:]))
    book.close()


if __name__ == "__main__":
    main()
