(function () {
  "use strict";

  const status = document.getElementById("health-status");

  fetch("/api/health")
    .then((response) => {
      if (!response.ok) {
        throw new Error("health check failed");
      }
      return response.json();
    })
    .then((payload) => {
      status.textContent = payload.ok ? "Local server ready" : "Local server unavailable";
    })
    .catch(() => {
      status.textContent = "Local server unavailable";
    });
}());
