"""Data layer for the Talent Acquisition Portal.

Every database read and write lives in this file. The rest of the app never
writes SQL. The same code runs on two databases:

* Supabase (PostgreSQL) when a DATABASE_URL is configured. This is the shared,
  online database used by the deployed app.
* A local SQLite file (ats_local.db) when no DATABASE_URL is configured. This is
  for running the app on your own computer.
"""
import datetime as dt
import os

from sqlalchemy import (Boolean, Column, Integer, LargeBinary, MetaData, Table, Text,
                        UniqueConstraint, create_engine, delete, func, insert, select, update)
from sqlalchemy.engine import URL

IVMAP = {
    "L1 interview": "L1", "L2 interview": "L2", "L3 interview": "L3", "L4 interview": "L4",
    "L5 interview": "L5", "Behavioural interview": "BI", "Get to know you interview": "GTKY",
    "Capstone interview": "Capstone", "Others": "Others",
}
STAGES_BEFORE = ["New Application", "Screening"]
STAGES_AFTER = ["Offer", "Hire", "Joined", "BGV"]

metadata = MetaData()

requisitions = Table(
    "ats_requisitions", metadata,
    Column("id", Text, primary_key=True),
    Column("seq", Integer, nullable=False),
    Column("bp", Text), Column("title", Text), Column("job_cat", Text), Column("level", Text),
    Column("positions", Integer), Column("location", Text), Column("dept", Text),
    Column("hm", Text), Column("recruiter", Text), Column("rec_email", Text),
    Column("descr", Text), Column("pmin", Text), Column("pmid", Text), Column("pmax", Text),
    Column("reason", Text), Column("open_date", Text), Column("clock_date", Text),
    Column("closed_date", Text), Column("status", Text),
)
req_interviews = Table(
    "ats_req_interviews", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("req_id", Text, index=True), Column("pos", Integer),
    Column("type", Text), Column("who", Text),
)
req_history = Table(
    "ats_req_history", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("req_id", Text, index=True), Column("d", Text), Column("s", Text), Column("reason", Text),
)
req_log = Table(
    "ats_req_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("req_id", Text, index=True), Column("d", Text), Column("t", Text),
)
candidates = Table(
    "ats_candidates", metadata,
    Column("id", Text, primary_key=True),
    Column("seq", Integer, nullable=False),
    Column("first", Text), Column("middle", Text), Column("last", Text),
    Column("email", Text), Column("phone", Text), Column("location", Text),
    Column("category", Text), Column("emp_status", Text),
    Column("source", Text), Column("src_detail", Text),
    Column("resume_name", Text), Column("added", Text),
)
applications = Table(
    "ats_applications", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cand_id", Text, index=True), Column("req_id", Text, index=True),
    Column("stage", Text), Column("declined", Boolean, default=False),
    Column("reason", Text), Column("doj", Text),
    UniqueConstraint("cand_id", "req_id", name="ats_app_unique"),
)
resumes = Table(
    "ats_resumes", metadata,
    Column("cand_id", Text, primary_key=True),
    Column("filename", Text), Column("mime", Text),
    Column("data", LargeBinary), Column("uploaded_at", Text),
)
meta = Table("ats_meta", metadata, Column("key", Text, primary_key=True), Column("value", Text))


# ---------------------------------------------------------------- connection
def _parse_url(url):
    """Turn a postgresql://user:password@host:port/db link into a SQLAlchemy URL.

    Parsed by hand so that a password containing characters such as @ or # still works.
    """
    rest = url.split("://", 1)[1]
    creds, hostpart = rest.rsplit("@", 1)
    user, password = creds.split(":", 1) if ":" in creds else (creds, "")
    hostport, _, dbname = hostpart.partition("/")
    dbname = dbname.split("?", 1)[0] or "postgres"
    host, _, port = hostport.partition(":")
    return URL.create("postgresql+psycopg2", username=user, password=password, host=host,
                      port=int(port) if port else 5432, database=dbname)


