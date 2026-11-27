"""Offline, read-only HTML view of a background-loop report.

``render_loop`` accepts the contract's JSON-like mapping: model, candidates,
extractions, projection (including projected_model), metrics, events and synthetic.
Collections may also be keyed mappings; benchmark.candidates is a fallback for
checkpoint reports. Missing snapshots are *unavailable*, never empty replacements.
The before/after tables compare the actual model snapshots, not change summaries.
Optional publication information is read from report.publication, then projection.
report.jobs supplies relative /jobs/<id> navigation in the local HTTP view. IDs
are URL-encoded, and all labels (including URLs in source text) remain plain text.
Optional report.geometry diagnostics are disclosed without charts or routing claims.
Metric presentation rounds floats to four significant digits; JSON stays exact.
No publication or evidence validation is inferred from a completed job. Unknown
fields remain inspectable in escaped technical details. This module does no I/O,
requires only the standard library, and never modifies the supplied report.
"""

from collections.abc import Mapping
from datetime import datetime, timezone
from html import escape
import json
from urllib.parse import quote


_LABELS = {
    "queued": "En attente", "pending": "En attente", "running": "En cours",
    "completed": "Traitement terminé", "complete": "Traitement terminé",
    "failed": "Échec du traitement", "error": "Erreur", "partial": "Résultat partiel",
    "cancelled": "Annulé", "needs_extraction": "Extraction à faire",
    "needs_review": "À vérifier", "ready": "Prêt pour révision",
    "proposed": "Proposition à vérifier", "published": "Publié",
    "not_published": "Non publié", "unpublished": "Non publié",
    "rolled_back": "Publication annulée", "blocked": "Bloqué",
    "unknown": "Non renseigné", "no_evidence": "Sans preuve disponible",
    "unresolved": "À résoudre", "conflict": "Conflit à vérifier",
    "schema_gap": "Filtre absent du modèle", "coverage_gap": "Produits à renseigner",
    "retrieval_gap": "Recherche à améliorer", "unresolved_intent": "Besoin à préciser",
    "lexical": "Routage lexical", "lexical_v1": "Routage lexical",
    "exhaustive": "Parcours exhaustif", "retrieval": "Sélection des sources",
    "extraction": "Extraction des valeurs", "selected": "Sources sélectionnées",
    "unselected": "Sources non sélectionnées", "unsupported": "Sources non prises en charge",
    "retrieval_seconds": "Sélection · durée mesurée (s)",
    "extraction_seconds": "Extraction · durée mesurée (s)",
    "retrieval_elapsed_seconds": "Sélection · durée mesurée (s)",
    "extraction_elapsed_seconds": "Extraction · durée mesurée (s)",
    "elapsed_seconds": "Durée mesurée (s)", "elapsed_ms": "Durée mesurée (ms)",
    "selected_records": "Enregistrements sélectionnés",
    "unselected_records": "Enregistrements non sélectionnés",
    "unsupported_records": "Enregistrements non pris en charge",
    "total_records": "Enregistrements disponibles", "extracted_records": "Enregistrements traités",
    "assignment_count": "Affectations rapportées", "conflict_count": "Conflits rapportés",
    "unknown_product_count": "Produits sans valeur", "top_k": "Limite de sélection",
    "adapter": "Adaptateur", "strategy": "Méthode", "method": "Méthode",
    "record_id": "Identifiant source", "product_id": "Produit", "source": "Source",
    "reason": "Motif", "status": "État", "value": "Valeur", "values": "Valeurs",
    "competing_values": "Valeurs contradictoires", "fact_key": "Clé du filtre",
    "candidate_key": "Clé du besoin", "asset_type": "Type de source",
    "text": "Texte", "document": "Document", "image": "Image",
    "empty": "Aucune exécution", "needs_definition": "Besoin à préciser",
    "search_integration_needed": "Recherche à faire évoluer", "backlog": "Besoins en attente",
    "input_records": "Enregistrements reçus", "catalog_assets": "Sources du catalogue",
    "supported_assets": "Sources prises en charge", "scored_assets": "Sources évaluées pour la sélection",
    "matched_assets": "Sources correspondantes", "selected_assets": "Sources sélectionnées",
    "unselected_assets": "Sources non sélectionnées", "unsupported_assets": "Sources non prises en charge",
    "excluded_assets": "Sources hors périmètre", "budget_skipped_assets": "Sources écartées par la limite",
    "truncated": "Sélection limitée", "embedding_calls": "Appels de vectorisation",
    "analyzed_assets": "Sources analysées", "extracted_claims": "Valeurs relevées",
    "matching_claims": "Valeurs liées au besoin", "evidence_count": "Citations rapportées",
    "assigned_products": "Produits avec une valeur", "conflicted_products": "Produits en conflit",
    "unknown_products": "Produits sans valeur établie", "analysis_status": "État d’analyse",
    "analysed": "Analysé", "unanalysed": "Non analysé", "excluded": "Sources hors périmètre",
    "explicit_extractor_required": "Adaptateur explicite requis pour cette source",
    "document_text_unavailable": "Texte du document indisponible",
    "no_lexical_match": "Aucune correspondance lexicale", "lexical_match": "Correspondance lexicale",
    "budget_limit": "Limite de sélection atteinte", "not_catalog": "Source hors catalogue",
    "outside_category": "Autre catégorie", "cosine": "Classement par similarité cosinus",
    "cosine_rank": "Classement par similarité cosinus", "cosine_then_lexical": "Similarité cosinus puis routage lexical",
    "score": "Score de sélection", "matched_aliases": "Expressions correspondantes",
    "benchmark": "Benchmark", "extract": "Extract", "projection": "Projection du modèle",
    "done": "Terminé", "candidate_count": "Besoins candidats", "source_records": "Sources disponibles",
    "inventory_products": "Produits du catalogue", "llm_calls": "Appels à un modèle de langage",
    "api_cost_usd": "Coût API rapporté (USD)", "provider": "Adaptateur de traitement",
    "geometry": "Traitement géométrique", "reused_stages": "Étapes réutilisées",
    "demand_events": "Événements de demande", "detector": "Détecteur de besoins",
    "not_available": "Diagnostic indisponible", "available": "Diagnostic disponible",
    "not_run": "Non exécuté", "noembedding": "Aucun vecteur fourni",
    "not_run_without_supplied_vectors": "Non exécuté · vecteurs fournis requis",
    "candidate_missing_embedding": "Aucun vecteur fourni pour ce besoin",
    "candidate_missing_embedding_contract": "Description des vecteurs du besoin manquante",
    "no_compatible_record_embeddings": "Aucun vecteur de source compatible",
    "landmark_count": "Sources repères examinées", "eligible_record_count": "Sources compatibles",
    "record_embeddings_inspected": "Vecteurs de sources examinés",
    "target_distance_evaluations": "Distances au besoin calculées",
    "pairwise_distance_evaluations": "Distances entre sources calculées",
    "mst_edges": "Liaisons de l’arbre calculées", "external_calls": "Appels externes",
    "not_requested": "Non demandé", "local_baseline": "Traitement local de référence",
    "unknown_product": "Produit sans valeur établie", "superseded": "Remplacé par une publication plus récente",
}


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _list(value):
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _entries(value, key="key"):
    """Accept contract lists and keyed checkpoint dictionaries without mutation."""
    if isinstance(value, Mapping):
        if key in value:
            return [dict(value)]
        return [dict(item, **{key: item.get(key, name)}) if isinstance(item, Mapping)
                else {key: name, "value": item} for name, item in value.items()]
    return [dict(item) if isinstance(item, Mapping) else {key: item}
            for item in _list(value)]


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _display(value):
    if value is None:
        return "Non renseigné"
    if value is True:
        return "Oui (valeur explicite)"
    if value is False:
        return "Non (valeur explicite)"
    if isinstance(value, (Mapping, list, tuple)):
        return _json(value)
    return str(value)


