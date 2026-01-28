# Iridium SBD Frame Decoder (Single File)

Single-file Python tool to decode Iridium SBD frames produced by your `build_sbdwb_frame_v2` firmware function. Works in both:
- Terminal/command line (prints to stdout)
- Google Colab (file picker + prints to output cell)

The decoder:
- Parses header (version, msg_type, has_payload, needs_ack, low_power)
- Decodes current latitude/longitude (signed int32 big-endian; default scale E7 → degrees)
- Prints latitude/longitude formatted with exactly two digits before the decimal point (zero-padded), keeping the sign
  - Examples: `07.500000`, `-03.250000`, `51.231451`, `123.400000`
- Reads battery code (1 byte) and Iridium timer (2 bytes, big-endian)
- If payload present: parses TLV (type, length, value bytes and bit list), GNSS history pairs (latest-first), and final recording period (hour/minute)
- Reports any trailing or malformed data in an `Errors/Notes` section

> Note on formatting: The integer part is zero-padded to 2 digits. If the integer part exceeds 2 digits (e.g., longitude 123), full digits are printed to avoid truncation.

---

## File Layout

Place this single file in your working directory:

- `sbd_decode_single.py` — the only script you need

---

## Requirements

- Python 3.8+ (no external packages required)

---

## Usage

### 1) Run from terminal

```bash
python sbd_decode_single.py --file payload.sbd
```

Or from a hex string:

```bash
python sbd_decode_single.py --hex 00112233445566778899AABBCCDDEEFF
```

Optional: set a different latitude/longitude scale (default `1e7` for E7). Use `--scale 0` to skip degree conversion and only show encoded integers.

```bash
python sbd_decode_single.py --file payload.sbd --scale 10000000
python sbd_decode_single.py --file payload.sbd --scale 0
```

Make it executable (Unix/macOS):

```bash
chmod +x sbd_decode_single.py
./sbd_decode_single.py --file payload.sbd
```

### 2) Run in Google Colab

- Upload `sbd_decode_single.py` to Colab
- Run the cell:

```python
%run sbd_decode_single.py
```

- A file picker will appear. Select your `.sbd` payload. The decoded result prints in the cell output.

---

## Output Example (text)

```
Raw length: 72
Header byte0=0xA3 byte1=0x01
  version=5 msg_type=3
  has_payload=True needs_ack=False low_power=False
Current coords: lat=51.231451 lon=007.123456 (lat_enc=512314510 lon_enc=71234560)
Battery code: 4
Iridium timer: 327
TLV: type=16 len=8
  value(hex)=f0a1b2c3d4e5f607
GNSS history pairs: 2 (latest-first)
  [0] lat=51.231450 lon=007.123455 (lat_enc=512314500 lon_enc=71234550)
  [1] lat=51.231449 lon=007.123454 (lat_enc=512314490 lon_enc=71234540)
Recording period: hour=1 minute=30
```

Notes:
- `lat`/`lon` show two digits before the decimal (zero-padded if needed).
- `lat_enc`/`lon_enc` are the raw signed int32 values.
- TLV value is printed in hex and decoded into a bit list internally.

---

## Options Summary

- `--file <path>`: Decode from a binary file.
- `--hex <hex-string>`: Decode from a hex string of payload bytes.
- `--scale <float>`: Convert encoded int32 lat/lon to degrees using the given scale (default `1e7`).  
  - `--scale 0` disables conversion and degree formatting.

The script always prints:
- Header fields
- Current coordinates (formatted and encoded)
- Battery code
- Iridium timer
- If present: TLV, GNSS history, recording period
- Any leftover/unknown bytes and decoding notes

---

## Troubleshooting

- “Payload too short”: The input is shorter than the minimal frame length (13 bytes).
- “Non-multiple-of-8 bytes in history section”: History area between TLV and final time isn’t aligned to 8-byte lat/lon pairs—data may be truncated or extra fields added.
- “No payload bit set, but extra bytes present”: The frame indicates no payload, but more bytes were found.

---

## License

This script is provided as-is, without warranty. Use at your own risk for inspecting/decoding frames that conform to your firmware’s `build_sbdwb_frame_v2` layout.
