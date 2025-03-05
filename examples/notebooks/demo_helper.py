import os

default_credentials = '~/.fabfed/fabfed_credentials.yml'


def absolute_path(path):
    from pathlib import Path
    
    path = Path(path).expanduser().absolute()
    return os.path.realpath(str(path))


def default_credentials_location():
    return absolute_path(default_credentials)


def parse_and_dump_chameleon_credentials(chi_rc_path):
    import yaml

    chi_creds_template = '''
    chi:
       project_name: REPLACE_ME
       key_pair: REPLACE_ME
       user: REPLACE_ME
       password: REPLACE_ME
       slice-private-key-location: REPLACE_ME
       slice-public-key-location: REPLACE_ME
       project_id:
         tacc: REPLACE_ME
         uc: REPLACE_ME
    '''

    chi_creds_mappings = dict(
        OS_PROJECT_ID='project_id',
        OS_USERNAME='user',
    )

    with open(absolute_path(chi_rc_path), 'r') as f:
        lines = f.readlines()

    chi_rc_dict = dict()

    for idx, line in enumerate(lines):
        line = line.strip('\n ')

        if not line.startswith('export') or '=' not in line:
            continue

        line = line[len('export'):].strip()
        name, value = line.split('=', 1)
        value = value.strip("\"'")
        chi_rc_dict[name] = value

    chi_creds = yaml.safe_load(chi_creds_template)
    chi_creds_dict = chi_creds['chi']

    for name, value in chi_creds_mappings.items():
        if 'OS_PROJECT_ID' == name:
            if 'CHI@TACC' == chi_rc_dict['OS_REGION_NAME']:
                chi_creds_dict[value]['tacc'] = chi_rc_dict[name]
            elif 'CHI@UC' == chi_rc_dict['OS_REGION_NAME']:
                chi_creds_dict[value]['uc'] = chi_rc_dict[name]
            else:
                print("KKKK:", name, )
        elif name in chi_rc_dict:
            chi_creds_dict[value] = chi_rc_dict[name]

    import sys

    sys.stdout.write(yaml.dump(chi_creds))


def parse_and_dump_fabric_credentials(fabric_rc_path):
    import yaml

    fabric_creds_template = '''
    fabric:
       bastion-user-name: REPLACE_ME
       token-location: REPLACE_ME
       bastion-key-location: REPLACE_ME
       project_id: REPLACE_ME
       slice-private-key-location: REPLACE_ME
       slice-public-key-location: REPLACE_ME
    '''

    fabric_creds_mappings = dict(
        FABRIC_BASTION_USERNAME='bastion-user-name',
        FABRIC_BASTION_KEY_LOCATION='bastion-key-location',
        FABRIC_PROJECT_ID='project_id',
        FABRIC_SLICE_PRIVATE_KEY_FILE='slice-private-key-location',
        FABRIC_SLICE_PUBLIC_KEY_FILE='slice-public-key-location'
    )

    with open(absolute_path(fabric_rc_path), 'r') as f:
        lines = f.readlines()

    fabric_rc_dict = dict()

    for idx, line in enumerate(lines):
        line = line.strip('\n ')

        if not line.startswith('export') or '=' not in line:
            continue

        line = line[len('export'):].strip()
        name, value = line.split('=', 1)
        fabric_rc_dict[name] = value

    fabric_creds = yaml.safe_load(fabric_creds_template)
    fabric_creds_dict = fabric_creds['fabric']

    for name, value in fabric_creds_mappings.items():
        if name in fabric_rc_dict:
            fabric_creds_dict[value] = fabric_rc_dict[name]

    import sys

    sys.stdout.write(yaml.dump(fabric_creds))
