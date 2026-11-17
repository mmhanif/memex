"""`python -m memex`: the same as the `memex` console script."""

import sys

from memex.launcher.cli import main

sys.exit(main())
