"""Tests for the TokenScheme verification logic.

Only the *verify_token* method is checked – the surrounding web server as well
as the CLI wrapper are intentionally excluded so the tests run fast and stay
deterministic.
"""

from datetime import datetime


import pytest


from server import TokenScheme


SECRET = b"hunter2"


def _make_token() -> tuple[TokenScheme, str]:
    """Generate a fresh *valid* token and return the scheme instance & token."""

    doc = "some tiny document"  # content is irrelevant for the logic under test
    ts = TokenScheme(SECRET, doc)
    prefix, bits = ts.make_token(datetime.now())
    token = prefix + "".join(bits)
    return ts, token


def test_valid_token_verifies():
    ts, token = _make_token()

    # Should *not* raise.
    ts.verify_token(token)


def test_doc_hash_mismatch_is_reported():
    ts, token = _make_token()

    # Corrupt the very first character of the document hash part.
    # Layout: 1:MMDD-HH:MM-<doc><pub><priv>
    head, tail = token[:-1], token[-1]
    # The doc hash starts right after the second dash – that's position index of last '-'? simpler: just
    # mutate one character after the final dash.
    pos = token.rfind("-") + 1
    tampered_char = "1" if token[pos] != "1" else "2"
    tampered_token = token[:pos] + tampered_char + token[pos + 1 :]

    with pytest.raises(TokenScheme.VerificationError) as err:
        ts.verify_token(tampered_token)

    assert any("Document hash mismatch" in issue for issue in err.value.issues)


def test_incomplete_token_is_reported_but_does_not_crash():
    ts, token = _make_token()

    # Strip the private hash so only doc+pub remain.
    incomplete_token = token[:- ts._AUTH_LEN]

    with pytest.raises(TokenScheme.VerificationError) as err:
        ts.verify_token(incomplete_token)

    assert any("Private hash incomplete" in issue for issue in err.value.issues)