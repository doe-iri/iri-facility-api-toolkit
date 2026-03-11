
from amscrot.controller.metadata_manager import MetadataManager
#mtd=MetadataManager.fetch(metadata_fetch_mode='local')
#mtd=MetadataManager.fetch(metadata_fetch_mode='local', metadata_id='service_client_metadata')
#mtd=MetadataManager.fetch(metadata_fetch_mode='remote')
#mtd=MetadataManager.fetch(metadata_fetch_mode='remote', metadata_id='AneesTest')
mtd=MetadataManager.fetch(metadata_fetch_mode='local|remote')


print(mtd)

# (.venv) PS C:\Users\4ua\Projects\amsc-isro-toolkit> python tests/test_metadata_manager.py