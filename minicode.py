import glob as globlib
import json
import os
import re 
import subprocess
import urllib.request

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
API_URL = "https://openrouter.ai/api/v1/messages" if OPENROUTER_KEY else "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("MODEL", "anthropic/claude-opus-4.5" if OPENROUTER_KEY else "claude-opus-4-5")

RESET, BOLD, DIM, ITALIC = "\033[0m", "\033[1m", "\033[2m", "\033[3m"
BLUE, CYAN, GREEN, YELLOW, RED, MAGENTA = (
    "\033[34m",
    "\033[36m",
    "\033[32m",
    "\033[33m",
    "\033[31m",
    "\033[35m",
)

# tools

def read(args):
    lines = open(args["path"]).readlines()
    offset = args.get("offset", 0)
    limit = args.get("limit", len(lines))
    selected = lines[offset:offset + limit]
    return "".join(f"{offset+idx+1:4} | {line}" for idx, line in enumerate(selected))

def write(args):
    with open(args["path"], "w") as f:
        f.write(args["content"])
    return "Ok"

def edit(args):
    text = open(args["path"]).read()
    old, new = args["old"], args["new"]
    if old not in text: return "Error: Old String not found"
    count = text.count(old)
    if not args.get("all") and count > 1: return f"Error: Old String appears {count} times, must be unique"
    replacement = (text.replace(old, new) if args.get("all") else text.replace(old, new, 1))
    with open(args["path"], "w") as f:
        f.write(replacement)
    return "Ok"


def glob(args):
    pattern = (args.get("path", ".") + "/" + args["pat"]).replace("//", "/")
    files = globlib.glob(pattern, recursive=True)
    files = sorted( files, key=lambda f: os.path.getmtime(f) if os.path.isfile(f) else 0, reverse=True,)
    return "\n".join(files) or "None"

def grep(args):
    pattern = re.compile(args["pat"])
    hits = []
    for filepath in globlib.glob(args.get("path", ".") + "/**", recursive=True):
        if not os.path.isfile(filepath): continue
        try:
            with open(filepath, "r", errors="ignore") as f:
                for line_num, line in enumerate(f, 1):
                    if pattern.search(line):
                        hits.append(f"{filepath}:{line_num}:{line.rstrip()}")
        except Exception:
            continue
    return "\n".join(hits[:50]) or "None"

def bash(args):
    proc = subprocess.Popen(
        args["cmd"], shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True
    )
    output_lines = []
    try:
        while True:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None: break
            if line:
                print(f"  {DIM}│ {line.rstrip()}{RESET}", flush=True)
                output_lines.append(line)
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        output_lines.append("\n(Timed out after 30s)")
    return "".join(output_lines).strip() or "(Empty)"


TOOLS = {
    "read": (
        "Read file with line numbers (file path, not directory)",
        {"path": "string", "offset": "number?", "limit": "number?"},
        read,
    ),
    "write": (
        "Write content to file",
        {"path": "string", "content": "string"},
        write,
    ),
    "edit": (
        "Replace old with new in file (old must be unique unless all=true)",
        {"path": "string", "old": "string", "new": "string", "all": "boolean?"},
        edit,
    ),
    "glob": (
        "Find files by pattern, sorted by mtime",
        {"pat": "string", "path": "string?"},
        glob,
    ),
    "grep": (
        "Search files for regex pattern",
        {"pat": "string", "path": "string?"},
        grep,
    ),
    "bash": (
        "Run shell command",
        {"cmd": "string"},
        bash,
    ),
}

def run_tool(name, args):
    return TOOLS[name][2](args)

def make_schema():
    result = []
    for name, (description, params, fn) in TOOLS.items():
        properties={}
        required=[]
        for param_name, param_type in params.items():
            is_optional = param_type.endswith("?")
            base_type = param_type.rstrip("?")
            properties[param_name] = { "type": "integer" if base_type == "number" else base_type }
            if not is_optional: required.append(param_name)
        result.append(
            {
                "name": name,
                "description": description,
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }
        )
    return result


def call_api(msgs, system_prompt):
    request = urllib.request.Request(API_URL, data = json.dumps(
        {
            "model":MODEL,
            "max_tokens":8192, # default 
            "system":system_prompt,
            "messages":msgs,
            "tools":make_schema(),
        }
    ).encode(),
    headers={
        "Content-Type":"application/json",
        "anthropic-version": "2023-06-01",
        **({"Authorization": f"Bearer {OPENROUTER_KEY}"} if OPENROUTER_KEY else {"x-api-key": os.environ.get("ANTHROPIC_API_KEY", "")}),
        },
    )
    response = urllib.request.urlopen(request)
    return json.loads(response.read())

def seperator():
    try:
        width = os.get_terminal_size().columns
    except OSError:
        width = 80
    return f"{DIM}{'─' * min(width, 100)}{RESET}"

def render_md(text):
    text = re.sub(r"`(.*?)`", f"{CYAN}\1{RESET}", text)  # inline code
    text = re.sub(r"\*\*(.+?)\*\*", f"{BOLD}\1{RESET}", text)  # bold
    text = re.sub(r"###\s*(.+)", f"{BOLD}{MAGENTA}\1{RESET}", text)  # headers
    return text


def main():
    if not OPENROUTER_KEY and not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"{RED}Error: OPENROUTER_API_KEY or ANTHROPIC_API_KEY not found in environment.{RESET}")
        return

    print(f"{BOLD}minicode{RESET} | {DIM}{MODEL} ({'OpenRouter' if OPENROUTER_KEY else 'Anthropic'}) | {os.getcwd()}{RESET}\n")
    messages = []
    system_prompt = f"Concise coding assistant. cwd: {os.getcwd()}"

    while True:
        try:
            print(seperator())
            user_input = input(f"{BOLD}{BLUE}❯{RESET} ").strip()
            if not user_input:
                continue
            if user_input in ("/q", "exit"):
                break
            if user_input == "/c":
                messages = []
                print(f"{GREEN}⏺ Cleared conversation{RESET}")
                continue

            messages.append({"role": "user", "content": user_input})

            # keep calling API until no more tool calls
            while True:
                response = call_api(messages, system_prompt)
                content_blocks = response.get("content", [])
                tool_results = []

                for block in content_blocks:
                    if block["type"] == "text":
                        print(f"\n{CYAN}⏺{RESET} {render_md(block['text'])}")

                    if block["type"] == "tool_use":
                        tool_name = block["name"]
                        tool_args = block["input"]
                        arg_preview = str(list(tool_args.values())[0])[:50]
                        print(
                            f"\n{GREEN}╭ 🛠️  {tool_name.capitalize()}{RESET} {DIM}({arg_preview}){RESET}"
                        )

                        result = run_tool(tool_name, tool_args)
                        result_lines = result.split("\n")
                        preview = result_lines[0][:80]
                        if len(result_lines) > 1:
                            preview += f" ... +{len(result_lines) - 1} lines"
                        elif len(result_lines[0]) > 80:
                            preview += "..."
                        print(f"{GREEN}╰{RESET} {DIM}⟶ {preview}{RESET}")

                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block["id"],
                                "content": result,
                            }
                        )

                messages.append({"role": "assistant", "content": content_blocks})

                if not tool_results:
                    break
                messages.append({"role": "user", "content": tool_results})

            print()

        except (KeyboardInterrupt, EOFError):
            break
        except Exception as err:
            print(f"{RED}⏺ Error: {err}{RESET}")
main()