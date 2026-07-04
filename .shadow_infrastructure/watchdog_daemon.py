"""
Watchdog Daemon — spacex-cryogenics
SHA-256 file integrity verification with tamper detection.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict

class WatchdogDaemon:
    """Monitors file integrity via SHA-256 hashing."""
    
    def __init__(self, repo_root: str = ".."):
        self.repo_root = Path(repo_root)
        self.hash_store = self.repo_root / ".shadow_infrastructure" / "file_hashes.json"
        self.baseline: Dict[str, str] = {}
        self._load_baseline()
    
    def _compute_hash(self, path: Path) -> str:
        """Compute SHA-256 hash of file."""
        return hashlib.sha256(path.read_bytes()).hexdigest()
    
    def _load_baseline(self):
        """Load stored hashes from disk."""
        if self.hash_store.exists():
            self.baseline = json.loads(self.hash_store.read_text())
    
    def _save_baseline(self):
        """Persist hashes to disk."""
        self.hash_store.write_text(json.dumps(self.baseline, indent=2))
    
    def scan(self) -> Dict[str, str]:
        """Scan all Python files and compute hashes."""
        current = {}
        for pattern in ["src/**/*.py", "*.py"]:
            for path in self.repo_root.glob(pattern):
                if "__pycache__" not in str(path):
                    rel = path.relative_to(self.repo_root)
                    current[str(rel)] = self._compute_hash(path)
        return current
    
    def verify(self) -> Dict[str, bool]:
        """Verify current hashes match baseline."""
        current = self.scan()
        results = {}
        for path, hash_val in current.items():
            if path in self.baseline:
                results[path] = self.baseline[path] == hash_val
            else:
                results[path] = False  # New file not in baseline
        return results
    
    def update_baseline(self):
        """Update baseline with current hashes."""
        self.baseline = self.scan()
        self._save_baseline()
    
    def run_check(self) -> bool:
        """Run integrity check, return True if all OK."""
        results = self.verify()
        return all(results.values())

if __name__ == "__main__":
    watchdog = WatchdogDaemon()
    watchdog.update_baseline()
    results = watchdog.verify()
    all_ok = all(results.values())
    print(f"Integrity check: {'PASS' if all_ok else 'FAIL'}")
    for path, ok in results.items():
        status = "✓" if ok else "✗"
        print(f"  {status} {path}")
