const form = document.getElementById("subscribe-form");
const statusEl = document.getElementById("status");
const authSummaryEl = document.getElementById("auth-summary");
const logoutBtn = document.getElementById("logout");

// Override with localStorage value for development if needed.
const apiBase = localStorage.getItem("warnwatcher_api_base") || "https://api.warnwatcher.com";
const authToken = localStorage.getItem("warnwatcher_auth_token") || "";
const authEmail = localStorage.getItem("warnwatcher_auth_email") || "";

if (!authToken) {
  window.location.href = "./signup.html";
}

authSummaryEl.textContent = authEmail ? `Signed in as ${authEmail}` : "Signed in";

logoutBtn.addEventListener("click", () => {
  localStorage.removeItem("warnwatcher_auth_token");
  localStorage.removeItem("warnwatcher_auth_email");
  window.location.href = "./signup.html";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  statusEl.textContent = "Submitting...";

  const formData = new FormData(form);
  const payload = {
    company: String(formData.get("company") || "").trim(),
    state: String(formData.get("state") || "CA").trim().toUpperCase(),
    min_employees: Number(formData.get("min_employees") || 0),
  };

  try {
    const res = await fetch(`${apiBase}/subscribe`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${authToken}`,
      },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (!res.ok) {
      if (res.status === 401) {
        localStorage.removeItem("warnwatcher_auth_token");
        localStorage.removeItem("warnwatcher_auth_email");
        statusEl.textContent = "Session expired. Redirecting to sign in...";
        setTimeout(() => {
          window.location.href = "./signup.html";
        }, 800);
        return;
      }
      statusEl.textContent = `Error: ${body.message || "request failed"}`;
      return;
    }
    const existingMatchCount = Number(body.existing_match_count || 0);
    const immediateEmailSent = Boolean(body.immediate_email_sent);
    const immediateEmailError = String(body.immediate_email_error || "");
    if (existingMatchCount > 0) {
      if (immediateEmailSent) {
        statusEl.textContent = `Subscription created. Found ${existingMatchCount} existing matching notice(s), and sent an email alert.`;
      } else if (immediateEmailError) {
        statusEl.textContent = `Subscription created. Found ${existingMatchCount} existing matching notice(s), but email failed (${immediateEmailError}).`;
      } else {
        statusEl.textContent = `Subscription created. Found ${existingMatchCount} existing matching notice(s).`;
      }
    } else {
      statusEl.textContent = "Subscription created. No existing matches found.";
    }
    form.reset();
  } catch (err) {
    statusEl.textContent = "Network error. Try again.";
  }
});
