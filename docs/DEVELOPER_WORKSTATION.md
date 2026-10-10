# DevOS Developer Workstation Guide

DevOS transforms your machine into a high-performance, turnkey developer workstation pre-configured for modern web, cloud, and AI engineering.

---

## 1. Quickstart: One-Click Projects (`devserver`)

Similar to Laragon on Windows, `devserver` provisions full web stacks with automated local domains (`https://*.test`) and trusted SSL certificates via `mkcert`:

### Create a Laravel Project:
```bash
devos serve new myapp --stack laravel
# -> Provisions project directory at ~/DevOSProjects/myapp
# -> Sets up https://myapp.test with trusted HTTPS
# -> Configures MariaDB database `myapp_db` and .env
```

### Create a Next.js Project:
```bash
devos serve new frontend --stack nextjs
# -> Sets up Next.js app with Tailwind CSS at https://frontend.test
```

### Create a FastAPI Python Service:
```bash
devos serve new api --stack fastapi
# -> Provisions FastAPI application ready for local Uvicorn serving
```

---

## 2. Pre-Configured Developer Services

All local services run on standard ports with on-demand socket activation to preserve idle RAM ($\le 900\text{ MB}$ target):

| Service | Port | Description |
|---|---|---|
| **Web Server (Caddy/Nginx)** | 80 / 443 | Automatic HTTPS reverse proxy for `*.test` |
| **PHP 8.3 FPM** | 9000 | FastCGI for Laravel, WordPress, and plain PHP |
| **MariaDB (MySQL)** | 3306 | Relational database (root user passwordless on localhost) |
| **PostgreSQL** | 5432 | Advanced relational database |
| **Redis** | 6379 | In-memory cache and queue broker |
| **Mailpit** | 1025 / 8025 | Local email sandbox with web UI at `http://localhost:8025` |

Check status anytime:
```bash
devos serve status
```

---

## 3. Editor & Local AI Coding Agent

### VSCodium (Telemetry-Free VS Code)
- Pre-installed with keybindings matching Windows VS Code.
- Pre-loaded with open-source formatters (Prettier, Intelephense, Python, Tailwind).
- Integrated terminal defaults to Bash.

### Local AI Agent Integration (`Continue`)
- The **Continue** sidebar extension is pre-configured to communicate directly with the local DevOS AI Core (`http://127.0.0.1:11434/v1`).
- **Tab Autocomplete**: Fast inline completion powered by local `Qwen2.5-Coder 1.5B`.
- **Chat & Edits**: Full codebase reasoning powered by `Qwen2.5-Coder 7B/14B`.
- **100% Free & Offline**: No API keys, no telemetry, zero cost.

### CLI Code Agent:
You can also generate and test code directly from the terminal:
```bash
devos code "Create an Eloquent User model with soft deletes and email verification" --framework laravel
```

---

## 4. Containers & Virtualization

- **Rootless Podman**: Drop-in Docker replacement without daemon root vulnerabilities.
- Run `docker` or `podman` interchangeably (`alias docker=podman`).
- Fast container startup using native Linux cgroups v2.
