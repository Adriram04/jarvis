"""
Tests for AI Tool Definitions and Handlers.
"""
import pytest
import os
import sys
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))


class TestToolDefinitions:
    """Test tool definition schemas."""
    
    def test_generate_cad_tool_schema(self):
        """Test generate_cad tool has correct schema."""
        from jarvis import generate_cad
        
        assert generate_cad['name'] == 'generate_cad'
        assert 'description' in generate_cad
        assert 'parameters' in generate_cad
        assert generate_cad['parameters']['type'] == 'OBJECT'
        assert 'prompt' in generate_cad['parameters']['properties']
        print(f"generate_cad tool: {generate_cad['name']}")
    
    def test_run_web_agent_tool_schema(self):
        """Test run_web_agent tool has correct schema."""
        from jarvis import run_web_agent
        
        assert run_web_agent['name'] == 'run_web_agent'
        assert 'description' in run_web_agent
        assert 'parameters' in run_web_agent
        assert 'prompt' in run_web_agent['parameters']['properties']
        print(f"run_web_agent tool: {run_web_agent['name']}")

    def test_create_directory_tool_schema(self):
        """Test create_directory tool has correct schema."""
        from jarvis import create_directory_tool

        assert create_directory_tool['name'] == 'create_directory'
        assert 'description' in create_directory_tool
        assert 'parameters' in create_directory_tool
        assert create_directory_tool['parameters']['type'] == 'OBJECT'
        assert 'path' in create_directory_tool['parameters']['properties']
        assert create_directory_tool['parameters']['required'] == ['path']
        print(f"create_directory tool: {create_directory_tool['name']}")
    
    def test_print_stl_tool_schema(self):
        """Test print_stl tool has correct schema."""
        from jarvis import print_stl_tool
        
        assert print_stl_tool['name'] == 'print_stl'
        assert 'description' in print_stl_tool
        assert 'parameters' in print_stl_tool
        print(f"print_stl tool: {print_stl_tool['name']}")
    
    def test_discover_printers_tool_schema(self):
        """Test discover_printers tool has correct schema."""
        from jarvis import discover_printers_tool
        
        assert discover_printers_tool['name'] == 'discover_printers'
        assert 'description' in discover_printers_tool
        print(f"discover_printers tool: {discover_printers_tool['name']}")
    
    def test_list_smart_devices_tool_schema(self):
        """Test list_smart_devices tool has correct schema."""
        from jarvis import list_smart_devices_tool
        
        assert list_smart_devices_tool['name'] == 'list_smart_devices'
        assert 'description' in list_smart_devices_tool
        print(f"list_smart_devices tool: {list_smart_devices_tool['name']}")
    
    def test_control_light_tool_schema(self):
        """Test control_light tool has correct schema."""
        from jarvis import control_light_tool
        
        assert control_light_tool['name'] == 'control_light'
        assert 'parameters' in control_light_tool
        props = control_light_tool['parameters']['properties']
        assert 'target' in props
        assert 'action' in props
        print(f"control_light tool: {control_light_tool['name']}")
    
    def test_list_projects_tool_schema(self):
        """Test list_projects tool has correct schema."""
        from jarvis import list_projects_tool
        
        assert list_projects_tool['name'] == 'list_projects'
        print(f"list_projects tool: {list_projects_tool['name']}")
    
    def test_iterate_cad_tool_schema(self):
        """Test iterate_cad tool has correct schema."""
        from jarvis import iterate_cad_tool
        
        assert iterate_cad_tool['name'] == 'iterate_cad'
        print(f"iterate_cad tool: {iterate_cad_tool['name']}")


class TestAudioLoopClass:
    """Test AudioLoop class structure."""
    
    def test_audioloop_class_exists(self):
        """Test AudioLoop class can be imported."""
        from jarvis import AudioLoop
        assert AudioLoop is not None
        print("AudioLoop class imported successfully")
    
    def test_audioloop_methods(self):
        """Test AudioLoop has required methods."""
        from jarvis import AudioLoop
        
        required_methods = [
            'run',
            'stop',
            'send_frame',
            'listen_audio',
            'receive_audio',
            'play_audio',
            'handle_cad_request',
            'handle_web_agent_request',
            'resolve_tool_confirmation',
            'update_permissions',
            'set_paused',
            'clear_audio_queue',
        ]
        
        for method in required_methods:
            assert hasattr(AudioLoop, method), f"Missing method: {method}"
            print(f"  ✓ {method}")