def _e(value):
    return escape(_display(value), quote=True)


def _label(value):
    return _LABELS.get(str(value), _display(value))


def _status(value=None):
    tone = "neutral"
    if value in ("failed", "error", "blocked", "conflict"):
        tone = "danger"
    elif value in ("needs_review", "partial", "needs_extraction", "no_evidence", "unresolved"):
        tone = "warning"
    elif value in ("published", "completed", "complete"):
        tone = "success"
    return f'<span class="badge {tone}">{_e(_label(value))}</span>'


def _empty(message):
    return f'<p class="empty">{_e(message)}</p>'


def _details(title, value):
    return f'<details class="technical"><summary>{_e(title)}</summary><pre>{_e(_json(value))}</pre></details>'


def _fields(value, *, empty="Aucune information renseignée."):
    data = _mapping(value)
    if not data:
        return _empty(empty)
    return '<dl class="facts">' + "".join(
        f'<div><dt>{_e(_label(key))}</dt><dd>{_e(item)}</dd></div>'
        for key, item in data.items()) + '</dl>'


def _evidence(value, *, demand=False):
    proofs = _list(value)
    if not proofs:
        return _empty("Aucune citation renseignée.")
    parts = ['<ul class="evidence">']
    for proof in proofs:
        if not isinstance(proof, Mapping):
            parts.append(f'<li>{_e(proof)}</li>')
            continue
        quote = proof.get("quote", proof.get("text"))
        parts.append('<li>')
        if quote is not None:
            parts.append(f'<blockquote>{_e(quote)}</blockquote>')
        else:
            parts.append('<p>Citation non renseignée.</p>')
        parts.append(f'<p class="source">{_e(proof.get("source", "Source non renseignée"))}</p>')
        parts.append('<div class="source-meta">')
        if "record_id" in proof or "id" in proof:
            parts.append(f'<span>Référence : <code>{_e(proof.get("record_id", proof.get("id")))}</code></span>')
        if "start" in proof and "end" in proof:
            parts.append(f'<span>Position : [{_e(proof["start"])}, {_e(proof["end"])})</span>')
        if "asset_type" in proof:
            parts.append(f'<span>{_e(_label(proof["asset_type"]))}</span>')
        parts.append('</div></li>')
    parts.append('</ul>')
    if demand:
        parts.append('<p class="help">Ces signaux décrivent une demande client ; ils ne prouvent aucune propriété produit.</p>')
    return "".join(parts)


def _table(caption, headings, rows):
    return (f'<div class="table-scroll" role="region" aria-label="{_e(caption)}" tabindex="0">'
            f'<table><caption>{_e(caption)}</caption><thead><tr>'
            + "".join(f'<th scope="col">{_e(h)}</th>' for h in headings)
            + '</tr></thead><tbody>'
            + "".join('<tr>' + "".join(f'<td>{cell}</td>' for cell in row) + '</tr>' for row in rows)
            + '</tbody></table></div>')