def make_engine(database_url=None):
    if database_url:
        if "[YOUR-PASSWORD]" in database_url:
            raise ValueError("DATABASE_URL still contains [YOUR-PASSWORD]. Replace it with the database password.")
        return create_engine(_parse_url(database_url.strip()), pool_size=3, max_overflow=2,
                             pool_pre_ping=True, pool_recycle=300)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ats_local.db")
    return create_engine("sqlite:///" + path, connect_args={"check_same_thread": False})


def init_db(engine):
    metadata.create_all(engine)
    with engine.begin() as conn:
        if conn.execute(select(meta.c.value).where(meta.c.key == "ver")).first() is None:
            conn.execute(insert(meta).values(key="ver", value="1"))


# ---------------------------------------------------------------- meta
def get_meta(conn, key):
    row = conn.execute(select(meta.c.value).where(meta.c.key == key)).first()
    return row[0] if row else None


def set_meta(conn, key, value):
    if get_meta(conn, key) is None:
        conn.execute(insert(meta).values(key=key, value=str(value)))
    else:
        conn.execute(update(meta).where(meta.c.key == key).values(value=str(value)))


def bump_version(conn):
    """Called after every change so other users' screens know to refresh."""
    set_meta(conn, "ver", int(get_meta(conn, "ver") or 0) + 1)


# ---------------------------------------------------------------- reading
def stage_order(rounds):
    return STAGES_BEFORE + list(rounds) + STAGES_AFTER


def read_state(conn):
    """Return everything the screens need, in the shape the front end uses."""
    ivs, hist, log = {}, {}, {}
    for row in conn.execute(select(req_interviews).order_by(req_interviews.c.req_id, req_interviews.c.pos)):
        ivs.setdefault(row.req_id, []).append({"type": row.type, "who": row.who or ""})
    for row in conn.execute(select(req_history).order_by(req_history.c.id)):
        hist.setdefault(row.req_id, []).append({"d": row.d, "s": row.s, "reason": row.reason or ""})
    for row in conn.execute(select(req_log).order_by(req_log.c.id)):
        m = row._mapping  # "t" is also a built-in attribute of a row, so read the columns by name
        log.setdefault(m["req_id"], []).append({"d": m["d"], "t": m["t"]})

    reqs, orders = [], {}
    for r in conn.execute(select(requisitions).order_by(requisitions.c.seq)):
        r_ivs = ivs.get(r.id, [])
        rounds = [IVMAP[i["type"]] for i in r_ivs if i["type"] in IVMAP]
        orders[r.id] = stage_order(rounds)
        reqs.append({
            "id": r.id, "bp": r.bp or "", "title": r.title or "", "jobCat": r.job_cat or "",
            "level": r.level or "", "positions": r.positions or 1, "location": r.location or "",
            "dept": r.dept or "", "hm": r.hm or "", "recruiter": r.recruiter or "",
            "recEmail": r.rec_email or "", "desc": r.descr or "", "pmin": r.pmin or "",
            "pmid": r.pmid or "", "pmax": r.pmax or "", "reason": r.reason or "",
            "open": r.open_date, "clock": r.clock_date, "closed": r.closed_date, "status": r.status,
            "rounds": rounds, "ivs": r_ivs, "hist": hist.get(r.id, []), "log": log.get(r.id, []),
        })

    tags = {}
    for a in conn.execute(select(applications).order_by(applications.c.id)):
        order = orders.get(a.req_id)
        if order is None:
            continue
        idx = order.index(a.stage) if a.stage in order else 0
        tags.setdefault(a.cand_id, []).append({
            "req": a.req_id, "idx": idx, "declined": bool(a.declined),
            "reason": a.reason or "", "doj": a.doj or "",
        })
    with_file = {row[0] for row in conn.execute(select(resumes.c.cand_id))}
    cands = []
    for c in conn.execute(select(candidates).order_by(candidates.c.seq)):
        cands.append({
            "id": c.id, "first": c.first or "", "middle": c.middle or "", "last": c.last or "",
            "email": c.email or "", "phone": c.phone or "", "location": c.location or "",
            "category": c.category or "", "empStatus": c.emp_status or "",
            "source": c.source or "", "srcDetail": c.src_detail or "",
            "resume": c.resume_name or "", "hasResume": c.id in with_file,
            "added": c.added, "tags": tags.get(c.id, []),
        })
    return {"R": reqs, "C": cands}


