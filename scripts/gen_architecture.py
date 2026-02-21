#!/usr/bin/env python3
"""Generate Excalidraw architecture diagram V3 - icon + wireframe hybrid.

Embeds icons from Excalidraw libraries:
  - system-design.excalidrawlib (server, cloud, DB, web app, pipeline)
  - system-design-template.excalidrawlib (speech bubble for D-Mail)
  - basic-ux-wireframing-elements.excalidrawlib (bulb for hibernate)
  - network-icons.excalidrawlib (server rack)

Usage: python scripts/gen_architecture.py
Output: docs/architecture.excalidraw
"""

import json
import random
import copy
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).resolve().parent.parent
LIBS_DIR = ROOT / "docs" / "libs"

# ---------------------------------------------------------------------------
# Library loader
# ---------------------------------------------------------------------------

def load_lib(filename):
    path = LIBS_DIR / filename if (LIBS_DIR / filename).exists() else ROOT / filename
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("libraryItems", data.get("library", []))
    result = []
    for item in items:
        if isinstance(item, dict):
            result.append(item.get("elements", []))
        elif isinstance(item, list):
            result.append(item)
    return result


def extract_icon(lib_items, index):
    """Deep-copy elements of a library item."""
    return copy.deepcopy(lib_items[index])


def reposition(els, target_x, target_y, scale=1.0):
    """Move a group of elements so their top-left is at (target_x, target_y).
    Optionally scale."""
    xs = [e["x"] for e in els]
    ys = [e["y"] for e in els]
    ox, oy = min(xs), min(ys)
    for e in els:
        e["x"] = target_x + (e["x"] - ox) * scale
        e["y"] = target_y + (e["y"] - oy) * scale
        if "width" in e:
            e["width"] *= scale
        if "height" in e:
            e["height"] *= scale
        if "points" in e:
            e["points"] = [[p[0] * scale, p[1] * scale] for p in e["points"]]
        if "fontSize" in e:
            e["fontSize"] *= scale
        # New unique ID
        e["id"] = f"lib_{random.randint(10000, 99999)}_{id(e) % 10000}"
        e["seed"] = random.randint(100000, 999999999)
        e["versionNonce"] = random.randint(100000, 999999999)
        # Clear bindings to avoid conflicts
        e["boundElements"] = e.get("boundElements") or []
        if "startBinding" in e:
            e["startBinding"] = None
        if "endBinding" in e:
            e["endBinding"] = None
    return els


# ---------------------------------------------------------------------------
# Element primitives
# ---------------------------------------------------------------------------

STROKE = "#1e1e1e"
elements = []
_ctr = 0


def _id():
    global _ctr
    _ctr += 1
    return f"v3_{_ctr:04d}"


def _seed():
    return random.randint(100000, 999999999)


def box(x, y, w, h, dashed=False, stroke=STROKE, sw=2):
    bid = _id()
    elements.append({
        "id": bid, "type": "rectangle",
        "x": x, "y": y, "width": w, "height": h,
        "angle": 0, "strokeColor": stroke,
        "backgroundColor": "transparent", "fillStyle": "hachure",
        "strokeWidth": sw, "strokeStyle": "dashed" if dashed else "solid",
        "roughness": 1, "opacity": 100, "groupIds": [],
        "roundness": {"type": 3}, "seed": _seed(),
        "version": 1, "versionNonce": _seed(),
        "isDeleted": False, "boundElements": [],
        "updated": 1, "link": None, "locked": False,
    })
    return bid


def txt(x, y, content, size=16, align="left", color=STROKE):
    tid = _id()
    lines = content.split("\n")
    w = max(len(ln) for ln in lines) * size * 0.55 + 10
    h = len(lines) * size * 1.25
    elements.append({
        "id": tid, "type": "text",
        "x": x, "y": y, "width": w, "height": h,
        "angle": 0, "strokeColor": color,
        "backgroundColor": "transparent", "fillStyle": "hachure",
        "strokeWidth": 1, "strokeStyle": "solid",
        "roughness": 1, "opacity": 100, "groupIds": [],
        "roundness": None, "seed": _seed(),
        "version": 1, "versionNonce": _seed(),
        "isDeleted": False, "boundElements": None,
        "updated": 1, "link": None, "locked": False,
        "text": content, "fontSize": size, "fontFamily": 1,
        "textAlign": align, "verticalAlign": "top",
        "baseline": int(size * 0.88),
    })
    return tid


