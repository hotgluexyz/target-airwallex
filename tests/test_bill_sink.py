"""Contract tests for Fulfil supplier invoice imports."""

import io
import json
import threading
import time
import uuid

import pytest
import requests

from target_airwallex.client import AirwallexSink
from target_airwallex.target import TargetAirwallex
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
            "legal_entity_id": "le-10",
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

    request_id = result.pop("request_id")
    assert str(uuid.UUID(request_id)) == request_id
    retry = sink.preprocess_record({
        "externalId": "invoice-100", "legal_entity_id": "le-10",
        "vendor_external_id": "supplier-10", "line_items": [],
    }, {})
    assert retry["request_id"] == request_id
    assert result == {
        "externalId": "invoice-100",
        "external_id": "invoice-100",
        "legal_entity_id": "le-10",
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
            "sync_status": "SYNCED",
            "request_id": "request-1",
        },
    }


@pytest.mark.parametrize("reject_vendors", [False, True])
def test_singer_input_preserves_buffered_vendor_results_for_bills(
    monkeypatch, tmp_path, reject_vendors
):
    bill_requests = []

    def request(method, url, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.url = url
        body = json.loads(kwargs.get("data") or "{}")
        if method == "GET":
            result = {"items": []}
        elif url.endswith("/spend/vendors/create"):
            assert body["sync_status"] == "SYNCED"
            assert body["legal_entity_ids"] == ["le-10"]
            if reject_vendors:
                response.status_code = 400
                result = {"message": "Vendor rejected"}
            else:
                result = {"id": "awx-" + body["external_id"], "name": body["name"]}
        elif url.endswith("/accounting/gl_accounts/create"):
            result = {**body, "id": "awx-account-40"}
        elif url.endswith("/spend/bills/create"):
            bill_requests.append(body)
            result = {"id": "awx-" + body["external_id"]}
        else:
            raise AssertionError(f"Unexpected request: {method} {url}")
        response._content = json.dumps(result).encode()
        return response

    monkeypatch.setattr(requests, "request", request)
    target = TargetAirwallex(config={
        "api_key": "test-only",
        "client_id": "test-only",
        "access_token": "test-only",
        "expires_in": int(time.time()) + 3600,
    })
    target.reference_data = {}
    target.incremental_target_state_path = str(tmp_path / "state.json")
    streams = {
        "Accounts": [{
            "externalId": "account-40", "accountNumber": "4000", "name": "Supplies",
            "isActive": True, "subsidiaryRef": [{"id": "le-10"}],
        }],
        "Vendors": [
            {"externalId": vendor, "vendorName": vendor, "isActive": True,
             "legal_entity_ids": ["le-10"]}
            for vendor in ("supplier-10", "supplier-20")
        ],
        "Bills": [
            {"externalId": invoice, "vendor_external_id": vendor,
             "legal_entity_id": "le-10",
             "line_items": [{"account_external_id": "account-40", "unit_price": "25"}]}
            for invoice, vendor in (("invoice-1", "supplier-20"), ("invoice-2", "supplier-10"))
        ],
    }
    messages = []
    for stream, records in streams.items():
        messages.append({
            "type": "SCHEMA", "stream": stream,
            "schema": {"type": "object", "properties": {key: {} for key in records[0]}},
            "key_properties": [],
        })
        messages.extend({"type": "RECORD", "stream": stream, "record": row} for row in records)
        messages.append({"type": "STATE", "value": {}})
    try:
        target.listen(io.StringIO("\n".join(json.dumps(message) for message in messages)))
    finally:
        target._shutdown_requested.set()

    state = target._latest_state
    for stream in ("Vendors", "Bills"):
        assert state["summary"][stream]["fail"] == (2 if reject_vendors else 0)
        assert state["summary"][stream]["success"] == (0 if reject_vendors else 2)
        assert len(state["bookmarks"][stream]) == 2
    if reject_vendors:
        assert bill_requests == []
    else:
        assert [bill["vendor_id"] for bill in bill_requests] == ["awx-supplier-20", "awx-supplier-10"]
        assert all(
            line["accounting_field_selections"] == [
                {"type": "GENERAL_LEDGER_ACCOUNT", "source_id": "awx-account-40"}
            ]
            for bill in bill_requests for line in bill["line_items"]
        )


def test_bill_reimports_reconcile_remote_ids_and_preserve_source_bookmarks(monkeypatch, tmp_path):
    remote = [{"id": "direct-created-ci332", "external_id": "1617", "legal_entity_id": "le-10"}]
    creates = []

    def request(method, url, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.url = url
        if method == "GET":
            params = kwargs["params"]
            assert params["from_created_at"] == "1970-01-01T00:00:00Z"
            # Existing bill is on page two, beyond the default 30-day window.
            result = {"items": [], "page_after": "older"} if "page" not in params else {
                "items": [row for row in remote if row["legal_entity_id"] == params["legal_entity_id"]]
            }
        else:
            body = json.loads(kwargs["data"])
            assert "externalId" not in body and "id" not in body
            creates.append(body)
            result = {**body, "id": "created-" + str(len(creates))}
            remote.append(result)
        response._content = json.dumps(result).encode()
        return response

    monkeypatch.setattr(requests, "request", request)
    records = [
        {"externalId": external_id, "legal_entity_id": entity,
         "vendor_external_id": "supplier-10", "line_items": []}
        for external_id, entity in (("1617", "le-10"), ("1618", "le-10"), ("1617", "le-20"))
    ]
    records.append({**records[0], "externalId": "1619", "id": "snapshot-bill"})
    messages = [{"type": "SCHEMA", "stream": "Bills", "key_properties": [],
                 "schema": {"type": "object", "properties": {key: {} for key in records[-1]}}}]
    messages += [{"type": "RECORD", "stream": "Bills", "record": record} for record in records]
    source = "\n".join(map(json.dumps, messages))
    for attempt in range(2):
        target = TargetAirwallex(config={
            "api_key": "test-only", "client_id": "test-only", "access_token": "test-only",
            "expires_in": int(time.time()) + 3600,
        })
        target.reference_data = {}
        target.incremental_target_state_path = str(tmp_path / f"state-{attempt}.json")
        target._latest_state = {"bookmarks": {"Vendors": [
            {"success": True, "externalId": "supplier-10", "id": "vendor-awx-10"}
        ]}, "summary": {}}
        try:
            target.listen(io.StringIO(source))
        finally:
            target._shutdown_requested.set()
        bookmarks = target._latest_state["bookmarks"]["Bills"]
        assert [(row["externalId"], row["id"], row["success"]) for row in bookmarks] == [
            ("1617", "direct-created-ci332", True),
            ("1618", "created-1", True),
            ("1617", "created-2", True),
            ("1619", "snapshot-bill", True),
        ]
    assert len(creates) == 2
    assert creates[0]["request_id"] != creates[1]["request_id"]
