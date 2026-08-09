import pytest
from pydantic import ValidationError

from opencover.core.worker_protocol import WorkerEvent


def test_progress_event_parses() -> None:
    event = WorkerEvent.parse_line('{"type":"progress","stage":"separation","value":35}')
    assert event.stage == "separation"
    assert event.value == 35


def test_progress_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        WorkerEvent.parse_line('{"type":"progress","value":101}')
