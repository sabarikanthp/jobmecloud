"""Tools that only read: nothing here changes anything in JobMe."""

import re

from jobmecloud.mcp.registry import ToolContext, ToolError, tool

_REF = re.compile(r"(?:job\s*#?\s*|#)(\d+)", re.IGNORECASE)
_NUMBER = re.compile(r"\s*#?(\d+)\s*")
_ID_REF = re.compile(r"JobMe (?:contact|follow-up|interview) (\d+)", re.IGNORECASE)


def parse_id(value: object, what: str = "id") -> int:
    """A contact, follow-up or interview id: a positive number, or the 'JobMe follow-up 7: ...' text copied from
    the app. Anything else is refused, so an argument can never smuggle extra path into a request URL."""
    found = 0
    if isinstance(value, int) and not isinstance(value, bool):
        found = value
    elif isinstance(value, str):
        match = _NUMBER.fullmatch(value) or _ID_REF.match(value.strip())
        found = int(match.group(1)) if match else 0
    if found < 1:
        raise ToolError(f"Give the {what} as a number.")
    return found

JOB_ARG = {"description": "A job id, or the text copied with Copy for Claude, e.g. 'JobMe job 123: Acme – Staff Engineer'.",
           "type": ["integer", "string"]}


def parse_job_ref(value: int | str | None) -> int:
    """The job id in a number or in pasted reference text."""
    if isinstance(value, bool):
        raise ToolError("Give a job id or the 'JobMe job <id>' reference.")
    if isinstance(value, int):
        found = value
    elif isinstance(value, str):
        match = _REF.search(value) or _NUMBER.fullmatch(value)
        found = int(match.group(1)) if match else 0
    else:
        found = 0
    if found < 1:
        raise ToolError("Give a job id or the 'JobMe job <id>' reference.")
    return found


def _optional_job(args: dict) -> int | None:
    return parse_job_ref(args["job"]) if args.get("job") not in (None, "") else None


@tool("list_jobs", "List jobs, newest first. Filter by status, text in employer or title, or minimum fit score.",
      {"type": "object", "properties": {
          "status": {"type": "string", "description": "e.g. New, Ready, Applied, Interviewing, Offer, Skipped"},
          "query": {"type": "string"}, "min_score": {"type": "integer"},
          "limit": {"type": "integer", "description": "1 to 50, default 20"}}})
def list_jobs(ctx: ToolContext, args: dict):
    params: dict = {"limit": max(1, min(int(args.get("limit") or 20), 50))}
    if args.get("status"):
        params["status"] = [args["status"]]
    if args.get("query"):
        params["q"] = args["query"]
    if args.get("min_score") is not None:
        params["min_score"] = args["min_score"]
    return ctx.call("GET", "/api/jobs", params=params)


@tool("get_job", "Everything about one job: the posting, fit score and reasons, gaps, status, notes, contacts, "
                 "follow-ups, interviews and history.",
      {"type": "object", "properties": {"job": JOB_ARG}, "required": ["job"]})
def get_job(ctx: ToolContext, args: dict):
    return ctx.call("GET", f"/api/jobs/{parse_job_ref(args.get('job'))}")


@tool("get_resume_context", "The owner's profile, search preferences, uploaded resumes and the text of a resume "
                            "(the default one unless resume_id is given).",
      {"type": "object", "properties": {"resume_id": {"type": "string"}}}, wrap=False)
def get_resume_context(ctx: ToolContext, args: dict):
    resumes = ctx.call("GET", "/api/resumes")
    resume_id = args.get("resume_id") or resumes.get("default_id")
    if resume_id and resume_id not in [r["id"] for r in resumes.get("resumes", [])]:
        raise ToolError("No resume with that id")
    reading = ctx.call("GET", f"/api/resumes/{resume_id}/reading") if resume_id else ctx.call("GET", "/api/profile/resume")
    return {"user": ctx.call("GET", "/api/profile/user"), "search": ctx.call("GET", "/api/profile/search"),
            "resumes": resumes, "reading": reading}


@tool("get_dashboard", "The overview numbers shown on the JobMe dashboard.", {"type": "object"}, wrap=False)
def get_dashboard(ctx: ToolContext, args: dict):
    return ctx.call("GET", "/api/dashboard")


@tool("list_followups", "List follow-ups. bucket is one of overdue, today, upcoming, done.",
      {"type": "object", "properties": {"bucket": {"type": "string"}, "job": JOB_ARG, "contact_id": {"type": "integer"}}})
def list_followups(ctx: ToolContext, args: dict):
    contact = parse_id(args["contact_id"], "contact id") if args.get("contact_id") not in (None, "") else None
    params = {k: v for k, v in {"bucket": args.get("bucket"), "job_id": _optional_job(args),
                                "contact_id": contact}.items() if v is not None}
    return ctx.call("GET", "/api/followups", params=params)


@tool("list_contacts", "List contacts, optionally for one job or matching some text.",
      {"type": "object", "properties": {"job": JOB_ARG, "query": {"type": "string"}}})
def list_contacts(ctx: ToolContext, args: dict):
    params = {k: v for k, v in {"job_id": _optional_job(args), "q": args.get("query")}.items() if v is not None}
    return ctx.call("GET", "/api/contacts", params=params)
