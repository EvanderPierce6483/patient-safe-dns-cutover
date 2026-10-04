from uuid import UUID

from health_dns_cutover.cutover_service import (
    AppointmentState,
    CutoverRequest,
    execute_cutover,
    rollback_cutover,
)


class RecordingDns:
    def __init__(self) -> None:
        self.writes: list[dict[str, object]] = []

    def get_zone(self, domain: str) -> dict[str, str]:
        assert domain == "example.org"
        return {"zone_id": "zone_health_1"}

    def upsert_record(self, **request: object) -> dict[str, str]:
        self.writes.append(request)
        return {"record_id": "record_1"}


def make_request(state: AppointmentState = AppointmentState.QUIET) -> CutoverRequest:
    return CutoverRequest(
        change_id=UUID("90720465-eb31-4d36-b604-d2a0e20e47e8"),
        domain="example.org",
        hostname="appointments.example.org",
        target_ipv4="192.0.2.20",
        rollback_ipv4="192.0.2.10",
        ttl=60,
        appointment_state=state,
    )


def test_active_check_in_defers_dns_write_and_emits_safe_notice() -> None:
    dns = RecordingDns()

    result = execute_cutover(make_request(AppointmentState.ACTIVE_CHECK_IN), dns)

    assert result.applied is False
    assert result.action == "deferred"
    assert result.notice.audience == "care-operations"
    assert "appointment" in result.notice.message.lower()
    assert dns.writes == []


def test_cutover_resolves_zone_before_writing_and_can_roll_back() -> None:
    dns = RecordingDns()
    request = make_request()

    changed = execute_cutover(request, dns)
    restored = rollback_cutover(request, dns)

    assert changed.active_ipv4 == "192.0.2.20"
    assert restored.active_ipv4 == "192.0.2.10"
    assert dns.writes[0] == {
        "zone_id": "zone_health_1",
        "record_type": "A",
        "name": "appointments.example.org",
        "content": "192.0.2.20",
        "ttl": 60,
        "request_id": "90720465-eb31-4d36-b604-d2a0e20e47e8",
    }
    assert dns.writes[1]["content"] == "192.0.2.10"
