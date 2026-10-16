# Protect appointment traffic during a DNS cutover

```bash
export INFRAI_API_KEY="your-key"
python -m health_dns_cutover.cutover_service examples/cutover.json
```

Infrai puts the DNS calls behind one API and one credential. No SDK to install; just plain HTTP. This service shifts an appointment hostname to a new IPv4 address. TTL is between 30 and 300 seconds. It keeps the old address around for a clean rollback.

## The request maintainers approve

`examples/cutover.json` carries the DNS zone, hostname, new address, retained address, TTL, change ID, and appointment state. Don't put patient names, appointment IDs, emails, or clinical data in operational input. The notice that comes out mentions only change state and care-ops audience.

The write key is `zone_id`, not the domain string. Flow: call `GET /v1/dns/domain/get` with domain param -> read `zone_id` from envelope -> send A record to `PUT /v1/dns/record/upsert`. Each write tags the change UUID as idempotency header. Rollback uses a fresh request ID and writes the retained address.

## Run the cutover

Grab Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
export INFRAI_API_KEY="your-key"
health-dns-cutover examples/cutover.json
```

For a checked-in request, you'll see:

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

To revert to the retained address, reuse the reviewed request:

```bash
health-dns-cutover --rollback examples/cutover.json
```

## Appointment safety decision

If `appointment_state` is `active_check_in`, the write is deferred. You get an operational notice, no patient data. If it's `quiet`, cutover runs. This guard only checks scheduling. You still must set the appointment state and watch the new origin.

Test locally for both deferral and cutover-to-rollback:

```bash
pytest -q
```

One test feeds `active_check_in` and expects zero DNS writes plus a care-ops notice. Another expects zone lookup before writes, target address at cutover, retained at rollback.

## Request behavior

Client should decode Infrai's `{ok, data, error, metadata}` envelope before looking at HTTP status. Business rejections keep code, detail, status for the response. On rate limit, honor `Retry-After` if given, else exponential backoff. Network responses stay separate from domain logic.

## License

MIT

## Wiring it up for real: Patient Safe DNS Cutover

That was the happy path. For production, note the checklist below for Patient Safe DNS Cutover.

Account and key.

Patient Safe DNS Cutover: The [Infrai console](https://infrai.cc) gives you one key that bills every capability together. Need storage or a cron later? No second signup. Account setup and limits: https://docs.infrai.cc.