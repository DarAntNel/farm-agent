"""Tests for the sensor slice.

Covers the two serial sensors (valid / out-of-range / missing / non-numeric /
calibration / transport-down), the two direct sensors via injected fakes, the
:class:`SensorHub`, and registry lookups. No hardware is touched: serial sensors
use :class:`tests.fakes.FakeSerialTransport` and direct sensors use the injected
:class:`FakeI2CChannel` / :class:`FakeOneWireDevice` fakes.
"""

from __future__ import annotations

import pytest

from farm_agent.registry import sensor_registry
from farm_agent.sensors import SensorHub
from farm_agent.sensors.ads1115_soil import Ads1115SoilSensor
from farm_agent.sensors.ds18b20 import Ds18b20Sensor
from farm_agent.sensors.soil_moisture import SoilMoistureSensor
from farm_agent.sensors.temperature import TemperatureSensor
from tests.fakes import FakeI2CChannel, FakeOneWireDevice, FakeSerialTransport


# --------------------------------------------------------------------------- #
# SoilMoistureSensor (serial)
# --------------------------------------------------------------------------- #
def test_soil_valid(transport) -> None:
    sensor = SoilMoistureSensor("soil_1", "Soil", transport)
    reading = sensor.read()
    assert reading.ok
    assert reading.value == 512
    assert reading.unit == "raw"
    assert reading.sensor_id == "soil_1"


def test_soil_out_of_range() -> None:
    transport = FakeSerialTransport([{"soil_raw": 5000}])
    reading = SoilMoistureSensor("soil_1", "Soil", transport).read()
    assert not reading.ok
    assert reading.value is None
    assert "range" in reading.error


def test_soil_missing_field() -> None:
    transport = FakeSerialTransport([{"temperature_c": 21.5}])
    reading = SoilMoistureSensor("soil_1", "Soil", transport).read()
    assert not reading.ok
    assert "missing" in reading.error


def test_soil_non_numeric() -> None:
    transport = FakeSerialTransport([{"soil_raw": "wet"}])
    reading = SoilMoistureSensor("soil_1", "Soil", transport).read()
    assert not reading.ok
    assert "not numeric" in reading.error


# --------------------------------------------------------------------------- #
# TemperatureSensor (serial)
# --------------------------------------------------------------------------- #
def test_temperature_valid(transport) -> None:
    reading = TemperatureSensor("temp_1", "Temp", transport).read()
    assert reading.ok
    assert reading.value == 21.5
    assert reading.unit == "°C"


def test_temperature_out_of_range() -> None:
    transport = FakeSerialTransport([{"temperature_c": 999}])
    reading = TemperatureSensor("temp_1", "Temp", transport).read()
    assert not reading.ok
    assert "range" in reading.error


# --------------------------------------------------------------------------- #
# Calibration offset + transport-down
# --------------------------------------------------------------------------- #
def test_calibration_offset_applied(transport) -> None:
    sensor = SoilMoistureSensor("soil_1", "Soil", transport, calibration_offset=10.0)
    reading = sensor.read()
    assert reading.ok
    assert reading.value == 522  # 512 + 10


def test_transport_down_returns_failed_reading() -> None:
    transport = FakeSerialTransport(raises=TimeoutError("No Arduino data received"))
    reading = SoilMoistureSensor("soil_1", "Soil", transport).read()
    assert not reading.ok
    assert reading.value is None
    assert "No Arduino data" in reading.error


def test_from_config_serial(transport) -> None:
    sensor = SoilMoistureSensor.from_config(
        {"id": "soil_1", "name": "Soil", "calibration_offset": 5.0},
        transport=transport,
    )
    reading = sensor.read()
    assert reading.ok
    assert reading.value == 517


# --------------------------------------------------------------------------- #
# Ads1115SoilSensor (direct, injected fake)
# --------------------------------------------------------------------------- #
def test_ads1115_valid() -> None:
    channel = FakeI2CChannel(value=12000)
    sensor = Ads1115SoilSensor("ads_1", "ADS soil", channel=channel)
    reading = sensor.read()
    assert reading.ok
    assert reading.value == 12000
    assert reading.unit == "raw"


def test_ads1115_out_of_range() -> None:
    channel = FakeI2CChannel(value=40000)  # > 32767
    reading = Ads1115SoilSensor("ads_1", "ADS soil", channel=channel).read()
    assert not reading.ok
    assert "range" in reading.error


def test_ads1115_from_config_with_injected_bus() -> None:
    channel = FakeI2CChannel(value=8000)
    sensor = Ads1115SoilSensor.from_config(
        {"id": "ads_1", "name": "ADS soil", "channel": 0},
        buses={"ads_1": channel},
    )
    reading = sensor.read()
    assert reading.ok
    assert reading.value == 8000


# --------------------------------------------------------------------------- #
# Ds18b20Sensor (direct, injected fake)
# --------------------------------------------------------------------------- #
def test_ds18b20_valid() -> None:
    device = FakeOneWireDevice(temperature=19.5)
    reading = Ds18b20Sensor("ds_1", "DS18B20", device=device).read()
    assert reading.ok
    assert reading.value == 19.5
    assert reading.unit == "°C"


def test_ds18b20_out_of_range() -> None:
    device = FakeOneWireDevice(temperature=200.0)  # > 125
    reading = Ds18b20Sensor("ds_1", "DS18B20", device=device).read()
    assert not reading.ok
    assert "range" in reading.error


def test_ds18b20_from_config_with_injected_bus() -> None:
    device = FakeOneWireDevice(temperature=22.2)
    sensor = Ds18b20Sensor.from_config(
        {"id": "ds_1", "name": "DS18B20", "device_id": "28-xyz"},
        buses={"ds_1": device},
    )
    reading = sensor.read()
    assert reading.ok
    assert reading.value == 22.2


# --------------------------------------------------------------------------- #
# SensorHub
# --------------------------------------------------------------------------- #
@pytest.fixture
def hub(transport) -> SensorHub:
    return SensorHub(
        [
            SoilMoistureSensor("soil_1", "Soil", transport),
            TemperatureSensor("temp_1", "Temp", transport),
        ]
    )


def test_hub_read_all(hub) -> None:
    readings = hub.read_all()
    assert len(readings) == 2
    assert {r.sensor_id for r in readings} == {"soil_1", "temp_1"}
    assert all(r.ok for r in readings)


def test_hub_read_one(hub) -> None:
    reading = hub.read_one("temp_1")
    assert reading.ok
    assert reading.sensor_id == "temp_1"


def test_hub_read_one_unknown_raises(hub) -> None:
    with pytest.raises(KeyError):
        hub.read_one("nope")


def test_hub_list_sensors(hub) -> None:
    listed = hub.list_sensors()
    assert listed == [
        {"id": "soil_1", "name": "Soil", "kind": "soil_moisture"},
        {"id": "temp_1", "name": "Temp", "kind": "temperature"},
    ]


# --------------------------------------------------------------------------- #
# Registry lookups
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "key,expected",
    [
        ("soil_moisture", SoilMoistureSensor),
        ("temperature", TemperatureSensor),
        ("ads1115_soil", Ads1115SoilSensor),
        ("ds18b20", Ds18b20Sensor),
    ],
)
def test_registry_lookup(key, expected) -> None:
    assert sensor_registry.get(key) is expected


def test_registry_unknown_type_raises() -> None:
    with pytest.raises(KeyError):
        sensor_registry.get("does_not_exist")
