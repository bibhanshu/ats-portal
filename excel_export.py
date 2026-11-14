"""Excel export. Builds one workbook with six sheets from the current data."""
import datetime as dt
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import db

ALL_STAGES = ["New Application", "Screening", "L1", "L2", "L3", "L4", "L5", "BI", "GTKY", "Capstone",
              "Others", "Offer", "Hire", "Joined", "BGV", "Declined"]
EMP_CATS = ["Employee of Shell Recharge", "Employee of Shell"]

HEAD_FILL = PatternFill("solid", fgColor="0A97A6")
HEAD_FONT = Font(name="Arial", size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name="Arial", size=10)
TOTAL_FONT = Font(name="Arial", size=10, bold=True)
EDGE = Side(style="thin", color="D3D1C7")
BORDER = Border(left=EDGE, right=EDGE, top=EDGE, bottom=EDGE)


def _d(value):
    """ISO text date -> real Excel date, so the column sorts and filters as dates."""
    return dt.date.fromisoformat(value) if value else None


def _name(c):
    return " ".join(x for x in [c["first"], c["middle"], c["last"]] if x)


def _label(req, tag):
    return "Declined" if tag["declined"] else db.stage_order(req["rounds"])[tag["idx"]]


def _cat_text(c):
    if c["category"] in EMP_CATS and c["empStatus"]:
        return c["category"] + " (" + c["empStatus"].lower() + ")"
    return c["category"]


def _days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def _sheet(wb, title, rows, bold_last=False):
    ws = wb.create_sheet(title)
    for row in rows:
        ws.append(row)
    widths = [8] * len(rows[0])
    for r_i, row in enumerate(ws.iter_rows(), start=1):
        for c_i, cell in enumerate(row):
            cell.border = BORDER
            if r_i == 1:
                cell.fill, cell.font = HEAD_FILL, HEAD_FONT
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            else:
                cell.font = TOTAL_FONT if (bold_last and r_i == len(rows)) else BODY_FONT
                cell.alignment = Alignment(horizontal="left", vertical="top")
                if isinstance(cell.value, dt.date):
                    cell.number_format = "DD-MMM-YYYY"
            length = 11 if isinstance(cell.value, dt.date) else len(str(cell.value if cell.value is not None else ""))
            widths[c_i] = max(widths[c_i], length)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = min(w + 3, 60)
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = "A1:" + get_column_letter(len(rows[0])) + str(len(rows))
    return ws


def build_workbook(state):
    reqs, cands = state["R"], state["C"]
    by_id = {r["id"]: r for r in reqs}
    tags = [(c, t, by_id[t["req"]]) for c in cands for t in c["tags"] if t["req"] in by_id]

    def hired(r):
        hire_idx = db.stage_order(r["rounds"]).index("Hire")
        return sum(1 for c, t, rr in tags if rr is r and not t["declined"] and t["idx"] >= hire_idx)

    s_reqs = [["Req number", "BP number", "Job designation", "Job category", "Job level", "Positions",
               "Positions filled", "Location", "Department", "Hiring manager", "Recruiter name",
               "Recruiter email ID", "Reason for opening", "Status", "First open date",
               "Time to fill counted from", "Closed date", "Time to fill (days)", "Times put on hold",
               "Candidates tagged", "Minimum pay", "Midpoint pay", "Maximum pay"]]
    for r in reqs:
        ttf = _days(r["clock"], r["closed"]) if r["status"] == "Closed" else None
        s_reqs.append([r["id"], r["bp"], r["title"], r["jobCat"], r["level"], r["positions"],
                       min(hired(r), r["positions"]), r["location"], r["dept"], r["hm"], r["recruiter"],
                       r["recEmail"], r["reason"], r["status"], _d(r["open"]), _d(r["clock"]), _d(r["closed"]),
                       ttf, sum(1 for h in r["hist"] if h["s"] == "On hold"),
                       sum(1 for c, t, rr in tags if rr is r), r["pmin"], r["pmid"], r["pmax"]])

    s_hist = [["Req number", "Job designation", "Date", "Activity", "Reason", "Days since previous activity"]]
    for r in reqs:
        for i, h in enumerate(r["hist"]):
            s_hist.append([r["id"], r["title"], _d(h["d"]), h["s"], h["reason"],
                           _days(r["hist"][i - 1]["d"], h["d"]) if i else None])

    s_cands = [["Candidate ID", "Name", "Email", "Phone", "Candidate location", "Category",
                "Employment status", "Source", "Source detail", "Added date", "Req number",
                "Job designation", "Job category", "Req status", "Current stage", "Date of joining",
                "Decline reason", "Resume file"]]
    for c, t, r in tags:
        s_cands.append([c["id"], _name(c), c["email"], c["phone"], c["location"], c["category"],
                        c["empStatus"] if c["category"] in EMP_CATS else None, c["source"], c["srcDetail"] or None,
                        _d(c["added"]), r["id"], r["title"], r["jobCat"], r["status"], _label(r, t),
                        _d(t["doj"]), t["reason"] if t["declined"] else None, c["resume"] or None])

    s_counts = [["Req number", "Job designation", "Status"] + ALL_STAGES + ["Total"]]
    for r in reqs:
        mine = [_label(r, t) for c, t, rr in tags if rr is r]
        s_counts.append([r["id"], r["title"], r["status"]] + [mine.count(s) for s in ALL_STAGES] + [len(mine)])
    every = [_label(r, t) for c, t, r in tags]
    s_counts.append(["All requisitions", None, None] + [every.count(s) for s in ALL_STAGES] + [len(every)])

    s_join = [["Candidate", "Category", "Req number", "Job designation", "Current stage", "Date of joining"]]
    for c, t, r in tags:
        if t["doj"] and not t["declined"]:
            s_join.append([_name(c), _cat_text(c), r["id"], r["title"], _label(r, t), _d(t["doj"])])

    s_log = [["Req number", "Job designation", "Date", "Activity"]]
    for r in reqs:
        for entry in r["log"]:
            s_log.append([r["id"], r["title"], _d(entry["d"]), entry["t"]])

    wb = Workbook()
    wb.remove(wb.active)
    _sheet(wb, "Requisitions", s_reqs)
    _sheet(wb, "Req status history", s_hist)
    _sheet(wb, "Candidates", s_cands)
    _sheet(wb, "Stage counts", s_counts, bold_last=True)
    _sheet(wb, "Joiners", s_join)
    _sheet(wb, "Activity log", s_log)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
