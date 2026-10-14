import unittest
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_functional import TestFunctionalSuite
from tests.test_security import TestSecuritySuite
from tests.test_performance import TestPerformanceSuite

def run_evaluation_test_suite():
    print("=" * 78)
    print("SMART HOSTEL MANAGEMENT SYSTEM - EVALUATION TEST RUNNER")
    print("Mapped to Anna University Autonomous PG Cloud-Based Evaluation Rubrics")
    print("=" * 78)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestFunctionalSuite))
    suite.addTests(loader.loadTestsFromTestCase(TestSecuritySuite))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformanceSuite))

    start_time = time.time()
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    elapsed = time.time() - start_time

    print("\n" + "=" * 78)
    print("TEST SUITE EXECUTION SUMMARY")
    print("=" * 78)
    print(f"Total Tests Run : {result.testsRun}")
    print(f"Passed          : {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failed          : {len(result.failures)}")
    print(f"Errors          : {len(result.errors)}")
    print(f"Total Time      : {elapsed:.2f} seconds")
    print(f"Final Outcome   : {'PASS (100% SUCCESS)' if result.wasSuccessful() else 'FAIL'}")
    print("=" * 78)

    return result.wasSuccessful()

if __name__ == "__main__":
    success = run_evaluation_test_suite()
    sys.exit(0 if success else 1)
