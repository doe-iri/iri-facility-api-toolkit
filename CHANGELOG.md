# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v1.2.0] - 2026-07-06

### Added
- **Native IRI JobSpec Passthrough**: Added the ability to pass a native `IriJobSpec` object directly into the `Job` constructor (`job_spec` parameter), bypassing generic `JobSpec` translation.
- **In-Memory File Uploads**: Supported uploading in-memory bytes/data streams directly via the remote filesystem interface without requiring writing to local files first.
- **Historical Job Reads**: Exposed a `historical` parameter on the facility client/resource `jobs()` methods to fetch jobs that are no longer in the active scheduler queue.
- **Discovery Metadata Normalization**: Added support for converting raw native discovery items to structured, strongly-typed model hierarchies (e.g. `Facility`, `Project`, `ProjectAllocation`, `UserAllocation`, `Compute`, `Storage`, `Network`, `Allocation`).
- **Discovery Metadata Caching & `session.metadata`**: Introduced a local, TTL-based file cache (`DiscoveryCache`) under `~/.amscrot/metadata/discovery/` and exposed a convenience `session.metadata()` method to query cache-backed (or live) service client discovery information in both native and normalized formats.
- **`uv` Package & Dependency Support**: Reorganized project metadata to move all dependencies from `requirements.txt` to standard PEP 621 dependencies/extras in `pyproject.toml` with `uv` package manager lockfile support.

### Changed
- **First-Class Job `resource_id`**: Promoted `resource_id` to a first-class parameter in the `Job` constructor. The IRI service client now reads it directly from the job object instead of extracting it from `job_spec.attributes`.
- **Lean Dependency Isolation**: Guarded heavy external optional imports (such as `kubernetes`, `sense`, and `paramiko`) so that the core package can be installed, imported, and tested cleanly without requiring optional extras.

## [v1.1.0] - 2026-06-05

- Last stable release with legacy `JobSpec.attributes` resource ID parsing.
