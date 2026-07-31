from target_airwallex.client import AirwallexSink

MAX_ACCOUNTING_FIELDS = 5


class AccountingFieldsSink(AirwallexSink):
    """Native Airwallex accounting custom fields (not unified schema).

    Airwallex quirks this sink has to handle:
    - Max 5 custom fields per account.
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
        accounting_field = next(
            (
                af
                for af in self.accounting_fields
                if ((record.get("id") == af.get("id")) or (af.get("name_label") == record.get("name_label")))
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
        """Return the next free Airwallex slot name in Custom field 1–5."""
        used = {
            int(af.get("name").split(" ")[-1])
            for af in self.accounting_fields
            if af.get("name")
        }
        for n in range(1, MAX_ACCOUNTING_FIELDS + 1):
            if n not in used:
                return f"Custom field {n}"
        raise Exception("No free Custom field slots available (1–5)")


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
