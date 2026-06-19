#!/usr/bin/env python3
"""
Boat BLE Scanner
ESP32 BoatSensor + Victron devices -> SignalK via UDP
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import socket
import json
import struct
from bleak import BleakScanner
from victron_ble.devices import detect_device_type

from shared.config import (
    ESP32_MAC, SIGNALK_IP, SIGNALK_PORT, BT_ADAPTER, VICTRON_DEVICES,
)
from shared.logger import get_logger

logger = get_logger("ble_scanner")

# ============================================================
# Persistent UDP socket
# ============================================================
_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_to_signalk(path, value):
    try:
        msg = {"updates": [{"values": [{"path": path, "value": value}]}]}
        _sock.sendto(json.dumps(msg).encode(), (SIGNALK_IP, SIGNALK_PORT))
    except Exception as e:
        logger.warning(f"  SignalK UDP error: {e}")

# ============================================================
# ESP32 parser
# ============================================================
def parse_esp32_data(data: bytes, rssi: int):
    if len(data) < 6:
        return
    temp_raw, hum_raw, mv = struct.unpack_from('<hhH', data, 0)
    temp_k   = temp_raw / 100.0
    temp_c   = temp_k - 273.15
    humidity = hum_raw / 100.0
    voltage  = mv / 1000.0

    logger.info(f"  🌡️  Temp:     {temp_c:.2f}°C")
    logger.info(f"  💧 Humidity: {humidity:.2f}%")
    logger.info(f"  ⚡ Voltage:  {voltage:.3f}V")
    logger.info(f"  📶 RSSI:     {rssi} dBm")

    send_to_signalk("environment.inside.temperature", temp_k)
    send_to_signalk("environment.inside.humidity", humidity / 100.0)
    send_to_signalk("electrical.sensors.esp32.voltage", voltage)
    send_to_signalk("sensors.esp32.rssi", rssi)

# ============================================================
# Victron SmartShunt parser
# ============================================================
def parse_shunt(parsed):
    v   = parsed.get_voltage()
    i   = parsed.get_current()
    soc = parsed.get_soc()
    rem = parsed.get_remaining_mins()
    ah  = parsed.get_consumed_ah()
    tmp = parsed.get_temperature()

    if v is not None:
        logger.info(f"  🔋 Voltage:    {v:.3f}V")
        send_to_signalk("electrical.batteries.house.voltage", v)
    if i is not None:
        logger.info(f"  ⚡ Current:    {i:.2f}A")
        send_to_signalk("electrical.batteries.house.current", i)
    if v is not None and i is not None:
        logger.info(f"  💡 Power:      {v*i:.1f}W")
    if soc is not None:
        logger.info(f"  📊 SOC:        {soc:.1f}%")
        send_to_signalk("electrical.batteries.house.capacity.stateOfCharge", soc / 100.0)
    if rem is not None and rem > 0:
        logger.info(f"  ⏱️  Remaining:  {rem:.0f} mins")
    if ah is not None:
        logger.info(f"  🔄 Consumed:   {ah:.1f}Ah")
    if tmp is not None:
        logger.info(f"  🌡️  Batt Temp:  {tmp:.1f} (raw) -> sending {tmp + 273.15:.2f}K")
        send_to_signalk("electrical.batteries.house.temperature", tmp + 273.15)
    sv = parsed.get_starter_voltage()
    if sv is not None:
        logger.info(f"  🔋 Starter V:  {sv:.2f}V")
        send_to_signalk("electrical.batteries.starter.voltage", sv)

# ============================================================
# Victron MPPT parser
# ============================================================
def parse_mppt(parsed, tag: str):
    bv  = parsed.get_battery_voltage()
    bc  = parsed.get_battery_charging_current()
    sp  = parsed.get_solar_power()
    yt  = parsed.get_yield_today()
    cs  = parsed.get_charge_state()
    err = parsed.get_charger_error()

    if bv is not None:
        logger.info(f"  🔋 Battery V:  {bv:.3f}V")
        send_to_signalk(f"electrical.solar.{tag}.batteryVoltage", bv)
    if bc is not None:
        logger.info(f"  ⚡ Charge A:   {bc:.2f}A")
        send_to_signalk(f"electrical.solar.{tag}.chargingCurrent", bc)
    if bv is not None and bc is not None:
        logger.info(f"  💡 Output W:   {bv*bc:.1f}W")
    if sp is not None:
        logger.info(f"  ☀️  Solar W:    {sp:.0f}W")
        send_to_signalk(f"electrical.solar.{tag}.panelPower", sp)
    if yt is not None:
        logger.info(f"  📈 Yield:      {yt:.0f}Wh today")
    if cs is not None:
        logger.info(f"  🔄 State:      {cs.name}")
        send_to_signalk(f"electrical.solar.{tag}.chargeState", cs.name)
    if err is not None and err.value != 0:
        logger.warning(f"  ⚠️  Error:      {err.name}")

# ============================================================
# Victron main handler
# ============================================================
def parse_victron(mac: str, dev: dict, manufacturer_data: dict, rssi: int):
    try:
        raw_data = manufacturer_data.get(0x02e1)
        if not raw_data:
            return

        device_class = detect_device_type(bytes(raw_data))
        if not device_class:
            return

        device = device_class(dev["key"])
        parsed = device.parse(bytes(raw_data))
        if parsed is None:
            return

        logger.info(f"  📶 RSSI: {rssi} dBm | {device_class.__name__}")

        if dev["type"] == "shunt":
            parse_shunt(parsed)
        elif dev["type"] == "mppt":
            parse_mppt(parsed, dev["tag"])

    except Exception as e:
        logger.warning(f"  Victron parse error: {e}")

# ============================================================
# Async queue for non-blocking BLE callbacks
# ============================================================
data_queue: asyncio.Queue = None

def detection_callback(device, advertisement_data):
    """Lightweight callback — just enqueue, never block."""
    mac = device.address.upper()
    if mac == ESP32_MAC.upper() or mac in VICTRON_DEVICES:
        try:
            data_queue.put_nowait((device, advertisement_data))
        except asyncio.QueueFull:
            logger.warning(f"  ⚠️  Queue full, dropping packet from {mac}")

async def processor():
    """Process BLE packets from the queue asynchronously."""
    while True:
        device, advertisement_data = await data_queue.get()
        mac = device.address.upper()

        if mac == ESP32_MAC.upper():
            logger.info(f"\n📡 BoatSensor1 | RSSI: {advertisement_data.rssi} dBm")
            if advertisement_data.service_data:
                for uuid, data in advertisement_data.service_data.items():
                    if 'abcd' in uuid.lower():
                        parse_esp32_data(data, advertisement_data.rssi)

        elif mac in VICTRON_DEVICES:
            dev = VICTRON_DEVICES[mac]
            logger.info(f"\n🔋 {dev['name']} | {mac}")
            if advertisement_data.manufacturer_data:
                parse_victron(mac, dev,
                              advertisement_data.manufacturer_data,
                              advertisement_data.rssi)

        data_queue.task_done()

# ============================================================
# Main
# ============================================================
async def main():
    global data_queue
    data_queue = asyncio.Queue(maxsize=100)
    logger.info("⛵ Boat BLE Scanner starting...")
    logger.info(f"   ESP32:      {ESP32_MAC}")
    logger.info(f"   Victron:    {len(VICTRON_DEVICES)} devices")
    logger.info(f"   SignalK:    {SIGNALK_IP}:{SIGNALK_PORT}")
    logger.info(f"   BT adapter: {BT_ADAPTER}")
    logger.info("   Press Ctrl+C to stop")

    scanner = BleakScanner(
        detection_callback=detection_callback,
        bluez={"adapter": BT_ADAPTER}
    )

    async with scanner:
        await processor()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scanner stopped.")
        _sock.close()
