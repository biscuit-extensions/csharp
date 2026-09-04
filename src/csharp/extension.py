from __future__ import annotations

import typing

from biscuit.extensions import Extension

if typing.TYPE_CHECKING:
    from biscuit.api import ExtensionsAPI


class CSharp(Extension):
    """C# language support, .NET build runner, and solution management"""

    def __init__(self, api: ExtensionsAPI) -> None:
        super().__init__(api)
        self.api = api
        self.api.logger.info("C# extension initialised.")

    def build_run_command(self, project_path: str | None = None) -> str:
        if project_path:
            return f'dotnet run --project "{project_path}"'
        return 'dotnet run'

    def build_build_command(self, target: str | None = None) -> str:
        if target:
            return f'dotnet build "{target}"'
        return 'dotnet build'

    def build_test_command(self, target: str | None = None) -> str:
        if target:
            return f'dotnet test "{target}"'
        return 'dotnet test'

    def detect_solution_files(self, directory: str) -> list[str]:
        import os
        found = []
        if not os.path.isdir(directory):
            return found
        for f in os.listdir(directory):
            if f.endswith(".sln") or f.endswith(".csproj"):
                found.append(f)
        return found

    def install(self) -> None:
        self.api.logger.info("C# extension installed.")
