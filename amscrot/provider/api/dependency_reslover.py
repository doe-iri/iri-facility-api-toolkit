import logging

from amscrot.model import ResolvedDependency, Resource
from amscrot.util.constants import Constants


class DependencyResolver:
    def __init__(self, *, label, logger: logging.Logger, external=True):
        self.label = label
        self.logger = logger

        if external:
            self.dependency_label = Constants.EXTERNAL_DEPENDENCIES
            self.resolved_dependency_label = Constants.RESOLVED_EXTERNAL_DEPENDENCIES
        else:
            self.dependency_label = Constants.INTERNAL_DEPENDENCIES
            self.resolved_dependency_label = Constants.RESOLVED_INTERNAL_DEPENDENCIES

    def check_if_external_dependencies_are_resolved(self, *, resource: dict):
        label = resource[Constants.LABEL]
        self.logger.info(f"Checking if all dependencies are resolved for {label} using {self.label}")

        if len(resource[self.dependency_label]) == len(resource[self.resolved_dependency_label]):
            ok = True

            for dependency in resource[self.dependency_label]:
                count = dependency.resource.attributes.get(Constants.RES_COUNT, 1)
                assert count > 0

                temp = resource[self.resolved_dependency_label]
                criteria = (dependency.key, dependency.resource.label)
                resolved_dependencies = [rd for rd in temp if (rd.attr, rd.resource_label) == criteria]

                assert len(resolved_dependencies) == 1
                resolved_dependency = resolved_dependencies[0]

                if len(resolved_dependency.value) != count:
                    ok = False
                    break

            self.logger.info(f"Checking if all dependencies are resolved for {label} using {self.label}:ret={ok}")
            return ok

        self.logger.info(f"Checking if all dependencies are resolved for {label} using {self.label}:ret=false")
        return False

    def resolve_dependency(self, *, resource: dict, from_resource: Resource):
        from_resource_dict = vars(from_resource)
        label = resource[Constants.LABEL]

        for dependency in resource[self.dependency_label]:
            count = dependency.resource.attributes.get(Constants.RES_COUNT, 1)
            assert count > 0

            if dependency.resource.label == from_resource.label:
                try:
                    if not dependency.attribute:
                        value = from_resource
                    elif "[" in dependency.attribute:
                        idx1 = dependency.attribute.find("[")
                        idx2 = dependency.attribute.find("]")
                        value = from_resource_dict.get(dependency.attribute[0:idx1])
                        value = value[int(dependency.attribute[idx1 + 1: idx2])]
                    else:
                        value = from_resource_dict.get(dependency.attribute)

                    if value and isinstance(value, list):
                        value = tuple(value)

                    self.logger.info(
                        f"Resolving: {dependency} for {label}: value={value} using {self.label}")

                    if value:
                        resolved_dependencies = resource[self.resolved_dependency_label]
                        from typing import List, Dict, Union
                        found: Union[ResolvedDependency, None] = None

                        for resolved_dependency in resolved_dependencies:
                            if resolved_dependency.attr == dependency.key \
                                    and resolved_dependency.resource_label == dependency.resource.label:
                                found = resolved_dependency
                                break

                        if not found:
                            resolved_dependency = ResolvedDependency(resource_label=dependency.resource.label,
                                                                     attr=dependency.key,
                                                                     value=(value,))
                            resolved_dependencies.append(resolved_dependency)
                            self.logger.info(f"Resolved dependency {dependency} for {label} using {self.label}")
                        elif len(found.value) < count:
                            resolved_dependency = ResolvedDependency(resource_label=dependency.resource.label,
                                                                     attr=dependency.key,
                                                                     value=(value,) + found.value)
                            resolved_dependencies.remove(found)
                            resolved_dependencies.append(resolved_dependency)
                            self.logger.info(f"Resolved dependency {dependency} for {label} using {self.label}")
                    else:
                        self.logger.warning(
                            f"Could not resolve {dependency} for {label} using {self.label}")
                except Exception as e:
                    self.logger.warning(
                        f"Severe Exception occurred while resolving dependency: {e} using {self.label}")
                    self.logger.error(e, exc_info=True)

    def extract_values(self, *, resource: dict):
        assert resource[self.dependency_label]

        for dependency in resource[self.dependency_label]:
            attribute = dependency.key

            label = resource.get(Constants.LABEL)
            self.logger.debug(f"Extracting Values: {label}:{attribute} using {self.label}")

            resolved_dependencies = [rd for rd in resource[self.resolved_dependency_label]
                                     if rd.attr == attribute]

            assert resolved_dependencies

            values = [rd.value for rd in resolved_dependencies]
            resource[attribute] = [rd.value for rd in resolved_dependencies]
            self.logger.info(f"Extracted Values: {values}:{label}:{attribute} using {self.label}")
