"""Comprehensive test runner for localRAGcoder.

Usage:
    python run_tests.py              # all tests
    python run_tests.py --unit       # unit tests only
    python run_tests.py --integration  # integration tests only

Version: 1.0.0
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

TEST_MODULES = [
    ("tests.test_models", "Data Models"),
    ("tests.test_database", "Database Layer"),
    ("tests.test_graph_exporter", "Graph Exporter"),
    ("tests.test_engine", "Engine Orchestrator"),
    ("tests.test_cli", "CLI"),
]


def main():
    args = set(sys.argv[1:])
    run_unit = "--unit" in args or not ("--integration" in args)
    run_int = "--integration" in args or not ("--unit" in args)

    passed = 0
    failed = 0
    total_time = 0.0

    print("=" * 60)
    print("  localRAGcoder - Test Suite  v1.0.0")
    print("=" * 60)

    if run_unit:
        print("")
        print(" Unit Tests ".center(60, "="))
        print("")
        for mod_name, label in TEST_MODULES:
            print(f"  {label} ... ", end="", flush=True)
            t0 = time.perf_counter()
            try:
                import runpy
                runpy.run_module(mod_name, run_name="__main__")
                elapsed = time.perf_counter() - t0
                print(f"PASS ({elapsed:.2f}s)")
                passed += 1
                total_time += elapsed
            except Exception as e:
                elapsed = time.perf_counter() - t0
                print(f"FAIL ({elapsed:.2f}s): {e}")
                failed += 1
                total_time += elapsed

    if run_int:
        print("")
        print(" Integration Tests ".center(60, "="))
        print("")
        t0 = time.perf_counter()
        try:
            import runpy
            runpy.run_module("tests.test_integration", run_name="__main__")
            elapsed = time.perf_counter() - t0
            print(f"  PASS Integration ({elapsed:.2f}s)")
            passed += 1
            total_time += elapsed
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"  FAIL Integration ({elapsed:.2f}s): {e}")
            failed += 1
            total_time += elapsed

    print("")
    print("=" * 60)
    print(f"  Result: {passed} passed, {failed} failed ({total_time:.2f}s total)")
    print("=" * 60)

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
