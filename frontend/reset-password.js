const form = document.getElementById("reset-password-form");
const statusEl = document.getElementById("status");

const apiBase = localStorage.getItem("warnwatcher_api_base") || "https://api.warnwatcher.com";
const params = new URLSearchParams(window.location.search);
const token = params.get("token") || "";

if (!token) {
  statusEl.textContent = "Reset token is missing.";
  form.querySelector("button").disabled = true;
}

async function parseJson(res) {
  try {
    return await res.json();
  } catch (_err) {
    return {};
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const formData = new FormData(form);
  const password = String(formData.get("password") || "");
  const confirmPassword = String(formData.get("confirm_password") || "");
  if (password !== confirmPassword) {
    statusEl.textContent = "Passwords do not match.";
    return;
  }

  statusEl.textContent = "Resetting password...";
  try {
    const res = await fetch(`${apiBase}/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, password }),
    });
    const body = await parseJson(res);
    if (!res.ok) {
      statusEl.textContent = `Reset failed: ${body.message || "request failed"}`;
      return;
    }
    statusEl.textContent = "Password reset successful. Redirecting to sign in...";
    setTimeout(() => {
      window.location.href = "./signup.html";
    }, 1200);
  } catch (_err) {
    statusEl.textContent = "Network error. Try again.";
  }
});
