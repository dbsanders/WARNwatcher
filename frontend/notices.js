const listEl = document.getElementById("notices-list");
const statusEl = document.getElementById("status");
const authSummaryEl = document.getElementById("auth-summary");
const refreshBtn = document.getElementById("refresh");
const logoutBtn = document.getElementById("logout");

const apiBase = localStorage.getItem("warnwatcher_api_base") || "https://api.warnwatcher.com";
const authToken = localStorage.getItem("warnwatcher_auth_token") || "";
const authEmail = localStorage.getItem("warnwatcher_auth_email") || "";

if (!authToken) {
  window.location.href = "./signup.html";
}

authSummaryEl.textContent = authEmail ? `Signed in as ${authEmail}` : "Signed in";

function handleUnauthorized() {
  localStorage.removeItem("warnwatcher_auth_token");
  localStorage.removeItem("warnwatcher_auth_email");
  window.location.href = "./signup.html";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function normalizeNotice(notice) {
  return {
    notice_id: String(notice.notice_id || ""),
    company: String(notice.company || "").trim(),
    state: String(notice.state || "").trim().toUpperCase(),
    city: String(notice.city || "").trim(),
    county: String(notice.county || "").trim(),
    employees_affected: Number(notice.employees_affected || 0),
    notice_date: String(notice.notice_date || "").trim(),
    effective_date: String(notice.effective_date || "").trim(),
    received_at: String(notice.received_at || "").trim(),
    source_id: String(notice.source_id || "").trim(),
    s3_object_key: String(notice.s3_object_key || "").trim(),
  };
}

function renderNotices(notices) {
  if (!notices.length) {
    listEl.innerHTML = '<p class="muted">No notices found.</p>';
    return;
  }

  const rows = notices
    .map(
      (notice) => `
      <tr>
        <td>${escapeHtml(notice.company)}</td>
        <td>${escapeHtml(notice.state)}</td>
        <td>${escapeHtml(notice.city)}</td>
        <td>${escapeHtml(notice.county)}</td>
        <td>${Number(notice.employees_affected)}</td>
        <td>${escapeHtml(notice.notice_date)}</td>
        <td>${escapeHtml(notice.effective_date)}</td>
        <td>${escapeHtml(notice.notice_id)}</td>
        <td>${escapeHtml(notice.source_id)}</td>
      </tr>
    `,
    )
    .join("");

  listEl.innerHTML = `
    <div class="subscriptions-table-wrap">
      <table class="subscriptions-table notices-table">
        <thead>
          <tr>
            <th>Company</th>
            <th>State</th>
            <th>City</th>
            <th>County</th>
            <th>Employees</th>
            <th>Notice Date</th>
            <th>Effective Date</th>
            <th>Notice ID</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

async function loadNotices() {
  statusEl.textContent = "Loading notices...";
  try {
    const res = await fetch(`${apiBase}/notices`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${authToken}`,
      },
    });
    const body = await res.json();
    if (res.status === 401) {
      handleUnauthorized();
      return;
    }
    if (!res.ok) {
      statusEl.textContent = `Error: ${body.message || "request failed"}`;
      return;
    }

    const notices = (Array.isArray(body.notices) ? body.notices : []).map(normalizeNotice);
    renderNotices(notices);
    const truncated = body.truncated ? " Showing first 2000." : "";
    statusEl.textContent = `Loaded ${notices.length} notice(s).${truncated}`;
  } catch (_err) {
    statusEl.textContent = "Network error. Try again.";
  }
}

refreshBtn.addEventListener("click", () => {
  void loadNotices();
});

logoutBtn.addEventListener("click", () => {
  handleUnauthorized();
});

void loadNotices();
