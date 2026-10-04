// ==UserScript==
// @name         Nightreign Challenge Title Sync
// @namespace    local.nr-challenge-tracker
// @version      1.0.0
// @description  Sync the tracker title through the Bilibili room-title editor.
// @match        https://link.bilibili.com/p/center/index*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

(function () {
  "use strict";

  const LOCAL_API = "http://127.0.0.1:5678/api/streak";
  const STATUS_API = "http://127.0.0.1:5678/api/sync-status";
  const POLL_INTERVAL_MS = 5000;
  const UI_SETTLE_MS = 300;
  const UI_TIMEOUT_MS = 5000;
  const STORAGE_KEY = "nr-challenge-tracker-synced";
  let pollIntervalMs = POLL_INTERVAL_MS;
  let retryDelayMs = POLL_INTERVAL_MS;
  let trackerRetryDelayMs = POLL_INTERVAL_MS;
  let nextUpdateAt = 0;

  const delay = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

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

  function waitFor(getValue, description) {
    return new Promise((resolve, reject) => {
      const deadline = Date.now() + UI_TIMEOUT_MS;
      const check = () => {
        const value = getValue();
        if (value) {
          resolve(value);
        } else if (Date.now() >= deadline) {
          reject(new Error(`Timed out waiting for ${description}`));
        } else {
          window.setTimeout(check, 100);
        }
      };
      check();
    });
  }

  function formatError(error) {
    return error instanceof Error ? error.message : String(error);
  }

  function updateRoomTitle(title) {
    const titleLabel = Array.from(document.querySelectorAll(".label-info"))
      .find((element) => element.textContent.replace("*", "").trim() === "房间标题：");
    const inputContainer = titleLabel?.parentElement?.querySelector(".input-cntr");
    const titleInput = inputContainer?.querySelector(':scope > input[type="text"]');
    if (!titleInput) {
      throw new Error("Could not find the room-title input");
    }
    if (titleInput.value === title) {
      return Promise.resolve();
    }

    console.log("[NR-challenge-tracker] Updating room title to:", title);
    titleInput.click();
    return delay(UI_SETTLE_MS)
      .then(() => waitFor(
        () => inputContainer.querySelector(".ai-title-panel"),
        "the AI title panel",
      ))
      .then((panel) => {
        const editor = panel.querySelector('input[type="text"]');
        if (!editor) {
          throw new Error("Could not find the AI title input");
        }

        editor.value = title;
        editor.dispatchEvent(new Event("input", { bubbles: true }));
        editor.dispatchEvent(new Event("change", { bubbles: true }));

        const saveLink = Array.from(panel.querySelectorAll("a"))
          .find((element) => element.textContent.trim() === "保存");
        if (!saveLink) {
          throw new Error("Could not find the AI title save link");
        }
        saveLink.click();
      })
      .then(() => delay(UI_SETTLE_MS))
      .then(() => waitFor(
        () => titleInput.value === title,
        "the room title to update",
      ));
  }

  function report(status, revision, message = "") {
    return request({
      method: "POST",
      url: STATUS_API,
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({ status, revision, message: message.slice(0, 200) }),
    }).catch(() => undefined);
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
      await report("sync.synced", payload.revision);
      return;
    }
    if (Date.now() < nextUpdateAt) {
      await report("sync.retrying", payload.revision);
      return;
    }

    try {
      await updateRoomTitle(payload.desired_title);
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ revision: payload.revision, title: payload.desired_title }),
      );
      retryDelayMs = POLL_INTERVAL_MS;
      nextUpdateAt = 0;
      await report("sync.synced", payload.revision);
    } catch (error) {
      await report(
        "sync.retrying",
        payload.revision,
        `Bilibili UI update failed: ${formatError(error) || "Unknown error"}`,
      );
      retryDelayMs = Math.min(Math.max(retryDelayMs * 2, POLL_INTERVAL_MS), 60000);
      nextUpdateAt = Date.now() + retryDelayMs;
    }
  }

  async function poll() {
    let nextPollDelayMs = Math.max(pollIntervalMs, retryDelayMs);
    try {
      const response = await request({ method: "GET", url: LOCAL_API });
      if (response.status < 200 || response.status >= 300) {
        throw new Error(`Tracker API HTTP ${response.status}`);
      }
      trackerRetryDelayMs = POLL_INTERVAL_MS;
      const payload = JSON.parse(response.responseText);
      await sync(payload);
      nextPollDelayMs = Math.max(pollIntervalMs, retryDelayMs);
    } catch (error) {
      console.warn("[NR-challenge-tracker] Tracker poll failed; retrying", formatError(error));
      let saved = null;
      try {
        saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
      if (saved?.revision !== undefined) {
        await report("sync.offline", saved.revision, formatError(error));
      }
      trackerRetryDelayMs = Math.min(
        Math.max(trackerRetryDelayMs * 2, POLL_INTERVAL_MS),
        60000,
      );
      nextPollDelayMs = Math.max(pollIntervalMs, trackerRetryDelayMs);
    } finally {
      window.setTimeout(poll, nextPollDelayMs);
    }
  }

  poll();
})();