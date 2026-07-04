from __future__ import annotations

import sys
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from circuit_breaker import CircuitBreaker


def _fresh_cb(threshold: int = 3, timeout: float = 60.0) -> CircuitBreaker:
    return CircuitBreaker("load_test", failure_threshold=threshold, recovery_timeout=timeout)


# =============================================================================
# CircuitBreaker — load / soak tests
# =============================================================================

class TestCircuitBreakerUnderLoad(unittest.TestCase):

    def test_trips_at_threshold_concurrent(self):
        cb = _fresh_cb(threshold=3)
        results = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            cb.record_failure()
            results.append(cb.is_open())

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(cb.is_open(), "CB must be open after 10 failures with threshold=3")
        open_count = sum(1 for r in results if r is True)
        self.assertGreaterEqual(open_count, 7,
            f"Expected at least 7 threads to see is_open()==True, got {open_count}")

    def test_probe_exclusive_under_concurrency(self):
        cb = _fresh_cb(threshold=1, timeout=0.05)
        cb.record_failure()
        time.sleep(0.1)

        results = []
        n_threads = 20
        barrier = threading.Barrier(n_threads)

        def worker():
            barrier.wait()
            results.append(cb.is_open())

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        probe_count = results.count(False)
        self.assertEqual(probe_count, 1,
            f"Exactly 1 thread should get the probe (False), got {probe_count}")

    def test_recovery_resets_state(self):
        cb = _fresh_cb(threshold=1, timeout=0.05)
        cb.record_failure()
        self.assertTrue(cb.is_open())

        time.sleep(0.1)
        probe = cb.is_open()
        self.assertFalse(probe, "First caller in HALF_OPEN must receive the probe")

        cb.record_success()
        self.assertFalse(cb.is_open(), "CB must be CLOSED after record_success()")

    def test_threshold_accuracy_soak(self):
        for _ in range(100):
            cb = _fresh_cb(threshold=3)
            cb.record_failure()
            self.assertFalse(cb.is_open(), "Should not be open after 1 failure (threshold=3)")
            cb.record_failure()
            self.assertFalse(cb.is_open(), "Should not be open after 2 failures (threshold=3)")
            cb.record_failure()
            self.assertTrue(cb.is_open(), "Must be open after 3 failures (threshold=3)")


# =============================================================================
# Budget atomicity — load / soak tests
# =============================================================================

class _MockSpendStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, float] = {}

    def reset(self):
        with self._lock:
            self._data.clear()

    def read(self, user_id: str) -> float:
        with self._lock:
            return self._data.get(user_id, 0.0)

    def write(self, user_id: str, amount: float) -> None:
        with self._lock:
            self._data[user_id] = self._data.get(user_id, 0.0) + amount


class TestBudgetAtomicityUnderLoad(unittest.TestCase):

    def setUp(self):
        self.spend = _MockSpendStore()

        import budget_store
        self.budget_store = budget_store
        budget_store._redis_client = None
        budget_store._redis_available = False

        budget_store._USER_LOCKS.clear()

    def _run_concurrent_reserves(self, user_id, estimated, limit, n_threads):
        results = []
        barrier = threading.Barrier(n_threads)

        def worker():
            barrier.wait()
            approved, total = self.budget_store.try_reserve(user_id, estimated, limit)
            results.append((approved, total))

        # Apply patches once at the test level so all threads share the same mock
        # and there is no race on module-attribute replacement.
        with unittest.mock.patch(
            "ui.run_history._user_today_spend",
            side_effect=lambda uid: self.spend.read(uid),
        ), unittest.mock.patch(
            "budget_store._record_spend_file",
            side_effect=lambda uid, amt: self.spend.write(uid, amt),
        ):
            threads = [threading.Thread(target=worker) for _ in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        return results

    def test_no_double_spend_10_threads(self):
        user_id = "load_test_user"
        n_threads = 10
        estimated = 0.15
        limit = 1.00

        results = self._run_concurrent_reserves(user_id, estimated, limit, n_threads)

        approved_count = sum(1 for approved, _ in results if approved)
        expected_approved = int(limit / estimated)  # floor(1.00/0.15) = 6
        self.assertEqual(approved_count, expected_approved,
            f"Expected exactly {expected_approved} approvals, got {approved_count}")

        total_reserved = self.spend.read(user_id)
        self.assertLessEqual(total_reserved, limit + 1e-9,
            f"Total reserved {total_reserved:.4f} exceeds limit {limit}")

    def test_all_approved_under_limit(self):
        user_id = "budget_ok_user"
        n_threads = 5
        estimated = 0.10
        limit = 1.00

        results = self._run_concurrent_reserves(user_id, estimated, limit, n_threads)

        approved_count = sum(1 for approved, _ in results if approved)
        self.assertEqual(approved_count, n_threads,
            f"All {n_threads} threads should be approved, got {approved_count}")

        total_reserved = self.spend.read(user_id)
        self.assertAlmostEqual(total_reserved, n_threads * estimated, places=9,
            msg=f"Expected total ${n_threads * estimated:.2f}, got ${total_reserved:.4f}")

    def test_all_rejected_when_over_limit(self):
        user_id = "over_budget_user"
        self.spend.write(user_id, 1.00)

        n_threads = 5
        estimated = 0.10
        limit = 1.00

        results = self._run_concurrent_reserves(user_id, estimated, limit, n_threads)

        rejected_count = sum(1 for approved, _ in results if not approved)
        self.assertEqual(rejected_count, n_threads,
            f"All {n_threads} threads should be rejected, got {rejected_count}")

        total_after = self.spend.read(user_id)
        self.assertAlmostEqual(total_after, 1.00, places=9,
            msg=f"Spend should remain at $1.00 after all rejections, got ${total_after:.4f}")


if __name__ == "__main__":
    unittest.main()
