(() => {
  const DEFAULT_POS = [25.03396, 121.56447];

  const els = {
    mapPane: document.querySelector(".map-pane"),
    headerDot: document.getElementById("header-status-dot"),
    headerText: document.getElementById("header-status-text"),
    btnPickStart: document.getElementById("btn-pick-start"),
    btnSearchToggle: document.getElementById("btn-search-toggle"),
    layerSelect: document.getElementById("layer-select"),
    chkFollow: document.getElementById("chk-follow"),
    btnRecenter: document.getElementById("btn-recenter"),
    searchPopover: document.getElementById("search-popover"),
    searchForm: document.getElementById("search-form"),
    searchInput: document.getElementById("search-input"),
    btnSearchClose: document.getElementById("btn-search-close"),
    searchStatus: document.getElementById("search-status"),
    searchResults: document.getElementById("search-results"),
    searchPreviewBar: document.getElementById("search-preview-bar"),
    previewName: document.getElementById("preview-name"),
    previewAddress: document.getElementById("preview-address"),
    btnApplyPreview: document.getElementById("btn-apply-preview"),
    pickBanner: document.getElementById("pick-banner"),
    tileWarning: document.getElementById("tile-warning"),
    hudCoords: document.getElementById("hud-coords"),
    hudMotion: document.getElementById("hud-motion"),
    hudDistance: document.getElementById("hud-distance"),
    btnZoomIn: document.getElementById("btn-zoom-in"),
    btnZoomOut: document.getElementById("btn-zoom-out"),
    btnClearTrail: document.getElementById("btn-clear-trail"),
    motionBadge: document.getElementById("motion-badge"),
    joystickPad: document.getElementById("joystick-pad"),
    joystickKnob: document.getElementById("joystick-knob"),
    btnToggleMotion: document.getElementById("btn-toggle-motion"),
    speedValue: document.getElementById("speed-value"),
    speedSlider: document.getElementById("speed-slider"),
    presetButtons: Array.from(document.querySelectorAll(".preset-btn")),
    devicePhaseBadge: document.getElementById("device-phase-badge"),
    deviceLabel: document.getElementById("device-label"),
    deviceFlags: document.getElementById("device-flags"),
    deviceMessage: document.getElementById("device-message"),
    btnInspect: document.getElementById("btn-inspect"),
    btnConnect: document.getElementById("btn-connect"),
    btnStartSync: document.getElementById("btn-start-sync"),
    btnRestore: document.getElementById("btn-restore"),
    btnDisconnect: document.getElementById("btn-disconnect"),
    btnPair: document.getElementById("btn-pair"),
    btnRevealDev: document.getElementById("btn-reveal-dev"),
    btnMountDdi: document.getElementById("btn-mount-ddi"),
  };

  let pickingStart = false;
  let previewPlace = null;
  let previewMarker = null;
  let searchDebounce = null;
  let busyAction = false;
  let latestState = null;

  // Map setup
  const tileLayers = {
    dark: L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      attribution: "&copy; OpenStreetMap &copy; CARTO",
      maxZoom: 20,
    }),
    osm: L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 19,
    }),
    satellite: L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { attribution: "Tiles &copy; Esri", maxZoom: 19 }
    ),
  };

  const map = L.map("map", {
    center: DEFAULT_POS,
    zoom: 16,
    zoomControl: false,
  });

  let activeLayer = tileLayers.dark.addTo(map);
  Object.values(tileLayers).forEach((layer) => {
    layer.on("tileerror", () => {
      els.tileWarning.classList.remove("hidden");
    });
    layer.on("tileload", () => {
      els.tileWarning.classList.add("hidden");
    });
  });

  function headingIconHtml(bearing) {
    return `
      <svg width="48" height="48" viewBox="0 0 48 48" style="display:block">
        <circle cx="24" cy="24" r="20" fill="rgba(217,245,110,0.20)" />
        <circle cx="24" cy="24" r="13" fill="#121e14" stroke="#d9f56e" stroke-width="2" />
        <g transform="rotate(${bearing}, 24, 24)">
          <path d="M24 13 L30 30 L24 26 L18 30 Z" fill="#d9f56e" />
        </g>
      </svg>
    `;
  }

  let currentBearing = 0;
  const headingMarker = L.marker(DEFAULT_POS, {
    icon: L.divIcon({
      className: "heading-marker-wrap",
      html: headingIconHtml(0),
      iconSize: [48, 48],
      iconAnchor: [24, 24],
    }),
    interactive: false,
  }).addTo(map);

  const trailLine = L.polyline([DEFAULT_POS], {
    color: "#d1f266",
    weight: 4,
    opacity: 0.9,
    lineCap: "round",
    lineJoin: "round",
  }).addTo(map);

  // WebSocket communication
  let ws = null;
  let wsReconnectTimer = null;

  function sendWs(payload) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  }

  function connectWs() {
    if (wsReconnectTimer) {
      clearTimeout(wsReconnectTimer);
      wsReconnectTimer = null;
    }
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        applyState(data);
      } catch (_) {}
    };
    ws.onclose = () => {
      wsReconnectTimer = setTimeout(connectWs, 1200);
    };
  }

  async function postDevice(endpoint) {
    if (busyAction) return;
    busyAction = true;
    renderButtons();
    try {
      const resp = await fetch(endpoint, { method: "POST" });
      const data = await resp.json();
      if (latestState) {
        latestState.device = data;
        applyState(latestState);
      }
    } catch (err) {
      showDeviceNotice(`操作失敗：${err}`, true);
    } finally {
      busyAction = false;
      renderButtons();
    }
  }

  function showDeviceNotice(text, isError) {
    if (!text) {
      els.deviceMessage.classList.add("hidden");
      els.deviceMessage.textContent = "";
      return;
    }
    els.deviceMessage.textContent = text;
    els.deviceMessage.className = `notice-box ${isError ? "error" : "info"}`;
  }

  function formatDistance(meters) {
    if (meters >= 1000) return `${(meters / 1000).toFixed(2)} km`;
    return `${Math.round(meters)} m`;
  }

  function setKnobVisual(east, north) {
    const maxOffset = 46;
    const x = east * maxOffset;
    const y = -north * maxOffset;
    els.joystickKnob.style.transform = `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`;
  }

  function applyState(state) {
    latestState = state;
    const nav = state.navigation;
    const dev = state.device;

    const latlng = [nav.position.latitude, nav.position.longitude];
    headingMarker.setLatLng(latlng);
    if (Math.abs(nav.bearing - currentBearing) > 0.4) {
      currentBearing = nav.bearing;
      headingMarker.setIcon(
        L.divIcon({
          className: "heading-marker-wrap",
          html: headingIconHtml(currentBearing),
          iconSize: [48, 48],
          iconAnchor: [24, 24],
        })
      );
    }
    trailLine.setLatLngs(nav.trail);

    if (els.chkFollow.checked && !pickingStart && !previewPlace) {
      const bounds = map.getBounds().pad(-0.2);
      if (!bounds.contains(latlng)) {
        map.panTo(latlng, { animate: false });
      }
    }

    els.hudCoords.textContent = `${nav.position.latitude.toFixed(5)}, ${nav.position.longitude.toFixed(5)}`;
    els.hudMotion.textContent = `${Math.round(nav.bearing)}° · ${nav.current_speed_kph.toFixed(1)} km/h`;
    els.hudDistance.textContent = formatDistance(nav.distance_m);

    const motionLabels = {
      awaiting_direction: "等待方向",
      moving: "移動中",
      paused: "已暫停",
    };
    els.motionBadge.textContent = motionLabels[nav.motion] || nav.motion;
    els.motionBadge.classList.toggle("active", nav.motion === "moving");
    els.btnToggleMotion.disabled = nav.motion === "awaiting_direction";
    els.btnToggleMotion.textContent = nav.motion === "moving" ? "暫停" : "開始";

    els.speedValue.textContent = `${nav.target_speed_kph.toFixed(1)} km/h`;
    if (document.activeElement !== els.speedSlider) {
      els.speedSlider.value = String(nav.target_speed_kph);
    }
    els.presetButtons.forEach((btn) => {
      const val = Number(btn.dataset.speed);
      btn.classList.toggle("active", Math.abs(val - nav.target_speed_kph) < 0.1);
    });

    // Device UI
    const phaseText = {
      idle: "未連線",
      connecting: "連線中…",
      ready: "已就緒",
      syncing: "同步中",
      restoring: "恢復定位中…",
      disconnecting: "中斷中…",
      error: "連線異常",
    };
    els.devicePhaseBadge.textContent = phaseText[dev.phase] || dev.phase;
    els.devicePhaseBadge.classList.toggle("active", dev.phase === "syncing" || dev.phase === "ready");
    els.deviceLabel.textContent = dev.device_label || "尚未偵測";

    const pairedTxt = dev.paired === null ? "—" : dev.paired ? "已信任" : "未配對";
    const devModeTxt = dev.developer_mode === null ? "—" : dev.developer_mode ? "已開啟" : "未開啟";
    els.deviceFlags.textContent = `${pairedTxt} / ${devModeTxt}`;

    if (dev.error) {
      showDeviceNotice(dev.error, true);
    } else if (dev.notice) {
      showDeviceNotice(dev.notice, false);
    } else {
      showDeviceNotice("", false);
    }

    // Header pill
    els.headerDot.className = "status-dot";
    if (dev.phase === "syncing") {
      els.headerDot.classList.add("syncing");
      els.headerText.textContent = `同步中 · ${dev.device_label || "iPhone"}`;
    } else if (dev.phase === "ready") {
      els.headerDot.classList.add("ready");
      els.headerText.textContent = `已連線 · ${dev.device_label || "iPhone"}`;
    } else if (dev.phase === "error") {
      els.headerDot.classList.add("error");
      els.headerText.textContent = "USB 連線異常";
    } else if (dev.restore_unconfirmed) {
      els.headerDot.classList.add("warn");
      els.headerText.textContent = "待恢復定位";
    } else {
      els.headerText.textContent = "本機預覽模式";
    }

    renderButtons();
  }

  function renderButtons() {
    const dev = latestState ? latestState.device : { phase: "idle", restore_unconfirmed: false };
    const phase = dev.phase;
    const connected = phase === "ready" || phase === "syncing";
    els.btnInspect.disabled = busyAction || connected;
    els.btnConnect.disabled = busyAction || connected || phase === "connecting";
    els.btnStartSync.disabled = busyAction || phase !== "ready" || Boolean(dev.restore_unconfirmed);
    els.btnRestore.disabled = busyAction || !connected;
    els.btnDisconnect.disabled = busyAction || !connected;
    els.btnPair.disabled = busyAction || connected;
    els.btnRevealDev.disabled = busyAction || connected;
    els.btnMountDdi.disabled = busyAction || connected;
  }

  // Picking start point on map
  function setPickingStart(enabled) {
    pickingStart = enabled;
    els.btnPickStart.classList.toggle("active", enabled);
    els.btnPickStart.textContent = enabled ? "取消選點" : "選擇起點";
    els.mapPane.classList.toggle("picking", enabled);
    els.pickBanner.classList.toggle("hidden", !enabled);
    if (enabled) closeSearch();
  }

  map.on("click", (ev) => {
    if (!pickingStart) return;
    sendWs({ action: "set_start", latitude: ev.latlng.lat, longitude: ev.latlng.lng });
    setPickingStart(false);
  });

  map.on("contextmenu", () => {
    if (pickingStart) setPickingStart(false);
  });

  // Search
  function closeSearch() {
    els.searchPopover.classList.add("hidden");
    els.btnSearchToggle.classList.remove("active");
    previewPlace = null;
    if (previewMarker) {
      map.removeLayer(previewMarker);
      previewMarker = null;
    }
    els.searchPreviewBar.classList.add("hidden");
  }

  async function runSearch(query) {
    const q = query.trim();
    if (!q) {
      els.searchResults.innerHTML = "";
      els.searchStatus.textContent = "";
      return;
    }
    els.searchStatus.textContent = "搜尋中…";
    const center = map.getCenter();
    try {
      const params = new URLSearchParams({
        q,
        lat: String(center.lat),
        lon: String(center.lng),
      });
      const resp = await fetch(`/api/search?${params.toString()}`);
      const data = await resp.json();
      els.searchResults.innerHTML = "";
      if (data.error) {
        els.searchStatus.textContent = data.error;
        return;
      }
      if (!data.results || data.results.length === 0) {
        els.searchStatus.textContent = "找不到符合的地點";
        return;
      }
      els.searchStatus.textContent = `找到 ${data.results.length} 筆結果`;
      data.results.forEach((place) => {
        const li = document.createElement("li");
        const title = document.createElement("strong");
        title.textContent = place.name;
        const addr = document.createElement("span");
        addr.textContent = place.address || `${place.latitude.toFixed(5)}, ${place.longitude.toFixed(5)}`;
        li.append(title, addr);
        li.addEventListener("click", () => selectPreview(place));
        els.searchResults.appendChild(li);
      });
    } catch (_) {
      els.searchStatus.textContent = "搜尋請求失敗，請確認網路連線。";
    }
  }

  function selectPreview(place) {
    previewPlace = place;
    if (previewMarker) map.removeLayer(previewMarker);
    previewMarker = L.marker([place.latitude, place.longitude]).addTo(map);
    map.setView([place.latitude, place.longitude], Math.max(map.getZoom(), 16));
    els.previewName.textContent = place.name;
    els.previewAddress.textContent =
      place.address || `${place.latitude.toFixed(5)}, ${place.longitude.toFixed(5)}`;
    els.searchPreviewBar.classList.remove("hidden");
  }

  els.btnPickStart.addEventListener("click", () => setPickingStart(!pickingStart));
  els.btnSearchToggle.addEventListener("click", () => {
    const opening = els.searchPopover.classList.contains("hidden");
    if (opening) {
      setPickingStart(false);
      els.searchPopover.classList.remove("hidden");
      els.btnSearchToggle.classList.add("active");
      els.searchInput.focus();
    } else {
      closeSearch();
    }
  });
  els.btnSearchClose.addEventListener("click", closeSearch);
  els.searchInput.addEventListener("input", () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => runSearch(els.searchInput.value), 350);
  });
  els.searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    clearTimeout(searchDebounce);
    runSearch(els.searchInput.value);
  });
  els.btnApplyPreview.addEventListener("click", () => {
    if (!previewPlace) return;
    sendWs({
      action: "set_start",
      latitude: previewPlace.latitude,
      longitude: previewPlace.longitude,
    });
    closeSearch();
  });

  els.layerSelect.addEventListener("change", () => {
    const next = tileLayers[els.layerSelect.value];
    if (!next || next === activeLayer) return;
    map.removeLayer(activeLayer);
    activeLayer = next.addTo(map);
  });

  els.btnRecenter.addEventListener("click", () => {
    if (!latestState) return;
    const p = latestState.navigation.position;
    map.setView([p.latitude, p.longitude], map.getZoom());
  });
  els.btnZoomIn.addEventListener("click", () => map.zoomIn());
  els.btnZoomOut.addEventListener("click", () => map.zoomOut());
  els.btnClearTrail.addEventListener("click", () => sendWs({ action: "clear_trail" }));

  // Joystick pointer drag
  let draggingStick = false;
  function updateStickFromPointer(ev) {
    const rect = els.joystickPad.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const radius = rect.width / 2 - 14;
    const dx = (ev.clientX - cx) / radius;
    const dy = (cy - ev.clientY) / radius;
    const mag = Math.hypot(dx, dy);
    const scale = Math.max(1, mag);
    const east = dx / scale;
    const north = dy / scale;
    setKnobVisual(east, north);
    sendWs({ action: "stick", east, north });
  }

  els.joystickPad.addEventListener("pointerdown", (ev) => {
    draggingStick = true;
    els.joystickPad.setPointerCapture(ev.pointerId);
    updateStickFromPointer(ev);
  });
  els.joystickPad.addEventListener("pointermove", (ev) => {
    if (draggingStick) updateStickFromPointer(ev);
  });
  function releaseStick() {
    if (!draggingStick) return;
    draggingStick = false;
    setKnobVisual(0, 0);
    sendWs({ action: "stick", east: 0, north: 0 });
  }
  els.joystickPad.addEventListener("pointerup", releaseStick);
  els.joystickPad.addEventListener("pointercancel", releaseStick);

  // Keyboard arrows + WASD
  const pressedKeys = new Set();
  const keyMap = {
    ArrowUp: "up",
    KeyW: "up",
    ArrowDown: "down",
    KeyS: "down",
    ArrowLeft: "left",
    KeyA: "left",
    ArrowRight: "right",
    KeyD: "right",
  };

  function pushKeyboardVector() {
    if (draggingStick) return;
    let east = 0;
    let north = 0;
    if (pressedKeys.has("right")) east += 1;
    if (pressedKeys.has("left")) east -= 1;
    if (pressedKeys.has("up")) north += 1;
    if (pressedKeys.has("down")) north -= 1;
    const mag = Math.hypot(east, north) || 1;
    const nx = east / mag;
    const ny = north / mag;
    setKnobVisual(nx, ny);
    sendWs({ action: "stick", east: nx, north: ny });
  }

  window.addEventListener("keydown", (ev) => {
    const tag = document.activeElement ? document.activeElement.tagName : "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    const dir = keyMap[ev.code];
    if (!dir) return;
    ev.preventDefault();
    if (!pressedKeys.has(dir)) {
      pressedKeys.add(dir);
      pushKeyboardVector();
    }
  });

  window.addEventListener("keyup", (ev) => {
    const dir = keyMap[ev.code];
    if (!dir || !pressedKeys.has(dir)) return;
    pressedKeys.delete(dir);
    pushKeyboardVector();
  });

  window.addEventListener("blur", () => {
    pressedKeys.clear();
    draggingStick = false;
    setKnobVisual(0, 0);
    sendWs({ action: "stick", east: 0, north: 0 });
  });

  // Speed & motion buttons
  els.btnToggleMotion.addEventListener("click", () => sendWs({ action: "toggle_motion" }));
  els.speedSlider.addEventListener("input", () => {
    const speed = Number(els.speedSlider.value);
    els.speedValue.textContent = `${speed.toFixed(1)} km/h`;
    sendWs({ action: "speed", speed_kph: speed });
  });
  els.presetButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const speed = Number(btn.dataset.speed);
      sendWs({ action: "speed", speed_kph: speed });
    });
  });

  // Device controls
  els.btnInspect.addEventListener("click", () => postDevice("/api/device/inspect"));
  els.btnConnect.addEventListener("click", () => postDevice("/api/device/connect"));
  els.btnStartSync.addEventListener("click", () => postDevice("/api/device/start-sync"));
  els.btnRestore.addEventListener("click", () => postDevice("/api/device/restore"));
  els.btnDisconnect.addEventListener("click", () => postDevice("/api/device/disconnect"));
  els.btnPair.addEventListener("click", () => postDevice("/api/device/pair"));
  els.btnRevealDev.addEventListener("click", () => postDevice("/api/device/reveal-dev-mode"));
  els.btnMountDdi.addEventListener("click", () => postDevice("/api/device/mount-ddi"));

  connectWs();
})();
