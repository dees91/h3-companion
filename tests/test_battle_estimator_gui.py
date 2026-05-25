from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tools import battle_estimator_gui
from tests.test_battle_estimator_cli import (
    _build_xor_hero_fixture,
    _removed_neutral_record_core_bytes,
    _write_h3m_map,
    _write_xor_hero_window,
)
from tests.test_h3_map_parser import (
    _minimal_h3m_with_templates_and_objects,
    _object_bytes,
    _object_template_bytes,
    _town_payload,
)
from tools import h3_map_parser, h3_save_parser, hero_skill_recommender


class BattleEstimatorGuiServerTests(unittest.TestCase):
    def _with_server(self, callback, app_state=None):
        server = battle_estimator_gui.create_server(port=0, app_state=app_state)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            callback(battle_estimator_gui.server_url(server))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def _get(self, base_url, path):
        with urlopen(f"{base_url}{path}", timeout=2) as response:
            return (
                response.status,
                response.headers.get("Content-Type"),
                response.read(),
            )

    def _get_json(self, base_url, path):
        status, content_type, body = self._get(base_url, path)
        self.assertEqual(content_type, "application/json")
        return status, json.loads(body.decode("utf-8"))

    def _post_json(self, base_url, path, payload):
        request = Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return (
                response.status,
                response.headers.get("Content-Type"),
                json.loads(response.read().decode("utf-8")),
            )

    def _post_raw(self, base_url, path, body):
        request = Request(
            f"{base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return (
                response.status,
                response.headers.get("Content-Type"),
                response.read(),
            )

    def test_health_endpoint_returns_json_ok(self):
        def check(base_url):
            status, content_type, body = self._get(base_url, "/api/health")

            self.assertEqual(status, 200)
            self.assertEqual(content_type, "application/json")
            self.assertEqual(json.loads(body.decode("utf-8")), {"ok": True})

        self._with_server(check)

    def test_static_assets_are_served_from_whitelisted_routes(self):
        def check(base_url):
            cases = (
                (
                    "/",
                    "text/html; charset=utf-8",
                    b'data-testid="top-status"',
                ),
                (
                    "/index.html",
                    "text/html; charset=utf-8",
                    b'data-testid="hero-panel"',
                ),
                (
                    "/app.js",
                    "application/javascript; charset=utf-8",
                    b'getJson("/api/state"',
                ),
                (
                    "/style.css",
                    "text/css; charset=utf-8",
                    b".map-panel",
                ),
            )
            for path, expected_type, expected_body in cases:
                with self.subTest(path=path):
                    status, content_type, body = self._get(base_url, path)

                    self.assertEqual(status, 200)
                    self.assertEqual(content_type, expected_type)
                    self.assertIn(expected_body, body)

            _, _, html = self._get(base_url, "/")
            self.assertIn(b'data-testid="map-panel"', html)
            self.assertIn(b'data-testid="result-panel"', html)

        self._with_server(check)

    def test_static_routes_are_allowlisted(self):
        def check(base_url):
            for path in ("/missing", "/../battle_estimator.py", "/%2e%2e/battle_estimator.py"):
                with self.subTest(path=path):
                    with self.assertRaises(HTTPError) as raised:
                        self._get(base_url, path)

                    self.assertEqual(raised.exception.code, 404)

        self._with_server(check)

    def test_frontend_shell_uses_safe_dom_text_rendering(self):
        app_js = (
            Path("tools") / "battle_estimator_gui" / "app.js"
        ).read_text(encoding="utf-8")
        index_html = (
            Path("tools") / "battle_estimator_gui" / "index.html"
        ).read_text(encoding="utf-8")
        style_css = (
            Path("tools") / "battle_estimator_gui" / "style.css"
        ).read_text(encoding="utf-8")

        self.assertNotIn("innerHTML", app_js)
        self.assertIn("textContent", app_js)
        self.assertIn("Snapshot unavailable", app_js)
        load_state_body = app_js[
            app_js.index("function loadState()"):
            app_js.index("function checkHealth()")
        ]
        select_hero_body = app_js[
            app_js.index("function selectHero("):
            app_js.index("function renderSnapshot(")
        ]
        simulate_target_body = app_js[
            app_js.index("function simulateTarget("):
            app_js.index("function setHiddenTarget(")
        ]
        scan_result_body = app_js[
            app_js.index("function selectScanResult("):
            app_js.index("function runRadiusScan(")
        ]
        self.assertNotIn("setHealth(", load_state_body)
        self.assertIn("renderRecentHeroes(heroState.recentHeroes);", select_hero_body)
        self.assertNotIn("selectedHeroId =", simulate_target_body)
        self.assertNotIn("/api/select-hero", simulate_target_body)
        self.assertIn("estimateState.requestId", simulate_target_body)
        self.assertIn("isFreshEstimatePayload(", simulate_target_body)
        self.assertNotIn("selectedHeroId =", scan_result_body)
        self.assertNotIn("/api/simulate-target", scan_result_body)
        self.assertIn("renderEstimateResult({", scan_result_body)
        self.assertIn('setText(elements.mode, "Snapshot unavailable")', app_js)
        self.assertIn('renderRecentHeroes([])', app_js)
        for expected in (
            "__battleEstimatorGuiTest",
            "buildMarkerCache",
            "defaultLevelForSnapshot",
            "worldToScreen",
            "screenToWorld",
            "zoomAtPoint",
            "hitTestMarker",
            "markerContainsScreenPoint",
            "markerScreenRadius",
            "markerTooltipText",
            "nextViewStateForSnapshot",
            "resolveSelectedHeroId",
            "sameMapGeometry",
            "pointerdown",
            "pointermove",
            "pointerup",
            "wheel",
            "ResizeObserver",
            "selected_hero_id",
            "estimator_creature_id",
            "removed",
            "hidden",
            "heroSearch",
            "filterHeroesForQuery",
            "matchRecentHeroName",
            "recentHeroChipState",
            "rankedMapHeroes",
            "formatWinPct",
            "isFreshEstimatePayload",
            "isFreshScanPayload",
            "scanClassForWinPct",
            "scanResultLookup",
            "simulationClickDecision",
            "sortedScanResults",
            "verdictForWinPct",
            "typeof winPct === \"number\"",
            "ambiguous in this snapshot",
            "is not in this snapshot",
            "Selected hero is not a simulation target.",
            "Hidden target is ignored.",
            "Scan response did not match the current request.",
            'addEventListener("input"',
            'addEventListener("contextmenu"',
            '"/api/select-hero"',
            '"/api/simulate-target"',
            '"/api/scan-radius"',
            '"/api/path-route"',
            '"/api/hidden-target"',
            '"/api/show-hidden"',
            '"/api/saves"',
            '"/api/save-mode"',
            '"/api/game-folders"',
            '"/api/game-folder"',
            '"/api/hero-skills"',
            '"/api/hero-skills/save"',
            '"/api/hero-skills/reset"',
            '"/api/hero-skills/compare"',
            "previousSaveButton",
            "nextSaveButton",
            "navigateSave",
            "heroSkillsButton",
            "heroSkillsDialog",
            "heroSkillSlots",
            "showHeroSkillsDialog",
            "hideHeroSkillsDialog",
            "saveHeroSkills",
            "resetHeroSkills",
            "compareHeroSkillOffers",
            "heroSkillOfferValidationMessage",
            "heroSkillSaveValidationMessage",
            "current_skills_source",
            "heroRankingButton",
            "heroRankingDialog",
            "renderHeroRanking",
            "gameFolderPath",
            "gameFolderInFlight",
            "showFollowLatestDialog",
            "showHiddenToggle",
            "routeOverlayToggle",
            "portalLinksToggle",
            "targetFilterControl",
            "targetFilter",
            "scanTargetTypeForFilter",
            "scanSortControl",
            "sortMode",
            "normalizeScanSortMode",
            "targetContextMenu",
            "hiddenTargetInFlight",
            "hidden_hero_target_ids",
            "setHiddenTarget",
            "Select as my hero",
            "Current hero",
            "showHiddenInFlight",
            "showRouteOverlay",
            "showPortalLinks",
            "ROUTE_OVERLAY_STYLES",
            "drawRouteOverlay",
            "drawPortalRelationOverlay",
            "portalCrossLevelSummaries",
            "routeRowsForLevel",
            "routeStateForChar",
            "routeStyleForChar",
            "pathModeToggle",
            "pathState",
            "setPathMode",
            "drawPathRoute",
            "tilePositionForCanvasPoint",
            "isFreshPathPayload",
            "currentPathStateForTest",
            "pathSegmentsForPayload",
            "pathSegmentTypeLabel",
            "pathSegmentFocusPosition",
            "focusPathSegment",
            "centerOnWorldPoint",
            "Select a hero before pathing.",
            "Path target is outside the map.",
            "use_latest_game_folder",
            "town_targets",
            "portal_targets",
            "portal_edges",
            "TOWN_MARKER_STYLE",
            "PORTAL_MARKER_STYLES",
            "currentMapViewForTest",
            "Town target is not a battle simulation target.",
            "Portal target is not a battle simulation target.",
            "portalDestinationText",
            "portalMarkerSymbolKind",
            "drawPortalMarkerSymbol",
            "portalRelationForSource",
            "currentPortalRelation",
            "currentPortalRelationStateForTest",
            "context-menu-note",
            "Initial owner:",
            "AUTO_REFRESH_MS = 5000",
            "AUTO_REFRESH_ENABLED = false",
            "require manual Refresh until UX settles",
            "setInterval",
            "snapshotChanged",
            "owner_color_id",
            "owner_color_name",
            "team_id",
            "PLAYER_COLOR_STYLES",
            "FOLLOW_LATEST_MODE",
            "PINNED_MODE",
            "return Promise.resolve();",
            "elements.refreshButton.disabled = busy;"
        ):
            self.assertIn(expected, app_js)
        for expected in (
            'id="game-folder-picker"',
            'id="game-folder-path"',
            'id="use-game-folder-button"',
            'id="hero-search"',
            'id="recent-heroes"',
            'class="panel-section detected-heroes-section"',
            'id="hero-list"',
            'id="save-picker"',
            'id="previous-save-button"',
            'id="next-save-button"',
            'id="follow-latest-button"',
            'id="follow-latest-dialog"',
            'id="follow-current-folder-button"',
            'id="follow-latest-folder-button"',
            'id="follow-cancel-button"',
            'id="hero-skills-button"',
            'id="hero-skills-dialog"',
            'id="hero-skills-status"',
            'id="hero-skill-slots"',
            'id="hero-skill-recommendations"',
            'id="hero-skill-avoid"',
            'id="hero-skill-compare-controls"',
            'id="hero-skill-compare-result"',
            'id="hero-skills-save-button"',
            'id="hero-skills-reset-button"',
            'id="hero-skills-compare-button"',
            'id="hero-ranking-button"',
            'id="hero-ranking-dialog"',
            'id="hero-ranking-list"',
            'id="hero-ranking-close-button"',
            'id="map-level-control"',
            'id="show-removed-toggle"',
            'id="show-hidden-toggle"',
            'id="show-route-overlay-toggle"',
            'id="portal-links-toggle"',
            'id="path-mode-toggle"',
            'id="target-filter-control"',
            'Route Overlay',
            'Portal Links',
            'Path Mode',
            'id="map-stage"',
            'id="map-tooltip"',
            'id="target-context-menu"',
            'id="scan-radius"',
            'id="path-state"',
            'id="scan-sort-control"',
            'id="scan-button"',
        ):
            self.assertIn(expected, index_html)
        self.assertNotIn('id="scan-target-type"', index_html)
        for expected in (
            ".chip-button",
            ".hero-item",
            ".hero-item.selected",
            ".item-title-row",
            ".color-swatch",
            ".estimate-grid",
            ".result-box.error",
            ".scan-result",
            ".scan-result.strong",
            ".top-actions",
            ".save-nav-controls",
            ".icon-button",
            ".toolbar-button",
            ".dialog-backdrop",
            ".dialog-panel",
            ".dialog-actions",
            ".skills-dialog-panel",
            ".skills-dialog-body",
            ".skill-slot-row",
            ".skill-entry",
            ".skill-compare-row",
            ".ranking-dialog-panel",
            ".ranking-list",
            ".ranking-item",
            ".segmented-control",
            ".toggle-control",
            ".map-tooltip",
            ".path-result",
            ".path-segment-list",
            ".path-segment",
            "#battle-map.path-mode",
            ".target-context-menu",
            ".context-menu-title",
            "#battle-map",
            "width: 100%;",
            "height: calc(100vh - 73px);",
            ".detected-heroes-section",
            "align-content: start;",
            "align-items: start;",
            "flex: 1 1 auto;",
            "grid-auto-rows: max-content;",
            "min-height: 0;",
            "overflow-y: auto;",
            "grid-template-rows: auto minmax(0, 1fr);",
            "place-items: start center;",
        ):
            self.assertIn(expected, style_css)

    def test_frontend_estimate_helpers_cover_click_and_stale_edges(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for frontend helper smoke test")

        app_js_path = str((Path("tools") / "battle_estimator_gui" / "app.js").resolve())
        script = f"""
(async function main() {{
const assert = require("assert");
const drawOperations = [];
const routeFillStyles = new Set(["#d9ead5", "#c8e2f2", "#87919e"]);
const townFillStyles = new Set(["#f8c756", "#f4e7c4"]);
const portalFillStyles = new Set(["#0f9f9a", "#7c3aed", "#d85fa3"]);
const context = new Proxy({{
  save() {{
    drawOperations.push({{ op: "save" }});
  }},
  restore() {{
    drawOperations.push({{ op: "restore" }});
  }},
  clearRect(x, y, width, height) {{
    drawOperations.push({{ op: "clearRect", x, y, width, height }});
  }},
  beginPath() {{
    this.lastArc = null;
    drawOperations.push({{ op: "beginPath" }});
  }},
  arc(x, y, radius, startAngle, endAngle) {{
    this.lastArc = {{ x, y, radius, startAngle, endAngle }};
    drawOperations.push({{ op: "arc", x, y, radius, startAngle, endAngle }});
  }},
  fill() {{
    drawOperations.push({{
      op: "fill",
      fillStyle: this.fillStyle,
      globalAlpha: this.globalAlpha,
      arc: this.lastArc
    }});
  }},
  fillRect(x, y, width, height) {{
    drawOperations.push({{
      op: "fillRect",
      fillStyle: this.fillStyle,
      globalAlpha: this.globalAlpha,
      x,
      y,
      width,
      height
    }});
  }},
  strokeRect(x, y, width, height) {{
    drawOperations.push({{
      op: "strokeRect",
      strokeStyle: this.strokeStyle,
      lineWidth: this.lineWidth,
      globalAlpha: this.globalAlpha,
      x,
      y,
      width,
      height
    }});
  }},
  moveTo(x, y) {{
    drawOperations.push({{
      op: "moveTo",
      strokeStyle: this.strokeStyle,
      lineWidth: this.lineWidth,
      x,
      y
    }});
  }},
  lineTo(x, y) {{
    drawOperations.push({{
      op: "lineTo",
      strokeStyle: this.strokeStyle,
      lineWidth: this.lineWidth,
      x,
      y
    }});
  }},
  closePath() {{
    drawOperations.push({{ op: "closePath" }});
  }},
  setLineDash(value) {{
    this.lineDash = Array.isArray(value) ? value.slice() : [];
    drawOperations.push({{
      op: "setLineDash",
      value: this.lineDash
    }});
  }},
  stroke() {{
    drawOperations.push({{
      op: "stroke",
      strokeStyle: this.strokeStyle,
      lineWidth: this.lineWidth,
      globalAlpha: this.globalAlpha,
      arc: this.lastArc,
      lineDash: this.lineDash || []
    }});
  }},
  fillText(text, x, y) {{
    drawOperations.push({{
      op: "fillText",
      fillStyle: this.fillStyle,
      font: this.font,
      text,
      x,
      y
    }});
  }},
  strokeText(text, x, y) {{
    drawOperations.push({{
      op: "strokeText",
      strokeStyle: this.strokeStyle,
      font: this.font,
      text,
      x,
      y
    }});
  }},
  measureText(text) {{
    return {{ width: String(text || "").length * 7 }};
  }}
}}, {{
  get(target, prop) {{
    if (!(prop in target)) {{
      target[prop] = function () {{}};
    }}
    return target[prop];
  }},
  set(target, prop, value) {{
    target[prop] = value;
    return true;
  }}
}});
class Element {{
  constructor(id) {{
    this.id = id;
    this.children = [];
    this.className = "";
    this.dataset = {{}};
    this.disabled = false;
    this.height = 640;
    this.hidden = false;
    this.checked = false;
    this.events = {{}};
    this.style = {{}};
    this.textContent = "";
    this.title = "";
    this.value = "";
    this.width = 960;
    this.classList = {{
      add() {{}},
      remove() {{}},
      toggle() {{}}
    }};
  }}
  get firstChild() {{
    return this.children[0] || null;
  }}
  get options() {{
    return this.children;
  }}
  appendChild(child) {{
    this.children.push(child);
    return child;
  }}
  getBoundingClientRect() {{
    return {{ left: 0, top: 0, width: 960, height: 640 }};
  }}
  getContext() {{
    return context;
  }}
  addEventListener(type, handler) {{
    if (!this.events[type]) {{
      this.events[type] = [];
    }}
    this.events[type].push(handler);
  }}
  dispatch(type, event) {{
    return (this.events[type] || []).map((handler) => handler({{ target: this, ...event }}));
  }}
  removeChild(child) {{
    const index = this.children.indexOf(child);
    if (index >= 0) {{
      this.children.splice(index, 1);
    }}
    return child;
  }}
  setAttribute(name, value) {{
    this[name] = value;
  }}
  setPointerCapture() {{}}
}}
const elements = {{}};
global.document = {{
  createElement(tag) {{
    return new Element(tag);
  }},
  getElementById(id) {{
    if (!elements[id]) {{
      elements[id] = new Element(id);
    }}
    return elements[id];
  }}
}};
let autoRefreshIntervalCalls = 0;
global.window = {{
  addEventListener() {{}},
  devicePixelRatio: 1,
  ResizeObserver: null,
  setInterval() {{
    autoRefreshIntervalCalls += 1;
    return 1;
  }}
}};
const snapshot = {{
  mode: "follow_latest",
  save_file: null,
  save_fingerprint: null,
  map_file: null,
  map_fingerprint: null,
  map: {{ width: 4, height: 4, levels: 2 }},
  route_layers: [
    ["LWBB", "LLWB", "BWLX", "LLLL"],
    ["BBBB", "WWWW", "LLLL", "LWBZ"]
  ],
  heroes: [],
  neutral_targets: [],
  town_targets: [],
  portal_targets: [],
  portal_edges: [],
  recent_heroes: [],
  selected_hero_id: null
}};
let fetchCalls = 0;
const fetchRequests = [];
let deferNextScanResponse = false;
let nextScanResults = null;
const pendingScanResponses = [];
let deferNextPathResponse = false;
let nextPathPayload = null;
let nextPathError = null;
const pendingPathResponses = [];
let deferNextHeroSkillsResponse = false;
let nextHeroSkillsError = null;
const pendingHeroSkillsResponses = [];
let heroSkillPayload = null;
function buildHeroSkillPayload(overrides = {{}}) {{
  const base = {{
    hero_id: "hero:0",
    map_key: "map-key",
    role: "main",
    hero: {{
      key: "isra",
      display_name: "Isra",
      save_name: "Isra",
      class_id: "deathKnight",
      faction: "necropolis",
      affinity: "might",
      specialty_summary: "Necromancy",
      starting_skills: [
        {{
          skill: "necromancy",
          skill_id: "necromancy",
          display_name: "Necromancy",
          level: "advanced"
        }}
      ]
    }},
    max_skills: 8,
    skill_levels: ["basic", "advanced", "expert"],
    skills: [
      {{ skill: "necromancy", skill_id: "necromancy", display_name: "Necromancy", index: 8, specialty_tags: [] }},
      {{ skill: "earthMagic", skill_id: "earthMagic", display_name: "Earth Magic", index: 17, specialty_tags: [] }},
      {{ skill: "logistics", skill_id: "logistics", display_name: "Logistics", index: 2, specialty_tags: [] }}
    ],
    current_skills: [
      {{
        skill: "necromancy",
        skill_id: "necromancy",
        display_name: "Necromancy",
        level: "advanced"
      }}
    ],
    current_skills_source: "starting",
    top_next: [
      {{
        skill: "necromancy",
        skill_id: "necromancy",
        display_name: "Necromancy",
        target_level: "expert",
        score: 99,
        tier: "S",
        availability: "available",
        reason_codes: ["hero_specialty"]
      }},
      {{
        skill: "earthMagic",
        skill_id: "earthMagic",
        display_name: "Earth Magic",
        target_level: "basic",
        score: 96,
        tier: "S",
        availability: "available",
        reason_codes: ["mass_slow"]
      }}
    ],
    avoid: [
      {{
        skill: "scouting",
        skill_id: "scouting",
        display_name: "Scouting",
        target_level: "basic",
        score: 28,
        tier: "D",
        availability: "available",
        reason_codes: ["low_combat_value"]
      }}
    ],
    offer_comparison: null
  }};
  return Object.assign(base, overrides);
}}
function heroNameForId(heroId) {{
  const snapshots = [markerSnapshot, hiddenHeroSnapshot].filter(Boolean);
  for (const source of snapshots) {{
    const match = (source.heroes || []).find((hero) => hero.id === heroId);
    if (match) {{
      return match.name || heroId;
    }}
  }}
  return heroId;
}}
global.fetch = (path, options = {{}}) => {{
  fetchCalls += 1;
  fetchRequests.push({{ path, options }});
  let payload = snapshot;
  let responseOk = true;
  let responseStatus = 200;
  let deferResponse = false;
  let deferredResponses = pendingScanResponses;
  if (path === "/api/health") {{
    payload = {{ ok: true }};
  }} else if (path === "/api/select-hero") {{
    const requestPayload = JSON.parse(options.body || "{{}}");
    payload = {{
      selected_hero_id: requestPayload.hero_id,
      recent_heroes: [heroNameForId(requestPayload.hero_id), "Isra"]
    }};
  }} else if (path === "/api/hidden-target") {{
    const requestPayload = JSON.parse(options.body || "{{}}");
    payload = {{
      target_id: requestPayload.target_id,
      hidden: requestPayload.hidden,
      hidden_neutral_target_ids: [],
      hidden_hero_target_ids: requestPayload.hidden ? [requestPayload.target_id] : []
    }};
  }} else if (path === "/api/scan-radius") {{
    const requestPayload = JSON.parse(options.body || "{{}}");
    const resultType = requestPayload.target_type === "hero" ? "hero" : "neutral";
    deferResponse = deferNextScanResponse;
    deferredResponses = pendingScanResponses;
    deferNextScanResponse = false;
    const defaultResults = [
      {{
        target_id: "target:near",
        target_type: resultType,
        distance: 1,
        win_pct: 20,
        enemy_ai_value: 200,
        note: "near",
        target: {{ name: "Near", creature_name: "Near" }}
      }},
      {{
        target_id: "target:easy",
        target_type: resultType,
        distance: 4,
        win_pct: 95,
        enemy_ai_value: 50,
        note: "easy",
        target: {{ name: "Easy", creature_name: "Easy" }}
      }},
      {{
        target_id: "target:missing",
        target_type: resultType,
        distance: 2,
        win_pct: null,
        enemy_ai_value: 999,
        note: "unknown",
        target: {{ name: "Unknown", creature_name: "Unknown" }}
      }}
    ];
    payload = {{
      hero_id: requestPayload.hero_id,
      radius: requestPayload.radius,
      target_type: requestPayload.target_type,
      include_removed: false,
      simulations: 1000,
      results: nextScanResults || defaultResults
    }};
    nextScanResults = null;
  }} else if (path === "/api/path-route") {{
    const requestPayload = JSON.parse(options.body || "{{}}");
    deferResponse = deferNextPathResponse;
    deferredResponses = pendingPathResponses;
    deferNextPathResponse = false;
    if (nextPathError) {{
      responseOk = false;
      responseStatus = nextPathError.status || 400;
      payload = {{ error: nextPathError.error || "path failed" }};
      nextPathError = null;
    }} else {{
      payload = nextPathPayload || {{
        hero_id: requestPayload.hero_id,
        target_id: requestPayload.target_id,
        status: "found",
        requested_target_position: requestPayload.target_position || {{ x: 1, y: 3, z: 0 }},
        resolved_target_position: requestPayload.target_position || {{ x: 1, y: 3, z: 0 }},
        steps: [
          {{ position: {{ x: 1, y: 2, z: 0 }}, route: "land", cost: 0 }},
          {{ position: {{ x: 1, y: 3, z: 0 }}, route: "land", cost: 1 }},
          {{ position: {{ x: 2, y: 3, z: 0 }}, route: "land", cost: 2 }}
        ],
        segments: [
          {{
            segment_type: "walk",
            start_position: {{ x: 1, y: 2, z: 0 }},
            end_position: {{ x: 2, y: 3, z: 0 }},
            is_non_deterministic: false,
            steps: [
              {{ position: {{ x: 1, y: 2, z: 0 }}, route: "land", cost: 0 }},
              {{ position: {{ x: 1, y: 3, z: 0 }}, route: "land", cost: 1 }},
              {{ position: {{ x: 2, y: 3, z: 0 }}, route: "land", cost: 2 }}
            ]
          }}
        ],
        message: null
      }};
      nextPathPayload = null;
    }}
  }} else if (path === "/api/hero-skills") {{
    const requestPayload = JSON.parse(options.body || "{{}}");
    deferResponse = deferNextHeroSkillsResponse;
    deferredResponses = pendingHeroSkillsResponses;
    deferNextHeroSkillsResponse = false;
    if (nextHeroSkillsError) {{
      responseOk = false;
      responseStatus = nextHeroSkillsError.status || 400;
      payload = {{ error: nextHeroSkillsError.error || "skills failed" }};
      nextHeroSkillsError = null;
    }} else {{
      heroSkillPayload = buildHeroSkillPayload({{
        ...(heroSkillPayload || {{}}),
        hero_id: requestPayload.hero_id
      }});
      payload = heroSkillPayload;
    }}
  }} else if (path === "/api/hero-skills/save") {{
    const requestPayload = JSON.parse(options.body || "{{}}");
    const savedSkills = (requestPayload.skills || []).map((skill) => ({{
      skill: skill.skill,
      skill_id: skill.skill,
      display_name: skill.skill === "earthMagic" ? "Earth Magic" : skill.skill,
      level: skill.level
    }}));
    heroSkillPayload = buildHeroSkillPayload({{
      hero_id: requestPayload.hero_id,
      current_skills: savedSkills,
      current_skills_source: savedSkills.length ? "manual" : "starting",
      top_next: [
        {{
          skill: "logistics",
          skill_id: "logistics",
          display_name: "Logistics",
          target_level: "basic",
          score: 92,
          tier: "S",
          availability: "available",
          reason_codes: ["map_tempo"]
        }}
      ],
      offer_comparison: null
    }});
    payload = heroSkillPayload;
  }} else if (path === "/api/hero-skills/reset") {{
    const requestPayload = JSON.parse(options.body || "{{}}");
    heroSkillPayload = buildHeroSkillPayload({{ hero_id: requestPayload.hero_id }});
    payload = heroSkillPayload;
  }} else if (path === "/api/hero-skills/compare") {{
    const requestPayload = JSON.parse(options.body || "{{}}");
    const comparison = {{
      winner: "necromancy:expert",
      reason_codes: ["higher_score"],
      offers: [
        {{
          skill: "earthMagic",
          skill_id: "earthMagic",
          display_name: "Earth Magic",
          target_level: "basic",
          score: 96,
          tier: "S",
          availability: "available",
          reason_codes: ["mass_slow"]
        }},
        {{
          skill: "necromancy",
          skill_id: "necromancy",
          display_name: "Necromancy",
          target_level: "expert",
          score: 99,
          tier: "S",
          availability: "available",
          reason_codes: ["hero_specialty"]
        }}
      ]
    }};
    heroSkillPayload = buildHeroSkillPayload({{
      ...(heroSkillPayload || {{}}),
      hero_id: requestPayload.hero_id,
      offer_comparison: comparison
    }});
    payload = heroSkillPayload;
  }}
  const response = {{
    ok: responseOk,
    status: responseStatus,
    json: () => Promise.resolve(payload)
  }};
  if (deferResponse) {{
    return new Promise((resolve) => {{
      deferredResponses.push(() => resolve(response));
    }});
  }}
  return Promise.resolve(response);
}};
require({json.dumps(app_js_path)});
const helpers = window.__battleEstimatorGuiTest;
assert.strictEqual(autoRefreshIntervalCalls, 0);
async function flushPromises() {{
  for (let index = 0; index < 20; index += 1) {{
    await Promise.resolve();
  }}
}}
await flushPromises();
const markerSnapshot = {{
  map: {{ width: 4, height: 4, levels: 2 }},
  route_layers: [
    ["LWBB", "LLWB", "BWLX", "LLLL"],
    ["BBBB", "WWWW", "LLLL", "LWBZ"]
  ],
  selected_hero_id: "hero:0",
  heroes: [
    {{
      id: "hero:0",
      name: "Isra",
      position: {{ x: 1, y: 2, z: 0 }},
      owner_color_id: 0,
      owner_color_name: "red",
      team_id: 0,
      total_creatures: 12,
      ai_value: 500,
      army_summary: "12x Skeleton"
    }},
    {{
      id: "hero:1",
      name: "Fafner",
      position: {{ x: 2, y: 3, z: 1 }},
      owner_color_id: 2,
      owner_color_name: "tan",
      team_id: 1,
      total_creatures: 292,
      ai_value: 1200,
      army_summary: "1x Devil, 72x Master Gremlin"
    }},
    {{
      id: "hero:2",
      name: "Dormant",
      position: null,
      owner_color_id: 0,
      owner_color_name: "red",
      team_id: 0,
      total_creatures: 999,
      ai_value: 9000,
      army_summary: "999x Skeleton"
    }}
  ],
  neutral_targets: [
    {{
      id: "neutral:0",
      position: {{ x: 1, y: 3, z: 0 }},
      count: 8,
      creature_name: "Gnoll",
      h3m_subid: 1,
      estimator_creature_id: 1,
      removed: false
    }},
    {{
      id: "neutral:removed",
      position: {{ x: 2, y: 3, z: 0 }},
      count: 9,
      creature_name: "Pikeman",
      h3m_subid: 2,
      estimator_creature_id: 2,
      removed: true,
      removal_note: "removed in save"
    }},
    {{
      id: "neutral:1",
      position: {{ x: 3, y: 1, z: 1 }},
      count: 10,
      creature_name: "Archer",
      h3m_subid: 3,
      estimator_creature_id: null,
      removed: false
    }}
  ],
  town_targets: [
    {{
      id: "town:0",
      object_index: 0,
      position: {{ x: 0, y: 0, z: 0 }},
      anchor_position: {{ x: 1, y: 0, z: 0 }},
      object_id: 98,
      h3m_subid: 3,
      faction_subid: 3,
      initial_owner: 0,
      initial_owner_color_name: "red",
      custom_name: "Castle Keep",
      has_garrison: true
    }},
    {{
      id: "town:random",
      object_index: 5,
      position: {{ x: 0, y: 1, z: 0 }},
      anchor_position: {{ x: 0, y: 1, z: 0 }},
      object_id: 77,
      h3m_subid: 99,
      faction_subid: null,
      initial_owner: null,
      initial_owner_color_name: null,
      custom_name: null,
      has_garrison: false
    }},
    {{
      id: "town:1",
      object_index: 1,
      position: {{ x: 3, y: 0, z: 1 }},
      anchor_position: {{ x: 3, y: 0, z: 1 }},
      object_id: 98,
      h3m_subid: 5,
      faction_subid: 5,
      initial_owner: 2,
      initial_owner_color_name: "tan",
      custom_name: "",
      has_garrison: false
    }}
  ],
  portal_targets: [
    {{
      id: "portal:100",
      object_index: 100,
      position: {{ x: 2, y: 0, z: 0 }},
      anchor_position: {{ x: 2, y: 0, z: 0 }},
      object_id: 43,
      h3m_subid: 7,
      portal_type: "monolith_one_way",
      role: "entrance",
      channel_key: "monolith-one-way:7"
    }},
    {{
      id: "portal:101",
      object_index: 101,
      position: {{ x: 0, y: 2, z: 1 }},
      anchor_position: {{ x: 0, y: 2, z: 1 }},
      object_id: 44,
      h3m_subid: 7,
      portal_type: "monolith_one_way",
      role: "exit",
      channel_key: "monolith-one-way:7"
    }},
    {{
      id: "portal:102",
      object_index: 102,
      position: {{ x: 1, y: 2, z: 1 }},
      anchor_position: {{ x: 1, y: 2, z: 1 }},
      object_id: 44,
      h3m_subid: 7,
      portal_type: "monolith_one_way",
      role: "exit",
      channel_key: "monolith-one-way:7"
    }},
    {{
      id: "portal:110",
      object_index: 110,
      position: {{ x: 3, y: 3, z: 0 }},
      anchor_position: {{ x: 3, y: 3, z: 0 }},
      object_id: 45,
      h3m_subid: 9,
      portal_type: "monolith_two_way",
      role: "both",
      channel_key: "monolith-two-way:9"
    }},
    {{
      id: "portal:111",
      object_index: 111,
      position: {{ x: 2, y: 0, z: 1 }},
      anchor_position: {{ x: 2, y: 0, z: 1 }},
      object_id: 45,
      h3m_subid: 9,
      portal_type: "monolith_two_way",
      role: "both",
      channel_key: "monolith-two-way:9"
    }},
    {{
      id: "portal:120",
      object_index: 120,
      position: {{ x: 2, y: 1, z: 0 }},
      anchor_position: {{ x: 2, y: 1, z: 0 }},
      object_id: 103,
      h3m_subid: 0,
      portal_type: "subterranean_gate",
      role: "both",
      channel_key: "subterranean:120"
    }}
  ],
  portal_edges: [
    {{
      source_id: "portal:100",
      destination_id: "portal:101",
      source_object_index: 100,
      destination_object_index: 101,
      portal_type: "monolith_one_way",
      channel_key: "monolith-one-way:7",
      h3m_subid: 7
    }},
    {{
      source_id: "portal:100",
      destination_id: "portal:102",
      source_object_index: 100,
      destination_object_index: 102,
      portal_type: "monolith_one_way",
      channel_key: "monolith-one-way:7",
      h3m_subid: 7
    }},
    {{
      source_id: "portal:100",
      destination_id: "portal:999",
      source_object_index: 100,
      destination_object_index: 999,
      portal_type: "monolith_one_way",
      channel_key: "monolith-one-way:7",
      h3m_subid: 7
    }},
    {{
      source_id: "portal:110",
      destination_id: "portal:111",
      source_object_index: 110,
      destination_object_index: 111,
      portal_type: "monolith_two_way",
      channel_key: "monolith-two-way:9",
      h3m_subid: 9
    }},
    {{
      source_id: "portal:111",
      destination_id: "portal:110",
      source_object_index: 111,
      destination_object_index: 110,
      portal_type: "monolith_two_way",
      channel_key: "monolith-two-way:9",
      h3m_subid: 9
    }}
  ]
}};
const level0Markers = helpers.buildMarkerCache(markerSnapshot, 10, 0, false);
assert.deepStrictEqual(level0Markers.map((marker) => marker.id), [
  "town:0",
  "town:random",
  "portal:100",
  "portal:110",
  "portal:120",
  "hero:0",
  "neutral:0"
]);
const townMarker = level0Markers.find((marker) => marker.id === "town:0");
assert.strictEqual(townMarker.type, "town");
assert.strictEqual(townMarker.label, "Castle Keep");
assert.strictEqual(townMarker.initialOwnerColorName, "red");
const randomTown = level0Markers.find((marker) => marker.id === "town:random");
assert.strictEqual(randomTown.label, "Random town");
assert.ok(helpers.markerTooltipText(randomTown).includes("Random town subid: 99"));
assert.ok(!helpers.markerTooltipText(randomTown).includes("null"));
const portalMarker = level0Markers.find((marker) => marker.id === "portal:100");
assert.strictEqual(portalMarker.type, "portal");
assert.strictEqual(portalMarker.label, "One-way monolith entrance");
assert.deepStrictEqual(
  portalMarker.destinations.map((destination) => destination.id),
  ["portal:101", "portal:102"]
);
assert.ok(helpers.markerTooltipText(portalMarker).includes("One-way monolith entrance"));
assert.ok(helpers.markerTooltipText(portalMarker).includes("2,0,0"));
assert.ok(helpers.markerTooltipText(portalMarker).includes("0,2,1"));
assert.ok(helpers.markerTooltipText(portalMarker).includes("1,2,1"));
assert.ok(!helpers.markerTooltipText(portalMarker).includes("portal:999"));
const impassablePortal = level0Markers.find((marker) => marker.id === "portal:120");
assert.strictEqual(helpers.portalDestinationText(impassablePortal), "Destinations: none");
assert.strictEqual(helpers.portalTypeLabel("subterranean_gate"), "Subterranean gate");
const relationSnapshot = {{
  portal_targets: [
    {{
      id: "portal:source",
      position: {{ x: 0, y: 0, z: 0 }},
      portal_type: "monolith_one_way",
      role: "entrance",
      channel_key: "monolith-one-way:1"
    }},
    {{
      id: "portal:same",
      position: {{ x: 1, y: 0, z: 0 }},
      portal_type: "monolith_one_way",
      role: "exit",
      channel_key: "monolith-one-way:1"
    }},
    {{
      id: "portal:cross",
      position: {{ x: 0, y: 1, z: 1 }},
      portal_type: "monolith_one_way",
      role: "exit",
      channel_key: "monolith-one-way:1"
    }},
    {{
      id: "portal:exit-only",
      position: {{ x: 2, y: 0, z: 0 }},
      portal_type: "monolith_one_way",
      role: "exit",
      channel_key: "monolith-one-way:2"
    }},
    {{
      id: "portal:broken",
      position: {{ x: 3, y: 0, z: 0 }},
      portal_type: "monolith_one_way",
      role: "entrance",
      channel_key: "monolith-one-way:3"
    }}
  ],
  portal_edges: [
    {{ source_id: "portal:source", destination_id: "portal:same" }},
    {{ source_id: "portal:source", destination_id: "portal:cross" }},
    {{ source_id: "portal:source", destination_id: "portal:missing" }},
    {{ source_id: "portal:broken", destination_id: "portal:missing" }}
  ]
}};
const sourceRelation = helpers.portalRelationForSource(relationSnapshot, "portal:source");
assert.strictEqual(sourceRelation.source.id, "portal:source");
assert.deepStrictEqual(
  sourceRelation.destinations.map((destination) => destination.id),
  ["portal:same", "portal:cross"]
);
assert.deepStrictEqual(
  sourceRelation.sameLevelDestinations.map((destination) => destination.id),
  ["portal:same"]
);
assert.deepStrictEqual(
  sourceRelation.crossLevelDestinations.map((destination) => destination.id),
  ["portal:cross"]
);
assert.strictEqual(sourceRelation.destinationCount, 2);
assert.strictEqual(sourceRelation.outgoingEdgeCount, 3);
assert.strictEqual(sourceRelation.unresolvedDestinationCount, 1);
assert.strictEqual(sourceRelation.isMultiExit, true);
assert.strictEqual(sourceRelation.isNonDeterministic, true);
assert.strictEqual(sourceRelation.status, "partial_destinations");
const exitOnlyRelation = helpers.portalRelationForSource(relationSnapshot, "portal:exit-only");
assert.strictEqual(exitOnlyRelation.status, "no_known_destination");
assert.strictEqual(exitOnlyRelation.unresolvedDestinationCount, 0);
const brokenRelation = helpers.portalRelationForSource(relationSnapshot, "portal:broken");
assert.strictEqual(brokenRelation.status, "no_known_destination");
assert.strictEqual(brokenRelation.unresolvedDestinationCount, 1);
assert.strictEqual(helpers.portalRelationForSource(relationSnapshot, "neutral:0"), null);
assert.deepStrictEqual(helpers.routeRowsForLevel(markerSnapshot, 0), ["LWBB", "LLWB", "BWLX", "LLLL"]);
assert.deepStrictEqual(helpers.routeRowsForLevel(markerSnapshot, 1), ["BBBB", "WWWW", "LLLL", "LWBZ"]);
assert.deepStrictEqual(helpers.routeRowsForLevel(markerSnapshot, 99), ["BBBB", "WWWW", "LLLL", "LWBZ"]);
assert.strictEqual(helpers.routeStateForChar("L"), "land");
assert.strictEqual(helpers.routeStateForChar("W"), "water");
assert.strictEqual(helpers.routeStateForChar("B"), "blocked");
assert.strictEqual(helpers.routeStateForChar("X"), null);
assert.notStrictEqual(helpers.routeStyleForChar("L").fill, helpers.routeStyleForChar("W").fill);
assert.notStrictEqual(helpers.routeStyleForChar("W").fill, helpers.routeStyleForChar("B").fill);
assert.strictEqual(helpers.routeStyleForChar("X"), null);
const level0WithRemoved = helpers.buildMarkerCache(markerSnapshot, 10, 0, true);
assert.deepStrictEqual(
  level0WithRemoved.map((marker) => marker.id),
  ["town:0", "town:random", "portal:100", "portal:110", "portal:120", "hero:0", "neutral:0", "neutral:removed"]
);
assert.strictEqual(level0WithRemoved.find((marker) => marker.id === "neutral:removed").removed, true);
const level0HeroesOnly = helpers.buildMarkerCache(markerSnapshot, 10, 0, false, false, "heroes");
assert.deepStrictEqual(level0HeroesOnly.map((marker) => marker.id), [
  "town:0",
  "town:random",
  "portal:100",
  "portal:110",
  "portal:120",
  "hero:0"
]);
const level0MonstersOnly = helpers.buildMarkerCache(markerSnapshot, 10, 0, false, false, "monsters");
assert.deepStrictEqual(level0MonstersOnly.map((marker) => marker.id), [
  "town:0",
  "town:random",
  "portal:100",
  "portal:110",
  "portal:120",
  "neutral:0"
]);
const hiddenHeroSnapshot = {{
  ...markerSnapshot,
  show_hidden: false,
  heroes: [
    ...markerSnapshot.heroes,
    {{
      id: "hero:hidden",
      name: "Hidden",
      position: {{ x: 3, y: 2, z: 0 }},
      owner_color_id: 2,
      owner_color_name: "tan",
      team_id: 1,
      hidden: true,
      total_creatures: 42,
      ai_value: 100,
      army_summary: "42x Skeleton"
    }}
  ]
}};
assert.ok(!helpers.buildMarkerCache(hiddenHeroSnapshot, 10, 0, false).some((marker) => marker.id === "hero:hidden"));
assert.ok(!helpers.buildMarkerCache({{ ...hiddenHeroSnapshot, show_hidden: true }}, 10, 0, false, false).some((marker) => marker.id === "hero:hidden"));
const level0WithHiddenHero = helpers.buildMarkerCache({{ ...hiddenHeroSnapshot, show_hidden: true }}, 10, 0, false);
assert.strictEqual(level0WithHiddenHero.find((marker) => marker.id === "hero:hidden").hidden, true);
assert.strictEqual(helpers.buildMarkerCache(hiddenHeroSnapshot, 10, 0, false, true).find((marker) => marker.id === "hero:hidden").hidden, true);
assert.ok(!helpers.buildMarkerCache(hiddenHeroSnapshot, 10, 0, false, true, "monsters").some((marker) => marker.id === "hero:hidden"));
const level1Markers = helpers.buildMarkerCache(markerSnapshot, 10, 1, false);
assert.deepStrictEqual(level1Markers.map((marker) => marker.id), [
  "town:1",
  "portal:101",
  "portal:102",
  "portal:111",
  "hero:1",
  "neutral:1"
]);
assert.strictEqual(level1Markers.find((marker) => marker.id === "town:1").label, "Dungeon town");
const overlapSnapshot = {{
  map: {{ width: 4, height: 4, levels: 1 }},
  selected_hero_id: "hero:0",
  heroes: [markerSnapshot.heroes[0]],
  neutral_targets: [],
  town_targets: [
    {{
      id: "town:overlap",
      object_index: 7,
      position: {{ x: 1, y: 2, z: 0 }},
      object_id: 98,
      h3m_subid: 3,
      faction_subid: 3,
      initial_owner_color_name: "red"
    }}
  ],
  portal_targets: [
    {{
      id: "portal:overlap",
      object_index: 12,
      position: {{ x: 1, y: 2, z: 0 }},
      object_id: 45,
      h3m_subid: 4,
      portal_type: "monolith_two_way",
      role: "both",
      channel_key: "monolith-two-way:4"
    }}
  ],
  portal_edges: []
}};
const overlapMarkers = helpers.buildMarkerCache(overlapSnapshot, 10, 0, false);
assert.deepStrictEqual(overlapMarkers.map((marker) => marker.id), [
  "town:overlap",
  "portal:overlap",
  "hero:0"
]);
assert.strictEqual(
  helpers.hitTestMarker(overlapMarkers, {{ x: 15, y: 25 }}, {{ zoom: 1, pan: {{ x: 0, y: 0 }} }}).id,
  "hero:0"
);
const portalTownOverlapSnapshot = {{
  map: {{ width: 4, height: 4, levels: 1 }},
  selected_hero_id: null,
  heroes: [],
  neutral_targets: [],
  town_targets: overlapSnapshot.town_targets,
  portal_targets: overlapSnapshot.portal_targets,
  portal_edges: []
}};
const portalTownOverlapMarkers = helpers.buildMarkerCache(portalTownOverlapSnapshot, 10, 0, false);
assert.strictEqual(
  helpers.hitTestMarker(portalTownOverlapMarkers, {{ x: 15, y: 25 }}, {{ zoom: 1, pan: {{ x: 0, y: 0 }} }}).id,
  "portal:overlap"
);
assert.deepStrictEqual(
  helpers.rankedMapHeroes(markerSnapshot).map((hero) => hero.id),
  ["hero:1", "hero:0"]
);
assert.strictEqual(helpers.defaultLevelForSnapshot(markerSnapshot, "hero:1"), 1);
assert.strictEqual(helpers.resolveSelectedHeroId(markerSnapshot, "hero:1"), "hero:1");
assert.strictEqual(helpers.resolveSelectedHeroId(markerSnapshot, "hero:missing"), "hero:0");
assert.strictEqual(
  helpers.sameMapGeometry(
    {{ map: {{ width: 4, height: 4, levels: 2 }} }},
    markerSnapshot
  ),
  true
);
assert.strictEqual(
  helpers.sameMapGeometry(
    {{ map: {{ width: 5, height: 4, levels: 2 }} }},
    markerSnapshot
  ),
  false
);
assert.deepStrictEqual(
  helpers.nextViewStateForSnapshot(markerSnapshot, {{
    snapshot: {{ map: {{ width: 4, height: 4, levels: 2 }} }},
    selectedHeroId: "hero:1",
    level: 0,
    zoom: 1.7,
    minZoom: 0.35,
    maxZoom: 5,
    pan: {{ x: 22, y: -9 }}
  }}),
  {{
    selectedHeroId: "hero:1",
    preserveView: true,
    level: 1,
    zoom: 1.7,
    pan: {{ x: 22, y: -9 }}
  }}
);
assert.deepStrictEqual(
  helpers.nextViewStateForSnapshot(markerSnapshot, {{
    snapshot: {{ map: {{ width: 4, height: 4, levels: 2 }} }},
    selectedHeroId: null,
    level: 1,
    zoom: 1.7,
    minZoom: 0.35,
    maxZoom: 5,
    pan: {{ x: 22, y: -9 }},
    preserveView: false
  }}),
  {{
    selectedHeroId: "hero:0",
    preserveView: false,
    level: 0,
    zoom: 1.7,
    pan: {{ x: 22, y: -9 }}
  }}
);
const tooltip = helpers.markerTooltipText(level1Markers.find((marker) => marker.id === "hero:1"));
assert.ok(tooltip.includes("Fafner"));
assert.ok(tooltip.includes("Tan team 1 enemy"));
assert.ok(tooltip.includes("2,3,1"));
assert.ok(!tooltip.includes("<"));
const townTooltip = helpers.markerTooltipText(townMarker);
assert.ok(townTooltip.includes("Castle Keep"));
assert.ok(townTooltip.includes("0,0,0"));
assert.ok(townTooltip.includes("Faction: Inferno (subid 3/3)"));
assert.ok(townTooltip.includes("Initial owner: Red"));
assert.strictEqual(helpers.formatWinPct(null), "not available");
assert.strictEqual(helpers.formatWinPct(0), "0.0%");
assert.strictEqual(helpers.verdictForWinPct(null), "Unsupported target");
assert.deepStrictEqual(
  helpers.simulationClickDecision(null, "hero:256"),
  {{ simulate: false, message: "No target selected." }}
);
assert.deepStrictEqual(
  helpers.simulationClickDecision({{ type: "hero", id: "hero:256" }}, "hero:256"),
  {{ simulate: false, message: "Selected hero is not a simulation target." }}
);
assert.deepStrictEqual(
  helpers.simulationClickDecision({{ type: "hero", id: "hero:512", relation: "ally" }}, "hero:256"),
  {{ simulate: false, message: "Allied hero is not a simulation target." }}
);
assert.deepStrictEqual(
  helpers.simulationClickDecision({{ type: "town", id: "town:0" }}, null),
  {{ simulate: false, message: "Town target is not a battle simulation target." }}
);
assert.deepStrictEqual(
  helpers.simulationClickDecision({{ type: "town", id: "town:0" }}, "hero:256"),
  {{ simulate: false, message: "Town target is not a battle simulation target." }}
);
assert.deepStrictEqual(
  helpers.simulationClickDecision({{ type: "portal", id: "portal:100" }}, "hero:256"),
  {{ simulate: false, message: "Portal target is not a battle simulation target." }}
);
assert.deepStrictEqual(
  helpers.simulationClickDecision({{ type: "neutral", id: "neutral:0" }}, "hero:256"),
  {{ simulate: true, message: "" }}
);
assert.deepStrictEqual(
  helpers.simulationClickDecision({{ type: "neutral", id: "neutral:0", hidden: true }}, "hero:256"),
  {{ simulate: false, message: "Hidden target is ignored." }}
);
assert.deepStrictEqual(
  helpers.simulationClickDecision({{ type: "hero", id: "hero:512", hidden: true }}, "hero:256"),
  {{ simulate: false, message: "Hidden target is ignored." }}
);
assert.strictEqual(
  helpers.isFreshEstimatePayload({{ hero_id: "hero:256" }}, 7, 7, "hero:256"),
  true
);
assert.strictEqual(
  helpers.isFreshEstimatePayload({{ hero_id: "hero:256" }}, 6, 7, "hero:256"),
  false
);
assert.strictEqual(
  helpers.isFreshEstimatePayload({{ hero_id: "hero:256" }}, 7, 7, "hero:512"),
  false
);
assert.strictEqual(
  helpers.estimateTargetLabel(
    {{ target_type: "hero", target: {{ name: "Marius" }} }},
    "hero:512"
  ),
  "Marius (hero:512)"
);
assert.strictEqual(helpers.scanClassForWinPct(null), "unsupported");
assert.strictEqual(helpers.scanClassForWinPct(0), "danger");
assert.strictEqual(helpers.scanClassForWinPct(30), "risky");
assert.strictEqual(helpers.scanClassForWinPct(70), "likely");
assert.strictEqual(helpers.scanClassForWinPct(90), "strong");
const sorted = helpers.sortedScanResults([
  {{ target_id: "neutral:2", distance: 4 }},
  {{ target_id: "neutral:1", distance: 1 }},
  {{ target_id: "hero:3", distance: 1 }}
]);
assert.deepStrictEqual(sorted.map((item) => item.target_id), [
  "hero:3",
  "neutral:1",
  "neutral:2"
]);
const easiestSorted = helpers.sortedScanResults([
  {{ target_id: "neutral:slow", distance: 1, win_pct: 20 }},
  {{ target_id: "neutral:tie-b", distance: 3, win_pct: 75 }},
  {{ target_id: "neutral:unknown", distance: 2, win_pct: null }},
  {{ target_id: "neutral:tie-a", distance: 2, win_pct: 75 }},
  {{ target_id: "neutral:best", distance: 5, win_pct: 95 }}
], "easiest");
assert.deepStrictEqual(easiestSorted.map((item) => item.target_id), [
  "neutral:best",
  "neutral:tie-a",
  "neutral:tie-b",
  "neutral:slow",
  "neutral:unknown"
]);
const lookup = helpers.scanResultLookup(sorted);
assert.strictEqual(lookup.get("neutral:2").distance, 4);
const scanRequest = {{ requestId: 5, heroId: "hero:256", radius: 10, targetType: "all" }};
assert.strictEqual(
  helpers.isFreshScanPayload(
    {{ hero_id: "hero:256", radius: 10, target_type: "all" }},
    scanRequest,
    5
  ),
  true
);
assert.strictEqual(
  helpers.isFreshScanPayload(
    {{ hero_id: "hero:256", radius: 11, target_type: "all" }},
    scanRequest,
    5
  ),
  false
);
assert.strictEqual(
  helpers.isFreshScanPayload(
    {{ hero_id: "hero:512", radius: 10, target_type: "all" }},
    scanRequest,
    5
  ),
  false
);
const fetchCallsBeforeRender = fetchCalls;
assert.strictEqual(elements["hero-skills-button"].disabled, true);
helpers.renderSnapshot(markerSnapshot, {{ preserveView: false }});
const overlayFillsAfterRender = drawOperations.filter((operation) => (
  operation.op === "fillRect" && routeFillStyles.has(operation.fillStyle)
));
assert.ok(overlayFillsAfterRender.length >= 3);
const townFillsAfterRender = drawOperations.filter((operation) => (
  operation.op === "fillRect" && townFillStyles.has(operation.fillStyle)
));
assert.ok(townFillsAfterRender.length >= 1);
const portalFillsAfterRender = drawOperations.filter((operation) => (
  operation.op === "fillRect" && portalFillStyles.has(operation.fillStyle)
));
assert.ok(portalFillsAfterRender.length >= 1);
const renderedView = helpers.currentMapViewForTest();
assert.strictEqual(elements["path-mode-toggle"].disabled, false);
assert.strictEqual(elements["path-mode-toggle"].checked, false);
assert.strictEqual(renderedView.pathMode, false);
assert.strictEqual(elements["path-state"].textContent, "No path requested.");
const symbolSnapshot = {{
  map: {{ width: 8, height: 2, levels: 1 }},
  route_layers: [["LLLLLLLL", "LLLLLLLL"]],
  selected_hero_id: null,
  heroes: [],
  neutral_targets: [],
  town_targets: [],
  portal_targets: [
    {{
      id: "portal:entrance",
      object_index: 1,
      position: {{ x: 0, y: 0, z: 0 }},
      portal_type: "monolith_one_way",
      role: "entrance",
      channel_key: "monolith-one-way:1"
    }},
    {{
      id: "portal:exit",
      object_index: 2,
      position: {{ x: 2, y: 0, z: 0 }},
      portal_type: "monolith_one_way",
      role: "exit",
      channel_key: "monolith-one-way:1"
    }},
    {{
      id: "portal:two-way",
      object_index: 3,
      position: {{ x: 4, y: 0, z: 0 }},
      portal_type: "monolith_two_way",
      role: "both",
      channel_key: "monolith-two-way:2"
    }},
    {{
      id: "portal:stairs",
      object_index: 4,
      position: {{ x: 6, y: 0, z: 0 }},
      portal_type: "subterranean_gate",
      role: "both",
      channel_key: "subterranean:4"
    }}
  ],
  portal_edges: []
}};
drawOperations.length = 0;
helpers.renderSnapshot(symbolSnapshot, {{ preserveView: false }});
const symbolView = helpers.currentMapViewForTest();
const symbolMarkers = new Map(symbolView.markers.map((marker) => [marker.id, marker]));
assert.strictEqual(helpers.portalMarkerSymbolKind(symbolMarkers.get("portal:entrance")), "outbound");
assert.strictEqual(helpers.portalMarkerSymbolKind(symbolMarkers.get("portal:exit")), "exit_only");
assert.strictEqual(helpers.portalMarkerSymbolKind(symbolMarkers.get("portal:two-way")), "bidirectional");
assert.strictEqual(helpers.portalMarkerSymbolKind(symbolMarkers.get("portal:stairs")), "stairs");
assert.strictEqual(helpers.portalMarkerSymbolKind({{ type: "portal", portalType: "unknown" }}), "unknown");
const entrancePoint = helpers.worldToScreen(symbolMarkers.get("portal:entrance").world, symbolView);
const exitPoint = helpers.worldToScreen(symbolMarkers.get("portal:exit").world, symbolView);
const twoWayPoint = helpers.worldToScreen(symbolMarkers.get("portal:two-way").world, symbolView);
const stairsPoint = helpers.worldToScreen(symbolMarkers.get("portal:stairs").world, symbolView);
const entranceOps = symbolLineOpsNear(entrancePoint);
const exitSegments = adjacentLineSegments(symbolLineOpsNear(exitPoint));
const twoWayOps = symbolLineOpsNear(twoWayPoint);
const stairsSegments = adjacentLineSegments(symbolLineOpsNear(stairsPoint));
assert.ok(entranceOps.some((operation) => (
  operation.op === "lineTo"
  && operation.x > entrancePoint.x + 7
  && Math.abs(operation.y - entrancePoint.y) <= 1
)), "one-way entrance should draw an outbound arrow point");
assert.ok(!entranceOps.some((operation) => (
  operation.op === "lineTo"
  && operation.x < entrancePoint.x - 7
  && Math.abs(operation.y - entrancePoint.y) <= 1
)), "one-way entrance should not draw a left-facing arrow point");
assert.ok(hasVerticalSegment(exitSegments, 10), "one-way exit should draw an exit-only barrier");
assert.ok(!hasHorizontalSegment(exitSegments, 14), "one-way exit should not reuse the entrance shaft");
assert.ok(twoWayOps.some((operation) => (
  operation.op === "lineTo"
  && operation.x > twoWayPoint.x + 7
  && Math.abs(operation.y - twoWayPoint.y) <= 1
)), "two-way monolith should draw a right arrow point");
assert.ok(twoWayOps.some((operation) => (
  operation.op === "lineTo"
  && operation.x < twoWayPoint.x - 7
  && Math.abs(operation.y - twoWayPoint.y) <= 1
)), "two-way monolith should draw a left arrow point");
assert.ok(horizontalSegmentCount(stairsSegments, 5) >= 3, "subterranean gate should draw stair steps");
assert.strictEqual(
  drawOperations.filter((operation) => (
    operation.op === "fillRect"
    && operation.fillStyle === "#f8fafc"
    && operation.width <= 20
    && operation.height >= 20
  )).length,
  0,
  "portal symbols should replace the old shared white stripe"
);
helpers.renderSnapshot(markerSnapshot, {{ preserveView: false }});
function targetFilterButtons() {{
  return elements["target-filter-control"].children;
}}
function heroRows() {{
  return elements["hero-list"].children
    .filter((child) => child.dataset && child.dataset.heroId);
}}
function scanRequestsSince(startIndex) {{
  return fetchRequests
    .slice(startIndex)
    .filter((request) => request.path === "/api/scan-radius");
}}
function pathRequestsSince(startIndex) {{
  return fetchRequests
    .slice(startIndex)
    .filter((request) => request.path === "/api/path-route");
}}
function scanSortButtons() {{
  return elements["scan-sort-control"].children;
}}
function scanResultRows() {{
  return elements["scan-state"].children
    .filter((child) => child.dataset && child.dataset.targetId);
}}
function scanResultIds() {{
  return scanResultRows().map((child) => child.dataset.targetId);
}}
function scanStateTextIncludes(text) {{
  return elements["scan-state"].children.some((child) => child.textContent.includes(text));
}}
function treeText(node) {{
  if (!node) {{
    return "";
  }}
  return [node.textContent || "", ...node.children.map((child) => treeText(child))].join(" ");
}}
function nodesWithClass(node, className) {{
  if (!node) {{
    return [];
  }}
  const matches = String(node.className || "").split(/\\s+/).includes(className)
    ? [node]
    : [];
  return matches.concat(node.children.flatMap((child) => nodesWithClass(child, className)));
}}
function pathSegmentButtons() {{
  return nodesWithClass(elements["path-state"], "path-segment");
}}
function skillSlotRows() {{
  return elements["hero-skill-slots"].children
    .filter((child) => child.dataset && child.dataset.slotIndex);
}}
function compareRows() {{
  return elements["hero-skill-compare-controls"].children
    .filter((child) => child.dataset && child.dataset.offerIndex);
}}
function heroSkillRequestsSince(startIndex, path) {{
  return fetchRequests
    .slice(startIndex)
    .filter((request) => request.path === path);
}}
function mapTileScreenPoint(x, y, view) {{
  return helpers.worldToScreen({{ x: (x + 0.5) * 28, y: (y + 0.5) * 28 }}, view);
}}
function symbolLineOpsNear(point) {{
  return drawOperations.filter((operation) => (
    (operation.op === "moveTo" || operation.op === "lineTo")
    && operation.strokeStyle === "#f8fafc"
    && Math.abs(operation.x - point.x) <= 28
    && Math.abs(operation.y - point.y) <= 28
  ));
}}
function adjacentLineSegments(operations) {{
  const segments = [];
  for (let index = 0; index < operations.length - 1; index += 1) {{
    if (operations[index].op === "moveTo" && operations[index + 1].op === "lineTo") {{
      segments.push({{ from: operations[index], to: operations[index + 1] }});
    }}
  }}
  return segments;
}}
function hasHorizontalSegment(segments, minWidth) {{
  return segments.some((segment) => (
    Math.abs(segment.from.y - segment.to.y) <= 0.5
    && Math.abs(segment.from.x - segment.to.x) >= minWidth
  ));
}}
function horizontalSegmentCount(segments, minWidth) {{
  return segments.filter((segment) => (
    Math.abs(segment.from.y - segment.to.y) <= 0.5
    && Math.abs(segment.from.x - segment.to.x) >= minWidth
  )).length;
}}
function hasVerticalSegment(segments, minHeight) {{
  return segments.some((segment) => (
    Math.abs(segment.from.x - segment.to.x) <= 0.5
    && Math.abs(segment.from.y - segment.to.y) >= minHeight
  ));
}}
function portalRelationStrokeOps() {{
  return drawOperations.filter((operation) => (
    operation.op === "stroke" && operation.strokeStyle === "#2563eb"
  ));
}}
function portalRelationBadgeTexts() {{
  return drawOperations.filter((operation) => (
    operation.op === "fillText" && operation.fillStyle === "#1e3a8a"
  ));
}}
function dispatchCanvasPointer(type, point, pointerId = 700) {{
  elements["battle-map"].dispatch(type, {{
    button: 0,
    pointerId,
    clientX: point.x,
    clientY: point.y
  }});
}}
const relationOverlaySnapshot = {{
  map: {{ width: 8, height: 4, levels: 2 }},
  route_layers: [
    ["LLLLLLLL", "LLLLLLLL", "LLLLLLLL", "LLLLLLLL"],
    ["LLLLLLLL", "LLLLLLLL", "LLLLLLLL", "LLLLLLLL"]
  ],
  selected_hero_id: null,
  heroes: [],
  neutral_targets: [],
  town_targets: [],
  portal_targets: [
    {{
      id: "portal:source-a",
      object_index: 10,
      position: {{ x: 1, y: 1, z: 0 }},
      portal_type: "monolith_one_way",
      role: "entrance",
      channel_key: "monolith-one-way:10"
    }},
    {{
      id: "portal:same-a",
      object_index: 11,
      position: {{ x: 3, y: 1, z: 0 }},
      portal_type: "monolith_one_way",
      role: "exit",
      channel_key: "monolith-one-way:10"
    }},
    {{
      id: "portal:cross-a",
      object_index: 12,
      position: {{ x: 5, y: 1, z: 1 }},
      portal_type: "monolith_one_way",
      role: "exit",
      channel_key: "monolith-one-way:10"
    }},
    {{
      id: "portal:source-b",
      object_index: 20,
      position: {{ x: 1, y: 2, z: 0 }},
      portal_type: "monolith_two_way",
      role: "both",
      channel_key: "monolith-two-way:20"
    }},
    {{
      id: "portal:same-b",
      object_index: 21,
      position: {{ x: 6, y: 2, z: 0 }},
      portal_type: "monolith_two_way",
      role: "both",
      channel_key: "monolith-two-way:20"
    }}
  ],
  portal_edges: [
    {{ source_id: "portal:source-a", destination_id: "portal:same-a" }},
    {{ source_id: "portal:source-a", destination_id: "portal:cross-a" }},
    {{ source_id: "portal:source-b", destination_id: "portal:same-b" }}
  ]
}};
helpers.renderSnapshot(relationOverlaySnapshot, {{ preserveView: false }});
assert.strictEqual(elements["portal-links-toggle"].disabled, false);
assert.strictEqual(elements["portal-links-toggle"].checked, true);
const relationView = helpers.currentMapViewForTest();
const relationSourceA = relationView.markers.find((marker) => marker.id === "portal:source-a");
const relationSourceB = relationView.markers.find((marker) => marker.id === "portal:source-b");
const relationSourceAPoint = helpers.worldToScreen(relationSourceA.world, relationView);
const relationSourceBPoint = helpers.worldToScreen(relationSourceB.world, relationView);
const beforePortalHoverView = helpers.currentMapViewForTest();
drawOperations.length = 0;
dispatchCanvasPointer("pointermove", relationSourceAPoint, 701);
assert.strictEqual(helpers.currentMapViewForTest().activeMarkerId, beforePortalHoverView.activeMarkerId);
let relationState = helpers.currentPortalRelationStateForTest();
assert.strictEqual(relationState.hoveredSourceId, "portal:source-a");
assert.strictEqual(relationState.pinnedSourceId, null);
assert.strictEqual(relationState.activeSourceId, "portal:source-a");
assert.ok(portalRelationStrokeOps().some((operation) => (
  operation.lineDash && operation.lineDash.length === 2
)), "multi-exit relation should draw dashed same-level links");
assert.ok(portalRelationBadgeTexts().some((operation) => (
  operation.text.includes("L1") && operation.text.includes("?")
)), "cross-level relation should draw a target-level badge");
assert.deepStrictEqual(
  helpers.portalCrossLevelSummaries(relationState.relation),
  [{{ level: 1, count: 1, label: "L1" }}]
);
drawOperations.length = 0;
dispatchCanvasPointer("pointerdown", relationSourceAPoint, 702);
dispatchCanvasPointer("pointerup", relationSourceAPoint, 702);
relationState = helpers.currentPortalRelationStateForTest();
assert.strictEqual(relationState.pinnedSourceId, "portal:source-a");
assert.ok(portalRelationStrokeOps().some((operation) => (
  operation.lineDash && operation.lineDash.length === 2
)));
drawOperations.length = 0;
elements["portal-links-toggle"].checked = false;
elements["portal-links-toggle"].dispatch("change", {{}});
assert.strictEqual(portalRelationStrokeOps().length, 0);
assert.strictEqual(portalRelationBadgeTexts().length, 0);
relationState = helpers.currentPortalRelationStateForTest();
assert.strictEqual(relationState.pinnedSourceId, "portal:source-a");
assert.strictEqual(relationState.activeSourceId, "portal:source-a");
drawOperations.length = 0;
elements["portal-links-toggle"].checked = true;
elements["portal-links-toggle"].dispatch("change", {{}});
assert.ok(portalRelationStrokeOps().some((operation) => (
  operation.lineDash && operation.lineDash.length === 2
)));
assert.ok(portalRelationBadgeTexts().some((operation) => operation.text.includes("L1")));
drawOperations.length = 0;
dispatchCanvasPointer("pointermove", relationSourceBPoint, 703);
relationState = helpers.currentPortalRelationStateForTest();
assert.strictEqual(relationState.hoveredSourceId, "portal:source-b");
assert.strictEqual(relationState.pinnedSourceId, "portal:source-a");
assert.strictEqual(relationState.activeSourceId, "portal:source-b");
assert.ok(portalRelationStrokeOps().length > 0);
assert.ok(!portalRelationStrokeOps().some((operation) => (
  operation.lineDash && operation.lineDash.length > 0
)), "single-exit hovered relation should not inherit pinned dashed style");
assert.strictEqual(portalRelationBadgeTexts().length, 0);
drawOperations.length = 0;
elements["battle-map"].dispatch("pointerleave", {{}});
relationState = helpers.currentPortalRelationStateForTest();
assert.strictEqual(relationState.hoveredSourceId, null);
assert.strictEqual(relationState.pinnedSourceId, "portal:source-a");
assert.strictEqual(relationState.activeSourceId, "portal:source-a");
assert.ok(portalRelationStrokeOps().some((operation) => (
  operation.lineDash && operation.lineDash.length === 2
)));
assert.ok(portalRelationBadgeTexts().some((operation) => operation.text.includes("L1")));
helpers.renderSnapshot(markerSnapshot, {{ preserveView: false }});
const noSelectedSkillsSnapshot = {{
  ...markerSnapshot,
  selected_hero_id: null,
  heroes: [
    {{ ...markerSnapshot.heroes[1], id: "hero:new" }}
  ]
}};
helpers.renderSnapshot(noSelectedSkillsSnapshot, {{ preserveView: false }});
assert.strictEqual(elements["hero-skills-button"].disabled, true);
await Promise.all(heroRows().find((row) => row.dataset.heroId === "hero:new").dispatch("click", {{}}));
await flushPromises();
assert.strictEqual(elements["hero-skills-button"].disabled, false);
helpers.renderSnapshot(markerSnapshot, {{ preserveView: false }});
assert.strictEqual(elements["hero-skills-button"].disabled, false);
const heroSkillsOpenStart = fetchRequests.length;
elements["hero-skills-button"].dispatch("click", {{}});
await flushPromises();
let heroSkillLoadRequests = heroSkillRequestsSince(heroSkillsOpenStart, "/api/hero-skills");
assert.strictEqual(heroSkillLoadRequests.length, 1);
assert.deepStrictEqual(JSON.parse(heroSkillLoadRequests[0].options.body), {{ hero_id: "hero:0" }});
assert.strictEqual(elements["hero-skills-dialog"].hidden, false);
assert.ok(treeText(elements["hero-skills-meta"]).includes("Isra"));
assert.ok(treeText(elements["hero-skills-meta"]).includes("starting"));
assert.strictEqual(skillSlotRows().length, 8);
assert.strictEqual(skillSlotRows()[0].children[1].value, "necromancy");
assert.strictEqual(skillSlotRows()[0].children[2].value, "advanced");
assert.ok(treeText(elements["hero-skill-recommendations"]).includes("Necromancy"));
assert.ok(treeText(elements["hero-skill-avoid"]).includes("Scouting"));
assert.strictEqual(elements["hero-skills-save-button"].disabled, true);
assert.strictEqual(elements["hero-skills-reset-button"].disabled, true);
let slotRows = skillSlotRows();
slotRows[1].children[1].value = "earthMagic";
slotRows[1].children[1].dispatch("change", {{}});
assert.ok(elements["hero-skills-status"].textContent.includes("Unsaved edits"));
assert.strictEqual(elements["hero-skills-save-button"].disabled, false);
slotRows = skillSlotRows();
slotRows[2].children[1].value = "earthMagic";
slotRows[2].children[1].dispatch("change", {{}});
assert.strictEqual(elements["hero-skills-save-button"].disabled, true);
assert.ok(elements["hero-skills-status"].textContent.includes("Duplicate"));
slotRows = skillSlotRows();
slotRows[2].children[1].value = "logistics";
slotRows[2].children[1].dispatch("change", {{}});
assert.strictEqual(elements["hero-skills-save-button"].disabled, false);
const heroSkillsSaveStart = fetchRequests.length;
elements["hero-skills-save-button"].dispatch("click", {{}});
assert.ok(skillSlotRows().every((row) => row.children[1].disabled && row.children[2].disabled));
await flushPromises();
const heroSkillSaveRequests = heroSkillRequestsSince(heroSkillsSaveStart, "/api/hero-skills/save");
assert.strictEqual(heroSkillSaveRequests.length, 1);
assert.deepStrictEqual(JSON.parse(heroSkillSaveRequests[0].options.body), {{
  hero_id: "hero:0",
  skills: [
    {{ skill: "necromancy", level: "advanced" }},
    {{ skill: "earthMagic", level: "basic" }},
    {{ skill: "logistics", level: "basic" }}
  ]
}});
assert.ok(elements["hero-skills-status"].textContent.includes("Saved"));
assert.ok(treeText(elements["hero-skills-meta"]).includes("manual"));
assert.ok(treeText(elements["hero-skill-recommendations"]).includes("Logistics"));
assert.strictEqual(elements["hero-skills-reset-button"].disabled, false);
const heroSkillsResetStart = fetchRequests.length;
elements["hero-skills-reset-button"].dispatch("click", {{}});
assert.ok(skillSlotRows().every((row) => row.children[1].disabled && row.children[2].disabled));
await flushPromises();
const heroSkillResetRequests = heroSkillRequestsSince(heroSkillsResetStart, "/api/hero-skills/reset");
assert.strictEqual(heroSkillResetRequests.length, 1);
assert.deepStrictEqual(JSON.parse(heroSkillResetRequests[0].options.body), {{ hero_id: "hero:0" }});
assert.ok(treeText(elements["hero-skills-meta"]).includes("starting"));
assert.strictEqual(skillSlotRows()[0].children[1].value, "necromancy");
let offerRows = compareRows();
offerRows[0].children[1].value = "earthMagic";
offerRows[0].children[1].dispatch("change", {{}});
offerRows = compareRows();
offerRows[1].children[1].value = "earthMagic";
offerRows[1].children[1].dispatch("change", {{}});
assert.strictEqual(elements["hero-skills-compare-button"].disabled, true);
assert.strictEqual(helpers.heroSkillOfferValidationMessage(), "Choose two different offer skills.");
offerRows = compareRows();
offerRows[1].children[1].value = "necromancy";
offerRows[1].children[1].dispatch("change", {{}});
offerRows = compareRows();
offerRows[1].children[2].value = "expert";
offerRows[1].children[2].dispatch("change", {{}});
assert.strictEqual(elements["hero-skills-compare-button"].disabled, false);
const heroSkillsCompareStart = fetchRequests.length;
elements["hero-skills-compare-button"].dispatch("click", {{}});
assert.ok(compareRows().every((row) => row.children[1].disabled && row.children[2].disabled));
await flushPromises();
const heroSkillCompareRequests = heroSkillRequestsSince(heroSkillsCompareStart, "/api/hero-skills/compare");
assert.strictEqual(heroSkillCompareRequests.length, 1);
assert.deepStrictEqual(JSON.parse(heroSkillCompareRequests[0].options.body), {{
  hero_id: "hero:0",
  offers: [
    {{ skill: "earthMagic", level: "basic" }},
    {{ skill: "necromancy", level: "expert" }}
  ]
}});
assert.ok(treeText(elements["hero-skill-compare-result"]).includes("Winner: necromancy:expert"));
elements["hero-skills-close-button"].dispatch("click", {{}});
assert.strictEqual(elements["hero-skills-dialog"].hidden, true);
deferNextHeroSkillsResponse = true;
const staleHeroSkillsStart = fetchRequests.length;
elements["hero-skills-button"].dispatch("click", {{}});
assert.strictEqual(heroSkillRequestsSince(staleHeroSkillsStart, "/api/hero-skills").length, 1);
assert.strictEqual(pendingHeroSkillsResponses.length, 1);
elements["hero-skills-close-button"].dispatch("click", {{}});
pendingHeroSkillsResponses.shift()();
await flushPromises();
assert.strictEqual(elements["hero-skills-dialog"].hidden, true);
nextHeroSkillsError = {{ status: 400, error: "unknown standard hero" }};
elements["hero-skills-button"].dispatch("click", {{}});
await flushPromises();
assert.strictEqual(elements["hero-skills-dialog"].hidden, false);
assert.ok(elements["hero-skills-status"].textContent.includes("unknown standard hero"));
elements["hero-skills-close-button"].dispatch("click", {{}});
assert.deepStrictEqual(
  targetFilterButtons().map((button) => button.textContent),
  ["Both", "Heroes", "Monsters"]
);
assert.deepStrictEqual(
  scanSortButtons().map((button) => button.textContent),
  ["Distance", "Easiest"]
);
assert.strictEqual(targetFilterButtons()[0].className, "active");
assert.strictEqual(scanSortButtons()[0].className, "active");
let heroSelectBeforeAnyScanStart = fetchRequests.length;
await Promise.all(heroRows().find((row) => row.dataset.heroId === "hero:1").dispatch("click", {{}}));
await flushPromises();
assert.strictEqual(scanRequestsSince(heroSelectBeforeAnyScanStart).length, 0);
await Promise.all(heroRows().find((row) => row.dataset.heroId === "hero:0").dispatch("click", {{}}));
await flushPromises();
assert.strictEqual(scanRequestsSince(heroSelectBeforeAnyScanStart).length, 0);
helpers.renderSnapshot(markerSnapshot, {{ preserveView: false }});
const heroScanRingStart = drawOperations.length;
const ringHeroSnapshot = {{
  ...markerSnapshot,
  heroes: markerSnapshot.heroes.map((hero) => (
    hero.id === "hero:1" ? {{ ...hero, position: {{ x: 3, y: 2, z: 0 }} }} : hero
  ))
}};
helpers.renderSnapshot(ringHeroSnapshot, {{ preserveView: false }});
targetFilterButtons()[1].dispatch("click", {{}});
elements["scan-radius"].value = "3";
nextScanResults = [
  {{
    target_id: "hero:1",
    target_type: "hero",
    distance: 1,
    win_pct: 95,
    enemy_ai_value: 100,
    note: "hero ring",
    target: {{ name: "Fafner" }}
  }}
];
elements["scan-button"].dispatch("click", {{}});
await flushPromises();
assert.deepStrictEqual(scanResultIds(), ["hero:1"]);
const heroScanRingOps = drawOperations.slice(heroScanRingStart);
assert.ok(heroScanRingOps.some((operation) => (
  operation.op === "fillRect" && operation.fillStyle === "#b98543"
)), "scanned hero should keep tan owner fill");
assert.ok(!heroScanRingOps.some((operation) => (
  operation.op === "fillRect" && operation.fillStyle === "#2f9e44"
)), "scanned hero body should not use strong scan fill");
assert.ok(heroScanRingOps.some((operation) => (
  operation.op === "stroke"
  && operation.strokeStyle === "#14532d"
  && operation.lineWidth === 4
  && operation.arc
)), "scanned hero should draw strong scan ring stroke");
helpers.renderSnapshot(markerSnapshot, {{ preserveView: false }});
targetFilterButtons()[0].dispatch("click", {{}});
const filterNeutral = renderedView.markers.find((marker) => marker.id === "neutral:0");
const filterNeutralScreen = helpers.worldToScreen(filterNeutral.world, renderedView);
elements["battle-map"].dispatch("contextmenu", {{
  clientX: filterNeutralScreen.x,
  clientY: filterNeutralScreen.y,
  preventDefault() {{}}
}});
assert.strictEqual(helpers.currentMapViewForTest().activeMarkerId, "neutral:0");
targetFilterButtons()[1].dispatch("click", {{}});
const heroesFilterView = helpers.currentMapViewForTest();
assert.strictEqual(heroesFilterView.activeMarkerId, null);
assert.ok(!heroesFilterView.markers.some((marker) => marker.type === "neutral"));
assert.ok(heroesFilterView.markers.some((marker) => marker.type === "hero"));
assert.ok(elements["target-state"].textContent.includes("No target selected"));
elements["scan-radius"].value = "3";
let scanRequestStart = fetchRequests.length;
elements["scan-button"].dispatch("click", {{}});
assert.ok(targetFilterButtons().every((button) => button.disabled));
await flushPromises();
let scanRequests = scanRequestsSince(scanRequestStart);
assert.strictEqual(scanRequests.length, 1);
assert.strictEqual(JSON.parse(scanRequests[0].options.body).target_type, "hero");
assert.ok(targetFilterButtons().every((button) => !button.disabled));
assert.deepStrictEqual(scanResultIds(), ["target:near", "target:missing", "target:easy"]);
const scanRequestsBeforeSortChange = fetchRequests.length;
scanSortButtons()[1].dispatch("click", {{}});
assert.strictEqual(fetchRequests.length, scanRequestsBeforeSortChange);
assert.strictEqual(scanSortButtons()[1].className, "active");
assert.deepStrictEqual(scanResultIds(), ["target:easy", "target:near", "target:missing"]);
deferNextScanResponse = true;
scanRequestStart = fetchRequests.length;
elements["scan-button"].dispatch("click", {{}});
scanRequests = scanRequestsSince(scanRequestStart);
assert.strictEqual(scanRequests.length, 1);
assert.strictEqual(pendingScanResponses.length, 1);
assert.ok(scanSortButtons().every((button) => !button.disabled));
assert.ok(scanStateTextIncludes("Running scan"));
assert.deepStrictEqual(scanResultIds(), []);
scanSortButtons()[0].dispatch("click", {{}});
assert.strictEqual(fetchRequests.length, scanRequestStart + 1);
assert.strictEqual(scanSortButtons()[0].className, "active");
assert.ok(scanStateTextIncludes("Running scan"));
assert.deepStrictEqual(scanResultIds(), []);
pendingScanResponses.shift()();
await flushPromises();
assert.deepStrictEqual(scanResultIds(), ["target:near", "target:missing", "target:easy"]);
scanSortButtons()[1].dispatch("click", {{}});
assert.strictEqual(scanSortButtons()[1].className, "active");
assert.deepStrictEqual(scanResultIds(), ["target:easy", "target:near", "target:missing"]);
targetFilterButtons()[2].dispatch("click", {{}});
const monstersFilterView = helpers.currentMapViewForTest();
assert.ok(monstersFilterView.markers.some((marker) => marker.type === "neutral"));
assert.ok(!monstersFilterView.markers.some((marker) => marker.type === "hero"));
assert.strictEqual(scanSortButtons()[1].className, "active");
assert.ok(elements["scan-state"].children.some((child) => child.textContent.includes("No scan results")));
scanRequestStart = fetchRequests.length;
elements["scan-button"].dispatch("click", {{}});
await flushPromises();
scanRequests = scanRequestsSince(scanRequestStart);
assert.strictEqual(scanRequests.length, 1);
assert.strictEqual(JSON.parse(scanRequests[0].options.body).target_type, "neutral");
assert.deepStrictEqual(scanResultIds(), ["target:easy", "target:near", "target:missing"]);
nextScanResults = [
  {{
    target_id: "neutral:0",
    target_type: "neutral",
    distance: 1,
    win_pct: 68,
    enemy_ai_value: 120,
    note: "scan visible",
    target: {{ name: "Visible Gnoll", creature_name: "Gnoll", count: 8 }}
  }},
  {{
    target_id: "neutral:not-visible",
    target_type: "neutral",
    distance: 2,
    win_pct: 20,
    enemy_ai_value: 80,
    note: "scan hidden",
    target: {{ name: "Filtered Target", creature_name: "Filtered Target" }}
  }}
];
scanRequestStart = fetchRequests.length;
const neutralScanRingStart = drawOperations.length;
elements["scan-button"].dispatch("click", {{}});
await flushPromises();
scanRequests = scanRequestsSince(scanRequestStart);
assert.strictEqual(scanRequests.length, 1);
const neutralScanRingOps = drawOperations.slice(neutralScanRingStart);
assert.ok(neutralScanRingOps.some((operation) => (
  operation.op === "fill" && operation.fillStyle === "#1f2937" && operation.arc
)));
assert.ok(!neutralScanRingOps.some((operation) => (
  operation.op === "fill" && operation.fillStyle === "#d99a21"
)));
assert.ok(neutralScanRingOps.some((operation) => (
  operation.op === "stroke"
  && operation.strokeStyle === "#7c4a03"
  && operation.lineWidth === 4
  && operation.arc
)));
const visibleScanRow = scanResultRows().find((row) => row.dataset.targetId === "neutral:0");
const missingScanRow = scanResultRows().find((row) => row.dataset.targetId === "neutral:not-visible");
assert.ok(visibleScanRow);
assert.ok(missingScanRow);
const beforeHoverView = helpers.currentMapViewForTest();
const beforeHoverFetchCalls = fetchCalls;
const beforeHoverTargetText = elements["target-state"].textContent;
const neutralHoverRingStart = drawOperations.length;
visibleScanRow.dispatch("pointerenter", {{}});
const neutralHoverRingOps = drawOperations.slice(neutralHoverRingStart);
assert.ok(neutralHoverRingOps.some((operation) => (
  operation.op === "stroke"
  && operation.strokeStyle === "#7c4a03"
  && operation.lineWidth === 4
  && operation.arc
)));
assert.ok(neutralHoverRingOps.some((operation) => (
  operation.op === "stroke"
  && operation.strokeStyle === "#4b5563"
  && operation.lineWidth === 2
  && operation.arc
)));
let hoverView = helpers.currentMapViewForTest();
assert.strictEqual(hoverView.hoveredMarkerId, "neutral:0");
assert.strictEqual(hoverView.activeMarkerId, beforeHoverView.activeMarkerId);
assert.strictEqual(hoverView.level, beforeHoverView.level);
assert.strictEqual(hoverView.zoom, beforeHoverView.zoom);
assert.deepStrictEqual(hoverView.pan, beforeHoverView.pan);
assert.strictEqual(elements["target-state"].textContent, beforeHoverTargetText);
assert.strictEqual(fetchCalls, beforeHoverFetchCalls);
missingScanRow.dispatch("focus", {{}});
hoverView = helpers.currentMapViewForTest();
assert.strictEqual(hoverView.hoveredMarkerId, null);
assert.strictEqual(hoverView.activeMarkerId, beforeHoverView.activeMarkerId);
assert.strictEqual(hoverView.level, beforeHoverView.level);
assert.strictEqual(hoverView.zoom, beforeHoverView.zoom);
assert.deepStrictEqual(hoverView.pan, beforeHoverView.pan);
assert.strictEqual(fetchCalls, beforeHoverFetchCalls);
visibleScanRow.dispatch("pointerenter", {{}});
visibleScanRow.dispatch("pointerleave", {{}});
assert.strictEqual(helpers.currentMapViewForTest().hoveredMarkerId, null);
visibleScanRow.dispatch("focus", {{}});
assert.strictEqual(helpers.currentMapViewForTest().hoveredMarkerId, "neutral:0");
visibleScanRow.dispatch("blur", {{}});
assert.strictEqual(helpers.currentMapViewForTest().hoveredMarkerId, null);
const beforeScanClickFetchCalls = fetchCalls;
const neutralActiveRingStart = drawOperations.length;
visibleScanRow.dispatch("click", {{}});
const neutralActiveRingOps = drawOperations.slice(neutralActiveRingStart);
assert.ok(neutralActiveRingOps.some((operation) => (
  operation.op === "stroke"
  && operation.strokeStyle === "#7c4a03"
  && operation.lineWidth === 4
  && operation.arc
)));
assert.ok(neutralActiveRingOps.some((operation) => (
  operation.op === "stroke"
  && operation.strokeStyle === "#111827"
  && operation.lineWidth === 2
  && operation.arc
)));
const clickedScanView = helpers.currentMapViewForTest();
assert.strictEqual(fetchCalls, beforeScanClickFetchCalls);
assert.strictEqual(clickedScanView.activeMarkerId, "neutral:0");
assert.ok(elements["target-state"].textContent.includes("neutral neutral:0"));
assert.ok(treeText(elements["estimate-state"]).includes("8x Gnoll"));
assert.ok(treeText(elements["estimate-state"]).includes("scan visible"));
helpers.renderSnapshot(markerSnapshot, {{ preserveView: false }});
targetFilterButtons()[0].dispatch("click", {{}});
const bothFilterView = helpers.currentMapViewForTest();
assert.ok(bothFilterView.markers.some((marker) => marker.type === "neutral"));
assert.ok(bothFilterView.markers.some((marker) => marker.type === "hero"));
assert.strictEqual(scanSortButtons()[1].className, "active");
scanRequestStart = fetchRequests.length;
elements["scan-button"].dispatch("click", {{}});
await flushPromises();
scanRequests = scanRequestsSince(scanRequestStart);
assert.strictEqual(scanRequests.length, 1);
assert.strictEqual(JSON.parse(scanRequests[0].options.body).target_type, "all");
assert.deepStrictEqual(scanResultIds(), ["target:easy", "target:near", "target:missing"]);
const renderedTown = renderedView.markers.find((marker) => marker.id === "town:0");
const renderedTownScreen = helpers.worldToScreen(renderedTown.world, renderedView);
const fetchCallsBeforeTownClick = fetchCalls;
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 7,
  clientX: renderedTownScreen.x,
  clientY: renderedTownScreen.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 7,
  clientX: renderedTownScreen.x,
  clientY: renderedTownScreen.y
}});
assert.strictEqual(fetchCalls, fetchCallsBeforeTownClick);
assert.ok(elements["target-state"].textContent.includes("town town:0"));
assert.ok(elements["target-state"].textContent.includes("Initial owner: Red"));
assert.ok(elements["estimate-state"].textContent.includes("Town target"));
const renderedNeutral = renderedView.markers.find((marker) => marker.id === "neutral:0");
const renderedNeutralScreen = helpers.worldToScreen(renderedNeutral.world, renderedView);
let neutralContextMenuPrevented = 0;
elements["battle-map"].dispatch("contextmenu", {{
  clientX: renderedNeutralScreen.x,
  clientY: renderedNeutralScreen.y,
  preventDefault() {{
    neutralContextMenuPrevented += 1;
  }}
}});
assert.strictEqual(neutralContextMenuPrevented, 1);
assert.strictEqual(elements["target-context-menu"].hidden, false);
const neutralContextButtons = elements["target-context-menu"].children.filter((child) => child.type === "button");
assert.deepStrictEqual(neutralContextButtons.map((button) => button.textContent), ["Simulate", "Hide"]);
assert.strictEqual(fetchCalls, fetchCallsBeforeTownClick);
const renderedPortal = renderedView.markers.find((marker) => marker.id === "portal:100");
const renderedPortalScreen = helpers.worldToScreen(renderedPortal.world, renderedView);
elements["battle-map"].dispatch("pointermove", {{
  pointerId: 80,
  clientX: renderedPortalScreen.x,
  clientY: renderedPortalScreen.y
}});
assert.strictEqual(helpers.currentMapViewForTest().activeMarkerId, "neutral:0");
let portalRelationState = helpers.currentPortalRelationStateForTest();
assert.strictEqual(portalRelationState.hoveredSourceId, "portal:100");
assert.strictEqual(portalRelationState.pinnedSourceId, null);
assert.strictEqual(portalRelationState.relation.source.id, "portal:100");
assert.deepStrictEqual(
  portalRelationState.relation.crossLevelDestinations.map((destination) => destination.id),
  ["portal:101", "portal:102"]
);
const emptyPortalRelationPoint = mapTileScreenPoint(3, 2, helpers.currentMapViewForTest());
elements["battle-map"].dispatch("pointermove", {{
  pointerId: 81,
  clientX: emptyPortalRelationPoint.x,
  clientY: emptyPortalRelationPoint.y
}});
assert.strictEqual(helpers.currentMapViewForTest().activeMarkerId, "neutral:0");
portalRelationState = helpers.currentPortalRelationStateForTest();
assert.strictEqual(portalRelationState.hoveredSourceId, null);
assert.strictEqual(portalRelationState.pinnedSourceId, null);
assert.strictEqual(portalRelationState.relation, null);
const fetchCallsBeforePortalClick = fetchCalls;
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 8,
  clientX: renderedPortalScreen.x,
  clientY: renderedPortalScreen.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 8,
  clientX: renderedPortalScreen.x,
  clientY: renderedPortalScreen.y
}});
assert.strictEqual(fetchCalls, fetchCallsBeforePortalClick);
portalRelationState = helpers.currentPortalRelationStateForTest();
assert.strictEqual(portalRelationState.hoveredSourceId, "portal:100");
assert.strictEqual(portalRelationState.pinnedSourceId, "portal:100");
assert.strictEqual(portalRelationState.relation.source.id, "portal:100");
assert.ok(elements["target-state"].textContent.includes("portal portal:100"));
assert.ok(elements["target-state"].textContent.includes("Destinations: 0,2,1; 1,2,1"));
assert.ok(elements["estimate-state"].textContent.includes("Portal target"));
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 82,
  clientX: renderedTownScreen.x,
  clientY: renderedTownScreen.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 82,
  clientX: renderedTownScreen.x,
  clientY: renderedTownScreen.y
}});
portalRelationState = helpers.currentPortalRelationStateForTest();
assert.strictEqual(portalRelationState.hoveredSourceId, null);
assert.strictEqual(portalRelationState.pinnedSourceId, null);
assert.strictEqual(portalRelationState.relation, null);
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 83,
  clientX: renderedPortalScreen.x,
  clientY: renderedPortalScreen.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 83,
  clientX: renderedPortalScreen.x,
  clientY: renderedPortalScreen.y
}});
assert.strictEqual(helpers.currentPortalRelationStateForTest().pinnedSourceId, "portal:100");
elements["battle-map"].dispatch("pointermove", {{
  pointerId: 830,
  clientX: renderedPortalScreen.x,
  clientY: renderedPortalScreen.y
}});
assert.strictEqual(helpers.currentPortalRelationStateForTest().hoveredSourceId, "portal:100");
elements["battle-map"].dispatch("pointerleave", {{}});
portalRelationState = helpers.currentPortalRelationStateForTest();
assert.strictEqual(portalRelationState.hoveredSourceId, null);
assert.strictEqual(portalRelationState.pinnedSourceId, "portal:100");
assert.strictEqual(portalRelationState.activeSourceId, "portal:100");
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 831,
  clientX: renderedPortalScreen.x,
  clientY: renderedPortalScreen.y
}});
elements["battle-map"].dispatch("pointermove", {{
  pointerId: 831,
  clientX: renderedPortalScreen.x + 12,
  clientY: renderedPortalScreen.y + 12
}});
portalRelationState = helpers.currentPortalRelationStateForTest();
assert.strictEqual(portalRelationState.hoveredSourceId, null);
assert.strictEqual(portalRelationState.pinnedSourceId, "portal:100");
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 831,
  clientX: renderedPortalScreen.x + 12,
  clientY: renderedPortalScreen.y + 12
}});
const renderedSecondPortal = renderedView.markers.find((marker) => marker.id === "portal:110");
const renderedSecondPortalScreen = helpers.worldToScreen(renderedSecondPortal.world, renderedView);
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 84,
  clientX: renderedSecondPortalScreen.x,
  clientY: renderedSecondPortalScreen.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 84,
  clientX: renderedSecondPortalScreen.x,
  clientY: renderedSecondPortalScreen.y
}});
assert.strictEqual(helpers.currentPortalRelationStateForTest().pinnedSourceId, "portal:110");
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 85,
  clientX: emptyPortalRelationPoint.x,
  clientY: emptyPortalRelationPoint.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 85,
  clientX: emptyPortalRelationPoint.x,
  clientY: emptyPortalRelationPoint.y
}});
portalRelationState = helpers.currentPortalRelationStateForTest();
assert.strictEqual(portalRelationState.hoveredSourceId, null);
assert.strictEqual(portalRelationState.pinnedSourceId, null);
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 86,
  clientX: renderedPortalScreen.x,
  clientY: renderedPortalScreen.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 86,
  clientX: renderedPortalScreen.x,
  clientY: renderedPortalScreen.y
}});
assert.strictEqual(fetchCalls, fetchCallsBeforePortalClick);
assert.strictEqual(helpers.currentPortalRelationStateForTest().pinnedSourceId, "portal:100");
helpers.renderSnapshot(markerSnapshot, {{ preserveView: true }});
assert.strictEqual(helpers.currentPortalRelationStateForTest().hoveredSourceId, null);
assert.strictEqual(helpers.currentPortalRelationStateForTest().pinnedSourceId, null);
let contextMenuPrevented = 0;
elements["battle-map"].dispatch("contextmenu", {{
  clientX: renderedPortalScreen.x,
  clientY: renderedPortalScreen.y,
  preventDefault() {{
    contextMenuPrevented += 1;
  }}
}});
assert.strictEqual(contextMenuPrevented, 1);
assert.strictEqual(elements["target-context-menu"].hidden, false);
const destinationButtons = elements["target-context-menu"].children.filter((child) => child.type === "button");
assert.strictEqual(destinationButtons.length, 2);
destinationButtons[0].dispatch("click", {{}});
const destinationView = helpers.currentMapViewForTest();
assert.strictEqual(destinationView.level, 1);
assert.strictEqual(destinationView.activeMarkerId, "portal:101");
assert.ok(elements["target-state"].textContent.includes("portal portal:101"));
const renderedHeroTarget = destinationView.markers.find((marker) => marker.id === "hero:1");
const renderedHeroTargetScreen = helpers.worldToScreen(renderedHeroTarget.world, destinationView);
let heroContextMenuPrevented = 0;
elements["battle-map"].dispatch("contextmenu", {{
  clientX: renderedHeroTargetScreen.x,
  clientY: renderedHeroTargetScreen.y,
  preventDefault() {{
    heroContextMenuPrevented += 1;
  }}
}});
assert.strictEqual(heroContextMenuPrevented, 1);
assert.strictEqual(elements["target-context-menu"].hidden, false);
const heroContextButtons = elements["target-context-menu"].children.filter((child) => child.type === "button");
assert.deepStrictEqual(heroContextButtons.map((button) => button.textContent), ["Select as my hero", "Simulate", "Hide"]);
const fetchRequestCountBeforeHeroSelect = fetchRequests.length;
await Promise.all(heroContextButtons[0].dispatch("click", {{}}));
const heroSelectRequests = fetchRequests
  .slice(fetchRequestCountBeforeHeroSelect)
  .filter((request) => request.path === "/api/select-hero");
assert.strictEqual(heroSelectRequests.length, 1);
const heroSelectRequest = heroSelectRequests[0];
assert.strictEqual(heroSelectRequest.path, "/api/select-hero");
assert.deepStrictEqual(JSON.parse(heroSelectRequest.options.body), {{ hero_id: "hero:1" }});
await flushPromises();
let heroSelectScanRequests = scanRequestsSince(fetchRequestCountBeforeHeroSelect);
assert.strictEqual(heroSelectScanRequests.length, 1);
assert.deepStrictEqual(JSON.parse(heroSelectScanRequests[0].options.body), {{
  hero_id: "hero:1",
  radius: 3,
  target_type: "all"
}});
assert.strictEqual(scanSortButtons()[1].className, "active");
assert.deepStrictEqual(scanResultIds(), ["target:easy", "target:near", "target:missing"]);
const selectedHeroView = helpers.currentMapViewForTest();
assert.strictEqual(selectedHeroView.snapshot.selected_hero_id, "hero:1");
assert.strictEqual(selectedHeroView.snapshot.recent_heroes[0], "Fafner");
const selectedHeroAfterSelect = selectedHeroView.markers.find((marker) => marker.id === "hero:1");
assert.ok(selectedHeroAfterSelect, selectedHeroView.markers.map((marker) => marker.id).join(","));
assert.strictEqual(selectedHeroAfterSelect.selected, true);
assert.strictEqual(elements["recent-heroes"].children[0].textContent, "Fafner");
let selectedHeroContextPrevented = 0;
const selectedHeroMarker = selectedHeroView.markers.find((marker) => marker.id === "hero:1");
const selectedHeroScreen = helpers.worldToScreen(selectedHeroMarker.world, selectedHeroView);
elements["battle-map"].dispatch("contextmenu", {{
  clientX: selectedHeroScreen.x,
  clientY: selectedHeroScreen.y,
  preventDefault() {{
    selectedHeroContextPrevented += 1;
  }}
}});
assert.strictEqual(selectedHeroContextPrevented, 1);
assert.strictEqual(elements["target-context-menu"].hidden, false);
assert.deepStrictEqual(
  elements["target-context-menu"].children
    .filter((child) => child.type === "button")
    .map((button) => button.textContent),
  []
);
assert.deepStrictEqual(
  elements["target-context-menu"].children
    .filter((child) => child.className === "context-menu-note")
    .map((note) => note.textContent),
  ["Current hero"]
);
const selectableHiddenHeroSnapshot = {{
  ...hiddenHeroSnapshot,
  show_hidden: true,
  hidden_hero_target_ids: ["hero:hidden"],
  heroes: hiddenHeroSnapshot.heroes.map((hero) => (
    hero.id === "hero:hidden"
      ? {{ ...hero, position: {{ x: 3, y: 2, z: 1 }} }}
      : hero
  ))
}};
helpers.renderSnapshot(selectableHiddenHeroSnapshot, {{ preserveView: false }});
const hiddenHeroView = helpers.currentMapViewForTest();
const hiddenHeroMarker = hiddenHeroView.markers.find((marker) => marker.id === "hero:hidden");
const hiddenHeroScreen = helpers.worldToScreen(hiddenHeroMarker.world, hiddenHeroView);
let hiddenHeroContextPrevented = 0;
elements["battle-map"].dispatch("contextmenu", {{
  clientX: hiddenHeroScreen.x,
  clientY: hiddenHeroScreen.y,
  preventDefault() {{
    hiddenHeroContextPrevented += 1;
  }}
}});
assert.strictEqual(hiddenHeroContextPrevented, 1);
const hiddenHeroButtons = elements["target-context-menu"].children.filter((child) => child.type === "button");
assert.deepStrictEqual(hiddenHeroButtons.map((button) => button.textContent), ["Select as my hero", "Unhide"]);
nextScanResults = [
  {{
    target_id: "target:stale",
    target_type: "neutral",
    distance: 0,
    win_pct: 99,
    enemy_ai_value: 1,
    note: "stale",
    target: {{ name: "Stale", creature_name: "Stale" }}
  }}
];
deferNextScanResponse = true;
const staleScanStart = fetchRequests.length;
elements["scan-button"].dispatch("click", {{}});
let staleScanRequests = scanRequestsSince(staleScanStart);
assert.strictEqual(staleScanRequests.length, 1);
assert.strictEqual(pendingScanResponses.length, 1);
const fetchRequestCountBeforeHiddenSelect = fetchRequests.length;
await Promise.all(hiddenHeroButtons[0].dispatch("click", {{}}));
const hiddenHeroSelectRequests = fetchRequests
  .slice(fetchRequestCountBeforeHiddenSelect)
  .filter((request) => request.path === "/api/select-hero");
assert.strictEqual(hiddenHeroSelectRequests.length, 1);
const hiddenHeroSelectRequest = hiddenHeroSelectRequests[0];
assert.strictEqual(hiddenHeroSelectRequest.path, "/api/select-hero");
assert.deepStrictEqual(JSON.parse(hiddenHeroSelectRequest.options.body), {{ hero_id: "hero:hidden" }});
await flushPromises();
const hiddenHeroScanRequests = scanRequestsSince(fetchRequestCountBeforeHiddenSelect);
assert.strictEqual(hiddenHeroScanRequests.length, 1);
assert.deepStrictEqual(JSON.parse(hiddenHeroScanRequests[0].options.body), {{
  hero_id: "hero:hidden",
  radius: 3,
  target_type: "all"
}});
pendingScanResponses.shift()();
await flushPromises();
assert.deepStrictEqual(scanResultIds(), ["target:easy", "target:near", "target:missing"]);
assert.ok(!scanResultIds().includes("target:stale"));
const selectedHiddenHeroView = helpers.currentMapViewForTest();
const selectedHiddenHeroMarker = selectedHiddenHeroView.markers.find((marker) => marker.id === "hero:hidden");
assert.deepStrictEqual(selectedHiddenHeroView.snapshot.hidden_hero_target_ids, []);
assert.strictEqual(selectedHiddenHeroView.snapshot.heroes.find((hero) => hero.id === "hero:hidden").hidden, false);
assert.strictEqual(selectedHiddenHeroMarker.selected, true);
assert.strictEqual(selectedHiddenHeroMarker.hidden, false);
selectedHiddenHeroView.snapshot.show_hidden = false;
helpers.renderSnapshot(selectedHiddenHeroView.snapshot, {{ preserveView: true }});
const hiddenShowOffView = helpers.currentMapViewForTest();
assert.strictEqual(hiddenShowOffView.markers.find((marker) => marker.id === "hero:hidden").selected, true);
const fetchCallsAfterContextActions = fetchCalls;
drawOperations.length = 0;
const routeToggle = elements["show-route-overlay-toggle"];
routeToggle.checked = false;
routeToggle.dispatch("change");
const overlayFillsAfterToggleOff = drawOperations.filter((operation) => (
  operation.op === "fillRect" && routeFillStyles.has(operation.fillStyle)
));
assert.strictEqual(overlayFillsAfterToggleOff.length, 0);
drawOperations.length = 0;
routeToggle.checked = true;
routeToggle.dispatch("change");
const overlayFillsAfterToggleOn = drawOperations.filter((operation) => (
  operation.op === "fillRect" && routeFillStyles.has(operation.fillStyle)
));
assert.ok(overlayFillsAfterToggleOn.length >= 3);
assert.strictEqual(fetchCalls, fetchCallsAfterContextActions);

const noHeroPathSnapshot = {{
  ...markerSnapshot,
  selected_hero_id: null,
  heroes: [],
  neutral_targets: [],
  town_targets: [],
  portal_targets: [],
  portal_edges: []
}};
helpers.renderSnapshot(noHeroPathSnapshot, {{ preserveView: false }});
elements["path-mode-toggle"].checked = true;
elements["path-mode-toggle"].dispatch("change", {{}});
assert.strictEqual(helpers.currentMapViewForTest().pathMode, true);
const noHeroPathStart = fetchRequests.length;
const noHeroPoint = mapTileScreenPoint(1, 1, helpers.currentMapViewForTest());
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 21,
  clientX: noHeroPoint.x,
  clientY: noHeroPoint.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 21,
  clientX: noHeroPoint.x,
  clientY: noHeroPoint.y
}});
assert.strictEqual(pathRequestsSince(noHeroPathStart).length, 0);
assert.ok(elements["path-state"].textContent.includes("Select a hero before pathing."));
assert.ok(elements["estimate-state"].textContent.includes("No simulation run."));

const pathMarkerSnapshot = {{
  ...markerSnapshot,
  selected_hero_id: "hero:0"
}};
helpers.renderSnapshot(pathMarkerSnapshot, {{ preserveView: false }});
targetFilterButtons()[0].dispatch("click", {{}});
elements["path-mode-toggle"].checked = true;
elements["path-mode-toggle"].dispatch("change", {{}});
assert.strictEqual(helpers.currentMapViewForTest().pathMode, true);
assert.strictEqual(elements["path-mode-toggle"].checked, true);
const pathView = helpers.currentMapViewForTest();
const pathPortal = pathView.markers.find((marker) => marker.id === "portal:100");
const pathPortalScreen = helpers.worldToScreen(pathPortal.world, pathView);
elements["battle-map"].dispatch("pointermove", {{
  pointerId: 220,
  clientX: pathPortalScreen.x,
  clientY: pathPortalScreen.y
}});
assert.strictEqual(helpers.currentPortalRelationStateForTest().hoveredSourceId, "portal:100");
assert.strictEqual(helpers.currentPortalRelationStateForTest().pinnedSourceId, null);
const pathPortalStart = fetchRequests.length;
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 221,
  clientX: pathPortalScreen.x,
  clientY: pathPortalScreen.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 221,
  clientX: pathPortalScreen.x,
  clientY: pathPortalScreen.y
}});
await flushPromises();
let pathPortalRequests = pathRequestsSince(pathPortalStart);
assert.strictEqual(pathPortalRequests.length, 1);
assert.deepStrictEqual(JSON.parse(pathPortalRequests[0].options.body), {{
  hero_id: "hero:0",
  target_id: "portal:100"
}});
assert.strictEqual(
  fetchRequests.slice(pathPortalStart).filter((request) => request.path === "/api/simulate-target").length,
  0
);
assert.strictEqual(helpers.currentPortalRelationStateForTest().pinnedSourceId, null);
assert.strictEqual(helpers.currentPortalRelationStateForTest().hoveredSourceId, "portal:100");
const pathNeutral = pathView.markers.find((marker) => marker.id === "neutral:0");
const pathNeutralScreen = helpers.worldToScreen(pathNeutral.world, pathView);
const foundPathStart = fetchRequests.length;
const foundPathDrawStart = drawOperations.length;
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 22,
  clientX: pathNeutralScreen.x,
  clientY: pathNeutralScreen.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 22,
  clientX: pathNeutralScreen.x,
  clientY: pathNeutralScreen.y
}});
await flushPromises();
let pathRequests = pathRequestsSince(foundPathStart);
assert.strictEqual(pathRequests.length, 1);
assert.deepStrictEqual(JSON.parse(pathRequests[0].options.body), {{
  hero_id: "hero:0",
  target_id: "neutral:0"
}});
assert.strictEqual(
  fetchRequests.slice(foundPathStart).filter((request) => request.path === "/api/simulate-target").length,
  0
);
assert.ok(treeText(elements["path-state"]).includes("found"));
assert.ok(treeText(elements["path-state"]).includes("3"));
const foundPathOps = drawOperations.slice(foundPathDrawStart);
assert.ok(foundPathOps.some((operation) => (
  operation.op === "stroke"
  && operation.strokeStyle === "#dc2626"
  && operation.lineWidth === 3
)), "found path should draw the route stroke");
assert.ok(foundPathOps.some((operation) => operation.op === "save"));
assert.ok(foundPathOps.some((operation) => operation.op === "restore"));

const emptyTilePoint = mapTileScreenPoint(2, 2, helpers.currentMapViewForTest());
assert.deepStrictEqual(
  helpers.tilePositionForCanvasPoint(
    emptyTilePoint,
    helpers.currentMapViewForTest().snapshot,
    helpers.currentMapViewForTest()
  ),
  {{ x: 2, y: 2, z: 0 }}
);
const emptyTilePathStart = fetchRequests.length;
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 23,
  clientX: emptyTilePoint.x,
  clientY: emptyTilePoint.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 23,
  clientX: emptyTilePoint.x,
  clientY: emptyTilePoint.y
}});
await flushPromises();
pathRequests = pathRequestsSince(emptyTilePathStart);
assert.strictEqual(pathRequests.length, 1);
assert.deepStrictEqual(JSON.parse(pathRequests[0].options.body), {{
  hero_id: "hero:0",
  target_position: {{ x: 2, y: 2, z: 0 }}
}});

nextPathPayload = {{
  hero_id: "hero:0",
  target_id: "neutral:0",
  status: "not_found",
  requested_target_position: {{ x: 1, y: 3, z: 0 }},
  resolved_target_position: null,
  steps: [],
  segments: [],
  message: "no land path found"
}};
const notFoundPathStart = fetchRequests.length;
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 24,
  clientX: pathNeutralScreen.x,
  clientY: pathNeutralScreen.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 24,
  clientX: pathNeutralScreen.x,
  clientY: pathNeutralScreen.y
}});
await flushPromises();
assert.strictEqual(pathRequestsSince(notFoundPathStart).length, 1);
assert.ok(elements["path-state"].className.includes("error"));
assert.ok(treeText(elements["path-state"]).includes("not_found"));
assert.ok(treeText(elements["path-state"]).includes("no land path found"));

nextPathPayload = {{
  hero_id: "hero:0",
  target_id: "neutral:0",
  status: "invalid",
  requested_target_position: {{ x: 9, y: 9, z: 0 }},
  resolved_target_position: null,
  steps: [],
  segments: [],
  message: "target is outside map"
}};
const invalidPathStart = fetchRequests.length;
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 25,
  clientX: pathNeutralScreen.x,
  clientY: pathNeutralScreen.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 25,
  clientX: pathNeutralScreen.x,
  clientY: pathNeutralScreen.y
}});
await flushPromises();
assert.strictEqual(pathRequestsSince(invalidPathStart).length, 1);
assert.ok(elements["path-state"].className.includes("error"));
assert.ok(treeText(elements["path-state"]).includes("invalid"));
assert.ok(treeText(elements["path-state"]).includes("target is outside map"));

nextPathError = {{ status: 400, error: "bad target" }};
const errorPathStart = fetchRequests.length;
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 26,
  clientX: pathNeutralScreen.x,
  clientY: pathNeutralScreen.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 26,
  clientX: pathNeutralScreen.x,
  clientY: pathNeutralScreen.y
}});
await flushPromises();
assert.strictEqual(pathRequestsSince(errorPathStart).length, 1);
assert.ok(elements["path-state"].className.includes("error"));
assert.ok(elements["path-state"].textContent.includes("Path error: bad target"));

nextPathPayload = {{
  hero_id: "hero:0",
  target_id: "neutral:0",
  status: "found",
  requested_target_position: {{ x: 1, y: 3, z: 0 }},
  resolved_target_position: {{ x: 1, y: 3, z: 0 }},
  steps: [
    {{ position: {{ x: 1, y: 2, z: 0 }}, route: "land", cost: 0 }},
    {{ position: {{ x: 1, y: 3, z: 0 }}, route: "land", cost: 1 }}
  ],
  segments: [],
  message: "stale path should not render"
}};
deferNextPathResponse = true;
const stalePathStart = fetchRequests.length;
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 27,
  clientX: pathNeutralScreen.x,
  clientY: pathNeutralScreen.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 27,
  clientX: pathNeutralScreen.x,
  clientY: pathNeutralScreen.y
}});
assert.strictEqual(pathRequestsSince(stalePathStart).length, 1);
assert.strictEqual(pendingPathResponses.length, 1);
const pendingPathRequestId = helpers.currentPathStateForTest().requestId;
assert.strictEqual(helpers.currentPathStateForTest().running, true);
elements["path-mode-toggle"].checked = false;
elements["path-mode-toggle"].dispatch("change", {{}});
assert.strictEqual(helpers.currentMapViewForTest().pathMode, false);
assert.ok(helpers.currentPathStateForTest().requestId > pendingPathRequestId);
assert.strictEqual(helpers.currentPathStateForTest().result, null);
assert.strictEqual(elements["path-state"].textContent, "No path requested.");
pendingPathResponses.shift()();
await flushPromises();
assert.strictEqual(helpers.currentPathStateForTest().result, null);
assert.ok(!treeText(elements["path-state"]).includes("stale path should not render"));

helpers.renderSnapshot(pathMarkerSnapshot, {{ preserveView: false }});
targetFilterButtons()[0].dispatch("click", {{}});
elements["path-mode-toggle"].checked = true;
elements["path-mode-toggle"].dispatch("change", {{}});
const crossLevelView = helpers.currentMapViewForTest();
const crossLevelNeutral = crossLevelView.markers.find((marker) => marker.id === "neutral:0");
const crossLevelNeutralScreen = helpers.worldToScreen(crossLevelNeutral.world, crossLevelView);
const crossLevelPayload = {{
  hero_id: "hero:0",
  target_id: "neutral:0",
  status: "found",
  requested_target_position: {{ x: 2, y: 1, z: 1 }},
  resolved_target_position: {{ x: 2, y: 1, z: 1 }},
  steps: [
    {{ position: {{ x: 1, y: 2, z: 0 }} }},
    {{ position: {{ x: 1, y: 1, z: 0 }} }},
    {{ position: {{ x: 1, y: 1, z: 1 }} }},
    {{ position: {{ x: 2, y: 1, z: 1 }} }}
  ],
  segments: [
    {{
      segment_type: "walk",
      start_position: {{ x: 1, y: 2, z: 0 }},
      end_position: {{ x: 1, y: 1, z: 0 }},
      is_non_deterministic: false,
      steps: [
        {{ position: {{ x: 1, y: 2, z: 0 }} }},
        {{ position: {{ x: 1, y: 1, z: 0 }} }}
      ]
    }},
    {{
      segment_type: "portal",
      start_position: {{ x: 1, y: 1, z: 0 }},
      end_position: {{ x: 1, y: 1, z: 1 }},
      is_non_deterministic: true,
      steps: [
        {{ position: {{ x: 1, y: 1, z: 0 }} }},
        {{ position: {{ x: 1, y: 1, z: 1 }} }}
      ],
      portal_edge: {{
        source_id: "portal:100",
        destination_id: "portal:101",
        source_position: {{ x: 1, y: 1, z: 0 }},
        destination_position: {{ x: 1, y: 1, z: 1 }},
        portal_type: "monolith_one_way",
        channel_key: "monolith-one-way:7",
        is_non_deterministic: true
      }}
    }},
    {{
      segment_type: "walk",
      start_position: {{ x: 1, y: 1, z: 1 }},
      end_position: {{ x: 2, y: 1, z: 1 }},
      is_non_deterministic: false,
      steps: [
        {{ position: {{ x: 1, y: 1, z: 1 }} }},
        {{ position: {{ x: 2, y: 1, z: 1 }} }}
      ]
    }},
    {{
      segment_type: "walk",
      steps: [],
      is_non_deterministic: false
    }}
  ],
  message: null
}};
nextPathPayload = crossLevelPayload;
const crossLevelStart = fetchRequests.length;
elements["battle-map"].dispatch("pointerdown", {{
  button: 0,
  pointerId: 28,
  clientX: crossLevelNeutralScreen.x,
  clientY: crossLevelNeutralScreen.y
}});
elements["battle-map"].dispatch("pointerup", {{
  button: 0,
  pointerId: 28,
  clientX: crossLevelNeutralScreen.x,
  clientY: crossLevelNeutralScreen.y
}});
await flushPromises();
assert.strictEqual(pathRequestsSince(crossLevelStart).length, 1);
assert.strictEqual(helpers.currentMapViewForTest().level, 0);
const segmentButtons = pathSegmentButtons();
assert.strictEqual(segmentButtons.length, 4);
assert.ok(treeText(segmentButtons[0]).includes("Walk"));
assert.ok(treeText(segmentButtons[0]).includes("1,2,0 -> 1,1,0"));
assert.ok(treeText(segmentButtons[1]).includes("One-way monolith"));
assert.ok(treeText(segmentButtons[1]).includes("1,1,0 -> 1,1,1"));
assert.ok(treeText(segmentButtons[1]).includes("monolith-one-way:7"));
assert.ok(treeText(segmentButtons[1]).includes("non-deterministic"));
assert.ok(treeText(segmentButtons[2]).includes("1,1,1 -> 2,1,1"));
assert.strictEqual(segmentButtons[3].disabled, true);
assert.ok(treeText(segmentButtons[3]).includes("no focus position"));

const segmentClickRequestStart = fetchRequests.length;
segmentButtons[1].dispatch("click", {{}});
assert.strictEqual(fetchRequests.length, segmentClickRequestStart);
assert.strictEqual(helpers.currentMapViewForTest().level, 0);
segmentButtons[2].dispatch("click", {{}});
assert.strictEqual(fetchRequests.length, segmentClickRequestStart);
const levelOneSegmentView = helpers.currentMapViewForTest();
assert.strictEqual(levelOneSegmentView.level, 1);
const levelOneFocus = helpers.pathSegmentFocusPosition(crossLevelPayload.segments[2]);
const levelOneFocusWorld = helpers.pathPointForPosition(levelOneFocus, 28);
assert.deepStrictEqual(levelOneSegmentView.pan, {{
  x: (elements["battle-map"].width / 2) - (levelOneFocusWorld.x * levelOneSegmentView.zoom),
  y: (elements["battle-map"].height / 2) - (levelOneFocusWorld.y * levelOneSegmentView.zoom)
}});
assert.strictEqual(helpers.currentPathStateForTest().result.status, "found");
assert.ok(pathSegmentButtons().length >= 4);
}})().catch((error) => {{
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
}});
"""
        completed = subprocess.run(
            [node, "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)

    def test_default_server_binds_to_localhost(self):
        server = battle_estimator_gui.create_server(port=0)
        try:
            host, _ = server.server_address[:2]

            self.assertEqual(host, battle_estimator_gui.DEFAULT_HOST)
        finally:
            server.server_close()

    def test_state_endpoint_returns_snapshot_selected_hero_and_recent_heroes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            save_path = _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            config_path.write_text(
                json.dumps({"recent_heroes": ["Isra", "Marius"]}) + "\n",
                encoding="utf-8",
            )
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                selected_hero_id="hero:256",
                config_path=config_path,
            )

            def check(base_url):
                status, payload = self._get_json(base_url, "/api/state")

                self.assertEqual(status, 200)
                self.assertEqual(payload["save_file"], str(save_path))
                self.assertEqual(payload["selected_hero_id"], "hero:256")
                self.assertEqual(payload["recent_heroes"], ["Isra", "Marius"])
                self.assertEqual(payload["route_layers"], [["L"]])
                self.assertEqual(payload["town_targets"], [])
                self.assertEqual(payload["portal_targets"], [])
                self.assertEqual(payload["portal_edges"], [])

            self._with_server(check, app_state=app_state)

    def test_state_endpoint_includes_town_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map_with_town(temp_path / "town-map.h3m")
            config_path = temp_path / "config.json"
            config_path.write_text("{}\n", encoding="utf-8")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )

            def check(base_url):
                status, payload = self._get_json(base_url, "/api/state")

                self.assertEqual(status, 200)
                self.assertEqual(len(payload["town_targets"]), 1)
                town = payload["town_targets"][0]
                self.assertEqual(town["id"], "town:0")
                self.assertEqual(town["object_index"], 0)
                self.assertEqual(town["position"], {"x": 6, "y": 5, "z": 0})
                self.assertEqual(town["anchor_position"], {"x": 7, "y": 5, "z": 0})
                self.assertEqual(town["object_id"], h3_map_parser.H3M_OBJECT_TOWN)
                self.assertEqual(town["h3m_subid"], 3)
                self.assertEqual(town["faction_subid"], 3)
                self.assertEqual(town["initial_owner"], 2)
                self.assertEqual(town["initial_owner_color_name"], "tan")
                self.assertEqual(town["custom_name"], "Castle Keep")
                self.assertTrue(town["has_garrison"])

            self._with_server(check, app_state=app_state)

    def test_state_endpoint_includes_portal_targets_and_edges(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map_with_portals(temp_path / "portal-map.h3m")
            config_path = temp_path / "config.json"
            config_path.write_text("{}\n", encoding="utf-8")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )

            def check(base_url):
                status, payload = self._get_json(base_url, "/api/state")

                self.assertEqual(status, 200)
                self.assertEqual(len(payload["portal_targets"]), 2)
                entrance = payload["portal_targets"][0]
                self.assertEqual(entrance["id"], "portal:0")
                self.assertEqual(entrance["object_index"], 0)
                self.assertEqual(entrance["position"], {"x": 6, "y": 5, "z": 0})
                self.assertEqual(entrance["anchor_position"], {"x": 7, "y": 5, "z": 0})
                self.assertEqual(
                    entrance["object_id"],
                    h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_ENTRANCE,
                )
                self.assertEqual(entrance["h3m_subid"], 2)
                self.assertEqual(
                    entrance["portal_type"],
                    h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                )
                self.assertEqual(entrance["role"], h3_map_parser.PORTAL_ROLE_ENTRANCE)
                self.assertEqual(entrance["channel_key"], "monolith-one-way:2")
                self.assertEqual(
                    payload["portal_edges"],
                    [
                        {
                            "source_id": "portal:0",
                            "destination_id": "portal:1",
                            "source_object_index": 0,
                            "destination_object_index": 1,
                            "portal_type": h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                            "channel_key": "monolith-one-way:2",
                            "h3m_subid": 2,
                        },
                    ],
                )

            self._with_server(check, app_state=app_state)

    def test_state_preserves_selected_hero_by_unambiguous_config_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(
                game_dir,
                "001.GM2",
                hero_name="Marius",
                name_offset=512,
            )
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            config_path.write_text(
                json.dumps({"last_hero": "marius"}) + "\n",
                encoding="utf-8",
            )
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                selected_hero_id="hero:256",
                config_path=config_path,
            )

            def check(base_url):
                status, payload = self._get_json(base_url, "/api/state")

                self.assertEqual(status, 200)
                self.assertEqual(payload["selected_hero_id"], "hero:512")
                self.assertEqual(app_state.selected_hero_id, "hero:512")

            self._with_server(check, app_state=app_state)

    def test_state_clears_selected_hero_when_config_name_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_multi_gui_save(
                game_dir,
                "001.GM2",
                (
                    {"hero_name": "Marius", "name_offset": 256, "position": (39, 69, 1)},
                    {"hero_name": "marius", "name_offset": 512, "position": (39, 71, 1)},
                ),
            )
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            config_path.write_text(
                json.dumps({"last_hero": "Marius"}) + "\n",
                encoding="utf-8",
            )
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                selected_hero_id="hero:999",
                config_path=config_path,
            )

            def check(base_url):
                status, payload = self._get_json(base_url, "/api/state")

                self.assertEqual(status, 200)
                self.assertIsNone(payload["selected_hero_id"])
                self.assertIsNone(app_state.selected_hero_id)

            self._with_server(check, app_state=app_state)

    def test_state_reuses_domain_snapshot_cache_for_unchanged_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                removed_neutral_cache=(
                    battle_estimator_gui.h3_save_parser.RemovedNeutralHistoryCache(
                        cache_dir=temp_path / "cache"
                    )
                ),
            )

            original_builder = battle_estimator_gui._build_domain_snapshot_from_source

            def check(base_url):
                with patch(
                    "tools.battle_estimator_gui._build_domain_snapshot_from_source",
                    wraps=original_builder,
                ) as wrapped_builder:
                    self._get_json(base_url, "/api/state")
                    self._get_json(base_url, "/api/state")

                    self.assertEqual(wrapped_builder.call_count, 1)

            self._with_server(check, app_state=app_state)

    def test_select_hero_reuses_cached_domain_snapshot_after_state_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
                removed_neutral_cache=(
                    battle_estimator_gui.h3_save_parser.RemovedNeutralHistoryCache(
                        cache_dir=temp_path / "cache"
                    )
                ),
            )

            original_builder = battle_estimator_gui._build_domain_snapshot_from_source

            def check(base_url):
                with patch(
                    "tools.battle_estimator_gui._build_domain_snapshot_from_source",
                    wraps=original_builder,
                ) as wrapped_builder:
                    _, state_payload = self._get_json(base_url, "/api/state")
                    self._post_json(
                        base_url,
                        "/api/select-hero",
                        {"hero_id": state_payload["heroes"][0]["id"]},
                    )

                    self.assertEqual(wrapped_builder.call_count, 1)

            self._with_server(check, app_state=app_state)

    def test_saves_endpoint_lists_numeric_saves_in_active_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            save_one = _write_gui_save(game_dir, "001.GM1", hero_name="One")
            save_two = _write_gui_save(game_dir, "002.GM2", hero_name="Two")
            (game_dir / "autosave.GM2").write_bytes(b"ignored")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                status, payload = self._get_json(base_url, "/api/saves")

                self.assertEqual(status, 200)
                self.assertEqual(payload["autosave_dir"], str(game_dir))
                self.assertEqual(payload["latest_save_file"], str(save_two))
                self.assertEqual(
                    [save["path"] for save in payload["saves"]],
                    [str(save_one), str(save_two)],
                )

            self._with_server(check, app_state=app_state)

    def test_saves_endpoint_orders_game_begin_before_hotseat_saves(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "2026.05.19 17;18 Diamond"
            game_dir.mkdir()
            game_begin = _write_gui_save(
                game_dir,
                "GAME_BEGIN.GM2",
                hero_name="Begin",
            )
            hotseat_111 = _write_gui_save(
                game_dir,
                "[hotseat] 111.GM2",
                hero_name="Hot111",
            )
            hotseat_112 = _write_gui_save(
                game_dir,
                "[hotseat] 112.GM2",
                hero_name="Hot112",
            )
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                status, saves_payload = self._get_json(base_url, "/api/saves")
                self.assertEqual(status, 200)
                self.assertEqual(saves_payload["latest_save_file"], str(hotseat_112))
                self.assertEqual(
                    [save["path"] for save in saves_payload["saves"]],
                    [str(game_begin), str(hotseat_111), str(hotseat_112)],
                )
                self.assertEqual(
                    [save["name"] for save in saves_payload["saves"]],
                    ["GAME_BEGIN.GM2", "111.GM2", "112.GM2"],
                )
                self.assertEqual(
                    [save["number"] for save in saves_payload["saves"]],
                    [battle_estimator_gui.h3_save_parser.GAME_BEGIN_SAVE_NUMBER, 111, 112],
                )

                status, state_payload = self._get_json(base_url, "/api/state")
                self.assertEqual(status, 200)
                self.assertEqual(state_payload["save_file"], str(hotseat_112))
                self.assertEqual(state_payload["heroes"][0]["name"], "Hot112")

            self._with_server(check, app_state=app_state)

    def test_saves_endpoint_and_follow_latest_ignore_numeric_symlinks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            other_dir = temp_path / "other"
            game_dir.mkdir()
            other_dir.mkdir()
            real_save = _write_gui_save(game_dir, "001.GM2", hero_name="Real")
            other_save = _write_gui_save(other_dir, "999.GM2", hero_name="Other")
            symlink_save = game_dir / "999.GM2"
            symlink_save.symlink_to(other_save)
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                status, saves_payload = self._get_json(base_url, "/api/saves")
                self.assertEqual(status, 200)
                self.assertEqual(
                    [save["path"] for save in saves_payload["saves"]],
                    [str(real_save)],
                )

                status, state_payload = self._get_json(base_url, "/api/state")
                self.assertEqual(status, 200)
                self.assertEqual(state_payload["save_file"], str(real_save))
                self.assertNotEqual(state_payload["save_file"], str(symlink_save))

            self._with_server(check, app_state=app_state)

    def test_game_folders_endpoint_lists_folders_with_numeric_saves(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "autosaves"
            root.mkdir()
            active_dir = root / "2026.05.18 10;00 Active"
            newer_dir = root / "2026.05.19 11;00 Newer"
            manual_dir = root / "Manual"
            empty_dir = root / "2026.05.20 12;00 Empty"
            active_dir.mkdir()
            newer_dir.mkdir()
            manual_dir.mkdir()
            empty_dir.mkdir()
            active_save = _write_gui_save(active_dir, "001.GM2", hero_name="Active")
            newer_save = _write_gui_save(newer_dir, "003.GM1", hero_name="Newer")
            manual_save = _write_gui_save(manual_dir, "002.GM2", hero_name="Manual")
            os.utime(active_save, ns=(2_000, 2_000))
            os.utime(newer_save, ns=(3_000, 3_000))
            os.utime(manual_save, ns=(1_000, 1_000))
            (root / "not-a-game.txt").write_text("ignored", encoding="utf-8")
            (empty_dir / "autosave.GM2").write_bytes(b"ignored")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=active_dir,
                map_file=map_path,
            )

            def check(base_url):
                status, payload = self._get_json(base_url, "/api/game-folders")

                self.assertEqual(status, 200)
                self.assertEqual(payload["autosave_root"], str(root))
                self.assertEqual(payload["active_autosave_dir"], str(active_dir))
                self.assertEqual(payload["latest_game_folder"], str(newer_dir))
                self.assertEqual(
                    [folder["path"] for folder in payload["game_folders"]],
                    [str(newer_dir), str(active_dir), str(manual_dir)],
                )
                self.assertEqual(
                    [folder["relative_path"] for folder in payload["game_folders"]],
                    [newer_dir.name, active_dir.name, manual_dir.name],
                )
                self.assertEqual(
                    [folder["latest_save_file"] for folder in payload["game_folders"]],
                    [str(newer_save), str(active_save), str(manual_save)],
                )
                self.assertEqual(
                    [folder["save_count"] for folder in payload["game_folders"]],
                    [1, 1, 1],
                )

            self._with_server(check, app_state=app_state)

    def test_game_folders_endpoint_scans_configured_games_root_recursively(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "Games"
            active_dir = root / "Random" / "PlayerTwo" / "2026.05.18 10;00 Active"
            latest_dir = root / "Hotseat" / "2026.05.19 17;18 Diamond"
            active_dir.mkdir(parents=True)
            latest_dir.mkdir(parents=True)
            active_save = _write_gui_save(active_dir, "001.GM2", hero_name="Active")
            latest_save = _write_gui_save(
                latest_dir,
                "[hotseat] 112.GM2",
                hero_name="Latest",
            )
            os.utime(active_save, ns=(1_000, 1_000))
            os.utime(latest_save, ns=(2_000, 2_000))
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=active_dir,
                map_file=map_path,
                config_path=config_path,
            )

            def check(base_url):
                status, payload = self._get_json(base_url, "/api/game-folders")

                self.assertEqual(status, 200)
                self.assertEqual(payload["autosave_root"], str(root))
                self.assertEqual(payload["latest_game_folder"], str(latest_dir))
                self.assertEqual(
                    [folder["relative_path"] for folder in payload["game_folders"]],
                    [
                        "Hotseat/2026.05.19 17;18 Diamond",
                        "Random/PlayerTwo/2026.05.18 10;00 Active",
                    ],
                )

                status, _, latest_payload = self._post_json(
                    base_url,
                    "/api/game-folder",
                    {"use_latest_game_folder": True},
                )
                config = battle_estimator_gui.h3_save_parser.load_config(config_path)

                self.assertEqual(status, 200)
                self.assertEqual(latest_payload["autosave_dir"], str(latest_dir))
                self.assertEqual(latest_payload["save_file"], str(latest_save))
                self.assertEqual(config.autosave_dir, latest_dir)
                self.assertEqual(app_state.autosave_dir, latest_dir)

            with patch.object(
                battle_estimator_gui.h3_save_parser,
                "DEFAULT_AUTOSAVE_ROOT",
                root,
            ):
                self._with_server(check, app_state=app_state)

    def test_game_folder_endpoint_switches_folder_and_persists_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            current_dir = temp_path / "current"
            next_dir = temp_path / "next"
            current_dir.mkdir()
            next_dir.mkdir()
            _write_gui_save(current_dir, "001.GM2", hero_name="Current")
            next_save = _write_gui_save(next_dir, "004.GM2", hero_name="Next")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            app_state = battle_estimator_gui.GuiAppState(
                mode=battle_estimator_gui.PINNED_MODE,
                autosave_dir=current_dir,
                save_file=current_dir / "001.GM2",
                map_file=map_path,
                selected_hero_id="hero:256",
                config_path=config_path,
            )

            def check(base_url):
                status, _, payload = self._post_json(
                    base_url,
                    "/api/game-folder",
                    {"autosave_dir": str(next_dir)},
                )
                config = battle_estimator_gui.h3_save_parser.load_config(config_path)

                self.assertEqual(status, 200)
                self.assertEqual(payload["mode"], battle_estimator_gui.FOLLOW_LATEST_MODE)
                self.assertEqual(payload["autosave_dir"], str(next_dir.resolve()))
                self.assertEqual(payload["save_file"], str(next_save.resolve()))
                self.assertIsNone(payload["selected_hero_id"])
                self.assertEqual(config.autosave_dir, next_dir.resolve())
                self.assertEqual(app_state.mode, battle_estimator_gui.FOLLOW_LATEST_MODE)
                self.assertEqual(app_state.autosave_dir, next_dir.resolve())
                self.assertIsNone(app_state.save_file)
                self.assertIsNone(app_state.selected_hero_id)

                status, saves_payload = self._get_json(base_url, "/api/saves")
                self.assertEqual(status, 200)
                self.assertEqual(saves_payload["autosave_dir"], str(next_dir.resolve()))
                self.assertEqual(
                    [save["path"] for save in saves_payload["saves"]],
                    [str(next_save.resolve())],
                )

            self._with_server(check, app_state=app_state)

    def test_game_folder_endpoint_can_switch_to_latest_game_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "autosaves"
            root.mkdir()
            older_dir = root / "2026.05.18 10;00 Older"
            latest_dir = root / "2026.05.19 11;00 Latest"
            older_dir.mkdir()
            latest_dir.mkdir()
            older_save = _write_gui_save(older_dir, "001.GM2", hero_name="Older")
            latest_save = _write_gui_save(latest_dir, "002.GM2", hero_name="Latest")
            os.utime(older_save, ns=(1_000, 1_000))
            os.utime(latest_save, ns=(2_000, 2_000))
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=older_dir,
                map_file=map_path,
                config_path=config_path,
            )

            def check(base_url):
                status, _, payload = self._post_json(
                    base_url,
                    "/api/game-folder",
                    {"use_latest_game_folder": True},
                )
                config = battle_estimator_gui.h3_save_parser.load_config(config_path)

                self.assertEqual(status, 200)
                self.assertEqual(payload["autosave_dir"], str(latest_dir))
                self.assertEqual(payload["save_file"], str(latest_save))
                self.assertEqual(config.autosave_dir, latest_dir)
                self.assertEqual(app_state.autosave_dir, latest_dir)

            self._with_server(check, app_state=app_state)

    def test_game_folder_endpoint_rejects_invalid_folder_without_mutating_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            empty_dir = temp_path / "empty"
            game_dir.mkdir()
            empty_dir.mkdir()
            save_path = _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            bad_file = temp_path / "not-folder.txt"
            bad_file.write_text("not a folder", encoding="utf-8")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            battle_estimator_gui.h3_save_parser.set_config_autosave_dir(
                game_dir,
                config_path,
            )
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )

            def check(base_url):
                for candidate in (bad_file, empty_dir, temp_path / "missing"):
                    with self.subTest(candidate=candidate):
                        with self.assertRaises(HTTPError) as raised:
                            self._post_json(
                                base_url,
                                "/api/game-folder",
                                {"autosave_dir": str(candidate)},
                            )

                        self.assertEqual(raised.exception.code, 400)

                config = battle_estimator_gui.h3_save_parser.load_config(config_path)
                self.assertEqual(app_state.autosave_dir, game_dir)
                self.assertEqual(config.autosave_dir, game_dir)
                status, payload = self._get_json(base_url, "/api/state")
                self.assertEqual(status, 200)
                self.assertEqual(payload["save_file"], str(save_path))

            self._with_server(check, app_state=app_state)

    def test_select_hero_endpoint_validates_id_and_persists_recent_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )

            def check(base_url):
                status, content_type, payload = self._post_json(
                    base_url,
                    "/api/select-hero",
                    {"hero_id": "hero:256"},
                )
                config = battle_estimator_gui.h3_save_parser.load_config(config_path)

                self.assertEqual(status, 200)
                self.assertEqual(content_type, "application/json")
                self.assertEqual(payload["selected_hero_id"], "hero:256")
                self.assertEqual(config.last_hero, "Isra")
                self.assertEqual(config.recent_heroes, ("Isra",))

            self._with_server(check, app_state=app_state)

    def test_hero_skills_endpoint_returns_starting_state_and_recommendations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )

            def check(base_url):
                status, _, payload = self._post_json(
                    base_url,
                    "/api/hero-skills",
                    {"hero_id": "hero:256"},
                )

                self.assertEqual(status, 200)
                self.assertEqual(payload["hero_id"], "hero:256")
                self.assertEqual(payload["role"], "main")
                self.assertEqual(payload["hero"]["key"], "isra")
                self.assertEqual(payload["hero"]["display_name"], "Isra")
                self.assertEqual(payload["hero"]["faction"], "necropolis")
                self.assertEqual(payload["current_skills_source"], "starting")
                self.assertEqual(
                    payload["current_skills"],
                    [
                        {
                            "skill": "necromancy",
                            "skill_id": "necromancy",
                            "display_name": "Necromancy",
                            "level": "advanced",
                        },
                    ],
                )
                self.assertEqual(payload["max_skills"], 8)
                self.assertEqual(payload["skill_levels"], ["basic", "advanced", "expert"])
                skill_ids = {skill["skill_id"] for skill in payload["skills"]}
                self.assertIn("earthMagic", skill_ids)
                self.assertEqual(payload["top_next"][0]["skill_id"], "necromancy")
                self.assertEqual(payload["top_next"][0]["target_level"], "expert")
                self.assertEqual(payload["top_next"][0]["tier"], "S")
                self.assertTrue(
                    any(entry["skill_id"] == "diplomacy" for entry in payload["avoid"])
                )
                self.assertIsNone(payload["offer_comparison"])

            self._with_server(check, app_state=app_state)

    def test_hero_skills_save_persists_manual_state_and_loads_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )

            def check(base_url):
                status, _, saved = self._post_json(
                    base_url,
                    "/api/hero-skills/save",
                    {
                        "hero_id": "hero:256",
                        "skills": [
                            {"skill": "earthMagic", "level": "basic"},
                            {"skill": "logistics", "level": "basic"},
                        ],
                    },
                )
                config = battle_estimator_gui.h3_save_parser.load_config(config_path)

                self.assertEqual(status, 200)
                self.assertEqual(saved["current_skills_source"], "manual")
                self.assertEqual(
                    [
                        (skill["skill_id"], skill["level"])
                        for skill in saved["current_skills"]
                    ],
                    [("earthMagic", "basic"), ("logistics", "basic")],
                )
                self.assertEqual(
                    config.manual_hero_current_skills_by_map[saved["map_key"]]["hero:256"],
                    (
                        hero_skill_recommender.CurrentSkill("earthMagic", "basic"),
                        hero_skill_recommender.CurrentSkill("logistics", "basic"),
                    ),
                )

                _, _, loaded = self._post_json(
                    base_url,
                    "/api/hero-skills",
                    {"hero_id": "hero:256"},
                )
                self.assertEqual(loaded["current_skills_source"], "manual")
                self.assertEqual(loaded["current_skills"], saved["current_skills"])

            self._with_server(check, app_state=app_state)

    def test_hero_skills_reset_clears_manual_state_and_returns_starting_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )

            def check(base_url):
                self._post_json(
                    base_url,
                    "/api/hero-skills/save",
                    {
                        "hero_id": "hero:256",
                        "skills": [
                            {"skill": "earthMagic", "level": "basic"},
                        ],
                    },
                )

                status, _, reset = self._post_json(
                    base_url,
                    "/api/hero-skills/reset",
                    {"hero_id": "hero:256"},
                )
                config = battle_estimator_gui.h3_save_parser.load_config(config_path)

                self.assertEqual(status, 200)
                self.assertEqual(reset["current_skills_source"], "starting")
                self.assertEqual(
                    [
                        (skill["skill_id"], skill["level"])
                        for skill in reset["current_skills"]
                    ],
                    [("necromancy", "advanced")],
                )
                self.assertEqual(config.manual_hero_current_skills_by_map, {})

            self._with_server(check, app_state=app_state)

    def test_hero_skills_compare_endpoint_returns_offer_comparison(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                status, _, payload = self._post_json(
                    base_url,
                    "/api/hero-skills/compare",
                    {
                        "hero_id": "hero:256",
                        "offers": [
                            {"skill": "earthMagic", "level": "basic"},
                            {"skill": "necromancy", "level": "expert"},
                        ],
                    },
                )
                comparison = payload["offer_comparison"]

                self.assertEqual(status, 200)
                self.assertEqual(comparison["winner"], "necromancy:expert")
                self.assertIn("higher_score", comparison["reason_codes"])
                self.assertEqual(
                    [offer["skill_id"] for offer in comparison["offers"]],
                    ["earthMagic", "necromancy"],
                )

                _, _, unavailable_payload = self._post_json(
                    base_url,
                    "/api/hero-skills/compare",
                    {
                        "hero_id": "hero:256",
                        "offers": [
                            {"skill": "necromancy", "level": "basic"},
                            {"skill": "earthMagic", "level": "basic"},
                        ],
                    },
                )
                unavailable_offer = unavailable_payload["offer_comparison"]["offers"][0]
                self.assertEqual(unavailable_offer["availability"], "unavailable")
                self.assertIn("illegal_upgrade_level", unavailable_offer["reason_codes"])

            self._with_server(check, app_state=app_state)

    def test_hero_skills_endpoint_rejects_invalid_hero_requests(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                with self.assertRaises(HTTPError) as missing_hero:
                    self._post_json(base_url, "/api/hero-skills", {})
                self.assertEqual(missing_hero.exception.code, 400)

                with self.assertRaises(HTTPError) as malformed_hero:
                    self._post_json(
                        base_url,
                        "/api/hero-skills",
                        {"hero_id": "bad"},
                    )
                self.assertEqual(malformed_hero.exception.code, 400)
                malformed_payload = json.loads(
                    malformed_hero.exception.read().decode("utf-8")
                )
                self.assertIn("hero:<stable_id>", malformed_payload["error"])

                with self.assertRaises(HTTPError) as unknown_hero:
                    self._post_json(
                        base_url,
                        "/api/hero-skills",
                        {"hero_id": "hero:999"},
                    )
                self.assertEqual(unknown_hero.exception.code, 404)

                with self.assertRaises(HTTPError) as unknown_role:
                    self._post_json(
                        base_url,
                        "/api/hero-skills",
                        {"hero_id": "hero:256", "role": "side"},
                    )
                self.assertEqual(unknown_role.exception.code, 400)
                role_payload = json.loads(
                    unknown_role.exception.read().decode("utf-8")
                )
                self.assertIn("unknown role", role_payload["error"])

            self._with_server(check, app_state=app_state)

    def test_hero_skills_endpoint_maps_recommender_load_errors_to_bad_request(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                with patch(
                    "tools.battle_estimator_gui.hero_skill_recommender.load_recommendation_rules",
                    side_effect=OSError("cannot read rules"),
                ):
                    with self.assertRaises(HTTPError) as raised:
                        self._post_json(
                            base_url,
                            "/api/hero-skills",
                            {"hero_id": "hero:256"},
                        )

                self.assertEqual(raised.exception.code, 400)
                payload = json.loads(raised.exception.read().decode("utf-8"))
                self.assertIn("invalid hero skill recommendation data", payload["error"])
                self.assertIn("cannot read rules", payload["error"])

            self._with_server(check, app_state=app_state)

    def test_hero_skills_endpoint_rejects_unresolved_standard_hero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Tiny")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                with self.assertRaises(HTTPError) as unresolved:
                    self._post_json(
                        base_url,
                        "/api/hero-skills",
                        {"hero_id": "hero:256"},
                    )

                self.assertEqual(unresolved.exception.code, 400)
                payload = json.loads(unresolved.exception.read().decode("utf-8"))
                self.assertIn("unknown standard hero", payload["error"])

            self._with_server(check, app_state=app_state)

    def test_hero_skills_save_and_compare_reject_invalid_payloads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                with self.assertRaises(HTTPError) as invalid_skills_shape:
                    self._post_json(
                        base_url,
                        "/api/hero-skills/save",
                        {"hero_id": "hero:256", "skills": "bad"},
                    )
                self.assertEqual(invalid_skills_shape.exception.code, 400)

                with self.assertRaises(HTTPError) as unknown_skill:
                    self._post_json(
                        base_url,
                        "/api/hero-skills/save",
                        {
                            "hero_id": "hero:256",
                            "skills": [
                                {"skill": "unknownSkill", "level": "basic"},
                            ],
                        },
                    )
                self.assertEqual(unknown_skill.exception.code, 400)

                invalid_compare_cases = (
                    ({}, "offers must be a list"),
                    ({"offers": [{"skill": "earthMagic", "level": "basic"}]}, "at least two"),
                    (
                        {
                            "offers": [
                                {"skill": "earthMagic", "level": "basic"},
                                {"skill": "earthMagic", "level": "basic"},
                            ],
                        },
                        "duplicate",
                    ),
                    (
                        {
                            "offers": [
                                {"skill": "earthMagic", "level": "wrong"},
                                {"skill": "necromancy", "level": "expert"},
                            ],
                        },
                        "skill level",
                    ),
                )
                for payload, expected_error in invalid_compare_cases:
                    with self.subTest(expected_error=expected_error):
                        payload = {"hero_id": "hero:256", **payload}
                        with self.assertRaises(HTTPError) as raised:
                            self._post_json(
                                base_url,
                                "/api/hero-skills/compare",
                                payload,
                            )
                        self.assertEqual(raised.exception.code, 400)
                        error_payload = json.loads(
                            raised.exception.read().decode("utf-8")
                        )
                        self.assertIn(expected_error, error_payload["error"])

            self._with_server(check, app_state=app_state)

    def test_save_mode_endpoint_supports_pinned_and_follow_latest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            pinned_save = _write_gui_save(game_dir, "001.GM1", hero_name="Pinned")
            latest_save = _write_gui_save(game_dir, "002.GM2", hero_name="Latest")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                status, _, pinned_payload = self._post_json(
                    base_url,
                    "/api/save-mode",
                    {
                        "mode": battle_estimator_gui.PINNED_MODE,
                        "save_file": str(pinned_save),
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(pinned_payload["mode"], battle_estimator_gui.PINNED_MODE)
                self.assertEqual(pinned_payload["save_file"], str(pinned_save))

                status, _, latest_payload = self._post_json(
                    base_url,
                    "/api/save-mode",
                    {"mode": battle_estimator_gui.FOLLOW_LATEST_MODE},
                )
                self.assertEqual(status, 200)
                self.assertEqual(latest_payload["mode"], battle_estimator_gui.FOLLOW_LATEST_MODE)
                self.assertEqual(latest_payload["save_file"], str(latest_save))

            self._with_server(check, app_state=app_state)

    def test_save_mode_rejects_pinned_save_outside_active_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            other_dir = temp_path / "other"
            game_dir.mkdir()
            other_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            other_save = _write_gui_save(other_dir, "001.GM2", hero_name="Other")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                with self.assertRaises(HTTPError) as raised:
                    self._post_json(
                        base_url,
                        "/api/save-mode",
                        {
                            "mode": battle_estimator_gui.PINNED_MODE,
                            "save_file": str(other_save),
                        },
                    )

                self.assertEqual(raised.exception.code, 400)
                payload = json.loads(raised.exception.read().decode("utf-8"))
                self.assertIn("active autosave folder", payload["error"])

            self._with_server(check, app_state=app_state)

    def test_save_mode_rejects_pinned_save_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            other_dir = temp_path / "other"
            game_dir.mkdir()
            other_dir.mkdir()
            _write_gui_save(game_dir, "002.GM2", hero_name="Isra")
            other_save = _write_gui_save(other_dir, "001.GM2", hero_name="Other")
            symlink_save = game_dir / "001.GM2"
            symlink_save.symlink_to(other_save)
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                with self.assertRaises(HTTPError) as raised:
                    self._post_json(
                        base_url,
                        "/api/save-mode",
                        {
                            "mode": battle_estimator_gui.PINNED_MODE,
                            "save_file": str(symlink_save),
                        },
                    )

                self.assertEqual(raised.exception.code, 400)
                payload = json.loads(raised.exception.read().decode("utf-8"))
                self.assertIn("symlink", payload["error"])

            self._with_server(check, app_state=app_state)

    def test_simulate_target_endpoint_returns_compact_estimate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra", position=(39, 69, 1))
            map_path = _write_h3m_map(temp_path / "map.h3m", position=(39, 70, 1))
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                with patch.object(
                    battle_estimator_gui.battle_estimator,
                    "run_simulations",
                    return_value=91.5,
                ) as run_mock:
                    status, _, payload = self._post_json(
                        base_url,
                        "/api/simulate-target",
                        {
                            "hero_id": "hero:256",
                            "target_id": "neutral:0",
                            "simulations": 12,
                        },
                    )

                self.assertEqual(status, 200)
                self.assertEqual(payload["target_id"], "neutral:0")
                self.assertEqual(payload["estimate"]["win_pct"], 91.5)
                self.assertEqual(payload["estimate"]["target"]["creature_name"], "Gnoll")
                self.assertEqual(run_mock.call_args.args[2], 12)

            self._with_server(check, app_state=app_state)

    def test_hidden_neutral_target_api_filters_state_and_scan_per_map(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra", position=(39, 69, 1))
            map_path = _write_h3m_map(temp_path / "map.h3m", position=(39, 70, 1))
            config_path = temp_path / "config.json"
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )

            def check(base_url):
                status, state = self._get_json(base_url, "/api/state")
                self.assertEqual(status, 200)
                self.assertEqual([target["id"] for target in state["neutral_targets"]], ["neutral:0"])
                self.assertFalse(state["neutral_targets"][0]["hidden"])
                self.assertFalse(state["show_hidden"])
                self.assertEqual(state["hidden_neutral_target_ids"], [])

                status, _, hidden_payload = self._post_json(
                    base_url,
                    "/api/hidden-target",
                    {"target_id": "neutral:0", "hidden": True},
                )
                config = battle_estimator_gui.h3_save_parser.load_config(config_path)
                map_key = hidden_payload["map_key"]

                self.assertEqual(status, 200)
                self.assertTrue(hidden_payload["hidden"])
                self.assertEqual(hidden_payload["hidden_neutral_target_ids"], ["neutral:0"])
                self.assertEqual(
                    config.hidden_neutral_targets_by_map[map_key],
                    ("neutral:0",),
                )

                _, state = self._get_json(base_url, "/api/state")
                self.assertEqual(state["neutral_targets"], [])
                self.assertFalse(state["show_hidden"])
                self.assertEqual(state["hidden_neutral_target_ids"], ["neutral:0"])

                with self.assertRaises(HTTPError) as hidden_simulation:
                    self._post_json(
                        base_url,
                        "/api/simulate-target",
                        {"hero_id": "hero:256", "target_id": "neutral:0"},
                    )
                self.assertEqual(hidden_simulation.exception.code, 404)

                with patch.object(
                    battle_estimator_gui.battle_estimator,
                    "run_simulations",
                    return_value=91.5,
                ) as run_mock:
                    _, _, scan_payload = self._post_json(
                        base_url,
                        "/api/scan-radius",
                        {
                            "hero_id": "hero:256",
                            "radius": 2,
                            "target_type": "neutral",
                            "simulations": 7,
                        },
                    )
                self.assertEqual(scan_payload["results"], [])
                run_mock.assert_not_called()

                status, _, shown_state = self._post_json(
                    base_url,
                    "/api/show-hidden",
                    {"show_hidden": True},
                )
                self.assertEqual(status, 200)
                self.assertTrue(shown_state["show_hidden"])
                self.assertEqual([target["id"] for target in shown_state["neutral_targets"]], ["neutral:0"])
                self.assertTrue(shown_state["neutral_targets"][0]["hidden"])

                with patch.object(
                    battle_estimator_gui.battle_estimator,
                    "run_simulations",
                    return_value=91.5,
                ) as run_mock:
                    _, _, scan_payload = self._post_json(
                        base_url,
                        "/api/scan-radius",
                        {
                            "hero_id": "hero:256",
                            "radius": 2,
                            "target_type": "neutral",
                            "simulations": 7,
                        },
                    )
                self.assertEqual(scan_payload["results"], [])
                run_mock.assert_not_called()

                status, _, unhidden_payload = self._post_json(
                    base_url,
                    "/api/hidden-target",
                    {"target_id": "neutral:0", "hidden": False},
                )
                self.assertEqual(status, 200)
                self.assertFalse(unhidden_payload["hidden"])
                self.assertEqual(unhidden_payload["hidden_neutral_target_ids"], [])

            self._with_server(check, app_state=app_state)

    def test_hidden_hero_target_api_filters_state_and_scan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_multi_gui_save(
                game_dir,
                "001.GM2",
                (
                    {"hero_name": "Isra", "name_offset": 256, "position": (39, 69, 1)},
                    {
                        "hero_name": "Marius",
                        "name_offset": 512,
                        "position": (39, 71, 1),
                        "owner_color_id": 2,
                    },
                ),
            )
            map_path = _write_h3m_map(temp_path / "map.h3m", position=(39, 70, 1))
            config_path = temp_path / "config.json"
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                selected_hero_id="hero:256",
                config_path=config_path,
            )

            def check(base_url):
                status, state = self._get_json(base_url, "/api/state")
                heroes_by_id = {hero["id"]: hero for hero in state["heroes"]}

                self.assertEqual(status, 200)
                self.assertEqual(state["selected_hero_id"], "hero:256")
                self.assertEqual(state["hidden_hero_target_ids"], [])
                self.assertFalse(heroes_by_id["hero:512"]["hidden"])
                self.assertFalse(state["show_hidden"])

                status, _, hidden_payload = self._post_json(
                    base_url,
                    "/api/hidden-target",
                    {"target_id": "hero:512", "hidden": True},
                )
                config = battle_estimator_gui.h3_save_parser.load_config(config_path)
                map_key = hidden_payload["map_key"]

                self.assertEqual(status, 200)
                self.assertTrue(hidden_payload["hidden"])
                self.assertEqual(hidden_payload["hidden_hero_target_ids"], ["hero:512"])
                self.assertEqual(
                    config.hidden_hero_targets_by_map[map_key],
                    ("hero:512",),
                )

                _, state = self._get_json(base_url, "/api/state")
                heroes_by_id = {hero["id"]: hero for hero in state["heroes"]}
                self.assertEqual(state["hidden_hero_target_ids"], ["hero:512"])
                self.assertTrue(heroes_by_id["hero:512"]["hidden"])
                self.assertFalse(heroes_by_id["hero:256"]["hidden"])

                with self.assertRaises(HTTPError) as hidden_simulation:
                    self._post_json(
                        base_url,
                        "/api/simulate-target",
                        {"hero_id": "hero:256", "target_id": "hero:512"},
                    )
                self.assertEqual(hidden_simulation.exception.code, 404)

                with patch.object(
                    battle_estimator_gui.battle_estimator,
                    "run_simulations",
                    return_value=72.0,
                ) as run_mock:
                    _, _, scan_payload = self._post_json(
                        base_url,
                        "/api/scan-radius",
                        {
                            "hero_id": "hero:256",
                            "radius": 2,
                            "target_type": "hero",
                            "simulations": 7,
                        },
                    )
                self.assertEqual(scan_payload["results"], [])
                run_mock.assert_not_called()

                status, _, shown_state = self._post_json(
                    base_url,
                    "/api/show-hidden",
                    {"show_hidden": True},
                )
                heroes_by_id = {hero["id"]: hero for hero in shown_state["heroes"]}
                self.assertEqual(status, 200)
                self.assertTrue(shown_state["show_hidden"])
                self.assertEqual(shown_state["hidden_hero_target_ids"], ["hero:512"])
                self.assertTrue(heroes_by_id["hero:512"]["hidden"])

                with patch.object(
                    battle_estimator_gui.battle_estimator,
                    "run_simulations",
                    return_value=72.0,
                ) as run_mock:
                    _, _, scan_payload = self._post_json(
                        base_url,
                        "/api/scan-radius",
                        {
                            "hero_id": "hero:256",
                            "radius": 2,
                            "target_type": "hero",
                            "simulations": 7,
                        },
                    )
                self.assertEqual(scan_payload["results"], [])
                run_mock.assert_not_called()

                with patch.object(
                    battle_estimator_gui.battle_estimator,
                    "run_simulations",
                    return_value=72.0,
                ):
                    status, _, simulation_payload = self._post_json(
                        base_url,
                        "/api/simulate-target",
                        {
                            "hero_id": "hero:256",
                            "target_id": "hero:512",
                            "simulations": 9,
                        },
                    )
                self.assertEqual(status, 200)
                self.assertEqual(simulation_payload["target_id"], "hero:512")
                self.assertEqual(simulation_payload["estimate"]["target_type"], "hero")

                status, _, unhidden_payload = self._post_json(
                    base_url,
                    "/api/hidden-target",
                    {"target_id": "hero:512", "hidden": False},
                )
                self.assertEqual(status, 200)
                self.assertFalse(unhidden_payload["hidden"])
                self.assertEqual(unhidden_payload["hidden_hero_target_ids"], [])

            self._with_server(check, app_state=app_state)

    def test_hidden_hero_target_persistence_is_per_map(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_multi_gui_save(
                game_dir,
                "001.GM2",
                (
                    {"hero_name": "Isra", "name_offset": 256, "position": (39, 69, 1)},
                    {
                        "hero_name": "Marius",
                        "name_offset": 512,
                        "position": (39, 71, 1),
                        "owner_color_id": 2,
                    },
                ),
            )
            map_one = _write_h3m_map(temp_path / "map-one.h3m", position=(39, 70, 1))
            map_two = _write_h3m_map(temp_path / "map-two.h3m", position=(39, 70, 1))
            config_path = temp_path / "config.json"
            first_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_one,
                selected_hero_id="hero:256",
                config_path=config_path,
            )

            def hide_on_first_map(base_url):
                status, _, payload = self._post_json(
                    base_url,
                    "/api/hidden-target",
                    {"target_id": "hero:512", "hidden": True},
                )

                self.assertEqual(status, 200)
                self.assertEqual(payload["hidden_hero_target_ids"], ["hero:512"])

            self._with_server(hide_on_first_map, app_state=first_state)

            second_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_two,
                selected_hero_id="hero:256",
                config_path=config_path,
            )

            def check_second_map(base_url):
                status, state = self._get_json(base_url, "/api/state")
                heroes_by_id = {hero["id"]: hero for hero in state["heroes"]}
                config = battle_estimator_gui.h3_save_parser.load_config(config_path)

                self.assertEqual(status, 200)
                self.assertEqual(state["hidden_hero_target_ids"], [])
                self.assertFalse(heroes_by_id["hero:512"]["hidden"])
                self.assertEqual(len(config.hidden_hero_targets_by_map), 1)

            self._with_server(check_second_map, app_state=second_state)

    def test_simulate_target_endpoint_supports_hero_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_multi_gui_save(
                game_dir,
                "001.GM2",
                (
                    {"hero_name": "Isra", "name_offset": 256, "position": (39, 69, 1)},
                    {
                        "hero_name": "Marius",
                        "name_offset": 512,
                        "position": (39, 71, 1),
                        "owner_color_id": 2,
                    },
                ),
            )
            map_path = _write_h3m_map(temp_path / "map.h3m", position=(39, 70, 1))
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                with patch.object(
                    battle_estimator_gui.battle_estimator,
                    "run_simulations",
                    return_value=72.0,
                ):
                    status, _, payload = self._post_json(
                        base_url,
                        "/api/simulate-target",
                        {
                            "hero_id": "hero:256",
                            "target_id": "hero:512",
                            "simulations": 9,
                        },
                    )

                self.assertEqual(status, 200)
                self.assertEqual(payload["hero_id"], "hero:256")
                self.assertEqual(payload["target_id"], "hero:512")
                self.assertEqual(payload["estimate"]["target_id"], "hero:512")
                self.assertEqual(payload["estimate"]["target_type"], "hero")
                self.assertEqual(payload["estimate"]["target"]["name"], "Marius")
                self.assertEqual(payload["estimate"]["enemy_army"][0]["creature_name"], "Skeleton Warrior")
                self.assertEqual(payload["estimate"]["win_pct"], 72.0)
                self.assertEqual(payload["estimate"]["note"], "army-only")

            self._with_server(check, app_state=app_state)

    def test_scan_radius_endpoint_returns_distance_sorted_neutral_and_hero_results(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_multi_gui_save(
                game_dir,
                "001.GM2",
                (
                    {"hero_name": "Isra", "name_offset": 256, "position": (39, 69, 1)},
                    {
                        "hero_name": "Marius",
                        "name_offset": 512,
                        "position": (39, 71, 1),
                        "owner_color_id": 2,
                    },
                ),
            )
            map_path = _write_h3m_map(temp_path / "map.h3m", position=(39, 70, 1))
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                with patch.object(
                    battle_estimator_gui.battle_estimator,
                    "run_simulations",
                    side_effect=(91.5, 72.0),
                ):
                    status, _, payload = self._post_json(
                        base_url,
                        "/api/scan-radius",
                        {
                            "hero_id": "hero:256",
                            "radius": 2,
                            "target_type": "all",
                            "simulations": 7,
                        },
                    )

                self.assertEqual(status, 200)
                self.assertEqual(
                    [(item["target_id"], item["distance"], item["win_pct"]) for item in payload["results"]],
                    [("neutral:0", 1, 91.5), ("hero:512", 2, 72.0)],
                )
                self.assertEqual(payload["results"][1]["target"]["name"], "Marius")

            self._with_server(check, app_state=app_state)

    def test_scan_radius_endpoint_supports_hero_target_filter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_multi_gui_save(
                game_dir,
                "001.GM2",
                (
                    {"hero_name": "Isra", "name_offset": 256, "position": (39, 69, 1)},
                    {
                        "hero_name": "Marius",
                        "name_offset": 512,
                        "position": (39, 71, 1),
                        "owner_color_id": 2,
                    },
                ),
            )
            map_path = _write_h3m_map(temp_path / "map.h3m", position=(39, 70, 1))
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                with patch.object(
                    battle_estimator_gui.battle_estimator,
                    "run_simulations",
                    return_value=72.0,
                ):
                    status, _, payload = self._post_json(
                        base_url,
                        "/api/scan-radius",
                        {
                            "hero_id": "hero:256",
                            "radius": 2,
                            "target_type": "hero",
                            "simulations": 7,
                        },
                    )

                self.assertEqual(status, 200)
                self.assertEqual([item["target_id"] for item in payload["results"]], ["hero:512"])

            self._with_server(check, app_state=app_state)

    def test_path_route_endpoint_accepts_explicit_target_position(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra", position=(0, 0, 0))
            map_path = _write_empty_h3m_map(temp_path / "map.h3m", map_size=3)
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                status, _, payload = self._post_json(
                    base_url,
                    "/api/path-route",
                    {
                        "hero_id": "hero:256",
                        "target_position": {"x": 2, "y": 0, "z": 0},
                    },
                )

                self.assertEqual(status, 200)
                self.assertEqual(payload["hero_id"], "hero:256")
                self.assertEqual(payload["status"], battle_estimator_gui.PATH_STATUS_FOUND)
                self.assertEqual(
                    [step["position"] for step in payload["steps"]],
                    [
                        {"x": 0, "y": 0, "z": 0},
                        {"x": 1, "y": 0, "z": 0},
                        {"x": 2, "y": 0, "z": 0},
                    ],
                )
                self.assertEqual(payload["segments"][0]["segment_type"], "walk")
                self.assertIsNone(payload["message"])

            self._with_server(check, app_state=app_state)

    def test_path_route_endpoint_accepts_neutral_marker_target_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra", position=(0, 0, 0))
            map_path = _write_h3m_map(
                temp_path / "map.h3m",
                position=(0, 0, 0),
            )
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                status, _, payload = self._post_json(
                    base_url,
                    "/api/path-route",
                    {
                        "hero_id": "hero:256",
                        "target_id": "neutral:0",
                    },
                )

                self.assertEqual(status, 200)
                self.assertEqual(payload["target_id"], "neutral:0")
                self.assertEqual(payload["status"], battle_estimator_gui.PATH_STATUS_FOUND)
                self.assertEqual(
                    payload["requested_target_position"],
                    {"x": 0, "y": 0, "z": 0},
                )

            self._with_server(check, app_state=app_state)

    def test_path_route_endpoint_accepts_town_and_portal_marker_ids(self):
        cases = (
            ("town:0", _write_h3m_map_with_town),
            ("portal:0", _write_h3m_map_with_portals),
        )
        for target_id, map_writer in cases:
            with self.subTest(target_id=target_id):
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_path = Path(temp_dir)
                    game_dir = temp_path / "game"
                    game_dir.mkdir()
                    _write_gui_save(
                        game_dir,
                        "001.GM2",
                        hero_name="Isra",
                        position=(0, 0, 0),
                    )
                    map_path = map_writer(temp_path / "map.h3m")
                    app_state = battle_estimator_gui.GuiAppState(
                        autosave_dir=game_dir,
                        map_file=map_path,
                    )

                    def check(base_url):
                        status, _, payload = self._post_json(
                            base_url,
                            "/api/path-route",
                            {
                                "hero_id": "hero:256",
                                "target_id": target_id,
                            },
                        )

                        self.assertEqual(status, 200)
                        self.assertEqual(payload["target_id"], target_id)
                        self.assertEqual(
                            payload["status"],
                            battle_estimator_gui.PATH_STATUS_FOUND,
                        )

                    self._with_server(check, app_state=app_state)

    def test_path_route_endpoint_honors_hidden_neutral_visibility(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra", position=(0, 0, 0))
            map_path = _write_h3m_map(
                temp_path / "map.h3m",
                position=(0, 0, 0),
            )
            config_path = temp_path / "config.json"
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )

            def check(base_url):
                self._post_json(
                    base_url,
                    "/api/hidden-target",
                    {"target_id": "neutral:0", "hidden": True},
                )
                with self.assertRaises(HTTPError) as hidden:
                    self._post_json(
                        base_url,
                        "/api/path-route",
                        {
                            "hero_id": "hero:256",
                            "target_id": "neutral:0",
                        },
                    )
                self.assertEqual(hidden.exception.code, 404)

                self._post_json(
                    base_url,
                    "/api/show-hidden",
                    {"show_hidden": True},
                )
                status, _, payload = self._post_json(
                    base_url,
                    "/api/path-route",
                    {
                        "hero_id": "hero:256",
                        "target_id": "neutral:0",
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(payload["target_id"], "neutral:0")

            self._with_server(check, app_state=app_state)

    def test_path_route_endpoint_honors_hidden_hero_visibility(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_multi_gui_save(
                game_dir,
                "001.GM2",
                (
                    {"hero_name": "Isra", "name_offset": 256, "position": (0, 0, 0)},
                    {
                        "hero_name": "Marius",
                        "name_offset": 512,
                        "position": (2, 0, 0),
                        "owner_color_id": 2,
                    },
                ),
            )
            map_path = _write_empty_h3m_map(temp_path / "map.h3m", map_size=3)
            config_path = temp_path / "config.json"
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                selected_hero_id="hero:256",
                config_path=config_path,
            )

            def check(base_url):
                self._post_json(
                    base_url,
                    "/api/hidden-target",
                    {"target_id": "hero:512", "hidden": True},
                )
                with self.assertRaises(HTTPError) as hidden:
                    self._post_json(
                        base_url,
                        "/api/path-route",
                        {
                            "hero_id": "hero:256",
                            "target_id": "hero:512",
                        },
                    )
                self.assertEqual(hidden.exception.code, 404)

                self._post_json(
                    base_url,
                    "/api/show-hidden",
                    {"show_hidden": True},
                )
                status, _, payload = self._post_json(
                    base_url,
                    "/api/path-route",
                    {
                        "hero_id": "hero:256",
                        "target_id": "hero:512",
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(payload["target_id"], "hero:512")

            self._with_server(check, app_state=app_state)

    def test_path_route_endpoint_serializes_not_found_and_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra", position=(0, 0, 0))
            map_path = _write_empty_h3m_map(temp_path / "map.h3m", map_size=2)
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                not_found = battle_estimator_gui.PathfindingResult(
                    battle_estimator_gui.PATH_STATUS_NOT_FOUND,
                    requested_target_position=(1, 0, 0),
                    message="no land path found",
                )
                fallback = battle_estimator_gui.PathfindingResult(
                    battle_estimator_gui.PATH_STATUS_FOUND,
                    requested_target_position=(1, 0, 0),
                    resolved_target_position=(0, 0, 0),
                    steps=(battle_estimator_gui.PathfindingStep((0, 0, 0)),),
                    segments=(
                        battle_estimator_gui.PathfindingSegment(
                            battle_estimator_gui.PATH_SEGMENT_WALK,
                            (0, 0, 0),
                            (0, 0, 0),
                            steps=(
                                battle_estimator_gui.PathfindingStep((0, 0, 0)),
                            ),
                        ),
                    ),
                    message="resolved target to reachable neighbor (0, 0, 0)",
                )
                with patch.object(
                    battle_estimator_gui,
                    "find_path_route",
                    side_effect=(not_found, fallback),
                ):
                    status, _, missing_payload = self._post_json(
                        base_url,
                        "/api/path-route",
                        {
                            "hero_id": "hero:256",
                            "target_position": {"x": 1, "y": 0, "z": 0},
                        },
                    )
                    status, _, fallback_payload = self._post_json(
                        base_url,
                        "/api/path-route",
                        {
                            "hero_id": "hero:256",
                            "target_position": {"x": 1, "y": 0, "z": 0},
                        },
                    )

                self.assertEqual(status, 200)
                self.assertEqual(
                    missing_payload["status"],
                    battle_estimator_gui.PATH_STATUS_NOT_FOUND,
                )
                self.assertEqual(missing_payload["message"], "no land path found")
                self.assertEqual(fallback_payload["resolved_target_position"], {"x": 0, "y": 0, "z": 0})
                self.assertIn("reachable neighbor", fallback_payload["message"])

            self._with_server(check, app_state=app_state)

    def test_path_route_endpoint_serializes_portal_segment_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra", position=(0, 0, 0))
            map_path = _write_empty_h3m_map(temp_path / "map.h3m", map_size=2)
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                portal_edge = battle_estimator_gui.PathfindingPortalEdge(
                    source_id="portal:0",
                    destination_id="portal:1",
                    source_position=(0, 0, 0),
                    destination_position=(1, 0, 0),
                    portal_type=h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                    channel_key="monolith-one-way:1",
                    is_non_deterministic=True,
                )
                portal_result = battle_estimator_gui.PathfindingResult(
                    battle_estimator_gui.PATH_STATUS_FOUND,
                    requested_target_position=(1, 0, 0),
                    resolved_target_position=(1, 0, 0),
                    steps=(
                        battle_estimator_gui.PathfindingStep((0, 0, 0)),
                        battle_estimator_gui.PathfindingStep((1, 0, 0)),
                    ),
                    segments=(
                        battle_estimator_gui.PathfindingSegment(
                            battle_estimator_gui.PATH_SEGMENT_PORTAL,
                            (0, 0, 0),
                            (1, 0, 0),
                            steps=(
                                battle_estimator_gui.PathfindingStep((0, 0, 0)),
                                battle_estimator_gui.PathfindingStep((1, 0, 0)),
                            ),
                            portal_edge=portal_edge,
                        ),
                    ),
                )
                with patch.object(
                    battle_estimator_gui,
                    "find_path_route",
                    return_value=portal_result,
                ):
                    status, _, payload = self._post_json(
                        base_url,
                        "/api/path-route",
                        {
                            "hero_id": "hero:256",
                            "target_position": {"x": 1, "y": 0, "z": 0},
                        },
                    )

                self.assertEqual(status, 200)
                segment = payload["segments"][0]
                self.assertEqual(segment["segment_type"], "portal")
                self.assertTrue(segment["is_non_deterministic"])
                self.assertEqual(segment["portal_edge"]["source_id"], "portal:0")
                self.assertEqual(segment["portal_edge"]["destination_id"], "portal:1")
                self.assertTrue(segment["portal_edge"]["is_non_deterministic"])

            self._with_server(check, app_state=app_state)

    def test_path_route_endpoint_rejects_hero_without_position(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra", position=None)
            map_path = _write_empty_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                with self.assertRaises(HTTPError) as raised:
                    self._post_json(
                        base_url,
                        "/api/path-route",
                        {
                            "hero_id": "hero:256",
                            "target_position": {"x": 0, "y": 0, "z": 0},
                        },
                    )

                self.assertEqual(raised.exception.code, 400)
                body = json.loads(raised.exception.read().decode("utf-8"))
                self.assertIn("no parsed position", body["error"])

            self._with_server(check, app_state=app_state)

    def test_path_route_endpoint_rejects_invalid_hero_and_target_payloads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra", position=(0, 0, 0))
            map_path = _write_empty_h3m_map(temp_path / "map.h3m", map_size=2)
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                invalid_requests = (
                    (
                        {
                            "hero_id": "hero:missing",
                            "target_position": {"x": 0, "y": 0, "z": 0},
                        },
                        404,
                        "unknown hero_id",
                    ),
                    (
                        {"hero_id": "hero:256"},
                        400,
                        "exactly one",
                    ),
                    (
                        {
                            "hero_id": "hero:256",
                            "target_position": {"x": 0, "y": 0, "z": 0},
                            "target_id": "neutral:0",
                        },
                        400,
                        "exactly one",
                    ),
                    (
                        {"hero_id": "hero:256", "target_id": "neutral:999"},
                        404,
                        "unknown target_id",
                    ),
                    (
                        {"hero_id": "hero:256", "target_position": None},
                        400,
                        "path position is required",
                    ),
                )
                for payload, expected_code, expected_error in invalid_requests:
                    with self.subTest(expected_error=expected_error):
                        with self.assertRaises(HTTPError) as raised:
                            self._post_json(base_url, "/api/path-route", payload)
                        self.assertEqual(raised.exception.code, expected_code)
                        body = json.loads(raised.exception.read().decode("utf-8"))
                        self.assertIn(expected_error, body["error"])

            self._with_server(check, app_state=app_state)

    def test_path_route_endpoint_returns_conflict_for_stale_selected_hero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra", position=(0, 0, 0))
            map_path = _write_empty_h3m_map(temp_path / "map.h3m", map_size=2)
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                selected_hero_id="hero:999",
            )

            def check(base_url):
                with self.assertRaises(HTTPError) as raised:
                    self._post_json(
                        base_url,
                        "/api/path-route",
                        {
                            "hero_id": "hero:999",
                            "target_position": {"x": 0, "y": 0, "z": 0},
                        },
                    )

                self.assertEqual(raised.exception.code, 409)
                body = json.loads(raised.exception.read().decode("utf-8"))
                self.assertIn("no longer available", body["error"])

            self._with_server(check, app_state=app_state)

    def test_api_errors_are_json_for_invalid_json_and_invalid_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                selected_hero_id="hero:256",
            )

            def check(base_url):
                with self.assertRaises(HTTPError) as invalid_json:
                    self._post_raw(base_url, "/api/select-hero", b"{bad")
                self.assertEqual(invalid_json.exception.code, 400)
                payload = json.loads(invalid_json.exception.read().decode("utf-8"))
                self.assertIn("invalid JSON", payload["error"])

                with self.assertRaises(HTTPError) as invalid_hero:
                    self._post_json(
                        base_url,
                        "/api/simulate-target",
                        {
                            "hero_id": "hero:missing",
                            "target_id": "neutral:0",
                        },
                    )
                self.assertEqual(invalid_hero.exception.code, 404)
                payload = json.loads(invalid_hero.exception.read().decode("utf-8"))
                self.assertIn("unknown hero_id", payload["error"])

                with self.assertRaises(HTTPError) as invalid_simulations:
                    self._post_json(
                        base_url,
                        "/api/simulate-target",
                        {
                            "hero_id": "hero:256",
                            "target_id": "neutral:0",
                            "simulations": battle_estimator_gui.MAX_API_SIMULATIONS + 1,
                        },
                    )
                self.assertEqual(invalid_simulations.exception.code, 400)

                with self.assertRaises(HTTPError) as invalid_hidden_format:
                    self._post_json(
                        base_url,
                        "/api/hidden-target",
                        {
                            "target_id": "hero:/bad",
                            "hidden": True,
                        },
                    )
                self.assertEqual(invalid_hidden_format.exception.code, 400)

                with self.assertRaises(HTTPError) as unknown_hidden_hero:
                    self._post_json(
                        base_url,
                        "/api/hidden-target",
                        {
                            "target_id": "hero:999",
                            "hidden": True,
                        },
                    )
                self.assertEqual(unknown_hidden_hero.exception.code, 404)

                with self.assertRaises(HTTPError) as selected_hidden_hero:
                    self._post_json(
                        base_url,
                        "/api/hidden-target",
                        {
                            "target_id": "hero:256",
                            "hidden": True,
                        },
                    )
                self.assertEqual(selected_hidden_hero.exception.code, 400)

            self._with_server(check, app_state=app_state)

    def test_api_rejects_float_simulations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            def check(base_url):
                with self.assertRaises(HTTPError) as raised:
                    self._post_json(
                        base_url,
                        "/api/simulate-target",
                        {
                            "hero_id": "hero:256",
                            "target_id": "neutral:0",
                            "simulations": 1.9,
                        },
                    )

                self.assertEqual(raised.exception.code, 400)
                payload = json.loads(raised.exception.read().decode("utf-8"))
                self.assertIn("simulations must be an integer", payload["error"])

            self._with_server(check, app_state=app_state)

    def test_state_clears_stale_selected_hero_and_simulation_returns_conflict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            latest_save = _write_gui_save(
                game_dir,
                "002.GM2",
                hero_name="Marius",
                name_offset=512,
            )
            map_path = _write_h3m_map(temp_path / "map.h3m")
            app_state = battle_estimator_gui.GuiAppState(
                autosave_dir=game_dir,
                map_file=map_path,
                selected_hero_id="hero:256",
            )

            def check(base_url):
                status, payload = self._get_json(base_url, "/api/state")

                self.assertEqual(status, 200)
                self.assertEqual(payload["save_file"], str(latest_save))
                self.assertIsNone(payload["selected_hero_id"])
                self.assertIsNone(app_state.selected_hero_id)

                app_state.selected_hero_id = "hero:256"
                with self.assertRaises(HTTPError) as raised:
                    self._post_json(
                        base_url,
                        "/api/simulate-target",
                        {
                            "hero_id": "hero:256",
                            "target_id": "neutral:0",
                        },
                    )

                self.assertEqual(raised.exception.code, 409)
                payload = json.loads(raised.exception.read().decode("utf-8"))
                self.assertIn("no longer available", payload["error"])

            self._with_server(check, app_state=app_state)


class BattleEstimatorGuiPathfindingContractTests(unittest.TestCase):
    def test_pathfinding_request_builder_normalizes_route_map_and_positions(self):
        request = battle_estimator_gui.build_pathfinding_request(
            h3_save_parser.HeroPosition(1, 1, 0),
            (2, 1, 1),
            [
                ["BLW", "LLB"],
                ["BBB", "LWL"],
            ],
        )

        self.assertEqual(
            request.start_position,
            battle_estimator_gui.PathPosition(1, 1, 0),
        )
        self.assertEqual(
            request.requested_target_position,
            battle_estimator_gui.PathPosition(2, 1, 1),
        )
        self.assertEqual(request.route_map.width, 3)
        self.assertEqual(request.route_map.height, 2)
        self.assertEqual(request.route_map.levels, 2)
        self.assertEqual(
            request.route_map.state_at((0, 0, 0)),
            battle_estimator_gui.PATH_ROUTE_BLOCKED,
        )
        self.assertEqual(
            request.route_map.state_at((1, 1, 0)),
            battle_estimator_gui.PATH_ROUTE_LAND,
        )
        self.assertEqual(
            request.route_map.state_at((2, 0, 0)),
            battle_estimator_gui.PATH_ROUTE_WATER,
        )
        self.assertEqual(
            request.route_map.state_at((2, 1, 1)),
            battle_estimator_gui.PATH_ROUTE_LAND,
        )
        self.assertIsInstance(request.route_map.layers, tuple)
        self.assertIsInstance(request.route_map.layers[0], tuple)
        self.assertEqual(request.portal_edges, ())

    def test_pathfinding_result_contract_represents_statuses_and_segments(self):
        start = battle_estimator_gui.PathPosition(0, 0, 0)
        portal_entry = battle_estimator_gui.PathPosition(1, 1, 0)
        portal_exit = battle_estimator_gui.PathPosition(2, 2, 1)
        requested = battle_estimator_gui.PathPosition(3, 3, 1)
        resolved = battle_estimator_gui.PathPosition(2, 3, 1)
        portal_edge = battle_estimator_gui.PathfindingPortalEdge(
            source_id="portal:10",
            destination_id="portal:11",
            source_position=portal_entry,
            destination_position=portal_exit,
            portal_type=h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
            channel_key="monolith-one-way:7",
            is_non_deterministic=True,
        )
        walk_segment = battle_estimator_gui.PathfindingSegment(
            battle_estimator_gui.PATH_SEGMENT_WALK,
            start,
            portal_entry,
            steps=[
                battle_estimator_gui.PathfindingStep(start),
                battle_estimator_gui.PathfindingStep(portal_entry),
            ],
        )
        portal_segment = battle_estimator_gui.PathfindingSegment(
            battle_estimator_gui.PATH_SEGMENT_PORTAL,
            portal_entry,
            portal_exit,
            steps=[
                battle_estimator_gui.PathfindingStep(portal_entry),
                battle_estimator_gui.PathfindingStep(portal_exit),
            ],
            portal_edge=portal_edge,
        )

        found = battle_estimator_gui.PathfindingResult(
            battle_estimator_gui.PATH_STATUS_FOUND,
            requested_target_position=requested,
            resolved_target_position=resolved,
            steps=[
                battle_estimator_gui.PathfindingStep(start),
                battle_estimator_gui.PathfindingStep(portal_entry),
                battle_estimator_gui.PathfindingStep(portal_exit),
            ],
            segments=[walk_segment, portal_segment],
        )
        not_found = battle_estimator_gui.PathfindingResult(
            battle_estimator_gui.PATH_STATUS_NOT_FOUND,
            requested_target_position=requested,
            message="no land path",
        )
        invalid = battle_estimator_gui.PathfindingResult(
            battle_estimator_gui.PATH_STATUS_INVALID,
            requested_target_position=requested,
            message="selected hero has no parsed position",
        )

        self.assertEqual(found.resolved_target_position, resolved)
        self.assertIsInstance(found.steps, tuple)
        self.assertIsInstance(found.segments, tuple)
        self.assertEqual(found.segments[0].segment_type, "walk")
        self.assertEqual(found.segments[1].segment_type, "portal")
        self.assertTrue(found.segments[1].is_non_deterministic)
        self.assertEqual(not_found.status, battle_estimator_gui.PATH_STATUS_NOT_FOUND)
        self.assertEqual(invalid.status, battle_estimator_gui.PATH_STATUS_INVALID)
        with self.assertRaisesRegex(ValueError, "unknown pathfinding result status"):
            battle_estimator_gui.PathfindingResult("partial", requested)
        with self.assertRaisesRegex(ValueError, "walk path segment cannot have"):
            battle_estimator_gui.PathfindingSegment(
                battle_estimator_gui.PATH_SEGMENT_WALK,
                start,
                portal_entry,
                portal_edge=portal_edge,
            )

    def test_pathfinding_portal_edges_resolve_positions_and_random_edges(self):
        targets = (
            self._portal_target(
                10,
                (1, 1, 0),
                h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                "monolith-one-way:4",
            ),
            self._portal_target(
                11,
                (4, 1, 0),
                h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                "monolith-one-way:4",
            ),
            self._portal_target(
                12,
                (6, 1, 0),
                h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                "monolith-one-way:4",
            ),
            self._portal_target(
                20,
                (2, 3, 0),
                h3_map_parser.PORTAL_TYPE_SUBTERRANEAN_GATE,
                "subterranean:20:21",
            ),
            self._portal_target(
                21,
                (2, 3, 1),
                h3_map_parser.PORTAL_TYPE_SUBTERRANEAN_GATE,
                "subterranean:20:21",
            ),
        )
        edges = (
            self._portal_edge(
                10,
                11,
                h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                "monolith-one-way:4",
            ),
            self._portal_edge(
                10,
                12,
                h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                "monolith-one-way:4",
            ),
            self._portal_edge(
                20,
                21,
                h3_map_parser.PORTAL_TYPE_SUBTERRANEAN_GATE,
                "subterranean:20:21",
            ),
        )

        path_edges = battle_estimator_gui._pathfinding_portal_edges(targets, edges)

        self.assertEqual(
            [(edge.source_id, edge.destination_id) for edge in path_edges],
            [
                ("portal:10", "portal:11"),
                ("portal:10", "portal:12"),
                ("portal:20", "portal:21"),
            ],
        )
        self.assertEqual(
            path_edges[0].source_position,
            battle_estimator_gui.PathPosition(1, 1, 0),
        )
        self.assertEqual(
            path_edges[0].destination_position,
            battle_estimator_gui.PathPosition(4, 1, 0),
        )
        self.assertTrue(path_edges[0].is_non_deterministic)
        self.assertTrue(path_edges[1].is_non_deterministic)
        self.assertFalse(path_edges[2].is_non_deterministic)
        request = battle_estimator_gui.build_pathfinding_request(
            (0, 0, 0),
            (6, 3, 1),
            [
                ["LLLLLLL", "LLLLLLL", "LLLLLLL", "LLLLLLL"],
                ["LLLLLLL", "LLLLLLL", "LLLLLLL", "LLLLLLL"],
            ],
            portal_targets=targets,
            portal_edges=edges,
        )
        self.assertEqual(request.portal_edges, path_edges)

    def test_pathfinding_contract_rejects_invalid_inputs(self):
        invalid_cases = (
            (
                lambda: battle_estimator_gui.PathRouteMap([]),
                "path route layers must include at least one level",
            ),
            (
                lambda: battle_estimator_gui.PathRouteMap([["LL", "L"]]),
                "same width",
            ),
            (
                lambda: battle_estimator_gui.PathRouteMap([["LX"]]),
                "unknown path route state",
            ),
            (
                lambda: battle_estimator_gui.build_pathfinding_request(
                    None,
                    (0, 0, 0),
                    [["L"]],
                ),
                "path position is required",
            ),
            (
                lambda: battle_estimator_gui.build_pathfinding_request(
                    (0, 0, 0),
                    (1, 0, 0),
                    [["L"]],
                ),
                "requested target position out of bounds",
            ),
            (
                lambda: battle_estimator_gui.build_pathfinding_request(
                    (0, 0, 0),
                    (0, 0, 0),
                    [["W"]],
                ),
                "selected hero position must be a land route tile",
            ),
            (
                lambda: battle_estimator_gui._pathfinding_portal_edges(
                    (
                        self._portal_target(
                            10,
                            (0, 0, 0),
                            h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                            "monolith-one-way:1",
                        ),
                    ),
                    (
                        self._portal_edge(
                            10,
                            99,
                            h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                            "monolith-one-way:1",
                        ),
                    ),
                ),
                "unknown portal destination object_index",
            ),
            (
                lambda: battle_estimator_gui._pathfinding_portal_edges(
                    (
                        self._portal_target(
                            10,
                            (0, 0, 0),
                            h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                            "monolith-one-way:1",
                        ),
                    ),
                    (
                        self._portal_edge(
                            99,
                            10,
                            h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                            "monolith-one-way:1",
                        ),
                    ),
                ),
                "unknown portal source object_index",
            ),
            (
                lambda: battle_estimator_gui.build_pathfinding_request(
                    (0, 0, 0),
                    (0, 0, 0),
                    [["L"]],
                    portal_targets=(
                        self._portal_target(
                            10,
                            (0, 0, 0),
                            h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                            "monolith-one-way:1",
                        ),
                        self._portal_target(
                            11,
                            (1, 0, 0),
                            h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                            "monolith-one-way:1",
                        ),
                    ),
                    portal_edges=(
                        self._portal_edge(
                            10,
                            11,
                            h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                            "monolith-one-way:1",
                        ),
                    ),
                ),
                "portal destination position out of bounds",
            ),
        )

        for action, expected_message in invalid_cases:
            with self.subTest(expected_message=expected_message):
                with self.assertRaisesRegex(ValueError, expected_message):
                    action()

    def _portal_target(self, object_index, position, portal_type, channel_key):
        template = h3_map_parser.H3ObjectTemplate(
            template_index=object_index,
            animation_file=f"AVXportal{object_index}.def",
            block_mask=b"\x00" * 6,
            visit_mask=b"\x01" + b"\x00" * 5,
            terrain_mask=0x01FF,
            object_id=h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_ENTRANCE,
            subid=0,
            object_type=0,
            print_priority=0,
        )
        x, y, z = position
        return h3_map_parser.H3PortalTarget(
            object_index=object_index,
            x=x,
            y=y,
            z=z,
            anchor_x=x,
            anchor_y=y,
            anchor_z=z,
            template=template,
            object_id=h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_ENTRANCE,
            h3m_subid=0,
            portal_type=portal_type,
            role=h3_map_parser.PORTAL_ROLE_BOTH,
            channel_key=channel_key,
        )

    def _portal_edge(self, source_index, destination_index, portal_type, channel_key):
        return h3_map_parser.H3PortalEdge(
            source_object_index=source_index,
            destination_object_index=destination_index,
            portal_type=portal_type,
            channel_key=channel_key,
            h3m_subid=0,
        )


class BattleEstimatorGuiLandPathTests(unittest.TestCase):
    def test_find_land_path_returns_shortest_diagonal_route(self):
        request = self._land_request(
            [
                ["LLLL", "LLLL", "LLLL"],
            ],
            (0, 0, 0),
            (3, 2, 0),
        )

        result = battle_estimator_gui.find_land_path(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_FOUND)
        self.assertEqual(
            result.requested_target_position,
            battle_estimator_gui.PathPosition(3, 2, 0),
        )
        self.assertEqual(
            result.resolved_target_position,
            result.requested_target_position,
        )
        self.assertEqual(
            self._step_keys(result),
            [(0, 0, 0), (1, 0, 0), (2, 1, 0), (3, 2, 0)],
        )
        self.assertEqual(len(result.steps) - 1, 3)
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(
            result.segments[0].segment_type,
            battle_estimator_gui.PATH_SEGMENT_WALK,
        )
        self.assertEqual(result.segments[0].steps, result.steps)
        self.assertTrue(all(step.position.z == 0 for step in result.steps))

    def test_find_land_path_allows_diagonal_corner_cutting_in_mvp(self):
        request = self._land_request(
            [
                ["LB", "BL"],
            ],
            (0, 0, 0),
            (1, 1, 0),
        )

        result = battle_estimator_gui.find_land_path(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_FOUND)
        self.assertEqual(self._step_keys(result), [(0, 0, 0), (1, 1, 0)])

    def test_find_land_path_does_not_traverse_water_or_blocked_tiles(self):
        request = self._land_request(
            [
                ["LLL", "WBL", "LLL"],
            ],
            (0, 2, 0),
            (2, 0, 0),
        )

        result = battle_estimator_gui.find_land_path(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_FOUND)
        self.assertGreater(len(result.steps) - 1, 2)
        for step in result.steps:
            self.assertEqual(
                request.route_map.state_at(step.position),
                battle_estimator_gui.PATH_ROUTE_LAND,
            )

    def test_find_land_path_returns_not_found_for_unreachable_land_target(self):
        request = self._land_request(
            [
                ["LWL", "WWW", "LLL"],
            ],
            (0, 0, 0),
            (2, 0, 0),
        )

        result = battle_estimator_gui.find_land_path(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_NOT_FOUND)
        self.assertEqual(result.steps, ())
        self.assertEqual(result.segments, ())
        self.assertIsNone(result.resolved_target_position)
        self.assertIn("no land path", result.message)

    def test_find_land_path_returns_not_found_without_reachable_fallback(self):
        request = self._land_request(
            [
                ["LWB"],
            ],
            (0, 0, 0),
            (2, 0, 0),
        )

        result = battle_estimator_gui.find_land_path(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_NOT_FOUND)
        self.assertEqual(result.requested_target_position.key, (2, 0, 0))
        self.assertEqual(result.steps, ())
        self.assertEqual(result.segments, ())
        self.assertIn("no reachable land neighbor", result.message)

    def test_find_land_path_ignores_portal_edges(self):
        portal_edge = battle_estimator_gui.PathfindingPortalEdge(
            source_id="portal:0",
            destination_id="portal:1",
            source_position=(0, 0, 0),
            destination_position=(2, 0, 0),
            portal_type=h3_map_parser.PORTAL_TYPE_MONOLITH_TWO_WAY,
            channel_key="monolith-two-way:1",
        )
        request = battle_estimator_gui.PathfindingRequest(
            start_position=(0, 0, 0),
            requested_target_position=(2, 0, 0),
            route_map=[
                ["LWL", "WWW", "LLL"],
            ],
            portal_edges=(portal_edge,),
        )

        result = battle_estimator_gui.find_land_path(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_NOT_FOUND)
        self.assertEqual(result.steps, ())
        self.assertEqual(result.segments, ())

    def test_find_land_path_handles_start_equal_to_target(self):
        request = self._land_request(
            [
                ["L"],
            ],
            (0, 0, 0),
            (0, 0, 0),
        )

        result = battle_estimator_gui.find_land_path(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_FOUND)
        self.assertEqual(self._step_keys(result), [(0, 0, 0)])
        self.assertEqual(
            result.segments[0].start_position,
            result.segments[0].end_position,
        )

    def test_find_land_path_rejects_non_request_input(self):
        with self.assertRaisesRegex(ValueError, "request must be PathfindingRequest"):
            battle_estimator_gui.find_land_path(object())

    def _land_request(self, route_layers, start_position, target_position):
        return battle_estimator_gui.build_pathfinding_request(
            start_position,
            target_position,
            route_layers,
        )

    def _step_keys(self, result):
        return [step.position.key for step in result.steps]


class BattleEstimatorGuiTargetResolutionTests(unittest.TestCase):
    def test_pathfinding_request_accepts_marker_position_targets(self):
        markers = (
            {"type": "hero", "position": {"x": 2, "y": 0, "z": 0}},
            {"type": "neutral", "position": {"x": 2, "y": 0, "z": 0}},
            {"type": "town", "position": {"x": 2, "y": 0, "z": 0}},
            {"type": "portal", "position": {"x": 2, "y": 0, "z": 0}},
        )
        for marker in markers:
            with self.subTest(marker_type=marker["type"]):
                request = battle_estimator_gui.build_pathfinding_request(
                    (0, 0, 0),
                    marker,
                    [
                        ["LLL"],
                    ],
                )

                result = battle_estimator_gui.find_path_route(request)

                self.assertEqual(
                    result.status,
                    battle_estimator_gui.PATH_STATUS_FOUND,
                )
                self.assertEqual(result.resolved_target_position.key, (2, 0, 0))

    def test_find_path_route_allows_blocked_terminal_target_as_final(self):
        marker = {"type": "town", "position": {"x": 1, "y": 0, "z": 0}}
        request = battle_estimator_gui.build_pathfinding_request(
            (0, 0, 0),
            marker,
            [
                ["LB"],
            ],
            terminal_positions=(marker,),
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_FOUND)
        self.assertEqual(self._step_keys(result), [(0, 0, 0), (1, 0, 0)])
        self.assertEqual(result.resolved_target_position.key, (1, 0, 0))

    def test_find_path_route_does_not_use_terminal_as_intermediate(self):
        request = battle_estimator_gui.PathfindingRequest(
            start_position=(0, 0, 0),
            requested_target_position=(2, 0, 0),
            route_map=[
                ["LLL"],
            ],
            terminal_positions=((1, 0, 0),),
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_NOT_FOUND)
        self.assertEqual(result.steps, ())
        self.assertEqual(result.segments, ())

    def test_find_path_route_falls_back_from_blocked_target_to_neighbor(self):
        request = battle_estimator_gui.build_pathfinding_request(
            (0, 0, 0),
            (2, 0, 0),
            [
                ["LLB"],
            ],
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_FOUND)
        self.assertEqual(result.requested_target_position.key, (2, 0, 0))
        self.assertEqual(result.resolved_target_position.key, (1, 0, 0))
        self.assertEqual(self._step_keys(result), [(0, 0, 0), (1, 0, 0)])
        self.assertIn("reachable neighbor", result.message)

    def test_find_path_route_can_resolve_start_as_blocked_target_fallback(self):
        request = battle_estimator_gui.build_pathfinding_request(
            (0, 0, 0),
            (1, 0, 0),
            [
                ["LB"],
            ],
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_FOUND)
        self.assertEqual(self._step_keys(result), [(0, 0, 0)])
        self.assertEqual(result.resolved_target_position.key, (0, 0, 0))
        self.assertIn("reachable neighbor", result.message)

    def test_find_path_route_fallback_tie_uses_target_neighbor_order(self):
        request = battle_estimator_gui.build_pathfinding_request(
            (1, 3, 0),
            (1, 1, 0),
            [
                ["LLL", "LBL", "LLL", "LLL"],
            ],
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_FOUND)
        self.assertEqual(result.resolved_target_position.key, (0, 2, 0))

    def test_find_path_route_excludes_terminal_from_blocked_target_fallback(self):
        request = battle_estimator_gui.PathfindingRequest(
            start_position=(0, 0, 0),
            requested_target_position=(2, 0, 0),
            route_map=[
                ["LLB"],
            ],
            terminal_positions=((1, 0, 0),),
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_NOT_FOUND)
        self.assertEqual(result.steps, ())
        self.assertEqual(result.segments, ())

    def test_find_path_route_returns_not_found_without_reachable_fallback(self):
        request = battle_estimator_gui.build_pathfinding_request(
            (0, 0, 0),
            (2, 0, 0),
            [
                ["LWB"],
            ],
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_NOT_FOUND)
        self.assertIsNone(result.resolved_target_position)
        self.assertEqual(result.steps, ())
        self.assertEqual(result.segments, ())
        self.assertIn("no reachable land neighbor", result.message)

    def test_pathfinding_request_rejects_out_of_bounds_terminal_position(self):
        with self.assertRaisesRegex(ValueError, "terminal position out of bounds"):
            battle_estimator_gui.PathfindingRequest(
                start_position=(0, 0, 0),
                requested_target_position=(0, 0, 0),
                route_map=[
                    ["L"],
                ],
                terminal_positions=((1, 0, 0),),
            )

    def test_find_path_route_allows_portal_to_active_non_land_terminal(self):
        marker = {"type": "portal", "position": {"x": 2, "y": 0, "z": 0}}
        request = battle_estimator_gui.PathfindingRequest(
            start_position=(0, 0, 0),
            requested_target_position=marker,
            route_map=[
                ["LWB"],
            ],
            portal_edges=(
                battle_estimator_gui.PathfindingPortalEdge(
                    source_id="portal:0",
                    destination_id="portal:2",
                    source_position=(0, 0, 0),
                    destination_position=(2, 0, 0),
                    portal_type=h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                    channel_key="monolith-one-way:terminal",
                ),
            ),
            terminal_positions=(marker,),
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_FOUND)
        self.assertEqual(self._step_keys(result), [(0, 0, 0), (2, 0, 0)])
        self.assertEqual(
            result.segments[0].segment_type,
            battle_estimator_gui.PATH_SEGMENT_PORTAL,
        )

    def test_find_path_route_skips_portal_to_non_target_terminal(self):
        request = battle_estimator_gui.PathfindingRequest(
            start_position=(0, 0, 0),
            requested_target_position=(3, 0, 0),
            route_map=[
                ["LWBL"],
            ],
            portal_edges=(
                battle_estimator_gui.PathfindingPortalEdge(
                    source_id="portal:0",
                    destination_id="portal:2",
                    source_position=(0, 0, 0),
                    destination_position=(2, 0, 0),
                    portal_type=h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                    channel_key="monolith-one-way:terminal",
                ),
            ),
            terminal_positions=((2, 0, 0),),
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_NOT_FOUND)
        self.assertEqual(result.steps, ())
        self.assertEqual(result.segments, ())

    def _step_keys(self, result):
        return [step.position.key for step in result.steps]


class BattleEstimatorGuiPortalPathTests(unittest.TestCase):
    def test_find_path_route_uses_same_level_one_way_portal_segments(self):
        request = self._request(
            [
                ["LLWLL"],
            ],
            (0, 0, 0),
            (4, 0, 0),
            (
                self._portal_edge(
                    "portal:1",
                    "portal:3",
                    (1, 0, 0),
                    (3, 0, 0),
                    h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                    "monolith-one-way:1",
                ),
            ),
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_FOUND)
        self.assertEqual(
            self._step_keys(result),
            [(0, 0, 0), (1, 0, 0), (3, 0, 0), (4, 0, 0)],
        )
        self.assertEqual(
            [segment.segment_type for segment in result.segments],
            [
                battle_estimator_gui.PATH_SEGMENT_WALK,
                battle_estimator_gui.PATH_SEGMENT_PORTAL,
                battle_estimator_gui.PATH_SEGMENT_WALK,
            ],
        )
        self.assertEqual(
            self._segment_step_keys(result.segments[1]),
            [(1, 0, 0), (3, 0, 0)],
        )
        self.assertEqual(result.segments[1].portal_edge.destination_id, "portal:3")

    def test_find_path_route_does_not_traverse_one_way_portal_backwards(self):
        request = self._request(
            [
                ["LLWLL"],
            ],
            (3, 0, 0),
            (1, 0, 0),
            (
                self._portal_edge(
                    "portal:1",
                    "portal:3",
                    (1, 0, 0),
                    (3, 0, 0),
                    h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                    "monolith-one-way:1",
                ),
            ),
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_NOT_FOUND)
        self.assertEqual(result.steps, ())
        self.assertEqual(result.segments, ())

    def test_find_path_route_uses_reverse_edge_when_parser_emits_it(self):
        request = self._request(
            [
                ["LLWLL"],
            ],
            (3, 0, 0),
            (1, 0, 0),
            (
                self._portal_edge(
                    "portal:1",
                    "portal:3",
                    (1, 0, 0),
                    (3, 0, 0),
                    h3_map_parser.PORTAL_TYPE_MONOLITH_TWO_WAY,
                    "monolith-two-way:1",
                ),
                self._portal_edge(
                    "portal:3",
                    "portal:1",
                    (3, 0, 0),
                    (1, 0, 0),
                    h3_map_parser.PORTAL_TYPE_MONOLITH_TWO_WAY,
                    "monolith-two-way:1",
                ),
            ),
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_FOUND)
        self.assertEqual(self._step_keys(result), [(3, 0, 0), (1, 0, 0)])
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(
            result.segments[0].segment_type,
            battle_estimator_gui.PATH_SEGMENT_PORTAL,
        )
        self.assertEqual(result.segments[0].portal_edge.source_id, "portal:3")

    def test_find_path_route_uses_cross_level_subterranean_edge(self):
        request = self._request(
            [
                ["L"],
                ["L"],
            ],
            (0, 0, 0),
            (0, 0, 1),
            (
                self._portal_edge(
                    "portal:surface",
                    "portal:underground",
                    (0, 0, 0),
                    (0, 0, 1),
                    h3_map_parser.PORTAL_TYPE_SUBTERRANEAN_GATE,
                    "subterranean:surface:underground",
                ),
            ),
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_FOUND)
        self.assertEqual(self._step_keys(result), [(0, 0, 0), (0, 0, 1)])
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(
            result.segments[0].segment_type,
            battle_estimator_gui.PATH_SEGMENT_PORTAL,
        )
        self.assertEqual(
            self._segment_step_keys(result.segments[0]),
            [(0, 0, 0), (0, 0, 1)],
        )

    def test_find_path_route_marks_used_multi_exit_portal_segment(self):
        request = self._request(
            [
                ["LWLWL"],
            ],
            (0, 0, 0),
            (4, 0, 0),
            (
                self._portal_edge(
                    "portal:0",
                    "portal:2",
                    (0, 0, 0),
                    (2, 0, 0),
                    h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                    "monolith-one-way:7",
                    is_non_deterministic=True,
                ),
                self._portal_edge(
                    "portal:0",
                    "portal:4",
                    (0, 0, 0),
                    (4, 0, 0),
                    h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                    "monolith-one-way:7",
                    is_non_deterministic=True,
                ),
            ),
        )

        result = battle_estimator_gui.find_path_route(request)

        self.assertEqual(result.status, battle_estimator_gui.PATH_STATUS_FOUND)
        self.assertEqual(len(request.portal_edges), 2)
        self.assertEqual(self._step_keys(result), [(0, 0, 0), (4, 0, 0)])
        self.assertEqual(len(result.segments), 1)
        portal_segment = result.segments[0]
        self.assertEqual(
            portal_segment.segment_type,
            battle_estimator_gui.PATH_SEGMENT_PORTAL,
        )
        self.assertEqual(portal_segment.portal_edge.destination_id, "portal:4")
        self.assertTrue(portal_segment.is_non_deterministic)
        self.assertTrue(portal_segment.portal_edge.is_non_deterministic)

    def test_find_path_route_ignores_portal_edges_to_non_land_destinations(self):
        for blocked_char in (
            battle_estimator_gui.PATH_ROUTE_WATER,
            battle_estimator_gui.PATH_ROUTE_BLOCKED,
        ):
            with self.subTest(blocked_char=blocked_char):
                request = self._request(
                    [
                        [f"L{blocked_char}LL"],
                    ],
                    (0, 0, 0),
                    (3, 0, 0),
                    (
                        self._portal_edge(
                            "portal:0",
                            "portal:blocked",
                            (0, 0, 0),
                            (1, 0, 0),
                            h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                            "monolith-one-way:blocked",
                        ),
                    ),
                )

                result = battle_estimator_gui.find_path_route(request)

                self.assertEqual(
                    result.status,
                    battle_estimator_gui.PATH_STATUS_NOT_FOUND,
                )
                self.assertEqual(result.steps, ())
                self.assertEqual(result.segments, ())

    def _request(self, route_layers, start_position, target_position, portal_edges):
        return battle_estimator_gui.PathfindingRequest(
            start_position=start_position,
            requested_target_position=target_position,
            route_map=route_layers,
            portal_edges=portal_edges,
        )

    def _portal_edge(
        self,
        source_id,
        destination_id,
        source_position,
        destination_position,
        portal_type,
        channel_key,
        is_non_deterministic=False,
    ):
        return battle_estimator_gui.PathfindingPortalEdge(
            source_id=source_id,
            destination_id=destination_id,
            source_position=source_position,
            destination_position=destination_position,
            portal_type=portal_type,
            channel_key=channel_key,
            is_non_deterministic=is_non_deterministic,
        )

    def _step_keys(self, result):
        return [step.position.key for step in result.steps]

    def _segment_step_keys(self, segment):
        return [step.position.key for step in segment.steps]


class BattleEstimatorGuiSnapshotTests(unittest.TestCase):
    def test_route_layers_serializer_uses_compact_rows_per_level(self):
        header = h3_map_parser.H3MapHeader(
            format_version=h3_map_parser.H3M_FORMAT_SOD,
            format_name="SoD",
            map_size=2,
            levels=2,
            are_any_players=True,
        )
        route_tiles = (
            h3_map_parser.H3RouteTile(0, 0, 0, h3_map_parser.ROUTE_LAND),
            h3_map_parser.H3RouteTile(1, 0, 0, h3_map_parser.ROUTE_WATER),
            h3_map_parser.H3RouteTile(0, 1, 0, h3_map_parser.ROUTE_BLOCKED),
            h3_map_parser.H3RouteTile(1, 1, 0, h3_map_parser.ROUTE_LAND),
            h3_map_parser.H3RouteTile(0, 0, 1, h3_map_parser.ROUTE_BLOCKED),
            h3_map_parser.H3RouteTile(1, 0, 1, h3_map_parser.ROUTE_LAND),
            h3_map_parser.H3RouteTile(0, 1, 1, h3_map_parser.ROUTE_WATER),
            h3_map_parser.H3RouteTile(1, 1, 1, h3_map_parser.ROUTE_BLOCKED),
        )

        self.assertEqual(
            battle_estimator_gui._serialize_route_layers(header, route_tiles),
            [
                ["LW", "BL"],
                ["BL", "WB"],
            ],
        )

    def test_route_layers_serializer_rejects_invalid_tiles(self):
        header = h3_map_parser.H3MapHeader(
            format_version=h3_map_parser.H3M_FORMAT_SOD,
            format_name="SoD",
            map_size=1,
            levels=1,
            are_any_players=True,
        )

        cases = (
            (
                (
                    h3_map_parser.H3RouteTile(0, 0, 0, h3_map_parser.ROUTE_LAND),
                    h3_map_parser.H3RouteTile(0, 0, 0, h3_map_parser.ROUTE_WATER),
                ),
                "duplicate route tile",
            ),
            (
                (
                    h3_map_parser.H3RouteTile(1, 0, 0, h3_map_parser.ROUTE_LAND),
                ),
                "out of bounds",
            ),
            (
                (
                    h3_map_parser.H3RouteTile(0, 0, 0, "lava"),
                ),
                "unknown route tile state",
            ),
            (
                (),
                "route tile count mismatch",
            ),
        )

        for route_tiles, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                with self.assertRaisesRegex(ValueError, expected_message):
                    battle_estimator_gui._serialize_route_layers(header, route_tiles)

    def test_follow_latest_snapshot_uses_latest_numeric_save_and_marks_removed_neutrals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            older_save = _write_gui_save(game_dir, "001.GM2", hero_name="Old")
            latest_save = _write_gui_save(
                game_dir,
                "002.GM2",
                hero_name="Isra",
                position=(39, 69, 1),
                removed_object_index=1,
                removed_h3m_subid=98,
            )
            map_path = _write_h3m_map(
                temp_path / "map.h3m",
                position=(39, 70, 1),
                sign_before_monster=True,
            )
            before = _file_state(latest_save, map_path)

            snapshot = battle_estimator_gui.build_state_snapshot(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            self.assertEqual(snapshot["mode"], battle_estimator_gui.FOLLOW_LATEST_MODE)
            self.assertEqual(snapshot["autosave_dir"], str(game_dir))
            self.assertEqual(snapshot["save_file"], str(latest_save))
            self.assertNotEqual(snapshot["save_file"], str(older_save))
            self.assertEqual(snapshot["map_file"], str(map_path))
            self.assertEqual(snapshot["map"], {"width": 1, "height": 1, "levels": 1})
            self.assertEqual(snapshot["route_layers"], [["B"]])
            self.assertEqual(len(snapshot["route_layers"]), snapshot["map"]["levels"])
            for level_rows in snapshot["route_layers"]:
                self.assertEqual(len(level_rows), snapshot["map"]["height"])
                for row in level_rows:
                    self.assertEqual(len(row), snapshot["map"]["width"])
            self.assertEqual(
                snapshot["save_fingerprint"],
                _expected_fingerprint(latest_save),
            )
            self.assertEqual(
                snapshot["map_fingerprint"],
                _expected_fingerprint(map_path),
            )

            self.assertEqual(len(snapshot["heroes"]), 1)
            hero = snapshot["heroes"][0]
            self.assertEqual(hero["id"], "hero:256")
            self.assertEqual(hero["name"], "Isra")
            self.assertEqual(hero["position"], {"x": 39, "y": 69, "z": 1})
            self.assertEqual(hero["owner_color_id"], 0)
            self.assertEqual(hero["owner_color_name"], "red")
            self.assertIsNone(hero["team_id"])
            self.assertEqual(hero["army"][0]["creature_name"], "Skeleton Warrior")
            self.assertEqual(hero["army"][0]["count"], 731)
            self.assertGreater(hero["ai_value"], 0)
            self.assertEqual(len(snapshot["players"]), 8)
            self.assertEqual(snapshot["teams"], [])

            self.assertEqual(len(snapshot["neutral_targets"]), 1)
            neutral = snapshot["neutral_targets"][0]
            self.assertEqual(neutral["id"], "neutral:1")
            self.assertEqual(neutral["object_index"], 1)
            self.assertEqual(neutral["position"], {"x": 39, "y": 70, "z": 1})
            self.assertEqual(neutral["h3m_subid"], 98)
            self.assertEqual(neutral["count"], 37)
            self.assertEqual(neutral["creature_name"], "Gnoll")
            self.assertEqual(neutral["estimator_creature_id"], 98)
            self.assertTrue(neutral["removed"])
            self.assertTrue(neutral["removal_note"].startswith("removed-save-record@"))
            json.dumps(snapshot)
            self.assertEqual(_file_state(latest_save, map_path), before)

    def test_follow_latest_snapshot_uses_configured_game_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "configured-game"
            game_dir.mkdir()
            latest_save = _write_gui_save(game_dir, "009.GM1", hero_name="Config")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            config_path.write_text(
                json.dumps({"autosave_dir": str(game_dir)}) + "\n",
                encoding="utf-8",
            )

            snapshot = battle_estimator_gui.build_state_snapshot(
                map_file=map_path,
                config_path=config_path,
            )

            self.assertEqual(snapshot["save_file"], str(latest_save))
            self.assertEqual(snapshot["heroes"][0]["name"], "Config")

    def test_pinned_snapshot_uses_explicit_save_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            latest_save = _write_gui_save(game_dir, "010.GM2", hero_name="Latest")
            pinned_save = _write_gui_save(
                game_dir,
                "003.GM1",
                hero_name="Pinned",
                position=None,
            )
            map_path = _write_h3m_map(temp_path / "map.h3m")

            snapshot = battle_estimator_gui.build_state_snapshot(
                mode=battle_estimator_gui.PINNED_MODE,
                save_file=pinned_save,
                map_file=map_path,
            )

            self.assertEqual(snapshot["mode"], battle_estimator_gui.PINNED_MODE)
            self.assertEqual(snapshot["save_file"], str(pinned_save))
            self.assertNotEqual(snapshot["save_file"], str(latest_save))
            self.assertEqual(snapshot["heroes"][0]["name"], "Pinned")
            self.assertIsNone(snapshot["heroes"][0]["position"])

    def test_snapshot_rejects_save_file_changed_during_build(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            save_path = _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            original_load_save = battle_estimator_gui.h3_save_parser.load_save

            def changing_load_save(path):
                loaded = original_load_save(path)
                save_path.write_bytes(save_path.read_bytes() + b"changed")
                return loaded

            with patch.object(
                battle_estimator_gui.h3_save_parser,
                "load_save",
                side_effect=changing_load_save,
            ):
                with self.assertRaises(battle_estimator_gui.SnapshotConsistencyError):
                    battle_estimator_gui.build_state_snapshot(
                        autosave_dir=game_dir,
                        map_file=map_path,
                    )


def _write_gui_save(
    game_dir: Path,
    name: str,
    hero_name: str,
    position=(39, 69, 1),
    removed_object_index: int | None = None,
    removed_h3m_subid: int | None = None,
    name_offset: int = 256,
) -> Path:
    payload = _build_xor_hero_fixture(
        hero_name=hero_name,
        position=position,
        name_offset=name_offset,
    )
    if removed_object_index is not None and removed_h3m_subid is not None:
        payload += (
            b"\x00" * 3
            + _removed_neutral_record_core_bytes(
                removed_object_index,
                removed_h3m_subid,
                0x9000,
            )
        )
    save_path = game_dir / name
    save_path.write_bytes(gzip.compress(payload))
    return save_path


def _write_h3m_map_with_town(path: Path) -> Path:
    visit_mask = bytes((0x01, 0x00, 0x00, 0x00, 0x00, 0x40))
    payload = _minimal_h3m_with_templates_and_objects(
        h3_map_parser.H3M_FORMAT_SOD,
        (
            _object_template_bytes(
                "AVCcasx0.def",
                h3_map_parser.H3M_OBJECT_TOWN,
                subid=3,
                visit_mask=visit_mask,
            ),
        ),
        (
            _object_bytes(
                (7, 5, 0),
                0,
                _town_payload(
                    owner=2,
                    custom_name="Castle Keep",
                    has_garrison=True,
                ),
            ),
        ),
        map_size=8,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(payload))
    return path


def _write_h3m_map_with_portals(path: Path) -> Path:
    visit_mask = bytes((0x01, 0x00, 0x00, 0x00, 0x00, 0x40))
    payload = _minimal_h3m_with_templates_and_objects(
        h3_map_parser.H3M_FORMAT_SOD,
        (
            _object_template_bytes(
                "AVXmn1e.def",
                h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_ENTRANCE,
                subid=2,
                visit_mask=visit_mask,
            ),
            _object_template_bytes(
                "AVXmn1x.def",
                h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_EXIT,
                subid=2,
            ),
        ),
        (
            _object_bytes((7, 5, 0), 0, b""),
            _object_bytes((2, 3, 1), 1, b""),
        ),
        map_size=8,
        levels=2,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(payload))
    return path


def _write_empty_h3m_map(path: Path, map_size=1, levels=1) -> Path:
    payload = _minimal_h3m_with_templates_and_objects(
        h3_map_parser.H3M_FORMAT_SOD,
        (),
        (),
        map_size=map_size,
        levels=levels,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(payload))
    return path


def _write_multi_gui_save(game_dir: Path, name: str, hero_specs) -> Path:
    max_name_offset = max(spec["name_offset"] for spec in hero_specs)
    data = bytearray(max_name_offset + 256)
    data[0:len(battle_estimator_gui.h3_save_parser.H3SVG_SIGNATURE)] = (
        battle_estimator_gui.h3_save_parser.H3SVG_SIGNATURE
    )
    for spec in hero_specs:
        _write_xor_hero_window(
            data,
            hero_name=spec["hero_name"],
            name_offset=spec["name_offset"],
            position=spec.get("position"),
            owner_color_id=spec.get("owner_color_id", 0),
        )
    save_path = game_dir / name
    save_path.write_bytes(gzip.compress(bytes(data)))
    return save_path


def _expected_fingerprint(path: Path) -> dict:
    stat_result = path.stat()
    return {
        "path": str(path),
        "size": stat_result.st_size,
        "mtime": stat_result.st_mtime,
        "mtime_ns": stat_result.st_mtime_ns,
    }


def _file_state(*paths: Path) -> tuple[tuple[bytes, int, int], ...]:
    return tuple(
        (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns)
        for path in paths
    )


if __name__ == "__main__":
    unittest.main()
