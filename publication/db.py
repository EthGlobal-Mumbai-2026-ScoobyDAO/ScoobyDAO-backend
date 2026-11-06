"""Publication tables, created in the same SQLite file as store.py (CREATE TABLE IF NOT EXISTS)."""
from __future__ import annotations
import json
from store import db, now

SCHEMA = '''
CREATE TABLE IF NOT EXISTS pub_targets(
 id TEXT PRIMARY KEY, report_id TEXT NOT NULL, report_version TEXT NOT NULL, report_sha256 TEXT NOT NULL,
 claim_manifest_json TEXT NOT NULL, claim_hash TEXT NOT NULL, chain_id INTEGER NOT NULL, registry TEXT NOT NULL,
 resolver TEXT NOT NULL, adjudicator TEXT NOT NULL, lock_time INTEGER NOT NULL, cross_chain_cutoff INTEGER NOT NULL,
 result_deadline INTEGER NOT NULL, challenge_period INTEGER NOT NULL, target_json TEXT NOT NULL,
 target_digest TEXT NOT NULL, created REAL NOT NULL,
 UNIQUE(report_id, report_version, target_digest));
CREATE TABLE IF NOT EXISTS pub_reviewers(
 iss TEXT NOT NULL, sub TEXT NOT NULL, label TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL,
 PRIMARY KEY(iss, sub));
CREATE TABLE IF NOT EXISTS pub_attempts(
 id TEXT PRIMARY KEY, target_id TEXT NOT NULL REFERENCES pub_targets(id),
 decision_intent TEXT NOT NULL CHECK (decision_intent IN ('approve','reject','revise')),
 reason TEXT NOT NULL, policy_version TEXT NOT NULL, accepted_acr TEXT NOT NULL, device_code_hash TEXT NOT NULL,
 user_code TEXT NOT NULL, verification_uri TEXT NOT NULL, verification_uri_complete TEXT, interval INTEGER NOT NULL,
 next_poll_at REAL NOT NULL, started_at REAL NOT NULL, expires_at REAL NOT NULL,
 status TEXT NOT NULL CHECK (status IN ('pending','approved','denied','expired','cancelled','rejected_not_reviewer','error')),
 error TEXT, idem TEXT UNIQUE, request_hash TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pub_receipts(
 id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE REFERENCES pub_attempts(id), target_id TEXT NOT NULL REFERENCES pub_targets(id),
 target_digest TEXT NOT NULL, decision TEXT NOT NULL CHECK (decision IN ('approve','reject','revise')), reason TEXT NOT NULL,
 reviewer_iss TEXT NOT NULL, reviewer_sub TEXT NOT NULL, acr TEXT NOT NULL, amr_json TEXT NOT NULL, auth_time INTEGER NOT NULL,
 verified_at REAL NOT NULL, verifier_version TEXT NOT NULL, consumed_at REAL, revoked_at REAL);
CREATE TABLE IF NOT EXISTS pub_outbox(
 id TEXT PRIMARY KEY, target_id TEXT NOT NULL REFERENCES pub_targets(id), receipt_id TEXT NOT NULL UNIQUE REFERENCES pub_receipts(id),
 reviewer_addr TEXT NOT NULL, nonce TEXT NOT NULL, approval_expiry INTEGER NOT NULL, signature TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('queued','signing','submitted','confirmed','failed','reconcile')),
 fence INTEGER NOT NULL DEFAULT 0, lease REAL, tx_hash TEXT, raw_tx TEXT, onchain_report_id TEXT, error TEXT,
 idem TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pub_events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, target_id TEXT, kind TEXT NOT NULL, actor TEXT NOT NULL, detail_json TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pub_idem(
 scope TEXT NOT NULL, idem TEXT NOT NULL, request_hash TEXT NOT NULL, result_json TEXT NOT NULL, created REAL NOT NULL,
 PRIMARY KEY(scope, idem));
CREATE TRIGGER IF NOT EXISTS pub_receipts_append_only BEFORE UPDATE ON pub_receipts
 WHEN NEW.id IS NOT OLD.id OR NEW.attempt_id IS NOT OLD.attempt_id OR NEW.target_id IS NOT OLD.target_id
   OR NEW.target_digest IS NOT OLD.target_digest OR NEW.decision IS NOT OLD.decision OR NEW.reviewer_iss IS NOT OLD.reviewer_iss
   OR NEW.reviewer_sub IS NOT OLD.reviewer_sub OR NEW.acr IS NOT OLD.acr OR NEW.auth_time IS NOT OLD.auth_time
   OR NEW.verified_at IS NOT OLD.verified_at
 BEGIN SELECT RAISE(ABORT, 'pub_receipts is append-only'); END;
CREATE TRIGGER IF NOT EXISTS pub_receipts_no_delete BEFORE DELETE ON pub_receipts
 BEGIN SELECT RAISE(ABORT, 'pub_receipts is append-only'); END;
CREATE TRIGGER IF NOT EXISTS pub_events_append_only BEFORE UPDATE ON pub_events
 BEGIN SELECT RAISE(ABORT, 'pub_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS pub_events_no_delete BEFORE DELETE ON pub_events
 BEGIN SELECT RAISE(ABORT, 'pub_events is append-only'); END;
'''


def init() -> None:
    with db() as c:
        c.executescript(SCHEMA)


def audit(c, target_id: str | None, kind: str, actor: str, detail: dict | None = None) -> None:
    """Append-only audit event. Never pass tokens, device codes or keys in detail."""
    c.execute('INSERT INTO pub_events(target_id,kind,actor,detail_json,created) VALUES(?,?,?,?,?)',
              (target_id, kind, actor, json.dumps(detail or {}, sort_keys=True), now()))


init()
