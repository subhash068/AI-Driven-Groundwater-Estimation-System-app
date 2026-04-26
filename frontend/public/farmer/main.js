const API_BASE = window.location.hostname === "localhost" ? "http://localhost:8000" : "";

const resources = {
  en: {
    translation: {
      title: "Farmer Water Advisory",
      locate: "Locate My Village",
      villageUnknown: "Village not identified yet",
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

function renderAdvisory(depth, villageName) {
  const level = levelFromDepth(depth);
  el.village.textContent = villageName || i18next.t("villageUnknown");
  el.status.textContent = i18next.t(level);
  el.depth.textContent = `${depth.toFixed(2)} m`;
  el.icon.src = `./tank-${level}.svg`;
  el.crop.textContent = level === "safe" ? i18next.t("cropPaddy") : i18next.t("cropMillet");
}

async function locateVillage() {
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition(
    async (position) => {
      const lat = position.coords.latitude;
      const lon = position.coords.longitude;

      const nearest = await fetch(`${API_BASE}/village/locate?lat=${lat}&lon=${lon}`).then((r) => r.json());
      const status = await fetch(`${API_BASE}/get-village-status/${nearest.village_id}`).then((r) => r.json());
      renderAdvisory(Number(status.current_depth || 0), `${nearest.village_name}, ${nearest.mandal}`);
    },
    () => {
      el.village.textContent = i18next.t("villageUnknown");
    },
    { enableHighAccuracy: false, timeout: 15000, maximumAge: 300000 }
  );
}

i18next.init(
  {
    lng: "en",
    resources
  },
  () => {
    applyTranslations();
    el.crop.textContent = i18next.t("cropMillet");
  }
);

el.lang.addEventListener("change", () => {
  i18next.changeLanguage(el.lang.value, applyTranslations);
});
el.locate.addEventListener("click", locateVillage);
