# Bluefors Control API Gen. 1 — Reference

Sources:
- `manual/Remote-Access-Control-API-Gen.-1-Technical-Reference-version-5.0.pdf`
- `manual/Bluefors-Control-Software-Gen.-1-User-Manual-version-10.0.pdf` (Appendix II)

Applies to Control Software Gen. 1 / API Gen. 1 (document version CS 2.6.1).

## Connection

| Item | Value |
|------|-------|
| HTTPS port | `49098` (LAN / external) |
| HTTP port | `49099` (localhost only) |
| Auth | Query parameter `key=<uuid>` |
| Format | JSON |

Enable in Control Software: **Configuration → API → Enable API + Enable HTTP/WebSocket**.

## HTTP Endpoints

### `GET /system/?key=&prettyprint=1`

Returns system metadata: `system_name`, `sw_version`, `api_version`, `product_type`.

### `GET /values/{branch}/?key=&recursion=-1&style=flat`

Primary snapshot endpoint used by this bot. One request returns the full value tree (flat keys).

| Parameter | Description |
|-----------|-------------|
| `recursion` | `-1` = unlimited depth |
| `style` | `flat` (default) or `tree` |
| `fields` | Semicolon-separated field filter |
| `prettyprint` | `1` for human-readable JSON |

Example:
```http
GET https://host:49098/values/?key=UUID&recursion=-1&style=flat
```

Branch-only (smaller payload):
```http
GET https://host:49098/values/mapper/bf/?key=UUID&recursion=-1&style=flat
```

### `GET /notifications/?key=`

Returns CS built-in notifications (errors, warnings).

### `GET /resources/{path}?key=`

Static UI resources (not used by monitor bot).

## Value Node Structure (flat style)

```json
{
  "mapper.bf.flow": {
    "name": "mapper.bf.flow",
    "type": "Value.Number.Float",
    "content": {
      "latest_valid_value": {
        "value": "1.23",
        "status": "SYNCHRONIZED",
        "date": 1631106116076,
        "outdated": false
      }
    }
  }
}
```

### Sample status codes

| Status | Valid | Meaning |
|--------|-------|---------|
| SYNCHRONIZED | Yes | Device data in sync |
| CHANGED | Yes | Changed locally, not yet written |
| INVALID | No | Read failed |
| DISCONNECTED | No | Device offline |
| INDEPENDENT | Yes | Local-only value |
| QUEUED | Yes | Pending write |

Bot reads `content.latest_valid_value` first; treats `DISCONNECTED` / `INVALID` as data-quality alerts.

## Appendix II Script Variables → Likely API Paths

Confirm paths on your system via snapshot discovery.

| Script var | Device | Description | Likely `value_path` |
|------------|--------|-------------|---------------------|
| `tmixing` | Temp Controller | MXC flange temp | `mapper.bf.tmixing` |
| `tstill` | Temp Controller | Still flange | `mapper.bf.tstill` |
| `t4k` | Temp Controller | 4K flange | `mapper.bf.t4k` |
| `t50k` | Temp Controller | 50K flange | `mapper.bf.t50k` |
| `flow` | Script engine | Flowmeter | `mapper.bf.flow` |
| `cptempwi` | CP2800 | Inlet water temp | `mapper.bf.cptempwi` |
| `cptempwo` | CP2800 | Outlet water temp | `mapper.bf.cptempwo` |
| `cpatempwi` | CPA compressor | Inlet water temp | `mapper.bf.cpatempwi` |
| `cpatempwo` | CPA compressor | Outlet water temp | `mapper.bf.cpatempwo` |
| `cpaerr` | CPA compressor | Error code | `mapper.bf.cpaerr` |
| `cparun` | CPA compressor | Running | `mapper.bf.cparun` |
| `cpastate` | CPA compressor | State | `mapper.bf.cpastate` |
| `p1`–`p6` | MaxiGauge | Pressure channels | `mapper.bf.p1` … |
| `compressor` | Relay | Compressor on/off | `mapper.bf.compressor` |

Multi-unit suffix: `_2`, `_3` (e.g. `cpatempwi_2`).

## Discovery Checklist

1. `GET /system/?key=...` — verify connectivity
2. `GET /values/?recursion=-1&prettyprint=1&key=...` — browse all keys
3. Search for `tmixing`, `cpa`, `flow` in response
4. Update `config.yaml` `value_path` entries
5. Run `alarm-bot check` or `/bluefors paths`

## WebSocket (v2, not implemented)

`wss://host:49098/ws/values/?key=...` supports `read`, `set`, `listen`, `unlisten`.
