"""Fetch a user's public GitHub numbers and boil them down to what the activity card shows."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

API = "https://api.github.com/graphql"

# Pull requests and issues are counted with an is:public search: the user's own
# connections would include private repositories whenever the token can see them.
USER_QUERY = """
query($login: String!, $cursor: String, $prSearch: String!, $issueSearch: String!) {
  prs: search(query: $prSearch, type: ISSUE, first: 1) { issueCount }
  issues: search(query: $issueSearch, type: ISSUE, first: 1) { issueCount }
  user(login: $login) {
    login
    createdAt
    followers { totalCount }
    publicRepos: repositories(ownerAffiliations: OWNER, privacy: PUBLIC) { totalCount }
    repositories(first: 100, after: $cursor, ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

# contributionsCollection spans at most one year, so ask for each year since joining.
YEAR_FIELDS = """
    y{year}: contributionsCollection(from: "{start}", to: "{end}") {{
      totalCommitContributions
      contributionCalendar {{ weeks {{ contributionDays {{ date contributionCount }} }} }}
    }}"""


def _graphql(query: str, variables: dict, token: str) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(API, data=body, headers={
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "profile-card-builder",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            break
        except OSError as error:  # URLError, HTTPError and socket timeouts are all OSErrors
            retryable = not isinstance(error, urllib.error.HTTPError) or error.code >= 500
            if attempt == 2 or not retryable:
                raise
            time.sleep(2 ** attempt * 3)
    if payload.get("errors"):
        messages = "; ".join(e.get("message", "?") for e in payload["errors"])
        raise RuntimeError(f"GitHub GraphQL error: {messages}")
    return payload["data"]


def _parse_time(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def fetch(login: str, token: str, now: Optional[datetime] = None) -> dict:
    """Return the raw numbers in the same shape the --data fixtures use."""
    now = now or datetime.now(timezone.utc)
    variables = {
        "login": login,
        "prSearch": f"author:{login} is:pr is:public",
        "issueSearch": f"author:{login} is:issue is:public",
    }
    user, repos, cursor = None, [], None
    while True:
        data = _graphql(USER_QUERY, {**variables, "cursor": cursor}, token)
        user = data["user"]
        if user is None:
            raise RuntimeError(f"GitHub user {login!r} not found")
        page = user["repositories"]
        repos += [{
            "name": r["name"],
            "stars": r["stargazerCount"],
            "languages": [
                {"name": e["node"]["name"], "color": e["node"]["color"], "size": e["size"]}
                for e in r["languages"]["edges"]
            ],
        } for r in page["nodes"]]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    joined = _parse_time(user["createdAt"])
    ranges = {}
    for year in range(joined.year, now.year + 1):
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = min(datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc), now)
        ranges[year] = (start, end)
    fields = "".join(
        YEAR_FIELDS.format(year=y, start=s.strftime("%Y-%m-%dT%H:%M:%SZ"), end=e.strftime("%Y-%m-%dT%H:%M:%SZ"))
        for y, (s, e) in ranges.items()
    )
    years = _graphql(f"query($login: String!) {{ user(login: $login) {{{fields}\n  }} }}", {"login": login}, token)["user"]

    days, commits = {}, 0
    for year, (start, end) in ranges.items():
        collection = years[f"y{year}"]
        commits += collection["totalCommitContributions"]
        for week in collection["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                # Calendars are padded to whole weeks; keep only days inside this year's window.
                if start.date().isoformat() <= day["date"] <= end.date().isoformat():
                    days[day["date"]] = day["contributionCount"]

    return {
        "login": user["login"],
        "createdAt": user["createdAt"],
        "followers": user["followers"]["totalCount"],
        "pullRequests": data["prs"]["issueCount"],
        "issues": data["issues"]["issueCount"],
        "publicRepos": user["publicRepos"]["totalCount"],
        "commits": commits,
        "repos": repos,
        "days": dict(sorted(days.items())),
    }


@dataclass
class Streak:
    length: int = 0
    start: Optional[date] = None
    end: Optional[date] = None


@dataclass
class Language:
    name: str
    color: str
    share: float


@dataclass
class Summary:
    login: str
    joined: date
    today: date
    contributions: int
    commits: int
    pull_requests: int
    issues: int
    repos: int
    stars: int
    followers: int
    current: Streak
    longest: Streak
    languages: list = field(default_factory=list)


def streaks(days: dict, today: date) -> tuple[Streak, Streak]:
    """(current, longest) runs of days with at least one contribution.

    Today only counts once it has a contribution, so a streak isn't shown as
    broken just because the day isn't over yet.
    """
    active = {date.fromisoformat(d) for d, count in days.items() if count > 0}
    longest, run_start, previous = Streak(), None, None
    for day in sorted(active):
        if previous is None or day - previous != timedelta(days=1):
            run_start = day
        length = (day - run_start).days + 1
        if length > longest.length:
            longest = Streak(length, run_start, day)
        previous = day

    end = today if today in active else today - timedelta(days=1)
    if end not in active:
        return Streak(), longest
    start = end
    while start - timedelta(days=1) in active:
        start -= timedelta(days=1)
    return Streak((end - start).days + 1, start, end), longest


def top_languages(repos: list, exclude_repos: list, hide: list, limit: int = 6) -> list:
    skip_repos = {name.lower() for name in exclude_repos}
    skip_langs = {name.lower() for name in hide}
    sizes, colors = Counter(), {}
    for repo in repos:
        if repo["name"].lower() in skip_repos:
            continue
        for lang in repo["languages"]:
            if lang["name"].lower() in skip_langs:
                continue
            sizes[lang["name"]] += lang["size"]
            # Colours come from the API and go straight into an SVG attribute: accept hex only.
            colors[lang["name"]] = lang["color"] if re.fullmatch(r"#[0-9A-Fa-f]{3,8}", lang["color"] or "") else "#8b949e"
    total = sum(sizes.values())
    if not total:
        return []
    ranked = sizes.most_common()
    if len(ranked) > limit:
        # Keep the legend to `limit` rows: the tail becomes one "Other" slice.
        ranked = ranked[:limit - 1] + [("Other", sum(size for _, size in ranked[limit - 1:]))]
        colors["Other"] = "#8b949e"
    return [Language(name, colors[name], size / total) for name, size in ranked]


def summarize(raw: dict, profile: dict, today: date) -> Summary:
    options = profile.get("languages", {})
    current, longest = streaks(raw["days"], today)
    return Summary(
        login=raw["login"],
        joined=_parse_time(raw["createdAt"]).date(),
        today=today,
        contributions=sum(raw["days"].values()),
        commits=raw["commits"],
        pull_requests=raw["pullRequests"],
        issues=raw["issues"],
        repos=raw["publicRepos"],
        stars=sum(repo["stars"] for repo in raw["repos"]),
        followers=raw["followers"],
        current=current,
        longest=longest,
        languages=top_languages(raw["repos"], options.get("exclude_repos", []), options.get("hide", [])),
    )
