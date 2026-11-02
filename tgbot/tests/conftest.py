import sys
from pathlib import Path

# Только cross-implementation test: backend verifier не требует его dependencies.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
