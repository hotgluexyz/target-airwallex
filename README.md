# target-airwallex

`target-airwallex` is a Singer target for [Airwallex](https://www.airwallex.com/), built with the Hotglue Singer SDK.

## Overview

This target syncs data to Airwallex over their REST API. It uses a generic sink: each Singer stream name is sent to `POST /{stream}` for creates and `PATCH /{stream}/{id}` when a record includes an `id` (update).

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
| `api_key`   | Your Airwallex API key |
| `client_id` | Your Airwallex client ID (used when obtaining an access token) |

The target’s config schema currently marks `api_key` as required; `client_id` is required by the authenticator at runtime—ensure both are present in your config.

### Optional settings

| Setting   | Description |
|-----------|-------------|
| `sandbox` | When `true`, uses the production API host URL configured in code; when `false` or omitted, uses the demo API host. Adjust to match how you deploy. |

Token-related fields (`access_token`, `expires_at`, etc.) may be supplied by your tap or initial auth flow so the target can refresh or reuse tokens. See `target_airwallex/auth.py` for the exact behavior.

Create a `config.json` file (example—add fields your environment needs):

```json
{
  "api_key": "your-airwallex-api-key",
  "client_id": "your-client-id",
  "sandbox": false
}
```

### API base URLs

The sink selects a base URL from the `sandbox` flag:

- **`sandbox: true`**: `https://api.airwallex.com/public_api/v1/`
- **`sandbox: false` (default)**: `https://api-demo.airwallex.com/public_api/v1`

Confirm paths and hosts against the [Airwallex API documentation](https://www.airwallex.com/docs/api) for your integration.

## Supported streams

There is no fixed list of streams in code: any stream name from the tap is used as the API path segment. Payload shape must match what the Airwallex API expects for that resource.

**Create:** records without an `id` (or with `id` removed before send, depending on stream) are sent with `POST /{stream_name}` as a JSON array with one element.

**Update:** records that still have an `id` after processing use `PATCH /{stream_name}/{id}` with the record body.

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
