"""Entry point: ``python -m app.evaluation COMMAND`` (see :mod:`app.evaluation.cli`)."""

import sys

from ed_v13.evaluation.cli import main

sys.exit(main())
