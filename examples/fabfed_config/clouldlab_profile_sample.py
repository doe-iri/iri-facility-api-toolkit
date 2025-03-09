"""Stitch a link through the Utah network to the FABRIC port on scidmz-cl
"""

# Import the Portal object.
import geni.portal as portal
# Import the ProtoGENI library.
import geni.rspec.pg as pg
# Emulab extensions
import geni.rspec.emulab
from ipaddress import IPv4Network, IPv4Address


NODE_MIN=0
NODE_MAX=10
VLAN_MIN=1000
VLAN_MAX=4095

# Create a portal context.
pc = portal.Context()

#
# List of Cloudlab clusters that have Fabric support.
#
clusters = [
    ('urn:publicid:IDN+utah.cloudlab.us+authority+cm', 'Utah'),
    ('urn:publicid:IDN+clemson.cloudlab.us+authority+cm', 'Clemson')]

pc.defineParameter("cluster", "Select Cluster",
                   portal.ParameterType.STRING,
                   clusters[0], clusters,
                   longDescription="Select a cluster")

# parameterize the vlan to use
portal.context.defineParameter("vlan", "VLAN ID", portal.ParameterType.INTEGER, 3100)
portal.context.defineParameter("ip_subnet", "IP_SUBNET", portal.ParameterType.STRING, "192.168.1.0/24")
portal.context.defineParameter("ip_start", "IP_START", portal.ParameterType.STRING, "192.168.1.2")
portal.context.defineParameter("node_count", "NODE_COUNT", portal.ParameterType.INTEGER, NODE_MIN)
params = portal.context.bindParameters()

# Check parameter validity.
if params.vlan < VLAN_MIN or params.vlan > VLAN_MAX:
    portal.context.reportError( portal.ParameterError( "VLAN ID must be in the range {}-{}".format(VLAN_MIN, VLAN_MAX) ) )

try:
    subnet = IPv4Network(unicode(params.ip_subnet))
    ip_start = int(IPv4Address(unicode(params.ip_start)))
except Exception as e:
    raise Exception("Bad subnet or ipstart")

if params.node_count < NODE_MIN or params.node_count > NODE_MAX:
    portal.context.reportError( portal.ParameterError( "Node count must be between {} and {} inclusive".format(NODE_MIN, NODE_MAX) ) )

# Create a Request object to start building the RSpec.
request = pc.makeRequestRSpec()

interfaces = list()

# Request nodes at one of the Utah clusters (Cloudlab Utah, Emulab, APT)

for i in range(0, params.node_count):
    node = request.RawPC("node{}".format(i))
    node.disk_image = "urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU22-64-STD"
    # node.hardware_type = "m510"

    if (params.cluster == 'urn:publicid:IDN+clemson.cloudlab.us+authority+cm'):
        node.Site("utah")
    else:
        node.Site("clemson")

    iface = node.addInterface("if0")
    # Must specify the IPv4 address on all stitched links
    iface.addAddress(pg.IPv4Address(str(IPv4Address(ip_start)), str(subnet.netmask)))
    ip_start += 1
    interfaces.append(iface)
    node.component_manager_id = params.cluster

# Request a special node that maps to the scidmz FABRIC port
fabric = request.Node("stitch-node", "emulab-connect")
fabric.Site("stitch")

# Magic.
fabric.component_id = "interconnect-fabric"
# XXX special handling for stitch fabric component_manager_id
if (params.cluster == 'urn:publicid:IDN+clemson.cloudlab.us+authority+cm'):
    fabric.component_manager_id = params.cluster
else:
    fabric.component_manager_id = "urn:publicid:IDN+stitch.geniracks.net+authority+cm"

fabric.exclusive = False
siface = fabric.addInterface("if0")
# Specify the IPv4 address for stitch node
siface.addAddress(pg.IPv4Address(str(IPv4Address(ip_start)), str(subnet.netmask)))
interfaces.append(siface)

# Make a LAN
if params.node_count == 1:
    lan = request.Link("link", "vlan")
else:
    lan = request.LAN()

for iface in interfaces:
    lan.addInterface(iface)

# Request one of the allowed tags
lan.setVlanTag(params.vlan)

# Many nodes have a single physical experimental interface, so use
# link multiplexing to make sure it maps to any node.
lan.link_multiplexing = True;

# Use best effort on stitched links.
lan.best_effort = True;

# Print the RSpec to the enclosing page.
pc.printRequestRSpec(request)