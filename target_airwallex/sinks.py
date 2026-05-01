from hotglue_singer_sdk.target_sdk.client import HotglueSink
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
        return response.json().get("id"), True, {}
    
