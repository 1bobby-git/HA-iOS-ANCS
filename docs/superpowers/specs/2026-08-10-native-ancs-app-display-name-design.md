# Native ANCS App Display Name Design

Date: 2026-08-10

## Context

The firmware currently derives `app_name` from a static App Identifier table in
`mqtt_app_name.c`. That table cannot cover every current and future iOS app, and
some localized names in it are already damaged by character encoding. Apple
ANCS provides the installed app's display name directly through the Control
Point `Get App Attributes` command, so the relay can resolve the name without an
external API, API key, or mirrored app catalog.

The Home Assistant companion integration also exposes a dedicated
`published_at_ms` sensor named "Published at device uptime". The MQTT field is
useful in the raw notification contract, but the dedicated entity is not useful
to the user and should be removed cleanly on upgrade.

## Goals

- Resolve an app display name natively from the connected iPhone through ANCS.
- Publish one complete notification event rather than an initial event followed
  by an enrichment update.
- Cache resolved names for the current ANCS connection session.
- Keep existing static mappings as a compatibility fallback, then fall back to
  the App Identifier when no friendly name is available.
- Ensure app-name lookup failure never discards otherwise valid notification
  details.
- Remove the dedicated `published_at_ms` Home Assistant sensor and delete its
  existing entity-registry entry during migration.
- Preserve MQTT ownership, topics, devices, and entities as separate from the
  `iOS ANCS` companion integration.

## Non-goals

- No Apple Search API, third-party API, API key, repository-hosted app catalog,
  or periodic catalog synchronization.
- No change to the MQTT base topic or Home Assistant MQTT device.
- No removal of `published_at_ms` from the MQTT payload, raw notification
  attributes, or event data.
- No persistent app-name cache across BLE sessions. Apple recommends treating
  app attributes as session-scoped.
- No second MQTT publication solely to enrich `app_name`.

## Selected Approach

Use a two-stage request for the first notification from each App Identifier in
an ANCS session:

1. Fetch the notification attributes as today.
2. If the App Identifier has a cached native display name, copy it into the
   notification and publish.
3. Otherwise request App Attribute `DisplayName` through the ANCS Control Point.
4. Parse the Data Source response across arbitrary BLE fragments.
5. Cache a non-empty result for the current session, attach it to the pending
   notification, and publish exactly once.
6. If the native lookup fails or returns an empty value, use the static mapping;
   if the map has no friendly value, use the App Identifier.

This adds one Control Point round trip for the first notification from an app in
each connection session. Later notifications from that app use the session
cache and retain the current latency.

Publishing immediately and then republishing with a name was rejected because
Home Assistant could surface two events for one iPhone notification. Removing
the static table immediately was rejected because a temporary ANCS attribute
failure would unnecessarily regress known app names.

## Protocol Layer

The ANCS protocol component will add explicit constants and typed APIs for:

- Command ID `1`: Get App Attributes.
- App Attribute ID `0`: Display Name.
- A request builder containing the command byte, a null-terminated App
  Identifier, and the Display Name attribute ID.
- A dedicated App Attributes response parser.

The parser will validate:

- The response Command ID.
- A null-terminated response App Identifier that exactly matches the requested
  identifier.
- Attribute tuple framing: attribute ID, little-endian 16-bit length, and value.
- Display Name presence and bounded storage.

The parser must accept every fragmentation boundary, including one byte per
fragment. It will null-terminate the stored UTF-8 bytes, record truncation, and
return the existing `MORE`, `COMPLETE`, or `ERROR` result contract. A mismatched
App Identifier or malformed sequence is an error and must not populate the
cache.

`ancs_notification_t` will gain bounded `app_name` storage and an
`app_name_truncated` flag so the resolved name travels with the notification
rather than being recomputed only in the MQTT serializer.

## Client State Machine

The worker will explicitly track whether the active Control Point operation is
fetching notification attributes or app attributes. Only one operation may be
active because ANCS Data Source responses are serialized through the same
characteristic.

Notification processing becomes:

