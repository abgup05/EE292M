"""Retrieval measurement: a golden set of thesis claims and the scorer that runs it.

``corpus`` pins and reads the filings the cases name, ``golden`` loads and checks
the cases, ``retrieval_eval`` ranks each case's passages as the pipeline does and
scores where the passage that matters lands. ``cli`` is the command line
(``python -m app.evaluation``), reached through ``make eval`` and
``make eval-validate``. Nothing here is imported by the running application.
"""
