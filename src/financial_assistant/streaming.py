"""Clean the model's streamed text before it reaches the caller."""

import re
from collections.abc import AsyncIterator

# DeepSeek sometimes leaks its internal tool-call markup (e.g. "<｜DSML｜function_calls") into the text.
DSML = re.compile(r"</?｜DSML｜[A-Za-z_]*>?")


def strip_dsml(stream_text: str) -> tuple[str, str]:
    """Remove DSML markup; return (text safe to emit now, tail to hold back in case a tag is split)."""
    text = DSML.sub("", stream_text)
    cut = text.rfind("<")
    if cut != -1 and len(text) - cut < 32 and ">" not in text[cut:] and "\n" not in text[cut:]:
        return text[:cut], text[cut:]
    return text, ""


async def text_chunks(events: AsyncIterator[dict]) -> AsyncIterator[str]:
    """Yield the text chunks of a Strands event stream with DSML markup removed."""
    pending = ""
    async for event in events:
        if "data" in event and isinstance(event["data"], str):
            out, pending = strip_dsml(pending + event["data"])
            if out:
                yield out
    if pending:
        yield DSML.sub("", pending)
