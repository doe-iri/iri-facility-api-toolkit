
from amscrot.client import Client

def main():
    client = Client()

    fabric_provider = client.add_provider(
        label="fabric_provider",
        type="fabric",
        profile="fabric",
        credential_file="~/.amscrot/credentials.yml" 
    )

    kube_provider = client.add_provider(
        label="kube_provider",
        type="kube",
        profile="kube",
        credential_file="~/.amscrot/credentials.yml"
    )

    # Create Session
    session = client.create_session("k3s_service_example")

    # Define Resources
    ctrl_node = session.add_node(
        label="ctrl_node",
        provider=fabric_provider,
        enable_fabnetv4=False,
        enable_fabnetv6=False,
        enable_fabnetv6ext=True,
        routes=["2600:4040:7879:e00::/64"],
        site="WASH" # Uncomment this otherwise site will be random
    )

    child_nodes = session.add_node(
        label="child_nodes",
        provider=fabric_provider,
        enable_fabnetv4=False,
        enable_fabnetv6=False,
        enable_fabnetv6ext=True,
        routes=["2600:4040:7879:e00::/64"],
        site="WASH", # Uncomment this otherwise site will be random
        count=2
    )

    kube_service = session.add_service(
        label="kube_service",
        provider=kube_provider,
        controller="{{ node.ctrl_node }}",
        node=["{{ node.ctrl_node }}", "{{ node.child_nodes }}"],
        count=1 # Set to 1 to enable, matching config.fab default
    )

    print("Generating Plan...")
    plan_result = session.plan()
    print("Plan generated successfully.")

    #session.destroy()
    #session.apply()



if __name__ == "__main__":
    main()
