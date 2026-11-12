Memex: Local Client-Server Markdown Workspace

1. Core Objective
The agent must design and generate a complete, self-contained client-server productivity application. The application will serve as a graphical interface for managing a hierarchical local directory of Markdown files. It must function entirely offline on a corporate workstation using a local runtime (Python or Node.js - Python preferred), requiring no administrative installation rights.
2. Environmental & Security Constraints
* Air-Gapped Operation: The application must not make any outbound network requests to the internet. All frontend assets (HTML, CSS, JS, fonts, icons) must be bundled within the project and served locally by the backend. No CDN links are permitted.
* Localhost Isolation: The backend server must explicitly bind to 127.0.0.1 (localhost) and never to 0.0.0.0. This guarantees the server is completely invisible to the corporate LAN and accessible only from the host machine.
* Zero Telemetry: The application must not include any tracking, crash reporting, or analytics software.
* No Admin Installation: The solution must run from a standard user directory using standard, pre-existing local runtimes (e.g., executing node server.js or python main.py).
3. Architecture Overview
* Backend: A lightweight local server (e.g., Express.js for Node, or FastAPI/Flask for Python) that handles all direct file system operations.
* Frontend: A modern Single Page Application (SPA) utilizing vanilla JavaScript or a lightweight bundled framework. It communicates with the backend exclusively via local HTTP REST/JSON APIs.
* Storage Layer: The native OS file system. There is no traditional database (like SQL or MongoDB). The folder structure is the database.
4. Backend (Server) Requirements
The agent must generate server code that implements the following API endpoints and behaviors:
* Static Asset Serving: The server must host the frontend SPA files on the root route (/).
* Directory API (GET /api/tree): Recursively scans the designated root workspace directory and returns a JSON representation of the folder and file hierarchy.
* File Read API (GET /api/files?path=...): Accepts a relative path, reads the specified Markdown file from the disk, and returns the raw text content.
* File Write API (POST /api/files, PUT /api/files): Accepts a relative path and a text payload, natively creating or overwriting the .md file on the disk.
* File/Folder Management (DELETE /api/files, POST /api/move): Handles renaming, moving, and deleting files and folders, ensuring the local disk perfectly mirrors the user's actions in the UI.
* Local Search (Optional/Bonus): Implement a fast, in-memory or lightweight text search across all Markdown files to return file paths matching user queries.
5. Frontend (Client) Requirements
The agent must generate frontend code with the following user experience:
* Dual-Pane Interface: A collapsible left sidebar displaying the hierarchical file tree (folders and files) and a main content area for the Markdown editor.
* Live Editor: A text area or split-pane editor that allows the user to write raw Markdown and see a rendered visual preview.
* API Integration: All user actions (creating a file, typing, moving a folder) must trigger asynchronous fetch() calls to the local backend APIs to ensure UI state and disk state remain synchronized.
* Auto-Save: The editor should debounce user input and automatically send PUT requests to the backend to save progress without requiring a manual "Save" button.
6. Data Format & File System Rules
* Strict Markdown: All text data must be saved as standard .md files.
* YAML Frontmatter: Application-specific metadata (e.g., tags, due dates, creation timestamps, task status) must be stored at the very top of the .md files using standard YAML frontmatter blocks bounded by ---.
* Data Portability: The root workspace directory must contain only the user's Markdown data and folders. The application source code must live in a completely separate directory so the user can easily zip or back up their workspace independently.

Functional Requirements

- I want to create and view Project Themes, which can have zero or more Projects, which in turn can have zero or more Deliverables.
- I want to be able to enter all my team members, with multiple levels of hierarchy. I want to be able to tag team members to Themes, Projects and Deliverables.
- I want to be able to define Stakeholders and tag them to Themes, Projects and Deliverables.
- I want to be able to have somewhere to capture terms and phrases in a Glossary
- I want to be able to bookmark links
- I want to be able to record and see my to-dos
- I want to be able to record to-dos for others 
- I want to be able to have a team member view where I can see what projects and deliverables they are tagged to, and any to-dos I am waiting for from them, also any actions they are waiting on for me.
- I want to have a mind-map view for Themes and for People, focused on my Directs or on Stakeholders. 
- I want the application to have an MCP interface so I can interact with it via an AI agent
