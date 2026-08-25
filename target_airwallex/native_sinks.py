from target_airwallex.client import AirwallexSink

MAX_ACCOUNTING_FIELDS = 20


class AccountingFieldsSink(AirwallexSink):
    """Native Airwallex accounting custom fields (not unified schema).

    Airwallex quirks this sink has to handle:
    - Max 20 custom fields per account.
    - `name_label` is the user-facing label (what we match on).
    - `name` is an internal slot Airwallex assigns like "Custom field 1"..N.
      On create we pick the next free slot; on update we must send the existing
      `name` back unchanged.
    """

    name = "accounting_fields"
    endpoint = "/accounting/accounting_fields/create"

    def upsert_record(self, record: dict, context: dict):
        state = {}
        endpoint = self.endpoint
        update_reference_date = True

        # Match an existing field by display label.
        # NOTE: AWX docs say only available values for name are Custom field N, 
        # but we've seen Custom fields where the name is the same as the name_label. (HGI-11058)
        # so we check both.
        accounting_field = next(
            (
                af
                for af in self.accounting_fields
                if ((record.get("id") == af.get("id")) or (af.get("name_label") == record.get("name_label") or af.get("name") == record.get("name_label")))
            ),
            None,
        )

        # Same label already in Airwallex, and no hotglue id → treat as existing
        if accounting_field and not record.get("id"):
            return accounting_field.get("id"), True, {"existing": True}

        if record.get("id") and accounting_field:
            # Previously synced by hotglue → update. Keep Airwallex's internal
            # `name` slot; only name_label (and other payload fields) may change.
            endpoint = f"/accounting/accounting_fields/{record.pop('id')}/update"
            record["name"] = accounting_field.get("name")
            state["is_updated"] = True
            update_reference_date = False
        elif not accounting_field and not record.get("id"):
            # Brand-new field → create. Assign next "Custom field N" slot 
            record = self.add_request_id(record)
            # Maximum number of accounts according to Airwallex docs is 5, raise an exception if all slots are taken
            if len(self.accounting_fields) == MAX_ACCOUNTING_FIELDS:
                raise Exception(
                    "Maximum number of accounting fields reached, cannot create new "
                    f"accounting field with name label: {record.get('name_label')}"
                )
            record["name"] = self._next_custom_field_name()

        response_json = self.request_api(
            "POST", endpoint, request_data=record
        ).json()
        field_id = response_json.get("id")

        if update_reference_date: 
            # Keep in-run cache in sync so later records in this job see the new field.
            self.accounting_fields.append({
                "id": field_id,
                "name_label": record.get("name_label"),
                "name": record.get("name"),
            })

        return field_id, True, state

    def _next_custom_field_name(self) -> str:
        """Return the next free Airwallex slot name in Custom field 1–20."""
        # NOTE: AWX docs say only available values for name are Custom field N, 
        # but we've seen Custom fields where the name is the same as the name_label. (HGI-11058)
        used_numbers = set()
        used_not_numbers = set()
        for af in self.accounting_fields:
            if af.get("name"):
                try:
                    used_numbers.add(int(af.get("name").split(" ")[-1]))
                except:
                    used_not_numbers.add(af.get("name"))

        # NOTE: in case all the custom fields have numbers we would  keep previous logic 
        # and iterate over all the fields and check which slots are taken, 
        # e.g. there were cases where 2 and 4 were taken but 3 was not, so we would use that one.
        if not used_not_numbers:
            for n in range(1, MAX_ACCOUNTING_FIELDS + 1):
                if n not in used_numbers:
                    return f"Custom field {n}"
            raise Exception("No free Custom field slots available (1–20)")
        
        else:
            # NOTE: in case some custom fields have numbers and some don't we can't reliably check for the next free number
            # so in case there are numbers and the max number is equal or greater than the number of custom fields, we can use the next number
            # otherwise we can only try to use the len(custom fields) + 1, this could still be taken.
            max_used_number = max(used_numbers) if used_numbers else 0
            if max_used_number >= len(self.accounting_fields) and max_used_number + 1 <= MAX_ACCOUNTING_FIELDS:
                return f"Custom field {max_used_number + 1}"
            else:
                return f"Custom field {len(self.accounting_fields) + 1}"        
        raise Exception("No free Custom field slots available (1–20)")

class AccountingFieldsValuesSink(AirwallexSink):
    name = "accounting_field_values"
    endpoint = "/accounting/accounting_field_values/create"

    relation_fields = [
        {
            "field": "accounting_field_id",
            "objectName": "accounting_fields",
        }
    ]

    def upsert_record(self, record: dict, context: dict):
        state = {}
        endpoint = self.endpoint

        if record.get("id"):
            endpoint = f"/accounting/accounting_field_values/{record.pop('id')}/update"
            state["is_updated"] = True
        else:
            record = self.add_request_id(record)
            record.pop("status", None)

        response = self.request_api(
            "POST", endpoint, request_data=record
        )   
        return response.json().get("id"), True, state


class TaxRatesSink(AirwallexSink):
    name = "tax_rates"
    endpoint = "/accounting/tax_codes/create"

    def upsert_record(self, record: dict, context: dict):
        state = {}
        endpoint = self.endpoint

        if record.get("id"):
            endpoint = f"/accounting/tax_codes/{record.pop('id')}/update"
            state["is_updated"] = True
            record["status"] = record.get("status", "ACTIVE")
        else:
            record = self.add_request_id(record)

        response = self.request_api(
            "POST", endpoint, request_data=record
        )   
        return response.json().get("id"), True, state