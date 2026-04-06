from hotglue_singer_sdk.target_sdk.client import HotglueSink

from target_airwallex.auth import AirwallexAuthenticator


class FallbackSink(HotglueSink):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.authenticator = AirwallexAuthenticator(self._target, self._state)
    
    @property
    def base_url(self) -> str:
        if self.config.get("sandbox"):
            return "https://api.airwallex.com/public_api/v1/"
        return "https://api-demo.airwallex.com/public_api/v1"
    
    @property
    def name(self) -> str:
        return self.stream_name

    def preprocess_record(self, record: dict, context: dict) -> dict:
        return record

    def upsert_record(self, record: dict, context: dict):
        record_id = record.pop("id", None)
        is_update = record_id is not None

        endpoint = f"/{self.name}"
        method = "POST"
        payload = [record]

        if is_update:
            endpoint = f"/{self.name}/{record_id}"
            method = "PATCH"
            payload = record

        response = self.request_api(method, endpoint, request_data=payload)
        id = response.json().get("id")

        state_updates = {}
        if is_update and response.ok:
            state_updates = {"is_updated": True}

        return id, response.ok, state_updates
    
