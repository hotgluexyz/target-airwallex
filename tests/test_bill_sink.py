"""Contract tests for Fulfil supplier invoice imports."""

import threading

from target_airwallex.client import AirwallexSink
from target_airwallex.unified_sinks import BillSink, VendorSink


def bill_sink_with_state(state):
    sink = object.__new__(BillSink)
    sink.state_id_for_external_id = lambda stream, external_id: state.get(
        (stream, external_id)
    )
    sink.add_request_id = lambda record: {**record, "request_id": "request-1"}
    return sink


def test_bill_resolves_vendor_and_line_accounts_from_target_state():
    sink = bill_sink_with_state(
        {
            ("Vendors", "supplier-10"): "vendor-awx-10",
            ("Accounts", "account-4000"): "account-awx-4000",
        }
    )

    result = sink.preprocess_record(
        {
            "externalId": "invoice-100",
            "vendor_external_id": "supplier-10",
            "line_items": [
                {
                    "description": "Office supplies",
                    "quantity": "1",
                    "unit_price": "25.00",
                    "account_external_id": "account-4000",
                }
            ],
        },
        {},
    )

    assert result == {
        "external_id": "invoice-100",
        "vendor_id": "vendor-awx-10",
        "line_items": [
            {
                "description": "Office supplies",
                "quantity": "1",
                "unit_price": "25.00",
                "accounting_field_selections": [
                    {"type": "GENERAL_LEDGER_ACCOUNT", "source_id": "account-awx-4000"}
                ],
            }
        ],
        "request_id": "request-1",
    }


def test_bill_requires_account_state_for_each_line():
    sink = bill_sink_with_state({("Vendors", "supplier-10"): "vendor-awx-10"})

    try:
        sink.preprocess_record(
            {
                "externalId": "invoice-100",
                "vendor_external_id": "supplier-10",
                "line_items": [{"account_external_id": "account-4000"}],
            },
            {},
        )
    except ValueError as error:
        assert str(error) == (
            "Fulfil account 'account-4000' has not been created in Airwallex. "
            "Emit Accounts before Bills."
        )
    else:
        raise AssertionError("Expected a missing Airwallex GL account error")


def test_state_id_for_external_id_uses_successful_record_state():
    sink = object.__new__(AirwallexSink)
    sink._target = type("Target", (), {"_state_lock": threading.Lock()})()
    sink.latest_state = {
        "bookmarks": {
            "Vendors": [
                {"success": False, "externalId": "supplier-10", "id": "failed-id"},
                {"success": True, "externalId": "supplier-10", "id": "vendor-awx-10"},
            ]
        }
    }

    assert sink.state_id_for_external_id("Vendors", "supplier-10") == "vendor-awx-10"
    assert sink.state_id_for_external_id("Vendors", "missing") is None


def test_vendor_sends_required_legal_entity_and_not_internal_external_id():
    sink = object.__new__(VendorSink)
    sink.add_request_id = lambda record: {**record, "request_id": "request-1"}
    sink._target = type(
        "Target",
        (), {"_reference_data_lock": threading.Lock(), "reference_data": {"vendors": []}},
    )()
    sink._cached_reference = lambda *args: []
    sent = {}
    sink.request_api = lambda method, endpoint, request_data: (
        sent.update({"method": method, "endpoint": endpoint, "body": request_data})
        or type("Response", (), {"json": lambda self: {"id": "vendor-awx-10"}})()
    )

    record = sink.preprocess_record(
        {
            "externalId": "supplier-10",
            "vendorName": "Supplier 10",
            "legal_entity_ids": ["le-10"],
            "isActive": True,
            "addresses": [],
        },
        {},
    )
    sink.upsert_record(record, {})

    assert sent == {
        "method": "POST",
        "endpoint": "/spend/vendors/create",
        "body": {
            "external_id": "supplier-10",
            "name": "Supplier 10",
            "legal_entity_ids": ["le-10"],
            "status": "ACTIVE",
            "request_id": "request-1",
        },
    }
