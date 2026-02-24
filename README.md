# Table of contents

 - [Description](#descr)
 - [Installation](#install)
 - [Operation Instructions](#operate)
 - [Using Fabfed Welcome Jupyter Notebook](#jupyter)

# <a name="descr"></a>Description
The American Science Cloud Infrastructure Services Resource Orchestration Toolkit (AmSC-ISRO-Toolkit) provides cross-site resource orchestrtion for AmSC workflows.

# <a name="operate"></a>Operation Instructions

# <a name="jupyter"></a>AmSc-ISRO-Toolkit Welcome Jupyter Notebook
The Welcome Jupyter Notebook helps with isro-toolkit installation, credential configuration, and with running several sample workflows.

The **[amsc_hello_world](examples/notebooks/client/amsc_hello_world.ipynb)** notebook is the recommended starting point. It walks through:
- Installing the toolkit and configuring credentials (SENSE, ESnet IRI)
- Creating a `Client`, `Session`, and `ServiceClient`
- Submitting jobs and monitoring their status with `session.wait()`
- Cleaning up resources with `session.destroy()`
