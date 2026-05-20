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
            app_js.index("function matchRecentHeroName(")
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
            '"/api/hidden-target"',
            '"/api/show-hidden"',
            '"/api/saves"',
            '"/api/save-mode"',
            '"/api/game-folders"',
            '"/api/game-folder"',
            "previousSaveButton",
            "nextSaveButton",
            "navigateSave",
            "heroRankingButton",
            "heroRankingDialog",
            "renderHeroRanking",
            "gameFolderPath",
            "gameFolderInFlight",
            "showFollowLatestDialog",
            "showHiddenToggle",
            "targetContextMenu",
            "hiddenTargetInFlight",
            "showHiddenInFlight",
            "use_latest_game_folder",
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
            'id="hero-ranking-button"',
            'id="hero-ranking-dialog"',
            'id="hero-ranking-list"',
            'id="hero-ranking-close-button"',
            'id="map-level-control"',
            'id="show-removed-toggle"',
            'id="show-hidden-toggle"',
            'id="map-stage"',
            'id="map-tooltip"',
            'id="target-context-menu"',
            'id="scan-radius"',
            'id="scan-target-type"',
            'id="scan-button"',
            'value="all"',
            'value="neutral"',
            'value="hero"',
        ):
            self.assertIn(expected, index_html)
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
            ".ranking-dialog-panel",
            ".ranking-list",
            ".ranking-item",
            ".segmented-control",
            ".toggle-control",
            ".map-tooltip",
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
const assert = require("assert");
const context = new Proxy({{}}, {{
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
  addEventListener() {{}}
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
  heroes: [],
  neutral_targets: [],
  recent_heroes: [],
  selected_hero_id: null
}};
global.fetch = (path) => Promise.resolve({{
  ok: true,
  json: () => Promise.resolve(path === "/api/health" ? {{ ok: true }} : snapshot)
}});
require({json.dumps(app_js_path)});
const helpers = window.__battleEstimatorGuiTest;
assert.strictEqual(autoRefreshIntervalCalls, 0);
const markerSnapshot = {{
  map: {{ width: 4, height: 4, levels: 2 }},
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
  ]
}};
const level0Markers = helpers.buildMarkerCache(markerSnapshot, 10, 0, false);
assert.deepStrictEqual(level0Markers.map((marker) => marker.id), ["hero:0", "neutral:0"]);
const level0WithRemoved = helpers.buildMarkerCache(markerSnapshot, 10, 0, true);
assert.deepStrictEqual(
  level0WithRemoved.map((marker) => marker.id),
  ["hero:0", "neutral:0", "neutral:removed"]
);
assert.strictEqual(level0WithRemoved.find((marker) => marker.id === "neutral:removed").removed, true);
const level1Markers = helpers.buildMarkerCache(markerSnapshot, 10, 1, false);
assert.deepStrictEqual(level1Markers.map((marker) => marker.id), ["hero:1", "neutral:1"]);
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
const tooltip = helpers.markerTooltipText(level1Markers[0]);
assert.ok(tooltip.includes("Fafner"));
assert.ok(tooltip.includes("Tan team 1 enemy"));
assert.ok(tooltip.includes("2,3,1"));
assert.ok(!tooltip.includes("<"));
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
  helpers.simulationClickDecision({{ type: "neutral", id: "neutral:0" }}, "hero:256"),
  {{ simulate: true, message: "" }}
);
assert.deepStrictEqual(
  helpers.simulationClickDecision({{ type: "neutral", id: "neutral:0", hidden: true }}, "hero:256"),
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

                with self.assertRaises(HTTPError) as invalid_hidden_target:
                    self._post_json(
                        base_url,
                        "/api/hidden-target",
                        {
                            "target_id": "hero:256",
                            "hidden": True,
                        },
                    )
                self.assertEqual(invalid_hidden_target.exception.code, 400)

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


class BattleEstimatorGuiSnapshotTests(unittest.TestCase):
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
