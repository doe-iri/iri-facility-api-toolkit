"""Unit tests for amscrot.client.async_client and amscrot.client.async_session."""

import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from amscrot.client.async_client import AsyncClient
from amscrot.client.async_session import AsyncSession
from amscrot.client.models import Provider, Session, WaitTimeoutError
from amscrot.client.job import Job, JobSpec, JobType, JobServiceType, JobState, JobStatus


# ── AsyncClient tests ─────────────────────────────────────────────────────


class TestAsyncClientInit:
    """Constructor should not perform I/O."""

    def test_creates_without_io(self):
        client = AsyncClient()
        assert isinstance(client, AsyncClient)
        assert client._providers == []
        assert client._service_clients == {}

    def test_deferred_flags_set(self):
        client = AsyncClient(
            create_service_clients=True, discover_endpoints=True
        )
        assert client._deferred_create_service_clients is True
        assert client._deferred_discover_endpoints is True


class TestAsyncClientCredentials:
    """In-memory credential methods are synchronous."""

    def test_add_credential_sync(self):
        client = AsyncClient()
        client.add_credential(profile="test", api_key="abc")
        assert "test" in client._credentials
        assert client._credentials["test"].api_key == "abc"

    def test_update_credential_sync(self):
        client = AsyncClient()
        client.add_credential(profile="test", api_key="abc")
        client.update_credential(profile="test", api_key="xyz")
        assert client._credentials["test"].api_key == "xyz"

    def test_update_missing_profile_raises(self):
        client = AsyncClient()
        with pytest.raises(ValueError, match="not found"):
            client.update_credential(profile="missing", api_key="xyz")

    def test_get_credential_sync(self):
        client = AsyncClient()
        client.add_credential(profile="test", api_key="abc")
        cred = client.get_credential("test")
        assert cred.api_key == "abc"

    def test_list_credentials_sync(self):
        client = AsyncClient()
        client.add_credential(profile="a")
        client.add_credential(profile="b")
        assert set(client.list_credentials()) == {"a", "b"}


class TestAsyncClientProvider:
    """Provider management is synchronous."""

    def test_add_provider_sync(self):
        client = AsyncClient()
        client.add_credential(profile="p1", api_key="key")
        provider = client.add_provider(label="myp", type="cloud", profile="p1")
        assert isinstance(provider, Provider)
        assert provider.label == "myp"
        assert len(client._providers) == 1

    def test_add_provider_missing_profile_raises(self):
        client = AsyncClient()
        with pytest.raises(ValueError, match="not found"):
            client.add_provider(label="myp", type="cloud", profile="nonexistent")


class TestAsyncClientServiceClient:
    """Service client management is synchronous."""

    def test_add_service_client_sync(self):
        client = AsyncClient()
        mock_sc = MagicMock()
        mock_sc.name = "test-sc"
        result = client.add_service_client(mock_sc)
        assert result is mock_sc
        assert "test-sc" in client._service_clients

    def test_get_service_client_by_name(self):
        client = AsyncClient()
        mock_sc = MagicMock()
        mock_sc.name = "nersc"
        client.add_service_client(mock_sc)
        assert client.get_service_client("nersc") is mock_sc

    def test_get_service_client_returns_list_when_none(self):
        client = AsyncClient()
        mock_sc = MagicMock()
        mock_sc.name = "nersc"
        client.add_service_client(mock_sc)
        result = client.get_service_client(None)
        assert isinstance(result, list)
        assert mock_sc in result

    def test_get_service_client_returns_none_for_unknown(self):
        client = AsyncClient()
        assert client.get_service_client("unknown") is None


class TestAsyncClientFacility:
    """Facility factory is synchronous."""

    def test_facility_returns_async_facility_client(self):
        client = AsyncClient()
        with patch("amscrot.facility.async_client.AsyncFacilityClient") as MockAFC:
            result = client.facility("https://example.com", token="tok")
            MockAFC.assert_called_once_with(
                endpoint="https://example.com",
                token="tok",
                token_provider=None,
                name=None,
            )


