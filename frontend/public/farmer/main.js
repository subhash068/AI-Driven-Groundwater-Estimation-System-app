const API_BASE = (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") ? "http://localhost:8000" : "";

const resources = {
  en: {
    translation: {
      title: "Farmer Water Advisory",
      locate: "Locate My Village",
      villageUnknown: "Village not identified yet",
      villageFound: "✅ Village Identified!",
      safe: "Safe",
      warning: "Warning",
      critical: "Critical",
      cropTitle: "Crop Recommendation",
      cropPaddy: "Water is stable: Paddy is suitable this cycle.",
      cropMillet: "Water stress likely: Choose millets or low-water crops."
    }
  },
  te: {
    translation: {
      title: "రైతు నీటి సూచన",
      locate: "నా గ్రామాన్ని గుర్తించండి",
      villageUnknown: "ఇంకా గ్రామం గుర్తించబడలేదు",
      villageFound: "✅ గ్రామం గుర్తించబడింది!",
      safe: "సురక్షితం",
      warning: "హెచ్చరిక",
      critical: "అత్యంత అపాయం",
      cropTitle: "పంట సూచన",
      cropPaddy: "నీటి స్థాయి బాగుంది: ఈ సీజన్‌లో వరి వేయవచ్చు.",
      cropMillet: "నీటి ఒత్తిడి ఉండే అవకాశం ఉంది: సజ్జలు వంటి తక్కువ నీటి పంటలు వేయండి."
    }
  }
};

const el = {
  lang: document.getElementById("langSelect"),
  locate: document.getElementById("locateBtn"),
  village: document.getElementById("villageLabel"),
  icon: document.getElementById("tankIcon"),
  status: document.getElementById("statusText"),
  depth: document.getElementById("depthText"),
  crop: document.getElementById("cropText")
};

function applyTranslations() {
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = i18next.t(node.getAttribute("data-i18n"));
  });
}

function levelFromDepth(depth) {
  if (depth >= 30) return "critical";
  if (depth >= 20) return "warning";
  return "safe";
}

function renderAdvisory(depth, villageName, mandalName) {
  const level = levelFromDepth(depth);
  
  // Clean up location string: Remove "Unknown" or empty mandals
  const locationText = (mandalName && mandalName.toLowerCase() !== "unknown") 
    ? `${villageName}, ${mandalName}` 
    : villageName;

  el.village.textContent = `${i18next.t("villageFound")} ${locationText}`;
  el.status.textContent = i18next.t(level).toUpperCase();
  el.depth.textContent = `${depth.toFixed(2)} m`;
  el.icon.src = `./tank-${level}.svg`;
  el.icon.style.opacity = "1";
  
  // Set theme color based on risk
  const themeColor = level === 'critical' ? '#ef4444' : level === 'warning' ? '#facc15' : '#22c55e';
  el.status.style.color = themeColor;
  
  el.crop.textContent = level === "safe" ? i18next.t("cropPaddy") : i18next.t("cropMillet");
}

async function locateVillage() {
  if (!navigator.geolocation) {
    alert("Geolocation is not supported by your browser");
    return;
  }
  
  const originalText = el.locate.querySelector('span:last-child').textContent;
  el.locate.querySelector('span:last-child').textContent = i18next.t("locate") === "Locate My Village" ? "Searching..." : "గుర్తిస్తోంది...";
  el.locate.disabled = true;
  el.village.textContent = "...";

  navigator.geolocation.getCurrentPosition(
    async (position) => {
      try {
        const lat = position.coords.latitude;
        const lon = position.coords.longitude;
        
        el.village.textContent = `📍 Locating near ${lat.toFixed(3)}, ${lon.toFixed(3)}...`;

        const resNearest = await fetch(`${API_BASE}/village/locate?lat=${lat}&lon=${lon}`);
        if (!resNearest.ok) throw new Error("Location outside service area");
        
        const nearest = await resNearest.json();
        const resStatus = await fetch(`${API_BASE}/get-village-status/${nearest.village_id}`);
        const status = await resStatus.json();
        
        renderAdvisory(Number(status.current_depth || 0), nearest.village_name, nearest.mandal);
      } catch (err) {
        console.error(err);
        el.village.textContent = "Location identified, but village details are being updated.";
      } finally {
        el.locate.querySelector('span:last-child').textContent = i18next.t("locate");
        el.locate.disabled = false;
      }
    },
    (error) => {
      console.error(error);
      el.village.textContent = i18next.t("villageUnknown");
      el.locate.textContent = originalText;
      el.locate.disabled = false;
      alert("Unable to retrieve your location. Please check GPS settings.");
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
  );
}

i18next.init(
  {
    lng: "en",
    resources
  },
  () => {
    applyTranslations();
  }
);

el.lang.addEventListener("change", () => {
  i18next.changeLanguage(el.lang.value, applyTranslations);
});
el.locate.addEventListener("click", locateVillage);
