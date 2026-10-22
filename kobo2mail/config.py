"""Load config.json and resolve the settings for one submission's form."""

import copy
import json
from pathlib import Path

PROVIDERS = ("gmail", "smtp")

DEFAULT_FORM = {
    "email_field": "",
    "subject": "Your submission",
    "template": "templates/default.html",
    "title": "Thank you for your submission",
    "intro": "Here is a copy of the answers you submitted.",
    "footer": "This is an automatic message. Please do not reply unless something looks wrong.",
    "from_name": "",
    "brand_color": "#2b6cb0",
    "logo_url": "",
    "include": ["*"],
    "exclude": ["_*", "meta/*", "formhub/*", "start", "end", "today", "deviceid"],
    "labels": {},
    "value_labels": {},
    "hide_empty": True,
    "group_headers": True,
    "ungrouped_label": "Other answers",
    "layout": "",  # "stacked" | "columns"; empty = template's default
    "button_label": "",
    "button_url": "",
    "vars": {},
    "pdf": False,  # attach a PDF copy (needs Chrome, Chromium or Edge)
    "pdf_template": "templates/pdf.html",
    "pdf_title": "Copy of your submission",
    "pdf_filename": "submission-$submission_id.pdf",
}

# Keys whose dict values are merged (per-form entries extend the default ones)
# instead of being replaced wholesale.
_MERGED_DICTS = ("labels", "value_labels", "vars")


class ConfigError(ValueError):
    pass


def load_config(path):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from None

    provider = data.get("provider", "gmail")
    if provider not in PROVIDERS:
        raise ConfigError(f"provider must be one of {PROVIDERS}, got {provider!r}")
    forms = data.get("forms", {})
    if not isinstance(forms, dict):
        raise ConfigError("'forms' must be an object keyed by asset UID or 'default'")
    for name, form in forms.items():
        if not isinstance(form, dict):
            raise ConfigError(f"forms.{name} must be an object")
        for key in ("include", "exclude"):
            if key in form and not isinstance(form[key], list):
                raise ConfigError(f"forms.{name}.{key} must be a list of patterns")
        if "pdf" in form and not isinstance(form["pdf"], bool):
            raise ConfigError(f"forms.{name}.pdf must be true or false")
        for key in _MERGED_DICTS:
            if key in form and not isinstance(form[key], dict):
                raise ConfigError(f"forms.{name}.{key} must be an object")

    return {"provider": provider, "forms": forms, "base_dir": path.parent}


def _merge(target, overrides):
    for key, value in overrides.items():
        if key in _MERGED_DICTS:
            target[key] = {**target.get(key, {}), **value}
        else:
            target[key] = copy.deepcopy(value)


def form_config(config, submission):
    """Settings for this submission: built-in defaults < forms.default < forms[<asset uid>]."""
    resolved = copy.deepcopy(DEFAULT_FORM)
    forms = config["forms"]
    _merge(resolved, forms.get("default", {}))
    asset_uid = submission.get("_xform_id_string")
    if asset_uid and asset_uid in forms:
        _merge(resolved, forms[asset_uid])
    resolved["template_path"] = Path(config["base_dir"]) / resolved["template"]
    resolved["pdf_template_path"] = Path(config["base_dir"]) / resolved["pdf_template"]
    return resolved