def arr(x, y, dx, dy, bidir=False, dashed=False, sw=2, stroke=STROKE):
    aid = _id()
    elements.append({
        "id": aid, "type": "arrow",
        "x": x, "y": y, "width": abs(dx), "height": abs(dy),
        "angle": 0, "strokeColor": stroke,
        "backgroundColor": "transparent", "fillStyle": "hachure",
        "strokeWidth": sw, "strokeStyle": "dashed" if dashed else "solid",
        "roughness": 1, "opacity": 100, "groupIds": [],
        "roundness": {"type": 2}, "seed": _seed(),
        "version": 1, "versionNonce": _seed(),
        "isDeleted": False, "boundElements": None,
        "updated": 1, "link": None, "locked": False,
        "points": [[0, 0], [dx, dy]], "lastCommittedPoint": None,
        "startBinding": None, "endBinding": None,
        "startArrowhead": "arrow" if bidir else None,
        "endArrowhead": "arrow",
    })
    return aid


def add_icon(els):
    """Append library icon elements to the diagram."""
    elements.extend(els)


# ---------------------------------------------------------------------------
# Load libraries
# ---------------------------------------------------------------------------

sys_design = load_lib("system-design.excalidrawlib")       # from docs/libs/
sys_tpl = load_lib("system-design-template.excalidrawlib")  # from root
ux_lib = load_lib("basic-ux-wireframing-elements.excalidrawlib")  # from root
net_icons = load_lib("network-icons.excalidrawlib")         # from docs/libs/

# ---------------------------------------------------------------------------
# Build V3 diagram
# ---------------------------------------------------------------------------

# ==================== TITLE ====================
txt(340, 30, "Polymarket Auto Trading Agent", size=32, color="#e67700")

# ==================== MAIN FLOW (horizontal, y~160-340) ====================
# Layout: 5 stations, each ~200px wide, spaced ~280px apart
# x positions: 80, 360, 640, 960, 1280

# --- 1. SCHEDULER ---
server_icon = extract_icon(net_icons, 5)  # Server rack
add_icon(reposition(server_icon, 105, 130, scale=0.85))
txt(75, 242, "Scheduler", size=18, align="center")
txt(55, 266, "Runs every 30 min\nor wakes from sleep", size=12, align="center")
txt(72, 300, "agent/scheduler.py", size=11, align="center", color="#868e96")

# --- 2. SESSION START HOOK ---
box(310, 145, 190, 100)
txt(322, 152, "SessionStart Hook", size=15, align="center")
txt(322, 176, "Auto-redeem profits\nSync blockchain state\nAuto stop-loss sell", size=12, align="left")
txt(320, 258, "hooks/session_start.py", size=11, align="center", color="#868e96")

# --- 3. CLAUDE AGENT (main, larger) ---
box(560, 130, 230, 130, sw=3)
app_server = extract_icon(sys_design, 1)  # Application server
add_icon(reposition(app_server, 578, 142, scale=0.65))
txt(638, 142, "Claude Agent", size=20, align="center")
txt(638, 170, "AI decision engine", size=13, align="center")
txt(578, 198, "Researches markets, then\ndecides BUY / SELL / HOLD", size=12, align="left")
txt(578, 232, "Sends D-Mail to future self", size=11, align="left")
txt(610, 274, "agent/main.py", size=11, align="center", color="#868e96")

# --- 4. MCP SERVER ---
pipeline = extract_icon(sys_design, 18)  # Pipeline
add_icon(reposition(pipeline, 870, 142, scale=1.0))
box(855, 130, 190, 120)
txt(870, 138, "MCP Server", size=18, align="center")
txt(870, 165, "11 tools via stdio", size=13, align="center")
txt(862, 188, "Search markets\nAnalyze opportunity\nPlace orders", size=11, align="left")
txt(880, 264, "mcp_server/", size=11, align="center", color="#868e96")

# --- 5. EXTERNAL APIS ---
cloud = extract_icon(sys_design, 19)  # Cloud
add_icon(reposition(cloud, 1160, 130, scale=1.2))
txt(1140, 222, "External APIs", size=18, align="center")
txt(1130, 248, "Gamma (markets)\nCLOB (orders)\nPolygon (blockchain)", size=12, align="left")

# ==================== ARROWS: MAIN FLOW ====================
# Scheduler -> Hook
arr(195, 190, 113, 0)
txt(205, 165, "every 30min", size=12)

# Hook -> Agent
arr(500, 195, 58, 0)
txt(503, 170, "inject state", size=12)

# Agent <-> MCP
arr(790, 195, 63, 0, bidir=True)
txt(795, 170, "tool calls", size=12)

