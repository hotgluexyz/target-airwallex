from copy import deepcopy
import json
import uuid

from target_airwallex.client import AirwallexSink


class VendorSink(AirwallexSink):
    name = "Vendors"
    endpoint = "/spend/vendors/create"
    max_concurrent_requests = 20

    def preprocess_record(self, record: dict, context: dict) -> dict:
        address = record.get("addresses")[0] if record.get("addresses") else {}
        email = record.get("email")
        payload = {
            "externalId": record.get("externalId"),
            "external_id": record.get("externalId"),
            "name": record.get("vendorName"),
            "legal_entity_ids": record.get("legal_entity_ids"),
            "status": "ARCHIVED" if not record.get("isActive") else "ACTIVE",
            "sync_status": "SYNCED",
        }

        if address:
            payload["address"] = {
                "street_address": address.get("line1"),
                "city": address.get("city"),
                "state": address.get("state"),
                "postcode": address.get("zipCode"),
                "country_code": address.get("country"),
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
        return self.add_request_id(payload)

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
        request_record = dict(record)
        request_record.pop("externalId", None)
        response = self.request_api(method, endpoint, request_data=request_record)
        response_json = response.json()
        # Keep the in-run vendor cache in sync so later parallel upserts see this create.
        with self._target._reference_data_lock:
            self._target.reference_data["vendors"].append({
                "id": response_json.get("id"),
                "name": response_json.get("name"),
            })
        return response_json.get("id"), True, {}
    

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


class BillSink(AirwallexSink):
    """Create Airwallex Spend bills from approved ERP supplier invoices."""

    name = "Bills"
    endpoint = "/spend/bills/create"

    def preprocess_record(self, record: dict, context: dict) -> dict:
        record = deepcopy(record)
        vendor_external_id = record.pop("vendor_external_id")
        vendor_id = self.state_id_for_external_id("Vendors", vendor_external_id)
        if not vendor_id:
            raise ValueError(
                f"Fulfil supplier '{vendor_external_id}' has not been created in Airwallex. "
                "Emit Vendors before Bills."
            )
        for line in record.get("line_items", []):
            account_external_id = line.pop("account_external_id", None)
            account_id = self.state_id_for_external_id("Accounts", account_external_id)
            if not account_id:
                raise ValueError(
                    f"Fulfil account '{account_external_id}' has not been created in Airwallex. "
                    "Emit Accounts before Bills."
                )
            line["accounting_field_selections"] = [
                {"type": "GENERAL_LEDGER_ACCOUNT", "source_id": account_id}
            ]
        record["vendor_id"] = vendor_id
        record["external_id"] = record["externalId"]
        # A retry after a lost response must use the same create request ID.
        identity = json.dumps([record["legal_entity_id"], str(record["externalId"])])
        record["request_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, "airwallex-bill:" + identity))
        return record

    def upsert_record(self, record: dict, context: dict):
        if record.get("id"):
            return record["id"], True, {"existing": True}

        entity_id = record["legal_entity_id"]
        cache_key = ("bills", entity_id)
        if cache_key not in self._target.reference_data:
            # The API defaults to the last 30 days without an explicit start.
            params = {"legal_entity_id": entity_id, "from_created_at": "1970-01-01T00:00:00Z"}
            bills = []
            while True:
                page = self.request_api("GET", "/spend/bills", params=params).json()
                bills.extend(page.get("items", []))
                cursor = page.get("page_after")
                if not cursor:
                    break
                params["page"] = cursor
            self._target.reference_data[cache_key] = bills

        bills = self._target.reference_data[cache_key]
        existing = next((bill for bill in bills
                         if bill.get("legal_entity_id") == entity_id
                         and str(bill.get("external_id")) == str(record["external_id"])), None)
        if existing:
            return existing["id"], True, {"existing": True}

        payload = dict(record)
        payload.pop("externalId", None)
        payload.pop("id", None)
        result = self.request_api("POST", self.endpoint, request_data=payload).json()
        bills.append({"id": result["id"], "external_id": record["external_id"],
                      "legal_entity_id": entity_id})
        return result["id"], True, {}
