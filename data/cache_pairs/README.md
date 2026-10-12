# Curated cache tuning pairs

`python -m scripts.make_paraphrases` regenerates 50 paraphrase pairs and 50 near-miss
pairs from reviewed Northwind-domain templates. Near-misses flip a region, plan,
number, named entity or operation direction. Router intent labels are separately
hand-written in data/router_labels.jsonl, including simple lookup questions containing
"explain" and multi-step questions without explicit complexity words.

These small fixtures are tuning/regression data, not a held-out production-quality
evaluation. Threshold sweeps use pairwise cosine scores, with and without the
entity/number guard. That guard does not detect every action/negation flip and can
reject valid paraphrases when capitalization or entity aliases differ. Evaluate with
the real embedder before choosing a deployment threshold; mock numbers are not results.
