from hotglue_singer_sdk.target_sdk.auth import OAuthAuthenticator
from pendulum import parse
from datetime import datetime, timezone
import requests
import json
from hotglue_etl_exceptions import InvalidCredentialsError


class AirwallexAuthenticator(OAuthAuthenticator):
    _auth_endpoint = "https://api.airwallex.com/public_api/v1/oauth/token"
    oauth_request_body = {}

    @property
    def oauth_request_headers(self) -> str:
        """Return the authentication endpoint."""
        return {
            "Content-Type": "application/json",
            "x-api-key": self._config["api_key"],
            "x-client-id": self._config["client_id"]
        }

    def is_token_valid(self) -> bool:
        """Return True when shared target config still has a fresh token.

        Always read from ``_config`` (not instance attrs) so workers that
        checked validity before acquiring ``_auth_lock`` still see the token
        written by the first refresher.
        """
        access_token = self._config.get("access_token")
        expires_in = self._config.get("expires_in")
        if not access_token or expires_in is None:
            return False
        return int(expires_in) - int(datetime.now(timezone.utc).timestamp()) > 120

    def update_access_token(self) -> None:
        """Refresh token under a lock so parallel upserts do not race."""
        with self._target._auth_lock:
            if self.is_token_valid():
                return
            super().update_access_token()

    def _update_access_token_locally(self) -> None:
        """Update `access_token` locally."""

        token_response = requests.post(self._auth_endpoint, headers=self.oauth_request_headers)
        try:
            token_response.raise_for_status()
            self.logger.info("OAuth authorization attempt was successful.")
        except Exception as ex:
            raise InvalidCredentialsError(
                f"Failed OAuth login, response was '{token_response.text}'. {ex}"
            )
        token_json = token_response.json()
        self.access_token = token_json["token"]
        expires_in = parse(token_json.get("expires_at")).timestamp()

        # Shared across all authenticator instances / worker threads.
        self._config["access_token"] = token_json["token"]
        self._config["expires_in"] = expires_in

        # Write the updated config back to the file (only when config was loaded from a path)
        if self._config_file_path is not None:
            with open(self._config_file_path, "w") as outfile:
                json.dump(self._config, outfile, indent=4)
