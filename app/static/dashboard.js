const elements = {
  form: document.querySelector("#weather-form"),
  location: document.querySelector("#location"),
  locationId: document.querySelector("#location-id"),
  candidates: document.querySelector("#location-candidates"),
  selectedLocation: document.querySelector("#selected-location"),
  startDate: document.querySelector("#start-date"),
  endDate: document.querySelector("#end-date"),
  exploreButton: document.querySelector("#explore-button"),
  status: document.querySelector("#status"),
  emptyState: document.querySelector("#empty-state"),
  recordView: document.querySelector("#record-view"),
  resolvedLocation: document.querySelector("#resolved-location"),
  locationMeta: document.querySelector("#location-meta"),
  dateRangeLabel: document.querySelector("#date-range-label"),
  weatherDays: document.querySelector("#weather-days"),
  plannerTitle: document.querySelector("#planner-title"),
  plannerSummary: document.querySelector("#planner-summary"),
  plannerReasons: document.querySelector("#planner-reasons"),
  plannerScore: document.querySelector("#planner-score"),
  scoreRing: document.querySelector("#score-ring"),
  scoreFactors: document.querySelector("#score-factors"),
  nearbyPlaces: document.querySelector("#nearby-places"),
  savedRecords: document.querySelector("#saved-records"),
  recordCount: document.querySelector("#record-count"),
  refreshRecord: document.querySelector("#refresh-record"),
  deleteRecord: document.querySelector("#delete-record"),
};

let activeRecord = null;
let searchTimer = null;
let searchController = null;

function toIsoDate(date) {
  return date.toISOString().slice(0, 10);
}

function initializeDates() {
  const today = new Date();
  const earliest = new Date(today);
  const latest = new Date(today);
  const defaultEnd = new Date(today);
  earliest.setDate(today.getDate() - 92);
  latest.setDate(today.getDate() + 15);
  defaultEnd.setDate(today.getDate() + 2);
  elements.startDate.min = toIsoDate(earliest);
  elements.startDate.max = toIsoDate(latest);
  elements.endDate.min = toIsoDate(earliest);
  elements.endDate.max = toIsoDate(latest);
  elements.startDate.value = toIsoDate(today);
  elements.endDate.value = toIsoDate(defaultEnd);
}

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>'"]/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[
        character
      ],
  );
}

