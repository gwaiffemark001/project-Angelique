# skills/self_evolution/code_generator.py
import os
import importlib.util
import re
import subprocess
import sys
import traceback

SKILLS_DIR = "data/generated_skills"
os.makedirs(SKILLS_DIR, exist_ok=True)

def save_new_skill(skill_name: str, code: str) -> str:
    try:
        file_path = os.path.join(SKILLS_DIR, f"{skill_name}.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)
        return f"✅ Skill '{skill_name}' saved to {file_path}"
    except Exception as e:
        return f"Failed to save skill: {str(e)}"


def convert_webm_to_mp4(input_path: str, output_path: str) -> str:
    """Convert a WebM file to MP4 using ffmpeg with a practical, fast profile."""
    input_path = os.path.abspath(os.path.expanduser(input_path))
    output_path = os.path.abspath(os.path.expanduser(output_path))
    if not os.path.exists(input_path):
        return f"Input file not found: {input_path}"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    args = [
        'ffmpeg',
        '-y',
        '-nostdin',
        '-i', input_path,
        '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
        '-r', '30',
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '28',
        '-pix_fmt', 'yuv420p',
        '-threads', '4',
        '-c:a', 'aac',
        '-b:a', '128k',
        output_path,
    ]
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return f"ffmpeg conversion timed out for {input_path}"
    if completed.returncode != 0:
        return completed.stderr.strip() or completed.stdout.strip() or "ffmpeg conversion failed"
    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        return f"Converted {input_path} to {output_path}"
    return f"ffmpeg completed but output file missing or empty: {output_path}"


def execute_generated_code(code: str, function_name: str = "main", timeout: int = 30, **kwargs) -> str:
    """
    Execute generated code with timeout protection and proper output capture.
    """
    # Write the generated code to a temp file and append a small runner wrapper
    temp_path = os.path.join(SKILLS_DIR, "_temp_exec.py")
    # Build wrapper without f-string to avoid accidental brace-formatting issues
    kwargs_repr = repr(kwargs or {})
    wrapper = (
        "\n\nif __name__ == '__main__':\n"
        "    import json, sys, traceback\n"
        "    try:\n"
        "        res = "
        + function_name
        + "(**"
        + kwargs_repr
        + ")\n"
        "        print('<<RESULT_START>>')\n"
        "        import json as _json\n"
        "        print(_json.dumps({'result': res}))\n"
        "        print('<<RESULT_END>>')\n"
        "    except Exception:\n"
        "        print('<<ERROR_START>>')\n"
        "        traceback.print_exc()\n"
        "        print('<<ERROR_END>>')\n"
        "        sys.exit(1)\n"
    )

    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(code)
        f.write(wrapper)

    import subprocess
    import signal
    import time
    try:
        proc = subprocess.Popen(
            [sys.executable, temp_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Let the process exit naturally if it has already produced a useful file.
            try:
                pgid = proc.pid
                os.killpg(pgid, signal.SIGTERM)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            return f"❌ Execution timeout: Code took longer than {timeout}s to execute (possible infinite loop or blocking operation)"
    finally:
        # Small sleep to let OS cleanup if needed
        time.sleep(0.05)

    # If process exit code indicates failure prefer stdout traceback
    retcode = None
    try:
        retcode = proc.returncode
    except Exception:
        retcode = None
    if '<<ERROR_START>>' in (stdout or '') or (retcode is not None and retcode != 0):
        tb = stdout if '<<ERROR_START>>' in (stdout or '') else (stderr or '')
        return f"❌ Execution failed: {tb.strip()}"

    # Extract JSON result
    m = re.search(r"<<RESULT_START>>(.*?)<<RESULT_END>>", stdout, re.S)
    if m:
        payload = m.group(1).strip()
        try:
            import json as _json
            data = _json.loads(payload)
            result_value = data.get('result')
            extra_output = (stdout + "\n" + stderr).strip()
            if result_value is None and extra_output:
                return f"✅ Code executed. Result: None\nOutput:\n{extra_output}"
            return f"✅ Code executed. Result: {result_value!r}"
        except Exception:
            return f"✅ Code executed. Raw output:\n{payload.strip()}"

    # Fallback: return combined stdout/stderr
    combined = (stdout + "\n" + stderr).strip()
    return f"✅ Code executed. Output:\n{combined}" if combined else "✅ Code executed. No output."


def _parse_webm_mp4_paths(instruction: str) -> tuple[str, str]:
    path_match = re.search(
        r"convert\s+['\"]?(?P<input>[^'\"]+?\.webm)['\"]?\s+to\s+['\"]?(?P<output>[^'\"]+?\.mp4)['\"]?",
        instruction,
        re.IGNORECASE,
    )
    if path_match:
        return (
            path_match.group('input').strip(' "\''),
            path_match.group('output').strip(' "\''),
        )
    webm_paths = re.findall(r"([A-Za-z0-9 _\-\./\\:]+?\.webm)", instruction, re.IGNORECASE)
    mp4_paths = re.findall(r"([A-Za-z0-9 _\-\./\\:]+?\.mp4)", instruction, re.IGNORECASE)
    input_path = webm_paths[0].strip(' "\'') if webm_paths else "input.webm"
    output_path = mp4_paths[-1].strip(' "\'') if mp4_paths else "output.mp4"
    return input_path, output_path

def _convert_webm_to_mp4(input_path: str, output_path: str, timeout: int = 1800) -> str:
    from pathlib import Path
    import subprocess

    input_path = Path(input_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    args = [
        'ffmpeg',
        '-y',
        '-nostdin',
        '-i',
        str(input_path),
        '-vf',
        'scale=trunc(iw/2)*2:trunc(ih/2)*2',
        '-r',
        '30',
        '-c:v',
        'libx264',
        '-preset',
        'ultrafast',
        '-crf',
        '28',
        '-pix_fmt',
        'yuv420p',
        '-threads',
        '4',
        '-c:a',
        'aac',
        '-b:a',
        '128k',
        str(output_path),
    ]

    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        if output_path.exists() and output_path.stat().st_size > 0:
            return f"Converted {input_path} to {output_path} with warnings: {proc.stderr.strip()}"
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"ffmpeg exited {proc.returncode}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg completed but output file is missing or empty: {output_path}")

    return f"Converted {input_path} to {output_path}"

def generate_skill_from_instruction(instruction: str, skill_name: str | None = None, allow_llm: bool = True) -> tuple[str, str]:
    """Generate a Python skill from an instruction and return (skill_name, code)."""
    normalized_name = skill_name or re.sub(r"[^a-zA-Z0-9_]+", "_", instruction.strip().lower())[:40]
    normalized_name = normalized_name.strip("_") or "generated_skill"

    # Try to use the LLM if available
    if allow_llm:
        try:
            from brain.llm_interface import query_llm

            prompt = (
                "You are a Python code generator. Create a Python script that defines a function named main(**kwargs) "
                "which performs the user's instruction. Return ONLY valid Python code with NO markdown, NO backticks, NO explanations. "
                f"User instruction: {instruction}"
            )
            code = query_llm([{"role": "user", "content": prompt}], temperature=0.0)
            if code and not code.startswith("I'm having a little trouble"):
                # Aggressive markdown stripping: remove ALL markdown code blocks and backticks
                code = re.sub(r'^```(?:python|py)?\s*\n?', '', code, flags=re.MULTILINE | re.IGNORECASE)
                code = re.sub(r'\n?```\s*$', '', code, flags=re.MULTILINE | re.IGNORECASE)
                code = code.strip()
                # Verify it's not still wrapped in backticks
                if code.startswith('```') or code.endswith('```'):
                    code = re.sub(r'```', '', code)
                # Reject LLM code that imports non-whitelisted modules (safety)
                try:
                    imports = set()
                    for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z0-9_\.]+)", code, flags=re.MULTILINE):
                        imports.add(m.group(1).split('.', 1)[0])
                    whitelist = {
                        'os', 'sys', 'subprocess', 'pathlib', 'datetime', 'json', 're', 'math', 'typing',
                        'shutil', 'tempfile', 'logging'
                    }
                    unsafe = [m for m in imports if m and m not in whitelist]
                    if unsafe:
                        # refuse LLM output containing unexpected imports
                        raise RuntimeError(f"LLM-generated code imports non-whitelisted modules: {unsafe}")
                except Exception:
                    # fall through to allow fallback generation
                    raise
                return normalized_name, code
        except Exception:
            pass

    # Fallback for a few common examples so self-evolution still works without LLM access.
    lowered = instruction.lower()
    if "square" in lowered:
        match = re.search(r"(-?\d+)", lowered)
        if match:
            num = int(match.group(1))
            code = (
                "def main(**kwargs):\n"
                f"    return {num} ** 2\n"
            )
            return normalized_name, code
    if "convert" in lowered and "webm" in lowered and "mp4" in lowered:
        path_match = re.search(
            r"convert\s+['\"]?(?P<input>[^'\"]+?\.webm)['\"]?\s+to\s+['\"]?(?P<output>[^'\"]+?\.mp4)['\"]?",
            instruction,
            re.IGNORECASE,
        )
        if path_match:
            input_path = path_match.group('input').strip(' "\'')
            output_path = path_match.group('output').strip(' "\'')
        else:
            webm_paths = re.findall(r"([A-Za-z0-9 _\-\./\\:]+?\.webm)", instruction, re.IGNORECASE)
            mp4_paths = re.findall(r"([A-Za-z0-9 _\-\./\\:]+?\.mp4)", instruction, re.IGNORECASE)
            input_path = webm_paths[0].strip(' "\'') if webm_paths else "input.webm"
            output_path = mp4_paths[-1].strip(' "\'') if mp4_paths else "output.mp4"
        # ensure generated code resolves user paths (expanduser + absolute)
        code = (
            "import subprocess\n"
            "from pathlib import Path\n"
            "def main(**kwargs):\n"
            f"    input_path = Path(r'''{input_path}''').expanduser().resolve()\n"
            f"    output_path = Path(r'''{output_path}''').expanduser().resolve()\n"
            "    if not input_path or not output_path:\n"
            "        raise ValueError(\"Both source and destination paths must be provided\")\n"
            "    if not input_path.exists():\n"
            "        raise FileNotFoundError(f\"Input file not found: {input_path}\")\n"
            "    output_path.parent.mkdir(parents=True, exist_ok=True)\n"
            "    args = [\n"
            "        'ffmpeg',\n"
            "        '-y',\n"
            "        '-nostdin',\n"
            "        '-i',\n"
            "        str(input_path),\n"
            "        '-vf',\n"
            "        'scale=trunc(iw/2)*2:trunc(ih/2)*2',\n"
            "        '-r',\n"
            "        '30',\n"
            "        '-c:v',\n"
            "        'libx264',\n"
            "        '-preset',\n"
            "        'ultrafast',\n"
            "        '-crf',\n"
            "        '28',\n"
            "        '-pix_fmt',\n"
            "        'yuv420p',\n"
            "        '-threads',\n"
            "        '4',\n"
            "        '-c:a',\n"
            "        'aac',\n"
            "        '-b:a',\n"
            "        '128k',\n"
            "        str(output_path),\n"
            "    ]\n"
            "    result = subprocess.run(args, capture_output=True, text=True)\n"
            "    if result.returncode != 0:\n"
            "        raise RuntimeError(result.stderr.strip() or result.stdout.strip())\n"
            "    return f'Converted {input_path} to {output_path}'\n"
        )
        return normalized_name, code
    if "date" in lowered or "time" in lowered:
        code = (
            "from datetime import datetime\n"
            "def main(**kwargs):\n"
            "    return datetime.now().isoformat()\n"
        )
        return normalized_name, code
    if "list files" in lowered or "list directory" in lowered:
        code = (
            "import os\n"
            "def main(**kwargs):\n"
            "    return os.listdir('.')\n"
        )
        return normalized_name, code

    raise ValueError("Unable to generate a skill for that instruction without a configured LLM.")


def create_and_execute_skill(instruction: str) -> str:
    try:
        use_fallback = (
            "convert" in instruction.lower()
            and "webm" in instruction.lower()
            and "mp4" in instruction.lower()
        )

        if use_fallback:
            path_match = re.search(
                r"convert\s+['\"]?(?P<input>[^'\"]+?\.webm)['\"]?\s+to\s+['\"]?(?P<output>[^'\"]+?\.mp4)['\"]?",
                instruction,
                re.IGNORECASE,
            )
            if path_match:
                input_path = path_match.group('input').strip(' "\'')
                output_path = path_match.group('output').strip(' "\'')
                result = convert_webm_to_mp4(input_path, output_path)
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    return f"✅ Skill conversion completed. Output file is ready: {output_path}"
                return f"❌ Skill conversion failed: {result}"

            skill_name, code = generate_skill_from_instruction(instruction, allow_llm=False)
            save_new_skill(skill_name, code)
            result = execute_generated_code(code, timeout=1800)
            out_match = re.search(r"output_path\s*=\s*Path\(r?'''(?P<out>[^']+)'''\)", code)
            if out_match:
                out_path = out_match.group('out')
                try:
                    from pathlib import Path as _P
                    p = _P(out_path).expanduser().resolve()
                    if p.exists() and p.stat().st_size > 0:
                        return f"✅ Skill '{skill_name}' created and executed (fallback). Output file is ready: {p}"
                    if not p.exists() or p.stat().st_size == 0:
                        return f"❌ Conversion ran but output file missing or empty: {p} -- execution result:\n{result}"
                except Exception:
                    pass
            return f"✅ Skill '{skill_name}' created and executed (fallback). {result}"

        # First try: allow LLM to generate code (if available)
        skill_name, code = generate_skill_from_instruction(instruction, allow_llm=True)
        save_new_skill(skill_name, code)
        # If instruction looks like a conversion, allow longer timeout
        if "convert" in instruction.lower() and "ffmpeg" in code.lower() or (
            "convert" in instruction.lower() and "webm" in instruction.lower() and "mp4" in instruction.lower()
        ):
            result = execute_generated_code(code, timeout=1800)
        else:
            result = execute_generated_code(code)

        fallback_conditions = [
            "❌ Execution failed",
            "Traceback",
            "No module named",
            "ImportError",
            "Please provide both source and destination paths.",
            "Result: None",
        ]

        if isinstance(result, str) and any(cond in result for cond in fallback_conditions):
            try:
                skill_name_fb, code_fb = generate_skill_from_instruction(instruction, allow_llm=False)
                save_new_skill(skill_name_fb, code_fb)
                result_fb = execute_generated_code(code_fb)
                return f"✅ Skill '{skill_name_fb}' created and executed (fallback). {result_fb}"
            except Exception as exc_fb:
                return f"❌ Self-evolution failed after fallback: {exc_fb}. Initial result: {result}"

        return f"✅ Skill '{skill_name}' created and executed. {result}"
    except Exception as exc:
        return f"❌ Self-evolution failed: {exc}"
