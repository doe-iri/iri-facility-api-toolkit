import logging
from typing import Union

from fabfed.util.utils import get_logger


class FacilityPortHandler:
    facility_ports = None

    def __init__(self, logger: Union[logging.Logger, None] = None):
        self.logger = logger or get_logger()

    def load_facility_ports(self):
        self.logger.info("Loading facility ports ...")
        from fabrictestbed_extensions.fablib.fablib import fablib

        ret = fablib.get_facility_ports()
        self.logger.info("Loaded facility ports")
        return ret

    def populate_stitch_port(self, *, stitch_port):
        if FacilityPortHandler.facility_ports is None:
            FacilityPortHandler.facility_ports = self.load_facility_ports()

        for fp in FacilityPortHandler.facility_ports.topology.facilities.values():
            if fp.name != stitch_port['profile'] or fp.site != stitch_port['site']:
                continue

            interface_list = [iface for iface in fp.interface_list if iface.labels]
            for iface in interface_list:
                labels = iface.labels

                if labels.device_name and labels.device_name != stitch_port['device_name']:
                    continue

                if labels.local_name and 'local_name' in stitch_port['local_name'] \
                        and labels.local_name != stitch_port['local_name']:
                    continue

                if labels.region:
                    stitch_port['region'] = labels.region

                stitch_port['vlan_range'] = labels.vlan_range
                label_allocations = iface.get_property("label_allocations")
                stitch_port['allocated_vlans'] = label_allocations.vlan if label_allocations else []
                stitch_port['allocated_vlans'] = [int(vlan) for vlan in stitch_port['allocated_vlans']]


def load_facility_info_using_stich_port(stitch_port):
    handler = FacilityPortHandler()
    handler.populate_stitch_port(stitch_port=stitch_port)


def load_facility_info(stitch_infos):
    handler = FacilityPortHandler()

    for si in stitch_infos:
        stitch_ports = [si.stitch_port,  si.stitch_port['peer']]

        for sp in stitch_ports:
            if sp['provider'] == "fabric":
                handler.populate_stitch_port(stitch_port=sp)
