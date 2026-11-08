from .aws import AwsAdapter
from .azure import AzureAdapter
from .google_workspace import GoogleWorkspaceAdapter
from .microsoft365 import Microsoft365Adapter
from .vmware import VmwareAdapter
from .base import AdapterConfigurationError, VendorAdapter

ADAPTERS = {
    "microsoft365": Microsoft365Adapter,
    "google_workspace": GoogleWorkspaceAdapter,
    "aws": AwsAdapter,
    "azure": AzureAdapter,
    "vmware": VmwareAdapter,
}

__all__ = [
    "AdapterConfigurationError",
    "VendorAdapter",
    "Microsoft365Adapter",
    "GoogleWorkspaceAdapter",
    "AwsAdapter",
    "AzureAdapter",
    "VmwareAdapter",
    "ADAPTERS",
]
