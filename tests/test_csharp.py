from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.csharp import setup
from src.csharp.extension import CSharp


class TestCSharpExtension:
    def test_setup_and_registration(self, mock_api) -> None:
        setup(mock_api)
        assert "csharp" in mock_api.registered_extensions
        ext = mock_api.registered_extensions["csharp"]
        assert isinstance(ext, CSharp)

    def test_install_registers_commands_and_integrations(self, mock_api) -> None:
        ext = CSharp(mock_api)
        ext.install()

        # Commands
        commands = mock_api.commands.commands
        assert "csharp.build" in commands
        assert "csharp.run" in commands
        assert "csharp.test" in commands
        assert "csharp.restore" in commands
        assert "csharp.clean" in commands

        # Core registrations
        mock_api.register_comment_prefix.assert_called_with("csharp", "//")
        mock_api.register_langserver.assert_called_with("csharp", "csharp-ls")
        mock_api.register_run_command.assert_called_with("csharp", "dotnet run")

        # Statusbar
        assert ext.statusbar_button is not None
        assert ext.statusbar_button.visible is True

    def test_detect_solution_files(self, mock_api, tmp_path) -> None:
        ext = CSharp(mock_api)
        (tmp_path / "MySolution.sln").write_text("", encoding="utf-8")
        (tmp_path / "MyProject.csproj").write_text("", encoding="utf-8")
        (tmp_path / "README.md").write_text("", encoding="utf-8")

        found = ext.detect_solution_files(str(tmp_path))
        assert "MySolution.sln" in found
        assert "MyProject.csproj" in found
        assert "README.md" not in found

    def test_find_solution_or_project(self, mock_api, tmp_path) -> None:
        ext = CSharp(mock_api)
        root = tmp_path / "App"
        sub = root / "src" / "Controllers"
        sub.mkdir(parents=True)
        sln_file = root / "App.sln"
        sln_file.write_text("Microsoft Visual Studio Solution File", encoding="utf-8")

        found = ext.find_solution_or_project(str(sub))
        assert found == sln_file

    def test_parse_solution(self, mock_api) -> None:
        ext = CSharp(mock_api)
        sample_sln = """
Microsoft Visual Studio Solution File, Format Version 12.00
# Visual Studio Version 17
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "WebApi", "src\\WebApi\\WebApi.csproj", "{A1B2C3D4-E5F6-7890-1234-567890ABCDEF}"
EndProject
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Core", "src\\Core\\Core.csproj", "{FEDCBA09-8765-4321-0987-654321FEDCBA}"
EndProject
Global
    GlobalSection(SolutionConfigurationPlatforms) = preSolution
        Debug|Any CPU = Debug|Any CPU
        Release|Any CPU = Release|Any CPU
    EndGlobalSection
EndGlobal
"""
        parsed = ext.parse_solution(sample_sln)
        assert len(parsed["projects"]) == 2
        assert parsed["projects"][0]["name"] == "WebApi"
        assert parsed["projects"][0]["path"] == "src/WebApi/WebApi.csproj"
        assert parsed["projects"][0]["guid"] == "A1B2C3D4-E5F6-7890-1234-567890ABCDEF"

        assert parsed["projects"][1]["name"] == "Core"
        assert parsed["projects"][1]["path"] == "src/Core/Core.csproj"

        assert "Debug|Any CPU" in parsed["configurations"]
        assert "Release|Any CPU" in parsed["configurations"]

    def test_parse_csproj(self, mock_api) -> None:
        ext = CSharp(mock_api)
        sample_csproj = r"""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
    <PackageReference Include="Microsoft.Extensions.Logging" Version="8.0.0" />
    <ProjectReference Include="..\Core\Core.csproj" />
  </ItemGroup>
</Project>"""

        parsed = ext.parse_csproj(sample_csproj)
        assert parsed["target_framework"] == "net8.0"
        assert parsed["output_type"] == "Exe"
        assert parsed["nullable"] == "enable"
        assert parsed["implicit_usings"] == "enable"

        assert len(parsed["package_references"]) == 2
        packages = {p["name"]: p["version"] for p in parsed["package_references"]}
        assert packages["Newtonsoft.Json"] == "13.0.3"
        assert packages["Microsoft.Extensions.Logging"] == "8.0.0"

        assert len(parsed["project_references"]) == 1
        assert parsed["project_references"][0] == "../Core/Core.csproj"

    def test_build_commands(self, mock_api) -> None:
        ext = CSharp(mock_api)

        # Build command
        b_cmd = ext.build_build_command("src/WebApi.csproj", config="Release", no_restore=True)
        assert 'dotnet build "src/WebApi.csproj" -c Release --no-restore' == b_cmd

        # Run command
        r_cmd = ext.build_run_command("src/WebApi.csproj", config="Debug", args=["--urls", "http://*:5000"])
        assert 'dotnet run --project "src/WebApi.csproj" -c Debug -- --urls http://*:5000' == r_cmd

        # Test command
        t_cmd = ext.build_test_command("tests/WebApi.Tests.csproj", filter_expr="Category=Unit", no_build=True)
        assert 'dotnet test "tests/WebApi.Tests.csproj" --filter "Category=Unit" --no-build' == t_cmd

    def test_parse_msbuild_output_errors_and_warnings(self, mock_api) -> None:
        ext = CSharp(mock_api)
        sample_output = """
Microsoft (R) Build Engine version 17.8.3+195e4f5a3 for .NET
Copyright (C) Microsoft Corporation. All rights reserved.

  Determining projects to restore...
Program.cs(14,18): error CS0103: The name 'myVariable' does not exist in the current context [C:\\App\\App.csproj]
Services/AuthService.cs(25,9): warning CS0219: The variable 'token' is assigned but its value is never used [C:\\App\\App.csproj]

Build FAILED.

       1 Warning(s)
       1 Error(s)

Time Elapsed 00:00:02.45
"""
        report = ext.parse_msbuild_output(sample_output)
        assert report["succeeded"] is False
        assert report["error_count"] == 1
        assert report["warning_count"] == 1
        assert report["time_elapsed"] == "00:00:02.45"

        assert len(report["errors"]) == 1
        assert report["errors"][0]["file"] == "Program.cs"
        assert report["errors"][0]["line"] == 14
        assert report["errors"][0]["col"] == 18
        assert report["errors"][0]["code"] == "CS0103"
        assert "myVariable" in report["errors"][0]["message"]

        assert len(report["warnings"]) == 1
        assert report["warnings"][0]["file"] == "Services/AuthService.cs"
        assert report["warnings"][0]["line"] == 25
        assert report["warnings"][0]["code"] == "CS0219"

    def test_parse_test_output(self, mock_api) -> None:
        ext = CSharp(mock_api)
        sample_test_output = """
Test run for C:\\App\\bin\\Debug\\net8.0\\App.Tests.dll (.NETCoreApp,Version=v8.0)
Microsoft (R) Test Execution Command Line Tool Version 17.8.0
Copyright (c) Microsoft Corporation.  All rights reserved.

Starting test execution, please wait...
A total of 1 test files matched the specified pattern.
  Passed App.Tests.UnitTest1.TestSuccess [24 ms]
  Failed App.Tests.UnitTest1.TestFailure [5 ms]
  Skipped App.Tests.UnitTest1.TestIgnored [1 ms]

Passed!  - Failed:     1, Passed:     8, Skipped:     1, Total:    10, Duration: 150 ms - App.Tests.dll (net8.0)
"""
        parsed = ext.parse_test_output(sample_test_output)
        assert parsed["total"] == 10
        assert parsed["passed"] == 8
        assert parsed["failed"] == 1
        assert parsed["skipped"] == 1
        assert parsed["duration"] == "150 ms - App.Tests.dll (net8.0)"
        assert len(parsed["tests"]) == 3

    def test_command_handlers(self, mock_api) -> None:
        ext = CSharp(mock_api)
        ext.install()

        # Build command
        ext.build_command_handler()
        assert len(mock_api.terminalmanager.opened_terminals) == 1
        assert "dotnet build" in mock_api.terminalmanager.opened_terminals[0]

        # Run command
        ext.run_command_handler()
        assert len(mock_api.terminalmanager.opened_terminals) == 2
        assert "dotnet run" in mock_api.terminalmanager.opened_terminals[1]

        # Restore command
        ext.restore_command_handler()
        assert "dotnet restore" in mock_api.terminalmanager.opened_terminals[2]

        # Clean command
        ext.clean_command_handler()
        assert "dotnet clean" in mock_api.terminalmanager.opened_terminals[3]

        # Show info
        with patch.object(ext, "get_dotnet_version", return_value="8.0.100"):
            info = ext.show_dotnet_info_command()
            assert info["sdk"] == "8.0.100"
            mock_api.notifications.info.assert_called()

    def test_manifest_schema_and_dependencies(self) -> None:
        import tomllib

        manifest_path = Path(__file__).parent.parent / "extension.toml"
        assert manifest_path.exists()
        with open(manifest_path, "rb") as f:
            data = tomllib.load(f)

        assert data["extension"]["id"] == "csharp"
        assert data["extension"]["author"] == "tomlin7"
        assert data["extension"]["version"] == "0.2.0"
        assert "defusedxml>=0.7.1" in data["dependencies"]["python"]
        assert "dotnet" in data["dependencies"]["tools"]
        assert len(data["contributes"]["commands"]) >= 5
