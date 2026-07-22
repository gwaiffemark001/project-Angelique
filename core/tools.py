from skills.os_control.app_discovery import open_app, get_installed_apps
from skills.memory.memory_tools import save_fact, recall_facts
from skills.vision.screen_tools import read_screen
from skills.vision.camera_tools import capture_and_analyze_scene, detect_faces

TOOL_REGISTRY = {
    "open_app": {
        "description": "Opens a GUI application on the user's computer. Use this when the user asks to open, launch, or start an app.",
        "parameters": {"app_name": "The name of the application to open (string)."},
        "function": open_app
    },
    "save_memory": {
        "description": "Saves a permanent fact, preference, or detail about the user. Use this when the user tells you something about themselves.",
        "parameters": {
            "key": "A short, lowercase label for the fact (e.g., 'favorite broker').",
            "value": "The specific detail to remember."
        },
        "function": save_fact
    },
    "recall_memory": {
        "description": "Searches your long-term memory for facts about the user using semantic understanding. Use this when the user asks about themselves or things they told you.",
        "parameters": {
            "query": "The topic or concept to search for (e.g., 'broker', 'girlfriend', 'work')."
        },
        "function": recall_facts
    },
    "read_screen": {
        "description": "Takes a screenshot of the user's current screen and extracts the text. Use this when the user asks 'what is on my screen'.",
        "parameters": {},
        "function": read_screen
    },
    "analyze_camera_scene": {
        "description": "Captures an image from the webcam and analyzes what objects, text, or scene elements are visible. Use this when the user asks 'what do you see' or 'what's around me'.",
        "parameters": {},
        "function": capture_and_analyze_scene
    },
    "detect_faces_in_camera": {
        "description": "Detects if there are any human faces visible in the camera view. Use this when the user asks if anyone is in front of the camera.",
        "parameters": {},
        "function": detect_faces
    }
}

def execute_tool(tool_name: str, args: dict) -> str:
    if tool_name not in TOOL_REGISTRY:
        return f"Error: Tool '{tool_name}' not found."
    
    tool = TOOL_REGISTRY[tool_name]
    func = tool["function"]
    
    try:
        if args is None:
            args = {}
            
        if tool["parameters"]:
            return func(**args)
        else:
            return func()
    except Exception as e:
        return f"Error executing {tool_name}: {str(e)}"