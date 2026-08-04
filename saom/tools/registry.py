"""Tool registry — discover and execute SAOM tools."""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

from saom.config import get_memory_dir


class ToolRegistry:
    """Discover and execute SAOM tools from the memory directory."""

    def __init__(self, memory_dir: Optional[str] = None):
        if memory_dir is None:
            memory_dir = str(get_memory_dir())
        self.memory_dir = Path(memory_dir)
        self.tools_dir = self.memory_dir / "tools"
        self.registry_path = self.tools_dir / "registry.json"
        self._tools = None

    def _load_tools(self) -> List[Dict]:
        if self._tools is not None:
            return self._tools
        if self.registry_path.exists():
            with open(self.registry_path, encoding="utf-8") as f:
                data = json.load(f)
                self._tools = data if isinstance(data, list) else data.get("tools", [])
                return self._tools
        self._tools = []
        if self.tools_dir.exists():
            for d in sorted(self.tools_dir.iterdir()):
                if d.is_dir() and (d / "tool.py").exists():
                    tj = d / "tool.json"
                    if tj.exists():
                        with open(tj, encoding="utf-8") as f:
                            self._tools.append(json.load(f))
                    else:
                        self._tools.append({"name": d.name, "description": d.name})
        return self._tools

    def list_tools(self) -> List[Dict]:
        return self._load_tools()

    def get_tool(self, name: str) -> Optional[Dict]:
        for t in self._load_tools():
            if t.get("name") == name:
                return t
        return None

    def call(self, tool_name: str, args: Optional[Dict] = None) -> Dict[str, Any]:
        tool = self.get_tool(tool_name)
        if not tool:
            return {"error": "Tool not found: %s" % tool_name}
        tool_py = self.tools_dir / tool_name / "tool.py"
        if not tool_py.exists():
            return {"error": "Tool script not found: %s" % tool_py}
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(tool_name, str(tool_py))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "handle"): return mod.handle(args or {})
            elif hasattr(mod, "run"): return mod.run(args or {})
            else: return {"error": "Tool has no handle() or run() function"}
        except Exception as e:
            return {"error": "Tool execution failed: %s" % str(e)}
