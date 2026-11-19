"""A strict check of Telegram HTML, so that a message never fails with "can't parse entities".

Telegram accepts only a few tags, and every ``<``, ``>`` and ``&`` that is not part of a tag or an
entity must be escaped. Text a person typed (or a language model wrote) that reaches a message
without ``html.escape`` shows up here as a stray character.
"""

import re

ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre", "a",
    "blockquote", "tg-spoiler", "span", "tg-emoji",
}  # fmt: skip
_TAG = re.compile(r"<(/?)([a-z-]+)((?:\s+[a-z-]+(?:=\"[^\"<>]*\")?)*)\s*>")
_BAD_AMPERSAND = re.compile(r"&(?!(?:lt|gt|amp|quot|#\d+);)")


def html_problems(text: str) -> list[str]:
    """Why Telegram would refuse ``text`` as HTML; an empty list means it is fine."""
    problems: list[str] = []
    stack: list[str] = []
    outside: list[str] = []
    position = 0
    for match in _TAG.finditer(text):
        outside.append(text[position : match.start()])
        position = match.end()
        closing, name = match.group(1) == "/", match.group(2)
        if name not in ALLOWED_TAGS:
            problems.append(f"tag <{name}> is not supported by Telegram")
        elif closing:
            if not stack or stack.pop() != name:
                problems.append(f"</{name}> closes nothing")
        else:
            stack.append(name)
    outside.append(text[position:])
    plain = "".join(outside)
    if "<" in plain or ">" in plain:
        problems.append("an unescaped < or > outside of a tag")
    if _BAD_AMPERSAND.search(plain):
        problems.append("an unescaped &")
    problems += [f"<{name}> is never closed" for name in stack]
    return problems
