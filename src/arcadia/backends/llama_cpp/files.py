"""Exact Hugging Face cache and download resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from arcadia.models import HuggingFaceFileSpec, ServiceStartupError, ServiceState
from arcadia.services import BackendProgressReporter

FileRole = Literal["model", "projector"]


class FileResolver(Protocol):
    def resolve(
        self,
        file_spec: HuggingFaceFileSpec,
        *,
        role: FileRole,
        progress: BackendProgressReporter,
    ) -> Path: ...


class HuggingFaceFileResolver:
    """Resolve one exact Hub file, preferring the configured local cache."""

    def __init__(self, *, cache_dir: Path | None = None) -> None:
        self._cache_dir = None if cache_dir is None else Path(cache_dir)

    def resolve(
        self,
        file_spec: HuggingFaceFileSpec,
        *,
        role: FileRole,
        progress: BackendProgressReporter,
    ) -> Path:
        progress.report(state=ServiceState.RESOLVING, message=f"Resolving {role} file")
        try:
            from huggingface_hub import hf_hub_download
            from huggingface_hub.errors import LocalEntryNotFoundError
        except (ImportError, ModuleNotFoundError) as exc:
            raise ServiceStartupError(
                "llama.cpp backend requires the llama optional dependencies",
                code="llama_cpp_dependency_missing",
                details={"dependency": "huggingface_hub"},
                cause=exc,
            ) from exc

        try:
            path_text = hf_hub_download(
                repo_id=file_spec.repo_id,
                filename=file_spec.filename,
                revision=file_spec.revision,
                cache_dir=self._cache_dir,
                local_files_only=True,
            )
        except LocalEntryNotFoundError:
            progress.report(state=ServiceState.DOWNLOADING, progress=None, message=f"Downloading {role} file")
            try:
                path_text = hf_hub_download(
                    repo_id=file_spec.repo_id,
                    filename=file_spec.filename,
                    revision=file_spec.revision,
                    cache_dir=self._cache_dir,
                )
            except Exception as exc:
                raise self._resolution_error(file_spec, role, exc) from exc
        except Exception as exc:
            raise self._resolution_error(file_spec, role, exc) from exc

        path = Path(path_text)
        try:
            is_file = path.is_file()
        except Exception as exc:
            raise self._resolution_error(file_spec, role, exc) from exc
        if not is_file:
            path_error = FileNotFoundError("Hub resolver returned a path that is not a regular file")
            raise self._resolution_error(file_spec, role, path_error) from path_error
        return path

    @staticmethod
    def _resolution_error(
        file_spec: HuggingFaceFileSpec,
        role: FileRole,
        cause: Exception,
    ) -> ServiceStartupError:
        return ServiceStartupError(
            f"Failed to resolve llama.cpp {role} file",
            code="llama_cpp_model_resolve_failed",
            details={
                "repo_id": file_spec.repo_id,
                "filename": file_spec.filename,
                "revision": file_spec.revision,
                "role": role,
                "exception_type": type(cause).__name__,
            },
            cause=cause,
        )
