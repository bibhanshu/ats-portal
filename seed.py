"""Sample data for the demo. Loaded once, the first time the app starts on an empty database.

Everything here is made up. Set SEED_SAMPLE_DATA = "false" in the secrets to start with an empty app.
"""
import db

REQS = [
    ("REQ-1834", "Senior Security Engineer", "P4", 1, "Bengaluru", "Technology", "Full time", ["L1", "L2"], "New headcount",
     [("2026-09-20", "Opened", "New headcount approved"), ("2026-10-15", "Closed", "Position filled")]),
    ("REQ-1835", "Data Engineer", "P3", 2, "Mumbai", "Technology", "Contract", ["L1"], "New headcount",
     [("2026-09-28", "Opened", "New headcount approved"), ("2026-10-06", "On hold", "Budget review"),
      ("2026-10-12", "Reopened", "Budget confirmed")]),
    ("REQ-1837", "Associate Platform Engineer", "P3", 3, "Bengaluru", "Technology", "Full time", ["L1", "L2", "L3", "BI"], "Backfill",
     [("2026-10-01", "Opened", "Backfill approved")]),
    ("REQ-1838", "Associate Platform Engineer", "P3", 1, "Pune", "Technology", "Full time", ["L1", "BI"], "Backfill",
     [("2026-10-05", "Opened", "Backfill approved"), ("2026-10-24", "Closed", "Position filled")]),
    ("REQ-1840", "Software Test Engineer", "P2", 1, "Chennai", "Technology", "Contract", ["L1"], "New headcount",
     [("2026-10-01", "Opened", "New headcount approved"), ("2026-10-20", "On hold", "Hiring manager on leave")]),
    ("REQ-1839", "Director, Product Management", "P6", 1, "Bengaluru", "Product", "Full time", ["L1", "L2", "L3", "BI"], "New headcount",
     [("2026-09-17", "Opened", "New headcount approved"), ("2026-10-08", "Closed", "Position filled")]),
]
# (number, last name, phone ending, location, category, employment status, source, source detail, added, applications)
# application = (req, stage, declined, decline reason, date of joining)
CANDS = [
    (1, "Candidate One", "02", "Bengaluru", "Contractor", "", "LinkedIn", "", "2026-10-22",
     [("REQ-1837", "Screening", False, "", ""), ("REQ-1840", "Screening", False, "", "")]),
    (2, "Candidate Two", "03", "Pune", "Employee of Shell Recharge", "Currently employed", "Referral", "", "2026-10-20",
     [("REQ-1837", "L2", False, "", "")]),
    (3, "Candidate Three", "04", "Mumbai", "Full time employee", "", "Naukri", "", "2026-10-18",
     [("REQ-1835", "L1", False, "", "")]),
    (4, "Candidate Four", "05", "Pune", "Rehire", "", "Self-sourcing", "Campus network", "2026-10-16",
     [("REQ-1838", "BGV", False, "", "2026-11-02")]),
    (5, "Candidate Five", "06", "Bengaluru", "Employee of Shell", "Past employee", "Referral", "", "2026-10-12",
     [("REQ-1839", "Joined", False, "", "2027-01-04")]),
    (6, "Candidate Six", "07", "Chennai", "Full time employee", "", "Others", "Job fair", "2026-10-10",
     [("REQ-1834", "L2", True, "Accepted a counter-offer elsewhere", "")]),
    (7, "Candidate Seven", "08", "Bengaluru", "Full time employee", "", "LinkedIn", "", "2026-09-28",
     [("REQ-1834", "Hire", False, "", ""), ("REQ-1839", "L1", False, "", "")]),
    (8, "Candidate Eight", "09", "Bengaluru", "Contractor", "", "Vendor", "Sample vendor", "2026-10-24",
     [("REQ-1837", "L1", False, "", "")]),
    (9, "Candidate Nine", "01", "Bengaluru", "Full time employee", "", "Vendor", "Sample vendor", "2026-10-25",
     [("REQ-1837", "New Application", False, "", "")]),
]
TYPE_OF = {v: k for k, v in db.IVMAP.items()}


def sample_pdf(lines):
    """A very small one-page PDF, written by hand so no extra library is needed."""
    def esc(text):
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = "BT /F1 12 Tf 60 780 Td 18 TL " + " ".join("(" + esc(x) + ") Tj T*" for x in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        "<< /Length " + str(len(stream)) + " >>\nstream\n" + stream + "\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = "%PDF-1.4\n", []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(i) + " 0 obj\n" + obj + "\nendobj\n"
    xref = len(out)
    out += "xref\n0 " + str(len(objects) + 1) + "\n0000000000 65535 f \n"
    out += "".join("%010d 00000 n \n" % o for o in offsets)
    out += "trailer\n<< /Size " + str(len(objects) + 1) + " /Root 1 0 R >>\nstartxref\n" + str(xref) + "\n%%EOF\n"
    return out.encode("latin-1")


def load_sample_data(conn):
    for rid, title, level, positions, location, dept, job_cat, rounds, reason, hist in REQS:
        status, clock, closed = "Open", hist[0][0], None
        for d, s, why in hist[1:]:
            if s == "On hold":
                status = "On hold"
            elif s == "Reopened":
                status, clock = "Open", d
            elif s == "Closed":
                status, closed = "Closed", d
        db.insert_req(conn, dict(
            id=rid, bp="BP-1", title=title, job_cat=job_cat, level=level, positions=positions,
            location=location, dept=dept, hm="Sample hiring manager", recruiter="Sample recruiter",
            rec_email="recruiter@example.com", descr="Sample job description. Paste the full text here.",
            pmin="", pmid="", pmax="", reason=reason, open_date=hist[0][0], clock_date=clock,
            closed_date=closed, status=status))
        db.set_interviews(conn, rid, [{"type": TYPE_OF[x], "who": "Sample interviewer"} for x in rounds])
        for i, (d, s, why) in enumerate(hist):
            db.add_history(conn, rid, d, s, why)
            db.add_log(conn, rid, d, ("Requisition created and opened. Reason: " if i == 0 else "Status: " + s + ". Reason: ") + why)
    for n, last, ph, location, category, emp, source, detail, added, apps in CANDS:
        cand_id, seq = db.next_candidate_id(conn)
        email = "candidate" + str(n) + "@example.com"
        db.insert_candidate(conn, dict(
            id=cand_id, seq=seq, first="Sample", middle="", last=last, email=email, phone="70000 000" + ph,
            location=location, category=category, emp_status=emp, source=source, src_detail=detail,
            resume_name="", added=added))
        for rid, stage, declined, why, doj in apps:
            db.add_application(conn, cand_id, rid, stage, declined, why, doj)
        pdf = sample_pdf(["Sample resume (made-up data)", "", "Name: Sample " + last, "Email: " + email,
                          "Location: " + location, "", "This file exists only to show how resumes are stored and opened."])
        db.save_resume(conn, cand_id, "Sample_" + last.replace(" ", "_") + ".pdf", "application/pdf", pdf)
