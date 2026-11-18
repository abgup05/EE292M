"""Entry point: ``python -m app.evaluation COMMAND`` (see :mod:`app.evaluation.cli`)."""

import sys

from ed_v10.evaluation.cli import main

sys.exit(main())
