<!-- generated:start cap:api-intro -->
# API Reference

Endpoints **declared on the architecture canvas** (`endpoints` widgets) - not extracted from source. Reconciliation against live routes is tooling-owned and will operate inside these same generated blocks.
<!-- generated:end cap:api-intro -->

<!-- generated:start comp:macro-engine -->
## Macro Engine (`macro-engine`)

| Method | Path | Description |
|---|---|---|
| **IPC** | `key_watch` | Watch (non-grabbing) evdev nodes whose name contains any given device name; [] stops |
| **IPC** | `key_events` | Key-down events since a sequence cursor from a bounded ring buffer |
<!-- generated:end comp:macro-engine -->

### `record_start` arguments

- `identity` (string, required): the device whose key and button presses are recorded.
- `also_identities` (list of strings, optional, at most 8): further devices recorded beside `identity`, e.g. the mouse next to a keyboard. Each is opened and checked for foreign grabs like `identity`; an extra that cannot be opened (or is grabbed exclusively elsewhere) is skipped and listed in `skipped_also`, and the request still succeeds. Only `identity` failing fails the request. `record_stop` releases every identity it opened. Recorded events keep the 3-element `[code, value, t]` form; mouse wheel notches are recorded as `["REL_WHEEL", ±1, t]`. Pointer motion is never recorded.

Reply: `{"identity": <primary>, "skipped_also": [<identity>, ...]}` (empty list when no extra was skipped), plus `"blocked_nodes"` when some nodes are grabbed by another program.

### Macro step `wheel`

`{"type": "wheel", "direction": "up" | "down"}` scrolls the mouse wheel one notch. Macros with a mouse button (`BTN_*` key step) or a wheel step play through a combined uinput that carries the trigger device's keys plus the mouse buttons and `REL_WHEEL`; other macros keep the passthrough clone. Older builds cannot read `wheel` steps.
