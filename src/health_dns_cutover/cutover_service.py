from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from .infrai_dns import InfraiDnsClient, InfraiError


class AppointmentState(StrEnum):
    QUIET = "quiet"
    ACTIVE_CHECK_IN = "active_check_in"


@dataclass(frozen=True)
class CutoverRequest:
    change_id: UUID
    domain: str
    hostname: str
    target_ipv4: str
    rollback_ipv4: str
    ttl: int
    appointment_state: AppointmentState

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CutoverRequest":
        return cls(
            change_id=UUID(str(value["change_id"])),
            domain=str(value["domain"]),
            hostname=str(value["hostname"]),
            target_ipv4=str(value["target_ipv4"]),
            rollback_ipv4=str(value["rollback_ipv4"]),
            ttl=int(value["ttl"]),
            appointment_state=AppointmentState(value["appointment_state"]),
        )


@dataclass(frozen=True)
class OperationalNotice:
    audience: str
    message: str


@dataclass(frozen=True)
class CutoverResult:
    applied: bool
    action: str
    hostname: str
    active_ipv4: str
    rollback_ipv4: str
    ttl: int
    notice: OperationalNotice


def plan_cutover(request: CutoverRequest) -> CutoverResult:
    if request.ttl < 30 or request.ttl > 300:
        raise ValueError("ttl must be between 30 and 300 seconds")
    if request.appointment_state is AppointmentState.ACTIVE_CHECK_IN:
        return CutoverResult(
            applied=False,
            action="deferred",
            hostname=request.hostname,
            active_ipv4=request.rollback_ipv4,
            rollback_ipv4=request.rollback_ipv4,
            ttl=request.ttl,
            notice=OperationalNotice(
                audience="care-operations",
                message="DNS change deferred while appointment check-in is active.",
            ),
        )
    return CutoverResult(
        applied=True,
        action="cutover",
        hostname=request.hostname,
        active_ipv4=request.target_ipv4,
        rollback_ipv4=request.rollback_ipv4,
        ttl=request.ttl,
        notice=OperationalNotice(
            audience="care-operations",
            message="Appointment hostname changed; rollback address is retained.",
        ),
    )


def execute_cutover(request: CutoverRequest, dns: Any) -> CutoverResult:
    result = plan_cutover(request)
    if not result.applied:
        return result
    zone = dns.get_zone(request.domain)
    zone_id = zone.get("zone_id")
    if not isinstance(zone_id, str) or not zone_id:
        raise ValueError("domain response did not contain zone_id")
    dns.upsert_record(
        zone_id=zone_id,
        record_type="A",
        name=request.hostname,
        content=request.target_ipv4,
        ttl=request.ttl,
        request_id=str(request.change_id),
    )
    return result


def rollback_cutover(request: CutoverRequest, dns: Any) -> CutoverResult:
    zone = dns.get_zone(request.domain)
    zone_id = zone.get("zone_id")
    if not isinstance(zone_id, str) or not zone_id:
        raise ValueError("domain response did not contain zone_id")
    dns.upsert_record(
        zone_id=zone_id,
        record_type="A",
        name=request.hostname,
        content=request.rollback_ipv4,
        ttl=request.ttl,
        request_id=f"{request.change_id}-rollback",
    )
    return CutoverResult(
        applied=True,
        action="rollback",
        hostname=request.hostname,
        active_ipv4=request.rollback_ipv4,
        rollback_ipv4=request.rollback_ipv4,
        ttl=request.ttl,
        notice=OperationalNotice(
            audience="care-operations",
            message="Appointment hostname restored to the retained address.",
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply or roll back an appointment DNS change")
    parser.add_argument("request", help="path to a JSON cutover request")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    with open(args.request, encoding="utf-8") as handle:
        request = CutoverRequest.from_dict(json.load(handle))
    api_key = os.environ.get("INFRAI_API_KEY")
    if not api_key:
        parser.error("INFRAI_API_KEY is required")
    client = InfraiDnsClient(api_key)
    try:
        result = rollback_cutover(request, client) if args.rollback else execute_cutover(request, client)
    except InfraiError as exc:
        print(json.dumps({"ok": False, "error": exc.detail, "status": exc.status}))
        raise SystemExit(2) from exc
    print(json.dumps({"ok": True, "result": asdict(result)}, indent=2))


if __name__ == "__main__":
    main()
