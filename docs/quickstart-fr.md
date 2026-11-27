# Démarrer en cinq minutes

Avec Python 3.11 à 3.13 :

```powershell
git clone https://github.com/jhuret1/pilon.git
cd pilon
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
pilon demo
```

Sur macOS/Linux, activer avec `source .venv/bin/activate`.
Ouvrir http://127.0.0.1:8472. La démo contient 24 avis produits inventés en six langues.
Elle rejoue des réponses préparées, sans modèle, sans clé et sans coût API. Elle
montre la mécanique du système ; elle ne prouve pas sa précision.

Pour importer 20 vrais avis Amazon publics, sans lancer d'inférence :

```sh
pilon import-amazon --limit 20 --output data/amazon-home-kitchen.json
```

Les données téléchargées restent hors Git. Ce sont 20 **avis**, pas nécessairement
20 produits. La version et les empreintes sont enregistrées. Le texte source conserve
les conditions de son fournisseur et n'est pas inclus dans la licence du logiciel.

Pour lancer la vraie induction, installer l'option OpenRouter, définir votre clé
dans votre terminal, puis fournir explicitement le budget et `--allow-paid` comme
dans le README. Le programme enverra alors les textes sélectionnés aux fournisseurs.

Une citation exacte garantit sa provenance. Elle ne garantit pas que la valeur
extraite ou l'interprétation est correcte. Les concepts restent donc candidats,
avec leurs preuves consultables et leurs erreurs à évaluer.
