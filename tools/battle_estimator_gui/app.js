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
    scanState: document.getElementById("scan-state")
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

    elements.targetState.textContent = "No target selected.";
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

  checkHealth().finally(loadState);
}());
