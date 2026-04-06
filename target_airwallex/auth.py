from hotglue_singer_sdk.target_sdk.auth import OAuthAuthenticator
from pendulum import parse
from datetime import datetime
import requests
import json
from hotglue_etl_exceptions import InvalidCredentialsError


class AirwallexAuthenticator(OAuthAuthenticator):

    @property
    def oauth_request_headers(self) -> str:
        """Return the authentication endpoint."""
        return {
            "Content-Type": "application/json",
            "x-api-key": self.config["api_key"],
            "x-client-id": self.config["client_id"]
        }

    def is_token_valid(self) -> bool:
        """Check if token is valid.

        Returns:
            True if the token is valid (fresh).
        """
        # if expires_in is not set, try to get it from the tap config
        if self.expires_in is None and self.config.get("expires_at"):
            self.expires_in = self.config.get("expires_at")
            self.expires_in = parse(self.expires_in).timestamp()
        if not self.expires_in:
            return False
        if int(self.expires_in) - int(datetime.utcnow().timestamp()) > 120:
            return True
        return False

    def update_access_token_locally(self) -> None:
        """Update `access_token` locally."""

        token_response = requests.post(self.auth_endpoint, headers=self.oauth_request_headers)
        try:
            token_response.raise_for_status()
            self.logger.info("OAuth authorization attempt was successful.")
        except Exception as ex:
            raise InvalidCredentialsError(
                f"Failed OAuth login, response was '{token_response.text}'. {ex}"
            )
        token_json = token_response.json()
        self.access_token = token_json["token"]
        expires_in = token_json.get("expires_at")
        self.expires_in = parse(expires_in).timestamp()

        # Update the tap config with the new access_token and refresh_token
        self._config["access_token"] = token_json["token"]
        self._config["expires_in"] = self.expires_in

        # Write the updated config back to the file (only when config was loaded from a path)
        if self._config_file_path is not None:
            with open(self._config_file_path, "w") as outfile:
                json.dump(self._config, outfile, indent=4)
