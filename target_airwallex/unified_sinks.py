import uuid

from target_airwallex.client import AirwallexSink


class VendorSink(AirwallexSink):
    name = "Vendors"
    endpoint = "/spend/vendors/create"

    def preprocess_record(self, record: dict, context: dict) -> dict:
        address = record.get("addresses")[0] if record.get("addresses") else {}
        email = record.get("email")
        payload = {
            "externalId": record.get("externalId"),
            "request_id": uuid.uuid4(), #idempotency key
            "external_id": record.get("externalId"),
            "name": record.get("vendorName"),
            "address": {
                "street_address": address.get("line1"),
                "city": address.get("city"),
                "state": address.get("state"),
                "postcode": address.get("zipCode"),
                "country_code": address.get("country")
            },
            "status": "ARCHIVED" if not record.get("isActive") else "ACTIVE",
        }

        if email:
            payload.update({
                "contacts": [
                    {
                        "email": email
                    }
                ]
            })

        if record.get("customFields"):
            custom_fields = {field.get("name"): field.get("value") for field in record.get("customFields")}
            payload.update(custom_fields)
        return payload

    def upsert_record(self, record: dict, context: dict):
        # lookup vendor by name
        vendor = next((v for v in self.vendors if v.get("name") == record.get("name")), None)
        if vendor:
            self.logger.info(f"Vendor {record.get('name')} already exists with id {vendor.get('id')}")
            return vendor.get("id"), True, {"existing": True}

        # if vendor has id, mark as existing, only status can be updated
        record_id = record.pop("id", None)
        if record_id:
            self.logger.info(f"Vendor only allows status update, skipping update for {record_id}")
            return record_id, True, {"existing": True}
        
        endpoint = self.endpoint
        method = "POST"
        response = self.request_api(method, endpoint, request_data=record)
        # add response to reference data
        self._target.reference_data["vendors"].append({
            "id": response.json().get("id"),
            "name": response.json().get("name")
        })
        return response.json().get("id"), True, {}
    

class AccountSink(AirwallexSink):

    name = "Accounts"
    endpoint = "/accounting/gl_accounts/create"

    def preprocess_record(self, record: dict, context: dict) -> dict:
        legal_entity_ids = [sub.get("id") for sub in record.get("subsidiaryRef")]
        payload = {
            "code": record.get("accountNumber"),
            "value": record.get("name"),
            "value_label": record.get("name"),
            "legal_entity_ids": legal_entity_ids,
            "status": "ARCHIVED" if not record.get("isActive") else "ACTIVE",
            "id": record.get("id"),
            "external_id": record.get("externalId"),
            "externalId": record.get("externalId"),
        }
        return self.add_request_id(payload)

    def upsert_record(self, record: dict, context: dict):
        record, skip = self.get_account(record)
        if skip:
            self.logger.info(
                f"Account {record.get('value') or record.get('value_label')} already exists with id {record.get('id')}"
            )
            return record.get("id"), True, {"existing": True}

        record_id = record.pop("id", None)
        state = {}
        endpoint = self.endpoint

        if record_id:
            endpoint = f"/accounting/gl_accounts/{record_id}/update"
            record.pop("request_id", None)
            state = {"is_updated": True}
        else:
            record.pop("status", None)

        response_json = self.request_api(
            "POST", endpoint, request_data=record
        ).json()
        account_entry = {
            "id": response_json.get("id"),
            "code": response_json.get("code"),
            "legal_entity_ids": response_json.get("legal_entity_ids"),
            "value": response_json.get("value"),
        }
        accounts = self._target.reference_data["accounts"]
        if record_id:
            for i, existing in enumerate(accounts):
                if existing.get("id") == account_entry["id"]:
                    accounts[i] = account_entry
                    break
        else:
            accounts.append(account_entry)
        return response_json.get("id"), True, state
