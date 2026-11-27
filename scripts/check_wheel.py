"""Check that the wheel can supply every input needed for the offline demo."""
from pathlib import Path
from zipfile import ZipFile

wheel, = Path("dist").glob("pilon_discovery-*.whl")
with ZipFile(wheel) as archive:
    names = set(archive.namelist())
    required = {"pilon/facets/example/model.json", "pilon/facets/example/signals.jsonl",
                "pilon/facets/report.py", "pilon/app.py", "pilon/cli.py"}
    assert required <= names, f"Missing package files: {required - names}"
    source = Path("src")
    modules = {p.relative_to(source).as_posix() for p in (source / "pilon").rglob("*.py")}
    packaged = {n for n in names if n.startswith("pilon/") and n.endswith(".py")}
    assert packaged == modules, f"Unexpected module differences: {packaged ^ modules}"
    assert not any(n.startswith("runtime/") or n.endswith(".sqlite") for n in names)
print("Discovery wheel verified.")
