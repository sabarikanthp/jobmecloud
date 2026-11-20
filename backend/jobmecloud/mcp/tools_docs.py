"""Documents written in a Claude chat: attach them to a job, and read a job's documents back into a chat."""

from jobmecloud.applydocs import attach
from jobmecloud.jobs.actor import acting_as
from jobmecloud.mcp.registry import ToolContext, ToolError, tool
from jobmecloud.mcp.tools_read import JOB_ARG, parse_job_ref

_DOC = {"type": "object", "description": "Either text (format md or txt) or base64 (format docx or pdf, up to about 3 MB).",
        "properties": {"format": {"type": "string", "enum": ["md", "txt", "docx", "pdf"]},
                       "text": {"type": "string"}, "base64": {"type": "string"}},
        "required": ["format"]}


@tool("attach_documents", "Save a resume and/or cover letter you wrote in this chat onto a job, so they appear on "
                          "its page in JobMe. Earlier files are archived, not overwritten. Cover letters may be md, docx or pdf.",
      {"type": "object", "properties": {"job": JOB_ARG, "resume": _DOC, "cover_letter": _DOC}, "required": ["job"]},
      write=True, wrap=False)  # the result is only the file names JobMe chose
def attach_documents(ctx: ToolContext, args: dict):
    job_id = parse_job_ref(args.get("job"))
    with acting_as(f"claude:{ctx.key.name}"):
        try:
            return attach.attach_documents(
                ctx.app.state.engine, ctx.app.state.data_dir, job_id, resume=args.get("resume"),
                cover_letter=args.get("cover_letter"), source=ctx.key.name, now=ctx.now, today=ctx.today)
        except attach.AttachError as e:
            raise ToolError(str(e)) from None


@tool("get_job_documents", "The resume and cover letter attached to a job, as text.",
      {"type": "object", "properties": {"job": JOB_ARG}, "required": ["job"]})
def get_job_documents(ctx: ToolContext, args: dict):
    try:
        found = attach.read_documents(ctx.app.state.engine, ctx.app.state.data_dir, parse_job_ref(args.get("job")))
    except attach.AttachError as e:
        raise ToolError(str(e)) from None
    if not found:
        raise ToolError("No documents are attached to this job yet.")
    out: dict = {"resume": None, "cover_letter": None}
    for kind, (name, text) in found.items():
        out[kind], out[f"{kind}_file"] = text, name  # wrapped as untrusted with every other result
    return out
