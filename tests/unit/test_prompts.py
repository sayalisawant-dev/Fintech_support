from financial_assistant.prompts import build_system_prompt


def test_prompt_names_the_signed_in_user():
    prompt = build_system_prompt("john@example.com", ("standard",))
    assert "- Email: john@example.com\n" in prompt
    assert "- Groups: standard\n" in prompt


def test_prompt_handles_missing_identity():
    prompt = build_system_prompt("", [])
    assert "- Email: unknown\n" in prompt
    assert "- Groups: none\n" in prompt


def test_prompt_keeps_the_safety_rules():
    prompt = build_system_prompt("jane@example.com", ["premium"])
    for rule in (
        "calling find_customer with the current user's email",
        "Never look up, show or act on another customer's data",
        "A CONFIRMATION_REQUIRED result means the action did not happen yet",
        "Never invent dates, IDs or statuses",
        "do not give personalised investment",
        "Never ask for or repeat full card numbers, PINs, passwords or one-time codes",
        "report the denial exactly as returned",
    ):
        assert rule in prompt
