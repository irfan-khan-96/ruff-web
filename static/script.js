/* Ruff: theme, toasts, confirmations, and the sheet. */
(function () {
    "use strict";

    const store = (() => {
        try {
            localStorage.setItem("__ruff", "1");
            localStorage.removeItem("__ruff");
            return localStorage;
        } catch (e) {
            return null; // private mode / blocked storage: everything still works, just no drafts
        }
    })();

    const readJSON = (key) => {
        try { return JSON.parse(store?.getItem(key) || "null"); } catch (e) { return null; }
    };
    const writeJSON = (key, value) => {
        try { store?.setItem(key, JSON.stringify(value)); } catch (e) { /* quota: ignore */ }
    };

    /* --- Theme: notebook (light), chalkboard (dark) or match the device --- */
    const systemTheme = () => (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const applyTheme = (choice) => {
        if (choice === "light" || choice === "dark") store?.setItem("theme", choice);
        else store?.removeItem("theme");
        document.documentElement.dataset.theme = choice === "light" || choice === "dark" ? choice : systemTheme();
    };

    document.getElementById("theme-toggle")?.addEventListener("click", () => {
        applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
        document.querySelectorAll("input[name=theme]").forEach((radio) => {
            radio.checked = radio.value === document.documentElement.dataset.theme;
        });
    });

    document.querySelectorAll("input[name=theme]").forEach((radio) => {
        const saved = store?.getItem("theme");
        radio.checked = radio.value === (saved === "light" || saved === "dark" ? saved : "system");
        radio.addEventListener("change", () => applyTheme(radio.value));
    });

    matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
        const saved = store?.getItem("theme");
        if (saved !== "light" && saved !== "dark") applyTheme("system");
    });

    /* --- Toasts fade away on their own --- */
    const toast = (message, kind = "success") => {
        let host = document.querySelector(".toasts");
        if (!host) {
            host = document.createElement("div");
            host.className = "toasts";
            host.setAttribute("role", "status");
            host.setAttribute("aria-live", "polite");
            document.body.appendChild(host);
        }
        const el = document.createElement("div");
        el.className = `toast ${kind}`;
        el.textContent = message;
        host.appendChild(el);
        dismissLater(el);
    };
    const dismissLater = (el) => {
        setTimeout(() => {
            el.classList.add("is-leaving");
            setTimeout(() => el.remove(), 350);
        }, 3500);
    };
    document.querySelectorAll(".toast").forEach(dismissLater);
    try {
        const pending = sessionStorage.getItem("ruff:toast");
        if (pending) {
            sessionStorage.removeItem("ruff:toast");
            toast(pending);
        }
    } catch (e) { /* ignore */ }

    /* --- Confirm before destructive actions (data-confirm) --- */
    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-confirm]");
        if (button && !window.confirm(button.dataset.confirm)) event.preventDefault();
    });

    if ("serviceWorker" in navigator) {
        navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
    }

    /* ======================================================================
       The sheet
       ====================================================================== */
    const form = document.getElementById("sheet");
    if (!form) return;

    const text = document.getElementById("sheet-text");
    const tags = document.getElementById("sheet-tags");
    const status = document.getElementById("sheet-status");
    const wordCount = document.getElementById("word-count");
    const rosterBox = document.getElementById("roster");
    const rosterList = document.getElementById("roster-list");
    const loggedIn = form.dataset.loggedIn === "yes";
    let stashId = form.dataset.stashId || "";
    const draftKey = `ruff:sheet:${stashId || "new"}`;
    const csrf = form.querySelector("input[name=csrf_token]").value;

    const ROSTER = /^(\s*(?:[-*]\s+)?)\[( |x|X)\]\s?/;
    let serverTimer = null;
    let saving = false;
    const setStatus = (message) => { status.textContent = message; };

    /* Restore a draft: new sheets always; existing stashes only if the draft
       was made on top of the version on screen (never over newer edits) */
    const draft = readJSON(draftKey);
    if (draft && draft.text && (!stashId || draft.version === form.dataset.version) && draft.text !== text.value) {
        text.value = draft.text;
        if (typeof draft.tags === "string") tags.value = draft.tags;
        setStatus(stashId ? "Unsaved changes restored." : "Picked up where you left off.");
        if (stashId) queueServerSave();
    }

    function countWords() {
        const words = text.value.trim() ? text.value.trim().split(/\s+/).length : 0;
        wordCount.textContent = `${words} word${words === 1 ? "" : "s"}`;
    }

    /* --- Recess Roster: the sheet's [ ] lines as a live to-do list --- */
    function renderRoster() {
        const lines = text.value.split("\n");
        rosterList.textContent = "";
        let count = 0;
        lines.forEach((line, index) => {
            const match = line.match(ROSTER);
            const task = match ? line.slice(match[0].length).trim() : "";
            if (!task) return;
            count += 1;
            const done = match[2].toLowerCase() === "x";
            const li = document.createElement("li");
            li.className = done ? "done" : "";
            const label = document.createElement("label");
            const box = document.createElement("input");
            box.type = "checkbox";
            box.checked = done;
            box.addEventListener("change", () => toggleTask(index, box.checked));
            const span = document.createElement("span");
            span.textContent = task;
            label.append(box, span);
            li.append(label);
            rosterList.append(li);
        });
        rosterBox.hidden = count === 0;
    }

    function toggleTask(lineIndex, done) {
        const lines = text.value.split("\n");
        lines[lineIndex] = lines[lineIndex].replace(ROSTER, (_, lead) => `${lead}[${done ? "x" : " "}] `);
        text.value = lines.join("\n");
        changed();
    }

    function insertTask() {
        const start = text.selectionStart;
        const lineStart = text.value.lastIndexOf("\n", start - 1) + 1;
        const line = text.value.slice(lineStart, text.value.indexOf("\n", start) === -1 ? undefined : text.value.indexOf("\n", start));
        if (ROSTER.test(line)) { text.focus(); return; }
        const prefix = line.trim() ? "\n[ ] " : "[ ] ";
        const at = line.trim() ? lineStart + line.length : lineStart;
        text.setRangeText(prefix, at, at, "end");
        text.focus();
        changed();
    }
    document.getElementById("roster-add")?.addEventListener("click", insertTask);

    /* Lists continue on Enter, like a notebook: [ ] tasks, - bullets, 1. numbers.
       Enter on an empty item ends the list. */
    text.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
            event.preventDefault();
            save();
            return;
        }
        if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
        const pos = text.selectionStart;
        if (pos !== text.selectionEnd) return;
        const lineStart = text.value.lastIndexOf("\n", pos - 1) + 1;
        const line = text.value.slice(lineStart, pos);
        const match = line.match(/^(\s*)(\[[ xX]\] |[-*•] |(\d+)[.)] )/);
        if (!match) return;
        event.preventDefault();
        if (line.trim() === match[0].trim()) {
            text.setRangeText("", lineStart, pos, "end"); // empty item: end the list
        } else {
            const marker = match[3] ? `${Number(match[3]) + 1}${match[2].trim().slice(-1)} `
                : match[2].startsWith("[") ? "[ ] " : match[2];
            text.setRangeText(`\n${match[1]}${marker}`, pos, pos, "end");
        }
        changed();
    });

    /* --- Saving --- */
    function keepDraft() {
        writeJSON(draftKey, { text: text.value, tags: tags.value, version: form.dataset.version, at: Date.now() });
    }

    function changed() {
        countWords();
        renderRoster();
        keepDraft();
        if (stashId && loggedIn) {
            setStatus("Editing…");
            queueServerSave();
        } else if (text.value.trim()) {
            setStatus(loggedIn ? "Kept on this device. Stash it to keep it." : "Kept on this device. Sign up to stash it.");
        }
    }

    function queueServerSave() {
        clearTimeout(serverTimer);
        serverTimer = setTimeout(save, 1200);
    }

    async function save() {
        if (!loggedIn) {
            setStatus("Kept on this device. Sign up to stash it.");
            return;
        }
        if (!text.value.trim()) {
            setStatus("Write something first.");
            return;
        }
        if (saving) { queueServerSave(); return; }
        saving = true;
        clearTimeout(serverTimer);
        setStatus("Saving…");
        try {
            const response = await fetch(form.action, {
                method: "POST",
                headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf },
                body: JSON.stringify({ text: text.value, tags: tags.value, stash_id: stashId }),
            });
            const data = await response.json().catch(() => ({}));
            if (response.status === 401) {
                setStatus("Your session ended. Log in again; your note is kept on this device.");
                return;
            }
            if (!response.ok) {
                setStatus(data.error || "Couldn't save. It's kept on this device.");
                return;
            }
            try { store?.removeItem(draftKey); } catch (e) { /* ignore */ }
            if (!stashId) {
                // First stash: open it as a stash (gets its actions: pass, relay, toss…)
                try { sessionStorage.setItem("ruff:toast", "Stashed."); } catch (e) { /* ignore */ }
                window.location.assign(data.url);
                return;
            }
            form.dataset.version = data.version;
            setStatus("Stashed · just now");
        } catch (e) {
            setStatus("You're offline. Your note is kept on this device.");
        } finally {
            saving = false;
        }
    }

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        save();
    });
    text.addEventListener("input", changed);
    tags.addEventListener("input", () => {
        keepDraft();
        if (stashId && loggedIn) queueServerSave();
    });
    window.addEventListener("beforeunload", keepDraft);

    countWords();
    renderRoster();
})();
