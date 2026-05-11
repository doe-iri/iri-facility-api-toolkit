from typing import List, Optional, Dict, Any, Iterator, TYPE_CHECKING
from pydantic import BaseModel, Field
from amscrot.util.constants import Constants

if TYPE_CHECKING:
    from amscrot.model.metadata import Facility
    from amscrot.model.intent import Intent


class DiscoveredResource(BaseModel):
    """A single discovered resource item."""
    type: str
    data: Dict[str, Any] = Field(default_factory=dict)
    name: Optional[str] = None
    metadata: Optional[Any] = Field(default=None, exclude=True)
    """Typed metadata object (e.g. Facility) populated when native=False."""

    model_config = {"arbitrary_types_allowed": True}

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
    def facilities(self) -> List["Facility"]:
        """Return typed Facility objects from normalized (native=False) discovery."""
        return [
            item.metadata
            for item in self.by_type(Constants.RES_FACILITY)
            if item.metadata is not None
        ]

    @property
    def capability(self) -> List[DiscoveredResource]:
        return self.by_type(Constants.RES_CAPABILITY)

    @property
    def intent(self) -> List[DiscoveredResource]:
        return self.by_type(Constants.RES_INTENT)

    @property
    def intents(self) -> List["Intent"]:
        """Return typed Intent objects from discovery."""
        return [
            item.metadata
            for item in self.by_type(Constants.RES_INTENT)
            if item.metadata is not None
        ]

    @property
    def incidents(self) -> List[DiscoveredResource]:
        """Return discovered incident resources."""
        return self.by_type(Constants.RES_INCIDENT)

    @property
    def events(self) -> List[DiscoveredResource]:
        """Return discovered event resources."""
        return self.by_type(Constants.RES_EVENT)

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

    def to_hierarchical(self) -> List[Dict[str, Any]]:
        """Return a hierarchical representation of normalized (native=False) Facility results.

        Each Facility is serialized with its nested compute, storage, network,
        and allocation resources.
        """
        from amscrot.model.metadata import Facility

        def _resource_dict(obj) -> Dict[str, Any]:
            """Generic typed-object -> dict using only the base + declared fields."""
            d: Dict[str, Any] = {}
            for field in type(obj).model_fields:
                val = getattr(obj, field, None)
                if val is not None:
                    d[field] = val
            return d

        def _fac_to_dict(fac: "Facility") -> Dict[str, Any]:
            return {
                "id": fac.id,
                "name": fac.name,
                "description": fac.description,
                "compute":     [_resource_dict(c) for c in (fac.compute     or [])],
                "storage":     [_resource_dict(s) for s in (fac.storage     or [])],
                "networks":    [_resource_dict(n) for n in (fac.networks    or [])],
                "allocations": [_resource_dict(a) for a in (fac.allocations or [])],
            }

        facilities = self.facilities  # List[Facility] from typed .metadata
        return [_fac_to_dict(f) for f in facilities]

    # -- Container protocol --

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return len(self._items) > 0

    def __iter__(self) -> Iterator[DiscoveredResource]:
        return iter(self._items)

    def __repr__(self) -> str:
        return f"<DiscoveryResult items={len(self._items)} types={self.summary()}>"