# ---------------------------------------------------------------- requisitions
def _next_seq(conn, table):
    return (conn.execute(select(func.max(table.c.seq))).scalar() or 0) + 1


def insert_req(conn, values):
    conn.execute(insert(requisitions).values(seq=_next_seq(conn, requisitions), **values))


def update_req(conn, req_id, values):
    conn.execute(update(requisitions).where(requisitions.c.id == req_id).values(**values))


def set_interviews(conn, req_id, ivs):
    conn.execute(delete(req_interviews).where(req_interviews.c.req_id == req_id))
    for pos, iv in enumerate(ivs):
        conn.execute(insert(req_interviews).values(req_id=req_id, pos=pos, type=iv["type"], who=iv.get("who", "")))


def add_history(conn, req_id, d, s, reason):
    conn.execute(insert(req_history).values(req_id=req_id, d=d, s=s, reason=reason))


def set_first_history_date(conn, req_id, d):
    first = conn.execute(select(func.min(req_history.c.id)).where(req_history.c.req_id == req_id)).scalar()
    if first is not None:
        conn.execute(update(req_history).where(req_history.c.id == first).values(d=d))


def add_log(conn, req_id, d, text):
    conn.execute(insert(req_log).values(req_id=req_id, d=d, t=text))


# ---------------------------------------------------------------- candidates
def next_candidate_id(conn):
    seq = _next_seq(conn, candidates)
    return "C" + str(seq), seq


def insert_candidate(conn, values):
    conn.execute(insert(candidates).values(**values))


def update_candidate(conn, cand_id, values):
    conn.execute(update(candidates).where(candidates.c.id == cand_id).values(**values))


def add_application(conn, cand_id, req_id, stage="New Application", declined=False, reason="", doj=""):
    conn.execute(insert(applications).values(cand_id=cand_id, req_id=req_id, stage=stage,
                                             declined=declined, reason=reason, doj=doj))


def update_application(conn, cand_id, req_id, values):
    conn.execute(update(applications).where(applications.c.cand_id == cand_id,
                                            applications.c.req_id == req_id).values(**values))


def delete_application(conn, cand_id, req_id):
    conn.execute(delete(applications).where(applications.c.cand_id == cand_id,
                                            applications.c.req_id == req_id))


# ---------------------------------------------------------------- resumes
def save_resume(conn, cand_id, filename, mime, data):
    conn.execute(delete(resumes).where(resumes.c.cand_id == cand_id))
    conn.execute(insert(resumes).values(cand_id=cand_id, filename=filename, mime=mime, data=data,
                                        uploaded_at=dt.datetime.utcnow().isoformat(timespec="seconds")))
    update_candidate(conn, cand_id, {"resume_name": filename})


def get_resume(conn, cand_id):
    row = conn.execute(select(resumes).where(resumes.c.cand_id == cand_id)).first()
    if row is None:
        return None
    return {"name": row.filename, "mime": row.mime or "application/octet-stream", "data": bytes(row.data)}


def storage_summary(conn):
    count = conn.execute(select(func.count()).select_from(resumes)).scalar() or 0
    size = conn.execute(select(func.coalesce(func.sum(func.length(resumes.c.data)), 0))).scalar() or 0
    return {"resumes": int(count), "bytes": int(size)}
