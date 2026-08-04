"""airwallex target class."""

import threading

from hotglue_singer_sdk import typing as th
from hotglue_singer_sdk.target_sdk.target import TargetHotglue

from target_airwallex.unified_sinks import VendorSink, AccountSink
from target_airwallex.native_sinks import AccountingFieldsSink, AccountingFieldsValuesSink


class TargetAirwallex(TargetHotglue):
    """Sample target for airwallex."""

    name = "target-airwallex"
    reference_data = {}
    _auth_lock = threading.Lock()
    # Shared by all sinks: parallel upserts read/write the same in-memory cache
    # (vendors, accounts). Hold this lock for those mutations.
    _reference_data_lock = threading.Lock()
    # SDK process_record/update_state mutate latest_state with no internal lock.
    _state_lock = threading.Lock()

    config_jsonschema = th.PropertiesList(
        th.Property("api_key", th.StringType, required=True),
        th.Property("client_id", th.StringType, required=True),
        th.Property("is_sandbox", th.BooleanType, required=False, default=False),
    ).to_dict()

    SINK_TYPES = [VendorSink, AccountSink, AccountingFieldsSink, AccountingFieldsValuesSink]

if __name__ == "__main__":
    TargetAirwallex.cli()
