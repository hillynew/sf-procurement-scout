"""robots.txt, parsed the way the standard says rather than the way 1996 did.

`urllib.robotparser` implements the original 1996 draft, in which a **blank
line ends a record**. RFC 9309 (2022) says a group starts at its `user-agent`
lines and runs until the next `user-agent` line; blank lines and comments carry
no meaning at all. Most robots.txt files in the wild are written to the RFC —
with a blank line and a comment banner between the agent and its rules, because
that is how people format files they expect other people to read.

The stdlib reads such a file as *a group with no rules*, which means every
Disallow in it is silently dropped, and the crawler concludes it may fetch
anything. Found on BidNet Direct, whose file opens:

    User-agent: *

    # --- Authenticated areas (blocked) ---
    Disallow: /private/
    Disallow: /login

Under the stdlib every one of those lines vanishes. Worse, the *same file's*
later groups — `User-agent: ClaudeBot` / `Disallow: /`, written without the
blank line — parse correctly. So the failure is not "robots was unreadable",
which the log would have shown; it is a file that reads as permission.

That is the precise shape of mistake `netpolicy` exists to prevent, so the
parsing moved here where it can be tested against real files.

What this implements, from RFC 9309:

* **Grouping** (§2.2.1). Consecutive `user-agent` lines share one group; the
  group ends at the first `user-agent` line that follows a rule. Groups naming
  the same product token are merged.
* **Product-token matching** (§2.2.1). Case-insensitive, against the token
  alone — `sf-procurement-scout` out of `sf-procurement-scout/1.0 (+…)`. The
  most specific match wins, and `*` is used only when nothing else matches.
* **Longest-match precedence** (§2.2.2). The rule with the longest matching
  pattern decides; on a tie, `allow` wins. An empty `Disallow:` allows
  everything, which is how a file says "no restrictions".
* **Wildcards** (§2.2.3). `*` matches any run of characters, `$` anchors the
  end of the path. Matching is against path *and* query, so a rule like
  `Disallow: /*?*page=` means what its author meant.

`Crawl-delay` is not in the RFC, but it is widely written and this crawler
honors it, so it is read from the matched group.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

#: (allow?, the pattern as written). Order is kept only for readability; the
#: winner is chosen by length, per §2.2.2.
Rule = Tuple[bool, str]


@dataclass
class Group:
    agents: List[str] = field(default_factory=list)
    rules: List[Rule] = field(default_factory=list)
    crawl_delay: Optional[float] = None


def product_token(user_agent: str) -> str:
    """The part of a User-Agent that robots.txt names.

    `sf-procurement-scout/1.0 (+https://…)` is written in robots.txt as
    `sf-procurement-scout`, so the version and the contact are cut off before
    matching.
    """
    return (user_agent or "").split("/")[0].strip().lower()


def _to_regex(pattern: str) -> re.Pattern:
    """A robots path pattern as a regex: `*` is any run, `$` ends the path."""
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    out = "".join("[^\n]*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile("^" + out + ("$" if anchored else ""))


@dataclass
class Robots:
    """One host's robots.txt, ready to answer for a given crawler."""

    groups: List[Group] = field(default_factory=list)

    def _group_for(self, user_agent: str) -> Optional[Group]:
        """The group that governs this crawler, most specific first.

        A named token beats `*`, and nothing else is a partial match: a group
        for `ClaudeBot` says nothing about a crawler called something else,
        even though both are operated by software.
        """
        token = product_token(user_agent)
        named = [g for g in self.groups if token and token in g.agents]
        if named:
            return _merge(named)
        wild = [g for g in self.groups if "*" in g.agents]
        return _merge(wild) if wild else None

    def allows(self, user_agent: str, url: str) -> bool:
        """May this crawler fetch this URL?"""
        group = self._group_for(user_agent)
        if group is None or not group.rules:
            return True

        path = _path_of(url)
        best: Optional[Tuple[int, bool]] = None
        for allow, pattern in group.rules:
            if not pattern:
                # `Disallow:` with nothing after it is "no restrictions", and
                # must not win as a zero-length match against everything.
                continue
            if _to_regex(pattern).match(path):
                length = len(pattern.rstrip("$"))
                # Longest wins; on a tie, allow wins (§2.2.2).
                if best is None or length > best[0] or (length == best[0] and allow):
                    best = (length, allow)
        return best[1] if best else True

    def crawl_delay(self, user_agent: str) -> Optional[float]:
        group = self._group_for(user_agent)
        return group.crawl_delay if group else None


def _path_of(url: str) -> str:
    """The part a rule matches against: path plus query, never the host."""
    if url.startswith(("http://", "https://")):
        split = urlsplit(url)
        path = split.path or "/"
        return f"{path}?{split.query}" if split.query else path
    return url or "/"


def _merge(groups: List[Group]) -> Group:
    """Groups naming the same token are one group (§2.2.1)."""
    out = Group(agents=list(groups[0].agents))
    for g in groups:
        out.rules.extend(g.rules)
        if out.crawl_delay is None:
            out.crawl_delay = g.crawl_delay
    return out


def parse(text: str) -> Robots:
    """Read a robots.txt body. Never raises — an unreadable line is skipped."""
    robots = Robots()
    current: Optional[Group] = None
    # A group ends at the first `user-agent` line *after* a rule, not at the
    # first blank line. This flag is the whole difference from the stdlib.
    seen_rule = False

    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        field_name = field_name.strip().lower()
        value = value.strip()

        if field_name == "user-agent":
            if current is None or seen_rule:
                current = Group()
                robots.groups.append(current)
                seen_rule = False
            current.agents.append(value.lower())
            continue

        if current is None:
            # Rules before any user-agent line belong to nobody. Dropping them
            # is what every parser does, and inventing an owner would be worse.
            continue

        if field_name in ("allow", "disallow"):
            current.rules.append((field_name == "allow", value))
            seen_rule = True
        elif field_name == "crawl-delay":
            try:
                current.crawl_delay = float(value)
            except ValueError:
                pass
            seen_rule = True

    return robots
