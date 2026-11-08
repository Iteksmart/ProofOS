"""AWS EC2 inventory using the official SDK and its credential chain."""
from __future__ import annotations

import os

import boto3

from .base import AdapterConfigurationError, VendorAdapter


class AwsAdapter(VendorAdapter):
    vendor = "aws"

    def list_resources(self) -> list[dict]:
        region = (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "").strip()
        if not region:
            raise AdapterConfigurationError("AWS_REGION must be configured")
        profile = os.getenv("AWS_PROFILE", "").strip() or None
        session = boto3.Session(profile_name=profile, region_name=region)
        ec2 = session.client("ec2")
        paginator = ec2.get_paginator("describe_instances")
        raw = [page for page in paginator.paginate()]
        instances = self.normalise_pages(raw)
        self._proof("vendor.aws.instances.list", {"count": len(instances), "region": region}, why={"reason": "EC2 inventory sync"})
        return instances

    def normalise_pages(self, pages: list[dict]) -> list[dict]:
        instances = []
        for page in pages:
            for reservation in page.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    tags = {tag.get("Key"): tag.get("Value") for tag in (instance.get("Tags") or []) if isinstance(tag, dict)}
                    state = instance.get("State") or {}
                    placement = instance.get("Placement") or {}
                    instances.append(
                        {
                            "id": instance.get("InstanceId"),
                            "name": tags.get("Name", ""),
                            "state": state.get("Name"),
                            "type": instance.get("InstanceType"),
                            "availability_zone": placement.get("AvailabilityZone"),
                            "private_ip": instance.get("PrivateIpAddress"),
                            "public_ip": instance.get("PublicIpAddress"),
                            "source": self.vendor,
                        }
                    )
        return instances
