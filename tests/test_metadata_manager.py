
from amscrot.controller.metadata_manager import MetadataManager
#mtd=MetadataManager.fetch()
mtd=MetadataManager.fetch(metadata_fetch_mode='local', metadata_id='service_client_metadata')
print(mtd)

# (.venv) PS C:\Users\4ua\Projects\amsc-isro-toolkit> python tests/test_metadata_manager.py