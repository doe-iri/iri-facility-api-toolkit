#!/usr/bin/env bash
# setup_airflow.sh -- Set up a local Apache Airflow environment for amscrot testing.
#
# Usage:
#   cd airflow/
#   bash setup_airflow.sh [--start]
#
# With --start: initialise the DB, create an admin user, and launch Airflow
#               in standalone mode (scheduler + webserver in one process).
#
# Without --start: only install packages and configure AIRFLOW_HOME.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AIRFLOW_HOME="${SCRIPT_DIR}/airflow_home"
AIRFLOW_VERSION="3.1.7"
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.10.txt"

export AIRFLOW_HOME

echo "==> AIRFLOW_HOME=${AIRFLOW_HOME}"
echo "==> Constraint URL: ${CONSTRAINT_URL}"


# ------------------------------------------------------------------
# 1. Install amscrot-airflow (this package) + apache-airflow
# ------------------------------------------------------------------
echo ""
echo "==> Installing amscrot-airflow..."
pip install -e "${SCRIPT_DIR}" --quiet

echo ""
echo "==> Installing apache-airflow[celery] ${AIRFLOW_VERSION}..."
pip install "apache-airflow[celery]==${AIRFLOW_VERSION}" --constraint "${CONSTRAINT_URL}" --quiet

# ------------------------------------------------------------------
# 2. Configure Airflow home and DAGs folder
# ------------------------------------------------------------------
mkdir -p "${AIRFLOW_HOME}/dags"
mkdir -p "${AIRFLOW_HOME}/logs"
mkdir -p "${AIRFLOW_HOME}/plugins"

# Symlink our DAGs folder so Airflow picks them up without copying
DAGS_LINK="${AIRFLOW_HOME}/dags/amscrot_dags"
if [ ! -L "${DAGS_LINK}" ]; then
    ln -s "${SCRIPT_DIR}/dags" "${DAGS_LINK}"
    echo "==> Symlinked ${SCRIPT_DIR}/dags -> ${DAGS_LINK}"
fi

# Minimal airflow.cfg overrides via environment
export AIRFLOW__CORE__DAGS_FOLDER="${AIRFLOW_HOME}/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES="False"
export AIRFLOW__CORE__EXECUTOR="LocalExecutor"
export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="sqlite:///${AIRFLOW_HOME}/airflow.db"
export AIRFLOW__API__PORT="8080"

# ------------------------------------------------------------------
# 3. Initialise the metadata database
# ------------------------------------------------------------------
echo ""
echo "==> Initialising Airflow database..."
airflow db migrate

echo ""
echo "==> Setup complete."
echo ""
echo "    AIRFLOW_HOME   : ${AIRFLOW_HOME}"
echo "    DAGs folder    : ${AIRFLOW_HOME}/dags"
echo "    Web UI         : http://localhost:8080"
echo ""
echo "    NOTE (Airflow 3): standalone prints the admin username/password"
echo "    to stdout on first launch -- look for a line like:"
echo "      Login with username: admin  password: <random>"
echo "    To trigger a DAG via REST API after the scheduler has parsed it:"
echo "      curl -X POST http://localhost:8080/api/v2/dags/esnet_iri_example/dagRuns"
echo "           -H 'Content-Type: application/json'"
echo "           -u 'admin:<password>' -d '{}'"
echo ""

# ------------------------------------------------------------------
# 5. Optionally start standalone Airflow
# ------------------------------------------------------------------
if [[ "${1:-}" == "--start" ]]; then
    echo "==> Starting Airflow standalone (Ctrl+C to stop)..."
    echo "    AIRFLOW_HOME=${AIRFLOW_HOME}"
    echo ""
    exec airflow standalone
else
    echo "    To start Airflow manually, run:"
    echo "      export AIRFLOW_HOME=${AIRFLOW_HOME}"
    echo "      airflow standalone"
fi