# MCP -> APIs
arr(1045, 190, 105, 0)
txt(1050, 166, "HTTP / RPC", size=12)

# ==================== BOTTOM ROW (y~400-580) ====================
# Supporting components below the main flow, with more vertical gap

BOT_Y = 420  # base y for bottom row

# --- Hibernate toggle (ON = auto-sleep loop active) ---
toggle = extract_icon(ux_lib, 8)  # Rounded toggle with text (ON)
add_icon(reposition(toggle, 110, BOT_Y, scale=4.0))
txt(82, BOT_Y + 80, "Auto-Sleep Loop", size=15, align="center")
txt(68, BOT_Y + 102, "Agent sleeps, then wakes\nat scheduled time to trade", size=11, align="center")

# --- D-Mail (speech bubble from template) ---
bubble = extract_icon(sys_tpl, 2)  # Speech bubble
add_icon(reposition(bubble, 340, BOT_Y - 10, scale=0.40))
txt(350, BOT_Y + 5, "D-Mail", size=16, align="center")
txt(340, BOT_Y + 60, "Message from past self\nto future self, injected\ninto next wake prompt", size=11, align="left")
txt(355, BOT_Y + 105, "hibernate.csv", size=11, align="center", color="#868e96")

# --- Workspace (DB icon) ---
db_icon = extract_icon(sys_design, 6)  # Relational DB
add_icon(reposition(db_icon, 870, BOT_Y - 5, scale=0.55))
txt(865, BOT_Y + 75, "Workspace", size=16, align="center")
txt(855, BOT_Y + 98, "All persistent state:\nbalance, positions, trades\ndecision log, exec traces", size=11, align="left")
txt(880, BOT_Y + 148, "workspace/", size=11, align="center", color="#868e96")

# --- Web UI (web app icon) ---
webapp = extract_icon(sys_design, 23)  # Web Application
add_icon(reposition(webapp, 1160, BOT_Y - 10, scale=0.72))
txt(1148, BOT_Y + 68, "Web UI", size=16, align="center")
txt(1135, BOT_Y + 90, "Live dashboard with\nreal-time P&L, positions\nand execution replay", size=11, align="left")
txt(1165, BOT_Y + 148, "web-ui/", size=11, align="center", color="#868e96")

# ==================== ARROWS: VERTICAL CONNECTIONS ====================
# Agent -> D-Mail (down)
arr(660, 264, -240, 155, dashed=True, sw=1)
txt(475, 340, "writes D-Mail", size=11, color="#868e96")

# Scheduler -> Auto-Sleep (down)
arr(150, 305, 0, 112, dashed=True, sw=1)
txt(160, 355, "sleep/wake", size=11, color="#868e96")

# MCP -> Workspace (down)
arr(950, 254, 0, 164, dashed=True, sw=1)
txt(958, 340, "persist state", size=11, color="#868e96")

# APIs -> Web UI (down)
arr(1200, 300, 0, 118, dashed=True, sw=1)
txt(1208, 355, "live prices", size=11, color="#868e96")

# Web UI -> Workspace (left, read files)
arr(1140, 505, -190, 0)
txt(990, 484, "read files", size=12)

# ==================== RISK MANAGEMENT (annotation) ====================
box(330, 610, 520, 42, dashed=True, stroke="#868e96", sw=1)
txt(345, 618, "Risk:  max_buy=$0.99  |  max_position=20%  |  stop_loss=20%    (config/risk.py)", size=13, color="#868e96")


# ---------------------------------------------------------------------------
# Assemble and write
# ---------------------------------------------------------------------------

doc = {
    "type": "excalidraw",
    "version": 2,
    "source": "https://excalidraw.com",
    "elements": elements,
    "appState": {
        "gridSize": None,
        "viewBackgroundColor": "#ffffff",
        "currentItemStrokeColor": STROKE,
        "currentItemBackgroundColor": "transparent",
        "currentItemFillStyle": "hachure",
        "currentItemStrokeWidth": 2,
        "currentItemStrokeStyle": "solid",
        "currentItemRoughness": 1,
        "currentItemOpacity": 100,
    },
    "files": {},
}

out_dir = ROOT / "docs"
out_dir.mkdir(exist_ok=True)
out_path = out_dir / "architecture.excalidraw"

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2, ensure_ascii=False)

print(f"Generated: {out_path}")
print(f"Elements:  {len(elements)}")
icon_count = sum(1 for e in elements if e["id"].startswith("lib_"))
print(f"  Library icons: {icon_count} elements from 6 icons")
print(f"  Custom:        {len(elements) - icon_count} elements")
