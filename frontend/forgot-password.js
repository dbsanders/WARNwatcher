const form = document.getElementById("forgot-password-form");
const statusEl = document.getElementById("status");

const apiBase = localStorage.getItem("warnwatcher_api_base") || "https://api.warnwatcher.com";

async function parseJson(res) {
  try {
    return await res.json();
  } catch (_err) {
    return {};
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  statusEl.textContent = "Sending reset link...";

  const formData = new FormData(form);
  const payload = {
    email: String(formData.get("email") || "").trim().toLowerCase(),
  };

  try {
    const res = await fetch(`${apiBase}/forgot-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await parseJson(res);
    if (!res.ok) {
      statusEl.textContent = `Request failed: ${body.message || "request failed"}`;
      return;
    }
    statusEl.textContent = "If that account exists, a reset link has been sent.";
  } catch (_err) {
    statusEl.textContent = "Network error. Try again.";
  }
});
