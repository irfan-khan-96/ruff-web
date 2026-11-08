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

    const Store = window.RuffStore;
    const $ = (id) => document.getElementById(id);
    if (Store) Store.onSync((state) => {
        if (state === "conflict") toast("A note changed on two devices at once. Both versions are kept.", "info");
    });
    const b64 = {
        encode: (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""),
        decode: (text) => Uint8Array.from(atob(text.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0)),
    };
    const ago = (ms) => {
        const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
        if (s < 60) return "just now";
        for (const [unit, size, next] of [["minute", 60, 3600], ["hour", 3600, 86400], ["day", 86400, 604800]]) {
            if (s < next) { const n = Math.floor(s / size); return `${n} ${unit}${n === 1 ? "" : "s"} ago`; }
        }
        return new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    };
    const download = (filename, text, type = "text/plain") => {
        const url = URL.createObjectURL(new Blob([text], { type }));
        const a = Object.assign(document.createElement("a"), { href: url, download: filename });
        document.body.append(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    const slug = (text) => (text || "note").replace(/[^\p{L}\p{N} _-]/gu, " ").trim().split(/\s+/).join("-").slice(0, 30) || "note";
    const parseTags = (raw) => [...new Set((raw || "").split(",").map((t) => t.trim().replace(/^#+/, "").trim().toLowerCase()).filter(Boolean))];

    /* ======================================================================
       Recently stashed (sheet sidebar)
       ====================================================================== */
    async function renderRecent(currentId) {
        const box = $("recent");
        if (!box) return;
        const notes = (await Store.list()).slice(0, 8);
        const list = $("recent-list");
        list.textContent = "";
        for (const note of notes) {
            const li = document.createElement("li");
            const a = Object.assign(document.createElement("a"), { href: `/stashes/${note.id}`, textContent: Store.firstLine(note.text) || "Untitled" });
            if (note.id === currentId) a.setAttribute("aria-current", "page");
            li.append(a);
            list.append(li);
        }
        box.hidden = notes.length === 0;
    }

    /* ======================================================================
       The sheet
       ====================================================================== */
    const form = $("sheet");
    if (form) initSheet();

    async function initSheet() {
        const text = $("sheet-text");
        const tags = $("sheet-tags");
        const status = $("sheet-status");
        const wordCount = $("word-count");
        const rosterBox = $("roster");
        const rosterList = $("roster-list");
        const ROSTER = /^(\s*(?:[-*]\s+)?)\[( |x|X)\]\s?/;
        const DRAFT_KEY = "ruff:sheet:new";
        // Offline, a stash opens in the cached blank sheet: take its id from the URL
        let noteId = form.dataset.stashId || (location.pathname.match(/^\/stashes\/([0-9a-f-]{36})$/) || [])[1] || "";
        let saveTimer = null;
        const setStatus = (message) => { status.textContent = message; };
        const syncedStatus = () => Store.signedIn ? "Stashed" : "Stashed on this device. Sign in to sync.";

        await Store.ready;
        if (noteId) {
            const note = await Store.get(noteId);
            if (!note) {
                form.hidden = true;
                $("sheet-missing").hidden = false;
                renderRecent(noteId);
                return;
            }
            text.value = note.text;
            tags.value = (note.tags || []).join(", ");
            setStatus(Store.signedIn
                ? `Stashed · ${ago(note.updated_at)}`
                : `Stashed on this device · ${ago(note.updated_at)}. Sign in to sync.`);
            $("sheet-actions").hidden = false;
            $("stash-button").textContent = "Save & close";  // offline, the page may be the blank-sheet copy
        } else {
            const draft = readJSON(DRAFT_KEY);
            if (draft && draft.text) {
                text.value = draft.text;
                tags.value = draft.tags || "";
                setStatus("Picked up where you left off.");
            }
        }
        renderRecent(noteId);

        Store.onSync((state) => {
            if (!noteId) return;
            const messages = {
                syncing: "Syncing…", synced: "Stashed · synced", partial: "Some notes couldn't sync.",
                offline: "Offline. Saved on this device; it'll sync later.",
                "signed-out": "Signed out. Saved on this device.", error: "Couldn't sync. Saved on this device.",
            };
            if (messages[state]) setStatus(messages[state]);
        });

        function countWords() {
            const words = text.value.trim() ? text.value.trim().split(/\s+/).length : 0;
            wordCount.textContent = `${words} word${words === 1 ? "" : "s"}`;
        }

        /* --- Recess Roster: the sheet's [ ] lines as a live to-do list --- */
        function renderRoster() {
            rosterList.textContent = "";
            let count = 0;
            text.value.split("\n").forEach((line, index) => {
                const match = line.match(ROSTER);
                const task = match ? line.slice(match[0].length).trim() : "";
                if (!task) return;
                count += 1;
                const done = match[2].toLowerCase() === "x";
                const li = document.createElement("li");
                li.className = done ? "done" : "";
                const label = document.createElement("label");
                const box = Object.assign(document.createElement("input"), { type: "checkbox", checked: done });
                box.addEventListener("change", () => toggleTask(index, box.checked));
                const span = Object.assign(document.createElement("span"), { textContent: task });
                label.append(box, span);
                li.append(label);
                rosterList.append(li);
            });
            rosterBox.hidden = count === 0;
        }

        const lineStartOf = (index) => text.value.split("\n").slice(0, index).reduce((sum, line) => sum + line.length + 1, 0);
        const lineEndAt = (start) => { const end = text.value.indexOf("\n", start); return end === -1 ? text.value.length : end; };
        const lineStartAt = (pos) => text.value.lastIndexOf("\n", pos - 1) + 1;

        function toggleTask(lineIndex, done) { setTask(lineStartOf(lineIndex), done); }

        /* Ticks a to-do (or unticks it), keeping the caret where it was */
        function setTask(lineStart, done) {
            const match = text.value.slice(lineStart, lineEndAt(lineStart)).match(ROSTER);
            if (!match) return;
            text.setRangeText(`${match[1]}[${done ? "x" : " "}] `, lineStart, lineStart + match[0].length, "preserve");
            changed();
        }

        /* --- To-dos on the sheet: a real box drawn over each "[ ]" marker --- */
        const marks = $("todo-marks");
        const mirror = Object.assign(document.createElement("div"), { className: "todo-mirror" });
        mirror.setAttribute("aria-hidden", "true");
        text.after(mirror);
        let drawQueued = false;
        const queueDraw = () => {
            if (drawQueued) return;
            drawQueued = true;
            requestAnimationFrame(drawTodos);
        };

        function drawTodos() {
            drawQueued = false;
            marks.textContent = "";
            mirror.textContent = "";
            const lines = text.value.split("\n");
            if (!lines.some((line) => ROSTER.test(line))) return;
            // The mirror lays the text out exactly like the sheet, so each marker can be measured
            const style = getComputedStyle(text);
            for (const key of ["fontFamily", "fontSize", "fontWeight", "fontStyle", "lineHeight", "letterSpacing",
                "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "tabSize"]) mirror.style[key] = style[key];
            mirror.style.width = `${text.clientWidth}px`;
            const found = [];
            let offset = 0;
            for (const line of lines) {
                const match = line.match(ROSTER);
                if (match) {
                    const marker = Object.assign(document.createElement("span"), { textContent: match[0].slice(match[1].length) });
                    const rest = Object.assign(document.createElement("span"), { textContent: line.slice(match[0].length) || "​" });
                    mirror.append(match[1], marker, rest, "\n");
                    found.push({ marker, rest, start: offset, done: match[2] !== " ", task: line.slice(match[0].length).trim() });
                } else {
                    mirror.append(line + "\n");
                }
                offset += line.length + 1;
            }
            const origin = mirror.getBoundingClientRect();
            const lineHeight = parseFloat(style.lineHeight) || 32;
            const reach = 26;  // the box's tap area reaches into the margin
            for (const { marker, rest, start, done, task } of found) {
                const at = marker.getClientRects()[0];
                if (!at) continue;
                const top = at.top - origin.top - (lineHeight - at.height) / 2;
                const left = at.left - origin.left;
                const box = document.createElement("span");
                box.className = "todo-box";
                box.setAttribute("role", "checkbox");
                box.setAttribute("aria-checked", String(done));
                box.setAttribute("aria-label", task ? `Done: ${task}` : "Done: (empty to-do)");
                box.tabIndex = -1;
                box.style.cssText = `top:${top}px;left:${left - reach}px;width:${Math.max(at.width, 20) + reach}px;height:${lineHeight}px`;
                box.style.setProperty("--cover", `${Math.max(at.width, 20)}px`);
                box.addEventListener("pointerdown", (event) => event.preventDefault());  // keep the caret in the sheet
                box.addEventListener("click", () => setTask(start, !done));
                marks.append(box);
                if (done && task) {
                    for (const piece of rest.getClientRects()) {
                        const strike = document.createElement("span");
                        strike.className = "todo-strike";
                        strike.style.cssText = `top:${piece.top - origin.top + piece.height / 2}px;left:${piece.left - origin.left}px;width:${piece.width}px`;
                        marks.append(strike);
                    }
                }
            }
            marks.style.transform = `translateY(${-text.scrollTop}px)`;
        }

        text.addEventListener("scroll", () => { marks.style.transform = `translateY(${-text.scrollTop}px)`; });
        if (window.ResizeObserver) new ResizeObserver(queueDraw).observe(text);
        document.fonts?.ready.then(queueDraw);

        /* The caret never hides under a box: it jumps to just after the marker */
        function markerAt(pos) {
            const start = lineStartAt(pos);
            const match = text.value.slice(start, lineEndAt(start)).match(ROSTER);
            return match ? { start, from: start + match[1].length, to: start + match[0].length } : null;
        }
        function keepCaretOutOfMarkers() {
            const pos = text.selectionStart;
            if (pos !== text.selectionEnd) return;
            const marker = markerAt(pos);
            if (marker && pos >= marker.from && pos < marker.to) text.setSelectionRange(marker.to, marker.to);
        }
        text.addEventListener("pointerup", keepCaretOutOfMarkers);
        text.addEventListener("keyup", keepCaretOutOfMarkers);

        /* Backspace right after a marker turns the to-do back into a plain line */
        text.addEventListener("beforeinput", (event) => {
            if (event.inputType !== "deleteContentBackward") return;
            const pos = text.selectionStart;
            const marker = pos === text.selectionEnd && markerAt(pos);
            if (!marker || pos !== marker.to) return;
            event.preventDefault();
            text.setRangeText("", marker.from, marker.to, "end");
            changed();
        });

        /* Lists continue on Enter: to-dos, - bullets, 1. numbers; Enter on an empty item ends the list.
           Handled after the line break goes in, so phone keyboards (which don't report the key) work too. */
        let softBreak = false;
        text.addEventListener("keydown", (event) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
                event.preventDefault();
                stashNow();
                return;
            }
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {  // Ctrl+Enter ticks the current to-do
                const marker = markerAt(text.selectionStart);
                if (marker) {
                    event.preventDefault();
                    setTask(marker.start, text.value[marker.from + 1] === " ");
                }
                return;
            }
            if (event.key === "Enter") softBreak = event.shiftKey;
            if (event.key === "ArrowLeft" && !event.shiftKey && text.selectionStart === text.selectionEnd) {
                const marker = markerAt(text.selectionStart);
                if (marker && text.selectionStart === marker.to) {
                    event.preventDefault();
                    const to = Math.max(marker.start - 1, 0);
                    text.setSelectionRange(to, to);
                }
            }
        });
        text.addEventListener("input", (event) => {
            const isBreak = /^insert(LineBreak|Paragraph)$/.test(event.inputType)
                || (event.inputType === "insertText" && (event.data || "").endsWith("\n"));
            const soft = softBreak;
            softBreak = false;
            if (!isBreak || soft) return;
            const pos = text.selectionStart;
            if (pos !== text.selectionEnd || text.value[pos - 1] !== "\n") return;
            const prevStart = lineStartAt(pos - 1);
            const prev = text.value.slice(prevStart, pos - 1);
            let match = prev.match(ROSTER);
            let marker;
            if (match) {
                marker = `${match[1]}[ ] `;
            } else if ((match = prev.match(/^(\s*)([-*•] |(\d+)([.)]) )/))) {
                marker = match[3] ? `${match[1]}${Number(match[3]) + 1}${match[4]} ` : match[1] + match[2];
            } else {
                return;
            }
            if (prev.slice(match[0].length).trim()) {
                text.setRangeText(marker, pos, pos, "end");
            } else {
                text.setRangeText("", prevStart, pos, "end");  // an empty item: the list ends here
            }
        });

        $("roster-add")?.addEventListener("click", () => {
            const start = text.selectionStart;
            const lineStart = text.value.lastIndexOf("\n", start - 1) + 1;
            const nextBreak = text.value.indexOf("\n", start);
            const line = text.value.slice(lineStart, nextBreak === -1 ? undefined : nextBreak);
            if (!ROSTER.test(line)) {
                const at = line.trim() ? lineStart + line.length : lineStart;
                text.setRangeText(line.trim() ? "\n[ ] " : "[ ] ", at, at, "end");
                changed();
            }
            text.focus();
        });

        /* --- Saving: drafts until stashed; stashed notes autosave on this device --- */
        function changed() {
            countWords();
            renderRoster();
            queueDraw();
            if (noteId) {
                setStatus("Editing…");
                clearTimeout(saveTimer);
                saveTimer = setTimeout(saveNote, 400);
            } else {
                writeJSON(DRAFT_KEY, { text: text.value, tags: tags.value });
                if (text.value.trim()) setStatus("Draft kept on this device. Stash it to keep it.");
            }
        }

        async function saveNote() {
            if (!text.value.trim()) { setStatus("Write something first."); return null; }
            const note = await Store.save({ id: noteId || undefined, text: text.value, tags: parseTags(tags.value) });
            setStatus(Store.signedIn ? (navigator.onLine ? "Saved · syncing soon" : "Offline. Saved on this device.") : syncedStatus());
            return note;
        }

        /* Stashing files the note away and leaves a clean pad */
        let stashing = false;
        async function stashNow() {
            if (stashing) return;  // a double tap stashes once
            stashing = true;
            clearTimeout(saveTimer);
            saveTimer = null;
            try {
                const note = await saveNote();
                if (!note) return;
                if (noteId) {
                    try { sessionStorage.setItem("ruff:toast", "Saved to your stash."); } catch (e) { /* ignore */ }
                    if (Store.signedIn) await Store.sync();
                    window.location.assign("/");
                    return;
                }
                try { store?.removeItem(DRAFT_KEY); } catch (e) { /* ignore */ }
                text.value = "";
                tags.value = "";
                countWords();
                renderRoster();
                queueDraw();
                setStatus("");
                toast(Store.signedIn ? "Stashed. Fresh page ready." : "Stashed on this device. Fresh page ready.");
                renderRecent("");
                text.focus();
                if (Store.signedIn) Store.sync();
            } finally {
                stashing = false;
            }
        }

        form.addEventListener("submit", (event) => { event.preventDefault(); stashNow(); });
        text.addEventListener("input", changed);
        tags.addEventListener("input", changed);
        // Leaving or hiding the page (phones rarely fire beforeunload): save a pending edit now
        const flush = () => {
            if (!noteId || !saveTimer) return;
            clearTimeout(saveTimer);
            saveTimer = null;
            saveNote();
        };
        window.addEventListener("pagehide", flush);
        document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") flush(); });
        // Ctrl/⌘+S works from the tags too
        tags.addEventListener("keydown", (event) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); stashNow(); }
        });

        /* --- Actions on a stashed note --- */
        $("download-button")?.addEventListener("click", () => {
            const tagLine = parseTags(tags.value).map((t) => `#${t}`).join(", ");
            download(`stash-${slug(Store.firstLine(text.value))}.txt`, text.value.replace(/\n+$/, "") + "\n" + (tagLine ? `\nTags: ${tagLine}\n` : ""));
        });
        $("toss-button")?.addEventListener("click", async () => {
            if (!window.confirm("Toss this stash? There's no undo.")) return;
            await Store.remove(noteId);
            if (Store.signedIn) await Store.sync();
            try { sessionStorage.setItem("ruff:toast", "Tossed it."); } catch (e) { /* ignore */ }
            window.location.assign("/stashes");
        });
        $("relay-form")?.addEventListener("submit", (event) => {
            const relayForm = event.target;
            relayForm.elements.title.value = Store.firstLine(text.value) || "Recess Relay";
            relayForm.elements.prompt.value = text.value.split("\n").slice(1).join("\n").trim().slice(0, 2000);
        });
        $("fold-button")?.addEventListener("click", () => foldNote(text.value));

        countWords();
        renderRoster();
        queueDraw();
    }

    /* ======================================================================
       Folded notes: encrypted here, opened once, key only in the #fragment
       ====================================================================== */
    async function foldNote(plain) {
        const panel = $("fold-panel");
        if (!plain.trim()) return toast("Write something first.", "error");
        if (!crypto.subtle) return toast("Folding needs a secure (https) connection.", "error");
        try {
            const key = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, ["encrypt"]);
            const iv = crypto.getRandomValues(new Uint8Array(12));
            const sealed = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(plain));
            const rawKey = await crypto.subtle.exportKey("raw", key);
            const response = await fetch("/fold", {
                method: "POST",
                headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": document.body.dataset.csrf },
                body: JSON.stringify({ ciphertext: b64.encode(sealed), iv: b64.encode(iv) }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) return toast(data.error || "Couldn't fold that. Try again?", "error");
            const link = `${data.url}#${b64.encode(rawKey)}`;
            $("fold-url").value = link;
            // QR drawn here, never by a server: the link carries the key after #
            if (window.qrcode) {
                const qr = window.qrcode(0, "M");
                qr.addData(link, "Byte");
                qr.make();
                const img = $("fold-qr");
                img.src = qr.createDataURL(5, 2);
                img.hidden = false;
            }
            $("fold-expiry").textContent = `Unopened, it expires ${new Date(data.expires_at + "Z").toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" })}.`;
            panel.hidden = false;
            panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
            const share = $("fold-share");
            if (navigator.share) {
                share.hidden = false;
                share.onclick = () => navigator.share({ title: "A folded note", text: "Someone passed you a note.", url: link }).catch(() => {});
            }
            $("fold-copy").onclick = async () => {
                try { await navigator.clipboard.writeText(link); toast("Link copied."); }
                catch (e) { $("fold-url").select(); }
            };
        } catch (e) {
            toast("Couldn't fold that. Try again?", "error");
        }
    }

    const unfold = $("unfold");
    if (unfold) {
        const key = location.hash.slice(1);
        if (!key) {
            $("unfold-status").textContent = "This link is missing its key (the part after #). Ask for the whole link.";
            unfold.disabled = true;
        }
        unfold.addEventListener("click", async () => {
            unfold.disabled = true;
            $("unfold-status").textContent = "Unfolding…";
            try {
                const response = await fetch(`${location.pathname}/open`, {
                    method: "POST",
                    headers: { Accept: "application/json", "X-CSRFToken": document.body.dataset.csrf },
                });
                if (!response.ok) {
                    $("unfold-status").textContent = "Someone already opened this note, or it expired.";
                    return;
                }
                const { ciphertext, iv } = await response.json();
                const cryptoKey = await crypto.subtle.importKey("raw", b64.decode(key), "AES-GCM", false, ["decrypt"]);
                const plain = new TextDecoder().decode(await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64.decode(iv) }, cryptoKey, b64.decode(ciphertext)));
                history.replaceState(null, "", location.pathname); // drop the key from the address bar
                $("unfold-closed").hidden = true;
                $("unfold-open").hidden = false;
                $("unfold-text").textContent = plain;
                $("unfold-keep").onclick = async () => {
                    await Store.ready;
                    const note = await Store.save({ text: plain, tags: [] });
                    try { sessionStorage.setItem("ruff:toast", "Kept it in your stash."); } catch (e) { /* ignore */ }
                    window.location.assign(`/stashes/${note.id}`);
                };
            } catch (e) {
                $("unfold-status").textContent = "This note couldn't be unlocked. The link may be incomplete.";
            }
        });
    }

    /* ======================================================================
       Stash list (rendered from this device's store)
       ====================================================================== */
    const stashList = $("stash-list");
    if (stashList) initList();

    async function initList() {
        const search = $("search");
        const chips = $("tag-chips");
        const empty = $("stash-empty");
        const nothing = $("stash-nothing");
        const more = $("load-more");
        const params = new URLSearchParams(location.search);
        let tag = params.get("tag") || "";
        let shown = 30;
        search.value = params.get("q") || "";
        await Store.ready;

        async function render() {
            const notes = await Store.list();
            const q = search.value.trim().toLowerCase();
            const counts = new Map();
            notes.forEach((n) => (n.tags || []).forEach((t) => counts.set(t, (counts.get(t) || 0) + 1)));

            chips.textContent = "";
            if (counts.size) {
                const chip = (label, value) => {
                    const a = Object.assign(document.createElement("a"), { className: "chip", href: value ? `?tag=${encodeURIComponent(value)}` : "?", textContent: label });
                    if (tag === value) a.setAttribute("aria-current", "true");
                    a.addEventListener("click", (event) => { event.preventDefault(); tag = value; shown = 30; history.replaceState(null, "", value ? `?tag=${encodeURIComponent(value)}` : location.pathname); render(); });
                    chips.append(a);
                };
                chip("All", "");
                [...counts.keys()].sort().forEach((t) => chip(`#${t}`, t));
            }
            chips.hidden = counts.size === 0;

            const matches = notes.filter((n) => (!tag || (n.tags || []).includes(tag)) && (!q || n.text.toLowerCase().includes(q)));
            stashList.textContent = "";
            for (const note of matches.slice(0, shown)) {
                const li = document.createElement("li");
                const card = Object.assign(document.createElement("a"), { className: "stash-card", href: `/stashes/${note.id}` });
                const title = Object.assign(document.createElement("span"), { className: "stash-card-title", textContent: Store.firstLine(note.text) || "Untitled" });
                card.append(title);
                const previewText = Store.preview(note.text);
                if (previewText) card.append(Object.assign(document.createElement("span"), { className: "stash-card-preview", textContent: previewText }));
                const metaLine = Object.assign(document.createElement("span"), { className: "stash-card-meta" });
                metaLine.append(Object.assign(document.createElement("span"), { textContent: ago(note.updated_at) }));
                const todo = Store.tasks(note.text);
                if (todo.length) metaLine.append(Object.assign(document.createElement("span"), { textContent: `☑ ${todo.filter((t) => t.done).length}/${todo.length} done` }));
                if (note.dirty && Store.signedIn) metaLine.append(Object.assign(document.createElement("span"), { textContent: "not synced yet" }));
                (note.tags || []).forEach((t) => metaLine.append(Object.assign(document.createElement("span"), { className: "tag", textContent: `#${t}` })));
                card.append(metaLine);
                li.append(card);
                stashList.append(li);
            }
            empty.hidden = notes.length > 0;
            nothing.hidden = notes.length === 0 || matches.length > 0;
            more.hidden = matches.length <= shown;
        }

        $("search-form").addEventListener("submit", (event) => { event.preventDefault(); shown = 30; render(); });
        search.addEventListener("input", () => { shown = 30; render(); });
        more.addEventListener("click", () => { shown += 30; render(); });
        Store.onSync((state) => { if (state === "synced" || state === "partial") render(); });
        render();
    }

    /* ======================================================================
       Teachers Lounge: backup and restore this device's notes
       ====================================================================== */
    $("backup-button")?.addEventListener("click", async () => {
        await Store.ready;
        const notes = await Store.list();
        const backup = {
            version: "2.0",
            exported_at: new Date().toISOString(),
            stashes: notes.map((n) => ({
                id: n.id, title: Store.firstLine(n.text), body: n.text, checklist: Store.tasks(n.text),
                tags: n.tags || [], updated_at: new Date(n.updated_at).toISOString(),
            })),
        };
        download(`ruff-backup-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(backup, null, 2), "application/json");
    });

    /* --- Passkeys: add one in the Lounge, sign in with it on the login page --- */
    const passkeysWork = Boolean(window.PublicKeyCredential && navigator.credentials);
    const postJSON = async (url, body) => {
        const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": document.body.dataset.csrf },
            body: JSON.stringify(body || {}),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "That didn't work. Try again?");
        return data;
    };
    const credentialJSON = (cred) => {
        const r = cred.response;
        const response = { clientDataJSON: b64.encode(r.clientDataJSON) };
        if (r.attestationObject) {
            response.attestationObject = b64.encode(r.attestationObject);
            response.transports = r.getTransports ? r.getTransports() : [];
        } else {
            response.authenticatorData = b64.encode(r.authenticatorData);
            response.signature = b64.encode(r.signature);
            if (r.userHandle) response.userHandle = b64.encode(r.userHandle);
        }
        return { id: cred.id, rawId: b64.encode(cred.rawId), type: cred.type, response,
                 clientExtensionResults: cred.getClientExtensionResults(), authenticatorAttachment: cred.authenticatorAttachment };
    };
    const showPasskeyError = (message) => {
        const box = $("passkey-error");
        if (box) { box.textContent = message; box.hidden = !message; }
    };
    const cancelled = (e) => e && (e.name === "NotAllowedError" || e.name === "AbortError");

    $("passkey-add")?.addEventListener("click", async (event) => {
        if (!passkeysWork) return;
        const button = event.currentTarget;
        button.disabled = true;
        showPasskeyError("");
        try {
            const options = await postJSON("/passkeys/options");
            options.challenge = b64.decode(options.challenge);
            options.user.id = b64.decode(options.user.id);
            (options.excludeCredentials || []).forEach((c) => { c.id = b64.decode(c.id); });
            const cred = await navigator.credentials.create({ publicKey: options });
            await postJSON("/passkeys", credentialJSON(cred));
            location.reload();
        } catch (e) {
            if (e && e.name === "InvalidStateError") showPasskeyError("This device already has a passkey here.");
            else if (!cancelled(e)) showPasskeyError(e.message || "That didn't work. Try again?");
            button.disabled = false;
        }
    });
    if ($("passkey-add") && !passkeysWork) {
        $("passkey-add").hidden = true;
        $("passkey-unsupported").hidden = false;
    }

    const signinButton = $("passkey-signin");
    if (signinButton && passkeysWork) {
        signinButton.hidden = false;
        signinButton.addEventListener("click", async () => {
            signinButton.disabled = true;
            showPasskeyError("");
            try {
                const options = await postJSON("/login/passkey/options");
                options.challenge = b64.decode(options.challenge);
                (options.allowCredentials || []).forEach((c) => { c.id = b64.decode(c.id); });
                const cred = await navigator.credentials.get({ publicKey: options });
                const result = await postJSON("/login/passkey", credentialJSON(cred));
                location.assign(result.redirect || "/");
            } catch (e) {
                if (!cancelled(e)) showPasskeyError(e.message || "That didn't work. Try again?");
                signinButton.disabled = false;
            }
        });
    }

    $("restore-form")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const file = $("file-input").files[0];
        if (!file) return toast("Pick a backup file first.", "error");
        let data;
        try { data = JSON.parse(await file.text()); } catch (e) { return toast("That isn't a backup file.", "error"); }
        await Store.ready;
        const existing = new Set((await Store.list()).map((n) => n.id));
        const collections = new Map((data.collections || []).map((c) => [c.id, c.name]));
        let added = 0;
        let skipped = 0;
        for (const item of data.stashes || []) {
            const id = typeof item.id === "string" && /^[0-9a-f-]{36}$/.test(item.id) ? item.id : Store.newId();
            if (existing.has(id)) { skipped += 1; continue; }
            let body = String(item.body || item.text || "");
            if (item.title && Store.firstLine(body) !== String(item.title).trim()) body = `${String(item.title).trim()}\n\n${body}`;
            const known = new Set(Store.tasks(body).map((t) => t.text));
            const extra = (item.checklist || []).filter((t) => t && t.text && !known.has(String(t.text).trim()))
                .map((t) => `[${t.done ? "x" : " "}] ${String(t.text).trim()}`);
            if (extra.length) body = `${body}\n\n${extra.join("\n")}`;
            if (!body.trim() || body.length > 50000) { skipped += 1; continue; }
            const tags = parseTags([...(Array.isArray(item.tags) ? item.tags : String(item.tags || "").split(",")), item.collection_name || collections.get(item.collection_id) || ""].join(","));
            await Store.save({ id, text: body, tags });
            added += 1;
        }
        toast(`Restored ${added} note${added === 1 ? "" : "s"}.${skipped ? ` ${skipped} were already here or couldn't be read.` : ""}`);
        if (Store.signedIn) Store.sync();
    });
})();
