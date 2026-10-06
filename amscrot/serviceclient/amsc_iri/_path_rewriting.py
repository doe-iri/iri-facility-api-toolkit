"""Thin shim around generated IRI ``ApiClient`` classes for path-prefix rewriting.

The auto-generated ``amsc_iri`` and ``amsc_iri_v2`` packages hardcode paths
like ``/api/v1/facility`` in every API method.  Most IRI facilities follow
this convention, but some (e.g. PNNL) use *bare* paths -- ``/v1/facility`` --
without the ``/api/`` prefix.

Rather than modifying or post-processing the generated code, this module
provides a factory that wraps any generated ``ApiClient`` to transparently
rewrite the path prefix on every outgoing request.

The *path_prefix* controls what replaces the leading ``/api`` segment that
the generated code assumes.  The default (``/api``) is a no-op.  Setting it
to ``""`` (empty string) yields the bare paths PNNL expects.

Usage from a versioned service client::

    from amsc_iri.api_client import ApiClient
    from amscrot.serviceclient.amsc_iri._path_rewriting import (
        make_path_rewriting_client,
    )

    # Standard facility -- no rewriting, just pass through.
    client = make_path_rewriting_client(ApiClient, configuration, path_prefix="/api")

    # Bare-path facility -- strip the '/api' prefix from every resource_path.
    client = make_path_rewriting_client(ApiClient, configuration, path_prefix="")

Consumers can also set ``path_prefix`` in ``~/.amscrot/credentials.yml``::

    nersc:
      client_type: IRI
      api_endpoint: https://iri-dev.ppg.es.net
      pat_file: ~/.amsc_token.json
      # path_prefix: /api          <-- default, can be omitted

    pnnl:
      client_type: IRI
      api_endpoint: https://pnnl-iri.example.org
      pat_file: ~/.amsc_token.json
      path_prefix: ""              <-- bare-path facility

.. note::

   The shim only modifies ``param_serialize``; all other ``ApiClient``
   behaviour -- authentication, serialisation, error handling -- is
   unchanged.
"""

from __future__ import annotations

from typing import Type, TypeVar

T = TypeVar("T")

#: The path prefix the generated bindings hardcode in every ``resource_path``.
GENERATED_PREFIX = "/api"


def make_path_rewriting_client(
    api_client_cls: Type[T],
    configuration,
    *,
    path_prefix: str = GENERATED_PREFIX,
) -> T:
    """Return an ``ApiClient`` instance that rewrites the ``/api`` prefix.

    If *path_prefix* equals the generated default (``"/api"``), returns a
    plain ``api_client_cls(configuration)`` -- no subclass overhead.

    Otherwise, returns a dynamically-created subclass whose
    ``param_serialize`` strips the hardcoded ``/api`` prefix from
    ``resource_path`` and replaces it with *path_prefix*.

    Args:
        api_client_cls: The generated ``ApiClient`` class (v1 or v2).
        configuration: A generated ``Configuration`` instance, already
            populated with ``host``, ``api_key``, etc.
        path_prefix: The prefix to use instead of ``/api``.  Common values:

            * ``"/api"`` -- standard facilities (no-op, default).
            * ``""`` -- bare-path facilities like PNNL.

    Returns:
        An ``ApiClient`` (or subclass) instance.
    """
    if path_prefix == GENERATED_PREFIX:
        # Standard facility -- skip the shim entirely.
        return api_client_cls(configuration)

    class _RewritingClient(api_client_cls):  # type: ignore[misc]
        """``ApiClient`` that rewrites the ``/api`` prefix in resource paths."""

        _rewrite_from: str = GENERATED_PREFIX
        _rewrite_to: str = path_prefix

        def param_serialize(
            self,
            method,
            resource_path,
            path_params=None,
            query_params=None,
            header_params=None,
            body=None,
            post_params=None,
            files=None,
            auth_settings=None,
            collection_formats=None,
            _host=None,
            _request_auth=None,
        ):
            # Rewrite: /api/v1/facility -> /v1/facility  (when _rewrite_to="")
            if resource_path.startswith(self._rewrite_from):
                resource_path = (
                    self._rewrite_to + resource_path[len(self._rewrite_from) :]
                )
            return super().param_serialize(
                method,
                resource_path,
                path_params=path_params,
                query_params=query_params,
                header_params=header_params,
                body=body,
                post_params=post_params,
                files=files,
                auth_settings=auth_settings,
                collection_formats=collection_formats,
                _host=_host,
                _request_auth=_request_auth,
            )

    # Give the dynamic class a meaningful name for debugging.
    _RewritingClient.__name__ = (
        "%s[prefix=%r]" % (api_client_cls.__name__, path_prefix)
    )
    _RewritingClient.__qualname__ = _RewritingClient.__name__

    return _RewritingClient(configuration)
