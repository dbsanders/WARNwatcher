const signupForm = document.getElementById("signup-form");
const loginForm = document.getElementById("login-form");
const statusEl = document.getElementById("status");
const loginTab = document.getElementById("login-tab");
const signupTab = document.getElementById("signup-tab");
const loginPanel = document.getElementById("login-panel");
const signupPanel = document.getElementById("signup-panel");

// Override with localStorage value for development if needed.
const apiBase = localStorage.getItem("warnwatcher_api_base") || "https://api.warnwatcher.com";

const existingToken = localStorage.getItem("warnwatcher_auth_token");
if (existingToken) {
  window.location.href = "./index.html";
}

function selectAuthPanel(panelName) {
  const showLogin = panelName === "login";
  loginTab.setAttribute("aria-selected", String(showLogin));
  signupTab.setAttribute("aria-selected", String(!showLogin));
  loginPanel.hidden = !showLogin;
  signupPanel.hidden = showLogin;
  statusEl.textContent = "";
}

loginTab.addEventListener("click", () => selectAuthPanel("login"));
signupTab.addEventListener("click", () => selectAuthPanel("signup"));

async function parseJson(res) {
  try {
    return await res.json();
  } catch (_err) {
    return {};
  }
}

signupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  statusEl.textContent = "Creating account...";

  const formData = new FormData(signupForm);
  const payload = {
    email: String(formData.get("email") || "").trim().toLowerCase(),
    password: String(formData.get("password") || ""),
  };

  try {
    const res = await fetch(`${apiBase}/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await parseJson(res);
    if (!res.ok) {
      statusEl.textContent = `Signup failed: ${body.message || "request failed"}`;
      return;
    }
    selectAuthPanel("login");
    statusEl.textContent = "Account created. Sign in to continue.";
    loginForm.elements.email.value = payload.email;
    loginForm.elements.password.focus();
  } catch (_err) {
    statusEl.textContent = "Network error. Try again.";
  }
});

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  statusEl.textContent = "Signing in...";

  const formData = new FormData(loginForm);
  const payload = {
    email: String(formData.get("email") || "").trim().toLowerCase(),
    password: String(formData.get("password") || ""),
  };

  try {
    const res = await fetch(`${apiBase}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await parseJson(res);
    if (!res.ok) {
      statusEl.textContent = `Sign in failed: ${body.message || "request failed"}`;
      return;
    }

    localStorage.setItem("warnwatcher_auth_token", String(body.access_token || ""));
    localStorage.setItem("warnwatcher_auth_email", String(body.email || payload.email));
    window.location.href = "./index.html";
  } catch (_err) {
    statusEl.textContent = "Network error. Try again.";
  }
});
