#!/usr/bin/env python3
"""
Single-file Iridium SBD decoder for frames built by build_sbdwb_frame_v2.
- Run in terminal: python sbd_decode_single.py --file payload.sbd
- Or in Google Colab: just run this file; it will open a file picker and print results.
"""

import argparse
from typing import Any, Dict, List, Optional

def _bytes_to_bits_msb_first(b: bytes) -> List[int]:
    bits = []
    for by in b:
        for i in range(7, -1, -1):
            bits.append((by >> i) & 1)
    return bits

def _to_degrees(enc: int, scale: Optional[float]) -> Optional[float]:
    if scale is None:
        return None
    return enc / scale

def _format_deg(value: Optional[float], width: int = 2, decimals: int = 6) -> Optional[str]:
    """
    Format degrees with at least `width` digits before '.', zero-padded when fewer.
    Keeps minus sign. If integer part has more than `width` digits, show all.
    Examples: 7.5 -> '07.500000', -3.25 -> '-03.250000', 51.231451 -> '51.231451', 123.4 -> '123.400000'
    """
    if value is None:
        return None
    sgn = '-' if value < 0 else ''
    abs_val = abs(value)
    rounded = round(abs_val, decimals)
    int_part = int(rounded)
    frac_part = rounded - int_part
    int_str = f"{int_part:0{width}d}" if int_part < 10**width else str(int_part)
    frac_str = f"{frac_part:.{decimals}f}".split('.')[1]
    return f"{sgn}{int_str}.{frac_str}"

def decode_sbd_bytes(
    data: bytes,
    scale: Optional[float] = 1e7,
    lat_width: int = 2,
    lon_width: int = 2,
    decimals: int = 6
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "raw_len": len(data),
        "header": {},
        "current": {},
        "battery": {},
        "iri_timer": {},
        "payload_present": False,
        "tlv": {},
        "gnss_history": [],
        "recording_period": {},
        "unknown_tail": b"",
        "errors": []
    }

    idx = 0
    def require(n: int) -> bool:
        if idx + n > len(data):
            result["errors"].append(f"Truncated: need {n} bytes at idx {idx}, only {len(data)-idx} available.")
            return False
        return True

    if len(data) < 13:
        result["errors"].append(f"Payload too short: {len(data)} bytes; expected at least 13.")
        return result

    # Header
    if not require(2): return result
    byte0 = data[idx]; idx += 1
    byte1 = data[idx]; idx += 1
    version = (byte0 >> 5) & 0x07
    msg_type = byte0 & 0x1F
    has_payload = bool(byte1 & 0x01)
    needs_ack = bool((byte1 >> 1) & 0x01)
    low_power = bool((byte1 >> 2) & 0x01)
    result["header"] = {
        "byte0": byte0,
        "byte1": byte1,
        "version": version,
        "msg_type": msg_type,
        "has_payload": has_payload,
        "needs_ack": needs_ack,
        "low_power": low_power,
    }
    result["payload_present"] = has_payload

    # Current coordinates
    if not require(8): return result
    lat0 = int.from_bytes(data[idx:idx+4], byteorder="big", signed=True); idx += 4
    lon0 = int.from_bytes(data[idx:idx+4], byteorder="big", signed=True); idx += 4
    lat0_deg = _to_degrees(lat0, scale)
    lon0_deg = _to_degrees(lon0, scale)
    result["current"] = {
        "lat_enc": lat0,
        "lon_enc": lon0,
        "lat_deg": lat0_deg,
        "lon_deg": lon0_deg,
        "lat_deg_fmt": _format_deg(lat0_deg, width=lat_width, decimals=decimals),
        "lon_deg_fmt": _format_deg(lon0_deg, width=lon_width, decimals=decimals),
    }

    # Battery
    if not require(1): return result
    bat_code = data[idx]; idx += 1
    result["battery"] = {"code": bat_code}

    # Iridium timer
    if not require(2): return result
    iri_timer = int.from_bytes(data[idx:idx+2], byteorder="big", signed=False); idx += 2
    result["iri_timer"] = {"value": iri_timer}

    # Optional payload
    if has_payload:
        if not require(2): return result
        tlv_type = data[idx]; idx += 1
        tlv_len = data[idx]; idx += 1
        if not require(tlv_len): return result
        tlv_value = data[idx:idx+tlv_len]; idx += tlv_len
        result["tlv"] = {
            "type": tlv_type,
            "length": tlv_len,
            "value_bytes_hex": tlv_value.hex(),
            "value_bits_msb_first": _bytes_to_bits_msb_first(tlv_value)
        }

        rem = len(data) - idx
        if rem < 2:
            result["errors"].append("Payload present but missing final recording period (2 bytes).")
            result["unknown_tail"] = data[idx:]
            return result

        tail_for_history = rem - 2
        history_pairs = tail_for_history // 8
        leftover = tail_for_history % 8

        gnss_history: List[Dict[str, Any]] = []
        for _ in range(history_pairs):
            if not require(8):
                result["errors"].append("Truncated inside GNSS history.")
                break
            lat_enc = int.from_bytes(data[idx:idx+4], byteorder="big", signed=True); idx += 4
            lon_enc = int.from_bytes(data[idx:idx+4], byteorder="big", signed=True); idx += 4
            lat_deg = _to_degrees(lat_enc, scale)
            lon_deg = _to_degrees(lon_enc, scale)
            gnss_history.append({
                "lat_enc": lat_enc,
                "lon_enc": lon_enc,
                "lat_deg": lat_deg,
                "lon_deg": lon_deg,
                "lat_deg_fmt": _format_deg(lat_deg, width=lat_width, decimals=decimals),
                "lon_deg_fmt": _format_deg(lon_deg, width=lon_width, decimals=decimals),
            })
        result["gnss_history"] = gnss_history

        if not require(2): return result
        hour = data[idx]; idx += 1
        minute = data[idx]; idx += 1
        result["recording_period"] = {"hour": hour, "minute": minute}

        if leftover != 0:
            start_leftover = len(data) - (2 + leftover)
            end_leftover = len(data) - 2
            result["unknown_tail"] = data[start_leftover:end_leftover]
            result["errors"].append(f"Non-multiple-of-8 bytes in history section: {leftover} leftover bytes.")
        else:
            result["unknown_tail"] = b""
    else:
        if idx < len(data):
            result["unknown_tail"] = data[idx:]
            if len(result["unknown_tail"]) > 0:
                result["errors"].append(f"No payload bit set, but {len(result['unknown_tail'])} extra bytes present.")

    return result

