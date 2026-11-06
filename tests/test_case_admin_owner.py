import pytest
from fastapi import HTTPException
from publication import admin
from store import db, now
import case_world
from admin_support import session_headers


def test_challenge_owner_is_bound_to_exact_active_admin_session():
    a=session_headers('test-issuer','case-admin-a','case_investigation')
    b=session_headers('test-issuer','case-admin-b','case_investigation')
    a2=session_headers('test-issuer','case-admin-a','case_investigation')
    p=admin.principal_for_token(admin.bearer(a['Authorization']))
    q=admin.principal_for_token(admin.bearer(b['Authorization']))
    second=admin.principal_for_token(admin.bearer(a2['Authorization']))
    with db() as c:
        c.execute('PRAGMA defer_foreign_keys=ON')
        c.execute("INSERT INTO case_snapshots VALUES('owner-snap','1:test','{}','{}','p','{}',?,?)",(now(),now()+500))
        c.execute("INSERT INTO cases VALUES('owner-case','1:test','owner-snap','monitoring',?)",(now(),))
        c.execute("INSERT INTO case_challenges VALUES('owner-ch','owner-case','owner-snap','p','diagnostic_research','owner-nonce','pending',?,?,?)",(now()+500,now(),'owner-idem'))
        c.execute('INSERT INTO case_challenge_admin VALUES(?,?,?)',('owner-ch',p.session_id,admin.subject_hash(p.iss,p.sub)))
        case_world.require_owner(c,'owner-ch',p)
        for other in (q,second,None):
            with pytest.raises(HTTPException) as error:case_world.require_owner(c,'owner-ch',other)
            assert error.value.status_code==403
        admin.revoke_scope(c,p.iss,p.sub,'case_investigation','test')
        with pytest.raises(HTTPException):case_world.require_owner(c,'owner-ch',p)