def _candidate(candidate, index, extraction=None):
    label = candidate.get("label", candidate.get("key", "Besoin sans libellé"))
    state = _mapping(extraction).get("status", candidate.get("status", "needs_extraction"))
    parts = [f'<article class="card" aria-labelledby="candidate-{index}">',
             f'<div class="card-top"><h3 id="candidate-{index}">{_e(label)}</h3>',
             _status(state), '</div>']
    if candidate.get("definition"):
        parts.append(f'<p>{_e(candidate["definition"])}</p>')
    parts.append(f'<p class="gap">{_e(_label(candidate.get("gap_type", "Besoin à qualifier")))}</p>')
    if extraction is not None:
        count = len(_entries(_mapping(extraction).get("assignments"), "product_id"))
        parts.append(f'<p class="help">Besoin conservé · {count} valeur(s) produit rapportée(s).</p>'
                     if count else '<p class="help">Besoin conservé · aucune valeur produit disponible.</p>')
    else:
        parts.append('<p class="help">Besoin conservé · extraction non disponible.</p>')
    parts.append('<dl class="facts"><div><dt>Événements de demande</dt>'
                 f'<dd>{_e(candidate.get("demand_events"))}</dd></div><div><dt>Clé du besoin</dt>'
                 f'<dd><code>{_e(candidate.get("key"))}</code></dd></div></dl>')
    parts.append('<details><summary>Comprendre la demande</summary>'
                 + _evidence(candidate.get("demand_records"), demand=True) + '</details>')
    parts.append(_details("Détails du besoin", candidate) + '</article>')
    return "".join(parts)


def _metric_value(value):
    """Round presentation only; never alter values, evidence or exact JSON."""
    if isinstance(value, float):
        return format(value, ".4g").replace(".", ",")
    if isinstance(value, Mapping):
        return {key: _metric_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_metric_value(item) for item in value]
    if isinstance(value, bool):
        return "Oui" if value else "Non"
    return value


def _metric_summary(data):
    retrieval, extraction = _mapping(data.get("retrieval")), _mapping(data.get("extraction"))
    values = []
    if "selected_assets" in retrieval:
        selected = _display(_metric_value(retrieval["selected_assets"]))
        if "supported_assets" in retrieval:
            supported = _display(_metric_value(retrieval["supported_assets"]))
            values.append(("Sources sélectionnées / prises en charge", f"{selected} / {supported}"))
        else:
            values.append(("Sources sélectionnées", selected))
    for key in ("assigned_products", "conflicted_products", "unknown_products"):
        if key in extraction:
            values.append((_label(key), _metric_value(extraction[key])))
    for label, source in (("Sélection", retrieval), ("Extraction", extraction), ("Total", data)):
        duration = source.get("elapsed_seconds")
        if type(duration) in (int, float):
            amount, unit = (duration * 1000, "ms") if 0 < duration < 1 else (duration, "s")
            values.append((label, f"{_metric_value(float(amount))} {unit}"))
    for key in ("geometry", "provider"):
        if key in data and not isinstance(data[key], Mapping):
            values.append((_label(key), _label(data[key])))
    return ('<p class="metric-summary">' + "".join(
        f'<span>{_e(label)} : <strong>{_e(value)}</strong></span>' for label, value in values) + '</p>') if values else ""


def _metrics(metrics):
    data = _mapping(metrics)
    if not data:
        return _empty("Mesures non disponibles à ce stade.")
    parts = []
    scalars = {}
    for key, value in data.items():
        if isinstance(value, Mapping):
            parts.append(f'<div class="metric-group"><h5>{_e(_label(key))}</h5>{_fields(_metric_value(value))}</div>')
        else:
            scalars[key] = _label(value) if key in ("geometry", "provider", "status") else _metric_value(value)
    if scalars:
        parts.insert(0, _fields(scalars))
    return (_metric_summary(data) + '<details class="metric-details"><summary>Mesures détaillées</summary>'
            + "".join(parts) + _details("Mesures exactes · JSON", metrics) + '</details>')


def _routing(routing):
    data = _mapping(routing)
    if not data:
        return _empty("Routage non renseigné.")
    parts = []
    method = {key: data[key] for key in ("adapter", "method", "strategy", "mode", "top_k", "exhaustive") if key in data}
    if method:
        parts.append(_fields({key: _label(value) if isinstance(value, str) else value for key, value in method.items()}))
    for key in ("selected", "unselected", "unsupported", "excluded"):
        if key not in data:
            continue
        value = data[key]
        parts.append(f'<details><summary>{_e(_label(key))}</summary>')
        if isinstance(value, (list, tuple, Mapping)):
            entries = _entries(value, "record_id")
            parts.append('<ul class="review-list">' + "".join(
                '<li>' + _fields({k: _label(v) if k in ("reason", "analysis_status", "asset_type", "method") else v
                                  for k, v in item.items()}) + '</li>' for item in entries) + '</ul>'
                if entries else _empty("Aucune source dans cette liste."))
        else:
            parts.append(f'<p>{_e(value)}</p>')
        parts.append('</details>')
    parts.append(_details("Routage complet et motifs de sélection", routing))
    return "".join(parts)


def _assignments(assignments):
    entries = _entries(assignments, "product_id")
    if not entries:
        return _empty("Aucune valeur produit extraite. Le besoin reste à traiter.")
    rows = []
    for entry in entries:
        rows.append((_e(entry.get("product_id")),
                     f'<strong class="value">{_e(entry.get("value"))}</strong>'
                     + _status(entry.get("status", "needs_review")),
                     _evidence(entry.get("evidence"))))
    return _table("Valeurs extraites et citations rapportées", ("Produit", "Valeur / révision", "Sources à examiner"), rows)


