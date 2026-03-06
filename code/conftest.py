import sys
from pathlib import Path

# Ensure code/ is on sys.path so `import db` works from tests/
sys.path.insert(0, str(Path(__file__).resolve().parent))
