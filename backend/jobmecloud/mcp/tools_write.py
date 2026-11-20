"""Tools that change things. Each one passes straight through to the app's own route, so the checks, the
activity history and the follow-up rules are exactly what the website gets. Nothing here deletes anything."""

from jobmecloud.mcp.registry import ToolContext, ToolError, tool
from jobmecloud.mcp.tools_read import JOB_ARG, parse_id, parse_job_ref

STR = {"type": "string"}
DATE = {"type": "string", "description": "YYYY-MM-DD"}


def _given(args: dict, *names: str) -> dict:
    """The named arguments the chat actually supplied."""
    return {n: args[n] for n in names if n in args and args[n] is not None}


def _schema(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required)}


@tool("set_job_status", "Change a job's status (Applied, Interviewing, Offer, Skipped, Rejected, Withdrawn, ...). "
                        "Skipped needs skip_reason; Duplicate needs duplicate_of.",
      _schema({"job": JOB_ARG, "status": STR, "date": DATE, "skip_reason": STR, "skip_note": STR, "note": STR,
               "duplicate_of": {"type": "integer"}}, ("job", "status")), write=True)
def set_job_status(ctx: ToolContext, args: dict):
    body = _given(args, "status", "date", "skip_reason", "skip_note", "note", "duplicate_of")
    return ctx.call("POST", f"/api/jobs/{parse_job_ref(args.get('job'))}/status", json=body)


@tool("update_job", "Replace a job's notes and/or set its applied, first-response or outcome dates. "
                    "To add to the notes use append_job_note.",
      _schema({"job": JOB_ARG, "notes": STR, "applied_date": DATE, "first_response_date": DATE, "outcome_date": DATE},
              ("job",)), write=True)
def update_job(ctx: ToolContext, args: dict):
    body = {k: args[k] for k in ("notes", "applied_date", "first_response_date", "outcome_date") if k in args}
    return ctx.call("PATCH", f"/api/jobs/{parse_job_ref(args.get('job'))}", json=body)


@tool("append_job_note", "Add a dated line to a job's notes without losing what is there.",
      _schema({"job": JOB_ARG, "text": STR}, ("job", "text")), write=True)
def append_job_note(ctx: ToolContext, args: dict):
    text = str(args.get("text") or "").strip()
    if not text:
        raise ToolError("Say what to add to the notes.")
    job_id = parse_job_ref(args.get("job"))
    current = (ctx.call("GET", f"/api/jobs/{job_id}").get("notes") or "").rstrip()
    line = f"{ctx.today.isoformat()}: {text}"
    return ctx.call("PATCH", f"/api/jobs/{job_id}", json={"notes": f"{current}\n{line}" if current else line})


@tool("add_job", "Add a job you found (it lands as New). Use check_job instead to read and score a posting.",
      _schema({"employer": STR, "title": STR, "apply_url": STR, "location": STR, "notes": STR},
              ("employer", "title")), write=True)
def add_job(ctx: ToolContext, args: dict):
    return ctx.call("POST", "/api/jobs", json=_given(args, "employer", "title", "apply_url", "location", "notes"))


@tool("check_job", "Read a job posting (pasted text or a link), add it to JobMe and score its fit. Uses the owner's AI "
                   "connection, so there is a daily limit.",
      _schema({"input": {"type": "string", "description": "The posting text, or a link to it"}}, ("input",)),
      write=True, ai_cost=True)
def check_job(ctx: ToolContext, args: dict):
    return ctx.call("POST", "/api/jobs/check", json={"input": str(args.get("input") or "")})


@tool("re_evaluate_job", "Give a job a pasted description (for a posting that could not be read) so JobMe reads it. "
                         "Uses the owner's AI connection, so there is a daily limit.",
      _schema({"job": JOB_ARG, "description": STR}, ("job", "description")), write=True, ai_cost=True)
def re_evaluate_job(ctx: ToolContext, args: dict):
    return ctx.call("POST", f"/api/jobs/{parse_job_ref(args.get('job'))}/description",
                    json={"text": str(args.get("description") or "")})


@tool("create_followup", "Schedule a follow-up. type: Application check-in, Recruiter outreach, Thank-you note, "
                         "Referral request or Other.",
      _schema({"type": STR, "due_date": DATE, "job": JOB_ARG, "contact_id": {"type": "integer"}, "note": STR},
              ("type", "due_date")), write=True)
def create_followup(ctx: ToolContext, args: dict):
    body = _given(args, "type", "due_date", "note")
    if args.get("contact_id") not in (None, ""):
        body["contact_id"] = parse_id(args["contact_id"], "contact id")
    if args.get("job") not in (None, ""):
        body["job_id"] = parse_job_ref(args["job"])
    return ctx.call("POST", "/api/followups", json=body)