def _review_list(items, empty):
    values = _list(items)
    if not values:
        return _empty(empty)
    parts = ['<ul class="review-list">']
    for item in values:
        parts.append('<li>')
        if isinstance(item, Mapping):
            competing = item.get("competing_values")
            hidden = {"evidence", "competing_values"} if isinstance(competing, Mapping) else {"evidence"}
            parts.append(_fields({k: _label(v) if k in ("status", "reason") else v
                                  for k, v in item.items() if k not in hidden}))
            if isinstance(competing, Mapping):
                for value, evidence in competing.items():
                    parts.append(f'<p><strong>Valeur en conflit : {_e(value)}</strong></p>' + _evidence(evidence))
            if "evidence" in item:
                parts.append(_evidence(item["evidence"]))
        else:
            parts.append(_e(item))
        parts.append('</li>')
    return "".join(parts) + '</ul>'


def _blocked(items):
    values = _list(items)
    content = _review_list(values, "Aucun blocage renseigné. Cela ne vaut pas validation de la proposition.")
    if len(values) <= 3:
        return content
    return (f'<details class="blocked-details"><summary>{len(values)} changements bloqués · voir les motifs</summary>'
            + content + '</details>')


def _extraction(result, label, index):
    parts = [f'<article class="card" aria-labelledby="extraction-{index}">',
             f'<div class="card-top"><h3 id="extraction-{index}">{_e(label)}</h3>',
             _status(result.get("status")), '</div>']
    if result.get("error"):
        parts.append(f'<div class="notice danger"><strong>Extraction interrompue</strong><p>{_e(result["error"])}</p></div>')
    parts.append('<h4>Valeurs et preuves produit</h4>' + _assignments(result.get("assignments")))
    parts.append('<div class="two-col"><div><h4>Produits sans valeur établie</h4>'
                 + _review_list(result.get("unknown_products"), "Aucun produit sans valeur signalé.")
                 + '</div><div><h4>Valeurs en conflit</h4>'
                 + _review_list(result.get("conflicts"), "Aucun conflit signalé.") + '</div></div>')
    if "unanalysed_products" in result:
        parts.append('<h4>Produits non analysés ou partiellement analysés</h4>'
                     '<p class="help">Au moins une source manque ou n’a pas été analysée. '
                     'Un produit peut déjà avoir une valeur issue d’une autre source.</p>'
                     + _review_list(result["unanalysed_products"], "Aucun produit non analysé signalé."))
    parts.append('<h4>Sélection et traitement des sources</h4>' + _routing(result.get("routing")))
    parts.append('<h4>Mesures rapportées</h4>' + _metrics(result.get("metrics")))
    parts.append(_details("Résultat technique de l’extraction", result) + '</article>')
    return "".join(parts)


def _facet_map(model):
    facets = {}
    for entry in _entries(model.get("existing_facets")) + _entries(model.get("facets")):
        key = _display(entry.get("key", entry.get("fact_key", entry.get("label", "Sans clé"))))
        facets[key] = dict(facets.get(key, {}), **entry)
    return facets


def _assignment_map(model):
    assignments = {}
    for entry in _entries(model.get("assignments"), "product_id"):
        key = (_display(entry.get("fact_key", entry.get("candidate_key", entry.get("key")))),
               _display(entry.get("product_id")))
        assignments.setdefault(key, []).append(entry)
    return assignments


def _facet_cell(value, available):
    if not available:
        return '<span class="muted">Instantané indisponible</span>'
    if value is None:
        return '<span class="muted">Filtre absent</span>'
    return (f'<strong>{_e(value.get("label", value.get("key")))}</strong>'
            f'<p>{_e(value.get("definition", "Définition non renseignée"))}</p>'
            f'<p><span class="muted">Valeurs : </span>{_e(value.get("values", "Non renseignées"))}</p>')


def _assignment_cell(values, available):
    if not available:
        return '<span class="muted">Instantané indisponible</span>'
    if values is None:
        return '<span class="muted">Aucune affectation</span>'
    return "".join(f'<div class="snapshot-value"><strong class="value">{_e(value.get("value"))}</strong>'
                   + _status(value.get("status", "needs_review"))
                   + _evidence(value.get("evidence")) + '</div>' for value in values)


def _change(before, after, comparable):
    if not comparable:
        return '<span class="badge neutral">Comparaison indisponible</span>'
    if before is None:
        label, tone = "Ajout", "success"
    elif after is None:
        label, tone = "Retrait", "danger"
    elif before != after:
        label, tone = "Modification", "warning"
    else:
        label, tone = "Identique", "neutral"
    return f'<span class="badge {tone}">{label}</span>'


def _snapshot_diff(before, after):
    before_available, after_available = isinstance(before, Mapping), isinstance(after, Mapping)
    base, proposed = _mapping(before), _mapping(after)
    comparable = before_available and after_available
    parts = []
    if not comparable:
        parts.append('<div class="notice warning">Comparaison incomplète : un instantané du modèle est indisponible. '
                     'Aucun ajout ni retrait ne peut en être déduit.</div>')
    parts.append('<div class="two-col snapshot-heads">')
    for name, model, available in (("Avant · modèle de référence", base, before_available),
                                   ("Après · modèle proposé", proposed, after_available)):
        parts.append(f'<div><h4>{name}</h4>')
        parts.append(_fields({"Catégorie": model.get("category"), "Version": model.get("version")})
                     if available else _empty("Instantané indisponible."))
        parts.append('</div>')
    parts.append('</div><h4>Évolution des filtres</h4>')
    old_facets, new_facets = _facet_map(base), _facet_map(proposed)
    rows = [(_e(key), _facet_cell(old_facets.get(key), before_available),
             _facet_cell(new_facets.get(key), after_available),
             _change(old_facets.get(key), new_facets.get(key), comparable))
            for key in sorted(old_facets.keys() | new_facets.keys())]
    parts.append(_table("Schéma · comparaison des instantanés", ("Filtre", "Avant", "Après proposé", "Évolution"), rows)
                 if rows else _empty("Aucun filtre renseigné dans les instantanés disponibles."))
    parts.append('<h4>Évolution des valeurs par produit</h4>')
    old_assignments, new_assignments = _assignment_map(base), _assignment_map(proposed)
    rows = [(f'<strong>{_e(key[1])}</strong><br><code>{_e(key[0])}</code>',
             _assignment_cell(old_assignments.get(key), before_available),
             _assignment_cell(new_assignments.get(key), after_available),
             _change(old_assignments.get(key), new_assignments.get(key), comparable))
            for key in sorted(old_assignments.keys() | new_assignments.keys())]
    parts.append(_table("Affectations · valeurs et preuves avant / après",
                        ("Produit / filtre", "Avant", "Après proposé · à vérifier", "Évolution"), rows)
                 if rows else _empty("Aucune affectation produit renseignée dans les instantanés disponibles."))
    parts.append('<div class="two-col">' + _details("Instantané complet avant", before)
                 + _details("Instantané complet après", after) + '</div>')
    return "".join(parts)


