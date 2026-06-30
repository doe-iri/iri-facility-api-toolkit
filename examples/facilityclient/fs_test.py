#!/usr/bin/env python3
import os
from amscrot.client import Client

if __name__ == "__main__":
    client = Client(discover_endpoints=True)
    target_client = client.get_service_client("nersc")

    if not target_client or not getattr(target_client, 'api_endpoint', None):
        raise RuntimeError("No NERSC service client: set AMSC_TOKEN or add nersc-iri to credentials.yml")

    nersc = client.facility(
        endpoint=target_client.api_endpoint, 
        token=target_client.api_key, 
        name=target_client.name
    )

    for r in nersc.resources():
        print(r)

    homes = nersc.resource("homes")

    print(homes.fs.mkdir("test2").result)
    print(homes.fs.ls("test2").result)

    # Use the underlying ServiceClient formatters directly
    print(nersc._service_client.filesystem.ls(homes.fs._resource_id, "test2", format=True))