1. Pop a notification event and request its notification attributes.
2. On complete parsing, examine `app_id`.
3. On an app-cache hit, copy the cached name and finalize publication.
4. On a miss, keep the completed notification as the active publication and
   issue an App Attributes request.
5. On app-response completion, cache the native name and finalize publication.

The existing notification UID cache for removed events remains independent from
the new app-name cache. A removed event received while either stage is active
continues to cancel/drain the active notification before processing the next
queue item.

The app-name cache will be bounded and use the existing least-recently-used age
pattern. Cache keys are exact App Identifiers. It is cleared by
`reset_worker_session`, which already runs on generation changes and connection
reset, so names cannot leak across ANCS sessions.

## Error Handling

Notification attribute errors keep the current behavior: retry once, publish an
incomplete/error payload if recovery fails, and recover the ANCS data stream.

App-name lookup errors are enrichment failures, not notification failures:

- Retry the app request once when the connection remains ready.
- Finalize `app_name` with the static map or App Identifier after an empty,
  malformed, mismatched, timed-out, or failed response.
- Publish the already complete notification once with no notification-level
  error.
- Recover the BLE data stream after parser or timeout failures when stream
  alignment is no longer trustworthy.
- Never store empty, mismatched, or failed native results in the app cache.

If the App Identifier itself is empty, skip the native request and finalize with
an empty app name. Memory allocation is not required for cache entries or parser
buffers; all storage remains bounded in the worker context.

## MQTT Payload

`mqtt_payload_build_notification` will prefer the `app_name` carried by the
notification. If it is empty, it applies the existing static lookup. The lookup
still returns the App Identifier for an unknown app, preserving the current
safe fallback and JSON schema.

The existing `app_name` JSON field remains unchanged, so the Home Assistant
runtime and its app-name sensor need no payload-schema migration.

## Home Assistant Sensor Removal

The companion integration will:

- Remove `published_at_ms` and `received_at_ms` from `SENSOR_DESCRIPTIONS`.
- Remove their translation entries from `strings.json`, English, and Korean
  translations.
- Bump the config-entry version.
- During migration, inspect only entities belonging to the current config entry
  and remove integration-owned sensors whose unique IDs end in
  `:sensor:published_at_ms` or `:sensor:received_at_ms`.

The migration must not remove MQTT entities, similarly named foreign entities,
raw notification attributes, event data, or stored notification fields.

## Test Strategy

Protocol tests will be written before implementation and will cover:

- Exact Get App Attributes request bytes.
- Complete Display Name response parsing.
- Every two-fragment boundary and one-byte fragments.
- UTF-8 name preservation, empty names, truncation, malformed framing, wrong
  command, and mismatched App Identifier.

Firmware payload tests will prove:

- A native `app_name` overrides the static map.
- An empty native name uses the static mapping.
- An unknown app falls back to its App Identifier.
- Existing payload fields and escaping remain unchanged.

Client behavior will be factored so unit-testable state/cache decisions cover:

- First app notification requests the native name.
- Subsequent same-session notifications use the cache.
- Session reset clears the cache.
- App lookup failure still finalizes a complete notification once.

Home Assistant tests will prove:

- Neither uptime marker is created as a companion sensor.
- Migration removes both old companion uptime registry entries and leaves MQTT
  entities untouched.
- Raw notification attributes still contain `published_at_ms` and
  `received_at_ms` when provided.

## Release and Verification

After targeted RED/GREEN tests, verification will include the firmware host/unit
test suite, Home Assistant pytest suite, repository release validators,
Hassfest/HACS checks where configured, and firmware builds for supported
installer targets. Versions, installer manifests, binary filenames, checksums,
tag, and GitHub release assets must agree before publication is reported as
complete.

Static and simulated verification will be reported separately from physical
proof. End-to-end success requires flashing the produced firmware, reconnecting
the iPhone, sending a fresh non-Home-Assistant notification, and observing a
native localized `app_name` in the MQTT payload and `iOS ANCS` companion sensor.