def _publication(report, projection):
    publication = report.get("publication", projection.get("publication"))
    if isinstance(publication, Mapping):
        status = publication.get("status")
    elif isinstance(publication, str):
        status = publication
    else:
        status = report.get("publication_status", projection.get("publication_status"))
    parts = ['<div class="publication"><div><h3>Publication du modèle</h3>', _status(status), '</div>',
             '<p>La projection est une proposition. La publication et le retour à un instantané antérieur '
             'sont des opérations explicites, distinctes du traitement.</p>']
    if status is None:
        parts.append('<p class="help">Ce rapport ne renseigne pas l’état de publication du modèle.</p>')
    if publication is not None:
        parts.append(_details("Informations de publication", publication))
    parts.append('</div>')
    return "".join(parts)


def _geometry(value, labels):
    entries = _entries(value, "candidate_key")
    if not entries:
        return ""
    parts = ['<article class="card"><details><summary>Diagnostic géométrique facultatif</summary>',
             '<p class="help">Inspection locale des vecteurs fournis. Ce diagnostic ne modifie pas le routage '
             'et ne mesure pas la précision des valeurs extraites. Les résultats portent uniquement sur les sources examinées.</p>']
    for entry in entries:
        key = _display(entry.get("candidate_key"))
        parts.append(f'<h4>{_e(labels.get(key, key))}</h4>' + _status(entry.get("status")))
        if entry.get("reason"):
            parts.append(f'<p>{_e(_label(entry["reason"]))}</p>')
        if entry.get("status") == "not_available":
            parts.append(_empty("Aucun résultat géométrique exploitable pour ce besoin."))
        else:
            scope = _mapping(entry.get("scope"))
            parts.append(_fields({k: scope[k] for k in ("eligible_record_count", "landmark_count") if k in scope}))
        parts.append(_metrics(entry.get("metrics")))
        parts.append(_details("Diagnostic complet · périmètre, calculs et limites", entry))
    return "".join(parts) + '</details></article>'


def _timestamp(value):
    if type(value) in (int, float):
        try:
            return datetime.fromtimestamp(value, timezone.utc).strftime("%d/%m/%Y à %H:%M UTC")
        except (OverflowError, OSError, ValueError):
            pass
    return value


def _job_navigation(report):
    jobs = _entries(report.get("jobs"), "id")
    if not jobs:
        return ""
    parts = ['<details class="job-nav" open><summary>Exécutions enregistrées</summary>',
             '<nav aria-label="Navigation entre les exécutions">']
    for job in jobs:
        job_id = job.get("id")
        # IDs never become a scheme, host, query, fragment or path traversal.
        valid_id = isinstance(job_id, str) and job_id not in ("", ".", "..")
        current = ' aria-current="page"' if job_id == report.get("id") else ""
        parts.append(f'<a href="/jobs/{escape(quote(job_id, safe=""), quote=True)}"{current}>'
                     if valid_id else '<div class="job-link">')
        parts.append(f'<strong>{_e(job_id)}</strong><small>{_e(_label(job.get("status")))}</small>')
        if job.get("stage"):
            parts.append(f'<small>Étape : {_e(_label(job["stage"]))}</small>')
        if job.get("updated") is not None:
            parts.append(f'<small>Mis à jour : {_e(_timestamp(job["updated"]))}</small>')
        if job.get("error"):
            parts.append(f'<small>Erreur : {_e(job["error"])}</small>')
        parts.append('</a>' if valid_id else '</div>')
    parts.append('</nav><p>Navigation disponible dans l’interface locale.</p></details>')
    return "".join(parts)


