"""Compare catalog specifications with observed language and current filters."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
import re
import unicodedata


STAGES = ("discovery", "forecast", "induction", "usage")
ROLES = {"demand", "catalog", "external"}


def _key(value):
    text = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[^\W_]+", text, re.UNICODE))


def _string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected non-empty text for {field}")
    return value


def _day(value, field):
    try:
        return date.fromisoformat(_string(value, field))
    except ValueError as exc:
        raise ValueError(f"Invalid {field}, expected YYYY-MM-DD") from exc


def _terms(value, field):
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of names")
    result = {_key(_string(item, field)) for item in value}
    if "" in result:
        raise ValueError(f"{field} contains an empty normalized name")
    return result


@dataclass(frozen=True)
class Spec:
    label: str
    value: str
    start: int
    end: int


# Merchant feeds often list one specification per line. A custom extractor can
# yield the same type from free text, including its original character offsets.
def labeled_specs(text):
    for match in re.finditer(r"(?m)^([^:\r\n]{1,80}):[ \t]*([^\r\n]+)", text):
        label, value = (part.strip() for part in match.groups())
        if _key(label) and _key(value):
            yield Spec(label, value, *match.span())


def _records(rows, category):
    seen = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each signal must be an object")
        for field in ("id", "role", "source", "category", "text"):
            _string(row.get(field), field)
        if row["role"] not in ROLES:
            raise ValueError(f"Unknown role in {row['id']}")
        if row["id"] in seen:
            if seen[row["id"]] != row:
                raise ValueError(f"Conflicting records for {row['id']}")
            continue
        seen[row["id"]] = row
        if row["category"] != category:
            continue
        if row["role"] == "catalog":
            _string(row.get("product_id"), "product_id")
        if row["role"] == "demand":
            _day(row.get("date"), "date")
            count = row.get("count", 1)
            if type(count) is not int or count < 1:
                raise ValueError(f"Invalid count in {row['id']}")
        yield row


def _evidence(row, start, end):
    return dict(record_id=row["id"], source=row["source"], start=start,
                end=end, quote=row["text"][start:end])


def explore(model, records, *, through="usage", horizon_days=30, extract_specs=labeled_specs):
    """Return a JSON-serializable report. The model and records are read-only."""
    if through not in STAGES or type(horizon_days) is not int or horizon_days < 1:
        raise ValueError("Invalid stage or forecast horizon")
    if not isinstance(model, dict):
        raise ValueError("Expected a category model object")
    category = _string(model.get("category"), "category")
    known = _terms(model.get("existing_facets"), "existing_facets")
    start = _day(model.get("window_start"), "window_start")
    end = _day(model.get("window_end"), "window_end")
    if end < start:
        raise ValueError("window_end precedes window_start")
    aliases = model.get("aliases", {})
    if not isinstance(aliases, dict):
        raise ValueError("aliases must map facet names to lists of phrases")
    synonyms = {_key(k): _terms(v, k) for k, v in aliases.items()}
    rows = sorted(_records(records, category), key=lambda row: row["id"])
    shoppers = [row for row in rows if row["role"] == "demand"
                and start <= _day(row["date"], "date") <= end]
    external = [row for row in rows if row["role"] == "external"]
    products = set()
    specs = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    labels = {}
    for row in rows:
        if row["role"] != "catalog":
            continue
        product = row["product_id"]
        products.add(product)
        for spec in extract_specs(row["text"]):
            if not (0 <= spec.start < spec.end <= len(row["text"])):
                raise ValueError(f"Invalid evidence span in {row['id']}")
            label = _key(_string(spec.label, "label"))
            value = _key(_string(spec.value, "value"))
            if not value or not label:
                raise ValueError(f"Empty normalized specification in {row['id']}")
            if label in known or any(label in synonyms.get(facet, ()) for facet in known):
                continue
            labels.setdefault(label, spec.label)
            specs[label][product][value].append(_evidence(row, spec.start, spec.end))

    candidates = []
    window_days = (end - start).days + 1
    for label, by_product in sorted(specs.items()):
        phrases = {label} | synonyms.get(label, set())
        def mentions(row):
            line = " " + _key(row["text"]) + " "
            return any(" " + phrase + " " in line for phrase in phrases)

        hits = [row for row in shoppers if mentions(row)]
        outside = [row for row in external if mentions(row)]
        if not hits and not outside:
            continue
        volume = sum(row.get("count", 1) for row in hits)
        by_channel = Counter()
        for row in hits:
            by_channel[row["source"]] += row.get("count", 1)
        candidate = dict(key=label.replace(" ", "_"), label=labels[label],
                         signal_origin="customer" if hits else "external_only",
                         status="candidate", demand_events=volume,
                         demand_by_source=dict(by_channel),
                         demand_records=[dict(id=row["id"], source=row["source"], text=row["text"],
                                              count=row.get("count", 1)) for row in hits],
                         external_records=[dict(id=row["id"], source=row["source"], text=row["text"])
                                           for row in outside],
                         products_with_mentions=len(by_product))
        if through != "discovery":
            assignable = sum(len(values) == 1 for values in by_product.values())
            candidate["forecast"] = dict(method="constant_rate", horizon_days=horizon_days,
                projected_demand_events=round(volume * horizon_days / window_days, 1) if hits else None,
                assignable_products=assignable, total_products=len(products))
        if through in ("induction", "usage"):
            assigned, conflicts = [], []
            for product, values in sorted(by_product.items()):
                if len(values) == 1:
                    value, evidence = next(iter(values.items()))
                    assigned.append(dict(product_id=product, value=value, evidence=evidence))
                else:
                    conflicts.append(dict(product_id=product, competing_values=dict(values)))
            candidate["induction"] = dict(values=sorted({a["value"] for a in assigned}),
                assignments=assigned, conflicts=conflicts,
                unknown_products=sorted(products.difference(by_product)))
        if through == "usage":
            preview = defaultdict(list)
            for assignment in candidate["induction"]["assignments"]:
                preview[assignment["value"]].append(assignment["product_id"])
            candidate["usage"] = dict(status="preview", product_ids_by_value=dict(preview))
        candidates.append(candidate)
    candidates.sort(key=lambda item: (-item["demand_events"], item["key"]))
    return dict(schema_version=1, category=category, through=through,
                window_start=start.isoformat(), window_end=end.isoformat(),
                window_days=window_days, inventory_products=len(products), candidates=candidates)