class TestAsyncClientLoadCredentials:
    """load_credentials is async (file I/O)."""

    @pytest.mark.asyncio
    async def test_load_credentials_default_missing(self):
        """When default file doesn't exist, credentials stay empty."""
        client = AsyncClient()
        with patch("os.path.exists", return_value=False):
            await client.load_credentials()
        assert client._credentials == {}

    @pytest.mark.asyncio
    async def test_load_credentials_from_file(self):
        """Load credentials from a YAML file."""
        client = AsyncClient()
        fake_creds = {"profile1": {"api_key": "key1", "client_type": "AMSC_IRI"}}
        with patch("amscrot.util.utils.load_yaml_from_file", return_value=fake_creds):
            await client.load_credentials(file_path="/fake/path.yml")
        assert "profile1" in client._credentials
        assert client._credentials["profile1"].api_key == "key1"


class TestAsyncClientCreateSession:
    """create_session is async (disk state hydration)."""

    @pytest.mark.asyncio
    async def test_create_session_returns_async_session(self):
        client = AsyncClient()
        with patch.object(client, "_hydrate_session"):
            session = await client.create_session("test-session")
        assert isinstance(session, AsyncSession)
        assert session.name == "test-session"
        assert session in client._sessions


class TestAsyncClientInitialize:
    """initialize() drives deferred I/O."""

    @pytest.mark.asyncio
    async def test_initialize_loads_credentials(self):
        client = AsyncClient(create_service_clients=True)
        with patch.object(client, "load_credentials", new_callable=AsyncMock) as mock_load, \
             patch.object(client, "_sync_create_service_clients_from_credentials"):
            await client.initialize()
        mock_load.assert_called_once()
        assert client._deferred_create_service_clients is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        with patch.object(AsyncClient, "initialize", new_callable=AsyncMock) as mock_init:
            async with AsyncClient() as client:
                assert isinstance(client, AsyncClient)
            mock_init.assert_called_once()


class TestAsyncClientHelpers:
    """Static/class helpers."""

    def test_normalize_endpoint(self):
        assert AsyncClient._normalize_endpoint("https://api.nersc.gov/v1/path") == "https://api.nersc.gov"

    def test_slugify(self):
        assert AsyncClient._slugify("My Facility Name") == "my-facility-name"

    def test_get_shorthand_nersc(self):
        assert AsyncClient.get_shorthand("NERSC Perlmutter") == "nersc"


# ── AsyncSession tests ────────────────────────────────────────────────────


def _make_async_session(**kwargs):
    """Build an AsyncSession backed by a real Session."""
    sync = Session(name="test", **kwargs)
    return AsyncSession(sync)


class TestAsyncSessionProperties:
    """Properties are synchronous."""

    def test_name(self):
        s = _make_async_session()
        assert s.name == "test"

    def test_jobs_empty(self):
        s = _make_async_session()
        assert s.jobs == []


class TestAsyncSessionSyncMethods:
    """In-memory resource/getter methods are synchronous."""

    def test_add_node_sync(self):
        s = _make_async_session()
        p = Provider("p1", "type1")
        node = s.add_node(label="n1", provider=p)
        assert node.label == "n1"

    def test_add_network_sync(self):
        s = _make_async_session()
        p = Provider("p1", "type1")
        net = s.add_network(label="net1", provider=p)
        assert net.label == "net1"

    def test_add_service_sync(self):
        s = _make_async_session()
        p = Provider("p1", "type1")
        svc = s.add_service(label="svc1", provider=p)
        assert svc.label == "svc1"

    def test_add_job_sync(self):
        s = _make_async_session()
        job = Job(name="j1", type=JobType.COMPUTE, service_type=JobServiceType.BATCH)
        s.add_job(job)
        assert s.get_job("j1") is job

    def test_add_provider_sync(self):
        s = _make_async_session()
        p = Provider("p2", "type2")
        s.add_provider(p)
        assert s.get_provider("p2") is p

    def test_add_service_client_sync(self):
        s = _make_async_session()
        mock_sc = MagicMock()
        mock_sc.name = "sc1"
        s.add_service_client(mock_sc)
        assert s.get_service_client("sc1") is mock_sc

    def test_getters_return_none_for_missing(self):
        s = _make_async_session()
        assert s.get_provider("x") is None
        assert s.get_node("x") is None
        assert s.get_network("x") is None
        assert s.get_service("x") is None
        assert s.get_service_client("x") is None
        assert s.get_job("x") is None

    def test_show_sync(self):
        s = _make_async_session()
        # Should not raise
        s.show(summary=True)

    def test_files_path_sync(self):
        s = _make_async_session()
        path = s.files_path("job1")
        assert "job1" in path


