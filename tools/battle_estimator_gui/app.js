(function () {
  "use strict";

  const elements = {
    health: document.getElementById("health-status"),
    mode: document.getElementById("mode-status"),
    save: document.getElementById("save-status"),
    map: document.getElementById("map-status"),
    refresh: document.getElementById("refresh-status"),
    refreshButton: document.getElementById("refresh-button"),
    heroCount: document.getElementById("hero-count"),
    recentHeroes: document.getElementById("recent-heroes"),
    heroList: document.getElementById("hero-list"),
    mapSummary: document.getElementById("map-summary"),
    objectCount: document.getElementById("object-count"),
    mapOverlayTitle: document.getElementById("map-overlay-title"),
    mapOverlayDetail: document.getElementById("map-overlay-detail"),
    targetState: document.getElementById("target-state"),
    estimateState: document.getElementById("estimate-state"),
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

  function setHealth(text, className) {
    elements.health.textContent = text;
    elements.health.className = `status-pill ${className || ""}`.trim();
  }

  function setText(element, value) {
    element.textContent = value || "...";
    element.title = value || "";
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

      canvasContext.save();
      canvasContext.globalAlpha = marker.removed ? 0.45 : 1;
      if (marker.type === "hero") {
        canvasContext.translate(screen.x, screen.y);
        canvasContext.rotate(Math.PI / 4);
        canvasContext.fillStyle = marker.selected ? "#f5c542" : "#2d6cdf";
        canvasContext.strokeStyle = marker.selected ? "#7a4d00" : "#143a75";
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
        canvasContext.fillStyle = marker.unsupported ? "#8b95a3" : "#c2413d";
        canvasContext.strokeStyle = marker.removed ? "#4b5563" : "#7a1f1c";
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

  function renderRecentHeroes(recentHeroes) {
    clearNode(elements.recentHeroes);
    if (!recentHeroes || recentHeroes.length === 0) {
      elements.recentHeroes.className = "chip-row empty-state";
      elements.recentHeroes.textContent = "None";
      return;
    }

    elements.recentHeroes.className = "chip-row";
    recentHeroes.slice(0, 8).forEach((name) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = name;
      chip.title = name;
      elements.recentHeroes.appendChild(chip);
    });
  }

  function renderHeroes(heroes) {
    if (!heroes || heroes.length === 0) {
      appendEmpty(elements.heroList, "No heroes detected.");
      return;
    }

    clearNode(elements.heroList);
    heroes.slice(0, 24).forEach((hero) => {
      const row = document.createElement("article");
      row.className = "list-item";

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

    renderRecentHeroes(snapshot.recent_heroes || []);
    renderHeroes(heroes);
    mapView.snapshot = snapshot;
    const tileSize = tileSizeForMap(snapshot.map || {});
    mapView.markers = buildMarkerCache(snapshot, tileSize);
    mapView.hoveredMarkerId = null;
    mapView.activeMarkerId = null;
    setTargetDetails(null);
    fitMapToCanvas(snapshot);
    drawMap();

    elements.estimateState.textContent = "No simulation run.";
    appendEmpty(elements.scanState, "No scan results.");
  }

  function renderError(message) {
    setText(elements.mode, "Snapshot unavailable");
    setText(elements.save, "None");
    setText(elements.map, "None");
    setText(elements.refresh, "Error");
    setText(elements.heroCount, "No snapshot loaded");
    renderRecentHeroes([]);
    appendEmpty(elements.heroList, "Unable to load heroes.");
    appendEmpty(elements.scanState, "No scan results.");
    setText(elements.mapSummary, "Snapshot unavailable");
    setText(elements.objectCount, "0 targets");
    setText(elements.mapOverlayTitle, "Snapshot unavailable");
    setText(elements.mapOverlayDetail, message);
    mapView.snapshot = null;
    mapView.markers = [];
    mapView.hoveredMarkerId = null;
    mapView.activeMarkerId = null;
    setTargetDetails(null);
    drawMap();
  }

  function loadState() {
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
    hitTestMarker,
    markerContainsScreenPoint,
    markerScreenRadius,
    screenToWorld,
    worldToScreen,
    zoomAtPoint
  };

  checkHealth().finally(loadState);
}());