_CSS = """
:root{color-scheme:light;--ink:#18302b;--muted:#566a63;--paper:#f2f5f1;--line:#d4dfd7;
--accent:#24624d;--soft:#e7f1eb;--amber:#76510b;--red:#9c3333}
*{box-sizing:border-box}html{scroll-padding-top:30px}body{margin:0;background:var(--paper);color:var(--ink);
font:17px/1.65 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-wrap:anywhere}
a{color:var(--accent);text-underline-offset:4px}a:hover{text-decoration-thickness:2px}
:focus-visible{outline:3px solid #aa591c;outline-offset:4px}button,summary,a{-webkit-tap-highlight-color:transparent}
.skip{position:absolute;top:12px;left:12px;z-index:10;padding:12px 20px;background:white;transform:translateY(-180%)}
.skip:focus{transform:none}.layout{display:grid;grid-template-columns:244px minmax(0,1fr);min-height:100vh}
.sidebar{padding:34px 22px;background:#173f33;color:white;position:sticky;top:0;height:100vh;display:flex;flex-direction:column;overflow-y:auto}
.brand{font-size:28px;font-weight:850;letter-spacing:.14em}.brand-dot{color:#b6d989}.sidebar p{color:#d2e2d8;font-size:14px}
nav{display:grid;gap:10px;margin-top:38px}nav a{display:block;border:1px solid #517164;border-radius:12px;padding:14px;color:white;text-decoration:none}
nav a:hover,nav a:focus{background:#2b5747}nav strong{display:block;font-size:18px}nav span{font-size:13px;color:#d2e2d8}
.job-nav{margin-top:28px;border-color:#517164}.job-nav summary{color:#e1f0e6;font-size:13px}.job-nav nav{margin-top:8px;gap:8px}.job-nav a,.job-link{padding:10px}.job-nav strong{font:12px/1.6 ui-monospace,Consolas,monospace}.job-nav small{display:block;font-size:11px;color:#d2e2d8}.job-nav a[aria-current=page]{background:#2b5747;border-color:#b6d989}.job-nav p{font-size:11px}
.sidebar-foot{margin-top:auto;padding-top:36px}.sidebar-foot small{display:block;color:#d2e2d8}.workspace{min-width:0;padding:40px clamp(20px,4vw,64px) 70px;max-width:1680px;width:100%;margin:auto}
.eyebrow{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.15em;color:var(--accent)}
.hero{margin:12px 0 28px}.hero h1{font-size:clamp(30px,3.3vw,48px);letter-spacing:-.035em;line-height:1.15;margin:12px 0 18px;max-width:850px}
.hero p{max-width:800px;color:var(--muted);margin:0 0 20px}.job-line{display:flex;gap:12px;align-items:center;flex-wrap:wrap;color:var(--muted);font-size:14px}
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:26px 0 42px}
.stat{border:1px solid var(--line);border-radius:15px;background:white;padding:22px}.stat strong{display:block;font-size:34px;line-height:1.3;font-weight:750}.stat span{color:var(--muted);font-size:14px}
.stage{margin:46px 0 62px;scroll-margin-top:26px}.stage:target>.stage-heading{border-color:var(--accent)}
.stage-heading{display:flex;gap:18px;align-items:flex-start;border-bottom:2px solid var(--line);padding-bottom:22px;margin-bottom:24px}
.step{display:grid;place-items:center;width:46px;height:46px;flex:none;background:var(--accent);color:white;border-radius:14px;font-size:15px;font-weight:800}
h2{font-size:30px;letter-spacing:-.025em;line-height:1.25;margin:0 0 8px}h3{font-size:22px;line-height:1.35;margin:0 0 14px}h4{font-size:18px;margin:30px 0 12px}h5{font-size:16px;margin:12px 0}.stage-heading p{margin:0;color:var(--muted);max-width:830px}
.card{padding:clamp(20px,3vw,34px);background:white;border:1px solid var(--line);border-radius:20px;margin:20px 0;box-shadow:0 5px 18px #173f3305;min-width:0}
.card-top{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap}.card-top h3{margin:0}.card p{margin:12px 0}.gap{font-weight:650;color:var(--accent)}
.badge{display:inline-block;max-width:100%;border-radius:7px;background:#edf0ed;color:#4e5f58;padding:4px 9px;font-size:12px;font-weight:700;line-height:1.6;vertical-align:middle}
.success{background:#e3f1e6;color:#275d37}.warning{background:#fff1d3;color:#76510b}.danger{background:#fbe9e6;color:#913434}
.notice{border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:12px;padding:18px 22px;margin:20px 0;background:#e8f0ea}
.notice.warning{background:#fff4df;border-left-color:#a27622}.notice.danger{background:#fbe9e6;border-left-color:#9c3333}.notice p{margin:8px 0 0}
.empty{padding:20px;border:1px dashed #bccdc1;border-radius:10px;background:#f7f9f6;color:var(--muted)}
.help,.muted{color:var(--muted);font-size:14px}.two-col{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}.two-col>*{min-width:0}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(180px,100%),1fr));gap:14px 24px;margin:18px 0}.facts div{min-width:0}.facts dt{font-size:13px;color:var(--muted)}.facts dd{margin:5px 0 0;font-weight:650;white-space:pre-wrap}
.metric-summary{display:flex;flex-wrap:wrap;gap:6px 20px;font-size:14px;color:var(--muted)}.metric-summary strong{color:var(--ink);font-variant-numeric:tabular-nums}
details{border-top:1px solid var(--line);margin:16px 0 0}summary{cursor:pointer;min-height:48px;padding:12px 6px;font-size:15px;font-weight:650;color:var(--accent)}details[open]>summary{margin-bottom:10px}.technical summary{color:var(--muted);font-size:13px}
pre{font:12px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f0;padding:16px;border-radius:10px;max-height:460px;overflow:auto}
code{font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;color:#455e54}.table-scroll{overflow:auto;margin:16px 0;border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;text-align:left;font-size:15px;min-width:640px}
caption{text-align:left;padding:14px 18px;font-size:13px;color:var(--muted);background:#f7f9f6}th{background:#edf3ec;font-size:12px;letter-spacing:.025em;color:#365447;padding:14px 18px;border-bottom:1px solid var(--line)}td{padding:20px 18px;vertical-align:top;border-bottom:1px solid var(--line);min-width:120px}tbody tr:last-child td{border-bottom:0}td p{font-size:14px}td:nth-child(2),td:nth-child(3){min-width:210px}
.value{display:block;font-size:18px;margin-bottom:10px;white-space:pre-wrap}.evidence{list-style:none;padding:0;margin:16px 0}.evidence li{border-left:3px solid #bfd6c2;padding:0 0 0 14px;margin:18px 0}blockquote{margin:0;white-space:pre-wrap;font-size:15px}.source{font-size:12px;font-weight:650;color:var(--accent)}.source-meta{display:flex;gap:4px 12px;flex-wrap:wrap;font-size:11px;color:var(--muted)}.review-list{padding-left:20px}.review-list>li{padding:6px 0}.snapshot-heads>div{background:#f2f6f0;border-radius:12px;padding:6px 20px}.snapshot-value+.snapshot-value{border-top:1px solid var(--line);padding-top:16px}.publication{padding:24px;border:1px solid #b9cfbe;border-radius:14px;background:#f1f7ef;margin-bottom:26px}.publication>div{display:flex;gap:16px;justify-content:space-between;flex-wrap:wrap}.publication h3{margin:0}.publication p{font-size:15px}.footer{border-top:1px solid var(--line);padding-top:22px;color:var(--muted);font-size:13px}
@media(min-width:1500px){.candidate-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.candidate-grid .card{margin:0}}
@media(max-width:1000px){.layout{grid-template-columns:196px minmax(0,1fr)}.sidebar{padding:28px 16px}.workspace{padding:28px 24px 50px}.two-col{grid-template-columns:1fr;gap:12px}.stats{gap:10px}.stat{padding:16px}}
@media(max-width:740px){.layout{display:block}.sidebar{position:static;height:auto;padding:18px 20px}.brand{font-size:22px}.sidebar>p,.sidebar-foot{display:none}nav{grid-template-columns:repeat(3,minmax(0,1fr));margin-top:14px;gap:8px}nav a{padding:10px}nav strong{font-size:14px}nav span{display:none}.workspace{padding:24px 16px 40px}.stats{grid-template-columns:1fr}.stat{display:flex;align-items:center;gap:18px}.stat strong{font-size:28px;min-width:46px}.stage{margin:34px 0 44px}.stage-heading{gap:12px}h2{font-size:26px}.card{border-radius:14px}.hero h1{font-size:34px}.step{width:38px;height:38px}.publication{padding:18px}}
@media print{.layout{display:block}.sidebar,.skip{display:none}.workspace{max-width:none;padding:0}.card{box-shadow:none;break-inside:avoid}.table-scroll{overflow:visible}table{min-width:0}.stage{margin:24px 0}details{display:block}.badge{border:1px solid #aaa}.stats{margin-bottom:20px}}
"""


