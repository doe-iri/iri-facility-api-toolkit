import logging

from amscrot.controller.controller import Controller
from amscrot.util import state as sutil
from amscrot.util import utils
from amscrot.util.config import WorkflowConfig
from typing import List
from amscrot.controller.provider_factory import default_provider_factory
from amscrot.exceptions import ControllerException
from amscrot.provider.dummy.dummy_provider import DummyService

from amscrot.model.state import ProviderState


class DummyFailCreateException(Exception):
    """Base class for other exceptions"""
    pass


def get_stats(*, states: List[ProviderState]):
    return utils.get_counters(states=states)


def run_plan_workflow(*, session, config_str):
    config = WorkflowConfig.parse(content=config_str)

    # logger = utils.init_logger()
    logger = logging.getLogger(__name__)
    controller = Controller(config=config, logger=logger)
    states = sutil.load_states(session)
    controller.init(session=session, provider_factory=default_provider_factory, provider_states=states)
    controller.plan(provider_states=states)
    cr, dl = sutil.dump_plan(resources=controller.resources, to_json=False, summary=False)
    return cr, dl


def run_apply_workflow(*, session, config_str) -> List[ProviderState]:
    config = WorkflowConfig.parse(content=config_str)

    # logger = utils.init_logger()
    logger = logging.getLogger(__name__)
    states = sutil.load_states(session)
    controller = Controller(config=config, logger=logger)
    controller.init(session=session, provider_factory=default_provider_factory, provider_states=states)
    controller.plan(provider_states=[])
    controller.add(provider_states=[])

    try:
        controller.apply(provider_states=[])
    except ControllerException as e:
        assert isinstance(e.exceptions[0], DummyFailCreateException)

    states = controller.get_states()
    sutil.save_states(states, session)
    return states


def run_destroy_workflow(*, session, config_str) -> List[ProviderState]:
    config = WorkflowConfig.parse(content=config_str)
    logger = logging.getLogger(__name__)
    controller = Controller(config=config, logger=logger)
    states = sutil.load_states(session)
    controller.init(session=session, provider_factory=default_provider_factory, provider_states=states)
    controller.destroy(provider_states=states)
    sutil.save_states(states, session)

    if not states:
        sutil.destroy_session(session)

    return states


def test_simple_workflow():
    config_str = '''
provider:
  - dummy:
    - my_provider:
       - url: https://some_url:5000
resource:
  - service:
      - dtn:
         - provider: '{{ dummy.my_provider }}'
           image: ubuntu
    '''
    session = "test_simple"
    cr, dl = run_plan_workflow(session=session, config_str=config_str)
    assert cr == 1 and dl == 0
    states = run_apply_workflow(session=session, config_str=config_str)
    assert len(states) == 1
    assert get_stats(states=states) == (0, 0, 1, 0, 0)
    states = run_destroy_workflow(session=session, config_str=config_str)
    assert len(states) == 0


def test_plan_workflow():
    config_str = '''
provider:
  - dummy:
    - my_provider:
       - url: https://some_url:5000
resource:
  - service:
      - dtn:
         - provider: '{{ dummy.my_provider }}'
           image: ubuntu
    '''

    config_str_2 = '''
provider:
  - dummy:
    - my_provider:
       - url: https://some_url:5000
resource:
  - service:
      - dtn2:
         - provider: '{{ dummy.my_provider }}'
           image: ubuntu
           count: 5
        '''

    config_str_3 = '''
provider:
  - dummy:
    - my_provider:
       - url: https://some_url:5000
resource:
  - service:
      - dtn2:
         - provider: '{{ dummy.my_provider }}'
           image: ubuntu
           count: 3
            '''
    session = "test_plan_workflow"
    cr, dl = run_plan_workflow(session=session, config_str=config_str)
    assert (cr, dl) == (1, 0)
    states = run_apply_workflow(session=session, config_str=config_str)
    assert len(states) == 1
    assert get_stats(states=states) == (0, 0, 1, 0, 0)
    cr, dl = run_plan_workflow(session=session, config_str=config_str_2)
    assert (cr, dl) == (5, 1)

    states = run_apply_workflow(session=session, config_str=config_str_2)
    assert len(states) == 1
    assert get_stats(states=states) == (0, 0, 5, 0, 0)
    cr, dl = run_plan_workflow(session=session, config_str=config_str_3)
    assert (cr, dl) == (3, 5)

    states = run_destroy_workflow(session=session, config_str=config_str)
    assert len(states) == 0


