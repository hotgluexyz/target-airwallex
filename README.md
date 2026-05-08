# target-airwallex

`target-airwallex` is a Singer target for [Airwallex](https://www.airwallex.com/), built with the Hotglue Singer SDK.

## Overview

This target sends Spend **vendor** data to the Airwallex REST API. It authenticates with API credentials, obtains a bearer token, and uses a dedicated `VendorSink` that maps tap records into Airwallex’s vendor-create payload. Updates are not sent over the API for existing vendors (records with an `id` are skipped after logging).

## Installation

```bash
pip install target-airwallex
```

Or install from source:

```bash
git clone https://github.com/hotglue/target-airwallex.git
cd target-airwallex
pip install .
```

## Configuration

### Required settings

| Setting     | Description |
|-------------|-------------|
| `api_key`   | Your Airwallex API key (`x-api-key` on the login request) |
| `client_id` | Your Airwallex client ID (`x-client-id` on the login request) |

These match the target’s JSON Schema in `target_airwallex/target.py`.

### Optional settings

| Setting   | Default | Description |
|-----------|---------|-------------|
| `sandbox` | `false` | Selects demo vs production API host (see below). |

After a successful login, the authenticator may persist `access_token` and `expires_in` back into your config file when the target is run with a config path. Ensure the process can write to that file if you rely on token reuse. See `target_airwallex/auth.py` for the token exchange flow.

Example `config.json`:

```json
{
  "api_key": "your-airwallex-api-key",
  "client_id": "your-client-id",
  "sandbox": false
}
```

### API base URLs

`AirwallexSink` picks the base URL in `target_airwallex/client.py`:

| `sandbox` | Base URL |
|-----------|----------|
| `true`    | `https://api-demo.airwallex.com/public_api/v1` |
| `false` or omitted | `https://api.airwallex.com/public_api/v1` |

Confirm paths and versions against the [Airwallex API documentation](https://www.airwallex.com/docs/api).

## Supported streams

### Vendors

Sink class: `VendorSink` (`target_airwallex/sinks.py`). Intended for a Singer stream whose catalog name matches **Vendors** (used for external-id handling in the SDK).

**Behavior**

- **Create:** `POST /{stream_name}` with the body produced by `preprocess_record` (see below).
- **Update:** If the record still has an `id` after preprocessing, the target logs and returns success without calling the vendor update API (Airwallex vendor updates are limited in this target).

**Input → payload mapping**

`preprocess_record` builds an Airwallex-style vendor object from fields such as:

| Input (tap record) | Output field |
|--------------------|--------------|
| `externalId`       | `external_id` |
| `name`             | `name` |
| `email`            | first contact `email` |
| `addresses[0]`     | `address`: `line1` → `street_address`, `city`, `state`, `zipCode` → `postcode`, `country` → `country_code` |
| `customFields`     | merged in as `{ name: value }` entries |

Adjust the tap so records include the keys your integration needs (and valid `addresses` when used).

## Usage

### Running the target

```bash
# Display version
target-airwallex --version

# Display help
target-airwallex --help

# Run with a tap
tap-some-source | target-airwallex --config config.json
```

### Local debugging (VS Code)

The repo includes `.vscode/launch.json` that runs the target with stdin from `.secrets/data.singer` and config `.secrets/config.json`. Point `program` and `cwd` at your machine paths if you use that layout.

## Development

### Setup

```bash
# Install poetry
pipx install poetry

# Install dependencies
poetry install
```

### Running tests

```bash
poetry run pytest
```

### CLI testing

```bash
poetry run target-airwallex --help
```

## License

Apache 2.0
