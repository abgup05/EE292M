"""The golden-set evaluation: retrieval and generation, scored apart.

``corpus`` pins and reads the filings the cases name, ``golden`` loads and checks
the cases, ``retrieval_eval`` ranks each case's passages as the pipeline does and
scores where the passage that matters lands. ``companies`` pins each company and
its XBRL facts, ``planning`` obtains the model-written queries through a cassette,
and ``generation_eval`` runs every case through the model, the citation gate and
the verdict rule and scores the answers. ``cli`` is the command line
(``python -m app.evaluation``), reached through ``make eval`` and
``make eval-validate``. Nothing here is imported by the running application.
"""
