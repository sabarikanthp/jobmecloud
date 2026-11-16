"""The candidate source for a run started by an email: read the stored message, ask which roles it recommends."""

from jobmecloud.agents.jobscout.pipeline import CandidateSource, RunSetupError
from jobmecloud.inbound.extract import MAX_EMAIL_CANDIDATES, extract_recommended
from jobmecloud.inbound.parse import parse_email
from jobmecloud.llm.structured import StructuredOutputError

NOT_CONFIGURED_COPY = "Email reports are not set up: the mail bucket is not configured."
UNREADABLE_COPY = "The emailed report could not be read from the mail bucket."
UNDERSTOOD_COPY = "The AI could not make sense of the emailed report. You can replay it later."


class EmailReadError(RunSetupError):
    """The emailed report could not be turned into candidates; the message is shown as it is."""


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def build_email_source(s3, bucket: str | None, key: str) -> CandidateSource:
    def source(ctx) -> list:
        if not bucket:
            raise EmailReadError(NOT_CONFIGURED_COPY)
        try:
            raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception as e:
            raise EmailReadError(UNREADABLE_COPY) from e
        provider, model = ctx.models["extract"]
        try:
            result = extract_recommended(provider, model, parse_email(raw), ctx.costs)
        except StructuredOutputError as e:
            raise EmailReadError(UNDERSTOOD_COPY) from e
        if result.dropped_no_link:
            n = result.dropped_no_link
            ctx.errors.append(f"{n} recommended {_plural(n, 'role', 'roles')} had no usable link and "
                              f"{_plural(n, 'was', 'were')} skipped.")
        if result.dropped_over_cap:
            ctx.errors.append(f"{result.dropped_over_cap} more recommended roles were left out "
                              f"(the limit is {MAX_EMAIL_CANDIDATES} per report).")
        return result.candidates

    return source
