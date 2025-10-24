from collections import namedtuple

Duration = namedtuple("Duration", "duration comment")

Stages = namedtuple("Stages", "setup_duration plan_duration create_duration delete_duration")

ProviderStats = namedtuple("ProviderStats",
                           "provider provider_duration has_failures has_pending stages")

AmSCROTStats = namedtuple("AmSCROTStats",
                          "action has_failures workflow_duration workflow_config controller providers provider_stats")
