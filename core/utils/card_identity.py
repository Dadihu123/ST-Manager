"""Stable identities for role cards."""

import uuid


CARD_UID_FIELD = 'card_uid'


def new_card_uid():
    return str(uuid.uuid4())


def normalize_card_uid(value):
    if not value:
        return ''
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, TypeError, AttributeError):
        return ''
