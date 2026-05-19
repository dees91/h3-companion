(function () {
  "use strict";

  const elements = {
    health: document.getElementById("health-status"),
    mode: document.getElementById("mode-status"),
    save: document.getElementById("save-status"),
    map: document.getElementById("map-status"),
    refresh: document.getElementById("refresh-status"),
    refreshButton: document.getElementById("refresh-button"),
    heroSearch: document.getElementById("hero-search"),
    heroCount: document.getElementById("hero-count"),
    recentHeroes: document.getElementById("recent-heroes"),
    heroList: document.getElementById("hero-list"),
    mapSummary: document.getElementById("map-summary"),
    objectCount: document.getElementById("object-count"),
    mapOverlayTitle: document.getElementById("map-overlay-title"),
    mapOverlayDetail: document.getElementById("map-overlay-detail"),
    targetState: document.getElementById("target-state"),
    estimateState: document.getElementById("estimate-state"),
    scanRadius: document.getElementById("scan-radius"),
    scanTargetType: document.getElementById("scan-target-type"),
    scanButton: document.getElementById("scan-button"),
    scanState: document.getElementById("scan-state"),
    canvas: document.getElementById("battle-map"),
    zoom: document.getElementById("zoom-status")
  };
  const canvasContext = elements.canvas.getContext("2d");
  const mapView = {
    snapshot: null,
    zoom: 1,
    minZoom: 0.35,
    maxZoom: 5,
    pan: { x: 0, y: 0 },
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
    results: [],
    resultByTargetId: new Map()
  };

  function setHealth(text, className) {
    elements.health.textContent = text;
    elements.health.className = `status-pill ${className || ""}`.trim();
  }

  function setText(element, value) {
    element.textContent = value || "...";
    element.title = value || "";
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

  function buildMarkerCache(snapshot, tileSize) {
    if (!snapshot) {
      return [];
    }

    const selectedHeroId = snapshot.selected_hero_id;
    const heroMarkers = (snapshot.heroes || [])
      .filter((hero) => hero.position)
      .map((hero) => ({
        type: "hero",
        id: hero.id,
        label: hero.name || hero.id,
        position: hero.position,
        world: {
          x: (hero.position.x + 0.5) * tileSize,
          y: (hero.position.y + 0.5) * tileSize
        },
        radius: 8,
        selected: hero.id === selectedHeroId,
        removed: false,
        unsupported: false,
        summary: hero.army_summary || `${hero.total_creatures || 0} creatures`
      }));

    const neutralMarkers = (snapshot.neutral_targets || [])
      .filter((target) => target.position)
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
        unsupported: target.estimator_creature_id === null,
        summary: target.removal_note || `subid ${target.h3m_subid}`
      }));

    return heroMarkers.concat(neutralMarkers);
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
    return (dx * dx) + (dy * dy) <= radius * radius;
  }

  function canvasPoint(event) {
    const rect = elements.canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top
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

  function centerOnHero(heroId) {
    const marker = mapView.markers.find((candidate) => (
      candidate.type === "hero" && candidate.id === heroId
    ));
    return centerOnMarker(marker);
  }

  function centerOnMarkerId(targetId) {
    const marker = mapView.markers.find((candidate) => candidate.id === targetId);
    if (centerOnMarker(marker)) {
      return marker;
    }
    return null;
  }

  function centerOnMarker(marker) {
    if (!marker) {
      return false;
    }

    const canvasSize = syncCanvasSize();
    mapView.pan = {
      x: (canvasSize.width / 2) - (marker.world.x * mapView.zoom),
      y: (canvasSize.height / 2) - (marker.world.y * mapView.zoom)
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

    drawMarkers();
    elements.zoom.textContent = `Zoom ${Math.round(mapView.zoom * 100)}%`;
  }

  function drawMarkers() {
    mapView.markers.forEach((marker) => {
      const screen = worldToScreen(marker.world, mapView);
      const radius = markerScreenRadius(marker, mapView) - 3;
      const isActive = marker.id === mapView.activeMarkerId;
      const isHover = marker.id === mapView.hoveredMarkerId;
      const scanColors = scanColorsForMarker(marker);

      canvasContext.save();
      canvasContext.globalAlpha = marker.removed ? 0.45 : 1;
      if (marker.type === "hero") {
        canvasContext.translate(screen.x, screen.y);
        canvasContext.rotate(Math.PI / 4);
        canvasContext.fillStyle = marker.selected
          ? "#f5c542"
          : (scanColors ? scanColors.fill : "#2d6cdf");
        canvasContext.strokeStyle = marker.selected
          ? "#7a4d00"
          : (scanColors ? scanColors.stroke : "#143a75");
        canvasContext.lineWidth = marker.selected ? 3 : 2;
        canvasContext.fillRect(-radius, -radius, radius * 2, radius * 2);
        canvasContext.strokeRect(-radius, -radius, radius * 2, radius * 2);
        canvasContext.rotate(-Math.PI / 4);
        canvasContext.translate(-screen.x, -screen.y);
        if (marker.selected) {
          canvasContext.beginPath();
          canvasContext.strokeStyle = "#7a4d00";
          canvasContext.lineWidth = 2;
          canvasContext.arc(screen.x, screen.y, radius + 7, 0, Math.PI * 2);
          canvasContext.stroke();
        }
      } else {
        canvasContext.beginPath();
        canvasContext.fillStyle = scanColors
          ? scanColors.fill
          : (marker.unsupported ? "#8b95a3" : "#c2413d");
        canvasContext.strokeStyle = scanColors
          ? scanColors.stroke
          : (marker.removed ? "#4b5563" : "#7a1f1c");
        canvasContext.lineWidth = marker.unsupported || marker.removed ? 3 : 2;
        canvasContext.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
        canvasContext.fill();
        canvasContext.stroke();
      }

      if (isHover || isActive) {
        canvasContext.beginPath();
        canvasContext.strokeStyle = isActive ? "#111827" : "#4b5563";
        canvasContext.lineWidth = 2;
        canvasContext.arc(screen.x, screen.y, radius + 5, 0, Math.PI * 2);
        canvasContext.stroke();
      }

      if (marker.position && marker.position.z) {
        canvasContext.fillStyle = "#111827";
        canvasContext.font = "11px Arial, Helvetica, sans-serif";
        canvasContext.fillText(`z${marker.position.z}`, screen.x + radius + 4, screen.y - radius);
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
    if (marker.unsupported) {
      flags.push("unsupported");
    }
    const suffix = flags.length ? ` | ${flags.join(", ")}` : "";
    elements.targetState.textContent = `${marker.type} ${marker.id} | ${marker.label} | ${positionText(marker.position)}${suffix}`;
    elements.targetState.title = marker.summary || marker.label;
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
    if (!selectedHeroId) {
      return { simulate: false, message: "Select a hero before simulating." };
    }
    if (marker.type === "hero" && marker.id === selectedHeroId) {
      return { simulate: false, message: "Selected hero is not a simulation target." };
    }
    return { simulate: true, message: "" };
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

  function sortedScanResults(results) {
    return (results || []).slice().sort((left, right) => {
      const leftDistance = typeof left.distance === "number" ? left.distance : Number.MAX_SAFE_INTEGER;
      const rightDistance = typeof right.distance === "number" ? right.distance : Number.MAX_SAFE_INTEGER;
      if (leftDistance !== rightDistance) {
        return leftDistance - rightDistance;
      }
      return String(left.target_id || "").localeCompare(String(right.target_id || ""));
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
    elements.scanTargetType.disabled = !hasSnapshot || scanState.running;
    elements.scanButton.disabled = !canRun;
  }

  function clearScanResults(message) {
    scanState.requestId += 1;
    scanState.running = false;
    scanState.heroId = null;
    scanState.radius = null;
    scanState.targetType = elements.scanTargetType.value || "all";
    scanState.results = [];
    scanState.resultByTargetId = new Map();
    appendEmpty(elements.scanState, message || "No scan results.");
    updateScanControls();
    drawMap();
  }

  function setScanMessage(message, className) {
    clearNode(elements.scanState);
    const item = document.createElement("p");
    item.className = className || "empty-state";
    item.textContent = message;
    elements.scanState.appendChild(item);
  }

  function renderScanResults(payload) {
    const results = sortedScanResults(payload.results || []);
    scanState.running = false;
    scanState.heroId = payload.hero_id;
    scanState.radius = payload.radius;
    scanState.targetType = payload.target_type;
    scanState.results = results;
    scanState.resultByTargetId = scanResultLookup(results);
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
    const targetType = elements.scanTargetType.value || "all";
    if (!heroState.selectedHeroId) {
      setScanMessage("Select a hero before scanning.");
      return;
    }
    if (radius === null) {
      setScanMessage("Radius must be an integer from 0 to 200.", "empty-state error-text");
      return;
    }

    const request = {
      requestId: scanState.requestId + 1,
      heroId: heroState.selectedHeroId,
      radius,
      targetType
    };
    scanState.requestId = request.requestId;
    scanState.running = true;
    updateScanControls();
    setScanMessage("Running scan...", "empty-state");

    postJson(
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

      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = hero.name || hero.id;
      title.title = title.textContent;

      const meta = document.createElement("div");
      meta.className = "item-meta";
      meta.textContent = `${positionText(hero.position)} | ${hero.total_creatures || 0} creatures`;
      meta.title = hero.army_summary || meta.textContent;

      row.appendChild(title);
      row.appendChild(meta);
      elements.heroList.appendChild(row);
    });
  }

  function applySelectedHero(heroId, recentHeroes) {
    invalidateEstimateRequests();
    heroState.selectedHeroId = heroId || null;
    heroState.recentHeroes = recentHeroes || heroState.recentHeroes;
    if (mapView.snapshot) {
      mapView.snapshot.selected_hero_id = heroState.selectedHeroId;
      mapView.snapshot.recent_heroes = heroState.recentHeroes;
    }
    const tileSize = tileSizeForMap((mapView.snapshot && mapView.snapshot.map) || {});
    mapView.markers = buildMarkerCache(mapView.snapshot, tileSize);
    renderRecentHeroes(heroState.recentHeroes);
    renderHeroes();
    if (!centerOnHero(heroState.selectedHeroId)) {
      drawMap();
    }
    setEstimateMessage("No simulation run.");
    clearScanResults("No scan results.");
  }

  function selectHero(heroId) {
    if (!heroId || heroState.selectingHeroId) {
      return;
    }
    invalidateEstimateRequests();
    heroState.selectingHeroId = heroId;
    setText(elements.refresh, "Selecting hero");
    renderHeroes();

    postJson(
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

  function renderSnapshot(snapshot) {
    const heroes = snapshot.heroes || [];
    const targets = snapshot.neutral_targets || [];
    const map = snapshot.map || {};
    const dimensions = map.width && map.height
      ? `${map.width} x ${map.height} x ${map.levels || 1}`
      : "No map";

    setText(elements.mode, snapshot.mode || "unknown");
    setText(elements.save, fileName(snapshot.save_file));
    setText(elements.map, fileName(snapshot.map_file));
    setText(elements.refresh, "Loaded");
    setText(elements.heroCount, `${heroes.length} heroes detected`);
    setText(elements.mapSummary, dimensions);
    setText(elements.objectCount, `${targets.length} targets`);
    setText(elements.mapOverlayTitle, dimensions);
    setText(elements.mapOverlayDetail, `${heroes.length} heroes | ${targets.length} neutrals`);

    heroState.heroes = heroes;
    heroState.recentHeroes = snapshot.recent_heroes || [];
    heroState.selectedHeroId = snapshot.selected_hero_id || null;
    elements.heroSearch.disabled = false;
    renderRecentHeroes(heroState.recentHeroes);
    renderHeroes();
    mapView.snapshot = snapshot;
    const tileSize = tileSizeForMap(snapshot.map || {});
    mapView.markers = buildMarkerCache(snapshot, tileSize);
    mapView.hoveredMarkerId = null;
    mapView.activeMarkerId = null;
    invalidateEstimateRequests();
    setTargetDetails(null);
    fitMapToCanvas(snapshot);
    drawMap();

    setEstimateMessage("No simulation run.");
    clearScanResults("No scan results.");
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
    renderRecentHeroes([]);
    appendEmpty(elements.heroList, "Unable to load heroes.");
    setText(elements.mapSummary, "Snapshot unavailable");
    setText(elements.objectCount, "0 targets");
    setText(elements.mapOverlayTitle, "Snapshot unavailable");
    setText(elements.mapOverlayDetail, message);
    mapView.snapshot = null;
    mapView.markers = [];
    mapView.hoveredMarkerId = null;
    mapView.activeMarkerId = null;
    invalidateEstimateRequests();
    setTargetDetails(null);
    setEstimateMessage("No simulation run.");
    clearScanResults("No scan results.");
    drawMap();
  }

  function loadState() {
    invalidateEstimateRequests();
    clearScanResults("No scan results.");
    setText(elements.refresh, "Loading");
    elements.refreshButton.disabled = true;

    return fetch("/api/state")
      .then((response) => {
        if (!response.ok) {
          return response.json().catch(() => ({})).then((payload) => {
            throw new Error(payload.error || `state request failed: ${response.status}`);
          });
        }
        return response.json();
      })
      .then((snapshot) => {
        renderSnapshot(snapshot);
      })
      .catch((error) => {
        renderError(error.message);
      })
      .finally(() => {
        elements.refreshButton.disabled = false;
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
    loadState();
  });

  elements.heroSearch.addEventListener("input", () => {
    heroState.searchQuery = elements.heroSearch.value;
    renderHeroes();
  });

  elements.scanButton.addEventListener("click", () => {
    runRadiusScan();
  });

  elements.scanRadius.addEventListener("input", () => {
    updateScanControls();
  });

  elements.scanTargetType.addEventListener("change", () => {
    updateScanControls();
  });

  elements.canvas.addEventListener("pointerdown", (event) => {
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
      drawMap();
      return;
    }

    const marker = hitTestMarker(mapView.markers, point, mapView);
    mapView.hoveredMarkerId = marker ? marker.id : null;
    elements.canvas.classList.toggle("has-marker-hover", Boolean(marker));
    if (marker && !mapView.activeMarkerId) {
      setTargetDetails(marker);
    } else if (!marker && !mapView.activeMarkerId) {
      setTargetDetails(null);
    }
    drawMap();
  });

  elements.canvas.addEventListener("pointerup", (event) => {
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
    simulateTarget(marker);
    drawMap();
  });

  elements.canvas.addEventListener("pointerleave", () => {
    mapView.hoveredMarkerId = null;
    elements.canvas.classList.remove("has-marker-hover");
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
    estimateTargetLabel,
    filterHeroesForQuery,
    formatWinPct,
    hitTestMarker,
    matchRecentHeroName,
    markerContainsScreenPoint,
    markerScreenRadius,
    recentHeroChipState,
    scanClassForWinPct,
    scanResultLookup,
    sortedScanResults,
    screenToWorld,
    centerOnHero,
    isFreshEstimatePayload,
    isFreshScanPayload,
    simulationClickDecision,
    verdictForWinPct,
    worldToScreen,
    zoomAtPoint
  };

  checkHealth().finally(loadState);
}());
