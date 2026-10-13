import asyncio

from financial_assistant.streaming import strip_dsml, text_chunks


async def _events(*items):
    for item in items:
        yield item


def collect(*events) -> list[str]:
    async def run():
        return [chunk async for chunk in text_chunks(_events(*events))]

    return asyncio.run(run())


def test_strip_dsml_removes_complete_tags():
    assert strip_dsml("Hello <｜DSML｜function_calls>world") == ("Hello world", "")


def test_strip_dsml_holds_back_a_possible_partial_tag():
    assert strip_dsml("Your balance is $5 <｜DS") == ("Your balance is $5 ", "<｜DS")


def test_strip_dsml_does_not_hold_back_ordinary_text():
    assert strip_dsml("a < b\nc") == ("a < b\nc", "")


def test_text_chunks_removes_a_tag_split_across_events():
    chunks = collect({"data": "Hi <｜DS"}, {"data": "ML｜invoke>there"}, {"event": "metadata"}, {"data": " done"})
    assert "".join(chunks) == "Hi there done"


def test_text_chunks_flushes_held_back_text_at_the_end():
    assert "".join(collect({"data": "x < y"})) == "x < y"
