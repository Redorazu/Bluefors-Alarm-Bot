import json
from pathlib import Path

from alarm_bot.logging.audit import AuditLogger


def test_audit_log_rotates_when_size_exceeded(tmp_path: Path):
    audit_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(audit_path, rotate_mb=1, backups=2)
    logger._handler.maxBytes = 80
    try:
        logger.log("poll.start", payload={"poll_id": "p1"})
        logger.log("poll.start", payload={"poll_id": "p2"})

        assert audit_path.exists()
        assert (tmp_path / "audit.jsonl.1").exists()

        records = logger.query(limit=10)
        assert len(records) == 1
        assert records[0]["payload"]["poll_id"] == "p2"
    finally:
        logger.close()


def test_audit_log_writes_json_lines(tmp_path: Path):
    audit_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(audit_path, rotate_mb=10, backups=1)
    try:
        logger.log("alert.triggered", metric_id="mxc_temperature", payload={"value": 1.2})
        line = audit_path.read_text(encoding="utf-8").strip()
        record = json.loads(line)
        assert record["event_type"] == "alert.triggered"
        assert record["metric_id"] == "mxc_temperature"
        assert record["payload"]["value"] == 1.2
    finally:
        logger.close()
