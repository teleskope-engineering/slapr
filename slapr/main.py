# Unless explicitly stated otherwise all files in this repository are licensed
# under the Apache License Version 2.0.
# This product includes software developed at Datadog (https://www.datadoghq.com/)
# Copyright 2023-present Datadog, Inc.

from typing import List

from . import emojis
from .config import Config
from .github import ALLOWED_BOT_REVIEWERS, PullRequest, Review


def main(config: Config) -> None:
    slack = config.slack_client
    github = config.github_client

    event = github.read_event()

    is_fork: bool = event["pull_request"]["head"]["repo"]["fork"]

    if is_fork:
        print("Fork PRs are not supported.")
        return

    review = event.get("review") or {}
    review_user = review.get("user", {})
    if review_user.get("type") == "Bot" and review_user.get("login") not in ALLOWED_BOT_REVIEWERS:
        print(f"Skipping bot review by {review_user.get('login')}")
        return

    pr_number: int = event["pull_request"]["number"]
    pr = github.get_pr(pr_number=pr_number)
    reviews = github.get_pr_reviews(pr_number=pr_number)

    pr_url: str = event["pull_request"]["html_url"]
    print(f"Event PR: {pr_url}")
    print(f"Is merged: {pr.merged}")
    print(f"Mergeable state: {pr.mergeable_state}")

    found = False
    for channel_id in config.slack_channel_ids:
        timestamp = slack.find_timestamp_of_review_requested_message(pr_url=pr_url, channel_id=channel_id)
        print(f"Slack message timestamp in {channel_id}: {timestamp}")
        if timestamp is None:
            continue
        found = True

        channel_reviews = reviews
        if channel_id in config.human_only_channel_ids:
            channel_reviews = [review for review in reviews if not review.is_bot]
        _update_emojis(config, pr, channel_reviews, channel_id, timestamp)

    if not found:
        print(f"No message found requesting review for PR: {pr_url}")


def _update_emojis(config: Config, pr: PullRequest, reviews: List[Review], channel_id: str, timestamp: str) -> None:
    slack = config.slack_client

    existing_emojis = slack.get_emojis_for_user(
        timestamp=timestamp, channel_id=channel_id, user_id=config.slapr_bot_user_id
    )
    print(f"Existing emojis: {', '.join(existing_emojis)}")

    review_emoji = emojis.get_for_reviews(
        reviews,
        emoji_commented=config.emoji_commented,
        emoji_needs_change=config.emoji_needs_change,
        emoji_approved=config.emoji_approved,
        number_of_approvals_required=config.number_of_approvals_required,
    )

    # Review emoji. Human-only channels get no review_started until a human has actually reviewed.
    new_emojis = set()
    if reviews or channel_id not in config.human_only_channel_ids:
        new_emojis.add(config.emoji_review_started)
    if review_emoji:
        new_emojis.add(review_emoji)

    # PR emoji
    if pr.merged:
        new_emojis.add(config.emoji_merged)
    elif pr.state == "closed":
        new_emojis.add(config.emoji_closed)

    # Add emojis
    emojis_to_add, emojis_to_remove = emojis.diff(new_emojis=new_emojis, existing_emojis=existing_emojis)

    sorted_emojis_to_add = sorted(emojis_to_add, key=config.emojis_by_review_step)

    print(f"Emojis to add (ordered) : {', '.join(sorted_emojis_to_add)}")
    print(f"Emojis to remove        : {', '.join(emojis_to_remove)}")

    for emoji in sorted_emojis_to_add:
        slack.add_reaction(timestamp=timestamp, emoji=emoji, channel_id=channel_id)

    for emoji in emojis_to_remove:
        slack.remove_reaction(timestamp=timestamp, emoji=emoji, channel_id=channel_id)
