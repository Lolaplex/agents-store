from agents_store.more.events import Event

FAB = "did:web:lolaplex.com:fabian"
CI = "did:web:lolaplex.com:ci"


def verification(subject, pin, result="pass", *, gate="ci", witness=True, stage="test", **kw):
    body = {"method": "unittest", "result": result, "stage": stage}
    if gate:
        body["gate"] = gate
    if witness:
        body["witness"] = {"command": ["python", "-m", "unittest"], "exit_code": 0 if result == "pass" else 1}
    body.update(kw.pop("body", {}))
    return Event("verification", CI, (subject,), (pin,) if pin else (), body=body, **kw)


def decision(subject, pin, status="decided", **body):
    b = {"status": status}
    if status == "decided":
        b["decided_by"] = FAB
    b.update(body)
    return Event("decision", FAB, (subject,), (pin,), body=b)


def acceptance(subject, pin, tests, outcome="accepted"):
    return decision(subject, pin, kind="acceptance", outcome=outcome, tests=list(tests),
                    requirement=subject)


def inclusion(subject, pin, into):
    return Event("inclusion", CI, (subject,), (pin,), body={"into": into, "from": "abc123..def456"})
