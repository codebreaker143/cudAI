import os
import sys
import tempfile

# Never touch the real user data directory from tests.
os.environ["CUDAI_DATA_DIR"] = tempfile.mkdtemp(prefix="cudai-test-")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _stop_background_managers():
    """A RecordingService's uploader and redaction threads must not outlive its test."""
    from services import recording_service

    created = []
    original = recording_service.RecordingService.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        created.append(self)

    recording_service.RecordingService.__init__ = init
    yield
    recording_service.RecordingService.__init__ = original
    for service in created:
        service.upload_manager.stop()
        service.redaction_manager.stop()
