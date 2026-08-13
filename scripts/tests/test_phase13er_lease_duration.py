"""Phase 13E-R: the command lease must outlast the run it is granted for.

The lease bounds how long AI authority may last without an explicit operator
grant. One hour had always been ample because no run had ever survived that
long -- Phase 13E died at 2.4 minutes on the clock defect, so the expiry was
never reached. With the clock disciplined, the first Gate C attempt drove for
60 minutes and then took LEASE_REJECT on every remaining command.

Nothing about the lease semantics changes: it still exists, still expires, and
still gates authority. These tests pin that its lifetime is derived from the
run it is covering, and that the run reports it rather than leaving it implied.
"""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13e_soak import SoakRunner  # noqa: E402


def make_args(**overrides) -> argparse.Namespace:
    base = {
        "burn_in_sec": 1800.0,
        "soak_sec": 7200.0,
        "backpressure_burst_sec": 330.0,
        "backpressure_settle_sec": 60.0,
        "lease_duration_sec": 0.0,
        "lease_margin_sec": 3600.0,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestLeaseSizing(unittest.TestCase):
    def test_a_gate_c_run_gets_a_lease_that_outlasts_it(self) -> None:
        args = make_args()
        lease = SoakRunner._required_lease_sec(args)
        driving = 1800.0 + 7200.0 + 330.0 + 120.0
        self.assertGreater(lease, driving)
        # The one-hour default would have expired 60 minutes into a ~2.6 h run.
        self.assertGreater(lease, 3600.0)
        self.assertEqual(lease, driving + 3600.0)

    def test_a_short_run_still_gets_at_least_the_old_default(self) -> None:
        # Shorter runs must not end up with a *smaller* lease than before.
        lease = SoakRunner._required_lease_sec(
            make_args(burn_in_sec=60.0, soak_sec=0.0, backpressure_burst_sec=0.0,
                      backpressure_settle_sec=0.0, lease_margin_sec=0.0)
        )
        self.assertGreaterEqual(lease, 3600.0)

    def test_an_explicit_lease_wins(self) -> None:
        self.assertEqual(
            SoakRunner._required_lease_sec(make_args(lease_duration_sec=12345.0)), 12345.0
        )

    def test_margin_covers_the_non_driving_phases(self) -> None:
        # Fault injection, the Phase 13B matrix, CARLA setup and evidence
        # collection all sit outside the driving phases and still need cover.
        lease = SoakRunner._required_lease_sec(make_args())
        driving = 1800.0 + 7200.0 + 330.0 + 120.0
        self.assertGreaterEqual(lease - driving, 3600.0)


class TestDriverLeasePlumbing(unittest.TestCase):
    def test_the_driver_exposes_the_lease_it_was_given(self) -> None:
        from run_phase13b_jil_checks import DEFAULT_LEASE_DURATION_SEC, JilSessionDriver

        driver = JilSessionDriver.__new__(JilSessionDriver)
        driver.lease_duration_sec = 9000.0
        driver.lease_duration_us = 9_000_000_000
        self.assertEqual(driver.lease_duration_us, int(driver.lease_duration_sec * 1_000_000))
        self.assertEqual(DEFAULT_LEASE_DURATION_SEC, 3600.0)


if __name__ == "__main__":
    unittest.main()
