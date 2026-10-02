// ==UserScript==
// @name         Nightreign Challenge Title Sync
// @namespace    local.nr-challenge-tracker
// @version      1.0.0
// @description  Sync the tracker title through the authenticated Bilibili session.
// @match        https://link.bilibili.com/p/center/index*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      api.live.bilibili.com
// ==/UserScript==

(function () {
  "use strict";

  const LOCAL_API = "http://127.0.0.1:5678/api/streak";
  const STATUS_API = "http://127.0.0.1:5678/api/sync-status";
  const ROOM_UPDATE_API = "https://api.live.bilibili.com/room/v1/Room/update";
  const POLL_INTERVAL_MS = 5000;
  const STORAGE_KEY = "nr-challenge-tracker-synced";
  let pollIntervalMs = POLL_INTERVAL_MS;
  let retryDelayMs = POLL_INTERVAL_MS;
  let nextUpdateAt = 0;

  function request(options) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        ...options,
        timeout: 10000,
        onload: resolve,
        onerror: () => reject(new Error("Network request failed")),
        ontimeout: () => reject(new Error("Network request timed out")),
      });
    });
  }

  function report(status, revision, message = "") {
    return request({
      method: "POST",
      url: STATUS_API,
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({ status, revision, message: message.slice(0, 200) }),
    }).catch(() => undefined);
  }

  function csrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)bili_jct=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function responseData(response) {
    if (response.status < 200 || response.status >= 300) {
      throw new Error(`HTTP ${response.status}`);
    }
    let data;
    try {
      data = JSON.parse(response.responseText);
    } catch {
      throw new Error("Invalid Bilibili response");
    }
    if (!data || data.code !== 0) {
      const error = new Error(data?.message || data?.msg || "Title update rejected");
      error.auth = data?.code === -101 || data?.code === -111;
      error.rejected = true;
      throw error;
    }
    return data;
  }

  async function sync(payload) {
    if (
      payload.schema_version !== 1 ||
      !Number.isInteger(payload.revision) ||
      !Number.isInteger(payload.current_streak) ||
      !Number.isInteger(payload.target) ||
      !Number.isInteger(payload.polling_interval_seconds) ||
      payload.polling_interval_seconds < 1 ||
      typeof payload.desired_title !== "string"
    ) {
      throw new Error("Invalid local tracker response");
    }
    pollIntervalMs = payload.polling_interval_seconds * 1000;
    if (!Number.isInteger(payload.room_id)) {
      await report("Title rejected", payload.revision, "Configure bilibili.room_id in config.yaml");
      return;
    }

    let saved = null;
    try {
      saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    } catch {
      localStorage.removeItem(STORAGE_KEY);
    }
    if (
      saved?.revision === payload.revision &&
      saved?.title === payload.desired_title
    ) {
      await report("Synced", payload.revision);
      return;
    }
    if (Date.now() < nextUpdateAt) {
      await report("Retrying", payload.revision);
      return;
    }

    const csrf = csrfToken();
    if (!csrf) {
      await report(
        "Authentication required",
        payload.revision,
        "Bilibili CSRF token unavailable",
      );
      nextUpdateAt = Date.now() + 30000;
      return;
    }

    const form = new URLSearchParams({
      room_id: String(payload.room_id),
      title: payload.desired_title,
      csrf,
    });
    try {
      const response = await request({
        method: "POST",
        url: ROOM_UPDATE_API,
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        data: form.toString(),
        withCredentials: true,
      });
      responseData(response);
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ revision: payload.revision, title: payload.desired_title }),
      );
      retryDelayMs = POLL_INTERVAL_MS;
      nextUpdateAt = 0;
      await report("Synced", payload.revision);
    } catch (error) {
      const status = error.auth
        ? "Authentication required"
        : error.rejected
          ? "Title rejected"
          : "Retrying";
      await report(status, payload.revision, error.message || "Request failed");
      retryDelayMs = Math.min(Math.max(retryDelayMs * 2, POLL_INTERVAL_MS), 60000);
      nextUpdateAt = Date.now() + retryDelayMs;
    }
  }

  async function poll() {
    try {
      const response = await request({ method: "GET", url: LOCAL_API });
      if (response.status < 200 || response.status >= 300) {
        throw new Error(`Tracker API HTTP ${response.status}`);
      }
      const payload = JSON.parse(response.responseText);
      await sync(payload);
    } catch (error) {
      let saved = null;
      try {
        saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
      if (saved?.revision !== undefined) {
        await report("Offline", saved.revision, error.message || "Tracker unavailable");
      }
      retryDelayMs = Math.min(Math.max(retryDelayMs * 2, POLL_INTERVAL_MS), 60000);
      nextUpdateAt = Date.now() + retryDelayMs;
    } finally {
      window.setTimeout(poll, Math.max(pollIntervalMs, retryDelayMs));
    }
  }

  poll();
})();