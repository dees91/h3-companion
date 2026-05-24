(function () {
  "use strict";

  const elements = {
    health: document.getElementById("health-status"),
    mode: document.getElementById("mode-status"),
    save: document.getElementById("save-status"),
    map: document.getElementById("map-status"),
    refresh: document.getElementById("refresh-status"),
    gameFolderPicker: document.getElementById("game-folder-picker"),
    gameFolderPath: document.getElementById("game-folder-path"),
    useGameFolderButton: document.getElementById("use-game-folder-button"),
    savePicker: document.getElementById("save-picker"),
    previousSaveButton: document.getElementById("previous-save-button"),
    nextSaveButton: document.getElementById("next-save-button"),
    followLatestButton: document.getElementById("follow-latest-button"),
    refreshButton: document.getElementById("refresh-button"),
    heroSearch: document.getElementById("hero-search"),
    heroCount: document.getElementById("hero-count"),
    recentHeroes: document.getElementById("recent-heroes"),
    heroList: document.getElementById("hero-list"),
    mapSummary: document.getElementById("map-summary"),
    objectCount: document.getElementById("object-count"),
    mapLevelControl: document.getElementById("map-level-control"),
    targetFilterControl: document.getElementById("target-filter-control"),
    showRemovedToggle: document.getElementById("show-removed-toggle"),
    showHiddenToggle: document.getElementById("show-hidden-toggle"),
    routeOverlayToggle: document.getElementById("show-route-overlay-toggle"),
    pathModeToggle: document.getElementById("path-mode-toggle"),
    heroSkillsButton: document.getElementById("hero-skills-button"),
    heroRankingButton: document.getElementById("hero-ranking-button"),
    mapStage: document.getElementById("map-stage"),
    mapTooltip: document.getElementById("map-tooltip"),
    targetContextMenu: document.getElementById("target-context-menu"),
    mapOverlayTitle: document.getElementById("map-overlay-title"),
    mapOverlayDetail: document.getElementById("map-overlay-detail"),
    targetState: document.getElementById("target-state"),
    estimateState: document.getElementById("estimate-state"),
    pathState: document.getElementById("path-state"),
    scanRadius: document.getElementById("scan-radius"),
    scanSortControl: document.getElementById("scan-sort-control"),
    scanButton: document.getElementById("scan-button"),
    scanState: document.getElementById("scan-state"),
    canvas: document.getElementById("battle-map"),
    zoom: document.getElementById("zoom-status"),
    followLatestDialog: document.getElementById("follow-latest-dialog"),
    followCurrentFolderButton: document.getElementById("follow-current-folder-button"),
    followLatestFolderButton: document.getElementById("follow-latest-folder-button"),
    followCancelButton: document.getElementById("follow-cancel-button"),
    heroRankingDialog: document.getElementById("hero-ranking-dialog"),
    heroRankingCloseButton: document.getElementById("hero-ranking-close-button"),
    heroRankingList: document.getElementById("hero-ranking-list"),
    heroSkillsDialog: document.getElementById("hero-skills-dialog"),
    heroSkillsCloseButton: document.getElementById("hero-skills-close-button"),
    heroSkillsStatus: document.getElementById("hero-skills-status"),
    heroSkillsMeta: document.getElementById("hero-skills-meta"),
    heroSkillSlots: document.getElementById("hero-skill-slots"),
    heroSkillRecommendations: document.getElementById("hero-skill-recommendations"),
    heroSkillAvoid: document.getElementById("hero-skill-avoid"),
    heroSkillCompareControls: document.getElementById("hero-skill-compare-controls"),
    heroSkillCompareResult: document.getElementById("hero-skill-compare-result"),
    heroSkillsResetButton: document.getElementById("hero-skills-reset-button"),
    heroSkillsSaveButton: document.getElementById("hero-skills-save-button"),
    heroSkillsCompareButton: document.getElementById("hero-skills-compare-button")
  };
  const canvasContext = elements.canvas.getContext("2d");
  const TOWN_FACTION_NAMES = {
    0: "Castle",
    1: "Rampart",
    2: "Tower",
    3: "Inferno",
    4: "Necropolis",
    5: "Dungeon",
    6: "Stronghold",
    7: "Fortress",
    8: "Conflux"
  };
  const mapView = {
    snapshot: null,
    zoom: 1,
    minZoom: 0.35,
    maxZoom: 5,
    pan: { x: 0, y: 0 },
    level: 0,
    showRemovedNeutrals: false,
    showHiddenNeutrals: false,
    showRouteOverlay: true,
    pathMode: false,
    targetFilter: "both",
    markers: [],
    hoveredMarkerId: null,
    activeMarkerId: null,
    drag: null,
    movedDuringDrag: false
  };
  const heroState = {
    heroes: [],
    recentHeroes: [],
    searchQuery: "",
    selectedHeroId: null,
    selectingHeroId: null
  };
  const estimateState = {
    requestId: 0,
    runningTargetId: null
  };
  const scanState = {
    requestId: 0,
    running: false,
    heroId: null,
    radius: null,
    targetType: "all",
    hasRun: false,
    sortMode: "distance",
    rawResults: [],
    hoveredResultTargetId: null,
    results: [],
    resultByTargetId: new Map()
  };
  const pathState = {
    requestId: 0,
    running: false,
    result: null,
    target: null
  };
  const heroSkillsState = {
    requestId: 0,
    heroId: null,
    payload: null,
    slots: [],
    compareOffers: [
      { skill_id: "", level: "" },
      { skill_id: "", level: "" }
    ],
    loading: false,
    saving: false,
    comparing: false,
    dirty: false
  };
  const saveNavigation = {
    saves: []
  };
  const stateRequests = {
    epoch: 0,
    loading: false,
    loadingEpoch: 0,
    saveListRequestId: 0,
    saveModeRequestId: 0,
    gameFolderListRequestId: 0,
    gameFolderRequestId: 0,
    gameFolderInFlight: false,
    hiddenTargetInFlight: false,
    showHiddenInFlight: false,
    saveModeInFlight: false,
    autoRefreshRunning: false,
    autoRefreshTimer: null
  };
  const AUTO_REFRESH_MS = 5000;
  // Keep the polling path available, but require manual Refresh until UX settles.
  const AUTO_REFRESH_ENABLED = false;
  const FOLLOW_LATEST_MODE = "follow_latest";
  const PINNED_MODE = "pinned";
  const TARGET_FILTERS = [
    { id: "both", label: "Both", scanTargetType: "all" },
    { id: "heroes", label: "Heroes", scanTargetType: "hero" },
    { id: "monsters", label: "Monsters", scanTargetType: "neutral" }
  ];
  const TARGET_FILTER_BY_ID = new Map(
    TARGET_FILTERS.map((filter) => [filter.id, filter])
  );
  const SCAN_SORT_MODES = [
    { id: "distance", label: "Distance" },
    { id: "easiest", label: "Easiest" }
  ];
  const SCAN_SORT_MODE_BY_ID = new Map(
    SCAN_SORT_MODES.map((mode) => [mode.id, mode])
  );
  const PLAYER_COLOR_STYLES = {
    red: { fill: "#e11d2e", stroke: "#8f1220" },
    blue: { fill: "#2d6cdf", stroke: "#143a75" },
    tan: { fill: "#b98543", stroke: "#6b451f" },
    green: { fill: "#2f8f46", stroke: "#14532d" },
    orange: { fill: "#e07826", stroke: "#8a3c0b" },
    purple: { fill: "#7c3aed", stroke: "#4c1d95" },
    teal: { fill: "#0f9f9a", stroke: "#115e59" },
    pink: { fill: "#d85fa3", stroke: "#8f2a61" }
  };
  const ROUTE_OVERLAY_STYLES = {
    land: { fill: "#d9ead5", stroke: "#b7cfb0" },
    water: { fill: "#c8e2f2", stroke: "#9fc4dc" },
    blocked: { fill: "#87919e", stroke: "#66717e" }
  };
  const TOWN_MARKER_STYLE = {
    fill: "#f8c756",
    stroke: "#7a4d00",
    unownedFill: "#f4e7c4",
    unownedStroke: "#8a7654"
  };
  const PORTAL_MARKER_STYLES = {
    monolith_one_way: { fill: "#0f9f9a", stroke: "#115e59" },
    monolith_two_way: { fill: "#7c3aed", stroke: "#4c1d95" },
    subterranean_gate: { fill: "#d85fa3", stroke: "#8f2a61" },
    unknown: { fill: "#64748b", stroke: "#334155" }
  };

  function setHealth(text, className) {
    elements.health.textContent = text;
    elements.health.className = `status-pill ${className || ""}`.trim();
  }

  function setText(element, value) {
    element.textContent = value || "...";
    element.title = value || "";
  }

  function getJson(path, fallbackMessage) {
    return fetch(path)
      .then((response) => {
        if (!response.ok) {
          return response.json().catch(() => ({})).then((errorPayload) => {
            throw new Error(errorPayload.error || `${fallbackMessage}: ${response.status}`);
          });
        }
        return response.json();
      });
  }

  function postJson(path, payload, fallbackMessage) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then((response) => {
        if (!response.ok) {
          return response.json().catch(() => ({})).then((errorPayload) => {
            const error = new Error(
              errorPayload.error || `${fallbackMessage}: ${response.status}`
            );
            error.status = response.status;
            throw error;
          });
        }
        return response.json();
      });
  }

  function fileName(path) {
    if (!path) {
      return "None";
    }
    return String(path).split(/[\\/]/).pop() || String(path);
  }

  function modeLabel(mode) {
    if (mode === FOLLOW_LATEST_MODE) {
      return "Follow latest";
    }
    if (mode === PINNED_MODE) {
      return "Pinned save";
    }
    return mode || "unknown";
  }

  function currentSaveIndex(snapshot) {
    const current = snapshot || mapView.snapshot;
    if (!current || !current.save_file) {
      return -1;
    }
    return saveNavigation.saves.findIndex((save) => save.path === current.save_file);
  }

  function heroAiValue(hero) {
    return typeof hero.ai_value === "number" ? hero.ai_value : 0;
  }

  function nextStateEpoch() {
    stateRequests.epoch += 1;
    return stateRequests.epoch;
  }

  function snapshotChanged(current, next) {
    if (!current || !next) {
      return true;
    }
    return (
      current.mode !== next.mode
      || current.save_file !== next.save_file
      || current.save_fingerprint !== next.save_fingerprint
      || current.map_file !== next.map_file
      || current.map_fingerprint !== next.map_fingerprint
      || current.selected_hero_id !== next.selected_hero_id
      || current.show_hidden !== next.show_hidden
      || JSON.stringify(current.hidden_hero_target_ids || []) !== JSON.stringify(next.hidden_hero_target_ids || [])
    );
  }

  function positionText(position) {
    if (!position) {
      return "no position";
    }
    return `${position.x},${position.y},${position.z}`;
  }

  function normalizeName(value) {
    return String(value || "").trim().toLowerCase();
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function clampZoom(zoom, minZoom, maxZoom) {
    return clamp(zoom, minZoom, maxZoom);
  }

  function worldToScreen(point, view) {
    return {
      x: point.x * view.zoom + view.pan.x,
      y: point.y * view.zoom + view.pan.y
    };
  }

  function screenToWorld(point, view) {
    return {
      x: (point.x - view.pan.x) / view.zoom,
      y: (point.y - view.pan.y) / view.zoom
    };
  }

  function zoomAtPoint(view, screenPoint, nextZoom) {
    const clampedZoom = clampZoom(nextZoom, view.minZoom, view.maxZoom);
    const worldPoint = screenToWorld(screenPoint, view);
    return {
      zoom: clampedZoom,
      pan: {
        x: screenPoint.x - worldPoint.x * clampedZoom,
        y: screenPoint.y - worldPoint.y * clampedZoom
      }
    };
  }

  function tileSizeForMap(map) {
    const width = Math.max(1, map && map.width ? map.width : 1);
    const height = Math.max(1, map && map.height ? map.height : width);
    const largest = Math.max(width, height);
    return clamp(720 / largest, 6, 28);
  }

  function mapLevelCount(snapshot) {
    const levels = snapshot && snapshot.map && snapshot.map.levels
      ? Number(snapshot.map.levels)
      : 1;
    return Math.max(1, Number.isInteger(levels) ? levels : 1);
  }

  function positionLevel(position) {
    if (!position) {
      return 0;
    }
    const level = Number(position.z);
    return Number.isInteger(level) ? level : 0;
  }

  function normalizeLevelForSnapshot(level, snapshot) {
    const numeric = Number(level);
    const requested = Number.isInteger(numeric) ? numeric : 0;
    return clamp(requested, 0, mapLevelCount(snapshot) - 1);
  }

  function normalizeTargetFilter(filter) {
    return TARGET_FILTER_BY_ID.has(filter) ? filter : "both";
  }

  function scanTargetTypeForFilter(filter) {
    return TARGET_FILTER_BY_ID.get(normalizeTargetFilter(filter)).scanTargetType;
  }

  function normalizeScanSortMode(mode) {
    return SCAN_SORT_MODE_BY_ID.has(mode) ? mode : "distance";
  }

  function heroById(snapshot, heroId) {
    if (!snapshot || !heroId) {
      return null;
    }
    return (snapshot.heroes || []).find((hero) => hero.id === heroId) || null;
  }

  function defaultLevelForSnapshot(snapshot, selectedHeroId) {
    const hero = heroById(snapshot, selectedHeroId);
    if (hero && hero.position) {
      return normalizeLevelForSnapshot(positionLevel(hero.position), snapshot);
    }
    return 0;
  }

  function sameMapGeometry(previous, next) {
    const previousMap = previous && previous.map ? previous.map : null;
    const nextMap = next && next.map ? next.map : null;
    if (!previousMap || !nextMap) {
      return false;
    }
    return (
      previousMap.width === nextMap.width
      && previousMap.height === nextMap.height
      && mapLevelCount(previous) === mapLevelCount(next)
    );
  }

  function routeRowsForLevel(snapshot, level) {
    const routeLayers = snapshot && Array.isArray(snapshot.route_layers)
      ? snapshot.route_layers
      : [];
    const activeLevel = normalizeLevelForSnapshot(level, snapshot);
    const rows = routeLayers[activeLevel];
    return Array.isArray(rows) ? rows : [];
  }

  function routeStateForChar(char) {
    if (char === "L") {
      return "land";
    }
    if (char === "W") {
      return "water";
    }
    if (char === "B") {
      return "blocked";
    }
    return null;
  }

  function routeStyleForChar(char) {
    const state = routeStateForChar(char);
    return state ? ROUTE_OVERLAY_STYLES[state] : null;
  }

  function truncateText(value, maxLength) {
    const text = String(value || "").trim();
    if (!text || text.length <= maxLength) {
      return text;
    }
    return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}...`;
  }

  function titleCase(value) {
    const text = String(value || "").trim();
    if (!text) {
      return "";
    }
    return `${text.charAt(0).toUpperCase()}${text.slice(1)}`;
  }

  function playerColorStyle(colorName) {
    return PLAYER_COLOR_STYLES[String(colorName || "").toLowerCase()] || {
      fill: "#64748b",
      stroke: "#334155"
    };
  }

  function heroOwnerText(hero) {
    if (!hero || !hero.owner_color_name) {
      return "No owner";
    }
    const team = typeof hero.team_id === "number" ? `team ${hero.team_id}` : "no team";
    return `${titleCase(hero.owner_color_name)} ${team}`;
  }

  function heroRelation(hero, snapshot) {
    if (!hero || !snapshot || !snapshot.selected_hero_id) {
      return null;
    }
    const selected = heroById(snapshot, snapshot.selected_hero_id);
    if (!selected) {
      return null;
    }
    if (hero.id === selected.id) {
      return "selected";
    }
    if (
      typeof hero.owner_color_id !== "number"
      || typeof selected.owner_color_id !== "number"
    ) {
      return "unknown";
    }
    if (hero.owner_color_id === selected.owner_color_id) {
      return "ally";
    }
    if (
      typeof hero.team_id === "number"
      && typeof selected.team_id === "number"
      && hero.team_id === selected.team_id
    ) {
      return "ally";
    }
    return "enemy";
  }

  function markerOwnerText(marker) {
    if (!marker || marker.type !== "hero") {
      return "";
    }
    const color = marker.ownerColorName ? titleCase(marker.ownerColorName) : "No owner";
    const team = typeof marker.teamId === "number" ? `team ${marker.teamId}` : "no team";
    const relation = marker.relation && marker.relation !== "selected"
      ? marker.relation
      : "";
    return [color, team, relation].filter(Boolean).join(" ");
  }

  function townFactionText(marker) {
    if (!marker || marker.type !== "town") {
      return "";
    }
    if (typeof marker.factionSubid === "number") {
      const factionName = TOWN_FACTION_NAMES[marker.factionSubid] || "Unknown faction";
      return `Faction: ${factionName} (subid ${marker.factionSubid}/${marker.h3mSubid})`;
    }
    if (typeof marker.h3mSubid === "number") {
      return `Random town subid: ${marker.h3mSubid}`;
    }
    return "Random town";
  }

  function townInitialOwnerText(marker) {
    if (!marker || marker.type !== "town") {
      return "";
    }
    if (marker.initialOwnerColorName) {
      return `Initial owner: ${titleCase(marker.initialOwnerColorName)}`;
    }
    return "Initial owner: none";
  }

  function townGarrisonText(marker) {
    if (!marker || marker.type !== "town") {
      return "";
    }
    return marker.hasGarrison ? "garrison present" : "";
  }

  function townSummaryParts(marker) {
    return [
      townFactionText(marker),
      townInitialOwnerText(marker),
      townGarrisonText(marker)
    ].filter(Boolean);
  }

  function townSummaryText(marker) {
    return townSummaryParts(marker).join(" | ");
  }

  function portalTypeLabel(portalType) {
    if (portalType === "monolith_one_way") {
      return "One-way monolith";
    }
    if (portalType === "monolith_two_way") {
      return "Two-way monolith";
    }
    if (portalType === "subterranean_gate") {
      return "Subterranean gate";
    }
    return "Portal";
  }

  function portalRoleLabel(role) {
    if (role === "entrance") {
      return "entrance";
    }
    if (role === "exit") {
      return "exit";
    }
    return "";
  }

  function portalMarkerLabel(portal) {
    const typeLabel = portalTypeLabel(portal.portal_type);
    const roleLabel = portalRoleLabel(portal.role);
    return roleLabel ? `${typeLabel} ${roleLabel}` : typeLabel;
  }

  function portalDestinationText(marker) {
    if (!marker || marker.type !== "portal") {
      return "";
    }
    const destinations = marker.destinations || [];
    if (destinations.length === 0) {
      return "Destinations: none";
    }
    return `Destinations: ${destinations.map((destination) => (
      positionText(destination.position)
    )).join("; ")}`;
  }

  function portalSummaryParts(marker) {
    if (!marker || marker.type !== "portal") {
      return [];
    }
    return [
      `${portalTypeLabel(marker.portalType)}${portalRoleLabel(marker.role) ? ` ${portalRoleLabel(marker.role)}` : ""}`,
      typeof marker.h3mSubid === "number" ? `subid ${marker.h3mSubid}` : "",
      marker.channelKey ? `channel ${marker.channelKey}` : "",
      portalDestinationText(marker)
    ].filter(Boolean);
  }

  function portalStyleForType(portalType) {
    return PORTAL_MARKER_STYLES[portalType] || PORTAL_MARKER_STYLES.unknown;
  }

  function portalTargetsById(snapshot) {
    const targets = new Map();
    (snapshot.portal_targets || []).forEach((target) => {
      if (target && target.id) {
        targets.set(target.id, target);
      }
    });
    return targets;
  }

  function portalDestinationsForTarget(snapshot, portal, targetsById) {
    if (!snapshot || !portal || !portal.id) {
      return [];
    }
    const lookup = targetsById || portalTargetsById(snapshot);
    return (snapshot.portal_edges || [])
      .filter((edge) => edge && edge.source_id === portal.id)
      .map((edge) => {
        const target = lookup.get(edge.destination_id);
        if (!target || !target.position) {
          return null;
        }
        return {
          id: target.id,
          label: portalMarkerLabel(target),
          position: target.position,
          portalType: target.portal_type,
          role: target.role,
          edge
        };
      })
      .filter(Boolean);
  }

  function appendColorSwatch(parent, colorName) {
    const swatch = document.createElement("span");
    const style = playerColorStyle(colorName);
    swatch.className = "color-swatch";
    swatch.style.backgroundColor = style.fill;
    swatch.style.borderColor = style.stroke;
    swatch.title = colorName ? titleCase(colorName) : "No owner";
    parent.appendChild(swatch);
  }

  function markerTooltipText(marker) {
    if (!marker) {
      return "";
    }
    if (marker.type === "hero") {
      return [
        marker.label,
        markerOwnerText(marker),
        positionText(marker.position),
        `${marker.creatureCount || 0} creatures`,
        truncateText(marker.summary, 90)
      ].filter(Boolean).join(" | ");
    }
    if (marker.type === "town") {
      return [
        marker.label,
        positionText(marker.position),
        ...townSummaryParts(marker)
      ].filter(Boolean).join(" | ");
    }
    if (marker.type === "portal") {
      return [
        marker.label,
        positionText(marker.position),
        ...portalSummaryParts(marker)
      ].filter(Boolean).join(" | ");
    }

    const flags = [];
    if (marker.removed) {
      flags.push("removed");
    }
    if (marker.hidden) {
      flags.push("hidden");
    }
    if (marker.unsupported) {
      flags.push("unsupported");
    }
    return [
      marker.label,
      positionText(marker.position),
      flags.join(", "),
      truncateText(marker.summary, 90)
    ].filter(Boolean).join(" | ");
  }

  function buildMarkerCache(
    snapshot,
    tileSize,
    level,
    showRemovedNeutrals,
    showHiddenTargets,
    targetFilter
  ) {
    if (!snapshot) {
      return [];
    }

    const selectedHeroId = snapshot.selected_hero_id;
    const activeLevel = normalizeLevelForSnapshot(level, snapshot);
    const normalizedTargetFilter = normalizeTargetFilter(targetFilter);
    const includeHeroes = normalizedTargetFilter !== "monsters";
    const includeNeutrals = normalizedTargetFilter !== "heroes";
    const includeHiddenTargets = typeof showHiddenTargets === "boolean"
      ? showHiddenTargets
      : Boolean(snapshot.show_hidden);
    const portalTargetLookup = portalTargetsById(snapshot);
    const heroMarkers = includeHeroes
      ? (snapshot.heroes || [])
        .filter((hero) => hero.position)
        .filter((hero) => positionLevel(hero.position) === activeLevel)
        .filter((hero) => includeHiddenTargets || !hero.hidden)
        .map((hero) => ({
          type: "hero",
          id: hero.id,
          label: hero.name || hero.id,
          position: hero.position,
          ownerColorId: hero.owner_color_id,
          ownerColorName: hero.owner_color_name,
          teamId: hero.team_id,
          relation: heroRelation(hero, snapshot),
          world: {
            x: (hero.position.x + 0.5) * tileSize,
            y: (hero.position.y + 0.5) * tileSize
          },
          radius: 8,
          selected: hero.id === selectedHeroId,
          removed: false,
          hidden: Boolean(hero.hidden),
          unsupported: false,
          creatureCount: hero.total_creatures || 0,
          summary: hero.army_summary || ""
        }))
      : [];

    const townMarkers = (snapshot.town_targets || [])
      .filter((town) => town.position)
      .filter((town) => positionLevel(town.position) === activeLevel)
      .map((town) => {
        const marker = {
          type: "town",
          id: town.id,
          label: town.custom_name
            || (typeof town.faction_subid === "number"
              ? `${TOWN_FACTION_NAMES[town.faction_subid] || "Unknown"} town`
              : "Random town"),
          position: town.position,
          world: {
            x: (town.position.x + 0.5) * tileSize,
            y: (town.position.y + 0.5) * tileSize
          },
          radius: 9,
          selected: false,
          removed: false,
          hidden: false,
          unsupported: false,
          objectId: town.object_id,
          h3mSubid: town.h3m_subid,
          factionSubid: town.faction_subid,
          initialOwner: town.initial_owner,
          initialOwnerColorName: town.initial_owner_color_name,
          hasGarrison: Boolean(town.has_garrison),
          summary: ""
        };
        marker.summary = townSummaryText(marker);
        return marker;
      });

    const portalMarkers = (snapshot.portal_targets || [])
      .filter((portal) => portal.position)
      .filter((portal) => positionLevel(portal.position) === activeLevel)
      .map((portal) => {
        const marker = {
          type: "portal",
          id: portal.id,
          label: portalMarkerLabel(portal),
          position: portal.position,
          world: {
            x: (portal.position.x + 0.5) * tileSize,
            y: (portal.position.y + 0.5) * tileSize
          },
          radius: 8,
          selected: false,
          removed: false,
          hidden: false,
          unsupported: false,
          objectIndex: portal.object_index,
          objectId: portal.object_id,
          h3mSubid: portal.h3m_subid,
          portalType: portal.portal_type,
          role: portal.role,
          channelKey: portal.channel_key,
          destinations: portalDestinationsForTarget(snapshot, portal, portalTargetLookup),
          summary: ""
        };
        marker.summary = portalSummaryParts(marker).join(" | ");
        return marker;
      });

    const neutralMarkers = includeNeutrals
      ? (snapshot.neutral_targets || [])
        .filter((target) => target.position)
        .filter((target) => positionLevel(target.position) === activeLevel)
        .filter((target) => showRemovedNeutrals || !target.removed)
        .filter((target) => includeHiddenTargets || !target.hidden)
        .map((target) => ({
          type: "neutral",
          id: target.id,
          label: `${target.count || 0}x ${target.creature_name || "Unknown"}`,
          position: target.position,
          world: {
            x: (target.position.x + 0.5) * tileSize,
            y: (target.position.y + 0.5) * tileSize
          },
          radius: 7,
          selected: false,
          removed: Boolean(target.removed),
          hidden: Boolean(target.hidden),
          unsupported: target.estimator_creature_id === null,
          summary: target.removal_note || `subid ${target.h3m_subid}`
        }))
      : [];

    return townMarkers.concat(portalMarkers, heroMarkers, neutralMarkers);
  }

  function hitTestMarker(markers, screenPoint, view) {
    for (let index = markers.length - 1; index >= 0; index -= 1) {
      const marker = markers[index];
      const markerScreen = worldToScreen(marker.world, view);
      const dx = screenPoint.x - markerScreen.x;
      const dy = screenPoint.y - markerScreen.y;
      if (markerContainsScreenPoint(marker, dx, dy, view)) {
        return marker;
      }
    }
    return null;
  }

  function markerScreenRadius(marker, view) {
    return Math.max(5, marker.radius * Math.sqrt(view.zoom)) + 3;
  }

  function markerContainsScreenPoint(marker, dx, dy, view) {
    const radius = markerScreenRadius(marker, view);
    if (marker.type === "hero") {
      return Math.abs(dx) + Math.abs(dy) <= (radius * Math.SQRT2);
    }
    if (marker.type === "town") {
      return Math.abs(dx) <= radius && Math.abs(dy) <= radius;
    }
    if (marker.type === "portal") {
      return Math.abs(dx) <= radius && Math.abs(dy) <= radius;
    }
    return (dx * dx) + (dy * dy) <= radius * radius;
  }

  function canvasPoint(event) {
    const rect = elements.canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top
    };
  }

  function tilePositionForCanvasPoint(point, snapshot, view) {
    const current = snapshot || mapView.snapshot;
    const activeView = view || mapView;
    if (!current || !current.map) {
      return null;
    }
    const tileSize = tileSizeForMap(current.map);
    const worldPoint = screenToWorld(point, activeView);
    const x = Math.floor(worldPoint.x / tileSize);
    const y = Math.floor(worldPoint.y / tileSize);
    const width = Math.max(1, current.map.width || 1);
    const height = Math.max(1, current.map.height || width);
    if (x < 0 || y < 0 || x >= width || y >= height) {
      return null;
    }
    return {
      x,
      y,
      z: normalizeLevelForSnapshot(activeView.level, current)
    };
  }

  function syncCanvasSize() {
    const rect = elements.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(rect.width * dpr));
    const height = Math.max(1, Math.round(rect.height * dpr));
    if (elements.canvas.width !== width || elements.canvas.height !== height) {
      elements.canvas.width = width;
      elements.canvas.height = height;
    }
    canvasContext.setTransform(dpr, 0, 0, dpr, 0, 0);
    return {
      width: rect.width,
      height: rect.height,
      dpr
    };
  }

  function mapWorldSize(snapshot) {
    const map = snapshot && snapshot.map ? snapshot.map : {};
    const tileSize = tileSizeForMap(map);
    const width = Math.max(1, map.width || 1);
    const height = Math.max(1, map.height || width);
    return {
      tileSize,
      width: width * tileSize,
      height: height * tileSize
    };
  }

  function fitMapToCanvas(snapshot) {
    if (!snapshot) {
      return;
    }
    const canvasSize = syncCanvasSize();
    const worldSize = mapWorldSize(snapshot);
    const fitZoom = clamp(
      Math.min(
        canvasSize.width / worldSize.width,
        canvasSize.height / worldSize.height
      ) * 0.9,
      mapView.minZoom,
      mapView.maxZoom
    );
    mapView.zoom = fitZoom;
    mapView.pan = {
      x: (canvasSize.width - worldSize.width * fitZoom) / 2,
      y: (canvasSize.height - worldSize.height * fitZoom) / 2
    };
  }

  function rebuildMarkerCache(snapshot) {
    const current = snapshot || mapView.snapshot;
    const tileSize = tileSizeForMap((current && current.map) || {});
    mapView.level = normalizeLevelForSnapshot(mapView.level, current);
    mapView.markers = buildMarkerCache(
      current,
      tileSize,
      mapView.level,
      mapView.showRemovedNeutrals,
      mapView.showHiddenNeutrals,
      mapView.targetFilter
    );
  }

  function markerCounts(markers) {
    return (markers || []).reduce((counts, marker) => {
      if (marker.type === "hero") {
        counts.heroes += 1;
      } else if (marker.type === "town") {
        counts.towns += 1;
      } else if (marker.type === "portal") {
        counts.portals += 1;
      } else if (marker.type === "neutral") {
        counts.neutrals += 1;
      }
      return counts;
    }, { heroes: 0, towns: 0, portals: 0, neutrals: 0 });
  }

  function snapshotDimensions(snapshot) {
    const map = snapshot && snapshot.map ? snapshot.map : {};
    return map.width && map.height
      ? `${map.width} x ${map.height} x ${map.levels || 1}`
      : "No map";
  }

  function updateMapMetrics(snapshot) {
    const current = snapshot || mapView.snapshot;
    const counts = markerCounts(mapView.markers);
    const dimensions = snapshotDimensions(current);
    setText(elements.mapSummary, `${dimensions} | Level ${mapView.level}`);
    setText(
      elements.objectCount,
      `${counts.neutrals} targets | ${counts.towns} towns | ${counts.portals} portals`
    );
    setText(elements.mapOverlayTitle, dimensions);
    setText(
      elements.mapOverlayDetail,
      `Level ${mapView.level} | ${counts.heroes} heroes | ${counts.neutrals} neutrals | ${counts.towns} towns | ${counts.portals} portals`
    );
  }

  function updateLevelControls(snapshot) {
    const current = snapshot || mapView.snapshot;
    clearNode(elements.mapLevelControl);
    if (!current || !current.map) {
      return;
    }

    for (let level = 0; level < mapLevelCount(current); level += 1) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = String(level);
      button.className = level === mapView.level ? "active" : "";
      button.setAttribute("aria-pressed", level === mapView.level ? "true" : "false");
      button.addEventListener("click", () => setMapLevel(level));
      elements.mapLevelControl.appendChild(button);
    }
  }

  function renderTargetFilterControl() {
    clearNode(elements.targetFilterControl);
    TARGET_FILTERS.forEach((filter) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = filter.label;
      button.className = filter.id === mapView.targetFilter ? "active" : "";
      button.disabled = !mapView.snapshot || scanState.running;
      button.setAttribute("aria-pressed", filter.id === mapView.targetFilter ? "true" : "false");
      button.addEventListener("click", () => setTargetFilter(filter.id));
      elements.targetFilterControl.appendChild(button);
    });
  }

  function renderScanSortControl() {
    clearNode(elements.scanSortControl);
    SCAN_SORT_MODES.forEach((mode) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = mode.label;
      button.className = mode.id === scanState.sortMode ? "active" : "";
      button.disabled = !mapView.snapshot;
      button.setAttribute("aria-pressed", mode.id === scanState.sortMode ? "true" : "false");
      button.addEventListener("click", () => setScanSortMode(mode.id));
      elements.scanSortControl.appendChild(button);
    });
  }

  function updatePathModeControl() {
    elements.pathModeToggle.checked = mapView.pathMode;
    elements.pathModeToggle.disabled = !mapView.snapshot;
    elements.canvas.classList.toggle("path-mode", mapView.pathMode);
  }

  function setPathMode(enabled) {
    const nextValue = Boolean(enabled && mapView.snapshot);
    if (nextValue === mapView.pathMode) {
      updatePathModeControl();
      return;
    }
    mapView.pathMode = nextValue;
    updatePathModeControl();
    if (!mapView.pathMode) {
      clearPathResult("No path requested.");
    }
  }

  function setScanSortMode(mode) {
    const normalized = normalizeScanSortMode(mode);
    if (normalized === scanState.sortMode) {
      return;
    }
    scanState.sortMode = normalized;
    renderScanSortControl();
    if (scanState.rawResults.length > 0) {
      renderScanResultRows();
    }
  }

  function setTargetFilter(filter) {
    const normalized = normalizeTargetFilter(filter);
    if (normalized === mapView.targetFilter) {
      return;
    }

    mapView.targetFilter = normalized;
    mapView.hoveredMarkerId = null;
    elements.canvas.classList.remove("has-marker-hover");
    hideMapTooltip();
    hideTargetContextMenu();
    rebuildMarkerCache(mapView.snapshot);
    if (!mapView.markers.some((marker) => marker.id === mapView.activeMarkerId)) {
      mapView.activeMarkerId = null;
      setTargetDetails(null);
    }
    updateMapMetrics(mapView.snapshot);
    clearScanResults("No scan results.");
  }

  function setMapLevel(level) {
    mapView.level = normalizeLevelForSnapshot(level, mapView.snapshot);
    mapView.hoveredMarkerId = null;
    scanState.hoveredResultTargetId = null;
    elements.canvas.classList.remove("has-marker-hover");
    hideMapTooltip();
    rebuildMarkerCache(mapView.snapshot);
    if (!mapView.markers.some((marker) => marker.id === mapView.activeMarkerId)) {
      mapView.activeMarkerId = null;
      setTargetDetails(null);
    }
    updateLevelControls(mapView.snapshot);
    updateMapMetrics(mapView.snapshot);
    drawMap();
  }

  function hideMapTooltip() {
    elements.mapTooltip.hidden = true;
    elements.mapTooltip.textContent = "";
  }

  function showMapTooltip(marker, event) {
    const text = markerTooltipText(marker);
    if (!text) {
      hideMapTooltip();
      return;
    }
    const stageRect = elements.mapStage.getBoundingClientRect();
    const x = clamp(event.clientX - stageRect.left + 12, 8, Math.max(8, stageRect.width - 24));
    const y = clamp(event.clientY - stageRect.top + 12, 8, Math.max(8, stageRect.height - 24));
    elements.mapTooltip.textContent = text;
    elements.mapTooltip.style.left = `${x}px`;
    elements.mapTooltip.style.top = `${y}px`;
    elements.mapTooltip.hidden = false;
  }

  function hideTargetContextMenu() {
    elements.targetContextMenu.hidden = true;
    clearNode(elements.targetContextMenu);
  }

  function showTargetContextMenu(marker, event) {
    if (
      !marker
      || (
        marker.type !== "neutral"
        && marker.type !== "hero"
        && marker.type !== "portal"
      )
    ) {
      hideTargetContextMenu();
      return;
    }

    clearNode(elements.targetContextMenu);
    const title = document.createElement("div");
    title.className = "context-menu-title";
    title.textContent = marker.label || marker.id;
    title.title = markerTooltipText(marker);
    elements.targetContextMenu.appendChild(title);

    if (marker.type === "portal") {
      const destinations = marker.destinations || [];
      if (destinations.length === 0) {
        elements.targetContextMenu.appendChild(contextMenuText("No known destinations"));
      }
      destinations.forEach((destination) => {
        elements.targetContextMenu.appendChild(
          contextMenuButton(
            `Center ${positionText(destination.position)}`,
            () => focusPortalDestination(destination.id)
          )
        );
      });
    } else if (marker.type === "hero") {
      if (marker.selected) {
        elements.targetContextMenu.appendChild(contextMenuText("Current hero"));
      } else {
        elements.targetContextMenu.appendChild(
          contextMenuButton("Select as my hero", () => selectHero(marker.id))
        );
        if (!marker.hidden) {
          elements.targetContextMenu.appendChild(
            contextMenuButton("Simulate", () => simulateTarget(marker))
          );
          elements.targetContextMenu.appendChild(
            contextMenuButton("Hide", () => setHiddenTarget(marker, true))
          );
        } else {
          elements.targetContextMenu.appendChild(
            contextMenuButton("Unhide", () => setHiddenTarget(marker, false))
          );
        }
      }
    } else if (!marker.hidden) {
      elements.targetContextMenu.appendChild(
        contextMenuButton("Simulate", () => simulateTarget(marker))
      );
      elements.targetContextMenu.appendChild(
        contextMenuButton("Hide", () => setHiddenTarget(marker, true))
      );
    } else {
      elements.targetContextMenu.appendChild(
        contextMenuButton("Unhide", () => setHiddenTarget(marker, false))
      );
    }

    const stageRect = elements.mapStage.getBoundingClientRect();
    const x = clamp(event.clientX - stageRect.left, 8, Math.max(8, stageRect.width - 180));
    const y = clamp(event.clientY - stageRect.top, 8, Math.max(8, stageRect.height - 120));
    elements.targetContextMenu.style.left = `${x}px`;
    elements.targetContextMenu.style.top = `${y}px`;
    elements.targetContextMenu.hidden = false;
  }

  function contextMenuText(text) {
    const item = document.createElement("div");
    item.className = "context-menu-note";
    item.textContent = text;
    item.title = text;
    return item;
  }

  function contextMenuButton(label, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", () => {
      hideTargetContextMenu();
      return onClick();
    });
    return button;
  }

  function centerOnHero(heroId) {
    const marker = mapView.markers.find((candidate) => (
      candidate.type === "hero" && candidate.id === heroId
    ));
    return centerOnMarker(marker);
  }

  function centerOnMarkerId(targetId) {
    let marker = mapView.markers.find((candidate) => candidate.id === targetId);
    if (!marker) {
      const targetPosition = positionForTargetId(mapView.snapshot, targetId);
      if (targetPosition) {
        mapView.level = normalizeLevelForSnapshot(positionLevel(targetPosition), mapView.snapshot);
        rebuildMarkerCache(mapView.snapshot);
        updateLevelControls(mapView.snapshot);
        updateMapMetrics(mapView.snapshot);
        marker = mapView.markers.find((candidate) => candidate.id === targetId);
      }
    }
    if (centerOnMarker(marker)) {
      return marker;
    }
    return null;
  }

  function focusPortalDestination(targetId) {
    const marker = centerOnMarkerId(targetId);
    mapView.activeMarkerId = marker ? marker.id : (targetId || null);
    if (marker) {
      setTargetDetails(marker);
    }
    drawMap();
    return marker;
  }

  function positionForTargetId(snapshot, targetId) {
    if (!snapshot || !targetId) {
      return null;
    }
    const hero = (snapshot.heroes || []).find((candidate) => candidate.id === targetId);
    if (hero && hero.position) {
      return hero.position;
    }
    const neutral = (snapshot.neutral_targets || []).find((candidate) => candidate.id === targetId);
    if (neutral && neutral.position) {
      return neutral.position;
    }
    const town = (snapshot.town_targets || []).find((candidate) => candidate.id === targetId);
    if (town && town.position) {
      return town.position;
    }
    const portal = (snapshot.portal_targets || []).find((candidate) => candidate.id === targetId);
    return portal && portal.position ? portal.position : null;
  }

  function centerOnMarker(marker) {
    if (!marker) {
      return false;
    }
    return centerOnWorldPoint(marker.world);
  }

  function centerOnWorldPoint(worldPoint) {
    if (!worldPoint) {
      return false;
    }
    const canvasSize = syncCanvasSize();
    mapView.pan = {
      x: (canvasSize.width / 2) - (worldPoint.x * mapView.zoom),
      y: (canvasSize.height / 2) - (worldPoint.y * mapView.zoom)
    };
    drawMap();
    return true;
  }

  function drawMap() {
    const canvasSize = syncCanvasSize();
    canvasContext.clearRect(0, 0, canvasSize.width, canvasSize.height);
    canvasContext.fillStyle = "#eef2f6";
    canvasContext.fillRect(0, 0, canvasSize.width, canvasSize.height);

    if (!mapView.snapshot || !mapView.snapshot.map) {
      return;
    }

    const map = mapView.snapshot.map;
    const worldSize = mapWorldSize(mapView.snapshot);
    const width = Math.max(1, map.width || 1);
    const height = Math.max(1, map.height || width);
    const tileSize = worldSize.tileSize;
    const topLeft = worldToScreen({ x: 0, y: 0 }, mapView);
    const bottomRight = worldToScreen(
      { x: width * tileSize, y: height * tileSize },
      mapView
    );

    canvasContext.fillStyle = "#f8fafc";
    canvasContext.fillRect(
      topLeft.x,
      topLeft.y,
      bottomRight.x - topLeft.x,
      bottomRight.y - topLeft.y
    );

    if (mapView.showRouteOverlay) {
      drawRouteOverlay(mapView.snapshot, tileSize, width, height);
    }

    canvasContext.strokeStyle = "#d4dbe4";
    canvasContext.lineWidth = 1;
    canvasContext.beginPath();
    for (let x = 0; x <= width; x += 1) {
      const screen = worldToScreen({ x: x * tileSize, y: 0 }, mapView);
      canvasContext.moveTo(screen.x, topLeft.y);
      canvasContext.lineTo(screen.x, bottomRight.y);
    }
    for (let y = 0; y <= height; y += 1) {
      const screen = worldToScreen({ x: 0, y: y * tileSize }, mapView);
      canvasContext.moveTo(topLeft.x, screen.y);
      canvasContext.lineTo(bottomRight.x, screen.y);
    }
    canvasContext.stroke();

    drawPathRoute(tileSize);
    drawMarkers();
    elements.zoom.textContent = `Zoom ${Math.round(mapView.zoom * 100)}%`;
  }

  function drawRouteOverlay(snapshot, tileSize, width, height) {
    const rows = routeRowsForLevel(snapshot, mapView.level);
    if (rows.length === 0) {
      return;
    }

    canvasContext.save();
    canvasContext.globalAlpha = 0.72;
    for (let y = 0; y < height && y < rows.length; y += 1) {
      const row = typeof rows[y] === "string" ? rows[y] : "";
      const rowWidth = Math.min(width, row.length);
      for (let x = 0; x < rowWidth; x += 1) {
        const style = routeStyleForChar(row.charAt(x));
        if (!style) {
          continue;
        }
        const topLeft = worldToScreen({ x: x * tileSize, y: y * tileSize }, mapView);
        const bottomRight = worldToScreen(
          { x: (x + 1) * tileSize, y: (y + 1) * tileSize },
          mapView
        );
        canvasContext.fillStyle = style.fill;
        canvasContext.fillRect(
          topLeft.x,
          topLeft.y,
          bottomRight.x - topLeft.x,
          bottomRight.y - topLeft.y
        );
      }
    }
    canvasContext.restore();
  }

  function pathStepPosition(step) {
    return step && step.position ? step.position : null;
  }

  function pathPointForPosition(position, tileSize) {
    return {
      x: (position.x + 0.5) * tileSize,
      y: (position.y + 0.5) * tileSize
    };
  }

  function drawPathRoute(tileSize) {
    const result = pathState.result;
    if (!result || result.status !== "found" || !Array.isArray(result.steps)) {
      return;
    }
    const positions = result.steps
      .map(pathStepPosition)
      .filter(Boolean);
    if (positions.length === 0) {
      return;
    }

    canvasContext.save();
    canvasContext.lineCap = "round";
    canvasContext.lineJoin = "round";
    canvasContext.strokeStyle = "#ffffff";
    canvasContext.lineWidth = 7;
    canvasContext.beginPath();
    let hasLine = false;
    for (let index = 0; index < positions.length - 1; index += 1) {
      const current = positions[index];
      const next = positions[index + 1];
      if (current.z !== mapView.level || next.z !== mapView.level) {
        continue;
      }
      const from = worldToScreen(pathPointForPosition(current, tileSize), mapView);
      const to = worldToScreen(pathPointForPosition(next, tileSize), mapView);
      canvasContext.moveTo(from.x, from.y);
      canvasContext.lineTo(to.x, to.y);
      hasLine = true;
    }
    if (hasLine) {
      canvasContext.stroke();
      canvasContext.strokeStyle = "#dc2626";
      canvasContext.lineWidth = 3;
      canvasContext.stroke();
    }

    positions.forEach((position) => {
      if (position.z !== mapView.level) {
        return;
      }
      const screen = worldToScreen(pathPointForPosition(position, tileSize), mapView);
      canvasContext.beginPath();
      canvasContext.fillStyle = "#dc2626";
      canvasContext.strokeStyle = "#ffffff";
      canvasContext.lineWidth = 2;
      canvasContext.arc(screen.x, screen.y, 4, 0, Math.PI * 2);
      canvasContext.fill();
      canvasContext.stroke();
    });
    canvasContext.restore();
  }

  function drawMarkerRing(screen, radius, strokeStyle, lineWidth) {
    canvasContext.beginPath();
    canvasContext.strokeStyle = strokeStyle;
    canvasContext.lineWidth = lineWidth;
    canvasContext.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
    canvasContext.stroke();
  }

  function drawMarkers() {
    mapView.markers.forEach((marker) => {
      const screen = worldToScreen(marker.world, mapView);
      const radius = markerScreenRadius(marker, mapView) - 3;
      const isActive = marker.id === mapView.activeMarkerId;
      const isHover = marker.id === mapView.hoveredMarkerId;
      const scanColors = scanColorsForMarker(marker);
      const ownerColors = playerColorStyle(marker.ownerColorName);

      canvasContext.save();
      canvasContext.globalAlpha = marker.hidden ? 0.32 : (marker.removed ? 0.45 : 1);
      if (marker.type === "hero") {
        canvasContext.translate(screen.x, screen.y);
        canvasContext.rotate(Math.PI / 4);
        canvasContext.fillStyle = marker.selected
          ? "#f5c542"
          : ownerColors.fill;
        canvasContext.strokeStyle = marker.selected
          ? "#7a4d00"
          : ownerColors.stroke;
        canvasContext.lineWidth = marker.selected ? 3 : 2;
        canvasContext.fillRect(-radius, -radius, radius * 2, radius * 2);
        canvasContext.strokeRect(-radius, -radius, radius * 2, radius * 2);
        canvasContext.rotate(-Math.PI / 4);
        canvasContext.translate(-screen.x, -screen.y);
        if (marker.selected) {
          drawMarkerRing(screen, radius + 7, "#7a4d00", 2);
        }
      } else if (marker.type === "town") {
        const townOwnerColors = playerColorStyle(marker.initialOwnerColorName);
        const hasOwner = Boolean(marker.initialOwnerColorName);
        const bodyFill = hasOwner ? townOwnerColors.fill : TOWN_MARKER_STYLE.unownedFill;
        const bodyStroke = hasOwner ? townOwnerColors.stroke : TOWN_MARKER_STYLE.unownedStroke;
        canvasContext.fillStyle = TOWN_MARKER_STYLE.fill;
        canvasContext.strokeStyle = TOWN_MARKER_STYLE.stroke;
        canvasContext.lineWidth = 2;
        canvasContext.fillRect(
          screen.x - radius * 0.72,
          screen.y - radius,
          radius * 1.44,
          radius * 0.48
        );
        canvasContext.strokeRect(
          screen.x - radius * 0.72,
          screen.y - radius,
          radius * 1.44,
          radius * 0.48
        );
        canvasContext.fillStyle = bodyFill;
        canvasContext.strokeStyle = bodyStroke;
        canvasContext.fillRect(
          screen.x - radius,
          screen.y - radius * 0.52,
          radius * 2,
          radius * 1.36
        );
        canvasContext.strokeRect(
          screen.x - radius,
          screen.y - radius * 0.52,
          radius * 2,
          radius * 1.36
        );
      } else if (marker.type === "portal") {
        const portalStyle = portalStyleForType(marker.portalType);
        canvasContext.fillStyle = portalStyle.fill;
        canvasContext.strokeStyle = portalStyle.stroke;
        canvasContext.lineWidth = 2;
        canvasContext.fillRect(
          screen.x - radius * 0.82,
          screen.y - radius * 0.82,
          radius * 1.64,
          radius * 1.64
        );
        canvasContext.strokeRect(
          screen.x - radius * 0.82,
          screen.y - radius * 0.82,
          radius * 1.64,
          radius * 1.64
        );
        canvasContext.fillStyle = "#f8fafc";
        canvasContext.fillRect(
          screen.x - radius * 0.28,
          screen.y - radius * 0.92,
          radius * 0.56,
          radius * 1.84
        );
      } else {
        canvasContext.beginPath();
        canvasContext.fillStyle = marker.hidden
          ? "#64748b"
          : (marker.unsupported ? "#8b95a3" : "#1f2937");
        canvasContext.strokeStyle = marker.hidden
          ? "#334155"
          : (marker.removed ? "#4b5563" : "#facc15");
        canvasContext.lineWidth = marker.unsupported || marker.removed || marker.hidden ? 3 : 2;
        canvasContext.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
        canvasContext.fill();
        canvasContext.stroke();
      }

      if (scanColors) {
        drawMarkerRing(screen, radius + 6, scanColors.stroke, 4);
      }

      if (isHover || isActive) {
        drawMarkerRing(
          screen,
          radius + (scanColors ? 12 : 5),
          isActive ? "#111827" : "#4b5563",
          2
        );
      }

      if (marker.position && marker.position.z) {
        canvasContext.fillStyle = "#111827";
        canvasContext.font = "11px Arial, Helvetica, sans-serif";
        canvasContext.fillText(
          `z${marker.position.z}`,
          screen.x + radius + (scanColors ? 12 : 4),
          screen.y - radius
        );
      }
      canvasContext.restore();
    });
  }

  function setTargetDetails(marker) {
    if (!marker) {
      elements.targetState.textContent = "No target selected.";
      elements.targetState.title = "";
      return;
    }
    const flags = [];
    if (marker.selected) {
      flags.push("selected hero");
    }
    if (marker.removed) {
      flags.push("removed");
    }
    if (marker.hidden) {
      flags.push("hidden");
    }
    if (marker.unsupported) {
      flags.push("unsupported");
    }
    if (marker.type === "hero") {
      const ownerText = markerOwnerText(marker);
      if (ownerText) {
        flags.push(ownerText);
      }
    } else if (marker.type === "town") {
      flags.push(...townSummaryParts(marker));
    } else if (marker.type === "portal") {
      flags.push(...portalSummaryParts(marker));
    }
    const suffix = flags.length ? ` | ${flags.join(", ")}` : "";
    elements.targetState.textContent = `${marker.type} ${marker.id} | ${marker.label} | ${positionText(marker.position)}${suffix}`;
    elements.targetState.title = markerTooltipText(marker) || marker.label;
  }

  function clearNode(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function appendEmpty(node, text) {
    clearNode(node);
    const item = document.createElement("p");
    item.className = "empty-state";
    item.textContent = text;
    node.appendChild(item);
  }

  function invalidateEstimateRequests() {
    estimateState.requestId += 1;
    estimateState.runningTargetId = null;
    return estimateState.requestId;
  }

  function nextEstimateRequestId(targetId) {
    estimateState.requestId += 1;
    estimateState.runningTargetId = targetId || null;
    return estimateState.requestId;
  }

  function setEstimateMessage(text, className) {
    clearNode(elements.estimateState);
    elements.estimateState.className = `result-box ${className || "empty-state"}`.trim();
    elements.estimateState.textContent = text;
    elements.estimateState.title = text;
  }

  function invalidatePathRequests() {
    pathState.requestId += 1;
    pathState.running = false;
    return pathState.requestId;
  }

  function setPathMessage(text, className) {
    clearNode(elements.pathState);
    elements.pathState.className = `result-box ${className || "empty-state"}`.trim();
    elements.pathState.textContent = text;
    elements.pathState.title = text;
  }

  function clearPathResult(message) {
    invalidatePathRequests();
    pathState.result = null;
    pathState.target = null;
    setPathMessage(message || "No path requested.");
    drawMap();
  }

  function selectedHero() {
    return heroState.heroes.find((hero) => hero.id === heroState.selectedHeroId) || null;
  }

  function formatHeroArmy(hero) {
    if (!hero) {
      return "Selected hero is not in the current snapshot.";
    }
    if (hero.army_summary) {
      return hero.army_summary;
    }
    return formatArmy(hero.army);
  }

  function formatArmy(army) {
    const parts = (army || [])
      .filter((stack) => stack.count > 0)
      .map((stack) => `${stack.count}x ${stack.creature_name || "Unknown"}`);
    return parts.length ? parts.join(", ") : "No army.";
  }

  function formatNumber(value) {
    return typeof value === "number" ? String(value) : "not available";
  }

  function formatWinPct(winPct) {
    return typeof winPct === "number" ? `${winPct.toFixed(1)}%` : "not available";
  }

  function verdictForWinPct(winPct) {
    if (typeof winPct !== "number") {
      return "Unsupported target";
    }
    if (winPct < 10) {
      return "Very unlikely";
    }
    if (winPct < 30) {
      return "Poor odds";
    }
    if (winPct < 50) {
      return "Risky";
    }
    if (winPct < 70) {
      return "Even fight";
    }
    if (winPct < 90) {
      return "Likely win";
    }
    return "Strong advantage";
  }

  function scanClassForWinPct(winPct) {
    if (typeof winPct !== "number") {
      return "unsupported";
    }
    if (winPct < 30) {
      return "danger";
    }
    if (winPct < 70) {
      return "risky";
    }
    if (winPct < 90) {
      return "likely";
    }
    return "strong";
  }

  function scanColorsForClass(className) {
    if (className === "strong") {
      return { fill: "#2f9e44", stroke: "#14532d" };
    }
    if (className === "likely") {
      return { fill: "#65a30d", stroke: "#365314" };
    }
    if (className === "risky") {
      return { fill: "#d99a21", stroke: "#7c4a03" };
    }
    if (className === "danger") {
      return { fill: "#d34a3f", stroke: "#7f1d1d" };
    }
    return { fill: "#8b95a3", stroke: "#4b5563" };
  }

  function scanColorsForMarker(marker) {
    if (!marker || marker.selected) {
      return null;
    }
    const result = scanState.resultByTargetId.get(marker.id);
    if (!result) {
      return null;
    }
    return scanColorsForClass(scanClassForWinPct(result.win_pct));
  }

  function estimateTargetLabel(estimate, targetId) {
    const target = estimate.target || {};
    if (estimate.target_type === "neutral") {
      return `${target.count || 0}x ${target.creature_name || "Unknown"} (${targetId})`;
    }
    if (estimate.target_type === "hero") {
      return `${target.name || "Hero"} (${targetId})`;
    }
    return targetId || "Unknown target";
  }

  function simulationClickDecision(marker, selectedHeroId) {
    if (!marker) {
      return { simulate: false, message: "No target selected." };
    }
    if (marker.type === "town") {
      return { simulate: false, message: "Town target is not a battle simulation target." };
    }
    if (marker.type === "portal") {
      return { simulate: false, message: "Portal target is not a battle simulation target." };
    }
    if (!selectedHeroId) {
      return { simulate: false, message: "Select a hero before simulating." };
    }
    if (marker.hidden) {
      return { simulate: false, message: "Hidden target is ignored." };
    }
    if (marker.type === "hero" && marker.id === selectedHeroId) {
      return { simulate: false, message: "Selected hero is not a simulation target." };
    }
    if (marker.type === "hero" && marker.relation === "ally") {
      return { simulate: false, message: "Allied hero is not a simulation target." };
    }
    return { simulate: true, message: "" };
  }

  function currentMapViewForTest() {
    return {
      snapshot: mapView.snapshot,
      zoom: mapView.zoom,
      pan: { x: mapView.pan.x, y: mapView.pan.y },
      level: mapView.level,
      pathMode: mapView.pathMode,
      activeMarkerId: mapView.activeMarkerId,
      hoveredMarkerId: mapView.hoveredMarkerId,
      markers: mapView.markers
    };
  }

  function currentPathStateForTest() {
    return {
      requestId: pathState.requestId,
      running: pathState.running,
      result: pathState.result,
      target: pathState.target
    };
  }

  function isFreshEstimatePayload(payload, requestId, currentRequestId, selectedHeroId) {
    return (
      requestId === currentRequestId
      && payload.hero_id === selectedHeroId
    );
  }

  function appendEstimateRow(parent, label, value, className) {
    const row = document.createElement("div");
    row.className = "estimate-row";

    const labelNode = document.createElement("span");
    labelNode.className = "estimate-label";
    labelNode.textContent = label;

    const valueNode = document.createElement("span");
    valueNode.className = `estimate-value ${className || ""}`.trim();
    valueNode.textContent = value;
    valueNode.title = value;

    row.appendChild(labelNode);
    row.appendChild(valueNode);
    parent.appendChild(row);
  }

  function renderEstimateResult(payload) {
    const estimate = payload.estimate || {};
    const hero = selectedHero();
    const heroLabel = hero ? (hero.name || payload.hero_id) : payload.hero_id;
    const targetId = payload.target_id || estimate.target_id;
    clearNode(elements.estimateState);
    elements.estimateState.className = "result-box estimate-result";
    elements.estimateState.title = "";

    const grid = document.createElement("div");
    grid.className = "estimate-grid";
    appendEstimateRow(grid, "Hero", heroLabel || "Unknown hero");
    appendEstimateRow(grid, "Hero army", formatHeroArmy(hero), "long-value");
    appendEstimateRow(grid, "Target", estimateTargetLabel(estimate, targetId), "long-value");
    appendEstimateRow(grid, "Distance", formatNumber(estimate.distance));
    appendEstimateRow(grid, "Enemy army", formatArmy(estimate.enemy_army), "long-value");
    appendEstimateRow(grid, "Enemy AI", formatNumber(estimate.enemy_ai_value));
    appendEstimateRow(grid, "Win", formatWinPct(estimate.win_pct), "estimate-win");
    appendEstimateRow(grid, "Verdict", verdictForWinPct(estimate.win_pct));
    appendEstimateRow(grid, "Note", estimate.note || "No note.", "long-value");
    elements.estimateState.appendChild(grid);
  }

  function isFreshPathPayload(payload, request, currentRequestId, selectedHeroId) {
    return (
      payload
      && request
      && request.requestId === currentRequestId
      && payload.hero_id === request.heroId
      && request.heroId === selectedHeroId
    );
  }

  function pathSegmentsForPayload(payload) {
    return Array.isArray(payload && payload.segments) ? payload.segments : [];
  }

  function pathSegmentStepPositions(segment) {
    return ((segment && segment.steps) || [])
      .map(pathStepPosition)
      .filter(Boolean);
  }

  function pathSegmentStartPosition(segment) {
    if (!segment) {
      return null;
    }
    const edge = segment.portal_edge || {};
    const steps = pathSegmentStepPositions(segment);
    return segment.start_position || edge.source_position || steps[0] || null;
  }

  function pathSegmentEndPosition(segment) {
    if (!segment) {
      return null;
    }
    const edge = segment.portal_edge || {};
    const steps = pathSegmentStepPositions(segment);
    return (
      segment.end_position
      || edge.destination_position
      || steps[steps.length - 1]
      || null
    );
  }

  function pathSegmentTypeLabel(segment) {
    if (!segment) {
      return "Segment";
    }
    const edge = segment.portal_edge || {};
    if (segment.segment_type === "portal") {
      return edge.portal_type ? portalTypeLabel(edge.portal_type) : "Portal";
    }
    if (segment.segment_type === "walk") {
      return "Walk";
    }
    return titleCase(String(segment.segment_type || "segment").replace(/_/g, " "));
  }

  function pathSegmentIsNonDeterministic(segment) {
    const edge = segment && segment.portal_edge ? segment.portal_edge : {};
    return Boolean((segment && segment.is_non_deterministic) || edge.is_non_deterministic);
  }

  function averagePathPositions(positions) {
    if (!positions.length) {
      return null;
    }
    const total = positions.reduce((accumulator, position) => ({
      x: accumulator.x + Number(position.x || 0),
      y: accumulator.y + Number(position.y || 0),
      z: accumulator.z
    }), { x: 0, y: 0, z: positionLevel(positions[0]) });
    return {
      x: total.x / positions.length,
      y: total.y / positions.length,
      z: total.z
    };
  }

  function pathSegmentFocusPosition(segment) {
    const start = pathSegmentStartPosition(segment);
    const end = pathSegmentEndPosition(segment);
    if (!segment) {
      return null;
    }
    if (segment.segment_type === "portal") {
      return (segment.portal_edge && segment.portal_edge.source_position) || start || end;
    }
    const focusLevel = positionLevel(start || end);
    const sameLevelSteps = pathSegmentStepPositions(segment)
      .filter((position) => positionLevel(position) === focusLevel);
    return (
      averagePathPositions(sameLevelSteps)
      || (
        start && end && positionLevel(start) === positionLevel(end)
          ? averagePathPositions([start, end])
          : null
      )
      || start
      || end
    );
  }

  function pathSegmentText(segment, index) {
    const start = pathSegmentStartPosition(segment);
    const end = pathSegmentEndPosition(segment);
    return [
      `${index + 1}. ${pathSegmentTypeLabel(segment)}`,
      start || end ? `${positionText(start)} -> ${positionText(end)}` : ""
    ].filter(Boolean).join(": ");
  }

  function pathSegmentMeta(segment) {
    const parts = [];
    const steps = pathSegmentStepPositions(segment);
    const edge = segment && segment.portal_edge ? segment.portal_edge : {};
    if (steps.length > 0) {
      parts.push(`${steps.length} step${steps.length === 1 ? "" : "s"}`);
    }
    if (edge.channel_key) {
      parts.push(edge.channel_key);
    }
    if (pathSegmentIsNonDeterministic(segment)) {
      parts.push("non-deterministic");
    }
    if (!pathSegmentFocusPosition(segment)) {
      parts.push("no focus position");
    }
    return parts.join(" | ") || "No segment metadata.";
  }

  function focusPathSegment(segment) {
    const focusPosition = pathSegmentFocusPosition(segment);
    if (!focusPosition || !mapView.snapshot || !mapView.snapshot.map) {
      return false;
    }
    mapView.level = normalizeLevelForSnapshot(positionLevel(focusPosition), mapView.snapshot);
    mapView.hoveredMarkerId = null;
    elements.canvas.classList.remove("has-marker-hover");
    hideMapTooltip();
    hideTargetContextMenu();
    rebuildMarkerCache(mapView.snapshot);
    updateLevelControls(mapView.snapshot);
    updateMapMetrics(mapView.snapshot);
    const tileSize = tileSizeForMap(mapView.snapshot.map);
    return centerOnWorldPoint(pathPointForPosition(focusPosition, tileSize));
  }

  function renderPathSegments(payload) {
    const segments = pathSegmentsForPayload(payload);
    if (segments.length === 0) {
      return null;
    }
    const list = document.createElement("div");
    list.className = "path-segment-list";
    segments.forEach((segment, index) => {
      const button = document.createElement("button");
      const canFocus = Boolean(pathSegmentFocusPosition(segment));
      button.type = "button";
      button.className = "list-item path-segment";
      button.disabled = !canFocus;
      button.dataset.segmentIndex = String(index);
      button.addEventListener("click", () => {
        if (canFocus) {
          focusPathSegment(segment);
        }
      });

      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = pathSegmentText(segment, index);
      title.title = title.textContent;

      const meta = document.createElement("div");
      meta.className = "item-meta";
      meta.textContent = pathSegmentMeta(segment);
      meta.title = meta.textContent;

      button.appendChild(title);
      button.appendChild(meta);
      list.appendChild(button);
    });
    return list;
  }

  function renderPathResult(payload) {
    pathState.result = payload;
    clearNode(elements.pathState);
    elements.pathState.className = `result-box path-result ${payload.status === "found" ? "" : "error"}`.trim();
    elements.pathState.title = "";

    const grid = document.createElement("div");
    grid.className = "estimate-grid";
    appendEstimateRow(grid, "Status", payload.status || "unknown");
    appendEstimateRow(
      grid,
      "Target",
      positionText(payload.requested_target_position),
      "long-value"
    );
    appendEstimateRow(
      grid,
      "Resolved",
      payload.resolved_target_position
        ? positionText(payload.resolved_target_position)
        : "none",
      "long-value"
    );
    appendEstimateRow(
      grid,
      "Steps",
      Array.isArray(payload.steps) ? String(payload.steps.length) : "0"
    );
    appendEstimateRow(grid, "Note", payload.message || "No note.", "long-value");
    elements.pathState.appendChild(grid);
    const segmentList = renderPathSegments(payload);
    if (segmentList) {
      elements.pathState.appendChild(segmentList);
    }
  }

  function requestPath(marker, point) {
    invalidateEstimateRequests();
    setEstimateMessage("No simulation run.");
    const requestId = invalidatePathRequests();
    pathState.result = null;
    pathState.target = null;

    if (!heroState.selectedHeroId) {
      setPathMessage("Select a hero before pathing.", "error");
      return;
    }

    const payload = { hero_id: heroState.selectedHeroId };
    let label = "tile";
    if (marker && marker.id) {
      payload.target_id = marker.id;
      label = marker.label || marker.id;
    } else {
      const targetPosition = tilePositionForCanvasPoint(point, mapView.snapshot, mapView);
      if (!targetPosition) {
        setPathMessage("Path target is outside the map.", "error");
        return;
      }
      payload.target_position = targetPosition;
      label = positionText(targetPosition);
    }

    const request = {
      requestId,
      heroId: heroState.selectedHeroId,
      target: payload.target_id || payload.target_position
    };
    pathState.running = true;
    pathState.target = request.target;
    setPathMessage(`Finding path to ${label}...`, "running");

    postJson("/api/path-route", payload, "path request failed")
      .then((responsePayload) => {
        if (!isFreshPathPayload(
          responsePayload,
          request,
          pathState.requestId,
          heroState.selectedHeroId
        )) {
          return;
        }
        pathState.running = false;
        renderPathResult(responsePayload);
        drawMap();
      })
      .catch((error) => {
        if (
          request.requestId !== pathState.requestId
          || request.heroId !== heroState.selectedHeroId
        ) {
          return;
        }
        pathState.running = false;
        pathState.result = null;
        setPathMessage(`Path error: ${error.message}`, "error");
        drawMap();
        if (error.status === 409) {
          loadState();
        }
      });
  }

  function simulateTarget(marker) {
    const decision = simulationClickDecision(marker, heroState.selectedHeroId);
    if (!decision.simulate) {
      invalidateEstimateRequests();
      setEstimateMessage(decision.message);
      return;
    }

    const heroId = heroState.selectedHeroId;
    const requestId = nextEstimateRequestId(marker.id);
    setEstimateMessage(`Estimating ${marker.label}`, "running");

    postJson(
      "/api/simulate-target",
      { hero_id: heroId, target_id: marker.id },
      "target simulation failed"
    )
      .then((payload) => {
        if (!isFreshEstimatePayload(
          payload,
          requestId,
          estimateState.requestId,
          heroState.selectedHeroId
        )) {
          return;
        }
        renderEstimateResult(payload);
      })
      .catch((error) => {
        if (requestId !== estimateState.requestId) {
          return;
        }
        setEstimateMessage(`Simulation error: ${error.message}`, "error");
        if (error.status === 409) {
          loadState();
        }
      })
      .finally(() => {
        if (requestId === estimateState.requestId) {
          estimateState.runningTargetId = null;
        }
      });
  }

  function setHiddenTarget(marker, hidden) {
    if (
      !marker
      || (marker.type !== "neutral" && marker.type !== "hero")
      || (marker.type === "hero" && marker.selected)
      || stateRequests.hiddenTargetInFlight
    ) {
      return Promise.resolve();
    }
    stateRequests.hiddenTargetInFlight = true;
    invalidateEstimateRequests();
    clearScanResults("No scan results.");
    setText(elements.refresh, hidden ? "Hiding target" : "Restoring target");

    return postJson(
      "/api/hidden-target",
      { target_id: marker.id, hidden },
      "hidden target update failed"
    )
      .then(() => loadState())
      .catch((error) => {
        setText(elements.refresh, `Hidden target error: ${error.message}`);
      })
      .finally(() => {
        stateRequests.hiddenTargetInFlight = false;
        syncSaveControls(mapView.snapshot);
        syncGameFolderControls();
      });
  }

  function setShowHiddenNeutrals(showHidden) {
    if (stateRequests.showHiddenInFlight) {
      return Promise.resolve();
    }
    stateRequests.showHiddenInFlight = true;
    invalidateEstimateRequests();
    clearScanResults("No scan results.");
    setText(elements.refresh, showHidden ? "Showing hidden" : "Hiding hidden");
    elements.showHiddenToggle.disabled = true;

    return postJson(
      "/api/show-hidden",
      { show_hidden: showHidden },
      "show hidden update failed"
    )
      .then((snapshot) => {
        renderSnapshot(snapshot, { preserveView: true });
      })
      .catch((error) => {
        elements.showHiddenToggle.checked = mapView.showHiddenNeutrals;
        setText(elements.refresh, `Show hidden error: ${error.message}`);
      })
      .finally(() => {
        stateRequests.showHiddenInFlight = false;
        elements.showHiddenToggle.disabled = !mapView.snapshot;
        syncSaveControls(mapView.snapshot);
        syncGameFolderControls();
      });
  }

  function parseScanRadius() {
    const rawValue = String(elements.scanRadius.value || "").trim();
    if (!rawValue) {
      return null;
    }
    const value = Number(rawValue);
    if (!Number.isInteger(value) || value < 0 || value > 200) {
      return null;
    }
    return value;
  }

  function numericDistance(result) {
    return typeof result.distance === "number" && Number.isFinite(result.distance)
      ? result.distance
      : Number.MAX_SAFE_INTEGER;
  }

  function numericWinPct(result) {
    return typeof result.win_pct === "number" && Number.isFinite(result.win_pct)
      ? result.win_pct
      : null;
  }

  function compareTargetIds(left, right) {
    const leftId = String(left.target_id || "");
    const rightId = String(right.target_id || "");
    if (leftId < rightId) {
      return -1;
    }
    if (leftId > rightId) {
      return 1;
    }
    return 0;
  }

  function sortedScanResults(results, sortMode) {
    const normalizedSortMode = normalizeScanSortMode(sortMode);
    return (results || []).slice().sort((left, right) => {
      const leftDistance = numericDistance(left);
      const rightDistance = numericDistance(right);
      if (normalizedSortMode === "easiest") {
        const leftWinPct = numericWinPct(left);
        const rightWinPct = numericWinPct(right);
        if (leftWinPct !== rightWinPct) {
          if (leftWinPct === null) {
            return 1;
          }
          if (rightWinPct === null) {
            return -1;
          }
          return rightWinPct - leftWinPct;
        }
      }
      if (leftDistance !== rightDistance) {
        return leftDistance - rightDistance;
      }
      return compareTargetIds(left, right);
    });
  }

  function scanResultLookup(results) {
    const lookup = new Map();
    (results || []).forEach((result) => {
      if (result.target_id) {
        lookup.set(result.target_id, result);
      }
    });
    return lookup;
  }

  function isFreshScanPayload(payload, request, currentRequestId) {
    return Boolean(
      payload
      && request
      && request.requestId === currentRequestId
      && payload.hero_id === request.heroId
      && payload.radius === request.radius
      && payload.target_type === request.targetType
    );
  }

  function updateScanControls() {
    const hasSnapshot = Boolean(mapView.snapshot);
    const canRun = hasSnapshot && Boolean(heroState.selectedHeroId) && !scanState.running;
    elements.scanRadius.disabled = !hasSnapshot || scanState.running;
    elements.scanButton.disabled = !canRun;
    renderTargetFilterControl();
    renderScanSortControl();
  }

  function clearScanResults(message) {
    scanState.requestId += 1;
    scanState.running = false;
    scanState.heroId = null;
    scanState.radius = null;
    scanState.targetType = scanTargetTypeForFilter(mapView.targetFilter);
    scanState.rawResults = [];
    clearScanResultHover();
    scanState.results = [];
    scanState.resultByTargetId = new Map();
    appendEmpty(elements.scanState, message || "No scan results.");
    updateScanControls();
    drawMap();
  }

  function setScanMessage(message, className) {
    clearScanResultHover();
    clearNode(elements.scanState);
    const item = document.createElement("p");
    item.className = className || "empty-state";
    item.textContent = message;
    elements.scanState.appendChild(item);
  }

  function clearScanResultHover() {
    const targetId = scanState.hoveredResultTargetId;
    scanState.hoveredResultTargetId = null;
    if (targetId && mapView.hoveredMarkerId === targetId) {
      mapView.hoveredMarkerId = null;
      elements.canvas.classList.remove("has-marker-hover");
      drawMap();
    }
  }

  function setScanResultHover(result, hovered) {
    const targetId = result && result.target_id ? result.target_id : null;
    if (!hovered) {
      if (targetId && scanState.hoveredResultTargetId === targetId) {
        clearScanResultHover();
      }
      return;
    }

    clearScanResultHover();
    if (!targetId || !mapView.markers.some((marker) => marker.id === targetId)) {
      return;
    }
    scanState.hoveredResultTargetId = targetId;
    mapView.hoveredMarkerId = targetId;
    elements.canvas.classList.add("has-marker-hover");
    drawMap();
  }

  function renderScanResultRows() {
    const results = sortedScanResults(scanState.rawResults, scanState.sortMode);
    scanState.results = results;
    scanState.resultByTargetId = scanResultLookup(results);
    clearScanResultHover();
    clearNode(elements.scanState);

    if (results.length === 0) {
      appendEmpty(elements.scanState, "No targets in radius.");
      updateScanControls();
      drawMap();
      return;
    }

    results.forEach((result) => {
      const row = document.createElement("button");
      const scanClass = scanClassForWinPct(result.win_pct);
      row.type = "button";
      row.className = `list-item scan-result ${scanClass}`.trim();
      row.dataset.targetId = result.target_id || "";
      row.addEventListener("pointerenter", () => setScanResultHover(result, true));
      row.addEventListener("pointerleave", () => setScanResultHover(result, false));
      row.addEventListener("focus", () => setScanResultHover(result, true));
      row.addEventListener("blur", () => setScanResultHover(result, false));
      row.addEventListener("click", () => selectScanResult(result));

      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = estimateTargetLabel(result, result.target_id);
      title.title = title.textContent;

      const meta = document.createElement("div");
      meta.className = "item-meta";
      meta.textContent = [
        `d ${formatNumber(result.distance)}`,
        formatWinPct(result.win_pct),
        `AI ${formatNumber(result.enemy_ai_value)}`,
        result.note || verdictForWinPct(result.win_pct)
      ].join(" | ");
      meta.title = meta.textContent;

      row.appendChild(title);
      row.appendChild(meta);
      elements.scanState.appendChild(row);
    });

    updateScanControls();
    drawMap();
  }

  function renderScanResults(payload) {
    scanState.running = false;
    scanState.heroId = payload.hero_id;
    scanState.radius = payload.radius;
    scanState.targetType = payload.target_type;
    scanState.rawResults = payload.results || [];
    renderScanResultRows();
  }

  function selectScanResult(result) {
    const marker = centerOnMarkerId(result.target_id);
    mapView.activeMarkerId = result.target_id || null;
    if (marker) {
      setTargetDetails(marker);
    } else {
      elements.targetState.textContent = `${result.target_type || "target"} ${result.target_id || "unknown"} | no map marker`;
      elements.targetState.title = "Scan result has no marker in the current snapshot.";
    }
    renderEstimateResult({
      hero_id: scanState.heroId || heroState.selectedHeroId,
      target_id: result.target_id,
      estimate: result
    });
    drawMap();
  }

  function runRadiusScan() {
    const radius = parseScanRadius();
    const targetType = scanTargetTypeForFilter(mapView.targetFilter);
    if (!heroState.selectedHeroId) {
      setScanMessage("Select a hero before scanning.");
      return Promise.resolve(null);
    }
    if (radius === null) {
      setScanMessage("Radius must be an integer from 0 to 200.", "empty-state error-text");
      return Promise.resolve(null);
    }

    const request = {
      requestId: scanState.requestId + 1,
      heroId: heroState.selectedHeroId,
      radius,
      targetType
    };
    scanState.requestId = request.requestId;
    scanState.running = true;
    scanState.hasRun = true;
    scanState.heroId = request.heroId;
    scanState.radius = request.radius;
    scanState.targetType = request.targetType;
    scanState.rawResults = [];
    clearScanResultHover();
    scanState.results = [];
    scanState.resultByTargetId = new Map();
    updateScanControls();
    setScanMessage("Running scan...", "empty-state");
    drawMap();

    return postJson(
      "/api/scan-radius",
      {
        hero_id: request.heroId,
        radius: request.radius,
        target_type: request.targetType
      },
      "radius scan failed"
    )
      .then((payload) => {
        if (!isFreshScanPayload(payload, request, scanState.requestId)) {
          if (request.requestId === scanState.requestId) {
            scanState.running = false;
            setScanMessage("Scan response did not match the current request.", "empty-state error-text");
            updateScanControls();
          }
          return;
        }
        renderScanResults(payload);
      })
      .catch((error) => {
        if (request.requestId !== scanState.requestId) {
          return;
        }
        scanState.running = false;
        setScanMessage(`Scan error: ${error.message}`, "empty-state error-text");
        updateScanControls();
        if (error.status === 409) {
          loadState();
        }
      });
  }

  function savePickerOption(value, text) {
    const option = document.createElement("option");
    option.value = value || "";
    option.textContent = text;
    return option;
  }

  function gameFolderOption(value, text) {
    const option = document.createElement("option");
    option.value = value || "";
    option.textContent = text;
    return option;
  }

  function controlsBusy() {
    return (
      stateRequests.saveModeInFlight
      || stateRequests.gameFolderInFlight
      || stateRequests.hiddenTargetInFlight
      || stateRequests.showHiddenInFlight
      || stateRequests.loading
    );
  }

  function syncSaveControls(snapshot) {
    const current = snapshot || mapView.snapshot;
    const mode = current ? current.mode : null;
    const hasSaveOptions = elements.savePicker.options.length > 1;
    const busy = controlsBusy();
    const saveIndex = currentSaveIndex(current);
    elements.followLatestButton.disabled = (
      !current
      || busy
    );
    elements.previousSaveButton.disabled = (
      !current
      || busy
      || saveIndex <= 0
    );
    elements.nextSaveButton.disabled = (
      !current
      || busy
      || saveIndex < 0
      || saveIndex >= saveNavigation.saves.length - 1
    );
    elements.savePicker.disabled = (
      !current
      || !hasSaveOptions
      || busy
    );
    elements.refreshButton.disabled = busy;
    if (!current) {
      elements.savePicker.value = "";
      syncHeroSkillControls();
      return;
    }
    if (mode === PINNED_MODE && current.save_file) {
      const hasCurrent = Array.from(elements.savePicker.options).some((option) => (
        option.value === current.save_file
      ));
      if (!hasCurrent) {
        elements.savePicker.appendChild(
          savePickerOption(current.save_file, `${fileName(current.save_file)} (current pinned)`)
        );
      }
      elements.savePicker.value = current.save_file;
      syncHeroSkillControls();
      return;
    }
    elements.savePicker.value = "";
    syncHeroSkillControls();
  }

  function syncHeroRankingControls() {
    elements.heroRankingButton.disabled = rankedMapHeroes(mapView.snapshot).length === 0;
  }

  function syncGameFolderControls() {
    const busy = controlsBusy();
    const path = String(elements.gameFolderPath.value || "").trim();
    elements.gameFolderPicker.disabled = busy || elements.gameFolderPicker.options.length <= 1;
    elements.gameFolderPath.disabled = busy;
    elements.useGameFolderButton.disabled = busy || !path;
  }

  function renderSaveOptions(payload) {
    const saves = payload && payload.saves ? payload.saves : [];
    saveNavigation.saves = saves;
    clearNode(elements.savePicker);
    if (saves.length === 0) {
      elements.savePicker.appendChild(savePickerOption("", "No numeric saves"));
      elements.savePicker.disabled = true;
      syncSaveControls(mapView.snapshot);
      return;
    }

    elements.savePicker.appendChild(savePickerOption("", "Pin a save..."));
    saves.forEach((save) => {
      const saveName = save.name || fileName(save.path);
      const label = save.path === payload.latest_save_file
        ? `${saveName} (latest)`
        : saveName;
      elements.savePicker.appendChild(savePickerOption(save.path, label));
    });
    syncSaveControls(mapView.snapshot);
  }

  function renderGameFolderOptions(payload) {
    const folders = payload && payload.game_folders ? payload.game_folders : [];
    const activePath = payload && payload.active_autosave_dir ? payload.active_autosave_dir : "";
    clearNode(elements.gameFolderPicker);
    if (activePath) {
      elements.gameFolderPath.value = activePath;
    }
    if (folders.length === 0) {
      elements.gameFolderPicker.appendChild(gameFolderOption("", "No game folders"));
      syncGameFolderControls();
      return;
    }

    elements.gameFolderPicker.appendChild(gameFolderOption("", "Detected folders..."));
    folders.forEach((folder) => {
      const folderName = folder.relative_path || folder.name || folder.path;
      const label = folder.path === activePath
        ? `${folderName} (${folder.save_count} saves, active)`
        : `${folderName} (${folder.save_count} saves)`;
      elements.gameFolderPicker.appendChild(gameFolderOption(folder.path, label));
    });
    elements.gameFolderPicker.value = activePath;
    syncGameFolderControls();
  }

  function loadSaves() {
    const requestId = stateRequests.saveListRequestId + 1;
    stateRequests.saveListRequestId = requestId;
    return getJson("/api/saves", "saves request failed")
      .then((payload) => {
        if (requestId !== stateRequests.saveListRequestId) {
          return;
        }
        renderSaveOptions(payload);
      })
      .catch((error) => {
        if (requestId !== stateRequests.saveListRequestId) {
          return;
        }
        saveNavigation.saves = [];
        clearNode(elements.savePicker);
        elements.savePicker.appendChild(savePickerOption("", "Unable to load saves"));
        elements.savePicker.disabled = true;
        setText(elements.refresh, `Save list error: ${error.message}`);
      });
  }

  function loadGameFolders() {
    const requestId = stateRequests.gameFolderListRequestId + 1;
    stateRequests.gameFolderListRequestId = requestId;
    return getJson("/api/game-folders", "game folders request failed")
      .then((payload) => {
        if (requestId !== stateRequests.gameFolderListRequestId) {
          return;
        }
        renderGameFolderOptions(payload);
      })
      .catch((error) => {
        if (requestId !== stateRequests.gameFolderListRequestId) {
          return;
        }
        clearNode(elements.gameFolderPicker);
        elements.gameFolderPicker.appendChild(gameFolderOption("", "Unable to load folders"));
        elements.gameFolderPicker.disabled = true;
        setText(elements.refresh, `Game folder list error: ${error.message}`);
        syncGameFolderControls();
      });
  }

  function refreshLists() {
    return Promise.all([loadSaves(), loadGameFolders()]);
  }

  function navigateSave(direction) {
    if (controlsBusy()) {
      return Promise.resolve();
    }
    const saveIndex = currentSaveIndex(mapView.snapshot);
    const targetIndex = saveIndex + direction;
    if (saveIndex < 0 || targetIndex < 0 || targetIndex >= saveNavigation.saves.length) {
      return Promise.resolve();
    }
    const targetSave = saveNavigation.saves[targetIndex];
    if (!targetSave || !targetSave.path) {
      return Promise.resolve();
    }
    return switchSaveMode(PINNED_MODE, targetSave.path);
  }

  function switchSaveMode(mode, saveFile) {
    if (mode === PINNED_MODE && !saveFile) {
      return;
    }
    if (stateRequests.gameFolderInFlight) {
      return Promise.resolve();
    }
    const requestId = stateRequests.saveModeRequestId + 1;
    const epoch = nextStateEpoch();
    stateRequests.saveModeRequestId = requestId;
    stateRequests.saveModeInFlight = true;
    syncSaveControls(mapView.snapshot);
    syncGameFolderControls();
    setText(elements.refresh, mode === PINNED_MODE ? "Pinning save" : "Following latest");

    const payload = mode === PINNED_MODE
      ? { mode, save_file: saveFile }
      : { mode };
    return postJson("/api/save-mode", payload, "save mode request failed")
      .then((snapshot) => {
        if (
          requestId !== stateRequests.saveModeRequestId
          || epoch !== stateRequests.epoch
        ) {
          return;
        }
        renderSnapshot(snapshot);
        setText(elements.refresh, "Loaded");
        return refreshLists();
      })
      .catch((error) => {
        if (requestId === stateRequests.saveModeRequestId) {
          setText(elements.refresh, `Save mode error: ${error.message}`);
        }
      })
      .finally(() => {
        if (requestId === stateRequests.saveModeRequestId) {
          stateRequests.saveModeInFlight = false;
          syncSaveControls(mapView.snapshot);
          syncGameFolderControls();
        }
      });
  }

  function switchGameFolder(payload, statusText) {
    if (stateRequests.saveModeInFlight || stateRequests.gameFolderInFlight) {
      return Promise.resolve();
    }
    const requestId = stateRequests.gameFolderRequestId + 1;
    const epoch = nextStateEpoch();
    stateRequests.gameFolderRequestId = requestId;
    stateRequests.gameFolderInFlight = true;
    syncSaveControls(mapView.snapshot);
    syncGameFolderControls();
    setText(elements.refresh, statusText || "Changing game folder");

    return postJson("/api/game-folder", payload, "game folder request failed")
      .then((snapshot) => {
        if (
          requestId !== stateRequests.gameFolderRequestId
          || epoch !== stateRequests.epoch
        ) {
          return;
        }
        renderSnapshot(snapshot, { preserveView: false });
        setText(elements.refresh, "Loaded");
        return refreshLists();
      })
      .catch((error) => {
        if (requestId === stateRequests.gameFolderRequestId) {
          setText(elements.refresh, `Game folder error: ${error.message}`);
        }
      })
      .finally(() => {
        if (requestId === stateRequests.gameFolderRequestId) {
          stateRequests.gameFolderInFlight = false;
          syncSaveControls(mapView.snapshot);
          syncGameFolderControls();
        }
      });
  }

  function refreshStateAndSaves() {
    if (stateRequests.saveModeInFlight || stateRequests.gameFolderInFlight) {
      return Promise.resolve();
    }
    return loadState().then(() => refreshLists());
  }

  function autoRefreshState() {
    if (
      stateRequests.autoRefreshRunning
      || stateRequests.saveModeInFlight
      || stateRequests.loading
      || !mapView.snapshot
      || mapView.snapshot.mode !== FOLLOW_LATEST_MODE
    ) {
      return;
    }

    const epoch = stateRequests.epoch;
    stateRequests.autoRefreshRunning = true;
    getJson("/api/state", "state request failed")
      .then((snapshot) => {
        if (
          epoch !== stateRequests.epoch
          || !mapView.snapshot
          || mapView.snapshot.mode !== FOLLOW_LATEST_MODE
          || snapshot.mode !== FOLLOW_LATEST_MODE
        ) {
          return;
        }
        if (snapshotChanged(mapView.snapshot, snapshot)) {
          renderSnapshot(snapshot);
          setText(elements.refresh, "Auto refreshed");
          loadSaves();
        } else {
          setText(elements.refresh, "Up to date");
        }
      })
      .catch((error) => {
        setText(elements.refresh, `Auto refresh error: ${error.message}`);
      })
      .finally(() => {
        stateRequests.autoRefreshRunning = false;
      });
  }

  function startAutoRefresh() {
    if (!AUTO_REFRESH_ENABLED) {
      return;
    }
    if (stateRequests.autoRefreshTimer) {
      return;
    }
    stateRequests.autoRefreshTimer = window.setInterval(
      autoRefreshState,
      AUTO_REFRESH_MS
    );
  }

  function showFollowLatestDialog() {
    elements.followLatestDialog.hidden = false;
  }

  function hideFollowLatestDialog() {
    elements.followLatestDialog.hidden = true;
  }

  function rankedMapHeroes(snapshot) {
    return ((snapshot && snapshot.heroes) || [])
      .filter((hero) => hero.position)
      .slice()
      .sort((left, right) => (
        heroAiValue(right) - heroAiValue(left)
        || (right.total_creatures || 0) - (left.total_creatures || 0)
        || String(left.name || left.id).localeCompare(String(right.name || right.id))
      ));
  }

  function renderHeroRanking() {
    const heroes = rankedMapHeroes(mapView.snapshot);
    clearNode(elements.heroRankingList);
    if (heroes.length === 0) {
      appendEmpty(elements.heroRankingList, "No positioned heroes.");
      return;
    }

    heroes.forEach((hero, index) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "list-item ranking-item";
      row.dataset.heroId = hero.id;
      row.addEventListener("click", () => focusRankedHero(hero.id));

      const titleRow = document.createElement("div");
      titleRow.className = "item-title-row";
      appendColorSwatch(titleRow, hero.owner_color_name);

      const title = document.createElement("div");
      title.className = "item-title ranking-title";
      title.textContent = `${index + 1}. ${hero.name || hero.id}`;
      title.title = title.textContent;
      titleRow.appendChild(title);

      const meta = document.createElement("div");
      meta.className = "item-meta";
      meta.textContent = [
        heroOwnerText(hero),
        `AI ${formatNumber(hero.ai_value)}`,
        positionText(hero.position),
        `${hero.total_creatures || 0} creatures`
      ].join(" | ");
      meta.title = hero.army_summary || meta.textContent;

      row.appendChild(titleRow);
      row.appendChild(meta);
      elements.heroRankingList.appendChild(row);
    });
  }

  function showHeroRankingDialog() {
    renderHeroRanking();
    elements.heroRankingDialog.hidden = false;
  }

  function hideHeroRankingDialog() {
    elements.heroRankingDialog.hidden = true;
  }

  function focusRankedHero(heroId) {
    hideHeroRankingDialog();
    const marker = centerOnMarkerId(heroId);
    mapView.activeMarkerId = heroId || null;
    if (marker) {
      setTargetDetails(marker);
    }
    drawMap();
  }

  function heroSkillsBusy() {
    return heroSkillsState.loading
      || heroSkillsState.saving
      || heroSkillsState.comparing;
  }

  function syncHeroSkillControls() {
    elements.heroSkillsButton.disabled = (
      !heroState.selectedHeroId
      || controlsBusy()
    );
  }

  function resetHeroSkillCompareOffers() {
    heroSkillsState.compareOffers = [
      { skill_id: "", level: "" },
      { skill_id: "", level: "" }
    ];
  }

  function invalidateHeroSkillsRequests() {
    heroSkillsState.requestId += 1;
    heroSkillsState.loading = false;
    heroSkillsState.saving = false;
    heroSkillsState.comparing = false;
    return heroSkillsState.requestId;
  }

  function heroSkillsRequestMatches(requestId, heroId, payload) {
    return (
      !elements.heroSkillsDialog.hidden
      && requestId === heroSkillsState.requestId
      && heroSkillsState.heroId === heroId
      && heroState.selectedHeroId === heroId
      && (!payload || payload.hero_id === heroId)
    );
  }

  function setHeroSkillsStatus(text, className) {
    elements.heroSkillsStatus.className = `dialog-status ${className || "empty-state"}`.trim();
    elements.heroSkillsStatus.textContent = text || "";
    elements.heroSkillsStatus.title = text || "";
  }

  function heroSkillLevelOptions(payload) {
    const levels = payload && Array.isArray(payload.skill_levels)
      ? payload.skill_levels
      : ["basic", "advanced", "expert"];
    return levels.length ? levels : ["basic", "advanced", "expert"];
  }

  function heroSkillMaxSlots(payload) {
    const maxSkills = payload && Number.isInteger(payload.max_skills)
      ? payload.max_skills
      : 8;
    return clamp(maxSkills, 1, 8);
  }

  function heroSkillSlotsFromPayload(payload) {
    const levels = heroSkillLevelOptions(payload);
    const slots = ((payload && payload.current_skills) || []).map((skill) => ({
      skill_id: skill.skill_id || skill.skill || "",
      level: skill.level || levels[0]
    }));
    while (slots.length < heroSkillMaxSlots(payload)) {
      slots.push({ skill_id: "", level: "" });
    }
    return slots.slice(0, heroSkillMaxSlots(payload));
  }

  function skillDisplayName(skillId, payload) {
    const match = ((payload && payload.skills) || []).find((skill) => (
      skill.skill_id === skillId || skill.skill === skillId
    ));
    return match ? (match.display_name || skillId) : skillId;
  }

  function skillLevelLabel(level) {
    return titleCase(String(level || "").replace(/_/g, " "));
  }

  function currentSkillText(skill, payload) {
    if (!skill || !skill.skill_id) {
      return "";
    }
    return `${skillDisplayName(skill.skill_id, payload)} ${skillLevelLabel(skill.level)}`;
  }

  function currentSkillListText(skills, payload) {
    const parts = (skills || [])
      .map((skill) => currentSkillText(skill, payload))
      .filter(Boolean);
    return parts.length ? parts.join(", ") : "None";
  }

  function appendSkillsMetaItem(parent, label, value, longValue) {
    const item = document.createElement("div");
    item.className = "skills-meta-item";

    const labelNode = document.createElement("div");
    labelNode.className = "skills-meta-label";
    labelNode.textContent = label;

    const valueNode = document.createElement("div");
    valueNode.className = `skills-meta-value ${longValue ? "long-value" : ""}`.trim();
    valueNode.textContent = value || "None";
    valueNode.title = value || "None";

    item.appendChild(labelNode);
    item.appendChild(valueNode);
    parent.appendChild(item);
  }

  function renderHeroSkillsMeta(payload) {
    clearNode(elements.heroSkillsMeta);
    if (!payload || !payload.hero) {
      appendEmpty(elements.heroSkillsMeta, "No hero loaded.");
      return;
    }
    const hero = payload.hero;
    appendSkillsMetaItem(elements.heroSkillsMeta, "Name", hero.display_name || hero.save_name || payload.hero_id);
    appendSkillsMetaItem(elements.heroSkillsMeta, "Class", hero.class_id || "Unknown");
    appendSkillsMetaItem(elements.heroSkillsMeta, "Faction", hero.faction || "Unknown");
    appendSkillsMetaItem(elements.heroSkillsMeta, "Source", payload.current_skills_source || "Unknown");
    appendSkillsMetaItem(
      elements.heroSkillsMeta,
      "Starting",
      currentSkillListText(hero.starting_skills || [], payload),
      true
    );
    appendSkillsMetaItem(
      elements.heroSkillsMeta,
      "Specialty",
      hero.specialty_summary || "None",
      true
    );
  }

  function selectedSkillIdsExcept(index) {
    return new Set(heroSkillsState.slots
      .map((slot, slotIndex) => (slotIndex === index ? "" : slot.skill_id))
      .filter(Boolean));
  }

  function createSkillSelect(value, disabledSkillIds, onChange) {
    const select = document.createElement("select");
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "Empty";
    select.appendChild(blank);
    ((heroSkillsState.payload && heroSkillsState.payload.skills) || []).forEach((skill) => {
      const option = document.createElement("option");
      option.value = skill.skill_id || skill.skill || "";
      option.textContent = skill.display_name || option.value;
      option.disabled = disabledSkillIds.has(option.value) && option.value !== value;
      select.appendChild(option);
    });
    select.value = value || "";
    select.disabled = heroSkillsBusy() || !heroSkillsState.payload;
    select.addEventListener("change", onChange);
    return select;
  }

  function createLevelSelect(value, disabled, onChange) {
    const select = document.createElement("select");
    heroSkillLevelOptions(heroSkillsState.payload).forEach((level) => {
      const option = document.createElement("option");
      option.value = level;
      option.textContent = skillLevelLabel(level);
      select.appendChild(option);
    });
    select.value = value || heroSkillLevelOptions(heroSkillsState.payload)[0];
    select.disabled = disabled || heroSkillsBusy() || !heroSkillsState.payload;
    select.addEventListener("change", onChange);
    return select;
  }

  function markHeroSkillsDirty() {
    heroSkillsState.dirty = true;
    if (heroSkillsState.payload) {
      heroSkillsState.payload.offer_comparison = null;
    }
    setHeroSkillsStatus("Unsaved edits. Save to refresh recommendations.");
  }

  function updateHeroSkillSlot(index, key, value) {
    const slot = heroSkillsState.slots[index];
    if (!slot) {
      return;
    }
    if (key === "skill_id") {
      slot.skill_id = value || "";
      slot.level = slot.skill_id
        ? (slot.level || heroSkillLevelOptions(heroSkillsState.payload)[0])
        : "";
    } else if (key === "level") {
      slot.level = value || "";
    }
    markHeroSkillsDirty();
    renderHeroSkillsDialog();
  }

  function renderHeroSkillSlots() {
    clearNode(elements.heroSkillSlots);
    if (!heroSkillsState.payload) {
      appendEmpty(elements.heroSkillSlots, "No skill slots loaded.");
      return;
    }
    heroSkillsState.slots.forEach((slot, index) => {
      const row = document.createElement("div");
      row.className = "skill-slot-row";
      row.dataset.slotIndex = String(index);

      const label = document.createElement("div");
      label.className = "skill-slot-index";
      label.textContent = String(index + 1);

      const skillSelect = createSkillSelect(
        slot.skill_id,
        selectedSkillIdsExcept(index),
        (event) => updateHeroSkillSlot(index, "skill_id", event.target.value)
      );
      skillSelect.setAttribute("aria-label", `Skill slot ${index + 1}`);

      const levelSelect = createLevelSelect(
        slot.level,
        !slot.skill_id,
        (event) => updateHeroSkillSlot(index, "level", event.target.value)
      );
      levelSelect.setAttribute("aria-label", `Skill slot ${index + 1} level`);

      row.appendChild(label);
      row.appendChild(skillSelect);
      row.appendChild(levelSelect);
      elements.heroSkillSlots.appendChild(row);
    });
  }

  function nonblankHeroSkillSlots() {
    return heroSkillsState.slots.filter((slot) => slot.skill_id);
  }

  function duplicateSkillIds(slots) {
    const seen = new Set();
    const duplicates = new Set();
    (slots || []).forEach((slot) => {
      if (!slot.skill_id) {
        return;
      }
      if (seen.has(slot.skill_id)) {
        duplicates.add(slot.skill_id);
      }
      seen.add(slot.skill_id);
    });
    return duplicates;
  }

  function heroSkillSaveValidationMessage() {
    const slots = nonblankHeroSkillSlots();
    const duplicates = duplicateSkillIds(slots);
    if (duplicates.size > 0) {
      return "Duplicate current skills are not allowed.";
    }
    if (slots.some((slot) => !slot.level)) {
      return "Each selected skill needs a level.";
    }
    return "";
  }

  function heroSkillOfferValidationMessage() {
    if (heroSkillsState.dirty) {
      return "Save before comparing offers.";
    }
    const offers = heroSkillsState.compareOffers || [];
    if (offers.some((offer) => !offer.skill_id || !offer.level)) {
      return "Choose two complete offers.";
    }
    if (new Set(offers.map((offer) => offer.skill_id)).size !== offers.length) {
      return "Choose two different offer skills.";
    }
    if (new Set(offers.map((offer) => `${offer.skill_id}:${offer.level}`)).size !== offers.length) {
      return "Choose two different offers.";
    }
    return "";
  }

  function heroSkillEntryTitle(entry) {
    const level = entry.target_level ? ` -> ${skillLevelLabel(entry.target_level)}` : "";
    return `${entry.display_name || entry.skill_id}${level}`;
  }

  function appendHeroSkillEntry(parent, entry, options) {
    const item = document.createElement("div");
    const isWinner = options && options.winnerKey
      && `${entry.skill_id}:${entry.target_level}` === options.winnerKey;
    item.className = `skill-entry ${entry.availability === "unavailable" ? "unavailable" : ""} ${isWinner ? "winner" : ""}`.trim();

    const titleRow = document.createElement("div");
    titleRow.className = "skill-entry-title";

    const name = document.createElement("div");
    name.className = "skill-entry-name";
    name.textContent = heroSkillEntryTitle(entry);
    name.title = name.textContent;

    const tier = document.createElement("div");
    tier.className = "skill-entry-tier";
    tier.textContent = entry.tier || "?";

    const meta = document.createElement("div");
    meta.className = "skill-entry-meta";
    meta.textContent = [
      typeof entry.score === "number" ? `score ${entry.score.toFixed(1)}` : "",
      entry.availability || ""
    ].filter(Boolean).join(" | ");
    meta.title = meta.textContent;

    const reasons = document.createElement("div");
    reasons.className = "skill-entry-reasons";
    reasons.textContent = (entry.reason_codes || []).join(", ") || "No reasons";
    reasons.title = reasons.textContent;

    titleRow.appendChild(name);
    titleRow.appendChild(tier);
    item.appendChild(titleRow);
    item.appendChild(meta);
    item.appendChild(reasons);
    parent.appendChild(item);
  }

  function renderHeroSkillEntryList(node, entries, emptyText) {
    clearNode(node);
    if (!entries || entries.length === 0) {
      appendEmpty(node, emptyText);
      return;
    }
    entries.forEach((entry) => appendHeroSkillEntry(node, entry));
  }

  function updateHeroSkillCompareOffer(index, key, value) {
    const offer = heroSkillsState.compareOffers[index];
    if (!offer) {
      return;
    }
    if (key === "skill_id") {
      offer.skill_id = value || "";
      offer.level = offer.skill_id
        ? (offer.level || heroSkillLevelOptions(heroSkillsState.payload)[0])
        : "";
    } else if (key === "level") {
      offer.level = value || "";
    }
    renderHeroSkillsDialog();
  }

  function renderHeroSkillCompareControls() {
    clearNode(elements.heroSkillCompareControls);
    if (!heroSkillsState.payload) {
      appendEmpty(elements.heroSkillCompareControls, "No offers loaded.");
      return;
    }
    heroSkillsState.compareOffers.forEach((offer, index) => {
      const row = document.createElement("div");
      row.className = "skill-compare-row";
      row.dataset.offerIndex = String(index);

      const label = document.createElement("div");
      label.className = "skill-compare-label";
      label.textContent = index === 0 ? "A" : "B";

      const otherSkillIds = new Set(heroSkillsState.compareOffers
        .map((candidate, candidateIndex) => (
          candidateIndex === index ? "" : candidate.skill_id
        ))
        .filter(Boolean));
      const skillSelect = createSkillSelect(
        offer.skill_id,
        otherSkillIds,
        (event) => updateHeroSkillCompareOffer(index, "skill_id", event.target.value)
      );
      skillSelect.setAttribute("aria-label", `Offer ${index + 1} skill`);

      const levelSelect = createLevelSelect(
        offer.level,
        !offer.skill_id,
        (event) => updateHeroSkillCompareOffer(index, "level", event.target.value)
      );
      levelSelect.setAttribute("aria-label", `Offer ${index + 1} level`);

      row.appendChild(label);
      row.appendChild(skillSelect);
      row.appendChild(levelSelect);
      elements.heroSkillCompareControls.appendChild(row);
    });
  }

  function renderHeroSkillCompareResult(comparison) {
    clearNode(elements.heroSkillCompareResult);
    if (!comparison) {
      appendEmpty(elements.heroSkillCompareResult, "No comparison.");
      return;
    }
    const winner = document.createElement("div");
    winner.className = "skill-entry winner";

    const winnerName = document.createElement("div");
    winnerName.className = "skill-entry-name";
    winnerName.textContent = comparison.winner
      ? `Winner: ${comparison.winner}`
      : "Winner: none";

    const reasons = document.createElement("div");
    reasons.className = "skill-entry-reasons";
    reasons.textContent = (comparison.reason_codes || []).join(", ") || "No reasons";

    winner.appendChild(winnerName);
    winner.appendChild(reasons);
    elements.heroSkillCompareResult.appendChild(winner);
    (comparison.offers || []).forEach((entry) => (
      appendHeroSkillEntry(
        elements.heroSkillCompareResult,
        entry,
        { winnerKey: comparison.winner }
      )
    ));
  }

  function renderHeroSkillsActions() {
    const saveError = heroSkillSaveValidationMessage();
    const compareError = heroSkillOfferValidationMessage();
    const busy = heroSkillsBusy();
    elements.heroSkillsSaveButton.disabled = (
      busy
      || !heroSkillsState.payload
      || !heroSkillsState.dirty
      || Boolean(saveError)
    );
    elements.heroSkillsResetButton.disabled = (
      busy
      || !heroSkillsState.payload
      || heroSkillsState.payload.current_skills_source !== "manual"
    );
    elements.heroSkillsCompareButton.disabled = (
      busy
      || !heroSkillsState.payload
      || Boolean(compareError)
    );
    if (
      !busy
      && heroSkillsState.dirty
      && !String(elements.heroSkillsStatus.className || "").includes("error-text")
    ) {
      setHeroSkillsStatus(saveError || "Unsaved edits. Save to refresh recommendations.", saveError ? "error-text" : "");
    }
  }

  function renderHeroSkillsDialog() {
    const payload = heroSkillsState.payload;
    if (!payload) {
      renderHeroSkillsMeta(null);
      renderHeroSkillSlots();
      renderHeroSkillEntryList(elements.heroSkillRecommendations, [], "No recommendations.");
      renderHeroSkillEntryList(elements.heroSkillAvoid, [], "No avoid entries.");
      renderHeroSkillCompareControls();
      renderHeroSkillCompareResult(null);
      renderHeroSkillsActions();
      return;
    }
    renderHeroSkillsMeta(payload);
    renderHeroSkillSlots();
    renderHeroSkillEntryList(elements.heroSkillRecommendations, payload.top_next || [], "No recommendations.");
    renderHeroSkillEntryList(elements.heroSkillAvoid, payload.avoid || [], "No avoid entries.");
    renderHeroSkillCompareControls();
    renderHeroSkillCompareResult(payload.offer_comparison);
    renderHeroSkillsActions();
  }

  function applyHeroSkillsPayload(payload, statusText) {
    heroSkillsState.payload = payload;
    heroSkillsState.slots = heroSkillSlotsFromPayload(payload);
    heroSkillsState.dirty = false;
    heroSkillsState.loading = false;
    heroSkillsState.saving = false;
    heroSkillsState.comparing = false;
    setHeroSkillsStatus(statusText || "Loaded");
    renderHeroSkillsDialog();
  }

  function showHeroSkillsDialog() {
    const heroId = heroState.selectedHeroId;
    if (!heroId) {
      return Promise.resolve();
    }
    heroSkillsState.heroId = heroId;
    heroSkillsState.payload = null;
    heroSkillsState.slots = [];
    heroSkillsState.dirty = false;
    resetHeroSkillCompareOffers();
    elements.heroSkillsDialog.hidden = false;
    const requestId = invalidateHeroSkillsRequests();
    heroSkillsState.requestId = requestId;
    heroSkillsState.loading = true;
    setHeroSkillsStatus("Loading skills...");
    renderHeroSkillsDialog();
    return postJson(
      "/api/hero-skills",
      { hero_id: heroId },
      "hero skills request failed"
    )
      .then((payload) => {
        if (!heroSkillsRequestMatches(requestId, heroId, payload)) {
          return;
        }
        applyHeroSkillsPayload(payload, "Loaded");
      })
      .catch((error) => {
        if (!heroSkillsRequestMatches(requestId, heroId)) {
          return;
        }
        heroSkillsState.loading = false;
        setHeroSkillsStatus(`Skills error: ${error.message}`, "error-text");
        renderHeroSkillsDialog();
      });
  }

  function hideHeroSkillsDialog() {
    elements.heroSkillsDialog.hidden = true;
    invalidateHeroSkillsRequests();
    setHeroSkillsStatus("No hero selected.");
  }

  function saveHeroSkills() {
    const heroId = heroSkillsState.heroId;
    const validationMessage = heroSkillSaveValidationMessage();
    if (!heroId || validationMessage || !heroSkillsState.payload) {
      if (validationMessage) {
        setHeroSkillsStatus(validationMessage, "error-text");
      }
      return Promise.resolve();
    }
    const skills = nonblankHeroSkillSlots().map((slot) => ({
      skill: slot.skill_id,
      level: slot.level
    }));
    const requestId = heroSkillsState.requestId + 1;
    heroSkillsState.requestId = requestId;
    heroSkillsState.saving = true;
    setHeroSkillsStatus("Saving skills...");
    renderHeroSkillsDialog();
    return postJson(
      "/api/hero-skills/save",
      { hero_id: heroId, skills },
      "hero skills save failed"
    )
      .then((payload) => {
        if (!heroSkillsRequestMatches(requestId, heroId, payload)) {
          return;
        }
        applyHeroSkillsPayload(payload, "Saved");
      })
      .catch((error) => {
        if (!heroSkillsRequestMatches(requestId, heroId)) {
          return;
        }
        heroSkillsState.saving = false;
        setHeroSkillsStatus(`Save error: ${error.message}`, "error-text");
        renderHeroSkillsActions();
      });
  }

  function resetHeroSkills() {
    const heroId = heroSkillsState.heroId;
    if (!heroId || !heroSkillsState.payload) {
      return Promise.resolve();
    }
    const requestId = heroSkillsState.requestId + 1;
    heroSkillsState.requestId = requestId;
    heroSkillsState.saving = true;
    setHeroSkillsStatus("Resetting skills...");
    renderHeroSkillsDialog();
    return postJson(
      "/api/hero-skills/reset",
      { hero_id: heroId },
      "hero skills reset failed"
    )
      .then((payload) => {
        if (!heroSkillsRequestMatches(requestId, heroId, payload)) {
          return;
        }
        applyHeroSkillsPayload(payload, "Reset");
      })
      .catch((error) => {
        if (!heroSkillsRequestMatches(requestId, heroId)) {
          return;
        }
        heroSkillsState.saving = false;
        setHeroSkillsStatus(`Reset error: ${error.message}`, "error-text");
        renderHeroSkillsActions();
      });
  }

  function compareHeroSkillOffers() {
    const heroId = heroSkillsState.heroId;
    const validationMessage = heroSkillOfferValidationMessage();
    if (!heroId || validationMessage || !heroSkillsState.payload) {
      if (validationMessage) {
        setHeroSkillsStatus(validationMessage, "error-text");
      }
      return Promise.resolve();
    }
    const offers = heroSkillsState.compareOffers.map((offer) => ({
      skill: offer.skill_id,
      level: offer.level
    }));
    const requestId = heroSkillsState.requestId + 1;
    heroSkillsState.requestId = requestId;
    heroSkillsState.comparing = true;
    setHeroSkillsStatus("Comparing offers...");
    renderHeroSkillsDialog();
    return postJson(
      "/api/hero-skills/compare",
      { hero_id: heroId, offers },
      "hero skill comparison failed"
    )
      .then((payload) => {
        if (!heroSkillsRequestMatches(requestId, heroId, payload)) {
          return;
        }
        heroSkillsState.payload = payload;
        heroSkillsState.slots = heroSkillSlotsFromPayload(payload);
        heroSkillsState.comparing = false;
        setHeroSkillsStatus("Compared");
        renderHeroSkillsDialog();
      })
      .catch((error) => {
        if (!heroSkillsRequestMatches(requestId, heroId)) {
          return;
        }
        heroSkillsState.comparing = false;
        setHeroSkillsStatus(`Compare error: ${error.message}`, "error-text");
        renderHeroSkillsActions();
      });
  }

  function matchRecentHeroName(heroes, name) {
    const normalized = normalizeName(name);
    if (!normalized) {
      return [];
    }
    return (heroes || []).filter((hero) => normalizeName(hero.name) === normalized);
  }

  function recentHeroChipState(heroes, name, selectingHeroId) {
    const matches = matchRecentHeroName(heroes, name);
    if (matches.length === 1) {
      return {
        disabled: Boolean(selectingHeroId),
        heroId: matches[0].id,
        reason: selectingHeroId ? "pending" : "selectable",
        title: selectingHeroId ? "Selection in progress" : `Select ${name}`
      };
    }
    return {
      disabled: true,
      heroId: null,
      reason: matches.length === 0 ? "missing" : "ambiguous",
      title: matches.length === 0
        ? `${name} is not in this snapshot`
        : `${name} is ambiguous in this snapshot`
    };
  }

  function renderRecentHeroes(recentHeroes) {
    clearNode(elements.recentHeroes);
    if (!recentHeroes || recentHeroes.length === 0) {
      elements.recentHeroes.className = "chip-row empty-state";
      elements.recentHeroes.textContent = "None";
      return;
    }

    elements.recentHeroes.className = "chip-row";
    recentHeroes.slice(0, 8).forEach((name) => {
      const chipState = recentHeroChipState(
        heroState.heroes,
        name,
        heroState.selectingHeroId
      );
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip chip-button";
      chip.textContent = name;
      chip.disabled = chipState.disabled;
      chip.title = chipState.title;
      if (chipState.heroId && !chipState.disabled) {
        chip.addEventListener("click", () => selectHero(chipState.heroId));
      }
      elements.recentHeroes.appendChild(chip);
    });
  }

  function filteredHeroes() {
    return filterHeroesForQuery(heroState.heroes, heroState.searchQuery);
  }

  function filterHeroesForQuery(heroes, queryText) {
    const query = normalizeName(queryText);
    if (!query) {
      return heroes || [];
    }
    return (heroes || []).filter((hero) => (
      normalizeName(hero.name || hero.id).includes(query)
    ));
  }

  function renderHeroes() {
    if (!heroState.heroes || heroState.heroes.length === 0) {
      appendEmpty(elements.heroList, "No heroes detected.");
      return;
    }

    const heroes = filteredHeroes();
    if (heroes.length === 0) {
      appendEmpty(elements.heroList, "No heroes match the search.");
      return;
    }

    clearNode(elements.heroList);
    heroes.forEach((hero) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "list-item hero-item";
      row.dataset.heroId = hero.id;
      row.setAttribute("aria-pressed", hero.id === heroState.selectedHeroId ? "true" : "false");
      if (hero.id === heroState.selectedHeroId) {
        row.classList.add("selected");
      }
      if (hero.id === heroState.selectingHeroId) {
        row.classList.add("pending");
      }
      row.disabled = Boolean(heroState.selectingHeroId);
      row.addEventListener("click", () => selectHero(hero.id));

      const titleRow = document.createElement("div");
      titleRow.className = "item-title-row";
      appendColorSwatch(titleRow, hero.owner_color_name);

      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = hero.name || hero.id;
      title.title = title.textContent;
      titleRow.appendChild(title);

      const meta = document.createElement("div");
      meta.className = "item-meta";
      meta.textContent = [
        heroOwnerText(hero),
        positionText(hero.position),
        `${hero.total_creatures || 0} creatures`
      ].join(" | ");
      meta.title = hero.army_summary || meta.textContent;

      row.appendChild(titleRow);
      row.appendChild(meta);
      elements.heroList.appendChild(row);
    });
  }

  function resolveSelectedHeroId(snapshot, previousSelectedHeroId) {
    if (heroById(snapshot, previousSelectedHeroId)) {
      return previousSelectedHeroId;
    }
    if (heroById(snapshot, snapshot && snapshot.selected_hero_id)) {
      return snapshot.selected_hero_id;
    }
    return null;
  }

  function nextViewStateForSnapshot(snapshot, previous) {
    const selectedHeroId = resolveSelectedHeroId(snapshot, previous.selectedHeroId);
    const preserveView = previous.preserveView !== false
      && sameMapGeometry(previous.snapshot, snapshot);
    const level = selectedHeroId
      ? defaultLevelForSnapshot(snapshot, selectedHeroId)
      : (preserveView ? normalizeLevelForSnapshot(previous.level, snapshot) : 0);
    return {
      selectedHeroId,
      preserveView,
      level,
      zoom: clampZoom(previous.zoom, previous.minZoom, previous.maxZoom),
      pan: {
        x: previous.pan && typeof previous.pan.x === "number" ? previous.pan.x : 0,
        y: previous.pan && typeof previous.pan.y === "number" ? previous.pan.y : 0
      }
    };
  }

  function applySelectedHero(heroId, recentHeroes) {
    const previousSelectedHeroId = heroState.selectedHeroId;
    const shouldRefreshScan = Boolean(
      scanState.hasRun
      && heroId
      && heroId !== previousSelectedHeroId
    );
    invalidateEstimateRequests();
    clearPathResult("No path requested.");
    if (heroId !== previousSelectedHeroId) {
      hideHeroSkillsDialog();
    }
    heroState.selectedHeroId = heroId || null;
    heroState.recentHeroes = recentHeroes || heroState.recentHeroes;
    if (mapView.snapshot) {
      mapView.snapshot.selected_hero_id = heroState.selectedHeroId;
      mapView.snapshot.recent_heroes = heroState.recentHeroes;
      mapView.snapshot.hidden_hero_target_ids = (
        mapView.snapshot.hidden_hero_target_ids || []
      ).filter((targetId) => targetId !== heroState.selectedHeroId);
      (mapView.snapshot.heroes || []).forEach((hero) => {
        if (hero.id === heroState.selectedHeroId) {
          hero.hidden = false;
        }
      });
    }
    mapView.level = defaultLevelForSnapshot(mapView.snapshot, heroState.selectedHeroId);
    rebuildMarkerCache(mapView.snapshot);
    updateLevelControls(mapView.snapshot);
    updateMapMetrics(mapView.snapshot);
    renderRecentHeroes(heroState.recentHeroes);
    renderHeroes();
    syncHeroSkillControls();
    if (!centerOnHero(heroState.selectedHeroId)) {
      drawMap();
    }
    setEstimateMessage("No simulation run.");
    clearScanResults("No scan results.");
    if (shouldRefreshScan) {
      runRadiusScan();
    }
  }

  function selectHero(heroId) {
    if (!heroId || heroState.selectingHeroId) {
      return Promise.resolve();
    }
    invalidateEstimateRequests();
    heroState.selectingHeroId = heroId;
    setText(elements.refresh, "Selecting hero");
    renderHeroes();

    return postJson(
      "/api/select-hero",
      { hero_id: heroId },
      "hero selection failed"
    )
      .then((payload) => {
        applySelectedHero(payload.selected_hero_id, payload.recent_heroes || []);
        setText(elements.refresh, "Hero selected");
      })
      .catch((error) => {
        setText(elements.refresh, `Selection error: ${error.message}; refreshing`);
        heroState.selectedHeroId = mapView.snapshot ? mapView.snapshot.selected_hero_id : null;
        return loadState();
      })
      .finally(() => {
        heroState.selectingHeroId = null;
        renderRecentHeroes(heroState.recentHeroes);
        renderHeroes();
      });
  }

  function renderSnapshot(snapshot, options) {
    const nextViewState = nextViewStateForSnapshot(snapshot, {
      snapshot: mapView.snapshot,
      zoom: mapView.zoom,
      minZoom: mapView.minZoom,
      maxZoom: mapView.maxZoom,
      pan: mapView.pan,
      level: mapView.level,
      selectedHeroId: heroState.selectedHeroId,
      preserveView: !options || options.preserveView !== false
    });
    const heroes = snapshot.heroes || [];
    const selectedHeroId = nextViewState.selectedHeroId;
    snapshot.selected_hero_id = selectedHeroId;
    if (!elements.heroSkillsDialog.hidden) {
      hideHeroSkillsDialog();
    }

    setText(elements.mode, modeLabel(snapshot.mode));
    setText(elements.save, fileName(snapshot.save_file));
    setText(elements.map, fileName(snapshot.map_file));
    setText(elements.refresh, "Loaded");
    setText(elements.heroCount, `${heroes.length} heroes detected`);
    elements.gameFolderPath.value = snapshot.autosave_dir || elements.gameFolderPath.value || "";

    heroState.heroes = heroes;
    heroState.recentHeroes = snapshot.recent_heroes || [];
    heroState.selectedHeroId = selectedHeroId;
    elements.heroSearch.disabled = false;
    renderRecentHeroes(heroState.recentHeroes);
    renderHeroes();
    mapView.snapshot = snapshot;
    mapView.level = nextViewState.level;
    mapView.showHiddenNeutrals = Boolean(snapshot.show_hidden);
    elements.showHiddenToggle.checked = mapView.showHiddenNeutrals;
    elements.showHiddenToggle.disabled = false;
    rebuildMarkerCache(snapshot);
    mapView.hoveredMarkerId = null;
    mapView.activeMarkerId = null;
    elements.canvas.classList.remove("has-marker-hover");
    hideMapTooltip();
    hideTargetContextMenu();
    invalidateEstimateRequests();
    setTargetDetails(null);
    if (nextViewState.preserveView) {
      mapView.zoom = nextViewState.zoom;
      mapView.pan = nextViewState.pan;
    } else {
      fitMapToCanvas(snapshot);
    }
    updateLevelControls(snapshot);
    updateMapMetrics(snapshot);
    updatePathModeControl();
    drawMap();

    setEstimateMessage("No simulation run.");
    clearPathResult("No path requested.");
    clearScanResults("No scan results.");
    syncSaveControls(snapshot);
    syncGameFolderControls();
    syncHeroRankingControls();
    if (!elements.heroRankingDialog.hidden) {
      renderHeroRanking();
    }
  }

  function renderError(message) {
    setText(elements.mode, "Snapshot unavailable");
    setText(elements.save, "None");
    setText(elements.map, "None");
    setText(elements.refresh, "Error");
    setText(elements.heroCount, "No snapshot loaded");
    heroState.heroes = [];
    heroState.recentHeroes = [];
    heroState.selectedHeroId = null;
    heroState.selectingHeroId = null;
    elements.heroSearch.disabled = true;
    elements.gameFolderPath.value = "";
    renderRecentHeroes([]);
    appendEmpty(elements.heroList, "Unable to load heroes.");
    setText(elements.mapSummary, "Snapshot unavailable");
    setText(elements.objectCount, "0 targets");
    setText(elements.mapOverlayTitle, "Snapshot unavailable");
    setText(elements.mapOverlayDetail, message);
    clearNode(elements.mapLevelControl);
    mapView.snapshot = null;
    mapView.markers = [];
    mapView.level = 0;
    mapView.hoveredMarkerId = null;
    mapView.activeMarkerId = null;
    elements.canvas.classList.remove("has-marker-hover");
    elements.showHiddenToggle.checked = false;
    elements.showHiddenToggle.disabled = true;
    mapView.pathMode = false;
    updatePathModeControl();
    hideMapTooltip();
    hideTargetContextMenu();
    invalidateEstimateRequests();
    setTargetDetails(null);
    setEstimateMessage("No simulation run.");
    clearPathResult("No path requested.");
    clearScanResults("No scan results.");
    syncSaveControls(null);
    syncGameFolderControls();
    syncHeroRankingControls();
    hideHeroSkillsDialog();
    hideHeroRankingDialog();
    drawMap();
  }

  function loadState() {
    const epoch = nextStateEpoch();
    stateRequests.loading = true;
    stateRequests.loadingEpoch = epoch;
    invalidateEstimateRequests();
    clearScanResults("No scan results.");
    setText(elements.refresh, "Loading");
    elements.refreshButton.disabled = true;
    syncSaveControls(mapView.snapshot);
    syncGameFolderControls();

    return getJson("/api/state", "state request failed")
      .then((snapshot) => {
        if (epoch !== stateRequests.epoch) {
          return;
        }
        renderSnapshot(snapshot);
      })
      .catch((error) => {
        if (epoch === stateRequests.epoch) {
          renderError(error.message);
        }
      })
      .finally(() => {
        if (stateRequests.loadingEpoch === epoch) {
          stateRequests.loading = false;
          elements.refreshButton.disabled = false;
          syncSaveControls(mapView.snapshot);
          syncGameFolderControls();
        }
      });
  }

  function checkHealth() {
    return fetch("/api/health")
      .then((response) => {
        if (!response.ok) {
          throw new Error("health check failed");
        }
        return response.json();
      })
      .then((payload) => {
        setHealth(payload.ok ? "Local server ready" : "Local server unavailable", payload.ok ? "ready" : "error");
      })
      .catch(() => {
        setHealth("Local server unavailable", "error");
      });
  }

  elements.refreshButton.addEventListener("click", () => {
    refreshStateAndSaves();
  });

  elements.gameFolderPicker.addEventListener("change", () => {
    if (elements.gameFolderPicker.value) {
      elements.gameFolderPath.value = elements.gameFolderPicker.value;
      syncGameFolderControls();
    }
  });

  elements.gameFolderPath.addEventListener("input", () => {
    syncGameFolderControls();
  });

  elements.useGameFolderButton.addEventListener("click", () => {
    const autosaveDir = String(elements.gameFolderPath.value || "").trim();
    if (autosaveDir) {
      switchGameFolder({ autosave_dir: autosaveDir }, "Changing game folder");
    }
  });

  elements.savePicker.addEventListener("change", () => {
    const saveFile = elements.savePicker.value;
    if (saveFile) {
      switchSaveMode(PINNED_MODE, saveFile);
    }
  });

  elements.previousSaveButton.addEventListener("click", () => {
    navigateSave(-1);
  });

  elements.nextSaveButton.addEventListener("click", () => {
    navigateSave(1);
  });

  elements.followLatestButton.addEventListener("click", () => {
    showFollowLatestDialog();
  });

  elements.followCurrentFolderButton.addEventListener("click", () => {
    hideFollowLatestDialog();
    switchSaveMode(FOLLOW_LATEST_MODE);
  });

  elements.followLatestFolderButton.addEventListener("click", () => {
    hideFollowLatestDialog();
    switchGameFolder({ use_latest_game_folder: true }, "Switching to latest game folder");
  });

  elements.followCancelButton.addEventListener("click", () => {
    hideFollowLatestDialog();
  });

  elements.followLatestDialog.addEventListener("click", (event) => {
    if (event.target === elements.followLatestDialog) {
      hideFollowLatestDialog();
    }
  });

  elements.heroRankingButton.addEventListener("click", () => {
    showHeroRankingDialog();
  });

  elements.heroSkillsButton.addEventListener("click", () => {
    showHeroSkillsDialog();
  });

  elements.heroSkillsCloseButton.addEventListener("click", () => {
    hideHeroSkillsDialog();
  });

  elements.heroSkillsDialog.addEventListener("click", (event) => {
    if (event.target === elements.heroSkillsDialog) {
      hideHeroSkillsDialog();
    }
  });

  elements.heroSkillsSaveButton.addEventListener("click", () => {
    saveHeroSkills();
  });

  elements.heroSkillsResetButton.addEventListener("click", () => {
    resetHeroSkills();
  });

  elements.heroSkillsCompareButton.addEventListener("click", () => {
    compareHeroSkillOffers();
  });

  elements.heroRankingCloseButton.addEventListener("click", () => {
    hideHeroRankingDialog();
  });

  elements.heroRankingDialog.addEventListener("click", (event) => {
    if (event.target === elements.heroRankingDialog) {
      hideHeroRankingDialog();
    }
  });

  elements.heroSearch.addEventListener("input", () => {
    heroState.searchQuery = elements.heroSearch.value;
    renderHeroes();
  });

  elements.showRemovedToggle.addEventListener("change", () => {
    mapView.showRemovedNeutrals = elements.showRemovedToggle.checked;
    mapView.hoveredMarkerId = null;
    elements.canvas.classList.remove("has-marker-hover");
    hideMapTooltip();
    hideTargetContextMenu();
    rebuildMarkerCache(mapView.snapshot);
    if (!mapView.markers.some((marker) => marker.id === mapView.activeMarkerId)) {
      mapView.activeMarkerId = null;
      setTargetDetails(null);
    }
    updateMapMetrics(mapView.snapshot);
    drawMap();
  });

  elements.showHiddenToggle.addEventListener("change", () => {
    setShowHiddenNeutrals(elements.showHiddenToggle.checked);
  });

  elements.routeOverlayToggle.addEventListener("change", () => {
    mapView.showRouteOverlay = elements.routeOverlayToggle.checked;
    drawMap();
  });

  elements.pathModeToggle.addEventListener("change", () => {
    setPathMode(elements.pathModeToggle.checked);
  });

  elements.scanButton.addEventListener("click", () => {
    runRadiusScan();
  });

  elements.scanRadius.addEventListener("input", () => {
    updateScanControls();
  });

  elements.canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) {
      return;
    }
    hideMapTooltip();
    hideTargetContextMenu();
    elements.canvas.setPointerCapture(event.pointerId);
    mapView.drag = {
      pointerId: event.pointerId,
      start: canvasPoint(event),
      pan: { x: mapView.pan.x, y: mapView.pan.y }
    };
    mapView.movedDuringDrag = false;
  });

  elements.canvas.addEventListener("pointermove", (event) => {
    const point = canvasPoint(event);
    if (mapView.drag && mapView.drag.pointerId === event.pointerId) {
      const dx = point.x - mapView.drag.start.x;
      const dy = point.y - mapView.drag.start.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) {
        mapView.movedDuringDrag = true;
      }
      mapView.pan = {
        x: mapView.drag.pan.x + dx,
        y: mapView.drag.pan.y + dy
      };
      hideMapTooltip();
      drawMap();
      return;
    }

    const marker = hitTestMarker(mapView.markers, point, mapView);
    mapView.hoveredMarkerId = marker ? marker.id : null;
    elements.canvas.classList.toggle("has-marker-hover", Boolean(marker));
    if (marker) {
      showMapTooltip(marker, event);
    } else {
      hideMapTooltip();
    }
    if (marker && !mapView.activeMarkerId) {
      setTargetDetails(marker);
    } else if (!marker && !mapView.activeMarkerId) {
      setTargetDetails(null);
    }
    drawMap();
  });

  elements.canvas.addEventListener("pointerup", (event) => {
    if (event.button !== 0) {
      return;
    }
    const point = canvasPoint(event);
    const didDrag = mapView.movedDuringDrag;
    mapView.drag = null;
    mapView.movedDuringDrag = false;
    if (didDrag) {
      return;
    }
    const marker = hitTestMarker(mapView.markers, point, mapView);
    mapView.activeMarkerId = marker ? marker.id : null;
    setTargetDetails(marker);
    if (mapView.pathMode) {
      requestPath(marker, point);
    } else {
      simulateTarget(marker);
    }
    drawMap();
  });

  elements.canvas.addEventListener("contextmenu", (event) => {
    const point = canvasPoint(event);
    const marker = hitTestMarker(mapView.markers, point, mapView);
    if (
      !marker
      || (
        marker.type !== "neutral"
        && marker.type !== "hero"
        && marker.type !== "portal"
      )
    ) {
      hideTargetContextMenu();
      return;
    }

    event.preventDefault();
    mapView.activeMarkerId = marker.id;
    setTargetDetails(marker);
    hideMapTooltip();
    showTargetContextMenu(marker, event);
    drawMap();
  });

  elements.canvas.addEventListener("pointerleave", () => {
    mapView.hoveredMarkerId = null;
    elements.canvas.classList.remove("has-marker-hover");
    hideMapTooltip();
    drawMap();
  });

  elements.canvas.addEventListener("wheel", (event) => {
    if (!mapView.snapshot) {
      return;
    }
    event.preventDefault();
    const point = canvasPoint(event);
    const factor = event.deltaY < 0 ? 1.12 : 0.89;
    const zoomed = zoomAtPoint(mapView, point, mapView.zoom * factor);
    mapView.zoom = zoomed.zoom;
    mapView.pan = zoomed.pan;
    drawMap();
  }, { passive: false });

  if (window.ResizeObserver) {
    const resizeObserver = new ResizeObserver(() => {
      drawMap();
    });
    resizeObserver.observe(elements.canvas);
  } else {
    window.addEventListener("resize", drawMap);
  }

  window.__battleEstimatorGuiTest = {
    buildMarkerCache,
    clampZoom,
    defaultLevelForSnapshot,
    estimateTargetLabel,
    filterHeroesForQuery,
    formatWinPct,
    hitTestMarker,
    markerTooltipText,
    matchRecentHeroName,
    markerContainsScreenPoint,
    markerScreenRadius,
    nextViewStateForSnapshot,
    rankedMapHeroes,
    recentHeroChipState,
    renderSnapshot,
    resolveSelectedHeroId,
    routeRowsForLevel,
    routeStateForChar,
    routeStyleForChar,
    drawRouteOverlay,
    drawPathRoute,
    pathPointForPosition,
    pathStepPosition,
    scanClassForWinPct,
    scanResultLookup,
    sameMapGeometry,
    sortedScanResults,
    screenToWorld,
    centerOnHero,
    centerOnMarkerId,
    centerOnWorldPoint,
    currentMapViewForTest,
    currentPathStateForTest,
    compareHeroSkillOffers,
    focusPathSegment,
    focusPortalDestination,
    heroSkillOfferValidationMessage,
    heroSkillSaveValidationMessage,
    heroSkillSlotsFromPayload,
    hideHeroSkillsDialog,
    isFreshEstimatePayload,
    isFreshPathPayload,
    isFreshScanPayload,
    pathSegmentEndPosition,
    pathSegmentFocusPosition,
    pathSegmentMeta,
    pathSegmentsForPayload,
    pathSegmentStartPosition,
    pathSegmentText,
    pathSegmentTypeLabel,
    portalDestinationText,
    portalMarkerLabel,
    portalTypeLabel,
    resetHeroSkills,
    saveHeroSkills,
    setPathMode,
    showHeroSkillsDialog,
    simulationClickDecision,
    tilePositionForCanvasPoint,
    verdictForWinPct,
    worldToScreen,
    zoomAtPoint
  };

  elements.showRemovedToggle.checked = mapView.showRemovedNeutrals;
  elements.showHiddenToggle.checked = mapView.showHiddenNeutrals;
  elements.showHiddenToggle.disabled = true;
  elements.routeOverlayToggle.checked = mapView.showRouteOverlay;
  updatePathModeControl();
  renderTargetFilterControl();
  renderScanSortControl();
  syncHeroRankingControls();
  syncHeroSkillControls();
  elements.targetContextMenu.addEventListener("click", (event) => {
    event.stopPropagation();
  });
  window.addEventListener("click", hideTargetContextMenu);
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideTargetContextMenu();
      hideFollowLatestDialog();
      hideHeroRankingDialog();
      hideHeroSkillsDialog();
    }
  });
  startAutoRefresh();
  checkHealth().finally(refreshStateAndSaves);
}());