def pretty_print_decoded(decoded: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"Raw length: {decoded.get('raw_len')}")
    h = decoded.get("header", {})
    lines.append(f"Header byte0=0x{h.get('byte0',0):02X} byte1=0x{h.get('byte1',0):02X}")
    lines.append(f"  version={h.get('version')} msg_type={h.get('msg_type')}")
    lines.append(f"  has_payload={h.get('has_payload')} needs_ack={h.get('needs_ack')} low_power={h.get('low_power')}")

    cur = decoded.get("current", {})
    lines.append(f"Current coords: lat={cur.get('lat_deg_fmt')} lon={cur.get('lon_deg_fmt')} "
                 f"(lat_enc={cur.get('lat_enc')} lon_enc={cur.get('lon_enc')})")

    bat = decoded.get("battery", {})
    lines.append(f"Battery code: {bat.get('code')}")

    iri = decoded.get("iri_timer", {})
    lines.append(f"Iridium timer: {iri.get('value')}")

    if decoded.get("payload_present"):
        tlv = decoded.get("tlv", {})
        lines.append(f"TLV: type={tlv.get('type')} len={tlv.get('length')}")
        lines.append(f"  value(hex)={tlv.get('value_bytes_hex')}")

        hist = decoded.get("gnss_history", [])
        lines.append(f"GNSS history pairs: {len(hist)} (latest-first)")
        for i, p in enumerate(hist):
            lines.append(f"  [{i}] lat={p.get('lat_deg_fmt')} lon={p.get('lon_deg_fmt')} "
                         f"(lat_enc={p.get('lat_enc')} lon_enc={p.get('lon_enc')})")

        rp = decoded.get("recording_period", {})
        lines.append(f"Recording period: hour={rp.get('hour')} minute={rp.get('minute')}")

    tail = decoded.get("unknown_tail", b"")
    if tail:
        lines.append(f"Unknown tail bytes ({len(tail)}): {tail.hex()}")

    errs = decoded.get("errors", [])
    if errs:
        lines.append("Errors/Notes:")
        for e in errs:
            lines.append(f"  - {e}")

    return "\n".join(lines)

def _decode_file(path: str, scale: Optional[float] = 1e7) -> Dict[str, Any]:
    with open(path, "rb") as f:
        data = f.read()
    return decode_sbd_bytes(data, scale=scale, lat_width=2, lon_width=2, decimals=6)

def main():
    # Try Colab file picker if available and no CLI args
    import sys
    use_colab = False
    input_bytes: Optional[bytes] = None
    try:
        if len(sys.argv) == 1:
            import google.colab  # type: ignore
            from google.colab import files  # type: ignore
            use_colab = True
            print("Select your SBD payload file...")
            uploaded = files.upload()
            for fname in uploaded.keys():
                input_bytes = uploaded[fname]
                print(f"Decoding: {fname}")
                decoded = decode_sbd_bytes(input_bytes, scale=1e7, lat_width=2, lon_width=2, decimals=6)
                print(pretty_print_decoded(decoded))
            return
    except Exception:
        use_colab = False

    # Simple CLI for terminal use
    p = argparse.ArgumentParser(description="Decode Iridium SBD payloads (single-file script).")
    p.add_argument("--file", "-f", help="Path to a binary SBD payload file.")
    p.add_argument("--hex", "-x", help="Hex string representing the payload bytes.")
    p.add_argument("--scale", type=float, default=1e7, help="Lat/Lon scale factor (default: 1e7). Set 0 to disable degree conversion.")
    args = p.parse_args()

    scale = None if args.scale == 0 else args.scale

    if args.file:
        decoded = _decode_file(args.file, scale=scale)
        print(pretty_print_decoded(decoded))
    elif args.hex:
        payload = bytes.fromhex(args.hex.strip())
        decoded = decode_sbd_bytes(payload, scale=scale, lat_width=2, lon_width=2, decimals=6)
        print(pretty_print_decoded(decoded))
    else:
        p.print_help()

if __name__ == "__main__":
    main()