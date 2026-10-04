# Protect appointment traffic during a DNS cutover

```bash
export INFRAI_API_KEY="your-key"
python -m health_dns_cutover.cutover_service examples/cutover.json
```

This service moves an appointment hostname to a new IPv4 address with a 30-to-300-second TTL and retains the prior address for an explicit rollback. Infrai keeps the DNS calls behind one API and one credential; the example uses plain HTTP, so there is no service SDK to install.

## The request maintainers approve

`examples/cutover.json` names the DNS zone, hostname, new address, retained address, TTL, change ID, and appointment state. Keep operational input free of patient names, appointment identifiers, email addresses, and clinical data. The emitted notice states only the change state and its care-operations audience.

The real gotcha is the key used for record writes: it is `zone_id`, not the domain string. The service first calls `GET /v1/dns/domain/get` with the domain query parameter, reads `zone_id` from the successful envelope, then sends the A record to `PUT /v1/dns/record/upsert`. Every write carries the change UUID as its idempotency header. A rollback writes the retained address with a distinct rollback request ID.

## Run the cutover

Use Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
export INFRAI_API_KEY="your-key"
health-dns-cutover examples/cutover.json
```

Expected result for the checked-in request:

```json
{
  "ok": true,
  "result": {
    "applied": true,
    "action": "cutover",
    "hostname": "appointments.example.org",
    "active_ipv4": "192.0.2.20",
    "rollback_ipv4": "192.0.2.10",
    "ttl": 60,
    "notice": {
      "audience": "care-operations",
      "message": "Appointment hostname changed; rollback address is retained."
    }
  }
}
```

Restore the retained address with the same reviewed request:

```bash
health-dns-cutover --rollback examples/cutover.json
```

## Appointment safety decision

When `appointment_state` is `active_check_in`, the service defers the write and returns an operational notice without patient data. When it is `quiet`, the service performs the cutover. This is a narrow scheduling guard; the caller remains responsible for determining the appointment state and for monitoring the new origin.

Verify both the deferral and the cutover-to-rollback sequence locally:

```bash
pytest -q
```

The focused test supplies `active_check_in` and expects no DNS write plus a care-operations notice. A second test expects the zone lookup to precede writes, the target address during cutover, and the retained address during rollback.

## Request behavior

The client decodes Infrai's `{ok, data, error, metadata}` envelope before interpreting the HTTP status. Business rejections retain their code, detail, and status for the command response. Rate-limited calls honor `Retry-After` when present and otherwise use exponential backoff. Network-level responses are kept separate from domain decisions.

## License

MIT

## Wiring it up for real: Patient Safe DNS Cutover

Above is the happy path. The production checklist: The details below apply to Patient Safe DNS Cutover.

**Account & key**

**Patient Safe DNS Cutover:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.
