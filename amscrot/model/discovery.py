from typing import List, Optional, Dict, Any, Iterator
from pydantic import BaseModel, Field
from amscrot.util.constants import Constants


class DiscoveredResource(BaseModel):
    """A single discovered resource item."""
    type: str
    data: Dict[str, Any] = Field(default_factory=dict)
    name: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        # Auto-extract name from data if not explicitly set
        if self.name is None and 'name' in self.data:
            self.name = self.data['name']

    def to_dict(self) -> Dict[str, Any]:
        """Serialize back to the legacy dict format."""
        return {"type": self.type, "data": self.data}


class DiscoveryResult:
    """Container for discovered resources from a ServiceClient.

    Organizes resources by type and provides typed accessors for each
    resource category defined in Constants.
    """

    def __init__(self, items: Optional[List[DiscoveredResource]] = None):
        self._items: List[DiscoveredResource] = items or []

    # -- Typed accessors for named resource types --

    @property
    def network(self) -> List[DiscoveredResource]:
        return self.by_type(Constants.RES_NETWORK)

    @property
    def compute(self) -> List[DiscoveredResource]:
        return self.by_type(Constants.RES_COMPUTE)

    @property
    def storage(self) -> List[DiscoveredResource]:
        return self.by_type(Constants.RES_STORAGE)

    @property
    def allocation(self) -> List[DiscoveredResource]:
        return self.by_type(Constants.RES_ALLOCATION)

    @property
    def project(self) -> List[DiscoveredResource]:
        return self.by_type(Constants.RES_PROJECT)

    @property
    def facility(self) -> List[DiscoveredResource]:
        return self.by_type(Constants.RES_FACILITY)

    @property
    def capability(self) -> List[DiscoveredResource]:
        return self.by_type(Constants.RES_CAPABILITY)

    # -- Generic access --

    @property
    def all(self) -> List[DiscoveredResource]:
        """Return all discovered resources."""
        return list(self._items)

    def by_type(self, type_str: str) -> List[DiscoveredResource]:
        """Filter resources by an arbitrary type string."""
        return [item for item in self._items if item.type == type_str]

    def summary(self) -> Dict[str, int]:
        """Return a dict of {type: count} for all resource types found."""
        counts: Dict[str, int] = {}
        for item in self._items:
            counts[item.type] = counts.get(item.type, 0) + 1
        return counts

    def to_list(self) -> List[Dict[str, Any]]:
        """Serialize to the legacy list-of-dicts format for backward compatibility."""
        return [item.to_dict() for item in self._items]

    # -- Container protocol --

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return len(self._items) > 0

    def __iter__(self) -> Iterator[DiscoveredResource]:
        return iter(self._items)

    def __repr__(self) -> str:
        return f"<DiscoveryResult items={len(self._items)} types={self.summary()}>"
