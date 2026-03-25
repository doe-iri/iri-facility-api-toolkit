from typing import Dict, Any, Optional


class Intent:
    """Represents a service client intent (template, profile structure, etc.).

    Wraps the raw dict data returned by a provider's profile/intent API
    and exposes common fields as attributes.

    Attributes:
        name:     Human-readable name of the intent.
        uuid:     Provider-assigned unique identifier.
        editable: Whether the intent supports edits.
        data:     Full raw data from the provider.
    """

    def __init__(
        self,
        data: Dict[str, Any],
        name: Optional[str] = None,
        uuid: Optional[str] = None,
        editable: bool = False,
    ):
        self.data = data
        self.name = name or data.get("name")
        self.uuid = uuid or data.get("uuid")
        self.editable = editable if editable else bool(data.get("editable", False))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "name": self.name,
            "uuid": self.uuid,
            "editable": self.editable,
            "data": self.data,
        }

    def __repr__(self) -> str:
        return f"<Intent name={self.name!r} uuid={self.uuid!r} editable={self.editable}>"
