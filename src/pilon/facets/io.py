"""Portable inputs and atomic UTF-8 exports."""
import csv
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile


def _jsonlines(lines):
    for number, line in enumerate(lines, 1):
        if line.strip():
            try:
                yield json.loads(line)
            except ValueError as exc:
                raise ValueError(f"Invalid JSON on signal line {number}") from exc


def read_signals(filename):
    if str(filename) == "-":
        yield from _jsonlines(sys.stdin)
        return
    path = Path(filename)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        if path.suffix.lower() == ".csv":
            for row in csv.DictReader(stream):
                if row.get("count"):
                    row["count"] = int(row["count"])
                else:
                    row.pop("count", None)
                yield row
        else:
            yield from _jsonlines(stream)


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False, mode="w", encoding="utf-8") as tmp:
        name = Path(tmp.name)
        try:
            tmp.write(content)
        except BaseException:
            tmp.close()
            name.unlink(missing_ok=True)
            raise
    try:
        os.replace(name, path)
    finally:
        name.unlink(missing_ok=True)
