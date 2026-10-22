"""Turn a raw Kobo REST submission into an ordered list of labelled entries."""

import fnmatch
import re
from email.utils import parseaddr

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_EMAIL_KEY_RE = re.compile(r"(^|[/_])e_?mail$", re.IGNORECASE)
_REPEAT = object()


def humanize(name):
    """'contact/phone_number' -> 'Phone number'."""
    text = re.sub(r"[_\-]+", " ", str(name).rsplit("/", 1)[-1]).strip()
    return text[:1].upper() + text[1:] if text else str(name)


def _matches(path, patterns):
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _lookup(mapping, path):
    """Config keys may be a full path ('contact/phone') or just the field name ('phone')."""
    if path in mapping:
        return mapping[path]
    return mapping.get(path.rsplit("/", 1)[-1])


def label_for(path, cfg):
    label = _lookup(cfg["labels"], path)
    return str(label) if label else humanize(path)


def format_value(path, value, cfg):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v not in (None, ""))
    if isinstance(value, dict):
        return ""
    text = str(value).strip()
    choices = _lookup(cfg["value_labels"], path)
    if choices is not None and text:
        # select_one / select_multiple: Kobo sends space-separated choice names.
        return ", ".join(str(choices.get(token, humanize(token))) for token in text.split())
    return text


def find_recipient(submission, EMAIL_FIELD=""):
    """Return the respondent's address from the submission, or None."""
    if EMAIL_FIELD:
        keys = [EMAIL_FIELD]
    else:
        keys = [key for key in submission if _EMAIL_KEY_RE.search(key)]
    for key in keys:
        value = submission.get(key)
        if isinstance(value, str):
            _, address = parseaddr(value.strip())
            if _EMAIL_RE.match(address):
                return address
    return None


def _is_repeat(value):
    return isinstance(value, list) and bool(value) and all(isinstance(v, dict) for v in value)


def build_entries(data, cfg, parent_included=False, top_level=True):
    """Ordered entries of type 'field', 'section' or 'repeat' (repeat items hold nested entries)."""
    entries = []
    current_group = None
    for path, value in data.items():
        if _matches(path, cfg["exclude"]):
            continue
        included = parent_included or _matches(path, cfg["include"])

        if _is_repeat(value):
            items = [build_entries(row, cfg, included, top_level=False) for row in value]
            items = [item for item in items if item]
            if not items:
                continue
            entry = {"type": "repeat", "path": path, "label": label_for(path, cfg), "items": items}
        else:
            if not included:
                continue
            text = format_value(path, value, cfg)
            if not text and cfg["hide_empty"]:
                continue
            entry = {"type": "field", "path": path, "label": label_for(path, cfg), "value": text}

        if top_level and cfg["group_headers"]:
            if entry["type"] == "repeat":
                current_group = _REPEAT  # repeats render their own header
            else:
                group = path.rsplit("/", 1)[0] if "/" in path else None
                if group != current_group:
                    if group is not None:
                        entries.append({"type": "section", "path": group, "label": label_for(group, cfg)})
                    elif current_group is not None and cfg["ungrouped_label"]:
                        entries.append({"type": "section", "path": "", "label": cfg["ungrouped_label"]})
                    current_group = group
        entries.append(entry)
    return entries
