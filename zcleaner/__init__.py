"""Zoho CRM Cleaner: normalize, validate and deduplicate Zoho CRM exports."""

from .pipeline import Result, run
from .schema import read_export

__all__ = ["Result", "run", "read_export"]
__version__ = "0.1.0"
