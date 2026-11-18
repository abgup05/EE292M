"""The standing watch (version 13): a saved thesis watched for new filings of its company.

``store`` keeps the watch's state (the record, and a disposable status), ``service``
is one watcher cycle and one job, ``routes`` the HTTP API, and ``python -m app.watch``
the watcher process.
"""
