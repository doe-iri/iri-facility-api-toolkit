# Table of contents

 - [Description](#descr)
 - [Installation](#install)
 - [Operation Instructions](#operate)
 - [Using Fabfed Welcome Jupyter Notebook](#jupyter)

# <a name="descr"></a>Description
The American Science Cloud Infrastructure Services Resource Orchestration Toolkit (AmSC-ISRO-Toolkit [AmSCROT]) provides _infrastructure_ orchestrtion for AmSC use.

# <a name="install"></a>Installation

```
pip install amscrot-py
```

# <a name="operate"></a>Operation Instructions
TBD

# <a name="jupyter"></a>AmSc-ISRO-Toolkit Welcome Jupyter Notebook
The Welcome Jupyter Notebook helps with the toolkit installation, credential configuration, and with running several sample infrastructure jobs in a _pass-though_ manner.

The **[amsc_hello_world](examples/notebooks/client/amsc_hello_world.ipynb)** notebook is the recommended starting point. It walks through:
- Installing the toolkit and configuring credentials (SENSE, ESnet IRI)
- Creating a `Client`, `Session`, and `ServiceClient`
- Submitting jobs and monitoring their status with `session.wait()`
- Cleaning up resources with `session.destroy()`
