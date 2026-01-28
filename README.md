# Iridium SBD Frame Decoder (Single File, DDMM.mmmm conversion)

Single-file Python tool to decode Iridium SBD frames produced by your `build_sbdwb_frame_v2` firmware function. This version converts coordinates from DDMM.mmmm format to decimal degrees using:

decimal_degrees = degrees + (minutes / 60)

The encoded int32 latitude/longitude are interpreted as DDMM.mmmm values (with a configurable scale), and the sign is applied after conversion (negative for S/W).

Works in:
- Terminal/command line (prints to stdout)
- Google Colab (file picker + prints to output cell)

---

## File

- `sbd_decode_single.py` — the only script you need

---

## Requirements

- Python 3.8+ (no external packages required)

---

## Usage

### Run from terminal

```bash
python sbd_decode_single.py --file payload.sbd
```

Or decode from a hex string:

```bash
python sbd_decode_single.py --hex 00112233445566778899AABBCCDDEEFF
```

Coordinate scaling (DDMM.mmmm):
- `--ddmm-scale` sets how the encoded int32 maps to DDMM.mmmm.
- Default is `1e4`, meaning `5130.1234` is stored as `51301234` in the payload.

Examples:
```bash
# Default scale (DDMM.mmmm with 4 decimals in minutes)
python sbd_decode_single.py --file payload.sbd --ddmm-scale 10000

# Custom scale (if your minutes have a different precision)
python sbd_decode_single.py --file payload.sbd --ddmm-scale 1000
```

Make it executable (Unix/macOS):
```bash
chmod +x sbd_decode_single.py
./sbd_decode_single.py --file payload.sbd
```

### Run in Google Colab

- Upload `sbd_decode_single.py` to Colab
- Run the cell:

```python
%run sbd_decode_single.py
```

- A file picker will appear. Select your `.sbd` payload. The decoded result prints in the cell output.

---

## What it decodes

- Header: `version`, `msg_type`, `has_payload`, `needs_ack`, `low_power`
- Current coordinates:
  - Encoded signed int32 (big-endian)
  - Converted from DDMM.mmmm to decimal degrees: `degrees + minutes/60`
  - Formatted with exactly two digits before the decimal point (zero‑padded when fewer), sign preserved
    - Examples: `07.500000`, `-03.250000`, `51.231451`
    - If the integer part exceeds two digits (e.g., `123.400000`), the full digits are shown to avoid truncation
- Battery code: 1 byte
- Iridium timer: 2 bytes, big-endian
- If payload is present:
  - TLV: type (1 byte), length (1 byte), value (length bytes)
  - GNSS history: zero or more lat/lon pairs (8 bytes each), latest-first
  - Final 2 bytes: recording period hour and minute
- Any extra or misaligned bytes are reported under `Errors/Notes`

---

## Example output (text)

```
Raw length: 72
Header byte0=0xA3 byte1=0x01
  version=5 msg_type=3
  has_payload=True needs_ack=False low_power=False
Current coords: lat=51.502056 lon=007.332387 (lat_enc=51301234 lon_enc=7339387)
Battery code: 4
Iridium timer: 327
TLV: type=16 len=8
  value(hex)=f0a1b2c3d4e5f607
GNSS history pairs: 2 (latest-first)
  [0] lat=51.502000 lon=007.332300 (lat_enc=51300000 lon_enc=7332300)
  [1] lat=51.501500 lon=007.332100 (lat_enc=51299000 lon_enc=7332100)
Recording period: hour=1 minute=30
```

Here:
- `lat_enc`/`lon_enc` are raw signed int32 values from the payload
- Conversion uses DDMM.mmmm → decimal degrees (`degrees + minutes/60`)
- Formatting enforces two digits before the decimal unless the integer part is ≥ 100

---

## CLI options

- `--file <path>`: Decode from a binary `.sbd` payload file
- `--hex <hex-string>`: Decode from a hex string of payload bytes
- `--ddmm-scale <float>`: Scale that converts the encoded int32 into DDMM.mmmm  
  - Default `10000` (DDMM.mmmm with 4 decimal places in minutes)
  - Example: `51301234` / `10000` → `5130.1234` → `51 + 30.1234/60`

---

## Troubleshooting

- “Payload too short”: Input is shorter than minimal frame length (13 bytes)
- “Non-multiple-of-8 bytes in history section”: History region isn’t aligned to 8-byte lat/lon pairs; data may be truncated or additional fields present
- “No payload bit set, but extra bytes present”: The frame indicates no payload, but more bytes were found

---

## License

Provided as-is, without warranty. Use at your own risk for frames that follow your `build_sbdwb_frame_v2` layout.
