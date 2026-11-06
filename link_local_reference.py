"""Operator-only association of an existing case and imported reference report."""
import argparse
import json
from pathlib import Path

from store import db, init, now
from modules.investigation.contract_validate import verify_digest


def link(case_id, report_id, version):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        case = c.execute('SELECT candidate_id FROM cases WHERE id=?', (case_id,)).fetchone()
        report = c.execute('SELECT r.*,i.candidate_id,i.status FROM reports r JOIN investigations i ON i.id=r.run_id WHERE r.id=? AND r.version=?', (report_id, version)).fetchone()
        if not case or not report or case['candidate_id'] != report['candidate_id']:
            raise ValueError('case/report identity mismatch or missing')
        if report['status'] != 'reference_only':
            raise ValueError('only reference-only drafts may use this link')
        doc = verify_digest(Path(report['path']), report['sha256'])
        if (doc['candidate_id'], doc['report_id'], doc['report_version']) != (case['candidate_id'], report_id, version):
            raise ValueError('report bundle identity mismatch')
        c.execute('INSERT OR IGNORE INTO case_reference_reports VALUES(?,?,?,?)', (case_id, report_id, version, now()))
        return {'case_id': case_id, 'candidate_id': case['candidate_id'], 'report_id': report_id, 'version': version, 'sha256': report['sha256'], 'association': 'local_reference_only', 'gate_effect': 'none'}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('case_id'); p.add_argument('report_id'); p.add_argument('version')
    a = p.parse_args(); init(); print(json.dumps(link(a.case_id, a.report_id, a.version)))
