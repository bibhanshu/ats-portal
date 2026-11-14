"""Business rules for the Talent Acquisition Portal.

Every change a user makes on screen arrives here as an "action". Each action is
checked against the rules, saved through db.py, and answered with a message.
The screens also check the same rules, but the checks here are the ones that
count, because several people can be using the app at the same time.
"""
import base64
import datetime as dt
import re

import db
import excel_export

JOBCATS = ["Full time", "Contract"]
CATS = ["Full time employee", "Contractor", "Rehire", "Employee of Shell Recharge", "Employee of Shell"]
EMP_CATS = ["Employee of Shell Recharge", "Employee of Shell"]
EMP_STATUS = ["Currently employed", "Past employee"]
SOURCES = ["LinkedIn", "Naukri", "Vendor", "Self-sourcing", "Referral", "Internal application", "Others"]
SRC_FOLLOW = {"Vendor": "vendor name", "Self-sourcing": "source of self-sourcing",
              "Others": "please specify the source"}
RESUME_TYPES = (".pdf", ".doc", ".docx")
MAX_RESUME_BYTES = 5 * 1024 * 1024
EMAIL_RE = re.compile(r"^\S+@\S+\.\S+$")


class RuleError(Exception):
    """Raised when an action breaks a rule. The text is shown to the user."""


# ---------------------------------------------------------------- helpers
def _s(value):
    return str(value if value is not None else "").strip()


def _date(value):
    try:
        return dt.date.fromisoformat(_s(value))
    except ValueError:
        return None