class TestAsyncSessionIOOperations:
    """I/O methods are async."""

    @pytest.mark.asyncio
    async def test_plan_delegates_to_sync(self):
        s = _make_async_session()
        with patch.object(s._sync, "plan", return_value={"resources": {}, "jobs": []}) as mock_plan:
            result = await s.plan(verbose=True)
        mock_plan.assert_called_once_with(verbose=True, skip_checks=False)

    @pytest.mark.asyncio
    async def test_apply_delegates_to_sync(self):
        s = _make_async_session()
        with patch.object(s._sync, "apply", return_value="ok") as mock_apply:
            result = await s.apply()
        mock_apply.assert_called_once()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_destroy_delegates_to_sync(self):
        s = _make_async_session()
        with patch.object(s._sync, "destroy", return_value="destroyed") as mock_destroy:
            result = await s.destroy()
        mock_destroy.assert_called_once()
        assert result == "destroyed"

    @pytest.mark.asyncio
    async def test_metadata_delegates_to_sync(self):
        s = _make_async_session()
        mock_sc = MagicMock()
        mock_sc.name = "sc1"
        s.add_service_client(mock_sc)
        with patch.object(s._sync, "metadata", return_value={"data": True}) as mock_meta:
            result = await s.metadata("sc1", refresh=True)
        mock_meta.assert_called_once_with("sc1", refresh=True, native=True)

    @pytest.mark.asyncio
    async def test_fetch_output_files_delegates_to_sync(self):
        s = _make_async_session()
        with patch.object(s._sync, "fetch_output_files", return_value={}) as mock_fetch:
            result = await s.fetch_output_files()
        mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_returns_on_terminal_state(self):
        """wait() should resolve immediately when all jobs are already terminal."""
        s = _make_async_session()
        mock_sc = MagicMock()
        mock_sc.name = "sc1"
        s.add_service_client(mock_sc)

        job = Job(name="j1", type=JobType.COMPUTE, service_type=JobServiceType.BATCH, service_client=mock_sc)
        s.add_job(job)

        # status() returns COMPLETED on first call
        mock_status = JobStatus(
            state=JobState.COMPLETED.value,
            message="done",
        )
        mock_sc.status.return_value = mock_status

        results = await s.wait(interval=0.01)
        assert "j1" in results
        assert results["j1"].state == JobState.COMPLETED.value

    @pytest.mark.asyncio
    async def test_wait_timeout_raises(self):
        """wait() should raise WaitTimeoutError on timeout."""
        s = _make_async_session()
        mock_sc = MagicMock()
        mock_sc.name = "sc1"
        s.add_service_client(mock_sc)

        job = Job(name="j1", type=JobType.COMPUTE, service_type=JobServiceType.BATCH, service_client=mock_sc)
        s.add_job(job)

        # status() always returns ACTIVE (non-terminal)
        mock_status = JobStatus(state=JobState.ACTIVE.value, message="running")
        mock_sc.status.return_value = mock_status

        with pytest.raises(WaitTimeoutError):
            await s.wait(timeout=0.05, interval=0.01)

    def test_repr(self):
        s = _make_async_session()
        assert "AsyncSession" in repr(s)
        assert "test" in repr(s)
