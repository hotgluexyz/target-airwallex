from hotglue_singer_sdk.target_sdk.client import HotglueSink
import uuid

from target_airwallex.auth import AirwallexAuthenticator


class AirwallexSink(HotglueSink):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    allows_externalid = ["Vendors", "Accounts"]
    
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

    def preprocess_record(self, record: dict, context: dict) -> dict:
        return record

    def add_request_id(self, record: dict) -> dict:
        record["request_id"] = str(uuid.uuid4())
        return record

    def get_data(self, endpoint: str) -> list[dict]:
        params = {}
        data = []
        while True:
            response = self.request_api("GET", endpoint, params=params)
            data.extend(response.json().get("items", []))
            cursor = response.json().get("page_after")
            if cursor is not None:
                params = {"page": cursor}
            else:
                break
        return data

    def _cached_reference(self, key: str, endpoint: str, fields: list[str]) -> list[dict]:
        if self._target.reference_data.get(key) is None:
            rows = self.get_data(endpoint)
            self._target.reference_data[key] = [
                {field: row.get(field) for field in fields} for row in rows
            ]
        return self._target.reference_data[key]

    @property
    def vendors(self) -> list[dict]:
        return self._cached_reference("vendors", "/spend/vendors", ["id", "name"])

    @property
    def accounts(self) -> list[dict]:
        return self._cached_reference(
            "accounts",
            "/accounting/gl_accounts",
            ["id", "code", "legal_entity_ids", "value"],
        )

    @property
    def accounting_fields(self) -> list[dict]:
        return self._cached_reference(
            "accounting_fields",
            "/accounting/accounting_fields",
            ["id", "name_label", "name"],
        )

    def get_account(self, record: dict) -> tuple[dict, bool]:
        """Resolve an account against existing Airwallex GL accounts.

        Logic added to not update existing accounts that don't belong to a new hg integration

        Returns (record, skip) where skip=True means mark as existing and do not
        create/update. Creating with a code/value that already exists fails;
        updating replaces code/value for all legal entities and dropping entities
        removes them — so conflicts are raised instead of silently updating.
        """
        code = record.get("code")
        value = record.get("value")
        accounts = self.accounts
        if code is None:
            raise ValueError("Account code is required")

        # Account was created/updated via hotglue — allow create/update path.
        if record.get("id"):
            return record, False

        by_code = next((a for a in accounts if a.get("code") == code), None)
        by_value = next(
            (a for a in accounts if value is not None and a.get("value") == value),
            None,
        )

        if by_code is None and by_value is None:
            return record, False

        self._raise_if_account_conflict(code, value, by_code, by_value)

        account = by_code or by_value
        self._raise_if_legal_entity_mismatch(code, value, record, account)

        record["id"] = account.get("id")
        return record, True

    def _raise_if_account_conflict(self, code, value, by_code, by_value) -> None:
        if by_code and by_code.get("value") != value:
            raise ValueError(
                f"Found an account with the same code '{code}' but different value "
                f"(existing: '{by_code.get('value')}', incoming: '{value}'). "
                "Updating would change the code/value for all the legal entities "
                "associated with the existing account."
            )

        if by_value and by_value.get("code") != code:
            raise ValueError(
                f"Found an account with the same value '{value}' but different code "
                f"(existing: '{by_value.get('code')}', incoming: '{code}'). "
                "Updating would change the code/value for all the legal entities "
                "associated with the existing account."
            )

    def _raise_if_legal_entity_mismatch(self, code, value, record, account) -> None:
        record_entities = set(record.get("legal_entity_ids") or [])
        account_entities = set(account.get("legal_entity_ids") or [])
        if record_entities == account_entities:
            return

        missing = record_entities - account_entities
        raise ValueError(
            f"Found an account with the same code '{code}' and value '{value}' "
            f"but different legal entities. "
            f"Record entities not on existing account: {sorted(missing) or 'none'}; "
            f"existing: {sorted(account_entities)}; incoming: {sorted(record_entities)}. "
            "Creating new account for missing entities will fail due to duplicate "
            "code/value; updating with fewer entities removes the omitted ones."
        )
