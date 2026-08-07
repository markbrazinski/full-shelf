import subprocess
import sys
import os

def main():
    env = os.environ.copy()
    env["PYTHONPATH"] = f".:{os.path.abspath('apps/plan-ledger/src')}:{os.path.abspath('apps/orchestrator/src')}"

    print("=== Running Full Shelf Domain & Policy Unit Tests ===")
    res_domain = subprocess.run(["python3", "-m", "pytest", "packages/domain/tests"], env=env)
    
    print("\n=== Running Full Shelf Plan Ledger API Contract Tests ===")
    res_ledger = subprocess.run(["python3", "-m", "pytest", "apps/plan-ledger/tests"], env=env)

    if res_domain.returncode == 0 and res_ledger.returncode == 0:
        print("\n✅ All Full Shelf Unit & Contract Tests Passed Cleanly!")
        sys.exit(0)
    else:
        print("\n❌ Test failures detected.")
        sys.exit(1)

if __name__ == "__main__":
    main()