async function apiRequest(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  if (response.status === 204) return null;
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const message = payload?.error?.message || `Request failed with status ${response.status}.`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function showStatus(message, isError = false) {
  elements.status.textContent = message;
  elements.status.classList.toggle("error", isError);
  elements.status.hidden = false;
}

function clearStatus() {
  elements.status.hidden = true;
  elements.status.textContent = "";
  elements.status.classList.remove("error");
}

function setFormLoading(isLoading) {
  elements.exploreButton.disabled = isLoading;
  elements.exploreButton.querySelector("span:first-child").textContent = isLoading
    ? "Reading the forecast…"
    : "Explore weather";
}

function formatDate(isoDate, options = { weekday: "short", month: "short", day: "numeric" }) {
  return new Intl.DateTimeFormat("en", options).format(new Date(`${isoDate}T12:00:00`));
}

function formatDateRange(startDate, endDate) {
  return `${formatDate(startDate)} — ${formatDate(endDate)}`;
}

function weatherIcon(code) {
  if (code === 0) return "☀";
  if ([1, 2].includes(code)) return "🌤";
  if (code === 3) return "☁";
  if ([45, 48].includes(code)) return "≋";
  if ([51, 53, 55, 56, 57].includes(code)) return "🌦";
  if ([61, 63, 65, 66, 67, 80, 81, 82].includes(code)) return "🌧";
  if ([71, 73, 75, 77, 85, 86].includes(code)) return "❄";
  if ([95, 96, 99].includes(code)) return "⛈";
  return "◌";
}

function numberOrDash(value, suffix = "") {
  return value === null || value === undefined ? "—" : `${Math.round(value)}${suffix}`;
}

async function searchLocations() {
  const query = elements.location.value.trim();
  elements.locationId.value = "";
  elements.selectedLocation.hidden = true;
  elements.candidates.hidden = true;
  if (query.length < 2) return;

  searchController?.abort();
  searchController = new AbortController();
  try {
    const response = await fetch(`/locations/search?query=${encodeURIComponent(query)}`, {
      signal: searchController.signal,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.error?.message || "Location search failed.");
    renderCandidates(payload.candidates);
  } catch (error) {
    if (error.name !== "AbortError") {
      elements.candidates.innerHTML = '<p class="saved-empty">Could not load suggestions.</p>';
      elements.candidates.hidden = false;
    }
  }
}

function renderCandidates(candidates) {
  if (!candidates.length) {
    elements.candidates.innerHTML = '<p class="saved-empty">No matching places found.</p>';
    elements.candidates.hidden = false;
    return;
  }
  elements.candidates.innerHTML = candidates
    .map(
      (candidate, index) => `
        <button class="candidate-option" type="button" role="option" data-index="${index}">
          <strong>${escapeHtml(candidate.canonical_location)}</strong>
          <small>${candidate.latitude.toFixed(3)}, ${candidate.longitude.toFixed(3)} · ${escapeHtml(candidate.timezone)}</small>
          <em>${escapeHtml(candidate.country_code || "")}</em>
        </button>`,
    )
    .join("");
  elements.candidates.hidden = false;
  elements.candidates.querySelectorAll(".candidate-option").forEach((button) => {
    button.addEventListener("click", () => selectCandidate(candidates[Number(button.dataset.index)]));
  });
}

function selectCandidate(candidate) {
  elements.location.value = candidate.name;
  elements.locationId.value = candidate.location_id;
  elements.selectedLocation.textContent = `Selected: ${candidate.canonical_location}`;
  elements.selectedLocation.hidden = false;
  elements.candidates.hidden = true;
  elements.startDate.focus();
}

async function createWeatherRecord(event) {
  event.preventDefault();
  clearStatus();
  if (!elements.form.reportValidity()) return;
  setFormLoading(true);
  const payload = {
    location: elements.location.value.trim(),
    start_date: elements.startDate.value,
    end_date: elements.endDate.value,
  };
  if (elements.locationId.value) payload.location_id = Number(elements.locationId.value);
  try {
    const record = await apiRequest("/weather", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showStatus(`${record.canonical_location} is ready — forecast saved as record #${record.id}.`);
    await showRecord(record);
    await loadSavedRecords();
    elements.recordView.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    setFormLoading(false);
  }
}

async function showRecord(record) {
  activeRecord = record;
  elements.emptyState.hidden = true;
  elements.recordView.hidden = false;
  elements.resolvedLocation.textContent = record.canonical_location;
  elements.locationMeta.innerHTML = [
    record.country_code ? `Country · ${escapeHtml(record.country_code)}` : null,
    `Timezone · ${escapeHtml(record.timezone)}`,
    `${record.latitude.toFixed(3)}, ${record.longitude.toFixed(3)}`,
    `Match · ${escapeHtml(record.location_match)}`,
  ]
    .filter(Boolean)
    .map((item) => `<span class="meta-chip">${item}</span>`)
    .join("");
  elements.dateRangeLabel.textContent = formatDateRange(record.start_date, record.end_date);
  renderWeatherDays(record.days);
  resetPlanner();
  highlightActiveRecord();
  await loadOutingPlan(record.id);
}

function renderWeatherDays(days, bestDate = null) {
  elements.weatherDays.innerHTML = days
    .map(
      (day) => `
      <article class="weather-card ${day.weather_date === bestDate ? "best-day" : ""}">
        ${day.weather_date === bestDate ? '<span class="best-label">Best outing</span>' : ""}
        <p class="weather-date">${escapeHtml(formatDate(day.weather_date, { weekday: "long", month: "short", day: "numeric" }))}</p>
        <span class="weather-icon" aria-hidden="true">${weatherIcon(day.weather_code)}</span>
        <p class="temperature">${numberOrDash(day.temperature_mean_c, "°")} <small>${numberOrDash(day.temperature_min_c, "°")} / ${numberOrDash(day.temperature_max_c, "°")}</small></p>
        <p class="condition">${escapeHtml(day.weather_description)}</p>
        <div class="weather-metrics">
          <div class="weather-metric"><span>Feels like</span><strong>${numberOrDash(day.apparent_temperature_mean_c, "°C")}</strong></div>
          <div class="weather-metric"><span>Rain</span><strong>${numberOrDash(day.precipitation_sum_mm, " mm")} · ${numberOrDash(day.precipitation_probability_max_pct, "%")}</strong></div>
          <div class="weather-metric"><span>Humidity</span><strong>${numberOrDash(day.humidity_mean_pct, "%")}</strong></div>
          <div class="weather-metric"><span>Wind</span><strong>${numberOrDash(day.wind_speed_max_kmh, " km/h")}</strong></div>
        </div>
      </article>`,
    )
    .join("");
}

function resetPlanner() {
  elements.plannerTitle.textContent = "Finding your best day…";
  elements.plannerSummary.textContent = "Weighing rain, conditions, comfort, and wind.";
  elements.plannerReasons.innerHTML = "";
  elements.plannerScore.textContent = "—";
  elements.scoreRing.style.setProperty("--score", 0);
  elements.scoreFactors.innerHTML = "";
  elements.nearbyPlaces.innerHTML = '<p class="saved-empty">Looking for nearby places…</p>';
}

async function loadOutingPlan(recordId) {
  try {
    const plan = await apiRequest(`/weather/${recordId}/outing-plan?radius_m=10000&limit=6`);
    renderOutingPlan(plan);
  } catch (error) {
    elements.plannerTitle.textContent = "Plan unavailable";
    elements.plannerSummary.textContent = error.message;
    elements.nearbyPlaces.innerHTML = '<p class="saved-empty">Nearby places could not be loaded.</p>';
  }
}

function renderOutingPlan(plan) {
  const best = plan.best_day;
  elements.plannerTitle.textContent = formatDate(best.weather_date, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
  elements.plannerSummary.textContent = plan.summary;
  elements.plannerScore.textContent = best.score;
  elements.scoreRing.style.setProperty("--score", best.score);
  elements.plannerReasons.innerHTML = best.reasons
    .slice(0, 4)
    .map((reason) => `<span class="reason-pill">${escapeHtml(reason)}</span>`)
    .join("");
  const factorLabels = {
    precipitation: "Rain",
    weather_condition: "Conditions",
    temperature_comfort: "Comfort",
    wind: "Wind",
    missing_data: "Data gaps",
  };
  elements.scoreFactors.innerHTML = Object.entries(best.penalties)
    .map(
      ([key, value]) => `
        <div class="factor">
          <span>${factorLabels[key]}</span>
          <strong>${value ? `−${value} pts` : "No penalty"}</strong>
        </div>`,
    )
    .join("");
  renderWeatherDays(activeRecord.days, best.weather_date);
  renderNearbyPlaces(plan.nearby_places);
}

function renderNearbyPlaces(places) {
  if (!places.length) {
    elements.nearbyPlaces.innerHTML = '<p class="saved-empty">No geotagged articles were found nearby.</p>';
    return;
  }
  elements.nearbyPlaces.innerHTML = places
    .map(
      (place, index) => `
        <a class="place-card" href="${escapeHtml(place.article_url)}" target="_blank" rel="noreferrer">
          <span class="place-number">${String(index + 1).padStart(2, "0")}</span>
          <span><strong>${escapeHtml(place.title)}</strong><small>${Math.round(place.distance_m).toLocaleString()} m away</small></span>
          <span class="place-arrow" aria-hidden="true">↗</span>
        </a>`,
    )
    .join("");
}

async function loadSavedRecords() {
  try {
    const payload = await apiRequest("/weather?limit=100");
    elements.recordCount.textContent = payload.total;
    if (!payload.items.length) {
      elements.savedRecords.innerHTML = '<p class="saved-empty">Your saved forecasts will appear here.</p>';
      return;
    }
    elements.savedRecords.innerHTML = payload.items
      .map(
        (record) => `
          <button class="saved-card ${activeRecord?.id === record.id ? "active" : ""}" type="button" data-record-id="${record.id}">
            <strong>${escapeHtml(record.canonical_location)}</strong>
            <span>${escapeHtml(formatDateRange(record.start_date, record.end_date))}</span>
            <small>#${record.id} · ${record.days.length} day${record.days.length === 1 ? "" : "s"} · ${escapeHtml(record.location_match)} match</small>
          </button>`,
      )
      .join("");
    elements.savedRecords.querySelectorAll(".saved-card").forEach((button) => {
      button.addEventListener("click", () => inspectRecord(Number(button.dataset.recordId)));
    });
  } catch (error) {
    elements.savedRecords.innerHTML = `<p class="saved-empty">${escapeHtml(error.message)}</p>`;
  }
}

function highlightActiveRecord() {
  elements.savedRecords.querySelectorAll(".saved-card").forEach((card) => {
    card.classList.toggle("active", Number(card.dataset.recordId) === activeRecord?.id);
  });
}

async function inspectRecord(recordId) {
  clearStatus();
  try {
    const record = await apiRequest(`/weather/${recordId}`);
    await showRecord(record);
    elements.recordView.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showStatus(error.message, true);
  }
}

async function refreshActiveRecord() {
  if (!activeRecord) return;
  elements.refreshRecord.disabled = true;
  clearStatus();
  try {
    const record = await apiRequest(`/weather/${activeRecord.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        start_date: activeRecord.start_date,
        end_date: activeRecord.end_date,
      }),
    });
    showStatus(`Record #${record.id} was refreshed with the latest provider data.`);
    await showRecord(record);
    await loadSavedRecords();
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    elements.refreshRecord.disabled = false;
  }
}

async function deleteActiveRecord() {
  if (!activeRecord) return;
  const recordId = activeRecord.id;
  if (!window.confirm(`Delete saved forecast #${recordId}?`)) return;
  elements.deleteRecord.disabled = true;
  clearStatus();
  try {
    await apiRequest(`/weather/${recordId}`, { method: "DELETE" });
    activeRecord = null;
    elements.recordView.hidden = true;
    elements.emptyState.hidden = false;
    showStatus(`Record #${recordId} was deleted.`);
    await loadSavedRecords();
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    elements.deleteRecord.disabled = false;
  }
}

elements.location.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(searchLocations, 280);
});
elements.form.addEventListener("submit", createWeatherRecord);
elements.refreshRecord.addEventListener("click", refreshActiveRecord);
elements.deleteRecord.addEventListener("click", deleteActiveRecord);
document.addEventListener("click", (event) => {
  if (!event.target.closest(".location-field")) elements.candidates.hidden = true;
});

initializeDates();
loadSavedRecords();
