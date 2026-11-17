from typing import Annotated, Literal
from pydantic import BaseModel, Field


class Hardware(BaseModel):
    manufacturer: str = Field(default="", max_length=255)
    model: str = Field(default="", max_length=255)
    processor: str = Field(default="", max_length=255)
    architecture: str = Field(default="", max_length=100)
    physical_cores: int | None = Field(default=None, ge=0, le=65536)
    logical_cores: int | None = Field(default=None, ge=0, le=65536)
    memory_bytes: int | None = Field(default=None, ge=0)
    boot_time: str = Field(default="", max_length=100)


class Disk(BaseModel):
    device: str = Field(max_length=255)
    mountpoint: str = Field(max_length=1024)
    filesystem: str = Field(default="", max_length=100)
    total_bytes: int = Field(ge=0)
    free_bytes: int = Field(ge=0)


class Network(BaseModel):
    name: str = Field(max_length=255)
    address: str = Field(max_length=255)
    family: str = Field(default="", max_length=40)


class Software(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    version: str = Field(default="", max_length=255)
    publisher: str = Field(default="", max_length=500)
    source: str = Field(default="", max_length=255)
    source_version: str = Field(default="", max_length=255)


class InventoryIn(BaseModel):
    hostname: str = Field(default="", max_length=255)
    os: str = Field(default="", max_length=255)
    hardware: Hardware = Field(default_factory=Hardware)
    disks: list[Disk] = Field(default_factory=list, max_length=256)
    networks: list[Network] = Field(default_factory=list, max_length=1024)
    software: list[Software] = Field(default_factory=list, max_length=5000)
    software_status: Literal["complete", "partial", "unavailable"] = "unavailable"
    os_release: dict[str, str] = Field(default_factory=dict, max_length=10)
    errors: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=30)
