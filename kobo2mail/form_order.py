"""Order a submission's fields like the Kobo form, using the form definition from the Kobo API."""

import json
import os
import sys
import urllib.error
import urllib.request

_BEGIN = {"begin_group", "begin group", "begin_repeat", "begin repeat"}
_END = {"end_group", "end group", "end_repeat", "end repeat"}
_REPEAT = {"begin_repeat", "begin repeat"}


def form_paths(survey):
    """Submission keys in form order, e.g. 'deployment_overview/thematic_focus_primary'."""
    paths, stack = [], []  # stack of (group name, is_repeat)
    for row in survey:
        kind = str(row.get("type", "")).strip()
        if kind in _END:
            if stack:
                stack.pop()
            continue
        name = row.get("name") or row.get("$autoname")
        if not name:
            continue
        # Fields inside repeat groups live in nested rows, not in top-level keys.
        if not any(is_repeat for _, is_repeat in stack):
            paths.append("/".join([n for n, _ in stack] + [name]))
        if kind in _BEGIN:
            stack.append((name, kind in _REPEAT))
    return paths


def fetch_survey(server, uid, token, timeout=20):
    url = f"{server.rstrip('/')}/api/v2/assets/{uid}/?format=json"
    request = urllib.request.Request(
        url, headers={"Authorization": f"Token {token}", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)["content"]["survey"]


def apply_form_order(submission, env=None):
    """Return the submission with keys in form order; unchanged if the form can't be fetched."""
    env = os.environ if env is None else env
    token = env.get("KOBO_API_TOKEN", "").strip()
    server = env.get("KOBO_SERVER", "").strip() or "https://kf.kobotoolbox.org"
    uid = env.get("KOBO_ASSET_UID", "").strip() or str(submission.get("_xform_id_string", ""))
    if not (token and uid):
        return submission
    try:
        survey = fetch_survey(server, uid, token)
    except (OSError, ValueError, KeyError) as exc:  # URLError and HTTPError are OSErrors
        # Class name only: never print the URL or token.
        print(f"kobo2mail: form order unavailable ({type(exc).__name__}); keeping payload order", file=sys.stderr)
        return submission
    rank = {path: index for index, path in enumerate(form_paths(survey))}
    # sorted() is stable, so keys the form doesn't know (_id, meta/...) keep their order, at the end.
    return dict(sorted(submission.items(), key=lambda item: rank.get(item[0], len(rank))))