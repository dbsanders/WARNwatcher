const listEl = document.getElementById("subscriptions-list");
const statusEl = document.getElementById("status");
const authSummaryEl = document.getElementById("auth-summary");
const refreshBtn = document.getElementById("refresh");
const logoutBtn = document.getElementById("logout");
const subscriptionsForm = document.getElementById("subscriptions-form");
const saveAllBtn = document.getElementById("save-all");

const apiBase = localStorage.getItem("warnwatcher_api_base") || "https://api.warnwatcher.com";
const authToken = localStorage.getItem("warnwatcher_auth_token") || "";
const authEmail = localStorage.getItem("warnwatcher_auth_email") || "";

let originalByWatchId = new Map();

if (!authToken) {
  window.location.href = "./signup.html";
}

authSummaryEl.textContent = authEmail ? `Signed in as ${authEmail}` : "Signed in";

function handleUnauthorized() {
  localStorage.removeItem("warnwatcher_auth_token");
  localStorage.removeItem("warnwatcher_auth_email");
  window.location.href = "./signup.html";
}

logoutBtn.addEventListener("click", () => {
  handleUnauthorized();
});

refreshBtn.addEventListener("click", () => {
  void loadSubscriptions();
});

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function normalizeSubscription(subscription) {
  return {
    watch_id: String(subscription.watch_id || ""),
    company: String(subscription.company || "").trim(),
    state: String(subscription.state || "CA").trim().toUpperCase(),
    min_employees: Number(subscription.min_employees || 0),
    is_enabled: Boolean(subscription.is_enabled),
  };
}

function setSaveEnabled(enabled) {
  saveAllBtn.disabled = !enabled;
}

function getCurrentRows() {
  const rows = Array.from(listEl.querySelectorAll("tbody tr"));
  return rows.map((row) => ({
    watch_id: String(row.dataset.watchId || ""),
    company: String(row.querySelector('input[name="company"]')?.value || "").trim(),
    state: String(row.querySelector('input[name="state"]')?.value || "CA").trim().toUpperCase(),
    min_employees: Number(row.querySelector('input[name="min_employees"]')?.value || 0),
    is_enabled: Boolean(row.querySelector('input[name="is_enabled"]')?.checked),
  }));
}

function getChangedRows() {
  const rows = getCurrentRows();
  return rows.filter((row) => {
    const original = originalByWatchId.get(row.watch_id);
    if (!original) {
      return false;
    }
    return (
      row.company !== original.company ||
      row.state !== original.state ||
      row.min_employees !== original.min_employees ||
      row.is_enabled !== original.is_enabled
    );
  });
}

function handleEdit() {
  setSaveEnabled(getChangedRows().length > 0);
}

function renderTable(subscriptions) {
  if (!subscriptions.length) {
    listEl.innerHTML = '<p class="muted">No subscriptions yet.</p>';
    setSaveEnabled(false);
    return;
  }

  const rows = subscriptions
    .map(
      (sub) => `
      <tr data-watch-id="${escapeHtml(sub.watch_id)}">
        <td><input name="company" type="text" required value="${escapeHtml(sub.company)}" /></td>
        <td><input name="state" type="text" maxlength="2" value="${escapeHtml(sub.state)}" /></td>
        <td><input name="min_employees" type="number" min="0" value="${Number(sub.min_employees)}" /></td>
        <td class="enabled-cell"><input name="is_enabled" type="checkbox" ${sub.is_enabled ? "checked" : ""} /></td>
        <td><button type="button" class="danger row-delete-btn">Delete</button></td>
      </tr>
    `,
    )
    .join("");

  listEl.innerHTML = `
    <div class="subscriptions-table-wrap">
      <table class="subscriptions-table">
        <thead>
          <tr>
            <th>Company Name</th>
            <th>State</th>
            <th>Min Employees</th>
            <th>Enabled</th>
            <th>Delete</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;

  listEl.querySelectorAll("input").forEach((input) => {
    input.addEventListener("input", handleEdit);
    input.addEventListener("change", handleEdit);
  });

  listEl.querySelectorAll(".row-delete-btn").forEach((button) => {
    button.addEventListener("click", async (event) => {
      const row = event.target.closest("tr");
      const watchId = String(row?.dataset.watchId || "");
      if (!watchId) {
        return;
      }
      await deleteSubscription(watchId);
    });
  });

  setSaveEnabled(false);
}

async function loadSubscriptions() {
  statusEl.textContent = "Loading subscriptions...";
  try {
    const res = await fetch(`${apiBase}/subscriptions`, {
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

    const subscriptions = (Array.isArray(body.subscriptions) ? body.subscriptions : []).map(normalizeSubscription);
    originalByWatchId = new Map(subscriptions.map((sub) => [sub.watch_id, sub]));
    renderTable(subscriptions);
    statusEl.textContent = `Loaded ${subscriptions.length} subscription(s).`;
  } catch (_err) {
    statusEl.textContent = "Network error. Try again.";
  }
}

subscriptionsForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const changedRows = getChangedRows();
  if (!changedRows.length) {
    statusEl.textContent = "No changes to save.";
    return;
  }

  statusEl.textContent = "Saving changes...";
  saveAllBtn.disabled = true;

  try {
    for (const row of changedRows) {
      const res = await fetch(`${apiBase}/subscriptions/${row.watch_id}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({
          company: row.company,
          state: row.state,
          min_employees: row.min_employees,
          is_enabled: row.is_enabled,
        }),
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
    }

    statusEl.textContent = `Saved ${changedRows.length} subscription(s).`;
    await loadSubscriptions();
  } catch (_err) {
    statusEl.textContent = "Network error. Try again.";
    setSaveEnabled(getChangedRows().length > 0);
  }
});

async function deleteSubscription(watchId) {
  statusEl.textContent = "Deleting subscription...";
  try {
    const res = await fetch(`${apiBase}/subscriptions/${watchId}`, {
      method: "DELETE",
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
    statusEl.textContent = "Subscription deleted.";
    await loadSubscriptions();
  } catch (_err) {
    statusEl.textContent = "Network error. Try again.";
  }
}

void loadSubscriptions();
