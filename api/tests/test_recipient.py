import pytest

from api.myemailer.recipient import resolve_recipient, validated_recipient


def test_pinned_recipient_wins_over_named_and_default_inbox():
    assert (
        resolve_recipient(
            pinned="pinned@example.com",
            named="named@example.com",
            default="default@example.com",
        )
        == "pinned@example.com"
    )


def test_named_recipient_used_when_nothing_is_pinned():
    assert (
        resolve_recipient(
            pinned=None,
            named="named@example.com",
            default="default@example.com",
        )
        == "named@example.com"
    )


def test_default_inbox_used_when_nothing_is_pinned_or_named():
    assert (
        resolve_recipient(
            pinned=None,
            named=None,
            default="default@example.com",
        )
        == "default@example.com"
    )


def test_resolve_fails_when_every_recipient_is_missing():
    with pytest.raises(ValueError, match="No recipient email configured"):
        resolve_recipient(pinned=None, named=None, default=None)


def test_resolve_fails_when_chosen_recipient_is_invalid():
    with pytest.raises(ValueError, match="Invalid recipient email"):
        resolve_recipient(
            pinned="not-an-email",
            named="named@example.com",
            default="default@example.com",
        )


def test_resolve_fails_when_named_recipient_is_invalid():
    with pytest.raises(ValueError, match="Invalid recipient email"):
        resolve_recipient(
            pinned=None,
            named="not-an-email",
            default="default@example.com",
        )


def test_resolve_fails_when_default_inbox_is_invalid():
    with pytest.raises(ValueError, match="Invalid recipient email"):
        resolve_recipient(
            pinned=None,
            named=None,
            default="not-an-email",
        )


def test_validated_recipient_accepts_a_good_pin():
    assert validated_recipient("pin@example.com") == "pin@example.com"


def test_validated_recipient_rejects_a_bad_pin():
    with pytest.raises(ValueError, match="Invalid recipient email"):
        validated_recipient("not-an-email")


def test_resolve_does_not_read_default_inbox_from_the_environment(monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", "env@example.com")
    with pytest.raises(ValueError, match="No recipient email configured"):
        resolve_recipient(pinned=None, named=None, default=None)