def render_loop(report) -> str:
    """Render a portable French dashboard, including incomplete/error checkpoints.

    Publication status must be explicit (``publication.status`` or
    ``publication_status``); a job's ``status`` never stands in for publication.
    Extraction and projection values are displayed as reported, not revalidated.
    Only job IDs generate links, under a fixed relative path with URL encoding.
    Source text is never interpreted as markup, a URL, a style or a script.
    """
    report = _mapping(report)
    benchmark = _mapping(report.get("benchmark"))
    candidates = _entries(report.get("candidates", benchmark.get("candidates")))
    extractions = _entries(report.get("extractions"), "candidate_key")
    projection = _mapping(report.get("projection"))
    model = report.get("model")
    base_model = projection.get("base_model", model)
    labels = {_display(c.get("key")): c.get("label", c.get("key")) for c in candidates}
    by_candidate = {_display(e.get("candidate_key")): e for e in extractions}
    assignment_count = sum(len(_entries(e.get("assignments"), "product_id")) for e in extractions)
    parts = ['<!doctype html><html lang="fr"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<title>PILON · Boucle de connaissance</title><style>', _CSS, '</style></head><body>',
             '<a class="skip" href="#main">Aller au contenu</a><div class="layout">',
             '<aside class="sidebar"><div class="brand">PILON<span class="brand-dot">.</span></div>',
             '<p>La connaissance produit,<br>en continu.</p><nav aria-label="Étapes de la boucle">',
             '<a href="#benchmark"><strong>01 &nbsp; Benchmark</strong><span>Comprendre les besoins</span></a>',
             '<a href="#extract"><strong>02 &nbsp; Extract</strong><span>Examiner les preuves</span></a>',
             '<a href="#ingest"><strong>03 &nbsp; Ingest</strong><span>Réviser le modèle</span></a></nav>',
             _job_navigation(report),
             '<div class="sidebar-foot"><strong>Rapport local</strong><small>Lecture seule · sans ressource distante</small></div>',
             '</aside><main id="main" class="workspace"><header class="hero">',
             '<div class="eyebrow">Atelier de connaissance produit</div>',
             '<h1>Des besoins clients<br>aux valeurs documentées.</h1>',
             '<p>Repérez les manques du catalogue, examinez les sources et révisez les changements proposés au modèle.</p>',
             '<div class="job-line">', _status(report.get("status")),
             f'<span>Exécution : <code>{_e(report.get("id", "Non renseignée"))}</code></span>',
             f'<span>Catégorie : {_e(_mapping(model).get("category"))}</span></div></header>']
    if report.get("synthetic"):
        parts.append('<div class="notice warning"><strong>Démonstration · données synthétiques</strong>'
                     '<p>Ces exemples illustrent le parcours. Ils ne mesurent ni la précision ni la couverture sur un catalogue réel.</p></div>')
    if report.get("error") or report.get("errors") or report.get("status") in ("failed", "error"):
        parts.append('<div class="notice danger"><strong>Le traitement a rencontré une erreur</strong>'
                     f'<p>{_e(report.get("error", report.get("errors", "Consultez les événements du traitement.")))}</p>'
                     '<p>Les résultats déjà disponibles restent consultables ci-dessous.</p></div>')
    parts.append('<div class="stats" aria-label="Éléments disponibles dans ce rapport">')
    for count, label in ((len(candidates), "Besoins candidats"), (len(extractions), "Résultats d’extraction"),
                         (assignment_count, "Affectations extraites · non publiées par cette vue")):
        parts.append(f'<div class="stat"><strong>{count}</strong><span>{label}</span></div>')
    parts.append('</div><section class="stage" id="benchmark" aria-labelledby="benchmark-title">'
                 '<div class="stage-heading"><span class="step" aria-hidden="true">01</span><div>'
                 '<h2 id="benchmark-title">Benchmark</h2><p>Quels besoins restent mal servis ? '
                 'Un besoin sans preuve produit reste visible. Cette étape ne répond pas aux requêtes des clients.</p></div></div>')
    parts.append('<div class="candidate-grid">' + "".join(
        _candidate(c, i, by_candidate.get(_display(c.get("key")))) for i, c in enumerate(candidates)) + '</div>'
                 if candidates else _empty("Aucun besoin candidat disponible. Le traitement peut être en attente ou n’avoir identifié aucun besoin."))
    parts.append('</section><section class="stage" id="extract" aria-labelledby="extract-title">'
                 '<div class="stage-heading"><span class="step" aria-hidden="true">02</span><div>'
                 '<h2 id="extract-title">Extract</h2><p>Quelles valeurs les sources permettent-elles de proposer ? '
                 'La sélection des sources et l’extraction sont deux opérations distinctes.</p></div></div>'
                 '<div class="notice"><strong>Lire les résultats sans confondre absence et preuve</strong>'
                 '<p>Une source non sélectionnée ou non prise en charge ne prouve pas l’absence d’une propriété. '
                 'Une valeur négative explicite reste distincte d’une valeur inconnue.</p>'
                 '<p class="help">Les mesures affichées proviennent du rapport, sans estimation de gain ni de rappel. '
                 'Aucune exécution TDA/ANN ou validation sémantique n’est présumée par cette vue.</p></div>')
    if extractions:
        for index, result in enumerate(extractions):
            key = _display(result.get("candidate_key"))
            parts.append(_extraction(result, labels.get(key, result.get("candidate_key", "Extraction sans besoin associé")), index))
    else:
        parts.append(_empty("Aucun résultat d’extraction disponible. Les besoins candidats sont conservés dans Benchmark."))
    extracted = {_display(result.get("candidate_key")) for result in extractions}
    waiting = [c for c in candidates if _display(c.get("key")) not in extracted]
    if waiting:
        parts.append('<article class="card"><h3>Besoins en attente de preuves</h3><ul class="review-list">'
                     + "".join(f'<li>{_e(c.get("label", c.get("key")))} · extraction non disponible</li>' for c in waiting)
                     + '</ul></article>')
    parts.append(_geometry(report.get("geometry"), labels))
    parts.append('</section><section class="stage" id="ingest" aria-labelledby="ingest-title">'
                 '<div class="stage-heading"><span class="step" aria-hidden="true">03</span><div>'
                 '<h2 id="ingest-title">Ingest</h2><p>Que changerait cette proposition ? '
                 'Comparez le schéma, les valeurs et leurs citations avant toute publication.</p></div></div>')
    parts.append(_publication(report, projection))
    parts.append('<article class="card"><div class="card-top"><h3>Le modèle, avant et après</h3>'
                 + _status(projection.get("status", _mapping(projection.get("summary")).get("status", "proposed"))
                           if projection else None) + '</div>'
                 + _snapshot_diff(base_model, projection.get("projected_model")) + '</article>')
    parts.append('<article class="card"><h3>Points à résoudre avant publication</h3>'
                 '<p class="help">Les inconnues et les conflits restent visibles ; ils ne deviennent pas des valeurs négatives.</p>'
                 '<h4>Changements bloqués dans la projection</h4>'
                 + _blocked(projection.get("blocked")))
    for index, result in enumerate(extractions):
        if result.get("unknown_products") or result.get("conflicts") or result.get("unanalysed_products"):
            key = _display(result.get("candidate_key"))
            parts.append(f'<h4>{_e(labels.get(key, key))}</h4><div class="two-col"><div>'
                         '<h5>Produits sans valeur établie</h5>'
                         + _review_list(result.get("unknown_products"), "Aucune inconnue signalée.")
                         + '</div><div><h5>Conflits à vérifier</h5>'
                         + _review_list(result.get("conflicts"), "Aucun conflit signalé.") + '</div></div>')
            if result.get("unanalysed_products"):
                parts.append('<h5>Produits non analysés ou partiellement analysés</h5>'
                             + _review_list(result["unanalysed_products"], "Aucun produit signalé."))
    parts.append(_details("Projection complète · résumé et changements déclarés", projection) + '</article></section>')
    parts.append('<section class="stage" aria-labelledby="journal-title"><h2 id="journal-title">Suivi du traitement</h2>'
                 '<div class="card"><h3>Mesures générales rapportées</h3>' + _metrics(report.get("metrics"))
                 + '<details><summary>Événements du traitement</summary>'
                 + _review_list(report.get("events"), "Aucun événement renseigné.") + '</details>'
                 + _details("Rapport complet · données techniques", report) + '</div></section>'
                 '<footer class="footer">PILON · Rapport autonome en lecture seule. '
                 'Les citations sont affichées telles que reçues ; leur validation relève du traitement d’extraction. '
                 'Cette page ne modifie aucun modèle.</footer></main></div></body></html>')
    return "".join(parts)
