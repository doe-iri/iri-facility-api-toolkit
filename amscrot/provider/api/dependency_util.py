from amscrot.util.constants import Constants


def has_resolved_external_dependencies(*, resource, attribute):
    resolved_dependencies = [rd for rd in resource[Constants.RESOLVED_EXTERNAL_DEPENDENCIES] if rd.attr == attribute]
    return len(resolved_dependencies) > 0


def has_resolved_internal_dependencies(*, resource, attribute):
    resolved_dependencies = [rd for rd in resource[Constants.RESOLVED_INTERNAL_DEPENDENCIES] if rd.attr == attribute]
    return len(resolved_dependencies) > 0


def get_values_for_dependency(*, resource, attribute):
    assert has_resolved_external_dependencies(resource=resource, attribute=attribute) \
           or has_resolved_internal_dependencies(resource=resource, attribute=attribute)

    values = []

    for temp in resource.get(attribute):
        for value in temp:
            values.append(value)

    return values

def get_single_value_for_dependency_if_any(*, resource, attribute):
    values = get_values_for_dependency(resource=resource, attribute=attribute)

    return values[0]

def get_single_value_for_dependency(*, resource, attribute):
    values = get_values_for_dependency(resource=resource, attribute=attribute)
    assert len(values) == 1
    return values[0]
