"""Portable HTML preview. All external text is escaped and remains local."""
from html import escape


def _e(value):
    return escape(str(value))


def _sources(records):
    return "".join(f"<li><b>{_e(r['source'])}</b> · {_e(r['text'])}</li>" for r in records)


def _block(candidate):
    c = candidate
    parts = [f"<article><h2>{_e(c['label'])}</h2><h3>Découverte</h3>",
             f"<p><strong>{c['demand_events']}</strong> signaux clients · "
             f"{c['products_with_mentions']} produits avec une mention</p>",
             "<details><summary>Voir la demande et les sources externes</summary><ul>",
             _sources(c["demand_records"]), _sources(c["external_records"]), "</ul></details>"]
    if "forecast" in c:
        f = c["forecast"]
        volume = f["projected_demand_events"]
        estimate = (f"<strong>{volume:g}</strong> signaux sur {f['horizon_days']} jours à rythme constant."
                    if volume is not None else "Demande locale à mesurer.")
        parts.extend(["<h3>Prévision</h3>",
            f"<p>{estimate} "
            f"{f['assignable_products']} produits sur {f['total_products']} ont une valeur sans conflit.</p>"])
    if "induction" in c:
        data = c["induction"]
        parts.append("<h3>Induction</h3><p>" +
                     " · ".join(_e(v) for v in data["values"]) + "</p>")
        parts.append("<details><summary>Affectations et citations</summary><ul>")
        for assignment in data["assignments"]:
            for proof in assignment["evidence"]:
                parts.append(f"<li><b>{_e(assignment['product_id'])}</b> · "
                             f"<q>{_e(proof['quote'])}</q> "
                             f"<small>{_e(proof['record_id'])} [{proof['start']}, {proof['end']})</small></li>")
        parts.append("</ul></details>")
        for conflict in data["conflicts"]:
            parts.append(f"<p>À vérifier · {_e(conflict['product_id'])} · " +
                         " / ".join(_e(v) for v in conflict["competing_values"]) + "</p>")
        if data["unknown_products"]:
            parts.append("<p>À renseigner · " + ", ".join(map(_e, data["unknown_products"])) + "</p>")
    if "usage" in c:
        parts.append("<h3>Usage</h3><p>Aperçu du filtre par valeur</p>")
        for value, products in c["usage"]["product_ids_by_value"].items():
            parts.append(f"<details><summary>{_e(value)} <small>({len(products)})</small></summary>"
                         "<ul>" + "".join(f"<li>{_e(p)}</li>" for p in products) + "</ul></details>")
    return "".join(parts) + "</article>"


def render(report):
    cards = "".join(_block(c) for c in report["candidates"])
    return """<!doctype html><html lang="fr"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PILON · Filtres proposés</title><style>
*{box-sizing:border-box}body{margin:0;background:#f6f7fa;color:#202536;font:16px/1.55 system-ui,sans-serif}
main{max-width:820px;margin:auto;padding:36px 20px}header{color:#536080}h1{font-size:2rem;margin:.5em 0}
article{background:#fff;border:1px solid #dee2ea;border-radius:14px;padding:clamp(16px,4vw,32px);margin:20px 0}
h2{margin:0}h3{margin:1.5em 0 .3em;color:#354f7a}p{margin:.3em 0 .75em}small{color:#5a6476}
summary{cursor:pointer;padding:.45em 0}ul{padding-left:1.5em}li{margin:.45em 0}q{white-space:pre-wrap}
</style><main><header>PILON / Catalogue</header><h1>Filtres proposés</h1>""" + (
        ("<small>Démonstration · données fictives</small>" if report.get("synthetic") else "") +
        f"<p>{_e(report['category'])} · {report['inventory_products']} produits · "
        f"{_e(report['window_start'])} → {_e(report['window_end'])}</p>" +
        (cards or "<p>Aucun filtre candidat pour ces signaux et ce catalogue.</p>") + "</main></html>")
