import os
import sys
import json
import re
import shutil
import importlib.util
import subprocess
import hashlib
import signal
import time
from datetime import datetime
from pathlib import Path

SKILLS_DIR = Path("data/generated_skills")
SKILLS_DIR.mkdir(parents=True, exist_ok=True)

EVOLUTION_LOG = Path("data/generated_skills/evolution_log.json")
COMPONENT_CACHE = Path("data/generated_skills/component_cache.json")

def _load_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default or {}

def _save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def _log_evolution(action, detail, success=True):
    log = _load_json(EVOLUTION_LOG, [])
    if not isinstance(log, list):
        log = []
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "action": action,
        "detail": detail,
        "success": success,
    }
    log.append(entry)
    if len(log) > 500:
        log = log[-500:]
    _save_json(EVOLUTION_LOG, log)

def _component_key(name, code_hash):
    return f"{name}:{code_hash}"

def _store_component(name, code, metadata=None):
    key = _component_key(name, hashlib.md5(code.encode()).hexdigest()[:12])
    cache = _load_json(COMPONENT_CACHE, {})
    if not isinstance(cache, dict):
        cache = {}
    cache[key] = {
        "name": name,
        "code": code,
        "metadata": metadata or {},
        "created_at": datetime.utcnow().isoformat() + "Z",
        "usage_count": 0,
    }
    _save_json(COMPONENT_CACHE, cache)
    return key

def _get_similar_components(name_query, top_k=5):
    cache = _load_json(COMPONENT_CACHE, {})
    if not isinstance(cache, dict):
        return []
    matches = []
    for key, entry in cache.items():
        if name_query.lower() in entry["name"].lower():
            matches.append(entry)
    matches.sort(key=lambda x: x.get("usage_count", 0), reverse=True)
    return matches[:top_k]

def _reuse_component(name_query):
    similar = _get_similar_components(name_query)
    if similar:
        best = similar[0]
        best["usage_count"] = best.get("usage_count", 0) + 1
        _save_json(COMPONENT_CACHE, _load_json(COMPONENT_CACHE, {}))
        return best["code"]
    return None

def save_new_skill(skill_name: str, code: str, metadata: dict = None) -> str:
    try:
        file_path = SKILLS_DIR / f"{skill_name}.py"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)
        _store_component(skill_name, code, metadata or {})
        _log_evolution("save_skill", f"Saved '{skill_name}' to {file_path}", success=True)
        return f"✅ Skill '{skill_name}' saved to {file_path}"
    except Exception as e:
        _log_evolution("save_skill", f"Failed to save '{skill_name}': {e}", success=False)
        return f"❌ Failed to save skill: {str(e)}"

