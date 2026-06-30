try:
    import numpy as np
    from amscrot.controller.metadata_manager import MetadataManager
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

if HAS_NUMPY:
    #mtd=MetadataManager.fetch(metadata_fetch_mode='local')
    #mtd=MetadataManager.fetch(metadata_fetch_mode='local', metadata_id='service_client_metadata3')
    #mtd=MetadataManager.fetch(metadata_fetch_mode='remote')
    #mtd=MetadataManager.fetch(metadata_fetch_mode='remote', metadata_id='AneesTest4')
    mtd=MetadataManager.fetch(metadata_fetch_mode='local|remote')
    # mtd=MetadataManager.fetch()
    print(mtd)
    # (.venv) amsc-isro-toolkit> python tests/test_metadata_manager.py
else:
    print("numpy not installed, skipping metadata manager test")
