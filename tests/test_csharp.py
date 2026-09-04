from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.csharp import setup
from src.csharp.extension import CSharp


class TestCSharpExtension:
    def test_extension_setup(self, app_instance) -> None:
        setup(app_instance.api)
        ext = CSharp(app_instance.api)
        assert ext.build_run_command("App.csproj") == 'dotnet run --project "App.csproj"'
        assert ext.build_build_command() == 'dotnet build'
        assert ext.build_test_command("Tests.csproj") == 'dotnet test "Tests.csproj"'