def days_between(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def resolve_today(client_today):
    """Use the date on the user's own computer, unless it is clearly wrong.

    The server clock runs on UTC, so near midnight it can be a day behind or
    ahead of the user. A difference of more than one day is not trusted.
    """
    server = dt.datetime.now(dt.timezone.utc).date()
    client = _date(client_today)
    if client and abs((client - server).days) <= 1:
        return client.isoformat()
    return server.isoformat()


def order(req):
    return db.stage_order(req["rounds"])


def full_name(c):
    return " ".join(x for x in [c["first"], c["middle"], c["last"]] if x)


def find_req(state, req_id):
    for r in state["R"]:
        if r["id"] == req_id:
            return r
    raise RuleError("This requisition was not found. Refresh the page and try again.")


def find_cand(state, cand_id):
    for c in state["C"]:
        if c["id"] == cand_id:
            return c
    raise RuleError("This candidate was not found. Refresh the page and try again.")


def hires(state, req):
    """Candidates on this requisition who are hired or beyond, and not declined."""
    hire_idx = order(req).index("Hire")
    return sum(1 for c in state["C"] for t in c["tags"]
               if t["req"] == req["id"] and not t["declined"] and t["idx"] >= hire_idx)


def time_to_fill(req):
    return days_between(req["clock"], req["closed"]) if req["status"] == "Closed" else None


def clean_interviews(raw):
    out, seen = [], set()
    for iv in raw or []:
        kind = _s((iv or {}).get("type"))
        if kind not in db.IVMAP:
            continue
        if kind in seen:
            raise RuleError("Each interview type can be used only once in the workflow. " + kind + " is selected twice.")
        seen.add(kind)
        out.append({"type": kind, "who": _s(iv.get("who"))})
    return out


def _positions(value):
    try:
        return max(1, int(float(_s(value) or 1)))
    except ValueError:
        return 1


def check_category(obj):
    if obj.get("category") not in CATS:
        raise RuleError("Choose the candidate category.")
    if obj["category"] in EMP_CATS and obj.get("empStatus") not in EMP_STATUS:
        raise RuleError("Choose whether this person is currently employed or a past employee.")


def check_person(obj):
    if not (_s(obj.get("first")) and _s(obj.get("last")) and _s(obj.get("email")) and _s(obj.get("phone"))):
        raise RuleError("First name, last name, email, and phone are required.")
    if not EMAIL_RE.match(_s(obj.get("email"))):
        raise RuleError("Enter a valid email address.")


def check_source(obj):
    if obj.get("source") not in SOURCES:
        raise RuleError("Choose a source.")
    if obj["source"] in SRC_FOLLOW and not _s(obj.get("srcDetail")):
        raise RuleError("Enter the " + SRC_FOLLOW[obj["source"]] + ".")


def same_person(c, email, phone):
    return (c["email"].strip().lower() == email.strip().lower()
            and re.sub(r"\s", "", c["phone"]) == re.sub(r"\s", "", phone))


def decode_resume(file):
    """Check an uploaded resume and return (name, mime, bytes), or None."""
    if not file or not file.get("b64"):
        return None
    name = _s(file.get("name")) or "resume"
    if not name.lower().endswith(RESUME_TYPES):
        raise RuleError("The resume must be a PDF or Word file (.pdf, .doc, .docx).")
    try:
        data = base64.b64decode(file["b64"], validate=True)
    except Exception:
        raise RuleError("The resume file could not be read. Choose the file again.")
    if not data:
        raise RuleError("The resume file is empty.")
    if len(data) > MAX_RESUME_BYTES:
        raise RuleError("The resume file is larger than 5 MB.")
    return name, _s(file.get("mime")) or "application/octet-stream", data


# ---------------------------------------------------------------- requisitions
def create_req(conn, state, p, today):
    d = p.get("D") or {}
    req_id, bp, title = _s(d.get("req")), _s(d.get("bp")), _s(d.get("title"))
    if not (bp and req_id and title):
        raise RuleError("BP number, requisition number, and job designation are required.")
    if d.get("jobCat") not in JOBCATS:
        raise RuleError("Choose the job category (Full time or Contract).")
    if any(r["id"].lower() == req_id.lower() for r in state["R"]):
        raise RuleError("Requisition number " + req_id + " already exists.")
    rec_email = _s(d.get("recEmail"))
    if rec_email and not EMAIL_RE.match(rec_email):
        raise RuleError("Enter a valid recruiter email ID.")
    open_date = _s(d.get("open")) or today
    if not _date(open_date):
        raise RuleError("Choose a valid open date.")
    ivs = clean_interviews(d.get("ivs"))
    reason = _s(d.get("reason"))
    why = reason or "Requisition created"
    db.insert_req(conn, dict(
        id=req_id, bp=bp, title=title, job_cat=d["jobCat"], level=_s(d.get("level")),
        positions=_positions(d.get("positions")), location=_s(d.get("location")), dept=_s(d.get("dept")),
        hm=_s(d.get("hm")), recruiter=_s(d.get("recruiter")), rec_email=rec_email,
        descr=str(d.get("desc") or ""), pmin=_s(d.get("pmin")), pmid=_s(d.get("pmid")), pmax=_s(d.get("pmax")),
        reason=reason, open_date=open_date, clock_date=open_date, closed_date=None, status="Open"))
    db.set_interviews(conn, req_id, ivs)
    db.add_history(conn, req_id, open_date, "Opened", why)
    db.add_log(conn, req_id, open_date, "Requisition created and opened. Reason: " + why)
    return req_id + " created. Status: Open."


def edit_req(conn, state, p, today):
    r = find_req(state, _s(p.get("id")))
    e = p.get("E") or {}
    title = _s(e.get("title"))
    if not title:
        raise RuleError("Job designation cannot be empty.")
    if e.get("jobCat") not in JOBCATS:
        raise RuleError("Choose the job category.")
    rec_email = _s(e.get("recEmail"))
    if rec_email and not EMAIL_RE.match(rec_email):
        raise RuleError("Enter a valid recruiter email ID.")
    only_opened = len(r["hist"]) == 1
    open_date = _s(e.get("open")) if only_opened else r["open"]
    if not _date(open_date):
        raise RuleError("Choose a valid open date.")
    ivs = clean_interviews(e.get("ivs"))
    new = dict(title=title, jobCat=e["jobCat"], level=_s(e.get("level")), location=_s(e.get("location")),
               dept=_s(e.get("dept")), hm=_s(e.get("hm")), recruiter=_s(e.get("recruiter")),
               recEmail=rec_email, reason=_s(e.get("reason")), open=open_date)
    labels = [("title", "Job designation"), ("jobCat", "Job category"), ("level", "Job level"),
              ("location", "Location"), ("dept", "Department"), ("hm", "Hiring manager"),
              ("recruiter", "Recruiter name"), ("recEmail", "Recruiter email"),
              ("reason", "Reason for opening"), ("open", "Open date")]
    changes = [label + " changed from " + (r[k] or "blank") + " to " + (new[k] or "blank")
               for k, label in labels if (r[k] or "") != (new[k] or "")]
    positions = _positions(e.get("positions"))
    if positions != r["positions"]:
        changes.append("Number of positions changed from " + str(r["positions"]) + " to " + str(positions))
    pay = (_s(e.get("pmin")), _s(e.get("pmid")), _s(e.get("pmax")))
    if pay != (r["pmin"], r["pmid"], r["pmax"]):
        changes.append("Pay range changed")
    desc = str(e.get("desc") or "")
    if desc != r["desc"]:
        changes.append("Job description edited")
    workflow_changed = ivs != r["ivs"]
    if workflow_changed:
        changes.append("Interview workflow changed")

    values = dict(title=title, job_cat=new["jobCat"], level=new["level"], positions=positions,
                  location=new["location"], dept=new["dept"], hm=new["hm"], recruiter=new["recruiter"],
                  rec_email=rec_email, reason=new["reason"], open_date=open_date,
                  pmin=pay[0], pmid=pay[1], pmax=pay[2], descr=desc)
    if only_opened:
        values["clock_date"] = open_date
        db.set_first_history_date(conn, r["id"], open_date)
    db.update_req(conn, r["id"], values)
    if workflow_changed:
        old_order = order(r)
        new_order = db.stage_order([db.IVMAP[i["type"]] for i in ivs])
        db.set_interviews(conn, r["id"], ivs)
        # A candidate sitting in a round that was removed moves to the stage in the same position.
        for c in state["C"]:
            for t in c["tags"]:
                if t["req"] == r["id"] and old_order[t["idx"]] not in new_order:
                    db.update_application(conn, c["id"], r["id"],
                                          {"stage": new_order[min(t["idx"], len(new_order) - 1)]})
    if not changes:
        return "No changes made."
    db.add_log(conn, r["id"], today, "; ".join(changes))
    return r["id"] + " updated. " + str(len(changes)) + " change(s) logged."


def req_status(conn, state, p, today):
    r = find_req(state, _s(p.get("id")))
    to, reason = p.get("to"), _s(p.get("reason"))
    last = r["hist"][-1]["d"]
    if r["status"] == "Closed" and hires(state, r) > 0:
        raise RuleError("This requisition has a hired or joined candidate and cannot be reopened.")
    allowed = {"Open": ["On hold", "Closed"], "On hold": ["Open", "Closed"], "Closed": ["Open"]}[r["status"]]
    if to not in allowed:
        raise RuleError("Choose the new status.")
    date = _s(p.get("date"))
    if r["status"] == "On hold" and to == "Closed" and p.get("mode") == "hold":
        date = last
    if not _date(date):
        raise RuleError("Choose the date.")
    if date < last:
        raise RuleError("The date cannot be before the last status activity (" + last + ").")
    if date > today:
        raise RuleError("The date cannot be in the future.")
    if not reason:
        raise RuleError("Enter the reason.")
    activity = "Reopened" if to == "Open" else to
    values = {"status": to}
    if to == "Open":
        values.update(clock_date=date, closed_date=None)
    if to == "Closed":
        values["closed_date"] = date
    db.update_req(conn, r["id"], values)
    db.add_history(conn, r["id"], date, activity, reason)
    db.add_log(conn, r["id"], date, "Status: " + activity + ". Reason: " + reason)
    if to == "Open":
        return r["id"] + " reopened on " + date + ". Time to fill now counts from this date."
    if to == "On hold":
        return r["id"] + " put on hold on " + date + "."
    return r["id"] + " closed on " + date + ". Time to fill: " + str(days_between(r["clock"], date)) + " days."


# ---------------------------------------------------------------- candidates
def add_candidate(conn, state, p, today):
    cd = p.get("CD") or {}
    check_category(cd)
    check_person(cd)
    check_source(cd)
    req_ids = list(dict.fromkeys(cd.get("reqs") or []))
    if not req_ids:
        raise RuleError("Select at least one open requisition.")
    for rid in req_ids:
        r = find_req(state, rid)
        if r["status"] != "Open":
            raise RuleError(rid + " is " + r["status"].lower() + " and cannot take new candidates.")
    email, phone = _s(cd.get("email")), _s(cd.get("phone"))
    for c in state["C"]:
        if same_person(c, email, phone):
            raise RuleError("This candidate already exists: " + full_name(c) + ". Open the existing record instead.")
    resume = decode_resume(cd.get("resumeFile"))
    cand_id, seq = db.next_candidate_id(conn)
    person = dict(first=_s(cd.get("first")), middle=_s(cd.get("middle")), last=_s(cd.get("last")))
    db.insert_candidate(conn, dict(
        id=cand_id, seq=seq, email=email, phone=phone, location=_s(cd.get("location")),
        category=cd["category"], emp_status=cd.get("empStatus") if cd["category"] in EMP_CATS else "",
        source=cd["source"], src_detail=_s(cd.get("srcDetail")) if cd["source"] in SRC_FOLLOW else "",
        resume_name="", added=today, **person))
    name = full_name(person)
    for rid in req_ids:
        db.add_application(conn, cand_id, rid)
        db.add_log(conn, rid, today, "Candidate added: " + name)
    if resume:
        db.save_resume(conn, cand_id, *resume)
    return name + " saved and tagged to " + ", ".join(req_ids) + "."


def edit_candidate(conn, state, p, today):
    c = find_cand(state, _s(p.get("id")))
    ce = p.get("CE") or {}
    check_category(ce)
    check_person(ce)
    check_source(ce)
    req_ids = list(dict.fromkeys(ce.get("reqs") or []))
    if not req_ids:
        raise RuleError("Keep at least one requisition tagged.")
    old_ids = [t["req"] for t in c["tags"]]
    for rid in req_ids:
        r = find_req(state, rid)
        if rid not in old_ids and r["status"] != "Open":
            raise RuleError(rid + " is " + r["status"].lower() + " and cannot take new candidates.")
    email, phone = _s(ce.get("email")), _s(ce.get("phone"))
    for other in state["C"]:
        if other["id"] != c["id"] and same_person(other, email, phone):
            raise RuleError("Another candidate already has this email and phone: " + full_name(other) + ".")
    resume = decode_resume(ce.get("resumeFile"))
    person = dict(first=_s(ce.get("first")), middle=_s(ce.get("middle")), last=_s(ce.get("last")))
    db.update_candidate(conn, c["id"], dict(
        email=email, phone=phone, location=_s(ce.get("location")), category=ce["category"],
        emp_status=ce.get("empStatus") if ce["category"] in EMP_CATS else "",
        source=ce["source"], src_detail=_s(ce.get("srcDetail")) if ce["source"] in SRC_FOLLOW else "",
        **person))
    name = full_name(person)
    for rid in req_ids:
        if rid not in old_ids:
            db.add_application(conn, c["id"], rid)
            db.add_log(conn, rid, today, "Candidate tagged: " + name)
    for rid in old_ids:
        if rid not in req_ids:
            db.delete_application(conn, c["id"], rid)
            db.add_log(conn, rid, today, "Candidate removed from requisition: " + name)
    if resume:
        db.save_resume(conn, c["id"], *resume)
    return "Candidate details saved."


def _tag(c, req_id):
    for t in c["tags"]:
        if t["req"] == req_id:
            return t
    raise RuleError("This candidate is no longer tagged to " + req_id + ". Refresh the page and try again.")


def set_stage(conn, state, p, today):
    c = find_cand(state, _s(p.get("cand")))
    r = find_req(state, _s(p.get("req")))
    _tag(c, r["id"])
    label = p.get("label")
    if label not in order(r):
        raise RuleError("Choose a stage from the list.")
    extra, doj = "", ""
    if label in ("Joined", "BGV"):
        doj = _s(p.get("doj"))
        if not _date(doj):
            raise RuleError("Enter the date of joining before submitting the " + label + " stage.")
        extra = " (date of joining " + doj + ")"
    db.update_application(conn, c["id"], r["id"], {"stage": label, "declined": False, "reason": "", "doj": doj})
    db.add_log(conn, r["id"], today, "Stage set to " + label + extra + ": " + full_name(c))
    return full_name(c) + " is now at " + label + " for " + r["id"] + extra + "."


def decline(conn, state, p, today):
    c = find_cand(state, _s(p.get("cand")))
    r = find_req(state, _s(p.get("req")))
    _tag(c, r["id"])
    reason = _s(p.get("reason"))
    if not reason:
        raise RuleError("Enter the reason for the decline.")
    db.update_application(conn, c["id"], r["id"], {"declined": True, "reason": reason})
    db.add_log(conn, r["id"], today, "Declined: " + full_name(c) + ". Reason: " + reason)
    return full_name(c) + " is declined for " + r["id"] + "."


WRITES = {"create_req": create_req, "edit_req": edit_req, "req_status": req_status,
          "add_candidate": add_candidate, "edit_candidate": edit_candidate,
          "set_stage": set_stage, "decline": decline}


# ---------------------------------------------------------------- entry point
def handle(engine, action):
    """Carry out one action from the screen and return the answer shown to the user."""
    kind = action.get("type")
    p = action.get("payload") or {}
    ack = {"nonce": action.get("nonce"), "ok": True, "msg": ""}
    today = resolve_today(action.get("today"))
    try:
        if kind == "poll":
            return ack
        if kind == "export":
            with engine.connect() as conn:
                state = db.read_state(conn)
            data = excel_export.build_workbook(state)
            name = "TA_Portal_Export_" + today + ".xlsx"
            ack["file"] = {"name": name, "b64": base64.b64encode(data).decode(),
                           "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
            ack["msg"] = ("Downloaded " + name + " with 6 sheets: Requisitions, Req status history, "
                          "Candidates, Stage counts, Joiners, Activity log.")
            return ack
        if kind == "get_resume":
            with engine.connect() as conn:
                f = db.get_resume(conn, _s(p.get("cand")))
            if f is None:
                raise RuleError("No resume file has been uploaded for this candidate.")
            ack["file"] = {"name": f["name"], "mime": f["mime"], "b64": base64.b64encode(f["data"]).decode()}
            return ack
        if kind not in WRITES:
            raise RuleError("This action is not recognised.")
        with engine.begin() as conn:
            state = db.read_state(conn)
            ack["msg"] = WRITES[kind](conn, state, p, today)
            db.bump_version(conn)
        return ack
    except RuleError as e:
        ack.update(ok=False, msg=str(e))
    except Exception as e:  # database or unexpected failure: nothing is half-saved, the transaction rolls back
        print("ATS action failed:", kind, repr(e))
        ack.update(ok=False, msg="This could not be completed because of an unexpected error. Please try again. (" + type(e).__name__ + ")")
    return ack
