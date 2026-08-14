"""Inspect or migrate the Full Shelf Model Armor template filter selector."""

import argparse
import json

import google.auth
from google.auth.transport.requests import AuthorizedSession


LATEST_ALIAS = "FILTER_VERSION_ALIAS_LATEST"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="preflight-hackathon")
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--template", default="full-shelf-recall-input-v1")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    name = f"projects/{args.project}/locations/{args.location}/templates/{args.template}"
    url = f"https://modelarmor.{args.location}.rep.googleapis.com/v1/{name}"
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    session = AuthorizedSession(credentials)
    before_response = session.get(url, timeout=30)
    before_response.raise_for_status()
    before = before_response.json()
    before_selector = before.get("templateMetadata", {}).get("filterVersionSelector")

    after = before
    if args.apply and before_selector != {"alias": LATEST_ALIAS}:
        response = session.patch(
            url,
            params={"updateMask": "templateMetadata.filterVersionSelector"},
            json={"templateMetadata": {"filterVersionSelector": {"alias": LATEST_ALIAS}}},
            timeout=30,
        )
        response.raise_for_status()
        after = response.json()

    after_selector = after.get("templateMetadata", {}).get("filterVersionSelector")
    if args.apply and after_selector != {"alias": LATEST_ALIAS}:
        raise RuntimeError("MODEL_ARMOR_LATEST_SELECTOR_NOT_PERSISTED")
    if after.get("filterConfig") != before.get("filterConfig"):
        raise RuntimeError("MODEL_ARMOR_FILTER_CONFIG_CHANGED")

    print(json.dumps({
        "template": name,
        "before_selector": before_selector,
        "after_selector": after_selector,
        "filter_config_preserved": True,
        "before_update_time": before.get("updateTime"),
        "after_update_time": after.get("updateTime"),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
