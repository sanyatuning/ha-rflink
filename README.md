# RFLink CE

A modern, UI-configured Home Assistant integration for [RFLink](https://www.nodo-shop.com/) USB/TCP gateways — covers and sensors only, for now.

This is a from-scratch custom_component, **not** a replacement for the built-in core `rflink` integration. It uses a different domain (`rflink_ce`) so it can be installed alongside core `rflink` without conflict. Unlike core `rflink`, it has no YAML configuration at all: gateway setup, device discovery, and device configuration all happen through the UI.

## Why this exists

Core `rflink` is YAML-only, has no config flow, and requires you to hand-declare every device's entity type (`cover`, `switch`, `sensor`, …) in `configuration.yaml` ahead of time. This integration replaces that with:

- A config flow for connecting to the gateway (serial or network), with reconfigure support.
- Automatic detection of new devices, surfaced as repair issues instead of requiring YAML edits.
- Each physical device becomes its own entry in the device registry (linked to the gateway via `via_device`), not just a bare entity.

## Setup

1. `custom_components/rflink_ce` already contains this integration — for manual installs, copy it to `<config>/custom_components/rflink_ce/` and restart Home Assistant. For HACS, add this repo as a custom repository instead.
2. Settings → Devices & Services → Add Integration → **RFLink CE**.
3. Choose **Serial** (pick your gateway's port from the list, or enter a path manually) or **Network** (host + port).
4. To change the connection later, use the integration's **Reconfigure** action — no need to remove and re-add it.

## Adding devices

Devices are **not** added manually. The gateway only knows a device exists once it hears a signal from it:

1. Trigger the device once — press a button on its remote, or wait for a sensor to transmit.
2. A repair issue appears: **Settings → System → Repairs → "New RFLink device detected: `<id>`"**.
3. Open it and choose **Classify this device** or **Ignore this device permanently**.
4. Classifying shows the raw signal(s) received so far (id, command, or sensor field/value) and suggests a device type — `sensor` if the signal carries a sensor reading, `cover` if the device ID looks like `*motor*`/`*cover*`/`*shutter*`/`*blind*`/`*roll*`. You can always override the suggestion.
5. Fill in a name and, optionally, advanced options (see below), and submit. The device now appears under **Settings → Devices & Services → RFLink CE** with its entities.

**A device's type can't be changed later** — remove it and let it get re-detected to reclassify. This is deliberate: switching a device between `cover` and `sensor` after the fact would mean tearing down and rebuilding a completely different entity shape anyway.

### Noisy / unwanted devices

RFLink hardware often picks up signals you don't care about (a neighbor's remote, someone else's weather station). Two ways to suppress them:

- **Ignore this device permanently** on its repair issue — adds its exact ID to the Gateway's Ignore Patterns.
- **Settings → Devices & Services → RFLink CE → Configure** — edit the Ignore Pattern list directly, with shell-style wildcards (e.g. `neighbor_*`).

Either way, matching device IDs never raise a repair issue again.

## Devices

### Cover

Open/close/stop always work. If you set **Time to fully open** (and optionally **Time to fully close**, which defaults to the same value) when classifying or editing a device, the cover also gets:

- A live, continuously-updating position estimate (0–100%), computed from elapsed time since the last move started — including moves triggered from the physical remote, not just from Home Assistant.
- `set_cover_position` support.

Leave the travel time unset for a plain open/close/stop cover with no position.

### Sensor

One entity per measurement field (temperature, humidity, battery, wind speed, barometric pressure, …), created automatically as each field is first observed — a device classified as `sensor` doesn't need every field configured up front. `update_time` (a bookkeeping timestamp RFLink attaches to every sensor packet) shows up as a diagnostic entity rather than a regular one.

### Advanced per-device options

- **Aliases** — other device IDs that should control this same entity, for both normal and group commands.
- **Group aliases** / **No-group aliases** — collected today but not yet wired into command matching; setting them currently has no effect.
- **Fire event** — put every incoming command on the HA event bus.
- **Signal repetitions** — override how many times outgoing commands are repeated.

## Limitations

- Only `cover` and `sensor` platforms exist. `switch`, `light`, and `binary_sensor` (available in core `rflink`) aren't implemented.
- No automatic USB-plug discovery — RFLink dongles use generic USB-serial chips (e.g. CH340) shared by unrelated hardware, so there's no safe way to auto-detect one being plugged in. Set up the gateway manually instead; the serial-port picker will still list it.
- Group/no-group alias matching isn't implemented yet (see above).
