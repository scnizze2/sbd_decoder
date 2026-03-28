#!/usr/bin/env python3
"""
SBD Frame Decoder for build_sbdwb_frame_v2()

Usage:
    python sbdwb_v2_decoder.py --file example.sbd
    python sbdwb_v2_decoder.py -f msg.sbd --raw-hex
    python sbdwb_v2_decoder.py -f msg.sbd --json
"""

import argparse
import struct
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

# ── TLV Type IDs (must match firmware) ────────────────────────────────────────
TLV_TYPE_BEACON_BIT_ARRAY = 0x01
TLV_TYPE_HISTORICAL_GNSS  = 0x02

# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class GNSSReading:
    latitude:        float
    longitude:       float
    lat_dm:          str
    lon_dm:          str
    timestamp:       int   = None
    timestamp_utc:   str   = ""
    timestamp_local: str   = ""


# ── Coordinate helpers ────────────────────────────────────────────────────────
def encoded_to_decimal(raw_u32):
    """
    Convert the raw uint32 stored by the encoder into signed decimal degrees.

    The encoder does:
        int32_t lat_enc = gnss_lat[i];   // gnss_lat[] is volatile uint32_t*
        frame1[idx++] = (lat_enc >> 24) & 0xFF;
        ...

    So the four bytes are just the big-endian reinterpretation of whatever
    integer lives in gnss_lat[].  We re-interpret the unsigned 32-bit word
    as a signed 32-bit integer (two's complement) to recover the original
    signed value, then divide by 1e7 to get decimal degrees.

    If your firmware stores coordinates as E7 (degrees * 1e7) this is correct.
    If it stores NMEA DDMM*1e5 change the divisor to 1e5 and enable the
    DDMM→decimal block below.
    """
    # re-interpret as signed 32-bit
    if raw_u32 & 0x80000000:
        signed = raw_u32 - 0x100000000
    else:
        signed = raw_u32

    # ── Option A  (most common): plain decimal degrees × 1e7 ─────────────────
    #decimal = signed / 1e6
    #return decimal

    # ── Option B  (NMEA DDMM × 1e5): uncomment if your GPS gives NMEA format ─
    ddmm    = signed / 1e4
    degrees = int(ddmm // 100)
    minutes = ddmm - degrees * 100
    return degrees + minutes / 60.0


def decimal_to_dm(decimal_deg, is_lat):
    """Format decimal degrees as DD°MM.MMMMM'N/S or DDD°MM.MMMMM'E/W."""
    if is_lat:
        direction = 'N' if decimal_deg >= 0 else 'S'
    else:
        direction = 'E' if decimal_deg >= 0 else 'W'
    d = abs(decimal_deg)
    deg  = int(d)
    mins = (d - deg) * 60.0
    if is_lat:
        return f"{deg:02d}°{mins:08.5f}'{direction}"
    else:
        return f"{deg:03d}°{mins:08.5f}'{direction}"


# ── GNSS record parser ────────────────────────────────────────────────────────
def parse_gnss_record(data, offset, with_timestamp):
    """
    Parse one GNSS record (8 bytes without timestamp, 12 with).
    Returns (GNSSReading, new_offset).
    """
    need = 12 if with_timestamp else 8
    if offset + need > len(data):
        raise ValueError(
            f"Corrupt SBD: need {need} bytes at offset {offset}, "
            f"only {len(data)-offset} available"
        )

    # Read as unsigned big-endian 32-bit then convert to signed decimal
    raw_lat = struct.unpack(">I", data[offset    :offset + 4])[0]
    raw_lon = struct.unpack(">I", data[offset + 4:offset + 8])[0]
    lat_deg = encoded_to_decimal(raw_lat)
    lon_deg = encoded_to_decimal(raw_lon)

    timestamp, ts_utc, ts_local = None, "", ""
    if with_timestamp:
        raw_ts    = struct.unpack(">I", data[offset + 8:offset + 12])[0]
        timestamp = raw_ts
        try:
            dt_utc   = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            dt_local = datetime.fromtimestamp(timestamp)
            ts_utc   = dt_utc  .strftime('%Y-%m-%d %H:%M:%S UTC')
            ts_local = dt_local.strftime('%Y-%m-%d %H:%M:%S (local)')
        except (OSError, OverflowError, ValueError):
            ts_utc   = f"<invalid unix ts {timestamp}>"
            ts_local = ts_utc

    return GNSSReading(
        latitude        = lat_deg,
        longitude       = lon_deg,
        lat_dm          = decimal_to_dm(lat_deg, is_lat=True),
        lon_dm          = decimal_to_dm(lon_deg, is_lat=False),
        timestamp       = timestamp,
        timestamp_utc   = ts_utc,
        timestamp_local = ts_local,
    ), offset + need


# ── Historical-GNSS TLV length decoder ───────────────────────────────────────
def read_hist_tlv_length(data, idx):
    """
    The encoder writes the byte-length of the historical block as:
        if msg_length >= 255:
            frame1[idx++] = 255;
            frame1[idx++] = (uint8_t)(msg_length - 255);
        else:
            frame1[idx++] = (uint8_t)msg_length;

    Returns (total_byte_length, new_idx).
    """
    if idx >= len(data):
        raise ValueError("Unexpected end of frame reading historical TLV length")

    first_byte = data[idx]; idx += 1

    if first_byte == 255:
        # two-byte encoding
        if idx >= len(data):
            raise ValueError("Unexpected end of frame reading historical TLV length (2nd byte)")
        second_byte = data[idx]; idx += 1
        total_len = 255 + second_byte
    else:
        total_len = first_byte

    return total_len, idx


# ── Main frame decoder ────────────────────────────────────────────────────────
def decode_frame(data: bytes) -> dict:
    if len(data) < 15:
        raise ValueError(
            f"Frame too short: {len(data)} bytes (minimum is 15)"
        )

    idx = 0

    # ── Byte 0: version + msg_type ────────────────────────────────────────────
    byte0   = data[idx]; idx += 1
    version  = (byte0 >> 5) & 0x07
    msg_type =  byte0       & 0x1F

    # ── Byte 1: flags ─────────────────────────────────────────────────────────
    byte1      = data[idx]; idx += 1
    has_payload = (byte1 & 0x01) != 0
    needs_ack   = (byte1 & 0x02) != 0
    low_power   = (byte1 & 0x04) != 0

    # ── Latest GNSS fix (no timestamp) ───────────────────────────────────────
    main_gnss, idx = parse_gnss_record(data, idx, with_timestamp=False)

    # ── Battery code (1 byte) ─────────────────────────────────────────────────
    bat_code = data[idx]; idx += 1

    # ── Iridium timer (2 bytes, big-endian) ───────────────────────────────────
    iri_timer = (data[idx] << 8) | data[idx + 1]; idx += 2

    # ── Optional payload TLVs ─────────────────────────────────────────────────
    beacon_bits = None
    historical  = []
    tlv_log     = []          # list of dicts for display/debug

    if has_payload:
        while idx < len(data):

            # need at least 1 byte for the TLV type tag
            if idx >= len(data):
                break
            tlv_type = data[idx]; idx += 1

            # ── Beacon Bit Array TLV ──────────────────────────────────────────
            if tlv_type == TLV_TYPE_BEACON_BIT_ARRAY:
                # Standard single-byte length
                if idx >= len(data):
                    break
                tlv_len = data[idx]; idx += 1

                if idx + tlv_len > len(data):
                    raise ValueError(
                        f"Beacon TLV length {tlv_len} exceeds remaining frame at offset {idx}"
                    )
                beacon_bits = data[idx:idx + tlv_len]
                idx += tlv_len
                tlv_log.append({
                    "type": tlv_type,
                    "length_bytes": tlv_len,
                    "label": "BEACON_BIT_ARRAY",
                })

            # ── Historical GNSS TLV ───────────────────────────────────────────
            elif tlv_type == TLV_TYPE_HISTORICAL_GNSS:
                # Encoder uses a non-standard 1-or-2-byte length field
                byte_len, idx = read_hist_tlv_length(data, idx)

                if byte_len % 12 != 0:
                    raise ValueError(
                        f"Historical GNSS TLV byte-length {byte_len} is not a "
                        f"multiple of 12 (each record is 12 bytes)"
                    )
                n_readings = byte_len // 12
                tlv_log.append({
                    "type": tlv_type,
                    "length_bytes": byte_len,
                    "n_readings": n_readings,
                    "label": "HISTORICAL_GNSS",
                })

                for _ in range(n_readings):
                    if idx + 12 > len(data):
                        print(
                            "WARNING: frame truncated inside historical GNSS block",
                            file=sys.stderr
                        )
                        break
                    reading, idx = parse_gnss_record(data, idx, with_timestamp=True)
                    historical.append(reading)

            # ── Unknown / future TLV  (single-byte length, skip payload) ─────
            else:
                if idx >= len(data):
                    break
                tlv_len = data[idx]; idx += 1
                tlv_log.append({
                    "type": tlv_type,
                    "length_bytes": tlv_len,
                    "label": f"UNKNOWN(0x{tlv_type:02X})",
                })
                print(
                    f"WARNING: unknown TLV type 0x{tlv_type:02X}, "
                    f"skipping {tlv_len} bytes",
                    file=sys.stderr
                )
                idx += tlv_len

    return {
        "byte0":       byte0,
        "version":     version,
        "msg_type":    msg_type,
        "has_payload": has_payload,
        "needs_ack":   needs_ack,
        "low_power":   low_power,
        "main_gnss":   main_gnss,
        "bat_code":    bat_code,
        "iri_timer":   iri_timer,
        "beacon_bits": beacon_bits,
        "historical":  historical if historical else None,
        "tlv_log":     tlv_log,
    }


# ── Pretty printer ────────────────────────────────────────────────────────────
def print_frame(frame: dict, filename: str = None):
    sep = "=" * 62
    print(sep)
    title = "Decoded SBD V2 Frame"
    if filename:
        title += f"  ←  {filename}"
    print(title)
    print(sep)

    print("[HEADER]")
    print(f"  byte0       : 0x{frame['byte0']:02X}")
    print(f"  Version     : {frame['version']}")
    print(f"  Msg type    : {frame['msg_type']}")
    print(f"  Has payload : {frame['has_payload']}")
    print(f"  Needs ACK   : {frame['needs_ack']}")
    print(f"  Low power   : {frame['low_power']}")

    g = frame['main_gnss']
    print("\n[LATEST GNSS FIX]")
    print(f"  Latitude    : {g.latitude:.7f}  ({g.lat_dm})")
    print(f"  Longitude   : {g.longitude:.7f}  ({g.lon_dm})")
    print(f"  Google Maps : https://maps.google.com/?q={g.latitude},{g.longitude}")

    print("\n[STATUS]")
    print(f"  Battery code: {frame['bat_code']}  (0x{frame['bat_code']:02X})")
    print(f"  IRI timer   : {frame['iri_timer']} sec")

    if frame['has_payload']:
        print("\n[PAYLOAD TLVs]")
        for i, t in enumerate(frame['tlv_log']):
            print(f"  TLV #{i+1}: type=0x{t['type']:02X}  label={t['label']}  "
                  f"length={t['length_bytes']} bytes"
                  + (f"  readings={t['n_readings']}" if 'n_readings' in t else ""))

        if frame['beacon_bits'] is not None:
            bb = frame['beacon_bits']
            print(f"\n  Beacon Bit Array ({len(bb)} bytes): {bb.hex()}")
            bits = ''.join(f'{b:08b}' for b in bb)
            print(f"  Binary: {bits}")

        if frame['historical']:
            hist = frame['historical']
            print(f"\n  Historical GNSS readings: {len(hist)}")
            for i, r in enumerate(hist):
                print(f"\n   #{i+1}")
                print(f"      Latitude    : {r.latitude:.7f}  ({r.lat_dm})")
                print(f"      Longitude   : {r.longitude:.7f}  ({r.lon_dm})")
                print(f"      Timestamp   : {r.timestamp}")
                print(f"      UTC         : {r.timestamp_utc}")
                print(f"      Local       : {r.timestamp_local}")
                print(f"      Google Maps : https://maps.google.com/?q={r.latitude},{r.longitude}")

    print(sep)


# ── Hex dump helper ───────────────────────────────────────────────────────────
def hex_dump(data: bytes):
    print(f"Raw hex ({len(data)} bytes):")
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hex_part  = ' '.join(f'{b:02X}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f"  {i:04X}:  {hex_part:<47}  {ascii_part}")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Decode SBD frames built by build_sbdwb_frame_v2()",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--file",    "-f", required=True, help="Binary SBD frame file")
    parser.add_argument("--raw-hex", action="store_true",  help="Print hex dump before decoding")
    parser.add_argument("--json",    action="store_true",  help="Output as JSON")
    args = parser.parse_args()

    try:
        with open(args.file, "rb") as fh:
            data = fh.read()
    except OSError as e:
        print(f"ERROR opening file: {e}", file=sys.stderr)
        sys.exit(1)

    if args.raw_hex:
        hex_dump(data)

    try:
        frame = decode_frame(data)
    except ValueError as e:
        print(f"DECODE ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        import json
        def _default(obj):
            if isinstance(obj, GNSSReading): return asdict(obj)
            if isinstance(obj, bytes):       return obj.hex()
            raise TypeError(f"Not serialisable: {type(obj)}")
        print(json.dumps(frame, indent=2, default=_default))
    else:
        print_frame(frame, filename=args.file)


if __name__ == "__main__":
    main()