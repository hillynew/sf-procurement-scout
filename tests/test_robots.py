"""robots.txt parsing, against the RFC rather than the 1996 draft.

The bug this module was written for: `urllib.robotparser` ends a record at a
blank line, so a file that puts a comment banner between `User-agent: *` and
its rules reads as a group with *no rules* — and every Disallow in it is
silently dropped. A crawler that believes it honors robots then fetches
everything, and the log says "present", not "unreadable".

Found on BidNet Direct. The file below is its shape, trimmed.
"""

from __future__ import annotations

from urllib.robotparser import RobotFileParser

import pytest

from src.robots import parse, product_token

US = "sf-procurement-scout/1.0 (+https://example.org; Florida procurement)"

BIDNET = """\
# ==========================================================
# METS Procurement Platform - robots.txt
# ==========================================================

# Default policy: all well-behaved crawlers
User-agent: *

# --- Authenticated areas (blocked) ---
Disallow: /private/
Disallow: /favorites

# --- Public pages that are NOT indexable ---
Disallow: /public/registration/
Disallow: /login

# --- Query-string traps ---
Disallow: /*?*sort=
Disallow: /*?*page=

# --- Crawl rate ---
Crawl-delay: 5

# ==========================================================
# Aggressive crawlers / AI scrapers - block entirely
# ==========================================================

User-agent: GPTBot
Disallow: /

User-agent: ClaudeBot
Disallow: /
"""


# -- the bug ---------------------------------------------------------------


def test_a_blank_line_after_the_agent_does_not_discard_its_rules():
    robots = parse(BIDNET)

    assert not robots.allows(US, "https://x.com/private/thing")
    assert not robots.allows(US, "https://x.com/login")
    assert robots.allows(US, "https://x.com/florida/miamidadecollege")


def test_the_standard_library_gets_this_file_wrong():
    """Kept as a test because it is the reason this module exists, and because
    a future "why not just use robotparser?" deserves an answer that runs."""
    stdlib = RobotFileParser()
    stdlib.parse(BIDNET.splitlines())

    assert stdlib.can_fetch(US, "https://x.com/private/thing") is True
    assert parse(BIDNET).allows(US, "https://x.com/private/thing") is False


def test_the_failure_was_silent_rather_than_loud():
    """The same file's later groups parse correctly under the stdlib, so the
    log said "robots: present" while the policy had vanished. Nothing about
    the outcome looked like an error."""
    stdlib = RobotFileParser()
    stdlib.parse(BIDNET.splitlines())

    assert stdlib.can_fetch("ClaudeBot", "https://x.com/anything") is False
    assert stdlib.can_fetch(US, "https://x.com/private/x") is True


# -- who a group applies to ------------------------------------------------


def test_a_group_naming_another_crawler_says_nothing_about_us():
    """`Disallow: /` for ClaudeBot is not a rule about this crawler, which is
    a different product with a different name and its own contact address."""
    robots = parse(BIDNET)

    assert robots.allows(US, "https://x.com/florida/anything")
    assert not robots.allows("ClaudeBot/1.0", "https://x.com/florida/anything")


def test_our_own_name_would_be_obeyed_if_a_site_wrote_it():
    robots = parse(
        "User-agent: *\nDisallow:\n\n"
        "User-agent: sf-procurement-scout\nDisallow: /bids/\n"
    )

    assert not robots.allows(US, "https://x.com/bids/1")


def test_a_named_group_beats_the_wildcard():
    robots = parse(
        "User-agent: *\nDisallow: /\n\n"
        "User-agent: sf-procurement-scout\nDisallow: /admin/\n"
    )

    assert robots.allows(US, "https://x.com/bids")
    assert not robots.allows(US, "https://x.com/admin/x")


def test_the_version_and_contact_are_not_part_of_the_name():
    assert product_token(US) == "sf-procurement-scout"
    assert product_token("ClaudeBot") == "claudebot"


def test_matching_ignores_case():
    robots = parse("User-agent: SF-Procurement-Scout\nDisallow: /x\n")

    assert not robots.allows(US, "https://x.com/x")


def test_two_groups_for_one_crawler_are_one_group():
    robots = parse(
        "User-agent: sf-procurement-scout\nDisallow: /a\n\n"
        "User-agent: sf-procurement-scout\nDisallow: /b\n"
    )

    assert not robots.allows(US, "https://x.com/a")
    assert not robots.allows(US, "https://x.com/b")


