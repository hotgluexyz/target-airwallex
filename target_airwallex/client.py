from hotglue_singer_sdk.target_sdk.client import HotglueSink

from target_airwallex.auth import AirwallexAuthenticator


class AirwallexSink(HotglueSink):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    allows_externalid = ["Vendors"]
    
    @property
    def base_url(self) -> str:
        if self.config.get("is_sandbox"):
            return "https://api-demo.airwallex.com/api/v1"
        return "https://api.airwallex.com/api/v1"
    
    @property
    def name(self) -> str:
        return self.stream_name

    @property
    def authenticator(self):
        auth_endpoint = f"{self.base_url}/authentication/login"
        return AirwallexAuthenticator(self._target, {}, auth_endpoint)