def test_simple_workflow_with_create_failing():
    config_str = '''
provider:
  - dummy:
    - my_provider:
       - url: https://some_url:5000
resource:
  - service:
      - dtn:
         - provider: '{{ dummy.my_provider }}'
           image: ubuntu
    '''
    session = "test_simple_workflow_with_create_failing"
    clazz = DummyService
    orig = clazz.create

    def create(self):
        raise DummyFailCreateException(f"Fail on purpose ... {self}")

    clazz.create = create
    states = run_apply_workflow(session=session, config_str=config_str)
    clazz.create = orig
    assert len(states) == 1
    assert get_stats(states=states) == (0, 0, 0, 0, 1)
    states = run_destroy_workflow(session=session, config_str=config_str)
    assert len(states) == 0


def test_service_dependency_workflow():
    config_str = '''
provider:
  - dummy:
    - my_provider:
       - url: https://some_url:5000
         name: prov1
  - dummy:
    - my_provider2:
       - url: https://some_other_url:5000
         name: prov2
resource:
  - service:
      - dtn1:
         - provider: '{{ dummy.my_provider }}'
           image: "centos"
           exposed_attribute_x: "{{ service.dtn2 }}"
  - service:
      - dtn2:
         - provider: '{{ dummy.my_provider2 }}'
           image: ubuntu
    '''
    session = "test_service_dependency"
    states = run_apply_workflow(session=session, config_str=config_str)
    assert len(states) == 2
    assert get_stats(states=states) == (0, 0, 2, 0, 0)
    states = run_destroy_workflow(session=session, config_str=config_str)
    assert len(states) == 0


def test_service_dependency_workflow_with_pending():
    config_str = '''
provider:
  - dummy:
    - my_provider:
       - url: https://some_url:5000
         name: prov1
  - dummy:
    - my_provider2:
       - url: https://some_other_url:5000
         name: prov2
resource:
  - service:
      - dtn1:
         - provider: '{{ dummy.my_provider }}'
           image: "centos"
           exposed_attribute_x: "{{ service.dtn2 }}"
  - service:
      - dtn2:
         - provider: '{{ dummy.my_provider2 }}'
           image: ubuntu
    '''
    session = "test_service_dependency"
    clazz = DummyService
    orig = clazz.create

    def create(self):
        if self.image == "ubuntu":
            raise DummyFailCreateException(f"Fail on purpose ... {self.image}")

    clazz.create = create
    states = run_apply_workflow(session=session, config_str=config_str)
    clazz.create = orig
    assert len(states) == 2
    assert get_stats(states=states) == (0, 0, 0, 1, 1)
    states = run_destroy_workflow(session=session, config_str=config_str)
    assert len(states) == 0


def test_attribute_dependency_workflow():
    config_str = '''
provider:
  - dummy:
    - my_provider:
       - url: https://some_url:5000
         name: prov1
  - dummy:
    - my_provider2:
       - url: https://some_other_url:5000
         name: prov2
resource:
  - service:
      - dtn1:
         - provider: '{{ dummy.my_provider }}'
           image: "centos"
           count: 5
           exposed_attribute_x: "{{ service.dtn2.exposed_attribute_x }}"
  - service:
      - dtn2:
         - provider: '{{ dummy.my_provider2 }}'
           image: ubuntu
    '''
    session = "test_attribute_dependency"
    states = run_apply_workflow(session=session, config_str=config_str)
    assert len(states) == 2

    assert get_stats(states=states) == (0, 0, 6, 0, 0)
    x = states[0].service_states[0].attributes["exposed_attribute_x"]

    for state in states:
        for service_state in state.service_states:
            assert service_state.attributes["exposed_attribute_x"] == x

    states = run_destroy_workflow(session=session, config_str=config_str)
    assert len(states) == 0


def test_multiple_service_dependency_workflow():
    config_str = '''
provider:
  - dummy:
    - my_provider:
       - url: https://some_url:5000
         name: prov1
  - dummy:
    - my_provider2:
       - url: https://some_other_url:5000
         name: prov2
resource:
  - service:
      - dtn1:
         - provider: '{{ dummy.my_provider }}'
           image: "centos"
           exposed_attribute_x: ["{{ service.dtn2 }}", "{{ service.dtn3 }}"]
           count: 10
  - service:
      - dtn2:
         - provider: '{{ dummy.my_provider2 }}'
           image: ubuntu
           count: 2
  - service:
      - dtn3:
         - provider: '{{ dummy.my_provider2 }}'
           image: ubuntu
           count: 3
 
    '''
    session = "test_multiple_service_dependency"
    states = run_apply_workflow(session=session, config_str=config_str)
    assert len(states) == 2
    assert get_stats(states=states) == (0, 0, 15, 0, 0)
    states = run_destroy_workflow(session=session, config_str=config_str)
    assert len(states) == 0
