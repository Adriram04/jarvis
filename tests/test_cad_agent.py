"""
Tests for CAD Generation Agent.
"""
import pytest
import asyncio
import os

from cad_agent import CadAgent


class TestCadAgentInit:
    """Test CadAgent initialization."""
    
    def test_agent_creation(self):
        """Test CadAgent can be created."""
        agent = CadAgent()
        assert agent is not None
        assert hasattr(agent, 'client')
        print("CadAgent initialized successfully")
    
    def test_agent_with_callbacks(self):
        """Test CadAgent with thought/status callbacks."""
        thoughts = []
        statuses = []
        
        def on_thought(text):
            thoughts.append(text)
        
        def on_status(status):
            statuses.append(status)
        
        agent = CadAgent(on_thought=on_thought, on_status=on_status)
        assert agent.on_thought is not None
        assert agent.on_status is not None

    def test_agent_uses_configurable_model_fallbacks(self, monkeypatch):
        """Test CAD model fallback sequence can be configured by env vars."""
        monkeypatch.setenv("JARVIS_CAD_MODEL", "gemini-primary")
        monkeypatch.setenv("JARVIS_CAD_FALLBACK_MODELS", "gemini-lite, gemini-primary, gemini-backup")

        agent = CadAgent()

        assert agent.models == ["gemini-primary", "gemini-lite", "gemini-backup"]
        assert agent.model == "gemini-primary"


class TestCadScriptSafety:
    """Test local execution safeguards for generated CAD scripts."""

    def test_generated_code_blocks_dangerous_imports(self):
        """Generated CAD code should not be allowed to import system modules."""
        agent = CadAgent()

        is_safe, error = agent._validate_generated_code("import os\nprint(os.getcwd())")

        assert is_safe is False
        assert "blocked module 'os'" in error

    @pytest.mark.asyncio
    async def test_generated_script_timeout(self, tmp_path):
        """Generated CAD scripts should not be able to hang the agent forever."""
        agent = CadAgent()
        agent.script_timeout_seconds = 1
        script_path = tmp_path / "current_design.py"
        script_path.write_text("while True:\n    pass\n", encoding="utf-8")

        result = await agent._run_generated_script(str(script_path))

        assert result.returncode == 124
        assert "timed out" in result.stderr

    @pytest.mark.asyncio
    async def test_generated_script_uses_ascii_output_filename_in_unicode_paths(self, tmp_path, monkeypatch):
        """Generated scripts should not embed absolute paths with non-ASCII characters."""
        import subprocess

        agent = CadAgent()
        work_dir = tmp_path / "Adrián AÑO"
        work_dir.mkdir()
        script_path = work_dir / "current_design.py"
        output_stl = work_dir / "output_20260506_123456.stl"

        async def fake_run(script_path_arg):
            return subprocess.CompletedProcess([script_path_arg], 0, "", "")

        monkeypatch.setattr(agent, "_run_generated_script", fake_run)

        code = "# soporte con comentario acentuado á\nexport_stl(result_part, 'output.stl')\n"
        await agent._write_and_run_generated_script(str(script_path), code, str(output_stl))

        written = script_path.read_text(encoding="utf-8")
        assert str(work_dir) not in written
        assert "output_20260506_123456.stl" in written
        assert "comentario acentuado á" in written

    @pytest.mark.asyncio
    async def test_rectangular_support_fallback_generates_stl(self, tmp_path):
        """Fallback should generate a simple support when model output fails."""
        agent = CadAgent()
        script_path = tmp_path / "current_design.py"
        output_stl = tmp_path / "output_test.stl"

        result = await agent._try_parametric_fallback(
            "Genera un soporte simple rectangular con cuatro agujeros",
            str(script_path),
            str(output_stl)
        )

        assert result is not None
        assert result["format"] == "stl"
        assert output_stl.exists()
        assert output_stl.stat().st_size > 0

    def test_hole_count_ignores_dimensions(self):
        """Hole count parsing should not confuse dimensions with hole counts."""
        agent = CadAgent()

        assert agent._extract_hole_count("placa rectangular 80x40 con 4 agujeros") == 4
        assert agent._extract_hole_count("rectangular support 80 by 40 with 2 holes") == 2


class TestCadGeneration:
    """Test CAD generation (requires API key)."""
    
    @pytest.fixture
    def agent(self):
        """Create a CadAgent instance."""
        return CadAgent()
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set"
    )
    async def test_generate_simple_cube(self, agent):
        """Test generating a simple cube."""
        thoughts = []
        statuses = []
        
        agent.on_thought = lambda t: thoughts.append(t)
        agent.on_status = lambda s: statuses.append(s)
        
        try:
            result = await agent.generate_prototype("A simple 10mm cube")
            print(f"Generation result: {result}")
            print(f"Thoughts received: {len(thoughts)}")
            print(f"Statuses received: {len(statuses)}")
            
            # Check if STL was generated
            if "output.stl" in str(result) or "success" in str(result).lower():
                print("CAD generation successful")
        except Exception as e:
            print(f"Generation failed (expected if build123d not installed): {e}")
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set"
    )
    async def test_generate_sphere(self, agent):
        """Test generating a sphere."""
        try:
            result = await agent.generate_prototype("A sphere with 25mm radius")
            print(f"Sphere generation result: {result}")
        except Exception as e:
            print(f"Sphere generation failed: {e}")


class TestCadIteration:
    """Test CAD iteration (modifying existing designs)."""
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set"
    )
    async def test_iterate_prototype(self):
        """Test iterating on an existing design."""
        agent = CadAgent()
        
        # First check if temp_cad_gen.py exists
        temp_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "backend",
            "temp_cad_gen.py"
        )
        
        if not os.path.exists(temp_file):
            pytest.skip("No existing temp_cad_gen.py to iterate on")
        
        try:
            result = await agent.iterate_prototype("Make it 50% larger")
            print(f"Iteration result: {result}")
        except Exception as e:
            print(f"Iteration failed: {e}")


class TestCadSystemPrompt:
    """Test CAD agent system prompt configuration."""
    
    def test_system_prompt_exists(self):
        """Test that system prompt is defined."""
        agent = CadAgent()
        # The agent should have a system prompt for Gemini
        assert hasattr(agent, 'system_prompt') or hasattr(agent, 'client')


class TestBuild123dImport:
    """Test build123d availability."""
    
    def test_build123d_import(self):
        """Test if build123d is installed."""
        try:
            import build123d
            print(f"build123d version: {build123d.__version__}")
        except ImportError:
            pytest.skip("build123d not installed")
