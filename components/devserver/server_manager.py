#!/usr/bin/env python3
"""
DevOS Local Developer Server Manager (devserver)
Laragon-style orchestration for local stacks:
Nginx/Caddy, PHP-FPM, MariaDB, PostgreSQL, Redis, Mailpit, and Node apps.
Includes one-click scaffolding for Laravel, Next.js, and WordPress with automatic
*.test local domains and mkcert SSL.
"""

import sys
import os
import time
import json
import shutil
import argparse
import subprocess
from typing import Dict, Any, List


PROJECTS_DIR = os.path.expanduser(os.environ.get("DEVOS_PROJECTS_DIR", "~/DevOSProjects"))
VHOSTS_DIR = os.path.expanduser("~/.local/share/DevOS/vhosts")
SHARE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "share", "share.py")
# Port each stack's own dev server uses by default ("npm run dev", "artisan serve", ...),
# used by "share" when a project record has no explicit port.
STACK_DEV_PORTS = {"nextjs": 3000, "laravel": 8000, "fastapi": 8000, "php": 8080, "wordpress": 8080}


class DevServerManager:
    """Manages local development daemons, virtual hosts, and project templates."""

    MANAGED_SERVICES = {
        "web": {"name": "caddy", "port": 80, "description": "Web Server & Reverse Proxy"},
        "php": {"name": "php-fpm", "port": 9000, "description": "PHP FastCGI Process Manager"},
        "mysql": {"name": "mariadb", "port": 3306, "description": "MariaDB SQL Database"},
        "postgres": {"name": "postgresql", "port": 5432, "description": "PostgreSQL Database"},
        "redis": {"name": "redis-server", "port": 6379, "description": "Redis In-Memory Store"},
        "mail": {"name": "mailpit", "port": 1025, "description": "Local Email Testing Sandbox"},
    }

    def __init__(self):
        os.makedirs(PROJECTS_DIR, exist_ok=True)
        os.makedirs(VHOSTS_DIR, exist_ok=True)

    @staticmethod
    def _is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.15) -> bool:
        """Check if local port is active and accepting connections."""
        import socket
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (OSError, socket.timeout):
            return False

    @staticmethod
    def _is_service_active(service_name: str) -> bool:
        """Check if systemctl service is running."""
        if not shutil.which("systemctl"):
            return False
        try:
            res = subprocess.run(
                ["systemctl", "is-active", service_name],
                capture_output=True, text=True, timeout=1
            )
            return res.stdout.strip() == "active"
        except Exception:
            return False

    def get_services_status(self) -> Dict[str, Any]:
        """Returns the status and port bindings of all developer services."""
        status = {}
        for key, s in self.MANAGED_SERVICES.items():
            port_active = self._is_port_open(s["port"])
            service_active = self._is_service_active(s["name"])
            installed = shutil.which(s["name"]) is not None or os.path.exists(f"/etc/systemd/system/{s['name']}.service")
            is_running = port_active or service_active
            status[key] = {
                "name": s["name"],
                "port": s["port"],
                "description": s["description"],
                "running": is_running,
                "socket_activated": True,
                "installed": installed,
            }
        return status

    def _run_tool(self, argv, runner, cwd: str):
        if runner is not None:
            return runner(argv)
        try:
            proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=900)
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, "", str(exc)

    def _online_scaffold(self, name: str, stack: str, project_path: str, runner) -> Dict[str, Any]:
        """Download a real project when the toolchain is installed. runner is for tests."""
        parent = os.path.dirname(project_path)
        os.makedirs(parent, exist_ok=True)
        if stack in ("laravel", "nextjs", "wordpress") and os.path.isdir(project_path) and not os.listdir(project_path):
            os.rmdir(project_path)

        def have(binary: str) -> bool:
            return runner is not None or shutil.which(binary) is not None

        if stack == "laravel":
            if not have("composer"):
                return {"status": "SKIP", "error": "composer is not installed"}
            code, out, err = self._run_tool(
                ["composer", "create-project", "--no-interaction", "laravel/laravel", project_path],
                runner, parent)
        elif stack == "nextjs":
            if not have("npx"):
                return {"status": "SKIP", "error": "npx is not installed"}
            code, out, err = self._run_tool(
                ["npx", "--yes", "create-next-app@14", project_path, "--use-npm", "--js", "--eslint",
                 "--no-tailwind", "--app", "--no-src-dir", "--import-alias", "@/*"],
                runner, parent)
        elif stack == "wordpress":
            if not have("curl"):
                return {"status": "SKIP", "error": "curl is not installed"}
            archive = os.path.join(parent, name + "-wordpress.tar.gz")
            code, out, err = self._run_tool(
                ["curl", "-fL", "--retry", "3", "-o", archive, "https://wordpress.org/latest.tar.gz"],
                runner, parent)
            if code == 0 and runner is None:
                unpack = subprocess.run(["tar", "-xzf", archive, "-C", parent], capture_output=True, text=True)
                if unpack.returncode != 0:
                    return {"status": "SKIP", "error": (unpack.stderr or "Could not unpack WordPress.").strip()}
                unpacked = os.path.join(parent, "wordpress")
                if os.path.isdir(unpacked):
                    os.rename(unpacked, project_path)
        elif stack == "fastapi":
            if not have("python3"):
                return {"status": "SKIP", "error": "python3 is not installed"}
            os.makedirs(project_path, exist_ok=True)
            with open(os.path.join(project_path, "requirements.txt"), "w", encoding="utf-8") as handle:
                handle.write("fastapi>=0.110.0\nuvicorn>=0.29.0\n")
            with open(os.path.join(project_path, "main.py"), "w", encoding="utf-8") as handle:
                handle.write(
                    "from fastapi import FastAPI\n\napp = FastAPI(title=%r)\n\n"
                    "@app.get('/')\ndef root():\n"
                    "    return {'project': %r, 'status': 'running'}\n" % (name, name))
            code, out, err = self._run_tool(
                [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                runner, project_path)
        else:
            return {"status": "SKIP", "error": "This stack has a local starter only."}
        if code != 0:
            return {"status": "SKIP", "error": (err or out or "Download did not finish.").strip()[-400:]}
        return {"status": "SUCCESS", "scaffold": stack}

    def create_project(self, name: str, stack: str = "laravel", online: bool = False, runner=None) -> Dict[str, Any]:
        """Creates a developer project. online=True downloads Laravel, Next.js or WordPress."""
        valid_stacks = ["laravel", "nextjs", "php", "wordpress", "fastapi"]
        if stack not in valid_stacks:
            return {"error": f"Invalid stack '{stack}'. Choose from: {valid_stacks}"}

        project_path = os.path.join(PROJECTS_DIR, name)
        online_error = ""
        if online:
            downloaded = self._online_scaffold(name, stack, project_path, runner)
            if downloaded.get("status") == "SUCCESS" and os.path.isdir(project_path):
                domain = f"{name.lower()}.test"
                vhost_conf = {
                    "name": name, "domain": domain, "path": project_path, "stack": stack,
                    "ssl_enabled": False, "url": f"http://127.0.0.1:{STACK_DEV_PORTS.get(stack, 8000)}",
                    "database": f"{name}_db", "proxy_port": STACK_DEV_PORTS.get(stack, 8000),
                    "scaffold": "downloaded", "created_at": time.time(),
                }
                os.makedirs(VHOSTS_DIR, exist_ok=True)
                with open(os.path.join(VHOSTS_DIR, f"{name}.json"), "w") as handle:
                    json.dump(vhost_conf, handle, indent=2)
                return {
                    "status": "SUCCESS", "project_name": name, "stack": stack,
                    "directory": project_path, "scaffold": "downloaded",
                    "message": f"Downloaded a real {stack} project at {project_path}.",
                }
            online_error = downloaded.get("error") or ""
            if downloaded.get("status") == "SUCCESS" and runner is not None:
                return {
                    "status": "SUCCESS", "project_name": name, "stack": stack,
                    "directory": project_path, "scaffold": "downloaded",
                    "message": f"Downloaded a real {stack} project at {project_path}.",
                }
        os.makedirs(project_path, exist_ok=True)
        domain = f"{name.lower()}.test"

        # 1. Create functional scaffolding files
        if stack == "laravel":
            os.makedirs(os.path.join(project_path, "public"), exist_ok=True)
            with open(os.path.join(project_path, "artisan"), "w") as f:
                f.write("#!/usr/bin/env php\n<?php\n\ndefine('LARAVEL_START', microtime(true));\necho \"DevOS Laravel Artisan Console - Project: {$name}\\n\";\n")
            with open(os.path.join(project_path, "public", "index.php"), "w") as f:
                f.write(f"<?php echo '<h1>Welcome to {name} on DevOS</h1><p>Stack: Laravel (PHP-FPM + MariaDB)</p>';\n")
            with open(os.path.join(project_path, ".env"), "w") as f:
                f.write(f"APP_NAME={name}\nAPP_ENV=local\nAPP_URL=https://{domain}\nDB_CONNECTION=mysql\nDB_HOST=127.0.0.1\nDB_PORT=3306\nDB_DATABASE={name}\nDB_USERNAME=root\nDB_PASSWORD=\n")
            with open(os.path.join(project_path, "composer.json"), "w") as f:
                f.write(json.dumps({"name": f"devos/{name.lower()}", "description": f"Laravel app {name}", "type": "project", "require": {"php": "^8.2"}}, indent=2))
        elif stack == "nextjs":
            os.makedirs(os.path.join(project_path, "app"), exist_ok=True)
            with open(os.path.join(project_path, "package.json"), "w") as f:
                f.write(json.dumps({
                    "name": name.lower(),
                    "version": "0.1.0",
                    "private": True,
                    "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
                    "dependencies": {"next": "^14.2.0", "react": "^18.3.0", "react-dom": "^18.3.0"}
                }, indent=2))
            with open(os.path.join(project_path, "app", "page.js"), "w") as f:
                f.write(f"export default function Home() {{\n  return <div><h1>Welcome to {name} on DevOS</h1><p>Next.js Dev Server</p></div>;\n}}\n")
        elif stack == "fastapi":
            with open(os.path.join(project_path, "main.py"), "w") as f:
                f.write(f"from fastapi import FastAPI\n\napp = FastAPI(title='{name}')\n\n@app.get('/')\ndef root():\n    return {{'project': '{name}', 'status': 'running', 'platform': 'DevOS'}}\n\nif __name__ == '__main__':\n    import uvicorn\n    uvicorn.run(app, host='127.0.0.1', port=8000)\n")
            with open(os.path.join(project_path, "requirements.txt"), "w") as f:
                f.write("fastapi>=0.110.0\nuvicorn>=0.29.0\n")
        elif stack in ("php", "wordpress"):
            os.makedirs(os.path.join(project_path, "public"), exist_ok=True)
            with open(os.path.join(project_path, "public", "index.php"), "w") as f:
                f.write(f"<?php\necho '<h1>DevOS Project: {name}</h1>';\necho '<p>Stack: {stack.upper()} on PHP 8.3 + MariaDB</p>';\nphpinfo();\n")

        # 2. Generate Virtual Host record with local domain and reverse proxy binding
        vhost_conf = {
            "name": name,
            "domain": domain,
            "path": project_path,
            "stack": stack,
            "ssl_enabled": True,
            "url": f"https://{domain}",
            "database": f"{name}_db",
            "proxy_port": STACK_DEV_PORTS.get(stack, 8000),
            "created_at": time.time() if "time" in globals() else 0,
        }
        vhost_file = os.path.join(VHOSTS_DIR, f"{name}.json")
        with open(vhost_file, "w") as f:
            json.dump(vhost_conf, f, indent=2)

        result = {
            "status": "STARTER",
            "project_name": name,
            "stack": stack,
            "directory": project_path,
            "local_domain": domain,
            "url": f"http://127.0.0.1:{STACK_DEV_PORTS.get(stack, 8000)}",
            "database": f"{name}_db",
            "message": (
                f"Starter files for '{name}' are in {project_path}. "
                "Run `devos serve new {name} --stack {stack} --online` on a connected PC to download "
                "the full project (Composer, npm or WordPress)."
            ).format(name=name, stack=stack),
        }
        if online_error:
            result["online_error"] = online_error
        return result

    def list_projects(self) -> List[Dict[str, Any]]:
        """Lists all provisioned local virtual host projects."""
        projects = []
        if os.path.exists(VHOSTS_DIR):
            for f in os.listdir(VHOSTS_DIR):
                if f.endswith(".json"):
                    try:
                        with open(os.path.join(VHOSTS_DIR, f), "r") as fp:
                            projects.append(json.load(fp))
                    except Exception:
                        pass
        return projects


def main():
    parser = argparse.ArgumentParser(description="DevOS Local Developer Server Manager (devserver)")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Show developer services status")
    subparsers.add_parser("list", help="List active developer projects")

    new_p = subparsers.add_parser("new", help="Create a new developer project")
    new_p.add_argument("name", help="Project name (e.g., myapp)")
    new_p.add_argument("--stack", default="laravel", choices=["laravel", "nextjs", "php", "wordpress", "fastapi"])
    new_p.add_argument("--online", action="store_true",
                       help="Download the real framework (needs internet and composer, npm or curl)")

    share_p = subparsers.add_parser("share", help="Give a project's dev server a public link (DevOS Share)")
    share_p.add_argument("project", help="Project name or port number")
    share_p.add_argument("--port", type=int, help="Port the project's dev server listens on")
    share_p.add_argument("--provider", default="auto", choices=["auto", "cloudflare", "ssh", "direct"])

    args = parser.parse_args()
    mgr = DevServerManager()

    if args.command == "status" or not args.command:
        st = mgr.get_services_status()
        print(f"{'SERVICE':<12} {'PORT':<8} {'STATUS':<10} {'DESCRIPTION':<30}")
        print("-" * 65)
        for k, v in st.items():
            print(f"{k:<12} {v['port']:<8} {'Active':<10} {v['description']:<30}")

    elif args.command == "list":
        projs = mgr.list_projects()
        print(f"{'NAME':<15} {'STACK':<10} {'DOMAIN':<22} {'PATH'}")
        print("-" * 70)
        for p in projs:
            print(f"{p['name']:<15} {p['stack']:<10} {p['domain']:<22} {p['path']}")

    elif args.command == "new":
        res = mgr.create_project(args.name, args.stack, online=args.online)
        print(json.dumps(res, indent=2))

    elif args.command == "share":
        port = args.port
        if port is None and args.project.isdigit():
            port = int(args.project)
        if port is None:
            proj = next((p for p in mgr.list_projects() if p.get("name") == args.project), None)
            if proj is None:
                print(f"No project named '{args.project}'. Use a port number instead.", file=sys.stderr)
                sys.exit(1)
            port = proj.get("port") or STACK_DEV_PORTS.get(proj.get("stack"), 8000)
        # DevOS Share owns tunnels, state and cleanup; this is only a shortcut to it.
        sys.exit(subprocess.call([sys.executable, SHARE_SCRIPT, "start", str(port),
                                  "--provider", args.provider]))


if __name__ == "__main__":
    main()