def execute_generated_code(code: str, function_name: str = "main", timeout: int = 30, kwargs: dict = None, reuse_cache: bool = True, **call_kwargs) -> str:
    kwargs = dict(kwargs or {})
    kwargs.update(call_kwargs)
    code_hash = hashlib.md5(code.encode()).hexdigest()[:12]
    func_sig = f"{function_name}:{code_hash}"

    reuse_result = None
    if reuse_cache:
        cached = _reuse_component(func_sig)
        if cached:
            cached_path = SKILLS_DIR / f"_cached_{func_sig}.py"
            if cached_path.exists():
                try:
                    result = subprocess.run(
                        [sys.executable, str(cached_path)],
                        capture_output=True, text=True, timeout=timeout,
                    )
                    if result.returncode == 0:
                        return f"✅ Reused cached component. Output:\n{result.stdout.strip() or 'No output.'}"
                except Exception:
                    pass

    temp_path = SKILLS_DIR / f"_exec_{code_hash}.py"
    kwargs_repr = repr(kwargs)
    wrapper = (
        "\n\nif __name__ == '__main__':\n"
        "    import json, sys, traceback\n"
        "    try:\n"
        f"        res = {function_name}(**{kwargs_repr})\n"
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

    try:
        proc = subprocess.Popen(
            [sys.executable, str(temp_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                pgid = proc.pid
                os.killpg(pgid, signal.SIGTERM)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            return f"❌ Execution timeout: Code took longer than {timeout}s to execute."
    finally:
        time.sleep(0.05)

    if '<<ERROR_START>>' in (stdout or '') or (proc.returncode is not None and proc.returncode != 0):
        tb = stdout if '<<ERROR_START>>' in (stdout or '') else (stderr or '')
        _log_evolution("execute_code", f"Failed: {tb.strip()[:200]}", success=False)
        return f"❌ Execution failed: {tb.strip()}"

    m = re.search(r"<<RESULT_START>>(.*?)<<RESULT_END>>", stdout, re.S)
    if m:
        payload = m.group(1).strip()
        try:
            data = json.loads(payload)
            result_value = data.get('result')
            extra_output = (stdout + "\n" + stderr).strip()
            if result_value is None and extra_output:
                return f"✅ Code executed. Result: None\nOutput:\n{extra_output}"
            return f"✅ Code executed. Result: {result_value!r}"
        except json.JSONDecodeError:
            return f"✅ Code executed. Raw output:\n{payload.strip()}"

    combined = (stdout + "\n" + stderr).strip()
    return f"✅ Code executed. Output:\n{combined}" if combined else "✅ Code executed. No output."

def _generate_fallback_code(instruction: str, normalized_name: str) -> str:
    lowered = instruction.lower().strip()

    if "square" in lowered:
        match = re.search(r"(-?\d+)", lowered)
        if match:
            num = int(match.group(1))
            return f"def main(**kwargs):\n    return {num} ** 2\n"

    if ("sum" in lowered or "add" in lowered) and ("numbers" in lowered or "values" in lowered or "digits" in lowered):
        nums = re.findall(r"-?\d+", lowered)
        if nums:
            values = ", ".join(nums)
            return f"def main(**kwargs):\n    return sum([{values}])\n"

    if "capitalize" in lowered:
        text_match = re.search(r"['\"]([^'\"]+)['\"]", instruction)
        if text_match:
            text = text_match.group(1)
            return (
                "def main(**kwargs):\n"
                f"    value = {text!r}\n"
                "    return value.capitalize()\n"
            )

    if "convert" in lowered and ("webm" in lowered or "mp4" in lowered):
        path_match = re.search(
            r"convert\s+['\"]?(?P<input>[^'\"]+?\.(?:webm|mp4))['\"]?\s+to\s+['\"]?(?P<output>[^'\"]+?\.(?:webm|mp4))['\"]?",
            instruction,
            re.IGNORECASE,
        )
        if path_match:
            input_path = path_match.group('input').strip(' "\'')
            output_path = path_match.group('output').strip(' "\'')
        else:
            paths = re.findall(r"([A-Za-z0-9 _\-\.\/\\:]+?\.(?:webm|mp4))", instruction, re.IGNORECASE)
            input_path = paths[0].strip(' "\'') if paths else "input.webm"
            output_path = paths[-1].strip(' "\'') if len(paths) > 1 else "output.mp4"
        return (
            "import subprocess\nfrom pathlib import Path\n"
            "def main(**kwargs):\n"
            f"    input_path = Path(r'''{input_path}''').expanduser().resolve()\n"
            f"    output_path = Path(r'''{output_path}''').expanduser().resolve()\n"
            "    if not input_path.exists():\n"
            "        raise FileNotFoundError(f\"Input file not found: {input_path}\")\n"
            "    output_path.parent.mkdir(parents=True, exist_ok=True)\n"
            "    result = subprocess.run(['ffmpeg', '-y', '-nostdin', '-i', str(input_path), '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', '-r', '30', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', '-pix_fmt', 'yuv420p', '-threads', '4', '-c:a', 'aac', '-b:a', '128k', str(output_path)], capture_output=True, text=True)\n"
            "    if result.returncode != 0:\n"
            "        raise RuntimeError(result.stderr.strip() or result.stdout.strip())\n"
            "    return f'Converted {input_path} to {output_path}'\n"
        )

    return (
        "def main(**kwargs):\n"
        f"    return {normalized_name!r}\n"
    )


def generate_skill_from_instruction(instruction: str, skill_name: str = None, allow_llm: bool = True) -> tuple:
    normalized_name = skill_name or re.sub(r"[^a-zA-Z0-9_]+", "_", instruction.strip().lower())[:40]
    normalized_name = normalized_name.strip("_") or "generated_skill"

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
                code = re.sub(r'^```(?:python|py)?\s*\n?', '', code, flags=re.MULTILINE | re.IGNORECASE)
                code = re.sub(r'\n?```\s*$', '', code, flags=re.MULTILINE | re.IGNORECASE)
                code = code.strip()
                if code.startswith('```') or code.endswith('```'):
                    code = re.sub(r'```', '', code)
                try:
                    imports = set()
                    for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z0-9_\.]+)", code, flags=re.MULTILINE):
                        imports.add(m.group(1).split('.', 1)[0])
                    whitelist = {
                        'os', 'sys', 'subprocess', 'pathlib', 'datetime', 'json', 're',
                        'math', 'typing', 'shutil', 'tempfile', 'logging', 'requests',
                        'urllib', 'http', 'collections', 'itertools', 'functools',
                    }
                    unsafe = [m for m in imports if m and m not in whitelist]
                    if unsafe:
                        raise RuntimeError(f"LLM-generated code imports non-whitelisted modules: {unsafe}")
                except Exception:
                    raise
                return normalized_name, code
        except Exception:
            pass

    fallback_code = _generate_fallback_code(instruction, normalized_name)
    return normalized_name, fallback_code


def build_recovery_instruction(instruction: str, failure_report: str) -> str:
    return (
        "The previous attempt to execute this instruction failed. "
        "Please generate a revised skill that resolves the reported issue and completes the task if possible.\n"
        f"Original instruction: {instruction}\n"
        f"Failure details: {failure_report}"
    )

def convert_webm_to_mp4(input_path: str, output_path: str) -> str:
    input_file = Path(input_path).expanduser().resolve()
    output_file = Path(output_path).expanduser().resolve()

    if not input_file.exists():
        return f"Input file not found: {input_file}"

    output_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-nostdin", "-i", str(input_file), "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p", "-threads", "4", "-c:a", "aac", "-b:a", "128k", str(output_file)],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception as exc:
        return f"Conversion failed: {exc}"

    return f"Converted {input_file} to {output_file}"


def create_and_execute_skill(instruction: str, max_attempts: int = 3, allow_llm: bool = True) -> str:
    current_instruction = instruction
    last_result = None

    for attempt in range(1, max_attempts + 1):
        try:
            skill_name, code = generate_skill_from_instruction(current_instruction, allow_llm=allow_llm)
            save_new_skill(skill_name, code)
            result = execute_generated_code(code, reuse_cache=True)
            if "❌ Execution failed" in result or "❌ Execution timeout" in result:
                last_result = result
                if attempt >= max_attempts:
                    _log_evolution("create_and_execute", f"Skill '{skill_name}' failed after {attempt} attempts: {result}", success=False)
                    return f"❌ Self-evolution could not complete after {attempt} attempts. {result}"

                recovery_instruction = build_recovery_instruction(instruction, result)
                if allow_llm:
                    try:
                        recovery_plan = think_about_problem(recovery_instruction)
                        current_instruction = f"{instruction}\n\nRecovery guidance:\n{recovery_plan}"
                    except Exception:
                        current_instruction = recovery_instruction
                else:
                    current_instruction = recovery_instruction

                _log_evolution("recover", f"Attempt {attempt} failed; retrying with recovery guidance", success=False)
                continue

            _log_evolution("create_and_execute", f"Skill '{skill_name}' created and executed", success=True)
            return f"✅ Skill '{skill_name}' created and executed. {result}"
        except Exception as exc:
            last_result = str(exc)
            if attempt >= max_attempts:
                _log_evolution("create_and_execute", f"Failed: {exc}", success=False)
                return f"❌ Self-evolution failed: {exc}"

            current_instruction = build_recovery_instruction(instruction, str(exc))
            _log_evolution("recover", f"Recovery attempt {attempt} hit an exception; retrying", success=False)

    if last_result:
        return f"❌ Self-evolution could not complete. {last_result}"
    return "❌ Self-evolution could not complete."

def think_about_problem(problem: str) -> str:
    try:
        from brain.llm_interface import query_llm
        prompt = (
            "You are Angelique, a self-evolving AI. Analyze the following problem step by step. "
            "Break it down into sub-problems, identify the best approach, and describe the solution plan. "
            "Return ONLY your analysis, no JSON, no markdown formatting.\n\n"
            f"Problem: {problem}"
        )
        return query_llm([{"role": "user", "content": prompt}], temperature=0.3) or "Unable to analyze the problem."
    except Exception as e:
        return f"Analysis failed: {e}"

def store_component(name: str, code: str, metadata: dict = None) -> str:
    try:
        key = _store_component(name, code, metadata)
        return f"✅ Component '{name}' stored with key '{key}'. It can be reused by future skills."
    except Exception as e:
        return f"❌ Failed to store component: {e}"

def retrieve_component(name_query: str) -> str:
    try:
        similar = _get_similar_components(name_query, top_k=3)
        if not similar:
            return f"No components found matching '{name_query}'."
        results = []
        for entry in similar:
            results.append(f"📦 {entry['name']} (used {entry.get('usage_count', 0)}x, created {entry.get('created_at', 'unknown')})")
        return "\n".join(results)
    except Exception as e:
        return f"❌ Retrieval failed: {e}"

def get_evolution_log() -> str:
    try:
        log = _load_json(EVOLUTION_LOG, [])
        if not log:
            return "No evolution history yet."
        lines = [f"[{e.get('timestamp', '?')}] {'✅' if e.get('success') else '❌'} {e.get('action', '?')}: {e.get('detail', '?')[:100]}" for e in log[-20:]]
        return "\n".join(lines)
    except Exception:
        return "Unable to read evolution log."