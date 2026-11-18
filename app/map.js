/* Local interactive map: the configured OSM boundary and evidence returned by the local app only. */
(() => {
  const byId = id => document.getElementById(id);
  const svg = byId("regionMap"), ns = "http://www.w3.org/2000/svg";
  const dimensions = { width: 840, height: 620, pad: 42 };
  let boundaryData = null, center = null, view = "map", dragStart = null, ignoreClick = false, areaRect = null;

  const svgNode = (name, attrs = {}) => {
    const node = document.createElementNS(ns, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    return node;
  };

  function project(lon, lat) {
    const b = boundaryData.bbox_wgs84;
    return {
      x: dimensions.pad + (lon - b.west) / (b.east - b.west) * (dimensions.width - 2 * dimensions.pad),
      y: dimensions.pad + (b.north - lat) / (b.north - b.south) * (dimensions.height - 2 * dimensions.pad),
    };
  }

  function renderBoundary() {
    const layer = byId("boundaryLayer");
    layer.replaceChildren();
    const geometry = boundaryData.geometry;
    const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
    for (const polygon of polygons) {
      let pathData = "";
      for (const ring of polygon) {
        ring.forEach(([lon, lat], index) => {
          const point = project(lon, lat);
          pathData += `${index ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)} `;
        });
        pathData += "Z ";
      }
      const path = svgNode("path", { d: pathData, class: "boundary-shape" });
      const title = svgNode("title");
      title.textContent = `${boundaryData.name}. ${boundaryData.source}; ${boundaryData.source_version}. ${boundaryData.source_license}.`;
      path.append(title);
      layer.append(path);
    }
    const label = svgNode("text", { x: 420, y: 310, class: "map-label" });
    label.textContent = "JHARKHAND";
    layer.append(label);
    byId("stageStatus").textContent = "Local Jharkhand boundary loaded";
    updateSelection();
  }

  function pointInRing(lon, lat, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  function contains(lon, lat) {
    if (!boundaryData) return false;
    const geometry = boundaryData.geometry;
    const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
    return polygons.some(polygon => pointInRing(lon, lat, polygon[0]) &&
      !polygon.slice(1).some(hole => pointInRing(lon, lat, hole)));
  }

  function updateSelection() {
    if (!center || !boundaryData) {
      byId("selectionPoint").setAttribute("visibility", "hidden");
      byId("selectionRing").setAttribute("visibility", "hidden");
      byId("dragSelection").setAttribute("visibility", "hidden");
      byId("searchMap").disabled = true;
      return;
    }
    const point = project(center.lon, center.lat), radius = Number(byId("radius").value), b = boundaryData.bbox_wgs84;
    const rx = radius / (111320 * Math.cos(center.lat * Math.PI / 180)) *
      (dimensions.width - 2 * dimensions.pad) / (b.east - b.west);
    const ry = radius / 111320 * (dimensions.height - 2 * dimensions.pad) / (b.north - b.south);
    const marker = byId("selectionPoint"), ring = byId("selectionRing");
    marker.setAttribute("cx", point.x); marker.setAttribute("cy", point.y); marker.setAttribute("visibility", "visible");
    ring.setAttribute("cx", point.x); ring.setAttribute("cy", point.y); ring.setAttribute("rx", rx); ring.setAttribute("ry", ry);
    ring.setAttribute("visibility", "visible");
    if (areaRect) {
      const a = project(areaRect.west, areaRect.north), b = project(areaRect.east, areaRect.south), box = byId("dragSelection");
      box.setAttribute("x", a.x); box.setAttribute("y", a.y); box.setAttribute("width", b.x - a.x); box.setAttribute("height", b.y - a.y);
      box.setAttribute("visibility", "visible");
    } else byId("dragSelection").setAttribute("visibility", "hidden");
    byId("searchMap").disabled = false;
  }

  function chooseCenter(lon, lat) {
    if (!contains(lon, lat)) {
      byId("mapTooltip").textContent = "That point is outside the configured Jharkhand boundary.";
      return;
    }
    const radiusSelect = byId("radius"), previousBoxRadius = radiusSelect.querySelector("option[data-map-radius]");
    if (previousBoxRadius) {
      if (radiusSelect.value === previousBoxRadius.value) radiusSelect.value = "1000";
      previousBoxRadius.remove();
    }
    center = { lon, lat };
    areaRect = null;
    byId("longitude").value = lon.toFixed(5); byId("latitude").value = lat.toFixed(5);
    byId("statCoords").textContent = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
    byId("statArea").textContent = "Selected in Jharkhand";
    byId("stageStatus").textContent = "Search area selected";
    byId("mapTooltip").textContent = `Selected center ${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E · radius ${byId("radius").value} m`;
    updateSelection();
  }

  function pointerCoordinates(event) {
    const point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
    const local = point.matrixTransform(svg.getScreenCTM().inverse()), b = boundaryData.bbox_wgs84;
    return {
      lon: b.west + (local.x - dimensions.pad) / (dimensions.width - 2 * dimensions.pad) * (b.east - b.west),
      lat: b.north - (local.y - dimensions.pad) / (dimensions.height - 2 * dimensions.pad) * (b.north - b.south),
    };
  }

  function setView(next) {
    view = next;
    const imageVisible = next === "image" && Boolean(document.getElementById("file").files.length);
    byId("regionMap").style.display = next === "map" ? "block" : "none";
    byId("preview").style.display = imageVisible ? "flex" : "none";
    byId("mapTooltip").style.display = next === "map" ? "block" : "none";
    byId("mapViewBtn").classList.toggle("active", next === "map");
    byId("imageViewBtn").classList.toggle("active", next === "image");
  }

  function drawEvidence(analysis) {
    const layer = byId("evidenceLayer"); layer.replaceChildren();
    for (const row of analysis?.firms?.records || []) {
      const lon = Number(row.longitude), lat = Number(row.latitude);
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
      const point = project(lon, lat), mark = svgNode("circle", {
        cx: point.x, cy: point.y, r: 4 + Math.min(4, Number(row.frp || 0) / 10), class: "map-marker-firms",
      });
      const title = svgNode("title");
      title.textContent = `FIRMS thermal anomaly · ${row.acq_date || "date unknown"} · ${row.satellite || "sensor unknown"} · FRP ${row.thermal_frp_mw ?? row.frp ?? "unknown"} MW`;
      mark.append(title); mark.addEventListener("pointerenter", () => { byId("mapTooltip").textContent = title.textContent; });
      mark.addEventListener("click", event => { event.stopPropagation(); chooseCenter(lon, lat); });
      layer.append(mark);
    }
    for (const row of analysis?.osm?.features || []) {
      const lon = Number(row.longitude), lat = Number(row.latitude);
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
      const point = project(lon, lat), mark = svgNode("rect", {
        x: point.x - 4, y: point.y - 4, width: 8, height: 8, rx: 1, class: "map-marker-osm",
      });
      const title = svgNode("title"); title.textContent = `OSM mapped context · ${row.label} · ${Number(row.distance_m).toFixed(0)} m`;
      mark.append(title); mark.addEventListener("pointerenter", () => { byId("mapTooltip").textContent = title.textContent; });
      mark.addEventListener("click", event => { event.stopPropagation(); chooseCenter(lon, lat); });
      layer.append(mark);
    }
  }

  async function searchArea() {
    if (!center) return;
    byId("error").style.display = "none"; byId("searchMap").disabled = true; byId("spinner").style.display = "block";
    try {
      const response = await fetch("/api/area-evidence", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ longitude: center.lon, latitude: center.lat, radius_m: Number(byId("radius").value),
          lookback_days: Number(byId("lookback").value), acquisition_date: byId("date").value || null }),
      });
      const data = await response.json(); if (!response.ok) throw new Error(data.error || "Map evidence search failed.");
      window.render({ map_selection: true, analysis: data.analysis });
    } catch (error) {
      byId("error").textContent = error.message || "Map evidence search failed."; byId("error").style.display = "block";
    } finally { byId("searchMap").disabled = false; byId("spinner").style.display = "none"; }
  }

  svg.addEventListener("pointermove", event => {
    if (!boundaryData || view !== "map") return;
    const position = pointerCoordinates(event), inside = contains(position.lon, position.lat);
    if (dragStart) {
      const a = project(dragStart.lon, dragStart.lat), b = project(position.lon, position.lat), box = byId("dragSelection");
      box.setAttribute("x", Math.min(a.x, b.x)); box.setAttribute("y", Math.min(a.y, b.y));
      box.setAttribute("width", Math.abs(a.x - b.x)); box.setAttribute("height", Math.abs(a.y - b.y));
      box.setAttribute("visibility", "visible");
      byId("mapTooltip").textContent = `Selecting area · release to search within a covering distance radius · ${inside ? "inside" : "outside"} boundary`;
      return;
    }
    byId("mapTooltip").textContent = `${inside ? "Jharkhand" : "Outside study boundary"} · ${position.lat.toFixed(4)}°N, ${position.lon.toFixed(4)}°E · click inside to select`;
  });
  svg.addEventListener("pointerleave", () => { byId("mapTooltip").textContent = "Hover for coordinates; click inside Jharkhand to choose a search center."; });
  svg.addEventListener("pointerdown", event => {
    if (!boundaryData || view !== "map" || event.target.closest(".map-marker-firms,.map-marker-osm")) return;
    const position = pointerCoordinates(event);
    if (!contains(position.lon, position.lat)) return;
    dragStart = position; svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener("pointerup", event => {
    if (!dragStart) return;
    const end = pointerCoordinates(event), start = dragStart; dragStart = null; ignoreClick = true;
    if (Math.hypot(end.lon - start.lon, end.lat - start.lat) < 0.015) {
      byId("dragSelection").setAttribute("visibility", "hidden");
      chooseCenter(start.lon, start.lat);
      return;
    }
    const box = { west: Math.min(start.lon, end.lon), east: Math.max(start.lon, end.lon),
      south: Math.min(start.lat, end.lat), north: Math.max(start.lat, end.lat) };
    const centerLon = (box.west + box.east) / 2, centerLat = (box.south + box.north) / 2;
    const corners = [[box.west, box.south], [box.west, box.north], [box.east, box.south], [box.east, box.north]];
    if (!corners.every(([lon, lat]) => contains(lon, lat)) || !contains(centerLon, centerLat)) {
      byId("dragSelection").setAttribute("visibility", "hidden");
      byId("mapTooltip").textContent = "Keep the selected rectangle fully inside the configured Jharkhand boundary.";
      return;
    }
    const radiusTo = ([lon, lat]) => {
      const rad = Math.PI / 180, dLat = (lat - centerLat) * rad, dLon = (lon - centerLon) * rad;
      const h = Math.sin(dLat / 2) ** 2 + Math.cos(centerLat * rad) * Math.cos(lat * rad) * Math.sin(dLon / 2) ** 2;
      return 6371008.8 * 2 * Math.asin(Math.sqrt(h));
    };
    const coveringRadius = Math.max(100, Math.ceil(Math.max(...corners.map(radiusTo)) / 100) * 100);
    if (coveringRadius > 10_000) {
      byId("dragSelection").setAttribute("visibility", "hidden");
      byId("mapTooltip").textContent = "That rectangle exceeds the 10 km search-radius limit. Select a smaller area.";
      return;
    }
    chooseCenter(centerLon, centerLat);
    const select = byId("radius");
    const option = document.createElement("option"); option.value = String(coveringRadius);
    option.textContent = `${(coveringRadius / 1000).toFixed(1)} km · covers selected box`; option.dataset.mapRadius = "true";
    select.add(option); select.value = option.value;
    areaRect = box; updateSelection();
    byId("mapTooltip").textContent = `Selected rectangle · evidence search uses a ${coveringRadius.toLocaleString()} m circle around its center.`;
  });
  svg.addEventListener("click", event => {
    if (ignoreClick) { ignoreClick = false; return; }
    if (!boundaryData || event.target.closest(".map-marker-firms,.map-marker-osm")) return;
    const position = pointerCoordinates(event); chooseCenter(position.lon, position.lat);
  });
  byId("mapViewBtn").addEventListener("click", () => setView("map"));
  byId("imageViewBtn").addEventListener("click", () => setView("image"));
  byId("searchMap").addEventListener("click", searchArea);
  byId("radius").addEventListener("change", updateSelection);

  // Keep the existing upload result renderer; add real evidence markers to its map view.
  const previousRender = window.render;
  if (typeof previousRender === "function") {
    window.render = function (data) {
      const renderData = data.map_selection ? {
        ...data,
        image: { width: null, height: null, bands: null, longitude: center?.lon ?? null, latitude: center?.lat ?? null,
          acquisition_date: byId("date").value || null, crs: null,
          preview_data_url: "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=" },
        smoke: { status: "map_only", message: "No image was uploaded; smoke inference was not run." },
      } : data;
      previousRender(renderData);
      if (data.map_selection) {
        const root = byId("results"), preview = root.querySelector(":scope > img.smallimg");
        if (preview) preview.remove();
        const modelHeading = [...root.querySelectorAll(".section-title")].find(node => node.textContent.includes("Visible-smoke"));
        if (modelHeading) { const modelResult = modelHeading.nextElementSibling; modelHeading.remove(); modelResult?.remove(); }
        const note = document.createElement("p"); note.className = "help";
        note.textContent = "Map-only search: no image was uploaded, so no computer-vision inference was run.";
        root.insertBefore(note, root.querySelector(".section-title"));
        byId("statModel").textContent = "Not run · map search";
      }
      drawEvidence(data.analysis);
      setView(view);
    };
  }

  document.getElementById("file").addEventListener("change", () => {
    byId("imageViewBtn").disabled = !document.getElementById("file").files.length;
    setTimeout(() => setView(view), 100);
  });

  fetch("/api/map-boundary").then(response => response.json().then(data => ({ response, data }))).then(({ response, data }) => {
    if (!response.ok) throw new Error(data.error || "Local boundary unavailable.");
    boundaryData = data; renderBoundary();
    byId("mapTooltip").textContent = `${data.name} · ${data.source} · click inside to set a search center.`;
  }).catch(error => {
    byId("stageStatus").textContent = "Boundary unavailable";
    byId("mapTooltip").textContent = error.message;
  });
})();
