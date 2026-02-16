const form = document.getElementById("subscribe-form");
const statusEl = document.getElementById("status");

// Override with localStorage value for development if needed.
const apiBase = localStorage.getItem("warnwatcher_api_base") || "https://api.warnwatcher.com";

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  statusEl.textContent = "Submitting...";

  const formData = new FormData(form);
  const payload = {
    email: String(formData.get("email") || "").trim(),
    company: String(formData.get("company") || "").trim(),
    state: String(formData.get("state") || "CA").trim().toUpperCase(),
    min_employees: Number(formData.get("min_employees") || 0),
  };

  try {
    const res = await fetch(`${apiBase}/subscribe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (!res.ok) {
      statusEl.textContent = `Error: ${body.message || "request failed"}`;
      return;
    }
    statusEl.textContent = "Subscription created.";
    form.reset();
  } catch (err) {
    statusEl.textContent = "Network error. Try again.";
  }
});
