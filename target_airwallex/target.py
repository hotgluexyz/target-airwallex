"""airwallex target class."""

import threading

from hotglue_singer_sdk import typing as th
from hotglue_singer_sdk.target_sdk.target import TargetHotglue

from target_airwallex.unified_sinks import VendorSink, AccountSink
from target_airwallex.native_sinks import AccountingFieldsSink, AccountingFieldsValuesSink, TaxRatesSink, BillsSyncSink, ExpensesSyncSink


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

    SINK_TYPES = [VendorSink, AccountSink, AccountingFieldsSink, AccountingFieldsValuesSink, TaxRatesSink, BillsSyncSink, ExpensesSyncSink]

    def merge_sink_state(self, sink) -> None:
        """
        If there's less records than the batch size, we need to Copy a sink's 
        latest_state into target _latest_state, so it's properly written.
        """
        sink_latest_state = getattr(sink, "latest_state", None)
        if not sink_latest_state:
            return
        with self._state_lock:
            if not self._latest_state:
                self._latest_state = sink_latest_state
                return
            for key in ("bookmarks", "summary"):
                part = sink_latest_state.get(key)
                if not isinstance(part, dict):
                    continue
                if key not in self._latest_state or not isinstance(
                    self._latest_state[key], dict
                ):
                    self._latest_state[key] = {}
                self._latest_state[key].update(part)

    def _flush_sink_pending_records(self, sink) -> None:
        if not sink or not hasattr(sink, "flush_pending_records"):
            return
        sink.flush_pending_records()

    def drain_all(self, is_endofpipe: bool = False) -> None:
        # SDK snapshots _latest_state before clean_up; flush queued records first.
        if is_endofpipe:
            # forcing flushing after each sink, so the state is written properly.
            for sink in self._sinks_to_clear:
                self._flush_sink_pending_records(sink)
            for sink in self._sinks_active.values():
                self._flush_sink_pending_records(sink)
        super().drain_all(is_endofpipe=is_endofpipe)

if __name__ == "__main__":
    TargetAirwallex.cli()
