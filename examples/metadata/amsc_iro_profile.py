#!/usr/bin/env python3
import json
import sys
import argparse
from sense.client.profile_api import ProfileApi
from sense.models.profile_manifest import ProfileManifest
from sense.models.profile_edit import ProfileEdit

def get_profile_api():
    try:
        return ProfileApi()
    except Exception as e:
        print(f"Error initializing ProfileApi: {e}")
        return None

def escape_multiline(text: str) -> str:
    # Order matters: escape backslashes first, then quotes, then newlines
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    return text

def get_manifest():
    # Provided Profile Data with a NEW name
    profile_name = "AmSC Demo - Networked IRI Jobs - Transfer"
    description = "DEMO"

    DEFAULT_JOB_DIR = "/data/home/kissel"  # <-- adjust
    input_file = f"{DEFAULT_JOB_DIR}/synthetic_training_data_1g.txt"
    output_dir = f"{DEFAULT_JOB_DIR}/results"

    num_steps = 1000
    num_lines = 1000000

    bash_payload = f"""
    set -euo pipefail

    echo "=== MiniGPT training job ==="
    echo "UTC now: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "Hostname: $(hostname)"

    echo "Input file: {input_file}"
    echo "Output dir: {output_dir}"

    mkdir -p "{output_dir}"

    echo "Starting training..."

    python3 /root/tiny_gpt2_cpu_1k.py \
        "{input_file}" \
        "{output_dir}" \
        {num_steps} \
        {num_lines}

    echo "Training finished."

    echo "Output directory contents:"
    ls -lah "{output_dir}"
    touch "{DEFAULT_JOB_DIR}/xfer.ready"
    """

    escaped_compute_script = escape_multiline(bash_payload)

    # The Intent object containing the service type and the data payload
    intent_payload = {
        "service": "iri",
        "data": {
            "type": "IRI Facility Space",
            "jobs": [
                {
                    "facility_selector": {"one_of": ["facility_1"]},
                    "image": "quay.io/amscesnet/minigpt:dev",
                    "name": "cjob1",
                    "attributes": {"duration": 1800},
                    "type": "compute",
                    "executable": [
                        "bash",
                        "-lc",
                        escaped_compute_script
                    ],
                    "resource_spec": {
                        "memory": "2Gi",
                        "cpu_cores_per_process": 4,
                        "node_count": 1,
                        "processes_per_node": 1
                    }
                },
                {
                    "facility_selector": {"one_of": ["facility_1"]},
                    "image": "docker.io/dtnaas/tools:oneshot",
                    "name": "cjob2",
                    "attributes": {"duration": 1800},
                    "type": "compute",
                    "executable": [
                        "bash",
                        "-lc",
                        "sleep 120"
                    ],
                    "resource_spec": {
                        "memory": "2Gi",
                        "cpu_cores_per_process": 2,
                        "node_count": 1,
                        "processes_per_node": 1
                    }
                },
                {
                    "facility_selector": {"one_of": ["facility_2"]},
                    "image": "docker.io/dtnaas/tools:oneshot",
                    "name": "cjob3",
                    "attributes": {"duration": 1800},
                    "type": "compute",
                    "executable": [
                        "bash",
                        "-lc",
                        "sleep 120"
                    ],
                    "resource_spec": {
                        "memory": "2Gi",
                        "cpu_cores_per_process": 2,
                        "node_count": 1,
                        "processes_per_node": 1
                    }
                }
            ],
            "facilities": [
                {
                    "name": "facility_1",
                    "facility_name": "ESnet Facility East",
                    "resource_name": "Low Priority compute"
                },
                {
                    "name": "facility_2",
                    "facility_name": "ESnet Facility West",
                    "resource_name": "Low Priority compute"
                }
            ],
            "networks": [
                {
                    "name": "connection_1",
                    "type": "l2vpn",
                    "connects": [
                        {"type": "job", "name": "cjob1"},
                        {"type": "job", "name": "cjob3"}
                    ]
                }
            ]
        }
    }

    # print(json.dumps(intent_payload, indent=2))

    # Define editable fields
    edit_configs = [
        # Job names
        ProfileEdit(path="data.jobs[0].name", valid="^.+$", description=""),
        ProfileEdit(path="data.jobs[1].name", valid="^.+$", description=""),
        ProfileEdit(path="data.jobs[2].name", valid="^.+$", description=""),
        
        # Memory
        ProfileEdit(path="data.jobs[0].resource_spec.memory", valid="^\\dGi$", description=""),
        ProfileEdit(path="data.jobs[1].resource_spec.memory", valid="^\\dGi$", description=""),
        ProfileEdit(path="data.jobs[2].resource_spec.memory", valid="^\\dGi$", description=""),
        
        # CPU Cores
        ProfileEdit(path="data.jobs[0].resource_spec.cpu_cores_per_process", valid="^[1-4]$", description=""),
        ProfileEdit(path="data.jobs[1].resource_spec.cpu_cores_per_process", valid="^[1-4]$", description=""),
        ProfileEdit(path="data.jobs[2].resource_spec.cpu_cores_per_process", valid="^[1-4]$", description=""),
        
        # Nodes and Processes
        ProfileEdit(path="data.jobs[0].resource_spec.node_count", valid="^[1-4]$", description=""),
        ProfileEdit(path="data.jobs[0].resource_spec.processes_per_node", valid="^[1-4]$", description=""),
        ProfileEdit(path="data.jobs[1].resource_spec.node_count", valid="^[1-4]$", description=""),
        ProfileEdit(path="data.jobs[1].resource_spec.processes_per_node", valid="^[1-4]$", description=""),
        ProfileEdit(path="data.jobs[2].resource_spec.node_count", valid="^[1-4]$", description=""),
        ProfileEdit(path="data.jobs[2].resource_spec.processes_per_node", valid="^[1-4]$", description=""),

        # Executable (the script string at index 2)
        ProfileEdit(path="data.jobs[0].executable[2]", valid="^.+$", description=""),
        ProfileEdit(path="data.jobs[1].executable[2]", valid="^.+$", description=""),
        ProfileEdit(path="data.jobs[2].executable[2]", valid="^.+$", description=""),
        
        # Network Connections (connects in connection_1)
        ProfileEdit(path="data.networks[0].connects[0].name", valid="^.+$", description=""),
        ProfileEdit(path="data.networks[0].connects[1].name", valid="^.+$", description=""),
        
        # Job Attributes (Duration)
        ProfileEdit(path="data.jobs[0].attributes.duration", valid="^\\d+$", description=""),
        ProfileEdit(path="data.jobs[1].attributes.duration", valid="^\\d+$", description=""),
        ProfileEdit(path="data.jobs[2].attributes.duration", valid="^\\d+$", description=""),

        ProfileEdit(path="data.jobs[0].image", valid="^.+$", description=""),
        ProfileEdit(path="data.jobs[1].image", valid="^.+$", description=""),
        ProfileEdit(path="data.jobs[2].image", valid="^.+$", description="")
    ]

    return ProfileManifest(
        name=profile_name,
        description=description,
        editable=True,
        data=intent_payload,  # Pass dict directly to ensure correct nesting in SENSE-O
        edit=edit_configs
    )

