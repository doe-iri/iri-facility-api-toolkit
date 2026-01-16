
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
        label="ctrl-node",
        provider=fabric_provider,
        enable_fabnetv4=False,
        enable_fabnetv6=False,
        enable_fabnetv6ext=True,
        routes=["2600:4040:787a:4000::/64"],
        site="MAX" # Uncomment this otherwise site will be random
    )

    child_nodes = session.add_node(
        label="child-node",
        provider=fabric_provider,
        enable_fabnetv4=False,
        enable_fabnetv6=False,
        enable_fabnetv6ext=True,
        routes=["2600:4040:787a:4000::/64"],
        site="MAX", # Uncomment this otherwise site will be random
        count=2
    )

    kube_service = session.add_service(
        label="kube-service",
        provider=kube_provider,
        flannel_iface="eth1",
        flannel_ipv6_masq=True,
        controller=ctrl_node,
        node=[ctrl_node, child_nodes],
        count=1,
        delete=0
    )

    print("Generating Plan...")
    plan_result = session.plan()
    print("Plan generated successfully.")
    
    session.show()

    #session.destroy()
    session.apply()



if __name__ == "__main__":
    main()
