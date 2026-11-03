"""airwallex target class."""

import copy
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

    def _apply_sink_latest_state(self, sink_latest_state: dict) -> None:
        """Merge sink state into _latest_state (streaming uses nested target bucket)."""
        if self.streaming_job:
            if not self._latest_state:
                self._latest_state = {"tap": {}, "target": {}}
            target_bucket = self._latest_state.get("target")
            if not target_bucket:
                self._latest_state["target"] = sink_latest_state
                return
            for key in ("bookmarks", "summary"):
                part = sink_latest_state.get(key)
                if not isinstance(part, dict):
                    continue
                if key not in target_bucket or not isinstance(
                    target_bucket[key], dict
                ):
                    target_bucket[key] = {}
                target_bucket[key].update(part)
            return

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

    def merge_sink_state(self, sink) -> None:
        """Merge sink bookmarks/summary into target _latest_state for final emit."""
        sink_latest_state = getattr(sink, "latest_state", None)
        if not sink_latest_state:
            return
        with self._state_lock:
            self._apply_sink_latest_state(sink_latest_state)

    def _process_record_message(self, message_dict: dict) -> None:
        """Same as TargetHotglue, but use _apply_sink_latest_state (SDK streaming merge is broken)."""
        self._assert_line_requires(message_dict, requires={"stream", "record"})

        stream_name = message_dict["stream"]
        for stream_map in self.mapper.stream_maps[stream_name]:
            raw_record = copy.copy(message_dict["record"])
            transformed_record = stream_map.transform(raw_record)
            if transformed_record is None:
                continue

            sink = self.get_sink(stream_map.stream_alias, record=transformed_record)
            if not sink:
                continue

            context = sink._get_context(transformed_record)
            if sink.include_sdc_metadata_properties:
                sink._add_sdc_metadata_to_record(
                    transformed_record, message_dict, context
                )
            else:
                sink._remove_sdc_metadata_from_record(transformed_record)

            sink._validate_and_parse(transformed_record)
            sink.tally_record_read()

            if hasattr(sink, "prepare_target_state_field_context"):
                sink.prepare_target_state_field_context(message_dict["record"], context)

            validation_success, transformed_record = self._validate_unified_schema(
                sink, transformed_record
            )
            if not validation_success:
                continue

            transformed_record = self.get_record_id(
                sink.name,
                transformed_record,
                sink.relation_fields if hasattr(sink, "relation_fields") else None,
            )

            sink.process_record(transformed_record, context)
            sink._after_process_record(context)

            if sink.is_full:
                self.logger.info(
                    f"Target sink for '{sink.stream_name}' is full. Draining..."
                )
                self.drain_one(sink)

            with self._state_lock:
                self._apply_sink_latest_state(sink.latest_state or {})

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
