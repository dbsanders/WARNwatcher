const statusEl = document.getElementById("status");
const apiBase = localStorage.getItem("warnwatcher_api_base") || "https://api.warnwatcher.com";
const verificationToken = new URLSearchParams(window.location.search).get("token") || "";

async function verifyEmail() {
  if (!verificationToken) {
    statusEl.textContent = "This verification link is missing its token.";
    return;
  }

  try {
    const res = await fetch(`${apiBase}/verify-email`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: verificationToken }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      statusEl.textContent = body.message || "This verification link is invalid or expired.";
      return;
    }

    localStorage.setItem("warnwatcher_auth_token", String(body.access_token || ""));
    localStorage.setItem("warnwatcher_auth_email", String(body.email || ""));
    statusEl.textContent = "Email verified. Signing you in...";
    window.setTimeout(() => {
      window.location.href = "./index.html";
    }, 500);
  } catch (_err) {
    statusEl.textContent = "Network error. Try opening the link again.";
  }
}

verifyEmail();
