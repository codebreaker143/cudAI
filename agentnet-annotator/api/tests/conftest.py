import os
import sys
import tempfile

# Never touch the real user data directory from tests.
os.environ["CUDAI_DATA_DIR"] = tempfile.mkdtemp(prefix="cudai-test-")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