def test_agents_sharing_one_group_share_its_rules():
    robots = parse("User-agent: GPTBot\nUser-agent: CCBot\nDisallow: /\n")

    assert not robots.allows("CCBot", "https://x.com/a")
    assert not robots.allows("GPTBot", "https://x.com/a")
    assert robots.allows(US, "https://x.com/a")


# -- which rule wins -------------------------------------------------------


def test_the_longest_matching_rule_decides():
    robots = parse("User-agent: *\nDisallow: /bids/\nAllow: /bids/public/\n")

    assert not robots.allows(US, "https://x.com/bids/private")
    assert robots.allows(US, "https://x.com/bids/public/1")


def test_allow_wins_a_tie():
    robots = parse("User-agent: *\nDisallow: /x\nAllow: /x\n")

    assert robots.allows(US, "https://x.com/x")


def test_an_empty_disallow_is_permission_not_a_prohibition():
    """"Disallow:" with nothing after it is how a file says "no restrictions",
    and reading it as a zero-length match against everything would lock out the
    whole site."""
    robots = parse("User-agent: *\nDisallow:\n")

    assert robots.allows(US, "https://x.com/anything")


def test_a_file_with_no_rules_for_anyone_allows_everything():
    assert parse("User-agent: *\n").allows(US, "https://x.com/a")
    assert parse("").allows(US, "https://x.com/a")


def test_rules_written_before_any_agent_belong_to_nobody():
    robots = parse("Disallow: /orphan\n\nUser-agent: *\nDisallow: /x\n")

    assert robots.allows(US, "https://x.com/orphan")
    assert not robots.allows(US, "https://x.com/x")


# -- patterns --------------------------------------------------------------


def test_a_star_matches_any_run_of_characters():
    robots = parse("User-agent: *\nDisallow: /a/*/secret\n")

    assert not robots.allows(US, "https://x.com/a/anything/secret")
    assert robots.allows(US, "https://x.com/a/secret")


def test_a_dollar_anchors_the_end():
    robots = parse("User-agent: *\nDisallow: /*.pdf$\n")

    assert not robots.allows(US, "https://x.com/docs/bid.pdf")
    assert robots.allows(US, "https://x.com/docs/bid.pdf.html")


def test_the_query_string_is_part_of_what_a_rule_matches():
    """BidNet blocks paging with `Disallow: /*?*page=`. Matching the path
    alone would read that as no rule at all."""
    robots = parse(BIDNET)

    assert robots.allows(US, "https://x.com/florida/solicitations/open-bids")
    assert not robots.allows(US, "https://x.com/florida/solicitations/open-bids?page=2")
    assert not robots.allows(US, "https://x.com/florida/x?foo=1&sort=date")


def test_a_pattern_is_a_prefix_not_a_substring():
    robots = parse("User-agent: *\nDisallow: /admin\n")

    assert not robots.allows(US, "https://x.com/admin/panel")
    assert robots.allows(US, "https://x.com/public/admin")


def test_regex_characters_in_a_path_are_literal():
    robots = parse("User-agent: *\nDisallow: /a+b(c)\n")

    assert not robots.allows(US, "https://x.com/a+b(c)")
    assert robots.allows(US, "https://x.com/aaab")


# -- crawl delay -----------------------------------------------------------


def test_the_crawl_delay_comes_from_the_group_that_applies():
    assert parse(BIDNET).crawl_delay(US) == 5.0
    assert parse(BIDNET).crawl_delay("ClaudeBot") is None


def test_an_unreadable_crawl_delay_is_no_delay_rather_than_a_crash():
    assert parse("User-agent: *\nCrawl-delay: soon\n").crawl_delay(US) is None


# -- robustness ------------------------------------------------------------


@pytest.mark.parametrize("body", [
    "\x00\x01 garbage",
    "User-agent\nDisallow\n",
    "user-AGENT:*\nDISALLOW:/x\n",
    ":\n:\n",
])
def test_a_malformed_file_never_raises(body):
    parse(body).allows(US, "https://x.com/x")


def test_the_case_of_field_names_does_not_matter():
    robots = parse("user-AGENT: *\nDISALLOW: /x\n")

    assert not robots.allows(US, "https://x.com/x")


def test_a_comment_at_the_end_of_a_rule_is_not_part_of_the_path():
    robots = parse("User-agent: *\nDisallow: /x  # no crawling here\n")

    assert not robots.allows(US, "https://x.com/x")
    assert robots.allows(US, "https://x.com/y")
