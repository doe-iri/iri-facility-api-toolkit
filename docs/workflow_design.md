# Table of contents

 - [Description](#descr)
 - [Variables](#variables)
 - [Providers](#providers)
 - [Configs](#configs)
   - [Layer3](#layer3)
   - [Peering](#peering)
   - [Stitching Policy](#policy)
 - [Resources](#resources)
   - [Nodes](#nodes)
   - [Networks](#networks)
   - [Services](#services)
 - [Dependencies](#dependencies)
 - [Network Stitching Policy](#stitching)
 - [Network Stitching Example](#stitching_example)
 - [Overriding Stitching Policy](#stitching_override)
   - [Using The Network Resource](#simple)
   - [Using Policy Config ](#stich_policy)
   - [Using Your Own Policy](#own_policy)
 - [Breaking The Configuration](#breaking)

# <a name="descr"></a>Description
This readme file describes fabfed-py workflow model. The model consist of the following high level classes:
- [ ] variable
- [ ] provider
- [ ] config
- [ ] resource

The `provider` class supports the following types.
- [ ] fabric
- [ ] chi
- [ ] cloudlab
- [ ] sense
- [ ] janus
      
The `config` class support the following types:
- [ ] layer3
- [ ] peering
- [ ] policy
      
The `resource` class support three types:
- [ ] node
- [ ] network
- [ ] service

The workflow model allows us to define resources and to express dependencies among them. This is explained in more details below. We recommend you read on but you can get started quickly by copying the template credential file and the complete chameleon to fabric stitching example expressed in a single ".fab" file. These reside under [fabfed_config](../examples/fabfed_config) directory. You would need to configure the chameleon and fabric sections in the credential file and install the fabfed tool. 

- [fabfed credential file template](../examples/fabfed_config/fabfed_credentials_template.yml)
- [stitching example](../examples/fabfed_config/chi_to_fabric_stitching.fab)

# <a name="variables"></a>Variables
Variables have their own class named <i>variable</i>. A variable consists of a name and a value. Its declaration 
uses the <i>default</i> attribute signifying that it can be overriden at runtime using an external var-file. More on this later. 
The variable <i>fabric_site<i> declared below can be referred to by the expression ```'{{ var.fabric_site }}'``` and similarly ```'{{ var.node_name }}'``` 
would refer to the variable node_name.
 

```
variable:             # Class 
  - fabric_site:      # Label
      default: STAR   # Default value
  - node_name:        # Default for this variable is None and so it must be overridden using a var-file
 
```

A variable need not be declared at all as long as it is injected by supplying an external var-file. This var-file consists of a set of key-value pairs and can be specified on the fabfed command line tool with the --var-file option. Each key-value pair is written as ```key: value```. The sample var-file below would override the value ```STAR``` of the <i>fabric_site<i> declared above and would set the value of node_name to ```my_node```. 
 
 ```
 fabric_site: TACC
 node_name: my_node
 ```
 <b>NOTE</b>: The parsing process would halt if a variable is not bound to a value other than ```None```.
  
# <a name="providers"></a>Providers
A provider has its own class named <i>provider<i>. It consists of a <i>type</i>, a <i>label</i> and a dictionary. The snippet below declares a <i>fabric</i> provider. The `credential_file` and the `profile` attributes are used to configure the provider's environment.

A <i>resource</i> must refer to a provider using its type and its label like so: ```provider: '{{ fabric.fabric_provider }}'```

```
provider:                                                    # Class 
  - fabric:                                                  # Prvider Type: Must be one of these. [fabric, chi, sense, cloudlab, janus]
    - fabric_provider:                                       # Label: Can be any string
         credential_file: ~/.fabfed/fabfed_credentials.yml
         profile: fabric                                     # This can be any string and it points to a section in the credential file
```
 
 The `credential_file` and the `profile` are attributes used to configure the provider's environment. The credential YAML file contains a section or a profile for each provider. Unlike the provider type, the profile is an arbitrary string used to point to a section in the credential file. And each section contains information specific to a user and to each provider. The example below shows a credential file for fabric and chi. Consult the [template credential file](../examples/fabfed_config/fabfed_credentials_template.yml) for all the providers we currently support
  
```
# Sample Fabfed Credential File

fabric:
   bastion-user-name:
   token-location:
   bastion-key-location:
   project_id:
   slice-private-key-location:
   slice-public-key-location:

chi:
   project_name:
   key_pair:
   user:
   password:
   project_id:
     tacc: 
     uc: 
   slice-private-key-location:
   slice-public-key-location:
```

# <a name="configs"></a>Configs

A config consists of a <i>type</i>, a <i>label</i> and a dictionary specifying its attributes. The parsing process guarantees that the combination of the type and the label is unique. One can think of Configs as glorifed variables. 
We have two types `layer3` and `peering` and the Network Resources refer to these configs.

### <a name="layer3"></a>Layer3

In the example below the fabric and the chi networks share or point to the same layer3 config. The controller detects that and partitions the ip address space automatically. This results in a more concise and less error-prone configuration.

```
config:
  - layer3:
      - my_layer:
          subnet: 192.168.100.0/24
resource:
  - network:
      - chi_network:
          layer3: "{{ layer3.my_layer }}"
      - fabric_network
          layer3: "{{ layer3.my_layer }}"
```

### <a name="peering"></a>Peering

In the example below the `fabric` and the `aws` networks share or point to the same `peering` config. The `peering` configuration will be used by both providers to provision the necessary network stitching points to enable an isolated connection between the nodes. Here `fabric` nodes would be able to communicate to AWS nodes attached to the VPC. 

```
config:
  - peering:
      - my_peering:
          cloud_account: "REPLACEME_WITH_AMAZON_CLOUD_ACCOUNT" 
          cloud_vpc: "vpc-0c641c70ee2ec1790"
          local_asn: 55038                     # customer
          local_address: "192.168.1.1/30"
          remote_asn: 64512                    # amazon
          remote_address: "192.168.1.2/30"
resource:
  - network:
      - aws_network:
          peering: "{{ peering.my_peering }}"

      - fabric_network:
          peering: "{{ peering.my_peering }}"
         
```
### <a name="policy"></a>Stitching Policy

In this example we have a stitching `policy` that is referred to by network `cloudlab_network` using the `stitch_option`. Typically one does not need to provide this `policy` config as fabfed supports system defined stitching policy. But it can be used to experiment with new facility ports
or override the existing stitching policy. 

Here we see two stitch ports. The top level `stitch_port` and the `peer` stitch port. The `peer` stitch port for fabric and the top level stitchPort is for `cloudlab`. This is specified by the `provider` attribute. Also we see that `clouldlab` is the consumer and `fabric` is the producer. This simply means that the fabric_network will be created first and when that happens, the cloudlab_network will be get created with the vlan information produced by the fabric network. 

```
config:
  - policy:
    - cloudlab_fabric_policy:
        producer: fabric
        consumer: cloudlab
        stitch_port:
          profile: fabfed-stitch-v2
          provider: cloudlab
          peer:
            device_name: Utah-Cloudlab-Powder
            profile: Utah-Cloudlab-Powder
            provider: fabric
            site: UTAH
resource:
 - network:
      - cloudlab_network:
          stitch_with:
            - network: '{{ network.fabric_network }}'
              stitch_option:
                 policy: "{{ policy.si_cloudlab_fabric }}"
      - fabric_network:
          provider: '{{ fabric.fabric_provider }}'
```

# <a name="resources"></a>Resources
A resource consists of a <i>type</i>, a <i>label</i> and a dictionary. The parsing process guarantees that the combination of the type and the label is unique. Resources can refer to each other using the expression ```'{{ type.label }}'```. They can also refer to a resource's attribute using ```'{{ type.label.attribute_name }}'```. 

As of now we support the following types: <i>node</i>, <i>network</i>, and <i>service</i>. The <i>label</i> can be any string and is used as the name of the resource if the <i>name</i> attribute is not present. Resources are declared under their own class named <i>resource<i>. 
 
### <a name="nodes"></a>Nodes
A <i>node</i> <b>must</b> refer to a provider. Here it refers to the provider declared above. 
 
A <i>service</i> or a <i>network</i> would refer to this node using its type and label like so: ```'{{ node.fabric_node }}'```
 
```
resource:                                               # Class
  - node:                                               # Type must be one of node, network, or service
      - fabric_node:                                    # Label can be any string
            provider: '{{ fabric.fabric_provider }}'
            site: '{{ var.fabric_site }}'
            image: default_rocky_8   
            count: 1                               
```
### <a name="networks"></a>Networks
A <i>network</i> <b>must</b> refer to a provider. Here it refers to the provider declared above. 
 
A <i>node</i> or a <i>network</i> would refer to this network using its type and label like so: ```'{{ network.fabric_network }}'```
 
```
resource:                                               # Class
   - network:                                           # Type can be node or network
      - fabric_network:                                 # Label can be any string
            provider: '{{ fabric.fabric_provider }}'
            site: '{{ var.fabric_site }}'
            name: my_network
```
### <a name="services"></a>Services
A <i>service</i> <b>must</b> refer to a provider. Here it refers to a Janus provider for container management.
 
 
```
provider:
  - janus:
      - janus_provider:
          credential_file: ~/.fabfed/fabfed_credentials.yml
          profile: janus


resource:                                                          # Class
   - service:                                                      # Must be one of node, network, or service
      - dtn_service:                                               # Label can be any string
          - provider: '{{ janus.janus_provider }}'
            node: [ '{{ node.my_node0 }}', '{{ node.my_node1 }}' ] # List of nodes to apply the service to
```
 
# <a name="dependencies"></a>Dependencies
A resource can refer to other resources that it depends on. Line 14 in the example below, states that the <i>fabric_node</i> depends 
on the <i>fabric_network</i>. This is an `internal dependency` as both resources are handled by the same provider. The fabfed 
controller detects internal and external dependencies processes the resources in the correct during the apply phase and the destroy phase

Internally the controller handles external and internal dependencies differently. In the example below the controller would `add` the fabric node after `adding` the fabric network. And would `add` the fabric node after `creating` the chameleon network. 
```
resource:
  - network:
      - chi_network:
          provider: '{{ chi.chi_provider }}'
          layer3: "{{ layer3.my_layer }}"
      - fabric_network:
          provider: '{{ fabric.fabric_provider }}'
          layer3: "{{ layer3.my_layer }}"
          stitch_with:
            - network: '{{ network.chi_network }}' # External dependency 
      - fabric_node:
          provider: '{{ fabric.fabric_provider }}'
          network: '{{ network.fabric_network }}'  # Internal dependency
```

 # <a name="stitching"></a>Network Stitching Policy
 
 The fabfed controller supports a policy-defined network stitching and consults a policy file to pick a suitable stitch 
 point between two providers and determines the producer/consumer relationship. 

 The policy is defined in two files with one file concerning itself with peering the stitching ports and defining the producer/consumer relationships.
 The second file provides details such site, device information ...

 - [stitching policy](../fabfed/policy/stitching_policy.json)
 - [stitching port details](../fabfed/policy/stitching_policy_details.json)
 
 This simple snippet shows a single stitch point from 
 `chi` to `fabric`. The groups are used to specify the consumer/producer relationship. In the example below, `chi` is the consumer and 
 fabric is the `fabric` is the producer. The `fabric_network` produces a `vlan` that the  `chi_network` uses to create a `facility port`. 
 and so the fabfed controller would reorder the resources as needed to ensure that the producer is processed first.
 
 The `stitch-port` under fabric and the one under chi are peered together since they have the same `name`. The one under fabric provides
 information for the fabric provider. And similarly its peer under chi provides information for the chameleon provider.
 
 When multiple stitch points are available, the one with the highest `preference` gets selected. We provide a `stitch_option` attribute, discussed in the next section, that can be used to select a desired stitch point.


 ```
fabric:
  stitch-port:
    - name: Chameleon-StarLight
      device_name: Chameleon-StarLight
      preference: 100 # higher is preferred
      site: STAR
      member-of:
        - STAR
  group:
      - name: STAR
        producer-for:
            - chi
chi:
  stitch-port:
    - name: Chameleon-StarLight
      profile: fabric
      site: CHI@UC
      member-of:
        - STAR
  group:
    - name: STAR
      consumer-for:
        - fabric
 ```
  # <a name="stitching_example"></a>Network Stitching Example
 
The example below shows two stitched networks. The aws network uses the `stitch_with` to declare itself stitched with the fabric network.  The `stitch_with` dependency is an external dependency as it involves two resources from different providers. Fabfed controller ensures that the ordering is correct for both internal and external dependencies during the create phase and the destroy phase. 
 
Also note the `stitch_option` right below the `stitch_with`. If `stitch_option` is not present, the system would select a stitch point with the highest preference. Here the `stitch_option` is telling the system to pick a stitch point with `device_name` agg3.ashb.net.internet2.edu

 To view the stitch points from any two providers 
 ```
fabfed stitch-policy -providers "fabric,aws" 
 ```
 To view the stitch port that would be selected use the `-stitch-info` option.
 ```
fabfed workflow -s my-aws-test -stitch-info -summary
 ```
 ```
- network:
    - aws_network:
        provider: '{{ aws.aws_provider }}'
        layer3: "{{ layer3.aws_layer }}"
        peering: "{{ peering.my_peering }}"
        stitch_with:
          - network: '{{ network.fabric_network }}'
            stitch_option:
              device_name: agg3.dall3
    - fabric_network:
        provider: '{{ fabric.fabric_provider }}'
        layer3: "{{ layer3.fab_layer }}"
        peering: "{{ peering.my_peering }}"
 ```
  # <a name="stitching_override"></a>Overriding Stitching Policy
 
 Fabfed uses system defined stitching. Here we discuss the several ways one can override the stitch configuration. As of this writting there are 3 approaches. The first two approaches require some changes in the fabfed workflow definition. These are the simpler approaches. There is also a third approach which allows one can use to provide a complete stitching policy.

 ### <a name="simple"></a>Using The Network Resource
The `stitch_option` can be used to tell fabfed to select a stitch point from sense to fabric that uses the agg3.dall3. This stitch point returns a default profile needed by the sense provider. 
Instead of changing the policy files, one can simply uses the network attribute `profile`in the sense network. Here we use the `profile` attribute to override the default. 
 
 ```
  - network:
      - sense_network:
          profile: my-new-sense-profile
          stitch_with:
            - network: '{{ network.fabric_network }}'
              stitch_option: 
                  device_name: agg3.dall3
      - fabric_network:
          provider: '{{ fabric.fabric_provider }}'
          layer3: "{{ layer3.fab_layer }}"
 ```
 ### <a name="stich_policy"></a>Using Policy Config 
Using the `policy` config class, one can, for example, use a stitch point with a new device that is not yet available in the fabfed stitching policy. Note how the cloudlab network points to the `policy` config using the attribute `policy` under the `stitch_option`. 
 ```
config:
  - policy:
    - cloudlab_fabric_policy:
        producer: fabric
        consumer: cloudlab
        stitch_port:
          name: my_policy
          profile: fabfed-stitch-v2
          provider: cloudlab
          peer:
            device_name: Utah-Cloudlab-Powder
            profile: Utah-Cloudlab-Powder
            provider: fabric
            site: UTAH
resource:
 - network:
      - cloudlab_network:
          stitch_with:
            - network: '{{ network.fabric_network }}'
              stitch_option:
                policy: "{{ policy.si_cloudlab_fabric }}"
      - fabric_network:
          provider: '{{ fabric.fabric_provider }}'
 ```
 ### <a name="own_policy"></a>Using Your Own Policy
This approach can be useful when designing a new policy with several new stitch points, new providers, ...
 
 ```
# View the stitch points 
fabfed stitch-policy -providers "fabric,chi" -p my-policy.yaml

# Test your workflow and verify the selected stitch point 
fabfed workflow -s my-session -stitch-info -p my-policy.yaml -summary

# Apply your workflow
fabfed workflow -s my-session -apply -p my-policy.yaml
 ```
 # <a name="breaking"></a>Breaking The Configuration
 
 A configuration can be broken into many configuration files ending with ```.fab``` extensions. Fabfed does not care about how the files are named. 
 It loads all the files residing in a given directory that match the pattern ```*.fab```. It does so in no particular order and then proceeds to parse the assembled result. see [Fabric Chameleon Stitch](../examples/basic-stitching/chameleon)
 
 