class TestFileOperations:
    """Test file operation handlers."""
    
    def test_create_directory_method_exists(self):
        """Test handle_create_directory exists."""
        from jarvis import AudioLoop
        assert hasattr(AudioLoop, 'handle_create_directory')

    def test_read_directory_method_exists(self):
        """Test handle_read_directory exists."""
        from jarvis import AudioLoop
        assert hasattr(AudioLoop, 'handle_read_directory')
    
    def test_read_file_method_exists(self):
        """Test handle_read_file exists."""
        from jarvis import AudioLoop
        assert hasattr(AudioLoop, 'handle_read_file')
    
    def test_write_file_method_exists(self):
        """Test handle_write_file exists."""
        from jarvis import AudioLoop
        assert hasattr(AudioLoop, 'handle_write_file')

    def test_project_path_resolution_blocks_escape(self, tmp_path):
        """Test project-rooted paths cannot escape the current project."""
        from jarvis import AudioLoop

        project_path = tmp_path / "projects" / "Demo"
        project_path.mkdir(parents=True)

        class DummyProjectManager:
            current_project = "Demo"

            def get_current_project_path(self):
                return project_path

        loop = object.__new__(AudioLoop)
        loop.project_manager = DummyProjectManager()

        assert loop._resolve_project_path("docs/specs") == (project_path / "docs" / "specs").resolve()

        with pytest.raises(ValueError):
            loop._resolve_project_path("../outside")

    @pytest.mark.asyncio
    async def test_handle_create_directory_creates_folder(self, tmp_path):
        """Test handle_create_directory creates nested folders in the project."""
        from jarvis import AudioLoop

        project_path = tmp_path / "projects" / "Demo"
        project_path.mkdir(parents=True)

        class DummyProjectManager:
            current_project = "Demo"

            def get_current_project_path(self):
                return project_path

        class DummySession:
            async def send(self, input, end_of_turn):
                self.last_message = input

        loop = object.__new__(AudioLoop)
        loop.project_manager = DummyProjectManager()
        loop.session = DummySession()
        loop.on_project_update = None

        await loop.handle_create_directory("docs/specs")

        assert (project_path / "docs" / "specs").is_dir()
        assert "created successfully" in loop.session.last_message

    @pytest.mark.asyncio
    async def test_handle_write_file_blocks_project_escape(self, tmp_path):
        """Test handle_write_file rejects paths outside the project."""
        from jarvis import AudioLoop

        project_path = tmp_path / "projects" / "Demo"
        project_path.mkdir(parents=True)
        outside_path = project_path.parent / "outside.txt"

        class DummyProjectManager:
            current_project = "Demo"

            def get_current_project_path(self):
                return project_path

        class DummySession:
            async def send(self, input, end_of_turn):
                self.last_message = input

        loop = object.__new__(AudioLoop)
        loop.project_manager = DummyProjectManager()
        loop.session = DummySession()
        loop.on_project_update = None

        await loop.handle_write_file("../outside.txt", "secret")

        assert not outside_path.exists()
        assert "Path must stay inside the current project" in loop.session.last_message

    @pytest.mark.asyncio
    async def test_handle_read_file_uses_project_root(self, tmp_path):
        """Test handle_read_file reads only from the current project."""
        from jarvis import AudioLoop

        project_path = tmp_path / "projects" / "Demo"
        project_path.mkdir(parents=True)
        safe_file = project_path / "notes.txt"
        safe_file.write_text("project note", encoding="utf-8")
        outside_file = project_path.parent / "outside.txt"
        outside_file.write_text("outside secret", encoding="utf-8")

        class DummyProjectManager:
            current_project = "Demo"

            def get_current_project_path(self):
                return project_path

        class DummySession:
            async def send(self, input, end_of_turn):
                self.last_message = input

        loop = object.__new__(AudioLoop)
        loop.project_manager = DummyProjectManager()
        loop.session = DummySession()

        await loop.handle_read_file("notes.txt")
        assert "project note" in loop.session.last_message

        await loop.handle_read_file("../outside.txt")
        assert "outside secret" not in loop.session.last_message
        assert "Path must stay inside the current project" in loop.session.last_message

    @pytest.mark.asyncio
    async def test_handle_read_directory_uses_project_root(self, tmp_path):
        """Test handle_read_directory lists only project-rooted directories."""
        from jarvis import AudioLoop

        project_path = tmp_path / "projects" / "Demo"
        docs_path = project_path / "docs"
        docs_path.mkdir(parents=True)
        (docs_path / "safe.txt").write_text("ok", encoding="utf-8")
        outside_dir = project_path.parent / "outside"
        outside_dir.mkdir()
        (outside_dir / "secret.txt").write_text("secret", encoding="utf-8")

        class DummyProjectManager:
            current_project = "Demo"

            def get_current_project_path(self):
                return project_path

        class DummySession:
            async def send(self, input, end_of_turn):
                self.last_message = input

        loop = object.__new__(AudioLoop)
        loop.project_manager = DummyProjectManager()
        loop.session = DummySession()

        await loop.handle_read_directory("docs")
        assert "safe.txt" in loop.session.last_message

        await loop.handle_read_directory("../outside")
        assert "secret.txt" not in loop.session.last_message
        assert "Path must stay inside the current project" in loop.session.last_message


class TestLiveConnectConfig:
    """Test Gemini Live Connect configuration."""
    
    def test_config_exists(self):
        """Test config is defined."""
        from jarvis import config
        assert config is not None
        print("LiveConnectConfig exists")
    
    def test_config_has_audio_modality(self):
        """Test config includes audio modality."""
        from jarvis import config
        assert 'AUDIO' in config.response_modalities
        print("Audio modality configured")


class TestToolPermissions:
    """Test tool permission handling."""
    
    def test_update_permissions_method(self):
        """Test update_permissions method exists."""
        from jarvis import AudioLoop
        assert hasattr(AudioLoop, 'update_permissions')
        print("update_permissions method exists")


class TestAgentImports:
    """Test agent module imports in jarvis.py."""
    
    def test_cad_agent_import(self):
        """Test CadAgent is imported."""
        from jarvis import CadAgent
        assert CadAgent is not None
        print("CadAgent imported")
    
    def test_web_agent_import(self):
        """Test WebAgent is imported."""
        from jarvis import WebAgent
        assert WebAgent is not None
        print("WebAgent imported")
    
    def test_kasa_agent_import(self):
        """Test KasaAgent is imported."""
        from jarvis import KasaAgent
        assert KasaAgent is not None
        print("KasaAgent imported")
    
    def test_printer_agent_import(self):
        """Test PrinterAgent is imported."""
        from jarvis import PrinterAgent
        assert PrinterAgent is not None
        print("PrinterAgent imported")


class TestToolConfirmation:
    """Test tool confirmation handling."""
    
    def test_resolve_tool_confirmation_method(self):
        """Test resolve_tool_confirmation exists."""
        from jarvis import AudioLoop
        assert hasattr(AudioLoop, 'resolve_tool_confirmation')
        print("resolve_tool_confirmation method exists")
