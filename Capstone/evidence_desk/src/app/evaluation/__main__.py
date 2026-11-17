"""Entry point: ``python -m app.evaluation COMMAND`` (see :mod:`app.evaluation.cli`)."""

import sys

from app.evaluation.cli import main

sys.exit(main())
