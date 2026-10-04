import services.recording_service as recording_service
from core.constants import FAILED
from core.permissions import check_permissions


class FakeSocket:
    def emit(self, *args, **kwargs):
        pass


def test_recording_refused_without_permissions(monkeypatch):
    monkeypatch.setattr(recording_service, "has_current_consent", lambda: True)
    monkeypatch.setattr(
        recording_service, "missing_permissions", lambda: ["Input Monitoring"]
    )
    service = recording_service.RecordingService(FakeSocket())

    status, message = service.start_recording()

    assert status == FAILED
    assert "Input Monitoring" in message
    assert service.recorder_thread is None


def test_permission_report_shape():
    report = check_permissions()
    assert set(report["permissions"]) == {"screen_recording", "input_monitoring", "accessibility"}
    for item in report["permissions"].values():
        assert {"label", "reason", "settings_url", "granted"} <= set(item)
    assert report["all_granted"] == all(i["granted"] for i in report["permissions"].values())


class FakeRecorder:
    def __init__(self, fail_on_stop=False):
        self.recording_path = "/tmp/rec-x"
        self.fail_on_stop = fail_on_stop
        self.stopped = False

    def stop_recording(self):
        self.stopped = True
        if self.fail_on_stop:
            raise RuntimeError("concat failed")


class RecordingSocket(FakeSocket):
    def __init__(self):
        self.events = []

    def emit(self, event, data=None, **kwargs):
        self.events.append((event, data))


def make_service(monkeypatch, socket=None):
    monkeypatch.setattr(recording_service, "has_current_consent", lambda: True)
    monkeypatch.setattr(recording_service, "missing_permissions", lambda: [])
    return recording_service.RecordingService(socket or FakeSocket())


def test_recording_refused_when_disk_is_nearly_full(monkeypatch):
    service = make_service(monkeypatch)
    monkeypatch.setattr(recording_service, "free_disk_bytes", lambda: 1 * 1024**3)

    status, message = service.start_recording()

    assert status == FAILED
    assert "disk space" in message


def test_failed_stop_does_not_leave_service_recording(monkeypatch):
    service = make_service(monkeypatch)
    service.recorder_thread = FakeRecorder(fail_on_stop=True)

    status, message = service.stop_recording()

    assert status == FAILED
    assert "recovered" in message
    assert service.recorder_thread is None
    assert service.get_status()["recording"] is False


def test_low_disk_stops_recording_automatically(monkeypatch):
    socket = RecordingSocket()
    service = make_service(monkeypatch, socket)
    monkeypatch.setattr(recording_service, "DISK_CHECK_INTERVAL", 0.01)
    monkeypatch.setattr(recording_service, "free_disk_bytes", lambda: 100 * 1024**2)
    recorder = FakeRecorder()
    service.recorder_thread = recorder
    service.reducer = None

    service._monitor_disk(recorder)

    assert recorder.stopped
    assert service.recorder_thread is None
    assert socket.events[-1][0] == "recording_auto_stopped"
    assert socket.events[-1][1]["reason"] == "low_disk"
