"""The capstone's versions, running live on this website (docs/site-live.md at the repository root).

Each tagged version of Evidence Desk is vendored under ``vendored/vN`` with its package renamed
``ed_vN`` (``make site-vendor``). :mod:`live.site` mounts version N at ``/vN``: it imports the
version on its first request, points its data at ``/tmp``, serves its own page with a banner
and a small client shim, holds a run-start request open until the run is finished, and passes
every request through :mod:`live.guard` first. Nothing here changes a version's code.
"""