def create_profile(api):
    manifest = get_manifest()
    print(f"Creating new profile '{manifest.name}'...")
    try:
        manifest_dict = manifest.to_dict()
        # The typed model is missing 'folder', but the API supports it
        manifest_dict['folder'] = "amsc/demo"
        
        body = json.dumps(manifest_dict)
        response = api.profile_create(body)
        print(f"Created profile successfully. UUID: {response}")
    except Exception as e:
        print(f"Failed to create profile: {e}")

def update_profile(api):
    manifest = get_manifest()
    print(f"Searching for profile '{manifest.name}' to update...")
    try:
        # Search for the profile UUID by name
        profile = api.profile_describe(manifest.name, force='true', fetch='false')
        if not profile:
            print(f"Profile '{manifest.name}' not found. You may want to create it first with --create.")
            return
            
        if isinstance(profile, dict) and 'uuid' in profile:
            uuid = profile['uuid']
        elif hasattr(profile, 'uuid'):
            uuid = profile.uuid
        elif isinstance(profile, str):
            uuid = profile
        else:
            print(f"Invalid profile format when searching for '{manifest.name}'.")
            return
            
        print(f"Updating profile {uuid}...")
        
        manifest_dict = manifest.to_dict()
        manifest_dict['folder'] = "amsc/demo"
        
        body = json.dumps(manifest_dict)
        api.profile_update(body, uuid=uuid)
        print("Profile updated successfully.")
    except Exception as e:
        print(f"Failed to update profile: {e}")

def delete_profile(api):
    manifest = get_manifest()
    print(f"Searching for profile '{manifest.name}' to delete...")
    try:
        # Search for the profile UUID by name
        profile = api.profile_describe(manifest.name, force='true', fetch='false')
        if not profile:
            print(f"Profile '{manifest.name}' not found.")
            return
            
        if isinstance(profile, dict) and 'uuid' in profile:
            uuid = profile['uuid']
        elif hasattr(profile, 'uuid'):
            uuid = profile.uuid
        elif isinstance(profile, str):
            uuid = profile
        else:
            print(f"Invalid profile format when searching for '{manifest.name}'.")
            return
            
        print(f"Deleting profile {uuid}...")
        api.profile_delete(uuid)
        print("Profile deleted successfully.")
    except Exception as e:
        print(f"Failed to delete profile: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage SENSE-O Intent Profiles")
    parser.add_argument("-c", "--create", action="store_true", help="Create a brand new profile")
    parser.add_argument("-u", "--update", action="store_true", help="Update an existing profile (found by name)")
    parser.add_argument("-d", "--delete", action="store_true", help="Delete an existing profile (found by name)")
    args = parser.parse_args()

    api = get_profile_api()
    if not api:
        exit(1)

    if args.delete:
        delete_profile(api)
    elif args.update:
        update_profile(api)
    elif args.create:
        create_profile(api)
    else:
        # If no flag is provided, print help
        parser.print_help()
