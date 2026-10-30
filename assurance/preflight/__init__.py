"""Independent checks over the shipped report reader. Never imported by src/ or tests/.

Hypothesis profiles: `dev` (100 examples, the default, without the too_slow health check, #51) and `ci`
(1000 examples, no deadline, derandomised, prints the reproduction blob of any failure). Select with
HYPOTHESIS_PROFILE=dev|ci.
"""

import os
import sys
from pathlib import Path

from hypothesis import HealthCheck, settings

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
FIXTURES = REPO / "tests" / "fixtures" / "reports"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# A cold local run builds Hypothesis's Unicode cache (.hypothesis/unicode_data) inside the first draw, which trips the
# too_slow health check once (#51). Suppressed for dev only; ci keeps every health check.
settings.register_profile("dev", max_examples=100, print_blob=True, suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("ci", max_examples=1000, deadline=None, derandomize=True, print_blob=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
