"""Tests for Airwallex target authentication."""

import threading

from target_airwallex.auth import AirwallexAuthenticator


def test_authenticator_refreshes_directly_with_airwallex():
    """The target must not request a Hotglue connector access token."""
    authenticator = object.__new__(AirwallexAuthenticator)
    authenticator._target = type("Target", (), {"_auth_lock": threading.Lock()})()
    authenticator.is_token_valid = lambda: False
    refreshed = []
    authenticator._update_access_token_locally = lambda: refreshed.append(True)

    authenticator.update_access_token()

    assert refreshed == [True]