@tool("complete_followup", "Mark a follow-up done, optionally scheduling the next one on next_date.",
      _schema({"id": {"type": "integer"}, "outcome_note": STR, "next_date": DATE}, ("id",)), write=True)
def complete_followup(ctx: ToolContext, args: dict):
    return ctx.call("POST", f"/api/followups/{parse_id(args.get('id'), 'follow-up id')}/done", json=_given(args, "outcome_note", "next_date"))


@tool("snooze_followup", "Hide a follow-up until a date.",
      _schema({"id": {"type": "integer"}, "until": DATE}, ("id", "until")), write=True)
def snooze_followup(ctx: ToolContext, args: dict):
    return ctx.call("POST", f"/api/followups/{parse_id(args.get('id'), 'follow-up id')}/snooze", json=_given(args, "until"))


@tool("reschedule_followup", "Move a follow-up to a new due date.",
      _schema({"id": {"type": "integer"}, "due_date": DATE}, ("id", "due_date")), write=True)
def reschedule_followup(ctx: ToolContext, args: dict):
    return ctx.call("POST", f"/api/followups/{parse_id(args.get('id'), 'follow-up id')}/reschedule", json=_given(args, "due_date"))


@tool("cancel_followup", "Cancel a follow-up (it stays in the history).",
      _schema({"id": {"type": "integer"}}, ("id",)), write=True)
def cancel_followup(ctx: ToolContext, args: dict):
    return ctx.call("POST", f"/api/followups/{parse_id(args.get('id'), 'follow-up id')}/cancel")


_CONTACT_FIELDS = ("name", "employer", "role", "link", "relationship", "status", "notes")
_CONTACT_PROPS = {"name": STR, "job": JOB_ARG, "employer": STR, "role": STR, "link": STR, "relationship": STR,
                  "status": STR, "notes": STR}


@tool("create_contact", "Add a contact (a recruiter, hiring manager, referral...), optionally tied to a job.",
      _schema(_CONTACT_PROPS, ("name",)), write=True)
def create_contact(ctx: ToolContext, args: dict):
    body = _given(args, *_CONTACT_FIELDS)
    if args.get("job") not in (None, ""):
        body["job_id"] = parse_job_ref(args["job"])
    return ctx.call("POST", "/api/contacts", json=body)


@tool("update_contact", "Change some fields of a contact; fields you leave out stay as they are.",
      _schema({"id": {"type": "integer"}, **_CONTACT_PROPS}, ("id",)), write=True)
def update_contact(ctx: ToolContext, args: dict):
    current = next((c for c in ctx.call("GET", "/api/contacts") if c["id"] == parse_id(args.get("id"), "contact id")), None)
    if current is None:
        raise ToolError("No contact with that id")
    body = {k: current.get(k) for k in (*_CONTACT_FIELDS, "job_id")}
    body.update(_given(args, *_CONTACT_FIELDS))
    if "job" in args:
        body["job_id"] = parse_job_ref(args["job"]) if args["job"] not in (None, "") else None
    return ctx.call("PUT", f"/api/contacts/{current['id']}", json=body)


@tool("add_interview", "Record an interview for a job (an Applied job moves to Interviewing).",
      _schema({"job": JOB_ARG, "date": {"type": "string", "description": "YYYY-MM-DD or a date and time"},
               "stage": STR, "notes": STR}, ("job",)), write=True)
def add_interview(ctx: ToolContext, args: dict):
    return ctx.call("POST", f"/api/jobs/{parse_job_ref(args.get('job'))}/interviews",
                    json=_given(args, "date", "stage", "notes"))


@tool("update_interview", "Change some fields of an interview (give its job too); fields you leave out stay as they are.",
      _schema({"job": JOB_ARG, "id": {"type": "integer"}, "date": STR, "stage": STR, "notes": STR}, ("job", "id")),
      write=True)
def update_interview(ctx: ToolContext, args: dict):
    detail = ctx.call("GET", f"/api/jobs/{parse_job_ref(args.get('job'))}")
    current = next((i for i in detail.get("interviews", []) if i["id"] == parse_id(args.get("id"), "interview id")), None)
    if current is None:
        raise ToolError("No interview with that id on that job")
    body = {k: current.get(k) for k in ("date", "stage", "notes")}
    body.update(_given(args, "date", "stage", "notes"))
    return ctx.call("PUT", f"/api/interviews/{current['id']}", json=body)
